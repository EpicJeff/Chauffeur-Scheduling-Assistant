# House piece 3: the Home Assistant link and live layer, implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rooms link to real Home Assistant areas, every device in a linked area appears in its room, a person places devices on anchors and surfaces (with Blink to identify), and the 3D house shows live markers, a room panel and a Lights mode that control the real house through the household's control rulebook.

**Architecture:** A new server module `services/twin_ha.py` joins the HA area, floor and device registries into one catalogue keyed by area id and device id, and computes suggestions, auto spots, obvious placements and count notes from the schema-3 model. Placements are model data (anchor `device` field plus a building `devices` list) changed only through new `twin_model_ops` operations, so the editor and Argyle share them. The 3D view (`static/twin/twin_view.js`) gains a live layer that reads a layout route once, polls the existing `api/ha/card/states`, and sends every control through the existing guarded `api/ha/card/service` with `window.chfControlFetch`.

**Tech Stack:** Python 3 / FastAPI, three.js ES modules (vendored), Playwright live tests via `tests/live_app.py`, node checks for pure JS.

**Spec:** `docs/superpowers/specs/2026-11-09-house-connected-model-design.md` §4.3 (hosts, anchors, devices), §7 (the HA link), §9 piece 3; the twin design `docs/superpowers/specs/2026-11-06-house-digital-twin-design.md` §5 (live layer) and §10 (control). The control rulebook (v2.499.773, `services/control_rules.py`) governs every control.

## Global Constraints

- Work only in worktree `E:\repositories\Chauffeur-house-ha-link`, branch `house-ha-link`. No version bump on the branch.
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset. Every critical path has one test that runs it (TestClient request, node run, or live browser), never a source grep.
- Every HA touchpoint degrades gracefully: with no Home Assistant the house renders and edits; the area pick-list, device lists, markers, room panel device rows and modes are absent; nothing errors or logs a traceback.
- Every control goes through `control_rules` (the household grid). Twin taps are a hand path like tiles: `api/ha/card/service` via `window.chfControlFetch`, which already handles `needs: 'pin' | 'identify'`. Never a new unguarded control route.
- New routes get a rule in `services/auth.py` placed above any prefix that would shadow it.
- Page JS fetches `base() + 'api/...'` (ingress-relative), never `/api/...`.
- No `alert`, `confirm`, `prompt`; use `showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice`.
- Vendored Alpine: coerce bound booleans with `!!`.
- After any template class change run `python tools/build_tailwind.py`.
- Never add packages to `requirements.txt`.
- Model changes go through `twin_model_ops.apply` and `twin_store.update_model`; ops refuse with a plain sentence (`Refused`).
- Fixed copy:
  - pick-list empty option: `No area`
  - suggestion: `Suggested: {area name}` with button `Use`
  - unlinked areas heading: `Areas with no room`
  - count note: `The plan shows {n} {plural kind}; Home Assistant has {m} in this area.` (plural kinds: `lights`, `switches`, `fans`, `cameras`, `sensors`, `outlets`)
  - gone area flag: `This room's Home Assistant area is gone; pick another.`
  - unknown area refusal: `Pick an area from Home Assistant.`
  - Blink button: `Blink`; Blink failure: `Could not blink that light.`; non-light: `Only lights can blink.`
  - no HA, in the editor: `Home Assistant is not connected, so areas and devices are hidden.`
  - placement refusal for an occupied anchor: `That spot already holds a device; move it first.`
  - unreachable HA on a tap: `Home Assistant is not reachable.`
  - Lights mode button: `Lights`; leaving a mode: `All`

## Review Focus

