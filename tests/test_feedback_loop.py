"""Test STEP 5 — feedback store + reconciler + auto-tuning."""
import json
import pytest

from src.brain.feedback_store import (
    init_feedback_schema,
    log_prediction,
    record_outcome,
    get_prediction_for_ticket,
    get_outcomes_for_project,
    increment_memory_hit,
    increment_memory_miss,
    get_memory_counters,
)
from src.brain.feedback_reconciler import (
    reconcile,
    get_feedback_stats,
    _precision_recall,
    HIT_PRECISION_THRESHOLD,
)


# ======================================================================
# 1. Schema migration
# ======================================================================
class TestSchema:
    def test_init_is_idempotent(self, tmp_brain):
        # Doppia chiamata non deve crashare
        init_feedback_schema()
        init_feedback_schema()
        # Tabelle esistono
        from src.storage.db import get_connection
        conn = get_connection()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert 'predictions_log' in tables
        assert 'ticket_outcomes' in tables

    def test_new_columns_added_to_memories(self, tmp_brain):
        init_feedback_schema()
        from src.storage.db import get_connection
        conn = get_connection()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()}
        conn.close()
        for c in ('hit_count', 'miss_count', 'last_outcome_at'):
            assert c in cols


# ======================================================================
# 2. log_prediction / record_outcome / reads
# ======================================================================
class TestStoreRoundtrip:
    def test_log_and_retrieve_prediction(self, tmp_brain):
        init_feedback_schema()
        pid = log_prediction(
            project='p', ticket_id=42, author='me',
            predicted_files=['a.py', 'b.py'],
            predicted_symbols=['login'],
            memories_shown=[1, 2],
        )
        assert pid > 0
        got = get_prediction_for_ticket('p', 42)
        assert got['predicted_files'] == ['a.py', 'b.py']
        assert got['predicted_symbols'] == ['login']
        assert got['memories_shown'] == [1, 2]

    def test_prediction_not_found(self, tmp_brain):
        init_feedback_schema()
        assert get_prediction_for_ticket('p', 999) is None

    def test_record_and_list_outcomes(self, tmp_brain):
        init_feedback_schema()
        record_outcome('p', 42, 'completed',
                       actual_files=['a.py'], commit_hash='abc123')
        record_outcome('p', 43, 'reverted', actual_files=[])
        outcomes = get_outcomes_for_project('p')
        assert len(outcomes) == 2
        # Più recenti per primi
        assert outcomes[0]['ticket_id'] == 43

    def test_invalid_outcome_raises(self, tmp_brain):
        init_feedback_schema()
        with pytest.raises(ValueError):
            record_outcome('p', 42, 'whatever')


# ======================================================================
# 3. Counters
# ======================================================================
class TestCounters:
    def test_increment_hit_miss(self, tmp_brain):
        from src.storage.db import save_memory
        init_feedback_schema()
        save_memory('p', 1, 'avoid', 'avoid: do X')
        # memory id 1 (primo inserito nel tmp_brain)
        increment_memory_hit(1)
        increment_memory_hit(1)
        increment_memory_miss(1)
        c = get_memory_counters(1)
        assert c == {'hit': 2, 'miss': 1}

    def test_counters_zero_if_not_touched(self, tmp_brain):
        from src.storage.db import save_memory
        init_feedback_schema()
        save_memory('p', 1, 'avoid', 'avoid: fresh')
        assert get_memory_counters(1) == {'hit': 0, 'miss': 0}

    def test_counters_nonexistent_memory(self, tmp_brain):
        init_feedback_schema()
        assert get_memory_counters(9999) == {'hit': 0, 'miss': 0}


