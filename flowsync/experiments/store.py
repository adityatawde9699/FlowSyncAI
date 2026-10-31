from __future__ import annotations

import json
import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class ExperimentStore:
    """Small SQLite record store for immutable experiment run outputs."""
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("FLOWSYNC_EXPERIMENT_DB", ".flowsync/experiments.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiment_runs (
                run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, scenario TEXT NOT NULL,
                seed INTEGER NOT NULL, controller TEXT NOT NULL, config_json TEXT NOT NULL,
                metrics_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_runs_experiment ON experiment_runs(experiment_id)")

    def save_run(self, run: dict[str, Any]) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO experiment_runs(run_id,experiment_id,scenario,seed,controller,config_json,metrics_json) VALUES(?,?,?,?,?,?,?)",
                (run["run_id"], run["experiment_id"], run["scenario"], run["seed"], run["controller"],
                 json.dumps(run["config"], sort_keys=True), json.dumps(run["metrics"], sort_keys=True)))

    def get_experiment(self, experiment_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT run_id,scenario,seed,controller,config_json,metrics_json,created_at FROM experiment_runs WHERE experiment_id=? ORDER BY scenario,seed,controller", (experiment_id,)).fetchall()
        return [{"run_id": r[0], "scenario": r[1], "seed": r[2], "controller": r[3],
                 "config": json.loads(r[4]), "metrics": json.loads(r[5]), "created_at": r[6]} for r in rows]

    def list_experiments(self) -> list[str]:
        with self._connect() as db:
            return [row[0] for row in db.execute("SELECT experiment_id FROM experiment_runs GROUP BY experiment_id ORDER BY MIN(created_at) DESC")]

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection: yield connection
        finally:
            connection.close()