1. An area deleted or renamed in HA after a room was linked: a rename changes nothing (the link is by area id); a deletion flags the room with the gone-area copy and its devices vanish from markers without errors. Tests in Task 1 and Task 3.
2. A device moved to another HA area after it was placed: it stays where the person placed it (the person's placement wins), and the room panel of its new area lists it. Test in Task 3.
3. Two rooms linked to the same area (an open plan split by a separator): allowed; unplaced devices take auto spots in the largest of those rooms; the room panel opens with the same devices from either room. Test in Task 1.
4. Home Assistant stops answering mid-session: markers keep their last state drawn as stale (dimmed), taps show the unreachable copy via `showGlobalAlert`, nothing throws. Test in Task 6.
5. The rulebook refuses a tap at the panel: the existing `chfControlFetch` message or PIN path appears; the marker never flips optimistically to a state the house did not reach. Test in Task 6.

---

### Task 1: The house's Home Assistant catalogue (server)

**Files:**
- Modify: `chauffeur/services/ha_api.py` (add `get_floor_registry`)
- Create: `chauffeur/services/twin_ha.py`
- Test: `chauffeur/tests/test_twin_ha.py`

**Interfaces:**
- Produces:
  - `ha_api.get_floor_registry(ttl=300) -> list[{floor_id, name, level}]` via `_registry_list` on ws command `config/floor_registry/list`; `[]` with no HA.
  - `twin_ha.catalogue() -> {'available': bool, 'areas': [{area_id, name, floor_id, floor_name}], 'floors': [...], 'devices': [{device_id, name, area_id, kind, entity_id, entities: [entity_id]}]}`. `available` is true only when HA is configured and the area list is non-empty. Devices come from `house._catalogue()` grouped by `_device_id`; an entity with no device becomes its own pseudo device `entity:<entity_id>`. `area_id` is mapped from the catalogue's area NAME back to an id through `get_area_registry`. `kind` is the anchor kind the device fits: `light` (domain light), `switch` (switch, input_boolean), `fan`, `camera`, `sensor` (binary_sensor, sensor), `lock`, `garage` (a cover that `control_rules.kind_of` calls garage), `blinds` (other covers), `climate`, `media`, else `other`; decided by the device's entities in that priority order. `entity_id` is the primary entity: the first entity whose domain matches the kind, in registry order.
  - `twin_ha.resolve_area(value, areas) -> str|None`: an area id if `value` is one; else the id whose name matches case-insensitively (a legacy name stored in `ha_area`); else None.
  - `twin_ha.suggest(model, areas) -> {room_id: area_id}` for unlinked rooms: exact name match after lowercasing and dropping punctuation, then the area name contained in the room name or the reverse; an area already linked or suggested is not suggested twice; when several rooms tie, prefer the room on the level whose index matches the area floor's `level`.
  - `twin_ha.rooms_for_area(model, area_id) -> [room]`, largest region first.
  - `twin_ha.auto_spots(model, catalogue) -> {device_id: {'building', 'level', 'room', 'at': [x, y], 'z'}}` for every device in a linked area with no placement: a grid inside the largest linked room's polygon (centroid first, then 2 ft steps, staying inside the polygon); `z` at the ceiling for lights and fans, 4 ft otherwise.
  - `twin_ha.placements(model) -> {device_id: {'kind': 'anchor'|'host', 'building', 'anchor'?: id, 'host'?: {...}, 'offset'}}` reading anchors' `device` and the building `devices` list (Task 2's shape).
  - `twin_ha.count_notes(model, room_id, catalogue) -> [str]` using the fixed count copy, one per kind where the room's anchors of that kind and the area's devices of that kind differ and both are non-zero.
  - `twin_ha.obvious(model, room_id, catalogue) -> [{'device', 'building', 'host': {'opening': opening_id, 'side': 'in'}}]`: each unplaced `garage` device onto a garage opening on the room's walls (in wall order, one each); a `lock` device onto an exterior door of the room (opening kind door on an `exterior` wall), only when exactly one such door exists.
  - `twin_ha.gone_rooms(model, areas) -> [room_id]`: rooms whose `ha_area` is set but not in `areas` (only when `areas` is non-empty).

