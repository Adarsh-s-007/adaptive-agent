"""Engine, session factory and additive schema sync.

`sync_schema()` creates missing tables and adds missing columns in place, so a
database created by an earlier ProjectPulse version upgrades without data loss.
It never drops or rewrites anything.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

log = logging.getLogger("projectpulse.db")

settings = get_settings()
database_url = settings.database_url
if database_url.startswith("sqlite:///./"):
    # Resolve against the repository root so the API and the MCP stdio server share a file.
    root = Path(__file__).resolve().parents[3]
    database_url = "sqlite:///" + str(root / database_url[len("sqlite:///./") :])
if database_url.startswith("postgres://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgres://") :]
elif database_url.startswith("postgresql://"):
    database_url = "postgresql+psycopg://" + database_url[len("postgresql://") :]

IS_SQLITE = database_url.startswith("sqlite")

engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if IS_SQLITE else {},
    pool_pre_ping=True,
)

if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _default_literal(column, dialect) -> str | None:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None
    value = default.arg
    if isinstance(value, bool):
        return ("1" if value else "0") if dialect.name == "sqlite" else ("true" if value else "false")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None


def sync_schema(bind=None) -> list[str]:
    """Create missing tables, then add any model columns the live tables lack."""
    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    added: list[str] = []
    inspector = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=bind.dialect)
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
                literal = _default_literal(column, bind.dialect)
                if literal is not None:
                    ddl += f" DEFAULT {literal}"
                conn.execute(text(ddl))
                added.append(f"{table.name}.{column.name}")
    if added:
        log.info("schema sync added columns: %s", ", ".join(added))
    return added


def ensure_sqlite_columns() -> None:
    """Backwards-compatible alias used by older entry points."""
    try:
        sync_schema()
    except Exception:  # pragma: no cover - never block startup on a best-effort sync
        log.exception("schema sync failed")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
