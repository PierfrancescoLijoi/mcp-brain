"""Evidence cards: what an agent needs to pick the file to edit from a shortlist.

Shared by ``repo_localizer`` (the MCP tool returns cards so the calling agent
does the final choice locally) and ``benchmark/loclab_verify.py`` (which
measures exactly these cards with an LLM).
"""
from __future__ import annotations

import re

from src.brain.localizer import code_terms

WINDOW = 12
WINDOWS_PER_FILE = 4
MAX_OUTLINE = 40
SIG_RE = re.compile(r'^([ \t]*)(?:async\s+)?(def|class)\s+(\w+)', re.M)
VERIFY_RULES = """Rules:
- Pick the file where the faulty logic lives and the fix belongs, not the file that
  merely raises, re-exports, wraps, or displays the symptom.
- Candidates are in retriever order. The retriever's #1 is correct about 65% of the
  time and the answer is in its top 5 about 86% of the time; move a candidate above
  #1 only when the evidence clearly says the fix belongs there.
- Each card shows the file outline (issue symbols marked with *) and the code windows
  that best match the issue."""


def card(rank: int, path: str, text: str, query: set, idents: set) -> str:
    lines = text.splitlines()
    outline = []
    try:
        from src.brain.extractor import extract

        extracted = extract(path, text)
    except Exception:
        extracted = None
    if extracted and extracted.symbols:
        for symbol in extracted.symbols:
            mark = '*' if symbol.name.lower() in idents else ''
            prefix = '  ' if symbol.parent else ''
            outline.append(f'{prefix}{symbol.kind} {symbol.name}{mark}')
    else:
        for m in SIG_RE.finditer(text):
            indent, kind, name = m.groups()
            if len(indent) <= 4:  # top level and methods; skip nested helpers
                mark = '*' if name.lower() in idents else ''
                outline.append(f'{"  " if indent else ""}{kind} {name}{mark}')
    marked = [o for o in outline if o.endswith('*')]
    if len(outline) > MAX_OUTLINE:  # keep every issue symbol, then the first others
        outline = marked + [o for o in outline if not o.endswith('*')][:MAX_OUTLINE - len(marked)] + ['...']
    scored = []
    for i in range(0, max(len(lines) - WINDOW, 0) + 1, WINDOW // 2):
        chunk = lines[i:i + WINDOW]
        scored.append((len(set(code_terms('\n'.join(chunk))) & query), i))
    picked = []
    for _s, i in sorted(scored, reverse=True):
        if all(abs(i - k) >= WINDOW for k in picked):  # no overlapping windows
            picked.append(i)
        if len(picked) == WINDOWS_PER_FILE:
            break
    body = '\n...\n'.join('\n'.join(f'{i + j + 1}: {l[:140]}'.rstrip() for j, l in enumerate(lines[i:i + WINDOW]))
                          for i in sorted(picked))
    return (f'## [{rank}] {path} ({len(lines)} lines)\noutline: {"; ".join(outline) or "none"}\n'
            f'{body}')
