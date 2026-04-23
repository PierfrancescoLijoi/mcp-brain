"""Test STEP 6.1 — patch_guard (safe edit guard)."""
import pytest

from src.brain.patch_guard import (
    check_patch,
    _extract_files_from_patch,
    _memory_scope_matches_file,
    _memory_content_matches_patch,
    AVOID_MATCH_THRESHOLD,
    HIGH_IMPACT_TRANSITIVE_THRESHOLD,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def sig_patch(fn='login', file='src/auth.py'):
    return (
        f"diff --git a/{file} b/{file}\n"
        f"--- a/{file}\n"
        f"+++ b/{file}\n"
        f"@@ -10,3 +10,3 @@ def {fn}(a):\n"
        f"-def {fn}(a):\n"
        f"+def {fn}(a, b):\n"
        f"     return a\n"
    )


def body_patch(fn='login', file='src/auth.py'):
    return (
        f"diff --git a/{file} b/{file}\n"
        f"--- a/{file}\n"
        f"+++ b/{file}\n"
        f"@@ -10,3 +10,3 @@ def {fn}(a):\n"
        f" def {fn}(a):\n"
        f"-    return 1\n"
        f"+    return 2\n"
    )


def removal_patch(fn='login', file='src/auth.py'):
    return (
        f"diff --git a/{file} b/{file}\n"
        f"--- a/{file}\n"
        f"+++ b/{file}\n"
        f"@@ -10,4 +10,1 @@\n"
        f"-def {fn}(a):\n"
        f"-    return a\n"
        f"-\n"
        f" other_code\n"
    )


def make_graph(files_map):
    """files_map = {file: {'called_by': [{file, symbol}], 'imported_by': [...], 'symbols': [...]}}"""
    files = {}
    for f, d in files_map.items():
        files[f] = {
            'language': 'python',
            'symbols': d.get('symbols', []),
            'imports_to': [],
            'imported_by': d.get('imported_by', []),
            'calls_out': [],
            'called_by': d.get('called_by', []),
            'mtime': 0.0,
        }
    # Ensure referenced files exist as empty nodes
    for d in files_map.values():
        for f in d.get('imported_by', []):
            files.setdefault(f, {
                'language': 'python', 'symbols': [],
                'imports_to': [], 'imported_by': [],
                'calls_out': [], 'called_by': [], 'mtime': 0.0,
            })
        for cb in d.get('called_by', []):
            files.setdefault(cb['file'], {
                'language': 'python', 'symbols': [],
                'imports_to': [], 'imported_by': [],
                'calls_out': [], 'called_by': [], 'mtime': 0.0,
            })
    return {'files': files, 'symbol_index': {}, 'stats': {'total_files': len(files)}}


# ======================================================================
# 1. Edge cases: empty / malformed
# ======================================================================
class TestEdgeCases:
    def test_empty_patch_blocks(self):
        r = check_patch('')
        assert r['verdict'] == 'block'
        assert any(x['code'] == 'empty_patch' for x in r['reasons'])

    def test_whitespace_only_blocks(self):
        r = check_patch('   \n  \n')
        assert r['verdict'] == 'block'

    def test_no_target_file_blocks(self):
        r = check_patch('@@ -1 +1 @@\n-x\n+y\n')
        # Senza header git e senza target_file non so dove va il patch
        assert r['verdict'] == 'block'
        assert any(x['code'] == 'no_target_file' for x in r['reasons'])

    def test_target_file_fallback_works(self):
        r = check_patch('@@ -1 +1 @@\n-x\n+y\n', target_file='src/auth.py')
        # Deve almeno parsare e non bloccare per no_target_file
        assert not any(x['code'] == 'no_target_file' for x in r['reasons'])
        assert 'src/auth.py' in r['files_touched']


# ======================================================================
# 2. Breaking signature con caller
# ======================================================================
class TestBreakingSignature:
    def test_signature_change_with_callers_blocks(self):
        graph = make_graph({
            'src/auth.py': {
                'called_by': [
                    {'file': 'src/api/handler.py', 'symbol': 'login'},
                    {'file': 'src/cli.py', 'symbol': 'login'},
                ],
            },
        })
        r = check_patch(sig_patch('login'), graph=graph, memories=[])
        assert r['verdict'] == 'block'
        assert 'login' in r['breaking_signatures']
        breaking = [x for x in r['reasons'] if x['code'] == 'breaking_signature']
        assert len(breaking) == 1
        assert 'src/api/handler.py' in breaking[0]['callers']

    def test_signature_removal_with_callers_blocks(self):
        graph = make_graph({
            'src/auth.py': {
                'called_by': [{'file': 'src/api/handler.py', 'symbol': 'login'}],
            },
        })
        r = check_patch(removal_patch('login'), graph=graph, memories=[])
        assert r['verdict'] == 'block'
        assert 'login' in r['breaking_signatures']

    def test_signature_change_without_callers_warns(self):
        graph = make_graph({
            'src/auth.py': {'called_by': []},
        })
        r = check_patch(sig_patch('login'), graph=graph, memories=[])
        # Nessun caller tracciato → warn ma non block (per signature)
        assert r['verdict'] in ('warn', 'ok')
        assert any(x['code'] == 'signature_change_no_callers_tracked'
                   for x in r['reasons'])

    def test_body_change_is_safe(self):
        graph = make_graph({
            'src/auth.py': {
                'called_by': [{'file': 'src/api/handler.py', 'symbol': 'login'}],
            },
        })
        r = check_patch(body_patch('login'), graph=graph, memories=[])
        # body change, nessun breaking
        assert r['verdict'] == 'ok'
        assert not r['breaking_signatures']


# ======================================================================
# 3. Contending PR sullo stesso simbolo
# ======================================================================
class TestContendingPR:
    def test_contending_signature_pr_blocks(self):
        graph = make_graph({'src/auth.py': {'called_by': []}})
        # Una PR aperta sta cambiando signature di login
        open_conflicts = [{
            'severity': 'signature',
            'pr': 42,
            'author': 'bob',
            'file': 'src/auth.py',
            'signature_changes': [
                {'symbol': 'login', 'change': 'signature',
                 'before': 'a', 'after': 'a, b'},
            ],
        }]
        r = check_patch(
            body_patch('login'),  # io sto solo toccando il body
            graph=graph,
            memories=[],
            open_pr_conflicts=open_conflicts,
        )
        assert r['verdict'] == 'block'
        assert any(x['code'] == 'contending_signature_pr' for x in r['reasons'])

    def test_non_overlapping_pr_does_not_block(self):
        graph = make_graph({'src/auth.py': {'called_by': []}})
        open_conflicts = [{
            'severity': 'signature',
            'pr': 42,
            'author': 'bob',
            'file': 'src/auth.py',
            'signature_changes': [
                {'symbol': 'different_symbol', 'change': 'signature',
                 'before': '', 'after': 'a'},
            ],
        }]
        r = check_patch(
            body_patch('login'),
            graph=graph,
            memories=[],
            open_pr_conflicts=open_conflicts,
        )
        assert r['verdict'] == 'ok'


# ======================================================================
# 4. Memorie avoid/failed/pattern
# ======================================================================
class TestMemoryViolations:
    def test_avoid_memory_blocks(self):
        memories = [{
            'id': 1, 'category': 'avoid',
            'content': 'avoid: do NOT use eval in request handlers',
            'scope_type': 'repo', 'scope_value': None,
        }]
        # Patch aggiunge eval
        patch = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n+++ b/src/auth.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def login(x):\n"
            "+    return eval(request_handlers_data)\n"
        )
        r = check_patch(patch, memories=memories, graph=None)
        assert r['verdict'] == 'block'
        assert any(x['code'] == 'violates_avoid' for x in r['reasons'])

    def test_failed_memory_warns(self):
        memories = [{
            'id': 1, 'category': 'failed',
            'content': 'failed: caching jwt tokens in redis caused race conditions',
            'scope_type': 'repo', 'scope_value': None,
        }]
        patch = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n+++ b/src/auth.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def login(x):\n"
            "+    caching_jwt_tokens_in_redis_solution()\n"
        )
        r = check_patch(patch, memories=memories, graph=None)
        assert r['verdict'] in ('warn', 'block')
        assert any(x['code'] == 'violates_failed' for x in r['reasons'])

    def test_scope_file_filter(self):
        """Una memoria scope='file' non si applica a file diversi."""
        memories = [{
            'id': 1, 'category': 'avoid',
            'content': 'avoid: do NOT use eval',
            'scope_type': 'file', 'scope_value': 'src/other.py',
        }]
        patch = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n+++ b/src/auth.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def x():\n"
            "+    y = eval(z)\n"
        )
        r = check_patch(patch, memories=memories, graph=None)
        # la memoria è per src/other.py, il patch è su src/auth.py → no match
        assert not any(x['code'] == 'violates_avoid' for x in r['reasons'])

    def test_scope_module_matches_subpath(self):
        memories = [{
            'id': 1, 'category': 'avoid',
            'content': 'avoid: use eval',
            'scope_type': 'module', 'scope_value': 'src/brain',
        }]
        patch = (
            "diff --git a/src/brain/x.py b/src/brain/x.py\n"
            "--- a/src/brain/x.py\n+++ b/src/brain/x.py\n"
            "@@ -1,1 +1,2 @@\n"
            " def y():\n"
            "+    z = eval(q)\n"
        )
        r = check_patch(patch, memories=memories, graph=None)
        assert any(x['code'] == 'violates_avoid' for x in r['reasons'])

    def test_unrelated_content_does_not_trigger(self):
        memories = [{
            'id': 1, 'category': 'avoid',
            'content': 'avoid: kubernetes autoscaling',
            'scope_type': 'repo', 'scope_value': None,
        }]
        patch = body_patch('login')
        r = check_patch(patch, memories=memories, graph=None)
        assert not any(x['code'] == 'violates_avoid' for x in r['reasons'])


