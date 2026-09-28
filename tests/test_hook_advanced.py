"""Security and Git-layout tests for hook installation."""

import subprocess
import sys

from src import cli
from src.capture import hook_support
from src.capture.hook_support import (
    build_post_commit_hook,
    install_post_commit_hook,
    resolve_hooks_dir,
)


def _run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def test_generated_hook_uses_isolated_python_and_shell_safe_quoting():
    hook = build_post_commit_hook("/opt/odd '$HOME` python")
    assert "'-I' '-m' 'src.cli' 'capture-commit'" in hook
    assert "'\"'\"'" in hook
    assert '"/opt/odd' not in hook


def test_default_command_prefers_the_entry_point_that_started_cli(
    tmp_path, monkeypatch
):
    invoked = tmp_path / ("mcp-brain.exe" if sys.platform == "win32" else "mcp-brain")
    invoked.write_text("launcher", encoding="utf-8")
    monkeypatch.setattr(hook_support.sys, "argv", [str(invoked), "init"])

    assert hook_support._default_command() == [str(invoked.resolve())]


def test_install_respects_custom_hooks_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    _run_git(repo, "config", "core.hooksPath", ".githooks")
    result = install_post_commit_hook(repo, "python")
    assert result.path == repo / ".githooks" / "post-commit"
    assert resolve_hooks_dir(repo) == repo / ".githooks"


def test_doctor_accepts_a_chained_companion(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-q")
    hooks = resolve_hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    primary = hooks / "post-commit"
    primary.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    install_post_commit_hook(repo, "python")
    primary.write_text("#!/bin/sh\necho existing\n\"$0.mcp-brain\"\n", encoding="utf-8")
    monkeypatch.setattr(cli, "_semantic_available", lambda: False)
    monkeypatch.setattr(cli, "_available_parsers", lambda: [])
    assert cli.doctor(str(repo)) == 0
