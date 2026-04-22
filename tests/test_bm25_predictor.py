"""
Test STEP 2.1 — BM25 con IDF sui symbols/identifiers.

La fixture `fake_index` costruisce un index deterministico in memoria (+ salvato
su disk via `save_index` grazie a `tmp_brain`). Così possiamo testare le
proprietà del BM25 senza dipendere dal parsing reale di file Python/JS.
"""
import math
import pytest

from src.brain.file_indexer import (
    _finalize_index,
    save_index,
    load_index,
    get_or_build_index,
    compute_bm25_stats,
)
from src.brain.file_predictor import (
    predict_files_explained,
    predict_files_from_issue,
    _idf,
    _bm25_tf_component,
    BM25_K1,
    BM25_B,
)


# ----------------------------------------------------------------------
# Fixture: index "finto" deterministico
# ----------------------------------------------------------------------
@pytest.fixture
def fake_index(tmp_brain):
    """Ritorna una factory che costruisce e persiste un index dato files_data."""
    def _make(files_data):
        # files_data: {rel_path: {'symbols': [...], 'identifiers': [...]}}
        # Completiamo con mtime se manca
        for f, d in files_data.items():
            d.setdefault('mtime', 0.0)
        idx = _finalize_index(files_data)
        save_index(idx)
        return idx
    return _make


# ======================================================================
# 1. Smoke: le stats BM25 sono calcolate e persistite
# ======================================================================
class TestIndexStats:
    def test_build_index_populates_df_and_avgdl(self, fake_index):
        idx = fake_index({
            'a.py': {'symbols': ['login', 'logout'], 'identifiers': ['user']},
            'b.py': {'symbols': ['login'], 'identifiers': ['user', 'token']},
        })
        assert idx['total'] == 2
        assert idx['df']['login'] == 2
        assert idx['df']['logout'] == 1
        # avgdl = average di doc_length: a=3*2+1*1=7, b=3*1+1*2=5 → avg=6
        assert idx['avgdl'] == pytest.approx(6.0)
        assert idx['doc_length']['a.py'] == 7
        assert idx['doc_length']['b.py'] == 5

    def test_compute_bm25_stats_empty(self):
        stats = compute_bm25_stats({})
        assert stats['total'] == 0
        assert stats['avgdl'] == 0.0
        assert stats['df'] == {}

    def test_persisted_index_preserves_stats(self, fake_index):
        fake_index({
            'a.py': {'symbols': ['x'], 'identifiers': []},
        })
        loaded = load_index()
        assert loaded is not None
        assert 'df' in loaded and 'avgdl' in loaded and 'doc_length' in loaded


# ======================================================================
# 2. Proprietà matematiche BM25
# ======================================================================
class TestBM25Math:
    def test_idf_rare_term_higher_than_common(self):
        # Termine presente in 1/100 doc vs 50/100 doc
        rare = _idf(df=1, total_docs=100)
        common = _idf(df=50, total_docs=100)
        assert rare > common > 0

    def test_idf_never_negative(self):
        # Okapi smoothed: +1.0 garantisce idf >= 0
        for df in [0, 1, 50, 99, 100]:
            assert _idf(df=df, total_docs=100) >= 0

    def test_idf_zero_total(self):
        assert _idf(df=0, total_docs=0) == 0.0

    def test_tf_saturation(self):
        # BM25 satura: tf=100 non è 100x tf=1
        avgdl = 10.0
        tf1 = _bm25_tf_component(tf=1, dl=10, avgdl=avgdl)
        tf100 = _bm25_tf_component(tf=100, dl=10, avgdl=avgdl)
        # Ratio deve essere << 100
        assert tf100 / tf1 < 10.0
        # Max asintotico di BM25 TF = k1+1
        assert tf100 < BM25_K1 + 1.0 + 0.01

    def test_tf_length_normalization(self):
        """
        Stessa TF ma file lungo vs corto: il corto deve avere score TF maggiore
        (è più "concentrato" sul termine).
        """
        avgdl = 10.0
        short = _bm25_tf_component(tf=3, dl=5, avgdl=avgdl)   # dl < avgdl
        long_ = _bm25_tf_component(tf=3, dl=50, avgdl=avgdl)  # dl > avgdl
        assert short > long_


