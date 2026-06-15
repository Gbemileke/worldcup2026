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

# ── Short display names ───────────────────────────────────────────────────────
SHORT_NAMES = {
    "South Africa":"S. Africa", "Côte d'Ivoire":"Ivory Coast",
    "Bosnia and Herzegovina":"Bosnia", "Curaçao":"Curacao",
    "United States":"USA", "IR Iran":"Iran", "Türkiye":"Turkey",
    "Korea Republic":"S. Korea", "Cape Verde":"Cape Verde",
    "Congo DR":"DR Congo", "Saudi Arabia":"Saudi Arabia",
}

# ── Flag codes ────────────────────────────────────────────────────────────────
FLAG_CODES = {
    "Mexico":"MX","South Africa":"ZA","Korea Republic":"KR","Czechia":"CZ",
    "Canada":"CA","Switzerland":"CH","Qatar":"QA","Bosnia and Herzegovina":"BA",
    "Brazil":"BR","Morocco":"MA","Scotland":"SC","Haiti":"HT",
    "USA":"US","United States":"US","Paraguay":"PY","Türkiye":"TR",
    "Germany":"DE","Ecuador":"EC","Côte d'Ivoire":"CI","Curaçao":"CW",
    "Netherlands":"NL","Japan":"JP","Tunisia":"TN","Sweden":"SE",
    "Belgium":"BE","Egypt":"EG","IR Iran":"IR","New Zealand":"NZ",
    "Spain":"ES","Uruguay":"UY","Saudi Arabia":"SA","Cape Verde":"CV",
    "France":"FR","Senegal":"SN","Norway":"NO","Iraq":"IQ",
    "Argentina":"AR","Algeria":"DZ","Austria":"AT","Jordan":"JO",
    "Portugal":"PT","Colombia":"CO","Uzbekistan":"UZ","Congo DR":"CD",
    "England":"EN","Croatia":"HR","Panama":"PA","Ghana":"GH",
}

VENUES = {
    "Estadio Azteca":"Estadio Azteca, Mexico City",
    "BMO Field":"BMO Field, Toronto",
    "NRG Stadium":"NRG Stadium, Houston",
    "AT&T Stadium":"AT&T Stadium, Dallas",
    "MetLife Stadium":"MetLife Stadium, New Jersey",
    "SoFi Stadium":"SoFi Stadium, Los Angeles",
    "Hard Rock Stadium":"Hard Rock Stadium, Miami",
    "Levi's Stadium":"Levi's Stadium, San Francisco",
    "Gillette Stadium":"Gillette Stadium, Boston",
    "Lincoln Financial":"Lincoln Financial Field, Philadelphia",
    "Arrowhead":"Arrowhead Stadium, Kansas City",
    "Lumen Field":"Lumen Field, Seattle",
    "Mercedes-Benz":"Mercedes-Benz Stadium, Atlanta",
    "BC Place":"BC Place, Vancouver",
    "Estadio BBVA":"Estadio BBVA, Monterrey",
    "Estadio Akron":"Estadio Akron, Guadalajara",
}

def short(name):
    return SHORT_NAMES.get(name, name)

def flag(name):
    return FLAG_CODES.get(name, name[:2].upper())

def venue_short(v):
    if not v: return "Stadium"
    for k, val in VENUES.items():
        if k.lower() in v.lower():
            return val
    return v

def fmt_date(dt_str):
    try:
        dt = datetime.datetime.fromisoformat(dt_str.replace("Z",""))
        return dt.strftime("Jun %-d")
    except:
        return dt_str[:10]


# ── Fetch from API ────────────────────────────────────────────────────────────
def fetch_matches(token):
    headers = {"X-Auth-Token": token}
    url = f"{API_BASE}/competitions/{WC_CODE}/matches?status=FINISHED"
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 403:
        print("ERROR: Invalid or expired token"); sys.exit(1)
    r.raise_for_status()
    return r.json().get("matches", [])

