"""Agent 2 — Screening: billigt regelbaseret førstefilter.

Bevidst UDEN sprogmodel: det er gratis, hurtigt og fuldt forklarligt, og det
betyder at kun relevante udbud sendes videre til de dyrere AI-agenter.
"""
from .monitor import Tender


def screen(tender: Tender, profile: dict) -> dict:
    text = f"{tender.title} {tender.description}".lower()

    profile_cpv = {c[:3] for c in profile["cpv_codes"]}          # CPV-hovedgruppe
    cpv_hits = [c for c in tender.cpv if c[:3] in profile_cpv]
    kw_hits = [k for k in profile["keywords"] if k.lower() in text]
    excluded = [k for k in profile.get("exclude_keywords", []) if k.lower() in text]

    cpv_score = 1.0 if cpv_hits else 0.0
    kw_score = min(len(kw_hits) / 3, 1.0)
    score = 0.6 * cpv_score + 0.4 * kw_score
    if excluded:
        score *= 0.2

    reasons = []
    reasons.append(f"CPV-match: {', '.join(cpv_hits)}" if cpv_hits else "Ingen CPV-match")
    if kw_hits:
        reasons.append(f"Nøgleord: {', '.join(kw_hits[:5])}")
    if excluded:
        reasons.append(f"Udelukkende ord: {', '.join(excluded)}")

    return {"score": round(score, 2), "reasons": reasons}