# ======================================================================
# 3. Predictor end-to-end
# ======================================================================
class TestPredictor:
    def test_rare_term_wins_over_common(self, fake_index):
        # 'config' appare in tutti i file (comune), 'jwt_validator' solo in uno
        fake_index({
            'src/a.py': {'symbols': ['config', 'setup'], 'identifiers': []},
            'src/b.py': {'symbols': ['config', 'routes'], 'identifiers': []},
            'src/c.py': {'symbols': ['config', 'logger'], 'identifiers': []},
            'src/d.py': {'symbols': ['config', 'jwt_validator'], 'identifiers': []},
        })
        res = predict_files_explained('fix jwt_validator config issue')
        assert res, 'expected ranked results'
        # Il file con il termine raro DEVE essere primo
        assert res[0]['file'] == 'src/d.py'
        assert 'jwt_validator' in res[0]['matches'].get('symbol', [])

    def test_doc_length_normalization_in_ranking(self, fake_index):
        # File "gonfio" con 50 simboli irrilevanti + 'auth'
        # vs file "focalizzato" con solo 'auth'
        big_syms = [f'noise_{i}' for i in range(50)] + ['auth']
        fake_index({
            'src/small.py': {'symbols': ['auth'], 'identifiers': []},
            'src/huge.py': {'symbols': big_syms, 'identifiers': []},
        })
        res = predict_files_explained('auth')
        assert res[0]['file'] == 'src/small.py'

    def test_symbol_weighted_more_than_identifier(self, fake_index):
        # 'auth' è symbol in a, identifier in b → a deve vincere
        fake_index({
            'src/a.py': {'symbols': ['auth'], 'identifiers': ['unrelated']},
            'src/b.py': {'symbols': ['unrelated'], 'identifiers': ['auth']},
        })
        res = predict_files_explained('auth')
        assert res[0]['file'] == 'src/a.py'
        assert 'auth' in res[0]['matches'].get('symbol', [])

    def test_filename_boost(self, fake_index):
        # Due file con stesso contenuto, ma uno ha il nome che matcha
        fake_index({
            'src/helpers.py': {'symbols': ['foo'], 'identifiers': ['bar']},
            'src/auth.py':    {'symbols': ['foo'], 'identifiers': ['bar']},
        })
        res = predict_files_explained('auth')
        assert res[0]['file'] == 'src/auth.py'
        assert 'auth' in res[0]['matches'].get('filename', [])

    def test_multi_term_aggregation(self, fake_index):
        # File che matcha 2 termini deve battere file che ne matcha 1
        fake_index({
            'src/a.py': {'symbols': ['jwt', 'validator'], 'identifiers': []},
            'src/b.py': {'symbols': ['jwt', 'whatever'], 'identifiers': []},
        })
        res = predict_files_explained('jwt validator fix')
        assert res[0]['file'] == 'src/a.py'

    def test_stopwords_ignored(self, fake_index):
        # 'fix', 'update', 'the', ... sono stopword: non dovrebbero pesare.
        fake_index({
            'src/a.py': {'symbols': ['authenticate'], 'identifiers': []},
        })
        # Stessa predizione con e senza stopword → stesso score (se non zero)
        only_kw = predict_files_explained('authenticate')
        with_stop = predict_files_explained('fix the authenticate update issue please')
        assert only_kw[0]['score'] == pytest.approx(with_stop[0]['score'], rel=1e-6)

    def test_unknown_term_returns_empty(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
        })
        assert predict_files_explained('kubernetes pods autoscaling') == []

    def test_empty_query_returns_empty(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login'], 'identifiers': []},
        })
        assert predict_files_explained('') == []
        assert predict_files_explained('fix the', '') == []  # solo stopwords

    def test_confidence_levels_assigned(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['login', 'validate'], 'identifiers': []},
            'src/b.py': {'symbols': ['login'], 'identifiers': []},
            'src/c.py': {'symbols': ['logger'], 'identifiers': ['login']},
        })
        res = predict_files_explained('login validate')
        confs = {r['file']: r['confidence'] for r in res}
        assert confs['src/a.py'] == 'high'
        # Almeno uno dovrebbe essere < high
        assert any(c != 'high' for c in confs.values())

    def test_score_deterministic(self, fake_index):
        fake_index({
            'src/a.py': {'symbols': ['alpha', 'beta'], 'identifiers': ['gamma']},
            'src/b.py': {'symbols': ['alpha'], 'identifiers': []},
        })
        r1 = predict_files_explained('alpha beta gamma')
        r2 = predict_files_explained('alpha beta gamma')
        assert [(x['file'], x['score']) for x in r1] == [(x['file'], x['score']) for x in r2]

    def test_top_k_respected(self, fake_index):
        files = {
            f'src/f{i}.py': {'symbols': ['auth'], 'identifiers': []}
            for i in range(25)
        }
        fake_index(files)
        res = predict_files_explained('auth', top_k=5)
        assert len(res) == 5

    def test_empty_index_returns_empty(self, tmp_brain):
        # Nessun index sul disco → get_or_build_index costruisce da zero
        # Ma il repo (tmp_path) è vuoto → niente file indicizzati → no match
        res = predict_files_explained('anything')
        assert res == []


# ======================================================================
# 4. Backward-compat API
# ======================================================================
class TestBackwardCompat:
    def test_predict_files_from_issue_returns_list_of_paths(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        files = predict_files_from_issue('fix login bug')
        assert isinstance(files, list)
        assert all(isinstance(f, str) for f in files)
        assert 'src/auth.py' in files

    def test_predict_files_from_issue_empty_text(self, fake_index):
        fake_index({'src/a.py': {'symbols': ['x'], 'identifiers': []}})
        assert predict_files_from_issue('') == []

    def test_result_has_expected_schema(self, fake_index):
        fake_index({
            'src/auth.py': {'symbols': ['login'], 'identifiers': []},
        })
        res = predict_files_explained('login')
        item = res[0]
        for key in ('file', 'score', 'confidence', 'why', 'matches'):
            assert key in item
        assert item['confidence'] in ('high', 'medium', 'low')