# ======================================================================
# 4. Precision/recall math
# ======================================================================
class TestPrecisionRecall:
    def test_perfect_match(self):
        m = _precision_recall(['a', 'b'], ['a', 'b'])
        assert m['precision'] == 1.0 and m['recall'] == 1.0 and m['f1'] == 1.0

    def test_no_overlap(self):
        m = _precision_recall(['a', 'b'], ['c', 'd'])
        assert m['precision'] == 0.0 and m['recall'] == 0.0 and m['f1'] == 0.0

    def test_partial_overlap(self):
        m = _precision_recall(['a', 'b', 'c'], ['a', 'b', 'd'])
        # tp=2 (a,b), fp=1 (c), fn=1 (d)
        assert m['precision'] == pytest.approx(2 / 3, rel=1e-3)
        assert m['recall'] == pytest.approx(2 / 3, rel=1e-3)

    def test_empty_both(self):
        m = _precision_recall([], [])
        assert m['precision'] == 1.0 and m['recall'] == 1.0


# ======================================================================
# 5. Reconciler
# ======================================================================
class TestReconciler:
    def _setup_prediction(self, tmp_brain, mem_ids=None, predicted=None):
        from src.storage.db import save_memory
        init_feedback_schema()
        # Crea alcune memorie
        if mem_ids is None:
            save_memory('p', 1, 'avoid', 'avoid: X')  # id=1
            save_memory('p', 1, 'pattern', 'pattern: Y')  # id=2
            mem_ids = [1, 2]
        log_prediction(
            project='p', ticket_id=42, author='me',
            predicted_files=predicted or ['a.py', 'b.py'],
            memories_shown=mem_ids,
        )
        return mem_ids

    def test_no_prediction_skips(self, tmp_brain):
        init_feedback_schema()
        r = reconcile('p', 99, 'completed', actual_files=['a.py'])
        assert r['status'] == 'skipped'
        assert 'no prediction' in r['reason']

    def test_abandoned_skips(self, tmp_brain):
        self._setup_prediction(tmp_brain)
        r = reconcile('p', 42, 'abandoned', actual_files=[])
        assert r['status'] == 'skipped'
        assert r['reason'] == 'abandoned'

    def test_completed_high_precision_is_hit(self, tmp_brain):
        self._setup_prediction(
            tmp_brain, predicted=['a.py', 'b.py']
        )
        r = reconcile('p', 42, 'completed', actual_files=['a.py', 'b.py'])
        assert r['status'] == 'reconciled'
        assert r['feedback_type'] == 'hit'
        assert r['metrics']['precision'] == 1.0
        # I memory shown devono aver ricevuto un hit
        assert get_memory_counters(1)['hit'] == 1
        assert get_memory_counters(2)['hit'] == 1

    def test_completed_low_precision_is_miss(self, tmp_brain):
        self._setup_prediction(
            tmp_brain, predicted=['a.py', 'b.py', 'c.py', 'd.py']
        )
        # Uno solo correct su 4 → precision 0.25 < 0.3
        r = reconcile('p', 42, 'completed', actual_files=['a.py'])
        assert r['feedback_type'] == 'miss'
        assert get_memory_counters(1)['miss'] == 1

    def test_reverted_always_miss(self, tmp_brain):
        self._setup_prediction(
            tmp_brain, predicted=['a.py', 'b.py']
        )
        # Anche se la prediction era perfetta, il fix è fallito
        r = reconcile('p', 42, 'reverted',
                      actual_files=['a.py', 'b.py'])
        assert r['feedback_type'] == 'miss'
        assert get_memory_counters(1)['miss'] == 1


