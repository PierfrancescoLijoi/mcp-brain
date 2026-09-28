"""Repository-specific historical coupling derived from prior Git commits."""

from __future__ import annotations

import math
import subprocess
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from src.brain.file_indexer import CODE_EXTENSIONS


def _commit_file_sets(repo_root: Path, max_commits: int) -> list[list[str]]:
    try:
        output = subprocess.check_output(
            [
                'git', '-C', str(repo_root), 'log', '--no-merges',
                f'--max-count={max_commits}', '--name-only',
                '--pretty=format:--MCP-BRAIN-COMMIT--',
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []

    commits: list[list[str]] = []
    current: list[str] = []
    for raw_line in output.splitlines():
        line = raw_line.strip().replace('\\', '/')
        if line == '--MCP-BRAIN-COMMIT--':
            if current:
                commits.append(current)
            current = []
        elif line and Path(line).suffix.lower() in CODE_EXTENSIONS:
            current.append(line)
    if current:
        commits.append(current)
    return commits


def build_cochange_graph(
    repo_root: str | Path,
    *,
    max_commits: int = 500,
    max_files_per_commit: int = 20,
    half_life_commits: float = 150.0,
) -> dict[str, dict[str, float]]:
    """Build a symmetric, recency-weighted historical coupling graph.

    A commit contributes ``2^(-age/half_life)/(n-1)`` to each file pair.
    Dividing by commit size prevents broad formatting/vendor commits from
    producing an overwhelming clique. Commits above the cap are ignored.
    """
    root = Path(repo_root).resolve()
    commits = _commit_file_sets(root, max_commits)
    weights: dict[str, dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    for age, raw_files in enumerate(commits):
        files = sorted(set(raw_files))
        if len(files) < 2 or len(files) > max_files_per_commit:
            continue
        recency = math.pow(2.0, -age / max(half_life_commits, 1.0))
        contribution = recency / (len(files) - 1)
        for left, right in combinations(files, 2):
            weights[left][right] += contribution
            weights[right][left] += contribution

    return {
        file: {
            neighbor: round(weight, 8)
            for neighbor, weight in sorted(neighbors.items())
        }
        for file, neighbors in sorted(weights.items())
    }
