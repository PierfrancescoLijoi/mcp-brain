import json
import subprocess

from benchmark import run_eval
from benchmark.worker_predict_batch import process_instances


def _item(instance_id='one', repo='org/repo'):
    return {
        'instance_id': instance_id,
        'repo': repo,
        'base_commit': 'abc123',
        'problem_statement': 'Fix parser behavior',
        'gold_files': ['src/parser.py'],
    }


def test_process_instances_reuses_runtime_and_isolates_errors(monkeypatch, tmp_path):
    calls = []

    def fake_predict(repo_dir, item, top_k, max_hops, use_semantic):
        calls.append(item['instance_id'])
        if item['instance_id'] == 'bad':
            raise RuntimeError('broken instance')
        return [{'file': 'src/parser.py', 'score': 1.0}]

    monkeypatch.setattr(
        'benchmark.worker_predict_batch.predict_one', fake_predict
    )
    rows = process_instances(
        tmp_path,
        [_item('good'), _item('bad')],
        top_k=10,
        max_hops=2,
        use_semantic=False,
    )

    assert calls == ['good', 'bad']
    assert rows[0]['predictions'][0]['file'] == 'src/parser.py'
    assert rows[0]['error'] is None
    assert rows[1]['predictions'] == []
    assert 'broken instance' in rows[1]['error']


def test_run_repo_batch_uses_one_process_for_multiple_instances(
    monkeypatch, tmp_path
):
    repo = tmp_path / 'org__repo'
    repo.mkdir()
    items = [_item('one'), _item('two')]
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps([
            {'instance_id': 'one', 'predictions': [], 'error': None},
            {'instance_id': 'two', 'predictions': [], 'error': None},
        ]),
        stderr='',
    )
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return completed

    monkeypatch.setattr(run_eval.subprocess, 'run', fake_run)
    rows = run_eval.run_repo_batch(
        'org/repo',
        items,
        tmp_path,
        top_k=10,
        max_hops=2,
        use_semantic=False,
        timeout=30,
    )

    assert len(calls) == 1
    assert [row['instance_id'] for row in rows] == ['one', 'two']
    assert json.loads(calls[0][1]['input']) == items


def test_grouped_batch_results_preserve_dataset_order(monkeypatch, tmp_path):
    instances = [_item('a', 'x/one'), _item('b', 'y/two'), _item('c', 'x/one')]

    def fake_batch(repo, items, *args, **kwargs):
        return [
            {'instance_id': item['instance_id'], 'predictions': [], 'error': None}
            for item in reversed(items)
        ]

    monkeypatch.setattr(run_eval, 'run_repo_batch', fake_batch)
    rows = run_eval.run_batched(
        instances,
        tmp_path,
        top_k=10,
        max_hops=2,
        use_semantic=False,
        timeout=30,
        jobs=2,
    )

    assert [row['instance_id'] for row in rows] == ['a', 'b', 'c']
