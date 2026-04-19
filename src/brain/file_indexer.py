import os
import re
import json
import time
from pathlib import Path

REPO_CWD = os.environ.get('MCP_BRAIN_REPO', os.getcwd())
INDEX_PATH = Path(REPO_CWD) / '.brain' / 'file_index.json'

IGNORE_DIRS = {'.git', '.brain', '__pycache__', 'node_modules', '.venv', 'venv', '.idea', 'dist', 'build', 'vendor', 'target'}
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.kt', '.rb', '.cs', '.cpp', '.c', '.h'}
MAX_FILE_SIZE = 500_000
MAX_REPO_FILES = 50_000


def _extract_tokens(text: str) -> set:
    '''Estrae token unici significativi.'''
    tokens = re.findall(r'[a-z_][a-z0-9_]{3,}', text.lower())
    return set(tokens)


def build_index() -> dict:
    '''Scansiona il repo e costruisce l indice keyword?file.'''
    root = Path(REPO_CWD)
    index = {'files': {}, 'built_at': time.time(), 'total': 0}
    count = 0

    for path in root.rglob('*'):
        if count >= MAX_REPO_FILES:
            break
        if not path.is_file():
            continue
        if path.suffix not in CODE_EXTENSIONS:
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue

        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
            rel = path.relative_to(root).as_posix()
            content = path.read_text(encoding='utf-8', errors='ignore')
            tokens = _extract_tokens(content) | _extract_tokens(rel)
            index['files'][rel] = list(tokens)[:200]
            count += 1
        except Exception:
            continue

    index['total'] = count
    save_index(index)
    return index


def save_index(index: dict):
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        json.dump(index, f)


def load_index() -> dict:
    if not INDEX_PATH.exists():
        return None
    try:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def get_or_build_index(max_age: int = 3600) -> dict:
    '''Carica indice esistente se fresco, altrimenti ricostruisce.'''
    index = load_index()
    if index and (time.time() - index.get('built_at', 0)) < max_age:
        return index
    return build_index()
