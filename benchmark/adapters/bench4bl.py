"""Bench4BL adapter.

Bench4BL is a legacy IR bug-localization dataset. This adapter has two goals:
1. Fetch the public dataset repository.
2. Normalize discoverable bug-report/fixed-file files to mcp-brain JSONL.

Because Bench4BL distributions have varied layouts across mirrors/forks, this
adapter includes an `inspect` command and a robust generic converter. For actual
evaluation you must provide source snapshots with --source-root-map, mapping each
project name to a local source root.

Examples:
    python -m benchmark.adapters.bench4bl fetch
    python -m benchmark.adapters.bench4bl inspect --root benchmark/datasets/raw/Bench4BL
    python -m benchmark.adapters.bench4bl convert \
      --root benchmark/datasets/raw/Bench4BL \
      --output benchmark/datasets/cache/bench4bl.jsonl \
      --source-root-map benchmark/datasets/source_root_maps/bench4bl.json
"""
from __future__ import annotations

import argparse
from pathlib import Path

from benchmark.adapters.local_ir_common import convert_directory, discover_files, ensure_git_clone, load_source_root_map

DEFAULT_REPO = "https://github.com/exatoa/Bench4BL.git"
DEFAULT_ROOT = Path("benchmark/datasets/raw/Bench4BL")
DEFAULT_OUTPUT = Path("benchmark/datasets/cache/bench4bl.jsonl")


def cmd_fetch(args: argparse.Namespace) -> None:
    ensure_git_clone(args.repo_url, Path(args.root))


def cmd_inspect(args: argparse.Namespace) -> None:
    root = Path(args.root)
    files = discover_files(root)
    print(f"Found {len(files)} candidate metadata files under {root}")
    for path in files[: args.limit]:
        print(path)
    if len(files) > args.limit:
        print(f"... {len(files) - args.limit} more")


def cmd_convert(args: argparse.Namespace) -> None:
    source_root_map = load_source_root_map(args.source_root_map)
    convert_directory(
        root=Path(args.root),
        output=Path(args.output),
        dataset="bench4bl",
        source_root_map=source_root_map,
        max_records=args.limit,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch/convert Bench4BL to mcp-brain JSONL")
    sub = parser.add_subparsers(required=True)

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("--repo-url", default=DEFAULT_REPO)
    p_fetch.add_argument("--root", default=str(DEFAULT_ROOT))
    p_fetch.set_defaults(func=cmd_fetch)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("--root", default=str(DEFAULT_ROOT))
    p_inspect.add_argument("--limit", type=int, default=80)
    p_inspect.set_defaults(func=cmd_inspect)

    p_convert = sub.add_parser("convert")
    p_convert.add_argument("--root", default=str(DEFAULT_ROOT))
    p_convert.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p_convert.add_argument("--source-root-map", default=None, help="JSON mapping project -> local source root")
    p_convert.add_argument("--limit", type=int, default=None)
    p_convert.set_defaults(func=cmd_convert)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
