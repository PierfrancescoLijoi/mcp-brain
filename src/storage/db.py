import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime, timezone

from src.storage.paths import DB_PATH, ensure_dirs
ensure_dirs()


def _utc_now_iso() -> str:
    """ISO 8601 UTC timezone-aware (sostituisce datetime.utcnow() deprecato)."""
    return datetime.now(timezone.utc).isoformat()


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL,
            stack TEXT,
            conventions TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            level INTEGER NOT NULL CHECK(level IN (1, 2, 3)),
            category TEXT NOT NULL,
            content TEXT NOT NULL,
            score REAL DEFAULT 0.5,
            status TEXT DEFAULT 'active',
            confidence TEXT DEFAULT 'medium',
            source TEXT DEFAULT 'manual',
            scope TEXT DEFAULT 'repo',
            scope_type TEXT DEFAULT 'repo',
            scope_value TEXT,
            supersedes INTEGER,
            last_verified_at TEXT DEFAULT (datetime('now')),
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS raw_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            commit_hash TEXT,
            branch TEXT,
            message TEXT NOT NULL,
            files TEXT,
            classification TEXT,
            promoted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            branch TEXT,
            wip TEXT,
            next_steps TEXT,
            saved_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(project, status);
        CREATE INDEX IF NOT EXISTS idx_raw_promoted ON raw_events(project, promoted);
    """)

    cols_memories = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    migrations = [
        ('status', "ALTER TABLE memories ADD COLUMN status TEXT DEFAULT 'active'"),
        ('confidence', "ALTER TABLE memories ADD COLUMN confidence TEXT DEFAULT 'medium'"),
        ('source', "ALTER TABLE memories ADD COLUMN source TEXT DEFAULT 'manual'"),
        ('scope', "ALTER TABLE memories ADD COLUMN scope TEXT DEFAULT 'repo'"),
        ('scope_type', "ALTER TABLE memories ADD COLUMN scope_type TEXT DEFAULT 'repo'"),
        ('scope_value', "ALTER TABLE memories ADD COLUMN scope_value TEXT"),
        ('supersedes', "ALTER TABLE memories ADD COLUMN supersedes INTEGER"),
        ('last_verified_at', "ALTER TABLE memories ADD COLUMN last_verified_at TEXT"),
    ]
    for col, ddl in migrations:
        if col not in cols_memories:
            try:
                conn.execute(ddl)
            except Exception:
                pass

    conn.commit()
    conn.close()


def save_project(name: str, path: str, stack: list, conventions: dict):
    conn = get_connection()
    conn.execute("""
        INSERT INTO projects (name, path, stack, conventions)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            path=excluded.path,
            stack=excluded.stack,
            conventions=excluded.conventions
    """, (name, path, json.dumps(stack), json.dumps(conventions)))
    conn.commit()
    conn.close()


def save_memory(project: str, level: int, category: str, content: str,
                score: float = 0.5, status: str = 'active',
                confidence: str = 'medium', source: str = 'manual',
                scope_type: str = 'repo', scope_value: str = None,
                supersedes: int = None):
    conn = get_connection()
    now = _utc_now_iso()
    conn.execute("""
        INSERT INTO memories
          (project, level, category, content, score, status, confidence,
           source, scope, scope_type, scope_value, supersedes, last_verified_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (project, level, category, content, score, status, confidence,
          source, scope_type, scope_type, scope_value, supersedes, now, now))
    conn.commit()
    conn.close()


def get_memories(project: str, level: int, only_active: bool = True) -> list:
    conn = get_connection()
    if only_active:
        rows = conn.execute("""
            SELECT * FROM memories
            WHERE project = ? AND level = ? AND status = 'active'
            ORDER BY score DESC, updated_at DESC
        """, (project, level)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM memories
            WHERE project = ? AND level = ?
            ORDER BY score DESC, updated_at DESC
        """, (project, level)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_memory_status(memory_id: int, status: str):
    conn = get_connection()
    conn.execute("UPDATE memories SET status = ?, updated_at = datetime('now') WHERE id = ?",
                 (status, memory_id))
    conn.commit()
    conn.close()


def verify_memory(memory_id: int):
    conn = get_connection()
    conn.execute("UPDATE memories SET last_verified_at = datetime('now') WHERE id = ?",
                 (memory_id,))
    conn.commit()
    conn.close()


def save_raw_event(project: str, commit_hash: str, branch: str,
                   message: str, files: list, classification: str) -> int:
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO raw_events (project, commit_hash, branch, message, files, classification)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (project, commit_hash, branch, message, json.dumps(files), classification))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id


def get_raw_events(project: str, promoted: bool = None) -> list:
    conn = get_connection()
    if promoted is None:
        rows = conn.execute(
            "SELECT * FROM raw_events WHERE project = ? ORDER BY created_at DESC",
            (project,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM raw_events WHERE project = ? AND promoted = ? ORDER BY created_at DESC",
            (project, 1 if promoted else 0)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_raw_promoted(event_id: int):
    conn = get_connection()
    conn.execute("UPDATE raw_events SET promoted = 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def save_session(project: str, branch: str, wip: str, next_steps: str):
    conn = get_connection()
    conn.execute("""
        INSERT INTO sessions (project, branch, wip, next_steps)
        VALUES (?, ?, ?, ?)
    """, (project, branch, wip, next_steps))
    conn.commit()
    conn.close()


def get_last_session(project: str) -> dict:
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM sessions WHERE project = ?
        ORDER BY saved_at DESC LIMIT 1
    """, (project,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_project(name: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def count_similar_patterns(project: str, content_prefix: str) -> int:
    conn = get_connection()
    result = conn.execute("""
        SELECT COUNT(*) FROM raw_events
        WHERE project = ? AND message LIKE ?
    """, (project, f'{content_prefix}%')).fetchone()
    conn.close()
    return result[0] if result else 0
