"""
Test STEP 2.3 — Semantic reranker (layer opzionale).

La maggior parte dei test gira SENZA sentence-transformers installato e verifica
i fallback graceful. I test che richiedono la libreria sono skipif(is_available).
"""
import pytest

from src.brain.file_indexer import _finalize_index, save_index
from src.brain.file_predictor import predict_files_with_impact, predict_files_explained
from src.brain import semantic_reranker
from src.brain.semantic_reranker import (
    is_available,
    rerank,
    _build_doc_text,
    DEFAULT_MODEL_NAME,
)


@pytest.fixture
def fake_index(tmp_brain):
    def _make(files_data):
        for _, d in files_data.items():
            d.setdefault('mtime', 0.0)
        idx = _finalize_index(files_data)
        save_index(idx)
        return idx
    return _make


# ======================================================================
# 1. Availability / env switches
# ======================================================================
class TestAvailability:
    def test_is_available_returns_bool(self):
        assert isinstance(is_available(), bool)

    def test_env_kill_switch_disables(self, monkeypatch):
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '0')
        assert is_available() is False

    def test_env_enabled_is_bool(self, monkeypatch):
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '1')
        # Non controlliamo True/False assoluto: dipende dall'installazione
        assert isinstance(is_available(), bool)


# ======================================================================
# 2. Graceful fallback
# ======================================================================
class TestGracefulFallback:
    def test_empty_candidates_returns_empty(self):
        out = rerank('some query', [])
        assert out == []

    def test_no_index_returns_unchanged(self, monkeypatch):
        """Se is_available=False (o lib mancante) → output == input."""
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '0')
        candidates = [
            {'file': 'a.py', 'score': 1.0},
            {'file': 'b.py', 'score': 0.5},
        ]
        out = rerank('query', candidates, index={'files': {}})
        # Stessa identità di oggetti e ordine
        assert out is candidates
        assert [c['file'] for c in out] == ['a.py', 'b.py']
        # Nessuno ha semantic_score aggiunto
        assert 'semantic_score' not in candidates[0]

    def test_missing_index_data_returns_unchanged(self, monkeypatch):
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '0')
        candidates = [{'file': 'a.py', 'score': 1.0}]
        out = rerank('query', candidates, index=None)
        assert out == candidates


# ======================================================================
# 3. Doc text building
# ======================================================================
class TestBuildDocText:
    def test_basename_extracted_without_extension(self):
        text = _build_doc_text('src/brain/auth_service.py', {
            'symbols': ['login'], 'identifiers': ['token'],
        })
        assert 'auth_service' in text
        # No .py nel testo
        assert '.py' not in text

    def test_limits_symbols_and_identifiers(self):
        syms = [f'sym_{i}' for i in range(50)]
        idents = [f'ident_{i}' for i in range(50)]
        text = _build_doc_text('x.py', {'symbols': syms, 'identifiers': idents})
        # 20 simboli + 20 identifier attesi al massimo + 1 basename
        parts = text.split()
        assert len(parts) <= 1 + 20 + 20

    def test_handles_missing_fields(self):
        text = _build_doc_text('a.py', {})
        assert 'a' in text


# ======================================================================
# 4. Integrazione con predict_files_with_impact
# ======================================================================
class TestIntegrationWithPredictor:
    def test_use_semantic_false_no_semantic_score_added(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
        })
        res = predict_files_with_impact('login', use_semantic=False)
        assert all('semantic_score' not in r for r in res)

    def test_use_semantic_unavailable_is_noop(self, fake_index, monkeypatch):
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '0')
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
            'src/b.py': {'symbols': ['logout'], 'identifiers': []},
        })
        bm25 = predict_files_explained('login')
        with_sem = predict_files_with_impact('login', use_semantic=True, max_hops=0)
        # Stesso ordine dei file, nessun semantic_score aggiunto
        assert [r['file'] for r in bm25] == [r['file'] for r in with_sem]
        assert all('semantic_score' not in r for r in with_sem)

    def test_use_semantic_does_not_crash_on_missing_lib(self, fake_index, monkeypatch):
        """Anche se qualcuno passa use_semantic=True senza lib installata,
        la funzione deve ritornare risultati BM25 senza crash."""
        monkeypatch.setenv('MCP_BRAIN_SEMANTIC', '0')
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        try:
            res = predict_files_with_impact('login', use_semantic=True)
        except Exception as e:
            pytest.fail(f'should not crash: {e}')
        assert res[0]['file'] == 'src/auth.py'


# ======================================================================
# 5. REAL rerank — skipped se lib non installata
# ======================================================================
@pytest.mark.skipif(
    not is_available(),
    reason='sentence-transformers not installed (pip install sentence-transformers)',
)
class TestRealRerank:
    def test_rerank_adds_semantic_score(self, fake_index):
        idx = fake_index({
            'src/auth.py': {'symbols': ['login', 'logout'], 'identifiers': []},
            'src/other.py': {'symbols': ['process_data'], 'identifiers': []},
        })
        candidates = [
            {'file': 'src/auth.py', 'score': 3.0},
            {'file': 'src/other.py', 'score': 2.5},
        ]
        out = rerank('user login authentication', candidates, index=idx)
        assert all('semantic_score' in c for c in out)
        for c in out:
            assert 0.0 <= c['semantic_score'] <= 1.0

    def test_rerank_preserves_count(self, fake_index):
        idx = fake_index({
            f'src/f{i}.py': {'symbols': [f'fn_{i}'], 'identifiers': []}
            for i in range(5)
        })
        candidates = [
            {'file': f'src/f{i}.py', 'score': float(5 - i)}
            for i in range(5)
        ]
        out = rerank('fn', candidates, index=idx)
        assert len(out) == 5

    def test_rerank_with_semantic_changes_ranking(self, fake_index):
        """Query semanticamente vicina a un file che perde su BM25:
        il semantic rerank può ripromuoverlo."""
        idx = fake_index({
            'src/authentication_service.py': {
                'symbols': ['verify_credentials', 'issue_token'],
                'identifiers': [],
            },
            'src/misc.py': {
                'symbols': ['foo'], 'identifiers': ['bar', 'baz'],
            },
        })
        # Score BM25 volutamente basso su authentication_service e alto su misc
        candidates = [
            {'file': 'src/misc.py', 'score': 10.0},
            {'file': 'src/authentication_service.py', 'score': 1.0},
        ]
        out = rerank('user login and token authentication',
                     candidates, index=idx, blend=0.8)  # blend alto per dimostrare
        # Con blend=0.8 il semantic domina: authentication_service dovrebbe salire
        # Non asserisco l'ordine esatto (dipende dal modello) ma che almeno il
        # semantic_score di authentication_service > semantic_score di misc
        auth = next(c for c in out if 'auth' in c['file'])
        misc = next(c for c in out if 'misc' in c['file'])
        assert auth['semantic_score'] > misc['semantic_score']


# ======================================================================
# 6. Model caching (smoke)
# ======================================================================
@pytest.mark.skipif(not is_available(), reason='sentence-transformers not installed')
class TestModelCache:
    def test_model_cached_singleton(self):
        # Chiamate multiple ritornano la stessa istanza
        m1 = semantic_reranker._get_model()
        m2 = semantic_reranker._get_model()
        assert m1 is m2

    def test_default_model_name_constant(self):
        assert DEFAULT_MODEL_NAME.startswith('sentence-transformers/')
