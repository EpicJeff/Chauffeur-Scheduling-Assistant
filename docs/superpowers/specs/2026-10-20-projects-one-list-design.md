# Projects: one list — design

**Date:** 2026-10-20. **Status:** rev 1, for the Codex adversarial review, then the user's review. **Builds on:** `2026-10-15-projects-core-design.md` (the record, steps, holds), `2026-10-15-projects-front-door-design.md` (chat creates the project, pieces, record sheets), `2026-10-16-project-audiences-shared-model-design.md`, `2026-10-18-projects-delete-design.md`. **Sibling:** `2026-10-20-programs-brief-and-course-design.md` (the program sheet and library page; this spec only places a program's rows in the project list). **Changes nothing** in access, audiences, deletion, holds, the plan engine or any API shape except where §6 says so.

## Problem

The user, 2026-10-20: "There are so many buttons and it feels very unintuitive to me. I would like to see what can be done to make it appear simple and familiar."

The audit (rendered with the live fixtures) found the admin project detail page draws about 37 tappable controls at rest for a project with three steps and three pieces: a Change button on the audience line, per step Tick / Put it on the calendar / Clear time / Skip / Stop, Add a step, then every thread or mission piece card drawn with its seven situation verbs (Draft a message, Change the next step, Look something up, Link to something in Chauffeur, Done with it, I'll handle it myself, Drop it) plus underlined Open and Delete, then Add a piece, then Plan it with Argyle / Pause / Done / Drop / Delete. Five button styles draw the same idea (solid grey, teal underline, blue underline, red underline, red bordered). The vocabulary is the engineering model's (Pieces, Tick, `waiting_user`, Needs a plan, Your work elsewhere), and Add a piece asks the person to choose among thread, mission and program before anything exists. The list page runs four status systems at once (lanes, a state chip repeating the lane, a Programs filter, Show closed), and the New project accordion stays pinned above the detail view.

The user manages projects on the admin page in a dedicated session and creates them from the Argyle chat on the phone. The admin page is therefore the surface to rebuild; the phone keeps the shared builder.

## Decisions (the user's, 2026-10-20, from the mockups in `.superpowers/brainstorm/56101-*/content/`)

1. **One list.** A project's detail is one list of rows, grouped Now / Next / Later / Logbook, not a steps list plus a pieces list. Chosen over "three sections" (Next up, Checklist, Attached) because one scan answers "what is next for this project" across people, Argyle and programs.
2. **Every row has a checkbox.** The checkbox completes the row's *next moment*, never the record behind it. A step: done. A conversation row: its next step is done, and the conversation asks for the next one. A program row: that session logged. Argyle's rows cannot be ticked; they fill themselves. Closing a conversation or finishing a program stays in that record's sheet.
3. **Four checkbox states:** open (yours to tick), done (ticked, or filled by Argyle; sinks to the Logbook), Argyle's (dashed, spinning, fills itself), not yet (a future session, a paused program, a row with no next step; the subtitle says why; tapping the text acts).
4. **One ⋯ menu per project** holds what used to be a row of buttons: Plan it with Argyle, Who sees it, Pause / Resume, Mark done, Drop, Delete. The ⋯ opens the existing `promptChoice` sheet the music widget and board tiles already use; no new pattern.
5. **One + Add** replaces Add a step and Add a piece. It opens one sheet with five kinds: Step, Conversation, Ask Argyle, Program, Something already in Chauffeur. The three forms behind it are today's forms (`project_piece_forms.html`), unchanged in fields.
6. **The record's own verbs live in its sheet.** The seven situation verbs on a thread or mission card, Open the lesson on a program, Skip and Stop on an Argyle step: all reachable from the row's sheet, none on the list row. Nothing a person can do is removed; it is one tap deeper.
7. **Progress bar counts steps only.** Attached records never count. The bar is "4 of 10 done" over the project's own steps, which the core spec already exposes as `steps_done` / `steps_total`. (The programs arc's "no 3 of 12" rule is about a *program's* progress and stands; a project's own checklist count is the user's existing `steps_done of steps_total` line.)
8. **Admin first, phone shares.** The same `projects_page.html` builder draws both; the phone host loses admin links and the top-level tab per the standing rule (`pwa-projects-home-rules`), which this spec folds in as §5.

## 1. The row model

A project detail is built from one ordered list of **rows**. A row is `{kind, id, title, subtitle, box, when, group, sheet, record}`:

| kind | one row per | title | box | `when` (next moment) |
|---|---|---|---|---|
| `step` (person) | project step not owned by Argyle | step title | open / done / not-yet(blocked by `needs`) | hold window date, else due_date, else none |
| `step` (Argyle) | project step owned by Argyle | "Argyle is {goal}" while doing; the found line when done; "Argyle needs you: {question}" when asking | argyle (dashed), done, or not-yet (blocked, `reason`) | now when asking; running while doing |
| `conversation` | thread piece | the thread's `next_action`, else the thread title | open when `next_action` is set; not-yet "set a next step" otherwise; done never (a done thread sinks to the Logbook as its own row) | `next_action_at`, else today |
| `argyle` | mission piece not folded into a thread | the mission's situation `next_step.label`, else its goal | argyle while running; open with an Answer button when `waiting_user`; done when closed | now when waiting; running |
| `program` | program piece | "{current lesson title}, {variant label}" | open on the day of its next window; not-yet before it ("box opens Thursday"); not-yet "paused" / "needs a program" (unresolved) | the next practice window's date and time |
| `link` | trip, occasion, list or other linked kind | the record's title | none (no box: the row is a link to its own page, drawn with the kind's glyph) | none |

