"""
STEP 5 — Schema delta e persistenza per feedback loop.

Aggiunge due tabelle e tre colonne al DB:

  TABLES:
    predictions_log       — ogni predizione di brain_get_ticket_context/brain_predict_files
    ticket_outcomes       — l'esito reale del ticket (commit/revert/abandoned)

  NEW COLUMNS on memories:
    hit_count             — quante volte la memoria ha "salvato" (true positive)
    miss_count            — quante volte ha generato un falso positivo
    last_outcome_at       — ISO timestamp dell'ultima riconciliazione

La migration è idempotente: safe da chiamare a ogni init_db() anche su DB
esistenti. `init_feedback_schema()` deve essere chiamato una volta in avvio.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.storage.db import get_connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------
# Migration
# ------------------------------------------------------------------
def init_feedback_schema() -> None:
    """Crea tabelle e colonne se non esistono. Idempotente."""
    conn = get_connection()

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS predictions_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            ticket_id INTEGER,
            author TEXT,
            predicted_files TEXT NOT NULL,   -- JSON array
            predicted_symbols TEXT,           -- JSON array (optional)
            memories_shown TEXT,              -- JSON array of memory_ids
            tool TEXT DEFAULT 'brain_get_ticket_context',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_pred_ticket ON predictions_log(project, ticket_id);

        CREATE TABLE IF NOT EXISTS ticket_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            ticket_id INTEGER NOT NULL,
            outcome TEXT NOT NULL,            -- 'completed' | 'reverted' | 'abandoned'
            actual_files TEXT,                -- JSON array of files committed
            commit_hash TEXT,
            pr_number INTEGER,
            duration_hours REAL,              -- optional
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_outcome_ticket ON ticket_outcomes(project, ticket_id);
        """
    )

    # Aggiunta colonne a memories (idempotent)
    cols_memories = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    feedback_cols = [
        ('hit_count', "ALTER TABLE memories ADD COLUMN hit_count INTEGER DEFAULT 0"),
        ('miss_count', "ALTER TABLE memories ADD COLUMN miss_count INTEGER DEFAULT 0"),
        ('last_outcome_at', "ALTER TABLE memories ADD COLUMN last_outcome_at TEXT"),
    ]
    for col, ddl in feedback_cols:
        if col not in cols_memories:
            try:
                conn.execute(ddl)
            except Exception:
                pass

    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Writes
# ------------------------------------------------------------------
def log_prediction(
    project: str,
    ticket_id: Optional[int],
    author: Optional[str],
    predicted_files: List[str],
    predicted_symbols: Optional[List[str]] = None,
    memories_shown: Optional[List[int]] = None,
    tool: str = 'brain_get_ticket_context',
) -> int:
    """Registra una predizione. Ritorna l'id del log entry."""
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO predictions_log
          (project, ticket_id, author, predicted_files, predicted_symbols,
           memories_shown, tool)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project,
            ticket_id,
            author,
            json.dumps(predicted_files or []),
            json.dumps(predicted_symbols or []),
            json.dumps(memories_shown or []),
            tool,
        ),
    )
    pred_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return pred_id


def record_outcome(
    project: str,
    ticket_id: int,
    outcome: str,
    actual_files: Optional[List[str]] = None,
    commit_hash: Optional[str] = None,
    pr_number: Optional[int] = None,
    duration_hours: Optional[float] = None,
    notes: Optional[str] = None,
) -> int:
    """
    Registra l'esito reale di un ticket.

    outcome ∈ {'completed', 'reverted', 'abandoned'}.
    """
    if outcome not in ('completed', 'reverted', 'abandoned'):
        raise ValueError(f"invalid outcome: {outcome!r}")

    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO ticket_outcomes
          (project, ticket_id, outcome, actual_files, commit_hash, pr_number,
           duration_hours, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project,
            ticket_id,
            outcome,
            json.dumps(actual_files or []),
            commit_hash,
            pr_number,
            duration_hours,
            notes,
        ),
    )
    outcome_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return outcome_id


# ------------------------------------------------------------------
# Reads
# ------------------------------------------------------------------
def get_prediction_for_ticket(
    project: str, ticket_id: int
) -> Optional[Dict[str, Any]]:
    """Ultima predizione loggata per un ticket. None se non esiste."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT * FROM predictions_log
        WHERE project = ? AND ticket_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (project, ticket_id),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d['predicted_files'] = json.loads(d.get('predicted_files') or '[]')
    d['predicted_symbols'] = json.loads(d.get('predicted_symbols') or '[]')
    d['memories_shown'] = json.loads(d.get('memories_shown') or '[]')
    return d


def get_outcomes_for_project(
    project: str, limit: int = 100
) -> List[Dict[str, Any]]:
    """Ultimi N outcome per un progetto, più recenti prima."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM ticket_outcomes
        WHERE project = ?
        ORDER BY id DESC LIMIT ?
        """,
        (project, limit),
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d['actual_files'] = json.loads(d.get('actual_files') or '[]')
        out.append(d)
    return out


def increment_memory_hit(memory_id: int) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE memories
        SET hit_count = COALESCE(hit_count, 0) + 1,
            last_outcome_at = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (_utc_now(), memory_id),
    )
    conn.commit()
    conn.close()


def increment_memory_miss(memory_id: int) -> None:
    conn = get_connection()
    conn.execute(
        """
        UPDATE memories
        SET miss_count = COALESCE(miss_count, 0) + 1,
            last_outcome_at = ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (_utc_now(), memory_id),
    )
    conn.commit()
    conn.close()


def get_memory_counters(memory_id: int) -> Dict[str, int]:
    conn = get_connection()
    row = conn.execute(
        "SELECT COALESCE(hit_count,0) as hit, COALESCE(miss_count,0) as miss "
        "FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {'hit': 0, 'miss': 0}
    return {'hit': row['hit'], 'miss': row['miss']}
