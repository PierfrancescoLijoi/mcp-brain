"""
Parser multi-linguaggio basato su tree-sitter.

Design principles:
  - LAZY LOADING: i parser vengono importati solo quando servono davvero
  - GRACEFUL FALLBACK: se il pacchetto tree-sitter-X non è installato,
    il linguaggio viene ignorato invece di crashare tutto il sistema
  - CACHE: un Parser per linguaggio, riutilizzato tra chiamate
  - EXTENSIBLE: aggiungere un linguaggio = aggiungere una entry in LANGUAGE_REGISTRY
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Callable


# -------------------- Registry --------------------

def _load_python():
    import tree_sitter_python
    return tree_sitter_python.language()


def _load_javascript():
    import tree_sitter_javascript
    return tree_sitter_javascript.language()


def _load_typescript():
    import tree_sitter_typescript
    return tree_sitter_typescript.language_typescript()


def _load_tsx():
    import tree_sitter_typescript
    return tree_sitter_typescript.language_tsx()


def _load_go():
    import tree_sitter_go
    return tree_sitter_go.language()


def _load_rust():
    import tree_sitter_rust
    return tree_sitter_rust.language()


def _load_java():
    import tree_sitter_java
    return tree_sitter_java.language()


def _load_csharp():
    import tree_sitter_c_sharp
    return tree_sitter_c_sharp.language()


# Mapping linguaggio → (estensioni, loader, nodi di interesse)
# I nodi di interesse sono i tipi AST usati per estrarre simboli
# (function/class/method declarations). Ogni grammatica tree-sitter
# ha nomi leggermente diversi — questo mapping li normalizza.
LANGUAGE_REGISTRY: Dict[str, Dict] = {
    'python': {
        'extensions': {'.py', '.pyi'},
        'loader': _load_python,
        'symbol_nodes': {
            'function_definition',
            'class_definition',
            'decorated_definition',
        },
        'import_nodes': {'import_statement', 'import_from_statement'},
        'call_nodes': {'call'},
    },
    'javascript': {
        'extensions': {'.js', '.jsx', '.mjs', '.cjs'},
        'loader': _load_javascript,
        'symbol_nodes': {
            'function_declaration',
            'function_expression',
            'arrow_function',
            'class_declaration',
            'method_definition',
        },
        'import_nodes': {'import_statement'},
        'call_nodes': {'call_expression'},
    },
    'typescript': {
        'extensions': {'.ts'},
        'loader': _load_typescript,
        'symbol_nodes': {
            'function_declaration',
            'class_declaration',
            'method_definition',
            'interface_declaration',
            'type_alias_declaration',
        },
        'import_nodes': {'import_statement'},
        'call_nodes': {'call_expression'},
    },
    'tsx': {
        'extensions': {'.tsx'},
        'loader': _load_tsx,
        'symbol_nodes': {
            'function_declaration',
            'class_declaration',
            'method_definition',
            'interface_declaration',
            'type_alias_declaration',
        },
        'import_nodes': {'import_statement'},
        'call_nodes': {'call_expression'},
    },
    'go': {
        'extensions': {'.go'},
        'loader': _load_go,
        'symbol_nodes': {
            'function_declaration',
            'method_declaration',
            'type_declaration',
        },
        'import_nodes': {'import_declaration'},
        'call_nodes': {'call_expression'},
    },
    'rust': {
        'extensions': {'.rs'},
        'loader': _load_rust,
        'symbol_nodes': {
            'function_item',
            'struct_item',
            'enum_item',
            'trait_item',
            'impl_item',
        },
        'import_nodes': {'use_declaration'},
        'call_nodes': {'call_expression', 'macro_invocation'},
    },
    'java': {
        'extensions': {'.java'},
        'loader': _load_java,
        'symbol_nodes': {
            'class_declaration',
            'method_declaration',
            'interface_declaration',
            'enum_declaration',
        },
        'import_nodes': {'import_declaration'},
        'call_nodes': {'method_invocation'},
    },
    'csharp': {
        'extensions': {'.cs'},
        'loader': _load_csharp,
        'symbol_nodes': {
            'class_declaration',
            'method_declaration',
            'interface_declaration',
            'struct_declaration',
            'record_declaration',
        },
        'import_nodes': {'using_directive'},
        'call_nodes': {'invocation_expression'},
    },
}


# -------------------- Cache --------------------

_parser_cache: Dict[str, object] = {}
_language_cache: Dict[str, object] = {}
_unavailable: set = set()  # linguaggi con pacchetto non installato


# -------------------- Public API --------------------

def detect_language(file_path: str | Path) -> Optional[str]:
    """Dedotto dall'estensione. Ritorna None per estensioni non mappate."""
    ext = Path(file_path).suffix.lower()
    for lang, spec in LANGUAGE_REGISTRY.items():
        if ext in spec['extensions']:
            return lang
    return None


