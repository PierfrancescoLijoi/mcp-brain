"""
Similar past tickets retrieval.

Trova ticket/PR passati simili al ticket corrente. Il "simile" è definito su
due dimensioni, e uniamo i risultati:

1. Text similarity (titoli/body) — riusiamo `similarity.find_similar_memories`
   che usa Jaccard sui token (stessa pipeline di `semantic_supersede`).

2. File overlap — se conosciamo già i file predetti dal ticket corrente,
   un PR passato che ha toccato quegli stessi file è altamente informativo
   (magari ha la stessa struttura del fix).

La sorgente dati sono le **memorie SQLite** del brain: ogni `brain_start_ticket`
ha storicamente scritto memorie con prefisso "ticket #N:". In più leggiamo
anche le memorie di categoria 'decision', 'pattern', 'failed' che citano il
ticket-id — sono spesso il "come l'ho risolto ieri" più utile.

NIENTE GitHub API: tutto locale, zero round-trip.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from src.brain.similarity import tokenize, jaccard


# ------------------------------------------------------------------
# Loader
# ------------------------------------------------------------------
def _load_past_ticket_memories(
    project: str,
    exclude_ticket_id: Optional[int] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Carica dal DB le memorie plausibilmente legate a ticket passati.

    Criterio: memorie con categoria in ('decision', 'pattern', 'failed')
    o il cui content contiene 'ticket #' / 'issue #'. Escludiamo 'superseded'
    e 'stale' per avere solo segnale fresco.
    """
    try:
        from src.storage.db import get_connection
    except Exception:
        return []

    try:
        conn = get_connection()
        rows = conn.execute(
            """
            SELECT id, category, content, status, created_at,
                   scope_type, scope_value
            FROM memories
            WHERE project = ?
              AND status IN ('active', 'suspect')
              AND (
                   category IN ('decision', 'pattern', 'failed')
                   OR content LIKE '%ticket #%'
                   OR content LIKE '%issue #%'
                   OR content LIKE '%PR #%'
              )
            ORDER BY id DESC
            LIMIT ?
            """,
            (project, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ------------------------------------------------------------------
# Ticket id extraction
# ------------------------------------------------------------------
_TICKET_ID_RE = re.compile(r'(?:ticket|issue|PR)\s*#?\s*(\d+)', re.IGNORECASE)


def _extract_ticket_id(content: str) -> Optional[int]:
    if not content:
        return None
    m = _TICKET_ID_RE.search(content)
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------
# Scoring
# ------------------------------------------------------------------
def _text_similarity(query_text: str, memory_content: str) -> float:
    return jaccard(tokenize(query_text), tokenize(memory_content))


def _file_overlap_bonus(
    predicted_files: List[str],
    memory: Dict[str, Any],
) -> float:
    """
    Bonus se la memoria è scope-taggata su un file/module che è nei predicted_files.
    Range [0.0, 0.2].
    """
    if not predicted_files:
        return 0.0
    scope_value = memory.get('scope_value') or ''
    if not scope_value:
        return 0.0
    scope_value_lower = scope_value.lower()
    for f in predicted_files:
        fl = f.lower()
        if scope_value_lower == fl or scope_value_lower in fl or fl in scope_value_lower:
            return 0.2
    return 0.0


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------
def find_similar_tickets(
    project: str,
    title: str,
    body: str = '',
    predicted_files: Optional[List[str]] = None,
    exclude_ticket_id: Optional[int] = None,
    top_k: int = 5,
    threshold: float = 0.2,
    memories: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Trova i ticket/memorie storici più simili a (title, body).

    Ritorna list of:
      {
        'memory_id': int,
        'category': 'decision'|'pattern'|'failed'|...,
        'content': str,
        'ticket_id': int | None,      # se estraibile dal content
        'similarity': float (0..1),   # text similarity + file bonus
        'scope_type': str,
        'scope_value': str,
        'created_at': str,
      }

    Ordinati per similarity desc, filtrati sotto `threshold`.

    `memories` è iniettabile per test (no-DB).
    """
    query_text = f'{title or ""} {body or ""}'.strip()
    if not query_text:
        return []

    mems = memories if memories is not None else _load_past_ticket_memories(
        project, exclude_ticket_id=exclude_ticket_id
    )
    if not mems:
        return []

    scored = []
    for m in mems:
        content = m.get('content', '') or ''
        mem_ticket = _extract_ticket_id(content)
        if exclude_ticket_id is not None and mem_ticket == exclude_ticket_id:
            continue

        text_sim = _text_similarity(query_text, content)
        file_bonus = _file_overlap_bonus(predicted_files or [], m)
        total = min(1.0, text_sim + file_bonus)

        if total < threshold:
            continue

        scored.append({
            'memory_id': m.get('id'),
            'category': m.get('category'),
            'content': content,
            'ticket_id': mem_ticket,
            'similarity': round(total, 3),
            'text_similarity': round(text_sim, 3),
            'file_bonus': round(file_bonus, 3),
            'scope_type': m.get('scope_type'),
            'scope_value': m.get('scope_value'),
            'created_at': m.get('created_at'),
        })

    scored.sort(key=lambda x: x['similarity'], reverse=True)
    return scored[:top_k]
