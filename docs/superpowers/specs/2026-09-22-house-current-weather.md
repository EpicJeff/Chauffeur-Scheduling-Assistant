# Outdoor weather and sun

The house state window reads current state/temperature from the configured Home
Assistant weather entity, or the first weather entity when none is configured.
It does not use the daily forecast to paint current outdoor conditions.

Day/night uses the existing `home_board.sun_theme` resolver with zero offsets:
the same `sun.sun` source as the theme, using physical sunrise/sunset rather than
the theme's user-adjustable early/late offsets. State includes the next transition.
The renderer no longer uses fixed browser-clock hours; `?day=1` still pins previews
to daylight. The visible page polls once a minute and refreshes when restored.
Unavailable sun data uses the resolver's conservative dark fallback. Unavailable
weather clears precipitation rather than inventing a forecast observation.

The existing sky paint responds to current condition. Night precipitation/overcast
does not show stars. Rain uses line segments; snow/hail uses points; mixed weather
shows both. Fog fades the distance. No accumulation or lightning flashes are modeled.

Effects use fixed buffers: 300 particles at high, 120 at medium, none at low/2D.
They appear outdoors, with a dry central footprint around the house; rooms stay
clear. They share the existing on-demand frame loop, stop when the page is hidden,
and remain static for reduced-motion users. Fog needs no animation. Buffers and
materials are disposed on WebGL context loss. No new provider, setting, or API call
from the browser was introduced.

## Exterior framing and visible lighting (2.499.154)

The exterior orbit keeps its horizontal radius and eight stops, but lowers its
height from 31 to 18 and raises the aim from 4 to 6.5. The distant painted skyline
is a thin 24-high backdrop rather than a 90-high wall, exposing sky above rooftops.
Portrait exterior views widen vertical FOV to preserve horizontal house framing;
room lenses remain unchanged. Neighborhood distance and object caps are unchanged.
Portrait room markers stay below the clock/event card and above the chat controls.

Cloud cover reduces direct sunlight to 58%; rain, snow, fog and storms reduce it
to 32% and slightly reduce sky fill. Day/night factors combine with those values
without accumulating over repeated updates. Clearing weather restores the original
light levels. This makes conditions visible on roofs and walls as well as the sky.
