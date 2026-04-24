"""Utilities for extracting file-level ground truth from unified git patches."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Iterable, List, Set

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.*?) b/(.*?)$")
_FILE_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+(?:a|b)/(.*?)$")
_DEV_NULL = "/dev/null"


def normalize_patch_path(path: str) -> str:
    """Normalize a path from a git patch to a clean relative POSIX path."""
    path = (path or "").strip().strip('"')
    if not path or path == _DEV_NULL:
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    normalized = PurePosixPath(path).as_posix().lstrip("./")
    if normalized.startswith("../") or normalized == "..":
        return ""
    return normalized


def extract_changed_files_from_patch(patch: str, include_tests: bool = False) -> List[str]:
    """Extract changed file paths from a unified git patch.

    By default test-only files are excluded because the benchmark target is
    ticket -> production files to edit. Set include_tests=True to evaluate all
    files touched by the reference patch.
    """
    files: Set[str] = set()
    for raw_line in (patch or "").splitlines():
        line = raw_line.rstrip("\n")
        m = _DIFF_GIT_RE.match(line)
        if m:
            old_path = normalize_patch_path(m.group(1))
            new_path = normalize_patch_path(m.group(2))
            candidate = new_path or old_path
            if candidate:
                files.add(candidate)
            continue
        m = _FILE_HEADER_RE.match(line)
        if m:
            candidate = normalize_patch_path(m.group(1))
            if candidate:
                files.add(candidate)

    filtered = [f for f in files if include_tests or not is_test_file(f)]
    return sorted(filtered)


def is_test_file(path: str) -> bool:
    p = path.lower()
    parts = p.split("/")
    name = parts[-1] if parts else p
    return (
        "test" in parts
        or "tests" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_tests.py")
        or "/testing/" in f"/{p}/"
    )


def file_recall_at_k(predicted: Iterable[str], gold: Iterable[str], k: int) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    pred_set = set(list(predicted)[:k])
    return len(pred_set & gold_set) / len(gold_set)


def hit_at_k(predicted: Iterable[str], gold: Iterable[str], k: int) -> int:
    gold_set = set(gold)
    if not gold_set:
        return 0
    return int(bool(set(list(predicted)[:k]) & gold_set))


def average_precision_at_k(predicted: Iterable[str], gold: Iterable[str], k: int) -> float:
    gold_set = set(gold)
    if not gold_set:
        return 0.0
    hits = 0
    score = 0.0
    for rank, file in enumerate(list(predicted)[:k], start=1):
        if file in gold_set:
            hits += 1
            score += hits / rank
    return score / min(len(gold_set), k)
