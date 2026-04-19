# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`mcp-brain` is a persistent memory MCP server for Claude Code. It stores project context, architectural decisions, and session snapshots in a local SQLite database (`~/.mcp-brain/brain.db`), then serves them back to Claude at the start of each session — eliminating context rebuilding overhead.

## Commands

Install in editable mode:
```bash
pip install -e .
```

Run the server directly (dev):
```bash
python run.py
```

Run via installed entry point:
```bash
mcp-brain
```

There is no test suite or linter configured yet.

## Architecture

### Data model — three memory levels

Every memory has a computed `score` (0.0–1.0) that determines its level:

| Level | Score threshold | When loaded |
|-------|----------------|-------------|
| L1    | ≥ 0.7          | Every session (`brain_get_context`) — ~70 tokens |
| L2    | ≥ 0.4          | On-demand (`brain_get_decisions`) — ~200–400 tokens |
| L3    | < 0.4          | Archive only, never served |

Scoring weights (`src/brain/scorer.py`): recency 35%, frequency 30%, file impact 20%, explicit flag 15%. Recency decays linearly to 0 over 30 days.

### Request flow

```
Claude calls MCP tool
  → src/tools/mcp_tools.py  (FastMCP tool definitions)
  → src/brain/retriever.py  (business logic: scoring, level assignment)
  → src/brain/compressor.py (builds YAML context strings)
  → src/storage/db.py       (SQLite reads/writes to ~/.mcp-brain/brain.db)
```

### MCP tools (exposed to Claude)

| Tool | Purpose |
|------|---------|
| `brain_init` | Register a project (call once per repo) |
| `brain_get_context` | Load L1 context — call at session start |
| `brain_get_decisions` | Load L2 decisions — call when historical context needed |
| `brain_remember` | Store a memory; level auto-assigned by scorer |
| `brain_save_session` | Save end-of-session snapshot (branch, wip, next steps) |

Memory categories: `decision`, `avoid`, `pattern`, `failed`.

### Storage

- Database location: `~/.mcp-brain/brain.db` (created automatically on first `init_db()` call)
- Three tables: `projects`, `memories`, `sessions`
- `src/capture/` — stubs for future git-hook and snapshot capture features (currently empty)

### Entry points

- `run.py` (repo root) — adds repo root to `sys.path`, used for running without install
- `src/run.py` — similar shim
- `src/server.py:main` — registered as the `mcp-brain` console script in `pyproject.toml`

All three call `init_db()` then `mcp.run()`.

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