import os
import json
import time
from pathlib import Path
from src.brain.ast_indexer import extract_symbols, extract_identifiers

REPO_CWD = os.environ.get('MCP_BRAIN_REPO', os.getcwd())
INDEX_PATH = Path(REPO_CWD) / '.brain' / 'file_index.json'

IGNORE_DIRS = {'.git', '.brain', '__pycache__', 'node_modules', '.venv', 'venv',
               '.idea', 'dist', 'build', 'vendor', 'target', '.next', '.nuxt'}
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs',
                   '.java', '.kt', '.rb', '.cs', '.cpp', '.c', '.h'}
MAX_FILE_SIZE = 500_000
MAX_REPO_FILES = 100_000


def _index_single_file(file_path: Path, rel: str) -> dict:
    '''Indicizza un singolo file. Separa symbols (peso alto) da identifiers (peso basso).'''
    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        symbols = extract_symbols(file_path, content)
        identifiers = extract_identifiers(content) - symbols
        return {
            'symbols': list(symbols)[:100],
            'identifiers': list(identifiers)[:300],
            'mtime': file_path.stat().st_mtime,
        }
    except Exception:
        return None


def _collect_files():
    root = Path(REPO_CWD)
    files = []
    for path in root.rglob('*'):
        if len(files) >= MAX_REPO_FILES:
            break
        if not path.is_file() or path.suffix not in CODE_EXTENSIONS:
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
        except Exception:
            continue
        files.append((path, path.relative_to(root).as_posix()))
    return files


def _build_inverted(files_data: dict) -> dict:
    '''Indice inverso: keyword -> list of files.'''
    inverted = {}
    for file, data in files_data.items():
        for sym in data.get('symbols', []):
            inverted.setdefault(sym, []).append({'file': file, 'weight': 3})
        for ident in data.get('identifiers', []):
            inverted.setdefault(ident, []).append({'file': file, 'weight': 1})
    return inverted


def build_index() -> dict:
    '''Full rebuild dell indice.'''
    files_data = {}
    for path, rel in _collect_files():
        data = _index_single_file(path, rel)
        if data:
            files_data[rel] = data

    index = {
        'files': files_data,
        'inverted': _build_inverted(files_data),
        'built_at': time.time(),
        'total': len(files_data),
    }
    save_index(index)
    return index


def incremental_update(changed_files: list) -> dict:
    '''Aggiorna solo i file modificati. Fallback a rebuild se indice non esiste.'''
    index = load_index()
    if not index:
        return build_index()

    root = Path(REPO_CWD)
    files_data = index.get('files', {})
    updated = 0

    for rel in changed_files:
        if any(part in IGNORE_DIRS for part in rel.split('/')):
            continue
        file_path = root / rel
        if not file_path.exists():
            files_data.pop(rel, None)
            updated += 1
            continue
        if file_path.suffix not in CODE_EXTENSIONS:
            continue
        data = _index_single_file(file_path, rel)
        if data:
            files_data[rel] = data
            updated += 1

    index['files'] = files_data
    index['inverted'] = _build_inverted(files_data)
    index['built_at'] = time.time()
    index['total'] = len(files_data)
    save_index(index)
    index['updated_files'] = updated
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
    index = load_index()
    if index and (time.time() - index.get('built_at', 0)) < max_age:
        return index
    return build_index()
