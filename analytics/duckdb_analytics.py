"""
DuckDB analytics layer. Reads the *clean* (GE-validated) parquet file produced by
ge_suite/run_validation.py and computes the metrics the RFP explicitly asks for:

  - PMPM (per-member-per-month) cost trends
  - Utilization breakdown by claim category
  - High-cost cohort identification (top-N patients by total billed cost)
  - Monthly claim volume / category trend

Run standalone:
    python analytics/duckdb_analytics.py
"""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CLEAN_PARQUET = ROOT / "data" / "clean" / "claims_clean.parquet"
OUT_DIR = ROOT / "data" / "analytics"

DUCKDB_FILE = ROOT / "data" / "analytics" / "claims_analytics.duckdb"
con = duckdb.connect(str(DUCKDB_FILE))

def run():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DUCKDB_FILE = ROOT / "data" / "analytics" / "claims_analytics.duckdb"
    con = duckdb.connect(str(DUCKDB_FILE))
    con.execute(f"CREATE VIEW claims AS SELECT * FROM read_parquet('{CLEAN_PARQUET}')")

    # --- PMPM: total billed cost per member per month ---
    pmpm = con.execute("""
        SELECT
            strftime(service_date, '%Y-%m') AS month,
            COUNT(DISTINCT patient_id)      AS member_count,
            SUM(billed_amount)              AS total_billed,
            ROUND(SUM(billed_amount) / NULLIF(COUNT(DISTINCT patient_id), 0), 2) AS pmpm_cost
        FROM claims
        WHERE patient_id IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """).df()
    con.execute("CREATE OR REPLACE TABLE pmpm_trend AS SELECT * FROM pmpm")

    # --- Utilization breakdown by claim category ---
    category_util = con.execute("""
        SELECT
            claim_category,
            COUNT(*)                        AS claim_count,
            ROUND(SUM(billed_amount), 2)    AS total_billed,
            ROUND(AVG(billed_amount), 2)    AS avg_billed,
            ROUND(SUM(paid_amount), 2)      AS total_paid
        FROM claims
        GROUP BY 1
        ORDER BY total_billed DESC
    """).df()
    con.execute("CREATE OR REPLACE TABLE category_utilization AS SELECT * FROM category_util")

    # --- High-cost cohort: top 20 patients by total billed cost ---
    high_cost_cohort = con.execute("""
        SELECT
            patient_id,
            COUNT(*)                       AS claim_count,
            ROUND(SUM(billed_amount), 2)   AS total_billed,
            ROUND(AVG(billed_amount), 2)   AS avg_billed_per_claim
        FROM claims
        WHERE patient_id IS NOT NULL
        GROUP BY 1
        HAVING COUNT(*) > 1
        ORDER BY total_billed DESC
        LIMIT 20
    """).df()
    con.execute("CREATE OR REPLACE TABLE high_cost_cohort AS SELECT * FROM high_cost_cohort")

    # --- Monthly claim volume trend by category ---
    monthly_trend = con.execute("""
        SELECT
            strftime(service_date, '%Y-%m') AS month,
            claim_category,
            COUNT(*)                        AS claim_count,
            ROUND(SUM(billed_amount), 2)    AS total_billed
        FROM claims
        GROUP BY 1, 2
        ORDER BY 1, 2
    """).df()
    con.execute("CREATE OR REPLACE TABLE monthly_trend AS SELECT * FROM monthly_trend")

    pmpm.to_csv(OUT_DIR / "pmpm_trend.csv", index=False)
    category_util.to_csv(OUT_DIR / "category_utilization.csv", index=False)
    high_cost_cohort.to_csv(OUT_DIR / "high_cost_cohort.csv", index=False)
    monthly_trend.to_csv(OUT_DIR / "monthly_trend.csv", index=False)

    con.close()

    print("=== DuckDB analytics summary ===")
    print(f"Months of PMPM data: {len(pmpm)}")
    print(f"Categories analyzed: {len(category_util)}")
    print(f"High-cost cohort size: {len(high_cost_cohort)}")
    print()
    print("Category utilization:")
    print(category_util.to_string(index=False))
    print()
    print("Top 5 high-cost patients:")
    print(high_cost_cohort.head(5).to_string(index=False))
    print()
    print(f"Persisted DuckDB file: {DUCKDB_FILE}")

    return {
        "pmpm": pmpm,
        "category_util": category_util,
        "high_cost_cohort": high_cost_cohort,
        "monthly_trend": monthly_trend,
    }


if __name__ == "__main__":
    run()