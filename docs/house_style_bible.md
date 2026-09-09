# The Home — Style Bible

**Written:** 2026-09-09 (art-director pass, studio pipeline v2.467.0)
**Binding on:** every set builder, the vehicle artist, the lighting artist.
**Graded against:** the ten reference plates transcribed below.

This document exists because the first architect pass (v2.463–v2.466) built
correct geometry that did not look like the reference. Each prop invented its
own proportions and bevels, so built-ins came out as featureless blocks. This
bible fixes the vocabulary. If a prop you are building is not described here,
build it from the nearest class that is, and add a section describing what you
did.

Nothing in a room is "done" until it passes the checklist at the end.

---

## 0. The reference plates

The user supplied ten reference images. They live in the conversation that
opened this arc, not on disk; if you can see images, ask for them again. These
transcriptions are the durable record and are themselves binding.

| # | Plate | What it is authority for |
|---|---|---|
| 1 | Night dollhouse, two storeys, blue-slate roof, every interior warm-lit, dense planting on the plinth, camper + red car on the driveway | Night exterior: warm interiors against a cool night, plinth landscaping density |
| 2 | Stock isometric cutaway house — dark slate gable, white siding, chimney, one large cutaway showing kitchen + dining, picket fence, yellow tree, dark sedan on a driveway apron, wicker chair and pots on the lawn | **The exterior composition target.** Roof pitch, fascia, cutaway framing, yard prop density |
| 3 | Isometric brick garage — pegboard of tools, tyre on the wall, blue tool cabinet with yellow top, shelf of boxes, red hatchback, mower, wheelie bin, mailbox, driveway apron with expansion joints | **The garage density target.** Wall storage, floor clutter, apron detailing |
| 4 | Cozy garage, teal roof, wooden cabinet, wall tool board, red car, open toolbox, cardboard boxes, tripod lamp, bin | Garage warmth, prop scatter, a workbench that reads as used |
| 5 | Small garage, blue SUV + tiny yellow car, plank floor, shelving with plants and jars, window, side table | Two vehicles of different size sharing one bay; shelf contents |
| 6 | Isometric living room — TV on a low wood media console, sofa with pillows, coffee table with tray, armchair angled to the sofa, four potted plants, a grid of framed art, blue-grey walls, plank floor | **The living-room target.** Seating geometry, art grid, plant count |
| 7 | Cozy retro kitchen — sage fridge and range, cream shaker cabinets, wood counters, open shelving both sides loaded with glassware, jars, plates and cake stands, tile backsplash, wall sconce, window with plants | **The kitchen target.** Open-shelf density, cabinet construction, two-tone palette |
| 8 | Warm orange kitchen at night — dramatic window light, dense counters, hood, plants everywhere, two-seat table, appliances with displays | Light pooling, surface clutter that still reads as tidy |
| 9 | Teal-and-white kitchen — L-run, island/table, wine rack, hood, black cooktop, tile backsplash, dense open shelving | Dark anchors against a light room; island-as-table |
| 10 | Low-poly car pack, three red-and-white cars — faceted bodies, hard chamfers, inset blue glass, grille, headlight blocks, wheel arches, bonnet scoops | **The vehicle target.** Silhouette, chamfer language, glass inset |

### What the plates have in common — and we do not

1. **The frame is full.** Contents occupy 70–85% of the image. Bare floor is
   never more than a quarter of the frame. Our current shots run 55–65% bare
   floor. This is the single largest gap and it is fixed from both ends:
   tighter cameras and more furniture.
2. **Nothing is one box.** A cabinet is a toe kick, carcass, face frame, inset
   fronts, reveals and hardware. A shelf carries objects. See §3.
3. **Every room has a dark anchor.** Black cooktop, dark hood, dark TV, slate
   roof. Our rooms are cream on cream, so nothing has edges.
4. **Every room has three to five saturated accents** in a family (terracotta,
   sage, brass; or teal, mustard, oxblood) — not one accent, and not ten.
5. **Light pools.** Warm patches on the floor and counters, cool elsewhere.
6. **Nothing floats.** Every object meets its surface with a hard contact
   shadow.

---

## 1. Units and proportion

The scene's unit is **0.75 m**. Derived rules, all binding:

| Element | Height (units) | Note |
|---|---|---|
| Counter top | 1.13 | already built; do not move |
| Toe kick | 0.16 tall, recessed 0.07 | |
| Base cabinet carcass | 0.16 → 1.06 | top cap sits on it |
| Countertop slab | 0.07 thick, overhang 0.05 front and open sides | |
| Backsplash | 1.13 → 1.85 | tile field, never blank |
| Upper cabinet | 1.90 → 3.05 | leaves 0.05 of wall above |
| Open shelf board | 0.06 thick, 0.45 deep | edge must be visible |
| Seat height | 0.58 | stools 0.86 (built) |
| Table top | 0.98 | |
| Door opening | 2.70 tall, 1.15 wide | |
| Wall height | 4.20 | as built |
| Ceiling-to-upper gap | 1.15 | fill it: art, a clock, a shelf, or crown |

**The 0.6 rule.** No floor gap wider than 0.6 units may exist between two props
that a person would place together. If the sofa and the armchair are 2 units
apart, the room reads empty regardless of how good either prop is.

---

## 2. Palette

Existing `C` in `house.js` stays; these are additions and roles. Give every new
prop a role, not an arbitrary hex.

### Neutrals (already in `C`)

| Role | Hex | Use |
|---|---|---|
| `shell` | `#efe9e2` | plinth, exterior mass |
| `wall` | `#f4efe8` | interior wall field |
| `cab` | `#f7f4ef` | cabinet face frames, door fronts |
| `cabShade` | `#e6e0d6` | carcass sides, reveals, toe kicks |
| `floorA` / `floorB` | `#f1ece3` / `#cfc7b8` | plank tone range |
| `steel` | `#b9bec4` | hardware, appliance trim |
| `dark` | `#4a4f55` | secondary dark |

### New — dark anchors (every room needs at least one)

| Role | Hex | Use |
|---|---|---|
| `ink` | `#23272c` | cooktop, hood interior, TV screen, range glass, tyre |
| `slate` | `#39424d` | roof, media console top, appliance bodies |
| `graphite` | `#5b6169` | pulls, pegboard, stove grates |

### New — the accent family (pick 3–4 per room, never more)

| Role | Hex | Reads as |
|---|---|---|
| `sage` | `#9db3a4` | retro appliances, cabinet accent, ref 7 |
| `terracotta` | `#b5713c` | pots, copper kettle, crates |
| `brass` | `#c9a54e` | hardware upgrade, sconce, lamp |
| `oxblood` | `#8f4038` | books, a rug border, a bin |
| `mustard` | `#d1a13c` | tool-cabinet top, cushions |
| `teal` | `#3fbdb2` | existing fridge — keep, it is our sage |

### Materials — use the existing opts objects

`GLOSS` for painted metal, ceramic, glass, tile. `WOODM` for anything wood.
`STEEL`/`CHROME` for hardware only — chrome on more than two props per room
reads as plastic. Default `mat()` roughness 0.86 is correct for wall, fabric
and matte paint. **Fabric must never take `GLOSS`.**

---

## 3. Prop vocabulary — what a thing IS

This section is the answer to "built-ins read as blocks".

### 3.1 A cabinet run (base or upper)

Minimum six parts. Fewer than six is a block and fails review.

1. **Toe kick** — `box`, 0.16 tall, set back 0.07, colour `cabShade`.
2. **Carcass** — `box`, colour `cabShade`. Never the visible surface.
3. **Face frame** — stiles and rails, 0.09 wide, 0.04 proud of the carcass,
   colour `cab`. Vertical stile between every pair of doors.
4. **Fronts** — `rbox` r=0.02, inset 0.015 inside the frame, colour `cab`,
   with a **0.03 reveal gap** on every side. On shaker fronts add an inner
   panel: a second `rbox` 0.10 smaller each way, 0.015 proud, `cabShade`.
5. **Hardware** — a `box` pull 0.30 × 0.025 × 0.025 in `graphite`, or a `knob`.
   Pulls horizontal on drawers, vertical on doors. Consistent within a run.
6. **Top** — countertop slab or top cap, different material from the fronts,
   overhanging 0.05.

### 3.2 An open shelf / built-in bay

- Shelf boards 0.06 thick, 0.45 deep, edge visible, `cab`.
- Back panel one shade darker (`cabShade`), inset 0.03 — this is what makes a
  bay read as a bay and not a hole.
- Vertical dividers every 0.9–1.2 units.
- **Contents: 3–6 objects per bay, no exceptions.** Drawn from: book blocks
  (a `box` 0.06–0.10 wide, 0.28 tall, leaning at 6–10° every fourth one),
  jars (`cyl` + a smaller lid `cyl`), bowls (`cyl` with a 0.85 top radius),
  stacked plates (three thin `cyl`s), a small plant, a framed 5×7.
