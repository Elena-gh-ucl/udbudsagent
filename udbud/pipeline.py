"""Orkestrator: kører agenterne i rækkefølge og stopper ved det menneskelige beslutningspunkt."""
import csv
from datetime import datetime
from pathlib import Path

import yaml

from . import analyst, monitor, requirements, screening

ROOT = Path(__file__).resolve().parent.parent
DECISIONS = ROOT / "data" / "decisions.csv"


def load_config(profile_file: str = "profile.yaml") -> tuple[dict, dict]:
    cfg = ROOT / "config"
    profile = yaml.safe_load((cfg / profile_file).read_text(encoding="utf-8"))
    scoring = yaml.safe_load((cfg / "scoring.yaml").read_text(encoding="utf-8"))
    return profile, scoring


def collect(profile: dict, live: bool) -> tuple[list, str]:
    """Agent 1. Falls back to demo data if TED cannot be reached."""
    if not live:
        return monitor.load_sample(), "Demo: fiktive eksempeludbud"
    try:
        tenders = monitor.fetch_ted(profile)
        return tenders, f"TED: {len(tenders)} aktive udbud hentet"
    except Exception as exc:  # network, API change, etc.
        return monitor.load_sample(), f"TED kunne ikke nås ({exc}). Viser demo-data."


def run(live: bool = False, use_ai: bool = False, profile_file: str = "profile.yaml") -> dict:
    profile, scoring = load_config(profile_file)
    tenders, source_note = collect(profile, live)
    results, filtered = [], []
    for t in tenders:
        s = screening.screen(t, profile)                       # Agent 2
        if s["score"] < scoring["thresholds"]["screening_min"]:
            filtered.append({"tender": t, "screening": s})
            continue
        ex = requirements.extract(t, use_ai)                    # Agent 3
        an = analyst.analyse(t, ex, s, profile, scoring, use_ai)  # Agent 4
        results.append({"tender": t, "screening": s, "extracted": ex, "analysis": an})
    order = {"BYD": 0, "OVERVEJ": 1, "BYD IKKE": 2}
    results.sort(key=lambda r: (order[r["analysis"]["decision"]], -r["analysis"]["score"]))
    return {"results": results, "filtered": filtered, "source_note": source_note,
            "profile": profile, "scoring": scoring}


def log_decision(tender_id: str, title: str, ai_recommendation: str, human_decision: str,
                 reason: str, decided_by: str) -> None:
    """Menneskets beslutning gemmes sammen med AI'ens anbefaling (audit trail)."""
    DECISIONS.parent.mkdir(exist_ok=True)
    new = not DECISIONS.exists()
    with DECISIONS.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "tender_id", "title", "ai_recommendation",
                        "human_decision", "agrees_with_ai", "reason", "decided_by"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), tender_id, title, ai_recommendation,
                    human_decision, ai_recommendation == human_decision, reason, decided_by])
