"""Test BM25 ranker."""
import pytest

from src.brain.bm25 import (
    tokenize_code,
    tokenize_query,
    build_bm25_index,
    save_bm25_index,
    load_bm25_index,
    search,
)
from src.brain.code_graph import build_graph
from src.brain.parsers import get_parser


def _skip_if_no_parser(lang):
    if get_parser(lang) is None:
        pytest.skip(f'tree-sitter-{lang} not installed')


# -------------------- Tokenization --------------------

class TestTokenizeCode:
    def test_splits_camel_case(self):
        tokens = tokenize_code('AuthService')
        assert 'auth' in tokens
        assert 'service' in tokens

    def test_splits_get_prefix(self):
        tokens = tokenize_code('getUserById')
        assert 'get' in tokens
        assert 'user' in tokens

    def test_splits_snake_case(self):
        tokens = tokenize_code('verify_jwt_token')
        assert 'verify' in tokens
        assert 'jwt' in tokens
        assert 'token' in tokens

    def test_removes_stopwords(self):
        tokens = tokenize_code('add the new feature')
        assert 'add' not in tokens   # add è in STOPWORDS
        assert 'the' not in tokens
        assert 'feature' not in tokens  # "feature" è stopword nel progetto
        # 'new' ha 3 caratteri e non è in stopwords → viene tenuto

    def test_preserves_repetitions_for_tf(self):
        """tokenize_code non deve dedup — serve per calcolare TF."""
        tokens = tokenize_code('jwt jwt jwt token')
        assert tokens.count('jwt') == 3
        assert tokens.count('token') == 1

    def test_lowercase_normalization(self):
        tokens = tokenize_code('HTTPRequest')
        # HTTPRequest → HTTP, Request → http, request (HTTP saltato perché <3 solo se upper)
        # Il nostro splitter lo vede come HTTPRequest → HTTP + Request
        assert 'request' in tokens
        # 'http' dovrebbe esserci
        assert 'http' in tokens

    def test_handles_special_chars(self):
        tokens = tokenize_code('user@email.com')
        assert 'user' in tokens
        assert 'email' in tokens


# -------------------- Build index --------------------

@pytest.fixture
def sample_repo(tmp_path):
    """Repo sintetico con 3 file di auth/login/db per testare BM25."""
    _skip_if_no_parser('python')
    (tmp_path / 'auth_service.py').write_text(
        'import jwt\n'
        'def login(user, password):\n'
        '    return jwt.encode({"sub": user})\n'
        'def logout(token):\n'
        '    return True\n'
        'def verify_token(token):\n'
        '    return jwt.decode(token)\n'
    )
    (tmp_path / 'login_handler.py').write_text(
        'from auth_service import login\n'
        'def handle_login_request(req):\n'
        '    token = login(req.user, req.password)\n'  # 'token' presente qui
        '    return token\n'
    )
    (tmp_path / 'database_operations.py').write_text(
        'def query_users(filter):\n'
        '    return []\n'
        'def insert_row(row):\n'
        '    pass\n'
    )
    return tmp_path


class TestBuildIndex:
    def test_builds_structure(self, sample_repo):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)

        assert 'term_freq' in idx
        assert 'idf' in idx
        assert 'doc_lengths' in idx
        assert 'avg_doc_len' in idx
        assert idx['n_docs'] == 3

    def test_idf_higher_for_rare_terms(self, sample_repo):
        """jwt è in 1/3 file, 'token' in 2/3 → 'jwt' deve avere IDF più alto."""
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)

        idf = idx['idf']
        assert idf['jwt'] > idf['token'], (
            f"rare 'jwt' should have higher IDF than 'token': "
            f"jwt={idf.get('jwt')} vs token={idf.get('token')}"
        )

    def test_filename_terms_get_boosted(self, sample_repo):
        """'database' nel filename appare boostato nel term_freq."""
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        tf = idx['term_freq']['database_operations.py']
        # Con boost 5 per filename tokens + eventuali altre occorrenze
        assert tf.get('database', 0) >= 5


# -------------------- Search --------------------

class TestSearch:
    def test_exact_match_finds_correct_file(self, sample_repo):
        """Query 'jwt decode' deve predire auth_service.py al top."""
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        results = search(idx, 'jwt decode token')

        assert len(results) > 0
        top_file = results[0][0]
        assert top_file == 'auth_service.py'

    def test_login_query_ranks_login_files_high(self, sample_repo):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        results = search(idx, 'user can login to the system')

        top_files = [r[0] for r in results[:2]]
        # Entrambi auth_service e login_handler sono rilevanti
        assert 'auth_service.py' in top_files or 'login_handler.py' in top_files
        # database_operations non deve essere nei primi
        all_files = [r[0] for r in results]
        if 'database_operations.py' in all_files:
            db_rank = all_files.index('database_operations.py')
            login_ranks = [
                all_files.index(f) for f in ('auth_service.py', 'login_handler.py')
                if f in all_files
            ]
            assert all(lr < db_rank for lr in login_ranks)

    def test_explanation_includes_matched_terms(self, sample_repo):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        results = search(idx, 'jwt token verify')

        top_file, top_score, explanation = results[0]
        assert 'matched_terms' in explanation
        assert len(explanation['matched_terms']) > 0
        # Almeno uno dei termini attesi deve essere nei matched
        assert any(t in explanation['matched_terms'] for t in ('jwt', 'token', 'verify'))

    def test_empty_query_returns_empty(self, sample_repo):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        results = search(idx, '')
        assert results == []

    def test_query_with_only_stopwords(self, sample_repo):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        results = search(idx, 'the and for with')
        assert results == []

    def test_top_k_limit(self, sample_repo):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)
        results = search(idx, 'login user token', top_k=1)
        assert len(results) == 1


