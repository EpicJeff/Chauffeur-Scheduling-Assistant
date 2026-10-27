# The house tool: Argyle reads and controls Home Assistant devices

**Date:** 2026-10-27. **Status:** SHIPPED v2.499.694 (2026-10-27), NOT device-verified. Review fix: the wall panel (access.HOUSE) is never a trusted hand.
**Precedes:** component 1.5.0 local relay (v2.499.693), which hands the house's own
`no_valid_targets` answer back instead of Argyle's refusal.

## Why

Argyle refuses every house sentence ("I can't control smart home devices"). The
add-on already holds the Supervisor token, and `services/ha_api.py` already has
`get_states`, `get_history`, `call_service`, `render_template` and a one-shot
WebSocket. What is missing is the agent tool.

The built-in Assist agent handles the common sentence instantly and stays first in
every pipeline. Argyle takes what it cannot: duplicate names, non-literal names
("column one"), numeric questions ("how bright is the office lamp"), history
("when did the garage last open"), multi-step requests, and every Chauffeur chat
surface (PWA, wall bar, control center) that never reaches Assist at all.

## Decisions

1. **One tool, `house`.** `action` is one of `find`, `read`, `history`, `act`.
   One tool keeps Flash-Lite's tool pick honest; three tools would not.
2. **Reads are open.** Any entity, exposed to Assist or not. Secrets never leave:
   `access_token`, `token`, `entity_picture`, `id`, and any attribute whose key
   ends in `_token` are stripped. Brightness is reported as a percent beside the
   raw value. Attributes are capped at 30 keys.
