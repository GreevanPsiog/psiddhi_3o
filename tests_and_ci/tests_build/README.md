# Tests

Covers the QA strategy named in the RFP: unit tests, integration tests, and
CI wired to run automatically on every push.

## Where these files go

Extract into your project root, merging with what's already there:

```
psiddhi-claims-platform/
├── tests/                        <- these test files
│   ├── conftest.py
│   ├── test_data_quality.py
│   ├── test_analytics.py
│   ├── test_ml_models.py
│   ├── test_narrative.py
│   ├── test_dag_integrity.py
│   └── test_integration.py
├── pytest.ini
└── .github/workflows/tests.yml   <- CI workflow
```

## What each file covers

| File | Type | What it checks |
|---|---|---|
| `test_data_quality.py` | Unit + integration | Raw dataset shape (repeat patients, injected duplicates, cost correlation — regression guards for the two bugs fixed earlier in this project), and that the GE gate's clean output is actually clean |
| `test_analytics.py` | Integration | DuckDB analytics CSV correctness, and that the persisted `.duckdb` file is rerunnable (regression guard for the `CREATE VIEW` bug) |
| `test_ml_models.py` | Unit | R² and silhouette score actually clear the proposal's own thresholds (> 0.6, > 0.3) — not just "training didn't crash" |
| `test_narrative.py` | Unit | `build_facts()` output shape, dry-run narrative generation (no LLM call — safe for CI), LLM client config error handling |
| `test_dag_integrity.py` | Unit | The Airflow DAG imports cleanly, has exactly 5 tasks wired in the correct order, no cycles — the standard Airflow testing pattern, doesn't need a running scheduler |
| `test_integration.py` | Integration (opt-in) | Actually runs the pipeline scripts end-to-end, including running DuckDB analytics **twice in a row** against the same persisted file (this is the regression test that would have caught the `CatalogException` bug) |

## Running locally

Most tests need the pipeline to have been run at least once, so their
fixtures have real output to check. If you haven't already:

```bash
python ge_suite/run_validation.py
python analytics/duckdb_analytics.py
python ml/train_models.py
python -m narrative.generate_narrative --dry-run
```

Then:

```bash
pip install pytest
pytest tests/ -v
```

Tests whose prerequisite files don't exist yet will **skip** (not fail) with
a message telling you which command to run first.

### Slower / opt-in tests

```bash
# Actually re-runs the pipeline scripts (slower, ~1-2 min)
pytest tests/test_integration.py -v --run-integration

# Additionally makes one real LLM API call (needs narrative/.env configured)
pytest tests/test_integration.py -v --run-integration --run-live-llm
```

Neither runs by default — the CI workflow only runs the fast, skip-graceful
suite plus the DAG integrity check.

## CI (`.github/workflows/tests.yml`)

Runs on every push/PR: sets up Python 3.12, runs the real pipeline (GE →
DuckDB → ML → narrative dry-run), then the test suite.

**One thing to configure**: the ML training step needs Databricks
credentials to actually succeed in CI. Add these as GitHub repo secrets
(**Settings → Secrets and variables → Actions**):
- `DATABRICKS_HOST`
- `DATABRICKS_TOKEN`

If you don't add these, the ML training step will fail but **won't fail the
whole CI run** (`continue-on-error: true`) — the ML-dependent tests will
simply skip, same as running locally without having trained models yet.

## Known limitation

`test_narrative.py`'s live-LLM path is intentionally excluded from CI —
only the dry-run (template, no API call) path is tested automatically, so
CI never depends on or spends a real Groq/Gemini/NVIDIA API call. Live
provider verification (per the disclosed Groq/Gemini gap) is still a manual
step until that's built out further.
