"""Udbudsagent — kontrolpanel. Start med:  streamlit run app.py"""
import os
from pathlib import Path

import pandas as pd
import streamlit as st

# På Streamlit Community Cloud ligger API-nøglen i "Secrets" — gør den tilgængelig som miljøvariabel,
# før sprogmodel-modulet indlæses. Lokalt (uden secrets.toml) sker der ingenting.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)):
            os.environ.setdefault(_k, str(_v))
except Exception:
    pass

from udbud import compliance, llm, pipeline  # noqa: E402

st.set_page_config(page_title="Udbudsagent", page_icon="📑", layout="wide")
ROOT = Path(__file__).resolve().parent
ICON = {"BYD": "🟢", "OVERVEJ": "🟡", "BYD IKKE": "🔴",
        "opfyldt": "✅", "ikke opfyldt": "❌", "uklart": "❔",
        "dækket": "✅", "delvist dækket": "🟡", "mangler": "❌"}

# ---------- Sidebar: tilstand ----------
st.sidebar.title("📑 Udbudsagent")
live = st.sidebar.toggle("Hent rigtige udbud fra TED", value=False)
# På den offentlige version kræver AI en adgangskode (AI_ACCESS_CODE i Secrets), så kun
# censorer/undervisere kan bruge den betalte sprogmodel. Uden kode kører agenterne med regler.
access_code = os.getenv("AI_ACCESS_CODE", "")
unlocked = True
if access_code and llm.available():
    entered = st.sidebar.text_input("Adgangskode til AI", type="password",
                                    help="Uden kode kører agenterne med regler (gratis demo).")
    unlocked = entered == access_code
    if entered and not unlocked:
        st.sidebar.error("Forkert kode.")
use_ai = st.sidebar.toggle("Brug AI-agenter", value=False, disabled=not (llm.available() and unlocked),
                           help="Kræver OPENAI_API_KEY eller ANTHROPIC_API_KEY")
if not llm.available():
    st.sidebar.caption("Ingen API-nøgle fundet: agenterne kører med regler (demo).")
else:
    st.sidebar.caption(f"Sprogmodel: {llm.label()}")
user = st.sidebar.text_input("Dit navn (til beslutningsloggen)", value="Bid manager")

if st.sidebar.button("▶ Kør agenterne", type="primary") or "out" not in st.session_state:
    with st.spinner("Overvågning → screening → kravanalyse → bid/no-bid ..."):
        st.session_state.out = pipeline.run(live=live, use_ai=use_ai)

out = st.session_state.out
profile = out["profile"]
st.sidebar.caption(out["source_note"])
st.sidebar.markdown(f"**Profil:** {profile['company']['name']}  \n{profile['company']['industry']}")

tab_board, tab_detail, tab_check, tab_log, tab_about = st.tabs(
    ["1 · Overblik", "2 · Analyse og beslutning", "3 · Kontrol af tilbud", "4 · Log og nøgletal",
     "5 · Om systemet"])

