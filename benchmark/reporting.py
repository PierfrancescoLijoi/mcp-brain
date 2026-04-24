from __future__ import annotations

import html
import json
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List


def summarize(results: List[Dict[str, Any]], ks=(1, 3, 5, 10)) -> Dict[str, Any]:
    n = len(results)
    summary: Dict[str, Any] = {"instances": n}
    for k in ks:
        summary[f"hit@{k}"] = mean([r["metrics"][f"hit@{k}"] for r in results]) if n else 0.0
        summary[f"recall@{k}"] = mean([r["metrics"][f"recall@{k}"] for r in results]) if n else 0.0
        summary[f"map@{k}"] = mean([r["metrics"][f"ap@{k}"] for r in results]) if n else 0.0
    summary["avg_gold_files"] = mean([len(r["gold_files"]) for r in results]) if n else 0.0
    summary["avg_predicted_files"] = mean([len(r["predicted_files"]) for r in results]) if n else 0.0
    summary["errors"] = sum(1 for r in results if r.get("error"))
    return summary


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    s = payload["summary"]
    lines = [
        "# mcp-brain SWE-bench Lite benchmark report",
        "",
        "## Summary",
        "",
        f"- Instances evaluated: **{s['instances']}**",
        f"- Errors: **{s['errors']}**",
        f"- Avg gold files: **{s['avg_gold_files']:.2f}**",
        f"- Avg predicted files: **{s['avg_predicted_files']:.2f}**",
        "",
        "| Metric | @1 | @3 | @5 | @10 |",
        "|---|---:|---:|---:|---:|",
        f"| Hit | {s['hit@1']:.3f} | {s['hit@3']:.3f} | {s['hit@5']:.3f} | {s['hit@10']:.3f} |",
        f"| Recall | {s['recall@1']:.3f} | {s['recall@3']:.3f} | {s['recall@5']:.3f} | {s['recall@10']:.3f} |",
        f"| MAP | {s['map@1']:.3f} | {s['map@3']:.3f} | {s['map@5']:.3f} | {s['map@10']:.3f} |",
        "",
        "## Worst misses / examples",
        "",
    ]
    rows = sorted(payload["results"], key=lambda r: (r["metrics"].get("hit@10", 0), r["metrics"].get("recall@10", 0)))[:20]
    for r in rows:
        lines.append(f"### {r['instance_id']} — {r['repo']}")
        lines.append(f"- Gold: `{', '.join(r['gold_files'][:10])}`")
        lines.append(f"- Predicted: `{', '.join(r['predicted_files'][:10])}`")
        lines.append(f"- Recall@10: **{r['metrics']['recall@10']:.3f}**, Hit@10: **{r['metrics']['hit@10']}**")
        if r.get("error"):
            lines.append(f"- Error: `{r['error']}`")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_html(path: Path, payload: Dict[str, Any]) -> None:
    s = payload["summary"]
    rows = []
    for r in payload["results"][:200]:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(r['instance_id']))}</td>"
            f"<td>{html.escape(str(r['repo']))}</td>"
            f"<td>{r['metrics']['hit@10']}</td>"
            f"<td>{r['metrics']['recall@10']:.3f}</td>"
            f"<td><code>{html.escape(', '.join(r['gold_files'][:8]))}</code></td>"
            f"<td><code>{html.escape(', '.join(r['predicted_files'][:8]))}</code></td>"
            "</tr>"
        )
    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>mcp-brain benchmark</title>
<style>
body{{font-family:Inter,Arial,sans-serif;margin:32px;line-height:1.45;color:#17202a}}
.card{{border:1px solid #ddd;border-radius:14px;padding:20px;margin:16px 0;box-shadow:0 2px 10px #0001}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #eee;padding:8px;text-align:left;vertical-align:top}}th{{background:#fafafa}}code{{white-space:pre-wrap}}
.metric{{display:inline-block;margin:8px 20px 8px 0;font-size:18px}}.metric b{{font-size:28px;display:block}}
</style></head><body>
<h1>mcp-brain SWE-bench Lite benchmark</h1>
<div class="card">
  <div class="metric"><b>{s['instances']}</b>instances</div>
  <div class="metric"><b>{s['hit@10']:.3f}</b>Hit@10</div>
  <div class="metric"><b>{s['recall@10']:.3f}</b>Recall@10</div>
  <div class="metric"><b>{s['map@10']:.3f}</b>MAP@10</div>
  <div class="metric"><b>{s['errors']}</b>errors</div>
</div>
<div class="card">
<h2>Metrics</h2>
<table><tr><th>Metric</th><th>@1</th><th>@3</th><th>@5</th><th>@10</th></tr>
<tr><td>Hit</td><td>{s['hit@1']:.3f}</td><td>{s['hit@3']:.3f}</td><td>{s['hit@5']:.3f}</td><td>{s['hit@10']:.3f}</td></tr>
<tr><td>Recall</td><td>{s['recall@1']:.3f}</td><td>{s['recall@3']:.3f}</td><td>{s['recall@5']:.3f}</td><td>{s['recall@10']:.3f}</td></tr>
<tr><td>MAP</td><td>{s['map@1']:.3f}</td><td>{s['map@3']:.3f}</td><td>{s['map@5']:.3f}</td><td>{s['map@10']:.3f}</td></tr>
</table></div>
<div class="card"><h2>Instances</h2><table><tr><th>ID</th><th>Repo</th><th>Hit@10</th><th>Recall@10</th><th>Gold</th><th>Predicted</th></tr>{''.join(rows)}</table></div>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_doc, encoding="utf-8")
