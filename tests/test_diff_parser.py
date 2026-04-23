"""Test STEP 3.1 / 3.2 — unified diff parser + signature detection."""
import pytest

from src.brain.diff_parser import (
    Hunk,
    parse_unified_diff,
    detect_signature_changes,
    get_touched_symbols,
)


# ----------------------------------------------------------------------
# 1. parse_unified_diff
# ----------------------------------------------------------------------
class TestParseUnifiedDiff:
    def test_single_file_with_git_header(self):
        patch = (
            "diff --git a/src/auth.py b/src/auth.py\n"
            "index abc..def 100644\n"
            "--- a/src/auth.py\n"
            "+++ b/src/auth.py\n"
            "@@ -10,7 +10,7 @@ def login(user):\n"
            " context line 1\n"
            "-    old_line = 1\n"
            "+    new_line = 2\n"
            " context line 2\n"
        )
        hunks = parse_unified_diff(patch)
        assert len(hunks) == 1
        h = hunks[0]
        assert h.file == 'src/auth.py'
        assert h.old_start == 10 and h.old_count == 7
        assert h.new_start == 10 and h.new_count == 7
        assert h.added == ['    new_line = 2']
        assert h.removed == ['    old_line = 1']
        assert 'def login' in h.context_header

    def test_patch_without_git_header_uses_fallback(self):
        patch = (
            "@@ -1,3 +1,4 @@\n"
            " x = 1\n"
            "+y = 2\n"
            " z = 3\n"
        )
        hunks = parse_unified_diff(patch, fallback_file='myfile.py')
        assert len(hunks) == 1
        assert hunks[0].file == 'myfile.py'
        assert hunks[0].added == ['y = 2']

    def test_multiple_hunks_same_file(self):
        patch = (
            "diff --git a/f.py b/f.py\n"
            "@@ -1,3 +1,3 @@\n"
            "-a\n"
            "+A\n"
            " b\n"
            "@@ -10,3 +10,3 @@\n"
            "-c\n"
            "+C\n"
            " d\n"
        )
        hunks = parse_unified_diff(patch)
        assert len(hunks) == 2
        assert hunks[0].new_start == 1 and hunks[1].new_start == 10
        assert all(h.file == 'f.py' for h in hunks)

    def test_short_hunk_header_counts_default_to_1(self):
        # Formato "@@ -N +M @@" senza count
        patch = (
            "--- a/f.py\n+++ b/f.py\n"
            "@@ -5 +5 @@\n"
            "-old\n+new\n"
        )
        hunks = parse_unified_diff(patch, fallback_file='f.py')
        assert hunks[0].old_count == 1
        assert hunks[0].new_count == 1

    def test_plus_plus_plus_lines_not_counted_as_added(self):
        patch = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-x\n"
            "+y\n"
        )
        hunks = parse_unified_diff(patch)
        assert hunks[0].added == ['y']
        assert hunks[0].removed == ['x']

    def test_empty_patch(self):
        assert parse_unified_diff('') == []
        assert parse_unified_diff(None) == []

    def test_no_hunks_only_headers(self):
        patch = "diff --git a/a b/a\nindex 1..2\n--- a/a\n+++ b/a\n"
        assert parse_unified_diff(patch) == []


