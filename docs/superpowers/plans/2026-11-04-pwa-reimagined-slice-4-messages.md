# PWA reimagined, slice 4: Messages — Signal's list, Messenger's thread — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The adult Messages tab becomes Signal's list (title, presence, camera and compose, a search field, a Moments row of rings with "Add" first, "Pinned" = Family and Argyle, "Chats" by last message; a row is avatar, name, time, one preview line, unread as weight plus a dot or a count; no cards, no separators) and a thread becomes a Messenger thread pushed as a `PwaNav` screen (Back, avatar, name, member line; day markers; theirs muted with a small sender name, mine in the accent; photos as rounded images; Argyle's asks as a white bordered bubble with buttons in the stream; compose = + for photos, the field, the mic where it works today, Send only when there is text). The Argyle overlay takes its three slice-2 carry-forwards. Kids render unchanged.

**Architecture:** A new `static/pwa_messages.js` owns the adult list: a pure `pwaConversationRows(channels, ctx)` groups and words the rows from the `/api/channels` payload the page already holds (`pwaTimeLabel`, `pwaPreviewLine` inside it), and `pwaRenderConversations()` paints them into `#channel-list` (buttons stay direct children so `pwaFilterConversations` and the kid check keep working; `renderChannelList` delegates to it for adults). The moments strip keeps `loadMomentsStrip` and its tap-through; adults get the ring skin and an "Add" ring. The thread keeps every id and handler: for an adult, `openChannel` pushes `PwaNav.push({id:'thread'})` and ADOPTS `#thread-view` into the screen body (the node moves, `getElementById` still finds it), `closeThread` pops, and `onPop` returns the node and finishes the close; hardware Back therefore closes the thread. The Messenger skin is CSS under `html[data-audience="adult"]` over the classes `renderThread` already emits, plus a `.pwa-thread-head` the screen draws (avatar + member line) and a `has-text` state on `#thread-form`. `renderThread`, `renderCard`, reactions, the ⋯ menu, albums, the lightbox, staging, voice, helper share mode and guests are not rewritten.

**Tech Stack:** FastAPI + Jinja, vanilla JS, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node + jsdom via `tests/pwa_pure.py` / `tests/test_pwa_nav.py` patterns. Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("Messages: Signal's list, Messenger's thread", dispositions rows 9-13 and 26, "Calls I made" 5, 8, 9). Mockup: `docs/design/pwa-reimagined/mockups/messages.html` (its `<style>` holds the sizes). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §8 and the `messages.html` gap table (302-324) — the preservation checklist. Slice 2 plan for the overlay contracts; slice 3 plan for adoption and `PwaNav`.

## Global Constraints

