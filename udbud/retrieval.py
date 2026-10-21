"""Videnbank (RAG light): chunking + søgning i virksomhedens egne dokumenter.

Prototypen bruger ordmatch i stedet for embeddings, så den kører uden ekstra
pakker og uden at sende dokumenterne nogen steder hen. I drift ville man skifte
search() ud med embeddings og en vector-database — resten af kæden er den samme.
Krav kan være på dansk, tysk eller svensk; lange sammensatte ord matches på
deres første 6 bogstaver (fx 'ansvarsforsikring' ~ 'erhvervsansvarsforsikring').
"""
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "data" / "videnbank"

STOP = {
    # dansk
    "skal", "have", "kunne", "mindst", "inden", "seneste", "tilbudsgiver", "tilbuddet", "leverandøren",
    "være", "eller", "ikke", "alle", "fra", "afgives", "dokumentere", "beskrive",
    # tysk
    "bieter", "muss", "mindestens", "nachweisen", "vorlegen", "angebot", "eine", "einen", "über", "abzugeben",
    # svensk
    "leverantören", "ska", "minst", "anbudet", "lämnas", "kunna", "leverera",
}


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zæøåäöüß0-9-]+", text.lower()) if len(w) > 4 and w not in STOP}


def _match(q: str, words: set[str]) -> bool:
    key = q[:6]
    return any(key in w or w[:6] in q for w in words)


@lru_cache(maxsize=1)
def chunks() -> list[dict]:
    """Del hvert dokument i afsnit ved '## '-overskrifter. README (governance) indekseres ikke."""
    out = []
    for f in sorted(KB.glob("*.md")):
        if f.name == "README.md":
            continue
        for part in re.split(r"\n(?=## )", f.read_text(encoding="utf-8")):
            lines = part.strip().splitlines()
            if not lines or not lines[0].startswith("## "):
                continue
            heading, body = lines[0][3:].strip(), " ".join(lines[1:]).strip()
            out.append({"source": f"{f.stem}#{heading}", "heading": heading, "text": body,
                        "words": _words(heading + " " + body)})
    return out


def search(query: str, k: int = 2, min_score: float = 0.2) -> list[dict]:
    q = _words(query)
    if not q:
        return []
    need = min(2, len(q))            # ét fælles ord er for tilfældigt, medmindre kravet kun har ét ord
    scored = []
    for c in chunks():
        hits = sum(_match(w, c["words"]) for w in q)
        score = hits / len(q)
        if hits >= need and score >= min_score:
            scored.append({"source": c["source"], "heading": c["heading"], "text": c["text"],
                           "score": round(score, 2)})
    return sorted(scored, key=lambda c: -c["score"])[:k]
