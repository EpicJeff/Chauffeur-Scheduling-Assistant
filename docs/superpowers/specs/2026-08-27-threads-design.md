# Threads — the household's open loops

Date: 2026-08-27
Status: Approved (design), for implementation
Vision context: the "Work Nobody Scheduled" arc — the outward half of the
family assistant, alongside the pulse (`services/vitals.py`, shipped
v2.427.x) and web research (`services/web.py`, shipped v2.428.x).

## The problem

Chauffeur manages the fraction of family life that has a start time. The
rest — the pool company, the pest control renewal, selling the old dresser,
finding after-school care, the insurance thing nobody has called about —
has no start time, so it lives nowhere and stalls invisibly.

Two consequences the app can measure and fix:

1. **The load is in the correspondence, not the appointment.** A pest
   control visit takes twenty minutes. Getting to it took four messages, two
   reschedules, and eleven days on somebody's mental list. The app schedules
   the twenty minutes and does nothing about the eleven days.
2. **The pulse is wrong without this.** `vitals.load` currently counts
   driving, tasks and findings — the visible work. Someone carrying nine
   open loops reads as unloaded. Mental load is precisely "who is holding
   the open loops", and it is currently unmeasurable.

## The noun

A **thread** is an open loop with someone outside the family:

- `title` — what this is ("Find after-school care for Lily")
- `goal` — the outcome wanted, one sentence
- `counterparty` — an assist contact id, or a loose name when there is no
  contact record (most threads start before you know who you're dealing with)
- `owner_member_id` — who is carrying it
- `next_action` + `next_action_at` — the single thing that has to happen next
- `state` — `open` | `waiting` (on them) | `done` | `dropped`
- `kind` — `vendor` (recurring, never reaches done) | `project` (has an end)
- `history` — append-only entries: notes, sent mail, received mail, research,
  state changes. Each carries `ts`, `who` (member id or `argyle`), `text`,
  and optional `url`/`message_id`.

Vendor relationships and one-off projects are the same shape; the pool guy
just never reaches `done`.

## What the app does with one

**Stall detection.** A nightly sweep. A thread stalls when its
`next_action_at` is past, or when nothing has been appended to `history` for
`stall_days` (default 7) while the state is `open`. A stalled thread becomes
a finding on the existing rail — the eleven days nobody was watching. Per
the locked watcher-signal policy, a stall finding arrives with what to do
next attached (its own `next_action`), never as a bare nag.

**Load contribution.** `vitals.measure_day` adds `THREAD_MINUTES` per open
thread per owner. This is the point of doing threads before negotiation:
carrying a loop is work, and the pulse should say so.

**Correspondence, both directions.**
- *Outbound*: the agent drafts; a human reads and sends. Never a send
  without a person, ever — a badly worded email to a nanny candidate is the
  family's reputation with someone they were about to trust with their kid.
  Sending appends to `history`.
- *Inbound*: `email_ingest` already classifies mail. Extend that
  classification with "is this an update to an open thread?", matched on
  counterparty address first and subject//content second. A match appends to
  `history` and clears `waiting`.

**Research.** `web.research` (shipped) answers a thread's open question with
sources. Results append to `history` with their citations, so a fact in a
thread always carries the page it came from.

**The Mind gains a verb.** Threads appear in the snapshot (open ones, their
owners, what is stalled). The Mind may propose starting a thread, or surface
one that has stopped moving.

## Surfaces

- **A Threads page** — the hand path: create, edit, advance, close. Grouped
  by state, stalls first.
- **PWA**: threads owned by the signed-in member, on the House tab beside
  chores and lists (same neighbourhood: the household's own work).
- **Agent tools** in the live v2 stack: `list_threads`, `create_thread`,
  `update_thread`, `add_thread_note`, `draft_thread_message`.

## Boundaries

- The agent **never sends** mail unread, never signs anything, never pays
  anything.
- Research facts inside a thread carry their source URL or they do not
  appear (already enforced by `services/web.py`).
- Screening someone the family intends to **employ** is regulated: the app
  organises a search and verifies public license records, and never presents
  itself as having run a background check. It names where a real one happens.
- Stall findings share the Mind's interruption budget. A stalled thread and
  an uncovered drive compete for the same attention, or this becomes a third
  notification system.

## Explicitly deferred

- Auto-filing every inbound message into threads without a match (guessing
  wrong is worse than not filing).
- Multi-party threads (more than one counterparty).
- Any payment or scheduling *on behalf of* the family with a vendor.

## Testing

Unit: thread lifecycle and state transitions; stall detection at the
boundaries (due today vs overdue, quiet 6 days vs 8); finding reconciliation
across sweeps; load contribution; inbound matching (matches by address, does
not match a stranger); draft generation with a faked LLM.
One runtime test that RUNS the sweep end to end into a real finding.
Hand-path test: every thread action reachable without chat.
