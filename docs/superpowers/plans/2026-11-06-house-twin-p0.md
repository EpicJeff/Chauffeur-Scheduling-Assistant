# House digital twin, P0 (pool house to the bar) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **This repository's standing split (memory `codex-coordination`):** Claude writes each task's tests first and confirms they fail, Codex implements, Claude reviews, runs the gate and commits. Never Codex reviewing Codex work.

**Goal:** Generate the pool house and its yard from the user's drawings and photos through Chauffeur's own model calls, draw it at a Low (Raspberry Pi 5) and a High (discrete GPU) tier on a hidden preview page, and improve the yard with a cost-tracked art-director loop until the user says it looks right.

**Architecture:** Python owns the plan: a validated plan file (`services/twin_plan.py`), its storage, sources and history (`twin_store.py`), model drafting from drawings and photos (`twin_draft.py`), deterministic composition rules for the yard (`twin_compose.py`), the critic (`twin_director.py`) and a cost ledger with checkpoints (`twin_cost.py`). The browser only draws: a deterministic plan-to-three.js generator, a yard builder and tier presets under `static/twin/`, mounted by `/house/twin`. Model output is always plan data, never geometry.

**Tech Stack:** FastAPI, SQLite-backed settings via `services/storage.py`, `services/model_pools.py`, `pypdfium2` + `Pillow` (new) for PDF pages; three.js r187 ES modules and `@dgreenheck/ez-tree` 1.1.0, both vendored; Poly Haven CC0 assets fetched once and cached.

**Spec:** `docs/superpowers/specs/2026-11-06-house-digital-twin-design.md` (P0 in section 13; plan file section 7; generation section 8; tiers 9.2; cost 8.6). Read it first. Spike to learn from, never to copy wholesale: `.superpowers/spike-poolhouse/` (git-ignored).

## Global Constraints

- Units in the plan are feet; world mapping X = plan x, Y = up, Z = -(plan y); the generator builds in feet and scales the root by 0.3048.
- No `transmission` (or any feature that adds a scene pre-pass) on any material. Glass and water are transparent `MeshStandardMaterial`s (memory `house-render-headroom`).
- Model output is plan data only. The director may change `site` and `materials`; it may never change `buildings`.
- Every asset is CC0 or MIT, listed in the library manifest with its source URL and licence. Nothing is invented.
- No spend cap up front. Every model call is costed. Checkpoints at a running total of **$10, $25, $50** stop all twin model calls until acknowledged. Director rounds are capped at **5 per run**.
- The twin is not a selectable House experience in P0: the only entry is `/house/twin`. `house.html`, `house.js` and the `house_hybrid_enabled` setting are untouched.
- No browser dialogs: `showGlobalAlert`, `promptConfirm`, `promptInput` from `templates/components/control_center.html`.
- Page JS fetches `base() + 'api/...'`, never `/api/...` (memory `no-root-relative-api-urls-under-ingress`).
- Every new route gets a rule in `services/auth.py` RULES; `tests/test_auth.py` `scenario_a_every_route_is_classified` must stay green.
- Every HA touchpoint degrades gracefully; P0 has none beyond reading HA area names (Task 6), which must be skipped silently with no HA.
- UI work reads `chauffeur/docs/ui_design_guide.md` first. After any template class change run `python tools/build_tailwind.py`.
- Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset. Run the task's own tests plus named neighbours; never the full sweep.
- Commit per task with no version bump; Task 10 bumps `chauffeur/config.yaml` to **2.499.763** and writes the `system_capabilities.md` entry.

## Review Focus

1. **A drawing set the model half-reads** (unlabelled rooms, a scanned sheet, an opening wider than its wall): the plan must still normalise into something drawable with notes, never a 500 or a blank page. Pinned in Task 1 (`scenario_bad_openings_are_dropped_with_notes`) and Task 6 (`scenario_a_partial_model_answer_still_drafts`).
2. **The ledger crossing a checkpoint in the middle of a run** (a round that starts at $9.80 and ends at $10.40): the next call must stop, the round's result must still be saved. Pinned in Task 3 (`scenario_a_round_that_crosses_a_checkpoint_is_kept`).
3. **A model priced at nothing** (a new model id absent from the price table): it must cost at the highest known rate, not $0, so checkpoints still fire. Pinned in Task 3 (`scenario_unpriced_models_cost_at_the_highest_rate`).
4. **Re-running composition after hand or director edits:** compose must replace only its own items and never resurrect what a person or the director removed. Pinned in Task 5 (`scenario_compose_is_idempotent_and_keeps_foreign_items`) and Task 8 (`scenario_director_rounds_do_not_rerun_compose`).
5. **The Pi panel with no network to Poly Haven:** the page must still draw from cached assets, and an uncached asset falls back to a plain kit colour, never an endless spinner. Pinned in Task 4 (`scenario_missing_asset_falls_back`) and Task 7 (`scenario_page_draws_with_the_library_offline`).

---

### Task 1: The plan schema

