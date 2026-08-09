# Home Assistant Voice Integration ("Hey Argyle")

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
the add-on has no auth of its own; keep it reachable only on the internal
Docker network.

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

- **The command gets cut off after about a second** — logs show `STT by VAD end`
  right after detection. Fix: ESPHome integration → device settings → set
  **finished speaking detection** to **relaxed**.

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

Either way, a bad flash is recoverable with the **Voice PE Imager**.

### Installing a modified YAML

`chauffeur/home-assistant-voice.yaml` in this repo is a **copy for versioning**.
Editing it changes nothing on the device until it reaches ESPHome.

1. **Take control, once.** ESPHome Device Builder → the Voice PE → **TAKE
   CONTROL**. This generates a config for it and, crucially, an **API
   encryption key** and OTA credentials, and re-pairs Home Assistant to it.
2. **Copy three things out of that generated config before you overwrite it**:
   `esphome: name:`, `api: encryption: key:`, and the `ota:` password/key.
3. **EDIT** → paste your YAML → **put those three back**. Then check `wifi:`.
4. **SAVE → INSTALL → Wirelessly**, and let the build run to
   `INFO Successfully uploaded program`.
5. Open **LOGS** and watch the device boot.

Editing the files directly instead of using the Builder's editor works too —
they live in the add-on's config folder (`/config/esphome/` in the standard
layout) — but the editor sidesteps the question of which path your add-on
version uses.

**Three traps, and the upstream `home-assistant-voice.yaml` has all three**,
because it is the factory source rather than an adopted-device config:

- **No `api: encryption:`.** Home Assistant already holds a key for this
  device. Flash firmware without one and it will not pair — the device goes
  unavailable and you end up deleting and re-adding the integration.
- **No `ota:` password.** Coming FROM Nabu Casa's firmware the first OTA can be
  refused, which means USB for that one flash.
- **No `wifi:` credentials.** It relies on what is already stored in flash.
  That survives an OTA, but any full erase brings the device back with no
  network and no way in except USB. Adding `ssid: !secret wifi_ssid` /
  `password: !secret wifi_password` is cheap insurance.

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

## Troubleshooting

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

1. `/config/custom_sentences/<lang>/*.yaml`.
2. **Automations with a `conversation` trigger** — the `command:` strings are
   compiled by the same code, and sentence triggers do NOT support expansion
   rules, so a `<...>` in one fails exactly like this. Easy to miss because it
   does not look like a sentence file.

Fix the reference (usually `<area>` → `{area}`), then **Developer tools →
Actions → `conversation.reload`**.

To confirm the diagnosis before hunting, switch **Prefer handling commands
locally** OFF: Chauffeur voice commands start working immediately, because that
skips the broken built-in path entirely. Built-in commands (garage, lights) stop
resolving while it is off, so this is a bisect, not a fix.

## Behavior notes

- Voice conversations get multi-turn memory: HA keeps a `conversation_id` for
  follow-up turns, and the add-on threads history through the same conversation
  store as the chat widget (ids prefixed `voice-`, titled 🎙️). Follow-ups like
  "actually, make it Mom instead" work within a voice session.
- Voice runs with the admin toolset (no driver identity), same as the control
  center chat. Don't put this pipeline on a device you wouldn't hand admin chat.
- If a family member's name ever collides with an exposed entity/area name,
  "prefer local" could steal a scheduling sentence — rename or unexpose the
  entity if that happens.
