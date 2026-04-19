# mcp-brain

> Persistent memory and team coordination MCP server for Claude Code.
> Zero tokens wasted on context rebuilding. Conflict-aware ticket workflow.

---

## The problem

Every time you open a new Claude Code session, you waste part of your token budget re-explaining:

- your project architecture and stack
- conventions, patterns to follow, patterns to avoid
- what you were working on yesterday
- what other developers are doing in parallel

`mcp-brain` eliminates this waste with persistent, compressed, team-aware context.

---

## What it does

```
git commit        -> hook captures decisions automatically (raw events + promotion rules)
end of session    -> snapshot saved (branch, wip, next steps)
new session       -> Claude gets compressed L1 context (~100 tokens)
GitHub ticket     -> auto-loads scope, predicts files, detects team conflicts
```

---

## Features

- **Persistent memory** across sessions via local SQLite brain
- **Memory with status and confidence** — memories have `active`, `suspect`, `stale`, `superseded` states, not just a score
- **Staleness detection** — memories not verified for 60+ days are auto-marked `suspect`, 90+ days `stale`
- **Raw capture + promotion** — commits go to a raw event layer first, only high-signal events are promoted to persistent memory
- **Git-aware context** — branch, recent commits, changed files, live via `gitpython`
- **GitHub-integrated ticket workflow** — reads issues, predicts involved files, detects conflicts with open PRs
- **Soft-claims system** — shared via `.brain/shared/claims.yaml` so the team sees who is working on what
- **Explainable predictions** — every predicted file comes with `why` (matched symbol, filename, identifier) and a `confidence` label
- **AST-based file indexing** with inverted index for sub-100ms file prediction
- **Incremental index updates** on every commit, no full repo rescan
- **Storage split** — `.brain/shared/` committed in repo, `.brain/local/` gitignored (DB, index, logs)
- **YAML-compressed context** (5-8x denser than prose)
- **One-command setup** per project via CLI

---

## Installation

### 1. Clone and install

```bash
git clone https://github.com/PierfrancescoLijoi/mcp-brain.git
cd mcp-brain
pip install -e .
```

### 2. Create a GitHub Personal Access Token

Go to https://github.com/settings/tokens and generate a fine-grained token.

Required permissions (read-only):

- `Metadata`
- `Contents`
- `Issues`
- `Pull requests`

Save the token in a `.env` file at the repo root:

```
GITHUB_TOKEN=github_pat_xxxxxxxxxxxx
```

The `.env` file is auto-ignored by git.

### 3. Register the MCP server in Claude Code

```bash
claude mcp add mcp-brain python /absolute/path/to/mcp-brain/run.py
claude mcp list
```

Expected output:

```
mcp-brain: python /path/to/run.py - Connected
```

---

## Per-project setup

Initialize `mcp-brain` in any git repo with one command:

```bash
cd your-project
mcp-brain init
```

This will:

- create `.brain/shared/` and `.brain/local/`
- update `.gitignore` with the correct `mcp-brain` entries
- append a ticket workflow section to `CLAUDE.md`
- install the git `post-commit` hook for automatic capture

---

## Usage

### Start a session

```
call brain_get_context for <project-name>
```

Claude receives automatically something like:

```yaml
p: {name: my-api, stack: [FastAPI, PostgreSQL]}
s: {branch: feat/auth, wip: "JWT refactor", next: "add refresh token"}
git:
  branch: feat/auth
  recent: ["refactor: JWT moved to RS256"]
  changed: [auth.py, middleware.py]
avoid: ["ORM for bulk insert", "sync endpoints for ML inference"]
team_claims:
  - {ticket: 42, author: dev-B, files: [middleware.py]}
```

### Work on a GitHub ticket (conflict-aware)

```
lavora ticket #42
```

(or in English: `work on ticket #42`)

Claude automatically:

1. calls `brain_start_ticket_explained issue_id=42`
2. loads issue title and body
3. predicts involved files via the AST index, with `why` and `confidence` per file
4. scans open PRs for conflicts
5. registers a claim in `.brain/shared/claims.yaml`
6. proposes a solution respecting active team work
7. waits for your confirmation before editing files

### End a session

```
call brain_save_session for <project>, branch main, wip "what I did", next "what to do next"
```

Everything is restored on the next session.

---

## MCP tools exposed

