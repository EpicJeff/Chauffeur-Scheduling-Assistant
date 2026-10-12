# Submit gate — a browse may book or submit a form, on a parent's tap

**Date:** 2026-10-11. **Status:** approved in conversation; awaiting the user's review of this file.
**Builds on:** `2026-10-10-browse-missions-design.md` (all three builds shipped, device-verified 2026-10-11).

## Problem

The browse arc reached the Dots result on the device: the household contact card released on a tap, the guest form filled, the reCAPTCHA passed on the headed browser, the trip charge and the real appointment slots read off the screen. It stopped one click short of the job because the spec locked "nothing is ever booked, paid, submitted or sent by the browser" and the runner enforces it in code: a click on Book, Confirm, Submit, Schedule now, Pay or Checkout ends the run `blocked: would submit`.

The user revised that decision on 2026-10-11. Dots booked nothing only because the user told it not to in conversation, not by rule. The power of this kind of agent is that it can do so many things. Booking an appointment with the person's approval is harmless; buying something or making a payment is a further step that needs layered approval; both must be possible. A person makes the commitment; the browser carries it out.

## Decisions made in this conversation

- **Scope of this slice:** a general "submit with approval" gate. Booking an appointment is one case; a permit application, a school form, a warranty registration are the same shape. Payment is not in this slice: a card-number field still ends the run and hands the person the page. Payment gets its own slice with its own layers.
- **Who says yes, and how:** one parent, by tap, on the Missions page, the thread card or the DM card. The approval names the exact button text, the page and the facts on screen (the slot, the price), and the browser may click only while the page still shows those facts. Spoken or typed "book it" never counts in this slice, for the same reason a release is tap-only: the chat model once approved a release from "enter my information". Voice approval arrives with the voice-identity slice (a spoken PIN, three levels of identity), and the voice-fingerprint slice after it.
- **The order of the next slices:** this gate first, since it finishes the dishwasher thread already open; then voice identity (PIN); then the STT wrapper that tags the speaker's voice, keeps a PIN session honest and lets Argyle greet the person by name.

## Section 1 — The wall becomes a question

**In the runner (`services/browse.py`).** The never-submit guard stays exactly where it is and keeps its tests; what changes is what it returns. A click, an Enter, or a stated intent that would press a submit control (`STOP_WORDS` on the element under the click, on the form's default submit control for Enter, or on the model's intent) ends the run with a new outcome, `needs_submit`, instead of `blocked`. The report carries a `submit` record:

```
submit = {
  button: str,        # the control's text, as the page shows it ('Book appointment')
  url: str,           # the page the control is on
  facts: {str: str},  # what the model read from the screen: the LEARNED: pairs of this run
  intent: str,        # the model's own words for the click, if it gave any
}
```

The model gets an explicit exit as well, the way `NEED:` and `WALL:` work: when the only way forward is a submit, book, confirm or order control, it ends its report with `SUBMIT: <button text>` and the runner returns `needs_submit` with that text. Either path, the facts are the `LEARNED:` pairs found in any of the model's turn texts so far in this run (the model writes prose beside its calls; the runner keeps the latest value per key), so a guard-triggered stop mid-turn has the slot and price the model already read; a submit with no facts is still a submit (the ask then shows the button and the page only, and the guarded click checks the button alone).

The payment guard is untouched: a page with a card-number, CVC or expiry field ends the run `blocked: payment` before any typing, before and after a submit. The domain guard, the typing guard, the release detection and the CAPTCHA policy are unchanged.

**The approved click.** `run()` takes one more argument, `approved: dict | None`, the `submit` record a parent approved. With it set, the runner allows exactly one click or Enter that `STOP_WORDS` would otherwise stop, and only when:

