# Voice enrollment — set up your voice by talking to Argyle, on a satellite or on your phone

**Date:** 2026-10-13. **Revised:** 2026-10-13 after a Codex adversarial review (five findings, all confirmed against the code and the locked rules; each is resolved below and named in **Review resolutions**). **Status:** draft for review. Nothing here is implemented.
**Builds on:** [Voice identity](2026-10-12-voice-identity-design.md), [Voice fingerprint](2026-10-12-voice-fingerprint-design.md), [App voice](2026-10-12-app-voice-design.md) (the phone capture path shipped in v2.499.408). Replaces the enrollment half that was cut from the app-voice spec and the manual cross-microphone experiment in [the feasibility notes](../experiments/2026-10-13-phone-voice-feasibility.md): a twenty-second spoken check on each speaker replaces the probe.

## Outcome

A family member says "Hey Argyle, set up my voice" to a satellite, or taps Set up my voice on their phone, answers a few short questions, and is done in one sitting. No Config page, no satellite picker, no refresh between samples, no phrase to memorize. A voice made on a phone is checked on a speaker with one more sentence before that speaker uses it.

Today's flow (Config › Voice identity: pick a satellite, pick a member, tick consent, press Enroll, wake Argyle five times, read a 15-word phrase off the phone each time, refresh the page in between, within ten minutes) stays as the hand path and gains only status.

## Boundary

- Recognition means naming, never authority. A template sets a session to `named`; PIN still sets `verified`; release, submit and payment keep their PIN-backed rules. Nothing here changes approval authority.
- The locked activation rule stands: recognition on a satellite is turned on by a parent after that satellite's check, never by the act of enrolling (fingerprint spec, builds F2 and the per-satellite setting). This spec makes that parent act a spoken word where the parent is already present; it does not remove it.
- No store migration. `templates.json` keeps its shape and gains fields. No portable-profile store, no rollback machinery.
- No background listening, no ambient samples, no enrollment from mission audio or from a PIN alone. Every sample is one deliberate answer to one question Argyle asked, admitted by the rule below.
- Speech during an active enrollment never reaches the chat model: it is a sample, setup guidance, or a cancellation (fingerprint spec review correction). An enrollment therefore owns its satellite for at most ten minutes, and "cancel voice setup" or silence hands it back.
- Archival and disabling keep stored templates and stop matching; only explicit voice deletion or permanent member deletion removes them (fingerprint spec review correction).

## The shared enrollment core

One state machine, two front doors. `services/voice_fingerprint.py` already holds samples, a centroid, two held-out checks, rival margins and the 600 s expiry; it is reshaped, not replaced.

**Samples are answers, not phrases.** The speaker model is text-independent, so the verbatim-phrase check is replaced by an admission rule that binds each sample to the question that asked for it and to the person being enrolled. Argyle asks questions that invite eight to twelve seconds of natural speech:

1. "Tell me about your day so far, for about ten seconds."
2. "What is coming up for the family this week?"
3. "Describe the room you are in."
4. "What would you like help with most mornings?" (check)
5. "Tell me something you are looking forward to." (check)

**Admission rule.** A sample is admitted only when all of these hold:
- The enrollment is awaiting an answer to a specific step, and the turn is that step's answer: on a satellite, the utterance that HA delivers as the continuation of the question's response, carrying the question's conversation id and the one-use step token the server issued with the question; on a phone, the audio upload for the request id that was issued for that step. A turn without the current token is not a sample; it gets setup guidance.
- The observation is the turn's own (exact run key on a satellite, request id on a phone), as today.
- At least four seconds of voiced audio (the existing `extract` rule); under that, "A little longer, please" and the same step again. Three unusable attempts at one step end the enrollment with a reason.
- **Speaker binding.** The credential utterance that opened the enrollment (the enrollee's own PIN, or the consenting parent's PIN) has its own fingerprint, held in memory for this enrollment only and never stored. For a self-enrollment every sample must be continuous with that fingerprint (the person who said the PIN is the person being enrolled). For a child's enrollment every sample must be mutually consistent and must not be continuous with the parent's credential fingerprint (the parent consented; the parent is not the voice). A sample that fails binding ends the enrollment and says why. When the credential utterance yields no usable fingerprint, the enrollment still runs on mutual consistency alone and the finish says so; the parent's confirmation (below) is then the only speaker evidence, which is what today's flow has.

