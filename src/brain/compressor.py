import json
import yaml
from src.storage.db import get_memories, get_last_session, get_project


def build_l1_context(project_name: str) -> str:
    """
    Costruisce il contesto L1 in YAML compresso.
    Target: 50-80 token fissi per sessione.
    """
    project = get_project(project_name)
    session = get_last_session(project_name)
    memories = get_memories(project_name, level=1)

    stack = json.loads(project["stack"]) if project and project["stack"] else []
    conventions = json.loads(project["conventions"]) if project and project["conventions"] else {}

    avoid = [
        m["content"] for m in memories if m["category"] == "avoid"
    ]
    decisions = [
        m["content"] for m in memories if m["category"] == "decision"
    ]

    ctx = {
        "p": {
            "name": project_name,
            "stack": stack,
            **conventions,
        },
        "s": {
            "branch": session["branch"] if session else "unknown",
            "wip": session["wip"] if session else None,
            "next": session["next_steps"] if session else None,
        },
    }

    if avoid:
        ctx["avoid"] = avoid[:3]  # max 3 per restare sotto token budget

    if decisions:
        ctx["decisions"] = decisions[:2]  # max 2 in L1

    return yaml.dump(ctx, default_flow_style=True, allow_unicode=True).strip()


def build_l2_context(project_name: str) -> str:
    """
    Costruisce il contesto L2 in YAML strutturato.
    Target: 200-400 token, on-demand.
    """
    memories = get_memories(project_name, level=2)

    decisions = [m["content"] for m in memories if m["category"] == "decision"]
    failed = [m["content"] for m in memories if m["category"] == "failed"]
    patterns = [m["content"] for m in memories if m["category"] == "pattern"]

    ctx = {}
    if decisions:
        ctx["decisions"] = decisions
    if failed:
        ctx["tried_and_failed"] = failed
    if patterns:
        ctx["patterns"] = patterns

    if not ctx:
        return "# No L2 context available yet."

    return yaml.dump(ctx, default_flow_style=False, allow_unicode=True).strip()