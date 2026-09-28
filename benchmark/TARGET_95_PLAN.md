# Hit@K 85–95% engineering target

## Definition

The target is accepted only on a pinned, held-out evaluation split with test
files excluded consistently:

- Hit@1 >= 0.85
- Hit@3 >= 0.90
- Hit@5 >= 0.93
- Hit@10 >= 0.95
- zero access to commits newer than each instance's `base_commit`

These are research-level targets. They must not be reported from a replay of an
already generated top-10 list or from a split used to tune weights.

## Mathematical decomposition

Let `C(q)` be the union of candidates generated for issue `q` by exact path and
symbol lookup, BM25, semantic retrieval, personalized code-graph PageRank, and
historical co-change retrieval. No ranker can exceed candidate recall, so the
first hard gate is:

```text
Recall(C@50) >= 0.98
```

For each issue-file pair, construct the feature vector:

```text
x(q,f) = [
  bm25, exact_path, symbol_match, filename_match,
  semantic_similarity, pagerank, graph_distance,
  import_edge, call_edge, cochange_weight,
  production_prior, file_role, repository_prior
]
```

The deterministic ranker starts with a normalized linear score:

```text
s(q,f) = w · zscore(x(q,f))
```

Weights must be learned only on training repositories with pairwise logistic
ranking loss and L2 regularization:

```text
L(w) = sum(log(1 + exp(-(s(q,f+) - s(q,f-))))) + lambda * ||w||²
```

Repository-grouped cross-validation is mandatory. Splitting instances randomly
would leak repository names, layouts, and historical coupling into validation.

## Architecture

1. **Broad deterministic recall** — retain at least 50 candidates from exact,
   BM25, semantic, forward/reverse graph, and co-change channels.
2. **Role-aware representation** — encode path role, exported symbols, rare IDF
   concepts, callers, callees, and recent historical neighbors.
3. **Learned fusion** — train pairwise weights on independent repositories;
   retain the current hand-tuned weights as a no-model fallback.
4. **Evidence verifier** — for the final 20 candidates, inspect compact semantic
   cards and ask a local or remote coding model to return relevance evidence,
   not just a score.
5. **Iterative navigation** — expand unresolved symbols/imports mentioned by the
   verifier, update the candidate workspace, then rerank once.

The deterministic stages should target >=90% candidate recall at 50. Reaching
85% Hit@1 is expected to require stages 4–5; changing BM25 constants alone is
not a credible route.

## Leakage controls

- Checkout `base_commit` before indexing.
- Build co-change edges only from commits reachable from that revision.
- Pin dataset revision and record its SHA-256.
- Tune on repository-disjoint folds; reserve an untouched final test fold.
- Publish confidence intervals and per-repository metrics.
- Never use reference patches, future commits, or stored gold paths as features.

## Release gates

Every experiment records candidate recall@50, Hit/Recall/MAP at 1/3/5/10,
latency percentiles, model and dataset versions, feature flags, and cost per
query. A new ranker ships only if it improves the repository-disjoint validation
set and does not regress any major repository by more than two percentage
points.

## Results (2026-09-28)

Split: train on SWE-bench Full minus Lite (1994 instances), test on Lite
(300). Test files are excluded from gold and candidates. Every feature is read
at `base_commit` from git objects, and history uses ancestors only. With n=300
the standard error is about 2.8 points.

| Ranker (test = Lite)                         | Hit@1 | Hit@3 | Hit@5 | Hit@10 |
|----------------------------------------------|------:|------:|------:|-------:|
| Legacy predictor (symbol BM25 + graph)       | 18.7  |   —   |   —   |  60.0  |
| Content BM25 only                            | 48.3  | 72.0  | 77.3  |  84.7  |
| Linear pairwise (RankNet-linear)             | 58.7  | 77.7  | 82.3  |  88.7  |
| LambdaMART, **shipped, pure Python**         | 63.3  | 81.7  | 85.0  |  89.0  |
| LambdaMART + CodeRankEmbed dense (optional)  | 64.7  | 82.3  | 86.0  |  91.0  |
| Linear, leave-one-repo-out (micro)           | 59.3  | 78.0  | 81.7  |  88.7  |

Ceiling of the dense+LambdaMART candidate list: Hit@15 93.0, Hit@20 93.7 and
Hit@30 95.7. Stage 4 (the LLM verifier over the top-15, `benchmark/loclab_verify.py`)
can therefore reach at most 93% Hit@1.

Reproduce:

```bash
python benchmark/prefetch_blobs.py                     # partial clones -> blobs
python -m benchmark.loclab extract --out features_full_v4.pkl
python -m benchmark.loclab_dense --features features_full_v4.pkl   # optional, GPU
python -m benchmark.loclab train --features features_full_v4.pkl --lambdamart --loro \
    --save-model src/brain/localizer_model.json
```
