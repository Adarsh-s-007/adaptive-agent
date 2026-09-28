"""ProjectPulse MCP stdio entry point."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import app.db.governed_models  # noqa: F401
from app.db.database import sync_schema
from app.models import entities  # noqa: F401
from app.services.mcp_server import mcp

sync_schema()

if __name__ == "__main__":
    mcp.run()
