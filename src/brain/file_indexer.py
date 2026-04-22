"""
File indexer con statistiche BM25.

Oltre al classico inverted index (term -> [files]), ogni index calcola:

- `df`          : document frequency per term (quanti file contengono il term)
- `doc_length`  : lunghezza "augmented" per file
                  = 3 * len(symbols) + 1 * len(identifiers)
                  (i simboli sono già pesati come 3x identifier)
- `avgdl`       : media di doc_length su tutti i file
- `total`       : N, numero di documenti

Questi valori sono richiesti dal predictor BM25 (STEP 2.1).
Si persistono insieme all'index in `file_index.json`.
"""
import os
import json
import time
from pathlib import Path

from src.brain.ast_indexer import extract_symbols, extract_identifiers
from src.storage.paths import INDEX_PATH

IGNORE_DIRS = {'.git', '.brain', '__pycache__', 'node_modules', '.venv', 'venv',
               '.idea', 'dist', 'build', 'vendor', 'target', '.next', '.nuxt'}
CODE_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs',
                   '.java', '.kt', '.rb', '.cs', '.cpp', '.c', '.h'}
MAX_FILE_SIZE = 500_000
MAX_REPO_FILES = 100_000

# Pesi per TF augmentation: un simbolo vale 3x un identifier
SYMBOL_WEIGHT = 3
IDENTIFIER_WEIGHT = 1


def _index_single_file(file_path: Path, rel: str) -> dict:
    """Indicizza un singolo file. Separa symbols (peso alto) da identifiers (peso basso)."""
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
    root = Path(os.environ.get('MCP_BRAIN_REPO', os.getcwd()))
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
    """Indice inverso: keyword -> list of {file, weight}."""
    inverted = {}
    for file, data in files_data.items():
        for sym in data.get('symbols', []):
            inverted.setdefault(sym, []).append({'file': file, 'weight': SYMBOL_WEIGHT})
        for ident in data.get('identifiers', []):
            inverted.setdefault(ident, []).append({'file': file, 'weight': IDENTIFIER_WEIGHT})
    return inverted


def compute_bm25_stats(files_data: dict) -> dict:
    """
    Calcola statistiche BM25 a partire dai files_data:

      df[term]          = numero di documenti che contengono il termine
      doc_length[file]  = 3*|symbols| + 1*|identifiers| (TF augmentation)
      avgdl             = media di doc_length su tutti i file
      total             = N (numero di documenti)

    Questo è l'input che predict_files_explained usa per calcolare
    idf(t) e il BM25 score per ogni (term, file).
    """
    df = {}
    doc_length = {}
    total = 0

    for file, data in files_data.items():
        total += 1
        syms = data.get('symbols', []) or []
        idents = data.get('identifiers', []) or []

        # Termini unici nel doc (l'index corrente memorizza già set-like lists)
        unique_terms = set(syms) | set(idents)
        for t in unique_terms:
            df[t] = df.get(t, 0) + 1

        # Doc length augmented
        doc_length[file] = SYMBOL_WEIGHT * len(syms) + IDENTIFIER_WEIGHT * len(idents)

    avgdl = (sum(doc_length.values()) / total) if total > 0 else 0.0

    return {
        'df': df,
        'doc_length': doc_length,
        'avgdl': avgdl,
        'total': total,
    }


def _finalize_index(files_data: dict) -> dict:
    """Costruisce il dict completo dell'index (files + inverted + stats BM25)."""
    stats = compute_bm25_stats(files_data)
    return {
        'files': files_data,
        'inverted': _build_inverted(files_data),
        'df': stats['df'],
        'doc_length': stats['doc_length'],
        'avgdl': stats['avgdl'],
        'total': stats['total'],
        'built_at': time.time(),
    }


def build_index() -> dict:
    """Full rebuild dell'indice."""
    files_data = {}
    for path, rel in _collect_files():
        data = _index_single_file(path, rel)
        if data:
            files_data[rel] = data

    index = _finalize_index(files_data)
    save_index(index)
    return index


def incremental_update(changed_files: list) -> dict:
    """Aggiorna solo i file modificati. Fallback a rebuild se indice non esiste."""
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

    # Ricalcola completamente inverted + stats BM25: sono derivati, costa poco
    # e garantisce coerenza su df/avgdl dopo delete/rename/update.
    new_index = _finalize_index(files_data)
    new_index['updated_files'] = updated
    save_index(new_index)
    return new_index


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
        # Backward-compat: se un vecchio index non ha df/avgdl, rebuild.
        if 'df' in index and 'avgdl' in index and 'doc_length' in index:
            return index
    return build_index()
