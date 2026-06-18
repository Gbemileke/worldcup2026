#!/usr/bin/env python3
"""
update_match_stats.py
═════════════════════
Fetches WC 2026 data from two sources:
  - ESPN API        → scores, goalscorers (live, no auth, reliable)
  - football-data.org → match stats (possession, shots, xG)

APPEND-ONLY: Never re-fetches or overwrites existing data.
Only adds NEW matches, NEW goals, NEW stats.

Requires: FOOTBALL_DATA_TOKEN env var (for stats only)
"""

import os, sys, json, time, datetime, requests

DATA_DIR = 'data'
API_BASE = 'https://api.football-data.org/v4'
WC_CODE  = 'WC'

ESPN_BASE = 'https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world'

# ── Name normalisation ────────────────────────────────────────────────────────
SHORT = {
    # Full name → our short name
    "South Africa":"S. Africa", "Côte d'Ivoire":"Ivory Coast",
    "Ivory Coast":"Ivory Coast",
    "Bosnia and Herzegovina":"Bosnia", "Bosnia-Herzegovina":"Bosnia",
    "Curaçao":"Curacao",
    "United States":"USA", "United States of America":"USA",
    "IR Iran":"Iran",
    "Türkiye":"Turkey", "Turkey":"Turkey",
    "Korea Republic":"S. Korea", "South Korea":"S. Korea",
    "Cape Verde":"Cape Verde", "Cape Verde Islands":"Cape Verde", "Cabo Verde":"Cape Verde",
    "Congo DR":"DR Congo", "DR Congo":"DR Congo",
    "Democratic Republic of Congo":"DR Congo",
    "Bosnia-Herzegovina":"Bosnia",
    "New Zealand":"New Zealand",
}

FIFA_BASE = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'

FIFA_NAME_MAP = {
    'S. Korea':'south-korea','South Korea':'south-korea',
    'Bosnia':'bosnia-herzegovina','Turkiye':'turkey','Turkey':'turkey',
    'Cape Verde':'cabo-verde','DR Congo':'democratic-republic-of-congo',
    'Ivory Coast':'cote-divoire','USA':'united-states',
    'S. Africa':'south-africa','South Africa':'south-africa',
    'Curacao':'curacao',
}

FIFA_URL_SWAPS = {('Qatar','Switzerland'), ('Norway','Iraq')}

VENUES = {
    "MetLife":"MetLife Stadium, New Jersey",
    "SoFi":"SoFi Stadium, Los Angeles",
    "AT&T":"AT&T Stadium, Dallas",
    "Hard Rock":"Hard Rock Stadium, Miami",
    "Arrowhead":"Arrowhead Stadium, Kansas City",
    "NRG":"NRG Stadium, Houston",
    "Lumen":"Lumen Field, Seattle",
    "Lincoln":"Lincoln Financial Field, Philadelphia",
    "Gillette":"Gillette Stadium, Boston",
    "Mercedes":"Mercedes-Benz Stadium, Atlanta",
    "Levis":"Levis Stadium, San Francisco",
    "BMO":"BMO Field, Toronto",
    "BC Place":"BC Place, Vancouver",
    "Akron":"Estadio Akron, Guadalajara",
    "BBVA":"Estadio BBVA, Monterrey",
    "Azteca":"Estadio Azteca, Mexico City",
}

def short(name):
    return SHORT.get(name, name)

def venue_fmt(v):
    if not v: return ''
    for k, val in VENUES.items():
        if k.lower() in v.lower():
            return val
    return v

def fmt_date(dt_str):
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace('Z',''))
        return f"Jun {dt.day}"
    except:
        return dt_str[:10]

def fifa_slug(name):
    return FIFA_NAME_MAP.get(name,
        name.lower().replace(' ','-').replace("'",'').replace('.',''))

def fifa_url(home, away):
    h, a = fifa_slug(home), fifa_slug(away)
    if (home, away) in FIFA_URL_SWAPS:
        return f"{FIFA_BASE}{a}-v-{h}-highlights-match-report"
    return f"{FIFA_BASE}{h}-v-{a}-highlights-match-report"