- Randomise heights. A shelf where every object is the same height is a comb.

### 3.3 Upholstery (sofa, armchair, bed)

- `rbox` r=0.14–0.18. Fat radii are the whole read; 0.05 looks like a crate.
- Separate meshes: base, back, each arm, and **individual seat cushions** with
  a 0.02 gap between them. One-piece upholstery fails review.
- Two throw pillows minimum on a sofa, `rbox` r=0.10, in an accent, rotated
  8–15° off-axis.
- Legs: four `cyl` r=0.05, 0.14 tall, `wood2` — furniture that meets the floor
  flat reads as a bathtub.

### 3.4 Appliances

- Body `rbox` r=0.05. Door face inset 0.02 with a reveal.
- A handle, always: `cyl` r=0.03 on two stand-offs.
- One dark or glass element (`ink` with `GLOSS`) — oven window, screen, cooktop.
- Feet or a toe recess. Appliances do not sit flush on the floor.

### 3.5 Vehicles — see §6

### 3.6 Bevel radii by class (binding)

| Class | `rbox` r |
|---|---|
| Architecture: walls, plinth, counters, worktops | 0 (use `box`) |
| Casework, appliances, media consoles | 0.04–0.06 |
| Small props: jars, books, boxes, frames | 0.015–0.03 |
| Upholstery | 0.14–0.18 |
| Vehicle bodies | 0.05, with hard chamfers (see §6) |
| Plant pots, bowls | `cyl`, not `rbox` |

---

## 4. Density targets

Per room, verified by counting in the screenshot:

- **Bare floor ≤ 30% of the framed image.**
- Every open shelf bay: 3–6 objects.
- Every horizontal surface larger than 0.5 units²: ≥ 2 props.
- Every wall panel wider than 2 units: at least one of art frame, sconce,
  shelf, clock, hook rail, or a window.
- **Plants: 3 minimum per interior room.** Vary pot material and plant height.
- Exactly one dark anchor object minimum.
- 3–4 accent hues from §2, and no others.
- Every floor-standing object has a contact shadow (`blobShadow` below tier 3;
  real shadows at tier 3 — verify it is actually casting).

### Tiering

Density is a **tier-3 and tier-2** concern. At `low`/`2d` the clutter loop must
not run: guard every content loop with `if (DETAIL >= 2)` (small props) or
`if (DETAIL >= 3)` (the finest layer — book lean, plate stacks, jar lids). The
Pi law is unchanged; a Pi shows the furniture, not the jars.

---

## 5. Camera and composition

### 5.0 Room shape comes before camera (learned the hard way)

Six camera attempts failed to produce a usable mudroom shot on 2026-09-09. The
cause was not framing. The mudroom was 2.2 units wide by 7.2 deep — a corridor
with solid walls down both long sides, its subject (the street door) capping one
short end and its bench on a long wall. **No camera position could see both.**

The law, taken from the plates: **a room is a wide, shallow-to-square box with
two walls and an open corner.** Plates 3, 4, 5 and 6 are all exactly that; it is
what makes the isometric-diorama read possible at all. A room whose depth is
more than about 1.4× its width has no viewing axis and cannot be photographed,
no matter how well it is furnished.

Before framing a room, check its footprint. If the ratio is wrong, the fix is
the floor plan, not the camera. The mudroom was rebuilt as a 5.6-unit square
(garage pushed 3.4 units west) for this reason.

Corollaries:

- The subject wall and the wall holding the room's zone should be **adjacent**,
  not opposite. Put furniture on the two walls that form the closed corner.
- The side the camera looks in through gets no wall, or a wall that joins the
  room's `hide` group — the garage door is the pattern.

### 5.1 Framing

Every room camera must satisfy, verified in the probe shot:

1. The room's **subject wall occupies the upper-left half** of the frame; the
   floor falls away to the lower right. This is the isometric-diorama read all
   ten plates share.
