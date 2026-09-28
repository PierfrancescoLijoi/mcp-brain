"""Generic SWE-bench adapter for Lite / Full / Verified.

Converts HuggingFace SWE-bench-family datasets to the common mcp-brain
benchmark JSONL format used by benchmark.run_eval.

Examples:
    # Lite, equivalent to the existing adapter
    python -m benchmark.adapters.swebench \
      --dataset-name princeton-nlp/SWE-bench_Lite \
      --output benchmark/datasets/cache/swebench_lite.jsonl

    # Full SWE-bench, 2294 instances
    python -m benchmark.adapters.swebench \
      --dataset-name princeton-nlp/SWE-bench \
      --output benchmark/datasets/cache/swebench_full.jsonl

    # Verified subset
    python -m benchmark.adapters.swebench \
      --dataset-name princeton-nlp/SWE-bench_Verified \
      --output benchmark/datasets/cache/swebench_verified.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List

from benchmark.adapters.patch_parser import extract_changed_files_from_patch

DEFAULT_DATASET_NAME = "princeton-nlp/SWE-bench"
DEFAULT_SPLIT = "test"


def _first_present(row: Dict[str, Any], keys: Iterable[str], default: Any = None) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _extract_patch(row: Dict[str, Any]) -> str:
    # SWE-bench-family datasets commonly expose `patch`; keep alternatives for
    # future compatibility / mirrored datasets.
    return str(_first_present(row, ("patch", "gold_patch", "reference_patch", "solution_patch"), "") or "")


LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".pyi": "python", ".go": "go", ".rs": "rust", ".java": "java", ".cs": "csharp",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
}


def infer_language(files: List[str]) -> str:
    """Majority language of the gold files; "other" when none is a supported source file."""
    langs = Counter(LANGUAGE_BY_SUFFIX.get(PurePosixPath(f).suffix.lower(), "other") for f in files)
    return langs.most_common(1)[0][0] if langs else "other"


def convert_record(row: Dict[str, Any], dataset_name: str, include_tests: bool = False) -> Dict[str, Any]:
    patch = _extract_patch(row)
    gold_files = extract_changed_files_from_patch(patch, include_tests=include_tests)
    return {
        "instance_id": _first_present(row, ("instance_id", "id")),
        "dataset": dataset_name.rsplit("/", 1)[-1].lower(),
        "repo": row.get("repo"),
        "language": infer_language(gold_files),
        "base_commit": row.get("base_commit"),
        "problem_statement": row.get("problem_statement") or "",
        "gold_patch": patch,
        "gold_files": gold_files,
        "created_at": row.get("created_at"),
        "version": row.get("version"),
        "source_dataset": dataset_name,
        "metadata": {
            "raw_keys": sorted(row.keys()),
        },
    }


def download_and_convert(
    output: Path,
    dataset_name: str = DEFAULT_DATASET_NAME,
    split: str = DEFAULT_SPLIT,
    include_tests: bool = False,
    limit: int | None = None,
) -> Path:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: datasets. Install with: pip install -r benchmark/requirements-benchmark.txt"
        ) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    ds = load_dataset(dataset_name, split=split)
    count = 0
    skipped_no_gold = 0
    skipped_missing_fields = 0

    with output.open("w", encoding="utf-8") as f:
        for i, row in enumerate(ds):
            if limit is not None and i >= limit:
                break
            converted = convert_record(dict(row), dataset_name=dataset_name, include_tests=include_tests)
            if not converted.get("repo") or not converted.get("base_commit"):
                skipped_missing_fields += 1
                continue
            if not converted["gold_files"]:
                skipped_no_gold += 1
                continue
            f.write(json.dumps(converted, ensure_ascii=False) + "\n")
            count += 1

    meta = {
        "dataset": dataset_name,
        "split": split,
        "records": count,
        "skipped_no_gold_files": skipped_no_gold,
        "skipped_missing_repo_or_commit": skipped_missing_fields,
        "include_tests": include_tests,
        "limit": limit,
        "output": str(output),
    }
    output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and convert SWE-bench-family datasets to mcp-brain JSONL")
    parser.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    parser.add_argument("--split", default=DEFAULT_SPLIT)
    parser.add_argument("--output", default="benchmark/datasets/cache/swebench_full.jsonl")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    out = download_and_convert(
        output=Path(args.output),
        dataset_name=args.dataset_name,
        split=args.split,
        include_tests=args.include_tests,
        limit=args.limit,
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
