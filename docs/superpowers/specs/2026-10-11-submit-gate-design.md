# Submit gate — a browse may book or submit a form, on a parent's tap

**Date:** 2026-10-11. **Status:** approved in conversation; revised twice the same day after the user's reviews. First round (five findings, all taken): the ask id, the form's state as the thing approved, attempt and outcome, the payment path, every activation method. Second round (five findings, all taken, one reshaped): the snapshot is complete and never empty, labels alone never make a control navigation (evidence of a final action does the classifying; the device-verified run is the fixture that must still pass), an attempt's outcome is written per attempt and the approved browse ends at it, `on_attempt` authorizes under the lock as well as writes, an approved press is exactly one activation. Awaiting the user's third review.
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

If the control's text or the intent matches `PAY_WORDS`: `blocked: payment`. If it matches `SUBMIT_WORDS`: the gate below. Otherwise the label decides nothing by itself; the control's place on the page does.

**The control's scope.** Every control has a scope: its form, or, outside a form, its closest ancestor that is a `dialog`, `main`, `section`, `article`, `form`-like region (`role=form|group|dialog`) or, failing those, `body`. The scope is what the snapshot below reads, and what the classification looks at.

**Evidence of a final action.** A control with no word from either list is a commitment when any one of these holds:

- it is its form's submit control (`type=submit`, the form's default submit control, or the only button in the form);
- it is the only button in its scope, or the last enabled button in document order, and the scope holds state (a filled field or a selected option);
- its scope's visible text carries commitment language near it (`COMMIT_CONTEXT`: "by clicking", "i agree", "terms", "authorize", "you will be charged", "total", "confirm your", "review your");
- the model's intent says so (any `SUBMIT_WORDS` in the intent, already covered above).

A control with that evidence goes through the gate, whatever its label: "Send application", "Request a quote", "Finish", "Lock it in", and also "Accept" on an agreement form, "Continue" as the last button of a form with a selected slot, "OK" under a "Review your request" heading. A control with none of that evidence runs: a "Dishwasher" appliance tile among eight sibling buttons inside a form with filled fields is not the only or last button and carries no commitment text, so the device-verified run still clicks it (that run is the fixture this rule must keep passing). `NAVIGATION_WORDS` (next, previous, back, close, cancel, search, find, go, filter, sort, show, view, see, select, choose) remain only as a reading aid in the ledger; they never let a control past the evidence. Accept, ok, continue, got it, agree, done, finish and proceed are not on any list: they are classified by evidence like any unfamiliar label. A cookie banner's "Accept" (a `type=button` outside any form, no state in its scope) runs; the same word on a form's submit control asks.

**The backstop after an ungated press.** The runner cannot see every commitment (a bare JS button with an unfamiliar label and no state around it). After any click, Enter or Space that was not gated, the settled page is checked against `CONFIRMATION_MARKERS` ("confirmation number", "confirmation #", "has been booked", "has been scheduled", "has been submitted", "we have received your", "thank you for your request|booking|application|order", "your appointment is"); a match ends the run `submit_unknown` with `unasked: true` and the control's text, url and the scope's state as the attempt record. Section 2 writes that attempt to the mission after the fact and hands off; the planner never presses again on that mission. This is a record of what the runner missed, not a permission: the classification above is what keeps it rare, and every such hit on the device is a fixture to add.

**One press is one activation.** A commitment the gate lets through (Section 1, "The approved action") runs as exactly one activation: a click request of any kind, including `double_click`, becomes a single `mouse.click(click_count=1)`; an Enter or Space becomes one `keyboard.press`; a `type_text_at` with `press_enter` types, then presses Enter once. The runner never re-presses: after the approved activation the loop refuses every further click, type or key for the rest of the run (Section 1, "After the action").

**The gate returns a question, not a wall.** An action that reaches the gate does not run. The run ends with the new outcome `needs_submit` and the report carries a `submit` record, the thing the person is asked to approve:

```
submit = {
  button: str,        # the control's text as the page shows it ('Book appointment')
  url: str,           # the page the control is on
  state: {            # the control's scope (its form, or the region around it), read from the DOM at the stop
    fields: {name: value},     # every text-like input's current value (passwords and card fields excluded)
    selected: [str],           # the labels of checked radios and checkboxes, selected options, and any element
                               # with aria-checked, aria-selected or aria-pressed = true, in page order
    text: str,                 # the scope's visible text, whitespace collapsed, WHOLE (no truncation)
    text_sha: str,             # sha256 of `text`; the comparison key, and what the mission stores verbatim
    prices: [str],             # every money amount in `text` ($114.95, 114.95 USD), in page order
  },
  display: str,       # the first 300 characters of `text`, for the card; never compared
  facts: {str: str},  # the model's LEARNED: pairs so far, latest value per key: the human summary (slot, price)
  intent: str,        # the model's words for the action, if any
}
```

`state` is the transaction, and it is complete: the whole scope text, every selection whether the site stores it in a native input or in an `aria-*` attribute on a custom slot picker, and every price on the page as its own list so a price that moved is named in plain words ("$124.95 appears; $114.95 does not") even when the text comparison already caught it. Display truncation lives only in `display`. A scheduling page that shows Tuesday in a paragraph while Thursday is selected has Thursday in `selected`; a price moved anywhere in the scope is a different `text_sha`. The model's `facts` are shown to the person but never used as the check.

**A snapshot is never empty.** The runner refuses to ask a question it cannot answer later. A `submit` record is produced only when the control resolved to a DOM element and its scope read non-empty (`text` has at least one word). The model also gets an explicit exit, as with `NEED:` and `WALL:`: when the only way forward is such a control, it ends its report with `SUBMIT: <button text>`; the runner finds the control by that text (exact after whitespace collapsing, then the one button whose text contains it when exactly one does), reads its scope and returns `needs_submit`. No such control: the runner answers the model once, "no control reads 'X'; click it, or name its text exactly as the page shows it", and a second miss ends the run `blocked: could not find the control 'X'` (the planner reads it; no ask is raised). An unreadable scope at the moment of an approved press (the control gone, the scope empty) is `blocked: form state unreadable`, never a press and never a re-ask on empty.

**The approved action, guarded.** `run()` takes `approved: dict | None`, the `submit` record a parent approved together with its `ask_id`, plus `on_attempt`, a callable the mission engine supplies (Section 2). With `approved` set the runner permits exactly one action that the gate would stop, and only when, at the moment of the action:

- the control's text equals `approved.button` (case-insensitive, whitespace collapsed);
- the page is on the site and `_domain(page.url) == _domain(approved.url)`;
- the control's scope state equals `approved.state`: the same `selected` list, the same `fields` values (the released values re-typed into a fresh session count as the same), and the same `text_sha`. The comparison is exact after whitespace collapsing; a timestamp or a counter in the scope text makes the page a different transaction, which is the correct answer when in doubt;
- `on_attempt(record)` returns true (below).

Anything short of a state match, the action does not run and the run ends `needs_submit` again with the current record and a `changed` list naming what differs ("selected: Thu, Oct 22 8AM–12PM (approved: Tue, Oct 20 8AM–12PM)", "prices: $124.95 appears; $114.95 does not", "text: changed"). 

**`on_attempt` is the authorization, not only the record.** With button, domain and state matched, the runner calls `on_attempt(record)` and waits. The mission engine answers under `db_lock` (Section 2): it verifies that this exact browse step is still the mission's live browse, that the mission is still `browsing`, that the approval on the step is this `ask_id` and is unspent, and that no unresolved attempt exists on the mission; it then writes the `submit_attempt` step and marks the approval spent, in the same lock, and returns true. Any check failing returns false, and the runner ends the run `blocked: approval withdrawn` without pressing. A worker that slept through a reclaim, a cancel, a drop or a second approve wakes up to a false and never clicks. Only after true does the activation run (one activation, above), the page settles, the screenshot and the scan follow as for any navigation, and the model reads the result.