def fetch_match_detail(token, match_id):
    headers = {"X-Auth-Token": token}
    try:
        r = requests.get(f"{API_BASE}/matches/{match_id}", headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()
    except:
        return {}


# ── Build one MATCH_STATS entry ───────────────────────────────────────────────
def build_entry(m, detail):
    home_name  = m["homeTeam"]["name"]
    away_name  = m["awayTeam"]["name"]
    home_score = m["score"]["fullTime"]["home"]
    away_score = m["score"]["fullTime"]["away"]
    utc_date   = m.get("utcDate", "")
    venue_raw  = m.get("venue", "") or ""

    date_str = fmt_date(utc_date) + " - " + venue_short(venue_raw)
    score    = f"{home_score}-{away_score}"

    stats_raw = detail.get("statistics", []) or []

    def get_stat(label, hd, ad):
        for s in stats_raw:
            if label.lower() in s.get("type","").lower():
                try:
                    return [int(str(s.get("home","")).replace("%","")),
                            int(str(s.get("away","")).replace("%",""))]
                except: pass
        return [hd, ad]

    poss   = get_stat("possession",    50, 50)
    shots  = get_stat("total shots",   10,  8)
    sot    = get_stat("shots on target", 4, 3)
    passes = get_stat("passes",       400,300)
    pacc   = get_stat("pass accuracy",  82, 75)
    fouls  = get_stat("fouls",          12, 12)
    corners= get_stat("corners",         5,  4)
    yellow = get_stat("yellow cards",    1,  1)
    offs   = get_stat("offsides",        2,  1)

    xg_h = round(sot[0] * 0.33 + max(0, shots[0] - sot[0]) * 0.05, 1)
    xg_a = round(sot[1] * 0.33 + max(0, shots[1] - sot[1]) * 0.05, 1)

    # Build the JS object string — NO trailing comma (caller adds it)
    return (
        f"{{home:'{short(home_name)}',away:'{short(away_name)}',"
        f"hf:'{flag(home_name)}',af:'{flag(away_name)}',"
        f"score:'{score}',date:'{date_str}',"
        f"poss:[{poss[0]},{poss[1]}],"
        f"stats:[['Shots',{shots[0]},{shots[1]}],"
        f"['Shots on Target',{sot[0]},{sot[1]}],"
        f"['Passes',{passes[0]},{passes[1]}],"
        f"['Pass Accuracy %',{pacc[0]},{pacc[1]}],"
        f"['Fouls',{fouls[0]},{fouls[1]}],"
        f"['Corners',{corners[0]},{corners[1]}]],"
        f"xtra:[['xG',{xg_h},{xg_a}],"
        f"['Yellow Cards',{yellow[0]},{yellow[1]}],"
        f"['Offsides',{offs[0]},{offs[1]}]]}}"
    )


# ── Patch index.html — safe, order-correct rewrite ───────────────────────────
def patch_html(new_entries):
    """
    Safely patches MATCH_STATS in index.html.

    Key fix: all modifications happen on one consistent string,
    assembled in the correct order, with no overlapping re.sub calls.
    """
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    # ── 1. Locate MATCH_STATS block ──────────────────────────────────────────
    OPEN_MARKER  = "var MATCH_STATS = {"
    CLOSE_MARKER = "\nfunction buildMatchSelector"

    ms_start = html.find(OPEN_MARKER)
    ms_end   = html.find(CLOSE_MARKER, ms_start)

    if ms_start < 0 or ms_end < 0:
        print("ERROR: Cannot locate MATCH_STATS block — aborting")
        sys.exit(1)

    ms_block = html[ms_start:ms_end]   # isolated block to edit

    # ── 2. Build set of already-present matches ──────────────────────────────
    already_in = set()
    for m in re.finditer(r"home:'([^']+)',\s*away:'([^']+)'", ms_block):
        already_in.add(f"{m.group(1)}|{m.group(2)}")

    # ── 3. Find next available match index ──────────────────────────────────
    # Only count real match keys like "m12:" at the START of an entry line
    existing_nums = [int(x) for x in re.findall(r"^\s*m(\d+)\s*:", ms_block, re.MULTILINE)]
    next_id = max(existing_nums) + 1 if existing_nums else 1

    # ── 4. Insert new entries ────────────────────────────────────────────────
    added = []
    for key, entry in new_entries.items():
        h, a = key.split("|")
        if key in already_in or f"{short(h)}|{short(a)}" in already_in:
            print(f"  Already exists: {key}")
            continue

        # Find the closing }; of MATCH_STATS and insert before it
        close_idx = ms_block.rfind("\n};")
        if close_idx < 0:
            print(f"  ERROR: cannot find closing }; — skipping {key}")
            continue

        insert = f"\n  m{next_id}: {entry},"
        ms_block = ms_block[:close_idx] + insert + ms_block[close_idx:]
        added.append(f"m{next_id}: {key}")
        next_id += 1

    if not added:
        print("No new matches to add.")
        return False

    # ── 5. Rebuild ids array ─────────────────────────────────────────────────
    match_nums = sorted(set(int(x) for x in re.findall(r"^\s*m(\d+)\s*:", ms_block, re.MULTILINE)))
    ids_str = ",".join(f"'m{i}'" for i in match_nums)

    # ── 6. Reassemble the full HTML ──────────────────────────────────────────
    # Do this BEFORE any further substitutions so we work on one clean string
    html_new = html[:ms_start] + ms_block + html[ms_end:]

    # ── 7. Update ids array ──────────────────────────────────────────────────
    html_new = re.sub(
        r"var ids = \['m\d+'(?:,'m\d+')*\];",
        f"var ids = [{ids_str}];",
        html_new, count=1
    )

    # ── 8. Update match count stat ───────────────────────────────────────────
    total = len(match_nums)
    html_new = re.sub(
        r'(<div class="stat-num">)\d+(</div><div class="stat-label">Matches Played</div>)',
        rf'\g<1>{total}\2',
        html_new, count=1
    )

    # ── 9. Verify brace balance before writing ───────────────────────────────
    js_start = html_new.rfind('<script>') + len('<script>')
    js_end   = html_new.rfind('</script>')
    js       = html_new[js_start:js_end]
    opens, closes = js.count('{'), js.count('}')
    if opens != closes:
        print(f"SAFETY ABORT: brace mismatch {opens}/{closes} — NOT writing file")
        sys.exit(1)

    # ── 10. Write ────────────────────────────────────────────────────────────
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html_new)

    print(f"Added {len(added)} match(es): {', '.join(added)}")
    print(f"Brace balance: {opens}/{closes} OK")
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
        print(f"  Fetching: {short(home)} vs {short(away)} ...", end=" ", flush=True)
        detail = fetch_match_detail(token, mid)
        time.sleep(0.7)  # free tier: 10 req/min
        entry = build_entry(m, detail)
        key   = f"{short(home)}|{short(away)}"
        new_entries[key] = entry
        print("done")

    print()
    patch_html(new_entries)

    print("\nUpdating MATCHES array...")
    patch_matches(new_entries)

    print("\nUpdating GOALS feed...")
    patch_goals(matches)

    print("\nDone ✓")


