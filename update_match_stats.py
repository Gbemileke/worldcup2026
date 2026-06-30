#!/usr/bin/env python3
"""
update_match_stats.py  —  WC 2026 automated data updater
═══════════════════════════════════════════════════════════
Goal source strategy:
  1. ESPN summary scoringPlays  — PROVEN to work from GitHub Actions IPs
                                  (same endpoint that gives us xG/poss data)
  2. ESPN scoreboard details[]  — sometimes populated, fast check
  3. AllSportsAPI               — if ALLSPORTSAPI_KEY secret is set
  4. Log missing for manual add — last resort

Why ESPN summary works:
  - We already have xG, possession, shots from ESPN summary for ALL matches
  - scoringPlays is in the SAME response — we just never parsed it
  - Different from ESPN API (which 403s) — summary endpoint works from Azure IPs
"""

import os, json, re, time, datetime, requests

DATA_DIR  = 'data'
ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world'
ASA_BASE  = 'https://allsportsapi.com/api/football/'
API_BASE  = 'https://api.football-data.org/v4'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, */*',
}

# ── Name normalisation ────────────────────────────────────────────────────────
SHORT = {
    'South Africa':'S. Africa', 'South Korea':'S. Korea', 'Korea Republic':'S. Korea',
    "Côte d'Ivoire":'Ivory Coast', 'Ivory Coast':'Ivory Coast',
    'Bosnia and Herzegovina':'Bosnia', 'Bosnia-Herzegovina':'Bosnia',
    'Curaçao':'Curacao', 'Curacao':'Curacao',
    'United States':'USA', 'United States of America':'USA', 'USMNT':'USA',
    'IR Iran':'Iran', 'Türkiye':'Turkey', 'Turkey':'Turkey',
    'Cape Verde Islands':'Cape Verde', 'Cabo Verde':'Cape Verde',
    'Congo DR':'DR Congo', 'Democratic Republic of Congo':'DR Congo',
}
FIFA_NAME_MAP = {
    'S. Korea':'south-korea','Bosnia':'bosnia-herzegovina','Turkey':'turkey',
    'Cape Verde':'cabo-verde','DR Congo':'democratic-republic-of-congo',
    'Ivory Coast':'cote-divoire','USA':'united-states','S. Africa':'south-africa','Curacao':'curacao',
}
FIFA_BASE_URL = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'
FIFA_SWAP     = {('Qatar','Switzerland'), ('Norway','Iraq')}

def sn(n): return SHORT.get(n, n) if n else ''

def load(f):
    p = os.path.join(DATA_DIR, f)
    return json.load(open(p)) if os.path.exists(p) else None

def save(f, d):
    with open(os.path.join(DATA_DIR, f), 'w') as fp: json.dump(d, fp, indent=2)

def fmt_date(s):
    try:
        dt = datetime.datetime.fromisoformat(s.replace('Z',''))
        return f"Jun {dt.day}" if dt.month==6 else f"Jul {dt.day}"
    except: return s[:10]

def fifa_url(home, away):
    h = FIFA_NAME_MAP.get(home, home.lower().replace(' ','-').replace("'",'').replace('.',''))
    a = FIFA_NAME_MAP.get(away, away.lower().replace(' ','-').replace("'",'').replace('.',''))
    return (f"{FIFA_BASE_URL}{a}-v-{h}-highlights-match-report"
            if (home,away) in FIFA_SWAP
            else f"{FIFA_BASE_URL}{h}-v-{a}-highlights-match-report")

def get_stat(stats, *names):
    for s in stats:
        for field in ('name','abbreviation','label'):
            if s.get(field,'').lower() in [n.lower() for n in names]:
                try:
                    v = str(s.get('displayValue','0')).replace('%','').strip()
                    return round(float(v),2) if '.' in v else int(v)
                except: pass
    return None

import unicodedata

# Players ESPN spells inconsistently — map any accent variant to ONE canonical form.
# Add new entries here whenever a player appears split across the top-scorer list.
SCORER_ALIASES = {
    # Brazilian single/Junior-name stars
    'V. Júnior': 'Vinicius Jr.',
    'V. Junior': 'Vinicius Jr.',
    'Vinícius Júnior': 'Vinicius Jr.',
    'Vinicius Júnior': 'Vinicius Jr.',
    'Vinícius Jr.': 'Vinicius Jr.',
    # goals.json spelling/convention variants (left = what scorer_fmt produces
    # from the official roster full name; right = the goals.json form)
    'M. Ziko': 'M. Zico',                 # Mostafa Ziko -> Zico
    'M. Al-Tamari': 'M. Al-Taamari',      # Mousa Al-Tamari -> Al-Taamari
    'M. Mohebi': 'M. Mohebbi',            # Mohammad Mohebi -> Mohebbi
    'A. Al Amri': 'A. Al-Amri',           # Abdulelah Al Amri -> Al-Amri
    'M. Trézéguet': 'Trézéguet',          # Mahmoud Trézéguet -> single name
    'M. Trezeguet': 'Trézéguet',
    'J. van Hecke': 'J. Paul van Hecke',  # Jan Paul van Hecke keeps middle name
    'M. Pedersen': 'M. Holmgren Pedersen',# Marcus (Holmgren) Pedersen
    'B. Yilmaz': 'B. Alper Yilmaz',       # Barış Alper Yılmaz keeps middle name
    # Korean names (surname-first in roster; goals.json uses given-initial + surname)
    'O. Hyeon-gyu': 'H. Oh',              # Oh Hyeon-gyu
    'O. Hyun-Kyu': 'H. Oh',
    'H. In-Beom': 'In-B. Hwang',          # Hwang In-Beom
    'H. In-beom': 'In-B. Hwang',
}

# ── PERMANENT goal-type overrides ─────────────────────────────────────────────
# ESPN only detects penalty/own-goal; free-kicks and headers always come back as
# 'open-play'. List them here keyed by (matchId, scorer, minute) and they will be
# re-applied after EVERY scrape so they never reset. This is the source of truth
# for manual goal-type classifications.
# To add one: GOAL_TYPE_OVERRIDES[('m39', 'K. Pina', 21)] = 'free-kick'
GOAL_TYPE_OVERRIDES = {
    ('m39', 'K. Pina', 21): 'free-kick',
    ('m27', 'N. Saliba', 68): 'free-kick',
    ('m45', 'N. Mendes', 17): 'free-kick',
}

# ══════════════════════════════════════════════════════════════════════════════
# LOCKED MATCHES — finished games whose goal data has been manually verified.
# The scraper will NOT re-scrape, re-score, or touch the goals for these matches.
# This protects hand-corrected scorers/minutes/own-goals from being reverted by
# ESPN feed errors (reversed scores, wrong scorers, scrambled running scores).
#
# Behaviour: once a match id is in this set, the scraper treats it as immutable —
# it only adds NEW matches and leaves locked ones exactly as they are in the JSON.
#
# To lock a match after verifying its goals: add its id, e.g. 'm10'.
# To re-open a match for re-scraping (rare): remove its id.
# Locks are keyed by TEAM PAIR (frozenset of the two team names), NOT by m-ID.
# m-IDs are positional and shift whenever matches are reordered (e.g. by kickoff
# time across time zones). A team pair is stable: Bosnia v Qatar is always the
# same match no matter which m-ID it lands on. _resolve_locked_ids() converts
# these pairs to the current m-IDs at runtime by reading matches.json.
LOCKED_PAIRS = {
    frozenset(['Germany','Curacao']),       # Germany 7-1 Curacao (Havertz minute)
    frozenset(['Netherlands','Japan']),     # Netherlands 2-2 Japan (scorers corrected)
    frozenset(['France','Senegal']),        # France 3-1 Senegal (sequence corrected)
    frozenset(['Norway','Iraq']),           # Norway 4-1 Iraq (reversed-score fix)
    frozenset(['Argentina','Algeria']),     # Argentina 3-0 Algeria (Messi minutes)
    frozenset(['Colombia','Uzbekistan']),   # Colombia 3-1 Uzbekistan (reversed-score fix)
    frozenset(['Canada','Qatar']),          # Canada 6-0 Qatar (David/Saliba minutes)
    frozenset(['Bosnia','Qatar']),          # Bosnia 3-1 Qatar (running-score fix)
    frozenset(['Morocco','Haiti']),         # Morocco 4-2 Haiti (own-goal running-score fix)
    frozenset(['Jordan','Algeria']),        # Jordan 1-2 Algeria (Al-Rashdan 36' home goal fix)
    frozenset(['Ecuador','Germany']),       # Ecuador 2-1 Germany (Sané/Angulo away/home swap)
    frozenset(['Norway','France']),         # Norway 1-4 France (Aasgaard 21' NOR goal fix)
    frozenset(['New Zealand','Belgium']),   # New Zealand 1-5 Belgium (Just 84' NZL goal fix)
    frozenset(['Croatia','Ghana']),         # Croatia 2-1 Ghana (Luckassen 73' Ghana equaliser fix)
    frozenset(['DR Congo','Uzbekistan']),   # DR Congo 3-1 Uzbekistan (4 goals manually verified)
    frozenset(['Algeria','Austria']),       # Algeria 3-3 Austria (6 goals manually verified)
    frozenset(['Jordan','Argentina']),      # Jordan 1-3 Argentina (Lo Celso/Martinez/Al-Taamari/Messi)
}

def _resolve_locked_ids(matches):
    """Convert LOCKED_PAIRS (team pairs) to current m-IDs using matches.json.
    This makes locks immune to match reordering — a pair always resolves to
    whatever m-ID currently holds that fixture."""
    ids = set()
    for m in matches:
        if frozenset([m.get('home',''), m.get('away','')]) in LOCKED_PAIRS:
            ids.add(m['id'])
    return ids

# Runtime-resolved set. Populated from matches.json inside fetch/update flows.
# Falls back to empty until resolved; _record_goal_fix also adds to it.
LOCKED_MATCHES = set()

# ─────────────────────────────────────────────────────────────────────────────
# SAFE MANUAL GOAL FIX
# Use this function to correct goals for any match instead of editing HTML
# directly. It writes to data/goals.json (the canonical source), auto-locks
# the match so the scraper never overwrites it, and update_site.py will
# regenerate the HTML cleanly on the next run — no syntax errors possible.
#
# Usage:
#   manual_fix_goals('mXX', [
#       {'scorer':'Player Name', 'minute':10, 'type':'open-play', 'score':'1-0'},
#       {'scorer':'Player Name', 'minute':67, 'type':'penalty',   'score':'1-1'},
#   ], home='Team A', away='Team B', phase='Group Stage')
#
# Types: open-play | penalty | own-goal | header | free-kick
# ─────────────────────────────────────────────────────────────────────────────
def manual_fix_goals(match_id, new_goals, home='', away='', phase='Group Stage'):
    import json, os

    goals_path = os.path.join(os.path.dirname(__file__), 'data', 'goals.json')
    with open(goals_path) as f:
        goals = json.load(f)

    # Remove any existing goals for this match
    goals = [g for g in goals if g.get('matchId') != match_id]

    # Determine next id
    next_id = max((g['id'] for g in goals), default=0) + 1

    # Derive home/away from existing data if not supplied
    if not home or not away:
        import re
        with open(os.path.join(os.path.dirname(__file__), 'index.html')) as f:
            html = f.read()
        m = re.search(rf"id:'{match_id}'[^}}]*home:'([^']*)'[^}}]*away:'([^']*)'", html)
        if m:
            home = home or m.group(1)
            away = away or m.group(2)

    for g in new_goals:
        goals.append({
            "id":      next_id,
            "matchId": match_id,
            "home":    home,
            "away":    away,
            "scorer":  g['scorer'],
            "minute":  g['minute'],
            "type":    g.get('type', 'open-play'),
            "phase":   g.get('phase', phase),
            "score":   g.get('score', ''),
            "desc":    g.get('desc', ''),
        })
        next_id += 1

    # Sort by match then minute
    goals.sort(key=lambda x: (x['matchId'], x['minute']))

    with open(goals_path, 'w') as f:
        json.dump(goals, f, indent=2)

    # Auto-lock this match
    if match_id not in LOCKED_MATCHES:
        LOCKED_MATCHES.add(match_id)
        print(f"  ✓ {match_id}: {len(new_goals)} goals written to goals.json and locked")
    else:
        print(f"  ✓ {match_id}: {len(new_goals)} goals written to goals.json (already locked)")
    print(f"    Run update_site.py to regenerate index.html")


def _strip_accents(s):
    return ''.join(ch for ch in unicodedata.normalize('NFD', s)
                   if unicodedata.category(ch) != 'Mn')

def _classify_goal_type(text):
    """Classify a goal from ESPN's type text + play description.
    ESPN reliably tags penalty/own-goal; free-kick and header appear in the
    play description text when present. Order matters: penalty/own-goal first."""
    t = (text or '').lower()
    if 'penalty' in t or 'penalty kick' in t:
        return 'penalty'
    if 'own goal' in t or 'own-goal' in t or ('own' in t and 'goal' in t):
        return 'own-goal'
    if 'free kick' in t or 'free-kick' in t or 'freekick' in t or 'direct free' in t:
        return 'free-kick'
    if 'header' in t or 'headed' in t or 'heads' in t or 'with the head' in t:
        return 'header'
    return 'open-play'

def apply_type_overrides(goals):
    """Re-apply permanent free-kick/header classifications. Call after every scrape."""
    applied = 0
    for g in goals:
        key = (g.get('matchId'), g.get('scorer'), g.get('minute'))
        if key in GOAL_TYPE_OVERRIDES and g.get('type') != GOAL_TYPE_OVERRIDES[key]:
            # Don't override penalty/own-goal (those ESPN detects correctly)
            if g.get('type') not in ('penalty', 'own-goal'):
                g['type'] = GOAL_TYPE_OVERRIDES[key]
                applied += 1
    if applied:
        print(f"  → Applied {applied} permanent goal-type override(s)")
    return goals

# Surname particles that attach to the last name when abbreviating
# (so 'Virgil van Dijk' -> 'V. van Dijk', 'Giovani Lo Celso' -> 'G. Lo Celso').
_SURNAME_PARTICLES = {'van','von','de','del','da','dos','di','der','den','ten','ter',
                      'la','le','el','al','bin','ibn','lo','dello','della'}

def scorer_fmt(raw):
    """Format an ESPN full name to the goals.json convention: 'F. Lastname',
    keeping accents and grouping multi-word surnames (particles). Handles the
    many special/accented names correctly, then applies SCORER_ALIASES for the
    handful of names that use a non-standard convention in goals.json."""
    if not raw:
        return ''
    name = raw.strip()
    parts = name.split()
    if len(parts) == 1:
        # Single-name player (Neymar, Rodri, Vinícius...) — keep as-is
        formatted = name
    else:
        first = parts[0]
        # Walk back from the last token, absorbing surname particles
        surname_start = len(parts) - 1
        i = len(parts) - 2
        while i >= 1 and parts[i].lower() in _SURNAME_PARTICLES:
            surname_start = i
            i -= 1
        surname = ' '.join(parts[surname_start:])
        formatted = f"{first[0].upper()}. {surname}"
    # Canonicalize via aliases (accent-insensitive match on the alias key)
    stripped = _strip_accents(formatted).lower()
    for key, canon in SCORER_ALIASES.items():
        if stripped == _strip_accents(key).lower():
            return canon
    return formatted

def parse_minute(clock_str):
    s = str(clock_str or '').replace("'",'').strip()
    try:
        if '+' in s:
            base, extra = s.split('+', 1)
            return int(base) + (1 if int(extra)>0 else 0)
        return int(s.split(':')[0]) if ':' in s else int(s)
    except: return 90

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — ESPN scoreboard (scores + espnId)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_espn_scoreboard():
    url = f"{ESPN_BASE}/scoreboard?dates=20260601-20260720&limit=200"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                events = r.json().get('events',[])
                print(f"  ESPN scoreboard: {len(events)} events")
                return events
            print(f"  ESPN scoreboard: HTTP {r.status_code} (attempt {attempt+1}/3)")
            time.sleep(5*(attempt+1))
        except Exception as e:
            print(f"  ESPN scoreboard error: {e}")
        time.sleep(2)
    return []

def parse_espn_event(event):
    if event.get('status',{}).get('type',{}).get('state','') != 'post': return None
    comp        = (event.get('competitions') or [{}])[0]
    competitors = comp.get('competitors',[])
    if len(competitors)<2: return None
    home_c = next((c for c in competitors if c.get('homeAway')=='home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway')=='away'), competitors[1])
    home = sn(home_c.get('team',{}).get('displayName',''))
    away = sn(away_c.get('team',{}).get('displayName',''))
    if not home or not away: return None
    h_score = int(home_c.get('score',0) or 0)
    a_score = int(away_c.get('score',0) or 0)
    # Penalty shootout: ESPN carries a separate shootoutScore on each competitor
    # when a knockout match is decided on penalties (regulation/ET score is level).
    def _so(c):
        v = c.get('shootoutScore', None)
        try:
            return int(v) if v is not None and str(v) != '' else None
        except (ValueError, TypeError):
            return None
    h_so = _so(home_c)
    a_so = _so(away_c)
    group = ''
    for n in comp.get('notes',[]):
        g = re.search(r'Group\s+([A-Z])', n.get('headline',''), re.I)
        if g: group = g.group(1); break
    # Try to get goals from scoreboard details[]
    details = comp.get('details',[])
    goals = _parse_details(details, home, away)
    return {
        'home':home, 'away':away, 'score':f"{h_score}-{a_score}",
        'date':fmt_date(event.get('date','')), 'group':group,
        'espn_id':event.get('id',''),
        'venue':comp.get('venue',{}).get('fullName',''),
        'goals':goals,
        'h_so':h_so, 'a_so':a_so,
    }

def _parse_details(details, home, away):
    """Parse goals from ESPN scoreboard details[] array."""
    goals = []
    for d in details:
        dtype = d.get('type',{}).get('text','').lower()
        if 'goal' not in dtype: continue
        athletes = d.get('athletesInvolved',[])
        if not athletes: continue
        raw   = athletes[0].get('displayName','')
        scorer = scorer_fmt(raw)
        if not scorer: continue
        minute = parse_minute(d.get('clock',{}).get('displayValue','90'))
        desc = (d.get('text','') or d.get('shortText','') or '').lower()
        gtype = _classify_goal_type(dtype + ' ' + desc)
        team   = sn(d.get('team',{}).get('displayName',''))
        # ESPN details often carry the running score — use it for exact attribution
        hs = d.get('homeScore', d.get('homeScoreValue'))
        as_ = d.get('awayScore', d.get('awayScoreValue'))
        g = {'scorer':scorer,'minute':minute,'type':gtype,'team':team}
        if isinstance(hs,int) and isinstance(as_,int):
            g['home_score'] = hs
            g['away_score'] = as_
        goals.append(g)
    return goals

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — ESPN summary (scoringPlays + match stats)
# PROVEN WORKING from GitHub Actions — same endpoint that gives us xG/poss
# ══════════════════════════════════════════════════════════════════════════════
def fetch_espn_summary(espn_id):
    for attempt in range(3):
        try:
            r = requests.get(f"{ESPN_BASE}/summary?event={espn_id}",
                             headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r.json()
            print(f"    ESPN summary HTTP {r.status_code} (attempt {attempt+1}/3)")
            time.sleep(3*(attempt+1))
        except Exception as e:
            print(f"    ESPN summary error: {e}")
        time.sleep(2)
    return {}

def parse_espn_scoring_plays(summary, home, away):
    """
    Parse goals from ESPN summary scoringPlays[].
    This is the PRIMARY goal source — proven accessible from GitHub Actions.
    Uses homeScore/awayScore directly (no calculation needed).
    """
    plays = (summary.get('scoringPlays') or
             summary.get('gamepackageJSON',{}).get('scoringPlays') or [])

    if not plays:
        # Also check header competitions details
        for comp in summary.get('header',{}).get('competitions',[]):
            details = comp.get('details',[])
            goals   = _parse_details(details, home, away)
            if goals: return goals
        return []

    goals = []
    for p in plays:
        dtype = (p.get('type',{}).get('text','') or p.get('scoringType',{}).get('displayName','')).lower()
        if not dtype: continue

        # Get scorer
        athletes = p.get('athletesInvolved', p.get('participants',[]))
        if not athletes: continue
        raw    = (athletes[0].get('displayName') or
                  athletes[0].get('athlete',{}).get('displayName',''))
        scorer = scorer_fmt(raw)
        if not scorer: continue

        # Minute
        clock  = (p.get('clock',{}).get('displayValue') or
                  p.get('periodClock',{}).get('displayValue','90'))
        minute = parse_minute(clock)

        # Goal type — detect penalty, own-goal, free-kick, header from ESPN text
        # ESPN exposes type.text and a play-description 'text' that often name the method
        desc = (p.get('text','') or p.get('shortText','') or '').lower()
        combined = dtype + ' ' + desc
        gtype = _classify_goal_type(combined)

        # Team — resolve by NAME first (robust to ESPN/our home-away orientation
        # differing, which is common in knockout fixtures). Only fall back to the
        # score-position method when the name genuinely can't be matched.
        home_score = p.get('homeScore', p.get('homeAthlete',{}).get('score',0))
        away_score = p.get('awayScore', p.get('awayAthlete',{}).get('score',0))
        team_disp  = sn(p.get('team',{}).get('displayName',''))

        def _norm_team(s):
            return ''.join(ch for ch in str(s).lower() if ch.isalnum())
        _hn, _an, _tn = _norm_team(home), _norm_team(away), _norm_team(team_disp)

        if _tn and _tn == _hn:
            team = home
        elif _tn and _tn == _an:
            team = away
        elif _tn and (_tn in _hn or _hn in _tn):
            team = home
        elif _tn and (_tn in _an or _an in _tn):
            team = away
        else:
            # Name unresolved — leave blank so assign_goals derives from running
            # score. Do NOT default to home (that caused Japan goals → Brazil).
            team = ''

        goals.append({
            'scorer': scorer, 'minute': minute, 'type': gtype, 'team': team,
            'home_score': home_score, 'away_score': away_score,
        })

    return goals

def parse_espn_stats(summary):
    bs    = summary.get('boxscore',{})
    teams = bs.get('teams',[])
    if not teams: return None
    by_side = {td.get('homeAway',''): td.get('statistics',[]) for td in teams}
    h = by_side.get('home',[]); a = by_side.get('away',[])
    poss_h = get_stat(h,'possessionPct','possession') or 50
    poss_a = get_stat(a,'possessionPct','possession') or 50
    pt = poss_h+poss_a
    if pt and pt!=100: poss_h=round(poss_h/pt*100); poss_a=100-poss_h
    sot_h   = get_stat(h,'shotsOnGoal','shotsOnTarget','ongoal') or 0
    sot_a   = get_stat(a,'shotsOnGoal','shotsOnTarget','ongoal') or 0
    shots_h = get_stat(h,'shotAttempts','totalShots','shots') or sot_h
    shots_a = get_stat(a,'shotAttempts','totalShots','shots') or sot_a
    xg_h    = get_stat(h,'expectedGoals','xg') or round(sot_h*0.33+max(0,shots_h-sot_h)*0.05,2)
    xg_a    = get_stat(a,'expectedGoals','xg') or round(sot_a*0.33+max(0,shots_a-sot_a)*0.05,2)
    return {
        'poss':[poss_h,poss_a],
        'stats':[
            ['Shot Attempts',shots_h,shots_a],['Shots on Goal',sot_h,sot_a],
            ['Corner Kicks',get_stat(h,'cornerKicks','corners') or 0,get_stat(a,'cornerKicks','corners') or 0],
            ['Fouls',get_stat(h,'fouls') or 0,get_stat(a,'fouls') or 0],
            ['Saves',get_stat(h,'saves') or 0,get_stat(a,'saves') or 0],
        ],
        'xtra':[
            ['xG',xg_h,xg_a],
            ['Yellow Cards',get_stat(h,'yellowCards') or 0,get_stat(a,'yellowCards') or 0],
            ['Red Cards',   get_stat(h,'redCards') or 0,   get_stat(a,'redCards') or 0],
            ['Offsides',    get_stat(h,'offsides') or 0,   get_stat(a,'offsides') or 0],
        ]
    }

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — AllSportsAPI (optional, if key is set)
# ══════════════════════════════════════════════════════════════════════════════
WC_TEAMS_LOWER = {
    'argentina','france','spain','england','brazil','portugal','netherlands',
    'germany','belgium','croatia','colombia','mexico','usa','senegal','uruguay',
    'japan','switzerland','iran','turkey','ecuador','austria','south korea',
    'australia','algeria','egypt','canada','norway','ivory coast','sweden',
    'czechia','paraguay','scotland','ghana','panama','morocco','saudi arabia',
    'qatar','iraq','south africa','jordan','bosnia','cape verde','dr congo',
    'uzbekistan','new zealand','curacao','haiti','tunisia',
}

def fetch_allsports_goals(asa_key, home, away, date_str):
    """Fetch goals for a specific match from AllSportsAPI."""
    if not asa_key: return []
    try:
        # Convert date
        day = int(date_str.replace('Jun ','').replace('Jul ',''))
        mon = '06' if 'Jun' in date_str else '07'
        d   = f"2026-{mon}-{day:02d}"

        url = f"{ASA_BASE}?met=Fixtures&APIkey={asa_key}&from={d}&to={d}"
        r   = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            return []
        results = r.json().get('result') or []
        for m in results:
            h = sn(m.get('event_home_team',''))
            a = sn(m.get('event_away_team',''))
            if (h==home and a==away) or (h==away and a==home):
                return _parse_asa_goals(m, home, away)
    except Exception as e:
        print(f"    AllSportsAPI error: {e}")
    return []

def _parse_asa_goals(event, home, away):
    raw_goals = event.get('goalscorers') or []
    goals = []
    for g in raw_goals:
        info   = (g.get('info') or '').lower()
        time_s = str(g.get('time') or g.get('minute') or '90')
        minute = parse_minute(time_s)
        home_s = (g.get('home_scorer') or '').strip()
        away_s = (g.get('away_scorer') or '').strip()
        if home_s:
            scorer,team = scorer_fmt(home_s), home
        elif away_s:
            scorer,team = scorer_fmt(away_s), away
        else: continue
        gtype = ('penalty' if 'penalty' in info else 'own-goal' if 'own' in info else 'open-play')
        goals.append({'scorer':scorer,'minute':minute,'type':gtype,'team':team})
    return goals

# ══════════════════════════════════════════════════════════════════════════════
# Goal assignment with score validation
# ══════════════════════════════════════════════════════════════════════════════
def assign_goals(goal_list, home, away, h_fin, a_fin, mid, group, next_id):
    """
    Build goal objects. If goals have homeScore/awayScore from ESPN,
    use those directly. Otherwise calculate running score.
    Validates final tally matches expected score.
    """
    h_run = a_run = 0
    built = []

    # Normalize home/away once for robust comparison
    def _norm(s):
        return ''.join(ch for ch in str(s).lower() if ch.isalnum())
    home_n, away_n = _norm(home), _norm(away)

    def _resolve_team(raw_team):
        """Map a (possibly blank/mismatched) ESPN team name to home or away."""
        if not raw_team:
            return None
        rn = _norm(raw_team)
        if rn == home_n: return home
        if rn == away_n: return away
        # Substring / partial match (handles 'Korea Republic' vs 'S. Korea', etc.)
        if rn and (rn in home_n or home_n in rn): return home
        if rn and (rn in away_n or away_n in rn): return away
        return None

    for gd in sorted(goal_list, key=lambda x: x.get('minute',90)):
        is_og = gd['type'] == 'own-goal'
        team  = _resolve_team(gd.get('team',''))

        # If the team was resolved by NAME (authoritative even when ESPN's home/away
        # orientation differs from ours), trust it and just advance the running score.
        hs = gd.get('home_score')
        as_ = gd.get('away_score')
        if team in (home, away):
            if is_og:
                if team == home: a_run += 1
                else:            h_run += 1
            else:
                if team == home: h_run += 1
                else:            a_run += 1
        elif hs is not None and as_ is not None:
            # Which score changed from previous?
            if hs > h_run and not is_og:   team = home
            elif as_ > a_run and not is_og: team = away
            elif hs > h_run and is_og:      team = away   # OG by away → home scores
            elif as_ > a_run and is_og:     team = home   # OG by home → away scores
            h_run = hs; a_run = as_
        else:
            # If team still unknown, infer from remaining capacity in the final score
            if team not in (home, away):
                h_need = h_fin - h_run
                a_need = a_fin - a_run
                if is_og:
                    # OG credits the OTHER team; assign to whichever side still needs goals
                    team = away if h_need >= a_need else home
                else:
                    team = home if h_need >= a_need else away
            # Calculate running score
            if is_og:
                if team == home: a_run += 1
                else:            h_run += 1
            else:
                if team == home: h_run += 1
                else:            a_run += 1

        built.append({
            'id':mid+str(next_id) if False else next_id,
            'matchId':mid, 'home':home, 'away':away,
            'scorer':gd['scorer'], 'minute':gd['minute'], 'type':gd['type'],
            'phase':f"Group {group}" if group else 'Group Stage',
            'score':f"{h_run}-{a_run}", 'desc':'',
        })
        next_id += 1

    if h_run==h_fin and a_run==a_fin:
        return built, next_id
    print(f"    ✗ Validation: got {h_run}-{a_run} expected {h_fin}-{a_fin}")
    return [], next_id-len(built)

# ══════════════════════════════════════════════════════════════════════════════
# WC_RESULTS auto-patch
# ══════════════════════════════════════════════════════════════════════════════
def patch_wc_results(home, away, h, a):
    path = 'update_rankings.py'
    if not os.path.exists(path): return
    try:
        with open(path) as f: content = f.read()
        if f'"home":"{home}"' in content and f'"away":"{away}"' in content: return
        result  = 1.0 if h>a else 0.5 if h==a else 0.0
        line    = f'    {{"home":"{home}", "away":"{away}", "result":{result}}},  # {h}-{a}\n'
        marker  = '    # ADD NEW RESULTS BELOW AS TOURNAMENT PROGRESSES:\n'
        if marker in content:
            with open(path,'w') as f: f.write(content.replace(marker, line+marker, 1))
            print(f"    WC_RESULTS: ✓ {home} {h}-{a} {away}")
    except Exception as e:
        print(f"    WC_RESULTS error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# Upcoming fixtures
# ══════════════════════════════════════════════════════════════════════════════
def fetch_upcoming(token, played_keys):
    if not token: return
    try:
        r = requests.get(f"{API_BASE}/competitions/WC/matches?status=SCHEDULED",
                         headers={'X-Auth-Token':token}, timeout=15)
        if r.status_code != 200: return
        upcoming = []
        for m in r.json().get('matches',[])[:48]:
            if not m.get('homeTeam') or not m.get('awayTeam'): continue
            hn = m['homeTeam'].get('name',''); an = m['awayTeam'].get('name','')
            if not hn or not an: continue
            home = sn(hn); away = sn(an)
            if not home or not away: continue
            if f"{home}|{away}" in played_keys or f"{away}|{home}" in played_keys: continue
            try:
                dt    = datetime.datetime.fromisoformat(m['utcDate'].replace('Z','+00:00'))
                cst   = dt-datetime.timedelta(hours=6)
                date_s = f"Jun {cst.day}" if cst.month==6 else f"Jul {cst.day}"
                h12   = cst.hour%12 or 12
                ampm  = 'AM' if cst.hour<12 else 'PM'
                mn    = f":{cst.minute:02d}" if cst.minute else ''
                time_s = f"{h12}{mn}{ampm} CST"
            except: date_s=m['utcDate'][:10]; time_s='?? CST'
            gr  = m.get('stage','')
            grp = gr.replace('GROUP_','') if 'GROUP_' in gr else ''
            # Determine round from football-data.org stage field
            stage = m.get('stage','') or ''
            if 'ROUND_OF_32' in stage or 'LAST_32' in stage or '32' in stage: rnd = 'R32'
            elif 'ROUND_OF_16' in stage or 'LAST_16' in stage or '16' in stage: rnd = 'R16'
            elif 'QUARTER' in stage or 'QF' in stage: rnd = 'QF'
            elif 'SEMI' in stage or 'SF' in stage: rnd = 'SF'
            elif 'FINAL' in stage and 'SEMI' not in stage: rnd = 'Final'
            else: rnd = 'Group Stage'

            upcoming.append({'date':date_s,'home':home,'away':away,'time':time_s,'group':grp,'round':rnd})
        if upcoming:
            save('upcoming_fixtures.json', upcoming)
            print(f"  Upcoming: {len(upcoming)} fixtures")
    except Exception as e:
        print(f"  Upcoming error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def _record_knockout_result(home, away, score, h_goals, a_goals, h_so=None, a_so=None):
    """
    Write a completed knockout match result to data/knockout_results.json.
    Determines match ID from UPCOMING_FIXTURES by team pair lookup.
    Never overwrites a manually recorded result.

    h_so/a_so are the penalty-shootout scores (or None). When the regulation/ET
    score is level and shootout scores are present, the winner is the shootout
    victor and a 'pens' field (e.g. '4-2') is stored alongside the regulation score.
    """
    import json as _json

    kr_path = os.path.join(DATA_DIR, 'knockout_results.json')
    uf_path = os.path.join(DATA_DIR, 'upcoming_fixtures.json')

    # Load existing knockout results
    try:
        with open(kr_path, encoding='utf-8') as f:
            kr = _json.load(f)
    except Exception:
        kr = {}

    # Find the match ID from upcoming_fixtures.json by team pair
    mid = None
    try:
        with open(uf_path, encoding='utf-8') as f:
            uf = _json.load(f)
        for fx in uf:
            fh = sn(fx.get('home', '')); fa = sn(fx.get('away', ''))
            if (fh == home and fa == away) or (fa == home and fh == away):
                mid = fx.get('matchId', '')
                break
    except Exception:
        pass

    if not mid:
        # Try R32_SCHEDULE in index.html — parse each entry by team pair.
        # Field order varies (home/away can come before OR after matchId), so
        # match a whole {...} entry then pull fields out individually.
        try:
            with open('index.html', encoding='utf-8') as f:
                html = f.read()
            import re as _re
            r32_start = html.find('var R32_SCHEDULE')
            if r32_start >= 0:
                r32_block = html[r32_start:html.find('];', r32_start) + 2]
                for entry in _re.finditer(r"\{[^}]*\}", r32_block):
                    et = entry.group()
                    fmid_m = _re.search(r"matchId:'(M\d+)'", et)
                    fh_m   = _re.search(r"home:'([^']*)'", et)
                    fa_m   = _re.search(r"away:'([^']*)'", et)
                    if not (fmid_m and fh_m and fa_m):
                        continue
                    fmid = fmid_m.group(1)
                    fh   = sn(fh_m.group(1))
                    fa   = sn(fa_m.group(1))
                    if (fh == home and fa == away) or (fa == home and fh == away):
                        mid = fmid
                        break
        except Exception:
            pass

    if not mid:
        print(f"      ⚠ Could not find match ID for {home} vs {away} — not recorded")
        return None

    if mid in kr:
        return mid  # already recorded — caller may still attach goals/stats

    # Determine winner. Regulation/ET first; if level, fall to penalty shootout.
    entry = {'home': home, 'away': away, 'score': score}
    if h_goals > a_goals:
        winner = home
    elif a_goals > h_goals:
        winner = away
    else:
        # Level after regulation/ET — decided on penalties if shootout scores exist.
        if h_so is not None and a_so is not None and h_so != a_so:
            winner = home if h_so > a_so else away
            entry['pens'] = f"{h_so}-{a_so}"   # stored in home-away order
        else:
            winner = ''  # draw, no shootout data — needs manual entry via add_result.py
    entry['winner'] = winner

    kr[mid] = entry
    kr = dict(sorted(kr.items(), key=lambda x: int(x[0][1:]) if x[0][1:].isdigit() else 999))
    with open(kr_path, 'w', encoding='utf-8') as f:
        _json.dump(kr, f, indent=2, ensure_ascii=False)
    return mid  # so caller can attach goals + stats under this M-ID


def run():
    asa_key  = os.environ.get('ALLSPORTSAPI_KEY','').strip()
    fd_token = os.environ.get('FOOTBALL_DATA_TOKEN','').strip()

    matches  = load('matches.json')     or []
    stats    = load('match_stats.json') or {}
    goals    = load('goals.json')       or []

    # Resolve team-pair locks to current m-IDs (immune to reordering)
    global LOCKED_MATCHES
    LOCKED_MATCHES = _resolve_locked_ids(matches)
    if LOCKED_MATCHES:
        print(f"  🔒 {len(LOCKED_MATCHES)} locked matches resolved: "
              f"{', '.join(sorted(LOCKED_MATCHES, key=lambda x:int(x.replace('m',''))))}")

    match_lookup = {}
    for m in matches:
        m['home']=sn(m['home']); m['away']=sn(m['away'])
        match_lookup[f"{m['home']}|{m['away']}"] = m['id']
        match_lookup[f"{m['away']}|{m['home']}"] = m['id']

    existing_nums = [int(m['id'].replace('m','')) for m in matches]
    next_num      = max(existing_nums)+1 if existing_nums else 1
    next_goal_id  = max((g['id'] for g in goals), default=0)+1

    goals_by_mid = {}
    for g in goals: goals_by_mid.setdefault(g['matchId'],[]).append(g)

    played_keys   = set(match_lookup.keys())
    matches_added = stats_added = goals_added = goals_fixed = 0

    # ── ESPN scoreboard ───────────────────────────────────────────────────────
    print("\nFetching ESPN scoreboard...")
    espn_events = fetch_espn_scoreboard()
    espn_by_key = {}
    for ev in espn_events:
        p = parse_espn_event(ev)
        if p: espn_by_key[f"{p['home']}|{p['away']}"] = p

    # ── Process each finished match ───────────────────────────────────────────
    print(f"\nProcessing {len(espn_by_key)} finished matches...\n")

    for key, parsed in espn_by_key.items():
        home  = parsed['home']; away = parsed['away']
        score = parsed['score']
        h_so  = parsed.get('h_so'); a_so = parsed.get('a_so')  # penalty shootout (or None)
        try: h_fin,a_fin = map(int,score.split('-'))
        except: continue

        mid = match_lookup.get(key) or match_lookup.get(f"{away}|{home}")

        # Normalize home/away to canonical order (matches.json is ground truth)
        # ESPN may return Tunisia as home when our canonical has Japan as home.
        # Without this, goals get wrong score perspective and stats get wrong columns.
        if mid:
            canon_m = next((m for m in matches if m['id'] == mid), None)
            if canon_m and canon_m['home'] != home:
                # Swap ESPN's home/away to match our canonical ordering
                home, away = canon_m['home'], canon_m['away']
                h_fin, a_fin = a_fin, h_fin  # flip goal counts too
                h_so, a_so = a_so, h_so      # flip shootout scores too
                score = f"{h_fin}-{a_fin}"

        # Add new match — GROUP STAGE ONLY for matches.json.
        # Knockout matches (M73+) get their result in knockout_results.json,
        # then flow through the SAME goals + stats processing below using their
        # M-ID, so the knockout cards show full goals and statistics too.
        if not mid:
            # Knockout detection: group stage matches always have a group letter (A-L).
            # If group is empty, this match has no group → it's a knockout match.
            # parse_espn_event never sets 'round', so check group only.
            is_knockout = not parsed.get('group', '')
            if is_knockout:
                ko_mid = _record_knockout_result(home, away, score, h_fin, a_fin, h_so, a_so)
                if not ko_mid:
                    # Couldn't resolve the M-ID — skip entirely this run
                    continue
                print(f"  ⟳ Knockout: {home} {score} {away} → {ko_mid} (result + goals + stats)")
                mid = ko_mid  # continue into goals/stats processing under this M-ID
                # ensure goals_by_mid has a slot for balance checks
                goals_by_mid.setdefault(mid, [g for g in goals if g['matchId'] == mid])
            else:
                mid = f"m{next_num}"; next_num+=1
                match_lookup[key]=mid; match_lookup[f"{away}|{home}"]=mid
                played_keys.update([key,f"{away}|{home}"])
                matches.append({
                    'id':mid,'date':parsed['date'],'home':home,'away':away,
                    'score':score,'group':parsed['group'],'ytId':'',
                    'fifaUrl':fifa_url(home,away),'espnId':parsed['espn_id'],
                })
                matches.sort(key=lambda m:int(m['id'].replace('m','')))
                matches_added+=1
                print(f"  ✚ {mid} {home} {score} {away}")
                patch_wc_results(home,away,h_fin,a_fin)
        else:
            ex = next(m for m in matches if m['id']==mid)
            if mid in LOCKED_MATCHES:
                # Verified match — leave score and goals untouched.
                if parsed['espn_id'] and not ex.get('espnId'): ex['espnId']=parsed['espn_id']
                if parsed['group']   and not ex.get('group'):  ex['group']=parsed['group']
                continue
            if ex.get('score')!=score:
                print(f"  ↺ {mid} score: {ex['score']} → {score}")
                ex['score']=score
                if mid in goals_by_mid:
                    goals=[g for g in goals if g['matchId']!=mid]
                    del goals_by_mid[mid]
                    next_goal_id=max((g['id'] for g in goals),default=0)+1
                patch_wc_results(home,away,h_fin,a_fin)
            if parsed['espn_id'] and not ex.get('espnId'): ex['espnId']=parsed['espn_id']
            if parsed['group']   and not ex.get('group'):  ex['group']=parsed['group']

        # ── Goals ─────────────────────────────────────────────────────────────
        existing_g  = goals_by_mid.get(mid,[])
        needs_goals = len(existing_g) != (h_fin+a_fin)

        if needs_goals:
            have = len(existing_g)
            need = h_fin+a_fin
            print(f"  → Goals {mid} ({home} {score} {away}): have {have}, need {need}")

            # Preserve manually-classified types (free-kick, header) by scorer+minute
            preserved_types = {}
            for eg in existing_g:
                if eg.get('type') in ('free-kick', 'header'):
                    preserved_types[(eg.get('scorer',''), eg.get('minute'))] = eg['type']

            # Clear partial
            if existing_g:
                goals=[g for g in goals if g['matchId']!=mid]
                next_goal_id=max((g['id'] for g in goals),default=0)+1

            espn_id = parsed['espn_id'] or next((m['espnId'] for m in matches if m['id']==mid and m.get('espnId')),'')
            goal_list = []

            # Source 1: ESPN scoreboard details[]
            if parsed['goals']:
                goal_list = parsed['goals']
                print(f"    ESPN scoreboard details: {len(goal_list)} goals")

            # Source 2: ESPN summary scoringPlays (PRIMARY — proven to work)
            if not goal_list and espn_id:
                print(f"    Fetching ESPN summary scoringPlays...")
                summary = fetch_espn_summary(espn_id)
                time.sleep(0.5)
                if summary:
                    goal_list = parse_espn_scoring_plays(summary, home, away)
                    if goal_list:
                        print(f"    ESPN summary scoringPlays: {len(goal_list)} goals")
                    # Cache summary for stats
                    parsed['_summary'] = summary

            # Source 3: AllSportsAPI (if key set)
            if not goal_list and asa_key:
                print(f"    Trying AllSportsAPI...")
                goal_list = fetch_allsports_goals(asa_key, home, away, parsed['date'])
                time.sleep(0.5)

            if goal_list:
                new_goals, next_goal_id = assign_goals(
                    goal_list, home, away, h_fin, a_fin, mid, parsed['group'], next_goal_id)
                if new_goals:
                    # Restore manually-classified free-kick/header types
                    for ng in new_goals:
                        key = (ng.get('scorer',''), ng.get('minute'))
                        if key in preserved_types and ng.get('type') == 'open-play':
                            ng['type'] = preserved_types[key]
                    goals.extend(new_goals)
                    goals_by_mid[mid]=new_goals
                    goals_added += len(new_goals) if have==0 else 0
                    goals_fixed += len(new_goals) if have>0  else 0
                    print(f"    ✓ {len(new_goals)} goals saved")
                else:
                    print(f"    ✗ Validation failed — retry next run")
            else:
                print(f"    ⚠ No goal data found for {mid} ({score}) — add manually")

        # ── Stats ──────────────────────────────────────────────────────────────
        espn_id = parsed['espn_id'] or next((m.get('espnId','') for m in matches if m['id']==mid),'')
        # Group stages (m1-m72) AND knockout (M73+) both get stats written.
        # Knockout stats are keyed by their M-ID and sync via update_wc.py update_stats().
        if espn_id and (mid not in stats or stats[mid].get('score')!=score):
            # Use cached summary if already fetched, else fetch
            summary = parsed.get('_summary')
            if not summary:
                print(f"  → Stats {mid}...", end=' ', flush=True)
                summary = fetch_espn_summary(espn_id)
                time.sleep(0.3)
            s = parse_espn_stats(summary) if summary else None
            if s:
                venue = parsed.get('venue','')
                stats[mid]={'home':home,'away':away,'score':score,
                    'date':f"{parsed['date']}{' - '+venue if venue else ''}",
                    'poss':s['poss'],'stats':s['stats'],'xtra':s['xtra']}
                stats_added+=1
                print(f"  ✓ stats {mid}")

    # ── Upcoming ──────────────────────────────────────────────────────────────
    if fd_token:
        print("\nFetching upcoming fixtures...")
        fetch_upcoming(fd_token, played_keys)

    goals.sort(key=lambda g:(int(g['matchId'].replace('m','').replace('M','')),g['minute']))
    goals = apply_type_overrides(goals)  # re-apply permanent free-kick/header types
    save('matches.json',matches); save('match_stats.json',stats); save('goals.json',goals)

    # Balance: group goals must equal sum of group scores. Knockout goals are
    # counted separately (knockout matches aren't in matches.json).
    group_mids = {m['id'] for m in matches}
    group_goals = [g for g in goals if g['matchId'] in group_mids]
    ko_goals = [g for g in goals if g['matchId'] not in group_mids]
    score_sum = sum(sum(int(p) for p in m['score'].split('-')) for m in matches)
    balanced  = len(group_goals)==score_sum

    print(f"""
═══════════════════════════════
SUMMARY
  Matches : {len(matches)}  (+{matches_added} new)
  Stats   : {len(stats)}
  Goals   : {len(goals)}  (group {len(group_goals)} + knockout {len(ko_goals)}; +{goals_added} new, {goals_fixed} fixed)
  Balance : {len(group_goals)} = {score_sum} {'✓' if balanced else '✗ MISMATCH'}
═══════════════════════════════""")

    if not balanced:
        print("  Missing:")
        for m in matches:
            g=goals_by_mid.get(m['id'],[])
            h,a=map(int,m['score'].split('-'))
            if len(g)!=h+a:
                print(f"  ⚠ {m['id']} {m['home']} {m['score']} {m['away']}  have={len(g)} need={h+a}")

if __name__=='__main__':
    print(f"=== Match Stats Updater — {datetime.date.today()} ===")
    run()
