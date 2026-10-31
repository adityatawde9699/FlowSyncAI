from flowsync.models import ControllerKind, IncidentKind, SimulationConfig
from flowsync.safety import SignalSafety
from flowsync.simulation.engine import TrafficSimulation
from flowsync.experiments.runner import ExperimentRunner, export_report, summarize
from flowsync.experiments.store import ExperimentStore


def test_minimum_green_and_clearance_are_enforced():
    class Node:
        phase = "NS"; stage = "green"; stage_elapsed = 0; green_elapsed = 0
        pending_phase = None; pending_pedestrian = False
    node = Node()
    safety = SignalSafety()
    assert not safety.request_phase(node, "EW")
    node.green_elapsed = safety.config.min_green
    assert safety.request_phase(node, "EW")
    assert node.stage == "yellow"
    for _ in range(safety.config.yellow): safety.advance(node)
    assert node.stage == "all-red"
    for _ in range(safety.config.all_red): safety.advance(node)
    assert node.phase == "EW" and node.stage == "green"


def test_pedestrian_service_has_all_red_walk_and_clearance():
    from flowsync.models import Intersection
    safety = SignalSafety()
    node = Intersection("J0", 0)
    node.green_elapsed = safety.config.min_green
    assert safety.request_pedestrian_service(node)
    for _ in range(safety.config.yellow): safety.advance(node)
    assert node.stage == "all-red"
    assert safety.green_approaches(node) == set()
    for _ in range(safety.config.all_red): safety.advance(node)
    assert node.stage == "ped-walk"
    assert safety.green_approaches(node) == set()
    for _ in range(safety.config.pedestrian_walk): safety.advance(node)
    assert node.stage == "ped-clearance"
    for _ in range(safety.config.pedestrian_clearance): safety.advance(node)
    assert node.stage == "green" and node.phase == "NS"


def test_five_intersection_run_is_reproducible():
    config = SimulationConfig(seed=41, duration_seconds=120, demand_per_hour=900,
                              controller=ControllerKind.FLOWSYNC)
    first = TrafficSimulation(config).run()
    second = TrafficSimulation(config).run()
    assert len(first.intersections) == 5
    assert {k: v for k, v in first.metrics.items() if k != "controller_execution_ms"} == {
        k: v for k, v in second.metrics.items() if k != "controller_execution_ms"}
    assert first.vehicles_passed == second.vehicles_passed


def test_generated_vehicle_is_enqueued_exactly_once():
    config = SimulationConfig(seed=41, duration_seconds=60, demand_per_hour=3600,
                              pedestrian_per_hour=0, emergency_per_hour=0)
    sim = TrafficSimulation(config)
    sim._generate_demand()
    queued = [vehicle for node in sim.intersections for queue in node.queues.values() for vehicle in queue]
    assert len(queued) == len(sim.arrivals) == 20
    assert len({vehicle.id for vehicle in queued}) == len(queued)


def test_controller_comparison_uses_identical_arrival_traces():
    base = dict(seed=12, duration_seconds=180, demand_per_hour=900, pedestrian_per_hour=80)
    fixed = TrafficSimulation(SimulationConfig(**base, controller=ControllerKind.FIXED))
    flowsync = TrafficSimulation(SimulationConfig(**base, controller=ControllerKind.FLOWSYNC))
    fixed.run(); flowsync.run()
    assert fixed.arrivals == flowsync.arrivals


def test_incident_injection_removal_and_communication_fallback():
    sim = TrafficSimulation(SimulationConfig(duration_seconds=60))
    incident = sim.inject_incident(IncidentKind.COMMUNICATION, "J2")
    assert not sim.intersections[2].communication
    sim.step()
    assert "max-pressure" in sim.intersections[2].local_fallback
    assert sim.remove_incident(incident.id)
    assert sim.intersections[2].communication
    assert sim.state().metrics["incident_recovery_seconds"] == 0


def test_intersection_agent_uses_neighbors_only_while_communication_is_up():
    from flowsync.control.agent import IntersectionAgent
    from flowsync.models import Intersection
    node, neighbor = Intersection("J1", 1), Intersection("J2", 2)
    agent = IntersectionAgent("J1")
    decision = agent.decide(node, ControllerKind.FLOWSYNC, 0, [node, neighbor], [])
    assert decision.neighbor_count == 1 and decision.controller == ControllerKind.FLOWSYNC
    node.communication = False
    fallback = agent.decide(node, ControllerKind.FLOWSYNC, 0, [node, neighbor], [])
    assert fallback.neighbor_count == 0 and fallback.controller == ControllerKind.MAX_PRESSURE


