# Voice fingerprint — keep the verified speaker, then recognize a familiar voice

**Date:** 2026-10-12. **Status:** continuity and automatic recognition implemented in v2.499.406 and corrected in v2.499.407, off until enrollment and household checks. The user clarified that recognition is the useful independent outcome, so implementation proceeds alongside device checks. Real satellite correlation, host performance and household accuracy acceptance remain pending; F0/F1/F2 device acceptance is not claimed.
**Builds on:** [Voice identity](2026-10-12-voice-identity-design.md). **Related:** [Payment gate](2026-10-12-payment-gate-design.md). A fingerprint never independently authorizes money. Per the user's payment policy, a fresh enrolled-parent match plus explicit transaction-bound approval is sufficient when Always require PIN for purchases is off; when on, even a recognized parent must supply a fresh PIN.

## Outcome and sequence

### Implementation decision, 2026-10-12

The bridge wraps `PipelineRun.async_execute` on **HA 2026.10.x**, with the installed
household version checked through its API. It sets an explicit `ContextVar`
with controller run ID, HA context ID, device, satellite and utterance nonce,
calls the original controller, then resets/cancels in `finally`. STT reads
that explicit context; conversation checks the same HA context/device/satellite.
This is not correlation by task identity, time or text. Unsupported versions
or replacement of the installed wrapper disable recognition. Version and signature checks precede installation; missing imports are optional feature failures. Unload uses its saved owner even after delegate removal. HA 2026.10.0 and .1 controller source was checked; live acceptance on .1 is not claimed. Bridge failures are exposed in satellite Config status.

Component **1.4.1** tees audio unchanged to an existing STT entity; the household
Argyle pipeline currently uses `stt.home_assistant_cloud`. Local upload starts
when the audio iterator ends, overlapping the delegate's final transcription.
Chauffeur immediately returns an opaque reference to a bounded single-worker
job. HA waits at most one second for the upload reference, then the server
waits at most 400ms for ordinary inference. Explicit setup phrases may wait
three seconds. References bind installation, satellite, device, run, utterance,
service-token revision and the active server-owned enrollment ID. They are
one-use with 60s expiry; a late result cannot attach to another turn.

