# House twin viewer: navigation by levels, and modes as icons (slice 2c)

**Status:** APPROVED by the user 2026-11-12. The design is theirs; the path chip, retiring the devices-only mode and moving Now/Day/Night into the drawer were proposed and approved.
**Scope:** the house twin VIEWER (`/house/twin`, wall panel, desk). The editor keeps its free camera and its own controls.

## Why
The user, on the wall panel, after slice 2a/2b:
- "I don't like the floor buttons."
- "I'm not sure free camera movement is the best for the house viewer, especially when thinking about a touch panel ... I know it is too free right now."
- "All is a misnomer currently. It really shows no visualizations."

The second floor never fades while zooming (the 2a distance bands), so you never reach the first floor without the button. Explicit levels replace distance bands, so that bug goes away rather than being patched.

The user expects to tune this after living with it: "It may be a little too restrictive in the way I described it." Every threshold below is therefore a named constant in one module, not scattered numbers.

## Levels
There are four levels. Each has its own camera, its own things to tap, and its own way up.

| Level | Camera | What shows | Tap | Pinch in | Pinch out |
|---|---|---|---|---|---|
| **House** | orbit around the centroid of all buildings, from the house's default height and angle | one large icon per building (its name below); attention devices | a building icon or the building itself → Building | → the building nearest the screen centre | (top) |
| **Building** | orbit around that building | the building; one floor icon per floor, stacked at each floor's height beside the building; attention devices | a floor icon → Floor | → its ground floor | → House |
| **Floor** | top-down on that floor's cutaway (2a's flat-cut walls), framed to the floor outline | room cards (2b); attention devices | a room card or a room's floor → Room | → the room under the pinch centre | → Building |
| **Room** | top-down, framed to the room | that room's device icons (all of them); attention devices elsewhere stay | a device: as today (tap toggles, hold opens the ring) | (bottom) | → Floor |

**Rules:**
- **Attention devices** (unlocked, open, alarm, leak and so on) show at every level and in every mode. They are the only devices shown above the room level. Tapping one jumps straight to its room and opens it.
- **Ordinary device icons** show only at the Room level. The 2b clump-to-badge logic still applies inside a room.
- **Transitions** are 400 ms eases (the 2b camera ease). The top-down switch blends from the orbit angle to straight down during the same ease.
- **Fades are per level, not per distance.** Focusing only moves the camera; nothing disappears except when you go down into a floor (user ruling 2026-11-12):
  - House and Building: everything stays as it is, roofs on. Focusing a building only moves the camera.
  - Floor: the parts above that floor peel away (the floors above, the roofs, and tree canopies or overhangs directly over it), and the cut walls are flat (2a). Nothing else fades.
  - Room: the same as Floor. The room is framed, and the other rooms stay as they are.
- **One-building houses** skip the House level: the default view is that building.
- **One-floor buildings** skip the floor icons: tapping the building goes straight to Floor.

## Gestures
- **Touch:** swipe and pinch.
- **Desk:** drag, wheel, click.

| Level | Swipe / drag | Pinch / wheel |
|---|---|---|
| House | orbit (yaw, plus a limited pitch band) around the centroid | moves between levels; within a level, a small zoom range without changing level |
| Building | orbit around the building | as above |
| Floor | ignored (top-down, fixed framing) | between levels |
| Room | **pans room-to-room:** a swipe snaps to the neighbouring room in that direction; at the building's edge a swipe toward no room is ignored | between levels |

- **No free pan** at House or Building.
- **Level change on pinch:** a pinch past the level's zoom range (a named threshold) commits the next level. Below the threshold it springs back.
- **The neighbouring room** in a swipe direction is the room whose centroid lies within ±45° of the swipe direction and is nearest. Ties go to the larger shared wall.

## The path chip (wayfinding)
- **Top-left:** a small chip reading "House › Main House › 2nd floor › Kitchen". Tap any part to jump to that level.
- It shows where you are and is the explicit way up on a mouse or a panel.
- On a one-building house, "House" is omitted.

## Controls
- **Removed from the viewer:** the floor buttons, and the camera buttons (Front, Porch, Rear, Top).
- **Mode icons**, centred at the top, are the only controls besides the path chip. Each has a tooltip (hover on desk, long-press on touch) and an accessible label.
- **The Now/Day/Night time preview** stays reachable: it moves into the house settings drawer (it is a preview, not navigation).
- **The glance bar, idle face, Argyle orb and shelf** are unchanged.

## Modes
| Mode | Icon (Lucide) | Shows |
|---|---|---|
| **All** (default) | layers | every visualization at once: lights light rooms; energy ribbons and solar; rooms tinted by temperature; locks, doors and windows highlighted by state; camera viewing cones |
| Lights | lightbulb | lights only |
| Climate | thermometer | temperature tint and thermostats |
| Energy | zap | ribbons, solar, chargers and cars |
| Security | shield | locks, doors, windows, alarm and camera cones |

- **Today's "All"** (devices with no visualizations) is retired. Devices still appear at the Room level in every mode.
- **Camera viewing cones** (new): a translucent frustum from each placed camera, along its facing, about 20 ft long. It draws in All and Security.
- **Cost:** the temperature tint, ribbons, highlights and cones are cheap. Only real-time lights cost GPU, and they already scale by tier. All mode needs no special reduced form.

## What carries over unchanged
- Room cards (2b), clump badges (2b), the device ring and controls, the camera grid rule, state colours (v2.499.807), the glance bar, and the idle face.
- **Idle face:** idle orbits at the House level and wake restores the exact level (v2.499.810's pin fix extends to levels).

## Fixed alongside
- **Sensor marker labels show raw floats** ("EV Charger · 21.0717598347897..."). Round them by the entity's display precision or unit (watts to whole numbers, kW to 2 dp, temperatures to 1 dp, else 2 significant decimals).

## Out of scope
- The editor's camera and controls.
- The lot, terrain and objects (slices 3 and 4).
- The solar conduit animation (queued with energy polish).

## Build order
1. **2c-1, levels, camera and the path chip:**
   - a level state machine;
   - gestures;
   - transitions;
   - per-level fades;
   - the path chip;
   - room-to-room swipe;
   - attention-only devices above Room;
   - floor and camera buttons removed;
   - the label rounding.
2. **2c-2, mode icons and the new All:**
   - the icon strip;
   - the All composition;
   - camera cones;
   - the time preview moved to the drawer.

## Approved calls
1. The path chip, top-left.
2. Today's devices-only mode is retired (devices show at Room level in every mode).
3. Now/Day/Night moves into the settings drawer.
4. Focusing a building only moves the camera; nothing ghosts (user ruling).
