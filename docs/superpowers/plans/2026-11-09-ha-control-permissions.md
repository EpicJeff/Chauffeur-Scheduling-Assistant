# One Rulebook for Home Assistant Control: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every surface that operates a Home Assistant device asks one function, against one household grid, whether this person may do it.

**Architecture:** A pure rulebook module (`services/control_rules.py`) holds the kinds, the stored grid with today's behaviour as its default, the `Who` a request resolves to, and `check()`. Scripts and scenes are expanded to what they touch by `services/control_scripts.py`. Every HTTP control endpoint and both Argyle device tools call `check()`; a refusal that can be cured by identifying the person returns `needs`, and the panel answers it with a face + PIN step that mints a one-use grant.

**Tech Stack:** FastAPI (`main.py`), services in Python, Alpine/vanilla JS templates, HA REST + websocket through `services/ha_api.py`. Tests are plain scripts run from `chauffeur/`.

**Spec:** `docs/superpowers/specs/2026-11-09-ha-control-permissions-design.md` (approved 2026-11-09). Read it first; this plan argues from it.

## Global Constraints

- Tests run from `chauffeur/` as `python tests/test_x.py`, with `HA_BASE_URL` unset. Run the task's own tests plus the named neighbours, never the whole suite.
- Every critical path has a test that runs it (TestClient request or a node run of the JS), not a source grep.
- No `alert`/`confirm`/`prompt`. Use `showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice` from `templates/components/control_center.html`.
- Every new route gets its rule in `services/auth.py` or the auth test suite flags it.
- Every HA touchpoint degrades gracefully with no Home Assistant present.
- After any template class change run `python tools/build_tailwind.py`.
- Page JS fetches `base() + 'api/...'`, never `/api/...`.
- Vendored Alpine: coerce every bound boolean with `!!`.
- Never remove anything a person can do beyond what the spec lists under Migration (three approved changes).
- Kinds (ids, in this order): `lights`, `switches`, `media`, `climate`, `blinds`, `garage`, `locks`, `alarm`, `other`.
- Roles: `parent`, `adult`, `child`, `helper`, `guest`. Places: `panel`, `unknown_voice`.
- People cells: `'yes' | 'no'`. Place cells: `'yes' | 'no' | 'ask'`.
- Never-callable domains: `homeassistant`, `hassio`, `automation`, `system_log`, `recorder`, `logger`, `notify`, `tts`, `persistent_notification`, `conversation`, `frontend`, `backup`, `update`, `zone`, `person`, `script` config services (`script.reload`, `scene.reload`, `scene.create`, `scene.apply`). `script.turn_on`/`script.<name>` and `scene.turn_on` are not refused here; they go through script analysis.
- A panel PIN grant: 60 seconds, one use, bound to the member and the panel's device id.
- A held Argyle action (typed at the panel, awaiting "Ask who"): 120 seconds.
- Do not bump `config.yaml` or commit inside a task if you are Codex; leave the tree for Claude's gate.

## Review Focus

1. **A card service call that targets an area or a list** (`{'area_id': 'kitchen'}`, `{'entity_id': ['light.a', 'lock.front']}`): every entity it reaches is checked; one lock in the list governs the call. Test in Task 4.
2. **The panel sends a member token from the avatar/critter PIN step and then taps a lock**: that ordinary token must not count as proof on a panel device (a person at a place outranks the place in `auth.identify`). Only a control grant proves. Test in Task 3.
3. **A grant replayed** (same `x-control-grant` twice, or from another device): the second use is refused. Test in Task 3.
4. **No Home Assistant at all**: the rules page loads, warnings are empty, `check()` never raises, script analysis returns "unreadable" rather than throwing. Test in Task 2 and Task 6.
5. **A short "yes" after Argyle asks to confirm an unlock by a recognised voice**: `recognized_this_turn` already carries inheritance; a proof kind still needs `level == 'verified'`, so the inherited yes cannot unlock. Test in Task 5.

---

### Task 1: The rulebook core

**Files:**
- Create: `chauffeur/services/control_rules.py`
- Test: `chauffeur/tests/test_control_rules.py`

**Interfaces:**
- Produces:
  - `KINDS: tuple[str, ...]`, `ROLES`, `PLACES`, `NEVER_DOMAINS: frozenset[str]`
  - `kind_of(entity_id: str, attributes: dict | None) -> str | None` (None for a domain that is not device control; script/scene ids return `'script'`/`'scene'` markers handled by Task 2; `attributes=None` means unread: a cover is then `'garage'`)
  - `default_rules(settings: dict) -> dict` and `rules(settings: dict | None = None) -> dict` (stored `settings['ha_control']` if present, else defaults)
  - `validate_rules(raw: dict) -> dict` (raises `ValueError` with a sentence on a bad cell)
  - `@dataclass(frozen=True) class Who: role: str | None; member_id: str | None; place: str | None; proven: bool; admin: bool = False; voice_id: bool = True`
  - `@dataclass class Decision: allowed: bool; needs: str | None; kinds: tuple[str, ...]; message: str` where `needs in (None, 'identify', 'pin')`
  - `decide(who: Who, kinds: Iterable[str], rules: dict) -> Decision` (pure; no HA)