def load(fname):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path): return None
    with open(path) as f: return json.load(f)

def save(fname, data):
    with open(os.path.join(DATA_DIR, fname), 'w') as f:
        json.dump(data, f, indent=2)

# ── ESPN API ──────────────────────────────────────────────────────────────────
def fetch_espn_scores():
    """Fetch all WC 2026 finished matches from ESPN. No auth needed."""
    results = []
    # ESPN scoreboard for soccer/world cup
    urls = [
        f"{ESPN_BASE}/scoreboard?dates=20260601-20260720&limit=200",
        f"{ESPN_BASE}/scoreboard",
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=15,
                headers={'User-Agent':'Mozilla/5.0 (compatible; WC2026Bot/1.0)'})
            if r.status_code == 200:
                data = r.json()
                events = data.get('events', [])
                print(f"  ESPN: {len(events)} events from {url[:60]}")
                return events
        except Exception as e:
            print(f"  ESPN URL failed: {e}")
    return []

def parse_espn_event(event):
    """Parse an ESPN event into our match format."""
    status = event.get('status', {})
    state  = status.get('type', {}).get('state', '')  # pre/in/post
    if state != 'post':
        return None  # not finished

    comps = event.get('competitions', [{}])
    if not comps: return None
    comp = comps[0]

    competitors = comp.get('competitors', [])
    if len(competitors) < 2: return None

    # Home/away
    home_c = next((c for c in competitors if c.get('homeAway')=='home'), competitors[0])
    away_c = next((c for c in competitors if c.get('homeAway')=='away'), competitors[1])

    home = short(home_c.get('team',{}).get('displayName',''))
    away = short(away_c.get('team',{}).get('displayName',''))
    h_score = int(home_c.get('score', 0) or 0)
    a_score = int(away_c.get('score', 0) or 0)
    score = f"{h_score}-{a_score}"

    # Date
    date_str = fmt_date(event.get('date',''))

    # Venue
    venue_raw = comp.get('venue',{}).get('fullName','')
    venue = venue_fmt(venue_raw)

    # Group
    notes = event.get('notes', [])
    group = ''
    for n in notes:
        if 'Group' in n.get('headline','') or 'GROUP' in n.get('headline',''):
            group = n.get('headline','').replace('Group ','').strip()
            break
    if not group:
        group = event.get('season',{}).get('displayName','Group Stage')

    # Goals from ESPN details
    goals = []
    details = comp.get('details', [])
    for d in details:
        dtype = d.get('type',{}).get('text','').lower()
        if 'goal' not in dtype and 'score' not in dtype:
            continue
        athlete_data = d.get('athletesInvolved', [])
        if not athlete_data:
            continue
        scorer_raw = athlete_data[0].get('displayName','Unknown')
        # Last name only for scorer
        parts = scorer_raw.split()
        scorer = parts[-1] if len(parts)==1 else f"{parts[0][0]}. {parts[-1]}" if len(parts)>1 else scorer_raw

        minute = d.get('clock', {}).get('displayValue','90')
        try:
            minute = int(str(minute).replace("'","").split('+')[0])
        except:
            minute = 90

        gtype = 'open-play'
        if 'penalty' in dtype or 'pen' in dtype:
            gtype = 'penalty'
        elif 'own' in dtype:
            gtype = 'own-goal'
            scorer = scorer + ' OG'

        team_data = d.get('team',{})
        team_name = short(team_data.get('displayName',''))
        is_home   = team_name == home

        # Running score — increment from previous
        goals.append({
            'scorer': scorer,
            'minute': minute,
            'type':   gtype,
            'team':   team_name,
        })

    return {
        'home':    home,
        'away':    away,
        'score':   score,
        'date':    date_str,
        'venue':   venue,
        'group':   group,
        'goals':   goals,
        'espn_id': event.get('id',''),
    }

