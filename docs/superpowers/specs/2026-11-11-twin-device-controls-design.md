# Real device controls in the 3D house: design

Status: draft for the user's approval (2026-11-11). It amends the twin design (2026-11-06 §5.4, §6, §10, §14) and builds on piece 3 (v2.499.782) and real lights (v2.499.783).

## 1. Why

The user, 2026-11-11: "For lights, I want to tap the light in the house to turn it on or off and I want the color and brightness controls right there with the light icon. Whatever you can do in a fancy light card, I want that interactive in the browser. Same with thermostats, I want the temp setting(s) shown as handle(s) on an arc like in the thermostat card and I want to be able to set modes. This has to give useful controls for most/all of the things or it is just a pretty shell with no value."

Today, devices other than lights and locks mostly show status:
- the tap sheet is compact and hides the brightness slider and the thermostat nudge (`live/live.js:170`);
- covers, media players and cameras get no controls;
- state arrives by a 10 s poll.

The user ranked this slice first (2026-11-11).

## 2. Goals and non-goals

**Goals**
- Every common device kind can be controlled from the house:
  - light, switch and outlet;
  - fan;
  - climate (thermostat);
  - cover (blinds, shades, garage);
  - lock;
  - alarm;
  - media player;
  - vacuum;
  - humidifier;
  - water heater;
  - scene and script;
  - camera, which is viewed rather than controlled.
- The controls sit where the device is: at its marker in the 3D house.
- The full control set is one tap deeper, in the room panel.
- State changes from anywhere show within about 1 s, pushed from Home Assistant rather than polled.
- Marker kinds and modes become registries, the plug-ins the twin design called for, so later modes are additions rather than core edits.

**Non-goals**
- New permission rules. The household control grid (`services/control_rules.py`) stays the single gate, and every control goes through `api/ha/card/service`.
- Energy, Climate and Security modes. Those are the next slice; this one only adds the registry they will plug into.
- Sensor history graphs.

## 3. Decisions

1. **Registries.**
   - `static/twin/live/kinds.js` maps each kind to:
     - `match(entity)`;
     - its icon;
     - `look(state)`, which gives on, off, attention or unavailable;
     - `quick` (the tap action);
     - `ring(state)` (the controls drawn at the marker);
     - `panel(state)` (the room-panel row);
     - `unsafe` (the services that need a confirm).
   - `static/twin/live/modes.js` becomes a mode registry: `{id, label, enter, update, leave}`. Lights and All register into it.
   - `markers.js`, `room_panel.js` and `live.js` read the registries instead of their if-chains.
2. **Tap and press-and-hold at the marker.**
   - **Tap** does the kind's quick action:
     - light, switch, outlet and fan toggle;
     - a scene or script runs;
     - lock, garage and alarm open their ring with a confirm;
     - climate, cover, media, vacuum and camera open their ring.
   - **Press-and-hold** (500 ms), or a tap on an open ring's centre, opens the ring for a kind whose tap toggles.
   - **The ring** is an HTML overlay anchored to the marker's projected position. It follows the camera, is touch-sized (44 px targets), and closes on a tap outside it or on Escape.
3. **The ring per kind.** One shared builder serves both the ring and the room panel's expanded row (UI guide: the same concept uses the same builder).
   - **Light:**
     - on/off in the centre;
     - a brightness arc;
     - a colour-temperature arc and colour swatches, plus a colour wheel when `supported_color_modes` allows each;
     - effects as a chip list when the light has `effect_list`.
   - **Climate:**
     - an arc showing the current temperature;
     - one setpoint handle, or two for `heat_cool` (`target_temp_low` and `target_temp_high`), dragged to set them, within min, max and step;
     - `hvac_mode` chips from `hvac_modes`;
     - fan mode and preset chips when the entity supports them;
     - the `hvac_action` shown as heating, cooling or idle.
   - **Fan:** on/off, a speed arc (`percentage` / `percentage_step`), oscillate, direction and preset when supported.
   - **Cover:** open, stop and close, a position arc (`current_position`), and tilt when supported. A garage door's open asks first.
   - **Media player:** play/pause, previous and next, a volume arc and mute, a source list, and the title and artist as text. No artwork, because it needs Home Assistant authentication and would need a proxy route.
   - **Lock:** Lock, and Unlock behind a confirm.
   - **Alarm:** the arm modes it supports, and Disarm behind a confirm. A code is asked for in an in-page sheet, never a browser dialog, when `code_format` requires one.
   - **Vacuum:** start, pause, return to dock, and locate.
   - **Humidifier and water heater:** on/off and a target arc, plus mode chips.
   - **Camera:** a live still that refreshes every 2 s, through a new route `GET api/house/camera/{entity_id}` (WALL_OR_SERVICE).
     - The server fetches HA's `camera_proxy`, so no token reaches the page.
     - The route obeys the grid's view rules.
     - MJPEG streaming is left for later.
   - **Sensor and binary sensor:** the value and its unit, no controls.
4. **Home Assistant's own cards as the "more" level.** The room panel's per-device "More" opens HA's real card through the existing card host (`static/ha_card_host.js`, `ChauffeurHaCards.mountBuiltin`):
   - light, thermostat, humidifier and tile for the rest.
   - Locks, garages and alarms are excluded, because a hosted card would skip our confirm.
   - When a card refuses to mount, our own ring is the fallback.
   - The hosted card's service calls already go through `api/ha/card/service` and the grid.
5. **Live state push.**
   - A long-lived server websocket client (`services/ha_events.py`) subscribes to `state_changed`, keeps the state cache warm, and fans out to an SSE route `GET api/ha/stream` (WALL_OR_SERVICE, filtered to the entities the page asks for).
   - The twin and the card host listen. Polling stays as the fallback, and as the only path when the stream is down.
   - With no Home Assistant, nothing connects and nothing errors (graceful degradation).
   - A device still shows only confirmed state, never an optimistic flip. With push, confirmation arrives in well under a second.
6. **Permissions and safety are unchanged.**
   - `offered` decides whether a marker acts.
   - A `needs` answer (PIN or identify) goes through `chfControlFetch`, as today.
   - Unlock, open and disarm confirm exactly once, in the shared control path (v2.499.782).
7. **The wall panel.** Rings and arcs are drawn at panel scale, with no hover-only affordances, and work by touch on the Pi.

## 4. Proven by

**Exit, at the wall panel (`?panel=true&kiosk=true`):**
1. Tap the kitchen light: it toggles, and the marker shows the confirmed state within 1 s.
2. Press and hold it: the ring opens at the light. Set the brightness to 40% and the colour to blue; the light follows, and so does the real-time or baked light in the scene.
3. Tap the thermostat: drag the setpoint handle to 70, switch the mode to cool; Home Assistant shows both.
4. Set a blind's position to 50%, change a speaker's volume, and see a camera's still.
5. Change a light in the Home Assistant app: the house shows it within 1 s.

**Tests:**
- node tests for each kind's ring builder against Home Assistant attribute shapes;
- live scenarios for each step of the exit above, using the fake Home Assistant;
- TestClient tests for the stream route (auth, filter, no-HA) and the camera route (auth, the grid, no token leak).

## 5. User answers (2026-11-11)

- Gesture: tap toggles a light, switch, outlet or fan; press-and-hold (or a tap on an open ring's centre) opens the ring; other kinds open their ring on tap (decision 2 stands).
- Home Assistant's own cards are the room panel's "More" level (decision 4 stands), locks, garages and alarms excepted.
