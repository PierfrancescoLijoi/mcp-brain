from mcp.server.fastmcp import FastMCP
from src.brain.retriever import (
    get_context,
    get_decisions,
    store_memory,
    store_session,
    init_project,
)
from src.storage.db import init_db

mcp = FastMCP("mcp-brain")


@mcp.tool()
def brain_init(project: str, path: str, stack: list[str], conventions: dict) -> str:
    """
    Inizializza un progetto nel brain.
    Chiamare una volta sola per repo.

    Args:
        project: nome del progetto (es. 'my-api')
        path: path assoluto del repo (es. '/home/user/projects/my-api')
        stack: lista tecnologie (es. ['FastAPI', 'PostgreSQL', 'Redis'])
        conventions: dict convenzioni (es. {'indent': 2, 'types': 'strict'})
    """
    init_db()
    return init_project(project, path, stack, conventions)


@mcp.tool()
def brain_get_context(project: str) -> str:
    """
    Ritorna il contesto L1 compresso per il progetto.
    Chiamare SEMPRE all'inizio di ogni sessione.
    Costo: ~70 token.

    Args:
        project: nome del progetto
    """
    return get_context(project)


@mcp.tool()
def brain_get_decisions(project: str) -> str:
    """
    Ritorna decisioni architetturali, pattern e tentativi falliti (L2).
    Chiamare solo quando il task corrente richiede contesto storico.
    Costo: ~200-400 token.

    Args:
        project: nome del progetto
    """
    return get_decisions(project)


@mcp.tool()
def brain_remember(
    project: str,
    category: str,
    content: str,
    explicit: bool = False,
    frequency: int = 1,
    files_affected: int = 1,
) -> str:
    """
    Salva una nuova memoria nel brain.
    Il sistema assegna automaticamente il livello (L1/L2/L3) tramite scoring.

    Args:
        project: nome del progetto
        category: tipo memoria — 'decision' | 'avoid' | 'pattern' | 'failed'
        content: contenuto compresso della memoria
        explicit: True se il developer l'ha marcata esplicitamente
        frequency: quante volte questo pattern appare (default 1)
        files_affected: quanti file tocca (default 1)
    """
    return store_memory(project, category, content, frequency, files_affected, explicit)


@mcp.tool()
def brain_save_session(
    project: str,
    branch: str,
    wip: str,
    next_steps: str,
) -> str:
    """
    Salva lo snapshot di fine sessione.
    Chiamare SEMPRE prima di chiudere Claude Code.

    Args:
        project: nome del progetto
        branch: branch git attivo (es. 'feat/guardrails')
        wip: cosa stavi facendo (es. 'refactor middleware chain')
        next_steps: prossimo step (es. 'aggiungere circuit breaker')
    """
    return store_session(project, branch, wip, next_steps)