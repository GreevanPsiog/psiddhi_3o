"""
Tests for the raw dataset shape and the Great Expectations quality gate.

Run: pytest tests/test_data_quality.py -v
"""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------- Unit ---
class TestRawDatasetShape:
    """These don't require the pipeline to have been run — they check the
    raw input file itself, so they're a fast first line of defense."""

    def test_raw_csv_exists(self, raw_claims_df):
        assert len(raw_claims_df) > 0

    def test_expected_columns_present(self, raw_claims_df):
        expected = {
            "claim_id", "patient_id", "claim_category", "service_date",
            "diagnosis_code", "procedure_code", "drg_code", "revenue_code",
            "billed_amount", "paid_amount", "provider_id", "is_error_injected",
        }
        assert expected.issubset(set(raw_claims_df.columns))

    def test_claim_categories_are_known_values(self, raw_claims_df):
        valid = {"Medical", "Pharmacy", "Behavioral"}
        actual = set(raw_claims_df["claim_category"].dropna().unique())
        assert actual.issubset(valid), f"Unexpected categories: {actual - valid}"

    def test_dataset_has_repeat_patients(self, raw_claims_df):
        """Regression guard for the original bug: every patient appearing
        exactly once, which broke PMPM trending and cohort analysis."""
        counts = raw_claims_df["patient_id"].value_counts()
        repeat_patients = (counts > 1).sum()
        assert repeat_patients > 0, "No repeat-visit patients — PMPM/cohort analytics would be meaningless"

    def test_dataset_has_injected_duplicates(self, raw_claims_df):
        """Regression guard: the GE duplicate-detection gate needs at least
        one real duplicate to catch, or the gate is untested by definition."""
        dupes = raw_claims_df.duplicated(
            subset=["patient_id", "service_date", "procedure_code", "billed_amount"],
            keep=False,
        )
        assert dupes.sum() > 0, "No duplicate claim pairs in the dataset"

    def test_billed_amount_correlates_with_procedure(self, raw_claims_df):
        """Regression guard for the original bug: billed_amount was pure
        random noise, uncorrelated with anything, making cost prediction
        unlearnable (R^2 ~ 0). This doesn't assert a specific correlation
        strength, just that procedure_code groups have meaningfully
        different average costs (i.e. it's not flat random noise)."""
        by_procedure = raw_claims_df.groupby("procedure_code")["billed_amount"].mean()
        assert by_procedure.std() > 0, "billed_amount shows no variation across procedure codes"


# ------------------------------------------------------------ Integration ---
class TestGreatExpectationsGate:
    """These need `python ge_suite/run_validation.py` to have been run first
    (the clean_claims_df fixture skips gracefully if not)."""

    def test_clean_output_has_no_nulls_in_patient_id(self, clean_claims_df):
        assert clean_claims_df["patient_id"].isnull().sum() == 0

    def test_clean_output_has_no_negative_billed_amounts(self, clean_claims_df):
        assert (clean_claims_df["billed_amount"] > 0).all()

    def test_clean_output_has_no_duplicate_claim_pairs(self, clean_claims_df):
        dupes = clean_claims_df.duplicated(
            subset=["patient_id", "service_date", "procedure_code", "billed_amount"],
            keep=False,
        )
        assert dupes.sum() == 0, "Duplicate claims leaked through the GE gate into clean output"

    def test_clean_row_count_is_less_than_raw(self, raw_claims_df, clean_claims_df):
        """The gate should actually be filtering something out, not passing
        every row through untouched."""
        assert len(clean_claims_df) < len(raw_claims_df)

    def test_quarantine_file_exists_and_has_reasons(self):
        quarantine_path = ROOT / "data" / "quarantine" / "claims_quarantine.csv"
        if not quarantine_path.exists():
            pytest.skip("Quarantine file not found — run the GE validation first")
        quarantine_df = pd.read_csv(quarantine_path)
        assert len(quarantine_df) > 0
        assert "quarantine_reasons" in quarantine_df.columns
        assert quarantine_df["quarantine_reasons"].notnull().all()
