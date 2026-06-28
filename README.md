# FIFA World Cup 2026 — Analytics Dashboard

Live analytics, interactive bracket simulator, and match statistics for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page app (~358KB, zero dependencies, zero frameworks) with six tabs:

| Tab | Content |
|---|---|
| **Highlights** | Live goal feed · filters by type/group · scorer hero panel · FIFA.com links |
| **Videos** | Match video cards linking to FIFA highlight pages |
| **Analytics** | 8 snapshot cards · period chart · goal-type donut · top scorers · collapsible match stats selector |
| **Simulator** | Model-driven R32→Final simulation · Top 4 bar · adjustable weights · quick presets |
| **Groups** | Match predictor with Consensus Pick · 12 group cards with live standings + qualification badges |
| **Bracket** | Interactive knockout bracket — pick every match, AI-fill, download PDF |

---

## Current data state

| Metric | Value |
|---|---|
| Group stage matches | 72 / 72 complete |
| Match stats | 72 / 72 complete |
| Goals recorded | 215 (all balanced) |
| Knockout results | Populated via `data/knockout_results.json` as games finish |

---

## Repository structure

```
worldcup2026/
├── index.html                 ← Full app (~358KB single file)
├── update_wc.py               ← ONE-STOP update script (use this)
├── update_site.py             ← Lower-level HTML patcher (called by update_wc.py)
├── update_match_stats.py      ← ESPN scraper for scores / goals / stats
└── data/
    ├── goals.json             ← 215 goals — scorer, minute, type, sequence
    ├── match_stats.json       ← Possession / shots / xG / cards (ESPN/Opta)
    ├── knockout_results.json  ← R32→Final results (add after each game)
    ├── matches.json           ← Match metadata + ESPN IDs
    ├── team_data.json         ← Elo, FIFA pts, form, qual record, squad depth
    ├── groups.json            ← 12 groups + Polymarket odds
    └── upcoming_fixtures.json ← R32 schedule with ET kick-off times
```

---

## update_wc.py — the main update script

```bash
python update_wc.py                      # full update (all sections in order)
python update_wc.py --section validate   # data integrity check + auto-fix
python update_wc.py --section scrape     # fetch latest from ESPN
python update_wc.py --section goals      # goals.json → GOALS in index.html
python update_wc.py --section stats      # match_stats.json → MATCH_STATS
python update_wc.py --section knockout   # knockout_results.json → KNOCKOUT_RESULTS
python update_wc.py --section upcoming   # upcoming_fixtures.json → ticker
python update_wc.py --section form       # recompute team form
python update_wc.py --section snapshot   # update analytics header cards
python update_wc.py --section stamp      # refresh build timestamp
```

### Workflow after each knockout match

```bash
# 1. Add result to data/knockout_results.json
# {"M73": {"home":"S. Africa","away":"Canada","score":"1-3","winner":"Canada"}}

# 2. Validate and update
python update_wc.py --section validate
python update_wc.py --section knockout

# 3. Push
git add index.html data/knockout_results.json
git commit -m "update: M73 Canada win"
git push origin main
```

The site will automatically:
- Remove the played match from the upcoming ticker
- Show the R16 fixture once both R32 winners for that slot are known
- Resolve TBD cards in the R16/QF/SF sections of match analytics

---

## Validator (`--section validate`)

Runs 9 checks and auto-fixes what it can. Always run before pushing.

| Check | Auto-fix |
|---|---|
| Goal balance — score must equal number of goal entries | No — manual |
| Duplicate goal IDs | No — manual |
| Goal type validity (open-play/header/penalty/own-goal/free-kick) | No — manual |
| MATCH_STATS home/away swapped vs MATCHES | **Yes — auto-corrects** |
| MATCH_STATS score mismatch vs MATCHES | No — manual |
| MATCH_STATS completeness (72/72) | No — manual |
| KNOCKOUT_RESULTS winner in [home, away] | No — manual |
| goals.json in sync with index.html | No — run `--section goals` |
| Sequential goal IDs (gaps are informational only) | — |

The validator found and auto-fixed m18 (Norway/Iraq) and m24 (Colombia/Uzbekistan)
having home/away swapped in MATCH_STATS — both corrected.

---

## Match Analytics — collapsible sections

