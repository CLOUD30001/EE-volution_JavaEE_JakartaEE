"""Thin launcher for the jakarta-impact MCP server.

Adds the server's own directory to sys.path so its absolute-style sibling imports
resolve correctly when the script is run from the workspace root via fastmcp or
directly with `uv run python`.
"""
import sys
from pathlib import Path

# Ensure the jakarta-impact package directory is on the path before importing.
_server_dir = Path(__file__).parent / "jakarta-impact"
if str(_server_dir) not in sys.path:
    sys.path.insert(0, str(_server_dir))

from jakarta_impact_server import server  # noqa: E402


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
