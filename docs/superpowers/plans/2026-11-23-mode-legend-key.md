# Mode legend key button Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-visible joined-string mode legend with a key button on the mode strip that opens one compact card of colour swatches per active mode.

**Architecture:** Each mode supplies structured key data (`key()`); one shared builder `live/mode_key.js` renders the button and card from the active modes; `live/modes.js` drives it in place of `#twin-mode-legend` text.

**Tech Stack:** Vanilla ES modules in `chauffeur/static/twin/live/`, styles in `chauffeur/templates/house_twin.html`, node-run JS tests and one Playwright Chromium viewer test.

**Spec:** `docs/superpowers/specs/2026-11-23-mode-legend-key-design.md` (owner-approved 2026-11-23).

## Global Constraints

- Paths are relative to `chauffeur/`. Tests run from `chauffeur/` with `HA_BASE_URL` unset; never the whole suite.
- Swatch colours come from the same constants the modes draw with (export them where they are defined); never duplicate hex values.
- No browser dialogs. Same concept = same shared builder (docs/ui_design_guide.md). Tailwind is precompiled: if template classes change, run `python tools/build_tailwind.py` (prefer plain CSS in the template's style block, as the twin page already does).
- Closed by default; open state per device in localStorage key `chauffeur.twin.legend.v1`.
- Do not remove anything a person can reach today: the energy check controls ("Why no ribbons?", wall-panel read-only check) stay reachable inside the Energy section; the Lights overflow note stays as the Lights note.
- Implementer (Codex) does not commit or bump.

## Review Focus

1. Two or more modes on with the card open must not overlap the glance bar at 1920x1080 or a 390x844 phone; the card scrolls past 60dvh.
2. A mode turned off while the card is open removes its section immediately; turning off the last keyed mode hides the button and closes the card.
3. Keyboard: the button is reachable and toggles with Enter/Space; Esc closes and returns focus to the button.
4. Wall panel (`?panel=true&kiosk=true`): tap opens, tap in scene closes; the energy read-only check still works inside.
5. Alarm summary with mixed states and with stale HA ("unavailable").

---

### Task 1: Key data, builder, wiring, browser check

**Files:**
- Create: `static/twin/live/mode_key.js`
- Modify: `static/twin/live/modes.js:99-100, :282-284, :337` (replace the joined-string legend), `static/twin/live/climate.js:115`, `static/twin/live/energy.js:283, :409`, `static/twin/live/security.js:191-195`, the Lights overflow note source in modes.js, `templates/house_twin.html:278, :348-362` (styles)
- Test: `tests/test_twin_mode_key_js.py` (node), `tests/test_house_twin_mode_key_live.py` (Chromium; harness `tests/house_twin_live_harness.py`)

**Interfaces:**
- Each registered mode may provide `key(): {items: [{swatch: string /* css colour from the mode's constant */ | 'cone', label: string}], note?: string, status?: string, content?: Node[]}`. Climate: Heating, Cooling, Idle. Energy: Solar, Battery, Grid, Car charger; note "Flows under 50 W are hidden" (or the existing placement guidance text when anchors are missing); `content` = the existing `checkControls`. Security: "Open or unlocked" (red), camera view (`'cone'`, label "Camera view" plus " · 25 ft" when no saved views); `status` = `alarmSummary(panels, stale)`.
- `alarmSummary(panels:[{state}], stale:boolean) -> string`: all same state gives "Alarm · <state with spaces> (n of n)"; mixed gives "Alarm · <most common> (k of n)" with the full list available behind a disclosure in the card; stale or none available gives "Alarm · unavailable"; no panels gives "".
- `mountModeKey(strip, {getSections: () => [{id, icon, name, key}], storage}) -> {update(), close(), button, card}`. The button is appended to the mode strip with accessible name "Legend" and `aria-expanded`. The card has `role="dialog"` with `aria-label="Legend"`.

- [ ] **Step 1: Write the failing node tests** in `tests/test_twin_mode_key_js.py`:
  - `test_sections_only_for_active_modes`;
  - `test_swatches_use_mode_constants`: the climate and energy swatches equal the exported constants;
  - `test_alarm_summary`: covers all-agree, mixed, stale and none;
  - `test_no_button_without_keys`;
  - `test_open_state_persists`;
  - `test_energy_content_inside_energy_section`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement `mode_key.js` and the mode `key()` providers, and replace the legend wiring in modes.js. Remove the old `legend` strings once every mode provides `key()`, but keep any consumer that reads them (grep `legend` across static/ and tests/, and update the tests that assert the old strings).
- [ ] **Step 4:** Write the Chromium test `tests/test_house_twin_mode_key_live.py`:
  - `scenario_closed_by_default_no_legend_text`;
  - `scenario_button_opens_card_with_three_sections` (Climate, Energy and Security on);
  - `scenario_escape_closes_and_returns_focus`;
  - `scenario_state_survives_reload`;
  - `scenario_energy_check_reachable`;
  - `scenario_card_clear_of_glance_bar` at 1920x1080 and 390x844.
  Claude runs it, because Codex's sandbox cannot launch Chromium.
- [ ] **Step 5:** Claude runs the new tests plus `tests/test_twin_modes_js.py`, `tests/test_twin_security_js.py`, `tests/test_twin_energy_js.py`, `tests/test_house_twin_controls_live.py` and `tests/test_house_twin_energy_live.py`. Expected: pass, apart from the known main reds.
- [ ] **Step 6:** Look check by Claude: screenshots at the default overview with three modes on, card open and card closed, on desktop and phone sizes.
- [ ] **Step 7:** Claude commits, then lands under the AGENTS.md contract:
  1. merge main;
  2. bump;
  3. add the capabilities entry;
  4. fast-forward main and push;
  5. remove the worktree.
