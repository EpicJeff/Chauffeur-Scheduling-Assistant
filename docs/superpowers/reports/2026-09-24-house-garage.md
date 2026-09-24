# One-bay hybrid garage — 2.499.179

The exterior Garage marker uses the shared interaction controller: first tap
expands Cars/Errands quick views, second tap enters the garage, hold Cars or
Shift+Enter visits the bay. Errands hold enters then opens the existing card.
The car and Vehicle information button open the existing fleet card. Outside,
browser back/forward, reload and deep links preserve the room journey.

The gray EV9 is parked straight, backed into the bay with its front square to
the doorway. The first angled image was rejected after user feedback and is not
used. The occupied photograph includes its lighting, contact shadows and floor
reflection; it is not a recolored or independently lit cutout.

Two full-frame images crossfade at the same camera position. This is a one-bay
visual proof, not an animation of driving or a general multi-bay compositor.
Garage artwork loads on first entry. Reduced motion switches immediately.
The exterior no longer shows parked car cutouts; the school bus remains as in
the previous preview. Other vehicles remain accessible in the fleet card.

When an EV9 appears in shared fleet state, the bay follows its presence and
shows available battery telemetry. Without one, the scene explicitly says
Example EV9. The Preview state selector can force Parked/Away locally; this
never writes vehicle state, changes HA data or sends vehicle commands. Reload
resets the override. Unknown fleet state does not masquerade as real telemetry.

Assets, generated using built-in imagegen:
- `chauffeur/static/house_hybrid/garage-empty.png`
- `chauffeur/static/house_hybrid/garage-ev9.png`

Exact prompts: `2026-09-24-house-garage-prompts.json`. Three generations total:
empty garage, rejected angled car, corrected straight parked car. No paid Gemini
calls or server generation workflow were added. This remains a fixed daylight,
single-model prototype; arbitrary models, multiple bays and night states are
not implemented.

Validation: `test_house_garage_live.py` covers marker quick views, second tap,
hold/keyboard entry, live presence, local override with no API writes, card
focus, history/reload and phone layout. The existing exterior/living navigation
regression passed. Screenshots in ignored `scratch/garage-review/` reviewed for
parked, empty and mobile states. Work stayed in the existing isolated worktree.
