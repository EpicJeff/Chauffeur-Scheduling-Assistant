# Triage and replies — the one thing, held in conversation; a vendor's reply read once

Date: 2026-10-10
Status: Approved in conversation; implementation plan pending
Sub-project 3 of the agentic-layer plan (1 = dismissed-is-dismissed, shipped v2.499.297; 2 = situations, builds 1 and 2 shipped v2.499.303–.321)

## Problem

Sub-project 2 gave every finding, insight, thread and mission one shape (a situation) with a status note, a highlighted next step, a closed verb set and an ask ledger, and six agent tools over it. Two gaps were named there and left for this sub-project:

- **Conversation is not yet the primary way in.** "Hey Argyle, what needs my attention?" reaches `list_situations`, which returns up to ten lines ranked for the lane, with threads and missions sitting flat below findings and insights. There is no single most-pressing answer in a spoken shape, and no ranking that compares a stalled thread with an uncovered ride. The conversation holds no focus: "handle it", "ask Sarah by text", "she said yes" each make the model re-resolve a title fragment, which is exactly the tool-selection weakness of the Lite tier the field feedback named.
- **Voice is half-blind.** `/api/v2/converse` passes no `acting_member`. `situations.can_see` hides findings and threads from a viewer with no role, so a voice triage today returns only non-sensitive insights, and `act_on_situation` and `start_ask` refuse voice outright. Yet the same voice path is already offered the admin scheduling tools as the "trusted open-admin context". The two rules disagree.
- **A reply is filed, never read.** `threads.match_inbound` lands a counterparty's mail on its thread (a `received` history entry; `waiting` → `open`) and stops. Nobody learns what the reply said until they open the thread. A thread send creates no ask ledger row, although the situations spec said it would, so there is nothing for a reply to answer.

## Decisions made in this conversation

1. **Voice speaks and acts as the parent of record.** The same nomination the admin pages make (`_approver_of_record`): a surface that carries no person reads and writes as the household's parent of record. This matches what voice already does for scheduling tools. Accepted trade-off: a child at the satellite is heard as the parent, as today. One guard follows from a speaker being in a room, not in a hand: a spoken answer never includes a sensitive insight.
2. **Reply detection is intake mail on threads only.** Typed replies under a Chauffeur ask card and forwarded replies for personal email or text asks were offered and declined for this sub-project.
3. **Triage returns one thing and holds it as focus.** One or two sentences, the most pressing situation and its next step. That situation becomes the conversation's focus; follow-ups resolve against it without a title. "Next" moves down the list.
4. **A reading records, never applies.** A reply Argyle reads as a clear yes or no moves the ask to `yes`/`no` with `answered_by: argyle`, changes the thread's next step and tells the owner. Nothing is booked, advanced or changed by the reading itself.

Carried over unchanged from sub-project 2: no people model; draft, approve, send for everything that leaves the family; asks never send mail from the app (threads keep the household-address send); no new LLM calls on reads, ticks or sweeps; options and unlocks bound server-side; the closed verb set.

## Approach

Three approaches to holding focus were weighed:

- **Focus on the conversation row (chosen).** The triage tool writes `focus` onto the conversation record that every entry point already keeps (`/api/chat` conversations, voice `voice-<id>`, the Argyle DM channel). The router injects one FOCUS line into the system prompt; the situation tools take their reference optionally and fall back to it. Deterministic, Lite-safe, survives turns.
- **Prompt-only.** The model infers the current one from recent history. Nothing to build, and it fails where Lite is weakest. Rejected.
- **A per-actor triage session across channels.** Voice then phone would continue one session. Two parents on two channels collide and voice has no member. Over-built. Rejected.

Reply reading sits inside the ingest poll, where mail is already read with LLM spend, and never anywhere else.

## Section 1 — Triage and focus

### `next_situation` — the one thing

New agent tool `next_situation(skip_current: bool = false)`, in the registry beside the six situation tools and in `TERMINAL_ACTION_TOOLS` (its message is the complete spoken answer; no concluding LLM round, which matters on voice).

