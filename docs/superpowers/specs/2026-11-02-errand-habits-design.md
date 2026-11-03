# Errand habits: how each person runs errands — design

**Date:** 2026-11-02. **Status:** rev 1, approved in conversation (three facts per person, constrained-first ordering for batched kinds). **Follows:** `2026-10-22-errands-ride-the-route-design.md` (rev 2.2; §1 shapes amended by v2.499.743/.746), `2026-10-22-errands-common-sense-design.md` (rev 1.1). This is the "standing per-person preferences" slice both specs deferred. **Touches:** `solver/matcher.py` (`insert_errands_globally`: placement order, candidate fits, cost, notes, why), `services/errand_prefs.py` (constants, `describe_habits`), `services/storage.py` (the habits store), `models/schemas.py` (`ErrandHabits`), `main.py` (three routes), `services/auth.py` (one rule), `services/agent_tools_v2.py` (two tools), a new `templates/components/errand_habits.html` included by `templates/errands.html`, Tailwind rebuilt.

## Problem

The user, 2026-11-02: "What I feel like is missing is the personal touch. Some people like to group their errands so they only make 1 trip. People have certain times during the day where they like to get things done, and that can be different for different errands. There is no way to say 'Lorena likes to do all of the groceries together' or 'Lorena prefers to make stops when she is already out' or 'Jeff can only do errands between 1pm and 3pm'." And: "When a driver is available to drive to activities and when they like to do errands can be very different things too."

Today every errand fact is per errand (window, days, drivers, kind, home-bound, a free-text group id whose bonus means same driver same day, not same outing). Nothing is per person: `Driver.preferred_start/end` apply to rides only and the errand pass never reads them; the learned rows are per person but soft, weekday/time-band/driver only, and taught only by steers; the dedicated-trip penalty is one household number.

## Decisions (the user's, 2026-11-02)

1. **Three facts per person, each one line.** Errand hours (with days, strict or preferred), separate trips (household default, a personal number, or never), and the kinds that person likes to run together.
2. **Errand hours are not driving hours.** `preferred_start/end` stay ride-only. A person can drive to soccer at 17:30 and still only run errands 13:00-15:00.
3. **Passing legs obey errand hours too.** A stop on a drive the person makes anyway is still outside their hours. Strict excludes it, preferred costs it. Otherwise "only 1-3pm" means nothing on a day with drives.
4. **Constrained first.** For a kind someone runs together, the errand with day requirements is placed first and the free ones chain onto it. "Placing an errand that has no restrictions first and then not batching because the other one has a restriction is worse for the driver for no real reason." Outside together kinds the shipped order (priority, then longer first) stays, so nothing shipped moves.
5. **Together means one outing.** The bonus applies only when the candidate sits beside the already placed sibling on the route (prev or next stop is the sibling, or the same location). Same day on a different leg earns nothing. This differs from the group id, which stays as it is.
6. **The facts sit above the learned rows.** A learned row never overrides a strict hour. Steers do not teach these facts in this slice.

## 1. The store

`storage.get_errand_habits() -> dict` keyed by driver id; `storage.get_driver_errand_habits(driver_id) -> dict` (normalised defaults when none); `storage.set_errand_habits(driver_id, habits: dict | None) -> dict` (None clears). App state key `errand_habits`, beside `errand_preferences`. A write invalidates the schedule caches (`_invalidate_schedule_caches` under the lock) because the solver reads it; the route then triggers a background refresh. Not on the Driver record: the Config page edits a driver by DELETE-then-POST from its own form state, which would drop any field it does not carry; keyed by driver id the habits survive that round trip.

`models/schemas.py`:

```python
class ErrandHoursRow(BaseModel):
    days: List[int]            # 0=Monday .. 6=Sunday, non-empty, each 0..6
    start: str                 # HH:MM
    end: str                   # HH:MM, after start

class ErrandHabits(BaseModel):
    hours: List[ErrandHoursRow] = []        # empty = any time
    hours_strict: bool = True               # strict: outside is excluded; else outside costs OUTSIDE_HOURS_MINS
    separate_trip_mins: Optional[int] = None  # 0..120; None = the household setting errand_dedicated_trip_mins
    no_separate_trips: bool = False         # never a trip from home for this person
    together_kinds: List[str] = []          # subset of ERRAND_KINDS
```

Validators: a row with no days or `end <= start` is refused (422); kinds outside `ERRAND_KINDS` refused; `separate_trip_mins` bounds 0..120 like the setting. Storage normalises through the model so the pass never sees a half row.

## 2. The pass

