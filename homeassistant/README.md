# Home Assistant Voice Integration ("Hey Argyle")

**Living integration guide. Reviewed with Chauffeur v2.499.4 on 2026-09-14.**
For product-wide setup and document status, see
[`../README.md`](../README.md) and [`../docs/README.md`](../docs/README.md).

This folder contains the HA-side glue that lets you talk to the Chauffeur agent
through Home Assistant Assist, while normal smart-home commands ("open the main
garage") keep working via HA's built-in intents.

## How it fits together

```
"Hey Argyle, have Celma drive Like to Warriors practice tomorrow"
        │
        ▼
Wake word (openWakeWord "hey_argyle" model)
        ▼
Speech-to-text (Whisper add-on or HA Cloud)
        ▼
Assist pipeline, with "Prefer handling commands locally" ON
        ├── matches a built-in intent (garage, lights…) → HA handles it
        └── no match → Chauffeur Conversation agent
                          │  POST /api/v2/converse  {text, language, conversation_id}
                          ▼
                  Chauffeur add-on agent (Argyle) → updates schedule → spoken reply
```

## 1. Install the custom component

Copy `custom_components/chauffeur_conversation/` into your HA config directory
(so it becomes `/config/custom_components/chauffeur_conversation/`), then
restart Home Assistant.

Add it via **Settings → Devices & Services → Add Integration → Chauffeur
Conversation**. The default URL `http://local-chauffeur:8000` is correct for a
locally built add-on; if you installed Chauffeur from an add-on repository, use
the hostname shown on the add-on's info page (looks like
`http://<repo-hash>-chauffeur:8000`). Enter it as a full URL with scheme and
port, not a bare hostname. The URL can be changed later via the integration's
**Configure** button. Do **not** map port 8000 to the host —
keep this service connection on the internal Docker network and give the
integration its Argyle service token from **Chauffeur → Config → People → Argyle**.
Local-network grace permits ordinary conversation during migration; it does
not verify a member or authorize a voice approval.

## Voice identity and approval

PIN identity was introduced in v2.499.402. Automatic recognition adds component
**1.4.1**. Copy the updated
custom component and restart HA. Keep voice approvals off until the submit-gate
and satellite device checks pass; local automated tests have not exercised the
household's microphone/STT pipeline.

On your personal device, sign into Config as a parent. Open **People → Voice
identity**. Configure the service token once under **HA → Settings → Devices &
services → Chauffeur Conversation → Configure**, using the token from
**Chauffeur → Config → People → Argyle**. Keep the existing token if it is already
configured; the token is not configured on individual speakers. Tick **Enable
voice identity** once. Since v2.499.729 every satellite that speaks to Argyle
joins by itself on its first turn (enabled, recognition set the way the
household switch is); untick a satellite's row to leave that one out. Before
that, each new satellite had to be ticked by hand, and until it was, "set up my
voice" on it fell through to the model, which said it could not (Office Voice PE,
2026-10-29). A recent HA supplies its satellite entity and device IDs directly.
Run **Sync Now** after updating Chauffeur so the schedule cache contains source
calendar privacy flags before you enable the voice feature.
On an older HA, use **Chauffeur integration → Configure → Device to satellite
mapping**, for example `{"device-registry-id": "assist_satellite.kitchen"}`.
The entity must exist and belong to that device; a conversation ID is never
used as a satellite identity. Record the actual HA version in device acceptance.
Supported HA versions continue listening while a PIN or approval reply is
pending. Older versions may require another wake word for the next turn.

- “It's Jeff” starts Jeff's non-sensitive lens. It grants no approvals.
- “Verify me,” then “My PIN is one two three four” verifies here for ten minutes.
  It uses the same member PIN as the phone; anyone who hears it may reuse it.
  Without recognition enabled, anyone in the room can use that session. With
  recognition enabled, the exact PIN utterance anchors the session and each
  subsequent utterance must match. If the PIN sample is too short, try “To verify
  my voice on this speaker, my PIN is one two three four”, using your real PIN.
  The PIN must be at the end of the phrase.
- Shared schedule/list questions, driver assignments, shopping adds/check-offs,
  internal messages and mission research use the household voice rail. An
  unverified internal message is explicitly relayed as Household voice.
- Once device checks pass, enable release/booking approvals separately. Request
  approval of a named pending mission; Argyle reads back its exact request,
  prompting for a PIN first if needed. Say **“approve release”** or **“approve
  booking”** on the next turn. A changed record or an expired readback asks again.
  A PIN turn never approves anything by itself.
- **Revoke session** and **Clear voice lock** are available on the phone. Three
  wrong PINs lock voice verification durably. Clearing that voice lock does not
  clear web PIN throttling or verify the satellite again.

Private content, external sends, uncertain-outcome verification and purchases
use their phone paths in this build. HA's built-in local intents retain their
existing routing; the integration still does not advertise `CONTROL`.

### Enroll a voice for automatic recognition

Recognition works independently of booking or purchase approval. An enrolled
voice can get its name and personal lens without saying a name or PIN. It
supplies a **named** lens, never the **verified** authority required for approvals.

1. Install component **1.4.1** and restart HA. Its exact-run bridge currently
   supports **HA 2026.10.x**, guarded by the controller signature. Other versions retain STT but have no recognition
   until their bridge is checked.
2. In the Chauffeur integration's **Configure** form, set **Existing STT entity**
   to your existing provider. The household's Argyle pipeline, checked
   2026-10-12, uses `stt.home_assistant_cloud`. Keep the current URL/token.
3. Under **HA → Settings → Voice assistants → Argyle**, change speech-to-text
   to **Chauffeur Voice recognition**. Your original provider still receives
   identical audio and transcribes it. Fingerprints are computed in Chauffeur
   locally; recognition adds no cloud recipient.
4. In **Chauffeur → Config → People → Voice identity**, enable the satellite,
   click **Prepare local voice model (27 MB)**, select the person, confirm their
   consent (parent authorization for a child), and click **Enroll voice on this satellite**.
