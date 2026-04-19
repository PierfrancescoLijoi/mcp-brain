import ast
import re
from pathlib import Path


def extract_symbols_python(content: str) -> set:
    '''Estrae function names, class names, imports da Python AST.'''
    symbols = set()
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbols.add(node.name.lower())
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    symbols.add(alias.name.split('.')[0].lower())
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    symbols.add(node.module.split('.')[0].lower())
                for alias in node.names:
                    symbols.add(alias.name.lower())
    except Exception:
        pass
    return symbols


def extract_symbols_js_ts(content: str) -> set:
    '''Regex-based extraction per JS/TS. Non perfetto ma veloce.'''
    symbols = set()
    patterns = [
        r'function\s+([a-zA-Z_$][\w$]*)',
        r'class\s+([a-zA-Z_$][\w$]*)',
        r'const\s+([a-zA-Z_$][\w$]*)\s*=',
        r'let\s+([a-zA-Z_$][\w$]*)\s*=',
        r'export\s+(?:default\s+)?(?:function|class|const)\s+([a-zA-Z_$][\w$]*)',
        r'import\s+.*?from\s+[\'"]([^\'"]+)[\'"]',
    ]
    for pat in patterns:
        for m in re.finditer(pat, content):
            symbols.add(m.group(1).lower())
    return symbols


def extract_symbols(file_path: Path, content: str) -> set:
    '''Dispatcher per linguaggio.'''
    suffix = file_path.suffix.lower()
    if suffix == '.py':
        return extract_symbols_python(content)
    if suffix in ('.js', '.jsx', '.ts', '.tsx'):
        return extract_symbols_js_ts(content)
    return set()


def extract_identifiers(content: str) -> set:
    '''Fallback: parole significative dal codice.'''
    idents = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]{3,}', content)
    return set(i.lower() for i in idents)