- [ ] **Step 1: Write the failing tests** in `tests/test_twin_ha.py` with a fake HA patched onto `ha_api` (pattern: `tests/test_control_endpoints.py` setUp/tearDown; areas and floors through a fake `ws_command`). Scenarios: `test_catalogue_groups_entities_by_device`, `test_catalogue_without_ha_is_empty_and_quiet` (`ha_api` unconfigured: returns `available` False and empty lists), `test_resolve_area_accepts_ids_and_legacy_names`, `test_suggest_matches_names_once_and_prefers_floor`, `test_two_rooms_one_area_auto_spots_in_largest` (Review Focus 3), `test_auto_spots_stay_inside_an_l_shaped_room`, `test_count_note_copy` (asserts exactly `The plan shows 5 lights; Home Assistant has 4 in this area.`), `test_obvious_places_garage_and_lock`, `test_deleted_area_reads_as_gone`, `test_renamed_area_keeps_the_link` (Review Focus 1).
- [ ] **Step 2:** Run `python tests/test_twin_ha.py`; expect failures on the missing module.
- [ ] **Step 3:** Implement `get_floor_registry` and `services/twin_ha.py` to the interfaces above.
- [ ] **Step 4:** Run `python tests/test_twin_ha.py` and `python tests/test_ha_api.py`; all pass.
- [ ] **Step 5:** Commit `feat(twin-ha): the house's view of Home Assistant areas, floors and devices`.

### Task 2: Placements are model data (operations)

**Files:**
- Modify: `chauffeur/services/twin_model.py` (normalize the `devices` list; the `opening` host), `chauffeur/services/twin_model_hosts.py` (an opening host follows its opening; unhosted when the opening goes), `chauffeur/services/twin_model_ops.py`, `chauffeur/services/twin_model_bridge.py` (round-trip `devices`), `chauffeur/services/twin_edit.py` (room `ha_area` validation), `chauffeur/services/agent_tools_v2.py` (`house_design` argument shapes for the new ops)
- Test: `chauffeur/tests/test_twin_model_devices.py`

**Interfaces:**
- Consumes: Task 1 `twin_ha.catalogue`, `resolve_area`, `obvious`.
- Produces:
  - Building field `devices: [{id: 'device:<ha device id>', device: <ha device id>, host: {...}, offset: float, src}]` for devices hosted directly on a surface or an opening. A device on an anchor lives only in that anchor's `device` field. Invariant: a HA device id appears at most once across all anchors and `devices` lists of the whole model.
  - New host shape `{opening: <opening id>, side: 'in'|'out'}`; `world_point` puts it on the opening's centre line, 3.5 ft above the level for a door, the sill + 1 ft for a window. When the opening is deleted the device becomes unhosted and flagged (spec §4.3: kept, visible, flagged).
  - Ops (all through `twin_model_ops.apply`):
    - `{'op': 'place_device', 'device': id, 'anchor': anchor_id}` or `{'op': 'place_device', 'device': id, 'building': b, 'host': {...}, 'offset'?: f}`. Removes any earlier placement of that device first. Refuses an anchor that holds another device with the fixed occupied copy.
    - `{'op': 'unplace_device', 'device': id}` removes it from anchors and lists; the device goes back to its auto spot.
    - `set` on a room's `ha_area` accepts an area id or `''`; when the area list is non-empty an unknown value refuses with the unknown-area copy; when HA is unavailable the value is stored as given. A legacy name is stored as its resolved id. Setting a room's area then runs `twin_ha.obvious` for that room and places those devices with `src: {'auto': True}` in the same round (spec §7: obvious devices place themselves; the person can still move them).
  - `house_design` gains `place_device` and `unplace_device` with the same argument shapes.

- [ ] **Step 1: Write failing tests** `test_place_on_anchor_then_move_to_wall`, `test_one_device_one_place`, `test_occupied_anchor_refused` (exact copy), `test_lock_follows_its_door_when_the_wall_moves`, `test_deleting_the_door_unhosts_and_flags_the_lock`, `test_set_area_by_name_stores_id`, `test_set_unknown_area_refused_only_when_ha_answers`, `test_linking_the_garage_places_its_doors` (garage devices land on garage openings with `src.auto`), `test_devices_survive_flatten_and_assemble`, `test_house_design_places_a_device` (runs the Argyle tool function).
- [ ] **Step 2:** Run `python tests/test_twin_model_devices.py`; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `test_twin_model_devices.py` plus `test_twin_model.py`, `test_twin_model_hosts.py`, `test_twin_model_bridge.py`, `test_twin_model_ops_walls.py`, `test_twin_model_ops_more.py`, `test_twin_edit.py`, `test_house_design_tool.py`, and every `tests/test_twin_build*.py`; all pass.
- [ ] **Step 5:** Commit `feat(twin): devices are placed on anchors, surfaces and doors as model data`.

