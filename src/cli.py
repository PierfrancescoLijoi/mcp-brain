import sys
import os
import shutil
from pathlib import Path

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


def init_project(repo_path: str = None):
    repo = Path(repo_path or os.getcwd()).resolve()

    if not (repo / '.git').exists():
        print(f'error: {repo} is not a git repository')
        return 1

    brain_dir = repo / '.brain'
    brain_dir.mkdir(exist_ok=True)
    print(f'[1/4] created {brain_dir}')

    gitignore = repo / '.gitignore'
    patterns = ['.env', '.brain/local/', '.brain/shared/*.log']
    existing = gitignore.read_text(encoding='utf-8') if gitignore.exists() else ''
    to_add = [p for p in patterns if p not in existing]
    if to_add:
        with open(gitignore, 'a', encoding='utf-8') as f:
            f.write('\n# mcp-brain\n' + '\n'.join(to_add) + '\n')
        print(f'[2/4] updated .gitignore with {len(to_add)} patterns')
    else:
        print('[2/4] .gitignore already configured')

    claude_md = repo / 'CLAUDE.md'
    if claude_md.exists():
        content = claude_md.read_text(encoding='utf-8')
        if 'Workflow ticket' not in content:
            with open(claude_md, 'a', encoding='utf-8') as f:
                f.write(CLAUDE_MD_WORKFLOW)
            print('[3/4] appended workflow to existing CLAUDE.md')
        else:
            print('[3/4] CLAUDE.md already has workflow')
    else:
        claude_md.write_text(
            f'# {repo.name}\n\nProject managed by mcp-brain.\n{CLAUDE_MD_WORKFLOW}',
            encoding='utf-8'
        )
        print('[3/4] created CLAUDE.md with workflow')

    hook_src = Path(__file__).parent.parent / 'hooks' / 'post-commit'
    hook_dst = repo / '.git' / 'hooks' / 'post-commit'
    if hook_src.exists():
        shutil.copy(hook_src, hook_dst)
        try:
            hook_dst.chmod(0o755)
        except Exception:
            pass
        print(f'[4/4] installed git hook')
    else:
        print('[4/4] hook source not found, skipping')

    print()
    print(f'mcp-brain initialized in {repo}')
    print('next: create a .env with GITHUB_TOKEN=... and run:')
    print('   claude mcp add mcp-brain python ' + str(repo / 'run.py'))
    return 0


def main():
    if len(sys.argv) < 2:
        print('usage: mcp-brain <command>')
        print('commands:')
        print('  init [path]   initialize mcp-brain in a git repo')
        return 1

    cmd = sys.argv[1]
    if cmd == 'init':
        path = sys.argv[2] if len(sys.argv) > 2 else None
        return init_project(path)
    else:
        print(f'unknown command: {cmd}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
