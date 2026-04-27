"""Prediction worker for static source-root benchmark instances.

Use this for legacy IR datasets that provide a local source snapshot instead of a
GitHub repo/base_commit pair, e.g. Bench4BL or BugLocator.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--body", default="")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-hops", type=int, default=0)
    parser.add_argument("--use-semantic", action="store_true")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve()
    if not source_root.exists():
        raise SystemExit(f"source root not found: {source_root}")

    os.environ["MCP_BRAIN_REPO"] = str(source_root)

    from src.brain.file_indexer import build_index
    from src.brain.file_predictor import predict_files_with_impact

    index = build_index()
    graph = None
    if args.max_hops > 0:
        try:
            from src.brain.code_graph import get_or_build_graph
            graph = get_or_build_graph(max_age_seconds=0, repo_root=source_root)
        except Exception:
            graph = None

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
