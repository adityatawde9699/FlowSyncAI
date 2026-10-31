# Installation

## Python fallback, API and tests

Python 3.11+ is required. In a virtual environment:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,api]'
pytest
```

Run `flowsync --engine fallback --seconds 600`. Start the API on port 8001 with `uvicorn flowsync.api.app:app --host 127.0.0.1 --port 8001`; OpenAPI docs are at `http://127.0.0.1:8001/docs`.

The repository-root `.env.example` documents local backend settings. Copy it to `.env` and export its values in your shell before starting the API:

```sh
cp .env.example .env
set -a && . ./.env && set +a
```

## SUMO engine

Install Eclipse SUMO and SUMO tools using the operating system's package manager or the SUMO installation guide. Ensure `sumo` and `netconvert` are on `PATH`; install the matching TraCI bindings with `python -m pip install -e '.[sumo]'`. `flowsync --engine sumo` requires all components; `--engine auto` uses SUMO only when all are detected.

The system generates the network and demand files under `.flowsync/sumo-<seed>/`. Keep a run's generated directory with the SQLite experiment manifest when archiving research runs.

## Dashboard

Node 20+ is recommended. Copy `frontend/.env.example` to `frontend/.env.local`, then in `frontend/` run `npm install && npm run dev`. The example points at the local API on `http://127.0.0.1:8001`; change `VITE_API_URL` to use a different API URL. For Vercel, set `VITE_API_URL` in project environment settings as described in [DEPLOYMENT.md](DEPLOYMENT.md).

## Optional video perception

Install `python -m pip install -e '.[perception]'`, provide a compatible YOLO ONNX file and the exact label list, then create `YoloOpenCVDNN(weights, labels, output_format='yolov8')`. Use `yolov5` for YOLOv5 output tensors. Missing files or OpenCV fail explicitly; there is no bundled model or fabricated detector output.
