"""End-to-end tests for the install and diagnostics CLI flows."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src import cli
from src.capture.hook_support import resolve_hooks_dir


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_init_installs_portable_hook(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path)
    monkeypatch.setattr(
        "src.capture.hook_support._default_command",
        lambda: ["C:/Tools/mcp-brain.exe"],
    )
    assert cli.init_project(str(repo)) == 0
    hook = (resolve_hooks_dir(repo) / "post-commit").read_text(encoding="utf-8")
    assert "mcp-brain managed post-commit hook" in hook
    assert "'C:/Tools/mcp-brain.exe' 'capture-commit'" in hook
    assert "src/capture/git_hook.py" not in hook
    assert "hook installed" in capsys.readouterr().out


def test_init_preserves_existing_post_commit_hook(tmp_path, capsys):
    repo = _git_repo(tmp_path)
    hooks = resolve_hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    existing = hooks / "post-commit"
    existing.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
    assert cli.init_project(str(repo)) == 0
    assert existing.read_text(encoding="utf-8") == "#!/bin/sh\necho existing\n"
    assert (hooks / "post-commit.mcp-brain").exists()
    assert "existing hook preserved" in capsys.readouterr().out


def test_doctor_reports_ready_repo(tmp_path, monkeypatch, capsys):
    repo = _git_repo(tmp_path)
    hooks = resolve_hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "post-commit").write_text(
        "#!/bin/sh\n# mcp-brain managed post-commit hook\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "_semantic_available", lambda: False)
    monkeypatch.setattr(cli, "_available_parsers", lambda: ["python"])
    monkeypatch.setattr(cli, "_verifier_status", lambda: "ready (local-model @ 127.0.0.1)")
    assert cli.doctor(str(repo)) == 0
    output = capsys.readouterr().out
    assert "repository: ok" in output
    assert "git hook: ok" in output
    assert "semantic reranker: optional, not installed" in output
    assert "parsers: python" in output
    assert "local verifier: ready (local-model @ 127.0.0.1)" in output


def test_doctor_fails_outside_git_repo(tmp_path, capsys):
    assert cli.doctor(str(tmp_path)) == 1
    assert "repository: error" in capsys.readouterr().out


def test_verifier_status_is_disabled_without_local_configuration(monkeypatch):
    monkeypatch.delenv('MCP_BRAIN_VERIFIER_URL', raising=False)
    monkeypatch.delenv('MCP_BRAIN_VERIFIER_MODEL', raising=False)
    assert cli._verifier_status() == 'disabled (optional)'


def test_main_routes_doctor_command(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "doctor", lambda path=None: called.append(path) or 0)
    monkeypatch.setattr(cli.sys, "argv", ["mcp-brain", "doctor", "sample"])
    assert cli.main() == 0
    assert called == ["sample"]


def test_init_from_subdirectory_configures_repository_root(tmp_path, monkeypatch):
    repo = _git_repo(tmp_path)
    nested = repo / "packages" / "api"
    nested.mkdir(parents=True)
    monkeypatch.setattr(
        "src.capture.hook_support._default_command",
        lambda: ["C:/Tools/mcp-brain.exe"],
    )

    assert cli.init_project(str(nested)) == 0

    assert (repo / ".brain").is_dir()
    assert (repo / "CLAUDE.md").is_file()
    assert not (nested / ".brain").exists()
    assert not (nested / "CLAUDE.md").exists()


def test_doctor_from_subdirectory_reports_repository_root(
    tmp_path, monkeypatch, capsys
):
    repo = _git_repo(tmp_path)
    nested = repo / "src" / "feature"
    nested.mkdir(parents=True)
    hooks = resolve_hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    (hooks / "post-commit").write_text(
        "#!/bin/sh\n# mcp-brain managed post-commit hook\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "_semantic_available", lambda: False)
    monkeypatch.setattr(cli, "_available_parsers", lambda: [])
    monkeypatch.setattr(cli, "_verifier_status", lambda: "disabled (optional)")

    assert cli.doctor(str(nested)) == 0
    assert f"repository: ok ({repo.resolve()})" in capsys.readouterr().out
