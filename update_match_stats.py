#!/usr/bin/env python3
"""
update_match_stats.py  —  WC 2026 automated data updater
═══════════════════════════════════════════════════════════
PRIMARY goal source : AllSportsAPI (allsportsapi.com)
  - Set ALLSPORTSAPI_KEY in GitHub secrets
  - Free tier: 100 req/day — enough for 3-hourly updates
  - Returns goalscorers with minute, type, running score

SECONDARY goal source : ESPN (scores + stats only, no goal details from Actions IPs)

Pipeline per run:
  1. AllSportsAPI → fetch all WC finished matches with goalscorers
  2. ESPN scoreboard → cross-check scores, pick up espnId
  3. ESPN summary  → match stats (possession, shots, xG, cards)
  4. Sync completed matches out of upcoming_fixtures.json
  5. Auto-patch WC_RESULTS in update_rankings.py
"""

import os, json, re, time, datetime, requests

DATA_DIR  = 'data'
ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world'
API_BASE  = 'https://api.football-data.org/v4'

# AllSportsAPI
ASA_BASE    = 'https://allsportsapi.com/api/football/'
WC_LEAGUE   = '1369'   # starting ID, auto-updated if wrong

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json',
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
    'New Zealand':'New Zealand',
}

FIFA_NAME_MAP = {
    'S. Korea':'south-korea', 'Bosnia':'bosnia-herzegovina',
    'Turkey':'turkey', 'Cape Verde':'cabo-verde',
    'DR Congo':'democratic-republic-of-congo', 'Ivory Coast':'cote-divoire',
    'USA':'united-states', 'S. Africa':'south-africa', 'Curacao':'curacao',
}
FIFA_BASE_URL = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'
FIFA_SWAP     = {('Qatar','Switzerland'), ('Norway','Iraq')}

def sn(n):
    return SHORT.get(n, n) if n else ''

def load(f):
    p = os.path.join(DATA_DIR, f)
    return json.load(open(p)) if os.path.exists(p) else None

def save(f, d):
    with open(os.path.join(DATA_DIR, f), 'w') as fp:
        json.dump(d, fp, indent=2)

def fmt_date(s):
    try:
        dt = datetime.datetime.fromisoformat(s.replace('Z',''))
        return f"Jun {dt.day}" if dt.month == 6 else f"Jul {dt.day}"
    except:
        return s[:10]

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

def scorer_fmt(raw):
    """Format 'Firstname Lastname' → 'F. Lastname'"""
    if not raw: return ''
    parts = raw.strip().split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw.strip()

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — AllSportsAPI  (PRIMARY goal source)
# ══════════════════════════════════════════════════════════════════════════════
# Known WC 2026 league IDs to try on AllSportsAPI
WC_LEAGUE_IDS = ['1369', '1165', '28', '36', '1388', '1390']

