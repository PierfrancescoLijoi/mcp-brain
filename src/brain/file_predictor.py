"""
STEP 2.1 (BM25 + IDF) e STEP 2.2 (graph expansion).

BM25 (STEP 2.1)
---------------
Ogni (query_term, file) riceve un punteggio:

    score(t, f) = idf(t) * (tf(t,f) * (k1+1)) / (tf(t,f) + k1 * (1 - b + b * dl(f)/avgdl))

con:
    idf(t)   = ln( (N - df(t) + 0.5) / (df(t) + 0.5) + 1 )   # Okapi BM25 smoothed
    tf(t,f)  = 3 se t è fra i symbols di f
               1 se t è fra gli identifiers di f
               0 altrimenti                                   # TF augmentation
    dl(f)    = 3*|symbols(f)| + |identifiers(f)|
    avgdl    = media di dl su tutti i file
    N        = numero di file indicizzati
    k1=1.5, b=0.75                                           # defaults standard

In più: filename match -> bonus additivo post-BM25 proporzionale al max BM25.
Lo score finale del file è la somma degli score per term + eventuale filename boost.

Graph expansion (STEP 2.2)
--------------------------
`predict_files_with_impact` prende i top-K seed di BM25 e li espande via code graph
(`get_impact_radius`). I file vicini (hop 1 / 2) ricevono uno score derivato dal
seed con decadimento per distanza:

    hop=0 (seed)     : score BM25 originale (source='text_match')
    hop=1 (diretto)  : seed_score * 0.35    (source='graph_expansion')
    hop=2 (transit.) : seed_score * 0.15    (source='graph_expansion')

Se un file è sia seed BM25 sia scoperto via graph, resta 'text_match' ma il suo
score viene incrementato dall'espansione (non duplicato: preserviamo la sorgente
più forte).
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from src.brain.file_indexer import get_or_build_index
from src.brain.ranking_features import extract_query_features, noise_penalty, score_path_features

# ------------------------------------------------------------------
# Parametri BM25 e pesatura
# ------------------------------------------------------------------
BM25_K1 = 1.5
BM25_B = 0.75

# Soglia operativa: il peso "symbol" parte da 2 per distinguerlo da identifier (=1)
SYMBOL_WEIGHT_THRESHOLD = 2

# Filename boost: frazione del max BM25 del turno (0.6 = "pesa quasi quanto un
# match rilevante", ma dipende dal corpus). Tenuto additivo, non moltiplicativo.
FILENAME_BOOST_RATIO = 0.6

# Expansion graph: decadimento per hop distance
HOP_DECAY = {1: 0.35, 2: 0.15, 3: 0.075}

# Soglie relative per la confidence label
CONF_HIGH = 0.70
CONF_MEDIUM = 0.40

STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'have', 'will',
    'should', 'would', 'could', 'been', 'when', 'where', 'which', 'while',
    'about', 'into', 'onto', 'issue', 'ticket', 'please', 'need', 'needs',
    'want', 'wants', 'make', 'makes', 'using', 'use', 'uses', 'add', 'adds',
    'fix', 'fixes', 'update', 'updates', 'feature', 'features',
}


# ------------------------------------------------------------------
# Keyword extraction
# ------------------------------------------------------------------
def _extract_keywords(text: str) -> set:
    words = re.findall(r'[a-z_][a-z0-9_]{3,}', text.lower())
    return set(w for w in words if w not in STOPWORDS)


# ------------------------------------------------------------------
# BM25 math
# ------------------------------------------------------------------
def _idf(df: int, total_docs: int) -> float:
    """Okapi BM25 IDF (smoothed, sempre >= 0)."""
    if total_docs <= 0:
        return 0.0
    return math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)


def _bm25_tf_component(tf: float, dl: float, avgdl: float) -> float:
    """Componente TF normalizzata di BM25 per un singolo (term, file)."""
    if tf <= 0:
        return 0.0
    denom = tf + BM25_K1 * (1.0 - BM25_B + BM25_B * (dl / avgdl if avgdl > 0 else 1.0))
    if denom == 0:
        return 0.0
    return (tf * (BM25_K1 + 1.0)) / denom


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------
def predict_files_from_issue(title: str, body: str = '') -> list:
    """Legacy API: ritorna solo lista file (backward-compat)."""
    return [p['file'] for p in predict_files_explained(title, body)]


def predict_files_explained(
    title: str,
    body: str = '',
    index: Optional[Dict[str, Any]] = None,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    Ranking BM25 dei file rispetto a titolo+body. Ritorna al massimo `top_k` item
    con struttura:
        {
          'file': str,
          'score': float,   # BM25 score (+ filename boost) grezzo
          'confidence': 'high'|'medium'|'low',
          'why': str,
          'matches': {'symbol': [...], 'identifier': [...], 'filename': [...]}
        }

    `index` è iniettabile per test: se None usa get_or_build_index().
    """
    features = extract_query_features(title, body)
    keyword_weights = features.weighted_terms
    # Backward-compatible fallback for very small synthetic tests.
    if not keyword_weights:
        keyword_weights = {kw: 1.0 for kw in _extract_keywords(f'{title} {body}')}
    if not keyword_weights:
        return []

    idx = index if index is not None else get_or_build_index()
    if not idx or not idx.get('inverted'):
        return []

    inverted: Dict[str, List[Dict[str, Any]]] = idx['inverted']
    files_meta: Dict[str, Any] = idx.get('files', {})
    df_map: Dict[str, int] = idx.get('df', {})
    doc_length: Dict[str, float] = idx.get('doc_length', {})
    avgdl: float = float(idx.get('avgdl', 0.0)) or 1.0
    total_docs: int = int(idx.get('total', len(files_meta)))

    # Se un vecchio index non ha df/avgdl, non possiamo calcolare BM25 →
    # fallback graceful: torniamo struttura vuota (l'utente vedrà il rebuild
    # al prossimo build_index).
    if not df_map or not doc_length or total_docs == 0:
        return []

    scores: Dict[str, Dict[str, Any]] = {}  # file -> aggregated entry

    for kw, q_weight in keyword_weights.items():
        entries = inverted.get(kw, [])
        df = df_map.get(kw, len(entries)) or len(entries)
        if df == 0:
            continue
        idf = _idf(df, total_docs)
        if idf <= 0:
            continue

        for entry in entries:
            file = entry['file']
            tf = float(entry['weight'])  # 3 per symbol, 1 per identifier
            dl = float(doc_length.get(file, avgdl))
            bm25_contrib = idf * _bm25_tf_component(tf, dl, avgdl)
            if bm25_contrib <= 0:
                continue

            slot = scores.setdefault(file, {
                'score': 0.0,
                'matches': {},
                'bm25_terms': 0,
            })
            slot['score'] += bm25_contrib * float(q_weight)
            slot['bm25_terms'] += 1

            reason_type = 'symbol' if tf >= SYMBOL_WEIGHT_THRESHOLD else 'identifier'
            slot['matches'].setdefault(reason_type, []).append(kw)

    # Filename boost: additivo, proporzionale al max BM25 corrente
    max_bm25 = max((s['score'] for s in scores.values()), default=0.0)
    filename_boost = max_bm25 * FILENAME_BOOST_RATIO if max_bm25 > 0 else 1.0

    for kw, q_weight in keyword_weights.items():
        for file in files_meta.keys():
            if kw in file.lower():
                slot = scores.setdefault(file, {'score': 0.0, 'matches': {}, 'bm25_terms': 0})
                slot['score'] += filename_boost * min(float(q_weight), 5.0)
                slot['matches'].setdefault('filename', []).append(kw)

    # Strong path/module/test-to-source features. These can create candidates even
    # when a path-like issue mention has no exact symbol match in the inverted index.
    path_unit = max(max_bm25, 1.0)
    for file in files_meta.keys():
        path_raw, path_reasons = score_path_features(file, features)
        if path_raw <= 0:
            continue
        slot = scores.setdefault(file, {'score': 0.0, 'matches': {}, 'bm25_terms': 0})
        # Keep path score additive but bounded relative to BM25 scale.
        slot['score'] += path_unit * path_raw / 3.0
        slot['matches'].setdefault('path', []).extend(path_reasons)

    # Soft penalties for noisy files after all positive evidence is aggregated.
    for file, data in list(scores.items()):
        factor, penalty_reasons = noise_penalty(file, data.get('matches', {}))
        if factor != 1.0:
            data['score'] *= factor
            data['matches'].setdefault('penalty', []).extend(penalty_reasons)

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda x: x[1]['score'], reverse=True)
    max_score = ranked[0][1]['score']

    results = []
    for file, data in ranked[:top_k]:
        score = data['score']
        if score <= 0:
            continue
        ratio = (score / max_score) if max_score > 0 else 0.0
        if ratio >= CONF_HIGH:
            conf = 'high'
        elif ratio >= CONF_MEDIUM:
            conf = 'medium'
        else:
            conf = 'low'

        why_parts = []
        matches = data['matches']
        if 'symbol' in matches:
            syms = sorted(set(matches['symbol']))[:3]
            why_parts.append(f"matched symbol(s) {', '.join(syms)}")
        if 'filename' in matches:
            fns = sorted(set(matches['filename']))[:1]
            why_parts.append(f"filename matches {fns[0]}")
        if 'path' in matches:
            # Preserve reason priority from score_path_features instead of
            # sorting alphabetically.
            why_parts.append(matches['path'][0])
        if 'identifier' in matches and 'symbol' not in matches:
            ids = sorted(set(matches['identifier']))[:2]
            why_parts.append(f"identifier match: {', '.join(ids)}")
        if 'penalty' in matches:
            why_parts.append(sorted(set(matches['penalty']))[0])

        results.append({
            'file': file,
            'confidence': conf,
            'why': '; '.join(why_parts) if why_parts else 'keyword match',
            'score': round(score, 4),
            'matches': {k: sorted(set(v)) for k, v in matches.items()},
            'breakdown': {
                'bm25_terms': data.get('bm25_terms', 0),
                'query_features': {
                    'paths': list(features.file_paths),
                    'modules': list(features.dotted_modules),
                    'symbols': list(features.symbols)[:10],
                    'test_source_candidates': list(features.test_source_candidates),
                },
            },
        })

    return results


