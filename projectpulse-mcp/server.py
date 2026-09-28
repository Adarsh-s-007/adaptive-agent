"""ProjectPulse MCP stdio entry point."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.database import Base, engine  # noqa: E402
from app.models import entities  # noqa: E402,F401
from app.services.mcp_server import mcp  # noqa: E402

Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    mcp.run()
