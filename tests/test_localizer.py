"""Learned localizer: pure channels, tree fusion, and the working-tree adapter."""
import subprocess

import pytest

from src.brain.localizer import (
    GENERATED_PATH_RE,
    is_test_path,
    plan_calibration,
    calibrate_tiers,
    reading_plan,
    RepoIndex,
    analyze_source,
    candidate_features,
    candidate_pool,
    history_features,
    issue_signals,
    tree_score,
)

SOURCES = {
    'pkg/__init__.py': 'from .parser import parse_config\n',
    'pkg/parser.py': (
        'from .errors import ConfigError\n\n'
        'def parse_config(text):\n'
        '    if not text:\n'
        '        raise ConfigError("configuration text must not be empty")\n'
        '    return dict(line.split("=") for line in text.splitlines())\n'
    ),
    'pkg/errors.py': 'class ConfigError(ValueError):\n    pass\n',
    'pkg/render.py': 'def render_template(name):\n    return name.upper()\n',
    'tests/test_parser.py': 'from pkg.parser import parse_config\n\ndef test_parse():\n    parse_config("a=1")\n',
}
ISSUE_BODY = (
    'Calling parse_config with an empty string fails:\n\n'
    'Traceback (most recent call last):\n'
    '  File "/site-packages/pkg/parser.py", line 5, in parse_config\n'
    'pkg.errors.ConfigError: configuration text must not be empty\n'
)


def _features():
    index = RepoIndex({p: analyze_source(p, s) for p, s in SOURCES.items()})
    return candidate_features(index, issue_signals('parse_config crashes on empty input', ISSUE_BODY))


def test_channels_point_at_the_defining_file():
    feats = _features()
    top = feats['pkg/parser.py']
    assert top['traceback_rr'] == 1.0
    assert top['defs_rr'] == 1.0
    assert top['literal_rr'] == 1.0
    assert 'tests/test_parser.py' not in feats  # tests are excluded from candidates
    # Pool = best rank on any channel; ties break by path, so it is deterministic.
    assert candidate_pool(feats, 2) == candidate_pool(dict(reversed(feats.items())), 2)
    assert 'pkg/parser.py' in candidate_pool(feats, 2)


def test_history_features_counts_touches_recent_and_fixes():
    log = ('\x01fix crash in parser\npkg/parser.py\n@scope/web/parser.ts\nREADME.md\n'
           '\x01add renderer\npkg/render.py\npkg/parser.py\n')
    hist = history_features(log)
    assert hist['touches']['pkg/parser.py'] == 2
    assert hist['touches']['@scope/web/parser.ts'] == 1
    assert hist['fixes']['pkg/parser.py'] == 1
    assert hist['fixes']['pkg/render.py'] == 0
    assert hist['recent']['pkg/render.py'] == 1
    assert 'README.md' not in hist['touches']


def test_tree_score_follows_splits_and_sums_trees():
    model = {'features': ['a', 'b'], 'trees': [[0, 0.5, 1.0, [1, 2.0, 10.0, 20.0]], -0.25]}
    assert tree_score(model, {'a': 0.1}) == pytest.approx(0.75)
    assert tree_score(model, {'a': 0.9, 'b': 1.0}) == pytest.approx(9.75)
    assert tree_score(model, {'a': 0.9, 'b': 3.0}) == pytest.approx(19.75)


@pytest.mark.parametrize('path, expected', [
    ('pkg/tests/test_parser.py', True),
    ('conftest.py', True),
    ('modules/caddyhttp/server_test.go', True),
    ('src/components/Button.test.tsx', True),
    ('lib/axios.spec.js', True),
    ('src/test/java/com/google/gson/GsonTest.java', True),
    ('MyApp.Tests/ParserTests.cs', True),
    ('modules/caddyhttp/server.go', False),
    ('src/main/java/com/google/gson/Gson.java', False),
    ('lib/contest.js', False),
    ('src/latest.rs', False),
    ('Scoring/Contests.cs', False),
])
def test_is_test_path_covers_supported_languages(path, expected):
    assert is_test_path(path) is expected


def test_calibrate_tiers_picks_smallest_prefix_meeting_target():
    # 10 queries: confident ones have gold at rank 1, uncertain ones deeper or missing.
    queries = [(5.0, 1), (4.0, 1), (3.0, 1),
               (2.0, 1), (1.8, 2), (1.5, 2), (1.2, 1),
               (0.5, 4), (0.3, None), (0.1, 12)]
    high, medium, low = calibrate_tiers(queries, target=0.75)
    assert (high['read_first'], high['expected_hit'], high['min_margin']) == (1, 1.0, 3.0)
    assert (medium['read_first'], medium['hit@1'], medium['n']) == (2, 0.5, 4)
    assert low['min_margin'] == 0.0
    assert low['read_first'] == 10 and low['expected_hit'] == pytest.approx(1 / 3, abs=1e-3)


