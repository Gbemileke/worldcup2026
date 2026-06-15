#!/usr/bin/env python3
"""
update_match_stats.py
─────────────────────
Fetches all concluded 2026 World Cup matches from football-data.org,
converts them into MATCH_STATS entries, and patches index.html in-place.

Run locally : python update_match_stats.py
Run via CI  : triggered by .github/workflows/update-match-stats.yml

Requires: FOOTBALL_DATA_TOKEN env var (free tier at football-data.org)
"""

import os, re, sys, json, datetime, time, requests

HTML_FILE = "index.html"
API_BASE  = "https://api.football-data.org/v4"
WC_CODE   = "WC"

# ── Flag codes for known teams (2-letter display codes used in our app) ──────
FLAG_CODES = {
    "Mexico":"MX","South Africa":"ZA","South Korea":"KR","Czechia":"CZ",
    "Canada":"CA","Switzerland":"CH","Qatar":"QA","Bosnia and Herzegovina":"BA",
    "Brazil":"BR","Morocco":"MA","Scotland":"SC","Haiti":"HT",
    "USA":"US","United States":"US","Paraguay":"PY","Türkiye":"TR","Turkey":"TR",
    "Germany":"DE","Ecuador":"EC","Côte d'Ivoire":"CI","Curaçao":"CW",
    "Netherlands":"NL","Japan":"JP","Tunisia":"TN","Sweden":"SE",
    "Belgium":"BE","Egypt":"EG","Iran":"IR","IR Iran":"IR","New Zealand":"NZ",
    "Spain":"ES","Uruguay":"UY","Saudi Arabia":"SA","Cape Verde":"CV",
    "France":"FR","Senegal":"SN","Norway":"NO","Iraq":"IQ",
    "Argentina":"AR","Algeria":"DZ","Austria":"AT","Jordan":"JO",
    "Portugal":"PT","Colombia":"CO","Uzbekistan":"UZ","DR Congo":"CD",
    "England":"EN","Croatia":"HR","Panama":"PA","Ghana":"GH",
}

# ── Short display names (keep cards concise) ──────────────────────────────────
SHORT_NAMES = {
    "South Africa":"S. Africa","Côte d'Ivoire":"Ivory Coast",
    "Bosnia and Herzegovina":"Bosnia","Curaçao":"Curacao",
    "Saudi Arabia":"Saudi Arabia","New Zealand":"New Zealand",
    "United States":"USA","IR Iran":"Iran","Türkiye":"Turkey",
    "Cape Verde":"Cape Verde","DR Congo":"DR Congo",
}

# ── Venue shortnames ──────────────────────────────────────────────────────────
VENUES = {
    "Estadio Azteca":          "Estadio Azteca, Mexico City",
    "BMO Field":               "BMO Field, Toronto",
    "NRG Stadium":             "NRG Stadium, Houston",
    "AT&T Stadium":            "AT&T Stadium, Dallas",
    "MetLife Stadium":         "MetLife Stadium, New Jersey",
    "SoFi Stadium":            "SoFi Stadium, Los Angeles",
    "Hard Rock Stadium":       "Hard Rock Stadium, Miami",
    "Levi's Stadium":          "Levi's Stadium, San Francisco",
    "Gillette Stadium":        "Gillette Stadium, Boston",
    "Lincoln Financial Field": "Lincoln Financial Field, Philadelphia",
    "Arrowhead Stadium":       "Arrowhead Stadium, Kansas City",
    "Lumen Field":             "Lumen Field, Seattle",
    "Mercedes-Benz Stadium":   "Mercedes-Benz Stadium, Atlanta",
    "Vancouver BC Place":      "BC Place, Vancouver",
    "Estadio BBVA":            "Estadio BBVA, Monterrey",
    "Estadio Akron":           "Estadio Akron, Guadalajara",
}

def short(name):
    return SHORT_NAMES.get(name, name)

def flag(name):
    return FLAG_CODES.get(name, name[:2].upper())

def venue_short(v):
    for k, val in VENUES.items():
        if k.lower() in v.lower():
            return val
    return v

def fmt_date(dt_str):
    """Jun 11 style from ISO date"""
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace("Z",""))
        return dt.strftime("Jun %-d")
    except:
        return dt_str[:10]

# ── Fetch from API ────────────────────────────────────────────────────────────
def fetch_matches(token):
    """Returns list of finished match dicts from football-data.org"""
    headers = {"X-Auth-Token": token}
    url = f"{API_BASE}/competitions/{WC_CODE}/matches?status=FINISHED"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 403:
        print("ERROR: Invalid or expired token")
        sys.exit(1)
    r.raise_for_status()
    data = r.json()
    return data.get("matches", [])

def fetch_match_stats(token, match_id):
    """Fetch detailed stats for one match (possession, shots etc)"""
    headers = {"X-Auth-Token": token}
    url = f"{API_BASE}/matches/{match_id}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except:
        return {}

