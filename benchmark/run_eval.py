"""Run offline file-localization benchmark on converted SWE-bench Lite data."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from benchmark.adapters.patch_parser import average_precision_at_k, file_recall_at_k, hit_at_k
from benchmark.reporting import summarize, write_html, write_json, write_markdown


def repo_dir(cache_root: Path, repo: str) -> Path:
    return cache_root / repo.replace("/", "__")


def read_instances(path: Path, limit: int | None = None) -> List[Dict[str, Any]]:
    items = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            if line.strip():
                items.append(json.loads(line))
    return items


def split_title_body(problem_statement: str) -> tuple[str, str]:
    text = (problem_statement or "").strip()
    if not text:
        return "Empty SWE-bench issue", ""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = lines[0][:240] if lines else text[:240]
    return title, text


def run_worker(item: Dict[str, Any], cache_root: Path, top_k: int, max_hops: int, use_semantic: bool, timeout: int) -> tuple[List[Dict[str, Any]], str | None]:
    rdir = repo_dir(cache_root, item["repo"])
    if not rdir.exists():
        return [], f"repo cache not found: {rdir}. Run benchmark/prepare_repos.py first."
    title, body = split_title_body(item.get("problem_statement", ""))
    cmd = [
        sys.executable, "-m", "benchmark.worker_predict",
        "--repo-dir", str(rdir),
        "--base-commit", item["base_commit"],
        "--title", title,
        "--body", body,
        "--top-k", str(top_k),
        "--max-hops", str(max_hops),
    ]
    if use_semantic:
        cmd.append("--use-semantic")
    try:
        completed = subprocess.run(cmd, text=True, capture_output=True, check=True, timeout=timeout)
        return json.loads(completed.stdout), None
    except subprocess.CalledProcessError as exc:
        return [], (exc.stderr or exc.stdout or str(exc))[-2000:]
    except Exception as exc:
        return [], str(exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate mcp-brain file prediction on SWE-bench Lite")
    parser.add_argument("--dataset", default="benchmark/datasets/cache/swebench_lite.jsonl")
    parser.add_argument("--repo-cache", default="benchmark/repos")
    parser.add_argument("--out", default="benchmark/results/swebench_lite_results.json")
    parser.add_argument("--report-dir", default="benchmark/reports")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-hops", type=int, default=2)
    parser.add_argument(
        "--use-semantic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable semantic reranking. Enabled by default; use --no-use-semantic to disable.",
    )
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    dataset = Path(args.dataset)
    cache_root = Path(args.repo_cache)
    started = time.time()
    instances = read_instances(dataset, limit=args.limit)
    results = []
    for idx, item in enumerate(instances, start=1):
        print(f"[{idx}/{len(instances)}] {item['instance_id']} {item['repo']}", flush=True)
        predictions, error = run_worker(item, cache_root, args.top_k, args.max_hops, args.use_semantic, args.timeout)
        predicted_files = [p.get("file") for p in predictions if p.get("file")]
        gold_files = item.get("gold_files", [])
        metrics = {}
        for k in (1, 3, 5, 10):
            metrics[f"hit@{k}"] = hit_at_k(predicted_files, gold_files, k)
            metrics[f"recall@{k}"] = file_recall_at_k(predicted_files, gold_files, k)
            metrics[f"ap@{k}"] = average_precision_at_k(predicted_files, gold_files, k)
        results.append({
            "instance_id": item["instance_id"],
            "repo": item["repo"],
            "base_commit": item["base_commit"],
            "gold_files": gold_files,
            "predicted_files": predicted_files,
            "predictions": predictions,
            "metrics": metrics,
            "error": error,
        })

    payload = {
        "config": {
            "dataset": str(dataset),
            "repo_cache": str(cache_root),
            "limit": args.limit,
            "top_k": args.top_k,
            "max_hops": args.max_hops,
            "use_semantic": args.use_semantic,
        },
        "summary": summarize(results),
        "results": results,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    out = Path(args.out)
    report_dir = Path(args.report_dir)
    write_json(out, payload)
    write_markdown(report_dir / "swebench_lite_report.md", payload)
    write_html(report_dir / "swebench_lite_report.html", payload)
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {out}")
    print(f"Wrote {report_dir / 'swebench_lite_report.html'}")


if __name__ == "__main__":
    main()
