#!/usr/bin/env python3
"""
update_fifa.py — FIFA/Coca-Cola World Ranking updater (results-driven only).

WHY THIS EXISTS
    The FIFA ranking is the ONLY ranking that is derived from match results:
    every recorded result changes teams' FIFA points via the SUM formula. It
    must therefore refresh the moment a result is written — inside auto-update.yml,
    per match — not once a day.

    Elo and Polymarket odds are fetched from EXTERNAL sources (eloratings.net,
    gamma-api.polymarket.com); they are not computed from our results and belong
    on the daily schedule. Those stay in update_rankings.py / daily-rankings.yml.

    So this script updates ONLY the three FIFA fields — fifaPts, fifaPtsDelta,
    fifaRankDelta — and never touches elo or marketPct.

SINGLE SOURCE OF TRUTH
    The FIFA computation itself (baseline, SUM formula, PSO handling, knockout
    no-loss guard, validation, sanity check) lives in update_rankings.py. This
    script imports it — it does NOT re-implement the maths. It only owns the
    narrow job of patching the FIFA fields into index.html and team_data.json.

IDEMPOTENT
    get_fifa_points() rebuilds from the frozen Jun-11 baseline + all verified
    results every run, so running this after every match gives the same answer
    as running it once. Safe to call on every auto-update cycle.

USAGE
    python update_fifa.py            # compute + patch index.html & team_data.json
    python update_fifa.py --check    # compute + print, but do not write (dry run)
"""

import os
import re
import sys
import json
import datetime

# Import the FIFA machinery from update_rankings.py — one source of truth for
# the computation, validation, and sanity check.
import update_rankings as ur

HTML_FILE = ur.HTML_FILE
DATA_DIR  = ur.DATA_DIR


def patch_fifa_only(fifa_data, pre_pts_data, pre_rank_data, cur_rank_data, write=True):
    """Patch ONLY the FIFA fields into TEAM_DATA in index.html and team_data.json.

    Deliberately does not read or write elo / marketPct — those are owned by the
    daily updater. Each field is a targeted, in-place string replacement scoped
    to the team's own TEAM_DATA entry.
    """
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    td_start = html.find("var TEAM_DATA = {")
    td_end   = html.find("\n};\n", td_start) + 4
    if td_start < 0:
        print("ERROR: TEAM_DATA not found in index.html")
        sys.exit(1)

    td = html[td_start:td_end]
    fifa_upd = []

    # Iterate the known teams (same key set the daily updater uses).
    for our in ur.ELO_NAMES:
        ti = td.find(f"'{our}':")
        if ti < 0:
            continue

        new_fifa = fifa_data.get(our)

        # fifaPts
        if new_fifa is not None:
            fi = td.find("fifaPts:", ti)
            if 0 < fi < ti + 300:
                c = td.find(",", fi + 8)
                try:
                    old_fifa = float(td[fi+8:c].strip())
                    if abs(old_fifa - new_fifa) > 0.01:
                        td = td[:fi+8] + str(round(new_fifa, 2)) + td[c:]
                        fifa_upd.append(f"{our}:{old_fifa:.2f}->{new_fifa:.2f}")
                except ValueError:
                    pass

        # fifaPtsDelta (final - pre-match points; only for teams with a last-match snapshot)
        pre_pts = pre_pts_data.get(our)
        if pre_pts is not None and new_fifa is not None:
            delta = round(new_fifa - pre_pts, 2)
            di = td.find("fifaPtsDelta:", ti)
            if 0 < di < ti + 300:
                c = td.find(",", di + 13)
                td = td[:di+13] + str(delta) + td[c:]

        # fifaRankDelta (pre_rank - current_rank; positive = climbed)
        pre_rank = pre_rank_data.get(our)
        if pre_rank is not None:
            cur_rank = cur_rank_data.get(our, pre_rank)
            rank_delta = pre_rank - cur_rank
            ri = td.find("fifaRankDelta:", ti)
            if 0 < ri < ti + 300:
                c = td.find(",", ri + 14)
                td = td[:ri+14] + str(rank_delta) + td[c:]

    html = html[:td_start] + td + html[td_end:]

    # team_data.json — update ONLY fifaPts (leave elo / marketPct untouched).
    td_path = os.path.join(DATA_DIR, "team_data.json")
    if os.path.exists(td_path):
        with open(td_path, encoding="utf-8") as f:
            team_json = json.load(f)
        for our in ur.ELO_NAMES:
            if our in team_json and our in fifa_data:
                team_json[our]["fifaPts"] = round(fifa_data[our], 2)
        if write:
            with open(td_path, "w", encoding="utf-8") as f:
                json.dump(team_json, f, indent=2, ensure_ascii=False)
            print("  team_data.json fifaPts updated")

    if write:
        with open(HTML_FILE, "w", encoding="utf-8") as f:
            f.write(html)

    print(f"  FIFA pts updated: {len(fifa_upd):2d}  "
          f"{', '.join(fifa_upd[:5])}{'...' if len(fifa_upd) > 5 else ''}")
    return len(fifa_upd)


def main():
    dry = "--check" in sys.argv
    print(f"=== WC 2026 FIFA Ranking Updater (results-driven) — {datetime.date.today()} ===\n")

    # Compute FIFA points from verified results. get_fifa_points() runs the full
    # validation + sanity check and sys.exit(1)s on failure, so bad data never
    # gets patched.
    fifa_data, pre_pts, pre_rank, cur_rank = ur.get_fifa_points()

    print(f"\nPatching FIFA fields into index.html{' (dry run)' if dry else ''} ...")
    patch_fifa_only(fifa_data, pre_pts, pre_rank, cur_rank, write=not dry)
    print("\nDone ✓  (Elo and Polymarket odds are handled by the daily updater)")


if __name__ == "__main__":
    main()
