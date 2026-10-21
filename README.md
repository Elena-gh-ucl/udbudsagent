# Udbudsagent — prototype

Et netværk af AI-agenter, der hjælper den fiktive eventteknik-virksomhed **NordScene ApS**
med at finde, vurdere og kontrollere tilbud på udbud i Danmark, Tyskland og Sverige.
AI'en anbefaler; et menneske beslutter altid, om der bydes, og godkender tilbuddet.

Mappen er kode og skal pakkes ud og køres på en computer (ikke åbnes på en telefon).

## Kom i gang (ca. 5 minutter)

1. Installer Python 3.11 eller nyere fra python.org.
2. Åbn en terminal i mappen og kør:
   ```
   pip install -r requirements.txt
   streamlit run app.py
   ```
3. Browseren åbner kontrolpanelet i **demo-tilstand**: 6 fiktive udbud på dansk, tysk og svensk,
   agenter baseret på regler. Det koster intet og virker uden internet.

**Rigtige udbud:** slå "Hent rigtige udbud fra TED" til i sidepanelet. TED's Search API er åbent og
kræver ingen nøgle. Kan TED ikke nås, vises årsagen, og demo-data bruges.

**Rigtige AI-agenter:** brug en API-nøgle fra OpenAI (platform.openai.com) eller Anthropic
(console.anthropic.com). Et ChatGPT-abonnement er ikke en API-nøgle; API'et betales separat
med forudbetalt kredit. Sæt nøglen, før appen startes:

| | OpenAI | Anthropic |
|---|---|---|
| Mac/Linux | `export OPENAI_API_KEY=din_nøgle` | `export ANTHROPIC_API_KEY=din_nøgle` |
| Windows (PowerShell) | `$env:OPENAI_API_KEY="din_nøgle"` | `$env:ANTHROPIC_API_KEY="din_nøgle"` |
| Model (valgfri) | `OPENAI_MODEL` (standard `gpt-4o-mini`; tjek hvilke modeller din konto har) | `CLAUDE_MODEL` |

Slå derefter "Brug AI-agenter" til; sidepanelet viser, hvilken model der bruges. Hvert kald logges i
`data/usage_log.csv` med tokens og pris, så business casen kan bruge målte tal. Priser pr. million
tokens sættes med `PRICE_IN_PER_MTOK` og `PRICE_OUT_PER_MTOK` (tjek leverandørens aktuelle prisside).

**Excel uden brugerflade:** `python run_report.py` (demo), `python run_report.py --live`
eller `python run_report.py --live --ai`. Resultatet gemmes i `reports/bid_board.xlsx`.

## Arkitektur

| # | Trin | Fil | Teknik | Hvorfor |
|---|---|---|---|---|
| 1 | Overvågning | `udbud/monitor.py` | TED Search API (DK, DE, SE) | Officielle, åbne data |
| 2 | Screening | `udbud/screening.py` | Regler: CPV, nøgleord på 3 sprog | Gratis og forklarligt; kun relevante udbud koster AI-kald |
| 3 | AI-modul 1: Kravanalyse | `udbud/requirements.py` + `prompts/requirements_agent.md` | Sprogmodel | Fritekst på 3 sprog; hvert krav citeres på originalsproget |
| 4 | AI-modul 2: Bid/no-bid | `udbud/analyst.py` + `prompts/analyst_agent.md` + `udbud/retrieval.py` | Sprogmodel + videnbank (RAG) | Kun svar med kilde; **scoren beregnes af kode** ud fra `config/scoring.yaml` |
| — | Menneske | fane 2 i `app.py` | — | Beslutning + påkrævet begrundelse i `data/decisions.csv` |
| 5 | AI-modul 3: Kvalitetskontrol | `udbud/compliance.py` + `prompts/compliance_agent.md` | Sprogmodel | Tjekker tilbudsudkastet krav for krav; skriver ikke tilbuddet |

- **Videnbank:** `data/videnbank/` (udstyr, referencer, kapacitet, certifikater). Hvad der ikke må ligge der:
  `data/videnbank/README.md`. Prototypen søger med ordmatch; i drift bruges embeddings og en vector-database.
- **Prompt injection:** udbudstekst behandles som data. Demo-udbud DEMO-DE-006 indeholder en skjult
  instruktion og bliver markeret, uden at anbefalingen ændres.
- **Ansvarlig AI:** fane 5 viser vurderingen efter AI-forordningen; fane 4 advarer om automatiseringsbias.

## Indstillinger
- `config/profile.yaml` — virksomhedsprofil: ydelser, lande, CPV-koder, nøgleord, sprog, referencer, timepris.
- `config/scoring.yaml` — vægte og grænser for anbefalingen.
- `prompts/` — prompt-kæden i 3 trin (prompt-biblioteket).

Samme kæde kan bruges til andre opgaver (fx praktiksøgning) ved at skifte profil, kilde og prompts.

## Begrænsninger
- Demo-udbuddene er fiktive; det står i data og i brugerfladen.
- TED-bekendtgørelser indeholder sjældent alle krav: den fulde tekst fra udbudsmaterialet indsættes i appen.
- Vinderchancen er en grov antagelse, ikke en model.

## Test (til porteføljen)

```
python run_tests.py          # regler
python run_tests.py --ai     # AI-agenter (kræver API-nøgle)
```
Kører de 6 demo-udbud to gange og gemmer `reports/testlog.xlsx` med forventet og faktisk resultat,
ja/nej-acceptkriterium, om indlejrede ordrer blev markeret, og hvor ens de to kørsler var.
Kolonnen "Menneskets vurdering" udfylder du selv. AI-kald køres med temperatur 0,2 (`LLM_TEMPERATURE`).

## Offentlig version (Streamlit Community Cloud)

Secrets (Settings → Secrets):
```
OPENAI_API_KEY = "sk-..."
AI_ACCESS_CODE = "en-kode-du-giver-censor"
```
Uden kode kører appen gratis med regler. Sæt også en månedlig udgiftsgrænse hos OpenAI (Billing → Limits).
