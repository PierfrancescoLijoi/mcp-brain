import os
import time
from github import Github, GithubException

_cache = {'prs': {'data': None, 'ts': 0}, 'issues': {}}
_TTL = 300  # 5 minuti


def _get_repo():
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise RuntimeError('GITHUB_TOKEN not set')

    repo_name = os.environ.get('MCP_BRAIN_GH_REPO')
    if not repo_name:
        import subprocess
        try:
            url = subprocess.check_output(
                ['git', 'config', '--get', 'remote.origin.url'],
                text=True, timeout=3
            ).strip()
            if url.endswith('.git'):
                url = url[:-4]
            repo_name = '/'.join(url.replace('https://github.com/', '').split('/')[-2:])
        except Exception:
            raise RuntimeError('cannot detect repo name')

    return Github(token).get_repo(repo_name)


def list_open_prs() -> list:
    '''Lista PR aperte con file modificati.'''
    now = time.time()
    if _cache['prs']['data'] and (now - _cache['prs']['ts']) < _TTL:
        return _cache['prs']['data']

    try:
        repo = _get_repo()
        prs = []
        for pr in repo.get_pulls(state='open'):
            files = [f.filename for f in pr.get_files()]
            prs.append({
                'number': pr.number,
                'title': pr.title,
                'author': pr.user.login,
                'branch': pr.head.ref,
                'files': files,
            })
        _cache['prs']['data'] = prs
        _cache['prs']['ts'] = now
        return prs
    except Exception as e:
        return []


def get_issue(issue_id: int) -> dict:
    '''Dettagli di un issue.'''
    if issue_id in _cache['issues']:
        cached = _cache['issues'][issue_id]
        if (time.time() - cached['ts']) < _TTL:
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
    '''Branch con commit recenti.'''
    try:
        repo = _get_repo()
        branches = []
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        for branch in repo.get_branches():
            commit = branch.commit.commit
            if commit.author.date.replace(tzinfo=timezone.utc) > cutoff:
                branches.append({
                    'name': branch.name,
                    'last_author': commit.author.name,
                    'last_date': commit.author.date.strftime('%Y-%m-%d'),
                })
        return branches
    except Exception:
        return []