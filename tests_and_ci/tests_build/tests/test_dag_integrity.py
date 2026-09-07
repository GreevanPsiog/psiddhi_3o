"""
DAG integrity tests — the standard Airflow testing pattern. These import
the DAG module directly and inspect its structure; they do NOT need a
running Airflow scheduler/webserver, so they're safe and fast to run in CI.

Run: pytest tests/test_dag_integrity.py -v
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dags"))

pytest.importorskip("airflow", reason="apache-airflow not installed in this environment")


@pytest.fixture(scope="module")
def dag():
    # Import fresh each test session; PROJECT_ROOT_IN_CONTAINER unset means
    # it'll fall back to /opt/airflow/project, which is fine for import-only
    # checks — we're not executing any tasks here.
    os.environ.setdefault("PROJECT_ROOT_IN_CONTAINER", str(ROOT))
    import claims_pipeline_dag
    return claims_pipeline_dag.dag


class TestDAGIntegrity:
    def test_dag_imports_without_errors(self, dag):
        assert dag is not None

    def test_dag_id_is_correct(self, dag):
        assert dag.dag_id == "psiddhi_claims_pipeline"

    def test_dag_has_exactly_five_tasks(self, dag):
        assert len(dag.tasks) == 5

    def test_dag_has_expected_task_ids(self, dag):
        expected = {"ingest", "validate_ge", "duckdb_analytics", "train_ml", "generate_narrative"}
        actual = {t.task_id for t in dag.tasks}
        assert actual == expected

    def test_dag_has_no_cycles(self, dag):
        # Airflow itself raises at DAG-build time if there's a cycle, but
        # this makes the intent explicit and catches it even if that
        # behavior ever changes upstream.
        dag.test_cycle()

    def test_tasks_are_wired_in_the_correct_linear_order(self, dag):
        ingest = dag.get_task("ingest")
        validate = dag.get_task("validate_ge")
        analytics = dag.get_task("duckdb_analytics")
        train_ml = dag.get_task("train_ml")
        narrative = dag.get_task("generate_narrative")

        assert validate.task_id in [t.task_id for t in ingest.downstream_list]
        assert analytics.task_id in [t.task_id for t in validate.downstream_list]
        assert train_ml.task_id in [t.task_id for t in analytics.downstream_list]
        assert narrative.task_id in [t.task_id for t in train_ml.downstream_list]

    def test_all_tasks_use_python_operator(self, dag):
        from airflow.providers.standard.operators.python import PythonOperator
        for task in dag.tasks:
            assert isinstance(task, PythonOperator), f"{task.task_id} is not a PythonOperator"

    def test_dag_has_no_schedule_by_default(self, dag):
        """This DAG is meant to be triggered manually / via the companion
        app, not run on an automatic schedule — regression guard against
        an accidental schedule getting added."""
        assert dag.schedule_interval is None or dag.timetable.summary == "None"
