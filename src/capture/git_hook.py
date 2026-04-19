import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.brain.retriever import store_memory
from src.storage.db import init_db


def get_commit_info() -> dict:
    try:
        message = subprocess.check_output(['git', 'log', '-1', '--pretty=%B'], text=True).strip()
        branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], text=True).strip()
        files = subprocess.check_output(
            ['git', 'diff-tree', '--no-commit-id', '-r', '--name-only', 'HEAD'], text=True
        ).strip().splitlines()
        return {'message': message, 'branch': branch, 'files': files}
    except Exception as e:
        print(f'[mcp-brain] git info error: {e}')
        return {}


def classify_commit(message: str, files: list) -> tuple:
    msg_lower = message.lower()
    if any(k in msg_lower for k in ['revert', 'rollback', 'undo']):
        return 'avoid', f'reverted: {message}'
    if any(k in msg_lower for k in ['refactor', 'migrate', 'replace', 'switch']):
        return 'decision', f'architectural change: {message}'
    if any(k in msg_lower for k in ['fix:', 'bugfix', 'hotfix', 'workaround']):
        return 'failed', f'fixed issue: {message}'
    return 'pattern', f'commit: {message}'


def update_index(changed_files: list):
    try:
        from src.brain.file_indexer import incremental_update
        idx = incremental_update(changed_files)
        print(f'[mcp-brain] index updated: {idx.get("updated_files", 0)} files changed, {idx["total"]} total')
    except Exception as e:
        print(f'[mcp-brain] index update error: {e}')


def run(project: str):
    init_db()
    info = get_commit_info()
    if not info:
        return

    message = info.get('message', '')
    files = info.get('files', [])
    if not message:
        return

    category, content = classify_commit(message, files)
    result = store_memory(
        project=project, category=category, content=content,
        frequency=1, files_affected=len(files), explicit=False,
    )
    print(f'[mcp-brain] memory stored -> {result}')

    if files:
        update_index(files)


if __name__ == '__main__':
    project = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
    run(project)
