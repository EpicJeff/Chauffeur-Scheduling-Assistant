# App voice — talk to Argyle from your phone

**Created:** 2026-10-12. **Revised:** 2026-10-13.
**Status:** initial chat-only build implemented in v2.499.408, authorized alongside the household spike on 2026-10-13. Real-device capture selection and latency acceptance remain pending. Record spike results before writing the subsequent rollout plan.
**Related:** [Voice identity](2026-10-12-voice-identity-design.md), [Voice fingerprint](2026-10-12-voice-fingerprint-design.md), [feasibility experiments](../experiments/2026-10-13-phone-voice-feasibility.md).

## Outcome and boundary

A signed-in member opens the installed Chauffeur PWA, taps the microphone, and talks to Argyle. The transcript appears when recognition finishes, the answer when the agent finishes, and speech when audio is ready. A requested follow-up can continue by voice.

Login supplies identity. No fingerprint, enrollment, model download, satellite configuration or payment target is required. Guided enrollment, portable profiles, migration and household recognition acceptance are removed. Write an enrollment spec only after the cross-microphone experiment gives a useful result. If it fails, guided spoken enrollment on the actual satellite becomes the main enrollment path.

The microphone accepts the same requests as the signed-in person's typed chat, including private requests. Retain the actual actor, tool permissions and on-screen result; only audible output differs. Shared requests can be spoken. Other results appear in full on screen with only “I put that on your screen” aloud. Release, submit and purchases retain existing controls/confirmations. No HA home intents, background listening or wake word.

## Supported surface

The intended compatibility target is installed PWA on the current iPhone generation and previous two, across compatible supported iOS releases. **The shipping gate is the household's actual phones.** Record exact hardware/iOS combinations tested; the matrix documents evidence and future coverage, not an exhaustive gate. Do not claim untested combinations passed.

