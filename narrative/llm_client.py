"""
Thin, provider-agnostic LLM client. Supports Groq and Gemini free tiers, chosen via
the LLM_PROVIDER env var. Both providers only need one thing from this module:
`chat(system, user, temperature) -> str`.

Config (set as environment variables, e.g. in a local .env you load yourself,
or `export` before running):
    LLM_PROVIDER=groq            # or "gemini" or "nvidia"
    GROQ_API_KEY=...             # https://console.groq.com/keys
    GROQ_MODEL=llama-3.3-70b-versatile   # optional override
    GEMINI_API_KEY=...           # https://aistudio.google.com/apikey
    GEMINI_MODEL=gemini-2.0-flash        # optional override
    NVIDIA_API_KEY=...           # https://build.nvidia.com (API Keys in your profile)
    NVIDIA_MODEL=nvidia/nemotron-3-ultra-550b-a55b   # optional override

If no API key is set for the selected provider, `chat()` raises a clear
LLMConfigError rather than failing with a confusing HTTP error — this is what
generate_narrative.py's --dry-run mode checks for.
"""

import os

import requests
from dotenv import load_dotenv


# Auto-load narrative/.env (if present) so GROQ_API_KEY / GEMINI_API_KEY /
# NVIDIA_API_KEY are picked up without a manual `export`/`set` step, on any OS.
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


class LLMConfigError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    pass


def _provider() -> str:
    return os.environ.get("LLM_PROVIDER", "groq").strip().lower()


def is_configured() -> bool:
    """True if the selected provider has an API key set."""
    provider = _provider()
    if provider == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    if provider == "nvidia":
        return bool(os.environ.get("NVIDIA_API_KEY"))
    return False


def _chat_groq(system: str, user: str, temperature: float) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise LLMConfigError("GROQ_API_KEY is not set (LLM_PROVIDER=groq)")

    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise LLMRequestError(f"Groq API error {resp.status_code}: {resp.text[:500]}")
    return resp.json()["choices"][0]["message"]["content"]


def _chat_gemini(system: str, user: str, temperature: float) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMConfigError("GEMINI_API_KEY is not set (LLM_PROVIDER=gemini)")

    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    url = GEMINI_URL_TEMPLATE.format(model=model)
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature},
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise LLMRequestError(f"Gemini API error {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise LLMRequestError(f"Unexpected Gemini response shape: {data}") from e


def _chat_nvidia(system: str, user: str, temperature: float, max_tokens: int = 4096, enable_thinking: bool = True) -> str:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise LLMConfigError("NVIDIA_API_KEY is not set (LLM_PROVIDER=nvidia)")

    model = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")
    resp = requests.post(
        NVIDIA_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "top_p": 0.95,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": enable_thinking},
        },
        timeout=120,
    )
    if resp.status_code != 200:
        raise LLMRequestError(f"NVIDIA API error {resp.status_code}: {resp.text[:500]}")
    message = resp.json()["choices"][0]["message"]
    content = message.get("content")
    if not content:
        reasoning_preview = str(message.get("reasoning_content", ""))[:300]
        raise LLMRequestError(
            f"NVIDIA response had no final content — likely ran out of max_tokens "
            f"during reasoning. Reasoning preview: {reasoning_preview}"
        )
    return content


def chat(system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096, enable_thinking: bool = True) -> str:
    """Send a system+user prompt to the configured provider, return the text reply."""
    provider = _provider()
    if provider == "groq":
        return _chat_groq(system, user, temperature)
    if provider == "gemini":
        return _chat_gemini(system, user, temperature)
    if provider == "nvidia":
        return _chat_nvidia(system, user, temperature, max_tokens=max_tokens, enable_thinking=enable_thinking)
    raise LLMConfigError(f"Unknown LLM_PROVIDER '{provider}' (expected 'groq', 'gemini', or 'nvidia')")

# def chat(system: str, user: str, temperature: float = 0.2) -> str:
#     """Send a system+user prompt to the configured provider, return the text reply."""
#     provider = _provider()
#     if provider == "groq":
#         return _chat_groq(system, user, temperature)
#     if provider == "gemini":
#         return _chat_gemini(system, user, temperature)
#     if provider == "nvidia":
#         return _chat_nvidia(system, user, temperature)
#     raise LLMConfigError(f"Unknown LLM_PROVIDER '{provider}' (expected 'groq', 'gemini', or 'nvidia')")
