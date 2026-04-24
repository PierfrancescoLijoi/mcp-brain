"""SWE-bench Lite adapter.

Downloads the HuggingFace dataset once, then converts it to a compact JSONL
format consumed by the local benchmark harness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from benchmark.adapters.patch_parser import extract_changed_files_from_patch

DATASET_NAME = "princeton-nlp/SWE-bench_Lite"
DEFAULT_SPLIT = "test"


def convert_record(row: Dict[str, Any], include_tests: bool = False) -> Dict[str, Any]:
    patch = row.get("patch") or ""
    gold_files = extract_changed_files_from_patch(patch, include_tests=include_tests)
    return {
        "instance_id": row.get("instance_id"),
        "repo": row.get("repo"),
        "base_commit": row.get("base_commit"),
        "problem_statement": row.get("problem_statement") or "",
        "gold_patch": patch,
        "gold_files": gold_files,
        "created_at": row.get("created_at"),
        "version": row.get("version"),
        "source_dataset": DATASET_NAME,
    }


def download_and_convert(output: Path, split: str = DEFAULT_SPLIT, include_tests: bool = False) -> Path:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: datasets. Install with: pip install -r benchmark/requirements-benchmark.txt"
        ) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    dataset = load_dataset(DATASET_NAME, split=split)
    count = 0
    skipped_no_gold = 0
    with output.open("w", encoding="utf-8") as f:
        for row in dataset:
            converted = convert_record(dict(row), include_tests=include_tests)
            if not converted["gold_files"]:
                skipped_no_gold += 1
                continue
            f.write(json.dumps(converted, ensure_ascii=False) + "\n")
            count += 1
    meta = {
        "dataset": DATASET_NAME,
        "split": split,
        "records": count,
        "skipped_no_gold_files": skipped_no_gold,
        "include_tests": include_tests,
        "output": str(output),
    }
    (output.with_suffix(".meta.json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and convert SWE-bench Lite to mcp-brain JSONL")
    parser.add_argument("--output", default="benchmark/datasets/cache/swebench_lite.jsonl")
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument("--include-tests", action="store_true")
    args = parser.parse_args()
    out = download_and_convert(Path(args.output), split=args.split, include_tests=args.include_tests)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
