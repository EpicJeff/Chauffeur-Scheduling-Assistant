# K4 — School model + homework/deadline domain (design, 2026-08-05)

Phase K4 of the kid-support arc (`kid_support_design.md`). The school day is
the biggest invisible part of a kid's life; this phase gives it a data model
and calm surfaces. Family decision 2026-08-05: build the feed intake
generalized regardless of the local district's support.

## Non-negotiable scope guards (from the arc principles)

- **Due dates and events only. Never grades, never missing-assignment
  shaming.** A task is something the kid can act on; a grade is a judgment.
- **No points for schoolwork** (same reasoning as routines: personal duties
  are not paid work). Streak/tier mechanics deliberately NOT extended here
  either — school pressure is what we're reducing.
- **Kid-owned surfaces**: tasks live on the kid's My Day and digest, with
  parents having visibility — not a parent dashboard about the kid.
- **Overdue is worded gently** ("still open — was due Fri"), shown in place,
  never pushed. No overdue notifications, ever.

## Data model

**KidTask** (`kid_tasks` table): `id`, `member_id` (child), `title`,
`due_date` (YYYY-MM-DD), `kind` (`homework|test|project|bring|other` —
drives the emoji: 📚 📝 📐 🎒 📌), `notes`, `source`
(`manual|agent|intake|ics|classroom`), `source_ref` (feed/message id for
dedupe), `status` (`open|done`), `done_at`, `created_at`,
`created_by_member_id`. Milestones are just tasks (a broken-down project =
several tasks with staggered due dates); no parent-child task linking in v1.

**School profile** (K4c): optional `school_hours_start`/`school_hours_end`
on FamilyMember. Unblocks the deferred K2 school-day-end pickup push and
K5's morning launch. Deliberately NOT a separate school entity until a
second field family proves needed.

## Sub-phases

### K4a — the domain + surfaces + agent tools (BUILD FIRST)
Storage CRUD + REST (`/api/kid-tasks`), My Day "Due soon" section (open
tasks due within 7 days of the viewed date, plus overdue; checkbox completes
via the per-action identity pattern — owner or parent), kid digest + kiosk
task lines (due within 3 days of the digest day + overdue, gentle wording),
agent tools in BOTH stacks: `get_kid_tasks`, `add_kid_task`,
`complete_kid_task` — kids manage their OWN list directly (their list =
their agency; no approval friction for "add my math worksheet"), parents
manage any kid's, helpers refused. Kid-persona prompt: offer milestone
breakdowns for big projects (agent adds several tasks on a yes) and never
nag about overdue.

### K4b — intake (fills the domain automatically)
- **Task-mode ICS feeds**: assignment feeds (Canvas/Schoology per-student
  URLs) must NOT become calendar events — they'd pollute the driving solver.
  `ics_feeds` gains `target_kind: calendar|tasks` + `member_id`; task-mode
  sync diffs into kid_tasks (source='ics', source_ref=uid) with the same
  patch/cancel semantics. Subscribe UI on the kid's Passenger profile.
- **Email intake**: extraction gains an optional `member_task` route — a
  `task` proposal whose member guess is a child can be approved into a
  KidTask instead of an all-day 📌 calendar event (approval card gets a
  "to {kid}'s list" target option alongside calendars).
- **Google Classroom API** (coursework.due dates): the deeper build, only
  worth it where no ICS exists. OAuth per kid via the existing Google
  credential flow; sync loop like ics_sync. Explicitly excluded: grades,
  submission state.

### K4c — school hours + the pushes they unblock
Member school-hours fields + Config People UI; then the deferred K2
"you're getting picked up by Mom at 3:15" scheduled push at school-day end,
and K5's "leave by 7:40" morning line.

## Test surface
`tests/test_kid_tasks.py`: CRUD + completion identity rules, due_soon
windowing (overdue included, horizon capped), digest line wording (due
tomorrow / weekday / gentle overdue), agent-tool identity scoping (kid =
self only, parent = any, helper refused), digest inclusion for task-only
kids.
