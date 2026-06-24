# 2026 FIFA World Cup Analytics Dashboard

Live analytics dashboard and interactive bracket simulator for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page app with six tabs:

| Tab | Content |
|---|---|
| **Highlights** | Live goal feed with filters · Goal hero panel with scorer/minute/type/group detail cards · FIFA.com links |
| **Videos** | Match video cards linking to FIFA highlight pages |
| **Analytics** | 8 snapshot cards · Goals by period chart · Goal type donut · Top scorers · Match stats selector |
| **Simulator** | Model-driven R32→Final prediction · Top 4 favourites · Adjustable model weights · Quick presets |
| **Groups** | Match predictor with **Consensus Pick** (Model + Market blend) · 12 redesigned group cards showing **live standings** (points, position, W/D/L/GD) + qualification prediction · Model / Market / FanDuel win-% per team |
| **Bracket** | **Interactive knockout bracket simulator** — pick every match, AI-fill, share, export PDF |

---

## ⭐ Interactive Bracket Simulator (Bracket tab)

The flagship feature: a full FIFA-accurate knockout bracket you can fill out yourself.

### Structure
- Mirrors the official FIFA bracket exactly: **R32 (M73–M88) → R16 (M89–M96) → QF (M97–M100) → SF (M101–M102) → Final (M104)**, plus the **third-place match (M103)**
- Each slot shows the real **match number, date, time, and venue**
- Empty R32 slots display **FIFA seed labels** ("1st A", "2nd B", "3rd A/B/C/D/F") until the group stage decides who qualifies

### Two modes
| Mode | Behaviour |
|---|---|
| **🤖 AI Prefill** (default) | Projects each group's standings from the model, resolves all seed labels to teams, and predicts every match. Click any match to override a pick. |
| **✏️ Pick My Own** | Projects the teams into R32 but leaves all winners blank — you pick every match yourself. |