It ranks every situation the actor may see with `situations.triage_rank` (below), takes the first (or the next after the focus when `skip_current`), and returns one sentence built deterministically with no model call:

> "{title}. {status note, when Argyle wrote one}. Next: {next step label}{, asked {name} by {channel}, waiting | said yes | said no}."

Examples: "No driver yet for soccer Thursday at 4. Next: ask Sarah to drive Kate — Mike was asked by text Wednesday and said no." / "Pest control has been quiet nine days. Next: set the next step." With nothing to say: "Nothing needs anyone right now."

The tool sets the conversation's focus to that situation and remembers the cursor (its position in the ranked list). `list_situations` stays as it is for "what's open?" and the lane.

### One rank across four kinds

`situations.triage_rank(rows)` orders what a person should hear first:

| Tier | What | Within the tier |
|---|---|---|
| 0 | Overdue or due within 24 hours: a `decide` finding by `due`, a thread whose `next_action_at` has passed, a mission in `waiting_user` | due, then since |
| 1 | `decide` findings without a near due; stalled threads (`is_stalled`) by days stalled; missions with a pending proposal | since |
| 2 | `approve` findings | due, then since |
| 3 | insights | confidence descending |
| 4 | `fyi` findings; everything else | since |

The existing `rank()` keeps the lanes exactly as they are; `triage_rank` is for the ear. A test pins a fixture with one row of each kind in each tier and the resulting order.

### Focus on the conversation

`focus = {kind, id, title, cursor, set_at}` is stored in one app-state map, `triage_focus`, keyed by the conversation key: `conv:<conversation_id>` for the widget, `voice:<conversation_id>` for HA Assist, `channel:<channel_id>` for the Argyle DM and @argyle (a chat channel is not a row in the conversations table, so the conversation row cannot carry it for every entry). Entries older than 24 hours are pruned on every write, so the map never grows. Set by `next_situation`, and by any situation tool that resolved a situation by reference (`explain_situation`, `act_on_situation`, `start_ask`): naming a thing makes it the current thing. Cleared by `done`, `dismiss`, `close` and `snooze` on the focused situation (the thing is gone from the list); `next_situation` then continues from the cursor, which it also advances past situations that have since left the list.

The router injects one line when a focus exists and still names a live situation:

> FOCUS: {kind} "{title}" — next step: {label}. "Handle it", "do that", "ask X by Y", "she said yes", "sent it", "next", "skip it" refer to this one unless another is named.

A focus whose situation has closed is dropped silently and the line is not injected.

The entry points already carry an id: `/api/chat` (the widget's `conversation_id`), `/api/v2/converse` (HA's `conversation_id`), and the Argyle DM / @argyle path (the channel id). Each passes a `focus_key` to `process_agent_request`, which hands it to the situation tools at dispatch the way it hands them the actor; the model never sees or supplies it. A voice turn with no `conversation_id` has no focus: `next_situation` still answers, the follow-up must name the situation, and the sentence ends with the title so the person can.

### Focus-aware tools

- `explain_situation`, `act_on_situation`, `start_ask`: `ref` becomes optional; absent, the focus is used; absent with no focus, the refusal says "Which one? Ask me what needs your attention first."
- `answer_ask(answer, ask_id?)` and `mark_ask_sent(ask_id?)`: `ask_id` optional; absent, resolve to the focus situation's one live ask (`drafted` or `sent`). Two or more live asks: refuse with their names ("Sarah by text, or Mike on Chauffeur?"). None: refuse plainly.
- Every refusal names the way out. No tool guesses between candidates (the `assign_driver_to_event_fuzzy` rule).

The parity test from sub-project 2 (every card verb reachable by a tool and back) is extended: a ref-less call on every focus-aware tool reaches the same `situations.act` path as a named one.

### Voice is the parent of record

