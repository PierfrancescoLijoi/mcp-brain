"""Run file-localization benchmark on static source-root datasets.

Use this for Bench4BL/BugLocator-style JSONL where each record has `source_root`.
For SWE-bench datasets with GitHub repo/base_commit, keep using benchmark.run_eval.
"""
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
        return "Empty bug report", ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0][:240] if lines else text[:240]
    return title, text


def run_worker(item: Dict[str, Any], top_k: int, max_hops: int, use_semantic: bool, timeout: int) -> tuple[List[Dict[str, Any]], str | None]:
    source_root = item.get("source_root")
    if not source_root:
        return [], "missing source_root; provide --source-root-map during conversion"
    title, body = split_title_body(item.get("problem_statement", ""))
    cmd = [
        sys.executable, "-m", "benchmark.worker_predict_static",
        "--source-root", str(source_root),
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
    parser = argparse.ArgumentParser(description="Evaluate mcp-brain on static-source bug-localization datasets")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--out", default="benchmark/results/static_results.json")
    parser.add_argument("--report-dir", default="benchmark/reports")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-hops", type=int, default=0, help="Use 0 first for Java/legacy datasets unless graph support is confirmed")
    parser.add_argument("--use-semantic", action="store_true")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    started = time.time()
    instances = read_instances(Path(args.dataset), limit=args.limit)
    results = []

    for idx, item in enumerate(instances, start=1):
        print(f"[{idx}/{len(instances)}] {item.get('instance_id')} {item.get('project') or item.get('repo')}", flush=True)
        predictions, error = run_worker(item, args.top_k, args.max_hops, args.use_semantic, args.timeout)
        predicted_files = [p.get("file") for p in predictions if p.get("file")]
        gold_files = item.get("gold_files", [])
        metrics = {}
        for k in (1, 3, 5, 10):
            metrics[f"hit@{k}"] = hit_at_k(predicted_files, gold_files, k)
            metrics[f"recall@{k}"] = file_recall_at_k(predicted_files, gold_files, k)
            metrics[f"ap@{k}"] = average_precision_at_k(predicted_files, gold_files, k)
        results.append({
            "instance_id": item.get("instance_id"),
            "dataset": item.get("dataset"),
            "project": item.get("project"),
            "source_root": item.get("source_root"),
            "gold_files": gold_files,
            "predicted_files": predicted_files,
            "predictions": predictions,
            "metrics": metrics,
            "error": error,
        })

    payload = {
        "config": {
            "dataset": args.dataset,
            "limit": args.limit,
            "top_k": args.top_k,
            "max_hops": args.max_hops,
            "use_semantic": args.use_semantic,
            "runner": "run_eval_static",
        },
        "summary": summarize(results),
        "results": results,
        "elapsed_seconds": round(time.time() - started, 2),
    }
    out = Path(args.out)
    report_dir = Path(args.report_dir)
    write_json(out, payload)
    write_markdown(report_dir / "static_report.md", payload)
    write_html(report_dir / "static_report.html", payload)
    print(json.dumps(payload["summary"], indent=2))
    print(f"Wrote {out}")
    print(f"Wrote {report_dir / 'static_report.html'}")


if __name__ == "__main__":
    main()
