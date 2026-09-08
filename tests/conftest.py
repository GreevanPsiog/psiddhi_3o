"""
Shared fixtures for the test suite.

These tests assume they're run from the project root (pytest picks up
conftest.py automatically and adds this directory to sys.path), and that
the pipeline has been run at least once so data/clean, data/analytics, and
ml/artifacts exist. Tests that need those are marked and skipped gracefully
if the files aren't present yet — see test docstrings for which ones need
a prior pipeline run vs. which are self-contained.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RAW_CSV = ROOT / "data" / "synthetic_claims.csv"
CLEAN_PARQUET = ROOT / "data" / "clean" / "claims_clean.parquet"
ANALYTICS_DIR = ROOT / "data" / "analytics"
ML_METRICS = ROOT / "ml" / "artifacts" / "model_metrics.json"
NARRATIVE_OUTPUT = ROOT / "narrative" / "output"


@pytest.fixture(scope="session")
def raw_claims_df() -> pd.DataFrame:
    if not RAW_CSV.exists():
        pytest.skip(f"Raw dataset not found at {RAW_CSV}")
    return pd.read_csv(RAW_CSV)


@pytest.fixture(scope="session")
def clean_claims_df() -> pd.DataFrame:
    if not CLEAN_PARQUET.exists():
        pytest.skip(
            f"{CLEAN_PARQUET} not found — run `python ge_suite/run_validation.py` first"
        )
    return pd.read_parquet(CLEAN_PARQUET)


@pytest.fixture(scope="session")
def analytics_csvs() -> dict:
    required = ["pmpm_trend.csv", "category_utilization.csv", "high_cost_cohort.csv", "monthly_trend.csv"]
    missing = [f for f in required if not (ANALYTICS_DIR / f).exists()]
    if missing:
        pytest.skip(f"Missing analytics outputs {missing} — run `python analytics/duckdb_analytics.py` first")
    return {f: pd.read_csv(ANALYTICS_DIR / f) for f in required}


def pytest_addoption(parser):
    parser.addoption(
        "--run-integration", action="store_true", default=False,
        help="Run slow end-to-end pipeline integration tests (tests/test_integration.py)",
    )
    parser.addoption(
        "--run-live-llm", action="store_true", default=False,
        help="Run the one test that makes a real LLM API call (costs a real request)",
    )
