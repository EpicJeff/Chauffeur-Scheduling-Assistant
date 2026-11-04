# PWA reimagined, slice 2: Argyle from anywhere — the overlay, and Ask Argyle leaves More — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tapping the orb raises a Siri-style overlay over whatever screen the adult is on (the screen stays put and dims, the edges glow, your words right-aligned, Argyle's reply in one frosted bubble with its real buttons, a text field with the orb as the send); holding the orb talks through the phone voice path; every exchange is written to the Argyle DM so Messages stays the record; the old "Ask Argyle" popup and its separate history leave More.

**Architecture:** A new `static/pwa_argyle.js` owns the overlay (`window.PwaArgyle`) and never routes through `setView`, so a pushed screen under it survives. It ensures the Argyle DM once (the same `POST api/channels/dm` the thread uses), sends text with the thread's own `POST api/channels/{id}/messages`, and learns of the reply the way the thread does: the SSE `api/messages/stream` event for that channel, followed by one `GET api/channels/{id}/messages`; the newest Argyle message's body and `card` are drawn with the thread's `renderCard`, so the buttons are the same buttons. Hold-to-talk drives `ChauffeurPhoneVoice` in a new host mode that writes its states into the overlay instead of the thread panel and does not switch views. The popup (`#kiosk-chat-popup`, `toggleKioskChat`, `/api/chat?surface=pwa` client), the FAB and the More entry are removed; the server's `/api/chat` routes stay for the wall.

**Tech Stack:** FastAPI + Jinja, vanilla JS, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node + jsdom for pure-JS tests (jsdom resolves from `C:\Users\ffejn\node_modules`, pattern `tests/test_pwa_nav.py`). Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("Argyle from anywhere: the orb and the overlay", "Decided with the user" bullet 2, "Calls I made" 8). Mockup: `docs/design/pwa-reimagined/mockups/argyle-overlay.html` ("Summoned, either way" phone; its `<style>` holds the sizes). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §8 (Argyle's three implementations) and the `argyle-anywhere.html` gap table (326-339). Slice 0/1 plans for the orb, `PwaNav` and the brief.

## Global Constraints

- The overlay opens WITHOUT `setView` and without `openChannel`; `currentView`, `PwaNav.depth()` and the screen's scroll are unchanged while it is up and after it closes. (Slice 1 note: `setView` clears `PwaNav`.)
- The orb shows only for `pwaOrbAllowed()` (adult + scope `chat.agent` not none); it hides while the overlay is open and while the Argyle thread is open (`.argyle-orb-hidden` via `updateAgentFab`, whose name, its `classList.contains('hidden')` screen check and its call from `showDriverSelection` stay: `tests/test_panel_chrome.py:803-815` pins them).
- Every exchange lands in the Argyle DM: text goes through `POST api/channels/{id}/messages` `{sender_member_id, body}`; voice goes through `/api/app-voice/*`, which already posts transcript and reply into the DM. The overlay never calls `/api/chat`.
- The reply bubble's buttons are `renderCard(card)` (app.html ~5675): asks, action proposals, mission asks, project and program-course cards — the same handlers as Messages. One card at a time (the newest Argyle message).
- Numbers and wording come from the server's reply; the overlay adds no sentence of its own beyond its states ("Listening…", "Thinking…", "Still thinking — the reply will land in Messages.").
- Never narrates lateness; never auto-opens; a visible drive sheet is never covered by an auto-opened overlay (only a tap or hold opens it).
- No browser dialogs. Page JS fetches `apiBase + 'api/...'`.
- Dismiss by swipe down, backdrop tap, Escape and hardware Back; Back uses a history entry with a non-null state `{pwaOverlay: 'argyle'}` (foreign to `PwaNav`, which ignores non-null states without `pwaDepth`).
- `prefers-reduced-motion: reduce`: no glow animation, no waveform animation, a plain fade.
- Helpers and guests get the orb only with a `chat.agent` grant; if the server refuses the DM (`_refuse_initiate`, main.py ~17187), the overlay shows the server's detail and no input, never a spinner.
- Kids: untouched (no orb, no overlay; `pwa_child_shell.*` not edited).
- "Ask Argyle" leaves More and the popup's separate `surface=pwa` history retires (approved removal 2026-11-03). The server routes `/api/chat`, `/api/chat/conversation` stay (the wall's control-center widget uses them); the auth rules at `services/auth.py:276-277` are untouched.
- Nothing else a person can do is removed: the Argyle DM in Messages, New chat → Argyle, the thread's mic (`#phone-voice-mic`) and voice controls all stay.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.753` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. The overlay must not disturb the screen under it: open it over a pushed `PwaNav` screen and over My Day scrolled halfway; after dismiss, depth and `scrollTop` are what they were (Task 4 live `screen_stays_put`).
2. A reply that arrives while the overlay is CLOSED must not reopen it or throw; the next open shows no stale "Thinking…" (Task 1 jsdom `closed_overlay_ignores_events`; Task 4 live).
3. A helper with a `chat.agent` grant whose DM is refused must see the refusal, not a spinner (Task 4 live `helper_refusal`).
4. Hold then release under 350 ms is a tap (type mode); hold past 350 ms starts voice and release ends the capture (`done()`), never a second open (Task 1 jsdom `hold_gesture`; Task 4 live `hold_talks`).
5. Removing the popup must leave `test_access_conversations.py` meaningful: its PWA half is retargeted, not deleted, and `/api/chat` keeps serving the wall (Task 5).