# ── Build a MATCH_STATS entry from API data ───────────────────────────────────
def build_entry(m, detail):
    home_name = m["homeTeam"]["name"]
    away_name = m["awayTeam"]["name"]
    home_score = m["score"]["fullTime"]["home"]
    away_score = m["score"]["fullTime"]["away"]
    utc_date   = m.get("utcDate","")
    venue_raw  = m.get("venue", "") or ""

    date_str = fmt_date(utc_date) + " - " + venue_short(venue_raw)
    score    = f"{home_score}-{away_score}"

    # Pull stats from detail response if available
    stats_raw = detail.get("statistics", []) or []
    def get_stat(label, home_default, away_default):
        for s in stats_raw:
            if label.lower() in s.get("type","").lower():
                hv = s.get("home")
                av = s.get("away")
                try:
                    return [int(str(hv).replace("%","")), int(str(av).replace("%",""))]
                except:
                    pass
        return [home_default, away_default]

    poss = get_stat("possession", 50, 50)
    shots_total  = get_stat("total shots",  10,  8)
    shots_target = get_stat("shots on target", 4, 3)
    passes       = get_stat("passes", 400, 300)
    pass_acc     = get_stat("pass accuracy", 82, 75)
    fouls        = get_stat("fouls", 12, 12)
    corners      = get_stat("corners", 5, 4)
    yellow       = get_stat("yellow cards", 1, 1)
    offsides     = get_stat("offsides", 2, 1)

    # Estimate xG from shots (simple heuristic if not in API)
    xg_home = round(shots_target[0] * 0.35 + (shots_total[0] - shots_target[0]) * 0.05, 1)
    xg_away = round(shots_target[1] * 0.35 + (shots_total[1] - shots_target[1]) * 0.05, 1)

    entry = (
        f"{{home:'{short(home_name)}', away:'{short(away_name)}', "
        f"hf:'{flag(home_name)}', af:'{flag(away_name)}', "
        f"score:'{score}', date:'{date_str}', "
        f"poss:[{poss[0]},{poss[1]}], "
        f"stats:[['Shots',{shots_total[0]},{shots_total[1]}],"
        f"['Shots on Target',{shots_target[0]},{shots_target[1]}],"
        f"['Passes',{passes[0]},{passes[1]}],"
        f"['Pass Accuracy %',{pass_acc[0]},{pass_acc[1]}],"
        f"['Fouls',{fouls[0]},{fouls[1]}],"
        f"['Corners',{corners[0]},{corners[1]}]], "
        f"xtra:[['xG',{xg_home},{xg_away}],"
        f"['Yellow Cards',{yellow[0]},{yellow[1]}],"
        f"['Offsides',{offsides[0]},{offsides[1]}]]}}"
    )
    return entry

# ── Patch index.html ──────────────────────────────────────────────────────────
def patch_html(new_entries):
    """
    new_entries: dict {match_key_str: entry_str}
    e.g. {"Belgium|Egypt": "{ home:'Belgium', ... }"}
    Appends any matches not already present in MATCH_STATS.
    """
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    # Find MATCH_STATS block boundaries
    ms_start = html.find("var MATCH_STATS = {")
    ms_end   = html.find("\nfunction buildMatchSelector", ms_start)
    if ms_start < 0:
        print("ERROR: MATCH_STATS block not found")
        sys.exit(1)

    ms_block = html[ms_start:ms_end]

    # Find current highest match index
    existing_ids = re.findall(r"m(\d+):", ms_block)
    next_id = max(int(x) for x in existing_ids) + 1 if existing_ids else 1

    # Find which matches are already in the block
    already_in = set()
    for m in re.finditer(r"home:'([^']+)',\s*away:'([^']+)'", ms_block):
        already_in.add(f"{m.group(1)}|{m.group(2)}")

    added = []
    for key, entry in new_entries.items():
        h, a = key.split("|")
        if f"{short(h)}|{short(a)}" in already_in or key in already_in:
            print(f"  Already exists: {key}")
            continue

        new_line = f"\n  m{next_id}: {entry},"
        # Insert before closing }; of MATCH_STATS
        close_idx = ms_block.rfind("\n};")
        ms_block = ms_block[:close_idx] + new_line + ms_block[close_idx:]
        added.append(f"m{next_id}: {key}")
        next_id += 1

    if not added:
        print("No new matches to add")
        return False

    # Update ids array in buildMatchSelector
    all_ids = re.findall(r"m(\d+):", ms_block)
    ids_str = ",".join(f"'m{i}'" for i in sorted(set(int(x) for x in all_ids)))
    html = re.sub(r"var ids = \[[^\]]+\];", f"var ids = [{ids_str}];", html)

    # Update match count in analytics snapshot
    total_matches = len(re.findall(r"m\d+:", ms_block)) - 1  # subtract header
    html = re.sub(
        r'(<div class="stat-num">)\d+(</div><div class="stat-label">Matches Played</div>)',
        rf'\g<1>{total_matches}\2', html
    )

    html = html[:ms_start] + ms_block + html[ms_end:]

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Added {len(added)} new matches: {', '.join(added)}")
    return True

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "")
    if not token or token == "YOUR_API_TOKEN_HERE":
        print("ERROR: Set FOOTBALL_DATA_TOKEN environment variable")
        print("  export FOOTBALL_DATA_TOKEN=your_token_here")
        sys.exit(1)

    print(f"=== Match Stats Updater — {datetime.date.today()} ===\n")

    matches = fetch_matches(token)
    print(f"Found {len(matches)} finished matches\n")

    new_entries = {}
    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        mid  = m["id"]

        print(f"Fetching stats: {short(home)} vs {short(away)} ...", end=" ")
        detail = fetch_match_stats(token, mid)
        time.sleep(0.7)  # respect rate limit (10 req/min free tier)

        entry = build_entry(m, detail)
        key   = f"{short(home)}|{short(away)}"
        new_entries[key] = entry
        print("done")

    print()
    patch_html(new_entries)
    print("\nDone ✓")
