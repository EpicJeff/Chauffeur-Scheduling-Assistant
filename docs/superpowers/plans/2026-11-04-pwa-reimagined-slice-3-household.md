# PWA reimagined, slice 3: Household — cards, then focus — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The adult Household tab becomes five cards in the order of what needs you most (Chores, Rewards, Tasks, Lists, Projects & programs), each a door: a tap pushes a full screen with "‹ Household", the thing's title, Argyle's one-line lead, a segment control where the thing has modes, and the full content drawn by today's builders in the new skin. Threads leave Household and keep their home on Plan's Needs-you lane and My Day. The household to-do list reaches the phone for the first time. The pushed-screen stack gets the hardening slice 0 deferred.

**Architecture:** A new `static/pwa_household.js` owns the cards: a pure `pwaHouseholdCards(inputs)` ranks and words them from the payloads the page already holds (chores, points, rewards, redemptions, lists with their server `open_count`, household tasks, projects, programs), a pure `pwaHouseholdLead(cards)` writes the lead, and `pwaRenderHousehold()` paints into `#house-anchors`' place. Tapping a card calls `PwaNav.push`; the screen ADOPTS the builder's own node (`#chores-content`, `#house-lists`, `#projects-container`) into its body and returns it `onPop`, so every handler keeps firing and no id is duplicated; a segment control shows one group of the adopted content (`data-chore-group` / `data-reward-group` wrappers that `renderChores` stamps for adults). `renderChores`, `renderHouseLists`, the Alpine projects page and `renderProgramsSection` are not rewritten. Household tasks (`/api/household-tasks`, already SIGNED_IN under `lists.household_tasks`) get a phone builder (list, complete, add) and feed My Day's Needs you. Threads: `fetchHouseThreads` / `renderHouseThreads` / `#house-threads` keep their names and move their host into Plan's Family pane under the Needs-you lane; My Day's `pwaNeedsYouInputs` adds threads in group `now`. `PwaNav` gains the reload stamp, focus management and `inert` on the covered view.

**Tech Stack:** FastAPI + Jinja, vanilla JS + one Alpine include, precompiled Tailwind (`python tools/build_tailwind.py` after any template class change), Playwright live tests via `tests/live_app.py`, node + jsdom for pure-JS tests (`tests/pwa_pure.py`, `tests/test_pwa_nav.py` patterns). Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-11-03-pwa-reimagined-design.md` ("Household: cards, then focus", vocabulary, "Calls I made" 4, "Left to the builder" card order). Mockup: `docs/design/pwa-reimagined/mockups/household.html` (both phones; its `<style>` holds the sizes). Inventory: `docs/design/pwa-reimagined/current-state-inventory.md` §7 and the `household-cards.html` gap table (277-301) — the preservation checklist. Slice 0/1/2 plans for `PwaNav`, the tokens, the dataset contract and the Needs-you pile.

## Global Constraints

- Adult-only, under `html[data-audience="adult"]`; the kid "House" tab (`pwaChildHouseTabs`, `renderChores`' child branches, `renderHouseLists` for kids) is untouched and the kid live checks stay green.
- Nothing a person can do today is removed (inventory §7 rows): chores Mark done / release / Claim / Assign / Unassign / Waiting for OK / verify / send back with reason; redemption Grant / reject / Approve anyway; family goals Grant / Grant now · cover / Grant anyway / Release; balances; lists select / private lock / open counts / item check / Add / needed-by explanations / in-cart count / No lists shared; threads' whole lane (state, next move, asks, notes, photos, Handled, close, linked records) — moved, not dropped; the lists-only reveal shows only the Lists card.
- The builders keep their names and their write targets: `renderChores` → `#chores-content`, `renderHouseLists` → `#house-lists`, `renderHouseThreads` → `#house-threads` / `#house-threads-lane` (tests pin: `tests/test_chores.py:421-428`, `test_projects_parity.py:134`, four thread live tests that call `fetchHouseThreads()` and read `#house-threads`).
- Pushed screens through `PwaNav.push({id, title, render, onPop})` only; never a second stack, never `setView` to reach a card's content; `#chores-container.dataset.section` still mirrors the open screen (`tasks|lists|reviews|rewards|projects`) because `tests/test_project_sheets_phone_live.py:170-171` and `test_pwa_myday_live.py:378` read it.
- Numbers come from the owning payloads: `choresData`, `redemptionsData`, `rewardsData` + pools, the `/api/points` balances, `houseLists[].open_count` (server-side), `/api/household-tasks` rows with their `past_due` / `due_today`, `/api/projects` rows (`state`, `lane`, `owner_member_id`), `fetchMyPrograms`' programs with `upcomingWindows(p.id)[0]`. The card computes nothing a module already computes; `houseChoresAttention()` stays the Household badge and the review count.
- Household tasks: read `GET /api/household-tasks`, complete `POST /api/household-tasks/{id}/complete`, add `POST /api/household-tasks` `{title, due_date?, assigned_to?}`; no edit/delete on the phone this slice (additive); only members whose `lists.household_tasks` is not `none` see the Tasks card (helpers and guests never).
- No packing in the Lists card (no packing list exists; packing waits for slice 6). "Shop day" on the Lists card comes from `GET /api/shopping/runs` (`next` for the default list) or is omitted.
- No browser dialogs; sheets via `_pwaModal`; choices via `promptChoice`; text via `promptInput`. Page JS fetches `apiBase + 'api/...'`.
- `PwaNav` hardening: on load, a history state with numeric `pwaDepth > 0` and an empty stack is re-stamped to `pwaDepth: 0` (a reload never leaves a dead Back); `push` moves focus to the screen's `h1` (tabindex −1) and `pop` returns it to the element that was focused before the push; while `depth() > 0` the covered view root gets `inert` (the tab bar and `#pwa-stack` stay live); `tests/test_pwa_nav.py` 11/11 stay green.
- Tailwind rebuilt before any live run; `chauffeur/config.yaml` → `2.499.754` and a `system_capabilities.md` entry in the last task.

