# Needs You — design brief (drafted 2026-08-23)

The pitch this came from: the "Generation 3" family-platform musing — observe,
anticipate, decide, execute, escalate only when necessary; *"the family
shouldn't have to manage the family-management system."* Stripped of the
marketing, most of it already exists in this codebase (solver, watchers, meals,
occasions, supply intake). What does not exist is the musing's one genuinely
good idea: **the app's front door should show what couldn't be handled without
you — with a solution attached — and everything else should close itself.**

Today's watchers ([watchers.py](../services/watchers.py)) are the Anticipator
half: deterministic scans, twelve finding kinds, anti-nag guarantees. But a
finding is a DM text line with no lifecycle: it fires once, nobody knows if it
got handled, and it puts resolution back on the parent's head. The user's field
report, verbatim in spirit: *lots of "needs a look" messages that aren't
actionable — unclaimed chores aren't worth a prompt, an optional activity three
days out isn't worth thinking about, and a normal activity with no driver
should arrive with a driver, an outside hand, or an honest "we can't cover
this."* That report is the spec.

## What this brief argued out (read before relitigating)

**1. The signal policy is the feature; buttons are secondary.** Every DM-able
finding must pass three tests: time-critical, actionable, solution attached.
Fail any → it goes to the digest or a dashboard surface, never a DM. A finding
without a solution *adds* mental load, which is the exact failure mode this
system exists to remove. (Memory: `watcher-signal-policy`.)

**2. Absence is resolution — the lifecycle trick that makes this cheap.**
Watchers re-scan current state every sweep. Therefore an open finding record
whose condition no longer appears in the sweep has been handled *somewhere* —
verified on the chores page, covered by a spouse, deadline met — and the record
closes itself (`done/auto`) with zero per-kind resolution code. This is what
keeps the Needs You surface from becoming a second inbox: nobody dismisses
anything that reality already dismissed.

**3. Record identity is (kind, subject); notify keys keep their dates.**
Today's dedup keys embed dates for notification cadence
(`occasion_gap:{id}:{today}`). Records strip the date — one record per
(kind, subject) — while the existing `watcher_notified` markers stay exactly
as they are. Two concerns, two keys; the anti-nag contract is untouched.

**4. Recommendations are deterministic or absent — the sweep stays zero-LLM.**
A recommendation is attached only when it is single and certain, and it rides
the *existing* proposal machinery
([chat_actions.py](../services/chat_actions.py) — `create_action_proposal`,
`act_on_proposal`, the Approve/Dismiss card, the admin gate at the tap). One
bad auto-recommendation costs more trust than ten good ones buy. Never fake
confidence; "decide" severity with named reasons is the honest fallback.

**5. The unassigned-event ladder is the centerpiece.** The solver already
evaluated every driver; the finding must say what it learned, not just the
verdict:

- **Tier 1 — a family driver is feasible.** Feasibility from the schedule
  cache: no overlapping run ± travel buffer, no protected-time window, driver
  active. *"Jeff is free 3:00–5:00. [Assign Jeff]"* — executes
  `assign_driver_to_event_fuzzy`. Multiple candidates → propose the
  priority-ranked first, name the alternate.
- **Tier 2 — no family driver; a known outside hand has history here.**
  Candidates come from assist-assignment history for this event/kid — never a
  cold suggestion. The tap drafts a plain text and opens the native share
  sheet; the ask itself stays the parent's act (outside hands hold work:
  helps-with is a filter, never a gate).
- **Tier 3 — honest can't-cover, with named reasons.** *"Jeff: work 3–5.
  Sarah: driving Ava."* The named reasons are the value — they replace the
  mental schedule replay. They fall out of the same feasibility pass that
  ruled each driver out. Zero LLM.

**6. Tier 3's buttons must all be real.** The first draft listed "move it /
mark optional / ask someone new" — two of three were painted doors. Argued
down to:

- **[Ask someone new]** — share-sheet-first, near-zero typing (point 8).
- **[We're skipping it]** — occurrence-scoped skip. This extends the
  optional-events decision machinery (`decide_optional_event`) to *any*
  occurrence, not just flagged-optional events. Honest name — it is not
  "mark optional," it is deciding not to go this once. Recurring series
  untouched.
- **[Leave it — I'll sort it]** — dismiss; the siren stays off.
- "Move it" is **cut**: calendar-sourced events cannot be moved from the app
  and real activities mostly cannot be rescheduled at all. Listing an action
  the app cannot perform is the fake-option pattern. (Argyle can still move
  Chauffeur-owned things conversationally; that remains a chat capability,
  not a button.)

**7. The ask link is cut from the friend flow.** A signed "tap to confirm"
link is socially wrong between friends and plain weird to another team parent
— a flyer where a text belongs. The insight that survives its removal:
Chauffeur needs exactly **one bit** from the reply (yes/no). So don't try to
capture the conversation; capture the bit:

- **Rail A (ship): the ask becomes state, and Chauffeur asks *you* at the
  right moments.** Tapping [Draft ask] puts the event into
  `awaiting: {name}`. Pushes with action buttons — first nudge ~1h after the
  ask (replies come fast), then evening sweep, final at T-18h:
  *"Did the Muellers take Thursday? [Covered] [No] [Still waiting]"*. One
  lock-screen tap; sw.js credentialed actions shipped v2.383 (ride-status
  pattern). [No] or timeout resumes the ladder. Every confirm carries an
  **Undo** (lock-screen mis-taps happen).
- **Rail B (opt-in): an iOS Shortcut in the share sheet.** Web Share Target
  is Android-only — the very reason the share target was cut in v2.382 —
  but a Shortcut can receive shared text and POST it to a scoped webhook.
  Long-press the "sure!" bubble → Share → Send to Chauffeur → matched to the
  open ask (usually exactly one; if several, a push asks which) → covered,
  DM confirm with Undo. One-time setup per phone; degrades gracefully to
  Rail A without it.
- **Rail C (later): the native iOS app's share extension** makes this
  first-class and retires the Shortcut. Already the recorded direction for
  share-TO.

**8. "Ask someone new" never needs the contact's number.** The parent picks
the person *in Messages*, so Chauffeur stores no phone number and asks for no
contacts permission. Optional single "Who?" field (skippable) exists only so
the waiting state can say a name; once they're confirmed as covering, they
become a known outside hand and a future tier-2 candidate. Contact Picker API
is Chromium-only (not iOS Safari) — a possible Android-panel enhancement,
irrelevant to v1.

**9. Care gaps and commitment findings never reach a shared surface.** Health
is a scheduling problem, not content, and the wall panel is semi-public. These
kinds stay DM-only; the Needs You tile excludes them entirely.

**10. The counts are real or they don't ship.** The records table gives the
family digest honest numbers — *watched / cleared themselves / one-tap /
decided / expired*. No invented "hours saved": the first fabricated number a
parent disagrees with poisons the channel.

## The noise cuts

| Finding | Disposition |
|---|---|
| Unclaimed-chores weekly batch | **Cut from DM** → monthly digest count only (user-stated 2026-08-23) |
| Optional event skipped, days out | **Cut from DM** — the schedule already shows it; surface only on look (user-stated 2026-08-23) |
| Prep-kit ideas (weekly LLM) | **Proposed cut** — same shape as unclaimed chores: no clock. NOT yet confirmed by the user |
| Chore verify, redemption, stale proposal, errand past-due, supply deadline, occasion gap | Keep in DM; first four gain one-tap actions |
| Care gap, commitment erosion | Keep, DM-only forever (point 9) |
| Unassigned normal event | Keep — becomes the solution ladder (point 5) |

## The pieces

**Findings table.** `id, identity (kind:subject), kind, severity
(decide|approve|fyi), line, subject {type,id}, proposal_id?, due_at?,
created_at, resolved_at, state (open|done|dismissed|expired), resolved_by
(auto|tap|dismiss|expiry) + member_id`. Dismissed identities never re-open
unless the subject materially changes (matches occasion `dismissed`
semantics). `due_at` past → expired.

**Sweep additions.** collect → upsert by identity → reconcile (open records
absent from this sweep close as `done/auto`) → expire → DM exactly as today.
Push cadence, quiet hours, notify-once markers, zero-LLM: all unchanged.

**Ask state.** `awaiting: {name?, asked_at, event_occurrence}` on the event;
nudge schedule (~1h, evening, T-18h); resolution writes an assist assignment
(covered-rides machinery, A1) and closes the finding; [No]/timeout resumes
the ladder at the next candidate or tier 3.

**Needs You tile.** `_tile_needs_you` in the home-board registry; card
conversion paradigm (section toggles per severity, interactive ON);
parents/adults only — kids never see it; wall panel renders read-only (lens
never writes). Empty means blank. `fyi` capped at 3 visible, rest fold.

**Agent stacks.** `list_open_findings` wired into both stacks
(agent_router/agent_tools_v2 *and* the chat loop) so "what needs me?" answers
from records. Hand path: everything tappable on the tile too.

**Digest.** One section, real counts (point 10).

## Build order

1. **Noise cuts** — the DM cuts. Immediate relief, no schema. **SHIPPED v2.385.0.**
2. **Feasibility pass + solution ladder** — tiers 1–3 with honest buttons,
   skip-this-occurrence, ask state + Rail A pushes. **SHIPPED v2.385.0.**
3. **Findings table + lifecycle** — records, auto-resolve, undo.
   **SHIPPED v2.385.0.**
4. **Tile** — the Needs You board card. Not built. The agent tool
   (`list_open_findings`, both stacks) and the digest counts shipped with
   slice 3; the hand path meanwhile is the approve-cards the sweep posts into
   the DM, which go through the same proposal rail a tile would.
5. **Rail B Shortcut** — opt-in, after the core proves out. Not built.

Slices 1–2 were shippable without 3; cuts and better DM lines need no records
table. They shipped together anyway because the ladder wanted somewhere to
record that an ask was in flight.

### What shipped in 1–3

- `services/findings.py` — the `Finding` tuple, identity, `reconcile`,
  `resolve`, `month_counts`. `findings` table.
- `services/coverage_options.py` — `driver_options`, `outside_hand_candidates`,
  `draft_ask`, `ladder`, `start_ask` / `answer_ask` / `due_nudges`.
  `coverage_asks` table.
- `services/watchers.py` — every collector emits `Finding`s; the sweep
  reconciles records before it decides whether to speak; `dm=False` carries the
  noise cuts; up to 3 approve-cards ride the DM.
- `chat_actions` gained `ask_outside_hand` and `skip_occurrence`;
  `optional_events.stamp_decisions` stamps `skip` on any event.
- `static/sw.js` gained the generic `postAction` rail; `main` gained
  `send_push_with_actions` and the nudge sweep.
- Tests: `tests/test_coverage_ladder.py` (10 scenarios), `tests/test_watchers.py`
  (+4).

## What this is not

No LLM in the sweep. No auto-assignment without a tap (propose-approve stays
the ceiling until the trust ratchet earns more). No phone numbers stored, no
contacts permission. No "hours saved" theater. No findings on kid surfaces.
No confirm links to friends.
