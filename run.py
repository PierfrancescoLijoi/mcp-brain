import sys
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.resolve()
os.chdir(REPO_ROOT)
os.environ['MCP_BRAIN_REPO'] = str(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / '.env')

import logging
logging.basicConfig(
    filename=str(REPO_ROOT / '.brain' / 'server.log'),
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logging.info('=== Server starting ===')

from src.storage.db import init_db
from src.tools.mcp_tools import mcp

if __name__ == '__main__':
    init_db()
    logging.info('DB initialized')
    mcp.run()
