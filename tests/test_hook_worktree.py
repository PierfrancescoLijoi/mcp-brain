"""Integration test for linked Git worktree hook resolution."""

import subprocess

from src.capture.hook_support import install_post_commit_hook, resolve_hooks_dir


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_install_in_linked_worktree(tmp_path):
    repo = tmp_path / "main"
    worktree = tmp_path / "linked"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "initial")
    _git(repo, "worktree", "add", "-q", "-b", "linked-test", str(worktree))

    result = install_post_commit_hook(worktree, "python")

    assert result.path == resolve_hooks_dir(worktree) / "post-commit"
    assert result.path.exists()
