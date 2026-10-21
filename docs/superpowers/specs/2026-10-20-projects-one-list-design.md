# Projects: one list — design

**Date:** 2026-10-20. **Status:** rev 2, Codex adversarial review of rev 1 folded (13 findings on this spec, §11), for the user's review. **Builds on:** `2026-10-15-projects-core-design.md` (the record, steps, holds), `2026-10-15-projects-front-door-design.md` (chat creates the project, pieces, record sheets), `2026-10-16-project-audiences-shared-model-design.md`, `2026-10-16-project-access-rule-design.md`, `2026-10-18-projects-delete-design.md`. **Sibling:** `2026-10-20-programs-brief-and-course-design.md` (the program sheet and library page; this spec only places a program's rows in the project list). **Changes nothing** in access, audiences, deletion, holds, the plan engine or any API shape except where §6 says so.

## Problem

The user, 2026-10-20: "There are so many buttons and it feels very unintuitive to me. I would like to see what can be done to make it appear simple and familiar."

The audit (rendered with the live fixtures) found the admin project detail page draws about 37 tappable controls at rest for a project with three steps and three pieces: a Change button on the audience line, per step Tick / Put it on the calendar / Clear time / Skip / Stop, Add a step, then every thread or mission piece card drawn with its seven situation verbs (Draft a message, Change the next step, Look something up, Link to something in Chauffeur, Done with it, I'll handle it myself, Drop it) plus underlined Open and Delete, then Add a piece, then Plan it with Argyle / Pause / Done / Drop / Delete. Five button styles draw the same idea. The vocabulary is the engineering model's (Pieces, Tick, `waiting_user`, Needs a plan, Your work elsewhere), and Add a piece asks the person to choose among thread, mission and program before anything exists. The list page runs four status systems at once (lanes, a state chip repeating the lane, a Programs filter, Show closed), and the New project accordion stays pinned above the detail view.

The user manages projects on the admin page in a dedicated session and creates them from the Argyle chat on the phone. The admin page is the surface to rebuild; the phone keeps the shared builder.

## Decisions (the user's, 2026-10-20, from the mockups in `.superpowers/brainstorm/56101-*/content/`)

1. **One list.** A project's detail is one list of rows, grouped Now / Next / Later / Logbook, not a steps list plus a pieces list. Chosen over three sections (Next up, Checklist, Attached) because one scan answers "what is next for this project" across people, Argyle and programs.
2. **Every row has a checkbox.** The checkbox completes the row's *next moment*, never the record behind it. A step: done. A conversation row: its next step is done, and the conversation asks for the next one. A program row: that session logged. Argyle's rows cannot be ticked; they fill themselves. Closing a conversation or finishing a program stays in that record's sheet.
3. **Four checkbox states:** open (yours to tick), done (ticked, or filled by Argyle; sinks to the Logbook), Argyle's (dashed, spinning, fills itself), not yet (a future session, a paused program, a row with no next step; the subtitle says why; tapping the text acts). Rev 2 adds a fifth for a question Argyle is asking: **asking** (dashed box, the ask's own buttons on the row; §1.3).
4. **One ⋯ menu per project** holds what used to be a row of buttons: Plan it with Argyle, Who sees it, Pause / Resume, Mark done, Drop, Delete. The ⋯ opens the existing `promptChoice` sheet the music widget and board tiles already use; no new pattern.
5. **One + Add** replaces Add a step and Add a piece. It opens one sheet with five kinds: Step, Conversation, Ask Argyle, Program, Something already in Chauffeur. The thread and mission forms behind it are today's (`project_piece_forms.html`); the program kind opens the sibling spec's setup sheet.
6. **The record's own verbs live in its sheet.** The seven situation verbs on a thread or mission card, Open the lesson on a program, Skip and Stop on an Argyle step: all reachable from the row's sheet, none on the list row. Nothing a person can do is removed; it is one tap deeper.
7. **Progress bar counts steps only.** `steps_done` of `steps_total` (the overview row's existing fields); attached records never count. The programs arc's "no 3 of 12" rule is about a program's curriculum and stands.
8. **Admin first, phone shares.** The same `projects_page.html` builder draws both; the phone host loses admin links and the top-level tab per the standing rule (`pwa-projects-home-rules`), folded in as §5.

## Rulings made while folding the review (for the user to confirm or overturn)

- **R1. Link rows (a trip, an occasion, a list) have no checkbox.** They have no next moment of their own. Their › opens a small sheet: Open, Remove (the unlink the person has today). The user's rule "every row has a checkbox" is read as every row *with a next moment*.
- **R2. A blocked step keeps the parent's override.** Today a parent may complete a step whose `needs` are not met (`projects.py:635`); the step sheet carries "Complete anyway" for a parent, and the row's box reads not-yet "waiting on {step}" for everyone.
- **R3. A program row cannot be unticked.** Undoing a logged session is "Remove this session" on the session log row in the program sheet (a new `programs.remove_session`, sibling spec §5). A step unticks (reopen); a conversation unticks (restore, §2.2).
- **R4. A thread keeper may tick their own visible next action** (keepers keep every thread verb today, `access.py:286`); the keeper projection's hidden next action can never be completed from a row because the row never carries it. The rev 1 blanket 409 is withdrawn.
- **R5. The Programs lane filter is removed [confirm].** The Library page lists every program with its runners; a project card's next line already names a program.

## 1. The row model

A project detail is built from one ordered list of **rows**: `{kind, id, title, subtitle, box, when, group, moment, sheet, actions}`. `moment` is the stable identity of the row's next moment (§2.1). `actions` is the list of buttons an asking row carries (§1.3). The table is exhaustive; a record state not listed is a defect the tests catch (`test_project_rows.py` asserts every situation state, mission status, program state and step state maps to one row shape).

### 1.1 Rows by kind and state

| kind | source | state → title · box · `when` · group |
|---|---|---|
| `step` person | project step, owner ≠ argyle | `todo`, needs met: title · open · hold date, else due_date, else none · Next (dated) or Later (undated). `todo`, needs unmet: title · not-yet "waiting on {needed step}" · none · Later. `doing`: title · open · as todo · Next. `done` / `skipped`: title · done · none · Logbook. `blocked`: title · not-yet "{reason}" · none · Later. |
| `step` argyle | project step, owner = argyle | `todo` (waiting on a stage, or missions disabled): "Argyle will {goal}" · not-yet "waits for {needed step}" or "Argyle's work is switched off" · none · Later. `doing`, no question: "Argyle is {goal}" · argyle · running · Next. `doing` with `question`, or `blocked` with a question: "Argyle needs you: {question}" · asking (§1.3) · now · Now. `blocked` without a question: title · not-yet "{reason}" · none · Later. `done`: the found line (`foundLines`, first line) · done · none · Logbook. `skipped`: title · done "skipped" · Logbook. |
| `conversation` | thread piece | open thread with `next_action`: next_action · open · `next_action_at`, else today · Now if `when` ≤ today or stalled `overdue`, else Next. Open thread without `next_action`: thread title · not-yet "set a next step" · none · Later, **except** when the situation group is `now` (a mission ask forwarded onto the thread, `situations._options_thread`): then the row is asking (§1.3) · Now. `waiting` state (we wrote, they owe a reply): "Waiting on {counterparty}" · not-yet · none · Next. `done` / `dropped`: title · done · Logbook, **except** a thread whose folded mission still has an open verify or ask: asking · Now. |
| `argyle` | mission piece not folded (§1.4) | `running` / `browsing` with a stage: `next_step.label`, else goal · argyle · running · Next. `waiting_user` or any `missions.ATTENTION` status, or `verify_open`: the ask's question · asking · now · Now. `queued` / `pending` / `paused`: goal · not-yet "{status word}" · none · Later. `blocked`: goal · not-yet "{reason}" · Later. terminal (`done`, `dropped`, `failed`): goal · done · Logbook (unless `verify_open`, above). |
| `program` | program piece | `active` with a next window: "{lesson title}, {variant}" from `programs.lesson_for(run, window.date, slot_rank)` · open on the window's day (today or earlier, unlogged) / not-yet "box opens {weekday}" before it · the window's date and time · Now (today, unlogged) / Next. `active`, every window this week logged: next week's first window as above · Next. `proposed`: title · not-yet "needs approval" (child's or Argyle's proposal; `actions` carries Approve for an adult or parent) · none · Now for an approver, Later for others. `paused`: title · not-yet "paused" · none · Later. `unresolved`: "Needs a program" · not-yet · `actions` Pick a program · Later. `done` / `dropped`: title · done · Logbook. |
| `link` | trip, occasion, list, any other linked kind | title · no box (R1) · none · a **Linked** group drawn after Later and before Logbook, with the kind's glyph; › opens Open / Remove. |

### 1.2 Groups, with precedence

One group per row, decided in this order: (1) **Now** if the row is asking, or open with `when` today or earlier, or its situation group is `now`; (2) **Logbook** if the row is done; (3) **Next** if open or argyle with a dated or running `when`; (4) **Later** otherwise; `link` rows are **Linked**. An outstanding decision always outranks a terminal status (a terminal mission with an open booking verification is Now, never Logbook). Within a group: Now by `when` then step order; Next by `when` then step order; Later in step order then piece order; Logbook newest first, folded behind "Logbook · N · Show".

### 1.3 Asking rows

A row whose record is waiting on a person draws a dashed box that cannot be ticked and carries the ask's own buttons, taken from the situation options (`situations.py:246-300`) and limited to the verbs `answer`, `release`, `submit`, `verify`, `approve_plan`, `run_stage`: Answer (opens the mission sheet at the question), Use / Make new / Not now (the program choice, posted as today's `answer` with `ask: 'program_choice'`), Approve plan, Release, Submit, Verify. The buttons post to the same routes the situation card posts to today (`Situations.act`); the row never invents a text answer. A tick request on an asking row answers 405 "Argyle is waiting on you, not on a tick."

