"""Issue -> file localization features.

Pure-Python (no NumPy) so the core install keeps working. The benchmark lab
and the product share this module, so measured numbers are shipped numbers.

Pipeline
--------
1. ``analyze_source`` turns one file into a ``FileDoc`` (code terms, defined
   symbols, imports). Callers cache it by content hash.
2. ``RepoIndex`` aggregates FileDocs: BM25 postings, definition index
   (symbol -> defining files), dotted-module map, import graph.
3. ``issue_signals`` extracts evidence from issue text: identifiers,
   traceback frames, dotted modules, literal paths, code-snippet imports.
4. ``candidate_features`` scores every candidate file on independent
   channels and returns one feature dict per file. A learned linear model
   (``score``) fuses them.
"""
from __future__ import annotations

import ast
import math
import posixpath
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
CAMEL_RE = re.compile(r'(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])')
DOTTED_RE = re.compile(r'\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b')
PATH_RE = re.compile(
    r'[\w./\\-]+\.(?:pyi?|jsx?|mjs|cjs|tsx?|go|rs|java|cs)\b', re.I
)
TB_FRAME_RE = re.compile(r'File "([^"]+\.py)", line (\d+), in (\w+)')
PYTEST_FRAME_RE = re.compile(r'^([\w./\\-]+\.py):(\d+):', re.M)
GENERIC_FRAME_RE = re.compile(
    r'([\w./\\-]+\.(?:pyi?|jsx?|mjs|cjs|tsx?|go|rs|java|cs)):(\d+)(?::\d+)?', re.I
)
IMPORT_RE = re.compile(
    r'^\s*(?:>>>\s*)?(?:from\s+([\w.]+)\s+import\s+([\w, ()*]+)|import\s+([\w., ]+))',
    re.M,
)
TEST_PATH_RE = re.compile(
    r'(^|/)(tests?|testing|__tests__)/|(^|/)test_[^/]*$|_tests?\.py$|(^|/)conftest\.py$'
    r'|_test\.go$|\.(test|spec)\.[cm]?[jt]sx?$|\.tests?/'  # Go, JS/TS, C# test-project conventions
)
# Build output and vendored copies: never the file to fix, but they duplicate its text.
GENERATED_PATH_RE = re.compile(r'(^|/)(dist|build|vendor|vendored|third_party|node_modules)/|\.min\.[cm]?js$|\.bundle\.js$')

STOPWORDS = frozenset('''
a an and are as at be been but by can could do does for from has have how i if
in into is it its itself me my no not of on or our out so than that the their
them then there these they this to too up us was we were what when where which
while who will with would you your self cls none true false return def class
import pass else elif try except raise finally lambda yield assert del global
print should also just like get set new use used using work works way want
issue bug fix error problem expected actual result results case example following
'''.split())

# Generic filenames that match many issue words but are rarely the answer on
# their own; the learner decides how much this matters.
NON_PACKAGE_DIRS = frozenset({'doc', 'docs', 'example', 'examples', 'benchmarks', 'asv_bench', 'tutorials', 'galleries', 'scripts', 'bin', 'tools', 'ci', 'extern'})
DOC_VERSION = 3  # bump when FileDoc fields/extraction change (invalidates cached docs)
MIN_LITERAL = 12
MAX_LITERALS = 200

GENERIC_STEMS = frozenset({'__init__', 'base', 'utils', 'util', 'core', 'common', 'compat', 'helpers', 'misc', 'constants', 'types'})
SOURCE_SUFFIXES = (
    '.py', '.pyi', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx',
    '.go', '.rs', '.java', '.cs',
)


def split_identifier(token: str) -> list[str]:
    parts: list[str] = []
    for chunk in token.split('_'):
        if chunk:
            parts.extend(p.lower() for p in CAMEL_RE.split(chunk) if p)
    return parts


def code_terms(text: str) -> Counter:
    """Full identifiers plus their snake/camel sub-tokens, lower-cased."""
    terms: Counter = Counter()
    for tok in IDENT_RE.findall(text):
        low = tok.lower()
        subs = split_identifier(tok)
        if len(subs) > 1 and len(low) >= 3:
            terms[low] += 1
        for sub in subs:
            if len(sub) >= 2 and sub not in STOPWORDS and not sub.isdigit():
                terms[sub] += 1
    return terms


