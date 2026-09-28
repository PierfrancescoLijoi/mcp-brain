"""Tests for the portable post-commit hook runtime."""

import subprocess
from pathlib import Path

from src import cli
from src.capture.hook_support import MANAGED_MARKER, install_post_commit_hook


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_reinstall_updates_managed_hook(tmp_path):
    repo = _repo(tmp_path)
    first = install_post_commit_hook(repo, "old-python")
    second = install_post_commit_hook(repo, "new-python")
    assert first.status == "installed"
    assert second.status == "updated"
    content = second.path.read_text(encoding="utf-8")
    assert MANAGED_MARKER in content
    assert "'-I' '-m' 'src.cli'" in content


def test_install_rejects_non_repository(tmp_path):
    try:
        install_post_commit_hook(tmp_path)
    except ValueError as exc:
        assert "not a git repository" in str(exc)
    else:
        raise AssertionError("non-repository path should be rejected")


def test_capture_commit_targets_selected_repository(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    calls = []
    from src.capture import git_hook
    monkeypatch.setattr(git_hook, "run", calls.append)
    original_cwd = Path.cwd()
    assert cli.capture_commit(str(repo)) == 0
    assert calls == ["repo"]
    assert Path.cwd() == original_cwd
