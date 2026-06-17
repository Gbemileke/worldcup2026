# 2026 FIFA World Cup Analytics Dashboard

Live analytics dashboard for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page analytics app with five tabs, fully responsive across desktop, tablet and iPhone:

| Tab | Content |
|---|---|
| **Analytics** (default) | Snapshot cards · Goals by period chart · Goal type donut · Top scorers table · Match stats selector |
| **Highlights** | Live goal feed with filters · Goal hero panel with FIFA.com highlight links |
| **Videos** | Match cards linking directly to FIFA highlight pages |
| **Bracket** | R32 simulation · Top 4 predictions · Model weight settings · Quick presets |
| **Groups** | 12 group prediction tables · Model vs Polymarket vs FanDuel comparison |

---

## Repository structure

```
worldcup2026/
├── index.html                    ← Entire app (~181KB, 48 JS functions, 5 mobile breakpoints)
├── data/                         ← JSON files — single source of truth
│   ├── matches.json              ← Match results + auto-generated FIFA highlight links
│   ├── goals.json                ← Goals: scorer, minute, type, description
│   ├── match_stats.json          ← Possession, shots, xG, yellow cards per match
│   ├── team_data.json            ← 48 teams: Elo, FIFA pts, live form, Polymarket winner %
│   ├── groups.json               ← 12 groups + Polymarket/FanDuel group winner odds
│   └── upcoming_fixtures.json    ← Next fixtures with CST kick-off times (auto-updated)
├── update_site.py                ← Master rebuild: data/ → index.html (8 sections)
├── update_match_stats.py         ← Fetches matches, goals, stats + upcoming from API
├── update_rankings.py            ← Fetches Elo, FIFA pts + Polymarket winner odds
├── update_odds.py                ← Manual: Polymarket/FanDuel group winner odds
├── add_match.py                  ← Manually add a match with descriptions + FIFA link
└── .github/workflows/
    ├── auto-update.yml           ← Every 3 hours: match data + form + upcoming
    ├── daily-rankings.yml        ← Daily 6am UTC: Elo + FIFA pts + Polymarket odds
    └── daily-odds.yml            ← Manual trigger: group winner odds
```

---

## What updates automatically vs manually

| Data | Auto? | Script | Schedule | Source |
|---|---|---|---|---|
| Match scores + stats | ✅ | `update_match_stats.py` | Every 3 hrs | football-data.org API |
| Goal scorers + types | ✅ | `update_match_stats.py` | Every 3 hrs | football-data.org API (24hr delay) |
| Goal descriptions (basic) | ✅ | `update_match_stats.py` | Every 3 hrs | Auto-generated |
| Upcoming fixtures + CST times | ✅ | `update_match_stats.py` | Every 3 hrs | football-data.org API |
| FIFA highlight links | ✅ | `update_match_stats.py` | Every 3 hrs | Auto-generated from name slugs |
| Team form | ✅ | `update_site.py` | Every 3 hrs | Computed from WC results |
| Elo ratings | ✅ | `update_rankings.py` | Daily 6am UTC | trueline.online |
| FIFA ranking points | ✅ | `update_rankings.py` | Daily 6am UTC | June 11 baseline + WC formula |
| WC winner odds (marketPct) | ✅ | `update_rankings.py` | Daily 6am UTC | Polymarket gamma API |
| Group winner odds | ⚠️ Manual | `update_odds.py` | After each matchday | polymarket.com + FanDuel |
| Goal descriptions (rich) | ⚠️ Manual | Edit `data/goals.json` | Optional | Written by you |

> **Note:** football-data.org free tier delays goal scorer data by ~24 hours after the match. Scores and stats are available immediately. Goals populate on subsequent Action runs.

---

## Automation flows

### `auto-update.yml` — every 3 hours