| Tool | Purpose | Typical cost |
|------|---------|--------------|
| `brain_init` | Register a project | one-off |
| `brain_get_context` | Load L1 compressed context | ~100 tokens, <1s |
| `brain_get_decisions` | Load L2 historical decisions | on-demand |
| `brain_get_git_snapshot` | Live git state | on-demand |
| `brain_start_ticket` | Ticket workflow (compact) | ~250 tokens |
| `brain_start_ticket_explained` | Ticket workflow with `why` + `confidence` | ~350 tokens |
| `brain_check_conflicts` | Scan files vs open PRs and claims | on-demand |
| `brain_team_status` | Who is doing what right now | on-demand |
| `brain_release_ticket` | Release a claim after merge | one-off |
| `brain_remember` | Store a memory explicitly | on-demand |
| `brain_save_session` | End-of-session snapshot | one-off |
| `brain_check_staleness` | Mark old memories as suspect or stale | periodic |
| `brain_verify_memory` | Re-validate a memory (back to active) | on-demand |

---

## Memory model

Every memory is stored with:

- `category`: `decision`, `avoid`, `pattern`, `failed`
- `status`: `active`, `suspect`, `stale`, `superseded`
- `confidence`: `low`, `medium`, `high`
- `source`: `manual`, `git-hook`
- `scope`: `repo`, `branch`, `module`, `ticket`
- `last_verified_at`: last time the memory was confirmed valid

Only `active` memories are injected in the context. Staleness is auto-computed.

---

## Memory levels

| Level | Score | Tokens | Injection |
|-------|-------|--------|-----------|
| L1 | >= 0.7 | ~100 | Every session automatically |
| L2 | >= 0.4 | ~200-400 | On-demand via tool call |
| L3 | < 0.4 | 0 | Archive only, never injected |

---

## Raw capture + promotion rules

Commits are first saved as `raw_events`. A promotion rule decides whether to lift an event into persistent memory:

- `breaking:` / `revert` / `rollback` -> always promoted, confidence `high`
- `refactor:` / `migrate` / `replace` / `switch to` -> promoted as `decision`, confidence `high`
- conventional commit (`feat:`, `fix:`, `perf:`) with 2+ files changed -> promoted, confidence `medium`
- recurring pattern (similar message appearing 3+ times) -> promoted, confidence `medium`
- everything else stays as raw event, not injected in context

This avoids polluting memory with noise.

---

## Token savings

Realistic impact measured on typical Claude Code sessions:

```
Without mcp-brain: ~1500 tokens/session on context rebuilding
With mcp-brain:    ~700 tokens/session (compressed context + targeted file reads)
Savings:           ~50% on context overhead, ~800 tokens/session

Team of 5 devs x 10 sessions/day -> ~1.2M tokens saved per month
```

These numbers do not count indirect savings from fewer wrong-file explorations, fewer regressions on abandoned patterns, and less rework after merge conflicts.

---

## Architecture

```
claude-code  <-- MCP stdio -->  mcp-brain server
                                       |
                                       +-- src/storage/
                                       |     db.py              SQLite brain
                                       |     paths.py           shared/local split
                                       |
                                       +-- src/brain/
                                       |     scorer.py          L1/L2/L3 scoring
                                       |     compressor.py      YAML compression
                                       |     retriever.py       fetch + store
                                       |     file_indexer.py    inverted index + AST
                                       |     ast_indexer.py     Python/JS/TS parser
                                       |     file_predictor.py  keyword -> files + why
                                       |     staleness.py       stale / superseded
                                       |     claims_manager.py  team claims
                                       |     conflict_detector.py
                                       |
                                       +-- src/capture/
                                       |     git_reader.py      live git state
                                       |     git_hook.py        commit capture + promotion
                                       |     github_reader.py   GitHub API (PRs, issues)
                                       |
                                       +-- src/tools/mcp_tools.py   13 MCP tools
                                       +-- src/cli.py               mcp-brain init
```

Storage layout per repo:

```
.brain/
  shared/            (committed in git)
    claims.yaml      active team claims
    memories.yaml    approved memories (optional)
  local/             (gitignored)
    memory.db        SQLite brain
    file_index.json  inverted AST index
    server.log       runtime logs
```

---

## Performance

| Repo size | Index build | First tool call | Cached call |
|-----------|-------------|-----------------|-------------|
| < 100 files | < 1s | ~ 2s | < 100ms |
| 100 - 1 000 | ~ 2s | ~ 3s | < 100ms |
| 1 000 - 10 000 | ~ 15s | ~ 5s | < 200ms |
| 10 000 - 50 000 | ~ 60s | ~ 10s | ~ 500ms |

The index is incremental. Only files touched by each commit are re-parsed.

---

## Requirements

- Python 3.10+
- Claude Code ( https://claude.ai/code )
- Git
- A GitHub Personal Access Token (needed only for the ticket workflow)

---

## Contributing

Issues and PRs welcome. Run `mcp-brain` on itself to dogfood it.

---

## License

MIT
