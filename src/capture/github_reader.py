"""
API GitHub remote. Unica sorgente per PR aperte, issue, branch remoti.
Tutte le chiamate sono cacheate con TTL per evitare rate limit.
"""
import os
import time
from datetime import datetime, timedelta, timezone

_TTL = 600  # 5 min, bilanciamento tra freschezza e rate limit
MAX_PRS = 50
RECENT_DAYS = 14

_cache = {
    'prs': {'data': None, 'ts': 0},
    'issues': {},
    'branches': {'data': None, 'ts': 0},
    'repo': None,
}


# -------------------- Detection & auth --------------------

def _detect_repo_name() -> str:
    """
    Ricava owner/repo dall'env o dal remote origin del repo locale.
    Env var MCP_BRAIN_GH_REPO sovrascrive il detection automatico.
    """
    repo_name = os.environ.get('MCP_BRAIN_GH_REPO')
    if repo_name:
        return repo_name
    try:
        from git import Repo
        repo = Repo(os.environ.get('MCP_BRAIN_REPO', os.getcwd()))
        url = repo.remote('origin').url
        if url.endswith('.git'):
            url = url[:-4]
        # Supporta sia https://github.com/owner/repo sia git@github.com:owner/repo
        url = url.replace('https://github.com/', '').replace('git@github.com:', '')
        return '/'.join(url.split('/')[-2:])
    except Exception as e:
        raise RuntimeError(f'cannot detect repo name: {e}')


def _get_repo():
    """Client GitHub cacheato (un oggetto per processo)."""
    if _cache['repo'] is not None:
        return _cache['repo']
    from github import Github
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GITHUB_TOKEN not set')
    repo = Github(token).get_repo(_detect_repo_name())
    _cache['repo'] = repo
    return repo


def _cache_valid(entry: dict) -> bool:
    return entry.get('data') is not None and (time.time() - entry.get('ts', 0)) < _TTL


# -------------------- Public API --------------------

def list_open_prs() -> list:
    """
    Lista PR aperte + file modificati, con cache TTL.
    Filtra a MAX_PRS PR aggiornate negli ultimi RECENT_DAYS giorni per limitare payload.
    """
    if _cache_valid(_cache['prs']):
        return _cache['prs']['data']

    try:
        repo = _get_repo()
        prs = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
        for pr in repo.get_pulls(state='open', sort='updated', direction='desc'):
            updated = pr.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated < cutoff:
                break
            if len(prs) >= MAX_PRS:
                break
            files = [f.filename for f in pr.get_files()]
            prs.append({
                'number': pr.number,
                'title': pr.title,
                'author': pr.user.login,
                'branch': pr.head.ref,
                'files': files,
                'updated_at': updated.isoformat(),
            })
        _cache['prs'] = {'data': prs, 'ts': time.time()}
        return prs
    except Exception as e:
        # Fallback silenzioso: se GitHub non è raggiungibile il sistema continua a funzionare
        return []


def get_issue(issue_id: int) -> dict:
    """Dettagli di una issue. Cache per-id."""
    cached = _cache['issues'].get(issue_id)
    if cached and (time.time() - cached['ts']) < _TTL:
        return cached['data']

    try:
        repo = _get_repo()
        issue = repo.get_issue(issue_id)
        data = {
            'id': issue.number,
            'title': issue.title,
            'body': issue.body or '',
            'labels': [l.name for l in issue.labels],
            'assignee': issue.assignee.login if issue.assignee else None,
            'state': issue.state,
        }
        _cache['issues'][issue_id] = {'data': data, 'ts': time.time()}
        return data
    except Exception as e:
        return {'error': str(e)}


def get_active_branches(days: int = 7) -> list:
    """
    Branch remoti con commit negli ultimi `days` giorni.
    Usato per team awareness (chi sta lavorando su cosa).
    """
    if _cache_valid(_cache['branches']):
        return _cache['branches']['data']

    try:
        repo = _get_repo()
        branches = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for branch in repo.get_branches():
            commit = branch.commit.commit
            commit_date = commit.author.date
            if commit_date.tzinfo is None:
                commit_date = commit_date.replace(tzinfo=timezone.utc)
            if commit_date > cutoff:
                branches.append({
                    'name': branch.name,
                    'last_author': commit.author.name,
                    'last_date': commit_date.strftime('%Y-%m-%d'),
                })
        _cache['branches'] = {'data': branches, 'ts': time.time()}
        return branches
    except Exception:
        return []


def clear_cache() -> None:
    """Reset della cache (utile in test e per force-refresh)."""
    _cache['prs'] = {'data': None, 'ts': 0}
    _cache['issues'] = {}
    _cache['branches'] = {'data': None, 'ts': 0}
    _cache['repo'] = None