#!/usr/bin/env python3
"""
add_result.py — Add a knockout result and deploy in one command.

Usage:
  python add_result.py M73 "S. Africa" Canada 1-3
  python add_result.py M74 Germany Paraguay 3-1
  python add_result.py M89 Canada Morocco 2-0

Arguments:
  1. Match ID   : M73 through M104
  2. Home team  : exact name (use quotes if spaces)
  3. Away team  : exact name
  4. Score      : home-away format e.g. 1-3

What it does automatically:
  1. Adds result to data/knockout_results.json
  2. Validates all data (goal balance, stats alignment, etc.)
  3. Updates index.html (KNOCKOUT_RESULTS + resolves upcoming fixtures)
  4. Commits and pushes to GitHub
"""

import sys, json, os, subprocess, re, datetime

# ── Parse args ────────────────────────────────────────────────────────────────
def usage():
    print(__doc__)
    sys.exit(1)

if len(sys.argv) < 5:
    usage()

match_id  = sys.argv[1].upper()          # e.g. M73
home_team = sys.argv[2]                  # e.g. S. Africa
away_team = sys.argv[3]                  # e.g. Canada
score     = sys.argv[4]                  # e.g. 1-3

# Validate inputs
if not re.match(r'^M\d+$', match_id):
    print(f"❌ Invalid match ID '{match_id}' — must be like M73, M89, M104")
    sys.exit(1)

if not re.match(r'^\d+-\d+$', score):
    print(f"❌ Invalid score '{score}' — must be like 1-3 or 2-0")
    sys.exit(1)

h_goals, a_goals = map(int, score.split('-'))
if h_goals > a_goals:
    winner = home_team
elif a_goals > h_goals:
    winner = away_team
else:
    # Draw — shouldn't happen in knockout, prompt
    print(f"⚠  Score is a draw ({score}). Knockout matches have extra time/penalties.")
    winner = input("  Enter the winner's name: ").strip()
    if not winner:
        print("❌ Winner required for knockout match"); sys.exit(1)

print(f"\n{'='*52}")
print(f"  Adding result: {match_id} — {home_team} {score} {away_team}")
print(f"  Winner: {winner}")
print(f"{'='*52}\n")

# ── Step 1: Update knockout_results.json ─────────────────────────────────────
KR_FILE = os.path.join('data', 'knockout_results.json')
os.makedirs('data', exist_ok=True)

try:
    with open(KR_FILE, encoding='utf-8') as f:
        kr = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    kr = {}

if match_id in kr:
    existing = kr[match_id]
    print(f"⚠  {match_id} already recorded: {existing['home']} {existing['score']} {existing['away']} → {existing['winner']}")
    confirm = input("  Overwrite? (y/N): ").strip().lower()
    if confirm != 'y':
        print("  Aborted."); sys.exit(0)

kr[match_id] = {
    "home":   home_team,
    "away":   away_team,
    "score":  score,
    "winner": winner
}

# Sort by match number
kr = dict(sorted(kr.items(), key=lambda x: int(x[0][1:])))

with open(KR_FILE, 'w', encoding='utf-8') as f:
    json.dump(kr, f, indent=2, ensure_ascii=False)

print(f"[ 1/4 ] ✅ {KR_FILE} updated ({len(kr)} results total)")

# ── Step 2: Validate ──────────────────────────────────────────────────────────
print(f"\n[ 2/4 ] Running validator...")
r = subprocess.run(
    [sys.executable, 'update_wc.py', '--section', 'validate'],
    capture_output=False, text=True
)
if r.returncode != 0:
    print("  ⚠  Validator had issues — review above before continuing")
    confirm = input("  Continue anyway? (y/N): ").strip().lower()
    if confirm != 'y':
        print("  Aborted — fix issues then re-run"); sys.exit(1)

# ── Step 3: Update site (knockout section) ───────────────────────────────────
print(f"\n[ 3/4 ] Updating index.html...")
r2 = subprocess.run(
    [sys.executable, 'update_wc.py', '--section', 'knockout'],
    capture_output=False, text=True
)
if r2.returncode != 0:
    print("❌ update_wc.py failed — aborting push"); sys.exit(1)

# ── Step 4: Git commit and push ───────────────────────────────────────────────
print(f"\n[ 4/4 ] Committing and pushing...")
msg = f"update: {match_id} — {home_team} {score} {away_team} (winner: {winner})"

cmds = [
    ['git', 'fetch', 'origin'],
    ['git', 'reset', '--soft', 'origin/main'],
    ['git', 'add', 'index.html', KR_FILE],
    ['git', 'commit', '-m', msg],
    ['git', 'push', 'origin', 'main'],
]

for cmd in cmds:
    r3 = subprocess.run(cmd, capture_output=True, text=True)
    label = ' '.join(cmd[:3])
    if r3.returncode != 0:
        # commit returns 1 if nothing to commit — that's fine
        if 'commit' in cmd and 'nothing to commit' in r3.stdout + r3.stderr:
            print(f"  ⚠  Nothing to commit (already up to date)")
        else:
            print(f"  ❌ {label} failed:\n{r3.stderr[:300]}")
            sys.exit(1)
    else:
        print(f"  ✅ {label}")

print(f"\n{'='*52}")
print(f"  🏆 DONE — {match_id} result live on GitHub Pages!")
print(f"     {home_team} {score} {away_team} → Winner: {winner}")
print(f"     https://gbemileke.github.io/worldcup2026/")
print(f"{'='*52}\n")

# ── Summary of remaining knockout fixtures ────────────────────────────────────
KNOCKOUT_IDS = [
    ('R32', [f'M{n}' for n in range(73, 89)]),
    ('R16', [f'M{n}' for n in range(89, 97)]),
    ('QF',  [f'M{n}' for n in range(97, 101)]),
    ('SF',  ['M101', 'M102']),
    ('3rd', ['M103']),
    ('Final', ['M104']),
]
remaining = []
for stage, ids in KNOCKOUT_IDS:
    for mid in ids:
        if mid not in kr:
            remaining.append((stage, mid))

if remaining:
    print(f"  Remaining fixtures ({len(remaining)}):")
    cur_stage = None
    for stage, mid in remaining[:8]:
        if stage != cur_stage:
            print(f"    {stage}:")
            cur_stage = stage
        print(f"      {mid}")
    if len(remaining) > 8:
        print(f"      ... and {len(remaining)-8} more")
else:
    print("  🏆 Tournament complete — all results recorded!")
