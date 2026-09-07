"""
Airflow DAG for the Psiddhi healthcare claims analytics pipeline.

Wires together the already-tested standalone scripts, in the order the RFP
specifies:
    ingest -> validate (Great Expectations) -> analytics (DuckDB) ->
    train_ml (scikit-learn) -> generate_narrative (LLM + judge)
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from airflow import DAG
from airflow.operators.python import PythonOperator

import os
PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT_IN_CONTAINER", "/opt/airflow/project"))

def _run_script(relative_path: str, extra_args: list[str] | None = None) -> None:
    cmd = [sys.executable, str(PROJECT_ROOT / relative_path)] + (extra_args or [])
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"{relative_path} failed with exit code {result.returncode}")


def _run_module(module_name: str, extra_args: list[str] | None = None) -> None:
    cmd = [sys.executable, "-m", module_name] + (extra_args or [])
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"{module_name} failed with exit code {result.returncode}")


def ingest_task(**context):
    raw_csv = PROJECT_ROOT / "data" / "synthetic_claims.csv"
    if not raw_csv.exists():
        raise FileNotFoundError(f"Expected raw claims file not found: {raw_csv}")
    line_count = sum(1 for _ in open(raw_csv, encoding="utf-8"))
    if line_count < 2:
        raise ValueError(f"{raw_csv} looks empty ({line_count} lines)")
    print(f"Ingest check passed: {raw_csv} ({line_count - 1} data rows)")


def validate_task(**context):
    _run_script("ge_suite/run_validation.py")
    clean_parquet = PROJECT_ROOT / "data" / "clean" / "claims_clean.parquet"
    if not clean_parquet.exists():
        raise FileNotFoundError(f"Expected {clean_parquet} was not created — GE gate did not run to completion")


def analytics_task(**context):
    _run_script("analytics/duckdb_analytics.py")
    required = ["pmpm_trend.csv", "category_utilization.csv", "high_cost_cohort.csv", "monthly_trend.csv"]
    missing = [f for f in required if not (PROJECT_ROOT / "data" / "analytics" / f).exists()]
    if missing:
        raise FileNotFoundError(f"DuckDB analytics did not produce: {missing}")


def train_ml_task(**context):
    _run_script("ml/train_models.py")
    metrics_path = PROJECT_ROOT / "ml" / "artifacts" / "model_metrics.json"
    if not metrics_path.exists():
        raise FileNotFoundError(f"Expected {metrics_path} was not created")

    with open(metrics_path) as f:
        metrics = json.load(f)

    r2 = max(
        metrics["cost_prediction"]["linear_regression_r2"],
        metrics["cost_prediction"]["random_forest_r2"],
    )
    silhouette = metrics["utilization_clustering"]["silhouette_score"]
    if r2 <= 0.6:
        raise ValueError(f"Cost prediction R^2 {r2} did not clear the proposal target of > 0.6")
    if silhouette <= 0.3:
        raise ValueError(f"Silhouette score {silhouette} did not clear the proposal target of > 0.3")
    print(f"ML targets met: R^2={r2}, silhouette={silhouette}")


def generate_narrative_task(**context):
    dry_run = (context.get("dag_run").conf or {}).get("dry_run", False) if context.get("dag_run") else False
    args = ["--dry-run"] if dry_run else []
    _run_module("narrative.generate_narrative", args)

    run_log_path = PROJECT_ROOT / "narrative" / "output" / "run_log.json"
    with open(run_log_path) as f:
        run_log = json.load(f)

    if run_log.get("final_verdict") != "PASS":
        raise ValueError(
            f"Narrative failed fact-checking (verdict={run_log.get('final_verdict')}) "
            f"after {run_log.get('attempts')} attempt(s) — see narrative/output/judge_report.json"
        )
    print(f"Narrative fact-check PASSED on attempt {run_log.get('attempts')}")


default_args = {
    "owner": "dhasagreevan",
    "retries": 1,
}

with DAG(
    dag_id="psiddhi_claims_pipeline",
    description="Healthcare claims analytics: ingest -> validate -> analytics -> train_ml -> generate_narrative",
    default_args=default_args,
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["psiddhi", "healthcare-claims"],
) as dag:

    ingest = PythonOperator(task_id="ingest", python_callable=ingest_task)
    validate = PythonOperator(task_id="validate_ge", python_callable=validate_task)
    analytics = PythonOperator(task_id="duckdb_analytics", python_callable=analytics_task)
    train_ml = PythonOperator(task_id="train_ml", python_callable=train_ml_task)
    generate_narrative = PythonOperator(
        task_id="generate_narrative",
        python_callable=generate_narrative_task,
    )

    ingest >> validate >> analytics >> train_ml >> generate_narrative
