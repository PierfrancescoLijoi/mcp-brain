"""
Test STEP 2.2 — Graph expansion del predictor.

Usiamo fake_index + fake_graph (entrambi iniettabili) per evitare di fare
parsing reale di codice. Il focus è la logica di merging e decadimento per hop.
"""
import pytest

from src.brain.file_indexer import _finalize_index, save_index
from src.brain.file_predictor import (
    predict_files_with_impact,
    predict_files_explained,
    HOP_DECAY,
)


# ----------------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------------
@pytest.fixture
def fake_index(tmp_brain):
    def _make(files_data):
        for _, d in files_data.items():
            d.setdefault('mtime', 0.0)
        idx = _finalize_index(files_data)
        save_index(idx)
        return idx
    return _make


def _make_graph(edges):
    """
    Costruisce un graph minimale compatibile con get_impact_radius.

    edges: dict {file: {'imported_by': [...], 'called_by': [{file, symbol}]}}
    """
    files = {}
    for f, e in edges.items():
        files[f] = {
            'language': 'python',
            'symbols': e.get('symbols', []),
            'imports_to': [],
            'imported_by': e.get('imported_by', []),
            'calls_out': [],
            'called_by': e.get('called_by', []),
            'mtime': 0.0,
        }
    # Eventuali file menzionati come importers ma non definiti come chiavi:
    # aggiungiamoli vuoti per non far crashare il BFS
    mentioned = set()
    for e in edges.values():
        mentioned.update(e.get('imported_by', []))
        mentioned.update(cb['file'] for cb in e.get('called_by', []))
    for f in mentioned:
        files.setdefault(f, {
            'language': 'python',
            'symbols': [],
            'imports_to': [],
            'imported_by': [],
            'calls_out': [],
            'called_by': [],
            'mtime': 0.0,
        })
    return {
        'files': files,
        'symbol_index': {},
        'stats': {'total_files': len(files)},
    }


# ======================================================================
# 1. Seeds text_match preservati
# ======================================================================
class TestSeeds:
    def test_seed_kept_at_top_without_graph(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        res = predict_files_with_impact('login', graph=None)
        assert res[0]['file'] == 'src/auth.py'
        assert res[0]['source'] == 'text_match'
        assert res[0]['hops'] == 0

    def test_no_seeds_returns_empty(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['unrelated'], 'identifiers': []},
        })
        res = predict_files_with_impact('kubernetes autoscaling', graph=None)
        assert res == []


# ======================================================================
# 2. Direct importers (hop=1)
# ======================================================================
class TestDirectExpansion:
    def test_direct_importer_added(self, fake_index):
        # auth.py è il seed. handler.py importa auth.py (nome senza "login" per
        # evitare filename boost e isolare il contributo del graph expansion).
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
            'src/handler.py': {'symbols': ['on_request'], 'identifiers': []},
        })
        graph = _make_graph({
            'src/auth.py': {'imported_by': ['src/handler.py']},
            'src/handler.py': {},
        })
        res = predict_files_with_impact('login', graph=graph, max_hops=2)
        files = [r['file'] for r in res]
        assert 'src/auth.py' in files
        assert 'src/handler.py' in files

        handler = next(r for r in res if r['file'] == 'src/handler.py')
        assert handler['source'] == 'graph_expansion'
        assert handler['hops'] == 1
        assert "impact of 'src/auth.py'" in handler['why']

    def test_forward_dependency_discovered_by_personalized_graph(self, fake_index):
        fake_index({
            'src/controller.py': {'symbols': ['handle_request'], 'identifiers': []},
            'src/validator.py': {'symbols': ['validate_payload'], 'identifiers': []},
        })
        graph = _make_graph({
            'src/controller.py': {},
            'src/validator.py': {},
        })
        graph['files']['src/controller.py']['imports_to'] = [
            {'resolved': 'src/validator.py'}
        ]

        res = predict_files_with_impact(
            'handle_request', graph=graph, max_hops=2, use_semantic=False,
        )

        validator = next(r for r in res if r['file'] == 'src/validator.py')
        assert validator['source'] == 'graph_expansion'
        assert 'personalized graph rank' in validator['why']

    def test_direct_score_is_seed_times_0_50(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
            'src/handler.py': {'symbols': [], 'identifiers': []},
        })
        graph = _make_graph({
            'src/auth.py': {'imported_by': ['src/handler.py']},
        })
        # use_semantic=False: testiamo la matematica BM25+graph pura, senza
        # il blend del reranker semantico che riscala tutti gli score.
        res = predict_files_with_impact(
            'login', graph=graph, max_hops=1, use_semantic=False,
        )
        seed = next(r for r in res if r['file'] == 'src/auth.py')
        handler = next(r for r in res if r['file'] == 'src/handler.py')
        assert handler['score'] == pytest.approx(seed['score'] * HOP_DECAY[1], rel=1e-4)


