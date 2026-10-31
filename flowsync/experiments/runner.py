from __future__ import annotations

import csv
import json
import math
import statistics
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from flowsync.models import ControllerKind, IncidentKind, SimulationConfig, VehicleClass
from flowsync.simulation.factory import create_simulation
from flowsync.experiments.store import ExperimentStore


@dataclass(frozen=True)
class Scenario:
    name: str
    demand: int = 480
    pedestrians: int = 70
    asymmetric: bool = False
    incidents: tuple[str, ...] = ()
    emergency: bool = False


SCENARIOS = {
    "low-traffic": Scenario("low-traffic", 140, 25),
    "normal-traffic": Scenario("normal-traffic", 480, 70),
    "peak-hour": Scenario("peak-hour", 1200, 100),
    "asymmetric-traffic": Scenario("asymmetric-traffic", 700, 80, asymmetric=True),
    "road-blockage": Scenario("road-blockage", 650, 70, incidents=("lane-blockage",)),
    "emergency-movement": Scenario("emergency-movement", 480, 70, emergency=True),
    "multiple-incidents": Scenario("multiple-incidents", 800, 100, incidents=("lane-blockage", "capacity-reduction")),
    "communication-failure": Scenario("communication-failure", 700, 70, incidents=("communication-failure",)),
    "pedestrian-heavy": Scenario("pedestrian-heavy", 450, 650),
}

METRICS = ("mean_delay_seconds", "p95_delay_seconds", "average_queue_length", "maximum_queue_length",
           "throughput_vehicles", "emergency_vehicle_delay_seconds", "emergency_vehicle_travel_seconds",
           "pedestrian_wait_seconds", "incident_recovery_seconds", "controller_execution_ms")