In the router's dispatch for the situation tools (the branch that resolves `actor` "at dispatch, never from the model"): when `acting_member` is None, not driver mode, not `propose_only`, the actor becomes the household's parent of record — a `services`-level `approver_of_record()` lifted out of `main._approver_of_record` so the router does not import `main`; `main` keeps calling the same function. No parents on record: the tools refuse as they do now. On `propose_only` the situation write tools are not reachable at all (they are not in `PROPOSE_ONLY_TOOLS`; `next_situation` and `list_situations` are reads and are added to `PROPOSE_ONLY_READS`).

Asks created from voice are `asked_by` that parent; Chauffeur asks post as that parent's DM; the ledger reads as if the parent had tapped. A test pins: voice (no actor) → `start_ask` succeeds as the parent of record; voice with `propose_only` → refused; a resolved child via @argyle → refused as today.

### Never spoken: sensitive insights

`list_situations(viewer, spoken=True)` and `triage_rank` under `next_situation` drop any insight with `sensitivity: sensitive`, whatever the viewer's role. The card, the lane and `explain_situation` by explicit reference are unchanged (a parent on their own phone may still ask about it by name; that is a hand, not a room). The structural test asserts no sensitive row reaches the spoken sentence from any entry point.

### Nothing else in the prompt changes

The system prompt gains the FOCUS line only. The tool descriptions already carry the entry phrases ("what needs my attention?", "anything I need to deal with?"); `next_situation` takes those and `list_situations` keeps "what's open", "everything outstanding".

## Section 2 — A reply, read once

### Thread sends become ledger rows

`threads.send_drafted` (the only function that can send) records an ask on success: `situation_kind: thread`, `situation_id`, `to: {name: counterparty, email: counterparty_email}`, `channel: email`, `state: sent`, `sent_at` now, `sent_via: household`, `draft_subject`/`draft_body` = what went out, `what` = the `intent` given to `draft_message` when one was given, else the subject line. Never `unlocks` (there is nothing to apply). `asked_by` = `who` when it is a member, else the parent of record. The card's ledger line reads "Emailed Pest Co Thu — waiting". Sending from the card's details form, the agent's `draft_thread_message` + send, and the thread page all pass through `send_drafted`, so there is one place.

A thread may hold several `sent` asks (two mails, no reply). The reading answers the newest live one.

### One reading per matched reply

`threads.match_inbound` files the `received` entry as today. Then `replies.read(thread_id, entry)` (new module `services/replies.py`) runs, inside the ingest poll's thread and budget:

- One `interactive` call, strict JSON `{"answer": "yes" | "no" | "question" | "info" | "unclear", "summary": "..."}` (summary at most 20 words), 20-second timeout, `workflow='replies.read'`.
- Input: the reply text (first 1,500 characters), the thread title, the live ask's `what` when there is one. Nothing else: no DMs, no other threads, no member records. The module never imports a DM accessor (the Mind's boundary; the source test from sub-project 2 is extended to this module).
- Cap `reply_cap_reads` (default 40/day), registered in `settings_registry.py` on the Mind page beside the note and draft caps, counted with the existing `_bump_call` idiom. The poll's own `ingest_daily_limit` counts this request too, since it is an intake request.
- Idempotent by the mail's `message_id` (already fetched): a reply read once is never read again, including on a rescan.

The result is stored on the history entry as `reading: {answer, summary, ts, source: argyle}` and the thread's `rev` is bumped, so the status note refreshes through the existing coalesced path. On failure, timeout, cap or no key: no `reading`, nothing invented, and the deterministic next step below still names the reply.

### Record, never apply

With exactly one live ask on the thread and a clear `yes` or `no`:

- `asks.record_reading(ask_id, answer, message_id)`, a new module-level function with no actor gate, called only from `replies.read` and never exposed as a tool or endpoint: under the storage lock, an ask in `sent` (or `drafted`) moves to `yes`/`no` with `answered_by: 'argyle'`, `read_from: <message_id>`; a `yes` records `outcome: manual` ("apply by hand"), because no thread ask carries `unlocks`. `apply` is never called from a reading. `answer()` is untouched.
- `question`, `info`, `unclear`, no live ask, or two or more live asks: the ask stays `sent`. Only the history entry and the next step change.
- An ask already `yes`/`no`/`withdrawn` is left alone; the reading still lands on the history.