def is_test_path(path: str) -> bool:
    return bool(TEST_PATH_RE.search(path.replace('\\', '/').lower()))


def path_module(path: str) -> str:
    """Convert a source path to a language-neutral dotted module name."""
    p = path.replace('\\', '/')
    leaf = p.rsplit('/', 1)[-1]
    if '.' in leaf:
        p = p[: -(len(leaf) - leaf.rfind('.'))]
    if p.endswith(('/__init__', '/index')):
        p = p.rsplit('/', 1)[0]
    return p.replace('/', '.')


# ------------------------------------------------------------------
# Per-file analysis
# ------------------------------------------------------------------
@dataclass
class FileDoc:
    path: str
    terms: Counter
    length: int
    defs: dict  # symbol (lower) -> kind: 'class' | 'func' | 'method'
    qualified: frozenset  # 'class.method' lower
    imports: tuple  # absolute or relative dotted modules, as written
    n_lines: int = 0
    strings: frozenset = frozenset()  # distinctive string literals (lower), e.g. error messages


_FORMAT_HOLE_RE = re.compile(r'%[-#0 +]*\d*(?:\.\d+)?[sdrfi]|\{[^{}]*\}')


def _add_literal(strings: set, value: str) -> None:
    """Keep the longest constant fragment of messages like 'Unknown %s (%r) value'."""
    if len(strings) >= MAX_LITERALS or not MIN_LITERAL <= len(value) <= 300 or '\n' in value.strip():
        return
    frag = max(_FORMAT_HOLE_RE.split(value), key=len).strip().lower()
    if len(frag) >= MIN_LITERAL and ' ' in frag:
        strings.add(frag)


def _ast_defs(tree: ast.AST) -> tuple[dict, set, list, set]:
    defs: dict = {}
    qualified: set = set()
    imports: list = []
    strings: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            _add_literal(strings, node.value)
        elif isinstance(node, ast.ClassDef):
            defs[node.name.lower()] = 'class'
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defs.setdefault(child.name.lower(), 'method')
                    qualified.add(f'{node.name}.{child.name}'.lower())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.setdefault(node.name.lower(), 'func')
        elif isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            mod = '.' * node.level + (node.module or '')
            imports.append(mod)
            imports.extend(f'{mod}.{a.name}' if mod and not mod.endswith('.') else mod + a.name for a in node.names)
    return defs, qualified, imports, strings


_DEF_RE = re.compile(r'^\s*(class|def|async\s+def)\s+(\w+)', re.M)


def analyze_source(path: str, text: str) -> FileDoc:
    terms = code_terms(text)
    if path.lower().endswith(('.py', '.pyi')):
        try:
            defs, qualified, imports, strings = _ast_defs(ast.parse(text))
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            defs = {m.group(2).lower(): ('class' if m.group(1) == 'class' else 'func') for m in _DEF_RE.finditer(text)}
            qualified, imports, strings = set(), [], set()
    else:
        defs, qualified, imports, strings = _analyze_generic_source(path, text)
    return FileDoc(
        path=path,
        terms=terms,
        length=sum(terms.values()),
        defs=defs,
        qualified=frozenset(qualified),
        imports=tuple(imports),
        n_lines=text.count('\n') + 1,
        strings=frozenset(strings),
    )


_GENERIC_DEF_RE = re.compile(
    r'\b(class|interface|struct|enum|trait|type|function|func|fn)\s+([A-Za-z_$][\w$]*)'
)
_GENERIC_STRING_RE = re.compile(r'(["\'`])(.{12,300}?)\1')


def _analyze_generic_source(path: str, text: str) -> tuple[dict, set, list, set]:
    """Use the shared tree-sitter extractor, with a dependency-free fallback."""
    defs: dict = {}
    qualified: set = set()
    imports: list = []
    try:
        from src.brain.extractor import extract

        result = extract(path, text)
    except Exception:
        result = None
    if result:
        for symbol in result.symbols:
            kind = symbol.kind
            normalized = 'class' if kind in {
                'class', 'interface', 'struct', 'enum', 'trait', 'type'
            } else 'method' if kind == 'method' else 'func'
            defs[symbol.name.lower()] = normalized
            if symbol.parent:
                qualified.add(f'{symbol.parent}.{symbol.name}'.lower())
        imports = [item.module for item in result.imports if item.module]
    if not defs:
        for kind, name in _GENERIC_DEF_RE.findall(text):
            defs[name.lower()] = 'class' if kind in {
                'class', 'interface', 'struct', 'enum', 'trait', 'type'
            } else 'func'
    strings: set = set()
    for _quote, value in _GENERIC_STRING_RE.findall(text):
        _add_literal(strings, value)
    return defs, qualified, imports, strings


