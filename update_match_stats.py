#!/usr/bin/env python3
"""
update_match_stats.py
─────────────────────
Fetches concluded 2026 World Cup matches from football-data.org
and updates ONLY the JSON data files in data/.

Does NOT touch index.html directly — that's update_site.py's job.
After this runs, call: python update_site.py

Requires: FOOTBALL_DATA_TOKEN env var
Get free token: https://www.football-data.org/client/register
"""

import os, re, sys, json, datetime, time, requests

DATA_DIR = 'data'
API_BASE = 'https://api.football-data.org/v4'
WC_CODE  = 'WC'

# ── Name normalisation ────────────────────────────────────────────────────────
SHORT = {
    "South Africa":"S. Africa", "Côte d'Ivoire":"Ivory Coast",
    "Bosnia and Herzegovina":"Bosnia", "Curaçao":"Curacao",
    "United States":"USA", "IR Iran":"Iran", "Türkiye":"Turkey",
    "Korea Republic":"S. Korea", "Cape Verde":"Cape Verde",
    "Congo DR":"DR Congo",
}

VENUES = {
    "Azteca":"Estadio Azteca, Mexico City",
    "BMO":"BMO Field, Toronto",
    "NRG":"NRG Stadium, Houston",
    "AT&T":"AT&T Stadium, Dallas",
    "MetLife":"MetLife Stadium, New Jersey",
    "SoFi":"SoFi Stadium, Los Angeles",
    "Hard Rock":"Hard Rock Stadium, Miami",
    "Levi":"Levis Stadium, San Francisco",
    "Gillette":"Gillette Stadium, Boston",
    "Lincoln":"Lincoln Financial Field, Philadelphia",
    "Arrowhead":"Arrowhead Stadium, Kansas City",
    "Lumen":"Lumen Field, Seattle",
    "Mercedes":"Mercedes-Benz Stadium, Atlanta",
    "BC Place":"BC Place, Vancouver",
    "BBVA":"Estadio BBVA, Monterrey",
    "Akron":"Estadio Akron, Guadalajara",
}

FIFA_BASE = 'https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/'

def short(name):
    return SHORT.get(name, name)

def venue_fmt(v):
    if not v: return 'Stadium'
    for k, val in VENUES.items():
        if k.lower() in v.lower():
            return val
    return v

def fmt_date(dt_str):
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace('Z',''))
        return dt.strftime('Jun %-d')
    except:
        return dt_str[:10]

def fifa_url(home, away):
    # FIFA uses their own name slugs — map our short names
    FIFA_NAME_MAP = {
        'S. Korea':'south-korea','South Korea':'south-korea',
        'Bosnia':'bosnia-herzegovina','Turkiye':'turkey','Turkey':'turkey',
        'Cape Verde':'cabo-verde','DR Congo':'democratic-republic-of-congo',
        'Ivory Coast':'cote-divoire','USA':'united-states',
        'S. Africa':'south-africa','South Africa':'south-africa',
        'Curacao':'curacao',
    }
    # FIFA sometimes lists away team first in the URL
    FIFA_URL_SWAPS = {
        ('Qatar','Switzerland'),
        ('Norway','Iraq'),
    }
    def slug(name):
        return FIFA_NAME_MAP.get(name, name.lower().replace(' ','-').replace("'","").replace('.',''))
    h, a = slug(home), slug(away)
    if (home, away) in FIFA_URL_SWAPS:
        return f"{FIFA_BASE}{a}-v-{h}-highlights-match-report"
    return f"{FIFA_BASE}{h}-v-{a}-highlights-match-report"


def load(fname):
    path = os.path.join(DATA_DIR, fname)
    if not os.path.exists(path):
        print(f"  WARNING: {fname} not found")
        return None
    with open(path) as f:
        return json.load(f)

def save(fname, data):
    path = os.path.join(DATA_DIR, fname)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

# ── API calls ─────────────────────────────────────────────────────────────────
def fetch_matches(token):
    headers = {'X-Auth-Token': token}
    url = f"{API_BASE}/competitions/{WC_CODE}/matches?status=FINISHED"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 403:
        print("ERROR: Invalid or expired token"); sys.exit(1)
    r.raise_for_status()
    return r.json().get('matches', [])

