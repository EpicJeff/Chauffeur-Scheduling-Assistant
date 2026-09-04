# Mission Engine — a generic agent loop with a pro-model brain

**Date:** 2026-09-04
**Status:** Approved direction, spec for review
**Version target:** v2.457.x

## Why

Every agentic capability shipped so far is a hand-wired pipeline (threads research,
programs curation, mind think, plans-as-sentences). Each does one thing; none
composes. The "plan the party / find and book a service / arrange the pickup"
class of task needs a model that *composes* the existing tool surface over many
steps — and a model tier strong enough to drive that loop.

Two facts ground the design:

- The v1 stack's `agentic_chat_loop` is single-shot despite its name (the only
  `while` in `llm.py` is a string parser). But its registry —
  `agent_tools.TOOL_SCHEMAS` / `TOOL_HANDLERS`, ~80 tools — is real, maintained,
  and already the execution vocabulary of the proposal rail
  (`chat_actions._execute` falls through to `TOOL_HANDLERS` for any action_type
  in the registry). The tool surface exists; the loop does not.
- Everything runs on the Gemini free tier. The user now has a **second, paid
  API key with pro models**, to be used **only** where pro is needed. Regular
  Chauffeur traffic must never touch it.

## Shape (one paragraph)

A **mission** is a goal sentence plus persisted state. The **engine** is one
generic loop: pro model + the full tool registry; read tools execute inline,
every write becomes a proposal on the existing propose-approve rail, mail stays
on the draft-never-send rail. **Doorways** (chat, a thread's Work-this button, a
manual form) are one-liners that hand a goal to the same engine. No per-domain
pipeline is ever added to the engine.

## Model routing: the pro pool

`model_pools.py` gains:

- Pool `'pro'`: default `["gemini-3.1-pro", "gemini-2.5-pro"]` (confirmed by
  the user at spec review, 2026-09-04), overridable via `model_pool_pro` like
  every other pool.
- Tier `'mission'`: chain `['pro']` — **no fallback into free pools**. If the
  pro pool is exhausted or erroring, the mission pauses (`waiting_retry`) and
  resumes on a later tick. A mission never silently degrades mid-run; a
  benchmarking mission launched on tier `flash` uses the existing free chains.

**Key routing:** new setting `llm_gemini_paid_api_key`. A single helper
`model_pools.api_key_for_pool(pool_name, settings)` returns the paid key for
`'pro'` and the free key otherwise. The paid-key settings key is read
**nowhere else** — pinned by a source-scan test (study-style source pin):
`llm_gemini_paid_api_key` may appear only in `model_pools.py`,
`settings_registry.py`, and their tests. That is the structural guarantee that
regular traffic cannot spend paid money.

## Data

Two tables, mind-style retention:

