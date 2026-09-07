# psiddhi_3o
S2-D-07 — Healthcare Claims Analytics Platform
# Psiddhi Claims Platform

Healthcare claims analytics platform built for IMPACT pSiddhi 3.0 (RFP S2-D-07,
Data Track, Semester 2). Ingests medical/pharmacy/behavioral claims, validates
them with quality gates, analyzes cost/utilization trends, runs ML models for
cost prediction and utilization clustering, generates a fact-checked AI
narrative, and orchestrates the whole thing with Airflow.

**Status as of Week 10:** core pipeline (data quality, analytics, ML, AI
narrative, orchestration) is built and verified end-to-end, with ML tracking
now hosted on Databricks. Power BI dashboard is mid-build (blocked on an
admin-rights step), tests and CI have not started — see
[Known Gaps](#known-gaps-vs-approved-proposal) below.

## Architecture

```
data/synthetic_claims.csv
        │
        ▼
  ge_suite/          Great Expectations quality gates
  (10 expectations,  (schema, ICD-10/CPT format, duplicates,
   5 gate types)       date validity, positive cost values)
        │
        ├──► data/clean/claims_clean.parquet
        └──► data/quarantine/claims_quarantine.csv
        │
        ▼
  analytics/          DuckDB queries
  duckdb_analytics.py (PMPM trend, category utilization,
        │              high-cost cohort, monthly trend)
        ▼
  data/analytics/*.csv
  data/analytics/claims_analytics.duckdb   (persisted DB file, for Power BI ODBC)
        │
        ▼
  ml/                 scikit-learn models, tracked in MLflow on Databricks
  train_models.py     (Linear Regression + Random Forest for cost
        │              prediction, KMeans for utilization clustering)
        ▼
  ml/artifacts/model_metrics.json
  Databricks Experiments → psiddhi-claims-analytics
        │
        ▼
  narrative/           AI narrative generation + LLM-as-judge fact-check
  generate_narrative.py (Groq / Gemini / NVIDIA NIM — provider-agnostic)
        │
        ▼
  narrative/output/narrative.md, judge_report.json

  dags/claims_pipeline_dag.py   Airflow DAG wiring all of the above:
                                 ingest → validate → analytics → train_ml → generate_narrative
```

## Quick start

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python ge_suite/run_validation.py
python analytics/duckdb_analytics.py
python ml/train_models.py
python -m narrative.generate_narrative --dry-run   # or without --dry-run once .env is set
```

See [`SETUP_AND_RUN_GUIDE.md`](./SETUP_AND_RUN_GUIDE.md) for a full step-by-step
walkthrough including expected output at each stage.

## Project structure

```
psiddhi-claims-platform/
├── requirements.txt
├── data/
│   ├── synthetic_claims.csv         # patched dataset, 3,116 rows (see Dataset History)
│   └── analytics/
│       └── claims_analytics.duckdb  # persisted DuckDB file, source for Power BI ODBC
├── ge_suite/
│   ├── claims_expectations.py       # GX 1.18 expectation suite
│   └── run_validation.py
├── analytics/
│   └── duckdb_analytics.py          # now writes to a persisted .duckdb file, not :memory:
├── ml/
│   ├── train_models.py              # logs to MLflow, hosted on Databricks
│   └── .env                          # DATABRICKS_HOST / DATABRICKS_TOKEN (not committed)
├── narrative/
│   ├── build_facts.py               # only source of truth the LLM ever sees
│   ├── llm_client.py                # Groq / Gemini / NVIDIA NIM, auto-loads .env
│   ├── prompts.py
│   ├── generate_narrative.py
│   ├── .env.example                  # copy to .env, fill in your key
│   └── README.md                     # narrative module details
├── dags/
│   └── claims_pipeline_dag.py       # Airflow DAG
├── tests/                            # not yet started
├── docs/                             # not yet started
└── .github/workflows/                # not yet started
```

## Dataset

`data/synthetic_claims.csv` started as a purely random synthetic dataset and
was patched twice: once to add realistic repeat-patient/duplicate structure
(needed for PMPM trending, cohort analysis, and the GE duplicate-detection
gate to have something to catch), and once to make `billed_amount` actually
correlated with claim features (the original random costs made cost
prediction unlearnable, R² ≈ 0). Current state: 3,116 rows, 317 patients with
repeat visits, 18 injected duplicate pairs, and several other injected error
types for QA gate testing.

## MLflow (now on Databricks)

Model params/metrics/artifacts are tracked on **Databricks Free Edition**,
matching the approved proposal (this replaces the earlier local SQLite
backend used during initial development):

```bash
python ml/train_models.py
```
`ml/train_models.py` calls `mlflow.set_tracking_uri("databricks")` and logs to
the `/Users/greevanpsiog@gmail.com/psiddhi-claims-analytics` experiment.
Requires `ml/.env` with `DATABRICKS_HOST` and `DATABRICKS_TOKEN` — see
`ml/.env.example`. View runs in the Databricks workspace under
**Experiments → psiddhi-claims-analytics**.

## DuckDB persistence (for Power BI ODBC)

`analytics/duckdb_analytics.py` now connects to a persisted file
(`data/analytics/claims_analytics.duckdb`) instead of an in-memory database,
and materializes each result as a real table (`pmpm_trend`,
`category_utilization`, `high_cost_cohort`, `monthly_trend`) inside it. This
is what the DuckDB ODBC driver connects to from Power BI, matching the
approved proposal's "connect to DuckDB via ODBC" requirement.

## Power BI

**Status: blocked, pending Windows admin rights.** The DuckDB ODBC driver
(`duckdb_odbc.dll` + `odbc_install.exe` from the
[duckdb-odbc releases](https://github.com/duckdb/duckdb-odbc/releases)) must
be registered system-wide in Windows' ODBC driver registry, which requires
admin permission to install — this is a Windows-level restriction on all
ODBC drivers, not specific to DuckDB. Once installed: create a System DSN
pointing at `data/analytics/claims_analytics.duckdb`, then in Power BI
Desktop use **Get Data → ODBC** and select that DSN. Two required dashboard
views (Cost & Utilization Overview; High-Cost Cohort & ML Clustering) are
planned once the connection is unblocked.

## Airflow

DAG id: `psiddhi_claims_pipeline`. Runs on WSL2/Linux (Apache Airflow does not
support native Windows). See `SETUP_AND_RUN_GUIDE.md` for WSL2 setup. Trigger
with `{"dry_run": true}` config to exercise the full chain without an LLM call.
Verified running end-to-end: all 5 tasks (ingest, validate_ge,
duckdb_analytics, train_ml, generate_narrative) complete successfully.

## Known gaps vs. approved proposal

This project is built incrementally and evidence-first — the sections below
are disclosed honestly rather than glossed over, since the mid-term
submission is evaluated against exactly this kind of gap:

- **Docker** — named in the approved plan for local Airflow setup; Airflow
  currently runs via a WSL2 venv, not a Docker container. Planned as a
  follow-up (Weeks 11-13); would also permanently resolve the native-Windows
  incompatibility.
- **Databricks** — resolved. MLflow tracking now runs on Databricks Free
  Edition instead of the local SQLite backend used earlier in development.
- **Groq (ICD-10/CPT classification)** — not built. Claim categories
  currently come from the synthetic data generator, not an LLM
  classification step.
- **Gemini (narrative generation)** — code path exists in `llm_client.py`
  but has not been live-tested. Narrative generation is currently verified
  working via **NVIDIA NIM** only.
- **Power BI via ODBC** — in progress, no longer a silent substitution.
  DuckDB now persists to a real `.duckdb` file and the ODBC driver
  install is underway, blocked on Windows admin rights (see Power BI
  section above). CSV-based views are a fallback if the ODBC path isn't
  unblocked in time.
- **Pytest / GitHub Actions CI** — not yet started.
- **Documentation package** — not yet started.

See the mid-term submission document (Section 8: Deviations) for the full
disclosure with reasoning for each.

## License / usage

Internal coursework project for IMPACT pSiddhi 3.0. Not intended for
production use with real claims data — the dataset is entirely synthetic.