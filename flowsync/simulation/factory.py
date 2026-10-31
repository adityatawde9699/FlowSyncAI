import logging
import os

from flowsync.models import SimulationConfig
from flowsync.simulation.engine import TrafficSimulation
from flowsync.simulation.sumo import SumoSimulation, availability, require_sumo

_log = logging.getLogger(__name__)
_sumo_failed = False


def reset_sumo_failure():
    """Reset the failure cache (useful for testing or after runtime environment fixes)."""
    global _sumo_failed
    _sumo_failed = False


def create_simulation(config: SimulationConfig):
    """Use SUMO by default when the full runtime is present; otherwise report and use fallback."""
    global _sumo_failed
    env_engine = os.environ.get("FLOWSYNC_ENGINE", "").lower().strip()
    if env_engine in ("fallback", "sumo") and config.engine == "auto":
        config.engine = env_engine

    if config.engine == "fallback":
        return TrafficSimulation(config)
    if config.engine == "sumo":
        require_sumo()
        return SumoSimulation(config)
    if config.engine != "auto":
        raise ValueError("engine must be auto, sumo, or fallback")

    if not _sumo_failed and all(availability().values()):
        try:
            config.engine = "sumo"
            return SumoSimulation(config)
        except Exception as exc:
            _log.warning("SUMO initialization failed, falling back to pure-Python engine: %s", exc)
            _sumo_failed = True
            config.engine = "fallback"
            return TrafficSimulation(config)
    config.engine = "fallback"
    return TrafficSimulation(config)