def get_parser(language: str):
    """
    Ritorna un Parser tree-sitter per il linguaggio, cacheato.
    Ritorna None se il pacchetto del parser non è installato o il linguaggio
    non è nel registry. Non solleva mai — degrada silenziosamente.
    """
    if language in _unavailable:
        return None
    if language in _parser_cache:
        return _parser_cache[language]

    spec = LANGUAGE_REGISTRY.get(language)
    if spec is None:
        _unavailable.add(language)
        return None

    try:
        from tree_sitter import Language, Parser
        lang_obj = spec['loader']()
        language_wrapped = Language(lang_obj)
        parser = Parser(language_wrapped)
        _parser_cache[language] = parser
        _language_cache[language] = language_wrapped
        return parser
    except ImportError as e:
        # Pacchetto tree-sitter-X non installato
        _unavailable.add(language)
        return None
    except Exception:
        _unavailable.add(language)
        return None


def get_language_spec(language: str) -> Optional[Dict]:
    """Ritorna lo spec (symbol_nodes, import_nodes, ...) per un linguaggio."""
    return LANGUAGE_REGISTRY.get(language)


def parse_file(file_path: str | Path, content: bytes | str = None):
    """
    Parsa un file. Se content non è fornito, legge da disco.
    Ritorna il root node dell'AST, o None se linguaggio non supportato
    o errore I/O.
    """
    path = Path(file_path)
    language = detect_language(path)
    if language is None:
        return None

    parser = get_parser(language)
    if parser is None:
        return None

    if content is None:
        try:
            content = path.read_bytes()
        except Exception:
            return None
    elif isinstance(content, str):
        content = content.encode('utf-8', errors='ignore')

    try:
        tree = parser.parse(content)
        return tree.root_node
    except Exception:
        return None


def supported_languages() -> list:
    """Lista linguaggi configurati nel registry (anche non installati)."""
    return list(LANGUAGE_REGISTRY.keys())


def available_languages() -> list:
    """Lista linguaggi con parser effettivamente caricabile (installati)."""
    available = []
    for lang in LANGUAGE_REGISTRY:
        if get_parser(lang) is not None:
            available.append(lang)
    return available


def supported_extensions() -> set:
    """Set di tutte le estensioni supportate."""
    exts = set()
    for spec in LANGUAGE_REGISTRY.values():
        exts.update(spec['extensions'])
    return exts


# -------------------- AST walking utilities --------------------

def walk(node, types: set = None):
    """
    Generator che visita tutti i nodi dell'AST (DFS).
    Se types è fornito, yielda solo i nodi di quei tipi.
    """
    stack = [node]
    while stack:
        current = stack.pop()
        if types is None or current.type in types:
            yield current
        stack.extend(current.children)


def node_text(node, source: bytes) -> str:
    """Estrae il testo sorgente di un nodo (utf-8 safe)."""
    try:
        return source[node.start_byte:node.end_byte].decode('utf-8', errors='ignore')
    except Exception:
        return ''


def find_identifier_child(node, source: bytes) -> str:
    """
    Cerca il primo child di tipo 'identifier' o 'type_identifier' in un nodo.
    Usato per estrarre il nome di una function/class/method in modo generico.
    """
    for child in node.children:
        if child.type in ('identifier', 'type_identifier', 'property_identifier', 'field_identifier', 'name'):
            return node_text(child, source)
    return ''
