# Submit gate — a browse may book or submit a form, on a parent's tap

**Date:** 2026-10-11. **Status:** approved in conversation; revised the same day after the user's review (five findings, all taken: the ask id, the form's state as the thing approved, attempt and outcome, the payment path, every activation method); awaiting the user's second review.
**Builds on:** `2026-10-10-browse-missions-design.md` (all three builds shipped, device-verified 2026-10-11).

## Problem

The browse arc reached the Dots result on the device: the household contact card released on a tap, the guest form filled, the reCAPTCHA passed on the headed browser, the trip charge and the real appointment slots read off the screen. It stopped one click short of the job because the spec locked "nothing is ever booked, paid, submitted or sent by the browser" and the runner enforces it in code: a click on Book, Confirm, Submit, Schedule now, Pay or Checkout ends the run `blocked: would submit`.

The user revised that decision on 2026-10-11. Dots booked nothing only because the user told it not to in conversation, not by rule. The power of this kind of agent is that it can do so many things. Booking an appointment with the person's approval is harmless; buying something or making a payment is a further step that needs layered approval; both must be possible. A person makes the commitment; the browser carries it out.

## Decisions made in this conversation

- **Scope of this slice:** a general "submit with approval" gate. Booking an appointment is one case; a permit application, a school form, a warranty registration are the same shape. Payment is not in this slice: a card-number field still ends the run and hands the person the page. Payment gets its own slice with its own layers.
- **Who says yes, and how:** one parent, by tap, on the Missions page, the thread card or the DM card. The approval names the exact button text, the page and the facts on screen (the slot, the price), and the browser may click only while the page still shows those facts. Spoken or typed "book it" never counts in this slice, for the same reason a release is tap-only: the chat model once approved a release from "enter my information". Voice approval arrives with the voice-identity slice (a spoken PIN, three levels of identity), and the voice-fingerprint slice after it.
- **The order of the next slices:** this gate first, since it finishes the dishwasher thread already open; then voice identity (PIN); then the STT wrapper that tags the speaker's voice, keeps a PIN session honest and lets Argyle greet the person by name.

## Section 1 — The wall becomes a question

**Two word lists, two paths (`services/browse.py`).** The single `STOP_WORDS` list splits:

- `SUBMIT_WORDS`: submit, book, booking, schedule now, confirm, reserve, send, apply, register, sign up, finish booking, complete booking, place request. A control with these words is a commitment the person may approve.
- `PAY_WORDS`: pay, payment, checkout, purchase, buy, order now, place order, charge, complete purchase. A control with these words is money. It ends the run `blocked: payment`, with or without a card field on the page, and no approval in this slice lifts it. A saved card, an invoiced account, a "buy with one click" are exactly the cases this path exists for.

The card-field guard (card number, CVC, expiry, `cc-*` autocomplete) is unchanged and also `blocked: payment`.

**Every way to press a control is one check.** The runner classifies an action before running it:

- a click or double-click: the control under the point (`elementFromPoint`, then its closest button, submit input, link or `role=button`);
- Enter: the focused element's form's default submit control (as today);
- Space, or Enter on a focused button: the focused element itself when it is a button, a submit input or `role=button`;
- the model's stated intent, for any of the above.

If the control's text or the intent matches `PAY_WORDS`: `blocked: payment`. If it matches `SUBMIT_WORDS`: the gate below. If the control is a form's submit control (`type=submit`, or the default submit control of a form, or the only button in a form) and its text matches neither list nor `NAVIGATION_WORDS` (next, continue, search, find, go, filter, sort, show, view, see, select, choose, back, previous, close, cancel, accept, got it, ok): the runner cannot classify it, and an unclassified final action is a commitment: the gate below. "Send application", "Request a quote", "Finish" all land here. A control that matches `NAVIGATION_WORDS` runs as today (a multi-step "Next" is not a booking).

**The gate returns a question, not a wall.** An action that reaches the gate does not run. The run ends with the new outcome `needs_submit` and the report carries a `submit` record, the thing the person is asked to approve:

