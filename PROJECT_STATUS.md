# FlowSync AI project status

**Last audited:** 2026-10-31  
**Overall estimated completion:** 49%  
**Basis:** Core modules and substantial docs exist; a SUMO/TraCI version mismatch found during deployment diagnosis is fixed in the Docker build, and failed experiment jobs now report a terminal state. Live Render/Vercel deployment and cross-platform verification remain incomplete. This is an engineering completeness estimate, not a measured project KPI.

## Completed tasks

- Repository inventory and implementation review completed across simulation, safety, controllers, perception, API, experiments, persistence, frontend, tests, docs and packaging.
- `TASKS.md` created with priorities, dependencies, expected outputs, acceptance criteria and relevant checks.
- Five-intersection scenario generation, heterogeneous vehicle definitions, pedestrian route generation and seeded departures are implemented in source.
- Fixed-time, actuated, Max Pressure and FlowSync controllers are implemented in source.
- SQLite persistence, REST/WebSocket API, dashboard controls and experiment report paths are implemented in source.
- FS-001 complete: removed duplicate fallback queue insertion and added a deterministic regression test.
- Frontend TypeScript/Vite production build succeeds (`npm run build`); bundle warning reports a 541.85 kB minified JS chunk.
- `docker compose config --quiet` succeeds; Docker image build is blocked by the sandbox's denied Docker socket access.
- Added Render Blueprint and Vercel static SPA configuration; made the container honor Render's `PORT`, added `/health`, configured environment-driven CORS, and documented the two-platform setup.
- Fixed the Render build error: Dockerfile health checks use `CMD` (Dockerfile syntax), not the Compose-only `CMD-SHELL` form. Render build retry is still required.
- Deployment logs showed SUMO route lookup failures. The local installation reports SUMO 1.25.0 with TraCI 1.28.0; the Docker image now imports TraCI and sumolib from the same apt-installed SUMO tools directory, avoiding a separate pip version lookup. Local instructions also describe version matching.
- Render's next build failed because its SUMO version text did not match the version-extraction expression. Removed that fragile extraction and verified that `/usr/share/sumo/tools` provides importable TraCI/sumolib modules.
- Latest browser report shows Render returns HTTP 502 for API requests and cannot accept the WebSocket. The app CORS configuration is environment-driven; deploy health and `FLOWSYNC_CORS_ORIGINS` still need verification after Render is live. The workspace cannot resolve the Render hostname to probe it directly.
- Experiment job exceptions now return a terminal `failed` state instead of repeated HTTP 500 responses; the dashboard stops polling and displays the error. WebSocket stream worker errors are sent as state messages and retried.
- Fixed the reported `'str' object has no attribute 'value'` experiment failure: API worker payloads now convert controller names back to `ControllerKind` before running experiments.
- Dashboard experiment polling now stops on a stale-job `404` after API restart and tells the user to start a new comparison. The supplied logs show new emergency requests succeeding (`201`) and experiment submissions/status polling succeeding (`202`/`200`).

## In-progress tasks

- **FS-004 (P0):** the API lifecycle test stalls during `TestClient` startup. A trivial standalone FastAPI app stalls the same way under the installed client stack, indicating an environment-level test-client issue; API behavior still needs verification through a compatible harness.
- **FS-002 (P0):** Docker now uses the apt-provided TraCI/sumolib modules matching SUMO; a new Render build and runtime verification are still required. Local TCP socket binding is unavailable, so the integration test skips.
- **FS-022 (P0):** the hosted API is currently returning 502. Push the updated Dockerfile and verify the latest Render deployment is Live before diagnosing app-level CORS.

## Blocked tasks

- **FS-002 SUMO/TraCI runtime validation:** SUMO, netconvert and TraCI are present, but socket binding is unavailable (`traci_socket: false`), preventing TraCI launch.
- **FS-004 API runtime validation:** API dependencies are present, but the lifecycle test hangs before its first request during TestClient startup. The new experiment failure response is unit-tested directly.
- **FS-006 Docker image validation:** Docker is installed, but the sandbox denies access to `/var/run/docker.sock`, preventing local image build/run.
- **FS-012 video validation:** a compatible ONNX weights file and actual video fixture are not included in the repository.

## Failed tests

- Full `pytest -q` does not finish: verbose run isolates the stall at `test_api_validation_and_simulation_lifecycle_when_optional_api_is_installed`, at `TestClient(app)` startup. A 20-second faulthandler timeout confirms the main test thread waits in `TestClient.__enter__` while its AnyIO portal is idle. A minimal standalone FastAPI route with the same installed TestClient stack also hangs before entering the client context.
- Excluding that API lifecycle test: `20 passed, 1 skipped, 1 deselected in 0.28s`.
- The one skip is `test_sumo_integration_when_runtime_is_installed`; local socket binding is unavailable.

## Remaining P0/P1 tasks

- FS-002 SUMO runtime and state/metric checks.
- FS-003 cross-engine safety verification.
- FS-004 API startup/lifecycle diagnosis and WebSocket/persistence validation.
- FS-005 browser control verification (production build passes).
- FS-006 Compose deployment validation.
- FS-022/FS-023 actual Render/Vercel Blueprint import, deploy and cross-origin live verification.
- FS-007 through FS-014 capability-specific controller, coordination, incident, emergency, perception, experiment and observability validation.

## Latest working commands

- Repository inventory: `rg --files -g '!node_modules' -g '!dist' -g '!build' -g '!venv' -g '!.venv'`
- `.venv/bin/python -m pytest -q -k 'not api_validation_and_simulation_lifecycle_when_optional_api_is_installed'` → 20 passed, 1 skipped, 1 deselected.
- `docker compose config --quiet` → succeeds. `docker compose build` cannot access Docker's per-user buildx state in the read-only home; using `DOCKER_CONFIG=/tmp/...` advances to a denied `/var/run/docker.sock` connection.
- `docker build --check -t flowsyncai-api .` → blocked by denied `/var/run/docker.sock`; Dockerfile syntax fix is not locally daemon-validated.
- `npm run build` in `frontend/` → succeeds with a Vite large-chunk warning.
- Frontend rebuild after stale experiment ID handling → succeeds.
- Render YAML parses with PyYAML; Vercel JSON parses; `flowsync/api/app.py` compiles.
- `flowsync.simulation.sumo.availability()` → SUMO/netconvert/TraCI present; local TraCI socket unavailable.
- Local tool versions: SUMO `1.25.0`, TraCI Python client `1.28.0`; Docker avoids this mismatch by using the apt-provided module path.

## Next recommended implementation task

Push the Docker/TraCI version-alignment and experiment controller enum fix to the connected GitHub branch, redeploy Render and Vercel, then verify `/health`, WebSocket reconnect, emergency route insertion and a short experiment. This workspace has no usable Git metadata or deployment CLI credentials, so those platform connection steps cannot be completed from this checkout. Separately run SUMO where local sockets are allowed.
