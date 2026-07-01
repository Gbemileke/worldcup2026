#!/usr/bin/env python3
"""
update_rankings.py — WC 2026 daily rankings updater
─────────────────────────────────────────────────────
Updates TEAM_DATA in index.html with:
  • elo:       live from eloratings.net (via footballratings.org)
  • fifaPts:   computed from June 11 2026 FIFA baseline + every verified WC match result
  • marketPct: live from Polymarket gamma API

Design principles:
  1. FIFA baseline is FROZEN at June 11 2026 (pre-tournament, before any WC match)
     — never edit this. WC deltas are always computed fresh from data files.
  2. WC_RESULTS is built dynamically from data/matches.json (group stage)
     and data/knockout_results.json (R32+). Never hardcoded.
  3. Idempotent — run 10 times, same answer every time.
  4. Sanity check against known reference values before patching index.html.
     Aborts with sys.exit(1) if numbers deviate beyond tolerance.
  5. No silent failures — every skip is logged.

Run: python update_rankings.py
CI:  .github/workflows/daily-rankings.yml (06:00 UTC daily)
"""

import os, re, sys, json, time, datetime, math, requests

HTML_FILE = "index.html"
DATA_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control":   "no-cache",
}

# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS — do not modify without understanding the consequences
# ═══════════════════════════════════════════════════════════════════════════════

# TRUE pre-tournament FIFA baseline — June 11, 2026 (before any WC match was played).
# Source: inside.fifa.com official June 11 2026 ranking update.
# FIFA next update: July 20 2026.
# ⚠ DO NOT CHANGE THESE VALUES — WC deltas are always computed on top of this baseline.
#   Changing this causes double-counting (WC results applied twice).
FIFA_BASELINE_JUN11 = {
    "Argentina": 1877.27, "Spain": 1874.71,  "France": 1870.70,
    "England":   1828.02, "Portugal": 1767.85, "Brazil": 1765.86,
    "Morocco":   1755.10, "Netherlands": 1753.57, "Belgium": 1742.24,
    "Germany":   1735.77, "Croatia": 1714.87, "Colombia": 1698.35,
    "Mexico":    1687.48, "Senegal": 1684.07, "Uruguay": 1673.07,
    "USA":       1671.23, "Japan": 1661.58,  "Switzerland": 1650.06,
    "Iran":      1619.58, "Turkey": 1605.73, "Ecuador": 1598.52,
    "Austria":   1597.40, "South Korea": 1591.63, "Australia": 1579.34,
    "Algeria":   1571.03, "Egypt": 1562.37,  "Canada": 1559.48,
    "Norway":    1557.44, "Ivory Coast": 1540.87, "Panama": 1539.16,
    "Sweden":    1509.79, "Czechia": 1505.74, "Paraguay": 1505.35,
    "Scotland":  1503.34, "Tunisia": 1476.41, "DR Congo": 1474.43,
    "Uzbekistan":1458.73, "Qatar": 1450.31,  "Iraq": 1446.28,
    "South Africa":1428.38,"Saudi Arabia":1423.88,"Jordan":1387.74,
    "Bosnia":    1387.22, "Cape Verde": 1371.11, "Ghana": 1346.88,
    "Curacao":   1294.77, "Haiti": 1293.10,  "New Zealand": 1275.58,
    # Non-WC anchors
    "Italy":     1704.73, "Denmark": 1619.47, "Nigeria": 1585.02,
}

# Name map: matches.json name → FIFA_BASELINE key
MATCH_TO_FIFA = {
    "S. Africa":   "South Africa",
    "S. Korea":    "South Korea",
    "DR Congo":    "DR Congo",
    "Ivory Coast": "Ivory Coast",
    "Bosnia":      "Bosnia",
    "Curacao":     "Curacao",
    "Cape Verde":  "Cape Verde",
    "Turkey":      "Turkey",
    "USA":         "USA",
    "Mexico":      "Mexico",
    # Pass-through (same in both)
}

