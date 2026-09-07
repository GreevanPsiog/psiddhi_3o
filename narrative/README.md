# AI Narrative Generation

Turns the DuckDB analytics outputs + ML metrics into an executive-summary
narrative, with a second LLM call acting as a fact-checking judge before
anything is trusted.

## Guard-condition analogy
If it helps to map this onto Freshservice Workflow Automator terms:
- `build_facts()` = the data snapshot the automation rule is allowed to act on
- Narrative LLM call = the action (draft the notification/summary)
- Judge LLM call = the guard condition that runs *after* the action and can
  reject it before it's allowed to proceed downstream

## Files
- `build_facts.py` — reads `data/analytics/*.csv` + `ml/artifacts/model_metrics.json`,
  writes `narrative/output/facts.json`. This is the *only* source of truth the
  LLM calls are ever shown.
- `llm_client.py` — provider-agnostic client for Groq or Gemini free tier.
- `prompts.py` — system/user prompt templates for both the generator and judge.
- `generate_narrative.py` — orchestrates: build facts → generate → judge →
  (retry once on FAIL) → save.

## Setup
```bash
cp narrative/.env.example narrative/.env
# edit narrative/.env, add your GROQ_API_KEY (or GEMINI_API_KEY)
export $(grep -v '^#' narrative/.env | xargs)
```

Get a free key:
- Groq: https://console.groq.com/keys
- Gemini: https://aistudio.google.com/apikey
- NVIDIA NIM: https://build.nvidia.com (profile → API Keys)

**Never paste a real key into a chat, ticket, or commit message** — if one
ever gets exposed that way, revoke/regenerate it immediately from the
provider's dashboard before using it.

## Run
```bash
# Full run (calls your configured LLM provider twice: generate + judge)
python -m narrative.generate_narrative

# No API key yet, or CI environment — exercises the whole pipeline with a
# deterministic template narrative instead of a real LLM call
python -m narrative.generate_narrative --dry-run
```

## Outputs (`narrative/output/`)
- `facts.json` — the grounded numbers (also useful on its own for the QA report)
- `narrative.md` — the generated narrative. If it failed fact-checking twice
  it's still saved, but prefixed with `**[FLAGGED - FAILED FACT-CHECK]**` —
  never publish that version to the dashboard as-is.
- `judge_report.json` — the judge's verdict (`PASS`/`FAIL`) plus any specific
  contradictions or unsupported claims it found.
- `run_log.json` — timestamp, provider, attempt count, final verdict. This is
  what the Pytest suite and Airflow DAG should check: a DAG task should treat
  `final_verdict != "PASS"` as a failed task, not a warning.

## Why fact-checking is a hard requirement here
`billed_amount` and the ML metrics were both patched earlier in this project
specifically because unlearnable/uncorrelated data produces silently wrong
results (R^2 ≈ 0 the first time round). The same risk applies to narrative
generation: an ungrounded LLM will happily write a plausible-sounding sentence
with a wrong number in it. The judge pass exists so a wrong number gets
caught before it reaches the Power BI dashboard, not after.
