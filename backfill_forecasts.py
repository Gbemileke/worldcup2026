#!/usr/bin/env python3
"""
backfill_forecasts.py — freeze each knockout match's PRE-MATCH forecast.

WHY
---
The simulator computes forecasts live from TEAM_DATA.form / fifaPts. When a match
finishes and the pipeline recomputes form + FIFA, those inputs change, so the
"forecast" for the completed match is silently recomputed with POST-match numbers.
A prediction that shifts after the result is known cannot be verified.

This freezes the forecast that was standing at KICKOFF and stores it inside the
match's KNOCKOUT_RESULTS entry, so completed matches show the real prediction.

CORRECTNESS
-----------
Both moving inputs are reconstructed at their pre-match value:
  • FORM  — replayed as 0.4*qualBase + 0.6*mean(results BEFORE match N). Verified
            to reproduce every current stored form value to the decimal.
  • FIFA  — taken from update_rankings.compute_fifa_points(per_match_pre=…), i.e.
            YOUR OWN tested engine, captured before each match. Correct by
            construction — not a reimplementation.
Static inputs (elo, squad depth, qual, experience, marketPct) never change during
the tournament, so their current TEAM_DATA value IS the pre-match value.

The model math (teamScore / drawPct / logistic) is ported verbatim from index.html
so Python reproduces exactly what the browser would have shown.

Usage:
    python backfill_forecasts.py --dry-run     # print, write nothing
    python backfill_forecasts.py               # write forecasts into index.html
"""
import os, sys, re, math, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import update_rankings as UR

HTML_PATH = os.path.join(HERE, 'index.html')
DRY = '--dry-run' in sys.argv

# Model weights — the PREDICTOR set (PRED_W), matching index.html's predictor.
PRED_W = {'elo':0.20, 'form':0.35, 'qual':0.10, 'squad':0.15, 'fifa':0.15, 'exp':0.05}


def logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


# ─────────────────────────────────────────────────────────────────────────────
# Parse TEAM_DATA (static inputs) from index.html
# ─────────────────────────────────────────────────────────────────────────────
def parse_team_data(html):
    teams = {}
    i = html.find('var TEAM_DATA')
    j = html.find('};', i)
    block = html[i:j]
    for m in re.finditer(r"'([^']+)':\s*\{([^}]*)\}", block):
        name, body = m.group(1), m.group(2)
        def num(field, default=0.0):
            mm = re.search(rf"{field}:\s*(-?[0-9.]+)", body)
            return float(mm.group(1)) if mm else default
        teams[name] = {
            'elo': num('elo'), 'fifaPts': num('fifaPts'), 'form': num('form'),
            'squadDepth': num('squadDepth'), 'exp': num('exp'),
            'qualW': num('qualW'), 'qualD': num('qualD'), 'qualL': num('qualL'),
            'qualGF': num('qualGF'), 'qualGA': num('qualGA'),
            'marketPct': num('marketPct'),
        }
    return teams


def qual_gd_pg(t):
    if not t: return 0.0
    g = t.get('qualW',0) + t.get('qualD',0) + t.get('qualL',0)
    return (t.get('qualGF',0) - t.get('qualGA',0)) / g if g else 0.0


def qual_base(t):
    if not t:
        return None
    g = t.get('qualW', 0) + t.get('qualD', 0) + t.get('qualL', 0)
    return (t.get('qualW', 0) + 0.5*t.get('qualD', 0)) / g if g else None