### Next step from the reading

Deterministic, computed at read time by `_options_thread` from the newest `received` entry and its reading; the highlighted option is:

| Reading | Next step (verb, label) |
|---|---|
| yes | `advance` — "Confirm with {counterparty}: {summary}" (payload pre-fills the next action with the summary) |
| no | the thread's ordinary options; the ledger line reads "{counterparty} said no" |
| question | `draft` — "Reply: {summary}" (the draft intent is the summary) |
| info, unclear | `advance` — "Read their reply: {summary}" |
| none (cap, failure, no key) | `advance` — "Read their reply" with the first line of the mail |

The thread's `state` stays `open`, as `match_inbound` already sets it. The reading's option is highlighted only while the newest history entry is that `received` entry; once the person acts (a note, a send, an advance), the ordinary options return.

### One message to the owner

The thread owner (`owner_member_id`; the parents when none) gets one DM from Argyle:

> "{counterparty} replied on '{title}': {summary} → {next step label}."

With no reading: "{counterparty} replied on '{title}' — read it." The DM honours the watcher gate: posted at once inside the waking window (`QUIET_END_HOUR <= hour < QUIET_START_HOUR`), otherwise the entry is marked `dm_pending` and `run_watchers` posts it on the first sweep inside the window, then clears the mark. Exactly one DM per `message_id`; a failed post keeps the mark for the next sweep. No DM for a reply on a closed thread (the reply is still filed).

### Hand path: "Argyle got it wrong"

The card shows the reading under the ask's ledger line: "Argyle read it as yes — 'Friday works'." with a quiet button **Argyle got it wrong**, which runs the new verb `unread` on the thread situation: the ask returns to `sent` (`answered_at`/`answered_by`/`read_from` cleared), the history entry keeps the reply and keeps the reading with `disputed: true`, the next step returns to "Read their reply", and the thread's `rev` bumps. `unread` joins the closed verb set and is reachable in conversation ("that reply wasn't a yes") through `act_on_situation`. Parents and adults only, like every write. It applies only to an ask whose `answered_by` is `argyle`; a human-tapped or reported answer is refused ("that was answered by {name}, not read").

## Section 3 — Surfaces

- **Voice** (HA Assist): "what needs my attention" → one sentence; "handle it" / "ask Sarah by text" / "she said yes" / "next" / "skip it" / "dismiss it" resolve against focus. No card. The Chauffeur ask on voice posts as the parent of record.
- **Chat widget and @argyle**: the same, with the ask draft shown as today.
- **The card** (`static/situations.js`): the reading line and the **Argyle got it wrong** button under a thread ask's ledger line; the "Emailed {name} — waiting" ledger line for household sends. No other change. The /threads details row shows the reading beside the `received` entry in the timeline.
- **The DM**: the one reply line described above.

## Section 4 — Tools and endpoints

| Tool | Does | Mirrors |
|---|---|---|
| `next_situation(skip_current?)` | The one most pressing situation as a sentence; sets focus and cursor. Terminal. | The top of the lane |
| `explain_situation(ref?)`, `act_on_situation(ref?, verb, ...)`, `start_ask(ref?, ...)` | As before; `ref` falls back to focus. | The card |
| `answer_ask(answer, ask_id?)`, `mark_ask_sent(ask_id?)` | As before; `ask_id` falls back to the focus situation's one live ask. | "She said yes" / "Sent it" |
| `act_on_situation(ref?, 'unread')` | Reverts a reading-answered ask. | **Argyle got it wrong** |

No new endpoints: the card's **Argyle got it wrong** posts `POST /api/situations/thread/{id}/act {verb: 'unread', option_id}`. The thread page's send keeps `POST /api/threads/{id}/send`, which now records the ask through `send_drafted`.

## Section 5 — Budget, failure, migration, tests

**Budget.** `reply_cap_reads` 40/day (new, Mind page); `situation_cap_notes` and `ask_cap_drafts` unchanged. `next_situation` and focus make no LLM call. The reading runs only inside the ingest poll, after a thread match, once per `message_id`. No new calls on reads, ticks or sweeps.

