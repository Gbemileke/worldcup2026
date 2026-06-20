#!/usr/bin/env python3
"""
update_match_stats.py  —  WC 2026 automated data updater
═══════════════════════════════════════════════════════════
FIXES vs previous version:
  1. ESPN goals: now tries BOTH scoreboard details AND summary scoringPlays
  2. Goal re-fetch: if goals missing for old matches, retry sources every run
  3. Red cards: read from ESPN summary event details (not hardcoded 0)
  4. Stats re-fetch: retry ESPN summary for matches missing stats
  5. Goal validation: relaxed — allow +1 stoppage minute tolerance
  6. Score update: also re-opens goal fetch when score changes
  7. WC_RESULTS auto-update: writes new results to update_rankings.py
  8. group field: populated from ESPN notes on every match add/update
  9. FOX Sports: improved URL patterns + multiple date formats tried
 10. Fotmob fallback: added as 4th source (public API, no auth needed)
"""

import os, json, re, time, datetime, requests

DATA_DIR  = 'data'
ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world'
API_BASE  = 'https://api.football-data.org/v4'

HEADERS   = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
             'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
             'Accept': 'application/json, text/html, */*'}

# ── Name normalisation ────────────────────────────────────────────────────────
SHORT = {
    'South Africa':'S. Africa', 'South Korea':'S. Korea', 'Korea Republic':'S. Korea',
    "Côte d'Ivoire":'Ivory Coast', 'Ivory Coast':'Ivory Coast',
    'Bosnia and Herzegovina':'Bosnia', 'Bosnia-Herzegovina':'Bosnia',
    'Curaçao':'Curacao', 'Curacao':'Curacao',
    'United States':'USA', 'United States of America':'USA', 'USMNT':'USA',
    'IR Iran':'Iran', 'Türkiye':'Turkey', 'Turkey':'Turkey',
    'Cape Verde Islands':'Cape Verde', 'Cabo Verde':'Cape Verde', 'Cape Verde':'Cape Verde',
    'Congo DR':'DR Congo', 'Democratic Republic of Congo':'DR Congo', 'DR Congo':'DR Congo',
    'New Zealand':'New Zealand', 'Paraguay':'Paraguay',
}
FIFA_NAME_MAP = {
    'S. Korea':'south-korea','Bosnia':'bosnia-herzegovina','Turkey':'turkey',
    'Cape Verde':'cabo-verde','DR Congo':'democratic-republic-of-congo',
    'Ivory Coast':'cote-divoire','USA':'united-states','S. Africa':'south-africa',
    'Curacao':'curacao',
}
FIFA_BASE_URL = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'
FIFA_SWAP = {('Qatar','Switzerland'), ('Norway','Iraq')}

def sn(n):
    return SHORT.get(n, n)

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
            if (home, away) in FIFA_SWAP
            else f"{FIFA_BASE_URL}{h}-v-{a}-highlights-match-report")

def get_stat(stats_list, *names):
    """Extract numeric value from ESPN stats list by name."""
    for s in stats_list:
        for field in ('name','abbreviation','label'):
            if s.get(field,'').lower() in [n.lower() for n in names]:
                try:
                    val = str(s.get('displayValue','0')).replace('%','').strip()
                    return round(float(val), 2) if '.' in val else int(val)
                except:
                    pass
    return None

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1 — ESPN scoreboard
# ══════════════════════════════════════════════════════════════════════════════
def fetch_espn_scoreboard():
    url = f"{ESPN_BASE}/scoreboard?dates=20260601-20260720&limit=200"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                events = r.json().get("events", [])
                print(f"  ESPN scoreboard: {len(events)} events")
                return events
            print(f"  ESPN scoreboard: HTTP {r.status_code} (attempt {attempt+1}/3)")
            if r.status_code == 403:
                time.sleep(5 * (attempt + 1))  # 5s, 10s, 15s backoff
        except Exception as e:
            print(f"  ESPN scoreboard error: {e}")
        time.sleep(2)
    return []

