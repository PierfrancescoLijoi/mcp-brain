import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.storage.db import init_db, save_raw_event, count_similar_patterns, save_memory, mark_raw_promoted, get_raw_events

CONVENTIONAL_PREFIXES = ('feat:', 'fix:', 'refactor:', 'perf:', 'docs:', 'chore:', 'revert:', 'breaking:')
PROMOTION_THRESHOLD = 3


def get_commit_info() -> dict:
    try:
        message = subprocess.check_output(['git', 'log', '-1', '--pretty=%B'], text=True).strip()
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], text=True).strip()
        commit_hash = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        files = subprocess.check_output(
            ['git', 'diff-tree', '--no-commit-id', '-r', '--name-only', 'HEAD'], text=True
        ).strip().splitlines()
        return {'message': message, 'branch': branch, 'hash': commit_hash, 'files': files}
    except Exception as e:
        print(f'[mcp-brain] git info error: {e}')
        return {}


def classify_commit(message: str) -> str:
    msg_lower = message.lower().strip()

    if any(k in msg_lower for k in ['revert', 'rollback', 'undo']):
        return 'avoid'
    if any(k in msg_lower for k in ['refactor:', 'migrate', 'replace', 'switch to', 'breaking:']):
        return 'decision'
    if any(k in msg_lower for k in ['fix:', 'hotfix', 'workaround']):
        return 'failed'
    if msg_lower.startswith(('feat:', 'perf:')):
        return 'pattern'
    return 'noise'


def should_promote(project: str, message: str, classification: str, files: list) -> tuple:
    '''
    Decide se promuovere un raw event a memory.
    Ritorna (should_promote, confidence, reason).
    '''
    msg_lower = message.lower().strip()

    # Rule 1: breaking/revert sempre promossi
    if any(k in msg_lower for k in ['breaking:', 'revert', 'rollback']):
        return True, 'high', 'breaking change or revert'

    # Rule 2: decision architetturale (refactor, migrate, switch)
    if classification == 'decision':
        return True, 'high', 'architectural decision'

    # Rule 3: conventional commit prefix + >=2 file modificati
    if message.startswith(CONVENTIONAL_PREFIXES) and len(files) >= 2:
        return True, 'medium', 'conventional commit with multi-file impact'

    # Rule 4: pattern ricorrente (>= threshold messaggi simili)
    msg_prefix = message[:30]
    similar = count_similar_patterns(project, msg_prefix)
    if similar >= PROMOTION_THRESHOLD:
        return True, 'medium', f'recurring pattern ({similar} occurrences)'

    # Altrimenti: resta raw, non promosso
    return False, 'low', 'insufficient signal'


def run(project: str):
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
    save_raw_event(project, commit_hash, branch, message, files, classification)
    print(f'[mcp-brain] raw event saved: {classification}')

    # Skip promotion per commit classificati noise
    if classification == 'noise':
        print(f'[mcp-brain] classified as noise, not promoted')
    else:
        promote, confidence, reason = should_promote(project, message, classification, files)
        if promote:
            content = f'{classification}: {message.strip().splitlines()[0]}'
            save_memory(
                project=project,
                level=1 if confidence == 'high' else 2,
                category=classification,
                content=content,
                score=0.8 if confidence == 'high' else 0.5,
                status='active',
                confidence=confidence,
                source='git-hook',
                scope='repo',
            )
            # Mark raw event as promoted
            events = get_raw_events(project)
            if events:
                mark_raw_promoted(events[0]['id'])
            print(f'[mcp-brain] promoted to memory: {reason}')
        else:
            print(f'[mcp-brain] not promoted: {reason}')

    # Incremental index update
    if files:
        try:
            from src.brain.file_indexer import incremental_update
            idx = incremental_update(files)
            print(f'[mcp-brain] index updated: {idx.get("updated_files", 0)} changed, {idx["total"]} total')
        except Exception as e:
            print(f'[mcp-brain] index update error: {e}')


if __name__ == '__main__':
    project = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
    run(project)
