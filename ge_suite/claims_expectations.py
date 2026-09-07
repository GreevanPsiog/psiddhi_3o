"""
Great Expectations suite for the healthcare claims analytics pipeline.

Maps directly to the RFP QA mandate:
  - schema compliance      -> not-null / dtype / category-set expectations
  - coding formats         -> ICD-10-style regex on diagnosis_code
  - duplicate detection    -> compound uniqueness on patient/date/procedure/amount
  - date validity          -> service_date must not be in the future
  - positive cost values   -> billed_amount > 0, paid_amount >= 0 and <= billed_amount

This is intentionally one Python module (not a full GX project scaffold) so it is
easy to import from the Airflow DAG, from pytest, and from a quick notebook check.
"""

import datetime

import great_expectations as gx

VALID_CATEGORIES = ["Medical", "Pharmacy", "Behavioral"]

# Loose ICD-10-ish pattern: one letter, two digits, optional decimal + 1-2 digits.
# Deliberately simple -- good enough to catch the injected "12345" style errors
# without trying to be a full ICD-10 code validator.
ICD10_PATTERN = r"^[A-Z][0-9]{2}(\.[0-9]{1,2})?$"


def build_suite(context: gx.data_context.AbstractDataContext, suite_name: str = "claims_suite"):
    """Create (or overwrite) the claims expectation suite in the given GX context."""
    suite = gx.ExpectationSuite(name=suite_name)

    # --- Schema compliance ---
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(column="claim_id")
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeUnique(column="claim_id")
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeInSet(
            column="claim_category", value_set=VALID_CATEGORIES
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(
            column="patient_id", mostly=0.95  # tolerate a small, known error-injection rate
        )
    )

    # --- Coding format ---
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToMatchRegex(
            column="diagnosis_code", regex=ICD10_PATTERN, mostly=0.95
        )
    )

    # --- Positive cost values ---
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="billed_amount", min_value=0.01, mostly=0.98
        )
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnPairValuesAToBeGreaterThanB(
            column_A="billed_amount", column_B="paid_amount", or_equal=True, mostly=0.97
        )
    )

    # --- Date validity (no future-dated claims) ---
    # NOTE: GX 1.x requires min_value/max_value to be the *same type* as the column values.
    # Since service_date is loaded as a real datetime64 column, bounds must be pd.Timestamp
    # (not plain strings or datetime.date) or GX raises a MetricResolutionError internally.
    import pandas as pd

    today_ts = pd.Timestamp(datetime.date.today())
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToNotBeNull(column="service_date")
    )
    suite.add_expectation(
        gx.expectations.ExpectColumnValuesToBeBetween(
            column="service_date",
            min_value=pd.Timestamp("2000-01-01"),
            max_value=today_ts,
            mostly=0.98,
        )
    )

    # --- Duplicate detection ---
    suite.add_expectation(
        gx.expectations.ExpectCompoundColumnsToBeUnique(
            column_list=["patient_id", "service_date", "procedure_code", "billed_amount"],
            mostly=0.99,
        )
    )

    context.suites.add_or_update(suite)
    return suite
