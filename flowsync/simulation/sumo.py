"""SUMO network generation and TraCI microscopic engine adapter."""
from __future__ import annotations

import importlib.util
import os
import shutil
import socket
import subprocess
import xml.etree.ElementTree as ET
import uuid
from pathlib import Path

from flowsync.control.agent import IntersectionAgent
from flowsync.models import (ControllerKind, Incident, IncidentKind, Intersection,
                             SimulationConfig, SimulationState, Vehicle, VehicleClass)


def availability() -> dict[str, bool]:
    socket_available = False
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        socket_available = True
        probe.close()
    except OSError:
        pass
    return {"sumo": shutil.which("sumo") is not None,
            # Network source XML is converted with netconvert; netgenerate does not
            # accept --node-files/--edge-files.
            "netconvert": shutil.which("netconvert") is not None,
            "traci": importlib.util.find_spec("traci") is not None,
            "traci_socket": socket_available}


def require_sumo() -> None:
    state = availability()
    if not all(state.values()):
        missing = ", ".join(name for name, available in state.items() if not available)
        raise RuntimeError(f"SUMO runtime unavailable ({missing}); install SUMO tools and the Python TraCI package")


def generate_scenario(directory: str | Path, duration_seconds: int = 1800,
                      demand_per_hour: int = 480, pedestrian_per_hour: int = 70,
                      emergency_per_hour: int = 4,
                      seed: int = 7, netconvert: str | None = None,
                      approach_demand: dict[str, int] | None = None) -> Path:
    """Generate a connected five-signal grid, heterogeneous routes and SUMO config."""
    exe = netconvert or shutil.which("netconvert")
    if not exe: raise RuntimeError("netconvert was not found on PATH")
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    nodes_path, edges_path = root / "network.nod.xml", root / "network.edg.xml"
    net_path, route_path, cfg_path = root / "network.net.xml", root / "traffic.rou.xml", root / "flowsync.sumocfg"
    write_network_sources(root)
    try:
        subprocess.run([exe, f"--node-files={nodes_path}", f"--edge-files={edges_path}",
        f"--output-file={net_path}", "--tls.default-type=static", "--tls.layout=opposites",
        "--tls.green.time=40", "--tls.yellow.time=3", "--tls.allred.time=1",
        "--default.lanenumber=2", "--default.lanewidth=3.5", "--default.sidewalk-width=2",
        "--crossings.guess=true", "--walkingareas=true", "--no-turnarounds=true"],
        check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"SUMO network conversion failed: {detail}") from exc
    _write_routes(route_path, duration_seconds, demand_per_hour, pedestrian_per_hour,
                  seed, approach_demand or {}, emergency_per_hour)
    config = ET.Element("configuration")
    inputs = ET.SubElement(config, "input")
    ET.SubElement(inputs, "net-file", value=net_path.name)
    ET.SubElement(inputs, "route-files", value=route_path.name)
    time_node = ET.SubElement(config, "time")
    ET.SubElement(time_node, "begin", value="0"); ET.SubElement(time_node, "end", value=str(duration_seconds))
    processing = ET.SubElement(config, "processing")
    ET.SubElement(processing, "step-length", value="1")
    ET.SubElement(processing, "lateral-resolution", value="0.7")
    # Preserve gridlock and congestion in measurements instead of silently moving vehicles.
    ET.SubElement(processing, "time-to-teleport", value="-1")
    random_node = ET.SubElement(config, "random_number")
    ET.SubElement(random_node, "seed", value=str(seed))
    ET.ElementTree(config).write(cfg_path, encoding="utf-8", xml_declaration=True)
    return cfg_path


