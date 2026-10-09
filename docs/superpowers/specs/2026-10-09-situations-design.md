# Situations — one shape for everything that needs a person

Date: 2026-10-09
Status: Approved in conversation; implementation plan pending
Sub-project 2 of the agentic-layer plan (1 = dismissed-is-dismissed, shipped v2.499.297; 3 = conversational triage and reply detection, not yet designed)

## Problem

After weeks with the Mind on, the household's verdict on the agentic layer (findings, insights, threads, missions) was that it had not earned its keep:

- "Handle it" was opaque. It was not clear what the app would do, through which channel, or whether that would suit the people involved. Family members use Chauffeur at very different depths (the wall only; the PWA for the schedule only), so acting through a Chauffeur workflow may not reach them at all. It was easier to ignore the finding and handle it by hand.
- Threads and missions each have a state machine but no sentence. The pages leave a person not knowing where a thing stands or what they can do next.
- Watcher findings had no hand path at all. Nothing in the UI calls `/api/findings`; a finding reaches a person only as a DM line plus up to three Approve cards. There was no screen to see, handle or dismiss one.

The underlying issue is that four different objects each present themselves differently, and none of them answers the two questions a person actually has: *where does this stand?* and *what can I do about it, right now, in a way that works for the people involved?*

## Locked decisions

These came out of the conversation and are not to be relitigated casually:

1. **No people model.** The app never keeps a profile of how to deal with a given person. The person names the avenue ("text the cleaner", "message Sarah", "email the teacher"). The only state kept is a ledger: what was asked, of whom, by which channel, and whether an answer came back.
2. **Draft, approve, send** for every communication that leaves the family. Inside the family, a Chauffeur message goes on the person's say-so.
3. **No channel is gated on a known address.** Email and text are always offered as drafts to copy; a known address or number only adds a one-tap `mailto:`/`sms:` link. "In person" also gets a draft of what to say.
4. **Asks never send mail from the app.** The configured SMTP is the household's intake/invite address, which is the wrong sender for a personal ask. Threads keep their existing household-address send for vendor correspondence (replies landing in intake is what matches a reply back to the thread). Per-member "send as me" is a possible later opt-in, not part of this slice.
5. **Argyle writes the status note on state change only** (option 1 of three considered): one Flash-Lite call when the object moves, cached on the row, never on read, deterministic fallback on failure. Deterministic-only templates (option 2) were rejected as never insightful; on-demand only (option 3) as leaving the UI dumb until poked.
6. **/threads and /missions are rewritten around the card**, not given a card on top (the halfway version was offered and declined).
7. **Dismissed is dismissed** (sub-project 1). Nothing here reopens a dismissed finding or insight.

## Approach

**One view-model over the four existing tables.** A new `services/situations.py` turns a finding, insight, thread or mission row into one `Situation` shape. Each of the four rows gains three persisted fields (`status_note`, `next_steps`, `note_ts`, plus `note_source`). Asks go to one ledger table, `asks`, which generalises the existing `coverage_asks`. One shared card builder renders a situation everywhere it appears.

Rejected: a new `situations` table as the source of truth (every mutator writes twice; projections drift), and four pages made consistent by convention with no shared builder (violates the UI design guide's same-concept-same-builder rule and reproduces today's problem).

Trade-off accepted: the status note is a cached opinion. It can be stale for the seconds between a state change and the Lite call, and it is deterministic when the call fails. The card always shows the deterministic facts (state, since-when, next action, due) beside it, so a stale note never hides the truth.

## Section 1 — The situation shape

```
situation = {
  kind: 'finding' | 'insight' | 'thread' | 'mission',
  id: str,
  title: str,            # finding.line / insight.line / thread.title / mission.goal
  state: str,            # the row's own state, untranslated
  since: float,          # when this state began (created_at, waiting-since, last step ts)
  people: [str],         # who it is about: finding subject, insight refs (members), counterparty, created_by
  due: float | None,     # due_at / next_action_at / None
  status_note: str,      # Argyle's one or two sentences, or the deterministic fallback
  note_source: 'argyle' | 'fallback',
  note_ts: float | None,
  next_step: option,     # ONE option, highlighted: the most likely move
  options: [option],     # the rest, always including a way to close and a way to dismiss where the kind allows it
  asks: [ask],           # ledger rows for this situation (Section 2)
}

option = { id: str, label: str, verb: str, payload: dict }
```

