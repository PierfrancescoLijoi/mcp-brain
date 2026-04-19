from pathlib import Path
import shutil
import os

repo = Path(os.getcwd())
brain = repo / '.brain'
shared = brain / 'shared'
local = brain / 'local'

shared.mkdir(parents=True, exist_ok=True)
local.mkdir(parents=True, exist_ok=True)

moves = [
    (brain / 'memory.db', local / 'memory.db'),
    (brain / 'file_index.json', local / 'file_index.json'),
    (brain / 'server.log', local / 'server.log'),
    (brain / 'claims.yaml', shared / 'claims.yaml'),
]

for src, dst in moves:
    if src.exists() and not dst.exists():
        shutil.move(str(src), str(dst))
        print(f'moved {src.name} -> {dst.relative_to(brain)}')
    elif src.exists():
        src.unlink()
        print(f'removed duplicate {src.name}')

print('done')
