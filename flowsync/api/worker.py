"""Process-isolated simulation owner with a serialized request/response channel."""
from __future__ import annotations

import multiprocessing as mp
import threading
import uuid
from dataclasses import asdict
from typing import Any

from flowsync.models import SimulationConfig
from flowsync.simulation.factory import create_simulation
from flowsync.experiments.simulation_store import SimulationStore


def _run_worker(connection):
    simulation: TrafficSimulation | None = None
    simulation_id: str | None = None
    store = SimulationStore()
    paused = False
    try:
        while True:
            message = connection.recv()
            operation = message["op"]
            if operation == "shutdown":
                if simulation is not None and hasattr(simulation, "close"): simulation.close()
                if simulation is not None and simulation_id: store.status(simulation_id, "stopped")
                connection.send({"ok": True})
                return
            try:
                if operation == "start":
                    if simulation is not None:
                        if hasattr(simulation, "close"): simulation.close()
                        if simulation_id: store.status(simulation_id, "stopped")
                    simulation = create_simulation(message["config"])
                    paused = False
                    result = simulation.state()
                    simulation_id = store.start(asdict(simulation.config), simulation.config.engine,
                        simulation.config.controller.value, simulation.config.seed)
                    store.event(simulation_id, simulation.time, "simulation-started", {"engine": simulation.config.engine})
                elif simulation is None:
                    connection.send({"ok": False, "error": "No simulation is running"})
                    continue
                elif operation == "state": result = simulation.state()
                elif operation == "step":
                    if simulation.status == "running" and not paused: simulation.step()
                    result = simulation.state()
                    if simulation.time and simulation.time % 10 == 0:
                        store.sample(simulation_id, simulation.time, result.metrics)
                    if simulation.status == "finished": store.status(simulation_id, "finished")
                elif operation == "pause":
                    paused = True
                    result = simulation.state()
                    store.event(simulation_id, simulation.time, "paused", {})
                elif operation == "resume":
                    paused = False
                    result = simulation.state()
                    store.event(simulation_id, simulation.time, "resumed", {})
                elif operation == "stop":
                    simulation.status = "stopped"
                    paused = False
                    result = simulation.state()
                    if hasattr(simulation, "close"): simulation.close()
                    store.status(simulation_id, "stopped")
                    store.event(simulation_id, simulation.time, "stopped", {})
                elif operation == "controller":
                    simulation.config.controller = message["controller"]
                    result = simulation.state()
                    store.event(simulation_id, simulation.time, "controller-changed", {"controller": message["controller"].value})
                elif operation == "inject":
                    result = simulation.inject_incident(message["kind"], message["intersection_id"], message["approach"], message["severity"])
                    store.event(simulation_id, simulation.time, "incident-injected", asdict(result))
                elif operation == "remove":
                    incident = next((i for i in simulation.incidents if i.id == message["incident_id"]), None)
                    result = simulation.remove_incident(message["incident_id"])
                    if result and incident: store.event(simulation_id, simulation.time, "incident-removed", asdict(incident))
                elif operation == "emergency":
                    result = simulation.generate_emergency(message["kind"], message["at"])
                    store.event(simulation_id, simulation.time, "emergency-generated", asdict(result))
                else: raise ValueError(f"unknown worker operation: {operation}")
                connection.send({"ok": True, "result": result, "paused": paused,
                                 "engine": getattr(simulation.config, "engine", "fallback"),
                                 "simulation_id": simulation_id})
            except Exception as exc:
                connection.send({"ok": False, "error": str(exc)})
    except EOFError:
        return
    finally:
        connection.close()


class SimulationWorker:
    """Lazily starts one simulation child; API endpoints only exchange commands/state."""
    def __init__(self):
        self._ctx = mp.get_context("spawn")
        self._lock = threading.Lock()
        self._process = None
        self._connection = None

    def _ensure_started(self):
        if self._process is not None and self._process.is_alive(): return
        parent, child = self._ctx.Pipe()
        self._process = self._ctx.Process(target=_run_worker, args=(child,), name="flowsync-simulation", daemon=True)
        self._process.start()
        child.close()
        self._connection = parent

    def call(self, operation: str, **payload: Any):
        with self._lock:
            self._ensure_started()
            self._connection.send({"op": operation, **payload})
            response = self._connection.recv()
            if not response["ok"]: raise RuntimeError(response["error"])
            return response

    def shutdown(self):
        with self._lock:
            if self._process is None: return
            if self._process.is_alive():
                try:
                    self._connection.send({"op": "shutdown"})
                    self._connection.recv()
                finally:
                    self._process.join(timeout=3)
                    if self._process.is_alive(): self._process.terminate(); self._process.join()
            self._connection.close()
            self._connection = None
            self._process = None
