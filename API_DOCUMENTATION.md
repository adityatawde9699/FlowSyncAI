# API reference

Install `.[api]`, run `uvicorn flowsync.api.app:app`, and browse `/docs`. The simulation engine runs in a separate spawned process. A WebSocket connection advances one simulation second every 250 ms; use REST pause/step controls to change that behavior. All endpoints operate on simulation data only.

## Simulation control

| Method | Path | Behavior |
|---|---|---|
| `POST` | `/api/simulations` | Start/reset. JSON: `seed`, `duration_seconds` (60–86400), `demand_per_hour` (0–10000), `pedestrian_per_hour`, `controller`, `engine` (`auto`, `sumo`, `fallback`). |
| `POST` | `/api/simulations/step` | Advance one second unless paused/stopped. |
| `POST` | `/api/simulations/pause` | Pause WebSocket-driven advancement. |
| `POST` | `/api/simulations/resume` | Resume advancement. |
| `POST` | `/api/simulations/stop` | Stop and close the active engine. |
| `PUT` | `/api/simulations/controller/{controller}` | Set `fixed-time`, `actuated`, `max-pressure` or `flowsync`. |
| `GET` | `/api/state` | Current actual state snapshot. |
| `GET` | `/api/simulations/{simulation_id}/history` | Manifest, events, periodic metrics and labelled observations from SQLite. |
| `WS` | `/api/stream` | Stream live snapshots and advance while running. |

## Incidents and emergency vehicles

`POST /api/incidents` accepts `kind`, `intersection_id` (`J0`–`J4`), `approach` (`N/S/E/W`) and `severity` (0–1). Kinds are `lane-blockage`, `capacity-reduction`, `congestion`, `vehicle-breakdown`, `accident`, and `communication-failure`. `DELETE /api/incidents/{incident_id}` clears an active incident.

`POST /api/emergency-vehicles` accepts `kind` (`ambulance`, `fire`, `police`) and `intersection_id`. It returns a vehicle ID and current simulation snapshot. Priority remains subject to safe signal transitions.

## Observations

`POST /api/observations` stores an observation linked to a simulation ID. Required fields: `simulation_id`, `intersection_id`, `approach`, `source` (`simulation` or `video:<adapter>`), and `confidence` 0–1. Optional fields: class counts, queue estimate, density and timestamp. The source is retained in history; camera data is not labelled as simulation and vice versa.

## Experiments and reports

- `POST /api/experiments` accepts scenario names, seeds, duration and controllers; returns `202` with an experiment ID. Execution uses a separate process pool.
- `GET /api/experiments/{id}` polls status and summary.
- `GET /api/experiments/{id}/results` returns per-run records, per-scenario/per-class summaries and paired differences.
- `GET /api/experiments/{id}/report?format=json|csv` downloads the report.

Experiment jobs/status live in API-process memory; completed run data persists in SQLite. Restarting the API can make old job status unavailable while stored results remain queryable if the ID is known.

## Errors and safety

Invalid request fields return `422`, absent simulations/results return `404` or `409`, and missing required SUMO dependencies fail clearly. The development API has no authentication and must not be exposed to an untrusted network. It has no route to live signals.
