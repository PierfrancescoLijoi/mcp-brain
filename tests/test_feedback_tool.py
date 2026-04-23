"""Test STEP 5 — tool MCP feedback (record_outcome, feedback_stats, memory_health)."""
import yaml
import pytest

from src.tools.feedback_tool import (
    record_outcome_impl,
    feedback_stats_impl,
    memory_health_impl,
    register_feedback_tools,
)
from src.brain.feedback_store import init_feedback_schema, log_prediction


class TestRecordOutcomeImpl:
    def test_without_prior_prediction_still_records(self, tmp_brain):
        out = record_outcome_impl(
            project='p', ticket_id=42, outcome='completed',
            actual_files=['a.py'],
        )
        data = yaml.safe_load(out)
        assert 'outcome_recorded' in data
        # No prediction era loggata → reconcile skippa
        assert data['outcome_recorded']['status'] == 'skipped'

    def test_with_prediction_reconciles(self, tmp_brain):
        init_feedback_schema()
        log_prediction('p', 42, 'me', ['a.py', 'b.py'], memories_shown=[])
        out = record_outcome_impl(
            project='p', ticket_id=42, outcome='completed',
            actual_files=['a.py', 'b.py'],
        )
        data = yaml.safe_load(out)
        assert data['outcome_recorded']['status'] == 'reconciled'
        assert data['outcome_recorded']['feedback_type'] == 'hit'

    def test_invalid_outcome_returns_error(self, tmp_brain):
        out = record_outcome_impl('p', 1, 'garbage')
        assert out.startswith('error')


class TestFeedbackStatsImpl:
    def test_empty_returns_zero_stats(self, tmp_brain):
        out = feedback_stats_impl('p')
        data = yaml.safe_load(out)
        assert data['feedback_stats']['total_outcomes'] == 0

    def test_window_days_param(self, tmp_brain):
        out = feedback_stats_impl('p', since_days=7)
        data = yaml.safe_load(out)
        assert data['feedback_stats']['window_days'] == 7


class TestMemoryHealthImpl:
    def test_empty_returns_string_placeholder(self, tmp_brain):
        init_feedback_schema()
        out = memory_health_impl('p')
        data = yaml.safe_load(out)
        # Nessuna memoria con hit/miss → placeholder
        assert data['memory_health'] == 'no feedback data yet'

    def test_surfaces_noisy_memories(self, tmp_brain):
        from src.storage.db import save_memory
        from src.brain.feedback_store import increment_memory_miss
        init_feedback_schema()
        save_memory('p', 1, 'avoid', 'avoid: noisy')
        save_memory('p', 1, 'pattern', 'pattern: fine')
        increment_memory_miss(1)
        increment_memory_miss(1)
        increment_memory_miss(1)

        out = memory_health_impl('p')
        data = yaml.safe_load(out)
        assert isinstance(data['memory_health'], list)
        # id=1 è in cima (miss=3, hit=0)
        assert data['memory_health'][0]['id'] == 1
        assert data['memory_health'][0]['miss'] == 3


class FakeMCP:
    def __init__(self):
        self.registered = []

    def tool(self):
        def deco(fn):
            self.registered.append(fn)
            return fn
        return deco


class TestRegistration:
    def test_registers_three_tools(self):
        mcp = FakeMCP()
        register_feedback_tools(mcp)
        names = [fn.__name__ for fn in mcp.registered]
        assert 'brain_record_outcome' in names
        assert 'brain_feedback_stats' in names
        assert 'brain_memory_health' in names

    def test_each_has_docstring(self):
        mcp = FakeMCP()
        register_feedback_tools(mcp)
        for fn in mcp.registered:
            assert fn.__doc__ and len(fn.__doc__) > 20

    def test_record_outcome_invocation(self, tmp_brain):
        mcp = FakeMCP()
        register_feedback_tools(mcp)
        fn = next(f for f in mcp.registered if f.__name__ == 'brain_record_outcome')
        result = fn(
            project='p', ticket_id=42, outcome='completed',
            actual_files=['a.py'],
        )
        data = yaml.safe_load(result)
        assert 'outcome_recorded' in data