**Files:**
- Create: `chauffeur/services/twin_plan.py`
- Create: `chauffeur/tests/fixtures/twin_poolhouse.plan.json` (the spike's `poolhouse.plan.json` converted to schema 1: `schema`, `materials` as kit references, `site.lot` added from the plot plan, planting and furniture removed so composition owns them)
- Test: `chauffeur/tests/test_twin_plan.py`

**Interfaces:**
- Produces:
  - `SCHEMA = 'chauffeur.twin.plan/1'`
  - `CAPS = {'walls': 400, 'openings': 400, 'rooms': 120, 'planting': 300, 'furniture': 120, 'beds': 60}`
  - `normalize(raw: dict) -> tuple[dict, list[str]]`; raises `ValueError` only when no building survives or `units != 'ft'`.
  - `merge_director(plan: dict, revised: dict) -> tuple[dict, list[str]]`: takes `site` and `materials` from `revised`, keeps `buildings`, normalises the result.
  - `diff_paths(a: dict, b: dict) -> list[str]`: dotted leaf paths that differ, list indices as `[i]`, sorted.
  - Plan shape: `{schema, units, materials: {role: {id, color}}, buildings: [{id, name, position:[x,y], levels:[{id,name,elevation,ceiling}], walls:[{id,level,from,to,thickness,height,exterior}], openings:[{wall|gable, kind, at|x, width, sill, head, panels?, split?, glass?}], rooms:[{name,level,polygon,ha_area?}], stairs:[...], roof:{main:{...}, extensions:[...]}, porch?, fixtures:[...], lights:[{room,kind,at,level}]}], site: {lot:[[x,y],...], ground, hardscape:[...], pool?, fire_pit?, beds:[...], fence?, planting:[{kind,preset,at,height,seed,by?}], furniture:[{asset,at,rotation,by?}], edges:[...]}}`

- [ ] **Step 1: Write the failing tests** (`harness.check`, `scenario_*` functions and the runner block, as in `tests/test_house_facade.py`)

```python
def scenario_the_fixture_normalizes_clean():
    plan, notes = tp.normalize(_fixture())
    check(plan['schema'] == tp.SCHEMA and notes == [], notes)
    b = plan['buildings'][0]
    check([l['id'] for l in b['levels']] == ['L1', 'L2'], 'levels sorted by elevation')
    check(b['roof']['main']['pitch'] == 11, 'pitch kept')

def scenario_bad_openings_are_dropped_with_notes():
    raw = _fixture(); raw['buildings'][0]['openings'].append(
        {'wall': 'front', 'kind': 'window', 'at': 30.5, 'width': 4, 'sill': 3, 'head': 7})
    plan, notes = tp.normalize(raw)
    check(len(plan['buildings'][0]['openings']) == len(_fixture()['buildings'][0]['openings']), 'overhang dropped')
    check(any('front' in n and 'outside' in n for n in notes), notes)

def scenario_defaults_and_degenerate_walls():
    # exterior thickness defaults to 0.5, interior to 0.33; a zero-length wall is dropped with a note
def scenario_caps_stop_runaway_lists():
    # 500 planting entries -> 300 kept, one note naming the cap
def scenario_units_must_be_feet():
    # units 'm' raises ValueError; no buildings raises ValueError
def scenario_merge_director_never_touches_buildings():
    # revised with a changed wall and a new bed: wall unchanged, bed present
def scenario_diff_paths_names_leaves():
    # changing materials.siding.color and buildings[0].walls[2].height -> exactly those two paths
```

- [ ] **Step 2: Run** `python tests/test_twin_plan.py`. Expected: FAIL, `No module named 'services.twin_plan'`.
- [ ] **Step 3: Implement `twin_plan.py`.** Pure module (no storage, no network). Openings must lie within `[0, wall length]` and `sill < head <= wall height` (gable openings within the roof span); rooms need three or more points; `roof.main.pitch` in `(0, 24]`.
- [ ] **Step 4: Run** `python tests/test_twin_plan.py`. Expected: every scenario `ok`.
- [ ] **Step 5: Commit** `feat(twin): plan schema, normalisation and the pool house fixture`.

---

### Task 2: Storage, sources, PDF pages and the plan routes

**Files:**
- Create: `chauffeur/services/twin_store.py`, `chauffeur/services/twin_pdf.py`
- Modify: `chauffeur/requirements.txt` (add `pypdfium2` and `Pillow`), `chauffeur/main.py` (routes), `chauffeur/services/auth.py` (RULES)
- Test: `chauffeur/tests/test_twin_store.py`

**Interfaces:**
- Consumes: `twin_plan.normalize`, `twin_plan.diff_paths`.
- Produces:
  - `twin_pdf.render_pages(pdf: bytes, dpi: int = 150, max_side: int = 2048, max_pages: int = 16) -> list[dict]`, each `{'page': int (1-based), 'mime': 'image/png', 'b64': str}`.
  - `twin_store.DATA_DIR`: `os.path.join(os.path.dirname(storage.DB_PATH), 'twin')`. Plans per round live in `DATA_DIR/rounds/<n>.json`; the settings key `house_twin` holds `{current: int|None, rounds: [{id, kind, created, note, cost, run}], fixes: [...], sources: [...]}`.
  - `current() -> dict | None`, `current_id() -> int | None`, `rounds() -> list[dict]` (each row also carries `stale: bool`), `push_round(plan: dict, kind: str, note: str = '', cost: float | None = None, run: str | None = None, base: int | None = None) -> int` (kind in `'draft', 'director', 'hand', 'revert'`). When `base` is given and is not `current_id()`, the round is saved with `stale: True` and the current pointer does NOT move: a delayed model result never overwrites newer work; it stays in the list for review. `revert(round_id: int) -> dict` (pushes a `'revert'` round copying that plan), `save_hand_edit(plan: dict, reason: str, base: int | None = None) -> int` (normalises, logs one fix per `diff_paths` entry, pushes a `'hand'` round; raises `StaleRound` when `base` is stale), `fixes() -> list[{path, before, after, reason, round, at}]`.
  - One module-level `threading.Lock` serialises every mutation: round id allocation, the round file write (temp file then rename), the settings row and the fix log.
  - `save_source(kind: str, filename: str, data: bytes) -> str` (kind in `'drawing', 'photo'`; drawings are rendered to pages once at upload), `sources() -> list[{id, kind, filename, pages}]`, `source_images(source_id: str, pages: list[int] | None = None) -> list[{'mime','b64'}]`.
  - Routes: `GET /api/house/twin` -> `{plan, rounds, kit_id}` (WALL_OR_SERVICE); `POST /api/house/twin/sources` multipart `kind`, `file` -> source row (PARENTS); `GET /api/house/twin/sources` (PARENTS); `PUT /api/house/twin/plan` body `{plan, reason, base}` -> `{round}`, 409 when `base` is stale (PARENTS); `POST /api/house/twin/revert` body `{round}` (PARENTS); `GET /api/house/twin/fixes` (PARENTS).

- [ ] **Step 1: Write the failing tests.** Use `CHAUFFEUR_DATA_DIR` set to a temp dir before imports, and FastAPI `TestClient` against `main.app` as an authenticated parent (see how `tests/test_house_facade.py` `scenario_routes_and_template` authenticates).

```python
def scenario_pdf_pages_render():
    # a two-page PDF built with pypdfium2.PdfDocument.new() -> two PNGs, pages 1 and 2, long side <= 2048
def scenario_rounds_push_and_revert():
    r1 = ts.push_round(plan_a, 'draft'); r2 = ts.push_round(plan_b, 'director')
    r3 = ts.revert(r1)
    check(ts.current() == plan_a and [r['kind'] for r in ts.rounds()] == ['draft', 'director', 'revert'], ts.rounds())
def scenario_hand_edits_log_each_changed_leaf():
    # change siding colour and one wall height via save_hand_edit -> two fixes with before/after and the reason
def scenario_routes_round_trip_through_the_app():
    # upload a PDF -> GET sources shows pages; PUT plan -> GET plan returns it; revert route works; fixes route lists the edit
def scenario_an_unparseable_upload_is_a_400_not_a_500():
```

- [ ] **Step 2: Run** `python tests/test_twin_store.py`. Expected: FAIL on import.
- [ ] **Step 3: Implement** `twin_pdf.py` (pypdfium2 render, Pillow downscale and PNG encode), `twin_store.py`, the routes and their RULES entries. Uploads larger than 40 MB are a 413.
- [ ] **Step 4: Run** `python tests/test_twin_store.py` and `python tests/test_auth.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): plan storage, rounds, hand-edit log, drawing and photo sources`.

---

### Task 3: The cost ledger and checkpoints

**Files:**
- Create: `chauffeur/services/twin_cost.py`
- Modify: `chauffeur/services/model_pools.py` (`call_pool_json` and `_call_chain`/`_call_candidates` gain `usage: list = None`), `chauffeur/services/llm.py` only if `call_model` does not already forward `metrics`; `chauffeur/main.py`; `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_cost.py`

**Interfaces:**
- Produces:
  - `model_pools.call_pool_json(..., usage: list = None)`: when a list is passed, each provider request appends `{'model': str, 'input_tokens': int, 'output_tokens': int}` from the request's metrics (`promptTokenCount`; `candidatesTokenCount` plus `thoughtsTokenCount` when present). Existing callers are unchanged.
  - Every twin model call passes `max_models=1`, so one `call_pool_json` is at most one provider request and the checkpoint is checked before every request (Codex review: a pool can otherwise launch a second billed candidate after the first crossed a checkpoint).
  - A dispatched request whose usage never came back (timeout after send, decode failure) still appends a usage entry with `input_tokens` and `output_tokens` set to `None`; `record` costs it conservatively: input estimated as 1,600 tokens per image plus prompt characters / 4, output as the call's `max_output_tokens`, both at the highest rate. So usage entries carry `images: int`, `prompt_chars: int`, `max_output_tokens: int`, and ledger entries carry `basis: 'reported' | 'estimated'`.
  - `twin_cost.PRICES: dict[str, tuple[float, float]]` (USD per million input and output tokens, keyed by the prefixed model id `model_pools` returns). Fill from each provider's pricing page on the day of implementation, with that date in a comment.
  - `twin_cost.CHECKPOINTS = (10.0, 25.0, 50.0)`, `ROUND_CAP = 5`.
  - `price(model: str, input_tokens: int, output_tokens: int) -> tuple[float, bool]` (`bool` = priced; unpriced models use the highest rate in `PRICES` for each side).
  - `record(stage: str, usage: list[dict], run: str | None = None) -> list[dict]` (entries `{stage, model, input_tokens, output_tokens, usd, priced, run, at}`, stored under settings key `house_twin_cost`).
  - `total() -> float`, `blocking_checkpoint() -> float | None` (smallest checkpoint `<= total()` not acknowledged), `acknowledge(checkpoint: float) -> None`.
  - `require_clear() -> None` raises `CheckpointReached` (attribute `checkpoint: float`, `total: float`) when a checkpoint blocks.
  - Routes: `GET /api/house/twin/cost` -> `{total, entries, blocking}`; `POST /api/house/twin/cost/ack` body `{checkpoint}` (both PARENTS).

- [ ] **Step 1: Write the failing tests.**

```python
def scenario_price_and_record():
    usd, priced = tc.price(KNOWN, 1_000_000, 0)
    check(priced and usd == tc.PRICES[KNOWN][0], usd)
def scenario_unpriced_models_cost_at_the_highest_rate():
    usd, priced = tc.price('anthropic:not-a-model', 1_000_000, 1_000_000)
    check(not priced and usd == max(p[0] for p in tc.PRICES.values()) + max(p[1] for p in tc.PRICES.values()), usd)
def scenario_checkpoints_block_until_acknowledged():
    # record usage worth $10.01 -> require_clear raises with checkpoint 10.0; acknowledge(10.0) -> clear; $25.01 -> blocks at 25.0
def scenario_a_round_that_crosses_a_checkpoint_is_kept():
    # total $9.80, record a $0.60 round -> entries saved, total $10.40, blocking == 10.0
def scenario_missing_usage_is_costed_conservatively():
    # a usage entry with None tokens, images=2, prompt_chars=4000, max_output_tokens=8192 -> basis 'estimated', usd at the highest rates for 4200 in / 8192 out
def scenario_call_pool_json_reports_usage():
    # stub llm.call_model to fill metrics; usage list gets one entry per provider request, including a failed first candidate
def scenario_cost_routes():
```

- [ ] **Step 2: Run** `python tests/test_twin_cost.py`. Expected: FAIL on import.
- [ ] **Step 3: Implement.** Thread `usage` through without changing any existing call's behaviour.
- [ ] **Step 4: Run** `python tests/test_twin_cost.py`, then the neighbours `python tests/test_model_pool_providers.py`, `python tests/test_model_pool_overload.py`, `python tests/test_llm_budget.py` and `python tests/test_house_facade.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): per-call cost ledger with $10/$25/$50 checkpoints`.

---

### Task 4: The asset library and the first style kit

**Files:**
- Create: `chauffeur/twin_library/manifest.json`, `chauffeur/twin_kits/modern_farmhouse.json`, `chauffeur/services/twin_library.py`
- Modify: `chauffeur/main.py`, `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_library.py`

**Interfaces:**
- Produces:
  - Manifest entries: `{id, kind: 'material'|'model'|'hdri', source: 'polyhaven', source_id, licence: 'CC0', files: {name: url}, cost: {triangles?, texture_px}}`. P0 set, chosen from the photos (spec 8.1): board-and-batten painted siding colour role (geometry, no texture), standing-seam metal (geometry), travertine French pattern pavers, stacked ledgestone, white beadboard, dark stone counter, mulch, artificial turf, lawn, cedar, mahogany door stain, brushed stainless; outdoor furniture and fixtures as Poly Haven models where a match exists (lounger substitute, rocking chairs, outdoor table set, planters, lantern sconce); day and dusk HDRIs. Every entry with its Poly Haven page URL.
  - Kit: `{id: 'modern_farmhouse', materials: {role: {asset, color}}, shrubs: [ez-tree preset names], backdrop_trees: [...], specimen_trees: [...], furniture: {role: asset}, composition: {...}, style_guide: str}`. `composition` values: `foundation_bed_depth_ft: 5`, `shrub_spacing_ft: 3.5`, `shrub_height_ft: [3, 4.5]`, `group_sizes: [3, 5]`, `door_clearance_ft: 3`, `pool_clearance_ft: 2`, `backdrop_min_building_ft: 25`, `backdrop_spacing_ft: 16`, `backdrop_jitter_ft: 4`, `backdrop_rows: 2`, `backdrop_row_gap_ft: 10`, `backdrop_height_ft: [45, 70]`. `style_guide` is the critic's brief: layering, odd groups, no bare expanses, edges softened, nothing toy-like, finishes as in the household photos.
  - `twin_library.ensure(asset_id: str) -> str` (local directory under `twin_store.DATA_DIR/library/<id>/`; downloads every file once with a `User-Agent` header; Poly Haven refuses the default one), `kit(kit_id: str) -> dict`, `manifest() -> dict`.
  - Route: `GET /api/house/twin/library/{asset_id}/{name}` serves a cached file, calling `ensure` on a miss; 404 when the fetch fails (WALL_OR_SERVICE). `GET /api/house/twin/kit/{kit_id}` (WALL_OR_SERVICE).

- [ ] **Step 1: Write the failing tests.**

```python
def scenario_manifest_is_licensed_and_complete():
    # every entry has source, source_id, licence in {'CC0','MIT'} and at least one file url
def scenario_kit_references_resolve():
    # every kit material/furniture asset id exists in the manifest; every plant preset is one of EZ-Tree's 15 preset names
def scenario_ensure_downloads_once():
    # stub urllib opener; two ensure() calls -> one fetch per file; the request carried a User-Agent
def scenario_missing_asset_falls_back():
    # fetch raises -> route returns 404 quickly, and ensure() leaves no partial directory behind
```

- [ ] **Step 2: Run** `python tests/test_twin_library.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Writes go to a temp directory, then rename, so a failed fetch leaves nothing half-written.
- [ ] **Step 4: Run** `python tests/test_twin_library.py` and `python tests/test_auth.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): vetted CC0 asset library and the modern farmhouse kit`.

---

### Task 5: Composition rules

**Files:**
- Create: `chauffeur/services/twin_compose.py`
- Test: `chauffeur/tests/test_twin_compose.py`

**Interfaces:**
- Consumes: plan from Task 1, kit from Task 4.
- Modify also: `chauffeur/services/twin_plan.py`: the schema gains `site.compose_overrides: {removed: [id], moved: {id: [x, y]}}` (default empty), and `record_compose_overrides(before: dict, after: dict) -> dict` returns `after` with overrides updated (a compose id present before and absent after joins `removed`; a compose item whose `at` changed joins `moved`). `twin_store.save_hand_edit` calls it; Task 8 wires `merge_director`.
- Produces: `compose(plan: dict, kit: dict, seed: int = 1) -> tuple[dict, list[str]]`. Every item it adds to `site.beds`, `site.planting` and `site.edges` carries `"by": "compose"` and a stable `"id"` of the form `cmp-<rule>-<n>` (same plan, kit and seed give the same ids). A rerun first removes only `by == "compose"` items, regenerates, then applies `site.compose_overrides`: ids in `removed` are not re-added, ids in `moved` take the stored position. Uses `random.Random(seed)`.
  - Foundation beds `foundation_bed_depth_ft` deep along each exterior wall, except where hardscape, a porch or another bed already touches the wall, and broken around doors (`sill == 0`) by `door_clearance_ft`.
  - Shrubs in each bed at `shrub_spacing_ft`, in consecutive groups of one preset whose size is drawn from `group_sizes`, heights within `shrub_height_ft`.
  - A backdrop tree line inside `site.lot` along every lot edge at least `backdrop_min_building_ft` from any building: `backdrop_rows` rows `backdrop_row_gap_ft` apart, spacing `backdrop_spacing_ft ± backdrop_jitter_ft`, heights within `backdrop_height_ft`.
  - `site.edges`: polylines where lawn meets hardscape or a bed (for edge grass).
  - Nothing is placed inside a building, hardscape, the pool plus `pool_clearance_ft`, or another plant's trunk radius.

- [ ] **Step 1: Write the failing tests** (on the Task 1 fixture plus the Task 4 kit).

```python
def scenario_compose_is_deterministic():
    a, _ = tc.compose(plan, kit, seed=7); b, _ = tc.compose(plan, kit, seed=7)
    check(a == b, 'same seed, same yard')