def test_blockage_is_removed_with_incident():
    sim = TrafficSimulation()
    incident = sim.inject_incident(IncidentKind.BLOCKAGE, "J1", "W")
    assert "W" in sim.intersections[1].blocked_approaches
    assert sim.remove_incident(incident.id)
    assert "W" not in sim.intersections[1].blocked_approaches


def test_emergency_priority_waits_for_a_safe_phase_transition():
    sim = TrafficSimulation(SimulationConfig(seed=3, duration_seconds=120, demand_per_hour=0,
                                              pedestrian_per_hour=0, controller=ControllerKind.FLOWSYNC))
    vehicle = sim.generate_emergency(at="J0")
    assert "W" not in sim.safety.green_approaches(sim.intersections[0])
    sim.step()
    assert any(v.id == vehicle.id for v in sim.intersections[0].queues["W"])
    assert sim.emergency_trip_samples == []
    sim.run()
    assert sim.emergency_trip_samples
    assert sim.intersections[0].stage in {"green", "yellow", "all-red", "ped-walk", "ped-clearance"}


def test_simulation_worker_owns_run_in_separate_process(tmp_path, monkeypatch):
    import os
    from flowsync.api.worker import SimulationWorker
    from flowsync.experiments.simulation_store import SimulationStore
    monkeypatch.setenv("FLOWSYNC_EXPERIMENT_DB", str(tmp_path / "simulation.sqlite3"))
    worker = SimulationWorker()
    try:
        started = worker.call("start", config=SimulationConfig(seed=5, duration_seconds=60,
            demand_per_hour=0, pedestrian_per_hour=0, engine="fallback"))
        assert started["result"].time == 0
        assert worker._process.pid != os.getpid()
        stepped = worker.call("step")
        assert stepped["result"].time == 1
        assert worker.call("pause")["paused"] is True
        stopped = worker.call("stop")
        assert stopped["result"].status == "stopped" and stopped["paused"] is False
        history = SimulationStore(tmp_path / "simulation.sqlite3").get_history(started["simulation_id"])
        assert history["seed"] == 5 and history["status"] == "stopped"
        assert any(event["kind"] == "simulation-started" for event in history["events"])
    finally:
        worker.shutdown()


def test_paired_experiment_persists_results_and_confidence_intervals(tmp_path):
    store = ExperimentStore(tmp_path / "runs.sqlite3")
    result = ExperimentRunner(store).run(scenarios=["low-traffic"], seeds=[19, 23], duration_seconds=60,
        controllers=[ControllerKind.FIXED, ControllerKind.FLOWSYNC], experiment_id="test-exp")
    assert len(result["runs"]) == 4
    persisted = store.get_experiment("test-exp")
    assert len(persisted) == 4
    confidence = result["summary"]["low-traffic"]["flowsync"]["mean_delay_seconds"]["ci95"]
    assert len(confidence) == 2 and confidence[0] <= confidence[1]
    paired = result["summary"]["paired_differences"]["low-traffic"]["flowsync-minus-fixed-time"]
    assert paired["mean_delay_seconds"]["n"] == 2
    csv_file = export_report(result["runs"], tmp_path / "report.csv")
    assert "class_delay_json" in csv_file.read_text()


def test_summary_omits_metrics_without_samples():
    result = summarize([{"scenario":"x","controller":"flowsync","seed":1,"metrics":{"incident_recovery_seconds":None}}])
    assert result == {"x":{"flowsync":{}},"paired_differences":{"x":{}}}


def test_experiment_status_returns_terminal_failure_state():
    import pytest
    pytest.importorskip("fastapi")
    from flowsync.api import app as api_module

    class FailedFuture:
        @staticmethod
        def done(): return True
        @staticmethod
        def result(): raise RuntimeError("SUMO route lookup failed")

    experiment_id = "failed-status-test"
    api_module.experiment_jobs[experiment_id] = FailedFuture()
    try:
        result = api_module.experiment_status(experiment_id)
        assert result == {"experiment_id": experiment_id, "status": "failed",
                          "error": "SUMO route lookup failed"}
    finally:
        api_module.experiment_jobs.pop(experiment_id, None)


