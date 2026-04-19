import os
import time
from pathlib import Path
from git import Repo

REPO_CWD = os.environ.get('MCP_BRAIN_REPO', os.getcwd())

_cache = {'data': None, 'ts': 0}
_TTL = 60


def _get_repo() -> Repo:
    return Repo(REPO_CWD)


def get_current_branch() -> str:
    try:
        return _get_repo().active_branch.name
    except Exception:
        return 'unknown'


def get_branch_status() -> dict:
    try:
        repo = _get_repo()
        ahead = sum(1 for _ in repo.iter_commits('main..HEAD'))
        behind = sum(1 for _ in repo.iter_commits('HEAD..main'))
        return {'ahead': ahead, 'behind': behind}
    except Exception:
        return {'ahead': 0, 'behind': 0}


def get_recent_commits(n: int = 5) -> list:
    try:
        repo = _get_repo()
        commits = []
        for c in list(repo.iter_commits('HEAD', max_count=n)):
            commits.append({
                'hash': c.hexsha[:8],
                'message': c.message.strip().split('\n')[0],
                'author': c.author.name,
                'date': c.committed_datetime.strftime('%Y-%m-%d'),
            })
        return commits
    except Exception:
        return []


def get_changed_files(n_commits: int = 3) -> list:
    try:
        repo = _get_repo()
        commits = list(repo.iter_commits('HEAD', max_count=n_commits + 1))
        if len(commits) < 2:
            return []
        diff = commits[0].diff(commits[-1])
        files = []
        for d in diff:
            path = d.a_path or d.b_path
            if path:
                files.append({'file': path, 'stats': d.change_type})
        return files
    except Exception:
        return []


def get_repo_snapshot() -> dict:
    now = time.time()
    if _cache['data'] and (now - _cache['ts']) < _TTL:
        return _cache['data']

    data = {
        'branch': get_current_branch(),
        'status': get_branch_status(),
        'recent_commits': get_recent_commits(n=3),
        'changed_files': get_changed_files(n_commits=3),
    }
    _cache['data'] = data
    _cache['ts'] = now
    return data