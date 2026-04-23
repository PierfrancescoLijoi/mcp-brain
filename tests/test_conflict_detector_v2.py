"""Test STEP 3.3 — graduated conflict detection."""
import pytest

from src.brain.conflict_detector_v2 import (
    analyze_pr_file,
    detect_graduated_conflicts,
    build_graduated_warnings,
    guidance_from_conflicts,
)


# ----------------------------------------------------------------------
# Helpers: build fake PR structures
# ----------------------------------------------------------------------
def make_pr(number, author, title, files_patches):
    """files_patches = [(filename, patch_text), ...]"""
    return {
        'number': number,
        'author': author,
        'title': title,
        'files_with_patches': [
            {'filename': fn, 'status': 'modified', 'patch': p}
            for fn, p in files_patches
        ],
    }


def py_patch_param_added(func_name='foo'):
    """Patch che cambia la signature di foo() aggiungendo un parametro."""
    return (
        f"@@ -10,3 +10,3 @@ def {func_name}(a):\n"
        f"-def {func_name}(a):\n"
        f"+def {func_name}(a, b):\n"
        f"     return a\n"
    )


def py_patch_body_change(func_name='foo'):
    """Patch che NON cambia la signature, solo il body di foo()."""
    return (
        f"@@ -10,3 +10,3 @@ def {func_name}(a):\n"
        f" def {func_name}(a):\n"
        f"-    return a\n"
        f"+    return a * 2\n"
    )


def py_patch_unrelated_region(func_name='unrelated'):
    """Patch su una funzione diversa."""
    return (
        f"@@ -50,3 +50,3 @@ def {func_name}():\n"
        f" def {func_name}():\n"
        f"-    x = 1\n"
        f"+    x = 2\n"
    )


# ======================================================================
# 1. analyze_pr_file
# ======================================================================
class TestAnalyzePRFile:
    def test_extracts_signature_change(self):
        r = analyze_pr_file('src/auth.py', py_patch_param_added('login'))
        assert any(s['symbol'] == 'login' and s['change'] == 'signature'
                   for s in r['signature_changes'])

    def test_body_change_not_signature(self):
        r = analyze_pr_file('src/auth.py', py_patch_body_change('login'))
        # Il body change non deve produrre signature_changes di tipo 'signature'
        sig_only = [s for s in r['signature_changes'] if s['change'] == 'signature']
        assert sig_only == []

    def test_touched_symbols_from_context(self):
        r = analyze_pr_file('src/auth.py', py_patch_body_change('login'))
        assert 'login' in r['touched_symbols']

    def test_unknown_language_no_crash(self):
        r = analyze_pr_file('bin/tool', "@@ -1 +1 @@\n-old\n+new\n")
        assert r['file'] == 'bin/tool'
        assert r['signature_changes'] == []


