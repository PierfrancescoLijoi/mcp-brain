"""Stage 4: provider-neutral LLM verifier over localization candidates.

``claude-cli`` preserves the historical baseline. ``openai-compatible`` runs
against local llama.cpp, Ollama, vLLM, or LocalAI. Version-3 cache records keep
diagnostics; failed calls are retryable and never counted as verified.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from benchmark.loclab import CACHE, KS, REPOS, BlobReader, git
from src.brain.evidence import card
from src.brain.llm_verifier import (
    OpenAICompatibleBackend,
    VerificationOutcome,
    VerifierConfig,
    verify_predictions,
)
from src.brain.localizer import issue_signals

CARD_VERSION = 3
POLICY_VERSION = 4


class ClaudeCliBackend:
    name = 'claude-cli'

    def __init__(self, model: str, timeout_seconds: float = 300):
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(self, prompt: str, schema: dict) -> str:
        result = subprocess.run(
            ['claude', '-p', '--model', self.model, '--output-format', 'text',
             '--no-session-persistence', '--tools', '', '--setting-sources', '',
             '--strict-mcp-config'],
            input=prompt, capture_output=True, text=True, encoding='utf-8',
            timeout=self.timeout_seconds, cwd=CACHE,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or 'unknown CLI failure').strip()
            raise RuntimeError(f'claude CLI failed ({result.returncode}): {detail[:500]}')
        if not result.stdout.strip():
            raise RuntimeError('claude CLI returned empty output')
        return result.stdout


def cache_identity(
    backend: str,
    model: str,
    top: int,
    max_candidates: int = 5,
    min_confidence: float = 0.75,
    max_prompt_chars: int = 8_000,
    max_output_tokens: int = 256,
) -> str:
    clean = lambda value: re.sub(r'[^A-Za-z0-9._-]+', '-', value).strip('-')
    confidence = round(min_confidence * 100)
    return (
        f'verify_{clean(backend)}_{clean(model)}_{top}_head{max_candidates}_'
        f'conf{confidence}_prompt{max_prompt_chars}_out{max_output_tokens}_'
        f'c{CARD_VERSION}_p{POLICY_VERSION}.json'
    )


def metric_hits(ranking: dict, records: dict, verified: bool) -> dict:
    ids = [
        iid for iid in ranking
        if iid in records and records[iid].get('verification', {}).get('status')
        in {'verified', 'abstained'}
    ]
    result = {'n': len(ids)}
    for k in KS:
        hits = 0
        for iid in ids:
            predicted = records[iid]['ranking'] if verified else ranking[iid]['ranked']
            hits += bool(set(ranking[iid]['gold']) & set(predicted[:k]))
        result[f'hit@{k}'] = round(hits / max(len(ids), 1), 4)
    return result



def verify(item: dict, ranked: list, backend, config: VerifierConfig):
    repo = REPOS / item['repo'].replace('/', '__')
    tree = {}
    for line in git(repo, 'ls-tree', '-r', item['base_commit']).splitlines():
        meta, path = line.split('\t', 1)
        tree[path] = meta.split()[2]
    sig = issue_signals('', item['problem_statement'])
    query, idents = set(sig.terms), set(sig.identifiers)
    reader = BlobReader(repo)
    try:
        predictions = []
        for n, path in enumerate(ranked, 1):
            if path not in tree:
                continue
            predictions.append({
                'file': path,
                'confidence': 'low',
                'score': float(len(ranked) - n + 1),
                'source': 'benchmark-retriever',
                'hops': 0,
                'why': 'retriever candidate',
                'evidence': card(n, path, reader.read(tree[path]), query, idents),
            })
    finally:
        reader.proc.kill()
    reranked, outcome = verify_predictions(
        item['problem_statement'], predictions, config=config, backend=backend
    )
    return [prediction['file'] for prediction in reranked], outcome


def _backend_from_args(args):
    config = VerifierConfig(
        base_url=args.base_url or 'http://127.0.0.1',
        model=args.model,
        timeout_seconds=args.timeout,
        min_override_confidence=args.min_confidence,
        api_key=os.environ.get(args.api_key_env) if args.api_key_env else None,
        allow_remote=args.allow_remote,
        max_candidates=args.max_candidates,
        max_prompt_chars=args.max_prompt_chars,
        max_output_tokens=args.max_output_tokens,
    )
    if args.backend == 'claude-cli':
        return ClaudeCliBackend(args.model, args.timeout), config
    if not args.base_url:
        raise SystemExit(
            '--base-url or MCP_BRAIN_VERIFIER_URL is required for openai-compatible'
        )
    return OpenAICompatibleBackend(config), config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ranking', required=True)
    ap.add_argument('--dataset', default='benchmark/datasets/cache/swebench_full.jsonl')
    ap.add_argument('--top', type=int, default=15)
    ap.add_argument('--backend', choices=('claude-cli', 'openai-compatible'), default='claude-cli')
    ap.add_argument('--model', default='sonnet')
    ap.add_argument('--base-url', default=os.environ.get('MCP_BRAIN_VERIFIER_URL', ''))
    ap.add_argument('--api-key-env', default='MCP_BRAIN_VERIFIER_API_KEY')
    ap.add_argument('--allow-remote', action='store_true')
    ap.add_argument('--min-confidence', type=float, default=0.75)
    ap.add_argument('--max-candidates', type=int, default=5)
    ap.add_argument('--max-prompt-chars', type=int, default=8000)
    ap.add_argument('--max-output-tokens', type=int, default=256)
    ap.add_argument('--timeout', type=float, default=300)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--jobs', type=int, default=4)
    args = ap.parse_args()
    ranking = json.loads(Path(args.ranking).read_text(encoding='utf-8'))
    items = {json.loads(l)['instance_id']: json.loads(l) for l in open(args.dataset, encoding='utf-8') if l.strip()}
    backend, config = _backend_from_args(args)
    out_file = CACHE / cache_identity(
        args.backend,
        args.model,
        args.top,
        args.max_candidates,
        args.min_confidence,
        args.max_prompt_chars,
        args.max_output_tokens,
    )
    failure_file = out_file.with_suffix('.failures.json')
    records = json.loads(out_file.read_text(encoding='utf-8')) if out_file.exists() else {}
    failures = json.loads(failure_file.read_text(encoding='utf-8')) if failure_file.exists() else {}
    order = sorted(ranking)
    random.Random(0).shuffle(order)  # --limit takes a repo-mixed sample; resumable runs extend it
    todo = [i for i in order if i not in records][:args.limit]

    def run(iid):
        try:
            paths, outcome = verify(
                items[iid], ranking[iid]['ranked'][:args.top], backend, config
            )
            return iid, paths, outcome
        except Exception as exc:
            return iid, ranking[iid]['ranked'][:args.top], VerificationOutcome(
                status='error', backend=backend.name, model=args.model,
                confidence=None, changed_top=False, latency_ms=0,
                error=f'{type(exc).__name__}: {exc}',
            )

    with ThreadPoolExecutor(args.jobs) as ex:
        for n, (iid, paths, outcome) in enumerate(ex.map(run, todo), 1):
            if outcome.status == 'error':
                failures[iid] = outcome.to_dict()
            else:
                records[iid] = {
                    'ranking': paths,
                    'verification': outcome.to_dict(),
                }
                failures.pop(iid, None)
            if n % 10 == 0:
                out_file.write_text(json.dumps(records), encoding='utf-8')
                failure_file.write_text(json.dumps(failures), encoding='utf-8')
                print(
                    f'{n}/{len(todo)} success={len(records)} failures={len(failures)}',
                    flush=True,
                )
    out_file.write_text(json.dumps(records), encoding='utf-8')
    failure_file.write_text(json.dumps(failures), encoding='utf-8')

    print('retriever', metric_hits(ranking, records, verified=False))
    print('verified', metric_hits(ranking, records, verified=True))
    print('failures', len(failures))


if __name__ == '__main__':
    main()
