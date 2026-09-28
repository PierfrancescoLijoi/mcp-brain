from types import SimpleNamespace

import pytest

from benchmark.loclab_verify import ClaudeCliBackend, cache_identity, metric_hits


def test_cache_identity_separates_backend_model_and_card_version():
    name = cache_identity('openai-compatible', 'qwen2.5-coder:14b', 15)
    assert name == (
        'verify_openai-compatible_qwen2.5-coder-14b_15_head5_conf75_'
        'prompt8000_out256_c3_p4.json'
    )
    assert cache_identity('openai-compatible', 'qwen2.5-coder:14b', 15, 3, 0.8) != name


def test_claude_backend_does_not_swallow_cli_failures(monkeypatch):
    monkeypatch.setattr(
        'benchmark.loclab_verify.subprocess.run',
        lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='quota exhausted'),
    )

    with pytest.raises(RuntimeError, match='quota exhausted'):
        ClaudeCliBackend('sonnet', 30).complete('prompt', {})


def test_metric_hits_uses_only_successful_v3_records():
    ranking = {
        'a': {'gold': ['right.py'], 'ranked': ['wrong.py', 'right.py']},
        'b': {'gold': ['b.py'], 'ranked': ['b.py', 'other.py']},
    }
    records = {
        'a': {'ranking': ['right.py', 'wrong.py'], 'verification': {'status': 'verified'}},
        'b': {'ranking': ['other.py', 'b.py'], 'verification': {'status': 'abstained'}},
        'failed': {'ranking': [], 'verification': {'status': 'error'}},
    }

    assert metric_hits(ranking, records, verified=False) == {
        'n': 2, 'hit@1': 0.5, 'hit@3': 1.0, 'hit@5': 1.0, 'hit@10': 1.0,
    }
    assert metric_hits(ranking, records, verified=True) == {
        'n': 2, 'hit@1': 0.5, 'hit@3': 1.0, 'hit@5': 1.0, 'hit@10': 1.0,
    }
