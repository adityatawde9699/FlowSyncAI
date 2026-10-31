# Limitations and validation status

## Implemented

- SUMO network and seeded route/person-file generator, TraCI controller adapter, and deterministic fallback engine.
- Four controller strategies, FlowSync downstream/context scoring, process-local communication failure fallback, incident insertion/removal and emergency request insertion.
- A tested fallback signal interlock for minimum green, yellow/all-red, all-red pedestrian walk and clearance; emergency priority never overrides it.
- REST/WebSocket control, process-isolated simulation worker, SQLite manifests/events/metrics/observation persistence, asynchronous paired experiments and report export.
- React/TypeScript/Tailwind client, OpenCV YOLO ONNX adapter and queue tracker requiring real model files.

## Simulated versus observed

All generated traffic, incidents and experiment values are simulations. The only route to video observations is the optional OpenCV adapter and the labelled observation API; it refuses missing model files and marks data source/confidence. No real traffic footage, trained weights or local traffic measurements are included. Simulated telemetry is labelled `simulation` and is not mixed with `video:*` sources.

## Not validated in this environment

SUMO 1.25, `netconvert`, TraCI, FastAPI/Pydantic and frontend packages are available on the user's project machine. The user reports 18 passing tests and a 600-second SUMO run. That run exposed misleading crossing/delay metrics and default vehicle teleporting; the code now counts internal-junction traversals, uses SUMO time loss for completed-trip delay, and disables teleporting. The corrected full SUMO metrics need to be rerun before research use. The React production build and Docker image build have not been reported as run.

## Research limits

The fallback is a simplified point-queue model. SUMO uses a generated five-signal grid and fixed origin-destination routes, not a calibrated OSM map. Arrival composition, per-class behavior, speed factors, incident rates and pedestrian demand are defaults, not Indian traffic estimates. There are two signal phase groups; the fallback does not model protected turn phases. SUMO's generated crossing phases are relied on and need runtime inspection. YOLO is an interface only and needs a compatible ONNX model and suitable camera calibration. PPO, OpenCV frame ingestion into the live controller, real-time camera feeds, PostgreSQL, authentication and production hardening are not implemented.

No experiment improvement target has been shown to be met. A short fallback smoke comparison is only a software-path check and is not evidence for the research question. There is no real-world deployment path and no public signal connection.
