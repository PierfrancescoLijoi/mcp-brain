"""Repository-batched prediction worker.

One process handles every instance for a repository. This keeps repository
isolation while loading Python, parsers, CUDA, and the semantic model only once.
Input is a JSON array on stdin; output is a JSON array on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _split_title_body(problem_statement: str) -> tuple[str, str]:
    text = (problem_statement or '').strip()
    if not text:
        return 'Empty SWE-bench issue', ''
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[0][:240] if lines else text[:240]), text


def predict_one(
    repo_dir: Path,
    item: dict[str, Any],
    top_k: int,
    max_hops: int,
    use_semantic: bool,
) -> list[dict[str, Any]]:
    subprocess.run(
        ['git', 'reset', '--hard', item['base_commit']],
        cwd=repo_dir,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ['git', 'clean', '-fdx', '-e', '.brain/'],
        cwd=repo_dir,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    from src.brain.code_graph import get_or_build_graph
    from src.brain.file_indexer import build_index
    from src.brain.file_predictor import predict_files_with_impact

    index = build_index()
    graph = get_or_build_graph(max_age_seconds=0, repo_root=repo_dir)
    title, body = _split_title_body(item.get('problem_statement', ''))
    return predict_files_with_impact(
        title=title,
        body=body,
        top_k=top_k,
        max_hops=max_hops,
        use_semantic=use_semantic,
        index=index,
        graph=graph,
    )


def process_instances(
    repo_dir: str | Path,
    items: list[dict[str, Any]],
    *,
    top_k: int,
    max_hops: int,
    use_semantic: bool,
) -> list[dict[str, Any]]:
    repo = Path(repo_dir).resolve()
    previous_repo = os.environ.get('MCP_BRAIN_REPO')
    os.environ['MCP_BRAIN_REPO'] = str(repo)
    rows = []
    try:
        for item in items:
            try:
                predictions = predict_one(
                    repo, item, top_k, max_hops, use_semantic
                )
                error = None
            except Exception as exc:
                predictions = []
                error = str(exc)
            rows.append({
                'instance_id': item.get('instance_id'),
                'predictions': predictions,
                'error': error,
            })
    finally:
        if previous_repo is None:
            os.environ.pop('MCP_BRAIN_REPO', None)
        else:
            os.environ['MCP_BRAIN_REPO'] = previous_repo
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo-dir', required=True)
    parser.add_argument('--top-k', type=int, default=10)
    parser.add_argument('--max-hops', type=int, default=2)
    parser.add_argument('--use-semantic', action='store_true')
    args = parser.parse_args()
    items = json.load(sys.stdin)
    rows = process_instances(
        args.repo_dir,
        items,
        top_k=args.top_k,
        max_hops=args.max_hops,
        use_semantic=args.use_semantic,
    )
    print(json.dumps(rows, ensure_ascii=False))


if __name__ == '__main__':
    main()
