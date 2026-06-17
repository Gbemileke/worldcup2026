#!/usr/bin/env python3
"""
generate_descriptions.py
════════════════════════
Auto-generates rich goal descriptions from match data alone.
No external API needed — uses templates + context from goals/matches.

Called by auto-update.yml after update_match_stats.py runs.
Only updates goals with missing or basic descriptions.
"""

import json, os, sys, random

DATA_DIR = 'data'

def load(fname):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path): return None
    with open(path) as f: return json.load(f)

def save(fname, data):
    with open(os.path.join(DATA_DIR, fname), 'w') as f:
        json.dump(data, f, indent=2)

def needs_description(g):
    desc = g.get('desc', '').strip()
    if not desc: return True
    basic = ['scored for', 'See FIFA.com', 'highlights-match-report',
             'scored a goal', 'not yet available']
    return any(p in desc for p in basic)

def score_context(score, home, away):
    """Return a context phrase based on the score."""
    parts = score.split('-')
    if len(parts) != 2: return ''
    try:
        h, a = int(parts[0]), int(parts[1])
    except:
        return ''
    diff = h - a
    total = h + a
    if diff == 0:   return f'{home} and {away} level at {h}-{a}'
    if diff >= 3:   return f'{home} dominant at {h}-{a}'
    if diff <= -3:  return f'{away} pulling clear {h}-{a}'
    if diff > 0:    return f'{home} lead {h}-{a}'
    if diff < 0:    return f'{away} ahead {h}-{a}'
    return f'{h}-{a}'

def generate(g, all_goals):
    """Generate a description from goal data."""
    scorer    = g['scorer'].replace(' OG','').strip()
    minute    = g['minute']
    gtype     = g['type']
    home      = g['home']
    away      = g['away']
    score     = g['score']
    phase     = g.get('phase','')
    ctx       = score_context(score, home, away)

    # Determine which team scored
    parts = score.split('-')
    try:
        h, a = int(parts[0]), int(parts[1])
    except:
        h, a = 0, 0

    # Figure out if this was an equaliser, opener, winner etc
    prev_goals = [x for x in all_goals
                  if x['matchId'] == g['matchId'] and x['minute'] < minute]
    prev_parts = prev_goals[-1]['score'].split('-') if prev_goals else ['0','0']
    try:
        ph, pa = int(prev_parts[0]), int(prev_parts[1])
    except:
        ph, pa = 0, 0

    is_og      = gtype == 'own-goal'
    is_pen     = gtype == 'penalty'
    is_header  = gtype == 'header'
    is_opener  = not prev_goals
    is_eq      = h == a
    is_late    = minute >= 80
    is_stoppage= minute > 90
    lead_change= (ph >= pa and h < a) or (pa >= ph and a < h)

    # Build description
    if is_og:
        templates = [
            f"Cruel own goal from {scorer} — {ctx}",
            f"{scorer} deflects the ball into his own net — {ctx}",
            f"Unfortunate own goal by {scorer} as the cross finds the back of the net",
            f"{scorer} can only watch as the ball loops past his keeper — {ctx}",
        ]
    elif is_pen:
        templates = [
            f"{scorer} steps up and converts from the spot — {ctx}",
            f"Penalty coolly dispatched by {scorer} — {ctx}",
            f"{scorer} sends the keeper the wrong way from 12 yards — {ctx}",
            f"Composed penalty finish from {scorer} — {ctx}",
        ]
    elif is_header:
        templates = [
            f"{scorer} powers a header home — {ctx}",
            f"Towering header from {scorer} finds the net — {ctx}",
            f"{scorer} rises highest to head home — {ctx}",
            f"Brilliant header by {scorer} — {ctx}",
        ]
    elif is_opener:
        templates = [
            f"{scorer} breaks the deadlock — {home} lead {score}",
            f"{scorer} opens the scoring with a clinical finish — {home} {score} {away}",
            f"First blood to {home} — {scorer} with a fine finish",
            f"{scorer} gets {home} off the mark — {score}",
        ]
    elif is_eq:
        templates = [
            f"{scorer} equalises — {ctx}",
            f"{scorer} pulls one back — {home} and {away} level at {score}",
            f"Great response from {scorer} — {ctx}",
            f"{scorer} restores parity — {score}",
        ]
    elif is_late:
        templates = [
            f"Late goal from {scorer} — {ctx}",
            f"{scorer} seals it late — {ctx}",
            f"{scorer} puts the game to bed with a late strike — {ctx}",
            f"Clinical finish from {scorer} to wrap it up — {ctx}",
        ]
    elif is_stoppage:
        templates = [
            f"Stoppage time drama — {scorer} scores — {ctx}",
            f"{scorer} strikes in injury time — {ctx}",
            f"Late, late goal from {scorer} — {ctx}",
        ]
    elif lead_change:
        templates = [
            f"{scorer} turns the game around — {ctx}",
            f"Lead change! {scorer} fires home — {ctx}",
            f"{scorer} flips the match on its head — {ctx}",
        ]
    else:
        templates = [
            f"{scorer} adds another — {ctx}",
            f"Another goal for {scorer} — {ctx}",
            f"{scorer} extends the lead — {ctx}",
            f"Clinical finish from {scorer} — {ctx}",
            f"{scorer} makes it {score} — {phase}",
        ]

    # Pick deterministically based on goal id (not random) for consistency
    idx = g.get('id', 0) % len(templates)
    return templates[idx]

def run():
    goals   = load('goals.json')
    matches = load('matches.json')
    if not goals:
        print("No goals.json found")
        sys.exit(0)

    to_update = [g for g in goals if needs_description(g)]
    print(f"Goals needing descriptions: {len(to_update)} of {len(goals)}")

    if not to_update:
        print("All goals already have good descriptions ✓")
        sys.exit(0)

    updated = 0
    for g in to_update:
        desc = generate(g, goals)
        g['desc'] = desc
        updated += 1
        print(f"  {g['matchId']} {g['minute']}' {g['scorer']:20s} → {desc[:70]}")

    if updated > 0:
        save('goals.json', goals)
        print(f"\n✓ Generated {updated} descriptions")
        os.system('python update_site.py --section goals')
        os.system('python update_site.py --section snapshot')
    else:
        print("Nothing to update")

if __name__ == '__main__':
    run()
