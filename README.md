# FIFA World Cup 2026 — Analytics Dashboard

Live analytics, interactive bracket simulator, and match statistics for the 2026 FIFA World Cup (USA · Canada · Mexico).

🌐 **Live site:** https://gbemileke.github.io/worldcup2026/
📁 **Repo:** https://github.com/gbemileke/worldcup2026

---

## What it does

A single-page app (~390KB, zero dependencies, zero frameworks) with six tabs:

| Tab | Content |
|---|---|
| **Highlights** | Live goal feed · filters by type/group · scorer hero panel · FIFA.com links |
| **Videos** | Match video cards linking to FIFA highlight pages |
| **Analytics** | snapshot cards (incl. penalties + all-time record tracker) · collapsible stage sections · match stats panel inside each section |
| **Simulator** | Model-driven R32→Final simulation · Top 4 bar · adjustable weights · quick presets · concluded matches show a frozen result with a **prediction right/wrong** banner |
| **Groups** | Match predictor with Consensus Pick · 12 group cards with live standings + qualification badges |
| **Bracket** | Interactive knockout bracket — pick every match, AI-fill, download PDF · **concluded matches are locked** to their real result (score shown, winner highlighted, uneditable) and their winner auto-advances |

---

## Current data state

| Metric | Value |
|---|---|
| Group stage matches | 72 / 72 complete (locked) |
| Match stats | 98 / 104 (72 group + 26 knockout) |
| Goals recorded | 285 (all balanced against scores) |
| Knockout results | R32 16/16 · R16 8/8 · QF 4/4 · **SF 1/2** (M101 played) |
| Penalty shootouts | 4 — M74 (Paraguay 4-3) · M75 (Morocco 3-2) · M88 (Egypt 4-2) · M96 (Switzerland 4-3). Stored as `pens`, shown as `(2) 1-1 (3)` everywhere |
| Frozen forecasts | 29 knockout matches carry a verified pre-match `forecast` block |
| Elo ratings | Post-group-stage (Jun 28 2026) — Spain/Argentina 2144, France 2123 |
| FIFA points | Jun 11 2026 baseline + WC delta |

### Knockout progress

| Round | Matches | Status |
|---|---|---|
| Round of 32 | M73–M88 | ✅ complete (locked 🔒) |
| Round of 16 | M89–M96 | ✅ complete (locked 🔒) |
| Quarter-finals | M97–M100 | ✅ complete |
| Semi-finals | M101–M102 | M101 France 0-2 Spain played · M102 pending |
| Third place / Final | M103 / M104 | M103 = France vs [M102 loser] · M104 = Spain vs [M102 winner] |

**Gone before the quarter-finals:** Brazil (beaten 2-1 by Norway), Germany, the Netherlands, Portugal, and **both host nations** — Canada (0-3 Morocco) and the USA (1-4 Belgium).

Rounds auto-**lock** once complete: the scraper never re-touches a finished match (score, goals, stats or kickoff time), and the Analytics tab shows a 🔒 on the round header.

---

## Repository structure

```
worldcup2026/
├── index.html                 ← Full app (~390KB single file)
├── update_wc.py               ← ONE-STOP update script (use this)
├── update_site.py             ← Lower-level HTML patcher (called by update_wc.py)
├── update_match_stats.py      ← ESPN scraper for scores / goals / stats (+ penalty shootouts)
├── update_rankings.py         ← Daily: Elo + Polymarket odds (+ FIFA) updater. `compute_fifa_points(per_match_pre=…)` captures pre-match FIFA for frozen forecasts
├── update_fifa.py             ← FIFA ranking only, results-driven (run per match)
├── add_result.py              ← Manual fallback: one command to record + deploy a result
├── validate_scorer_country.py ← Roster-backed scorer↔country validator (uses WC2026_Players.csv)
├── fix_rescrape_match.py       ← One-time helper: clear a match's goals for a clean re-scrape
├── backfill_stats.py          ← One-time corrective: repair corners + add Pass Accuracy to existing matches
├── backfill_forecasts.py      ← Freeze pre-match forecasts into KNOCKOUT_RESULTS (imports update_rankings.py; also invoked by update_wc.py --section forecast)
├── archive/
│   └── worldcup-goals.old.html ← Retired earlier single-file version (kept for reference)
└── data/
    ├── goals.json             ← 285 goals — scorer, minute, type, sequence
    ├── match_stats.json       ← Possession / shots / corners / Pass Accuracy / cards — 98 entries
    ├── knockout_results.json  ← R32→Final results (+ optional pens field) — ground truth
    ├── matches.json           ← 72 group stage matches + ESPN IDs (ground truth for rankings)
    ├── team_data.json         ← Elo, FIFA pts, form, qual record, squad depth (150 teams)
    ├── groups.json            ← 12 groups + Polymarket odds
    ├── upcoming_fixtures.json ← Authoritative kickoff times (ET) — synced into KICKOFF_TIMES
    └── WC2026_Players.csv     ← Official 48-squad roster (1248 players) — authoritative for the validator
```