# ------------------------------------------------------------------
# Repository index
# ------------------------------------------------------------------
BM25_K1 = 1.2
BM25_B = 0.75


class RepoIndex:
    def __init__(self, docs: dict):
        self.docs: dict = docs  # path -> FileDoc
        self.n = max(len(docs), 1)
        self.postings: dict = defaultdict(list)
        self.def_index: dict = defaultdict(set)
        self.qual_index: dict = defaultdict(set)
        self.module_map: dict = {}
        self.literal_index: dict = defaultdict(set)
        total = 0
        for path, doc in docs.items():
            total += doc.length
            for term, tf in doc.terms.items():
                self.postings[term].append((path, tf))
            for sym in doc.defs:
                self.def_index[sym].add(path)
            for q in doc.qualified:
                self.qual_index[q].add(path)
            for lit in doc.strings:
                self.literal_index[lit].add(path)
            self.module_map[path_module(path)] = path
        self.avgdl = total / self.n or 1.0
        self.path_terms = {p: set(code_terms(path_module(p).replace('.', ' '))) for p in docs}
        self.api_postings: dict = defaultdict(set)
        for path, doc in docs.items():
            for term in code_terms(' '.join(doc.defs)):
                self.api_postings[term].add(path)
        self._build_import_graph()

    def idf(self, df: int) -> float:
        return math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))

    def resolve_module(self, dotted: str) -> str | None:
        """Longest prefix of a dotted name that maps to a file ('a.b.C.meth' -> a/b.py)."""
        parts = dotted.split('.')
        for end in range(len(parts), 0, -1):
            hit = self.module_map.get('.'.join(parts[:end]))
            if hit:
                return hit
        return None

    def resolve_suffix_module(self, dotted: str) -> str | None:
        """Like resolve_module but tolerant to a missing top-level package prefix."""
        hit = self.resolve_module(dotted)
        if hit:
            return hit
        for mod, path in self.module_map.items():
            if mod.endswith('.' + dotted):
                return path
        return None

    def _build_import_graph(self) -> None:
        self.imports_of: dict = defaultdict(set)
        self.imported_by: dict = defaultdict(set)
        for path, doc in self.docs.items():
            pkg = path_module(path).split('.')
            if not path.endswith('__init__.py'):
                pkg = pkg[:-1]
            for mod in doc.imports:
                if mod.startswith(('./', '../')):
                    relative = posixpath.normpath(posixpath.join(posixpath.dirname(path), mod))
                    target = self.resolve_module(path_module(relative))
                    if target and target != path:
                        self.imports_of[path].add(target)
                        self.imported_by[target].add(path)
                    continue
                if mod.startswith('.'):
                    level = len(mod) - len(mod.lstrip('.'))
                    base = pkg[: len(pkg) - level + 1] if level > 1 else pkg
                    mod = '.'.join(base + [m for m in mod.lstrip('.').split('.') if m])
                target = self.resolve_module(mod)
                if target and target != path:
                    self.imports_of[path].add(target)
                    self.imported_by[target].add(path)


# ------------------------------------------------------------------
# Issue signals
# ------------------------------------------------------------------
@dataclass
class IssueSignals:
    terms: Counter
    identifiers: Counter  # raw identifiers, lower
    dotted: list
    paths: list
    frames: list  # (path, func) in traceback order (outermost first)
    imports: list  # dotted modules named in snippet imports
    title_terms: frozenset = field(default_factory=frozenset)
    text_lower: str = ''  # whitespace-normalised, for verbatim literal matching


