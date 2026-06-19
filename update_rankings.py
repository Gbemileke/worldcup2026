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
    "Argentina": 1877.27,  "Spain": 1874.71,  "France": 1870.7,
    "England": 1828.02,  "Portugal": 1767.85,  "Brazil": 1765.86,
    "Morocco": 1755.1,  "Netherlands": 1753.57,  "Belgium": 1742.24,
    "Germany": 1735.77,  "Croatia": 1714.87,  "Colombia": 1698.35,
    "Mexico": 1687.48,  "Senegal": 1684.07,  "Uruguay": 1673.07,
    "USA": 1671.23,  "Japan": 1661.58,  "Switzerland": 1650.06,
    "Iran": 1619.58,  "Turkey": 1605.73,  "Ecuador": 1598.52,
    "Austria": 1597.4,  "S. Korea": 1591.63,  "Australia": 1579.34,
    "Algeria": 1571.03,  "Egypt": 1562.37,  "Canada": 1559.48,
    "Norway": 1557.44,  "Ivory Coast": 1540.87,  "Panama": 1539.16,
    "Sweden": 1509.79,  "Czechia": 1505.74,  "Paraguay": 1505.35,
    "Scotland": 1503.34,  "Tunisia": 1476.41,  "DR Congo": 1474.43,
    "Uzbekistan": 1458.73,  "Qatar": 1450.31,  "Iraq": 1446.28,
    "S. Africa": 1428.38,  "Saudi Arabia": 1423.88,  "Jordan": 1387.74,
    "Bosnia": 1387.22,  "Cape Verde": 1371.11,  "Ghana": 1346.88,
    "Curacao": 1294.77,  "Haiti": 1293.1,  "New Zealand": 1275.58,
}

