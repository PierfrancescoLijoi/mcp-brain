"""
Safe edit guard: valida un patch PRIMA che Claude lo applichi.

Idea: il patch è un unified diff (stesso formato di GitHub). Lo passiamo a
questo modulo e ci dice se è safe da applicare o se viola qualche invariante.

Check eseguiti (ordinati per severity decrescente):

  block:
    1. Il patch cambia la signature di una funzione pubblica che ha N>=1
       caller esterni nel code graph (rompere caller = breaking API).
    2. Il patch tocca un file hot che è in contesa con una PR aperta che
       sta cambiando la signature dello stesso simbolo.
    3. Il patch viola una memoria 'avoid' il cui scope matcha il file toccato.

  warn:
    4. Il patch tocca un file ad alto impact radius (>=10 dipendenti transitivi).
    5. Il patch viola una memoria 'failed' (approccio che è già fallito).
    6. Il patch rimuove una funzione pubblica referenziata altrove.

  info:
    7. Il patch viola una 'pattern' (informativo, non bloccante).
    8. Simboli aggiunti — log per trasparenza.

Output: dict con:
  {
    'verdict': 'block' | 'warn' | 'ok',
    'reasons': [{'severity': 'block'|'warn'|'info', 'message': str, ...}],
    'files_touched': [str],
    'symbols_changed': [str],
    'breaking_signatures': [str],
  }

Il tool NON applica mai il patch. Si limita a validarlo.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from src.brain.diff_parser import (
    parse_unified_diff,
    detect_signature_changes,
    get_touched_symbols,
)

# Soglia per "alto impact radius"
HIGH_IMPACT_TRANSITIVE_THRESHOLD = 10

# Soglia Jaccard per matching memorie "avoid"/"failed"/"pattern"
AVOID_MATCH_THRESHOLD = 0.25


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _file_language(filename: str) -> str:
    fn = (filename or '').lower()
    if fn.endswith(('.py', '.pyi')):
        return 'python'
    if fn.endswith(('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs')):
        return 'javascript'
    return 'unknown'


def _extract_files_from_patch(patch_text: str) -> List[str]:
    """Estrae i filename target dal patch. Supporta sia formato git-diff che
    solo-hunk con fallback_file."""
    files = set()
    for line in (patch_text or '').splitlines():
        m = re.match(r'^diff --git a/(.+?) b/(.+?)$', line)
        if m:
            files.add(m.group(2))
            continue
        m = re.match(r'^\+\+\+ b/(.+)$', line)
        if m and m.group(1) != '/dev/null':
            files.add(m.group(1))
    return sorted(files)


def _load_graph_safe():
    try:
        from src.brain.code_graph import load_graph
        return load_graph()
    except Exception:
        return None


def _load_avoid_memories_safe(project: str) -> List[Dict[str, Any]]:
    """Carica memorie 'avoid', 'failed', 'pattern' attive del progetto."""
    try:
        from src.storage.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT id, category, content, scope_type, scope_value
            FROM memories
            WHERE project = ? AND status = 'active'
              AND category IN ('avoid', 'failed', 'pattern')
            """,
            (project,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _memory_scope_matches_file(memory: Dict[str, Any], filename: str) -> bool:
    """True se lo scope della memoria si applica al file."""
    scope_type = memory.get('scope_type') or 'repo'
    scope_value = memory.get('scope_value') or ''

    if scope_type == 'repo':
        return True
    if not scope_value:
        return False
    sv = scope_value.lower()
    fn = (filename or '').lower()
    if scope_type == 'file':
        return sv == fn
    if scope_type == 'module':
        return fn.startswith(sv)
    return False


def _memory_content_matches_patch(memory_content: str, added_text: str) -> float:
    """Jaccard similarity tra memoria e testo aggiunto dal patch.

    Usa una tokenizzazione "gonfiata": oltre ai token normali, splitta
    snake_case e camelCase così `request_handlers_payload` matcha
    `request handlers`. Questo aumenta recall sul matching semantico delle
    memorie avoid/failed/pattern senza abbassare il threshold.
    """
    try:
        from src.brain.similarity import tokenize, jaccard
    except Exception:
        return 0.0

    def _expand(text: str) -> set:
        base = tokenize(text)
        expanded = set(base)
        for t in base:
            # snake_case → parti
            if '_' in t:
                expanded.update(p for p in t.split('_') if len(p) >= 3)
            # camelCase → parti lowercase
            camel_parts = re.findall(r'[a-z]+|[A-Z][a-z]*', t)
            expanded.update(p.lower() for p in camel_parts if len(p) >= 3)
        return expanded

    return jaccard(_expand(memory_content), _expand(added_text))


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def check_patch(
    patch_text: str,
    project: str = '',
    target_file: Optional[str] = None,
    graph: Optional[Dict[str, Any]] = None,
    memories: Optional[List[Dict[str, Any]]] = None,
    open_pr_conflicts: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Valida un patch unified-diff. Ritorna un verdict strutturato.

    Parametri iniettabili (se None → fetch live):
      graph: output di code_graph.load_graph()
      memories: lista memorie dal DB (avoid/failed/pattern)
      open_pr_conflicts: conflitti dalla conflict_detector_v2

    `target_file` è il file usato come fallback quando il patch non ha
    l'header `diff --git`.
    """
    reasons: List[Dict[str, Any]] = []

    if not patch_text or not patch_text.strip():
        return {
            'verdict': 'block',
            'reasons': [{'severity': 'block', 'code': 'empty_patch',
                         'message': 'patch is empty'}],
            'files_touched': [],
            'symbols_changed': [],
            'breaking_signatures': [],
        }

    # Files coinvolti: preferisci header diff --git, fallback a target_file
    files_from_patch = _extract_files_from_patch(patch_text)
    if not files_from_patch and target_file:
        files_from_patch = [target_file]

    if not files_from_patch:
        return {
            'verdict': 'block',
            'reasons': [{'severity': 'block', 'code': 'no_target_file',
                         'message': 'cannot determine target file from patch; '
                                    'pass target_file explicitly'}],
            'files_touched': [],
            'symbols_changed': [],
            'breaking_signatures': [],
        }

    # Lazy-load dependencies se non iniettate
    if graph is None:
        graph = _load_graph_safe()
    if memories is None:
        memories = _load_avoid_memories_safe(project) if project else []

    all_symbols_changed: List[str] = []
    breaking_sigs: List[str] = []

    # Parse per file
    per_file_hunks: Dict[str, List] = {}
    for f in files_from_patch:
        hunks = parse_unified_diff(patch_text, fallback_file=f)
        # Filtra per file corrente (nel caso di patch multi-file)
        per_file_hunks[f] = [h for h in hunks if h.file == f]

    # ---------- CHECK per ogni file ----------
    for filename, hunks in per_file_hunks.items():
        language = _file_language(filename)

        # Simboli + signature changes
        touched = set()
        sig_changes_file = []
        added_text_parts = []
        removed_text_parts = []

        for h in hunks:
            touched.update(get_touched_symbols(h, language=language))
            sig_changes_file.extend(detect_signature_changes(h, language=language))
            added_text_parts.extend(h.added)
            removed_text_parts.extend(h.removed)

        all_symbols_changed.extend(sorted(touched))

        added_text = '\n'.join(added_text_parts)
        removed_text = '\n'.join(removed_text_parts)

        # ---- 1. Signature breaking con caller esterni ----
        if graph and 'files' in graph:
            file_entry = graph['files'].get(filename, {})
            called_by = file_entry.get('called_by', [])
            # group callers per simbolo
            callers_per_symbol: Dict[str, List[str]] = {}
            for cb in called_by:
                callers_per_symbol.setdefault(cb.get('symbol', ''), []).append(
                    cb.get('file', '')
                )

            for sc in sig_changes_file:
                if sc['change'] not in ('signature', 'removed'):
                    continue
                sym = sc['symbol']
                callers = callers_per_symbol.get(sym, [])
                if callers:
                    breaking_sigs.append(sym)
                    reasons.append({
                        'severity': 'block',
                        'code': 'breaking_signature',
                        'message': (
                            f"{sc['change']} of '{sym}' in {filename} will break "
                            f"{len(callers)} caller(s)"
                        ),
                        'file': filename,
                        'symbol': sym,
                        'change': sc['change'],
                        'before': sc.get('before', ''),
                        'after': sc.get('after', ''),
                        'callers': callers[:5],
                    })
                elif sc['change'] == 'signature':
                    # Public-looking signature change ma nessun caller tracciato:
                    # warn (potrebbe avere caller non tracciati esterni al repo)
                    reasons.append({
                        'severity': 'warn',
                        'code': 'signature_change_no_callers_tracked',
                        'message': (
                            f"signature of '{sym}' changed in {filename}; "
                            f"no internal callers found (external/dynamic callers?)"
                        ),
                        'file': filename,
                        'symbol': sym,
                    })

        # ---- 2. Conflict con PR aperte sullo stesso simbolo ----
        if open_pr_conflicts:
            for conf in open_pr_conflicts:
                if conf.get('file') != filename:
                    continue
                if conf.get('severity') != 'signature':
                    continue
                pr_sig_syms = [
                    s.get('symbol')
                    for s in (conf.get('signature_changes') or [])
                    if s.get('change') in ('signature', 'removed')
                ]
                overlap = set(pr_sig_syms) & touched
                if overlap:
                    reasons.append({
                        'severity': 'block',
                        'code': 'contending_signature_pr',
                        'message': (
                            f"PR #{conf.get('pr')} by {conf.get('author')} is "
                            f"changing signature of {sorted(overlap)} in {filename}"
                        ),
                        'file': filename,
                        'pr': conf.get('pr'),
                        'symbols': sorted(overlap),
                    })

        # ---- 3. Memorie avoid / failed / pattern ----
        for mem in memories or []:
            if not _memory_scope_matches_file(mem, filename):
                continue
            cat = mem.get('category')
            sim = _memory_content_matches_patch(mem.get('content', ''), added_text)
            if sim < AVOID_MATCH_THRESHOLD:
                continue

            if cat == 'avoid':
                sev = 'block'
            elif cat == 'failed':
                sev = 'warn'
            else:  # pattern
                sev = 'info'

            reasons.append({
                'severity': sev,
                'code': f'violates_{cat}',
                'message': (
                    f"patch may violate {cat} memory #{mem.get('id')} "
                    f"(similarity={sim:.2f}) in {filename}"
                ),
                'file': filename,
                'memory_id': mem.get('id'),
                'memory_content': (mem.get('content') or '')[:160],
                'similarity': round(sim, 3),
            })

        # ---- 4. High impact radius ----
        if graph and 'files' in graph:
            try:
                from src.brain.code_graph import get_impact_radius
                radius = get_impact_radius(graph, filename, max_hops=3)
                transitive = len(radius.get('transitive', []))
                direct = len(radius.get('direct', []))
                total = direct + transitive
                if total >= HIGH_IMPACT_TRANSITIVE_THRESHOLD:
                    reasons.append({
                        'severity': 'warn',
                        'code': 'high_impact_radius',
                        'message': (
                            f"{filename} has high impact radius "
                            f"({direct} direct + {transitive} transitive dependents)"
                        ),
                        'file': filename,
                        'direct': direct,
                        'transitive': transitive,
                    })
            except Exception:
                pass

    # ---------- Verdict ----------
    sev_order = {'block': 3, 'warn': 2, 'info': 1}
    reasons.sort(key=lambda r: -sev_order.get(r['severity'], 0))

    if any(r['severity'] == 'block' for r in reasons):
        verdict = 'block'
    elif any(r['severity'] == 'warn' for r in reasons):
        verdict = 'warn'
    else:
        verdict = 'ok'

    return {
        'verdict': verdict,
        'reasons': reasons,
        'files_touched': sorted(files_from_patch),
        'symbols_changed': sorted(set(all_symbols_changed)),
        'breaking_signatures': sorted(set(breaking_sigs)),
    }
