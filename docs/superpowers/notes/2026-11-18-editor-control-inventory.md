# House editor control inventory (input to slice 4, "the shell")

Date 2026-11-18, branch `editor-slice4`. Required by the overhaul spec (`docs/superpowers/specs/2026-11-16-twin-editor-overhaul-design.md`, Slice 4): every control that exists today, with a home in the new layout. Read-only survey of `chauffeur/templates/house_editor.html` (HE), its include `nav.html`, every file in `chauffeur/static/twin/editor/` and `static/twin/edit_timing.js`. Paths below are relative to `chauffeur/static/twin/editor/` unless prefixed. Line numbers were checked against the branch at 7fdcfda5.

**Home codes.** `TB:sel` (select and move group), `TB:struct` (wall, room, door, window, roof), `TB:yard` (yard, pool, plants), `TB:fix` (light, effect, device, measure), `TB:undo`, `TB:floor` (floor picker), `TB:view` (view picker), `Menu` (toolbar menu button), `Props(kind)` (Properties, for that selection), `Scene` / `Layers` / `Library` (dock tabs), `History` (folded section under Properties), `Dlg:name` (centred dialog), `Status` (status line), `RC(kind)` (right-click menu on that thing, in the view and in lists), `Gen` (generation bar), `View` (stays in the 3D view: gizmos, handles, labels), `Keys` (keyboard, unchanged), `Prompt` (shared control-centre prompt, unchanged). A `?` marks a home placed without confidence; each one is in "No obvious home" below.

## 1. Page chrome (nav.html, included at HE:79)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Site nav (all app links) | nav.html (whole) | app navigation | always | stays above the editor (page chrome) |
| Material library (link) | nav.html:314 | opens /house/library | always | Menu (and a link in the Library tab) |
| Settings gear `#page-settings-gear` | nav.html:316 | opens the page's settings drawer | never on this page: the editor has no drawer, the gear stays hidden | Menu > Settings (Dlg:settings) |

## 2. Top bar `#editor-top` (HE:88-112)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Library (link, new tab) | HE:90 | opens /house/library | always | Menu; duplicate of nav link |
| Status text `#editor-status` | HE:91 (dimensions.js:108-116 swaps in drag problems) | shows state and drag problems | always (display) | Status |
| Save state `#editor-save-state` | HE:92 | Saved / Saving | always (display) | toolbar save state + Status |
| Status chip: Working / Waiting on you / $ so far / about $ / Lights wait to re-bake | status_chip.js:2-18 | display, tooltip on the last | as state allows | Gen (spend while a run is live); `?` spend total outside a run |
| Check this step | editor.js:643 (shown 284) | opens the check card at the pause | build paused, pause card dismissed | Gen |
| Resume | editor.js:476 (state 285-286) | rechecks spend, resumes the build | build stopped or at a spend checkpoint | Gen `?` (bar is "only while a generation runs"; a stopped build is not running) |
| Stop | editor.js:490; moved into chip status_chip.js:8 | stops the build | build running, paused or at checkpoint | Gen |
| Houses | houses.js:81 | opens the Houses dialog | always | Menu > Open / Save (Dlg:save-open) |
| Menu (details/summary) | HE:98 | opens the menu | always | Menu button |

## 3. Steps strip `#editor-steps` (built steps.js:5-10, handler editor.js:53-56)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Your files · now/done/not yet | steps.js:5-10 | opens Your place at that step | always | `?` Dlg:your-place (step tabs inside it) |
| Your lot | same | same | always | `?` same |
| Build | same | same | always | `?` same |
| Check it (N) | same; editor.js:53-56 | closes Your place, opens the check card | always | `?` Gen while running; Status count otherwise |
| Link to Home Assistant | same | opens Your place at the Link step | always | `?` Dlg:your-place |

## 4. Menu `#editor-menu` (HE:98-110)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Your place | editor.js:499 | opens step Your files | always | Menu |
| Upload more | editor.js:503 | opens step Your files (same as Your place) | always | Menu (merge with Your place, see Removed) |
| Art director | editor.js:539 (disabled 291, 294) | compares 4 views with photos, up to 5 rounds | buildings exist, idle | Menu (starts a generation: Gen shows) |
| Advanced: edit the plan file | editor.js:560 | opens the plan JSON editor (in the Argyle panel today) | idle | Menu, editor moves to Dlg:plan-file |
| Start over | editor.js:621 (Prompt 625-627) | clears house, history, drawings, photos | no build, can edit | Menu |
| Reset spend total | editor.js:605 (Prompt type "reset" 610-612) | clears the spend total | idle | Menu (or Dlg:settings) |
| Show edit timing (toggle) | editor.js:500 -> edit_timing.js:74 | shows the timing overlay (localStorage) | always (`?timing=1` forces on) | Menu (or Dlg:settings) |
| Send timing report | editor.js:500 -> edit_timing.js:79 | posts the timing report | always | Menu |
| Download build record | editor.js:525 (hidden 281-282) | downloads house-build-record JSON | ready and signed in | Menu > Export |
| House preview (link) | HE:109 | goes to /house/twin | always | Menu |

## 5. Front door `#editor-front-door` (HE:82-86)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Add plans and photos | editor.js:504 | opens Your files | empty house (editor.js:276-277) | `?` empty-state (Dlg or dock) |
| Draw it myself | editor.js:505-524 | makes "My house" + L1, arms Draw wall | empty house | `?` same |

## 6. Left tool rail `#editor-rail` (HE:113-119; all removed as a column, each tool moves)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Select | HE:114; scene_tools.js:508-509 | Select tool | always | TB:sel |
| Move | same | Move tool (gizmo) | always | TB:sel |
| Turn | same | Turn tool | always | TB:sel |
| Scale | same | Scale tool | always | TB:sel |
| Draw room | HE:114; draw.js:202-205 | room tool (drag rect or click corners) | needs a floor | TB:struct |
| Draw wall | same | wall chain tool | needs a floor | TB:struct |
| Split room | same, guard draw.js:101 | split tool, refused without a room | room selected | `?` RC(room) + Props(room) |
| Add door | same | door placement | always | TB:struct |
| Add window | same | window placement | always | TB:struct |
| Add anchor | same, choice draw.js:112-117 | asks Light/Switch/Outlet/Fan/Camera/Sensor, arms | always | `?` TB:fix > device |
| Add stair | same, draw.js:102-111 | stair draft in the piece card, click start/end | floor above exists | `?` TB:struct (overflow) |
| Add solar zone | same, draw.js:118-121 | exterior view, click a roof plane | always | `?` TB:struct > roof submenu + RC(roof) |
| Add meter | same | wall-face placement | always | Library > Items (already there, library.js:362-366) `?` |
| Add electric panel | same | wall-face placement | always | same `?` |
| Add charger | same | wall-face placement | always | same `?` |
| Add parking spot | same | floor/ground placement 9x18 ft | always | same `?` |
| Roof | roof_tools.js:104 | roof mode, shows roof choices | needs a floor | TB:struct |
| Add floor | draw.js:214-224 | Prompt name, add level above | needs a floor | TB:floor ("Add floor" in the picker) |
| Delete | draw.js:207-213 | deletes selection | always | RC(any) + Props(any) Delete + Delete key |
| Undo | history.js:64 | undo | step exists, can edit | TB:undo |
| Redo | history.js:65 | redo | redo exists | TB:undo |
| Sheet (toggle) | scene_tools.js:177-180, 511 | drawing underlay for this floor | always | `?` Layers ("the plot plan" row) or TB:view |
| Library | library.js:464-468 | toggles the library panel | always | Library tab |
| Add effect | editor.js:746 -> fixtures.js:235 | Prompt effect type, then Point/Line | can edit, idle | TB:fix > effect |
| Ground and yard (JS-made `#rail-ground`) | terrain_tools.js:478 | opens the terrain card menu | always | TB:yard > yard (menu of yard drafts) |
| (side effect) any rail click closes terrain card / leaves roof mode | terrain_tools.js:479-482; roof_tools.js:113 | — | — | keep on toolbar clicks |

