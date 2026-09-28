"""Shared test setup. Owner: P1.

Unit tests run on a temporary SQLite database with fakes for both gateways
(tests/fakes/fake_hindsight.py by P2, tests/fakes/fake_llm.py by P5).
"""

import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{Path(_tmp) / 'test.db'}")
os.environ.setdefault("APP_ACCESS_TOKEN", "test-token")
os.environ.setdefault("DEMO_MODE", "true")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db import models  # noqa: E402,F401
from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db():
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
