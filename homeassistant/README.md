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

> **Voice Preview Edition does NOT do openWakeWord.** It runs microWakeWord
> on-device and there is no "process the wake word in Home Assistant" setting
> to switch it over — the wake-word select only lists models baked into the
> firmware it is running (Okay Nabu / Hey Jarvis / Hey Mycroft). An earlier
> version of this file said to flip that setting; the setting does not exist,
> and no amount of `/share/openwakeword/` will make Voice PE see a custom word.
> Getting one onto a Voice PE means building and flashing firmware. There is no
> path around that.

### On a Voice Preview Edition — custom firmware

1. Get a **microWakeWord** model for the phrase. Training your own is a
   different pipeline from the openWakeWord notebook below; the community
   [Tater-Wake-Words](https://github.com/Tater-Wake-Words) collection is where
   most people start, and a ready-made model saves the training run entirely.
2. In **ESPHome Builder**, *take control* of the device (this is what makes the
   YAML yours to edit — and hands you its updates from then on: Nabu Casa's
   OTA releases stop applying, which is the real cost of this route).
3. Add a `micro_wake_word:` block listing your model alongside the stock ones,
   then **Install** — OTA once the device is adopted, no cable.
4. Reconfigure the integration so the new word shows in the wake-word select.

If the flash goes wrong the device is recoverable with the **Voice PE Imager**,
so this is reversible — it is just not a setting.

### On a streaming satellite — openWakeWord

For an ATOM Echo, an S3-BOX-3, or `wyoming-satellite` on a Raspberry Pi, the
server-side route works and is much less work (free, ~1 hour, no recordings of
your own voice):

1. Open the [openWakeWord training notebook](https://www.home-assistant.io/voice_control/create_wake_word/)
   from the HA docs and train on `hey argyle` — it synthesizes thousands of TTS
   samples. Download `hey_argyle.tflite`.
2. Install the **openWakeWord** add-on and put the file in
   `/share/openwakeword/`.
3. On the satellite, set wake word processing to run **in Home Assistant** and
   select `hey argyle`.

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