## 7. Viewport bar `#editor-cameras` (HE:138-149)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Top / Front / Back / Orbit | HE:139-141; scene_tools.js:512-516 | sets the camera (Top frames the floor) | always | TB:view |
| Lighting: Day / Night / Now / Unlit (fast) | HE:144-146; lighting.js:21-24 | viewport lighting, per device (localStorage) | always | TB:view |

## 8. Floors panel `#editor-floors` (HE:176; drawFloors scene_tools.js:201-241)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Floor name button (per level) | scene_tools.js:209-210 | shows that level, selects it | levels exist | TB:floor |
| Eye toggle (per floor) | scene_tools.js:211-219 | shows/hides that level | levels exist | TB:floor + Layers/Scene eye (slice 5) |
| All floors | scene_tools.js:223-229 | exterior view, all levels | always | TB:floor |
| Change this floor | scene_tools.js:231-235 | selects the level (level card) | always | Props(level) via Scene row / breadcrumb |
| Change the house | same | selects the building | always | Props(building) via Scene row / breadcrumb |

## 9. Mode strips: draw, device, roof (HE:150-162)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Draw note `#draw-note` | HE:151; draw.js:123 | what the tool expects | draw tool armed | Status |
| Cancel drawing | draw.js:206 | ends the draw tool | draw tool armed | Status (+ Esc) |
| Device note `#device-note` | HE:155; fixtures.js:229 | what the mode expects | fixture/device mode | Status |
| Cancel placement / Done (`#device-cancel`, relabelled) | device_placement.js:199; fixtures.js:229, 532 | ends placement; Done saves a complete line | fixture or device mode | Status (+ Esc, Enter) |
| Roof over this | roof_tools.js:105-109 | roof over the selected building (Shift-click room set) | roof choices | TB:struct roof submenu + RC(building, room) |
| Draw roof area | roof_tools.js:110 | click corners, close on first | roof choices | TB:struct roof submenu |
| Add dormer | roof_tools.js:111 | click a sloped roof | roof choices | TB:struct roof submenu + RC(roof) + Props(roof) |
| Roof note | HE:161 | roof mode instructions | roof mode | Status |
| Cancel roof editing | roof_tools.js:112 | leaves roof mode | roof mode | Status (+ Esc) |

## 10. Piece card `#piece-card` (cards.js:68): every selection

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Close | cards.js:163 | deselects | any selection | Props back arrow / Esc |
| Ask Argyle about this | cards.js:343; panel.js:84-88 | prefills the Argyle input | any selection | Props(any) + RC(any) `?` (depends on Argyle home) |
| Looks right | cards.js:345 | accepts a ghost / clears roof flags | ghost piece or flagged roof | Props(that kind) |
| Delete | cards.js:348 (remove 350-366, Prompt) | deletes | any selection | Props(any) + RC(any) |
| Material line: Change | cards.js:178 -> library pick | opens the Library in picking mode | wall faces, room floor/ceiling/walls, roof, opening parts, stair, cabinets | Props(kind) slot row ("Use selected", slice 6) |
| Material line: Clear | cards.js:182 | clears the override | override set | Props(kind) slot row |
| Material line: Clear for this floor / for the building | cards.js:185 | clears inherited level/building material | inherited | Props(kind) slot row |
| Enter in any text field | cards.js:324 | saves now | any card field | Props (unchanged) |

## 11. Piece card by kind (cards.js, shelves)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Split wall | cards.js:165 -> scene_tools.js:32-55 | arms a click on the wall | wall | Props(wall) + RC(wall) "split here" |
| Height / Thickness (text) | cards.js:19, 268-325 | sets wall size | wall | Props(wall) |
| Exterior (checkbox) | cards.js:285 | exterior flag | wall | Props(wall) |
| Width / Height above floor / Top of opening / Panels / Distance along the wall | cards.js:268 loop | opening size and place | door, window | Props(opening) |
| Kind (Window/Door/Sliding/Folding/Open passage/Garage door) | cards.js:274-284 | opening kind | door, window | Props(opening) |
| Hinge / Swing | object_shelf.js:52-75 | hinge side, swing | door, window | Props(opening) |
| Door style / Windows (garage) | object_shelf.js:53 | garage door look | garage door | Props(opening) |
| Model grid: Generated + one per model | object_shelf.js:85-97 | opening model | door, window | Props(opening) slot row (slice 6) |
| Name / Floor height (text) | cards.js:268 loop | room name, floor offset | room | Props(room) |
| Down 0.5 ft / Up 0.5 ft | cards.js:326-334 | nudge floor offset | room | Props(room) |
| Foundation (Posts/Enclosed/Solid) | porch_foundation_shelf.js:33, 45-51 | porch foundation | porch room | Props(room: porch) |
| Post width / Post shape / Post spacing / Floor overhang | porch_foundation_shelf.js:34-37 | porch post settings | porch room | Props(room: porch) |
| Posts and beam / Skirt / Solid base material slots | porch_foundation_shelf.js:55-59 | porch materials | porch by type | Props(room: porch) |
| Kind (Hip/Gable/One slope/Flat) | cards.js:274 | roof kind | rect roof, dormer | Props(roof) |
| Pitch / Wall height under the roof / Overhang (text) | cards.js:268, 336 | roof dims | rect roof, dormer | Props(roof) |
| Left/Right or Front/Back end (Gable/Hip/Clipped) | cards.js:266-275 | end per ridge | rect gable/hip roof | Props(roof) |
| More (details): Ridge / Low side | cards.js:264, 275, 337-339 | ridge axis, shed low side | rect roof | Props(roof) (folded) |
| Edge N: Sloped/Gable/Clipped buttons | cards.js:198-200 | opens roof edge sub-card | polygon roof | Props(roof) -> child page "Edge N" (breadcrumb) |
| Add dormer (card) | cards.js:201 -> roof_tools addDormer | dormer mode | polygon roof | Props(roof) + RC(roof) |
| Solar ribbon starts here | cards.js:205 | set_solar_source | roof, solar zone | Props(roof, solar zone) |
| Back to roof | cards.js:375 | back from edge sub-card | roof edge | Props back arrow |
| Sloped / Gable / Clipped toggles; Pitch | cards.js:386-403 | roof edge setting | roof edge | Props(roof edge) |
| Zone rectangle / Panel width / Panel height / Gap / Setback / Panel count / Production sensor | cards.js:210-220 | solar zone fields | solar zone | Props(solar zone) |
| Orientation (portrait/landscape) | cards.js:212-213 | panel orientation | solar zone | Props(solar zone) |
| Name / Position / Rotation / Fixed base | cards.js:268-298, 271 | building fields | building | Props(building) |
| Foundation mode / Offset / Thickness | foundation_shelf.js:11-36 | foundation (live preview) | building | Props(building) |
| Slab material slot | foundation_shelf.js:39-51 | slab material | building | Props(building) |
| House materials: 26 slots in 7 groups (Walls and floors, Trim, Openings, Porch and stairs, Roof and ceilings, Fixtures, Yard) | house_materials.js:12-38 (mounted cards.js:226) | house-wide materials | building | Dlg:house-materials (opened from Menu and from Props(building)) |
| Name / Height above ground / Ceiling | cards.js:21, 268 | level fields | level (via Change this floor) | Props(level) |
| Width / To level / Style / Rails | stair_shelf.js:8-27 (cards.js:166) | stair fields | stair; Add stair draft | Props(stair); draft `?` |
| Turn / Size / Distance from surface | cards.js:23, 268, 336 | hosted item transform | item | Props(item) |
| Host coords: Across room / Along room / Along surface / Height on surface / Roof edge | object_shelf.js:34-49 | move on host | item, anchor without device | Props(item, anchor) |
| Object kind (furniture/decor/plant/door/window/car/lamp/other) | object_shelf.js:51 | object kind | item, anchor, planting, furniture | Props(object) |
| Name / Yaw / Pitch / Roll / Scale | object_shelf.js:52-75 | object fields (Pitch, Roll unhosted only) | object kinds | Props(object) |
| Mirror left-right / Mirror front-back | object_shelf.js:52-75 | mirror_x / mirror_y | object kinds | Props(object) + RC(object) |
| Material tint (text) / Casts shadow / Visible in / Height above surface | object_shelf.js:52-75 | object render fields | object kinds | Props(object) |
| Advanced (details): X, Y, Z scale | object_shelf.js:29, 78 | scale_axes | object kinds | Props(object) (folded) |
| Emissive / Glow colour / Linked HA light | object_shelf.js:11-24, 76 | lamp glow + entity | lamp objects | Props(object: lamp) |
| Position x / Position y | object_shelf.js:34-49 | yard item position | site planting, furniture | Props(plant, furniture) |
| Distance from surface | cards.js:23 | offset | anchor (incl. meter/panel/charger/parking) | Props(anchor) |
| Charger: Name / Power entity / Dedicated car | equipment_shelf.js:60-92 | charger fields | charger anchor | Props(charger) |
| Parking: Assigned car / Width / Length / Turn | equipment_shelf.js:61 | parking fields | parking anchor | Props(parking) |
| Edit {feature} materials (per room feature) | cards.js:233-240 | selects that pool feature | yard room with features | Props(yard room) child link (breadcrumb) |
| Move east / Move north (ft) | cards.js:251-261 | nudge yard piece | yard pieces | Props(yard piece) |

