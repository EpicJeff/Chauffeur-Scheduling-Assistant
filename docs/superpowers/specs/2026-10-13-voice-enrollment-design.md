# Voice enrollment — set up your voice by talking to Argyle, on a satellite or on your phone

**Date:** 2026-10-13. **Status:** draft for review. Nothing here is implemented.
**Builds on:** [Voice identity](2026-10-12-voice-identity-design.md), [Voice fingerprint](2026-10-12-voice-fingerprint-design.md), [App voice](2026-10-12-app-voice-design.md) (the phone capture path shipped in v2.499.408). Replaces the enrollment half that was cut from the app-voice spec and the cross-microphone experiment in [the feasibility notes](../experiments/2026-10-13-phone-voice-feasibility.md): the system runs that check itself, during normal use.

## Outcome

A family member says "Hey Argyle, set up my voice" to a satellite, or taps Set up my voice on their phone, answers a few short questions, and is done in one sitting. No Config page, no satellite picker, no refresh between samples, no phrase to memorize. Afterwards the satellites that have confirmed that voice name the person without a name introduction.

Today's flow (Config › Voice identity: pick a satellite, pick a member, tick consent, press Enroll, wake Argyle five times, read a 15-word phrase off the phone each time, refresh the page in between, within ten minutes) stays as the hand path and gains only status.

## Boundary

- Recognition means naming, never authority. A template sets a session to `named`; PIN still sets `verified`; release, submit and payment keep their PIN-backed rules. Nothing in this spec changes approval authority.
- No store migration. `templates.json` keeps its shape and gains fields. No portable-profile store, no rollback machinery.
- No experiment, no probe, no manual recordings. Whether a phone template works on a given satellite is learned from use (shadow acceptance below).
- No background listening, no ambient samples, no enrollment from mission audio or from a PIN alone. Every sample is one deliberate answer to one question Argyle asked, bound to its exact run.

## The shared enrollment core

One state machine, two front doors. `services/voice_fingerprint.py` already holds samples, a centroid, two held-out checks, rival margins and the 600 s expiry; it is reshaped, not replaced.