- the element under the click (or the form's default submit control, for Enter) has text that matches `approved.button`, compared case-insensitively with whitespace collapsed;
- the page is on the site (the domain allowlist, as today);
- every value in `approved.facts` still appears in the page's visible text (whitespace collapsed, case-insensitive).

A click that fails any check does not run; the run ends `needs_submit` again with the current button, page and facts and a `changed` list naming which approved facts are no longer on the screen ("$114.95 is no longer shown; the page says $124.95"). After the approved click runs, the runner waits for the page to settle, takes its screenshot and scans it as for any navigation; the model is then expected to read the confirmation and finish; the runner returns `submitted` with the model's report and the `LEARNED:` pairs (a confirmation number when the page shows one). A second submit control reached after the approved click is a new `needs_submit`; one approval is one click.

**Outcomes.** `OUTCOMES` gains `needs_submit` and `submitted`. The ledger line for the stop reads `needs_submit: Book appointment`; the approved click's line reads `click (x,y) 'Book appointment' (approved)`.

## Section 2 — The mission asks, the person taps

**`finish_browse`** maps `needs_submit` to an `ask` step named `submit`, the mission goes `waiting_user`, and the person is told, the way a release works today:

```
result_json = {
  question: "Book at bodewell.com: Tue, Oct 20 8AM–12PM, trip charge $114.95 (button 'Book appointment')?",
  site: 'bodewell.com', url: <the page>, button: 'Book appointment',
  facts: {earliest_availability: 'Tue, Oct 20 ...', trip_charge: '$114.95'},
  filled: {first_name: 'Jeff', ...},        # what the form holds, from the report
  browse: {goal, site, start_url: <the page>, released: <the released values>},
  changed: [...]                             # only on a re-ask, what moved
}
```

The question is built deterministically: "{Verb} at {domain}: {facts in the model's order, joined by ', '} (button '{button}')?" where the verb is Book when the button or the goal says book, schedule or appointment, Submit otherwise. The filled values are listed under it on the card and in the DM so the person knows exactly what the site has. The DM: "Argyle needs a yes: {question} Filled: {values}. Tap Book it on the Missions page or the thread card."

**Options and verbs.** `situations.VERBS` gains `submit`. A mission (and, through the thread's routing, its thread) whose last ask is a `submit` leads with `submit:approve` (label "Book it" or "Submit it"), then `submit:decline` ("Not this"), `submit:stop` ("Stop the mission"). `needs_attention` counts a submit as a decision left; triage ranks it tier 0 on the thread as it does a release. `VERB_LABELS.submit` = "Book it". `act_on_situation` refuses the `submit` verb outright, as it refuses `release`: "Booking takes a tap, not a word: tap Book it on the Missions page, the thread card or the DM card."

**`missions.submit(mission_id, decision, actor)`**, parent/adult:

- `approve`: idempotent under `db_lock` (a second tap answers `already`); notes `submit_approved` with the button and facts; re-runs the browse through `start_browse(..., start_url=ask.url, released=ask.browse.released, approved=ask.submit_record)`. The released values ride again so the form can be re-filled if the session is gone.
- `decline`: a `handoff` ask ("I got as far as {url}. I did not press '{button}'. Finish it on your phone and tell me what you found.") plus DM; the mission waits.
- `stop`: `blocked` with "the family did not book".
- A mission not waiting on a submit: `already`.

`POST /api/missions/{id}/submit` `{decision}`, gated like `/release`. The transcript's `submit` ask block shows the question, the facts, the filled values and the three buttons while it is the last ask; the free-text answer box is hidden for it, as for a release.

**After the click.** `finish_browse` maps `submitted` to `running` with a `note` step named `submitted` whose text is the model's report and whose `result_json` holds the facts (the confirmation number when read). The planner's view of the step says `submitted`. The planner's rules gain: "A submitted step is the commitment made: finish with what was booked and the confirmation; never book twice." `_land_finish` writes "Booked: {facts}" instead of "Nothing is booked" when a `submitted` note exists on the mission, both in the thread note and the DM. The thread's next step after such a finish is the person's: "Tue Oct 20 8–12, Bodewell, confirmation 12345" with the date as `next_action_at`.

**A re-ask.** When the resumed browse ends `needs_submit` again with `changed`, the new ask's question leads with the change: "The page changed: $114.95 is no longer shown; it says $124.95. Book at bodewell.com: … ?" and the previous approval is spent.

## Section 3 — The switch

`missions_submit_enabled` (Settings, registry, Missions drawer → Browser section): "Argyle may book and submit forms with your approval", default on. Off, the runner's guard behaves as before this slice (`blocked: would submit`) and the planner is told booking is off. The hand path stays either way: the hand-off link.

## Section 4 — Tests

- `test_browse_runner.py`: the guard returns `needs_submit` with the button, url and facts (a click, an Enter, an intent); `SUBMIT:` in the report does the same; an approved click runs only when the button matches and the facts are on the page; a changed price re-asks with `changed`; a second submit after an approved click is a new `needs_submit`; a payment page after a submit is still `blocked: payment`; the switch off restores `blocked: would submit`; the ledger lines.
- `test_browse_mission.py`: the `submit` ask shape, question and DM; the card's three options on the mission and on the thread; approve resumes with the record, the released values and the stopped-at page; a double tap resumes once; decline hands off; stop blocks; the chat tool refuses the verb; `submitted` → a `submitted` note, "Booked: …" on the thread and in the DM, the finish's next step as the person's.
- `test_browse_page_live.py` / `test_browse_thread_live.py`: the submit ask on /missions and the thread card with Book it, Not this, Stop; Book it from the thread card resumes the mission.
- `test_start_mission.py`: the end-to-end dishwasher scenario extended: after the slots are read the browse ends `needs_submit`, the parent taps Book it, the resumed browse returns `submitted` with a confirmation, the mission finishes "Booked: Tue Oct 20 8–12 … confirmation 12345", nothing proposed.
- Pins unchanged: `browse.py` never names the paid key; `missions.py` never names the mailer.

## Out of scope

- Payment of any kind: a card field is a wall. Its own slice, with layered approval.
- Voice or typed approval of a submit: the voice-identity slice (PIN) and the voice-fingerprint slice.
- Booking on the person's behalf without an ask: never.
- Stealth, proxies, or anything that changes what the browser says about itself.

## Appendix — The sequence after this slice

1. **Voice identity.** Three levels on a satellite: unknown (a room, as today), named ("it's Jeff": that person's lens for harmless things, no approvals), verified (name plus the member's PIN spoken aloud: that person for ten minutes on that satellite; approvals of a release and a submit count, read back before acting; three wrong PINs lock voice approval until a tap on the phone; sensitive content stays withheld out loud).
2. **Voice fingerprint.** A custom STT provider in the HA component that passes the audio on unchanged and computes a speaker embedding on CPU, writing "satellite, moment, fingerprint" to a state the agent reads; first use: the voice that spoke the PIN keeps the session and a different voice drops it; second use: enrolled members get their lens and their name back ("Morning, Jeff. Two things."). A strong hint that stacks with the room and the PIN, never the key to money by itself.
3. **Payment.** Its own spec: what the layers are (two parents, a per-mission amount cap, a PIN on the phone), what the browser may type, what it never types.