The transcript is never identity proof and never stored.

**Consistency and checks** stay as they are: checks 4 and 5 must clear the naming threshold against the centroid and the margin against every other calibrated template on that satellite; a new similar template still invalidates affected calibrations. Thresholds are never lowered to finish a setup.

**Who is enrolled, who consents, how it is verified.**
- An adult enrolls themself. Identity is their own PIN through the existing intercept; that turn's fingerprint becomes the binding anchor.
- A child is enrolled with a parent's consent. This uses an **enrollment-scoped consent verifier**, not the session PIN intercept: Argyle asks "Which parent?" when there is more than one, verifies that parent's PIN against that parent's record with that parent's rate limits and locks, records the parent as consent actor, and keeps that turn's fingerprint as the exclusion anchor. It creates no parent voice session and no speaker anchor on the session; the child stays the actor for everything after. On a phone, the parent enters the PIN on the child's screen and the same verifier runs.
- At the finish of a child's enrollment Argyle asks the parent "Was that Lily? Say yes." Only yes saves the template.
- Household, wall and service sessions cannot enroll anyone.

**Finishing.** On the fifth sample the template is saved with provenance (`satellite` or `phone`), the capturing device, the consent actor and the model revision. A satellite-made template is `checked` on that satellite. Recognition on that satellite is **not** turned on by finishing (see Activation). A re-enrollment replaces the old template only when it passes; a failed one leaves the old template untouched.

**Cancel.** "Cancel voice setup", a Stop tap on the phone, ten minutes of silence or three unusable attempts end the enrollment and discard its samples and anchors. Any other speech during enrollment gets setup guidance ("Voice setup is in progress. Answer the question, or say cancel voice setup.") and is never answered as a request.

## Satellite flow

"Hey Argyle, set up my voice."

1. Argyle: "Who is this for?" The existing name intercept resolves the member. "For Lily" by a parent resolves the child.
2. Argyle: "Say your PIN." (adult) or "Which parent? Say your PIN." (child). The enrollee's PIN goes through the existing intercept; a parent's PIN for a child goes through the consent verifier. A wrong PIN ends the enrollment.
3. Argyle asks question 1, issues the step token, and returns `continue_conversation: true`, so the satellite listens without a wake word. The answer arrives as its own HA run with its own observation; the admission rule decides whether it is a sample. Argyle acknowledges in one word ("Got it.") and asks the next question with a new token and the flag set again.
4. After the fifth, and for a child the parent's "yes": "Your voice is saved here." Then the activation question (below). The flag is off, the enrollment is gone.

The satellite speaks each question before it listens, so Argyle's own playback is never in a sample. The HA component already returns the continue flag to the pipeline; the plan's first task is a served test asserting that each continued turn arrives as a distinct run with its own observation and the question's conversation id. If the installed HA version does not continue, the fallback is the wake word before each answer with the same server flow.

## Phone flow

Entry: the PWA's account sheet, where the member's PIN is managed, gains Set up my voice. The screen says what recognition does, that it is optional, that only a local voice template is saved, and that the household's STT provider will hear the answers. Start or Cancel.

1. The member is the signed-in personal session. A child's screen asks for a parent's PIN before Start, through the consent verifier.
2. The first question appears on screen and is read aloud by the existing phone reply path; capture opens after playback ends, using the shipped recorder. One tap per answer, with Done and a 15 s cap, exactly like a chat turn. The audio reaches the server through the voice turn's audio endpoint in a server-selected enrollment mode: decoded with the existing `pcm` helper, embedded, never transcribed and never dispatched to the agent. Each step issues its own request id, which is the admission token.
3. "1 of 5", a small acknowledgment, the next question. A short or clipped answer asks again with the reason.
4. "Saved. Your speakers will each check it the first time: say 'Hey Argyle, check my voice' in the kitchen." Then Try talking to Argyle, or Done.

