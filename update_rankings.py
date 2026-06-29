import json
#!/usr/bin/env python3
"""
update_rankings.py  —  WC 2026 daily data updater
──────────────────────────────────────────────────
Updates TEAM_DATA in index.html with:
  • elo:       from trueline.online (mirrors eloratings.net) — updated after every match
  • fifaPts:   HARDCODED — FIFA rankings frozen until July 20 2026 (next update post-WC)
  • marketPct: from Polymarket gamma API — live tournament win probabilities

KEY FACTS:
  - FIFA rankings last updated: June 11 2026
  - FIFA rankings next update:  July 20 2026  (won't change during tournament)
  - Elo updates after every match (real-time)
  - Polymarket updates continuously (real money prediction market)

Run locally : python update_rankings.py
GitHub CI   : .github/workflows/update-rankings.yml  (runs daily 06:00 UTC)
"""

import os, re, sys, json, time, datetime, requests

HTML_FILE = "index.html"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control":   "no-cache",
}

# ── FIFA points: HARDCODED June 11 2026 (frozen until July 20 2026) ──────────
# Source: inside.fifa.com/fifa-world-ranking/men  — Official June 11 2026 update
# Argentina #1 (after pre-WC wins vs Iceland & Honduras), Spain #2, France #3
# These will NOT change until July 20 — no need to fetch them daily.
# Official FIFA rankings — June 11, 2026 (frozen until July 20, 2026)
# Official FIFA/Coca-Cola Men's World Ranking — June 11, 2026 (live, sourced from inside.fifa.com)
# Next update: July 20, 2026
FIFA_POINTS_JUNE_11_2026 = {
    # Post-group-stage estimates (base Jun 11 + WC group match delta)
    "Argentina": 1907.40,  "Spain": 1903.15,  "France": 1895.20,
    "England": 1828.02,  "Portugal": 1767.85,  "Brazil": 1765.86,
    "Morocco": 1755.1,  "Netherlands": 1753.57,  "Belgium": 1742.24,
    "Germany": 1735.77,  "Croatia": 1714.87,  "Colombia": 1698.35,
    "Mexico": 1687.48,  "Senegal": 1684.07,  "Uruguay": 1673.07,
    "USA": 1671.23,  "Japan": 1661.58,  "Switzerland": 1650.06,
    "Iran": 1619.58,  "Turkey": 1605.73,  "Ecuador": 1598.52,
    "Austria": 1597.4,  "South Korea": 1591.63,  "Australia": 1579.34,
    "Algeria": 1571.03,  "Egypt": 1562.37,  "Canada": 1559.48,
    "Norway": 1557.44,  "Ivory Coast": 1540.87,  "Panama": 1539.16,
    "Sweden": 1509.79,  "Czechia": 1505.74,  "Paraguay": 1505.35,
    "Scotland": 1503.34,  "Tunisia": 1476.41,  "DR Congo": 1474.43,
    "Uzbekistan": 1458.73,  "Qatar": 1450.31,  "Iraq": 1446.28,
    "South Africa": 1428.38,  "Saudi Arabia": 1423.88,  "Jordan": 1387.74,
    "Bosnia": 1387.22,  "Cape Verde": 1371.11,  "Ghana": 1346.88,
    "Curacao": 1294.77,  "Haiti": 1293.1,  "New Zealand": 1275.58,
    # Alias keys so validator finds them by both names
    "Bosnia and Herzegovina": 1387.22,
    "South Korea": 1591.63,
    "Congo DR": 1474.43,
    "Ivory Coast": 1540.87,
    "Cape Verde": 1371.11,
    # Non-WC teams kept as ranking anchors
    "Italy": 1704.73,  "Denmark": 1619.47,  "Nigeria": 1585.02,
}

