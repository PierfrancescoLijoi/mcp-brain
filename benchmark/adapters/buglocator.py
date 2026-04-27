"""BugLocator dataset adapter.

BugLocator-style datasets are usually distributed as archives containing bug
reports and fixed-file mappings for Java/Eclipse-family projects. Figshare/DOI
pages often require a browser or a direct file URL, so this adapter supports both:

    # If you have a direct archive URL:
    python -m benchmark.adapters.buglocator fetch --url <direct_zip_url>

    # If you downloaded manually from Figshare:
    python -m benchmark.adapters.buglocator extract --archive path/to/BugLocator.zip

    # Inspect and convert:
    python -m benchmark.adapters.buglocator inspect --root benchmark/datasets/raw/BugLocator
    python -m benchmark.adapters.buglocator convert \
      --root benchmark/datasets/raw/BugLocator \
      --output benchmark/datasets/cache/buglocator.jsonl \
      --source-root-map benchmark/datasets/source_root_maps/buglocator.json
"""
from __future__ import annotations

import argparse
from pathlib import Path

from benchmark.adapters.local_ir_common import convert_directory, discover_files, download_file, extract_zip, load_source_root_map

DEFAULT_ROOT = Path("benchmark/datasets/raw/BugLocator")
DEFAULT_ARCHIVE = Path("benchmark/datasets/raw/buglocator_archive.zip")
DEFAULT_OUTPUT = Path("benchmark/datasets/cache/buglocator.jsonl")


def cmd_fetch(args: argparse.Namespace) -> None:
    if not args.url:
        raise SystemExit("Provide --url with a direct downloadable archive URL, or download manually and use `extract`.")
    archive = download_file(args.url, Path(args.archive))
    extract_zip(archive, Path(args.root))


def cmd_extract(args: argparse.Namespace) -> None:
    extract_zip(Path(args.archive), Path(args.root))


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
        dataset="buglocator",
        source_root_map=source_root_map,
        max_records=args.limit,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch/extract/convert BugLocator-style dataset to mcp-brain JSONL")
    sub = parser.add_subparsers(required=True)

    p_fetch = sub.add_parser("fetch")
    p_fetch.add_argument("--url", default=None, help="Direct downloadable archive URL")
    p_fetch.add_argument("--archive", default=str(DEFAULT_ARCHIVE))
    p_fetch.add_argument("--root", default=str(DEFAULT_ROOT))
    p_fetch.set_defaults(func=cmd_fetch)

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--archive", required=True)
    p_extract.add_argument("--root", default=str(DEFAULT_ROOT))
    p_extract.set_defaults(func=cmd_extract)

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