Browser-tab voice is incidental compatibility, with no separate fallback or acceptance work. The same applies to Android for this initial slice. Typed chat remains available. Use the secure app URL; plain LAN HTTP explains that voice needs HTTPS. **HA ingress is out of scope:** the household iframe does not delegate microphone permission. [Microphone requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

## Conversation experience

Add an accessible microphone button to the personal composer. First tap requests permission; later taps begin a turn. Show **Listening**, **Thinking**, **Speaking**, a capture indicator and Stop. Candidate A uses the recognition engine's endpointing. **Candidate B ends on Done or the 15-second cap**; optional silence assistance is at most the lesson player's cheap analyser/RMS check, not a browser DSP/resampler framework. Bound both paths to 15 seconds and show why recording ended at that limit.

Publish final transcript before agent/TTS work. Interim browser recognition stays provisional and never dispatches an action. Sanitize credentials before display/history. Render the answer before fetching/playing audio; TTS failure retains the answer with **Play reply**.

For an explicit follow-up, resume listening after playback while visible if the tested platform permits it; stop after ten seconds without speech. **Tap to reply is the designed fallback** for gesture requirements or failed resume. Otherwise require another tap. Pause capture during playback and avoid a backlog of old answers.

Stop closes capture/playback and cancels undispatched work. A new turn supersedes the old undispatched turn. A dispatched action remains completed; report its real status. Navigation, backgrounding, lock, microphone interruption, logout or lost track releases resources and discards partial recordings. Return to **Tap to resume**. Close tracks from permission granted after cancellation. Denial/ignored permission, missing microphone and speech/network failures have visible recovery; text remains usable.

## Capture choice: spike before committing

Chat needs no embedding. Remove the AudioWorklet, browser mono-mixing and browser resampler commitments from this slice. Compare two small input paths on a real installed PWA:

| Candidate | Path | Benefit | Question to prove |
|---|---|---|---|
| A: browser recognition | `SpeechRecognition` / `webkitSpeechRecognition`; send final text | Smallest input path; no Chauffeur audio upload/decoder | PWA reliability, repeated follow-ups, interruptions and household transcription |
| B: household STT | `getUserMedia` + `MediaRecorder`; upload real format, server decode, HA STT delegate | Consistent household transcription and configurable provider | Actual iPhone recording formats and added upload/decode/STT latency |

Both use the same authenticated dispatch and HA TTS voice. One house voice does not require HA transcription. Prefer A if the household PWA/reliability/transcript gates and latency pass. Choose B if A fails a household phone or materially mishears requests and B passes. The user authorized building alongside these checks: the initial testable build may use B and a disposable A comparison entry, with no claim of settled real-device selection. Record choice/device/OS/results here before the rollout plan; retain one selected capture path afterward.

Browser recognition is not necessarily on-device: it may use a remote service, while local processing is a separate capability. Describe the chosen provider accurately. Historical iOS standalone issues are a hypothesis to test, not a measured household result. [SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition), [local processing](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition/processLocally).

For B, choose an actual supported MIME type with `MediaRecorder.isTypeSupported()`. The add-on already ships ffmpeg: use a bounded server decoder to produce HA-supported mono PCM/rate. Do not relabel encoded audio as WAV. Bound input to 15 seconds/5 MB, decoder output/time and request lifetime. Consider browser PCM only if the simpler recorder demonstrably fails; record the evidence. [Recorder format checks](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/isTypeSupported_static).

## Latency and progressive delivery

Measure warm ordinary shared-calendar/list requests on normal household connectivity from **the end of speech**:

| Milestone | Pilot p95 target |
|---|---|
| Final transcript visible | 2.5 seconds |
| Text answer visible | 6 seconds |
| First reply audio audible | 8 seconds |

Record endpoint detection, recognition/upload/decode, agent, TTS and playback separately, plus end-to-end timing. Stage percentiles do not prove end-to-end latency. Render each stage immediately. These are targets, not current results; settle capture and reconcile targets with real-device measurements.

Record the ten-sample spike counts, stage timings, observed failures and chosen capture in this spec **before the rollout plan is written**. The household-phone gate is finite; the wider matrix is a record of tested coverage.

Foreground phone turns use the existing interactive **lite-first** model path. Its current chain includes a slow Gemma fallback and 60/90-second call limits; those defaults cannot meet this slice. Phone voice disables the slow/heavy foreground fallback and uses a bounded lite request budget. Exhaustion reports an actionable retry/text fallback, not silent escalation to Gemma/flash/pro. Typed-chat defaults remain unchanged. Long work may launch through existing asynchronous mission/trip behavior; only its acknowledgment belongs to the foreground voice turn.

After three seconds without a transcript, show recognition progress. After eight seconds without audio, retain text/progress and offer recovery as appropriate. After 15 seconds without recognition, end with a recoverable error and never dispatch late text. Long mission work acknowledges initiation and continues in the mission UI. Report cold starts/outages separately.

## Identity, permissions and speech safety

Use personal-token resolution and `acting_member`. Recheck active status, role, token and conversation ownership before dispatch. Anonymous/admin ingress, household/wall sessions and service tokens cannot use phone voice, including in auth audit mode. Client member/role/source and spoken names grant no authority.

Extract shared chat dispatch only as needed and add an explicit server-selected phone speech policy. Do not manufacture an HA installation/device/satellite or borrow its PIN session. `VoiceContext.member()` requires a real paired satellite and is not a phone-login container. Retain the actual member principal, with no parent-of-record fallback.

Run the request once on the person's typed-chat rail with the same authorized actor/focus and offered tools. The existing personal typed DM worker does not inject message history; phone follow-ups add only server-confirmed shared voice turns, excluding private displayed answers and arbitrary typed history. Track the complete executed-tool set server-side. If any tool is outside `voice_tools.TOOLS` (excluding satellite `prepare_voice_approval`), mark the turn display-only: retain the authorized answer on screen and speak the fixed acknowledgment. Do not ask the person to retype or execute an action twice.

**Necessary guard on that rule:** tool names alone are not privacy labels. `get_calendar_events(spoken=False)` and member-scoped lists can return private rows despite being in the shared tool set. Full typed history/focus can also contain private detail, even when no tool runs. Audible eligibility therefore also requires the turn's context/history/results to be established shared-safe by the existing source projections; any missing/uncertain provenance makes the whole turn display-only. Reuse `speech_safe` and shared projections for those known sources, not a general per-tool classification framework. The full authorized typed answer stays on screen. A no-tool or failed-tool turn does not gain speech eligibility merely from an empty set.

Keep display and speech fields distinct, even when identical for shared answers. Deterministic policy limits data/tools before composition; a model instruction alone is insufficient. Intercept credential-shaped PIN turns before display/history, title, SSE, logs or model dispatch and consume the whole turn. Credentials/payment data/private mission details stay withheld. Existing entered-PIN controls remain; no new purchase/enrollment PIN flow.

The payment spec still governs one-parent approval and **Always require PIN for purchases**: on requires a fresh PIN; off may accept the signed-in parent device. This slice changes no payment authority.

## Minimal turn ownership

One in-flight turn per personal conversation/session. A new turn supersedes the old before dispatch. Immediately before tool dispatch, atomically check that the turn is current and the actor authorized. Check currency before late publication/playback too. Cancellation after dispatch is not rollback.

Use a client request ID for the utterance and record acceptance with its existing conversation turn. Reject repeat delivery of that ID without rerunning the agent/tool. This small guard prevents replay of a completed action; cancellation handles overlapping work. No server-issued sequence nonces, audio hashes, retained result cache or custom global speech scheduler in v1. Disable automatic action-POST retries after ambiguous failure; show conversation/action status before a manual new request.

Reuse authenticated chat transport with a server-selected voice mode. Add binary STT/audio routes only as needed by the chosen paths, with personal-member capability-map and handler checks. Keep ordinary HTTP byte/time limits; add no generic session protocol or durable voice store.

## Speech service reuse

Reuse `ha_api._pick_argyle_pipeline` and `get_pipeline_tts`. The lesson player supplies browser capture/cleanup and `speechSynthesis` patterns; its analyser is not STT. Reuse suitable lifecycle patterns without treating them as completed voice chat.

For B, obtain pipeline STT engine/language. The existing Chauffeur wrapper can be called directly through `/api/stt/{provider}`: without a `PipelineRun`, it simply forwards identical audio to its configured delegate and creates no fingerprint. This reuses the real configured delegate without fabricating a satellite or extra configuration discovery. Use bounded binary HA transport and supported metadata; credentials stay server-side. [HA STT source](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/stt/__init__.py).

Both candidates use authenticated HA `/api/tts_get_url` with selected `engine_id`, language, voice option, safe message and `cache=false`. Fetch only a returned `/api/tts_proxy/` path against the configured HA origin; serve bounded audio through an authenticated Chauffeur response. Play a Blob/object URL without a long-lived reference store. Return no HA credentials/upstream URL and never announce phone replies on room speakers. **Play reply** supplies a gesture if blocked. [HA TTS source](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/tts/__init__.py).

Audio stays transient and excluded from service-worker caches, body logs, telemetry and database exports. Describe the chosen recognition provider/cloud recipient honestly.

## Acceptance and sequencing

Build phone chat independently of cross-microphone results, then record the real installed-PWA comparison, selected capture and latency before rollout planning. Gate shipping on the household's phones; document the broader tested matrix. Browser-tab/Android voice adds no mandatory work.

- Speak a shared request, see transcript/text progressively, hear Argyle's configured voice, and answer a follow-up.
- Measure warm transcript/text/first-audio targets and cold/outage behavior. Fixtures/emulated viewports do not pass the device gate.
- Permission/interruption/background/logout/repeated-turn recovery releases resources; playback never transcribes itself.
- Existing child/helper/adult/parent permissions hold. Forged actor/source, wall/revoked token and another member's conversation are refused.
- A private spoken request runs with ordinary typed permissions and shows its full authorized answer; TTS receives only the fixed acknowledgment. Shared-eligible answers can be spoken. Private history/rows, no-tool answers and whitelisted tools returning private rows all exercise display-only guards. Credentials stay absent from model input, speech, history, title, SSE and logs.
- Foreground calls use the bounded interactive lite path; exhausted lite quota never silently routes a spoken turn into the slow/heavy tier.
- Cancel/new turn before dispatch prevents the old action; dispatched completion remains visible. Duplicate completed request delivery never repeats it.
- STT/TTS failure keeps text usable and cannot publish cancelled recognition. Typed chat and satellite behavior remain unchanged.

Recognition fixes shipped separately as **b971cf3b, v2.499.407 / HA 1.4.1**. Missing evidence preserves the bounded satellite session; confident contradiction clears it. This is independent of authenticated phone chat.

## Initial implementation, 2026-10-13

Implemented the HA recorder path in the personal Argyle DM, including a mic entry from the existing Argyle popup, Done/cap, progressive transcript/text, household TTS and Play/Tap-to-reply recovery. Follow-up capture uses the designed tap fallback until automatic resume is device-proven. No voice enrollment or kitchen diagnostic recorder was added.

The temporary browser comparison is reachable from Config → People → Voice identity → Phone voice comparison; it opens the same app with `voice_probe=browser`. This is a spike entry, not an automatic fallback or permanent capture setting. Runtime timings are available in `ChauffeurPhoneVoice.timings`, contain no transcripts, and label their anchor: recorder completion/Done, browser speech-end event, or result availability when speech-end is unobserved. True end-of-speech timing still requires the phone experiment.

Known-source checks are conservative: unclassified/private tool results and private focus use the display-only acknowledgment; typed/edited/private displayed history is excluded from voice follow-up context. Server-owned speech markers are separate from client message context. A private result does not make later independently shared queries permanently inaudible. The full typed answer/actions remain in the personal DM. Foreground lite calls have a six-second overall model budget, four seconds per attempt and no transient provider retries/slow model promotion; typed defaults stay unchanged.

Local proof: 18 backend/audio tests, served phone UI with fixture capture/providers/playback, existing satellite identity/fingerprint and actor/model/auth/build checks. Actual HA metadata confirms the selected wrapper accepts canonical phone PCM; a safe TTS-only probe returned 17,660 bytes of MP3 in 858ms without using room speakers. These are plumbing checks, not iPhone first-audio/latency acceptance. Household device counts/timings/capture choice remain pending before rollout planning.
