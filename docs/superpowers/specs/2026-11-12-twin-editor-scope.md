# House twin editor: scope against Live Home 3D

**Status:** agreed with the user, 2026-11-12.

The user said: "Sometimes it feels like I am just asking for a stripped down version of Live Home 3D." That is roughly right, and it is a fine thing to be. This list keeps the "stripped down" honest.

**The test for any feature:** does it make the house accurate enough to place and run real Home Assistant devices, or to read the house at a glance? If not, it is out, or left to imported models.

## Build: core to the twin

**Structure**
- Walls, rooms, open-plan splits, levels. *Shipped.*
- Sunken and raised rooms. *Shipped.*
- Doors and windows, including models fitted to openings. *Shipped.*
- Roofs. *Shipped.*
- **Stairs between floors and steps between floor heights.** *Not built.* Sunken rooms already record where a step is needed.
- **Railings on porches and decks.** *Not built.*

**Site**
- Terrace pads with layering. *Shipped.*
- Foundations for buildings. *Shipped.* Porches: *in progress.*
- **Retaining walls on sharp pad edges.** *Planned.*
- **Ground features drawn as outlines:** beds, patios and other hardscape, pools. *Planned.*
- **Paths drawn along a line with a width:** sidewalks, paver paths, driveways. *Planned.*
- Fences, plants and trees. *Shipped.*
- **Lot features as rooms** (pool area, fire pit, grill), so they can hold devices. *Planned.*

**Objects**
- One object model with size, turn and properties. *Shipped.*
- glTF, Collada and KMZ import, with automatic lighter versions. *Shipped.*
- Car models. *Shipped.*
- Lamps linked to Home Assistant lights. *Shipped.*

**Light and time**
- The real sun and moon for the house's location and time. *Shipped.*
- Home Assistant lights as real-time and baked light. *Shipped.*

**Views**
- Viewer navigation: house, building, floor, room. *Shipped.*
- Mode icons and the new All mode. *Next.*
- The editor's free camera. *Shipped.*
- Dimensions and measuring in the editor. *Exists. Extend if needed.*

**The twin's own** (not in Live Home 3D)
- Home Assistant device placement and controls.
- Live modes: Lights, Climate, Energy, Security.
- Energy ribbons and solar.
- Cars and chargers.
- The glance bar and idle face.
- Argyle.

## Keep light: a little, on purpose

- **Materials:** choose from the kit's materials and tint them. No material editor and no texture painting.
- **Furniture:** a small built-in library; anything specific comes in by import. No large catalogue.
- **Interior finishes:** floor and wall material per room. No wallpaper, curtain or trim designers.
- **Landscaping:** placed plants and trees with sizes. No growth or seasons simulation.
- **Custom shapes:** paths and outlines cover the ground. No general solid-modelling tools: boolean cuts, lofts, free mesh editing.

## Skip: not the twin's job

- Photoreal rendering, ray tracing, video and walkthrough exports, VR.
- Printable 2D plans, elevations, sections and construction drawings.
- Cost estimates and bills of materials.
- A built-in 3D Warehouse browser, and SketchUp (.skp) files. The user ruled this out, 2026-11-12.
- Export to other 3D formats.
- First-person walk mode. The viewer uses levels navigation instead.

## How to use this list
- **New asks:** a new ask that fits "Build" goes ahead.
- **Keep light:** an ask in "Keep light" gets its smallest useful form.
- **Skip:** an ask in "Skip" is named as out of scope, with the reason, before any work. The user can move it.
- **Changes:** add rows as decisions are made; this document is the record.
