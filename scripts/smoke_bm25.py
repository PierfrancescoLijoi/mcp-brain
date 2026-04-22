"""
Smoke test STEP 2.1 + 2.2 — da eseguire dalla root del repo mcp-brain.

Cosa fa:
  1. Rebuild dell'index (con statistiche BM25: df, avgdl, doc_length, N).
  2. Stampa N, avgdl e i top-10 termini per DF (quelli più comuni).
  3. Stampa i top-10 termini per IDF (quelli più rari/informativi).
  4. Esegue 3 query di esempio e stampa top-5 file con score e why.
  5. Se esiste un code_graph salvato, ri-esegue le query usando
     predict_files_with_impact e stampa anche source/hops.

Uso:
    python scripts/smoke_bm25.py
    python scripts/smoke_bm25.py "fix JWT authentication bug"
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

# Assicuriamoci di eseguire dalla root del progetto
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.brain.file_indexer import build_index, load_index
from src.brain.file_predictor import (
    predict_files_explained,
    predict_files_with_impact,
    _idf,
)

SAMPLE_QUERIES = [
    "fix JWT authentication bug",
    "predict files from issue body",
    "BM25 scoring with IDF",
]


def banner(text: str) -> None:
    print()
    print("=" * 72)
    print(f"  {text}")
    print("=" * 72)


def main() -> int:
    banner("1) Building file_index.json")
    idx = build_index()
    n = idx.get('total', 0)
    avgdl = idx.get('avgdl', 0.0)
    df = idx.get('df', {})
    print(f"  indexed files : {n}")
    print(f"  avgdl         : {avgdl:.2f}")
    print(f"  unique terms  : {len(df)}")

    if n == 0:
        print("  [!] no files indexed — check MCP_BRAIN_REPO env and that you're in the repo root")
        return 1

    banner("2) Top-10 most common terms (low IDF)")
    common = sorted(df.items(), key=lambda x: x[1], reverse=True)[:10]
    for term, cnt in common:
        idf = _idf(cnt, n)
        print(f"  {term:<30} df={cnt:<4} idf={idf:.3f}")

    banner("3) Top-10 rarest terms (high IDF)")
    rare_candidates = [t for t, c in df.items() if c == 1]
    # Stampiamo comunque top-10 per IDF (tipicamente df=1)
    idf_sorted = sorted(df.items(), key=lambda x: _idf(x[1], n), reverse=True)[:10]
    for term, cnt in idf_sorted:
        print(f"  {term:<30} df={cnt:<4} idf={_idf(cnt, n):.3f}")

    # --- 4) Query di esempio ---
    queries = sys.argv[1:] if len(sys.argv) > 1 else SAMPLE_QUERIES

    # Verifica se il graph è disponibile
    graph_path = ROOT / '.brain' / 'local' / 'code_graph.json'
    has_graph = graph_path.exists()

    for q in queries:
        banner(f"4) Query (BM25 only): {q!r}")
        res = predict_files_explained(q, top_k=5)
        if not res:
            print("  (no results)")
        for i, r in enumerate(res, 1):
            print(f"  #{i} {r['confidence']:<6} score={r['score']:<7.3f} {r['file']}")
            print(f"      why: {r['why']}")

        if has_graph:
            banner(f"5) Query (BM25 + graph expansion): {q!r}")
            res2 = predict_files_with_impact(q, top_k=5, max_hops=2)
            for i, r in enumerate(res2, 1):
                src = r['source']
                hops = r.get('hops', 0)
                print(f"  #{i} {r['confidence']:<6} score={r['score']:<7.3f} "
                      f"[{src} hop={hops}] {r['file']}")
                print(f"      why: {r['why']}")
        else:
            print("  (code_graph.json not found — skipping graph expansion)")

    banner("DONE")
    return 0


if __name__ == '__main__':
    sys.exit(main())
