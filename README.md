# mcp-brain

> Claude Code forgets your project every session.
> **mcp-brain gives it persistent, structured memory — without wasting tokens.**

It tracks decisions, prevents regressions, and makes the AI aware of your team’s work in real time.

---

## The problem

Every new Claude Code session starts from zero.

You waste tokens re-explaining:

* architecture and stack
* conventions and anti-patterns
* current work (WIP, branches)
* what your teammates are doing

This leads to:

* repeated mistakes
* outdated suggestions
* conflicts with ongoing work

---

## The solution

`mcp-brain` introduces a **persistent, structured memory layer** for Claude Code.

```text
git commit        → raw events captured (filtered, not blindly stored)
end of session    → snapshot saved (branch, WIP, next steps)
new session       → compressed L1 context injected (~100 tokens)
GitHub ticket     → files predicted + conflicts detected + team awareness
```

---

## Why this is different

Most AI coding tools rely on ephemeral context or raw history.

mcp-brain is built around three principles:

### Signal over noise

Commits are captured as **raw events**, not immediate memory.
Only high-signal patterns are promoted.

### Memory lifecycle

Every memory has a state:

* `active`
* `suspect`
* `stale`
* `superseded`

New decisions automatically **supersede older similar ones** using lightweight semantic matching
(Jaccard similarity on tokenized content — no embeddings, zero latency).

### Team awareness

The AI knows:

* who is working on what
* which files are being touched
* where conflicts may occur

This prevents outdated suggestions and reduces merge conflicts.

---

## Features

### Core memory system

* Persistent memory via local SQLite
* Memory lifecycle with status tracking
* Confidence and source attribution
* Staleness detection (time + repo activity)

### Signal filtering

* Raw event capture from git
* Promotion rules to avoid noise
* `docs`, `chore`, `style`, `test`, `ci` → never promoted

### Developer awareness

* Git-aware context (branch, changes, commits)
* GitHub ticket workflow
* Soft-claims system (`.brain/shared/claims.yaml`)

### Explainability

* File predictions include:

  * `why` (symbol match, keyword, filename)
  * `confidence`

### Performance & efficiency

* AST-based file indexing (sub-100ms predictions)
* Incremental updates on commit
* YAML-compressed context (5–8x denser)

### Storage model

* `.brain/shared/` → committed (team coordination)
* `.brain/local/` → gitignored (DB, index, logs)

---

## Quick start

```bash
git clone https://github.com/PierfrancescoLijoi/mcp-brain.git
cd mcp-brain
pip install -e .
```

Add to Claude Code:

```bash
claude mcp add mcp-brain python /absolute/path/to/run.py
```

Initialize in your repo:

```bash
mcp-brain init
```

---

## Usage

### Start a session

```text
call brain_get_context for <project-name>
```

Claude receives compressed, structured context:

```yaml
p: {name: my-api, stack: [FastAPI, PostgreSQL]}
s: {branch: feat/auth, wip: "JWT refactor", next: "add refresh token"}
git:
  branch: feat/auth
  recent: ["refactor: JWT moved to RS256"]
  changed: [auth.py, middleware.py]
avoid: ["ORM for bulk insert"]
team_claims:
  - {ticket: 42, author: dev-B, files: [middleware.py]}
```

---

### Work on a ticket

```text
work on ticket #42
```

Claude will:

1. load issue
2. predict files (with reasons)
3. detect conflicts (PRs + claims)
4. register a claim
5. propose a solution
6. wait for confirmation

---

## Token savings

Typical sessions:

```text
Without mcp-brain: ~1500 tokens/session  
With mcp-brain:    ~700 tokens/session  
→ ~50% reduction
```

Also reduces:

* wrong file exploration
* regressions
* merge conflicts

---

## Architecture (simplified)

```text
claude-code  <-- MCP -->  mcp-brain

src/
  storage/
  brain/
  capture/
  tools/
```

---

## Limitations

* Memory quality depends on promotion rules
* Staleness detection is heuristic-based
* No embeddings (by design, to keep token usage low)
* Best suited for medium/large repos

---

## License

MIT
