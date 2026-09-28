from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()
database_url = settings.database_url
if database_url.startswith("sqlite:///./"):
    # Resolve against the repository root for API and MCP stdio parity.
    root = Path(__file__).resolve().parents[3]
    database_url = "sqlite:///" + str(root / database_url[len("sqlite:///./") :])
engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False}
    if database_url.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def ensure_sqlite_columns() -> None:
    """Ensure newly added columns exist in SQLite for backwards-compatibility."""
    if not database_url.startswith("sqlite"):
        return
    try:
        with engine.connect() as conn:
            res = conn.exec_driver_sql("PRAGMA table_info(projects)")
            cols = {row[1] for row in res.fetchall()}
            if cols:
                if "bank_status" not in cols:
                    conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN bank_status VARCHAR(32) DEFAULT 'ready'")
                if "rulebook_cache" not in cols:
                    conn.exec_driver_sql("ALTER TABLE projects ADD COLUMN rulebook_cache TEXT")
                conn.commit()
    except Exception:
        pass


ensure_sqlite_columns()



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
