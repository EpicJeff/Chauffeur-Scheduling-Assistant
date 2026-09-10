# Open items from the studio pipeline and the repair run

**Written:** 2026-09-09, at the end of the session that ran v2.467.0 → v2.472.0.
**Why this exists:** these were each found with evidence, deliberately not fixed,
and would otherwise survive only in commit messages and agent reports. Nothing
here is speculative — every entry names the file and the proof.

Ordered by consequence, not by effort.

---

## 1. Gift secrecy: a present list for a household member's own birthday reaches the wall

**Severity: highest. This is the one to do first.**

`services/occasions.py` `_gift_visibility` (~line 1235-1250) stamps
`{'audience': 'private', 'shared_with': [adults]}` on gift lists **only when the
occasion's `kind == 'invited'`**. A present list minted for a *household
member's own* birthday gets no audience at all, so it defaults to `household` —
and `household` is exactly what passes `scope.audience_allows(obj, type, None)`
on a viewerless surface.

So the v2.471.0 audience fix, which closed the board tile, the corkboard and the
list picker, does **nothing** for this case: the list is not restricted in the
first place. The wall will draw "Emma's present — bike helmet" for the household
whose birthday it is.

This is upstream policy in the occasions module, not a filtering bug, which is
why it was flagged rather than changed — gift secrecy is a standing user ruling
and the fix is a decision about what audience a self-birthday gift list should
carry, not a patch.

## 2. `option_sources()['trips']` has the hole the shopping picker had

`services/home_board.py` (~line 5519-5527). The board editor's trip picker puts
every trip title into `/api/home_board/catalog`, which is WALL tier
(`services/auth.py:258`), while `_tile_trips` correctly refuses to draw them.

Not fixed because trips default to `audience: 'parents'`, so filtering with
`viewer=None` would empty the picker **completely for every household** — that
is dropping functionality, which needs approval first. The real fix is probably
to give the catalog endpoint a viewer, which is a design change rather than a
patch, and it interacts with item 4 below.

## 3. `/api/errands` leaks private list names and open counts

`main.py:15713`. `storage.find_shopping_lists_for_errand`
(`services/storage.py:3449-3463`) matches `store == errand.location` as a
convenience fallback, and `occasions._source_supplies` sets `store` on gift
lists. So a gift list for Target binds itself to a Target errand and rides
`obj['shopping_lists']` as `{id, name, open_count}`.

Milder than the others — `SIGNED_IN` rather than WALL, and names-and-counts
rather than contents — but a signed-in child can see "Emma's present — 3". Left
alone because the helper is shared with write paths (`services/shopping.py:387`
and `:412`), so filtering inside it has a blast radius that needs deciding
deliberately.

## 4. The board cache key has no viewer in it

`services/home_board.py:5244` — `cache_key` is
`[slug, columns, row_height, editing, instances]`.

`_tile_occasions`, `_tile_trips` and `_tile_trips_gallery` all declare
`viewer=None` and receive `None` today, because `home_board.build()` takes no
viewer at all. That is safe **only** while nobody threads one in. The moment
someone does without adding it to the cache key, the first parent to warm the
cache serves their parents-audience trips and occasions to every wall panel for
the TTL.

