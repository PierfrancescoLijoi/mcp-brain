"""
Layer semantico per il predictor .

Come funziona:

1. Di default, il layer è DISABILITATO: niente dipendenze attive,
   nessun modello caricato, zero costo runtime.

2. Quando `rerank()` viene chiamato:
   - Se `sentence-transformers` non è installato → ritorna i candidate
     invariati (fallback graceful)
   - Se `MCP_BRAIN_SEMANTIC=0` è nell'env → stessa cosa
   - Altrimenti carica il modello (cached singleton), embeddizza la query
     e i doc, calcola cosine similarity, e blenda con il BM25 score.

3. Il blend è "soft": `final = (1 - blend) * bm25_norm + blend * semantic`
   con `blend=0.3` di default. In questo modo BM25 resta dominante e il
   semantic serve a "raffinare il ranking" fra candidate con score BM25
   simili (tiebreaker informato).

Dipendenza opzionale installabile con:
    pip install sentence-transformers

Modello di default: all-MiniLM-L6-v2 (~80 MB, veloce, CPU-friendly, 384-dim).
"""
from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

# Modello di default: piccolo, veloce, CPU-friendly
DEFAULT_MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'

# Cache singleton del modello (thread-safe)
_MODEL_CACHE: Dict[str, Any] = {}
_MODEL_LOCK = threading.Lock()


# ------------------------------------------------------------------
# Availability
# ------------------------------------------------------------------
def is_available() -> bool:
    """True se il layer semantico è utilizzabile in questo processo."""
    # Kill-switch via env (utile in CI o per debug)
    if os.environ.get('MCP_BRAIN_SEMANTIC', '1') == '0':
        return False
    try:
        import sentence_transformers  # noqa: F401
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def _get_model(name: Optional[str] = None):
    name = name or DEFAULT_MODEL_NAME
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    with _MODEL_LOCK:
        if name in _MODEL_CACHE:
            return _MODEL_CACHE[name]
        from sentence_transformers import SentenceTransformer
        _MODEL_CACHE[name] = SentenceTransformer(name)
    return _MODEL_CACHE[name]


# ------------------------------------------------------------------
# Rerank API
# ------------------------------------------------------------------
def _build_doc_text(file_path: str, file_data: Dict[str, Any]) -> str:
    """
    Stringa "rappresentativa" di un file da embeddare.
    Combina: basename, primi 20 simboli, primi 20 identifier più significativi.
    """
    name = file_path.rsplit('/', 1)[-1]
    # Strippa estensione per non sprecare token su '.py' ecc.
    if '.' in name:
        name = name.rsplit('.', 1)[0]
    syms = list(file_data.get('symbols', []))[:20]
    idents = list(file_data.get('identifiers', []))[:20]
    return ' '.join([name] + syms + idents)


def rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    index: Optional[Dict[str, Any]] = None,
    blend: float = 0.3,
    model_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Riordina `candidates` (list di {file, score, ...}) con similarity semantica.

    - Se semantic non disponibile → ritorna candidates inalterata.
    - Se candidates è vuota → ritorna candidates inalterata.
    - Su QUALSIASI eccezione nel forward del modello → ritorna candidates
      inalterata (fallback graceful: meglio un ranking BM25 corretto che
      un crash).

    Muta gli item aggiungendo `semantic_score` (float in [0,1]).
    Aggiorna `score` con la media pesata (mantenuta sulla stessa scala
    del BM25 originale tramite riscalatura).
    """
    if not candidates:
        return candidates
    if not is_available():
        return candidates

    if index is None:
        try:
            from src.brain.file_indexer import get_or_build_index
            index = get_or_build_index()
        except Exception:
            return candidates
    if not index:
        return candidates

    files_meta = index.get('files', {})

    # Costruisci testi: [query, doc1, doc2, ...]
    texts = [query or '']
    for c in candidates:
        data = files_meta.get(c['file'], {})
        texts.append(_build_doc_text(c['file'], data))

    try:
        import numpy as np
        model = _get_model(model_name)
        emb = model.encode(texts, show_progress_bar=False)
        q = emb[0]
        docs = emb[1:]

        q_norm = float(np.linalg.norm(q)) + 1e-12
        doc_norms = np.linalg.norm(docs, axis=1) + 1e-12
        sims = (docs @ q) / (q_norm * doc_norms)
    except Exception:
        return candidates

    max_bm25 = max((c.get('score', 0.0) for c in candidates), default=0.0) or 1.0

    for c, sim in zip(candidates, sims):
        # Cosine teoricamente in [-1, 1], ma su testi brevi in pratica >= 0.
        # Clippiamo comunque a [0, 1] per avere blend stabile.
        sem = float(max(0.0, min(1.0, sim)))
        c['semantic_score'] = round(sem, 4)

        bm25_norm = c.get('score', 0.0) / max_bm25
        blended = (1.0 - blend) * bm25_norm + blend * sem
        # Riscala sulla stessa magnitudo del max BM25 per comparabilità
        c['score'] = round(blended * max_bm25, 4)

    candidates.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    return candidates
