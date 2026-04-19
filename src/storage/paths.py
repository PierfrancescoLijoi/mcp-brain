import os
from pathlib import Path

REPO_CWD = os.environ.get('MCP_BRAIN_REPO', os.getcwd())

BRAIN_ROOT = Path(REPO_CWD) / '.brain'
SHARED_DIR = BRAIN_ROOT / 'shared'
LOCAL_DIR = BRAIN_ROOT / 'local'

# Shared (committed)
CLAIMS_PATH = SHARED_DIR / 'claims.yaml'
SHARED_MEMORIES_PATH = SHARED_DIR / 'memories.yaml'

# Local (gitignored)
DB_PATH = LOCAL_DIR / 'memory.db'
INDEX_PATH = LOCAL_DIR / 'file_index.json'
LOG_PATH = LOCAL_DIR / 'server.log'


def ensure_dirs():
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