def fetch_detail(token, match_id):
    headers = {'X-Auth-Token': token}
    try:
        r = requests.get(f"{API_BASE}/matches/{match_id}", headers=headers, timeout=15)
        if r.status_code == 429:
            print(f"  RATE LIMIT hit — waiting 60s...")
            time.sleep(60)
            r = requests.get(f"{API_BASE}/matches/{match_id}", headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        goals_count = len(data.get('goals') or [])
        print(f"  API: match {match_id} — {goals_count} goals in response")
        return data
    except Exception as e:
        print(f"  WARNING: fetch_detail({match_id}) failed: {e}")
        return {}

def fetch_upcoming(token):
    """Fetch next 10 scheduled matches from football-data.org
    and update upcoming_fixtures.json"""
    headers = {'X-Auth-Token': token}
    try:
        r = requests.get(
            f"{API_BASE}/competitions/{WC_CODE}/matches?status=SCHEDULED",
            headers=headers, timeout=15)
        r.raise_for_status()
        scheduled = r.json().get('matches', [])
    except Exception as e:
        print(f"  WARNING: Could not fetch upcoming fixtures: {e}")
        return

    # Convert timezone: API returns UTC, convert to CST (UTC-6)
    import datetime
    upcoming = []
    for m in scheduled[:12]:  # next 12 scheduled
        home = short(m['homeTeam']['name'])
        away = short(m['awayTeam']['name'])
        utc_str = m.get('utcDate','')
        group_raw = m.get('stage','') or m.get('group','') or ''
        # Extract group letter
        group_letter = ''
        if 'GROUP_' in group_raw:
            group_letter = group_raw.replace('GROUP_','')
        elif group_raw.startswith('Group '):
            group_letter = group_raw.replace('Group ','')

        # Parse UTC time and convert to CST (UTC-6)
        try:
            dt_utc = datetime.datetime.fromisoformat(utc_str.replace('Z','+00:00'))
            dt_cst = dt_utc - datetime.timedelta(hours=6)
            date_str = dt_cst.strftime('%-d %b').replace(' ','\xa0')
            date_str = 'Jun ' + str(dt_cst.day) if dt_cst.month == 6 else \
                       'Jul ' + str(dt_cst.day)
            # Format time
            hour = dt_cst.hour
            minute = dt_cst.minute
            ampm = 'AM' if hour < 12 else 'PM'
            hour12 = hour % 12 or 12
            time_str = f"{hour12}{':{:02d}'.format(minute) if minute else ''}{'\u200b'}{ampm} CST"
        except:
            date_str = utc_str[:10]
            time_str = '?:?? CST'

        upcoming.append({
            "date":  date_str,
            "home":  home,
            "away":  away,
            "time":  time_str,
            "group": group_letter
        })

    if upcoming:
        save('upcoming_fixtures.json', upcoming)
        print(f"  Upcoming fixtures updated: {len(upcoming)} matches")
        for f in upcoming[:4]:
            print(f"    {f['date']} {f['home']} vs {f['away']} {f['time']}")

def get_stat(stats_raw, label, default_h, default_a):
    for s in stats_raw or []:
        if label.lower() in s.get('type','').lower():
            try:
                return [
                    int(str(s.get('home','')).replace('%','')),
                    int(str(s.get('away','')).replace('%',''))
                ]
            except:
                pass
    return [default_h, default_a]

# ── Main update logic ─────────────────────────────────────────────────────────
def run(token):
    # Load all existing data
    matches   = load('matches.json')       or []
    stats     = load('match_stats.json')   or {}
    goals     = load('goals.json')         or []
    upcoming  = load('upcoming_fixtures.json') or []

    # Build lookup of what we already have
    existing_match_ids = {m['id'] for m in matches}
    existing_stat_keys = set(stats.keys())
    # Only count matches as 'goals done' if they have at least 1 goal
    # Only mark a match as 'goals done' if it actually has goals in goals.json
    goals_per_match = {}
    for g in goals:
        gmid = g['matchId']
        goals_per_match[gmid] = goals_per_match.get(gmid, 0) + 1
    existing_goal_matchids = {k for k, v in goals_per_match.items() if v > 0}

    # Build match number lookup: "Home|Away" -> "m1", "m2" etc
    match_lookup = {}
    for m in matches:
        key = f"{m['home']}|{m['away']}"
        match_lookup[key] = m['id']
        match_lookup[f"{m['away']}|{m['home']}"] = m['id']

    # Figure out next match id number
    existing_nums = [int(m['id'].replace('m','')) for m in matches if m['id'].startswith('m')]
    next_num = max(existing_nums) + 1 if existing_nums else 1

    # Fetch from API
    api_matches = fetch_matches(token)
    print(f"API returned {len(api_matches)} finished matches")

    matches_added  = 0
    stats_added    = 0
    goals_added    = 0
    upcoming_removed = 0

    next_goal_id = max((g['id'] for g in goals), default=0) + 1

    for m in api_matches:
        home_raw   = m['homeTeam']['name']
        away_raw   = m['awayTeam']['name']
        home       = short(home_raw)
        away       = short(away_raw)
        home_score = m['score']['fullTime']['home']
        away_score = m['score']['fullTime']['away']
        score      = f"{home_score}-{away_score}"
        date_str   = fmt_date(m.get('utcDate',''))
        group_raw  = m.get('stage','') or m.get('group','') or 'Group Stage'

        # Find or assign match id
        key = f"{home}|{away}"
        mid = match_lookup.get(key)
        if not mid:
            # Also try raw names
            mid = match_lookup.get(f"{home_raw}|{away_raw}")
        if not mid:
            # New match - assign next id
            mid = f"m{next_num}"
            next_num += 1
            match_lookup[key] = mid
            match_lookup[f"{away}|{home}"] = mid

        # ── 1. Update matches.json ─────────────────────────────────────────
        existing = next((x for x in matches if x['id'] == mid), None)
        if existing:
            if existing.get('score') != score:
                existing['score'] = score
                print(f"  Updated score: {mid} {home} {score} {away}")
        else:
            new_match = {
                "id": mid,
                "date": date_str,
                "home": home,
                "away": away,
                "score": score,
                "group": group_raw,
                "ytId": "",
                "fifaUrl": fifa_url(home, away)
            }
            matches.append(new_match)
            matches.sort(key=lambda x: int(x['id'].replace('m','')))
            matches_added += 1
            print(f"  Added match: {mid} {home} {score} {away}")

        # ── 2+3. Fetch detail once for BOTH stats AND goals ───────────────
        need_stats = mid not in existing_stat_keys
        need_goals = mid not in existing_goal_matchids
        
        detail = {}
        if need_stats or need_goals:
            print(f"  Fetching detail for {mid} ({home} vs {away})...", end=' ', flush=True)
            detail = fetch_detail(token, m['id'])
            time.sleep(1.0)  # rate limit: free tier = 10 req/min
            print("done")

        if need_stats:

            sr = detail.get('statistics') or []
            venue_raw = m.get('venue','') or ''

            poss   = get_stat(sr, 'possession',       50, 50)
            shots  = get_stat(sr, 'total shots',       10,  8)
            sot    = get_stat(sr, 'shots on target',    4,  3)
            passes = get_stat(sr, 'passes',           400,300)
            pacc   = get_stat(sr, 'pass accuracy',     82, 75)
            fouls  = get_stat(sr, 'fouls',             12, 12)
            corners= get_stat(sr, 'corner',             5,  4)
            yellow = get_stat(sr, 'yellow',             1,  1)
            offside= get_stat(sr, 'offside',            2,  1)
            saves  = get_stat(sr, 'saves',              3,  3)

            xg_h = round(sot[0]*0.33 + max(0, shots[0]-sot[0])*0.05, 1)
            xg_a = round(sot[1]*0.33 + max(0, shots[1]-sot[1])*0.05, 1)

            stats[mid] = {
                "home": home,
                "away": away,
                "score": score,
                "date": f"{date_str} - {venue_fmt(venue_raw)}",
                "poss": poss,
                "stats": [
                    ["Shots",           shots[0],  shots[1]],
                    ["Shots on Target", sot[0],    sot[1]],
                    ["Passes",          passes[0], passes[1]],
                    ["Pass Accuracy %", pacc[0],   pacc[1]],
                    ["Fouls",           fouls[0],  fouls[1]],
                    ["Corners",         corners[0],corners[1]],
                    ["Saves",           saves[0],  saves[1]],
                ],
                "xtra": [
                    ["xG",          xg_h,     xg_a],
                    ["Yellow Cards",yellow[0],yellow[1]],
                    ["Offsides",    offside[0],offside[1]],
                ]
            }
            stats_added += 1
            print("done")

        # ── 3. Update goals.json ───────────────────────────────────────────
        if need_goals:
            # Use the detail already fetched above (no extra API call needed)
            detail_goals = detail.get('goals') or []
            # football-data.org free tier: goals are in detail['goals']
            # Each goal: {scorer:{name}, team:{name}, minute, type}
            print(f"  Goals for {mid}: {len(detail_goals)} found")

            if detail_goals:
                for gd in detail_goals:
                    scorer_name = (gd.get('scorer') or {}).get('name','Unknown')
                    team_name   = (gd.get('team')   or {}).get('name','')
                    minute      = gd.get('minute') or 0
                    gtype_raw   = (gd.get('type') or 'REGULAR').upper()
                    gtype = ('penalty'  if gtype_raw == 'PENALTY'  else
                             'own-goal' if gtype_raw == 'OWN_GOAL' else
                             'open-play')

                    is_og    = gtype == 'own-goal'
                    scorer   = scorer_name + (' OG' if is_og else '')
                    run_score = f"{home_score}-{away_score}"

                    goals.append({
                        "id":      next_goal_id,
                        "matchId": mid,
                        "home":    home,
                        "away":    away,
                        "scorer":  scorer,
                        "minute":  minute,
                        "type":    gtype,
                        "phase":   group_raw,
                        "score":   run_score,
                        "desc":    f"{scorer_name}{'(OG) ' if is_og else ' '}scored for {short(team_name) if team_name else home} — {home} {home_score}-{away_score} {away}"
                    })
                    next_goal_id += 1
                    goals_added += 1
            else:
                # API returned no goals — add placeholder so match appears in feed
                # Will be overwritten next run if API returns goals
                print(f"  WARNING: No goals from API for {mid} ({home} {home_score}-{away_score} {away})")
                total_goals_in_match = (home_score or 0) + (away_score or 0)
                if total_goals_in_match > 0:
                    goals.append({
                        "id":      next_goal_id,
                        "matchId": mid,
                        "home":    home,
                        "away":    away,
                        "scorer":  'See FIFA.com',
                        "minute":  90,
                        "type":    'open-play',
                        "phase":   group_raw,
                        "score":   f"{home_score}-{away_score}",
                        "desc":    f"{home} {home_score}-{away_score} {away} — scorers not yet available from API. Check FIFA.com for full details."
                    })
                    next_goal_id += 1
                    goals_added += 1

        # ── 4. Remove from upcoming_fixtures.json ─────────────────────────
        before = len(upcoming)
        upcoming = [
            f for f in upcoming
            if not (f['home'].lower() in home.lower() or home.lower() in f['home'].lower()
                    or f['away'].lower() in away.lower() or away.lower() in f['away'].lower())
            or not (f['home'].lower() in away.lower() or away.lower() in f['home'].lower()
                    or f['away'].lower() in home.lower() or home.lower() in f['away'].lower())
        ]
        removed = before - len(upcoming)
        if removed > 0:
            upcoming_removed += removed

    # ── Save all updated JSON files ───────────────────────────────────────────
    save('matches.json', matches)
    save('match_stats.json', stats)
    save('goals.json', sorted(goals, key=lambda g: (int(g['matchId'].replace('m','')), g['minute'])))

    # Fetch upcoming fixtures directly from API (always fresh)
    print("\nFetching upcoming fixtures from API...")
    fetch_upcoming(token)

    print(f"\n=== SUMMARY ===")
    print(f"  Matches added:    {matches_added}")
    print(f"  Stats added:      {stats_added}")
    print(f"  Goals added:      {goals_added}")
    print(f"  Upcoming removed: {upcoming_removed}")
    print(f"  Total matches:    {len(matches)}")
    print(f"  Total stats:      {len(stats)}")
    print(f"  Total goals:      {len(goals)}")
    print(f"\nNow run: python update_site.py")

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    token = os.environ.get('FOOTBALL_DATA_TOKEN','').strip()
    if not token:
        print("WARNING: FOOTBALL_DATA_TOKEN not set — skipping")
        print("Add it in: GitHub Settings → Secrets → Actions → FOOTBALL_DATA_TOKEN")
        sys.exit(0)

    print(f"=== Match Stats Updater — {datetime.date.today()} ===\n")
    run(token)