5. Wake Argyle and read the displayed phrase clearly, with other people quiet.
   Refresh after each phrase. Three enrollment phrases are followed by two
   checks. Each sample belongs to its exact HA run and active enrollment.
   Say **“cancel voice setup”** to stop.
6. Check ordinary requests with each family member and an unenrolled speaker,
   near/far and in normal room noise. Then turn on **Recognize enrolled voices
   here and check for speaker changes**. Leave it off if it assigns a wrong name.
   Approval activation stays separate.

Argyle greets a newly recognized person once and resolves “my” in supported
shared-schedule requests to that person. **“That's not me”** clears the lens and
suppresses automatic naming for that session. A usable, confident different-speaker sample
clears the prior session/readback before processing. Missing, late, short or
inconclusive evidence keeps identity until its original expiry. A correct PIN
with unavailable evidence still establishes the ten-minute room session and says
voice matching is unavailable. No later speaker is silently used as its anchor.
Continuity is best effort, not proof of who spoke every approval. Disabled
members retain their templates for reactivation.
Recognition has no replay/voice-cloning protection and is not authentication.

Only templates persist in `/data/voice_private/templates.json`; audio and
per-turn vectors stay in memory. **Delete voice samples** removes automatic
naming and active speaker sessions. Templates are excluded from member JSON
and general database downloads; full add-on backups can retain them. The five
samples check consistency, not household-wide accuracy. Short, quiet, clipped
or mixed speech may remain unknown. The model is downloaded only when prepared.

Refresh voice status shows bridge/version incompatibility, missing-model/quality
errors and compute time. Missing evidence is not a fresh purchase match.
`python tools/voice_probe.py` runs a synthetic CPU/memory probe inside the add-on
after model preparation; it does not assess accuracy. Real satellite
correlation, host performance and family recognition acceptance remain device
checks. Model failure preserves transcription and withholds speaker authority.

## 2. Create the Argyle wake word

HA's stock wake words don't include "Hey Argyle". **How you add one depends
entirely on the satellite**, and the two engines are not interchangeable:

| | openWakeWord | microWakeWord |
|---|---|---|
| Runs on | the HA server (add-on) | the device itself |
| Satellite streams audio first | yes | no |
| Custom words | train a `.tflite`, drop it in `/share/openwakeword/` | model must be **compiled into the firmware** |
| Used by | ATOM Echo, ESP32-S3-BOX-3, `wyoming-satellite` on a Pi | **Voice Preview Edition**, S3-BOX-3, Companion app |

> **On a Voice PE there is no SETTING for this — only a firmware build.** The
> shipped config is on-device only, and that is not a UI restriction, it is the
> firmware: `home-assistant-voice.yaml` declares `micro_wake_word:` with the
> stock models and sets `voice_assistant: use_wake_word: false`, which is
> exactly the flag that would hand wake-word detection to Home Assistant. So the
> wake-word select lists only what is compiled in (Okay Nabu / Hey Jarvis /
> Hey Mycroft), and nothing in `/share/openwakeword/` can appear there.
> An earlier version of this file said to switch the device to "process wake
> words in Home Assistant"; no such control exists on stock firmware.
>
> Once you are building firmware anyway, **both** engines are open to you — see
> the two routes below. Neither is reachable without flashing.

### On a Voice Preview Edition — route A: microWakeWord (stays on-device)

