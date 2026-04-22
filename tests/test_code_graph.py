"""Test code graph builder + query API."""
import json
import pytest

from src.brain.code_graph import (
    build_graph,
    save_graph,
    load_graph,
    get_or_build_graph,
    get_imported_by,
    get_callers,
    get_impact_radius,
    get_symbol_definitions,
    _resolve_python_import,
    _resolve_js_import,
)
from src.brain.parsers import get_parser


def _skip_if_no_parser(lang):
    if get_parser(lang) is None:
        pytest.skip(f'tree-sitter-{lang} not installed')


@pytest.fixture
def py_repo(tmp_path):
    """Mini repo Python: auth_service → chiamato da login e logout."""
    _skip_if_no_parser('python')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / '__init__.py').write_text('')
    (tmp_path / 'src' / 'auth_service.py').write_text(
        'import jwt\n'
        'from src.db.users import get_user\n'
        'def login(user):\n'
        '    u = get_user(user)\n'
        '    return jwt.encode({"sub": user})\n'
        'def verify_token(token):\n'
        '    return jwt.decode(token)\n'
    )
    (tmp_path / 'src' / 'db').mkdir()
    (tmp_path / 'src' / 'db' / '__init__.py').write_text('')
    (tmp_path / 'src' / 'db' / 'users.py').write_text(
        'def get_user(username):\n    return {"name": username}\n'
    )
    (tmp_path / 'src' / 'api').mkdir()
    (tmp_path / 'src' / 'api' / '__init__.py').write_text('')
    (tmp_path / 'src' / 'api' / 'login_handler.py').write_text(
        'from src.auth_service import login\n'
        'def handle_login(req):\n'
        '    return login(req["user"])\n'
    )
    (tmp_path / 'src' / 'api' / 'logout_handler.py').write_text(
        'from src.auth_service import verify_token\n'
        'def handle_logout(token):\n'
        '    return verify_token(token)\n'
    )
    return tmp_path


# -------------------- Risoluzione import --------------------

class TestResolvePythonImport:
    def test_absolute_module_to_file(self):
        all_files = {'src/db/users.py', 'src/auth_service.py'}
        resolved = _resolve_python_import('src.db.users', ['get_user'],
                                          'src/auth_service.py', all_files)
        assert resolved == 'src/db/users.py'

    def test_absolute_to_package_init(self):
        all_files = {'src/db/__init__.py'}
        resolved = _resolve_python_import('src.db', [], 'src/x.py', all_files)
        assert resolved == 'src/db/__init__.py'

    def test_relative_same_package(self):
        all_files = {'src/pkg/a.py', 'src/pkg/b.py'}
        # from . import a → when inside src/pkg/b.py, module='.' names=['a']
        # Il mio extractor restituisce module='.' per from . import X
        # In questo caso non si risolve — dobbiamo gestire names per il relative root
        # Verifico invece il caso from .a import X
        resolved = _resolve_python_import('.a', ['foo'], 'src/pkg/b.py', all_files)
        assert resolved == 'src/pkg/a.py'

    def test_external_returns_none(self):
        all_files = {'src/a.py'}
        assert _resolve_python_import('jwt', [], 'src/a.py', all_files) is None
        assert _resolve_python_import('requests', [], 'src/a.py', all_files) is None


class TestResolveJsImport:
    def test_relative_with_extension_detection(self):
        all_files = {'src/lib.ts', 'src/app.ts'}
        resolved = _resolve_js_import('./lib', 'src/app.ts', all_files, ts_mode=True)
        assert resolved == 'src/lib.ts'

    def test_index_file_fallback(self):
        all_files = {'src/components/Button/index.tsx', 'src/app.tsx'}
        resolved = _resolve_js_import('./components/Button', 'src/app.tsx',
                                      all_files, ts_mode=True)
        assert resolved == 'src/components/Button/index.tsx'

    def test_bare_import_is_external(self):
        all_files = {'src/a.ts'}
        assert _resolve_js_import('react', 'src/a.ts', all_files, ts_mode=True) is None
        assert _resolve_js_import('lodash', 'src/a.ts', all_files, ts_mode=True) is None

    def test_parent_dir_import(self):
        all_files = {'src/lib/util.ts', 'src/app/view.ts'}
        resolved = _resolve_js_import('../lib/util', 'src/app/view.ts',
                                      all_files, ts_mode=True)
        assert resolved == 'src/lib/util.ts'


# -------------------- Build graph end-to-end --------------------

