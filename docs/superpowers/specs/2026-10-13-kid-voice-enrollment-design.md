# Kid voice enrollment — many short answers instead of a few long ones

**Date:** 2026-10-13. **Status:** draft design, agreed in conversation, revised once after a Codex adversarial review (same evening; the five findings and what changed are at the end). Not yet planned. Nothing here is implemented.
**Builds on:** [Voice enrollment](2026-10-13-voice-enrollment-design.md) as revised the same evening (one setup works everywhere; one household switch). This spec changes how a sample is assembled, how a held-out check is scored for a pooled enrollment, how a child's voice is positively established before anything is dropped, and how Argyle talks to a child. Thresholds and activation are untouched. Two gaps in today's consent path that the review found are fixed here for every enrollment, not only pooled ones.

## Outcome

A parent says "Hey Argyle, set up Lily's voice" in the kitchen, gives their PIN, and Lily answers a dozen quick questions about her favorite color, food, animal and friends while Argyle keeps the microphone open. The parent says "yes, that was Lily" and recognition keeps working. No sentence a six-year-old cannot say, no "a little longer, please".

## Why the model allows it

The speaker model is text-independent. What a sample needs is about four seconds of voiced speech, and the core needs five samples (three to train, two held-out checks). A child giving one- to two-second answers to twelve or fifteen questions produces the same amount of voice as an adult answering five questions for ten seconds each. The adult flow is the right shape for adults and the wrong shape for children, who cannot hold a ten-second monologue on request.

## The one mechanism change: pooled samples

