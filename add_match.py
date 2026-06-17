#!/usr/bin/env python3
"""
add_match.py — Add a new completed match to all data files
══════════════════════════════════════════════════════════
Run after each match to add result + stats + goals to JSON files,
then calls update_site.py to patch index.html.

Usage:
  python add_match.py

Just edit the MATCH, STATS, and GOALS variables below, then run.
GitHub Actions can also call this after fetching from football-data.org.
"""

import json, os, sys

DATA_DIR = 'data'

def load(fname):
    path = os.path.join(DATA_DIR, fname)
    with open(path) as f:
        return json.load(f)

def save(fname, data):
    path = os.path.join(DATA_DIR, fname)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"✓ Saved {fname}")

# ══════════════════════════════════════════════════════════
# ← EDIT THESE BEFORE RUNNING ─────────────────────────────
# ══════════════════════════════════════════════════════════

MATCH = {
    "id":    "m19",              # next match id
    "date":  "Jun 16",
    "home":  "Argentina",
    "away":  "Algeria",
    "score": "2-0",              # final score
    "group": "Group J",
    "ytId":  "",                 # YouTube ID if available
    "fifaUrl": "https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/argentina-v-algeria-highlights-match-report"
}

STATS = {
    "home": "Argentina",
    "away": "Algeria",
    "score": "2-0",
    "date": "Jun 16 - Arrowhead Stadium, Kansas City",
    "poss": [64, 36],
    "stats": [
        ["Shots", 18, 6],
        ["Shots on Target", 7, 2],
        ["Passes", 580, 310],
        ["Pass Accuracy %", 87, 73],
        ["Fouls", 12, 14],
        ["Corners", 7, 2],
        ["Clearances", 5, 22],
        ["Turnovers", 10, 18]
    ],
    "xtra": [
        ["xG", 2.4, 0.6],
        ["Yellow Cards", 1, 2],
        ["Offsides", 2, 1],
        ["Saves", 1, 6]
    ]
}

# Each goal: id is auto-assigned, matchId auto-set from MATCH
GOALS = [
    {
        "scorer": "L. Messi",
        "minute": 38,
        "type": "open-play",    # open-play / header / penalty / own-goal / free-kick
        "phase": "Group J",
        "score": "1-0",
        "desc": "Messi opens his 2026 World Cup account with a superb low drive"
    },
    {
        "scorer": "L. Martinez",
        "minute": 72,
        "type": "open-play",
        "phase": "Group J",
        "score": "2-0",
        "desc": "Martinez seals it with a clinical finish after Messi's through ball"
    },
]

REMOVE_FROM_UPCOMING = [MATCH['home'], MATCH['away']]  # remove this fixture from ticker

# ══════════════════════════════════════════════════════════

def run():
    # 1. Add to matches.json
    matches = load('matches.json')
    if any(m['id'] == MATCH['id'] for m in matches):
        print(f"Match {MATCH['id']} already exists — updating score")
        for m in matches:
            if m['id'] == MATCH['id']:
                m.update(MATCH)
    else:
        matches.append(MATCH)
    save('matches.json', matches)

    # 2. Add to match_stats.json
    stats = load('match_stats.json')
    stats[MATCH['id']] = STATS
    save('match_stats.json', stats)

    # 3. Add to goals.json
    goals = load('goals.json')
    existing_ids = {g['id'] for g in goals}
    next_id = max(existing_ids) + 1 if existing_ids else 1
    for i, g in enumerate(GOALS):
        goal = {
            "id": next_id + i,
            "matchId": MATCH['id'],
            "home": MATCH['home'],
            "away": MATCH['away'],
            **g
        }
        if goal['id'] not in existing_ids:
            goals.append(goal)
    goals.sort(key=lambda g: (int(g['matchId'].replace('m','')), g['minute']))
    save('goals.json', goals)

    # 4. Update upcoming_fixtures.json — remove completed match
    upcoming = load('upcoming_fixtures.json')
    upcoming = [f for f in upcoming 
                if not (f['home'] in REMOVE_FROM_UPCOMING and f['away'] in REMOVE_FROM_UPCOMING)]
    save('upcoming_fixtures.json', upcoming)

    # 5. Re-patch index.html
    print("\nPatching index.html...")
    os.system('python update_site.py')

    print(f"\n✅ Match {MATCH['id']} ({MATCH['home']} {MATCH['score']} {MATCH['away']}) added.")
    print(f"   Goals added: {len(GOALS)}")
    print(f"   Commit data/ and index.html to GitHub to publish.")

if __name__ == '__main__':
    run()
