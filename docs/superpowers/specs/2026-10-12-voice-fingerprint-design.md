# Voice fingerprint — keep the verified speaker, then recognize a familiar voice

**Date:** 2026-10-12. **Status:** speculative design, parked behind F0; no production integration path has been demonstrated. F1/F2 are conditional, not committed delivery work.
**Builds on:** [Voice identity](2026-10-12-voice-identity-design.md). **Related:** [Payment gate](2026-10-12-payment-gate-design.md). A fingerprint never independently authorizes money. Per the user's payment policy, a fresh enrolled-parent match plus explicit transaction-bound approval is sufficient when Always require PIN for purchases is off; when on, even a recognized parent must supply a fresh PIN.

## Outcome and sequence

First, the voice that supplied the PIN can retain the ten-minute session, while a different speaker loses its authority before their command reaches tools. Second, a voluntarily enrolled household member can get their non-sensitive lens and greeting without saying their name. Both are hints under the identity service's policy; neither upgrades a voice to verified without a PIN.

Do not ship enrollment first and claim it protects verified sessions. Build continuity, test it on the household's actual satellites, then add recognition.

Neither device-chat payment nor PIN-based voice identity depends on F0 succeeding. Other specs may describe the optional recognized-parent experience, but no implementation plan may require it before the correlation proof passes. If F0 fails, leave fingerprint work parked; do not replace exact correlation with a heuristic to meet a delivery date.

## Existing seam and the feasibility requirement

Extend `homeassistant/custom_components/chauffeur_conversation` with an STT platform. `__init__.py` currently forwards only `Platform.CONVERSATION`; `config_flow.py` selects a server URL and service token. The wrapper selects one existing STT entity as its delegate and rejects itself or a wrapper cycle. It forwards the original audio stream, metadata and returned transcript unchanged. Recognition observes a separate in-memory copy.