## Review Focus

1. A lists-only member (chores door closed, holds a shared list) must see exactly one card, Lists, and tapping it must open the lists with Add and check working (Task 5 live `lists_only_member`).
2. The Chores screen's "To check" segment must show the same rows the My Day review card led to, and verifying one must update the card line and the Household badge on Back (Task 5 live `verify_from_to_check`).
3. Threads must still be reachable and actionable after leaving Household: a parent with an open thread sees it on Plan's lane with note/photo and on My Day's pile (Task 5 live `threads_live_on_plan`; the four thread live tests green).
4. Reload with a pushed screen's state in history must land on the tab with no dead Back press (Task 2 jsdom `reload_restamps_the_root`; Task 5 live `reload_lands_on_the_tab`).
5. A household task due today must appear on My Day's pile and in the Tasks card line, and completing it from the Tasks screen must clear both (Task 5 live `household_task_due_today`).

---

### Task 1: The cards and the lead, pure

**Files:**
- Create: `chauffeur/static/pwa_household.js` (pure parts)
- Test: `chauffeur/tests/test_pwa_household_cards.py` (node via `tests/pwa_pure.py`)

**Interfaces:**
- `pwaHouseholdCards(inputs) -> cards[]` with `inputs = { role, canReview, listsOnly, facets: { chores, rewards, tasks, lists, projects }, chores: [], balances: [], rewards: [], redemptions: [], householdTasks: [], lists: [], runs: {}, projects: [], programs: [], nextWindowFor: (programId) => window|null, members: [], today: 'YYYY-MM-DD' }` and each card `{ id: 'chores'|'rewards'|'tasks'|'lists'|'projects', icon, title, line, pills: [{text, tone: 'plain'|'hot'|'ok'}], faces: [memberId], progress: 0..1|null, score, open: { screen: id } }`:
  - `chores`: open = chores with state `open`; claimed = by whom (`claimed_by_name` counts, "Maya has 2 claimed"); done waiting = state `done` (parent only); line "N open · <name> has M claimed · K done waiting on you"; pills: `hot` "K to check" (parent, K>0), then up to two live items ("<title> · <claimant or open>"); score = 3·done + 1·open (parent) / 1·eligible-open (others).
  - `rewards`: pending redemptions (parent) "<name> asked for <reward> · <cost> pts"; funded pools "Family goal: <title> funded"; else the top goal "<title> <pct>%" with `progress`; pills `hot` "N request(s)" (parent), then balances "<name> <balance> pts" (up to two); score = 3·pending + 2·funded.
  - `tasks`: household tasks open; line "N due this week · <first overdue title> is overdue" (or "N open", or "Nothing on the list"); pills `hot` "N overdue", then the next due "<title> · <weekday>"; score = 3·past_due + 2·due_today + 1·due_this_week.
  - `lists`: "<name> <open_count>" joined by " · " (up to three lists), pills `hot` "Shop day <today|tomorrow|weekday>" when `runs.next` is within 7 days, then "N lists"; score = 2 if shop day is today/tomorrow else 1·(any open).
  - `projects`: running = projects `state === 'active'` (lane `needs_you` first) + programs `state in (active, paused)`; line = up to three titles, a program as "<title> (lesson <unit_n> of <total>)" when known; pills `hot` "<program> · <weekday h:mm>" for the soonest next window, "N running"; faces = owners (`owner_member_id`, program `member_id`) deduplicated; score = 3·needs_you projects + 1·(a window today).
  - A card whose facet is `none` is absent; `listsOnly` → only `lists`; a card with score 0 sinks to the bottom (stable order among zeros: chores, rewards, tasks, lists, projects).