# ----------------------------------------------------------------------
# 2. detect_signature_changes
# ----------------------------------------------------------------------
class TestDetectSignatureChangesPython:
    def _mk_hunk(self, removed, added, file='f.py'):
        return Hunk(
            file=file, old_start=1, old_count=5, new_start=1, new_count=5,
            removed=removed, added=added,
        )

    def test_param_added_is_signature_change(self):
        h = self._mk_hunk(
            removed=['def foo(a):'],
            added=['def foo(a, b):'],
        )
        changes = detect_signature_changes(h, language='python')
        assert len(changes) == 1
        assert changes[0]['symbol'] == 'foo'
        assert changes[0]['change'] == 'signature'
        assert changes[0]['before'] == 'a'
        assert changes[0]['after'] == 'a, b'

    def test_param_renamed_is_signature_change(self):
        h = self._mk_hunk(
            removed=['def foo(old_name):'],
            added=['def foo(new_name):'],
        )
        changes = detect_signature_changes(h, language='python')
        assert len(changes) == 1
        assert changes[0]['change'] == 'signature'

    def test_function_removed(self):
        h = self._mk_hunk(
            removed=['def foo(x):'],
            added=[],
        )
        changes = detect_signature_changes(h, language='python')
        assert len(changes) == 1
        assert changes[0]['change'] == 'removed'
        assert changes[0]['symbol'] == 'foo'

    def test_function_added(self):
        h = self._mk_hunk(
            removed=[],
            added=['def bar(x):'],
        )
        changes = detect_signature_changes(h, language='python')
        assert len(changes) == 1
        assert changes[0]['change'] == 'added'

    def test_identical_signature_no_change(self):
        # Stesso simbolo con stessi params in removed e added → non change
        h = self._mk_hunk(
            removed=['def foo(a, b):', '    x = 1'],
            added=['def foo(a, b):', '    x = 2'],
        )
        changes = detect_signature_changes(h, language='python')
        assert changes == []

    def test_async_function_detected(self):
        h = self._mk_hunk(
            removed=['async def fetch(url):'],
            added=['async def fetch(url, timeout):'],
        )
        changes = detect_signature_changes(h, language='python')
        assert len(changes) == 1
        assert changes[0]['symbol'] == 'fetch'

    def test_class_signature_change(self):
        h = self._mk_hunk(
            removed=['class Foo(Base):'],
            added=['class Foo(Base, Mixin):'],
        )
        changes = detect_signature_changes(h, language='python')
        # class match con base class cambiata
        assert any(c['symbol'] == 'Foo' and c['change'] == 'signature' for c in changes)


class TestDetectSignatureChangesJS:
    def _mk_hunk(self, removed, added):
        return Hunk(
            file='f.js', old_start=1, old_count=5, new_start=1, new_count=5,
            removed=removed, added=added,
        )

    def test_function_signature_change(self):
        h = self._mk_hunk(
            removed=['function validate(token) {'],
            added=['function validate(token, opts) {'],
        )
        changes = detect_signature_changes(h, language='javascript')
        assert len(changes) == 1
        assert changes[0]['symbol'] == 'validate'
        assert changes[0]['change'] == 'signature'

    def test_export_async_function(self):
        h = self._mk_hunk(
            removed=['export async function fetch(u) {'],
            added=['export async function fetch(u, t) {'],
        )
        changes = detect_signature_changes(h, language='javascript')
        assert any(c['symbol'] == 'fetch' for c in changes)


# ----------------------------------------------------------------------
# 3. get_touched_symbols
# ----------------------------------------------------------------------
class TestGetTouchedSymbols:
    def test_from_context_header(self):
        h = Hunk(
            file='f.py', old_start=10, old_count=5, new_start=10, new_count=5,
            added=['    x = 2'], removed=['    x = 1'],
            context_header='def login(user):',
        )
        syms = get_touched_symbols(h, language='python')
        assert 'login' in syms

    def test_from_added_lines(self):
        h = Hunk(
            file='f.py', old_start=1, old_count=3, new_start=1, new_count=3,
            added=['def new_func(a):', '    pass'],
            removed=[],
        )
        syms = get_touched_symbols(h, language='python')
        assert 'new_func' in syms

    def test_from_file_content_tracking(self):
        content = (
            "def alpha():\n"
            "    pass\n"
            "\n"
            "def beta(x):\n"
            "    y = 1\n"
            "    z = 2\n"
        )
        # Hunk che modifica "y = 1" a "y = 10" - dentro beta
        h = Hunk(
            file='f.py', old_start=5, old_count=1, new_start=5, new_count=1,
            added=['    y = 10'], removed=['    y = 1'],
        )
        syms = get_touched_symbols(h, language='python', file_content_new=content)
        assert 'beta' in syms

    def test_unknown_language_returns_empty(self):
        h = Hunk(file='f.rs', old_start=1, old_count=1, new_start=1, new_count=1)
        assert get_touched_symbols(h, language='rust') == []

    def test_no_symbols_found(self):
        h = Hunk(
            file='f.py', old_start=1, old_count=1, new_start=1, new_count=1,
            added=['    x = 1'], removed=['    x = 2'],
            context_header='',
        )
        assert get_touched_symbols(h, language='python') == []