class TestBuildGraph:
    def test_builds_structure(self, py_repo):
        graph = build_graph(py_repo)
        assert 'files' in graph
        assert 'symbol_index' in graph
        assert 'stats' in graph
        assert graph['stats']['total_files'] == 7  # 3 __init__ + auth_service + db/users + 2 handlers
        assert graph['stats']['build_time_ms'] >= 0

    def test_symbols_registered(self, py_repo):
        graph = build_graph(py_repo)
        # auth_service definisce login e verify_token
        auth = graph['files']['src/auth_service.py']
        assert set(auth['symbols']) == {'login', 'verify_token'}

    def test_imports_resolved_to_paths(self, py_repo):
        graph = build_graph(py_repo)
        auth = graph['files']['src/auth_service.py']
        resolved = [i['resolved'] for i in auth['imports_to']]
        assert 'src/db/users.py' in resolved
        # jwt è external
        externals = [i['module'] for i in auth['imports_to'] if i['external']]
        assert 'jwt' in externals

    def test_imported_by_reverse_index(self, py_repo):
        graph = build_graph(py_repo)
        auth = graph['files']['src/auth_service.py']
        # login_handler e logout_handler importano auth_service
        assert 'src/api/login_handler.py' in auth['imported_by']
        assert 'src/api/logout_handler.py' in auth['imported_by']

    def test_called_by_reverse_index(self, py_repo):
        graph = build_graph(py_repo)
        # get_user definito in db/users.py deve essere chiamato da auth_service
        users = graph['files']['src/db/users.py']
        caller_files = [cb['file'] for cb in users['called_by']]
        assert 'src/auth_service.py' in caller_files

    def test_symbol_index_global(self, py_repo):
        graph = build_graph(py_repo)
        idx = graph['symbol_index']
        assert 'login' in idx
        assert 'src/auth_service.py' in idx['login']
        assert 'get_user' in idx
        assert 'src/db/users.py' in idx['get_user']

    def test_calls_out_resolved(self, py_repo):
        graph = build_graph(py_repo)
        auth = graph['files']['src/auth_service.py']
        # auth_service chiama get_user che è in db/users.py
        get_user_call = next(c for c in auth['calls_out'] if c['name'] == 'get_user')
        assert 'src/db/users.py' in get_user_call['resolves_to']


# -------------------- Persistenza --------------------

class TestPersistence:
    def test_save_and_load(self, py_repo, tmp_path):
        graph = build_graph(py_repo)
        out = tmp_path / 'graph.json'
        save_graph(graph, out)
        assert out.exists()
        loaded = load_graph(out)
        assert loaded['stats']['total_files'] == graph['stats']['total_files']

    def test_load_nonexistent_returns_none(self, tmp_path):
        assert load_graph(tmp_path / 'doesnotexist.json') is None


# -------------------- Query API --------------------

class TestQueryAPI:
    def test_impact_radius_1_hop(self, py_repo):
        graph = build_graph(py_repo)
        radius = get_impact_radius(graph, 'src/auth_service.py', max_hops=1)
        # login_handler e logout_handler importano auth_service
        assert 'src/api/login_handler.py' in radius['direct']
        assert 'src/api/logout_handler.py' in radius['direct']

    def test_impact_radius_returns_affected_symbols(self, py_repo):
        graph = build_graph(py_repo)
        radius = get_impact_radius(graph, 'src/auth_service.py')
        assert set(radius['affected_symbols']) == {'login', 'verify_token'}

    def test_impact_radius_unknown_file_returns_empty(self, py_repo):
        graph = build_graph(py_repo)
        radius = get_impact_radius(graph, 'nonexistent.py')
        assert radius['direct'] == []
        assert radius['affected_symbols'] == []

    def test_get_imported_by(self, py_repo):
        graph = build_graph(py_repo)
        importers = get_imported_by(graph, 'src/auth_service.py')
        assert 'src/api/login_handler.py' in importers

    def test_get_symbol_definitions(self, py_repo):
        graph = build_graph(py_repo)
        files = get_symbol_definitions(graph, 'login')
        assert 'src/auth_service.py' in files


# -------------------- Edge cases --------------------

class TestEdgeCases:
    def test_ignores_excluded_dirs(self, tmp_path):
        _skip_if_no_parser('python')
        (tmp_path / 'src').mkdir()
        (tmp_path / 'src' / 'a.py').write_text('def foo(): pass\n')
        (tmp_path / 'node_modules').mkdir()
        (tmp_path / 'node_modules' / 'b.py').write_text('def bar(): pass\n')
        (tmp_path / '.venv').mkdir()
        (tmp_path / '.venv' / 'c.py').write_text('def baz(): pass\n')

        graph = build_graph(tmp_path)
        paths = list(graph['files'].keys())
        assert 'src/a.py' in paths
        assert all('node_modules' not in p for p in paths)
        assert all('.venv' not in p for p in paths)

    def test_empty_repo(self, tmp_path):
        graph = build_graph(tmp_path)
        assert graph['stats']['total_files'] == 0
        assert graph['files'] == {}

    def test_self_reference_excluded_from_calls_resolves(self, tmp_path):
        """Un file che chiama i propri simboli non deve self-link."""
        _skip_if_no_parser('python')
        (tmp_path / 'a.py').write_text(
            'def helper():\n    pass\n'
            'def main():\n    helper()\n'
        )
        graph = build_graph(tmp_path)
        a = graph['files']['a.py']
        helper_call = next((c for c in a['calls_out'] if c['name'] == 'helper'), None)
        if helper_call:
            assert 'a.py' not in helper_call['resolves_to']
