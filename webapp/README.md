# Psiddhi Companion App

A small React + FastAPI app to sit alongside the main pipeline: ask AI
questions about the claims analytics, trigger the Airflow DAG, watch its
task-by-task status, and check when the analytics data was last computed.

## Where this goes

Extract this `webapp/` folder into your project root, so it sits next to
`narrative/`, `dags/`, `analytics/`, etc.:

```
psiddhi-claims-platform/
├── narrative/
├── dags/
├── analytics/
├── ...
└── webapp/            <- this folder
    ├── backend/
    └── frontend/
```

The backend imports `narrative.ask` and `narrative.build_facts` directly
from the main project, so it must stay at this relative location
(`<project_root>/webapp/backend/app.py`) to find them.

## What this app can do

- **Ask AI** — question answered strictly from the latest `facts.json`
  built from your DuckDB analytics + ML metrics (reuses `narrative/ask.py`).
- **Trigger the pipeline** — calls Airflow's REST API to start a DAG run,
  with a dry-run toggle (no LLM call) or a full run.
- **Live status** — polls Airflow every 4 seconds while a run is active,
  showing each of the 5 tasks' state (queued/running/success/failed).
- **Data freshness** — shows when `claims_analytics.duckdb` was last
  written and when the narrative was last generated (with its judge
  verdict). This is the closest available proxy for "is Power BI showing
  current data" — see the note below on why it can't be more direct.

## What this app cannot do

- **Confirm Power BI has actually refreshed.** Power BI Desktop has no API
  to query "last refreshed at." The Data Freshness panel tells you when the
  *source data* was last computed — you'd still need to click Refresh in
  Power BI Desktop yourself to pick up a newer run.
- **Run without the rest of the project already working.** The Ask AI
  panel needs `data/analytics/*.csv` to already exist (run the pipeline at
  least once); the Trigger/Status panels need Airflow actually running
  (Docker Compose stack up, or the WSL2 setup).
- **Authenticate against a production-hardened Airflow.** This uses basic
  auth with the default `airflow`/`airflow` credentials from the official
  docker-compose.yaml. Fine for local dev; would need real auth (API
  tokens, a reverse proxy) before ever being exposed beyond localhost.

## Setup — backend

```bash
cd webapp/backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env if your Airflow isn't at the defaults (localhost:8080, airflow/airflow)

uvicorn app:app --reload --port 8000
```

Leave this running. Confirm it's up: open `http://localhost:8000/api/health`
in a browser — should return `{"status":"ok"}`.

## Setup — frontend

In a second terminal:

```bash
cd webapp/frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Notes

- The frontend is hardcoded to call the backend at `http://localhost:8000`
  (see `src/api.ts`) — change `API_BASE` there if you run the backend
  elsewhere.
- CORS on the backend is currently locked to `localhost:5173` — update the
  `allow_origins` list in `app.py` if you serve the frontend from a
  different port/host.
- The Ask AI endpoint calls whichever LLM provider is configured in your
  main project's `narrative/.env` (Groq/Gemini/NVIDIA) — same credentials,
  no separate setup needed here.
