# Development status and roadmap

## Completed implementation slices

1. **Repository audit and architecture:** initial workspace was empty; modular package boundaries and documented decisions are in place.
2. **Simulation foundation:** generated five-signal SUMO network/route files, TraCI engine and deterministic fallback are implemented. Source-level topology, seeded demand, and emergency route edge-connectivity tests pass. SUMO 1.25 network conversion and standalone simulation run successfully; TraCI runtime integration is skipped in this restricted container because local TCP sockets cannot be bound.
3. **Baseline controllers:** fixed-time, actuated and Max Pressure operate in both available engine paths; SUMO controller behavior needs execution on an installed SUMO runtime.
4. **FlowSync:** downstream queue pressure, incident severity, emergency requests, pedestrian demand and local communication fallback affect phase recommendations. This is an implementation hypothesis, not a novelty claim.
5. **Safety and incidents:** fallback enforces minimum green, yellow, all-red, dedicated pedestrian walk and pedestrian clearance; incidents can be injected/removed; emergency routes wait for safe phase transitions. SUMO retains generated signal clearance phases.
6. **API and dashboard:** process-isolated simulation worker, REST/WebSocket controls, session/event/observation persistence, comparative experiment jobs and React controls/charts are implemented.
7. **Evaluation:** nine scenarios, common seeded arrival traces, paired controller results, per-class summaries, confidence intervals and JSON/CSV reports are implemented. Only short fallback smoke comparisons have been run; no research conclusions are available.
8. **Packaging/docs:** Docker Compose configuration validates; installation, API, algorithm, experiment and limitation docs are present. Python verification currently reports 15 passed and 2 integration skips. Docker image builds and frontend builds cannot be run in this restricted environment because dependencies are unavailable.

## Remaining validation work

- Execute the skipped TraCI integration test from an environment that allows local TCP sockets. Check generated TLS program states, pedestrian crossings, incident effects and emergency insertion. The generated routes and standalone SUMO run have already been checked on SUMO 1.25.
- Install the frontend dependencies and run `npm run build`; perform desktop/tablet browser QA. Generate and commit an npm lockfile when dependency installation is available.
- Install FastAPI, Pydantic and HTTPX, then execute the skipped API lifecycle test and exercise WebSocket and experiment job endpoints.
- Run all nine scenarios with the preregistered seed matrix on SUMO, inspect failed/unroutable departures, and review paired confidence intervals before discussing targets.
- Calibrate demand composition, speeds, lane widths, sublane model and pedestrian behavior against appropriate Indian traffic observations. None are calibrated now.
- Harden experiment job restart/recovery and add authentication before any shared network deployment.
