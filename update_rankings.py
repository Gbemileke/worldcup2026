#!/usr/bin/env python3
"""
update_rankings.py
──────────────────
Fetches today's World Football Elo ratings and FIFA ranking points
for all 48 World Cup 2026 teams, then patches index.html in-place.

Data sources:
  Elo  : footballratings.org  (mirrors eloratings.net, JSON-friendly)
  FIFA : football-data.org API v4  (free tier, requires FOOTBALL_DATA_TOKEN env var)

Run locally : python update_rankings.py
Run via CI  : triggered by .github/workflows/update-rankings.yml
"""

import os, re, sys, json, time, datetime, requests
from bs4 import BeautifulSoup

HTML_FILE = "index.html"

# ── Name mapping: our TEAM_DATA keys → names used in each external source ──────
# footballratings.org uses FIFA official names; we map them to our internal names.
ELO_NAME_MAP = {
    "Spain":               "Spain",
    "Argentina":           "Argentina",
    "France":              "France",
    "England":             "England",
    "Colombia":            "Colombia",
    "Brazil":              "Brazil",
    "Portugal":            "Portugal",
    "Netherlands":         "Netherlands",
    "Ecuador":             "Ecuador",
    "Croatia":             "Croatia",
    "Norway":              "Norway",
    "Germany":             "Germany",
    "Switzerland":         "Switzerland",
    "Uruguay":             "Uruguay",
    "Turkey":              "Türkiye",
    "Japan":               "Japan",
    "Senegal":             "Senegal",
    "Mexico":              "Mexico",
    "Belgium":             "Belgium",
    "Paraguay":            "Paraguay",
    "Austria":             "Austria",
    "Morocco":             "Morocco",
    "Canada":              "Canada",
    "South Korea":         "Korea Republic",
    "Australia":           "Australia",
    "Iran":                "IR Iran",
    "USA":                 "United States",
    "Panama":              "Panama",
    "Czechia":             "Czech Republic",
    "Algeria":             "Algeria",
    "Uzbekistan":          "Uzbekistan",
    "Jordan":              "Jordan",
    "Sweden":              "Sweden",
    "Egypt":               "Egypt",
    "Ivory Coast":         "Côte d'Ivoire",
    "Scotland":            "Scotland",
    "Saudi Arabia":        "Saudi Arabia",
    "Tunisia":             "Tunisia",
    "Ghana":               "Ghana",
    "Iraq":                "Iraq",
    "Bosnia":              "Bosnia and Herzegovina",
    "DR Congo":            "Congo DR",
    "Haiti":               "Haiti",
    "Qatar":               "Qatar",
    "South Africa":        "South Africa",
    "Cape Verde":          "Cabo Verde",
    "Curacao":             "Curaçao",
    "New Zealand":         "New Zealand",
}

# football-data.org team IDs for the WC competition (competition code WC)
# We map our internal names to their API team names for FIFA points lookup
FIFA_NAME_MAP = {
    "Spain":          "Spain",
    "Argentina":      "Argentina",
    "France":         "France",
    "England":        "England",
    "Colombia":       "Colombia",
    "Brazil":         "Brazil",
    "Portugal":       "Portugal",
    "Netherlands":    "Netherlands",
    "Ecuador":        "Ecuador",
    "Croatia":        "Croatia",
    "Norway":         "Norway",
    "Germany":        "Germany",
    "Switzerland":    "Switzerland",
    "Uruguay":        "Uruguay",
    "Turkey":         "Türkiye",
    "Japan":          "Japan",
    "Senegal":        "Senegal",
    "Mexico":         "Mexico",
    "Belgium":        "Belgium",
    "Paraguay":       "Paraguay",
    "Austria":        "Austria",
    "Morocco":        "Morocco",
    "Canada":         "Canada",
    "South Korea":    "Korea Republic",
    "Australia":      "Australia",
    "Iran":           "IR Iran",
    "USA":            "USA",
    "Panama":         "Panama",
    "Czechia":        "Czechia",
    "Algeria":        "Algeria",
    "Uzbekistan":     "Uzbekistan",
    "Jordan":         "Jordan",
    "Sweden":         "Sweden",
    "Egypt":          "Egypt",
    "Ivory Coast":    "Côte d'Ivoire",
    "Scotland":       "Scotland",
    "Saudi Arabia":   "Saudi Arabia",
    "Tunisia":        "Tunisia",
    "Ghana":          "Ghana",
    "Iraq":           "Iraq",
    "Bosnia":         "Bosnia and Herzegovina",
    "DR Congo":       "DR Congo",
    "Haiti":          "Haiti",
    "Qatar":          "Qatar",
    "South Africa":   "South Africa",
    "Cape Verde":     "Cape Verde",
    "Curacao":        "Curaçao",
    "New Zealand":    "New Zealand",
}


