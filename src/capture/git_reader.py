"""
Operazioni git LOCALI (filesystem .git del repo).
Nessuna chiamata alle API GitHub — vedi github_reader.py per quelle.
"""
import os
from datetime import datetime, timezone

REPO_PATH = os.environ.get('MCP_BRAIN_REPO', os.getcwd())

# Limiti default per evitare payload enormi in context
DEFAULT_RECENT_COMMITS = 5
DEFAULT_MAX_CHANGED_FILES = 10


def _get_repo():
    """
    Ritorna un oggetto GitPython Repo per il percorso corrente.
    Usato anche da staleness.py per iterare commit e branch locali.
    """
    from git import Repo
    return Repo(REPO_PATH)


def get_repo_snapshot(
    recent_commits: int = DEFAULT_RECENT_COMMITS,
    max_changed: int = DEFAULT_MAX_CHANGED_FILES,
) -> dict:
    """
    Snapshot dello stato git locale.
    Ritorna:
      {
        'branch': str,
        'status': {'ahead': int, 'behind': int},
        'recent_commits': [{'hash', 'message', 'author', 'date'}],
        'changed_files': [{'file', 'status'}],   # modified|staged|untracked
      }
    Ritorna {} in caso di errore (repo non inizializzato, detached HEAD, ecc.).
    """
    try:
        repo = _get_repo()
        if repo.bare:
            return {}

        branch = _safe_branch_name(repo)
        status = _ahead_behind(repo)
        commits = _recent_commits(repo, recent_commits)
        changed = _changed_files(repo, max_changed)

        return {
            'branch': branch,
            'status': status,
            'recent_commits': commits,
            'changed_files': changed,
        }
    except Exception as e:
        return {'error': str(e)}


def _safe_branch_name(repo) -> str:
    """Gestisce detached HEAD senza sollevare eccezione."""
    try:
        return repo.active_branch.name
    except TypeError:
        return f'HEAD@{repo.head.commit.hexsha[:8]}'
    except Exception:
        return 'unknown'


def _ahead_behind(repo) -> dict:
    """Quanti commit avanti/dietro rispetto all'upstream tracciato."""
    try:
        active = repo.active_branch
        tracking = active.tracking_branch()
        if not tracking:
            return {'ahead': 0, 'behind': 0}
        ahead = sum(1 for _ in repo.iter_commits(f'{tracking.name}..HEAD'))
        behind = sum(1 for _ in repo.iter_commits(f'HEAD..{tracking.name}'))
        return {'ahead': ahead, 'behind': behind}
    except Exception:
        return {'ahead': 0, 'behind': 0}


def _recent_commits(repo, n: int) -> list:
    """Ultimi N commit su HEAD con metadata compatti."""
    commits = []
    try:
        for c in repo.iter_commits('HEAD', max_count=n):
            commits.append({
                'hash': c.hexsha[:8],
                'message': c.message.strip().splitlines()[0][:120],
                'author': c.author.name,
                'date': c.committed_datetime.astimezone(timezone.utc).isoformat(),
            })
    except Exception:
        pass
    return commits


def _changed_files(repo, cap: int) -> list:
    """File modificati (unstaged + staged + untracked), deduplicati, con status."""
    seen = {}

    try:
        for f in repo.index.diff(None):
            seen.setdefault(f.a_path, 'modified')
    except Exception:
        pass

    try:
        for f in repo.index.diff('HEAD'):
            seen.setdefault(f.a_path, 'staged')
    except Exception:
        pass

    try:
        for path in repo.untracked_files:
            seen.setdefault(path, 'untracked')
    except Exception:
        pass

    return [{'file': p, 'status': s} for p, s in list(seen.items())[:cap]]


def get_current_branch() -> str:
    """Shortcut: solo nome del branch corrente."""
    try:
        return _safe_branch_name(_get_repo())
    except Exception:
        return 'unknown'


def get_changed_files_since(ref: str = 'HEAD~5') -> list:
    """
    File toccati dai commit tra `ref` e HEAD.
    Usato dal predictor per dare priorità a file 'caldi'.
    """
    try:
        repo = _get_repo()
        files = set()
        for c in repo.iter_commits(f'{ref}..HEAD'):
            files.update(c.stats.files.keys())
        return sorted(files)
    except Exception:
        return []