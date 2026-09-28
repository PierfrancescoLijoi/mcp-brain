# mcp-brain contributor guide

## What this project is

`mcp-brain` is a local-first, repository-aware MCP server for coding agents. It
combines persistent memories, session snapshots, Git history, a code graph,
file prediction, conflict checks, patch-safety checks, and an optional semantic
reranker. Repository state stays under `.brain/`; credentials belong in the
environment and must never be committed.

## Commands

```bash
# Editable development install with test dependencies
pip install -e ".[dev]"

# Start the MCP server
mcp-brain-server

# Configure the current Git repository and its post-commit hook
mcp-brain init

# Verify the hook and optional parser/semantic capabilities
mcp-brain doctor

# Measure file prediction on this repository history (writes .brain/local/calibration.json)
mcp-brain calibrate

# Run the complete test suite
python -m pytest -q
```

`python run.py` remains a development shim. The console scripts are deliberately
separate: `mcp-brain` is the setup/diagnostic CLI and `mcp-brain-server` starts
the MCP server.

## Architecture

The main request path is:

```text
MCP client
  -> src/tools/            FastMCP tool definitions and input/output shaping
  -> src/brain/            retrieval, scoring, graph, prediction, and guards
  -> src/storage/          SQLite access and repository-local paths
  -> .brain/local/         generated private state (gitignored)
  -> .brain/shared/        optional shareable team signals
```

Important generated files include `.brain/local/memory.db`,
`.brain/local/file_index.json`, and `.brain/local/code_graph.json`. Do not put
generated state back in a global home-directory database.

`src/capture/git_hook.py` is active code: the installed post-commit hook invokes
it through the CLI. `src/capture/hook_support.py` owns safe hook installation,
worktree/custom-hooks-path resolution, and preservation of existing user hooks.

The semantic reranker is optional. Core installation must continue to work
without `sentence-transformers` and NumPy; install `.[semantic]` when that
capability is wanted. Language parsers are likewise optional via `.[parsers]`.

## Development rules

- Add or update tests for behavior changes and run the focused tests first.
- Run the full suite before handing off a change.
- Preserve existing Git hooks; when a companion hook is generated, report the
  required chaining step instead of overwriting user configuration.
- Resolve a supplied repository path to the Git worktree root before writing
  `.brain`, `.gitignore`, or `CLAUDE.md`.
- Keep the default installation local-first and avoid mandatory paid services.
- Never commit credentials, `.env`, or `.brain/local/`.

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