Stored shape of `settings['ha_control']`:
```python
{'enabled': True,
 'proof': {kind: bool},                       # every kind present
 'people': {role: {kind: 'yes' | 'no'}},
 'places': {'panel': {kind: 'yes'|'no'|'ask'}, 'unknown_voice': {kind: ...}}}
```

`decide` order (spec "Resolving one request"): disabled refuses with message `'Home Assistant control is turned off for this household.'`; `who.admin` passes; each kind must pass; place cell `no` refuses; place `yes` passes unless `proof[kind]`; place `ask`, or `yes` on a proof kind, returns `needs='identify'` (or refuses with the "voice ID isn't on" sentence when `who.place == 'unknown_voice' and not who.voice_id`); person `no` refuses; person `yes` passes when not `proof[kind]` or `who.proven`, else `needs='pin'`. A refusal anywhere refuses the whole decision; otherwise `identify` beats `pin`.

- [ ] **Step 1: Write the failing tests** in `tests/test_control_rules.py` (unittest, `from harness import check` first like `tests/test_house_tool.py`):
  - `test_kinds`: `kind_of('light.k', {}) == 'lights'`; `switch`, `fan`, `input_boolean` → `'switches'`; `media_player`, `remote` → `'media'`; `climate`, `water_heater` → `'climate'`; `cover` with `device_class` `garage`/`door`/`gate` → `'garage'`, `cover` with `shade` or none → `'blinds'`; `lock` → `'locks'`; `alarm_control_panel` → `'alarm'`; `valve`, `vacuum`, `siren`, `button` → `'other'`; `homeassistant.x`, `notify.x`, `sensor.x` → `None`.
  - `test_defaults_switch_off`: `default_rules({})` has `enabled` True; `proof` True only for `locks`, `garage`, `alarm`; parent/adult all `'yes'`; child/helper/guest `'no'` on locks/garage/alarm, `'yes'` elsewhere; unknown_voice `'ask'` on locks/garage/alarm, `'yes'` elsewhere; panel `'yes'` on lights/switches/media/climate/blinds/other, `'no'` on garage/locks/alarm.
  - `test_defaults_switch_on`: `default_rules({'panel_allow_unsafe_controls': True})` panel: blinds `'yes'`, other `'yes'`, locks `'ask'`, garage `'ask'`, alarm `'no'`.
  - `test_stored_rules_win`: `rules({'ha_control': X})` returns X.
  - `test_validate_rejects`: an unknown kind, a person cell `'ask'`, a place cell `'maybe'` each raise `ValueError`; a valid grid round-trips.
  - `test_decide_matrix`: with defaults: parent proven + locks → allowed; parent unproven (voice-recognised) + locks → `needs == 'pin'`; parent unproven + lights → allowed; child proven + locks → refused, `needs is None`; panel + lights → allowed; panel + locks (switch on) → `needs == 'identify'`; panel + locks (switch off) → refused; unknown_voice + locks → `needs == 'identify'`; unknown_voice with `voice_id=False` + locks → refused and the message mentions the phone; admin + alarm → allowed; `enabled False` → admin refused too, with the off message (the switch means nothing anywhere operates a device).
  - `test_decide_place_yes_on_proof_kind`: rules where panel locks is `'yes'` and proof locks True → `needs == 'identify'`.
  - `test_decide_mixed`: kinds `('lights', 'locks')` for a child → refused (one refusal refuses all).

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_rules.py`
Expected: ImportError on `services.control_rules`.

- [ ] **Step 3: Implement** `services/control_rules.py` with the interfaces above. No HA calls in this task.

- [ ] **Step 4: Run, expect pass**
Run: `python tests/test_control_rules.py`
Expected: all pass.

- [ ] **Step 5: Commit** (Claude, after review)
`git add chauffeur/services/control_rules.py chauffeur/tests/test_control_rules.py`

---

### Task 2: What a request touches (entities, areas, scripts, scenes)

**Files:**
- Create: `chauffeur/services/control_scripts.py`
- Modify: `chauffeur/services/control_rules.py` (add `kinds_for` and `check`)
- Test: `chauffeur/tests/test_control_scripts.py`

**Interfaces:**
- Consumes: Task 1 `kind_of`, `decide`, `rules`, `Who`, `Decision`.
- Produces:
  - `control_scripts.touched(entity_id: str) -> tuple[set[str], list[str]]`: entity ids a `script.*`/`scene.*` reaches (recursively through called scripts and scenes, devices and areas expanded to entities), and a list of unreadable reasons (empty when fully read). Cached 300 s keyed by entity id.
  - `ha_api.get_script_config(object_id: str) -> dict | None`: REST GET `config/script/config/<object_id>` through `ha_api._request`; None when HA is absent or the script is not UI-managed (YAML scripts: rely on search/related alone).
  - `control_scripts.clear_cache() -> None` (tests and the rules page's refresh use it).
  - `control_scripts.unreadable_scripts() -> list[dict]` each `{'entity_id', 'name', 'reason'}`, for the settings page.
  - `control_rules.targets(data: dict) -> set[str]`: entity ids named by a service call's `entity_id` (str or list), `device_id`, `area_id` (expanded through `ha_api.get_entity_registry()` / `get_device_registry()` / `get_area_map()`).
  - `control_rules.kinds_for(entity_ids: Iterable[str]) -> tuple[str, ...]`: each id's kind; a script/scene contributes the kinds of what it touches, plus EVERY kind in `KINDS` when any reason is unreadable (the spec's "strictest": it must pass every kind).
  - `control_rules.check(who: Who, entity_ids: Iterable[str], settings: dict | None = None) -> Decision`: `decide(who, kinds_for(ids), rules(settings))`; never raises (any exception refuses with `'Home Assistant could not answer that request.'`).

Script reading: scene → its state's `attributes.entity_id`. Script → `ha_api.ws_command('search/related', item_type='script', item_id=<FULL entity id, e.g. 'script.goodnight'>)`, unioned with the targets read from the script's own config; an existing script whose config has device-capable actions but whose search and config yield no targets is unreadable; take `entity`, `device`, `area`, `script`, `scene` keys. Unreadable when: `ha_api.ws_command` returns None; the script config (`ha_api.ws_command('script/config', entity_id=...)`, or REST `config/script/config/<id>` when the websocket command is unavailable) contains a `{{` template in any `target`/`entity_id`/`device_id`/`area_id`, or an action whose service domain is in `('rest_command', 'shell_command', 'pyscript', 'python_script', 'hassio', 'conversation')` or is not a domain HA lists for any entity. Actions in `('delay', 'wait_template', 'wait_for_trigger', 'notify', 'tts', 'persistent_notification', 'logbook', 'system_log', 'stop', 'variables', 'condition')` are ignored. Following automations triggered by touched entities is out (spec leaves it to the builder; not doing it, and Task 6's page says so).

- [ ] **Step 1: Write the failing tests** (stub `ha_api.ws_command`, `get_states`, registries the way `tests/test_house_tool.py` stubs `ha_api`):
  - `test_scene_reads_entity_list`: scene with `entity_id: ['light.a', 'lock.front']` → `touched` = both, no reasons; `kinds_for(['scene.night'])` contains `'locks'` and `'lights'`.
  - `test_script_via_search_related`: `search/related` returns `{'entity': ['light.a'], 'device': ['dev1'], 'area': ['garage_area']}`, dev1 carries `cover.garage_door` (device_class garage), the area holds `lock.side` → touched has all three.
  - `test_script_calls_script`: script A relates to script B, B relates to `lock.front` → A's kinds include `'locks'`; a cycle A↔B terminates.
  - `test_template_target_unreadable`: config action target `{'entity_id': '{{ states(\"input_text.x\") }}'}` → reason mentions "template"; `kinds_for` includes `'alarm'`.
  - `test_rest_command_unreadable`: action `service: rest_command.open_gate` → reason names `rest_command`.
  - `test_conversation_process_unreadable`: a script whose only action is `conversation.process` → unreadable, kinds = every kind.
  - `test_unreadable_is_every_kind`: a grid where children may use Alarm but not Locks → a child running an unreadable script is refused.
  - `test_search_uses_full_entity_id`: the stubbed `ws_command` records its arguments; `item_id == 'script.goodnight'`. A stub that answers an empty result for an existing script with a `lock.unlock` action in its config still yields `'locks'` (config targets unioned).
  - `test_harmless_actions_ignored`: script with only `delay` and `notify.mobile` plus `light.turn_on` → no reasons, kinds `('lights',)`.
  - `test_no_ha`: `ws_command` returns None and `get_states` returns [] → `touched` returns `(set(), ['Home Assistant could not be read'])`, `check()` does not raise and refuses a child on that script.
  - `test_targets_area_and_list`: `targets({'area_id': 'kitchen'})` expands; `targets({'entity_id': ['light.a', 'lock.front']})` returns both; `check(child, targets(...))` refuses.
  - `test_unreadable_scripts_list`: two scripts, one with a template → list has one row with name and reason.

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_scripts.py`
Expected: ImportError on `services.control_scripts`.

- [ ] **Step 3: Implement** `control_scripts.py` and the three `control_rules` functions.

- [ ] **Step 4: Run, expect pass**, then neighbours: `python tests/test_control_rules.py`.

- [ ] **Step 5: Commit** (Claude, after review)

---

### Task 3: Who is asking, and the panel's one-use grant

**Files:**
- Modify: `chauffeur/services/control_rules.py` (who + grants + held actions)
- Modify: `chauffeur/main.py` (two routes)
- Modify: `chauffeur/services/auth.py` (rules for the routes)
- Modify: `chauffeur/services/storage.py` only if a helper is needed to read a token row's `house_session` flag (`member_tokens_table` row)
- Test: `chauffeur/tests/test_control_identity.py`

**Interfaces:**
- Consumes: Task 1 `Who`, Task 2 `check`.
- Produces:
  - `who_from_request(headers, query) -> Who`:
    - valid `x-control-grant` (consumed here: one request, one action) → that member's role, `proven=True`;
    - member token whose token row has `house_session` → `Who(place='panel', ...)`;
    - member token arriving WITH a valid device token (a person at a panel) → `Who(place='panel', ...)` (Review Focus 2: only a grant proves on a panel);
    - member token alone → member role, `proven=True` ONLY when the token row says it was minted on a personal device with a password or PIN (`proof in ('password', 'pin')` and `minted_on != 'panel'`); any other member token (minted on a panel, or `proof == 'none'`) → `place='panel'` (Codex review: a dropped device header must not upgrade a panel token);
    - device token alone → `place='panel'`;
    - admin ingress (whatever `auth.identify` returns for the admin page with no member) → `admin=True`;
    - anything else → `place='panel'` (most restrictive non-person).
  - `who_from_agent(acting_member: dict | None, voice_context, source: str | None) -> Who`:
    - `source == 'voice'`: `voice_context.level == 'verified'` → member, proven; `voice_context.recognized_this_turn and voice_context.member_id` → member, `proven=False`; else `place='unknown_voice'`, `voice_id=bool(voice_context.paired)` (a claimed name with no fingerprint is unknown_voice: spec);
    - `access.is_house(acting_member)` (panel chat, HOUSE or HOUSE_PARENT) → `place='panel'`;
    - `acting_member is None and source == 'admin'` → `admin=True`;
    - real member → role, proven.
  - Token provenance: `storage.create_member_token(member_id, house_session=False, proof='none', minted_on='personal')` records both on the row. Every existing caller passes the truth: password sign-in `proof='password'`; `/api/members/{id}/auth` `proof='pin'`, or `'none'` when the member has no PIN; `minted_on='panel'` when that request carried a valid panel device token. Legacy rows with neither field: treat as `proof='password', minted_on='personal'` (ruling: before this change only personal sign-ins were long-lived; costs a stale avatar-step token counting as proof until it expires).
  - `mint_grant(member_id: str, device_id: str) -> str`; `consume_grant(token: str, device_id: str) -> dict | None` (member row or None; single use; 60 s; bound to device).
  - `hold(tool: str, args: dict) -> str` and `take_held(held_id: str) -> dict | None` (120 s, single use).
  - Routes:
    - `POST /api/ha/control/grant` body `{member_id, pin}`; requires a valid panel device token; refuses a member with no `pin_hash` (403 `'Set a PIN to use this from the wall.'`); verifies with `storage.verify_member_pin` and the existing `_pin_rate_check`/`_pin_rate_record`; returns `{'grant': str, 'expires_in': 60}`.
    - `POST /api/ha/control/held/{held_id}` with `x-control-grant`: runs the held `house`/`music` call as the grant's member (`acting_member=<member>`, `source='panel_grant'`) and returns the tool's result dict.
  - HTTP refusal shape for every control endpoint (used by Tasks 4, 5, 7): status 403, `detail = {'message': str, 'needs': None | 'identify' | 'pin', 'kinds': [str]}`.

- [ ] **Step 1: Write the failing tests** (TestClient on `main.app`, enforcement on; panel enrolled with `storage.enrol_device_token`; see `tests/test_accounts.py:568-575` for identify):
  - `test_grant_requires_panel_and_pin`: no device token → 403; member without PIN → 403 with the "Set a PIN" sentence; wrong PIN → 403; right PIN → 200 with `grant` and `expires_in == 60`.
  - `test_grant_one_use`: `who_from_request` with the grant → proven member; the same headers again → `place == 'panel'` (Review Focus 3).
  - `test_grant_bound_to_device`: grant minted on panel-1 presented with panel-2's device token → not proven.
  - `test_grant_expires`: monkeypatch time +61 s → not proven.
  - `test_member_token_on_panel_is_panel`: avatar-style member token plus panel device token → `place == 'panel'` (Review Focus 2).
  - `test_house_session_is_panel`: token minted with `create_member_token(id, house_session=True)` → `place == 'panel'`.
  - `test_phone_member_is_proven`: member token minted by password sign-in, alone → role, proven.
  - `test_panel_token_without_header`: a token minted through `/api/members/{id}/auth` while carrying the panel device token, then presented WITHOUT the device header → `place == 'panel'`.
  - `test_pinless_token_not_proof`: a PIN-less member's `/auth` token → `place == 'panel'`.
  - `test_who_from_agent_voice`: verified ctx → proven; fingerprint-recognised ctx → unproven; named by claim (`level='named'`, `recognized_this_turn=False`) → unknown_voice; unpaired → `voice_id False`.
  - `test_held_runs_once`: `hold('house', {...lock args...})` then POST held with a parent grant → the stubbed `house.house` receives `acting_member` = that parent; a second POST → 404.

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_identity.py`

- [ ] **Step 3: Implement** the interfaces and routes; add both routes to `services/auth.py` RULES (grant: device tier; held: device tier, facet None).

- [ ] **Step 4: Run, expect pass**, then neighbours: `python tests/test_auth.py`, `python tests/test_accounts.py`, `python tests/test_control_rules.py`.

- [ ] **Step 5: Commit** (Claude, after review)

---

### Task 4: Every HTTP control endpoint obeys

**Files:**
- Modify: `chauffeur/main.py`: the Sendspin websocket (`/api/sendspin/ws`, ~14460-14530: authorize client command frames as `media` per frame against current rules; stream and read traffic untouched), `ha_toggle` (`/api/ha/toggle`, ~1742), `/api/ha/card/climate` (~11383), `ha_card_service` (`/api/ha/card/service`, ~11432), `/api/ha/media_players/{entity_id}/command` (~12047), `/api/music/queue/command` (~12137), `/api/music/play` (~12284). Each gains `request: Request`.
- Modify: `chauffeur/services/home_board.py:3273-3306` (retire `HA_TOGGLE_DOMAINS`/`HA_UNSAFE_DOMAINS`/`toggle_domains` as the gate; the tile's `toggleable` at ~3559 asks the rulebook), `chauffeur/services/ha_card_convert.py:90-99, 256` (same).
- Modify: `chauffeur/tests/test_board_ha_tiles.py` (assertions at ~151, ~166, ~341 that pin the old allowlist are rewritten to the grid; the spec supersedes them).
- Test: `chauffeur/tests/test_control_endpoints.py`

**Interfaces:**
- Consumes: Task 3 `who_from_request` and the refusal shape; Task 2 `check`, `targets`; Task 1 `NEVER_DOMAINS`.
- Produces: `control_rules.check` also applies the effective member's scope (`media` needs the `music` facet; reuse the scope helper the auth middleware uses, for `who.member_id`), so grants, held actions and the facet-less card route are covered; `control_rules.guard(request, entity_ids) -> None` raising `HTTPException(403, detail=...)` per Task 3's shape; `control_rules.offered(who: Who, entity_id: str) -> bool` (true when `check` is allowed or `needs` is set) for tiles.

`ha_card_service`: refuse `NEVER_DOMAINS` first (400, unchanged wording style), keep the climate clamping, then `guard(request, control_rules.call_targets(domain, service, data))`. `call_targets(domain: str, service: str, data: dict) -> set[str]` = `targets(data)`, plus `script.<service>` when `domain == 'script'` and the service is not `turn_on`/`turn_off`/`toggle` (a named script call's payload is its variables, not its target; Codex review). A service call that names no target at all is refused (400 `'Name the device this card controls.'`). Music `/api/music/play` and queue command guard the target player as `media`.

Tiles: `toggleable` = `offered(who_from_request(...), entity_id)` where the board endpoint has the request; where it does not, the panel `Who`. The browser's own switch stays cosmetic; the server decides.

- [ ] **Step 1: Write the failing tests** (TestClient; stub `ha_api.call_service` to record calls and `ha_api.get_states` for kinds):
  - `test_toggle_panel_lock_switch_off`: panel token, `lock.front` → 403, `needs is None`, no service call.
  - `test_toggle_panel_lock_switch_on`: settings `panel_allow_unsafe_controls: True`, no `ha_control` → 403, `needs == 'identify'`; then with a parent grant → 200 and one call.
  - `test_toggle_phone_child_lock`: child member token on `lock.front`, switch on → 403 (approved migration change 3).
  - `test_toggle_phone_parent_lock`: parent member token, switch off → 200 (widening).
  - `test_card_service_list_with_lock`: panel, `{'entity_id': ['light.a', 'lock.front']}` → 403 (Review Focus 1); `{'area_id': 'kitchen'}` where kitchen holds a lock → 403.
  - `test_named_script_forged_payload`: child token posts `domain='script', service='open_garage', data={'entity_id': 'light.a'}` where `script.open_garage` touches `cover.garage_door` → 403.
  - `test_sendspin_command_frames`: over a TestClient websocket to `/api/sendspin/ws` with the MA upstream stubbed, a playback/volume command frame from a requester whose media cell is `'no'` (or with control switched off) is dropped, not forwarded; stream/read frames still pass; changing the rules mid-connection takes effect on the next frame.
  - `test_media_scope_every_lane`: one guest with music scope none and grid media `'yes'` is refused on `/api/ha/card/service` (media_player), `/api/ha/media_players/.../command`, `/api/music/play`, and via a panel grant.
  - `test_card_service_never_domains`: `homeassistant.restart`, `hassio.addon_stop`, `automation.turn_off` → 400 for a parent token too.
  - `test_card_service_no_target`: `light.turn_on` with no target → 400.
  - `test_climate_and_media_guarded`: child token with `climate` set to `'no'` in a stored grid → `/api/ha/card/climate` 403; panel with media `'no'` → `/api/ha/media_players/media_player.k/command` 403.
  - `test_disabled_switch`: `ha_control.enabled False` → parent token on a light → 403 with the off message.
  - `test_no_ha`: `ha_api.mode()` unconfigured → existing 503/"not reachable" behaviour unchanged, no exception.
  - `test_scope_still_applies`: a guest whose scope lacks the `music` facet, with the grid's guest media `'yes'` → `/api/music/play` still refused (grid AND scope: spec).
  - `test_tile_toggleable`: board payload for a panel shows `toggleable` true for a light, false for a lock with switch off, true (askable) with switch on.

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_endpoints.py`

- [ ] **Step 3: Implement** `guard`, `offered`, and wire the six endpoints and the two `toggleable` sites.

- [ ] **Step 4: Run, expect pass**, then neighbours: `python tests/test_board_ha_tiles.py`, `python tests/test_control_identity.py`, `python tests/test_auth.py`.

- [ ] **Step 5: Commit** (Claude, after review)

---

### Task 5: Argyle obeys (house tool, TV apps, music tool, voice)

**Files:**
- Modify: `chauffeur/services/house.py:892-962` (`_trusted` STAYS for the private child-location read at ~528, unchanged; only its device-control use at ~962 is replaced: `house()` act and `open_app` call `control_rules.check(who_from_agent(...), ids)`) and `chauffeur/services/voice_tools.py` (its `house` dispatch path must reach the same check)
- Modify: `chauffeur/services/music_tool.py:165-250` (play/pause/volume guard the resolved player as `media`)
- Modify: `chauffeur/services/agent_tools_v2.py:1383-1400, 9660-9665` (thread `voice_context` and `source` into both tools if the handler drops them today; confirm against the router's dispatch)
- Modify: `chauffeur/services/agent_router.py` (a tool result carrying `control_held` is surfaced on the router's return dict under `control_held`)
- Modify: `chauffeur/main.py` `/api/chat` (~20177-20308): pass `control_held` through to the JSON reply
- Modify: `chauffeur/tests/test_house_tool.py` (trust assertions that pin "wall panel NEVER trusted" are rewritten to the grid defaults; spec supersedes)
- Test: `chauffeur/tests/test_control_argyle.py`

**Interfaces:**
- Consumes: Task 3 `who_from_agent`, `hold`; Task 2 `check`.
- Produces: tool refusal dicts `{'status': 'refused', 'message': str, 'needs': 'identify' | 'pin' | None}`; on a panel `needs == 'identify'` the dict also carries `control_held: {'id': str, 'message': "Who's asking?"}` from `hold('house' | 'music', args)`. `/api/chat` reply gains `control_held` (absent when none).

Voice messages: `needs == 'pin'` → `'Say your PIN first, then ask again.'`; unknown voice `needs == 'identify'` → `'Who is this? Say your name and PIN, then ask again.'`. No held action for voice (the person re-asks).

Scripts through Argyle: `house` act on `script.*`/`scene.*` checks `kinds_for` like any entity.

- [ ] **Step 1: Write the failing tests** (pattern of `tests/test_house_tool.py`: stubbed `ha_api`, real `services.house`, real tool entry point):
  - `test_private_location_unchanged`: the existing private child-location assertions in `tests/test_house_tool.py` (~884-903) pass untouched.
  - `test_panel_chat_blinds_kept`: `acting_member=access.HOUSE`, switch off, `cover.office_shade` (shade) and `valve.sprinkler` → allowed (migration keeps them).
  - `test_panel_chat_lock_defaults`: `acting_member=access.HOUSE` unlocking `lock.front`, switch off → refused, `needs is None`; switch on → refused with `needs == 'identify'` and a `control_held` id.
  - `test_held_unlock_runs_as_parent`: POST `/api/ha/control/held/{id}` with a parent grant → `lock.unlock` called once.
  - `test_voice_recognised_parent`: ctx `level='named'`, `recognized_this_turn=True`, parent → light allowed; lock refused with `needs == 'pin'` and the PIN sentence.
  - `test_voice_verified_parent_lock`: `level='verified'` → unlock called.
  - `test_voice_inherited_yes_cannot_unlock` (Review Focus 5): ctx recognised by inheritance (`recognized_this_turn=True`, `level='named'`) → lock still `needs == 'pin'`.
  - `test_voice_claimed_name`: `level='named'`, `recognized_this_turn=False` → treated as unknown voice (`needs == 'identify'` on lock; light allowed by default).
  - `test_child_signed_in`: child member on lock → refused; on light → allowed.
  - `test_script_goodnight`: child runs `script.goodnight` that touches `lock.front` → refused; parent signed in → `script.turn_on` called.
  - `test_music_tool_guard`: stored grid child media `'no'` → music play refused; parent → plays.
  - `test_open_app_guard`: panel with media `'no'` → `open_app` refused.
  - `test_chat_reply_carries_held`: `/api/chat` from a panel (context search `?panel=true`) with the router stubbed to return a tool result with `control_held` → JSON has `control_held.id`.

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_argyle.py`

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run, expect pass**, then neighbours: `python tests/test_house_tool.py`, `python tests/test_voice_conversation_mode.py`, `python tests/test_voice_my_drives.py`, `python tests/test_control_identity.py`.

- [ ] **Step 5: Commit** (Claude, after review)

---

### Task 6: The rules page, its API, and the two warnings

**Files:**
- Create: `chauffeur/templates/components/control_rules.html` (included in the Config › People drawer beside the Argyle settings, `templates/config.html` ~1165-1185)
- Modify: `chauffeur/templates/config.html` (one include line; remove nothing else)
- Modify: `chauffeur/services/settings_registry.py` (new `_e('ha_control', 'integrations', 'Who can control what', ..., page='config', anchor='people')`; the `panel_allow_unsafe_controls` entry at ~148 is retired: removed from the Boards drawer UI and the registry, still read by `default_rules` for migration)
- Modify: the Boards drawer template that renders `panel_allow_unsafe_controls` (find with `grep -rn panel_allow_unsafe_controls templates`) to drop that checkbox
- Modify: `chauffeur/main.py` (two routes) and `chauffeur/services/auth.py` (their rules, parent tier)
- Modify: `chauffeur/services/control_rules.py` (`local_handling_warning`)
- Test: `chauffeur/tests/test_control_rules_page.py`

**Interfaces:**
- Consumes: Task 1 `rules`, `validate_rules`, `KINDS`; Task 2 `unreadable_scripts`.
- Produces:
  - `GET /api/ha/control/rules` (parent) → `{'rules': dict, 'kinds': [{'id','label'}], 'warnings': {'unreadable_scripts': [...], 'local_handling': dict | None}}`
  - `POST /api/ha/control/rules` (parent) body = rules dict → validated, saved to `settings['ha_control']`, returns the saved rules; 400 with the `ValueError` sentence on a bad grid.
  - `control_rules.local_handling_warning(rules: dict) -> dict | None`: reads `ha_api.ws_command('assist_pipeline/pipeline/list')`; when any pipeline has `prefer_local_intents` true, returns `{'pipelines': [names], 'devices': [{'entity_id','name','kind'}]}` for entities exposed to Assist (`ha_api.get_exposed()`) whose kind is restricted (proof checked, or any role `'no'`, or any place not `'yes'`); None when no HA, no such pipeline, or nothing restricted.

Kind labels (copy): Lights; Switches & fans; TV & music; Climate; Blinds & shades; Garage, doors & gates; Locks; Alarm; Everything else.

Layout B (spec "Settings placement"; mockup chosen in brainstorm): the household switch "Chauffeur can control Home Assistant devices" with "Off: nothing anywhere operates a device. Reading still works."; then a "Needs proof of who you are" card with one checkbox per kind; then one card per role (Yes/No segmented per kind), then Wall panel and Unknown voice cards (Yes / Ask who / No). A place cell set to Yes on a proof kind renders "Ask who (needs proof)". Unknown voice card note: "Ask who needs voice ID turned on for the speaker." Helper and guest cards note: "Each person's own access can narrow this further." Then the warnings: unreadable scripts by name with reason, plus "Scripts that start other automations are judged only by what they touch directly."; and the local handling warning naming pipelines and devices. Saves on change (like `saveAuthSettings()` in config.html), errors through `showGlobalAlert`. Follow `docs/ui_design_guide.md` and reuse the drawer's existing segmented/checkbox builders; screenshot proof at phone and desktop width.

- [ ] **Step 1: Write the failing tests:**
  - `test_rules_api_parent_only`: child token GET → 403; parent GET → 200 with defaults and nine kinds.
  - `test_rules_api_round_trip`: POST a changed grid → GET returns it; `check()` now follows it.
  - `test_rules_api_rejects_bad_grid`: person cell `'ask'` → 400 with a sentence.
  - `test_local_handling_warning`: stub pipeline list with `prefer_local_intents: True` and an exposed `lock.front` → warning names the pipeline and the lock; with `False` → None; with HA unconfigured → None and the GET still 200 (Review Focus 4).
  - `test_unreadable_scripts_in_payload`: one templated script → listed in `warnings.unreadable_scripts`.
  - `test_page_renders`: GET the config page as a parent → the component's root marker is present; node run of the component's Alpine data factory (pattern of an existing `tests/test_*_js.py`) with a stubbed fetch: toggling a person cell posts the full grid; a panel Yes on a proof kind reads "Ask who (needs proof)".
  - `test_old_switch_gone_from_boards_drawer`: the Boards drawer no longer renders `panel_allow_unsafe_controls`; `default_rules` still reads it.

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_rules_page.py`

- [ ] **Step 3: Implement**, then `python tools/build_tailwind.py`.

- [ ] **Step 4: Run, expect pass**, then neighbours: `python tests/test_settings_registry.py` (if present; else the registry's own test found by `grep -ln settings_registry tests`), `python tests/test_auth.py`, `python tests/test_board_ha_tiles.py`.

- [ ] **Step 5: Commit** (Claude, after review)

---

### Task 7: "Ask who" on the wall panel

**Files:**
- Modify: `chauffeur/templates/components/control_center.html` (beside `chfMemberToken`, ~1545-1600: new `window.chfControlGrant`; chat send ~976-1000 handles `control_held`)
- Modify: the tile tap handler that POSTs `api/ha/toggle` and the hosted card bridge that POSTs `api/ha/card/service` / `api/ha/card/climate` (find with `grep -rn "api/ha/toggle\|api/ha/card/service\|api/ha/card/climate" templates static`), and the music card's command posts
- Test: `chauffeur/tests/test_control_grant_js.py`

**Interfaces:**
- Consumes: Task 3 grant route and refusal shape; Task 5 `control_held`.
- Produces:
  - `window.chfControlGrant() -> Promise<string | null>`: `promptChoice("Who's asking?", '', members)` listing active members (from `api/members`) with PIN-less members shown but answering "Set a PIN to use this from the wall." through `showGlobalAlert` when picked; then `promptInput('Hi <name>!', 'Enter your PIN', {type: 'password'})`; POST `base + 'api/ha/control/grant'`; 403 → "Wrong PIN" and ask again; 429 → "Too many tries — wait a moment" and stop; returns the grant or null. Never stores it.
  - `window.chfControlFetch(url, opts) -> Promise<Response>`: performs the request; on 403 with `detail.needs === 'identify'` runs `chfControlGrant()` and retries once with header `x-control-grant`; on any other refusal shows `detail.message` via `showGlobalAlert`. Tile, hosted card bridge and music card posts go through it.
  - Chat: when the reply has `control_held`, the bubble shows a "Who's asking?" button; tapping it runs `chfControlGrant()` then POSTs `base + 'api/ha/control/held/' + id` with the grant and shows the returned `message`.

- [ ] **Step 1: Write the failing tests** (node run of the extracted functions with stubbed `fetch`, `promptChoice`, `promptInput`, `showGlobalAlert`):
  - `test_grant_happy`: pick parent, PIN right → returns grant; the PIN request went to `api/ha/control/grant` relative to `chfBase` (not root-relative).
  - `test_grant_wrong_then_right`: first 403 → "Wrong PIN" alert, second → grant.
  - `test_grant_pinless_member`: picking a member with `has_pin: false` alerts the "Set a PIN" sentence and returns null without a POST.
  - `test_control_fetch_retries_once`: first response 403 `needs: 'identify'` → grant obtained → second request carries `x-control-grant`; a second 403 is shown, not retried again.
  - `test_control_fetch_plain_refusal`: 403 `needs: null` → alert with the message, no grant prompt.
  - `test_chat_held_button`: a chat reply with `control_held` renders the button; tapping posts to `api/ha/control/held/<id>` with the grant header.
  - `test_no_browser_dialogs`: the new code never calls `alert`, `confirm` or `prompt` (stubs throw).

- [ ] **Step 2: Run, expect failure**
Run: `python tests/test_control_grant_js.py`

- [ ] **Step 3: Implement**, then `python tools/build_tailwind.py` if any class changed.

- [ ] **Step 4: Run, expect pass**, then neighbours: `python tests/test_control_endpoints.py`, `python tests/test_control_argyle.py`, and the existing avatar/pets PIN JS test if one exists (`grep -ln chfMemberToken tests`).

- [ ] **Step 5: Ship** (Claude): update `chauffeur/system_capabilities.md` (new top entry: what shipped, the three approved behaviour changes, device steps), update the memory arc `ha-control-permissions-arc.md` to SHIPPED, bump `chauffeur/config.yaml`, commit, push.

Device steps for the user (go in the capabilities entry): rebuild the add-on; open Config › People › Who can control what and confirm the grid matches the house; on the panel tap a lock tile (expect "Who's asking?" if the board switch was on, else a refusal); say "unlock the front door" to a satellite as a recognised parent (expect the PIN ask); run a script that locks a door as a child on a phone (expect refusal); read the local-handling warning and decide in HA.
