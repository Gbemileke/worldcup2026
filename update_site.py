#!/usr/bin/env python3
"""
update_site.py — Master update script for WC 2026 Analytics
═══════════════════════════════════════════════════════════
Reads all JSON data files and patches index.html in-place.
Run this whenever any data file changes.

Usage:
  python update_site.py                  # update everything
  python update_site.py --section goals  # update only goals
  python update_site.py --section stats  # update only match stats
  python update_site.py --section groups # update only group odds
  python update_site.py --section upcoming # update ticker fixtures
  python update_site.py --section snapshot # update analytics cards

Called by GitHub Actions after football-data.org fetches new data.
"""

import json, re, sys, os

HTML_FILE   = 'index.html'
DATA_DIR    = 'data'
BASE_URL    = 'https://raw.githubusercontent.com/gbemileke/worldcup2026/main/data/'
FIFA_BASE   = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'

def load(fname):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        print(f"  ⚠ {fname} not found, skipping")
        return None
    with open(path) as f:
        return json.load(f)

def read_html():
    with open(HTML_FILE) as f:
        return f.read()

def write_html(content):
    with open(HTML_FILE, 'w') as f:
        f.write(content)
    print(f"  ✓ {HTML_FILE} updated")

# ═══════════════════════════════════════════════════════════
# SECTION 1: MATCHES + FIFA LINKS
# ═══════════════════════════════════════════════════════════
def update_matches():
    data = load('matches.json')
    if not data:
        return
    c = read_html()
    js_start = c.rfind('<script>') + len('<script>')
    js_end   = c.rfind('</script>')
    js       = c[js_start:js_end]

    # Build new MATCHES array
    entries = []
    for m in data:
        fifa_url = m.get('fifaUrl','')
        if not fifa_url and m.get('score','') and m['score'] != '?-?':
            # Auto-generate FIFA URL from team names
            h = m['home'].lower().replace(' ','-').replace('.','').replace("'",'')
            a = m['away'].lower().replace(' ','-').replace('.','').replace("'",'')
            h = h.replace('ivory-coast','cote-divoire').replace('south-africa','south-africa')
            fifa_url = f"{FIFA_BASE}{h}-v-{a}-highlights-match-report"
        
        entry = (
            f"  {{id:'{m['id']}', date:'{m['date']}', home:'{m['home']}', "
            f"away:'{m['away']}', hf:'', af:'', score:'{m['score']}', "
            f"group:'{m['group']}', ytId:'{m.get('ytId','')}',"
            f" fifaUrl:'{fifa_url}'}}"
        )
        entries.append(entry)

    new_matches = 'var MATCHES = [\n' + ',\n'.join(entries) + '\n];'
    
    old_start = js.find('var MATCHES = [')
    old_end   = js.find('\n];', old_start) + 3
    js = js[:old_start] + new_matches + js[old_end:]

    c = c[:js_start] + js + c[js_end:]
    write_html(c)
    print(f"  → {len(data)} matches written")

# ═══════════════════════════════════════════════════════════
# SECTION 2: GOALS
# ═══════════════════════════════════════════════════════════
def update_goals():
    data = load('goals.json')
    if not data:
        return
    c = read_html()
    js_start = c.rfind('<script>') + len('<script>')
    js_end   = c.rfind('</script>')
    js       = c[js_start:js_end]

    def esc(s):
        return str(s).replace("'","\\'").replace('\n',' ')

    entries = []
    for g in data:
        entry = (
            f"  {{id:{g['id']}, matchId:'{g['matchId']}', "
            f"home:'{g['home']}', away:'{g['away']}', hf:'', af:'', "
            f"scorer:'{esc(g['scorer'])}', flag:'', minute:{g['minute']}, "
            f"type:'{g['type']}', phase:'{g['phase']}', score:'{g['score']}', "
            f"desc:'{esc(g['desc'])}'}}"
        )
        entries.append(entry)

    new_goals = 'var GOALS = [\n' + ',\n'.join(entries) + '\n];'

    old_start = js.find('var GOALS = [')
    # Find the closing ]; of GOALS
    bracket_depth = 0; i = old_start
    while i < len(js):
        if js[i] == '[': bracket_depth += 1
        elif js[i] == ']':
            bracket_depth -= 1
            if bracket_depth == 0:
                old_end = i + 1
                while old_end < len(js) and js[old_end] in ' \t;': old_end += 1
                break
        i += 1
    js = js[:old_start] + new_goals + '\n\n' + js[old_end:]

    c = c[:js_start] + js + c[js_end:]
    write_html(c)
    print(f"  → {len(data)} goals written")

