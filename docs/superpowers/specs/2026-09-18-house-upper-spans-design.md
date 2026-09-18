# The Home — upper stories as spans (massing arc 2b)

Binding spec, user-ratified 2026-09-18 in session. An insert between massing arc 2 (blocks, materials, mirror, the photo pipeline; shipped v2.499.67–v2.499.94) and arc 3 (style kits, spec not written). It replaces one field of the arc-2 block model — the per-block `stories: 1|2` — with a list of **upper spans**, each a run of slots along the street that carries a second story and its own roof. Every prior house law travels with it unchanged: batching, the lifecycle law (mkTex owns textures; cgeo owns geometry), the shell registry, view-volume masking and the roof valleys (`2026-09-16-house-view-volume-masking-design.md`), the facade generator (`2026-09-15-house-facade-generator-design.md`), and the arc-2 rulings recorded in `2026-09-17-house-blocks-materials-design.md` §9.

Spelling: **story / stories**, **upper span**, **wing** (the one-story part of a block beside an upper span), **seam** (the vertical plane where a wing meets an upper span inside one block), **volume** (a run of one block along x with one eave and one roof). Roof language as arc 2: ridge direction and the face the gable shows.

## 1. Why

Arc 2's farmhouse acceptance photo has a two-story centre over the middle third of the main block, with one-story wings either side whose ridge runs along the street. Arc 2 declared "a partial second story" out of scope (§8), wrote the fixture's expected model to what the schema could hold, and recorded at wrap (§9) that the whole-block upper story "is the single biggest resemblance cost in either photo" — it turns a composed front into a barn. There was never a resemblance test; the mapping test proved response→spec plumbing, and the resemblance gate is the user's eyes. The user's eyes said no.

The user asked why stories was a block property rather than a slot property. Answer: a scope cut, not a law. The upper story is fabric built on block rectangles; a stepped upper story needs the roof to break at each step, the room masks to keep working under it, and the block-meet rules to run inside a block as well as between the two blocks. That is this arc.

The user's second question — why doesn't stories apply to the garage block — had a false premise: it does (`storyBox('garage')`, `GARAGE_BLOCK.eave`, story-2 windows on slots 0–5). Upper spans apply to both blocks exactly as `stories` did.

Decisions taken in session, in order: spans run along the street only, always the block's full depth; each span owns its roof (form, ridge, pitch); a block may carry a list of spans; the list is capped only by the face's slot count (the user declined a cap of 2 or 3, aware that every span adds two seams and that the live tests will pin a representative subset rather than the whole space); the hand path is the facade editor's cell editor, so a span reads on the slot strip.

Ruled out (§8): spans with a z extent; a third story; a span's own cladding or colour; rooms, zones or cameras inside an upper (it stays sealed); a wing as a volume with its own footprint (that is a third block, still declined).

## 2. The schema (version 3)

```
house: {
  version: 3,
  mirror, pitch_deg, style, ground, roof, unexpressed,   // unchanged from version 2
  blocks: {
    main:   { depth, roof: {form, ridge, pitch_deg}, cladding, base, body },   // `stories` REMOVED
    garage: { same fields, plus orientation }
  },
  upper: [ { slot: 0..17, span: >= 1, roof: { form: gable|hip, ridge: x|z, pitch_deg: 22.5..35 } } ]
}
```