**Grouping.** `now`: anything whose box is open with `when` today or earlier, every Argyle question, and any situation in the `now` group. `next`: open or argyle rows with a future or running `when`, ordered by `when` then by step order. `later`: not-yet rows and undated open steps, in step order, drawn at 60% opacity. `logbook`: done rows and closed records (done or dropped threads, closed missions, finished or dropped programs), newest first, folded behind "Logbook · N · Show" (the Show closed toggle moves here on the detail; the list page keeps its own, §4).

**The row's subtitle** names the record and the owner in plain words: "Ace Tile · conversation", "Dad · on the calendar", "Strength basics · program", "Ivory matte so far". It never shows a state code.

**Folding stands.** A mission launched from a thread of the same project still folds into that thread (delete spec §7): it contributes no row of its own; the thread row's `when` becomes the mission's when the mission is asking.

**Built server-side.** `projects.rows(project, viewer)` returns the list; it composes from `piece_cards` (unchanged), the steps, `programs.practice_windows` for the program rows and the situation projection for thread and mission rows. The access rule applies as today: a row for a record the viewer sees at keeper view carries only the keeper projection's words. `GET /api/projects/{id}` gains `rows` beside `steps` and `pieces` (both kept for the phone sheets and tests).

## 2. The checkbox

`POST /api/projects/{id}/rows/{kind}/{rid}/tick` with `{done: true|false}` dispatches per kind and returns the refreshed rows:

- step → `projects.set_step_state` (`done` / `todo`), exactly today's Tick.
- conversation → clears the thread's `next_action` and `next_action_at` through `threads.update` and opens `promptInput("What's next with Ace Tile?")`; an empty answer leaves the row at not-yet "set a next step". Unticking restores the previous next action (kept on the thread as `last_next_action`, a new field, cleared on the next set).
- program → `programs.log_session` with `source: 'ticked'`, `slot_date` = the window's date, today-or-earlier only (the v2.499.630 rule); a tap on a future row's text opens the session sheet / lesson player as Start, exactly today's Start.
- argyle rows → 405 "Argyle fills this one in." The Answer button on an asking row opens the mission sheet at its question, as "Open Argyle's work and answer" does today.

Every tick asks nothing except the conversation's "what's next" prompt. Deleting, dropping, skipping and stopping stay behind confirms in the sheets, as today.

## 3. The detail page

Top to bottom, admin host:

