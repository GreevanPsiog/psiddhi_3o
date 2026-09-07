"""
Tests for the DuckDB analytics layer's output correctness.

Run: pytest tests/test_analytics.py -v
Needs: python analytics/duckdb_analytics.py to have been run first.
"""

from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parent.parent
DUCKDB_FILE = ROOT / "data" / "analytics" / "claims_analytics.duckdb"


class TestAnalyticsCSVs:
    def test_pmpm_trend_columns(self, analytics_csvs):
        df = analytics_csvs["pmpm_trend.csv"]
        assert {"month", "member_count", "total_billed", "pmpm_cost"}.issubset(df.columns)

    def test_pmpm_trend_has_no_negative_costs(self, analytics_csvs):
        df = analytics_csvs["pmpm_trend.csv"]
        assert (df["pmpm_cost"] >= 0).all()

    def test_category_utilization_covers_all_three_categories(self, analytics_csvs):
        df = analytics_csvs["category_utilization.csv"]
        assert set(df["claim_category"]) == {"Medical", "Pharmacy", "Behavioral"}

    def test_high_cost_cohort_is_exactly_20_patients(self, analytics_csvs):
        df = analytics_csvs["high_cost_cohort.csv"]
        assert len(df) == 20

    def test_high_cost_cohort_is_sorted_descending(self, analytics_csvs):
        df = analytics_csvs["high_cost_cohort.csv"]
        assert list(df["total_billed"]) == sorted(df["total_billed"], reverse=True)

    def test_high_cost_cohort_patients_all_have_multiple_claims(self, analytics_csvs):
        """The query filters HAVING COUNT(*) > 1 — verify that held."""
        df = analytics_csvs["high_cost_cohort.csv"]
        assert (df["claim_count"] > 1).all()


class TestPersistedDuckDBFile:
    """Regression guard for the Power BI ODBC integration: the file must be
    persisted (not :memory:) and must contain real, queryable tables."""

    def test_duckdb_file_exists(self):
        if not DUCKDB_FILE.exists():
            pytest.skip(f"{DUCKDB_FILE} not found — run analytics/duckdb_analytics.py first")
        assert DUCKDB_FILE.stat().st_size > 0

    def test_duckdb_file_contains_expected_tables(self):
        if not DUCKDB_FILE.exists():
            pytest.skip(f"{DUCKDB_FILE} not found")
        con = duckdb.connect(str(DUCKDB_FILE), read_only=True)
        try:
            tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        finally:
            con.close()
        expected = {"pmpm_trend", "category_utilization", "high_cost_cohort", "monthly_trend"}
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_duckdb_file_is_rerunnable(self):
        """Regression guard for the CatalogException bug: CREATE VIEW claims
        must use OR REPLACE, or a second run against the same persisted
        file fails. This test only checks the file opens read-only cleanly
        after having been run at least twice in this environment — it does
        not itself rerun the pipeline."""
        if not DUCKDB_FILE.exists():
            pytest.skip(f"{DUCKDB_FILE} not found")
        con = duckdb.connect(str(DUCKDB_FILE), read_only=True)
        try:
            result = con.execute("SELECT COUNT(*) FROM claims").fetchone()
            assert result[0] > 0
        finally:
            con.close()
