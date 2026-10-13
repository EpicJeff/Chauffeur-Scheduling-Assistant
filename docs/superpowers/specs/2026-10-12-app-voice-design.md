# App voice — talk to Argyle from your phone

**Created:** 2026-10-12. **Revised:** 2026-10-13.
**Status:** chat-only draft; capture choice awaits the real-iPhone spike. Phone voice is not implemented.
**Related:** [Voice identity](2026-10-12-voice-identity-design.md), [Voice fingerprint](2026-10-12-voice-fingerprint-design.md), [feasibility experiments](../experiments/2026-10-13-phone-voice-feasibility.md).

## Outcome and boundary

A signed-in member opens the installed Chauffeur PWA, taps the microphone, and talks to Argyle. The transcript appears when recognition finishes, the answer when the agent finishes, and speech when audio is ready. A requested follow-up can continue by voice.

Login supplies identity. No fingerprint, enrollment, model download, satellite configuration or payment target is required. Guided enrollment, portable profiles, migration and household recognition acceptance are removed. Write an enrollment spec only after the cross-microphone experiment gives a useful result. If it fails, guided spoken enrollment on the actual satellite becomes the main enrollment path.

V1 spoken capabilities reuse the satellite speech-safe set: shared calendar reads, driver assignment/removal, shared-list reads/additions/check-off, family/direct messages and mission research requests. Retain the authenticated member as actor and obey their existing permissions. Release, submit and purchases use on-screen controls. Private mail/situations and broader app actions remain in typed chat. No HA home intents, background listening or wake word.

## Supported surface

Required voice support: **installed PWA on the current iPhone generation and previous two**, across Apple-supported stable iOS releases compatible with those devices. Record exact hardware/iOS combinations from Apple at implementation time. Distinguish intended coverage from measured combinations; one phone or an emulated viewport cannot pass the matrix.

Browser-tab voice is incidental compatibility, with no separate fallback or acceptance work. The same applies to Android for this initial slice. Typed chat remains available. Use the secure app URL; plain LAN HTTP explains that voice needs HTTPS. **HA ingress is out of scope:** the household iframe does not delegate microphone permission. [Microphone requirements](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).

## Conversation experience

Add an accessible microphone button to the personal composer. First tap requests permission; later taps begin a turn. Show **Listening**, **Thinking**, **Speaking**, a capture indicator and Stop. End after roughly one second of trailing silence; **Done** is an alternative. Limit recordings to 15 seconds and show why recording ended at that limit.

Publish final transcript before agent/TTS work. Interim browser recognition stays provisional and never dispatches an action. Sanitize credentials before display/history. Render the answer before fetching/playing audio; TTS failure retains the answer with **Play reply**.

For an explicit follow-up, resume listening after playback while visible; stop after ten seconds without speech. Otherwise require another tap. If iOS requires a gesture, show **Tap to reply**. Pause capture during playback and avoid a backlog of old answers.

Stop closes capture/playback and cancels undispatched work. A new turn supersedes the old undispatched turn. A dispatched action remains completed; report its real status. Navigation, backgrounding, lock, microphone interruption, logout or lost track releases resources and discards partial recordings. Return to **Tap to resume**. Close tracks from permission granted after cancellation. Denial/ignored permission, missing microphone and speech/network failures have visible recovery; text remains usable.

## Capture choice: spike before committing

Chat needs no embedding. Remove the AudioWorklet, browser mono-mixing and browser resampler commitments from this slice. Compare two small input paths on a real installed PWA:

| Candidate | Path | Benefit | Question to prove |
|---|---|---|---|
| A: browser recognition | `SpeechRecognition` / `webkitSpeechRecognition`; send final text | Smallest input path; no Chauffeur audio upload/decoder | PWA reliability, repeated follow-ups, interruptions and household transcription |
| B: household STT | `getUserMedia` + `MediaRecorder`; upload real format, server decode, HA STT delegate | Consistent household transcription and configurable provider | Actual iPhone recording formats and added upload/decode/STT latency |

Both use the same authenticated dispatch and HA TTS voice. One house voice does not require HA transcription. Prefer A if its required PWA/reliability/transcript gates and latency pass. Choose B if A fails a required combination or materially mishears household requests and B passes. Ship one tested path, not runtime orchestration of both. Record choice/device/OS/results here before production implementation. First spike the available household phone, then validate the remaining supported matrix.

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

After three seconds without a transcript, show recognition progress. After eight seconds without audio, retain text/progress and offer recovery as appropriate. After 15 seconds without recognition, end with a recoverable error and never dispatch late text. Long mission work acknowledges initiation and continues in the mission UI. Report cold starts/outages separately.

## Identity, permissions and speech safety

Use personal-token resolution and `acting_member`. Recheck active status, role, token and conversation ownership before dispatch. Anonymous/admin ingress, household/wall sessions and service tokens cannot use phone voice, including in auth audit mode. Client member/role/source and spoken names grant no authority.