```
submit = {
  button: str,        # the control's text as the page shows it ('Book appointment')
  url: str,           # the page the control is on
  state: {            # the control's own form, read from the DOM at the stop
    fields: {name: value},     # every text-like input's current value (passwords and card fields excluded)
    selected: [str],           # the labels of checked radios and checkboxes and of selected options, in page order
    text: str,                 # the form's visible text, whitespace collapsed, first 1,500 characters
  },
  facts: {str: str},  # the model's LEARNED: pairs so far, latest value per key: the human summary (slot, price)
  intent: str,        # the model's words for the action, if any
}
```

`state` is the transaction. A scheduling page that shows Tuesday in a paragraph while Thursday is selected has Thursday in `selected`; a page whose price moved has a different `text`. The model's `facts` are shown to the person but never used as the check. The model also gets an explicit exit, as with `NEED:` and `WALL:`: when the only way forward is such a control, it ends its report with `SUBMIT: <button text>`; the runner finds the control by that text, reads its form's state and returns `needs_submit` the same way (no control with that text: `needs_submit` with an empty state, and the question names the button only).

**The approved action, guarded.** `run()` takes `approved: dict | None`, the `submit` record a parent approved, plus `on_attempt`, a callable the mission engine supplies (Section 2). With `approved` set the runner permits exactly one action that the gate would stop, and only when, at the moment of the action:

- the control's text equals `approved.button` (case-insensitive, whitespace collapsed);
- the page is on the site and `_domain(page.url) == _domain(approved.url)`;
- the control's form state equals `approved.state`: the same `selected` list, the same `fields` values (the released values re-typed into a fresh session count as the same), and the same `text`. The comparison is exact after whitespace collapsing; a timestamp or a counter in the form text makes the page a different transaction, which is the correct answer when in doubt.

Anything short of that, the action does not run and the run ends `needs_submit` again with the current record and a `changed` list naming what differs ("selected: Thu, Oct 22 8AM–12PM (approved: Tue, Oct 20 8AM–12PM)", "text: $124.95 appears; $114.95 does not"). Before the permitted action runs, the runner calls `on_attempt(record)` and waits for it to return: the attempt is on the mission's transcript before the press lands. Then the action runs, the page settles, the screenshot and the scan follow as for any navigation, and the model reads the result.

**Three outcomes after the action.** The model is told: "After an approved press, read the page and end your report with exactly one of: `CONFIRMED: <what the page says, with any confirmation number>`, `REJECTED: <the error the page shows>`, or `UNKNOWN: <what you see>`." The runner maps them to the outcomes `submitted`, `submit_rejected`, `submit_unknown`; a report with none of the three, a page that never settled, a timeout, a cap or an error after the action is `submit_unknown`. A page whose controls carry payment words or whose fields are card fields after the action is `blocked: payment` on top of the attempt already recorded; the attempt is never lost. A second gated control after a confirmed action is a new `needs_submit`; one approval is one action.

**Outcomes and the ledger.** `OUTCOMES` gains `needs_submit`, `submitted`, `submit_rejected`, `submit_unknown`. Ledger lines: `needs_submit: Book appointment`, `press 'Book appointment' (approved)`, `blocked: payment (Pay now)`.

## Section 2 — The mission asks, the person taps

**`finish_browse`** maps `needs_submit` to an `ask` step named `submit`, the mission goes `waiting_user`, and the person is told:

```
result_json = {
  question: "Book at bodewell.com: Tue, Oct 20 8AM–12PM, trip charge $114.95 (button 'Book appointment')?",
  verb: 'book' | 'submit',
  site, url, button, state, facts,          # the submit record, verbatim
  filled: {first_name: 'Jeff', ...},        # what the form holds, from the report
  browse: {goal, site, start_url: url, released},
  changed: [...]                            # on a re-ask only: what moved
}
```