### Interactions
- **Click any match** → modal to pick the winner, showing both teams with flags, Elo, FIFA rank, and model win %
- **Edit R32 teams** → each R32 slot has dropdowns to swap teams, **constrained to the eligible group(s)** for that seed ("1st A" → Group A's 4 teams only; "3rd A/B/C/D/F" → the 20 teams from those 5 groups)
- **AI reasoning tooltips** → hover any AI-picked match to see why ("Elo 2062 vs 1680 · Form 89% vs 54%")
- Changing a pick **cascades** — downstream picks auto-clear to keep the bracket consistent
- Third-place match auto-populates from the two semifinal losers

### Share & export
- **Share** → preview-card modal with a one-click "Copy link to share anywhere" button
- Picks are encoded into an **ultra-compact ~15-character URL** (`?b=1z141z3_1bcqpbe`) using base36-packed bits — paste into any app and Open Graph meta tags render a rich preview
- **Download PDF** → landscape A3 PDF of the completed bracket via jsPDF + html2canvas

---

## Groups tab features

### Live group standings (per card)
Each of the 12 group cards shows the **real current standings** computed from played matches, not just predictions:
- **Position + points** (`1st · 6 pts`) with a colored rank circle and left accent stripe (gold = 1st, blue = 2nd, gray = out)
- **Record line** — `P2 W2 D0 L0 · GD+3` (played, win/draw/loss, goal difference)
- **Qualification prediction badge** — `TOP` / `Q` / `OUT` from the model, shown alongside the live position
- **Three win-% sources** per team — Model (gold) / Market (blue) / FanDuel (purple)

**Robust standings calculation** (`computeGroupStandings`): the group of each match is **inferred from the teams' GROUPS membership**, not the scraped `group` field — which is frequently empty or abbreviated (`''`, `E`) in the ESPN feed. Team names are canonicalized so abbreviated forms (`S. Korea` → `South Korea`, `C. Verde` → `Cape Verde`) always resolve. This makes standings correct regardless of how the scraper tags matches, and guarantees the **final group-stage round will update points correctly**. Tiebreakers follow FIFA order: points → goal difference → goals for.

### Consensus Pick (match predictor)
The upcoming-match predictor blends the model and market into a single **Consensus Pick** bar (below the Model favourite bar), weighted 50/50:
```
consensus = (model_prob + market_prob) / 2   (then normalized)
```

### Refined market probability
The "Market" row no longer uses raw Polymarket group-win % (which produced distorted 0% / 73% splits for single matches). It now **blends Polymarket crowd odds + FanDuel bookmaker odds** into a relative match strength, with a **floor clamp [0.18, 0.82]** so neither team ever collapses to 0% in a head-to-head. *(Note: no true per-match betting lines exist in the data — these are group-winner odds repurposed for match estimation.)*

---

## Repository structure

```
worldcup2026/
├── index.html                    ← Entire app (~316KB single HTML file)
├── data/
│   ├── matches.json              ← Matches + scores + espnId + FIFA links
│   ├── goals.json                ← Goals + scorers + minute + type + descriptions
│   ├── match_stats.json          ← Possession / shots / xG / cards per match (ESPN)
│   ├── team_data.json            ← Teams: Elo, FIFA pts, form, qual record, squad depth
│   ├── groups.json               ← 12 groups + Polymarket odds
│   └── upcoming_fixtures.json    ← Remaining fixtures with ET kick-off times
├── update_site.py                ← Master rebuild: reads all JSON → writes index.html
├── update_match_stats.py         ← Fetches ESPN scoreboard + summary endpoints
├── update_rankings.py            ← Updates Elo / FIFA rankings daily
├── update_odds.py                ← Updates Polymarket group odds (manual)
├── add_match.py                  ← Manually add a completed match
├── generate_descriptions.py      ← Goal description text helper
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

Step 2: update_site.py --section form
  └── Recomputes team form (idempotent — see Form model below)

Step 3: update_site.py (full rebuild)
  ├── matches    → goal feed, video cards, ticker
  ├── goals      → highlight feed, scorers, charts
  ├── stats      → match analytics (ESPN labels, xG)
  ├── groups     → group prediction odds
  ├── upcoming   → ticker + predictor dropdown
  ├── sync       → removes completed games from upcoming
  ├── snapshot   → 8 cards with tooltips
  ├── form       → team form in bracket / predictor
  └── build-stamp → refreshes cache-busting timestamp (forces fresh load)

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

## Goal attribution & validation

`update_match_stats.py` validates that the running goal tally matches the ESPN final score before saving any goals for a match.

**Robust team resolution** (added after m24/m39/m40 attribution bug):
- Normalizes and fuzzy-matches ESPN team names against home/away (handles "Korea Republic" vs "S. Korea", blank names, etc.)
- Extracts per-goal `homeScore`/`awayScore` from ESPN `details[]` for exact attribution when available
- Falls back to capacity-based assignment (fills toward the known final score) when the team genuinely can't be determined
- If the tally still can't be reconciled, goals are **skipped and retried next run** rather than saved with wrong attribution

This fixed matches that previously recorded e.g. `0-4` instead of the real `1-3`, leaving goals unsaved.

### Goal-type classification (free-kick / header / penalty / own-goal)

ESPN only reliably tags **penalty** and **own-goal** — free-kicks and headers come back as generic "open-play". A 3-layer system keeps goal types correct and persistent:

1. **Auto-detect** (`_classify_goal_type`) — reads ESPN's goal-type text *and* the play description (`text` / `shortText`) for "free kick", "headed", "direct free", etc. so new free-kicks/headers are caught automatically when ESPN describes them.
2. **Preserve** — existing free-kick/header classifications survive a re-scrape if ESPN's text is silent on a goal it already tagged.
3. **Override** (`GOAL_TYPE_OVERRIDES`) — a hardcoded `(matchId, scorer, minute): type` map force-applies known free-kicks/headers on every run, so manual classifications never reset. Present in **both** `update_match_stats.py` and `update_site.py`. Penalty/own-goal are never overridden.

To add a new free-kick/header: one line in `GOAL_TYPE_OVERRIDES` in both scripts.

### Scorer name canonicalization (accent merging)

ESPN spells some scorers inconsistently (`K. Mbappe` vs `K. Mbappé`), which would split one player into two top-scorer entries. `canonScorer` (in `index.html`) and `SCORER_ALIASES` + `_strip_accents` (in `update_match_stats.py`) normalize diacritics and merge variants so a player's goals always tally to one entry — applied across the top-scorers list, goal feed, hero panel, and penalty tooltips.

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

**Idempotent** — the qualifying record never changes, so running `update_form` repeatedly always gives the same result.

---

## Prediction model

### Match predictor (Groups tab) — fixed weights

```
score(team) = form × 0.35 + (elo/2200) × 0.20 + (squadDepth/100) × 0.15
            + (fifaPts/1900) × 0.15 + qualGDpg × 0.10 + (exp/10) × 0.05

P(win) = 1 / (1 + e^(−8 × (score_A − score_B)))
draw%  = max(0.12, 0.30 − eloGap/2800)
```

### Bracket simulator — `computeFullModelScore`

The interactive bracket and the Simulator tab use the same full model score to project group standings, resolve seeds, and predict knockout matches. Seed resolution:
- **`1st X` / `2nd X`** → projected winner / runner-up of Group X (ranked by model score)
- **`3rd X/Y/Z…`** → best-ranked projected 3rd-place team among those groups (deduplicated so no two slots claim the same team)

---

## Match statistics

- **Source:** ESPN summary endpoint — `site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={espnId}`
- **Labels match ESPN exactly:** Shot Attempts · Shots on Goal · Corner Kicks · Fouls · Saves
- **Extra stats:** xG · Yellow Cards · Red Cards · Offsides
- **xG:** Real ESPN/Opta data where available; calculated from SOT for others
- **espnId** stored per match in `matches.json` for re-fetching

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

## Caching & deployment

- `index.html` carries `Cache-Control: no-cache` meta tags and an auto-refreshing `<!-- build: ... -->` timestamp so browsers always load the latest data.
- After an update, check the build stamp in **View Source** (`Ctrl+U`) to confirm you're seeing the current deploy.
- If you still see stale data, hard-refresh: `Ctrl+Shift+R` (Windows) / `Cmd+Shift+R` (Mac).

### Note on pushes
Both you and the GitHub Action commit to `main`, so manual pushes are often rejected with "fetch first" / "non-fast-forward". Before pushing:
```bash
git pull origin main --no-rebase   # then resolve any conflict, keeping the Action's fresh data
git push origin main
```
Tip: `git config pull.rebase false` makes pulls merge automatically.

---

## GitHub secrets required

**Settings → Secrets → Actions:**

| Secret | Used by | Get it at |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | `update_match_stats.py` | football-data.org (free tier) |

---

## update_site.py — section reference

```bash
python update_site.py                      # rebuild everything (+ build stamp)
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
  matches:     MATCHES.length,
  goals:       GOALS.length,
  matchStats:  Object.keys(MATCH_STATS).length,
  teams:       Object.keys(TEAM_DATA).length,
  groups:      Object.keys(GROUPS).length,         // expect 12
  upcoming:    UPCOMING_FIXTURES.length,
  predictor:   typeof buildMatchPredictor,         // 'function'
  bracketSim:  typeof buildBracketSim,             // 'function'
  standings:   typeof computeGroupStandings,       // 'function'
  scorerCanon: typeof canonScorer,                 // 'function'
})

// Check live standings for a group (points should be correct even mid-tournament)
console.table(computeGroupStandings('Group A'))
```

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
| Flags | flagcdn.com (size-snapped to valid widths) |
| PDF export | jsPDF + html2canvas (CDN, deferred load) |