The match selector has six collapsible sections stacked vertically.
Each section uses the same card design as before (flag · team · score · team · flag).

| Section | Opens when |
|---|---|
| Group Stage | During group stage |
| Round of 32 | Active now — gold header |
| Round of 16 | First R16 result recorded |
| Quarter-Finals | First QF result recorded |
| Semi-Finals | First SF result recorded |
| 3rd Place and Final | SF complete |

Tap a played card → full stats panel (possession, shots, xG, discipline) opens
inside that same section, below the cards grid.
Unplayed matches show as dashed cards. TBD slots resolve to real team names
once KNOCKOUT_RESULTS is populated.

---

## Bracket simulator — bracket integrity

The simulator follows the official FIFA bracket pairings:

- `runSimulation()` resolves each round via the BSIM arrays
  (BSIM_R16, BSIM_QF, BSIM_SF, BSIM_FINAL) not sequential array pairs
- Each BSIM entry references winner slots: `fH:"W74"` means home = winner of M74
- `bsimAiFill()` propagates picks through the correct slots at each stage
- Argentina (M86 left half) cannot meet Japan (M76 right half) until the Final

PDF export captures the live bracket at natural size, A3 landscape, centred.

---

## Upcoming fixtures ticker

- Shows only unplayed R32 matches (disappear once KNOCKOUT_RESULTS has winner)
- R16 fixtures appear only once both R32 winners for that slot are known
- Auto-refreshes every 60 seconds and on tab visibility change
- `getKnownFixtures()` is the single source of truth for both ticker and analytics

---

## Goal data model

```javascript
{
  id: 42, matchId: "m27", home: "Canada", away: "Qatar",
  scorer: "D. Davies", flag: "", minute: 12,
  type: "open-play",  // open-play | header | penalty | own-goal | free-kick
  phase: "Group F", score: "1-0", desc: ""
}
```

### Goal type classification (3-layer system)

1. ESPN auto-detect — reads goal-type text and play description
2. Preserve — existing free-kick/header types survive re-scrape
3. GOAL_TYPE_OVERRIDES in update_match_stats.py — hardcoded map, never reset

To add a manual override:
```python
GOAL_TYPE_OVERRIDES = {
    ("m39", "K. Pina",   21): "free-kick",
    ("m27", "N. Saliba", 68): "free-kick",
    # add new entries here
}
```

---

## Prediction model

```
score(team) = form×0.35 + (elo/2200)×0.20 + (squadDepth/100)×0.15
            + (fifaPts/1900)×0.15 + qualGDpg×0.10 + (exp/10)×0.05

P(win) = 1 / (1 + exp(−8 × (score_A − score_B)))
draw%  = max(0.12, 0.30 − eloGap/2800)
```

Form:
```
base = (qualW + 0.5×qualD) / total_qual_games
form = base×0.40 + wc_avg×0.60    (win=1.0, draw=0.5, loss=0.0, floor=0.10)
```

---

## Browser console checks

```javascript
console.table({
  matches:   MATCHES.length,                      // 72
  goals:     GOALS.length,                        // 215
  stats:     Object.keys(MATCH_STATS).length,     // 72
  knockout:  Object.keys(KNOCKOUT_RESULTS).length, // grows with results
  upcoming:  UPCOMING_FIXTURES.length,            // 16 (R32 fixtures)
  r16:       R16_FIXTURES.length,                 // 8
})

// Check bracket resolution
resolveKnockoutTeam("W74")  // returns team name once M74 is played

// Check known fixtures (played ones filtered out)
getKnownFixtures().map(f => f.home + " vs " + f.away)
```

---

## Push workflow

```bash
python update_wc.py --section validate

git fetch origin && git reset --soft origin/main
git add index.html data/
git commit -m "update: R32 results matchday 1"
git push origin main
```

If push rejected (Action committed first):
```bash
git pull origin main --no-rebase
git push origin main
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS — zero frameworks, zero build step |
| Data | JSON files in data/ — GitHub as a free database |
| Hosting | GitHub Pages |
| Match data | ESPN API (no auth required) |
| PDF export | jsPDF + html2canvas (CDN, deferred) |
| Flags | flagcdn.com |
| Charts | Pure SVG/HTML — no chart library |