def scenario_compose_is_idempotent_and_keeps_foreign_items():
    # add a hand planting without 'by'; compose twice -> hand item present once, compose items identical to a single run
def scenario_removed_and_moved_compose_items_survive_recompose():
    # delete one compose shrub and move another (record_compose_overrides), recompose -> the deleted id stays gone, the moved one keeps its new 'at'
def scenario_beds_hug_the_walls_and_skip_doors():
    # every compose bed touches an exterior wall, depth == 5, no bed within 3 ft of a sill-0 opening
def scenario_shrub_groups_are_odd():
    # consecutive same-preset runs along each bed have length 3 or 5 (the last run may be shorter only when the bed ends)
def scenario_nothing_lands_where_it_cannot():
    # no plant inside the footprint, the patio, the pool or within 2 ft of the pool edge
def scenario_backdrop_lines_far_edges_only():
    # backdrop trees only along lot edges >= 25 ft from the pool house; two rows
```

- [ ] **Step 2: Run** `python tests/test_twin_compose.py`. Expected: FAIL.
- [ ] **Step 3: Implement** with plain polygon maths (point-in-polygon, segment distance); no new dependency.
- [ ] **Step 4: Run** `python tests/test_twin_compose.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): deterministic yard composition from the kit's rules`.

---

### Task 6: Drafting the plan from drawings and photos

