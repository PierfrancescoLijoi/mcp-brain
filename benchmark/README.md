# mcp-brain benchmark harness — SWE-bench Lite

This folder adds an offline-first, file-localization benchmark for `mcp-brain` using **SWE-bench Lite**.

The benchmark question is:

> Given a real GitHub issue/problem statement, can `mcp-brain` rank the files that the accepted reference patch actually modified?

It measures file-level localization quality, not whether the system can generate the final code patch.

## Why SWE-bench Lite

SWE-bench Lite gives 300 real Python bug-fix tasks with `repo`, `base_commit`, `problem_statement`, and reference `patch`. The adapter extracts file-level ground truth from the reference patch.

## Offline-first flow

Network is required only for the one-time preparation steps:

```bash
pip install -e .
pip install -r benchmark/requirements-benchmark.txt
python -m benchmark.adapters.swebench_lite --output benchmark/datasets/cache/swebench_lite.jsonl
python -m benchmark.prepare_repos --dataset benchmark/datasets/cache/swebench_lite.jsonl --repo-cache benchmark/repos
```

After that, evaluation is offline:

```bash
python -m benchmark.run_eval \
  --dataset benchmark/datasets/cache/swebench_lite.jsonl \
  --repo-cache benchmark/repos \
  --out benchmark/results/swebench_lite_results.json \
  --report-dir benchmark/reports \
  --top-k 10 \
  --max-hops 2
```

For a quick smoke run:

```bash
python -m benchmark.run_eval --limit 5 --timeout 180
```

## Outputs

- `benchmark/results/swebench_lite_results.json`: complete machine-readable results
- `benchmark/reports/swebench_lite_report.md`: markdown report
- `benchmark/reports/swebench_lite_report.html`: readable HTML report

## Metrics

The harness reports:

- `Hit@K`: at least one gold file appears in top-K predictions
- `Recall@K`: fraction of gold files recovered in top-K
- `MAP@K`: average precision at K

Default K values: 1, 3, 5, 10.

## Important design choice

By default the adapter excludes test files from ground truth. This makes the benchmark stricter for the product goal: predict the production files to modify from a ticket. To include tests too:

```bash
python -m benchmark.adapters.swebench_lite --include-tests
```

## Notes

- `mcp-brain.json` is intentionally not required and not used.
- The repo cache is not committed and can be large.
- `--use-semantic` is optional; it requires the semantic reranker dependencies/model cache to be available locally.
