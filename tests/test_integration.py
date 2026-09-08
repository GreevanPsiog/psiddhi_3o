"""
End-to-end integration tests. These actually RUN the pipeline scripts (not
just inspect their prior output), so they're slower and are skipped by
default — opt in explicitly:

    pytest tests/test_integration.py -v --run-integration

The one live-LLM test additionally requires a configured provider and is
skipped unless you also pass --run-live-llm, since it costs a real API call.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

integration = pytest.mark.skipif(
    "not config.getoption('--run-integration')",
    reason="Use --run-integration to run full pipeline integration tests",
)
live_llm = pytest.mark.skipif(
    "not config.getoption('--run-live-llm')",
    reason="Use --run-live-llm to run the live LLM API call test",
)


def _run(relative_script: str, extra_args: list | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(ROOT / relative_script)] + (extra_args or [])
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)


@integration
class TestFullPipelineIntegration:
    """Runs each stage for real, in order, and checks the handoff between
    stages actually works — this is what would have caught bugs like the
    CatalogException from a non-idempotent CREATE VIEW, since it exercises
    a second consecutive run against the same persisted files."""

    def test_ge_validation_runs_and_produces_clean_parquet(self):
        result = _run("ge_suite/run_validation.py")
        assert result.returncode == 0, result.stderr
        assert (ROOT / "data" / "clean" / "claims_clean.parquet").exists()

    def test_duckdb_analytics_runs_after_validation(self):
        result = _run("analytics/duckdb_analytics.py")
        assert result.returncode == 0, result.stderr
        for f in ["pmpm_trend.csv", "category_utilization.csv", "high_cost_cohort.csv", "monthly_trend.csv"]:
            assert (ROOT / "data" / "analytics" / f).exists()

    def test_duckdb_analytics_is_rerunnable_against_persisted_file(self):
        """Runs it a SECOND time in a row — this is the regression test for
        the 'View with name claims already exists' bug."""
        first = _run("analytics/duckdb_analytics.py")
        second = _run("analytics/duckdb_analytics.py")
        assert first.returncode == 0, first.stderr
        assert second.returncode == 0, second.stderr

    def test_ml_training_runs_after_analytics(self):
        result = _run("ml/train_models.py")
        assert result.returncode == 0, result.stderr
        assert (ROOT / "ml" / "artifacts" / "model_metrics.json").exists()

    def test_dry_run_narrative_after_full_pipeline(self):
        # narrative must be invoked as a module for its relative imports
        cmd = [sys.executable, "-m", "narrative.generate_narrative", "--dry-run"]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        assert "Verdict: PASS" in result.stdout


@live_llm
class TestLiveLLMGeneration:
    """The one test in this whole suite that costs a real API call. Only
    runs with --run-live-llm, and requires narrative/.env to be configured
    with a working provider."""

    def test_configured_provider_produces_a_pass_verdict(self):
        from narrative import llm_client
        if not llm_client.is_configured():
            pytest.skip("No LLM_PROVIDER configured in narrative/.env")

        cmd = [sys.executable, "-m", "narrative.generate_narrative"]
        result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        assert "Verdict: PASS" in result.stdout
