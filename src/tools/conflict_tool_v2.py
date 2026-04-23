"""
STEP 3 — Tool MCP `brain_check_conflicts_v2`.

Espone il conflict detector symbol-level con graduated severity.
Pattern di registrazione identico a predict_files_tool.
"""
from __future__ import annotations

import time
import logging
from typing import Any, Dict, List, Optional

import yaml

from src.brain.conflict_detector_v2 import (
    detect_graduated_conflicts,
    build_graduated_warnings,
    guidance_from_conflicts,
)


def _format_output(conflicts: List[Dict]) -> str:
    if not conflicts:
        return yaml.dump(
            {'conflicts': [], 'guidance': 'No conflicts detected, safe to proceed'},
            default_flow_style=False,
            sort_keys=False,
        ).strip()

    warnings = build_graduated_warnings(conflicts)

    # Raggruppa per severity per leggibilità
    by_sev: Dict[str, List[Dict]] = {'signature': [], 'hard': [], 'soft': []}
    for w in warnings:
        by_sev.setdefault(w['severity'], []).append(w)

    output: Dict[str, Any] = {}
    for sev in ('signature', 'hard', 'soft'):
        if by_sev.get(sev):
            output[sev] = by_sev[sev]
    output['guidance'] = guidance_from_conflicts(conflicts)

    return yaml.dump(
        output,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()


def check_conflicts_v2_impl(
    files: List[str],
    symbols: Optional[List[str]] = None,
    exclude_author: Optional[str] = None,
    prs_with_patches: Optional[List[Dict]] = None,
) -> str:
    """
    `prs_with_patches` è iniettabile per test. Se None, fa fetch live da GitHub.
    """
    try:
        if prs_with_patches is None:
            from src.capture.github_pr_patches import get_open_prs_with_patches
            prs_with_patches = get_open_prs_with_patches()

        conflicts = detect_graduated_conflicts(
            my_files=files or [],
            my_symbols=symbols or [],
            open_prs_with_patches=prs_with_patches,
            exclude_author=exclude_author,
        )
        return _format_output(conflicts)
    except Exception as e:
        logging.exception('brain_check_conflicts_v2 failed')
        return f'error: {e}'


def register_check_conflicts_v2_tool(mcp) -> None:
    """Registra il tool sull'istanza FastMCP."""
    @mcp.tool()
    def brain_check_conflicts_v2(
        project: str,
        files: list,
        symbols: list = None,
        author: str = None,
    ) -> str:
        '''Check graduated conflicts (signature / hard / soft) contro le PR aperte.
        Parsa i diff delle PR a livello di simbolo per individuare:
        - signature: PR cambia firma di una funzione pubblica (più critico)
        - hard: PR tocca gli stessi simboli che vuoi toccare
        - soft: PR tocca lo stesso file su regioni diverse
        Ritorna YAML raggruppato per severity + guidance testuale.'''
        start = time.time()
        logging.info(
            f'brain_check_conflicts_v2 START files={len(files or [])} '
            f'symbols={len(symbols or [])}'
        )
        try:
            result = check_conflicts_v2_impl(
                files=files or [],
                symbols=symbols or [],
                exclude_author=author,
            )
            logging.info(
                f'brain_check_conflicts_v2 END '
                f'({time.time() - start:.2f}s, {len(result)} chars)'
            )
            return result
        except Exception as e:
            logging.error(
                f'brain_check_conflicts_v2 FAILED: {e}', exc_info=True
            )
            return f'error: {e}'
