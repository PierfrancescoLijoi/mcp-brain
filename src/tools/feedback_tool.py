"""
STEP 5 — Tool MCP per il feedback loop.

Tre tool:
  brain_record_outcome    — quando il ticket si chiude, ne registri l'esito
  brain_feedback_stats    — report aggregato precision/recall ultimi N giorni
  brain_memory_health     — hit/miss count per memoria, utile per debugging

Il LOG delle predizioni è automatico: viene fatto dentro `ticket_context_tool`.
Il tool qui sotto serve solo per OUTCOME + reporting.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import yaml

from src.brain.feedback_store import (
    init_feedback_schema,
    record_outcome,
    get_outcomes_for_project,
)
from src.brain.feedback_reconciler import reconcile, get_feedback_stats


def record_outcome_impl(
    project: str,
    ticket_id: int,
    outcome: str,
    actual_files: Optional[List[str]] = None,
    commit_hash: Optional[str] = None,
    pr_number: Optional[int] = None,
    notes: Optional[str] = None,
) -> str:
    try:
        init_feedback_schema()
        record_outcome(
            project=project,
            ticket_id=ticket_id,
            outcome=outcome,
            actual_files=actual_files or [],
            commit_hash=commit_hash,
            pr_number=pr_number,
            notes=notes,
        )
        report = reconcile(
            project=project,
            ticket_id=ticket_id,
            outcome=outcome,
            actual_files=actual_files or [],
        )
        return yaml.dump(
            {'outcome_recorded': report},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ).strip()
    except Exception as e:
        logging.exception('brain_record_outcome failed')
        return f'error: {e}'


def feedback_stats_impl(project: str, since_days: int = 30) -> str:
    try:
        init_feedback_schema()
        stats = get_feedback_stats(project, since_days=since_days)
        return yaml.dump(
            {'feedback_stats': stats},
            default_flow_style=False, sort_keys=False,
        ).strip()
    except Exception as e:
        logging.exception('brain_feedback_stats failed')
        return f'error: {e}'


def memory_health_impl(project: str, top_k: int = 20) -> str:
    """Memorie del progetto con hit/miss count. Aiuta il debug delle memorie rumorose."""
    try:
        from src.storage.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT id, category, status, content,
                   COALESCE(hit_count, 0) as hit,
                   COALESCE(miss_count, 0) as miss,
                   score
            FROM memories
            WHERE project = ?
              AND (hit_count > 0 OR miss_count > 0)
            ORDER BY (miss_count - hit_count) DESC, id DESC
            LIMIT ?
            """,
            (project, top_k),
        ).fetchall()
        conn.close()
        mems = [{
            'id': r['id'],
            'category': r['category'],
            'status': r['status'],
            'score': r['score'],
            'hit': r['hit'],
            'miss': r['miss'],
            'delta': r['miss'] - r['hit'],
            'content': (r['content'] or '')[:120],
        } for r in rows]
        return yaml.dump(
            {'memory_health': mems or 'no feedback data yet'},
            default_flow_style=False, sort_keys=False, allow_unicode=True,
        ).strip()
    except Exception as e:
        logging.exception('brain_memory_health failed')
        return f'error: {e}'


def register_feedback_tools(mcp) -> None:
    """Registra i 3 tool del feedback loop su FastMCP."""

    @mcp.tool()
    def brain_record_outcome(
        project: str,
        ticket_id: int,
        outcome: str,
        actual_files: list = None,
        commit_hash: str = '',
        pr_number: int = 0,
        notes: str = '',
    ) -> str:
        '''Registra l'esito di un ticket (completed/reverted/abandoned) e
        chiude il ciclo predizione→feedback. Calcola precision/recall delle
        predizioni, aggiorna hit/miss dei memory mostrati, e auto-tara i
        memory rumorosi (demote a suspect dopo 3+ miss consecutivi).'''
        start = time.time()
        logging.info(
            f'brain_record_outcome START ticket={ticket_id} outcome={outcome}'
        )
        try:
            result = record_outcome_impl(
                project=project,
                ticket_id=ticket_id,
                outcome=outcome,
                actual_files=actual_files or [],
                commit_hash=commit_hash or None,
                pr_number=pr_number if pr_number else None,
                notes=notes or None,
            )
            logging.info(
                f'brain_record_outcome END ({time.time() - start:.2f}s)'
            )
            return result
        except Exception as e:
            logging.error(f'brain_record_outcome FAILED: {e}', exc_info=True)
            return f'error: {e}'

    @mcp.tool()
    def brain_feedback_stats(project: str, since_days: int = 30) -> str:
        '''Report aggregato precision/recall/outcome count per un progetto,
        finestra mobile in giorni. Usato per monitorare la qualità delle
        predizioni nel tempo.'''
        return feedback_stats_impl(project, since_days=since_days)

    @mcp.tool()
    def brain_memory_health(project: str, top_k: int = 20) -> str:
        '''Classifica le memorie per impatto sui risultati (miss - hit).
        Le memorie in cima sono quelle che generano più falsi positivi:
        candidate al retiring manuale se il sistema non le demote da solo.'''
        return memory_health_impl(project, top_k=top_k)