**Verbs are a closed set.** `assign` (a family driver, via the override rail), `ask` (someone, by a channel — Section 2), `plan` (an insight: create its plan via `mind.make_plan`), `prepare` (an unbound tool step: bind it to a proposal via `mind.bind_step`), `do` (execute an existing proposal through `chat_actions.act_on_proposal`), `done` (a human step, or a situation the owner finished by hand), `skip` (a plan step), `research` (`web.research`, threads), `draft` (thread mail via `threads.draft_message`), `advance` (set a thread's next action and date), `answer` (a mission's `waiting_user` question), `close`, `snooze`, `dismiss`, `own` ("I'll handle it myself"). The UI renders a verb the same way everywhere; the agent executes a verb the same way everywhere; `situations.act(kind, id, verb, option_id, payload, actor)` is the single implementation both call.

**Options are bound server-side.** A client or the model names an `option_id`; the server re-derives the situation's current options and executes only one it finds there. `payload` is accepted only for verbs whose payload is free text (`answer`, `advance`, the `what` of an `ask`); proposal ids, event ids and assignments always come from the server-built option, never from the request.

**Taking it is not finishing it.** `own` records who took the situation (`owner_member_id`, `owned_at`) and moves it from *needs you now* to *in hand*; it does not close anything. What ends ownership is reality (a finding whose condition no longer appears closes `done/auto` as today; a thread or mission moves on) or the owner's explicit `done`. Findings gain the state `in_hand`: `reconcile` treats it like `open` (the sentence keeps updating, absence still closes it) and never re-adds a row for it. No follow-up nudges on owned situations in this slice.

**Who authors what.**

| Kind | Options | Status note |
|---|---|---|
| finding | Deterministic: the coverage ladder and the finding's own `action`, as today. The ladder's tier-1 driver is an `assign` option; tier-2 outside hand is an `ask`; tier-3 is `self`/`dismiss`. | Argyle |
| insight | Before a plan: next step is `plan`, labelled with the `approach` sentence ("Plan: ask Sarah to take Thursday"). After: each open step is an option — an unbound tool step is `prepare` (labelled with the step text), a bound one is `do`, a human step is `done`, any step `skip`. The highlighted one is the first open step. | Argyle |
| thread | Argyle proposes 1–3 from history and state (`draft` a reply, `advance` with a date, `research`, `close`), typed with the closed verb set; the deterministic set (`advance`, `draft`, `close`) is always present underneath. | Argyle; fallback "Waiting on {counterparty} since {date}; next: {next_action} ({date})" |
| mission | Deterministic from status: `answer` when `waiting_user`, `do` for a waiting proposal, `close` (drop). | Argyle; fallback "{status}: {last step name}" |

**When Argyle writes.** Every situation row carries a revision counter `rev`, bumped by each mutation of the row and by any change to one of its asks (created, sent, answered, withdrawn). `situations.refresh(kind, id)` is requested after a state change, never on read:

- thread: history append (note, sent, received, research), state change, next-action change;
- mission: a step appended, status change;
- finding: opened or reopened (not the per-sweep sentence update);
- insight: created, revived, plan created, a step closed;
- any kind: an ask created, sent, answered or withdrawn; ownership taken.

Requests coalesce: one logical mutation that appends history and changes state (a `send`, say) triggers one refresh, and requests within a two-second window for the same `(kind, id)` collapse to one. The call runs on the existing background thread after the write and never blocks the mutator. It captures `rev` at the start; if the row's `rev` has moved by the time the result arrives, the result is discarded and a fresh refresh is requested. So an older note can never overwrite a newer one.

One call on the `interactive` tier, strict JSON `{"status_note": "...", "options": [{"label","verb","payload"}]}`, 20 s timeout. Result cached on the row with `note_ts`, `note_rev` and `note_source: argyle`. A failure, timeout or cap leaves the deterministic fallback with `note_source: fallback`. Options returned with a verb outside the closed set, or a payload the verb cannot execute, are dropped. **Deterministic options are computed from current state at read time**, independent of the note, so the card is actionable while a refresh is pending or has failed.

**What the model sees.** The row's own facts only: title, state, dates, people, the last ten history lines or steps, open asks. Never DMs, never gift records — the Mind's structural boundaries, enforced the same way (the module never imports a DM accessor; a test asserts on its source).

## Section 2 — The ask

**The ask is a sentence first.** An `ask` option carries `{to: {name, member_id?, contact_id?}, what: "drive Kate to practice Thursday 4pm", unlocks: {action_type, payload} | None}`. The card shows it as the sentence — **Ask Sarah to drive Kate Thursday.** In conversation the person says it. Either way the next question is the channel.

**Every channel yields a draft; the channel decides only how it leaves.**

