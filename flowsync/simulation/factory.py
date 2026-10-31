from flowsync.models import SimulationConfig
from flowsync.simulation.engine import TrafficSimulation
from flowsync.simulation.sumo import SumoSimulation, availability, require_sumo


def create_simulation(config: SimulationConfig):
    """Use SUMO by default when the full runtime is present; otherwise report and use fallback."""
    if config.engine == "fallback": return TrafficSimulation(config)
    if config.engine == "sumo":
        require_sumo()
        return SumoSimulation(config)
    if config.engine != "auto": raise ValueError("engine must be auto, sumo, or fallback")
    if all(availability().values()):
        config.engine = "sumo"
        return SumoSimulation(config)
    config.engine = "fallback"
    return TrafficSimulation(config)
