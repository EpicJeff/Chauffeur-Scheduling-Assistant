# House editor slice 1b-i: Your place — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace slice 1's household-specific Build dropdown and per-page house/pool-house selector with **Your place**: one Lot and any number of named buildings, each with its own documents and photos, a paid-on-request plot plan read whose suggestions the person confirms, lot placement confirmed during setup, buildings without drawings built as shells, and one Build that runs the whole place in order.

**Architecture:** A new *place registry* (`house_twin.place` in household settings, owned by `twin_store`) records the buildings, the lot's placement and the photo tags. Plans themselves still hold only geometry. Pure rules live in a new `services/twin_place.py`. The paid setup reads (the plot plan, photo suggestions) live in a new `services/twin_place_reads.py`. `twin_build` learns *parts*: it builds the lot, a building with drawings or a shell, and chains them for a whole-place Build. The editor gains a full-screen `Your place` view in a new `static/twin/editor/place.js`.

**Tech Stack:** FastAPI (`chauffeur/main.py`), Python services, Jinja template `templates/house_editor.html`, vanilla ES modules under `static/twin/editor/`, Playwright live tests through `tests/live_app.py`.

**Spec:** `docs/superpowers/specs/2026-11-07-house-editor-structures-design.md` (§3, §4, §6, §9; §11's first three points are the bar). It amends `docs/superpowers/specs/2026-11-07-house-editor-design.md`. Slice 1's plan, `docs/superpowers/plans/2026-11-07-house-editor-slice-1.md`, shows the conventions this plan follows.

## Global Constraints

- Who does what (the codex-coordination memory): Claude writes each task's tests first, Codex (`codex:codex-rescue`, a fresh thread per task) implements, and Claude runs the sqlite and Playwright gates, reviews, commits, bumps `chauffeur/config.yaml` and updates `chauffeur/system_capabilities.md`. Codex never commits and never bumps.
- Run tests from `chauffeur/` as plain scripts with `HA_BASE_URL` unset: `env -u HA_BASE_URL python tests/test_x.py`. Run the task's own suites plus the neighbours it names, never the whole suite.
- No household names or kinds in the product (spec §2). The ids `house` and `pool_house` appear only through migration and legacy callers. Remove the `'pool' not in b['name'].lower()` heuristic from every new code path.
- Building kinds, in this order, with these labels: Main house, Garage, ADU or guest house, Pool house, Shed, Greenhouse, Barn, Studio or office, Workshop, Other.
- Building page roles: floor, roof, elevation, other, skip. Lot page roles: plot (shown as "Plot plan"), survey, landscape (shown as "Landscape plan"), other, skip.
- The lot's reserved part id is `lot`. A building id never equals `lot`.
- Nothing becomes part of the place without the person accepting it. No paid read starts by itself, and each shows its estimated cost before it runs (spec §4, §10).
- No browser dialogs. Use `promptConfirm`, `promptInput` and `showGlobalAlert`.
- Page JS calls the API through `request()` in `static/twin/editor/api.js`, never a root-relative `/api/...` URL.
- After any template class change, run `python tools/build_tailwind.py`.
- Never add packages to `requirements.txt`. Never use `transmission` in materials.
- Every Argyle place action has a hand path, and every hand path is visible to Argyle through `house_design` status.
- Everything slice 1 can do keeps a place (spec §2). Legacy `POST /api/house/editor/build` bodies `{building: {id, name}, photos}` keep slice 1's exact steps.
- New reads are recorded once on the user's own documents, capped at **$1.00 total**. Never open, print or commit `*_api_key.txt`. Check recorded fixtures for keys before committing.
- Errors that reach a person are plain sentences of at most 160 characters without `[]{}_=<>|`, so `_house_editor_call` passes them through.

## Review Focus

1. **A page moved to a part whose roles don't fit it** (a floor page moved to the lot, a plot page moved to a building). Expected: its role becomes Other and its level clears; no invalid row is ever saved. Pinned in Task 1 (`scenario_move_page_resets_incompatible_role`).
2. **The plot page changes after the plot read** (its role changes away from plot, it moves to a building, or Start over runs). Expected: the stored read and an unconfirmed placement are cleared, and the Build then reads the plot itself with the lot placement pause. Pinned in Task 3 (`scenario_plot_read_cleared_when_page_changes`).
3. **A building is renamed, or its kind changed, after it is built.** Expected: the plan's building name follows, so cards, Argyle and labels use the new name; the building id never changes. Pinned in Task 1 (`scenario_rename_built_building_updates_plan`).
4. **A building with pages, or one already built, is removed.** Expected: refused with a plain reason. Removing an unbuilt building with no pages drops it from every photo's tags, and a photo left with no tag belongs to the lot. Pinned in Task 1 (`scenario_remove_building_rules`).
5. **A whole-place Build where a building without drawings has no footprint yet.** Expected: that building is skipped with the log line "Skipped <name>: it has no footprint yet." and the rest builds. Pinned in Task 6 (`scenario_place_skips_shell_without_footprint`).

## Rulings this plan makes (designer's calls, recorded for review)

- Feature suggestions, from the plot plan or from photos, arrive with 1b-ii, when features exist. In 1b-i the plot read suggests building footprints, the lot, the street edge and the scale; the lot build's `site` step keeps reading the pool, hardscape, fire pit and retaining walls as slice 1 does.
- A footprint drawn on the lot is a dragged rectangle in 1b-i. Adding corners comes with 1b-ii's drawing tools. A shell's walls can be edited in plan view like any building's.
- Composition runs at the end of every single-part build and once at the end of a whole-place Build.
- Legacy build bodies keep slice 1's exact steps, so its 32 engine scenarios stay as they are; the editor uses only `part`.
- Start over empties the place along with the documents.
- The place is the source of truth for a building's name and kind; a rename on the building's card in the scene writes the place too.
- Building names are unique without regard to case, so Argyle and the cards never confuse two buildings.

## File Structure

| File | Responsibility |
|---|---|
| `chauffeur/services/twin_place.py` (new) | Pure rules: kinds and their shell defaults, building ids, footprint validation, migration from slice 1, plot registration and suggestions, shell geometry. Imports `twin_register` only, never `twin_store`. |
| `chauffeur/services/twin_store.py` | Persists the place, roles per part, photo tags, each upload's part, and the lot placement. Start over empties the place. |
| `chauffeur/services/twin_place_reads.py` (new) | The paid setup reads and their outcomes: plot read, suggestion accept and dismiss, placement confirm, photo suggestions, cost estimates. |
| `chauffeur/services/twin_reads.py` | `sheet_roles` gains part context and the `elsewhere` hint. New read kind `photo_parts`. |
| `chauffeur/services/twin_plan.py` | A plan with no buildings is valid when it has a valid `site.lot`. |
| `chauffeur/services/twin_build.py` | Parts: lot builds, building builds with a `fit` step, shell builds, and whole-place chains. |
| `chauffeur/services/agent_tools_v2.py` | `house_design` gains `add_building`, `set_building` and `remove_building`; its status summarises the place. |
| `chauffeur/main.py` | `/api/house/editor/place/*` routes, `part` on uploads, `place` in `/sheets`, `part` on build. |
| `chauffeur/templates/house_editor.html`, `static/twin/editor/place.js` (new), `editor.js`, `pauses.js`, `editor.css` | The Your place view. The dropdown and the per-page building selector are retired. |
| `chauffeur/tools/twin_live.py` | A `record-place` subcommand that records the new reads once, within a budget. |

---

### Task 1: The place registry, roles per part, photo tags and migration

**Files:**
- Create: `chauffeur/services/twin_place.py`, `chauffeur/tests/test_twin_place.py`
- Modify: `chauffeur/services/twin_store.py` (`_state`, `save_source`, `set_page_roles`, new place functions), `chauffeur/services/twin_edit.py` (building `name` set writes the place)
- Neighbours to run: `tests/test_twin_sheets.py`, `tests/test_twin_store.py`, `tests/test_twin_edit.py`

**Interfaces:**
- Produces, in `twin_place`:
  - `KINDS: dict[str, str]`: ordered kind id to label: `main_house` Main house, `garage` Garage, `adu` ADU or guest house, `pool_house` Pool house, `shed` Shed, `greenhouse` Greenhouse, `barn` Barn, `studio` Studio or office, `workshop` Workshop, `other` Other.
  - `SHELL_DEFAULT = {'storeys': 1, 'wall_height': 8, 'roof': 'gable', 'pitch': 6, 'door_side': 'front'}`.
  - `KIND_SHELL = {'main_house': {'storeys': 2, 'wall_height': 9}, 'garage': {'wall_height': 9}, 'adu': {'wall_height': 9}, 'pool_house': {'wall_height': 9}, 'greenhouse': {'wall_height': 7, 'pitch': 8}, 'barn': {'wall_height': 12, 'pitch': 8}, 'studio': {'wall_height': 9}, 'workshop': {'wall_height': 10}}`.
  - `BUILDING_ROLES = ('floor', 'roof', 'elevation', 'other', 'skip')`, `LOT_ROLES = ('plot', 'survey', 'landscape', 'other', 'skip')`, `LOT = 'lot'`.
  - `shell_for(kind) -> dict`: `SHELL_DEFAULT` overlaid with `KIND_SHELL[kind]`.
  - `check_shell(card) -> dict`: storeys an int 1–4; wall_height 6–20; roof gable, hip, shed or flat; pitch 0–24 (flat forces 0); door_side front, back, left or right. Raises `ValueError` with a plain sentence.
  - `check_footprint(points) -> list`: 3–64 finite points, each within ±2000 ft, area of at least 4 sq ft, no self-intersection.
  - `new_id(name, taken) -> str`: lowercase, runs of non-alphanumerics become `-`, at most 40 characters, `building` if empty, `-2`, `-3` and so on while taken; never `lot`.
  - `empty_place() -> {'buildings': [], 'lot': {'placement': None, 'read': None}, 'photo_tags': {}}`.
  - `migrate(row: dict, plan: dict | None) -> dict` (spec §9):
    - each distinct non-plot `building` in `row['page_roles']`, then each plan building not yet listed, becomes a place building with the same id;
    - names: `house` becomes Main house (kind `main_house`); `pool_house` becomes Pool house (kind `pool_house`); any other id takes the plan building's `name` or its id, with kind `other`;
    - `shell` is `shell_for(kind)`, and `footprint` is None;
    - each photo source is tagged with every migrated building and `lot`.
  - `to_master(crop, uv) -> list`: the math `twin_store.crop_to_master` now delegates to.
- Produces, in `twin_store`:
  - `place() -> dict`: migrates on first read, saves, and returns a deep copy.
  - `add_building(name: str, kind: str) -> dict`
  - `update_building(bid: str, fields: dict) -> dict`: fields are `name`, `kind`, `shell` (partial, merged then checked, sets `shell_from='person'` unless a `shell_from` of `photos` is passed), `footprint` (checked), and `footprint_from` (`plot`, `typed` or `drawn`).
  - `remove_building(bid: str) -> None`
  - `move_page(source: str, page: int, part: str) -> list[dict]`: returns the moved rows.
  - `set_photo_tags(source: str, parts: list[str]) -> list[str]`
  - `photos_for(part: str) -> list[str]`: photo source ids tagged with the part. Untagged photos count as `lot`.
  - `set_lot(lot: dict) -> None`: replaces `place['lot']` under the lock (Task 3 is its only writer).
  - `save_source(kind, filename, data, *, content_type=None, part=None)`: records `source['part']`. A photo starts tagged `[part]`. With no part (legacy), a photo is tagged with every building plus `lot` and a drawing's part is `house`.
  - Place building record: `{'id', 'name', 'kind', 'footprint', 'footprint_from', 'shell', 'shell_from'}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_place.py`. Follow the scenario style of `tests/test_twin_sheets.py`, using a temporary `CHAUFFEUR_DATA_DIR` and a two-page blank PDF built with PIL. Scenarios and their assertions:
  - `scenario_empty_place`: `ts.place() == tp.empty_place()`.
  - `scenario_add_building_ids_and_names`:
    - `add_building('Detached garage', 'garage')['id'] == 'detached-garage'`;
    - a second "Detached Garage" raises `ValueError('There is already a building called Detached Garage.')`;
    - `add_building('Lot', 'other')['id'] != 'lot'`;
    - an unknown kind raises `ValueError` with a message starting "Choose a kind";
    - a shed's `shell == tp.shell_for('shed') == tp.SHELL_DEFAULT`.
  - `scenario_upload_to_part`:
    - `save_source('drawing', 'g.pdf', pdf, part='detached-garage')` gives a source with `part == 'detached-garage'`;
    - a photo uploaded with `part='lot'` gives `photos_for('lot') == [id]`;
    - an unknown part raises `ValueError`.
  - `scenario_roles_per_part`:
    - `set_page_roles` accepts `{'building': 'lot', 'role': 'plot'}`;
    - it rejects `{'building': 'lot', 'role': 'floor'}` and `{'building': 'detached-garage', 'role': 'survey'}` with `ValueError('That page role does not fit this part of your place.')`;
    - it rejects an unknown building id;
    - a legacy row without `building` saves as `lot` when its role is plot and as `house` otherwise, adding Main house to the place if it is missing.
  - `scenario_move_page_resets_incompatible_role`:
    - a floor page with level "Main floor" moved to `lot` saves `role == 'other'` and `level is None`;
    - a roof page moved between buildings keeps role `roof`;
    - every region of a page with two boxes moves together.
  - `scenario_photo_tags`:
    - `set_photo_tags(pid, ['lot', 'detached-garage'])` makes `photos_for('detached-garage')` include `pid`;
    - an empty list makes `photos_for('lot')` include it;
    - an unknown part raises.
  - `scenario_migration_from_slice_1`:
    - write a `house_twin` state with page roles for `house` (floor) and `pool_house` (floor), one plot row with building `house`, and one photo, with no `place` key;
    - `ts.place()['buildings']` gives `[('house', 'Main house', 'main_house'), ('pool_house', 'Pool house', 'pool_house')]` as (id, name, kind);
    - the plot row's `building == 'lot'`;
    - the photo is tagged `['house', 'pool_house', 'lot']`;
    - a second `ts.place()` call returns the same result without migrating again.
  - `scenario_rename_built_building_updates_plan`: push a plan with building `house`, then `update_building('house', {'name': 'Farmhouse'})` gives `ts.current()['buildings'][0]['name'] == 'Farmhouse'` with the id unchanged. A `twin_edit.save({'op': 'set', 'building': 'house', 'piece': 'house', 'field': 'name', 'value': 'Home'}, 'p1')` then makes `ts.place()` show name "Home".
  - `scenario_remove_building_rules`:
    - removing a building with pages raises `ValueError('Move or remove this building\'s pages first.')`;
    - removing a built one raises `ValueError('This building is part of the house. Delete it from the house first.')`;
    - removing an unbuilt one with no pages drops it from every photo's tags, and a photo left with no tags shows in `photos_for('lot')`.
  - `scenario_start_over_empties_place`: after `ts.start_over()`, `ts.place() == tp.empty_place()`.
  - `scenario_footprint_and_shell_checks`:
    - a bow-tie polygon raises `ValueError('A footprint cannot cross itself.')`;
    - storeys 0 raises;
    - roof flat saves pitch 0;
    - `{'footprint': [[0,0],[10,0],[10,12],[0,12]], 'footprint_from': 'typed'}` saves.

- [ ] **Step 2: Run them and see them fail.** `env -u HA_BASE_URL python tests/test_twin_place.py`. Expect an ImportError for `twin_place`.
- [ ] **Step 3: Implement `twin_place.py` and the store functions** with the signatures above. Every mutation happens under `_LOCK`; any that also touches the plan takes `LIFECYCLE` first. A rename or kind change of a built building calls `update_current(..., kind='edit', note='Renamed <old> to <new>')`. `_PAGE_ROLES` becomes the union of both role sets.
- [ ] **Step 4: Run them and see them pass,** together with the neighbours: `tests/test_twin_place.py`, `test_twin_sheets.py`, `test_twin_store.py` and `test_twin_edit.py` all exit 0.
- [ ] **Step 5: Controller commits** `feat(twin): the place registry - buildings of any kind, the lot, documents and photos per part, migration from slice 1 (slice 1b-i task 1)`.

### Task 2: Place routes, uploads to a part, and page hints

**Files:**
- Modify: `chauffeur/main.py` (new routes beside `house_editor_sheets`, `/api/house/twin/sources` POST gains form field `part`, `house_editor_suggest_roles`), `chauffeur/services/twin_reads.py` (`sheet_roles` prompt and parse)
- Test: `chauffeur/tests/test_house_editor_routes.py` (new scenarios), `chauffeur/tests/test_twin_reads.py` (new scenarios)
- Neighbours: `tests/test_auth.py` (the `/api/house/editor/*` PARENTS rule already covers the new routes; the suite must stay green)

**Interfaces:**
- Consumes: Task 1's store functions.
- Produces, as routes that all go through `_house_editor_call`:
  - `GET /api/house/editor/sheets` adds `place` (from `ts.place()`), `kinds` (`[{id, label}]`), `roles` (`{'building': [...], 'lot': [...]}`) and `estimates` (Task 3 fills these; this task returns `{}`).
  - `POST /api/house/editor/place/buildings` `{name, kind}` returns `{building, summary}`.
  - `PATCH /api/house/editor/place/buildings/{bid}` with the fields from Task 1 returns `{building, summary}`.
  - `DELETE /api/house/editor/place/buildings/{bid}` returns `{status: 'ok', summary}`.
  - `POST /api/house/editor/place/pages/move` `{source, page, part}` returns `{page_roles}`.
  - `PUT /api/house/editor/place/photos/{source_id}` `{parts}` returns `{parts}`.
  - `POST /api/house/twin/sources` takes an optional form field `part`.
  - `POST /api/house/editor/sheets/suggest` sends context `{'source', 'pages', 'part': {id, name, kind}, 'parts': [{id, name, kind}]}`. Each returned row carries `building` (the source's part). A row may also carry `elsewhere` (a part id other than the source's own) and `hint` (`"Page 7 looks like the Detached garage."`).
- `twin_reads`: the `sheet_roles` page role choices become `('floor', 'roof', 'plot', 'survey', 'landscape', 'elevation', 'other')`. Each page may carry an optional `"elsewhere"` (text). The prompt asks for it only when a page clearly shows another listed part.

- [ ] **Step 1: Write the failing tests.**
  - In `test_house_editor_routes.py` (TestClient, parent token as the existing scenarios do):
    - `scenario_place_crud`:
      - POST Garage (kind `garage`) returns 200 with `building.id == 'garage'`;
      - a duplicate returns 400 with detail "There is already a building called Garage.";
      - PATCH `{'shell': {'storeys': 2}}` returns `building.shell.storeys == 2` and `shell_from == 'person'`;
      - DELETE returns 200;
      - `GET /sheets` includes `place`, the `kinds` labels in spec order, and `roles`.
    - `scenario_upload_with_part`: multipart upload with `part=lot` gives a source with `part == 'lot'`; `part=nope` gives 400 with a plain detail.
    - `scenario_move_page_route`: moving a floor page to `lot` returns the row with role `other`.
    - `scenario_suggest_hint`: stub `twin_reads.read` to return `{'pages': [{'page': 1, 'role': 'floor', 'level': 'Main', 'box': None, 'elsewhere': 'garage'}]}` for a source uploaded to `house`. The response row has `building == 'house'`, `elsewhere == 'garage'` and `hint == 'Page 1 looks like the Garage.'`. An `elsewhere` naming an unknown part, or the source's own part, is dropped. A `floor` suggestion for a lot source becomes `other`.
  - In `test_twin_reads.py`, `scenario_sheet_roles_elsewhere`: `parse('sheet_roles', {'pages': [{'page': 1, 'role': 'survey', 'level': None, 'box': None, 'elsewhere': 'garage'}]})` keeps `role == 'survey'` and `elsewhere == 'garage'`, and a non-text `elsewhere` is a problem that drops only that field.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the routes and the parse and prompt change. The summary strings are "Added Garage.", "Updated Garage." and "Removed Garage.".
- [ ] **Step 4: Run them and see them pass:** `test_house_editor_routes.py`, `test_twin_reads.py`, `test_twin_place.py` and `test_auth.py`.
- [ ] **Step 5: Controller commits** `feat(twin): place routes - add, change and remove buildings, upload to a part, move a page, tag a photo, page hints (slice 1b-i task 2)`.

### Task 3: The plot plan read in setup, suggestions, placement, photo suggestions

**Files:**
- Create: `chauffeur/services/twin_place_reads.py`, `chauffeur/tests/test_twin_place_reads.py`
- Modify: `chauffeur/services/twin_place.py` (`plot_registration`, `plot_suggestions`, `sheet_matrix`), `chauffeur/services/twin_build.py` (`_plot_registration` delegates to `twin_place.plot_registration`), `chauffeur/services/twin_reads.py` (new kind `photo_parts`), `chauffeur/services/twin_cost.py` (`estimate`), `chauffeur/main.py` (routes, `estimates` in `/sheets`)
- Neighbours: `test_twin_build.py`, `test_twin_reads.py`, `test_twin_cost.py`

**Interfaces:**
- Produces, in `twin_place`:
  - `plot_registration(crop, fragment, edge=None) -> dict`: today's `twin_build._plot_registration`. An explicit `edge` overrides the fragment's street edge.
  - `plot_suggestions(fragment, crop, reg) -> list[dict]`: each item is `{'id': 'plot-<n>', 'outline': world ft, 'outline_px': master px, 'size_ft': [w, d], 'where': 'at the front left', 'name': <read name>, 'state': 'open', 'building': None}`. `where` uses the centroid's thirds of the lot bounds, with the street side as the front (y nearest 0).
  - `sheet_matrix(reg, crop) -> [a, b, c, d, e, f]`: the SVG matrix taking full-page uv (0..1) to world feet.
- Produces, in `twin_cost`: `estimate(kind: str, images: int) -> float`. It prices `1500 + 1600 * images` input tokens and `twin_reads.MAX_OUTPUT[kind]` output tokens at the twin pool's first model (`model_pools._pool('twin', settings)[0]`) when `PRICES` knows it, and at `_highest_rates()` otherwise. Round up to the cent.
- Produces, in `twin_reads`: kind `photo_parts`, `MAX_OUTPUT` 2048. The answer is `{"photos": [{"index": 0, "parts": ["house", "lot"]}], "shells": [{"building": "shed", "storeys": 1, "roof": "gable", "pitch": 6, "confidence": 0.5, "why": ""}]}`. Parse checks each index against the images given and each part or building against the context's parts; shell fields use `twin_place.check_shell` ranges.
- Produces, in `twin_place_reads` (each raises plain `ValueError`s):
  - `read_plot(*, reader=twin_reads.read) -> dict`:
    - uses the lot's single page with role `plot` (with none, raises "Confirm a plot plan page on the lot first."), its confirmed box, and a full crop as the build does;
    - the run is `place` and the step is `plot`;
    - stores `place['lot']['read'] = {'source', 'page', 'box', 'crop', 'fragment', 'registration', 'lot', 'street_edge', 'suggestions', 'matrix', 'cost'}`;
    - clears an unconfirmed `placement`;
    - on a refused or unusable answer, raises "The plot plan could not be read. Try again, or place the buildings by hand.";
    - honours the generation guard.
  - `answer_suggestion(sid, action, *, building=None, name=None, kind=None) -> dict`:
    - `accept` with `building` matches an existing building and sets its footprint (`footprint_from='plot'`);
    - `accept` with `name` and `kind` creates the building;
    - `dismiss` marks the suggestion dismissed, and it is never offered again by this read;
    - an accepted footprint for an already built building fits that building onto it at once, unless the building's `src.person` is set (`twin_register.fit_outline` against its lowest level outline, written through `update_current(kind='edit')`).
  - `confirm_placement(street_edge: list[int] | None, footprints: list[dict]) -> dict`:
    - a changed `street_edge` rebuilds the registration through `plot_registration(..., edge=street_edge)` and reprojects every accepted footprint through the old registration's inverse and the new one;
    - `footprints` are `[{building, outline}]` in world feet and replace those buildings' footprints after `check_footprint`;
    - it saves `placement = {'source', 'page', 'box', 'outline', 'street_edge', 'registration', 'confirmed': True}`;
    - it calls `twin_store.set_registration(source, page, None, registration)`, so the site read at build time uses it.
  - `suggest_photos(*, reader=twin_reads.read) -> dict`:
    - reads at most 12 photos, the earliest uploads first, each cut to a 768 px thumbnail;
    - context `{'parts': [{id, name, kind, has_drawings}]}`;
    - stores `place['photo_read'] = {'photos': [{'source', 'parts'}], 'shells': [...], 'cost'}`;
    - never changes tags or shells by itself.
  - The store change: when the plot page's role changes away from plot, the page moves off the lot, or its source is gone, `lot.read` and any unconfirmed `placement` clear (in `set_page_roles` and `move_page`).
- Routes:
  - `POST /api/house/editor/place/plot/read` returns `{lot}`;
  - `POST /api/house/editor/place/plot/suggestions/{sid}` `{action, building?, name?, kind?}` returns `{lot, place, summary}`;
  - `PUT /api/house/editor/place/lot/placement` `{street_edge?, footprints}` returns `{lot}`;
  - `POST /api/house/editor/place/photos/suggest` returns `{photo_read}`;
  - `/sheets` `estimates` returns `{'plot': estimate('plot', 1), 'photos': estimate('photo_parts', min(12, photo count))}`.
  - The paid routes run `twin_cost.require_clear()` first and return the ledger entry's `usd` as `cost`. A checkpoint answers 409 as the build route does.

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_place_reads.py`, with a stub reader returning `tests/fixtures/twin_reads/plot.json`, extended with a second building and one recorded usage row through `twin_cost.record`:
  - `scenario_plot_read_needs_plot_page`: no plot page raises with the exact message above.
  - `scenario_plot_read_stores_suggestions`:
    - there are two suggestions, `plot-1` and `plot-2`, each `state == 'open'`;
    - each world outline equals `twin_register.apply(reg, to_master(crop, p))` within 1e-6;
    - `lot.street_edge == [1, 2]` (from the fixture);
    - `lot.read.cost > 0`, and one ledger entry has `run == 'place'` and `stage == 'step:plot'`.
  - `scenario_accept_new_and_match_and_dismiss`:
    - accepting `plot-1` with name Shed and kind shed creates `shed` with `footprint_from == 'plot'`;
    - accepting `plot-2` with `building='house'` sets house's footprint;
    - dismissing either afterwards raises "This suggestion was already answered.";
    - a fresh dismissed suggestion stays dismissed after `ts.place()` is read again.
  - `scenario_accept_fits_built_building`: push a plan whose `house` L1 outline is a 40×30 rectangle at the origin, then accept a suggestion whose outline is the same rectangle translated by (100, 50). The plan's house position comes out within 0.5 ft of (100, 50). Repeating with `src.person` set leaves the position unchanged.
  - `scenario_confirm_placement_and_street_edge`:
    - confirming with `street_edge=[0, 1]` changes the registration, keeps the lot's area within 1e-6 and moves the accepted footprints with the lot;
    - `ts.registration(source, page, None)` equals the saved registration;
    - a bow-tie footprint raises "A footprint cannot cross itself.".
  - `scenario_plot_read_cleared_when_page_changes`: after a read, setting that page's role to `survey` clears `lot.read` and leaves no unconfirmed placement. After a confirmed placement, changing the page's role keeps the confirmed placement and clears only the read.
  - `scenario_photo_suggestions`: a stub returns `{'photos': [{'index': 0, 'parts': ['house', 'lot']}], 'shells': [{'building': 'shed', 'storeys': 1, 'roof': 'gable', 'pitch': 7, 'confidence': 0.4, 'why': 'side photo'}]}`. `photo_read.photos[0].parts == ['house', 'lot']`, the shed's `shell` is unchanged and its tags are unchanged; an unknown part in the answer is dropped.
  - `scenario_estimate`: `twin_cost.estimate('plot', 1) > 0`; an unknown model prices at the highest rates; 12 photos estimate more than 1.
  - `scenario_refused_read_costs_nothing_and_raises`: a reader returning `{'error': 'refused'}` raises the plain message and records no suggestion.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** Route tests go in `test_house_editor_routes.py` as `scenario_plot_routes` (read, accept, confirm and estimates through TestClient with a stubbed reader).
- [ ] **Step 4: Run and see them pass:** `test_twin_place_reads.py`, `test_house_editor_routes.py`, `test_twin_build.py`, `test_twin_reads.py` and `test_twin_cost.py`.
- [ ] **Step 5: Controller commits** `feat(twin): read the plot plan in setup - suggestions you accept, match or dismiss, lot placement confirmed before building, photo suggestions (slice 1b-i task 3)`.

### Task 4: Builds of a part: the lot, a building with drawings, the fit

**Files:**
- Modify: `chauffeur/services/twin_build.py` (`start`, `plan_steps`, `_base`, `_obtain`, `_pause`, `_settle`, `answer`, `status`, `_run`), `chauffeur/services/twin_plan.py` (`normalize`)
- Create: `chauffeur/tests/test_twin_build_parts.py` (it reuses `test_twin_build`'s helpers by import, as `test_twin_build_replay.py` does)
- Neighbours: `test_twin_build.py` (all 32 stay green unchanged), `test_twin_build_replay.py`, `test_twin_plan_v2.py`, `test_twin_compose.py`, `test_twin_draft.py`

**Interfaces:**
- Consumes: `ts.place()`, `ts.photos_for(part)`, the lot placement (Task 3).
- Produces:
  - `twin_build.start(inputs)` accepts `{'part': 'lot' | <building id>}`.
    - A building part builds `inputs['building'] = {'id', 'name', 'kind'}` from the place, with `photos = ts.photos_for(bid)`.
    - Legacy `{'building': {...}, 'photos'?}` keeps slice 1's exact steps and behaviour.
    - Internal flags `inputs['compose']` (default True for a single part) and `inputs['then']` (Task 6) are set by the engine, never by callers.
  - `status()` adds `part` and `next` (None until Task 6).
  - Part step lists:
    - **Lot with a confirmed placement:** `lot` (no read, no pause; settles `plan['site']['lot'] = placement.outline`), then `site` on the plot page using the saved registration, then `compose` when `inputs['compose']`.
    - **Lot without a confirmed placement:** `plot` (read, pause `lot_placement`, Looks right and Re-read only; settling saves `plan['site']['lot']`, stores the read and its suggestions into `place['lot']['read']` and saves a confirmed placement), then `site`, then `compose`.
    - **Lot with no plot page:** refused with "Add a plot plan to the lot first."
    - **Building with floor pages:** slice 1's floor, roof, pitch and finishes steps with that building's tagged photos, without `plot` and `site`, then `fit` when the plan or the place has a lot, then `compose` when `inputs['compose']`.
  - The `fit` step (no read):
    - with a footprint, `fit_outline(lowest level outline, footprint)` gives the transform;
    - it settles without a pause when the RMS is at most 2 ft and the outline's area is within 20% of the footprint's;
    - otherwise it pauses with `{'kind': 'lot_placement', 'step': 'fit', 'transform', 'registration': twin_register.make(1), 'why'}`, where `why` is "The drawings and the plot plan disagree about this building's shape. Check where it sits." or, with no footprint, "This building has no footprint on the lot yet. Drag it into place.";
    - with no footprint, the proposed transform is beside the other buildings, as slice 1 does today;
    - `answer(..., {'transform': ...})` is allowed for `fit` as it is for `plot`;
    - settling never moves a building whose `src.person` is set.
  - `twin_plan.normalize` keeps a plan with no buildings when `site.lot` is a valid polygon, and still raises "Twin plan must contain at least one usable building." otherwise.
  - A lot build never adds a building to the plan. `_settle`'s per-house bookkeeping is skipped when the plan has no building for the build.

- [ ] **Step 1: Write the failing tests** in `test_twin_build_parts.py` (inline builds, stub reader keyed by kind, as `test_twin_build.py` does):
  - `scenario_lot_build_confirmed_placement`:
    - with an empty plan and a confirmed placement, `start({'part': 'lot'}, inline=True)` ends `done`;
    - the step kinds are `['lot', 'site', 'compose']`;
    - `ts.current()['buildings'] == []` and `ts.current()['site']['lot'] == placement.outline`;
    - the reader saw only `site`.
  - `scenario_lot_build_reads_plot_when_unconfirmed`: the build pauses at `plot` with kind `lot_placement`. After `answer(bid, 'plot', {'accept': True})`, the place has a confirmed placement, `lot.read.suggestions` has length 1, and the build ends done.
  - `scenario_lot_without_plot_page_refused`: `ValueError('Add a plot plan to the lot first.')`.
  - `scenario_building_part_steps`:
    - for `house` with a floor and a roof page, a confirmed lot and one photo tagged `house` plus one tagged `lot`, the step kinds are the slice 1 floor steps, then `roof`, `pitch`, `finishes`, `fit`, `compose`;
    - there are no `plot` or `site` steps;
    - the pitch and finishes reads received exactly one image.
  - `scenario_fit_settles_on_matching_footprint`: with a footprint equal to the read outline turned 90° and moved, the build ends done with no pause; the house rotation is within 1° and its position within 0.5 ft of the footprint's.
  - `scenario_fit_pauses_on_poor_fit_and_missing_footprint`:
    - a footprint 2× the size pauses at `fit` with the first message;
    - answering a transform moves the house to it;
    - no footprint pauses with the second message.
  - `scenario_legacy_body_unchanged`: `start({'building': {'id': 'house', 'name': 'Main house'}, 'photos': [pid]}, inline=True)` with a plot page produces slice 1's step ids, including `plot` and `site`.
  - `scenario_zero_building_plan`: `twin_plan.normalize({'units': 'ft', 'buildings': [], 'site': {'lot': square}})` keeps the lot; without the lot it raises.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.** `compose` with no buildings must not fail: run `test_twin_compose.py` and add `scenario_compose_without_buildings` there if it isn't covered.
- [ ] **Step 4: Run and see them pass:** `test_twin_build_parts.py`, all 32 of `test_twin_build.py`, `test_twin_build_replay.py`, `test_twin_plan_v2.py`, `test_twin_compose.py` and `test_twin_draft.py`.
- [ ] **Step 5: Controller commits** `feat(twin): builds of a part - the lot on its own, each building fitted onto its footprint (slice 1b-i task 4)`.

### Task 5: Shells for buildings without drawings

**Files:**
- Modify: `chauffeur/services/twin_place.py` (`shell_building`), `chauffeur/services/twin_build.py` (a `shell` step)
- Test: `chauffeur/tests/test_twin_build_parts.py` (new scenarios)
- Neighbours: `test_twin_plan_v2.py`, `test_twin_roof_js.py` (a shell's roof must draw), `test_twin_edit.py`

**Interfaces:**
- Produces: `twin_place.shell_building(building: dict, step_id: str) -> dict`. It returns a plan building with these properties:
  - id, name and kind from the place;
  - `position [0, 0]`, `rotation 0`, `base 0`;
  - one level per storey: id `L<n>`, name `Floor <n>`, elevation `(n-1) * wall_height`, ceiling `wall_height`, outline = footprint;
  - exterior walls along each footprint edge on every level: thickness 0.5, height `wall_height`, `exterior: True`;
  - one roof section on the footprint's bounding rectangle: `kind` from the card, `ridge` along the longer side, `pitch` from the card (0 when flat), `plate = storeys * wall_height`, `overhang 1`, `pitch_source 'card'`; a shed's `low_side` is the back (y1);
  - one door, 3 ft wide with head 6.67 and sill 0, centred on the longest L1 wall whose outward normal faces the card's `door_side`: front is −y (towards the street), back +y, left −x, right +x;
  - every piece has `state: 'settled'` and `src: {'sheet': '', 'page': 1, 'step': step_id}`.
- A building part with no floor pages builds steps `['shell', 'compose']`, or only `shell` inside a chain. It needs a footprint, or is refused with "Give <name> a footprint: type its size or draw it on the lot." Settling goes through `_merge_list`, so a rebuilt shell keeps a person's edits, and a moved wall stays moved.

- [ ] **Step 1: Write the failing tests:**
  - `scenario_shell_geometry`, with a 10×12 footprint and storeys 1, wall_height 8, gable, pitch 6, door front:
    - one level, four exterior walls of height 8;
    - one roof section with rect `[0, 0, 10, 12]`, `ridge == 'y'` and plate 8;
    - one door on the wall from (0,0) to (10,0), at 5;
    - `twin_plan.normalize` reports no notes.
  - `scenario_shell_two_storeys_hip_left_door`: two levels at elevations 0 and 9; plate 18; the door is on the x = 0 wall.
  - `scenario_shell_needs_footprint`: refused with the exact message.
  - `scenario_shell_rebuild_keeps_person_edit`: after a person moves a shell wall through `twin_edit.save(move)`, building the part again leaves that wall where the person put it.
  - `scenario_shell_roof_draws`: run the shell plan through the node roof harness used by `test_twin_roof_js.py`, which must produce a non-empty mesh.
- [ ] **Step 2: Run and see them fail.** **Step 3: Implement.** **Step 4: Run and see them pass,** with the neighbours.
- [ ] **Step 5: Controller commits** `feat(twin): buildings without drawings build as shells - walls, a roof and one door from their footprint and card (slice 1b-i task 5)`.

### Task 6: Build the whole place

**Files:**
- Modify: `chauffeur/services/twin_build.py` (`start` with `part: 'place'`, chaining in `_run`'s done branch), `chauffeur/main.py` (`house_editor_build` accepts `part`)
- Test: `chauffeur/tests/test_twin_build_parts.py`, `chauffeur/tests/test_house_editor_routes.py`
- Neighbours: `test_twin_build.py`, `test_house_design_tool.py`

**Interfaces:**
- Produces:
  - `start({'part': 'place'})` builds this order: `lot` when the lot has a plot page; then each building with floor pages, in place order; then each building without floor pages that has a footprint.
    - A building without drawings and with no footprint is skipped with the log event "Skipped <name>: it has no footprint yet." in the first build.
    - Nothing to build raises "Add a building with drawings or a footprint first."
    - The first part's build carries `inputs['then']` (the remaining parts) and only the last carries `compose`.
  - When a build with a non-empty `then` reaches done, still under `LIFECYCLE` and `_LOCK` and only if the generation is unchanged, it creates the next part's build with the rest of `then`, records `build['next'] = <id>` and the event `next`, saves both, and dispatches the next build after releasing the locks.
  - A stopped or failed build never starts its next. Resuming a chained build continues the chain.
  - `POST /api/house/editor/build` takes `{part}` (a string), or the legacy `{building}`; a body with neither returns 400 "Choose what to build.".

- [ ] **Step 1: Write the failing tests:**
  - `scenario_place_chain_order`, for a lot with a confirmed placement, `house` with floors and a footprint, a shed with a footprint and no drawings, and a garage with neither:
    - `start({'part': 'place'}, inline=True)` runs three builds in turn;
    - the first status shows `next` naming the second, and so on;
    - the parts are `['lot', 'house', 'shed']`;
    - only the last build has a `compose` step;
    - the first build's events include "Skipped Garage: it has no footprint yet.".
  - `scenario_place_skips_shell_without_footprint` is covered by the same fixture; assert the garage is not in the plan.
  - `scenario_chain_stops_with_build`: with a pausing house build (an outline scale pause), the shed build is not created until the pause is answered and the house build ends done.
  - `scenario_chain_stops_on_start_over`: start over while the house build is paused; no further build is ever created (`len(tb._BUILDS)` stays the same after the stale worker returns).
  - `scenario_nothing_to_build`: the exact message.
  - In `test_house_editor_routes.py`, `scenario_build_part_route`: `{'part': 'place'}` returns an id, an empty body returns 400 with "Choose what to build.", and the legacy body still returns an id.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass,** with the neighbours.
- [ ] **Step 5: Controller commits** `feat(twin): one Build for the whole place - the lot, then buildings with drawings, then shells, then finishes (slice 1b-i task 6)`.

### Task 7: Argyle can set up the place

**Files:**
- Modify: `chauffeur/services/agent_tools_v2.py` (`HouseDesignTool`, `handle_house_design`, `house_design_status`)
- Test: `chauffeur/tests/test_house_design_tool.py` (new scenarios)
- Neighbours: `tests/test_registry_parity.py` (failures that predate this slice stay as they were; no new ones)

**Interfaces:**
- `HouseDesignTool.action` gains `add_building`, `set_building` and `remove_building`.
- New optional fields:
  - `name: Optional[str]`;
  - `kind: Optional[str]` (a kind id, or its label matched without regard to case);
  - `size: Optional[list[float]]` (width and depth in feet; this becomes a typed rectangular footprint placed to the right of the other footprints, 10 ft apart, with y from 10);
  - `shell: Optional[dict]`.
- `building` names the target by id, or by name without regard to case.
- Each place action returns `{'status': 'ok', 'changed': True, 'summary': ...}`, using the same summaries as Task 2's routes.
- `house_design_status()['summary']` begins "Your place: <n> buildings (<name> (<kind label>, drawings|no drawings, footprint|no footprint); ...). Lot: plot plan read|not read, placement confirmed|not confirmed." and then gives today's text.

- [ ] **Step 1: Write the failing tests:**
  - `scenario_add_detached_garage`: `{'action': 'add_building', 'name': 'Detached garage', 'kind': 'Garage'}` makes the place hold `detached-garage` of kind `garage`.
  - `scenario_shed_size_and_roof`: `{'action': 'set_building', 'building': 'Shed', 'size': [10, 12], 'shell': {'roof': 'gable'}}` sets a 10×12 rectangle footprint with `footprint_from == 'typed'` and roof gable.
  - `scenario_remove_refusal_words`: removing a building with pages returns `status 'error'` with Task 1's message.
  - `scenario_status_mentions_place`: the summary starts with "Your place: 2 buildings".
  - `scenario_kid_refused`: a non-parent actor is refused, as today.
- [ ] **Step 2: Fail. Step 3: Implement. Step 4: Pass,** with the neighbours.
- [ ] **Step 5: Controller commits** `feat(twin): Argyle adds, changes and removes buildings in words, and reads your place (slice 1b-i task 7)`.

### Task 8: The Your place view

**Files:**
- Create: `chauffeur/static/twin/editor/place.js`, `chauffeur/tests/test_house_place_live.py`
- Modify: `chauffeur/templates/house_editor.html` (remove the `#editor-upload` section with `#editor-build-target`; add `#place-view`; the menu button `#editor-manage-sources` reads "Your place"; "Upload more" opens Your place; add `editor/place` to the import list), `chauffeur/static/twin/editor/editor.js` (retire `drawPages`, the upload, suggest, confirm and build handlers and the `data-page-building` selector; follow `next`), `chauffeur/static/twin/editor/pauses.js` (the owner of a `fit` pause is `currentBuild.part`; a lot-build `plot` pause offers only Looks right and Re-read), `chauffeur/static/twin/editor/editor.css`, then `python tools/build_tailwind.py`
- Modify tests: `chauffeur/tests/test_house_editor_live.py`. Its upload, role and build scenarios drive Your place instead, keeping each scenario's intent; no scenario is deleted.
- Neighbours: `test_twin_editor_scene_live.py`, `test_twin_view_live.py`
- First reading for the implementer: `chauffeur/docs/ui_design_guide.md` and `chauffeur/static/twin/editor/editor.css`. Your place uses the editor's dark style, not admin forms.

**Interfaces:**
- `createPlace({ request, getSheets, reload, follow, canEdit, panel }) -> { open(), close(), isOpen(), sync(sheets, snapshot) }` in `place.js`. `editor.js` calls `sync` after each `loadSheets`, and `open()` on boot when the place has no buildings and the lot has no documents.
- DOM contract (the live tests select by these ids and data attributes):
  - `#place-view` (role dialog, aria-label "Your place"), `#place-close` ("Back to the house");
  - `#place-lot` (the Lot card);
  - `[data-place-building="<id>"]` (one per building card);
  - `#place-add-name`, `#place-add-kind` (options in spec order), `#place-add` ("Add building");
  - per part `[data-place-upload="<part>"]` (a file input accepting PDF, JPEG and PNG; posts `part`);
  - per page `[data-place-page="<source>:<page>"]` holding `select[data-place-role]` (that part's roles), `input[data-place-level]` (buildings only) and `select[data-place-move]` (every other part, labelled "Move to"; one change moves the page at once);
  - per photo `[data-place-photo="<source>"]` holding a `button[data-place-tag="<part>"][aria-pressed]` per part;
  - `[data-place-hint]` (the hint text and a "Move it" button);
  - `[data-place-suggest="<source>"]` ("Suggest page roles"), `#place-confirm-pages` ("Confirm pages");
  - per building without drawings, `[data-place-shell="<id>"]` holding `storeys`, `wall_height`, `roof`, `pitch` and `door_side` controls, `[data-place-size]` (width and depth, "Set size") and `[data-place-draw]` ("Draw on the lot", shown only with a lot placement or read);
  - `#place-read-plot` ("Read the plot plan · about $X.XX", enabled only with a confirmed plot page);
  - `[data-place-suggestion="<sid>"]` holding the size and `where` words, `input[data-suggestion-name]`, `select[data-suggestion-kind]`, `select[data-suggestion-match]` ("New building" plus each building), `button[data-suggestion-accept]` and `button[data-suggestion-dismiss]`;
  - `#place-map` (an SVG in world feet: the plot sheet `<image>` placed with `matrix`, the lot polygon, the street edge drawn heavier with each lot edge tappable as `[data-place-edge="i"]`, accepted footprints as `[data-place-footprint="<bid>"]` you can drag and turn with `#place-turn`, and a rectangle drag while drawing);
  - `#place-confirm-placement` ("These are in the right place");
  - `#place-suggest-photos` ("Suggest from photos · about $X.XX"), with photo suggestions as `[data-photo-suggestion]` ("Also shows Main house · Add") and `[data-shell-suggestion="<id>"]` ("From photos: 1 storey, gable, 6 in 12 · Use these");
  - `[data-place-build="<part>"]` per card ("Build the lot" or "Build this building"), and `#place-build` ("Build your place").
- Every paid action asks first through `promptConfirm` with its estimate. Removing a building asks through `promptConfirm`. Errors show through `report` with the server's sentence.
- After `#place-build` or `[data-place-build]`, Your place closes and the editor follows the build. When a followed build is done and has `next`, polling follows `next`.

- [ ] **Step 1: Write the failing live tests** in `test_house_place_live.py` (the `live_app` harness, mocked paid routes through `page.route`, as `test_house_editor_live.py` does). Scenarios and assertions:
  - `scenario_empty_place_opens_first`: `#place-view` is visible on load; `#editor-build-target` and `[data-page-building]` have count 0.
  - `scenario_add_building_and_duplicate`:
    - adding Detached garage (Garage) shows `[data-place-building="detached-garage"]` with "Garage";
    - adding it again shows "There is already a building called Detached garage." in the global alert.
  - `scenario_upload_to_building_and_move_page`:
    - uploading a two-page PDF to `house` shows two pages under `[data-place-building="house"]`, whose role options are exactly Floor, Roof, Outside view, Other, Skip;
    - choosing Lot in page 2's Move to shows it under `#place-lot` with role Other, with lot options exactly Plot plan, Survey, Landscape plan, Other, Skip.
  - `scenario_photo_tags`: a photo uploaded to the lot shows the Lot tag pressed; pressing Main house makes the PUT body's `parts` equal `['lot', 'house']`.
  - `scenario_hint_moves_page`: with suggest mocked to return a row with `elsewhere: 'detached-garage'`, the hint reads "Page 1 looks like the Detached garage."; Move it moves the page.
  - `scenario_plot_read_suggestions_and_placement`, with the plot read mocked:
    - the button shows the estimate, and the confirm dialog names it;
    - two suggestion cards appear;
    - accepting one as Shed (Shed) adds a shed card;
    - matching the other to Main house sets its footprint;
    - dismissing a third removes it;
    - dragging `[data-place-footprint="shed"]` 50 px changes the confirm PUT's shed outline;
    - tapping `[data-place-edge="0"]` sends `street_edge: [0, 1]`.
  - `scenario_shell_card_and_size`: for the shed, setting size 10 by 12 sends PATCH `footprint` `[[x,y],[x+10,y],[x+10,y+12],[x,y+12]]`; changing roof to Hip sends `shell.roof == 'hip'`.
  - `scenario_build_place_follows_chain`: `#place-build` posts `{part: 'place'}`; the mocked first build is done with `next: 'b2'`, and the editor then polls `build/b2`.
  - `scenario_fit_pause_drags_owner`: a mocked `fit` pause with `part: 'house'` drags the house, not the lot.
  - Update `test_house_editor_live.py`: every scenario that used `#editor-source-files`, `#editor-suggest-roles`, `#editor-confirm-roles`, `#editor-build` or `#editor-build-target` uses the Your place equivalents, keeping its assertions about what the person sees.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement** `place.js`, the template and the editor changes; run `python tools/build_tailwind.py`.
- [ ] **Step 4: Run and see them pass:** `test_house_place_live.py`, all of `test_house_editor_live.py`, `test_twin_editor_scene_live.py` and `test_twin_view_live.py`. Take a screenshot of Your place with three buildings and a lot placement for the review package (`ui-design-guide-rule`).
- [ ] **Step 5: Controller commits** `feat(twin): Your place - the lot and every building as cards, documents and photos on each, the plot plan read and placement in setup; the house and pool house dropdown is retired (slice 1b-i task 8)`.

### Task 9: Record the new reads once, then replay them

**Files:**
- Modify: `chauffeur/tools/twin_live.py` (a `record-place` subcommand)
- Create: `chauffeur/tests/fixtures/twin_reads/recorded/claude/plot-place.json`, `photo_parts.json`, `sheet_roles-hint.json`, `chauffeur/tests/test_twin_place_replay.py`

**Interfaces:**
- `python tools/twin_live.py record-place --sheets <pdf> --plot-page <n> --photos <jpg> [<jpg> ...] --budget 1.00 --models claude`:
  - runs one plot read on the plot page;
  - runs one `photo_parts` read on at most 4 photos;
  - runs one `sheet_roles` read with part context on the plans PDF;
  - uses fresh scratch storage (as `compare` does), stops before any read whose estimate would pass the budget, writes `{answer, usage, model}` files, and redacts keys;
  - prints the spend.
- `test_twin_place_replay.py` stubs only `model_pools.call_pool_json` with the recorded answers, as `test_twin_build_replay.py` does. It checks that each answer parses with no problems. The plot answer yields at least two suggestions, a lot with a street edge, and a placement that confirms. The sheet_roles answer yields rows whose roles fit their part.

- [ ] **Step 1: Write `test_twin_place_replay.py`** against the fixture paths. It fails while they're missing.
- [ ] **Step 2: Implement `record-place`** (Codex), with an offline test in `tests/test_twin_live_tool.py` (`scenario_record_place_budget`: a stub reader at a $0.40 estimate per read and a $1.00 budget makes two reads and refuses the third).
- [ ] **Step 3: Controller runs the recording once** on the user's own documents with provider anthropic and `--budget 1.00`. Check the files for keys, and confirm the printed spend is at most $1.00.
- [ ] **Step 4: Run and see them pass:** `test_twin_place_replay.py` and `test_twin_live_tool.py`.
- [ ] **Step 5: Controller commits** `test(twin): the plot plan, photo and page-hint reads recorded once on real documents and replayed (slice 1b-i task 9)`.

### Task 10: Ship 1b-i (controller)

- [ ] Whole-branch review on the most capable model, then one fix dispatch and one scoped re-review. Residuals become rulings in the ledger.
- [ ] Gate run: every suite named in Tasks 1–9 exits 0.
- [ ] `chauffeur/system_capabilities.md`: a new top entry for the version, covering what shipped, the suites and counts, and parked notes, with shipped work only (`system-capabilities-is-shipped-only`). Bump `chauffeur/config.yaml`, commit, push.
- [ ] Memory: update `house-digital-twin-arc.md` (1b-i shipped; NEXT = Task 19 live acceptance on Your place, then 1b-ii) and its `MEMORY.md` line.