`_tile_shopping` was deliberately written to hard-code `None` rather than accept
a parameter for this reason (following `_tile_mind`'s precedent at line 2673). A
comment on the cache key, or removing the three unused `viewer=` parameters
outright, would close the trap.

## 5. `meals.py:3335` reads and can delete across every list

It scans every open item on every list, gift lists included. It only *acts* on
rows whose `added_via == 'meal'`, so it is not a read leak — but it is a write
path with cross-list reach, and it would happily delete an item off a private
list if that item had ever been meal-claimed.

---

## House: known visual limits (accepted, recorded so they are not re-discovered)

- **The garage room frame holds two cars however many the family has.** At
  `GARAGE_POS` with FOV 24, a car on the apron projects below the chat-bar line.
  Every car now has a plaque and the fleet card shows them all, but making the
  *room* show four is a floor-plan or camera change.
- **The near living-room armchair shows more back than front.** Forced: the
  camera looks north-west, so a chair south of the coffee table points away.
  Moving it south-west bought a readable three-quarter; going further means
  parking it beside the hearth, which is the defect it was moved to fix.
- **minivan and van are nearly interchangeable** at exterior distance. They
  separate on roof height and bonnet length, which is not much at that scale.
- **The bus stop arm** is a red octagon with a cream centre and no lettering; it
  reads more like a "no entry" plate.
- **The garage strip light hangs from nothing** — with the roof hidden there is
  no ceiling plane to mount to, so it rides two drops that run off frame.
- **The kitchen frame no longer shows the leave card.** It used to see the
  plaque on the street door across the great room; the card lives on the
  mudroom's garage door now (v2.468.0). The wall calendar still carries the
  next-leave line, so no information is lost, but it is a deliberate change to a
  view nobody asked about. A second face on the street door would restore it.
- **Bare plank in the north-east of the living room** (x 1.5→3.2, z 5.9→7.6) and
  the far south-east of the great room. Left bare on purpose: filling it with
  scattered props was a defect in an earlier pass, and density means furnished,
  not sprinkled.

## House: lighting work the pass did not reach

- **Interior walls have no baked gradient.** Floors pool; walls are lit only by
  the hemisphere plus lamp falloff. A shared wall-gradient texture is the
  obvious next step.
- **Counters do not pool either** — `woodLight` and `marble` are shared across
  dozens of props, so baking into them would put the same gradient on a stool
  and a cabinet door. Needs per-run textures.
- **The sun is still near-frontal** (~15° off the exterior camera axis).
  Raking it darkens the kitchen's subject wall, so modelling currently comes
  from the cool/warm split and the pools instead. Stronger form needs a
  dedicated fill on the north wall.
- **Kitchen counter wood reads deeper at medium than at high** — an authored
  tier inconsistency (`kWoodK = NICE ? 0xffffff : …` plus `mat()`'s tier-
  dependent map handling), not a lighting bug.
- **Contact language differs across tiers** — real cast shadows at tier 3, grey
  multiply ellipses at 1-2. Correct, but visibly different.
- **The scenery knob only works on chroma**, so anything already neutral does
  not move. A cream toaster cannot be made to stop competing with a cream fridge
  by colour alone. Mapped materials are exempt by design (tinting them can only
  darken, never desaturate).

## Process

- **The sweep is flaky under load.** Two consecutive runs failed a different
  browser-driven test each time (`test_kitchen_state`, then `test_screensaver`),
  and **both passed in isolation**, while a background agent and probe runs were
  driving Chromium concurrently. Reads as resource contention at 12 workers
  rather than a real regression — but a sweep you cannot trust is worth a proper
  look.
- **The pantry card sits two round trips deeper than every other zone**, because
  `_tile_shopping_list` is deliberately self-fetching. On a GPU that is ~50 ms;
  under software WebGL each hop waits for a frame. Putting list contents in the
  tile payload would close it but conflicts with that tile's design *and* with
  item 1 above.
- **None of the house is device-verified.** Everything from v2.463.0 to
  v2.472.0 has been judged on desktop screenshots. The Pi look is still due, and
  it is due *before* H4 flips the panel's home to the house.

## Feature ideas raised but not scoped

- **A car configurator.** The original spec deliberately scoped cars to three
  knobs — `body_type`, `color_code` as the paint, `seat_capacity` nudging length
  — and rejected text-to-3D with reasons. But the v2.467.6 `buildVehicle`
  rewrite gave every car separately-addressable parts that did not exist then:
  inset glass, roof cap, bumpers, grille, rims, hub caps, tyres, lights. Turning
  those into per-car fields is mostly plumbing, and stays inside the original
  design's constraints (no LLM, no downloaded meshes, no Pi cost beyond what is
  already drawn). Suggested first three: trim colour, two-tone roof, wheel size.
- **The reveal-on-demand control** for the scenery knob. The mechanism already
  exists — `window.chfHouseScenery(1.0)` is the reveal and it works today. What
  is missing is only the control that calls it.
