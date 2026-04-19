# mcp-brain

> Persistent memory and team coordination MCP server for Claude Code.
> Zero tokens wasted on context rebuilding. Conflict-aware ticket workflow.

---

## The problem

Every time you open a new Claude Code session, you waste 15-30% of your token budget re-explaining:
- your project architecture and stack
- conventions, patterns to follow, patterns to avoid
- what you were working on yesterday
- what other developers are doing in parallel

`mcp-brain` eliminates this waste with persistent, compressed, team-aware context.

---

## What it does
```
git commit -> hook captures decisions automatically
end of session -> snapshot saved (branch, wip, next steps)
new session -> Claude gets compressed L1 context (~100 tokens)
GitHub ticket -> auto-loads scope, predicts files, detects team conflicts
```
---

## Features

- **Persistent memory** across sessions via local SQLite brain
- **Git-aware context**: branch, recent commits, changed files (live, via gitpython)
- **GitHub-integrated ticket workflow**: reads issues, predicts involved files, detects conflicts with open PRs
- **Soft-claims system** shared via `.brain/claims.yaml` committed in repo -> team sees who is working on what
- **AST-based file indexing** with inverted index -> sub-100ms file prediction on any repo size
- **Incremental index updates** on git hook -> no full repo rescan
- **Multi-layer caching**: file index, GitHub API, issues
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

### 2. Create GitHub Personal Access Token

Go to https://github.com/settings/tokens -> Generate new token (fine-grained).

Required permissions (read-only):
- `Metadata`
- `Contents`
- `Issues`
- `Pull requests`

Save the token in `.env` at the repo root:
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
- create `.brain/` directory for local memory
- update `.gitignore` with `mcp-brain` entries
- append ticket workflow section to `CLAUDE.md`
- install the git post-commit hook for automatic memory capture

---

## Usage

### Start a session (once per Claude Code session)
```call brain_get_context for <project-name>```
Claude receives automatically:
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
```lavora ticket #42 (/"work on ticket #42 ")```

Claude automatically:
1. calls `brain_start_ticket issue_id=42`
2. loads issue title and body
3. predicts involved files via AST index
4. scans open PRs for conflicts
5. registers a claim in `.brain/claims.yaml`
6. proposes a solution respecting active work
7. waits for your confirmation before editing files

### End a session
```
call brain_save_session for <project>, branch main, wip "what I did", next "what to do next"
Everything is restored on the next session.
```
---

## MCP tools exposed

| Tool | Purpose | Typical cost |
|------|---------|--------------|
| `brain_init` | Register a project | one-off |
| `brain_get_context` | Load L1 compressed context | ~100 tokens, <1s |
| `brain_get_decisions` | Load L2 historical decisions | on-demand |
| `brain_get_git_snapshot` | Live git state | on-demand |
| `brain_start_ticket` | Ticket-aware workflow | ~300 tokens |
| `brain_check_conflicts` | Scan files vs open PRs/claims | on-demand |
| `brain_team_status` | Who is doing what right now | on-demand |
| `brain_release_ticket` | Release a claim after merge | one-off |
| `brain_remember` | Store a memory explicitly | on-demand |
| `brain_save_session` | End-of-session snapshot | one-off |

---

## Memory levels

Every memory is scored 0.0-1.0 (recency 35%, frequency 30%, file impact 20%, explicit flag 15%).

| Level | Score | Tokens | Injection |
|-------|-------|--------|-----------|
| L1 | >= 0.7 | ~100 | Every session automatically |
| L2 | >= 0.4 | ~200-400 | On-demand via tool call |
| L3 | < 0.4 | 0 | Archive only, never injected |

---

## Memory categories

- `decision` — architectural choices
- `avoid` — anti-patterns to never suggest again
- `pattern` — recurring code patterns
- `failed` — things tried and abandoned

---

## Token savings
```
Without mcp-brain: ~1500 tokens/session on context rebuilding
With mcp-brain:    ~700 tokens/session (compressed context + targeted file reads)
Savings:           ~50% on context overhead, ~800 tokens/session

Team of 5 devs x 10 sessions/day -> ~1.2M tokens saved per month
```
---

## Architecture
claude-code <- MCP stdio -> mcp-brain server
|
+-- src/storage/db.py       (SQLite local brain)
+-- src/brain/
|   +-- scorer.py           (L1/L2/L3 scoring)
|   +-- compressor.py       (YAML compression)
|   +-- retriever.py        (fetch + store logic)
|   +-- file_indexer.py     (inverted index + AST)
|   +-- ast_indexer.py      (Python/JS/TS parser)
|   +-- file_predictor.py   (keyword -> files)
|   +-- claims_manager.py   (team claims)
|   +-- conflict_detector.py
+-- src/capture/
|   +-- git_reader.py       (live git state)
|   +-- git_hook.py         (commit capture)
|   +-- github_reader.py    (GitHub API)
+-- src/tools/mcp_tools.py  (10 MCP tools)
+-- src/cli.py              (mcp-brain init)
local storage:
~/.mcp-brain/      (not used in v1.1; brain moved into each repo)
.brain/
memory.db        (shared across team via git)
claims.yaml      (active team claims)
file_index.json  (inverted AST index)
server.log       (runtime logs, gitignored)

---

## Performance

Tested scaling characteristics:

| Repo size | Index build | First call | Cached call |
|-----------|-------------|------------|-------------|
| <100 files | <1s | ~2s | <100ms |
| 100-1000 | ~2s | ~3s | <100ms |
| 1000-10000 | ~15s | ~5s | <200ms |
| 10000-50000 | ~60s | ~10s | ~500ms |

Index is incremental: only files touched by each commit are re-parsed.

---

## Requirements

- Python 3.10+
- Claude Code (https://claude.ai/code)
- Git
- A GitHub Personal Access Token (for ticket workflow)

---

## Contributing

Issues and PRs welcome. Run the project itself with `mcp-brain` installed to dogfood.

---

## License

MIT