# ═══════════════════════════════════════════════════════════
# SECTION 3: MATCH STATS
# ═══════════════════════════════════════════════════════════
def update_match_stats():
    data = load('match_stats.json')
    if not data:
        return
    c = read_html()
    js_start = c.rfind('<script>') + len('<script>')
    js_end   = c.rfind('</script>')
    js       = c[js_start:js_end]

    entries = []
    for mid, m in sorted(data.items(), key=lambda x: int(x[0].replace('m',''))):
        stats_str = json.dumps(m['stats'])
        xtra_str  = json.dumps(m['xtra'])
        # Escape apostrophes in text fields
        home_esc  = m['home'].replace("'", "\\'")
        away_esc  = m['away'].replace("'", "\\'")
        score_esc = m['score'].replace("'", "\\'")
        date_esc  = m['date'].replace("'", "\\'")
        entry = (
            f"  {mid}: {{home:'{home_esc}', away:'{away_esc}', hf:'', af:'', "
            f"score:'{score_esc}', date:'{date_esc}', "
            f"poss:{json.dumps(m['poss'])}, stats:{stats_str}, xtra:{xtra_str}}}"
        )
        entries.append(entry)

    new_ms = 'var MATCH_STATS = {\n' + ',\n'.join(entries) + '\n};'
    
    old_start = js.find('var MATCH_STATS = {')
    # Find the closing }; of MATCH_STATS (not everything until next function)
    depth = 0
    i = old_start
    while i < len(js):
        if js[i] == '{': depth += 1
        elif js[i] == '}':
            depth -= 1
            if depth == 0:
                old_end = i + 1
                # Skip trailing whitespace/semicolon
                while old_end < len(js) and js[old_end] in ' \t;\n':
                    old_end += 1
                break
        i += 1
    js = js[:old_start] + new_ms + '\n\n' + js[old_end:]

    c = c[:js_start] + js + c[js_end:]
    write_html(c)
    print(f"  → {len(data)} match stats written")

# ═══════════════════════════════════════════════════════════
# SECTION 4: GROUPS (Polymarket + FanDuel odds)
# ═══════════════════════════════════════════════════════════
def update_groups():
    data = load('groups.json')
    if not data:
        return
    c = read_html()
    js_start = c.rfind('<script>') + len('<script>')
    js_end   = c.rfind('</script>')
    js       = c[js_start:js_end]

    group_entries = []
    for letter in 'ABCDEFGHIJKL':
        if letter not in data:
            continue
        g = data[letter]
        teams_str = ',\n'.join([
            f"      {{name:'{t['name']}', polymarket:{t['polymarket']}, fanDuelOdds:{t['fanDuelOdds']}}}"
            for t in g['teams']
        ])
        entry = (
            f"  {letter}: {{\n"
            f"    name: '{g['name']}', venue: '{g['venue']}',\n"
            f"    teams: [\n{teams_str}\n    ]\n"
            f"  }}"
        )
        group_entries.append(entry)

    new_groups = '\n\nvar GROUPS = {\n' + ',\n'.join(group_entries) + '\n};\n'

    old_start = js.find('var GROUPS = {')
    old_end   = js.find('var PRESETS', old_start)
    js = js[:old_start] + new_groups + '\n\n' + js[old_end:]

    c = c[:js_start] + js + c[js_end:]
    write_html(c)
    print(f"  → {len(data)} groups written")

# ═══════════════════════════════════════════════════════════
# SECTION 5: UPCOMING FIXTURES (ticker)
# ═══════════════════════════════════════════════════════════
def update_upcoming():
    data = load('upcoming_fixtures.json')
    if not data:
        return
    c = read_html()
    js_start = c.rfind('<script>') + len('<script>')
    js_end   = c.rfind('</script>')
    js       = c[js_start:js_end]

    entries = []
    for f in data:
        entry = (
            f"  {{date:'{f['date']}', home:'{f['home']}', away:'{f['away']}', "
            f"time:'{f['time']}', group:'{f['group']}'}}"
        )
        entries.append(entry)

    new_uf = 'var UPCOMING_FIXTURES = [\n' + ',\n'.join(entries) + '\n];'
    
    old_start = js.find('var UPCOMING_FIXTURES = [')
    old_end   = js.find('];', old_start) + 2
    js = js[:old_start] + new_uf + js[old_end:]

    c = c[:js_start] + js + c[js_end:]
    write_html(c)
    print(f"  → {len(data)} upcoming fixtures written")