2. **No foreground occluder.** If a tree, wall or roof crosses the near plane,
   the camera is wrong — move the camera, or add the group to the room's `hide`
   list. (Today's garage view fails this: a tree eats the left third.)
3. Subject fills the frame per §4's bare-floor rule.
4. The chat bar sits at the bottom ~90 px of the viewport. Nothing important
   below y=880 of 1000.
5. Camera FOV stays 24. Frame by moving the camera, never by widening the lens.

---

## 5.2 The shadow frustum (read before blaming a material)

`sun.shadow.camera` is a **±10 orthographic box centred on the house**. Anything
outside it either receives no shadow at all or samples the boundary and renders
a **hard diagonal dark edge that looks exactly like a different material**.

This has caused three bugs so far, each of which cost a builder time:

- No vehicle had ever cast a shadow, in any version of the house — the garage
  bay (x −16.7), the driveway (x −15.4) and the kerb (z 19.8) all fall outside
  the box.
- The minivan's roof cap read as a dark navy panel against a light blue body.
  It was not a material: the `u = −10` boundary cuts diagonally across the bay
  at x ≈ −14.1, so half the cap sampled the map and half was forced lit. It was
  diagnosed by temporarily painting the cap magenta.
- The whole garage bay had the same problem, and now disables `receiveShadow`
  on every mesh in it.

**Do not widen the frustum.** Measured: widening to ±40 makes the shadow appear
but coarsens every other room's shadows about 4×. The house's interiors are the
priority.

Until the lighting pass resolves it properly (a second shadow camera for the
yard is the obvious candidate), the workaround for anything outside the box is:
disable `receiveShadow` on the object, and give it a hand-placed multiply disc
for contact. `blobShadow` takes an optional floor-height parameter — the garage
floor is at y 0.035 and the mudroom floor at y 0.03, and shadow discs authored
without it render *underneath* the floor, which is its own silent bug.

**Diagnostic trick worth reusing:** when a surface shades wrongly and you cannot
tell whether it is the material or the light, paint it an impossible colour
(magenta) and re-shoot. If the wrong shading survives, it is the light.

---

## 6. Vehicles (plate 10)

The current cars are extruded blocks and fail. The rebuild is a side-profile
silhouette, not a stack of boxes.

- **Body** — a `T.Shape` traced in side profile (bonnet line, windscreen rake,
  roof, backlight, boot), extruded across the car's width with
  `bevelEnabled: true, bevelThickness: 0.05, bevelSize: 0.05, bevelSegments: 1`.
  One-segment bevels give the hard chamfer of the plate; two or more give soft
  plastic.
- **Glass** — a separate mesh **inset 0.06 inside the body sides**, colour
  `#7fb6d9` with `GLOSS`, so the pillars stand proud. Flush glass is the single
  clearest tell of a block car.
- **Wheel arches** — the body profile cuts an arc over each wheel; the tyre sits
  inside it with 0.04 clearance. No arch = toy.
- **Wheels** — tyre `cyl` in `ink`, plus a rim `cyl` at 0.62 radius in `steel`,
  inset 0.02.
- **Bumpers** — front and rear, a `box` 0.10 deep proud of the body, in
  `cabShade` or the body colour darkened.
- **Grille** — a `box` in `graphite` with 4–6 thin `box` slats at tier 3.
- **Lights** — two `box`es in `#fdf6e3` with `GLOSS` front, two in `oxblood`
  rear.
- **Roof** — the plate's cars have a slightly narrower cabin than the body;
  taper the cabin 0.12 per side.

All seven body types (sedan, suv, truck, minivan, hatch, wagon, van) plus the
school bus must be screenshotted individually before the vehicle pass closes.

---

## 7. Per-room punch list

Numbered items are what the art director has already found. Fixing them is the
floor, not the ceiling — §3 and §4 still apply to everything else in the room.

### Living room (plate 6)

1. **The armchair faces the wall.** Rotate it to face the sofa/hearth at
   roughly 30–40° off the sofa axis, forming a conversation triangle.
2. Furniture is crowded into the top-left corner; two thirds of the room is
   bare plank. Spread the seating group and add a second zone (a reading
   corner, or a console table against the long wall).
3. The built-ins beside the hearth are flat panels. Rebuild per §3.2 with real
   bays, a darker back panel, and books.
4. The TV is a floating black rectangle. Give it a bezel, a stand or bracket,
   and a media console beneath it with two props on top.
5. Wall art: the plate has a grid of five frames. We have none.
6. Plant count is 1. Needs 3.
7. The rug is a white blob under the sofa only. Widen it so both the sofa and
   the armchair have front legs on it, and give it a border stripe.

### Kitchen (plates 7, 8, 9)

1. Bare floor is over half the frame. Pull the camera in and give the
   foreground something — the island is the only object below the counter line.
2. Uppers are plain boxes: no face frame, no reveals, no hardware. §3.1.
3. There is no open shelving anywhere; plates 7 and 9 are half open shelving,
   loaded. Convert at least one upper run to open bays with contents.
4. The backsplash tile field stops short; extend it across the whole run.
5. No hood over the cooktop — every kitchen plate has one, and it is the dark
   anchor.
6. Counter clutter is four small props over a long run. Plates carry a kettle,
   a board with produce, a canister set, a coffee machine, a fruit bowl, a
   utensil crock, and a plant.
7. The window has no sill props; plates 7 and 8 both put plants on the sill.

### Mudroom + pantry

The room was rebuilt on 2026-09-09 as a 5.6-unit square, x ∈ [-12.6, -7.0],
z ∈ [2.6, 8.2] — see §5.0. The garage moved 3.4 units west to make room. The
closed corner is the **north and west** walls; the camera looks in from the
south-east through the street wall, which hides with the roof.

1. Bench, hooks and coat now live on the north wall. They are a plank, four
   posts and three cubes — rebuild them as real objects: a bench with a frame
   and a lower shelf, hooks with a mounting rail, coats with sleeves.
2. Judge against §4 from scratch. The plates want, at minimum: a boot tray with
   two pairs of boots, a shelf above the hooks carrying baskets, an umbrella or
   a bag on a hook, a small mat at the door, a wall light.
3. The west wall is the garage connection and is currently blank — it needs a
   door, and that door needs casing.
4. The pantry closet's shelves must carry §3.2 contents — the honest-empty
   twist only means the *shopping-signal* shelf goes bare, not the whole closet.

### Garage (plates 3, 4, 5)

1. **A tree occludes the left third of the frame.** Camera or `hide` fix.
2. The cars are blocks. §6.
3. Walls are blank. Plate 3 has a pegboard with hanging tools, a tyre, a shelf
   of boxes, a strip light. Plate 4 has a tool board and a tripod lamp.
4. Floor is empty apart from the cars. Plates add a workbench, a tool cabinet,
   a wheelie bin, stacked boxes, a mower.
5. The driveway apron is a flat plane; plate 3 scores it with expansion joints.

### Exterior / yard (plates 1, 2)

1. The plinth is a bare green plane with one tree and one bush. Plate 2 has a
   picket fence, a wicker chair, pots, a paved path and a bordered lawn; plate
   1 lines the whole plinth with planting.
2. The cutaway edge is a raw wall section. Give it a visible wall thickness
   band in `cabShade`, as the plates do.
3. Warm interior light does not read from outside. That is the lighting pass,
   but the geometry must leave the windows glazed and emissive-capable.

---

## 8. The review checklist

A room passes when every line is true of its probe screenshot at
`--quality high`. Anything false is a punch-list item.

- [ ] Bare floor ≤ 30% of the frame
- [ ] No foreground occluder crossing the near plane
- [ ] Subject wall in the upper-left half, floor falling to lower right
- [ ] Every cabinet run has all six parts of §3.1
- [ ] Every open bay has 3–6 objects
- [ ] Every surface > 0.5 u² has ≥ 2 props
- [ ] Every wall panel > 2 u has art, a sconce, a shelf, a clock or a window
- [ ] ≥ 3 plants
- [ ] ≥ 1 dark anchor
- [ ] 3–4 accent hues, no strays
- [ ] Upholstery uses r ≥ 0.14 and has separate cushions
- [ ] No object floats: every floor contact has a shadow
- [ ] Seating faces other seating, not a wall
- [ ] Renders identically at `--quality medium`, degraded but not broken, at
      `low`; 2D fallback untouched
- [ ] Zone keys unchanged: door, radio, pet, board, calendar, counter, fridge,
      window, garage, curb

---

## 9. Working method (binding on set builders)

1. Read this file and the room's punch list.
2. Edit `static/house.js` only. `/kitchen` and `static/kitchen.js` are frozen
   until H4.
3. `node -e "new Function(require('fs').readFileSync('static/house.js','utf8'))"`
   after every edit — a syntax error shows up as a silent 2D fallback.
4. `python tools/house_probe.py --views <room> --quality high --out <dir>`
5. **Look at the screenshot.** Not the code — the screenshot.
6. Iterate. Ten or more rounds is the expectation, not two.
7. Before handing back: run `medium` and `low` once each and confirm neither
   throws.
8. Full sweep `python chauffeur/tools/test.py`, bump `config.yaml`, commit
   `(vX.Y.Z)`, push.