def write_network_sources(directory: str | Path):
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    nodes_path, edges_path = root / "network.nod.xml", root / "network.edg.xml"
    positions = _positions()
    nodes = ET.Element("nodes")
    for node_id, (x, y) in positions.items():
        kind = "traffic_light" if node_id.startswith("J") else "priority"
        ET.SubElement(nodes, "node", id=node_id, x=str(x), y=str(y), type=kind)
    ET.ElementTree(nodes).write(nodes_path, encoding="utf-8", xml_declaration=True)
    edges = ET.Element("edges")
    edge_ids: set[tuple[str, str]] = set()
    def connect(a, b):
        if (a, b) in edge_ids: return
        edge_ids.add((a, b))
        ET.SubElement(edges, "edge", id=f"e_{a}_{b}", **{"from": a, "to": b}, numLanes="2", speed="13.89")
    # Directed links make a three-row urban grid with five signalized corridor nodes.
    rows = [[f"N{i}" for i in range(5)], [f"J{i}" for i in range(5)], [f"S{i}" for i in range(5)]]
    for row in rows:
        for a, b in zip(row, row[1:]): connect(a, b); connect(b, a)
    connect("W", "J0"); connect("J0", "W")
    connect("J4", "E"); connect("E", "J4")
    for i in range(5):
        north, junction, south = f"N{i}", f"J{i}", f"S{i}"
        connect(north, junction); connect(junction, north)
        connect(junction, south); connect(south, junction)
    ET.ElementTree(edges).write(edges_path, encoding="utf-8", xml_declaration=True)
    return nodes_path, edges_path


def _positions():
    coords = {}
    for i in range(5):
        coords[f"N{i}"] = (i * 200, 200)
        coords[f"J{i}"] = (i * 200, 0)
        coords[f"S{i}"] = (i * 200, -200)
    coords["W"] = (-200, 0); coords["E"] = (1000, 0)
    return coords


