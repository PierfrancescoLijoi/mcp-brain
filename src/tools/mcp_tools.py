import logging
import time
from mcp.server.fastmcp import FastMCP
from src.brain.retriever import (
    get_context, get_decisions, store_memory, store_session, init_project,
)
from src.storage.db import init_db

mcp = FastMCP('mcp-brain')


def _timed_tool(name, func):
    def wrapper(*args, **kwargs):
        start = time.time()
        logging.info(f'{name} START')
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start
            logging.info(f'{name} END ({elapsed:.2f}s, {len(str(result))} chars)')
            return result
        except Exception as e:
            elapsed = time.time() - start
            logging.error(f'{name} FAILED ({elapsed:.2f}s): {e}', exc_info=True)
            return f'error: {e}'
    return wrapper


@mcp.tool()
def brain_init(project: str, path: str, stack: list[str], conventions: dict) -> str:
    '''Inizializza un progetto nel brain.'''
    init_db()
    return init_project(project, path, stack, conventions)


@mcp.tool()
def brain_get_context(project: str) -> str:
    '''Contesto L1 compresso.'''
    return _timed_tool('brain_get_context', lambda: get_context(project))()


@mcp.tool()
def brain_get_decisions(project: str) -> str:
    '''Decisioni L2.'''
    return get_decisions(project)


@mcp.tool()
def brain_get_git_snapshot(project: str) -> str:
    '''Snapshot git corrente.'''
    from src.brain.compressor import build_git_context
    return _timed_tool('brain_get_git_snapshot', lambda: build_git_context(project))()


@mcp.tool()
def brain_remember(project: str, category: str, content: str, explicit: bool = False, frequency: int = 1, files_affected: int = 1) -> str:
    '''Salva memoria.'''
    return store_memory(project, category, content, frequency, files_affected, explicit)


@mcp.tool()
def brain_save_session(project: str, branch: str, wip: str, next_steps: str) -> str:
    '''Salva snapshot sessione.'''
    return store_session(project, branch, wip, next_steps)


@mcp.tool()
def brain_install_hook(project_path: str) -> str:
    '''Installa git hook.'''
    import shutil
    from pathlib import Path
    hook_src = Path(__file__).parent.parent.parent / 'hooks' / 'post-commit'
    hook_dst = Path(project_path) / '.git' / 'hooks' / 'post-commit'
    if not hook_src.exists():
        return 'error: hook source not found'
    if not (Path(project_path) / '.git').exists():
        return 'error: not a git repository'
    shutil.copy(hook_src, hook_dst)
    hook_dst.chmod(0o755)
    return f'hook installed at {hook_dst}'


def _start_ticket_impl(project, issue_id, author):
    from src.capture.github_reader import get_issue
    from src.brain.file_predictor import predict_files_from_issue
    from src.brain.conflict_detector import detect_conflicts, build_warnings
    from src.brain.claims_manager import claim_files
    import yaml

    issue = get_issue(issue_id)
    if 'error' in issue:
        return 'error loading issue: ' + str(issue.get('error'))

    predicted = predict_files_from_issue(issue['title'], issue.get('body', ''))
    conflicts = detect_conflicts(predicted, exclude_author=author)
    warnings = build_warnings(conflicts)
    claim_files(issue_id, predicted, author, issue['title'])

    result = {
        'ticket': {'id': issue['id'], 'title': issue['title'], 'labels': issue['labels']},
        'predicted_files': predicted[:5],
        'conflicts': warnings if warnings else ['none'],
        'guidance': 'Coordinate with active PRs before modifying shared files' if warnings else 'No conflicts detected, safe to proceed',
    }
    return yaml.dump(result, default_flow_style=False, allow_unicode=True).strip()


@mcp.tool()
def brain_start_ticket(project: str, issue_id: int, author: str) -> str:
    '''Inizia lavoro su issue GitHub.'''
    return _timed_tool('brain_start_ticket', lambda: _start_ticket_impl(project, issue_id, author))()


@mcp.tool()
def brain_check_conflicts(project: str, files: list[str], author: str = None) -> str:
    '''Verifica conflitti su file.'''
    from src.brain.conflict_detector import detect_conflicts, build_warnings
    import yaml
    conflicts = detect_conflicts(files, exclude_author=author)
    warnings = build_warnings(conflicts)
    if not warnings:
        return 'no conflicts detected'
    return yaml.dump({'warnings': warnings}, default_flow_style=False).strip()


