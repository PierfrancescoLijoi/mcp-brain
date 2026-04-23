"""Test STEP 7 — observability collector + @observed decorator."""
import json
import logging
import pytest

from src.brain import observability as obs
from src.brain.observability import (
    record_call,
    get_snapshot,
    get_tool_stats,
    reset,
    observed,
    _percentile,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Ogni test parte da registry vuoto."""
    reset()
    yield
    reset()


# ======================================================================
# 1. record_call + snapshot
# ======================================================================
class TestRecordCall:
    def test_empty_snapshot_is_empty_dict(self):
        assert get_snapshot() == {}

    def test_single_call_recorded(self):
        record_call('tool_a', duration_ms=10.0, output_size=100)
        snap = get_snapshot()
        assert 'tool_a' in snap
        assert snap['tool_a']['count'] == 1
        assert snap['tool_a']['errors'] == 0
        assert snap['tool_a']['latency_ms']['avg'] == 10.0

    def test_multiple_calls_aggregated(self):
        for ms in [10, 20, 30, 40, 50]:
            record_call('t', duration_ms=ms, output_size=ms * 10)
        snap = get_snapshot()
        assert snap['t']['count'] == 5
        assert snap['t']['latency_ms']['avg'] == 30.0
        assert snap['t']['latency_ms']['max'] == 50.0

    def test_error_tracked(self):
        err = ValueError('bad input')
        record_call('t', 10.0, 0, error=err)
        snap = get_snapshot()
        assert snap['t']['errors'] == 1
        assert snap['t']['error_rate'] == 1.0
        assert snap['t']['errors_by_type']['ValueError'] == 1
        assert 'ValueError' in snap['t']['last_error']

    def test_error_rate_accurate(self):
        for _ in range(4):
            record_call('t', 5.0, 10)
        record_call('t', 5.0, 0, error=RuntimeError('x'))
        snap = get_snapshot()
        assert snap['t']['count'] == 5
        assert snap['t']['errors'] == 1
        assert snap['t']['error_rate'] == 0.2

    def test_output_sizes_tracked(self):
        record_call('t', 1.0, 100)
        record_call('t', 1.0, 200)
        record_call('t', 1.0, 300)
        snap = get_snapshot()
        assert snap['t']['output_chars']['avg'] == 200
        assert snap['t']['output_chars']['max'] == 300

    def test_separate_tools_separate_buckets(self):
        record_call('a', 10.0, 100)
        record_call('b', 20.0, 200)
        snap = get_snapshot()
        assert snap['a']['count'] == 1
        assert snap['b']['count'] == 1
        assert snap['a']['latency_ms']['avg'] == 10.0
        assert snap['b']['latency_ms']['avg'] == 20.0


# ======================================================================
# 2. Percentili
# ======================================================================
class TestPercentiles:
    def test_percentile_empty(self):
        assert _percentile([], 50) == 0.0

    def test_percentile_single(self):
        assert _percentile([5.0], 50) == 5.0
        assert _percentile([5.0], 99) == 5.0

    def test_p50_matches_median(self):
        vals = sorted([10, 20, 30, 40, 50])
        assert _percentile(vals, 50) == 30.0

    def test_p95_high(self):
        # Su un range 1..100 il p95 deve essere vicino a 95
        vals = sorted(list(range(1, 101)))
        p95 = _percentile(vals, 95)
        assert 94 <= p95 <= 96

    def test_p99_top(self):
        vals = sorted(list(range(1, 101)))
        p99 = _percentile(vals, 99)
        assert 98 <= p99 <= 100

    def test_percentile_with_known_distribution(self):
        # Many 10ms samples + 1 outlier 1000ms
        vals = sorted([10.0] * 99 + [1000.0])
        assert _percentile(vals, 50) == 10.0
        # p99 cade sull'outlier
        assert _percentile(vals, 99) > 10.0


# ======================================================================
# 3. Rolling window (bounded memory)
# ======================================================================
class TestRollingWindow:
    def test_window_caps_at_500(self):
        for i in range(600):
            record_call('t', float(i), 1)
        # Count è la somma reale, non cappato
        snap = get_snapshot()
        assert snap['t']['count'] == 600
        # Ma le durations tengono solo le ultime 500, quindi avg != 299.5
        # L'ultimo valore (599) è nella window, il primo (0) no
        # Nuova avg = media di 100..599
        expected_avg = sum(range(100, 600)) / 500
        assert abs(snap['t']['latency_ms']['avg'] - expected_avg) < 1.0


# ======================================================================
# 4. @observed decorator
# ======================================================================
class TestObservedDecorator:
    def test_wraps_function(self):
        @observed('my_tool')
        def do_thing(x):
            return f'result-{x}'

        assert do_thing(42) == 'result-42'
        snap = get_snapshot()
        assert 'my_tool' in snap
        assert snap['my_tool']['count'] == 1

    def test_records_error_and_reraises(self):
        @observed('broken')
        def bad():
            raise RuntimeError('boom')

        with pytest.raises(RuntimeError):
            bad()

        snap = get_snapshot()
        assert snap['broken']['errors'] == 1

    def test_uses_function_name_as_default(self):
        @observed()
        def brain_fancy():
            return 'ok'

        brain_fancy()
        snap = get_snapshot()
        assert 'brain_fancy' in snap

    def test_size_measured_for_string(self):
        @observed('s')
        def f():
            return 'x' * 123

        f()
        snap = get_snapshot()
        assert snap['s']['output_chars']['avg'] == 123

    def test_size_fallback_for_non_string(self):
        @observed('d')
        def f():
            return {'a': 1, 'b': 2}

        f()
        snap = get_snapshot()
        # Non crash, size stimata via json.dumps
        assert snap['d']['output_chars']['avg'] > 0

    def test_size_none_handled(self):
        @observed('n')
        def f():
            return None

        f()
        snap = get_snapshot()
        assert snap['n']['output_chars']['avg'] == 0

    def test_multiple_calls_accumulate(self):
        @observed('multi')
        def f(x):
            return str(x)

        for i in range(10):
            f(i)
        snap = get_snapshot()
        assert snap['multi']['count'] == 10


# ======================================================================
# 5. reset + get_tool_stats
# ======================================================================
class TestUtilities:
    def test_reset_clears_all(self):
        record_call('t', 1.0, 10)
        assert get_snapshot()
        reset()
        assert get_snapshot() == {}

    def test_get_tool_stats_nonexistent(self):
        assert get_tool_stats('nonexistent') is None

    def test_get_tool_stats_existing(self):
        record_call('t', 5.0, 50)
        stats = get_tool_stats('t')
        assert stats['count'] == 1


# ======================================================================
# 6. Structured JSON logs (via env)
# ======================================================================
class TestStructuredLogs:
    def test_json_logs_disabled_by_default(self, monkeypatch, caplog):
        monkeypatch.delenv('MCP_BRAIN_JSON_LOGS', raising=False)

        @observed('t')
        def f():
            return 'ok'

        with caplog.at_level(logging.INFO):
            f()
        # No MCPB_METRIC nel log
        assert not any('MCPB_METRIC' in r.message for r in caplog.records)

    def test_json_logs_enabled_emits_metric(self, monkeypatch, caplog):
        monkeypatch.setenv('MCP_BRAIN_JSON_LOGS', '1')

        @observed('t')
        def f():
            return 'ok'

        with caplog.at_level(logging.INFO):
            f()

        metric_records = [r for r in caplog.records if 'MCPB_METRIC' in r.message]
        assert len(metric_records) == 1
        # Estrai la parte JSON
        msg = metric_records[0].message
        json_part = msg.split('MCPB_METRIC ', 1)[1]
        payload = json.loads(json_part)
        assert payload['tool'] == 't'
        assert payload['ok'] is True
        assert 'ms' in payload