```
update_match_stats.py
  ├── fetch FINISHED matches
  │     → matches.json  (score, date, auto FIFA highlight URL)
  │     → match_stats.json  (possession, shots, xG, cards)
  │     → goals.json  (scorer, minute, type, auto-description)
  │     → removes completed games from upcoming_fixtures.json
  │     → cleans up any stale placeholder entries
  └── fetch SCHEDULED matches
        → upcoming_fixtures.json  (next 12 games, CST times)

update_site.py --section form
  └── new_form = old_form × 0.4 + wc_result × 0.6

update_site.py  (full rebuild — all 8 sections)

git commit + push → GitHub Pages live in ~2 minutes
```

### `daily-rankings.yml` — 6am UTC every day

```
update_rankings.py
  ├── fetch_elo()        → live Elo from trueline.online
  ├── get_fifa_points()  → P_new = P_old + 40 × (W − We) on all WC results
  └── fetch_polymarket() → WC winner % for all 48 teams, normalised to 100%

patch_html() → patches index.html + saves data/team_data.json

git commit + push
```

### `daily-odds.yml` — manual trigger

```
update_odds.py
  └── edit ODDS_UPDATES (all 12 groups templated with current values)
      → updates groups.json + rebuilds groups section in index.html

git commit + push
```

---

## FIFA highlight links — auto-generation

```python
# Pattern: {home-slug}-v-{away-slug}-highlights-match-report
# Name mapping handles FIFA's non-standard team names:
'S. Korea' / 'Korea Republic'         → 'south-korea'
'Bosnia' / 'Bosnia and Herzegovina'   → 'bosnia-herzegovina'
'Turkiye' / 'Turkey'                  → 'turkey'
'Cape Verde' / 'Cape Verde Islands'   → 'cabo-verde'
'DR Congo' / 'Congo DR'               → 'democratic-republic-of-congo'
'Ivory Coast' / "Côte d'Ivoire"       → 'cote-divoire'
'USA' / 'United States'               → 'united-states'

# Some matches FIFA lists away team first in the URL:
Qatar vs Switzerland  → switzerland-v-qatar
Norway vs Iraq        → iraq-v-norway
```

If a new match link is wrong, add the pair to `FIFA_URL_SWAPS` in `update_match_stats.py`.

---

## Goal descriptions

**Auto-generated** (from API):
`"Bellingham scored for England vs Croatia — England 1-0 Croatia"`

**To add rich descriptions:**
1. Edit `data/goals.json` → update the `desc` field
2. `python update_site.py --section goals`
3. `git add . && git commit -m "goals: descriptions" && git push`

---

## Group winner odds — update after each matchday