---

## Two types of updates

### Type 1 — Automatic (GitHub Actions)

Polls **every 30 minutes** during tournament hours (plus a `*/6` safety net). It's result-driven, not clock-driven: the scraper only records matches ESPN marks completed, and the run pushes only when data changed — so the site updates shortly after each match concludes, with no timezone math.

```
ESPN scrape → auto-knockout → validate → goals → stats → knockout → FIFA ranking → upcoming → form → snapshot → stamp → push
```

The `auto-knockout` step reads `match_stats.json` for completed knockout scores and writes them to `knockout_results.json` automatically. Your manually recorded results are **never overwritten**. The `FIFA ranking` step runs `update_fifa.py` so FIFA points refresh in the same cycle a result is recorded (Elo + odds stay on the daily job).

### Type 2 — You (after each knockout match)

One command per match after it finishes:

```bash
python add_result.py M73 Canada "S. Africa" 1-0
```

Handles: draws (prompts for penalty winner), duplicate check, validate, update, push — all automatic.

---

## update_wc.py — sections

```bash
python update_wc.py                        # full update (all sections)
python update_wc.py --section validate     # 9 integrity checks + auto-fix
python update_wc.py --section auto-knockout # auto-populate from ESPN match_stats
python update_wc.py --section scrape       # fetch from ESPN
python update_wc.py --section goals        # goals.json → GOALS in index.html
python update_wc.py --section stats        # match_stats.json → MATCH_STATS
python update_wc.py --section knockout     # knockout_results.json → KNOCKOUT_RESULTS
python update_wc.py --section upcoming     # upcoming_fixtures.json → ticker
python update_wc.py --section forecast     # freeze pre-match forecasts (runs BEFORE form)
python update_wc.py --section form         # recompute team form from WC results
python update_wc.py --section snapshot     # update analytics header cards
python update_wc.py --section stamp        # refresh build timestamp

# Multiple sections work (and auto-sort into dependency order):
python update_wc.py --section stats --section snapshot
```

⚠️ **This used to silently fail.** The old parser read only `sys.argv[2]`, so `--section stats --section snapshot` ran **stats only** and quietly dropped `snapshot` — leaving the analytics cards stale with no warning. Fixed: every `--section` flag now runs, ordered so dependencies hold (`stats` always before `snapshot`).

---

## backfill_stats.py — one-time corrective

Fixing the scraper only helps **future** matches. Existing ones are never revisited: group-stage stats are re-fetched only when the match is new or the score changed, and completed knockout matches are locked. So bad data stays frozen.

```bash
python backfill_stats.py --dry-run     # report only
python backfill_stats.py               # repair data/match_stats.json
python update_wc.py --section stats --section snapshot
```

It re-fetches each affected match from ESPN and **surgically** writes only the `Corner Kicks` and `Pass Accuracy` rows — shots, fouls, saves, xG, cards and possession are left untouched. Corners are overwritten only where they're currently a false `0-0` **and** ESPN reports a real value.

**Order matters:** run the backfill *before* `--section snapshot`, or you bake the broken numbers into the Corner Kicks card.

---

## Frozen forecasts — verifiable pre-match predictions

**The problem it solves.** The simulator computes every forecast live from `TEAM_DATA.form` and `fifaPts`. When a match finishes and `--section form` / rankings recompute those, the "forecast" for the completed match was silently recomputed with **post-match** numbers — a prediction that shifts after the result is known, and can't be verified.

