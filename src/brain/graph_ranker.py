"""Issue-conditioned ranking over the repository's static code graph.

The existing impact traversal answers "what depends on this file?". Fault
localization needs both directions: a failure mentioned in a controller can be
implemented in a validator it imports, while a low-level failure can surface in
one of its callers. Personalized PageRank provides this bidirectional,
degree-normalized propagation without allowing high-degree hubs to dominate.
"""

from __future__ import annotations

import math
from typing import Any


IMPORT_WEIGHT = 1.0
CALL_WEIGHT = 1.5
COCHANGE_WEIGHT = 0.8


def build_file_adjacency(
    graph: dict[str, Any],
) -> dict[str, dict[str, float]]:
    """Build a deterministic weighted, bidirectional file adjacency map."""
    files = graph.get("files", {}) if graph else {}
    if not files:
        return {}

    edge_weights: dict[tuple[str, str], float] = {}

    def connect(left: str, right: str, weight: float) -> None:
        if left == right or left not in files or right not in files:
            return
        key = tuple(sorted((left, right)))
        edge_weights[key] = max(edge_weights.get(key, 0.0), weight)

    for file in sorted(files):
        data = files[file]
        for item in data.get("imports_to", []):
            target = item.get("resolved")
            if target:
                connect(file, target, IMPORT_WEIGHT)
        for importer in data.get("imported_by", []):
            connect(file, importer, IMPORT_WEIGHT)
        for item in data.get("calls_out", []):
            for target in item.get("resolves_to", []):
                connect(file, target, CALL_WEIGHT)
        for item in data.get("called_by", []):
            caller = item.get("file")
            if caller:
                connect(file, caller, CALL_WEIGHT)

    for file, neighbors in sorted(graph.get('cochange', {}).items()):
        for neighbor, raw_weight in sorted(neighbors.items()):
            weight = COCHANGE_WEIGHT * math.log1p(max(float(raw_weight), 0.0))
            if weight > 0:
                connect(file, neighbor, weight)

    adjacency: dict[str, dict[str, float]] = {
        file: {} for file in sorted(files)
    }
    for (left, right), weight in sorted(edge_weights.items()):
        adjacency[left][right] = weight
        adjacency[right][left] = weight
    return adjacency


def personalized_pagerank(
    graph: dict[str, Any],
    seeds: dict[str, float],
    *,
    damping: float = 0.72,
    iterations: int = 24,
    tolerance: float = 1e-10,
    max_hops: int | None = None,
) -> dict[str, float]:
    """Rank files using a weighted random walk restarted on lexical seeds."""
    adjacency = build_file_adjacency(graph)
    positive = {
        file: float(weight)
        for file, weight in seeds.items()
        if file in adjacency and float(weight) > 0
    }
    total_seed = sum(positive.values())
    if not adjacency or total_seed <= 0:
        return {}

    if max_hops is not None:
        allowed = set(positive)
        frontier = set(positive)
        for _ in range(max(0, max_hops)):
            next_frontier = {
                neighbor
                for file in frontier
                for neighbor in adjacency[file]
                if neighbor not in allowed
            }
            allowed.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        adjacency = {
            file: {
                neighbor: weight
                for neighbor, weight in neighbors.items()
                if neighbor in allowed
            }
            for file, neighbors in adjacency.items()
            if file in allowed
        }

    restart = {
        file: positive.get(file, 0.0) / total_seed for file in adjacency
    }
    scores = dict(restart)

    for _ in range(max(1, iterations)):
        updated = {
            file: (1.0 - damping) * restart[file] for file in adjacency
        }
        dangling_mass = 0.0

        for file in sorted(adjacency):
            neighbors = adjacency[file]
            weight_sum = sum(neighbors.values())
            if weight_sum <= 0:
                dangling_mass += damping * scores[file]
                continue
            for neighbor, edge_weight in sorted(neighbors.items()):
                updated[neighbor] += (
                    damping * scores[file] * edge_weight / weight_sum
                )

        if dangling_mass:
            for file in updated:
                updated[file] += dangling_mass * restart[file]

        delta = sum(abs(updated[file] - scores[file]) for file in updated)
        scores = updated
        if delta <= tolerance:
            break

    total = sum(scores.values())
    if total <= 0:
        return {}
    return {
        file: scores[file] / total
        for file in sorted(scores)
        if scores[file] > 0
    }