1. Open `update_odds.py` — all 12 groups already templated
2. Update percentages from [polymarket.com](https://polymarket.com) and FanDuel
3. `python update_odds.py`
4. `git add data/groups.json index.html && git commit -m "odds: MD[N]" && git push`

---

## Prediction model

### Match probability

```
score(team) = (elo/2200      × W.elo)   +
              (form           × W.form)  +
              (qualGDpg        × W.qual)  +
              (squadDepth/100  × W.squad) +
              (fifaPts/1900    × W.fifa)  +
              (exp/10          × W.exp)

P(home wins) = 1 / (1 + e^(−8 × (score_home − score_away)))
```

### Default weights

| Factor | Weight | Auto-updated |
|---|---|---|
| Elo rating | 30% | ✅ Daily |
| Squad depth | 20% | ❌ Static |
| Recent form | 20% | ✅ Every 3 hrs |
| FIFA points | 15% | ✅ Daily |
| Qualifying record | 10% | ❌ Static |
| Tournament experience | 5% | ❌ Static |

### Team form formula

```
new_form = (pre_tournament_form × 0.4) + (wc_result × 0.6)
win=1.0 · draw=0.5 · loss=0.0
```

### FIFA points formula

```
P_new = P_old + I × (W − We)
We = 1 / (10^(−ΔR/600) + 1)    ← expected score based on Elo difference
I  = 40                          ← World Cup match importance factor
```

### Bracket simulation

Monte Carlo with 10,000 iterations. Re-runs instantly on weight change. Six Quick Presets:

| Preset | Elo | Form | Qual | Squad | FIFA | Exp |
|---|---|---|---|---|---|---|
| Default | 30% | 20% | 10% | 20% | 15% | 5% |
| Elo pure | 70% | 20% | 10% | 0% | 0% | 0% |
| Form heavy | 30% | 40% | 20% | 5% | 0% | 5% |
| Squad heavy | 30% | 20% | 5% | 35% | 5% | 5% |
| Qual heavy | 30% | 20% | 30% | 5% | 10% | 5% |
| Equal | 17% | 17% | 17% | 17% | 16% | 16% |

---

## What xG means

**xG (Expected Goals)** — each shot assigned a probability (0–1) based on distance, angle, body part, and defensive pressure. Sum across all shots = xG total.

- xG > goals scored → missed chances (underperformed)
- xG < goals scored → clinical finishing (overperformed)

Hover the **?** icon next to xG in any match's KEY NUMBERS panel for an inline tooltip.

---

## Responsive design — breakpoints

| Breakpoint | Target | Key changes |
|---|---|---|
| 1100px | Small desktop | Grids reduce columns |
| 900px | Tablet landscape | Sidebar narrows, single-col bracket |
| 768px | Tablet / large phone | Sidebar stacks above content, header stacks, tab bar scrolls horizontally |
| 480px | iPhone | All grids single column, snapshot cards scroll horizontally, fonts scale down |
| 390px | iPhone 14/15 Pro | Fine-tuned for 390px viewport — most common iPhone width |

---

## How to manually add a match

```bash
# 1. Edit add_match.py — fill in MATCH, STATS, GOALS
python add_match.py
git add . && git commit -m "add: [Home] vs [Away]" && git push
```

---

## update_site.py — individual sections

```bash
python update_site.py                      # rebuild everything
python update_site.py --section matches    # match array + FIFA links
python update_site.py --section goals      # goal feed + descriptions
python update_site.py --section stats      # match analytics panel
python update_site.py --section groups     # group winner odds
python update_site.py --section upcoming   # ticker fixtures + CST times
python update_site.py --section sync       # remove completed from upcoming
python update_site.py --section snapshot   # analytics snapshot cards
python update_site.py --section form       # team form + marketPct
```

---

## Secrets required

**GitHub Settings → Secrets → Actions:**

| Secret | Used by | Get at |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | `update_match_stats.py` | football-data.org (free) |

Polymarket API is public — no token needed.

---

## Tournament snapshot (Jun 17 2026)

- **21 matches** played · MD1 complete · MD2 in progress
- **64 goals** · 3.05 per match average
- **Goals breakdown:** 47 open play · 11 headers · 2 penalties · 4 own goals
- **Top scorer:** L. Messi — 3 goals (equals Klose all-time WC record of 16)
- **Biggest match:** Germany 7–1 Curaçao (8 goals)
- **Last played:** Portugal 1–1 DR Congo · Neves 6' · Wissa 45+5' (Jun 17)
- **Notable:** Ronaldo became oldest outfield player to start a World Cup match (age 41)
- **Notable:** DR Congo scored their first ever World Cup goal (Wissa)
- **Polymarket WC winner:** France 17.8% · Spain 12.8% · Argentina 10.4%

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS — zero frameworks, no build step |
| Mobile | 5 responsive breakpoints (1100 / 900 / 768 / 480 / 390px) |
| Charts | Pure SVG/HTML — no chart library |
| Data | JSON files in `data/` — GitHub as database |
| Hosting | GitHub Pages (free) |
| Automation | GitHub Actions (3 workflows, free tier) |
| Match API | football-data.org free tier (10 req/min, ~24hr goal delay) |
| Odds API | Polymarket gamma API (public, no auth) |
| Elo | trueline.online (mirrors eloratings.net) |

---

## Browser console verification

```javascript
console.table({
  matches:         MATCHES.length,
  goals:           GOALS.length,
  matchStats:      Object.keys(MATCH_STATS).length,
  teams:           Object.keys(TEAM_DATA).length,
  groups:          Object.keys(GROUPS).length,
  presets:         Object.keys(PRESETS).length,
  switchTab:       typeof switchTab,
  buildGroupsGrid: typeof buildGroupsGrid
})
// Expected: matches:21, goals:64, matchStats:21, teams:48, groups:12, presets:6
```