### 1.4 Folding

A mission launched from a thread of the same project folds into that thread's row under exactly today's predicates (`projects_page.html:416-429`): the thread's card and the mission's are both read in full, the mission carries its own open and Delete, and the host's thread sheet lists the thread's missions (`window.chfThreadSheetHistory`). A keeper-view thread or mission never folds; it keeps its own row. A folded mission contributes its ask to the thread row (the thread row becomes asking, §1.1).

### 1.5 Built server-side

`projects.rows(project, viewer)` returns the list. It composes from `piece_cards` (unchanged; `card.situation` supplies state, group, options and `next_step`), the steps, `programs.practice_windows` for the program rows and `programs.lesson_for` for their titles. The access rule applies as today: a keeper-view record's row carries only the keeper projection's words (`situations.py:586`), so a hidden next action is never on a row. `GET /api/projects/{id}` gains `rows` beside `steps` and `pieces` (both kept for the phone sheets and tests).

## 2. The checkbox

### 2.1 Request

`POST /api/projects/{id}/tick` with `{kind, id, moment, done, key}`:

- `moment` is the row's next-moment identity, from `rows`: step `{step_id}`; conversation `{thread_id, rev}` where `rev` is the thread's `next_action_rev` (§2.2); program `{run_id, window_date, slot_rank, lesson_id, variant_label}`.
- `key` is a client idempotency key (uuid). The server stores `(project_id, key) → result` for 24 h and returns the stored result for a repeat.
- The server verifies, under the mutation lock: the actor is signed in; the record is a piece of this project (or a step of it); the actor passes the record's own write gate (`record_actable(kind, row, actor, verb)` with verb `edit` for steps and threads, and `_program_permission_or_refuse`'s rule for programs: own run, else parent or adult stand-in); and the `moment` still matches the record (step still `todo`/`doing`; thread `next_action_rev` equal; program window still unlogged and `lesson_for` still resolves the same lesson id and variant). A mismatch answers 409 "That changed; look again." and the refreshed rows.

