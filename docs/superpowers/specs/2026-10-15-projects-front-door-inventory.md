# Projects front door — parity inventory (input to the spec)

**Date:** 2026-10-15. **Status:** WORKING NOTE, not a spec. Collected before writing the "Projects front door" spec so the Threads, Missions and Programs pages can retire without losing anything a person can do. The spec is the next step (see `projects-arc` memory: direction change 2026-10-15).

## The user's direction (2026-10-15)

- "I am expecting a project proposal for pretty much everything and then programs, threads, missions fall out of that." "Anything that falls under threads, missions, or programs should be a project ... One concept. One place to look. Simple." Direct actions ("assign Grandma to drive Barney to soccer tomorrow") stay instant.
- In chat, the project card comes first; Argyle then plans inside the project.
- Existing open threads, live missions and active programs are wrapped, one project each.
- One Projects page (overview) opens a project detail page (like Trips -> Trip) with its pieces as cards; a piece opens in a sheet (admin: settings-sheet style; phone: action sheet). The user invited pushback.
- Mail intake and Mind findings PROPOSE a project. "Propose a program" exists only as New project -> a program if warranted.

## Claude's refinements (agreed)

- Retire Threads, Missions and Programs only after every capability below lives in a piece sheet or the Projects page's settings drawer; old links redirect to the project with the sheet open.
- A program's sheet opens full height; lessons still open in the lesson player.
- Kids' practice and session cards on Today stay where they are.
- Four slices: 1 front door (chat: project card first, then planning; start_mission_for / propose_program from chat always inside a project; New project yields a program when warranted); 2 project detail page + piece sheets at parity, then retire the three pages behind redirects and move their settings; 3 wrap existing open items (with slice 2); 4 intake and Mind propose projects.

## Root cause of the reported bug

"I want to learn Brazilian Portuguese" in chat only proposed a program: `propose_program`'s description (services/agent_tools_v2.py ~5084) cites "I want to learn guitar"; `start_mission_for` (~4956) is described for outside-world errands; the router's guidance (services/agent_router.py ~316-330) never routes a goal to a planned mission; there is no chat tool that starts a project. `tests/test_project_portuguese.py` started the mission directly, so chat routing was never exercised.

## Inventory (paths under chauffeur/)

Legend: TP = templates/components/threads_page.html, MP = missions_page.html, PP = programs_page.html, MT = mission_transcript.html, PC = programs_card.html, SJ = static/situations.js, SIT = services/situations.py, APP = templates/app.html. ACT = POST /api/situations/{kind}/{id}/act. Nothing on these pages is a sheet today; all inline cards, forms and `<details>`. Thread/mission writes are parent/adult only; program writes owner or parent; approve parent only.

### Threads (TP)
- Create (title, goal, project|vendor, owner, contact or name+email, first next action+date): TP:35-81 -> POST /api/threads.
- Lanes Needs you now / Waiting on them / Moving / Closed (folded); "Show closed" (localStorage): TP:88-104, 433-441.
- Card options via ACT (SIT:234-266): set/change next step (inline form TP:464), draft a message, look something up, reply/confirm/read their reply (SIT:180), forwarded mission asks and steer (SIT:239-248), link/change/unlink About (SIT:221, SJ:134), I'll handle it / Handled, Done with it, Drop it, "Argyle got it wrong", Argyle's cached next steps (SIT:381); ask ledger said yes/no/Sent it (SJ:51) -> /api/asks/{id}/answer|sent|withdraw.
- Details (TP:115-196): goal/next/counterparty/owner/kind; history with photos and "Argyle read it as…"; missions opened from the thread with transcripts (GET /api/threads/{id}/missions); Draft email -> POST /draft, edit, Send (confirm) -> POST /send, Redraft; Add note -> /note; Advance -> /advance; Research -> /research (answer + sources); Photo -> /photo; Work this -> POST /api/missions/launch {origin_kind:'thread'}; Edit (title/goal/kind/owner/contact) -> PATCH; Done/Drop -> /close; Delete (cascades missions) -> DELETE.
- No reopen; no bulk actions.

### Missions (MP, MT)
- Launch goal + tier Pro|Flash: MP:164-180 -> POST /api/missions/launch.
- Lanes Needs you / Running / History (60): MP:410-417; polls 15 s; plan stepper MP:196.
- Card options (SIT:269-366): plan Looks good / Stop / Leave out; stage Do this / Carry on / Not this one / Stop / Leave out row; Skip/Stop while running; Share / Not these / Stop; Book it / I'll finish it myself / Stop; It went through / did not / Still can't tell; answer a question; Tell it something; proposal Approve; About link; I'll handle it / Handled; Drop.
- Details MP:203-250: tier/started/finished/error; transcript; answer/steer box -> /answer; Drop; OK ack -> /ack; Delete.
- Transcript (MT, static/mission_transcript.js): proposal Approve/Dismiss; release, submit, verify with confirmation text; browse report, last screenshot, per-turn shots (GET /api/missions/{id}/shots/{name}); handoff Open it; draft read-only; raw JSON.
- Interview "Send answers" exists only in the phone chat card (APP:5326).