A phone-made template binds to the phone's credential: the signed-in session for an adult. The phone has no spoken PIN utterance to anchor on, so speaker binding there is mutual consistency, which is the phone's own guarantee that one person answered all five.

No raw audio, per-step vectors or transcripts leave memory; audio routes stay out of service-worker caches and request logs, as for chat.

## Checking a phone voice on a speaker

A phone-made template is `unchecked` on every satellite and is never used for naming there until checked. The check is a deliberate twenty seconds, not a background inference:

"Hey Argyle, check my voice." Argyle asks for the PIN (the person's own; a parent's for a child, through the consent verifier), then asks one question and continues listening. The answer is admitted by the same rule and must be continuous with the credential utterance's fingerprint. It is scored against the phone template with the naming threshold and the margin against every calibrated template on that satellite.

- Clears it: the template is `checked` on that satellite, and Argyle says "Your phone voice works here." Then the activation question.
- Does not: Argyle says "Your phone voice does not match this microphone. Shall I set up your voice here now?" Yes rolls straight into the satellite flow, with the check's answer kept as sample 1 and the PIN already verified. No means the template stays `does_not_transfer` on that satellite, shown in Config in words.

No passive scoring of ordinary conversation, no hit and miss counters, no trust in a retained session. A check is one explicit act by the person, bound to a fresh credential utterance.

## Activation

The locked rule: recognition on a satellite is enabled per satellite by a parent after that satellite's check. The spoken forms:

- A parent who has just enrolled or checked their **own** voice on that satellite, with their own PIN, is asked "Turn on voice recognition for you here? Say yes." Yes enables it: the parent act and the check are both present.
- After a child's enrollment or check, the consenting parent, already verified for this enrollment, is asked the same for the child. Yes enables it.
- A non-parent adult hears "Saved. A parent can turn on recognition for you here." A parent later says "turn on voice recognition for Sam here" (name resolved, parent PIN through the intercept) or taps it in Config, as today.

Turning it off, per satellite, stays as it is: a spoken parent act or Config.

## Storage

`templates.json` rows gain: `provenance` (`satellite` | `phone`), `device_id` of the capture device, `consent_actor` (already present), `checks`: a map from satellite key to `checked` | `does_not_transfer`. Existing rows read as `provenance: satellite`, checked on their own key. Readers ignore fields they do not know. Credential fingerprints and step tokens live only in the in-memory enrollment and die with it.

Deletion: Delete my voice removes every template for that member and cancels pending enrollments; permanent member deletion does the same. Archiving or disabling a member stops matching and cancels any pending enrollment but keeps the templates, per the status ladder and the fingerprint spec.

## Hand paths and surfaces

- Config › Voice identity keeps everything it has. It adds, per member and satellite, the check state in words, and loses nothing.
- The PWA account sheet: Set up my voice, Set up again, Turn recognition off for me, Delete my voice. Disabling is reversible; deletion is explicit and confirmed with `promptConfirm`.
- Argyle on a satellite: "set up my voice", "check my voice", "cancel voice setup", "turn on voice recognition for <name> here", and after enrollment "that's not me" keeps clearing a named session as today.

## Identity and safety

- A spoken PIN goes through the intercept or the consent verifier and is never shown, stored or sent to a model. The consent verifier never creates a parent session, anchor or readback; it consumes the credential turn only.
- Samples are admitted only by the rule above; neighbouring speech on the same satellite, a turn without the current step token, or a different voice from the credential's cannot enroll anyone.
- Enrollment turns are intercepted before history, titles, SSE and the agent, like PIN turns today.
- Rate limits and voice locks apply unchanged, against the record whose PIN was said. Enrollment is capped at one pending per satellite and per member, sixteen household-wide.
- Spoken prompts and the phone's screen never read a PIN back.

