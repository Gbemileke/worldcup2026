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
    """Return the set of country keys this scorer name maps to in the roster.

    The roster contains EVERY registered player, so a scorer that fails to
    resolve is a name-normalization gap, not a missing player. The layered
    matching below is designed so that gap approaches zero without per-player
    aliases: exact short form, name-on-shirt, last-name, hyphen/space
    insensitivity, multi-word surnames, single-name/no-initial forms, and
    transliteration tolerance (collapsed doubled letters)."""
    s = scorer.strip()
    if s.endswith(' OG'):
        s = s[:-3].strip()
    key = norm(s)

    def hyless(x):
        return x.replace('-', '').replace(' ', '')

    def translit(x):
        # collapse doubled letters so transliteration variants align
        # (e.g. "altaamari" → "altamari", "mohammed"/"mohamed")
        x = hyless(x)
        out = []
        for ch in x:
            if not out or out[-1] != ch:
                out.append(ch)
        return ''.join(out)

    # 1. Exact "F. Lastname"
    if key in by_short:
        return by_short[key]
    # 2. Name-on-shirt (single-name stars, or where surname differs from shirt)
    if key in by_shirt:
        return by_shirt[key]
    # 3. Last-name fallback (token after "F. ")
    last = norm(s.split('. ')[-1]) if '. ' in s else key
    if last in by_last:
        return by_last[last]
    # 4. Hyphen/space-insensitive retry (Al-Amri vs ALAMRI)
    hl_last = hyless(last)
    for k, v in by_last.items():
        if hyless(k) == hl_last:
            return v
    for k, v in by_shirt.items():
        if hyless(k) == hyless(key):
            return v
    # 5. Try EVERY token of the scorer against the index — covers single-name /
    #    no-initial forms like "Vinicius Jr." (tokens: "vinicius", "jr") and
    #    "Trézéguet". Skip generic suffixes that aren't identifying.
    _SKIP = {'jr', 'jnr', 'junior', 'ii', 'iii', 'i', 'de', 'da', 'do', 'el', 'al'}
    tokens = [t for t in key.replace('.', ' ').split() if t and t not in _SKIP]
    # try longest, most-specific tokens first
    for t in sorted(tokens, key=len, reverse=True):
        if len(t) < 3:
            continue
        if t in by_last:
            return by_last[t]
        if t in by_shirt:
            return by_shirt[t]
    # 6. Transliteration tolerance: collapse doubled letters, hyphen/space-free.
    #    Resolves "Al-Taamari" (altaamari) → roster "ALTAMARI" (altamari).
    t_key = translit(key)
    for k, v in by_shirt.items():
        if translit(k) == t_key:
            return v
    for k, v in by_last.items():
        if translit(k) == t_key:
            return v
    for t in sorted(tokens, key=len, reverse=True):
        if len(t) < 4:
            continue
        tt = translit(t)
        for k, v in by_last.items():
            if translit(k) == tt:
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


def _official_finals(data_dir=DATA_DIR):
    """Load authoritative final scores keyed by matchId (lowercased).
    Group stage from matches.json, knockout from knockout_results.json.
    Used as a safety cross-check before applying any correction."""
    finals = {}
    for fname in ('matches.json', 'knockout_results.json'):
        p = os.path.join(data_dir, fname)
        if not os.path.exists(p):
            continue
        try:
            data = json.load(open(p, encoding='utf-8'))
        except Exception:
            continue
        items = data.values() if isinstance(data, dict) else data
        for it in items:
            mid = str(it.get('id') or it.get('matchId') or '').lower()
            # dict-keyed files (knockout_results) — key is the id
            if not mid and isinstance(data, dict):
                continue
            score = it.get('score', '')
            if mid and score and '-' in str(score):
                finals[mid] = score
        # knockout_results.json is keyed by matchId at the top level
        if isinstance(data, dict):
            for k, it in data.items():
                if isinstance(it, dict) and it.get('score'):
                    finals[k.lower()] = it['score']
    return finals


