import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.storage.db import init_db
from src.tools.mcp_tools import mcp

if __name__ == '__main__':
    init_db()
    mcp.run()
