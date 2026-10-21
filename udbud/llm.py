"""Tynd indpakning om sprogmodellen — virker med enten Anthropic (Claude) eller OpenAI (ChatGPT).

Hvilken leverandør der bruges, afgøres af miljøvariablerne:
  ANTHROPIC_API_KEY  -> Claude   (model: CLAUDE_MODEL)
  OPENAI_API_KEY     -> OpenAI   (model: OPENAI_MODEL)
Er begge sat, bruges Anthropic, medmindre LLM_PROVIDER=openai.

Hvert kald logges i data/usage_log.csv med tokens og anslået pris, så business
casen kan bruge målte omkostninger i stedet for gæt.
"""
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "prompts"
USAGE_LOG = ROOT / "data" / "usage_log.csv"


def _provider() -> str | None:
    wanted = os.getenv("LLM_PROVIDER", "").lower()
    if wanted == "openai" and os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


PROVIDER = _provider()
if PROVIDER == "openai":
    # Tjek på platform.openai.com hvilke modeller din konto har adgang til, og sæt OPENAI_MODEL.
    MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
else:
    MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")

# Lav temperatur (0–0,3) til udtræk og klassifikation giver ensartede svar (Gang 2). Kan ændres med LLM_TEMPERATURE.
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# Priser i USD pr. million tokens. Tjek leverandørens aktuelle prisside og sæt dem som miljøvariabler.
PRICE_IN = float(os.getenv("PRICE_IN_PER_MTOK", "2.0"))   # Claude Sonnet 5.5, okt. 2026
PRICE_OUT = float(os.getenv("PRICE_OUT_PER_MTOK", "10.0"))


def available() -> bool:
    return PROVIDER is not None


def label() -> str:
    return f"{'OpenAI' if PROVIDER == 'openai' else 'Claude'} ({MODEL})" if PROVIDER else "ingen"


def load_prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Modellen svarede ikke med JSON")
    return json.loads(match.group(0))


def _log_usage(agent: str, tokens_in: int, tokens_out: int, seconds: float) -> None:
    USAGE_LOG.parent.mkdir(exist_ok=True)
    new = not USAGE_LOG.exists()
    cost = tokens_in / 1e6 * PRICE_IN + tokens_out / 1e6 * PRICE_OUT
    with USAGE_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "agent", "provider", "model", "input_tokens", "output_tokens",
                        "cost_usd", "seconds"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), agent, PROVIDER, MODEL,
                    tokens_in, tokens_out, round(cost, 5), round(seconds, 1)])


def _ask_anthropic(system: str, user_content: str, max_tokens: int) -> tuple[str, int, int]:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens, "temperature": TEMPERATURE, "system": system,
              "messages": [{"role": "user", "content": user_content}]},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    text = "".join(b.get("text", "") for b in data.get("content", []))
    return text, usage.get("input_tokens", 0), usage.get("output_tokens", 0)


def _ask_openai(system: str, user_content: str, max_tokens: int) -> tuple[str, int, int]:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens, "temperature": TEMPERATURE,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user_content}]},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    text = data["choices"][0]["message"].get("content") or ""
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


def ask_json(agent: str, user_content: str, max_tokens: int = 2000) -> dict:
    """Send én opgave til sprogmodellen med agentens instruktion og returnér JSON-svaret."""
    started = time.time()
    system = load_prompt(agent)
    ask = _ask_openai if PROVIDER == "openai" else _ask_anthropic
    text, tokens_in, tokens_out = ask(system, user_content, max_tokens)
    _log_usage(agent, tokens_in, tokens_out, time.time() - started)
    return _extract_json(text)
