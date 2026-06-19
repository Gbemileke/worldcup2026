# 2026 FIFA World Cup Analytics Dashboard

Live analytics dashboard for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page analytics app with five tabs:

| Tab | Content |
|---|---|
| **Analytics** | 8 snapshot cards · Goals by period chart · Goal type donut · Top scorers · Match stats selector |
| **Highlights** | Live goal feed with filters · Goal hero panel with scorer/minute/type/group detail cards · FIFA.com links |
| **Videos** | Match video cards linking to FIFA highlight pages |
| **Bracket** | R32 bracket simulation · Top 4 predictions · Model weight settings · Quick presets |
| **Groups** | Match predictor · 12 group tables · Model vs Polymarket comparison |

---

## Repository structure

```
worldcup2026/
├── index.html                    ← Entire app (~210KB single HTML file)
├── data/
│   ├── matches.json              ← 28 matches + scores + espnId + FIFA links
│   ├── goals.json                ← 89 goals + scorers + minute + type + descriptions
│   ├── match_stats.json          ← Possession / shots / xG / cards per match (ESPN)
│   ├── team_data.json            ← 48 teams: Elo, FIFA pts, form, qual record, squad depth
│   ├── groups.json               ← 12 groups + Polymarket odds
│   └── upcoming_fixtures.json    ← 42 remaining fixtures with CST kick-off times
├── update_site.py                ← Master rebuild: reads all JSON → writes index.html
├── update_match_stats.py         ← Fetches ESPN scoreboard + summary endpoints
├── update_rankings.py            ← Updates Elo / FIFA rankings daily
├── update_odds.py                ← Updates Polymarket group odds (manual)
├── add_match.py                  ← Manually add a completed match
└── .github/workflows/
    ├── auto-update.yml           ← Every 3 hours: ESPN match data + form + rebuild
    ├── daily-rankings.yml        ← Daily 6am UTC: Elo + FIFA rankings
    └── daily-odds.yml            ← Manual trigger: Polymarket odds
```

---

## Automation — what updates automatically

### `auto-update.yml` — every 3 hours

```
Step 1: update_match_stats.py
  ├── ESPN scoreboard  → new match scores, goals, espnId per match
  └── ESPN summary     → possession, shots, SOT, corners, fouls, saves (Opta data)
        Goal validation: running score must match final before saving
        (prevents wrong attribution if ESPN homeAway is incorrect)

Step 2: update_site.py --section form
  └── Recomputes team form:
        base_form = (qualW + 0.5×qualD) / (qualW + qualD + qualL)
        new_form  = base_form × 0.40 + wc_avg × 0.60
        floor = 10% — no team ever shows 0%
        Idempotent: runs same result every time

Step 3: update_site.py (full rebuild)
  ├── matches    → goal feed, video cards, ticker
  ├── goals      → highlight feed, scorers, charts
  ├── stats      → match analytics (ESPN labels, xG)
  ├── groups     → group prediction odds
  ├── upcoming   → ticker + predictor dropdown
  ├── sync       → removes completed games from upcoming
  ├── snapshot   → 8 cards with tooltips
  └── form       → team form in bracket / predictor

Step 4: git commit + push → GitHub Pages live in ~2 minutes
```

### `daily-rankings.yml` — 6am UTC daily
```
update_rankings.py → Elo ratings + FIFA ranking points → team_data.json + index.html
```

### `daily-odds.yml` — manual trigger
```
update_odds.py → Polymarket group odds → groups.json + index.html
```

---

## Features

### 8 Snapshot Cards (Analytics tab)
Cards scroll horizontally. Order:

| # | Card | Size | Notes |
|---|---|---|---|
| 1 | Matches Played | 200px | `27 of 104` with goal type breakdown sub-text |
| 2 | Total Goals | 200px | Per-match average |
| 3 | Penalties | 200px | `in N matches` — hover: `Switzerland (Embolo) vs Qatar` |
| 4 | Own Goals | 200px | `in N matches` — hover: `Paraguay (Bobadilla) vs USA` |
| 5 | Red Cards | 200px | `in N matches` — hover: `Mexico (1) vs S. Africa` etc |
| 6 | Biggest Win | 200px | Germany 8-1 Curaçao |
| 7 | Top Scorer | 200px | Single: `L. Messi - Argentina` · Tied: hover tooltip |
| 8 | All-Time WC Record Scorer | 240px | **NEW RECORD!** flashing gold when broken |

Last 2 cards (Matches Played override + All-Time Record) are 240px wide.

### Match Predictor (Groups tab)
- Dropdown of all remaining group stage fixtures
- **Left panel:** 6 model input factors with weights (form-heavy)
- **Right panel:** Model vs Polymarket win probabilities (Team A / Draw / Team B)
- **Favourite bar:** 3-segment green|gray|blue with % labels
- Fixed weights: Form 35% · Elo 20% · Squad 15% · FIFA pts 15% · Qual GD 10% · Exp 5%

### Highlights tab
- Goal feed with ALL / OPEN PLAY / HEADER / PENALTY / OWN GOAL filters
- Hero panel: match on one line (`Mexico 1-0 S. Africa`) · Scorer · Minute · Type · Group (4 detail cards)
- Description text first, then video placeholder below
- FIFA.com highlight link per match

### Tooltip system
- JS tooltip (not CSS) — appends to `#tip-popup` div, avoids overflow clipping
- `mouseover` with `closest('.has-tip')` — follows cursor
- Mobile: disabled via `maxTouchPoints` check
- Format: `Country (Player) vs Opponent`

---

## Form model

```
base_form = (qualW + 0.5 × qualD) / (qualW + qualD + qualL)
new_form  = base_form × 0.40 + wc_results_avg × 0.60

win  → wc_result = 1.0
draw → wc_result = 0.5
loss → wc_result = 0.0
floor = 0.10 (no team ever shows 0%)
```

This is **idempotent** — the qualifying record never changes, so running `update_form` multiple times always gives the same result. Previously the function used the *current stored form* as the baseline, causing form to decay toward 50% on every Action run.

### Sample values after MD2 (Jun 19, 2026)

| Team | Qual record | WC results | Form |
|---|---|---|---|
| Argentina | CONMEBOL 1st | W | 100% |
| England | UEFA 10W-0D-0L | W | 100% |
| Mexico | CONCACAF 1st | W, W | 100% |
| Brazil | CONMEBOL 14W-3D-1L | D | 64% |
| Spain | UEFA 8W-2D-0L | D | 66% |
| Portugal | UEFA 9W-1D-0L | D | 68% |
| Morocco | CAF 6W-1D-1L | D | 63% |
| Croatia | UEFA 5W-2D-3L | L | 29% |

---

## Match statistics

- **Source:** ESPN summary endpoint — `site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={espnId}`
- **Labels match ESPN exactly:** Shot Attempts · Shots on Goal · Corner Kicks · Fouls · Saves
- **Extra stats:** xG · Yellow Cards · Red Cards · Offsides
- **xG:** Real ESPN/Opta data where available; calculated from SOT for others
- **espnId** stored per match in `matches.json` for re-fetching

### Goal attribution safety
`update_match_stats.py` validates that the running goal tally matches the ESPN final score before saving. If ESPN returns wrong `homeAway` values (as happened with Canada vs Qatar), goals are **skipped entirely** rather than saved with wrong attribution. Manual add via `add_match.py` is then used.

---

## Prediction model

### Match predictor (Groups tab) — fixed weights

```
score(team) = form × 0.35 + (elo/2200) × 0.20 + (squadDepth/100) × 0.15
            + (fifaPts/1900) × 0.15 + qualGDpg × 0.10 + (exp/10) × 0.05

P(win) = 1 / (1 + e^(−8 × (score_A − score_B)))
draw%  = max(0.12, 0.30 − eloGap/2800)
```