Extract shared chat dispatch only as needed and add an explicit server-selected phone speech policy. Do not manufacture an HA installation/device/satellite or borrow its PIN session. `VoiceContext.member()` requires a real paired satellite and is not a phone-login container. Retain the actual member principal, with no parent-of-record fallback.

**Verified code constraint:** the general agent rail has no universal per-tool speech privacy result. Existing safeguards are `voice_tools.TOOLS`, `speech_safe`, spoken calendar/list projections and mission privacy checks. Reuse these projections and a narrow offered-tool/dispatch allowlist, intersected with the member's existing permissions. Exclude `prepare_voice_approval`; show app approval controls. Refuse unoffered tools at dispatch even if the model requests them.

Voice context/history contains speech-safe phone turns and shared projections only. Earlier private typed messages remain visible to their owner but do not enter audible composition. Exclude mail, private situation focus and private mission details. Private requests get generic guidance to continue in typed chat. V1 does not promise a rich private on-screen answer plus a separately classified AI speech summary.

Keep display and speech fields distinct, even when identical for shared answers. Deterministic policy limits data/tools before composition; a model instruction alone is insufficient. Intercept credential-shaped PIN turns before display/history, title, SSE, logs or model dispatch and consume the whole turn. Credentials/payment data/private mission details stay withheld. Existing entered-PIN controls remain; no new purchase/enrollment PIN flow.

The payment spec still governs one-parent approval and **Always require PIN for purchases**: on requires a fresh PIN; off may accept the signed-in parent device. This slice changes no payment authority.

## Minimal turn ownership

One in-flight turn per personal conversation/session. A new turn supersedes the old before dispatch. Immediately before tool dispatch, atomically check that the turn is current and the actor authorized. Check currency before late publication/playback too. Cancellation after dispatch is not rollback.

Use a client request ID for the utterance and record acceptance with its existing conversation turn. Reject repeat delivery of that ID without rerunning the agent/tool. This small guard prevents replay of a completed action; cancellation handles overlapping work. No server-issued sequence nonces, audio hashes, retained result cache or custom global speech scheduler in v1. Disable automatic action-POST retries after ambiguous failure; show conversation/action status before a manual new request.

Reuse authenticated chat transport with a server-selected voice mode. Add binary STT/audio routes only as needed by the chosen paths, with personal-member capability-map and handler checks. Keep ordinary HTTP byte/time limits; add no generic session protocol or durable voice store.

## Speech service reuse

Reuse `ha_api._pick_argyle_pipeline` and `get_pipeline_tts`. The lesson player supplies browser capture/cleanup and `speechSynthesis` patterns; its analyser is not STT. Reuse suitable lifecycle patterns without treating them as completed voice chat.

If B wins, obtain pipeline STT engine/language. Resolve Chauffeur's wrapper to its configured non-wrapper delegate; phone transcription has no HA run to correlate. Add bounded binary `ha_api` transport for authenticated `/api/stt/{provider}` and supported metadata. HA credentials stay server-side. [HA STT source](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/stt/__init__.py).

Both candidates use authenticated HA `/api/tts_get_url` with selected `engine_id`, language, voice option, safe message and `cache=false`. Fetch only a returned `/api/tts_proxy/` path against the configured HA origin; serve bounded audio through an authenticated Chauffeur response. Play a Blob/object URL without a long-lived reference store. Return no HA credentials/upstream URL and never announce phone replies on room speakers. **Play reply** supplies a gesture if blocked. [HA TTS source](https://github.com/home-assistant/core/blob/2026.10.0/homeassistant/components/tts/__init__.py).

Audio stays transient and excluded from service-worker caches, body logs, telemetry and database exports. Describe the chosen recognition provider/cloud recipient honestly.

## Acceptance and sequencing

Record the real installed-PWA comparison, choose capture and validate latency. Implement chat independently of cross-microphone results. Validate the required iPhone/iOS matrix before claiming full support; browser-tab/Android voice adds no mandatory work.

- Speak a shared request, see transcript/text progressively, hear Argyle's configured voice, and answer a follow-up.
- Measure warm transcript/text/first-audio targets and cold/outage behavior. Fixtures/emulated viewports do not pass the device gate.
- Permission/interruption/background/logout/repeated-turn recovery releases resources; playback never transcribes itself.
- Existing child/helper/adult/parent permissions hold. Forged actor/source, wall/revoked token and another member's conversation are refused.
- Private history/rows never enter audible composition; model-requested private tools are refused. Credentials stay absent from model input, speech, history, title, SSE and logs.
- Cancel/new turn before dispatch prevents the old action; dispatched completion remains visible. Duplicate completed request delivery never repeats it.
- STT/TTS failure keeps text usable and cannot publish cancelled recognition. Typed chat and satellite behavior remain unchanged.

Recognition fixes shipped separately as **b971cf3b, v2.499.407 / HA 1.4.1**. Missing evidence preserves the bounded satellite session; confident contradiction clears it. This is independent of authenticated phone chat.
