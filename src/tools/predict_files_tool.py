"""
Tool MCP `brain_predict_files`: localizer appreso multi-canale con fallback
BM25/grafo, evidence cards e verifier locale OpenAI-compatible opzionale.

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

from src.brain.evidence import VERIFY_RULES
from src.brain.file_predictor import predict_files_ranked
from src.brain.llm_verifier import verify_predictions


class _BlockDumper(yaml.SafeDumper):
    """Multi-line strings (evidence cards) as readable `|` blocks."""


_BlockDumper.add_representer(
    str,
    lambda d, v: d.represent_scalar(
        'tag:yaml.org,2002:str', v, style='|' if '\n' in v else None
    ),
)


def _plan_advice(plan: Dict[str, Any]) -> str:
    k, hit = plan['read_first'], round(plan['expected_hit'] * 100)
    where = plan.get('calibrated_on', 'benchmark')
    if plan['confidence'] == 'low':
        return (f'Low confidence: the file to change is in the top {k} about {hit}% of the time '
                f'(measured on {where}). Confirm with search or the evidence cards before editing.')
    return f'Read the top {k} file(s) first: hit rate {hit}% measured on {where}.'


def _format_predictions(
    results: List[Dict[str, Any]], verification: Dict[str, Any] | None = None
) -> str:
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
        if 'evidence' in r:
            entry['evidence'] = r['evidence']
        items.append(entry)

    doc = {'predictions': items}
    # Calibrated only for the ranker's own order: omitted if the verifier moved the top file.
    plan = results[0].get('plan')
    if plan:
        doc = {'plan': {**plan, 'advice': _plan_advice(plan)}, **doc}
    if any('evidence' in i for i in items):
        doc = {'verify': VERIFY_RULES, **doc}
    if verification is not None:
        doc = {'verification': verification, **doc}
    return yaml.dump(
        doc,
        Dumper=_BlockDumper,
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
    evidence: bool = True,
    verify_local: bool = False,
) -> str:
    """
    Implementazione pura (no decorators). Tornà stringa YAML.
    Eccezioni → stringa 'error: <msg>' per aderire al pattern degli altri tool.
    """
    try:
        if not title or not str(title).strip():
            return 'error: title is required'
        results = predict_files_ranked(
            title=str(title),
            body=str(body or ''),
            max_hops=int(max_hops),
            top_k=int(top_k),
            use_semantic=bool(use_semantic),
            evidence=bool(evidence or verify_local),
        )
        verification = None
        if verify_local and results:
            issue = f'{title}\n{body or ""}'.strip()
            results, outcome = verify_predictions(issue, results)
            verification = outcome.to_dict()
        return _format_predictions(results, verification)
    except Exception as e:
        logging.exception('brain_predict_files failed')
        return f'error: {e}'


def register_predict_files_tool(mcp) -> None:
    """
    Registra il tool `brain_predict_files` sull'istanza FastMCP passata.

    Firma esposta al client MCP:
        brain_predict_files(
            project: str,
            title: str,
            body: str = '',
            max_hops: int = 2,
            top_k: int = 10,
            use_semantic: bool = True,
            evidence: bool = True,
            verify_local: bool = False,
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
        evidence: bool = True,
        verify_local: bool = False,
    ) -> str:
        '''Predice i file probabilmente da modificare per un ticket/issue.
        Nei repository Git usa il localizer multi-linguaggio (BM25 multi-canale,
        definizioni, traceback, messaggi citati, import graph, storia Git,
        fusi da LambdaMART). Il modello incluso è validato su Python; gli altri
        linguaggi sono supportati ma richiedono una promotion evaluation propria.
        Se il localizer non è disponibile usa BM25 + code graph.
        Con evidence=True (default) ogni file ha una evidence card (outline +
        codice rilevante) e 'verify' spiega come scegliere il file da
        modificare: leggi le card e scegli tu, senza aprire ogni file.
        Con verify_local=True, un endpoint LLM OpenAI-compatible configurato
        tramite MCP_BRAIN_VERIFIER_URL/MODEL riordina le card interamente
        on-prem; errori e astensioni sono espliciti e il retriever resta fallback.
        Nel localizer, 'plan' dice quanti file leggere per primi (read_first)
        e con quale hit rate misurato su issue mai viste (expected_hit), in base
        al margine tra primo e secondo candidato; confidence 'low' = incerto.
        calibrated_on dice dove è stato misurato: dopo `mcp-brain calibrate`
        è la storia Git di questo repository.
        Ritorna YAML con: plan, file, confidence, score, source, hops, why.'''
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
                evidence=evidence,
                verify_local=verify_local,
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