def fetch_allsports(asa_key, date_from, date_to):
    """
    Fetch all WC finished matches with goalscorers from AllSportsAPI.
    Tries multiple strategies to find the correct league.
    """
    if not asa_key:
        print("  AllSportsAPI: no key set (ALLSPORTSAPI_KEY)")
        return []

    # Strategy 1: No leagueId — get ALL fixtures for date range, filter WC ones
    print("  AllSportsAPI: trying without leagueId (all fixtures)...")
    results = _asa_fetch(asa_key, date_from, date_to, league_id=None)
    wc = _filter_wc(results)
    if wc:
        print(f"  AllSportsAPI: {len(wc)} WC matches found (no leagueId)")
        return wc

    # Strategy 2: Try known WC league IDs
    for lid in WC_LEAGUE_IDS:
        print(f"  AllSportsAPI: trying leagueId={lid}...")
        results = _asa_fetch(asa_key, date_from, date_to, league_id=lid)
        wc = _filter_wc(results)
        if wc:
            print(f"  AllSportsAPI: {len(wc)} WC matches found (leagueId={lid})")
            global WC_LEAGUE
            WC_LEAGUE = lid  # cache the working ID
            return wc
        time.sleep(0.5)

    # Strategy 3: met=Livescore (no date filter needed)
    print("  AllSportsAPI: trying Livescore endpoint...")
    try:
        r = requests.get(f"{ASA_BASE}?met=Livescore&APIkey={asa_key}",
                         headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            results = data.get('result') or []
            wc = _filter_wc(results)
            if wc:
                print(f"  AllSportsAPI: {len(wc)} WC live matches")
                return wc
    except Exception as e:
        print(f"  AllSportsAPI Livescore error: {e}")

    print("  AllSportsAPI: no WC matches found — check ALLSPORTSAPI_KEY and league ID")
    return []

def _asa_fetch(asa_key, date_from, date_to, league_id=None):
    """Single AllSportsAPI request, returns raw result list."""
    try:
        url = f"{ASA_BASE}?met=Fixtures&APIkey={asa_key}&from={date_from}&to={date_to}"
        if league_id:
            url += f"&leagueId={league_id}"
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            data = r.json()
            if data.get('success'):
                return data.get('result') or []
            print(f"    API error: {data.get('error','')}")
        else:
            print(f"    HTTP {r.status_code}")
    except Exception as e:
        print(f"    fetch error: {e}")
    return []

def _filter_wc(results):
    """Filter results to World Cup matches only."""
    if not results:
        return []
    WC_KEYWORDS = ['world cup', 'fifa world', 'wc 2026', 'world cup 2026', 'mondial']
    finished_statuses = {'Finished','FT','finished','ft','Match Finished','Full Time'}
    wc = []
    for m in results:
        league = (m.get('league_name','') or m.get('event_league_title','') or '').lower()
        status = m.get('event_status','') or m.get('event_final_result','')
        is_wc  = any(kw in league for kw in WC_KEYWORDS)
        is_done = status in finished_statuses or (
            m.get('event_final_result','?') not in ('?','','0-0') and
            m.get('event_status','') in ('Finished','FT','Match Finished')
        )
        if is_wc or (is_done and _is_wc_teams(m)):
            wc.append(m)
    return wc

def _is_wc_teams(m):
    """Check if both teams are WC 2026 participants."""
    WC_TEAMS = {
        'argentina','france','spain','england','brazil','portugal','netherlands',
        'germany','belgium','croatia','colombia','mexico','usa','senegal','uruguay',
        'japan','switzerland','iran','turkey','ecuador','austria','south korea',
        'australia','algeria','egypt','canada','norway','ivory coast','sweden',
        'czechia','paraguay','scotland','ghana','panama','morocco','saudi arabia',
        'qatar','iraq','south africa','jordan','bosnia','cape verde','dr congo',
        'uzbekistan','new zealand','curacao','haiti','tunisia'
    }
    h = (m.get('event_home_team','') or '').lower()
    a = (m.get('event_away_team','') or '').lower()
    return any(t in h for t in WC_TEAMS) and any(t in a for t in WC_TEAMS)

def parse_allsports_goals(event, home, away):
    """
    Parse goalscorers from AllSportsAPI event dict.
    Returns list of {scorer, minute, type, team} dicts.
    """
    raw_goals = event.get('goalscorers') or []
    goals = []
    for g in raw_goals:
        info   = (g.get('info') or '').lower().strip()
        time_s = str(g.get('time') or g.get('minute') or '').replace("'",'').strip()
        # Stoppage time: "45+2" → 46
        try:
            if '+' in time_s:
                parts = time_s.split('+')
                minute = int(parts[0]) + (1 if int(parts[1]) > 0 else 0)
            else:
                minute = int(time_s) if time_s else 90
        except:
            minute = 90

        home_scorer = (g.get('home_scorer') or '').strip()
        away_scorer = (g.get('away_scorer') or '').strip()

        if home_scorer:
            raw    = home_scorer
            team   = home
            gtype  = ('penalty'  if 'penalty'  in info else
                      'own-goal' if 'own' in info else 'open-play')
        elif away_scorer:
            raw    = away_scorer
            team   = away
            gtype  = ('penalty'  if 'penalty'  in info else
                      'own-goal' if 'own' in info else 'open-play')
        else:
            continue   # skip empty rows

        scorer = scorer_fmt(raw)
        if not scorer:
            continue

        goals.append({'scorer': scorer, 'minute': minute,
                      'type': gtype, 'team': team})

    return goals

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — ESPN scoreboard  (scores + espnId only)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_espn_scoreboard():
    url = f"{ESPN_BASE}/scoreboard?dates=20260601-20260720&limit=200"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                events = r.json().get('events', [])
                print(f"  ESPN scoreboard: {len(events)} events")
                return events
            print(f"  ESPN scoreboard: HTTP {r.status_code} (attempt {attempt+1}/3)")
            time.sleep(5 * (attempt + 1))
        except Exception as e:
            print(f"  ESPN scoreboard error: {e}")
        time.sleep(2)
    return []

def parse_espn_event(event):
    """Extract score, teams, espnId, group from ESPN event."""
    if event.get('status',{}).get('type',{}).get('state','') != 'post':
        return None
    comp        = (event.get('competitions') or [{}])[0]
    competitors = comp.get('competitors', [])
    if len(competitors) < 2:
        return None

    home_c = next((c for c in competitors if c.get('homeAway')=='home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway')=='away'), competitors[1])
    home   = sn(home_c.get('team',{}).get('displayName',''))
    away   = sn(away_c.get('team',{}).get('displayName',''))
    if not home or not away:
        return None

    h_score = int(home_c.get('score', 0) or 0)
    a_score = int(away_c.get('score', 0) or 0)

    group = ''
    for n in comp.get('notes', []):
        g = re.search(r'Group\s+([A-Z])', n.get('headline',''), re.I)
        if g:
            group = g.group(1)
            break

    return {
        'home': home, 'away': away,
        'score': f"{h_score}-{a_score}",
        'date': fmt_date(event.get('date','')),
        'group': group,
        'espn_id': event.get('id',''),
        'venue': comp.get('venue',{}).get('fullName',''),
    }

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — ESPN summary  (match stats only)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_espn_summary(espn_id):
    try:
        r = requests.get(f"{ESPN_BASE}/summary?event={espn_id}",
                         headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"    ESPN summary HTTP {r.status_code}")
    except Exception as e:
        print(f"    ESPN summary error: {e}")
    return {}