The selected candidate is English WeSpeaker VoxCeleb ResNet34 through
**sherpa-onnx 1.13.8**, which supplies native features and CPU ONNX inference
without PyTorch. Python 3.11 aarch64 wheels were checked. The
[model asset](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)
is **26,534,365 bytes**, SHA-256
`5ef208a9da1453335308a6b6f4e6dfbd7e183a38b604de0a57664f45d257fe94`.
The [author's model card](https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet34)
and [runtime license](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/LICENSE)
identify Apache-2.0. Model preparation explicitly downloads/verifies the pinned
asset. Native inference releases the GIL; HA has no model/runtime dependency.

The initial decode slice accepts HA's raw mono 16-bit PCM at 16/24/48 kHz.
Duration, energy and clipping reject
unusable observations. These are heuristics, not reliable diarization or proof
of speech-only audio. Provisional cosine thresholds: naming 0.70 with 0.12
margin, enrollment consistency 0.65 and different-speaker distance below 0.40.
These are provisional, not household-calibrated claims. Extraction accepts
0.3s of voiced speech; naming or a speaker-change decision still needs 1.2s.
Ordinary turns run one model pass; only explicit enrollment runs two additional
half-sample checks when the sample lasts at least five seconds.

Parent-owned personal-device enrollment requires consent, three varied phrases
and two held-out checks. A new similar template invalidates affected checks.
The internal `calibrated` flag means those two pilot checks passed; the full
household matrix below still precedes parent activation. Templates live outside
the general database in a protected file; status/member JSON omit vectors.
Recognition only provides named identity; no payment-grade `recognized_parent`
proof is implemented. That optional purchase path remains a separate gate.

Local tests cover concurrent equal transcripts, exact context, one-use/stale/
late references, cancellation/local-only runs, unchanged audio/transcripts,
automatic naming, PIN anchors, speaker-change downgrade and deletion. A served
phone check exercises all five enrollment phrases, activation, automatic
naming and deletion with fixture inference. Synthetic workstation medians:
125ms for two seconds, 716ms for seven seconds, 1496ms for fourteen seconds
(long samples in that build included half-sample checks). These are historical, not host or accuracy
results. `tools/voice_probe.py` supports the pending host probe. Real microphone
correlation, host memory/latency, room/noise/impostor checks and one-word approval
quality remain acceptance work. Naming/continuity need no payment target.

The original gates below remain device acceptance requirements. Implementation
in parallel does not mark them passed or enable recognition by default.

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

Revised wait ceiling: one second for the HA upload reference plus 400ms ordinary inference (three seconds for enrollment). Measure actual p95 added latency; target at most 750 MB additional resident memory, and no event-loop blocking. These are budgets to measure, not claims about the model. If no result is ready within the wait budget, the identity service gets `unavailable`; a late result cannot retroactively authorize an already handled utterance.

Require usable voiced speech, not merely a long audio packet. Calibrate quality thresholds against the selected model; include the user's one-word “approved” as a first-class test, not only long commands. A recognized short approval must not acquire an extra PIN/phrase prompt when the purchase setting is off. If a short sample cannot support a confident match, use the PIN fallback and record that limitation rather than guessing identity; do not claim the one-word experience is device-verified until it passes. Clipped audio, overlap, low quality, silence, unsupported encoding and timeout return `inconclusive`. Mixed speakers are not reliably solved by one embedding, so uncertain/mixed samples preserve bounded PIN-based room identity but supply no fresh payment recognition proof.

F0/F2 must evaluate the short-approval case separately; success on five-second enrollment samples does not pass it. A longer optional phrase may improve evidence but is not a new mandatory purchase step. Evaluate continuity across the current readback exchange too: the request and approval each retain their exact-run observation, must support the same enrolled parent, and must fall within that readback's lifetime with no intervening identity change. Never concatenate different speakers into one embedding or let a strong earlier request substitute for unusable speaker evidence on the approval itself. Until this passes on a satellite, no-new-PIN voice payment is unavailable there and the spoken-PIN path remains usable.

## Phase 1 — continuity of a PIN session

When PIN verification succeeds, bind the exact PIN utterance's usable embedding as the session anchor. If it is unavailable, establish the normal ten-minute verified room session, clear the request-rate counter and explicitly say voice matching is unavailable. The audit records the actual verified state. Clear any prior anchor. Do not anchor on the next arbitrary speaker. The anchor stays in RAM and expires with the identity session.

For every later Chauffeur utterance while fingerprint continuity is enabled:

| Result against the anchor | Identity result before processing the text |
|---|---|
| Same speaker above the calibrated acceptance threshold | Retain verified level until the original expiry; never extend the ten minutes. |
| Confident different speaker | Clear verification, anchor, pending readback and person-specific history/focus; treat the current utterance as unknown unless it explicitly names someone. |
| Inconclusive, missing, late, short or uncorrelated observation | Keep identity, generation, anchor and readback until their original expiry. No greeting replay, sliding extension or fresh payment recognition proof. |

After a downgrade, an enrolled identity can at most supply a named lens; it cannot rescue the old verified session. A fresh PIN is needed for the new speaker. Identity evaluation precedes intent parsing so a new speaker's “approve booking” cannot consume the prior speaker's readback.

No rolling anchor updates in this slice: background adaptation could gradually replace the verified speaker. Replay/voice cloning remains a limitation even with a good match; do not label the result “authenticated by voice.”

## Phase 2 — opt-in recognition and greeting

In the personal phone settings, a member or authorized parent starts enrollment for a specific active member and satellite, receives a short-lived enrollment ID, then follows three varied spoken prompts of at least five seconds each. Match each captured sample by its exact run key; neighboring speech cannot enroll someone. Collect explicit consent and provide a delete button. Child enrollment requires a parent's approval. No enrollment from ambient recordings, mission audio or a successful PIN alone.

Store only normalized reference vectors, model revision, quality summary, consent actor and timestamps in protected local storage. Exclude embeddings from normal member JSON, HA state, model context, exports intended for general diagnostics and logs. Raw audio is deleted as soon as features are computed. Member deletion, enrollment deletion and model incompatibility revoke the templates and associated session anchors. Document backup retention: deletion cannot erase offline backups already made.

Recognition requires a score above a separately calibrated named-identity threshold and a clear margin over the second candidate. Close candidates leave a new session unknown and preserve an existing lens. A confident match sets level `named`, never `verified`; an explicit spoken name still does not prove identity. Greet once when a named session begins, not on every response. “That's not me” clears the named session without changing enrollment automatically.

For payment with Always require PIN for purchases off, expose a distinct server-owned `recognized_parent` proof for this exact utterance: observation ID, matched member, model revision and threshold decision. Use an approval threshold at least as strict as naming, calibrated separately in F2; recheck that the member is currently a parent. The payment controller consumes that proof with the pending readback and explicit approval. It does not turn the entire session into verified, does not enable release/submit approval without their PIN, and cannot be reused on a later utterance. If this payment-grade match is unavailable, the payment controller requests a PIN. With the setting on, the proof never bypasses the PIN prompt.

## Evaluation, failure and rollout

F0 first tests two simultaneous satellites speaking the same sentence, repeated utterances, a local-only HA intent, cancellation, delayed embedding, reconnect and restart. A stale observation must never attach to another request. Check forwarded audio hashes and transcripts against the unwrapped delegate.

Calibrate continuity and naming separately using consented samples from every household participant, each target room, near/far speech, noise and short confirmation phrases. Hold out recordings from calibration. Proposed pilot gate: no wrong-speaker retention or wrong-name assignment in the held-out household matrix, at least 95% acceptance of adequately long same-speaker samples in supported conditions, and the latency/memory budgets above. Record sample counts and errors; zero observed errors is not a guarantee of zero false accepts. If this gate fails, leave recognition disabled and keep the phone/PIN route usable rather than relaxing a threshold to improve a demo.

Builds: F0 correlation/model feasibility; F1 continuity plus opt-in switch on one satellite; F2 enrollment and names. The setting is per enrolled satellite, off until its calibration/device check passes. Missing models or worker failure preserve normal transcription and the current bounded identity. Model upgrades make incompatible templates inert without deleting them and require evaluation before re-enabling; never compare vectors from different revisions.

Measure inconclusive turns, forced re-verifications and successful completion in real kitchen noise, not just false matches. Keep continuity off by default on each satellite until the parent enables it after calibration; it may reasonably stay off. Turning it off revokes current anchors/readbacks and returns subsequent PIN sessions to the identity spec's explicitly weaker room-based behavior. It also disables recognized-parent payment proof on that satellite; do not silently relax matching when the room gets noisy.

Expose payment-recognition readiness per satellite only after F2, enrollment and payment-grade calibration pass and the feature is enabled. Payment Settings may advertise approval by a recognized parent's voice only for those ready satellites; hide that clause while fingerprint is parked or unavailable. Until then, turning Always require PIN for purchases off changes the signed-in device path only; voice still needs a fresh spoken PIN. Loss of readiness removes the capability claim without changing the household's purchase setting.

Acceptance: Jeff verifies; Jeff's next adequate utterance retains his session; another adult speaks and loses Jeff's authority before dispatch; Jeff returns and must verify again. Identical concurrent sentences stay on their own satellites. An unusable approval sample cannot exercise the no-new-PIN purchase path. An enrolled member gets “Morning, Jeff” and a shared schedule but cannot approve a release without a PIN. With purchase PIN enforcement off, a confident match on “approved” completes that payment's identity check without a PIN prompt; with enforcement on, the same match still requires a fresh PIN. Deleting enrollment removes automatic naming and recognized-parent payment proofs. HA built-in commands keep working with the wrapper installed.

## Non-goals

No passive room monitoring, background recording, emotion/age inference, biometric certainty claims, automatic payment from recognition, automatic biometric enrollment or model training on household audio. The fingerprint can corroborate a PIN-backed turn and, under the user's optional no-new-PIN purchase policy, identify a parent explicitly approving the current payment. It never overrides Always require PIN for purchases when that setting is on.

## Review corrections and app follow-up, 2026-10-12

The user explicitly chose missing-evidence continuity: only usable, confident contradiction ends an established identity. This is best-effort speaker continuity, not proof of who spoke an inconclusive approval. The future no-new-PIN purchase path still requires fresh payment-grade evidence. Session/readback expiry and role/PIN/token/device revocation remain enforced.

Disabled/archived members are excluded from matching but their stored templates remain intact. Enrollment or deletion of another member preserves those rows. Explicit voice/member deletion removes them. Enrollment tolerates bounded transcript slips while retaining exact observation/enrollment correlation and audio/held-out checks. Speech during active enrollment gets deterministic setup guidance or cancellation and never falls through to the chat model. A missing STT delegate presents an unavailable engine with safe empty capability lists.

Phone chat is specified independently in [App voice](2026-10-12-app-voice-design.md). Guided phone enrollment and portable profiles are deferred until the [cross-microphone experiment](../experiments/2026-10-13-phone-voice-feasibility.md) demonstrates a useful result. A failed experiment favors spoken satellite enrollment.
