import json
import yaml
from src.storage.db import get_memories, get_last_session, get_project


def build_l1_context(project_name: str) -> str:
    project = get_project(project_name)
    session = get_last_session(project_name)
    memories = get_memories(project_name, level=1)

    stack = json.loads(project['stack']) if project and project['stack'] else []
    conventions = json.loads(project['conventions']) if project and project['conventions'] else {}

    avoid = [m['content'] for m in memories if m['category'] == 'avoid']
    decisions = [m['content'] for m in memories if m['category'] == 'decision']

    try:
        from src.capture.git_reader import get_repo_snapshot
        git = get_repo_snapshot()
    except Exception:
        git = {}

    try:
        from src.brain.claims_manager import get_active_claims
        claims = get_active_claims()
    except Exception:
        claims = []

    ctx = {
        'p': {'name': project_name, 'stack': stack, **conventions},
        's': {
            'branch': session['branch'] if session else git.get('branch', 'unknown'),
            'wip': session['wip'] if session else None,
            'next': session['next_steps'] if session else None,
        },
        'git': {
            'branch': git.get('branch', 'unknown'),
            'ahead': git.get('status', {}).get('ahead', 0),
            'behind': git.get('status', {}).get('behind', 0),
            'recent': [c['message'] for c in git.get('recent_commits', [])[:3]],
            'changed': [f['file'] for f in git.get('changed_files', [])[:5]],
        },
    }

    if claims:
        ctx['team_claims'] = [
            {
                'ticket': c['ticket'],
                'author': c['author'],
                'files': c['files'][:3],
            }
            for c in claims[:5]
        ]

    if avoid:
        ctx['avoid'] = avoid[:3]
    if decisions:
        ctx['decisions'] = decisions[:2]

    return yaml.dump(ctx, default_flow_style=True, allow_unicode=True).strip()


def build_l2_context(project_name: str) -> str:
    memories = get_memories(project_name, level=2)
    decisions = [m['content'] for m in memories if m['category'] == 'decision']
    failed = [m['content'] for m in memories if m['category'] == 'failed']
    patterns = [m['content'] for m in memories if m['category'] == 'pattern']

    ctx = {}
    if decisions:
        ctx['decisions'] = decisions
    if failed:
        ctx['tried_and_failed'] = failed
    if patterns:
        ctx['patterns'] = patterns

    if not ctx:
        return '# No L2 context available yet.'
    return yaml.dump(ctx, default_flow_style=False, allow_unicode=True).strip()


def build_git_context(project_name: str) -> str:
    try:
        from src.capture.git_reader import get_repo_snapshot
        snap = get_repo_snapshot()
        return yaml.dump({'git': snap}, default_flow_style=False, allow_unicode=True).strip()
    except Exception as e:
        return f'# git unavailable: {e}'
