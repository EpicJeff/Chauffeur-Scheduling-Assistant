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

HA's stock wake words don't include "Hey Argyle", so train one (it's free,
~1 hour, no recordings of your own voice needed):

1. Open the openWakeWord training notebook linked from the HA docs
   (https://www.home-assistant.io/voice_control/create_wake_word/).
2. Train on the phrase `hey argyle` (the notebook synthesizes thousands of TTS
   samples). Download the resulting `hey_argyle.tflite`.
3. Install the **openWakeWord** add-on, and place the file in
   `/share/openwakeword/`.
4. On your voice satellite (ESPHome device / Voice Preview Edition), set wake
   word processing to run **in Home Assistant** and select `hey argyle`.
   (On-device microWakeWord only ships stock words; streaming to openWakeWord
   is how custom words work.)

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
