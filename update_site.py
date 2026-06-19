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

def esc_js(s):
    """Escape a string for safe embedding inside JS single-quoted strings"""
    s = str(s)
    s = s.replace('\\', '\\\\')  # backslashes first
    s = s.replace("'", "\\'"  )      # single quotes
    s = s.replace('\n', ' ')          # newlines
    s = s.replace('\r', '')           # carriage returns
    return s

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
    js_start = c.find('<script>') + len('<script>')
    js_end   = c.find('</script>')
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
            f"  {{id:'{esc_js(m['id'])}', date:'{esc_js(m['date'])}', home:'{esc_js(m['home'])}', "
            f"away:'{esc_js(m['away'])}', hf:'', af:'', score:'{esc_js(m['score'])}', "
            f"group:'{esc_js(m['group'])}', ytId:'{esc_js(m.get('ytId',''))}',"
            f" fifaUrl:'{esc_js(fifa_url)}'}}"
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
    js_start = c.find('<script>') + len('<script>')
    js_end   = c.find('</script>')
    js       = c[js_start:js_end]

    def esc(s):
        s = str(s)
        s = s.replace('\\', '\\\\')  # escape backslashes first
        s = s.replace("'", "\\'"  )      # escape single quotes
        s = s.replace('\n', ' ')          # remove newlines
        s = s.replace('\r', '')           # remove carriage returns
        return s

    entries = []
    for g in data:
        entry = (
            f"  {{id:{g['id']}, matchId:'{esc_js(g['matchId'])}', "
            f"home:'{esc_js(g['home'])}', away:'{esc_js(g['away'])}', hf:'', af:'', "
            f"scorer:'{esc_js(g['scorer'])}', flag:'', minute:{g['minute']}, "
            f"type:'{esc_js(g['type'])}', phase:'{esc_js(g['phase'])}', score:'{esc_js(g['score'])}', "
            f"desc:'{esc_js(g['desc'])}'}}"
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
    js_start = c.find('<script>') + len('<script>')
    js_end   = c.find('</script>')
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
    js_start = c.find('<script>') + len('<script>')
    js_end   = c.find('</script>')
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
    js_start = c.find('<script>') + len('<script>')
    js_end   = c.find('</script>')
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


# ═══════════════════════════════════════════════════════════
# SECTION 5b: SYNC UPCOMING — remove completed matches
# ═══════════════════════════════════════════════════════════
def sync_upcoming():
    """Remove fixtures from upcoming_fixtures.json that are now in match_stats.json"""
    upcoming = load('upcoming_fixtures.json')
    stats    = load('match_stats.json')
    if not upcoming or not stats:
        return

    # Build set of completed match pairs
    completed = set()
    for mid, m in stats.items():
        h = m['home'].lower().strip()
        a = m['away'].lower().strip()
        completed.add((h, a))
        completed.add((a, h))  # both directions

    before = len(upcoming)
    upcoming = [
        f for f in upcoming
        if (f['home'].lower().strip(), f['away'].lower().strip()) not in completed
    ]
    removed = before - len(upcoming)

    if removed > 0:
        import os, json
        path = os.path.join(DATA_DIR, 'upcoming_fixtures.json')
        with open(path, 'w') as f:
            json.dump(upcoming, f, indent=2)
        print(f"  → Removed {removed} completed fixtures from upcoming")
        # Re-run upcoming section
        update_upcoming()
    else:
        print(f"  → No completed fixtures to remove")

# SECTION 6: SNAPSHOT CARDS (analytics page header cards)
# ═══════════════════════════════════════════════════════════
def update_snapshot():
    """Recomputes all snapshot cards from goals.json + match_stats.json.
    buildSnapshotStats() in JS now does this dynamically too,
    but this updates the HTML initial state for first-paint."""
    goals_data = load('goals.json')
    stats_data = load('match_stats.json')
    if not goals_data or not stats_data:
        return
    c = read_html()
    import datetime
    from collections import Counter

    total_goals = len(goals_data)
    match_count = len(stats_data)
    avg = f"{total_goals/match_count:.2f}" if match_count else "0.00"

    own_goals  = [g for g in goals_data if g['type'] == 'own-goal']
    penalties  = [g for g in goals_data if g['type'] == 'penalty']
    headers    = [g for g in goals_data if g['type'] == 'header']
    open_play  = [g for g in goals_data if g['type'] == 'open-play']
    free_kicks = [g for g in goals_data if g['type'] == 'free-kick']

    # Biggest match
    biggest = max(
        stats_data.items(),
        key=lambda x: sum(int(p) for p in x[1]['score'].split('-') if p.isdigit()),
        default=(None, {'home':'?','away':'?','score':'0-0'})
    )
    biggest_goals = sum(int(p) for p in biggest[1]['score'].split('-') if p.isdigit())
    biggest_label = f"{biggest[1]['home']} vs {biggest[1]['away']}"

    # Top scorers — exclude own goals
    scorer_counts = Counter(
        g['scorer'].replace(' OG','').strip()
        for g in goals_data if g['type'] != 'own-goal'
    )
    top_count   = scorer_counts.most_common(1)[0][1] if scorer_counts else 0
    top_scorers = [s for s,n in scorer_counts.items() if n == top_count]
    top_label   = f"Joint Top Scorers ({len(top_scorers)})" if len(top_scorers) > 1 else "Top Scorer"
    def scorer_country(name, goals_data):
        """Find which country a scorer plays for from goals data."""
        for g in goals_data:
            if g.get('scorer') == name and g.get('type') != 'own-goal':
                # Determine team from score direction
                match_goals = [x for x in goals_data
                               if x.get('matchId') == g['matchId'] and x.get('minute',0) < g.get('minute',0)]
                prev = match_goals[-1]['score'] if match_goals else '0-0'
                ph  = int(prev.split('-')[0] or 0)
                ph2 = int(g.get('score','0-0').split('-')[0] or 0)
                return g['home'] if ph2 > ph else g['away']
        return ''

    def fmt_scorer(name, goals_data):
        last = name.split('.')[-1].strip()
        country = scorer_country(name, goals_data)
        return f"{last} · {country}" if country else last

    top_sub = ', '.join(fmt_scorer(s, goals_data) for s in top_scorers[:6])
    if len(top_scorers) > 6:
        top_sub += f' +{len(top_scorers)-6} more'

    # OG sub-text: "in N matches" with tooltip details
    def og_country(g):
        # OG scorer plays for the team whose score DIDN'T increase
        # Find prev goal to determine which team benefited
        match_goals = sorted([x for x in goals_data if x['matchId']==g['matchId'] and x['minute']<g['minute']], key=lambda x: x['minute'])
        prev_score  = match_goals[-1]['score'] if match_goals else '0-0'
        ph_prev = int(prev_score.split('-')[0]) if prev_score.split('-')[0].isdigit() else 0
        ph_now  = int(g['score'].split('-')[0]) if g['score'].split('-')[0].isdigit() else 0
        return g['away'] if ph_now > ph_prev else g['home']
    def og_opponent(g):
        match_goals = sorted([x for x in goals_data if x['matchId']==g['matchId'] and x['minute']<g['minute']], key=lambda x: x['minute'])
        prev_score  = match_goals[-1]['score'] if match_goals else '0-0'
        ph_prev = int(prev_score.split('-')[0]) if prev_score.split('-')[0].isdigit() else 0
        ph_now  = int(g['score'].split('-')[0]) if g['score'].split('-')[0].isdigit() else 0
        return g['home'] if ph_now > ph_prev else g['away']

    og_tip = ' | '.join(
        f"{og_country(g)} ({g['scorer'].replace(' OG','').split('.')[-1].strip()}) vs {og_opponent(g)}"
        for g in own_goals
    )
    og_match_count = len(set((g['home'],g['away']) for g in own_goals))
    og_names = f"in {og_match_count} match{'es' if og_match_count != 1 else ''}"  

    # Penalty sub-text: "in N matches" with tooltip details
    def scorer_country(g):
        parts = g['score'].split('-')
        h, a = int(parts[0]) if parts[0].isdigit() else 0, int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
        return g['home'] if h > a else g['away']
    def scorer_opponent(g):
        parts = g['score'].split('-')
        h, a = int(parts[0]) if parts[0].isdigit() else 0, int(parts[1]) if len(parts)>1 and parts[1].isdigit() else 0
        return g['away'] if h > a else g['home']

    pen_tip = ' | '.join(
        f"{scorer_country(g)} ({g['scorer'].split('.')[-1].strip()}) vs {scorer_opponent(g)}"
        for g in penalties
    )
    pen_match_count = len(set((g['home'],g['away']) for g in penalties))
    pen_names = f"in {pen_match_count} match{'es' if pen_match_count != 1 else ''}"  

    # Goals breakdown
    breakdown = (f"{len(open_play)} open play · {len(headers)} headers · "
                 f"{len(penalties)} penalties · {len(own_goals)} OGs"
                 + (f" · {len(free_kicks)} free kicks" if free_kicks else ""))

    updates = {
        'stat-total-goals': (total_goals, 'Total Goals',
                             f"{avg} per match · {match_count} matches played"),
        'stat-biggest-win': (biggest_goals, biggest_label,
                             'Most goals in a single match'),
        'stat-own-goals':   (len(own_goals),  'Own Goals',     og_names, og_tip),
        'stat-penalties':   (len(penalties),  'Penalties Scored', pen_names, pen_tip),
        'stat-top-team':    (top_count,       top_label,       top_sub),
        'stat-matches':     (f'{match_count} of 104', 'Matches Played', breakdown),
        'stat-alltime':     (16, 'All-Time WC Record Scorer',
                             'Miroslav Klose, GER (2002\u20132014) \u2014 Mbapp\u00E9 on 14'),
    }

    import re
    for card_id, vals in updates.items():
        num, label, sub = vals[0], vals[1], vals[2]
        tip = vals[3] if len(vals) > 3 else None
        c = re.sub(
            rf'(id="{card_id}"><div class="stat-num">)[^<]*(</div>)',
            rf'\g<1>{num}\g<2>', c, count=1)
        c = re.sub(
            rf'(id="{card_id}">.*?<div class="stat-label">)[^<]*(</div>)',
            rf'\g<1>{label}\g<2>', c, count=1, flags=re.DOTALL)
        if tip:
            sub_with_tip = f'<span class="has-tip" data-tip="{tip}" title="{tip}">{sub}</span>'
            c = re.sub(
                rf'(id="{card_id}">.*?<div class="stat-sub">).*?(</div>)',
                rf'\g<1>{sub_with_tip}\g<2>', c, count=1, flags=re.DOTALL)
        else:
            c = re.sub(
                rf'(id="{card_id}">.*?<div class="stat-sub">).*?(</div>)',
                rf'\g<1>{sub}\g<2>', c, count=1, flags=re.DOTALL)

    # Update date
    today = datetime.date.today().strftime("%B %-d, %Y").upper()
    c = re.sub(r'TOURNAMENT SNAPSHOT &mdash; [^<]+<',
               f'TOURNAMENT SNAPSHOT &mdash; {today}<', c, count=1)

    write_html(c)
    print(f"  \u2192 Snapshot: {total_goals} goals · {match_count} matches · "
          f"top={top_count} ({len(top_scorers)} players) · {len(own_goals)} OGs · {len(penalties)} pens")




# ═══════════════════════════════════════════════════════════
# SECTION 7: TEAM FORM — computed from actual WC results
# ═══════════════════════════════════════════════════════════
def update_form():
    """Recomputes team form from actual WC match results.
    Blends pre-tournament form (40%) with WC results (60%).
    win=1.0, draw=0.5, loss=0.0
    Updates team_data.json then patches index.html TEAM_DATA block."""
    matches_data = load('matches.json')
    teams_data   = load('team_data.json')
    if not matches_data or not teams_data:
        return

    # Compute WC results per team
    wc_results = {}
    for m in matches_data:
        score = m.get('score','?-?')
        if '?' in score: continue
        parts = score.split('-')
        if len(parts) != 2: continue
        try:
            h, a = int(parts[0]), int(parts[1])
        except:
            continue
        home, away = m['home'], m['away']
        if home not in wc_results: wc_results[home] = []
        if away not in wc_results: wc_results[away] = []
        if h > a:
            wc_results[home].append(1.0); wc_results[away].append(0.0)
        elif h < a:
            wc_results[home].append(0.0); wc_results[away].append(1.0)
        else:
            wc_results[home].append(0.5); wc_results[away].append(0.5)

    # Short name → full name aliases (matches.json uses short, team_data.json uses full)
    NAME_ALIASES = {
        'S. Korea':'South Korea', 'S. Africa':'South Africa',
        'DR Congo':'Congo DR', 'Ivory Coast':"Côte d'Ivoire",
        'Bosnia':'Bosnia and Herzegovina', 'Curacao':'Curaçao',
        'Cape Verde':'Cabo Verde',
    }

    # Update form values — floor 0.10 so no team ever shows 0%
    updated = 0
    for team, results in wc_results.items():
        full_name = NAME_ALIASES.get(team, team)
        target = full_name if full_name in teams_data else (team if team in teams_data else None)
        if target:
            avg = sum(results) / len(results)
            old = teams_data[target].get('form', 0.7)
            teams_data[target]['form'] = round(max(0.10, old * 0.4 + avg * 0.6), 2)
            updated += 1

    import os, json as _json
    path = os.path.join(DATA_DIR, 'team_data.json')
    with open(path, 'w') as f:
        _json.dump(teams_data, f, indent=2)

    # Patch TEAM_DATA in index.html — form AND marketPct
    c = read_html()
    js_start = c.find('<script>') + len('<script>')
    js = c[js_start:c.find('</script>')]

    import re
    form_updated = 0
    pct_updated  = 0
    for team, data in teams_data.items():
        form_val = data.get('form', 0.7)
        pct_val  = data.get('marketPct', 0)
        pattern_form = rf"('{re.escape(team)}':\s*\{{[^}}]*?form:)([\d.]+)"
        pattern_pct  = rf"('{re.escape(team)}':\s*\{{[^}}]*?marketPct:)([\d.]+)"
        new_js = re.sub(pattern_form, rf'\g<1>{form_val}', js, count=1)
        if new_js != js:
            js = new_js
            form_updated += 1
        new_js2 = re.sub(pattern_pct, rf'\g<1>{pct_val}', js, count=1)
        if new_js2 != js:
            js = new_js2
            pct_updated += 1

    c = c[:js_start] + js + c[c.find('</script>'):]
    write_html(c)
    print(f"  → Form updated for {form_updated} teams, marketPct for {pct_updated} teams")

# ═══════════════════════════════════════════════════════════
# SECTIONS + MAIN
# ═══════════════════════════════════════════════════════════
SECTIONS = {
    'matches':  update_matches,
    'goals':    update_goals,
    'stats':    update_match_stats,
    'groups':   update_groups,
    'upcoming': update_upcoming,
    'sync':     sync_upcoming,
    'snapshot': update_snapshot,
    'form':     update_form,
}

if __name__ == '__main__':
    import sys
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
