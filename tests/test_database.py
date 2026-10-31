from __future__ import annotations

from flowsync.database import configured_database


def test_database_url_takes_precedence_over_sqlite_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/flowsync")
    monkeypatch.setenv("FLOWSYNC_EXPERIMENT_DB", str(tmp_path / "local.sqlite3"))

    url, path = configured_database()

    assert url == "postgresql://example.invalid/flowsync"
    assert path is None


def test_explicit_path_forces_sqlite_even_if_database_url_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/flowsync")
    sqlite_path = tmp_path / "nested" / "local.sqlite3"

    url, path = configured_database(sqlite_path)

    assert url is None
    assert path == sqlite_path
    assert sqlite_path.parent.is_dir()


def test_sqlite_environment_path_is_the_local_default(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    configured_path = tmp_path / "experiments.sqlite3"
    monkeypatch.setenv("FLOWSYNC_EXPERIMENT_DB", str(configured_path))

    url, path = configured_database()

    assert url is None
    assert path == configured_path
    assert configured_path.parent.is_dir()