**The approved browse ends at the outcome.** The model is told: "After an approved press, read the page and end your report with exactly one of: `CONFIRMED: <what the page says, with any confirmation number>`, `REJECTED: <the error the page shows>`, or `UNKNOWN: <what you see>`. Do not act again." After the activation the runner permits only `scroll`, `wait` and `go_back` (to read, never to press); any click, type or key call is refused with "the press is done; report what the page says", and a second such call ends the run `submit_unknown`. The runner maps the three lines to the outcomes `submitted`, `submit_rejected`, `submit_unknown`; a report with none of the three, a page that never settled, a timeout, a cap or an error after the activation is `submit_unknown`. Whatever the outcome, the report carries `attempt = {ask_id, button, url, state, pressed_at, outcome: 'confirmed'|'rejected'|'unknown', text}`: the attempt's outcome travels with the attempt, never only as the run's outcome. A page whose controls carry payment words or whose fields are card fields after the activation is `blocked: payment` with `attempt.outcome = 'unknown'` in the report; the attempt is never lost. There is no second gated control in an approved run: one approval is one activation is one run, and whatever the site wants next is a new browse, a new `needs_submit`, a new ask.

**Outcomes and the ledger.** `OUTCOMES` gains `needs_submit`, `submitted`, `submit_rejected`, `submit_unknown`. Ledger lines: `needs_submit: Book appointment`, `press 'Book appointment' (approved, ask a1b2)`, `blocked: payment (Pay now)`, `blocked: approval withdrawn`, `submit_unknown: confirmation page after an ungated press of 'Lock it in'`.

## Section 2 — The mission asks, the person taps

**`finish_browse`** maps `needs_submit` to an `ask` step named `submit`, the mission goes `waiting_user`, and the person is told:

```
result_json = {
  question: "Book at bodewell.com: Tue, Oct 20 8AM–12PM, trip charge $114.95 (button 'Book appointment')?",
  verb: 'book' | 'submit',
  site, url, button, state, display, facts, # the submit record, verbatim (state whole: it is what the press re-checks)
  filled: {first_name: 'Jeff', ...},        # what the form holds, from the report
  browse: {goal, site, start_url: url, released},
  changed: [...]                            # on a re-ask only: what moved
}
```

The question is deterministic: "{Book|Submit} at {domain}: {facts in the model's order, joined by ', '} (button '{button}')?"; with no facts, "{Book|Submit} at {domain} with the button '{button}'?". The verb is Book when the button, the intent or the goal says book, schedule, appointment or reserve; Submit otherwise. Under the question the card lists the form's `selected` labels and the filled values, so the person sees the transaction the way the site has it. The DM says the same and ends "Tap Book it on the Missions page or the thread card."

**The ask's id is the approval.** Every option carries the ask step's id: `submit:<ask_id>:approve`, `submit:<ask_id>:decline`, `submit:<ask_id>:stop` on the mission card, and `submit:mission:<mid>:<ask_id>:approve` (and the other two) when a thread carries them. `POST /api/missions/{id}/submit` takes `{decision, ask_id}`; `missions.submit(mission_id, decision, actor, ask_id)` refuses a request whose `ask_id` is not the mission's pending submit ask: "That question has moved on; look at the card again." A re-ask is a new ask step with a new id, so a stale card, a delayed request or a second tap on the old card can never answer the new question. The same id discipline is applied to the release in this slice: `release:<ask_id>:…`, `{decision, ask_id}` on `/release`, `missions.release(..., ask_id)`; the thread's routed ids gain the ask id the same way. A client that sends no `ask_id` is refused, not defaulted: the old card is the risk.

**Options and verbs.** `situations.VERBS` gains `submit`. A mission whose last ask is a `submit` leads with approve ("Book it" / "Submit it"), then decline ("I'll finish it myself"), then stop ("Stop the mission"); the thread routes them as it routes a release. `needs_attention` counts a submit; triage ranks it tier 0; `VERB_LABELS.submit` is "Book it". `act_on_situation` refuses the `submit` verb outright, as it refuses `release`.

**`missions.submit(mission_id, decision, actor, ask_id)`**, parent/adult:

- `approve`: under `db_lock`, the mission must be `waiting_user` and the pending submit ask must be `ask_id`, else `already` (a second tap) or `moved` (a stale card). Notes `submit_approved` with the record; re-runs the browse with `start_browse(..., start_url=record.url, released=ask.browse.released, approved={**record, 'ask_id': ask_id})`. The browse step's `args_json` carries `approved_ask_id` and `approval_spent: false`: the thing `on_attempt` checks.
- `decline`: a `handoff` ask ("I got as far as {url}. I did not press '{button}'. Finish it yourself and tell me what you found.") plus DM; the mission waits.
- `stop`: `blocked`. The text consults the mission's attempts (below): with none, "the family did not book"; with a confirmed attempt, "stopped; the booking already made stands ({facts}, confirmation {n})"; with an unresolved attempt, "stopped; a press of '{button}' at {url} may have gone through: check your email or the site". A stop never says "did not book" over an attempt on the record.

`POST /api/missions/{id}/submit` `{decision, ask_id}`, gated like `/release`. The transcript's `submit` ask block shows the question, the selected labels, the filled values and the three buttons while it is the pending ask; the free-text answer box is hidden for it.

**The attempt is on the record before the press, and its outcome is written first after it.** `on_attempt(record)` runs under `db_lock` in the mission engine:

1. the mission is `browsing`, and its newest `browse` step is the step this worker was started for (`step_id` is bound into the callable);
2. that step's `approved_ask_id` equals `record.ask_id` and `approval_spent` is false;
3. no `submit_attempt` on the mission has `outcome` null or `'unknown'` (an unresolved attempt: the one-press rule);
4. then, in the same lock: a `note` step named `submit_attempt` with `{ask_id, browse_step_id, button, url, state, pressed_at, outcome: null}` and `approval_spent: true` on the browse step; return true.

Any check failing returns false and writes nothing (the runner ends `blocked: approval withdrawn`). A mission reclaimed by the tick, cancelled, dropped or re-approved has, by then, either a different status, a different newest browse step or a spent approval, so a worker that slept through it cannot press.

`finish_browse`, whatever the browse outcome, first resolves the attempt: when the report carries `attempt`, the matching `submit_attempt` note (by `ask_id` and `browse_step_id`) gets `outcome` and `text` written before anything else is mapped. An `attempt` with `unasked: true` (the confirmation-page backstop) adds a `submit_attempt` note after the fact with `outcome: 'unknown'`. A report that mentions no attempt leaves a pending attempt as it is; the tick's reclaim (below) resolves it. Then:

