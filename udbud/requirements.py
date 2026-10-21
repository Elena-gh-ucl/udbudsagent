"""Agent 3 — Kravanalyse: udtrækker krav, knock-out-krav og dokumenter (dansk, tysk, svensk)."""
import json
import re

from . import llm
from .monitor import Tender

CATEGORY_RULES = [
    ("økonomi", r"omsætning|umsatz|omsättning|soliditet|egenkapital"),
    ("certificering", r"\biso\b|certificer|zertifiz|certifier"),
    ("referencer", r"referen"),
    ("sikkerhed", r"sikkerhedsgodkend"),
    ("sprog", r"dansk|engelsk|deutsch|svensk|engelska|sprache"),
    ("forsikring", r"forsikring|versicherung|haftpflicht|försäkring"),
    ("dokumentation", r"espd|vedlæg|beskrive|nachweis"),
    ("organisation", r"produktionsleder|tekniker|personal|leverera inom|start"),
]
KNOCKOUT = r"^(mindstekrav|mindestanforderung|ska-krav)\s*:\s*"
INJECTION = r"ignor\w*\s+(alle|all|dine|your|deine)?\s*\w*\s*(regler|regeln|rules|instruktion|instructions)"


def _demo_extract(tender: Tender) -> dict:
    """Regelbaseret udtræk, så demoen virker uden API-nøgle."""
    reqs = []
    for line in tender.requirements_text.splitlines():
        line = line.strip().lstrip("-").strip()
        if not line:
            continue
        low = line.lower()
        category = next((c for c, pat in CATEGORY_RULES if re.search(pat, low)), "andet")
        reqs.append({
            "text": re.sub(KNOCKOUT, "", line, flags=re.I),
            "category": category,
            "is_knockout": bool(re.match(KNOCKOUT, low)),
            "source_quote": line,
            "note": "",
        })
    docs = ["ESPD"] if "espd" in tender.requirements_text.lower() else []
    suspicious = bool(re.search(INJECTION, f"{tender.title} {tender.description} {tender.requirements_text}", re.I))
    return {"requirements": reqs, "documents_needed": docs, "award_criteria": tender.award_criteria,
            "deadline": tender.deadline, "suspicious_instruction": suspicious}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _found(quote: str, text: str) -> bool:
    """Citatet (eller et langt stykke af det) skal stå i teksten. Tolererer små afvigelser i tegnsætning."""
    if quote in text:
        return True
    words = quote.split()
    if len(words) < 4:
        return False
    windows = [" ".join(words[i:i + 4]) for i in range(len(words) - 3)]
    return sum(w in text for w in windows) / len(windows) >= 0.6


def extract(tender: Tender, use_ai: bool) -> dict:
    if not use_ai or not llm.available():
        result = _demo_extract(tender)
        result["engine"] = "regler (demo)"
        return result
    content = json.dumps({
        "titel": tender.title, "ordregiver": tender.buyer, "land": tender.country,
        "beskrivelse": tender.description,
        "udbudstekst": tender.requirements_text or "(ingen udbudstekst indsat — brug beskrivelsen)",
        "tildelingskriterier": tender.award_criteria, "frist": tender.deadline,
    }, ensure_ascii=False)
    result = llm.ask_json("requirements_agent", content)
    # Værn i koden: et krav tæller kun, hvis citatet faktisk findes i udbudsteksten.
    # Krav uden belæg (hallucinationer) fjernes og vises som spørgsmål til et menneske.
    source_text = _norm(" ".join([tender.title, tender.description, tender.requirements_text or "",
                                  tender.award_criteria or ""]))
    kept, rejected = [], []
    for r in result.get("requirements", []):
        quote = _norm(r.get("source_quote", ""))
        (kept if quote and _found(quote, source_text) else rejected).append(r)
    result["requirements"] = kept
    result["rejected_requirements"] = [r.get("text", "") for r in rejected]
    result.setdefault("suspicious_instruction", bool(result.get("mistaenkelig_instruktion", False)))
    result["engine"] = f"AI ({llm.label()})"
    return result
