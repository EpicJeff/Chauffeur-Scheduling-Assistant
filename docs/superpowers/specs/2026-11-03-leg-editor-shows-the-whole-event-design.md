# The event editor opens the whole event, never a leg — design

**Date:** 2026-11-03. **Status:** rev 1, approved in conversation. **Touches:** `templates/dashboard.html` (`openEventModal`, `switchToEditMode`, the save), `templates/components/event_config_form.html` (`eventConfigPayload`), one new line of markup in the event modal.

## Problem

The user, 2026-11-03: "once you split an event and get the drop off and pick up events, if you go to edit the event details by clicking on one of those, it carries the time of the drop off / pick up and not the time of the whole event, so if you switch it back to stay or let scheduler decide, it modifies the time of the event ... the whole event becomes a 0 minute event. Why doesn't it always show the original event's info when you click the event configuration button?"

The card clicked is the leg. The split (`main.refresh_schedule_logic`) copies the event twice, a drop-off whose `end` is the start and a pick-up whose `start` is the end, and keeps the whole event in the page data beside them (`all_events_for_ui`). `openEventModal` and `switchToEditMode` read `currentEventsMap[eventId]`, the leg, so the time fields show a zero-length event. Since v2.499.244 a save only writes times when the fields changed against the form as drawn, so a mode-only save does not rewrite; a touched time field does, with the leg's pair, and any host without a baseline would. The form showing the leg at all is the defect.

## Decisions

1. **The modal is about the whole event.** For a leg (`event_type` `dropoff` / `pickup`, or an id ending `_dropoff` / `_pickup`), `openEventModal` resolves `whole = currentEventsMap[ev.original_event_id]` (fallback: the leg with `start`/`end` replaced by its `original_start`/`original_end`; last resort the leg itself). View mode shows the whole event's date and time. One new line under the time, `#view-leg`, says which drive this card is: `Drop-off drive` / `Pick-up drive` (for a merged block, `Pick-up drive for Swim + Dive`: the leg's own title after the prefix). Hidden for a whole event.
2. **The editor fills and saves from the whole event.** `switchToEditMode` fills from `whole`; the save builds the payload from `whole`. `activeEventId` stays the clicked id (cancel, ride group and the other modal actions keep working on the leg as they do today).
3. **A leg never writes times.** `eventConfigPayload(ev, v, base)`: when `ev` is a leg, `details` is `null` whatever the fields say. Belt and braces for any other host.

## Tests (Claude, first)

`tests/test_leg_editor_live.py`: a household with one three-hour event (the two-hour default splits it). Open the drop-off card: `#view-time` shows the whole span, `#view-leg` says `Drop-off drive`; edit mode shows the whole span in `#edit-start` / `#edit-end`; switch Attendance Mode to `stay` and save: one POST `api/events/config/gev1` carrying `driver_attendance_mode: 'stay'` and NO `PATCH api/events`. Open the pick-up card: same span, `Pick-up drive`. Open the whole event (no leg line). `eventConfigPayload` on a leg with moved times returns `details: null` (run in the page).