| Channel | Offered | How it leaves |
|---|---|---|
| `chauffeur` | `to` is an active member | Argyle posts the draft as a DM from the asker, with Yes / No buttons that answer the ask. |
| `email` | always | Draft (subject + body) with Copy; a `mailto:` link pre-filled when an address is known. "Sent it" marks the ask sent. |
| `text` | always | Draft with Copy; an `sms:` link when a number is known. "Sent it" marks it sent. |
| `in_person` | always | A short draft of what to say; "Asked them" marks it. |

A known address or number never gates a channel; the card offers a one-tap "add a number or email" to the contact or member record as a convenience, nothing more.

**Drafting.** `asks.draft(ask, channel)`: one `interactive` call, returns `{subject?, body}` in the asker's voice, at most 80 words, facts only from the ask (what, when, where). Thread drafts keep `threads.draft_message` (it already has thread context) and record into the same ledger. Fallback template when the call fails: "Hi {name} — could you {what}? Thanks, {asker}".

**The ledger.** One table `asks`:

```
ask = {
  id, situation_kind, situation_id,
  to_name, to_member_id?, to_contact_id?,
  what, channel: 'chauffeur' | 'email' | 'text' | 'in_person',
  draft_subject?, draft_body?,
  asked_by (member id), asked_at,
  sent_at?,                      # when it left (posted, copied-and-confirmed, said)
  state: 'drafted' | 'sent' | 'yes' | 'no' | 'withdrawn' | 'expired',
  answered_at?, answered_by?,    # the member who tapped, or the asker reporting
  unlocks?: {action_type, payload, situation_rev, fingerprint?},   # server-built
  applied_at?, outcome?: 'applied' | 'superseded' | 'stale' | 'failed',
  unlock_error?: str,
  nudges_sent, rearmed_at?, event_id?, legacy_id?   # coverage_asks fields, carried
}
```

**`asks` is the only ledger.** `coverage_options` keeps every public function (`start_ask`, `answer_ask`, the nudge sweep, undo, expiry, rearm) and every endpoint and DM button it serves, but they become adapters over `asks`: `waiting` → `sent`, `covered` → `yes` + `outcome: applied`, `declined` → `no`, `expired` → `expired`, undo → back to `sent` with `rearmed_at`. Migration is idempotent, keyed by `legacy_id`; a legacy row's situation is the finding identity `unassigned:{event_id}`, derived from its `event_id`. The old table is read once, then retained for one release as recovery only — nothing reads or writes it after migration. The existing coverage tests run against the adapters unchanged.

**Who may do what to an ask.** Three different acts, three gates:

- *Create* an ask: parent or adult (the usual write gate).
- *Answer your own ask*: the member it is addressed to, whatever their role — a helper or a child who is sent Yes/No buttons can use them. The answer endpoint checks `to_member_id == actor` for this path.
- *Report someone else's answer* ("she said yes"): the asker, or any parent/adult.

Answering never carries authority to change anything; **applying** does, and it always runs under the asker's identity (a parent or adult by construction), the way an approved proposal runs under its approver.

**Closing the loop.** An ask closes by the member's Yes/No tap on the Chauffeur DM; by the asker's "She said yes / no" tap on the card (every channel); or by the agent, told in conversation. **No** returns the situation to its options with that person marked "asked, said no" on this situation only — no memory beyond it. Auto-detection of a reply from inbound mail is sub-project 3.

**Yes, then applying.** The person's yes and what the app did with it are two facts, kept separately:

1. The ask records `state: yes`, `answered_at`, `answered_by` under the storage lock, only if it was `sent` or `drafted`; a second yes is a no-op that returns the recorded outcome (idempotent retries, duplicate taps).
2. `unlocks` was built by the server when the ask was created and carries the situation's `rev` and, for event asks, the finding's fingerprint. Applying validates them against the present: the situation still open, the fingerprint unchanged (the event has not moved), no sibling ask on the same situation already applied.
3. Applying is a single claim under the lock: the first ask to apply writes `applied_at` and `outcome: applied`; any later yes on the same need records `outcome: superseded` and the card says so ("Mike also said yes — Sarah already has it; let him know"). A yes that arrives after the event changed records `outcome: stale` and the situation's next step becomes "confirm with {name}: the time moved". A failed apply records `outcome: failed` with `unlock_error` and the next step becomes "finish by hand: {what}".
4. The situation re-reads after any outcome.

A `yes` is never overwritten by an outcome; the ledger line reads "Sarah said yes Thu 9:40 — covering" or "— already covered by Mike".

**Visible everywhere.** The card lists the situation's asks: "Asked Sarah by text Thu 9:10 — waiting", "Mike said no Wed". The DM heads-up for a finding gains the same clause.

## Section 3 — Surfaces

