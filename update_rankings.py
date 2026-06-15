#!/usr/bin/env python3
"""
update_rankings.py  —  WC 2026 daily data updater
──────────────────────────────────────────────────
Updates in index.html:
  • elo:       from eloratings.net  (scraped via multiple fallbacks)
  • fifaPts:   from football-data.org API v4  (needs FOOTBALL_DATA_TOKEN)
  • marketPct: from Polymarket gamma API  (public, no key)

Run locally : python update_rankings.py
GitHub CI   : .github/workflows/update-rankings.yml  (runs daily at 06:00 UTC)
"""

import os, re, sys, json, time, datetime, requests

HTML_FILE = "index.html"

# ── Team name maps ────────────────────────────────────────────────────────────
# Keys = our TEAM_DATA names.  Values = what each external source calls them.
ELO_NAME_MAP = {
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
    "Ivory Coast":"Côte d'Ivoire","Scotland":"Scotland","Saudi Arabia":"Saudi Arabia",
    "Tunisia":"Tunisia","Ghana":"Ghana","Iraq":"Iraq",
    "Bosnia":"Bosnia-Herzegovina","DR Congo":"DR Congo","Haiti":"Haiti",
    "Qatar":"Qatar","South Africa":"South Africa","Cape Verde":"Cape Verde",
    "Curacao":"Curaçao","New Zealand":"New Zealand",
}

POLY_NAME_MAP = {
    "Spain":"Spain","Argentina":"Argentina","France":"France","England":"England",
    "Colombia":"Colombia","Brazil":"Brazil","Portugal":"Portugal",
    "Netherlands":"Netherlands","Germany":"Germany","Uruguay":"Uruguay",
    "Morocco":"Morocco","Mexico":"Mexico","United States":"USA","USA":"USA",
    "Belgium":"Belgium","Japan":"Japan","Ecuador":"Ecuador","Senegal":"Senegal",
    "Norway":"Norway","Croatia":"Croatia","Switzerland":"Switzerland",
    "Canada":"Canada","Korea Republic":"South Korea","South Korea":"South Korea",
    "Australia":"Australia","Iran":"Iran","Türkiye":"Turkey","Turkey":"Turkey",
    "Austria":"Austria","Sweden":"Sweden","Egypt":"Egypt","Algeria":"Algeria",
    "Paraguay":"Paraguay","Côte d'Ivoire":"Ivory Coast","Ivory Coast":"Ivory Coast",
    "Ghana":"Ghana","Panama":"Panama","Saudi Arabia":"Saudi Arabia",
    "Scotland":"Scotland","Tunisia":"Tunisia","Uzbekistan":"Uzbekistan",
    "Iraq":"Iraq","Jordan":"Jordan",
    "Bosnia and Herzegovina":"Bosnia","Bosnia-Herzegovina":"Bosnia",
    "Congo DR":"DR Congo","DR Congo":"DR Congo",
    "Cape Verde":"Cape Verde","Cabo Verde":"Cape Verde",
    "Haiti":"Haiti","Qatar":"Qatar","South Africa":"South Africa",
    "New Zealand":"New Zealand","Curaçao":"Curacao","Curacao":"Curacao",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
}


# ── 1. Elo — try three sources in order ───────────────────────────────────────
def fetch_elo_ratings():
    print("Fetching Elo ratings ...")

    # Source A: trueline.online (same data as eloratings.net, cleaner markup)
    result = _elo_from_trueline()
    if result:
        return result

    # Source B: eloratings.net direct (often JS-heavy but sometimes works)
    result = _elo_from_eloratings()
    if result:
        return result

    # Source C: footballratings.org JSON API
    result = _elo_from_footballratings_api()
    if result:
        return result

    print("  WARNING: all Elo sources failed — Elo will not be updated this run")
    return {}