# ─────────────────────────────────────────────────────────────────────────────
# Ordered results from the LIVE html (authoritative), with pso flags
# ─────────────────────────────────────────────────────────────────────────────
def ordered_results(html):
    NM = getattr(UR, 'NAME_MAP', {})
    nm = lambda x: NM.get(x, x)
    out = []

    i = html.find('var MATCHES'); j = html.find('\n];', i); mb = html[i:j]
    for m in re.finditer(r"\{[^{}]*\}", mb):
        e = m.group()
        idm = re.search(r"id:'?(m\d+)'?", e)
        h = re.search(r"home:'([^']*)'", e); a = re.search(r"away:'([^']*)'", e)
        s = re.search(r"score:'([^']*)'", e)
        if h and a and s and '-' in s.group(1):
            hh, aa = map(int, s.group(1).split('-'))
            res = 1.0 if hh > aa else (0.0 if hh < aa else 0.5)
            out.append({'id': idm.group(1) if idm else '', 'home': nm(h.group(1)),
                        'away': nm(a.group(1)), 'result': res, 'score': s.group(1),
                        'source': 'group', 'pso': False,
                        'rawHome': h.group(1), 'rawAway': a.group(1)})

    i = html.find('var KNOCKOUT_RESULTS'); j = html.find('\n};', i); kb = html[i:j]
    ko = []
    for m in re.finditer(r"(M\d+):\s*\{([^}]*)\}", kb):
        b = m.group(2)
        g = lambda k: (re.search(k+r":'([^']*)'", b).group(1)
                       if re.search(k+r":'([^']*)'", b) else '')
        ko.append((m.group(1), g('home'), g('away'), g('score'), g('winner'), bool(g('pens'))))
    ko.sort(key=lambda x: int(x[0][1:]))
    for mid, h, a, sc, w, pens in ko:
        hh, aa = map(int, sc.split('-'))
        res = 1.0 if hh > aa else (0.0 if hh < aa else 0.5)
        if pens:                                   # FIFA needs shootout winner's side
            res = 1.0 if nm(w) == nm(h) else 0.0
        out.append({'id': mid, 'home': nm(h), 'away': nm(a), 'result': res,
                    'score': sc, 'source': 'knockout', 'pso': pens,
                    'rawHome': h, 'rawAway': a, 'winner': w})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The model — ported verbatim from index.html's predictor
# ─────────────────────────────────────────────────────────────────────────────
def team_score(t):
    return (PRED_W['elo']  * (t['elo'] / 2200) +
            PRED_W['form'] * t['form'] +
            PRED_W['qual'] * min(1, max(0, (qual_gd_pg(t) + 3) / 6)) +
            PRED_W['squad']* (t['squadDepth'] / 100) +
            PRED_W['fifa'] * (t['fifaPts'] / 1900) +
            PRED_W['exp']  * (t['exp'] / 10))


def forecast(home_t, away_t):
    """Return the frozen forecast dict for one match, given pre-match team states."""
    sA, sB = team_score(home_t), team_score(away_t)
    elo_gap = abs(home_t['elo'] - away_t['elo'])
    draw_pct = max(0.12, 0.30 - elo_gap / 2800)
    raw = logistic((sA - sB) * 8)
    p_win  = round(raw * (1 - draw_pct) * 100)
    p_draw = round(draw_pct * 100)
    p_loss = 100 - p_win - p_draw

    # market (group-winner odds, normalised head-to-head) — display only
    sm = home_t['marketPct'] + away_t['marketPct']
    m_home = round(home_t['marketPct'] / sm * 100) if sm else 50
    m_away = 100 - m_home

    return {
        'modelHome': p_win, 'modelDraw': p_draw, 'modelAway': p_loss,
        'marketHome': m_home, 'marketAway': m_away,
        'formHome': round(home_t['form'], 3), 'formAway': round(away_t['form'], 3),
        'fifaHome': round(home_t['fifaPts'], 2), 'fifaAway': round(away_t['fifaPts'], 2),
    }