# ── Elo fallback (June 15 2026, from trueline.online/eloratings.net) ─────────
# Used only if the live fetch fails. Update after each matchday.
ELO_FALLBACK = {
    # Updated Jun 28 2026 — post group stage (source: eloratings.net via footballratings.org)
    "Spain":2144,"Argentina":2144,"France":2123,"England":2038,"Brazil":2009,
    "Colombia":2004,"Portugal":1990,"Netherlands":1980,"Norway":1918,"Germany":1916,
    "Switzerland":1914,"Mexico":1912,"Croatia":1892,"Japan":1882,"Ecuador":1875,
    "Senegal":1869,"Belgium":1852,"Morocco":1840,"USA":1820,"Canada":1818,
    "Austria":1806,"South Korea":1784,"Australia":1780,"Algeria":1762,
    "Turkey":1758,"Egypt":1742,"Sweden":1730,"Ivory Coast":1728,"Ghana":1700,
    "Bosnia":1680,"DR Congo":1670,"Paraguay":1650,"Cape Verde":1640,
    "Uruguay":1635,"Saudi Arabia":1620,"South Africa":1600,"Tunisia":1590,
    "Czechia":1580,"Iraq":1560,"Scotland":1555,"Iran":1545,
    "Qatar":1520,"Curacao":1490,"Haiti":1470,"New Zealand":1460,
    "Uzbekistan":1440,"Jordan":1380,
}

# ── Source name maps ──────────────────────────────────────────────────────────
# Our TEAM_DATA key → how the source names the team
ELO_NAMES = {
    "Spain":"Spain","Argentina":"Argentina","France":"France","England":"England",
    "Colombia":"Colombia","Brazil":"Brazil","Portugal":"Portugal",
    "Netherlands":"Netherlands","Ecuador":"Ecuador","Croatia":"Croatia",
    "Norway":"Norway","Germany":"Germany","Switzerland":"Switzerland",
    "Uruguay":"Uruguay","Turkey":"Türkiye","Japan":"Japan","Senegal":"Senegal",
    "Mexico":"Mexico","Belgium":"Belgium","Paraguay":"Paraguay","Austria":"Austria",
    "Morocco":"Morocco","Canada":"Canada","South Korea":"Korea Republic",
    "Australia":"Australia","Iran":"IR Iran","USA":"United States",
    "Panama":"Panama","Czechia":"Czech Republic","Algeria":"Algeria",
    "Uzbekistan":"Uzbekistan","Jordan":"Jordan","Sweden":"Sweden","Egypt":"Egypt",
    "Ivory Coast":"Côte d'Ivoire","Scotland":"Scotland",
    "Saudi Arabia":"Saudi Arabia","Tunisia":"Tunisia","Ghana":"Ghana","Iraq":"Iraq",
    "Bosnia":"Bosnia-Herzegovina","DR Congo":"DR Congo","Haiti":"Haiti",
    "Qatar":"Qatar","South Africa":"South Africa","Cape Verde":"Cape Verde",
    "Curacao":"Curaçao","New Zealand":"New Zealand",
}

POLY_NAMES = {
    "Spain":"Spain","Argentina":"Argentina","France":"France","England":"England",
    "Colombia":"Colombia","Brazil":"Brazil","Portugal":"Portugal",
    "Netherlands":"Netherlands","Germany":"Germany","Uruguay":"Uruguay",
    "Morocco":"Morocco","Mexico":"Mexico","United States":"USA",
    "Belgium":"Belgium","Japan":"Japan","Ecuador":"Ecuador","Senegal":"Senegal",
    "Norway":"Norway","Croatia":"Croatia","Switzerland":"Switzerland",
    "Canada":"Canada","Korea Republic":"South Korea","South Korea":"South Korea",
    "Australia":"Australia","Iran":"Iran","Türkiye":"Turkey","Turkey":"Turkey",
    "Austria":"Austria","Sweden":"Sweden","Egypt":"Egypt","Algeria":"Algeria",
    "Paraguay":"Paraguay","Côte d'Ivoire":"Ivory Coast","Ivory Coast":"Ivory Coast",
    "Ghana":"Ghana","Panama":"Panama","Saudi Arabia":"Saudi Arabia",
    "Scotland":"Scotland","Tunisia":"Tunisia","Uzbekistan":"Uzbekistan",
    "Iraq":"Iraq","Jordan":"Jordan","Bosnia and Herzegovina":"Bosnia",
    "Bosnia-Herzegovina":"Bosnia","Congo DR":"DR Congo","DR Congo":"DR Congo",
    "Cape Verde":"Cape Verde","Cabo Verde":"Cape Verde","Haiti":"Haiti",
    "Qatar":"Qatar","South Africa":"South Africa","New Zealand":"New Zealand",
    "Curaçao":"Curacao","Curacao":"Curacao",
}


