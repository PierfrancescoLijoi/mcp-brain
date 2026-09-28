"""Safe, portable Git hook installation for mcp-brain."""

from __future__ import annotations

import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MANAGED_MARKER = "mcp-brain managed post-commit hook"


@dataclass(frozen=True)
class HookInstallResult:
    status: str
    path: Path


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _default_command() -> list[str]:
    names = ("mcp-brain.exe", "mcp-brain") if sys.platform == "win32" else ("mcp-brain",)
    invoked = Path(sys.argv[0]).resolve()
    if invoked.name.lower() in names and invoked.is_file():
        return [str(invoked)]

    candidates = [
        Path(sysconfig.get_path("scripts")).resolve(),
        Path(sys.executable).resolve().parent,
        Path(
            sysconfig.get_path(
                "scripts", scheme=sysconfig.get_preferred_scheme("user")
            )
        ).resolve(),
    ]
    script_dirs = list(dict.fromkeys(candidates))
    for scripts_dir in script_dirs:
        for name in names:
            candidate = scripts_dir / name
            if candidate.is_file():
                return [str(candidate.resolve())]

    package_root = Path(__file__).resolve().parents[2]
    bootstrap = (
        "import sys; "
        f"sys.path.insert(0, {str(package_root)!r}); "
        "from src.cli import main; raise SystemExit(main())"
    )
    return [sys.executable, "-I", "-c", bootstrap]


def build_post_commit_hook(
    python_executable: str | None = None,
    command: Sequence[str] | None = None,
) -> str:
    """Return a hook whose Python imports cannot be shadowed by the repo."""
    if command is not None:
        parts = list(command)
    elif python_executable is not None:
        parts = [python_executable, "-I", "-m", "src.cli"]
    else:
        parts = _default_command()
    invocation = " ".join(_shell_quote(part) for part in [*parts, "capture-commit"])
    return (
        "#!/bin/sh\n"
        f"# {MANAGED_MARKER}\n"
        "repo_root=\"$(git rev-parse --show-toplevel)\" || exit 0\n"
        "cd \"$repo_root\" || exit 0\n"
        f"{invocation}\n"
    )


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"{repo} is not a git repository") from exc


def resolve_repo_root(repo_path: str | Path) -> Path:
    """Return the canonical worktree root for any path inside a Git repository."""
    repo = Path(repo_path).resolve()
    return Path(_git(repo, "rev-parse", "--show-toplevel")).resolve()


def resolve_hooks_dir(repo_path: str | Path) -> Path:
    """Resolve Git's effective hook directory, including worktrees and hooksPath."""
    repo = resolve_repo_root(repo_path)
    try:
        configured = _git(repo, "config", "--path", "--get", "core.hooksPath")
    except ValueError:
        configured = ""
    if configured:
        path = Path(configured)
        return path.resolve() if path.is_absolute() else (repo / path).resolve()

    try:
        raw = _git(repo, "rev-parse", "--path-format=absolute", "--git-path", "hooks")
    except ValueError:
        raw = _git(repo, "rev-parse", "--git-path", "hooks")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (repo / path).resolve()


def install_post_commit_hook(
    repo_path: str | Path,
    python_executable: str | None = None,
    command: Sequence[str] | None = None,
) -> HookInstallResult:
    """Install without overwriting an unrelated user hook."""
    hooks_dir = resolve_hooks_dir(repo_path)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "post-commit"
    content = build_post_commit_hook(python_executable, command)
    status = "installed"
    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="replace")
        if MANAGED_MARKER not in existing:
            hook = hooks_dir / "post-commit.mcp-brain"
            status = "needs-chaining"
        else:
            status = "updated"
    hook.write_text(content, encoding="utf-8", newline="\n")
    try:
        hook.chmod(0o755)
    except OSError:
        pass
    return HookInstallResult(status=status, path=hook)
