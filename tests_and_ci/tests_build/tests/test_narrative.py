"""
Tests for the narrative module. Deliberately uses --dry-run / no-LLM paths
wherever possible so this suite runs in CI without needing API keys or
burning LLM calls. Live-LLM behavior (actual Groq/Gemini/NVIDIA calls) is
intentionally NOT tested here — see tests/test_integration.py for the one
opt-in live test, skipped by default.

Run: pytest tests/test_narrative.py -v
Needs: the pipeline (GE, analytics, ML) to have been run at least once, since
build_facts() reads their output.
"""

import json

import pytest


class TestBuildFacts:
    def test_build_facts_returns_expected_top_level_keys(self):
        from narrative.build_facts import build_facts, ANALYTICS_DIR

        if not ANALYTICS_DIR.exists() or not any(ANALYTICS_DIR.glob("*.csv")):
            pytest.skip("Analytics CSVs not found — run the pipeline first")

        facts = build_facts()
        expected_keys = {
            "period_covered", "pmpm_trend", "category_utilization",
            "high_cost_cohort", "monthly_trend_summary", "ml_models",
        }
        assert expected_keys.issubset(facts.keys())

    def test_build_facts_is_json_serializable(self):
        from narrative.build_facts import build_facts, ANALYTICS_DIR

        if not ANALYTICS_DIR.exists() or not any(ANALYTICS_DIR.glob("*.csv")):
            pytest.skip("Analytics CSVs not found — run the pipeline first")

        facts = build_facts()
        # Should not raise — this is what gets embedded directly into the
        # LLM prompt, so it must serialize cleanly every time.
        json.dumps(facts)

    def test_build_facts_saves_facts_json_file(self):
        from narrative.build_facts import build_facts, OUT_DIR, ANALYTICS_DIR

        if not ANALYTICS_DIR.exists() or not any(ANALYTICS_DIR.glob("*.csv")):
            pytest.skip("Analytics CSVs not found — run the pipeline first")

        build_facts()
        assert (OUT_DIR / "facts.json").exists()


class TestDryRunNarrative:
    """The dry-run path builds a narrative directly from facts with no LLM
    call — ideal for CI since it needs no API key and costs nothing."""

    def test_dry_run_produces_a_pass_verdict(self):
        from narrative.generate_narrative import generate
        from narrative.build_facts import ANALYTICS_DIR

        if not ANALYTICS_DIR.exists() or not any(ANALYTICS_DIR.glob("*.csv")):
            pytest.skip("Analytics CSVs not found — run the pipeline first")

        result = generate(dry_run=True)
        assert result["judge_result"]["verdict"] == "PASS"

    def test_dry_run_narrative_mentions_no_llm_call_was_made(self):
        from narrative.generate_narrative import generate
        from narrative.build_facts import ANALYTICS_DIR

        if not ANALYTICS_DIR.exists() or not any(ANALYTICS_DIR.glob("*.csv")):
            pytest.skip("Analytics CSVs not found — run the pipeline first")

        result = generate(dry_run=True)
        assert "DRY RUN" in result["narrative"]

    def test_dry_run_saves_all_expected_output_files(self):
        from narrative.generate_narrative import generate, OUT_DIR
        from narrative.build_facts import ANALYTICS_DIR

        if not ANALYTICS_DIR.exists() or not any(ANALYTICS_DIR.glob("*.csv")):
            pytest.skip("Analytics CSVs not found — run the pipeline first")

        generate(dry_run=True)
        for filename in ["narrative.md", "judge_report.json", "facts.json", "run_log.json"]:
            assert (OUT_DIR / filename).exists(), f"{filename} was not saved"


class TestLLMClientConfig:
    """These test the config/error-handling paths only — no network calls."""

    def test_unconfigured_provider_raises_config_error(self, monkeypatch):
        from narrative import llm_client

        monkeypatch.setattr(llm_client.os.environ, "get", lambda k, d=None: d)
        assert llm_client.is_configured() is False

    def test_unknown_provider_raises_config_error(self, monkeypatch):
        from narrative import llm_client

        monkeypatch.setenv("LLM_PROVIDER", "not_a_real_provider")
        with pytest.raises(llm_client.LLMConfigError):
            llm_client.chat("system", "user")