# ═══════════════════════════════════════════════════════════
# SECTION 6: SNAPSHOT CARDS (analytics page header cards)
# ═══════════════════════════════════════════════════════════
def update_snapshot():
    """Recomputes snapshot from goals.json + match_stats.json"""
    goals_data = load('goals.json')
    stats_data = load('match_stats.json')
    if not goals_data or not stats_data:
        return
    c = read_html()

    total_goals = len(goals_data)
    match_count = len(stats_data)
    avg = f"{total_goals/match_count:.2f}" if match_count else "0.00"
    own_goals   = [g for g in goals_data if g['type'] == 'own-goal']
    penalties   = [g for g in goals_data if g['type'] == 'penalty']

    # Top scorers
    from collections import Counter
    scorer_counts = Counter(g['scorer'] for g in goals_data if g['type'] != 'own-goal')
    top_count = scorer_counts.most_common(1)[0][1] if scorer_counts else 0
    top_scorers = [s for s,n in scorer_counts.items() if n == top_count]

    # Biggest match
    biggest = max(stats_data.items(), 
                  key=lambda x: sum(int(p) for p in x[1]['score'].split('-') if p.isdigit()),
                  default=(None,None))
    biggest_label = f"{biggest[1]['home']} vs {biggest[1]['away']}" if biggest[0] else "—"
    biggest_goals = sum(int(p) for p in biggest[1]['score'].split('-') if p.isdigit()) if biggest[0] else 0

    # Own goal names (without OG suffix)
    og_names = ', '.join(g['scorer'].replace(' OG','') for g in own_goals)
    pen_names = ', '.join(f"{g['scorer']} ({g['phase'].split()[1] if ' ' in g['phase'] else g['phase'][:3]})" for g in penalties)
    top_names = ', '.join(top_scorers[:3]) + (f' + {len(top_scorers)-3} more' if len(top_scorers) > 3 else '')

    updates = {
        'stat-total-goals': (total_goals, 'Total Goals', f"{avg} per match avg ({match_count} matches)"),
        'stat-biggest-win': (biggest_goals, biggest_label, 'Most goals in one match'),
        'stat-own-goals':   (len(own_goals), 'Own Goals', og_names or '—'),
        'stat-penalties':   (len(penalties), 'Penalties Scored', pen_names or '—'),
        'stat-top-team':    (top_count, f'Joint Top Scorers' if len(top_scorers) > 1 else 'Top Scorer', top_names),
        'stat-matches':     (match_count, 'Matches Played', f"{len([g for g in goals_data if g['type']=='header'])} headers · {len(penalties)} penalties · {len(own_goals)} OGs"),
        'stat-alltime':     (16, 'All-Time WC Record', 'Miroslav Klose, GER (2002–2014) — Mbappé on 14'),
    }

    for card_id, (num, label, sub) in updates.items():
        # Replace num
        c = re.sub(
            rf'(id="{card_id}"><div class="stat-num">)\d+(</div>)',
            rf'\g<1>{num}\2', c, count=1)
        # Replace label
        c = re.sub(
            rf'(id="{card_id}">.*?<div class="stat-label">)[^<]*(</div>)',
            rf'\g<1>{label}\2', c, count=1, flags=re.DOTALL)
        # Replace sub
        c = re.sub(
            rf'(id="{card_id}">.*?<div class="stat-sub">)[^<]*(</div>)',
            rf'\g<1>{sub}\2', c, count=1, flags=re.DOTALL)

    # Update snapshot date
    import datetime
    today = datetime.date.today().strftime("%B %-d, %Y").upper()
    c = re.sub(r'TOURNAMENT SNAPSHOT &mdash; [^<]+<', f'TOURNAMENT SNAPSHOT &mdash; {today}<', c, count=1)

    write_html(c)
    print(f"  → Snapshot: {total_goals} goals, {match_count} matches, top={top_count}")

# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
SECTIONS = {
    'matches':  update_matches,
    'goals':    update_goals,
    'stats':    update_match_stats,
    'groups':   update_groups,
    'upcoming': update_upcoming,
    'snapshot': update_snapshot,
}

if __name__ == '__main__':
    section = None
    if len(sys.argv) >= 3 and sys.argv[1] == '--section':
        section = sys.argv[2]

    if section:
        if section in SECTIONS:
            print(f"Updating {section}...")
            SECTIONS[section]()
        else:
            print(f"Unknown section: {section}. Options: {list(SECTIONS.keys())}")
            sys.exit(1)
    else:
        print("Updating all sections...")
        for name, fn in SECTIONS.items():
            print(f"\n[{name}]")
            fn()
        print("\n✅ All sections updated.")
