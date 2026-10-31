from __future__ import annotations

import random
import statistics
import time
import uuid

from flowsync.control.agent import IntersectionAgent
from flowsync.models import (ControllerKind, Incident, IncidentKind, Intersection,
                             SimulationConfig, SimulationState, Vehicle, VehicleClass)
from flowsync.safety import SignalSafety


class TrafficSimulation:
    """Reproducible discrete-time fallback model; use SUMO for calibrated mobility studies."""
    TOPOLOGY = 5
    CAPACITY = {VehicleClass.MOTORCYCLE: 2, VehicleClass.CAR: 1,
                VehicleClass.AUTO: 1, VehicleClass.BUS: 1,
                VehicleClass.HEAVY: 1, VehicleClass.AMBULANCE: 1,
                VehicleClass.FIRE: 1, VehicleClass.POLICE: 1}

    def __init__(self, config: SimulationConfig | None = None):
        self.config = config or SimulationConfig()
        self.demand_rng = random.Random(self.config.seed)
        self.service_rng = random.Random(self.config.seed ^ 0x5F3759DF)
        self.route_rng = random.Random(self.config.seed ^ 0x9E3779B9)
        self.emergency_rng = random.Random(self.config.seed ^ 0x1F123BB5)
        self.intersections = [Intersection(f"J{i}", i) for i in range(self.TOPOLOGY)]
        self.agents = {node.id: IntersectionAgent(node.id) for node in self.intersections}
        self.safety = SignalSafety()
        self.time = 0
        self.vehicles_passed = 0
        self.intersection_crossings = 0
        self.next_vehicle = 0
        self.arrivals: list[tuple[int, str, str, str]] = []
        self.emergency_vehicles: dict[str, Vehicle] = {}
        self.incidents: list[Incident] = []
        self.wait_samples: list[int] = []
        self.emergency_wait_samples: list[int] = []
        self.emergency_trip_samples: list[int] = []
        self.pedestrian_wait_samples: list[int] = []
        self.class_wait: dict[str, list[int]] = {}
        self.controller_ms: list[float] = []
        self.recovery_times: list[int] = []
        self.queue_samples: list[float] = []
        self.maximum_queue_length = 0
        self._incident_baseline: dict[str, int] = {}
        self._pending_recovery: list[tuple[Incident, int, int]] = []
        self.status = "running"

    def inject_incident(self, kind: IncidentKind, intersection_id: str = "J2", approach: str = "N", severity: float = .5) -> Incident:
        node = self._get_intersection(intersection_id)
        if approach not in "NSEW": raise ValueError("approach must be N, S, E or W")
        if not 0 <= severity <= 1: raise ValueError("severity must be between 0 and 1")
        incident = Incident(str(uuid.uuid4()), kind, node.id, approach, severity,
                            max(.05, 1 - severity), self.time)
        self.incidents.append(incident)
        self._incident_baseline[incident.id] = len(node.queues[approach])
        if kind == IncidentKind.COMMUNICATION:
            node.communication = False
        elif kind in (IncidentKind.BLOCKAGE, IncidentKind.ACCIDENT):
            node.blocked_approaches.add(approach)
        return incident

    def remove_incident(self, incident_id: str) -> bool:
        for incident in self.incidents:
            if incident.id == incident_id and incident.active:
                incident.active = False
                node = self._get_intersection(incident.intersection_id)
                if incident.kind == IncidentKind.COMMUNICATION:
                    node.communication = True
                if incident.kind in (IncidentKind.BLOCKAGE, IncidentKind.ACCIDENT):
                    node.blocked_approaches.discard(incident.approach)
                baseline = self._incident_baseline.get(incident.id, 0)
                if incident.kind == IncidentKind.COMMUNICATION:
                    self.recovery_times.append(0)
                else:
                    self._pending_recovery.append((incident, baseline, self.time))
                return True
        return False

    def generate_emergency(self, kind: VehicleClass = VehicleClass.AMBULANCE, at: str = "J0") -> Vehicle:
        if kind not in (VehicleClass.AMBULANCE, VehicleClass.FIRE, VehicleClass.POLICE):
            raise ValueError("emergency class must be ambulance, fire or police")
        node = self._get_intersection(at)
        destination = "E" if node.index <= self.TOPOLOGY // 2 else "W"
        approach = "W" if destination == "E" else "E"
        return self._new_vehicle(node, approach, kind, destination)

    def step(self) -> SimulationState:
        if self.status != "running": raise RuntimeError("simulation is not running")
        self._generate_demand()
        for node in self.intersections:
            start = time.perf_counter()
            active = [i for i in self.incidents if i.active]
            visible = [other for other in self.intersections if abs(other.index-node.index) <= 1]
            decision = self.agents[node.id].decide(node, self.config.controller, self.time, visible, active)
            requested, explanation, controller = decision.requested_phase, decision.explanation, decision.controller
            self.controller_ms.append((time.perf_counter() - start) * 1000)
            has_pedestrian_call = any(node.pedestrian_wait.values())
            if has_pedestrian_call and self.safety.request_pedestrian_service(node):
                pass
            elif self.safety.can_change(node, requested):
                self.safety.request_phase(node, requested)
                node.last_decision = f"{controller.value}: {explanation}"
            self._serve(node)
            self.safety.advance(node)
        self.queue_samples.append(statistics.fmean(len(q) for n in self.intersections for q in n.queues.values()))
        self.maximum_queue_length = max(self.maximum_queue_length,
            max((len(q) for n in self.intersections for q in n.queues.values()), default=0))
        self.time += 1
        self._check_recovery()
        if self.time >= self.config.duration_seconds:
            self.status = "finished"
        return self.state()

    def run(self, seconds: int | None = None) -> SimulationState:
        count = seconds if seconds is not None else self.config.duration_seconds - self.time
        for _ in range(max(0, count)):
            if self.status != "running": break
            self.step()
        return self.state()

    def state(self) -> SimulationState:
        queue_lengths = [len(q) for n in self.intersections for q in n.queues.values()]
        metrics = {
            "mean_delay_seconds": statistics.fmean(self.wait_samples) if self.wait_samples else None,
            "p95_delay_seconds": self._percentile(self.wait_samples, .95) if self.wait_samples else None,
            "average_queue_length": statistics.fmean(self.queue_samples) if self.queue_samples else 0.0,
            "maximum_queue_length": self.maximum_queue_length,
            "throughput_vehicles": self.vehicles_passed,
            "intersection_crossings": self.intersection_crossings,
            "pedestrian_wait_seconds": statistics.fmean(self.pedestrian_wait_samples) if self.pedestrian_wait_samples else None,
            "emergency_vehicle_delay_seconds": statistics.fmean(self.emergency_wait_samples) if self.emergency_wait_samples else None,
            "emergency_vehicle_travel_seconds": statistics.fmean(self.emergency_trip_samples) if self.emergency_trip_samples else None,
            "incident_recovery_seconds": statistics.fmean(self.recovery_times) if self.recovery_times else None,
            "controller_execution_ms": statistics.fmean(self.controller_ms) if self.controller_ms else 0.0,
            "per_vehicle_class_mean_delay": {k: statistics.fmean(v) for k, v in self.class_wait.items() if v},
        }
        return SimulationState(self.time, self.intersections, [i for i in self.incidents if i.active],
                               self.vehicles_passed, metrics, self.status,
                               [{"id": v.id, "kind": v.kind.value, "intersection_id": v.current_intersection,
                                 "approach": v.approach, "destination": v.destination, "waiting_seconds": v.waiting}
                                for v in self.emergency_vehicles.values()])

    def _generate_demand(self):
        for node in self.intersections:
            for approach in "NSEW":
                rate = self.config.approach_demand.get(f"{node.id}:{approach}", self.config.demand_per_hour) / 3600
                if self.demand_rng.random() < rate:
                    kinds, weights = zip(*[(VehicleClass(k), w) for k, w in self.config.vehicle_composition.items()])
                    vehicle = self._new_vehicle(node, approach, self.demand_rng.choices(kinds, weights=weights)[0])
                    self.arrivals.append((self.time, node.id, approach, vehicle.kind.value))
                if self.demand_rng.random() < self.config.pedestrian_per_hour / 3600:
                    phase = "NS" if approach in "NS" else "EW"
                    node.pedestrian_wait[phase] += 1
                    node.pedestrian_ages[phase].append(0)
        if self.emergency_rng.random() < self.config.emergency_per_hour / 3600:
            node = self.intersections[self.emergency_rng.randrange(self.TOPOLOGY)]
            kind = self.emergency_rng.choice((VehicleClass.AMBULANCE, VehicleClass.FIRE, VehicleClass.POLICE))
            destination = self.emergency_rng.choice(("E", "W"))
            approach = "W" if destination == "E" else "E"
            vehicle = self._new_vehicle(node, approach, kind, destination)
            self.arrivals.append((self.time, node.id, approach, vehicle.kind.value))

    def _serve(self, node):
        green = self.safety.green_approaches(node)
        if node.stage == "green": node.green_elapsed += 1
        for approach in green:
            if approach in node.blocked_approaches: continue
            incidence = next((i for i in self.incidents if i.active and i.intersection_id == node.id and i.approach == approach), None)
            factor = incidence.capacity_factor if incidence and incidence.kind in (IncidentKind.CAPACITY, IncidentKind.CONGESTION, IncidentKind.BREAKDOWN, IncidentKind.ACCIDENT) else 1.0
            headway = {VehicleClass.MOTORCYCLE: .92, VehicleClass.CAR: .72, VehicleClass.AUTO: .66,
                       VehicleClass.BUS: .42, VehicleClass.HEAVY: .38, VehicleClass.AMBULANCE: .95,
                       VehicleClass.FIRE: .9, VehicleClass.POLICE: .95}
            service_rate = factor * headway.get(node.queues[approach][0].kind, .7) if node.queues[approach] else 0
            if (node.queues[approach] and node.queues[approach][0].ready_at <= self.time
                    and self._downstream_has_space(node, node.queues[approach][0])
                    and (self.service_rng.random() < service_rate or node.queues[approach][0].emergency)):
                vehicle = node.queues[approach].pop(0)
                vehicle.crossed_at = self.time
                self.intersection_crossings += 1
                vehicle.waiting = 0
                self._move_vehicle(node, approach, vehicle)
        for approach, queue in node.queues.items():
            for vehicle in queue:
                vehicle.waiting += 1
                vehicle.total_waiting += 1
        for phase in ("NS", "EW"):
            node.pedestrian_ages[phase] = [age + 1 for age in node.pedestrian_ages[phase]]
            if node.stage == "ped-walk" and node.pedestrian_crossing_count[phase]:
                served = min(node.pedestrian_crossing_count[phase], len(node.pedestrian_ages[phase]))
                self.pedestrian_wait_samples.extend(node.pedestrian_ages[phase][:served])
                node.pedestrian_ages[phase] = node.pedestrian_ages[phase][served:]
                node.pedestrian_wait[phase] -= served
                node.pedestrian_crossing_count[phase] -= served

    def _move_vehicle(self, node, approach, vehicle):
        # Route along the five-node east-west corridor; boundary exits count as delivered.
        destination = vehicle.destination
        if (destination == "E" and node.index == self.TOPOLOGY - 1) or (destination == "W" and node.index == 0):
            self.vehicles_passed += 1
            self.wait_samples.append(vehicle.total_waiting)
            self.class_wait.setdefault(vehicle.kind.value, []).append(vehicle.total_waiting)
            if vehicle.emergency:
                self.emergency_trip_samples.append(self.time - vehicle.entered_at)
                self.emergency_wait_samples.append(vehicle.total_waiting)
                self.emergency_vehicles.pop(vehicle.id, None)
            return
        next_index = node.index + (1 if destination == "E" else -1)
        next_node = self.intersections[next_index]
        next_approach = "W" if destination == "E" else "E"
        if len(next_node.queues[next_approach]) < 40:
            vehicle.approach = next_approach
            vehicle.current_intersection = next_node.id
            vehicle.position = 0
            vehicle.ready_at = self.time + 1
            next_node.queues[next_approach].append(vehicle)

    def _downstream_has_space(self, node, vehicle):
        if (vehicle.destination == "E" and node.index == self.TOPOLOGY - 1) or (vehicle.destination == "W" and node.index == 0):
            return True
        next_index = node.index + (1 if vehicle.destination == "E" else -1)
        next_approach = "W" if vehicle.destination == "E" else "E"
        return len(self.intersections[next_index].queues[next_approach]) < 40

    def _new_vehicle(self, node, approach, kind, destination=None):
        self.next_vehicle += 1
        if destination is None:
            destination = "E" if approach == "W" else "W" if approach == "E" else self.route_rng.choice(("E", "W"))
        vehicle = Vehicle(f"v{self.next_vehicle}", kind, approach, destination, self.time,
                          emergency=kind in (VehicleClass.AMBULANCE, VehicleClass.FIRE, VehicleClass.POLICE),
                          current_intersection=node.id)
        node.queues[approach].append(vehicle)
        if vehicle.emergency: self.emergency_vehicles[vehicle.id] = vehicle
        return vehicle

    def _check_recovery(self):
        pending = []
        for incident, baseline, cleared_at in self._pending_recovery:
            node = self._get_intersection(incident.intersection_id)
            if len(node.queues[incident.approach]) <= baseline:
                self.recovery_times.append(self.time - cleared_at)
            else:
                pending.append((incident, baseline, cleared_at))
        self._pending_recovery = pending

    def _get_intersection(self, ident):
        for node in self.intersections:
            if node.id == ident: return node
        raise ValueError(f"unknown intersection: {ident}")

    @staticmethod
    def _percentile(values, fraction):
        if not values: return 0.0
        ordered = sorted(values)
        return float(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))])