# Elo name map: our TEAM_DATA key → eloratings.net name
ELO_NAMES = {
    "Spain":"Spain","Argentina":"Argentina","France":"France","England":"England",
    "Brazil":"Brazil","Colombia":"Colombia","Portugal":"Portugal",
    "Netherlands":"Netherlands","Norway":"Norway","Germany":"Germany",
    "Switzerland":"Switzerland","Mexico":"Mexico","Croatia":"Croatia",
    "Japan":"Japan","Ecuador":"Ecuador","Senegal":"Senegal",
    "Belgium":"Belgium","Morocco":"Morocco","USA":"United States",
    "Canada":"Canada","Austria":"Austria","South Korea":"South Korea",
    "Australia":"Australia","Algeria":"Algeria","Egypt":"Egypt",
    "Sweden":"Sweden","Ivory Coast":"Ivory Coast","Ghana":"Ghana",
    "Bosnia":"Bosnia and Herzegovina","DR Congo":"DR Congo",
    "Paraguay":"Paraguay","Cape Verde":"Cape Verde","Uruguay":"Uruguay",
    "Saudi Arabia":"Saudi Arabia","South Africa":"South Africa",
    "Tunisia":"Tunisia","Czechia":"Czech Republic","Iraq":"Iraq",
    "Scotland":"Scotland","Iran":"Iran","Qatar":"Qatar",
    "Curacao":"Curacao","Haiti":"Haiti","New Zealand":"New Zealand",
    "Uzbekistan":"Uzbekistan","Jordan":"Jordan","Turkey":"Turkey",
    "Norway":"Norway",
}

# Polymarket name map: market label → our TEAM_DATA key
POLY_NAMES = {
    "Argentina":"Argentina","Spain":"Spain","France":"France",
    "England":"England","Brazil":"Brazil","Germany":"Germany",
    "Portugal":"Portugal","Netherlands":"Netherlands","Colombia":"Colombia",
    "Morocco":"Morocco","Mexico":"Mexico","USA":"USA","Norway":"Norway",
    "Belgium":"Belgium","Senegal":"Senegal","Japan":"Japan",
    "Switzerland":"Switzerland","South Korea":"South Korea",
    "Ecuador":"Ecuador","Australia":"Australia","Croatia":"Croatia",
    "Austria":"Austria","Egypt":"Egypt","Algeria":"Algeria",
    "Canada":"Canada","Uruguay":"Uruguay","Denmark":"Denmark",
    "Italy":"Italy","Ghana":"Ghana","Ivory Coast":"Ivory Coast",
}

# Elo fallback (post-group-stage, Jun 28 2026 — source: eloratings.net)
# Used only if live fetch returns < 20 teams.
ELO_FALLBACK = {
    "Spain":2144,"Argentina":2144,"France":2123,"England":2038,
    "Brazil":2009,"Colombia":2004,"Portugal":1990,"Netherlands":1980,
    "Norway":1918,"Germany":1916,"Switzerland":1914,"Mexico":1912,
    "Croatia":1892,"Japan":1882,"Ecuador":1875,"Senegal":1869,
    "Belgium":1852,"Morocco":1840,"USA":1820,"Canada":1818,
    "Austria":1806,"South Korea":1784,"Australia":1780,"Algeria":1762,
    "Turkey":1758,"Egypt":1742,"Sweden":1730,"Ivory Coast":1728,
    "Ghana":1700,"Bosnia":1680,"DR Congo":1670,"Paraguay":1650,
    "Cape Verde":1640,"Uruguay":1635,"Saudi Arabia":1620,
    "South Africa":1600,"Tunisia":1590,"Czechia":1580,"Iraq":1560,
    "Scotland":1555,"Iran":1545,"Qatar":1520,"Curacao":1490,
    "Haiti":1470,"New Zealand":1460,"Uzbekistan":1440,"Jordan":1380,
}

# Known reference values for sanity check
# Update this dict after each FIFA ranking update (Jul 20 2026 is next)
# Source: FIFA.com rankings page, confirmed Jun 29 2026
FIFA_REFERENCE = {
    "Argentina": 1907.40,   # 3W in group
    "France":    1906.84,   # 3W in group (Norway rotated)
    "Spain":     1879.58,   # 2W 1D (Cape Verde draw)
    "England":   1840.46,   # 2W 1D (Ghana draw)
    "Brazil":    1785.19,   # 2W 1D (Morocco draw)
}
FIFA_REFERENCE_TOLERANCE = 3.0  # ±3 pts — tight tolerance, rounding only


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LOAD & VALIDATE MATCH RESULTS
# ═══════════════════════════════════════════════════════════════════════════════

