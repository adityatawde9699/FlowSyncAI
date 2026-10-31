"""Intersection-local decision agent; receives only self and adjacent-node state."""
from dataclasses import dataclass

from flowsync.control.controllers import choose_phase
from flowsync.models import ControllerKind, Incident


@dataclass(frozen=True)
class PhaseDecision:
    requested_phase: str
    controller: ControllerKind
    explanation: str
    neighbor_count: int


class IntersectionAgent:
    def __init__(self, intersection_id: str, fallback: ControllerKind = ControllerKind.MAX_PRESSURE):
        self.intersection_id = intersection_id
        self.fallback = fallback

    def decide(self, intersection, controller: ControllerKind, time: int,
               available_neighbors: list, incidents: list[Incident]) -> PhaseDecision:
        connected = intersection.communication
        active_controller = controller if connected else self.fallback
        visible_nodes = available_neighbors if connected else [intersection]
        local_incidents = [incident for incident in incidents
                           if incident.intersection_id == self.intersection_id and incident.active]
        phase, explanation = choose_phase(intersection, active_controller, time, visible_nodes, local_incidents)
        return PhaseDecision(phase, active_controller, explanation, max(0, len(visible_nodes)-1))
