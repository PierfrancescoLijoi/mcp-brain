"""Test sulle funzioni pure di git_hook.py (classify, should_promote, scope)."""
import pytest

from src.capture.git_hook import (
    classify_commit,
    should_promote,
    _compute_scope,
)


class TestClassifyCommit:
    @pytest.mark.parametrize('msg, expected', [
        ('feat: add login', 'pattern'),
        ('perf: cache lookup', 'pattern'),
        ('fix: broken auth', 'failed'),
        ('hotfix: race condition', 'failed'),
        ('refactor: migrate to JWT RS256', 'decision'),
        ('breaking: change API signature', 'decision'),
        ('revert: previous change', 'avoid'),
        ('rollback to v1', 'avoid'),
        ('docs: update readme', 'noise'),
        ('chore: bump deps', 'noise'),
        ('style: format', 'noise'),
    ])
    def test_classifies_correctly(self, msg, expected):
        assert classify_commit(msg) == expected


class TestShouldPromote:
    def test_noise_never_promoted(self):
        ok, conf, reason = should_promote('p', 'docs: update', 'noise', [])
        assert ok is False
        assert conf == 'low'
        assert 'low-signal' in reason

    def test_decision_always_promoted_high(self, tmp_brain):
        ok, conf, reason = should_promote('p', 'refactor: switch to JWT', 'decision', [])
        assert ok is True
        assert conf == 'high'

    def test_breaking_always_promoted_high(self, tmp_brain):
        ok, conf, _ = should_promote('p', 'breaking: remove v1 endpoint', 'pattern', [])
        assert ok is True
        assert conf == 'high'

    def test_semantic_commit_multifile_promoted(self, tmp_brain):
        files = ['a.py', 'b.py', 'c.py']
        ok, conf, _ = should_promote('p', 'feat: new module', 'pattern', files)
        assert ok is True
        assert conf == 'medium'

    def test_semantic_commit_single_file_not_promoted(self, tmp_brain):
        ok, conf, reason = should_promote('p', 'feat: tiny change', 'pattern', ['a.py'])
        assert ok is False
        assert 'insufficient' in reason


class TestComputeScope:
    def test_no_files_is_repo(self):
        assert _compute_scope([]) == ('repo', None)

    def test_single_dir_is_module(self):
        assert _compute_scope(['src/auth/a.py', 'src/auth/b.py']) == ('module', 'src/auth')

    def test_multiple_dirs_is_repo(self):
        assert _compute_scope(['src/a.py', 'tests/b.py']) == ('repo', None)

    def test_over_5_files_is_repo(self):
        many = [f'src/f{i}.py' for i in range(6)]
        assert _compute_scope(many) == ('repo', None)

    def test_files_without_dir_is_repo(self):
        # file al top-level senza '/' non contribuiscono al dirs set
        assert _compute_scope(['README.md', 'setup.py'])[0] == 'repo'
