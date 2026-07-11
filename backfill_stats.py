#!/usr/bin/env python3
"""
One-time corrective for match_stats.json. Does two things in a single ESPN pass:

  1. CORNERS — repairs matches whose 'Corner Kicks' were silently written as 0-0
     by the old name-matching bug in get_stat().
  2. PASSES ACCURACY — adds the new 'Passes Accuracy' row (a %), which no existing
     match has, because the scraper never requested passing data from ESPN at all.

WHY A BACKFILL IS NEEDED
------------------------
Fixing update_match_stats.py only affects FUTURE scrapes. Existing matches are
never revisited, because:
  * group stage : stats are re-fetched only when `mid not in stats` or the score
                  changed (update_match_stats.py) — neither is true.
  * knockout    : completed matches sit in LOCKED_MATCHES and the loop `continue`s
                  before it ever reaches the stats fetch.
So the bad 0-0 corners and the missing passing data are frozen. This goes and
gets them directly.

SAFETY
------
Surgical: only the 'Corner Kicks' and 'Passes Accuracy' rows are touched. Every
other stat (shots, fouls, saves, xG, cards, possession) is left byte-for-byte as
it is, so verified data cannot be clobbered. Corners are only overwritten when
they are currently 0-0 AND ESPN reports a real value.

Usage:
    python backfill_stats.py --dry-run     # report only, change nothing
    python backfill_stats.py               # apply

Then sync into the site:
    python update_wc.py --section stats --section snapshot
"""
import os, sys, json, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Reuse the scraper's own (fixed) fetch + parse logic — no duplicated ESPN code.
import update_match_stats as U

DATA_DIR   = os.path.join(HERE, 'data')
STATS_PATH = os.path.join(DATA_DIR, 'match_stats.json')

DRY = '--dry-run' in sys.argv

CORNERS = 'Corner Kicks'
PASSACC = 'Pass Accuracy'   # 5-element row: [name, hTot, aTot, hAcc%, aAcc%]


def row_of(entry, name):
    for r in entry.get('stats', []):
        if r and r[0] == name:
            return r
    return None


def set_row(entry, name, vals, after=None):
    """Update the row in place, or insert it (optionally after another row).

    `vals` is the list AFTER the name, so 2 elements for a normal stat
    ([home, away]) or 4 for Pass Accuracy ([hTot, aTot, hAcc%, aAcc%]).
    """
    stats = entry.setdefault('stats', [])
    for r in stats:
        if r and r[0] == name:
            r[1:] = list(vals)
            return
    idx = len(stats)
    if after:
        for i, rr in enumerate(stats):
            if rr and rr[0] == after:
                idx = i + 1
                break
    stats.insert(idx, [name] + list(vals))


def main():
    if not os.path.exists(STATS_PATH):
        print(f"✗ {STATS_PATH} not found"); return 1
    stats = json.load(open(STATS_PATH, encoding='utf-8'))

    need_corners = [m for m, e in stats.items()
                    if (row_of(e, CORNERS) or [None, 0, 0])[1:] == [0, 0]]
    need_passes  = [m for m, e in stats.items() if row_of(e, PASSACC) is None]
    todo = sorted(set(need_corners) | set(need_passes),
                  key=lambda x: int(''.join(c for c in x if c.isdigit())))

    print(f"Matches in file          : {len(stats)}")
    print(f"Need corners repaired    : {len(need_corners)}")
    print(f"Need Pass Accuracy       : {len(need_passes)}")
    print(f"Total to re-fetch        : {len(todo)}")
    if not todo:
        print("\n✓ Nothing to do.")
        return 0
    if DRY:
        print("\n--dry-run: no changes written.")
        return 0

    print("\nFetching ESPN scoreboard to resolve event IDs...")
    events = U.fetch_espn_scoreboard() or []
    if not events:
        print("✗ Could not fetch ESPN scoreboard — aborting (no changes made).")
        return 1

    by_pair = {}
    for ev in events:
        p = U.parse_espn_event(ev)
        if not p or not p.get('espn_id'):
            continue
        h, a = U.sn(p['home']), U.sn(p['away'])
        by_pair[f"{h}|{a}"] = p['espn_id']
        by_pair[f"{a}|{h}"] = p['espn_id']

    fixed_c = fixed_p = 0
    skipped = []

    for mid in todo:
        e = stats[mid]
        h, a = U.sn(e.get('home', '')), U.sn(e.get('away', ''))
        eid = by_pair.get(f"{h}|{a}")
        if not eid:
            skipped.append((mid, f"{h} v {a}", "no ESPN event id")); continue

        summary = U.fetch_espn_summary(eid)
        time.sleep(0.4)                      # be polite to ESPN
        if not summary:
            skipped.append((mid, f"{h} v {a}", "summary fetch failed")); continue

        parsed = U.parse_espn_stats(summary)
        if not parsed:
            skipped.append((mid, f"{h} v {a}", "no boxscore")); continue

        new = {r[0]: (r[1], r[2]) for r in parsed['stats'] if len(r) == 3}
        notes = []

        # --- corners: only overwrite a false 0-0, and only with a real value ---
        cur = row_of(e, CORNERS)
        if (cur or [None, 0, 0])[1:] == [0, 0]:
            nc = new.get(CORNERS)
            if nc and nc != (0, 0):
                set_row(e, CORNERS, [nc[0], nc[1]])
                fixed_c += 1
                notes.append(f"corners 0-0 → {nc[0]}-{nc[1]}")

        # --- pass accuracy: add if missing (5-element row) ---
        if row_of(e, PASSACC) is None:
            pr = next((r for r in parsed['stats'] if r[0] == PASSACC), None)
            if pr and len(pr) == 5 and (pr[1] or pr[2]):
                set_row(e, PASSACC, pr[1:], after='Shots on Goal')
                fixed_p += 1
                notes.append(f"pass acc {pr[1]} ({pr[3]}%) / {pr[2]} ({pr[4]}%)")

        if notes:
            print(f"  ✓ {mid:5} {h} v {a}: " + "; ".join(notes))
        else:
            skipped.append((mid, f"{h} v {a}", "ESPN had no usable values"))

    if fixed_c or fixed_p:
        with open(STATS_PATH, 'w', encoding='utf-8') as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)
        print(f"\n✓ corners repaired      : {fixed_c}")
        print(f"✓ pass accuracy added   : {fixed_p}")
        print(f"✓ wrote {STATS_PATH}")
        print("  Now run: python update_wc.py --section stats --section snapshot")
    else:
        print("\nNothing repaired; file unchanged.")

    if skipped:
        print(f"\n⚠ {len(skipped)} skipped:")
        for mid, fx, why in skipped:
            print(f"    {mid:5} {fx:28} {why}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