`insert_errands_globally` reads `storage.get_errand_habits()` once per run (a test may monkeypatch it like the preference rows). `habits_for(d_id)` is the normalised dict.

### 2.1 Errand hours

A candidate `(driver, start, end)` on `day_date` is **inside hours** when the driver has no hours rows, or some row lists `day_date.weekday()` and `row.start <= start` and `end <= row.end` (times on that date). Rows exist but none for that weekday means outside.

Candidate starts are chosen inside the hours when they can be. A helper replaces the bare `_first_fit` call on every shape:

```python
def fit_hours(lo, hi, *, latest=False):
    """Returns (start, outside). start None = no fit. outside True only for a preferred-hours driver placed outside."""
```

- No rows: `(_first_fit(lo, hi, ...), False)`.
- Rows: intersect `[lo, hi]` with each row window on that weekday (sorted by start; reversed for `latest=True`) and take the first `_first_fit` that lands. Found: `(start, False)`.
- None found and strict: `(None, None)` and the driver's name joins `hours_blocked` for the note.
- None found and preferred: `(_first_fit(lo, hi, ...), True)`; the candidate's cost gains `OUTSIDE_HOURS_MINS` (20, `errand_prefs`).

`fit_dedicated` uses the rows instead of the human-hours band when the driver has rows (the person's own hours beat the default band); preferred hours with nothing inside fall back to the band as for anyone, marked outside; with no rows it is unchanged. The bedtime bound, rider rules and the day bounds still apply after the fit as today.

### 2.2 Separate trips

`penalty_for(d_id)` = `habits.separate_trip_mins` when not None, else the household setting. `no_separate_trips` drops the `empty` shape for that driver on every day (empty day and every home gap). With no leg left the errand gets the usual `no_slot` / `no_driver` note.

### 2.3 Together

**Batched kinds** = the union of `together_kinds` over the active, non-disabled drivers in the run.

**Order.** The base order is unchanged: `(priority, -duration)`. Walking that order, the first errand of a batched kind pulls every active errand of that kind into its position as one block, sorted by tightness: `(0 if pinned_date else 1, len(valid_days_of_week) or 7, window minutes or 1440, priority, -duration)`. A kind nobody batches keeps its positions exactly.

**Bonus.** When placing errand B of kind K for driver D on day d, its siblings are the rows this run already placed on d for D with kind K, and only if K is in D's `together_kinds`. A candidate whose `prev_stop` or `next_stop` id is a sibling's id (the same location is the inside-stop case, prev == next; the same place on another leg of the day is not one outing) earns `TOGETHER_BONUS` (9999, the group bonus's size, so one outing wins over any other day's cheaper leg but never over the unknown rank). The `empty` shape never earns it: a trip home and out again is not one outing. A sibling already on the route is an ordinary stop, so the between / to-home / from-home shapes beside it measure the real detour.

**Primer.** After a placement, the errand's location joins `places`, so the next errand's primer buys the pair with it and a chained candidate is never unknown on the first run because its sibling was unknown to the cache.

**Anchor fallback.** Nothing to build: when the constrained one cannot be placed at all it gets its note and the next in tightness order is placed on its own merits; it becomes the anchor the rest chain onto by the same rule.

### 2.4 Notes

When no candidate survived: `kids_bedtime` keeps precedence (shipped); else, if `hours_blocked` is non-empty and every driver who saw a day is in it, reason `errand_hours`, text `outside Jeff's errand hours` / `outside Jeff's and Lorena's errand hours`; else `no_slot` / `no_driver` as today. `ERRAND_UNPLACED_TEXT['errand_hours'] = "outside everyone's errand hours"` is the generic fallback.

## 3. Words

`why` gains up to two keys, and `errand_why_text` says them at the end, after the learned clause:

- `why['hours'] = 'inside' | 'outside'` only when the driver has hours rows: `, in Jeff's errand hours` / `, outside Jeff's errand hours`.
- `why['together'] = <sibling title>` when the bonus applied: `, with the Kroger run`.

So: `a trip from home, 20 min each way, in Jeff's errand hours`; `on Lorena's way home from Soccer, +6 min, with the Kroger run`. Rows reach the page, the phone and the steer sheet through `why.text`, nothing else changes.

`errand_prefs.describe_habits(name, habits) -> list[str]`, one sentence per fact in the order hours, separate trips, together, for the drawer's summary line and Argyle: `Jeff runs errands 13:00-15:00 on weekdays (strict)`, `Lorena never makes a separate trip`, `Lorena would rather a passing drive add up to 40 min than go out just for it`, `Lorena runs groceries and pharmacy runs together`. Nothing set: `No errand habits set`. Hours rows join with ` and `: `09:00-12:00 on weekends and 18:00-20:00 on Wednesdays (preferred)`. Day phrases: all seven `every day`, 0-4 `on weekdays`, 5-6 `on weekends`, one day `on Wednesdays`, otherwise the names joined with `, ` and a final ` and ` (`on Mondays, Wednesdays and Fridays`). `no_separate_trips` wins over a number. Kinds use `KIND_LABELS` joined the same way.

## 4. Routes and auth

- `GET /api/errands/habits` → `{"drivers": [{"id", "name", "habits", "text": [...]}]}` for active, non-disabled drivers in name order, habits normalised.
- `PUT /api/errands/habits/{driver_id}` body `ErrandHabits` → stores, invalidates, background refresh; 404 for an unknown driver; 422 for a bad row.
- `DELETE /api/errands/habits/{driver_id}` → clears to defaults, invalidates, refresh.

Auth: one rule `(ANY, '/api/errands/habits/*', PARENTS, None)` beside the preferences rule, above `/api/errands/*`, declared before the `{doc_id}` errand routes in `main.py` so "habits" is never read as a doc id. `GET /api/errands` is untouched.

## 5. The hand path

`templates/components/errand_habits.html`, included in the Errands drawer between "Where errands land" and the rules, inside `settings_section('errand-habits', 'How people run errands')`. Alpine `errandHabitsPanel()`: loads on `chf-settings-opened` for the errands tab; `apiBase` from `window.chfBase`; parents only (401/403 shows the same italic line the Learned block uses). One card per driver:

- **Errand hours.** Rows of day chips Mon..Sun (toggle), two `type="time"` inputs, Remove; an "Add hours" button; a strict / preferred select shown when any row exists. Help: "When they like to run errands. Different from when they can drive. Strict means never outside; preferred means only when nothing inside works."
- **Separate trips.** Select: `Household default (N min)` / `Never` / `Up to … min` with a number input 0..120 shown for the third.
- **Together.** Kind chips from `ERRAND_KINDS` with `KIND_LABELS`; help: "Kinds this person likes to do in one outing."
- Summary line under the card from `text`.

Every change saves the whole card with PUT, through `chfSettingsSaving` / `chfSettingsSaved`, `showGlobalAlert` on failure, never a browser dialog, `:disabled` coerced with `!!`. The drawer macro draws nothing on a panel or kiosk, so a wall never shows it. Tailwind rebuilt after.

## 6. Argyle

Admin tools, beside `get_errand_preferences`:

- `get_errand_habits` (no args) → `{"status", "drivers": [{"id", "name", "habits", "text"}]}`.
- `set_errand_habits(driver_name, hours?, hours_strict?, separate_trip_mins?, no_separate_trips?, together_kinds?, clear_hours?)` partial: only the fields given change; `clear_hours` empties the rows; `separate_trip_mins` -1 means back to the household default. Resolves the driver by name (case-insensitive, unknown → error). Schedule-mutating. The hand path is §5.

## 7. Tests (Claude, first)

- `tests/test_errand_habits.py` (solver, grid world): strict hours move a trip from home to 13:00 and exclude a passing leg outside; weekend without a row is outside and the note says `outside Jeff's errand hours`; preferred hours keep the leg at a cost and the why says `outside Jeff's errand hours`; `no_separate_trips` leaves an empty week unplaced and still rides a leg; a personal penalty picks the cheaper person; together places the Saturday-only grocery first and chains the free one beside it with `why.together`, while without the habit the free one goes Monday; a kind nobody batches keeps the shipped order; the primer sees the sibling's location.
- `tests/test_errand_habits_api.py`: storage normalise / invalidate; the three routes as a parent and their tiers; both tools in the admin lists and working by name; `describe_habits`; the component is on the page and not on a panel; the panel's logic PUTs the whole card.
- Gate: the errand gate (routing 32, common-sense 25, passengers 5, bedtime 4, dedicated_gap 3, routing_api 15, lists_render 12, pwa_steer 3, prefs_api 6, solve_pack, chat_actions 13, storage 33) plus test_auth, test_template_js, test_agent_v2_bridge (pre-existing 3/5).

## Out of scope

- Steers teaching the three facts (a steer off a from-home trip nudging separate trips).
- Lookahead that moves the anchor to suit a sibling.
- The driver's own quiet hours (bedtime slice left it).
- Per-errand-per-person matrices. Three facts per person, each one line.
