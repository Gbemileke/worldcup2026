# 2026 FIFA World Cup Analytics Dashboard

Live analytics dashboard for the 2026 FIFA World Cup hosted across USA, Canada & Mexico.

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/

---

## Repository Structure

```
worldcup2026/
├── index.html              ← The entire app (single HTML file)
├── data/                   ← JSON data files (source of truth)
│   ├── matches.json        ← All 18 matches + scores + FIFA links
│   ├── goals.json          ← All 55 goals + scorers + descriptions
│   ├── match_stats.json    ← Possession/shots/xG per match
│   ├── team_data.json      ← 48 teams: Elo, FIFA pts, form, squad
│   ├── groups.json         ← 12 groups + Polymarket/FanDuel odds
│   └── upcoming_fixtures.json ← Ticker upcoming matches
├── update_site.py          ← Master: rebuilds index.html from data/
├── add_match.py            ← Add a new completed match + goals
├── update_odds.py          ← Update group prediction odds
├── update_match_stats.py   ← Auto-fetch from football-data.org
├── update_rankings.py      ← Auto-fetch Elo/FIFA rankings
└── .github/workflows/
    ├── auto-update.yml     ← Runs every 30 min (match data)
    └── daily-odds.yml      ← Manual trigger (group odds)
```

---

## How to update after each match

### Option A — Manual (no API token needed)
1. Edit `data/goals.json` — add the new goals
2. Edit `data/matches.json` — update the score
3. Edit `data/match_stats.json` — add possession/shots stats
4. Edit `data/upcoming_fixtures.json` — remove the played match
5. Run: `python update_site.py`
6. Commit and push all files

### Option B — Semi-automated (edit `add_match.py`)
1. Open `add_match.py`
2. Fill in `MATCH`, `STATS`, and `GOALS` variables
3. Run: `python add_match.py`
4. Commit and push: `git add . && git commit -m "add: [match]" && git push`

### Option C — Fully automated (requires football-data.org token)
1. Get free token at https://www.football-data.org/client/register
2. Add to GitHub Secrets: `Settings → Secrets → FOOTBALL_DATA_TOKEN`
3. GitHub Actions runs every 30 minutes automatically

---

## What updates what

| Data file | Script | When |
|---|---|---|
| `matches.json` | `add_match.py` | After each match |
| `goals.json` | `add_match.py` | After each match |
| `match_stats.json` | `add_match.py` or `update_match_stats.py` | After each match |
| `upcoming_fixtures.json` | `add_match.py` | After each match |
| `groups.json` | `update_odds.py` | After each matchday |
| `team_data.json` | `update_rankings.py` | Daily |
| `index.html` | `update_site.py` | Called by all above |

---

## Sections of index.html rebuilt by update_site.py

| Section | Data source | `--section` flag |
|---|---|---|
| Goal feed sidebar | `goals.json` | `goals` |
| Videos tab cards | `matches.json` | `matches` |
| Analytics charts | `goals.json` | `snapshot` |
| Match selector + stats | `match_stats.json` | `stats` |
| Ticker (gold bar) | `upcoming_fixtures.json` + last 5 of `match_stats.json` | `upcoming` |
| Groups tab | `groups.json` | `groups` |
| Bracket / Top 4 | `team_data.json` (via rankings update) | N/A (live JS) |

---

## Secrets needed (GitHub Settings → Secrets)

| Secret | Required for | Get it at |
|---|---|---|
| `FOOTBALL_DATA_TOKEN` | Auto match fetch | football-data.org (free) |