def _write_routes(path: Path, duration: int, demand: int, pedestrians: int, seed: int = 7,
                  approach_demand: dict[str, int] | None = None, emergency_per_hour: int = 4):
    import random
    approach_demand = approach_demand or {}
    rng = random.Random(seed)
    ped_rng = random.Random(seed ^ 0x1F123BB5)
    emergency_rng = random.Random(seed ^ 0xA5A5A5A5)
    routes = ET.Element("routes")
    distribution = ET.SubElement(routes, "vTypeDistribution", id="mixed")
    definitions = [
        ("motorcycle", "motorcycle", 2.2, .8, 16.7, .39, "motorcycle"),
        ("car", "passenger", 4.3, 1.8, 16.7, .33, "passenger"),
        ("auto_rickshaw", "passenger", 3.0, 1.4, 13.9, .16, "passenger"),
        ("bus", "bus", 10.0, 2.5, 13.9, .06, "bus"),
        ("heavy", "truck", 8.0, 2.5, 13.9, .06, "truck"),
    ]
    for ident, vclass, length, width, speed, probability, shape in definitions:
        ET.SubElement(distribution, "vType", id=ident, vClass=vclass, length=str(length), width=str(width),
            maxSpeed=str(speed), accel="2.0", decel="4.5", sigma="0", speedFactor="1", guiShape=shape,
            latAlignment="arbitrary", minGapLat="0.15",
            probability=str(probability))
    emergency_types = [
        ("ambulance", "emergency", 5.0, 1.9, 22.2, "emergency"),
        ("fire", "emergency", 8.0, 2.5, 19.4, "emergency"),
        ("police", "emergency", 4.8, 1.9, 22.2, "emergency"),
    ]
    for ident, vclass, length, width, speed, shape in emergency_types:
        ET.SubElement(routes, "vType", id=ident, vClass=vclass, length=str(length), width=str(width),
            maxSpeed=str(speed), accel="2.5", decel="5.0", sigma="0", speedFactor="1",
            guiShape=shape, latAlignment="arbitrary", minGapLat="0.15")
    # Each entry approach feeds a reproducible opposite exit with a heterogeneous type draw.
    movements = [("W", "J0", "J4", "E"), ("E", "J4", "J0", "W")]
    for i in range(5):
        movements.extend([(f"N{i}", f"J{i}", f"J{i}", f"S{i}"),
                          (f"S{i}", f"J{i}", f"J{i}", f"N{i}")])
    # Sidewalks/crossings are built by netconvert; explicit people keep demand traces paired.
    demand_entities = []
    route_defs = []
    for i in range(5):
        for cross_index, (origin, target) in enumerate(((f"e_N{i}_J{i}", f"e_J{i}_S{i}"), (f"e_S{i}_J{i}", f"e_J{i}_N{i}"))):
            if pedestrians <= 0: continue
            depart = 0.0; serial = 0
            while True:
                depart += ped_rng.expovariate(pedestrians/3600)
                if depart >= duration: break
                serial += 1
                demand_entities.append((depart, "person", i*2+cross_index, serial, (origin, target)))
    if emergency_per_hour > 0:
        depart = 0.0; serial = 0
        while True:
            depart += emergency_rng.expovariate(emergency_per_hour/3600)
            if depart >= duration: break
            serial += 1
            node_index = emergency_rng.randrange(5)
            destination = emergency_rng.choice(("E", "W"))
            route_id = f"emergency_route_{serial}"
            route_defs_for_emergency = _emergency_movement(node_index, destination)
            route_defs.append((route_id, route_defs_for_emergency))
            type_id = emergency_rng.choices(("ambulance", "fire", "police"), weights=(.7,.2,.1), k=1)[0]
            speed_factor = min(1.3, max(.7, emergency_rng.gauss(1,.05)))
            demand_entities.append((depart, "vehicle", 100, serial, (route_id, type_id, speed_factor)))
    type_weights = [(item[0], item[5]) for item in definitions]
    vehicles = []
    for index, (source, entry, exit_node, destination) in enumerate(movements):
        if source in ("W", "E"):
            arm = source
        else:
            arm = "N" if source.startswith("N") else "S"
        rate = approach_demand.get(f"{entry}:{arm}", demand)
        if rate <= 0: continue
        route_id = f"route_{index}"
        edge_path = _movement_edges(source, entry, exit_node, destination)
        route_defs.append((route_id, edge_path))
        depart = 0.0
        serial = 0
        while rate > 0:
            depart += rng.expovariate(rate/3600)
            if depart >= duration: break
            serial += 1
            type_id = rng.choices([item[0] for item in type_weights], weights=[item[1] for item in type_weights], k=1)[0]
            speed_factor = min(1.3, max(.7, rng.gauss(1.0, .1)))
            vehicles.append((depart, index, serial, route_id, type_id, speed_factor))
    for route_id, edges in route_defs:
        ET.SubElement(routes, "route", id=route_id, edges=" ".join(edges))
    # Explicitly seeded departures, vehicle classes and routes stay identical across controllers.
    demand_entities.extend((depart, "vehicle", origin_index, serial, (route_id, type_id, speed_factor))
                           for depart, origin_index, serial, route_id, type_id, speed_factor in vehicles)
    for depart, kind, origin_index, serial, data in sorted(demand_entities, key=lambda row: (row[0], row[1], row[2], row[3])):
        if kind == "vehicle":
            route_id, type_id, speed_factor = data
            ET.SubElement(routes, "vehicle", id=f"v{origin_index}_{serial}", type=type_id,
                route=route_id, depart=f"{depart:.3f}", departLane="best", departSpeed="desired",
                speedFactor=f"{speed_factor:.4f}")
        else:
            origin, target = data
            person = ET.SubElement(routes, "person", id=f"p{origin_index}_{serial}", depart=f"{depart:.3f}")
            ET.SubElement(person, "walk", **{"from": origin, "to": target})
    ET.ElementTree(routes).write(path, encoding="utf-8", xml_declaration=True)


def _movement_edges(source, entry, exit_node, destination):
    if source == "W": return ["e_W_J0", "e_J0_J1", "e_J1_J2", "e_J2_J3", "e_J3_J4", "e_J4_E"]
    if source == "E": return ["e_E_J4", "e_J4_J3", "e_J3_J2", "e_J2_J1", "e_J1_J0", "e_J0_W"]
    if source.startswith("N"): return [f"e_{source}_{entry}", f"e_{entry}_{destination}"]
    return [f"e_{source}_{entry}", f"e_{entry}_{destination}"]


def _emergency_movement(node_index: int, destination: str) -> list[str]:
    if not 0 <= node_index < 5 or destination not in ("E", "W"):
        raise ValueError("emergency route requires a junction index from 0 to 4 and destination E or W")
    if destination == "E":
        edges = [f"e_J{node_index-1}_J{node_index}" if node_index > 0 else "e_W_J0"]
        edges.extend(f"e_J{i}_J{i+1}" for i in range(node_index, 4))
        edges.append("e_J4_E")
        return edges
    edges = [f"e_J{node_index+1}_J{node_index}" if node_index < 4 else "e_E_J4"]
    edges.extend(f"e_J{i}_J{i-1}" for i in range(node_index, 0, -1))
    edges.append("e_J0_W")
    return edges