def parse_espn_stats(summary):
    bs    = summary.get('boxscore', {})
    teams = bs.get('teams', [])
    if not teams:
        return None
    by_side = {td.get('homeAway',''): td.get('statistics',[]) for td in teams}
    h = by_side.get('home', [])
    a = by_side.get('away', [])

    poss_h = get_stat(h,'possessionPct','possession') or 50
    poss_a = get_stat(a,'possessionPct','possession') or 50
    pt = poss_h + poss_a
    if pt and pt != 100:
        poss_h = round(poss_h/pt*100); poss_a = 100-poss_h

    sot_h   = get_stat(h,'shotsOnGoal','shotsOnTarget','ongoal') or 0
    sot_a   = get_stat(a,'shotsOnGoal','shotsOnTarget','ongoal') or 0
    shots_h = get_stat(h,'shotAttempts','totalShots','shots') or sot_h
    shots_a = get_stat(a,'shotAttempts','totalShots','shots') or sot_a
    xg_h    = get_stat(h,'expectedGoals','xg') or round(sot_h*0.33+max(0,shots_h-sot_h)*0.05,2)
    xg_a    = get_stat(a,'expectedGoals','xg') or round(sot_a*0.33+max(0,shots_a-sot_a)*0.05,2)

    return {
        'poss': [poss_h, poss_a],
        'stats': [
            ['Shot Attempts', shots_h, shots_a],
            ['Shots on Goal', sot_h,   sot_a],
            ['Corner Kicks',  get_stat(h,'cornerKicks','corners') or 0,
                              get_stat(a,'cornerKicks','corners') or 0],
            ['Fouls',         get_stat(h,'fouls') or 0, get_stat(a,'fouls') or 0],
            ['Saves',         get_stat(h,'saves') or 0, get_stat(a,'saves') or 0],
        ],
        'xtra': [
            ['xG',           xg_h,  xg_a],
            ['Yellow Cards', get_stat(h,'yellowCards') or 0, get_stat(a,'yellowCards') or 0],
            ['Red Cards',    get_stat(h,'redCards') or 0,    get_stat(a,'redCards') or 0],
            ['Offsides',     get_stat(h,'offsides') or 0,    get_stat(a,'offsides') or 0],
        ]
    }