**The fix.** Each match's forecast is frozen at kickoff and stored inside its `KNOCKOUT_RESULTS` entry:

```js
M99: {home:'Norway', away:'England', score:'1-2', winner:'England',
      forecast:{modelHome:20, modelDraw:26, modelAway:54,
                marketHome:0, marketAway:100,
                formHome:0.847, formAway:0.94,
                fifaHome:1651.29, fifaAway:1871.39}}
```

Completed matches display this frozen forecast (bars don't move on Re-Simulate); upcoming matches compute live.

### Three files work together

| File | Role |
|---|---|
| `update_rankings.py` | Extended with a `per_match_pre` parameter that captures each match's **pre-match** FIFA points from the existing engine — correct by construction, no reconstruction. |
| `backfill_forecasts.py` | Generates frozen forecasts for all played knockouts. Form is replayed (`0.4×qual + 0.6×WC-so-far`); FIFA comes from the instrumented engine. Two gates below. |
| `index.html` | `frozenForecast()` / `findResultWinner()` read the stored forecast; `simMatch()` uses it for completed matches. Names are normalised (`S. Africa` ↔ `South Africa`). |

### Two safety gates (the backfill refuses to write if either fails)

1. **FIFA reconciliation** — each team's frozen pre-match FIFA must equal `fifaPts − fifaPtsDelta` (its live points minus what it gained in its last match). Verifiable by hand: England pre-M99 = 1889.42 − 18.03 = **1871.39**.
2. **Coverage** — every knockout must have a *real* captured pre-match FIFA. A match missing from the engine's data is flagged, not silently defaulted to the current (post-match) value.

### Going-forward auto-freeze

`update_wc.py` has a `forecast` section placed **before `form`** in `SECTION_ORDER`. It calls `backfill_forecasts.py` (idempotent — only writes matches lacking a forecast), so a normal pipeline run freezes each new match at its true pre-match numbers automatically:

```bash
python update_wc.py          # full run: forecast freezes new matches BEFORE form recomputes
```

**Ordering is the whole point:** the freeze must run before form/rankings, or it captures post-match inputs. The section auto-sorts, so even `--section form --section forecast` runs `forecast` first.

### First-time backfill

```bash
python backfill_forecasts.py --dry-run     # both gates must be ✅, M99 shows 1871.39, M73 present
python backfill_forecasts.py               # writes forecast:{…} into all 29 knockout entries
```

⚠️ **`backfill_forecasts.py` imports `update_rankings.py`** and is invoked by `update_wc.py` — all three live in the repo root together. Missing one breaks the chain.

---

## Validators

### Built-in pipeline (`update_wc.py --section validate`)

Runs a **roster-driven auto-correction step first**, then 11 integrity checks. Runs automatically inside `add_result.py` and GitHub Actions before every push. **Validation failures now block the push** (the section returns a non-zero exit code — previously the return value was ignored and failures shipped silently).

**Step 0 — roster auto-correction (self-healing).** Before any check runs, the pipeline rebuilds each match's running scores from the scorers' true countries (from `data/WC2026_Players.csv`) and writes the fix to `goals.json` + regenerates the inline `GOALS` in `index.html`. This *corrects* scraping inversions rather than only flagging them — e.g. an ESPN home/away flip that credited a DR Congo goal to England is silently repaired before it reaches the site. Only safe matches are touched: every scorer must resolve to exactly one roster country that is one of the two teams, **and** the rebuilt final must match the official score; otherwise the match is left alone and surfaced for review.

| Check | Auto-fix |
|---|---|
| Goal balance — score must equal number of goal entries | No — manual |
| Duplicate goal IDs | No — manual |
| Goal type validity (open-play/header/penalty/own-goal/free-kick) | No — manual |
| MATCH_STATS home/away swapped vs MATCHES | **Yes — auto-corrects** |
| MATCH_STATS score mismatch vs MATCHES | No — manual |
| MATCH_STATS completeness | No — manual |
| KNOCKOUT_RESULTS winner in [home, away] | No — manual |
| goals.json in sync with index.html | No — run `--section goals` |
| Sequential goal IDs (gaps are informational only) | — informational |
| Scorer ↔ country consistency (history-based) | No — manual |
| **Scorer ↔ country consistency (roster-backed, #11)** | **Yes — Step 0 corrects; #11 is the final gate** |

The history-based check (#10) derives each scorer's country from running-score deltas; its blind spot is that it only catches a player mis-credited *after* they've scored correctly before. Check #11 (roster-backed) has no such blind spot and also acts as the hard gate: anything Step 0 could not safely auto-correct is a blocking error.

### Roster-backed corrector (`validate_scorer_country.py`)

Uses the **official squad roster** (`data/WC2026_Players.csv`, `COUNTRY` + `PLAYER_NAME` columns), which contains every registered player. Because it knows every player's real country up front, it catches — and corrects — even a brand-new scorer's first goal being credited to the wrong team, the class of bug the history-based check misses.

```bash
python validate_scorer_country.py            # report mismatches
python validate_scorer_country.py --strict   # exit 1 on any mismatch (CI / pre-push)
python validate_scorer_country.py --fix      # rebuild running scores from the roster
```

**Correction (`--fix`, and Step 0 of the pipeline):** for each match, rebuilds the running score from the scorers' true countries — a normal goal increments the scorer's own country's side, an own goal the opposite side. Applied only when every scorer resolves unambiguously to one of the match's two teams and the rebuilt final equals the official score (from `matches.json` / `knockout_results.json`). Idempotent, and it self-heals ESPN home/away inversions.

**Name matching is rule-based and alias-free.** Because the roster holds every registered player, a miss is a normalization gap, not a missing player. Matching layers: case + accent normalization, compound-surname handling (matches each word of `VARGAS MARTINEZ`), hyphen/spacing tolerance (`Al-Amri` ↔ `ALAMRI`), name-on-shirt fallback, **every-token matching** for single-name / no-initial forms (`Vinicius Jr.`), and **transliteration tolerance** that collapses doubled letters (`Al-Taamari` ↔ `ALTAMARI`). The two previous hardcoded aliases were removed — both now resolve by rule, and all current scorers resolve with zero unmatched. Country-name aliases (`IR Iran` → Iran, `Congo DR`/`Cabo Verde` → DR Congo / Cape Verde) are handled too. Roster file is read as cp1252/UTF-8 and tab- or comma-delimited automatically.

On its first run it caught two genuine attribution bugs — **m39 (Pina, Uruguay↔Cape Verde)** and **m40 (Surman, NZ↔Egypt)** — and later self-healed a live one: **M80**, where an ESPN orientation flip credited Brian Cipenga's DR Congo goal to England.

### Scraper orientation fix (`update_match_stats.py`)

Root-cause defense so inversions aren't produced in the first place: `assign_goals` now anchors the running score to team **identity**, never to ESPN's positional home/away. It detects ESPN's orientation once per match from any name-resolved goal, then advances each side by identity — so a flipped feed no longer inverts the scoreline. The roster corrector remains the safety net if anything still slips through.

---

## Match Analytics — collapsible sections

Six sections stack vertically. Cards are identical to the original design (flag · team · score · team · flag in a 4-col grid). The group stage is **permanently locked** — no new cards ever appear there.

| Section | Behaviour |
|---|---|
| ⚽ Group Stage | 🔒 Locked — 72/72 complete, always collapsed |
| ⚡ Round of 32 | **Always open** — gold header (active stage). Uses `R32_SCHEDULE` (frozen — played matches never disappear even when update scripts run) |
| 🏆 Round of 16 | Opens once first R16 result recorded. TBD cards resolve as R32 winners known |
| ⚡ Quarter-Finals | Opens once first QF result recorded |
| 🏆 Semi-Finals | Opens once first SF result recorded |
| 🎉 3rd Place & Final | Opens once SF complete |

**Tap a played card** → full stats panel (possession, shots, xG, discipline) injects inside that same section and scrolls into view. Works for both group stage (m1–m72) and knockout cards (M73+) — the id is normalised to lowercase so `showMatchStats('M73')` correctly looks up `MATCH_STATS['m73']`.

**Key design decision:** The R32 analytics section reads from `R32_SCHEDULE` (a frozen 16-entry constant), not from `UPCOMING_FIXTURES`. This means played R32 matches always stay visible as result cards even when `update_wc.py --section upcoming` removes them from the ticker.

---

## Matches played card

The "Matches Played" snapshot card shows a live breakdown:

```
80 of 104   72 group · 8 R32 · 0 R16 · 0 QF · 0 SF · 0 3rd · 0 Final
```

- Group count is capped at m1–m72 (knockout matches written to MATCH_STATS by ESPN are excluded)
- Knockout count reads from `KNOCKOUT_RESULTS` winners only
- Total = group + knockout played

---

## All-time record scorer card

A snapshot card (`stat-alltime`) tracks the all-time World Cup scoring record (Klose, 16) and who has passed it. Each contender's total = pre-2026 career WC goals + goals scored in 2026 (tallied live from `GOALS`). When one or more players pass 16 it flashes **NEW RECORD!** and lists them highest-first, with the current record holder **bolded**, e.g.:

```
NEW RECORD!  L. Messi 19 (6 in 2026) · K. Mbappé 18 (6 in 2026)  Passed Klose (16)
```

The list, totals, and "Passed Klose (16)" note update automatically as goals are scored.

---

## Penalty shootouts

Knockout matches drawn after regulation are decided on penalties. The pipeline handles this end-to-end:

- **Scraper** (`update_match_stats.py`) reads ESPN's `shootoutScore` for each team. When regulation is level and shootout scores exist, the winner is the shootout victor and a `pens` field (home-away order, e.g. `"3-4"`) is recorded. The shootout scores flip correctly when ESPN's home/away orientation differs from the fixture.
- **Schema** — `knockout_results.json` entry gains an optional `pens` field; `winner` stays authoritative (team name). Matches decided in regulation simply omit `pens`.
- **Display** — the score shows the shootout in parentheses beside each team, **everywhere a result appears**: bracket cards, video cards, the scrolling ticker (gold bar), and the match-stats panel header.

```
Netherlands (2) 1-1 (3) Morocco
```

A single helper, `fmtScoreWithPens(matchId, score)`, looks up the shootout from `KNOCKOUT_RESULTS` and formats it consistently. Per-goal running scores (goal feed / hero panel) intentionally show the score *at the moment of the goal* and do not append pens.

- `winner` advances via `resolveKnockoutTeam('W74')` — unaffected by penalties
- The Simulator overrides simulated rounds with **actual** completed results (`applyActual`), so eliminated teams drop out of R16+ and the real winner advances

---

---

## ⚠️ ESPN field names — read this before touching the scraper

`get_stat()` matches ESPN's `name`, `abbreviation` **and** `label`. Those three often disagree, and the label usually contains **spaces**. Guessing a field name is how stats end up silently wrong.

Real examples from the live feed:

| What ESPN sends | `name` | `label` |
|---|---|---|
| Corners | `wonCorners` | `Corner Kicks` |
| Passes | `totalPasses` | `Passes` |
| Accurate passes | `accuratePasses` | `Accurate Passes` |

**The bug this caused (fixed):** the scraper searched for `cornerKicks` / `corners`. ESPN's name is `wonCorners` and its label is `Corner Kicks` (with a space) — so *nothing* matched, `or 0` fired, and **46 of 98 matches silently stored 0-0 corners** while every other stat in those same matches parsed fine.

**The fix:** `_norm_stat_key()` strips non-alphanumerics and lowercases both sides, so `Corner Kicks` → `cornerkicks` → matches `cornerKicks`. This kills the whole *class* of bug, not just corners.

**The rule:** never let a missing stat fall through to a plausible-looking default. Every lookup that can fail now **prints a warning**. Silent zeros are worse than crashes — they look like data.

---

## Pass Accuracy

A 5-element stats row (all other rows are 3):

```js
["Pass Accuracy", homeTotal, awayTotal, homeAcc%, awayAcc%]
["Pass Accuracy", 243, 598, 78, 90]          // renders: 243 (78%) … (90%) 598
```

The renderer auto-detects the extra fields and widens the value cells. 3-element rows are unaffected.

**Accuracy is DERIVED, not taken from ESPN.** ESPN sends `passPct` as a fraction rounded to **one decimal** — for a match with 505/575 accurate passes (**87.8%**) it reports `0.9`. Using it would render 90% (or 0.9%). So we compute `accuratePasses / totalPasses` ourselves and only fall back to `passPct` with a printed warning.

⚠️ **Anything that transforms stats rows must handle 5-element rows.** `update_wc.py`'s home/away swap used to filter on `len(s)==3`, which **silently deleted** the Pass Accuracy row from any swapped match. Fixed — the swap now flips totals *and* percentages.

---

## Corner Kicks card (Analytics)

`id="stat-corners"`, sits between **Own Goals** and **Red Cards**. Populated by `update_wc.py --section snapshot`:

- **Number** — tournament corner total
- **Sub-text** — per-phase breakdown: `group stage · R32 · R16 · QF · SF · 3rd · final` (a phase only appears once it has corners recorded)

---

## Known issue — Expected Goals (xG) is NOT real

**The xG shown in the app is largely fabricated.** ESPN's `boxscore.teams[].statistics` contains **no team xG field**, so the scraper falls back to `sot × 0.33 + (shots − sot) × 0.05` — an uncalibrated formula. An audit found **68% of stored xG values (133 of 196) exactly equal that formula**, and it is **systematically inflated** (France–Senegal: formula gives 2.79, real xG is 1.79).

**What the investigation established:**

- A goalkeeper's `expectedGoalsConceded` **is** the opposing team's true xG — proven, not inferred (Simón played all 90; his `0.344` matches Belgium's displayed `0.34` exactly).
- It **breaks on keeper substitutions**: `leaders` only reports the *top* saves leader. Belgium subbed keepers, so Courtois's `1.196` was one shift — the backup's ~0.76 appears **nowhere** in the payload, and Spain's real xG was 1.96.
- Substitutions **are** detectable via `rosters[].subbedIn` / `subbedOut`.
- **Per-shot xG does not exist in the API** — checked `summary` and both CDN endpoints.

**Planned fix:** use the opposing keeper's xGC where they played the full match (real, measured); fall back to a **clearly labelled estimate** where they didn't. Until then, treat displayed xG as unreliable.

---

## Rankings updaters

Rankings are split by what drives them: **FIFA points are derived from match results**, so they refresh the moment a result is recorded; **Elo and Polymarket odds are external feeds**, so they refresh once daily.

### `update_fifa.py` — FIFA ranking, results-driven

Runs inside `auto-update.yml` after each result is recorded. Recomputes the FIFA/Coca-Cola World Ranking from the frozen Jun 11 2026 baseline plus every verified WC result, and patches **only** the FIFA fields (`fifaPts`, `fifaPtsDelta`, `fifaRankDelta`) into `index.html` and `team_data.json` — it never touches Elo or `marketPct`. The SUM computation itself is imported from `update_rankings.py`, so there is one source of truth for the maths.

The calculation implements the official FIFA **SUM** formula (`P = Pbefore + I·(W − We)`) including the conditions that specifically affect knockout matches:

- **Match importance I** is stage-aware: `I=50` for group stage and knockout rounds up to the QF, `I=60` from the QF stage onwards (per the FIFA spec).
- **Penalty shootouts** are scored specially: the PSO winner gets `W=0.75` ("half a win"), the PSO loser `W=0.5` (a draw) — **not** a normal 1.0/0.0. A win in regulation or extra time (no shootout) is a normal win.
- **Knock-out no-loss protection:** in a knockout round, if `(W − We) < 0` the team keeps its points (`P = Pbefore`). Teams don't lose ranking points for a knockout defeat.
- **Rank delta** is the real change in position, `pre_rank − current_rank` (positive = climbed). A card's arrow direction follows this; a previous bug wrote the raw pre-match rank (always positive), so every card wrongly showed an up arrow.

`python update_fifa.py --check` does a dry run (compute + print, no write).

### `update_rankings.py` — Elo + odds (+ FIFA), daily

Runs daily at 06:00 UTC via `daily-rankings.yml`. Updates:

- **Elo** — live from eloratings.net (via footballratings.org), falls back to hardcoded post-group-stage values (Jun 28 2026) if the live fetch fails
- **FIFA pts** — recomputed via the same SUM logic `update_fifa.py` uses (harmless overlap; keeps the daily run self-contained)
- **Polymarket** — live win probabilities from gamma-api.polymarket.com

### Rankings validator (built-in)

The result set fed to the calculator is **never hardcoded**. It is built dynamically at runtime from:

- `data/matches.json` → group stage (id ≤ 72, valid score required)
- `data/knockout_results.json` → R32 through Final (each entry may carry an optional `pens` field, which flags a PSO for the special W-values above)

Before calculating, `validate_results()` checks for duplicate match entries, unrecognised team names (warns), and invalid result values — and `sys.exit(1)`s on failure, so bad data is never patched. A **sanity check** then confirms the recomputed group-stage points still match a frozen Jun 29 reference within ±3 pts.

**Idempotent:** both scripts rebuild from the frozen baseline + all verified results every run, so running either one repeatedly gives the same answer as running it once — safe to run on every auto-update cycle.

---

## Bracket simulator

There are two bracket views. The **Simulator tab** (`renderMatchupCard`) shows model-vs-market prediction cards. The **Bracket tab** (`bsimSlot` / `bsimRender`) is the interactive pick-every-match bracket with AI Fill, Reset, and PDF export. Both follow the **official FIFA bracket** (M73–M104) exactly.

**Concluded-match locking (both views).** A match is "concluded" when it has a `KNOCKOUT_RESULTS` entry.

- **Bracket tab:** concluded slots render **locked** — real teams, real score (with shootout as `1 (3)` / `1 (4)`), winner highlighted, a single lock icon on the header, and **not clickable**. Three guards enforce it: the locked card has no click handler, `bsimOpenModal` refuses to open, and `bsimPick` rejects the pick. The real winner is forced and cascades into the next round (`bsimApplyActual`), and downstream matches stay editable until they too conclude — so the user can complete the rest.
- **Simulator tab:** a concluded card keeps its full prediction (probability bars, model %, market %) and adds a **FINAL banner stating whether the prediction was right (green ✓) or wrong (red ✗)** vs the actual winner. The result is frozen — re-simulating only re-rolls the unplayed matches.

**Engine notes:**

- `runSimulation()` resolves each round via `(BSIM_R16||[]).map()` — `fH:'W74'` means home = winner of M74; `applyActual` overrides simulated rounds with real `KNOCKOUT_RESULTS`
- `bsimAiFill()` / `bsimAiFillSilent()` **respect concluded results** — they lock real winners first and only predict the unplayed matches (so an eliminated team never advances)
- **Reset** (`bsimReset`) clears every pick — AI Prefill, AI Fill, and user picks — back to a blank bracket, keeping only concluded matches locked, so you start predictions from scratch
- `bsimEnforceIntegrity()` called after AI fill to catch any slot inconsistencies
- PDF: html2canvas direct capture of live bracket, A3 landscape, centred both axes

---

## Upcoming fixtures ticker

- Reads from `getKnownFixtures()` — single source of truth for both ticker and analytics
- Played R32 matches removed automatically once `KNOCKOUT_RESULTS[matchId].winner` exists
- R16 fixtures appear only when both R32 winners are resolved (no Wxx placeholders)
- Auto-refreshes every 60s + immediately on `visibilitychange` (returning to tab)
- `UPCOMING_FIXTURES` drives the ticker (filtered). `R32_SCHEDULE` drives analytics (frozen).

---

## GitHub Actions schedule

| Workflow | Trigger | What it does |
|---|---|---|
| `auto-update.yml` | Polls every 30 min during tournament hours + `*/6` safety net | Scrape → auto-knockout → validate → sync → **refresh FIFA ranking** → push |
| `daily-rankings.yml` | 06:00 UTC daily | Update Elo + Polymarket odds (and recompute FIFA) |

**Result-driven, not clock-driven.** `auto-update.yml` used to carry ~33 hand-computed per-match crons (each needing the right EST/EDT offset and a guess about when extra-time matches finish). It now simply **polls every 30 minutes** during the active window and self-gates: the scraper only records matches ESPN marks completed (`status.state == 'post'`), and the commit step pushes only when data actually changed — so the site updates shortly after each match concludes, with no timezone math and no feed-lag gamble. An extra-time/penalty match is picked up on the next poll once ESPN posts the final.

**FIFA refresh is part of the match cycle.** Because FIFA points are derived from results, `auto-update.yml` runs `update_fifa.py` right after recording a result, so the ranking is never stale relative to the score. Elo and odds — external feeds — stay on the daily job.

---

## Goal data model

```javascript
{
  id: 42, matchId: "m27", home: "Canada", away: "Qatar",
  scorer: "D. Davies", flag: "", minute: 12,
  type: "open-play",  // open-play | header | penalty | own-goal | free-kick
  phase: "Group F", score: "1-0", desc: ""
}
```

Goal type classification uses a 3-layer system: ESPN auto-detect → preserve existing types on re-scrape → `GOAL_TYPE_OVERRIDES` (hardcoded map, never reset by scraping).

---

## Prediction model

```
score(team) = form×0.35 + (elo/2200)×0.20 + (squadDepth/100)×0.15
            + (fifaPts/1900)×0.15 + qualGDpg×0.10 + (exp/10)×0.05

P(win) = 1 / (1 + exp(−8 × (score_A − score_B)))
draw%  = max(0.12, 0.30 − eloGap/2800)
```

Form is recalculated after each matchday:
```
base = (qualW + 0.5×qualD) / total_qual_games   (or wc_avg if no qual data)
form = base×0.40 + wc_avg×0.60    (floor: 0.10)
```

Post-group-stage Elo (Jun 28 2026): Spain/Argentina 2144 · France 2123 · England 2038 · Brazil 2009

---

## Browser console checks

```javascript
// Data state
console.table({
  matches:   MATCHES.length,                       // 72
  goals:     GOALS.length,                         // 234
  stats:     Object.keys(MATCH_STATS).length,      // 98 (72 group + 26 knockout)
  knockout:  Object.keys(KNOCKOUT_RESULTS).length, // grows with results
  r32sched:  R32_SCHEDULE.length,                  // 16 (frozen)
  upcoming:  UPCOMING_FIXTURES.length,             // ≤16 (filtered)
})

// Check bracket resolution
resolveKnockoutTeam('W74')   // → real team name once M74 played

// Fixtures in ticker (played filtered out)
getKnownFixtures().map(f => f.matchId + ': ' + f.home + ' vs ' + f.away)

// Argentina post-WC values
TEAM_DATA['Argentina'].elo        // 2144
TEAM_DATA['Argentina'].fifaPts    // 1907.40
TEAM_DATA['Argentina'].form       // 1.0 (3W group stage)
```

---

## Push workflow

```bash
# After a knockout result
python add_result.py M73 Canada "S. Africa" 1-0
# That's it — validates, updates, pushes automatically

# If you need to push manually
python update_wc.py --section validate
git fetch origin && git reset --soft origin/main
git add index.html data/
git commit -m "update: R32 results"
git push origin main

# If push rejected (Action committed first)
git pull origin main --no-rebase && git push origin main
```

### Deploying the forecast-freeze feature (add all three together)

`index.html`, `backfill_forecasts.py`, and `update_rankings.py` are interdependent — add them in one commit:

```bash
git pull origin main --no-rebase          # bot may have pushed

python backfill_forecasts.py --dry-run    # both gates ✅, M99 = 1871.39, M73 present
python backfill_forecasts.py              # writes 29 forecast blocks

# verify
grep -c 'forecast:{modelHome' index.html  # 29
grep -c 'function frozenForecast' index.html  # 1
grep -c '<<<<<<<' index.html              # 0

git add index.html backfill_forecasts.py update_rankings.py update_wc.py
git commit -m "frozen pre-match forecasts + going-forward auto-freeze"
git pull origin main --no-rebase && git push origin main
```

Include `update_wc.py` too if you're adding the auto-freeze `forecast` section. After this, every future match freezes automatically on the next pipeline run.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS — zero frameworks, zero build step |
| Data | JSON files in `data/` — GitHub as a free database |
| Hosting | GitHub Pages |
| Match data | ESPN API (no auth required) |
| Rankings | eloratings.net (via footballratings.org) + FIFA hardcoded + Polymarket |
| PDF export | jsPDF + html2canvas (CDN, deferred) |
| Flags | flagcdn.com |
| Charts | Pure SVG/HTML — no chart library |
| CI/CD | GitHub Actions — free tier, result-driven 30-min polling + daily rankings |
