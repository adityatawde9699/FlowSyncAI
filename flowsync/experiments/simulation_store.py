"""Persistence for simulation manifests, events, sampled metrics and observations."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flowsync.database import configured_database, connect


class SimulationStore:
    def __init__(self, path: str | Path | None = None):
        self.database_url, self.path = configured_database(path)
        self._schema_ready = False
        try:
            self._ensure_schema()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("SimulationStore: deferred schema init (DB not ready): %s", exc)

    def _ensure_schema(self):
        if self._schema_ready:
            return
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS simulations (
                    simulation_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
                    seed INTEGER NOT NULL, engine TEXT NOT NULL, controller TEXT NOT NULL,
                    status TEXT NOT NULL, config_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS simulation_events (
                    event_id TEXT PRIMARY KEY, simulation_id TEXT NOT NULL, sim_time INTEGER NOT NULL,
                    kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                    FOREIGN KEY(simulation_id) REFERENCES simulations(simulation_id));
                CREATE TABLE IF NOT EXISTS simulation_samples (
                    sample_id TEXT PRIMARY KEY, simulation_id TEXT NOT NULL, sim_time INTEGER NOT NULL,
                    metrics_json TEXT NOT NULL,
                    FOREIGN KEY(simulation_id) REFERENCES simulations(simulation_id));
                CREATE TABLE IF NOT EXISTS traffic_observations (
                    observation_id TEXT PRIMARY KEY, simulation_id TEXT NOT NULL, sim_time REAL,
                    source TEXT NOT NULL, confidence REAL NOT NULL, intersection_id TEXT NOT NULL,
                    approach TEXT NOT NULL, observation_json TEXT NOT NULL,
                    FOREIGN KEY(simulation_id) REFERENCES simulations(simulation_id));
                CREATE INDEX IF NOT EXISTS idx_sim_events ON simulation_events(simulation_id,sim_time);
                CREATE INDEX IF NOT EXISTS idx_sim_samples ON simulation_samples(simulation_id,sim_time);
            """)
        self._schema_ready = True

    def start(self, config: dict[str, Any], engine: str, controller: str, seed: int) -> str:
        self._ensure_schema()
        ident = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO simulations(simulation_id,started_at,seed,engine,controller,status,config_json) VALUES(?,?,?,?,?,?,?)",
                (ident, datetime.now(timezone.utc).isoformat(), seed, engine, controller, "running", _json(config)))
        return ident

    def event(self, simulation_id: str, sim_time: int, kind: str, payload: Any):
        self._ensure_schema()
        with self._connect() as db:
            db.execute("INSERT INTO simulation_events VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), simulation_id, sim_time, kind, _json(payload)))

    def sample(self, simulation_id: str, sim_time: int, metrics: dict):
        self._ensure_schema()
        with self._connect() as db:
            db.execute("INSERT INTO simulation_samples VALUES(?,?,?,?)",
                (str(uuid.uuid4()), simulation_id, sim_time, _json(metrics)))

    def status(self, simulation_id: str, status: str):
        self._ensure_schema()
        with self._connect() as db:
            db.execute("UPDATE simulations SET status=?, ended_at=? WHERE simulation_id=?",
                (status, datetime.now(timezone.utc).isoformat() if status in ("finished", "stopped", "failed") else None, simulation_id))

    def observation(self, simulation_id: str, observation):
        self._ensure_schema()
        payload = {"vehicle_counts": observation.vehicle_counts, "queue_estimate": observation.queue_estimate,
                   "density": observation.density}
        with self._connect() as db:
            db.execute("INSERT INTO traffic_observations VALUES(?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), simulation_id, observation.timestamp_seconds, observation.source,
                 observation.confidence, observation.intersection_id, observation.approach, _json(payload)))

    def get_history(self, simulation_id: str):
        self._ensure_schema()
        with self._connect() as db:
            session = db.execute("SELECT simulation_id,started_at,ended_at,seed,engine,controller,status,config_json FROM simulations WHERE simulation_id=?", (simulation_id,)).fetchone()
            if session is None: return None
            events = db.execute("SELECT sim_time,kind,payload_json FROM simulation_events WHERE simulation_id=? ORDER BY sim_time,event_id", (simulation_id,)).fetchall()
            samples = db.execute("SELECT sim_time,metrics_json FROM simulation_samples WHERE simulation_id=? ORDER BY sim_time,sample_id", (simulation_id,)).fetchall()
            observations = db.execute("SELECT sim_time,source,confidence,intersection_id,approach,observation_json FROM traffic_observations WHERE simulation_id=? ORDER BY sim_time,observation_id", (simulation_id,)).fetchall()
        return {"simulation_id": session[0], "started_at": session[1], "ended_at": session[2], "seed": session[3],
            "engine": session[4], "controller": session[5], "status": session[6], "config": json.loads(session[7]),
            "events": [{"time": r[0], "kind": r[1], "payload": json.loads(r[2])} for r in events],
            "samples": [{"time": r[0], "metrics": json.loads(r[1])} for r in samples],
            "observations": [{"time": r[0], "source": r[1], "confidence": r[2], "intersection_id": r[3],
                              "approach": r[4], "data": json.loads(r[5])} for r in observations]}

    def _connect(self):
        return connect(self.database_url, self.path)


def _json(value):
    return json.dumps(value, sort_keys=True, default=lambda obj: obj.value if hasattr(obj, "value") else str(obj))
