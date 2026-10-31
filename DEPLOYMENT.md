# Deployment

## Vercel frontend + Render API

The supported split deployment serves the static Vite dashboard from Vercel and runs FastAPI with SUMO/TraCI on Render. The backend remains a simulation service; it does not connect to public traffic signals.

### Render API

1. Push this repository to GitHub and import `render.yaml` as a Render Blueprint.
2. The Blueprint builds the root `Dockerfile`, deploys the API in Singapore, checks `/health`, and stores SQLite under `/var/data` on a persistent disk. It selects Render's `1c-2g` paid plan for the API and disk-backed service because Free web services cannot attach persistent disks. The disk keeps experiment and simulation history across deploys.
3. During Blueprint setup, set `FLOWSYNC_CORS_ORIGINS` to the Vercel deployment origin(s), comma-separated and without paths. For example: `https://flowsync-ai.vercel.app`. Include the production origin; add preview origins only if browser previews need API access.
4. After the first deploy, confirm `https://<render-service>.onrender.com/health` returns `{"status":"ok"}`. Keep the exact API origin for the Vercel setting below.

The Docker image imports TraCI and sumolib directly from `/usr/share/sumo/tools`, installed with the apt SUMO package. This keeps the Python bindings aligned with the SUMO executable and avoids route-lookup protocol mismatches.

Render's service name may need to be changed if `flowsyncai-api` is already taken. If so, use the actual generated `onrender.com` hostname in both the health check and Vercel configuration. The local SQLite store is intended for this single-instance research deployment; do not scale the disk-backed service to multiple instances.

### Vercel dashboard

1. Import the same GitHub repository as a Vercel project.
2. Set **Root Directory** to `frontend`. Vercel reads `frontend/vercel.json`, builds with `npm run build`, publishes `dist`, and serves the Vite single-page app with an index fallback.
3. Add `VITE_API_URL` in Project Settings → Environment Variables for Preview and Production. Set it to the Render service's public HTTPS origin, for example `https://flowsyncai-api.onrender.com` (no trailing slash and no `/api`). Redeploy after changing this value.
4. Copy the assigned production Vercel origin into Render's `FLOWSYNC_CORS_ORIGINS` if it differs from the value entered during Blueprint setup. If using branch previews, list the specific preview origins needed.

`frontend/.env.production.example` shows the expected variable format. Do not commit a real service secret; `VITE_API_URL` is public configuration, not a credential. For local development the frontend continues to default to `http://127.0.0.1:8001`.

### Deployment limits

- Render's disk-backed Blueprint uses a paid service plan. Render Free services have ephemeral filesystems and cannot attach persistent disks, so the existing SQLite history would be lost on restarts/deploys there. See [Render persistent disks](https://render.com/docs/disks) and [Render Free service limits](https://render.com/docs/free).
- A persistent disk pins the API to one instance. This is suitable for a demo/research deployment, not a horizontally scaled production API.
- Render Free web services can sleep when idle; expect a cold start if choosing a no-disk Free configuration instead.
- The browser needs the Render API origin in `VITE_API_URL`, and the API needs the exact browser origin in `FLOWSYNC_CORS_ORIGINS` for REST and WebSocket access.

## Local container stack

`docker compose up --build` starts the API (with system SUMO) and the compiled React dashboard. Host ports are 8001 for the API and 5173 for the dashboard; the API container listens on port 8000 internally. SQLite persists in the `flowsync-data` named volume. Configure `FLOWSYNC_EXPERIMENT_DB` and `FLOWSYNC_LOG_LEVEL` through the API service environment.

The Python service runs one simulation worker process and a separate experiment process pool. Long experiments can consume CPU and memory; limit submitted seeds/scenarios or provision appropriately. SUMO network files are created under the service working tree; preserve generated configs alongside archived results when needed.

## Security and operational boundary

The API has no authentication and should remain on a trusted development/research network. Add authentication, authorization, request limits, job quotas, log retention, backup/restore and health monitoring before any shared deployment. Do not add public-signal credentials or connect the simulation to signal hardware. This application is a research simulator, not an operational traffic-control product.
