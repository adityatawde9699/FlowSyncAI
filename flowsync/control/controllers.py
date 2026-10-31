from __future__ import annotations

from flowsync.models import ControllerKind


def phase_pressure(intersection, phase: str, downstream: dict[str, int] | None = None) -> float:
    downstream = downstream or {}
    approaches = ("N", "S") if phase == "NS" else ("E", "W")
    score = 0.0
    for arm in approaches:
        upstream = intersection.queue_size(arm)
        if arm == "W":
            downstream_queue = downstream.get(f"J{intersection.index + 1}:W", 0)
        elif arm == "E":
            downstream_queue = downstream.get(f"J{intersection.index - 1}:E", 0)
        elif getattr(intersection, "side_street_sinks", False):
            downstream_queue = 0
        else:
            neighbors = [downstream[key] for key in
                (f"J{intersection.index + 1}:W", f"J{intersection.index - 1}:E") if key in downstream]
            downstream_queue = sum(neighbors) / len(neighbors) if neighbors else 0
        score += upstream - 0.7 * downstream_queue
    return score


def choose_phase(intersection, kind: ControllerKind, time: int, network: list, incidents: list) -> tuple[str, str]:
    if kind == ControllerKind.FIXED:
        return ("NS" if time % 80 < 40 else "EW", "fixed 40s split")
    if kind == ControllerKind.ACTUATED:
        ns = sum(intersection.queue_size(a) for a in ("N", "S"))
        ew = sum(intersection.queue_size(a) for a in ("E", "W"))
        return ("NS" if ns >= ew else "EW", f"actuated demand NS={ns}, EW={ew}")

    downstream = {f"{node.id}:{arm}": node.queue_size(arm) for node in network for arm in "NSEW"}
    ns = phase_pressure(intersection, "NS", downstream)
    ew = phase_pressure(intersection, "EW", downstream)
    if kind == ControllerKind.FLOWSYNC:
        # Severity weights blocked/local approaches; emergency and pedestrian demands
        # enter the phase score. Remote congestion is exchanged only with live peers.
        for incident in incidents:
            if incident.active and incident.intersection_id == intersection.id:
                if incident.approach in "NS": ns -= 6 * incident.severity
                else: ew -= 6 * incident.severity
        ns += 2.5 * intersection.pedestrian_wait["NS"] / 30
        ew += 2.5 * intersection.pedestrian_wait["EW"] / 30
        for arm in "NS":
            if any(v.emergency for v in intersection.queues[arm]): ns += 50
        for arm in "EW":
            if any(v.emergency for v in intersection.queues[arm]): ew += 50
    return ("NS" if ns >= ew else "EW", f"pressure NS={ns:.1f}, EW={ew:.1f}")
