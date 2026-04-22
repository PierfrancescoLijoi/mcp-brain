"""
BM25 ranker per la predizione file da ticket.

Zero dipendenze esterne (solo stdlib). L'indice si costruisce dal code_graph
esistente (STEP 1.3) arricchendo i simboli con identifier estratti dal file
e token dal filename/path.

Formula classica BM25:
  BM25(D, Q) = Σ IDF(qi) * f(qi,D)*(k1+1) / (f(qi,D) + k1*(1-b+b*|D|/avgDL))

  IDF(qi) = ln((N - df(qi) + 0.5) / (df(qi) + 0.5) + 1)

Default parameters: k1=1.5, b=0.75 (valori canonici Robertson/Zaragoza 2004).

Design:
  - Index serializzato come JSON leggero (compatibile con il resto del progetto)
  - tokenize condiviso con similarity.py per consistenza (stopwords, camelCase
    → snake_case, lowercase)
  - Boost per tipo di termine (filename > symbol > module > identifier)
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.brain.similarity import STOPWORDS
from src.storage.paths import LOCAL_DIR

BM25_INDEX_PATH = LOCAL_DIR / 'bm25_index.json'

# Parametri BM25 canonici
K1 = 1.5
B = 0.75

# Boost per tipo di termine (moltiplicatore della term frequency)
BOOST_FILENAME = 5
BOOST_SYMBOL = 3
BOOST_MODULE_PATH = 2
BOOST_IDENTIFIER = 1

# Penalità per file di test: riducono lo score finale di questo fattore.
# Un file in tests/ matcha parole come 'jwt' 'auth' 'token' molte volte
# (mock, assert, fixture) senza essere il file "sorgente" che il ticket
# vuole modificare. Il boost inverso (0.3) li degrada in modo coerente.
TEST_FILE_PENALTY = 0.3

# Regex per riconoscere file di test
_TEST_FILE_PATTERNS = re.compile(
    r'(^|/)(tests?|__tests__|spec)/|(^|/)test_|_test\.|\.test\.|\.spec\.',
    re.IGNORECASE,
)


def is_test_file(rel_path: str) -> bool:
    """
    Euristica: un file è 'di test' se è in tests/, __tests__/, spec/,
    o il nome inizia con test_ / finisce con _test. / .test. / .spec.
    """
    return bool(_TEST_FILE_PATTERNS.search(rel_path))


# Minimo numero di caratteri per considerare un token
MIN_TOKEN_LEN = 3


# =================================================================
# TOKENIZATION
# =================================================================

_CAMEL_SPLIT = re.compile(r'(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
_NON_WORD = re.compile(r'[^a-zA-Z0-9_]+')


def _split_camel(word: str) -> List[str]:
    """'AuthService' → ['Auth', 'Service']; 'getUser' → ['get', 'User']"""
    return _CAMEL_SPLIT.split(word)


def tokenize_code(text: str) -> List[str]:
    """
    Tokenizzazione orientata al codice:
      - split su non-word chars
      - split camelCase/PascalCase
      - split snake_case
      - lowercase
      - rimuove stopwords
      - min 3 caratteri
    Ritorna lista (non set) per preservare term frequency.
    """
    if not text:
        return []
    tokens = []
    for raw in _NON_WORD.split(text):
        if not raw:
            continue
        # Split su underscore
        for part in raw.split('_'):
            if not part:
                continue
            # Split su camelCase
            for sub in _split_camel(part):
                sub_lower = sub.lower()
                if len(sub_lower) < MIN_TOKEN_LEN:
                    continue
                if sub_lower in STOPWORDS:
                    continue
                tokens.append(sub_lower)
    return tokens


def tokenize_query(text: str) -> List[str]:
    """Stessa tokenizzazione usata per i documenti (coerenza)."""
    return tokenize_code(text)


# =================================================================
# BUILD INDEX
# =================================================================

def _extract_doc_terms_from_graph_entry(file_path: str, entry: Dict,
                                         file_content: bytes = None) -> List[str]:
    """
    Estrae i termini di un file applicando i boost.
    Ripete un termine N volte per simulare la sua frequenza pesata.
    """
    terms = []

    # Filename tokens × BOOST_FILENAME
    filename_tokens = tokenize_code(Path(file_path).stem)
    for t in filename_tokens:
        terms.extend([t] * BOOST_FILENAME)

    # Module path tokens × BOOST_MODULE_PATH (escluso il file)
    path_parts = Path(file_path).parent.as_posix().split('/')
    for part in path_parts:
        for t in tokenize_code(part):
            terms.extend([t] * BOOST_MODULE_PATH)

    # Symbols (definiti nel file) × BOOST_SYMBOL
    for sym in entry.get('symbols', []):
        for t in tokenize_code(sym):
            terms.extend([t] * BOOST_SYMBOL)

    # Identifiers dal contenuto del file × BOOST_IDENTIFIER
    # Opzionale: se content disponibile estraggo TUTTI gli identificatori,
    # altrimenti uso solo quello che c'è nel grafo (symbols già coperti)
    if file_content:
        try:
            text = file_content.decode('utf-8', errors='ignore')
            for t in tokenize_code(text):
                terms.append(t)
        except Exception:
            pass

    return terms


def build_bm25_index(graph: Dict, repo_root: Path = None,
                     include_file_content: bool = True) -> Dict:
    """
    Costruisce l'indice BM25 dal code_graph.

    include_file_content=True arricchisce i termini con tutti gli identificatori
    del contenuto del file (non solo symbols). Più lento ma molto più accurato
    per predizioni su ticket con descrizioni lunghe.
    """
    import os
    started = time.perf_counter()
    root = repo_root or Path(os.environ.get('MCP_BRAIN_REPO', os.getcwd()))

    files_entries = graph.get('files', {})

    # Pass 1: estrai termini per ogni doc
    doc_terms: Dict[str, List[str]] = {}
    for rel_path, entry in files_entries.items():
        content = None
        if include_file_content:
            try:
                full = root / rel_path
                if full.is_file() and full.stat().st_size < 500_000:
                    content = full.read_bytes()
            except Exception:
                content = None
        terms = _extract_doc_terms_from_graph_entry(rel_path, entry, content)
        if terms:
            doc_terms[rel_path] = terms

    # Pass 2: term frequency per doc + doc frequency globale
    term_freq: Dict[str, Dict[str, int]] = {}  # {file: {term: count}}
    doc_freq: Dict[str, int] = {}              # {term: num_docs_containing}
    doc_lengths: Dict[str, int] = {}

    for rel_path, terms in doc_terms.items():
        tf: Dict[str, int] = {}
        for t in terms:
            tf[t] = tf.get(t, 0) + 1
        term_freq[rel_path] = tf
        doc_lengths[rel_path] = len(terms)
        for term in tf:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    # Pass 3: IDF precomputato per ogni termine
    n_docs = len(term_freq)
    idf: Dict[str, float] = {}
    for term, df in doc_freq.items():
        idf[term] = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)

    avg_doc_len = sum(doc_lengths.values()) / n_docs if n_docs else 0

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    return {
        'term_freq': term_freq,
        'idf': idf,
        'doc_lengths': doc_lengths,
        'avg_doc_len': avg_doc_len,
        'n_docs': n_docs,
        'stats': {
            'total_terms': len(doc_freq),
            'build_time_ms': elapsed_ms,
            'built_at': datetime.now(timezone.utc).isoformat(),
        },
    }


# =================================================================
# PERSISTENCE
# =================================================================

def save_bm25_index(index: Dict, path: Path = None) -> None:
    target = path or BM25_INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(index, f, separators=(',', ':'))


def load_bm25_index(path: Path = None) -> Optional[Dict]:
    target = path or BM25_INDEX_PATH
    if not target.exists():
        return None
    try:
        with open(target, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


# =================================================================
# SEARCH
# =================================================================

def search(index: Dict, query: str, top_k: int = 10,
           k1: float = K1, b: float = B,
           penalize_tests: bool = True) -> List[Tuple[str, float, Dict]]:
    """
    Ricerca BM25: ritorna top_k file ordinati per score decrescente.
    Ogni elemento è (file_path, score, explanation).

    explanation contiene i termini della query che hanno contribuito allo
    score, con il loro peso — usato dal predictor v2 per costruire il 'why'.

    penalize_tests=True applica TEST_FILE_PENALTY ai file di test, perché
    tipicamente il ticket riguarda il codice di produzione, non i test.
    Passa False per casi d'uso specifici come "fix test flakiness".
    """
    query_terms = tokenize_query(query)
    if not query_terms:
        return []

    # Deduplica la query ma preserva il count
    query_tf: Dict[str, int] = {}
    for t in query_terms:
        query_tf[t] = query_tf.get(t, 0) + 1

    term_freq = index['term_freq']
    idf = index['idf']
    doc_lengths = index['doc_lengths']
    avg_doc_len = index.get('avg_doc_len', 1.0) or 1.0

    scores: Dict[str, float] = {}
    per_doc_hits: Dict[str, Dict[str, float]] = {}  # per explanation

    for term, q_count in query_tf.items():
        term_idf = idf.get(term, 0.0)
        if term_idf <= 0:
            continue

        # Scorri solo i doc che contengono il termine (non scanniamo tutti)
        for doc, tf_map in term_freq.items():
            tf = tf_map.get(term, 0)
            if tf == 0:
                continue
            dl = doc_lengths.get(doc, 0)
            norm = 1 - b + b * (dl / avg_doc_len) if avg_doc_len else 1
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * norm
            contribution = term_idf * (numerator / denominator) * q_count

            scores[doc] = scores.get(doc, 0.0) + contribution
            per_doc_hits.setdefault(doc, {})[term] = round(contribution, 3)

    # Applico la penalità ai file di test DOPO aver calcolato i contributi
    # (così i top_terms nella explanation restano coerenti con il contributo
    # raw dei termini, non moltiplicati per la penalty)
    if penalize_tests:
        for doc in list(scores.keys()):
            if is_test_file(doc):
                scores[doc] *= TEST_FILE_PENALTY

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    results: List[Tuple[str, float, Dict]] = []
    for doc, score in ranked:
        hits = per_doc_hits.get(doc, {})
        # Tieni solo i top 3 termini contributori per spiegazione
        top_terms = sorted(hits.items(), key=lambda x: -x[1])[:3]
        explanation = {
            'matched_terms': [t for t, _ in top_terms],
            'score': round(score, 3),
            'is_test': is_test_file(doc),
        }
        results.append((doc, round(score, 4), explanation))
    return results


def get_or_build_bm25_index(graph: Dict, max_age_seconds: int = 3600,
                            repo_root: Path = None) -> Dict:
    """Carica l'indice se fresco, altrimenti lo rebuilds dal grafo."""
    idx = load_bm25_index()
    if idx:
        built_at_str = idx.get('stats', {}).get('built_at')
        if built_at_str:
            try:
                built_at = datetime.fromisoformat(built_at_str)
                age = (datetime.now(timezone.utc) - built_at).total_seconds()
                if age < max_age_seconds:
                    return idx
            except Exception:
                pass
    idx = build_bm25_index(graph, repo_root=repo_root)
    save_bm25_index(idx)
    return idx
