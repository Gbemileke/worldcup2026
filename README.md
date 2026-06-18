# 2026 FIFA World Cup Analytics Dashboard

Live analytics dashboard for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page analytics app with five tabs:

| Tab | Content |
|---|---|
| **Analytics** | Snapshot cards · Goals by period chart · Goal type donut · Top scorers · Match stats selector |
| **Highlights** | Live goal feed with filters · Goal hero panel with FIFA.com links |
| **Videos** | Match video cards linking to FIFA highlight pages |
| **Bracket** | R32 bracket simulation · Top 4 predictions · Model weight settings · Quick presets |
| **Groups** | Match predictor · 12 group tables · Model vs Polymarket vs FanDuel comparison |

---

## Repository structure

```
worldcup2026/
├── index.html                    ← Entire app (~200KB single HTML file)
├── data/
│   ├── matches.json              ← All 26 matches + scores + espnId + FIFA links
│   ├── goals.json                ← 82 goals + scorers + minute + type + descriptions
│   ├── match_stats.json          ← Possession / shots / xG / cards per match (ESPN)
│   ├── team_data.json            ← 48 teams: Elo, FIFA pts, live form, squad depth
│   ├── groups.json               ← 12 groups + Polymarket / FanDuel odds
│   └── upcoming_fixtures.json    ← All remaining fixtures with CST kick-off times
├── update_site.py                ← Master rebuild: reads all JSON → writes index.html
├── update_match_stats.py         ← Fetches from ESPN scoreboard + summary endpoints
├── update_rankings.py            ← Updates Elo / FIFA rankings daily
├── update_odds.py                ← Updates Polymarket / FanDuel group odds (manual)
├── generate_descriptions.py      ← Template-based goal descriptions
├── add_match.py                  ← Manually add a completed match
└── .github/workflows/
    ├── auto-update.yml           ← Every 3 hours: ESPN match data + form + rebuild
    ├── daily-rankings.yml        ← Daily 6am UTC: Elo + FIFA rankings
    └── daily-odds.yml            ← Manual trigger: Polymarket + FanDuel odds
```

---

## Automation — what updates automatically

### `auto-update.yml` — every 3 hours

```
Step 1: update_match_stats.py
  ├── ESPN scoreboard  → scores, goals, espnId stored per match
  └── ESPN summary     → possession, shots, SOT, corners, fouls, saves (real Opta data)

Step 2: update_site.py --section form
  └── recomputes team form from WC results (floor: 10%)

Step 3: update_site.py (full rebuild)
  ├── matches    → goal feed, video cards, ticker results
  ├── goals      → highlight feed, scorers table, charts
  ├── stats      → match analytics selector (ESPN labels)
  ├── groups     → group prediction odds
  ├── upcoming   → scrolling ticker + predictor dropdown
  ├── sync       → removes completed games from upcoming
  ├── snapshot   → cards: goals, OGs, pens (in N matches + hover tooltip)
  └── form       → team form values in bracket / group predictions

Step 4: git commit + push → GitHub Pages live in ~2 minutes
```

### `daily-rankings.yml` — 6am UTC daily
```
update_rankings.py → Elo ratings + FIFA ranking points → team_data.json + index.html
```

### `daily-odds.yml` — manual trigger
```
update_odds.py → Polymarket / FanDuel group odds → groups.json + index.html
```

---

## Features

### Match Predictor (Groups tab)
- Dropdown of all remaining group stage fixtures
- **Left panel:** 6 model input factors with weights (form-heavy: 35% form)
- **Right panel:** Model vs Polymarket win probabilities (Team A / Draw / Team B)
- **Favourite bar:** 3-segment green|gray|blue with % labels under each segment
- Fixed weights: Form 35% · Elo 20% · Squad 15% · FIFA pts 15% · Qual GD 10% · Exp 5%
- Neutral venue — no home/away advantage applied

### Snapshot Cards Tooltip
- Penalties card: shows `in N matches` — hover reveals `Switzerland (Embolo) vs Qatar`
- Own Goals card: shows `in N matches` — hover reveals `Paraguay (Bobadilla) vs USA`
- JS tooltip (not CSS) — appends to body, avoids overflow clipping
- Mobile: tooltip hidden (no hover on touch devices)

### Match Statistics
- Source: **ESPN summary endpoint** (`site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={espnId}`)
- Labels match ESPN exactly: Shot Attempts, Shots on Goal, Corner Kicks, Fouls, Saves
- Extra: Yellow Cards, Red Cards, Offsides
- espnId stored per match in matches.json for re-fetching

---

## Prediction model

### Match probability formula