# ── 1. Elo — live from trueline.online, fallback to hardcoded ────────────────
def fetch_elo():
    print("Fetching Elo ratings from trueline.online ...")
    data = {}

    # Try trueline.online — plain HTML table, most reliable
    try:
        r = requests.get("https://trueline.online/elo", headers=HEADERS, timeout=20)
        if r.ok:
            text = r.text
            # Match markdown table rows: | N | Nation | ELO | Change |
            for m in re.finditer(
                r'\|\s*\d+\s*\|\s*([A-Za-zÀ-ÿ\' \-\.]+?)\s*\|\s*(\d{3,4})\s*\|',
                text
            ):
                name, elo = m.group(1).strip(), int(m.group(2))
                if 1300 <= elo <= 2400 and len(name) > 1:
                    data[name] = elo

            # Also try JSON blocks
            if len(data) < 10:
                for jblk in re.findall(r'\[[\s\S]*?\]', text):
                    try:
                        rows = json.loads(jblk)
                        if isinstance(rows, list) and len(rows) > 5:
                            for row in rows:
                                if isinstance(row, dict):
                                    name = row.get("name") or row.get("Nation","")
                                    elo  = row.get("rating") or row.get("ELO",0)
                                    try:
                                        elo = int(elo)
                                        if 1300 <= elo <= 2400 and name:
                                            data[name] = elo
                                    except: pass
                    except: pass
    except Exception as e:
        print(f"  trueline.online error: {e}")

    if len(data) >= 20:
        print(f"  ✓ Got {len(data)} Elo ratings from trueline.online")
        return data

    # Fallback
    print(f"  ⚠ Live fetch got only {len(data)} entries — using hardcoded fallback")
    print(f"    (Last updated: June 15 2026. Update ELO_FALLBACK after each matchday.)")
    return ELO_FALLBACK.copy()



# ── FIFA points calculator (Elo-based, post-2018 formula) ────────────────────
# Formula: P_new = P_before + I × (W − We)
# We = 1 / (10^(−Δr/600) + 1)
# Match importance I: WC group stage = 40, knockouts = 40 (FIFA uses same)
#
# ── WC Results: loaded dynamically from match data files (NOT hardcoded) ─────
# Ground truth sources:
#   Group stage:  data/matches.json       (written by update_match_stats.py)
#   Knockout:     data/knockout_results.json (written by add_result.py)
#
# RESULT_OVERRIDES: use only for AET/penalty winners where ESPN scores ties
# Format: {(home, away): result}  where result = 1.0 win / 0.5 draw / 0.0 loss
# (from HOME team perspective). These are applied AFTER the base result.
RESULT_OVERRIDES = {
    # Example: ("Team A", "Team B"): 1.0  # Team A won on pens after 1-1 AET
}