### Bracket simulator (Bracket tab) — adjustable weights

| Preset | Elo | Form | Qual | Squad | FIFA | Exp |
|---|---|---|---|---|---|---|
| Default | 30% | 20% | 10% | 20% | 15% | 5% |
| Elo pure | 70% | 20% | 10% | 0% | 0% | 0% |
| Form heavy | 30% | 40% | 20% | 5% | 0% | 5% |
| Squad heavy | 30% | 20% | 5% | 35% | 5% | 5% |
| Equal | 17% | 17% | 17% | 17% | 16% | 16% |

---

## Data sources

| Data | Source | Frequency |
|---|---|---|
| Match scores + goals | ESPN scoreboard API | Every 3 hours (auto) |
| Match statistics | ESPN summary API (Opta) | Every 3 hours (auto) |
| Upcoming fixtures | football-data.org API | Every 3 hours (auto) |
| Team form | Computed from qual record + WC results | Every 3 hours (auto) |
| Elo ratings | clubelo.com | Daily (auto) |
| FIFA rankings | FIFA.com | Daily (auto) |
| Group odds (Polymarket) | polymarket.com | Manual after each matchday |

---

## GitHub secrets required

Go to **Settings → Secrets → Actions**:

| Secret | Used by | Get it at |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | `update_match_stats.py` | football-data.org (free tier) |

---

## Tournament snapshot (Jun 19, 2026)

- **28 matches** played · MD1 complete · MD2 complete
- **89 goals** · 3.18 per match · 64 open play · 14 headers · 6 penalties · 5 OGs
- **Joint Top Scorers:** L. Messi (Argentina) & J. David (Canada) — 3 goals each
- **Red cards:** 6 total across 3 matches
  - Mexico 1 · S. Africa 2 (opener)
  - Bosnia 1 vs Switzerland
  - Qatar 2 vs Canada (nine-man finish)
- **Biggest win:** Canada 6-0 Qatar — J. David hat trick · xG 4.54-0.18
- **Mexico first R32:** First team to book knockout spot after 2 wins
- **42 remaining fixtures** through Jul 2

---

## update_site.py — section reference

```bash
python update_site.py                      # rebuild everything
python update_site.py --section matches    # matches array only
python update_site.py --section goals      # goals feed only
python update_site.py --section stats      # match stats panel only
python update_site.py --section groups     # group odds only
python update_site.py --section upcoming   # ticker fixtures only
python update_site.py --section sync       # remove completed from upcoming
python update_site.py --section snapshot   # snapshot cards only
python update_site.py --section form       # team form from qual record + WC results
```

---

## Browser console verification

```javascript
console.table({
  matches:    MATCHES.length,        // expect 28+
  goals:      GOALS.length,          // expect 89+
  matchStats: Object.keys(MATCH_STATS).length,
  teams:      Object.keys(TEAM_DATA).length,  // expect 48
  groups:     Object.keys(GROUPS).length,     // expect 12
  upcoming:   UPCOMING_FIXTURES.length,
  predictor:  typeof buildMatchPredictor,     // 'function'
})
```

---

## Known issues / watchlist

- **ESPN goal details:** ESPN `details[]` array sometimes returns empty for scorer info. When this happens, goal validation skips the match — manual add required via `add_match.py`. Affected: m28 Mexico vs S. Korea (L. Romo 50').
- **Yellow card totals:** Partially estimated for matches where ESPN summary didn't return card data. Red card totals are fully verified.
- **xG:** Verified from Opta for m12 (Sweden 1.51-0.30) and m23 (Ghana 1.31-0.73). All other matches use SOT-based estimate until ESPN summary returns real xG.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JavaScript — zero frameworks, no build step |
| Data | JSON files in `data/` — GitHub as a free database |
| Hosting | GitHub Pages (free) |
| Automation | GitHub Actions (free tier, 3-hour schedule) |
| Match API | ESPN (no auth) + football-data.org (free tier) |
| Charts | Pure SVG/HTML — no chart library |