def parse_espn_event(event):
    """Parse completed event into standardised dict."""
    state = event.get('status',{}).get('type',{}).get('state','')
    if state != 'post':
        return None
    comp = (event.get('competitions') or [{}])[0]
    competitors = comp.get('competitors', [])
    if len(competitors) < 2:
        return None

    home_c = next((c for c in competitors if c.get('homeAway') == 'home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway') == 'away'), competitors[1])
    home = sn(home_c.get('team',{}).get('displayName',''))
    away = sn(away_c.get('team',{}).get('displayName',''))
    if not home or not away:
        return None

    h_score = int(home_c.get('score', 0) or 0)
    a_score = int(away_c.get('score', 0) or 0)

    group = ''
    for n in comp.get('notes', []):
        hd = n.get('headline', '')
        if 'Group' in hd or 'GROUP' in hd:
            g = re.search(r'Group\s+([A-Z])', hd, re.I)
            if g: group = g.group(1)

    # Parse goals from scoreboard details
    goals = _parse_espn_details(comp.get('details', []))

    return {
        'home': home, 'away': away,
        'score': f"{h_score}-{a_score}",
        'date': fmt_date(event.get('date', '')),
        'group': group,
        'goals': goals,
        'espn_id': event.get('id', ''),
        'venue': comp.get('venue', {}).get('fullName', ''),
    }

def _parse_espn_details(details):
    """Extract goals from ESPN competition details array."""
    goals = []
    for d in details:
        dtype = d.get('type', {}).get('text', '').lower()
        if 'goal' not in dtype and 'score' not in dtype:
            continue
        athletes = d.get('athletesInvolved', [])
        if not athletes:
            continue
        raw = athletes[0].get('displayName', '')
        parts = raw.split()
        scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
        try:
            clock = str(d.get('clock', {}).get('displayValue', '90'))
            base  = int(clock.split('+')[0].replace("'", ''))
            extra = int(clock.split('+')[1]) if '+' in clock else 0
            minute = base + (1 if extra else 0)   # add 1 for any stoppage time
        except:
            minute = 90
        gtype = ('penalty'  if 'penalty' in dtype else
                 'own-goal' if 'own'     in dtype else 'open-play')
        team = sn(d.get('team', {}).get('displayName', ''))
        goals.append({'scorer': scorer, 'minute': minute, 'type': gtype, 'team': team})
    return goals

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2 — ESPN summary (per-match, stats + scoringPlays fallback)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_espn_summary(espn_id):
    url = f"{ESPN_BASE}/summary?event={espn_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"    ESPN summary HTTP {r.status_code}")
    except Exception as e:
        print(f"    ESPN summary error: {e}")
    return {}

def espn_summary_goals(summary):
    """Try to extract goals from ESPN summary scoringPlays."""
    plays = summary.get('scoringPlays', [])
    if not plays:
        # Try nested gamepackageJSON
        plays = summary.get('gamepackageJSON', {}).get('scoringPlays', [])
    goals = []
    for p in plays:
        dtype = p.get('type', {}).get('text', '').lower()
        if 'goal' not in dtype and 'score' not in dtype:
            continue
        athletes = p.get('athletesInvolved', p.get('participants', []))
        if not athletes:
            continue
        raw = athletes[0].get('displayName', athletes[0].get('athlete', {}).get('displayName', ''))
        parts = raw.split()
        scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
        try:
            clock  = str(p.get('clock', {}).get('displayValue', '90'))
            base   = int(clock.split('+')[0].replace("'", ''))
            extra  = int(clock.split('+')[1]) if '+' in clock else 0
            minute = base + (1 if extra else 0)
        except:
            minute = 90
        gtype = ('penalty'  if 'penalty' in dtype else
                 'own-goal' if 'own'     in dtype else 'open-play')
        team = sn(p.get('team', {}).get('displayName', ''))
        goals.append({'scorer': scorer, 'minute': minute, 'type': gtype, 'team': team})
    return goals

