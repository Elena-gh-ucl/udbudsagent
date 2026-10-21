"""Kør hele kæden fra kommandolinjen og gem resultatet som Excel.

    python run_report.py            # demo-data, regelbaserede agenter
    python run_report.py --live     # rigtige udbud fra TED
    python run_report.py --live --ai  # rigtige udbud + AI-agenter (kræver OPENAI_API_KEY eller ANTHROPIC_API_KEY)
"""
import argparse
from pathlib import Path

import pandas as pd

from udbud import pipeline

parser = argparse.ArgumentParser()
parser.add_argument("--live", action="store_true", help="hent udbud fra TED")
parser.add_argument("--ai", action="store_true", help="brug sprogmodellen til krav og analyse")
args = parser.parse_args()

out = pipeline.run(live=args.live, use_ai=args.ai)
print(out["source_note"])

rows = []
for r in out["results"]:
    t, a = r["tender"], r["analysis"]
    rows.append({
        "Anbefaling": a["decision"], "Score": a["score"], "Titel": t.title, "Ordregiver": t.buyer,
        "Frist": t.deadline, "Dage tilbage": a["days_left"], "Værdi (DKK)": t.estimated_value_dkk,
        "Begrundelse": a["why"],
        "Opfyldte krav": sum(c["status"] == "opfyldt" for c in a["checks"]),
        "Uklare krav": sum(c["status"] == "uklart" for c in a["checks"]),
        "Tilbudsomkostning (DKK)": a["bid_cost_dkk"],
        "Forventet dækningsbidrag (DKK)": a["expected_profit_dkk"],
        "Link": t.url, "Kilde": t.source,
    })
for f in out["filtered"]:
    t = f["tender"]
    rows.append({"Anbefaling": "FRASORTERET", "Score": f["screening"]["score"], "Titel": t.title,
                 "Ordregiver": t.buyer, "Frist": t.deadline, "Begrundelse": "; ".join(f["screening"]["reasons"]),
                 "Link": t.url, "Kilde": t.source})

Path("reports").mkdir(exist_ok=True)
path = Path("reports") / "bid_board.xlsx"
pd.DataFrame(rows).to_excel(path, index=False)
for row in rows:
    print(f"{row['Anbefaling']:<12} {row['Score']:<5} {row['Titel'][:60]}")
print(f"\nGemt: {path}")
