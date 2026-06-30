# FIFA World Cup 2026 — Analytics Dashboard

Live analytics, interactive bracket simulator, and match statistics for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page app (~367KB, zero dependencies, zero frameworks) with six tabs:

| Tab | Content |
|---|---|
| **Highlights** | Live goal feed · filters by type/group · scorer hero panel · FIFA.com links |
| **Videos** | Match video cards linking to FIFA highlight pages |
| **Analytics** | snapshot cards (incl. penalties) · collapsible stage sections · match stats panel inside each section |
| **Simulator** | Model-driven R32→Final simulation · Top 4 bar · adjustable weights · quick presets |
| **Groups** | Match predictor with Consensus Pick · 12 group cards with live standings + qualification badges |
| **Bracket** | Interactive knockout bracket — pick every match, AI-fill, download PDF |

---

## Current data state

| Metric | Value |
|---|---|
| Group stage matches | 72 / 72 complete (locked) |
| Match stats | 76 / 76 complete (72 group + M73–M76 knockout) |
| Goals recorded | 223 (all balanced against scores) |
| Knockout results | M73–M76 recorded (R32 in progress). Auto-populated from ESPN · manual fallback via `add_result.py` |
| Penalty shootouts | M74 (Paraguay 4-3) · M75 (Morocco 3-2) — stored as `pens` field, shown as `(2) 1-1 (3)` everywhere |
| Elo ratings | Post-group-stage (Jun 28 2026) — Spain/Argentina 2144, France 2123 |
| FIFA points | Jun 11 2026 baseline + WC delta — Argentina 1907.40 |

### Round of 32 results so far

| Match | Result | Notes |
|---|---|---|
| M73 | S. Africa 0-1 Canada | Eustáquio 92' |
| M74 | Germany 1-1 Paraguay | **Paraguay win 4-3 on pens** |
| M75 | Netherlands 1-1 Morocco | **Morocco win 3-2 on pens** |
| M76 | Brazil 2-1 Japan | Sano (JPN), Casemiro + Martinelli (BRA) |

---

## Repository structure

```
worldcup2026/
├── index.html                 ← Full app (~367KB single file)
├── update_wc.py               ← ONE-STOP update script (use this)
├── update_site.py             ← Lower-level HTML patcher (called by update_wc.py)
├── update_match_stats.py      ← ESPN scraper for scores / goals / stats (+ penalty shootouts)
├── update_rankings.py         ← Elo + FIFA pts + Polymarket updater
├── add_result.py              ← Manual fallback: one command to record + deploy a result
├── validate_scorer_country.py ← Roster-backed scorer↔country validator (uses WC2026_Players.csv)
├── fix_rescrape_match.py       ← One-time helper: clear a match's goals for a clean re-scrape
├── archive/
│   └── worldcup-goals.old.html ← Retired earlier single-file version (kept for reference)
└── data/
    ├── goals.json             ← 223 goals — scorer, minute, type, sequence
    ├── match_stats.json       ← Possession / shots / xG / cards (ESPN/Opta) — 76 entries
    ├── knockout_results.json  ← R32→Final results (+ optional pens field) — ground truth
    ├── matches.json           ← 72 group stage matches + ESPN IDs (ground truth for rankings)
    ├── team_data.json         ← Elo, FIFA pts, form, qual record, squad depth (150 teams)
    ├── groups.json            ← 12 groups + Polymarket odds
    ├── upcoming_fixtures.json ← R32 schedule (ticker only — R32_SCHEDULE drives analytics)
    └── WC2026_Players.csv     ← Official 48-squad roster (1248 players) — authoritative for the validator
```

---

## Two types of updates

### Type 1 — Automatic (GitHub Actions)

Runs on a precise schedule — **3 hours after each match kickoff** so the match is always finished when the action fires. Also has a `*/6` safety net for AET/delay overruns.

```
ESPN scrape → auto-knockout → validate → goals → stats → knockout → upcoming → form → snapshot → stamp → push
```

The `auto-knockout` step reads `match_stats.json` for completed knockout scores and writes them to `knockout_results.json` automatically. Your manually recorded results are **never overwritten**.

