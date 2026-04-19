from src.brain.compressor import build_l1_context, build_l2_context
from src.storage.db import save_memory, save_session, save_project
from src.brain.scorer import score_memory, assign_level
from datetime import datetime, timezone


def get_context(project_name: str) -> str:
    """Ritorna il contesto L1 compresso — chiamato ad ogni sessione."""
    try:
        return build_l1_context(project_name)
    except Exception as e:
        return f"# mcp-brain: no context found for '{project_name}'. Run init first.\n# Error: {e}"


def get_decisions(project_name: str) -> str:
    """Ritorna il contesto L2 — chiamato on-demand da Claude."""
    try:
        return build_l2_context(project_name)
    except Exception as e:
        return f"# mcp-brain: error building L2 context.\n# Error: {e}"


def store_memory(
    project: str,
    category: str,
    content: str,
    frequency: int = 1,
    files_affected: int = 1,
    explicit: bool = False,
) -> str:
    """Salva una nuova memoria e la assegna al livello corretto."""
    now = datetime.now(timezone.utc).isoformat()
    score = score_memory(
        content=content,
        created_at=now,
        frequency=frequency,
        files_affected=files_affected,
        explicit=explicit,
    )
    level = assign_level(score)
    save_memory(project, level, category, content, score)
    return f"saved: level={level} score={score} category={category}"


def store_session(project: str, branch: str, wip: str, next_steps: str) -> str:
    """Salva lo snapshot di fine sessione."""
    save_session(project, branch, wip, next_steps)
    return f"session saved for '{project}' on branch '{branch}'"


def init_project(
    project: str,
    path: str,
    stack: list,
    conventions: dict,
) -> str:
    """Inizializza un progetto nel brain."""
    save_project(project, path, stack, conventions)
    return f"project '{project}' initialized"