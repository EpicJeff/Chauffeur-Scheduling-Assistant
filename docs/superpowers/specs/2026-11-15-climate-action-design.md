# Climate mode shows what the system is doing

Date: 2026-11-15. Status: draft for the user's approval.

## Why

The twin's Climate mode colours a room's floor by its temperature against a comfort band: blue when it is below, grey inside, red above. The user expected something else: to see, from across the room, whether an area is being heated or cooled right now, the way a Honeywell T10's screen turns orange or blue. Today a cold room that is being heated shows blue, which reads as the opposite. And only the rooms in the thermostat's own Home Assistant area show anything, so most of the house stays blank.

## What the user decided (2026-11-15)

- Colour means what the system is doing: orange while heating, blue while cooling.
- The comfort tint (blue cold room, red hot room) is dropped as a colour. Temperature stays in the label.
- Rooms being heated or cooled breathe (a slow pulse).
- A thermostat serves a set of rooms, with three scopes: **Whole house**, **Whole floor**, **These rooms**. The house and floor scopes take an **Except** list.
- The narrower scope wins: These rooms beats Whole floor beats Whole house.

## Goals

1. In Climate mode every room a thermostat serves shows that thermostat's action as a floor wash.
2. In All mode only rooms being heated or cooled right now carry the wash, so a wash always means something.
3. A person sets which rooms a thermostat serves, by hand, in the editor.
4. A house where nobody has set anything still shows something sensible.

## Not in this slice

- Pool and spa heaters, steam, spa jets and the other new effects. They are the next slice.
- Changing the thermostat marker's disc colour or the thermostat control panel.
- Any agent tool. The `house_design` schema is at its cap and is not touched.
- A "conditioned" flag on rooms. The Except list covers the garage and porch.

## Would make this a failure

- A wash that shows on rooms the thermostat does not serve, or that stays on after Home Assistant goes stale.
- A new stream per tab, or a new per-frame cost on the low tier.
- Losing a person's zone setting when the thermostat marker is moved.
- Anything a person can do today going away, other than the comfort tint the user approved dropping.

## Behaviour

### Action

One action per thermostat (`climate.*` entity), in this order:

1. State is stale, `unknown` or `unavailable`: **none**.
2. State is `off`: **off**.
3. `hvac_action` is `heating` or `preheating`: **heat**. `cooling`: **cool**. Any other reported value (`idle`, `fan`, `drying`, `defrosting`, `off`): **idle**.
4. No `hvac_action` reported: infer. In `heat`, current below the setpoint is heat. In `cool`, current above the setpoint is cool. In `heat_cool` or `auto`, current below the low setpoint is heat and above the high setpoint is cool. Anything else is idle.

### Colour

| Action | Climate mode | All mode |
|---|---|---|
| heat | orange wash, breathing | orange wash, breathing |
| cool | blue wash, breathing | blue wash, breathing |
| idle | faint grey wash, steady | no wash |
| off, none, or no thermostat serves the room | no wash | no wash |