# ── Step 1: Fetch Elo ratings from footballratings.org ───────────────────────
def fetch_elo_ratings():
    """
    Scrapes footballratings.org which publishes eloratings.net data in HTML.
    Returns dict: {official_team_name: elo_int}
    """
    print("Fetching Elo ratings from footballratings.org ...")
    url = "https://www.footballratings.org/"
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "WC2026-updater/1.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"  WARNING: Elo fetch failed — {e}")
        return {}

    soup = BeautifulSoup(r.text, "lxml")
    elo_data = {}

    # The site renders teams in table rows with team name and rating
    # Pattern: look for rows containing rating numbers 1400–2300
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 3:
            name_cell = cells[0].get_text(strip=True)
            rating_cell = cells[1].get_text(strip=True)
            try:
                rating = int(rating_cell.replace(",", ""))
                if 1400 <= rating <= 2400 and name_cell:
                    elo_data[name_cell] = rating
            except ValueError:
                pass

    # Fallback: try JSON endpoint if available
    if not elo_data:
        try:
            jr = requests.get("https://www.footballratings.org/api/ratings",
                              timeout=10, headers={"User-Agent": "WC2026-updater/1.0"})
            if jr.status_code == 200:
                data = jr.json()
                for team in data:
                    if "name" in team and "rating" in team:
                        elo_data[team["name"]] = int(team["rating"])
        except Exception:
            pass

    print(f"  Got {len(elo_data)} Elo entries")
    return elo_data


# ── Step 2: Fetch FIFA ranking points via football-data.org ─────────────────
def fetch_fifa_rankings():
    """
    Uses the football-data.org API to get current FIFA ranking points
    for World Cup 2026 teams.
    Returns dict: {api_team_name: fifa_points_float}
    Requires FOOTBALL_DATA_TOKEN env var.
    """
    token = os.environ.get("FOOTBALL_DATA_TOKEN", "")
    if not token or token == "YOUR_API_TOKEN_HERE":
        print("  INFO: FOOTBALL_DATA_TOKEN not set — skipping FIFA points update")
        return {}

    print("Fetching FIFA ranking points from football-data.org ...")
    url = "https://api.football-data.org/v4/competitions/WC/teams"
    try:
        r = requests.get(url, timeout=15,
                         headers={"X-Auth-Token": token})
        if r.status_code == 403:
            print("  WARNING: API token invalid or expired")
            return {}
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  WARNING: FIFA fetch failed — {e}")
        return {}

    fifa_data = {}
    for team in data.get("teams", []):
        name = team.get("name") or team.get("shortName", "")
        pts  = team.get("fifaRankingPoints") or team.get("ranking", {}).get("points")
        if name and pts:
            try:
                fifa_data[name] = float(pts)
            except (ValueError, TypeError):
                pass

    print(f"  Got {len(fifa_data)} FIFA ranking entries")
    return fifa_data



# ── Step 3: Fetch Polymarket win probabilities ───────────────────────────────
POLYMARKET_SLUG = "which-country-will-win-the-2026-fifa-world-cup"

