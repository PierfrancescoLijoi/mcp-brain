"""Fast localization lab: feature extraction straight from git objects.

No checkout: files are read at each instance's ``base_commit`` through one
``git cat-file --batch`` process, and each blob is analysed once (cache keyed
by blob SHA). History features only see ancestors of ``base_commit``.

    python -m benchmark.loclab extract --dataset benchmark/datasets/cache/swebench_full.jsonl
    python -m benchmark.loclab train
"""
from __future__ import annotations

import argparse
import json
import pickle
import subprocess
import sys
import time
import warnings
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from src.brain.localizer import (DOC_VERSION, HISTORY_DEPTH, RepoIndex, add_history, analyze_source, candidate_features,
                                 SOURCE_SUFFIXES, calibrate_tiers, candidate_pool, plan_calibration, history_features, issue_signals, reading_plan,
                                 tree_score)

from src.brain.self_calibration import BlobReader

CACHE = Path('benchmark/tmp/loclab')
REPOS = Path('benchmark/repos')
CHUNK = 60


def git(repo: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', check=True).stdout


def repo_history(repo: Path, commit: str) -> dict:
    return history_features(git(repo, 'log', commit, f'--max-count={HISTORY_DEPTH}', '--no-merges',
                                '--no-renames', '--name-only', '--format=\x01%s'))


def extract_repo(repo_name: str, items: list, chunk: int = 0, suffixes: tuple = ('.py',)) -> list:
    warnings.simplefilter('ignore')  # ast.parse SyntaxWarnings from old sources
    repo = REPOS / repo_name.replace('/', '__')
    cache_file = CACHE / f'blobs_v{DOC_VERSION}_{repo_name.replace("/", "__")}_{chunk}.pkl'
    blobs = pickle.loads(cache_file.read_bytes()) if cache_file.exists() else {}
    reader = BlobReader(repo)
    rows = []
    started = time.time()
    for n, item in enumerate(items, 1):
        commit = item['base_commit']
        docs = {}
        for line in git(repo, 'ls-tree', '-r', commit).splitlines():
            meta, path = line.split('\t', 1)
            _mode, kind, sha = meta.split()
            if kind != 'blob' or not path.endswith(suffixes):
                continue
            if sha not in blobs:
                blobs[sha] = analyze_source(path, reader.read(sha))
            doc = blobs[sha]
            if doc.path != path:
                doc = type(doc)(**{**doc.__dict__, 'path': path})
            docs[path] = doc
        index = RepoIndex(docs)
        title, _, body = (item['problem_statement'] or '').strip().partition('\n')
        feats = candidate_features(index, issue_signals(title, body))
        add_history(feats, repo_history(repo, commit))
        keep = candidate_pool(feats)
        gold = set(item['gold_files'])
        rows.append({
            'instance_id': item['instance_id'], 'repo': repo_name,
            'gold': sorted(gold), 'n_files': len(docs),
            'gold_in_repo': sorted(gold & set(docs)),
            'cands': {p: feats[p] for p in keep},
        })
        if n % 25 == 0:
            print(f'{repo_name}: {n}/{len(items)} {time.time() - started:.0f}s', file=sys.stderr, flush=True)
    reader.proc.kill()
    cache_file.write_bytes(pickle.dumps(blobs))
    return rows


def cmd_extract(args) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    items = [json.loads(l) for l in open(args.dataset, encoding='utf-8') if l.strip()]
    if args.limit:
        items = items[: args.limit]
    groups = defaultdict(list)
    for it in sorted(items, key=lambda it: it.get('created_at') or ''):
        groups[it['repo']].append(it)
    # Date-ordered chunks: neighbouring commits share most blobs.
    suffixes = SOURCE_SUFFIXES if args.all_languages else ('.py',)
    jobs = [(repo, its[i:i + CHUNK], i // CHUNK, suffixes)
            for repo, its in groups.items() for i in range(0, len(its), CHUNK)]
    jobs.sort(key=lambda j: -len(j[1]))
    rows = []
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for part in ex.map(extract_repo, *zip(*jobs)):
            rows.extend(part)
    out = CACHE / args.out
    out.write_bytes(pickle.dumps(rows))
    print(f'wrote {out} ({len(rows)} instances)')


KS = (1, 3, 5, 10)


def load_rows(name: str) -> list:
    return pickle.loads((CACHE / name).read_bytes())


def feature_names(rows: list) -> list:
    return sorted({k for r in rows for f in r['cands'].values() for k in f})


def matrix(row: dict, names: list):
    import numpy as np
    paths = list(row['cands'])
    X = np.array([[row['cands'][p].get(k, 0.0) for k in names] for p in paths], dtype=np.float64)
    y = np.array([p in row['gold'] for p in paths], dtype=bool)
    return paths, X, y


def evaluate(rows: list, rank_fn) -> dict:
    hits = {k: 0 for k in KS}
    in_pool = 0
    for row in rows:
        ranked = rank_fn(row)
        gold = set(row['gold'])
        in_pool += bool(gold & set(row['cands']))
        for k in KS:
            hits[k] += bool(gold & set(ranked[:k]))
    n = max(len(rows), 1)
    out = {f'hit@{k}': round(hits[k] / n, 4) for k in KS}
    out['pool_recall'] = round(in_pool / n, 4)
    out['n'] = len(rows)
    return out


def fit_pairwise(rows: list, names: list, l2: float = 1e-3, epochs: int = 300, neg_per_query: int = 60):
    """RankNet-linear: minimise sum log(1+exp(-(s+ - s-))) + l2 ||w||^2 (full-batch Adam)."""
    import numpy as np
    diffs = []
    for row in rows:
        _paths, X, y = matrix(row, names)
        if not y.any() or y.all():
            continue
        pos, neg = X[y], X[~y]
        # Hard negatives: the strongest non-gold files on any channel.
        order = np.argsort(-neg.max(axis=1))[:neg_per_query]
        for p in pos:
            diffs.append(p - neg[order])
    D = np.vstack(diffs)
    sd = np.abs(D).max(0) + 1e-9  # scale only; differences are already centred
    D = D / sd
    w = np.zeros(D.shape[1]); m = np.zeros_like(w); v = np.zeros_like(w)
    for t in range(1, epochs + 1):
        z = D @ w
        g = -(D * (1 / (1 + np.exp(z)))[:, None]).mean(0) + 2 * l2 * w
        m = 0.9 * m + 0.1 * g; v = 0.999 * v + 0.001 * g * g
        w -= 0.05 * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return {k: float(wi / si) for k, wi, si in zip(names, w, sd)}


def linear_ranker(weights: dict):
    def rank(row):
        c = row['cands']
        return sorted(c, key=lambda p: -sum(weights.get(k, 0.0) * v for k, v in c[p].items()))
    return rank


def fit_gbdt(rows: list, names: list):
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier
    Xs, ys = [], []
    for row in rows:
        _p, X, y = matrix(row, names)
        if y.any():
            Xs.append(X); ys.append(y)
    model = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                           class_weight='balanced', random_state=0)
    model.fit(np.vstack(Xs), np.concatenate(ys))

    def rank(row):
        paths, X, _y = matrix(row, names)
        s = model.predict_proba(X)[:, 1]
        return [paths[i] for i in np.argsort(-s)]
    return rank


def fit_lambdamart(rows: list, names: list, **params):
    """LightGBM LambdaMART (lab only): optimises NDCG@k directly."""
    import lightgbm as lgb
    import numpy as np
    Xs, ys, groups = [], [], []
    for row in rows:
        _p, X, y = matrix(row, names)
        if y.any():
            Xs.append(X); ys.append(y.astype(int)); groups.append(len(y))
    cfg = dict(objective='lambdarank', n_estimators=400, learning_rate=0.03, num_leaves=31,
               min_child_samples=20, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
               lambdarank_truncation_level=20, verbose=-1, random_state=0)
    cfg.update(params)
    model = lgb.LGBMRanker(**cfg)
    model.fit(np.vstack(Xs), np.concatenate(ys), group=groups)

    def rank(row):
        paths, X, _y = matrix(row, names)
        s = model.predict(X)
        return [paths[i] for i in np.argsort(-s)]
    rank.model = model
    return rank


def export_trees(model, names: list) -> dict:
    """LightGBM booster -> nested lists [feature, threshold, left, right] / leaf float."""
    def conv(node):
        if 'leaf_value' in node:
            return node['leaf_value']
        assert node['decision_type'] == '<='
        return [node['split_feature'], node['threshold'], conv(node['left_child']), conv(node['right_child'])]
    dump = model.booster_.dump_model()
    return {'features': list(names),
            'trees': [conv(t['tree_structure']) for t in dump['tree_info']]}


def attach_dense(rows: list, name: str) -> None:
    """Merge per-instance dense scores as dense_n / dense_rr features (0 outside the pool)."""
    path = CACHE / name
    if not path.exists():
        return
    dense = pickle.loads(path.read_bytes())
    for row in rows:
        scores = dense.get(row['instance_id'], {})
        if not scores:
            continue
        peak = max(scores.values())
        for r, (p, v) in enumerate(sorted(scores.items(), key=lambda kv: -kv[1]), 1):
            if p in row['cands']:
                row['cands'][p]['dense_n'] = v / peak if peak > 0 else 0.0
                row['cands'][p]['dense_rr'] = 1.0 / r
                row['cands'][p]['dense_raw'] = v


def cmd_train(args) -> None:
    rows = load_rows(args.features)
    if args.dense:
        attach_dense(rows, args.dense)
    lite = {json.loads(l)['instance_id'] for l in open(args.test_ids, encoding='utf-8') if l.strip()}
    train = [r for r in rows if r['instance_id'] not in lite]
    test = [r for r in rows if r['instance_id'] in lite]
    names = feature_names(rows)
    report = {'features': names, 'n_train': len(train), 'n_test': len(test)}
    report['bm25_only'] = evaluate(test, linear_ranker({'bm25_n': 1.0}))
    weights = fit_pairwise(train, names, l2=args.l2)
    report['linear_pairwise'] = evaluate(test, linear_ranker(weights))
    report['linear_pairwise_train'] = evaluate(train, linear_ranker(weights))
    if args.gbdt:
        report['gbdt'] = evaluate(test, fit_gbdt(train, names))
    if args.lambdamart:
        lm = fit_lambdamart(train, names)
        report['lambdamart'] = evaluate(test, lm)
        imp = sorted(zip(names, lm.model.booster_.feature_importance('gain')), key=lambda kv: -kv[1])
        report['lambdamart_gain'] = {k: round(float(v)) for k, v in imp[:15]}
        if args.save_model:
            model = export_trees(lm.model, names)
            probe = test[0]
            _p, X, _y = matrix(probe, names)
            ours = [tree_score(model, probe['cands'][p]) for p in _p]
            assert max(abs(a - b) for a, b in zip(ours, lm.model.predict(X))) < 1e-6, 'tree export mismatch'
            Path(args.save_model).write_text(json.dumps(model, separators=(',', ':')), encoding='utf-8')
    if args.dump_ranking:
        # Stage-3 output consumed by the LLM verifier (benchmark/loclab_verify.py).
        ranker = lm if args.lambdamart else linear_ranker(weights)
        dump = {r['instance_id']: {'ranked': ranker(r)[:30], 'gold': sorted(r['gold']), 'repo': r['repo']} for r in test}
        Path(args.dump_ranking).write_text(json.dumps(dump), encoding='utf-8')
    if args.loro:
        # Leave-one-repository-out on the test split: weights never see the repo.
        per_repo = {}
        for repo in sorted({r['repo'] for r in test}):
            w = fit_pairwise([r for r in train if r['repo'] != repo], names, l2=args.l2)
            per_repo[repo] = evaluate([r for r in test if r['repo'] == repo], linear_ranker(w))
        report['loro'] = per_repo
        tot = sum(v['n'] for v in per_repo.values())
        report['loro_micro'] = {k: round(sum(v[k] * v['n'] for v in per_repo.values()) / tot, 4) for k in (f'hit@{k}' for k in KS)}
    report['weights'] = dict(sorted(weights.items(), key=lambda kv: -abs(kv[1])))
    print(json.dumps({k: v for k, v in report.items() if k != 'features'}, indent=1))
    if args.save_weights:
        Path(args.save_weights).write_text(json.dumps(weights, indent=1, sort_keys=True), encoding='utf-8')


CV_CONFIGS = {
    'lm_default': {},
    'lm_small': dict(n_estimators=200, num_leaves=15, min_child_samples=50),
    'lm_tiny': dict(n_estimators=150, num_leaves=7, min_child_samples=100, reg_lambda=5.0),
    'lm_mono': dict(n_estimators=200, num_leaves=15, min_child_samples=50, monotone='channels'),
}


def cmd_cv(args) -> None:
    """Leave-one-repository-out over every instance: the model never sees the test repo."""
    rows = load_rows(args.features)
    if args.dense:
        attach_dense(rows, args.dense)
    drop = set(args.drop or ())
    names = [n for n in feature_names(rows) if not any(n.startswith(d) for d in drop)]
    repos = sorted({r['repo'] for r in rows})
    out = {}
    for cfg_name in args.configs:
        cfg = dict(CV_CONFIGS[cfg_name])
        if cfg.pop('monotone', None):
            # Evidence channels may only raise the score: cannot learn repo-specific inversions.
            cfg['monotone_constraints'] = [1 if n.endswith(('_n', '_rr')) else 0 for n in names]
        per_repo = {}
        for repo in repos:
            model = fit_lambdamart([r for r in rows if r['repo'] != repo], names, **cfg)
            per_repo[repo] = evaluate([r for r in rows if r['repo'] == repo], model)
        tot = sum(v['n'] for v in per_repo.values())
        micro = {k: round(sum(v[k] * v['n'] for v in per_repo.values()) / tot, 4) for k in (f'hit@{k}' for k in KS)}
        macro = {k: round(sum(v[k] for v in per_repo.values()) / len(per_repo), 4) for k in micro}
        worst = min(per_repo.items(), key=lambda kv: kv[1]['hit@1'])
        out[cfg_name] = {'micro': micro, 'macro': macro, 'worst_repo': [worst[0], worst[1]['hit@1']],
                         'per_repo_hit1': {k: v['hit@1'] for k, v in per_repo.items()}}
        print(cfg_name, json.dumps(out[cfg_name]), flush=True)


def cmd_calibrate(args) -> None:
    """Fit reading-plan tiers on held-out queries and store them in the shipped model."""
    model_path = Path(args.model)
    model = json.loads(model_path.read_text(encoding='utf-8'))
    items = [json.loads(l) for l in open(args.calib_ids, encoding='utf-8') if l.strip()]
    language = {it['instance_id']: it.get('language', 'python') for it in items}
    queries, scores, langs, tops = [], [], [], []
    for row in load_rows(args.features):
        if row['instance_id'] not in language:
            continue
        scored = sorted(((tree_score(model, f), p) for p, f in row['cands'].items()), reverse=True)
        gold = [i for i, (_s, p) in enumerate(scored, 1) if p in row['gold']]
        margin = scored[0][0] - scored[1][0] if len(scored) > 1 else 0.0
        queries.append((margin, gold[0] if gold else None))
        scores.append([s for s, _p in scored] or [0.0])
        langs.append(language[row['instance_id']])
        tops.append(scored[0][1])
    if 'calibration' in model:
        # How the stored plan transfers to these queries, per language and overall.
        report = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for (_m, rank), sc, lang, top in zip(queries, scores, langs, tops):
            plan = reading_plan(sc, plan_calibration(model, top))
            for key in (lang, 'all'):
                for stat, ok in ((plan['confidence'], rank is not None and rank <= plan['read_first']),
                                 *((f'hit@{k}', rank is not None and rank <= k) for k in KS)):
                    report[key][stat][0] += ok
                    report[key][stat][1] += 1
        for key, stats in sorted(report.items()):
            print(key, {s: f'{a / b:.3f} (n={b})' if s in ('high', 'medium', 'low') else round(a / b, 3)
                        for s, (a, b) in stats.items()})
    # One pooled tier when the calibration set is too small for stable margin cut-offs.
    tiers = (calibrate_tiers(queries, target=args.target, shares=(), labels=('low',)) if args.single_tier
             else calibrate_tiers(queries, target=args.target))
    model[args.key] = {'target': args.target, 'n': len(queries), 'source': f'held-out {Path(args.calib_ids).stem} ({len(queries)} issues)', 'tiers': tiers}
    print(json.dumps(model[args.key], indent=1))
    if args.write:
        model_path.write_text(json.dumps(model, separators=(',', ':')), encoding='utf-8')


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract')
    e.add_argument('--dataset', default='benchmark/datasets/cache/swebench_full.jsonl')
    e.add_argument('--out', default='features_full.pkl')
    e.add_argument('--limit', type=int)
    e.add_argument('--jobs', type=int, default=8)
    e.add_argument('--all-languages', action='store_true', help='index every supported source suffix, not only .py')
    t = sub.add_parser('train')
    t.add_argument('--features', default='features_full.pkl')
    t.add_argument('--test-ids', default='benchmark/datasets/cache/swebench_lite.jsonl')
    t.add_argument('--l2', type=float, default=1e-3)
    t.add_argument('--gbdt', action='store_true')
    t.add_argument('--lambdamart', action='store_true')
    t.add_argument('--dense', help='dense score pickle to merge, e.g. dense_features_full.pkl')
    t.add_argument('--loro', action='store_true')
    t.add_argument('--save-weights')
    t.add_argument('--save-model', help='export the LambdaMART trees as pure-Python JSON')
    t.add_argument('--dump-ranking', help='write top-30 test rankings (json) for the LLM verifier')
    c = sub.add_parser('cv')
    c.add_argument('--features', default='features_full.pkl')
    c.add_argument('--dense')
    c.add_argument('--configs', nargs='+', default=list(CV_CONFIGS))
    c.add_argument('--drop', nargs='*', help='feature-name prefixes to exclude')
    k = sub.add_parser('calibrate')
    k.add_argument('--features', default='features_full_v4.pkl')
    k.add_argument('--calib-ids', default='benchmark/datasets/cache/swebench_lite.jsonl',
                   help='held-out instances: must not overlap the model training split')
    k.add_argument('--model', default='src/brain/localizer_model.json')
    k.add_argument('--target', type=float, default=0.85)
    k.add_argument('--write', action='store_true')
    k.add_argument('--key', default='calibration', choices=('calibration', 'calibration_other'),
                   help='calibration_other = plan used when the top file is not Python')
    k.add_argument('--single-tier', action='store_true')
    args = ap.parse_args()
    {'extract': cmd_extract, 'train': cmd_train, 'cv': cmd_cv, 'calibrate': cmd_calibrate}[args.cmd](args)


if __name__ == '__main__':
    main()
