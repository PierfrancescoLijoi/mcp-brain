import json
import subprocess

from src.brain.self_calibration import history_queries, self_calibrate


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
                   check=True, capture_output=True)


def _commit(root, files: dict, message: str):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    _git(root, 'add', '.')
    _git(root, 'commit', '-qm', message)


def _repo(tmp_path, fixes: int):
    modules = {f'pkg/mod{i}.py': f'def handler_{i}(value):\n    return value\n' for i in range(4)}
    _commit(tmp_path, modules, 'initial import of the package')
    for n in range(fixes):
        i = n % 4
        _commit(tmp_path, {f'pkg/mod{i}.py': f'def handler_{i}(value):\n    return value + {n}\n',
                           f'tests/test_mod{i}.py': f'# {n}\n'},
                f'fix handler_{i} returning wrong value')
    return tmp_path


def test_history_queries_keep_modified_source_files_only(tmp_path):
    _git(tmp_path, 'init', '-q')
    repo = _repo(tmp_path, fixes=3)
    _commit(repo, {'pkg/mod0.py': 'x = 1\n'}, 'wip')  # subject too short to be an issue
    queries = history_queries(repo, limit=10)
    assert len(queries) == 3  # the initial commit adds files, it modifies none
    assert queries[0]['files'] == ['pkg/mod2.py']  # newest first, test file dropped
    assert queries[0]['message'] == 'fix handler_2 returning wrong value'


def test_self_calibrate_writes_local_plan_used_by_localize(tmp_path):
    from src.brain.repo_localizer import localize

    _git(tmp_path, 'init', '-q')
    repo = _repo(tmp_path, fixes=8)
    report = self_calibrate(repo, limit=20, min_queries=5)
    assert report['n'] == 8 and report['hit']['hit@1'] == 1.0
    saved = json.loads((repo / '.brain' / 'local' / 'calibration.json').read_text(encoding='utf-8'))
    assert saved['tiers'] == report['tiers'] and saved['source'] == 'this repository (8 commits)'
    plan = localize(repo, 'handler_3 returns the wrong value', top_k=3)[0]['plan']
    assert plan['calibrated_on'] == 'this repository (8 commits)'


def test_self_calibrate_needs_enough_commits(tmp_path):
    _git(tmp_path, 'init', '-q')
    repo = _repo(tmp_path, fixes=2)
    report = self_calibrate(repo, limit=20)
    assert 'tiers' not in report and report['n'] == 2
    assert not (repo / '.brain' / 'local' / 'calibration.json').exists()