**Files:**
- Create: `chauffeur/services/twin_draft.py`
- Modify: `chauffeur/services/model_pools.py` (`TIER_CHAINS['twin'] = ['pro']`, with the comment that says only `mission` touches `pro` updated to name `twin` too), `chauffeur/main.py`, `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_draft.py`

**Interfaces:**
- Consumes: `twin_store.source_images`, `twin_cost.require_clear/record`, `twin_plan.normalize`, `twin_compose.compose`, `twin_library.kit`, `ha_api.get_area_registry` (optional).
- Produces:
  - `draft(drawings: list[dict], photos: list[str], site: dict | None, kit_id: str = 'modern_farmhouse') -> tuple[dict | None, list[str], str | None]` returning `(result, notes, error)`; `drawings` and `site` items are `{'id': source_id, 'pages': [int]}`. `result = {'round': int, 'plan': dict, 'cost': float}`.
  - Three foreground model calls through `model_pools.call_pool_json('twin', ..., strict_json=True, usage=...)`, each preceded by `require_clear()` and followed by `record(stage, usage, run)`:
    1. `'building'`: drawing pages, giving `buildings` (walls, openings, rooms, stairs, roof, porch, fixtures, lights from an electrical sheet). Rooms the drawings leave unnamed take HA area names when HA is reachable (passed in the prompt as a list); with no HA, they get descriptive names.
    2. `'finishes'`: photos plus the kit's material roles and allowed assets, giving `materials` (asset ids from the kit only, colours as hex).
    3. `'site'`: the plot plan pages, giving `site.lot`, hardscape, pool, fire pit, and building positions on the lot.
  - Each completed stage's result is persisted under the run (`DATA_DIR/runs/<run>/<stage>.json`) before the next stage starts. `draft(..., run=<id>)` with an existing run skips stages already stored, so a draft stopped at a checkpoint resumes after acknowledgement without paying for finished stages again. The signature becomes `draft(drawings, photos, site, kit_id='modern_farmhouse', run: str | None = None)`; the route body takes an optional `run` and the 409 body returns it.
  - Then `normalize`, `compose`, `push_round(plan, 'draft', note, cost, run, base=<current id when the draft started>)`.
  - Prompts are module constants (`BUILDING_PROMPT`, `FINISHES_PROMPT`, `SITE_PROMPT`) stating the schema fragment each call must return, feet, the axes rule, and "return only what the drawings show; omit what you cannot read".
  - Route: `POST /api/house/twin/draft` body `{drawings, photos, site, kit}` -> `{result, notes}`; 409 with `{checkpoint, total}` on `CheckpointReached`; 409 while a draft is already running (PARENTS).

