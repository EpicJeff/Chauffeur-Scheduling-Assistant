# App voice — talk to Argyle and set up your voice on your phone

**Date:** 2026-10-12. **Status:** draft design; app microphone and guided enrollment are not implemented by this document.
**Builds on:** [Voice identity](2026-10-12-voice-identity-design.md) and [Voice fingerprint](2026-10-12-voice-fingerprint-design.md). Independent of the payment target and payment implementation.

## Outcome

A family member opens Chauffeur, taps the microphone, and talks to Argyle. Argyle answers aloud and on screen, and listens for a requested follow-up. The same microphone experience powers a short, guided **Set up my voice** flow. After setup, enabled household speakers can recognize that member without a name introduction.

Setting up a voice must require no HA configuration, speaker selection, walking between devices, status refresh, or per-person recognition toggle. A parent still owns the one-time household setup of HA speech providers and enabled speakers. Existing satellite setup continues to work while the phone flow is built.

The phone behaves like a voice endpoint while the app is open. Its personal app session already identifies the member; enrollment is not a prerequisite for app voice control. This slice starts with the actions available in the member's existing Argyle chat: calendar and driving requests, lists, family messages, reminders and mission research, subject to current role and tool permissions. It does not add a broader HA home-control capability to app chat. Full HA local-intent parity can follow with its own action authorization; it must not be obtained by impersonating an HA satellite or forwarding every phone command under an HA service account.

## Everyday conversation

The Argyle conversation composer gains a microphone button, with an accessible label and a visible listening state. The first tap asks for microphone permission. Subsequent taps start listening immediately when permission remains granted. Existing text entry remains available alongside voice.

The user sees **Listening**, **Thinking**, and **Speaking** states, a recording indicator, and a persistent Stop button. End speech after a short silence, with a **Done** button as a reliable alternative. A turn is limited to 15 seconds; reaching the limit submits that bounded turn and shows that recording ended. There is no continuous ambient recording or background wake word in this PWA slice.

Show the recognized text and Argyle's response in the same conversation. Read the speech-safe response aloud. If Argyle asks a question, resume listening automatically after playback ends. An unprompted follow-up requires another tap; an active follow-up ends after ten seconds without speech. The microphone never collects samples while Argyle is speaking. Stop interrupts recording/playback and cancels an undispatched turn; a change already accepted by a tool is reported as completed rather than pretending it was undone.

On navigation away, hidden app, device lock, lost microphone track, logout or audio interruption, close the capture and playback resources. Returning shows **Tap to resume**, with no automatic upload of a partial recording. A late permission grant after cancellation immediately closes its new tracks. Permission denial, no microphone and unavailable speech services each have a short recovery message and retain text chat.

