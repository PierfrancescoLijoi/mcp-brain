"""Self-calibration: measure the localizer on this repository's own Git history.

Each recent commit that modified 1..MAX_FILES existing source files becomes a
query: its message plays the issue, the modified files are the answer, and the
index is built from the parent commit (blobs streamed through one
``git cat-file --batch``, nothing is checked out). The resulting reading-plan
tiers are stored in ``.brain/local/calibration.json`` and replace the shipped
benchmark calibration for this repository.

Commit messages are terser than issues. On SWE-bench Lite (291 issues linked to
their fix commits) tiers fitted on commit messages never over-claimed on the
real issues (claimed 85%, observed 91-95%), so the local plan is conservative.
"""
from __future__ import annotations

import json
import subprocess
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

from src.brain.localizer import (
    GENERATED_PATH_RE,
    HISTORY_DEPTH,
    RepoIndex,
    add_history,
    analyze_source,
    calibrate_tiers,
    candidate_features,
    candidate_pool,
    history_features,
    is_test_path,
    issue_signals,
    tree_score,
)
from src.brain.repo_localizer import CALIBRATION_FILE, MAX_FILE_SIZE, SOURCE_EXTENSIONS, _git, load_model

MAX_FILES = 5  # larger commits are refactors/merges, not single-issue fixes
MIN_QUERIES = 30
MIN_SUBJECT_WORDS = 3
KS = (1, 3, 5, 10)
TRAILERS = ('signed-off-by:', 'co-authored-by:', 'reviewed-by:', 'change-id:')


class BlobReader:
    def __init__(self, repo: Path):
        self.proc = subprocess.Popen(['git', '-C', str(repo), 'cat-file', '--batch'],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def read(self, sha: str) -> str:
        self.proc.stdin.write(f'{sha}\n'.encode())
        self.proc.stdin.flush()
        header = self.proc.stdout.readline().split()
        size = int(header[2])
        data = self.proc.stdout.read(size + 1)[:-1]
        return data.decode('utf-8', errors='replace')

    def close(self) -> None:
        self.proc.kill()


def _is_source(path: str) -> bool:
    low = path.lower()
    return (Path(low).suffix in SOURCE_EXTENSIONS and not is_test_path(path)
            and not GENERATED_PATH_RE.search(low))


def history_queries(root: Path, limit: int) -> list[dict]:
    """Most recent commits usable as (message, modified source files) queries."""
    log = _git(root, '-c', 'core.quotePath=false', 'log', '--no-merges', '--no-renames', '--diff-filter=M',
               '--name-only', f'--max-count={limit * 10}', '--format=%x01%H%x02%B%x03')
    queries = []
    for chunk in log.split('\x01')[1:]:
        head, _, names = chunk.partition('\x03')
        sha, _, message = head.partition('\x02')
        files = [f for f in (n.strip() for n in names.splitlines()) if f and _is_source(f)]
        message = '\n'.join(l for l in message.strip().splitlines() if not l.lower().startswith(TRAILERS))
        if not 1 <= len(files) <= MAX_FILES or len(message.split('\n', 1)[0].split()) < MIN_SUBJECT_WORDS:
            continue
        queries.append({'commit': sha, 'message': message, 'files': files})
        if len(queries) >= limit:
            break
    return queries


def _docs_at(root: Path, reader: BlobReader, commit: str, blobs: dict) -> dict:
    docs = {}
    for entry in _git(root, 'ls-tree', '-r', '-l', '-z', commit).split('\0'):
        if not entry:
            continue
        meta, path = entry.split('\t', 1)
        _mode, kind, sha, size = meta.split()
        if kind != 'blob' or Path(path).suffix.lower() not in SOURCE_EXTENSIONS or int(size) > MAX_FILE_SIZE:
            continue
        if sha not in blobs:
            blobs[sha] = analyze_source(path, reader.read(sha))
        doc = blobs[sha]
        docs[path] = doc if doc.path == path else type(doc)(**{**doc.__dict__, 'path': path})
    return docs


def measure(root: Path, query: dict, reader: BlobReader, blobs: dict, model: dict) -> tuple | None:
    """(top1-top2 margin, 1-based rank of the first modified file or None); None if unusable."""
    parent = f"{query['commit']}^"
    docs = _docs_at(root, reader, parent, blobs)
    gold = set(query['files']) & set(docs)
    if not gold:
        return None
    title, _, body = query['message'].partition('\n')
    feats = candidate_features(RepoIndex(docs), issue_signals(title, body))
    if not feats:
        return 0.0, None
    add_history(feats, history_features(_git(root, 'log', parent, f'--max-count={HISTORY_DEPTH}', '--no-merges',
                                             '--no-renames', '--name-only', '--format=%x01%s')))
    scored = sorted(((tree_score(model, feats[p]), p) for p in candidate_pool(feats)), reverse=True)
    rank = next((n for n, (_s, p) in enumerate(scored, 1) if p in gold), None)
    return (scored[0][0] - scored[1][0] if len(scored) > 1 else 0.0), rank


def self_calibrate(repo: str | Path, limit: int = 150, target: float = 0.85,
                   min_queries: int = MIN_QUERIES, progress=None) -> dict:
    """Measure the localizer on recent commits and store local reading-plan tiers.

    Returns the report; ``tiers`` is present (and the file written) only when at
    least ``min_queries`` commits were usable.
    """
    root = Path(_git(Path(repo), 'rev-parse', '--show-toplevel').strip())
    started = time.time()
    model = load_model()
    reader, blobs, results = BlobReader(root), {}, []
    try:
        queries = history_queries(root, limit)
        for n, query in enumerate(queries, 1):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')  # SyntaxWarnings from old sources
                res = measure(root, query, reader, blobs, model)
            if res is not None:
                results.append(res)
            if progress:
                progress(n, len(queries))
    finally:
        reader.close()
    n = len(results)
    report = {
        'source': f'this repository ({n} commits)',
        'n': n,
        'head': _git(root, 'rev-parse', 'HEAD').strip(),
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'target': target,
        'hit': {f'hit@{k}': round(sum(r is not None and r <= k for _m, r in results) / max(n, 1), 3) for k in KS},
        'seconds': round(time.time() - started, 1),
    }
    if n >= min_queries:
        tiers = calibrate_tiers(results, target=target)
        if any(a['read_first'] > b['read_first'] for a, b in zip(tiers, tiers[1:])):
            # The margin does not separate this repository's commits: one pooled tier is the honest plan.
            tiers = calibrate_tiers(results, target=target, shares=(), labels=('low',))
        report['tiers'] = tiers
        path = root / '.brain' / 'local' / CALIBRATION_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=1), encoding='utf-8')
    return report