def test_api_experiment_worker_restores_controller_enums(monkeypatch):
    import pytest
    pytest.importorskip("fastapi")
    from flowsync.api import app as api_module
    from flowsync.models import ControllerKind

    observed = {}

    class RunnerSpy:
        def __init__(self, store): pass
        def run(self, **kwargs):
            observed.update(kwargs)
            return {"experiment_id": kwargs["experiment_id"]}

    monkeypatch.setattr(api_module, "ExperimentStore", lambda: object())
    monkeypatch.setattr(api_module, "ExperimentRunner", RunnerSpy)
    result = api_module._run_experiment_process("enum-test", {
        "scenarios": ["normal-traffic"], "seeds": [11], "duration_seconds": 60,
        "controllers": ["flowsync", "max-pressure"],
    })

    assert result["experiment_id"] == "enum-test"
    assert observed["controllers"] == [ControllerKind.FLOWSYNC, ControllerKind.MAX_PRESSURE]


def test_sumo_scenario_sources_define_five_signals_and_heterogeneous_demand(tmp_path):
    import xml.etree.ElementTree as ET
    from flowsync.simulation.sumo import _write_routes, write_network_sources
    nodes_path, edges_path = write_network_sources(tmp_path)
    _write_routes(tmp_path / "traffic.rou.xml", 900, 480, 70, seed=7)
    nodes = ET.parse(nodes_path).getroot()
    assert len([n for n in nodes.findall("node") if n.get("type") == "traffic_light"]) == 5
    assert len(ET.parse(edges_path).getroot().findall("edge")) >= 40
    routes = ET.parse(tmp_path / "traffic.rou.xml").getroot()
    types = {v.get("id") for v in routes.find("vTypeDistribution")}
    types.update(v.get("id") for v in routes.findall("vType"))
    assert {"motorcycle", "car", "auto_rickshaw", "bus", "heavy", "ambulance", "fire", "police"} <= types
    assert routes.findall("vehicle") and routes.findall("person")
    first_trace = [(v.get("depart"),v.get("type"),v.get("route"),v.get("speedFactor")) for v in routes.findall("vehicle")]
    _write_routes(tmp_path / "repeat.rou.xml", 900, 480, 70, seed=7)
    repeat = ET.parse(tmp_path / "repeat.rou.xml").getroot()
    assert first_trace == [(v.get("depart"),v.get("type"),v.get("route"),v.get("speedFactor")) for v in repeat.findall("vehicle")]
    departure_times = [float(v.get("depart")) for v in routes.findall("vehicle")]
    assert departure_times == sorted(departure_times)
    all_times = [float(demand.get("depart")) for demand in routes if demand.tag in ("vehicle", "person")]
    assert all_times == sorted(all_times)


def test_emergency_routes_only_use_edges_in_generated_network(tmp_path):
    import xml.etree.ElementTree as ET
    from flowsync.simulation.sumo import _emergency_movement, write_network_sources
    _, edges_path = write_network_sources(tmp_path)
    available = {edge.get("id") for edge in ET.parse(edges_path).getroot().findall("edge")}
    for node in range(5):
        for destination in ("E", "W"):
            route = _emergency_movement(node, destination)
            assert route and set(route) <= available
    import pytest
    with pytest.raises(ValueError): _emergency_movement(5, "E")


def test_normal_phase_transition_resets_min_green_timer():
    from flowsync.safety import SignalSafety
    from flowsync.models import Intersection
    safety = SignalSafety()
    node = Intersection("J0", 0, green_elapsed=10)
    assert safety.request_phase(node, "EW")
    for _ in range(safety.config.yellow + safety.config.all_red): safety.advance(node)
    assert node.stage == "green" and node.phase == "EW" and node.green_elapsed == 0


def test_auto_engine_falls_back_when_traci_socket_is_unavailable(monkeypatch):
    from flowsync.simulation import factory
    factory.reset_sumo_failure()
    monkeypatch.setattr(factory, "availability", lambda: {
        "sumo": True, "netconvert": True, "traci": True, "traci_socket": False})
    config = SimulationConfig(duration_seconds=60, engine="auto")
    simulation = factory.create_simulation(config)
    assert isinstance(simulation, TrafficSimulation)
    assert config.engine == "fallback"


