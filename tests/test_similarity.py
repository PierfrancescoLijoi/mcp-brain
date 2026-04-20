"""Test primitive di similarity (base semantica di tutto il progetto)."""
from src.brain.similarity import tokenize, jaccard, semantic_similar, find_similar_memories


class TestTokenize:
    def test_removes_stopwords(self):
        tokens = tokenize('the quick brown fox')
        assert 'the' not in tokens
        assert 'quick' in tokens

    def test_lowercases(self):
        assert tokenize('JWT RS256') == {'jwt', 'rs256'}

    def test_skips_short_tokens(self):
        # Minimo 3 caratteri (regex `{2,}` + prima lettera)
        tokens = tokenize('ab xy foo')
        assert 'ab' not in tokens
        assert 'foo' in tokens

    def test_empty_input(self):
        assert tokenize('') == set()
        assert tokenize(None) == set()


class TestJaccard:
    def test_identical_sets(self):
        a = {'jwt', 'auth', 'rs256'}
        assert jaccard(a, a) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({'a', 'b'}, {'c', 'd'}) == 0.0

    def test_partial_overlap(self):
        # |{jwt}| / |{jwt, auth, oauth}| = 1/3
        a = {'jwt', 'auth'}
        b = {'jwt', 'oauth'}
        assert jaccard(a, b) == 1 / 3

    def test_empty_sets(self):
        assert jaccard(set(), set()) == 0.0
        assert jaccard({'a'}, set()) == 0.0


class TestSemanticSimilar:
    def test_above_threshold_is_similar(self):
        a = 'decision: JWT RS256 signing strategy'
        b = 'decision: JWT signing uses RS256'
        is_sim, score = semantic_similar(a, b, threshold=0.35)
        assert is_sim is True
        assert score >= 0.35

    def test_below_threshold_is_not_similar(self):
        a = 'decision: use kubernetes for deployment'
        b = 'decision: pytest as testing framework'
        is_sim, _ = semantic_similar(a, b, threshold=0.35)
        assert is_sim is False


class TestFindSimilarMemories:
    def test_filters_by_category(self):
        candidates = [
            {'id': 1, 'category': 'decision', 'content': 'decision: JWT RS256'},
            {'id': 2, 'category': 'pattern', 'content': 'pattern: JWT validation'},
        ]
        results = find_similar_memories('decision: JWT updated',
                                        candidates,
                                        threshold=0.2,
                                        same_category='decision')
        ids = [m['id'] for m, _ in results]
        assert ids == [1]

    def test_sorts_by_score_desc(self):
        candidates = [
            {'id': 1, 'content': 'foo bar zzz'},
            {'id': 2, 'content': 'foo bar baz'},
        ]
        results = find_similar_memories('foo bar baz qux',
                                        candidates, threshold=0.0)
        # id=2 deve matchare più di id=1
        assert results[0][0]['id'] == 2
        assert results[0][1] >= results[1][1]
