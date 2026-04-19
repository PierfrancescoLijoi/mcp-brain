import logging
from mcp.server.fastmcp import FastMCP
from src.brain.retriever import (
    get_context,
    get_decisions,
    store_memory,
    store_session,
    init_project,
)
from src.storage.db import init_db

mcp = FastMCP('mcp-brain')


@mcp.tool()
def brain_init(project: str, path: str, stack: list[str], conventions: dict) -> str:
    '''Inizializza un progetto nel brain.'''
    init_db()
    return init_project(project, path, stack, conventions)


@mcp.tool()
def brain_get_context(project: str) -> str:
    '''Ritorna il contesto L1 compresso per il progetto.'''
    logging.info(f'brain_get_context called for {project}')
    try:
        result = get_context(project)
        logging.info(f'brain_get_context returned {len(result)} chars')
        return result
    except Exception as e:
        logging.error(f'brain_get_context error: {e}', exc_info=True)
        return f'error: {e}'


@mcp.tool()
def brain_get_decisions(project: str) -> str:
    '''Ritorna decisioni architetturali, pattern e tentativi falliti (L2).'''
    return get_decisions(project)

@mcp.tool()
def brain_get_git_snapshot(project: str) -> str:
    '''Ritorna snapshot git corrente: branch, commit recenti, file modificati. On-demand.'''
    from src.brain.compressor import build_git_context
    logging.info(f'brain_get_git_snapshot called for {project}')
    try:
        result = build_git_context(project)
        logging.info(f'brain_get_git_snapshot returned {len(result)} chars')
        return result
    except Exception as e:
        logging.error(f'brain_get_git_snapshot error: {e}', exc_info=True)
        return f'error: {e}'

@mcp.tool()
def brain_remember(
    project: str,
    category: str,
    content: str,
    explicit: bool = False,
    frequency: int = 1,
    files_affected: int = 1,
) -> str:
    '''Salva una nuova memoria nel brain.'''
    return store_memory(project, category, content, frequency, files_affected, explicit)


@mcp.tool()
def brain_save_session(
    project: str,
    branch: str,
    wip: str,
    next_steps: str,
) -> str:
    '''Salva lo snapshot di fine sessione.'''
    return store_session(project, branch, wip, next_steps)


@mcp.tool()
def brain_install_hook(project_path: str) -> str:
    '''Installa il git hook post-commit nel repo specificato.'''
    import shutil
    from pathlib import Path

    hook_src = Path(__file__).parent.parent.parent / 'hooks' / 'post-commit'
    hook_dst = Path(project_path) / '.git' / 'hooks' / 'post-commit'

    if not hook_src.exists():
        return f'error: hook source not found at {hook_src}'

    if not (Path(project_path) / '.git').exists():
        return f'error: {project_path} is not a git repository'

    shutil.copy(hook_src, hook_dst)
    hook_dst.chmod(0o755)

    return f'hook installed at {hook_dst}'


@mcp.tool()
def brain_get_git_snapshot(project: str) -> str:
    '''Ritorna snapshot git corrente: branch, commit recenti, file modificati. On-demand.'''
    from src.brain.compressor import build_git_context
    logging.info(f'brain_get_git_snapshot called for {project}')
    try:
        result = build_git_context(project)
        logging.info(f'brain_get_git_snapshot returned {len(result)} chars')
        return result
    except Exception as e:
        logging.error(f'brain_get_git_snapshot error: {e}', exc_info=True)
        return f'error: {e}'
