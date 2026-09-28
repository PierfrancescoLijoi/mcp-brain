import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from src.capture.hook_support import (
    MANAGED_MARKER,
    install_post_commit_hook,
    resolve_hooks_dir,
    resolve_repo_root,
)


CLAUDE_MD_WORKFLOW = """

## Workflow ticket

Quando l utente scrive "lavora ticket #N":

1. call brain_start_ticket issue_id=N
2. call brain_get_context
3. leggi i file predetti dal tool
4. se ci sono warning di conflitto con PR aperte, allineati a quelle PR
5. PROPONI la soluzione in chat come diff o blocco di codice
6. NON modificare nessun file senza conferma esplicita
7. aspetta iterazioni: "cambia X", "rifai Y", "non mi piace Z"
8. applica modifiche ai file SOLO dopo "ok applica" o equivalente
9. NON fare mai git commit in autonomia
10. il commit lo fa sempre l utente dopo aver testato
"""


def _semantic_available() -> bool:
    from src.brain.semantic_reranker import is_available
    return is_available()


def _available_parsers() -> list[str]:
    from src.brain.parsers import available_languages
    return available_languages()


def _verifier_status() -> str:
    from src.brain.llm_verifier import OpenAICompatibleBackend, VerifierConfig

    url = os.environ.get('MCP_BRAIN_VERIFIER_URL', '').strip()
    model = os.environ.get('MCP_BRAIN_VERIFIER_MODEL', '').strip()
    if not url and not model:
        return 'disabled (optional)'
    try:
        config = VerifierConfig.from_env()
        OpenAICompatibleBackend(config)  # validates local/private endpoint; no request
    except (TypeError, ValueError) as exc:
        return f'configuration error ({exc})'
    return f'ready ({model} @ {urlparse(url).hostname})'


def init_project(repo_path: str | None = None) -> int:
    try:
        repo = resolve_repo_root(repo_path or os.getcwd())
    except ValueError:
        attempted = Path(repo_path or os.getcwd()).resolve()
        print(f'error: {attempted} is not a git repository')
        return 1

    brain_dir = repo / '.brain'
    brain_dir.mkdir(exist_ok=True)
    print(f'[1/4] created {brain_dir}')
    gitignore = repo / '.gitignore'
    patterns = ['.env', '.brain/local/', '.brain/shared/*.log']
    existing = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ''
    to_add = [p for p in patterns if p not in existing]
    if to_add:
        with open(gitignore, 'a', encoding='utf-8') as handle:
            handle.write('\n# mcp-brain\n' + '\n'.join(to_add) + '\n')
        print(f'[2/4] updated .gitignore with {len(to_add)} patterns')
    else:
        print('[2/4] .gitignore already configured')

    claude_md = repo / 'CLAUDE.md'
    if claude_md.exists():
        content = claude_md.read_text(encoding='utf-8')
        if 'Workflow ticket' not in content:
            with open(claude_md, 'a', encoding='utf-8') as handle:
                handle.write(CLAUDE_MD_WORKFLOW)
            print('[3/4] appended workflow to existing CLAUDE.md')
        else:
            print('[3/4] CLAUDE.md already has workflow')
    else:
        claude_md.write_text(
            f'# {repo.name}\n\nProject managed by mcp-brain.\n{CLAUDE_MD_WORKFLOW}',
            encoding='utf-8',
        )
        print('[3/4] created CLAUDE.md with workflow')

    hook = install_post_commit_hook(repo)
    if hook.status == 'needs-chaining':
        print(
            f'[4/4] existing hook preserved; helper created at {hook.path}. '
            'Add a call to it from your existing post-commit hook.'
        )
    else:
        print(f'[4/4] git hook {hook.status} at {hook.path}')
    print()
    print(f'mcp-brain initialized in {repo}')
    print('next: optionally set GITHUB_TOKEN, then run:')
    print('   claude mcp add mcp-brain -- mcp-brain-server')
    return 0