- `pwaHouseholdLead(cards) -> string`: "N thing(s) want your yes." from hot review/request counts (parent), then one of: "Shop day is today/tomorrow.", "<title> is overdue.", "<program> is at <h:mm>."; max two sentences; "All quiet in the house." when every score is 0.

- [ ] **Step 1: Write the failing node test** with fixtures for a parent, a non-parent adult, a lists-only member, a keeping-up adult (facets from the presets: `keeping_up` has lists.shopping none, household_tasks none) and cases: `order_follows_need` (a done chore and a pending redemption outrank quiet lists), `zero_scores_sink_stable`, `lists_only_is_one_card`, `facet_none_hides_the_card`, `chores_line_and_pills` (exact strings), `rewards_progress_and_request_pill`, `tasks_overdue_first`, `lists_shop_day_tomorrow`, `projects_faces_and_next_window`, `lead_sentences` (parent with 2 hot → "Two things want your yes. Shop day is tomorrow."; all quiet → "All quiet in the house."), `is_pure`.
- [ ] **Step 2: Run** → FAIL (module missing). **Step 3: Implement** at top level (column 0, no DOM). **Step 4: Run** `python tests/test_pwa_household_cards.py` → ok.

---

### Task 2: `PwaNav` hardening: reload, focus, inert

**Files:**
- Modify: `chauffeur/static/pwa_nav.js`, `chauffeur/templates/app.html` (the covered view root gets an id if it lacks one), `chauffeur/static/pwa_shell.css` (`.pwa-screen h1 { outline: none }`, `.pwa-screen h1:focus-visible` ring)
- Test: `chauffeur/tests/test_pwa_nav.py` (extend)

**Interfaces:**
- On script load: `if (history.state && typeof history.state.pwaDepth === 'number' && history.state.pwaDepth > 0 && depth() === 0) history.replaceState({ ...history.state, pwaDepth: 0, pwaScreen: null }, '')`.
- `push`: remember `document.activeElement` as the screen's `opener`; after the body renders, focus the `h1` (`tabindex="-1"`). `pop`/`clear`: focus the popped screen's `opener` when it is still in the document and visible, else `#tab-${currentView}` if present, else nothing.
- `sync()`: when `depth() > 0`, set `inert` (and `aria-hidden="true"`) on the covered root `PWA_NAV_COVERED_ROOT` (default selector `#pwa-covered` — Task 5 gives the view container that id; `#pwa-tab-bar` and `#pwa-stack` are outside it); remove both at depth 0.

- [ ] **Step 1: Add the failing jsdom cases**: `reload_restamps_the_root` (state `{pwaScreen:'x', pwaDepth:1}` before load, empty stack → after load `history.state.pwaDepth === 0`; `history.back()` then does nothing visible and no error), `push_moves_focus_to_the_title` (`document.activeElement` is the `h1` with tabindex -1), `pop_returns_focus_to_the_opener` (a focused button pushes; after pop it is focused again; after removing the opener, focus goes to `#tab-household` or stays), `covered_root_is_inert_while_a_screen_is_up` (`#pwa-covered` has `inert` and `aria-hidden` at depth 1, neither at 0; `#pwa-tab-bar` never).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `python tests/test_pwa_nav.py` (15/15) `&& python tests/test_pwa_argyle.py && python tests/test_template_js.py` → ok.