def _elo_from_trueline():
    try:
        r = requests.get("https://trueline.online/elo", headers=HEADERS, timeout=20)
        if not r.ok:
            return {}
        text = r.text
        data = {}
        # Table rows:  | #  | Nation | ELO | Change |
        for m in re.finditer(
            r'\|\s*\d+\s*\|\s*([A-Za-zÀ-ÿ \'.\-]+?)\s*\|\s*(\d{4})\s*\|', text
        ):
            name, elo = m.group(1).strip(), int(m.group(2))
            if 1400 <= elo <= 2400:
                data[name] = elo
        # Also try JSON embedded in page
        for jm in re.findall(r'\{[^{}]*"rating"\s*:\s*(\d+)[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*\}', text):
            elo, name = int(jm[0]), jm[1]
            if 1400 <= elo <= 2400:
                data[name] = elo
        if data:
            print(f"  Got {len(data)} entries from trueline.online")
        return data
    except Exception as e:
        print(f"  trueline.online failed: {e}")
        return {}


def _elo_from_eloratings():
    try:
        r = requests.get("https://www.eloratings.net/World_Cup_2026",
                         headers=HEADERS, timeout=20)
        if not r.ok:
            return {}
        text = r.text
        data = {}
        # Try JSON in script tags
        for jblock in re.findall(r'<script[^>]*>(.*?)</script>', text, re.DOTALL):
            try:
                teams = json.loads(jblock.strip())
                if isinstance(teams, list):
                    for t in teams:
                        if "name" in t and "rating" in t:
                            data[t["name"]] = int(t["rating"])
            except:
                pass
        # Try TSV rows
        if not data:
            for line in text.split('\n'):
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    try:
                        elo = int(parts[1].replace(',',''))
                        if 1400 <= elo <= 2400:
                            data[parts[0].strip()] = elo
                    except:
                        pass
        if data:
            print(f"  Got {len(data)} entries from eloratings.net")
        return data
    except Exception as e:
        print(f"  eloratings.net failed: {e}")
        return {}


def _elo_from_footballratings_api():
    try:
        r = requests.get("https://www.footballratings.org/api/ratings",
                         headers=HEADERS, timeout=15)
        if not r.ok:
            return {}
        teams = r.json()
        data = {}
        for t in teams:
            name, elo = t.get("name",""), t.get("rating",0)
            try:
                elo = int(elo)
                if 1400 <= elo <= 2400 and name:
                    data[name] = elo
            except:
                pass
        if data:
            print(f"  Got {len(data)} entries from footballratings.org API")
        return data
    except Exception as e:
        print(f"  footballratings.org API failed: {e}")
        return {}


# ── 2. FIFA points — football-data.org ───────────────────────────────────────
def fetch_fifa_rankings():
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "")
    if not token or token == "YOUR_API_TOKEN_HERE":
        print("FIFA: FOOTBALL_DATA_TOKEN not set — skipping")
        return {}

    print("Fetching FIFA ranking points from football-data.org ...")
    h = {**HEADERS, "X-Auth-Token": token}
    try:
        r = requests.get("https://api.football-data.org/v4/competitions/WC/teams",
                         headers=h, timeout=15)
        if r.status_code == 403:
            print(f"  HTTP 403 — token may lack permission for this endpoint")
            return {}
        r.raise_for_status()
        data = {}
        for team in r.json().get("teams", []):
            name = team.get("name") or team.get("shortName","")
            pts  = (team.get("fifaRankingPoints") or
                    (team.get("ranking") or {}).get("points"))
            if name and pts:
                try: data[name] = float(pts)
                except: pass
        print(f"  Got {len(data)} FIFA entries")
        return data
    except Exception as e:
        print(f"  football-data.org failed: {e}")
        return {}


# ── 3. Polymarket ─────────────────────────────────────────────────────────────
def fetch_polymarket():
    print("Fetching Polymarket probabilities ...")
    url = "https://gamma-api.polymarket.com/events?slug=world-cup-winner&limit=1"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
        events = r.json()
        if not events:
            raise ValueError("empty")
    except Exception as e:
        print(f"  Polymarket gamma API failed: {e}")
        return {}

    markets = events[0].get("markets") or []
    result  = {}
    for mkt in markets:
        team_label = (mkt.get("groupItemTitle") or
                      re.sub(r" to win.*", "", mkt.get("question",""), flags=re.I).strip())
        prices = mkt.get("outcomePrices","[]")
        if isinstance(prices, str):
            try: prices = json.loads(prices)
            except: prices = []
        if prices:
            try:
                yes_pct = round(float(prices[0]) * 100, 2)
                our = POLY_NAME_MAP.get(team_label)
                if our:
                    result[our] = yes_pct
            except:
                pass

    print(f"  Got {len(result)} Polymarket entries")
    return result