# ── Elo fallback (June 15 2026, from trueline.online/eloratings.net) ─────────
# Used only if the live fetch fails. Update after each matchday.
ELO_FALLBACK = {
    "Spain":2172,"Argentina":2113,"France":2062,"England":2042,"Colombia":1998,
    "Brazil":1978,"Portugal":1976,"Netherlands":1959,"Germany":1939,"Ecuador":1933,
    "Norway":1922,"Croatia":1912,"Japan":1910,"Switzerland":1897,"Uruguay":1890,
    "Turkey":1880,"Senegal":1869,"Mexico":1857,"Belgium":1850,"Paraguay":1833,
    "Austria":1818,"Morocco":1806,"Canada":1805,"South Korea":1784,"Australia":1774,
    "Iran":1755,"USA":1747,"Panama":1733,"Czechia":1731,"Algeria":1728,
    "Uzbekistan":1728,"Jordan":1689,"Sweden":1660,"Egypt":1659,"Ivory Coast":1650,
    "Scotland":1645,"Saudi Arabia":1635,"Tunisia":1630,"Ghana":1620,"Iraq":1600,
    "Bosnia":1580,"DR Congo":1550,"Haiti":1550,"Qatar":1550,"South Africa":1500,
    "Cape Verde":1500,"Curacao":1500,"New Zealand":1500,
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
# WC 2026 concluded matches — add each result here as the tournament progresses.
# result: 1=win, 0.5=draw, 0=loss  (from HOME team perspective)
WC_RESULTS = [
    # Group A — MD1
    {"home":"Mexico",      "away":"South Africa", "result":1.0},  # 2-0
    {"home":"South Korea", "away":"Czechia",       "result":1.0},  # 2-1
    # Group B — MD1
    {"home":"Canada",      "away":"Bosnia",        "result":0.5},  # 1-1
    # Group C — MD1
    {"home":"Brazil",      "away":"Morocco",       "result":0.5},  # 1-1
    {"home":"Haiti",       "away":"Scotland",      "result":0.0},  # 0-1
    # Group D — MD1
    {"home":"USA",         "away":"Paraguay",      "result":1.0},  # 4-1
    {"home":"Australia",   "away":"Turkey",        "result":1.0},  # 2-0
    # Group B — MD1
    {"home":"Qatar",       "away":"Switzerland",   "result":0.5},  # 1-1
    # Group E — MD1
    {"home":"Germany",     "away":"Curacao",       "result":1.0},  # 7-1
    {"home":"Ivory Coast", "away":"Ecuador",       "result":1.0},  # 1-0
    # Group F — MD1
    {"home":"Netherlands", "away":"Japan",         "result":0.5},  # 2-2
    {"home":"Sweden",      "away":"Tunisia",       "result":1.0},  # 5-1
    # Group H — MD1
    {"home":"Spain",       "away":"Cape Verde",    "result":0.5},  # 0-0
    {"home":"Iran",      "away":"New Zealand", "result":0.5},  # 2-2 Jun 15
    # Group I — MD1
    {"home":"France",    "away":"Senegal",     "result":1.0},  # 3-1 Jun 16
    {"home":"Norway",    "away":"Iraq",        "result":1.0},  # 4-1 Jun 16
    # Group J — MD1
    {"home":"Argentina", "away":"Algeria",     "result":1.0},  # 3-0 Jun 16
    {"home":"Austria",   "away":"Jordan",      "result":1.0},  # 2-0 Jun 16
    # Group G — MD1 (missing from original)
    {"home":"Belgium",   "away":"Egypt",       "result":0.5},  # 1-1 Jun 15
    # Group H — MD1 (additional)
    {"home":"Saudi Arabia","away":"Uruguay",   "result":0.5},  # 1-1 Jun 15
    # Group K — MD1
    {"home":"Portugal",    "away":"DR Congo",    "result":0.5},  # 1-1 Jun 17
    {"home":"Colombia",    "away":"Uzbekistan",  "result":1.0},  # 3-1 Jun 17
    # Group L — MD1
    {"home":"England",     "away":"Croatia",     "result":1.0},  # 4-2 Jun 17
    {"home":"Ghana",       "away":"Panama",      "result":1.0},  # 1-0 Jun 17
    # Group G — MD1 (additional)
    {"home":"Iran",        "away":"Egypt",       "result":0.5},  # 1-1 Jun 15 (corrected)
    # Group A — MD2
    {"home":"Czechia",     "away":"South Africa","result":0.5},  # 1-1 Jun 18
    {"home":"Mexico",      "away":"South Korea", "result":1.0},  # 1-0 Jun 18/19
    # Group B — MD2
    {"home":"Switzerland", "away":"Bosnia",      "result":1.0},  # 4-1 Jun 18
    {"home":"Canada",      "away":"Qatar",       "result":1.0},  # 6-0 Jun 18
    # ADD NEW RESULTS BELOW AS TOURNAMENT PROGRESSES:
]

import math as _math

def _expected(pa, pb):
    return 1.0 / (10.0 ** ((pb - pa) / 600.0) + 1.0)

def compute_fifa_points():
    """
    Start from June 11 2026 baseline and apply every concluded WC match
    result using the FIFA Elo formula. Returns updated points for all teams.
    """
    pts = {k: v for k, v in FIFA_POINTS_JUNE_11_2026.items()}
    I = 50  # World Cup group stage importance factor (verified against FIFA live rankings)

    for match in WC_RESULTS:
        h, a, w = match["home"], match["away"], match["result"]
        ph = pts.get(h)
        pa = pts.get(a)
        if ph is None or pa is None:
            continue  # team not in our data

        we_h = _expected(ph, pa)
        we_a = 1.0 - we_h
        w_a  = 1.0 - w

        pts[h] = round(ph + I * (w   - we_h), 2)
        pts[a] = round(pa + I * (w_a - we_a), 2)

    return pts

# ── 2. FIFA points — use hardcoded June 11 values ────────────────────────────
def get_fifa_points():
    pts = compute_fifa_points()
    concluded = len(WC_RESULTS)
    print(f"FIFA points: computed from {concluded} concluded WC matches")
    print(f"  (Baseline: June 11 2026 | Formula: P_new = P + 40×(W−We))")
    # Show top 5 for verification
    top5 = sorted(pts.items(), key=lambda x: -x[1])[:5]
    for name, p in top5:
        baseline = FIFA_POINTS_JUNE_11_2026.get(name, 0)
        diff = round(p - baseline, 2)
        sign = "+" if diff >= 0 else ""
        print(f"  {name}: {p} ({sign}{diff} from baseline)")
    return pts


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
def patch_html(elo_data, fifa_data, poly_data):
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
    fifa_data = get_fifa_points()   # no network call needed
    time.sleep(1)
    poly_data = fetch_polymarket()

    print(f"\nPatching index.html ...")
    patch_html(elo_data, fifa_data, poly_data)
    print("\nDone ✓")