# Map Polymarket outcome labels → our TEAM_DATA keys
POLY_NAME_MAP = {
    "Spain":            "Spain",
    "Argentina":        "Argentina",
    "France":           "France",
    "England":          "England",
    "Colombia":         "Colombia",
    "Brazil":           "Brazil",
    "Portugal":         "Portugal",
    "Netherlands":      "Netherlands",
    "Germany":          "Germany",
    "Uruguay":          "Uruguay",
    "Morocco":          "Morocco",
    "Mexico":           "Mexico",
    "United States":    "USA",
    "USA":              "USA",
    "Belgium":          "Belgium",
    "Japan":            "Japan",
    "Ecuador":          "Ecuador",
    "Senegal":          "Senegal",
    "Norway":           "Norway",
    "Croatia":          "Croatia",
    "Switzerland":      "Switzerland",
    "Canada":           "Canada",
    "Korea Republic":   "South Korea",
    "South Korea":      "South Korea",
    "Australia":        "Australia",
    "Iran":             "Iran",
    "Turkey":           "Turkey",
    "Austria":          "Austria",
    "Sweden":           "Sweden",
    "Egypt":            "Egypt",
    "Algeria":          "Algeria",
    "Paraguay":         "Paraguay",
    "Ivory Coast":      "Ivory Coast",
    "Ghana":            "Ghana",
    "Panama":           "Panama",
    "Saudi Arabia":     "Saudi Arabia",
    "Scotland":         "Scotland",
    "Tunisia":          "Tunisia",
    "Uzbekistan":       "Uzbekistan",
    "Iraq":             "Iraq",
    "Jordan":           "Jordan",
    "Bosnia":           "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "DR Congo":         "DR Congo",
    "Congo DR":         "DR Congo",
    "Cape Verde":       "Cape Verde",
    "Haiti":            "Haiti",
    "Qatar":            "Qatar",
    "South Africa":     "South Africa",
    "New Zealand":      "New Zealand",
    "Curacao":          "Curacao",
    "Curaçao":          "Curacao",
}

def fetch_polymarket():
    """
    Fetches live tournament win probabilities from Polymarket's public API.
    Returns dict: {our_team_name: probability_pct_float}
    No API key needed — Polymarket data is public.
    """
    print("Fetching Polymarket probabilities ...")
    url = f"https://gamma-api.polymarket.com/markets?slug={POLYMARKET_SLUG}&limit=1"
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "WC2026-updater/1.0"})
        r.raise_for_status()
        markets = r.json()
        if not markets:
            raise ValueError("Empty response")
        market = markets[0]
        market_id = market.get("id") or market.get("conditionId")
    except Exception as e:
        print(f"  WARNING: Polymarket market lookup failed — {e}")
        return {}

    # Fetch order book to get current prices (= implied probabilities)
    try:
        r2 = requests.get(
            f"https://clob.polymarket.com/markets/{market_id}",
            timeout=15,
            headers={"User-Agent": "WC2026-updater/1.0"}
        )
        r2.raise_for_status()
        data = r2.json()
        tokens = data.get("tokens") or data.get("outcomes") or []
    except Exception:
        # Fallback: use outcomes from gamma API directly
        tokens = market.get("outcomes") or []
        outcomes_prices = market.get("outcomePrices") or []
        if isinstance(outcomes_prices, str):
            try:
                outcomes_prices = __import__("json").loads(outcomes_prices)
            except:
                outcomes_prices = []
        if tokens and outcomes_prices:
            result = {}
            for i, name in enumerate(tokens):
                our = POLY_NAME_MAP.get(name)
                if our and i < len(outcomes_prices):
                    try:
                        result[our] = round(float(outcomes_prices[i]) * 100, 2)
                    except:
                        pass
            print(f"  Got {len(result)} Polymarket entries (gamma fallback)")
            return result
        return {}

    result = {}
    for t in tokens:
        name  = t.get("outcome") or t.get("name") or t.get("token_id","")
        price = t.get("price") or t.get("midpoint") or t.get("lastPrice") or 0
        our   = POLY_NAME_MAP.get(name) or POLY_NAME_MAP.get(name.title())
        if our:
            try:
                pct = round(float(price) * 100, 2)
                result[our] = pct
            except:
                pass

    print(f"  Got {len(result)} Polymarket entries")
    return result

