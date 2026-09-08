# Psiddhi Claims Platform

Healthcare claims analytics platform built for IMPACT pSiddhi 3.0 (RFP S2-D-07,
Data Track, Semester 2). Ingests medical/pharmacy/behavioral claims, validates
them with quality gates, analyzes cost/utilization trends, runs ML models for
cost prediction and utilization clustering, generates a fact-checked AI
narrative, and orchestrates the whole thing with Airflow.

**Status as of Final Term:** core pipeline (data quality, analytics, ML, AI
narrative, orchestration) is built and verified end-to-end, with ML tracking
hosted on Databricks. The complete Power BI dashboard (all 3 tabs) is built
and connected via the MotherDuck DuckDB connector. Automated tests and CI are
in place and passing. Docker deployment is live on a GCP Compute Engine VM.
See [Known Gaps](#known-gaps-vs-approved-proposal) below for the few
remaining items.

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

## Docker deployment on Google Cloud

The complete platform is deployed as a Docker Compose stack on a private
Google Compute Engine VM (`instance-psiddhi-healthcare-analytics`). This is
preferred over putting the whole stack in a single Cloud Run container because
Airflow, PostgreSQL, Redis, the FastAPI backend, and the frontend are separate
services.

The production Compose overlay is
[`docker-compose.prod.yaml`](./docker-compose.prod.yaml). It builds the
Airflow image from `Dockerfile`, the FastAPI backend from
`webapp/backend/Dockerfile`, and serves the React frontend through Nginx from
`webapp/frontend/Dockerfile`.

### Compute Engine setup

Create a Linux VM attached to your VPC. For the full stack, use at least
2 vCPUs, 8 GB RAM, and a 30 GB persistent disk. A 4 vCPU/16 GB VM is
recommended for ML training and Airflow. Prefer a VM without a public IP and
use Identity-Aware Proxy (IAP), VPN, or an internal load balancer.

Install Docker and clone the repository on the VM:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git openssl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

git clone <repository-url> psiddhi-claims-platform
cd psiddhi-claims-platform
```

Reconnect after adding the user to the Docker group.

### Configure secrets

Create a VM-local `.env` file and do not commit it:

```bash
openssl rand -base64 32
nano .env
chmod 600 .env
```

At minimum, configure:

```dotenv
AIRFLOW_UID=50000
_AIRFLOW_WWW_USER_USERNAME=<strong-admin-username>
_AIRFLOW_WWW_USER_PASSWORD=<strong-admin-password>
FERNET_KEY=<generated-fernet-key>
AIRFLOW__API_AUTH__JWT_SECRET=<random-secret>
CORS_ALLOWED_ORIGINS=
```

Add the Databricks and LLM provider variables required by the pipeline.
`CORS_ALLOWED_ORIGINS` may remain empty because the frontend Nginx container
proxies `/api` requests to the backend over the internal Compose network.

### Start the stack

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml config
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up airflow-init
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml up -d
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml ps
```

Check service logs:

```bash
docker compose -f docker-compose.yaml -f docker-compose.prod.yaml \
  logs -f airflow-apiserver backend frontend
```

The frontend is bound to the VM's loopback interface on port `8081`, the
backend on `8000`, and Airflow on `8080`. Do not expose these ports publicly.
From an authorized workstation using IAP, create a tunnel:

```bash
gcloud compute ssh <vm-name> --zone <zone> --tunnel-through-iap \
  -- -L 8081:127.0.0.1:8081
```

Then open `http://localhost:8081`. To access Airflow, use another tunnel with
`-L 8080:127.0.0.1:8080`.

For the complete firewall, persistence, backup, update, and cost guidance, see
[`GCP_VPC_DEPLOYMENT.md`](./GCP_VPC_DEPLOYMENT.md).

## Project structure

```
psiddhi-claims-platform/
├── Dockerfile
├── docker-compose.yaml
├── docker-compose.prod.yaml
├── GCP_VPC_DEPLOYMENT.md
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
├── tests/
│   ├── conftest.py                   # shared fixtures, skip logic
│   ├── test_data_quality.py          # raw dataset + GE gate integration
│   ├── test_analytics.py             # DuckDB CSV + persisted .duckdb checks
│   ├── test_ml_models.py             # R^2 > 0.6, silhouette > 0.3
│   ├── test_narrative.py             # build_facts, dry-run
│   ├── test_dag_integrity.py         # DAG structure (5 tasks, no cycles)
│   ├── test_integration.py           # full pipeline rerun (opt-in)
│   └── README.md                     # test docs, CI instructions
├── pytest.ini
├── .github/workflows/tests.yml      # CI on push/PR
├── docs/                             # technical documentation
└── README.md
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

## DuckDB persistence (for Power BI)

`analytics/duckdb_analytics.py` now connects to a persisted file
(`data/analytics/claims_analytics.duckdb`) instead of an in-memory database,
and materializes each result as a real table (`pmpm_trend`,
`category_utilization`, `high_cost_cohort`, `monthly_trend`) inside it. This
is what the Power BI connector (MotherDuck DuckDB Power Query) connects to,
matching the approved proposal's "connect to DuckDB" requirement.

## Power BI

**Status: Complete.** After an initial attempt via generic Windows ODBC
proved unreliable (Power BI's Navigator could not enumerate tables in the
DuckDB file), the project switched to the **MotherDuck DuckDB Power Query
connector**, a purpose-built custom connector that correctly surfaces DuckDB's
catalog/schema/table structure.

The dashboard has **3 tabs fully built**:
1. **Cost & Utilization Overview** – KPI cards, bar chart (by category), line chart (by month)
2. **High Cost Cohort** – table, scatter plot, bar chart (top patients)
3. **Utilization Clustering** – scatter plot (colored by cluster), pie chart (patient distribution), table

All tables (`claims`, `pmpm_trend`, `category_utilization`, `high_cost_cohort`,
`monthly_trend`, `utilization_clusters`) are loaded via the DuckDB connector.

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

- **Docker** — implemented for the complete Compose deployment. Use Linux,
  Compute Engine, WSL2, or Docker Desktop; native Windows Airflow execution is
  not supported.
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