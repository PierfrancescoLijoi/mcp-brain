"""
Test dell'incremental update del code graph.
Casi critici:
  - file modificato: simboli cambiati
  - file nuovo: aggiunto al grafo
  - file cancellato: rimosso con pulizia reverse indexes
  - import switchato: da A a B — A perde imported_by, B lo guadagna
  - mantenimento idempotenza: update e rebuild producono lo stesso grafo
"""
import pytest

from src.brain.code_graph import (
    build_graph,
    update_graph_incremental,
    get_impact_radius,
    get_imported_by,
    get_symbol_definitions,
)
from src.brain.parsers import get_parser


def _skip_if_no_parser(lang):
    if get_parser(lang) is None:
        pytest.skip(f'tree-sitter-{lang} not installed')


@pytest.fixture
def mini_repo(tmp_path):
    """Mini repo a 4 file: auth importa db, login_handler importa auth."""
    _skip_if_no_parser('python')
    (tmp_path / '__init__.py').write_text('')
    (tmp_path / 'db.py').write_text(
        'def get_user(u): return {"name": u}\n'
    )
    (tmp_path / 'auth.py').write_text(
        'from db import get_user\n'
        'def login(u):\n'
        '    return get_user(u)\n'
    )
    (tmp_path / 'login_handler.py').write_text(
        'from auth import login\n'
        'def handle(req): return login(req)\n'
    )
    return tmp_path


# -------------------- Incremental = Full Rebuild (idempotenza) --------------------

class TestIdempotence:
    def test_update_equals_full_rebuild(self, mini_repo):
        """Dopo una modifica, incremental update e full rebuild devono coincidere."""
        graph_full_1 = build_graph(mini_repo)

        # Modifico auth.py
        (mini_repo / 'auth.py').write_text(
            'from db import get_user\n'
            'def login(u):\n'
            '    return get_user(u)\n'
            'def logout(u):\n'
            '    pass\n'  # aggiunto logout
        )

        # Incremental update
        update_graph_incremental(graph_full_1, ['auth.py'], mini_repo)

        # Full rebuild for comparison
        graph_full_2 = build_graph(mini_repo)

        # Confronto strutture principali
        assert set(graph_full_1['files'].keys()) == set(graph_full_2['files'].keys())
        for path in graph_full_2['files']:
            a = graph_full_1['files'][path]
            b = graph_full_2['files'][path]
            assert set(a['symbols']) == set(b['symbols']), f'symbols differ in {path}'
            assert sorted(a['imported_by']) == sorted(b['imported_by']), (
                f'imported_by differ in {path}: '
                f'incremental={a["imported_by"]} full={b["imported_by"]}'
            )


# -------------------- File modificato --------------------