- [ ] **Step 1: Write the failing tests** with `model_pools.call_pool_json` stubbed (pattern: `tests/photo_helpers.py`).

```python
def scenario_three_stages_build_one_round():
    # stubbed answers for building/finishes/site -> one 'draft' round; plan has buildings, materials, site; compose items present
    # cost ledger has three entries with stages 'building','finishes','site'
def scenario_a_partial_model_answer_still_drafts():
    # finishes stage returns an error -> round still saved with kit default materials and a note naming the failed stage
def scenario_finishes_outside_the_kit_are_replaced():
    # model names an asset not in the kit -> kit default for that role, with a note
def scenario_checkpoint_stops_before_the_next_stage():
    # ledger at $9.99, building stage costs $0.02 -> finishes stage never called, route answers 409 {checkpoint: 10.0, total, run}
def scenario_a_stopped_draft_resumes_without_repaying():
    # after the 409, acknowledge(10.0) and draft(run=<same>) -> the building stub is NOT called again; finishes and site are; one draft round
def scenario_each_stage_is_one_provider_request():
    # call_pool_json is called with max_models=1 for every stage
def scenario_no_ha_still_names_rooms():
    # ha_api raises -> draft succeeds, rooms named
def scenario_draft_route_runs_through_the_app():
```

- [ ] **Step 2: Run** `python tests/test_twin_draft.py`. Expected: FAIL.
- [ ] **Step 3: Implement.** Page images go in `images=[{'mime','b64'}]`; at most 16 pages per call.
- [ ] **Step 4: Run** `python tests/test_twin_draft.py`, `python tests/test_twin_cost.py`, `python tests/test_auth.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): draft the plan from drawings, photos and the plot plan`.

