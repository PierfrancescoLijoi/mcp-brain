# Benchmark extensions: SWE-bench full, Bench4BL, BugLocator

This add-on extends the current SWE-bench Lite harness without changing the existing workflow.

## 1. SWE-bench full

SWE-bench full is the easiest extension because it uses the same HuggingFace/SWE-bench family format.

```powershell
pip install -r benchmark\requirements-benchmark.txt

python -m benchmark.adapters.swebench `
  --dataset-name princeton-nlp/SWE-bench `
  --output benchmark\datasets\cache\swebench_full.jsonl

python -m benchmark.prepare_repos `
  --dataset benchmark\datasets\cache\swebench_full.jsonl `
  --repo-cache benchmark\repos
```

Run a subset first:

```powershell
python -m benchmark.run_eval `
  --dataset benchmark\datasets\cache\swebench_full.jsonl `
  --repo-cache benchmark\repos `
  --out benchmark\results\swebench_full_100_semantic_gpu.json `
  --report-dir benchmark\reports `
  --top-k 10 `
  --max-hops 2 `
  --limit 100 `
  --use-semantic
```

Then full:

```powershell
python -m benchmark.run_eval `
  --dataset benchmark\datasets\cache\swebench_full.jsonl `
  --repo-cache benchmark\repos `
  --out benchmark\results\swebench_full_semantic_gpu.json `
  --report-dir benchmark\reports `
  --top-k 10 `
  --max-hops 2 `
  --use-semantic
```

## 2. Bench4BL

Bench4BL is a Java IR bug-localization dataset. Unlike SWE-bench, it may not provide GitHub `repo/base_commit` pairs. Convert it first, then use the static-source runner.

```powershell
python -m benchmark.adapters.bench4bl fetch
python -m benchmark.adapters.bench4bl inspect --root benchmark\datasets\raw\Bench4BL
```

Create a source-root map for the projects you want to evaluate:

```json
{
  "projectName": "C:/dev/bench4bl-sources/projectName"
}
```

Then convert:

```powershell
python -m benchmark.adapters.bench4bl convert `
  --root benchmark\datasets\raw\Bench4BL `
  --output benchmark\datasets\cache\bench4bl.jsonl `
  --source-root-map benchmark\datasets\source_root_maps\bench4bl.json
```

Smoke run, usually BM25/path only first:

```powershell
python -m benchmark.run_eval_static `
  --dataset benchmark\datasets\cache\bench4bl.jsonl `
  --out benchmark\results\bench4bl_30.json `
  --report-dir benchmark\reports `
  --top-k 10 `
  --max-hops 0 `
  --limit 30
```

## 3. BugLocator

Download the BugLocator archive manually from the Figshare page or pass a direct archive URL if you have one.

Manual archive path:

```powershell
python -m benchmark.adapters.buglocator extract `
  --archive C:\path\to\BugLocator.zip `
  --root benchmark\datasets\raw\BugLocator
```

Or direct URL:

```powershell
python -m benchmark.adapters.buglocator fetch `
  --url "https://direct-download-url/file.zip" `
  --archive benchmark\datasets\raw\buglocator_archive.zip `
  --root benchmark\datasets\raw\BugLocator
```

Inspect and convert:

```powershell
python -m benchmark.adapters.buglocator inspect --root benchmark\datasets\raw\BugLocator

python -m benchmark.adapters.buglocator convert `
  --root benchmark\datasets\raw\BugLocator `
  --output benchmark\datasets\cache\buglocator.jsonl `
  --source-root-map benchmark\datasets\source_root_maps\buglocator.json
```

Evaluate:

```powershell
python -m benchmark.run_eval_static `
  --dataset benchmark\datasets\cache\buglocator.jsonl `
  --out benchmark\results\buglocator_30.json `
  --report-dir benchmark\reports `
  --top-k 10 `
  --max-hops 0 `
  --limit 30
```

## Notes

- SWE-bench full is immediately runnable with the existing Git-based runner.
- Bench4BL/BugLocator are legacy IR datasets; layouts vary. The adapters include `inspect` so you can verify parsed files before evaluation.
- For Java/static datasets, start with `--max-hops 0`. Enable graph only after confirming Java graph indexing works well in your repo.
- The benchmark remains offline-first after the one-time fetch/conversion step.