### 2.2 Dispatch

- **step**, `done: true` → `projects.set_step_state(…, 'done')`; `done: false` → `set_step_state(…, 'todo')` (today's reopen, `projects.py:620`). A parent completing a blocked step passes `override: true` from the step sheet's Complete anyway; the row's box never sends it.
- **conversation**, `done: true` → new `threads.complete_next_action(thread_id, rev, who)`: inside one transaction, checks `next_action_rev == rev`, appends a `completed` history entry carrying the action and its date, clears `next_action` / `next_action_at`, bumps `next_action_rev`, and returns the entry id. The page then opens `promptInput("What's next with {counterparty}?")`; a non-empty answer calls today's `threads.advance` (which logs it; the route is `/advance`), an empty answer leaves the row at not-yet "set a next step". `done: false` → `threads.restore_next_action(thread_id, entry_id)`: restores the action and date from that history entry only while `next_action` is still empty and the entry is the latest `completed`; otherwise 409. The PATCH route's exclusion of `next_action` stands (`main.py:7411`); these two are the only new writers and both log.
- **program**, `done: true` → `programs.log_session(run_id, source='ticked', slot_date=window_date, lesson_id, variant_label)` after the server's own today-or-earlier check on `window_date` (the v2.499.630 rule: a future window is Start, never Done; `log_session` itself allows ahead-of-window logging for Start and keeps doing so). `done: false` → 405 (R3).
- **argyle rows and asking rows** → 405 "Argyle fills this one in." / "Argyle is waiting on you, not on a tick."

### 2.3 Drafting from a completed next action

A mission drafting a message captures the thread's next action before its model call (`threads.py:102`). `draft_message` and the mission's finishing write gain the thread's `next_action_rev` at capture; when the draft lands and the revision has moved, the draft is still posted (it is only a proposal) but its history entry says "drafted against an earlier next step", and the mission's completion never writes `next_action` over a newer one (the `advance` it would make is skipped and noted). (Codex 10.)

## 3. The detail page

Top to bottom, admin host:

1. Header: title, one muted line "Owner · audience label · done when", ⋯ at the right. The audience Change button is gone; "Who sees it" in ⋯ opens the audience sheet. Goal under the title only when it differs from the title.
2. Progress bar: steps done of steps total, hidden when there are no steps.
3. Now / Next / Later / Linked / Logbook as §1. A row is one `rounded-lg` panel row, box left, title and subtitle, `when` right; asking rows carry their buttons under the subtitle. Tapping the title opens the row's sheet: the record sheet for a thread, mission or program; the **step sheet** (new, framed like the record sheet) for a step, holding the step's existing controls: owner, due, Put it on the calendar / Clear time / Keep this time / Pick another time, Skip / Stop for Argyle's, Complete anyway for a parent on a blocked step, Remove step; and the **link sheet** (Open, Remove) for a `link` row.
4. One `+ Add` button.
5. No New project accordion on the detail; the back link stays.

"Pick another time" stays the typed `YYYY-MM-DD HH:MM HH:MM` prompt (§9).

## 4. The list page

- One `+ New project` button opening a sheet with today's create form (same fields; the audience picker inline).
- One list of project cards, grouped **Needs you** (today's `needs_you` lane) then **Everything else** (moving, waiting and paused together; paused rows say "paused" in the subtitle), then **Done & dropped** behind Show closed as today. The state chip goes; the card's second line is the owner and the lane's word.
- The Programs filter is removed (R5, [confirm]).
- **Your work elsewhere stays**, renamed "Argyle work you started elsewhere", drawn as `argyle` rows under its own heading.

## 5. The phone

The shared builder draws the same rows; host differences are presentation only:

- The Projects bottom tab is removed; Projects is reached from More. Live tests that click `#tab-projects` move to the More path.
- `link` rows and `project_links.js` "Part of" lines open PWA homes, never admin pages.
- **The situation card builder gets phone navigation callbacks** (Codex 13): `Situations.cardHtml` and the phone piece sheets (`app.html:2024`) take `ctx.navigate(kind, id)`; on the phone every About / subject / handoff anchor (`situations.js:94`) becomes a button calling it, landing on the record's phone sheet or view. `test_project_sheets_phone_live.py` opens each piece sheet and asserts no `<a href>` to an admin path.
- The kid shell draws the same list; a child's ⋯ holds only what `can_act` allows.

## 6. API and data changes

- New: `rows` on `GET /api/projects/{id}`; `POST /api/projects/{id}/tick`; `threads.complete_next_action` / `restore_next_action` and `next_action_rev` on the thread row (migration sets 0); `completed` thread history entries; `draft_message` carrying the revision; the step sheet's `override` on `set_step_state` for parents.
- Unchanged: `steps`, `pieces`, `/pieces`, `/steps/*`, `/state`, `/plan`, the thread PATCH exclusions, every situation route.
- Access: the tick route is registered in `access_readers.READERS` with kinds `('project', 'thread', 'mission', 'program')`; authorization is the record's own gate as §2.1 says, not registration. A child's tick on a sibling's program run inside a project they may edit is refused by `_program_permission_or_refuse`'s rule (not their run, not a parent or adult). No access matrix cell changes; `test_access_matrix` gains tick probes for the thread-keeper, child and id-less readers.

## 7. Vocabulary

| today | now |
|---|---|
| Pieces | (no heading; rows) |
| Tick | checkbox |
| `active` / `waiting_user` chips | gone from cards; words in subtitles |
| Needs a plan | "Argyle hasn't planned this yet" subtitle, and Plan it with Argyle in ⋯ |
| Your work elsewhere | Argyle work you started elsewhere |
| Add a step / Add a piece | + Add |
| Open (underlined) | tap the row |
| Done (project) | Mark done (in ⋯) |

## 8. Tests

- `tests/test_project_rows.py`: `projects.rows` over the `project_sheets_fixture` plus added records for every state in §1.1 (asserted exhaustive: a parametrised test over every situation state, mission status in `missions.LIVE ∪ ATTENTION ∪ terminal`, program state, step state and owner); group precedence (terminal mission with `verify_open` is Now; stalled thread without next action is Now only via its situation); folding predicates; keeper-view redaction; link rows in Linked.
- `tests/test_project_rows_tick.py`: every kind through the TestClient: idempotency key replay; stale `moment` 409 (step already done, thread rev moved, program window logged, lesson moved); the future-window refusal; the argyle and asking 405s; conversation complete → prompt → advance, and restore only while empty and latest; the parent override on a blocked step and its refusal for a non-parent; a child ticking a sibling's run refused; a keeper ticking their own visible next action allowed, a hidden one impossible (not on the row); two concurrent program ticks log one session.
- `tests/test_thread_next_action_rev.py`: `complete_next_action` / `restore_next_action` revision rules; `draft_message` landing after a completion is marked and never overwrites the successor.
- `tests/test_projects_detail_live.py` (rewritten): buttons at rest ≤ rows + 3 (⋯, + Add, back) + asking rows' buttons; ⋯ six items; + Add five kinds; row tap opens the right sheet (record / step / link); Logbook folds; screenshots.
- `tests/test_project_sheets_phone_live.py`, `test_pwa_adult_shell_live.py`: More path, no `#tab-projects`, no admin anchor in the projects surface or any opened piece sheet.
- `tests/test_projects_parity.py` extended: every verb of the front-door inventory reachable from a row's sheet, the step sheet or ⋯ (the never-drop guard), including Remove on a link.

## 9. Not in this spec

- The step sheet's time picker stays typed text.
- The programs sheet, library page and setup are the sibling spec.
- The Argyle chat card for a new project is unchanged.

## 10. Build split

Claude: tests first (§8), `projects.rows`, the detail and list templates, the step and link sheets, the phone host changes incl. the situation navigation callbacks, the capabilities doc. Codex: the tick route (identity check, idempotency, dispatch, access registration), `threads.complete_next_action` / `restore_next_action` / `next_action_rev` and the draft revision carry, the live test rewrites. Claude reviews every Codex task; Codex reviews the whole branch at the end.

## 11. Codex review of rev 1, folded

1 Remove on links → R1, §3 link sheet. 2 parent override → R2, §2.2. 3 exhaustive rows → §1.1 table and the parametrised test. 4 precedence → §1.2. 5 folding predicates → §1.4. 6 asking rows → §1.3 and the fifth state. 7 moment identity and idempotency, today-or-earlier in the wrapper → §2.1, §2.2. 8 `threads.update` did not exist; undo record → §2.2 new functions, history entry with the date, revision check. 9 untick per kind → R3, §2.2. 10 drafting against a cleared action → §2.3. 11 authorization → §2.1 (record gates, project membership, lock). 12 keeper refusal withdrawn → R4. 13 phone situation anchors → §5 callbacks and the piece-sheet test.