---

### Task 7: The generator, the yard, the tiers and the preview page

**Files:**
- Create: `chauffeur/static/vendor/three-r187/` (`three.module.js`, `three.core.js`, and only the addons used: `controls/OrbitControls.js`, `loaders/GLTFLoader.js`, `loaders/HDRLoader.js`, `utils/BufferGeometryUtils.js`, `lights/RectAreaLightUniformsLib.js` and its `RectAreaLightTexturesLib.js`), `chauffeur/static/vendor/ez-tree/ez-tree.es.js` (1.1.0, MIT, licence file beside it)
- Create: `chauffeur/static/twin/twin_generator.js`, `twin_yard.js`, `twin_tiers.js`, `twin_library.js`, `twin_view.js`; `chauffeur/templates/house_twin.html`
- Modify: `chauffeur/main.py` (`GET /house/twin`), `chauffeur/services/auth.py` (`(ANY, '/house/twin', ANYONE, None)`, as `/house`), `chauffeur/tests/live_app.py` (`browser()` gains a `launch_args: list[str] | None = None` keyword passed to `chromium.launch(args=...)`; existing callers unchanged)
- Test: `chauffeur/tests/test_twin_view_live.py` (uses `tests/live_app.py` `live_app`, as `tests/test_house_facade_live.py` does; Chromium launched with `--use-angle=gl --enable-gpu --ignore-gpu-blocklist`, memory `house-render-headroom`)

