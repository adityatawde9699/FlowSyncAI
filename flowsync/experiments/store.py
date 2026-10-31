from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from flowsync.database import configured_database, connect

_log = logging.getLogger(__name__)


class ExperimentStore:
    """Store immutable experiment run outputs in SQLite or PostgreSQL."""
    def __init__(self, path: str | Path | None = None):
        self.database_url, self.path = configured_database(path)
        self._schema_ready = False
        try:
            self._ensure_schema()
        except Exception as exc:
            _log.warning("ExperimentStore: deferred schema init (DB not ready): %s", exc)

    def _ensure_schema(self):
        if self._schema_ready:
            return
        with connect(self.database_url, self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiment_runs (
                run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, scenario TEXT NOT NULL,
                seed INTEGER NOT NULL, controller TEXT NOT NULL, config_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL, created_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_runs_experiment ON experiment_runs(experiment_id)")
        self._schema_ready = True

    def save_run(self, run: dict[str, Any]) -> None:
        self._ensure_schema()
        with self._connect() as db:
            db.execute("INSERT INTO experiment_runs(run_id,experiment_id,scenario,seed,controller,config_json,metrics_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (run["run_id"], run["experiment_id"], run["scenario"], run["seed"], run["controller"],
                 json.dumps(run["config"], sort_keys=True), json.dumps(run["metrics"], sort_keys=True),
                 datetime.now(timezone.utc).isoformat()))

    def get_experiment(self, experiment_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._connect() as db:
            rows = db.execute("SELECT run_id,scenario,seed,controller,config_json,metrics_json,created_at FROM experiment_runs WHERE experiment_id=? ORDER BY scenario,seed,controller", (experiment_id,)).fetchall()
        return [{"run_id": r[0], "scenario": r[1], "seed": r[2], "controller": r[3],
                 "config": json.loads(r[4]), "metrics": json.loads(r[5]), "created_at": r[6]} for r in rows]

    def list_experiments(self) -> list[str]:
        self._ensure_schema()
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT experiment_id FROM experiment_runs GROUP BY experiment_id ORDER BY MIN(created_at) DESC")]

    def _connect(self):
        return connect(self.database_url, self.path)

