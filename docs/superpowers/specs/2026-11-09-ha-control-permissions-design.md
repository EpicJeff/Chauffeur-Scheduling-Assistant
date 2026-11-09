# Who can control what: one rulebook for Home Assistant control

Date: 2026-11-09. Status: design, awaiting approval. First of three projects (see "Where this sits").

## Why

Today three surfaces decide whether a Home Assistant device may be operated, and they disagree:

- Board tiles and hosted HA cards use an allowlist (`home_board.HA_TOGGLE_DOMAINS`) plus one household switch, `panel_allow_unsafe_controls`, which adds locks, covers, garage and valves (`services/home_board.py:3273-3306`, enforced in `main.py` `/api/ha/toggle` and `/api/ha/card/service`).
- Argyle's `house` tool refuses locks, alarms and garage/door/gate covers unless a "trusted hand" asks: a signed-in parent/adult, the admin page, or a PIN-verified parent/adult voice. The wall panel chats as `access.HOUSE` and is never trusted (`services/house.py:892-904`, `:958-962`).
- Voice adds a PIN on top: a voice recognised by fingerprint is only `named`; locks need `verified` (PIN).

So in a household that turned the tile switch on, the lock tile on a panel unlocks the door, but Argyle on the same panel refuses. The user's ruling: a household knows its own doors; one rulebook, set by the household, that every surface obeys. "Why would Chauffeur be any different from my HA panel?"

## Goals

- One household switch that turns all Chauffeur control of HA devices on or off.
- One grid of who may control which kind of thing, which every surface reads: board tiles, hosted HA cards, the music/media card, climate card, Argyle typed (phone, panel, admin), and Argyle by voice.
- A per-kind "needs proof of who you are" checkbox, so a household decides which kinds must know the person for certain rather than guess.
- Scenes and scripts judged by what they actually touch.
- On upgrade, the default grid reproduces today's behaviour (two deliberate exceptions listed under Migration).
- A warning when Home Assistant's own voice handling can operate devices around these rules.

## Non-goals

- Per-device exceptions ("kids may open the pool house lock but not the front door"). The user called this over-engineering for now; a possible later step.
- Governing what people do in Home Assistant's own app, or what HA automations do on their own.
- Changing HA's pipeline configuration. Commands HA handles itself are an HA config issue (the user's ruling); Chauffeur warns, it does not fix.
- Recognised voices making non-HA changes (calendar, approvals) without a PIN, and ending a recognised voice session on sign-off. Those are project 2.
- Panel rooms, satellites and tap-to-talk. Project 3.
- Reading device state. Reads stay open exactly as today, switch on or off.

## Anti-goals (would be a failure even if it works)

- Any surface allowing what another refuses for the same person and the same device. The whole point is one answer.
- The settings screen claiming more than happens (for example showing "Yes" for the panel on a kind where it will actually ask who you are).
- Asking a signed-in person for a PIN. The user: "if I am signed into the Admin section or my phone, I don't want to be asked to authenticate with a PIN. I just want to make sure people are who we think they are."
- A browser dialog anywhere (house rule: `promptInput`/`promptConfirm`/`showGlobalAlert` only).

## The rules (decided with the user)

### The household switch

"Chauffeur can control Home Assistant devices." Off: no surface operates any device. Reads still work. On: the grid below applies.

### Kinds of thing

Rules are per kind, not per device (the user: kind is fine-grained enough). The kinds, mapped from HA domain and device_class (my call on the exact mapping; the builder may refine edge domains):

