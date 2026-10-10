# Browse missions — the agent that gets the dishwasher fixed

Date: 2026-10-10
Status: Approved in conversation; implementation plan pending
Follows the agentic-layer plan (sub-projects 1–3, shipped v2.499.297–.340). Spike findings: Appendix A.

## Problem

The user showed a transcript from OpenAI's Dots agent: "our dishwasher is not heating to dry, the TCO keeps tripping" became, in one conversation, a found purchase email with the model number, a label read off a photo, the official repair site, a booking form driven in a cloud browser (contact details shared with permission, CAPTCHA handled), and a report of appointment windows and the trip charge with nothing booked. That is what threads and missions are meant to be. Dots costs $100 a month. The pieces to do it ourselves mostly exist: missions (a propose-only pro-model loop, built dark), threads with household-address mail, the asks ledger and approval cards, the intake mailbox over IMAP, a vision tier, web research. What is missing is the browser, a way to search our own mail, a photo on a thread, and the conversation that ties them together.

The spike (Appendix A) proved Gemini's Computer Use model driving headless Chromium through Playwright reaches the same form Dots reached, for about seven cents, following a plain brief and stopping where told. It also found the wall: the vendor's form wants name, address, phone and email plus a reCAPTCHA before it shows a single slot or price.

## Decisions made in this conversation

1. **DIY, not a subscription.** The browser runs inside the Chauffeur add-on (the HA VM has 8 GB), on the paid Gemini key, pennies per task.
2. **Hand-off at the wall, remote hand later.** When the agent cannot pass a human check, it hands the person the link and everything it filled; a tap-on-screenshot relay is a later arc.
3. **The agent may attempt CAPTCHAs, capped, with recorded consent.** A Missions setting, off by default, lets it tick the checkbox and try up to two image challenges. A third challenge, a model refusal or an access-denied page ends the attempt.
4. **Personal details leave the house on one card per site per mission.** The family's own contact card is filled once; each site the agent would type it into gets one approval, good for that mission only.
5. **Nothing is ever booked, paid, submitted or sent by the browser.** A code guard, not a prompt line.
6. **Scope is three builds under one spec:** mail search and a photo on a thread; the browse step with its gates; the conversation and surfaces.

Carried over: missions execute reads and propose writes; drafts are never sent by the agent; every agent capability has a hand path; no new LLM calls on reads, ticks or sweeps beyond the mission's own steps; the paid key is read only through `model_pools.api_key_for_pool`.

## Approach

**`browse` is one mission action, run by a separate runner.** The mission model (pro, one step per 30 s beat) stays the planner: it emits `{"action":"browse","goal":"…","site":"bodewell.com"}` the way it emits `research` today. A runner (`services/browse.py`) executes that goal to completion in its own thread: the Computer Use loop on `gemini-3.8-flash` (pool `cu`, paid key only) over Playwright's headless Chromium, up to a turn cap, and returns one report that becomes one mission step. The planner reads the report and decides what next. Two loops, two concerns.

Rejected: every browser click as a mission step (forty clicks at thirty-second beats is twenty minutes for one form and burns the step cap); a separate browser add-on or sidecar (only needed below 4 GB).

The Interactions API (`client.interactions`) refuses every computer-use continuation on this account (Appendix A); the runner uses `generate_content` with `types.ComputerUse`, the path the official preview repository uses.

## Section 1 — The contact card and its release

**Household contact card.** New settings (Missions drawer, registry entries): `contact_first_name`, `contact_last_name`, `contact_email`, `contact_phone`, `contact_street`, `contact_apt`, `contact_city`, `contact_state`, `contact_zip`, `contact_preferred` (`text | email | phone`). The family's own facts about itself, filled once by a parent. Empty stays empty; the agent never invents a value, and a form that needs an empty field ends the browse with `needs_release` naming the missing field.

**Release card.** When the runner meets a form asking for any contact-card field, it stops with `outcome: needs_release` and the set of fields the form wants. The mission records a `release` step, goes `waiting_user`, and the person gets a card (on the mission card, the thread card, and as a DM): "Share with bodewell.com: Jeff Wilson · 919-327-7497 · ffejnosliw@gmail.com · 123 Chestnut Walk, Cary NC 27519?" with **Approve**, **Not these** (opens the contact card to fix), **Stop**. Approve writes `releases: [{site, fields, approved_by, at}]` on the mission and resumes the browse with those fields available; the same registrable domain in the same mission never asks again; another domain asks; the next mission asks again. Stop ends the mission `blocked` with "the family kept its details".

