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

## Phase K1 — Kid evening digest — SHIPPED v2.33.0 (2026-08-05)

As designed, with the delivery decision from the family (2026-08-05): **dual
delivery always, no per-kid phone config** — every child gets the Argyle DM
(push rides free for device kids; the thread waits for shared devices) AND
the same content renders as a 🌙 per-kid card strip on `/routines?kiosk=true`
(independent of routine lanes). Builder `main._build_kid_digests` reuses
member_day's ride resolution; unassigned rides omit the driver phrase
(reassurance principle — the parent watcher chases missing drivers). Kid
quiet hours are settings (`kid_quiet_start`/`kid_quiet_end`, default
20:30–07:00) via `family_digest.in_kid_quiet_hours` — the shared gate every
later kid-facing push (K2+) must use. Settings UI in Config → General.
Tests: `tests/test_kid_digest.py`.

## Phase K2 — Pickup clarity — SHIPPED v2.33.1 (2026-08-05)

Both push moments landed, with "rules of calm" refined during build:
driver-change pushes are GAINS-ONLY (a ride losing its driver never alarms
the kid — parent watchers chase unassigned) and next-48h only; the
on-the-way push fires once per event per day on the FIRST leg start (both
the PWA button and the agent start_route path); kid quiet hours SKIP rather
than defer on both (stale reassurance is worse than none — the digests
restate). Deferred to after K4 (needs school hours): the scheduled
end-of-school-day "you're getting picked up by Mom at 3:15" push.
Tests: `tests/test_kid_pushes.py`.

## Phase K3 — Kid-as-sensor — SHIPPED v2.33.2 (2026-08-05)

SHIPPED v2.33.2 (2026-08-05). Corrected assumption from this brief:
`propose_family_action` was never admin-gated (approval is the gate) — the
REAL gap was visibility: a card created in the kid's private Argyle DM never
reached the approvers. Shipped: kid-DM proposal cards mirror into the family
channel ("💡 Addison flagged this for a parent:") with the proposal re-bound
there so the approval outcome lands where parents saw it; kid-persona prompt
(propose + tell them you flagged it, ONE clarifying question max — missing
info goes in the summary as a gap, never an interrogation; no lecturing
about chores/points ever). Child Approve taps remain refused server-side.
Tests: `tests/test_kid_sensor.py`.

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

## Phase K5 — Morning launch — SHIPPED v2.35.0 (2026-08-05)

"🚀 Leave by 7:35 AM with Dad" — computed honestly from the solver's
initial edges (start − travel − driver buffer), shown atop My Day and
leading the kid digest/kiosk cards; no edge or ghost-only → no line (never
fabricate precision). K4c shipped alongside: school hours on the member +
the dismissal push ("🚗 Dad has you after school"), silent whenever
anything is unknown. THE ARC AS DESIGNED IS COMPLETE. Not built from the
original K5 sketch: spirit-week email → one-day prep-kit proposals (the
weekly watcher suggest covers kits; revisit if the family misses it).

## Sequencing & effort

K1 (small: one builder + setting) → K2a driver-change pushes (small) → K3
(prompt + tool-scope work, medium) → K2b on-the-way push (small) → K4
(new domain, its own multi-release arc like intake was) → K5 (small, after
K4's school profile exists).

Open questions — ANSWERED 2026-08-05: (1) K4 school-feed intake is worth
building regardless of this district's support (generalize; others have it);
(2) no per-kid phone tracking — dual delivery always (DM everyone + kiosk
strip), device kids simply get both; (3) kid quiet hours are config-page
settings (`kid_quiet_start`/`kid_quiet_end`), not hardcoded policy.