### Task 3: Routes for the link and the live layer

**Files:**
- Modify: `chauffeur/main.py`, `chauffeur/services/auth.py`
- Test: `chauffeur/tests/test_twin_ha_routes.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces:
  - `GET /api/house/ha/link` (PARENTS) -> `{'available', 'areas', 'floors', 'rooms': [{building, level, room, name, ha_area, suggested?, gone: bool, notes: [str]}], 'unlinked': [{area_id, name}], 'devices': [{device_id, name, kind, area_id, entity_id, placed: {...}|None, auto: {...}|None}]}`.
  - `GET /api/house/live` (WALL) -> `{'available', 'markers': [{device_id, name, kind, entity_id, entities, room, building, level, at: [x, y, z] in lot feet after building position and rotation, placed: bool, offered: bool}], 'rooms': [{room, building, level, area_id, name, polygon_world, lights: [entity_id]}]}`. `offered` is `control_rules.offered(who, entity_id)` for the caller. A device whose area is gone or that HA no longer lists is omitted. With no HA: `available` false, `markers` empty, `rooms` listed with `area_id` null.
  - `POST /api/house/ha/identify` (PARENTS) body `{device_id}`: runs `control_rules.guard(request, [entity_id])` first; for a light, `light.turn_on` with `flash: 'short'` when its `supported_features` has the flash bit (8), otherwise a toggle then a restore of the earlier state after 1.5 s on a background thread; returns `{'ok': True, 'how': 'flash'|'toggle'}`; a non-light returns 400 with the non-light copy.
  - Auth rules for the three routes next to `('GET', '/api/house/twin', ...)`.

- [ ] **Step 1: Write failing TestClient tests:** `test_link_lists_rooms_suggestions_and_unlinked`, `test_link_without_ha` (`available` false, empty lists, 200, no error log), `test_live_positions_follow_building_rotation`, `test_live_omits_devices_whose_area_is_gone` (Review Focus 1), `test_moved_device_keeps_its_placement` (Review Focus 2), `test_live_offered_follows_the_grid` (a panel caller with locks off sees `offered: False` on a lock), `test_identify_flash_and_toggle_restore`, `test_identify_guarded` (a guest is refused with 403), plus the repository's every-route-has-a-rule check passing.
- [ ] **Step 2:** Run `python tests/test_twin_ha_routes.py`; expect failures.
- [ ] **Step 3:** Implement routes and auth rules.
- [ ] **Step 4:** Run `test_twin_ha_routes.py`, `test_twin_ha.py`, `test_control_endpoints.py`, `test_house_editor_routes.py`, and the auth coverage test (find it with `grep -l "RULES" tests/test_auth*.py`); all pass.
- [ ] **Step 5:** Commit `feat(twin-ha): link, live and identify routes`.

### Task 4: The editor links rooms to areas

**Files:**
- Create: `chauffeur/static/twin/editor/ha_link.js` (fetches `api/house/ha/link`, renders the pick-list, suggestions, the unlinked list, the no-HA line)
- Modify: `chauffeur/static/twin/editor/cards.js` (room `ha_area` becomes the pick-list from `ha_link.js`), `chauffeur/static/twin/editor/editor.js` (import and wiring), the editor template's import map if it lists modules
- Test: `chauffeur/tests/test_twin_ha_link_js.py` (node), `chauffeur/tests/test_house_editor_model_live_t18.py` (live)

**Interfaces:**
- Consumes: Task 3 link route; the existing `applyOpNow` in `editor.js`.
- Produces: `createHaLink({ api, onCommit, signal }) -> { refresh(): Promise, roomSection(room): HTMLElement, buildingSection(building): HTMLElement, state() }`, exposed on `window.__twinEditor.haLink` for tests.
  - Room card: a `<select>` labelled `Home Assistant area` with `No area` plus every area by name (in `<optgroup>`s per floor when floors exist); a suggestion row `Suggested: Kitchen` with a `Use` button that commits `set ha_area`; the gone-area copy when `gone`.
  - Building card: `Areas with no room` listing unlinked areas; tapping one runs `promptChoice` over the building's rooms, then commits `set ha_area`.
  - No HA: the room card shows the no-HA copy in place of the select; nothing else changes.

- [ ] **Step 1: Write failing tests.** Node: `pick_list_groups_by_floor`, `suggestion_use_commits_set`, `no_ha_shows_the_line`. Live t18 (a fake HA patched in-process onto `ha_api` before the app serves): `scenario_room_card_picks_an_area`, `scenario_suggestion_use_links_and_places_the_garage_doors`, `scenario_unlinked_area_is_placed_on_a_room`, `scenario_no_ha_editor_still_edits`.
- [ ] **Step 2:** Run both; expect failures.
- [ ] **Step 3:** Implement; rebuild Tailwind if template classes changed.
- [ ] **Step 4:** Run the node test, t18, and t10 plus t15 (cards and library neighbours); all pass.
- [ ] **Step 5:** Commit `feat(twin-editor): rooms link to Home Assistant areas`.

### Task 5: The editor places devices room by room

**Files:**
- Modify: `chauffeur/static/twin/editor/ha_link.js`, `chauffeur/static/twin/editor/cards.js` (an anchor card shows its device with `Remove`), `chauffeur/static/twin/editor/editor.js` (drop handling)
- Test: `chauffeur/tests/test_house_editor_model_live_t19.py`

**Interfaces:**
- Consumes: Task 2 ops, Task 3 link and identify routes, Task 4 `roomSection`, Task 6 `markers.js` builder (Task 5 runs after Task 6).
- Produces: in the room card a `Devices` section listing the area's devices (name, kind, `Placed` or `Not placed yet`) beside the room's anchors, with the count notes under it.
  - Per device: `Pick a spot` opens `promptChoice` over the room's free anchors of a fitting kind plus `On a wall` and `On the ceiling` (these arm a one-click placement on the next surface click; Escape cancels); `Blink` for lights (calls identify; failure shows the fixed copy).
  - Dragging a device row onto the 3D scene: a drop on an anchor commits `place_device` with `anchor`; a drop on a wall, floor or ceiling commits it with that host at the drop point (the editor's existing surface pick decides the host).
  - Placed and auto-spot devices draw in the editor as small markers in their resting look.

- [ ] **Step 1: Write failing live scenarios:** `scenario_pick_a_spot_on_an_anchor`, `scenario_drag_a_device_onto_a_wall`, `scenario_occupied_anchor_says_so`, `scenario_blink_calls_identify` (the fake HA recorded `light.turn_on` with `flash`), `scenario_count_note_shows`, `scenario_escape_cancels_an_armed_placement`.
- [ ] **Step 2:** Run t19; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run t19, t18, t10, t13; all pass.
- [ ] **Step 5:** Commit `feat(twin-editor): place each room's devices, with Blink`.