# Team name aliases: match data name → FIFA_POINTS_JUNE_11_2026 key
RESULT_NAME_MAP = {
    # Africa
    "S. Africa": "South Africa", "South Africa": "South Africa",
    "DR Congo": "Congo DR", "Congo DR": "Congo DR",
    "Ivory Coast": "Ivory Coast", "Côte d'Ivoire": "Ivory Coast",
    # Americas
    "Cape Verde": "Cape Verde", "Cabo Verde": "Cape Verde",
    "Bosnia": "Bosnia and Herzegovina",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "USA": "USA", "United States": "USA",
    # Asia
    "South Korea": "South Korea", "Korea Republic": "South Korea",
    "S. Korea": "South Korea",
    # Europe
    "Turkey": "Turkey", "Türkiye": "Turkey",
    "Curacao": "Curacao", "Curaçao": "Curacao",
    # Common mismatches
    "Netherlands": "Netherlands",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def load_verified_results():
    """
    Build WC_RESULTS dynamically from ground-truth data files.
    Only includes matches with a valid, parseable score.
    Returns list of {home, away, result} dicts.
    """
    results = []
    seen = set()

    def normalise(name):
        return RESULT_NAME_MAP.get(name, name)

    def parse_score(score_str):
        """Parse 'X-Y', return (home_goals, away_goals) or None if invalid."""
        if not score_str or "-" not in score_str:
            return None
        parts = score_str.strip().split("-")
        if len(parts) != 2:
            return None
        try:
            h, a = int(parts[0].strip()), int(parts[1].strip())
            return h, a
        except ValueError:
            return None

    def score_to_result(h_goals, a_goals, home_team, away_team):
        """Convert goal counts to Elo result (1.0/0.5/0.0 from home perspective)."""
        key = (normalise(home_team), normalise(away_team))
        rev_key = (normalise(away_team), normalise(home_team))
        # Check for override (AET/pens)
        if key in RESULT_OVERRIDES:
            return RESULT_OVERRIDES[key]
        if rev_key in RESULT_OVERRIDES:
            return 1.0 - RESULT_OVERRIDES[rev_key]
        if h_goals > a_goals:
            return 1.0
        elif a_goals > h_goals:
            return 0.0
        else:
            return 0.5

    # ── 1. Group stage: data/matches.json ────────────────────────────────────
    matches_path = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(matches_path):
        with open(matches_path, encoding="utf-8") as f:
            matches = json.load(f)
        for m in matches:
            home = normalise(m.get("home", ""))
            away = normalise(m.get("away", ""))
            score = m.get("score", "")
            mid = m.get("id", "")
            # Skip if not a group stage match or no valid score
            parsed = parse_score(score)
            if not parsed:
                continue
            # Skip knockout matches that may have been added to matches.json
            num = int(mid.replace("m","").replace("M","")) if mid else 0
            if num > 72:
                continue
            key = (home, away)
            if key in seen:
                continue
            seen.add(key)
            h_g, a_g = parsed
            result = score_to_result(h_g, a_g, home, away)
            results.append({"home": home, "away": away, "result": result,
                           "score": score, "source": "group", "id": mid})
    else:
        print("  WARNING: data/matches.json not found — group stage results missing")

    # ── 2. Knockout: data/knockout_results.json ───────────────────────────────
    kr_path = os.path.join(DATA_DIR, "knockout_results.json")
    if os.path.exists(kr_path):
        with open(kr_path, encoding="utf-8") as f:
            kr = json.load(f)
        for mid, r in sorted(kr.items(), key=lambda x: int(x[0][1:])):
            home = normalise(r.get("home", ""))
            away = normalise(r.get("away", ""))
            score = r.get("score", "")
            winner = r.get("winner", "")
            if not home or not away or not score:
                continue
            parsed = parse_score(score)
            if not parsed:
                continue
            key = (home, away)
            if key in seen:
                continue
            seen.add(key)
            h_g, a_g = parsed
            # If score is a draw (AET) and winner is recorded, use winner
            if h_g == a_g and winner:
                norm_winner = normalise(winner)
                result = 1.0 if norm_winner == home else 0.0
            else:
                result = score_to_result(h_g, a_g, home, away)
            results.append({"home": home, "away": away, "result": result,
                           "score": score, "source": "knockout", "id": mid})
    else:
        print("  INFO: data/knockout_results.json not found or empty — no knockout results yet")

    return results


def validate_wc_results(results):
    """
    Validate the built results list.
    Reports: missing scores, duplicate entries, unknown teams, suspicious results.
    """
    known_teams = set(FIFA_POINTS_JUNE_11_2026.keys())
    errors = []
    warnings = []
    seen = {}

    for r in results:
        h, a = r["home"], r["away"]
        key = (h, a)
        # Duplicate check
        if key in seen:
            errors.append(f"DUPLICATE: {h} vs {a} (ids: {seen[key]}, {r['id']})")
        else:
            seen[key] = r["id"]
        # Unknown team check
        if h not in known_teams:
            warnings.append(f"UNKNOWN HOME TEAM: '{h}' in {r['id']} — add to FIFA_POINTS or RESULT_NAME_MAP")
        if a not in known_teams:
            warnings.append(f"UNKNOWN AWAY TEAM: '{a}' in {r['id']} — add to FIFA_POINTS or RESULT_NAME_MAP")
        # Result sanity check
        if r["result"] not in (0.0, 0.5, 1.0):
            errors.append(f"INVALID RESULT: {h} vs {a} result={r['result']}")

    if errors:
        print(f"  ❌ {len(errors)} validation errors:")
        for e in errors: print(f"     • {e}")
    else:
        print(f"  ✅ No validation errors")

    if warnings:
        print(f"  ⚠  {len(warnings)} warnings:")
        for w in warnings: print(f"     • {w}")

    return len(errors) == 0


# ── Build WC_RESULTS at runtime (validated, not hardcoded) ───────────────────
WC_RESULTS = load_verified_results()


import math as _math

def _expected(pa, pb):
    return 1.0 / (10.0 ** ((pb - pa) / 600.0) + 1.0)

def compute_fifa_points():
    """
    Start from June 11 2026 baseline and apply every concluded WC match
    result using the FIFA Elo formula.
    Returns:
      pts        — current points for all teams
      pre_pts    — points BEFORE each team's last WC match (for delta display)
      pre_rank   — rank BEFORE each team's last WC match
    """
    pts = {k: v for k, v in FIFA_POINTS_JUNE_11_2026.items()}
    I = 50  # World Cup group stage importance factor (verified against FIFA live rankings)

    # Track the last match each team played
    last_match_idx = {}
    for i, match in enumerate(WC_RESULTS):
        last_match_idx[match["home"]] = i
        last_match_idx[match["away"]] = i

    # pre_pts[team] = pts snapshot just BEFORE that team's last match
    pre_pts = {}

    for i, match in enumerate(WC_RESULTS):
        h, a, w = match["home"], match["away"], match["result"]
        ph = pts.get(h)
        pa = pts.get(a)
        if ph is None or pa is None:
            continue

        # Snapshot pts before this match if it's the team's last one
        if last_match_idx.get(h) == i:
            pre_pts[h] = round(ph, 2)
        if last_match_idx.get(a) == i:
            pre_pts[a] = round(pa, 2)

        we_h = _expected(ph, pa)
        we_a = 1.0 - we_h
        w_a  = 1.0 - w

        pts[h] = round(ph + I * (w   - we_h), 2)
        pts[a] = round(pa + I * (w_a - we_a), 2)

    # Compute pre-match global ranks using pre_pts merged into full pts snapshot
    # For teams with no WC match yet, pre_pts = baseline
    def _global_rank(team_pts_dict, name):
        my_pts = team_pts_dict.get(name, 0)
        return sum(1 for p in team_pts_dict.values() if p > my_pts) + 1

    # Build pre-match pts dict: replace each team's pts with their pre-match snapshot
    pre_rank = {}
    for team, pp in pre_pts.items():
        # Build a snapshot: current pts for everyone EXCEPT this team uses pre_pts
        snap = dict(pts)
        snap[team] = pp
        pre_rank[team] = _global_rank(snap, team)

    return pts, pre_pts, pre_rank

# ── 2. FIFA points — use hardcoded June 11 values ────────────────────────────
def get_fifa_points():
    # Validate before computing
    print(f"  Loading match results from data files...")
    group_count = sum(1 for r in WC_RESULTS if r.get("source") == "group")
    ko_count    = sum(1 for r in WC_RESULTS if r.get("source") == "knockout")
    print(f"  Group stage: {group_count} results | Knockout: {ko_count} results")
    print(f"  Running validation...")
    valid = validate_wc_results(WC_RESULTS)
    if not valid:
        print("  ❌ Validation failed — aborting FIFA points calculation")
        import sys; sys.exit(1)
    pts, pre_pts, pre_rank = compute_fifa_points()
    concluded = len(WC_RESULTS)
    print(f"  FIFA points computed from {concluded} verified match results")
    print(f"  (Baseline: June 11 2026 | Formula: P_new = P + 50×(W−We))")
    top5 = sorted(pts.items(), key=lambda x: -x[1])[:5]
    for name, p in top5:
        baseline = FIFA_POINTS_JUNE_11_2026.get(name, 0)
        diff = round(p - baseline, 2)
        sign = "+" if diff >= 0 else ""
        print(f"    {name}: {p} ({sign}{diff} from Jun 11)")
    return pts, pre_pts, pre_rank


# ── 3. Polymarket — live from gamma API ──────────────────────────────────────
def fetch_polymarket():
    print("Fetching Polymarket probabilities ...")
    data = {}

    for slug in ["world-cup-winner", "2026-fifa-world-cup-winner-595"]:
        try:
            url = f"https://gamma-api.polymarket.com/events?slug={slug}&limit=1"
            r = requests.get(url, headers=HEADERS, timeout=20)
            if not r.ok:
                print(f"  HTTP {r.status_code} for slug={slug}")
                continue

            events = r.json()
            if not events:
                print(f"  Empty response for slug={slug}")
                continue

            markets = events[0].get("markets") or []
            print(f"  Found {len(markets)} markets for slug={slug}")

            for mkt in markets:
                label  = (mkt.get("groupItemTitle") or
                          re.sub(r"\s+to win.*", "", mkt.get("question",""), flags=re.I).strip())
                prices = mkt.get("outcomePrices","[]")
                if isinstance(prices, str):
                    try: prices = json.loads(prices)
                    except: prices = []
                if prices:
                    try:
                        yes_pct = round(float(prices[0]) * 100, 2)
                        our = POLY_NAMES.get(label)
                        if our:
                            data[our] = yes_pct
                    except: pass

            if data:
                print(f"  ✓ Got {len(data)} Polymarket probabilities")
                return data

        except Exception as e:
            print(f"  Polymarket error (slug={slug}): {e}")

    print("  ⚠ Polymarket unavailable — marketPct not updated this run")
    return {}


# ── 4. Patch index.html ───────────────────────────────────────────────────────
def patch_html(elo_data, fifa_data, poly_data, pre_pts_data=None, pre_rank_data=None):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    td_start = html.find("var TEAM_DATA = {")
    td_end   = html.find("\n};\n", td_start) + 4
    if td_start < 0:
        print("ERROR: TEAM_DATA not found"); sys.exit(1)

    td = html[td_start:td_end]
    elo_upd, fifa_upd, poly_upd, missing = [], [], [], []

    for our in ELO_NAMES:
        ti = td.find(f"'{our}':")
        if ti < 0:
            continue

        # ── Elo ──
        src  = ELO_NAMES[our]
        new  = elo_data.get(src) or elo_data.get(our)
        if new:
            ei = td.find("elo:", ti)
            if 0 < ei < ti + 300:
                c   = td.find(",", ei + 4)
                old = int(td[ei+4:c].strip())
                if old != int(new):
                    td = td[:ei+4] + str(int(new)) + td[c:]
                    elo_upd.append(f"{our}:{old}→{int(new)}")
        else:
            missing.append(our)

        # ── FIFA pts ──
        new_fifa = fifa_data.get(our)
        if new_fifa:
            fi = td.find("fifaPts:", ti)
            if 0 < fi < ti + 300:
                c   = td.find(",", fi + 8)
                old = float(td[fi+8:c].strip())
                nf  = round(new_fifa, 2)
                if abs(old - nf) > 0.1:        # update if any meaningful change
                    td = td[:fi+8] + str(nf) + td[c:]
                    fifa_upd.append(f"{our}:{old}→{nf}")

        # ── FIFA pts delta (change since last WC match) ──
        if pre_pts_data and pre_rank_data:
            pp = pre_pts_data.get(our)
            pr = pre_rank_data.get(our)
            if pp is not None and new_fifa is not None:
                pts_delta  = round(new_fifa - pp, 2)
                # Current global rank
                cur_rank   = sum(1 for v in fifa_data.values() if v > new_fifa) + 1
                rank_delta = (pr - cur_rank) if pr else 0  # positive = moved up
                # Write fifaPtsDelta
                di = td.find("fifaPtsDelta:", ti)
                if 0 < di < ti + 400:
                    dc = td.find(",", di + 13)
                    td = td[:di+13] + str(pts_delta) + td[dc:]
                # Write fifaRankDelta
                ri = td.find("fifaRankDelta:", ti)
                if 0 < ri < ri + 400:
                    rc = td.find(",", ri + 14)
                    td = td[:ri+14] + str(rank_delta) + td[rc:]

        # ── Polymarket ──
        new_poly = poly_data.get(our)
        if new_poly is not None:
            pi = td.find("marketPct:", ti)
            if 0 < pi < ti + 400:
                vs      = pi + 10
                ve      = td.find("}", vs)
                old_str = td[vs:ve].strip().rstrip(",")
                try:
                    old_p = float(old_str)
                    if abs(old_p - new_poly) >= 0.1:
                        td = td[:vs] + str(new_poly) + td[vs + len(old_str):]
                        poly_upd.append(f"{our}:{old_p}→{new_poly}")
                except: pass

    html = html[:td_start] + td + html[td_end:]

    # Safety brace check
    js = html[html.rfind('<script>') + len('<script>'):html.rfind('</script>')]
    o, c = js.count('{'), js.count('}')
    if o != c:
        print(f"SAFETY ABORT: brace mismatch {o}/{c} — file NOT written")
        sys.exit(1)

    # Save updated values to team_data.json to keep data/ in sync
    data_path = os.path.join("data", "team_data.json")
    if os.path.exists(data_path):
        with open(data_path) as f:
            team_json = json.load(f)
        for our in ELO_NAMES:
            if our not in team_json: continue
            src = ELO_NAMES[our]
            new_elo = elo_data.get(src) or elo_data.get(our)
            if new_elo:
                team_json[our]["elo"] = int(new_elo)
            new_fifa = fifa_data.get(our)
            if new_fifa:
                team_json[our]["fifaPts"] = round(new_fifa, 2)
            new_poly = poly_data.get(our)
            if new_poly is not None:
                team_json[our]["marketPct"] = new_poly
        with open(data_path, "w") as f:
            json.dump(team_json, f, indent=2)
        print("  team_data.json updated")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    today = datetime.date.today().isoformat()
    print(f"\n  Elo  updated : {len(elo_upd):2d}  {', '.join(elo_upd[:5])}{'...' if len(elo_upd)>5 else ''}")
    print(f"  FIFA updated : {len(fifa_upd):2d}  {', '.join(fifa_upd[:5])}{'...' if len(fifa_upd)>5 else ''}")
    print(f"  Poly updated : {len(poly_upd):2d}  {', '.join(poly_upd[:5])}{'...' if len(poly_upd)>5 else ''}")
    if missing:
        print(f"  Elo missing  : {', '.join(missing[:8])}")
    print(f"\n  index.html written — {today}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"=== WC 2026 Rankings Updater — {datetime.date.today()} ===\n")

    elo_data  = fetch_elo()
    time.sleep(1)
    fifa_data, pre_pts_data, pre_rank_data = get_fifa_points()   # no network call needed
    time.sleep(1)
    poly_data = fetch_polymarket()

    print(f"\nPatching index.html ...")
    patch_html(elo_data, fifa_data, poly_data, pre_pts_data, pre_rank_data)
    print("\nDone ✓")

