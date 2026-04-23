"""
STEP 4.1 — Tool MCP `brain_get_ticket_context`: all-in-one per bootare un ticket.

Unifica in una sola chiamata:

  1. Fetch dell'issue (GitHub o injected) → titolo, body, labels
  2. Prediction dei file (BM25 + graph + semantic) con why+impact
  3. Estrazione dei symbols toccati dai file predetti (via code graph) per
     alimentare il conflict check
  4. Graduated conflict detection (signature / hard / soft) contro PR aperte
  5. Claim dei file (soft-claim) in modo che altri membri del team lo vedano
  6. Similar past tickets (retrieval locale dalle memorie del brain)

Output: YAML compatto con 5 sezioni chiare. Claude Code legge UN solo tool.

Tutte le sorgenti esterne (issue, PRs) sono iniettabili per test.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import yaml


# ------------------------------------------------------------------
# Symbol extraction dai file predetti
# ------------------------------------------------------------------
def _collect_my_symbols(predicted_files: List[Dict[str, Any]]) -> List[str]:
    """
    Estrae la lista di simboli "esportati" dai file predetti.
    Usa il code graph se disponibile: per ogni file, prende il suo `symbols`
    list dal grafo. Fallback silenzioso a [] se il grafo non esiste.
    """
    try:
        from src.brain.code_graph import load_graph
        graph = load_graph()
    except Exception:
        graph = None
    if not graph or 'files' not in graph:
        return []

    files_data = graph['files']
    symbols = set()
    for p in predicted_files:
        f = p.get('file') if isinstance(p, dict) else p
        entry = files_data.get(f)
        if entry:
            for s in entry.get('symbols', []):
                symbols.add(s)
    return sorted(symbols)


# ------------------------------------------------------------------
# Implementazione pura
# ------------------------------------------------------------------
def get_ticket_context_impl(
    project: str,
    issue_id: int,
    author: str,
    top_k_files: int = 5,
    top_k_similar: int = 5,
    max_hops: int = 2,
    do_claim: bool = True,
    issue: Optional[Dict[str, Any]] = None,
    prs_with_patches: Optional[List[Dict[str, Any]]] = None,
    similar_memories: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Ritorna YAML con le 5 sezioni. I parametri `issue`/`prs_with_patches`/
    `similar_memories` sono iniettabili: se None, vengono fetchati live.
    """
    try:
        # -------------------- 1. Issue --------------------
        if issue is None:
            from src.capture.github_reader import get_issue
            issue = get_issue(issue_id)
        if not issue or 'error' in issue:
            err = (issue or {}).get('error', 'unknown')
            return f'error loading issue: {err}'

        title = issue.get('title', '')
        body = issue.get('body', '') or ''

        # -------------------- 2. Predictions --------------------
        from src.brain.file_predictor import predict_files_with_impact
        predictions = predict_files_with_impact(
            title=title,
            body=body,
            max_hops=max_hops,
            top_k=top_k_files,
        )
        files_only = [p['file'] for p in predictions]

        # -------------------- 3. My symbols --------------------
        my_symbols = _collect_my_symbols(predictions)

        # -------------------- 4. Conflicts v2 --------------------
        from src.brain.conflict_detector_v2 import (
            detect_graduated_conflicts,
            build_graduated_warnings,
            guidance_from_conflicts,
        )
        if prs_with_patches is None:
            from src.capture.github_pr_patches import get_open_prs_with_patches
            prs_with_patches = get_open_prs_with_patches()

        conflicts = detect_graduated_conflicts(
            my_files=files_only,
            my_symbols=my_symbols,
            open_prs_with_patches=prs_with_patches,
            exclude_author=author,
        )
        warnings = build_graduated_warnings(conflicts)
        guidance = guidance_from_conflicts(conflicts)

        # -------------------- 5. Claim --------------------
        claim_info: Dict[str, Any] = {'claimed': False, 'reason': 'skipped'}
        if do_claim and files_only:
            try:
                from src.brain.claims_manager import claim_files
                claim_files(issue_id, files_only, author, title)
                claim_info = {'claimed': True, 'files': files_only[:5]}
            except Exception as e:
                claim_info = {'claimed': False, 'reason': f'claim error: {e}'}

        # -------------------- 6. Similar past tickets --------------------
        from src.brain.similar_tickets import find_similar_tickets
        similar = find_similar_tickets(
            project=project,
            title=title,
            body=body,
            predicted_files=files_only,
            exclude_ticket_id=issue_id,
            top_k=top_k_similar,
            memories=similar_memories,
        )

        # -------------------- 7. Log della predizione (STEP 5) --------------------
        # Registriamo la predizione per poterla riconciliare con l'outcome reale.
        # Fallback silenzioso: se il DB non è disponibile niente crashes.
        try:
            from src.brain.feedback_store import init_feedback_schema, log_prediction
            init_feedback_schema()
            log_prediction(
                project=project,
                ticket_id=issue_id,
                author=author,
                predicted_files=files_only,
                predicted_symbols=my_symbols,
                memories_shown=[s.get('memory_id') for s in similar
                                if s.get('memory_id') is not None],
                tool='brain_get_ticket_context',
            )
        except Exception:
            logging.warning('prediction log failed (non-critical)', exc_info=True)

        # -------------------- Output YAML --------------------
        output: Dict[str, Any] = {
            'ticket': {
                'id': issue.get('id', issue_id),
                'title': title,
                'labels': issue.get('labels', []),
            },
            'predicted_files': [
                {
                    'file': p['file'],
                    'confidence': p['confidence'],
                    'score': p['score'],
                    'source': p.get('source', 'text_match'),
                    'hops': p.get('hops', 0),
                    'why': p['why'],
                }
                for p in predictions
            ],
        }
        if my_symbols:
            output['my_symbols'] = my_symbols[:20]

        # Raggruppa i conflicts per severity
        conflicts_out: Dict[str, Any] = {}
        by_sev: Dict[str, List[Dict[str, Any]]] = {}
        for w in warnings:
            by_sev.setdefault(w['severity'], []).append(w)
        for sev in ('signature', 'hard', 'soft'):
            if by_sev.get(sev):
                conflicts_out[sev] = by_sev[sev]
        output['conflicts'] = conflicts_out or 'none'
        output['guidance'] = guidance
        output['claim'] = claim_info

        if similar:
            output['similar_past_tickets'] = [
                {
                    'ticket_id': s.get('ticket_id'),
                    'category': s.get('category'),
                    'similarity': s['similarity'],
                    'content': s['content'][:200],
                    'scope': (
                        f"{s.get('scope_type')}:{s.get('scope_value')}"
                        if s.get('scope_value') else s.get('scope_type')
                    ),
                }
                for s in similar
            ]

        return yaml.dump(
            output,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ).strip()

    except Exception as e:
        logging.exception('brain_get_ticket_context failed')
        return f'error: {e}'


