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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
