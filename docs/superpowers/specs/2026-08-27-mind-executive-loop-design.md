# The Mind: Agentic Executive Loop — Design

Date: 2026-08-27
Status: Approved (design), implementation plan pending

## Purpose

Chauffeur today is a platform with an AI agent bolted on: the CP-SAT solver
decides, eighteen hand-coded sweeps in `push_notification_loop` watch for
situations someone already thought of, and the LLM parses chat into tool
calls. The Mind adds the missing organ: a standing executive loop that reads
whole-family state on its own initiative and surfaces observations nobody
wrote a watcher for — the S.A.R.A.H. ambition ("monitoring everything,
making intelligent decisions or telling you about a situation and asking how
to handle it"). The power being bought is novelty: cross-domain patterns
("six activity nights in a row", "you always scramble when Scouts and
gymnastics collide") that per-feature watchers structurally cannot see.

The Mind speaks as Argyle. One house persona, one voice.

## Trust ladder

- **Phase C (this design): pull lane only.** Insights accumulate on a card;
  nothing DMs anyone. Interruption stays governed by the existing
  watcher-signal policy (time-critical + actionable + solution attached),
  which the Mind does not use in phase C.
- **Phase B (later slice, mechanics pre-built here): audience by stakes.**
  Categories with proven act-rates graduate — with an explicit per-category
  human flip — to direct delivery to the affected member. Anything touching
  schedule, money, or another person's obligations still routes through
  parents.

## Data boundaries (locked)

- **DMs are never read.** Family-channel messages are input — "a family chat
  is the same as sitting in the living room and talking out loud." One-to-one
  DMs are private, structurally never queried by any Mind component.
- **Gift/present records are never read.** Gift secrecy leaks are
  unrecoverable, so exclusion is mechanical: the snapshot builder never
  touches gift fields; occasion dates are included, gift content is
  structurally absent from every prompt.
- **Kid emotional state and health are visible but sensitivity-gated.**
  The Mind may reason about them (that is much of its value); the resulting
  insights are tagged `sensitive` and render only to parents (see
  Surfacing).

## Architecture

New service `chauffeur/services/mind.py`. Three rungs, all riding the
existing `push_notification_loop` marker-set-first pattern. No new
scheduler, no write-path instrumentation.

### Rung 1 — Sentinel (gemma tier, ~every 120s when deltas exist)

A poll-based differ, not event hooks. Each pass gathers what changed since
the last look — new/edited events, new findings, supply changes, new
family-channel messages (message-id watermark) — and makes ONE coalesced
gemma call: "anything here the house should remember or act on?" Output is
zero or more *noticings*: compact one-line observations with an urgency
guess. An empty delta makes no LLM call. The 120s window is also the burst
coalescer: a calendar sync writing forty events becomes one look, not forty
(RPM hygiene, and one look at "sync added 40 events" judges better than
forty blind looks).

### Rung 2 — Promoter (flash-lite tier, rare)

Noticings the sentinel flags urgent get one flash-lite sanity check: "does
this need attention before the next hourly think?" Yes sets
`mind_think_requested`; the next 30s loop tick runs the deep think early.

### Rung 3 — Deep think (flash via heavy tier, hourly inside waking window)

Input: full snapshot + unconsumed noticings + the Mind's own active insights
+ recorded human reactions to them. Skipped when the snapshot hash is
unchanged AND no new noticings exist. Output: the desired card state — new,
updated, and retired insights, at most ~7 active. The Mind curates its own
card each think; there is no append-only feed. Each insight may carry a
proposal (a `propose_family_action` spec); the Mind never executes anything
— a human tap approves.

### Budget arithmetic (checked 2026-08-26)

Free-tier quotas: flash ~100/day (shared with trip generation and vision),
lite ~1,020/day, gemma ~28,800/day. Actual usage the prior day: 2 lite + 27
gemma. Hourly waking-window thinks ≈ 16–20 flash/day — comfortable.
Quota is not the binding constraint; the guards below exist for the real
ones (state churn, attention, RPM bursts).

## Data model

Two new tables.

**`mind_noticings`** — id, ts, source (chat | calendar | findings | supply |
…), line (one compact sentence), refs (JSON ids), urgency, consumed_at.
Sentinel writes; deep think consumes (sets consumed_at); 14-day retention.

**`mind_insights`** — id, slug (stable identity across thinks), line,
detail, domain (the feature area the insight is about: meals, kids, cars,
schedule, …), sensitivity (normal | sensitive), category (a pattern slug the
Mind chooses and reuses, the unit of graduation: overload, supply-gap,
logistics-conflict, …), proposal_json
(optional), confidence, state (active | retired), outcome (acted | dismissed
| expired), created_ts, resolved_ts.

Deliberately NOT reusing `findings`: findings live on absence-means-resolved
reconciliation (`findings.reconcile`); insights live on the Mind's own
keep/retire judgment plus human feedback. Different lifecycle, different
table.

## Snapshot

`mind.snapshot()` builds one compact text block (~8–12k token target):

- next-7-days calendar per member
- driver load summary
- open findings lines
- supplies low/claimed
- car readiness
- member status days
- family-channel messages since last think, verbatim (the living-room
  transcript)
- unconsumed noticings
- active insights with recorded human reactions

Structurally excluded: DMs (never queried), gift/present records (never
queried). A hash of the snapshot with timestamps stripped drives
skip-when-unchanged.

## Surfacing (phase C)

One insight-lane component, three renders (kiosk-shares-logic pattern).
The sensitivity gate is applied server-side per request identity; shared
surfaces receive a payload that never contained sensitive rows.

1. **Board tile "Argyle noticed"** (wall panels, kiosks — no viewer
   identity): normal-sensitivity insights only. An instance under the
   configurable-tiles system.
2. **PWA** (logged in, identity-aware): same tile; a parent sees the full
   lane including sensitive, kids and other adults see the filtered view.
   Placement: the Family tab, adjacent to the Needs You material — same
   "house wants your attention" neighborhood, not merged with it.
3. **Admin (control_center) — new Mind page**: settings, the full lane
   including sensitive, history/archive of retired insights with outcomes,
   per-category feedback counters, and graduation proposals.

Each insight renders with: line, optional detail, dismiss button, and an
act button when a proposal is attached (tap = approve via the existing
`propose_family_action` rails).

Hand path + both-stacks rule: `list_insights` / `dismiss_insight` tools are
added to agent_tools_v2 so chat reads the same lane; the tile is the
no-chat hand path.

## Feedback and graduation

Every insight terminates as acted, dismissed, or expired (retired by the
Mind untouched). Counters roll up per category. When a category reaches
≥10 resolved samples with act-rate ≥60%, the Mind admin page shows a
graduation proposal ("flip `supply-gap` to direct delivery?"); a tap adds
the category to `mind_direct_categories`. Phase-B delivery itself (DM to
the affected member, watcher-signal policy applies in full) is a later
slice — this design ships the lane, the counters, and the flip switch, so
phase B is a delivery change, not a redesign.

## Settings

Via settings_registry plus the Mind admin page (config-decentralisation
rule; nothing added to config.html): `mind_enabled` (default off until
flipped), sentinel cadence, think cadence, wake window (default
06:00–22:00), max active insights, daily call caps, `mind_direct_categories`
(empty until graduations).

## Budget and failure guards

- Marker-set-first before every rung runs (matches existing sweep
  convention) — a crashing rung skips its cadence window instead of
  retry-storming.
- Daily hard caps, settings-tunable: thinks ≤ 20, sentinel gemma ≤ 400,
  promoter lite ≤ 50. Cap reached = silent skip until midnight.
- LLM failure = skip cycle; model_pools cooldowns already handle 429s.
- All calls log-tagged (`mind.think`, `mind.sentinel`, `mind.promote`) for
  day-after usage review.
- No HA dependency anywhere; with nothing to notice the Mind degrades to
  silence.

## Testing

- Unit: snapshot builder (family channel in, DMs out, gifts out — asserted
  by construction), skip-hash behavior, insight reconcile
  (keep/update/retire), sensitivity filtering per surface, cap enforcement,
  feedback counter rollup and graduation threshold.
- One runtime test that actually RUNS a full think cycle with a faked LLM
  response through to rendered card payload (entry points swallow
  exceptions; a source-reading test would miss a broken wire).
- Hand-path test: tile actions (dismiss, act) reachable without chat.
- LLM mocked everywhere; zero live calls in tests.

## Future work (explicitly out of scope now)

- **Phase B delivery**: direct-to-member DMs for graduated categories,
  under the watcher-signal policy.
- **HA input**: entity states and house telemetry as snapshot input —
  insights about the house, and the house as a signal about the family
  (e.g., presence patterns, energy rhythms). Interesting, deferred; must
  follow the HA-degrades-gracefully rule when it lands.
- **Existing-watcher absorption**: sensors stay; whether any hand-coded
  sweep's judgment folds into the Mind is a question for after phase C
  proves taste.