class SumoSimulation:
    """TraCI-controlled SUMO engine. Its generated SUMO TLS program supplies safe clearance phases."""
    def __init__(self, config: SimulationConfig, workdir: str | Path | None = None, gui: bool = False):
        require_sumo()
        if not os.environ.get("SUMO_HOME") and Path("/usr/share/sumo/tools").is_dir():
            os.environ["SUMO_HOME"] = "/usr/share/sumo"
        import traci
        self.traci = traci
        self.config = config
        self.workdir = Path(workdir or Path.cwd() / ".flowsync" / f"sumo-{config.seed}")
        cfg = generate_scenario(self.workdir, config.duration_seconds, config.demand_per_hour,
                                config.pedestrian_per_hour, config.emergency_per_hour, config.seed,
                                approach_demand=config.approach_demand)
        binary = shutil.which("sumo-gui" if gui else "sumo") or shutil.which("sumo")
        self.label = f"flowsync-{uuid.uuid4().hex}"
        retries = int(os.environ.get("FLOWSYNC_TRACI_RETRIES", "1"))
        traci.start([binary, "-c", str(cfg), "--seed", str(config.seed), "--no-step-log", "true"],
                    label=self.label, numRetries=retries)
        self.conn = traci.getConnection(self.label)
        self._closed = False
        self.time = 0
        self.status = "running"
        self.intersections = [Intersection(f"J{i}", i) for i in range(5)]
        for node in self.intersections: node.side_street_sinks = True
        self.agents = {node.id: IntersectionAgent(node.id) for node in self.intersections}
        self.incidents: list[Incident] = []
        self.vehicles_passed = 0
        self.crossings = 0
        self.wait_samples: list[float] = []
        self.ped_wait_samples: list[float] = []
        self.emergency_wait: list[float] = []
        self.emergency_travel: list[float] = []
        self.class_wait: dict[str, list[float]] = {}
        self.controller_ms: list[float] = []
        self._departed: dict[str, float] = {}
        self._emergency_ids: set[str] = set()
        self._last_time_loss: dict[str, float] = {}
        self._last_edge: dict[str, str] = {}
        self._last_internal_junction: dict[str, str] = {}
        self._queue_samples: list[float] = []
        self._max_queue_length = 0
        self._emergency_positions: dict[str, dict] = {}
        self._incident_speed: dict[str, dict[str, float]] = {}
        self._incident_baseline: dict[str, int] = {}
        self._pending_recovery: list[tuple[Incident, int, int]] = []
        self.recovery_samples: list[int] = []
        self._pedestrian_wait_tracker = _PedestrianWaitTracker()
        try:
            self._tls = {node.id: self._tls_info(node.id) for node in self.intersections}
        except Exception:
            self.close()
            raise
        self._original_type = {}

    def step(self) -> SimulationState:
        if self.status != "running": raise RuntimeError("simulation is not running")
        self.conn.simulationStep()
        self.time = int(round(self.conn.simulation.getTime()))
        self._update_queues()
        for node in self.intersections:
            start = __import__("time").perf_counter()
            visible = [other for other in self.intersections if abs(other.index-node.index) <= 1]
            decision = self.agents[node.id].decide(node, self.config.controller, self.time, visible,
                [incident for incident in self.incidents if incident.active])
            self._adapt_tls(node, decision.requested_phase)
            self.controller_ms.append((__import__("time").perf_counter() - start) * 1000)
            node.last_decision = f"{decision.controller.value}: {decision.explanation}"
        self._collect_metrics()
        if self.time >= self.config.duration_seconds: self.status = "finished"
        return self.state()

    def run(self, seconds: int | None = None):
        end = self.time + (seconds if seconds is not None else self.config.duration_seconds - self.time)
        while self.status == "running" and self.time < end: self.step()
        return self.state()

    def inject_incident(self, kind, intersection_id="J2", approach="N", severity=.5):
        node = next((n for n in self.intersections if n.id == intersection_id), None)
        if node is None: raise ValueError(f"unknown intersection: {intersection_id}")
        if approach not in "NSEW" or not 0 <= severity <= 1: raise ValueError("invalid approach or severity")
        kind = IncidentKind(kind)
        incident = Incident(f"inc-{len(self.incidents)+1}", kind, intersection_id, approach, severity, 1-severity, self.time)
        self.incidents.append(incident)
        if kind == IncidentKind.COMMUNICATION: node.communication = False
        else:
            lanes = self._tls[intersection_id]["lanes"][approach]
            speeds = {lane: self.conn.lane.getMaxSpeed(lane) for lane in lanes}
            self._incident_speed[incident.id] = speeds
            self._incident_baseline[incident.id] = node.queue_size(approach)
            for lane, speed in speeds.items():
                reduced = .1 if kind in (IncidentKind.BLOCKAGE, IncidentKind.ACCIDENT) else max(.5, speed * (1-severity))
                self.conn.lane.setMaxSpeed(lane, reduced)
        return incident

    def remove_incident(self, incident_id):
        incident = next((i for i in self.incidents if i.id == incident_id and i.active), None)
        if incident is None: return False
        incident.active = False
        if incident.kind == IncidentKind.COMMUNICATION:
            next(n for n in self.intersections if n.id == incident.intersection_id).communication = True
            self.recovery_samples.append(0)
        else:
            self._pending_recovery.append((incident, self._incident_baseline.get(incident.id, 0), self.time))
        for lane, speed in self._incident_speed.pop(incident_id, {}).items(): self.conn.lane.setMaxSpeed(lane, speed)
        return True

    def generate_emergency(self, kind=VehicleClass.AMBULANCE, at="J0"):
        kind = VehicleClass(kind)
        if kind not in (VehicleClass.AMBULANCE, VehicleClass.FIRE, VehicleClass.POLICE): raise ValueError("invalid emergency class")
        node_index = int(at[1:])
        origin, destination = f"e_W_J0", "e_J4_E"
        if node_index > 0:
            origin = f"e_J{node_index-1}_J{node_index}"
        if node_index < 4: destination = f"e_J4_E"
        route = self.conn.simulation.findRoute(origin, destination)
        if not route.edges: raise RuntimeError("SUMO could not route emergency vehicle")
        vehicle_id = f"emergency-{kind.value}-{self.time}-{len(self._departed)}"
        route_id = f"route-{vehicle_id}"
        self.conn.route.add(route_id, route.edges)
        type_id = kind.value
        self.conn.vehicle.add(vehicle_id, route_id, typeID=type_id, depart="now", departLane="best", departSpeed="0")
        self._departed[vehicle_id] = float(self.time)
        self._emergency_ids.add(vehicle_id)
        return Vehicle(vehicle_id, kind, "W", "E", self.time, emergency=True)

    def state(self):
        metrics = {"mean_delay_seconds": _mean(self.wait_samples) if self.wait_samples else None,
            "p95_delay_seconds": _percentile(self.wait_samples, .95) if self.wait_samples else None,
            "average_queue_length": _mean(self._queue_samples),
            "maximum_queue_length": self._max_queue_length,
            "throughput_vehicles": self.vehicles_passed, "intersection_crossings": self.crossings,
            "emergency_vehicle_delay_seconds": _mean(self.emergency_wait) if self.emergency_wait else None,
            "emergency_vehicle_travel_seconds": _mean(self.emergency_travel) if self.emergency_travel else None,
            "pedestrian_wait_seconds": _mean(self.ped_wait_samples) if self.ped_wait_samples else None, "incident_recovery_seconds": _mean(self.recovery_samples) if self.recovery_samples else None,
            "controller_execution_ms": _mean(self.controller_ms),
            "per_vehicle_class_mean_delay": {k: _mean(v) for k,v in self.class_wait.items()}}
        return SimulationState(self.time, self.intersections, [i for i in self.incidents if i.active],
                               self.vehicles_passed, metrics, self.status, list(self._emergency_positions.values()))

    def close(self):
        if not self._closed:
            self._closed = True
            self.conn.close()

    def _tls_info(self, junction):
        links = self.conn.trafficlight.getControlledLinks(junction)
        lanes = {arm: [] for arm in "NSEW"}
        link_arms = []
        for group in links:
            arms = set()
            for incoming, _outgoing, _via in group:
                edge = self.conn.lane.getEdgeID(incoming)
                arm = self._incoming_arm(junction, edge)
                if arm is None: continue
                arms.add(arm); lanes[arm].append(incoming)
            link_arms.append(arms)
        programs = self.conn.trafficlight.getAllProgramLogics(junction)
        logic = next((p for p in programs if p.programID == self.conn.trafficlight.getProgram(junction)), programs[0])
        return {"links": links, "link_arms": link_arms, "lanes": {a: list(dict.fromkeys(v)) for a,v in lanes.items()},
                "phase_groups": [self._classify_state(p.state, link_arms) for p in logic.phases]}

    def _incoming_arm(self, junction, edge):
        if not edge.startswith("e_"): return None
        source, target = edge.split("_")[1:3]
        if source.startswith("N"): return "N"
        if source.startswith("S"): return "S"
        if source == "W": return "W"
        if source == "E": return "E"
        si, ti = int(source[1:]), int(target[1:])
        return "E" if si < ti else "W"

    @staticmethod
    def _classify_state(signal_state, link_arms):
        arms = set()
        for index, char in enumerate(signal_state):
            if char in "gG" and index < len(link_arms): arms |= link_arms[index]
        if arms and arms <= {"N", "S"}: return "NS"
        if arms and arms <= {"E", "W"}: return "EW"
        return None

    def _update_queues(self):
        for node in self.intersections:
            info = self._tls[node.id]
            state = self.conn.trafficlight.getRedYellowGreenState(node.id)
            green_dirs = set()
            for index, signal in enumerate(state):
                if signal in "gG" and index < len(info["link_arms"]): green_dirs |= info["link_arms"][index]
            node.phase = "NS" if green_dirs and green_dirs <= {"N", "S"} else "EW" if green_dirs and green_dirs <= {"E", "W"} else node.phase
            node.stage = "yellow" if any(c in "yY" for c in state) else "green" if any(c in "gG" for c in state) else "all-red"
            node.queues = {arm: [] for arm in "NSEW"}
            for arm, lanes in info["lanes"].items():
                for lane in lanes:
                    for vehicle_id in self.conn.lane.getLastStepVehicleIDs(lane):
                        if self.conn.vehicle.getSpeed(vehicle_id) < .3:
                            type_id = self.conn.vehicle.getTypeID(vehicle_id)
                            cls = _vehicle_class(type_id)
                            node.queues[arm].append(Vehicle(vehicle_id, cls, arm, "unknown", self.time,
                                emergency=cls in (VehicleClass.AMBULANCE, VehicleClass.FIRE, VehicleClass.POLICE),
                                waiting=int(self.conn.vehicle.getWaitingTime(vehicle_id))))

    def _adapt_tls(self, node, requested):
        tls = node.id
        state = self.conn.trafficlight.getRedYellowGreenState(tls)
        if not any(c in "gG" for c in state): return
        info = self._tls[tls]
        phase_index = self.conn.trafficlight.getPhase(tls)
        phase_group = info["phase_groups"][phase_index]
        if phase_group not in ("NS", "EW"): return
        now = self.conn.simulation.getTime()
        remaining = max(0, self.conn.trafficlight.getNextSwitch(tls) - now)
        elapsed = max(0, self.conn.trafficlight.getPhaseDuration(tls) - remaining)
        if requested == phase_group:
            self.conn.trafficlight.setPhaseDuration(tls, max(1, 55 - elapsed))
        elif elapsed < 10:
            self.conn.trafficlight.setPhaseDuration(tls, max(1, 10 - elapsed))
        else:
            # Advance only the active green. SUMO's generated yellow/all-red program phases remain in force.
            self.conn.trafficlight.setPhaseDuration(tls, 1)

    def _collect_metrics(self):
        arrived = set(self.conn.simulation.getArrivedIDList())
        departed = set(self.conn.simulation.getDepartedIDList())
        arrived_emergency = self._emergency_ids.intersection(arrived)
        for vehicle_id in departed:
            if vehicle_id not in self._departed: self._departed[vehicle_id] = float(self.time)
        for vehicle_id in arrived:
            self.vehicles_passed += 1
            departed_at = self._departed.pop(vehicle_id, float(self.time))
            if vehicle_id in self._emergency_ids:
                self.emergency_travel.append(self.time - departed_at)
                self._emergency_ids.discard(vehicle_id)
        active = set(self.conn.vehicle.getIDList())
        for vehicle_id in active:
            edge = self.conn.vehicle.getRoadID(vehicle_id)
            if edge.startswith(":J"):
                junction = edge[1:].split("_", 1)[0]
                if self._last_internal_junction.get(vehicle_id) != junction:
                    self.crossings += 1
                self._last_internal_junction[vehicle_id] = junction
            else:
                self._last_internal_junction.pop(vehicle_id, None)
            self._last_edge[vehicle_id] = edge
            self._last_time_loss[vehicle_id] = self.conn.vehicle.getTimeLoss(vehicle_id)
        self._queue_samples.append(_mean([sum(len(q) for q in n.queues.values()) for n in self.intersections]))
        self._max_queue_length = max(self._max_queue_length,
            max((len(q) for n in self.intersections for q in n.queues.values()), default=0))
        for vehicle_id in arrived:
            wait = self._last_time_loss.pop(vehicle_id, 0.0)
            self.wait_samples.append(wait)
            if vehicle_id in arrived_emergency: self.emergency_wait.append(wait)
            self.class_wait.setdefault(_vehicle_class(self._original_type.get(vehicle_id, "car")).value, []).append(wait)
            self._last_edge.pop(vehicle_id, None)
            self._last_internal_junction.pop(vehicle_id, None)
            self._emergency_positions.pop(vehicle_id, None)
        for vehicle_id in departed: self._original_type[vehicle_id] = self.conn.vehicle.getTypeID(vehicle_id)
        for vehicle_id in self._emergency_ids:
            if vehicle_id not in active: continue
            self._emergency_positions[vehicle_id] = {"id": vehicle_id,
                "kind": self.conn.vehicle.getTypeID(vehicle_id), "lane": self.conn.vehicle.getLaneID(vehicle_id),
                "edge": self.conn.vehicle.getRoadID(vehicle_id), "waiting_seconds": self.conn.vehicle.getWaitingTime(vehicle_id),
                "destination": "E"}
        person_waits = {person_id: self.conn.person.getWaitingTime(person_id)
                        for person_id in self.conn.person.getIDList()}
        self.ped_wait_samples.extend(self._pedestrian_wait_tracker.update(person_waits))
        pending = []
        for incident, baseline, cleared_at in self._pending_recovery:
            node = next(n for n in self.intersections if n.id == incident.intersection_id)
            if node.queue_size(incident.approach) <= baseline: self.recovery_samples.append(self.time-cleared_at)
            else: pending.append((incident, baseline, cleared_at))
        self._pending_recovery = pending


