"""Convert ByteDance-Seed/Multi-SWE-bench splits to the benchmark jsonl format.

Used as extra non-Python *training* data for the localizer; instances that also
appear in SWE-bench Multilingual are dropped so that evaluation stays held out.

    python -m benchmark.adapters.multi_swebench js/sveltejs__svelte_dataset.jsonl ts/vuejs__core_dataset.jsonl \
        --exclude benchmark/datasets/cache/swebench_multilingual.jsonl \
        --out benchmark/datasets/cache/multi_swebench_jsts.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from benchmark.adapters.patch_parser import extract_changed_files_from_patch
from benchmark.adapters.swebench import infer_language

HF_DATASET = 'ByteDance-Seed/Multi-SWE-bench'


def convert(row: dict) -> dict:
    issues = row.get('resolved_issues') or []
    statement = '\n\n'.join(f"{i.get('title') or ''}\n{i.get('body') or ''}".strip() for i in issues)
    gold = extract_changed_files_from_patch(row['fix_patch'])
    return {
        'instance_id': row['instance_id'],
        'dataset': 'multi-swe-bench',
        'repo': f"{row['org']}/{row['repo']}",
        'language': infer_language(gold),
        'base_commit': row['base']['sha'],
        'problem_statement': statement or f"{row.get('title') or ''}\n{row.get('body') or ''}",
        'gold_patch': row['fix_patch'],
        'gold_files': gold,
        'created_at': row.get('created_at'),
        'source_dataset': HF_DATASET,
    }


def main() -> None:
    from huggingface_hub import hf_hub_download

    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+', help='split files inside the HF dataset, e.g. ts/vuejs__core_dataset.jsonl')
    ap.add_argument('--exclude', nargs='*', default=[], help='jsonl files whose instance_ids must not be reused')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    seen = {json.loads(l)['instance_id'] for p in args.exclude for l in open(p, encoding='utf-8') if l.strip()}
    kept = 0
    with open(args.out, 'w', encoding='utf-8') as out:
        for name in args.files:
            path = hf_hub_download(HF_DATASET, name, repo_type='dataset')
            for line in open(path, encoding='utf-8'):
                rec = convert(json.loads(line))
                if rec['instance_id'] in seen or not rec['gold_files'] or rec['language'] == 'other':
                    continue
                out.write(json.dumps(rec) + '\n')
                kept += 1
    print(f'wrote {Path(args.out)} ({kept} instances)')


if __name__ == '__main__':
    main()
