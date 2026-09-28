"""Working-tree adapter for the learned localizer (``src/brain/localizer.py``).

Reads tracked and untracked (non-ignored) supported source files, caches one FileDoc per
file under ``.brain/local`` keyed by (mtime, size), adds Git-history features
and ranks candidates with the exported LambdaMART trees in
``localizer_model.json``. Same features and model as ``benchmark/loclab.py``.
The shipped trees are trained on Python SWE-bench repositories; other supported
languages reuse the same language-neutral channels but remain a promotion slice.
"""
from __future__ import annotations

import json
import pickle
import subprocess
import warnings
from functools import lru_cache
from pathlib import Path

from src.brain.evidence import card
from src.brain.localizer import (
    DOC_VERSION,
    HISTORY_DEPTH,
    RepoIndex,
    add_history,
    analyze_source,
    candidate_features,
    candidate_pool,
    history_features,
    issue_signals,
    plan_calibration,
    reading_plan,
    tree_score,
)
from src.brain.parsers import supported_extensions

MODEL_PATH = Path(__file__).with_name('localizer_model.json')
CALIBRATION_FILE = 'calibration.json'  # written by `mcp-brain calibrate` under .brain/local
MAX_FILE_SIZE = 500_000
SOURCE_EXTENSIONS = frozenset(supported_extensions())
# Evidence shown to the agent, strongest first.
EVIDENCE = (
    ('traceback', 'in traceback'),
    ('literal', 'contains quoted message'),
    ('literal_path', 'path named in issue'),
    ('module', 'module named in issue'),
    ('defs', 'defines issue symbol'),
    ('qualified', 'defines Class.method'),
    ('bm25_title', 'matches title'),
    ('bm25', 'matches issue text'),
    ('api', 'API names match'),
    ('path_bm25', 'path matches'),
    ('neighbor', 'imports/imported by a match'),
)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', check=True).stdout


@lru_cache(maxsize=1)
def load_model() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding='utf-8'))


def load_local_calibration(root: Path) -> dict | None:
    try:
        cal = json.loads((root / '.brain' / 'local' / CALIBRATION_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return cal if cal.get('tiers') else None


def load_docs(root: Path, cache_dir: Path) -> dict:
    files = [
        p for p in _git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split('\0')
        if Path(p).suffix.lower() in SOURCE_EXTENSIONS
    ]
    cache_file = cache_dir / f'localizer_docs_v{DOC_VERSION}.pkl'
    try:
        cache = pickle.loads(cache_file.read_bytes())
    except (OSError, pickle.UnpicklingError, EOFError, AttributeError, TypeError):
        cache = {}
    fresh, docs, changed = {}, {}, False
    for rel in files:
        path = root / rel
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size > MAX_FILE_SIZE:
            continue
        key = (st.st_mtime_ns, st.st_size)
        hit = cache.get(rel)
        if hit and hit[0] == key:
            doc = hit[1]
        else:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')  # SyntaxWarnings from old sources
                doc = analyze_source(rel, path.read_text(encoding='utf-8', errors='replace'))
            changed = True
        fresh[rel] = (key, doc)
        docs[rel] = doc
    if changed or len(fresh) != len(cache):
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(pickle.dumps(fresh))
    return docs


@lru_cache(maxsize=4)
def _history(root: str, head: str) -> dict:
    return history_features(_git(Path(root), 'log', head, f'--max-count={HISTORY_DEPTH}', '--no-merges',
                                 '--no-renames', '--name-only', '--format=\x01%s'))


def _why(features: dict) -> str:
    reasons = [label for name, label in EVIDENCE if features.get(f'{name}_rr') == 1.0]
    reasons += [label for name, label in EVIDENCE if features.get(f'{name}_n', 0.0) >= 0.5 and label not in reasons]
    return ', '.join(reasons[:3]) or 'weak lexical match'


def localize(repo: str | Path, title: str, body: str = '', top_k: int = 10, evidence: bool = False) -> list:
    """Rank supported source files of ``repo`` most likely to change for an issue.

    Raises ``subprocess.CalledProcessError`` when ``repo`` is not a Git work tree.
    """
    root = Path(_git(Path(repo), 'rev-parse', '--show-toplevel').strip())
    docs = load_docs(root, root / '.brain' / 'local')
    if not docs:
        return []
    sig = issue_signals(title, body)
    feats = candidate_features(RepoIndex(docs), sig)
    if not feats:
        return []
    try:
        add_history(feats, _history(str(root), _git(root, 'rev-parse', 'HEAD').strip()))
    except subprocess.CalledProcessError:  # repository without commits
        add_history(feats, history_features(''))
    model = load_model()
    scored = sorted(((tree_score(model, feats[p]), p) for p in candidate_pool(feats)), reverse=True)
    # Margin needs the true runner-up, so the plan is computed before truncating to top_k.
    calibration = plan_calibration(model, scored[0][1], load_local_calibration(root))
    plan = reading_plan([s for s, _p in scored], calibration)
    plan['calibrated_on'] = calibration.get('source', 'benchmark')
    scored = scored[:top_k]
    plan['read_first'] = min(plan['read_first'], len(scored))
    out = []
    for n, (s, p) in enumerate(scored, 1):
        out.append({
            'file': p,
            'score': round(s, 4),
            'confidence': plan['confidence'] if n <= plan['read_first'] else 'low',
            'why': _why(feats[p]),
            'source': 'localizer',
            'hops': 0,
        })
    out[0]['plan'] = plan
    if evidence:
        query, idents = set(sig.terms), set(sig.identifiers)
        for n, item in enumerate(out, 1):
            text = (root / item['file']).read_text(encoding='utf-8', errors='replace')
            item['evidence'] = card(n, item['file'], text, query, idents)
    return out