- The five-sample core is untouched. A **pooled step** assembles one sample from several short answers: each answer is embedded on its own and admitted by the existing rule (one-use token, the question's conversation id, the run's own observation, speaker binding), and the dialog keeps asking until the step holds **four seconds of voiced speech**, then the step's sample is the normalized mean of those embeddings.
- Thresholds (`THRESHOLD, MARGIN, CONTINUITY`), provenance and per-speaker check state are exactly as today. The **training** samples (steps 1 to 3) are pooled means; the centroid is their normalized mean, as today.
- The **held-out checks** (steps 4 and 5) are **not** scored on the pooled sample. Each short answer in a check step is scored **alone** against the centroid and the rivals, with today's threshold and margin, and the step passes only if every answer in it passes. Reason (review finding 1): a normalized mean of several noisy short embeddings sits closer to the centroid than any single one of them does, so a pooled check would pass more easily than live recognition, which scores one ordinary utterance of 1.2 s or more (`IDENTIFY_SECONDS`) in `apply()`. Scoring the individual short answers is the honest stand-in for what the kitchen will do with this child's "Hey Argyle" tomorrow. The check step still collects four voiced seconds so it exercises several answers, not one lucky one.
- A pooled template therefore carries no claim that the thresholds are proven for children. The device step below is the proof per household, and it includes negatives.
- The per-answer floor is **one second** of voiced speech (the embedder's own floor is 1.2 s of audio; a pooled answer under one second is kept out of the pool, not refused). Anything shorter gets a follow-up question, never "a little longer".
- Pooling is a property of the enrollment (`pooled: true`), chosen by the dialog, not by the person. The phone door does not pool: a child cannot read the prompts there, and the satellite is the door for children.

## Establishing the child's voice before anything is dropped

Today's rule aborts on the first inconsistent answer. The review (finding 2) showed that softening it to drop-and-continue without a positive reference lets whoever answers first seed the pool: a sibling who answers the first two questions becomes "the child", and Lily's own answers get dropped as inconsistent. The parent's fingerprint only says who the child is *not*. So:

- **Pool 1 is hard.** Answers within the first pool must be mutually continuous (`CONTINUITY`), as today. An inconsistent answer inside pool 1 discards the whole pool and starts it again ("Let's start over. What's your favorite color?"); a second discard ends the setup.
- **The parent names the voice.** When pool 1 fills, Argyle turns to the parent: "Is that Lily talking? Say yes." A yes makes pool 1's mean the enrollment's **anchor** (the same `anchor` field a self-enrollment binds to its PIN voice today); a no ends the setup ("Not saved. Try again when it's just Lily."). The questions resume with the child.
- **After the anchor, dropping is safe.** Every later answer must be continuous with the anchor (`CONTINUITY`), exactly today's anchor rule; one that is not is **dropped**, Argyle says "Let's try another one" and asks the next question. Three drops in a row end the setup. The parent-exclusion rule stays hard on every answer, pool 1 included: an answer continuous with the parent's fingerprint ends the setup, as today.
- Pooling never crosses a pool boundary: a dropped answer is forgotten, a kept answer belongs to the pool that was open when it was admitted.

## The dialog, for a child

1. **Start.** "Set up Lily's voice" or "set up my voice" followed by "for Lily" as today. The consent step is the parent's PIN through the enrollment-scoped verifier, no parent session, the parent's fingerprint kept as the exclusion anchor. **New, for every child enrollment (finding 3):** if the PIN turn yields no usable fingerprint (short PIN, worker busy, timeout), the enrollment does not start with `exclude=None` as it does today. Argyle asks the parent for one longer line first, "Say: I'm giving consent for Lily to set up her voice", up to three times, and ends the setup if none produces a fingerprint ("I couldn't hear you well enough to go on."). A child enrollment always has the parent's voice to exclude.
2. **Hand-off to the child.** Argyle: "Hi Lily. I'm going to ask you some questions. Just answer out loud. What's your favorite color?" The microphone stays open through `continue_conversation` as today.
3. **Questions.** Short, concrete questions in a fixed order, then **follow-ups on the same topic** when the list is spent, because the list alone cannot fill five pools (finding 5: five pools need twenty voiced seconds, fifteen one-second answers give fifteen). Completion is counted in accepted voiced seconds and pools, never in questions asked. The fixed list:
   - What's your favorite color, and why?
   - What's your favorite food?
   - What do you like to do at the park?
   - What's your favorite animal?
   - What did you have for breakfast today?
   - Who is your best friend, and what do you play together?
   - What do you want to be when you grow up?
   - What's the best part of school?
   - What's a game you like to play?
   - Do you have a pet or a stuffed animal? What's its name?
   - What's your favorite thing to do on the weekend?
   - If you could go anywhere, where would you go?
   - What makes you laugh?
   - What's your favorite song or show?
   - What do you like to eat for dinner?
   After the fifteenth, the dialog cycles the topics with a follow-up lead ("Tell me more about your favorite animal.", "What else do you like at the park?"), so questions never run out before the pools fill. Between answers Argyle says one of "Nice.", "Cool.", "Good one." and asks the next. When a pool fills, nothing is announced; the game just continues. The count-down is by pools, not questions: "Almost done!" when the fifth pool opens, and nothing else is promised, because how many answers remain depends on how long the child talks. **Exhaustion:** forty admitted turns (answers, follow-ups and drops together) without five pools end the setup with the parent message "That's enough for today. I couldn't get all of Lily's voice; try again another time." The template is not saved and any existing template for the child is untouched.
4. **A short answer** (under one second of voice): Argyle asks a follow-up on the same topic, "Why is that your favorite?" or "Tell me more about that", instead of a retry message. Three follow-ups in a row that stay under a second end the setup with a message to the parent, not the child: "I couldn't get enough of Lily's voice. Try again another time."
5. **Drift and siblings.** A child wanders mid-answer and siblings chime in. For a pooled enrollment the consistency rule is softened: an answer that does not match the pool so far is **dropped**, Argyle says "Let's try another one" and asks the next question; three dropped answers end the setup. The parent-exclusion rule stays hard: an answer continuous with the parent's fingerprint ends the setup, as today.
6. **Finish.** After the fifth pool: "All done! If that was Lily, say your PIN." to the parent. **The final confirmation is the consenting parent's PIN again, not a yes (finding 4; the user chose this over a transcript yes, 2026-10-13).** Today both the "Was that them?" yes and the activation yes are accepted on the transcript alone, from any voice, in any conversation; a one-word yes cannot carry speaker evidence (the embedder needs 1.2 s). The PIN turn is the one spoken thing that both authenticates the parent (the enrollment-scoped verifier, the same one that gave consent, the same parent) and carries a fingerprint long enough to score: it must be continuous with the parent's exclusion fingerprint (`CONTINUITY`), or Argyle says "That did not sound like the parent who gave consent." and asks again. A wrong PIN is the verifier's message and one more try; the verifier's lockout ends the setup; the PIN must arrive in the **same conversation** the question opened (the dialog records the question's conversation id, as `expect_conversation` does for an answer). This replaces the confirm phase for **every** enrollment where the consenting parent is not the person being set up, pooled or not, whether or not an exclusion fingerprint exists (today the yes is skipped when `exclude` is None). A self-enrollment still ends as today, with no confirmation, because every sample was bound to the PIN voice. Then the household activation question if recognition is not already on, a yes as today, now bound to the same conversation as the PIN that just verified the parent. The template is saved with `provenance: satellite` and `pooled: true` for diagnostics. The mid-dialog "Is that Lily talking?" stays a transcript yes: it only chooses the anchor, and the PIN at the end is the gate on the whole result.
7. **Cancel.** "Cancel", "stop", "we're done" from anyone ends it, as today, including a child who says "stop" on its own; a sentence that merely contains the word is an answer (today's rule: only a bare cancel word cancels). **Silence:** HA closes the conversation when nobody speaks; the enrollment stays open ten minutes (`expires_at`, as today) and the parent re-opens it with "Hey Argyle" plus anything, which the open-dialog path already adopts as the next question (the Config-started path does this today).

An adult can ask for the short questions too ("the short questions" or "the kid questions" at the start) for someone who finds the long answers hard; the mechanism does not care about age, only the dialog's choice of questions.

## What does not change

- Admission: every answer is still one run, one token, one observation, bound to its credential.
- Consent: parent PIN for a child at the start and again before saving, no parent session created.
- Thresholds: `THRESHOLD, MARGIN, CONTINUITY` and the rival margin are untouched. What is scored against them changes for a pooled check step (each short answer alone).
- Activation: one household switch, a parent's spoken "yes" or Config.
- Storage: `templates.json` gains only `pooled: true` on rows made this way; readers ignore it.
- The phone door is unchanged: it does not pool, and it has no closing confirmation (a present parent types the PIN on the child's screen at the start, which is the parent's own authenticated act). The adult satellite flow gains the consent fixes above (no child enrollment without an exclusion fingerprint; the parent's PIN instead of a yes before saving someone else's voice; the activation yes bound to its conversation), which it should have had.

## Risks and how they are met

- **Pooled embeddings of short answers are noisier than one long one.** The pool is assembled from one-second-plus answers up to four seconds of voice, the same total voice as an adult sample; but equal duration does not make equal statistics, so the held-out checks score each short answer alone (the shape of a live query) and the device step includes negatives. A child whose checks fail stays off, as today. If the kitchen shows wrong names for children after this ships, raise the per-step pool to six seconds before touching thresholds.
- **A sibling answering for the child.** Pool 1 is hard, the parent names pool 1's voice, and every later answer must be continuous with it; a sibling's answers are dropped, three in a row end it. A sibling who answers first is caught by the parent's "Is that Lily talking?".
- **Boredom.** Fifteen questions is the ceiling; most children fill five pooled steps in nine to twelve answers. The count-down lines keep it a game.

## Testing

- Unit, offline, with fixture vectors: a pooled step fills at four voiced seconds across three one-and-a-half-second answers and produces the normalized mean; an answer under one second is kept out of the pool and asks a follow-up; three sub-second follow-ups end the setup; an inconsistent answer inside pool 1 discards the pool and a second discard ends the setup; after the anchor a non-continuous answer is dropped with "let's try another one" and three drops end it; a sibling-first run (two sibling answers, then the child) is stopped by the hard pool-1 rule or by the parent's no at "Is that Lily talking?"; an alternating-speaker run never fills a pool with two voices; the parent-exclusion rule ends it on the first parental answer in any pool; a held-out check step scores each short answer alone with unchanged thresholds and fails when one answer fails even if the pooled mean would pass; forty turns without five pools end the setup and leave an existing template untouched; the finished row carries `pooled: true`.
- Consent fixes, for every satellite enrollment of someone else: a child enrollment whose PIN turn has no fingerprint asks for the consent line and never starts with `exclude=None`; the final confirmation is the parent's PIN even without an exclusion fingerprint; a "yes" at that point is answered with "say your PIN"; a correct PIN from a voice that is not continuous with the parent's fingerprint re-asks; a wrong PIN gets one more try and the lockout ends the setup; a PIN from a different conversation id re-asks; the activation yes from another conversation re-asks.
- Dialog, through the real converse endpoint: a parent starts "set up Lily's voice", PIN, the hand-off line, scripted short answers with the "Nice." interjections, "Is that Lily talking?" after pool 1, "Almost done!" at the fifth pool, follow-up questions once the list is spent, "If that was Lily, say your PIN", the PIN, and the activation question when recognition is off.
- Device, the proof the thresholds are allowed to stay: one real child in the kitchen, start to finish in one conversation; then the child, each parent and a sibling each say "Hey Argyle, who am I?" twice. The child must be named every time and nobody else may be named as the child. One wrong name parks the arc at "raise the pool to six seconds" before any threshold moves.

## Delivery and split

Bounded: the pooling helper, the hard-then-anchored consistency rule, per-answer held-out scoring and the exhaustion counter in `services/voice_fingerprint.py` (Codex, against tests Claude writes); the child dialog branch, the question list with follow-ups, the "Is that Lily talking?" turn, the consent-line fallback, the closing PIN and the conversation-bound activation yes in `services/voice_setup.py` (Claude); a Config word ("short answers") and the capabilities entry (Claude).

## Revision after the Codex adversarial review (2026-10-13)

Five findings, all verified against `voice_fingerprint.py` and `voice_setup.py` before changing the spec:

1. **Pooled held-out checks pass more easily than live recognition** (high). Accepted. Check steps now score each short answer alone; the device step gains negatives. The thresholds stay, with the proof moved to where it belongs.
2. **Drop-and-continue lets a sibling seed the pool** (high). Accepted. Pool 1 is hard, the parent names its voice, later answers bind to it as an anchor.
3. **A PIN turn with no fingerprint starts a child enrollment with no exclusion and no "Was that Lily?"** (high, true of today's code: `voice_setup` passes `exclude=vector` with `vector` None, and `answer()` only enters the confirm phase when `exclude` is set). Accepted; fixed for every enrollment.
4. **The final yes is any voice, any conversation** (high, true today). Accepted in full: the closing confirmation for someone else's enrollment is the consenting parent's PIN again, verified and voice-matched to the consent fingerprint, in the question's conversation. First drafted as a conversation-bound transcript yes with an opportunistic voice check; the user chose the second PIN ("second PIN is fine", 2026-10-13).
5. **Fifteen questions cannot fill five pools at the one-second floor** (medium, arithmetic). Accepted. Follow-ups cycle the topics, completion is by seconds and pools, forty turns is the ceiling, the count-down promises nothing it cannot keep.
