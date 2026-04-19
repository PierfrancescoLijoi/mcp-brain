import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime


_REPO_ROOT = os.environ.get("MCP_BRAIN_REPO", os.getcwd())
DB_PATH = Path(_REPO_ROOT) / ".brain" / "memory.db"

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
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            branch TEXT,
            wip TEXT,
            next_steps TEXT,
            saved_at TEXT DEFAULT (datetime('now'))
        );
    """)
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


def save_memory(project: str, level: int, category: str, content: str, score: float = 0.5):
    conn = get_connection()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO memories (project, level, category, content, score, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (project, level, category, content, score, now))
    conn.commit()
    conn.close()


def get_memories(project: str, level: int) -> list[dict]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM memories
        WHERE project = ? AND level = ?
        ORDER BY score DESC, updated_at DESC
    """, (project, level)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_session(project: str, branch: str, wip: str, next_steps: str):
    conn = get_connection()
    conn.execute("""
        INSERT INTO sessions (project, branch, wip, next_steps)
        VALUES (?, ?, ?, ?)
    """, (project, branch, wip, next_steps))
    conn.commit()
    conn.close()


def get_last_session(project: str) -> dict | None:
    conn = get_connection()
    row = conn.execute("""
        SELECT * FROM sessions
        WHERE project = ?
        ORDER BY saved_at DESC
        LIMIT 1
    """, (project,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_project(name: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM projects WHERE name = ?", (name,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None