- Adult-only, under `html[data-audience="adult"]`; kids share `#messages-container`, `#channel-list`, `#thread-view` and every handler — a kid's list and thread must render exactly as today (`tests/pwa_child_checks.py` waits on `#channel-list > button`; the kid live checks in `test_pwa_adult_shell_live.py` stay green).
- Nothing a person can do today is removed (inventory §8): presence stack + roster flyout; New chat (pills, DM vs group, initiation limits); search; moments strip tap-through to the thread and the lightbox; incoming moment pop; thread open/read/back; day separators; drive-context chip; reactions (☺+, the six + recent, the ＋ picker); ⋯ Edit / Share / Delete / Delete album; photo and video single/album with lightbox and grid; staging up to ten, caption, remove, retry; voice in the Argyle DM (mic, Done, Stop, Play reply, Tap to reply, the panel); helper share mode; event-thread guests (parent); `messageMember` and `relayViaFamilyChannel` prefill; share-out; the unread tab badge.
- The builders keep their names and ids: `renderChannelList` → `#channel-list` (buttons as direct children), `loadMomentsStrip` → `#moments-strip-row`, `renderThread` → `#thread-messages`, `#thread-title`, `#thread-input`, `#thread-form`, `#thread-attach-btn`, `#phone-voice-*`; `openChannel(channelId, channelObj, focusMessageId)` and `closeThread()` keep their signatures (every caller — `messageMember`, `openMomentFromStrip`, `startNewChat`, `pwaOpenArgyle`, `app_voice.js` thread mode, `relayViaFamilyChannel`, the moment pop's Open chat — goes on calling them).
- The thread rides `PwaNav.push({ id: 'thread', title, render, onPop })` only for adults; `updateAgentFab`'s "thread open" test (`#thread-view` display `flex`) must still hold while adopted; the orb hides in the Argyle thread as today. Kids keep the absolute `#thread-view` overlay with no history entry.
- Numbers and words come from the payloads: `GET /api/channels?member_id=` rows (`id`, `kind` family|dm|group|event, `member_ids`, `title`, `last_message {ts, body, sender_member_id, attachment, id}`, `unread`); `channelDisplay(c)` stays the one source of a conversation's name, colour, avatar and image; `momentPreviewLabel` stays the attachment wording; the badge stays `updateMessagesBadge`.
- No browser dialogs; sheets via `_pwaModal`; choices via `promptChoice`. Page JS fetches `apiBase + 'api/...'`.
- The overlay carry-forwards (slice 2): a swipe down over a long reply must not fire while the reply is being scrolled; the dim gets an assistive-technology Dismiss control; a reply that landed refreshes the schedule surfaces once.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.755` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. A thread opened from anywhere (`messageMember` from a ride row, the moments strip, New chat, the orb's "full conversation in Messages", `app_voice.js` thread mode) must land as ONE pushed screen with the right title and member line, and hardware Back must close it and refetch the list (Task 3 live `thread_from_every_door`).
2. Leaving Messages with a thread open (tab tap, `setView` from a deep link) must return `#thread-view` to its place, hidden, with `activeChannelId` null and voice stopped, so the next open starts clean (Task 3 live `leave_with_thread_open`).
3. The helper share-only surface and the guest profile must keep working in the new skin: a helper opening an event thread sees "Share a moment", no history, the picker; a guest lands on Messages with their invited conversations only (Task 3 live `helper_share_mode`, `guest_lands_on_messages`).
4. Kids: a navigator's list and thread render with today's classes and no `PwaNav` entry (Task 3 live `kid_unchanged`).
5. The overlay's swipe over a scrolled reply: a long reply scrolled by touch must not dismiss; a swipe from the dim or from a reply at scroll top must (Task 2 jsdom `swipe_ignores_a_scrolling_reply`).

---

### Task 1: The conversation rows, pure

**Files:**
- Create: `chauffeur/static/pwa_messages.js` (pure parts)
- Test: `chauffeur/tests/test_pwa_conversations.py` (node via `tests/pwa_pure.py`)

**Interfaces:**
- `pwaTimeLabel(ts, now) -> string`: `ts` seconds; same calendar day → `h:mm` (12-hour, no leading zero, no AM/PM as the sentence builder does); yesterday → `Yesterday`; within six days → weekday (`Mon`); same year → `Oct 31`; else `Oct 31, 2025`.
- `pwaPreviewLine(last, ctx) -> string`: `last` is `channel.last_message` or null; `ctx = { meId, members: [{id,name}], previewLabel: fn(last) }` (`previewLabel` = `momentPreviewLabel`, passed in so the pure function never reads the page); "You: <text>" when the sender is `meId`; "<first name>: <text>" otherwise (Argyle → "Argyle"); attachments through `previewLabel(last)`; null → `No messages yet`.
- `pwaConversationRows(channels, ctx) -> { pinned: row[], chats: row[] }` with `ctx = { meId, members, now, argyleAllowed, display: fn(channel) -> {name, color, avatar, image}, previewLabel }`:
  - `pinned`: the `family` channel (always first, from the payload), then Argyle — the DM whose `member_ids` holds `argyle` when it exists, else a synthetic row `{ id: null, kind: 'argyle', name: 'Argyle', preview: 'Ask me anything.', time: '' }` when `argyleAllowed`; absent otherwise.
  - `chats`: every other channel, in payload order (the server already sorts by last activity).
  - row = `{ id, kind, name, color, avatar, image, time: pwaTimeLabel(last.ts, now) or '', preview, unread: int, unreadStyle: 'none'|'dot'|'count' }` — `dot` when `unread === 1`, `count` when `> 1` (capped `99+` at paint time).
  - Pure: no `document`, no `window`.

- [ ] **Step 1: Write the failing node test** (`tests/test_pwa_conversations.py`, fixtures: a family channel, an Argyle DM, a human DM, an event thread with a 3-photo album last message, a group; `now` fixed to 2026-11-04T15:12; members with first names) with scenarios `is_pure`, `family_then_argyle_pinned`, `argyle_synthetic_when_no_dm` (and absent when `argyleAllowed` is false), `chats_keep_payload_order`, `time_labels` (today `9:40`, yesterday, `Mon`, `Oct 31`, `Oct 31, 2025`), `preview_lines` ("You: …", "Lorena: Did you move the dentist?", "You: 📷 3 photos" through `previewLabel`, "No messages yet"), `unread_styles` (0 none, 1 dot, 2 count).
- [ ] **Step 2: Run** → FAIL (module missing). **Step 3: Implement** at column 0. **Step 4: Run** `python tests/test_pwa_conversations.py` → ok.

---

### Task 2: The overlay's three carry-forwards

**Files:**
- Modify: `chauffeur/static/pwa_argyle.js`, `chauffeur/static/pwa_argyle.css` (the Dismiss control's skin)
- Test: `chauffeur/tests/test_pwa_argyle.py` (extend, jsdom)

**Interfaces:**
- Swipe: the `touchstart` records the target's nearest scrollable ancestor inside `.pwa-argyle-ask` (the reply bubble's scroller) and its `scrollTop`; on `touchend` the gesture closes only when `dy >= 60`, `|dy| > 2 * |dx|`, and (no scroller was under the finger OR its `scrollTop` was 0 at start and is still 0).
- Dismiss: `<button class="pwa-argyle-dismiss" type="button" aria-label="Dismiss">×</button>` inside the overlay (top-right, 36px, visible but quiet; in the tab order before the input; `close('dismiss')`); the hint keeps "Swipe down to dismiss".
- Refresh: when a reply lands in the overlay (the newest-reply draw, typed or voice), call `window.refreshTodaySurfaces?.(true)` once per reply (debounced by message id), so an ask answered through the overlay reaches My Day and Plan without a tab change.

- [ ] **Step 1: Add the failing jsdom cases**: `swipe_ignores_a_scrolling_reply` (a reply scroller with `scrollTop` 40 → a 100px downward touch does not close; `scrollTop` 0 → closes), `dismiss_control_closes_and_returns_focus` (keyboard-opened overlay: Tab reaches `.pwa-argyle-dismiss` before the input; activating it closes and focuses the orb), `reply_refreshes_today_once` (a stubbed `window.refreshTodaySurfaces` is called once for a reply and not again for the same reply's re-pull).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python tests/test_pwa_argyle.py` (21/21) `&& python tests/test_pwa_argyle_live.py` → ok.

---

### Task 3: The live proof (written before Tasks 4-5, green after them)

**Files:**
- Create: `chauffeur/tests/test_pwa_messages_live.py`
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py` (the Messages block ~463-468: the search still filters to one visible `#channel-list > button`; add: `.pwa-conv-label` "Pinned" and "Chats" present, Family first; the hint block ~200-209: after "full conversation in Messages" `PwaNav.depth() === 1` and the screen h1 is `Argyle`, `closeThread()` still works), `chauffeur/tests/test_pwa_argyle_live.py` (the to-messages hint expectation: a pushed screen, Back returns to the list), `chauffeur/tests/test_moments_past_days_live.py:98` (keep: `#thread-view` display not none — now inside `#pwa-stack`; add `PwaNav.depth() === 1` for an adult).

**Interfaces:** profiles `parent` (d1), `adult` (d2), `helper` (d3, no `chat.event_threads`), `guest`, `navigator` (kid). Mocks: `**/api/channels?*` → family (unread 2, last from Lorena), the Argyle DM `dm_argyle` (last from Argyle, with a `card` of kind `ask`), a human DM (unread 1), an event thread "Soccer practice" (last = a 3-photo album from me), a group; `**/api/channels/*/messages*` → per channel: day markers across today and yesterday, mine/theirs, one photo message, one Argyle message with an ask card (`renderCard` output with buttons), reactions on one; `**/api/presence/moments*` → two moments (one video) for the parent, `[]` for the kid; `**/api/channels/*/read` recorder; `**/api/channels/*/messages` POST recorder; `**/api/messages/*/react` recorder; `**/api/channels/dm` → the Argyle DM; the helper's event thread with `member_ids` not holding the helper.

- [ ] **Step 1: Write the test** with scenarios: `list_is_signals` (parent: `.pwa-msg-title` 34px "Messages"; `#presence-stack` present; `#messages-add-moment` and `#messages-new-chat` 36px circles; the search field; `#moments-strip-row` rings with "Add" first and the event title under each; `.pwa-conv-label` texts `['Pinned','Chats']`; the Pinned rows are Family then Argyle; Chats in payload order; each `#channel-list > button.pwa-conv` has `.pwa-conv-av`, `.pwa-conv-name`, `.pwa-conv-time`, `.pwa-conv-preview`; the family row has `.pwa-conv-count` "2" and a bold preview, the human DM a `.pwa-conv-dot`; no `.rounded-2xl` card borders; order and texts equal `pwaConversationRows(...)` evaluated in the page over the mocked payload; screenshot `messages-list-light.png`); `search_filters` (typing "Soccer" leaves one visible button and hides the labels; clearing restores); `add_moment_ring` (tap "Add" → `promptChoice` over event threads → pick → the Soccer thread is pushed with `#thread-attach-btn.animate-pulse`); `thread_is_messengers` (tap Family → `PwaNav.depth() === 1`, h1 "Family", back "‹ Messages", `.pwa-thread-head` with the avatar and the member line "Alex, Robin, Sam"; `#thread-view` inside `#pwa-stack .pwa-screen` and `display: flex`; `.pwa-day` markers "Yesterday" and "Today"; a theirs bubble background `rgba(31, 29, 43, 0.06)` with a `.pwa-who` sender name above, mine the accent; the photo bubble's img radius 16px; the Argyle message's card has a white background and a 1px border with its buttons; ☺+ and ⋯ still present and working (react → POST recorded); Send absent until text is typed, present after; `#phone-voice-mic` hidden here; screenshot `messages-thread-light.png`); `argyle_thread_has_mic` (the Argyle row → `#phone-voice-mic` visible, the orb hidden, h1 "Argyle"); `thread_from_every_door` (`messageMember('adult')`, `openMomentFromStrip`, `startNewChat` with one pill, the overlay hint, `app_voice.js`-style `openChannel(id, ch)` by evaluate: each lands at depth 1 with the right h1; `page.go_back()` closes it, `#thread-view` back under `#messages-container` and hidden, `activeChannelId` null, `api/channels` refetched); `leave_with_thread_open` (open Family, tap `#tab-myday` → depth 0, `#thread-view` home and hidden, `threadChannel` null; back to Messages → the list, not the thread); `helper_share_mode` (helper opens the event thread → h1 "Share a moment", the note text, no history, `#thread-attach-btn` present, text send alerts); `guest_lands_on_messages` (guest: `currentView === 'messages'`, only their channels, no Argyle pinned row, no `#messages-add-moment`); `kid_unchanged` (navigator: `#channel-list > button` without `.pwa-conv`, no `.pwa-conv-label`, opening a thread leaves `PwaNav.depth() === 0` and `#thread-view` inside `#messages-container`); `widths_and_dark` (360 and 390 no overflow; dark screenshots `messages-list-dark.png`, `messages-thread-dark.png`; reduced motion); `served.errors()` empty per profile.
- [ ] **Step 2: Run** `python tests/test_pwa_messages_live.py` → FAIL at `.pwa-conv-label` missing.
- [ ] **Step 3: After Task 5, run** it and the adjusted tests → green.

---

### Task 4: The list: header, search, Moments rings, Pinned and Chats

**Files:**
- Modify: `chauffeur/static/pwa_messages.js` (add `pwaRenderConversations()`, `pwaAddMomentRing()`), `chauffeur/templates/app.html` (the `#messages-container` header: a `.pwa-msg-title` h1 "Messages" for adults (the existing `div.text-lg` stays for kids), `id="messages-new-chat"` on the New chat button, a new `<button id="messages-add-moment" class="pwa-adult-only" aria-label="Add a moment" onclick="pwaAddMoment()">` before it, `#moments-strip` label hidden for adults; `renderChannelList` delegates to `pwaRenderConversations()` when `pwaIsAdult()`; `loadMomentsStrip` prepends the Add ring for adults when an event channel exists; `applyViewVisibility`/`pwaRenderHeading`: the `#pwa-page-heading` entry for `messages` is dropped for adults (the in-page title replaces it, as Household did)), `chauffeur/static/pwa_shell.css` (the list skin), `chauffeur/static/pwa_shell.js` (`pwaFilterConversations` also hides `.pwa-conv-label` while a query is non-empty)
- Test: Task 3's `list_is_signals`, `search_filters`, `add_moment_ring`, `guest_lands_on_messages`, `kid_unchanged`; `python tests/test_pwa_conversations.py`, `tests/test_template_js.py`

**Interfaces:**
- `pwaRenderConversations()`: paints into `#channel-list` from `pwaConversationRows(channelsData, ctx)`: `<div class="pwa-conv-label">Pinned</div>` then one `<button class="pwa-conv" data-channel="<id>" onclick="...">` per row (`.pwa-conv-av` 52px circle with the image, avatar glyph or initial and the colour; `.pwa-conv-tx` > `.pwa-conv-name` (name + `<small class="pwa-conv-time">`) and `.pwa-conv-preview` (`.u` when unread); `.pwa-conv-dot` or `.pwa-conv-count`), then `<div class="pwa-conv-label">Chats</div>` and its rows; the "Chats" label is absent when there are no chats; the synthetic Argyle row's tap is `pwaOpenArgyle()`; every other row's tap is `openChannel(id)`; the empty state stays "No conversations yet." Rows stay direct children of `#channel-list` (the search and the kid check depend on it).
- `pwaAddMoment()`: the event channels from `channelsData` (kind `event`) → `promptChoice('Add a moment to…', '', [{value: id, label: title}])` (one channel → straight through) → `openChannel(id)` then `armMomentCapture()` (the existing pulse on `#thread-attach-btn`); with no event channel → `showGlobalAlert('Start from an event: open it from your day and tap Add a moment.')`. The "Add" ring (`.pwa-mo.add`) appears only when an event channel exists; the strip itself stays absent with no moments (call 9).
- CSS from the mockup: title 34px/700/-.03em; header icons 36px circles `rgba(31,29,43,.05)`; search 12px radius `rgba(31,29,43,.05)` 10px 14px 15px; labels 12px/700 uppercase .08em faint, 10px 20px 6px; `.pwa-conv` flex gap 14 padding 11px 20px, no border, no background; avatar 52px; name 16px/600 with time 13px faint; preview 14px muted, `.u` ink; dot 10px accent; count 22px pill accent; moments ring 58px gradient `linear-gradient(135deg,#8a7cff,#ffb36b)` 3px with a 2px white inner border, label 11px muted under, the Add ring `rgba(31,29,43,.08)` with a white inner. Dark through the tokens (`--pwa-ink`, `--pwa-card`, `--pwa-accent`). The old adult rules at `pwa_shell.css:333-342, 356` are replaced, not stacked.

- [ ] **Step 1: Read Task 3's test and the mockup**; list every selector and text.
- [ ] **Step 2: Implement** list → header → rings → CSS; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_pwa_conversations.py && python tests/test_template_js.py && python tests/test_pwa_messages_live.py` (the list scenarios green; thread scenarios still red).

---

### Task 5: The thread as a pushed screen, in the Messenger skin

**Files:**
- Modify: `chauffeur/templates/app.html` (`openChannel`: for an adult, when no `thread` screen is up, `PwaNav.push({ id: 'thread', title: name, render(body) { body.append(pwaThreadHead(c)); body.append(#thread-view) }, onPop() { pwaThreadRestore(); } })`; when a thread screen is already up, re-title it and re-render the head instead of pushing again (a door opened from inside a thread, e.g. the moments strip is not reachable there, but `messageMember` from a card is); `closeThread()`: for an adult with the thread screen on top, `PwaNav.pop()` and let `onPop` finish; the body of today's `closeThread` moves into `pwaThreadRestore()` (voice stop, state reset, guests, staging, `display:none`, the node back to `#messages-container` before `#thread-view`'s old sibling, `applyViewVisibility`, `fetchChannels`) and kids call it directly; `#thread-form`: an `input` listener on `#thread-input` toggles `has-text` on the form; the Send button gets `id="thread-send"`), `chauffeur/static/pwa_messages.js` (`pwaThreadHead(c)` → `<div class="pwa-thread-head">` with the 38px avatar (`channelDisplay` image / glyph / initial, the colour) and `.pwa-thread-sub` member line: family → the other members' first names joined by ", "; group → the same; event → the event's day from `c.event_end`/`title` as today's `channelDisplay` name carries it (fall back to "Event thread"); DM → the member's status line when `presence` has one, else nothing; Argyle → "Ask anything · every exchange lands here"), `chauffeur/static/pwa_shell.css` (the thread skin under `[data-audience="adult"] #pwa-stack #thread-view` and `.pwa-screen[data-screen="thread"]`), `chauffeur/static/pwa_nav.js` (none expected; `push` already focuses the h1 — the thread screen must NOT steal focus from `#thread-input` when the person typed first: push happens before any typing, fine).
- Test: Task 3's thread scenarios and the three adjusted live tests; `tests/test_pwa_nav.py`, `tests/test_pwa_argyle.py`, `tests/test_app_voice_host.py`, `tests/test_share_out.py`, `tests/test_mission_chat_card_render.py` stay green.

**Interfaces:**
- The screen: `.pwa-screen[data-screen="thread"] .pwa-screen-body { display:flex; flex-direction:column; min-height:0; padding:0 }`; `#pwa-stack #thread-view { position: static; flex: 1; min-height: 0; background: transparent }` (today's `absolute inset-0 bg-gray-950 z-20` is for the kid overlay); the thread's own header row (`#thread-view > div:first-child`) becomes `display: contents` for adults with its back button and `#thread-title` hidden, so `#thread-guests-btn` still renders (in the head row, right-aligned); `#thread-guests-panel` positions under it.
- Bubbles (CSS only, over the classes `renderThread` emits): theirs `.bg-gray-800` → `rgba(31,29,43,.06)` on `--pwa-ink`, 20px radius, 9px 13px, 16px/1.35; mine `.bg-blue-600` → the accent on white (the existing `[data-profile-color]` rule already recolours, keep it); the sender name `.text-xs.font-bold` → 11px faint; `dayDivider` → centred 12px faint with no hairlines (`.pwa-day` class added to its wrapper in `dayDivider` for both audiences, kids' rule unchanged); the photo `img.rounded-2xl` → 16px radius; `renderCard` output (`.bg-gray-900.border-gray-700` boxes) → white, 1px `rgba(31,29,43,.08)` border, 20px radius, its buttons 999px pills (`.bg-blue-600` primary = ink on white per the mockup's `.acts span`, secondary `rgba(31,29,43,.06)`); reactions and the ☺+ / ⋯ row keep their size, 60% opacity until the bubble is tapped (`:focus-within, :active` → 100%); the `🚗 re:` chip keeps its words.
- Compose: `#thread-form` → `.pwa-compose` 10px 14px, `#thread-attach-btn` 36px circle `rgba(31,29,43,.05)`, `#thread-input` pill 22px radius `rgba(31,29,43,.05)` 11px 16px 16px, `#phone-voice-mic` 36px accent circle (shown exactly where `ChauffeurPhoneVoice.visibility()` shows it today), `#thread-send` hidden unless `#thread-form.has-text` (then a 36px accent circle with an arrow glyph, `aria-label="Send"`); Enter still submits; the voice panel keeps its ids under the compose row.
- `pwaThreadRestore()`: idempotent; called by `onPop` (adult) and `closeThread` (kid); never pops.

- [ ] **Step 1: Read Task 3's thread scenarios and the mockup's thread styles.**
- [ ] **Step 2: Implement** push + adopt + restore → head → skin → compose rules; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_pwa_nav.py && python tests/test_pwa_argyle.py && python tests/test_app_voice_host.py && python tests/test_share_out.py && python tests/test_mission_chat_card_render.py && python tests/test_template_js.py && python tests/test_pwa_messages_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_argyle_live.py && python tests/test_moments_past_days_live.py` → green.

---

### Task 6: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (a "Messages, Signal's list and Messenger's thread" section under the reimagined vocabulary: the row contract, the Add ring, the thread as an adopted pushed screen, the skin rules, the compose rule, the overlay carry-forwards), `chauffeur/system_capabilities.md` (new top entry `v2.499.755`), `chauffeur/config.yaml` (→ `2.499.755`)

- [ ] **Step 1: Docs and version.**
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_pwa_conversations.py && python tests/test_pwa_argyle.py && python tests/test_pwa_nav.py && python tests/test_app_voice_host.py && python tests/test_share_out.py && python tests/test_mission_chat_card_render.py && python tests/test_messaging.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_auth.py && python tests/test_pwa_messages_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_argyle_live.py && python tests/test_pwa_myday_live.py && python tests/test_pwa_household_live.py && python tests/test_moments_past_days_live.py && python tests/test_app_voice_live.py && python tests/test_audience_picker_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 4 of the reimagined PWA, Messages (v2.499.755)` and push.

---

## Sequencing calls (check these while reading)

1. **The thread is a pushed screen that ADOPTS `#thread-view`** (the slice-3 pattern), not a rewrite: every id, handler, the voice panel, staging and the lightbox keep working because the node moves and `getElementById` still finds it; hardware Back closes the thread for free. Kids keep today's absolute overlay and no history entry.
2. **Argyle is always pinned for an adult who can reach Argyle**, even before the DM exists (a synthetic row whose tap is `pwaOpenArgyle`, which ensures the DM); the server's "no empty channels" rule is unchanged.
3. **The mic stays where it works today** (the Argyle DM through `ChauffeurPhoneVoice.visibility()`); the mockup's mic in the Family thread would be a new voice-to-text feature, not this slice. Send appears only with text; Enter still sends.
4. **"Add" on the Moments row posts into an event thread** (the only albums the server has): a `promptChoice` over the event channels, then the thread with the picker pulsing; with no event thread the person is told to start from the event. The row stays absent with no moments (call 9).
5. **The in-page 34px title replaces the `#pwa-page-heading` entry for Messages**, as Household did in slice 3; the presence stack, camera and compose sit on the title row.
6. **Argyle's cards keep `renderCard`** (the ask, proposal, mission, project and course builders) and get the white bordered bubble by CSS; buttons become pills. No second card renderer.
7. **The overlay's three carry-forwards ride here** (swipe vs scroll, an assistive-technology Dismiss, a schedule refresh after a reply) because the overlay and the thread share the DM and the reply path.
8. **Not this slice:** the header's avatar-top-right → Profile and the header shrink ("More and the header": with slice 6), "Note to self" (dropped), voice in non-Argyle threads, a kid Messages restyle.
