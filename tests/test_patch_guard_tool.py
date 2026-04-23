"""Test STEP 6.1 — tool MCP brain_check_patch."""
import yaml
import pytest

from src.tools.patch_guard_tool import (
    check_patch_impl,
    register_check_patch_tool,
)


def body_patch():
    return (
        "diff --git a/src/auth.py b/src/auth.py\n"
        "--- a/src/auth.py\n+++ b/src/auth.py\n"
        "@@ -1,2 +1,2 @@\n def login(x):\n-    return 1\n+    return 2\n"
    )


def sig_patch():
    return (
        "diff --git a/src/auth.py b/src/auth.py\n"
        "--- a/src/auth.py\n+++ b/src/auth.py\n"
        "@@ -1,3 +1,3 @@ def login(a):\n-def login(a):\n+def login(a, b):\n     return a\n"
    )


# ======================================================================
# Impl (pure)
# ======================================================================
class TestImpl:
    def test_empty_patch_blocks(self):
        out = check_patch_impl('', project='p')
        data = yaml.safe_load(out)
        assert data['verdict'] == 'block'
        assert 'action' in data

    def test_body_patch_is_ok_without_graph(self, tmp_brain):
        out = check_patch_impl(body_patch(), project='p')
        data = yaml.safe_load(out)
        assert data['verdict'] == 'ok'
        assert 'Safe to apply' in data['action']

    def test_yaml_has_expected_keys(self, tmp_brain):
        out = check_patch_impl(body_patch(), project='p')
        data = yaml.safe_load(out)
        for k in ('verdict', 'files_touched', 'symbols_changed', 'action'):
            assert k in data

    def test_blocking_avoid_memory_surfaces(self, tmp_brain):
        """Se inseriamo una memoria 'avoid' pertinente, il check_patch la trova."""
        from src.storage.db import save_memory
        save_memory('p', 1, 'avoid',
                    'avoid: do NOT use eval in request handlers',
                    status='active')
        patch = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n+++ b/src/auth.py\n"
            "@@ -1,1 +1,2 @@\n def login(x):\n"
            "+    return eval(request_handlers_payload)\n"
        )
        out = check_patch_impl(patch, project='p')
        data = yaml.safe_load(out)
        assert data['verdict'] == 'block'
        assert 'block' in data
        assert any('violates_avoid' == r['code'] for r in data['block'])

    def test_signature_change_without_graph_may_warn(self, tmp_brain):
        """Senza graph non ci sono caller: signature change ≠ block."""
        out = check_patch_impl(sig_patch(), project='p')
        data = yaml.safe_load(out)
        # Senza graph: no block per breaking_signature (nessun caller tracciato)
        assert data['verdict'] in ('ok', 'warn')

    def test_handles_bad_input_gracefully(self, tmp_brain):
        out = check_patch_impl('not a real patch', project='p')
        data = yaml.safe_load(out)
        # Il patch non ha file target → block con ragione chiara
        assert data['verdict'] == 'block'


# ======================================================================
# Registration
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
    def test_registers_one_tool(self):
        mcp = FakeMCP()
        register_check_patch_tool(mcp)
        assert len(mcp.registered) == 1
        assert mcp.registered[0].__name__ == 'brain_check_patch'

    def test_tool_docstring_mentions_guard(self):
        mcp = FakeMCP()
        register_check_patch_tool(mcp)
        doc = mcp.registered[0].__doc__ or ''
        assert 'patch' in doc.lower() or 'guard' in doc.lower()

    def test_tool_returns_yaml_string(self, tmp_brain):
        mcp = FakeMCP()
        register_check_patch_tool(mcp)
        fn = mcp.registered[0]
        result = fn(project='p', patch=body_patch())
        # non crash, è una stringa YAML parsabile
        data = yaml.safe_load(result)
        assert 'verdict' in data
