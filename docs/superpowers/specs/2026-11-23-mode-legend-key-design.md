# House viewer mode legend: a key button and one compact card

Date: 2026-11-23. Size: small change (short design). Status: for owner approval.

## Intent

The owner (2026-11-23): "the mode legends really get in the way, especially when you have multiple modes enabled. If they have to exist, they should be much more compact or collapsed and compact." They want:
- colour blocks instead of colour words;
- a short description for each colour;
- no long lists of matching things, as the Security legend has today;
- the legend out of the way unless it is asked for;
- pretty and easy to read at a glance.

The owner picked option A from three mockups: a key button on the mode strip.

## Today

- `live/modes.js:99-100, :282-284, :337` builds `#twin-mode-legend`, an always-visible panel of strings joined with " · ".
  - Climate is a static string (`live/climate.js:115`).
  - Energy is a string from `energyPlacementLegend` or a fallback (`live/energy.js:283, :409`). Its `legendContent` holds the energy check controls ("Why no ribbons?", `live/energy_check.js`).
  - Security builds a string that lists every alarm panel (`live/security.js:191-195`).
  - The Lights overflow note is appended to the end.
- Styles live in `templates/house_twin.html:278, :348-362`.

## Design

- **The button.** A key button (`?`, accessible name "Legend") sits at the end of the mode strip. It is shown only when at least one active mode has a key. `aria-expanded` reflects the card.
- **The card.** One card drops below the strip, with one section per active mode, in strip order. Each section has:
  - a small header (the mode's own icon and name);
  - rows of a colour swatch plus 1-3 words;
  - at most one short note, such as "Flows under 50 W are hidden" or the Lights overflow note.
- **Swatches.** Swatches come from the same colour constants the modes draw with, never duplicated hex values. The camera view gets a small cone glyph rather than a colour.
- **Security.** Security's alarm panels become one status line, e.g. "Alarm · armed away (5 of 6)" or "Alarm · unavailable". The full list is shown only if the panels disagree, collapsed behind that line.
- **Energy.** Energy's existing check controls ("Why no ribbons?", the read-only wall-panel check) stay inside the Energy section.
- **Opening and closing.**
  - Closed by default.
  - Tapping the button toggles it.
  - Esc, a tap in the scene, or turning off the last mode with a key closes it.
  - Open/closed is remembered per device in localStorage.
- **Panels and kiosks.** These use the same component, opened by a tap.
- **One builder.** A shared `live/mode_key.js` builds the card, following the UI design guide's rule that the same concept uses the same builder. Each mode provides structured data instead of a string: `key() -> {items:[{swatch, label}], note?, status?}`. The existing `legend` strings are removed once every mode provides `key()`.
- **Look.** It uses the viewer's existing glass panel tokens (`--twinGlass`, `--twinText`, `--twinBorder`). Rows are 12.5 px with 12 px swatches. The card is 200-240 px wide and scrolls past 60dvh.

## Non-goals

- No change to what the modes draw.
- No new settings page: the open state is just remembered.

## Tests

- A node test of `mode_key.js`:
  - sections only for active modes;
  - swatches come from the modes' constants;
  - the alarm summary for all-agree, mixed and unavailable;
  - no button when no active mode has a key.
- A Chromium check on the viewer:
  - closed by default with no legend text on screen;
  - the button opens the card with Climate, Energy and Security sections;
  - Esc closes it;
  - the state survives a reload;
  - the energy check link is still reachable;
  - the card does not overlap the glance bar at 1080p.
- Look check: screenshots at your default overview with three modes on, card open and closed.