def correct_goals(roster_path=ROSTER_CSV, goals_path=GOALS_JSON, apply=False):
    """
    Use the authoritative roster to REBUILD each match's running scores from the
    scorers' true countries — correcting scraping inversions rather than merely
    flagging them.

    For every match, in minute order:
      • normal goal  → the scorer's OWN country's side increments
      • own goal     → the OTHER side increments (scorer concedes)
    A match is only corrected when it is SAFE to do so:
      • every scorer in the match resolves to exactly one roster country, and
      • every resolved country is one of the match's two teams, and
      • the rebuilt FINAL score matches the official final (matches.json /
        knockout_results.json) when that final is known.
    Matches that don't meet these are left untouched and reported for review.

    Returns a report dict. Writes goals.json only when apply=True.
    """
    by_short, by_last, by_shirt, country_display = load_roster(roster_path)
    goals = json.load(open(goals_path, encoding='utf-8'))
    finals = _official_finals()

    from collections import defaultdict
    by_match = defaultdict(list)
    order = {}
    for i, g in enumerate(goals):
        by_match[g['matchId']].append(g)
        order[id(g)] = i

    corrected_matches = []   # (matchId, [(scorer, old_score, new_score)])
    skipped = []             # (matchId, reason)

    for mid, gs in by_match.items():
        gs_sorted = sorted(gs, key=lambda x: int(x.get('minute', 0)))
        home = gs_sorted[0].get('home', '')
        away = gs_sorted[0].get('away', '')
        home_k, away_k = norm_country(home), norm_country(away)

        # Resolve every scorer's country; bail if any is unresolvable/ambiguous
        safe = True
        resolved = []  # (goal, country_key or None, is_og)
        for g in gs_sorted:
            scorer = (g.get('scorer') or '').strip()
            is_og = g.get('type') == 'own-goal' or scorer.endswith(' OG')
            countries = resolve_scorer_countries(scorer, by_short, by_last, by_shirt)
            ck = None
            if len(countries) == 1:
                ck = next(iter(countries))
            elif len(countries) > 1:
                # ambiguous: prefer one that is a team in THIS match
                inter = countries & {home_k, away_k}
                if len(inter) == 1:
                    ck = next(iter(inter))
            if ck is None or ck not in (home_k, away_k):
                safe = False
            resolved.append((g, ck, is_og))
        if not safe:
            skipped.append((mid, "unresolved/ambiguous scorer or country not in match"))
            continue

        # Rebuild running score by identity
        h = a = 0
        proposed = []
        for g, ck, is_og in resolved:
            if is_og:
                scoring_home = (ck == away_k)   # OG by away player → home scores
            else:
                scoring_home = (ck == home_k)
            if scoring_home: h += 1
            else:            a += 1
            proposed.append((g, f"{h}-{a}"))

        # Safety cross-check against official final, if known
        official = finals.get(mid.lower())
        if official:
            of = official.strip()
            if f"{h}-{a}" != of:
                skipped.append((mid, f"rebuilt final {h}-{a} != official {of}"))
                continue

        # Record changes
        changes = [(g['scorer'], g.get('score', ''), ns)
                   for g, ns in proposed if g.get('score', '') != ns]
        if changes:
            corrected_matches.append((mid, changes))
            if apply:
                for g, ns in proposed:
                    g['score'] = ns

    if apply and corrected_matches:
        json.dump(goals, open(goals_path, 'w', encoding='utf-8'),
                  indent=2, ensure_ascii=False)

    return {'corrected': corrected_matches, 'skipped': skipped, 'applied': apply}


def main():
    strict = '--strict' in sys.argv
    do_fix = '--fix' in sys.argv

    # ── Correction mode ───────────────────────────────────────────────────────
    if do_fix:
        try:
            rep = correct_goals(apply=True)
        except (FileNotFoundError, ValueError) as e:
            print(f"❌ {e}")
            sys.exit(2)
        print("── Roster-driven score correction ──")
        if rep['corrected']:
            print(f"   ✅ Corrected {len(rep['corrected'])} match(es):")
            for mid, changes in rep['corrected']:
                print(f"      {mid}:")
                for scorer, old, new in changes:
                    print(f"         {scorer}: {old} → {new}")
        else:
            print("   ✅ Nothing to correct — all running scores already match the roster")
        if rep['skipped']:
            print(f"\n   ⚠ {len(rep['skipped'])} match(es) left untouched (need review):")
            for mid, reason in rep['skipped']:
                print(f"      {mid}: {reason}")
        # After fixing, run a normal validation to confirm clean
        print()

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
        if not do_fix:
            print("\n   → run with --fix to auto-correct running scores from the roster")
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