| Kind | HA |
|---|---|
| Lights | `light` |
| Switches & fans | `switch`, `fan`, `input_boolean` |
| TV & music | `media_player`, `remote` (includes Argyle's music tool and TV app launch) |
| Climate | `climate`, `water_heater` |
| Blinds & shades | `cover` whose device_class is not garage/door/gate |
| Garage, doors & gates | `cover` with device_class `garage`, `door` or `gate` |
| Locks | `lock` |
| Alarm | `alarm_control_panel` |
| Everything else | any other DEVICE domain (valve, vacuum, button, number, select, siren, lawn mower, humidifier, and so on) |

Scenes and scripts are not a kind; see below.

**Never callable from Chauffeur, whatever the grid says** (my call, after the builder check): system and configuration domains, never devices, so not in any cell: `homeassistant` (restart/stop/reload), `hassio`, `automation`, `system_log`, `recorder`, `logger`, configuration reloads, and notify/tts (they are not device control; existing notify paths stay as they are). Today `/api/ha/card/service` refuses them by allowlist; they stay refused.

### Who: two sorts of card

The settings screen is one card per "who", layout B from the brainstorm (the user chose it; it works on desktop and phone).

**People cards**, one per member role: parent, adult, child, helper, guest. Each kind is Yes or No. Nothing else.

**Cards for places with no known person**: Wall panel, and Unknown voice. Each kind is Yes, No, or Ask who.
- Yes: anyone there may do it.
- No: nobody may from there.
- Ask who: find out who it is, then that person's own card decides.

### Needs proof of who you are

One card at the top, under the household switch: one checkbox per kind. A checked kind requires that Chauffeur *knows* the person, not merely thinks so.

| How the person is reaching Chauffeur | Counts as proven? |
|---|---|
| Signed in on their own device (member token), or the admin pages | Yes, nothing asked |
| Just entered their PIN (panel handshake, or spoken to Argyle) | Yes |
| Recognised by voice fingerprint only (`named`) | No: Argyle asks for the PIN |
| Wall panel or unknown voice, nobody identified | No: it asks who you are |

When a kind needs proof, "anyone" cannot pass: a panel or unknown-voice cell set to Yes behaves as Ask who for that kind, and the screen shows it as "Ask who (needs proof)" (my call, from the anti-goal above).

### Resolving one request

1. Household switch off: refuse.
2. Work out the kinds the request touches (one, or several for a scene/script).
3. Work out who is asking:
   - member token on a personal device, or the admin page: that member's role;
   - PIN-verified voice: that member's role, proven;
   - fingerprint-recognised voice: that member's role, not proven;
   - wall panel with no person: the Wall panel card;
   - voice nobody recognises: the Unknown voice card.
4. For every kind touched: a place card's No refuses; Yes passes unless the kind needs proof; Ask who (or Yes on a proof kind) triggers identification, then the identified person's card decides. A person card's No refuses; Yes passes if the kind needs no proof or the person is proven; otherwise identification is asked for (voice: Argyle asks for the PIN).
5. All kinds must pass. One refusal refuses the whole request.

The admin page with no member (today's `acting_member is None and source == 'admin'`) stays fully trusted.

### Identifying someone ("Ask who")

- **Wall panel** (tiles, hosted HA cards, the music/climate cards, typed Argyle): a "Who are you?" face picker, then the existing PIN handshake. Lift `_avatarPinHandshake` (`templates/components/avatar_editor.html:48-60`, also behind the critter editor via `board_tile_body.html:494-530`) into one shared component so avatars, critters and control use the same PIN step (design guide: same concept, same builder). It returns a member token.
- **A PIN on the panel covers one action only** (my call; the panel is shared and the next person must not inherit an unlock). The next tap asks again. The server enforces this: the panel step mints a one-use grant for the one action, not an ordinary member token (today `/api/members/{id}/auth` returns the same `create_member_token` a phone sign-in gets, which the server could not tell apart from "signed in on their own device"). The avatar/critter use of the shared component keeps its ordinary token.
- **Where a member token came from matters** (Codex review). A token records how it was minted: `proof` (`password`, `pin` or `none`) and the device kind it was minted on. Only a token minted on a personal device with a password or PIN counts as "signed in on their own device". A token minted on a panel (avatar/critter step), or with no PIN, never counts as proof for control, with or without the device header.
- **Ask who always needs a PIN** (my call). `/api/members/{id}/auth` skips the PIN for a member with no `pin_hash`, so a face tap alone would let anyone pass as a PIN-less parent. On the control step, members without a PIN are shown but cannot be chosen ("Set a PIN to use this from the wall").
- **A parent's 15-minute house session on the panel** (`house_session` token, `house_life.js:158`) counts as the Wall panel card for control, not as the parent (my call; precedent: voice settings already refuse house sessions, `main.py:4015`). Otherwise anyone walking up in those 15 minutes inherits the parent's locks.
- **Voice**: Argyle's existing name-then-PIN flow (`services/voice_identity.py`). Its existing session length applies.
- **A voice that only claims a name** ("it's Mum", `level='named'` with no fingerprint, `voice_identity.py:482`) is the Unknown voice card until a fingerprint or PIN confirms it (my call). Only a fingerprint match (`recognized=True`, `voice_fingerprint.py:726`) gets the person's card without proof.
- **Where a voice cannot be identified at all** (identity off or unpaired on that satellite, or Argyle reached through HA's own Assist with no satellite metadata), Ask who cannot succeed. The refusal says so plainly ("Voice ID isn't on for this speaker; use your phone"), and the Unknown voice card carries a one-line note that Ask who needs voice ID on the speaker (my call).
- **Per-person access still applies, checked centrally.** The family-network scope facets stay in force for the EFFECTIVE person (including a person identified through a panel grant or a held action): TV & music needs the person's `music` facet on every lane, including the generic card service route, which has no facet of its own (Codex review). The helper and guest cards carry a one-line note that each person's own access can narrow this further (my call; per-person exceptions stay a non-goal).
- **Typed Argyle on the panel**: when the tool needs identification, the reply offers the same face picker + PIN step, and the action runs on success. Exact UI is the builder's, inside the design guide.

### Scenes and scripts

Judged by what they touch (the user's ruling: "follow the same permissions based on what they are affecting").
- Scene: its state's `entity_id` attribute lists every entity it sets.
- Script: HA's `search/related` websocket command (reachable through `ha_api.ws_command`, `services/ha_api.py:446`) returns the entities, devices, areas, scripts and scenes it references. Expand devices and areas through the registries Chauffeur already reads; recurse into called scripts and scenes.
- A script or scene is allowed only if every kind it touches is allowed for that person, and needs proof if any touched kind needs proof.
- **Anything Chauffeur cannot read makes the script count as touching the strictest kind** (the user: "Strict is fine. We can always revisit"). Unreadable means a templated target, or an action that names no HA entity and could operate something (`rest_command`, `shell_command`, and similar). Actions that cannot operate a device (delay, notify, tts, persistent_notification) are ignored. `conversation.process` is opaque, not harmless: it hands text to an HA agent that can operate anything (Codex review, 2026-11-09). "Strictest" means the script is judged as touching EVERY kind, so it passes only if every kind would pass for that person, proof included. Hard-coding Alarm was unsafe because a household may allow Alarm while denying Locks (Codex review).
- Following automations a script triggers indirectly (script flips `input_boolean.goodnight`, an automation watching it locks doors) is the builder's call: one more hop of the same search if cheap, otherwise left out and stated on the settings page.
- The settings page lists the household's scripts that landed on "strictest" because of an unreadable part, each with its reason, so the household can see them.
- Cache the analysis (scripts change rarely); invalidate on a short TTL like the registries.

### Home Assistant's own voice handling: warn only

The recommended pipeline (`homeassistant/README.md` section 3) turns on "Prefer handling commands locally", so HA answers sentences it recognises ("open the main garage") before Argyle sees them. Those commands never reach these rules. The settings page reads the pipelines (Chauffeur already lists them for TTS, `ha_api.get_pipeline_tts`), and when any pipeline prefers local handling it shows a plain warning naming the exposed devices, in kinds this household restricts, that any voice can operate through HA directly. No fix button. With no HA present, no warning.

### Refusals

A refusal says what would make it work, in the house voice ("Locks need a parent.", "Who's asking? Enter your PIN."). Tiles and cards show it through `showGlobalAlert`; Argyle says it. Wording is the builder's.

## Migration: defaults reproduce today

Defaults on upgrade:
- Household switch: on.
- Needs proof: Locks, Garage doors & gates, Alarm checked.
- Parent, adult: Yes everywhere.
- Child, helper, guest: Yes everywhere except Locks, Garage doors & gates, Alarm: No.
- Unknown voice: Yes everywhere except Locks, Garage, Alarm: Ask who.
- Wall panel: Lights, Switches & fans, TV & music, Climate, Blinds & shades, Everything else: Yes. Argyle at the panel could already operate blinds and other devices, and taking that away was never approved; the tiles widen to match (ruling 2026-11-09 after the Codex review, replacing the earlier stricter call). Locks, Garage: Ask who if `panel_allow_unsafe_controls` was on, else No. Alarm: No.
- `panel_allow_unsafe_controls` retires into the grid. Never drop a person's ability: everything it allowed is still reachable.

Two deliberate behaviour changes, both accepted in conversation:
1. A household that had `panel_allow_unsafe_controls` on now gets asked who before a panel unlock, because Locks needs proof by default. They can uncheck proof for Locks.
2. Scripts and scenes that touch restricted kinds (or cannot be read) are now refused to children, helpers, guests and the panel where today anyone could run them through Argyle.
3. Tiles and hosted cards now follow the person's role, not one board-wide switch. Where `panel_allow_unsafe_controls` was off, parents and adults gain locks, garage and blinds from their own phone's tiles (a widening). Where it was on, children, helpers and guests lose unlock and open-garage from their phone's tiles, matching what Argyle already refuses them. The user approved this removal on 2026-11-09.

`house_control_unexposed` (Argyle may control devices not exposed to Assist) stays exactly as it is, a separate gate.

## Settings placement

`services/settings_registry.py` entries; the screen lives in Config › People, in the drawer beside the Argyle settings (where `house_control_unexposed` already lives), never `config.html` directly. Editable by parents (my call: Config is already behind the admin gate). Layout B: household switch, then the needs-proof card, then one card per who, then the warnings (unread scripts, HA local handling). On a phone the cards stack; on desktop they may sit side by side.

## Constraints

- Every HA touchpoint degrades gracefully with no HA present.
- Enforcement is at the server, in one shared function every call site uses. Today's call sites that operate devices: `main.py` `/api/ha/toggle`, `/api/ha/card/climate`, `/api/ha/card/service`, `/api/ha/media_players/{entity_id}/command`, the music queue and favourites endpoints, `services/house.py` (act and app launch), `services/music_tool.py`, `music_queue.py`, `music_search.py`. The builder confirms the full list; announcements and notify are not device control and are out.
- Hosted HA cards are third-party JavaScript: the server decides, never the browser (`/api/ha/card/service` docstring).
- Each new or changed route needs its rule in `services/auth.py`.
- No browser dialogs. Tailwind rebuild after template class changes.
- Every critical path needs a test that runs it (TestClient request or node run), not a source grep. At minimum: a refused and an allowed request through each endpoint family; a panel Ask who round trip (PIN then action, then the next action asks again); voice named versus verified on a proof kind; a script that touches a lock; an unreadable script; switch off; migration from both values of `panel_allow_unsafe_controls`.

## Left to the builder

- Storage shape of the grid.
- Exact domain-to-kind mapping for rare domains.
- How the panel chat surfaces the face picker after a refused typed request.
- Refusal wording.
- Whether to follow automation chains for scripts.
- Cache lifetimes.

## Where this sits

1. This: the grid and the switch.
2. Recognised voices act (non-HA writes) by role, and a sign-off ends the recognised session so it is not inherited by the next conversation.
3. Panel rooms, the room's satellite, and a mic button in the panel's Argyle chat that starts a satellite conversation with no wake word (`assist_satellite.start_conversation`).
