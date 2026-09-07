"""
Builds a single grounded facts.json from the DuckDB analytics outputs + ML metrics.

This is the anti-hallucination guardrail: the narrative LLM call is only ever shown
this file's contents (never the raw claims data), and the judge LLM call fact-checks
the generated narrative against this same file. If a number isn't in facts.json,
it isn't allowed to appear in the narrative.

Run standalone:
    python narrative/build_facts.py
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = ROOT / "data" / "analytics"
ML_METRICS = ROOT / "ml" / "artifacts" / "model_metrics.json"
OUT_DIR = ROOT / "narrative" / "output"


def _round_records(df: pd.DataFrame, n: int = 2) -> list:
    return json.loads(df.round(n).to_json(orient="records"))


def build_facts() -> dict:
    pmpm = pd.read_csv(ANALYTICS_DIR / "pmpm_trend.csv")
    category_util = pd.read_csv(ANALYTICS_DIR / "category_utilization.csv")
    high_cost_cohort = pd.read_csv(ANALYTICS_DIR / "high_cost_cohort.csv")
    monthly_trend = pd.read_csv(ANALYTICS_DIR / "monthly_trend.csv")
    utilization_clusters = pd.read_csv(ANALYTICS_DIR / "utilization_clusters.csv")

    with open(ML_METRICS) as f:
        ml_metrics = json.load(f)

    cluster_summary = (
        utilization_clusters.groupby("cluster")
        .agg(
            patient_count=("patient_id", "count"),
            avg_claim_count=("claim_count", "mean"),
            avg_total_billed=("total_billed", "mean"),
        )
        .round(2)
        .reset_index()
    )

    facts = {
        "period_covered": {
            "first_month": str(pmpm["month"].min()),
            "last_month": str(pmpm["month"].max()),
            "months_of_data": int(len(pmpm)),
        },
        "pmpm_trend": {
            "overall_avg_pmpm_cost": round(float(pmpm["pmpm_cost"].mean()), 2),
            "latest_month": str(pmpm.iloc[-1]["month"]),
            "latest_pmpm_cost": round(float(pmpm.iloc[-1]["pmpm_cost"]), 2),
            "min_pmpm_cost": round(float(pmpm["pmpm_cost"].min()), 2),
            "max_pmpm_cost": round(float(pmpm["pmpm_cost"].max()), 2),
            "monthly_series": _round_records(pmpm),
        },
        "category_utilization": _round_records(category_util),
        "high_cost_cohort": {
            "cohort_size": int(len(high_cost_cohort)),
            "top_5_patients": _round_records(high_cost_cohort.head(5)),
            "cohort_avg_total_billed": round(float(high_cost_cohort["total_billed"].mean()), 2),
        },
        "monthly_trend_summary": {
            "total_months": int(monthly_trend["month"].nunique()),
            "categories": sorted(monthly_trend["claim_category"].unique().tolist()),
        },
        "ml_models": {
            "cost_prediction": ml_metrics["cost_prediction"],
            "utilization_clustering": {
                **ml_metrics["utilization_clustering"],
                "cluster_summary": _round_records(cluster_summary),
            },
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "facts.json", "w") as f:
        json.dump(facts, f, indent=2)

    return facts


if __name__ == "__main__":
    facts = build_facts()
    print("=== Facts bundle built ===")
    print(f"Period: {facts['period_covered']['first_month']} to {facts['period_covered']['last_month']}")
    print(f"Categories: {[c['claim_category'] for c in facts['category_utilization']]}")
    print(f"High-cost cohort size: {facts['high_cost_cohort']['cohort_size']}")
    print(f"Saved to: narrative/output/facts.json")