# ------------------------------------------------------------------
# STEP 2.2 — Graph expansion
# ------------------------------------------------------------------
def _load_graph_safe():
    """Carica il code graph se esiste, altrimenti None (fallback graceful)."""
    try:
        from src.brain.code_graph import load_graph
        return load_graph()
    except Exception:
        return None


def predict_files_with_impact(
    title: str,
    body: str = '',
    top_k_seeds: int = 3,
    max_hops: int = 2,
    top_k: int = 10,
    use_semantic: bool = True,
    index: Optional[Dict[str, Any]] = None,
    graph: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Predizione "v2" = BM25 seeds + graph expansion (+ semantic rerank opzionale).

    1. Calcola ranking BM25 (primary seeds).
    2. Prende i primi `top_k_seeds` seed e calcola `get_impact_radius` per ciascuno.
    3. I file scoperti ricevono score = seed_score * HOP_DECAY[hop].
    4. Se `use_semantic=True` e il layer è disponibile, ri-ranka con cosine
       similarity (blend 70/30 BM25/semantic). Altrimenti no-op.
    5. Se `max_hops == 0` o graph non disponibile → identico a predict_files_explained.

    Ogni item include:
      file, score, confidence, why, source ('text_match' | 'graph_expansion'),
      hops (0 per seed, 1..max_hops per vicini), seed (se scoperto via graph).
      Se use_semantic=True e attivo: 'semantic_score' aggiuntivo.
    """
    seeds = predict_files_explained(title, body, index=index, top_k=max(top_k, top_k_seeds * 5))
    if not seeds:
        return []

    # Inizializza merged con i seed (source='text_match', hops=0)
    merged: Dict[str, Dict[str, Any]] = {}
    for s in seeds:
        merged[s['file']] = {
            'file': s['file'],
            'score': s['score'],
            'confidence': s['confidence'],
            'why': s['why'],
            'source': 'text_match',
            'hops': 0,
            'matches': s.get('matches', {}),
        }

    if max_hops > 0:
        g = graph if graph is not None else _load_graph_safe()
        if g and 'files' in g:
            from src.brain.code_graph import get_impact_radius

            for seed in seeds[:top_k_seeds]:
                seed_file = seed['file']
                seed_score = seed['score']
                if seed_score <= 0:
                    continue
                radius = get_impact_radius(g, seed_file, max_hops=max_hops)
                hops_map = radius.get('hops', {})

                for dep_file, hop in hops_map.items():
                    if hop <= 0:
                        continue
                    decay = HOP_DECAY.get(hop, 0.1)
                    added = seed_score * decay

                    if dep_file in merged:
                        # Già in lista (magari come seed o scoperto da altro seed):
                        # accumuliamo lo score, ma NON degradiamo la sorgente.
                        merged[dep_file]['score'] += added
                        # Se ancora 'graph_expansion' e arriva un hop più piccolo,
                        # aggiorna hops al minimo
                        if merged[dep_file]['source'] == 'graph_expansion':
                            merged[dep_file]['hops'] = min(merged[dep_file]['hops'], hop)
                    else:
                        merged[dep_file] = {
                            'file': dep_file,
                            'score': added,
                            'confidence': 'medium' if hop == 1 else 'low',
                            'why': f"impact of '{seed_file}' (hop={hop})",
                            'source': 'graph_expansion',
                            'hops': hop,
                            'seed': seed_file,
                            'matches': {},
                        }

    ranked = sorted(merged.values(), key=lambda x: x['score'], reverse=True)

    # Ricalcola confidence relative sul ranking finale per i 'text_match'
    if ranked:
        top_score = ranked[0]['score']
        for item in ranked:
            if item['source'] == 'text_match' and top_score > 0:
                ratio = item['score'] / top_score
                if ratio >= CONF_HIGH:
                    item['confidence'] = 'high'
                elif ratio >= CONF_MEDIUM:
                    item['confidence'] = 'medium'
                else:
                    item['confidence'] = 'low'

    for item in ranked:
        item['score'] = round(item['score'], 4)

    # STEP 2.3 — semantic rerank opzionale (no-op se lib non installata)
    if use_semantic:
        try:
            from src.brain.semantic_reranker import rerank as semantic_rerank
            idx_for_rerank = index if index is not None else get_or_build_index()
            query_text = f'{title} {body}'.strip()
            # Reranka solo i primi 2*top_k per limitare I/O del modello
            head = ranked[:max(top_k * 2, 10)]
            tail = ranked[len(head):]
            head = semantic_rerank(query_text, head, index=idx_for_rerank)
            ranked = head + tail
        except Exception:
            pass  # fallback: tieni il ranking BM25 + graph

    return ranked[:top_k]
