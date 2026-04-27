"""
STEP 2.4 — Tool MCP `brain_predict_files`.

Espone `predict_files_with_impact` a Claude Code con output YAML compatto che
include: file, confidence, score, source (text_match | graph_expansion), hops,
why, e (se use_semantic=True) semantic_score.

Uso dall'interno di `src/tools/mcp_tools.py`:

    from src.tools.predict_files_tool import register_predict_files_tool
    register_predict_files_tool(mcp)

Questo pattern evita di editare fisicamente la lista dei tool già definiti in
`mcp_tools.py`: basta aggiungere UNA riga di registrazione in coda.
"""
from __future__ import annotations

import time
import logging
from typing import Any, Dict, List

import yaml

from src.brain.file_predictor import predict_files_with_impact


def _format_predictions(results: List[Dict[str, Any]]) -> str:
    """Formatta la lista di predizioni come YAML leggibile da Claude."""
    if not results:
        return 'predictions: []\nhint: "try different keywords or run brain_init"'

    items = []
    for r in results:
        entry = {
            'file': r['file'],
            'confidence': r['confidence'],
            'score': r['score'],
            'source': r['source'],
            'hops': r['hops'],
            'why': r['why'],
        }
        if 'semantic_score' in r:
            entry['semantic_score'] = r['semantic_score']
        if 'seed' in r:
            entry['seed'] = r['seed']
        items.append(entry)

    return yaml.dump(
        {'predictions': items},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()


def predict_files_impl(
    title: str,
    body: str = '',
    max_hops: int = 2,
    top_k: int = 10,
    use_semantic: bool = True,
) -> str:
    """
    Implementazione pura (no decorators). Tornà stringa YAML.
    Eccezioni → stringa 'error: <msg>' per aderire al pattern degli altri tool.
    """
    try:
        if not title or not str(title).strip():
            return 'error: title is required'
        results = predict_files_with_impact(
            title=str(title),
            body=str(body or ''),
            max_hops=int(max_hops),
            top_k=int(top_k),
            use_semantic=bool(use_semantic),
        )
        return _format_predictions(results)
    except Exception as e:
        logging.exception('brain_predict_files failed')
        return f'error: {e}'


def register_predict_files_tool(mcp) -> None:
    """
    Registra il tool `brain_predict_files` sull'istanza FastMCP passata.

    Firma esposta a Claude:
        brain_predict_files(
            project: str,
            title: str,
            body: str = '',
            max_hops: int = 2,
            top_k: int = 10,
            use_semantic: bool = False,
        ) -> str   # YAML con predictions
    """
    @mcp.tool()
    def brain_predict_files(
        project: str,
        title: str,
        body: str = '',
        max_hops: int = 2,
        top_k: int = 10,
        use_semantic: bool = True,
    ) -> str:
        '''Predice i file probabilmente da modificare per un ticket/issue.
        Usa BM25 (symbols+identifiers con IDF) + espansione via code graph
        (imported_by / called_by). Se use_semantic=True e sentence-transformers
        è installato, aggiunge un rerank semantico.
        Ritorna YAML con: file, confidence, score, source, hops, why.'''
        start = time.time()
        logging.info(
            f'brain_predict_files START title={title!r} hops={max_hops} '
            f'top_k={top_k} semantic={use_semantic}'
        )
        try:
            result = predict_files_impl(
                title=title,
                body=body,
                max_hops=max_hops,
                top_k=top_k,
                use_semantic=use_semantic,
            )
            elapsed = time.time() - start
            logging.info(
                f'brain_predict_files END ({elapsed:.2f}s, {len(result)} chars)'
            )
            return result
        except Exception as e:
            elapsed = time.time() - start
            logging.error(
                f'brain_predict_files FAILED ({elapsed:.2f}s): {e}', exc_info=True
            )
            return f'error: {e}'
