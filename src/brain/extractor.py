"""
Extractor unificato multi-linguaggio.

Dato un file sorgente, produce una rappresentazione canonica (FileExtraction)
con symbols, imports e calls indipendente dal linguaggio.

Design:
  - Dispatcher per linguaggio via EXTRACTORS registry
  - Python/JS/TS hanno extractor specializzati (qualità alta)
  - Go/Rust/Java/C# usano extractor generico (qualità ~70-80%)
  - Mai solleva eccezioni: ritorna strutture vuote o None in caso di errore
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List, Dict, Callable

from src.brain.parsers import (
    parse_file,
    detect_language,
    get_language_spec,
    walk,
    node_text,
    find_identifier_child,
)


# -------------------- Dataclass canoniche --------------------

@dataclass
class Symbol:
    name: str
    kind: str                      # function | class | method | interface | struct | enum | trait | type
    line_start: int
    line_end: int
    parent: Optional[str] = None   # classe/modulo che contiene, se applicabile
    is_public: bool = True


@dataclass
class Import:
    module: str                    # modulo/path importato
    names: List[str] = field(default_factory=list)  # simboli specifici importati
    raw: str = ''                  # testo sorgente per debug


@dataclass
class Call:
    name: str                      # nome simbolo chiamato (es "encode" o "jwt.encode")
    line: int


@dataclass
class FileExtraction:
    path: str
    language: str
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[Import] = field(default_factory=list)
    calls: List[Call] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'path': self.path,
            'language': self.language,
            'symbols': [asdict(s) for s in self.symbols],
            'imports': [asdict(i) for i in self.imports],
            'calls': [asdict(c) for c in self.calls],
        }


# -------------------- Utility --------------------

def _node_lines(node) -> tuple:
    """Ritorna (start_line, end_line) 1-indexed."""
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _find_ancestor(node, ancestor_types: set, source: bytes) -> Optional[str]:
    """Risale gli ancestors, ritorna il nome del primo ancestor di tipo `ancestor_types`."""
    parent = node.parent
    while parent is not None:
        if parent.type in ancestor_types:
            name = find_identifier_child(parent, source)
            return name or None
        parent = parent.parent
    return None


def _text_utf8(node, source: bytes, maxlen: int = 200) -> str:
    return node_text(node, source).replace('\n', ' ')[:maxlen]


# =================================================================
# PYTHON EXTRACTORS (specialized)
# =================================================================

_PY_CLASS_TYPES = {'class_definition'}
_PY_FUNCTION_TYPES = {'function_definition', 'async_function_definition'}


def _extract_python_symbols(root, source: bytes) -> List[Symbol]:
    symbols = []
    for node in walk(root, _PY_CLASS_TYPES | _PY_FUNCTION_TYPES):
        name = find_identifier_child(node, source)
        if not name:
            continue
        ls, le = _node_lines(node)
        parent = _find_ancestor(node, _PY_CLASS_TYPES, source)
        if node.type in _PY_CLASS_TYPES:
            kind = 'class'
            parent_for_this = parent  # nested class: parent è la classe esterna
        else:
            kind = 'method' if parent else 'function'
            parent_for_this = parent
        is_public = not name.startswith('_')
        symbols.append(Symbol(
            name=name, kind=kind,
            line_start=ls, line_end=le,
            parent=parent_for_this,
            is_public=is_public,
        ))
    return symbols


def _extract_python_imports(root, source: bytes) -> List[Import]:
    imports = []
    # `import foo` / `import foo as f` / `import foo.bar`
    for node in walk(root, {'import_statement'}):
        raw = _text_utf8(node, source)
        # child 'dotted_name' o 'aliased_import'
        for child in node.children:
            if child.type == 'dotted_name':
                imports.append(Import(module=node_text(child, source), names=[], raw=raw))
            elif child.type == 'aliased_import':
                mod = child.child_by_field_name('name')
                if mod:
                    imports.append(Import(module=node_text(mod, source), names=[], raw=raw))
    # `from foo.bar import baz, qux`
    # Struttura tree-sitter-python: [from, dotted_name(=module), import, dotted_name, ..., dotted_name]
    # Il modulo è il PRIMO dotted_name prima della keyword 'import'.
    for node in walk(root, {'import_from_statement'}):
        raw = _text_utf8(node, source)
        module = ''
        names = []
        seen_import_kw = False
        for child in node.children:
            if child.type == 'import':
                seen_import_kw = True
                continue
            if child.type in ('from', ','):
                continue
            if child.type == 'dotted_name':
                text = node_text(child, source)
                if not seen_import_kw:
                    module = text
                else:
                    names.append(text)
            elif child.type == 'aliased_import':
                name = child.child_by_field_name('name')
                if name and seen_import_kw:
                    names.append(node_text(name, source))
            elif child.type == 'relative_import' and not seen_import_kw:
                # from . import X / from .foo import X
                module = node_text(child, source)
            elif child.type == 'wildcard_import':
                names.append('*')
        imports.append(Import(module=module, names=names, raw=raw))
    return imports


def _extract_python_calls(root, source: bytes) -> List[Call]:
    calls = []
    for node in walk(root, {'call'}):
        func = node.child_by_field_name('function')
        if func is None:
            continue
        line = node.start_point[0] + 1
        if func.type == 'identifier':
            calls.append(Call(name=node_text(func, source), line=line))
        elif func.type == 'attribute':
            # es. jwt.encode(...) → vogliamo "jwt.encode"
            calls.append(Call(name=node_text(func, source), line=line))
        # altri tipi (chiamate a expression complesse) skippati
    return calls


# =================================================================
# JAVASCRIPT / TYPESCRIPT EXTRACTORS (specialized)
# =================================================================

_JS_CLASS_TYPES = {'class_declaration'}
_JS_FUNC_TYPES = {'function_declaration', 'method_definition', 'arrow_function', 'function_expression'}


def _extract_js_symbols(root, source: bytes, is_ts: bool = False) -> List[Symbol]:
    symbols = []
    # 1. class_declaration e method_definition
    for node in walk(root, _JS_CLASS_TYPES | {'method_definition'}):
        name = find_identifier_child(node, source)
        if not name:
            continue
        ls, le = _node_lines(node)
        if node.type in _JS_CLASS_TYPES:
            symbols.append(Symbol(
                name=name, kind='class',
                line_start=ls, line_end=le,
                parent=_find_ancestor(node, _JS_CLASS_TYPES, source),
                is_public=_js_is_exported(node, source),
            ))
        else:
            parent = _find_ancestor(node, _JS_CLASS_TYPES, source)
            # private se inizia con # (ES2022) o _ per convenzione
            is_pub = not (name.startswith('#') or name.startswith('_'))
            symbols.append(Symbol(
                name=name, kind='method',
                line_start=ls, line_end=le,
                parent=parent,
                is_public=is_pub,
            ))

    # 2. function_declaration standalone
    for node in walk(root, {'function_declaration'}):
        name = find_identifier_child(node, source)
        if not name:
            continue
        ls, le = _node_lines(node)
        symbols.append(Symbol(
            name=name, kind='function',
            line_start=ls, line_end=le,
            parent=None,
            is_public=_js_is_exported(node, source),
        ))

    # 3. const/let/var = arrow_function | function_expression
    for node in walk(root, {'lexical_declaration', 'variable_declaration'}):
        for vardecl in node.children:
            if vardecl.type != 'variable_declarator':
                continue
            name_node = vardecl.child_by_field_name('name')
            value_node = vardecl.child_by_field_name('value')
            if name_node is None or value_node is None:
                continue
            if value_node.type not in {'arrow_function', 'function_expression'}:
                continue
            name = node_text(name_node, source)
            ls, le = _node_lines(vardecl)
            symbols.append(Symbol(
                name=name, kind='function',
                line_start=ls, line_end=le,
                parent=None,
                is_public=_js_is_exported(node, source),
            ))

    # 4. TypeScript: interface, type_alias
    if is_ts:
        for node in walk(root, {'interface_declaration'}):
            name = find_identifier_child(node, source)
            if not name:
                continue
            ls, le = _node_lines(node)
            symbols.append(Symbol(
                name=name, kind='interface',
                line_start=ls, line_end=le,
                parent=None,
                is_public=_js_is_exported(node, source),
            ))
        for node in walk(root, {'type_alias_declaration'}):
            name = find_identifier_child(node, source)
            if not name:
                continue
            ls, le = _node_lines(node)
            symbols.append(Symbol(
                name=name, kind='type',
                line_start=ls, line_end=le,
                parent=None,
                is_public=_js_is_exported(node, source),
            ))
    return symbols


def _js_is_exported(node, source: bytes) -> bool:
    """Un nodo è esportato se è dentro un export_statement."""
    p = node.parent
    while p is not None:
        if p.type == 'export_statement':
            return True
        p = p.parent
    return False


def _extract_js_imports(root, source: bytes) -> List[Import]:
    imports = []
    for node in walk(root, {'import_statement'}):
        raw = _text_utf8(node, source)
        source_node = node.child_by_field_name('source')
        module = node_text(source_node, source).strip('\'"') if source_node else ''
        names = []
        # import { a, b } from '...'
        for clause in walk(node, {'import_clause'}):
            for spec in walk(clause, {'import_specifier', 'namespace_import', 'identifier'}):
                n = find_identifier_child(spec, source) or node_text(spec, source)
                if n and n not in names:
                    names.append(n)
        imports.append(Import(module=module, names=names, raw=raw))
    return imports


def _extract_js_calls(root, source: bytes) -> List[Call]:
    calls = []
    for node in walk(root, {'call_expression'}):
        func = node.child_by_field_name('function')
        if func is None:
            continue
        line = node.start_point[0] + 1
        if func.type == 'identifier':
            calls.append(Call(name=node_text(func, source), line=line))
        elif func.type == 'member_expression':
            calls.append(Call(name=node_text(func, source), line=line))
    return calls


# =================================================================
# GENERIC EXTRACTOR (Go, Rust, Java, C#)
# =================================================================

def _extract_generic_symbols(root, source: bytes, spec: Dict, lang: str) -> List[Symbol]:
    """Extractor minimalista che usa solo i symbol_nodes del registry."""
    symbols = []
    symbol_types = spec['symbol_nodes']
    class_like_types = {
        'class_declaration', 'struct_declaration', 'struct_item',
        'interface_declaration', 'enum_declaration', 'trait_item',
        'impl_item', 'record_declaration', 'type_declaration',
    }
    for node in walk(root, symbol_types):
        name = find_identifier_child(node, source)
        if not name:
            continue
        ls, le = _node_lines(node)
        parent = _find_ancestor(node, class_like_types & symbol_types, source)
        kind = _normalize_generic_kind(node.type)
        is_public = _generic_is_public(name, node, source, lang)
        symbols.append(Symbol(
            name=name, kind=kind,
            line_start=ls, line_end=le,
            parent=parent,
            is_public=is_public,
        ))
    return symbols


def _normalize_generic_kind(node_type: str) -> str:
    """Mappa i tipi di nodo tree-sitter a kind canonici."""
    mapping = {
        'function_declaration': 'function',
        'function_item': 'function',
        'method_declaration': 'method',
        'class_declaration': 'class',
        'interface_declaration': 'interface',
        'struct_declaration': 'struct',
        'struct_item': 'struct',
        'enum_declaration': 'enum',
        'enum_item': 'enum',
        'trait_item': 'trait',
        'impl_item': 'impl',
        'type_alias_declaration': 'type',
        'type_declaration': 'type',
        'record_declaration': 'class',
    }
    return mapping.get(node_type, 'symbol')


def _generic_is_public(name: str, node, source: bytes, lang: str) -> bool:
    """Euristica visibility per linguaggi generic."""
    if lang == 'go':
        # Go: prima lettera maiuscola → esportato
        return bool(name) and name[0].isupper()
    if lang == 'rust':
        # Rust: cerca "pub " nel testo del nodo (approssimazione)
        text = node_text(node, source)
        return text.lstrip().startswith('pub ')
    if lang in ('java', 'csharp'):
        # Java/C#: cerca modifier "public" nei primi children
        for child in node.children:
            if child.type in ('modifiers', 'modifier'):
                if 'public' in node_text(child, source):
                    return True
        # se manca modifiers, assume package-private/internal
        return False
    return True


def _extract_generic_imports(root, source: bytes, spec: Dict) -> List[Import]:
    """Import extractor generico: prende il raw text, module best-effort."""
    imports = []
    for node in walk(root, spec['import_nodes']):
        raw = _text_utf8(node, source)
        # Cerca il primo string_literal o identifier dopo la keyword
        module = ''
        for child in walk(node, {'interpreted_string_literal', 'raw_string_literal',
                                 'string_literal', 'scoped_identifier', 'identifier'}):
            module = node_text(child, source).strip('\'"`')
            break
        imports.append(Import(module=module, names=[], raw=raw))
    return imports


def _extract_generic_calls(root, source: bytes, spec: Dict) -> List[Call]:
    calls = []
    for node in walk(root, spec.get('call_nodes', set())):
        line = node.start_point[0] + 1
        # Il primo child è di solito il nome/expression chiamato
        for child in node.children:
            if child.type in ('identifier', 'field_access', 'member_expression',
                              'selector_expression', 'scoped_identifier',
                              'simple_name', 'field_expression'):
                calls.append(Call(name=node_text(child, source), line=line))
                break
    return calls


# =================================================================
# DISPATCHER
# =================================================================

def extract(file_path, content: bytes | str = None) -> Optional[FileExtraction]:
    """
    Estrae {symbols, imports, calls} da un file sorgente.
    Ritorna None se il linguaggio non è supportato o il parsing fallisce.
    Non solleva mai: errori a valle ritornano liste vuote.
    """
    path = Path(file_path)
    language = detect_language(path)
    if language is None:
        return None

    spec = get_language_spec(language)
    if spec is None:
        return None

    if content is None:
        try:
            content = path.read_bytes()
        except Exception:
            return None
    if isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')

    root = parse_file(path, content)
    if root is None:
        return None

    result = FileExtraction(path=str(path), language=language)

    try:
        if language == 'python':
            result.symbols = _extract_python_symbols(root, content)
            result.imports = _extract_python_imports(root, content)
            result.calls = _extract_python_calls(root, content)
        elif language in ('javascript', 'typescript', 'tsx'):
            is_ts = language in ('typescript', 'tsx')
            result.symbols = _extract_js_symbols(root, content, is_ts=is_ts)
            result.imports = _extract_js_imports(root, content)
            result.calls = _extract_js_calls(root, content)
        else:
            result.symbols = _extract_generic_symbols(root, content, spec, language)
            result.imports = _extract_generic_imports(root, content, spec)
            result.calls = _extract_generic_calls(root, content, spec)
    except Exception:
        # Non propagare, ma segnala con liste vuote
        pass

    return result