## 12. Yard shape shelf (site_shape_shelf.js, in the piece card cards.js:242)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Name | site_shape_shelf.js:83-84 | yard room name | yard room | Props(yard room) |
| Home Assistant area (text) | site_shape_shelf.js:85 | ha_area | yard room, no HA | Props(yard room) |
| Make this a room | site_shape_shelf.js:88-98 | make_yard_room | pool, hardscape, path, bed, fire pit, spa | Props(those) + RC(those) |
| Fuel / Body / Top / Height / Fire glass colour / Linked switch | site_shape_shelf.js:103-109 | fire-pit fields | fire pit | Props(fire pit) |
| Material select (Mulch/Concrete/Pavers/Grass/Stone/Wood) | site_shape_shelf.js:111-112 | base material | bed, hardscape, edge, pool | Props(yard piece) |
| Material slots per part (fire pit, hardscape, bed, pool, spa, edge, fence parts) | site_shape_shelf.js:14-32, 114-119 | part materials | per kind | Props(yard piece) |
| Surface (Solid/Pavers), Layout, Paver length/width, Gap, Rotation, Edges, Joints, Lay | site_shape_shelf.js:122-132 | paver settings | path (pavers) | Props(path) |
| Width / Corner style / Corner radius / Smooth curve / Edging | site_shape_shelf.js:134-138 | path shape | path | Props(path) |
| Centre X / Centre Y | site_shape_shelf.js:140 | moves shape | every yard shape | Props(yard piece) |
| Radius / Angle (round fire pit) | site_shape_shelf.js:142-143 | size, angle | round fire pit | Props(fire pit) |
| Angle / Size (%) / Width, Depth (or X/Y span) | site_shape_shelf.js:147-157 | rotate, scale, size | per kind | Props(yard piece) |
| Advanced (details): X scale / Y scale / Point N X,Y / Remove corner N | site_shape_shelf.js:56, 158-168, 215 | per-vertex edit | yard shapes | Props(yard piece) (folded) |
| Pool depth / Coping | site_shape_shelf.js:172-173 | pool fields | pool | Props(pool) |
| Add tanning ledge / Add steps / Add spa | site_shape_shelf.js:174-178 -> terrain draft | draws a feature | pool | Props(pool) + RC(pool) |
| Pool feature disclosure (nested shelf) | site_shape_shelf.js:180-184 | edits feature | pool with features | Props(pool) -> child page per feature |
| Delete (pool feature) | site_shape_shelf.js:185-189 | deletes feature | pool feature | Props(feature) + RC(feature) |
| Water depth / Treads / Entry edge / Bench seat depth / Bench width / Mode / Raise above deck / Spillover | site_shape_shelf.js:193-208 | feature fields | ledge, steps, spa | Props(feature) |
| Fence type / Height / Style | site_shape_shelf.js:211-213 | fence fields | fence | Props(fence) |

## 13. Material slot (material_slot.js; used by house materials, foundation, porch, yard shelf, pad edges)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Change | material_slot.js:31-67 | opens inline chooser | not read-only | Props slot row: "Use selected" + swatch (slice 6) |
| Use default | material_slot.js:46 | clears to default | chooser open | Props slot row: clear |
| One button per material (quick picks first) | material_slot.js:47-55 | sets material | chooser open | Library tab selection + "Use selected" |
| Override tint (colour input) / Clear override | material_slot.js:57-61 | tint | material set | Props slot row (slice 7 puts tint in the row) |
| Cancel | material_slot.js:63 | closes chooser | chooser open | gone with the inline chooser (see Removed) |

