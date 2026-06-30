#!/usr/bin/env python3
"""
Scorer ↔ Country validator backed by the authoritative roster WC2026_Players.csv.

Unlike the history-based check in update_wc.py (which can only catch a player
mis-credited AFTER they've scored correctly before), this validator uses the
official squad roster, so it ALSO catches a brand-new scorer's first goal being
credited to the wrong country — e.g. K. Sano's goal credited to Brazil instead
of Japan, or a goal credited to a player who isn't on the named team at all.

Roster source: data/WC2026_Players.csv
  Columns used: COUNTRY and PLAYER_NAME (plus FIRST_NAME / LAST_NAME /
  NAME_ON_SHIRT when present, for more robust matching).
  The file may be comma- or tab-delimited; both are handled.

Goal source: data/goals.json
  Each goal's scorer is in "F. Lastname" form (e.g. "K. Sano", "A. Hakimi").
  The team a goal belongs to is derived from the running-score deltas.

ALL text comparisons are case-normalized and accent-insensitive.

Usage:
    python validate_scorer_country.py            # report only
    python validate_scorer_country.py --strict   # exit 1 if any mismatch (for CI)
"""

import csv, json, os, sys, unicodedata
from collections import defaultdict

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
ROSTER_CSV = os.path.join(DATA_DIR, 'WC2026_Players.csv')
GOALS_JSON = os.path.join(DATA_DIR, 'goals.json')


# ── Text normalization ───────────────────────────────────────────────────────
def norm(s):
    """Lowercase, strip accents/diacritics, collapse whitespace, drop punctuation
    except internal hyphens. Used for ALL comparisons so case never matters."""
    if s is None:
        return ''
    s = unicodedata.normalize('NFKD', str(s))
    s = ''.join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    # keep letters, digits, spaces, hyphens; turn everything else into space
    out = []
    for ch in s:
        if ch.isalnum() or ch in (' ', '-'):
            out.append(ch)
        else:
            out.append(' ')
    return ' '.join(''.join(out).split())


def norm_country(s):
    """Normalize country names so common variants collapse to one key."""
    n = norm(s)
    aliases = {
        'usa': 'usa', 'united states': 'usa', 'united states of america': 'usa',
        's korea': 'south korea', 'korea republic': 'south korea',
        'republic of korea': 'south korea', 'korea': 'south korea',
        's africa': 'south africa', 'rsa': 'south africa',
        'dr congo': 'dr congo', 'congo dr': 'dr congo',
        'democratic republic of congo': 'dr congo', 'drc': 'dr congo',
        'ivory coast': 'ivory coast', 'cote divoire': 'ivory coast',
        "cote d ivoire": 'ivory coast',
        'turkiye': 'turkiye', 'turkey': 'turkiye',
        'czechia': 'czechia', 'czech republic': 'czechia',
        'bosnia': 'bosnia', 'bosnia and herzegovina': 'bosnia',
        'bosnia herzegovina': 'bosnia',
        'cape verde': 'cape verde', 'cabo verde': 'cape verde',
        'curacao': 'curacao',
        'ir iran': 'iran', 'iran': 'iran',
        'korea dpr': 'north korea',
    }
    return aliases.get(n, n)


# ── Load roster ──────────────────────────────────────────────────────────────
def _open_text(path):
    """Open a text file trying common encodings (handles cp1252/latin-1 exports)."""
    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                f.read()
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return 'latin-1'  # last resort: never fails


def sniff_delimiter(path):
    enc = _open_text(path)
    with open(path, encoding=enc) as f:
        first = f.readline()
    # tab if header looks tab-separated, else comma
    return '\t' if first.count('\t') >= first.count(',') and '\t' in first else ','