# ------------------------------------------------------------------
# Registration MCP
# ------------------------------------------------------------------
def register_get_ticket_context_tool(mcp) -> None:
    """Registra brain_get_ticket_context sull'istanza FastMCP."""
    @mcp.tool()
    def brain_get_ticket_context(
        project: str,
        issue_id: int,
        author: str,
        top_k_files: int = 5,
        top_k_similar: int = 5,
        max_hops: int = 2,
        do_claim: bool = True,
    ) -> str:
        '''All-in-one boot di un ticket. Fetcha issue, predice i file
        (BM25+graph+semantic), rileva conflicts graduated contro PR aperte
        (signature/hard/soft), fa soft-claim dei file, recupera ticket
        passati simili. Ritorna YAML compatto con 5 sezioni:
        ticket / predicted_files / conflicts / claim / similar_past_tickets.'''
        start = time.time()
        logging.info(f'brain_get_ticket_context START issue={issue_id} author={author}')
        try:
            result = get_ticket_context_impl(
                project=project,
                issue_id=issue_id,
                author=author,
                top_k_files=top_k_files,
                top_k_similar=top_k_similar,
                max_hops=max_hops,
                do_claim=do_claim,
            )
            logging.info(
                f'brain_get_ticket_context END '
                f'({time.time() - start:.2f}s, {len(result)} chars)'
            )
            return result
        except Exception as e:
            logging.error(
                f'brain_get_ticket_context FAILED: {e}', exc_info=True
            )
            return f'error: {e}'
