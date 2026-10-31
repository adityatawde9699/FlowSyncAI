# Deployment

## Vercel frontend + Render API

The supported split deployment serves the static Vite dashboard from Vercel and runs FastAPI with SUMO/TraCI on Render. The backend remains a simulation service; it does not connect to public traffic signals.

### Render API

1. Push this repository to GitHub and import `render.yaml` as a Render Blueprint.
2. The Blueprint builds the root `Dockerfile`, deploys the API in Singapore, checks `/health`, and prompts for `DATABASE_URL`. The API remains on Render's `1c-2g` plan. A disk mounted at `/var/data` is retained as legacy SQLite data; new data is written to Neon once its connection string is configured.
3. During Blueprint setup, set `FLOWSYNC_CORS_ORIGINS` to the Vercel deployment origin(s), comma-separated and without paths. For example: `https://flowsync-ai.vercel.app`. Include the production origin; add preview origins only if browser previews need API access.
4. After the first deploy, confirm `https://<render-service>.onrender.com/health` returns `{"status":"ok"}`. Keep the exact API origin for the Vercel setting below.

The Docker image imports TraCI and sumolib directly from `/usr/share/sumo/tools`, installed with the apt SUMO package. This keeps the Python bindings aligned with the SUMO executable and avoids route-lookup protocol mismatches.

If the API service name changes, use its generated `onrender.com` hostname in Vercel's `VITE_API_URL` and in `FLOWSYNC_CORS_ORIGINS`. In the Neon Console, open your project, choose **Connect**, select the database and role, then copy the connection string. Prefer Neon's pooled connection string for this hosted API, and keep its SSL mode enabled (`sslmode=require`). Add the full URI as `DATABASE_URL` under the Render API service's Environment settings; keep it secret and redeploy. `DATABASE_URL` takes precedence over `FLOWSYNC_EXPERIMENT_DB`; local runs without it use SQLite. The PostgreSQL major version is configured in Neon, not in Render's Blueprint. Existing SQLite history is not copied automatically; keep the legacy disk until its data is no longer needed or has been migrated.

### Vercel dashboard

1. Import the same GitHub repository as a Vercel project.
2. Set **Root Directory** to `frontend`. Vercel reads `frontend/vercel.json`, builds with `npm run build`, publishes `dist`, and serves the Vite single-page app with an index fallback.
3. Add `VITE_API_URL` in Project Settings → Environment Variables for Preview and Production. Set it to the Render service's public HTTPS origin, for example `https://flowsyncai-api.onrender.com` (no trailing slash and no `/api`). Redeploy after changing this value.
4. Copy the assigned production Vercel origin into Render's `FLOWSYNC_CORS_ORIGINS` if it differs from the value entered during Blueprint setup. If using branch previews, list the specific preview origins needed.

`frontend/.env.production.example` shows the expected variable format. Do not commit a real service secret; `VITE_API_URL` is public configuration, not a credential. For local development the frontend continues to default to `http://127.0.0.1:8001`.

### Deployment limits

- Neon manages the database separately from Render. Confirm the Neon project's PostgreSQL version and compute limits in the Neon Console.
- A persistent disk pins the API to one instance. This is suitable for a demo/research deployment, not a horizontally scaled production API.
- Render Free web services can sleep when idle; expect a cold start if choosing a no-disk Free configuration instead.
- The browser needs the Render API origin in `VITE_API_URL`, and the API needs the exact browser origin in `FLOWSYNC_CORS_ORIGINS` for REST and WebSocket access.

## Local container stack

`docker compose up --build` starts the API (with system SUMO) and the compiled React dashboard. Host ports are 8001 for the API and 5173 for the dashboard; the API container listens on port 8000 internally. Without `DATABASE_URL`, SQLite persists in the `flowsync-data` named volume. To use PostgreSQL, provide a PostgreSQL connection string as `DATABASE_URL` to the API service. Configure `FLOWSYNC_EXPERIMENT_DB` and `FLOWSYNC_LOG_LEVEL` through the API service environment.

The Python service runs one simulation worker process and a separate experiment process pool. Long experiments can consume CPU and memory; limit submitted seeds/scenarios or provision appropriately. SUMO network files are created under the service working tree; preserve generated configs alongside archived results when needed.

## Security and operational boundary

The API has no authentication and should remain on a trusted development/research network. Add authentication, authorization, request limits, job quotas, log retention, backup/restore and health monitoring before any shared deployment. Do not add public-signal credentials or connect the simulation to signal hardware. This application is a research simulator, not an operational traffic-control product.