**Never a payment field.** A field whose label or autocomplete reads card number, CVC, expiry, or a pay/checkout step ends the browse with `outcome: blocked, reason: payment` and the report "this part needs a card; do it yourself here: {url}".

## Section 2 — The browse step

**Runner contract.** `browse.run(goal, site, released: dict, consent: dict, caps) -> report`:

```
report = {
  outcome: 'done' | 'needs_release' | 'captcha_failed' | 'blocked' | 'refused' | 'capped' | 'error',
  text: str,                 # the model's own plain report, or the runner's reason
  learned: {str: str},       # key facts the model extracted (windows, fee, required fields)
  stopped_at: str,           # URL
  wanted_fields: [str],      # on needs_release
  turns: int, tokens_in: int, tokens_out: int, seconds: float,
  screenshots: [path],       # every turn, 1440×900 PNG, under the mission's media folder
  filled: {field: value},    # what it typed from the contact card, for the hand-off
}
```

**Guards, in code.** Each one is a test:

- *Domain.* The browse carries an allowlist: the named site plus any domain reached by a server redirect from it (that is how geappliances.com hands off to bodewell.com). A `navigate` or a click that lands on another registrable domain is undone (`go_back`) once and, on repeat, ends the run `blocked: left the site`.
- *Never submit.* A click whose target label, the model's stated intent, or the element's form role reads submit, book, schedule now, confirm, place order, pay, checkout, or purchase ends the run `blocked: would submit`. The runner reads the element under the click through Playwright (`elementFromPoint`, its text, `type=submit`), not only the model's words.
- *Never a payment field.* As Section 1.
- *Personal data.* The runner's `type` action refuses any string that matches a contact-card value not in `released`, and any email or phone shape at all when not released.
- *Caps.* 40 turns, 5 minutes wall clock, one browser at a time per add-on, screenshots 1440×900.
- *Memory floor.* The step refuses to start under 600 MB free with "not enough room for a browser right now" and the mission retries on the next beat, three times, then `blocked`.

**CAPTCHA policy.** The model marks cookie banners and human-verification checks `require_confirmation`. Cookie consent is acknowledged always. A CAPTCHA is acknowledged only when `missions_captcha_attempts` (Missions drawer, default off) is on, and then at most one checkbox and two image challenges per browse; a third challenge, a model refusal, or a page reading access denied / unusual traffic ends the run `captcha_failed`. Every attempt is a line in the report.

**Hand-off.** On `captcha_failed`, on a release declined, and on `blocked: payment`, the mission records a `handoff` step and goes `waiting_user`. The DM reads: "I got as far as {url}. Filled so far: {filled}. {reason}. Finish it on your phone and tell me what you found." The thread card and mission card show the same with the link. The person's answer (typed, tapped, or spoken "tell the mission …") resumes the mission, which then finishes from the person's words.

**Resume after a release.** A fresh browser opens at `stopped_at` with the released fields; if the page no longer holds the form (session gone), the runner restarts the goal from the site's start once, then reports.

**Model and money.** Pool `cu` = `gemini-3.8-flash` with the computer-use tool, paid key only, no free fallback (a missing key ends the browse `refused: no paid key`). New cap `mission_cap_browse_turns` (default 400/day, Missions drawer). The browse's tokens and seconds are stored on its step. The planning steps stay on the pro pool and its cap.

**What the planner sees.** The report's `text`, `learned`, `stopped_at`, `outcome` and the last screenshot's path, compacted like any tool result. The planner never drives the browser; the runner never plans beyond its goal.

**Image.** The add-on Dockerfile installs Playwright's Chromium with its system deps. Without the binary the runner reports `refused: no browser on this box` and the mission moves on.

**Prompt to the runner.** The goal, the site, the released fields as "you may enter these and only these", the consent flags, and the standing rules in Appendix B. The runner's system text is fixed; the planner supplies only the goal.

## Section 3 — Mail search and a photo on a thread

