"""Shared test helpers: an app on a temporary SQLite file, its database, a client."""

from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import create_app
from app.database.connection import init_db


def make_app(tmp_path, name="test.sqlite3", *, initialize=True, **config):
    """A test app using its own SQLite file. Tables are created unless initialize=False."""
    # Sign-in is off in tests unless a test turns it on (REQUIRE_LOGIN=True).
    app = create_app({"TESTING": True, "REQUIRE_LOGIN": False, "DATABASE": str(tmp_path / name), **config})
    if initialize:
        init_db(app.state.engine)
    return app


@contextmanager
def database(app):
    """A database session for arranging and checking test data."""
    session = app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


def client(app):
    """A test client that returns redirects instead of following them."""
    return TestClient(app, follow_redirects=False)


def sql(db, query, **params):
    """Run raw SQL and return the result."""
    return db.execute(text(query), params)


def scalar(db, query, **params):
    return db.execute(text(query), params).scalar()


def add_lookups(db, names_by_table):
    for table, names in names_by_table.items():
        for name in names:
            sql(db, f"INSERT INTO {table} (name, active) VALUES (:name, 1)", name=name)
    db.commit()
