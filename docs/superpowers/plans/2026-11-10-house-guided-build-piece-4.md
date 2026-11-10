# House guided build (piece 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A person is led through building their house: an empty canvas that invites a start, a step strip, a status chip with spend, pieces that appear in the real 3D house as the reader writes them, a Stop that ends the paid call at once, stop-fix-continue, and checks one at a time.

**Architecture:** Reader calls gain a streaming transport with a cancel handle (`services/llm_stream.py`). An incremental parser (`services/twin_stream.py`) turns the partial JSON into complete pieces. The build engine (`services/twin_build.py`) emits a `piece` event per complete piece and, on Stop, cancels the call, charges only what was produced and keeps the arrived pieces as a round. The editor draws each piece as a ghost that settles, and gains a front door, a step strip, a status chip and a checks queue that replaces the pause cards.

**Tech Stack:** FastAPI, urllib (no new packages), vendored three.js r187, plain ES modules, node and Playwright tests.

**Spec:** `docs/superpowers/specs/2026-11-09-house-connected-model-design.md` §6 (piece 4), §3, §4.6a, §8, §9 piece 4, §11.

## Global Constraints

- No new packages (never touch requirements.txt). Streaming uses urllib on the existing `llm_budget.urlopen`.
- Stage names, in this order and verbatim: `scale`, `outline`, `walls`, `rooms`, `doors and windows`, `fixtures`, `roofs`, `finishes`, `yard`.
- Step strip labels verbatim: `Your files`, `Your lot`, `Build`, `Check it`, `Link to Home Assistant`.
- Status chip words verbatim: `Working`, `Waiting on you`. Spend shows as `$x.xx so far`, estimate as `about $x.xx` (two decimals).
- Front door copy verbatim: `Let's make your house`, `Add plans and photos`, `Draw it myself`.
- Check actions verbatim: `Looks right`, `Fix it`, `Skip for now`. Proposals keep `Use this` and `Dismiss`.
- Stop is visible whenever a build is running and ends the provider call within 2 s. Pieces already complete are kept; the reply cache never stores a partial reply.
- A cancelled call is charged its input tokens plus the output it produced (provider usage when the stream reported it, else characters received / 4), never `max_output_tokens`.
- The spend shown on screen equals the sum of `twin_cost` ledger entries for the household (exit check).
- Generation never overwrites a person's piece (§4.6a, `src.person`); a disagreeing read becomes a proposal.
- Spend checkpoints ($10/$20/$30/$40, hard stop $50) stay; no browser dialogs; page JS fetches `base() + 'api/...'`; every new route gets an `auth.py` tier; Home Assistant absent changes nothing here.
- Never drop functionality without approval: every ability of the Your place dialog and the pause cards must live somewhere after this piece (the spec's §8.3 retirements are approved).
- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset; no test spends money (replay or stub readers only).

## Review Focus

1. Stop pressed while the first bytes have not arrived yet (in the request's connect/TTFB window): the call still ends, nothing is charged beyond input, the build reads `stopped`, Continue works.
2. A stream that ends mid-piece (network drop, max tokens): the half piece is discarded, complete pieces kept, the step reports a plain error and offers Read it again.
3. Continue after a hand fix that deleted or moved a piece the stopped read had produced: the re-read does not resurrect the deleted piece (tombstones) and the moved piece stays the person's.
4. Two tabs open on the editor during a streaming build: both see the same pieces in order; a Stop from either ends it.
5. A provider without streaming (OpenAI in the pro pool): the read still works blocking, pieces appear when the reply lands, and Stop still ends the call (socket closed).

---

### Task 1: Streaming transport with a cancel handle

**Files:**
- Create: `chauffeur/services/llm_stream.py`
- Modify: `chauffeur/services/twin_reads.py` (a streaming variant of `read`), `chauffeur/services/twin_cost.py` (charge for a cancelled call)
- Test: `chauffeur/tests/test_llm_stream.py`

**Interfaces:**
- Produces: `llm_stream.Cancel()` with `.cancel()`, `.cancelled -> bool`, `.attach(resp)` (closes an attached response from another thread).
- Produces: `llm_stream.stream_json(provider, url, api_key, model, system_prompt, user_prompt, *, images, max_output_tokens, thinking_level, timeout_s, cancel) -> Iterator[str]` yielding text deltas of the model's answer (thinking excluded), then setting `cancel.usage = {'input_tokens', 'output_tokens', 'complete': bool}`. Anthropic: Messages API `stream: true` SSE (`content_block_delta` text deltas, `message_delta` usage). Gemini: `:streamGenerateContent?alt=sse` (`candidates[0].content.parts[].text`, `usageMetadata`). Other providers: one blocking call through the existing `llm._call_llm_json(..., text=True)` path yielding the whole text once; cancel closes the socket.
- Produces: `twin_reads.read_stream(kind, context, images, *, cancel, on_text)` with the same pool/credential choice and validation as `read`, calling `on_text(delta)` per delta and returning the validated answer, or raising `twin_reads.Cancelled` after a cancel.
- Produces: `twin_cost.record(stage, usage, run, *, cancelled=False, produced_chars=0)`: when `cancelled` and usage lacks output tokens, charge `produced_chars // 4`.

- [ ] Step 1: tests (fake `llm_budget.urlopen` returning a file-like SSE body; no sockets): `anthropic_sse_yields_text_and_usage`, `gemini_sse_yields_text_and_usage`, `thinking_deltas_are_not_text`, `cancel_from_another_thread_ends_within_2s` (a body that blocks between chunks), `cancel_before_first_byte_ends`, `cancelled_call_charges_input_plus_produced_not_max`, `non_streaming_provider_yields_once_and_cancel_closes`, `read_stream_validates_like_read`.
- [ ] Step 2: run, expect failures.
- [ ] Step 3: implement.
- [ ] Step 4: run plus `tests/test_twin_reads*.py`, `tests/test_llm*.py` neighbours; all pass.
- [ ] Step 5: commit `feat(twin): reader calls stream and can be stopped mid-call`.

### Task 2: Pieces from partial JSON

**Files:**
- Create: `chauffeur/services/twin_stream.py`
- Test: `chauffeur/tests/test_twin_stream.py`

**Interfaces:**
- Produces: `twin_stream.Pieces(paths: dict[str, str])` where `paths` maps a JSON path (`building.walls`, `building.openings`, `building.fixtures`, `building.roof.sections`, `building.levels`, `rooms`) to a stage name; `.feed(text) -> list[tuple[str, str, dict]]` returning `(stage, path, item)` for every array item completed by this text; `.stage -> str|None` the stage whose array is open now; tolerant of whitespace, strings containing brackets and escaped quotes, and code fences.
- [ ] Step 1: tests: `items_arrive_when_their_closing_brace_arrives` (feed a recorded draft fixture from `tests/fixtures/twin_reads/recorded/` one character at a time and in random chunk sizes; the items equal the parsed answer's items in order), `strings_with_brackets_do_not_confuse_it`, `half_item_at_the_end_is_not_returned`, `stage_follows_the_open_array`, `nested_arrays_inside_an_item_stay_inside_it`.
- [ ] Step 2-4: fail, implement, pass.
- [ ] Step 5: commit `feat(twin): read pieces out of a reply as it streams`.

### Task 3: The build streams pieces and Stop ends the call

**Files:**
- Modify: `chauffeur/services/twin_build.py`, `chauffeur/main.py` (no new route; `status` payload grows), `chauffeur/services/twin_store.py` if a partial round needs a kind
- Test: `chauffeur/tests/test_twin_build_stream.py`

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces events: `{type:'piece', step, stage, kind, piece}` per complete piece (kind one of `level`, `wall`, `opening`, `fixture`, `roof`, `room`); `{type:'stage', step, stage}` when the open array changes.
- Produces: `twin_build.stop(build_id)` cancels the in-flight call (the worker's `Cancel`), records the cost as cancelled, publishes the complete pieces that arrived as one round `kind='build', step=<step>, partial=True`, sets state `stopped`; `resume`/`reread` no longer refuse with "still stopping" once the cancel returns (the refusal stays only while the cancel itself is in progress, under 2 s).
- Produces: Continue (`resume`) runs the stopped step again and the later steps on the model as it stands; person-owned pieces and tombstones are respected through the existing `_merge_list` and bridge proposals.
- Reader inputs: `stub reader` in tests gets an `on_text` callback so replays stream.
- [ ] Step 1: tests (replay a recorded draft through a streaming stub reader that yields the fixture in chunks): `pieces_arrive_in_order_before_the_step_settles`, `stop_mid_walls_keeps_complete_walls_and_charges_produced`, `stop_before_first_piece_keeps_nothing_and_charges_input`, `continue_after_stop_rereads_on_the_model_as_it_stands`, `continue_after_a_hand_delete_does_not_resurrect_it` (Review Focus 3), `stream_ending_mid_piece_reports_and_offers_read_again` (Review Focus 2), `paid_reply_cache_never_holds_a_partial`, `blocking_provider_still_stops` (Review Focus 5).
- [ ] Step 2-4: fail, implement, pass; neighbours: every `tests/test_twin_build*.py`, `tests/test_twin_store*.py`, `tests/test_twin_model*.py`, `tests/test_house_design_tool.py`.
- [ ] Step 5: commit `feat(twin-build): pieces stream into the house and Stop ends the call`.

### Task 4: The reader writes the model's rules, in stage order, with fixtures

**Files:**
- Modify: `chauffeur/services/twin_reads.py` (`_DRAFT_RULES`, `PROMPTS['draft']`, `PROMPTS['draft_level']`, `PROMPTS['draft_rooms']`, validators), `chauffeur/services/twin_model_bridge.py` (fixtures become anchors), `chauffeur/services/twin_build.py` (stage map)
- Test: `chauffeur/tests/test_twin_reads_rules.py`

**Interfaces:**
- The draft output order is `levels`, `walls`, `openings`, `fixtures`, `roof`, then the rest; the prompt states the model's rules: rooms are closed by walls; every opening sits on a wall and names it; fixtures shown on the plans (lights, switches, outlets, fans, smoke alarms) are `fixtures:[{kind, level, at:[x,y], surface:'ceiling'|'wall'|'floor', wall?}]`.
- Produces: the bridge turns each fixture into an anchor on its surface (`src.read`), never on a person's anchor spot; a fixture with no valid surface becomes a flag.
- [ ] Step 1: tests: `prompt_states_the_rules_and_order`, `validator_accepts_fixtures_and_rejects_bad_surface`, `fixtures_become_anchors_on_their_surfaces`, `a_recorded_draft_without_fixtures_still_validates` (old fixtures keep passing).
- [ ] Step 2-4: fail, implement, pass (+ `tests/test_twin_reads*.py`, `tests/test_twin_model_bridge.py`, `tests/test_twin_build_draft*.py`).
- [ ] Step 5: commit `feat(twin-reads): the reader is told the house's rules and reads fixtures`.

### Task 5: Pieces appear in the house as ghosts that settle

**Files:**
- Modify: `chauffeur/static/twin/editor/editor.js` (`onBuild`), `chauffeur/static/twin/editor/api.js` (poll every 500 ms while a read streams), create `chauffeur/static/twin/editor/build_ghosts.js`
- Test: `chauffeur/tests/test_twin_build_ghosts_js.py` (node), `chauffeur/tests/test_house_editor_guided_live.py` (live, stub streaming reader in the server)

**Interfaces:**
- Produces: `createBuildGhosts(view) -> {add(event), settle(round), clear(), count()}`; a `piece` event draws that piece alone in the real house at its building's transform, translucent, and fades to solid when the round that contains it lands; a stopped build's kept pieces settle with the partial round.
- [ ] Step 1: tests: node `a_piece_event_adds_one_ghost`, `settle_replaces_ghosts_with_the_round`; live `scenario_pieces_appear_one_by_one` (ghost count rises across polls before the step settles), `scenario_stop_mid_walls_keeps_the_walls` (Stop visible, press it, the walls already shown stay and settle), `scenario_two_tabs_see_the_same_pieces` (Review Focus 4).
- [ ] Step 2-4: fail, implement, pass (+ `tests/test_house_editor_model_live_t*.py` neighbours named in the brief).
- [ ] Step 5: commit `feat(twin-editor): the house builds itself in front of you`.

### Task 6: Status chip, Stop and spend

**Files:**
- Modify: `chauffeur/templates/house_editor.html`, `chauffeur/static/twin/editor/editor.js`, create `chauffeur/static/twin/editor/status_chip.js`; `main.py` `/api/house/editor/state` carries `cost.total` from the ledger and the running build's estimate
- Test: node `chauffeur/tests/test_twin_status_chip_js.py`; live scenarios in `test_house_editor_guided_live.py`

**Interfaces:**
- Produces: `createStatusChip(host) -> {update({state, pause, cost, estimate})}` showing `Working` while a step runs, `Waiting on you` while a pause/check/checkpoint waits, nothing else; `$x.xx so far` from the ledger total; `about $x.xx` for the running build's remaining estimate; the Stop button sits in the chip while Working.
- [ ] Step 1: tests: node `chip_words_follow_state`, `spend_and_estimate_format`; live `scenario_chip_spend_matches_the_ledger` (exit check), `scenario_stop_is_visible_while_working`.
- [ ] Step 2-4, Step 5: commit `feat(twin-editor): one chip says who is waiting and what it costs`.

### Task 7: The front door and the step strip

**Files:**
- Modify: `chauffeur/templates/house_editor.html`, `chauffeur/static/twin/editor/editor.js`, `chauffeur/static/twin/editor/place.js` (its dialog becomes the Your files and Your lot step panels), create `chauffeur/static/twin/editor/steps.js`
- Test: node `chauffeur/tests/test_twin_steps_js.py`; live scenarios in `test_house_editor_guided_live.py`; keep `tests/test_house_place_live.py` green (retarget selectors only where the test names the old dialog, and say so)

**Interfaces:**
- Produces: `createSteps(host, {state}) -> {render(state), open(name)}`; steps `Your files` (buildings, uploads, page roles, photo tags, shells), `Your lot` (plot read and suggestions, lot placement), `Build` (build buttons, estimates), `Check it` (Task 8 queue), `Link to Home Assistant` (piece 3's building card section); each shows done / now / not yet, derived from the model and the stored sources; always visible.
- Produces: with no buildings and no lot, the canvas shows `Let's make your house` with `Add plans and photos` (opens Your files) and `Draw it myself` (closes the front door and arms Draw wall from piece 2). Menu › Your place opens Your files.
- [ ] Step 1: tests: node `step_state_from_model_and_sources`; live `scenario_empty_house_shows_the_front_door`, `scenario_add_plans_opens_your_files`, `scenario_draw_it_myself_arms_draw_wall`, `scenario_every_your_place_ability_is_still_reachable` (a list of each control the old dialog had).
- [ ] Step 2-4, Step 5: commit `feat(twin-editor): the empty canvas leads and a step strip shows the way`.

### Task 8: Checks one at a time

**Files:**
- Modify: `chauffeur/static/twin/editor/flags.js`, `chauffeur/static/twin/editor/pauses.js` (pause kinds become checks), `chauffeur/static/twin/editor/editor.js`, create `chauffeur/static/twin/editor/checks.js`; `chauffeur/services/twin_build.py` (a check id per pause and a `skip` decision)
- Test: node `chauffeur/tests/test_twin_checks_js.py`; live scenarios in `test_house_editor_guided_live.py`; keep `tests/test_twin_build_draft_pause_js.py` and `tests/test_twin_flags_js.py` green or retarget with a stated reason

**Interfaces:**
- Produces: `createChecks(view, {api}) -> {queue(), current(), next()}` merging a build pause, model flags and proposals into one queue; one at a time on the model with the thing highlighted and the camera on it; `Looks right` (pause: answer accept; flag: `flag_ok`; proposal shows `Use this`/`Dismiss` instead), `Fix it` (opens the editor on that piece, the build stays paused), `Skip for now` (moves to the next, the item stays in the queue; a skipped build pause leaves the build `Waiting on you`). A pause's re-read stays available as `Read it again · about $x.xx`.
- [ ] Step 1: tests: node `queue_merges_pause_flags_and_proposals`, `skip_moves_on_and_keeps_the_item`; live `scenario_checks_come_one_at_a_time`, `scenario_fix_it_opens_the_piece`, `scenario_stop_fix_continue` (the piece-4 exit flow on the stub reader: start, Stop mid-walls, move a wall by hand, Continue, the rest builds on the moved wall).
- [ ] Step 2-4, Step 5: commit `feat(twin-editor): checks come one at a time on the house`.

### Task 9: Retire the legacy per-floor build path

**Files:**
- Modify: `chauffeur/services/twin_build.py` (`plan_steps` `part is None` branch, `_expand`, legacy pause kinds `scale_outline`/`level_registration`), `chauffeur/main.py` (legacy `{building:{id}}` body), `chauffeur/static/twin/editor/pauses.js` (legacy pause UI)
- Test: `chauffeur/tests/test_twin_build_legacy_retired.py`; retarget or delete legacy-only tests with a list in the report

**Interfaces:**
- A build request without `part` refuses with `Build a part of your place.`; a stored legacy build in progress at upgrade is reported stopped with `This build used an older path; start it again.`
- [ ] Step 1: tests: `legacy_body_refuses`, `stored_legacy_build_reports_stopped`, `part_builds_unchanged`.
- [ ] Step 2-4, Step 5: commit `refactor(twin-build): one build path`.

Execution order: 1, 2, 3, 4, 5, 6, 7, 8, 9. Tasks 1, 2 and 4 are independent and server-only; 5-8 need a browser round each.