- `upper` is a top-level layer indexed by the 18-slot table like `ground` and `roof`. The block a span belongs to is derived from its slot (`BLOCK_OF_FACE[slots[slot]['face']]`), never stated. A span may not cross the face boundary between slots 5 and 6; `normalize` splits one that does into two spans with the same roof and writes a note.
- Spans on one face are non-overlapping and sorted by slot. Overlap is resolved by a dedicated `_resolve_upper_spans(spans, notes)` — NOT `_resolve_exclusive`, which keys on `kind` and a rank table that spans do not have, and whose ground/roof behaviour must not change. Priority is LIST ORDER: the first span in `upper` owns its slots; each later span is trimmed to the slots still free on its face, split into two spans if the free run is broken, dropped with a note when nothing is left ("dropped an upper span at slot N: its slots were taken" / "trimmed an upper span at slot N around an earlier span"). After resolution the list is sorted by slot. Two spans that then touch AND carry an identical roof (form, ridge, pitch) are merged into one — there is no seam between them. Two touching spans with different roofs stay two volumes with a seam wall between them (§3). The editor puts the span being edited at the head of the list (§4), which is what makes list order a usable rule.
- `roof` on a span defaults to the block's `roof` when absent — in `normalize`, for hand-fed and legacy input. A model-produced object must state it (§2's validation is strict, as arc 2 rev2 ruled: validation is not normalization). A span's eave is always `2·EXT_TOP4`.
- A story-2 `ground` entry (a `window` with `story: 2`) survives only when its whole slot range lies inside one upper span on that face. Otherwise it is dropped with a note ("dropped a story-2 window at slot N: no upper story there"). This replaces arc 2's rule "the block has two stories".
- A `roof`-layer feature (gable/dormer/shed/hip_end) may not cross a seam. `normalize` trims it to the side that holds its start slot, with a note; a feature trimmed to nothing is dropped. A feature wholly inside an upper span stands on the upper's deck plane (§3).
- `slot_table(blocks, upper)` publishes per-slot `eave`: `2·EXT_TOP4` for a slot covered by an upper span, `EXT_TOP4` otherwise. Python's table and house.js's table stay in step (arc 2's rule); a two-story slot's features are placed off this number in both. **Every call site that publishes a table beside a spec passes BOTH fields**: `active_bundle()`, `house_facades_api` (the saved list), the draft route (`/house?draft=`) and the photo route's draft — today they call `slot_table(spec['blocks'])` and would silently publish one-story eaves under a span. Pinned at the API level (§6), not only on `slot_table` directly.
- **Mapping.** `normalize` reads any version, as arc 2's V1→V2 mapping does today. V2 → V3: `blocks.X.stories == 2` becomes one upper span over block X's whole face with `roof: blocks.X.roof`; `stories == 1` becomes nothing; `stories` is deleted. V1 → V2 → V3 in one read. Saved V1 and V2 facades keep opening through `list_facades`' read-normalize.
- **Canonical** is unchanged in substance: `upper: []`, no spans, one volume per block. What holds byte-for-byte is everything RENDERED and DERIVED — the fabric registry set, the roof piece names, the slot table's geometry (x0/x1/cx/z/eave per slot), the exterior mesh count, `EXTERIOR_HINTS`, the mesh pin. The serialized canonical JSON itself intentionally changes (`version: 3`, `stories` gone from both blocks, `upper: []` added), so `CANONICAL`, `CANONICAL_JS` and any test that compares the canonical dict as a whole are updated in the same commit, not pinned to the V2 bytes.
- `validate_block_model` (V3): `version == 3`; `upper` required (may be `[]`); each entry complete (`slot`, `span`, `roof` with all three fields), `slot` in 0..17, `span >= 1`, `slot + span` within the face that holds `slot`, roof enums and ranges; every entry's block fields as V2 minus `stories`; a model that carries `stories` anywhere is rejected ("blocks.main.stories: removed in version 3, use upper[]"), so a model call cannot hand back the old shape unnoticed. Validation still runs BEFORE `normalize` and rejects whole (arc 2 rev2).

## 3. Geometry (house.js)

**Volumes.** Per block, `blockVolumes(name)` cuts the block's x range at every upper-span edge (the slot table's `x0`/`x1`, which already carry `depth`) into an ordered west→east list `[{x0, x1, eave, roof, upper: bool, k}]`. Wings inherit `blocks[name].roof` at `EXT_TOP4`; uppers carry the span's roof at `2·EXT_TOP4`. Every volume's z range is the block's full `north..south` (with depth). A block with no spans is one wing volume equal to the block, so `FULL_HOUSE`, `GARAGE_BLOCK` and every roof piece build exactly as they do at arc-2 HEAD — `EXTERIOR_HINTS`, the registry pin and the canonical mesh pin are untouched.

**Names.** A block with no spans keeps every fabric name it has today. A block with spans names its volume pieces `<block>_w<k>_*` (wing) and `<block>_u<k>_*` (upper), k the volume index, for roof pieces (`_roof_south`, `_roof_north`, `_roof_west`, `_roof_east`, hip ends), upper walls (`_upper_south`, `_upper_north`, `_upper_west`, `_upper_east`) and gable infills. The registry pin stays an exact canonical set; the span scenarios pin their own exact sets.