- Orange `[240, 120, 40]`, blue `[65, 143, 232]`, grey is today's `NEUTRAL`. They live in `static/twin/palette.js` beside the other mode colours.
- Breathing: the wash opacity moves between about 0.5 and 0.8 on a period of about 3 seconds. On the low tier, and when the browser asks for reduced motion, it holds steady at 0.72 (today's value). Idle grey is steady at about 0.35.
- The pulse must not force the lamp and bake section of `draw()` to rerun each frame. It sets opacity on the wash materials that are showing and nothing else.

### Which rooms a thermostat serves

Each thermostat has a zone setting: `scope` (`house`, `floor` or `rooms`), `rooms` (room ids, used by `rooms`) and `except` (room ids, used by `house` and `floor`).

- **These rooms**: the room the thermostat stands in, plus the rooms picked.
- **Whole floor**: every room on the level the thermostat stands on, in its building, less the Except list.
- **Whole house**: every room in the building the thermostat stands in, less the Except list. Another building (a pool house) is never included.
- A room goes to the narrowest scope that claims it. Between two thermostats of the same scope, the one standing in the room wins, then the lowest entity id, so the answer never flickers.
- Ghost rooms and yard rooms are never served by a house or floor scope. A yard room can be picked under These rooms.

Defaults, while a person has set nothing for that thermostat:

- A thermostat that is placed, and is the only placed thermostat in its building: Whole house.
- Placed, with others in the building: Whole floor.
- Not placed: the rooms linked to its Home Assistant area, as today.

A default is computed on read and never stored, so it follows the house as thermostats are placed. Once a person saves a setting it holds until they change it.

### Labels

- The room a thermostat stands in carries the zone's label: room name, current, arrow, setpoint, and the action word when heating or cooling. Example: `Hall 68° → 71° Heating`. An unplaced thermostat labels the first room it serves.
- A served room with its own temperature sensor shows its own reading as a short label (`Office 66°`), so a cold room in a zone is still visible now that colour no longer says it.
- Other rooms carry no label.
- Labels show in Climate mode only, as today.

### Legend

`Orange · Heating   |   Blue · Cooling   |   Grey · Idle`

### No Home Assistant

No thermostat state means no wash and no label, as today. The editor control still works on the stored setting.

## Storage and ops

- Model map `climate_zones`, keyed by climate entity id: `{scope, rooms, except}`. It sits beside `light_fixtures_meta` and `camera_views` and follows their pattern, so it survives the marker being moved (a move unplaces and re-places the row).
- One op, `set_climate_zone {entity, scope, rooms, except}`. Sending `scope: null` clears the setting back to the default. Validation: the entity is a `climate.` id, scope is one of the three, room ids are strings and are de-duplicated, lists are capped (64). Ids for rooms that no longer exist are dropped on read, not rejected, so deleting a room never breaks a save.
- The setting reaches the viewer in the `/api/house/live` layout the same way `camera_views` does. No new stream and no new route.

## Viewer

- A pure module (the rewritten `static/twin/live/climate.js`) resolves zones: given the layout's rooms, markers, devices, `climate_zones` and the states, it returns per room `{entity, action, current, target, unit, label}`. It keeps exporting what `room_cards.js` needs for the room temperature fact; that fact does not change.
- `temperatureColor` and the comfort band go away with their tests.
- Floor wash slabs are built today only for rooms linked to a Home Assistant area. A served room may have no area, so slabs are needed for every non-ghost room with a polygon. They stay hidden unless washed, so the draw-call count of a house with nothing heating does not change. The light wash keeps using the same slabs.
- The marker dimming rule for Climate mode (`foreground`) is unchanged.

## Editor (the hand path)

A thermostat has no card today. In the room card's Devices list, a device whose kind is `climate` gets a **Serves** row:

- A select: Whole house, Whole floor, These rooms. With nothing saved it shows the default and says so (`Whole house (default)`).
- A room checklist under it, labelled `Rooms` for These rooms and `Except` for the other two, listing the building's rooms as `Name · Level` (the list `choosable` already builds). The thermostat's own room is shown ticked and locked under These rooms.
- Each change sends one `set_climate_zone`. Read-only people see the values disabled.
- No browser dialogs.

## Tests

- Zone resolution: each scope, the precedence, the tie rule, the Except list, ghost and yard rooms, both defaults, the unplaced fallback, a removed room id.
- Action: every `hvac_action` value, each inference branch, off, stale and unavailable.
- Mounted mode under Node: heat shows orange on every served room and none on an excepted room; idle is grey in Climate and hidden in All; the pulse changes opacity between frames on a non-low tier and not on low; labels as specified; cleanup.
- Op and model: `set_climate_zone` through a real request, validation, clear, survival across a marker move, the layout carrying it.
- Editor: the Serves row draws for a thermostat only, sends one op per change, and is read-only when it should be.
- Existing tests that pin the comfort tint are rewritten to the new behaviour, not deleted: `tests/test_twin_climate_js.py`, the Climate part of `tests/test_house_twin_glance_live.py`. Neighbours to keep green: `tests/test_twin_live_rooms_js.py`, `tests/test_twin_energy_js.py`, `tests/test_twin_fixture_lights_js.py`, `tests/test_twin_real_lights_js.py`, `tests/test_twin_palette_js.py`, `tests/test_twin_building_reuse_js.py`.

## Calls made by Claude, not by the user

- Idle shows as faint grey in Climate mode, and nothing in All mode.
- The pulse is off on the low tier and under reduced motion.
- The label sits on the thermostat's room only; rooms with their own sensor get a short reading.
- The tie rule (standing in the room, then lowest entity id).
- The setting is keyed by entity, stored beside the camera and light settings, and edited from the Devices list.
- A missing `hvac_action` is inferred from mode and setpoint.
