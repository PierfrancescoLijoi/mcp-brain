import os
import time
from datetime import datetime, timedelta, timezone
from github import Github

_cache = {'prs': {'data': None, 'ts': 0}, 'issues': {}, 'repo': None}
_TTL = 600
MAX_PRS = 50
RECENT_DAYS = 14


def _detect_repo_name():
    repo_name = os.environ.get('MCP_BRAIN_GH_REPO')
    if repo_name:
        return repo_name
    try:
        from git import Repo
        repo = Repo(os.environ.get('MCP_BRAIN_REPO', os.getcwd()))
        url = repo.remote('origin').url
        if url.endswith('.git'):
            url = url[:-4]
        return '/'.join(url.replace('https://github.com/', '').split('/')[-2:])
    except Exception:
        raise RuntimeError('cannot detect repo name')


def _get_repo():
    if _cache['repo'] is not None:
        return _cache['repo']
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GITHUB_TOKEN not set')
    repo = Github(token).get_repo(_detect_repo_name())
    _cache['repo'] = repo
    return repo


def list_open_prs() -> list:
    now = time.time()
    if _cache['prs']['data'] is not None and (now - _cache['prs']['ts']) < _TTL:
        return _cache['prs']['data']
    try:
        repo = _get_repo()
        prs = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)
        for pr in repo.get_pulls(state='open', sort='updated', direction='desc'):
            if pr.updated_at.replace(tzinfo=timezone.utc) < cutoff:
                break
            if len(prs) >= MAX_PRS:
                break
            files = [f.filename for f in pr.get_files()]
            prs.append({
                'number': pr.number, 'title': pr.title, 'author': pr.user.login,
                'branch': pr.head.ref, 'files': files,
            })
        _cache['prs']['data'] = prs
        _cache['prs']['ts'] = now
        return prs
    except Exception:
        return []


def get_issue(issue_id: int) -> dict:
    if issue_id in _cache['issues']:
        cached = _cache['issues'][issue_id]
        if (time.time() - cached['ts']) < _TTL:
            return cached['data']
    try:
        repo = _get_repo()
        issue = repo.get_issue(issue_id)
        data = {
            'id': issue.number, 'title': issue.title, 'body': issue.body or '',
            'labels': [l.name for l in issue.labels],
            'assignee': issue.assignee.login if issue.assignee else None,
            'state': issue.state,
        }
        _cache['issues'][issue_id] = {'data': data, 'ts': time.time()}
        return data
    except Exception as e:
        return {'error': str(e)}