**Failure honesty.** No reading → "Read their reply" with the first line of the mail; the owner's DM says a reply came in. A reading the person disputes is kept with `disputed: true`, never deleted. A thread ask a reading answered reads "Argyle read it as …" in the ledger, never "Sarah said yes" — the person can always tell a tap from a reading.

**Migration.** None. Existing threads with `sent` history entries and no ask rows are left as they are; a reply to one of those gets a reading, a next step and a DM, with no ask to answer. New sends create rows from the day this ships.

**Tests.** Own tests plus named related, per the project's gate rule:

- `test_triage.py`: `triage_rank` tiers across all four kinds with a fixture row per tier; the spoken sentence for each kind with and without a note and with asks; no sensitive insight in a spoken list from any viewer; focus set by `next_situation` and by a named tool call, cleared by `done`/`dismiss`/`close`/`snooze`, cursor advances past a closed row; ref-less `explain`/`act`/`start_ask` resolve to focus and refuse with the way out when there is none; ref-less `answer_ask`/`mark_ask_sent` resolve one live ask and refuse naming two; voice (no actor) acts as the parent of record, `propose_only` refuses, a child via @argyle refuses; the FOCUS line present exactly when a live focus exists; `next_situation` is terminal.
- `test_reply_reading.py`: `send_drafted` records the ask with `what` from intent else subject and never `unlocks`; each reading outcome (yes → `yes`/`manual`/`answered_by argyle`; no; question; info; unclear; no live ask; two live asks; already answered ask untouched); idempotent by `message_id` across a rescan; cap, failure and no key leave "Read their reply" with the mail's first line; the next step per reading and its return to ordinary options after the person acts; exactly one DM per reply, deferred through quiet hours and flushed by `run_watchers`, none on a closed thread; `unread` reverts the ask, keeps the disputed reading, and refuses on a human-tapped answer; the module never imports a DM accessor.
- `test_situation_tools.py`: parity walk extended with `next_situation` and `unread`; ref-less calls walk the same path.
- Live (`*_live.py`): the reading line and **Argyle got it wrong** on /threads and on the PWA House thread card.
- Existing, unchanged: `test_threads_*`, `test_email_ingest`, `test_email_backlog`, `test_situations*`, `test_asks*`, `test_agent_v2_bridge` (the registry grows by one tool, never loses one), `test_watchers`.

**Acceptance scenarios** (end to end, each its own test):

1. Voice, no identity: "what needs my attention" → the uncovered ride in one sentence → "text Sarah and ask her" → the draft, ask `drafted` as the parent of record → "sent it" → `sent` → "she said yes" → `applied`, one assignment, focus cleared when the finding retires.
2. "Next" twice walks the ranked list in tier order and never repeats a situation that closed between turns.
3. A thread mail goes out from the details form → ask row `sent` → the vendor replies "Friday at 9 works" → one reading → ask `yes`/`manual`, next step "Confirm with Pest Co: Friday 9am", one DM to the owner, status note refreshed → the owner taps **Argyle got it wrong** → ask `sent`, next step "Read their reply", reading kept as disputed.
4. The same reply with the cap reached → no reading, next step "Read their reply: Friday at 9 works", the DM says a reply came in; the next poll does not read it again.

**One build under this spec**, split into two tasks in the plan: (1) triage, focus, voice; (2) thread ledger rows, reading, DM, `unread`.

## Out of scope (named so they stay out)

- Typed replies under a Chauffeur ask card ("sure", "can't") — declined for this sub-project.
- Forwarded replies for personal email and text asks — declined.
- `In-Reply-To` / `References` header matching; the counterparty address stays the key, as `match_inbound` already works.
- Any voice identity beyond the parent of record (room → person, spoken names, PINs).
- Applying anything from a reading; thread asks with `unlocks`.
- A proactive "here is what needs you" at a time of day (no new tick).
- Per-member "send as me"; sending personal mail from the app.