# ── 4. Patch index.html ───────────────────────────────────────────────────────
def patch_html(elo_data, fifa_data, poly_data):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    td_start = html.find("var TEAM_DATA = {")
    td_end   = html.find("\n};\n", td_start) + 4
    if td_start < 0:
        print("ERROR: TEAM_DATA block not found"); sys.exit(1)

    td = html[td_start:td_end]
    elo_upd, fifa_upd, poly_upd, skipped = [], [], [], []

    for name in ELO_NAME_MAP:
        ti = td.find(f"'{name}':")
        if ti < 0:
            continue

        # Elo
        src_name = ELO_NAME_MAP[name]
        new_elo  = elo_data.get(src_name) or elo_data.get(name)
        if new_elo:
            ei = td.find("elo:", ti)
            if 0 < ei < ti + 300:
                c = td.find(",", ei+4)
                old = int(td[ei+4:c].strip())
                if old != new_elo:
                    td = td[:ei+4] + str(new_elo) + td[c:]
                    elo_upd.append(f"{name}: {old}→{new_elo}")
        else:
            skipped.append(name)

        # FIFA
        new_fifa = fifa_data.get(ELO_NAME_MAP.get(name, name)) or fifa_data.get(name)
        if new_fifa:
            fi = td.find("fifaPts:", ti)
            if 0 < fi < ti + 300:
                c = td.find(",", fi+8)
                old = int(td[fi+8:c].strip())
                nf  = int(round(new_fifa))
                if abs(old - nf) > 1:
                    td = td[:fi+8] + str(nf) + td[c:]
                    fifa_upd.append(f"{name}: {old}→{nf}")

        # Polymarket
        new_poly = poly_data.get(name)
        if new_poly is not None:
            pi = td.find("marketPct:", ti)
            if 0 < pi < ti + 400:
                vs = pi + 10
                ve = td.find("}", vs)
                old_str = td[vs:ve].strip().rstrip(",")
                try:
                    old_p = float(old_str)
                    if abs(old_p - new_poly) >= 0.1:
                        td = td[:vs] + str(new_poly) + td[vs+len(old_str):]
                        poly_upd.append(f"{name}: {old_p}→{new_poly}")
                except:
                    pass

    html = html[:td_start] + td + html[td_end:]

    # Safety check
    js_start = html.rfind('<script>') + len('<script>')
    js       = html[js_start:html.rfind('</script>')]
    if js.count('{') != js.count('}'):
        print(f"SAFETY ABORT: brace mismatch {js.count('{')} / {js.count('}')}")
        sys.exit(1)

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    today = datetime.date.today().isoformat()
    print(f"\nElo     updated: {len(elo_upd):2d} teams  — {', '.join(elo_upd[:4])}{'...' if len(elo_upd)>4 else ''}")
    print(f"FIFA    updated: {len(fifa_upd):2d} teams  — {', '.join(fifa_upd[:4])}{'...' if len(fifa_upd)>4 else ''}")
    print(f"Poly    updated: {len(poly_upd):2d} teams  — {', '.join(poly_upd[:4])}{'...' if len(poly_upd)>4 else ''}")
    if skipped:
        print(f"Skipped (no Elo source): {', '.join(skipped[:6])}{'...' if len(skipped)>6 else ''}")
    print(f"\nindex.html written — {today}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"=== WC 2026 Rankings Updater — {datetime.date.today()} ===\n")

    elo_data  = fetch_elo_ratings();  time.sleep(1)
    fifa_data = fetch_fifa_rankings(); time.sleep(1)
    poly_data = fetch_polymarket()

    if not elo_data and not fifa_data and not poly_data:
        print("\nNo data fetched from any source — exiting without changes")
        print("Check network access and API token in GitHub Secrets")
        sys.exit(0)

    patch_html(elo_data, fifa_data, poly_data)
    print("\nDone ✓")