## 14. Home Assistant section (ha_link.js; in the piece card for room, yard room, building, anchor; also Your place Link step)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Home Assistant area (select) | ha_link.js:325-352 | link room to HA area | room, yard room, HA up | Props(room, yard room) |
| Use (Suggested: area) | ha_link.js:359 | link suggested area | no area, suggestion exists | Props(room, yard room) |
| Areas with no room: one button per area | ha_link.js:385-392 | choose the room for an area | building, unlinked areas | Props(building) |
| Device row drag (row; touch: grip) | ha_link.js:111, 150-154 -> device_placement.js:153-193 | drag device onto the house | device rows | Props(room...) row drag into View; also Scene `?` |
| Show as (Device with controls / Separate entities) | ha_link.js:38-46, 118 | display mode | device with controls | Props(device) |
| Controls (N) (details) + Hide/Show per entity | ha_link.js:120-125 | hide one control | device with controls | Props(device) |
| Pick a spot | ha_link.js:80-96, 130 | place on door/anchor, or arm wall/ceiling | device row | Props(device) + TB:fix > device |
| Blink | ha_link.js:98-105, 131 | identify light | light device | Props(device) |
| Hide / Show | ha_link.js:132-134 | hide device in house view | device row | Props(device) + RC(device) |
| Remove | ha_link.js:135-137 | unplace device | placed | Props(device) + RC(device) |
| Height above ground | ha_link.js:140-148 | yard device height | yard device | Props(device) |
| Serves / Rooms-Except checkboxes / Use default | ha_link.js:198-235 | climate zone | climate device | Props(device: climate) |
| Group header: Show as + Hide/Show parent | ha_link.js:247-252 | entity group | split device | Props(device) |
| Hidden (N) (details) | ha_link.js:259-260 | hidden devices list | hidden exist | Props(room...) folded; Layers/Scene dimmed rows (slice 5) |
| Placed devices with no room | ha_link.js:395-399 | stray device rows | building, strays | Props(building) |
| Remove (anchor device) | ha_link.js:286-288 | unplace | anchor with device | Props(anchor) |
| Fixtures / Fixtures and camera view | fixtures.js:298-302 (in row, ha_link.js:159) | opens device fixtures card | light/switch/media/effect/camera device | Props(device) -> child page Fixtures (breadcrumb) |

## 15. Device fixtures card and effects (fixtures.js / effects.js take over `#piece-card`, fixtures.js:316-329)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Close | fixtures.js:325 | releases card | card open | Props back arrow |
| Output (lm) | fixtures.js:40-41 | light output | per light entity | Props(device > fixtures) |
| Fixture row (details, expand = select fixture) | fixtures.js:45, 330-341 | select fixture | per fixture | Props(fixtures) list; Scene row |
| East / North / Height / Offset / Share | fixtures.js:56-64 | position, share | point/spot/area; point/line | Props(fixture) |
| Aim east/north/height / Cone / Softness | fixtures.js:67-72 | spot aim | spot | Props(fixture: spot) |
| Aim | fixtures.js:73, 263-265 | aim mode (drag) | spot | Props(fixture) + RC(fixture) |
| Width (in) / Facing | fixtures.js:76-78 | line fixture | line | Props(fixture: line) |
| Snap host kind / host id / Edge from-to / t0 t1 | fixtures.js:81-84 | snapped line | snapped line | Props(fixture: line) (folded) |
| Reattach / Pick another edge | fixtures.js:85 | redo snap | snapped line | Props(fixture: line) |
| Keep as drawn | fixtures.js:86-94 | free the path | detached line | Props(fixture: line) |
| Point N east/north/height / Add path point / Remove last point | fixtures.js:96-107 | path points | unsnapped line | Props(fixture: line) |
| Width / Height of panel / Facing / Normal east,north,up / Rotation | fixtures.js:112-120 | area fixture | area | Props(fixture: area) |
| Redraw / Move | fixtures.js:123 | redraw or move mode | per fixture | Props(fixture) + RC(fixture) |
| Duplicate | fixtures.js:124-128 | copies fixture | per fixture | Props(fixture) + RC(fixture) |
| Delete | fixtures.js:129-132 | deletes (Prompt) | per fixture | Props(fixture) + RC(fixture) |
| Add point fixtures / Add spot fixtures | fixtures.js:136 | click-to-add mode | per light entity | Props(device > fixtures) + TB:fix > light |
| Add line fixture / Add area fixture | fixtures.js:137 | line/area tool | per light entity | same |
| Add effect (per entity / device-level) | fixtures.js:138, 287 | add effect flow | light entity / effect-capable device | Props(device > fixtures) + TB:fix > effect |
| Aim camera | fixtures.js:294 | camera aim mode | placed camera | Props(device: camera) |
| Effect: Type / Name / Switch / Clear switch | effects.js:27-33 | effect binding | effect | Props(effect) |
| Effect: Sensor (+chained Prompt) / Attribute / Clear sensor / Sensor min, max | effects.js:34-72 | sensor drive | effect | Props(effect) |
| Effect: Offset / Size at min, max / Level / Drop | effects.js:75-80 | effect shape | effect (drop: waterfall/sheer) | Props(effect) |
| Effect: Redraw / Move / Delete | effects.js:86-89 | edit, delete | effect | Props(effect) + RC(effect) |

## 16. Fixture, line-tool and device placement modes (`#device-tools`)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Point effect: click surfaces (repeats) | fixtures.js:244, 488-492 | adds effect fixtures | after Add effect | View; Status says what to click |
| Add fixtures: click surfaces (repeats until Done) | fixtures.js:232, 478-492 | adds point/spot | add mode | View; Status |
| Move mode: click once | fixtures.js:256-261, 480-486 | moves fixture/effect | Move mode | View; Status |
| Aim / Aim camera: drag on ground or wall | fixtures.js:263-265, 432-476 | aims spot or camera | aim mode | View |
| Cone / Field of view (range 10-160) | fixtures.js:266-269 | live cone preview | aim modes | `?` tool options (Props of the fixture already has Cone) |
| Draw line / Snap to edge (mode buttons) | line_fixture_tool.js:153 | line tool mode | line light/effect | `?` tool options |
| Snap points (checkbox; Alt inverts) | line_fixture_tool.js:154-155, 201 | point snapping | draw mode | `?` tool options; Alt stays |
| Finish | line_fixture_tool.js:156, 285-293 | completes line/rect | draw/area | Status (+ Enter) |
| Facing (select) | line_fixture_tool.js:157-158, 137-142 | facing while drawing | shape modes | `?` tool options |
| Click adds point / click edge = whole edge / drag = partial run / drag rectangle | line_fixture_tool.js:205-216, 241-282 | draws the fixture | line tool modes | View |
| Device placement: click wall / ceiling / yard room | device_placement.js:147-152, 170-186 | place_device | after Pick a spot | View; Status |
| Device placement: drop a carried row | device_placement.js:162-169, 187-193 | places on anchor/door/surface/yard room | dragging a row | View |
| Pointer cancel | device_placement.js:194 | cancels drag | dragging | (unchanged) |

