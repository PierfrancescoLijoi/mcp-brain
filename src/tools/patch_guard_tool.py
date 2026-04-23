"""
STEP 6.1 — Tool MCP `brain_check_patch`.

Espone `patch_guard.check_patch` a Claude Code. L'output è YAML ottimizzato
per essere leggibile sia a umani che al modello. Claude deve chiamare QUESTO
tool prima di applicare un diff.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import yaml

from src.brain.patch_guard import check_patch


def _format_verdict(result: Dict[str, Any]) -> str:
    """Rende YAML compatto, raggruppando reasons per severity."""
    output: Dict[str, Any] = {
        'verdict': result['verdict'],
        'files_touched': result.get('files_touched', []),
        'symbols_changed': result.get('symbols_changed', []),
    }
    if result.get('breaking_signatures'):
        output['breaking_signatures'] = result['breaking_signatures']

    reasons = result.get('reasons', [])
    by_sev: Dict[str, List[Dict[str, Any]]] = {}
    for r in reasons:
        by_sev.setdefault(r['severity'], []).append(r)
    for sev in ('block', 'warn', 'info'):
        if by_sev.get(sev):
            output[sev] = by_sev[sev]

    # Summary one-liner
    if result['verdict'] == 'block':
        output['action'] = 'DO NOT apply this patch — address the block(s) first'
    elif result['verdict'] == 'warn':
        output['action'] = 'REVIEW warnings carefully before applying'
    else:
        output['action'] = 'Safe to apply'

    return yaml.dump(
        output, default_flow_style=False, allow_unicode=True, sort_keys=False
    ).strip()


def check_patch_impl(
    patch_text: str,
    project: str = '',
    target_file: Optional[str] = None,
) -> str:
    try:
        result = check_patch(
            patch_text=patch_text,
            project=project,
            target_file=target_file,
        )
        return _format_verdict(result)
    except Exception as e:
        logging.exception('brain_check_patch failed')
        return f'error: {e}'


def register_check_patch_tool(mcp) -> None:
    """Registra `brain_check_patch` sull'istanza FastMCP."""
    @mcp.tool()
    def brain_check_patch(
        project: str,
        patch: str,
        target_file: str = '',
    ) -> str:
        '''Safe edit guard: valida un unified-diff PRIMA di applicarlo.
        Ritorna YAML con verdict (block/warn/ok) + reasons raggruppate.
        Check: breaking signature (rompe caller nel graph), conflict con PR
        aperte sugli stessi simboli, violazioni di memorie (avoid/failed/pattern),
        alto impact radius. Claude deve chiamare QUESTO tool prima di qualunque
        edit non banale.'''
        start = time.time()
        logging.info(
            f'brain_check_patch START target={target_file!r} '
            f'patch_len={len(patch or "")}'
        )
        try:
            result = check_patch_impl(
                patch_text=patch or '',
                project=project,
                target_file=target_file or None,
            )
            logging.info(
                f'brain_check_patch END '
                f'({time.time() - start:.2f}s, {len(result)} chars)'
            )
            return result
        except Exception as e:
            logging.error(f'brain_check_patch FAILED: {e}', exc_info=True)
            return f'error: {e}'