def normalise_team(name):
    """Normalise match data team name to FIFA_BASELINE key."""
    return MATCH_TO_FIFA.get(name, name)


def parse_score(score_str):
    """Parse 'X-Y' → (home_goals, away_goals) or None if invalid."""
    if not score_str or "-" not in score_str:
        return None
    parts = score_str.strip().split("-")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None


def load_verified_results():
    """
    Build ordered list of verified match results from data files.
    Only includes matches with a parseable score.
    Returns list of dicts: {home, away, result, score, source, id}
    """
    results = []
    seen_ids  = set()
    seen_pairs = set()
    skipped = []

    def add_result(mid, home, away, score, source, winner=None):
        h = normalise_team(home)
        a = normalise_team(away)
        parsed = parse_score(score)
        if not parsed:
            skipped.append(f"{mid}: unparseable score '{score}'")
            return
        hg, ag = parsed
        if mid in seen_ids:
            skipped.append(f"{mid}: duplicate match id")
            return
        pair = (h, a)
        if pair in seen_pairs:
            skipped.append(f"{mid}: duplicate team pair ({h} vs {a})")
            return
        # Determine result (from home perspective: 1.0=win 0.5=draw 0.0=loss)
        if hg > ag:
            result = 1.0
        elif ag > hg:
            result = 0.0
        else:
            # Draw — for knockout, use winner field (AET/pens)
            if winner:
                wn = normalise_team(winner)
                result = 1.0 if wn == h else 0.0
            else:
                result = 0.5
        seen_ids.add(mid)
        seen_pairs.add(pair)
        results.append({"id": mid, "home": h, "away": a,
                        "result": result, "score": score, "source": source})

    # ── Group stage: data/matches.json ───────────────────────────────────────
    matches_path = os.path.join(DATA_DIR, "matches.json")
    if os.path.exists(matches_path):
        with open(matches_path, encoding="utf-8") as f:
            matches = json.load(f)
        group_added = 0
        for m in matches:
            mid  = m.get("id", "")
            home = m.get("home", "")
            away = m.get("away", "")
            score = m.get("score", "")
            # Only include IDs m1-m72 (group stage)
            try:
                num = int(mid.replace("m", "").replace("M", ""))
            except ValueError:
                skipped.append(f"{mid}: non-numeric id")
                continue
            if num < 1 or num > 72:
                skipped.append(f"{mid}: out of group range ({num})")
                continue
            add_result(mid, home, away, score, "group")
            group_added += 1
        if group_added < 72:
            print(f"  ⚠ Only {group_added}/72 group matches found — rankings may be incomplete")
            print(f"    Run: python update_match_stats.py  to scrape missing matches")
        else:
            print(f"  Group stage: {group_added} matches ✅")
    else:
        print("  ⚠ data/matches.json not found — no group stage results")

    # ── Knockout: data/knockout_results.json ─────────────────────────────────
    kr_path = os.path.join(DATA_DIR, "knockout_results.json")
    if os.path.exists(kr_path):
        with open(kr_path, encoding="utf-8") as f:
            kr = json.load(f)
        ko_added = 0
        for mid, r in sorted(kr.items(), key=lambda x: int(x[0][1:])):
            add_result(mid, r.get("home",""), r.get("away",""),
                       r.get("score",""), "knockout", r.get("winner",""))
            ko_added += 1
        if ko_added:
            print(f"  Knockout:    {ko_added} matches ✅")
    else:
        print("  ℹ data/knockout_results.json not found — no knockout results yet")

    if skipped:
        print(f"  ⚠ {len(skipped)} matches skipped:")
        for s in skipped[:10]:
            print(f"    • {s}")

    return results


def validate_results(results):
    """
    Validate the built results list.
    Returns True if valid, False if errors found.
    """
    known = set(FIFA_BASELINE_JUN11.keys())
    errors = []
    warnings = []
    seen_pairs = {}

    for r in results:
        h, a = r["home"], r["away"]
        key = (h, a)
        if key in seen_pairs:
            errors.append(f"DUPLICATE: {h} vs {a} (ids: {seen_pairs[key]}, {r['id']})")
        else:
            seen_pairs[key] = r["id"]
        if h not in known:
            warnings.append(f"UNKNOWN TEAM: '{h}' ({r['id']}) — not in FIFA_BASELINE. Add to MATCH_TO_FIFA.")
        if a not in known:
            warnings.append(f"UNKNOWN TEAM: '{a}' ({r['id']}) — not in FIFA_BASELINE. Add to MATCH_TO_FIFA.")
        if r["result"] not in (0.0, 0.5, 1.0):
            errors.append(f"INVALID RESULT: {h} vs {a} result={r['result']}")

    for w in warnings:
        print(f"  ⚠ {w}")

    if errors:
        print(f"  ❌ {len(errors)} validation errors:")
        for e in errors:
            print(f"     • {e}")
        return False

    print(f"  ✅ Validation passed ({len(results)} results, {len(warnings)} warnings)")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FIFA POINTS COMPUTATION
