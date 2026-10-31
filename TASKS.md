# FlowSync AI task register

This register reflects the code and local validation inspected on 2026-10-31. “Complete” means the stated acceptance criteria are evidenced by implementation and an executed check; documentation claims alone do not qualify. Items are grouped by dependency order within priority.

## P0 — working, safe, demonstrable core

| ID | Module | Description | Status | Dependencies | Expected output | Acceptance criteria | Relevant tests |
|---|---|---|---|---|---|---|---|
| FS-001 | Fallback simulation | Ensure each demand arrival is inserted into a queue exactly once. `_new_vehicle` currently enqueues and `_generate_demand` enqueues again. | Complete | — | Corrected demand path and regression test | Each generated demand arrival is represented by exactly one queued vehicle, with no duplicate vehicle IDs. Targeted deterministic regression passes. | `test_generated_vehicle_is_enqueued_exactly_once` |
| FS-002 | SUMO simulation | Execute and validate the five-signal SUMO/TraCI path, TLS phases, pedestrian crossings, incidents, emergency insertion and metrics. | Partially complete (version mismatch fix added) | FS-001 | Verified SUMO run and documented artifacts | TraCI integration test passes in an environment with SUMO tools and local sockets; runtime outputs confirm five signals and usable state. | `test_sumo_scenario_sources_define_five_signals_and_heterogeneous_demand`, `test_sumo_integration_when_runtime_is_installed` |
| FS-003 | Signal safety | Verify safe transition invariants on both engines, including conflicting greens, minimum green, yellow/all-red, pedestrian clearance and emergency priority. | Partially complete | FS-002 | Safety contract and fixes if needed | Tests establish no conflicting vehicle phases and no priority bypass of vehicle/pedestrian clearance. | existing safety tests; add SUMO safety/integration checks |
| FS-004 | Backend/API | Execute API lifecycle, validation, WebSocket, incident/emergency controls, persistence and error paths. | In progress (experiment failure status fixed) | FS-001, FS-002 | API-tested control plane | API tests pass; invalid configuration is rejected; snapshots match live simulation state. | `test_api_validation_and_simulation_lifecycle_when_optional_api_is_installed`, `test_experiment_status_returns_terminal_failure_state`; add endpoint/WebSocket tests |
| FS-005 | Frontend integration | Verify production build and browser flows against live API state; ensure controls reflect successful backend operations. | Partially complete (build passes) | FS-004 | Buildable and browser-verified dashboard | TypeScript/Vite build passes and primary controls update actual backend state without fabricated values. | `npm run build`; browser smoke/e2e |
| FS-006 | Packaging | Build and run the Compose deployment, including health check, API and dashboard. | Partially complete (config passes) | FS-002, FS-004, FS-005 | Reproducible local container stack | `docker compose build` and service smoke checks succeed. | Compose build and HTTP smoke checks |
| FS-022 | Deployment | Configure Render Blueprint, dynamic port binding, health endpoint and persistent SQLite location. | Partially complete (configuration validated) | FS-004, FS-006 | Git-backed Render API service definition | Blueprint is accepted by Render and service responds on its assigned port; disk survives restart/redeploy. | YAML parse, Render Blueprint validation and deployed health/persistence smoke checks |
| FS-023 | Deployment | Configure Vercel project root, Vite build/output, SPA fallback and API origin. | Partially complete (build/config validated) | FS-005, FS-022 | Git-backed Vercel frontend project configuration | Vercel build succeeds; production REST and WebSocket connections reach the Render API with correct CORS origin. | JSON parse, frontend build and deployed browser smoke checks |

## P1 — essential project capabilities

| ID | Module | Description | Status | Dependencies | Expected output | Acceptance criteria | Relevant tests |
|---|---|---|---|---|---|---|---|
| FS-007 | SUMO scenario | Confirm every required vehicle class, configured approach demand, pedestrian crossings and emergency routes are present and reproducible. | Partially complete | FS-002 | Verified scenario generator | Generated route/person inputs contain five connected signal nodes and seeded heterogeneous traffic for tested configuration. | SUMO source-generation and repeatability tests |
| FS-008 | Controllers | Validate fixed-time, actuated, Max Pressure and FlowSync behavior independently in both engines. | Partially complete | FS-002, FS-003 | Controller behavior checks | Each controller makes attributable decisions; paired runs use common demand traces. | add controller unit tests and per-engine integration tests |
| FS-009 | FlowSync coordination | Verify adjacent-neighbor information, downstream capacity, incident, emergency, pedestrian and communication-fallback terms. | Partially complete | FS-008 | Decision-level tests and algorithm docs | Each input changes the documented decision in a constructed case; link loss falls back locally. | agent/controller unit tests |
| FS-010 | Incidents | Verify dynamic incident application/removal, capacity loss, blocked approaches, congestion response and recovery-time measurement on SUMO and fallback. | Partially complete | FS-002, FS-008 | Incident lifecycle validation | Inject/clear restores affected capacity and records only measured recovery. | incident tests in both engines |
| FS-011 | Emergency vehicles | Verify ambulance/fire/police request, route tracking, next junction, safe priority, cancellation/recovery and delay/travel metrics. | Partially complete | FS-002, FS-003, FS-008 | Emergency workflow validation | Emergency path is safe and metrics derive from completed simulated trips. | emergency tests for both engines/API |
| FS-012 | Computer vision | Verify ONNX detector output formats, class/count/density and stationary queue tracking on real test frames/video; clearly label source. | Partially complete | — | Reproducible perception test fixture and usage | OpenCV pipeline processes supplied test input; missing model/input fails clearly; simulation is not passed off as video. | perception unit tests and optional video fixture tests |
| FS-013 | Experiments | Validate nine scenarios, matched seed traces, all metrics, confidence intervals, persistence and CSV/JSON report export. | Partially complete (failure state and API enum conversion fixed) | FS-002, FS-008, FS-010, FS-011 | Verified experiment/report workflow | Identical scenario-seed inputs per controller; samples and unavailable metrics are represented honestly; export round-trips. | experiment runner/store/report tests, `test_experiment_status_returns_terminal_failure_state`, `test_api_experiment_worker_restores_controller_enums` |
| FS-014 | Observability | Audit structured logs, SQLite lifecycle, restart behavior, validation and error handling. | Partially complete | FS-004, FS-013 | Operational behavior notes and resilience fixes | Failures are logged with context; persisted state is queryable; process shutdown cleans up worker resources. | API/store lifecycle tests |

