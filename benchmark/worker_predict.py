"""One-instance prediction worker.

Run in a fresh Python process so MCP_BRAIN_REPO is read before src.storage.paths
module globals are initialized.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-dir", required=True)
    parser.add_argument("--base-commit", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", default="")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-hops", type=int, default=2)
    parser.add_argument("--use-semantic", action="store_true")
    args = parser.parse_args()

    repo_dir = Path(args.repo_dir).resolve()
    subprocess.run(
        ["git", "reset", "--hard", args.base_commit],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    subprocess.run(
        ["git", "clean", "-fdx", "-e", ".brain/"],
        cwd=repo_dir,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ["MCP_BRAIN_REPO"] = str(repo_dir)

    from src.brain.file_indexer import build_index
    from src.brain.code_graph import get_or_build_graph
    from src.brain.file_predictor import predict_files_with_impact

    index = build_index()
    graph = get_or_build_graph(max_age_seconds=0, repo_root=repo_dir)
    predictions = predict_files_with_impact(
        title=args.title,
        body=args.body,
        top_k=args.top_k,
        max_hops=args.max_hops,
        use_semantic=args.use_semantic,
        index=index,
        graph=graph,
    )
    print(json.dumps(predictions, ensure_ascii=False))


if __name__ == "__main__":
    main()
