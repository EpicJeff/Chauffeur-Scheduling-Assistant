# The Drive Sheet

*Built v2.291.0. The screen a driver has open while they are driving.*

## The gap this closes

Starting a drive already worked: tap a leg, tap **Start Drive**, the ETA is
priced at that tap and the family hears "Dad is on the way". Then the app went
quiet, and the phone locked. Everything the drive needed after that moment —
did I get everyone, am I going to be late, where do I go next — happened
somewhere other than here.

Worse, the app went blind. Arrival auto-complete (`services/drive_arrival.py`)
completes a started leg when the driver is verifiably AT the destination, but
its only eyes were `ha_person_entity` and the car's device tracker. A household
without the Home Assistant companion app on the driver's phone never had a
position, so their legs never self-completed and every drive ended in a nudge
push asking a question the app could have answered itself.

So the sheet is not only a convenience screen. **It is the position source for
households with no HA on the phone** — which is the reason it earns the screen
wake lock rather than just borrowing it.

## Shape

One sheet, two states, opened by tapping a leg on the Drives timeline (or
resumed automatically when a leg of mine is already `in_progress`).

### Pre-drive — before Start

| Element | Why it is here |
| --- | --- |
| Destination + address | What the drive is |
| Car chip, with a fuel/charge warning when low | Reuses `car_fuel_warn_pct` / `car_battery_warn_pct`; the one screen where "you're at 11%" is actionable |
| **Roll call** — one big chip per passenger | "Gotta make sure they have everyone." Tapping toggles aboard / not here |
| Prep kit, per item | A loading checklist belongs at the car, before pulling out |
| Start Drive · Mark Completed · Not Staying | Unchanged from the old action sheet |

### En route — after Start

| Element | Why it is here |
| --- | --- |
| Destination + **arriving about 4:12** | The stored `eta_ts` from the Start tap |
| Google / Apple / Waze | Unchanged. This sheet never draws a map — navigation apps own that |
| Quick messages | One tap each, no typing while driving |
| **Send my ETA** | Prices from the current fix and shares it |
| **Arrived** | The same `tap_check` the arrival push runs |
| Roll call (collapsed), prep (collapsed) | Still reachable, no longer the point |
| **Next drive today** — *"Next: Swim Practice · leave 5:40"*, or *"Last drive of the day"* | The real question at a destination |
| Not Staying / Staying | Unchanged |
| Location + awake banner, with a stop control | Never invisible tracking |

## Decisions

**One ETA path, not two.** The obvious design is a "Running Late" button. It
was rejected: `drive_arrival` already computes ETAs at the Start tap, parks a
recomputed one on the arrival check (`pending_eta_ts`), and shares it on the
driver's explicit tap. A separate Running-Late number is a second ETA that can
disagree with the first. **Send my ETA** always prices from the current fix and
always shares, which is honest whether the driver is early, on time or late —
and it keeps the never-narrate-lateness rule, because it is still the driver's
own tap.

**Gate on who is waiting, not on route type.** "Only for a pickup route" misses
the run home from practice, where a kid is standing outside. `_leg_is_toward_kids`
already encodes exactly this (a `init_*_1` leg or a `_pickup` slice), so the
quick messages and the ETA share use that instead.

**The roll call never gates anything.** A driver who does not tap it completes
the drive exactly as before. It records what somebody chose to record; a
half-filled roll call is normal and means nothing bad.

**Location sharing and keep-awake are DEVICE choices, not household settings.**
They live in `localStorage` with a toggle in the sheet, not in `Settings` — one
phone in the family declining to share position is a preference about that
phone, and routing it through a household setting would let one parent's choice
silence another's. Defaults: both on.

**No phone numbers.** A "call the passenger" button was cut: member records
carry no phone number, and adding one to make a button work is a data model
change wearing a feature's clothes. The quick messages use the lanes the app
already owns.

**The next drive is today's, or none.** The schedule cache holds days either
side, and the first cut answered with tomorrow morning's school run once the
day was over. That is worse than answering nothing — it reads as "you are not
finished" to somebody who is. The window is the current drive's own date (so a
drive across midnight keeps talking about the night it belongs to), a finished
day says so, and a leg whose driver cannot be resolved claims neither.

**Nothing on this sheet requires reading while moving.** Every action is a
single large target and every one is safe to leave untapped. That is why there
is no map, no turn list, and no confirm dialog with two similar buttons.

## Mechanics

`GET /api/drive_sheet/{leg_id}` assembles everything in one call — destination,
ETA, passengers with their roll-call state, prep items, car levels, the next
drive, and which quick messages apply. The client draws it; it computes nothing
the server could have said.

`POST /api/drive_status/ping` is the position lane. While the en-route sheet is
open the client posts a fix every 45 seconds; the server stores it on the member
(`member_positions`) and immediately runs the arrival check for that leg, so a
drive completes itself the moment the car reaches the destination. Those
positions also back-fill `_driver_position` in `drive_arrival` and the family
map, which is how a household with no HA companion app gets a moving dot at all.

`POST /api/drive_status/roll_call` toggles one passenger.
`POST /api/drive_status/message` sends one canned message to the waiting
audience — into the family chat as a real message, and out over the same lanes
as every other family push.
`POST /api/drive_status/send_eta` prices from the fix and shares.

## What the agent can already do

`update_drive_status` and `start_route` cover starting and completing by voice.
The roll call, the canned messages and the ETA share are hand-path-only for now
and that is the right way round — they are all "I am in the car right now"
actions, and the hand is already on the phone.