---

### Task 3: Household tasks on the phone, and threads move to Plan

**Files:**
- Modify: `chauffeur/templates/app.html`: new `fetchHouseholdTasks()` / `householdTasksData` / `renderHouseholdTasks(host)` / `completeHouseholdTask(id)` / `addHouseholdTask()` near the Household builders (~6830-7090); `paneSectionsHtml` (~2529-2545) hosts `#house-threads` after `#mind-container` in the Family pane; `fetchMind` (~3746) fetches `kinds=finding,insight,thread` with `owner=` for threads and `renderMind` draws threads through the same `window.Situations.render` with `houseThreadExtras` (or `renderHouseThreads` renders into the moved `#house-threads` — one of the two, not both; keep `renderHouseThreads`/`fetchHouseThreads`/`#house-threads-lane` names); `setView('family')` calls `fetchHouseThreads()`; `setView('chores')` no longer does.
- Modify: `chauffeur/static/pwa_myday.js`: `pwaNeedsYouInputs` adds `householdTasks` (rows with `past_due || due_today`) and `threads` (situations of kind thread in group `now`); `pwaNeedsYou` gains kinds `household_task` (icon '☑️', title, why "overdue" / "due today", deadline = due_date, rank 2, open `{screen:'tasks'}` → the Household Tasks screen via `pwaOpenHouseScreen`) and `thread` (icon '🧵', title, why = next move, deadline `due_at`, rank 2, open `{view:'family', anchor:'house-threads'}`); `pwaBriefFacts` maps `household_task` → "<title> is overdue." / "<title> is due today."
- Test: `chauffeur/tests/test_pwa_needs_you.py` (+3 cases), `chauffeur/tests/test_household_tasks_phone.py` (TestClient: the three routes answer for a parent and a household adult, 403 for a helper; a source scenario that `app.html` fetches `api/household-tasks` and posts `complete`), the four thread live tests (`test_situations_lane_live.py`, `test_reply_reading_live.py`, `test_thread_photo_live.py`, `test_browse_thread_live.py`) must stay green — read them first: they call `fetchHouseThreads()` and read `#house-threads`; if one navigates to the chores view to find the lane, update that navigation to the Family view in the same spirit and say so.

**Interfaces:**
- `renderHouseholdTasks(host)`: open tasks sorted due first (past due at the top with a `hot` chip "overdue", due today "today"), each row title / due weekday / `assigned_to_name` or "anyone", a `✓` button → `completeHouseholdTask(id)` (POST, then refetch + repaint + `pwaRenderHousehold()`), an Add form (`#household-task-add` input + Add; due date through `promptInput('When is it due? (YYYY-MM-DD, blank for none)')` and assignee through `promptChoice` over household adults + "Anyone"); empty: "Nothing on the household list."
- `pwaOpenHouseScreen(id)` (Task 4) is what `pwaOpenNeed` calls for `open.screen`.

- [ ] **Step 1: Write the failing tests** (needs-you cases: `household_task_due_today_is_a_card`, `thread_in_now_is_a_card`, `household_tasks_outrank_quiet_lists_but_not_a_needs_driver`; the TestClient scenarios; a source scenario for the Family pane hosting `#house-threads`).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** the three plus `python tests/test_template_js.py && python tests/test_projects_parity.py && python tests/test_chores.py` and the four thread live tests → green.

---

### Task 4: The live proof (written before Task 5, green after it)

