# Recognised voices act, and panel tap-to-talk: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A voice Argyle recognises acts as that person with their phone chat powers; a goodbye ends the session; a wall panel with a room gets a mic button that starts a conversation on that room's satellite.

**Architecture:** Piece 1 (Tasks 1-3) changes the satellite path only: `voice_conversation` draws conversation boundaries, `VoiceContext.actor()` names who acts, the router runs an actor's turn on the family tool rail, and a held-answer dialog keeps private answers off the speaker unless the actor says so. Piece 2 (Tasks 4-6) adds `area_id`/`satellite_id` to a panel's trusted-device row, resolves the room's satellite, and calls `assist_satellite.start_conversation` from a panel-only endpoint behind a mic button.

**Tech Stack:** FastAPI (`chauffeur/main.py`), services under `chauffeur/services/`, Jinja + vendored Alpine templates, precompiled Tailwind, plain-script tests run from `chauffeur/` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-10-voice-acts-and-panel-talk-design.md`

**Who does what (standing rule):** Claude writes each task's test file first, Codex implements against it (`codex:codex-rescue`, inside this worktree `E:\repositories\Chauffeur-voice-tap`), a Claude reviewer reviews each task, Claude gates, documents and lands. Codex never reviews Codex work. Task 5 is Claude's alone (a live HA call, user go-ahead first).

## Global Constraints

- A claimed name never acts. Only `level == 'verified'` or a fingerprint recognised on this turn makes an actor.
- A fingerprint is never proof: `proven` stays `ctx.level == 'verified'` on every satellite turn.
- An unrecognised satellite turn behaves exactly as today (same tools, `voice_tools.dispatch`, `parent_of_record`, "Household voice:" messages).
- The phone path (`services/app_voice.py`) keeps its behaviour; shared helpers may move but phone results must not change (its tests stay green unmodified).
- Every HA touchpoint degrades gracefully with no HA present; no browser dialogs; run `python tools/build_tailwind.py` after template class changes; new routes need an `services/auth.py` rule (`/api/panel/*` is already WALL, `/api/account/devices/*` already PARENTS).
- Do not touch schedule rebuild behaviour.
- Do not bump `chauffeur/config.yaml` on the branch.

## Review Focus

1. A recognised child at a satellite asks for something only parents may do: refused exactly as on the child's phone, never run as `parent_of_record`. (Task 2 test `test_child_actor_gets_child_rail`.)
2. Two people at the satellite: Dad is recognised, then a kid says a short "yes" after Dad said goodbye or after 30 s: the kid is not Dad. (Task 1 tests.)
3. A private answer is held and the next turn is someone else's long, matched voice: the answer goes to Dad's chat, never spoken, and the new turn is answered normally. (Task 3 `test_other_voice_sends_to_chat`.)
4. A tool added to the registry later without a speech classification: treated as private at runtime and the classification test fails. (Task 3 `test_every_registry_tool_is_classified`.)
5. Panel talk with HA absent, with a panel that has no room, and from a non-panel caller: no button, a clear refusal, no exception. (Task 6 tests.)

---

### Task 1: Conversation boundaries; goodbye ends the session

**Files:**
- Modify: `chauffeur/services/voice_conversation.py`, `chauffeur/services/voice_fingerprint.py` (`apply`), `chauffeur/services/voice_identity.py`, `chauffeur/main.py` (`converse_ha_assist`)
- Test: `chauffeur/tests/test_voice_session_end.py` (new; Claude writes it first)

**Interfaces:**
- Produces: `voice_conversation.in_conversation(ctx) -> bool`: True when this satellite's previous turn left the mic open (`continue_conversation` returned True) less than `GAP_SECONDS` ago. Read-only; does not prune or count.
- Produces: `voice_identity.end_session(ha_instance_id, satellite_id) -> None`: replaces the satellite's session with `_new_session(device_id)` (level unknown, new generation), keeping `recognition_suppressed` false. No-op when there is no session.
- Changes: in `voice_fingerprint.apply`, the short/absent-sample inheritance term `(not usable and row.get('recognized') and row.get('member_id'))` also requires `voice_conversation.in_conversation(ctx)`. Nothing else in `apply` changes.
- Changes: in `converse_ha_assist`, after the model answer, when `voice_conversation.is_sign_off(req.text)` is true, call `voice_identity.end_session(...)` (after `continue_conversation` has been computed, so the answer and greeting are unchanged).

- [ ] **Step 1: Claude writes the failing tests** (pattern: `tests/test_voice_conversation_mode.py`, real endpoint, stubbed model):
  - `test_short_reply_inherits_inside_conversation`: recognised long turn, then a 0.4 s "yes" with the mic still open: `recognized_this_turn` true; the stub router sees `voice_context.actor()` (Task 2 name; until Task 2 assert `recognized_this_turn`).
  - `test_short_first_turn_of_new_conversation_not_inherited`: recognised turn, mic closes by sign-off; next 0.4 s turn: `recognized_this_turn` false.
  - `test_gap_ends_conversation`: recognised turn, clock advanced `GAP_SECONDS + 1`; next short turn: not recognised.
  - `test_cap_close_ends_conversation`: two unrecognised turns close the mic; a short turn after: not recognised.
  - `test_sign_off_ends_session`: recognised Dad says "thanks, that's all": reply still spoken, `continue_conversation` false, and `voice_identity._sessions[key]['level'] == 'unknown'` with a new generation.
  - `test_sign_off_ends_verified_session`: PIN-verified session, "goodbye": level back to unknown.
  - `test_long_new_conversation_still_fingerprints`: after a sign-off, a long matching sample names the speaker again ("Hi Jeff.").
  - `test_pin_flow_unchanged`: a "my PIN is …" dialog still verifies (regression).
- [ ] **Step 2:** Run `python tests/test_voice_session_end.py`; expect failures on the new behaviour.
- [ ] **Step 3 (Codex):** Implement the interfaces above.
- [ ] **Step 4:** Run `python tests/test_voice_session_end.py tests/test_voice_conversation_mode.py tests/test_voice_fingerprint.py tests/test_voice_identity.py tests/test_control_argyle.py`; all pass. If an existing test encodes cross-conversation inheritance, report it rather than editing it; Claude rules.
- [ ] **Step 5:** Commit `feat(voice): goodbye ends the speaker; short replies inherit only inside one conversation`.

### Task 2: A recognised voice acts as that person

**Files:**
- Modify: `chauffeur/services/voice_identity.py` (`VoiceContext`), `chauffeur/services/agent_router.py`, `chauffeur/services/voice_tools.py`, `chauffeur/services/argyle_memory.py`, `chauffeur/services/agent_tools_v2.py` (`act_on_situation` approve_plan/run_stage gate; `start_project` requester)
- Test: `chauffeur/tests/test_voice_actor.py` (new; Claude writes it first)

**Interfaces:**
- Consumes: Task 1's `in_conversation` (through `recognized_this_turn`).
- Produces: `VoiceContext.actor() -> dict | None`: `verified_member()` if verified; else `member()` when `level == 'named'`, the session row has `recognized` true, `recognized_this_turn` is true, and `scope.can_see(member, 'chat.agent')`; else None.
- Changes: `VoiceContext.provenance()` returns `actor_kind='member'`, `actor_member_id`, plus `via='voice'` when `actor()` is set; unchanged otherwise.
- Router, `source == 'voice'` with `actor = voice_context.actor()`:
  - `acting_member = actor`; `proven` unchanged (caller passes `ctx.level == 'verified'`).
  - Tools: the same list the family source would build for that member (the existing `bridge_ok` / role logic, not a copy), plus every name in `voice_tools.MUTATIONS` and `prepare_voice_approval`. No `voice_tools.TOOLS` filter.
  - Prompt: the family role prompt for that member, then the SHARED SPEAKER block reworded: "Recognised by voice as {name}; acting as themselves; not proven. Do assign/clear drivers and shopping changes directly with the tools; never as a propose_family_action card."
  - Dispatch: names in `voice_tools.MUTATIONS` and the two message tools go through `voice_tools.dispatch`, which now uses `ctx.actor()` as principal and sender when set (no "Household voice:" prefix, provenance from `ctx.provenance()`). `prepare_voice_approval` unchanged. Every other tool goes through the ordinary family dispatch branch with `spoken=True` and `voice_context` passed where accepted.
  - A result carrying a `card` on an actor turn: post reply + card into `storage.get_or_create_dm(actor['id'], 'argyle')` with `_post_chat_message`, and the spoken message becomes the model reply plus "I've put that in your Argyle chat."
- Gates moved from `verified_member()` to `actor()`: argyle_memory teaching (`_trusted` caller passes the actor), `act_on_situation` approve_plan/run_stage (actor must equal the situation actor), `start_project` requester. `voice_approval.prepare` still demands a PIN.
- Unrecognised turns (`actor()` None): byte-for-byte today's path.

- [ ] **Step 1: Claude writes the failing tests** (stub the model to call a named tool; real router):
  - `test_actor_none_for_claimed_name`, `test_actor_none_for_uncertain_long_sample`, `test_actor_for_recognised`, `test_actor_for_verified`, `test_actor_none_without_chat_agent_scope`.
  - `test_recognised_adult_gets_family_tools`: the tool list offered to the model contains `add_household_task` and `cancel_event` (not in `voice_tools.TOOLS`) and all of `voice_tools.MUTATIONS`.
  - `test_unknown_voice_tools_unchanged`: unknown voice offered exactly `voice_tools.TOOLS` ∩ registry + approval schema (today's list).
  - `test_child_actor_gets_child_rail`: recognised child offered the child's family tool set; a bridge tool call is refused as on the phone; `parent_of_record` never used.
  - `test_actor_mutation_runs_as_actor`: recognised adult "Jeff drives Ben": `assign_driver_to_event_fuzzy` runs with principal Jeff, provenance `actor_kind='member'`, `via='voice'`.
  - `test_actor_message_from_member`: `send_family_message` posts from Jeff, body has no "Household voice:" prefix.
  - `test_unknown_message_still_household`: unknown voice message still "Household voice: …" from Argyle.
  - `test_actor_family_tool_runs`: recognised adult `add_household_task` creates the task as Jeff.
  - `test_actor_teaches_memory`: recognised parent's `memory` remember succeeds (was "Only a parent or adult…").
  - `test_actor_card_goes_to_dm`: a tool result with a `card` lands in Jeff's Argyle DM with the card; spoken reply ends "I've put that in your Argyle chat."
  - `test_recognised_not_proven`: recognised parent unlocking a lock whose kind requires authentication still gets "Say your PIN first" (HA rulebook unchanged).
  - `test_booking_approval_still_pin`: `prepare_voice_approval` for a recognised parent still returns the PIN challenge.
- [ ] **Step 2:** Run `python tests/test_voice_actor.py`; expect failures.
- [ ] **Step 3 (Codex):** Implement.
- [ ] **Step 4:** Run `python tests/test_voice_actor.py tests/test_voice_session_end.py tests/test_voice_identity.py tests/test_voice_my_drives.py tests/test_control_argyle.py tests/test_house_tool.py tests/test_app_voice.py` (app_voice has 3 known pre-existing errors in `_call_llm_json`; no new ones).
- [ ] **Step 5:** Commit `feat(voice): a recognised voice acts as that person with their phone powers`.

### Task 3: Private answers: Argyle asks before reading aloud

**Files:**
- Modify: `chauffeur/services/voice_tools.py`, `chauffeur/services/app_voice.py` (move per-row checks into shared helpers only), `chauffeur/services/agent_router.py` (hook), `chauffeur/services/voice_identity.py` (held answer on the session), `chauffeur/main.py` (`converse_ha_assist`)
- Create: `chauffeur/services/voice_private.py`
- Test: `chauffeur/tests/test_voice_private_answers.py` (new; Claude writes it first)

**Interfaces:**
- Produces in `voice_tools`: `SPEAKABLE` and `PRIVATE` frozensets of tool names that together cover every name from `agent_tools_v2.get_available_tools()` and `get_admin_tools()`, plus `house`, `music`, `memory`, `report_gap`, `prepare_voice_approval`. Rule for filling them: a write whose spoken confirmation only repeats what the speaker asked is SPEAKABLE; a read is SPEAKABLE only if it is in `voice_tools.TOOLS` today; `read_mail`, `search_mail`, `get_family_messages`, `list_threads`, `find_in_chauffeur`, `get_requests`, `research_question`, `start_mission_for`, `launch_mission` and every other read are PRIVATE. Unknown names count as PRIVATE at runtime.
- Produces in `voice_tools`: `row_checks_before(name, args, member) -> bool` and `row_checks_after(name, result) -> bool`: the per-row checks now inside `PhoneTurn.before_tool`/`tool_result` (driver events via `speech_safe`, shopping list audience/private/sensitive, calendar events via `speech_safe` on the cached schedule), moved verbatim. `PhoneTurn` calls them; its own `TOOLS` whitelist rule stays as is.
- Produces `voice_private.SatelliteTurn` (contextvar, like `app_voice.current`): `before_tool(name, args)`, `tool_result(result)`, `safe -> bool`. Unsafe when a PRIVATE tool ran or a row check failed. The router calls it at the same two points it calls `phone_turn`, only on actor turns.
- Produces `voice_private.hold(ctx, actor, reply, card) -> str` (stores `{'member_id', 'reply', 'card', 'expires'}` on the satellite session row under `held_answer`, starts a 60 s `threading.Timer` that posts to the DM if still held; returns the question "That's private. Read it out, or send it to your chat?"), `voice_private.intercept(text, ctx) -> dict | None` (runs in `converse_ha_assist` right after `voice_approval.intercept`), `voice_private.release(ctx, reason)` (posts held reply + card to `get_or_create_dm(member_id, 'argyle')`, clears it).
- `intercept` rules:
  - No held answer: None.
  - Same actor (`ctx.actor()` id == held member id): words "read", "out loud", "aloud", "tell me", "yes", "go ahead" return `{'message': held reply}`; "send", "chat", "phone", "no", "later" release and return `{'message': 'Sent to your chat.'}`; anything else once returns the question again (`continue` true), a second unclear reply releases and lets the turn continue to the model.
  - Different or no actor: release, return None (the turn is answered normally).
  - Sign-off: release, then the normal sign-off path (Task 1) runs.
- In `converse_ha_assist`, on an actor turn with `SatelliteTurn.safe` false, the speech becomes `hold(...)` and `continue_conversation` is true. `end_session` (Task 1) releases any held answer first.

- [ ] **Step 1: Claude writes the failing tests:**
  - `test_every_registry_tool_is_classified`: every registry name is in exactly one of SPEAKABLE / PRIVATE.
  - `test_unknown_tool_is_private`.
  - `test_write_confirmation_spoken`: recognised adult `add_household_task`: answer spoken, nothing held.
  - `test_private_read_asks`: recognised adult `read_mail`: speech is the question, `continue_conversation` true, the reply text absent from speech.
  - `test_same_actor_read_it`: then a 0.4 s "read it" from the same recognised session: speech is the held reply.
  - `test_same_actor_send_it`: "send it to my chat": DM gets the reply (and card), speech "Sent to your chat."
  - `test_unclear_reasks_once`, `test_second_unclear_releases`.
  - `test_other_voice_sends_to_chat`: a long sample matching Mum after Jeff's hold: Jeff's DM gets it; Mum's turn reaches the model.
  - `test_unknown_voice_sends_to_chat`, `test_sign_off_sends_to_chat`, `test_timer_sends_to_chat` (call the timer function directly).
  - `test_calendar_private_event_asks`: `get_calendar_events` returning a non-speech-safe event: held.
  - `test_unknown_voice_never_held`: unrecognised turn's answer never held (today's behaviour).
  - `test_phone_unchanged`: `tests/test_app_voice.py` scenarios for driver/shopping/calendar safety give the same `speech_safe` as before (run the file in Step 4).
- [ ] **Step 2:** Run it; expect failures.
- [ ] **Step 3 (Codex):** Implement.
- [ ] **Step 4:** Run `python tests/test_voice_private_answers.py tests/test_voice_actor.py tests/test_voice_session_end.py tests/test_app_voice.py tests/test_voice_conversation_mode.py tests/test_voice_identity.py`.
- [ ] **Step 5:** Commit `feat(voice): private answers wait for the speaker to say read it or send it`.

**Landing point A:** Tasks 1-3 land on main (merge main in, gate, bump, capabilities entry, ff-only, push). The worktree continues for Tasks 4-6.

### Task 4: A panel's room and satellite

**Files:**
- Modify: `chauffeur/services/storage.py` (trusted_devices), `chauffeur/main.py` (`GET /api/account/devices` returns the fields; new `POST /api/account/devices/{device_id}/room`), `chauffeur/templates/config.html` (Trusted devices rows, ~line 1054 and the Alpine block ~4320)
- Create: `chauffeur/services/panel_talk.py`
- Test: `chauffeur/tests/test_panel_room.py` (new; Claude writes it first)

**Interfaces:**
- Produces: `storage.set_device_room(device_id, area_id: str | None, satellite_id: str | None) -> dict | None` (panel rows only; returns the row; None for unknown or non-panel).
- Produces: `POST /api/account/devices/{device_id}/room` body `{area_id, satellite_id}`: 404 unknown, 400 non-panel or a `satellite_id` not starting `assist_satellite.`; returns the row.
- Produces: `panel_talk.satellite_for_panel(device: dict) -> str | None`: `satellite_id` override if it is still a known satellite (`voice_identity` config rows or HA states); else `settings.announce_targets[area_id]` if it starts `assist_satellite.`; else the first `assist_satellite.*` in the area, sorted (reuse the area lookup `announce.pick_target` uses); None when HA is absent or nothing fits. Never raises.
- Produces: `panel_talk.rooms() -> {'areas': [{id, name}], 'satellites': [{id, name, area_id}]}` for the pickers; empty lists with HA absent.
- UI: each panel row in Config › Trusted devices gets a Room select (blank = none) and a Satellite select (Automatic + known satellites). With HA absent the row says "Home Assistant is not connected" in place of the selects. Non-panel rows unchanged.

- [ ] **Step 1: Claude writes the failing tests:** `test_set_room_panel_only`, `test_route_parent_only` (TestClient: non-parent 401/403), `test_route_validates_satellite`, `test_list_returns_room_fields`, `test_satellite_override_wins`, `test_stale_override_falls_back`, `test_announce_pin_satellite_used`, `test_announce_pin_media_player_ignored`, `test_first_area_satellite`, `test_no_ha_none`, `test_config_rows_render_selects` (render config.html, assert the Room/Satellite controls exist only on panel rows).
- [ ] **Step 2:** Run; expect failures. **Step 3 (Codex):** implement; rebuild Tailwind. **Step 4:** Run `python tests/test_panel_room.py tests/test_auth_routes.py` (or the auth classification test that flags unruled routes) plus the trusted-devices tests (`grep -l trusted_devices tests/*.py`). **Step 5:** Commit `feat(panel): a panel belongs to a room and finds its satellite`.

### Task 5: Spike: `assist_satellite.start_conversation` on a real satellite (Claude, user go-ahead first)

- [ ] Ask the user before the call (it makes a speaker chime). Then call it once via `ha_api.call_service('assist_satellite', 'start_conversation', {'entity_id': <office satellite>, 'preannounce': True})` from a scratch script, with HA reached the way the dev shell's `HA_BASE_URL` allows.
- [ ] Record in the ledger: did HA accept an absent `start_message`; did the satellite chime and listen; did the spoken turn reach `/api/v2/converse` with satellite metadata (Config › Voice identity "last" row, or the add-on log); did conversation mode keep listening after the answer.
- [ ] Rule: payload = `{'entity_id', 'preannounce': True}` if it worked, else add `'start_message': 'Yes?'`. Firmware trouble goes to the user. Write the ruling into Task 6's brief.

### Task 6: The mic button

**Files:**
- Modify: `chauffeur/services/panel_talk.py`, `chauffeur/main.py` (`GET`/`POST /api/panel/talk`), `chauffeur/templates/components/control_center.html` (chat bar ~513-535 and the panel orb ~1146-1185)
- Test: `chauffeur/tests/test_panel_talk.py` (new; Claude writes it first)

**Interfaces:**
- Consumes: `satellite_for_panel`, `control_rules.panel_device(request)`, Task 5's payload ruling.
- Produces: `GET /api/panel/talk` → `{'available': bool, 'state': 'idle'|'listening'|'processing'|'responding'|'unavailable'|None}` (`available` false for a non-panel caller, no room, no satellite, or HA absent; `state` from the satellite entity's HA state).
- Produces: `POST /api/panel/talk` → 200 `{'ok': True}` after `ha_api.call_service('assist_satellite', 'start_conversation', payload)`; 403 for a non-panel caller; 409 `{'message': ...}` when no satellite; 429 when the same panel started one under 5 s ago; 502 `{'message': 'The <area name> speaker is offline.'}` when the call returns None or the entity is unavailable.
- UI: a mic button beside the chat input and on the orb, rendered only when `GET` says available (checked on load and every 5 minutes). Tap: POST, then poll GET once a second for at most 120 s, showing Listening / Thinking / Answering (states listening / processing / responding), back to idle on `idle`. A 4xx/5xx shows `showGlobalAlert(message)`. All URLs `base() + 'api/panel/talk'` (never root-relative). Follow `docs/ui_design_guide.md`.

- [ ] **Step 1: Claude writes the failing tests:** TestClient: `test_get_unavailable_non_panel`, `test_get_unavailable_no_room`, `test_get_available_with_state`, `test_get_no_ha`, `test_post_calls_start_conversation_payload`, `test_post_non_panel_403`, `test_post_rate_limited_429`, `test_post_offline_502`; jsdom (pattern `tests/test_board_render.py`): `test_button_hidden_when_unavailable`, `test_tap_posts_and_shows_listening`, `test_error_uses_global_alert`, `test_no_root_relative_url`.
- [ ] **Step 2:** Run; expect failures. **Step 3 (Codex):** implement; rebuild Tailwind. **Step 4:** Run `python tests/test_panel_talk.py tests/test_panel_room.py tests/test_control_grant_js.py tests/test_board_render.py`. Screenshot the panel bar and orb with the button (UI rule). **Step 5:** Commit `feat(panel): tap to talk on the room's satellite`.

**Landing point B:** Tasks 4-6 land like landing point A.
