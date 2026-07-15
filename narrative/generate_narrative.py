"""
AI narrative generation with LLM-as-judge fact-checking.

Pipeline:
    1. build_facts()            -> facts.json (grounded numbers, the only source of truth)
    2. LLM call #1 (generator)  -> narrative text, strictly prompted to use only facts.json
    3. LLM call #2 (judge)      -> audits the narrative against facts.json, returns PASS/FAIL
                                    + a list of any unsupported or contradicted claims
    4. If FAIL: regenerate once with the judge's feedback appended to the prompt.
       If still FAIL: save the narrative anyway but mark it clearly as
       "FLAGGED - failed fact-check" so it can never be silently trusted downstream
       (Airflow DAG should treat a second FAIL as a task failure, not a warning).

Run standalone:
    python narrative/generate_narrative.py
    python narrative/generate_narrative.py --dry-run   # no API calls, template narrative
Env:
    LLM_PROVIDER=groq|gemini, plus the matching API key (see llm_client.py)
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from narrative import llm_client
from narrative.build_facts import build_facts
from narrative.prompts import (
    JUDGE_SYSTEM_PROMPT,
    NARRATIVE_SYSTEM_PROMPT,
    build_judge_prompt,
    build_narrative_prompt,
)

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "narrative" / "output"


def _dry_run_narrative(facts: dict) -> str:
    """Deterministic, template-based narrative — no LLM call. Used for --dry-run
    (e.g. in CI, or when no API key is configured) so the rest of the pipeline
    can still be exercised end-to-end."""
    p = facts["pmpm_trend"]
    cats = facts["category_utilization"]
    ml = facts["ml_models"]
    top_cat = max(cats, key=lambda c: c["total_billed"])
    return (
        f"[DRY RUN - template narrative, not LLM-generated]\n\n"
        f"Across {facts['period_covered']['months_of_data']} months of claims data "
        f"({facts['period_covered']['first_month']} to {facts['period_covered']['last_month']}), "
        f"average PMPM cost was ${p['overall_avg_pmpm_cost']}, "
        f"ranging from ${p['min_pmpm_cost']} to ${p['max_pmpm_cost']}, "
        f"with the most recent month ({p['latest_month']}) at ${p['latest_pmpm_cost']}.\n\n"
        f"{top_cat['claim_category']} was the highest-cost category at "
        f"${top_cat['total_billed']} total billed across {top_cat['claim_count']} claims.\n\n"
        f"The high-cost cohort of {facts['high_cost_cohort']['cohort_size']} patients "
        f"averaged ${facts['high_cost_cohort']['cohort_avg_total_billed']} in total billed cost each.\n\n"
        f"The cost prediction model achieved an R^2 of "
        f"{max(ml['cost_prediction']['linear_regression_r2'], ml['cost_prediction']['random_forest_r2'])} "
        f"(target: > 0.6), and utilization clustering achieved a silhouette score of "
        f"{ml['utilization_clustering']['silhouette_score']} (target: > 0.3)."
    )


def _dry_run_judge() -> dict:
    return {
        "verdict": "PASS",
        "contradictions": [],
        "unsupported_claims": [],
        "notes": "Dry run — judge not invoked, template narrative is generated directly from facts.",
    }


def _parse_judge_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def generate(dry_run: bool = False, max_attempts: int = 2) -> dict:
    facts = build_facts()
    facts_json_str = json.dumps(facts, indent=2)

    if dry_run:
        narrative = _dry_run_narrative(facts)
        judge_result = _dry_run_judge()
        attempts = 1
    else:
        if not llm_client.is_configured():
            raise llm_client.LLMConfigError(
                "No API key configured for the selected LLM_PROVIDER. "
                "Set GROQ_API_KEY or GEMINI_API_KEY, or run with --dry-run to test "
                "the pipeline without calling an LLM."
            )

        judge_result = None
        narrative = None
        feedback_note = ""
        for attempt in range(1, max_attempts + 1):
            user_prompt = build_narrative_prompt(facts_json_str) + feedback_note
            narrative = llm_client.chat(
                NARRATIVE_SYSTEM_PROMPT, user_prompt, temperature=0.2,
                max_tokens=8000, enable_thinking=True,
            )

            judge_prompt = build_judge_prompt(facts_json_str, narrative)
            judge_raw = llm_client.chat(
                JUDGE_SYSTEM_PROMPT, judge_prompt, temperature=0.0,
                max_tokens=4000, enable_thinking=False,
            )
            judge_result = _parse_judge_response(judge_raw)

            if judge_result.get("verdict") == "PASS":
                break

            feedback_note = (
                "\n\nNOTE: A previous draft failed fact-checking with these issues, "
                "fix them and use ONLY numbers present in the facts JSON above:\n"
                + json.dumps(
                    judge_result.get("contradictions", []) + judge_result.get("unsupported_claims", []),
                    indent=2,
                )
            )
        attempts = attempt

    flagged = judge_result.get("verdict") != "PASS"
    if flagged:
        narrative = "**[FLAGGED - FAILED FACT-CHECK, DO NOT PUBLISH AS-IS]**\n\n" + narrative

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "narrative.md", "w") as f:
        f.write(narrative)
    with open(OUT_DIR / "judge_report.json", "w") as f:
        json.dump(judge_result, f, indent=2)

    run_log = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "attempts": attempts,
        "final_verdict": judge_result.get("verdict"),
        "provider": "dry-run" if dry_run else llm_client._provider(),
    }
    with open(OUT_DIR / "run_log.json", "w") as f:
        json.dump(run_log, f, indent=2)

    return {"narrative": narrative, "judge_result": judge_result, "run_log": run_log}


def main():
    parser = argparse.ArgumentParser(description="Generate AI narrative with fact-checking.")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, use a template narrative.")
    args = parser.parse_args()

    try:
        result = generate(dry_run=args.dry_run)
    except llm_client.LLMConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        raise SystemExit(1)
    except llm_client.LLMRequestError as e:
        print(f"[API ERROR] {e}")
        raise SystemExit(1)

    print("=== Narrative generation summary ===")
    print(f"Verdict: {result['judge_result'].get('verdict')}")
    print(f"Attempts: {result['run_log']['attempts']}")
    print()
    print(result["narrative"])
    print()
    print("Saved to narrative/output/: narrative.md, judge_report.json, facts.json, run_log.json")


if __name__ == "__main__":
    main()
