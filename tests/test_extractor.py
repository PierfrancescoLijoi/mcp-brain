"""Test dell'extractor unificato multi-linguaggio."""
import pytest

from src.brain.extractor import extract, Symbol, Import, Call, FileExtraction
from src.brain.parsers import get_parser


def _skip_if_no_parser(lang):
    if get_parser(lang) is None:
        pytest.skip(f'tree-sitter-{lang} not installed')


# -------------------- Python --------------------

class TestPythonExtractor:
    def setup_method(self):
        _skip_if_no_parser('python')

    def test_extracts_function(self, tmp_path):
        code = b'def login(user):\n    return jwt.encode(user)\n'
        f = tmp_path / 'x.py'
        f.write_bytes(code)
        r = extract(f)
        assert r.language == 'python'
        funcs = [s for s in r.symbols if s.kind == 'function']
        assert len(funcs) == 1
        assert funcs[0].name == 'login'
        assert funcs[0].line_start == 1
        assert funcs[0].is_public is True
        assert funcs[0].parent is None

    def test_private_function_detected(self, tmp_path):
        code = b'def _internal():\n    pass\n'
        f = tmp_path / 'x.py'
        f.write_bytes(code)
        r = extract(f)
        assert r.symbols[0].is_public is False

    def test_method_has_parent(self, tmp_path):
        code = b'class Auth:\n    def login(self): pass\n    def _verify(self): pass\n'
        f = tmp_path / 'x.py'
        f.write_bytes(code)
        r = extract(f)
        methods = [s for s in r.symbols if s.kind == 'method']
        assert len(methods) == 2
        for m in methods:
            assert m.parent == 'Auth'
        # visibility
        login = next(m for m in methods if m.name == 'login')
        verify = next(m for m in methods if m.name == '_verify')
        assert login.is_public is True
        assert verify.is_public is False

    def test_import_statement(self, tmp_path):
        code = b'import jwt\nimport os.path\n'
        f = tmp_path / 'x.py'
        f.write_bytes(code)
        r = extract(f)
        modules = [i.module for i in r.imports]
        assert 'jwt' in modules
        assert 'os.path' in modules

    def test_from_import(self, tmp_path):
        code = b'from src.db.users import get_user, create_user\n'
        f = tmp_path / 'x.py'
        f.write_bytes(code)
        r = extract(f)
        assert len(r.imports) == 1
        imp = r.imports[0]
        assert imp.module == 'src.db.users'
        assert set(imp.names) == {'get_user', 'create_user'}

    def test_calls_extracted(self, tmp_path):
        code = b'def f():\n    get_user(1)\n    jwt.encode({})\n'
        f = tmp_path / 'x.py'
        f.write_bytes(code)
        r = extract(f)
        names = [c.name for c in r.calls]
        assert 'get_user' in names
        assert 'jwt.encode' in names


# -------------------- JavaScript --------------------

class TestJavascriptExtractor:
    def setup_method(self):
        _skip_if_no_parser('javascript')

    def test_export_function(self, tmp_path):
        code = b'export function login(u) { return jwt.sign(u); }\n'
        f = tmp_path / 'x.js'
        f.write_bytes(code)
        r = extract(f)
        funcs = [s for s in r.symbols if s.kind == 'function']
        assert len(funcs) == 1
        assert funcs[0].name == 'login'
        assert funcs[0].is_public is True

    def test_non_exported_function_is_private(self, tmp_path):
        code = b'function helper() {}\n'
        f = tmp_path / 'x.js'
        f.write_bytes(code)
        r = extract(f)
        assert r.symbols[0].is_public is False

    def test_class_and_methods(self, tmp_path):
        code = b'export class Auth {\n    login() {}\n    _verify() {}\n}\n'
        f = tmp_path / 'x.js'
        f.write_bytes(code)
        r = extract(f)
        classes = [s for s in r.symbols if s.kind == 'class']
        methods = [s for s in r.symbols if s.kind == 'method']
        assert len(classes) == 1
        assert classes[0].name == 'Auth'
        assert classes[0].is_public is True
        assert len(methods) == 2
        for m in methods:
            assert m.parent == 'Auth'

    def test_arrow_function_assigned(self, tmp_path):
        code = b'export const login = (u) => jwt.sign(u);\n'
        f = tmp_path / 'x.js'
        f.write_bytes(code)
        r = extract(f)
        funcs = [s for s in r.symbols if s.kind == 'function']
        names = [s.name for s in funcs]
        assert 'login' in names

    def test_import_named(self, tmp_path):
        code = b'import { a, b } from "./lib";\n'
        f = tmp_path / 'x.js'
        f.write_bytes(code)
        r = extract(f)
        assert len(r.imports) == 1
        imp = r.imports[0]
        assert imp.module == './lib'
        assert 'a' in imp.names and 'b' in imp.names


