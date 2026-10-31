"""Independent signal interlock. Controllers can request phases; only this layer applies them."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyConfig:
    min_green: int = 10
    max_green: int = 55
    yellow: int = 3
    all_red: int = 1
    pedestrian_walk: int = 7
    pedestrian_clearance: int = 5


class SignalSafety:
    def __init__(self, config: SafetyConfig | None = None):
        self.config = config or SafetyConfig()

    def can_change(self, intersection, requested_phase: str) -> bool:
        if requested_phase == intersection.phase or intersection.stage != "green":
            return False
        return intersection.green_elapsed >= self.config.min_green

    def request_phase(self, intersection, requested_phase: str) -> bool:
        if not self.can_change(intersection, requested_phase):
            return False
        intersection.stage = "yellow"
        intersection.stage_elapsed = 0
        intersection.last_decision = f"safe transition {intersection.phase} to {requested_phase}"
        intersection.pending_phase = requested_phase
        return True

    def request_pedestrian_service(self, intersection) -> bool:
        if intersection.stage != "green" or intersection.green_elapsed < self.config.min_green:
            return False
        intersection.stage = "yellow"
        intersection.stage_elapsed = 0
        intersection.pending_phase = intersection.phase
        intersection.pending_pedestrian = True
        intersection.pedestrian_crossing_count = dict(intersection.pedestrian_wait)
        intersection.last_decision = "pedestrian call: safe clearance requested"
        return True

    def advance(self, intersection) -> None:
        intersection.stage_elapsed += 1
        if intersection.stage == "green" and intersection.green_elapsed >= self.config.max_green:
            intersection.stage = "yellow"
            intersection.stage_elapsed = 0
            intersection.pending_phase = "EW" if intersection.phase == "NS" else "NS"
        elif intersection.stage == "yellow" and intersection.stage_elapsed >= self.config.yellow:
            intersection.stage = "all-red"
            intersection.stage_elapsed = 0
        elif intersection.stage == "all-red" and intersection.stage_elapsed >= self.config.all_red:
            if intersection.pending_pedestrian:
                intersection.stage = "ped-walk"
            else:
                intersection.phase = intersection.pending_phase or ("EW" if intersection.phase == "NS" else "NS")
                intersection.stage = "green"
                intersection.green_elapsed = 0
            intersection.stage_elapsed = 0
            return
        elif intersection.stage == "ped-walk" and intersection.stage_elapsed >= self.config.pedestrian_walk:
            intersection.stage = "ped-clearance"
            intersection.stage_elapsed = 0
        elif intersection.stage == "ped-clearance" and intersection.stage_elapsed >= self.config.pedestrian_clearance:
            intersection.pending_pedestrian = False
            intersection.phase = intersection.pending_phase or intersection.phase
            intersection.stage = "green"
            intersection.stage_elapsed = 0
            intersection.green_elapsed = 0

    @staticmethod
    def green_approaches(intersection) -> set[str]:
        if intersection.stage != "green":
            return set()
        return {"N", "S"} if intersection.phase == "NS" else {"E", "W"}
