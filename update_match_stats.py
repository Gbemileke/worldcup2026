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
    'K. Mbappe': 'K. Mbappé',
    'V. Júnior': 'Vinicius Jr.',
    'V. Junior': 'Vinicius Jr.',
    'Vinícius Júnior': 'Vinicius Jr.',
    'Vinicius Júnior': 'Vinicius Jr.',
    'Vinícius Jr.': 'Vinicius Jr.',
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

def scorer_fmt(raw):
    if not raw: return ''
    parts = raw.strip().split()
    name = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts)>1 else raw.strip()
    # Canonicalize: if the accent-stripped name matches an alias key, use the canonical form
    stripped = _strip_accents(name)
    for key, canon in SCORER_ALIASES.items():
        if stripped == _strip_accents(key):
            return canon
    return name

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

        # Team — use homeScore/awayScore diff to determine who scored
        # This is more reliable than team.displayName which can be wrong
        home_score = p.get('homeScore', p.get('homeAthlete',{}).get('score',0))
        away_score = p.get('awayScore', p.get('awayAthlete',{}).get('score',0))
        team_disp  = sn(p.get('team',{}).get('displayName',''))

        # Use explicit team if available, else infer from score
        if team_disp in (home, away):
            team = team_disp
        elif isinstance(home_score,int) and isinstance(away_score,int):
            # We'll determine team during assign_goals from running score
            team = team_disp or home  # fallback
        else:
            team = team_disp or home

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

        # If ESPN provided running scores, use them to determine team
        hs = gd.get('home_score')
        as_ = gd.get('away_score')
        if hs is not None and as_ is not None:
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
            upcoming.append({'date':date_s,'home':home,'away':away,'time':time_s,'group':grp})
        if upcoming:
            save('upcoming_fixtures.json', upcoming)
            print(f"  Upcoming: {len(upcoming)} fixtures")
    except Exception as e:
        print(f"  Upcoming error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def run():
    asa_key  = os.environ.get('ALLSPORTSAPI_KEY','').strip()
    fd_token = os.environ.get('FOOTBALL_DATA_TOKEN','').strip()

    matches  = load('matches.json')     or []
    stats    = load('match_stats.json') or {}
    goals    = load('goals.json')       or []

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
        try: h_fin,a_fin = map(int,score.split('-'))
        except: continue

        mid = match_lookup.get(key) or match_lookup.get(f"{away}|{home}")

        # Add new match
        if not mid:
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

    goals.sort(key=lambda g:(int(g['matchId'].replace('m','')),g['minute']))
    goals = apply_type_overrides(goals)  # re-apply permanent free-kick/header types
    save('matches.json',matches); save('match_stats.json',stats); save('goals.json',goals)

    score_sum = sum(sum(int(p) for p in m['score'].split('-')) for m in matches)
    balanced  = len(goals)==score_sum

    print(f"""
═══════════════════════════════
SUMMARY
  Matches : {len(matches)}  (+{matches_added} new)
  Stats   : {len(stats)}
  Goals   : {len(goals)}  (+{goals_added} new, {goals_fixed} fixed)
  Balance : {len(goals)} = {score_sum} {'✓' if balanced else '✗ MISMATCH'}
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
