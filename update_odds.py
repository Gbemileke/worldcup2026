#!/usr/bin/env python3
"""
update_odds.py — Update Polymarket/FanDuel group odds after each matchday
═════════════════════════════════════════════════════════════════════════
Edit the ODDS_UPDATES dict below with the latest odds after each MD,
then run. Patches groups.json and index.html.

Also updates UPCOMING_FIXTURES to remove played matches
and add next matchday fixtures.
"""

import json, os

DATA_DIR = 'data'

# ══════════════════════════════════════════════════════════
# ← EDIT AFTER EACH MATCHDAY ───────────────────────────────
# polymarket = % chance of winning group (0-100)
# fanDuelOdds = American odds (+300 = underdog, -200 = favourite)
# ══════════════════════════════════════════════════════════

ODDS_UPDATES = {
    'I': {
        'France':  {'polymarket': 88, 'fanDuelOdds': -450},
        'Norway':  {'polymarket': 10, 'fanDuelOdds':  200},
        'Senegal': {'polymarket':  1.5,'fanDuelOdds': 1200},
        'Iraq':    {'polymarket':  0.5,'fanDuelOdds': 15000},
    },
    'G': {
        'Belgium':     {'polymarket': 55, 'fanDuelOdds': -180},
        'New Zealand': {'polymarket': 20, 'fanDuelOdds':  350},
        'Iran':        {'polymarket': 15, 'fanDuelOdds':  500},
        'Egypt':       {'polymarket': 10, 'fanDuelOdds':  700},
    },
    'H': {
        'Spain':        {'polymarket': 72, 'fanDuelOdds': -280},
        'Uruguay':      {'polymarket': 20, 'fanDuelOdds':  280},
        'Cape Verde':   {'polymarket':  5, 'fanDuelOdds': 3000},
        'Saudi Arabia': {'polymarket':  3, 'fanDuelOdds': 4000},
    },
    # Add more groups here as odds change...
}

# ══════════════════════════════════════════════════════════

def run():
    path = os.path.join(DATA_DIR, 'groups.json')
    with open(path) as f:
        groups = json.load(f)

    changed = 0
    for letter, team_updates in ODDS_UPDATES.items():
        if letter not in groups:
            print(f"  ✗ Group {letter} not found")
            continue
        for team in groups[letter]['teams']:
            if team['name'] in team_updates:
                updates = team_updates[team['name']]
                old_pm = team['polymarket']
                team['polymarket']  = updates['polymarket']
                team['fanDuelOdds'] = updates['fanDuelOdds']
                changed += 1
                print(f"  {letter}: {team['name']:15} pm {old_pm}% → {updates['polymarket']}%")

    with open(path, 'w') as f:
        json.dump(groups, f, indent=2)
    print(f"\n✓ {changed} team odds updated in groups.json")

    # Re-patch index.html
    os.system('python update_site.py --section groups')
    print("✅ Done. Commit data/groups.json and index.html to publish.")

if __name__ == '__main__':
    run()