The question is deterministic: "{Book|Submit} at {domain}: {facts in the model's order, joined by ', '} (button '{button}')?"; with no facts, "{Book|Submit} at {domain} with the button '{button}'?". The verb is Book when the button, the intent or the goal says book, schedule, appointment or reserve; Submit otherwise. Under the question the card lists the form's `selected` labels and the filled values, so the person sees the transaction the way the site has it. The DM says the same and ends "Tap Book it on the Missions page or the thread card."

**The ask's id is the approval.** Every option carries the ask step's id: `submit:<ask_id>:approve`, `submit:<ask_id>:decline`, `submit:<ask_id>:stop` on the mission card, and `submit:mission:<mid>:<ask_id>:approve` (and the other two) when a thread carries them. `POST /api/missions/{id}/submit` takes `{decision, ask_id}`; `missions.submit(mission_id, decision, actor, ask_id)` refuses a request whose `ask_id` is not the mission's pending submit ask: "That question has moved on; look at the card again." A re-ask is a new ask step with a new id, so a stale card, a delayed request or a second tap on the old card can never answer the new question. The same id discipline is applied to the release in this slice: `release:<ask_id>:…`, `{decision, ask_id}` on `/release`, `missions.release(..., ask_id)`; the thread's routed ids gain the ask id the same way. A client that sends no `ask_id` is refused, not defaulted: the old card is the risk.

**Options and verbs.** `situations.VERBS` gains `submit`. A mission whose last ask is a `submit` leads with approve ("Book it" / "Submit it"), then decline ("I'll finish it myself"), then stop ("Stop the mission"); the thread routes them as it routes a release. `needs_attention` counts a submit; triage ranks it tier 0; `VERB_LABELS.submit` is "Book it". `act_on_situation` refuses the `submit` verb outright, as it refuses `release`.

**`missions.submit(mission_id, decision, actor, ask_id)`**, parent/adult:

- `approve`: under `db_lock`, the mission must be `waiting_user` and the pending submit ask must be `ask_id`, else `already` (a second tap) or `moved` (a stale card). Notes `submit_approved` with the record; re-runs the browse with `start_browse(..., start_url=record.url, released=ask.browse.released, approved=record)`.
- `decline`: a `handoff` ask ("I got as far as {url}. I did not press '{button}'. Finish it yourself and tell me what you found.") plus DM; the mission waits.
- `stop`: `blocked`, "the family did not book".

`POST /api/missions/{id}/submit` `{decision, ask_id}`, gated like `/release`. The transcript's `submit` ask block shows the question, the selected labels, the filled values and the three buttons while it is the pending ask; the free-text answer box is hidden for it.

**After the action.** `finish_browse` maps:

- `submitted` → a `note` step named `submitted` (`result_json`: the record, the model's CONFIRMED text, the facts with any confirmation number) and `running`. `_land_finish` writes "Booked: {facts}, confirmation {n}" (or "Submitted: …" for a submit verb) instead of "Nothing is booked", in the thread note and the DM, and the thread's next step is the appointment itself with its date as `next_action_at`.
- `submit_rejected` → a `note` named `submit_rejected` with the page's error and `running`: the planner reads it and may ask the person or re-browse; a new `needs_submit` is a new ask.
- `submit_unknown` → a `handoff` ask: "I pressed '{button}' at {url} and could not read whether it went through. Check your email or the site, then tell me what you find." plus DM; the mission waits. The planner is told, in its rules: "A `submit_attempt` on the transcript with no `submitted` note is a commitment that may have happened: never press again on this mission; ask the person."

**The attempt is on the record before the press.** `on_attempt` adds a `note` step named `submit_attempt` with the record and the time; `finish_browse` leaves it in place whatever follows. The tick's lost-browse reclaim (`BROWSE_LOST_S`) checks for a `submit_attempt` newer than the browse step: with one, the mission does not return to `running`; it gets the `submit_unknown` hand-off above. A payment wall or a second gated control after the action never removes the attempt.

**A re-ask.** A `needs_submit` with `changed` becomes a new ask whose question leads with the change: "The page changed: selected Thu, Oct 22 8AM–12PM (you approved Tue, Oct 20 8AM–12PM). Book at bodewell.com: …?" The earlier approval is spent and its id no longer answers anything.

## Section 3 — The switch

`missions_submit_enabled` (Settings, registry, Missions drawer → Browser section): "Argyle may book and submit forms with your approval", default on. Off, the runner's guard behaves as before this slice (`blocked: would submit`) and the planner is told booking is off. The hand path stays either way: the hand-off link.

## Section 4 — Tests

- `test_browse_runner.py` (real Playwright; the local site gains a booking form with a slot radio group, a price line, a "Book appointment" button, a "Pay now" button, a "Send application" form, and a saved-card "Buy now" page): the gate returns `needs_submit` with the button, url and state for a click, an Enter, a Space on a focused button, an intent, and a `SUBMIT:` line; `PAY_WORDS` and the saved-card "Buy now" are `blocked: payment` even with `approved` set; an unfamiliar final label ("Send application") is `needs_submit`; "Next" still passes; the approved action runs only when button, domain and state match; a visible-but-unselected slot (Tuesday in the text, Thursday checked) re-asks with `changed`; a changed price re-asks; `on_attempt` is called before the press (the fake records the order); `CONFIRMED:` → `submitted`, `REJECTED:` → `submit_rejected`, no line → `submit_unknown`; a payment page after the press is `blocked: payment` with the attempt intact; a second gated control after a confirmed press is a new `needs_submit`; the switch off restores `blocked: would submit`; the ledger lines.
- `test_browse_mission.py`: the `submit` ask shape, question and DM; the id-bearing options on the mission and the thread; approve with the right id resumes with the record, the released values and the page; a second tap answers `already`; a stale id answers `moved` and changes nothing; decline hands off; stop blocks; the chat tool refuses the verb; `submitted` → the note, "Booked: …" on the thread and in the DM, the finish's next step as the appointment; `submit_rejected` → `running` with the note; `submit_unknown` → the hand-off; a crash after the attempt (a `submit_attempt` with no outcome, the browse older than `BROWSE_LOST_S`) → the hand-off, never `running`; the release endpoint refuses a stale `ask_id` too.
- `test_browse_page_live.py` / `test_browse_thread_live.py`: the submit ask on /missions and on the thread card with Book it, I'll finish it myself, Stop; Book it from the thread card resumes the mission with the ask id.
- `test_start_mission.py`: the end-to-end dishwasher scenario extended: after the slots are read the browse ends `needs_submit`, the parent taps Book it, the attempt lands, the resumed browse returns `submitted` with a confirmation, the mission finishes "Booked: Tue, Oct 20 8AM–12PM, confirmation 12345", nothing proposed, nothing paid.
- Pins unchanged: `browse.py` never names the paid key; `missions.py` never names the mailer.

## Out of scope

- Payment of any kind: a card field, and any control that reads pay, checkout, purchase, buy or place order, is a wall that no approval in this slice lifts. Its own slice, with layered approval.
- Voice or typed approval of a submit: the voice-identity slice (PIN) and the voice-fingerprint slice.
- Booking on the person's behalf without an ask: never.
- Stealth, proxies, or anything that changes what the browser says about itself.

## Appendix — The sequence after this slice

1. **Voice identity.** Three levels on a satellite: unknown (a room, as today), named ("it's Jeff": that person's lens for harmless things, no approvals), verified (name plus the member's PIN spoken aloud: that person for ten minutes on that satellite; approvals of a release and a submit count, read back before acting; three wrong PINs lock voice approval until a tap on the phone; sensitive content stays withheld out loud).
2. **Voice fingerprint.** A custom STT provider in the HA component that passes the audio on unchanged and computes a speaker embedding on CPU, writing "satellite, moment, fingerprint" to a state the agent reads; first use: the voice that spoke the PIN keeps the session and a different voice drops it; second use: enrolled members get their lens and their name back ("Morning, Jeff. Two things."). A strong hint that stacks with the room and the PIN, never the key to money by itself.
3. **Payment.** Its own spec: what the layers are (two parents, a per-mission amount cap, a PIN on the phone), what the browser may type, what it never types.
