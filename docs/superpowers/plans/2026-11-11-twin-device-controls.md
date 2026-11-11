# Real device controls in the 3D house Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Control every common device from where it sits in the 3D house:
- tap a light, switch, outlet or fan to toggle it, or press-and-hold for a ring of controls at the marker;
- full Home Assistant cards one level deeper;
- live state pushed from Home Assistant.

**Architecture:**
- **Registries.** Marker kinds and modes become registries (`live/kinds.js`, `live/modes.js`). One shared builder per kind draws the ring at the marker and the room panel row (`live/controls/*.js`).
- **Control path.** Every control goes through `live.control` to `api/ha/card/service` and the household grid.
- **Live state.** A server websocket subscriber pushes `state_changed` events over an SSE route; polling stays as the fallback.
- **The "More" level.** The room panel mounts Home Assistant's own cards through the existing card host.

**Tech Stack:** FastAPI, a stdlib websocket client (no new packages), SSE (`StreamingResponse`), vendored three r187, ES modules, node and Playwright tests.

**Spec:** `docs/superpowers/specs/2026-11-11-twin-device-controls-design.md` (the user's answers are in §5).

## Global Constraints

- **Gestures:** tap toggles a light, switch, outlet or fan. Press-and-hold (500 ms), or a tap on an open ring's centre, opens the ring. Every other kind opens its ring on tap (user, 2026-11-11).
- **Ring:**
  - an HTML overlay anchored to the marker's projected position, following the camera;
  - 44 px targets;
  - closes on a tap outside or Escape;
  - no hover-only affordances;
  - works by touch on the wall panel.
- **Shared builder:** the ring and the room panel's expanded row are drawn by the same builder per kind (UI guide: same concept, same builder).
- **Safety:** every control goes through `live.control` (`api/ha/card/service` via `window.chfControlFetch`). Unlock, open (garage) and disarm confirm exactly once. A device shows only confirmed state, never an optimistic flip.
- **"More":** Home Assistant's cards (`ChauffeurHaCards.mountBuiltin`) for light, thermostat, humidifier, and tile for other kinds. Never for lock, garage or alarm. Our ring is the fallback when a mount refuses.
- **Camera:** `GET api/house/camera/{entity_id}` (WALL_OR_SERVICE) fetches HA's `camera_proxy` server-side and obeys the grid's view rule; no token reaches the page. The page refreshes the still every 2 s while it is open.
- **Live state:** `GET api/ha/stream?entities=...` (WALL_OR_SERVICE, SSE).
  - It is fed by `services/ha_events.py`, a long-lived HA websocket subscription to `state_changed` that also warms `ha_api`'s state cache.
  - Polling stays at 10 s as the fallback.
  - With no HA nothing connects and nothing errors.
- **Copy:** button labels are plain verbs (`Lock`, `Unlock`, `Open`, `Close`, `Stop`, `More`). Mode chips use HA's own mode names, title-cased.
- **Standing rules:** no browser dialogs; page JS fetches `base() + 'api/...'`; every new route has an auth tier; no new packages; run `python tools/build_tailwind.py` after template class changes; tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset.

## Review Focus

1. **A control while the SSE stream is down:** the marker still confirms through the poll, and nothing hangs.
2. **A long-press on a marker over another marker or the room badge:** the right device's ring opens, and a drag that orbits the camera never opens a ring.
3. **Two quick drags of a ring arc:** only the final value is sent (debounced), and the ring shows the confirmed value after.
4. **A device the grid does not offer:** the ring shows state read-only, with no actionable control.
5. **HA restarts:** the websocket reconnects with back-off, the SSE clients keep their connection, and state resumes.

---

### Task 1: Registries
**Files:** create `static/twin/live/kinds.js`; refactor `static/twin/live/modes.js` into a registry; modify `markers.js`, `room_panel.js` and `live.js` to read the registries. Test: node `tests/test_twin_kinds_js.py`.
**Interfaces:**
- `registerKind({id, match(entity), icon, look(state), quick, ring, panel, unsafe})`, `kindOf(entity)`;
- `registerMode({id, label, enter, update, leave})`, `modes()`.
- Lights and All register as modes.
- The existing kinds move into registrations with identical behaviour.

- [ ] Tests:
  - `every_existing_kind_behaves_as_before`, a table check against today's markerState, icons and deviceActions;
  - `a_new_kind_registers_without_core_edits`;
  - `modes_register_and_switch`.
- [ ] Fail, implement, pass. Keep green: test_twin_markers_js, test_twin_live_rooms_js, test_twin_live_control_js, test_twin_real_lights_js.
- [ ] Commit `refactor(twin-live): device kinds and modes are registries`.

### Task 2: Live state push
**Files:** create `services/ha_events.py`; modify `main.py` (SSE route, startup and shutdown), `services/auth.py`, `static/twin/live/live.js` (subscribe, with the poll as fallback). Test: `tests/test_ha_events.py` (TestClient plus a fake HA websocket).
- [ ] Tests:
  - `state_changed_reaches_a_subscriber_within_a_second`;
  - `filter_by_entities`;
  - `no_ha_no_errors`;
  - `reconnects_with_backoff` (Review Focus 5);
  - `stream_route_auth_tiers`;
  - `live_layer_falls_back_to_poll_when_stream_drops` (node).
- [ ] Fail, implement, pass. Commit `feat(ha): live state pushed to the house`.

### Task 3: Ring host and the light ring
**Files:** create `static/twin/live/ring.js` (overlay anchored to a marker, gestures) and `static/twin/live/controls/light.js` (shared builder); modify `live.js` (tap and hold), `room_panel.js` (expanded row uses the builder), `templates/house_twin.html` (ring CSS). Test: node `tests/test_twin_ring_js.py`; live `tests/test_house_twin_controls_live.py`.
- [ ] Tests:
  - node: `tap_toggles_hold_opens_ring`, `drag_never_opens_a_ring` (Review Focus 2), `ring_follows_the_marker`, `light_ring_parts_follow_supported_color_modes`, `arc_drags_are_debounced` (Review Focus 3), `unoffered_ring_is_read_only` (Review Focus 4);
  - live: `scenario_tap_toggles_kitchen_light`, `scenario_hold_opens_ring_and_sets_brightness_and_colour` (fake HA records the service calls; the marker and the real/baked light follow the confirmed state).
- [ ] Fail, implement, pass. Commit `feat(twin-live): a ring of light controls at the light`.

### Task 4: Climate, fan, cover, media, lock, alarm, vacuum, humidifier, water heater, scene and script rings
**Files:** `static/twin/live/controls/{climate,fan,cover,media,lock,alarm,vacuum,humidifier,water_heater,scene}.js`, registered in `kinds.js`. Test: node `tests/test_twin_controls_js.py`; live scenarios in `test_house_twin_controls_live.py`.
- [ ] Tests:
  - node, one per kind against HA attribute shapes: setpoint handles for heat, cool and heat_cool (two handles); hvac mode chips; fan speed by `percentage_step`; cover position and tilt; media volume and source; alarm modes and code sheet; vacuum actions; scene `turn_on`; script `turn_on`.
  - live: `scenario_thermostat_arc_sets_70_and_cool`, `scenario_blind_to_half`, `scenario_speaker_volume`, `scenario_unlock_asks_once`, `scenario_alarm_code_sheet_not_a_dialog`.
- [ ] Fail, implement, pass. Commit `feat(twin-live): controls for every common device`.

### Task 5: Cameras and HA's own cards as "More"
**Files:** `main.py` (`GET api/house/camera/{entity_id}`), `services/auth.py`, `static/twin/live/controls/camera.js`, `room_panel.js` ("More" mounts `ChauffeurHaCards.mountBuiltin`), `templates/house_twin.html` (loads `static/ha_card_host.js`). Test: `tests/test_twin_camera_route.py` (TestClient); live scenarios.
- [ ] Tests:
  - TestClient: `camera_still_through_the_server_no_token_on_page`, `camera_obeys_the_grid`, `no_ha_camera_404s_plainly`;
  - live: `scenario_camera_ring_shows_a_still_and_refreshes`, `scenario_more_opens_the_ha_light_card_and_it_controls_through_the_grid`, `scenario_lock_has_no_more_card`, `scenario_card_refusal_falls_back_to_our_ring`.
- [ ] Fail, implement, pass. Commit `feat(twin-live): cameras and Home Assistant's own cards`.

**Execution order:** 1, then 2 (independent of 3-5, may run beside them), then 3, 4, 5. Tasks 3-5 each get a Claude browser round after Codex.

**Exit, at the wall panel (spec §4):** tap the kitchen light; hold it to set 40% and blue; set the thermostat to 70 and cool; set a blind to half; change a speaker's volume; see a camera; change a light in the HA app and see it here within 1 s.