# ══════════════════════════════════════════════════════════════════════════════
# Goal assignment
# ══════════════════════════════════════════════════════════════════════════════
def assign_goals(goal_list, home, away, h_fin, a_fin, mid, group, next_id):
    """
    Build goal objects with running score. Validates final score matches.
    Returns (goals_list, next_id) or ([], next_id_unchanged) on failure.
    """
    h_run = a_run = 0
    built = []

    for gd in sorted(goal_list, key=lambda x: x.get('minute', 90)):
        is_og = gd['type'] == 'own-goal'
        team  = gd.get('team','')

        if is_og:
            # OG by home player → away scores; OG by away player → home scores
            if team == home:
                a_run += 1
            else:
                h_run += 1
        else:
            if team == home:
                h_run += 1
            else:
                a_run += 1

        built.append({
            'id':      next_id,
            'matchId': mid,
            'home':    home,
            'away':    away,
            'scorer':  gd['scorer'],
            'minute':  gd['minute'],
            'type':    gd['type'],
            'phase':   f"Group {group}" if group else 'Group Stage',
            'score':   f"{h_run}-{a_run}",
            'desc':    '',
        })
        next_id += 1

    if h_run == h_fin and a_run == a_fin:
        return built, next_id
    else:
        print(f"    ✗ Validation: built {h_run}-{a_run} ≠ final {h_fin}-{a_fin}")
        return [], next_id - len(built)

