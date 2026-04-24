# SWE-bench Lite benchmark quickstart

Questo pacchetto aggiunge a `mcp-brain` un harness benchmark **offline-first** basato su SWE-bench Lite.

## Setup una tantum online

```bash
pip install -e .
pip install -r benchmark/requirements-benchmark.txt
python -m benchmark.adapters.swebench_lite --output benchmark/datasets/cache/swebench_lite.jsonl
python -m benchmark.prepare_repos --dataset benchmark/datasets/cache/swebench_lite.jsonl --repo-cache benchmark/repos
```

## Eval offline

```bash
python -m benchmark.run_eval \
  --dataset benchmark/datasets/cache/swebench_lite.jsonl \
  --repo-cache benchmark/repos \
  --out benchmark/results/swebench_lite_results.json \
  --report-dir benchmark/reports \
  --top-k 10 \
  --max-hops 2
```

## Smoke test rapido

```bash
python -m benchmark.run_eval --limit 5 --timeout 180
```

## Output

- `benchmark/results/swebench_lite_results.json`
- `benchmark/reports/swebench_lite_report.md`
- `benchmark/reports/swebench_lite_report.html`

`mcp-brain.json` non è richiesto e non viene usato dal benchmark.
