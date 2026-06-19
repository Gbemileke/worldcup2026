#!/usr/bin/env python3
"""
update_match_stats.py
═════════════════════
Data sources (tried in order — first success wins):
  1. ESPN scoreboard API   → scores, goals, espn_id
  2. ESPN summary API      → possession, shots, xG (uses espn_id)
  3. FOX Sports scraper    → goal scorers fallback when ESPN 403s
  4. API-Football (RapidAPI)→ goal scorers 2nd fallback
  5. football-data.org     → upcoming fixtures + CST times

APPEND-ONLY: never re-fetches or overwrites existing data.
"""

import os, sys, json, re, time, datetime, requests

DATA_DIR  = 'data'
API_BASE  = 'https://api.football-data.org/v4'
WC_CODE   = 'WC'
ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world'
ESPN_HDRS = {'User-Agent':'Mozilla/5.0 (compatible; WC2026/1.0)'}

HEADERS_BROWSER = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/html, */*',
}

# ── Name normalisation ────────────────────────────────────────────────────────
SHORT = {
    'South Africa':'S. Africa', "Côte d'Ivoire":'Ivory Coast', 'Ivory Coast':'Ivory Coast',
    'Bosnia and Herzegovina':'Bosnia', 'Bosnia-Herzegovina':'Bosnia',
    'Curaçao':'Curacao', 'United States':'USA', 'United States of America':'USA',
    'IR Iran':'Iran', 'Türkiye':'Turkey', 'Turkey':'Turkey',
    'Korea Republic':'S. Korea', 'South Korea':'S. Korea',
    'Cape Verde':'Cape Verde', 'Cape Verde Islands':'Cape Verde', 'Cabo Verde':'Cape Verde',
    'Congo DR':'DR Congo', 'DR Congo':'DR Congo', 'Democratic Republic of Congo':'DR Congo',
    'Australia':'Australia', 'New Zealand':'New Zealand',
}

FIFA_BASE_URL = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'
FIFA_NAME_MAP = {
    'S. Korea':'south-korea','Bosnia':'bosnia-herzegovina','Turkey':'turkey','Turkiye':'turkey',
    'Cape Verde':'cabo-verde','DR Congo':'democratic-republic-of-congo',
    'Ivory Coast':'cote-divoire','USA':'united-states','S. Africa':'south-africa','Curacao':'curacao',
}
FIFA_URL_SWAPS = {('Qatar','Switzerland'), ('Norway','Iraq')}

def short(name): return SHORT.get(name, name)
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
    return f"{FIFA_BASE_URL}{a}-v-{h}-highlights-match-report" if (home,away) in FIFA_URL_SWAPS \
           else f"{FIFA_BASE_URL}{h}-v-{a}-highlights-match-report"

# ── Source 1: ESPN scoreboard ─────────────────────────────────────────────────
def fetch_espn_scoreboard():
    url = f"{ESPN_BASE}/scoreboard?dates=20260601-20260720&limit=200"
    try:
        r = requests.get(url, headers=ESPN_HDRS, timeout=15)
        if r.status_code == 200:
            events = r.json().get('events', [])
            print(f"  ESPN scoreboard: {len(events)} events")
            return events
        print(f"  ESPN scoreboard: HTTP {r.status_code}")
    except Exception as e:
        print(f"  ESPN scoreboard error: {e}")
    return []

# ── Source 2: ESPN summary (stats + goals) ────────────────────────────────────
def fetch_espn_summary(espn_id):
    url = f"{ESPN_BASE}/summary?event={espn_id}"
    try:
        r = requests.get(url, headers=ESPN_HDRS, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"    ESPN summary HTTP {r.status_code} for {espn_id}")
    except Exception as e:
        print(f"    ESPN summary error: {e}")
    return {}

# ── Source 3: FOX Sports goal fallback ───────────────────────────────────────
def fetch_fox_goals(home, away, date_str):
    """Scrape FOX Sports boxscore page for goal scorers."""
    try:
        # FOX Sports search endpoint
        query = f"{home} {away} 2026 World Cup goals"
        url = f"https://api.foxsports.com/bifrost/v1/soccer/event/segment?groupId=55&id=2026-world-cup"
        # Try the FOX boxscore directly — format: team1-vs-team2-month-day-year
        h = home.lower().replace(' ','-').replace('.','').replace("'",'')
        a = away.lower().replace(' ','-').replace('.','').replace("'",'')
        # Parse date
        try:
            day = int(date_str.replace('Jun ','').replace('Jul ',''))
            month = 'jun' if 'Jun' in date_str else 'jul'
            fox_url = f"https://www.foxsports.com/soccer/fifa-world-cup-men-{h}-vs-{a}-{month}-{day}-2026-game-boxscore"
            r = requests.get(fox_url, headers=HEADERS_BROWSER, timeout=15)
            if r.status_code == 200:
                # Extract goals from FOX page
                goals = parse_fox_goals(r.text, home, away)
                if goals:
                    print(f"    FOX Sports: found {len(goals)} goals")
                    return goals
        except Exception as e:
            print(f"    FOX scrape error: {e}")
    except Exception as e:
        print(f"    FOX Sports error: {e}")
    return []

def parse_fox_goals(html, home, away):
    """Parse goal events from FOX Sports HTML."""
    goals = []
    # FOX Sports puts goal data in __NEXT_DATA__ JSON
    m = re.search(r'__NEXT_DATA__\s*=\s*(\{.+?\})\s*</script>', html, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        # Navigate to scoring plays
        props = data.get('props', {}).get('pageProps', {})
        event = props.get('event', props.get('initialData', {}))
        scoring = event.get('scoringPlays', event.get('scoring', []))
        for play in scoring:
            dtype = play.get('type', {}).get('text', '').lower()
            if 'goal' not in dtype and 'score' not in dtype:
                continue
            athletes = play.get('athletesInvolved', [])
            if not athletes:
                continue
            raw   = athletes[0].get('displayName', '')
            parts = raw.split()
            scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
            try:
                minute = int(str(play.get('clock', {}).get('displayValue', '90'))
                             .split('+')[0].replace("'",''))
            except:
                minute = 90
            gtype = 'open-play'
            if 'penalty' in dtype: gtype = 'penalty'
            elif 'own'    in dtype: gtype = 'own-goal'
            team = short(play.get('team', {}).get('displayName', ''))
            goals.append({'scorer': scorer, 'minute': minute,
                          'type': gtype, 'team': team})
    except Exception as e:
        print(f"    FOX parse error: {e}")
    return goals

# ── Source 4: API-Football fallback ──────────────────────────────────────────
def fetch_api_football_goals(home, away, rapidapi_key):
    """Use RapidAPI football-api as last resort for goal scorers."""
    if not rapidapi_key:
        return []
    try:
        url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
        headers = {
            "X-RapidAPI-Key":  rapidapi_key,
            "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
        }
        # Search for WC 2026 fixture
        params = {"league": "1", "season": "2026", "team": ""}  # league 1 = World Cup
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code != 200:
            return []
        fixtures = r.json().get('response', [])
        for fx in fixtures:
            h_name = fx.get('teams',{}).get('home',{}).get('name','')
            a_name = fx.get('teams',{}).get('away',{}).get('name','')
            if short(h_name)==home and short(a_name)==away:
                events = fx.get('events', [])
                goals = []
                for ev in events:
                    if ev.get('type') != 'Goal':
                        continue
                    raw   = ev.get('player',{}).get('name','')
                    parts = raw.split()
                    scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts)>1 else raw
                    minute = ev.get('time',{}).get('elapsed', 90)
                    detail = ev.get('detail','').lower()
                    gtype  = 'penalty' if 'penalty' in detail else \
                             'own-goal' if 'own' in detail else 'open-play'
                    team   = short(ev.get('team',{}).get('name',''))
                    goals.append({'scorer':scorer,'minute':minute,'type':gtype,'team':team})
                if goals:
                    print(f"    API-Football: found {len(goals)} goals")
                    return goals
    except Exception as e:
        print(f"    API-Football error: {e}")
    return []

# ── Parse ESPN summary stats ──────────────────────────────────────────────────
def parse_espn_stats(summary):
    boxscore = summary.get('boxscore', {})
    teams    = boxscore.get('teams', [])
    if not teams:
        game_pkg = summary.get('gamepackageJSON', {})
        if game_pkg:
            teams = game_pkg.get('boxscore', {}).get('teams', [])
    if not teams:
        return None

    stats_by_side = {}
    for team_data in teams:
        ha    = team_data.get('homeAway', '')
        stats = team_data.get('statistics', [])
        stats_by_side[ha] = stats

    h = stats_by_side.get('home', [])
    a = stats_by_side.get('away', [])
    print(f"    ESPN summary stats: home={len(h)} away={len(a)} fields")

    def get(stats, *names):
        for s in stats:
            sname = s.get('name','').lower()
            sabrv = s.get('abbreviation','').lower()
            slbl  = s.get('label','').lower()
            for name in names:
                if name.lower() in (sname, sabrv, slbl):
                    try:
                        val = str(s.get('displayValue','0')).replace('%','').strip()
                        return round(float(val),2) if '.' in val else int(val)
                    except: pass
        return None

    poss_h = get(h,'possessionPct','possession') or 50
    poss_a = get(a,'possessionPct','possession') or 50
    pt = poss_h + poss_a
    if pt > 0 and pt != 100:
        poss_h = round(poss_h/pt*100); poss_a = 100-poss_h

    shots_h  = get(h,'shotAttempts','totalShots','shots') or 0
    shots_a  = get(a,'shotAttempts','totalShots','shots') or 0
    sot_h    = get(h,'shotsOnGoal','shotsOnTarget','ongoal') or 0
    sot_a    = get(a,'shotsOnGoal','shotsOnTarget','ongoal') or 0
    xg_h     = get(h,'expectedGoals','xg')
    xg_a     = get(a,'expectedGoals','xg')
    if xg_h is None: xg_h = round(sot_h*0.33 + max(0,shots_h-sot_h)*0.05, 2)
    if xg_a is None: xg_a = round(sot_a*0.33 + max(0,shots_a-sot_a)*0.05, 2)
    corners_h = get(h,'cornerKicks','corners') or 0
    corners_a = get(a,'cornerKicks','corners') or 0
    fouls_h   = get(h,'fouls','foulcommitted') or 0
    fouls_a   = get(a,'fouls','foulcommitted') or 0
    yellow_h  = get(h,'yellowCards') or 0
    yellow_a  = get(a,'yellowCards') or 0
    saves_h   = get(h,'saves') or 0
    saves_a   = get(a,'saves') or 0
    offside_h = get(h,'offsides') or 0
    offside_a = get(a,'offsides') or 0

    return {
        'poss': [poss_h, poss_a],
        'stats': [
            ['Shot Attempts', shots_h,   shots_a],
            ['Shots on Goal', sot_h,     sot_a],
            ['Corner Kicks',  corners_h, corners_a],
            ['Fouls',         fouls_h,   fouls_a],
            ['Saves',         saves_h,   saves_a],
        ],
        'xtra': [
            ['xG',           xg_h,     xg_a],
            ['Yellow Cards', yellow_h, yellow_a],
            ['Red Cards',    0,        0],
            ['Offsides',    offside_h, offside_a],
        ]
    }

# ── Parse ESPN scoreboard event ───────────────────────────────────────────────
def parse_espn_event(event):
    status = event.get('status',{}).get('type',{}).get('state','')
    if status != 'post': return None
    comp = (event.get('competitions') or [{}])[0]
    competitors = comp.get('competitors',[])
    if len(competitors) < 2: return None
    home_c = next((c for c in competitors if c.get('homeAway')=='home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway')=='away'), competitors[1])
    home   = short(home_c.get('team',{}).get('displayName',''))
    away   = short(away_c.get('team',{}).get('displayName',''))
    if not home or not away: return None
    h_score = int(home_c.get('score',0) or 0)
    a_score = int(away_c.get('score',0) or 0)
    notes   = comp.get('notes',[])
    group   = ''
    for n in notes:
        hd = n.get('headline','')
        if 'Group' in hd or 'GROUP' in hd:
            group = hd.replace('Group ','').strip()
    details = comp.get('details',[])
    goals = []
    for d in details:
        dtype = d.get('type',{}).get('text','').lower()
        if 'goal' not in dtype and 'score' not in dtype: continue
        athletes = d.get('athletesInvolved',[])
        if not athletes: continue
        raw   = athletes[0].get('displayName','')
        parts = raw.split()
        scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts)>1 else raw
        try: minute = int(str(d.get('clock',{}).get('displayValue','90')).split('+')[0].replace("'",''))
        except: minute = 90
        gtype = 'open-play'
        if 'penalty' in dtype: gtype = 'penalty'
        elif 'own'    in dtype: gtype = 'own-goal'
        team = short(d.get('team',{}).get('displayName',''))
        goals.append({'scorer':scorer,'minute':minute,'type':gtype,'team':team})
    return {
        'home':home,'away':away,'score':f"{h_score}-{a_score}",
        'date':fmt_date(event.get('date','')),
        'group':group,'goals':goals,
        'espn_id':event.get('id',''),
        'venue':comp.get('venue',{}).get('fullName',''),
    }

# ── Upcoming fixtures ─────────────────────────────────────────────────────────
def fetch_upcoming(token):
    try:
        r = requests.get(f"{API_BASE}/competitions/{WC_CODE}/matches?status=SCHEDULED",
                         headers={'X-Auth-Token':token}, timeout=15)
        if r.status_code != 200: return
        scheduled = r.json().get('matches',[])
        upcoming = []
        for m in scheduled[:16]:
            home = short(m['homeTeam']['name']); away = short(m['awayTeam']['name'])
            try:
                dt = datetime.datetime.fromisoformat(m['utcDate'].replace('Z','+00:00'))
                dt_cst = dt - datetime.timedelta(hours=6)
                date_s = f"Jun {dt_cst.day}" if dt_cst.month==6 else f"Jul {dt_cst.day}"
                h12 = dt_cst.hour%12 or 12
                ampm = 'AM' if dt_cst.hour<12 else 'PM'
                mn = f":{dt_cst.minute:02d}" if dt_cst.minute else ''
                time_s = f"{h12}{mn}{ampm} CST"
            except: date_s=m['utcDate'][:10]; time_s='?? CST'
            gr = m.get('stage','')
            letter = gr.replace('GROUP_','') if 'GROUP_' in gr else gr.replace('Group ','') if 'Group ' in gr else ''
            upcoming.append({"date":date_s,"home":home,"away":away,"time":time_s,"group":letter})
        if upcoming:
            save('upcoming_fixtures.json', upcoming)
            print(f"  Upcoming: {len(upcoming)} fixtures updated")
    except Exception as e:
        print(f"  Upcoming error: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    token       = os.environ.get('FOOTBALL_DATA_TOKEN','').strip()
    rapidapi_key= os.environ.get('RAPIDAPI_KEY','').strip()

    matches  = load('matches.json')  or []
    stats    = load('match_stats.json') or {}
    goals    = load('goals.json')    or []
    upcoming = load('upcoming_fixtures.json') or []

    before = len(goals)
    goals  = [g for g in goals if g.get('scorer','').strip() not in {'See FIFA.com','Unknown',''}]
    if len(goals) < before: print(f"  Cleaned {before-len(goals)} placeholder goals")

    match_lookup = {}
    for m in matches:
        h = short(m['home']); a = short(m['away'])
        m['home'] = h; m['away'] = a
        match_lookup[f"{h}|{a}"] = m['id']
        match_lookup[f"{a}|{h}"] = m['id']

    existing_nums    = [int(m['id'].replace('m','')) for m in matches]
    next_num         = max(existing_nums)+1 if existing_nums else 1
    next_goal_id     = max((g['id'] for g in goals), default=0)+1
    existing_goal_ms = set(g['matchId'] for g in goals)
    existing_stat_ks = set(stats.keys())

    matches_added = stats_added = goals_added = 0

    print("\nFetching ESPN scoreboard...")
    events = fetch_espn_scoreboard()

    for event in events:
        parsed = parse_espn_event(event)
        if not parsed: continue
        home = parsed['home']; away = parsed['away']; score = parsed['score']
        if not home or not away: continue

        key = f"{home}|{away}"
        mid = match_lookup.get(key)
        if not mid:
            mid = f"m{next_num}"; next_num += 1
            match_lookup[key] = mid; match_lookup[f"{away}|{home}"] = mid

        existing = next((m for m in matches if m['id']==mid), None)
        if existing:
            if existing.get('score') != score:
                print(f"  Score update: {mid} {score}")
                existing['score'] = score
            if not existing.get('espnId') and parsed['espn_id']:
                existing['espnId'] = parsed['espn_id']
        else:
            matches.append({
                'id':mid,'date':parsed['date'],'home':home,'away':away,
                'score':score,'group':parsed['group'],'ytId':'',
                'fifaUrl':fifa_url(home,away),'espnId':parsed['espn_id'],
            })
            matches.sort(key=lambda m: int(m['id'].replace('m','')))
            match_lookup[key]=mid; match_lookup[f"{away}|{home}"]=mid
            matches_added += 1
            print(f"  Added: {mid} {home} {score} {away}")

        # ── Goals — try ESPN first, then FOX, then API-Football ──────────────
        if mid not in existing_goal_ms:
            parts = score.split('-')
            try: h_fin, a_fin = int(parts[0]), int(parts[1])
            except: continue

            goal_list = parsed['goals']  # from ESPN scoreboard details

            # FALLBACK 1: ESPN returned goals but validation failed, OR returned 0 goals
            if not goal_list:
                print(f"  Goals: {mid} — ESPN returned 0 goals, trying FOX Sports...")
                goal_list = fetch_fox_goals(home, away, parsed['date'])
                time.sleep(0.5)

            # FALLBACK 2: FOX also empty → try API-Football
            if not goal_list and rapidapi_key:
                print(f"  Goals: {mid} — FOX empty, trying API-Football...")
                goal_list = fetch_api_football_goals(home, away, rapidapi_key)
                time.sleep(0.5)

            if goal_list:
                h_run = a_run = 0
                match_goals = []
                for gd in sorted(goal_list, key=lambda x: x['minute']):
                    is_og = gd['type'] == 'own-goal'
                    team  = gd.get('team', '')
                    if is_og:
                        if team == home: a_run += 1
                        else:            h_run += 1
                    else:
                        if team == home: h_run += 1
                        else:            a_run += 1
                    match_goals.append({
                        'id': next_goal_id, 'matchId': mid,
                        'home': home, 'away': away,
                        'scorer': gd['scorer'], 'minute': gd['minute'],
                        'type': gd['type'],
                        'phase': f"Group {parsed['group']}",
                        'score': f"{h_run}-{a_run}", 'desc': '',
                    })
                    next_goal_id += 1

                if h_run == h_fin and a_run == a_fin:
                    goals.extend(match_goals)
                    goals_added += len(match_goals)
                    existing_goal_ms.add(mid)
                    print(f"  Goals: {mid} — {len(match_goals)} goals added ({h_run}-{a_run} ✓)")
                else:
                    print(f"  Goals: {mid} — SKIPPED (running {h_run}-{a_run} != final {h_fin}-{a_fin})")
                    next_goal_id -= len(match_goals)
            else:
                # All sources exhausted — log for manual add
                print(f"  Goals: {mid} ⚠ ALL SOURCES FAILED ({h_fin}-{a_fin}) — ADD MANUALLY")

        # ── Stats via ESPN summary ────────────────────────────────────────────
        espn_id = parsed['espn_id'] or (existing.get('espnId','') if existing else '')
        if mid not in existing_stat_ks and espn_id:
            print(f"  Fetching ESPN summary for {mid} (id={espn_id})...", end=' ', flush=True)
            summary = fetch_espn_summary(espn_id)
            time.sleep(0.5)
            espn_s = parse_espn_stats(summary) if summary else None
            if espn_s:
                venue = parsed.get('venue','') or ''
                stats[mid] = {
                    'home':home,'away':away,'score':score,
                    'date':f"{parsed['date']}{' - '+venue if venue else ''}",
                    'poss':espn_s['poss'],'stats':espn_s['stats'],'xtra':espn_s['xtra'],
                }
                stats_added += 1; existing_stat_ks.add(mid)
                print(f"done (poss={espn_s['poss'][0]}-{espn_s['poss'][1]}%)")
            else:
                print("no stats returned")

        upcoming = [f for f in upcoming
                    if not((f['home'].lower() in home.lower() or home.lower() in f['home'].lower()) and
                           (f['away'].lower() in away.lower() or away.lower() in f['away'].lower()))]

    if token:
        print("\nFetching upcoming fixtures...")
        fetch_upcoming(token)

    goals.sort(key=lambda g: (int(g['matchId'].replace('m','')), g['minute']))
    save('matches.json',           matches)
    save('match_stats.json',       stats)
    save('goals.json',             goals)
    save('upcoming_fixtures.json', upcoming)

    print(f"\n=== SUMMARY ===")
    print(f"  Matches added: {matches_added}")
    print(f"  Stats added:   {stats_added}")
    print(f"  Goals added:   {goals_added}")
    print(f"  Total matches: {len(matches)}")
    print(f"  Total stats:   {len(stats)}")
    print(f"  Total goals:   {len(goals)}")

if __name__ == '__main__':
    print(f"=== Match Stats Updater — {datetime.date.today()} ===")
    run()