# ======================================================================
# 3. Transitive importers (hop=2)
# ======================================================================
class TestTransitiveExpansion:
    def test_transitive_gets_weighted_less_than_direct(self, fake_index):
        # C -> B -> A (seed). A è il match, B hop=1, C hop=2
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': [], 'identifiers': []},
            'src/c.py': {'symbols': [], 'identifiers': []},
        })
        graph = _make_graph({
            'src/a.py': {'imported_by': ['src/b.py']},
            'src/b.py': {'imported_by': ['src/c.py']},
            'src/c.py': {},
        })
        res = predict_files_with_impact('login', graph=graph, max_hops=2)
        files = {r['file']: r for r in res}
        assert 'src/b.py' in files and 'src/c.py' in files
        assert files['src/b.py']['hops'] == 1
        assert files['src/c.py']['hops'] == 2
        assert files['src/b.py']['score'] > files['src/c.py']['score']

    def test_max_hops_limits_expansion(self, fake_index):
        # max_hops=1 ⇒ non include C
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': [], 'identifiers': []},
            'src/c.py': {'symbols': [], 'identifiers': []},
        })
        graph = _make_graph({
            'src/a.py': {'imported_by': ['src/b.py']},
            'src/b.py': {'imported_by': ['src/c.py']},
        })
        res = predict_files_with_impact('login', graph=graph, max_hops=1)
        files = [r['file'] for r in res]
        assert 'src/b.py' in files
        assert 'src/c.py' not in files


# ======================================================================
# 4. Graceful fallback
# ======================================================================
class TestFallback:
    def test_no_graph_equals_plain_bm25(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': ['logout'], 'identifiers': []},
        })
        with_impact = predict_files_with_impact('login', graph=None, max_hops=2)
        no_impact = predict_files_explained('login')
        assert [r['file'] for r in with_impact] == [r['file'] for r in no_impact]
        # Tutti source=text_match quando graph è None
        assert all(r['source'] == 'text_match' for r in with_impact)

    def test_max_hops_zero_disables_expansion(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': [], 'identifiers': []},
        })
        graph = _make_graph({
            'src/a.py': {'imported_by': ['src/b.py']},
        })
        res = predict_files_with_impact('login', graph=graph, max_hops=0)
        files = [r['file'] for r in res]
        assert files == ['src/a.py']

    def test_empty_graph_fallback(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
        })
        res = predict_files_with_impact('login', graph={'files': {}}, max_hops=2)
        assert len(res) == 1
        assert res[0]['file'] == 'src/a.py'


# ======================================================================
# 5. Dedup + merging
# ======================================================================
class TestMerging:
    def test_seed_not_duplicated_even_if_reached_by_graph(self, fake_index):
        # a e b entrambi matchano BM25. b importa a → b sarebbe sia seed sia hop=1.
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': ['login'], 'identifiers': []},
        })
        graph = _make_graph({
            'src/a.py': {'imported_by': ['src/b.py']},
        })
        res = predict_files_with_impact('login', graph=graph, max_hops=2)
        files = [r['file'] for r in res]
        # Ogni file appare una sola volta
        assert len(files) == len(set(files))
        # b è seed BM25, mantiene source='text_match' anche se graph lo raggiunge
        b_entry = next(r for r in res if r['file'] == 'src/b.py')
        assert b_entry['source'] == 'text_match'
        assert b_entry['hops'] == 0

    def test_graph_boost_accumulates_for_seed(self, fake_index):
        """
        Se b è text_match e anche scoperto via graph da a (anch'esso seed),
        lo score di b dovrebbe essere BM25(b) + DECAY*BM25(a).
        """
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': ['login'], 'identifiers': []},
        })
        graph_linked = _make_graph({
            'src/a.py': {'imported_by': ['src/b.py']},
        })
        graph_empty = _make_graph({})

        res_linked = predict_files_with_impact(
            'login', graph=graph_linked, max_hops=1, use_semantic=False,
        )
        res_empty = predict_files_with_impact(
            'login', graph=graph_empty, max_hops=1, use_semantic=False,
        )

        b_linked = next(r['score'] for r in res_linked if r['file'] == 'src/b.py')
        b_empty = next(r['score'] for r in res_empty if r['file'] == 'src/b.py')
        assert b_linked > b_empty


# ======================================================================
# 6. Called_by path (non solo imports)
# ======================================================================
class TestCalledByExpansion:
    def test_caller_expanded_via_called_by(self, fake_index):
        # validator.py ha un simbolo validate_jwt. handler.py chiama validate_jwt.
        # Nel grafo: validator.called_by = [{file: handler.py, symbol: validate_jwt}]
        fake_index({
            'src/validator.py': {'symbols': ['validate_jwt'], 'identifiers': []},
            'src/handler.py': {'symbols': [], 'identifiers': []},
        })
        graph = _make_graph({
            'src/validator.py': {
                'called_by': [{'file': 'src/handler.py', 'symbol': 'validate_jwt'}],
            },
        })
        res = predict_files_with_impact('validate_jwt', graph=graph, max_hops=1)
        files = [r['file'] for r in res]
        assert 'src/handler.py' in files
        handler = next(r for r in res if r['file'] == 'src/handler.py')
        assert handler['source'] == 'graph_expansion'
        assert handler['hops'] == 1
