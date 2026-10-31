"""Small SQLite/PostgreSQL connection adapter used by the persistence stores."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator


try:
    import psycopg
    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:  # PostgreSQL support is optional for local SQLite installs.
    psycopg = None
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)


class DatabaseConnection:
    """Expose the small common subset of sqlite3/psycopg used by this project."""

    def __init__(self, connection: Any, postgres: bool):
        self._connection = connection
        self._postgres = postgres

    def execute(self, statement: str, parameters=()):
        if self._postgres:
            statement = statement.replace("?", "%s")
        return self._connection.execute(statement, parameters)

    def executescript(self, script: str) -> None:
        if not self._postgres:
            self._connection.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)


def configured_database(path: str | Path | None = None) -> tuple[str | None, Path | None]:
    """Resolve storage: explicit paths force SQLite; otherwise DATABASE_URL wins."""
    if path is None:
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            return database_url, None
        path = os.environ.get("FLOWSYNC_EXPERIMENT_DB", ".flowsync/experiments.sqlite3")
    sqlite_path = Path(path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return None, sqlite_path


@contextmanager
def connect(database_url: str | None, sqlite_path: Path | None) -> Iterator[DatabaseConnection]:
    if database_url:
        if psycopg is None:
            raise RuntimeError("DATABASE_URL is set; install PostgreSQL support with `pip install -e '.[postgres]'`")
        # Neon DB (serverless PostgreSQL) requires SSL and has cold starts;
        # add sslmode if not already specified and retry on transient failures.
        connect_kwargs: dict[str, Any] = {"conninfo": database_url, "connect_timeout": 30}
        if "sslmode" not in database_url:
            connect_kwargs["conninfo"] += ("&" if "?" in database_url else "?") + "sslmode=require"
        import time, logging
        _log = logging.getLogger(__name__)
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                connection = psycopg.connect(**connect_kwargs)
                break
            except (psycopg.OperationalError, OSError) as exc:
                last_exc = exc
                _log.warning("Database connection attempt %d/3 failed: %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
        else:
            raise RuntimeError(f"Failed to connect to database after 3 attempts: {last_exc}") from last_exc
        try:
            with connection:
                yield DatabaseConnection(connection, postgres=True)
        finally:
            connection.close()
        return

    if sqlite_path is None:
        raise RuntimeError("No database URL or SQLite path is configured")
    connection = sqlite3.connect(sqlite_path, timeout=30)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        with connection:
            yield DatabaseConnection(connection, postgres=False)
    finally:
        connection.close()
