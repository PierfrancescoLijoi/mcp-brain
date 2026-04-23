"""Test STEP 3 — tool MCP brain_check_conflicts_v2."""
import yaml
import pytest

from src.tools.conflict_tool_v2 import (
    check_conflicts_v2_impl,
    register_check_conflicts_v2_tool,
)


# ----------------------------------------------------------------------
# Helpers (replicati da test_conflict_detector_v2 per indipendenza)
# ----------------------------------------------------------------------
def make_pr(number, author, title, files_patches):
    return {
        'number': number,
        'author': author,
        'title': title,
        'files_with_patches': [
            {'filename': fn, 'status': 'modified', 'patch': p}
            for fn, p in files_patches
        ],
    }


def sig_patch(fn='foo'):
    return (
        f"@@ -10,3 +10,3 @@ def {fn}(a):\n"
        f"-def {fn}(a):\n"
        f"+def {fn}(a, b):\n"
        f"     return a\n"
    )


def body_patch(fn='foo'):
    return (
        f"@@ -10,3 +10,3 @@ def {fn}(a):\n"
        f" def {fn}(a):\n"
        f"-    return 1\n"
        f"+    return 2\n"
    )


# ======================================================================
# check_conflicts_v2_impl
# ======================================================================
class TestImpl:
    def test_no_prs_returns_no_conflicts(self):
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=[], prs_with_patches=[]
        )
        data = yaml.safe_load(out)
        assert data['conflicts'] == []
        assert 'safe to proceed' in data['guidance'].lower()

    def test_signature_conflict_yaml_structure(self):
        prs = [make_pr(42, 'bob', 'refactor', [('f.py', sig_patch('foo'))])]
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=[], prs_with_patches=prs
        )
        data = yaml.safe_load(out)
        assert 'signature' in data
        assert data['signature'][0]['pr'] == 42
        assert 'signature_changes' in data['signature'][0]
        assert 'block' in data['guidance'].lower()

    def test_hard_conflict_groups_correctly(self):
        prs = [make_pr(7, 'alice', 'opt', [('f.py', body_patch('login'))])]
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=['login'], prs_with_patches=prs
        )
        data = yaml.safe_load(out)
        assert 'hard' in data
        assert 'signature' not in data
        assert data['hard'][0]['pr'] == 7
        assert 'caution' in data['guidance'].lower()

    def test_mixed_severity_all_groups(self):
        prs = [
            make_pr(1, 'a', 'soft', [('f.py', body_patch('other'))]),
            make_pr(2, 'b', 'hard', [('f.py', body_patch('login'))]),
            make_pr(3, 'c', 'sig', [('f.py', sig_patch('login'))]),
        ]
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=['login'], prs_with_patches=prs
        )
        data = yaml.safe_load(out)
        assert 'signature' in data
        assert 'hard' in data
        assert 'soft' in data

    def test_exclude_author(self):
        prs = [
            make_pr(1, 'me', 'own', [('f.py', sig_patch('x'))]),
            make_pr(2, 'other', 'theirs', [('f.py', sig_patch('y'))]),
        ]
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=[], exclude_author='me', prs_with_patches=prs
        )
        data = yaml.safe_load(out)
        sig_prs = [c['pr'] for c in data.get('signature', [])]
        assert 1 not in sig_prs
        assert 2 in sig_prs

    def test_no_matching_files(self):
        prs = [make_pr(1, 'x', 't', [('other.py', sig_patch('x'))])]
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=[], prs_with_patches=prs
        )
        data = yaml.safe_load(out)
        assert data['conflicts'] == []

    def test_handles_none_symbols(self):
        # symbols=None deve essere gestito come lista vuota
        out = check_conflicts_v2_impl(
            files=['f.py'], symbols=None, prs_with_patches=[]
        )
        data = yaml.safe_load(out)
        assert isinstance(data, dict)


# ======================================================================
# Tool registration
# ======================================================================
class FakeMCP:
    def __init__(self):
        self.registered = []

    def tool(self):
        def decorator(fn):
            self.registered.append(fn)
            return fn
        return decorator


class TestRegistration:
    def test_register_adds_tool(self):
        mcp = FakeMCP()
        register_check_conflicts_v2_tool(mcp)
        assert len(mcp.registered) == 1
        assert mcp.registered[0].__name__ == 'brain_check_conflicts_v2'

    def test_tool_has_docstring(self):
        mcp = FakeMCP()
        register_check_conflicts_v2_tool(mcp)
        assert mcp.registered[0].__doc__
        assert 'signature' in mcp.registered[0].__doc__.lower()

    def test_tool_invocation_without_github_token(self, monkeypatch):
        """Senza GITHUB_TOKEN la chiamata reale non deve crashare."""
        monkeypatch.delenv('GITHUB_TOKEN', raising=False)
        # Pulisci la cache
        from src.capture import github_pr_patches
        github_pr_patches.clear_cache()

        mcp = FakeMCP()
        register_check_conflicts_v2_tool(mcp)
        result = mcp.registered[0](
            project='demo', files=['src/auth.py'], symbols=['login']
        )
        assert isinstance(result, str)
        # Senza token: nessuna PR → no conflicts
        data = yaml.safe_load(result)
        assert data.get('conflicts') == [] or 'signature' not in data