# ======================================================================
# 2. detect_graduated_conflicts — severity
# ======================================================================
class TestSeverity:
    def test_signature_severity(self):
        prs = [
            make_pr(42, 'bob', 'refactor login',
                    [('src/auth.py', py_patch_param_added('login'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['src/auth.py'],
            my_symbols=[],
            open_prs_with_patches=prs,
        )
        assert len(conflicts) == 1
        assert conflicts[0]['severity'] == 'signature'
        assert conflicts[0]['pr'] == 42

    def test_hard_severity_same_symbol(self):
        prs = [
            make_pr(7, 'alice', 'optimize login',
                    [('src/auth.py', py_patch_body_change('login'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['src/auth.py'],
            my_symbols=['login'],  # io voglio toccare login
            open_prs_with_patches=prs,
        )
        assert len(conflicts) == 1
        assert conflicts[0]['severity'] == 'hard'
        assert 'login' in conflicts[0]['overlapping_symbols']

    def test_soft_severity_different_region(self):
        prs = [
            make_pr(3, 'carl', 'tweak utilities',
                    [('src/auth.py', py_patch_unrelated_region('helper'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['src/auth.py'],
            my_symbols=['login'],
            open_prs_with_patches=prs,
        )
        assert len(conflicts) == 1
        assert conflicts[0]['severity'] == 'soft'

    def test_no_overlap_no_conflict(self):
        prs = [
            make_pr(1, 'x', 'other file',
                    [('src/unrelated.py', py_patch_body_change('foo'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['src/auth.py'],
            my_symbols=['login'],
            open_prs_with_patches=prs,
        )
        assert conflicts == []

    def test_signature_trumps_hard(self):
        """Se una PR cambia signature E tocca il simbolo, severity=signature."""
        prs = [
            make_pr(42, 'bob', 'refactor login',
                    [('src/auth.py', py_patch_param_added('login'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['src/auth.py'],
            my_symbols=['login'],
            open_prs_with_patches=prs,
        )
        assert conflicts[0]['severity'] == 'signature'

    def test_added_function_is_not_signature_conflict(self):
        """Aggiungere una funzione nuova NON è un conflict."""
        patch = (
            "@@ -20,0 +21,3 @@\n"
            "+def new_helper():\n"
            "+    return 42\n"
        )
        prs = [make_pr(10, 'bob', 'add helper', [('src/auth.py', patch)])]
        conflicts = detect_graduated_conflicts(
            my_files=['src/auth.py'],
            my_symbols=[],
            open_prs_with_patches=prs,
        )
        # severity dovrebbe essere 'soft' (tocca il file ma nessun conflict)
        assert len(conflicts) == 1
        assert conflicts[0]['severity'] != 'signature'


# ======================================================================
# 3. ordering + exclude_author
# ======================================================================
class TestOrderingAndFilters:
    def test_sorted_by_severity_desc(self):
        prs = [
            make_pr(1, 'a', 'soft', [('f.py', py_patch_unrelated_region('other'))]),
            make_pr(2, 'b', 'hard', [('f.py', py_patch_body_change('login'))]),
            make_pr(3, 'c', 'sig', [('f.py', py_patch_param_added('login'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['f.py'],
            my_symbols=['login'],
            open_prs_with_patches=prs,
        )
        severities = [c['severity'] for c in conflicts]
        # signature > hard > soft
        assert severities == ['signature', 'hard', 'soft']

    def test_exclude_author_filters_own_prs(self):
        prs = [
            make_pr(10, 'me', 'my own PR',
                    [('f.py', py_patch_param_added('x'))]),
            make_pr(11, 'other', 'other PR',
                    [('f.py', py_patch_param_added('y'))]),
        ]
        conflicts = detect_graduated_conflicts(
            my_files=['f.py'],
            my_symbols=[],
            open_prs_with_patches=prs,
            exclude_author='me',
        )
        assert len(conflicts) == 1
        assert conflicts[0]['pr'] == 11

    def test_empty_prs_no_conflicts(self):
        assert detect_graduated_conflicts(['f.py'], ['login'], []) == []

    def test_none_prs_no_crash(self):
        assert detect_graduated_conflicts(['f.py'], ['login'], None) == []


# ======================================================================
# 4. warnings + guidance
# ======================================================================
class TestWarningsAndGuidance:
    def test_build_graduated_warnings_compact(self):
        prs = [
            make_pr(42, 'bob', 'refactor',
                    [('src/auth.py', py_patch_param_added('login'))]),
        ]
        conflicts = detect_graduated_conflicts(['src/auth.py'], [], prs)
        warnings = build_graduated_warnings(conflicts)
        assert len(warnings) == 1
        w = warnings[0]
        for k in ('severity', 'pr', 'author', 'file', 'message'):
            assert k in w
        # Signature warnings includono signature_changes
        assert 'signature_changes' in w

    def test_guidance_no_conflicts(self):
        assert 'safe to proceed' in guidance_from_conflicts([]).lower()

    def test_guidance_signature_is_block(self):
        conflicts = [{'severity': 'signature'}]
        assert 'block' in guidance_from_conflicts(conflicts).lower()

    def test_guidance_hard_is_caution(self):
        conflicts = [{'severity': 'hard'}]
        assert 'caution' in guidance_from_conflicts(conflicts).lower()

    def test_guidance_soft_is_note(self):
        conflicts = [{'severity': 'soft'}]
        assert 'note' in guidance_from_conflicts(conflicts).lower()
