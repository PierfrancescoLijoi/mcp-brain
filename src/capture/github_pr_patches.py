"""
Fetch GitHub PR patches. Separato da `github_reader.list_open_prs` per due motivi:

  1. Fetchare i patch è pesante: 1 extra round-trip per file vs 1 per PR.
  2. La cache ha TTL diverso (10 min) e viene usata solo dal conflict detector v2.

Se GITHUB_TOKEN non è settato o la PR API fallisce → ritorna `[]` graceful.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

_TTL = 600  # 10 min
_cache = {'data': None, 'ts': 0}


def _cache_valid() -> bool:
    return _cache['data'] is not None and (time.time() - _cache['ts']) < _TTL


def get_open_prs_with_patches(force_refresh: bool = False) -> List[Dict]:
    """
    Ritorna tutte le PR aperte (recenti) con i patch dei file modificati.

    Struttura:
      [
        {
          'number': int,
          'title': str,
          'author': str,
          'branch': str,
          'updated_at': str,
          'files_with_patches': [
            {'filename': str, 'status': str, 'patch': str},
            ...
          ],
        },
        ...
      ]

    Fallback graceful: ogni eccezione (token mancante, rate limit, rete) →
    ritorna lista vuota. Il conflict detector si comporterà come se non ci
    fossero PR aperte.
    """
    if not force_refresh and _cache_valid():
        return _cache['data']  # type: ignore[return-value]

    if not os.environ.get('GITHUB_TOKEN'):
        # Niente token = niente fetch (evita tracebacks in log durante dev)
        _cache['data'] = []
        _cache['ts'] = time.time()
        return []

    try:
        # Import locale per non penalizzare i moduli che non usano GitHub
        from src.capture.github_reader import _get_repo, MAX_PRS, RECENT_DAYS

        repo = _get_repo()
        prs: List[Dict] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)

        for pr in repo.get_pulls(state='open', sort='updated', direction='desc'):
            updated = pr.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated < cutoff:
                break
            if len(prs) >= MAX_PRS:
                break

            files_with_patches: List[Dict] = []
            for f in pr.get_files():
                files_with_patches.append({
                    'filename': f.filename,
                    'status': f.status,
                    'patch': getattr(f, 'patch', '') or '',
                })

            prs.append({
                'number': pr.number,
                'title': pr.title,
                'author': pr.user.login,
                'branch': pr.head.ref,
                'updated_at': updated.isoformat(),
                'files_with_patches': files_with_patches,
            })

        _cache['data'] = prs
        _cache['ts'] = time.time()
        return prs
    except Exception:
        # Fallback silenzioso (coerente con github_reader.list_open_prs)
        _cache['data'] = []
        _cache['ts'] = time.time()
        return []


def clear_cache() -> None:
    _cache['data'] = None
    _cache['ts'] = 0
