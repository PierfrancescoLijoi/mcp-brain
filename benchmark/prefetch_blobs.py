"""Bulk-fetch blobs missing from partial clones at every dataset base_commit.

Lazy fetching in a blob:none clone downloads one object per round-trip; this
fetches all missing source blobs per repository in a few batched requests.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.brain.localizer import SOURCE_SUFFIXES

BATCH = 2000


def missing_blobs(repo: Path, commits: set, suffixes: tuple = ('.py',)) -> set:
    missing = set()
    for commit in commits:
        tree = subprocess.run(['git', '-C', str(repo), 'ls-tree', '-r', commit],
                              capture_output=True, text=True, check=True).stdout
        shas = [l.split()[2] for l in tree.splitlines() if l.endswith(suffixes) and ' blob ' in l]
        check = subprocess.run(['git', '-C', str(repo), 'cat-file', '--batch-check'],
                               input='\n'.join(shas), capture_output=True, text=True,
                               env={'GIT_NO_LAZY_FETCH': '1', **__import__('os').environ}).stdout
        missing.update(l.split()[0].strip('?') for l in check.splitlines() if l.endswith(' missing'))
    return missing


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dataset', default='benchmark/datasets/cache/swebench_full.jsonl')
    ap.add_argument('--repo-cache', default='benchmark/repos')
    ap.add_argument('--all-languages', action='store_true', help='every supported source suffix, not only .py')
    args = ap.parse_args()
    suffixes = SOURCE_SUFFIXES if args.all_languages else ('.py',)
    commits = defaultdict(set)
    for line in open(args.dataset, encoding='utf-8'):
        if line.strip():
            item = json.loads(line)
            commits[item['repo']].add(item['base_commit'])
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda kv: prefetch(Path(args.repo_cache), *kv, suffixes), sorted(commits.items())))


def prefetch(cache: Path, name: str, cs: set, suffixes: tuple) -> None:
    repo = cache / name.replace('/', '__')
    shas = sorted(missing_blobs(repo, cs, suffixes))
    print(f'{name}: {len(shas)} missing blobs', flush=True)
    for i in range(0, len(shas), BATCH):
        # Bytes, not text: Windows text mode would send '\r\n' and git rejects the refspec.
        subprocess.run(['git', '-C', str(repo), '-c', 'fetch.negotiationAlgorithm=noop', 'fetch',
                        'origin', '--no-tags', '--no-write-fetch-head', '--stdin'],
                       input='\n'.join(shas[i:i + BATCH]).encode(), check=True, capture_output=True)


if __name__ == '__main__':
    main()