# ── Patch MATCHES array ───────────────────────────────────────────────────────
def patch_matches(new_entries):
    """
    Adds new entries to the var MATCHES = [...] array in index.html.
    new_entries: same dict as patch_html — {key: entry_str}
    """
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    OPEN_M  = "var MATCHES = ["
    CLOSE_M = "\n];\n\nvar GOALS"

    ms = html.find(OPEN_M)
    me = html.find(CLOSE_M, ms)
    if ms < 0 or me < 0:
        print("  WARNING: MATCHES array not found — skipping MATCHES update")
        return

    mb = html[ms:me]

    # Already-present match keys
    present = set()
    for m in re.finditer(r"home:'([^']+)',\s*away:'([^']+)'", mb):
        present.add(f"{m.group(1)}|{m.group(2)}")

    existing_nums = [int(x) for x in re.findall(r"id:'m(\d+)'", mb)]
    next_id = max(existing_nums) + 1 if existing_nums else 1

    added = []
    for key, _ in new_entries.items():
        h, a = key.split("|")
        if key in present or f"{h}|{a}" in present:
            continue
        # Parse date from the MATCH_STATS entry we already built
        date_str = "Jun ??"
        # Build a minimal MATCHES entry
        line = (
            f"\n  {{id:'m{next_id}', date:'{date_str}', "
            f"home:'{h}', away:'{a}', "
            f"hf:'{flag(h)}', af:'{flag(a)}', "
            f"score:'?-?', group:'Group ?', ytId:''}},"
        )
        # Insert before closing ];
        close_idx = mb.rfind("\n];")
        if close_idx < 0:
            close_idx = len(mb)
        mb = mb[:close_idx] + line + mb[close_idx:]
        added.append(f"m{next_id}: {key}")
        next_id += 1

    if not added:
        return

    html = html[:ms] + mb + html[me:]
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  MATCHES updated: {', '.join(added)}")


