"""A/B: does mcp-brain help a real coding agent find the file to fix?

For each sampled SWE-bench Lite issue the repository is checked out at the
issue's base commit (a detached worktree, the benchmark clone is untouched) and
Claude Code runs headless twice with read-only tools:

* ``baseline``  - no MCP servers;
* ``mcp-brain`` - the mcp-brain server, and one system-prompt line telling the
  agent to call ``brain_predict_files`` first (what ``mcp-brain init`` puts in
  CLAUDE.md).

User settings, hooks and plugins are not loaded (``--setting-sources project``).
The agent must answer with a JSON list of paths; the first path is scored
against the files changed by the reference patch. Cost, tokens, turns and wall
time come from ``claude -p --output-format json``.

    python -m benchmark.agent_ab --n 20 --model sonnet --out benchmark/results/agent_ab.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROMPT = """Here is a GitHub issue for the repository in the current directory.

<issue>
{issue}
</issue>

Find the source file that must be modified to fix this issue. Do not modify anything.
End your answer with a JSON list of repository-relative paths, most likely first,
at most 3, for example: ["pkg/module.py"]"""
BRAIN_HINT = ('An MCP tool mcp__mcp-brain__brain_predict_files is available: call it first with the issue '
              'title and body, then follow its reading plan before searching on your own.')
READ_ONLY = ['Read', 'Grep', 'Glob']
BRAIN_TOOL = 'mcp__mcp-brain__brain_predict_files'
LIST_RE = re.compile(r'\[\s*"[^\]]*\]', re.S)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(repo), *args], check=True, capture_output=True)


def answer_paths(text: str, root: Path) -> list[str]:
    """Last JSON path list in the answer, as repository-relative posix paths."""
    found = LIST_RE.findall(text or '')
    if not found:
        return []
    try:
        paths = json.loads(found[-1])
    except json.JSONDecodeError:
        return []
    prefix = root.as_posix().lower().rstrip('/') + '/'
    out = []
    for p in paths:
        p = str(p).replace('\\', '/')
        if p.lower().startswith(prefix):
            p = p[len(prefix):]
        out.append(p.lstrip('./'))
    return out


def run_arm(arm: str, task: dict, wt: Path, model: str, scratch: Path) -> dict:
    empty = scratch / 'no_mcp.json'
    config = scratch / f"mcp_{task['instance_id']}.json"
    cmd = ['claude', '-p', '--output-format', 'json',
           '--model', model, '--setting-sources', 'project', '--strict-mcp-config', '--permission-mode', 'default']
    if arm == 'mcp-brain':
        config.write_text(json.dumps({'mcpServers': {'mcp-brain': {
            'command': 'mcp-brain-server', 'env': {'MCP_BRAIN_REPO': str(wt), 'MCP_BRAIN_SEMANTIC': '0'}}}}))
        cmd += ['--mcp-config', str(config), '--append-system-prompt', BRAIN_HINT,
                '--allowedTools', *READ_ONLY, BRAIN_TOOL]
    else:
        empty.write_text(json.dumps({'mcpServers': {}}))
        cmd += ['--mcp-config', str(empty), '--allowedTools', *READ_ONLY]
    started = time.time()
    proc = subprocess.run(cmd, cwd=wt, input=PROMPT.format(issue=task['problem_statement']), capture_output=True,
                          text=True, encoding='utf-8', errors='replace', timeout=900,
                          env={**os.environ, 'MCP_TOOL_TIMEOUT': '300000'})
    wall = round(time.time() - started, 1)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {'arm': arm, 'error': (proc.stderr or proc.stdout)[-500:], 'wall_s': wall}
    if out.get('is_error'):  # e.g. usage limit reached: not an answer, rerun it with --resume
        return {'arm': arm, 'error': str(out.get('result'))[-500:], 'wall_s': wall}
    usage = out.get('usage', {})
    paths = answer_paths(out.get('result', ''), wt)
    gold = set(task['gold_files'])
    return {
        'arm': arm,
        'answer': paths,
        'hit@1': bool(paths) and paths[0] in gold,
        'hit@3': any(p in gold for p in paths[:3]),
        'cost_usd': out.get('total_cost_usd'),
        'turns': out.get('num_turns'),
        'input_tokens': sum(usage.get(k, 0) for k in
                            ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')),
        'output_tokens': usage.get('output_tokens', 0),
        'wall_s': wall,
    }


def run_task(task: dict, args, scratch: Path) -> dict:
    repo = Path(args.repo_cache) / task['repo'].replace('/', '__')
    wt = scratch / 'wt' / task['instance_id']
    if wt.exists():
        subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(repo), 'worktree', 'remove', '--force', str(wt)], capture_output=True)
        shutil.rmtree(wt, ignore_errors=True)
    _git(repo, 'worktree', 'add', '--detach', str(wt), task['base_commit'])
    try:
        # The index is kept warm by the post-commit hook in real use; build it before timing.
        from src.brain.repo_localizer import localize
        localize(wt, task['problem_statement'].split('\n', 1)[0], top_k=1)
        arms = ['baseline', 'mcp-brain']
        random.Random(task['instance_id']).shuffle(arms)
        result = {'instance_id': task['instance_id'], 'gold': task['gold_files']}
        for arm in arms:
            result[arm] = run_arm(arm, task, wt, args.model, scratch)
        print(f"{task['instance_id']}: " + '  '.join(
            f"{a}={'hit' if result[a].get('hit@1') else 'miss'} ${result[a].get('cost_usd') or 0:.3f}" for a in arms),
            flush=True)
        return result
    finally:
        subprocess.run(['git', '-c', 'core.longpaths=true', '-C', str(repo), 'worktree', 'remove', '--force', str(wt)], capture_output=True)


def _safe(fn, task, *args):
    try:
        return fn(task, *args)
    except Exception as exc:  # one broken checkout must not lose the other runs
        print(f"{task['instance_id']}: skipped ({exc})", flush=True)
        return None


def _complete(result: dict) -> bool:
    return all('error' not in result[arm] for arm in ('baseline', 'mcp-brain'))


def summarize(results: list) -> dict:
    """Means over tasks where both arms answered, so the arms are compared on the same issues."""
    summary = {}
    for arm in ('baseline', 'mcp-brain'):
        rows = [r[arm] for r in results if _complete(r)]
        n = len(rows)
        mean = lambda k: round(sum(r[k] or 0 for r in rows) / max(n, 1), 4)
        summary[arm] = {'n': n, 'hit@1': mean('hit@1'), 'hit@3': mean('hit@3'), 'cost_usd': mean('cost_usd'),
                        'turns': mean('turns'), 'input_tokens': mean('input_tokens'),
                        'output_tokens': mean('output_tokens'), 'wall_s': mean('wall_s')}
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='benchmark/datasets/cache/swebench_lite.jsonl')
    p.add_argument('--repo-cache', default='benchmark/repos')
    p.add_argument('--n', type=int, default=20)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--model', default='sonnet')
    p.add_argument('--workers', type=int, default=3)
    # Outside the mcp-brain checkout, so the agent does not read this project's CLAUDE.md.
    p.add_argument('--scratch', required=True)
    p.add_argument('--out', default='benchmark/results/agent_ab.json')
    p.add_argument('--resume', action='store_true', help='keep completed tasks in --out, rerun the rest')
    args = p.parse_args()
    rows = [json.loads(line) for line in open(args.dataset, encoding='utf-8')]
    tasks = random.Random(args.seed).sample(rows, args.n)
    scratch = Path(args.scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    done = []
    if args.resume and Path(args.out).exists():
        done = [r for r in json.loads(Path(args.out).read_text(encoding='utf-8'))['results'] if _complete(r)]
        ids = {r['instance_id'] for r in done}
        tasks = [t for t in tasks if t['instance_id'] not in ids]
    with ThreadPoolExecutor(args.workers) as pool:
        results = done + [r for r in pool.map(lambda t: _safe(run_task, t, args, scratch), tasks) if r]
    report = {'model': args.model, 'seed': args.seed, 'summary': summarize(results), 'results': results}
    Path(args.out).write_text(json.dumps(report, indent=1), encoding='utf-8')
    print(json.dumps(report['summary'], indent=1))


if __name__ == '__main__':
    main()
