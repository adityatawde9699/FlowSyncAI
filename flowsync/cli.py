import argparse
import json

from flowsync.models import ControllerKind, SimulationConfig
from flowsync.simulation.factory import create_simulation
from flowsync.simulation.sumo import availability


def main():
    parser = argparse.ArgumentParser(description="Run a reproducible FlowSync simulation")
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--demand", type=int, default=480, help="vehicles/hour/approach")
    parser.add_argument("--pedestrians", type=int, default=70, help="pedestrians/hour/crossing")
    parser.add_argument("--emergency", type=int, default=4, help="emergency vehicles/hour/network")
    parser.add_argument("--controller", choices=[x.value for x in ControllerKind], default="flowsync")
    parser.add_argument("--engine", choices=["auto", "fallback", "sumo"], default="auto")
    parser.add_argument("--experiment", action="store_true", help="run paired controller experiment matrix")
    parser.add_argument("--scenarios", nargs="+", help="experiment scenario names")
    parser.add_argument("--seeds", nargs="+", type=int, default=[11, 23, 37, 41, 53])
    parser.add_argument("--store", help="SQLite file path override (otherwise use DATABASE_URL or the default SQLite file)")
    parser.add_argument("--export", help="write experiment report as .json or .csv")
    args = parser.parse_args()
    if args.experiment:
        from flowsync.experiments.runner import ExperimentRunner, SCENARIOS, export_report
        from flowsync.experiments.store import ExperimentStore
        scenarios = args.scenarios or list(SCENARIOS)
        result = ExperimentRunner(ExperimentStore(args.store)).run(scenarios=scenarios, seeds=args.seeds,
                                                                    duration_seconds=args.seconds)
        if args.export: export_report(result["runs"], args.export)
        print(json.dumps({"experiment_id": result["experiment_id"], "runs": len(result["runs"]),
                          "summary": result["summary"], "export": args.export}, indent=2))
        return
    sim = create_simulation(SimulationConfig(seed=args.seed, duration_seconds=args.seconds,
             demand_per_hour=args.demand, pedestrian_per_hour=args.pedestrians, emergency_per_hour=args.emergency,
             controller=ControllerKind(args.controller), engine=args.engine))
    try: state = sim.run()
    finally:
        if hasattr(sim, "close"): sim.close()
    runtime = availability()
    print(json.dumps({"engine": sim.config.engine, "sumo_available": all(runtime.values()),
                      "sumo_components": runtime,
                      "time": state.time, "status": state.status, "metrics": state.metrics}, indent=2))


if __name__ == "__main__": main()