def test_auto_engine_falls_back_when_sumo_init_raises(monkeypatch):
    from flowsync.simulation import factory
    factory.reset_sumo_failure()
    monkeypatch.setattr(factory, "availability", lambda: {
        "sumo": True, "netconvert": True, "traci": True, "traci_socket": True})

    def mock_sumo_init(*args, **kwargs):
        raise RuntimeError("TraCI connection refused")

    monkeypatch.setattr(factory, "SumoSimulation", mock_sumo_init)
    config = SimulationConfig(duration_seconds=60, engine="auto")
    simulation = factory.create_simulation(config)
    assert isinstance(simulation, TrafficSimulation)
    assert config.engine == "fallback"
    assert factory._sumo_failed is True

    # Subsequent calls should immediately return fallback without calling SumoSimulation again
    call_count = 0
    def mock_sumo_init2(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Should not be called")
    monkeypatch.setattr(factory, "SumoSimulation", mock_sumo_init2)
    config2 = SimulationConfig(duration_seconds=60, engine="auto")
    sim2 = factory.create_simulation(config2)
    assert isinstance(sim2, TrafficSimulation)
    assert call_count == 0
    factory.reset_sumo_failure()


def test_factory_honors_flowsync_engine_env(monkeypatch):
    from flowsync.simulation import factory
    factory.reset_sumo_failure()
    monkeypatch.setenv("FLOWSYNC_ENGINE", "fallback")
    monkeypatch.setattr(factory, "availability", lambda: {
        "sumo": True, "netconvert": True, "traci": True, "traci_socket": True})
    config = SimulationConfig(duration_seconds=60, engine="auto")
    simulation = factory.create_simulation(config)
    assert isinstance(simulation, TrafficSimulation)
    assert config.engine == "fallback"



def test_sumo_pedestrian_wait_records_completed_intervals():
    from flowsync.simulation.sumo import _PedestrianWaitTracker
    tracker = _PedestrianWaitTracker()
    assert tracker.update({"p1": 2.0}) == []
    assert tracker.update({"p1": 5.0}) == []
    assert tracker.update({"p1": 0.0}) == [5.0]
    assert tracker.update({"p2": 3.0}) == []
    assert tracker.update({}) == [3.0]


def test_perception_source_is_explicit_and_queue_needs_persistent_detections():
    from flowsync.perception.pipeline import Detection, QueueEstimator, observation_from_simulation
    sim = TrafficSimulation(SimulationConfig(duration_seconds=60, demand_per_hour=0, pedestrian_per_hour=0))
    sim.generate_emergency(at="J0")
    observation = observation_from_simulation(sim.state(), "J0", "W")
    assert observation.source == "simulation" and observation.queue_estimate == 1
    tracker = QueueEstimator(stationary_frames=2)
    detection = Detection("car", .9, 10, 10, 40, 40)
    results = [tracker.update([detection], (0, 0, 1, 1), "J0", "N", (100, 100)) for _ in range(3)]
    assert results[-1].source == "video:yolo-opencv" and results[-1].queue_estimate == 1


def test_sumo_integration_when_runtime_is_installed(tmp_path):
    import pytest
    from flowsync.simulation.sumo import availability
    if not all(availability().values()): pytest.skip("SUMO runtime or local TraCI sockets are unavailable")
    from flowsync.simulation.sumo import SumoSimulation
    sim = SumoSimulation(SimulationConfig(seed=2, duration_seconds=20, demand_per_hour=200,
        pedestrian_per_hour=0, engine="sumo"), workdir=tmp_path)
    try:
        result = sim.run(10)
        assert len(result.intersections) == 5
        assert result.time == 10
    finally:
        sim.close()


def test_api_validation_and_simulation_lifecycle_when_optional_api_is_installed():
    import pytest
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from flowsync.api.app import app
    with TestClient(app) as client:
        invalid = client.post("/api/simulations", json={"engine":"unknown","duration_seconds":30})
        assert invalid.status_code == 422
        started = client.post("/api/simulations", json={"seed":9,"duration_seconds":60,"engine":"fallback"})
        assert started.status_code == 201 and len(started.json()["intersections"]) == 5
        simulation_id = started.json()["simulation_id"]
        observation = client.post("/api/observations", json={"simulation_id":simulation_id,"intersection_id":"J1",
            "approach":"N","source":"simulation","confidence":1,"vehicle_counts":{"car":2},"queue_estimate":2})
        assert observation.status_code == 201
        assert len(client.get(f"/api/simulations/{simulation_id}/history").json()["observations"]) == 1
        stepped = client.post("/api/simulations/step")
        assert stepped.status_code == 200 and stepped.json()["time"] == 1
        assert client.post("/api/simulations/pause").json()["status"] == "paused"
        assert client.post("/api/simulations/stop").json()["status"] == "stopped"