**`search_mail(query, since_days=365, limit=5)`**, a READ tool in the registry and the router, parent/adult (the registry's reader for missions). IMAP SEARCH on the intake mailbox: the query's words OR'd across FROM, SUBJECT and TEXT, limited to messages newer than `since_days`, newest first; returns `[{uid, from, date, subject, snippet}]` with a 400-character snippet. **`read_mail(uid)`** returns one message's text, first 6,000 characters. Both open a read-only connection, move no cursor, make no LLM call, skip attachments. The mailbox is the family's; a child, helper or guest is refused.

**A photo on a thread.** `POST /api/threads/{id}/photo` (multipart image; parent/adult, or the thread's owner) stores the image under the media root beside moments and appends `{kind: 'photo', url, text}` to the history. `threads.read_photo` makes one vision-tier call (`thread_cap_photo_reads`, default 20/day) with a fixed prompt: transcribe what the image says that a repair, order or school office would ask for (model, serial, dates, amounts, names, reference numbers), verbatim, nothing inferred. The transcription is the entry's `text`; a failed or capped read leaves "photo added (not read)". The thread card's details get a camera button; the PWA House card the same; the /threads timeline shows the thumbnail and the text. A mission waiting on `ask_user` whose question asked for a photo resumes when a `photo` entry lands on its origin thread (the entry is appended as the `user_answer`).

## Section 4 — The conversation

**"Get the dishwasher fixed."** A new router tool `start_mission_for(goal, title?)` for parents and adults (voice as the parent of record): creates the thread (`threads.create`, direct, as `create_thread` is for parents today), launches a thread-origin mission on it, sets the conversation's focus to the thread, and replies "On it. I'll come back when I have something or need you." A mission already running on a matching thread is not duplicated: the tool says so and names it.

**The mission's reach.** Everything today plus `browse`, `search_mail`, `read_mail`, and the photo. Appendix B's planner rules tell it the order a person would take: our own mail first, the official site next, release only what the form needs, stop at the wall.

**Coming back.** Every `ask_user`, release and hand-off step DMs the person with the question and the answer path (reply in the Argyle DM, tap on the card, or say "tell the mission yes" through `act_on_situation` `answer`). A finish writes the summary as a thread `note`, sets the thread's next step by `advance` with a pre-filled action ("Book Tue Oct 20, 8–noon; trip charge $114.95") and DMs the same line. Nothing is booked.

**Triage.** A mission waiting on the person is tier 0 as today; its question is the spoken next step. A thread whose mission just finished carries the pre-filled `advance` as its lead, tier 1.

## Section 5 — Surfaces, settings, budget, tests, image

**Surfaces.** The thread card's details show the mission's steps inline (the shared transcript component), the browse step with its report, outcome and last screenshot thumbnail, and the release and hand-off cards with their buttons; the mission card the same. The PWA House card shows the release and hand-off cards too. The Argyle DM carries each as text with the link.

**Settings (Missions drawer, all registered):** the household contact card (ten fields, one section); `missions_captcha_attempts` (off); `mission_cap_browse_turns` 400/day; `thread_cap_photo_reads` 20/day.

**Budget.** A browse spends its turns on the paid key only; the planning steps spend the pro cap as today; mail search and photo storage cost nothing; one vision call per photo under its cap. No new calls on reads, ticks or sweeps.

**Failure honesty.** Every outcome but `done` names its reason in the mission transcript and the DM. A report never claims a slot, a price or a fact the screenshots do not show; the runner stores every screenshot so a person can check. "Nothing is booked" is said on every finish that touched a scheduling site.

**Image.** Dockerfile: `pip install playwright && playwright install --with-deps chromium`; about 400 MB more. `run.sh` unchanged.

**Tests.** Own tests plus named related:

- `test_browse_runner.py`: with a scripted fake model and local test pages (served by the test): domain stop and the one allowed redirect; the submit stop by label, by intent, by `type=submit`; the payment-field stop; `needs_release` with the wanted fields and no typing of unreleased values; the consented CAPTCHA cap (checkbox + two challenges, third ends it); turn and time caps; the missing-binary refusal; the memory floor; the report shape and screenshot paths.
- `test_browse_mission.py`: `browse` as a mission action end to end with the fake runner: report becomes a step; release pause → approve → resume with fields; decline → hand-off DM and `waiting_user`; the same site asks once per mission; a second site asks again; `captcha_failed` → hand-off; the finish writes the thread note and the pre-filled advance.
- `test_mail_tools.py`: `search_mail`/`read_mail` against a fake IMAP server object; role gates; no cursor movement; snippet and length caps.
- `test_thread_photo.py`: upload, storage path, the `photo` entry, the vision read with a stubbed pool call, the cap, "not read" on failure, the waiting mission resumed by the photo.
- `test_start_mission_for.py`: the tool creates thread + mission + focus; dedupe on a running mission; voice as the parent of record; a child refused.
- Live: the thread card's photo button and mission steps in details; the release card's buttons.
- `test_browse_smoke_real.py`: the Bodewell flow against the real site, run only with `CHF_BROWSE_SMOKE=1`, never in the gate.
- Existing, unchanged: `test_missions_*`, `test_threads_*`, `test_email_ingest`, `test_situation*`, `test_triage`, `test_reply_reading`.

**Acceptance scenarios**

1. "Get the dishwasher fixed" by voice → thread + mission; the mission finds the Café email (`search_mail`), asks for a label photo, the photo is read, `browse` reaches the Bodewell form, stops `needs_release`, the release card is approved, the browse resumes, the CAPTCHA is attempted under consent and fails on a third challenge → hand-off DM with the link and the filled fields → the person answers "Tue 20th 8–noon, $114.95" → the mission finishes: thread note, pre-filled advance, DM. Nothing booked.
2. The same with consent off: the browse stops at the CAPTCHA without touching it → hand-off.
3. A form that jumps to a payment page → `blocked: payment`, hand-off, no card field ever typed into.
4. A browse that leaves the site (a link to a marketplace) → one `go_back`, then `blocked: left the site`; the mission goes on with what it has.

**Three builds under this spec.** (1) `search_mail`/`read_mail` and the photo on a thread. (2) The runner, the `browse` action, the contact card and release flow, CAPTCHA policy, hand-off, the image change. (3) `start_mission_for`, the DMs and answers, the thread card's mission steps, the pre-filled finish, triage.

## Out of scope (named so they stay out)

- Remote hand: tapping a live screenshot from the phone to drive the browser. Later arc.
- Booking, paying, submitting, or sending anything from the browser.
- Attachments in mail search; searching any mailbox but the intake one.
- CAPTCHA solving beyond the capped, consented attempt; any evasion of bot detection (no proxies, no stealth plugins).
- Sites beyond the mission's own named site and its redirects.
- Running the browser anywhere but inside the add-on.

## Appendix A — Spike findings (2026-10-10, dev box, headless Chromium, paid key)

- Gemini Computer Use via `client.models.generate_content` with `types.Tool(computer_use=types.ComputerUse(environment=ENVIRONMENT_BROWSER))` on `gemini-3.8-flash`: GE service page → Bodewell → "Continue as Guest" → the guest scheduling form in 10 turns, 91 s, 84,107 input tokens, 1,925 output tokens (about $0.07 at list price). The model obeyed "enter nothing personal, stop at the form, report the required fields" and reported: first/last name, email, phone, preferred contact, street, city, state, ZIP, reCAPTCHA checkbox; slots and fee only after that step.
- The Interactions API (`client.interactions.create` with `{"type":"computer_use"}`) returned `400 Request blocked due to safety violations (harmful content)` on every continuation that carried a `function_result` for a computer-use action, including Google's own docs sample and a bare `"ok"` result on example.com, while a plain custom-function continuation succeeded on the same key. Not a content problem; not used.
- Headless Chromium from a home IP was served a CAPTCHA by Google's own docs site once mid-spike. Bodewell's form carries reCAPTCHA v2 (checkbox). A direct click on the checkbox outside the agent loop did not register (inconclusive).
- Safety decisions ride inside the function call's arguments (`safety_decision: {decision: require_confirmation, explanation}`) and are acknowledged with `safety_acknowledgement: "true"` in the function response.
- Spike scripts stayed in the session scratchpad; nothing was committed.

## Appendix B — Standing rules in the prompts

**Runner (fixed system text):** you are driving a browser for one family on one site; you may enter only the values you were given; never invent a name, address, phone or email; never click anything that submits, books, confirms, pays or orders; stop and report when a form wants a value you were not given, when a payment field appears, when a human-verification check appears (unless told you may try, and then at most the allowed attempts), when the page says access denied, or when the goal is met; your report states only what the screen showed.

**Planner (added to the mission system prompt):** to find a thing's details, search our own mail before the web; to deal with a company, prefer its official site; use `browse` only for what reading cannot answer and name the site; before any form that wants the family's details, expect a release step and wait for it; a browse that stops at a wall is a result, not a failure: hand it to the person; never claim a booking, a price or a slot the browse did not show.
