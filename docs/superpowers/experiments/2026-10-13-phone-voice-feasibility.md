# Phone voice feasibility — evidence before capture or enrollment decisions

**Date:** 2026-10-13. **Status:** experiments prepared; real-iPhone and cross-microphone results pending. This is not an enrollment/profile-store spec.
**Related:** [App voice chat](../specs/2026-10-12-app-voice-design.md).

## Capture comparison

Required surface: installed PWA on the current iPhone generation and previous two, across compatible Apple-supported stable iOS releases. Record the exact matrix from Apple when testing. Start with the available household phone and state its model/OS; expand before claiming full support. Browser-tab voice is incidental and requires no extra fallback effort.

Compare `SpeechRecognition` with `getUserMedia`/`MediaRecorder → server decode → configured HA STT`. Both use the same requests, authenticated dispatch and HA TTS voice. Do not assume Web Speech runs locally or works because its constructor exists. Spike only capture/STT/playback and necessary temporary adapters; no profile store, enrollment UI or generic audio protocol.

Try ten ordinary shared requests per candidate, including family names and a two-turn follow-up. Repeat without reload; deny/regrant permission; interrupt with playback; background/return; stop before recognition finishes. Record failed starts, lost final transcripts, duplicate callbacks, name/action errors and resource recovery. A required combination with failed recovery disqualifies that capture path. Record actual recorder MIME/rate and test the existing ffmpeg decoder before requiring browser DSP.

Time speech-end to final transcript, text answer and first audible reply. Record individual stages, counts, median, p95 and worst delay. Ten samples give a pilot near-worst-case p95, not a stable percentile estimate. Targets: 2.5s transcript, 6s text, 8s first audio for warm ordinary queries. A canned reply isolates plumbing; real agent-inclusive turns are required for end-to-end claims. Never hold text for TTS.

Choose browser recognition if reliability, household transcription and latency pass; otherwise choose HA if it passes. If neither passes, retain text and record the actual blocker before considering a DSP/native rewrite. Enter measured device/OS, provider, counts, timings, failures and selected capture in the chat spec.

**Pending:** physical-device execution. An emulated iPhone viewport is not the experiment.

## Cross-microphone experiment

Question: can a phone-enrolled reference name Jeff on the kitchen satellite at current **0.70 score / 0.12 rival margin**? Login already names him on the phone.

Use the pinned model and Jeff's existing calibrated kitchen template. With consent, capture five different phone utterances of roughly 5–8 seconds and two fresh kitchen-satellite utterances at normal distance/noise. No PINs, payment text or other members' new recordings. Kitchen audio must come from that satellite's actual audio path in a temporary consented diagnostic run; a nearby phone is not a substitute.

Use `chauffeur/tools/voice_cross_mic_probe.py` against the private template file. It computes temporary evidence without saving profiles, vectors or decoded audio. Source recordings are explicit temporary experiment artifacts: delete them after comparison and retain scores/timings only. Normal recognition gains no ambient recording or audio persistence.

Run both directions:

1. Score the five phone samples against the existing kitchen reference and compatible calibrated rivals. This cheaply tests transfer of the existing profile to a phone.
2. Build a temporary phone centroid from the first three phone recordings. Check the remaining two phone recordings and two fresh kitchen recordings against it and the same rivals. This tests the intended phone-to-satellite direction. The old kitchen centroid is not a held-out kitchen recording.

Count all misses/inconclusive samples. Keep thresholds unchanged. With no rival, report that multi-member margin is unmeasured. The probe conservatively includes all compatible calibrated kitchen templates in its supplied file, including potentially inactive members; that is stricter than the live candidate set, not exact production calibration.

A passing Jeff/kitchen pilot justifies an enrollment spec, not automatic support for everyone/all rooms. Failure or inconsistency makes fully spoken satellite enrollment the main path; phone chat remains independent. Initial room exercises are parent-only using their own voice. Do not require every family member to record near/far samples in every room. Parent success cannot establish another person's accuracy; others stay off until their applicable evidence passes.

Run from `chauffeur/` with private paths; phone files 1–3 train, 4–5 are held out:

```powershell
..\venv\Scripts\python.exe tools/voice_cross_mic_probe.py `
  --model C:\private\wespeaker_en_voxceleb_resnet34.onnx `
  --templates C:\private\templates.json --member jeff `
  --installation HA_INSTANCE_ID --satellite assist_satellite.kitchen `
  --phone C:\private\phone1.m4a C:\private\phone2.m4a C:\private\phone3.m4a C:\private\phone4.m4a C:\private\phone5.m4a `
  --room C:\private\kitchen1.wav C:\private\kitchen2.wav
```

**Pending:** real consented phone/kitchen samples and Jeff's private template. Synthetic samples prove only tool mechanics/performance, never identity transfer. No experiment result is claimed here.

## Constraints for any later enrollment spec

Write it after the experiment. If phone enrollment proves useful, estimate roughly **two minutes** for five phrases/instructions/checks and measure on the add-on CPU. Child consent uses one mechanism: a parent's PIN entered on the child's device, scoped to enrollment without changing the child's actor.

Design no store migration now. If later necessary, explicit deletion removes all live voice data. Prefer one-time migration with the legacy file removed after the first successful boot. Rollback/backup restoration is manual and may require re-deletion. Do not promise that old readers honor new deletion markers or that deletion rewrites offline backups.
