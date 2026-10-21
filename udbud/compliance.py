"""Agent 5 — Compliance: tjekker om et udkast til tilbud besvarer alle krav."""
import json
import re

from . import llm

STOP = {"skal", "have", "kunne", "på", "af", "en", "et", "og", "i", "til", "de", "der",
        "med", "mindst", "for", "som", "det", "den", "inden", "seneste", "tilbudsgiver", "tilbuddet"}


def _demo_check(requirements: list, draft: str) -> dict:
    draft_low = draft.lower()
    sentences = re.split(r"(?<=[.!?])\s+", draft)
    coverage, critical = [], []
    for r in requirements:
        words = [w for w in re.findall(r"[a-zæøå0-9]+", r["text"].lower()) if len(w) > 3 and w not in STOP]
        hits = [w for w in words if w in draft_low]
        share = len(hits) / len(words) if words else 0
        status = "dækket" if share >= 0.6 else "delvist dækket" if share >= 0.3 else "mangler"
        evidence = next((s for s in sentences if hits and any(h in s.lower() for h in hits)), "")
        coverage.append({"requirement": r["text"], "status": status, "evidence": evidence[:200],
                         "is_knockout": r.get("is_knockout", False)})
        if status == "mangler" and r.get("is_knockout"):
            critical.append(f"Knock-out-krav ikke besvaret: {r['text']}")
    return {"coverage": coverage, "critical": critical, "engine": "ordmatch (demo)"}


def check(requirements: list, draft: str, use_ai: bool) -> dict:
    if not use_ai or not llm.available():
        return _demo_check(requirements, draft)
    result = llm.ask_json("compliance_agent", json.dumps(
        {"krav": requirements, "udkast": draft}, ensure_ascii=False))
    result["engine"] = f"AI ({llm.label()})"
    return result
