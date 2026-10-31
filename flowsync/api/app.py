"""HTTP control API. Simulation state and stepping live in a separate worker process."""
import asyncio
from concurrent.futures import ProcessPoolExecutor
import os
import re
import uuid

try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except ImportError as exc:
    raise RuntimeError("Install FlowSync with `pip install -e '.[api]'` to use the HTTP API") from exc

from flowsync.api.worker import SimulationWorker
from flowsync.database import INTEGRITY_ERRORS
from flowsync.experiments.runner import ExperimentRunner, SCENARIOS, summarize
from flowsync.experiments.simulation_store import SimulationStore
from flowsync.experiments.store import ExperimentStore
from flowsync.logging_config import configure_logging
from flowsync.models import ControllerKind, IncidentKind, SimulationConfig, VehicleClass

app = FastAPI(title="FlowSync AI", description="Simulation only; never controls public signals.", version="0.2.0")
configure_logging()
cors_origins = [origin.strip() for origin in os.environ.get(
    "FLOWSYNC_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,https://flowsyncaiseva.vercel.app"
).split(",") if origin.strip()]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins,
                   allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                   allow_headers=["*"],
                   allow_origin_regex=r"https://.*\.vercel\.app")
worker = SimulationWorker()
experiment_pool = ProcessPoolExecutor(max_workers=1)
experiment_jobs = {}
experiment_store = ExperimentStore()


class StartRequest(BaseModel):
    seed: int = 7
    duration_seconds: int = Field(default=1800, ge=60, le=86400)
    demand_per_hour: int = Field(default=480, ge=0, le=10000)
    pedestrian_per_hour: int = Field(default=70, ge=0, le=10000)
    emergency_per_hour: int = Field(default=4, ge=0, le=1000)
    vehicle_composition: dict[str, float] = Field(default_factory=lambda: {
        "motorcycle":.39,"car":.33,"auto-rickshaw":.16,"bus":.06,"heavy":.06})
    approach_demand: dict[str, int] = Field(default_factory=dict)
    controller: ControllerKind = ControllerKind.FLOWSYNC
    engine: str = Field(default="auto", pattern="^(auto|sumo|fallback)$")


class IncidentRequest(BaseModel):
    kind: IncidentKind
    intersection_id: str = "J2"
    approach: str = Field(default="N", pattern="^[NSEW]$")
    severity: float = Field(default=.5, ge=0, le=1)


class EmergencyRequest(BaseModel):
    kind: VehicleClass = VehicleClass.AMBULANCE
    intersection_id: str = "J0"


class ExperimentRequest(BaseModel):
    scenarios: list[str] = Field(default_factory=lambda: list(SCENARIOS), min_length=1)
    seeds: list[int] = Field(default_factory=lambda: [11, 23, 37, 41, 53], min_length=1)
    duration_seconds: int = Field(default=1800, ge=60, le=86400)
    controllers: list[ControllerKind] = Field(default_factory=lambda: list(ControllerKind), min_length=1)


class ObservationRequest(BaseModel):
    simulation_id: str
    intersection_id: str
    approach: str = Field(pattern="^[NSEW]$")
    source: str = Field(pattern="^(simulation|video:[a-z0-9_-]+)$")
    confidence: float = Field(ge=0, le=1)
    vehicle_counts: dict[str, int] = Field(default_factory=dict)
    queue_estimate: int | None = Field(default=None, ge=0)
    density: float | None = Field(default=None, ge=0)
    timestamp_seconds: float | None = Field(default=None, ge=0)


def _call(operation: str, **payload):
    try: return worker.call(operation, **payload)
    except RuntimeError as exc:
        status = 409 if "No simulation" in str(exc) else 422
        raise HTTPException(status, str(exc)) from exc


def _snapshot(response: dict):
    state = response["result"]
    return {"time": state.time, "simulation_id": response.get("simulation_id"), "engine": response.get("engine", "fallback"), "status": "paused" if response.get("paused") else state.status,
            "vehicles_passed": state.vehicles_passed, "metrics": state.metrics,
            "intersections": [{"id": n.id, "phase": n.phase, "stage": n.stage,
                "queues": {arm: len(queue) for arm, queue in n.queues.items()},
                "pedestrian_wait": n.pedestrian_wait, "communication": n.communication,
                "decision": n.last_decision} for n in state.intersections],
            "incidents": [{"id": i.id, "kind": i.kind.value, "intersection_id": i.intersection_id,
                "approach": i.approach, "severity": i.severity} for i in state.active_incidents],
            "emergency_vehicles": state.emergency_vehicles}