## P2 — research rigor and advanced functionality

| ID | Module | Description | Priority status | Dependencies | Expected output | Acceptance criteria | Relevant tests |
|---|---|---|---|---|---|---|---|
| FS-015 | Research validation | Run preregistered multi-seed comparisons on SUMO; inspect confidence intervals and scenario-wise effects without performance claims ahead of results. | Not started | FS-002, FS-008, FS-013 | Versioned experiment artifacts and report | All four controllers run identical scenario/seed inputs; failures retained; report includes requested metrics and uncertainty. | reproducibility checks and experiment reports |
| FS-016 | Calibration | Calibrate demand, composition, speeds, pedestrian behavior and road capacity against suitable Indian traffic observations. | Not started | FS-012, FS-015 | Calibration dataset/config and methodology | Parameters have traceable data sources and calibration procedure; uncalibrated values remain labelled exploratory. | calibration validation scripts |
| FS-017 | Algorithm ablation | Compare FlowSync terms and sensitivity of tunable weights using paired runs. | Not started | FS-015 | Ablation/sensitivity report | Ablations disable individual terms and report paired estimates with uncertainty. | experiment matrix tests |
| FS-018 | Frontend analytics | Show full experiment comparison with uncertainty and scenario-wise analysis, and expose real configuration inputs. | Partially complete | FS-005, FS-013 | Evidence-based analytics dashboard | Displayed values match API report outputs and uncertainty; no hardcoded performance claims. | frontend tests and API-to-view checks |

## P3 — optional enhancements

| ID | Module | Description | Status | Dependencies | Expected output | Acceptance criteria | Relevant tests |
|---|---|---|---|---|---|---|---|
| FS-019 | Operations/security | Add authentication, authorization, quotas, backup/restore and monitoring if deployment scope expands beyond trusted local research use. | Not started | FS-004, FS-006 | Deployment hardening | Access and operational controls meet an agreed deployment threat model. | auth, quota and recovery tests |
| FS-020 | Mapping/perception integration | Add calibrated camera mapping or optional map import and connect trusted observations to live simulation experiments. | Not started | FS-012, FS-016 | Optional input adapters | Input provenance and coordinate calibration are validated and retained end-to-end. | adapter integration tests |
| FS-021 | Interface polish | Add responsive browser QA, accessible control labels and useful empty/loading/error states. | Partially complete | FS-005 | QA'd dashboard | Keyboard/accessibility and desktop/tablet browser checks pass. | browser accessibility and responsive checks |

## Dependency-aware implementation roadmap

1. **Core correctness:** FS-001 → FS-002 → FS-003. Repair deterministic fallback semantics first; validate SUMO runtime and then safety across both engines.
2. **Integrated control:** FS-004 → FS-005 → FS-006. Verify API state/control contracts, build/browser-check the dashboard, then validate the container stack.
3. **Capabilities:** FS-007 through FS-014. Validate controllers and FlowSync terms before incident/emergency scenarios and paired experiments; check perception independently.
4. **Research:** FS-015 → FS-016/FS-017 → FS-018. Produce measurements only after runtime and metric validation; calibrate and ablate before interpreting efficacy.
5. **Deployment setup:** FS-022 → FS-023. Configure and validate platform build settings, then create the services from the pushed GitHub repository and verify cross-origin REST/WebSocket behavior.
6. **Optional hardening:** FS-019 through FS-021 according to deployment and usability needs.

## Audit findings

- **Implemented:** Python package, seeded five-signal SUMO network/route generation, TraCI adapter, deterministic fallback, four controller strategies, separate safety interlock in fallback, incidents/emergency requests, OpenCV ONNX adapter, FastAPI process worker, SQLite stores, experiment runner/report export, React dashboard, Docker files and project documentation.
- **Partial/unverified:** SUMO/TraCI runtime semantics and metrics; API/WebSocket runtime; frontend production build/browser behavior; Compose build; YOLO on actual supplied frames/model; confidence interval/scenario report adequacy under a full experiment matrix.
- **Critical defect found:** fallback normal-demand arrivals are appended twice because `_new_vehicle` already queues them.
- **Tests present:** one test module covering core fallback behavior, source generation, stores, optional API/TraCI and perception tracking. Non-API suite passes; SUMO/TraCI test skips because local TCP sockets are unavailable; API lifecycle hangs at TestClient startup under Python 3.14.4 / FastAPI 0.162.0 / Starlette 1.10.0 / HTTPX 0.28.1 and needs diagnosis.
- **Configuration:** Python optional extras for API, SUMO, perception and development; Vite/React/TypeScript frontend; Docker Compose. No conventional database server is used; state persists in SQLite. A standalone trivial FastAPI app using the installed TestClient stack also hangs at client startup, so the lifecycle-test stall reproduces outside this codebase.
- **Repository metadata:** `.git` exists in the workspace, but the `git` command reported “not a git repository”; change tracking through Git is unavailable in this checkout.
