# Mind Plans — insights terminate in plans, watches, or nothing

**Date:** 2026-09-02
**Status:** Approved design, pre-implementation
**Prior art:** `2026-08-27-mind-executive-loop-design.md` (phase C, shipped v2.426.x)

## Problem

Two complaints from live use, one root cause:

1. **Repeat nagging.** An insight about next Tuesday is restated every day
   until Tuesday. An insight retires only when the think call omits it from
   the desired set (`mind.py` retire-by-omission); while it stays true it
   stays on the lane, forever, with no snooze and no time decay.
2. **Observations without moves.** "Margin is narrowing" arrives with
   nothing attached. The only action rail is `propose_fix` — explicitly
   instructed to propose *exactly ONE concrete action* via the scheduling
   agent — so every insight bottoms out at a schedule nudge regardless of
   what was noticed. Reads like the reminders and pushes that already exist.

The fix is not another domain vertical (a "capacity arc", a "hiring arc").
The range of family problems is infinite; enumerating them is a losing
battle. Generality comes from composing a small stable set of primitives —
and the app already has the primitives: 99 tools in the v2 stack, nine of
them general (`research_question`, `create_thread`, `make_request`,
`propose_family_action`, `negotiate_day`, `add_household_task`,
`send_direct_message`, `announce_to_room`, `propose_program`). The
bottleneck is arity: one tool call, on demand, after a tap. This design
removes that ceiling.

## Shape

An active insight is no longer allowed to just persist. It terminates in
exactly one of three things:

1. **A plan** — 2–5 ordered steps, each either a *tool step* (a sentence the
   existing agent rail can bind to a real proposal) or a *human step* (owner
   + due date; the app tracks it, a person does it). Mixed freely. Human
   steps are what keep the plan space infinite while the execution space
   stays finite and auditable.
2. **A watch** — a snooze with a wake date. Silent until then.
3. **Dropped** — dismissed, forever, as today.

Approval model: **per-step** (option B). Each tool step has its own Approve;
a bad plan costs one skipped line, not a cascade. Nothing executes without a
tap. No step is ever auto-run.

Runtime code generation is out of scope and stays out: "inventing
functionality" here means authoring persistent configured behavior out of
generic machinery (a plan, a thread, a snooze, a recurring task) — never
writing code.

## Two-stage composition (no new binding layer)

- **Planner** (one `_pool_call('heavy')`, at tap): insight + snapshot + a
  short natural-language capability menu → steps JSON. The menu is a
  hand-written paragraph naming the general primitives in plain terms — not
  99 schemas.
