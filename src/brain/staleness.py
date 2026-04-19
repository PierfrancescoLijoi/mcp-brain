from datetime import datetime, timezone, timedelta
from src.storage.db import get_connection

STALE_DAYS = 90
SUSPECT_DAYS = 60
HIGH_CHANGE_THRESHOLD = 5
RECENT_WINDOW_DAYS = 30


def _parse_date(s: str):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _get_recent_commit_files(days: int = RECENT_WINDOW_DAYS) -> set:
    """Returns set of files touched in the last N days via git."""
    try:
        from src.capture.git_reader import _get_repo
        repo = _get_repo()
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        files = set()
        for commit in repo.iter_commits('HEAD', max_count=200):
            if commit.committed_datetime.replace(tzinfo=timezone.utc) < cutoff:
                break
            try:
                for f in commit.stats.files.keys():
                    files.add(f)
            except Exception:
                continue
        return files
    except Exception:
        return set()


def _get_active_branches() -> set:
    """Remote branches still existing."""
    try:
        from src.capture.git_reader import _get_repo
        repo = _get_repo()
        return {b.name for b in repo.branches}
    except Exception:
        return set()


def _scope_overlaps_changes(memory: dict, changed_files: set, active_branches: set) -> bool:
    """Check if memory scope was recently touched."""
    scope_type = memory.get('scope_type') or memory.get('scope') or 'repo'
    scope_value = memory.get('scope_value')

    if scope_type == 'repo':
        return True

    if scope_type == 'branch' and scope_value:
        return scope_value in active_branches

    if scope_type in ('file', 'module') and scope_value:
        for f in changed_files:
            if scope_value in f or f.startswith(scope_value):
                return True
        return False

    if scope_type == 'ticket':
        return True

    return True


def check_staleness(project: str) -> dict:
    """Marks staleness using time, file changes, active branches."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM memories WHERE project = ? AND status IN ('active', 'suspect')",
        (project,)
    ).fetchall()

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    suspect_cutoff = now - timedelta(days=SUSPECT_DAYS)

    recent_files = _get_recent_commit_files()
    active_branches = _get_active_branches()

    marked = {'stale': 0, 'suspect': 0, 'active': 0, 'unchanged': 0}

    for row in rows:
        memory = dict(row)
        last_verified = _parse_date(memory.get('last_verified_at'))
        if not last_verified:
            marked['unchanged'] += 1
            continue

        current_status = memory['status']
        scope_touched = _scope_overlaps_changes(memory, recent_files, active_branches)

        if last_verified < stale_cutoff:
            new_status = 'stale'
        elif last_verified < suspect_cutoff:
            new_status = 'stale' if scope_touched else 'suspect'
        elif scope_touched and last_verified < (now - timedelta(days=14)):
            new_status = 'suspect'
        else:
            new_status = 'active'

        if new_status != current_status:
            conn.execute(
                "UPDATE memories SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (new_status, memory['id'])
            )
            marked[new_status] = marked.get(new_status, 0) + 1
        else:
            marked['unchanged'] += 1

    conn.commit()
    conn.close()
    return marked


def mark_superseded(project: str, old_content_prefix: str, new_memory_id: int) -> int:
    """Marks memories matching prefix as superseded."""
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
    """Developer re-verifies a stale/suspect memory. Back to active."""
    conn = get_connection()
    conn.execute(
        "UPDATE memories SET status = 'active', last_verified_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
        (memory_id,)
    )
    conn.commit()
    conn.close()