The documented [STT method](https://developers.home-assistant.io/docs/core/entity/stt/) receives audio metadata and an asynchronous byte stream. It does not document a satellite or per-utterance identifier. The [STT metadata model](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/stt/models.py) contains audio format information. Therefore “write the latest fingerprint for this room” is not an implementation: concurrent speech, locally handled intents and delayed inference would misattribute it.

**Build F0 is an integration proof, with an explicit pass/fail result.** Pin the installed HA version and demonstrate a shared per-run key at the wrapper's audio entry and the conversation adapter's text entry. HA's [pipeline run controller](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/assist_pipeline/run.py) has run/device/satellite identity, while the [default pipeline](https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/components/assist_pipeline/default_pipeline.py) invokes STT separately from conversation. Isolate any version-specific bridge in `pipeline_bridge.py`; do not invent a `satellite_id` field on STT metadata or spread private HA access across the feature.

The proof must identify the exact supported callback/context path, or the narrow version-pinned compatibility hook needed to attach it, and capture that decision in this document before F1. No transcript suffixes, “closest timestamp,” text matching, global latest value or task-identity assumption are acceptable substitutes. If the installed HA cannot provide exact correlation without an invasive patch, F0 stops fingerprint activation and records the required HA change; ordinary STT and the PIN-only identity slice continue. This is the one unresolved integration choice, not a promise that a stable public hook already exists.

## Data flow

```text
satellite utterance -> HA run identity
                    -> Chauffeur STT wrapper -> original STT -> original text
                           |
                           +-> bounded audio copy -> local CPU embedding

same run identity -> conversation adapter -> one-use observation reference
                  -> voice_identity -> tools/readback or identity downgrade
```

An observation is keyed by `(installation_id, satellite_id, run_id, utterance_id)`. It is consumed once by that utterance; clock times are for expiry only. The conversation adapter passes the authenticated reference to Chauffeur. The model sees only the resulting level/name, never raw embeddings or thresholds. A locally handled HA command consumes/discards its observation when its run ends; it cannot become the next Chauffeur command's evidence.

Proposed transport: the HA component submits an authenticated observation to `/api/voice/observations`, then references the server-issued opaque ID in `/api/v2/converse`. Observation fields: identity key, model revision, quality result, embedding, captured time and local sequence. Chauffeur verifies satellite enrollment and one-use correlation; retry is idempotent. Use private in-memory component/server state with a 60-second TTL, not an HA entity attribute that Recorder persists. An optional diagnostic sensor exposes only available/unavailable and last processing latency, never a voice vector or transcript.

## Audio and compute contract

Tee chunks without changing order, bytes, language or delegate metadata. Bound the copied sample to 15 seconds and about 1 MB; exceeding the cap makes recognition unavailable while transcription continues. Do not make the downstream STT wait for CPU inference. Run one embedding worker with a bounded queue off the HA event loop; a full queue drops the fingerprint task rather than blocking speech. Cancellation or integration unload discards buffered audio and observations.

Initial F0 candidate: a [WeSpeaker ResNet34 ONNX model](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md) with ONNX Runtime CPU. Pin the artifact revision, checksum, license, runtime and feature extraction configuration, then benchmark the actual add-on host CPU. Measure download size, installed dependencies, peak resident memory and latency; no package-size claim is a readiness result. ONNX inference alone does not prove a torch-free pipeline: demonstrate audio decoding and filterbank preprocessing parity with the official implementation without importing a large training framework into the shipped add-on. Model suitability for this household and short speech is unproven; published dataset scores are not household acceptance evidence.

Prefer an isolated worker in the Chauffeur add-on for the model/runtime; the HA component only tees audio and correlates requests. This keeps a large ML dependency out of HA Core. Use authenticated local streaming to that worker, bounded in-memory buffers and no audio persistence. Document that the existing STT delegate may still be cloud-hosted; fingerprinting adds no cloud audio recipient. The wrapper advertises only formats accepted by its delegate; recognition decodes/resamples its own copy, never the forwarded stream.

Proposed readiness targets: at most 500 ms added p95 response latency waiting for an observation, at most 750 MB additional resident memory, and no event-loop blocking. These are budgets to measure, not claims about the model. If no result is ready within the wait budget, the identity service gets `unavailable`; a late result cannot retroactively authorize an already handled utterance.

Require usable voiced speech, not merely a long audio packet. Calibrate quality thresholds against the selected model; include the user's one-word “approved” as a first-class test, not only long commands. A recognized short approval must not acquire an extra PIN/phrase prompt when the purchase setting is off. If a short sample cannot support a confident match, use the PIN fallback and record that limitation rather than guessing identity; do not claim the one-word experience is device-verified until it passes. Clipped audio, overlap, low quality, silence, unsupported encoding and timeout return `inconclusive`. Mixed speakers are not reliably solved by one embedding, so uncertain/mixed samples cannot preserve approval authority.

F0/F2 must evaluate the short-approval case separately; success on five-second enrollment samples does not pass it. A longer optional phrase may improve evidence but is not a new mandatory purchase step. Evaluate continuity across the current readback exchange too: the request and approval each retain their exact-run observation, must support the same enrolled parent, and must fall within that readback's lifetime with no intervening identity change. Never concatenate different speakers into one embedding or let a strong earlier request substitute for unusable speaker evidence on the approval itself. Until this passes on a satellite, no-new-PIN voice payment is unavailable there and the spoken-PIN path remains usable.

## Phase 1 — continuity of a PIN session

When PIN verification succeeds, bind the exact PIN utterance's usable embedding as the session anchor. If it is unusable, the satellite gets the named lens but no continuity-backed verified authority; ask for a longer verification utterance including the PIN or offer the phone. Do not anchor on the next arbitrary speaker. The anchor stays in RAM and expires with the identity session.

For every later Chauffeur utterance while fingerprint continuity is enabled:

| Result against the anchor | Identity result before processing the text |
|---|---|
| Same speaker above the calibrated acceptance threshold | Retain verified level until the original expiry; never extend the ten minutes. |
| Confident different speaker | Clear verification, anchor, pending readback and person-specific history/focus; treat the current utterance as unknown unless it explicitly names someone. |
| Inconclusive, missing, late or uncorrelated observation | Suspend privileged execution for this turn and clear pending approval; require PIN verification again or phone approval. Never silently fall back to PIN-only approval while this mode is enabled. |

After a downgrade, an enrolled identity can at most supply a named lens; it cannot rescue the old verified session. A fresh PIN is needed for the new speaker. Identity evaluation precedes intent parsing so a new speaker's “approve booking” cannot consume the prior speaker's readback.

No rolling anchor updates in this slice: background adaptation could gradually replace the verified speaker. Replay/voice cloning remains a limitation even with a good match; do not label the result “authenticated by voice.”

## Phase 2 — opt-in recognition and greeting

In the personal phone settings, a member or authorized parent starts enrollment for a specific active member and satellite, receives a short-lived enrollment ID, then follows three varied spoken prompts of at least five seconds each. Match each captured sample by its exact run key; neighboring speech cannot enroll someone. Collect explicit consent and provide a delete button. Child enrollment requires a parent's approval. No enrollment from ambient recordings, mission audio or a successful PIN alone.

Store only normalized reference vectors, model revision, quality summary, consent actor and timestamps in protected local storage. Exclude embeddings from normal member JSON, HA state, model context, exports intended for general diagnostics and logs. Raw audio is deleted as soon as features are computed. Member deletion, enrollment deletion and model incompatibility revoke the templates and associated session anchors. Document backup retention: deletion cannot erase offline backups already made.

Recognition requires a score above a separately calibrated named-identity threshold and a clear margin over the second candidate. Close candidates produce unknown. A confident match sets level `named`, never `verified`; an explicit spoken name still does not prove identity. Greet once when a named session begins, not on every response. “That's not me” clears the named session without changing enrollment automatically.

For payment with Always require PIN for purchases off, expose a distinct server-owned `recognized_parent` proof for this exact utterance: observation ID, matched member, model revision and threshold decision. Use an approval threshold at least as strict as naming, calibrated separately in F2; recheck that the member is currently a parent. The payment controller consumes that proof with the pending readback and explicit approval. It does not turn the entire session into verified, does not enable release/submit approval without their PIN, and cannot be reused on a later utterance. If this payment-grade match is unavailable, the payment controller requests a PIN. With the setting on, the proof never bypasses the PIN prompt.

## Evaluation, failure and rollout

F0 first tests two simultaneous satellites speaking the same sentence, repeated utterances, a local-only HA intent, cancellation, delayed embedding, reconnect and restart. A stale observation must never attach to another request. Check forwarded audio hashes and transcripts against the unwrapped delegate.

Calibrate continuity and naming separately using consented samples from every household participant, each target room, near/far speech, noise and short confirmation phrases. Hold out recordings from calibration. Proposed pilot gate: no wrong-speaker retention or wrong-name assignment in the held-out household matrix, at least 95% acceptance of adequately long same-speaker samples in supported conditions, and the latency/memory budgets above. Record sample counts and errors; zero observed errors is not a guarantee of zero false accepts. If this gate fails, leave recognition disabled and keep the phone/PIN route usable rather than relaxing a threshold to improve a demo.

Builds: F0 correlation/model feasibility; F1 continuity plus opt-in switch on one satellite; F2 enrollment and names. The setting is per enrolled satellite, off until its calibration/device check passes. Missing models or worker failure preserve normal transcription and downgrade authority. Model upgrades invalidate incompatible templates and require evaluation before re-enabling; never compare vectors from different revisions.

Measure inconclusive turns, forced re-verifications and successful completion in real kitchen noise, not just false matches. Keep continuity off by default on each satellite until the parent enables it after calibration; it may reasonably stay off. Turning it off revokes current anchors/readbacks and returns subsequent PIN sessions to the identity spec's explicitly weaker room-based behavior. It also disables recognized-parent payment proof on that satellite; do not silently relax matching when the room gets noisy.

Expose payment-recognition readiness per satellite only after F2, enrollment and payment-grade calibration pass and the feature is enabled. Payment Settings may advertise approval by a recognized parent's voice only for those ready satellites; hide that clause while fingerprint is parked or unavailable. Until then, turning Always require PIN for purchases off changes the signed-in device path only; voice still needs a fresh spoken PIN. Loss of readiness removes the capability claim without changing the household's purchase setting.

Acceptance: Jeff verifies; Jeff's next adequate utterance retains his session; another adult speaks and loses Jeff's authority before dispatch; Jeff returns and must verify again. Identical concurrent sentences stay on their own satellites. An unusable approval sample cannot exercise the no-new-PIN purchase path. An enrolled member gets “Morning, Jeff” and a shared schedule but cannot approve a release without a PIN. With purchase PIN enforcement off, a confident match on “approved” completes that payment's identity check without a PIN prompt; with enforcement on, the same match still requires a fresh PIN. Deleting enrollment removes automatic naming and recognized-parent payment proofs. HA built-in commands keep working with the wrapper installed.

## Non-goals

No passive room monitoring, background recording, emotion/age inference, biometric certainty claims, automatic payment from recognition, automatic biometric enrollment or model training on household audio. The fingerprint can corroborate a PIN-backed turn and, under the user's optional no-new-PIN purchase policy, identify a parent explicitly approving the current payment. It never overrides Always require PIN for purchases when that setting is on.