**Interfaces:**
- Consumes: `GET /api/house/twin`, `GET /api/house/twin/kit/{id}`, library route.
- Produces:
  - `twin_tiers.js`: `export const TIERS = { low: {...}, high: {...} }` and `export function pickTier(search: URLSearchParams, gl: WebGL2RenderingContext) -> 'low' | 'high'` (`?tier=` wins; otherwise `low` when the renderer string names a VideoCore/V3D GPU or `navigator.hardwareConcurrency <= 4`). Low: pixel ratio 1, no antialias, no shadow map, trees as two crossed alpha cards baked once per preset, shrubs at most 300 leaves, no room rect lights in daylight, budget **≤ 120 draw calls and ≤ 200k triangles** at the front camera. High: pixel ratio `min(devicePixelRatio, 2)`, antialias, one 4096 sun shadow, full EZ-Tree plants, rect lights at night.
  - `twin_library.js`: `export function libUrl(assetId, name)` (built on `base()`, then passed through `window.chfAuthUrl` when it exists, because loader image requests bypass nav.html's fetch wrapper; house_twin.html includes nav.html's auth helpers as house.html does), `export function kitMaterial(role, kit, tier) -> THREE.Material` (falls back to a plain `MeshStandardMaterial` in the kit colour when a texture fails).
  - `twin_generator.js`: `export function buildTwin(plan, kit, tier) -> { root, groups: { site, roof, gableFull, gableCut, lights, levels: { [levelId]: THREE.Group } }, roomLights }`. Ports the spike's wall, opening, gable, roof (pitch change, awning), stair, porch and fixture builders, with the spike's merge helper, upstairs walls clipped under the roof, and cut gables for floor views. All static geometry merged per material.
  - `twin_yard.js`: `export async function buildYard(plan, kit, tier) -> { group, triangles }` (EZ-Tree presets by seed, scaled to `height`; library models; beds; fence; edge grass along `site.edges` as instanced blades in High, omitted in Low).
  - `twin_view.js`: `export async function mountTwin(el, { plan, kit, tier }) -> view` with `view.setView('ext' | levelId)`, `view.setTime('day' | 'night')`, `view.setCamera('front' | 'porch' | 'rear' | 'top')`, `view.capture(names: string[], width = 1280, height = 800) -> Promise<string[]>` (PNG data URLs), `view.stats() -> { drawCalls, triangles, tier }`, `view.rebuild(plan)`, `view.dispose()`; sets `window.__twin = view`.
  - `house_twin.html`: full-bleed canvas, the view/time/camera chips, a tier badge, and the parent tools sheet (Task 8 fills it); loads modules via an import map pointing at the vendored files.

- [ ] **Step 1: Write the failing live tests.** Seed the fixture **after `twin_compose.compose(plan, kit, seed=1)`**, so the budget includes the composed yard, through `PUT /api/house/twin/plan`; library textures stubbed small, EZ-Tree plants real; print the renderer string.

```python
def scenario_page_boots_and_draws_the_pool_house():
    # /house/twin?tier=high -> window.__twin present; mesh count > 0; no console errors
def scenario_no_material_uses_transmission():
    # traverse scene: every material.transmission is undefined or 0
def scenario_low_tier_holds_its_budget():
    # ?tier=low front camera: stats().drawCalls <= 120 and triangles <= 200000
def scenario_views_cut_the_house():
    # setView('L1'): roof and L2 hidden; setView('L2'): gableCut visible, gableFull hidden
def scenario_night_lights_rooms():
    # setTime('night') at High: roomLights visible count == plan lights count
def scenario_capture_returns_pngs():
    # capture(['front','top']) -> two data:image/png URLs of the requested size
def scenario_library_urls_carry_auth_under_enforcement():
    # auth_enforce on, local grace off, a paired panel device token -> library texture requests answer 200, none 401 (a separate live file if harness.py must not be imported under enforcement, memory auth-flip-aftermath)
def scenario_low_budget_holds_in_floor_views_too():
    # ?tier=low: setView('L1') and setView('L2') at the top camera also within 120 draw calls / 200k triangles
def scenario_page_draws_with_the_library_offline():
    # library route returns 404 for everything -> page still boots, materials fall back to kit colours
```

- [ ] **Step 2: Run** `python tests/test_twin_view_live.py`. Expected: FAIL (`/house/twin` 404).
- [ ] **Step 3: Implement.** Read `chauffeur/docs/ui_design_guide.md` first. No `transmission`. Run `python tools/build_tailwind.py` if the template uses Tailwind classes.
- [ ] **Step 4: Run** `python tests/test_twin_view_live.py` and `python tests/test_auth.py`. Expected: all `ok`. Save screenshots of front/porch/rear/top at Low and High for the review.
- [ ] **Step 5: Commit** `feat(twin): plan-to-scene generator, yard, Low/High tiers and the /house/twin preview`.

---

### Task 8: The art director loop and the tools sheet

**Files:**
- Create: `chauffeur/services/twin_director.py`, `chauffeur/static/twin/twin_director.js`
- Modify: `chauffeur/templates/house_twin.html` (tools sheet), `chauffeur/main.py`, `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_director.py` (pure and route, model stubbed), `chauffeur/tests/test_twin_director_live.py`