- **Binder** (per tool step, lazily, at that step's Approve tap): the
  existing `propose_fix` rail — `process_agent_request` with the tapping
  parent as acting member — turns the step sentence into a validated
  proposal card. Approve then executes via the same chat_actions rail chat
  uses. `research_question` is already a v2 tool, so "go find out" steps
  bind with no special case.

Both planner and binder count against the existing `mind_cap_handle`
(30/day). The think call stays one call.

## Think-time `approach` line (hybrid, zero extra requests)

THINK_SYSTEM gains one field per insight: `approach` — one line naming the
shape of the fix the Mind would build ("I'd price two outside-hand options
and ask whether Thursday can drop"). Same call, no new requests. The lane
stops reading as bare reminders before anyone taps anything, and the quality
of `approach` lines is a cheap early read on whether plans will be worth
tapping.

## Data shape

No new table. Plans live on the `mind_insights` row, following the
`proposal_json` precedent:

```
plan_json = {
  'created_ts': float,
  'steps': [{
    'id': hex,
    'kind': 'tool' | 'human',
    'text': 'one sentence',                    # what the planner wrote
    'owner_member_id': str|None,               # human steps
    'due': 'YYYY-MM-DD' | None,                # human steps; optional on tool steps
    'status': 'open' | 'done' | 'skipped',
    'proposal_json': {proposal_id, summary}    # tool steps only, bound lazily
  }]
}
```

Row gains two fields: `approach` (str, from think) and `snoozed_until`
(float ts, from a Not-now tap).

## Lifecycle

- **active** — in lane as today, now with the approach line rendered.
- **snoozed** — still state `active`, `snoozed_until` in the future. Leaves
  the lane. The think prompt is shown the row with its wake date and told to
  leave it be. **Retire-by-omission skips snoozed rows** — otherwise a
  snooze silently becomes a dismiss. Date passes → back in the lane.
- **in_hand** — new state, set when a plan is created. Leaves the lane
  except when a step is due or overdue, where the card renders as "N steps
  due", not the restated observation. Retire-by-omission skips these too; if
  the model re-emits the slug, fields update and state stays `in_hand`.
- **retired** — when the plan's last step closes: any step `done` →
  outcome `acted`; all steps `skipped` → outcome `dismissed`. Dismissed
  slugs stay suppressed forever, acted may return — both unchanged from
  phase C. Graduation counters keep working untouched.

## Surfaces

One behavior change, flagged deliberately: **"Handle it" becomes "make a
plan."** The old single-proposal path survives as a one-step plan with the
same tap count (Handle → Approve); nothing a person could do is lost, but
the button's meaning changes from "one proposal" to "a plan".

- **Insight card** (PWA Family lane + /mind, shared markup): line +
  `approach` in muted text. Buttons: **Handle it** (creates plan), **Not
  now** (snooze — quick picks: a few days / a week / pick a date, via
  `promptInput`, never browser dialogs), **Dismiss** (unchanged, forever).
- **Plan checklist**, inline on the card: tool steps get **Approve** (binds,
  then rides the existing approve rail) and **Skip**; human steps show
  owner + due with **Done** / **Skip**.
- **Due steps** surface in-lane only. No push — delivery is phase B and is
  not smuggled in here.
- **Endpoints:** `POST /api/mind/insights/{id}/plan`,
  `POST /api/mind/insights/{id}/step/{sid}/bind`, `.../done`, `.../skip`.
  Parents/adults only, same gate as the existing mind endpoints; sensitive
  insights keep their parents-only render.
- Agent tools stack untouched this slice (`list_insights`/`dismiss_insight`
  unchanged; plan tools are YAGNI until asked for).

## THINK_SYSTEM changes

- Request `approach` per insight (one line, the shape of the fix).
- Snapshot's own-insights section tags snoozed rows (`[snoozed until …]`)
  and in-hand rows (`[in hand, N steps open]`); prompt says: leave snoozed
  rows alone until their date, never restate an in-hand observation.
- Retire-by-omission applies **only to active, non-snoozed** rows.

## Feedback loop (unchanged, now with more signal)

Outcome-per-category already feeds the think prompt via the own-insights
section and graduation counters. Plans make outcomes more honest: acted now
means "steps actually ran or were done", not "someone tapped a button to
make it go away".

## Failure honesty

- Planner returns unusable JSON → error surfaced on the card, no plan row
  written, cap still bumped (a spent call is a spent call).
- Binder returns no card → step shows the agent's honest no-move note,
  stays `open`, can be skipped.
- All-skipped plans retire as `dismissed` so the graduation math hears the
  family saying no.

## Testing

- `test_mind_plan.py` — planner parse + clamp (≤5 steps), lazy bind, per-step
  status math, retire math (any-done→acted, all-skipped→dismissed), snooze
  survives think omission, in_hand survives think omission, lane visibility
  (snoozed hidden, in_hand hidden unless step due, wake on date).
- `test_mind_think.py` — approach field parsed and stored; retire-by-omission
  skip rules.
- Endpoint tests in `test_mind_endpoints.py` — role gates, sensitive render.

## Out of scope (named so they stay out)

- Runtime code generation by the agent.
- Condition-based watches (date-based snooze covers the need; revisit only
  if dates prove insufficient).
- Push delivery of due steps (phase B).
- Plan visibility in the agent tools stack.
- Any domain-specific "capacity" / hiring vertical — the whole point is
  that no such vertical exists.
