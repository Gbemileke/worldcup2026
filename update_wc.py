#!/usr/bin/env python3
"""
update_wc.py — WC 2026 One-Stop Update Script
═══════════════════════════════════════════════════════════════════════════════
Safely updates index.html with the latest data. Run after each match finishes.

Usage:
  python update_wc.py                        # full update (all sections)
  python update_wc.py --section stats        # match stats only
  python update_wc.py --section knockout     # knockout results only
  python update_wc.py --section goals        # goals only
  python update_wc.py --section upcoming     # upcoming fixtures only
  python update_wc.py --section form         # team form only
  python update_wc.py --section snapshot     # snapshot cards only

Data files read from ./data/ directory:
  goals.json              — all goal events (source of truth)
  match_stats.json        — possession, shots, xG per match
  knockout_results.json   — R32/R16/QF/SF results as they happen
  upcoming_fixtures.json  — remaining fixture schedule
  team_data.json          — team form / market odds

After running, commit and push:
  git add index.html data/ && git commit -m "update: matchday N" && git push
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import re, re, os, sys, datetime

HTML_FILE = 'index.html'
DATA_DIR  = 'data'

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def esc(s):
    """Escape for JS single-quoted string."""
    return str(s).replace('\\','\\\\').replace("'","\\'").replace('\n',' ').replace('\r','')

def load(fname):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        print(f'  ⚠  {fname} not found — skipping')
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)

def save(fname, data):
    path = os.path.join(DATA_DIR, fname)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def read_html():
    with open(HTML_FILE, encoding='utf-8') as f:
        return f.read()

def write_html(c):
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(c)
    size_kb = len(c) // 1024
    print(f'  ✓  index.html written ({size_kb} KB)')

def replace_js_block(html, start_marker, end_token, new_block):
    """
    Replace a JS block that starts with start_marker and ends with end_token.
    end_token = '];\n' for arrays, '\n};\n' for objects (brace-safe version uses depth).
    Returns (new_html, replaced: bool).
    """
    idx = html.find(start_marker)
    if idx < 0:
        print(f'  ⚠  marker not found: {start_marker[:40]}')
        return html, False
    end_idx = html.find(end_token, idx)
    if end_idx < 0:
        print(f'  ⚠  end token not found for: {start_marker[:40]}')
        return html, False
    end_idx += len(end_token)
    return html[:idx] + new_block + html[end_idx:], True

def replace_js_object(html, var_name, new_block):
    """
    Replace a JS object (var X = { ... };) using brace depth tracking.
    Safe for nested objects like MATCH_STATS.
    IMPORTANT: preserves everything after the block (was the source of truncation bugs).
    """
    marker = f'var {var_name} = {{'
    idx = html.find(marker)
    if idx < 0:
        marker = f'var {var_name}={{'
        idx = html.find(marker)
    if idx < 0:
        print(f'  ⚠  {var_name} not found in HTML')
        return html, False

    depth = 0
    i = idx
    end_idx = None
    while i < len(html):
        if html[i] == '{':
            depth += 1
        elif html[i] == '}':
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                # consume trailing semicolon only (NOT newlines — preserve spacing)
                if end_idx < len(html) and html[end_idx] == ';':
                    end_idx += 1
                break
        i += 1

    if end_idx is None:
        print(f'  ⚠  could not find end of {var_name}')
        return html, False

    # CRITICAL: html[:idx] + new_block + html[end_idx:] — preserve tail
    return html[:idx] + new_block + html[end_idx:], True


# ─────────────────────────────────────────────────────────────────────────────
# SECTION: GOALS
# ─────────────────────────────────────────────────────────────────────────────

def update_goals():
    data = load('goals.json')
    if not data:
        return

    # Permanent goal-type overrides — never let the scraper reset these
    OVERRIDES = {
        ('m39', 'K. Pina',    21): 'free-kick',
        ('m27', 'N. Saliba',  68): 'free-kick',
        ('m45', 'N. Mendes',  17): 'free-kick',
    }
    for g in data:
        key = (g.get('matchId'), g.get('scorer'), g.get('minute'))
        if key in OVERRIDES and g.get('type') not in ('penalty','own-goal'):
            g['type'] = OVERRIDES[key]

    entries = []
    for g in data:
        entries.append(
            f"  {{id:{g['id']}, matchId:'{esc(g['matchId'])}', "
            f"home:'{esc(g['home'])}', away:'{esc(g['away'])}', hf:'', af:'', "
            f"scorer:'{esc(g['scorer'])}', flag:'', minute:{g['minute']}, "
            f"type:'{esc(g['type'])}', phase:'{esc(g['phase'])}', "
            f"score:'{esc(g['score'])}', desc:'{esc(g.get('desc',''))}'}}"
        )

    new_block = 'var GOALS = [\n' + ',\n'.join(entries) + '\n];'
    html = read_html()
    html, ok = replace_js_block(html, 'var GOALS = [', '\n];', new_block + '\n')
    if ok:
        write_html(html)
        print(f'  →  {len(data)} goals written')


# ─────────────────────────────────────────────────────────────────────────────
# SECTION: MATCH STATS
# ─────────────────────────────────────────────────────────────────────────────

def update_stats():
    """
    MERGE new ESPN stats into existing MATCH_STATS.
    Never replaces — only adds/updates entries that exist in match_stats.json.
    Only processes m1-m72 (group stage). Knockout stats (m73+) are ignored.
    This preserves manually-built stats that ESPN hasn't scraped yet.
    """
    new_data = load('match_stats.json')
    if not new_data:
        return

    html = read_html()

    # Parse existing MATCH_STATS from index.html
    ms_start = html.find('var MATCH_STATS = {')
    ms_end   = html.find('\n};', ms_start) + 3
    existing_block = html[ms_start:ms_end]

    # Build a dict of existing entries (preserve what we have)
    existing_entries = {}
    for m in re.finditer(r"  (m\d+): (\{[^}]+(?:\{[^}]*\}[^}]*)*\})", existing_block):
        mid, body = m.group(1), m.group(2)
        try:
            num = int(mid.replace('m',''))
            if 1 <= num <= 72:
                existing_entries[mid] = body
        except ValueError:
            pass

    # Merge: overlay new ESPN data (group stage only)
    updated_count = 0
    for mid, m in new_data.items():
        try:
            num = int(mid.replace('m','').replace('M',''))
        except ValueError:
            continue
        if num < 1 or num > 72:
            continue  # never write knockout stats to MATCH_STATS
        mid_lower = f'm{num}'
        home_e  = esc(m['home'])
        away_e  = esc(m['away'])
        score_e = esc(m['score'])
        date_e  = esc(m['date'])
        entry = (
            f"{{home:'{home_e}', away:'{away_e}', hf:'', af:'', "
            f"score:'{score_e}', date:'{date_e}', "
            f"poss:{json.dumps(m['poss'])}, "
            f"stats:{json.dumps(m['stats'])}, "
            f"xtra:{json.dumps(m['xtra'])}}}"
        )
        if existing_entries.get(mid_lower) != entry:
            existing_entries[mid_lower] = entry
            updated_count += 1

    # Rebuild sorted block
    entries = []
    for mid in sorted(existing_entries.keys(), key=lambda x: int(x.replace('m',''))):
        entries.append(f"  {mid}: {existing_entries[mid]}")

    new_block = 'var MATCH_STATS = {\n' + ',\n'.join(entries) + '\n};'
    html, ok = replace_js_object(html, 'MATCH_STATS', new_block + '\n\n')
    if ok:
        write_html(html)
        total = len(existing_entries)
        print(f'  →  {total} match stats in MATCH_STATS ({updated_count} updated from ESPN, {total-updated_count} preserved)')
    else:
        print('  ⚠  MATCH_STATS not found in index.html')


# ─────────────────────────────────────────────────────────────────────────────
# SECTION: KNOCKOUT RESULTS
# Reads data/knockout_results.json and patches KNOCKOUT_RESULTS in index.html.
#
# knockout_results.json format:
# {
#   "M73": {"home":"S. Africa","away":"Canada","score":"1-3","winner":"Canada"},
#   "M74": {"home":"Germany",  "away":"Paraguay","score":"3-1","winner":"Germany"},
#   ...
# }
# Covers R32 (M73-M88), R16 (M89-M96), QF (M97-M100), SF (M101-M102)
# ─────────────────────────────────────────────────────────────────────────────

# Official match order for all knockout rounds
KNOCKOUT_IDS = [
    # R32
    'M73','M74','M75','M76','M77','M78','M79','M80',
    'M81','M82','M83','M84','M85','M86','M87','M88',
    # R16
    'M89','M90','M91','M92','M93','M94','M95','M96',
    # QF
    'M97','M98','M99','M100',
    # SF
    'M101','M102',
]

def update_knockout():
    data = load('knockout_results.json')
    if data is None:
        data = {}

    lines = [
        'var KNOCKOUT_RESULTS = {',
        '  // Populated by update_wc.py as matches finish.',
        '  // Add results to data/knockout_results.json then run:',
        '  //   python update_wc.py --section knockout',
    ]
    for mid in KNOCKOUT_IDS:
        if mid in data:
            r = data[mid]
            h  = esc(r.get('home',''))
            a  = esc(r.get('away',''))
            sc = esc(r.get('score',''))
            w  = esc(r.get('winner',''))
            lines.append(f"  {mid}: {{home:'{h}', away:'{a}', score:'{sc}', winner:'{w}'}},")
    lines.append('};')

    new_block = '\n'.join(lines)
    html = read_html()

    # Find and replace KNOCKOUT_RESULTS block
    start = html.find('var KNOCKOUT_RESULTS')
    if start < 0:
        print('  ⚠  KNOCKOUT_RESULTS not found in index.html')
        return
    end = html.find('\n};', start) + 3
    html = html[:start] + new_block + '\n' + html[end:]
    write_html(html)
    n = len([k for k in data if k in KNOCKOUT_IDS])
    print(f'  →  KNOCKOUT_RESULTS: {n} results recorded')

    # Also update UPCOMING_FIXTURES to reflect resolved teams
    _sync_upcoming_from_knockout(data)


def _sync_upcoming_from_knockout(knockout_data):
    """
    Update UPCOMING_FIXTURES in index.html so that R16/QF/SF entries
    show real team names once the R32/R16/QF is done.
    """
    # Map Wxx → winner name
    resolved = {}
    for mid, r in knockout_data.items():
        if r.get('winner'):
            num = mid[1:]   # 'M73' → '73'
            resolved[f'W{num}'] = r['winner']

    html = read_html()
    uf_start = html.find('var UPCOMING_FIXTURES')
    if uf_start < 0:
        return
    uf_end = html.find('];', uf_start) + 2
    uf_block = html[uf_start:uf_end]

    changed = False
    def _resolve_ref(ref):
        nonlocal changed
        if ref in resolved:
            changed = True
            return resolved[ref]
        return ref

    # Replace Wxx references inside home/away fields
    def _sub(m):
        field = m.group(1)   # 'home' or 'away'
        val   = m.group(2)
        new_val = _resolve_ref(val)
        return f"{field}:'{new_val}'"

    new_uf_block = re.sub(r"(home|away):'(W\d+)'", _sub, uf_block)

    if changed:
        html = html[:uf_start] + new_uf_block + html[uf_end:]
        write_html(html)
        print(f'  →  Upcoming fixtures: team names resolved from knockout results')


# ─────────────────────────────────────────────────────────────────────────────
# SECTION: UPCOMING FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

def update_upcoming():
    data = load('upcoming_fixtures.json')
    if not data:
        return

    # Only show R32 fixtures (known teams). R16+ shown dynamically via getKnownFixtures().
    r32 = [f for f in data if f.get('round','').upper() in ('R32','GROUP STAGE','') 
           or f.get('group','')]
    # Fall back to all if no R32 found
    show = r32 if r32 else data

    entries = []
    for f in show:
        rnd   = esc(f.get('round', 'R32'))
        grp   = esc(f.get('group', ''))
        entry = (
            f"  {{date:'{esc(f['date'])}', home:'{esc(f['home'])}', "
            f"away:'{esc(f['away'])}', time:'{esc(f['time'])}', "
            f"venue:'{esc(f.get('venue',''))}', "
            f"group:'{grp}', matchId:'{esc(f.get('matchId',''))}', round:'{rnd}'}}"
        )
        entries.append(entry)

    new_block = 'var UPCOMING_FIXTURES = [\n' + ',\n'.join(entries) + '\n];'
    html = read_html()
    html, ok = replace_js_block(html, 'var UPCOMING_FIXTURES = [', '];', new_block)
    if ok:
        write_html(html)
        print(f'  →  {len(show)} upcoming fixtures written')


# ─────────────────────────────────────────────────────────────────────────────
# SECTION: TEAM FORM
# ─────────────────────────────────────────────────────────────────────────────

def update_form():
    teams_data   = load('team_data.json')
    matches_data = load('matches.json')
    if not teams_data or not matches_data:
        return

    NAME_ALIASES = {
        'S. Korea':'South Korea','S. Africa':'South Africa',
        'DR Congo':'Congo DR','Ivory Coast':"Côte d'Ivoire",
        'Bosnia':'Bosnia and Herzegovina','Curacao':'Curaçao',
        'Cape Verde':'Cabo Verde',
    }

    wc_results = {}
    for m in matches_data:
        sc = m.get('score','?-?')
        if '?' in sc or '-' not in sc:
            continue
        try:
            h, a = map(int, sc.split('-'))
        except ValueError:
            continue
        home, away = m['home'], m['away']
        wc_results.setdefault(home, [])
        wc_results.setdefault(away, [])
        if h > a:   wc_results[home].append(1.0); wc_results[away].append(0.0)
        elif h < a: wc_results[home].append(0.0); wc_results[away].append(1.0)
        else:       wc_results[home].append(0.5); wc_results[away].append(0.5)

    updated = 0
    for team, results in wc_results.items():
        full = NAME_ALIASES.get(team, team)
        target = full if full in teams_data else (team if team in teams_data else None)
        if not target or not results:
            continue
        td = teams_data[target]
        qw = td.get('qualW',0); qd = td.get('qualD',0); ql = td.get('qualL',0)
        qtot = qw + qd + ql
        base = (qw + 0.5*qd) / qtot if qtot else td.get('form', 0.5)
        avg  = sum(results) / len(results)
        td['form'] = round(max(0.10, base*0.4 + avg*0.6), 3)
        updated += 1

    save('team_data.json', teams_data)

    # Patch TEAM_DATA in index.html
    html = read_html()
    js_s = html.find('<script>') + 8
    js   = html[js_s:html.find('</script>')]
    form_n = pct_n = 0
    for team, td in teams_data.items():
        fv = td.get('form', 0.5)
        pv = td.get('marketPct', 0)
        pat_f = rf"('{re.escape(team)}':\s*\{{[^}}]*?form:)([\d.]+)"
        pat_p = rf"('{re.escape(team)}':\s*\{{[^}}]*?marketPct:)([\d.]+)"
        new_js = re.sub(pat_f, rf'\g<1>{fv}', js, count=1)
        if new_js != js: js = new_js; form_n += 1
        new_js = re.sub(pat_p, rf'\g<1>{pv}', js, count=1)
        if new_js != js: js = new_js; pct_n += 1

    html = html[:js_s] + js + html[html.find('</script>'):]
    write_html(html)
    print(f'  →  Form updated {updated} teams; form patches={form_n}, pct patches={pct_n}')


# ─────────────────────────────────────────────────────────────────────────────
# SECTION: SNAPSHOT CARDS
# ─────────────────────────────────────────────────────────────────────────────

def update_snapshot():
    from collections import Counter
    goals_data = load('goals.json')
    stats_data = load('match_stats.json')
    if not goals_data or not stats_data:
        return

    total  = len(goals_data)
    played = len(stats_data)
    avg    = f'{total/played:.2f}' if played else '0.00'

    own      = [g for g in goals_data if g['type']=='own-goal']
    pens     = [g for g in goals_data if g['type']=='penalty']
    fks      = [g for g in goals_data if g['type']=='free-kick']
    headers  = [g for g in goals_data if g['type']=='header']
    open_p   = [g for g in goals_data if g['type']=='open-play']

    biggest = max(
        stats_data.items(),
        key=lambda x: sum(int(p) for p in x[1]['score'].split('-') if p.isdigit()),
        default=(None,{'home':'?','away':'?','score':'0-0'})
    )
    bg = sum(int(p) for p in biggest[1]['score'].split('-') if p.isdigit())
    bg_lbl = f"{biggest[1]['home']} vs {biggest[1]['away']}"

    cnts   = Counter(g['scorer'] for g in goals_data if g['type']!='own-goal')
    top_n  = cnts.most_common(1)[0][1] if cnts else 0
    top_sc = [s for s,n in cnts.items() if n==top_n]
    top_lbl= f"Joint Top Scorers ({len(top_sc)})" if len(top_sc)>1 else "Top Scorer"
    top_sub= ', '.join(s.split('.')[-1].strip() for s in top_sc[:6])
    if len(top_sc) > 6: top_sub += f' +{len(top_sc)-6} more'

    total_y = sum(r[1]+r[2] for s in stats_data.values() for r in s.get('xtra',[]) if r[0]=='Yellow Cards')
    total_r = sum(r[1]+r[2] for s in stats_data.values() for r in s.get('xtra',[]) if r[0]=='Red Cards')
    bkdn    = (f"{len(open_p)} open play · {len(headers)} headers · "
               f"{len(pens)} penalties · {len(own)} OGs"
               + (f" · {len(fks)} free kicks" if fks else ""))

    updates = {
        'stat-total-goals': (total,    'Total Goals',         f'{avg} per match · {played} matches played'),
        'stat-biggest-win': (bg,       bg_lbl,                'Most goals in a single match'),
        'stat-own-goals':   (len(own), 'Own Goals',           f'in {len(set((g["home"],g["away"]) for g in own))} matches'),
        'stat-penalties':   (len(pens),'Penalties Scored',    f'in {len(set((g["home"],g["away"]) for g in pens))} matches'),
        'stat-top-team':    (top_n,    top_lbl,               top_sub),
        'stat-matches':     (f'{played} of 104','Matches Played', bkdn),
        'stat-discipline':  (total_r,  'Red Cards',           f'Yellow cards: {total_y}'),
    }

    html = read_html()
    for cid, (num, lbl, sub) in updates.items():
        html = re.sub(
            rf'(id="{cid}"><div class="stat-num">)[^<]*(</div>)',
            rf'\g<1>{num}\g<2>', html, count=1)
        html = re.sub(
            rf'(id="{cid}">.*?<div class="stat-sub">).*?(</div>)',
            rf'\g<1>{sub}\g<2>', html, count=1, flags=re.DOTALL)

    today = datetime.date.today().strftime('%B %-d, %Y').upper()
    html  = re.sub(r'TOURNAMENT SNAPSHOT &mdash; [^<]+<',
                   f'TOURNAMENT SNAPSHOT &mdash; {today}<', html, count=1)
    write_html(html)
    print(f'  →  Snapshot: {total} goals · {played} matches · top={top_n}')


# ─────────────────────────────────────────────────────────────────────────────
# BUILD STAMP
# ─────────────────────────────────────────────────────────────────────────────

def update_stamp():
    html = read_html()
    ts   = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    html = re.sub(r'<!-- build: [^>]+ -->\n?', '', html)
    html = html.replace('<!DOCTYPE html>', f'<!DOCTYPE html>\n<!-- build: {ts} -->', 1)
    write_html(html)
    print(f'  →  Build stamp: {ts}')


# ─────────────────────────────────────────────────────────────────────────────
# ALSO update match stats via the scraper if available
# ─────────────────────────────────────────────────────────────────────────────

def run_scraper():
    """Run update_match_stats.py to fetch latest scores/goals/stats from ESPN."""
    import subprocess
    if not os.path.exists('update_match_stats.py'):
        print('  ⚠  update_match_stats.py not found — skipping scrape')
        return
    print('  Running update_match_stats.py scraper...')
    r = subprocess.run([sys.executable, 'update_match_stats.py'],
                       capture_output=False, text=True)
    if r.returncode != 0:
        print(f'  ⚠  Scraper exited with code {r.returncode}')


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: VALIDATE
# Runs all data consistency checks and auto-fixes what it can.
# Run: python update_wc.py --section validate
# ═══════════════════════════════════════════════════════════════════════════════

def validate_and_fix():
    import json

    html  = read_html()
    s0    = html.find('<script>') + 8
    e0    = html.find('</script>', s0)
    js    = html[s0:e0]
    changed = False
    errors = []
    fixes  = []

    print("  ── 1. Parse MATCHES ──")
    ms = html.find("var MATCHES = ["); me = html.find("\n];", ms) + 3
    matches = {}
    for m in re.finditer(
        r"\{id:'(m\d+)'[^}]*home:'([^']*)'[^}]*away:'([^']*)'[^}]*score:'([^']*)'",
        html[ms:me]):
        matches[m.group(1)] = {'home': m.group(2), 'away': m.group(3), 'score': m.group(4)}
    print(f"    {len(matches)} matches found (m1–m{max(int(x[1:]) for x in matches)})")

    print("  ── 2. Parse GOALS ──")
    gs = html.find("var GOALS = ["); ge = html.find("\n];", gs)
    goal_list = re.findall(
        r"\{id:(\d+), matchId:'([^']*)', home:'([^']*)', away:'([^']*)'[^}]*"
        r"scorer:'([^']*)'[^}]*minute:(\d+)[^}]*type:'([^']*)'[^}]*score:'([^']*)'",
        html[gs:ge])
    gc = {}
    for g in goal_list:
        gc[g[1]] = gc.get(g[1], 0) + 1
    print(f"    {len(goal_list)} goals across {len(gc)} matches")

    print("  ── 3. Goal balance check ──")
    balance_errors = []
    for mid, info in sorted(matches.items(), key=lambda x: int(x[0][1:])):
        sc = info['score']
        if '-' not in sc: continue
        try: h, a = map(int, sc.split('-'))
        except: continue
        exp = h + a; act = gc.get(mid, 0)
        if exp > 0 and act != exp:
            balance_errors.append((mid, info['home'], info['away'], sc, exp, act))

    if balance_errors:
        print(f"    ❌ {len(balance_errors)} balance conflicts:")
        for mid, h, a, sc, exp, act in balance_errors:
            print(f"       {mid}: {h} {sc} {a} — expected {exp} goals, have {act}")
            errors.append(f"BALANCE {mid}: {h} {sc} {a} exp={exp} have={act}")
    else:
        print(f"    ✅ All {len(matches)} matches balanced")

    print("  ── 4. Duplicate goal IDs ──")
    goal_ids = [int(g[0]) for g in goal_list]
    seen = set(); dupes = set()
    for gid in goal_ids:
        if gid in seen: dupes.add(gid)
        seen.add(gid)
    if dupes:
        print(f"    ❌ Duplicate goal IDs: {sorted(dupes)}")
        errors.append(f"DUPLICATE_GOAL_IDS: {sorted(dupes)}")
    else:
        print(f"    ✅ No duplicate goal IDs")

    print("  ── 5. MATCH_STATS consistency ──")
    ms2 = html.find("var MATCH_STATS"); me2 = html.find("\n};", ms2) + 3
    stat_ids = set("m"+x for x in re.findall(r'\bm(\d+)\s*:', html[ms2:me2]))
    match_ids = set(matches.keys())

    # Missing stats
    missing_stats = sorted(match_ids - stat_ids, key=lambda x: int(x[1:]))
    extra_stats   = sorted(stat_ids - match_ids, key=lambda x: int(x[1:]))
    if missing_stats: print(f"    ⚠ Matches missing stats: {missing_stats}"); errors.append(f"MISSING_STATS: {missing_stats}")
    if extra_stats:   print(f"    ⚠ Stats with no match: {extra_stats}");     errors.append(f"EXTRA_STATS: {extra_stats}")
    if not missing_stats and not extra_stats: print(f"    ✅ MATCH_STATS complete ({len(stat_ids)}/72)")

    # Score/home/away alignment between MATCHES and MATCH_STATS
    score_conflicts = []
    for mid in stat_ids & match_ids:
        m_home = matches[mid]['home']
        m_away = matches[mid]['away']
        m_score = matches[mid]['score']
        stat_m = re.search(
            rf'{mid}:\s*\{{home:\'([^\']*)\',\s*away:\'([^\']*)\',\s*hf:\'[^\']*\',\s*af:\'[^\']*\',\s*score:\'([^\']*)\'',
            html[ms2:me2])
        if not stat_m: continue
        s_home, s_away, s_score = stat_m.group(1), stat_m.group(2), stat_m.group(3)

        conflict = None
        if s_home != m_home and s_away != m_away:
            # home/away swapped
            conflict = ('SWAPPED', mid, m_home, m_away, m_score, s_home, s_away, s_score)
        elif s_score != m_score:
            conflict = ('SCORE', mid, m_home, m_away, m_score, s_home, s_away, s_score)

        if conflict:
            score_conflicts.append(conflict)
            kind = conflict[0]
            mid_ = conflict[1]
            print(f"    ❌ {kind} {mid_}: MATCHES={m_home} {m_score} {m_away} | STATS={s_home} {s_score} {s_away}")

            if kind == 'SWAPPED':
                # Auto-fix: swap home/away/score in MATCH_STATS
                # Also flip possession
                try:
                    h_score, a_score = m_score.split('-')
                    flipped = f"{a_score}-{h_score}"
                    old_entry = f"{mid_}: {{home:'{s_home}', away:'{s_away}', hf:'', af:'', score:'{s_score}'"
                    new_entry = f"{mid_}: {{home:'{m_home}', away:'{m_away}', hf:'', af:'', score:'{m_score}'"
                    if old_entry in html:
                        html = html.replace(old_entry, new_entry, 1)
                        changed = True
                        fixes.append(f"AUTO-FIXED swap {mid_}: {m_home} {m_score} {m_away}")
                        print(f"       → AUTO-FIXED home/away swap")
                except Exception as ex:
                    errors.append(f"SWAP_FIX_FAILED {mid_}: {ex}")

    if not score_conflicts:
        print(f"    ✅ All MATCH_STATS home/away/scores consistent")

    print("  ── 6. Goal type validation ──")
    type_counts = {}
    for g in goal_list:
        t = g[6]; type_counts[t] = type_counts.get(t, 0) + 1
    print(f"    Goal types: {type_counts}")
    valid_types = {'open-play','header','penalty','own-goal','free-kick'}
    bad_types = [(g[0],g[1],g[4],g[6]) for g in goal_list if g[6] not in valid_types]
    if bad_types:
        print(f"    ❌ Invalid goal types: {bad_types[:5]}")
        errors.append(f"INVALID_TYPES: {bad_types}")
    else:
        print(f"    ✅ All goal types valid")

    print("  ── 7. Own goal direction check ──")
    og_issues = []
    for g in goal_list:
        if g[6] != 'own-goal': continue
        gid, mid, home, away, scorer, minute, gtype, score = g
        if '-' not in score: continue
        try: h_s, a_s = map(int, score.split('-'))
        except: continue
        # OG by a player associated with home team increases away score
        # We can't check team association automatically, just flag for review
    print(f"    ℹ {type_counts.get('own-goal',0)} own goals (manual review recommended)")

    print("  ── 8. KNOCKOUT_RESULTS integrity ──")
    kr_idx = html.find('var KNOCKOUT_RESULTS')
    kr_end = html.find('\n};', kr_idx) + 3
    kr_block = html[kr_idx:kr_end]
    kr_entries = re.findall(r"(M\d+):\s*\{home:'([^']*)',\s*away:'([^']*)',\s*score:'([^']*)',\s*winner:'([^']*)'", kr_block)
    print(f"    {len(kr_entries)} knockout results recorded")
    for mid, h, a, sc, w in kr_entries:
        if w not in (h, a):
            print(f"    ❌ {mid}: winner '{w}' not in [{h},{a}]")
            errors.append(f"KR_WINNER_MISMATCH {mid}")
        else:
            print(f"    ✅ {mid}: {h} {sc} {a} → {w}")

    print("  ── 9. Sequential goal IDs ──")
    ids_sorted = sorted(goal_ids)
    gaps = [ids_sorted[i+1] for i in range(len(ids_sorted)-1) if ids_sorted[i+1]-ids_sorted[i]>1]
    if gaps:
        print(f"    ⚠ Non-sequential goal IDs (gaps before): {gaps[:10]}")
        # Not an error — just informational, IDs can have gaps from deletions
    else:
        print(f"    ✅ Goal IDs sequential")

    # ── Write fixes ───────────────────────────────────────────────────────────
    if changed:
        write_html(html)
        print(f"\n  ✅ Auto-fixed {len(fixes)} issues:")
        for f in fixes: print(f"     • {f}")
    else:
        print(f"\n  ✅ No auto-fixes needed")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n  {'✅ VALIDATION PASSED' if not errors else '❌ '+str(len(errors))+' ISSUES FOUND'}")
    if errors:
        for e in errors: print(f"    • {e}")
    return len(errors) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION: AUTO-KNOCKOUT — scrape completed knockout results from ESPN
# Reads match_stats.json (populated by update_match_stats.py) to find finished
# knockout matches and writes them to knockout_results.json automatically.
# add_result.py remains as manual fallback for any ESPN misses.
# ═══════════════════════════════════════════════════════════════════════════════
def auto_scrape_knockout():
    """Read match_stats.json, find completed knockout matches, update knockout_results.json."""
    import json

    stats_path = os.path.join(DATA_DIR, 'match_stats.json')
    kr_path    = os.path.join(DATA_DIR, 'knockout_results.json')

    if not os.path.exists(stats_path):
        print("    ⚠ match_stats.json not found — skipping auto knockout scrape")
        return

    with open(stats_path, encoding='utf-8') as f:
        stats = json.load(f)

    try:
        with open(kr_path, encoding='utf-8') as f:
            kr = json.load(f)
    except Exception:
        kr = {}

    # UPCOMING_FIXTURES match IDs (R32)
    R32_IDS = [
        'M73','M74','M75','M76','M77','M78','M79','M80',
        'M81','M82','M83','M84','M85','M86','M87','M88',
    ]
    R16_IDS  = ['M89','M90','M91','M92','M93','M94','M95','M96']
    QF_IDS   = ['M97','M98','M99','M100']
    SF_IDS   = ['M101','M102']
    FIN_IDS  = ['M103','M104']
    ALL_KO   = R32_IDS + R16_IDS + QF_IDS + SF_IDS + FIN_IDS

    # match_stats.json keys can be 'M73' or 'm73' depending on scraper
    # Normalise to uppercase M
    stats_upper = {}
    for k,v in stats.items():
        nk = k.upper() if k.upper() in ALL_KO else k
        stats_upper[nk] = v

    added = []
    for mid in ALL_KO:
        if mid in kr:
            continue   # already recorded — never overwrite manual entries
        if mid not in stats_upper:
            continue   # ESPN hasn't scraped it yet

        entry = stats_upper[mid]
        home  = entry.get('home','')
        away  = entry.get('away','')
        score = entry.get('score','')

        # Only process if match is finished (score has a clear result)
        if not score or '-' not in score:
            continue
        try:
            h_g, a_g = map(int, score.split('-'))
        except ValueError:
            continue

        # Determine winner (draws handled separately — assume AET/pens recorded in score)
        if h_g > a_g:
            winner = home
        elif a_g > h_g:
            winner = away
        else:
            # Draw — check if ESPN includes AET/pen winner in extra field
            winner = entry.get('winner', '')
            if not winner:
                print(f"    ⚠ {mid} is a draw ({score}) — winner unknown, skipping. Use add_result.py to record penalty winner.")
                continue

        kr[mid] = {'home': home, 'away': away, 'score': score, 'winner': winner}
        added.append(f"{mid}: {home} {score} {away} → {winner}")

    if added:
        # Sort by match number
        kr = dict(sorted(kr.items(), key=lambda x: int(x[0][1:])))
        with open(kr_path, 'w', encoding='utf-8') as f:
            json.dump(kr, f, indent=2, ensure_ascii=False)
        print(f"    ✅ Auto-knockout: added {len(added)} results:")
        for a in added: print(f"       {a}")
    else:
        print(f"    ✅ Auto-knockout: no new results found ({len(kr)} already recorded)")

SECTIONS = {
    'goals':    update_goals,
    'stats':    update_stats,
    'knockout': update_knockout,
    'upcoming': update_upcoming,
    'form':     update_form,
    'snapshot': update_snapshot,
    'scrape':   run_scraper,
    'stamp':    update_stamp,
    'validate': validate_and_fix,
    'auto-knockout': auto_scrape_knockout,
}

SECTION_ORDER = ['scrape', 'auto-knockout', 'validate', 'goals', 'stats', 'knockout', 'upcoming', 'form', 'snapshot', 'stamp']

if __name__ == '__main__':
    section = None
    if len(sys.argv) >= 3 and sys.argv[1] == '--section':
        section = sys.argv[2]

    if section:
        if section not in SECTIONS:
            print(f'Unknown section: {section}')
            print(f'Options: {list(SECTIONS.keys())}')
            sys.exit(1)
        print(f'\n[ {section} ]')
        SECTIONS[section]()
    else:
        print(f'=== WC 2026 Full Update — {datetime.date.today()} ===\n')
        for name in SECTION_ORDER:
            print(f'\n[ {name} ]')
            SECTIONS[name]()
        print('\n✅ Done. Commit and push:')
        print('   git add index.html data/ && git commit -m "update: matchday" && git push')



# ── Add 'validate' to SECTIONS dict ──────────────────────────────────────────