Microphone capture requires a secure browser context and user permission. The intended household entry is its HTTPS phone URL; plain LAN HTTP must show an actionable secure-connection message. HA ingress in an iframe also needs microphone permission delegated by the parent document. Supported entry points are the standalone PWA and its normal top-level browser URL; ingress is accepted only after a real-device permission check. [Browser microphone requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

## Guided enrollment

Entry: **My profile → Voice → Set up my voice**. Show what recognition does, that it is optional, and that only a local voice template is saved. State that speech transcription uses the household's existing provider, which may be Home Assistant Cloud. Provide **Start** and **Cancel**, not a configuration checklist.

1. Resolve the member from their personal authenticated session. An adult can enroll their own voice. A child needs a parent's recorded authorization before Start; the parent can grant it on their phone or enter their PIN on the child's device. That authorization is short-lived, names only this child and enrollment, and does not sign the child in as the parent. Reject household/wall sessions, service tokens and anonymous admin ingress as enrollment credentials.
2. Prepare the pinned local model automatically if the parent has enabled household voice recognition. Show download/progress once if necessary; retries reuse the verified artifact. Ordinary phone conversations do not need this model.
3. Ask for microphone permission and show the first short phrase. Read instructions aloud, then stop playback before opening capture. The phrase remains visible with **1 of 5** and a listening indicator. Do not speak the full phrase while recording it.
4. Accept three training phrases followed by two different check phrases. Each has at least four seconds of usable voiced audio. On success, show a small acknowledgment and advance immediately. Keep the microphone session permission across steps, while gating actual capture around playback. No refresh or config visit between phrases.
5. A quiet, clipped, inconsistent or unusable sample asks for that same phrase again with a concrete reason. Small STT wording errors are tolerated by the deterministic prompt matcher; arbitrary questions are not enrollment samples and receive setup guidance rather than reaching the chat model. The transcript is not identity proof. Check samples must have their own new recording IDs and cannot reuse training recordings.
6. After all checks pass, atomically save the template and show **Your voice is ready** with **Try talking to Argyle** and **Done**. Make it eligible for naming on household speakers whose cross-microphone acceptance has passed. If household speaker acceptance is pending, say **Saved. Ready on this phone; household speaker checks are pending**. Do not falsely promise room recognition from phone-only accuracy checks.

Target: a successful five-phrase run in about a minute, with automatic advancement. Measure actual device timing; it is a usability acceptance target, not a current performance claim. After three consecutive unusable attempts at one step, offer retry or cancel with a brief microphone/noise check. Never lower recognition thresholds to finish setup.

Cancel, ten-minute enrollment expiry or logout discards incomplete samples. An interrupted run can resume only while its same authenticated enrollment remains live; a retry records the current step anew. Restarting creates a fresh enrollment. Re-enrolling leaves the prior usable profile intact until the new profile passes; failure never deletes it. Profile settings show **Set up again**, **Turn recognition off for me**, and **Delete my voice**. Disabling is reversible; deletion is explicit.

Parents authorize a child's enrollment, but that child remains the actor for all subsequent app requests. A parent enrolling another adult on a shared phone must first switch into that adult's personal session; choosing a name from a dropdown is not proof of that person's consent or identity.

## Authentication and speech policy

Reuse the app's personal-token resolution and `acting_member` semantics. A server-owned phone voice session binds member, token revision, conversation, device nonce and expiry. The nonce separates sessions; it grants no identity. Recheck the actor's active status, role and token at every dispatch. Client-supplied member, source, role, speaker result or conversation ID cannot change authorization. Enforce conversation ownership before reading or writing history.

Phone voice uses the same actor and action permissions as that person's typed Argyle chat. Extract the shared chat dispatch into a small reusable service rather than having one HTTP handler manufacture a request to another. Do not feed phone audio into the service-token satellite converse endpoint, fabricate HA registry metadata, or fall back to a nominated parent when actor resolution fails.

Keep the display response and speech response separate. Tool/source privacy metadata must determine the safe speech projection before model composition; the model cannot choose to expose sensitive content aloud. Shared household answers can be spoken. Private or sensitive results receive a generic audible acknowledgment and their authorized detail on screen. PIN digits, credentials, payment data and private mission details remain withheld aloud. The user's own transcript is shown only in their authorized conversation, with credential turns replaced by a sanitized authentication result.

Existing release and submit readbacks retain their binding to the actor, mission facts and expiry. First app-voice delivery renders the existing approval controls for these actions; it does not introduce a second spoken approval parser. Everyday mutations reuse existing chat permissions and confirmations. Payment is not implemented by this slice. Its subsequent controller must honor the user's policy: one parent's explicit approval; **Always require PIN for purchases** on demands a fresh entered or spoken PIN, while off may accept the signed-in parent app session. A remembered voice lens is never a fresh payment fingerprint proof.

PIN or enrollment controls are intercepted deterministically before conversation history, title generation, SSE publication or agent dispatch. A spoken PIN goes through the configured STT provider, as existing satellite PINs do; it never goes to the chat model or application logs. Entering a PIN on screen remains available. Any parent authorization consumes only the credential turn, not an instruction appended to it.

## Audio and speech services

Use one foreground browser capture module for chat and enrollment. Capture through `getUserMedia` and an `AudioWorklet`, mix to mono, and produce bounded signed 16-bit little-endian PCM with its **actual** sample rate. Do not assume the browser honored a requested rate. Resample 44.1/48 kHz input to canonical 16 kHz with an explicit anti-aliasing resampler shared by both flows. Upload raw PCM and explicit metadata; do not relabel WebM/Opus as WAV. If the required capture path is unsupported, explain that voice is unavailable on this browser and keep text usable. [AudioWorklet documentation](https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet).

The server discovers the household Argyle pipeline using `ha_api`'s existing pipeline selection. Use its selected STT provider and language. If it selects Chauffeur's wrapper, resolve its configured non-wrapper delegate for phone transcription; the server computes phone embeddings itself. Do not depend on a synthetic HA `PipelineRun` or recursively invoke the wrapper. The household's current delegate is `stt.home_assistant_cloud`; another supported provider must be discoverable, not hardcoded into the client.

Add a bounded binary STT method to `ha_api`. HA's authenticated `/api/stt/{provider}` accepts an audio stream with its speech metadata and returns a transcript/result. Check provider-supported metadata before sending; enforce a timeout and propagate a sanitized failure. HA credentials remain server-side. The existing JSON-only service-call helper is not an audio transport. This API contract is checked in [HA 2026.10 STT source](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/stt/__init__.py).

Replies use the same configured Argyle TTS engine, language and voice as satellites. The server calls HA's authenticated `/api/tts_get_url` with the selected `engine_id`, language, voice option, safe message and `cache=false`. Fetch only the returned `/api/tts_proxy/` path on the configured HA origin; ignore any returned external origin. Serve the audio through an authenticated, short-lived Chauffeur reference. The browser plays it after the user's microphone gesture. Never announce a phone reply on a room speaker or return HA credentials/upstream media URLs to the browser. Test the selected cloud voice and a supported local Piper voice. If synthesis or playback fails, show the answer and a **Play reply** retry; chat remains usable. This contract is checked in [HA 2026.10 TTS source](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/tts/__init__.py).

For enrollment, compute local embeddings in the existing bounded CPU worker from the same canonical recording used for transcription. Enrollment may run the split-sample consistency checks; ordinary chat runs one pass and does not wait on a fingerprint to establish the authenticated phone actor. Keep raw audio, per-step vectors and transcripts in memory only. Exclude audio endpoints from service-worker caches, request-body logging, error telemetry and general database exports.

## Endpoint and turn contract

Proposed routes are under `/api/app-voice`, separate from the HA service routes. Require a personal member session in the auth capability map **and** handler; denial still holds when general auth is in audit mode. Apply the app's same-origin/CSRF rules and per-member request/byte limits.

| Operation | Server contract |
|---|---|
| Start session | Return opaque session ID, expiry, server-selected mode and audio limits; chat conversation belongs to actor. Enrollment authorization is verified before choosing enrollment mode. |
| Submit turn | Session ID, server-issued turn nonce, audio format/rate and bounded PCM. Bind nonce to actor, session, expected sequence and mode; authenticate before consuming bytes. |
| Receive result | Sanitized transcript/result, display response, speech response/audio reference, explicit follow-up state or enrollment progress/retry. Never return vectors, PINs or a member credential. |
| Cancel / end | Mark the turn/session inactive; discard undecoded/undispatched work and transient enrollment samples. Completion reports distinguish a dispatched action from cancellation. |

Server issues each next turn nonce. Accept one recording per nonce and retain an idempotent, sanitized result for retries during the session. Reusing a nonce with a different audio hash is rejected. Duplicate and concurrent deliveries run STT/agent/tool work at most once. Out-of-order turns do not advance enrollment or enter history. Multiple phones have distinct sessions; neither can supply evidence to the other.

Close a cancelled session before late STT, fingerprint or TTS results can publish. Immediately before agent/tool dispatch, check cancellation and credential revision again. A race after tool dispatch cannot roll back an external action; return its real status on the next refresh. Enrollment results additionally bind enrollment ID, step, template/model revision and audio nonce. Automatic capture must never enroll Argyle's own playback.

Session inactivity expiry is ten minutes; it does not extend existing PIN/readback authority. Only one active capture turn per session. Bound concurrent speech jobs globally and reject excess work with retry guidance. No queue of long stale voice requests. Status polling/SSE carries only sanitized result/progress and requires the owning member session.

## A voice profile that follows the person

The current templates are keyed to `(HA installation, satellite)`. Keeping that model would force phone setup to be repeated for every speaker. Introduce a member-owned profile with model revision, training centroid, consent record, capture provenance, checks and a separately stored recognition preference. Phone identity comes from login; this template is for naming on speakers, not phone authentication.

Keep eligibility separate from enrollment: phone-held-out checks establish the profile, while household acceptance establishes whether phone profiles reliably name people on each speaker/microphone class. A parent runs the acceptance check once during household rollout, not a config exercise for every enrollee. As long as a target speaker's acceptance has passed and recognition is enabled there, a new compatible, checked profile becomes eligible automatically. A rival profile with insufficient margin invalidates eligibility rather than silently choosing a name. The app explains the failed distinction and offers setup again.

Save versioned profiles in a separate protected `profiles-v2.json`; do not make old code parse a new layout in `templates.json`. Read legacy compatible templates as existing satellite-specific references so Jeff's current enrollment keeps working. Preserve their provenance and satellite checks; do not promote them to global phone-tested profiles without checks. Re-enrollment can add a portable profile without removing working legacy references until replacement is accepted. Never average vectors from different model revisions.

Make migration idempotent and atomic, retaining the original file for rollback. Readers select the current schema and ignore unsupported revisions without deleting them. Disable/archival excludes a member from matching but preserves their saved templates. Explicit deletion removes that member from both stores and cancels their pending enrollments, sessions and anchors. Member deletion follows the same path. A rollback must not resurrect explicitly deleted templates from a migration copy; any retained migration backup requires the same deletion or a durable deletion marker respected by the old reader. Document that offline add-on backups remain outside live deletion.

Prove this deletion/rollback behavior before switching the reader. If the existing version cannot honor a deletion marker, update the legacy file itself and keep no live backup copy that a rollback could restore. The separate v2 file is the fallback copy for schema rollout, not a source for restoring deleted voices.

## Existing recognition policy carried forward

Missing, delayed, short or uncertain evidence preserves a current named or PIN-verified satellite session and its readback, with the original non-sliding expiry. A usable, confident different-speaker result clears the old authority before dispatch. A correct PIN without a usable embedding creates the normal bounded room session, clears the request-rate counter and reports that voice matching is unavailable; it never anchors on the next arbitrary speaker.

This is best-effort speaker continuity. It deliberately does not prove who spoke an inconclusive approval. Release/submit retain their PIN-backed room semantics, while a future no-new-PIN purchase path still needs fresh, payment-grade evidence. HA bridge health and model/quality diagnostics must be visible without breaking ordinary STT or conversations.

## Delivery and acceptance

Deliver in this order: repair current recognition regressions; build foreground phone conversation capture/STT/actor dispatch/TTS; add guided enrollment using that exact capture path; migrate portable profiles and prove cross-microphone recognition. No payment target is required. Phone conversation is useful and deliverable before portable recognition passes household checks.

Acceptance requires:

- Real iPhone Safari **and installed PWA**, plus Android Chrome/PWA: microphone permission, actual 44.1/48 kHz capture, audible reply, five automatically advancing phrases, and immediate ordinary voice use. Fixture embeddings alone cannot pass this.
- Existing authenticated roles retain chat permissions; child, wall, anonymous ingress, forged member/source and expired/revoked token cannot borrow parent authority or another conversation/enrollment. Parent child-consent grant expires and cannot authorize other actions.
- Permission denied/ignored, hidden app, phone call/interruption, logout, cancellation and suspended audio context release resources. Echo/playback never becomes training speech. STT/model/TTS outage has visible recovery and keeps text chat usable.
- Duplicate/out-of-order submissions, concurrent phones, late STT/inference after cancel and conflicting audio under one nonce cause no duplicate tool execution or accepted enrollment sample.
- PIN tests demonstrate no credential in model input, history, title, SSE, logs or spoken reply. Private data stays authorized on screen and withheld in speech according to source policy.
- Three training and two held-out samples, STT slips, short/quiet/clipped audio, inconsistent speaker, rival margin and failed re-enrollment all have correct progress and preserve the old working profile.
- Jeff's legacy template survives upgrade; disable/reactivate preserves it; explicit delete/member delete and schema rollback cannot restore it. Incompatible model revisions remain inert.
- Phone enrollment tested against held-out near/far utterances on actual household speakers, with all enrolled members and an unenrolled speaker. Record wrong names, false speaker changes, inconclusive turns, sample count and latency. Leave a failing microphone class ineligible and report it honestly.
- Current PIN room session keeps its original expiry/readback on a short or missing observation, but a confident different speaker loses authority before an approval dispatch.

After this acceptance, optional fully spoken satellite enrollment can reuse the same server-owned enrollment steps: establish a member and PIN/consent, speak each prompt, continue listening automatically, then announce completion. It must preserve exact HA run correlation and require no config refresh. It is a follow-up to the phone slice, not a reason to delay the app microphone.