@app.on_event("startup")
def verify_database():
    """Verify database connectivity on startup to surface config errors early."""
    import logging
    _log = logging.getLogger(__name__)
    db_url, sqlite_path = experiment_store.database_url, experiment_store.path
    _log.info("Database config: url=%s sqlite=%s", "set" if db_url else "none", sqlite_path)
    try:
        from flowsync.database import connect
        with connect(db_url, sqlite_path) as conn:
            conn.execute("SELECT 1")
        _log.info("Database connection verified successfully")
    except Exception as exc:
        _log.error("Database connection failed at startup: %s", exc)


@app.on_event("shutdown")
def shutdown_worker():
    worker.shutdown()
    experiment_pool.shutdown(wait=False, cancel_futures=True)


@app.get("/health")
def health():
    """Platform health probe; does not start or mutate a simulation."""
    return {"status": "ok"}


@app.post("/api/simulations", status_code=201)
def start(request: StartRequest):
    allowed_classes = {"motorcycle", "car", "auto-rickshaw", "bus", "heavy"}
    if not request.vehicle_composition or set(request.vehicle_composition)-allowed_classes:
        raise HTTPException(422, "vehicle composition must use motorcycle, car, auto-rickshaw, bus and/or heavy")
    if any(weight < 0 for weight in request.vehicle_composition.values()) or sum(request.vehicle_composition.values()) <= 0:
        raise HTTPException(422, "vehicle composition weights must be non-negative with a positive total")
    if any(not re.fullmatch(r"J[0-4]:[NSEW]", key) or value < 0
           for key, value in request.approach_demand.items()):
        raise HTTPException(422, "approach demand keys must match J0:N through J4:W and values must be non-negative")
    config = SimulationConfig(seed=request.seed, duration_seconds=request.duration_seconds,
        demand_per_hour=request.demand_per_hour, pedestrian_per_hour=request.pedestrian_per_hour,
        emergency_per_hour=request.emergency_per_hour, vehicle_composition=request.vehicle_composition,
        approach_demand=request.approach_demand, controller=request.controller, engine=request.engine)
    return _snapshot(_call("start", config=config))


@app.post("/api/simulations/step")
def step(): return _snapshot(_call("step"))


@app.post("/api/simulations/pause")
def pause(): return _snapshot(_call("pause"))


@app.post("/api/simulations/resume")
def resume(): return _snapshot(_call("resume"))


@app.post("/api/simulations/stop")
def stop(): return _snapshot(_call("stop"))


@app.put("/api/simulations/controller/{controller}")
def set_controller(controller: ControllerKind):
    return _snapshot(_call("controller", controller=controller))


@app.post("/api/incidents", status_code=201)
def inject(request: IncidentRequest):
    response = _call("inject", kind=request.kind, intersection_id=request.intersection_id,
                     approach=request.approach, severity=request.severity)
    return {"incident_id": response["result"].id, **_snapshot(_call("state"))}


@app.delete("/api/incidents/{incident_id}")
def remove(incident_id: str):
    response = _call("remove", incident_id=incident_id)
    if not response["result"]: raise HTTPException(404, "Active incident not found")
    return _snapshot(_call("state"))


@app.post("/api/emergency-vehicles", status_code=201)
def emergency(request: EmergencyRequest):
    if request.kind not in (VehicleClass.AMBULANCE, VehicleClass.FIRE, VehicleClass.POLICE):
        raise HTTPException(422, "kind must be ambulance, fire, or police")
    response = _call("emergency", kind=request.kind, at=request.intersection_id)
    vehicle = response["result"]
    return {"vehicle_id": vehicle.id, "kind": vehicle.kind.value, "approach": vehicle.approach,
            **_snapshot(_call("state"))}


@app.get("/api/state")
def get_state(): return _snapshot(_call("state"))


@app.get("/api/simulations/{simulation_id}/history")
def simulation_history(simulation_id: str):
    history = SimulationStore().get_history(simulation_id)
    if history is None: raise HTTPException(404, "Simulation history not found")
    return history


