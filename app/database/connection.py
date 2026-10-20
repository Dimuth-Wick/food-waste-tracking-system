"""Database engine and per-request sessions.

The engine comes from settings["DATABASE_URL"], so the same code runs on the
local SQLite file or on PostgreSQL. Each request gets its own session through
the ``get_session`` FastAPI dependency.
"""

from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.database.tables import Base


def create_database_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _enforce_foreign_keys(connection, _record):
            # SQLite ignores foreign keys unless each connection turns them on.
            connection.execute("PRAGMA foreign_keys = ON")

        return engine
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_session(request: Request):
    """FastAPI dependency: one database session per request, always closed."""
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def init_db(engine: Engine) -> None:
    """Create any missing tables and indexes. Safe to run more than once."""
    Base.metadata.create_all(engine)