class TestFileModified:
    def test_symbols_updated(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'logout' not in graph['files']['auth.py']['symbols']

        (mini_repo / 'auth.py').write_text(
            'from db import get_user\n'
            'def login(u): return get_user(u)\n'
            'def logout(u): pass\n'
        )
        update_graph_incremental(graph, ['auth.py'], mini_repo)

        assert 'logout' in graph['files']['auth.py']['symbols']

    def test_new_symbol_appears_in_symbol_index(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'logout' not in graph['symbol_index']

        (mini_repo / 'auth.py').write_text(
            'def login(u): pass\n'
            'def logout(u): pass\n'
        )
        update_graph_incremental(graph, ['auth.py'], mini_repo)

        assert 'auth.py' in graph['symbol_index']['logout']

    def test_removed_symbol_disappears_from_index(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'login' in graph['symbol_index']

        # Sostituisco login con qualcos'altro
        (mini_repo / 'auth.py').write_text('def authenticate(u): pass\n')
        update_graph_incremental(graph, ['auth.py'], mini_repo)

        # login non è più definito da auth.py
        assert 'auth.py' not in graph['symbol_index'].get('login', [])


# -------------------- Import switchato --------------------

class TestImportSwitch:
    def test_imported_by_moves_from_old_to_new(self, mini_repo):
        """
        Se auth.py cambia import da db.py a newdb.py,
        - db.py deve perdere auth.py dai suoi imported_by
        - newdb.py deve guadagnarlo
        """
        graph = build_graph(mini_repo)
        assert 'auth.py' in graph['files']['db.py']['imported_by']

        (mini_repo / 'newdb.py').write_text('def get_user(u): return u\n')
        (mini_repo / 'auth.py').write_text(
            'from newdb import get_user\n'  # switched
            'def login(u): return get_user(u)\n'
        )
        update_graph_incremental(graph, ['auth.py', 'newdb.py'], mini_repo)

        # db.py non deve più avere auth.py come importer
        assert 'auth.py' not in graph['files']['db.py']['imported_by']
        # newdb.py deve averlo
        assert 'auth.py' in graph['files']['newdb.py']['imported_by']

    def test_called_by_moves_correctly(self, mini_repo):
        graph = build_graph(mini_repo)
        db_callers = [cb['file'] for cb in graph['files']['db.py']['called_by']]
        assert 'auth.py' in db_callers

        # auth.py non chiama più get_user
        (mini_repo / 'auth.py').write_text(
            'def login(u): return u\n'
        )
        update_graph_incremental(graph, ['auth.py'], mini_repo)

        db_callers = [cb['file'] for cb in graph['files']['db.py']['called_by']]
        assert 'auth.py' not in db_callers


# -------------------- File cancellato --------------------

class TestFileDeleted:
    def test_file_removed_from_graph(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'login_handler.py' in graph['files']

        (mini_repo / 'login_handler.py').unlink()
        update_graph_incremental(graph, ['login_handler.py'], mini_repo)

        assert 'login_handler.py' not in graph['files']

    def test_deleted_file_removed_from_reverse_indexes(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'login_handler.py' in graph['files']['auth.py']['imported_by']

        (mini_repo / 'login_handler.py').unlink()
        update_graph_incremental(graph, ['login_handler.py'], mini_repo)

        # auth.py non deve più vedere login_handler come importer
        assert 'login_handler.py' not in graph['files']['auth.py']['imported_by']

    def test_deleted_file_removed_from_symbol_index(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'handle' in graph['symbol_index']

        (mini_repo / 'login_handler.py').unlink()
        update_graph_incremental(graph, ['login_handler.py'], mini_repo)

        assert 'handle' not in graph['symbol_index']


# -------------------- File nuovo --------------------

class TestFileAdded:
    def test_new_file_added_to_graph(self, mini_repo):
        graph = build_graph(mini_repo)
        assert 'logout_handler.py' not in graph['files']

        (mini_repo / 'logout_handler.py').write_text(
            'from auth import login\n'
            'def handle_logout(r): return login(r)\n'
        )
        update_graph_incremental(graph, ['logout_handler.py'], mini_repo)

        assert 'logout_handler.py' in graph['files']

    def test_new_file_establishes_reverse_links(self, mini_repo):
        graph = build_graph(mini_repo)

        (mini_repo / 'logout_handler.py').write_text(
            'from auth import login\n'
            'def handle_logout(r): return login(r)\n'
        )
        update_graph_incremental(graph, ['logout_handler.py'], mini_repo)

        # auth.py deve avere logout_handler.py nei suoi imported_by
        assert 'logout_handler.py' in graph['files']['auth.py']['imported_by']


# -------------------- Edge cases --------------------

class TestEdgeCases:
    def test_empty_changed_files_is_noop(self, mini_repo):
        graph = build_graph(mini_repo)
        snapshot = {k: dict(v) for k, v in graph['files'].items()}
        update_graph_incremental(graph, [], mini_repo)
        # Grafo invariato (eccetto stats)
        for k in snapshot:
            assert snapshot[k]['symbols'] == graph['files'][k]['symbols']

    def test_ignores_files_in_excluded_dirs(self, mini_repo):
        graph = build_graph(mini_repo)
        files_before = len(graph['files'])

        # Finto update su file in node_modules
        update_graph_incremental(graph, ['node_modules/x.py'], mini_repo)

        # Nessun cambio
        assert len(graph['files']) == files_before

    def test_ignores_unsupported_extensions(self, mini_repo):
        graph = build_graph(mini_repo)
        files_before = len(graph['files'])
        update_graph_incremental(graph, ['README.md', 'config.yaml'], mini_repo)
        assert len(graph['files']) == files_before

    def test_stats_last_incremental_recorded(self, mini_repo):
        graph = build_graph(mini_repo)
        (mini_repo / 'auth.py').write_text('def login(u): pass\n')
        update_graph_incremental(graph, ['auth.py'], mini_repo)

        last = graph['stats']['last_incremental']
        assert last['updated'] == 1
        assert last['removed'] == 0

    def test_performance_faster_than_full_rebuild(self, mini_repo):
        """
        Sanity check: incremental su 1 file deve essere molto più veloce
        del full rebuild del repo. Non è una benchmark rigorosa, solo
        conferma dell'ordine di grandezza.
        """
        import time
        graph = build_graph(mini_repo)

        # Aggiungo N file per simulare un repo più grande
        for i in range(20):
            (mini_repo / f'extra_{i}.py').write_text(f'def f_{i}(): pass\n')
        graph = build_graph(mini_repo)  # rebuild con 20+ file

        # Ora modifico un solo file
        (mini_repo / 'auth.py').write_text('def login(u): return u\n')

        t_full_start = time.perf_counter()
        build_graph(mini_repo)
        t_full = time.perf_counter() - t_full_start

        t_inc_start = time.perf_counter()
        update_graph_incremental(graph, ['auth.py'], mini_repo)
        t_inc = time.perf_counter() - t_inc_start

        # Incremental dovrebbe essere almeno 2x più veloce su un mini-repo di 20+ file
        # (il margine aumenta con la dimensione del repo)
        assert t_inc < t_full, f'incremental={t_inc*1000:.1f}ms, full={t_full*1000:.1f}ms'