### Type 2 — You (after each knockout match)

One command per match after it finishes:

```bash
python add_result.py M73 Canada "S. Africa" 1-0
```

Handles: draws (prompts for penalty winner), duplicate check, validate, update, push — all automatic.

---

## update_wc.py — sections

```bash
python update_wc.py                        # full update (all sections)
python update_wc.py --section validate     # 9 integrity checks + auto-fix
python update_wc.py --section auto-knockout # auto-populate from ESPN match_stats
python update_wc.py --section scrape       # fetch from ESPN
python update_wc.py --section goals        # goals.json → GOALS in index.html
python update_wc.py --section stats        # match_stats.json → MATCH_STATS
python update_wc.py --section knockout     # knockout_results.json → KNOCKOUT_RESULTS
python update_wc.py --section upcoming     # upcoming_fixtures.json → ticker
python update_wc.py --section form         # recompute team form from WC results
python update_wc.py --section snapshot     # update analytics header cards
python update_wc.py --section stamp        # refresh build timestamp
```

---

## Validators

### Built-in validator (`update_wc.py --section validate`)

Runs 10 checks and auto-fixes what it can. Runs automatically inside `add_result.py` and GitHub Actions before every push.

| Check | Auto-fix |
|---|---|
| Goal balance — score must equal number of goal entries | No — manual |
| Duplicate goal IDs | No — manual |
| Goal type validity (open-play/header/penalty/own-goal/free-kick) | No — manual |
| MATCH_STATS home/away swapped vs MATCHES | **Yes — auto-corrects** |
| MATCH_STATS score mismatch vs MATCHES | No — manual |
| MATCH_STATS completeness | No — manual |
| KNOCKOUT_RESULTS winner in [home, away] | No — manual |
| goals.json in sync with index.html | No — run `--section goals` |
| Sequential goal IDs (gaps are informational only) | — informational |
| **Scorer ↔ country consistency (history-based)** | No — manual |

The scorer↔country check derives each scorer's country from running-score deltas and flags any goal crediting a known scorer to a different country. **Limitation:** it can only catch a player mis-credited *after* they've scored correctly before — it cannot catch a brand-new scorer's first goal being mis-keyed. That gap is covered by the roster-backed validator below.

### Roster-backed validator (`validate_scorer_country.py`)