# -------------------- TypeScript --------------------

class TestTypescriptExtractor:
    def setup_method(self):
        _skip_if_no_parser('typescript')

    def test_interface(self, tmp_path):
        code = b'export interface User { id: number; name: string; }\n'
        f = tmp_path / 'x.ts'
        f.write_bytes(code)
        r = extract(f)
        ifaces = [s for s in r.symbols if s.kind == 'interface']
        assert len(ifaces) == 1
        assert ifaces[0].name == 'User'
        assert ifaces[0].is_public is True

    def test_type_alias(self, tmp_path):
        code = b'type UserId = number;\n'
        f = tmp_path / 'x.ts'
        f.write_bytes(code)
        r = extract(f)
        types = [s for s in r.symbols if s.kind == 'type']
        assert len(types) == 1
        assert types[0].name == 'UserId'


# -------------------- Go (generic extractor) --------------------

class TestGoExtractor:
    def setup_method(self):
        _skip_if_no_parser('go')

    def test_exported_function_uppercase(self, tmp_path):
        code = b'package auth\nfunc Login(u string) string { return u }\n'
        f = tmp_path / 'x.go'
        f.write_bytes(code)
        r = extract(f)
        funcs = [s for s in r.symbols if s.kind == 'function']
        assert any(s.name == 'Login' and s.is_public for s in funcs)

    def test_lowercase_function_unexported(self, tmp_path):
        code = b'package auth\nfunc login(u string) string { return u }\n'
        f = tmp_path / 'x.go'
        f.write_bytes(code)
        r = extract(f)
        funcs = [s for s in r.symbols if s.kind == 'function']
        assert funcs[0].is_public is False

    def test_method_with_receiver(self, tmp_path):
        code = b'package auth\ntype Auth struct{}\nfunc (a *Auth) Login() string { return "" }\n'
        f = tmp_path / 'x.go'
        f.write_bytes(code)
        r = extract(f)
        methods = [s for s in r.symbols if s.kind == 'method']
        assert any(m.name == 'Login' for m in methods)


# -------------------- Rust (generic) --------------------

class TestRustExtractor:
    def setup_method(self):
        _skip_if_no_parser('rust')

    def test_pub_function(self, tmp_path):
        code = b'pub fn login(u: &str) -> String { u.to_string() }\n'
        f = tmp_path / 'x.rs'
        f.write_bytes(code)
        r = extract(f)
        funcs = [s for s in r.symbols if s.kind == 'function']
        assert funcs[0].is_public is True

    def test_private_function(self, tmp_path):
        code = b'fn helper() {}\n'
        f = tmp_path / 'x.rs'
        f.write_bytes(code)
        r = extract(f)
        funcs = [s for s in r.symbols if s.kind == 'function']
        assert funcs[0].is_public is False


# -------------------- Robustezza --------------------

class TestRobustness:
    def test_unsupported_extension_returns_none(self, tmp_path):
        f = tmp_path / 'x.txt'
        f.write_text('hello')
        assert extract(f) is None

    def test_empty_file(self, tmp_path):
        _skip_if_no_parser('python')
        f = tmp_path / 'x.py'
        f.write_text('')
        r = extract(f)
        assert r is not None
        assert r.symbols == []
        assert r.imports == []
        assert r.calls == []

    def test_syntactically_broken_file_does_not_crash(self, tmp_path):
        """tree-sitter è error-tolerant: deve recuperare il possibile."""
        _skip_if_no_parser('python')
        f = tmp_path / 'x.py'
        f.write_text('def foo(\n    pass\n')  # rotto
        r = extract(f)
        assert r is not None  # non crasha

    def test_to_dict_serializable(self, tmp_path):
        """Verifica che la struttura sia JSON-serializzabile per lo storage."""
        _skip_if_no_parser('python')
        import json
        f = tmp_path / 'x.py'
        f.write_text('def f(): pass\nclass C: pass\n')
        r = extract(f)
        d = r.to_dict()
        # Deve serializzare senza errori
        serialized = json.dumps(d)
        assert 'symbols' in serialized
        parsed = json.loads(serialized)
        assert parsed['language'] == 'python'

    def test_content_override_instead_of_disk(self, tmp_path):
        _skip_if_no_parser('python')
        f = tmp_path / 'x.py'
        f.write_text('def on_disk(): pass\n')  # sul disco
        # Ma passo content diverso
        r = extract(f, content=b'def in_memory(): pass\n')
        names = [s.name for s in r.symbols]
        assert 'in_memory' in names
        assert 'on_disk' not in names