# ══════════════════════════════════════════════════════════════════════════════
# WC_RESULTS auto-patch
# ══════════════════════════════════════════════════════════════════════════════
def patch_wc_results(home, away, h, a):
    path = 'update_rankings.py'
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            content = f.read()
        # Check if already present (both orders)
        if (f'"home":"{home}"' in content and f'"away":"{away}"' in content):
            return
        result = 1.0 if h > a else 0.5 if h == a else 0.0
        line   = f'    {{"home":"{home}", "away":"{away}", "result":{result}}},  # {h}-{a}\n'
        marker = '    # ADD NEW RESULTS BELOW AS TOURNAMENT PROGRESSES:\n'
        if marker in content:
            content = content.replace(marker, line + marker, 1)
            with open(path,'w') as f:
                f.write(content)
            print(f"    WC_RESULTS: ✓ added {home} {h}-{a} {away}")
    except Exception as e:
        print(f"    WC_RESULTS error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# Upcoming fixtures
# ══════════════════════════════════════════════════════════════════════════════
def fetch_upcoming(token, played_keys):
    if not token:
        return
    try:
        r = requests.get(f"{API_BASE}/competitions/WC/matches?status=SCHEDULED",
                         headers={'X-Auth-Token': token}, timeout=15)
        if r.status_code != 200:
            return
        upcoming = []
        for m in r.json().get('matches', [])[:48]:
            # Skip TBD knockout fixtures
            if not m.get('homeTeam') or not m.get('awayTeam'): continue
            hn = m['homeTeam'].get('name',''); an = m['awayTeam'].get('name','')
            if not hn or not an: continue
            home = sn(hn); away = sn(an)
            if not home or not away: continue
            if f"{home}|{away}" in played_keys or f"{away}|{home}" in played_keys:
                continue
            try:
                dt    = datetime.datetime.fromisoformat(m['utcDate'].replace('Z','+00:00'))
                cst   = dt - datetime.timedelta(hours=6)
                date_s = f"Jun {cst.day}" if cst.month==6 else f"Jul {cst.day}"
                h12   = cst.hour%12 or 12
                ampm  = 'AM' if cst.hour<12 else 'PM'
                mn    = f":{cst.minute:02d}" if cst.minute else ''
                time_s = f"{h12}{mn}{ampm} CST"
            except:
                date_s = m['utcDate'][:10]; time_s='?? CST'
            gr  = m.get('stage','')
            grp = gr.replace('GROUP_','') if 'GROUP_' in gr else ''
            upcoming.append({'date':date_s,'home':home,'away':away,'time':time_s,'group':grp})
        if upcoming:
            save('upcoming_fixtures.json', upcoming)
            print(f"  Upcoming: {len(upcoming)} fixtures updated")
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

    # Build lookups
    match_lookup = {}
    for m in matches:
        m['home'] = sn(m['home']); m['away'] = sn(m['away'])
        match_lookup[f"{m['home']}|{m['away']}"] = m['id']
        match_lookup[f"{m['away']}|{m['home']}"] = m['id']

    existing_nums = [int(m['id'].replace('m','')) for m in matches]
    next_num      = max(existing_nums)+1 if existing_nums else 1
    next_goal_id  = max((g['id'] for g in goals), default=0)+1

    goals_by_mid  = {}
    for g in goals:
        goals_by_mid.setdefault(g['matchId'],[]).append(g)

    played_keys   = set(match_lookup.keys())
    matches_added = stats_added = goals_added = goals_fixed = 0

    # ── STEP 1: AllSportsAPI — get ALL WC matches with goalscorers ────────────
    print("\nStep 1: Fetching AllSportsAPI fixtures with goalscorers...")
    date_from = '2026-06-01'
    date_to   = datetime.date.today().strftime('%Y-%m-%d')
    asa_matches = fetch_allsports(asa_key, date_from, date_to)

    # Build ASA lookup: (home_short, away_short) → event
    asa_lookup = {}
    for evt in asa_matches:
        h = sn(evt.get('event_home_team',''))
        a = sn(evt.get('event_away_team',''))
        if h and a:
            asa_lookup[f"{h}|{a}"] = evt
            asa_lookup[f"{a}|{h}"] = evt

    # ── STEP 2: ESPN scoreboard — scores + espnId ─────────────────────────────
    print("\nStep 2: Fetching ESPN scoreboard for scores...")
    espn_events = fetch_espn_scoreboard()
    espn_parsed = {}
    for ev in espn_events:
        p = parse_espn_event(ev)
        if p:
            espn_parsed[f"{p['home']}|{p['away']}"] = p

    # ── STEP 3: Process each finished match ───────────────────────────────────
    print("\nStep 3: Processing matches...\n")

    # Combine keys from both sources
    all_keys = set(list(asa_lookup.keys()) + list(espn_parsed.keys()))
    processed = set()

    for key in all_keys:
        if '|' not in key: continue
        home, away = key.split('|',1)
        canonical  = f"{home}|{away}"
        reverse    = f"{away}|{home}"

        # Avoid processing same match twice
        if canonical in processed or reverse in processed:
            continue
        processed.add(canonical)

        # Get score — prefer ESPN (more reliable for final score)
        espn_p  = espn_parsed.get(canonical) or espn_parsed.get(reverse)
        asa_evt = asa_lookup.get(canonical)  or asa_lookup.get(reverse)

        if not espn_p and not asa_evt:
            continue

        # Determine final score
        if espn_p:
            score = espn_p['score']
        else:
            score = (asa_evt.get('event_final_result') or '').strip()
            if not score or '?' in score:
                continue

        try:
            h_fin, a_fin = map(int, score.split('-'))
        except:
            continue

        date    = (espn_p or {}).get('date','') or fmt_date(asa_evt.get('event_date','') if asa_evt else '')
        group   = (espn_p or {}).get('group','') or ''
        espn_id = (espn_p or {}).get('espn_id','') or ''
        venue   = (espn_p or {}).get('venue','')   or ''

        mid = match_lookup.get(canonical) or match_lookup.get(reverse)

        # Add new match if not seen before
        if not mid:
            mid = f"m{next_num}"; next_num += 1
            match_lookup[canonical] = mid
            match_lookup[reverse]   = mid
            played_keys.update([canonical, reverse])
            matches.append({
                'id':mid, 'date':date, 'home':home, 'away':away,
                'score':score, 'group':group, 'ytId':'',
                'fifaUrl':fifa_url(home,away), 'espnId':espn_id,
            })
            matches.sort(key=lambda m: int(m['id'].replace('m','')))
            matches_added += 1
            print(f"  ✚ {mid} {home} {score} {away}")
            patch_wc_results(home, away, h_fin, a_fin)
        else:
            ex = next(m for m in matches if m['id']==mid)
            if ex.get('score') != score:
                print(f"  ↺ Score {mid}: {ex['score']} → {score}")
                ex['score'] = score
                # Clear goals for re-fetch if score changed
                if mid in goals_by_mid:
                    goals = [g for g in goals if g['matchId']!=mid]
                    del goals_by_mid[mid]
                    next_goal_id = max((g['id'] for g in goals), default=0)+1
                patch_wc_results(home, away, h_fin, a_fin)
            if espn_id and not ex.get('espnId'):
                ex['espnId'] = espn_id
            if group and not ex.get('group'):
                ex['group'] = group

        # ── Goals ─────────────────────────────────────────────────────────────
        existing_g  = goals_by_mid.get(mid,[])
        needs_goals = len(existing_g) != (h_fin + a_fin)

        if needs_goals:
            total_needed = h_fin + a_fin
            have         = len(existing_g)
            print(f"  → Goals {mid} ({home} {score} {away}): have {have}, need {total_needed}")

            # Clear partial goals
            if existing_g:
                goals = [g for g in goals if g['matchId']!=mid]
                next_goal_id = max((g['id'] for g in goals), default=0)+1

            # PRIMARY: AllSportsAPI
            goal_list = []
            if asa_evt:
                goal_list = parse_allsports_goals(asa_evt, home, away)
                if goal_list:
                    print(f"    AllSportsAPI: {len(goal_list)} goals found")

            if goal_list:
                new_goals, next_goal_id = assign_goals(
                    goal_list, home, away, h_fin, a_fin, mid, group, next_goal_id)
                if new_goals:
                    goals.extend(new_goals)
                    goals_by_mid[mid] = new_goals
                    if have == 0:
                        goals_added += len(new_goals)
                    else:
                        goals_fixed += len(new_goals)
                    print(f"    ✓ {len(new_goals)} goals saved for {mid}")
                else:
                    print(f"    ✗ Validation failed for {mid} — will retry next run")
            else:
                print(f"    ⚠ No goal data from AllSportsAPI for {mid}")
                print(f"      → Add ALLSPORTSAPI_KEY to GitHub secrets if not set")

        # ── Stats ──────────────────────────────────────────────────────────────
        ex_match = next((m for m in matches if m['id']==mid), {})
        eid      = espn_id or ex_match.get('espnId','')
        if eid and (mid not in stats or stats[mid].get('score') != score):
            print(f"  → Stats {mid}...", end=' ', flush=True)
            summary = fetch_espn_summary(eid)
            time.sleep(0.3)
            s = parse_espn_stats(summary) if summary else None
            if s:
                stats[mid] = {
                    'home':home, 'away':away, 'score':score,
                    'date':f"{date}{' - '+venue if venue else ''}",
                    'poss':s['poss'], 'stats':s['stats'], 'xtra':s['xtra'],
                }
                stats_added += 1
                print(f"done")
            else:
                print(f"no stats")

    # ── Upcoming fixtures ──────────────────────────────────────────────────────
    if fd_token:
        print("\nStep 4: Fetching upcoming fixtures...")
        fetch_upcoming(fd_token, played_keys)

    # ── Save ───────────────────────────────────────────────────────────────────
    goals.sort(key=lambda g:(int(g['matchId'].replace('m','')), g['minute']))
    save('matches.json',     matches)
    save('match_stats.json', stats)
    save('goals.json',       goals)

    score_sum = sum(sum(int(p) for p in m['score'].split('-')) for m in matches)
    balanced  = len(goals) == score_sum

    print(f"""
═══════════════════════════════
SUMMARY
  Matches : {len(matches)}  (+{matches_added} new)
  Stats   : {len(stats)}
  Goals   : {len(goals)}  (+{goals_added} new, {goals_fixed} fixed)
  Balance : {len(goals)} = {score_sum} from scores {'✓' if balanced else '✗ MISMATCH'}
═══════════════════════════════""")

    if not balanced:
        print("  Missing goals:")
        for m in matches:
            g  = goals_by_mid.get(m['id'],[])
            h,a = map(int, m['score'].split('-'))
            if len(g) != h+a:
                print(f"  ⚠ {m['id']} {m['home']} {m['score']} {m['away']}  "
                      f"have={len(g)} need={h+a}")

if __name__ == '__main__':
    print(f"=== Match Stats Updater — {datetime.date.today()} ===")
    run()
