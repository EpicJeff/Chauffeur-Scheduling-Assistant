# Mudroom packing and exterior glance — 2.499.185

The photographic mudroom now shows a backpack for each activity with a packing
list in the existing Family Day feed. Lists share the existing packing dialog
and claim endpoint. Incomplete bags are open; completed bags are closed.
Activities in the same outing remain separate, and preparation tiles are
deduplicated against their source activities. Empty lists create no demo bags.
Additional activities are paged, four at a time on large screens and two on
small screens. The room and bags share one camera transform when cropped.

The four styles are sage canvas, navy sport, burgundy rounded, and tan rolltop.
Per the final placement decision, they stand in the middle of the floor where
unfinished packing is conspicuous. All artwork was generated inside the exact
room photograph with its perspective, lighting, straps and contact shadows.
Soft registered scene regions allow each bag to change independently without
replacing another activity's state. These are packaged assets, not a runtime
asset-generation pipeline.

The exterior uses the screensaver's existing clock and compact HeroCard renderer.
They hide on entering a room. Interior clocks remain deferred.

## Assets and generation

Mode: built-in image generation/editing tool. Final assets, all 1536 × 1024:

- [Open/day](../../../chauffeur/static/house_hybrid/mudroom-packs-open-day.png)
- [Closed/day](../../../chauffeur/static/house_hybrid/mudroom-packs-closed-day.png)
- [Open/night](../../../chauffeur/static/house_hybrid/mudroom-packs-open-night.png)
- [Closed/night](../../../chauffeur/static/house_hybrid/mudroom-packs-closed-night.png)

Prompt set:

1. **Open/day**, editing `mudroom-day.png`: Preserve the exact architecture,
   furniture, camera, framing, flooring, rug, lighting, doors, plants and boards.
   Add four distinct photorealistic open backpacks standing on the existing
   middle floor in front of the cabinet with correct scale, perspective,
   lighting, contact shadows and ambient occlusion. Sage canvas with leather
   trim; navy sporty; burgundy rounded; honey-tan rolltop. Main compartments
   wide open with visible lining. Leave gaps between bags and preserve the
   hamper and walkable foreground rug. No UI, labels, people or text.
2. **Closed/day**, editing the open/day master: Change only the four backpacks
   to fully closed packed states. Preserve camera, resolution, architecture,
   background, positions, sizes, colors, styles, straps and contact shadows.
   Fasten sage flap; zip navy and burgundy fronts; roll and buckle tan top.
   No contents visible. Match the original footprints and silhouettes closely.
3. **Open/night**, editing the open/day master with `mudroom-night.png` as
   lighting reference: Match the reference's nighttime lighting precisely.
   Preserve all four open compartments, bag shapes, positions, sizes, colors,
   straps and floor contact. Night outside the windows; warm amber interior
   light; no daylight patch on the floor. Preserve exact camera and room.
4. **Closed/night**, editing open/night with closed/day as the shape reference:
   Change only the four backpacks to the closed packed states of the reference.
   Keep exact night lighting, floor, background, camera, positions, sizes and
   styles. Sage flap fastened, navy/burgundy fronts zipped, tan rolltop buckled,
   no visible contents. Preserve straps and contact shadows. No other changes.

## Verification

Tests use isolated fixture storage and remove inherited Home Assistant
credentials. No live household schedule or packing claims were modified.

- Mudroom browser test: separate activity bags, deduplication, saved packing,
  reopening, other-device update, keyboard focus/Escape, seven-activity paging,
  empty state, day/night assets, responsive layouts, exterior clock/hero.
- Connected-room browser test: all five rooms, 14 object views in day/night,
  responsive full-screen layout, Study PIN/lock/history.
- Existing packing-card browser scenarios: 11/11.
- Template JavaScript: 9/9. Tailwind build checks: 6/6.
- Visually reviewed desktop, phone, short landscape and ultrawide captures.

The new packing test disables the delayed legacy startup migration that clears
schedule caches, so it cannot erase this test's deliberately seeded schedule.
The connected-room test selects the currently visible navigation controls,
including the wide-screen shortcut layout when the camera follows the bags.

Version 2.499.185 is published on main for the add-on update. Installing that
update on Home Assistant is separate from publishing the repository changes.