---

### Task 1: The overlay module: gesture, reply picker, chrome

**Files:**
- Create: `chauffeur/static/pwa_argyle.js`
- Modify: `chauffeur/static/pwa_shell.css` (the overlay skin)
- Test: `chauffeur/tests/test_pwa_argyle.py` (jsdom + pure node)

**Interfaces:**
- Pure: `pwaArgyleGesture()` → an object `{ down(t), up(t) -> 'tap'|'hold-end'|null, cancel(), tick(t) -> 'hold-start'|null, state }` with the hold threshold `PWA_ARGYLE_HOLD_MS = 350`; `up` before the threshold returns `'tap'`; `tick` at or after the threshold returns `'hold-start'` once; `up` after a hold returns `'hold-end'`; `cancel` (pointercancel / pointerleave) returns to idle without a tap.
- Pure: `pwaArgyleNewestReply(messages, afterId, argyleId) -> message | null`: the last message whose `sender_member_id === argyleId` and whose `id !== afterId` and which comes after the message `afterId` in the array (or any Argyle message when `afterId` is null); null when none.
- `window.PwaArgyle = { open({ mode: 'type'|'talk' }), close(reason), isOpen(), channelId(), send(text), pull(), onStream(channelId), setState(name, text?) }` with states `idle | thinking | listening | speaking | error`. `open` builds (once) `<div id="pwa-argyle-overlay" class="pwa-argyle" hidden>` appended to `document.body` with children `.pwa-argyle-dim` (click → close), `.pwa-argyle-glow` (pointer-events none), `.pwa-argyle-ask` holding `.pwa-argyle-wave` (six bars), `.pwa-argyle-you` (right-aligned, your last words), `.pwa-argyle-reply` (hidden until a reply: `.pwa-argyle-reply-body` + `.pwa-argyle-reply-card`), `.pwa-argyle-status` (role=status), `form.pwa-argyle-bar` with `input.pwa-argyle-input` (placeholder "Or type…") and `button.pwa-argyle-send.argyle-orb` (type submit, `ArgyleOrb.glyph()`), and `.pwa-argyle-hint` = "Swipe down to dismiss · " + `<button class="pwa-argyle-to-messages">full conversation in Messages</button>`. `open` sets `document.documentElement.dataset.pwaArgyle = '1'`, pushes `history.pushState({ pwaOverlay: 'argyle' }, '')`, focuses the input in type mode, and calls `updateAgentFab()` when it exists. `close(reason)` hides, clears `.pwa-argyle-you`/reply/status, removes the dataset flag, calls `history.back()` only when `history.state && history.state.pwaOverlay === 'argyle'` and the close did not come from popstate, calls `ChauffeurPhoneVoice.stop(false)` when a voice turn is live, and `updateAgentFab()`.
- Swipe down: `touchstart`/`touchend` on `.pwa-argyle-ask` with a downward delta ≥ 60 px closes; `keydown` Escape closes; `popstate` whose state lacks `pwaOverlay` while open closes with reason `'back'`.
- `send(text)`: trims, ignores empty, writes `.pwa-argyle-you`, hides the previous reply, `setState('thinking')`, POSTs `apiBase + 'api/channels/' + channelId + '/messages'` with `{ sender_member_id: selectedMemberId, body: text }`; on non-ok `setState('error', 'Could not reach Argyle')`; records `pwaArgyleAfterId` = the id the POST returns (the thread's own message) so the picker only takes replies after it; starts a 45 s timer that turns a still-thinking state into `'Still thinking — the reply will land in Messages.'`.
- `onStream(channelId)`: when open and `channelId === PwaArgyle.channelId()`, calls `pull()`; otherwise nothing. `pull()`: `GET apiBase + 'api/channels/' + id + '/messages?limit=20'`, `pwaArgyleNewestReply(msgs, afterId, ARGYLE_ID)`; when found: body into `.pwa-argyle-reply-body` (escaped), `renderCard(m.card)` into `.pwa-argyle-reply-card` when `m.card`, `setState('idle')`, clear the timer, remember the id so a second pull does not redraw. The Argyle member id is `'argyle'` (`storage.ensure_argyle_member`).
- Channel: `PwaArgyle.ensureChannel()` POSTs `api/channels/dm` `{ member_id: selectedMemberId, other_member_id: 'argyle' }` once per member (cache keyed by member); a non-ok response shows the response's `detail` (or "Argyle isn't available for this account.") in `.pwa-argyle-status` with class `is-refused`, hides the bar, and still lets the overlay close.
- CSS (adult-scoped): `.pwa-argyle { position: fixed; inset: 0; z-index: 300 }` (above the tab bar and `#pwa-stack` 40, below `_pwaModal` 400 and the toast); `.pwa-argyle-dim { background: rgba(31,29,43,.18); backdrop-filter: blur(2px) }`; `.pwa-argyle-glow { box-shadow: inset 0 0 0 3px rgba(138,124,255,.9), inset 0 0 40px 10px rgba(255,179,107,.45), inset 0 0 90px 30px rgba(138,124,255,.35); animation: pwa-argyle-glow 2.4s ease-in-out infinite alternate }`; `.pwa-argyle-ask { position:absolute; left:16px; right:16px; bottom: calc(24px + env(safe-area-inset-bottom, 0px)) }`; `.pwa-argyle-you { text-align:right; font-size:17px; color:#fff; text-shadow:0 1px 6px rgba(0,0,0,.4); margin:0 10px 12px }`; `.pwa-argyle-reply { background: rgba(255,255,255,.92); backdrop-filter: blur(16px); border-radius: 26px; padding: 16px 18px; font-size: 17px; line-height: 1.4; box-shadow: 0 14px 40px rgba(31,29,43,.25); color: var(--pwa-ink-light, #1f1d2b) }` (the bubble stays light in both themes; its card buttons take the card's own classes); `.pwa-argyle-bar { margin-top:12px; display:flex; align-items:center; gap:10px; background: rgba(255,255,255,.92); border-radius: 28px; padding: 8px 8px 8px 18px }`; `.pwa-argyle-send { --argyle-orb-size: 40px }`; `.pwa-argyle-wave i` six bars 5 px wide, heights 14/26/38/22/30/12, `animation: pwa-argyle-wave .9s ease-in-out infinite alternate` only in state `listening`; `.pwa-argyle-hint { text-align:center; color:#fff; font-size:13px; opacity:.85; margin-top:10px }`; `[data-audience="adult"] #tab-argyle { touch-action: none; -webkit-touch-callout: none; user-select: none }` (a held orb must not open the OS text menu); enter: the ask block translates up 24 px and fades over .22 s; `@media (prefers-reduced-motion: reduce) { .pwa-argyle-glow, .pwa-argyle-wave i { animation: none } .pwa-argyle-ask { transition: opacity .15s } }`.

- [ ] **Step 1: Write the failing test** (`tests/test_pwa_argyle.py`; pure cases via `tests/pwa_pure.py`'s extractor over `static/pwa_argyle.js`, jsdom cases in the `test_pwa_nav.py` style with `runScripts: 'outside-only'`, a stub `window.ArgyleOrb`, `renderCard`, `updateAgentFab`, `selectedMemberId`, `apiBase`, a recording `fetch`, and `ChauffeurPhoneVoice.stop`):

```
pure:  'tap_under_threshold' (down 0, up 200 → 'tap'), 'hold_gesture' (down 0, tick 350 → 'hold-start', tick 400 → null, up 900 → 'hold-end'), 'cancel_is_silent',
       'newest_reply_after_mine' (msgs [me#1, argyle#2, me#3, argyle#4], afterId 3 → #4), 'no_reply_yet' (→ null), 'first_open_takes_latest' (afterId null → #4)
jsdom: 'open_builds_chrome' (one #pwa-argyle-overlay, hint text, input focused in type mode, html[data-pwa-argyle], history.state.pwaOverlay 'argyle', updateAgentFab called),
       'send_posts_to_the_dm' (fetch POST api/channels/dm then api/channels/dm_argyle/messages with {sender_member_id, body}; .pwa-argyle-you text; state thinking),
       'pull_draws_the_reply_and_card' (fetch GET returns [me, argyle with card {kind:'ask', ...}] → reply body shown, renderCard called once with the card, state idle),
       'closed_overlay_ignores_events' (close(); onStream('dm_argyle') → no fetch; open() again → no stale thinking, no stale reply),
       'dismissals' (Escape closes; dim click closes; a popstate with null state closes with reason 'back' and does NOT call history.back again; swipe: touchstart y 500 → touchend y 580 closes),
       'refusal_shows_detail' (dm POST 403 {detail:'Requires chat.agent'} → status text contains it, class is-refused, bar hidden),
       'reduced_motion_rule' (source: pwa_shell.css has the prefers-reduced-motion block naming .pwa-argyle-glow and .pwa-argyle-wave).
```

- [ ] **Step 2: Run** `python tests/test_pwa_argyle.py` → FAIL (`static/pwa_argyle.js` missing).
- [ ] **Step 3: Implement** the module (classic script, column-0 top-level statements for the two pure functions and the constant) and the CSS.
- [ ] **Step 4: Run** `python tests/test_pwa_argyle.py` → ok.

---

### Task 2: Voice has a host: `ChauffeurPhoneVoice.start({ host })`

**Files:**
- Modify: `chauffeur/static/app_voice.js:11-30` (`visibility`, `status`), `:79-120` (`start`), `:31-34` (`valid`), `:225-240` (`dispatch`), `:67-78` (`stop`)
- Test: `chauffeur/tests/test_app_voice_host.py` (jsdom)

**Interfaces:**
- `ChauffeurPhoneVoice.start(opts = {})`: when `opts.host` is an object `{ status(label, state), transcript(text), reply(text, meta), channelId() , isOpen() }`, the turn runs in host mode: no `setView('messages')`, no `openChannel`; `status()` calls `host.status(label, state)` instead of writing `#phone-voice-*`; the recognized transcript goes to `host.transcript`; the reply text from `/run` goes to `host.reply(reply, { continue_conversation, speech_safe })`; `valid()` holds while `host.isOpen()` is true (the `activeChannelId` check is skipped in host mode); `dispatch` skips `refreshThread()` when `currentView !== 'messages'`; the `channel_id` sent to `/api/app-voice/start` is `host.channelId()`. Without `opts.host` nothing changes (the thread's mic path is byte-for-byte today's behaviour; `tests/test_app_voice_live.py` and `test_voice_setup_pwa.py` stay green).
- `ChauffeurPhoneVoice.done()` and `stop(show)` work in host mode (done ends the capture; stop cancels the server turn and the audio, calls `host.status('', 'idle')`).
- The host is cleared on `stop`/`onended`.

- [ ] **Step 1: Write the failing jsdom test**: load `static/app_voice.js` with stubs (`memberToken` → 'tok', `isSecureContext` true, `self === top`, `navigator.mediaDevices.getUserMedia` resolving a fake stream, a fake `MediaRecorder` that emits one blob on `stop`, a recording `fetch` answering `/api/app-voice/start` `{request_id, channel:{id:'dm_argyle'}}`, `/audio` `{transcript:'Can Grandma take Kate Thursday?'}`, `/run` `{reply:'Grandma Ruth is free…', speech:false, continue_conversation:false}`, `/cancel` `{status:'stopped'}`; `setView` and `openChannel` as spies; `Audio` stubbed). Cases: `host_mode_never_switches_views` (start({host}) → setView/openChannel never called, host.status saw 'listening'), `transcript_and_reply_reach_the_host` (after done(): host.transcript got the text, host.reply got the reply), `stop_clears_the_host` (stop() → host.status('', 'idle'), a later status() writes nothing to the host), `thread_mode_unchanged` (start() without host → setView('messages') and openChannel called as today).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** behind `opts.host`. **Step 4: Run** `python tests/test_app_voice_host.py && python tests/test_voice_setup_pwa.py` → ok.

---

### Task 3: The live proof (written before Task 4, green after it)

**Files:**
- Create: `chauffeur/tests/test_pwa_argyle_live.py`
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py` `check_orb` (~147-181): the tap now opens the overlay (not the thread); `check_orb` asserts `#pwa-argyle-overlay` visible, `currentView` unchanged, orb hidden, `dm_posts[-1]` body `{member_id: key, other_member_id: 'argyle'}` (the ensure), then Escape → overlay hidden, orb back; the "full conversation in Messages" button → `activeChannelId && threadChannel.member_ids.includes('argyle')` → `closeThread()` → orb back; the More assertions gain `assert page.locator('[data-feature="assistant"]').count() == 0`; `#kiosk-chat-popup` count 0.
- Modify: `chauffeur/tests/test_argyle_orb.py` `scenario_the_phone_bar_ends_with_the_orb`: the orb's tap handler is the gesture (`pwaArgyleBindOrb` or the names Task 4 defines) and `pwaOpenArgyle` still exists (the hint's path to Messages); add `'static/pwa_argyle.js'|ver` loaded by app.html; add "no `toggleKioskChat`, no `kiosk-chat-popup` in app.html or pwa_shell.js".

**Interfaces:** profiles `parent` (d1), `helper_granted` (helper with `scope.overrides['chat.agent'] = 'all'`; the DM route answers 403 `{detail: 'Requires chat.agent'}` for this key to model the server's refusal), mocks as the adult-shell test plus `**/api/channels/dm_argyle/messages*` answering a scripted list that the test flips between calls (`[]` → after a POST, `[me, argyle-with-ask-card]`), `**/api/asks/*/answer` recording POSTs, `**/api/app-voice/start` `{request_id, channel:{id:'dm_argyle'}}` and `**/api/app-voice/*/cancel` `{status:'stopped'}` (the live test does not run a real mic: it stubs `ChauffeurPhoneVoice.start` with a spy that records `opts.host` presence and returns, and asserts the gesture called it; one separate case stubs nothing and asserts the secure-context alert path is not triggered on localhost — skip if not meaningful).

- [ ] **Step 1: Write the test** with scenarios:
  - `tap_opens_over_the_screen`: push a `PwaNav` probe screen, scroll My Day 300 px, `page.locator('#tab-argyle').click()` → `#pwa-argyle-overlay` visible, `PwaNav.depth() == 1`, `currentView == 'myday'`, scroll unchanged, orb `.argyle-orb-hidden`, the input focused, hint text.
  - `type_and_reply`: fill the input, submit → POST `/api/channels/dm_argyle/messages` body `{sender_member_id: 'parent', body: '...'}` recorded; `.pwa-argyle-you` shows it; `.pwa-argyle-status` 'Thinking…'; `page.evaluate("PwaArgyle.onStream('dm_argyle')")` after flipping the messages mock → `.pwa-argyle-reply-body` shows the reply, `.pwa-argyle-reply-card` has an ask card with two buttons; click one → POST `/api/asks/<id>/answer` recorded; state idle.
  - `dismissals`: Escape closes and the orb returns; reopen; backdrop tap closes; reopen; `page.go_back()` closes and `PwaNav.depth()` is still 1; reopen; swipe down (`page.touchscreen` or dispatched touch events on `.pwa-argyle-ask`) closes.
  - `to_messages`: open, click "full conversation in Messages" → `activeChannelId == 'dm_argyle'`, overlay hidden, orb hidden (thread open), `closeThread()` → orb back.
  - `hold_talks`: stub `ChauffeurPhoneVoice.start` to record calls; `pointerdown` on the orb, wait 450 ms, `pointerup` → overlay open in talk mode (`.pwa-argyle-wave` visible, status 'Listening…' written by the host stub, or the spy saw `opts.host`), exactly one `start` call with `host`, no second open; a fast tap (down/up in 100 ms) → type mode, no `start` call.
  - `helper_refusal`: for `helper_granted` the orb is visible; tap → status contains 'Requires chat.agent' with `is-refused`, no input bar; Escape closes.
  - `closed_overlay_ignores_events`: close, flip the messages mock, `PwaArgyle.onStream('dm_argyle')` → no fetch to messages (count the route hits); reopen → no reply bubble, state idle.
  - `popup_is_gone`: `#kiosk-chat-popup` count 0, `#kiosk-chat-fab` count 0, More has no `[data-feature="assistant"]`, `typeof toggleKioskChat === 'undefined'`.
  - `reduced_motion_and_dark`: a context with `reduced_motion='reduce'`: `.pwa-argyle-glow` computed `animationName` is 'none'; `applyTheme('dark')` screenshot; screenshots `argyle-overlay-type.png`, `argyle-overlay-reply.png`, `argyle-overlay-talk.png`, `argyle-overlay-dark.png`.
  - `served.errors()` empty per profile.
- [ ] **Step 2: Run** `python tests/test_pwa_argyle_live.py` → FAIL at `#pwa-argyle-overlay` missing.
- [ ] **Step 3: After Task 4, run** it and `python tests/test_pwa_adult_shell_live.py && python tests/test_argyle_orb.py` → green.

---

### Task 4: Wire it: the orb's gesture, the stream hook, the hint, the orb's hiding

**Files:**
- Modify: `chauffeur/templates/app.html:~116` (load `static/pwa_argyle.js` deferred after `pwa_myday.js`), `:~537` (`#tab-argyle` loses `onclick="pwaOpenArgyle()"`; the gesture binds it), `:961-984` (`updateAgentFab`: the orb hides when `PwaArgyle?.isOpen()` OR the Argyle thread is open; the FAB lines go in Task 5), `:4589-4606` (`connectMessagesStream` onmessage: before the `currentView === 'messages'` branch call `window.PwaArgyle?.onStream(data.channel_id)`), `:869` (`setView` leaving messages stops voice: also `PwaArgyle?.close('view')` so a tab tap under the overlay never leaves it orphaned — but tabs are under the dim, so this is the Back/deep-link case)
- Modify: `chauffeur/static/pwa_shell.js:17-38` (`pwaOpenArgyle` stays as the DM opener the hint uses: `PwaArgyle.close('messages')` then the existing body), new `pwaArgyleBindOrb()` called from `pwaSyncShell` once: `pointerdown` → `gesture.down(now)` + a 350 ms timer → on `'hold-start'` `PwaArgyle.open({mode:'talk'})`; `pointerup` → `'tap'` → `PwaArgyle.open({mode:'type'})`, `'hold-end'` → `ChauffeurPhoneVoice.done()`; `pointercancel`/`pointerleave` → `gesture.cancel()`; `contextmenu` prevented; `touch-action: none` on the orb; the `click` event is swallowed (the gesture owns it).
- Modify: `chauffeur/static/pwa_argyle.js` (`open({mode:'talk'})` builds the host object and calls `ChauffeurPhoneVoice.start({ host })`; `host.status` maps `listening`→ wave on + "Listening…", `thinking` → "Thinking…", `speaking` → "Speaking…", `idle` → clear; `host.transcript` → `.pwa-argyle-you`; `host.reply` → `.pwa-argyle-reply-body` at once, then `pull()` fetches the card; when `continue_conversation` the input gets focus with placeholder "Tap to reply…")

**Interfaces:** consumes Task 1's `PwaArgyle` and Task 2's host mode; produces `pwaArgyleBindOrb()` in `pwa_shell.js`.

- [ ] **Step 1: Read Task 3's live test** and the mockup; list every selector and text it asserts.
- [ ] **Step 2: Implement** the wiring. Run `python tools/build_tailwind.py` if any template class changed.
- [ ] **Step 3: Run** `python tests/test_pwa_argyle.py && python tests/test_app_voice_host.py && python tests/test_template_js.py && python tests/test_pwa_argyle_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_argyle_orb.py` → green.

---

### Task 5: Ask Argyle leaves More; the popup and the FAB go

**Files:**
- Modify: `chauffeur/templates/app.html:10842-10883` (remove `#kiosk-chat-popup`, `#kiosk-chat-fab`), `:10885-11021` (remove the popup script: `toggleKioskChat`, `resetPwaChat`, `loadChatHistory`, `appendMessage`, `scrollToBottom`, `submitChat`, the consts), `:1171, 4381, 8208` (drop the `resetPwaChat()` calls), `:961-984` (`updateAgentFab` keeps its name, the picker/login `classList.contains('hidden')` check and the orb toggle; drops the `#kiosk-chat-fab` lines), `:7681, 7980` (its other callers stay)
- Modify: `chauffeur/static/pwa_shell.js:225` (remove the `assistant` More item), `chauffeur/static/pwa_shell.css:147` and `chauffeur/static/pwa_child_shell.css:13` (drop `#kiosk-chat-fab` from the hide lists; the child CSS edit is one selector removal, not a behaviour change), `chauffeur/static/app_voice.js:103-106` (drop the popup hide)
- Modify: `chauffeur/tests/test_access_conversations.py:305-360` (controller: retarget `scenario_clients_request_server_owned_conversations`'s client half to the wall widget in `templates/components/control_center.html` — slice its `submitChat`/history script the same way and assert it asks `api/chat/conversation?surface=` and posts `conversation_id`; keep the server `surface=pwa` API scenarios as they are)
- Test: `tests/test_argyle_orb.py` (Task 3's additions), `tests/test_panel_chrome.py` (unchanged, must stay green), `tests/test_access_conversations.py`, `tests/test_auth.py`

- [ ] **Step 1: Remove** the markup, the script, the callers, the More entry, the CSS selectors and the voice hide; keep `updateAgentFab`'s shape.
- [ ] **Step 2: Run** `python tests/test_argyle_orb.py && python tests/test_panel_chrome.py && python tests/test_access_conversations.py && python tests/test_auth.py && python tests/test_template_js.py && python tests/test_voice_setup_pwa.py && python tests/test_household_features_live.py` → green.

---

### Task 6: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (extend the slice-0 orb bullet: the orb's two gestures, the overlay's contract — no `setView`, the DM is the record, `renderCard` buttons, dismissals, reduced motion — and "Ask Argyle is not in More")
- Modify: `chauffeur/system_capabilities.md` (new top entry `v2.499.753`; the slice-0 entry's "they leave in slice 2" sentence becomes past tense), `chauffeur/config.yaml` (→ `2.499.753`)

- [ ] **Step 1: Docs and version.**
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_pwa_argyle.py && python tests/test_app_voice_host.py && python tests/test_argyle_orb.py && python tests/test_panel_chrome.py && python tests/test_access_conversations.py && python tests/test_auth.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_voice_setup_pwa.py && python tests/test_pwa_nav.py && python tests/test_pwa_argyle_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_myday_live.py && python tests/test_household_features_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 2 of the reimagined PWA, Argyle from anywhere (v2.499.753)` and push.

---

## Sequencing calls (check these while reading)

1. **The reply reaches the overlay the way it reaches the thread**: the SSE channel event plus one messages read. No new server route, no polling loop; a 45 s "still thinking" hint covers a slow model, and Messages always has the record.
2. **Voice gets a host mode rather than a second voice client.** `ChauffeurPhoneVoice` keeps one state machine; the overlay is a sink for its states. The thread's mic path is unchanged.
3. **Hold is 350 ms** (the user's "hold to talk"; shorter and a slow tap talks, longer and the gesture feels stuck). Cost if wrong: one constant.
4. **The hint's "Messages" button is the one way from the overlay into the thread**; it reuses `pwaOpenArgyle`, which stays.
5. **`test_access_conversations.py`'s client half is retargeted to the wall widget**, which makes the same request; the server `surface=pwa` scenarios stay because the server surface is not retired (the wall and tests still exercise `/api/chat`).
6. **Kid stages do not get the orb or the overlay in this slice** (slice 0's rule); the spec's "kid bars gain the orb where the stage already reaches Argyle" is a later pass.
7. **The overlay never auto-opens and never covers a drive's Arrived by itself**; while a drive sheet is open the orb is still tappable (slice 6 owns the drive screens and may hide the orb on the road).