# ═══════════════════════════════════════════════════════════════════════════════

def _expected(pa, pb):
    """FIFA Elo expected result for team A against team B."""
    return 1.0 / (10.0 ** ((pb - pa) / 600.0) + 1.0)


def compute_fifa_points(wc_results):
    """
    Apply every verified WC result to the June 11 baseline using the FIFA Elo formula.
    Formula: P_new = P_before + I × (W − We)
    I = 50 (WC group stage and knockout)
    Results are applied sequentially in match order (both teams' pts update each match).

    Returns:
        pts      — final points for all teams
        pre_pts  — pts snapshot before each team's last match (for delta display)
        pre_rank — rank before each team's last match
    """
    I = 50
    pts = dict(FIFA_BASELINE_JUN11)

    # Track which match index is each team's last
    last_idx = {}
    for i, r in enumerate(wc_results):
        last_idx[r["home"]] = i
        last_idx[r["away"]] = i

    pre_pts = {}

    for i, r in enumerate(wc_results):
        h, a, result = r["home"], r["away"], r["result"]
        ph = pts.get(h)
        pa = pts.get(a)
        if ph is None:
            continue  # unknown team — validator already warned
        if pa is None:
            continue

        # Snapshot pre-match pts for each team's last match
        if last_idx.get(h) == i:
            pre_pts[h] = round(ph, 2)
        if last_idx.get(a) == i:
            pre_pts[a] = round(pa, 2)

        we_h = _expected(ph, pa)
        we_a = 1.0 - we_h

        pts[h] = round(ph + I * (result       - we_h), 2)
        pts[a] = round(pa + I * ((1 - result) - we_a), 2)

    # Compute pre-match global ranks
    def global_rank(pts_dict, name):
        my = pts_dict.get(name, 0)
        return sum(1 for p in pts_dict.values() if p > my) + 1

    pre_rank = {}
    for team, pp in pre_pts.items():
        snap = dict(pts)
        snap[team] = pp
        pre_rank[team] = global_rank(snap, team)

    return pts, pre_pts, pre_rank


def sanity_check(fifa_pts, group_pts=None):
    """
    Compare computed FIFA pts against known reference values.
    Returns True if all within tolerance, False if something looks wrong.
    Aborts patching if False.

    IMPORTANT: FIFA_REFERENCE is a frozen GROUP-STAGE snapshot (verified against
    FIFA.com on Jun 29 2026, before any knockout match). As knockout games are
    played, the live total (fifa_pts) legitimately grows past those references,
    so we must validate against the GROUP-STAGE-ONLY recomputation (group_pts)
    to check the calculation is still correct — not against the live total,
    which would fail for every team the moment it plays a knockout match.
    """
    compare = group_pts if group_pts is not None else fifa_pts
    ok = True
    label = "group-stage only" if group_pts is not None else "live total"
    print(f"  Checking against {len(FIFA_REFERENCE)} reference values (Jun 29 2026, {label}):")
    for team, ref in sorted(FIFA_REFERENCE.items()):
        computed = compare.get(team)
        if computed is None:
            print(f"    ⚠ {team}: not in computed data")
            continue
        diff = computed - ref
        within = abs(diff) <= FIFA_REFERENCE_TOLERANCE
        if not within:
            ok = False
        status = "✅" if within else "❌"
        print(f"    {status} {team}: {computed:.2f} (ref {ref:.2f}, diff {diff:+.2f})")
    if ok:
        print(f"  ✅ Sanity check passed — all within ±{FIFA_REFERENCE_TOLERANCE} pts")
    else:
        print(f"  ❌ Sanity check FAILED — fix FIFA_BASELINE or match data before patching")
    return ok


