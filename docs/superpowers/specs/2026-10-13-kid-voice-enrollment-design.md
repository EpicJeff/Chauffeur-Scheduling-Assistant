# Kid voice enrollment — many short answers instead of a few long ones

**Date:** 2026-10-13. **Status:** draft design, agreed in conversation, not yet reviewed by Codex or planned. Nothing here is implemented.
**Builds on:** [Voice enrollment](2026-10-13-voice-enrollment-design.md) as revised the same evening (one setup works everywhere; one household switch). This spec changes nothing about consent, admission, thresholds or activation. It changes how a sample is assembled and how Argyle talks to a child.

## Outcome

A parent says "Hey Argyle, set up Lily's voice" in the kitchen, gives their PIN, and Lily answers a dozen quick questions about her favorite color, food, animal and friends while Argyle keeps the microphone open. The parent says "yes, that was Lily" and recognition keeps working. No sentence a six-year-old cannot say, no "a little longer, please".

## Why the model allows it

The speaker model is text-independent. What a sample needs is about four seconds of voiced speech, and the core needs five samples (three to train, two held-out checks). A child giving one- to two-second answers to twelve or fifteen questions produces the same amount of voice as an adult answering five questions for ten seconds each. The adult flow is the right shape for adults and the wrong shape for children, who cannot hold a ten-second monologue on request.

## The one mechanism change: pooled samples

- The five-sample core is untouched. A **pooled step** assembles one sample from several short answers: each answer is embedded on its own and admitted by the existing rule (one-use token, the question's conversation id, the run's own observation, speaker binding), and the dialog keeps asking until the step holds **four seconds of voiced speech**, then the step's sample is the normalized mean of those embeddings.
- Thresholds, the mutual-consistency check, the two held-out checks against the centroid and rivals, provenance and per-speaker check state are all exactly as today, applied to the pooled sample.
- The per-answer floor is **one second** of voiced speech (the embedder's own floor is 1.2 s of audio; a pooled answer under one second is kept out of the pool, not refused). Anything shorter gets a follow-up question, never "a little longer".
- Pooling is a property of the enrollment (`pooled: true`), chosen by the dialog, not by the person. The phone door does not pool: a child cannot read the prompts there, and the satellite is the door for children.

## The dialog, for a child

1. **Start.** "Set up Lily's voice" or "set up my voice" followed by "for Lily" as today. The consent step is unchanged: the parent's PIN through the enrollment-scoped verifier, no parent session, the parent's fingerprint kept as the exclusion anchor.
2. **Hand-off to the child.** Argyle: "Hi Lily. I'm going to ask you some questions. Just answer out loud. What's your favorite color?" The microphone stays open through `continue_conversation` as today.
3. **Questions.** A pool of short, concrete questions in a fixed order, enough for the whole setup without repeating:
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
   Between answers Argyle says one of "Nice.", "Cool.", "Good one." and asks the next. When a step fills, nothing is announced; the game just continues. Near the end: "Three more!" then "Last one!"
4. **A short answer** (under one second of voice): Argyle asks a follow-up on the same topic, "Why is that your favorite?" or "Tell me more about that", instead of a retry message. Three follow-ups in a row that stay under a second end the setup with a message to the parent, not the child: "I couldn't get enough of Lily's voice. Try again another time."
5. **Drift and siblings.** A child wanders mid-answer and siblings chime in. For a pooled enrollment the consistency rule is softened: an answer that does not match the pool so far is **dropped**, Argyle says "Let's try another one" and asks the next question; three dropped answers end the setup. The parent-exclusion rule stays hard: an answer continuous with the parent's fingerprint ends the setup, as today.
6. **Finish.** After the fifth pooled sample: "All done! Was that Lily? Say yes." to the parent, then the household activation question if recognition is not already on, both as today. The template is saved with `provenance: satellite` and `pooled: true` for diagnostics.
7. **Cancel.** "Cancel", "stop", "we're done" from anyone ends it, as today.

An adult can ask for the short questions too ("the short questions" or "the kid questions" at the start) for someone who finds the long answers hard; the mechanism does not care about age, only the dialog's choice of questions.

## What does not change

- Admission: every answer is still one run, one token, one observation, bound to its credential.
- Consent: parent PIN for a child, the parent's "yes" before saving, no parent session created.
- Thresholds and checks: `THRESHOLD, MARGIN, CONTINUITY` and the rival margin are untouched; pooled samples are checked like any other.
- Activation: one household switch, a parent's spoken "yes" or Config.
- Storage: `templates.json` gains only `pooled: true` on rows made this way; readers ignore it.
- The phone door and the adult satellite flow are unchanged.

## Risks and how they are met

- **Pooled embeddings of short answers are noisier than one long one.** The pool is assembled from one-second-plus answers up to four seconds of voice, which is the same total voice as an adult sample; the held-out checks are the proof per child, and a child whose checks fail stays off, as today. If the kitchen shows wrong names for children after this ships, raise the per-step pool to six seconds before touching thresholds.
- **A sibling answering for the child.** Dropped by the consistency rule, three strikes end it; and the parent's "yes" at the end is the last gate.
- **Boredom.** Fifteen questions is the ceiling; most children fill five pooled steps in nine to twelve answers. The count-down lines keep it a game.

## Testing

- Unit, offline, with fixture vectors: a pooled step fills at four voiced seconds across three one-and-a-half-second answers and produces the normalized mean; an answer under one second is kept out of the pool and asks a follow-up; three sub-second follow-ups end the setup; a non-matching answer is dropped with "let's try another one" and three drops end it; the parent-exclusion rule still ends it on the first parental answer; the held-out checks run against pooled samples with unchanged thresholds; the finished row carries `pooled: true`.
- Dialog, through the real converse endpoint: a parent starts "set up Lily's voice", PIN, the hand-off line, a dozen scripted short answers with the "Nice." interjections, "Three more!" and "Last one!" at the right places, "Was that Lily?", yes, and the activation question when recognition is off.
- Device: one real child in the kitchen, start to finish in one conversation, then "who am I?" names them; Config shows the template as pooled.

## Delivery and split

Bounded: the pooling helper and the softened consistency rule in `services/voice_fingerprint.py` (Codex, against tests Claude writes), the child dialog branch and the question list in `services/voice_setup.py` (Claude), a Config word ("short answers") and the capabilities entry (Claude). Under the standing coordination rule the spec goes to `/codex:adversarial-review` before the plan, with a focus on the pooled-sample thresholds and the softened consistency rule.