### Task 6: Live markers in the 3D house

**Files:**
- Create: `chauffeur/static/twin/live/markers.js` (marker builder and looks), `chauffeur/static/twin/live/live.js` (layout fetch, state poll, taps)
- Modify: `chauffeur/static/twin/twin_view.js` (mount the live layer when `api/house/live` says available), `chauffeur/templates/house_twin.html` (import map entries; the `control_center.html` helpers present on the page)
- Test: `chauffeur/tests/test_twin_markers_js.py` (node), `chauffeur/tests/test_house_twin_live_markers.py` (live)

**Interfaces:**
- Consumes: Task 3 live route; the existing `GET api/ha/card/states?fresh=0|1` (poll every 10 s, `fresh=1` right after a control) and `POST api/ha/card/service` via `window.chfControlFetch`.
- Produces:
  - `markerState(kind, state, attributes) -> {look: 'on'|'off'|'attention'|'unavailable', label: str}`: attention for a lock `unlocked`, a garage `open`/`opening`, binary sensors of class `smoke`, `moisture` or `gas` that are `on`; unavailable for `unavailable`/`unknown`.
  - `mountLive(view, { api }) -> { refresh(), setMode(name|null), markers(), stop() }`, on `window.__twin.live` under `?test=1`.
  - One marker per device at its `at`, a screen-space sprite with an icon per kind. Levels of detail: zoomed far out, a room's markers merge into one room badge with a count that shows any attention; labels appear only zoomed in.
  - Tap: a light or switch toggles via `homeassistant.toggle`; a lock, garage or alarm opens a small sheet with explicit actions (`Lock`/`Unlock`, `Open`/`Close`) and `promptConfirm` before unlocking or opening; anything else opens the room panel (Task 7). Only `offered` markers act; others show state.
  - A marker shows the confirmed state from the next poll, never an optimistic flip (Review Focus 5).
  - Stale: when the state poll fails, markers dim and a tap shows the unreachable copy (Review Focus 4).

