# Experiment methodology

## Status

The experiment manager is implemented. The fallback smoke run verifies serialization and report output. SUMO 1.25 network generation and standalone simulation have been checked; the project machine has also run TraCI, but that run exposed crossing, delay and teleport artifacts. The metrics have since been corrected and need a fresh full TraCI run before use. No calibrated traffic experiment or improvement claim is available.

## Scenario matrix

`low-traffic`, `normal-traffic`, `peak-hour`, `asymmetric-traffic`, `road-blockage`, `emergency-movement`, `multiple-incidents`, `communication-failure`, and `pedestrian-heavy` are implemented. Scenarios set demand/pedestrian rates, approach imbalance, incident schedules and emergency requests. Defaults are exploratory and need calibration.

Each `(scenario, seed)` constructs a seeded explicit vehicle/person departure trace, type assignment, route and per-vehicle speed factor before controller execution. Each of the four controllers receives the same trace and incident/event schedule for that pair. SUMO control can change resulting trajectories, which is the experimental treatment; the input demand is held constant. Random draws for fallback arrivals, route assignment and service behavior use separate streams, preventing controller-dependent service from perturbing later arrivals.

## Metrics

- Mean and p95 completed-trip delay. The fallback measures accumulated queue waiting; SUMO measures accumulated time loss relative to desired speed.
- Time-averaged queue length per approach and peak approach queue.
- Vehicles exiting the network and intersection crossings.
- SUMO teleporting is disabled so gridlock remains in the network and does not inflate completed-trip throughput.
- Emergency completed-trip delay and travel time (null when no emergency trip completes).
- Mean completed continuous pedestrian waiting interval (null when no interval completes during the run).
- Incident recovery time from incident removal until the affected queue returns to its pre-incident count (null if recovery is not observed before run end).
- Mean controller execution time.
- Per-vehicle-class completed-trip delay using the engine-specific definition above.

Run configs, seeds, metric outputs and experiment IDs are persisted in SQLite. Results contain means, standard deviations and two-sided 95% Student-t intervals across seeds. Paired `FlowSync − baseline` differences use matched scenario/seed runs. The `n=1` interval is reported as unavailable; nonnegative metric intervals are clipped to zero. No performance target is hardcoded as an outcome.

## Recommended research procedure

Use SUMO for results. Freeze network/configuration, warm-up, measurement window, seeds, demand and incident schedule before comparison. Run at least 20 scenario-seed pairs where compute permits, retain failed/unroutable runs, inspect vehicle-class breakdowns, and report paired differences and intervals. Perform ablations for each FlowSync term and sensitivity checks for weights. Tune only on disjoint seeds. Calibrate demand and behavior using labelled local observations before interpreting absolute values.

Example exploratory run:

```sh
flowsync --experiment --scenarios normal-traffic peak-hour --seeds 11 23 37 41 53 \
  --seconds 1800 --engine sumo --export results.csv
```