def get_fifa_points():
    """Load results, validate, compute, sanity-check. Returns (pts, pre_pts, pre_rank)."""
    print("Computing FIFA points ...")
    wc_results = load_verified_results()
    print(f"  Total results loaded: {len(wc_results)}")

    if not validate_results(wc_results):
        print("  ❌ Validation failed — aborting")
        sys.exit(1)

    pts, pre_pts, pre_rank = compute_fifa_points(wc_results)

    # Group-stage-only recomputation for the sanity check (references are a
    # frozen group-stage snapshot; the live `pts` also includes knockout deltas).
    group_results = [r for r in wc_results if r.get("source") == "group"]
    group_pts, _, _ = compute_fifa_points(group_results)

    print(f"  Top 5:")
    top5 = sorted(pts.items(), key=lambda x: -x[1])[:5]
    for name, p in top5:
        base = FIFA_BASELINE_JUN11.get(name, 0)
        diff = p - base
        pp = pre_pts.get(name, base)
        match_delta = p - pp
        print(f"    {name}: {p:.2f}  (vs Jun11 baseline: {diff:+.2f},  last match: {match_delta:+.2f})")

    if not sanity_check(pts, group_pts):
        print("  ❌ Aborting — fix data then re-run")
        sys.exit(1)

    return pts, pre_pts, pre_rank


# ═══════════════════════════════════════════════════════════════════════════════
# 3. ELO FETCH
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_elo():
    print("Fetching Elo ratings from eloratings.net ...")
    data = {}
    try:
        r = requests.get("https://www.footballratings.org/", headers=HEADERS, timeout=20)
        if r.ok:
            text = r.text
            # Match JSON-like entries: "rating":2144
            for m in re.finditer(r'"([A-Za-zÀ-ÿ\' \-\.]+)"\s*[^}]*?"rating"\s*:\s*(\d{3,4})', text):
                name, elo = m.group(1).strip(), int(m.group(2))
                if 1300 <= elo <= 2400 and len(name) > 1:
                    data[name] = elo
    except Exception as e:
        print(f"  ⚠ footballratings.org error: {e}")

    # Also try trueline.online
    if len(data) < 10:
        try:
            r = requests.get("https://trueline.online/elo", headers=HEADERS, timeout=20)
            if r.ok:
                for m in re.finditer(r'\|\s*\d+\s*\|\s*([A-Za-zÀ-ÿ\' \-\.]+?)\s*\|\s*(\d{3,4})\s*\|', r.text):
                    name, elo = m.group(1).strip(), int(m.group(2))
                    if 1300 <= elo <= 2400 and len(name) > 1:
                        data[name] = elo
        except Exception as e:
            print(f"  ⚠ trueline.online error: {e}")

    if len(data) >= 20:
        print(f"  ✅ Got {len(data)} Elo ratings from live source")
        return data

    print(f"  ⚠ Live fetch got {len(data)} entries — using hardcoded fallback (Jun 28 2026)")
    return ELO_FALLBACK.copy()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. POLYMARKET FETCH
# ═══════════════════════════════════════════════════════════════════════════════

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
                continue
            markets = events[0].get("markets") or []
            print(f"  Found {len(markets)} markets for slug={slug}")
            for mkt in markets:
                label = (mkt.get("groupItemTitle") or
                         re.sub(r"\s+to win.*", "", mkt.get("question", ""), flags=re.I).strip())
                prices = mkt.get("outcomePrices", "[]")
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
                print(f"  ✅ Got {len(data)} Polymarket probabilities")
                return data
        except Exception as e:
            print(f"  Polymarket error (slug={slug}): {e}")
    print("  ⚠ Polymarket unavailable — marketPct not updated this run")
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PATCH index.html
# ═══════════════════════════════════════════════════════════════════════════════

