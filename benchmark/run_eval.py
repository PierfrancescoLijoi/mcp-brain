"""Run offline file-localization benchmark on converted SWE-bench Lite data."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def run_repo_batch(
    repo: str,
    items: List[Dict[str, Any]],
    cache_root: Path,
    top_k: int,
    max_hops: int,
    use_semantic: bool,
    timeout: int,
) -> List[Dict[str, Any]]:
    rdir = repo_dir(cache_root, repo)
    if not rdir.exists():
        error = f"repo cache not found: {rdir}. Run benchmark/prepare_repos.py first."
        return [
            {'instance_id': item['instance_id'], 'predictions': [], 'error': error}
            for item in items
        ]
    cmd = [
        sys.executable, '-m', 'benchmark.worker_predict_batch',
        '--repo-dir', str(rdir),
        '--top-k', str(top_k),
        '--max-hops', str(max_hops),
    ]
    if use_semantic:
        cmd.append('--use-semantic')
    try:
        completed = subprocess.run(
            cmd,
            input=json.dumps(items),
            text=True,
            encoding='utf-8',
            capture_output=True,
            check=True,
            timeout=max(timeout, timeout * len(items)),
        )
        return json.loads(completed.stdout)
    except subprocess.CalledProcessError as exc:
        error = (exc.stderr or exc.stdout or str(exc))[-2000:]
    except Exception as exc:
        error = str(exc)
    return [
        {'instance_id': item['instance_id'], 'predictions': [], 'error': error}
        for item in items
    ]


def run_batched(
    instances: List[Dict[str, Any]],
    cache_root: Path,
    top_k: int,
    max_hops: int,
    use_semantic: bool,
    timeout: int,
    jobs: int,
) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in instances:
        groups.setdefault(item['repo'], []).append(item)

    by_id: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        futures = {
            executor.submit(
                run_repo_batch,
                repo,
                items,
                cache_root,
                top_k,
                max_hops,
                use_semantic,
                timeout,
            ): (repo, len(items))
            for repo, items in groups.items()
        }
        for future in as_completed(futures):
            repo, count = futures[future]
            print(f"completed {repo} ({count} instances)", flush=True)
            for row in future.result():
                by_id[row['instance_id']] = row

    return [
        by_id.get(item['instance_id'], {
            'instance_id': item['instance_id'],
            'predictions': [],
            'error': 'batch worker returned no result',
        })
        for item in instances
    ]


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
    parser.add_argument(
        '--jobs', type=int, default=1,
        help='Repository batches to run concurrently. Use 1 with one GPU.',
    )
    parser.add_argument(
        '--legacy-instance-workers', action='store_true',
        help='Start one Python process per instance (slow compatibility mode).',
    )
    args = parser.parse_args()

    dataset = Path(args.dataset)
    cache_root = Path(args.repo_cache)
    started = time.time()
    instances = read_instances(dataset, limit=args.limit)
    results = []
    if args.legacy_instance_workers:
        worker_rows = []
        for idx, item in enumerate(instances, start=1):
            print(f"[{idx}/{len(instances)}] {item['instance_id']} {item['repo']}", flush=True)
            predictions, error = run_worker(item, cache_root, args.top_k, args.max_hops, args.use_semantic, args.timeout)
            worker_rows.append({
                'instance_id': item['instance_id'],
                'predictions': predictions,
                'error': error,
            })
    else:
        worker_rows = run_batched(
            instances,
            cache_root,
            args.top_k,
            args.max_hops,
            args.use_semantic,
            args.timeout,
            args.jobs,
        )

    for item, worker_row in zip(instances, worker_rows):
        predictions = worker_row['predictions']
        error = worker_row['error']
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
            "jobs": args.jobs,
            "runner": (
                'legacy-instance' if args.legacy_instance_workers else 'repo-batch'
            ),
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
