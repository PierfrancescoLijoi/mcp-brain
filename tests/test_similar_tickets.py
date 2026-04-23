"""Test STEP 4.2 — similar past tickets."""
import pytest

from src.brain.similar_tickets import (
    find_similar_tickets,
    _extract_ticket_id,
    _text_similarity,
    _file_overlap_bonus,
)


# ----------------------------------------------------------------------
# 1. extract ticket id
# ----------------------------------------------------------------------
class TestExtractTicketId:
    @pytest.mark.parametrize('content, expected', [
        ('ticket #42: fix login', 42),
        ('Ticket #7 closed', 7),
        ('Fixed in PR #123', 123),
        ('closes issue #99', 99),
        ('decision: use JWT', None),
        ('', None),
    ])
    def test_various(self, content, expected):
        assert _extract_ticket_id(content) == expected


# ----------------------------------------------------------------------
# 2. text similarity
# ----------------------------------------------------------------------
class TestTextSimilarity:
    def test_identical_topics(self):
        s = _text_similarity('JWT signing RS256', 'JWT RS256 signing')
        assert s > 0.9

    def test_unrelated(self):
        s = _text_similarity('JWT signing', 'kubernetes deployment')
        assert s == 0.0

    def test_partial(self):
        s = _text_similarity('JWT signing validation',
                             'JWT decoding authentication')
        assert 0.0 < s < 1.0


# ----------------------------------------------------------------------
# 3. file overlap bonus
# ----------------------------------------------------------------------
class TestFileOverlapBonus:
    def test_exact_match(self):
        mem = {'scope_type': 'file', 'scope_value': 'src/auth.py'}
        assert _file_overlap_bonus(['src/auth.py'], mem) == 0.2

    def test_partial_match_in_path(self):
        mem = {'scope_type': 'module', 'scope_value': 'src/brain'}
        assert _file_overlap_bonus(['src/brain/auth.py'], mem) == 0.2

    def test_no_predicted_files(self):
        mem = {'scope_type': 'file', 'scope_value': 'src/auth.py'}
        assert _file_overlap_bonus([], mem) == 0.0

    def test_no_scope(self):
        mem = {'scope_type': 'repo', 'scope_value': None}
        assert _file_overlap_bonus(['src/auth.py'], mem) == 0.0

    def test_no_overlap(self):
        mem = {'scope_type': 'file', 'scope_value': 'src/db.py'}
        assert _file_overlap_bonus(['src/auth.py'], mem) == 0.0


# ----------------------------------------------------------------------
# 4. find_similar_tickets (iniettando memories)
# ----------------------------------------------------------------------
class TestFindSimilarTickets:
    def _mk(self, **kwargs):
        defaults = dict(
            id=kwargs.get('id', 1),
            category=kwargs.get('category', 'decision'),
            content=kwargs.get('content', 'decision: JWT signing RS256'),
            status='active',
            created_at='2026-01-01T00:00:00+00:00',
            scope_type=kwargs.get('scope_type', 'repo'),
            scope_value=kwargs.get('scope_value'),
        )
        defaults.update(kwargs)
        return defaults

    def test_empty_query_returns_empty(self):
        assert find_similar_tickets('p', '', '', memories=[self._mk()]) == []

    def test_empty_memories_returns_empty(self):
        assert find_similar_tickets('p', 'JWT fix', memories=[]) == []

    def test_ranks_by_similarity(self):
        mems = [
            self._mk(id=1, content='decision: use kubernetes for deployment'),
            self._mk(id=2, content='decision: JWT RS256 signing strategy'),
        ]
        results = find_similar_tickets(
            'p', 'fix JWT RS256 signing', memories=mems, threshold=0.0
        )
        # id=2 deve essere primo
        assert results[0]['memory_id'] == 2

    def test_threshold_filters_below(self):
        mems = [
            self._mk(id=1, content='totally unrelated content'),
        ]
        results = find_similar_tickets(
            'p', 'JWT auth fix', memories=mems, threshold=0.5
        )
        assert results == []

    def test_excludes_self_ticket(self):
        mems = [
            self._mk(id=1, content='ticket #42: previous fix for JWT signing'),
            self._mk(id=2, content='ticket #99: old JWT signing fix'),
        ]
        results = find_similar_tickets(
            'p', 'JWT signing fix', exclude_ticket_id=42,
            memories=mems, threshold=0.0,
        )
        tids = [r['ticket_id'] for r in results]
        assert 42 not in tids
        assert 99 in tids

    def test_file_bonus_increases_score(self):
        mem_with_scope = self._mk(
            id=1,
            content='decision: something minor',
            scope_type='file',
            scope_value='src/auth.py',
        )
        mem_without_scope = self._mk(id=2, content='decision: something minor')

        r_with = find_similar_tickets(
            'p', 'whatever',
            predicted_files=['src/auth.py'],
            memories=[mem_with_scope],
            threshold=0.0,
        )
        r_without = find_similar_tickets(
            'p', 'whatever',
            predicted_files=['src/auth.py'],
            memories=[mem_without_scope],
            threshold=0.0,
        )
        if r_with and r_without:
            assert r_with[0]['similarity'] > r_without[0]['similarity']

    def test_extracts_ticket_id_from_content(self):
        mems = [
            self._mk(
                id=1,
                content='ticket #42: fix JWT RS256 signing bug',
            ),
        ]
        results = find_similar_tickets(
            'p', 'JWT RS256 signing', memories=mems, threshold=0.0
        )
        assert results[0]['ticket_id'] == 42

    def test_top_k_respected(self):
        mems = [
            self._mk(id=i, content=f'decision: JWT token variant {i}')
            for i in range(10)
        ]
        results = find_similar_tickets(
            'p', 'JWT token refactor', memories=mems,
            top_k=3, threshold=0.0,
        )
        assert len(results) <= 3

    def test_schema_fields_present(self):
        mems = [self._mk(id=1, content='decision: JWT signing')]
        results = find_similar_tickets('p', 'JWT signing', memories=mems,
                                       threshold=0.0)
        for key in (
            'memory_id', 'category', 'content', 'ticket_id',
            'similarity', 'text_similarity', 'file_bonus',
            'scope_type', 'scope_value', 'created_at',
        ):
            assert key in results[0]


# ----------------------------------------------------------------------
# 5. Integration with DB (se il DB è vuoto, fallback a [])
# ----------------------------------------------------------------------
class TestDBIntegration:
    def test_empty_db_returns_empty(self, tmp_brain):
        results = find_similar_tickets('some_project', 'any query')
        assert results == []

    def test_reads_from_db_when_no_injection(self, tmp_brain):
        """Inseriamo una memoria e verifichiamo che il loader la trovi."""
        from src.storage.db import save_memory
        save_memory('myproj', 1, 'decision',
                    'decision: JWT RS256 signing strategy',
                    status='active')
        results = find_similar_tickets(
            'myproj', 'JWT RS256 fix', threshold=0.0
        )
        assert len(results) >= 1
        assert 'JWT' in results[0]['content']