```
score(team) = (elo / 2200      × W.elo)   +
              (form             × W.form)  +
              (qualGDpg         × W.qual)  +
              (squadDepth / 100 × W.squad) +
              (fifaPts / 1900   × W.fifa)  +
              (exp / 10         × W.exp)

P(A wins) = 1 / (1 + e^(−8 × (score_A − score_B)))
```

### Default weights (Bracket tab)

| Factor | Weight |
|---|---|
| Elo rating | 30% |
| Squad depth | 20% |
| Recent form | 20% |
| FIFA points | 15% |
| Qualifying GD | 10% |
| Experience | 5% |

### Match Predictor weights (fixed, form-heavy)

| Factor | Weight |
|---|---|
| Form | **35%** |
| FIFA Rank (Elo) | 20% |
| Squad depth | 15% |
| FIFA points | 15% |
| Qualifying GD | 10% |
| Experience | 5% |

### Team form — live from WC results

```
new_form = max(0.10, old_form × 0.4 + wc_result × 0.6)

win  → wc_result = 1.0
draw → wc_result = 0.5
loss → wc_result = 0.0
```

Floor of 10% — no team ever shows 0% form. Updates every 3 hours automatically.

### Model presets

| Preset | Elo | Form | Qual | Squad | FIFA | Exp |
|---|---|---|---|---|---|---|
| Default | 30% | 20% | 10% | 20% | 15% | 5% |
| Elo pure | 70% | 20% | 10% | 0% | 0% | 0% |
| Form heavy | 30% | 40% | 20% | 5% | 0% | 5% |
| Squad heavy | 30% | 20% | 5% | 35% | 5% | 5% |
| Qual heavy | 30% | 20% | 30% | 5% | 10% | 5% |
| Equal | 17% | 17% | 17% | 17% | 16% | 16% |

---

## Data sources

| Data | Source | Updated |
|---|---|---|
| Match scores + goals | ESPN scoreboard API | Every 3 hours (auto) |
| Match statistics | ESPN summary API (Opta) | Every 3 hours (auto) |
| Upcoming fixtures | football-data.org API | Every 3 hours (auto) |
| Team form | Computed from WC results | Every 3 hours (auto) |
| Elo ratings | clubelo.com | Daily (auto) |
| FIFA rankings | FIFA.com | Daily (auto) |
| Group odds (Polymarket) | polymarket.com | Manual after each matchday |
| Group odds (FanDuel) | FanDuel via Fox Sports | Manual after each matchday |
| Qualifying records | Pre-loaded | Static |
| Squad depth | Pre-loaded | Static |
| FIFA highlight links | Manual | After each match |

---

## GitHub secrets required

Go to **Settings → Secrets → Actions** and add:

| Secret | Used by | Get it at |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | `update_match_stats.py` (upcoming fixtures) | football-data.org (free) |

---

## Tournament snapshot (Jun 18, 2026)

- **26 matches** played · MD1 complete · MD2 in progress
- **82 goals** · 3.15 per match average
- **Top scorer:** L. Messi — 3 goals
- **Own goals:** 4 — Bobadilla (Paraguay), Hany (Egypt), Hussein (Iraq), Al-Arab (Jordan)
- **Penalties:** 6 — Embolo (Switzerland), Havertz (Germany), Arnautovic (Austria), Kane (England), Mokoena (S. Africa), Xhaka (Switzerland)
- **Biggest match:** Germany 7–1 Curaçao
- **Next up:** 45 remaining group stage fixtures through Jul 2

---

## update_site.py — individual sections

```bash
python update_site.py                      # rebuild everything
python update_site.py --section matches    # matches array only
python update_site.py --section goals      # goals feed only
python update_site.py --section stats      # match stats panel only
python update_site.py --section groups     # group odds only
python update_site.py --section upcoming   # ticker fixtures only
python update_site.py --section sync       # remove completed from upcoming
python update_site.py --section snapshot   # analytics snapshot cards only
python update_site.py --section form       # team form from WC results only
```

---

## Browser console verification

```javascript
console.table({
  matches:    MATCHES.length,        // expect 26+
  goals:      GOALS.length,          // expect 82+
  matchStats: Object.keys(MATCH_STATS).length,
  teams:      Object.keys(TEAM_DATA).length,  // expect 48
  groups:     Object.keys(GROUPS).length,     // expect 12
  upcoming:   UPCOMING_FIXTURES.length,
  predictor:  typeof buildMatchPredictor,     // expect 'function'
})
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JavaScript — zero frameworks, no build step |
| Data storage | JSON files in `data/` — GitHub as a free database |
| Hosting | GitHub Pages (free) |
| Automation | GitHub Actions (free tier, 3-hour schedule) |
| Match API | ESPN (no auth) + football-data.org (free tier) |
| Charts | Pure SVG/HTML — no chart library |
