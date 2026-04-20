"""Test del modulo parsers multi-linguaggio."""
import pytest

from src.brain.parsers import (
    detect_language,
    get_parser,
    parse_file,
    supported_languages,
    available_languages,
    supported_extensions,
    walk,
    node_text,
    find_identifier_child,
    get_language_spec,
)


class TestDetectLanguage:
    @pytest.mark.parametrize('filename, expected', [
        ('foo.py', 'python'),
        ('foo.pyi', 'python'),
        ('foo.js', 'javascript'),
        ('foo.jsx', 'javascript'),
        ('foo.mjs', 'javascript'),
        ('foo.ts', 'typescript'),
        ('foo.tsx', 'tsx'),
        ('foo.go', 'go'),
        ('foo.rs', 'rust'),
        ('foo.java', 'java'),
        ('foo.cs', 'csharp'),
        ('foo.txt', None),
        ('foo', None),
    ])
    def test_detection(self, filename, expected):
        assert detect_language(filename) == expected


class TestRegistryIntegrity:
    def test_supported_languages_not_empty(self):
        langs = supported_languages()
        assert 'python' in langs
        assert 'javascript' in langs
        assert 'typescript' in langs

    def test_all_languages_have_required_spec_fields(self):
        for lang in supported_languages():
            spec = get_language_spec(lang)
            assert 'extensions' in spec
            assert 'loader' in spec
            assert 'symbol_nodes' in spec
            assert isinstance(spec['extensions'], set)
            assert len(spec['extensions']) > 0

    def test_supported_extensions_includes_common_ones(self):
        exts = supported_extensions()
        for e in {'.py', '.js', '.ts', '.tsx', '.go', '.rs', '.java', '.cs'}:
            assert e in exts


class TestGetParser:
    def test_python_parser_loads(self):
        parser = get_parser('python')
        # Se tree-sitter-python non è installato, test skippato
        if parser is None:
            pytest.skip('tree-sitter-python not installed')
        assert parser is not None

    def test_unknown_language_returns_none(self):
        assert get_parser('cobol') is None

    def test_parser_is_cached(self):
        p1 = get_parser('python')
        p2 = get_parser('python')
        if p1 is None:
            pytest.skip('tree-sitter-python not installed')
        assert p1 is p2


class TestParseFile:
    def test_parse_python_source(self, tmp_path):
        if get_parser('python') is None:
            pytest.skip('tree-sitter-python not installed')
        code = b'def login(user):\n    return jwt.encode(user)\n\nclass Auth:\n    pass\n'
        root = parse_file(tmp_path / 'x.py', content=code)
        assert root is not None
        assert root.type == 'module'
        # Conta function_definition e class_definition nel tree
        functions = list(walk(root, {'function_definition'}))
        classes = list(walk(root, {'class_definition'}))
        assert len(functions) == 1
        assert len(classes) == 1

    def test_parse_file_reads_from_disk(self, tmp_path):
        if get_parser('python') is None:
            pytest.skip('tree-sitter-python not installed')
        f = tmp_path / 'x.py'
        f.write_text('def hello(): pass\n')
        root = parse_file(f)
        assert root is not None
        assert root.type == 'module'

    def test_unsupported_extension_returns_none(self, tmp_path):
        f = tmp_path / 'x.txt'
        f.write_text('hello')
        assert parse_file(f) is None

    def test_javascript_parse(self, tmp_path):
        if get_parser('javascript') is None:
            pytest.skip('tree-sitter-javascript not installed')
        code = b'function login(u) { return jwt.sign(u); }\nclass Auth {}\n'
        root = parse_file(tmp_path / 'x.js', content=code)
        assert root is not None
        funcs = list(walk(root, {'function_declaration'}))
        classes = list(walk(root, {'class_declaration'}))
        assert len(funcs) == 1
        assert len(classes) == 1


class TestWalkAndNodeText:
    def test_walk_visits_all_nodes(self, tmp_path):
        if get_parser('python') is None:
            pytest.skip('tree-sitter-python not installed')
        code = b'def a():\n    pass\ndef b():\n    pass\n'
        root = parse_file(tmp_path / 'x.py', content=code)
        names = []
        for node in walk(root, {'function_definition'}):
            names.append(find_identifier_child(node, code))
        assert set(names) == {'a', 'b'}

    def test_node_text_extracts_source(self, tmp_path):
        if get_parser('python') is None:
            pytest.skip('tree-sitter-python not installed')
        code = b'def hello():\n    pass\n'
        root = parse_file(tmp_path / 'x.py', content=code)
        func = next(walk(root, {'function_definition'}))
        text = node_text(func, code)
        assert 'def hello' in text


class TestAvailableLanguages:
    def test_returns_list(self):
        langs = available_languages()
        assert isinstance(langs, list)
        # Almeno python deve essere disponibile in ambiente dev
        # (negli ambienti CI senza parser, questa assertion va skippata)
        if not langs:
            pytest.skip('no tree-sitter parsers installed')
        assert all(isinstance(l, str) for l in langs)
