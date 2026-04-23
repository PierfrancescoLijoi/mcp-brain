"""
Parser unified diff per conflict detection v2.

Parsa un patch in formato unified diff (quello che GitHub restituisce per
ogni file modificato in una PR) e ne estrae:

  - gli HUNK (range di linee modificate) con added/removed lines
  - i SIMBOLI toccati (function / class) per ogni hunk
  - i SIGNATURE CHANGES: funzioni pubbliche la cui signature cambia tra
    la versione vecchia e quella nuova — il tipo di conflitto più
    pericoloso perché rompe i caller

Supporta Python come primo citizen + JS/TS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ------------------------------------------------------------------
# Regex
# ------------------------------------------------------------------
HUNK_HEADER_RE = re.compile(
    r'^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@(.*)$'
)
DIFF_FILE_RE = re.compile(r'^diff --git a/(.+?) b/(.+?)$')

# Python
PY_FUNC_RE = re.compile(r'(?:^|\s)(?:async\s+)?def\s+(\w+)\s*\(([^)]*)\)')
PY_CLASS_RE = re.compile(r'(?:^|\s)class\s+(\w+)\s*(?:\(([^)]*)\))?')

# JS/TS (classic function + class + method shorthand: `name(params) {`)
JS_FUNC_RE = re.compile(r'(?:^|\s)(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)')
JS_CLASS_RE = re.compile(r'(?:^|\s)(?:export\s+)?class\s+(\w+)')


# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------
@dataclass
class Hunk:
    """Singolo hunk di un diff."""
    file: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    context_header: str = ''


# ------------------------------------------------------------------
# Parse
# ------------------------------------------------------------------
def parse_unified_diff(patch_text: str, fallback_file: str = '') -> List[Hunk]:
    """
    Parsa un patch unified diff. Se il patch NON contiene l'header
    `diff --git` (come i patch per singolo file ritornati dalla GitHub API),
    usa `fallback_file` come nome del file per tutti gli hunk.
    """
    hunks: List[Hunk] = []
    current_file = fallback_file
    current: Optional[Hunk] = None

    for line in (patch_text or '').splitlines():
        m = DIFF_FILE_RE.match(line)
        if m:
            current_file = m.group(2)
            continue

        m = HUNK_HEADER_RE.match(line)
        if m:
            if current is not None:
                hunks.append(current)
            current = Hunk(
                file=current_file,
                old_start=int(m.group(1)),
                old_count=int(m.group(2)) if m.group(2) else 1,
                new_start=int(m.group(3)),
                new_count=int(m.group(4)) if m.group(4) else 1,
                context_header=(m.group(5) or '').strip(),
            )
            continue

        if current is None:
            continue

        # +++/--- sono header di file, non righe added/removed
        if line.startswith('+++') or line.startswith('---'):
            continue
        if line.startswith('+'):
            current.added.append(line[1:])
        elif line.startswith('-'):
            current.removed.append(line[1:])
        # context lines (' ') ignorate

    if current is not None:
        hunks.append(current)
    return hunks


# ------------------------------------------------------------------
# Signature detection
# ------------------------------------------------------------------
def _lang_patterns(language: str):
    if language == 'python':
        return PY_FUNC_RE, PY_CLASS_RE
    if language in ('javascript', 'typescript', 'js', 'ts'):
        return JS_FUNC_RE, JS_CLASS_RE
    return None, None


def _extract_sigs(lines: List[str], func_re, class_re) -> Dict[str, Dict]:
    """Estrae signature (nome -> {kind, params}) da una lista di righe."""
    sigs: Dict[str, Dict] = {}
    for line in lines:
        m = func_re.search(line)
        if m:
            # Salta built-in/privati con singolo underscore iniziale? No, li
            # includiamo comunque: il conflict è utile anche su simboli privati
            sigs[m.group(1)] = {'kind': 'func', 'params': (m.group(2) or '').strip()}
            continue
        if class_re is not None:
            m = class_re.search(line)
            if m:
                groups = m.groups()
                params = groups[1] if len(groups) > 1 and groups[1] else ''
                sigs[m.group(1)] = {'kind': 'class', 'params': (params or '').strip()}
    return sigs


def detect_signature_changes(hunk: Hunk, language: str = 'python') -> List[Dict]:
    """
    Rileva differenze di signature tra righe removed e added dell'hunk.

    Ritorna lista di:
      {'symbol': str, 'change': 'signature'|'removed'|'added',
       'kind': 'func'|'class', 'before': str, 'after': str}

    - 'signature' → lo stesso simbolo appare in removed e added con param diversi
    - 'removed'   → simbolo solo in removed (funzione cancellata)
    - 'added'     → simbolo solo in added (funzione nuova; non è un conflict
                    ma lo tracciamo per completezza)
    """
    func_re, class_re = _lang_patterns(language)
    if func_re is None:
        return []

    removed_sigs = _extract_sigs(hunk.removed, func_re, class_re)
    added_sigs = _extract_sigs(hunk.added, func_re, class_re)

    changes: List[Dict] = []
    for name, rsig in removed_sigs.items():
        if name in added_sigs:
            asig = added_sigs[name]
            if asig['params'] != rsig['params'] or asig['kind'] != rsig['kind']:
                changes.append({
                    'symbol': name,
                    'change': 'signature',
                    'kind': rsig['kind'],
                    'before': rsig['params'],
                    'after': asig['params'],
                })
        else:
            changes.append({
                'symbol': name,
                'change': 'removed',
                'kind': rsig['kind'],
                'before': rsig['params'],
                'after': '',
            })

    for name, asig in added_sigs.items():
        if name not in removed_sigs:
            changes.append({
                'symbol': name,
                'change': 'added',
                'kind': asig['kind'],
                'before': '',
                'after': asig['params'],
            })

    return changes


# ------------------------------------------------------------------
# Touched symbols
# ------------------------------------------------------------------
def get_touched_symbols(
    hunk: Hunk,
    language: str = 'python',
    file_content_new: Optional[str] = None,
) -> List[str]:
    """
    Simboli (function/class) toccati da un hunk.

    Strategia (in ordine di preferenza):
      1. Context header del `@@ ... @@`: spesso contiene il nome della funzione
         contenente, es: `@@ -12,7 +12,7 @@ def verify_token(tok):`
      2. Definizioni presenti nelle righe added/removed (hunk definisce/modifica
         il simbolo stesso).
      3. Se `file_content_new` è fornito: fa tracking della funzione/classe che
         contiene la regione modificata (best-effort, ignora indentation).
    """
    func_re, class_re = _lang_patterns(language)
    if func_re is None:
        return []

    symbols = set()

    # 1) context header
    if hunk.context_header:
        m = func_re.search(hunk.context_header)
        if m:
            symbols.add(m.group(1))
        if class_re is not None:
            m = class_re.search(hunk.context_header)
            if m:
                symbols.add(m.group(1))

    # 2) righe del hunk che sono esse stesse def/class
    for line in list(hunk.added) + list(hunk.removed):
        m = func_re.search(line)
        if m:
            symbols.add(m.group(1))
        if class_re is not None:
            m = class_re.search(line)
            if m:
                symbols.add(m.group(1))

    # 3) tracking nel file completo: trova l'ultimo def/class che precede
    #    la regione modificata. Best-effort (non tiene indentation).
    if file_content_new:
        lines = file_content_new.splitlines()
        end = min(hunk.new_start + hunk.new_count - 1, len(lines))
        current = None
        for i in range(end):
            line = lines[i]
            m = func_re.search(line)
            if m:
                current = m.group(1)
                continue
            if class_re is not None:
                m = class_re.search(line)
                if m:
                    current = m.group(1)
        if current:
            symbols.add(current)

    return sorted(symbols)
