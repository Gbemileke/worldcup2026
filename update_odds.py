#!/usr/bin/env python3
"""
update_odds.py — Update Polymarket/FanDuel group winner odds
════════════════════════════════════════════════════════════
Run after each matchday to update group winner odds.

Usage:
  1. Update ODDS_UPDATES below with latest odds
  2. python update_odds.py
  3. git add data/groups.json index.html
  4. git commit -m "odds: MD[N] update" && git push

Sources:
  Polymarket: polymarket.com/event/world-cup-group-[a-l]-winner
  FanDuel:    sportsbook.fanduel.com (via Fox Sports)

Last updated: Jun 17 2026 (post MD1)
"""

import json, os

DATA_DIR = 'data'

# ══════════════════════════════════════════════════════════════════
# EDIT THIS after each matchday — all 12 groups
# polymarket = % chance of winning group (must sum to ~100 per group)
# fanDuelOdds = American odds (-200=favourite, +300=underdog)
# ══════════════════════════════════════════════════════════════════

ODDS_UPDATES = {
    'A': {
        'Mexico':       {'polymarket': 62,  'fanDuelOdds': -160},
        'South Korea':  {'polymarket': 34,  'fanDuelOdds':  160},
        'Czechia':      {'polymarket':  3,  'fanDuelOdds': 1700},
        'South Africa': {'polymarket':  1,  'fanDuelOdds': 8000},
    },
    'B': {
        'Switzerland':  {'polymarket': 47,  'fanDuelOdds': -165},
        'Canada':       {'polymarket': 35,  'fanDuelOdds':  200},
        'Bosnia':       {'polymarket': 15,  'fanDuelOdds':  600},
        'Qatar':        {'polymarket':  3,  'fanDuelOdds': 4000},
    },
    'C': {
        'Brazil':       {'polymarket': 58,  'fanDuelOdds': -200},
        'Morocco':      {'polymarket': 30,  'fanDuelOdds':  280},
        'Scotland':     {'polymarket': 11,  'fanDuelOdds':  700},
        'Haiti':        {'polymarket':  1,  'fanDuelOdds':15000},
    },
    'D': {
        'USA':          {'polymarket': 70,  'fanDuelOdds': -260},
        'Australia':    {'polymarket': 21,  'fanDuelOdds':  300},
        'Turkey':       {'polymarket':  8,  'fanDuelOdds':  900},
        'Paraguay':     {'polymarket':  1,  'fanDuelOdds': 5000},
    },
    'E': {
        'Germany':      {'polymarket': 74,  'fanDuelOdds': -400},
        'Ivory Coast':  {'polymarket': 21,  'fanDuelOdds':  350},
        'Ecuador':      {'polymarket':  4,  'fanDuelOdds': 2000},
        'Curacao':      {'polymarket':  1,  'fanDuelOdds':25000},
    },
    'F': {
        'Netherlands':  {'polymarket': 44,  'fanDuelOdds': -130},
        'Sweden':       {'polymarket': 28,  'fanDuelOdds':  240},
        'Japan':        {'polymarket': 27,  'fanDuelOdds':  260},
        'Tunisia':      {'polymarket':  1,  'fanDuelOdds':10000},
    },
    'G': {
        'Belgium':      {'polymarket': 63,  'fanDuelOdds': -220},
        'Egypt':        {'polymarket': 25,  'fanDuelOdds':  380},
        'Iran':         {'polymarket':  7,  'fanDuelOdds':  900},
        'New Zealand':  {'polymarket':  5,  'fanDuelOdds': 2500},
    },
    'H': {
        'Spain':        {'polymarket': 73,  'fanDuelOdds': -350},
        'Uruguay':      {'polymarket': 22,  'fanDuelOdds':  320},
        'Cape Verde':   {'polymarket':  3,  'fanDuelOdds': 3000},
        'Saudi Arabia': {'polymarket':  2,  'fanDuelOdds': 4000},
    },
    'I': {
        'France':       {'polymarket': 77,  'fanDuelOdds': -450},
        'Norway':       {'polymarket': 21,  'fanDuelOdds':  300},
        'Senegal':      {'polymarket':  1,  'fanDuelOdds': 1200},
        'Iraq':         {'polymarket':  1,  'fanDuelOdds':15000},
    },
    'J': {
        'Argentina':    {'polymarket': 85,  'fanDuelOdds': -600},
        'Austria':      {'polymarket': 13,  'fanDuelOdds':  500},
        'Algeria':      {'polymarket':  1,  'fanDuelOdds': 3000},
        'Jordan':       {'polymarket':  1,  'fanDuelOdds':15000},
    },
    'K': {
        'Portugal':     {'polymarket': 63,  'fanDuelOdds': -280},
        'Colombia':     {'polymarket': 31,  'fanDuelOdds':  260},
        'DR Congo':     {'polymarket':  3,  'fanDuelOdds': 2500},
        'Uzbekistan':   {'polymarket':  3,  'fanDuelOdds': 3000},
    },
    'L': {
        'England':      {'polymarket': 71,  'fanDuelOdds': -320},
        'Croatia':      {'polymarket': 23,  'fanDuelOdds':  340},
        'Ghana':        {'polymarket':  5,  'fanDuelOdds': 1800},
        'Panama':       {'polymarket':  1,  'fanDuelOdds': 8000},
    },
}

# ══════════════════════════════════════════════════════════════════

def run():
    path = os.path.join(DATA_DIR, 'groups.json')
    with open(path) as f:
        groups = json.load(f)

    changed = 0
    for letter, team_updates in ODDS_UPDATES.items():
        if letter not in groups:
            print(f"  ✗ Group {letter} not found")
            continue
        # Verify sum is ~100
        total_pm = sum(v['polymarket'] for v in team_updates.values())
        if abs(total_pm - 100) > 2:
            print(f"  ⚠ Group {letter} Polymarket odds sum to {total_pm}% (should be 100%)")

        for team in groups[letter]['teams']:
            if team['name'] in team_updates:
                updates      = team_updates[team['name']]
                old_pm       = team['polymarket']
                old_fd       = team['fanDuelOdds']
                team['polymarket']  = updates['polymarket']
                team['fanDuelOdds'] = updates['fanDuelOdds']
                changed += 1
                pm_arrow = '↑' if updates['polymarket'] > old_pm else ('↓' if updates['polymarket'] < old_pm else '=')
                print(f"  {letter}: {team['name']:15s} {old_pm}% {pm_arrow} {updates['polymarket']}%  "
                      f"FanDuel: {old_fd} → {updates['fanDuelOdds']}")

    with open(path, 'w') as f:
        json.dump(groups, f, indent=2)
    print(f"\n✓ {changed} team odds updated in groups.json")

    os.system('python update_site.py --section groups')
    print("✅ Done. Commit data/groups.json and index.html to publish.")

if __name__ == '__main__':
    run()
