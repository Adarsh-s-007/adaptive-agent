"""Async engine and session. Owner: P1.

Rule: never hold a transaction open across a Hindsight or Groq call. Commit the pending
state first, call the provider, then update (outbox pattern).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_kwargs(url: str) -> dict:
    if url.startswith("postgresql+asyncpg"):
        # Supabase pooled URLs run PgBouncer in transaction mode, which breaks
        # asyncpg's prepared-statement cache.
        return {"pool_pre_ping": True, "connect_args": {"statement_cache_size": 0}}
    return {}


engine = create_async_engine(
    get_settings().database_url, **_engine_kwargs(get_settings().database_url)
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