## 17. Terrain card `#terrain-card` (terrain_tools.js:26, floats over the view)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Close | terrain_tools.js:222 | closes, cancels draft | open | Props back arrow / Esc |
| Pad row (per pad, "Pad N · ±h ft", badges) | terrain_tools.js:156-169 | chooses the pad | pads exist | Scene (yard > pads) |
| Pad row drag (grip on touch) | terrain_tools.js:177-211 | reorders pad stack | can edit | Scene (drag reorder) `?` |
| Alt+Up / Alt+Down on a pad row | terrain_tools.js:170-176 | pad up/down one layer | row focused | Scene row keys |
| Add pad | terrain_tools.js:260 | terraces draft | menu | TB:yard > yard |
| Draw yard room / bed / patio-hard surface / pool / planting edge | terrain_tools.js:261-262 | site-shape draft | menu | TB:yard (pool = TB:yard > pool; rest under yard) |
| Sidewalk / Paver path / Driveway | terrain_tools.js:263-264 | path draft with preset | menu | TB:yard > yard |
| Add fire pit | terrain_tools.js:265 | fire-pit draft | menu | TB:yard > yard |
| Draw fence | terrain_tools.js:266-270 | fence draft | menu | TB:yard > yard |
| Grade (toggle) | terrain_tools.js:271-272 | grade tint on terrain | menu | `?` TB:view or Layers |
| "<Kind> N" row per site shape | terrain_tools.js:274 | selects that shape | menu | Scene |
| Fire pit: Shape / Radius / Side / Width + Depth | terrain_tools.js:226-231 | draft size | drawing fire pit | `?` tool options |
| Finish / Finish pad | terrain_tools.js:237 | ends the draft | drawing | Status (+ Enter) |
| Pad height / Blend (draft) | terrain_tools.js:239-240 | draft pad | drawing pad | `?` tool options |
| Fence Height / Style (draft) | terrain_tools.js:243-244 | draft fence | drawing fence | `?` tool options |
| Path Preset / Width / Corner style / Smooth curve (draft) | terrain_tools.js:247-250 | draft path | drawing path | `?` tool options |
| Rectangle | terrain_tools.js:251-254 | 2 corners to a rectangle, finishes | drawing area shapes | Status (or tool options) |
| Bring forward / Send back | terrain_tools.js:285-287 | pad order | pad | Props(pad) + RC(pad) |
| Pad height / Down 0.5 / Up 0.5 / Blend | terrain_tools.js:289-291 | pad fields | pad | Props(pad) |
| Edge N (slope/sharp) / Type (None/Wall/Stair) | terrain_tools.js:300-306 | edge mode | pad | Props(pad) -> child "Edge N" |
| Wall: Thickness / Above ground / Wall cap / Cap thickness / Cap overhang | terrain_tools.js:326-334 | wall edge | edge Wall | Props(pad edge) |
| Wall face / Cap material slots | terrain_tools.js:336-337 | materials | edge Wall | Props(pad edge) |
| Stair: Step height / Tread depth / Treads / Risers + Treads material slots | terrain_tools.js:339-343 | stair edge | edge Stair | Props(pad edge) |
| Railing / Railing height / Railing material | terrain_tools.js:345-351 | railing | Wall or Stair edge | Props(pad edge) |
| Delete (pad) | terrain_tools.js:356, 377-379 | deletes pad (Prompt) | pad | Props(pad) + RC(pad) |
| Ground and yard (back) | terrain_tools.js:356 | back to menu | pad | Props back arrow |

## 18. Lot placement card (lot_tools.js:117, floats; opened from Your place)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Close | lot_tools.js:257 | closes | open | Props back arrow / Esc |
| Plot suggestion: Match to / Name / Kind / Accept / Dismiss | place.js:28-39 (used lot_tools.js:263-265) | answers a plot read footprint | click inside a suggestion | Props(suggestion) `?` + RC(suggestion) |
| This edge is the street | lot_tools.js:269-270 | street edge | lot edge chosen | Props(lot edge) + RC(lot edge) |
| Turn 90 degrees | lot_tools.js:276-281 | turns building 90 | building | Props(building) + RC(building) |
| These are in the right place | lot_tools.js:282-283 | confirms placement | building, plot read | Props(building) `?` or Gen |
| Building name buttons | lot_tools.js:302 | focus building / start footprint | lot card | Scene |
| Lot edge N buttons | lot_tools.js:303 | street card | plot read | Scene `?` (lot edges as rows) |
| Cancel drawing (footprint) | lot_tools.js:462 | ends footprint draw | footprint drawing | Status (+ Esc) |

## 19. Your place `#place-view` (HE:213-274, place.js; full panel over the editor)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Back to the house | place.js:503 | closes | open | `?` Dlg:your-place close |
| Building name / Kind / Add building | place.js:471-473, 507-512 | adds a building | step Your files | `?` Dlg:your-place |
| Facing dial (drag; arrows, Shift = 10) | place.js:151-171 | front bearing | step Your files | `?` Dlg:your-place; also Props(site) |
| Front bearing in degrees / Save facing | place.js:172-180 | bearing | step Your files | same |
| Read the plot plan · about $ | place.js:476-477, 516-518 | paid plot read | step Your lot | `?` Dlg:your-place (starts Gen) |
| Place in the scene | place.js:527 | closes, opens lot card | step Your lot | `?` Dlg:your-place |
| These are in the right place | place.js:523-526 | confirms placement | step Your lot | `?` same |
| Suggest from photos · about $ | place.js:519-521 | paid photo read | photos exist | `?` same |
| Photo suggestion Add / Use these | place.js:453-465 | apply suggestions | after photo read | `?` same |
| Confirm pages | place.js:513 | saves page roles | step Your files | `?` same |
| Build your place | place.js:181-192, 522 | paid build of every part | step Build | `?` same (starts Gen) |
| Part card: Place on the lot | place.js:357-358 | focus building on lot | building card | `?` same |
| Part card: Name and kind (details) / Name / Kind / Remove building | place.js:359-369 | rename, kind, remove | building card | `?` same; Props(building) has Name |
| Part card: Add drawings or photos (file input) | place.js:371-389 | uploads | always, even mid-build | `?` same; Menu > Import |
| Page fieldset: This page shows / Level name / Move to / Move it | place.js:278-295 | page roles | per page region | `?` same |
| Suggest page roles | place.js:396-410 | paid role guess | per drawing | `?` same |
| Photo tag toggles (per part) | place.js:306-310 | which parts a photo shows | per photo | `?` same |
| Shape without drawings: Storeys / Wall height / Roof pitch / Roof / Door side / Width + Depth + Set size / Draw on the lot | place.js:316-346 | rough shell | building with no drawings | `?` same |
| Build the lot / Build this building | place.js:422-424 | paid build of one part | step Build | `?` same |
| Link step: HA cards per building and room | place.js:217-241 | HA links (section 14) | step Link | `?` same; Props(room, building) already carry them |
| Esc | place.js:504-506 | closes | open | Keys |

## 20. Pause card, check card, flags (generation review)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Looks right `#pause-accept` | pauses.js:169-186 | accepts the paused step | build paused | Gen |
| Drag | pauses.js:192, 270-301 | drag the outline to register | paused (not lot plot/draft) | Gen; gesture in View |
| Pin 2 points (toggle) | pauses.js:187-191, 253-269 | 4 taps to register | level registration pause | Gen; taps in View |
| Re-read / Try again `#pause-reread` | pauses.js:128-131, 205-216 | paid re-read (Prompt) | paused | Gen |
| Turn in degrees | pauses.js:197-204 | turns lot placement | lot placement pause | Gen |
| Length of the measured line | HE:166; read pauses.js:172 | rescale on accept | scale outline pause | Gen |
| Cancel adjustment | pauses.js:193-196 | reverts | adjusting | Gen (+ Esc) |
| Check card Close | checks.js:77 | dismisses | open | `?` |
| Use this / Dismiss (proposal) | checks.js:94-95 | accept or dismiss a proposal | proposal item | `?` Props(proposal) + RC(proposal) |
| Looks right (flag) | checks.js:99-101 | flag ok | flag item | `?` Props(flagged piece) |
| Fix it | checks.js:102-110 | selects the piece or adjusts the pause | flag or pause | `?` Props / Gen |
| Skip for now | checks.js:112-115 | next item | any item | `?` Status / Gen |
| Read it again (fallback, Prompt) | checks.js:119-123 | re-read | pause, no #pause-reread | Gen |
| Proposal ghost click in the view | flags.js:186-198; editor.js:759 | opens the check card on it | proposals visible | View -> Props(proposal) |
| "N things to check" `#editor-flag-count` | panel.js:14-18, 78-82 | opens the check card | after first check sync | `?` Status (count) + Gen |

