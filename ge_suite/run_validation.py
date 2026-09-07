"""
Runs the claims expectation suite against a CSV and produces two outputs:
  - data/clean/claims_clean.parquet      (rows passing all gates)
  - data/quarantine/claims_quarantine.csv (rows failing one or more gates, with reasons)

This is the script the Airflow "validate" task calls. It's also runnable
standalone for local testing:

    python ge_suite/run_validation.py data/synthetic_claims.csv
"""

import sys
from pathlib import Path

import great_expectations as gx
import pandas as pd

from claims_expectations import build_suite

ROOT = Path(__file__).resolve().parent.parent


def run(csv_path: str):
    df = pd.read_csv(csv_path, parse_dates=["service_date"])

    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas("claims_pandas")
    data_asset = data_source.add_dataframe_asset(name="claims")
    batch_definition = data_asset.add_batch_definition_whole_dataframe("claims_batch")

    suite = build_suite(context)

    validation_results = {}
    bad_row_mask = pd.Series(False, index=df.index)
    reasons = pd.Series("", index=df.index)

    for expectation in suite.expectations:
        batch = batch_definition.get_batch(batch_parameters={"dataframe": df})
        result = batch.validate(expectation, result_format="COMPLETE")
        exp_type = expectation.expectation_type
        exp_column = getattr(expectation, "column", None) or getattr(expectation, "column_list", None)
        exp_key = f"{exp_type} ({exp_column})" if exp_column else exp_type
        validation_results[exp_key] = {
            "success": result.success,
            "unexpected_count": result.result.get("unexpected_count", 0),
        }
        unexpected_index_list = result.result.get("unexpected_index_list") or []
        for idx_info in unexpected_index_list:
            # unexpected_index_list entries are dicts keyed by column name(s) in newer GX,
            # or plain row indices in some expectation types -- handle both.
            if isinstance(idx_info, dict):
                idx = idx_info.get("__pk_index", None)
            else:
                idx = idx_info
            if idx is not None and idx in df.index:
                bad_row_mask.loc[idx] = True
                reasons.loc[idx] += f"{exp_key};"

    clean_dir = ROOT / "data" / "clean"
    quarantine_dir = ROOT / "data" / "quarantine"
    clean_dir.mkdir(parents=True, exist_ok=True)
    quarantine_dir.mkdir(parents=True, exist_ok=True)

    clean_df = df[~bad_row_mask].copy()
    quarantine_df = df[bad_row_mask].copy()
    quarantine_df["quarantine_reasons"] = reasons[bad_row_mask]

    clean_df.to_parquet(clean_dir / "claims_clean.parquet", index=False)
    quarantine_df.to_csv(quarantine_dir / "claims_quarantine.csv", index=False)

    print("=== Great Expectations validation summary ===")
    for exp_type, info in validation_results.items():
        status = "PASS" if info["success"] else "FAIL"
        print(f"[{status}] {exp_type} -- unexpected: {info['unexpected_count']}")
    print()
    print(f"Total rows:        {len(df)}")
    print(f"Clean rows:        {len(clean_df)}")
    print(f"Quarantined rows:  {len(quarantine_df)}")

    return validation_results, clean_df, quarantine_df


if __name__ == "__main__":
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data" / "synthetic_claims.csv")
    run(csv_arg)
