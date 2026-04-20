import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.storage.db import (
    init_db,
    save_raw_event,
    count_similar_patterns,
    save_memory,
    mark_raw_promoted,
)

# -------------------- Costanti --------------------

PROMOTION_THRESHOLD = 3
SEMANTIC_SUPERSEDE_THRESHOLD = 0.35

NOISE_PREFIXES = ('docs:', 'chore:', 'style:', 'test:', 'ci:')
SEMANTIC_PREFIXES = ('feat:', 'fix:', 'perf:', 'refactor:')

DECISION_KEYWORDS = ('refactor:', 'migrate', 'replace', 'switch to', 'breaking:')
FAILED_KEYWORDS = ('fix:', 'hotfix', 'workaround')
REVERT_KEYWORDS = ('revert', 'rollback', 'undo')
BREAKING_KEYWORDS = ('breaking:', 'revert', 'rollback')


# -------------------- Git info --------------------

def get_commit_info() -> dict:
    try:
        message = subprocess.check_output(
            ['git', 'log', '-1', '--pretty=%B'], text=True
        ).strip()
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'], text=True
        ).strip()
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], text=True
        ).strip()
        files = subprocess.check_output(
            ['git', 'diff-tree', '--no-commit-id', '-r', '--name-only', 'HEAD'],
            text=True,
        ).strip().splitlines()
        return {
            'message': message,
            'branch': branch,
            'hash': commit_hash,
            'files': files,
        }
    except Exception as e:
        print(f'[mcp-brain] git info error: {e}')
        return {}


# -------------------- Classification --------------------

def classify_commit(message: str) -> str:
    msg_lower = message.lower().strip()

    if any(k in msg_lower for k in REVERT_KEYWORDS):
        return 'avoid'
    if any(k in msg_lower for k in DECISION_KEYWORDS):
        return 'decision'
    if any(k in msg_lower for k in FAILED_KEYWORDS):
        return 'failed'
    if msg_lower.startswith(('feat:', 'perf:')):
        return 'pattern'
    return 'noise'


def should_promote(project: str, message: str, classification: str, files: list) -> tuple:
    """
    Decide se promuovere un raw event a memory.
    Ritorna (should_promote: bool, confidence: str, reason: str).
    """
    msg_lower = message.lower().strip()

    # Filtra rumore: commit a basso segnale non vengono mai promossi
    if msg_lower.startswith(NOISE_PREFIXES):
        prefix = msg_lower.split(':', 1)[0]
        return False, 'low', f'low-signal prefix ({prefix}:)'

    # Rule 1: breaking change / revert → alto impatto architetturale
    if any(k in msg_lower for k in BREAKING_KEYWORDS):
        return True, 'high', 'breaking change or revert'

    # Rule 2: decision architetturale (refactor/migrate/switch)
    if classification == 'decision':
        return True, 'high', 'architectural decision'

    # Rule 3: conventional commit semantico + impatto multi-file
    if message.startswith(SEMANTIC_PREFIXES) and len(files) >= 3:
        return (
            True,
            'medium',
            f'semantic commit with multi-file impact ({len(files)} files)',
        )

    # Rule 4: pattern ricorrente (>= threshold messaggi simili)
    msg_prefix = message[:30]
    similar = count_similar_patterns(project, msg_prefix)
    if similar >= PROMOTION_THRESHOLD:
        return True, 'medium', f'recurring pattern ({similar} occurrences)'

    return False, 'low', 'insufficient signal'


# -------------------- Helpers --------------------

def _compute_scope(files: list) -> tuple:
    """
    Se il commit tocca ≤5 file tutti nella stessa directory → scope='module'.
    Altrimenti → scope='repo'. Aiuta la staleness detection.
    """
    if not files or len(files) > 5:
        return 'repo', None
    dirs = {f.rsplit('/', 1)[0] for f in files if '/' in f}
    if len(dirs) == 1:
        return 'module', dirs.pop()
    return 'repo', None


def _get_last_memory_id(project: str, content: str):
    """Recupera l'id della memoria appena inserita per attivare il supersede."""
    from src.storage.db import get_connection
    conn = get_connection()
    row = conn.execute(
        'SELECT id FROM memories WHERE project = ? AND content = ? '
        'ORDER BY id DESC LIMIT 1',
        (project, content),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _apply_semantic_supersede(project: str, content: str, category: str) -> None:
    """
    Marca come 'superseded' le memorie semanticamente simili alla nuova,
    usando Jaccard sui token (vedi src/brain/similarity.py).
    Solo memorie della stessa categoria vengono considerate.
    """
    from src.brain.staleness import mark_superseded_semantic

    new_id = _get_last_memory_id(project, content)
    if not new_id:
        return

    superseded = mark_superseded_semantic(
        project=project,
        new_content=content,
        new_memory_id=new_id,
        category=category,
        threshold=SEMANTIC_SUPERSEDE_THRESHOLD,
    )
    if superseded:
        print(
            f'[mcp-brain] superseded {len(superseded)} {category}(s) via semantic similarity:'
        )
        for s in superseded:
            print(
                f'  id={s["id"]} sim={s["similarity"]} '
                f'content="{s["content"][:60]}"'
            )


# -------------------- Main pipeline --------------------

def run(project: str) -> None:
    init_db()
    info = get_commit_info()
    if not info:
        return

    message = info.get('message', '')
    files = info.get('files', [])
    commit_hash = info.get('hash', '')
    branch = info.get('branch', '')

    if not message:
        return

    classification = classify_commit(message)
    event_id = save_raw_event(project, commit_hash, branch, message, files, classification)
    print(f'[mcp-brain] raw event saved: {classification} (id={event_id})')

    if classification == 'noise':
        print('[mcp-brain] classified as noise, not promoted')
    else:
        promote, confidence, reason = should_promote(project, message, classification, files)
        if promote:
            first_line = message.strip().splitlines()[0]
            content = f'{classification}: {first_line}'
            scope_type, scope_value = _compute_scope(files)

            save_memory(
                project=project,
                level=1 if confidence == 'high' else 2,
                category=classification,
                content=content,
                score=0.8 if confidence == 'high' else 0.5,
                status='active',
                confidence=confidence,
                source='git-hook',
                scope_type=scope_type,
                scope_value=scope_value,
            )
            mark_raw_promoted(event_id)

            # Auto-supersede semantico: solo per decision (alto impatto)
            if classification == 'decision':
                _apply_semantic_supersede(project, content, category='decision')

            tag = f'scope={scope_type}' + (f':{scope_value}' if scope_value else '')
            print(f'[mcp-brain] promoted ({tag}): {reason}')
        else:
            print(f'[mcp-brain] not promoted: {reason}')

    # Incremental index update (se implementato)
    if files:
        try:
            from src.brain.file_indexer import incremental_update
            idx = incremental_update(files)
            print(
                f'[mcp-brain] index updated: '
                f'{idx.get("updated_files", 0)} changed, {idx["total"]} total'
            )
        except Exception as e:
            print(f'[mcp-brain] index update error: {e}')


if __name__ == '__main__':
    project = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
    run(project)