**Files:**
- Create: `chauffeur/tests/test_pwa_household_live.py`
- Modify: `chauffeur/tests/test_pwa_adult_shell_live.py` (the household block ~431-437 and ~516-521: `open_review_card` now lands on the pushed Chores screen with the "To check" segment on; `#chores-container[data-section="reviews"]` stays true as the mirror; `✓ Verify` visible inside `#pwa-stack .pwa-screen`; the "Tasks → Mark done" step becomes segment "Mine"; Back returns to the cards), `chauffeur/tests/test_pwa_myday_live.py` (`open_review_card` expectation: `PwaNav.depth() == 1` and the Chores screen; the review card's route is `pwaOpenNeed` → `pwaOpenHouseScreen('chores', 'check')`), `chauffeur/tests/test_project_sheets_phone_live.py:170-171` (reads `data-section === 'lists'` after `phoneOpenList` — keep green; `phoneOpenList` now pushes the Lists screen and mirrors the section).

**Interfaces:** profiles `parent` (d1), `adult` (d2), `keeping` (keeping_up preset: lists.shopping none, household_tasks none → no Lists, no Tasks card), `lists_only` (an adult with `scope.overrides = {'chores.board': 'none'}` and a shared list → one card), `helper` (no Household tab). Mocks: the adult-shell chores/points/rewards/redemptions; `**/api/shopping/lists` two lists (`Groceries` open_count 12 default, `Costco` 4) and items; `**/api/shopping/runs` `{next: <tomorrow>}`; `**/api/household-tasks` two rows (one `past_due`, one due in 3 days, `assigned_to_name` null) and POST/complete recorders; `**/api/projects` two rows (one `active` lane `needs_you` owner parent, one `paused`), `**/api/projects/elsewhere` `[]`, `**/api/members` the seeded members; `**/api/programs` one active with `member_id` adult; `**/api/practice-windows*` one window tomorrow 16:30; `**/api/situations?*` with `kinds=finding,insight,thread` → one thread in group `now` for the parent; `**/api/threads/*/note` recorder.

- [ ] **Step 1: Write the test** with scenarios: `cards_in_need_order` (parent: five cards present, `.pwa-house-card` order equals `pwaHouseholdCards(...)` evaluated in the page, the lead text equals `pwaHouseholdLead`, the chores card's hot pill "1 to check", the tasks card's hot pill "1 overdue", the lists card's "Shop day tomorrow", the projects card has two faces); `chores_screen_segments` (tap Chores → `PwaNav.depth() == 1`, `.pwa-screen h1` 'Chores', `document.activeElement` is the h1, `#pwa-covered` inert, segments Mine / Open / To check · 1, "To check" shows `✓ Verify` and no Claim, "Open" shows Claim and no Verify, "Mine" shows Mark done; verify from To check → POST recorded, segment count drops, Back → the chores card's hot pill is gone and `#tab-chores-badge` hidden); `rewards_screen` (balances chips, a family goal bar, the pending redemption row with Grant, grant → POST); `tasks_screen` (rows with overdue first, complete → POST `/api/household-tasks/<id>/complete`, the row leaves, the card line updates on Back; Add → POST with title); `lists_screen` (two list chips, check an item → PATCH, add → POST, "N in the cart"); `projects_screen` (segments Projects / Programs; Projects shows `[data-project-card]` from the adopted `#projects-container`; Programs shows the program card and "Open the session" for the next window); `back_and_reload` (push Chores, `page.reload()` → lands on the Household cards with `PwaNav.depth() == 0`, `page.go_back()` → still the cards, no `#pwa-stack .pwa-screen`); `lists_only_member` (one card, Lists, works); `keeping_up_cards` (no Tasks, no Lists; Chores/Rewards/Projects present); `threads_live_on_plan` (parent: Plan shows `#house-threads` with the thread and a note form; My Day pile has a `thread` card that opens Plan at the lane); `household_task_due_today` (My Day pile shows the overdue task; opening it pushes the Tasks screen; completing it removes it from the pile on return); `widths_and_dark` + screenshots `household-cards-light.png`, `household-cards-dark.png`, `household-chores-check.png`, `household-tasks.png`, `household-lists.png`, `household-projects.png`, `household-360.png`; `served.errors()` empty per profile.
- [ ] **Step 2: Run** `python tests/test_pwa_household_live.py` → FAIL at `.pwa-house-card` missing.
- [ ] **Step 3: After Task 5, run** it and the adjusted tests → green.

---

### Task 5: The Household view: cards, pushed screens, adoption, segments

**Files:**
- Modify: `chauffeur/static/pwa_household.js` (add `pwaRenderHousehold()`, `pwaOpenHouseScreen(id, segment?)`, `pwaHouseSegment(id, segment)`, the adoption helpers), `chauffeur/static/pwa_shell.js` (`pwaRenderHouseTabs` for adults renders the cards instead of the section tabs; `pwaSelectHouse(section)` becomes a compatibility shim that opens the matching screen: `tasks|reviews → chores (segment mine|check)`, `lists → lists`; the More route "Household" unchanged), `chauffeur/templates/app.html` (`#chores-container` gains a `#house-cards` host before `#chores-content`; the view containers' common parent gets `id="pwa-covered"` (everything except the tab bar and `#pwa-stack`); `renderChores` stamps `data-chore-group="mine|open|check"` and `data-reward-group="balances|goals|redemptions"` wrappers for adults; `setView('chores')` fetches chores, lists, household tasks, projects summary (`api/projects`) and programs, then `pwaRenderHousehold()`; `phoneOpenList` → `pwaOpenHouseScreen('lists')`), `chauffeur/static/pwa_shell.css` (the card and screen skin), `chauffeur/static/pwa_myday.js` (`pwaOpenNeed` handles `open.screen`)
- Test: Task 4's live test and adjustments; `tests/test_pwa_household_cards.py`, `test_pwa_nav.py`, `test_pwa_needs_you.py`, `test_chores.py`, `test_projects_parity.py`, `test_template_js.py` stay green

**Interfaces:**
- `pwaRenderHousehold()`: paints into `#house-cards`: `<h1 class="pwa-house-title">Household</h1>`, `<p class="pwa-house-lead">`, then one `<button class="pwa-house-card" data-card="<id>">` per card: `.pwa-house-icon` (44 px tile, white, soft shadow), `.pwa-house-t1` title + chevron, `.pwa-house-t2` line, `.pwa-house-pills` (`.pwa-pill`, `.pwa-pill.hot`, `.pwa-pill.ok`), `.pwa-house-faces` (`presenceCircle(m, 'w-6 h-6 text-xs')` per face), `.pwa-house-bar > i` when `progress` is a number. `#chores-content`, `#house-lists`, `#house-threads` stay in the DOM but hidden on the cards view (`#chores-container[data-house="cards"]`). Repaint after every refetch (`fetchChores`, `fetchHouseLists`, `fetchHouseholdTasks`) while `currentView === 'chores'`.
- `pwaOpenHouseScreen(id, segment)`: `PwaNav.push({ id: 'house-' + id, title, render(body) { lead; segments; adopt }, onPop() { return the node; mirror section back } })`. Adoption: `chores` and `rewards` adopt `#chores-content` (moving the node) and set `#chores-content.dataset.houseScreen = id`; CSS shows only `[data-chore-group]` wrappers on `chores` (segments `mine` → `data-chore-group="mine"`, `open` → `open`, `check` → `check` (parent only; count in the segment label)) and only `[data-reward-group]` wrappers on `rewards` (no segments); `tasks` renders `renderHouseholdTasks(body)` fresh; `lists` adopts `#house-lists`; `projects` adopts `#projects-container` (dispatching `chf-projects-open` once so the Alpine page loads) under segment "Projects" and appends `renderProgramsSection(programs, commitmentsById)` under "Programs" (the first segment with content wins by default). Every screen's lead is `pwaHouseholdLead([thatCard])`. `#chores-container.dataset.section` mirrors: `chores` → `tasks` (or `reviews` when the segment is `check`), `rewards` → `rewards`, `lists` → `lists`, `projects` → `projects`.
- Segment control: `.pwa-seg` with `.pwa-seg-item[aria-pressed]`; `pwaHouseSegment(id, segment)` flips `data-house-segment` on the screen body; the Chores default segment is `mine` when the member has claimed work, else `open`, else `check`; `pwaOpenNeed` passes `check` for reviews.
- CSS from the mockup: title 34px/700/-.03em; lead 16px muted; card = `--pwa-card`, 22px radius, 16px 18px padding, flex gap 14; icon 44px/15px radius white with `0 2px 8px rgba(31,29,43,.06)`; t1 18px/600 with the chevron faint; t2 14px muted; pills 12px/600 999px `rgba(31,29,43,.06)`, hot `#ffe6cc`/amber, ok `#dcf3e8`/green; faces 26px rings −6px overlap; bar 6px `rgba(31,29,43,.08)` with the accent fill; segment `.pwa-seg` 4px padding 14px radius `rgba(31,29,43,.05)`, item 14px/600 8px 0 11px radius, `.on` white with `0 1px 4px rgba(31,29,43,.08)`; job rows (the adopted `.pwa-chore-row`, list rows) take `--pwa-card` 18px radius, 14px 16px padding, no separators; section labels inside screens 13px/700 uppercase .08em faint. Dark through the tokens.

- [ ] **Step 1: Read Task 4's live test** and the mockup; list every selector and text.
- [ ] **Step 2: Implement** cards → screens → adoption → segments → the mirrors and shims → CSS; `python tools/build_tailwind.py`.
- [ ] **Step 3: Run** `python tests/test_pwa_household_cards.py && python tests/test_pwa_nav.py && python tests/test_pwa_needs_you.py && python tests/test_chores.py && python tests/test_projects_parity.py && python tests/test_template_js.py && python tests/test_pwa_household_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_myday_live.py && python tests/test_project_sheets_phone_live.py && python tests/test_projects_live.py` → green.

---

### Task 6: Record it, gate it, ship it

**Files:**
- Modify: `chauffeur/docs/ui_design_guide.md` (a "Household, cards then focus" bullet under the reimagined vocabulary: the card contract, adoption rule, segments, `PwaNav` focus/inert/reload, threads' home), `chauffeur/system_capabilities.md` (new top entry `v2.499.754`), `chauffeur/config.yaml` (→ `2.499.754`)

- [ ] **Step 1: Docs and version.**
- [ ] **Step 2: Gate** (from `chauffeur/`, `HA_BASE_URL` unset):

```bash
python tests/test_pwa_household_cards.py && python tests/test_pwa_nav.py && python tests/test_pwa_needs_you.py && python tests/test_household_tasks_phone.py && python tests/test_chores.py && python tests/test_projects_parity.py && python tests/test_programs_reachable.py && python tests/test_template_js.py && python tests/test_tailwind_build.py && python tests/test_auth.py && python tests/test_pwa_argyle.py && python tests/test_pwa_household_live.py && python tests/test_pwa_adult_shell_live.py && python tests/test_pwa_myday_live.py && python tests/test_pwa_argyle_live.py && python tests/test_project_sheets_phone_live.py && python tests/test_projects_live.py && python tests/test_situations_lane_live.py && python tests/test_reply_reading_live.py && python tests/test_thread_photo_live.py && python tests/test_browse_thread_live.py
```

- [ ] **Step 3: Commit** as one commit `feat(pwa): slice 3 of the reimagined PWA, Household cards then focus (v2.499.754)` and push.

---

## Sequencing calls (check these while reading)

1. **"Tasks" is the household to-do list that already exists on the server** (`household_tasks`: title, notes, due, assigned-to-or-household, open/done), which the phone never showed. The user's words were "I meant household tasks"; the inventory's "Tasks" section was the chore board under an older label. The phone gets list, complete and add this slice; edit and delete stay on the Errands & Todos page.
2. **No packing in the Lists card.** There is no packing list on the server, only the wall's packing status; slice 6 owns packing.
3. **Threads move to Plan's lane** (the spec said "as today", but today Plan's lane does not show threads: `fetchMind` reads findings and insights only). The builder, its names and its element ids survive; only the host moves, so the four thread live tests keep their contract. My Day's pile gains threads in `now`.
4. **Screens adopt the builders' nodes** (as My Day adopts the day pane) instead of re-rendering into new ids: `renderChores` and friends write by fixed id, and two copies of `#chores-content` would be a bug. Segments show one `data-chore-group` of the adopted content.
5. **The Chores screen holds "To check"; the Rewards screen holds redemptions and goals.** `renderChores` today draws redemption rows inside the parent's "Needs your OK" together with chore verifies; the `data-reward-group` wrappers let Rewards own them without a second renderer. The My Day review card for a redemption opens Rewards; for a chore, Chores › To check.
6. **Projects & programs is one screen with two segments**; the Projects segment is the Alpine projects page adopted (so the one-list rules, sheets and deep links keep working), the Programs segment is `renderProgramsSection`. More keeps Projects, Library and My programs.
7. **`PwaNav` hardening lands here** because this is the first slice that pushes screens people will reload and deep-link into: reload re-stamps the root, focus moves to the title and back to the opener, the covered view is `inert`.
8. **The covered root gets `id="pwa-covered"`** rather than an attribute per view, so `inert` is one toggle; the tab bar and `#pwa-stack` sit outside it.
