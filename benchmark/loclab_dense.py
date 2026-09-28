"""Dense (embedding) channel for the localization lab.

Scores only the lexical candidate pool of each instance. Files are split at
top-level ``def``/``class`` boundaries; a file's score is the max cosine over
its chunks. Chunk embeddings are cached per blob SHA.

    python -m benchmark.loclab_dense --features features_full.pkl
"""
from __future__ import annotations

import argparse
import json
import pickle
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np

from benchmark.loclab import CACHE, REPOS, BlobReader, git

MODEL = 'nomic-ai/CodeRankEmbed'
QUERY_PREFIX = 'Represent this query for searching relevant code: '
CHUNK_LINES = 80
MAX_CHUNKS = 24
SPLIT_RE = re.compile(r'^(?=(?:class|def|async def) )', re.M)


def chunks(path: str, text: str) -> list:
    parts = [p for p in SPLIT_RE.split(text) if p.strip()]
    out = []
    for part in parts:
        lines = part.splitlines()
        for i in range(0, len(lines), CHUNK_LINES):
            out.append(f'# {path}\n' + '\n'.join(lines[i:i + CHUNK_LINES]))
    return out[:MAX_CHUNKS] or [f'# {path}']


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--features', default='features_full.pkl')
    ap.add_argument('--dataset', default='benchmark/datasets/cache/swebench_full.jsonl')
    ap.add_argument('--pool', type=int, default=100, help='top-N lexical candidates to embed')
    ap.add_argument('--batch', type=int, default=64)
    ap.add_argument('--max-len', type=int, default=512)
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL, trust_remote_code=True, device='cuda')
    model.max_seq_length = args.max_len
    model.half()

    rows = pickle.loads((CACHE / args.features).read_bytes())
    issues = {json.loads(l)['instance_id']: json.loads(l) for l in open(args.dataset, encoding='utf-8') if l.strip()}
    emb_file = CACHE / 'dense_blobs.pkl'
    blob_emb: dict = pickle.loads(emb_file.read_bytes()) if emb_file.exists() else {}
    out_file = CACHE / f'dense_{args.features}'
    dense: dict = pickle.loads(out_file.read_bytes()) if out_file.exists() else {}

    by_repo = defaultdict(list)
    for r in rows:
        if r['instance_id'] not in dense:
            by_repo[r['repo']].append(r)

    for repo_name, repo_rows in by_repo.items():
        repo = REPOS / repo_name.replace('/', '__')
        reader = BlobReader(repo)
        for n, row in enumerate(repo_rows, 1):
            item = issues[row['instance_id']]
            tree = {}
            for line in git(repo, 'ls-tree', '-r', item['base_commit']).splitlines():
                meta, path = line.split('\t', 1)
                tree[path] = meta.split()[2]
            pool = _pool(row, args.pool)
            todo = [(tree[p], p) for p in pool if p in tree and tree[p] not in blob_emb]
            texts, owners = [], []
            for sha, path in todo:
                for c in chunks(path, reader.read(sha)):
                    texts.append(c); owners.append(sha)
            if texts:
                vecs = model.encode(texts, batch_size=args.batch, normalize_embeddings=True,
                                    convert_to_numpy=True).astype(np.float16)
                grouped = defaultdict(list)
                for sha, v in zip(owners, vecs):
                    grouped[sha].append(v)
                for sha, vs in grouped.items():
                    blob_emb[sha] = np.stack(vs)
            q = model.encode([QUERY_PREFIX + item['problem_statement'][:4000]],
                             normalize_embeddings=True, convert_to_numpy=True)[0].astype(np.float32)
            dense[row['instance_id']] = {
                p: float((blob_emb[tree[p]].astype(np.float32) @ q).max())
                for p in pool if p in tree and tree[p] in blob_emb
            }
            if n % 50 == 0:
                print(f'{repo_name} {n}/{len(repo_rows)} blobs={len(blob_emb)}', flush=True)
        reader.proc.kill()
        emb_file.write_bytes(pickle.dumps(blob_emb))
        out_file.write_bytes(pickle.dumps(dense))
    print(f'wrote {out_file}')


def _pool(row: dict, n: int) -> list:
    """Top-n candidates by best reciprocal rank on any lexical channel."""
    best = {p: max((v for k, v in f.items() if k.endswith('_rr')), default=0.0) for p, f in row['cands'].items()}
    return sorted(best, key=lambda p: -best[p])[:n]


if __name__ == '__main__':
    main()
