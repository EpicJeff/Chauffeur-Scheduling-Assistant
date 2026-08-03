# Kid Support Arc — design brief (drafted 2026-08-03)

Goal, in the family's own words: **help the kids manage stress and be
successful.** Chauffeur currently models a kid's life as rides + chores; the
school day — most of their waking hours and most of their anxiety — is
invisible to the system. This arc makes the app work FOR the kid, not just
around them.

## Design principles (argue before violating)

1. **Reassurance over reminders.** Kid anxiety is mostly *uncertainty*: who's
   picking me up, what do I need, did I forget something. Answer those
   questions before they're asked. Never become a nag machine — the roadmap's
   routine-reminder caution applies doubly to children.
2. **One digest, not N pings.** Consolidate; time-critical pushes only for
   genuinely time-critical facts (ride en route, pickup driver).
3. **Kid agency, not surveillance.** The chore marketplace won because choice
   drives buy-in. School data belongs on the KID's surfaces (their My Day,
   their Argyle DM) with parents having visibility — never a parent dashboard
   about the kid. Explicitly out: grades monitoring. In: due dates and events.
4. **Kids are sensors, not just recipients.** They're first to know half the
   family's logistics ("coach moved practice"). Give that information a path
   in — parent-gated via the existing propose→approve cards.
5. **Calm voice.** Argyle's kid-facing copy is warm, short, and concrete.
   Celebrate effort (streak/tier rails exist); never shame a miss.

## Phase K1 — Kid evening digest (cheapest, do first)

Per child-role member with anything tomorrow, one Argyle DM at
`tomorrow_digest_time` (reuse the marker/loop): tomorrow's rides from
`/api/members/{id}/day` data (driver names resolved), prep-kit items
("bring goggles + towel"), weather line, and a routine/streak line when a
streak is live. Rails: `_send_tomorrow_digests` pattern, Argyle DMs, day API,
prep kits. New: kid-tone formatting, `kid_digest_enabled` setting.

## Phase K2 — Pickup clarity ("who's getting me?")

The single most common kid worry, and the moat answers it.
- Push to the kid when their ride's driver changes (extend the existing
  assignment-change buffer — today it notifies drivers only; map affected
  passengers → child members, kid wording: "Change: Dad is taking you to
  swim tomorrow").
- "On the way" push when the driver taps Start Drive on a leg carrying the
  kid (drive_status already flows; kid already sees a chip IF they open the
  app — push closes the gap).
- Optional later: school-day-end "You're getting picked up by Mom at 3:15"
  scheduled push per school-day (needs school-hours config from K4).

## Phase K3 — Kid-as-sensor (capture from the kid's Argyle DM)

Kid tells Argyle "practice moved to 5pm Thursday" → agent turns it into an
`action_proposal` card posted to the parents (family channel or parent DMs).
Rails: Argyle DMs already route kids to the agent with role-scoped tools;
`propose_family_action` already exists and children's approval taps are
already refused server-side. New: prompt work (kid persona: always propose,
never execute; never interrogate), plus allowing the kid-context agent to
OFFER proposals (today the bridge tools are admin-gated — the proposal tool
must be reachable without the admin toolset).

## Phase K4 — School model + homework/deadlines (the big one)

New domain: per-kid school profile (name, hours, A/B-day calendar or bell
schedule ICS) and **kid tasks with due dates** (test Friday, project
milestones, library book Thursday, $12 by Friday).
- Intake routes: check the district/platform for per-student ICS feeds first
  (Canvas/Schoology expose them — rides the EXISTING ics_sync with zero new
  code). Google Classroom API (coursework + due dates) is the build if feeds
  don't exist. Email intake `task` kind graduates from all-day 📌 events to
  real kid tasks.
- Surfaces: My Day "Due soon" section, kid digest line ("math test Friday —
  2 days away"), NOT points (school is not paid work; same reasoning as
  routines).
- Agent: milestone breakdown proposals for far-out projects ("science fair
  in 3 weeks → pick topic this weekend…") — proposals the kid accepts into
  their own task list; one LLM call, kid-approved, parent-visible.
- Scope guard: due dates and events only. No grades, no missing-assignment
  shaming.

## Phase K5 — School-rhythm prep + morning launch

- Spirit-week / picture-day / PE-day intake emails → one-day prep-kit
  proposals (extend the watcher's weekly suggest to ingested email content).
- My Day + kiosk lanes get a "leave by 7:40 with Dad" line computed from the
  solved schedule's departure times — the number exists, the person who needs
  shoes on never sees it.

## Sequencing & effort

K1 (small: one builder + setting) → K2a driver-change pushes (small) → K3
(prompt + tool-scope work, medium) → K2b on-the-way push (small) → K4
(new domain, its own multi-release arc like intake was) → K5 (small, after
K4's school profile exists).

Open questions for the family: does the district expose assignment ICS/
Classroom? Which kids get phones vs kiosk-only (kiosk-only kids need the
digest on the wall board instead of a DM)? Quiet-hours for kid pushes should
probably be stricter than parents' (nothing after ~20:30?).
