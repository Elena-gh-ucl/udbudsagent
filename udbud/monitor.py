"""Agent 1 — Overvågning: henter nye udbud fra TED (live) eller eksempeldata (demo)."""
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TED_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_FIELDS = [
    "publication-number", "notice-title", "buyer-name", "buyer-country",
    "classification-cpv", "publication-date", "deadline-receipt-tender-date-lot",
    "description-lot", "estimated-value-lot",
]


@dataclass
class Tender:
    id: str
    title: str
    buyer: str
    country: str
    cpv: list
    published: str
    deadline: str
    estimated_value_dkk: float | None
    url: str
    description: str
    requirements_text: str = ""
    award_criteria: str = ""
    source: str = "demo"
    extra: dict = field(default_factory=dict)


def load_sample() -> list[Tender]:
    raw = json.loads((ROOT / "data" / "sample_tenders.json").read_text(encoding="utf-8"))
    return [Tender(**t, source="demo") for t in raw["tenders"]]


def _pick(value):
    """TED returns values as plain values, lists or {language: [values]}. Prefer Danish."""
    if isinstance(value, dict):
        for lang in ("dan", "eng"):
            if lang in value:
                return _pick(value[lang])
        return _pick(next(iter(value.values()), ""))
    if isinstance(value, list):
        return _pick(value[0]) if value else ""
    return value if value is not None else ""


def _as_list(value) -> list:
    if isinstance(value, dict):
        value = sum((v if isinstance(v, list) else [v] for v in value.values()), [])
    return [str(v) for v in (value if isinstance(value, list) else [value]) if v]


def fetch_ted(profile: dict, days_back: int = 14, limit: int = 50) -> list[Tender]:
    """Search TED for active notices in the profile's countries and CPV codes. No API key needed."""
    since = (date.today() - timedelta(days=days_back)).strftime("%Y%m%d")
    cpvs = " ".join(profile["cpv_codes"])
    countries = " ".join(profile["company"].get("countries", ["DNK"]))
    query = f"buyer-country IN ({countries}) AND classification-cpv IN ({cpvs}) AND publication-date>={since}"
    resp = requests.post(
        TED_URL,
        json={"query": query, "fields": TED_FIELDS, "limit": limit, "page": 1,
              "scope": "ACTIVE", "paginationMode": "PAGE_NUMBER"},
        timeout=60,
    )
    resp.raise_for_status()
    tenders = []
    for n in resp.json().get("notices", []):
        pub_no = str(_pick(n.get("publication-number")))
        value = _pick(n.get("estimated-value-lot"))
        tenders.append(Tender(
            id=pub_no,
            title=str(_pick(n.get("notice-title"))),
            buyer=str(_pick(n.get("buyer-name"))),
            country=str(_pick(n.get("buyer-country"))),
            cpv=_as_list(n.get("classification-cpv")),
            published=str(_pick(n.get("publication-date")))[:10],
            deadline=str(_pick(n.get("deadline-receipt-tender-date-lot")))[:10],
            estimated_value_dkk=float(value) if str(value).replace(".", "", 1).isdigit() else None,
            url=f"https://ted.europa.eu/en/notice/-/detail/{pub_no}",
            description=str(_pick(n.get("description-lot"))),
            # TED-bekendtgørelsen indeholder sjældent alle krav. Den fulde tekst
            # fra udbudsmaterialet indsættes af brugeren i appen.
            requirements_text="",
            source="TED",
        ))
    return tenders