- `submitted` → a `note` step named `submitted` (`result_json`: the record, the model's CONFIRMED text, the facts with any confirmation number) and `running`. `_land_finish` writes "Booked: {facts}, confirmation {n}" (or "Submitted: …" for a submit verb) instead of "Nothing is booked", in the thread note and the DM, and the thread's next step is the appointment itself with its date as `next_action_at`. The finish reads the mission's `submit_attempt` notes, not the browse outcome, so a confirmed booking is reported even when a later browse on the same mission ended some other way.
- `submit_rejected` → a `note` named `submit_rejected` with the page's error and `running`: the planner reads it and may ask the person or re-browse; a new `needs_submit` is a new ask. A rejected attempt is resolved: it does not bar a later press on this mission.
- `submit_unknown` → a `handoff` ask: "I pressed '{button}' at {url} and could not read whether it went through. Check your email or the site, then tell me what you find." plus DM; the mission waits. The planner is told, in its rules: "A `submit_attempt` on the transcript whose outcome is not confirmed or rejected is a commitment that may have happened: never press again on this mission; ask the person." `on_attempt` check 3 is the same rule in code.

**The reclaim.** The tick's lost-browse reclaim (`BROWSE_LOST_S`) looks for a `submit_attempt` newer than the lost browse step with `outcome` null: with one, it writes `outcome: 'unknown'` on it and the mission gets the `submit_unknown` hand-off above, never `running`. With none, as today. The worker, if still alive, will later find the mission not `browsing` (its report parks on the step, as today) and, had it not pressed yet, `on_attempt` refuses it.

**A re-ask.** A `needs_submit` with `changed` becomes a new ask whose question leads with the change: "The page changed: selected Thu, Oct 22 8AM–12PM (you approved Tue, Oct 20 8AM–12PM). Book at bodewell.com: …?" The earlier approval is spent and its id no longer answers anything.

## Section 3 — The switch

`missions_submit_enabled` (Settings, registry, Missions drawer → Browser section): "Argyle may book and submit forms with your approval", default on. Off, the runner's guard behaves as before this slice (`blocked: would submit`) and the planner is told booking is off. The hand path stays either way: the hand-off link.

## Section 4 — Tests

- `test_browse_runner.py` (real Playwright; the local site gains a booking form with a slot radio group, a price line, a "Book appointment" button, a "Pay now" button, a "Send application" form, a saved-card "Buy now" page, an agreement form whose submit control reads "Accept", a cookie banner whose "Accept" is a `type=button` outside any form, a `role=button` "Lock it in" outside any form beside a custom `aria-checked` slot picker, an appliance-tile form (eight sibling buttons, filled fields, "Dishwasher" among them, as the device run saw), a long form whose price line sits past 1,500 characters of text, and a booking endpoint that counts the POSTs it receives): the gate returns `needs_submit` with the button, url and state for a click, an Enter, a Space on a focused button, an intent, and a `SUBMIT:` line; `PAY_WORDS` and the saved-card "Buy now" are `blocked: payment` even with `approved` set; the unfamiliar-label fallback with no `SUBMIT_WORDS` hit ("Request a quote" as a form's submit control, "Lock it in" as the only button in a scope with an `aria-checked` slot) is `needs_submit`; "Accept" on the agreement form asks, "Accept" on the cookie banner runs, "Continue" as the last button of a form with a selected slot asks, "Next" with no state behind it runs, the "Dishwasher" tile runs; the snapshot's `selected` holds the `aria-checked` slot label; the price past 1,500 characters is in `prices` and a change to it re-asks; `SUBMIT:` naming a control that is not there answers the model once, then `blocked: could not find the control`; an empty scope never yields a `submit` record; the approved action runs only when button, domain and state match; a visible-but-unselected slot (Tuesday in the text, Thursday checked) re-asks with `changed`; a changed price re-asks naming the prices; `on_attempt` is called before the press (the fake records the order) and a false from it means no POST reaches the endpoint and `blocked: approval withdrawn`; an approved `double_click` and an approved `type_text_at` with `press_enter` each land exactly one POST on the counting endpoint; a click after the approved press is refused, a second one ends `submit_unknown`; `CONFIRMED:` → `submitted`, `REJECTED:` → `submit_rejected`, no line → `submit_unknown`, each with `report.attempt.outcome` set to match; a payment page after the press is `blocked: payment` with `attempt` in the report; an ungated press that lands on a confirmation page is `submit_unknown` with `attempt.unasked`; the switch off restores `blocked: would submit`; the ledger lines.
- `test_browse_mission.py`: the `submit` ask shape, question and DM; the id-bearing options on the mission and the thread; approve with the right id resumes with the record, the released values, the page and `approved_ask_id` on the browse step; a second tap answers `already`; a stale id answers `moved` and changes nothing; decline hands off; stop blocks with "did not book" only when no attempt exists, names the confirmation over a confirmed attempt, and warns over an unresolved one; the chat tool refuses the verb; `on_attempt` under the lock: true once and the `submit_attempt` note written with `outcome: null`, false on a second call (spent), false after the tick reclaimed the mission, false after a cancel, false with an unresolved attempt already on the mission, false when a newer browse step exists; a late worker (the browse run inline, `on_attempt` called after the test reclaims the mission) presses nothing; `submitted` → the attempt's outcome `confirmed` written before the `submitted` note, "Booked: …" on the thread and in the DM, the finish's next step as the appointment; `submit_rejected` → `running` with the note and the attempt resolved `rejected`, and a later press on the mission allowed; `submit_unknown` → the hand-off and the attempt `unknown`; a crash after the attempt (a `submit_attempt` with `outcome: null`, the browse older than `BROWSE_LOST_S`) → the attempt marked `unknown`, the hand-off, never `running`; an `unasked` attempt → the note after the fact and the hand-off; the release endpoint refuses a stale `ask_id` too.
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
