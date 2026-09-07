"""
Tests for ML training output — verifies the proposal's own accuracy targets
are actually met, not just that training ran without crashing.

Run: pytest tests/test_ml_models.py -v
Needs: python ml/train_models.py to have been run first.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ML_METRICS = ROOT / "ml" / "artifacts" / "model_metrics.json"


@pytest.fixture(scope="module")
def ml_metrics() -> dict:
    if not ML_METRICS.exists():
        pytest.skip(f"{ML_METRICS} not found — run `python ml/train_models.py` first")
    with open(ML_METRICS) as f:
        return json.load(f)


class TestCostPredictionTargets:
    def test_r2_meets_proposal_target(self, ml_metrics):
        """Proposal target: R^2 > 0.6"""
        r2 = max(
            ml_metrics["cost_prediction"]["linear_regression_r2"],
            ml_metrics["cost_prediction"]["random_forest_r2"],
        )
        assert r2 > 0.6, f"Cost prediction R^2 {r2} does not meet the > 0.6 target"

    def test_selected_model_is_one_of_the_two_trained(self, ml_metrics):
        assert ml_metrics["cost_prediction"]["selected_model"] in {
            "linear_regression", "random_forest",
        }

    def test_selected_model_is_actually_the_better_one(self, ml_metrics):
        cp = ml_metrics["cost_prediction"]
        best = max(cp["linear_regression_r2"], cp["random_forest_r2"])
        selected_r2 = (
            cp["linear_regression_r2"] if cp["selected_model"] == "linear_regression"
            else cp["random_forest_r2"]
        )
        assert selected_r2 == best, "Selected model is not the one with the higher R^2"


class TestUtilizationClusteringTargets:
    def test_silhouette_meets_proposal_target(self, ml_metrics):
        """Proposal target: silhouette score > 0.3"""
        score = ml_metrics["utilization_clustering"]["silhouette_score"]
        assert score > 0.3, f"Silhouette score {score} does not meet the > 0.3 target"

    def test_k_equals_four(self, ml_metrics):
        assert ml_metrics["utilization_clustering"]["k"] == 4

    def test_reasonable_number_of_patients_clustered(self, ml_metrics):
        """Sanity check against silent data loss — should be clustering
        roughly the patient population, not a tiny fraction of it."""
        n = ml_metrics["utilization_clustering"]["n_patients"]
        assert n > 100, f"Only {n} patients clustered — suspiciously low"