**Upper walls.** `storyBox` runs per upper volume rather than per block: south and north walls over `[x0, x1]` from `EXT_TOP4` to `2·EXT_TOP4`, in the block's cladding with the block's corner boards, registered as fabric with no room; the story-2 windows of that span are placed on its south wall (the existing mechanism, keyed on the span's slots). Side walls at `x0` and `x1`:

- A seam inside a block is always upper|wing or upper|upper-with-a-different-roof (same-roof neighbours were merged in `normalize`). The wall on a seam plane belongs to the volume WEST of the seam when both are upper, and to the upper when one is a wing. One wall per seam; two would z-fight and none would be a hole (arc 2's shared-plane rule, now applied to every seam).
- The shared plane x −7.15 is closed by exactly one wall: the taller of the two end volumes touching it (the main block's westmost volume and the garage block's eastmost); on a tie, main. When only one of them is an upper there is nothing to share and that upper builds its own wall over its own z extent. When both are uppers the owner's wall spans `sharedEnd` (the further of the two blocks' faces at each end), exactly as today. `sharedFaceOwner()` reads end-volume eaves instead of block eaves; its callers are unchanged.
- A wing has no upper walls; its ground walls already exist.

**Roofs.** One roof per volume: `shellGable` or the hip form via `roofVault` deck planes over the volume's box `[x0, x1] × [north, south]`, at the volume's eave, form, ridge and pitch, in the block's roof colour. A ridge-`z` upper four slots wide is a 7.4-wide gable showing its end to the street — the farmhouse centre. A ridge-`x` wing beside it has its gable end at the seam, buried in the upper's wall.

**Meet.** `neighbourVolume` and `BLOCK_MEET` generalise from a pair of blocks to a list of volumes. Each volume's roof is clipped by the bounded box of every ADJACENT volume — adjacent along x inside a block (across a seam) and across x −7.15 between the two blocks' end volumes. A neighbour's box is its footprint × ground..its ridge, plus its overhang on the shared side only when that neighbour owns the plane, and the neighbour's own deck planes inside the box (arc 2 rev2, unchanged). `blockRoofsIdentical` becomes a per-pair gate: a pair is left uncut only when its five inputs (depth, form, ridge, pitch, eave) are identical. A wing|upper pair always differs in eave and is always cut. The canonical has two identical volumes across x −7.15 and no seams, so it is uncut exactly as today. No overhang crosses a seam into a taller neighbour.

**Above-eave closure at a seam.** The rectangular seam wall follows §3 ownership. Above its eave, the roof volume that has a vertical end profile on that plane builds the physical closure — a ridge-x gable infill or hip end — and that closure is clipped against the neighbour's bounded box and deck planes exactly as roofs are. A ridge-z roof has no vertical end profile at an x seam and cannot own a non-empty closure merely because it owns the rectangular wall. Consequences, each a pin: wing|upper — the upper owns the wall and the wing's buried infill is omitted; equal-eave ridge-z|ridge-x uppers — the west ridge-z span owns the rectangular wall while the east ridge-x span builds the gable closure clipped to what stands proud of the west deck, so no triangular hole opens; identical roofs at equal eave — merged in normalize, no seam.

**Features.** `deckPlane` for a street feature reads the volume under the feature's start slot, not the block: a dormer inside an upper span sits on the upper roof; one on a wing sits on the wing roof. The porch is a ground overlay and is legal under an upper span. A roof feature never crosses a seam (§2 trims it).

**Vault gate** (finer than arc 2's "any second story caps the block"): an interior partition vaults only when its whole run in x lies under ONE wing volume whose roof is gable with ridge x; under an upper, or crossing a seam, it caps at `EXT_TOP4`. With a full-face span (the V2 equivalent) every partition caps, exactly as today.

**Masks.** Unchanged. `ROOM_AABB_EAVE` keeps the story-1 eave as the room box top; upper volumes are fabric and go through `buildRoomShells` and the room mask like every other convex fabric mesh (arc 2 §3.2). The test is the view, not the shell.

**Mirror.** Free: volumes are derived in house-local space and the root reflection covers them.

**Untouched.** The side garage, the driveway, the bay, markers, cameras, the yard, AO occluders (registry-derived; upper walls are already fabric), the orbit. Spans are x-only and the ground floor does not change.

## 4. The hand path (facade editor, Config → People → Home)

The slot strip is one button per slot showing the cell's ground and roof kinds. It gains:

- A slot inside an upper span is drawn taller and tinted (`facadeCellClass`) and its text gains a `2↑` line, so a span reads on the strip at a glance.
- The cell editor gains an **Upper story** control: `none | two stories`. When set it shows **Upper span** (slots, number input like the ground and roof spans), **Roof** form and ridge, and **Pitch**. `facadeCellApply` writes to `facadeDraft.upper` the way the porch path writes to `ground`.
- Selecting a covered cell that is not the span's start edits THAT span (arc 2 ruling 21 generalised: the selection searches covers and opens on the owner). Setting `none` on any covered cell removes the span.
- **The edited span wins.** When an edit grows a span over slots another span holds, `facadeCellApply` trims the OTHER spans to the slots still free (split or dropped as `_resolve_upper_spans` would), moves the edited span to the head of `facadeDraft.upper`, and re-sorts the rest by slot — so the strip shows the result immediately and the server's list-order rule (§2) reaches the same answer. A visible edit never silently loses to an older span.
- The Story 1 / Story 2 segmented control shows when the selected slot is inside an upper span — `facadeSlotStories(i)` replaces `facadeBlockStories(i)`.
- The Blocks panel's **Stories** select is removed; its function moves to the cell (a full-face span is the old `2`). Everything else in the panel stays. The user approved this move in session (it is a relocation, not a removal: nothing a person could do before is lost).
- A V2 saved facade opens with its full-face span already painted; a V1 facade opens through two mappings.
- Preview in 3D, the draft token and `/house?draft=` are unchanged (they carry the whole spec).

## 5. The photo pipeline

- **Pass 1 prompt.** `blocks.*.stories` is gone. A fraction-based `upper` list is added: `[{"block": "main"|"garage", "at": 0..1, "width": 0..1, "roof": {"form", "ridge", "pitch_deg"}}]`, snapped to slots the way features are. The worked example gains the farmhouse sentence: "a two-story centre showing its gable to the street with one-story wings either side whose ridge runs along the street is main.roof {gable, x} plus upper [{block main, at 0.33, width 0.34, roof {gable, z}}]". A whole-block second story is one span at 0 width 1.
- **Pass 2** is unchanged in shape: one full revised model, now V3, validated then normalized on a copy.
- **Fixtures.** The farmhouse EXPECTED model is rewritten: main roof gable ridge x, one upper span over the centre with gable ridge z, the stacked slot-13 window pair now inside that span, "partial second story" leaves the structural-gap list. The brick EXPECTED model gains `upper: []` and is otherwise unchanged. The mapping test compares the `upper` list as a full sorted list, like ground and roof (arc 2 ruling 19). Recorded responses stay hand-written until a real key run — arc 2's posture, its commands still apply.
- `viewpoint`, `critique_token`, single-flight, `max_models=2`, `_DRAFTS` bound: unchanged.

## 6. Tests

Pure (`tests/test_house_facade.py`):
- `normalize`: `upper: []` default; V2 `stories: 2` → full-face span carrying the block roof, `stories` gone; V1 → V3 through both mappings; a face-crossing span split in two with a note; adjacent same-roof spans merged, adjacent different-roof spans kept; overlap first-wins with a note; span `roof` defaults to the block roof; a story-2 window outside any span dropped with a note and one inside kept; a roof feature crossing a seam trimmed with a note, one trimmed to nothing dropped; slot/span bounds clamped to the face.
- `validate_block_model` V3: rejects `{}`, a model carrying `stories`, a missing `upper`, an incomplete span, a span past its face end, an out-of-enum span roof; the draft is byte-identical after each rejection.
- `slot_table`: per-slot `eave` follows spans; the canonical table is byte-identical to arc-2 HEAD.
- `_resolve_upper_spans`: list-order priority, trim, split, drop, each with its note; `_resolve_exclusive` untouched (its existing pins stay green).
- API-level: `active_bundle()`, the saved-facade list, the draft route and the photo route each publish a slot table whose covered slots carry `eave == 2·EXT_TOP4` for a spec with a span — a pin per call site, against the served JSON.
- Fraction→slot snap for `upper`; the farmhouse mapping asserts ground, roof AND upper as full sorted lists; brick unchanged.
- `list_facades` read-normalizes a stored V1 and a stored V2 row to V3.

Live:
- `test_house_shell_live` — **partial upper on the main block** (span slots 9–12, gable ridge z; wings ridge x): `main_u1_*` walls and roof registered, `main_w0_*`/`main_w2_*` roofs registered, exactly one wall per seam, roof-line audit clean, kitchen and living views unobstructed, and correct wing/upper partition caps. **Two spans on the garage block** (bay slots 0–2 ridge z, mudroom slots 3–5 ridge x): the west span owns the rectangular seam wall; the east ridge-x span builds the non-empty clipped gable closure; the shared plane x −7.15 closes once; the garage door and marker remain reachable.
- `test_house_facade_live` — a full-face span on both blocks preserves the V2 geometry and behavior while using the V3 per-volume registry names.
- `test_house_variants_live` - `two_story` becomes the full-face span; a new `partial_upper` variant (main span 4 slots ridge z + garage span 3 slots ridge z) has its own paired delta; `combined` gains a partial span on each block. Measured values and ceilings are in section 9. `buildMs` law remains `max(1500, base + 250)`.
- Editor pins (the file that holds the cell-editor scenarios today): paint a span from a cell; a span edit from a covered cell edits the owner; growing a span over another trims the other and the edited one heads the list; the story control shows only inside a span; a V2 facade opens with its span painted; the Blocks panel has no Stories select.
- The hand-path reachability rule: every shape the photo pipeline can produce is reachable from the cell editor (a pure test enumerates a farmhouse-shaped V3 through the editor's own apply path).

## 7. Budgets

The canonical rendered geometry is unchanged, so B0 is unchanged and no ceiling is rebaselined. Every variant is paired against a base measured in the same run (arc 2's rule). The `partial_upper` delta is a new number, measured before it is ceilinged and recorded in section 9. Exterior in-frustum meshes, per-view draw calls and texture count follow arc 2 section 7.

## 8. Out of scope

A third story; spans with a z extent; a span's own cladding, base or colour (it inherits the block); rooms, zones or cameras inside an upper (sealed, as arc 2 §2); a wing as its own footprint (a third block: declined); interior refit; the mudroom's sealed street door; the garage room following its block's depth (arc 2 look item); a cross gable that is part of the roof (arc 3).

## 9. Results

Implemented in v2.499.97 on 2026-09-18. Canonical V3/no-upper remained within the existing pixel and live-count pins. Paired geometry/texture deltas over canonical were: mirrored −3/−6, full-face two-story +24/+48, partial upper +62/+124, side garage +3/+6, brick +5/+10, combined +67/+134. Ceilings are +26/+52, +64/+128, and +69/+138 for full-face, partial, and combined respectively. The implementation clarified two impossible or contradictory draft requirements: mixed ridge-z|ridge-x closure follows the roof with the vertical end profile rather than rectangular-wall ownership, and full-face V3 spans preserve V2 geometry and behavior while adopting V3 volume names rather than reproducing legacy registry names. The recorded farmhouse fixtures now carry its partial upper; device verification remains outstanding.

### Prerequisite carried from arc 2's parked list

`roofVault(GARAGE_BLOCK, …, Math.PI / 8)` (house.js ~6182) reads a literal and must read `BLOCK_PITCH` before per-volume roofs are built from it; `hipEndAt`'s local pitch must read `PITCH_FAMILY`. The ridge-z roof-piece rename is subsumed by §3's naming rule.

### Editor and roof follow-up (v2.499.98, 2026-09-18)

User testing exposed restrictions that the initial tests did not exercise. Selecting a cell now keeps that exact slot selected even inside an upper span. Ground edits replace only the selected range on the selected story and preserve the other portions; upper, roof and porch edits retain their own anchors. Applying one layer does not rewrite the others. The editor refreshes from the normalized response so merged or clamped spans do not leave stale anchors.

Garage/mudroom is a room boundary within one roof block, not a roof-span boundary. Roof features can span all six slots; ground features retain the driveway/garage-door rules. Both blocks now show room labels under their block heading. Slot counts remain derived from fixed block widths; changing house width or grid resolution is a separate capability and was not added here.

Covered flat porches now build their missing deck. Porch roofs also accept `shed` and `mixed`; mixed uses one sloped cover plus a smaller gable, positioned by `gable_offset` and `gable_span` within the porch. The two roof surfaces are clipped at their intersection. Ordinary non-porch gables terminate at the wall face plus the normal eave overhang, rather than projecting 2.2 units into the yard. Dormer bodies and roofs extend back to the parent roof intersection. Buried-feature clipping uses the parent volume under the feature, not the intersection of every volume in its block.

These changes close the reported editor/roof gaps. They do not establish full visual equivalence with both reference photos. Fixed block widths, roof-material differences and unsupported house shapes remain separate representation limits. Browser screenshots were inspected at high quality; wall-panel verification remains outstanding.
