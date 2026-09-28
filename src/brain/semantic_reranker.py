"""
Layer semantico per il predictor.

Come funziona:

1. Di default, il layer è ATTIVO (`use_semantic=True` nei chiamanti).
   Il modello viene caricato lazy alla prima chiamata di `rerank()`,
   poi rimane in cache singleton thread-safe per tutto il processo.

2. Quando `rerank()` viene chiamato:
   - Se `sentence-transformers` non è installato → ritorna i candidate
     invariati (fallback graceful) e logga UN warning una-tantum.
   - Se `MCP_BRAIN_SEMANTIC=0` è nell'env → stessa cosa, con messaggio
     dedicato che cita il kill-switch.
   - Altrimenti carica il modello (cached singleton), embeddizza la query
     e i doc, calcola cosine similarity, e blenda con il BM25 score.

3. Il blend è "soft": `final = (1 - blend) * bm25_norm + blend * semantic`
   con `blend=0.3` di default. In questo modo BM25 resta dominante e il
   semantic serve a "raffinare il ranking" fra candidate con score BM25
   simili (tiebreaker informato).

Dipendenza obbligatoria (in `pyproject.toml > dependencies`):
    sentence-transformers, numpy

Kill-switch a runtime (utile in CI lean / container slim):
    export MCP_BRAIN_SEMANTIC=0     # bash/zsh
    $env:MCP_BRAIN_SEMANTIC = '0'   # PowerShell

Modello di default: all-MiniLM-L6-v2 (~80 MB, veloce, CPU-friendly, 384-dim).
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from typing import Any, Dict, List, Optional

# Modello di default: piccolo, veloce, CPU-friendly
DEFAULT_MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'

# Cache singleton del modello (thread-safe)
_MODEL_CACHE: Dict[str, Any] = {}
_MODEL_LOCK = threading.Lock()

# Flag per emettere il warning "lib non disponibile" UNA SOLA volta per processo.
# Esposto a livello modulo per poterlo resettare nei test.
_WARNED_UNAVAILABLE: bool = False
_WARN_LOCK = threading.Lock()


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


def _warn_unavailable_once() -> None:
    """
    Emette un `logging.warning` UNA volta per processo quando il rerank
    semantico viene richiesto ma il layer non è disponibile.

    Distingue due cause:
      - kill-switch attivo (`MCP_BRAIN_SEMANTIC=0`)
      - libreria mancante (sentence-transformers / numpy)

    Idempotente: dopo la prima emissione, no-op fino al reset esplicito di
    `_WARNED_UNAVAILABLE` (usato dai test).
    """
    global _WARNED_UNAVAILABLE
    if _WARNED_UNAVAILABLE:
        return
    with _WARN_LOCK:
        if _WARNED_UNAVAILABLE:
            return
        _WARNED_UNAVAILABLE = True

    if os.environ.get('MCP_BRAIN_SEMANTIC', '1') == '0':
        reason = "kill-switch attivo (env MCP_BRAIN_SEMANTIC=0)"
    else:
        reason = (
            "sentence-transformers o numpy non installati "
            "(pip install -e \".[semantic]\" oppure pip install sentence-transformers numpy)"
        )

    logging.warning(
        "[mcp-brain] Semantic reranker richiesto ma NON attivo: %s. "
        "Procedo con BM25+graph puro (fallback graceful). "
        "Questo warning viene emesso una sola volta per processo.",
        reason,
    )


def _get_device() -> str:
    """Prefer CUDA when available, unless explicitly overridden."""
    forced = os.environ.get("MCP_BRAIN_SEMANTIC_DEVICE")
    if forced:
        return forced

    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass

    return "cpu"


def _get_model(name: Optional[str] = None):
    name = name or DEFAULT_MODEL_NAME
    device = _get_device()
    cache_key = f"{name}::{device}"

    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    with _MODEL_LOCK:
        if cache_key in _MODEL_CACHE:
            return _MODEL_CACHE[cache_key]

        from sentence_transformers import SentenceTransformer

        _MODEL_CACHE[cache_key] = SentenceTransformer(name, device=device)

    return _MODEL_CACHE[cache_key]


# ------------------------------------------------------------------
# Rerank API
# ------------------------------------------------------------------
def _build_doc_text(
    file_path: str,
    file_data: Dict[str, Any],
    *,
    df: Optional[Dict[str, int]] = None,
    total_docs: Optional[int] = None,
) -> str:
    """
    Build a compact, deterministic role-aware representation for embedding.

    Full path components communicate architectural role. Symbols are stable and
    identifiers are ordered by inverse document frequency so domain concepts
    win over ubiquitous language/framework vocabulary.
    """
    path_without_ext = file_path.replace('\\', '/').rsplit('.', 1)[0]
    path_terms = re.findall(r'[A-Za-z0-9]+', path_without_ext.lower())[-8:]
    basename = path_without_ext.rsplit('/', 1)[-1].lower()
    syms = sorted(set(file_data.get('symbols', [])))[:20]
    idents = set(file_data.get('identifiers', []))
    df = df or {}
    total = max(int(total_docs or 0), 1)

    def identifier_priority(term: str) -> tuple[float, str]:
        frequency = max(int(df.get(term, total)), 1)
        idf = math.log((total + 1.0) / frequency)
        return (-idf, term)

    ranked_idents = sorted(idents, key=identifier_priority)[:20]
    parts = ['path', *path_terms, 'file', basename]
    if syms:
        parts.extend(['defines', *syms])
    if ranked_idents:
        parts.extend(['concepts', *ranked_idents])
    return ' '.join(parts)


def rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    index: Optional[Dict[str, Any]] = None,
    blend: float = 0.3,
    model_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Riordina `candidates` (list di {file, score, ...}) con similarity semantica.

    - Se semantic non disponibile → ritorna candidates inalterata + WARNING una-tantum.
    - Se candidates è vuota → ritorna candidates inalterata, NESSUN warning
      (non è un problema: solo nessun candidato da reranker).
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
        _warn_unavailable_once()
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
    df = index.get('df', {})
    total_docs = int(index.get('total', len(files_meta)))
    for c in candidates:
        data = files_meta.get(c['file'], {})
        texts.append(
            _build_doc_text(
                c['file'], data, df=df, total_docs=total_docs
            )
        )

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