@mcp.tool()
def brain_release_ticket(project: str, issue_id: int) -> str:
    '''Rilascia claim.'''
    from src.brain.claims_manager import release_claim
    released = release_claim(issue_id)
    return f'claim for #{issue_id} released' if released else f'no active claim for #{issue_id}'


def _team_status_impl():
    from src.brain.claims_manager import get_active_claims
    from src.capture.github_reader import list_open_prs
    import yaml
    claims = get_active_claims()
    prs = list_open_prs()
    status = {
        'active_claims': [
            {'ticket': c['ticket'], 'author': c['author'], 'title': c.get('title', ''), 'files': c['files'][:3]}
            for c in claims
        ] or ['none'],
        'open_prs': [
            {'pr': p['number'], 'author': p['author'], 'title': p['title'], 'files': p['files'][:3]}
            for p in prs
        ] or ['none'],
    }
    return yaml.dump(status, default_flow_style=False, allow_unicode=True).strip()


@mcp.tool()
def brain_team_status(project: str) -> str:
    '''Stato team.'''
    return _timed_tool('brain_team_status', _team_status_impl)()


@mcp.tool()
def brain_check_staleness(project: str) -> str:
    '''Marca come stale/suspect le memorie non verificate di recente. Ritorna conteggio.'''
    from src.brain.staleness import check_staleness
    import yaml
    try:
        result = check_staleness(project)
        return yaml.dump({'staleness_check': result}, default_flow_style=False).strip()
    except Exception as e:
        return f'error: {e}'


@mcp.tool()
def brain_verify_memory(memory_id: int) -> str:
    '''Ri-verifica una memoria stale/suspect (torna active).'''
    from src.brain.staleness import reactivate_memory
    try:
        reactivate_memory(memory_id)
        return f'memory {memory_id} reactivated as active'
    except Exception as e:
        return f'error: {e}'


@mcp.tool()
def brain_start_ticket_explained(project: str, issue_id: int, author: str) -> str:
    '''Come brain_start_ticket ma con spiegazione per ogni file predetto.'''
    from src.capture.github_reader import get_issue
    from src.brain.file_predictor import predict_files_explained
    from src.brain.conflict_detector import detect_conflicts, build_warnings
    from src.brain.claims_manager import claim_files
    import yaml

    try:
        issue = get_issue(issue_id)
        if 'error' in issue:
            return 'error loading issue: ' + str(issue.get('error'))

        predictions = predict_files_explained(issue['title'], issue.get('body', ''))
        files_only = [p['file'] for p in predictions]

        conflicts = detect_conflicts(files_only, exclude_author=author)
        warnings = build_warnings(conflicts)
        claim_files(issue_id, files_only, author, issue['title'])

        result = {
            'ticket': {
                'id': issue['id'],
                'title': issue['title'],
                'labels': issue['labels'],
            },
            'predicted_files': [
                {
                    'file': p['file'],
                    'confidence': p['confidence'],
                    'why': p['why'],
                }
                for p in predictions[:5]
            ],
            'conflicts': warnings if warnings else ['none'],
            'guidance': (
                'Coordinate with active PRs before modifying shared files'
                if warnings else 'No conflicts detected, safe to proceed'
            ),
        }
        return yaml.dump(result, default_flow_style=False, allow_unicode=True).strip()
    except Exception as e:
        return f'error: {e}'

from src.tools.predict_files_tool import register_predict_files_tool
register_predict_files_tool(mcp)
from src.tools.conflict_tool_v2 import register_check_conflicts_v2_tool
register_check_conflicts_v2_tool(mcp)
from src.tools.ticket_context_tool import register_get_ticket_context_tool
register_get_ticket_context_tool(mcp)
from src.tools.patch_guard_tool import register_check_patch_tool
register_check_patch_tool(mcp)
from src.tools.feedback_tool import register_feedback_tools
register_feedback_tools(mcp)

# STEP 7 — Observability
from src.tools.observability_tool import register_observability_tool, auto_instrument_existing_tools
register_observability_tool(mcp)
_instrumented = auto_instrument_existing_tools(mcp)
import logging; logging.info(f'[observability] auto-instrumented {_instrumented} tools')
