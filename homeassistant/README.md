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
through. Nothing in this integration can recover it — by the time our entity is
called the local response is gone and we are not told it existed.

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
main garage" to Argyle, which cannot open it. The flag means "this agent
controls Home Assistant entities"; ours controls a schedule.

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
  entity if that happens.
