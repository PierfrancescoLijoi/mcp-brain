"""Prepare local repo cache for SWE-bench Lite evaluation.

This is the only step, besides HuggingFace dataset download, that needs network.
After it succeeds, benchmark/run_eval.py can run offline against the cached repos.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def read_instances(path: Path, limit: int | None = None) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            if line.strip():
                yield json.loads(line)


def collect_repo_commits(dataset_path: Path, limit: int | None = None) -> Dict[str, Set[str]]:
    repos: Dict[str, Set[str]] = {}
    for item in read_instances(dataset_path, limit=limit):
        repos.setdefault(item["repo"], set()).add(item["base_commit"])
    return repos


def repo_dir(cache_root: Path, repo: str) -> Path:
    return cache_root / repo.replace("/", "__")


def ensure_repo(cache_root: Path, repo: str, commits: Set[str]) -> Tuple[str, str]:
    target = repo_dir(cache_root, repo)
    url = f"https://github.com/{repo}.git"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--filter=blob:none", url, str(target)])
    else:
        run(["git", "remote", "set-url", "origin", url], cwd=target)
        run(["git", "fetch", "--filter=blob:none", "origin"], cwd=target)

    missing = []
    for commit in sorted(commits):
        result = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=target)
        if result.returncode != 0:
            missing.append(commit)
    if missing:
        run(["git", "fetch", "--filter=blob:none", "origin", *missing], cwd=target)
    return repo, str(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Clone/fetch repos needed by a converted SWE-bench Lite JSONL")
    parser.add_argument("--dataset", default="benchmark/datasets/cache/swebench_lite.jsonl")
    parser.add_argument("--repo-cache", default="benchmark/repos")
    parser.add_argument("--limit", type=int, default=None, help="Prepare only first N benchmark instances")
    args = parser.parse_args()

    dataset = Path(args.dataset)
    cache_root = Path(args.repo_cache)
    repo_commits = collect_repo_commits(dataset, limit=args.limit)
    manifest = {}
    for repo, commits in sorted(repo_commits.items()):
        name, path = ensure_repo(cache_root, repo, commits)
        manifest[name] = {"path": path, "commits": sorted(commits)}
    cache_root.mkdir(parents=True, exist_ok=True)
    (cache_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Prepared {len(manifest)} repos under {cache_root}")


if __name__ == "__main__":
    main()