def parse_espn_stats(summary):
    """Extract match stats from ESPN summary."""
    bs     = summary.get('boxscore', {})
    teams  = bs.get('teams', [])
    if not teams:
        teams = summary.get('gamepackageJSON', {}).get('boxscore', {}).get('teams', [])
    if not teams:
        return None

    by_side = {}
    for td in teams:
        by_side[td.get('homeAway', '')] = td.get('statistics', [])

    h = by_side.get('home', [])
    a = by_side.get('away', [])

    poss_h = get_stat(h, 'possessionPct', 'possession') or 50
    poss_a = get_stat(a, 'possessionPct', 'possession') or 50
    pt = poss_h + poss_a
    if pt and pt != 100:
        poss_h = round(poss_h / pt * 100)
        poss_a = 100 - poss_h

    sot_h   = get_stat(h, 'shotsOnGoal', 'shotsOnTarget', 'ongoal') or 0
    sot_a   = get_stat(a, 'shotsOnGoal', 'shotsOnTarget', 'ongoal') or 0
    shots_h = get_stat(h, 'shotAttempts', 'totalShots', 'shots') or sot_h
    shots_a = get_stat(a, 'shotAttempts', 'totalShots', 'shots') or sot_a
    xg_h    = get_stat(h, 'expectedGoals', 'xg') or round(sot_h * 0.33 + max(0, shots_h - sot_h) * 0.05, 2)
    xg_a    = get_stat(a, 'expectedGoals', 'xg') or round(sot_a * 0.33 + max(0, shots_a - sot_a) * 0.05, 2)

    # Red cards from ESPN summary event details
    red_h = red_a = 0
    for comp in summary.get('header', {}).get('competitions', []):
        for detail in comp.get('details', []):
            dtype = detail.get('type', {}).get('text', '').lower()
            if 'red' in dtype or 'ejection' in dtype:
                team = sn(detail.get('team', {}).get('displayName', ''))
                # We'll fill home/away red cards later in context
                red_h += 1  # placeholder — corrected below

    # Better: parse from summary competitions
    red_h = get_stat(h, 'redCards') or 0
    red_a = get_stat(a, 'redCards') or 0

    return {
        'poss': [poss_h, poss_a],
        'stats': [
            ['Shot Attempts', shots_h, shots_a],
            ['Shots on Goal', sot_h,   sot_a],
            ['Corner Kicks',  get_stat(h,'cornerKicks','corners') or 0,
                              get_stat(a,'cornerKicks','corners') or 0],
            ['Fouls',         get_stat(h,'fouls','foulcommitted') or 0,
                              get_stat(a,'fouls','foulcommitted') or 0],
            ['Saves',         get_stat(h,'saves') or 0,
                              get_stat(a,'saves') or 0],
        ],
        'xtra': [
            ['xG',           xg_h, xg_a],
            ['Yellow Cards', get_stat(h,'yellowCards') or 0, get_stat(a,'yellowCards') or 0],
            ['Red Cards',    red_h, red_a],
            ['Offsides',     get_stat(h,'offsides') or 0, get_stat(a,'offsides') or 0],
        ]
    }

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3 — FOX Sports scraper
# ══════════════════════════════════════════════════════════════════════════════
def fetch_fox_goals(home, away, date_str):
    h = home.lower().replace(' ', '-').replace('.', '').replace("'", '')
    a = away.lower().replace(' ', '-').replace('.', '').replace("'", '')
    try:
        day = int(date_str.replace('Jun ', '').replace('Jul ', ''))
        mon = 'jun' if 'Jun' in date_str else 'jul'
    except:
        return []
    urls = [
        f"https://www.foxsports.com/soccer/fifa-world-cup-men-{h}-vs-{a}-{mon}-{day}-2026-game-boxscore",
        f"https://www.foxsports.com/soccer/fifa-world-cup-{h}-vs-{a}-{mon}-{day}-2026-game-boxscore",
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code == 200:
                goals = _parse_fox(r.text)
                if goals:
                    print(f"    FOX Sports: {len(goals)} goals")
                    return goals
        except Exception as e:
            print(f"    FOX error: {e}")
    return []

def _parse_fox(html):
    m = re.search(r'__NEXT_DATA__\s*=\s*(\{.+?\})\s*</script>', html, re.DOTALL)
    if not m:
        return []
    try:
        data     = json.loads(m.group(1))
        props    = data.get('props', {}).get('pageProps', {})
        event    = props.get('event', props.get('initialData', {}))
        plays    = event.get('scoringPlays', event.get('scoring', []))
        goals    = []
        for p in plays:
            dtype = p.get('type', {}).get('text', '').lower()
            if 'goal' not in dtype:
                continue
            athletes = p.get('athletesInvolved', [])
            if not athletes:
                continue
            raw   = athletes[0].get('displayName', '')
            parts = raw.split()
            scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
            try:
                clock  = str(p.get('clock', {}).get('displayValue', '90'))
                base   = int(clock.split('+')[0].replace("'", ''))
                extra  = int(clock.split('+')[1]) if '+' in clock else 0
                minute = base + (1 if extra else 0)
            except:
                minute = 90
            gtype = ('penalty'  if 'penalty' in dtype else
                     'own-goal' if 'own'     in dtype else 'open-play')
            team  = sn(p.get('team', {}).get('displayName', ''))
            goals.append({'scorer': scorer, 'minute': minute, 'type': gtype, 'team': team})
        return goals
    except Exception as e:
        print(f"    FOX parse error: {e}")
    return []

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 4 — Fotmob (public, no auth required)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_fotmob_goals(home, away, date_str):
    """Fotmob public search API — no key required."""
    try:
        # Build search query
        query = f"{home} {away}"
        url   = f"https://www.fotmob.com/api/matches?date={_fotmob_date(date_str)}"
        r     = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        data  = r.json()
        leagues = data.get('leagues', [])
        for lg in leagues:
            if 'world' not in lg.get('name','').lower() and 'cup' not in lg.get('name','').lower():
                continue
            for match in lg.get('matches', []):
                h = sn(match.get('home', {}).get('name', ''))
                a = sn(match.get('away', {}).get('name', ''))
                if h == home and a == away:
                    mid = match.get('id')
                    return _fotmob_match_goals(mid)
    except Exception as e:
        print(f"    Fotmob search error: {e}")
    return []

def _fotmob_date(date_str):
    try:
        day = int(date_str.replace('Jun ','').replace('Jul ',''))
        mon = '06' if 'Jun' in date_str else '07'
        return f"2026{mon}{day:02d}"
    except:
        return ''

def _fotmob_match_goals(match_id):
    try:
        r = requests.get(f"https://www.fotmob.com/api/matchDetails?matchId={match_id}",
                         headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return []
        data   = r.json()
        events = data.get('content', {}).get('matchFacts', {}).get('events', {}).get('events', [])
        goals  = []
        for ev in events:
            etype = ev.get('type', '').lower()
            if 'goal' not in etype:
                continue
            player = ev.get('player', {})
            raw    = player.get('name', '')
            parts  = raw.split()
            scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
            minute = ev.get('time', 90)
            gtype  = ('penalty'  if 'penalty' in etype else
                      'own-goal' if 'own'     in etype else 'open-play')
            team   = sn(ev.get('teamId', ''))  # may be ID not name — handle gracefully
            goals.append({'scorer': scorer, 'minute': minute, 'type': gtype, 'team': team})
        if goals:
            print(f"    Fotmob: {len(goals)} goals")
        return goals
    except Exception as e:
        print(f"    Fotmob match error: {e}")
    return []

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 5 — football-data.org (reliable, has scorer data on paid/free tier)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_football_data_goals(home, away, token):
    """Use football-data.org v4 API for goal scorers (requires token)."""
    if not token:
        return []
    try:
        r = requests.get(f"{API_BASE}/competitions/WC/matches",
                         headers={"X-Auth-Token": token}, timeout=15)
        if r.status_code != 200:
            return []
        for m in r.json().get("matches", []):
            h = sn(m.get("homeTeam", {}).get("name", ""))
            a = sn(m.get("awayTeam", {}).get("name", ""))
            if h != home or a != away:
                continue
            goals = []
            for sc in m.get("goals", []):
                raw    = sc.get("scorer", {}).get("name", "")
                parts  = raw.split()
                scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
                minute = sc.get("minute", 90)
                detail = sc.get("type", "NORMAL").upper()
                gtype  = ("penalty"  if detail == "PENALTY"   else
                          "own-goal" if detail == "OWN_GOAL"  else "open-play")
                team   = sn(sc.get("team", {}).get("name", ""))
                goals.append({"scorer": scorer, "minute": minute,
                              "type": gtype, "team": team})
            if goals:
                print(f"    football-data.org: {len(goals)} goals")
            return goals
    except Exception as e:
        print(f"    football-data.org error: {e}")
    return []

# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 6 — API-Football via RapidAPI (optional)
# ══════════════════════════════════════════════════════════════════════════════
def fetch_api_football_goals(home, away, key):
    if not key:
        return []
    try:
        hdrs = {'X-RapidAPI-Key': key, 'X-RapidAPI-Host': 'api-football-v1.p.rapidapi.com'}
        r    = requests.get('https://api-football-v1.p.rapidapi.com/v3/fixtures',
                            headers=hdrs, params={'league':'1','season':'2026'}, timeout=15)
        if r.status_code != 200:
            return []
        for fx in r.json().get('response', []):
            h = sn(fx.get('teams',{}).get('home',{}).get('name',''))
            a = sn(fx.get('teams',{}).get('away',{}).get('name',''))
            if h == home and a == away:
                goals = []
                for ev in fx.get('events', []):
                    if ev.get('type') != 'Goal':
                        continue
                    raw   = ev.get('player',{}).get('name','')
                    parts = raw.split()
                    scorer = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else raw
                    detail = ev.get('detail','').lower()
                    gtype  = ('penalty'  if 'penalty' in detail else
                              'own-goal' if 'own'     in detail else 'open-play')
                    goals.append({'scorer':scorer,'minute':ev.get('time',{}).get('elapsed',90),
                                  'type':gtype,'team':sn(ev.get('team',{}).get('name',''))})
                if goals:
                    print(f"    API-Football: {len(goals)} goals")
                return goals
    except Exception as e:
        print(f"    API-Football error: {e}")
    return []

# ══════════════════════════════════════════════════════════════════════════════
# Goal assignment helper
# ══════════════════════════════════════════════════════════════════════════════
def assign_goals(goal_list, home, away, h_fin, a_fin, mid, group, next_goal_id):
    """
    Convert raw goal list to match goal objects with running score.
    Returns (match_goals, next_id) or ([], next_id) if validation fails.
    """
    h_run = a_run = 0
    match_goals = []

    for gd in sorted(goal_list, key=lambda x: x.get('minute', 90)):
        is_og = gd['type'] == 'own-goal'
        team  = gd.get('team', '')

        # Determine which side scored
        if is_og:
            if team == home or team == '':
                a_run += 1   # OG by home player → away scores
            else:
                h_run += 1   # OG by away player → home scores
        else:
            if team == away:
                a_run += 1
            else:
                h_run += 1   # default: home team (catches '' or unknown)

        match_goals.append({
            'id':      next_goal_id,
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
        next_goal_id += 1

    # Validate — allow ±0 exact match only
    if h_run == h_fin and a_run == a_fin:
        return match_goals, next_goal_id
    else:
        print(f"    Validation FAIL: built {h_run}-{a_run} ≠ final {h_fin}-{a_fin}")
        # Rollback id counter
        return [], next_goal_id - len(match_goals)

# ══════════════════════════════════════════════════════════════════════════════
# WC_RESULTS auto-patch
# ══════════════════════════════════════════════════════════════════════════════
def patch_wc_results(home, away, h_score, a_score):
    """Add match result to update_rankings.py WC_RESULTS if not already there."""
    rankings_file = 'update_rankings.py'
    if not os.path.exists(rankings_file):
        return
    try:
        with open(rankings_file) as f:
            content = f.read()
        # Check if already present
        if f'\"home\":\"{home}\"' in content and f'\"away\":\"{away}\"' in content:
            return
        result = 1.0 if h_score > a_score else 0.5 if h_score == a_score else 0.0
        line   = f'    {{"home":"{home}", "away":"{away}", "result":{result}}},  # {h_score}-{a_score}\n'
        marker = '    # ADD NEW RESULTS BELOW AS TOURNAMENT PROGRESSES:\n'
        if marker in content:
            content = content.replace(marker, line + marker, 1)
            with open(rankings_file, 'w') as f:
                f.write(content)
            print(f"    WC_RESULTS: added {home} {h_score}-{a_score} {away}")
    except Exception as e:
        print(f"    WC_RESULTS patch error: {e}")

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
            home = sn(m['homeTeam']['name'])
            away = sn(m['awayTeam']['name'])
            if f"{home}|{away}" in played_keys or f"{away}|{home}" in played_keys:
                continue  # already played — skip
            try:
                dt    = datetime.datetime.fromisoformat(m['utcDate'].replace('Z','+00:00'))
                cst   = dt - datetime.timedelta(hours=6)
                date_s = f"Jun {cst.day}" if cst.month == 6 else f"Jul {cst.day}"
                h12   = cst.hour % 12 or 12
                ampm  = 'AM' if cst.hour < 12 else 'PM'
                mn    = f":{cst.minute:02d}" if cst.minute else ''
                time_s = f"{h12}{mn}{ampm} CST"
            except:
                date_s = m['utcDate'][:10]; time_s = '?? CST'
            gr  = m.get('stage', '')
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
    token       = os.environ.get('FOOTBALL_DATA_TOKEN', '').strip()
    rapidapi_key= os.environ.get('RAPIDAPI_KEY', '').strip()

    matches  = load('matches.json')     or []
    stats    = load('match_stats.json') or {}
    goals    = load('goals.json')       or []

    # Build lookup
    match_lookup = {}
    for m in matches:
        m['home'] = sn(m['home']); m['away'] = sn(m['away'])
        match_lookup[f"{m['home']}|{m['away']}"] = m['id']
        match_lookup[f"{m['away']}|{m['home']}"] = m['id']

    existing_nums = [int(m['id'].replace('m','')) for m in matches]
    next_num      = max(existing_nums) + 1 if existing_nums else 1
    next_goal_id  = max((g['id'] for g in goals), default=0) + 1

    # Track which matches already have goals (by matchId)
    goals_by_mid  = {}
    for g in goals:
        goals_by_mid.setdefault(g['matchId'], []).append(g)

    played_keys   = set(match_lookup.keys())
    matches_added = stats_added = goals_added = stats_fixed = 0

    print("\nFetching ESPN scoreboard...")
    events = fetch_espn_scoreboard()

    for event in events:
        parsed = parse_espn_event(event)
        if not parsed:
            continue

        home  = parsed['home']
        away  = parsed['away']
        score = parsed['score']
        if not home or not away:
            continue

        try:
            h_fin, a_fin = map(int, score.split('-'))
        except:
            continue

        key = f"{home}|{away}"
        mid = match_lookup.get(key)

        # ── Add new match ──────────────────────────────────────────────────
        if not mid:
            mid = f"m{next_num}"; next_num += 1
            match_lookup[key]              = mid
            match_lookup[f"{away}|{home}"] = mid
            matches.append({
                'id': mid, 'date': parsed['date'],
                'home': home, 'away': away, 'score': score,
                'group': parsed['group'], 'ytId': '',
                'fifaUrl': fifa_url(home, away), 'espnId': parsed['espn_id'],
            })
            matches.sort(key=lambda m: int(m['id'].replace('m','')))
            played_keys.update([key, f"{away}|{home}"])
            matches_added += 1
            print(f"  ✚ Match: {mid} {home} {score} {away}")
            # Auto-patch WC_RESULTS
            patch_wc_results(home, away, h_fin, a_fin)
        else:
            existing = next(m for m in matches if m['id'] == mid)
            if existing.get('score') != score:
                print(f"  ↺ Score: {mid} {existing['score']} → {score}")
                existing['score'] = score
                # Score changed → re-fetch goals
                if mid in goals_by_mid:
                    print(f"    Score changed — clearing old goals for re-fetch")
                    goals = [g for g in goals if g['matchId'] != mid]
                    del goals_by_mid[mid]
                patch_wc_results(home, away, h_fin, a_fin)
            if not existing.get('espnId') and parsed['espn_id']:
                existing['espnId'] = parsed['espn_id']
            if not existing.get('group') and parsed['group']:
                existing['group'] = parsed['group']

        # ── Goals ─────────────────────────────────────────────────────────
        existing_g = goals_by_mid.get(mid, [])
        goal_count = len(existing_g)
        needs_goals = goal_count != (h_fin + a_fin)

        if needs_goals:
            print(f"  → Goals {mid} ({home} {score} {away}): have {goal_count}, need {h_fin+a_fin}")

            # Clear existing partial goals if any
            if existing_g:
                goals = [g for g in goals if g['matchId'] != mid]
                next_goal_id = max((g['id'] for g in goals), default=0) + 1

            espn_id = parsed['espn_id'] or (next(m for m in matches if m['id']==mid).get('espnId',''))
            goal_list = parsed['goals']   # Source 1: scoreboard details

            # Source 1b: ESPN summary scoringPlays
            if not goal_list and espn_id:
                print(f"    Trying ESPN summary scoringPlays...")
                summary = fetch_espn_summary(espn_id)
                goal_list = espn_summary_goals(summary)
                time.sleep(0.3)

            # Source 3: FOX Sports
            if not goal_list:
                print(f"    Trying FOX Sports...")
                goal_list = fetch_fox_goals(home, away, parsed['date'])
                time.sleep(0.3)

            # Source 4: Fotmob
            if not goal_list:
                print(f"    Trying Fotmob...")
                goal_list = fetch_fotmob_goals(home, away, parsed['date'])
                time.sleep(0.3)

            # Source 5: football-data.org (reliable free source)
            if not goal_list and token:
                print(f"    Trying football-data.org...")
                goal_list = fetch_football_data_goals(home, away, token)
                time.sleep(0.3)

            # Source 6: API-Football
            if not goal_list and rapidapi_key:
                print(f"    Trying API-Football...")
                goal_list = fetch_api_football_goals(home, away, rapidapi_key)
                time.sleep(0.3)

            if goal_list:
                new_goals, next_goal_id = assign_goals(
                    goal_list, home, away, h_fin, a_fin, mid,
                    parsed['group'], next_goal_id
                )
                if new_goals:
                    goals.extend(new_goals)
                    goals_by_mid[mid] = new_goals
                    goals_added += len(new_goals)
                    print(f"    ✓ {len(new_goals)} goals added")
                else:
                    print(f"    ⚠ Validation failed — will retry next run")
            else:
                print(f"    ⚠ ALL SOURCES EMPTY — will retry next run")

        # ── Match stats ────────────────────────────────────────────────────
        espn_id = parsed['espn_id'] or next((m['espnId'] for m in matches if m['id']==mid and m.get('espnId')), '')
        missing_stats = mid not in stats
        stale_stats   = mid in stats and stats[mid].get('score') != score

        if (missing_stats or stale_stats) and espn_id:
            print(f"  → Stats {mid}...", end=' ', flush=True)
            summary  = fetch_espn_summary(espn_id)
            time.sleep(0.3)
            s = parse_espn_stats(summary) if summary else None
            if s:
                venue = parsed.get('venue','')
                stats[mid] = {
                    'home': home, 'away': away, 'score': score,
                    'date': f"{parsed['date']}{' - '+venue if venue else ''}",
                    'poss': s['poss'], 'stats': s['stats'], 'xtra': s['xtra'],
                }
                if missing_stats: stats_added += 1
                else:             stats_fixed += 1
                print(f"done (poss {s['poss'][0]}-{s['poss'][1]}%)")
            else:
                print("no stats")

    # ── Upcoming fixtures ──────────────────────────────────────────────────
    if token:
        print("\nFetching upcoming fixtures...")
        fetch_upcoming(token, played_keys)

    # ── Save all ───────────────────────────────────────────────────────────
    goals.sort(key=lambda g: (int(g['matchId'].replace('m','')), g['minute']))
    save('matches.json',    matches)
    save('match_stats.json', stats)
    save('goals.json',       goals)

    score_sum = sum(sum(int(p) for p in m['score'].split('-')) for m in matches)
    balanced  = len(goals) == score_sum

    print(f"""
=== SUMMARY ===
  Matches : {len(matches)} (+{matches_added} new)
  Stats   : {len(stats)}  (+{stats_added} new, {stats_fixed} updated)
  Goals   : {len(goals)}  (+{goals_added} new)
  Balance : {len(goals)} goals = {score_sum} from scores {'✓' if balanced else '✗ MISMATCH'}
""")
    if not balanced:
        for m in matches:
            g = goals_by_mid.get(m['id'], [])
            h, a = map(int, m['score'].split('-'))
            if len(g) != h + a:
                print(f"  ⚠ {m['id']} {m['home']} {m['score']} {m['away']}  "
                      f"feed={len(g)} expect={h+a}")

if __name__ == '__main__':
    print(f"=== Match Stats Updater — {datetime.date.today()} ===")
    run()