1. Header: title, one muted line "Owner · audience label · done when", ⋯ at the right. The audience line's Change button is gone; "Who sees it" in ⋯ opens the audience sheet. Goal shows under the title only when it differs from the title.
2. Progress bar: steps done over steps total, hidden when there are no steps (today's rule).
3. Now / Next / Later / Logbook as §1. A row is one `rounded-lg` panel row (design guide vocabulary), checkbox left, title and subtitle, `when` right. Tapping the title opens the row's sheet (record sheet for thread / mission / program, a step sheet for steps). The step sheet is new and holds the step's existing controls: owner, due, Put it on the calendar / Clear time / Keep this time / Pick another time, Skip / Stop for Argyle's, Remove step.
4. One `+ Add` button.
5. Nothing else. No New project accordion on the detail; the back link stays ("← All projects").

"Pick another time" stays the typed `YYYY-MM-DD HH:MM HH:MM` prompt for now (unchanged; noted in §9).

## 4. The list page

- One `+ New project` button opening a sheet with today's create form (same fields; the audience picker inline). The form is no longer an accordion pinned above the lanes.
- One list of project cards, grouped **Needs you** (today's `needs_you` lane) then **Everything else** (moving, waiting and paused together, paused rows marked "paused" in the subtitle), then **Done & dropped** behind Show closed as today. The state chip on the card goes; the card's second line is the owner and the lane's word ("needs you", "moving", "waiting", "paused").
- The **Programs filter is removed [confirm]**: the Library page lists every program with its runners, and a project card already says "Learn piano" in its next line. Removing it removes a hand path to "projects with a program", so the user must confirm.
- **Your work elsewhere stays**, renamed "Argyle work you started elsewhere", drawn as `argyle` rows under its own heading, as today.

## 5. The phone

The shared builder draws the same rows; the host differences are presentation only:

- The Projects bottom tab is removed; Projects is reached from More (already registered there). The live tests that click `#tab-projects` move to the More path (`pwa-projects-home-rules`).
- `link` rows open a PWA home (the record's phone sheet or view), never an admin page; `project_links.js` "Part of" lines become buttons that open the project in the phone's Projects view.
- The phone's own piece sheets (app.html) are unchanged.
- The kid shell draws the same list; a child's project shows the ⋯ with only what `can_act` allows (today's gating).

## 6. API and data changes

- New: `GET /api/projects/{id}` returns `rows`; `POST /api/projects/{id}/rows/{kind}/{rid}/tick`; `threads.update` accepts `next_action: ''` and keeps `last_next_action`.
- Changed: nothing removed. `steps`, `pieces`, `/pieces`, `/steps/*`, `/state`, `/plan` stay as the sheets' and tests' contract.
- Access: the tick route is registered in `access_readers.READERS` with kinds `('project', 'thread', 'mission', 'program')` and refuses with the same codes as the underlying writes. A viewer at keeper view on a thread cannot tick its row (409 "That isn't yours to tick").

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

- `tests/test_project_rows.py`: `projects.rows` for the Bathroom fixture (`project_sheets_fixture`): one row per step and piece, grouping, `when` per kind, folding, keeper view redaction, unresolved program, paused program, thread without next action.
- `tests/test_project_rows_tick.py`: every kind's tick through the TestClient, including the future-session refusal, the argyle 405, the conversation prompt round trip and untick, and the access refusals (keeper view, child on a mission row).
- `tests/test_projects_detail_live.py` (rewritten scenarios): the rendered page shows exactly the row controls (count of buttons at rest ≤ rows + 3), the ⋯ opens the choice sheet with the six items, + Add opens the five kinds, a row tap opens the right sheet, the Logbook folds. Screenshots as proof (design guide).
- `tests/test_project_sheets_phone_live.py` and `test_pwa_adult_shell_live.py`: More path, no `#tab-projects`, no anchor in the projects surface.
- `tests/test_projects_parity.py` extended: every verb of the inventory reachable from a row's sheet (the parity test is the never-drop guard).

## 9. Not in this spec

- The step sheet's time picker stays typed text; a real picker is its own small slice.
- The programs sheet, library page and setup are the sibling spec.
- The Argyle chat card for a new project is unchanged.

## 10. Build split

Claude: tests first (§8), `projects.rows`, the detail and list templates, the phone host changes, the capabilities doc. Codex: the tick route and dispatch with its access registration, `threads.update` next-action handling, the step sheet, the live test rewrites. Claude reviews every Codex task; Codex adversarial-reviews this spec before any code and the whole branch at the end.
