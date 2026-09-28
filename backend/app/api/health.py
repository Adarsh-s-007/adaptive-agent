"""GET /health: liveness plus dependency status (unauthenticated). Owner: P1."""

import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app.db.session import engine
from app.gateways.hindsight_gateway import get_hindsight_gateway
from app.gateways.llm_gateway import get_llm_gateway

router = APIRouter(tags=["health"])


async def _db() -> str:
    try:
        async with engine.connect() as conn:
            await asyncio.wait_for(conn.execute(text("SELECT 1")), timeout=3)
        return "ok"
    except Exception:
        return "down"


async def _probe(check) -> str:
    try:
        return await asyncio.wait_for(check(), timeout=3)
    except Exception:
        return "down"


@router.get("/health")
async def health() -> dict:
    db, hindsight, groq = await asyncio.gather(
        _db(),
        _probe(get_hindsight_gateway().health),
        _probe(get_llm_gateway().health),
    )
    return {"status": "ok", "db": db, "hindsight": hindsight, "groq": groq}