class ExperimentRunner:
    def __init__(self, store: ExperimentStore | None = None):
        self.store = store or ExperimentStore()

    def run(self, scenarios: list[str] | None = None, seeds: list[int] | None = None,
            duration_seconds: int = 1800, controllers: list[ControllerKind] | None = None,
            experiment_id: str | None = None) -> dict[str, Any]:
        selected_scenarios = scenarios or list(SCENARIOS)
        selected_seeds = seeds or [11, 23, 37, 41, 53]
        selected_controllers = controllers or list(ControllerKind)
        unknown = set(selected_scenarios) - set(SCENARIOS)
        if unknown: raise ValueError(f"unknown scenarios: {', '.join(sorted(unknown))}")
        if not selected_seeds: raise ValueError("at least one seed is required")
        if duration_seconds < 60: raise ValueError("duration_seconds must be at least 60")
        experiment_id = experiment_id or str(uuid.uuid4())
        runs: list[dict[str, Any]] = []
        for scenario_name in selected_scenarios:
            scenario = SCENARIOS[scenario_name]
            for seed in selected_seeds:
                for controller in selected_controllers:
                    config = self._config(scenario, seed, duration_seconds, controller)
                    sim = create_simulation(config)
                    incident_ids: list[str] = []
                    clear_at = max(1, duration_seconds * 2 // 3)
                    incident_at = max(1, duration_seconds // 3)
                    emergency_at = max(1, duration_seconds // 4)
                    try:
                        for _ in range(duration_seconds):
                            if sim.time == incident_at:
                                for index, raw_kind in enumerate(scenario.incidents):
                                    kind = IncidentKind(raw_kind)
                                    intersection = f"J{1 + (index * 2) % 4}"
                                    approach = "N" if index % 2 == 0 else "E"
                                    incident_ids.append(sim.inject_incident(kind, intersection, approach, .7).id)
                            if sim.time == emergency_at and scenario.emergency:
                                sim.generate_emergency(VehicleClass.AMBULANCE, "J0")
                            if sim.time == clear_at:
                                for incident_id in incident_ids: sim.remove_incident(incident_id)
                            sim.step()
                        raw_metrics = sim.state().metrics
                        metric_data = {metric: raw_metrics.get(metric) for metric in METRICS}
                        metric_data["per_vehicle_class_mean_delay"] = raw_metrics.get("per_vehicle_class_mean_delay", {})
                    finally:
                        if hasattr(sim, "close"): sim.close()
                    run = {"run_id": str(uuid.uuid4()), "experiment_id": experiment_id,
                           "scenario": scenario_name, "seed": seed, "controller": controller.value,
                           "config": asdict(config), "metrics": metric_data}
                    # Enum values in dataclass dictionaries are not directly JSON serializable.
                    run["config"]["controller"] = controller.value
                    run["config"]["network"] = "flowsync-generated-5signal-grid-v1"
                    self.store.save_run(run)
                    runs.append(run)
        summary = summarize(runs)
        return {"experiment_id": experiment_id, "runs": runs, "summary": summary,
                "method": {"paired_by": ["scenario", "seed"], "confidence_interval": "two-sided Student-t 95% CI",
                           "duration_seconds": duration_seconds}}

    @staticmethod
    def _config(scenario: Scenario, seed: int, duration: int, controller: ControllerKind) -> SimulationConfig:
        approach_demand = {}
        if scenario.asymmetric:
            for i in range(5):
                for arm in "NSEW": approach_demand[f"J{i}:{arm}"] = scenario.demand * (2 if (i < 2 and arm in "EW") else .5 if (i > 2 and arm in "NS") else 1)
        composition = {"motorcycle": .38, "car": .32, "auto-rickshaw": .16, "bus": .06, "heavy": .08}
        return SimulationConfig(seed=seed, duration_seconds=duration, demand_per_hour=scenario.demand,
            pedestrian_per_hour=scenario.pedestrians, emergency_per_hour=0, approach_demand=approach_demand,
            controller=controller, vehicle_composition=composition)


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in runs: grouped.setdefault((run["scenario"], run["controller"]), []).append(run)
    result: dict[str, Any] = {}
    for (scenario, controller), group in grouped.items():
        metrics = {}
        for name in METRICS:
            vals = [r["metrics"][name] for r in group if isinstance(r["metrics"].get(name), (int, float))]
            if not vals: continue
            metrics[name] = _estimate(vals)
        class_names = {vehicle_class for run in group for vehicle_class in run["metrics"].get("per_vehicle_class_mean_delay", {})}
        if class_names:
            by_class = {}
            for vehicle_class in sorted(class_names):
                vals = [run["metrics"]["per_vehicle_class_mean_delay"][vehicle_class] for run in group
                        if vehicle_class in run["metrics"].get("per_vehicle_class_mean_delay", {})]
                by_class[vehicle_class] = _estimate(vals)
            metrics["per_vehicle_class_mean_delay"] = by_class
        result.setdefault(scenario, {})[controller] = metrics
    # Paired differences use identical seed demand traces to compare FlowSync with each baseline.
    by_pair = {}
    for scenario in sorted({run["scenario"] for run in runs}):
        seed_controller = {(run["seed"], run["controller"]): run for run in runs if run["scenario"] == scenario}
        controllers = sorted({run["controller"] for run in runs if run["scenario"] == scenario})
        by_pair[scenario] = {}
        for controller in controllers:
            if controller == ControllerKind.FLOWSYNC.value: continue
            differences = {}
            for metric in METRICS:
                samples = []
                for seed in sorted({run["seed"] for run in runs if run["scenario"] == scenario}):
                    adaptive = seed_controller.get((seed, ControllerKind.FLOWSYNC.value))
                    baseline = seed_controller.get((seed, controller))
                    if not adaptive or not baseline: continue
                    a, b = adaptive["metrics"].get(metric), baseline["metrics"].get(metric)
                    if isinstance(a, (int, float)) and isinstance(b, (int, float)): samples.append(a-b)
                if samples: differences[metric] = _estimate(samples, nonnegative=False)
            by_pair[scenario][f"flowsync-minus-{controller}"] = differences
    result["paired_differences"] = by_pair
    return result


_T95 = {1:12.706,2:4.303,3:3.182,4:2.776,5:2.571,6:2.447,7:2.365,8:2.306,9:2.262,
        10:2.228,11:2.201,12:2.179,13:2.160,14:2.145,15:2.131,16:2.120,17:2.110,
        18:2.101,19:2.093,20:2.086,21:2.080,22:2.074,23:2.069,24:2.064,25:2.060,
        26:2.056,27:2.052,28:2.048,29:2.045}


def _estimate(values: list[float], nonnegative: bool = True):
    mean = statistics.fmean(values)
    if len(values) < 2: return {"mean": mean, "stddev": 0.0, "n": len(values), "ci95": None}
    sd = statistics.stdev(values)
    critical = _T95.get(len(values)-1, 1.96)
    margin = critical * sd / math.sqrt(len(values))
    lower, upper = mean-margin, mean+margin
    if nonnegative: lower = max(0.0, lower)
    return {"mean": mean, "stddev": sd, "n": len(values), "ci95": [lower, upper]}


def export_report(runs: list[dict[str, Any]], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8") as file:
            fields = ["run_id", "experiment_id", "scenario", "seed", "controller", *METRICS, "class_delay_json"]
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for run in runs:
                writer.writerow({**{k: run[k] for k in fields[:5]}, **{k: run["metrics"].get(k) for k in METRICS},
                                 "class_delay_json": json.dumps(run["metrics"].get("per_vehicle_class_mean_delay", {}), sort_keys=True)})
    else:
        path.write_text(json.dumps({"runs": runs, "summary": summarize(runs)}, indent=2), encoding="utf-8")
    return path
