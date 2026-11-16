# Effect fixtures, second set

Date: 2026-11-16. Status: asked for by the user 2026-11-15 ("We can do more effects. The ones you listed are good. One I just thought of is spa jets. An effect or just visualization for when a pool or spa heater is on would be good too."). The details below marked as Claude's calls were not put to the user one by one.

This extends the effect fixtures shipped in v2.499.888. Everything locked there still holds: an effect is placed like a light fixture, a switch decides whether it runs, a sensor between a minimum and a maximum drives its size, the low tier shows a still pose, water effects are unlit shaders that take the scene's light level, there is no new stream, and the cap is 64 effects.

## New effect types

| Type | Label | Shape | Size means | Default size (ft) |
|---|---|---|---|---|
| `spa_jet` | Spa jet | point | how far the plume reaches | 0.5 to 2.5 |
| `steam` | Steam | point | how high the vapour rises | 1 to 4 |
| `sheer` | Sheer descent | line | how far the sheet throws | 0.5 to 3 |
| `deck_jet` | Deck jet | point | how far the arc throws | 2 to 8 |
| `mist` | Mist | point, line | how far the mist drifts down | 1 to 6 |

### Spa jet

A jet in the wall of a spa or pool, below the waterline. Placed as a point on or near the water body's edge. It aims at the centre of the water body it stands in (the nearest body within about 3 ft when it is placed on the coping). It shows an aerated plume under the surface, running from the wall toward the centre, and a patch of boiling water where the plume breaks the surface. The surface patch is a ripple source in the receiving water, the same way a bubbler is. Placed away from any water it draws nothing and the card says why.

### Steam

Vapour rising off warm water: the picture of a heater that is running. Placed as a point. When the point is on a pool or spa, the steam covers that whole water body: slow wisps that rise, drift and thin out. When it is not on water, it is a single local plume about 3 ft across (a kettle, a vent). The sensor is meant for the water temperature: denser and taller as it climbs. Steam casts no light and makes no ripples.

### Sheer descent

A thin, smooth sheet of water falling in an arc from a line, the glassy kind that comes out of a slot in a wall. It differs from the waterfall, which is broken white water: the sheer is clear, holds together, and only turns white where it lands. It uses the waterfall's placement, facing and Drop rules, and is a ripple source where it lands in water.

### Deck jet

A thin laminar arc of water from a point on the deck into the pool. It aims at the nearest pool or spa water within about 12 ft and lands at the throw distance along that line, clamped so it lands inside the water. It is a ripple source where it lands. With no water in range it arcs along the fixture's facing-free default (toward the lot centre) and lands on the ground.

### Mist

A fine cooling mist, the patio kind. A point is one nozzle; a line is a run of nozzles. The mist drifts down and thins out over the drop distance. No ripples, no light.

## Heaters and other things that are not plain switches

The switch field accepts more domains, each with its own meaning of "on":

| Domain | The effect runs when |
|---|---|
| `switch`, `light`, `input_boolean`, `fan` | state is `on` (unchanged) |
| `binary_sensor` | state is `on` |
| `climate` | `hvac_action` is `heating` or `preheating`; when no `hvac_action` is reported, the mode is a heating mode and the current temperature is below the setpoint |
| `water_heater` | the state is not `off`, and the current temperature is below the setpoint when both are reported (a heater with no temperatures reported counts as on while its state is not `off`) |

A stale or unavailable entity means off, as today. This is how a pool or spa heater drives steam: link the heater as the switch and the water temperature as the sensor.

## Sensor attributes

The sensor field can read an attribute of an entity, not only its state. A new optional field `sensor_attribute` names it. With an attribute named, the sensor entity may be from any of: `sensor`, `number`, `input_number`, `fan`, `climate`, `water_heater`, `light`, `cover`, `valve`. Examples: a fan's `percentage`, a heater's `current_temperature`, a light's `brightness`. Without an attribute the three existing domains read their state, as today. A missing or non-numeric attribute behaves as a non-numeric state does today: the effect runs at its own Level.

The effect card shows an Attribute box under the sensor, empty by default, with the entity's numeric attributes offered when Home Assistant is reachable and free text otherwise.

## Rules that carry over

- Low tier: a still pose at the right size, no animation.
- Water effects are unlit and take the `light` uniform, so they do not glow at night.
- Ripples: at most eight sources per water body; only water that receives an effect gets the extra shader.
- No Home Assistant: an effect with no switch and no sensor still runs.
- An effect adds its own marker only when its switch has no other marker in the house.
- Its entities ride the existing live stream.
- The editor rail's Add effect flow, the card, and the three ops stay as they are; the new types appear in the type list for the shapes they allow.
- A house with none of the new types draws exactly as before.

## Looks

The user is a game developer of long standing; these must read as competent real-time effects, not placeholders. Steam and mist are soft, layered, slowly scrolling noise with soft edges and depth fade against what is behind them, not hard-edged cards. The sheer descent and deck jet are clear water with a bright edge and a little refraction-like distortion, white only where they break. No `transmission` (tests forbid it), and no added render pass.

## Not in this slice

- The fire pit as an effect fixture. The fire pit keeps its own flame and light (locked); making it sensor-driven touches the bake and is its own piece of work.
- Pool or spa water changing colour in Climate mode when its heater runs. That waits for the Climate mode change being built alongside this.
- Sound.

## Tests

- Server: each new type validates with its shapes and default sizes, the widened switch and sensor domains, `sensor_attribute` rules, old records load unchanged.
- Driver under Node: "on" for each domain including every `climate` and `water_heater` branch, stale and unavailable, attribute reads, missing attribute.
- Visuals under Node: each new type builds, sizes to its pose, freezes on the low tier, carries the `light` uniform, has no `transmission`; a spa jet off water draws nothing; steam on water covers the body; sheer and deck jet and spa jet register ripple sources where they meet water, steam and mist do not.
- Editor under Node: the type list per shape, the Attribute box, one op per change.
- An untouched house and a house with only the four original types are unchanged (existing pins stay green).

## Calls made by Claude, not by the user

- The five types, their shapes, what size means and the default sizes.
- A spa jet aims at the centre of its water body; a deck jet aims at the nearest water.
- Steam on water covers the whole body.
- A heater is linked through the switch field by widening its domains; `binary_sensor` is added too.
- Sensor attributes are a separate optional field.
- The fire pit is left out.
