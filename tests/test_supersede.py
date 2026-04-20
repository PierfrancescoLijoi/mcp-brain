"""
Test del flusso semantic-supersede end-to-end.
Questo è il flusso che PRIMA di step 0.1 era codice morto.
"""
from src.storage.db import save_memory, get_connection
from src.capture.git_hook import _apply_semantic_supersede


def _get_all(project='p'):
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, status, content, supersedes FROM memories WHERE project=? ORDER BY id",
        (project,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _find(rows, substring):
    return next(r for r in rows if substring in r['content'])


class TestSemanticSupersede:
    def test_new_decision_supersedes_similar_old(self, tmp_brain):
        """Caso canonico: nuova decision simile rimpiazza la vecchia."""
        save_memory('p', 1, 'decision',
                    'decision: refactor JWT to use RS256 signing',
                    status='active')
        save_memory('p', 1, 'decision',
                    'decision: move auth to OAuth2 flow',
                    status='active')
        new_content = 'decision: JWT signing now uses ES256 instead of RS256'
        save_memory('p', 1, 'decision', new_content, status='active', source='git-hook')

        _apply_semantic_supersede('p', new_content, category='decision')

        rows = _get_all()
        assert _find(rows, 'RS256 signing')['status'] == 'superseded'
        assert _find(rows, 'OAuth2 flow')['status'] == 'active'
        assert _find(rows, 'ES256 instead')['status'] == 'active'

    def test_supersede_sets_link(self, tmp_brain):
        """La colonna supersedes deve puntare al nuovo id."""
        save_memory('p', 1, 'decision', 'decision: use postgres for storage')
        new_content = 'decision: migrate storage from postgres to sqlite'
        save_memory('p', 1, 'decision', new_content, source='git-hook')

        _apply_semantic_supersede('p', new_content, 'decision')

        rows = _get_all()
        old = _find(rows, 'postgres for storage')
        new = _find(rows, 'migrate storage')
        assert old['status'] == 'superseded'
        assert old['supersedes'] == new['id']

    def test_unrelated_decision_not_superseded(self, tmp_brain):
        """Decisioni su topic completamente diversi restano active."""
        save_memory('p', 1, 'decision', 'decision: kubernetes for deployment')
        new_content = 'decision: use pytest for testing'
        save_memory('p', 1, 'decision', new_content, source='git-hook')

        _apply_semantic_supersede('p', new_content, 'decision')

        rows = _get_all()
        assert _find(rows, 'kubernetes')['status'] == 'active'

    def test_different_category_not_crossed(self, tmp_brain):
        """Una nuova decision NON deve superseded un pattern anche se simile."""
        save_memory('p', 1, 'pattern', 'pattern: use JWT for auth')
        new_content = 'decision: standardize JWT handling'
        save_memory('p', 1, 'decision', new_content, source='git-hook')

        _apply_semantic_supersede('p', new_content, 'decision')

        rows = _get_all()
        assert _find(rows, 'pattern:')['status'] == 'active'

    def test_no_new_memory_is_noop(self, tmp_brain):
        """Se il content non esiste ancora nel DB, la funzione non crasha."""
        _apply_semantic_supersede('p', 'decision: not saved yet', 'decision')
        assert _get_all() == []