**One builder.** `static/situations.js` exposes `Situations.cardHtml(situation, ctx)` and `Situations.act(situation, option)`. Alpine pages and the PWA's vanilla renderers both call it (the `_typedDetailsHtml` precedent in the design guide). The card: title · state and since · status note in muted text (attributed to Argyle; nothing shown there when the note is a fallback) · **the next step as the one primary button** · the other options as quiet buttons · the ask ledger lines · a "details" disclosure. The panel and kiosk renders (`?panel=true`, the wall) draw the card read-only; the lens never writes.

**The Needs you lane.** Findings and insights are the same thing to a person — something that needs them — so they share one lane ranked by `situations.rank()`: `decide` findings by due, then `approve`, then insights by confidence, then `fyi`. It renders on:

- **/mind**, replacing the insight lane. The page keeps its settings, counters, history and the held-back line.
- **the PWA Family tab**, replacing "Argyle noticed". Viewer gates unchanged: kids see non-sensitive insights only; findings are parents and adults.
- **the board tile** (`_tile_mind` becomes the Needs-you tile), read-only.

This is the first hand path findings have had: Handle, Dismiss, the ask flow.

**/threads, rewritten.** The page is the lane of thread cards grouped *needs you now* (stalled, or a due next action) → *waiting on them* → *moving* → *closed* (folded). A card's details hold everything the page holds today: the history timeline, the draft/send form (household address, unchanged), notes, the edit fields, Work-this. "+ New thread" opens the existing create form as a sheet. The settings drawer is untouched.

**/missions, rewritten.** The active mission is a situation card: status note; next step = answer the question, approve the waiting proposal, or nothing yet; details hold the transcript and artifacts. The launch form stays. Grouping is by `needs_attention`, derived independently of engine status: a mission with an open `proposal` step or in `waiting_user` sits in the actionable group whether it is `running`, `done` or `blocked`; only a mission with nothing left to decide moves to history, as a card with its summary. Settings drawer untouched.

**PWA House tab** threads use the same card, owner's threads only, as now.

**The DM heads-up** for a finding adds the next step and any ask: "🚨 No driver yet: Soccer Thu 4:00 → Ask Sarah (asked Mike by text Wed, said no)". The action cards are unchanged.

**Endpoints.** `GET /api/situations` (ranked, viewer-filtered, optional `kinds=`), `GET /api/situations/{kind}/{id}`, `POST /api/situations/{kind}/{id}/act` with `{verb, option_id, payload}`; `POST /api/asks` (create + draft), `POST /api/asks/{id}/sent`, `POST /api/asks/{id}/answer`. Every existing endpoint stays; the new ones compose them, so current tests and tools keep working. Write endpoints carry the same parent/adult gate as the Mind endpoints; sensitive insights keep their parents-only render.

## Section 4 — Agent tools and hand-path parity

Every button on the card has a verb; every verb is one tool. Added once to the registry (`agent_tools_v2`, which is the only stack since v2.499.296):

| Tool | Does | Mirrors |
|---|---|---|
| `list_situations(kinds?, limit?)` | Ranked, viewer-filtered situations: title, state, status note, next step, open asks. | The lane |
| `explain_situation(kind, id_or_title)` | The full card as text: note, every option, the asks so far. | Opening a card |
| `act_on_situation(kind, id_or_title, verb, option_id?, payload?)` | Runs a verb through the same `situations.act` the button uses. | The option buttons |
| `start_ask(kind, id_or_title, to_name, what, channel)` | Creates the ask, returns the draft; posts it when the channel is `chauffeur`. | "Ask Sarah…" and the channel pick |
| `mark_ask_sent(ask_id)` / `answer_ask(ask_id, yes_or_no)` | Ledger updates; `yes` runs `unlocks`. | "Sent it" / "She said yes" |

Rules carried over unchanged: parent/adult only for anything that writes, except answering an ask addressed to you (Section 2); `acting_member` resolved at dispatch, never from the model; option ids and unlocks are server-bound, never model-supplied; outside-family text and email are drafts the person sends; `chauffeur` DMs go on the person's say-so. The existing tools (`list_open_findings`, `list_insights`, `dismiss_insight`, the thread tools, `launch_mission`) stay as they are.

**Fuzzy by title.** `explain_situation`, `act_on_situation` and `start_ask` accept a title fragment and resolve it the way `assign_driver_to_event_fuzzy` does, refusing when ambiguous and naming the candidates.

**Parity, checked both ways.** A test walks every verb the card can render and asserts a tool reaches it, and walks every tool and asserts the card renders its verb. Nothing agent-only, nothing UI-only.