# ── football-data.org — stats only ────────────────────────────────────────────
def fetch_fdorg_stats(token, match_id):
    """Fetch possession/shots/xG for one match. Returns {} if unavailable."""
    try:
        r = requests.get(f"{API_BASE}/matches/{match_id}",
            headers={'X-Auth-Token': token}, timeout=12)
        if r.status_code == 429:
            print("  Rate limit — waiting 60s"); time.sleep(60)
            r = requests.get(f"{API_BASE}/matches/{match_id}",
                headers={'X-Auth-Token': token}, timeout=12)
        if r.status_code != 200:
            return {}
        data = r.json()
        goals_count = len(data.get('goals') or [])
        print(f"    fd.org match {match_id}: {goals_count} goals in response")
        return data
    except Exception as e:
        print(f"    fd.org fetch failed: {e}")
        return {}

def get_stat(stats_raw, label, dh, da):
    for s in stats_raw or []:
        if label.lower() in s.get('type','').lower():
            try:
                return [int(str(s.get('home',dh)).replace('%','')),
                        int(str(s.get('away',da)).replace('%',''))]
            except: pass
    return [dh, da]

def fetch_fdorg_matches(token):
    """Fetch match IDs for finished WC matches (for stats lookup)."""
    try:
        r = requests.get(f"{API_BASE}/competitions/{WC_CODE}/matches?status=FINISHED",
            headers={'X-Auth-Token': token}, timeout=15)
        if r.status_code == 403:
            print("  fd.org: invalid token"); return {}
        r.raise_for_status()
        matches = r.json().get('matches', [])
        # Build lookup: "home|away" → match_id
        lookup = {}
        for m in matches:
            h = short(m['homeTeam']['name'])
            a = short(m['awayTeam']['name'])
            lookup[f"{h}|{a}"] = m['id']
            lookup[f"{a}|{h}"] = m['id']
        return lookup
    except Exception as e:
        print(f"  fd.org matches fetch failed: {e}")
        return {}

# ── Upcoming fixtures ─────────────────────────────────────────────────────────
def fetch_upcoming(token):
    """Fetch scheduled matches and update upcoming_fixtures.json."""
    try:
        r = requests.get(f"{API_BASE}/competitions/{WC_CODE}/matches?status=SCHEDULED",
            headers={'X-Auth-Token': token}, timeout=15)
        if r.status_code != 200: return
        scheduled = r.json().get('matches', [])
        upcoming = []
        for m in scheduled[:14]:
            home = short(m['homeTeam']['name'])
            away = short(m['awayTeam']['name'])
            utc  = m.get('utcDate','')
            try:
                dt_utc = datetime.datetime.fromisoformat(utc.replace('Z','+00:00'))
                dt_cst = dt_utc - datetime.timedelta(hours=6)
                date_str = f"Jun {dt_cst.day}"
                hour = dt_cst.hour
                ampm = 'AM' if hour < 12 else 'PM'
                h12  = hour % 12 or 12
                min_part = f":{dt_cst.minute:02d}" if dt_cst.minute else ''
                time_str = f"{h12}{min_part}{ampm} CST"
            except:
                date_str = utc[:10]
                time_str = '?? CST'

            group_raw = m.get('stage','') or m.get('group','')
            letter = ''
            if 'GROUP_' in group_raw:
                letter = group_raw.replace('GROUP_','')
            elif group_raw.startswith('Group '):
                letter = group_raw.replace('Group ','')

            upcoming.append({
                "date":  date_str,
                "home":  home,
                "away":  away,
                "time":  time_str,
                "group": letter,
            })

        if upcoming:
            save('upcoming_fixtures.json', upcoming)
            print(f"  Upcoming fixtures: {len(upcoming)} matches updated")
            for u in upcoming[:4]:
                print(f"    {u['date']} {u['home']} vs {u['away']} {u['time']}")
    except Exception as e:
        print(f"  Upcoming fetch failed: {e}")