## 21. History `#editor-history` (HE:177-186, timeline.js, history.js)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| History (details/summary) | HE:177; timeline.js:46 | folds the list | always | History (folded under Properties) |
| History row (per round, up to 50, "· Current") | timeline.js:15-23 | previews that house read-only, freezes tools | rounds exist, idle | History |
| Return to this house | timeline.js:70-81 | reverts to the previewed round | previewing | History |
| Return to now | timeline.js:69 | leaves the preview | previewing | History (+ Status while previewing) |
| Progress / step count / "Looking at step N" chip `#time-chip` | timeline.js:27-36; HE:174 | display | — | History; chip text to Status |

## 22. Argyle panel `#editor-agent` (HE:187-211, panel.js)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Message input | panel.js:12, 65-66 | type to Argyle | always (disabled read-only) | `?` see No obvious home |
| Send / Enter ("keep going" accepts the pause) | panel.js:38, 65-66; editor.js:46-50 | sends | not read-only | `?` |
| Quick replies: Keep going / What needs checking? | panel.js:67-75, 162, 168 | sends that text | always / paused | `?` (Keep going also in Gen) |
| Build log `#editor-log` + conversation `#editor-messages` | HE:202-203 | display | always | `?` |
| Plan file: textarea / Reason / Save plan / Close plan file | editor.js:565-604 (409 Prompt 595-596) | hand-edit plan JSON | after Menu > Advanced | Dlg:plan-file |

## 23. Library panel `#library-panel`, chooser, import (library.js, imports.js)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Materials / Items tabs | library.js:469-471 | category | panel open | Library (sub-tabs) |
| Search models | library.js:463 | filter | panel open | Library |
| Import model | imports.js:198-199 | file picker | can edit | Library + Menu > Import (Dlg:import) |
| File drop on the canvas | imports.js:200-201 | imports dropped models | always | View (drop target) -> Dlg:import |
| Import settings (details): Maximum upload size / Maximum unpacked size | imports.js:202-211; library.js:369 | import limits | panel open | Dlg:settings |
| Import dialog: Name / Kind / Add to library / Cancel | imports.js:77-88 | keep the import | after a file loads | Dlg:import |
| Equipment: Meter / Electric panel / Charger / Parking spot | library.js:362-366 | clicks rail-add-* | Items tab | Library > Items (keeps calling the tool) |
| Material tile: drag onto the house | library.js:412-416, 472-484 | drop -> scope chooser | Materials tab | Library (drag into View; dragging onto a slot row is slice 6) |
| Material tile: click / Enter / Space | library.js:417-421 | apply to the picked surface | picking mode | Library selection + Props "Use selected" (slice 6) |
| Edit in Library (link) | library.js:378-380 | opens /house/library?material= | each tile | Library action bar + RC(asset) (slice 6) |
| Item tile: drag onto floor, wall or ground | library.js:412-416, 472-483 | adds item / opening / yard item | Items tab | Library (drag into View); plants also TB:yard > plants |
| Rename / Delete model | library.js:393-410 | rename or delete import | import entries | Library action bar + RC(asset) (slice 6) |
| Select hidden: name | library.js:430-431 | selects a hidden object | hidden objects exist | Scene (dimmed hidden rows, slice 5) |
| Scope chooser: This wall face / This room / This floor / The whole building / This roof / Cancel | library.js:96-101, 316-327 | material scope | after a drop or pick | `?` |
| Yard item body drag (Move tool), Shift free, typed value | library.js:548-603; editor.js:755-763 | moves plant/furniture | Move tool, yard item selected | View |

## 24. Houses dialog `#houses-panel` (HE:275-286, houses.js)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Close / Esc / Tab trap | houses.js:85, 104-112 | closes, focus | open | Dlg:save-open |
| Save current house | houses.js:86-92 | names, thumbnails, saves | open | Menu > Save + Dlg:save-open |
| Download current house | houses.js:93 | downloads .chauffeur-house.json | open | Menu > Export |
| Upload a house file + file input | houses.js:94-103 | uploads a house save | open | Dlg:save-open |
| Row: Load / Rename / Download / Delete | houses.js:55-74 | per save | each save | Dlg:save-open (+ RC(row)) |

## 25. Edit timing overlay `#editor-edit-timing` (HE:87, edit_timing.js)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| Timing overlay (display only, no controls) | HE:87; edit_timing.js:74-89 | per-edit timing | Show edit timing on | `?` (floats over the view today) |

## 26. 3D view: handles, gizmo, typed value, dimensions (all stay in the view)