# ======================================================================
# 6. Auto-tuning
# ======================================================================
class TestAutoTuning:
    def _make_memory(self, tmp_brain, hits=0, misses=0, status='active',
                     category='avoid', score=0.5):
        from src.storage.db import save_memory, get_connection
        init_feedback_schema()
        save_memory('p', 1, category, f'{category}: some content',
                    status=status, score=score)
        # Set counters
        conn = get_connection()
        conn.execute(
            "UPDATE memories SET hit_count=?, miss_count=? WHERE id=1",
            (hits, misses)
        )
        conn.commit()
        conn.close()
        return 1

    def test_demote_after_3_misses(self, tmp_brain):
        from src.brain.feedback_reconciler import _auto_tune_memory
        self._make_memory(tmp_brain, hits=0, misses=3, status='active')
        result = _auto_tune_memory(1)
        assert result['status_after'] == 'suspect'
        assert 'demoted' in result['action']

    def test_no_demote_if_hits_offset_misses(self, tmp_brain):
        from src.brain.feedback_reconciler import _auto_tune_memory
        self._make_memory(tmp_brain, hits=2, misses=3, status='active')
        result = _auto_tune_memory(1)
        assert result['status_after'] == 'active'
        assert result['action'] == 'no-op'

    def test_reactivate_suspect_after_hits(self, tmp_brain):
        from src.brain.feedback_reconciler import _auto_tune_memory
        self._make_memory(tmp_brain, hits=3, misses=0, status='suspect')
        result = _auto_tune_memory(1)
        assert result['status_after'] == 'active'
        assert 'reactivated' in result['action']

    def test_score_bump_on_consistent_hits(self, tmp_brain):
        from src.brain.feedback_reconciler import _auto_tune_memory
        self._make_memory(tmp_brain, hits=5, misses=0,
                          status='active', score=0.5)
        result = _auto_tune_memory(1)
        assert result['score_after'] == 0.6

    def test_score_capped_at_1(self, tmp_brain):
        from src.brain.feedback_reconciler import _auto_tune_memory
        self._make_memory(tmp_brain, hits=10, misses=0,
                          status='active', score=0.95)
        result = _auto_tune_memory(1)
        assert result['score_after'] <= 1.0

    def test_nonexistent_memory(self, tmp_brain):
        from src.brain.feedback_reconciler import _auto_tune_memory
        init_feedback_schema()
        result = _auto_tune_memory(9999)
        assert result['action'] == 'not_found'


# ======================================================================
# 7. End-to-end demote flow
# ======================================================================
class TestEndToEndDemote:
    def test_three_reverts_demote_memory(self, tmp_brain):
        """Scenario reale: memoria 'avoid' che dopo 3 ticket reverted viene
        automaticamente demoted a suspect."""
        from src.storage.db import save_memory, get_connection
        init_feedback_schema()
        save_memory('p', 1, 'avoid', 'avoid: questionable advice')

        # 3 ticket chiusi come 'reverted' con quella memoria mostrata
        for tid in (1, 2, 3):
            log_prediction(
                project='p', ticket_id=tid, author='me',
                predicted_files=['a.py'], memories_shown=[1],
            )
            record_outcome('p', tid, 'reverted', actual_files=[])
            reconcile('p', tid, 'reverted', actual_files=[])

        # Dopo 3 miss, lo status è 'suspect'
        conn = get_connection()
        row = conn.execute("SELECT status, miss_count FROM memories WHERE id=1").fetchone()
        conn.close()
        assert row['miss_count'] == 3
        assert row['status'] == 'suspect'


# ======================================================================
# 8. Aggregate stats
# ======================================================================
class TestStats:
    def test_empty_project(self, tmp_brain):
        init_feedback_schema()
        stats = get_feedback_stats('nobody')
        assert stats['total_outcomes'] == 0
        assert stats['avg_precision'] is None

    def test_mixed_outcomes(self, tmp_brain):
        init_feedback_schema()
        # 2 completed (perfetti, precision=1.0) + 1 reverted (actual=[], precision=0.0)
        for tid in (1, 2, 3):
            log_prediction('p', tid, 'me', ['a.py'], memories_shown=[])
        record_outcome('p', 1, 'completed', actual_files=['a.py'])
        record_outcome('p', 2, 'completed', actual_files=['a.py'])
        record_outcome('p', 3, 'reverted', actual_files=[])

        stats = get_feedback_stats('p')
        assert stats['total_outcomes'] == 3
        assert stats['outcomes']['completed'] == 2
        assert stats['outcomes']['reverted'] == 1
        # Media su 3 ticket: (1.0 + 1.0 + 0.0) / 3 = 0.667
        # Il reverted ha precision=0 perché actual_files è vuoto
        assert stats['avg_precision'] == pytest.approx(2 / 3, rel=1e-2)
        assert stats['samples'] == 3
