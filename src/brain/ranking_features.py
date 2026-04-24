"""Explainable ranking features for ticket -> file prediction.

This module is intentionally dependency-free. It extracts strong signals from
issue text (paths, dotted modules, symbols, exceptions and test names) and turns
those signals into deterministic boosts/penalties used by file_predictor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Sequence, Tuple

from src.brain.file_indexer import CODE_EXTENSIONS

# Keep this list local so the scorer can also reason about generic filenames.
GENERIC_FILE_STEMS = {
    "__init__",
    "base",
    "core",
    "common",
    "compat",
    "helpers",
    "helper",
    "misc",
    "utils",
    "utility",
    "config",
    "settings",
    "constants",
    "types",
    "models",
}

PATH_SUFFIX_PATTERN = "|".join(re.escape(ext.lstrip(".")) for ext in sorted(CODE_EXTENSIONS))

FILE_PATH_RE = re.compile(
    rf"(?<![A-Za-z0-9_])([A-Za-z0-9_./\\-]+\.(?:{PATH_SUFFIX_PATTERN}))(?![A-Za-z0-9_])"
)

DOTTED_MODULE_RE = re.compile(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*){1,}\b")
EXCEPTION_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]*(?:Error|Exception|Warning)\b")
IDENTIFIER_RE = re.compile(r"\b[a-zA-Z_]\w{2,}\b")
QUOTED_RE = re.compile(r"[`'\"]([^`'\"]{3,120})[`'\"]")

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "have",
    "will",
    "should",
    "would",
    "could",
    "been",
    "when",
    "where",
    "which",
    "while",
    "about",
    "into",
    "onto",
    "issue",
    "ticket",
    "please",
    "need",
    "needs",
    "want",
    "wants",
    "make",
    "makes",
    "using",
    "use",
    "uses",
    "add",
    "adds",
    "fix",
    "fixes",
    "fixed",
    "bug",
    "bugs",
    "update",
    "updates",
    "feature",
    "features",
    "error",
    "fails",
    "failed",
    "failure",
    "test",
    "tests",
}
LOW_SIGNAL_TERMS = {
    "model",
    "models",
    "file",
    "files",
    "test",
    "tests",
    "core",
    "utils",
    "base",
    "common",
    "helper",
    "helpers",
    "config",
    "settings",
    "index",
    "main",
    "app",
    "apps",
    "type",
    "types",
}

@dataclass(frozen=True)
class QueryFeatures:
    """Structured signals extracted from a ticket/problem statement."""

    weighted_terms: Dict[str, float] = field(default_factory=dict)
    file_paths: Tuple[str, ...] = ()
    dotted_modules: Tuple[str, ...] = ()
    symbols: Tuple[str, ...] = ()
    exceptions: Tuple[str, ...] = ()
    test_source_candidates: Tuple[str, ...] = ()


def _norm_path(value: str) -> str:
    return value.strip().replace("\\", "/").strip("./")


def _path_without_suffix(path: str) -> str:
    """Remove only the final file extension while preserving forward slashes.

    Important: pathlib.Path behaves differently with slash-separated paths on
    Windows, so using string logic here keeps this deterministic across OSes.
    """
    p = _norm_path(path)
    last_slash = p.rfind("/")
    last_dot = p.rfind(".")
    if last_dot > last_slash:
        return p[:last_dot]
    return p


def _path_stem(path: str) -> str:
    p = _norm_path(path)
    filename = p.rsplit("/", 1)[-1]
    if "." in filename:
        return filename.rsplit(".", 1)[0]
    return filename


def _path_suffix(path: str) -> str:
    p = _norm_path(path)
    filename = p.rsplit("/", 1)[-1]
    if "." in filename:
        return "." + filename.rsplit(".", 1)[1]
    return ""


def _split_identifier(value: str) -> List[str]:
    """Split snake/camel/dotted/path-like strings into lower-case code tokens."""
    value = value.replace("\\", "/")
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    raw_parts = re.split(r"[^A-Za-z0-9_]+|_+", value)

    out: List[str] = []
    for part in raw_parts:
        p = part.lower()
        if len(p) < 3 or p in STOPWORDS:
            continue
        out.append(p)
    return out


def _add_weight(terms: Dict[str, float], term: str, weight: float) -> None:
    term = term.lower().strip()
    if len(term) < 3 or term in STOPWORDS:
        return

    # General-purpose downweighting: these terms are useful context, but too broad
    # to dominate ranking across real codebases.
    if term in LOW_SIGNAL_TERMS:
        weight *= 0.35

    terms[term] = terms.get(term, 0.0) + weight


def _unique_preserve_order(values: Sequence[str]) -> Tuple[str, ...]:
    seen = set()
    out: List[str] = []

    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)

    return tuple(out)


def _test_to_source_candidates(path: str) -> List[str]:
    """Map common test paths to likely source paths without requiring repo access."""
    p = _norm_path(path)
    parts = p.split("/")
    filename = parts[-1] if parts else p
    stem = _path_stem(filename)
    suffix = _path_suffix(filename) or ".py"

    candidates: List[str] = []

    source_stem = stem
    if source_stem.startswith("test_"):
        source_stem = source_stem[len("test_"):]
    if source_stem.endswith("_test"):
        source_stem = source_stem[: -len("_test")]

    # package/tests/test_x.py -> package/x.py
    if "tests" in parts:
        i = parts.index("tests")
        prefix = parts[:i]
        if source_stem:
            candidates.append("/".join(prefix + [source_stem + suffix]))

    # tests/test_x.py -> x.py, test_x.py -> x.py
    if source_stem and source_stem != stem:
        candidates.append(source_stem + suffix)

    return candidates


def extract_query_features(title: str, body: str = "") -> QueryFeatures:
    """Extract weighted lexical/path/code features from an issue."""
    text = f"{title or ''}\n{body or ''}"
    weighted: Dict[str, float] = {}

    # Baseline natural/code tokens.
    for token in _split_identifier(text):
        _add_weight(weighted, token, 1.0)

    file_paths = [_norm_path(m.group(1)) for m in FILE_PATH_RE.finditer(text)]

    dotted_modules: List[str] = []
    for m in DOTTED_MODULE_RE.finditer(text):
        value = m.group(0)

        # File paths like test_parser.py are handled as paths, not modules.
        if _path_suffix(value).lower() in CODE_EXTENSIONS:
            continue

        dotted_modules.append(value)

    exceptions = [m.group(0) for m in EXCEPTION_RE.finditer(text)]

    quoted_symbols: List[str] = []
    for quoted in QUOTED_RE.findall(text):
        # Quoted snippets are often function names, module fragments or messages.
        if len(quoted.split()) <= 4:
            quoted_symbols.extend(_split_identifier(quoted))

    identifiers = [m.group(0) for m in IDENTIFIER_RE.finditer(text)]
    symbols: List[str] = []

    for ident in identifiers:
        ident_l = ident.lower()

        if ident_l in STOPWORDS:
            continue

        if "_" in ident or ident[:1].isupper() or ident_l in quoted_symbols:
            symbols.append(ident_l)

    # Strong signals receive extra query weight.
    for path in file_paths:
        path_no_ext = _path_without_suffix(path)
        for token in _split_identifier(path_no_ext):
            _add_weight(weighted, token, 5.0)

    for module in dotted_modules:
        for token in _split_identifier(module):
            _add_weight(weighted, token, 4.0)

    for sym in symbols:
        _add_weight(weighted, sym.lower(), 3.0)
        for token in _split_identifier(sym):
            _add_weight(weighted, token, 2.0)

    for exc in exceptions:
        _add_weight(weighted, exc.lower(), 2.0)
        for token in _split_identifier(exc):
            _add_weight(weighted, token, 2.0)

    source_candidates: List[str] = []
    for path in file_paths:
        source_candidates.extend(_test_to_source_candidates(path))

    return QueryFeatures(
        weighted_terms=dict(sorted(weighted.items())),
        file_paths=_unique_preserve_order(file_paths),
        dotted_modules=_unique_preserve_order(dotted_modules),
        symbols=_unique_preserve_order(symbols),
        exceptions=_unique_preserve_order(exceptions),
        test_source_candidates=_unique_preserve_order(source_candidates),
    )


def _looks_like_test_path(path: str) -> bool:
    rel = _norm_path(path).lower()
    return bool(re.search(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_|_test\.", rel))


def score_path_features(file_path: str, features: QueryFeatures) -> Tuple[float, List[str]]:
    """Return an additive path/module/test mapping boost and human reasons."""
    rel = _norm_path(file_path).lower()
    rel_no_ext = _path_without_suffix(rel)
    stem = _path_stem(rel).lower()

    reasons: List[str] = []
    score = 0.0

    for mentioned in features.file_paths:
        m = _norm_path(mentioned).lower()
        m_no_ext = _path_without_suffix(m)

        if rel == m:
            # A directly mentioned test path is often the failing test, while the
            # source file is the likely modification target. Keep this signal,
            # but avoid letting it dominate test-to-source mapping.
            if _looks_like_test_path(rel):
                score += 4.0
                reasons.append(f"mentioned failing test path: {mentioned}")
            else:
                score += 15.0
                reasons.append(f"exact path mentioned: {mentioned}")

        elif rel.endswith(m) or m.endswith(rel):
            score += 10.0
            reasons.append(f"partial path match: {mentioned}")

        elif m_no_ext and (rel_no_ext.endswith(m_no_ext) or m_no_ext.endswith(rel_no_ext)):
            score += 8.0
            reasons.append(f"path stem match: {mentioned}")

    for module in features.dotted_modules:
        module_l = module.lower()
        module_path = module_l.replace(".", "/")

        if module_path and (module_path in rel_no_ext or rel_no_ext.endswith(module_path)):
            score += 12.0
            reasons.append(f"module path match: {module}")
        else:
            module_leaf = module_l.split(".")[-1]
            if module_leaf == stem:
                score += 5.0
                reasons.append(f"module leaf matches filename: {module_leaf}")

    for candidate in features.test_source_candidates:
        c = _norm_path(candidate).lower()
        c_no_ext = _path_without_suffix(c)

        if rel == c or rel.endswith(c) or (c_no_ext and rel_no_ext.endswith(c_no_ext)):
            score += 14.0
            reasons.append(f"test-to-source candidate: {candidate}")

    for sym in features.symbols:
        # Symbol names often mirror filenames/classes. Exact leaf filename matches
        # are strong across repositories, languages and frameworks.
        sym_l = sym.lower()
        sym_tokens = _split_identifier(sym_l)

        if sym_l == stem:
            score += 14.0
            reasons.append(f"exact symbol matches filename: {sym}")

        elif stem in sym_tokens:
            score += 7.0
            reasons.append(f"symbol token matches filename: {sym}")

    return score, reasons[:5]


def noise_penalty(file_path: str, matches: Dict[str, List[str]] | None = None) -> Tuple[float, List[str]]:
    """Return multiplicative penalty for broad/noisy files.

    Penalties are intentionally soft: generic files can still win if they have
    strong direct evidence.
    """
    rel = _norm_path(file_path).lower()
    stem = _path_stem(rel).lower()

    reasons: List[str] = []
    factor = 1.0
    matches = matches or {}

    has_strong_signal = bool(
        matches.get("path")
        or matches.get("filename")
        or matches.get("symbol")
    )

    if stem == "__init__" and not has_strong_signal:
        factor *= 0.50
        reasons.append("soft penalty: __init__ file")

    elif stem in GENERIC_FILE_STEMS and not has_strong_signal:
        factor *= 0.75
        reasons.append(f"soft penalty: generic filename {stem}.py")

    is_test = bool(re.search(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_|_test\.py$", rel))

    if is_test:
        # Failing tests are excellent clues, but the modification target is often
        # the adjacent source file. Keep this as a soft penalty so genuine test-only
        # bugs can still rank.
        if matches.get("path") and not matches.get("symbol"):
            factor *= 0.40
            reasons.append("stronger penalty: mentioned failing test without symbol match")
        elif matches.get("symbol"):
            factor *= 0.75
            reasons.append("soft penalty: test file with symbol signal")
        else:
            factor *= 0.55
            reasons.append("soft penalty: test file, prefer source candidate")

    return factor, reasons