## Review resolutions

1. *A retained PIN session can calibrate the wrong speaker.* Shadow acceptance is gone. The check is an explicit act bound to a fresh credential utterance; sessions are never ground truth.
2. *Run correlation does not bind speech to a question.* The admission rule: one-use step token, the question's conversation id, the run's own observation, and speaker binding to the credential fingerprint.
3. *The PIN intercept verifies the child, not the parent.* The enrollment-scoped consent verifier resolves the parent, checks the parent's PIN with the parent's limits, and creates no parent session.
4. *Finishing bypassed the activation gate.* Activation is a separate parent act, spoken where the parent is present, per satellite, after the check.
5. *Archival would delete templates.* Archival and disabling keep templates and stop matching; only explicit deletion removes them.

## Testing and acceptance

- Unit, offline, with fixture vectors: both doors through the state machine (questions, short-sample retry, three-strike end, consistency end, binding end, checks, finish, cancel, expiry, unrelated speech gets guidance and never the agent); the admission rule (stale token, missing token, wrong conversation id, neighbouring run, speaker takeover before sample one, a sibling answering during a child's enrollment); the consent verifier (which parent, wrong parent PIN hits the parent's counters not the child's, no parent session created, parent-to-child handoff); the check (clears, does not transfer, rolls into enrollment keeping sample 1); activation (parent self yes, parent-for-child yes, non-parent told to wait, spoken turn-on by name); storage fields, backwards reading, archival keeps, deletion removes.
- Served: the satellite converse endpoint drives a whole enrollment through `continue_conversation`, asserting each continued turn is a distinct run with its own observation and the question's conversation id; the phone endpoints drive one through the audio route in enrollment mode with no transcript and no agent dispatch.
- Device, before this is called done: one adult enrolls on the kitchen satellite in one conversation and turns recognition on by voice; one adult enrolls on an iPhone and checks it in the kitchen, and Config shows `checked` or `does_not_transfer`; a child is enrolled with a parent's PIN and the parent's "yes", and the parent's session is unchanged afterwards.

## Delivery and split

Order: the shared core (questions, admission rule, consent verifier, provenance and check fields) with its tests; the satellite flow with the continuation test; the check and activation; the phone flow; the Config and PWA surfaces. Each ships behind nothing: the current manual flow keeps working throughout.

Under the standing coordination rule: Claude writes this spec and the tests; Codex adversarial-reviews the spec before the plan (done once; the revised spec goes back for a second pass); Codex builds the enrollment core, the admission rule and the consent verifier against the tests; Claude builds the satellite dialog, the check and activation dialog, the phone flow and the surfaces, reviews Codex's diff, runs the gate, documents, bumps and commits.

## Revision 2026-10-13, evening: one setup works everywhere (user decision on device evidence)

A phone-made voice passed "check my voice" on the kitchen satellite twice on the real device, so the per-speaker caution has done its job and is retired:

- A voice set up anywhere, phone or satellite, names its person on every speaker (`voice_fingerprint.usable_on`). The per-speaker record now only marks a speaker where a check proved the voice does not transfer; that speaker gets "set up your voice here" once. A template whose two checks failed, or that a similar new voice invalidated, is never used for naming anywhere (`calibrated`).
- "Check my voice" is optional: something to say on a speaker that gets you wrong, not a setup step.
- Activation is one household switch, still a parent's act: `set_recognition_everywhere`. The spoken "yes" after an enrollment or a check turns recognition on for every enabled speaker; once on, later setups just save. Config keeps the per-speaker checkboxes as the hand path for switching one speaker off by itself.
- This amends the fingerprint spec's per-satellite activation rule for this household, on measured evidence.

Also from the first device runs: a setup dialog's PIN anchor and check answer get the 3 s embedding wait; bare "cancel" cancels; names resolve by first or full name with or without a lead-in, and a PIN said before the name is answered with "your name first"; informal yes and no are understood everywhere in the dialog, and a non-answer is asked once more.