# ── Patch GOALS — add placeholder goal entries for scoring matches ────────────
def patch_goals(matches_api):
    """
    For each finished match with goals, adds placeholder GOALS entries
    if the match has goals but none are yet in the GOALS array.
    Uses API scorers endpoint to get goal details where available.
    """
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    OPEN_G  = "var GOALS = ["
    CLOSE_G = "\n];\n\nvar currentFilter"

    gs = html.find(OPEN_G)
    ge = html.find(CLOSE_G, gs)
    if gs < 0 or ge < 0:
        print("  WARNING: GOALS array not found — skipping GOALS update")
        return

    gb = html[gs:ge]

    # Find current max goal id
    existing_ids = [int(x) for x in re.findall(r"\{id:(\d+),", gb)]
    next_gid = max(existing_ids) + 1 if existing_ids else 1

    # Find which matchIds already have goals
    present_matches = set(re.findall(r"matchId:'(m\d+)'", gb))

    # Find match id mapping from MATCH_STATS
    ms_start = html.find("var MATCH_STATS = {")
    ms_end   = html.find("\nfunction buildMatchSelector", ms_start)
    ms_block = html[ms_start:ms_end]
    match_nums = sorted(set(int(x) for x in re.findall(r"^\s*m(\d+)\s*:", ms_block, re.MULTILINE)))

    added_goals = 0
    for m in matches_api:
        home_name  = m["homeTeam"]["name"]
        away_name  = m["awayTeam"]["name"]
        home_score = m["score"]["fullTime"]["home"] or 0
        away_score = m["score"]["fullTime"]["away"] or 0
        total_goals = home_score + away_score

        if total_goals == 0:
            continue  # 0-0 match — no goals to add

        # Find the matchId for this match
        h_short = short(home_name)
        a_short = short(away_name)
        mid = None
        for k, v in [(f"home:'{h_short}',away:'{a_short}'", None)]:
            for num in match_nums:
                search = f"m{num}:"
                if search in ms_block:
                    entry_start = ms_block.find(search)
                    entry = ms_block[entry_start:entry_start+200]
                    if f"home:'{h_short}'" in entry and f"away:'{a_short}'" in entry:
                        mid = f"m{num}"
                        break
        if not mid:
            continue

        if mid in present_matches:
            continue  # Already have goals for this match

        # Add placeholder goal entries (one per goal, with unknown scorer)
        phase = f"Group {next(iter([t.get('group','?') for t in [m] if t.get('group')]), '?')}"
        utc = m.get("utcDate","")
        date_part = fmt_date(utc)

        # Try to get scorer data from API goals
        goals_data = m.get("goals", []) or []
        if goals_data:
            for gd in goals_data:
                scorer_name = (gd.get("scorer",{}) or {}).get("name","Unknown")
                team = (gd.get("team",{}) or {}).get("name", home_name)
                minute = gd.get("minute", 0) or 0
                gtype_raw = (gd.get("type") or "REGULAR").upper()
                gtype = "penalty" if gtype_raw=="PENALTY" else \
                        "own-goal" if gtype_raw=="OWN_GOAL" else \
                        "open-play"
                scorer_flag = flag(team)
                score_so_far = "?-?"  # hard to reconstruct incrementally

                line = (
                    f"\n  {{id:{next_gid}, matchId:'{mid}', "
                    f"home:'{h_short}', away:'{a_short}', "
                    f"hf:'{flag(home_name)}', af:'{flag(away_name)}', "
                    f"scorer:'{scorer_name}', flag:'{scorer_flag}', "
                    f"minute:{minute}, type:'{gtype}', "
                    f"phase:'Group ?', score:'{home_score}-{away_score}', "
                    f"desc:'{scorer_name} goal vs {a_short if team==home_name else h_short}'}},"
                )
                close_idx = gb.rfind("\n];")
                gb = gb[:close_idx] + line + gb[close_idx:]
                next_gid += 1
                added_goals += 1
        else:
            # No goal detail — add single placeholder
            line = (
                f"\n  {{id:{next_gid}, matchId:'{mid}', "
                f"home:'{h_short}', away:'{a_short}', "
                f"hf:'{flag(home_name)}', af:'{flag(away_name)}', "
                f"scorer:'See match report', flag:'{flag(home_name)}', "
                f"minute:45, type:'open-play', "
                f"phase:'Group ?', score:'{home_score}-{away_score}', "
                f"desc:'{h_short} {home_score}-{away_score} {a_short} — full match report on FIFA.com'}},"
            )
            close_idx = gb.rfind("\n];")
            gb = gb[:close_idx] + line + gb[close_idx:]
            next_gid += 1
            added_goals += 1

    if added_goals == 0:
        return

    html = html[:gs] + gb + html[ge:]
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  GOALS updated: {added_goals} new entries added")
