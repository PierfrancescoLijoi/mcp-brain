"""
STEP 5 — Reconciler: chiude il ciclo predizione → outcome.

Quando `record_outcome(ticket_id, outcome, actual_files)` viene chiamato,
`reconcile(project, ticket_id)`:

  1. Recupera la predizione loggata per quel ticket
  2. Calcola precision/recall dei file predetti vs quelli effettivamente
     toccati (intersezione / unione classici)
  3. Aggiorna i contatori `hit_count`/`miss_count` delle memorie mostrate:
     - Se outcome == 'completed' E precision >= HIT_PRECISION_THRESHOLD
       → memorie che erano state mostrate ricevono un HIT
     - Se outcome == 'reverted' → miss per TUTTE le memorie mostrate
       (il fix è fallito; il contesto che Claude ha usato includeva quelle
       memorie, quindi non le ha aiutate)
     - Se outcome == 'abandoned' → niente update (ticket chiuso senza esito)
  4. Auto-tuning delle memorie:
     - miss >= 3 consecutivi (miss > hit + TOLERANCE) → demote a 'suspect'
     - hit >= 3 consecutivi (hit > miss + TOLERANCE) → score += 0.1 (cap 1.0)
     - In caso di status già 'suspect', un hit extra riporta ad 'active'

Ritorna un report strutturato con le metriche + lista di memorie aggiornate.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.brain.feedback_store import (
    get_prediction_for_ticket,
    get_memory_counters,
    increment_memory_hit,
    increment_memory_miss,
)
from src.storage.db import get_connection


# Soglie di policy (valori conservativi: il sistema aggiusta lentamente)
HIT_PRECISION_THRESHOLD = 0.3
DEMOTE_MISS_DELTA = 3
PROMOTE_HIT_DELTA = 3
SCORE_BUMP = 0.1
SCORE_CAP = 1.0


# ------------------------------------------------------------------
# Metrics
# ------------------------------------------------------------------
def _precision_recall(
    predicted: List[str], actual: List[str]
) -> Dict[str, float]:
    pset = set(predicted or [])
    aset = set(actual or [])
    if not pset and not aset:
        return {'precision': 1.0, 'recall': 1.0, 'f1': 1.0,
                'tp': 0, 'fp': 0, 'fn': 0}
    tp = len(pset & aset)
    fp = len(pset - aset)
    fn = len(aset - pset)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        'precision': round(precision, 3),
        'recall': round(recall, 3),
        'f1': round(f1, 3),
        'tp': tp, 'fp': fp, 'fn': fn,
    }


# ------------------------------------------------------------------
# Auto-tuning
# ------------------------------------------------------------------
def _auto_tune_memory(memory_id: int) -> Dict[str, Any]:
    """
    Applica le regole di auto-tuning a una singola memoria.
    Ritorna un log dell'azione presa (o 'no-op' se niente cambia).
    """
    conn = get_connection()
    row = conn.execute(
        "SELECT id, category, status, score, hit_count, miss_count, content "
        "FROM memories WHERE id = ?",
        (memory_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {'memory_id': memory_id, 'action': 'not_found'}

    m = dict(row)
    hit = m.get('hit_count') or 0
    miss = m.get('miss_count') or 0
    status = m.get('status')
    score = m.get('score') or 0.0

    action = 'no-op'
    new_status = status
    new_score = score

    # 1. Demote se troppi miss
    if status == 'active' and (miss - hit) >= DEMOTE_MISS_DELTA:
        new_status = 'suspect'
        action = f'demoted_to_suspect (miss={miss}, hit={hit})'

    # 2. Promote: se suspect e ora ha più hit che miss (+tolerance), torna active
    elif status == 'suspect' and (hit - miss) >= PROMOTE_HIT_DELTA:
        new_status = 'active'
        new_score = min(SCORE_CAP, score + SCORE_BUMP)
        action = f'reactivated_from_suspect (hit={hit}, miss={miss})'

    # 3. Bump score se hit streak consistente (e memoria già active)
    elif status == 'active' and (hit - miss) >= PROMOTE_HIT_DELTA and score < SCORE_CAP:
        new_score = min(SCORE_CAP, score + SCORE_BUMP)
        action = f'score_bumped (hit={hit}, miss={miss}, {score}→{new_score})'

    if new_status != status or new_score != score:
        conn.execute(
            """
            UPDATE memories
            SET status = ?, score = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (new_status, new_score, memory_id),
        )
        conn.commit()

    conn.close()
    return {
        'memory_id': memory_id,
        'category': m.get('category'),
        'action': action,
        'hit_count': hit,
        'miss_count': miss,
        'status_before': status,
        'status_after': new_status,
        'score_before': score,
        'score_after': new_score,
    }


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def reconcile(
    project: str,
    ticket_id: int,
    outcome: str,
    actual_files: Optional[List[str]] = None,
    hit_precision_threshold: float = HIT_PRECISION_THRESHOLD,
) -> Dict[str, Any]:
    """
    Chiude il ciclo per un ticket. Chiamato subito dopo `record_outcome`.

    Strategia:
      - outcome='abandoned': skippa (niente feedback utile)
      - outcome='reverted': tutte le memorie mostrate prendono un miss
      - outcome='completed': calcola precision/recall; se precision >=
        threshold, memorie mostrate prendono un hit; altrimenti un miss
    """
    prediction = get_prediction_for_ticket(project, ticket_id)
    if not prediction:
        return {
            'ticket_id': ticket_id,
            'status': 'skipped',
            'reason': 'no prediction logged',
        }

    predicted = prediction.get('predicted_files', [])
    memories_shown = prediction.get('memories_shown', []) or []

    metrics = _precision_recall(predicted, actual_files or [])

    updates: List[Dict[str, Any]] = []

    if outcome == 'abandoned':
        return {
            'ticket_id': ticket_id,
            'status': 'skipped',
            'reason': 'abandoned',
            'metrics': metrics,
        }

    # Decidiamo se i memory sono da premiare o penalizzare
    if outcome == 'reverted':
        feedback_type = 'miss'
    elif outcome == 'completed':
        feedback_type = 'hit' if metrics['precision'] >= hit_precision_threshold else 'miss'
    else:
        return {
            'ticket_id': ticket_id,
            'status': 'error',
            'reason': f'unknown outcome: {outcome}',
        }

    for mem_id in memories_shown:
        if feedback_type == 'hit':
            increment_memory_hit(mem_id)
        else:
            increment_memory_miss(mem_id)
        updates.append(_auto_tune_memory(mem_id))

    return {
        'ticket_id': ticket_id,
        'status': 'reconciled',
        'outcome': outcome,
        'feedback_type': feedback_type,
        'metrics': metrics,
        'memories_updated': updates,
    }


