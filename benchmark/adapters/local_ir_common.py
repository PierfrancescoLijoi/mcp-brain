"""Common helpers for legacy IR bug-localization datasets.

Bench4BL and BugLocator-style datasets are not SWE-bench-style GitHub issue
snapshots with a single `base_commit`. They usually provide bug-report text and
fixed source files, often with separate source snapshots.

These helpers normalize them to a JSONL format consumed by run_eval_static.py:

    {
      "instance_id": "...",
      "dataset": "bench4bl|buglocator",
      "project": "...",
      "language": "java",
      "source_root": "C:/path/to/source/snapshot",
      "problem_statement": "bug report text",
      "gold_files": ["src/.../Foo.java"],
      "metadata": {...}
    }
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence
from urllib.request import urlretrieve

CODE_FILE_RE = re.compile(r"[A-Za-z0-9_./\\$-]+\.(?:java|kt|scala|py|js|ts|c|cc|cpp|h|hpp)")
TEXT_KEYS = ("problem_statement", "description", "desc", "body", "report", "bug_report", "summary", "title")
ID_KEYS = ("instance_id", "bug_id", "bugid", "id", "issue_id", "report_id")
PROJECT_KEYS = ("project", "repo", "repository", "product", "component")
FILE_KEYS = ("gold_files", "fixed_files", "fix_files", "buggy_files", "files", "modified_files")


def run(cmd: Sequence[str], cwd: Path | None = None) -> None:
    print("$", " ".join(map(str, cmd)))
    subprocess.run(list(cmd), cwd=str(cwd) if cwd else None, check=True)


def ensure_git_clone(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        run(["git", "fetch", "--all", "--prune"], cwd=target)
    else:
        run(["git", "clone", url, str(target)])
    return target


def download_file(url: str, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        print(f"Already exists: {output}")
        return output
    print(f"Downloading {url} -> {output}")
    urlretrieve(url, output)
    return output


def extract_zip(archive: Path, target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    return target


def discover_files(root: Path, patterns: Sequence[str] = ("*.csv", "*.tsv", "*.json", "*.jsonl", "*.xml", "*.txt")) -> List[Path]:
    out: List[Path] = []
    for pat in patterns:
        out.extend(root.rglob(pat))
    return sorted(set(out))


def read_text_safe(path: Path, max_chars: int = 5_000_000) -> str:
    data = path.read_bytes()[:max_chars]
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def normalize_path(p: str) -> str:
    return p.strip().replace("\\", "/").strip("./")


def split_files(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = []
        for item in value:
            raw.extend(split_files(item))
        return raw
    text = str(value)
    found = CODE_FILE_RE.findall(text)
    if found:
        return sorted(set(normalize_path(x) for x in found))
    parts = re.split(r"[;,|\n\r\t ]+", text)
    return sorted(set(normalize_path(x) for x in parts if CODE_FILE_RE.search(x)))


def first_value(row: Mapping[str, Any], candidates: Iterable[str]) -> Any:
    lower_map = {str(k).lower().strip(): v for k, v in row.items()}
    for key in candidates:
        if key in lower_map and lower_map[key] not in (None, ""):
            return lower_map[key]
    return None


def infer_record(row: Mapping[str, Any], dataset: str, source_root_map: Mapping[str, str] | None = None) -> Dict[str, Any] | None:
    bug_id = first_value(row, ID_KEYS) or abs(hash(json.dumps(dict(row), sort_keys=True, default=str)))
    project = str(first_value(row, PROJECT_KEYS) or "unknown")

    text_parts: List[str] = []
    for key in TEXT_KEYS:
        val = first_value(row, (key,))
        if val:
            text_parts.append(str(val))
    if not text_parts:
        # Fallback: concatenate short textual columns.
        for val in row.values():
            if isinstance(val, str) and 5 <= len(val) <= 4000 and not CODE_FILE_RE.search(val):
                text_parts.append(val)
    problem = "\n".join(dict.fromkeys(text_parts)).strip()

    gold_files: List[str] = []
    for key in FILE_KEYS:
        val = first_value(row, (key,))
        gold_files.extend(split_files(val))
    if not gold_files:
        # Last-resort: scan full row for code paths.
        gold_files.extend(split_files(json.dumps(dict(row), ensure_ascii=False, default=str)))
    gold_files = sorted(set(gold_files))

    if not problem or not gold_files:
        return None

    source_root = None
    if source_root_map:
        source_root = source_root_map.get(project) or source_root_map.get(project.lower())

    return {
        "instance_id": f"{dataset}__{project}__{bug_id}",
        "dataset": dataset,
        "project": project,
        "repo": project,
        "language": "java",
        "source_root": source_root,
        "problem_statement": problem,
        "gold_files": gold_files,
        "metadata": {"raw": dict(row)},
    }


def iter_csv_records(path: Path) -> Iterator[Dict[str, Any]]:
    text = read_text_safe(path)
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(text.splitlines(), dialect=dialect)
    for row in reader:
        if row:
            yield dict(row)


def iter_json_records(path: Path) -> Iterator[Dict[str, Any]]:
    text = read_text_safe(path)
    if path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if line:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    yield obj
        return
    obj = json.loads(text)
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                yield item
    elif isinstance(obj, dict):
        # Either one record or a dict of records/lists.
        yielded = False
        for val in obj.values():
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        yielded = True
                        yield item
        if not yielded:
            yield obj


def iter_xml_records(path: Path) -> Iterator[Dict[str, Any]]:
    # Generic XML parser: looks for elements that contain both text-like fields and code paths.
    import xml.etree.ElementTree as ET

    root = ET.fromstring(read_text_safe(path))
    for elem in root.iter():
        children = list(elem)
        if len(children) < 2:
            continue
        row: Dict[str, Any] = {}
        for child in children:
            tag = child.tag.split("}")[-1].lower()
            val = " ".join((child.itertext())) if list(child) else (child.text or "")
            if val and val.strip():
                row[tag] = val.strip()
        if row and split_files(json.dumps(row)):
            yield row


def iter_candidate_records(path: Path) -> Iterator[Dict[str, Any]]:
    suffix = path.suffix.lower()
    try:
        if suffix in {".csv", ".tsv", ".txt"}:
            yield from iter_csv_records(path)
        elif suffix in {".json", ".jsonl"}:
            yield from iter_json_records(path)
        elif suffix == ".xml":
            yield from iter_xml_records(path)
    except Exception as exc:
        print(f"[warn] failed to parse {path}: {exc}")


def convert_directory(
    root: Path,
    output: Path,
    dataset: str,
    source_root_map: Mapping[str, str] | None = None,
    max_records: int | None = None,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    candidates = discover_files(root)
    records: List[Dict[str, Any]] = []
    seen_ids = set()

    for path in candidates:
        for raw in iter_candidate_records(path):
            rec = infer_record(raw, dataset=dataset, source_root_map=source_root_map)
            if not rec:
                continue
            rec["metadata"]["source_file"] = str(path)
            if rec["instance_id"] in seen_ids:
                continue
            seen_ids.add(rec["instance_id"])
            records.append(rec)
            if max_records is not None and len(records) >= max_records:
                break
        if max_records is not None and len(records) >= max_records:
            break

    with output.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "dataset": dataset,
        "root": str(root),
        "records": len(records),
        "candidate_files_scanned": len(candidates),
        "output": str(output),
        "note": "Inspect the JSONL before evaluation. Legacy dataset formats vary; provide --source-root-map for runnable static evaluation.",
    }
    output.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))
    return output


def load_source_root_map(path: str | None) -> Dict[str, str]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))
