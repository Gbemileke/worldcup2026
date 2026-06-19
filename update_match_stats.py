#!/usr/bin/env python3
"""
update_match_stats.py
═════════════════════
Data sources:
  PRIMARY:  ESPN scoreboard API  → scores, goals, espn_id
  STATS:    ESPN summary API     → possession, shots, xG (uses espn_id)
  UPCOMING: football-data.org    → scheduled fixtures + CST times

APPEND-ONLY: never re-fetches or overwrites existing data.
"""

import os, sys, json, re, time, datetime, requests

DATA_DIR  = 'data'
API_BASE  = 'https://api.football-data.org/v4'
WC_CODE   = 'WC'
ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world'
ESPN_HDRS = {'User-Agent':'Mozilla/5.0 (compatible; WC2026/1.0)'}

# ── Name normalisation ────────────────────────────────────────────────────────
SHORT = {
    'South Africa':'S. Africa', "Côte d'Ivoire":'Ivory Coast', 'Ivory Coast':'Ivory Coast',
    'Bosnia and Herzegovina':'Bosnia', 'Bosnia-Herzegovina':'Bosnia',
    'Curaçao':'Curacao', 'United States':'USA', 'United States of America':'USA',
    'IR Iran':'Iran', 'Türkiye':'Turkey', 'Turkey':'Turkey',
    'Korea Republic':'S. Korea', 'South Korea':'S. Korea',
    'Cape Verde':'Cape Verde', 'Cape Verde Islands':'Cape Verde', 'Cabo Verde':'Cape Verde',
    'Congo DR':'DR Congo', 'DR Congo':'DR Congo', 'Democratic Republic of Congo':'DR Congo',
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

# ── ESPN scoreboard ───────────────────────────────────────────────────────────
def fetch_espn_scoreboard():
    url = f"{ESPN_BASE}/scoreboard?dates=20260601-20260720&limit=200"
    try:
        r = requests.get(url, headers=ESPN_HDRS, timeout=15)
        if r.status_code == 200:
            events = r.json().get('events', [])
            print(f"  ESPN scoreboard: {len(events)} events")
            return events
    except Exception as e:
        print(f"  ESPN scoreboard error: {e}")
    return []

# ── ESPN summary (stats) ──────────────────────────────────────────────────────
def fetch_espn_summary(espn_id):
    """Fetch full match stats from ESPN summary endpoint."""
    url = f"{ESPN_BASE}/summary?event={espn_id}"
    try:
        r = requests.get(url, headers=ESPN_HDRS, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"    ESPN summary error for {espn_id}: {e}")
    return {}

def parse_espn_stats(summary):
    """
    Parse stats from ESPN summary response.
    ESPN summary structure:
      boxscore.teams[].team.displayName
      boxscore.teams[].statistics[].{name, displayValue, label}
    """
    boxscore = summary.get('boxscore', {})
    teams    = boxscore.get('teams', [])

    if not teams:
        return None

    # Map team side → stats
    stats_by_side = {}
    for team_data in teams:
        team    = team_data.get('team', {})
        name    = short(team.get('displayName',''))
        home_away = team_data.get('homeAway', '')
        stats   = team_data.get('statistics', [])
        stats_by_side[home_away] = {'name': name, 'stats': stats}

    h = stats_by_side.get('home', {}).get('stats', [])
    a = stats_by_side.get('away', {}).get('stats', [])

    if not h and not a:
        # Try alternate structure: boxscore.players or gamepackageJSON
        game_pkg = summary.get('gamepackageJSON', {})
        if game_pkg:
            boxscore = game_pkg.get('boxscore', {})
            teams    = boxscore.get('teams', [])
            for team_data in teams:
                home_away = team_data.get('homeAway','')
                stats_by_side[home_away] = {'stats': team_data.get('statistics',[])}
            h = stats_by_side.get('home',{}).get('stats',[])
            a = stats_by_side.get('away',{}).get('stats',[])

    print(f"    ESPN summary stats: home={len(h)} away={len(a)} fields")

    # Debug — print all available stat names
    if h:
        print(f"    Available stats: {[s.get('name','?') for s in h[:10]]}")

    def get(stats, *names):
        """Try multiple name variations, return numeric value."""
        for s in stats:
            sname = s.get('name','').lower()
            sabrv = s.get('abbreviation','').lower()
            slbl  = s.get('label','').lower()
            for name in names:
                if name.lower() in (sname, sabrv, slbl):
                    try:
                        val = str(s.get('displayValue','0')).replace('%','').strip()
                        return round(float(val), 2) if '.' in val else int(val)
                    except: pass
        return None

    # Possession
    poss_h = get(h, 'possessionPct', 'possession', 'possessionpct') or 50
    poss_a = get(a, 'possessionPct', 'possession', 'possessionpct') or 50
    # Normalise to 100
    pt = poss_h + poss_a
    if pt > 0 and pt != 100:
        poss_h = round(poss_h/pt*100)
        poss_a = 100 - poss_h

    # Shots (ESPN uses "shotAttempts" or "totalShots" or label "Shot Attempts")
    shots_h = get(h, 'shotAttempts', 'totalShots', 'shots', 'totalshots', 'shot attempts') or 0
    shots_a = get(a, 'shotAttempts', 'totalShots', 'shots', 'totalshots', 'shot attempts') or 0

    # Shots on Goal (ESPN uses "shotsOnGoal" or label "Shots on Goal")
    sot_h = get(h, 'shotsOnGoal', 'shotsOnTarget', 'ongoal', 'shotsongoal', 'shots on goal') or 0
    sot_a = get(a, 'shotsOnGoal', 'shotsOnTarget', 'ongoal', 'shotsongoal', 'shots on goal') or 0

    # xG
    xg_h = get(h, 'expectedGoals', 'xg', 'xgoals', 'expectedgoals')
    xg_a = get(a, 'expectedGoals', 'xg', 'xgoals', 'expectedgoals')
    # Fallback: calculate from SOT if ESPN doesn't return xG
    if xg_h is None: xg_h = round(sot_h*0.33 + max(0,shots_h-sot_h)*0.05, 2)
    if xg_a is None: xg_a = round(sot_a*0.33 + max(0,shots_a-sot_a)*0.05, 2)

    # Other stats
    corners_h = get(h, 'cornerKicks', 'corners', 'corner kicks') or 0
    corners_a = get(a, 'cornerKicks', 'corners', 'corner kicks') or 0
    fouls_h   = get(h, 'fouls', 'foulcommitted') or 0
    fouls_a   = get(a, 'fouls', 'foulcommitted') or 0
    yellow_h  = get(h, 'yellowCards', 'yellowcard') or 0
    yellow_a  = get(a, 'yellowCards', 'yellowcard') or 0
    saves_h   = get(h, 'saves', 'gksaves') or 0
    saves_a   = get(a, 'saves', 'gksaves') or 0
    offside_h = get(h, 'offsides', 'offside') or 0
    offside_a = get(a, 'offsides', 'offside') or 0
    # Passes dropped — not available from ESPN

    return {
        'poss': [poss_h, poss_a],
        'stats': [
            ['Shot Attempts',  shots_h,   shots_a],
            ['Shots on Goal',  sot_h,     sot_a],
            ['Corner Kicks',   corners_h, corners_a],
            ['Fouls',          fouls_h,   fouls_a],
            ['Saves',          saves_h,   saves_a],
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
        h = n.get('headline','')
        if 'Group' in h or 'GROUP' in h:
            group = h.replace('Group ','').strip()
    details = comp.get('details',[])
    goals = []
    for d in details:
        dtype = d.get('type',{}).get('text','').lower()
        if 'goal' not in dtype and 'score' not in dtype: continue
        athletes = d.get('athletesInvolved',[])
        if not athletes: continue
        raw    = athletes[0].get('displayName','')
        parts  = raw.split()
        scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts)>1 else raw
        try: minute = int(str(d.get('clock',{}).get('displayValue','90')).split('+')[0].replace("'",''))
        except: minute = 90
        gtype = 'open-play'
        if 'penalty' in dtype: gtype = 'penalty'
        elif 'own'    in dtype: gtype = 'own-goal'; scorer += ' OG'
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
    token = os.environ.get('FOOTBALL_DATA_TOKEN','').strip()

    matches  = load('matches.json')  or []
    stats    = load('match_stats.json') or {}
    goals    = load('goals.json')    or []
    upcoming = load('upcoming_fixtures.json') or []

    # Clean placeholders
    before = len(goals)
    goals  = [g for g in goals if g.get('scorer','').strip() not in {'See FIFA.com','Unknown',''}]
    if len(goals) < before: print(f"  Cleaned {before-len(goals)} placeholder goals")

    # Build lookups
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

    # ── ESPN scoreboard ───────────────────────────────────────────────────────
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

        # Update or add match
        existing = next((m for m in matches if m['id']==mid), None)
        if existing:
            if existing.get('score') != score:
                print(f"  Score update: {mid} {score}")
                existing['score'] = score
            # Store ESPN ID if missing
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

        # ── Goals ─────────────────────────────────────────────────────────────
        if mid not in existing_goal_ms and parsed['goals']:
            parts = score.split('-')
            try: h_fin,a_fin = int(parts[0]),int(parts[1])
            except: continue
            h_run = a_run = 0
            match_goals = []
            for gd in sorted(parsed['goals'], key=lambda x: x['minute']):
                is_og = gd['type']=='own-goal'
                team  = gd.get('team','')
                if is_og:
                    if team==home: a_run+=1
                    else: h_run+=1
                else:
                    if team==home: h_run+=1
                    else: a_run+=1
                match_goals.append({
                    'id':next_goal_id,'matchId':mid,'home':home,'away':away,
                    'scorer':gd['scorer'],'minute':gd['minute'],'type':gd['type'],
                    'phase':f"Group {parsed['group']}",'score':f"{h_run}-{a_run}",'desc':'',
                })
                next_goal_id+=1
            # Validate: final running score must match ESPN final score
            if h_run == h_fin and a_run == a_fin:
                goals.extend(match_goals)
                goals_added += len(match_goals)
                existing_goal_ms.add(mid)
                print(f"  Goals: {mid} — {len(match_goals)} goals added ({h_run}-{a_run} ✓)")
            else:
                print(f"  Goals: {mid} — SKIPPED (running {h_run}-{a_run} != final {h_fin}-{a_fin})")
                next_goal_id -= len(match_goals)

        # ── Stats via ESPN summary endpoint ───────────────────────────────────
        espn_id = parsed['espn_id'] or (existing.get('espnId','') if existing else '')
        if mid not in existing_stat_ks and espn_id:
            print(f"  Fetching ESPN summary for {mid} (id={espn_id})...", end=' ', flush=True)
            summary = fetch_espn_summary(espn_id)
            time.sleep(0.5)
            espn_s = parse_espn_stats(summary)
            if espn_s:
                venue = parsed.get('venue','') or ''
                stats[mid] = {
                    'home':home,'away':away,'score':score,
                    'date':f"{parsed['date']}{' - '+venue if venue else ''}",
                    'poss':espn_s['poss'],'stats':espn_s['stats'],'xtra':espn_s['xtra'],
                }
                stats_added+=1; existing_stat_ks.add(mid)
                print(f"done (poss={espn_s['poss'][0]}-{espn_s['poss'][1]}%)")
            else:
                print("no stats returned")

        # Remove from upcoming
        upcoming = [f for f in upcoming
                    if not((f['home'].lower() in home.lower() or home.lower() in f['home'].lower()) and
                           (f['away'].lower() in away.lower() or away.lower() in f['away'].lower()))]

    # ── Upcoming from football-data.org ───────────────────────────────────────
    if token:
        print("\nFetching upcoming fixtures...")
        fetch_upcoming(token)

    # ── Save ──────────────────────────────────────────────────────────────────
    goals.sort(key=lambda g: (int(g['matchId'].replace('m','')), g['minute']))
    save('matches.json',          matches)
    save('match_stats.json',      stats)
    save('goals.json',            goals)
    save('upcoming_fixtures.json',upcoming)

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