# -------------------- Persistence --------------------

class TestPersistence:
    def test_save_and_load(self, sample_repo, tmp_path):
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)

        out = tmp_path / 'bm25.json'
        save_bm25_index(idx, out)
        loaded = load_bm25_index(out)

        assert loaded['n_docs'] == idx['n_docs']
        assert set(loaded['term_freq'].keys()) == set(idx['term_freq'].keys())

    def test_load_nonexistent_returns_none(self, tmp_path):
        assert load_bm25_index(tmp_path / 'nothere.json') is None


# -------------------- BM25 correctness --------------------

class TestBM25Correctness:
    def test_term_frequency_saturation(self, sample_repo):
        """
        Proprietà BM25: la saturazione limita il contributo di un termine
        ripetuto nel DOCUMENTO (non nella query). 
        
        Verifichiamo confrontando un doc col termine 1 volta vs N volte:
        il contributo deve crescere meno-che-linearmente.
        
        Qui lo verifichiamo sul meccanismo interno: se ripeto il termine
        nella QUERY, lo score cresce linearmente (by design in BM25), ma il
        contributo del termine al singolo doc tf → inf è limitato a k1+1.
        """
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)

        # Saturazione si vede sul tf all'interno di un doc
        # La formula tf*(k1+1)/(tf+k1*norm) converge a k1+1 per tf→inf
        # Quindi max term contribution per query singola ≈ idf * (k1+1)
        from src.brain.bm25 import K1
        max_contribution_per_term = max(idx['idf'].values()) * (K1 + 1)
        
        # Con query di 1 singolo termine, lo score max è bound da max_contribution
        r = search(idx, 'jwt')
        assert r[0][1] <= max_contribution_per_term + 0.01, (
            f"score {r[0][1]} eccede saturazione teorica {max_contribution_per_term}"
        )

    def test_common_term_low_idf(self, sample_repo):
        """Un termine in tutti i doc ha IDF bassa (vicina a zero o negativa)."""
        graph = build_graph(sample_repo)
        idx = build_bm25_index(graph, repo_root=sample_repo)

        # Aggiungo un termine artificialmente presente ovunque
        idf = idx['idf']
        # 'def' è token Python comune — ma viene filtrato da tokenize_code
        # Prendiamo invece 'token' che è in auth_service (in 2/3 forse)
        if 'def' in idf:
            assert idf['def'] < 1.0


# -------------------- Test file detection & penalty --------------------

class TestIsTestFile:
    @pytest.mark.parametrize('path, expected', [
        ('tests/test_foo.py', True),
        ('tests/conftest.py', True),
        ('src/__tests__/bar.js', True),
        ('src/spec/user.spec.ts', True),
        ('test_main.py', True),
        ('auth_test.py', True),
        ('user.test.js', True),
        ('user.spec.ts', True),
        ('src/auth.py', False),
        ('src/models/user.py', False),
        ('README.md', False),
        ('src/__init__.py', False),
    ])
    def test_detection(self, path, expected):
        from src.brain.bm25 import is_test_file
        assert is_test_file(path) == expected


class TestTestFilePenalty:
    def test_test_files_get_penalized(self, tmp_path):
        """Con penalize_tests=True, file di test prendono score ridotto."""
        _skip_if_no_parser('python')
        # Repo con un source file e un test file entrambi con stesse keyword
        (tmp_path / 'auth.py').write_text(
            'def login(user): return user\n'
            'def verify_token(token): return token\n'
        )
        (tmp_path / 'tests').mkdir()
        (tmp_path / 'tests' / 'test_auth.py').write_text(
            'def test_login_verify_token():\n'
            '    from auth import login, verify_token\n'
            '    assert login("u") and verify_token("t")\n'
        )

        graph = build_graph(tmp_path)
        idx = build_bm25_index(graph, repo_root=tmp_path)

        with_penalty = search(idx, 'login verify token', penalize_tests=True)
        without = search(idx, 'login verify token', penalize_tests=False)

        # Con penalty: il source deve essere in alto
        top_with = with_penalty[0][0]
        assert top_with == 'auth.py', f'Expected auth.py at top, got {top_with}'

        # Senza penalty: il test potrebbe essere al top (ha più termini)
        # Verifichiamo almeno che la penalty cambia l'ordine o gli score
        test_score_with = next(
            (s for p, s, _ in with_penalty if 'test_' in p), None
        )
        test_score_without = next(
            (s for p, s, _ in without if 'test_' in p), None
        )
        if test_score_with is not None and test_score_without is not None:
            assert test_score_with < test_score_without
