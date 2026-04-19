# mcp-brain

<p align="center">
  <img src="assets/banner.svg" width="900"/>
</p>

> Claude Code doesn’t fail because it lacks intelligence.  
> It fails because **it has zero awareness of your repo and your team.**

**mcp-brain turns Claude into a repo-aware, team-aware engineer — with lower token usage.**

---

<p align="center">
  <img src="assets/workflow.svg" width="850"/>
</p>

---

## 🚀 What this is

> **An awareness layer for AI coding — not just memory.**

mcp-brain gives Claude:

- repo awareness (structure, signals, changes)
- team awareness (WIP, ownership, conflicts)
- predictive navigation (issue → file)
- **compressed context instead of token-heavy context rebuilding**

---

## 🚨 The real problem

Claude operates blindly:

- no idea which files matter  
- no awareness of recent changes  
- no visibility into teammates  
- no understanding of outdated decisions  

Result:

- wrong file exploration  
- outdated suggestions  
- merge conflicts  
- **massive token waste rebuilding context**

---

## ⚡ What mcp-brain changes

Without:
Claude → explores → guesses → retries → conflicts → high token usage

With:
Claude → predicts → verifies → acts → aligned → **low token usage**

---

## 🧬 Core idea

Instead of giving more context,

👉 **we give structured awareness of reality**

- what changed  
- what matters  
- who is working on what  
- where to act  

⚡ And we do it **in ~100 tokens**

---

## 💰 Token efficiency (core advantage)

<p align="center">
  <img src="assets/costOptimization.svg" width="750"/>
</p>

Most tools increase token usage:

- embeddings  
- vector databases  
- full context injection  

mcp-brain reduces it:

- no embeddings  
- no vector DB  
- no history replay  

### Token usage comparison

Without mcp-brain:
~1000–2000 tokens / session

With mcp-brain:
~500–900 tokens / session

→ **40–60% reduction**

---

## 🔑 How it works

git commit        → signals captured (filtered)  
session end       → structured snapshot saved  
new session       → compressed awareness injected (~100 tokens)  
ticket opened     → files predicted + conflicts detected  

---

## 🧠 Awareness system

### 1. Signal extraction
Git = source of truth  
Only high-signal events are promoted  

Ignored:
docs / chore / test / ci  

---

### 2. Decision lifecycle

- active  
- suspect  
- stale  
- superseded  

Old decisions automatically invalidated.

---

### 3. Predictive repo understanding

Claude knows:

- which files matter  
- why  
- confidence level  

---

### 4. Team awareness

- who works on what  
- file ownership  
- conflict detection  

→ prevents collisions before coding

---

## ✨ What makes it different

This is NOT:

- vector DB memory  
- RAG system  
- checkpoint tool  

This IS:

- repo-aware AI  
- team-aware execution  
- predictive navigation  
- **token-efficient intelligence**

---

## ✨ Features

### 🧠 Awareness engine
- structured project state
- lifecycle tracking
- staleness detection

### 🔍 Prediction engine
- issue → file prediction
- explainability
- sub-100ms

### 👥 Team coordination
- soft claims
- conflict detection
- shared/local memory split

### ⚡ Performance
- no embeddings
- no vector DB
- incremental updates
- compressed YAML context

---

## 🧠 Example

```yaml
p: {name: my-api, stack: [FastAPI, PostgreSQL]}
s: {branch: feat/auth, wip: "JWT refactor", next: "add refresh token"}

git:
  recent: ["refactor: JWT moved to RS256"]
  changed: [auth.py, middleware.py]

team_claims:
  - {ticket: 42, author: dev-B, files: [middleware.py]}
```

👉 Claude already knows where and how to act.

---

## 🚀 Quick start

```bash
git clone https://github.com/PierfrancescoLijoi/mcp-brain.git
cd mcp-brain
pip install -e .
```

```bash
claude mcp add mcp-brain python /absolute/path/to/run.py
```

```bash
mcp-brain init
```

---

## 🏗️ Architecture

<p align="center">
  <img src="assets/architecture.svg" width="850"/>
</p>

```
claude-code  <-- MCP -->  mcp-brain

src/
  storage/
  brain/
  capture/
  tools/
```

---

## ⚠️ Trade-offs

- heuristic-based (no embeddings)
- depends on commit quality
- best for medium/large repos

---

## 💡 Positioning

mcp-brain is:
**a repo-aware, team-aware, token-efficient AI layer**
It is not:
- a memory database  
- a knowledge base  
- a generic MCP tool  
---

## 📄 License

MIT