**Samples are answers, not phrases.** The speaker model is text-independent, and each sample is already bound to the run that produced it (satellite: the HA run key; phone: the voice turn's request id). So the prompt check that demanded a verbatim phrase goes. Argyle asks a question that invites eight to twelve seconds of natural speech:

1. "Tell me about your day so far, for about ten seconds."
2. "What is coming up for the family this week?"
3. "Describe the room you are in."
4. "What would you like help with most mornings?" (check)
5. "Tell me something you are looking forward to." (check)

A sample is usable at four seconds of voiced audio (the existing `extract` rule); under that, Argyle says "A little longer, please" and asks the same question again. Three unusable attempts at one step end the enrollment with a reason. The transcript is never identity proof and never stored.

**Consistency and checks** stay as they are: a sample that does not resemble the earlier ones ends the enrollment; checks 4 and 5 must clear the naming threshold against the centroid and the margin against every other calibrated template on that satellite class. Thresholds are never lowered to finish a setup.

**Who is being enrolled, and who consents.**
- An adult enrolls themself. Identity is their own PIN, which is also the consent.
- A child is enrolled with a parent's PIN as the consent, spoken on the same satellite or entered on the child's phone. The child stays the person enrolled and the actor for everything after. The consent actor is recorded on the template.
- Household, wall and service sessions cannot enroll anyone.

**Finishing.** On the fifth sample the template is saved with provenance (`satellite` or `phone`), the capturing device, the consent actor and the model revision. A satellite-made template is calibrated for that satellite immediately, as today. Recognition on that satellite is turned on for that person as part of finishing; there is no separate per-person toggle. A re-enrollment replaces the old template only when it passes; a failed one leaves the old template untouched.

**Cancel.** "Cancel voice setup", a Stop tap on the phone, ten minutes of silence, or any unrelated request on the satellite ends the enrollment and discards its samples. An unrelated request is answered normally; it is not fed to the enrollment.

## Satellite flow

"Hey Argyle, set up my voice."

1. Argyle: "Who is this for?" The existing name intercept resolves the member. "For Lily" by a parent resolves the child.
2. Argyle: "Say your PIN." (adult) or "A parent's PIN, please." (child). The existing PIN intercept verifies it; the same rate limits and locks apply. A wrong PIN ends the enrollment.
3. Argyle asks question 1 and returns `continue_conversation: true`, so the satellite listens without a wake word. The answer arrives as an ordinary run with its own observation; the enrollment consumes it. Argyle acknowledges in one word ("Got it.") and asks the next question with the flag set again.
4. After the fifth: "Your voice is ready here." The flag is off, the enrollment is gone.

The satellite speaks each question before it listens, so Argyle's own playback is never in a sample. The HA component already returns the continue flag to the pipeline; no component change is expected. If the installed HA version ignores the flag, the fallback is the wake word before each answer, with the same server flow.

## Phone flow

Entry: the PWA's account sheet, where the member's PIN is managed, gains Set up my voice. The screen says what recognition does, that it is optional, that only a local voice template is saved, and that the household's STT provider will hear the answers. Start or Cancel.

1. The member is the signed-in personal session. A child's screen asks for a parent's PIN before Start.
2. The first question appears on screen and is read aloud by the existing phone reply path; capture opens after playback ends, using the shipped recorder. One tap per answer, with Done and a 15 s cap, exactly like a chat turn. The audio reaches the server through the voice turn's audio endpoint in a server-selected enrollment mode: it is decoded with the existing `pcm` helper, embedded, and never transcribed or dispatched to the agent.
3. "1 of 5", a small acknowledgment, the next question. A short or clipped answer asks again with the reason.
4. "Saved. This phone made it; your kitchen speaker will confirm it the first few times it hears you." Then Try talking to Argyle, or Done.

No raw audio, per-step vectors or transcripts leave memory; audio routes stay out of service-worker caches and request logs, as for chat.

## Shadow acceptance: the check the system runs

A phone-made template is `unverified` on every satellite. On each satellite it earns or loses trust from ordinary use:

- When a satellite utterance arrives whose speaker is already known another way (a PIN-verified session for that member, or a confident match by that member's satellite-made template), and its observation carries a usable vector, that vector is scored against the phone template: a `hit` if it clears the naming threshold with the margin, a `miss` otherwise. Inconclusive samples count as nothing.
- Three hits on a satellite accept the template there: it becomes calibrated for that satellite and can name the person. Three misses mark it `does_not_transfer` there; it is never used for naming on that satellite, and Config says so in words ("your phone voice does not match the kitchen microphone; set up your voice there").
- Scoring is passive. It never changes the current session, never greets, never writes anything but the hit and miss counters. It stops once accepted or rejected.
- A satellite-made template never needs acceptance; it was made where it is used.

This replaces the manual experiment. If phone templates never transfer in a household, the phone flow still gives a correct template for the phone's own future uses, and the satellite flow carries recognition.

## Storage

`templates.json` rows gain: `provenance` (`satellite` | `phone`), `device_id` of the capture device, `consent_actor` (already present), `acceptance`: a map from satellite key to `{hits, misses, state}` with `state` in `unverified` | `accepted` | `does_not_transfer`. Existing rows read as `provenance: satellite`, accepted on their own key. Readers ignore fields they do not know.

Deletion is unchanged: Delete my voice removes every template for that member and cancels pending enrollments; member archival or deletion does the same. Disabling a member stops matching but keeps the template, per the status ladder.

## Hand paths and surfaces

- Config › Voice identity keeps everything it has. It adds, per member and satellite, the acceptance state in words, and loses nothing.
- The PWA account sheet: Set up my voice, Set up again, Turn recognition off for me, Delete my voice. Disabling is reversible; deletion is explicit and confirmed with `promptConfirm`.
- Argyle on a satellite: "set up my voice", "cancel voice setup", and after enrollment "that's not me" keeps clearing a named session as today.

## Identity and safety

- The spoken PIN goes through the existing intercept and is never shown, stored or sent to a model. A parent's PIN spoken for a child's enrollment verifies the parent for that turn only and does not sign the child in as the parent.
- Samples are matched to their exact run or request id; neighbouring speech on the same satellite cannot enroll anyone.
- The enrollment's conversation turns are intercepted before history, titles, SSE and the agent, like PIN turns today.
- Rate limits and voice locks apply unchanged. Enrollment is capped at one pending per satellite and per member, sixteen household-wide.
- Spoken prompts and the phone's screen never read the PIN back.

## Testing and acceptance

- Unit, offline, with fixture vectors: the state machine for both doors (questions, short-sample retry, three-strike end, consistency end, checks, finish, cancel, expiry, unrelated-request pass-through); consent rules (adult self, child needs parent PIN, wall and service sessions refused); shadow scoring (hit, miss, inconclusive, acceptance at three, rejection at three, passive and session-neutral); storage fields and backwards reading; deletion and disable.
- Served: the satellite converse endpoint drives a whole enrollment through `continue_conversation`; the phone endpoints drive one through the audio route in enrollment mode with no transcript and no agent dispatch.
- Device, before this is called done: one adult enrolls on the kitchen satellite in one conversation; one adult enrolls on an iPhone; the phone template reaches `accepted` or `does_not_transfer` on the kitchen satellite from ordinary use within a few days, and Config shows which.

## Delivery and split

Order: the shared core (questions, consent, provenance, acceptance fields) with its tests; the satellite flow; the phone flow; the shadow scorer; the Config and PWA surfaces. Each ships behind nothing: the current manual flow keeps working throughout.

Under the standing coordination rule: Claude writes this spec and the tests; Codex adversarial-reviews the spec before the plan; Codex builds the enrollment core and the shadow scorer against the tests; Claude builds the satellite dialog, the phone flow and the surfaces, reviews Codex's diff, runs the gate, documents, bumps and commits.