- [ ] **Step 1: Write failing tests.** Node: `marker_states_cover_attention_and_unavailable`, `room_badge_merges_at_far_zoom`. Live: `scenario_markers_sit_at_placed_positions` (a placed light's screen position is within 12 px of its projected `at`), `scenario_tap_light_toggles_through_the_card_service`, `scenario_unlock_asks_first`, `scenario_refused_tap_shows_rulebook_message_and_no_flip`, `scenario_ha_stops_answering_dims_markers`, `scenario_no_ha_twin_renders_without_markers`.
- [ ] **Step 2:** Run both; expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run both plus the existing twin view live suite (`ls tests/test_twin_view*live*.py`); all pass.
- [ ] **Step 5:** Commit `feat(twin-live): device markers with live state and taps`.

### Task 7: The room panel, Lights mode and the wall panel

**Files:**
- Create: `chauffeur/static/twin/live/room_panel.js`, `chauffeur/static/twin/live/modes.js`
- Modify: `chauffeur/static/twin/live/live.js`, `chauffeur/static/twin/twin_view.js` (room picking on tap), `chauffeur/templates/house_twin.html` (under `?panel=true&kiosk=true`: no nav chrome, the mode strip), the House page shelf (`chauffeur/static/house.js` or its template) gains a `3D house` button linking to `house/twin` that keeps the `panel` and `kiosk` flags
- Test: `chauffeur/tests/test_house_twin_live_rooms.py` (live)

**Interfaces:**
- Consumes: Task 6 `mountLive`, Task 3 live route.
- Produces:
  - Tapping a room's floor (not a marker) opens a side panel titled with the room name listing every device of its area (placed or not), each with its control: lights a toggle and a brightness slider (`light.turn_on` `brightness_pct`); switches and fans a toggle; locks and garage explicit actions with `promptConfirm`; climate the current temperature and setpoint steppers (`climate.set_temperature`); sensors their reading. Controls render only when `offered`; otherwise state only.
  - Mode strip with `Lights` and `All`. Lights mode: each room's floor glows by its lights' brightness (mean of `brightness / 255` over lights that are on; rooms with every light off stay dark), tinted by the lights' `rgb_color` when present; non-light markers dim.
  - Under `?panel=true&kiosk=true` the page shows only the house, the mode strip and the room panel, never editing links.

- [ ] **Step 1: Write failing live scenarios:** `scenario_tap_kitchen_opens_its_devices` (the spec exit: in a panel-token session, tapping the kitchen floor lists its devices and toggling a light calls the card service), `scenario_brightness_slider_sets_percent`, `scenario_lights_mode_lights_rooms`, `scenario_panel_kiosk_has_no_editing`, `scenario_house_page_links_to_the_3d_house`, `scenario_room_panel_respects_the_grid` (locks off for the panel: the lock row shows state only).
- [ ] **Step 2:** Run; expect failures.
- [ ] **Step 3:** Implement; rebuild Tailwind.
- [ ] **Step 4:** Run this suite, the Task 6 suites, and the House page live suite (`ls tests/test_house*live*.py`, the one that loads `/house`); all pass.
- [ ] **Step 5:** Commit `feat(twin-live): room panel, Lights mode and the wall panel`.

## Execution order

Tasks 1, 2, 3, 4, 6, 5, 7 (Task 5 reuses Task 6's marker builder in the editor).