def load_roster(path=ROSTER_CSV):
    """
    Returns:
      by_short   : { 'f. lastname' (normalized) -> set(country_keys) }
      by_last    : { 'lastname'    (normalized) -> set(country_keys) }
      by_shirt   : { name_on_shirt (normalized) -> set(country_keys) }
      country_display : { country_key -> original COUNTRY string }
    All keys are normalized (case/accent-insensitive).
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Roster not found at {path}. Place WC2026_Players.csv in the data/ folder."
        )
    delim = sniff_delimiter(path)
    enc = _open_text(path)
    by_short = defaultdict(set)
    by_last = defaultdict(set)
    by_shirt = defaultdict(set)
    country_display = {}

    with open(path, encoding=enc, newline='') as f:
        reader = csv.DictReader(f, delimiter=delim)
        # Normalize header names so we tolerate case/spacing in column titles
        field_map = {norm(h): h for h in (reader.fieldnames or [])}
        col_country = field_map.get('country')
        col_player = field_map.get('player name') or field_map.get('player_name') \
            or field_map.get('playername')
        col_first = field_map.get('first name') or field_map.get('first_name')
        col_last = field_map.get('last name') or field_map.get('last_name')
        col_shirt = field_map.get('name on shirt') or field_map.get('name_on_shirt')

        if not col_country or not col_player:
            raise ValueError(
                f"Roster must have COUNTRY and PLAYER_NAME columns. "
                f"Found: {reader.fieldnames}"
            )

        for row in reader:
            country_raw = (row.get(col_country) or '').strip()
            if not country_raw:
                continue
            ck = norm_country(country_raw)
            country_display.setdefault(ck, country_raw)

            player = (row.get(col_player) or '').strip()
            first = (row.get(col_first) or '').strip() if col_first else ''
            last = (row.get(col_last) or '').strip() if col_last else ''
            shirt = (row.get(col_shirt) or '').strip() if col_shirt else ''

            # Derive last name if not supplied
            if not last and player:
                last = player.split()[-1]
            if not first and player and len(player.split()) > 1:
                first = player.split()[0]

            # Index by "F. Lastname" (the goals.json convention).
            # Roster LAST_NAME is often compound (e.g. "VARGAS MARTINEZ",
            # "JIMENEZ RODRIGUEZ"), while goals.json uses a single common surname
            # ("R. Vargas", "R. Jiménez"). So index the short form against EACH
            # word of the surname, not just the whole thing.
            if first and last:
                fi = first[0]
                surname_words = last.split()
                # whole compound: "R. Vargas Martinez"
                by_short[norm(f"{fi}. {last}")].add(ck)
                # each word: "R. Vargas", "R. Martinez"
                for w in surname_words:
                    by_short[norm(f"{fi}. {w}")].add(ck)
                # also the LAST word alone (common Spanish/Portuguese paternal name)
                if surname_words:
                    by_short[norm(f"{fi}. {surname_words[0]}")].add(ck)
            # Index by bare last name AND each surname word (fallback)
            if last:
                by_last[norm(last)].add(ck)
                for w in last.split():
                    by_last[norm(w)].add(ck)
            # Index by name-on-shirt
            if shirt:
                by_shirt[norm(shirt)].add(ck)
                for w in shirt.split():
                    by_last[norm(w)].add(ck)
            # Also index full player name's last token
            if player:
                for w in player.split():
                    if not w.isupper() or len(w) > 2:  # skip codes
                        by_last[norm(w)].add(ck)

    return by_short, by_last, by_shirt, country_display


# ── Derive each goal's team from running score ───────────────────────────────
def derive_goal_teams(goals):
    """For each goal, figure out which team (home/away) scored it, using the
    running score. Returns list of (goal, scoring_country_raw)."""
    by_match = defaultdict(list)
    for g in goals:
        by_match[g['matchId']].append(g)

    out = []
    for mid, gs in by_match.items():
        gs = sorted(gs, key=lambda x: int(x.get('minute', 0)))
        ph = pa = 0
        for g in gs:
            try:
                h, a = map(int, str(g.get('score', '0-0')).split('-'))
            except ValueError:
                out.append((g, None))
                continue
            is_og = g.get('type') == 'own-goal'
            team = None
            if h > ph:
                team = g.get('away') if is_og else g.get('home')
            elif a > pa:
                team = g.get('home') if is_og else g.get('away')
            ph, pa = h, a
            out.append((g, team))
    return out


# ── Validate ─────────────────────────────────────────────────────────────────
def resolve_scorer_countries(scorer, by_short, by_last, by_shirt):
    """Return the set of country keys this scorer name maps to in the roster."""
    s = scorer.strip()
    if s.endswith(' OG'):
        s = s[:-3].strip()
    key = norm(s)

    # Explicit aliases for irreducible spelling differences between goals.json
    # and the roster (single-name stars, transliteration variants). Maps the
    # goals.json scorer (normalized) -> the roster country key directly.
    ALIASES = {
        'vinicius jr': 'brazil',
        'm al-taamari': 'jordan',   # roster shirt ALTAMARI / last SULEIMAN
    }
    if key in ALIASES:
        return {ALIASES[key]}

    def hyless(x):
        return x.replace('-', '').replace(' ', '')

    # 1. Exact "F. Lastname"
    if key in by_short:
        return by_short[key]
    # 2. Name-on-shirt (handles single-name stars & where surname differs from shirt)
    if key in by_shirt:
        return by_shirt[key]
    # 3. Last-name fallback (after "F. ")
    last = norm(s.split('. ')[-1]) if '. ' in s else key
    if last in by_last:
        return by_last[last]
    # 4. Hyphen/space-insensitive retry (Al-Amri vs ALAMRI, Al-Taamari vs ALTAMARI)
    hl_last = hyless(last)
    for k, v in by_last.items():
        if hyless(k) == hl_last:
            return v
    for k, v in by_shirt.items():
        if hyless(k) == hyless(key):
            return v
    # 5. Multi-word surname in goals (e.g. "Holmgren Pedersen"): try each word
    if '. ' in s:
        tail = s.split('. ', 1)[1]
        for w in tail.split():
            wk = norm(w)
            if wk in by_last:
                return by_last[wk]
            for k, v in by_last.items():
                if hyless(k) == hyless(wk):
                    return v
    return set()


def validate(roster_path=ROSTER_CSV, goals_path=GOALS_JSON):
    by_short, by_last, by_shirt, country_display = load_roster(roster_path)
    goals = json.load(open(goals_path, encoding='utf-8'))
    goal_teams = derive_goal_teams(goals)

    mismatches = []   # (matchId, scorer, credited_country, roster_countries)
    unmatched = []    # (matchId, scorer) — scorer not found in roster at all
    checked = 0

    for g, team_raw in goal_teams:
        scorer = (g.get('scorer') or '').strip()
        if not scorer or scorer.endswith(' OG') or g.get('type') == 'own-goal':
            continue  # own goals: scorer's country != scoring team by definition
        if not team_raw:
            continue
        checked += 1
        credited = norm_country(team_raw)
        roster_countries = resolve_scorer_countries(scorer, by_short, by_last, by_shirt)

        if not roster_countries:
            unmatched.append((g.get('matchId'), scorer))
        elif credited not in roster_countries:
            mismatches.append((
                g.get('matchId'), scorer,
                country_display.get(credited, team_raw),
                sorted(country_display.get(c, c) for c in roster_countries),
            ))

    return {
        'checked': checked,
        'mismatches': mismatches,
        'unmatched': unmatched,
        'roster_size': sum(len(v) for v in by_short.values()),
    }


def main():
    strict = '--strict' in sys.argv
    try:
        res = validate()
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        sys.exit(2)

    print("── Scorer ↔ Country validation (roster-backed) ──")
    print(f"   Roster: {os.path.basename(ROSTER_CSV)}")
    print(f"   Goals checked: {res['checked']}")

    if res['mismatches']:
        print(f"\n   ❌ {len(res['mismatches'])} COUNTRY MISMATCH(ES):")
        for mid, scorer, credited, roster_c in res['mismatches']:
            print(f"      {mid}: '{scorer}' credited to {credited}, "
                  f"but roster has them in {', '.join(roster_c)}")
    else:
        print("   ✅ No country mismatches")

    if res['unmatched']:
        print(f"\n   ⚠ {len(res['unmatched'])} scorer(s) not found in roster "
              f"(name spelling/format differences — review):")
        seen = set()
        for mid, scorer in res['unmatched']:
            if scorer not in seen:
                print(f"      {mid}: '{scorer}'")
                seen.add(scorer)

    ok = not res['mismatches']
    print(f"\n   {'✅ PASS' if ok else '❌ FAIL'}")
    if strict and not ok:
        sys.exit(1)


if __name__ == '__main__':
    main()