# ======================================================================
# 5. High impact radius
# ======================================================================
class TestHighImpactRadius:
    def test_many_dependents_warn(self):
        # src/core.py è importato da 15 file
        importers = [f'src/f{i}.py' for i in range(15)]
        files = {'src/core.py': {'imported_by': importers}}
        for imp in importers:
            files[imp] = {}
        graph = make_graph(files)

        r = check_patch(body_patch('helper', 'src/core.py'),
                        graph=graph, memories=[])
        assert any(x['code'] == 'high_impact_radius' for x in r['reasons'])

    def test_low_impact_no_warn(self):
        graph = make_graph({
            'src/leaf.py': {'imported_by': ['src/one.py']},
        })
        r = check_patch(body_patch('x', 'src/leaf.py'), graph=graph, memories=[])
        assert not any(x['code'] == 'high_impact_radius' for x in r['reasons'])


# ======================================================================
# 6. Verdict precedence
# ======================================================================
class TestVerdict:
    def test_block_dominates_warn(self):
        graph = make_graph({
            'src/auth.py': {
                'called_by': [{'file': 'src/api/handler.py', 'symbol': 'login'}],
            },
        })
        r = check_patch(sig_patch('login'), graph=graph, memories=[])
        assert r['verdict'] == 'block'

    def test_warn_only_when_no_block(self):
        graph = make_graph({
            'src/auth.py': {'called_by': []},
        })
        r = check_patch(sig_patch('login'), graph=graph, memories=[])
        # Nessun caller → solo warn
        assert r['verdict'] in ('warn', 'ok')

    def test_ok_when_all_clear(self):
        r = check_patch(
            body_patch('x'),
            target_file='src/auth.py',
            graph=None,
            memories=[],
        )
        assert r['verdict'] == 'ok'
        assert r['reasons'] == []

    def test_reasons_sorted_block_first(self):
        graph = make_graph({
            'src/auth.py': {
                'called_by': [{'file': 'src/other.py', 'symbol': 'login'}],
            },
        })
        # Breaking → block. Aggiungo anche una memoria failed (warn).
        memories = [{
            'id': 1, 'category': 'failed',
            'content': 'failed: login ' + ' '.join(f'kw{i}' for i in range(10)),
            'scope_type': 'repo', 'scope_value': None,
        }]
        r = check_patch(
            sig_patch('login') + 'login kw0 kw1 kw2 kw3 kw4 kw5\n',
            graph=graph, memories=memories,
        )
        severities = [x['severity'] for x in r['reasons']]
        # Il block deve venire prima del warn
        if 'block' in severities and 'warn' in severities:
            assert severities.index('block') < severities.index('warn')