def main():
    html = open(HTML_PATH, encoding='utf-8').read()
    static = parse_team_data(html)
    results = ordered_results(html)
    NM = getattr(UR, 'NAME_MAP', {}); nm = lambda x: NM.get(x, x)

    # ---- FIFA: pre-match pts for every match, from YOUR engine fed by YOUR data ----
    # CRITICAL: feed compute_fifa_points() from load_verified_results() — the SAME
    # data/matches.json + data/knockout_results.json the live pipeline uses — NOT a
    # list re-parsed from index.html. Those two sources can differ subtly (name
    # normalisation, ordering), and even a ~1 pt drift means the frozen pre-match
    # FIFA won't reconcile with the team's own +delta. Using the pipeline's own
    # loader makes the pre-match pts identical to what produced the live values.
    #   (Verify: England pre-M99 must be 1889.42 - 18.03 = 1871.39.)
    fifa_results = UR.load_verified_results()
    per_match_pre = {}
    UR.compute_fifa_points(fifa_results, per_match_pre=per_match_pre)

    def resolve_static(raw):
        """Find a team's TEAM_DATA entry, tolerating name variants.

        KNOCKOUT_RESULTS abbreviates some names ('S. Africa') while TEAM_DATA uses
        the full form ('South Africa'). A miss here silently dropped M73 — the kind
        of quiet skip this project keeps getting bitten by. Try, in order: the raw
        name, the NAME_MAP-normalised name, then a de-abbreviated form.
        """
        if raw in static:
            return static[raw]
        n = nm(raw)
        if n in static:
            return static[n]
        exp = re.sub(r'^([A-Z])\.\s*', lambda m: {
            'S': 'South ', 'N': 'North ', 'C': 'Central ', 'W': 'West ', 'E': 'East ',
        }.get(m.group(1), m.group(1) + '. '), raw)
        if exp in static:
            return static[exp]
        tail = raw.split('.')[-1].strip().lower()
        for k in static:
            if tail and tail in k.lower():
                return static[k]
        return None

    # ---- FORM: replay running mean per team (pre-match) ----
    form_runal = {}          # team -> list of result points so far
    def form_before(team_raw):
        t = nm(team_raw)
        base = qual_base(resolve_static(team_raw))
        rl = form_runal.get(t, [])
        if base is None:
            st = resolve_static(team_raw) or {}
            return st.get('form', 0.5)                           # fallback: current
        if not rl:
            return round(max(0.10, base), 3)                    # no WC games yet
        avg = sum(rl) / len(rl)
        return round(max(0.10, base*0.4 + avg*0.6), 3)

    forecasts = {}
    missing_fifa = []
    skipped_names = []

    for r in results:
        mid = r['id']
        if r['source'] == 'knockout':
            hraw, araw = r['rawHome'], r['rawAway']
            hs, as_ = resolve_static(hraw), resolve_static(araw)
            if hs is None or as_ is None:
                miss = hraw if hs is None else araw
                skipped_names.append(f"{mid} ({miss})")
            else:
                ht, at = dict(hs), dict(as_)
                # inject PRE-MATCH form + FIFA
                ht['form'] = form_before(hraw); at['form'] = form_before(araw)
                pmp = per_match_pre.get(mid)
                if not pmp or 'home' not in pmp or 'away' not in pmp:
                    # No pre-match FIFA — do NOT silently fall back to current
                    # fifaPts (that freezes a POST-match value). Record it.
                    missing_fifa.append(mid)
                    ht['_fifa_ok'] = at['_fifa_ok'] = False
                else:
                    ht['fifaPts'] = pmp['home']
                    at['fifaPts'] = pmp['away']
                forecasts[mid] = forecast(ht, at)

        # advance the running form tally AFTER snapshotting (pso = draw for form)
        ph = 0.5 if r['pso'] else (1.0 if r['result']==1.0 else (0.5 if r['result']==0.5 else 0.0))
        pa = 0.5 if r['pso'] else (1.0-ph if r['result']!=0.5 else 0.5)
        form_runal.setdefault(nm(r['rawHome']), []).append(ph)
        form_runal.setdefault(nm(r['rawAway']), []).append(pa)

    if skipped_names:
        print(f"❌ {len(skipped_names)} knockout match(es) SKIPPED — team not found in "
              f"TEAM_DATA: {', '.join(skipped_names)}")
        print("   These have no forecast. Fix the name mapping and re-run.\n")

    print(f"Generated forecasts for {len(forecasts)} knockout matches\n")

    # ---- SELF-CHECK: frozen pre-match FIFA must reconcile with current − delta ----
    # Each team's TEAM_DATA carries fifaPts and fifaPtsDelta (points gained in its
    # LAST match). So for a team's last knockout match, the pre-match FIFA we froze
    # must equal fifaPts − fifaPtsDelta. If it doesn't, the FIFA source is wrong and
    # we must NOT write — a forecast that can't reconcile is exactly what we're here
    # to prevent.
    def td_pair(name):
        mm = re.search(rf"'{re.escape(name)}':\s*\{{[^}}]*?fifaPts:([0-9.]+)[^}}]*?fifaPtsDelta:(-?[0-9.]+)", html)
        return (float(mm.group(1)), float(mm.group(2))) if mm else (None, None)

    last_ko = {}   # team -> (mid, side) of its latest knockout match
    for r in results:
        if r['source'] == 'knockout':
            last_ko[nm(r['rawHome'])] = (r['id'], 'home')
            last_ko[nm(r['rawAway'])] = (r['id'], 'away')

    checked = mismatched = 0
    for team, (mid, side) in last_ko.items():
        cur, delta = td_pair(team)
        pmp = per_match_pre.get(mid, {})
        frozen = pmp.get(side)
        if cur is None or frozen is None:
            continue
        expected = round(cur - delta, 2)
        checked += 1
        if abs(frozen - expected) > 0.05:
            mismatched += 1
            print(f"  ⚠ {team:12} {mid}: frozen {frozen} != current−delta {expected} "
                  f"(off {frozen-expected:+.2f})")

    if checked:
        status = "✅ all reconcile" if not mismatched else f"❌ {mismatched}/{checked} MISMATCH"
        print(f"\nFIFA reconciliation ({checked} teams' last match): {status}")
        if mismatched and not DRY:
            print("  Refusing to write — FIFA source disagrees with live deltas.")
            print("  (Likely stale data/knockout_results.json — run in the real repo.)")
            return 1

    # ---- COVERAGE GATE: every knockout must have a REAL pre-match FIFA ----
    # A match missing from per_match_pre means the FIFA engine's data
    # (data/matches.json + data/knockout_results.json) doesn't cover it, so its
    # frozen FIFA is unreliable. Do not pass this off as valid.
    if missing_fifa:
        miss = ', '.join(sorted(missing_fifa, key=lambda x: int(x[1:])))
        print(f"\n❌ {len(missing_fifa)} match(es) have NO pre-match FIFA: {miss}")
        print("   The FIFA engine's data/ files don't cover these matches, so their")
        print("   frozen FIFA is NOT trustworthy. Fix the data and re-run.")
        if not DRY:
            print("   Refusing to write.")
            return 1
    else:
        print(f"✅ pre-match FIFA present for all {len(forecasts)} knockout matches")
    print()

    for mid in sorted(forecasts, key=lambda x: int(x[1:])):
        f = forecasts[mid]
        print(f"  {mid}: model {f['modelHome']}/{f['modelDraw']}/{f['modelAway']}  "
              f"market {f['marketHome']}/{f['marketAway']}  "
              f"form {f['formHome']}/{f['formAway']}  fifa {f['fifaHome']}/{f['fifaAway']}")

    if DRY:
        print("\n--dry-run: nothing written.")
        return 0

    # ---- write `forecast:{…}` into each KNOCKOUT_RESULTS entry ----
    i = html.find('var KNOCKOUT_RESULTS'); j = html.find('\n};', i)
    block = html[i:j]
    written = 0
    def add_forecast(m):
        nonlocal written
        mid, body = m.group(1), m.group(2)
        if mid not in forecasts or 'forecast:' in body:
            return m.group(0)
        f = forecasts[mid]
        fjson = ('forecast:{' +
                 f"modelHome:{f['modelHome']},modelDraw:{f['modelDraw']},modelAway:{f['modelAway']}," +
                 f"marketHome:{f['marketHome']},marketAway:{f['marketAway']}," +
                 f"formHome:{f['formHome']},formAway:{f['formAway']}," +
                 f"fifaHome:{f['fifaHome']},fifaAway:{f['fifaAway']}" + '}')
        written += 1
        return m.group(0)[:-1] + ', ' + fjson + '}'

    new_block = re.sub(r"(M\d+):\s*\{([^}]*)\}", add_forecast, block)
    html = html[:i] + new_block + html[j:]
    open(HTML_PATH, 'w', encoding='utf-8').write(html)
    print(f"\n✓ wrote forecast into {written} KNOCKOUT_RESULTS entries")
    return 0


if __name__ == '__main__':
    sys.exit(main())
