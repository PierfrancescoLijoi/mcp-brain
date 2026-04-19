from datetime import datetime, timezone, timedelta
from src.storage.db import get_connection

STALE_DAYS = 90
SUSPECT_DAYS = 60


def _parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def check_staleness(project: str) -> dict:
    '''
    Marca come stale/suspect le memorie:
    - non verificate da oltre STALE_DAYS
    - non verificate da oltre SUSPECT_DAYS
    Ritorna conteggio per stato.
    '''
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, last_verified_at, status FROM memories WHERE project = ? AND status IN ('active', 'suspect')",
        (project,)
    ).fetchall()

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    suspect_cutoff = now - timedelta(days=SUSPECT_DAYS)

    marked = {'stale': 0, 'suspect': 0, 'unchanged': 0}

    for row in rows:
        last_verified = _parse_date(row['last_verified_at'])
        if not last_verified:
            marked['unchanged'] += 1
            continue

        if last_verified.tzinfo is None:
            last_verified = last_verified.replace(tzinfo=timezone.utc)

        current_status = row['status']
        new_status = current_status

        if last_verified < stale_cutoff:
            new_status = 'stale'
        elif last_verified < suspect_cutoff:
            new_status = 'suspect'

        if new_status != current_status:
            conn.execute(
                "UPDATE memories SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (new_status, row['id'])
            )
            marked[new_status] += 1
        else:
            marked['unchanged'] += 1

    conn.commit()
    conn.close()
    return marked


def mark_superseded(project: str, old_content_prefix: str, new_memory_id: int):
    '''Marca come superseded le memory che contengono il prefix dato.'''
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE memories SET status = 'superseded', supersedes = ?, updated_at = datetime('now') WHERE project = ? AND content LIKE ? AND id != ? AND status = 'active'",
        (new_memory_id, project, f'%{old_content_prefix}%', new_memory_id)
    )
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count


def reactivate_memory(memory_id: int):
    '''Developer ri-verifica una memory stale/suspect. Torna active.'''
    conn = get_connection()
    conn.execute(
        "UPDATE memories SET status = 'active', last_verified_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (memory_id,)
    )
    conn.commit()
    conn.close()