def issue_signals(title: str, body: str) -> IssueSignals:
    text = f'{title}\n{body}'
    frames = [(p.replace('\\', '/'), fn) for p, _line, fn in TB_FRAME_RE.findall(text)]
    frames += [(p.replace('\\', '/'), '') for p, _line in PYTEST_FRAME_RE.findall(text)]
    frames += [
        (p.replace('\\', '/'), '')
        for p, _line in GENERIC_FRAME_RE.findall(text)
        if p.replace('\\', '/') not in {known for known, _fn in frames}
    ]
    imports: list = []
    for m in IMPORT_RE.finditer(text):
        if m.group(1):
            imports.append(m.group(1))
            for name in re.split(r'[,\s()]+', m.group(2)):
                if name and name != '*':
                    imports.append(f'{m.group(1)}.{name}')
        elif m.group(3):
            imports.extend(x.strip().split(' ')[0] for x in m.group(3).split(',') if x.strip())
    return IssueSignals(
        terms=code_terms(text),
        identifiers=Counter(t.lower() for t in IDENT_RE.findall(text) if len(t) >= 3),
        dotted=DOTTED_RE.findall(text),
        paths=[p.replace('\\', '/').lstrip('./') for p in PATH_RE.findall(text)],
        frames=frames,
        imports=imports,
        title_terms=frozenset(code_terms(title)),
        text_lower=' '.join(text.lower().split()),
    )


# ------------------------------------------------------------------
# Channel scores -> features
# ------------------------------------------------------------------
def _bm25(index: RepoIndex, sig: IssueSignals, title_only: bool = False) -> dict:
    scores: dict = defaultdict(float)
    for term, qtf in sig.terms.items():
        if title_only and term not in sig.title_terms:
            continue
        plist = index.postings.get(term)
        if not plist:
            continue
        w = index.idf(len(plist)) * (1.0 + math.log(qtf)) * (1.5 if term in sig.title_terms else 1.0)
        for path, tf in plist:
            dl = index.docs[path].length
            scores[path] += w * tf * (BM25_K1 + 1) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * dl / index.avgdl))
    return scores


def _path_bm25(index: RepoIndex, sig: IssueSignals) -> dict:
    """Issue terms that appear in the file's module path, idf-weighted over paths."""
    df = Counter(t for terms in index.path_terms.values() for t in terms)
    out: dict = {}
    for path, terms in index.path_terms.items():
        s = sum(math.log(1 + index.n / df[t]) * (1 + math.log(sig.terms[t])) for t in terms if t in sig.terms)
        if s:
            out[path] = s
    return out


def _api_bm25(index: RepoIndex, sig: IssueSignals) -> dict:
    """Issue terms among the sub-tokens of names the file defines (its API surface)."""
    out: dict = defaultdict(float)
    for term, qtf in sig.terms.items():
        paths = index.api_postings.get(term)
        if paths and len(paths) < index.n / 2:
            w = index.idf(len(paths)) * (1.0 + math.log(qtf))
            for p in paths:
                out[p] += w / math.sqrt(1 + len(index.docs[p].defs) / 20)
    return out


def _suffix_match(index: RepoIndex, raw: str) -> str | None:
    raw = raw.replace('\\', '/')
    parts = raw.split('/')
    for start in range(len(parts)):
        cand = '/'.join(parts[start:])
        if cand in index.docs:
            return cand
    return None


