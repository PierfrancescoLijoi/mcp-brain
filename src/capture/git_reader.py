import subprocess
from pathlib import Path


def get_repo_root() -> Path:
    result = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
    return Path(result)


def get_current_branch() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True
    ).strip()


def get_branch_status() -> dict:
    """Quanti commit ahead/behind rispetto a main/master."""
    try:
        base = "main"
        ahead = subprocess.check_output(
            ["git", "rev-list", "--count", f"{base}..HEAD"], text=True
        ).strip()
        behind = subprocess.check_output(
            ["git", "rev-list", "--count", f"HEAD..{base}"], text=True
        ).strip()
        return {"ahead": int(ahead), "behind": int(behind)}
    except Exception:
        return {"ahead": 0, "behind": 0}


def get_recent_commits(n: int = 10) -> list[dict]:
    """Ultimi N commit del branch corrente."""
    try:
        log = subprocess.check_output([
            "git", "log", f"-{n}",
            "--pretty=format:%H|%s|%an|%ad",
            "--date=short"
        ], text=True).strip()

        commits = []
        for line in log.splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0][:8],
                    "message": parts[1],
                    "author": parts[2],
                    "date": parts[3],
                })
        return commits
    except Exception:
        return []


def get_changed_files(n_commits: int = 5) -> list[dict]:
    """File modificati negli ultimi N commit con stat."""
    try:
        result = subprocess.check_output([
            "git", "diff", "--stat", f"HEAD~{n_commits}..HEAD"
        ], text=True).strip()

        files = []
        for line in result.splitlines():
            if "|" in line and ("+" in line or "-" in line):
                parts = line.split("|")
                filename = parts[0].strip()
                stats = parts[1].strip() if len(parts) > 1 else ""
                files.append({
                    "file": filename,
                    "stats": stats,
                })
        return files
    except Exception:
        return []


def get_diff_summary(max_lines: int = 50) -> str:
    """Diff compresso degli ultimi cambiamenti — max_lines per restare nel budget token."""
    try:
        diff = subprocess.check_output([
            "git", "diff", "HEAD~1..HEAD",
            "--unified=1",
            "--diff-filter=AM",
        ], text=True)

        lines = diff.splitlines()[:max_lines]
        return "\n".join(lines)
    except Exception:
        return ""


def get_repo_snapshot() -> dict:
    """Snapshot completo dello stato corrente del repo."""
    return {
        "branch": get_current_branch(),
        "status": get_branch_status(),
        "recent_commits": get_recent_commits(n=5),
        "changed_files": get_changed_files(n_commits=3),
    }