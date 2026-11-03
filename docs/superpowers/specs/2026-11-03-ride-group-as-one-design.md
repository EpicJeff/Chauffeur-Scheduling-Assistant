# Ride groups: one drop-off, one pick-up — design

**Date:** 2026-11-03. **Status:** rev 1, approved in conversation. **Follows:** ride groups (v2.499.223, `services/ride_groups.py`), the attendance split in `main.refresh_schedule_logic` (`_attendance_decision`, the `_dropoff` / `_pickup` legs). **Touches:** `services/ride_groups.py` (a group mode, the merge plan), `services/storage.py` (one column), `models/schemas.py` (`Event.ride_group_mode`), `main.py` (the split loop reads the plan; the group route takes a mode), `services/agent_tools_v2.py` (one field), `templates/dashboard.html` (the drop dialog, the chip), `templates/components/schedule_timeline.html` (the chip on merged legs), Tailwind rebuilt.

## Problem

The user, 2026-11-03: "back to back events at the same location. They are grouped so they schedule together. But I want to set them to drop off / pick up and have there be a single drop off event at the beginning of the first event and a single pickup event at the end of the last event without having to go in and set each event to drop off and pick up and then remove / ignore the in between pick ups and drop offs. There should be a simplified mechanism to set a group to drop off / pick up and have it treat them as a singular event."

Today each member of a ride group decides its own split (`_attendance_decision` per event). Two grouped two-hour classes at one venue yield four legs, two of them a pick-up and a drop-off at the same minute and place. The group knows they ride together; nothing knows the kids never leave the building.

## Decisions (the user's, 2026-11-03)

1. **A ride group gets a mode.** `ride` (the shipped group: ride together, routed as one trip, members split on their own) or `one` (the group is one event for attendance: one drop-off at the first start, one pick-up at the last end, nothing in between).
2. **Per occurrence, never a rule.** The mode lives on the group's rows in `storage.ride_groups`, beside the group id. Same keying, same pruning, same "a member that moves stops matching".
3. **Same place only.** Mode `one` is refused when the members' places differ (normalised: case-folded, whitespace-collapsed) or any is empty: `One drop-off and pick-up needs every event at the same place.` Gaps between members are allowed; the kids wait at the venue. The dialog says so.
4. **Whole events.** A `one` group is over whole events (row leg `''`). A leg id given to the group or ungroup routes under mode `one` means its parent.
5. **Precedence.** The group mode beats hashtags, rules and each member's Attendance Mode dropdown (that is the point). A day-of attendance override (`storage.get_attendance_overrides`) with action `stay` on ANY member of the group on that date cancels the merge for that day: every member then decides on its own, as today. The person in the car outranks the plan.
6. **Legs hang off the first member.** Ids `{first}_dropoff` and `{first}_pickup`. Nothing else in the app has to learn a new id shape.

## 1. Store and stamp

`storage.set_ride_group_row(google_id, date, leg, group_id, mode=None)` writes `mode` (`None`/`''` read as `ride`). `storage.get_ride_group_rows` returns it. `ride_groups.group(items, mode=None)`: with `mode` given, every row of the resulting group gets it (an existing group switches mode by grouping its members again with the new mode); with `mode=None` the target group's existing mode is kept (a member joining a `one` group joins as `one`) and a new group is `ride`. Before writing `one`, `group` checks the members' places (`_get(ev, 'location')`), and raises the ValueError above when they differ or one is empty. `main._ride_group_event` keeps `location` among the keys it reads from the page.

`Event.ride_group_mode: Optional[str] = None`. `stamp_ride_groups` sets it from the whole-event row (`leg == ''`) when that row's mode is `one`; a leg copy made later by `model_copy` carries it. `ride_groups.group_mode_of(ev) -> str` (`'one'` or `'ride'`).

## 2. The merge plan

`ride_groups.merge_as_one(events, attendance_overrides) -> dict`:

