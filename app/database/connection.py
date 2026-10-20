import sqlite3
from pathlib import Path

import click
from flask import current_app, g


SCHEMA_VERSION = 1


def get_db():
    if "db" not in g:
        database = Path(current_app.config["DATABASE"])
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db


def close_db(error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def init_db():
    connection = get_db()
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version != 0:
        raise RuntimeError(f"Unsupported database schema version: {version}")

    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


@click.command("init-db")
@click.option("--seed", is_flag=True, help="Add synthetic development data.")
def init_db_command(seed):
    """Initialize the local SQLite database."""
    init_db()
    click.echo("Database schema ready.")
    if seed:
        from app.database.seed import seed_demo_data

        credentials = seed_demo_data(get_db())
        click.echo("Synthetic demo data added. Save these one-time passwords:")
        for username, password in credentials.items():
            click.echo(f"  {username}: {password}")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
