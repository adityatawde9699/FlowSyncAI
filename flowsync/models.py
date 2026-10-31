from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ControllerKind(str, Enum):
    FIXED = "fixed-time"
    ACTUATED = "actuated"
    MAX_PRESSURE = "max-pressure"
    FLOWSYNC = "flowsync"


class VehicleClass(str, Enum):
    MOTORCYCLE = "motorcycle"
    CAR = "car"
    AUTO = "auto-rickshaw"
    BUS = "bus"
    HEAVY = "heavy"
    AMBULANCE = "ambulance"
    FIRE = "fire"
    POLICE = "police"


class IncidentKind(str, Enum):
    BLOCKAGE = "lane-blockage"
    CAPACITY = "capacity-reduction"
    CONGESTION = "congestion"
    BREAKDOWN = "vehicle-breakdown"
    ACCIDENT = "accident"
    COMMUNICATION = "communication-failure"


@dataclass
class Vehicle:
    id: str
    kind: VehicleClass
    approach: str
    destination: str
    entered_at: int
    position: float = 0.0
    emergency: bool = False
    waiting: int = 0
    total_waiting: int = 0
    ready_at: int = 0
    crossed_at: int | None = None
    current_intersection: str | None = None


@dataclass
class Incident:
    id: str
    kind: IncidentKind
    intersection_id: str
    approach: str
    severity: float = 0.5
    capacity_factor: float = 0.5
    started_at: int = 0
    active: bool = True


@dataclass
class Intersection:
    id: str
    index: int
    phase: str = "NS"
    stage: str = "green"
    stage_elapsed: int = 0
    green_elapsed: int = 0
    queues: dict[str, list[Vehicle]] = field(default_factory=lambda: {a: [] for a in ("N", "S", "E", "W")})
    pedestrian_wait: dict[str, int] = field(default_factory=lambda: {a: 0 for a in ("NS", "EW")})
    pedestrian_ages: dict[str, list[int]] = field(default_factory=lambda: {a: [] for a in ("NS", "EW")})
    pedestrian_crossing_count: dict[str, int] = field(default_factory=lambda: {a: 0 for a in ("NS", "EW")})
    communication: bool = True
    local_fallback: str = "max-pressure"
    last_decision: str = "initial phase"
    blocked_approaches: set[str] = field(default_factory=set)
    pending_phase: str | None = None
    pending_pedestrian: bool = False
    side_street_sinks: bool = False

    def queue_size(self, approach: str) -> int:
        return len(self.queues[approach])


@dataclass
class SimulationConfig:
    seed: int = 7
    duration_seconds: int = 1800
    demand_per_hour: int = 480
    pedestrian_per_hour: int = 70
    emergency_per_hour: int = 4
    approach_demand: dict[str, int] = field(default_factory=dict)
    controller: ControllerKind = ControllerKind.FLOWSYNC
    engine: str = "auto"
    vehicle_composition: dict[str, float] = field(default_factory=lambda: {
        "motorcycle": .39, "car": .33, "auto-rickshaw": .16,
        "bus": .06, "heavy": .06,
    })


@dataclass
class SimulationState:
    time: int
    intersections: list[Intersection]
    active_incidents: list[Incident]
    vehicles_passed: int
    metrics: dict[str, Any]
    status: str = "running"
    emergency_vehicles: list[dict[str, Any]] = field(default_factory=list)
