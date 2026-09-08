"""
Backend for the Psiddhi Claims Platform companion app.

Sits between the React frontend and:
  - narrative/ask.py + narrative/build_facts.py (AI Q&A over the analytics facts)
  - Airflow's REST API (trigger the DAG, poll run/task status)
  - the filesystem (data freshness — when analytics were last computed)

This file expects to live at <project_root>/webapp/backend/app.py, so it can
import the project's own `narrative` package via a relative path insert.

Run:
    cd webapp/backend
    pip install -r requirements.txt
    uvicorn app:app --reload --port 8000
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Make the project's own `narrative` package importable ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(Path(__file__).resolve().parent / ".env")

AIRFLOW_BASE_URL = os.environ.get("AIRFLOW_BASE_URL", "http://localhost:8080")
AIRFLOW_USERNAME = os.environ.get("AIRFLOW_USERNAME", "airflow")
AIRFLOW_PASSWORD = os.environ.get("AIRFLOW_PASSWORD", "airflow")
DAG_ID = os.environ.get("AIRFLOW_DAG_ID", "psiddhi_claims_pipeline")

DUCKDB_FILE = PROJECT_ROOT / "data" / "analytics" / "claims_analytics.duckdb"
LAST_RUN_FILE = PROJECT_ROOT / "narrative" / "output" / "run_log.json"

app = FastAPI(title="Psiddhi Claims Platform — Companion API")

# Local dev: Vite's default port. Add your deployed frontend origin here too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _airflow_auth_header() -> dict:
    token_url = f"{AIRFLOW_BASE_URL}/auth/token"
    response = httpx.post(
        token_url,
        json={"username": AIRFLOW_USERNAME, "password": AIRFLOW_PASSWORD},
        timeout=15,
    )
    response.raise_for_status()
    access_token = response.json()["access_token"]
    return {"Authorization": f"Bearer {access_token}"}


# ---------------------------------------------------------------- Ask AI ---
class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


@app.post("/api/ask", response_model=AskResponse)
def ask_ai(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question cannot be empty")
    try:
        from narrative.ask import ask
        from narrative.build_facts import build_facts

        facts = build_facts()
        facts_json_str = json.dumps(facts, indent=2)
        answer = ask(req.question, facts_json_str)
        return AskResponse(answer=answer)
    except FileNotFoundError as e:
        raise HTTPException(
            424,
            f"Analytics data not found ({e}). Run the pipeline at least once first.",
        )
    except Exception as e:
        raise HTTPException(502, f"AI request failed: {e}")


# --------------------------------------------------------- Trigger DAG ---
class TriggerResponse(BaseModel):
    dag_run_id: str
    state: str


@app.post("/api/trigger", response_model=TriggerResponse)
def trigger_dag(dry_run: bool = False):
    url = f"{AIRFLOW_BASE_URL}/api/v2/dags/{DAG_ID}/dagRuns"
    payload = {
        "logical_date": datetime.now(timezone.utc).isoformat(),
        "conf": {"dry_run": dry_run},
    }
    try:
        resp = httpx.post(url, json=payload, headers=_airflow_auth_header(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return TriggerResponse(dag_run_id=data["dag_run_id"], state=data["state"])
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"Airflow rejected the trigger: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(502, f"Could not reach Airflow at {AIRFLOW_BASE_URL}: {e}")


# ---------------------------------------------------------- DAG status ---
class TaskStatus(BaseModel):
    task_id: str
    state: str | None


class RunStatusResponse(BaseModel):
    dag_run_id: str
    state: str
    start_date: str | None
    end_date: str | None
    tasks: list[TaskStatus]


@app.get("/api/status/latest", response_model=RunStatusResponse)
def latest_status():
    runs_url = f"{AIRFLOW_BASE_URL}/api/v2/dags/{DAG_ID}/dagRuns"
    try:
        resp = httpx.get(
            runs_url,
            params={"order_by": "-start_date", "limit": 1},
            headers=_airflow_auth_header(),
            timeout=15,
        )
        resp.raise_for_status()
        runs = resp.json().get("dag_runs", [])
        if not runs:
            raise HTTPException(404, "No DAG runs found yet — trigger one first")
        run = runs[0]
        run_id = run["dag_run_id"]

        tasks_url = f"{AIRFLOW_BASE_URL}/api/v2/dags/{DAG_ID}/dagRuns/{run_id}/taskInstances"
        tasks_resp = httpx.get(tasks_url, headers=_airflow_auth_header(), timeout=15)
        tasks_resp.raise_for_status()
        task_instances = tasks_resp.json().get("task_instances", [])

        return RunStatusResponse(
            dag_run_id=run_id,
            state=run["state"],
            start_date=run.get("start_date"),
            end_date=run.get("end_date"),
            tasks=[TaskStatus(task_id=t["task_id"], state=t.get("state")) for t in task_instances],
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            e.response.status_code,
            f"Airflow returned an error for the latest status request: {e.response.text}",
        )
    except httpx.RequestError as e:
        raise HTTPException(502, f"Could not reach Airflow at {AIRFLOW_BASE_URL}: {e}")


# ------------------------------------------------------- Data freshness ---
class DataFreshnessResponse(BaseModel):
    duckdb_file_exists: bool
    duckdb_last_modified: str | None
    narrative_last_generated: str | None
    narrative_last_verdict: str | None
    note: str


@app.get("/api/data-freshness", response_model=DataFreshnessResponse)
def data_freshness():
    """
    Power BI Desktop has no API to ask 'have you refreshed this data' — this
    endpoint reports the last time the underlying analytics were computed,
    i.e. the data Power BI *would* show once you click Refresh. It cannot
    confirm Power BI has actually refreshed; that's a local desktop action.
    """
    duckdb_exists = DUCKDB_FILE.exists()
    duckdb_mtime = None
    if duckdb_exists:
        duckdb_mtime = datetime.fromtimestamp(
            DUCKDB_FILE.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    narrative_ts = None
    narrative_verdict = None
    if LAST_RUN_FILE.exists():
        with open(LAST_RUN_FILE) as f:
            log = json.load(f)
        narrative_ts = log.get("timestamp_utc")
        narrative_verdict = log.get("final_verdict")

    return DataFreshnessResponse(
        duckdb_file_exists=duckdb_exists,
        duckdb_last_modified=duckdb_mtime,
        narrative_last_generated=narrative_ts,
        narrative_last_verdict=narrative_verdict,
        note=(
            "This reflects when the pipeline last computed the analytics, "
            "not whether Power BI Desktop has clicked Refresh since then."
        ),
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}
