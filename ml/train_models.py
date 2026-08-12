"""
Trains the two models the RFP asks for:
  1. Cost prediction regression   (target: billed_amount)      -- report R^2
  2. Utilization clustering       (KMeans on per-patient features) -- report silhouette score

Both read from data/clean/claims_clean.parquet (GE-validated output).
Baseline-first per the proposal's risk mitigation: Linear Regression + fixed-K KMeans,
with a RandomForest comparison for the regression task.

Metrics/params/models are also logged to MLflow (local SQLite backend) so runs
can be browsed and compared via `mlflow ui --backend-store-uri sqlite:///mlruns.db`.

Run standalone:
    python ml/train_models.py
"""
import os
import json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("ml/.env")  # for DATABRICKS_HOST and DATABRICKS_TOKEN
print(os.environ.get("DATABRICKS_HOST"))
print(bool(os.environ.get("DATABRICKS_TOKEN")))

import joblib
import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, silhouette_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
CLEAN_PARQUET = ROOT / "data" / "clean" / "claims_clean.parquet"
MODEL_DIR = ROOT / "ml" / "artifacts"

# Local MLflow tracking store — a single SQLite file inside the project, so
# `mlflow ui --backend-store-uri sqlite:///mlruns.db` can browse it with no
# server setup. (Plain file-store backend is deprecated in newer MLflow.)
# mlflow.set_tracking_uri(f"sqlite:///{ROOT / 'mlruns.db'}")
# mlflow.set_experiment("psiddhi-claims-analytics")

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment("/Users/greevanpsiog@gmail.com/psiddhi-claims-analytics")


def load_clean():
    return pd.read_parquet(CLEAN_PARQUET)


def run_cost_prediction(df: pd.DataFrame):
    """Regression: predict billed_amount from claim features."""
    features = pd.get_dummies(
        df[["claim_category", "procedure_code"]], drop_first=True
    )
    features["service_month"] = pd.to_datetime(df["service_date"]).dt.month
    target = df["billed_amount"]

    X_train, X_test, y_train, y_test = train_test_split(
        features, target, test_size=0.2, random_state=42
    )

    results = {}

    with mlflow.start_run(run_name="cost_prediction"):
        mlflow.log_param("test_size", 0.2)
        mlflow.log_param("random_state", 42)
        mlflow.log_param("n_features", features.shape[1])

        lin = LinearRegression()
        lin.fit(X_train, y_train)
        results["linear_regression_r2"] = round(r2_score(y_test, lin.predict(X_test)), 4)
        mlflow.log_metric("linear_regression_r2", results["linear_regression_r2"])

        rf = RandomForestRegressor(n_estimators=150, max_depth=8, random_state=42)
        rf.fit(X_train, y_train)
        results["random_forest_r2"] = round(r2_score(y_test, rf.predict(X_test)), 4)
        mlflow.log_param("rf_n_estimators", 150)
        mlflow.log_param("rf_max_depth", 8)
        mlflow.log_metric("random_forest_r2", results["random_forest_r2"])

        best_model = rf if results["random_forest_r2"] >= results["linear_regression_r2"] else lin
        results["selected_model"] = "random_forest" if best_model is rf else "linear_regression"
        mlflow.log_param("selected_model", results["selected_model"])
        mlflow.log_metric(
            "selected_model_r2",
            max(results["linear_regression_r2"], results["random_forest_r2"]),
        )
        mlflow.sklearn.log_model(best_model, name="cost_prediction_model")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(best_model, MODEL_DIR / "cost_prediction_model.joblib")
    joblib.dump(list(features.columns), MODEL_DIR / "cost_prediction_features.joblib")

    return results


def run_utilization_clustering(df: pd.DataFrame, k: int = 4):
    """Clustering: group patients into utilization cohorts."""
    per_patient = (
        df[df["patient_id"].notnull()]
        .groupby("patient_id")
        .agg(
            claim_count=("claim_id", "count"),
            total_billed=("billed_amount", "sum"),
            avg_billed=("billed_amount", "mean"),
        )
        .reset_index()
    )
    # Need at least a few claims per patient for clustering to be meaningful.
    per_patient = per_patient[per_patient["claim_count"] >= 1]

    scaler = StandardScaler()
    X = scaler.fit_transform(per_patient[["claim_count", "total_billed", "avg_billed"]])

    with mlflow.start_run(run_name="utilization_clustering"):
        mlflow.log_param("k", k)
        mlflow.log_param("random_state", 42)
        mlflow.log_param("n_patients", len(per_patient))

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(X)

        sil_score = silhouette_score(X, labels) if len(set(labels)) > 1 else float("nan")
        mlflow.log_metric("silhouette_score", round(float(sil_score), 4))
        mlflow.sklearn.log_model(kmeans, name="utilization_clustering_model")

    per_patient["cluster"] = labels
    per_patient.to_csv(ROOT / "data" / "analytics" / "utilization_clusters.csv", index=False)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(kmeans, MODEL_DIR / "utilization_clustering_model.joblib")
    joblib.dump(scaler, MODEL_DIR / "utilization_scaler.joblib")

    return {"silhouette_score": round(float(sil_score), 4), "k": k, "n_patients": len(per_patient)}


def run():
    df = load_clean()
    cost_results = run_cost_prediction(df)
    cluster_results = run_utilization_clustering(df)

    summary = {"cost_prediction": cost_results, "utilization_clustering": cluster_results}

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(MODEL_DIR / "model_metrics.json", "w") as f:
        json.dump(summary, f, indent=2)

    print("=== ML training summary ===")
    print(json.dumps(summary, indent=2))
    print()
    print(f"Cost prediction R^2 target from proposal: > 0.6 -> "
          f"{'MET' if max(cost_results['linear_regression_r2'], cost_results['random_forest_r2']) > 0.6 else 'NOT MET'}")
    print(f"Silhouette score target from proposal: > 0.3 -> "
          f"{'MET' if cluster_results['silhouette_score'] > 0.3 else 'NOT MET'}")

    return summary


if __name__ == "__main__":
    run()