def _vehicle_class(type_id: str) -> VehicleClass:
    return {"motorcycle": VehicleClass.MOTORCYCLE, "car": VehicleClass.CAR,
        "auto_rickshaw": VehicleClass.AUTO, "bus": VehicleClass.BUS, "heavy": VehicleClass.HEAVY,
        "ambulance": VehicleClass.AMBULANCE, "fire": VehicleClass.FIRE,
        "police": VehicleClass.POLICE}.get(type_id, VehicleClass.CAR)


class _PedestrianWaitTracker:
    """Collect completed continuous wait intervals, not per-step wait snapshots."""
    def __init__(self):
        self._maximum_wait: dict[str, float] = {}

    def update(self, waiting_by_person: dict[str, float]) -> list[float]:
        completed = []
        active_ids = set(waiting_by_person)
        for person_id, waiting in waiting_by_person.items():
            if waiting > 0:
                self._maximum_wait[person_id] = max(waiting, self._maximum_wait.get(person_id, 0.0))
            elif person_id in self._maximum_wait:
                completed.append(self._maximum_wait.pop(person_id))
        for person_id in set(self._maximum_wait) - active_ids:
            completed.append(self._maximum_wait.pop(person_id))
        return completed


def _mean(values): return sum(values) / len(values) if values else 0.0


def _percentile(values, fraction):
    if not values: return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered)-1, int((len(ordered)-1)*fraction))])
