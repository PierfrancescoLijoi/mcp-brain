"""
Code graph builder: costruisce un grafo bidirezionale delle dipendenze
tra file del repo partendo dalle FileExtraction prodotte da extractor.py.

Dati persistiti in .brain/local/code_graph.json:
  {
    "files": {
      "<path>": {
        "language": str,
        "symbols": [str],           # nomi dei simboli definiti
        "imports_to": [{"module", "resolved", "external", "names"}],
        "imported_by": [str],       # REVERSE — chi mi importa
        "calls_out": [{"name", "line", "resolves_to": [str]}],
        "called_by": [{"file", "symbol"}],  # REVERSE — chi chiama un mio simbolo
        "mtime": float
      }
    },
    "symbol_index": {"<name>": [<file_path>, ...]},
    "stats": {"total_files", "total_symbols", "build_time_ms", "built_at"}
  }

Il grafo è la base per:
  - predictor v2 (STEP 2): impact radius nella predizione file
  - patch guard (STEP 6): vedere chi viene rotto da un cambio
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.brain.extractor import extract, FileExtraction
from src.storage.paths import LOCAL_DIR

GRAPH_PATH = LOCAL_DIR / 'code_graph.json'

# Estensioni da indicizzare (superset di quelle supportate dagli extractor)
SUPPORTED_EXTENSIONS = {
    '.py', '.pyi',
    '.js', '.jsx', '.mjs', '.cjs',
    '.ts', '.tsx',
    '.go',
    '.rs',
    '.java',
    '.cs',
}

# Directory da ignorare durante la scansione
IGNORE_DIRS = {
    '.git', '.brain', '__pycache__', 'node_modules', '.venv', 'venv',
    '.idea', '.vscode', 'dist', 'build', 'vendor', 'target',
    '.next', '.nuxt', '.pytest_cache', '.mypy_cache', 'coverage',
}

MAX_FILE_SIZE = 500_000
MAX_REPO_FILES = 100_000


# =================================================================
# SCANSIONE FILESYSTEM
# =================================================================

def _repo_root() -> Path:
    return Path(os.environ.get('MCP_BRAIN_REPO', os.getcwd()))


def _collect_code_files(repo_root: Path) -> List[Path]:
    """File di codice del repo, escluse dir da ignorare e file troppo grandi."""
    files = []
    for path in repo_root.rglob('*'):
        if len(files) >= MAX_REPO_FILES:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
        except Exception:
            continue
        files.append(path)
    return files


# =================================================================
# RISOLUZIONE IMPORT → PATH
# =================================================================

def _resolve_python_import(
    module: str,
    names: List[str],
    importer_rel: str,
    all_files: Set[str],
) -> Optional[str]:
    """
    Risolve un import Python in un path relativo al repo_root.
    Gestisce assoluti (src.db.users) e relativi (., .foo, ..pkg).
    Ritorna None se external/non risolvibile.
    """
    if not module:
        # `from . import foo` senza submodulo: module = "" or "."
        return None

    # Relative: "." | ".foo" | "..foo.bar"
    if module.startswith('.'):
        # Conta i dots iniziali per risalire N livelli
        n_dots = len(module) - len(module.lstrip('.'))
        rest = module[n_dots:]
        importer_dir = Path(importer_rel).parent
        # n_dots=1 → stesso package; n_dots=2 → parent; ...
        target_dir = importer_dir
        for _ in range(n_dots - 1):
            target_dir = target_dir.parent
        if rest:
            target_rel = str(target_dir / rest.replace('.', '/'))
        else:
            target_rel = str(target_dir)
        return _first_existing_python_module(target_rel, all_files)

    # Assoluto: "src.db.users" → "src/db/users"
    target_rel = module.replace('.', '/')
    return _first_existing_python_module(target_rel, all_files)


def _first_existing_python_module(base_rel: str, all_files: Set[str]) -> Optional[str]:
    """Prova <base>.py poi <base>/__init__.py. Ritorna il primo che esiste."""
    base_rel = base_rel.replace('\\', '/').lstrip('/')
    for candidate in (f'{base_rel}.py', f'{base_rel}/__init__.py'):
        if candidate in all_files:
            return candidate
    return None


def _resolve_js_import(
    module: str,
    importer_rel: str,
    all_files: Set[str],
    ts_mode: bool,
) -> Optional[str]:
    """
    Risolve un import JS/TS. Solo relative (./foo, ../foo) sono risolte.
    Bare imports (react, lodash) sono external.
    """
    if not module or not module.startswith('.'):
        return None

    importer_dir = Path(importer_rel).parent
    # Normalizza il path senza risolvere i .. (funziona rel-only)
    target = (importer_dir / module).as_posix()
    # Rimuovi ./  e normalizza
    parts = []
    for p in target.split('/'):
        if p in ('', '.'):
            continue
        if p == '..':
            if parts:
                parts.pop()
        else:
            parts.append(p)
    base = '/'.join(parts)

    # Prova estensioni: TS ha priorità su JS in ts_mode
    extensions_priority = (
        ('.tsx', '.ts', '.jsx', '.js', '.mjs', '.cjs')
        if ts_mode else
        ('.jsx', '.js', '.mjs', '.cjs', '.tsx', '.ts')
    )

    for ext in extensions_priority:
        cand = base + ext
        if cand in all_files:
            return cand

    # Prova come directory con index.*
    for ext in extensions_priority:
        cand = f'{base}/index{ext}'
        if cand in all_files:
            return cand

    return None


def _resolve_import(
    language: str,
    module: str,
    names: List[str],
    importer_rel: str,
    all_files: Set[str],
) -> Optional[str]:
    """Dispatcher di risoluzione."""
    if language == 'python':
        return _resolve_python_import(module, names, importer_rel, all_files)
    if language in ('javascript', 'typescript', 'tsx'):
        ts_mode = language in ('typescript', 'tsx')
        return _resolve_js_import(module, importer_rel, all_files, ts_mode=ts_mode)
    # Go, Rust, Java, C#: external per ora
    return None


# =================================================================
# BUILDER
# =================================================================

def build_graph(repo_root: Path = None) -> Dict:
    """
    Costruisce il grafo completo del repo. Operazione O(N files).
    Ritorna il dict già serializzabile (non fa save).
    """
    started = time.perf_counter()
    root = repo_root or _repo_root()
    paths = _collect_code_files(root)
    rel_paths = [p.relative_to(root).as_posix() for p in paths]
    all_files_set = set(rel_paths)

    # Pass 1: extract di ogni file
    extractions: Dict[str, FileExtraction] = {}
    mtimes: Dict[str, float] = {}
    for path, rel in zip(paths, rel_paths):
        try:
            mtimes[rel] = path.stat().st_mtime
        except Exception:
            mtimes[rel] = 0.0
        r = extract(path)
        if r is not None:
            extractions[rel] = r

    # Pass 2: symbol index globale (per risolvere called_by)
    symbol_index: Dict[str, List[str]] = {}
    for rel, ext in extractions.items():
        for sym in ext.symbols:
            # Indicizza solo simboli pubblici per ridurre rumore
            if sym.is_public:
                symbol_index.setdefault(sym.name, []).append(rel)

    # Pass 3: costruzione entry per ogni file con imports risolti e calls risolte
    files_data: Dict[str, Dict] = {}
    for rel, ext in extractions.items():
        imports_to = []
        for imp in ext.imports:
            resolved = _resolve_import(
                ext.language, imp.module, imp.names, rel, all_files_set
            )
            imports_to.append({
                'module': imp.module,
                'resolved': resolved,
                'external': resolved is None,
                'names': imp.names,
            })

        calls_out = []
        for call in ext.calls:
            # Il nome potrebbe essere "foo" o "obj.method" - risolviamo sul segmento finale
            last_segment = call.name.rsplit('.', 1)[-1]
            resolves_to = symbol_index.get(last_segment, [])
            # escludo self-references
            resolves_to = [r for r in resolves_to if r != rel]
            calls_out.append({
                'name': call.name,
                'line': call.line,
                'resolves_to': resolves_to,
            })

        files_data[rel] = {
            'language': ext.language,
            'symbols': [s.name for s in ext.symbols],
            'imports_to': imports_to,
            'imported_by': [],     # popolato in pass 4
            'calls_out': calls_out,
            'called_by': [],       # popolato in pass 4
            'mtime': mtimes.get(rel, 0.0),
        }

    # Pass 4: reverse indexes (imported_by, called_by)
    for rel, data in files_data.items():
        for imp in data['imports_to']:
            if imp['resolved'] and imp['resolved'] in files_data:
                files_data[imp['resolved']]['imported_by'].append(rel)
        for call in data['calls_out']:
            for target in call['resolves_to']:
                if target in files_data:
                    files_data[target]['called_by'].append({
                        'file': rel,
                        'symbol': call['name'],
                    })

    # Deduplica reverse lists
    for data in files_data.values():
        data['imported_by'] = sorted(set(data['imported_by']))
        # dedupe called_by conservando prima occorrenza
        seen = set()
        dedup = []
        for cb in data['called_by']:
            key = (cb['file'], cb['symbol'])
            if key not in seen:
                seen.add(key)
                dedup.append(cb)
        data['called_by'] = dedup

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    try:
        from src.brain.cochange_graph import build_cochange_graph
        cochange = build_cochange_graph(root)
    except Exception:
        cochange = {}

    return {
        'files': files_data,
        'symbol_index': symbol_index,
        'cochange': cochange,
        'stats': {
            'total_files': len(files_data),
            'total_symbols': sum(len(v) for v in symbol_index.values()),
            'cochange_files': len(cochange),
            'build_time_ms': elapsed_ms,
            'built_at': datetime.now(timezone.utc).isoformat(),
        },
    }


# =================================================================
# PERSISTENZA
# =================================================================

def save_graph(graph: Dict, path: Path = None) -> None:
    target = path or GRAPH_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(graph, f, separators=(',', ':'))


def load_graph(path: Path = None) -> Optional[Dict]:
    target = path or GRAPH_PATH
    if not target.exists():
        return None
    try:
        with open(target, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def get_or_build_graph(max_age_seconds: int = 3600, repo_root: Path = None) -> Dict:
    """Se il grafo esiste e non è troppo vecchio lo carica, altrimenti rebuilds."""
    graph = load_graph()
    if graph:
        built_at_str = graph.get('stats', {}).get('built_at')
        if built_at_str:
            try:
                built_at = datetime.fromisoformat(built_at_str)
                age = (datetime.now(timezone.utc) - built_at).total_seconds()
                if age < max_age_seconds:
                    return graph
            except Exception:
                pass
    graph = build_graph(repo_root)
    save_graph(graph)
    return graph


# =================================================================
# QUERY API — usata da predictor v2 (STEP 2) e patch guard (STEP 6)
# =================================================================

def get_imported_by(graph: Dict, file: str) -> List[str]:
    """File che importano `file`."""
    return graph.get('files', {}).get(file, {}).get('imported_by', [])


def get_callers(graph: Dict, file: str) -> List[Dict]:
    """File che chiamano uno dei simboli esportati da `file`."""
    return graph.get('files', {}).get(file, {}).get('called_by', [])


def get_impact_radius(graph: Dict, file: str, max_hops: int = 2) -> Dict:
    """
    Calcola l'impact radius di un file: chi dipende da lui direttamente
    (1 hop) e transitivamente (up to max_hops).
    Ritorna:
      {
        'direct': [file1, file2, ...],
        'transitive': [fileN, ...],
        'hops': {file1: 1, file2: 2, ...},
        'affected_symbols': [sym1, sym2, ...]
      }
    """
    files = graph.get('files', {})
    if file not in files:
        return {'direct': [], 'transitive': [], 'hops': {}, 'affected_symbols': []}

    hops: Dict[str, int] = {}
    queue = [(file, 0)]
    visited = {file}

    while queue:
        current, depth = queue.pop(0)
        if depth >= max_hops:
            continue
        neighbors: Set[str] = set()
        data = files.get(current, {})
        # chi importa current
        neighbors.update(data.get('imported_by', []))
        # chi chiama simboli di current
        for cb in data.get('called_by', []):
            neighbors.add(cb['file'])
        for nb in neighbors:
            if nb in visited:
                continue
            visited.add(nb)
            hops[nb] = depth + 1
            queue.append((nb, depth + 1))

    direct = sorted([f for f, h in hops.items() if h == 1])
    transitive = sorted([f for f, h in hops.items() if h > 1])
    affected_symbols = files.get(file, {}).get('symbols', [])

    return {
        'direct': direct,
        'transitive': transitive,
        'hops': hops,
        'affected_symbols': affected_symbols,
    }


def get_symbol_definitions(graph: Dict, symbol_name: str) -> List[str]:
    """File che definiscono un simbolo con quel nome."""
    return list(graph.get('symbol_index', {}).get(symbol_name, []))


# =================================================================
# INCREMENTAL UPDATE
# =================================================================

def _remove_file_from_reverse_indexes(graph: Dict, removed_file: str) -> None:
    """
    Rimuove tutte le tracce di `removed_file` dai reverse index degli altri file.
    Usato sia quando un file è cancellato sia quando viene ri-estratto (prima di
    riaggiungerlo con i nuovi reverse).
    """
    files = graph['files']
    file_data = files.get(removed_file)
    if not file_data:
        return

    # Per ogni file che avevamo come imports_to.resolved, togli removed_file dai suoi imported_by
    for imp in file_data.get('imports_to', []):
        target = imp.get('resolved')
        if target and target in files:
            files[target]['imported_by'] = [
                x for x in files[target]['imported_by'] if x != removed_file
            ]

    # Per ogni file che avevamo in calls_out.resolves_to, togli da called_by le entry di removed_file
    for call in file_data.get('calls_out', []):
        for target in call.get('resolves_to', []):
            if target in files:
                files[target]['called_by'] = [
                    cb for cb in files[target]['called_by']
                    if cb.get('file') != removed_file
                ]


def _remove_symbols_from_index(graph: Dict, file: str, old_symbols: List[str]) -> None:
    """Pulisce symbol_index rimuovendo file dai simboli che non possiede più."""
    symbol_index = graph.setdefault('symbol_index', {})
    for sym_name in old_symbols:
        if sym_name in symbol_index:
            symbol_index[sym_name] = [f for f in symbol_index[sym_name] if f != file]
            if not symbol_index[sym_name]:
                del symbol_index[sym_name]


def _add_symbols_to_index(graph: Dict, file: str, extraction: FileExtraction) -> None:
    """Aggiunge i simboli pubblici della nuova estrazione al symbol_index."""
    symbol_index = graph.setdefault('symbol_index', {})
    for sym in extraction.symbols:
        if sym.is_public:
            entries = symbol_index.setdefault(sym.name, [])
            if file not in entries:
                entries.append(file)


def _apply_reverse_indexes_for_file(graph: Dict, file: str) -> None:
    """
    Dopo che la entry di `file` è aggiornata, propaga i suoi reverse:
    - aggiunge `file` a imported_by dei target risolti
    - aggiunge entry a called_by dei target dei calls_out
    """
    files = graph['files']
    file_data = files.get(file)
    if not file_data:
        return

    for imp in file_data.get('imports_to', []):
        target = imp.get('resolved')
        if target and target in files:
            imported_by = files[target].setdefault('imported_by', [])
            if file not in imported_by:
                imported_by.append(file)

    for call in file_data.get('calls_out', []):
        for target in call.get('resolves_to', []):
            if target in files:
                called_by = files[target].setdefault('called_by', [])
                # dedup su (file, symbol)
                key = (file, call['name'])
                if not any((cb.get('file'), cb.get('symbol')) == key for cb in called_by):
                    called_by.append({'file': file, 'symbol': call['name']})


def _backfill_reverse_indexes_for_new_file(graph: Dict, new_file: str) -> None:
    """
    Quando un file NUOVO viene aggiunto al grafo, scandisce tutte le entry
    esistenti per trovare chi lo importa/chiama e popola correttamente
    imported_by e called_by della nuova entry.

    Necessario perché quando incremental processa più file in batch,
    l'ordine non è deterministico: se A viene processato prima di B
    (dove A importa B), al momento del processing di A, B non esiste
    ancora e il link non si crea. Il backfill risolve guardando "chi punta
    a me" dopo che tutte le entry sono in place.
    """
    files = graph['files']
    new_file_data = files.get(new_file)
    if new_file_data is None:
        return

    imported_by = set(new_file_data.get('imported_by', []))
    called_by = list(new_file_data.get('called_by', []))
    called_by_keys = {(cb.get('file'), cb.get('symbol')) for cb in called_by}

    for other_file, other_data in files.items():
        if other_file == new_file:
            continue
        # imports
        for imp in other_data.get('imports_to', []):
            if imp.get('resolved') == new_file:
                imported_by.add(other_file)
        # calls
        for call in other_data.get('calls_out', []):
            if new_file in call.get('resolves_to', []):
                key = (other_file, call['name'])
                if key not in called_by_keys:
                    called_by_keys.add(key)
                    called_by.append({'file': other_file, 'symbol': call['name']})

    new_file_data['imported_by'] = sorted(imported_by)
    new_file_data['called_by'] = called_by


def update_graph_incremental(
    graph: Dict,
    changed_files: List[str],
    repo_root: Path = None,
) -> Dict:
    """
    Aggiorna il grafo solo per i file specificati.
    - Se il file esiste: ri-estrae e aggiorna entry + reverse indexes
    - Se il file è stato cancellato: rimuove entry e pulisce reverse indexes
    - Ritorna il grafo aggiornato (muta anche in-place)

    Complessità: O(changed_files * avg_imports) invece di O(all_files).
    """
    if not changed_files:
        return graph

    root = repo_root or _repo_root()
    files = graph.setdefault('files', {})

    # Snapshot dell'elenco corrente di path (per la risoluzione import)
    all_files_set: Set[str] = set(files.keys())
    # Aggiungo eventuali nuovi file che stiamo introducendo ora
    for rel in changed_files:
        if (root / rel).is_file():
            all_files_set.add(rel)

    updated = 0
    removed = 0

    for rel in changed_files:
        rel = rel.replace('\\', '/')
        # Skip paths che non ci interessano
        if any(part in IGNORE_DIRS for part in rel.split('/')):
            continue
        suffix = Path(rel).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            continue

        full = root / rel
        old_data = files.get(rel)

        # Caso 1: file cancellato dal disco
        if not full.is_file():
            if old_data is not None:
                _remove_file_from_reverse_indexes(graph, rel)
                _remove_symbols_from_index(graph, rel, old_data.get('symbols', []))
                del files[rel]
                all_files_set.discard(rel)
                removed += 1
            continue

        # Caso 2: file modificato o nuovo
        # 2a. pulisci reverse indexes dalla vecchia versione (se esisteva)
        if old_data is not None:
            _remove_file_from_reverse_indexes(graph, rel)
            _remove_symbols_from_index(graph, rel, old_data.get('symbols', []))

        # 2b. ri-estrai
        extraction = extract(full)
        if extraction is None:
            # Estrazione fallita: rimuovi entry se c'era
            if old_data is not None:
                files.pop(rel, None)
                all_files_set.discard(rel)
                removed += 1
            continue

        # 2c. mtime
        try:
            mtime = full.stat().st_mtime
        except Exception:
            mtime = 0.0

        # 2d. aggiungi simboli al symbol_index
        _add_symbols_to_index(graph, rel, extraction)

        # 2e. risolvi imports_to e calls_out usando all_files_set e symbol_index aggiornato
        imports_to = []
        for imp in extraction.imports:
            resolved = _resolve_import(
                extraction.language, imp.module, imp.names, rel, all_files_set
            )
            imports_to.append({
                'module': imp.module,
                'resolved': resolved,
                'external': resolved is None,
                'names': imp.names,
            })

        symbol_index = graph.get('symbol_index', {})
        calls_out = []
        for call in extraction.calls:
            last_segment = call.name.rsplit('.', 1)[-1]
            resolves_to = [
                f for f in symbol_index.get(last_segment, []) if f != rel
            ]
            calls_out.append({
                'name': call.name,
                'line': call.line,
                'resolves_to': resolves_to,
            })

        # 2f. preserva eventuali imported_by/called_by che OTHER files hanno già
        # creato per noi (sono cumulativi: sono un aspetto degli altri, non del nostro file
        # — ma noi li memorizziamo sulla entry target per efficienza di lookup)
        is_new_file = old_data is None
        files[rel] = {
            'language': extraction.language,
            'symbols': [s.name for s in extraction.symbols],
            'imports_to': imports_to,
            'imported_by': old_data.get('imported_by', []) if old_data else [],
            'calls_out': calls_out,
            'called_by': old_data.get('called_by', []) if old_data else [],
            'mtime': mtime,
        }

        # 2g. propaga i nuovi reverse verso i target
        _apply_reverse_indexes_for_file(graph, rel)

        # 2h. se è un file NUOVO, backfill: cerca chi già lo importa/chiama
        # tra i file esistenti. Serve quando si processano batch con ordine
        # non deterministico (A importa B, A processato prima di B).
        if is_new_file:
            _backfill_reverse_indexes_for_new_file(graph, rel)

        updated += 1

    # Deduplica reverse lists per sicurezza
    for data in files.values():
        data['imported_by'] = sorted(set(data['imported_by']))
        seen = set()
        dedup = []
        for cb in data.get('called_by', []):
            key = (cb.get('file'), cb.get('symbol'))
            if key not in seen:
                seen.add(key)
                dedup.append(cb)
        data['called_by'] = dedup

    # Aggiorna stats
    graph['stats'] = {
        'total_files': len(files),
        'total_symbols': sum(len(v) for v in graph.get('symbol_index', {}).values()),
        'build_time_ms': graph.get('stats', {}).get('build_time_ms', 0),
        'built_at': datetime.now(timezone.utc).isoformat(),
        'last_incremental': {
            'updated': updated,
            'removed': removed,
            'at': datetime.now(timezone.utc).isoformat(),
        },
    }

    return graph


def update_and_save(changed_files: List[str], repo_root: Path = None) -> Dict:
    """
    Convenience: carica il grafo, applica incremental, salva.
    Se il grafo non esiste fa full build.
    Chiamato dal git-hook post-commit.
    """
    graph = load_graph()
    if graph is None:
        graph = build_graph(repo_root)
    else:
        update_graph_incremental(graph, changed_files, repo_root)
    save_graph(graph)
    return graph


# =================================================================
# INCREMENTAL UPDATE
# =================================================================

def incremental_update(
    graph: Dict,
    changed_files: List[str],
    repo_root: Path = None,
) -> Dict:
    """
    Aggiorna il grafo per i soli file cambiati, senza ricostruire tutto.

    Per ogni file cambiato:
      - se esiste sul FS: ri-estrae e aggiorna la sua entry
      - se non esiste (delete): rimuove l'entry e tutti i reference

    Dopo gli updates per-file, ricomputa i reverse indexes (imported_by,
    called_by) solo per i file del "touch set" = cambiati + loro vicini.

    Ritorna il grafo aggiornato. Se il grafo input è None o sentinel di
    mancato caricamento, fa full build come fallback.
    """
    started = time.perf_counter()

    if not graph or 'files' not in graph:
        # Nessun grafo valido → full build
        new_graph = build_graph(repo_root)
        save_graph(new_graph)
        return new_graph

    root = repo_root or _repo_root()
    files_data = graph['files']
    symbol_index = graph.get('symbol_index', {})

    # Colleziona tutti i path del repo (per la risoluzione import)
    all_fs_files = {p.relative_to(root).as_posix() for p in _collect_code_files(root)}

    # Touch set: file cambiati + loro vicini (pre e post update)
    touch_set: Set[str] = set()

    # Preserva la lista dei file che importavano/chiamavano i file che cambiano
    # così dopo possiamo ricomputarne i reverse.
    for rel in changed_files:
        rel = rel.replace('\\', '/')  # normalizza per Windows
        touch_set.add(rel)
        # neighbors nel grafo vecchio
        if rel in files_data:
            touch_set.update(files_data[rel].get('imported_by', []))
            touch_set.update(
                cb['file'] for cb in files_data[rel].get('called_by', [])
            )
            touch_set.update(
                imp['resolved']
                for imp in files_data[rel].get('imports_to', [])
                if imp.get('resolved')
            )
            for call in files_data[rel].get('calls_out', []):
                touch_set.update(call.get('resolves_to', []))

    # 1. Per ogni file cambiato, aggiorna la sua entry (o rimuovila)
    updated = 0
    removed = 0
    for rel in changed_files:
        rel = rel.replace('\\', '/')
        abs_path = root / rel

        if not abs_path.exists():
            # File rimosso → togli dal graph + symbol index
            if rel in files_data:
                # Rimuovi i simboli del file dal symbol_index
                for sym in files_data[rel].get('symbols', []):
                    if sym in symbol_index:
                        symbol_index[sym] = [f for f in symbol_index[sym] if f != rel]
                        if not symbol_index[sym]:
                            del symbol_index[sym]
                del files_data[rel]
                removed += 1
            continue

        # File esiste: ri-estraelo
        if abs_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if any(part in IGNORE_DIRS for part in abs_path.parts):
            continue

        ext = extract(abs_path)
        if ext is None:
            continue

        # Rimuovi i vecchi simboli dal symbol_index
        if rel in files_data:
            for old_sym in files_data[rel].get('symbols', []):
                if old_sym in symbol_index:
                    symbol_index[old_sym] = [
                        f for f in symbol_index[old_sym] if f != rel
                    ]
                    if not symbol_index[old_sym]:
                        del symbol_index[old_sym]

        # Aggiungi i nuovi simboli (solo pubblici)
        for sym in ext.symbols:
            if sym.is_public:
                if sym.name not in symbol_index:
                    symbol_index[sym.name] = []
                if rel not in symbol_index[sym.name]:
                    symbol_index[sym.name].append(rel)

        # Risolvi gli import del file aggiornato
        imports_to = []
        for imp in ext.imports:
            resolved = _resolve_import(
                ext.language, imp.module, imp.names, rel, all_fs_files
            )
            imports_to.append({
                'module': imp.module,
                'resolved': resolved,
                'external': resolved is None,
                'names': imp.names,
            })

        calls_out = []
        for call in ext.calls:
            last_segment = call.name.rsplit('.', 1)[-1]
            resolves_to = symbol_index.get(last_segment, [])
            resolves_to = [r for r in resolves_to if r != rel]
            calls_out.append({
                'name': call.name,
                'line': call.line,
                'resolves_to': resolves_to,
            })

        try:
            mtime = abs_path.stat().st_mtime
        except Exception:
            mtime = 0.0

        files_data[rel] = {
            'language': ext.language,
            'symbols': [s.name for s in ext.symbols],
            'imports_to': imports_to,
            'imported_by': [],   # sarà ricalcolato dopo
            'calls_out': calls_out,
            'called_by': [],     # sarà ricalcolato dopo
            'mtime': mtime,
        }

        # Aggiorna touch_set con i nuovi vicini
        touch_set.update(
            imp['resolved'] for imp in imports_to if imp.get('resolved')
        )
        for call in calls_out:
            touch_set.update(call.get('resolves_to', []))

        updated += 1

    # 2. Ricomputa i reverse indexes SOLO per i file nel touch_set
    # Reset dei reverse per i file nel touch set
    for rel in touch_set:
        if rel in files_data:
            files_data[rel]['imported_by'] = []
            files_data[rel]['called_by'] = []

    # Popola i reverse facendo uno scan completo ma scrivendo solo
    # nei file del touch set (la scrittura è il costo, non la lettura)
    for rel, data in files_data.items():
        for imp in data['imports_to']:
            target = imp.get('resolved')
            if target and target in files_data and target in touch_set:
                files_data[target]['imported_by'].append(rel)
        for call in data['calls_out']:
            for target in call.get('resolves_to', []):
                if target in files_data and target in touch_set:
                    files_data[target]['called_by'].append({
                        'file': rel,
                        'symbol': call['name'],
                    })

    # Deduplica reverse per i file touchati
    for rel in touch_set:
        if rel not in files_data:
            continue
        files_data[rel]['imported_by'] = sorted(set(files_data[rel]['imported_by']))
        seen = set()
        dedup = []
        for cb in files_data[rel]['called_by']:
            key = (cb['file'], cb['symbol'])
            if key not in seen:
                seen.add(key)
                dedup.append(cb)
        files_data[rel]['called_by'] = dedup

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    graph['files'] = files_data
    graph['symbol_index'] = symbol_index
    graph['stats'] = {
        'total_files': len(files_data),
        'total_symbols': sum(len(v) for v in symbol_index.values()),
        'build_time_ms': elapsed_ms,
        'built_at': datetime.now(timezone.utc).isoformat(),
        'last_update_type': 'incremental',
        'last_updated_files': updated,
        'last_removed_files': removed,
        'last_touch_set_size': len(touch_set),
    }

    return graph


def smart_rebuild(
    changed_files: List[str] = None,
    max_age_seconds: int = 3600,
    max_incremental_files: int = 50,
    repo_root: Path = None,
) -> Dict:
    """
    Strategia intelligente per aggiornare il grafo:
      - Nessun grafo esistente o troppo vecchio → full build
      - Troppi file cambiati (> max_incremental_files) → full build
      - Altrimenti → incremental_update

    Ritorna sempre un grafo aggiornato e salvato su disco.
    """
    graph = load_graph()

    # Determina se serve full rebuild
    needs_full = False
    reason = 'incremental'

    if graph is None:
        needs_full = True
        reason = 'no-existing-graph'
    else:
        built_at_str = graph.get('stats', {}).get('built_at')
        if built_at_str:
            try:
                built_at = datetime.fromisoformat(built_at_str)
                age = (datetime.now(timezone.utc) - built_at).total_seconds()
                if age > max_age_seconds:
                    needs_full = True
                    reason = f'stale-graph ({int(age)}s > {max_age_seconds}s)'
            except Exception:
                needs_full = True
                reason = 'invalid-timestamp'
        else:
            needs_full = True
            reason = 'missing-timestamp'

        if changed_files and len(changed_files) > max_incremental_files:
            needs_full = True
            reason = f'too-many-changes ({len(changed_files)} > {max_incremental_files})'

    if needs_full:
        graph = build_graph(repo_root)
        graph['stats']['last_update_type'] = 'full'
        graph['stats']['last_rebuild_reason'] = reason
    else:
        graph = incremental_update(graph, changed_files or [], repo_root)

    save_graph(graph)
    return graph