def candidate_features(index: RepoIndex, sig: IssueSignals, exclude_tests: bool = True) -> dict:
    feats: dict = defaultdict(lambda: defaultdict(float))

    for name, channel in (
        ('bm25', _bm25(index, sig)),
        ('bm25_title', _bm25(index, sig, title_only=True)),
        ('api', _api_bm25(index, sig)),
        ('path_bm25', _path_bm25(index, sig)),
    ):
        _add_channel(feats, name, channel)

    # Definitions: the issue names a symbol and this file defines it.
    defs: dict = defaultdict(float)
    defs_class: dict = defaultdict(float)
    for ident, cnt in sig.identifiers.items():
        paths = index.def_index.get(ident)
        if not paths or len(paths) > 30:
            continue
        w = math.log(1 + index.n / len(paths)) * (1 + math.log(cnt))
        for p in paths:
            defs[p] += w
            if index.docs[p].defs.get(ident) == 'class':
                defs_class[p] += w
    _add_channel(feats, 'defs', defs)
    _add_channel(feats, 'defs_class', defs_class)

    qual: dict = defaultdict(float)
    for d in sig.dotted:
        parts = d.lower().split('.')
        for i in range(len(parts) - 1):
            for p in index.qual_index.get(f'{parts[i]}.{parts[i + 1]}', ()):
                qual[p] += 1.0
    _add_channel(feats, 'qualified', qual)

    # Dotted modules / snippet imports resolved to files.
    mod: dict = defaultdict(float)
    for d in list(sig.dotted) + list(sig.imports):
        hit = index.resolve_suffix_module(d)
        if hit:
            mod[hit] += 1.0
    _add_channel(feats, 'module', mod)

    literal: dict = defaultdict(float)
    for raw in sig.paths:
        hit = _suffix_match(index, raw)
        if hit:
            literal[hit] += 1.0
    _add_channel(feats, 'literal_path', literal)

    # Traceback: innermost repo frames are the strongest evidence.
    tb: dict = defaultdict(float)
    frames = [(hit, fn) for raw, fn in sig.frames if (hit := _suffix_match(index, raw))]
    for depth, (hit, _fn) in enumerate(reversed(frames)):
        tb[hit] = max(tb[hit], 1.0 / (1 + depth))
    _add_channel(feats, 'traceback', tb)

    # Verbatim string literals (error messages, warnings) quoted in the issue.
    lit: dict = defaultdict(float)
    for literal, paths in index.literal_index.items():
        if len(paths) <= 10 and literal in sig.text_lower:
            w = math.log(1 + index.n / len(paths)) * min(len(literal), 80) / 40
            for p in paths:
                lit[p] += w
    _add_channel(feats, 'literal', lit)

    # Structural propagation: evidence from files one import hop away.
    base = {p: f.get('defs', 0.0) + f.get('module', 0.0) + f.get('traceback', 0.0) + f.get('bm25_n', 0.0) for p, f in feats.items()}
    nb: dict = defaultdict(float)
    for p, s in base.items():
        if s <= 0:
            continue
        for q in index.imports_of.get(p, ()):
            nb[q] = max(nb[q], s)
        for q in index.imported_by.get(p, ()):
            nb[q] = max(nb[q], 0.5 * s)
    _add_channel(feats, 'neighbor', nb, create=False)

    out = {}
    for path, f in feats.items():
        if exclude_tests and is_test_path(path):
            continue
        if GENERATED_PATH_RE.search(path.lower()):
            continue
        doc = index.docs[path]
        filename = path.rsplit('/', 1)[-1]
        stem = filename.rsplit('.', 1)[0]
        f['is_init'] = float(stem in {'__init__', 'index'})
        f['is_generic'] = float(stem in GENERIC_STEMS)
        f['non_package'] = float('/' not in path or path.split('/', 1)[0].lower() in NON_PACKAGE_DIRS)
        f['depth'] = float(path.count('/'))
        f['log_lines'] = math.log1p(doc.n_lines)
        f['stem_in_issue'] = float(stem.lower() in sig.terms or stem.lower() in sig.identifiers)
        out[path] = dict(f)
    return out


def _add_channel(feats: dict, name: str, channel: dict, create: bool = True) -> None:
    """Per channel: raw value normalised by query max, and reciprocal rank."""
    if not channel:
        return
    peak = max(channel.values()) or 1.0
    ranked = sorted(channel.items(), key=lambda kv: (-kv[1], kv[0]))  # path tie-break: deterministic
    for rank, (path, value) in enumerate(ranked, start=1):
        if value <= 0:
            break
        if not create and path not in feats:
            if rank > 200:
                continue
        f = feats[path]
        f[f'{name}_n'] = value / peak
        f[f'{name}_rr'] = 1.0 / rank


# ------------------------------------------------------------------
# Learned fusion
# ------------------------------------------------------------------
def score(features: dict, weights: dict) -> float:
    return sum(weights.get(k, 0.0) * v for k, v in features.items()) + weights.get('__bias__', 0.0)


def rank(features_by_path: dict, weights: dict, top_k: int = 10) -> list:
    scored = sorted(((score(f, weights), p) for p, f in features_by_path.items()), reverse=True)
    return [(p, s) for s, p in scored[:top_k]]


