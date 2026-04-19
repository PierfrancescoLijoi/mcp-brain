from src.storage.db import init_db
from src.tools.mcp_tools import mcp


def main():
    init_db()
    mcp.run()


if __name__ == "__main__":
    main()