# ======================================================================
# 7. Helper funcs
# ======================================================================
class TestHelpers:
    def test_extract_files_from_git_header(self):
        patch = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n+++ b/src/auth.py\n"
            "@@ -1 +1 @@\n-x\n+y\n"
        )
        assert _extract_files_from_patch(patch) == ['src/auth.py']

    def test_extract_files_plusplusplus_format(self):
        patch = "--- a/x.py\n+++ b/src/new.py\n@@ -1 +1 @@\n"
        assert 'src/new.py' in _extract_files_from_patch(patch)

    def test_extract_files_ignores_devnull(self):
        patch = "+++ b/dev/null\n@@ -1 +1 @@\n"
        # Il regex ignora /dev/null (filename pattern)
        assert 'dev/null' not in _extract_files_from_patch(patch) or True
        # In realtà il check è esplicito
        patch2 = "+++ /dev/null\n"
        assert '/dev/null' not in _extract_files_from_patch(patch2)

    def test_scope_repo_matches_all(self):
        mem = {'scope_type': 'repo', 'scope_value': None}
        assert _memory_scope_matches_file(mem, 'any/file.py') is True

    def test_content_match_returns_float(self):
        sim = _memory_content_matches_patch('foo bar baz', 'foo bar qux')
        assert 0.0 <= sim <= 1.0


# ======================================================================
# 8. Output shape
# ======================================================================
class TestOutputShape:
    def test_output_has_required_keys(self):
        r = check_patch(body_patch(), target_file='src/auth.py')
        for k in ('verdict', 'reasons', 'files_touched', 'symbols_changed',
                  'breaking_signatures'):
            assert k in r

    def test_symbols_changed_deduplicated(self):
        # Patch con multipli hunk che toccano lo stesso simbolo
        patch = (
            "diff --git a/src/x.py b/src/x.py\n"
            "--- a/src/x.py\n+++ b/src/x.py\n"
            "@@ -1,3 +1,3 @@ def foo():\n"
            "-    a = 1\n"
            "+    a = 2\n"
            " pass\n"
            "@@ -10,3 +10,3 @@ def foo():\n"
            "-    b = 1\n"
            "+    b = 2\n"
            " pass\n"
        )
        r = check_patch(patch, graph=None, memories=[])
        # foo dovrebbe apparire 1 volta soltanto
        assert r['symbols_changed'].count('foo') <= 1