A stronger, standalone check that uses the **official squad roster** (`data/WC2026_Players.csv`, `COUNTRY` + `PLAYER_NAME` columns) instead of goal history. Because it knows every player's real country up front, it **also catches a brand-new scorer's first goal** being credited to the wrong team — the class of bug the history-based check misses (e.g. a Japan player's goal credited to Brazil).

```bash
python validate_scorer_country.py            # report
python validate_scorer_country.py --strict   # exit 1 on any mismatch (for CI / pre-push)
```

How it matches: derives `F. Lastname` from the roster, with full **case + accent normalization**, compound-surname handling (matches each word of `VARGAS MARTINEZ`), hyphen/spacing tolerance (`Al-Amri` ↔ `ALAMRI`), name-on-shirt fallback, country-name aliases (`IR Iran` → Iran, `Cabo Verde` → Cape Verde), and a small explicit alias map for irreducible spelling differences (`Vinicius Jr.`, `M. Al-Taamari`). Roster file is read as cp1252/UTF-8 and tab- or comma-delimited automatically.

On its first run against the real roster it caught two genuine attribution bugs — **m39 (Pina, Uruguay-Cape Verde)** and **m40 (Surman, NZ-Egypt)** — where the home/away running scores were inverted.

---

## Match Analytics — collapsible sections

Six sections stack vertically. Cards are identical to the original design (flag · team · score · team · flag in a 4-col grid). The group stage is **permanently locked** — no new cards ever appear there.

| Section | Behaviour |
|---|---|
| ⚽ Group Stage | 🔒 Locked — 72/72 complete, always collapsed |
| ⚡ Round of 32 | **Always open** — gold header (active stage). Uses `R32_SCHEDULE` (frozen — played matches never disappear even when update scripts run) |
| 🏆 Round of 16 | Opens once first R16 result recorded. TBD cards resolve as R32 winners known |
| ⚡ Quarter-Finals | Opens once first QF result recorded |
| 🏆 Semi-Finals | Opens once first SF result recorded |
| 🎉 3rd Place & Final | Opens once SF complete |

**Tap a played card** → full stats panel (possession, shots, xG, discipline) injects inside that same section and scrolls into view. Works for both group stage (m1–m72) and knockout cards (M73+) — the id is normalised to lowercase so `showMatchStats('M73')` correctly looks up `MATCH_STATS['m73']`.

**Key design decision:** The R32 analytics section reads from `R32_SCHEDULE` (a frozen 16-entry constant), not from `UPCOMING_FIXTURES`. This means played R32 matches always stay visible as result cards even when `update_wc.py --section upcoming` removes them from the ticker.

---

## Matches played card

The "Matches Played" snapshot card shows a live breakdown:

```
76 of 104   72 group · 4 R32 · 0 R16 · 0 QF · 0 SF · 0 3rd · 0 Final
```

- Group count is capped at m1–m72 (knockout matches written to MATCH_STATS by ESPN are excluded)
- Knockout count reads from `KNOCKOUT_RESULTS` winners only
- Total = group + knockout played

---

## Penalty shootouts

Knockout matches drawn after regulation are decided on penalties. The pipeline handles this end-to-end:

- **Scraper** (`update_match_stats.py`) reads ESPN's `shootoutScore` for each team. When regulation is level and shootout scores exist, the winner is the shootout victor and a `pens` field (home-away order, e.g. `"3-4"`) is recorded. The shootout scores flip correctly when ESPN's home/away orientation differs from the fixture.
- **Schema** — `knockout_results.json` entry gains an optional `pens` field; `winner` stays authoritative (team name). Matches decided in regulation simply omit `pens`.
- **Display** — the score shows the shootout in parentheses beside each team, **everywhere a result appears**: bracket cards, video cards, the scrolling ticker (gold bar), and the match-stats panel header.

```
Netherlands (2) 1-1 (3) Morocco
```

A single helper, `fmtScoreWithPens(matchId, score)`, looks up the shootout from `KNOCKOUT_RESULTS` and formats it consistently. Per-goal running scores (goal feed / hero panel) intentionally show the score *at the moment of the goal* and do not append pens.

- `winner` advances via `resolveKnockoutTeam('W74')` — unaffected by penalties
- The Simulator overrides simulated rounds with **actual** completed results (`applyActual`), so eliminated teams drop out of R16+ and the real winner advances

---

## Rankings updater (`update_rankings.py`)

Runs daily at 06:00 UTC via `daily-rankings.yml`. Updates:

- **Elo** — live from eloratings.net (via footballratings.org), falls back to hardcoded post-group-stage values (Jun 28 2026) if live fetch fails
- **FIFA pts** — frozen at Jun 11 2026 per FIFA (next update Jul 20). WC match delta applied using the FIFA Elo formula (I=50)
- **Polymarket** — live win probabilities from gamma-api.polymarket.com

### Rankings validator (built-in)

`WC_RESULTS` is **never hardcoded**. It is built dynamically at runtime from:

- `data/matches.json` → group stage (id ≤ 72, valid score required)
- `data/knockout_results.json` → R32 through Final

Before calculating, `validate_wc_results()` checks:
- No duplicate match entries
- All team names recognisable (warns on unknown teams)
- All results are 0.0 / 0.5 / 1.0 (valid Elo values)
- Validation failure = `sys.exit(1)` — never silently wrong

**Idempotent:** running the script 5× gives the same result as running it once. AET/penalty draws are handled via `RESULT_OVERRIDES` dict — explicit and auditable.

```python
# To record a penalty shootout result:
RESULT_OVERRIDES = {
    ("Argentina", "France"): 1.0,  # Argentina won on pens after 3-3 AET
}
```

---

## Bracket simulator

Follows the **official FIFA bracket** (M73–M104) exactly:

- `runSimulation()` resolves each round via `(BSIM_R16||[]).map()` — `fH:'W74'` means home = winner of M74
- `bsimAiFill()` propagates picks through correct slots at every stage (R32→R16→QF→SF→FINAL)
- `bsimEnforceIntegrity()` called after AI fill to catch any slot inconsistencies
- PDF: html2canvas direct capture of live bracket, A3 landscape, centred both axes

---

## Upcoming fixtures ticker

- Reads from `getKnownFixtures()` — single source of truth for both ticker and analytics
- Played R32 matches removed automatically once `KNOCKOUT_RESULTS[matchId].winner` exists
- R16 fixtures appear only when both R32 winners are resolved (no Wxx placeholders)
- Auto-refreshes every 60s + immediately on `visibilitychange` (returning to tab)
- `UPCOMING_FIXTURES` drives the ticker (filtered). `R32_SCHEDULE` drives analytics (frozen).

---

## GitHub Actions schedule

| Workflow | Trigger | What it does |
|---|---|---|
| `auto-update.yml` | 33 match-timed crons + `*/6` safety net | Scrape → auto-knockout → validate → sync all sections → push |
| `daily-rankings.yml` | 06:00 UTC daily | Update Elo, FIFA pts delta, Polymarket odds |

Crons fire exactly **3 hours after each match kickoff** (converted to UTC). The `*/6` fallback catches AET/penalty overruns.

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

Goal type classification uses a 3-layer system: ESPN auto-detect → preserve existing types on re-scrape → `GOAL_TYPE_OVERRIDES` (hardcoded map, never reset by scraping).

---

## Prediction model

```
score(team) = form×0.35 + (elo/2200)×0.20 + (squadDepth/100)×0.15
            + (fifaPts/1900)×0.15 + qualGDpg×0.10 + (exp/10)×0.05

P(win) = 1 / (1 + exp(−8 × (score_A − score_B)))
draw%  = max(0.12, 0.30 − eloGap/2800)
```

Form is recalculated after each matchday:
```
base = (qualW + 0.5×qualD) / total_qual_games   (or wc_avg if no qual data)
form = base×0.40 + wc_avg×0.60    (floor: 0.10)
```

Post-group-stage Elo (Jun 28 2026): Spain/Argentina 2144 · France 2123 · England 2038 · Brazil 2009

---

## Browser console checks

```javascript
// Data state
console.table({
  matches:   MATCHES.length,                       // 72
  goals:     GOALS.length,                         // 223
  stats:     Object.keys(MATCH_STATS).length,      // 76 (group + M73–M76)
  knockout:  Object.keys(KNOCKOUT_RESULTS).length, // grows with results
  r32sched:  R32_SCHEDULE.length,                  // 16 (frozen)
  upcoming:  UPCOMING_FIXTURES.length,             // ≤16 (filtered)
})

// Check bracket resolution
resolveKnockoutTeam('W74')   // → real team name once M74 played

// Fixtures in ticker (played filtered out)
getKnownFixtures().map(f => f.matchId + ': ' + f.home + ' vs ' + f.away)

// Argentina post-WC values
TEAM_DATA['Argentina'].elo        // 2144
TEAM_DATA['Argentina'].fifaPts    // 1907.40
TEAM_DATA['Argentina'].form       // 1.0 (3W group stage)
```

---

## Push workflow

```bash
# After a knockout result
python add_result.py M73 Canada "S. Africa" 1-0
# That's it — validates, updates, pushes automatically

# If you need to push manually
python update_wc.py --section validate
git fetch origin && git reset --soft origin/main
git add index.html data/
git commit -m "update: R32 results"
git push origin main

# If push rejected (Action committed first)
git pull origin main --no-rebase && git push origin main
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS — zero frameworks, zero build step |
| Data | JSON files in `data/` — GitHub as a free database |
| Hosting | GitHub Pages |
| Match data | ESPN API (no auth required) |
| Rankings | eloratings.net (via footballratings.org) + FIFA hardcoded + Polymarket |
| PDF export | jsPDF + html2canvas (CDN, deferred) |
| Flags | flagcdn.com |
| Charts | Pure SVG/HTML — no chart library |
| CI/CD | GitHub Actions — free tier, 33 match-timed triggers |
