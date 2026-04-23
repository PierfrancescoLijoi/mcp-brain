"""
STEP 7 — Tool MCP `brain_observability`: dashboard unificata.

Aggrega in un unico YAML:
  - tool metrics (count, latency p50/p95, errors) — da STEP 7 in-memory
  - feedback stats (precision/recall finestra N giorni) — da STEP 5
  - code graph stats (total files, symbols, build time) — da STEP 1
  - index stats (total files, terms, avgdl) — da STEP 2.1
  - memory health counts (active/suspect/superseded)
  - system info (python, pid, uptime)

Output compatto, pensato per essere letto da Claude e/o inserito in una CI.
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import yaml

from src.brain.observability import get_snapshot, observed


_PROCESS_START = time.time()


# ------------------------------------------------------------------
# Collectors — each fallback-safe, never raise
# ------------------------------------------------------------------
def _collect_tool_metrics() -> Dict[str, Any]:
    try:
        snap = get_snapshot()
        # Ordina per count desc per avere i tool più usati in cima
        return dict(sorted(snap.items(), key=lambda kv: -kv[1].get('count', 0)))
    except Exception:
        return {}


def _collect_feedback_stats(project: str, since_days: int) -> Optional[Dict[str, Any]]:
    try:
        from src.brain.feedback_store import init_feedback_schema
        from src.brain.feedback_reconciler import get_feedback_stats
        init_feedback_schema()
        return get_feedback_stats(project, since_days=since_days)
    except Exception:
        return None


def _collect_graph_stats() -> Optional[Dict[str, Any]]:
    try:
        from src.brain.code_graph import load_graph
        g = load_graph()
        if not g:
            return {'present': False}
        stats = dict(g.get('stats') or {})
        stats['present'] = True
        return stats
    except Exception:
        return None


def _collect_index_stats() -> Optional[Dict[str, Any]]:
    try:
        from src.brain.file_indexer import load_index
        idx = load_index()
        if not idx:
            return {'present': False}
        return {
            'present': True,
            'total_files': idx.get('total', 0),
            'unique_terms': len(idx.get('df', {})),
            'avgdl': round(idx.get('avgdl', 0.0), 2),
            'built_at': idx.get('built_at'),
        }
    except Exception:
        return None


def _collect_memory_stats(project: str) -> Optional[Dict[str, Any]]:
    """Conteggio memorie per status + top 5 per hit_count."""
    try:
        from src.storage.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT status, COUNT(*) AS n
            FROM memories
            WHERE project = ?
            GROUP BY status
            """,
            (project,),
        ).fetchall()
        by_status = {r['status']: r['n'] for r in rows}

        # Top hit memorie (se STEP 5 installato)
        top_hits = []
        try:
            rows2 = conn.execute(
                """
                SELECT id, category, content, hit_count, miss_count
                FROM memories
                WHERE project = ? AND COALESCE(hit_count, 0) > 0
                ORDER BY hit_count DESC, id DESC LIMIT 5
                """,
                (project,),
            ).fetchall()
            top_hits = [{
                'id': r['id'],
                'category': r['category'],
                'hit': r['hit_count'] or 0,
                'miss': r['miss_count'] or 0,
                'content': (r['content'] or '')[:80],
            } for r in rows2]
        except Exception:
            # hit_count/miss_count colonne mancanti → STEP 5 non installato
            pass

        conn.close()
        return {
            'by_status': by_status,
            'top_hit_memories': top_hits,
        }
    except Exception:
        return None


def _collect_system_info() -> Dict[str, Any]:
    return {
        'python': sys.version.split()[0],
        'pid': os.getpid(),
        'uptime_seconds': int(time.time() - _PROCESS_START),
        'json_logs': os.environ.get('MCP_BRAIN_JSON_LOGS', '0') == '1',
        'semantic_enabled': os.environ.get('MCP_BRAIN_SEMANTIC', '1') != '0',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------------------------------------------
# Impl
# ------------------------------------------------------------------
def observability_impl(project: str, since_days: int = 30) -> str:
    try:
        report: Dict[str, Any] = {
            'system': _collect_system_info(),
            'tools': _collect_tool_metrics() or 'no tool calls recorded yet',
        }

        graph = _collect_graph_stats()
        if graph is not None:
            report['code_graph'] = graph

        idx = _collect_index_stats()
        if idx is not None:
            report['file_index'] = idx

        mem = _collect_memory_stats(project)
        if mem is not None:
            report['memories'] = mem

        fb = _collect_feedback_stats(project, since_days)
        if fb is not None:
            report['feedback'] = fb

        return yaml.dump(
            report,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ).strip()
    except Exception as e:
        logging.exception('brain_observability failed')
        return f'error: {e}'


# ------------------------------------------------------------------
# Registration + wrapping utility
# ------------------------------------------------------------------
def register_observability_tool(mcp) -> None:
    """Registra `brain_observability` sull'istanza FastMCP."""
    @mcp.tool()
    @observed('brain_observability')
    def brain_observability(project: str, since_days: int = 30) -> str:
        '''Dashboard unificata: tool metrics (latency p50/p95, error rate),
        feedback stats (precision/recall ultimi N giorni), code graph stats,
        file index stats, memory counters, system info. Usa per diagnosi
        runtime e health check del brain.'''
        return observability_impl(project, since_days=since_days)


def auto_instrument_existing_tools(mcp) -> int:
    """
    Avvolge con `@observed` i tool già registrati sull'istanza FastMCP
    (quelli registrati PRIMA che questo si chiami). Non touch di quelli
    nuovi che useranno `@observed` direttamente.

    Ritorna il numero di tool istrumentati. Idempotente: se un tool è già
    stato istrumentato (attributo `_mcpb_observed`), viene saltato.

    La strategia varia in base alla versione di FastMCP. Cerchiamo:
      - `mcp._tool_manager._tools` (FastMCP recente)
      - `mcp._tools` (versioni vecchie)
      - `mcp.tools` (fallback)

    Se nessuno di questi esiste, ritorna 0 senza crash: l'istrumentazione
    resta manuale e il tool `brain_observability` funziona comunque (gli
    altri tool semplicemente non appariranno in `tools` finché non si
    istrumentano manualmente).
    """
    registry = None
    for attr_path in (
        ('_tool_manager', '_tools'),
        ('_tool_manager', 'tools'),
        ('_tools',),
        ('tools',),
    ):
        try:
            obj: Any = mcp
            for name in attr_path:
                obj = getattr(obj, name)
            if isinstance(obj, dict):
                registry = obj
                break
        except Exception:
            continue

    if not registry:
        return 0

    count = 0
    for tool_name, tool_entry in list(registry.items()):
        # Gli entry possono essere callable diretti o oggetti con attributo .fn
        target = None
        attr_to_set = None
        for attr in ('fn', 'func', 'handler', 'callable'):
            if hasattr(tool_entry, attr):
                target = getattr(tool_entry, attr)
                attr_to_set = attr
                break
        if target is None and callable(tool_entry):
            target = tool_entry

        if target is None or getattr(target, '_mcpb_observed', False):
            continue

        wrapped = observed(tool_name)(target)
        wrapped._mcpb_observed = True  # type: ignore[attr-defined]

        try:
            if attr_to_set:
                setattr(tool_entry, attr_to_set, wrapped)
            else:
                registry[tool_name] = wrapped
            count += 1
        except Exception:
            continue

    return count