# ------------------------------------------------------------------
# History and tree-ensemble fusion (shared by lab and product)
# ------------------------------------------------------------------
FIX_RE = re.compile(r'\b(fix|fixed|fixes|bug|regression|refs?\s+#|closes?\s+#)', re.I)
HISTORY_DEPTH = 3000
RECENT_COMMITS = 300
MAX_CANDIDATES = 300


def history_features(log_text: str) -> dict:
    """Parse ``git log --name-only --format=%x01%s`` into per-path counters."""
    touches, recent, fixes = Counter(), Counter(), Counter()
    age = -1
    is_fix = False
    for line in log_text.splitlines():
        if line.startswith('\x01'):
            age += 1
            is_fix = bool(FIX_RE.search(line))
            continue
        line = line.strip()
        if not line.lower().endswith(SOURCE_SUFFIXES):
            continue
        touches[line] += 1
        if age < RECENT_COMMITS:
            recent[line] += 1
        if is_fix:
            fixes[line] += 1
    return {'touches': touches, 'recent': recent, 'fixes': fixes}


def add_history(feats: dict, hist: dict) -> None:
    for path, f in feats.items():
        f['hist_touch'] = math.log1p(hist['touches'][path])
        f['hist_recent'] = math.log1p(hist['recent'][path])
        f['hist_fix'] = math.log1p(hist['fixes'][path])


def candidate_pool(feats: dict, n: int = MAX_CANDIDATES) -> list:
    """Top-n files by their best reciprocal rank on any channel."""
    best = {p: max((v for k, v in f.items() if k.endswith('_rr')), default=0.0) for p, f in feats.items()}
    return sorted(best, key=lambda p: (-best[p], p))[:n]


def reading_plan(scores: list, calibration: dict) -> dict:
    """Calibrated read-first plan from the top-1/top-2 score margin.

    ``calibration['tiers']`` is sorted by descending ``min_margin`` (last tier 0.0);
    each tier carries the smallest prefix size whose held-out hit rate met the target.
    """
    margin = scores[0] - scores[1] if len(scores) > 1 else math.inf
    tier = next(t for t in calibration['tiers'] if margin >= t['min_margin'])
    return {
        'confidence': tier['label'],
        'read_first': min(tier['read_first'], len(scores)),
        'expected_hit': tier['expected_hit'],
        'margin': round(margin, 4) if margin != math.inf else None,
    }


def plan_calibration(model: dict, top_path: str, local: dict | None = None) -> dict:
    """Repository self-calibration wins; else Python tiers for Python, pooled non-Python tiers otherwise."""
    if local:
        return local
    if top_path.lower().endswith(('.py', '.pyi')):
        return model['calibration']
    return model.get('calibration_other', model['calibration'])


def calibrate_tiers(queries: list, target: float = 0.85, cap: int = 10,
                    shares: tuple = (0.3, 0.7), labels: tuple = ('high', 'medium', 'low')) -> list:
    """Margin tiers from held-out queries ``(margin, gold_rank | None)`` (rank 1-based).

    Tier cut-offs sit at the given cumulative shares of queries sorted by margin;
    ``read_first`` is the smallest k <= cap with empirical hit@k >= target (else cap).
    """
    ordered = sorted(queries, key=lambda q: -q[0])
    bounds = [0, *(round(len(ordered) * s) for s in shares), len(ordered)]
    tiers = []
    for label, lo, hi in zip(labels, bounds, bounds[1:]):
        group = ordered[lo:hi]
        hit = {k: sum(r is not None and r <= k for _m, r in group) / len(group) for k in range(1, cap + 1)}
        k = next((k for k in hit if hit[k] >= target), cap)
        tiers.append({
            'label': label,
            'min_margin': round(group[-1][0], 4) if hi < len(ordered) else 0.0,
            'read_first': k,
            'expected_hit': round(hit[k], 3),
            'hit@1': round(hit[1], 3),
            'n': len(group),
        })
    return tiers


def tree_score(model: dict, features: dict) -> float:
    """Sum of exported LambdaMART trees; nodes are [feature, threshold, left, right]."""
    x = [features.get(name, 0.0) for name in model['features']]
    total = 0.0
    for node in model['trees']:
        while isinstance(node, list):
            node = node[2] if x[node[0]] <= node[1] else node[3]
        total += node
    return total