# ------------------------------------------------------------------
# Aggregate stats (used by tool + STEP 7 observability)
# ------------------------------------------------------------------
def get_feedback_stats(project: str, since_days: int = 30) -> Dict[str, Any]:
    """
    Statistiche aggregate precision/recall/outcomes per un progetto.

    Usato da STEP 7 per dashboards e da STEP 5 tool.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT t.ticket_id, t.outcome, t.actual_files, p.predicted_files
        FROM ticket_outcomes t
        LEFT JOIN predictions_log p
          ON p.project = t.project AND p.ticket_id = t.ticket_id
        WHERE t.project = ?
          AND t.created_at >= datetime('now', ?)
        ORDER BY t.id DESC
        """,
        (project, f'-{since_days} days'),
    ).fetchall()
    conn.close()

    import json as _json
    outcomes_count = {'completed': 0, 'reverted': 0, 'abandoned': 0}
    precisions: List[float] = []
    recalls: List[float] = []

    for r in rows:
        d = dict(r)
        outcomes_count[d['outcome']] = outcomes_count.get(d['outcome'], 0) + 1
        if d.get('predicted_files') and d['outcome'] != 'abandoned':
            try:
                pred = _json.loads(d['predicted_files'])
                actual = _json.loads(d.get('actual_files') or '[]')
                m = _precision_recall(pred, actual)
                precisions.append(m['precision'])
                recalls.append(m['recall'])
            except Exception:
                continue

    avg_prec = (sum(precisions) / len(precisions)) if precisions else None
    avg_rec = (sum(recalls) / len(recalls)) if recalls else None

    return {
        'project': project,
        'window_days': since_days,
        'total_outcomes': sum(outcomes_count.values()),
        'outcomes': outcomes_count,
        'avg_precision': round(avg_prec, 3) if avg_prec is not None else None,
        'avg_recall': round(avg_rec, 3) if avg_rec is not None else None,
        'samples': len(precisions),
    }