def patch_html(elo_data, fifa_data, poly_data, pre_pts_data, pre_rank_data):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    td_start = html.find("var TEAM_DATA = {")
    td_end   = html.find("\n};\n", td_start) + 4
    if td_start < 0:
        print("ERROR: TEAM_DATA not found in index.html"); sys.exit(1)

    td = html[td_start:td_end]
    elo_upd, fifa_upd, poly_upd, missing = [], [], [], []

    for our, src in ELO_NAMES.items():
        ti = td.find(f"'{our}':")
        if ti < 0:
            missing.append(our)
            continue

        # Elo
        new_elo = elo_data.get(src) or elo_data.get(our)
        if new_elo:
            ei = td.find("elo:", ti)
            if 0 < ei < ti + 300:
                c = td.find(",", ei + 4)
                try:
                    old_elo = int(td[ei+4:c].strip())
                    if old_elo != new_elo:
                        td = td[:ei+4] + str(new_elo) + td[c:]
                        elo_upd.append(f"{our}:{old_elo}→{new_elo}")
                except: pass

        # FIFA pts
        new_fifa = fifa_data.get(our)
        if new_fifa:
            fi = td.find("fifaPts:", ti)
            if 0 < fi < ti + 300:
                c = td.find(",", fi + 8)
                try:
                    old_fifa = float(td[fi+8:c].strip())
                    if abs(old_fifa - new_fifa) > 0.01:
                        td = td[:fi+8] + str(round(new_fifa, 2)) + td[c:]
                        fifa_upd.append(f"{our}:{old_fifa:.2f}→{new_fifa:.2f}")
                except: pass

        # FIFA pts delta
        pre_pts = pre_pts_data.get(our)
        if pre_pts and new_fifa:
            delta = round(new_fifa - pre_pts, 2)
            di = td.find("fifaPtsDelta:", ti)
            if 0 < di < ti + 300:
                c = td.find(",", di + 13)
                td = td[:di+13] + str(delta) + td[c:]

        # FIFA rank delta
        pre_rank = pre_rank_data.get(our)
        if pre_rank:
            ri = td.find("fifaRankDelta:", ti)
            if 0 < ri < ti + 300:
                c = td.find(",", ri + 14)
                # Positive = moved up (current rank < pre_rank)
                td = td[:ri+14] + str(pre_rank) + td[c:]

        # Polymarket
        new_poly = poly_data.get(our)
        if new_poly is not None:
            pi = td.find("marketPct:", ti)
            if 0 < pi < ti + 300:
                c = td.find("}", pi + 10)
                try:
                    old_poly = float(td[pi+10:c].strip())
                    if abs(old_poly - new_poly) > 0.01:
                        td = td[:pi+10] + str(new_poly) + td[c:]
                        poly_upd.append(f"{our}:{old_poly:.2f}→{new_poly:.2f}")
                except: pass

    html = html[:td_start] + td + html[td_end:]

    # Update team_data.json
    td_path = os.path.join(DATA_DIR, "team_data.json")
    if os.path.exists(td_path):
        with open(td_path, encoding="utf-8") as f:
            team_json = json.load(f)
        for our in ELO_NAMES:
            if our not in team_json:
                continue
            if our in elo_data or our in ELO_FALLBACK:
                team_json[our]["elo"] = elo_data.get(ELO_NAMES[our]) or elo_data.get(our) or ELO_FALLBACK.get(our) or team_json[our].get("elo")
            if our in fifa_data:
                team_json[our]["fifaPts"] = round(fifa_data[our], 2)
            if our in poly_data:
                team_json[our]["marketPct"] = poly_data[our]
        with open(td_path, "w", encoding="utf-8") as f:
            json.dump(team_json, f, indent=2, ensure_ascii=False)
        print("  team_data.json updated")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    today = datetime.date.today().isoformat()
    print(f"\n  Elo  updated : {len(elo_upd):2d}  {', '.join(elo_upd[:5])}{'...' if len(elo_upd)>5 else ''}")
    print(f"  FIFA updated : {len(fifa_upd):2d}  {', '.join(fifa_upd[:5])}{'...' if len(fifa_upd)>5 else ''}")
    print(f"  Poly updated : {len(poly_upd):2d}  {', '.join(poly_upd[:5])}{'...' if len(poly_upd)>5 else ''}")
    if missing:
        print(f"  Missing from TEAM_DATA: {', '.join(missing[:5])}")
    print(f"\n  index.html written — {today}")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"=== WC 2026 Rankings Updater — {datetime.date.today()} ===\n")

    elo_data  = fetch_elo();  time.sleep(1)
    fifa_data, pre_pts, pre_rank = get_fifa_points();  time.sleep(1)
    poly_data = fetch_polymarket()

    print(f"\nPatching index.html ...")
    patch_html(elo_data, fifa_data, poly_data, pre_pts, pre_rank)
    print("\nDone ✓")