- Members: among `events` (the refresh's unrolled whole events, never `background_trip`), those with `group_mode_of == 'one'`, bucketed by `(group id, occurrence date)`. A bucket of one is no merge. A bucket whose members' places differ (the row was written before a member moved) is no merge: each member decides on its own. A bucket with a `stay` override on any member is no merge.
- For a merging bucket, sorted by start: `first`, `last` (latest end). Two legs from `first.model_copy()` exactly as the split loop makes them today (`event_type`, `needs_triage=False`, `original_event_id=first.id`), except: both carry `original_start = first.start`, `original_end = last.end`; the pick-up's `start = end = last.end`; `calendar_ids`, `original_calendar_ids` and `source_event_ids` are the union over members in start order (deduped); titles `Dropoff: Swim + Dive` / `Pickup: Swim + Dive` (member titles in start order, deduped, joined with ` + `); `description` the first's.
- Returns `{'legs': {first.id: [drop, pick]}, 'skip': {every member id, first included}}`.

In the split loop (`main.refresh_schedule_logic`, where `should_split` is decided): compute the plan once before the loop over `events`; a member in `skip` takes no per-event decision; the first member appends its two legs to `events_to_solve` and `all_events_for_ui` instead; the inner and last members are neither solved nor split (they stay in `all_events_for_ui` as any split parent does, so the page draws them the way it draws a split parent today, which is not as a card). Nothing changes for a `ride` group or an ungrouped event.

Solver: the two legs are not paired with each other (`pairs` reads leg keys, the mode row is leg `''`), so the drop-off and the pick-up may go to different drivers and the driver goes home between, exactly as a split event's legs today.

## 3. Routes, agent, hand path

`POST /api/events/ride_group` body gains `mode: 'ride' | 'one'` (absent = keep / `ride` as §1). A ValueError is a 400 with its words. `DELETE /api/events/{event_id}/ride_group` on a merged leg id (`{first}_dropoff`) resolves to the parent row.

`GroupEventsRideTogetherTool.as_one: Optional[bool]` (`true` = "one drop-off at the first, one pick-up at the last; everyone waits at the venue until the last one ends"); `group_by_titles(..., mode=None)` passes it; the success message says `as one event: one drop-off at 9:00 and one pick-up at 14:00` for `one`.

Schedule page:

- `chooseDropAction`: when both cards are whole events (not legs) at the same place, a third button `One drop-off, one pick-up` resolving `group_one`, and the dialog text gains: `Same place: "One drop-off, one pick-up" treats them as one event — a single drop-off at the first start and a single pick-up at the last end. Everyone waits at the venue until the last one ends.` `rideTogether(ids, mode)` sends the mode.
- The chip: `stRideGroupOf(ev)` for a leg whose `ride_group_mode === 'one'` returns `ev.ride_groups['']` so both merged legs wear it. `openRideGroupChip` draws an `openCCConfirmModal` with buttons `Keep`, `Ungroup`, and the mode switch (`One drop-off, one pick-up` when the group is `ride` and the partners share the place; `Ride together only` when it is `one`); the switch posts the group's member ids with the new mode. The ungroup of a merged leg sends the parent id.

## 4. Tests (Claude, first)

`tests/test_ride_group_as_one.py`:

1. The store carries the mode; `group(mode='one')` writes it on every row, a later `group()` of the same members keeps it, `mode='ride'` clears it; different places refuse with the words; a leg id means its parent.
2. `merge_as_one`: two members 9-10 and 10-11 at the Pool: one drop-off at 9:00 and one pick-up at 11:00 hung off the first, titles joined, calendar ids the union, `original_end` 11:00 on both; a gap (10:30-11:30) still merges; three members; a member alone is no merge; a `stay` override on the second member is no merge; different places is no merge; a `ride` group is no merge.
3. The refresh actually runs it: a household with two calendar events at one place grouped `one`; the cached schedule has `gev1_dropoff` at 16:00 and `gev1_pickup` at 20:00, no `gev2_*` leg and no whole `gev2` assignment, both legs assigned; the same two with mode `ride` give four legs (the two-hour default splits each).
4. Routes: POST with `mode: 'one'` writes it, with different places is a 400, DELETE on `gev1_dropoff` ungroups the parent; the agent tool with `as_one` groups and says it.
5. The hand path exists in the templates (the third button, the chip's mode switch).

`tests/test_ride_groups_live.py`: the drop dialog at the pool now lists `Cancel`, `Group Events`, `One drop-off, one pick-up` (same column) and the four with `Assign to Jeff`; a new scenario picks the third button, the re-solve shows `swim_dropoff` at 9:00 and `swim_pickup` at 11:05 and no `dive` leg, both wear the chip, the chip switches back to ride together.

## Out of scope

Automatic merging of any same-place contiguous group (a hand choice stays a hand choice). A merged block across two drivers. The editor showing the block's span on a merged leg (it shows the first member, see the leg-editor spec).