@app.post("/api/observations", status_code=201)
def save_observation(request: ObservationRequest):
    if not request.intersection_id.startswith("J") or request.intersection_id[1:] not in {str(i) for i in range(5)}:
        raise HTTPException(422, "intersection_id must be J0 through J4")
    from flowsync.perception.pipeline import TrafficObservation
    observation = TrafficObservation(request.intersection_id, request.approach, request.source,
        request.confidence, request.vehicle_counts, request.queue_estimate, request.density,
        request.timestamp_seconds)
    if any(value < 0 for value in request.vehicle_counts.values()):
        raise HTTPException(422, "vehicle counts must be non-negative")
    try: SimulationStore().observation(request.simulation_id, observation)
    except INTEGRITY_ERRORS as exc: raise HTTPException(404, "Simulation history not found") from exc
    return {"status": "stored", "source": request.source, "simulation_id": request.simulation_id}


def _run_experiment_process(experiment_id, request_data):
    store = ExperimentStore()
    return ExperimentRunner(store).run(scenarios=request_data["scenarios"], seeds=request_data["seeds"],
        duration_seconds=request_data["duration_seconds"],
        controllers=[ControllerKind(controller) for controller in request_data["controllers"]],
        experiment_id=experiment_id)


@app.post("/api/experiments", status_code=202)
def start_experiment(request: ExperimentRequest):
    unknown = set(request.scenarios) - set(SCENARIOS)
    if unknown: raise HTTPException(422, f"unknown scenarios: {', '.join(sorted(unknown))}")
    experiment_id = str(uuid.uuid4())
    payload = request.model_dump()
    payload["controllers"] = [c.value for c in request.controllers]
    future = experiment_pool.submit(_run_experiment_process, experiment_id, payload)
    experiment_jobs[experiment_id] = future
    return {"experiment_id": experiment_id, "status": "queued"}


@app.get("/api/experiments/{experiment_id}")
def experiment_status(experiment_id: str):
    future = experiment_jobs.get(experiment_id)
    if future is None: raise HTTPException(404, "Experiment not found in this API process")
    if not future.done(): return {"experiment_id": experiment_id, "status": "running"}
    try: result = future.result()
    except Exception as exc:
        return {"experiment_id": experiment_id, "status": "failed", "error": str(exc)}
    return {"experiment_id": experiment_id, "status": "complete", "summary": result["summary"],
            "run_count": len(result["runs"]), "method": result["method"]}


@app.get("/api/experiments/{experiment_id}/results")
def experiment_results(experiment_id: str):
    runs = experiment_store.get_experiment(experiment_id)
    if not runs: raise HTTPException(404, "Experiment results not found")
    return {"experiment_id": experiment_id, "runs": runs, "summary": summarize(runs)}


@app.get("/api/experiments/{experiment_id}/report")
def experiment_report(experiment_id: str, format: str = "json"):
    runs = experiment_store.get_experiment(experiment_id)
    if not runs: raise HTTPException(404, "Experiment results not found")
    if format not in ("json", "csv"): raise HTTPException(422, "format must be json or csv")
    from fastapi.responses import Response
    if format == "csv":
        import csv, io
        from flowsync.experiments.runner import METRICS
        output = io.StringIO()
        fields = ["run_id", "experiment_id", "scenario", "seed", "controller", *METRICS, "class_delay_json"]
        writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
        for run in runs:
            import json
            writer.writerow({**{k: run[k] for k in fields[:5]}, **{k: run["metrics"].get(k) for k in METRICS},
                "class_delay_json": json.dumps(run["metrics"].get("per_vehicle_class_mean_delay", {}), sort_keys=True)})
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=flowsync-{experiment_id}.csv"})
    import json
    return Response(json.dumps({"experiment_id": experiment_id, "runs": runs, "summary": summarize(runs)}, indent=2),
        media_type="application/json", headers={"Content-Disposition": f"attachment; filename=flowsync-{experiment_id}.json"})


@app.websocket("/api/stream")
async def stream(socket: WebSocket):
    await socket.accept()
    try:
        while True:
            try:
                response = await asyncio.to_thread(worker.call, "step")
                await socket.send_json(_snapshot(response))
            except RuntimeError as exc:
                if "No simulation" in str(exc): await socket.send_json({"status": "idle"})
                else: await socket.send_json({"status": "error", "detail": str(exc)})
            except Exception as exc:
                # A dead worker pipe (for example after a platform restart) must not
                # immediately tear down the browser stream; the next call can restart it.
                await socket.send_json({"status": "error", "detail": str(exc)})
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(.25)
    except WebSocketDisconnect:
        return