def test_reading_plan_uses_top_two_margin():
    cal = {'tiers': [
        {'label': 'high', 'min_margin': 2.0, 'read_first': 1, 'expected_hit': 0.87},
        {'label': 'low', 'min_margin': 0.0, 'read_first': 10, 'expected_hit': 0.79},
    ]}
    assert reading_plan([5.0, 2.5, 1.0], cal)['confidence'] == 'high'
    low = reading_plan([5.0, 4.5, 1.0], cal)
    assert (low['confidence'], low['read_first'], low['margin']) == ('low', 3, 0.5)
    assert reading_plan([1.0], cal) == {'confidence': 'high', 'read_first': 1, 'expected_hit': 0.87, 'margin': None}


def test_plan_calibration_uses_python_tiers_only_for_python():
    model = {'calibration': 'py'}
    assert plan_calibration(model, 'src/app.go') == 'py'  # no non-Python calibration shipped
    model['calibration_other'] = 'other'
    assert plan_calibration(model, 'pkg/mod.PY') == 'py'
    assert plan_calibration(model, 'lib/http.js') == 'other'


def test_single_pooled_tier():
    (tier,) = calibrate_tiers([(3.0, 1), (1.0, 2), (0.5, None)], target=0.6, shares=(), labels=('low',))
    assert (tier['label'], tier['min_margin'], tier['read_first'], tier['n']) == ('low', 0.0, 2, 3)


@pytest.mark.parametrize('path, generated', [
    ('dist/axios.js', True), ('build/three.cjs', True), ('jest/vendor/remark.js', True),
    ('lib/jquery.min.js', True), ('lib/adapters/http.js', False), ('examples/plot_roc.py', False),
    ('src/builder.py', False),
])
def test_generated_paths_are_recognised(path, generated):
    assert bool(GENERATED_PATH_RE.search(path)) is generated


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


@pytest.fixture
def python_repo(tmp_path):
    for rel, text in SOURCES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'fix parser bug')
    return tmp_path


def test_localize_ranks_working_tree_and_caches_docs(python_repo):
    from src.brain.repo_localizer import localize

    results = localize(python_repo, 'parse_config crashes on empty input', ISSUE_BODY, top_k=3)
    assert results[0]['file'] == 'pkg/parser.py'
    assert results[0]['source'] == 'localizer'
    assert 'in traceback' in results[0]['why']
    assert {'file', 'score', 'confidence', 'why', 'source', 'hops'} <= set(results[0])
    plan = results[0]['plan']
    assert 1 <= plan['read_first'] <= 3 and 0 < plan['expected_hit'] <= 1
    assert all('plan' not in r for r in results[1:])
    assert list((python_repo / '.brain' / 'local').glob('localizer_docs_v*.pkl'))
    # Second call reuses the cache and gives the same answer.
    assert localize(python_repo, 'parse_config crashes on empty input', ISSUE_BODY, top_k=3) == results


def test_predict_files_ranked_falls_back_outside_git(tmp_brain, monkeypatch):
    from src.brain import file_predictor

    monkeypatch.setattr(file_predictor, 'predict_files_with_impact', lambda *a, **k: [{'file': 'legacy.py'}])
    assert file_predictor.predict_files_ranked('anything') == [{'file': 'legacy.py'}]


def test_localize_supports_typescript_and_builds_generic_evidence(tmp_path):
    sources = {
        'src/parser.ts': (
            'export function parseConfig(text: string) {\n'
            '  if (!text) throw new Error("configuration text must not be empty");\n'
            '  return text.split("=");\n'
            '}\n'
        ),
        'src/render.ts': 'export function renderTemplate(name: string) { return name; }\n',
        'tests/parser.test.ts': 'import { parseConfig } from "../src/parser";\n',
    }
    for rel, text in sources.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    _git(tmp_path, 'init', '-q')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'add parser')

    from src.brain.repo_localizer import localize

    result = localize(
        tmp_path,
        'parseConfig crashes on empty input',
        'Calling parseConfig with an empty string says configuration text must not be empty',
        top_k=2,
        evidence=True,
    )

    assert result[0]['file'] == 'src/parser.ts'
    assert 'parseConfig' in result[0]['evidence']
