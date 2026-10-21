"""Agent 4 — Bid/no-bid-analytiker.

Sprogmodellen (eller reglerne i demo) vurderer krav mod profilen. Selve scoren og
anbefalingen beregnes i almindelig kode ud fra vægte i config/scoring.yaml, så
ledelsen kan se og ændre præcis hvordan anbefalingen opstår.
"""
import difflib
import json
import re
from datetime import date

from . import llm, retrieval
from .monitor import Tender

EUR_DKK = 7.46
# Ord i referencekrav på dansk/tysk/svensk -> ord i profilens reference-emner
REF_TOPICS = {
    "byfest": ["byfest", "stadtfest"], "stadtfest": ["byfest", "stadtfest"],
    "festival": ["festival"], "konferenc": ["konference"], "streaming": ["streaming"],
    "konzert": ["koncert"], "koncert": ["koncert"], "open-air": ["open-air"],
}
LANG = {"dansk": "dansk", "engelsk": "engelsk", "english": "engelsk", "deutsch": "tysk",
        "tysk": "tysk", "svensk": "svensk", "svenska": "svensk"}


def _num(text: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    return float(m.group(1).replace(",", ".")) if m else None


def _check_rule(req: dict, profile: dict) -> tuple[str, str]:
    t = req["text"].lower()
    c = profile["company"]
    if re.search(r"omsætning|umsatz|omsättning", t) and (n := _num(t)) is not None:
        need = n * 1e6 if "mio" in t else n
        if "eur" in t:
            need *= EUR_DKK
        ok = c["annual_revenue_dkk"] >= need
        return ("opfyldt" if ok else "ikke opfyldt",
                f"annual_revenue_dkk = {c['annual_revenue_dkk']/1e6:.0f} mio. kr. vs. krav {need/1e6:.1f} mio. kr.")
    if "soliditet" in t and (n := _num(t)) is not None:
        ok = c["equity_ratio_pct"] >= n
        return ("opfyldt" if ok else "ikke opfyldt", f"equity_ratio_pct = {c['equity_ratio_pct']} % vs. krav {n:.0f} %")
    if (m := re.search(r"iso\s?(\d{4,5})", t)):
        cert = f"ISO {m.group(1)}"
        ok = cert in profile.get("certificates", [])
        return ("opfyldt" if ok else "ikke opfyldt", f"certificates = {profile.get('certificates')}")
    if "referen" in t:
        need = int(_num(t) or 1)
        topics = [w for key, words in REF_TOPICS.items() if key in t for w in words]
        refs = profile.get("references", [])
        hits = [r for r in refs if not topics or any(w in r["topic"].lower() for w in topics)]
        status = "opfyldt" if len(hits) >= need else ("uklart" if hits else "ikke opfyldt")
        return status, f"{len(hits)} relevante referencer i profilen, krav: {need}"
    if "sikkerhedsgodkend" in t:
        if profile.get("security_clearance"):
            return "opfyldt", "security_clearance = true"
        return "uklart", "Ingen sikkerhedsgodkendelse i profilen — kan den opnås inden kontraktstart?"
    asked = {code for word, code in LANG.items() if word in t}
    if asked:
        ok = bool(asked & set(c.get("languages", [])))
        return ("opfyldt" if ok else "ikke opfyldt",
                f"krævet: {', '.join(sorted(asked))} · profil: {', '.join(c.get('languages', []))}")
    return "uklart", "Profilen indeholder ikke nok information — kræver vurdering af medarbejder"


def _rule_checks(reqs: list, profile: dict) -> dict:
    checks = []
    for r in reqs:
        status, reason = _check_rule(r, profile)
        source = "profil"
        if status == "uklart" and reason.startswith("Profilen indeholder ikke"):
            # Ingen regel passer, og profilen svarer ikke — slå op i videnbanken (RAG)
            hits = retrieval.search(r["text"], k=1, min_score=0.5)
            if hits:
                h = hits[0]
                negative = re.search(r"\b(ikke|ingen)\b", h["text"].lower())
                status = "uklart" if negative else "opfyldt"
                reason = f"Videnbank: {h['text'][:160]}"
                source = h["source"]
            else:
                reason = "Står hverken i profil eller videnbank — kræver vurdering af medarbejder"
                source = "—"
        checks.append({"requirement": r["text"], "status": status, "reason": reason, "source": source,
                       "is_knockout": r.get("is_knockout", False), "category": r.get("category", "")})
    questions = [f"Afklar: {c['requirement']}" for c in checks if c["status"] == "uklart"]
    return {"checks": checks, "strengths": [], "risks": [], "questions_for_human": questions}


def _days_left(deadline: str) -> int | None:
    try:
        return (date.fromisoformat(deadline[:10]) - date.today()).days
    except ValueError:
        return None


def analyse(tender: Tender, extracted: dict, screening: dict, profile: dict, scoring: dict, use_ai: bool) -> dict:
    reqs = extracted.get("requirements", [])
    if use_ai and llm.available() and reqs:
        # Augmentation: hvert krav får de mest relevante uddrag fra videnbanken med
        excerpts = {r["text"]: retrieval.search(r["text"], k=2) for r in reqs}
        result = llm.ask_json("analyst_agent", json.dumps(
            {"krav": reqs, "virksomhedsprofil": profile, "videnbank_uddrag": excerpts}, ensure_ascii=False))
        result["engine"] = f"AI ({llm.label()})"
        # Værn i koden (ikke kun i prompten): knock-out bestemmes af kravanalysen (trin 1),
        # og "ikke opfyldt" uden kilde nedgraderes til "uklart" — så en manglende oplysning
        # aldrig alene kan give BYD IKKE.
        ko = {r["text"]: bool(r.get("is_knockout")) for r in reqs}
        kept = []
        for c in result.get("checks", []):
            match = difflib.get_close_matches(c.get("requirement", ""), list(ko), n=1, cutoff=0.5)
            if not match:   # krav som AI'en selv har tilføjet — står ikke i kravanalysen
                result.setdefault("questions_for_human", []).append(
                    f"AI nævnte et krav, der ikke står i udbuddet (fjernet): {c.get('requirement')}")
                continue
            c["is_knockout"] = ko[match[0]]
            # Tal, antal, certifikater og sprog kontrolleres af koden, ikke af sprogmodellen
            # (sprogmodeller er upålidelige med tal og optælling — Gang 2).
            rule_status, rule_reason = _check_rule({"text": match[0]}, profile)
            if not rule_reason.startswith("Profilen indeholder ikke") and rule_status != c.get("status"):
                c["reason"] = f"Kontrolleret af kode: {rule_reason} (AI vurderede: {c.get('status')})"
                c["status"], c["source"] = rule_status, "virksomhedsprofil (regel)"
            kept.append(c)
        result["checks"] = kept
        for c in kept:
            if c.get("status") == "ikke opfyldt" and str(c.get("source", "")).strip() in ("", "—", "-"):
                c["status"] = "uklart"
                c["reason"] = (c.get("reason", "") + " (ingen kilde — rettet til uklart af koden)").strip()
                result.setdefault("questions_for_human", []).append(f"Afklar: {c['requirement']}")
    else:
        result = _rule_checks(reqs, profile)
        result["engine"] = "regler (demo)"

    checks = result.get("checks", [])
    n = len(checks) or 1
    met = sum(c["status"] == "opfyldt" for c in checks)
    unclear = sum(c["status"] == "uklart" for c in checks)
    knockout_failed = [c for c in checks if c.get("is_knockout") and c["status"] == "ikke opfyldt"]

    w, th = scoring["weights"], scoring["thresholds"]
    value = tender.estimated_value_dkk
    rng = profile["contract_value_dkk"]
    value_score = 0.6 if value is None else 1.0 if rng["min"] <= value <= rng["max"] else 0.3
    days = _days_left(tender.deadline)
    min_days = scoring.get("min_days_to_prepare", 10)
    time_score = 0.5 if days is None else max(0.0, min(days / min_days, 1.0))

    parts = {
        "fit": screening["score"],
        "requirements": (met + 0.5 * unclear) / n if checks else 0.5,
        "value": value_score,
        "time": time_score,
    }
    total = sum(w[k] * parts[k] for k in w)

    other_failed = [c for c in checks if not c.get("is_knockout") and c["status"] == "ikke opfyldt"]
    too_short = days is not None and days < min_days

    if knockout_failed:
        decision = "BYD IKKE"
        why = "Knock-out-krav ikke opfyldt: " + "; ".join(c["requirement"] for c in knockout_failed)
    elif not checks and total >= th["consider"]:
        decision, why = "OVERVEJ", "Kravene er ikke analyseret endnu — indsæt udbudsmaterialet"
    elif total >= th["bid"] and (other_failed or too_short):
        decision = "OVERVEJ"
        why = "; ".join(
            ([f"Krav ikke opfyldt: {other_failed[0]['requirement']}"] if other_failed else [])
            + ([f"Kun {days} dage til fristen (minimum {min_days})"] if too_short else []))
    elif total >= th["bid"]:
        decision, why = "BYD", "Høj samlet score, alle kendte krav opfyldt eller uafklarede"
    elif total >= th["consider"]:
        decision, why = "OVERVEJ", "Middel score — afklar de uklare punkter først"
    else:
        decision, why = "BYD IKKE", "Lav samlet score"

    if extracted.get("suspicious_instruction"):
        # Udbudsteksten forsøgte at give agenten instruktioner: anbefalingen ændres ikke, men et menneske advares
        why += " · ADVARSEL: mistænkelig instruktion i udbudsteksten, ignoreret"
        result.setdefault("questions_for_human", []).insert(
            0, "Udbudsteksten indeholder en instruktion til AI'en (mulig prompt injection) — kontrollér kilden")

    cap = profile["capacity"]
    bid_cost = cap["bid_hours_estimate"] * cap["hourly_cost_dkk"]
    win_prob = 0.0 if knockout_failed else round(min(0.15 + 0.35 * total, 0.5), 2)  # grov antagelse
    expected_profit = (win_prob * (value or 0) * cap["expected_margin_pct"] / 100) - bid_cost

    result.update({
        "score": round(total, 2), "parts": {k: round(v, 2) for k, v in parts.items()},
        "decision": decision, "why": why, "days_left": days,
        "bid_cost_dkk": bid_cost, "win_prob_assumed": win_prob,
        "expected_profit_dkk": round(expected_profit),
    })
    return result