- `missions`: `id`, `goal` (text), `origin_kind` (`manual|thread|chat`),
  `origin_ref` (e.g. thread id), `created_by` (member id), `tier`
  (`mission|flash`), `status`
  (`running | waiting_user | waiting_retry | done | blocked | dropped`),
  `summary` (model's closing statement), `error`, `step_count`,
  `created_at/updated_at/finished_at`. Terminal rows pruned at 120d; active
  never pruned.
- `mission_steps`: `id`, `mission_id`, `idx`, `kind`
  (`llm | tool | proposal | draft | ask | note`), `name`, `args_json`,
  `result_json`, `ts`. The transcript is the audit log and the resume state.

## Engine loop (`services/missions.py`)

Background daemon thread like the mind's poll loop: tick every 30s, advance
each `running` mission by up to K=3 steps per tick (missions are resumable by
construction; a restart loses nothing).

One step = one LLM call on the mission tier:

- **Prompt:** goal + compact digest (last N steps + open artifacts + today's
  date) + tool schemas. Schemas offered: the v1 registry's read tools verbatim;
  write tools wrapped as `propose(<tool>, args, why)`; `research(question)`
  (existing `web.research`, citations from `facts` only, per the threads
  ruling); `draft_message(...)` (thread draft rail, returns text only);
  `ask_user(question)`; `finish(summary)`; `give_up(reason)`.
- **Read tool call:** dispatched through `agent_tools.TOOL_HANDLERS`, result
  appended as a `tool` step. Read/write is decided by an explicit
  `READ_TOOLS` frozenset in `missions.py` — **default deny**: any registry
  tool not on that list is offered only in propose-wrapped form. A new tool
  added to the registry later is write-classed until someone consciously
  promotes it; a test asserts every READ_TOOLS entry exists in the registry.
- **Write intent:** stored as a `proposal` step holding
  `{action_type, payload, why}` where `action_type` is a registry tool name —
  the exact shape `chat_actions._execute` already runs. Approve on /missions
  executes it (mirroring the mind-insight approve endpoint); Discard marks it
  declined. The engine itself executes **no** write, ever — same law as the
  room never writes.
- **`ask_user`:** mission → `waiting_user`, question surfaced on /missions;
  answering (a text box) appends a `note` step and resumes the loop.
- **`finish`/`give_up`/step-cap:** terminal status + one finding (kind
  `mission_done` / `mission_blocked`, added to `watchers.SCANNED_KINDS`,
  `due_at=None` per the thread-stall precedent) with the next action in the
  line — "3 proposals await approval", "blocked: no vendor replied". Findings
  only at terminal/waiting states, never per step (watcher signal policy).

**Identity & authorization:** launching requires a resolved parent/adult
(allowlist, threads-style — `/api/chat` is WALL_OR_SERVICE so blocklists leak).
The mission stores `created_by`; proposals execute under that member at
approve time, resolved at dispatch, never from the model.

**Caps (settings, mind-cap pattern):** `mission_cap_launch` 3/day,
`mission_step_cap` 40 LLM calls per mission, `mission_cap_pro_calls` 120/day
global, concurrent running missions: 1 (queue the rest as `waiting_retry`).
The per-mission step cap times pro pricing is the bank-account guard; caps are
enforced in the engine, not the prompt. These defaults are uncalibrated
starting values (user's call at review: no way to judge without trying) —
settings-editable on /missions, revisit after the first real missions.

## Doorways (v1 ships three, all thin)

1. **Manual** — /missions has a goal text box + Launch (+ tier picker,
   default `mission`). This is the hand path; it exists before any agent path.
2. **Thread** — a Work-this button on a thread builds a goal from
   title/goal/counterparty/history-tail and launches with
   `origin_kind='thread'`. Mission proposals that draft mail attach to the
   thread's draft rail unchanged.
3. **Chat** — `launch_mission` tool wired into BOTH stacks per the two-stacks
   rule: v1 schema+handler, v2 declaration + wrapper + dispatch branch.
   Parent/adult only, resolved at dispatch.

**Deferred doorways:** mind Handle-it upgrade (insight → suggested mission) —
phase 2, after the engine proves out; occasions; auto-launch of any kind.

## Surface

`/missions` admin page, nav treated exactly like /mind and /threads:
admin-only slug, kiosk-hidden (counterparty and pricing data will appear in
transcripts). Sections: active mission (live transcript, artifacts with
Approve/Discard, answer box when `waiting_user`), history, settings (caps,
pro pool, paid key). Settings registered in `settings_registry.py` with
`page='missions'` per the config-decentralisation rule — nothing goes to
config.html.

Study furniture for missions (a desk drawer? the contracts shelf?) is
explicitly deferred — Law 1 review when the engine is real.

## What this is NOT (locked at birth)

- **No browser actuation.** No form-filling, no carts, no payments. The
  supply-intake finding stands: ATC is a URL. Booking happens via drafted
  mail/messages a human sends, or by handing the human a link.
- **No autonomous sends.** draft-never-send survives structurally: the engine
  can only reach `draft_message`; `send_drafted` remains humans-only behind
  its own endpoint.
- **No third stack.** The engine consumes the v1 registry; the v2 chat stack
  gains one launch tool. No new tool vocabulary is invented for missions.
- **No pro creep.** The paid key is unreachable outside the pro pool resolver;
  the source-pin test is the fence.

## Testing

- Engine unit tests with a scripted fake LLM: read-dispatch, propose capture,
  ask_user pause/resume, step cap → blocked + finding, retry pause on pool
  exhaustion, resume across "restart" (fresh engine over same tables).
- Source-pin: paid key setting referenced only in allowed modules.
- Rail pin: no mission code path imports mailer; proposal execution goes
  through `chat_actions._execute` only.
- Doorway reachability (hand-path rule): /missions launch endpoint allows
  parent/adult, refuses child/anonymous; thread button and both chat stacks
  reach the same endpoint.
- Cap tests per counter; pool test: tier `mission` never yields a free-pool
  model; `api_key_for_pool` returns the right key per pool.
- One live-shaped runthrough (harness.py pattern) that RUNS the engine loop
  end-to-end with the fake LLM — the source-reading-tests-miss-runtime-breaks
  rule.

## Review resolutions (2026-09-04)

1. Pro pool default: `gemini-3.1-pro`, `gemini-2.5-pro` (user-confirmed).
2. Cap defaults stand as starting values; calibrate from real missions.
3. Proposals surface on /missions only for v1 (confirmed).