| Control | Where | Does | When | New home |
|---|---|---|---|---|
| site_move / site_radius / site_vertex / "+" insert handles | handles.js:79-87, 178, 224 | move, radius, corner, insert corner | yard shape selected | View |
| Alt+click corner | handles.js:222-224, 440; polygon_handles.js:12-14 | removes corner | yard shape | View |
| joint (corner) / room centre / room body press | handles.js:99-115, 202-206 | move corner (welds within 1 ft) / move room | room, wall | View |
| wall midpoint / wall line press | handles.js:112, 192-201 | slide wall along normal | wall | View |
| stair_end from/to | handles.js:107-109 | move stair end | stair | View |
| opening middle / left / right / top / bottom | handles.js:126-130, 386-389 | slide, width, head, sill | door, window | View |
| solar middle / 4 edges | handles.js:136-137, 373-374 | move/resize zone | solar zone | View |
| roof_edge (drag; click) | handles.js:140-143, 340-348, 449 | push edge; click calls back | roof | View |
| dormer middle / edges | handles.js:150-152, 350-353 | slide, width | dormer | View |
| hosted handle | handles.js:154-161, 390-410 | slide/re-host on wall, roof, floor, ceiling, ground | anchor, item, device piece | View |
| Gizmo Move X / Y / free | gizmo.js:86, 99-101 | axis/free move | Move tool, placed things | View |
| Gizmo Turn handle + ring | gizmo.js:87, 104-122, 183-188 | turn (15 deg) | Turn tool | View |
| Gizmo Scale uniform / X / Y | gizmo.js:88, 192-201 | scale | Scale tool, objects and shapes | View |
| Building move / turn handles; body press with Move/Turn | lot_tools.js:167, 235, 349-354, 387-401 | move/turn building on lot (Shift free) | building, exterior view | View |
| Pad corner / "+" / Alt+press corner | terrain_tools.js:81, 412-471 | reshape pad | pad chosen | View |
| Fixture point handles | fixtures.js:379-417, 439-460 | move one path point | unsnapped line light/effect | View |
| Aim handle (sphere) | aim_tool.js:28-41 | aim point of a spot | aim mode | View |
| Typed value box (digits . - ' " Backspace, Enter, Esc) | typed_value.js:5-37; scene_tools.js:482-491; lot_tools.js:430-436 | exact length/angle/factor | during gizmo, wall/joint/room, site_move, lot, yard-item drags | View |
| Wall length label (button) | dimensions.js:178-202 | Prompt a length, moves the far end | wall selected | View (+ Props(wall) Length `?`) |
| Distance to wall labels (up to 2) | dimensions.js:216-221 | Prompt a gap, moves the wall | wall with parallel neighbours | View |

## 27. Keyboard

| Key | Where | Does | When | New home |
|---|---|---|---|---|
| Ctrl+Z | history.js:66-73 | undo | not in a field, no modal | Keys (TB:undo tooltip) |
| Ctrl+Shift+Z / Ctrl+Y / Ctrl+Shift+Y | history.js:66-73 | redo | same | Keys |
| Delete | scene_tools.js:455 | deletes object, opening or yard item | those selections | Keys (+ RC Delete) |
| Delete (pad) | terrain_tools.js:489 | deletes chosen pad | terrain card, pad | Keys |
| Arrows | scene_tools.js:456-459 | move yard item 1 ft | yard item | Keys |
| Arrows | lot_tools.js:440-442 | move building 1 ft | building with move handle | Keys |
| R / Shift+R | scene_tools.js:462-470 | rotate object (Shift other way/step) | placed object | Keys |
| [ / ] | scene_tools.js:462-470 | scale object | placed object | Keys |
| Esc (layered, capture first) | scene_tools.js:479-503; draw.js:225-230; roof_tools.js:114-118; terrain_tools.js:486; lot_tools.js:439; fixtures.js:534-545; device_placement.js:195-198; library.js:488-492; checks.js:194-196; houses.js:104; place.js:504 | cancels split, drag, tool, mode, card, chooser; idle Esc steps the selection back (selection.js:46-50) | per mode | Keys (keep the order) |
| Enter | terrain_tools.js:487; line_fixture_tool.js:308 | finishes the drawing | drawing | Keys (Status shows it) |
| Backspace | terrain_tools.js:488; line_fixture_tool.js:307 | removes last point | drawing | Keys |
| Alt+Up / Alt+Down | terrain_tools.js:170-176 | pad layer order | pad row focused | Keys (Scene row) |
| Arrows / Shift+arrows on facing dial | place.js:164-171 | bearing 1 / 10 deg | dial focused | Keys |
| Typed-value keys | typed_value.js:22-37 | see section 26 | during drags | Keys |

## 28. Mouse gestures and modifiers (scene_tools.js routes; delegates set at editor.js:754-765)

| Gesture | Where | Does | When | New home |
|---|---|---|---|---|
| Hover | scene_tools.js:346, 447; selection.js:60-64 | outline of what a click selects | Select tool | View |
| Click (under 3 px) | scene_tools.js:334, 416-430 | selects nearest | any tool, unclaimed | View |
| Click again within 4 px | picking.js:15-24 | cycles to the thing beneath | Select tool | View |
| Click a room / outside it | selection.js:39-57 | room focus / back out | any | View |
| Shift+click | scene_tools.js:329-330, 419-425 | adds room to Roof over this set | Select tool | View |
| Drag selected body (Move / Turn) | scene_tools.js:313-383, 438 | moves / turns building | Move/Turn tool, selected | View |
| Shift during any drag | handles.js:279; drag.js:26, 46-47; gizmo.js:152; lot_tools.js:387-398; terrain_tools.js:432-471; site_drawing.js:49-51; library.js:587 | snapping off | drags and drawing | View |
| Alt while drawing a line fixture | line_fixture_tool.js:201 | inverts point snap | line draw | View |
| Draw room: drag rectangle / click corners | draw.js:157-161, 255-270 | draws room | Draw room | View |
| Draw wall: click corners; double-click ends | draw.js:162-171, 231-235 | wall chain | Draw wall | View |
| Split room: click two walls (then Prompt name, Skip) | draw.js:85-91, 141-147 | splits room | Split room | View |
| Door / window: click a wall | draw.js:190-199, 303-304 | adds 3 ft opening | Add door/window | View |
| Anchor / stair / solar / equipment / parking clicks | draw.js:150-155, 174-188, 274-300 | places that thing | that tool | View |
| Press the just-placed item's handle | draw.js:243-245 | ends placement, handle takes over | placement tools | View |
| Split wall click | scene_tools.js:32-55 | splits at click (inch / middle snap) | split armed | View |
| Roof: click corners / click sloped roof | roof_tools.js:128-148 | roof area / dormer | roof modes | View |
| Ground clicks (draft points), fire pit release | terrain_tools.js:432-442, 473-491 | yard drafts | terrain drawing | View |
| Click a pad | terrain_tools.js:400-410; editor.js:757 | chooses pad | exterior view | View -> Props(pad) |
| Click a lot edge / suggestion / unbuilt footprint; drag footprint rectangle | lot_tools.js:365-384, 418-426 | street card / suggestion / focus / footprint | exterior view | View -> Props |
| Click a fixture or effect | fixtures.js:345, 365-373, 423-432, 471-472 | opens fixture/effect card | always | View -> Props(fixture, effect) |
| Any scene interaction | editor.js:695 | dismisses check and pause cards | always | keep |

## 29. Shared prompts raised (control_center.html; unchanged)

Spend checkpoint Continue/Stop and $50 limit (api.js:32-38); plan changed Reload/Keep editing (editor.js:595-596); Reset spend type "reset" (editor.js:610-612); Start over (editor.js:625-627); Load/Delete/Rename/Save house (houses.js:57, 66, 72, 87); paid confirm (place.js:190-191); Remove building (place.js:365-369); Read it again (checks.js:121); delete confirms (cards.js:359, fixtures.js:130, effects.js:88, terrain_tools.js:379, site_shape_shelf.js:187, library.js:402); Add anchor kind (draw.js:112-117); Add floor name (draw.js:214-224); room name with Skip (draw.js:85-91); Pick a spot choice (ha_link.js:80-96); Choose a room (ha_link.js:387); effect type and shape (fixtures.js:235-240); sensor attribute/min/max (effects.js:34-54); dimension Set distance (dimensions.js:178-221). Home: Prompt (centred, already one at a time).

Test-only: `window.__editor` (editor.js:32, 647-653, 693, 776-785), `window.__twinEditor` (editor.js:786-793), `window.__twinEditTiming`. No person-reachable controls.

## No obvious home

1. **Argyle chat panel** (section 22: input, Send, quick replies, build log, conversation). The new layout has no place for it; today it is a permanent column. Candidates: a fourth dock tab "Argyle" beside Scene/Layers/Library; or a slide-out opened from a toolbar button and from "Ask Argyle about this". The build log may belong in the generation bar's detail.
2. **Your place view and the steps strip** (sections 3, 19: about 40 controls: files, pages, photos, lot, facing, build, HA link step). It is a full workflow, not a dialog the spec names. Candidates: a centred "Your place" dialog with step tabs, opened from the menu (and "Check it" moving to the generation bar); or a dock tab while setting up.
3. **Check card queue and the "N things to check" count** (section 20). Spec covers the generation bar and Properties but not a review queue that outlives a run. Candidates: the count in the status line opening a walk through items, each item landing in Properties (proposal / flagged piece) with Use this, Dismiss, Looks right, Skip; or a "Checks" section in the generation bar.
4. **Resume and the spend total outside a running build** (section 2). The generation bar shows only while a generation runs; Resume appears when a build is stopped, the spend total always. Candidates: keep the bar visible while a build is stopped or paused; or Resume in the menu and the spend in the status line.
5. **Tools missing from the spec's toolbar list**: Split room, Add anchor, Add stair, Add floor, Add solar zone, Add meter / electric panel / charger / parking spot (section 6). Candidates: Split room in RC(room) and Props(room); stair and floor in the structure group's overflow or the floor picker; solar zone in the roof submenu and RC(roof); anchor under fixtures > device; equipment stays in Library > Items (already present there).
6. **Sheet (drawing underlay) and Grade tint** (sections 6, 17). View toggles, not tools. Candidates: the view picker, or Layers (the spec lists "the plot plan" as a layer).
7. **Tool options while drawing or placing**: terrain draft options (fire pit shape/size, pad height/blend, fence height/style, path preset/width/corners), the Add stair draft fields, line fixture mode buttons and Snap points, Facing, the aim Cone/Field of view slider (sections 16, 17, 11). Properties is for a selection; a draft is not one. Candidates: Properties shows the active tool's options when nothing is selected or a draft is live; or a tool-options strip in the status line.
8. **Material scope chooser** (This wall face / This room / This floor / The whole building / This roof, library.js:316-327) after dropping a material in the view. It floats today and "nothing floats". Candidates: a small right-click-style menu at the drop point; or the choice as rows in Properties for the picked surface (slice 6/7 slot rows may make it moot).
9. **Front door empty state** (section 5). Floats over the view. Candidates: a centred dialog on an empty house; or an empty-state body in the dock.
10. **Edit timing overlay** (section 25). Diagnostic display that floats over the view. Candidates: a section in the dock under History; or a centred dialog opened from the menu.
11. **Lot placement card pieces**: plot suggestion answers, Lot edge N buttons, "These are in the right place" (section 18). Candidates: suggestions and lot edges as Scene rows with Props pages; confirm placement in the generation bar or Props(building).
12. **Wall length / distance labels** stay in the view, but whether Properties(wall) also gains a typed Length field is open (the wall card has no length field today).

## Removed or duplicated (a move is fine, a loss is not)

- **Left tool rail** (HE:113-119, terrain_tools.js:478): the column goes. Each button's capability moves: select/move/turn/scale to TB:sel; room, wall, door, window, roof to TB:struct; Ground and yard to TB:yard; Add effect to TB:fix; Undo/Redo to TB:undo; Library to the Library tab; Delete to RC, Props and the Delete key; the rest per "No obvious home" 5-6. The rail's side effects (any rail click closes the terrain card, terrain_tools.js:479-482; leaves roof mode, roof_tools.js:113) must follow the toolbar.
- **Floors panel** (HE:176): becomes the floor picker; per-floor eye also gets the Layers/Scene eye in slice 5; Change this floor / Change the house become Scene rows and the breadcrumb.
- **Camera bar and lighting group** (HE:138-149): become the view picker.
- **Piece card, terrain card, lot card, fixtures card, effect card, roof edge sub-card, all shelves**: all become Properties pages; Close and "Back to roof" / "Ground and yard" become the back arrow; nested pages (device > Fixtures, roof > Edge N, pool > feature, pad > Edge N) become breadcrumb steps.
- **Draw, device and roof mode strips** (HE:150-162): notes and Cancel/Done/Finish move to the status line; Esc and Enter keep working.
- **Material slot inline chooser** (material_slot.js:31-67): replaced by Library selection plus "Use selected" and clear in the slot row (slice 6). Cancel has nothing to cancel then. Default/tint/clear stay in the row.
- **Library panel** (HE:120-137): becomes the Library dock tab; Import settings move to Dlg:settings.
- **House materials section in the building card** (house_materials.js): moves to the centred House materials dialog (spec, slice 7).
- **Houses button and dialog**: become Menu > Save / Open / Export and Dlg:save-open.
- **Top-bar Library link** (HE:90) and **nav Material library link** (nav.html:314): duplicates; keep one in the Menu and one in the Library tab.
- **Menu "Upload more" and "Your place"** (editor.js:499, 503): identical action; one entry suffices.
- **Library Items equipment buttons** (library.js:362-366) duplicate the rail's Add meter/panel/charger/parking; they become the only entry unless the toolbar adds them.
- **flags.js review card** (flags.js:47-63, 178): dead on this page (managed:true); removing it loses nothing.
- **Advanced plan file section inside the Argyle panel**: moves to Dlg:plan-file from the Menu.

## Notes for the planner (found while surveying)

- `#pause-accept` and `#pause-reread` are adopted into the check card and sent home (checks.js:19-22, 99, 119); the ids must survive the move.
- `#device-cancel` is bound by both fixtures.js:532 and device_placement.js:199; one click runs both.
- Esc handlers are layered by capture order across ten files (section 27); the shell must keep that order.
- Ctrl+Z/Y check `ctrlKey` only (history.js:67); Cmd on a Mac does nothing.
- Charger and parking anchors appear to get the object shelf as well as the equipment shelf (anchor without `device`), and meters/panels show "Distance from surface" (cards.js:23, 230).
- `cards.edge()` (cards.js:420-423) has no caller in the editor.
- The typed-value box appears only for gizmo, wall/joint/room, site_move, lot and yard-item drags; opening, stair, solar, roof, dormer, hosted, vertex and radius drags take no typed value.
- The spec's TB:fix "light", "device" and "measure" tools do not exist as tools today: lights are added per entity from the device's Fixtures page, devices by Pick a spot or row drag, and there is no measure tool (new work, not a move).
- Place view upload and photo tags stay enabled during a build (place.js:91-93); keep that if the view moves.

## Owner rulings on "No obvious home" (2026-11-18)

The owner approved Claude's proposed homes ("Mostly sound fine"), with one change to item 8:

1. Argyle chat panel: a fourth dock tab, Argyle (Scene, Layers, Library, Argyle). An "Ask Argyle" action on a selection opens it with that thing in context.
2. Your place view and steps strip: a centred "Your place" dialog with one tab per step, opened from the menu and on its own for a new house.
3. Check queue and "N things to check": the count lives in the status line; clicking it walks the items, each landing in Properties.
4. Resume and the spend total: the generation bar shows while a build is running, paused, or resumable.
5. Tools missing from the spec's toolbar list: Split room, Add stair, Add floor in the structure group (Add floor also in the floor picker); Add anchor and an equipment menu (meter, electric panel, charger, parking spot) in the fixtures group; Add solar zone under Roof. Measure is new work (a small tool), built in this slice.
6. Sheet underlay and grade tint: rows in the Layers tab now (slice 5 fills out Layers).
7. Tool options while drawing or placing: Properties shows the armed tool's options.
8. Material scope chooser after a drop: **stays as the small menu at the drop point, and stays even after slices 6 and 7 add material slot rows** (owner: "I like that drop menu the way it is. I would keep it even after the material slot controls are in."). Dragging a material onto a surface in the view therefore remains a permanent way to assign.
9. Empty-house front door: a centred dialog when the house is empty.
10. Edit timing overlay: opt-in with `?timing=1`, shown as a History sub-section, not floating over the view.
11. Lot placement extras: Properties for the lot or the building, reached from Scene.
12. Wall length: a typed Length field in Properties for a selected wall, beside the on-view dimension labels.

Bugs found by the survey, fixed in slice 4: Ctrl-only undo/redo (Cmd on a Mac does nothing); `#device-cancel` runs two handlers per click; `cards.edge()` has no caller.