3. **Writes respect HA's exposure list** (`homeassistant/expose_entity/list`,
   the `conversation` assistant). A new household setting
   `house_control_unexposed` (bool, default off) lifts that. It lives in
   `models.schemas.Settings`, the registry (`integrations` group, Config › People,
   `people` anchor, beside Argyle's service token) and the Argyle block on the
   People tab, saved through `saveAuthSettings`.
4. **Sensitive writes need a trusted hand.** Domains `lock`, `alarm_control_panel`,
   and `cover` whose `device_class` is `garage`, `door` or `gate` need a parent or
   adult: a signed-in parent/adult in chat, the admin control-center chat, or a
   VERIFIED voice. A named-only or unknown voice, and a kid, get
   `{'status': 'refused', 'message': 'That needs a parent on their phone.'}`.
   Everything else (lights, switches, fans, media, climate, other covers) is any
   member or any voice.
5. **An act reads back.** After `call_service`, the tool waits 0.6 s, re-reads the
   entity and reports the state it sees, never "done" on faith.
6. **Find never dumps the house.** `find` returns at most 8 candidates ranked by
   fuzzy score over friendly name, entity registry aliases, entity id words and
   area name, filtered by `domain` when given. Hidden and disabled registry
   entries are skipped. When a query names an area and no entity, the area's
   entities are listed (same cap).
7. **The local relay stays as shipped.** Routing Argyle into duplicate-name
   resolution is a later slice; this one gives Argyle the tool.
8. **Cars.** `manage_car` gains `action: locate`, which reads
   `cars.car_location` and answers with the HA zone state (`home`, `not_home`,
   a zone name), coordinates and, when coordinates exist, a reverse-geocoded
   place via a new `maps.reverse_geocode(lat, lon)` (Mapbox when configured,
   Nominatim `/reverse` fallback, same rate locks as forward). The house tool can
   read the same tracker; both paths exist on purpose.

## The tool

```
house(action, query='', entity_id='', domain='', service='', data={}, hours=24)
```

| action | input | output |
|---|---|---|
| `find` | `query` (required), optional `domain` | `{'status','candidates':[{entity_id,name,area,domain,state,aliases}]}` |
| `read` | `entity_id`, or `query` resolved through find (exactly one strong match, else the candidates come back with `status: 'ambiguous'`) | `{'status','entity':{entity_id,name,area,state,attributes,last_changed,brightness_pct?,exposed}}` |
| `history` | `entity_id` or `query`, `hours` (1..168) | `{'status','entity_id','points':[{at,state}], 'changes': N}` with points thinned to at most 50 |
| `act` | `entity_id` or `query`, `service` (`turn_on`, `turn_off`, `toggle`, `open_cover`, `set_temperature`, any `domain.service`), optional `data` | `{'status','entity_id','service','state_after','message'}` |

Rules in `act`:
- `service` without a domain uses the entity's domain; `light.turn_on` style is
  accepted and must match the entity's domain.
- The service must exist (`ha_api.has_service`), else `error`.
- `data` is merged under HA's own keys; `brightness_pct` is passed as given;
  `entity_id` always comes from the resolved entity, never from `data`.
- Exposure and sensitivity checks run BEFORE the call. A refusal names the reason
  in `message` in words a person can act on ("Office TV is not exposed to
  Assist; expose it in Home Assistant, or allow unexposed control under
  Config › People › Argyle.").
- Returns `status: 'success'` with `state_after`, or `error` when HA is
  unreachable (`ha_api.mode() == 'unconfigured'` short-circuits every action with
  "Home Assistant is not connected.").

## Where the identity comes from

The router passes `acting_member` (signed-in member in chat, the verified member
for voice, None for the admin control center) and `voice_context`. The tool
decides trust once:

```
trusted = (actor is None and source == 'admin')               # admin page, already behind the admin gate
       or (actor has an id, is not access.HOUSE, role in ('parent', 'adult'))   # signed-in chat; the wall panel chats as HOUSE and is never trusted
       or (voice_context and voice_context.level == 'verified' and verified role in ('parent','adult'))
```

Model arguments never carry identity (`execute_tool` already strips them).

## Wiring

- `services/agent_tools_v2.py`: declaration in `get_available_tools()` (every
  surface sees it), `house(...)` function, `handle_house` in `TOOL_HANDLERS`,
  `REGISTRY_EXCEPTIONS['house'] = 'Device control never runs from a mission.'`
  for now (missions get it later, by hand path review).
- `services/agent_router.py`: an `elif func_name == 'house'` branch that calls
  `_atv2.house(**args, acting_member=actor, voice_context=voice_context,
  source=source)`; `actor` resolved like the situations tools (driver in PWA,
  acting member in chat, verified member for voice).
- `services/voice_tools.py`: `house` added to `TOOLS`; dispatch calls
  `tools.house(..., voice_context=ctx, source='voice')`. `act` is recorded through
  `record_action` with label `Controlled a device` when it succeeds.
- `services/ha_api.py`: `get_entity_registry(ttl=300)` (ws
  `config/entity_registry/list`, keeps `entity_id, name, original_name, aliases,
  area_id, device_id, hidden_by, disabled_by, platform`), `get_exposed(ttl=60)`
  (ws `homeassistant/expose_entity/list` reduced to `{entity_id: bool}` for the
  `conversation` assistant), `get_device_registry(ttl=300)` (for device-inherited
  areas when `get_area_map` has no entry).
- `services/house.py` (new): catalogue build, fuzzy find, read shaping, history
  thinning, act with checks. Pure functions over `ha_api` calls so the tests stub
  `ha_api` only.
- `services/maps.py`: `reverse_geocode(lat, lon) -> str | None`.
- `services/cars.py` / `handle_manage_car`: `locate`.
- `models/schemas.py`: `house_control_unexposed: bool = False`.
- `services/settings_registry.py` + `templates/config.html` People tab Argyle
  block: the toggle.
- System prompt (`agent_router.py`): one sentence telling the model the house tool
  exists and that it must `find` before `act` when it does not hold an entity id.
- `homeassistant/README.md`: the "Chauffeur's own chat surfaces can only refuse"
  paragraph becomes "can control through the house tool, with these rules".

## Degradation

No HA (`mode() == 'unconfigured'`), HA unreachable, WebSocket refused: every
action returns `status: 'error'` with a plain message; nothing raises; find on a
stale states cache still works.

## Tests (written first)

`tests/test_house_tool.py`, stubbed `ha_api` (states, registry, exposure,
call_service capture, history), the real `house` function:

1. find ranks "office lamp" above "office tv" for query "office lamp"; aliases
   match ("column one" finds `light.front_porch_column_1` through its alias).
2. read returns brightness as percent and strips `access_token`.
3. act on an exposed light by a kid succeeds (lights are not sensitive).
4. act on an unexposed light is refused with the exposure sentence; with
   `house_control_unexposed` on it runs.
5. act on `lock.front_door` by a named-only voice is refused; by a verified
   parent voice it runs and reports `state_after`.
6. act on a garage cover by a signed-in kid is refused; by a parent it runs.
7. act with an unknown service is an error and nothing is called.
8. ambiguous read returns candidates, calls nothing.
9. history thins 500 points to at most 50 and counts changes.
10. no HA: every action returns the "not connected" error.
11. `execute_tool('house', ...)` runs the handler (the entry point is exercised).

`tests/test_car_locate.py`: `manage_car locate` with a stubbed tracker and a
stubbed `reverse_geocode`; a car with no tracker says so.

`tests/test_settings_registry.py` stays green (the new key is registered and the
template carries it).
