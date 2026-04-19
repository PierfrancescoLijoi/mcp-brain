# mcp-brain 🧠

> Persistent memory MCP server for Claude Code — zero tokens wasted on context rebuilding.

Every time you open a new Claude Code session, you waste 15-30% of your token budget re-explaining your architecture, conventions, and what you were working on. `mcp-brain` fixes this.

## How it works
## Installation

```bash
pip install mcp-brain
claude mcp add mcp-brain python run.py
```

## Usage

### 1. Initialize your project (once per repo)
### 2. Start every session
### 3. End every session
## Memory levels

| Level | Tokens | When loaded |
|-------|--------|-------------|
| L1 | ~70 | Every session automatically |
| L2 | ~200-400 | On-demand when Claude needs historical context |
| L3 | — | Archive only, never injected |

## Memory categories

- `decision` — architectural choices
- `avoid` — patterns to never use
- `pattern` — recurring code patterns
- `failed` — things tried and abandoned

## Token savings

Without mcp-brain: ~1700 tokens/session on context rebuilding
With mcp-brain: ~70 tokens fixed
Savings: ~78%

## Requirements

- Python 3.10+
- Claude Code
- Git

## License

MIT