# ── Step 4: Patch index.html ─────────────────────────────────────────────────
def patch_html(elo_data, fifa_data, poly_data):
    """
    Reads index.html, updates elo: and fifaPts: values for each team,
    updates the last-updated comment, and writes the file back.
    """
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    # Find TEAM_DATA block
    td_start = html.find("var TEAM_DATA = {")
    td_end   = html.find("\n};\n", td_start) + 4
    if td_start < 0:
        print("ERROR: TEAM_DATA not found in HTML")
        sys.exit(1)

    td_block = html[td_start:td_end]
    td_new   = td_block

    elo_updated   = []
    fifa_updated  = []
    poly_updated  = []
    skipped       = []

    # Reverse map: official source name → our TEAM_DATA key
    elo_reverse  = {v: k for k, v in ELO_NAME_MAP.items()}
    fifa_reverse = {v: k for k, v in FIFA_NAME_MAP.items()}

    for our_name in ELO_NAME_MAP:
        # ── Update Elo ──
        official_elo_name = ELO_NAME_MAP[our_name]
        new_elo = elo_data.get(official_elo_name)
        if new_elo:
            team_idx = td_new.find(f"'{our_name}':")
            if team_idx >= 0:
                elo_idx = td_new.find("elo:", team_idx)
                if elo_idx >= 0 and elo_idx < team_idx + 300:
                    comma = td_new.find(",", elo_idx + 4)
                    old_elo = int(td_new[elo_idx+4:comma].strip())
                    if old_elo != new_elo:
                        td_new = td_new[:elo_idx+4] + str(new_elo) + td_new[comma:]
                        elo_updated.append(f"{our_name}: {old_elo}→{new_elo}")
        else:
            skipped.append(f"Elo/{our_name}")

        # ── Update Polymarket % ──
        new_poly = poly_data.get(our_name)
        if new_poly is not None:
            team_idx = td_new.find(f"\'{our_name}\':")
            if team_idx >= 0:
                mp_idx = td_new.find("marketPct:", team_idx)
                if mp_idx >= 0 and mp_idx < team_idx + 400:
                    comma = td_new.find("}", mp_idx + 10)
                    old_val_str = td_new[mp_idx+10:comma].strip().rstrip(",")
                    try:
                        old_poly = float(old_val_str)
                        if abs(old_poly - new_poly) >= 0.1:
                            td_new = td_new[:mp_idx+10] + f"{new_poly}" + td_new[mp_idx+10+len(old_val_str):]
                            poly_updated.append(f"{our_name}: {old_poly}→{new_poly}")
                    except:
                        pass

        # ── Update FIFA points ──
        official_fifa_name = FIFA_NAME_MAP.get(our_name)
        if official_fifa_name:
            new_fifa = fifa_data.get(official_fifa_name)
            if new_fifa:
                team_idx = td_new.find(f"'{our_name}':")
                if team_idx >= 0:
                    fp_idx = td_new.find("fifaPts:", team_idx)
                    if fp_idx >= 0 and fp_idx < team_idx + 300:
                        comma = td_new.find(",", fp_idx + 8)
                        old_fifa = int(td_new[fp_idx+8:comma].strip())
                        new_fifa_int = int(round(new_fifa))
                        if abs(old_fifa - new_fifa_int) > 1:
                            td_new = td_new[:fp_idx+8] + str(new_fifa_int) + td_new[comma:]
                            fifa_updated.append(f"{our_name}: {old_fifa}→{new_fifa_int}")

    # Rebuild HTML with updated TEAM_DATA
    html = html[:td_start] + td_new + html[td_end:]

    # Update the "last updated" comment/note if present
    today = datetime.date.today().strftime("%B %d, %Y")
    html = re.sub(
        r"(Elo ratings? updated?[^<\"']*)(June \d+, 2026|Updated \w+ \d+, \d{4})",
        r"\g<1>" + today,
        html
    )
    # Also update the src-note text
    html = re.sub(
        r"(eloratings\.net)[^<>·]*?(·|&middot;)",
        r"\1, " + today + r" \2",
        html, count=1
    )

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    if poly_updated:
        print(f"Polymarket updated ({len(poly_updated)} teams): {', '.join(poly_updated[:5])}" + ("..." if len(poly_updated) > 5 else ""))
    print(f"\nElo updated ({len(elo_updated)} teams): {', '.join(elo_updated[:5])}" +
          ("..." if len(elo_updated) > 5 else ""))
    print(f"FIFA updated ({len(fifa_updated)} teams): {', '.join(fifa_updated[:5])}" +
          ("..." if len(fifa_updated) > 5 else ""))
    if skipped:
        print(f"Skipped (source name not found): {', '.join(skipped[:5])}")
    print(f"\nindex.html updated — {today}")


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"=== WC 2026 Rankings Updater — {datetime.date.today()} ===\n")

    elo_data  = fetch_elo_ratings()
    fifa_data = fetch_fifa_rankings()
    poly_data = fetch_polymarket()

    if not elo_data and not fifa_data and not poly_data:
        print("No data fetched — exiting without changes")
        sys.exit(0)

    patch_html(elo_data, fifa_data, poly_data)
    print("\nDone ✓")