**Interfaces:**
- Consumes: `twin_store`, `twin_cost`, `twin_plan.merge_director`, `twin_library.kit`, `view.capture`, `view.rebuild`.
- Produces:
  - `critique(run: str, renders: list[str], cameras: list[str]) -> tuple[dict | None, str | None]`: `result = {round, critique, done, plan, cost}`. The prompt carries the kit's `style_guide`, the household's photo sources (at most 4), the renders labelled by camera, the current `site` and `materials` JSON, and the kit's allowed assets and presets. The model returns `{critique, done, site, materials}`. Rounds per `run` are capped at `ROUND_CAP`; the sixth answers `'round cap reached'`. Compose is **not** rerun after a director round.
  - Route: `POST /api/house/twin/critique` body `{run, renders: [base64 png], cameras, base}` -> `{result}` (the round is pushed with `base`; a stale result is kept as a stale round, the response says `stale: true`, and the client stops the loop and tells the person); 409 `{checkpoint, total}` on a checkpoint; 409 `'round cap reached'`; 409 while a round is in flight (PARENTS).
  - `twin_director.js`: `export async function runDirector(view, { run, cameras = ['front','porch','rear','top'], onRound })`: capture, POST, `view.rebuild(result.plan)`, report critique and running cost, loop until `done`, the cap, or a checkpoint. On a checkpoint it shows `promptConfirm('Spent $X so far', 'Continue to the next checkpoint?', 'Continue', 'Stop')`, posts `/api/house/twin/cost/ack` and continues only on Continue.
  - Tools sheet (parents only; hidden for a panel device): upload drawings and photos; pick pages per drawing; Draft; Run art director; the rounds list with Revert; the running cost; a plan JSON editor (save goes to `PUT /api/house/twin/plan` with a required reason, so every hand fix is logged).

- [ ] **Step 1: Write the failing tests.**

```python
# test_twin_director.py
def scenario_a_round_changes_only_site_and_materials():
def scenario_director_rounds_do_not_rerun_compose():
    # director removes a compose shrub -> next round's plan still lacks it
def scenario_a_revert_during_a_critique_wins():
    # critique based on round 2; a revert to round 1 lands first -> the critique's round is saved stale, current stays the revert
def scenario_round_cap_is_five_per_run():
def scenario_checkpoint_blocks_a_round():
def scenario_assets_outside_the_kit_are_refused():
# test_twin_director_live.py (critique route stubbed to return a revised site twice, then done)
def scenario_director_loop_rebuilds_and_stops_when_done():
    # three rounds posted, scene rebuilt twice, loop stops on done; rounds list shows them
def scenario_checkpoint_asks_with_promptconfirm_not_a_browser_dialog():
    # stub returns 409 checkpoint -> the control_center confirm sheet is visible; page.on('dialog') never fires
def scenario_hand_edit_requires_a_reason_and_logs_fixes():
```

- [ ] **Step 2: Run** both files. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_director.py`, `python tests/test_twin_director_live.py`, `python tests/test_twin_view_live.py`, `python tests/test_auth.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): art director rounds with checkpoints, revert and the hand-edit log`.

---

### Task 9: The panel performance probe

**Files:**
- Modify: `chauffeur/static/twin/twin_view.js` (`runProbe`), `chauffeur/templates/house_twin.html` (`?probe=1`, `?hud=1`), `chauffeur/main.py`, `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_view_live.py` (one more scenario)

**Interfaces:**
- Produces: `view.runProbe(seconds = 20) -> Promise<{ tier, fpsAvg, fpsP5, drawCalls, triangles, gpu, ua, at }>` (a scripted orbit at the exterior, then 5 s each at Ground floor and Upstairs). `?probe=1` runs it after load and posts to `POST /api/house/twin/perf` (WALL_OR_SERVICE; keeps the last 20); `GET /api/house/twin/perf` (PARENTS). `?hud=1` shows a small fps and draw-call readout.

- [ ] **Step 1: Write the failing test** `scenario_probe_posts_a_result`: `?tier=low&probe=1` with `seconds` shortened through `?probe_s=3`, then `GET /api/house/twin/perf` has one result with `tier == 'low'` and `fpsAvg > 0`.
- [ ] **Step 2: Run** it. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `python tests/test_twin_view_live.py`. Expected: all `ok`.
- [ ] **Step 5: Commit** `feat(twin): on-device performance probe for the tiers`.

---

### Task 10: The live run, the record and the release

This task needs the user present: it spends real credits and judges looks.

- [ ] **Step 1: Deploy** per memory `ha-deployment-workflow` after bumping `chauffeur/config.yaml` to `2.499.763`.
- [ ] **Step 2: Draft for real.** On `/house/twin` (desktop, High), upload `Pool Simplified Plot Plan.pdf`, `UPTON POOLHOUSE FINALS 6-2-22.pdf` (pick the plan, elevation, electrical and roof sheets) and the two pool house photos; run Draft. Record the cost of each stage from `GET /api/house/twin/cost`.
- [ ] **Step 3: Correct by hand** in the plan editor until the building matches the drawings. Each save carries a reason. Export `GET /api/house/twin/fixes`: this is the plan reader's accuracy record.
- [ ] **Step 4: Run the art director** at High until the user stops it, says done, or a checkpoint stops it and the user stops there. Note the cost and a screenshot per round.
- [ ] **Step 5: Measure on the Pi 5.** Open `/house/twin?tier=low&probe=1` on the wall panel; read `GET /api/house/twin/perf`. Exit criterion: the Low orbit is smooth on the Pi (the user's judgement, with the measured fps alongside). If it is not, record the numbers and open the pre-rendered idle loop question (spec 5.6) with the user rather than tuning blind.
- [ ] **Step 6: Record.** Add the v2.499.763 entry at the top of `chauffeur/system_capabilities.md` (what shipped, the hidden route, the cost and fix-log numbers from this run, NOT device-verified unless the user says so). Update the memory arc `house-digital-twin-arc` with the run's numbers and the user's verdict.
- [ ] **Step 7: Commit** `feat(twin): P0 pool house twin preview, drafted from plans and photos, art-directed, Low/High tiers (v2.499.763)` and push.
