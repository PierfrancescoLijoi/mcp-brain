"""
Graduated conflict detection.

Severity dal più critico al meno critico:

  signature: il PR cambia la SIGNATURE di un simbolo pubblico.
             Chiunque usi quel simbolo si romperà. Merge semplice non basta:
             va coordinato a monte.
  hard     : stesso file + stesso simbolo toccato. Merge conflict quasi certo
             sulle stesse righe.
  soft     : stesso file ma simboli diversi. Merge conflict possibile ma
             risolvibile meccanicamente.

Input principale: `detect_graduated_conflicts` prende i file/symbols che il
mio ticket vuole toccare + le PR aperte CON i patch già fetchati.

Questo modulo NON parla con GitHub: il fetch è in `github_pr_patches.py`.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from src.brain.diff_parser import (
    parse_unified_diff,
    detect_signature_changes,
    get_touched_symbols,
)

# Peso ordinale per sorting
SEVERITY_ORDER = {'signature': 3, 'hard': 2, 'soft': 1, 'none': 0}


def _file_language(filename: str) -> str:
    fn = (filename or '').lower()
    if fn.endswith(('.py', '.pyi')):
        return 'python'
    if fn.endswith(('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs')):
        return 'javascript'
    return 'unknown'


def analyze_pr_file(filename: str, patch: str) -> Dict:
    """
    Parsa il patch di un singolo file di una PR. Ritorna:
      {
        'file': filename,
        'touched_symbols': [...],
        'signature_changes': [...],
        'hunks_count': N,
      }
    """
    language = _file_language(filename)
    hunks = parse_unified_diff(patch or '', fallback_file=filename)

    touched = set()
    sig_changes: List[Dict] = []

    for h in hunks:
        touched.update(get_touched_symbols(h, language=language))
        sig_changes.extend(detect_signature_changes(h, language=language))

    return {
        'file': filename,
        'touched_symbols': sorted(touched),
        'signature_changes': sig_changes,
        'hunks_count': len(hunks),
    }


def detect_graduated_conflicts(
    my_files: List[str],
    my_symbols: Optional[List[str]] = None,
    open_prs_with_patches: Optional[List[Dict]] = None,
    exclude_author: Optional[str] = None,
) -> List[Dict]:
    """
    Identifica conflitti graduated fra il mio ticket e le PR aperte.

    Input:
      my_files: file che voglio toccare
      my_symbols: simboli che voglio toccare (può essere vuoto: in quel caso
                  'hard' decade a 'soft', 'signature' resta se il PR cambia
                  signature di un simbolo pubblico nel file)
      open_prs_with_patches: list di
        {'number', 'author', 'title', 'files_with_patches': [{filename, patch, status}]}

    Output: lista di conflitti (ordinati per severity desc, poi pr asc), ciascuno:
      {
        'pr', 'author', 'title',
        'file',
        'severity': 'signature'|'hard'|'soft',
        'pr_touched_symbols': [...],
        'overlapping_symbols': [...],
        'signature_changes': [...],
        'message': str,
      }
    """
    my_files_set = set(my_files or [])
    my_symbols_set = set(my_symbols or [])

    conflicts: List[Dict] = []
    for pr in open_prs_with_patches or []:
        if exclude_author and pr.get('author') == exclude_author:
            continue

        pr_number = pr.get('number', 0)
        pr_author = pr.get('author', '?')
        pr_title = pr.get('title', '')

        for f in pr.get('files_with_patches', []) or []:
            filename = f.get('filename')
            if not filename or filename not in my_files_set:
                continue

            analysis = analyze_pr_file(filename, f.get('patch', ''))
            pr_symbols = set(analysis['touched_symbols'])
            sig_changes = analysis['signature_changes']

            # Un signature change è sempre severity=signature.
            # Le signature "added" (funzioni nuove) NON contano come conflict:
            # non c'è una API pre-esistente che viene rotta.
            breaking_sig = [
                c for c in sig_changes if c.get('change') in ('signature', 'removed')
            ]

            overlapping = sorted(pr_symbols & my_symbols_set) if my_symbols_set else []

            if breaking_sig:
                severity = 'signature'
                sig_list = ', '.join(f"{c['symbol']}()" for c in breaking_sig[:3])
                msg = (
                    f"PR #{pr_number} ({pr_author}) changes signature of "
                    f"{sig_list} in {filename}"
                )
            elif overlapping:
                severity = 'hard'
                msg = (
                    f"PR #{pr_number} ({pr_author}) touches same symbols "
                    f"({', '.join(overlapping[:3])}) in {filename}"
                )
            else:
                severity = 'soft'
                msg = (
                    f"PR #{pr_number} ({pr_author}) touches {filename}"
                    + (
                        f" (symbols: {', '.join(sorted(pr_symbols)[:3])})"
                        if pr_symbols else ' (different region)'
                    )
                )

            conflicts.append({
                'pr': pr_number,
                'author': pr_author,
                'title': pr_title,
                'file': filename,
                'severity': severity,
                'pr_touched_symbols': sorted(pr_symbols),
                'overlapping_symbols': overlapping,
                'signature_changes': sig_changes,
                'message': msg,
            })

    conflicts.sort(
        key=lambda c: (-SEVERITY_ORDER.get(c['severity'], 0), c.get('pr', 0))
    )
    return conflicts


def build_graduated_warnings(conflicts: List[Dict]) -> List[Dict]:
    """Versione compatta per output tool (niente liste lunghe di simboli)."""
    out = []
    for c in conflicts:
        entry = {
            'severity': c['severity'],
            'pr': c['pr'],
            'author': c['author'],
            'file': c['file'],
            'message': c['message'],
        }
        if c['severity'] == 'signature' and c.get('signature_changes'):
            entry['signature_changes'] = [
                {
                    'symbol': s['symbol'],
                    'kind': s['kind'],
                    'change': s['change'],
                    'before': s.get('before', ''),
                    'after': s.get('after', ''),
                }
                for s in c['signature_changes']
                if s.get('change') in ('signature', 'removed')
            ][:5]
        if c['severity'] == 'hard' and c.get('overlapping_symbols'):
            entry['overlapping_symbols'] = c['overlapping_symbols'][:5]
        out.append(entry)
    return out


def guidance_from_conflicts(conflicts: List[Dict]) -> str:
    """Messaggio sintetico su cosa fare a fronte dei conflitti."""
    if not conflicts:
        return 'No conflicts detected, safe to proceed'
    sev = {'signature': 0, 'hard': 0, 'soft': 0}
    for c in conflicts:
        sev[c['severity']] = sev.get(c['severity'], 0) + 1
    if sev['signature']:
        return (
            f"BLOCK: {sev['signature']} signature change(s) upstream — "
            "coordinate with PR author before modifying dependent code"
        )
    if sev['hard']:
        return (
            f"CAUTION: {sev['hard']} hard conflict(s) on same symbols — "
            "rebase or align with the open PR before editing"
        )
    return (
        f"NOTE: {sev['soft']} soft overlap(s) on same files — "
        "safe to proceed but review merge carefully"
    )