1. Get a **microWakeWord** model for the phrase. Training one is a different
   pipeline from the openWakeWord notebook below; the community
   [Tater-Wake-Words](https://github.com/Tater-Wake-Words) collection is where
   most people start, and a ready-made model skips the training run entirely.
2. In **ESPHome Builder**, *take control* of the device (this is what makes the
   YAML yours to edit — and hands you its updates from then on: Nabu Casa's
   OTA releases stop applying, which is the real cost of either route).
3. Add your model to the `micro_wake_word:` `models:` list alongside the stock
   ones, then **Install** — OTA once adopted, no cable.
4. Reconfigure the integration so the new word shows in the wake-word select.

Keeps audio on the device, no constant streaming, lowest latency.

### On a Voice Preview Edition — route B: stream to openWakeWord

Flip the device to stream continuously and let the server decide, which is how
an ATOM Echo has always worked. Community forks do exactly this
([mike-nott/open-voice-pe](https://github.com/mike-nott/open-voice-pe) is one);
the substance is dropping `micro_wake_word:` and setting `use_wake_word: true`
so the pipeline's wake stage runs in HA. Any openWakeWord model then works with
no reflash — which is the real appeal if you expect to change the word.

Three things bite people here:

- **Nothing happens at all — the word never registers.** `use_wake_word: true`
  does not make a device stream; something has to *start* it. The stock Voice PE
  never needed that, because `micro_wake_word`'s own detection trigger started
  the pipeline. Take mww out and the microphone is simply never opened. Compare
  against the canonical server-side config,
  [`m5stack-atom-echo.yaml`](https://github.com/esphome/wake-word-voice-assistants/blob/main/m5stack-atom-echo/m5stack-atom-echo.yaml),
  which arms the stream from the API connection and **re-arms it after every
  pipeline run**:

  ```yaml
  api:
    on_client_connected:
      - delay: 2s                                  # let the API settle
      - lambda: id(va).set_use_wake_word(true);
      - voice_assistant.start_continuous:
    on_client_disconnected:
      - voice_assistant.stop:

  voice_assistant:
    id: va
    microphone:
      microphone: i2s_mics
      channels: 1
      gain_factor: 4        # NOT optional — see below
    on_end:
      - delay: 1s
      - voice_assistant.start_continuous:          # or it works exactly once
  ```

- **Streaming, but never detecting: you are sending the wrong microphone.** The
  Voice PE's `nabu_microphone` exposes the XMOS chip as TWO channels, and they
  are not equivalent:

  ```yaml
  channel_0:
    id: asr_mic
    amplify_shift: 0     # clean speech for STT, AFTER something already woke it
  channel_1:
    id: comm_mic
    amplify_shift: 2     # 4x louder — the channel wake detection runs on
  ```

  Stock points `micro_wake_word:` at `comm_mic` and `voice_assistant:` at
  `asr_mic`, which is right when the device wakes itself. Go server-side without
  touching it and the wake word is now being detected on `asr_mic` — the
  un-amplified channel — so openWakeWord is fed audio far too quiet to cross its
  threshold. Raise `amplify_shift` on `channel_0` (2 matches the wake channel),
  or point `voice_assistant:` at `comm_mic`.

- **It wakes, then does not wait for the command** — logs show `STT by VAD end`
  about a second after detection, so most attempts die before you finish
  speaking. Fix: on the device in Home Assistant, set **finished speaking
  detection** to **relaxed**. No reflash. If it is still intermittent, the
  stream is too quiet for voice-activity detection to latch onto — see the
  audio settings at the end of the overlay above.

  Know what that setting actually buys, because it is easy to expect too much
  of it. From `assist_pipeline/vad.py`, the three options are trailing-silence
  windows of **aggressive 0.25s / default 0.7s / relaxed 1.25s**, and they
  apply only AFTER speech has started — they govern "have they finished?", not
  "are they ever going to begin?". Silence before you start speaking does not
  end the run at all; the only cap there is the segmenter's absolute
  `timeout_seconds: 15.0`.
  
  So: relaxed buys you a longer pause *mid-sentence*. There is no setting that
  grants a long think before you start, and 15 seconds is the ceiling either
  way. For "I need a moment to remember what I wanted", the button is the
  right instrument — it starts a command with no wake word and no race.

Telling the first two apart takes one glance at the **openWakeWord add-on log**.
This, repeating, is cause 1:

```
Client connected: 280397385913641
Sent info to client: 280397385913641
Client disconnected: 280397385913641
```

Connect → `Sent info` → disconnect is the Wyoming `describe`/`info` handshake:
Home Assistant asking the service which models it has. **That is also what fills
the wake-word dropdown** — so the word being listed proves only that this
handshake works, which is exactly why openWakeWord looks like the suspect when
it is healthy. No audio is being sent. A satellite that is actually streaming
holds the connection open and logs detections; if it holds the connection and
never detects, that is cause 2.
- **It will not compile** (e.g. `no matching function for call to
  'AudioSinkTransferBuffer::transfer_data_to_sink()'`). The forks track a moving
  ESPHome audio API and lag its releases; you need a fork updated for your
  ESPHome version, or to pin ESPHome to the one it was built against.

Also weigh: this streams room audio to HA continuously, and adds a network
round trip before the device even knows it was addressed.

**And you cannot pause after the wake word.** This one is structural, it is not
a setting, and it is the strongest argument for route A:

When detection happens on the server, the wake word's own audio is in the same
stream the command is transcribed from — deliberately. `assist_pipeline`
forwards the audio pending at detection into speech-to-text with the comment
*"we need to make sure pending audio is forwarded to speech-to-text so the user
does not have to pause before speaking the voice command"*, which is right for
"Hey Argyle, turn on the lights" said in one breath.

The cost lands on the other way of talking. `VoiceCommandSegmenter` needs only
`speech_seconds: 0.3` to decide a command has STARTED, and the tail of the wake
word supplies it. Your thinking pause is then TRAILING silence, so it ends the
command after `silence_seconds` — 0.7s by default, 1.25s on relaxed. Two to
three seconds with latency, and no way to widen it.

The segmenter's generous `timeout_seconds: 15.0` only applies while
`in_command` is still false, which is what happens when speech-to-text opens on
SILENCE. That is the on-device case: microWakeWord detects locally and streams
only what comes after, so the fifteen seconds are real. Route A therefore lets
you say the wake word and then think; route B never will.

Either way, a bad flash is recoverable with the **Voice PE Imager**.

### Server-side wake word without a fork

Copying the whole `home-assistant-voice.yaml` and editing it is the obvious
move and it is a trap. The Voice PE's components were vendored when the
community forks were written and have since been **upstreamed into ESPHome
core**, so an old copy fails one component at a time — `aic3204` not found,
then `microphone.nabu_microphone` not found (now core `i2s_audio`: a single
`i2s_mics` id in place of `asr_mic`/`comm_mic`, with the gain moved off the
platform onto each consumer as `gain_factor`), then the media player id, then
the sound files. Each fix reveals the next, and the finish line is a hand-built
copy of upstream that will drift again.

Keep the upstream package and **overlay** the differences. Package merging
replaces scalars with the top-level value and concatenates lists, so the whole
change is a few lines in the device config. The complete, working version lives
in [`voice-pe-overlay.yaml`](voice-pe-overlay.yaml) — copy it into ESPHome
Builder and change the two names. Abridged:

```yaml
substitutions:
  name: kitchen-voice-assistant
packages:
  Nabu Casa.Home Assistant Voice PE: github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml@dev
esphome:
  name: ${name}
wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

# ── server-side wake word ────────────────────────────────────────────────
voice_assistant:
  # Scalar: replaces upstream's `false`, so the pipeline runs a wake stage.
  use_wake_word: true
  # List: CONCATENATED onto upstream's, which only starts micro_wake_word and
  # never opens a stream. These run after it.
  on_client_connected:
    - delay: 2s                                   # let the API settle
    - lambda: id(va).set_use_wake_word(true);     # the flag does not survive a stop
    - voice_assistant.start_continuous:

  # Put the LED ring back to idle when a reply finishes.
  #
  # Upstream does this at the end of `on_end` — but behind
  # `wait_until: not voice_assistant.is_running`, and in continuous mode that
  # never completes, because continuous mode IS the assistant never stopping.
  # So the phase is never reset and the ring spins forever. The device is still
  # listening the whole time (say the wake word again and it answers); only the
  # light is wrong, which is worse than it sounds on something whose entire job
  # is to tell a room what it is doing from across the kitchen.
  #
  # NOT on_tts_stream_end, however tempting: those triggers require a
  # `speaker:` on the component and the Voice PE drives a `media_player:`, so
  # they fail validation outright ("speaker is required when using
  # on_tts_stream_start and/or on_tts_stream_end").
  #
  # on_tts_end fires when the speech is READY, not when it has been heard, so
  # resetting there drops the ring to idle while the device is still talking.
  # Watch the media player instead: wait for the announcement to start, then
  # for it to finish. Both waits are bounded — an unbounded wait_until is the
  # exact bug being worked around here, and a reply that never plays must not
  # strand the ring a second time.
  on_tts_end:
    - wait_until:
        condition:
          media_player.is_announcing:
            id: external_media_player
        timeout: 3s
    - wait_until:
        condition:
          not:
            media_player.is_announcing:
              id: external_media_player
        timeout: 60s
    - lambda: id(voice_assistant_phase) = ${voice_assist_idle_phase_id};
    - script.execute: control_leds
  # Same for the failure path — upstream lights the error phase and relies on
  # that same unreachable code in on_end to clear it. The delay lets the error
  # actually be seen first.
  on_error:
    - delay: 2s
    - lambda: id(voice_assistant_phase) = ${voice_assist_idle_phase_id};
    - script.execute: control_leds

  # ── only if the command is not being heard after the wake word ──
  # Upstream zeroes all three because the XMOS chip does the conditioning and
  # the wake word was decided ON the device, where a quiet stream is fine.
  # Streaming to a server, Home Assistant's VAD has to find the start of speech
  # in this audio, and the canonical server-side config (m5stack-atom-echo)
  # feeds it a much hotter signal. Try the "relaxed" device setting FIRST — it
  # needs no reflash — and only reach for these if that is not enough.
  # noise_suppression_level: 2
  # auto_gain: 31dBFS
  # volume_multiplier: 2.0
```

**Two symptoms that mean "the stream is too quiet" rather than "speech-to-text
is bad at English":** having to enunciate unnaturally for a command to land,
and the SAME kind of phrase transcribing differently between runs — `column
one` on one attempt, `left 2` on the next. Whisper guessing differently on
comparable input is what a marginal signal looks like from outside, and
aliasing cannot fix it, because you cannot alias every spelling of every guess.
That is the point at which those three settings stop being optional.

If Validate rejects `${voice_assist_idle_phase_id}`, the package's substitutions
are not reaching the overlay — put the literal `1` in instead (upstream defines
idle as phase 1).

**Verify the merge rather than assuming it.** Hit **Validate**: it prints the
fully merged config, so you can read `use_wake_word: true` and see your three
actions appended to upstream's `on_client_connected`. If a list replaced
instead of concatenating, you will see that too, before flashing anything.

Upstream already hands `voice_assistant` both microphone channels, so start
without touching gain. If the wake word is heard but unreliably, add
`gain_factor: 4` to the channel-1 entry — which needs the full `microphone:`
list restated, since that list would otherwise concatenate.

### Installing a modified YAML

`chauffeur/home-assistant-voice.yaml` in this repo is a **copy for versioning**.
Editing it changes nothing until ESPHome can actually read that content.

An adopted Voice PE is not a pasted config — it is a small wrapper that pulls
the real one in as a **package**:

```yaml
substitutions:
  name: kitchen-voice-assistant
packages:
  Nabu Casa.Home Assistant Voice PE: "github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml"
esphome:
  name: ${name}
wifi:
  ssid: !secret wifi_ssid
```

That wrapper is doing real work — the device NAME and the wifi credentials live
there, and package merging is what lets them win over whatever the upstream
file says (dictionaries merge key-by-key; the top level takes precedence). So
customising means repointing the package, not replacing the wrapper.

**Point it at a LOCAL file.** A remote package is cached against a `refresh`
interval and pinned to a git ref, so edits you push can take a day to show up —
or never, if the ref or the repo visibility is wrong. When you are iterating on
the file, that indirection is the enemy:

1. Copy the YAML into the ESPHome add-on's config folder (`/config/esphome/` in
   the standard layout), beside `<device>.yaml`. The Builder's editor only
   edits device configs, so use the File Editor add-on or Samba to put it there.
2. In the device config, swap the package for a local include:

   ```yaml
   packages:
     voice_pe: !include home-assistant-voice.yaml
   ```
3. **Validate**, and search the merged output it prints for something only your
   copy has (`config_revision` below). If it is not there, ESPHome is still
   reading someone else's file and installing will change nothing.
4. **Install → Wirelessly**, to `INFO Successfully uploaded program`.

If you would rather keep the remote package, add `refresh: 0s` to it and use
**Clean Build Files** — but expect to keep fighting the cache.

Only if you abandon the wrapper and paste the factory file as the WHOLE config
do its omissions start to matter: it carries no `api: encryption:`, no `ota:`
password and no `wifi:` credentials, because those are the wrapper's job. Left
out, the device flashes and then cannot be reached.

**Prove the flash took.** A flash that silently did not apply looks exactly like
a change that did not work, and you will debug the wrong thing. The config logs
a revision at boot:

```yaml
substitutions:
  config_revision: '1'      # bump on every edit

esphome:
  on_boot:
    then:
      - logger.log:
          level: INFO
          format: "=== chauffeur voice config revision ${config_revision} ==="
```

Bump it, install, and look for that line in LOGS. If the number is stale, the
device is not running what you just wrote and nothing else you observe means
anything.

### The openWakeWord side (route B, and any streaming satellite)

This half is the same whether the satellite is a re-flashed Voice PE, an ATOM
Echo, an S3-BOX-3, or `wyoming-satellite` on a Pi. Training is free, ~1 hour,
and needs no recordings of your own voice.

1. Open the [openWakeWord training notebook](https://www.home-assistant.io/voice_control/create_wake_word/)
   from the HA docs and train on `hey argyle` — it synthesizes thousands of TTS
   samples. Download `hey_argyle.tflite`.
2. **Settings → Add-ons → openWakeWord → Install**, then **Start**.
3. Put the `.tflite` in `/share/openwakeword/` and **restart the add-on** — it
   enumerates models at startup, so a file added while it is running is invisible.
4. **Settings → Devices & services** → the openWakeWord Wyoming service should
   be discovered → **Configure → Submit**.
5. In your assistant (**Settings → Voice assistants**), open the **three-dot
   menu → Add streaming wake word**, pick **openwakeword**, then your word.

**Bisect before blaming the firmware.** Step 5's dropdown is served by the
add-on and has nothing to do with any device: if `hey argyle` is not listed
there, the problem is openWakeWord (steps 2–4 — usually the missing restart, or
the model in the wrong folder), and no amount of firmware work will help. If it
IS listed, openWakeWord is fine and the fault is on the device side.

### Or skip the wake word

The wake word is not part of Chauffeur — it only decides what wakes the
satellite up. **Any** wake word (or Voice PE's push-to-talk button) reaches
Argyle just as well, because the routing happens at the pipeline's conversation
agent in step 3. "Okay Nabu, have Celma drive Like to practice tomorrow" works
today, with nothing flashed.

## 3. Build the pipeline

**Settings → Voice assistants → Add assistant**:

- **Name:** Argyle
- **Speech-to-text:** Whisper add-on (or Home Assistant Cloud)
- **Conversation agent:** *Chauffeur*
- **Prefer handling commands locally:** **ON** ← this is what routes garage/
  light commands to HA's built-in intents and only sends unmatched sentences
  (i.e. scheduling requests) to Chauffeur.
- **Text-to-speech:** Piper add-on (or Cloud)

Assign this pipeline to your satellite(s).

## 4. Make sure home commands resolve

Built-in intents only see entities exposed to Assist: check **Settings → Voice
assistants → Expose** and expose the garage cover, giving it the alias
"main garage" if its entity name differs.

**Test the built-in agent on its own, not through the pipeline.** Developer
tools → Actions → `conversation.process`, with the BUILT-IN agent named
explicitly:

```yaml
action: conversation.process
data:
  agent_id: conversation.home_assistant
  text: "open the main garage"
```

If that does not work, "prefer handling commands locally" can never work
either, and the fault is exposure or naming rather than anything to do with
Chauffeur. This removes the whole pipeline from the question in one step.

**FIRST, CHECK WHICH CHAT YOU ARE IN.** Chauffeur's own chat surfaces -- the
control-center bar, the wall panel's Argyle bar, the PWA -- post straight to
`/api/chat`. Argyle can read and control Home Assistant devices there through
the `house` tool: it finds a device by name, alias or room, reads any device,
and controls devices exposed to Assist. Config › People › Argyle can allow
unexposed control too. Locks, alarms and garage doors always need a signed-in
parent/adult, admin chat, or a verified parent/adult voice. Each action reads
the device back before reporting its state.

Only **Assist** (the dialog, or a voice satellite running an Assist pipeline)
has the local-intent path in front of Argyle. If a command fails, compare
**Assist with the Chauffeur pipeline selected** and Chauffeur's own chat to
distinguish local intent matching from the house tool's discovery and permissions.

**IF IT WORKS TYPED AND FAILS SPOKEN, IT IS THE TRANSCRIPT, NOT THE ROUTING.**
Type the sentence into Assist with the Chauffeur pipeline selected. If it is
handled locally there, then prefer-local, the fall-through and the `CONTROL`
flag are all working, and the only remaining variable is what speech-to-text
actually wrote.

Local matching is literal. `front porch column 1` and `front porch column one`
are different strings, and speech-to-text will nearly always give you the
second — entity names are matched as text, with no number-word conversion.
Anything with a digit, an abbreviation, an ampersand or an unusual spelling
works perfectly when typed and never matches when spoken.

Read the transcript rather than guessing at it: **Settings → Voice assistants →
your pipeline → three-dot → Debug** shows the exact STT output per run. Then
fix it where the mismatch is — add an **alias** on the entity for how the
sentence is actually said (`front porch column one`). Aliases exist for this;
renaming the entity to suit the microphone is the worse trade.

This is never one entity. If you own `Column 1` you own `Column 2`, and a
`2nd Floor` and a `Tom & Jerry Lamp` somewhere else, each of which will fail
its first spoken command and no other. [`add_voice_aliases.py`](add_voice_aliases.py)
does the sweep — it reads the entity registry over the WebSocket API, works out
how each name would be SPOKEN (digits and ordinals to words, `&` to "and") and
adds that as an alias:

```powershell
$env:HA_TOKEN = "..."          # HA -> your profile -> Security -> long-lived token
# Use the repo's venv, which already has websockets. A bare `python` on PATH is
# often a different interpreter that does not.
.\venv\Scripts\python.exe homeassistant\add_voice_aliases.py `
    --url http://homeassistant.local:8123 --exposed-only
.\venv\Scripts\python.exe homeassistant\add_voice_aliases.py `
    --url http://homeassistant.local:8123 --exposed-only --apply
```

Dry run by default, prints every change first, and MERGES with existing aliases
rather than replacing them. It leaves numbers above 99 alone on purpose: "2024"
could be spoken four different ways and a wrong alias is worse than none, since
it silently matches a sentence you did not mean.

**ONE ENTITY FAILS WHILE ITS SIBLINGS WORK.** `Front Yard Left 1` obeys and
`Front Yard Left 2` does not, both exposed, both named the same way, nothing
different in either one's settings. Two causes fit that shape, and neither is
visible where you are looking:

- **The entity is `unavailable`.** An offline target cannot be matched, so the
  sentence resolves to nothing and falls through. This is runtime state, not
  configuration, which is why comparing settings finds nothing. Developer tools
  → States, filter for it, look at the state.
- **A DIFFERENT entity shares its name.** The ambiguity is a property of the
  pair, so the entity you are inspecting looks perfect. `add_voice_aliases.py`
  checks every name and alias against every other and reports collisions, so a
  dry run finds this for free.

**A DUPLICATE NAME LOOKS EXACTLY LIKE A BROKEN SETTING.** If the built-in agent
answers "there is more than one device with that name", prefer-local is working
perfectly and you will still watch every such command land on Argyle — which
then says, reasonably, that it cannot control appliances. `default_agent`
recognises the sentence, fails to resolve the entity, and treats that as NOT
HANDLED:

```python
if (response.response_type is ERROR
        and response.error_code not in (FAILED_TO_HANDLE, UNKNOWN)):
    # We ignore no matching errors
    return None
```

`None` means "fall through to the conversation agent". So an ambiguous name is
never reported as ambiguity — it is silently converted into a question for your
LLM, about a device it has never heard of.

**Music Assistant makes this the default state of the house**: it mirrors every
player as a second `media_player` entity, so a TV or speaker exposed twice is
ambiguous for every command aimed at it. Deduplicate in **Settings → Voice
assistants → Expose** — unexpose the copy you do not want voice to reach, or
give the two distinct aliases (`office TV` for the set, `office TV music` for
the Music Assistant one).

That is worth doing regardless, because two identically-named targets break
voice control with or without a custom agent.

**Know exactly how much gets swallowed, because it is less than it looks.**
There are only four error codes, and the fall-through splits them along a
defensible line:

| code | meaning | fall through? |
|---|---|---|
| `NO_INTENT_MATCH` | text matched no intent | **yes** — correct, let another agent try |
| `NO_VALID_TARGETS` | intent matched, no valid target | **yes** — correct for "no such device", WRONG for "which one?" |
| `FAILED_TO_HANDLE` | matched, tried, the call failed | no — reported to you |
| `UNKNOWN` | outside intent processing | no — reported to you |

So "I tried and the device did not respond" is NOT lost. A service call that
fails or times out raises `IntentHandleError` → `FAILED_TO_HANDLE`, which the
exclusion list deliberately passes straight through. The rule is
"could not understand or target you" falls through, "understood and it broke"
is reported — and that is the right rule.

**Exactly one thing sits on the wrong side of it.** `NO_VALID_TARGETS` covers
both "no such device" and "several devices with that name", which are opposite
situations: one means the local agent cannot help, the other means it knows
exactly what you asked and needs one word back. Home Assistant already knows
which it is — `MatchFailedReason.DUPLICATE_NAME` is a distinct reason at the
point of failure — and then flattens it into the shared code before
`async_handle_intents` can act on the difference.

That makes the upstream fix a narrow one: surface `DUPLICATE_NAME` rather than
collapsing it, so ambiguity is reported while genuine no-match keeps falling
through. By the time our entity is called the local response is gone and we are
not told it existed, so **component 1.5.0 asks the house again** rather than
guessing. In `ChauffeurConversationEntity.async_process`, before anything goes
to Chauffeur, the entity asks HA's default agent to recognise the sentence
(strict matching, the same mode the pipeline used). If an intent matches and
every name in it resolved to a real exposed entity, the sentence IS a house
command that the house could not target, and the entity hands it to the default
agent's own `async_process` and returns that answer unchanged. You hear "Sorry,
there are multiple devices called Office TV", which names the problem, instead
of Argyle explaining that it does not do appliances. Re-running the default
agent is safe: with prefer-local on it already failed on the same state a moment
earlier, so the rerun reproduces the same error and no action fires. With
prefer-local OFF, or a `conversation.process` call aimed straight at Argyle, the
house command now runs locally through the entity instead of being refused.

A sentence whose name HA has never heard of (`unmatched_entities` non-empty) is
NOT relayed: "open the schedule" matches the cover template with an unknown
name, and relaying it would turn an Argyle sentence into "I am not aware of any
device called schedule". Overlapping vocabulary stays with Argyle. A missing,
older or failing default agent falls through to Chauffeur exactly as before,
with a warning in the HA log (`Default agent relay failed`), because a silent
relay failure looks identical to the bug it exists to fix.
Component 1.5.1: media intents (`HassMediaSearchAndPlay`, pause, unpause,
next, previous, set volume) are never relayed, because the house cannot play
a song on a TV remote and Argyle's `music` tool can; "Sorry, no device
supports the required features" was the relay repeating that failure.
Component 1.5.2 (2026-10-30): the house's answer is kept only when it is not
an error. "Sorry, there are multiple devices called Office TV" came back
through the relay because four Assist-exposed entities carried that name (the
Remote face, the Music Assistant face, a stale unavailable player and the real
media player); on the day of 1.5.0 Argyle could not touch devices, so the
house's error was the better answer, but since the house tool Argyle resolves a
name to one device and acts, so an error response now falls through to it.
The three extras were also unexposed from Assist by hand that day (keep
`media_player.office_tv_2` exposed; the app launcher accepts any exposed face
on the TV's device). Copy the component and restart HA to take 1.5.2.
Component 1.6.0 (2026-10-30): Argyle can answer through a room speaker
instead of the satellite, per satellite. In Chauffeur's Config › Voice
identity, each satellite's row has "Argyle answers through": pick a media
player (default "This satellite"); from then on every spoken answer to that
satellite (the model's, voice identity's, a setup dialog's) is said on that
speaker through the same `tts.speak` announcements use (HA's announce flag: Sonos, Google Cast, Alexa Media Player and Music
Assistant players duck, speak and resume; Apple TV and the Samsung TV face do
not, so do not pin those), and Chauffeur hands the satellite blank speech (one
space, which a 1.5.x component passes through unchanged) with a `spoken_on`
field. The pipeline skips TTS on blank speech, so the Voice PE
stays quiet. The component keeps the blank instead of its "did not return a
response" line, and when the answer is a question it holds the turn for the
speaking time before returning, since the satellite would otherwise reopen its
mic while the room speaker is still talking, outside the satellite's echo
cancel. A satellite left on "This satellite", a chosen speaker that is
unavailable, a refused speaker call and typed requests all answer on the
satellite as before. The room ducking
automation (section 5) keeps the room ducked while the satellite shows
`processing`, and the announce overlays on top. Copy the component and
restart HA to take 1.6.0; the Config select needs the add-on at v2.499.738.
`chauffeur/tests/test_voice_local_relay.py` runs the real entity against a
stubbed default agent for each branch.

**A landmine to leave alone.** How much gets handled locally depends on a flag
our entity does not set. `assist_pipeline` narrows the local path to a
two-intent allowlist — `INTENT_GET_STATE` and `INTENT_MEDIA_SEARCH_AND_PLAY` —
but only when the conversation agent advertises
`ConversationEntityFeature.CONTROL`, on the assumption that such an agent
controls the house itself through its own LLM tools:

```python
intent_filter = None
if ... & conversation.ConversationEntityFeature.CONTROL:
    intent_filter = _async_local_fallback_intent_filter
```

`ChauffeurConversationEntity` deliberately declares no `supported_features`, so
`intent_filter` stays `None` and EVERY matched built-in intent is handled
locally — which is what makes the garage work. Adding `CONTROL` to look tidy
would silently restrict local handling to those two intents and route "open the
main garage" to Argyle's house tool and its trusted-parent check. The house
tool does not change this flag: built-in Assist handling stays first for every
matched house intent.

## 5. Duck the room while someone talks to a satellite

Installed in Home Assistant on 2026-10-29 as the automation **Voice: duck the
room while listening** (id `voice_duck_room_while_listening`, created through
the config API, so it lives in `automations.yaml` and shows in Settings >
Automations). A RECORD, NOT A SOURCE FILE: edit it in HA, then update this copy.

What it does: when any listed `assist_satellite` leaves `idle` (to `listening`,
`processing` or `responding`), every media player in the satellite's AREA that
is `playing` or `on` with a `volume_level` is set to 30% of its volume (floor
0.02). When the satellite is `idle` again (or after 120 s), each one goes back to
exactly the volume it had. Players on the satellite's own device are skipped:
the Voice PE firmware already ducks itself 20 dB (`nabu.set_ducking` in
upstream's `on_start` / `on_end`), and lowering its player would lower the reply.

Why no scene snapshot: `scene.create` + `scene.turn_on` was the first build and
it MUTED the kitchen Family Hub TV on restore, because reproducing a media
player's state sends `volume_mute`, and the Samsung TV integration's mute is a
KEY_MUTE toggle. The volumes now live in the automation run itself
(`variables.snapshot`, mode `single`), so nothing but `volume_set` is ever sent.

Known edges: a second utterance while the first run is still waiting is ignored
by mode `single` (the first run holds the true volumes and restores them when
the satellite idles). Nothing is persisted, so an HA restart mid-conversation
leaves the room ducked once; the next conversation restores nothing because it
snapshots the already-ducked level. A new satellite must be added to the
trigger's `entity_id` list by hand. `on` is accepted alongside `playing`
because Samsung TVs never report `playing`.

Only players that take `volume_set` count (`supported_features` bit 4). DEVICE-FOUND
2026-10-30 on the Office TV: the Android TV Remote face (`media_player.office_tv_2`)
reports a volume but offers step and mute only, so the first run died with
"does not support action media_player.volume_set" and nothing ducked. The TV's
Cast face (`media_player.googletv1645_2`, "Office Google TV Media Player") takes
`volume_set` and moves the TV's own volume (the remote face reads the change
back). It sat in no HA area, so it was moved into Office through the device
registry; a TV whose Cast face is in the room is ducked, one with only the
remote face is skipped. 2026-10-30: the Living Room TV, Pool House Lounge TV
and Sunroom TV Cast faces were moved into Living Room, Pool Lounge and Rear
Porch the same way, so every Google TV ducks once its room has a satellite.
The kitchen Family Hub TV's Cast face stays out on purpose: its Samsung face
already takes `volume_set`, and two faces on one TV would fight over the restore. Verified with `assist_satellite.announce` on the Office
satellite: 0.10 to 0.03 at `listening`, back to 0.10 on `idle`. Both satellites
(Kitchen and Office) are in the trigger.

Verified 2026-10-29 with `assist_satellite.announce` on the kitchen satellite:
trace shows `volume_set` 0.5 -> 0.15 at `responding`, the wait completing on
`idle` 4.4 s later, and `volume_set` back to 0.5; mute untouched.

```yaml
id: voice_duck_room_while_listening
alias: 'Voice: duck the room while listening'
description: 'When a voice satellite leaves idle (listening / processing / responding), lower every playing
  speaker in its room that takes volume_set to 30% of its volume; when the satellite is idle again, put
  each one back to exactly what it was. Volumes live in this run, not in a scene: scene restore sends
  mute commands, and a Samsung TV''s mute is a toggle. A player without volume_set (the Android TV Remote
  face offers step and mute only) is skipped; put the TV''s Cast face in the room instead, it moves the
  TV volume. Add new satellites to the trigger.'
triggers:
- trigger: state
  entity_id:
  - assist_satellite.home_assistant_voice_0a6b85_assist_satellite
  - assist_satellite.home_assistant_voice_0a8547_assist_satellite
  from: idle
  to:
  - listening
  - processing
  - responding
actions:
- condition: template
  value_template: '{{ snapshot | count > 0 }}'
- repeat:
    for_each: '{{ snapshot | list }}'
    sequence:
    - action: media_player.volume_set
      target:
        entity_id: '{{ repeat.item }}'
      data:
        volume_level: '{{ [ (snapshot[repeat.item] | float) * ratio, 0.02 ] | max | round(2) }}'
- wait_for_trigger:
  - trigger: template
    value_template: '{{ is_state(satellite, ''idle'') }}'
  timeout:
    seconds: 120
  continue_on_timeout: true
- repeat:
    for_each: '{{ snapshot | list }}'
    sequence:
    - action: media_player.volume_set
      target:
        entity_id: '{{ repeat.item }}'
      data:
        volume_level: '{{ snapshot[repeat.item] }}'
mode: single
variables:
  satellite: '{{ trigger.entity_id }}'
  ratio: 0.3
  snapshot: '{% set sat_dev = device_id(satellite) %}{% set ns = namespace(out={}) %}{% for e in area_entities(area_id(satellite))
    | select(''match'',''media_player\.'') | list %}{% if states(e) in [''playing'',''on''] and state_attr(e,''volume_level'')
    is number and device_id(e) != sat_dev and (state_attr(e,''supported_features'') | int(0)) | bitwise_and(4)
    %}{% set ns.out = dict(ns.out, **{e: state_attr(e,''volume_level'')}) %}{% endif %}{% endfor %}{{
    ns.out }}'
```

## Troubleshooting

### A "play X on Y" sentence dies with `Unexpected error during intent recognition` and Argyle never runs

Found 2026-10-27 with "Play mayonnaise by Smashing Pumpkins on the office TV":
the pipeline debug shows `intent-failed`, the core log shows

```
File ".../helpers/intent.py", line 116, in async_handle
    raise UnknownIntent(f"Unknown intent {intent_type}")
```

and the Chauffeur add-on log has nothing, because Chauffeur was never
called. Same shape as the `RuleReference` failure below: the BUILT-IN agent
runs first under prefer-local, a sentence file matches, and the match raises
instead of returning "not handled", so the pipeline aborts before the
fall-through. Here the file is Music Assistant's
`/config/custom_sentences/en/music_assistant_PlayMediaOnMediaPlayer.yaml`,
whose `MassPlayMediaOnMediaPlayer` intent has no registered handler in this
Home Assistant (the current Music Assistant integration no longer registers
it). Every `<play> {query} on {name}` sentence in the house lands there, and
it would also have aimed at `media_player.office_tv_2`, the Android TV remote,
not the Music Assistant player.

Confirm before touching anything: Developer tools has no UI for it, but the
WebSocket command `conversation/agent/homeassistant/debug` with the sentence
returns `"source": "custom", "file": "en/music_assistant_...yaml"` and the
intent name. Then rename or delete the `music_assistant_*.yaml` files under
`/config/custom_sentences/en/`, run **Developer tools → Actions →
`conversation.reload`**, and the debug call should report no match. The
sentence now falls through to Argyle, whose `music` tool plays on the room's
Music Assistant player. Music Assistant updates may put the files back; the
debug call is the one-minute check.

### Every voice command fails with `ValueError: RuleReference(rule_name='...')`

```
File ".../hassil/expression.py", line 250, in _compile_expression
    raise ValueError(rule_ref)
ValueError: RuleReference(rule_name='area')
```

**Not Chauffeur, and Chauffeur never even runs.** This is HA's BUILT-IN agent
failing to compile its sentence set. `prefer_local_intents` (step 3) makes the
pipeline offer every utterance to that agent first, and the call is not
individually guarded — `assist_pipeline` catches the exception and aborts with
`IntentRecognitionError`, so the pipeline dies before it can fall through to the
conversation agent. One malformed sentence anywhere in HA therefore takes out
**all** voice commands, Chauffeur's included, and the traceback never mentions
Chauffeur.

Something is referencing an expansion rule (`<angle brackets>`) that isn't
defined. Lists are `{braces}` — `{area}` is a list, `<area>` is a rule — and
copying a built-in sentence out of the intents repo without its `_common.yaml`
is the usual way to end up with a dangling one. Two places to look:

```bash
grep -rn "<area>" /config --include=*.yaml     # name from the ValueError
```

1. `/config/custom_sentences/<lang>/*.yaml`. **Music Assistant's are a known
   offender, and there is more than one of them** (`MassPlayMediaAssist`,
   `MassPlayMediaOnMediaPlayer`, …). Each defines every rule it uses —
   `play`, `on`, `artist`, `track`, `player_devices` — except `area`, which it
   expects to come from Home Assistant's own sentences. When that stops
   resolving, one integration's sentence files take every voice command in the
   house down with them. Fix them all in one pass:

   ```bash
   grep -rl "<area>" /config/custom_sentences/          # see the damage
   sed -i 's/<area>/{area}/g' /config/custom_sentences/en/*.yaml
   ```

   Anything installed by an INTEGRATION is worth suspecting before your own
   files — and worth re-checking after that integration updates, since an
   update restores its own copies and the fault with them.
2. **Automations with a `conversation` trigger** — the `command:` strings are
   compiled by the same code, and sentence triggers do NOT support expansion
   rules, so a `<...>` in one fails exactly like this. Easy to miss because it
   does not look like a sentence file.

The fix is one of two, depending on what was meant:

```yaml
# it should have been a LIST — areas are one Home Assistant provides
- "turn on the lights in {area}"

# or it really is a rule, and the file has to define it
expansion_rules:
  area: "[the] {area}"
```

Then **Developer tools → Actions → `conversation.reload`**.

**If grep finds nothing, bisect — the traceback names no file, so do not keep
reading YAML.** hassil raises on the rule reference with no idea which file it
came from, which is why this is worth five deterministic minutes instead:

1. Rename `/config/custom_sentences` to `custom_sentences.bak`, call
   `conversation.reload`, try a command.
2. **Works** → the culprit is in that folder. Put the files back one at a time,
   reloading after each, until it breaks again.
3. **Still fails** → it is not a sentence file. It is a `conversation` trigger
   in an automation or a blueprint, which the same compiler processes. Disable
   automations with conversation triggers in batches the same way.

To confirm the diagnosis before any of that, switch **Prefer handling commands
locally** OFF: Chauffeur voice commands start working immediately, because that
skips the broken built-in path entirely. Built-in commands (garage, lights) stop
resolving while it is off, so that is a bisect, not a fix — and leaving it off
is the one thing you should not do, since it is what routes "open the garage"
to Home Assistant instead of to Argyle.

## Behavior notes

- Voice conversations get multi-turn memory: HA keeps a `conversation_id` for
  follow-up turns, and the add-on threads history through the same conversation
  store as the chat widget (ids prefixed `voice-`, titled 🎙️). Follow-ups like
  "actually, make it Mom instead" work within a voice session.
- Voice runs with the admin toolset (no driver identity), same as the control
  center chat. Don't put this pipeline on a device you wouldn't hand admin chat.
- If a family member's name ever collides with an exposed entity/area name,
  "prefer local" could steal a scheduling sentence — rename or unexpose the
  entity if that happens. Component 1.5.0's local relay (above) has the same
  edge: a sentence whose every name resolves to a real exposed entity is the
  house's, with or without prefer-local.
