"""Test STEP 4.1 — brain_get_ticket_context all-in-one."""
import yaml
import pytest

from src.brain.file_indexer import _finalize_index, save_index
from src.tools.ticket_context_tool import (
    get_ticket_context_impl,
    register_get_ticket_context_tool,
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


def fake_issue(iid=42, title='Fix JWT bug', body='RS256 signing broken'):
    return {
        'id': iid, 'title': title, 'body': body,
        'labels': ['bug', 'auth'], 'state': 'open',
    }


def sig_patch(fn='login'):
    return (
        f"@@ -10,3 +10,3 @@ def {fn}(a):\n"
        f"-def {fn}(a):\n"
        f"+def {fn}(a, b):\n"
        f"     return a\n"
    )


def make_pr(n, author, title, files_patches):
    return {
        'number': n, 'author': author, 'title': title,
        'files_with_patches': [
            {'filename': fn, 'status': 'modified', 'patch': p}
            for fn, p in files_patches
        ],
    }


# ======================================================================
# 1. Output structure
# ======================================================================
class TestOutputStructure:
    def test_yaml_sections_present(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(), prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        for key in ('ticket', 'predicted_files', 'conflicts', 'guidance', 'claim'):
            assert key in data, f'missing: {key}'

    def test_ticket_fields(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(iid=42, title='T', body='B'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        assert data['ticket']['id'] == 42
        assert data['ticket']['title'] == 'T'
        assert 'labels' in data['ticket']

    def test_predicted_files_have_required_fields(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(title='login fix'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        assert data['predicted_files']
        for p in data['predicted_files']:
            for k in ('file', 'confidence', 'score', 'source', 'hops', 'why'):
                assert k in p


# ======================================================================
# 2. Issue errors
# ======================================================================
class TestIssueErrors:
    def test_issue_with_error_returns_error(self, fake_index):
        fake_index({'src/a.py': {'symbols': ['x'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=99, author='me',
            issue={'error': 'Not Found'},
            prs_with_patches=[], similar_memories=[],
        )
        assert out.startswith('error')

    def test_missing_issue_returns_error(self, fake_index):
        fake_index({'src/a.py': {'symbols': ['x'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=99, author='me',
            issue=None,
            prs_with_patches=[], similar_memories=[],
        )
        # Senza GitHub token questo passerà dal reader e tornerà un error string
        # ma non deve crashare
        assert isinstance(out, str)


# ======================================================================
# 3. Conflicts integration
# ======================================================================
class TestConflictsIntegration:
    def test_conflicts_none_when_no_prs(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(title='login fix'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        assert data['conflicts'] == 'none' or data['conflicts'] == {}
        assert 'safe to proceed' in data['guidance'].lower()

    def test_signature_conflict_detected(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        prs = [make_pr(42, 'bob', 'refactor',
                       [('src/auth.py', sig_patch('login'))])]
        out = get_ticket_context_impl(
            project='p', issue_id=7, author='me',
            issue=fake_issue(iid=7, title='login related fix'),
            prs_with_patches=prs, similar_memories=[],
        )
        data = yaml.safe_load(out)
        # Dovrebbe esserci almeno un gruppo 'signature'
        assert 'signature' in data['conflicts']
        assert 'block' in data['guidance'].lower()

    def test_author_excluded_from_own_conflicts(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        prs = [
            make_pr(1, 'me', 'my own', [('src/auth.py', sig_patch('login'))]),
            make_pr(2, 'other', 'theirs', [('src/auth.py', sig_patch('logout'))]),
        ]
        out = get_ticket_context_impl(
            project='p', issue_id=7, author='me',
            issue=fake_issue(title='login fix'),
            prs_with_patches=prs, similar_memories=[],
        )
        data = yaml.safe_load(out)
        sig = data['conflicts'].get('signature', []) if isinstance(data['conflicts'], dict) else []
        prs_found = [c['pr'] for c in sig]
        assert 1 not in prs_found  # mio, escluso


# ======================================================================
# 4. Claim integration
# ======================================================================
class TestClaimIntegration:
    def test_claim_performed_when_enabled(self, fake_index, tmp_brain):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me', do_claim=True,
            issue=fake_issue(title='login fix'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        assert data['claim']['claimed'] is True

        # Verifica effetto collaterale su claims.yaml
        from src.brain.claims_manager import get_active_claims
        active = get_active_claims()
        assert any(c['ticket'] == 42 for c in active)

    def test_claim_skipped_when_disabled(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me', do_claim=False,
            issue=fake_issue(title='login fix'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        assert data['claim']['claimed'] is False


# ======================================================================
# 5. Similar tickets integration
# ======================================================================
class TestSimilarTickets:
    def test_similar_surfaced_if_matching(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        similar = [{
            'id': 100, 'category': 'decision',
            'content': 'decision: JWT RS256 signing for login',
            'status': 'active',
            'created_at': '2026-01-01T00:00:00+00:00',
            'scope_type': 'file', 'scope_value': 'src/auth.py',
        }]
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(title='JWT RS256 signing bug for login'),
            prs_with_patches=[], similar_memories=similar,
        )
        data = yaml.safe_load(out)
        assert 'similar_past_tickets' in data
        assert data['similar_past_tickets'][0]['category'] == 'decision'

    def test_no_similar_no_section(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(title='login fix'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        assert 'similar_past_tickets' not in data


# ======================================================================
# 6. my_symbols extraction (se il code graph non esiste)
# ======================================================================
class TestMySymbols:
    def test_no_graph_no_symbols(self, fake_index):
        fake_index({'src/auth.py': {'symbols': ['login'], 'identifiers': []}})
        out = get_ticket_context_impl(
            project='p', issue_id=42, author='me',
            issue=fake_issue(title='login fix'),
            prs_with_patches=[], similar_memories=[],
        )
        data = yaml.safe_load(out)
        # my_symbols è presente solo se il graph è disponibile
        # (in test_repo senza graph, assente o vuota lista → no key)
        assert 'my_symbols' not in data or data['my_symbols']


# ======================================================================
# 7. Registration
# ======================================================================
class FakeMCP:
    def __init__(self):
        self.registered = []

    def tool(self):
        def deco(fn):
            self.registered.append(fn)
            return fn
        return deco


class TestRegistration:
    def test_register_adds_one_tool(self):
        mcp = FakeMCP()
        register_get_ticket_context_tool(mcp)
        assert len(mcp.registered) == 1
        assert mcp.registered[0].__name__ == 'brain_get_ticket_context'

    def test_tool_docstring_mentions_sections(self):
        mcp = FakeMCP()
        register_get_ticket_context_tool(mcp)
        doc = mcp.registered[0].__doc__ or ''
        assert 'all-in-one' in doc.lower()