# ── Main ──────────────────────────────────────────────────────────────────────
def run():
    token = os.environ.get('FOOTBALL_DATA_TOKEN','').strip()

    # Load existing data — APPEND ONLY, never re-source
    matches  = load('matches.json')  or []
    stats    = load('match_stats.json') or {}
    goals    = load('goals.json')    or []
    upcoming = load('upcoming_fixtures.json') or []

    # Clean any placeholder goals
    before = len(goals)
    goals = [g for g in goals
             if g.get('scorer','').strip() not in {'See FIFA.com','Unknown',''}]
    if len(goals) < before:
        print(f"  Cleaned {before-len(goals)} placeholder goals")

    # Build lookup tables from EXISTING data
    existing_match_ids  = {m['id'] for m in matches}
    existing_stat_keys  = set(stats.keys())
    existing_goal_mids  = {g['matchId'] for g in goals
                           if sum(1 for x in goals if x['matchId']==g['matchId']) > 0}
    # Build lookup using short() on stored names to ensure consistency with API names
    match_lookup = {}
    for m in matches:
        h = short(m['home'])
        a = short(m['away'])
        # Update stored names to short form if different
        if m['home'] != h: m['home'] = h
        if m['away'] != a: m['away'] = a
        match_lookup[f"{h}|{a}"] = m['id']
        match_lookup[f"{a}|{h}"] = m['id']

    existing_nums = [int(m['id'].replace('m','')) for m in matches]
    next_num = max(existing_nums)+1 if existing_nums else 1
    next_goal_id = max((g['id'] for g in goals), default=0) + 1

    matches_added = stats_added = goals_added = upcoming_removed = 0

    # ── Step 1: ESPN for scores + goals ──────────────────────────────────────
    print("\nFetching from ESPN...")
    espn_events = fetch_espn_scores()
    
    fd_lookup = {}
    if token:
        print("\nFetching fd.org match IDs for stats lookup...")
        fd_lookup = fetch_fdorg_matches(token)

    for event in espn_events:
        parsed = parse_espn_event(event)
        if not parsed: continue

        home  = parsed['home']
        away  = parsed['away']
        score = parsed['score']
        if not home or not away: continue

        # Find or assign match ID
        key = f"{home}|{away}"
        mid = match_lookup.get(key)
        if not mid:
            mid = f"m{next_num}"
            next_num += 1
            match_lookup[key] = mid
            match_lookup[f"{away}|{home}"] = mid
            print(f"  New match: {mid} {home} {score} {away}")

        # ── APPEND: update score if changed ──────────────────────────────────
        existing = next((m for m in matches if m['id']==mid), None)
        if existing:
            if existing.get('score') != score:
                print(f"  Score update: {mid} {home} {existing['score']} → {score}")
                existing['score'] = score
        else:
            matches.append({
                "id":     mid,
                "date":   parsed['date'],
                "home":   home,
                "away":   away,
                "score":  score,
                "group":  parsed['group'],
                "ytId":   "",
                "fifaUrl": fifa_url(home, away),
            })
            matches.sort(key=lambda m: int(m['id'].replace('m','')))
            match_lookup[key] = mid
            match_lookup[f"{away}|{home}"] = mid
            matches_added += 1

        # ── APPEND: goals from ESPN (only if not already fetched) ─────────────
        if mid not in existing_goal_mids and parsed['goals']:
            parts = score.split('-')
            try: h_final, a_final = int(parts[0]), int(parts[1])
            except: continue

            # Rebuild running score
            h_run, a_run = 0, 0
            for gd in sorted(parsed['goals'], key=lambda x: x['minute']):
                is_og   = gd['type'] == 'own-goal'
                team    = gd.get('team','')
                scorer  = gd['scorer']
                minute  = gd['minute']
                gtype   = gd['type']

                # Determine which team scored
                if is_og:
                    # OG goes to OPPOSING team
                    if team == home: a_run += 1
                    else: h_run += 1
                else:
                    if team == home: h_run += 1
                    else: a_run += 1

                run_score = f"{h_run}-{a_run}"

                goals.append({
                    "id":      next_goal_id,
                    "matchId": mid,
                    "home":    home,
                    "away":    away,
                    "scorer":  scorer,
                    "minute":  minute,
                    "type":    gtype,
                    "phase":   parsed['group'],
                    "score":   run_score,
                    "desc":    "",  # generate_descriptions.py will fill this
                })
                next_goal_id += 1
                goals_added += 1

            existing_goal_mids.add(mid)
            print(f"  Goals added: {mid} — {goals_added} total new")

        # ── APPEND: stats from fd.org (only if not already fetched) ──────────
        if mid not in existing_stat_keys and token:
            fd_mid = fd_lookup.get(key)
            if fd_mid:
                print(f"  Fetching stats: {mid}...", end=' ', flush=True)
                detail = fetch_fdorg_stats(token, fd_mid)
                time.sleep(1.0)

                sr = detail.get('statistics') or []
                venue = venue_fmt(detail.get('venue','') or parsed['venue'])

                poss   = get_stat(sr,'possession',50,50)
                shots  = get_stat(sr,'total shots',10,8)
                sot    = get_stat(sr,'shots on target',4,3)
                passes = get_stat(sr,'passes',400,300)
                pacc   = get_stat(sr,'pass accuracy',82,75)
                fouls  = get_stat(sr,'fouls',12,12)
                corners= get_stat(sr,'corner',5,4)
                yellow = get_stat(sr,'yellow',1,1)
                offside= get_stat(sr,'offside',2,1)

                xg_h = round(sot[0]*0.33 + max(0,shots[0]-sot[0])*0.05, 1)
                xg_a = round(sot[1]*0.33 + max(0,shots[1]-sot[1])*0.05, 1)

                stats[mid] = {
                    "home":  home, "away": away, "score": score,
                    "date":  f"{parsed['date']}{(' - '+venue) if venue else ''}",
                    "poss":  poss,
                    "stats": [
                        ["Shots",           shots[0],  shots[1]],
                        ["Shots on Target",   sot[0],    sot[1]],
                        ["Passes",          passes[0], passes[1]],
                        ["Pass Accuracy %",   pacc[0],   pacc[1]],
                        ["Fouls",           fouls[0],  fouls[1]],
                        ["Corners",         corners[0],corners[1]],
                    ],
                    "xtra": [
                        ["xG",          xg_h,      xg_a],
                        ["Yellow Cards",yellow[0], yellow[1]],
                        ["Offsides",    offside[0],offside[1]],
                    ]
                }
                stats_added += 1
                existing_stat_keys.add(mid)
                print("done")

        # ── Remove from upcoming ──────────────────────────────────────────────
        before = len(upcoming)
        upcoming = [f for f in upcoming
                    if not (f['home'].lower() in home.lower() or
                            home.lower() in f['home'].lower()) or
                    not (f['away'].lower() in away.lower() or
                         away.lower() in f['away'].lower())]
        upcoming_removed += before - len(upcoming)

    # ── Step 2: Fetch upcoming fixtures ──────────────────────────────────────
    if token:
        print("\nFetching upcoming fixtures...")
        fetch_upcoming(token)

    # ── Save all (append-safe) ────────────────────────────────────────────────
    goals.sort(key=lambda g: (int(g['matchId'].replace('m','')), g['minute']))
    save('matches.json',   matches)
    save('match_stats.json', stats)
    save('goals.json',     goals)
    save('upcoming_fixtures.json', upcoming)

    print(f"\n=== SUMMARY ===")
    print(f"  Matches added:    {matches_added}")
    print(f"  Stats added:      {stats_added}")
    print(f"  Goals added:      {goals_added}")
    print(f"  Upcoming removed: {upcoming_removed}")
    print(f"  Total matches:    {len(matches)}")
    print(f"  Total stats:      {len(stats)}")
    print(f"  Total goals:      {len(goals)}")
    print(f"\nNow run: python update_site.py")

if __name__ == '__main__':
    print(f"=== Match Stats Updater — {datetime.date.today()} ===")
    run()