**Not in this slice:** the "what needs my attention?" entry phrase and its ranking across all four kinds in conversation, Assist/voice wording, reply detection from inbound mail — sub-project 3 builds on `list_situations` and `start_ask` as they land here.

## Section 5 — Budget, failure, tests, migration

**Budget.** Status notes: one `interactive` call per state change, cap `situation_cap_notes` (default 60/day). Drafts: one call per ask, cap `ask_cap_drafts` (default 40/day). Both registered in `settings_registry.py` on the Mind page and counted with the existing `_bump_call` idiom. A capped call means fallback text, never a missing card. No new calls on reads, ticks or sweeps.

**Failure honesty.** A fallback note is marked `note_source: fallback` and the card leaves Argyle's line empty; the deterministic facts are always there. A failed draft falls back to the template. A failed `unlocks` on `yes` leaves the ask at `yes` with `unlock_error` set and the situation's next step becomes "finish by hand: {what}" — the person's yes is never lost because an assignment call failed.

**Migration.** `coverage_asks` → `asks` on first boot (kind `finding`, nudge fields intact), old table retained one release. Rows without `status_note` get the fallback on first read; no backfill calls are made.

**Tests.** Own tests plus named related, per the project's gate rule:

- `test_situations.py`: view for each kind; rank order; fallback notes; refresh on state change only (a sentence update on a finding makes no call); caps; verbs outside the closed set dropped; DM accessors never imported.
- `test_asks.py`: every channel offered regardless of address; a draft for every channel; ledger states; the three answer gates (own ask by any role, report by asker/parent, create by parent/adult); `yes` applies once — duplicate taps, a competing sibling yes (`superseded`), a moved event (`stale`), a failed apply (`failed`), each with the recorded outcome; `no` returns to options; `coverage_asks` migration idempotent with nudges, undo, expiry and the legacy DM buttons working through the adapters.
- `test_situations.py` also covers: `own` moves to in hand without closing, a finding in `in_hand` is never re-added by the sweep, `done` closes; refresh coalescing and the out-of-order result discarded by `rev`; options bound server-side (an unknown or stale `option_id` is refused).
- `test_situation_tools.py`: parity walk both ways; fuzzy resolve and ambiguity refusal; write gates.
- Live tests (`*_live.py`, rendered pixels): the /mind lane, /threads, /missions, the PWA Family lane, the board tile.
- Existing, unchanged: `test_watchers`, `test_mind_*`, `test_threads_*`, `test_missions_*`, `test_negotiation_watcher`, `test_coverage_*`.

**Acceptance scenarios** (end to end, each its own test, each exercised with duplicate taps and the reversed refresh order):

1. Text an outside helper from a finding → "Sent it" → "She said yes" → coverage applied exactly once → the finding retires by absence on the next sweep.
2. A helper receives a Chauffeur ask → answers Yes from their own identity → the ledger updates and the assignment is applied under the asker's authority.
3. A mission finishes with a proposal still pending → it stays in the actionable group → approving the proposal resolves it and it moves to history.

**Two builds under this one spec.**

1. `situations.py`, `asks`, the tools, the Needs-you lane on /mind, the PWA Family tab and the board tile.
2. /threads and /missions rewritten on the card, the PWA House threads, the DM clause.

## Review resolutions (2026-10-09)

Seven findings from design review, all accepted and folded in above:

1. Answer gates: creating, answering your own, and reporting another's answer are three gates; applying runs under the asker. Options and unlocks are server-bound.
2. Yes and applying are separate facts; applying is an atomic claim validated against `rev` and fingerprint, with a recorded `outcome` (applied, superseded, stale, failed) and idempotent retries.
3. `self` became `own`: ownership without completion; findings gain `in_hand`; `done` is the completion act.
4. `asks` is the only ledger; `coverage_options` becomes adapters with a state mapping, idempotent migration by `legacy_id`, legacy buttons kept working.
5. Refresh carries `rev`, coalesces per logical mutation, discards superseded results, and is triggered by ask changes; deterministic options are computed at read time.
6. Insight verbs cover every stage: `plan`, `prepare`, `do`, `done`, `skip`.
7. Mission grouping is by `needs_attention`, independent of engine status.

Three end-to-end acceptance scenarios were added to Section 5.

## Out of scope (named so they stay out)

- Any per-person preference or history beyond the ask ledger (locked decision 1).
- Sending personal mail or texts from the app (locked decision 4); per-member "send as me".
- Reply detection from inbound mail; the conversational "what needs my attention?" entry; voice wording (sub-project 3).
- New LLM calls on read paths, ticks or sweeps.
- Changing what findings exist or when they fire; changing the Mind's think cadence or prompt beyond what sub-project 1 did.