### Programs (PP)
- Propose (aim, for whom, starting point, sessions/week, minutes, preferred days, target date): PP:182-248 -> POST /api/programs.
- Shelf Proposed / Under way / Done & dropped: PP:251-266; Part of project (PP:276, static/project_links.js).
- Plan source tier, Why this one / Also considered, progress, phase steps/rotation, Next time, Done when, lesson ladder with Open the lesson: PP:283-604.
- Tonight windows + Start session (GET /api/practice-windows, GET /lesson); finishing logs -> POST /session {source:'asked'}.
- Lesson editor (PP:428-557): play, edit say/do/check beats, reorder, delete, add (max 12), Save -> PUT /lesson, Regenerate -> DELETE /lesson.
- Ladder Another session / Move on -> POST /unit; milestone Reached it -> /milestone.
- Footprint (PP:617-703): slots and "Not these times?" editor -> /edit {slots}; kit thread and calendar target; Plan without the book -> /edit {recurate, exclude_books}; Approve — claim this time -> /approve.
- Proposal row: Edit -> /edit; Look again -> /edit {recurate}; Dismiss -> /drop.
- Active/paused: Log a session -> /session {source:'added'}; Pause; Resume; Finished; Re-shape the week; Drop.
- "Write lessons now" sweep with per-slot Play -> POST /api/programs/lessons/sweep.

### Phone surfaces outside the admin pages (APP)
- House tab Threads (own threads; APP:6478-6506): card options via ACT, Add note, Add a photo; anchor count APP:6364; adult tab static/pwa_shell.js:420, child tab static/pwa_child_shell.js:225.
- Programs: My Day / Drives Today rows (APP:1644), program card (APP:1473-1600: Coming up, Yes it happened, Did it happen?, Add a session, Reached it, Open the lesson), session sheet (APP:1925: Done, Start -> lesson player), Family tab practice cards (APP:9225), More > My programs (pwa_shell.js:114; child pwa_child_shell.js:213). No propose/approve/edit/pause/lesson-edit/sweep on the phone. renderPracticeNow (APP:2083) is built but never rendered.
- Mission chat cards (APP:5285-5437): mission_ask with situation options, interview form + You decide + Send answers (POST /plan/answers), plan/stage/release/submit details, handoff Open it; mission_done Copy/Share drafts; action-proposal cards.
- Projects tab embeds components/projects_page.html (APP:442) with Conversations and Plan it with Argyle.

### Wall, panel and house
- Programs board tile (board_tile_body.html:480 + PC; services/home_board.py:2027): Practice today + Start session, Coming up, This week, Just reached. No page link.
- House living-room program book (house_life.html:24, house_books.html:37-62, static/house_books.js); Study Programs binder (static/house_study_surfaces.js:87-96: Log practice, Pause/Resume, Milestone); Study pins show threads read-only (house_study_surfaces.js:113, services/study.py:72).
- Wall/calendar practice dialog Start session (family_calendar.html:1228,1283). No thread or mission board tiles.

### Settings drawers (POST /api/settings; registry services/settings_registry.py:658-760)
- Threads 'threads' / threads-settings: thread_stall_days.
- Missions 'missions': missions-settings (missions_enabled, llm_gemini_paid_api_key + Remove, model_pool_pro, mission_cap_launch, mission_step_cap, mission_cap_pro_calls, thread_cap_photo_reads); browse (missions_submit_enabled, missions_captcha_attempts, mission_cap_browse_turns, Check the network -> GET /api/browse/netcheck); contact-card (contact_first_name … contact_preferred).
- Programs 'programs': programs-settings (programs_enabled, programs_generate_enabled); lessons (program_lessons_enabled, lesson_help_daily_cap, Write lessons now); programs-pacing (programs_ask_grace_hours, programs_rebaseline_days, programs_rebaseline_cooldown_days, programs_research_pages).

### Deep links into these pages
- Nav: templates/nav.html:129 (rhythms?tab=programs), :134 (work?tab=threads), :135 (work?tab=missions); page routes main.py:1769, 1810, 1816, 1867, 1871; kiosk hide list nav.html:734.
- projects_page.html:81 and :123 link `missions?id=` / `threads?id=`, but none of TP, MP, PP reads `?id=` today (the id is ignored) — the key gap for sheets.
- Pieces and the About chip use subjects.link: thread -> `threads`, program -> `programs`, no id (services/subjects.py:661,671; SJ:104).
- occasions.html:133 and trip.html:1120 "Argyle: …" lines link to `threads` with no id.
- Settings index anchors (work?tab=missions#…, work?tab=threads#…, rhythms?tab=programs#…).
- static/study.js:147,636 point to `/programs`; plain-text "/missions" mentions in services/watchers.py:463,473.