def capture_commit(repo_path: str | None = None) -> int:
    """Capture the current commit from a hook in any initialized repo."""
    if repo_path:
        try:
            repo = resolve_repo_root(repo_path)
        except ValueError:
            print(f'error: {Path(repo_path).resolve()} is not a git repository')
            return 1
    else:
        try:
            root = subprocess.check_output(
                ['git', 'rev-parse', '--show-toplevel'], text=True
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            print('error: current directory is not a git repository')
            return 1
        repo = Path(root).resolve()
    previous_cwd = Path.cwd()
    os.environ['MCP_BRAIN_REPO'] = str(repo)
    try:
        os.chdir(repo)
        from src.capture.git_hook import run
        run(repo.name)
    finally:
        os.chdir(previous_cwd)
    return 0


def doctor(repo_path: str | None = None) -> int:
    """Report whether a repository is ready to use mcp-brain."""
    try:
        repo = resolve_repo_root(repo_path or os.getcwd())
        hooks_dir = resolve_hooks_dir(repo)
    except ValueError:
        attempted = Path(repo_path or os.getcwd()).resolve()
        print(f'repository: error ({attempted})')
        return 1
    print(f'repository: ok ({repo})')
    hook = hooks_dir / 'post-commit'
    companion = hooks_dir / 'post-commit.mcp-brain'
    content = hook.read_text(encoding='utf-8', errors='replace') if hook.exists() else ''
    managed = MANAGED_MARKER in content
    chained = companion.exists() and (
        companion.name in content or '$0.mcp-brain' in content
    )
    if managed or chained:
        print('git hook: ok')
    elif companion.exists():
        print('git hook: action required (chain post-commit.mcp-brain)')
    else:
        print('git hook: missing (run mcp-brain init)')
    print('semantic reranker: ready' if _semantic_available()
          else 'semantic reranker: optional, not installed')
    parsers = _available_parsers()
    print(f'parsers: {", ".join(parsers) if parsers else "none installed"}')
    print(f'local verifier: {_verifier_status()}')
    return 0 if managed or chained else 1


def calibrate(repo_path: str | None = None, limit: int = 150) -> int:
    """Measure the localizer on this repository's own history and store the reading plan."""
    from src.brain.self_calibration import self_calibrate

    try:
        repo = resolve_repo_root(repo_path or os.getcwd())
    except ValueError:
        print(f'not a git repository: {Path(repo_path or os.getcwd()).resolve()}')
        return 1
    print(f'measuring on up to {limit} recent commits of {repo} (local, nothing leaves this machine)...')

    def progress(n: int, total: int) -> None:
        print(f'\r  {n}/{total} commits', end='', flush=True)

    report = self_calibrate(repo, limit=limit, progress=progress)
    print()
    hit = report['hit']
    print(f"measured on {report['n']} commits in {report['seconds']} s")
    print('changed file found in   ' + '   '.join(f'top-{k[4:]}: {v:.0%}' for k, v in hit.items()))
    if 'tiers' not in report:
        print('too few usable commits for a reading plan; keeping the benchmark calibration')
        return 1
    print(f"reading plan (target {report['target']:.0%}):")
    for t in report['tiers']:
        files = f"{t['read_first']} file{'s' if t['read_first'] > 1 else ''}"
        print(f"  {t['label']:<6} {t['n']:>4} commits   read {files:<9} -> {t['expected_hit']:.0%}")
    print('saved .brain/local/calibration.json; brain_predict_files now uses it.')
    print('commit messages are terser than issues, so these rates are conservative.')
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: mcp-brain <command>')
        print('commands:')
        print('  init [path]   initialize mcp-brain in a git repo')
        print('  doctor [path] verify installation and optional features')
        print('  capture-commit [path] capture the latest commit (used by hook)')
        print('  calibrate [path] measure file prediction on this repo history')
        return 1
    cmd = sys.argv[1]
    path = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == 'init':
        return init_project(path)
    if cmd == 'doctor':
        return doctor(path)
    if cmd == 'capture-commit':
        return capture_commit(path)
    if cmd == 'calibrate':
        return calibrate(path)
    print(f'unknown command: {cmd}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
