"""
Interactive Q&A over the claims analytics facts — ask any question, get an
answer grounded strictly in facts.json (same anti-hallucination approach as
generate_narrative.py, minus the judge pass since this is exploratory/single-shot).

Run:
    python -m narrative.ask
    python -m narrative.ask "What was the highest PMPM month?"   # one-shot mode
"""

import json
import sys

from narrative import llm_client
from narrative.build_facts import build_facts

ASK_SYSTEM_PROMPT = """You are a healthcare claims data analyst assistant.
Answer the user's question using ONLY the facts JSON provided. Never invent,
estimate, or infer a number not explicitly present. If the facts JSON doesn't
contain what's needed to answer, say so clearly instead of guessing. Keep
answers concise — a few sentences unless the question asks for detail. Always
state currency/units correctly (these are dollar amounts, not billions unless
actually in the billions)."""


def ask(question: str, facts_json_str: str) -> str:
    user_prompt = f"""Facts JSON (source of truth):
{facts_json_str}

Question: {question}"""
    return llm_client.chat(ASK_SYSTEM_PROMPT, user_prompt, temperature=0.1)


def main():
    facts = build_facts()
    facts_json_str = json.dumps(facts, indent=2)

    if len(sys.argv) > 1:
        # One-shot mode: python -m narrative.ask "your question"
        question = " ".join(sys.argv[1:])
        print(f"Q: {question}\n")
        print(ask(question, facts_json_str))
        return

    # Interactive mode
    print("=== Claims Analytics Q&A ===")
    print("Ask anything about the analytics data. Type 'exit' or 'quit' to stop.\n")
    while True:
        try:
            question = input("Q: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break
        try:
            answer = ask(question, facts_json_str)
            print(f"\nA: {answer}\n")
        except (llm_client.LLMConfigError, llm_client.LLMRequestError) as e:
            print(f"[ERROR] {e}\n")


if __name__ == "__main__":
    main()