# ---------- 1. Overblik ----------
with tab_board:
    res = out["results"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Udbud fundet", len(res) + len(out["filtered"]))
    c2.metric("Frasorteret automatisk", len(out["filtered"]))
    c3.metric("Anbefalet: BYD", sum(r["analysis"]["decision"] == "BYD" for r in res))
    c4.metric("Kræver afklaring", sum(r["analysis"]["decision"] == "OVERVEJ" for r in res))

    rows = [{
        "": ICON[r["analysis"]["decision"]],
        "Anbefaling": r["analysis"]["decision"],
        "Score": r["analysis"]["score"],
        "Titel": r["tender"].title,
        "Ordregiver": r["tender"].buyer,
        "Frist": r["tender"].deadline,
        "Dage": r["analysis"]["days_left"],
        "Værdi (DKK)": r["tender"].estimated_value_dkk,
        "Begrundelse": r["analysis"]["why"],
    } for r in res]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    with st.expander(f"Frasorteret af screening-agenten ({len(out['filtered'])})"):
        for f in out["filtered"]:
            st.write(f"**{f['tender'].title}** — {'; '.join(f['screening']['reasons'])}")
    st.caption("AI'en anbefaler. Beslutningen om at byde træffes af et menneske under fanen 2.")

# ---------- 2. Analyse og beslutning ----------
with tab_detail:
    res = out["results"]
    if not res:
        st.info("Ingen relevante udbud.")
    else:
        labels = [f"{ICON[r['analysis']['decision']]} {r['tender'].title}" for r in res]
        idx = st.selectbox("Vælg udbud", range(len(res)), format_func=lambda i: labels[i])
        r = res[idx]
        t, ex, an = r["tender"], r["extracted"], r["analysis"]

        st.subheader(t.title)
        st.write(f"**{t.buyer}** · frist {t.deadline} · [åbn i TED]({t.url}) · kilde: {t.source}")
        st.write(t.description)

        if t.source == "TED" and not t.requirements_text:
            st.warning("TED-bekendtgørelsen indeholder sjældent alle krav. Indsæt teksten fra udbudsmaterialet "
                       "for en fuld kravanalyse.")
            pasted = st.text_area("Udbudsmaterialets tekst", height=150, key=f"paste_{t.id}")
            if st.button("Analysér igen med denne tekst") and pasted:
                from udbud import analyst, requirements
                t.requirements_text = pasted
                r["extracted"] = requirements.extract(t, use_ai)
                r["analysis"] = analyst.analyse(t, r["extracted"], r["screening"], profile, out["scoring"], use_ai)
                st.rerun()

        a, b, c = st.columns(3)
        a.metric("Anbefaling", f"{ICON[an['decision']]} {an['decision']}", f"score {an['score']}")
        b.metric("Tilbudsomkostning", f"{an['bid_cost_dkk']:,.0f} kr.".replace(",", "."))
        c.metric("Forventet dækningsbidrag*", f"{an['expected_profit_dkk']:,.0f} kr.".replace(",", "."))
        st.caption(f"Begrundelse: {an['why']}.  *Vinderchance {an['win_prob_assumed']:.0%} er en grov antagelse.")
        st.caption("Scoredele: " + " · ".join(f"{k} {v}" for k, v in an["parts"].items())
                   + f"  |  Kravanalyse: {ex.get('engine')}  |  Vurdering: {an.get('engine')}")

        st.markdown("#### Krav fundet i udbuddet")
        st.dataframe(pd.DataFrame([{
            "": ICON.get(ch["status"], ""),
            "Status": ch["status"],
            "Knock-out": "JA" if ch.get("is_knockout") else "",
            "Krav": ch["requirement"],
            "Begrundelse": ch.get("reason", ""),
            "Kilde": ch.get("source", ""),
        } for ch in an["checks"]]), hide_index=True, width="stretch")
        st.caption("Kilde 'profil' = config/profile.yaml · 'fil#afsnit' = videnbanken (data/videnbank) · "
                   "'—' = ingen kilde, derfor uklart.")

        if an.get("questions_for_human"):
            st.markdown("#### Skal afklares af en medarbejder")
            for q in an["questions_for_human"]:
                st.write(f"- {q}")
        if ex.get("rejected_requirements"):
            st.warning("Kravanalysen fandt krav uden belæg i udbudsteksten — de er fjernet: "
                       + "; ".join(ex["rejected_requirements"]))
        if ex.get("documents_needed"):
            st.write("**Dokumenter der skal vedlægges:** " + ", ".join(ex["documents_needed"]))

        st.markdown("---\n#### 🧑‍💼 Menneskelig beslutning")
        decision = st.radio("Beslutning", ["BYD", "OVERVEJ", "BYD IKKE"], horizontal=True,
                            index=["BYD", "OVERVEJ", "BYD IKKE"].index(an["decision"]), key=f"dec_{t.id}")
        reason = st.text_input("Begrundelse (påkrævet)", key=f"why_{t.id}")
        if st.button("Gem beslutning", key=f"save_{t.id}"):
            if not reason.strip():
                st.error("Skriv en begrundelse — den bruges til at lære af beslutningerne.")
            else:
                pipeline.log_decision(t.id, t.title, an["decision"], decision, reason, user)
                st.success("Beslutningen er gemt i loggen.")

# ---------- 3. Kontrol af tilbud ----------
with tab_check:
    res = out["results"]
    if res:
        idx2 = st.selectbox("Udbud", range(len(res)), format_func=lambda i: res[i]["tender"].title, key="chk")
        reqs = res[idx2]["extracted"]["requirements"]
        draft = st.text_area("Indsæt udkast til tilbud", height=220)
        if st.button("Kontrollér udkastet") and draft:
            cov = compliance.check(reqs, draft, use_ai)
            for msg in cov.get("critical", []):
                st.error(msg)
            st.dataframe(pd.DataFrame([{
                "": ICON.get(c["status"], ""), "Status": c["status"],
                "Knock-out": "JA" if c.get("is_knockout") else "",
                "Krav": c["requirement"], "Fundet i udkastet": c.get("evidence", ""),
            } for c in cov["coverage"]]), hide_index=True, width="stretch")
            st.caption(f"Kontrol udført af: {cov.get('engine')}. Agenten peger på mangler — den skriver ikke tilbuddet.")

# ---------- 4. Log og nøgletal ----------
with tab_log:
    st.markdown("#### Beslutninger (audit trail)")
    if pipeline.DECISIONS.exists():
        log = pd.read_csv(pipeline.DECISIONS)
        agree = log["agrees_with_ai"].mean() if len(log) else 0
        st.metric("Enighed mellem menneske og AI", f"{agree:.0%}", f"{len(log)} beslutninger")
        short = (log["reason"].astype(str).str.len() < 20).mean() if len(log) else 0
        if len(log) >= 10 and (agree >= 0.95 or short >= 0.5):
            st.warning("Risiko for automatiseringsbias: mennesket følger næsten altid AI'en "
                       "og/eller skriver meget korte begrundelser. Stikprøvekontrollér de seneste beslutninger.")
        st.dataframe(log, hide_index=True, width="stretch")
    else:
        st.info("Ingen beslutninger endnu.")

    st.markdown("#### AI-forbrug og omkostning (målt)")
    if llm.USAGE_LOG.exists():
        usage = pd.read_csv(llm.USAGE_LOG)
        c1, c2, c3 = st.columns(3)
        c1.metric("AI-kald", len(usage))
        c2.metric("Samlet pris (USD)", f"{usage['cost_usd'].sum():.3f}")
        c3.metric("Gns. pris pr. kald (USD)", f"{usage['cost_usd'].mean():.4f}")
        st.dataframe(usage.groupby("agent")[["input_tokens", "output_tokens", "cost_usd"]].sum(),
                     width="stretch")
    else:
        st.info("Ingen AI-kald endnu. I demo-tilstand koster agenterne 0 kr.")

# ---------- 5. Om systemet (gennemsigtighed) ----------
with tab_about:
    st.markdown("""
#### Hvem gør hvad
| Trin | Udføres af | AI-modul? |
|---|---|---|
| 1 Overvågning (TED) | integration | nej |
| 2 Screening | regler (CPV, nøgleord) | nej |
| 3 Kravanalyse | sprogmodel, prompt-kæde trin 1 | **ja** |
| 4 Bid/no-bid-vurdering | sprogmodel + videnbank (RAG), trin 2 · score beregnes af kode | **ja** |
| Beslutning om at byde | **menneske**, med påkrævet begrundelse | — |
| 5 Kontrol af tilbud | sprogmodel, trin 3 | **ja** |

#### AI-forordningen — egen vurdering (ikke juridisk rådgivning)
1. **Er det et AI-system?** Ja, trin 3–5 udleder output fra input med en sprogmodel. Trin 1–2 er almindelig, deterministisk software.
2. **Er anvendelsen forbudt (art. 5)?** Nej.
3. **Er den højrisiko (art. 6, bilag III)?** Nej, vurdering af udbud til eget brug er ikke på listen. Bruges systemet til at udvælge medarbejdere eller vurdere CV'er, skal vurderingen laves igen.
4. **Roller:** virksomheden bygger og bruger selv systemet og er derfor både udbyder og idriftsætter. Leverandøren af sprogmodellen er udbyder af en GPAI-model.
5. **Gennemsigtighed:** alle AI-vurderinger er markeret med motor (AI eller regler) og kilde.
6. **Menneskeligt tilsyn som designkrav:** et menneske træffer beslutningen, begrundelsen er påkrævet, og loggen måler enighed med AI'en for at opdage automatiseringsbias.

#### Data der sendes til sprogmodellen
Udbudstekster (offentlige), virksomhedsprofil og uddrag fra videnbanken. Personoplysninger og fortrolige kundedokumenter må ikke ligge i videnbanken — se `data/videnbank/README.md`.
""")
