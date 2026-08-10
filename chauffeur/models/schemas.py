from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any, Dict
from datetime import datetime
import uuid
import time

class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    role: str
    content: str
    timestamp: float = Field(default_factory=time.time)

class Conversation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: str = "general" # 'general', 'schedule', 'errands', 'trips'
    mode: str = "standard" # 'standard', 'planner'
    title: str = "New Conversation"
    context_id: Optional[str] = None # Trip ID, Errand ID, etc.
    messages: List[Message] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
class Event(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    location: Optional[str] = None
    description: Optional[str] = None
    calendar_ids: List[str]
    recurring_event_id: Optional[str] = None
    original_calendar_ids: List[str] = Field(default_factory=list)
    source_event_ids: List[str]
    all_day: bool = False
    event_type: str = "standard"
    original_start: Optional[datetime] = None
    original_end: Optional[datetime] = None
    original_event_id: Optional[str] = None
    needs_triage: bool = False
    app_config: Optional[dict] = None
    # Optional events, phase 2: what the family chose about THIS occurrence.
    # 'attend' -> full weight, real commitment; 'skip' -> out of the solve,
    # still drawn; None -> undecided, goes if it fits. Stamped each refresh
    # from storage.optional_decisions (services/optional_events.py).
    optional_decision: Optional[str] = None
    trip_id: Optional[str] = None
    poi_id: Optional[str] = None
    # Set by the refresh when every passenger on the event is away on a
    # background trip: excluded from solving but still shown on the calendar.
    trip_suppressed: bool = False
    # THE WHOLE TRIP, carried on every daily slice of it.
    #
    # A background trip is cut into one event per day for the UI and the
    # solver, and each slice's own start/end are that DAY's — so anything
    # reading the slices could only see as much of the trip as the solve
    # window happened to contain. Slices before the window are never created
    # at all, which meant a five-day camp that started on Monday reported
    # itself as beginning on whatever day the window opened, every day, and
    # kept announcing "begins!" to the kids until it ended. These two say what
    # the trip actually is, independently of how much of it is in view.
    span_start: Optional[datetime] = None
    span_end: Optional[datetime] = None

class Driver(BaseModel):
    id: str
    name: str
    color_code: str
    group: str = 'primary'
    priority_index: int = 1
    preferred_start: Optional[str] = None
    preferred_end: Optional[str] = None
    home_location: Optional[str] = None
    is_disabled: bool = False
    calendar_ids: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    preferred_maps_provider: str = 'google'
    phone_number: Optional[str] = None
    cell_carrier: Optional[str] = None
    bio: Optional[str] = ""
    max_passengers: Optional[int] = None  # graduated-licensing cap, independent of car

class Passenger(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    calendar_ids: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    requires_attendance: bool = False
    bio: Optional[str] = ""

class CarUnavailableRange(BaseModel):
    start: str                      # ISO date, inclusive
    end: str                        # ISO date, inclusive
    reason: Optional[str] = ""

class Car(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    icon: Optional[str] = None      # emoji; None -> generic car glyph
    image: Optional[str] = None     # small data-URL photo (~128px); shown where chips have room
    color_code: str = '#6b7280'
    seat_capacity: int = 4          # passenger seats, excluding the driver
    # Drivers permitted behind the wheel. A driver listed on NO car keeps an
    # implicit personal car (solver ignores cars for them entirely).
    allowed_driver_ids: List[str] = Field(default_factory=list)
    allowed_passenger_ids: Optional[List[str]] = None  # None = anyone fits (no car-seat restriction)
    default_driver_id: Optional[str] = None
    unavailable_ranges: List[CarUnavailableRange] = Field(default_factory=list)
    is_disabled: bool = False
    notes: Optional[str] = ""
    # C2 telemetry (docs/car_telemetry_design.md): explicit HA entity mapping,
    # no auto-discovery — car integrations vary too much. All None -> the car
    # is untouched by every telemetry feature.
    ha_device_tracker: Optional[str] = None   # device_tracker.* — location
    ha_battery_entity: Optional[str] = None   # sensor.* — EV charge %
    ha_fuel_entity: Optional[str] = None      # sensor.* — fuel level %
    ha_range_entity: Optional[str] = None     # sensor.* — remaining range (display only)

class FamilyMember(BaseModel):
    # Overlay entity: one record per human. Drivers/passengers stay the
    # solver's source of truth; members link to them via driver_id /
    # passenger_id and carry hub-level identity (avatar, HA mappings).
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    color_code: str = '#3b82f6'
    avatar: Optional[str] = None  # emoji or static path; None -> initials
    image: Optional[str] = None   # small data-URL photo (~128px); wins over avatar where surfaces have room
    bio: Optional[str] = ""
    can_drive: bool = False
    is_child: bool = False  # legacy display flag, kept in sync with role
    # parent: admin powers (verify chores, reset PINs). adult: full family
    # participation, no admin. child: family + kid lens + points economy.
    # helper: external (hired driver/nanny) — driving surfaces only.
    role: str = 'adult'
    # COVERING IS NOT CARRYING (load arc). `household` contributions count as
    # the household's load; `assist` ones do not. A teenager who drives, a
    # hired nanny, a grandparent who cooks Sunday dinner all COVER work
    # without CARRYING the household's share of it — and the tier lives here,
    # on the member, rather than on the driver record, because assisting is
    # not a driving-specific thing: a teen can cook a night, a nanny can
    # supervise homework. Hanging it on `Driver` would have leaked the moment
    # a teenager cooked, making the parents' split look even.
    # `helper` is always assist regardless of what this says.
    assist_tier: str = 'household'          # household | assist
    # --- Stages: the child that grows (load arc A4) ---
    # A birthdate only ever SUGGESTS a stage; `stage_override` pins it, and
    # `capability_overrides` bends a single switch, because kids differ and a
    # single number should not be destiny. `stage_acknowledged` is what a
    # parent has confirmed — growing up is GRANTED, never silently switched,
    # so the suggestion moving ahead of the acknowledgement is what raises the
    # "Ellie is a Navigator now" moment rather than the app quietly changing.
    # Quiet hours ON THE IDENTITY (load arc A6). A kid's window is a
    # protection set for them by someone else, and lives in household config;
    # an adult's is a preference owned by the self, and lives here — a
    # night-shift parent, a 6am riser and a hired driver share no window.
    # Absent = the household default (21:00–08:00), NEVER "off". Urgent sends
    # (a departure push, a drive reassigned today) escape the window.
    quiet_start: Optional[str] = None       # HH:MM
    quiet_end: Optional[str] = None         # HH:MM
    # Merged stale backlog item: members with both web push and HA notify got
    # everything twice. 'all' keeps the v1 behaviour.
    notify_lanes: str = 'all'               # all | push | ha
    birthdate: Optional[str] = None         # YYYY-MM-DD
    stage_override: Optional[str] = None    # sprout | explorer | navigator | copilot
    stage_acknowledged: Optional[str] = None
    capability_overrides: Dict[str, Any] = Field(default_factory=dict)
    driver_id: Optional[str] = None
    passenger_id: Optional[str] = None
    # Google calendars belonging to THIS PERSON — set in exactly one place
    # (Config -> People -> Identity). Driver.calendar_ids and
    # Passenger.calendar_ids are derived mirrors of this list, rewritten on
    # every save (storage.set_member_calendars), so the solver and matcher can
    # go on reading the records they always read. What a calendar MEANS still
    # comes from the links: a passenger link makes its events ride demand, a
    # driver link makes them busy-time, and a person with NEITHER link (drives
    # themselves, chauffeurs nobody) simply appears on the family calendar.
    calendar_ids: List[str] = Field(default_factory=list)
    ha_person_entity: Optional[str] = None    # e.g. person.jeff
    notify_service: Optional[str] = None      # e.g. notify.mobile_app_jeffs_iphone
    media_player_entity: Optional[str] = None
    # School hours (K4c, children only): drive the school-day-end pickup
    # push and the morning launch line. Empty = no school-hour features.
    school_hours_start: Optional[str] = None  # HH:MM
    school_hours_end: Optional[str] = None    # HH:MM
    # Aftercare as a care window (load arc A5, children only). The actual
    # fallback most two-income families use, previously inexpressible: on an
    # aftercare day the pickup deadline is `aftercare_until`, not the school
    # bell, which widens the solver's window and lets the dismissal push tell
    # the child the truth ("you're in aftercare today, Mom gets you at 5:30").
    # Days are weekday ints (0=Mon). No cost, no sessions — we don't do money.
    aftercare_days: List[int] = Field(default_factory=list)
    aftercare_until: Optional[str] = None     # HH:MM
    aftercare_place: Optional[str] = ""       # "Extended Day", a name the kid knows
    # Dietary constraints (meals arc M3), mirroring the SOLVER's own hard/soft
    # grammar: `dietary_avoid` is HARD — a meal tagged with one of these is
    # filtered out entirely whenever this person is eating (allergies).
    # `dietary_dislike` is SOFT — it demotes a meal in ranking and never
    # removes it (picky eaters are a preference, not a constraint).
    dietary_avoid: List[str] = Field(default_factory=list)
    dietary_dislike: List[str] = Field(default_factory=list)
    # School bus (bus arc, children only — services/bus.py). bus_am_stop_time
    # is the opt-in switch; HCTB live data auto-discovers via first name.
    bus_am_stop_time: Optional[str] = None    # HH:MM — morning pickup at stop
    bus_pm_stop_time: Optional[str] = None    # HH:MM — usual afternoon drop
    bus_walk_mins: Optional[int] = None       # walk to the stop (default 5)
    bus_entity_prefix: Optional[str] = None   # HCTB entity prefix override
    # Explicit HA entity ids for non-HCTB bus platforms (blank = HCTB
    # auto-discovery): stop-ETA sensors + an "is running" binary sensor.
    bus_am_eta_entity: Optional[str] = None
    bus_pm_eta_entity: Optional[str] = None
    bus_active_entity: Optional[str] = None
    pin_hash: Optional[str] = None            # pbkdf2; never exposed via API
    pin_salt: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

class ChatChannel(BaseModel):
    # Family messaging. Table names are chat_* to stay clear of the agent's
    # 'conversations' store.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = 'dm'  # 'family' | 'dm' | 'group' | 'event'
    member_ids: List[str] = Field(default_factory=list)  # empty for 'family' = everyone
    dm_key: Optional[str] = None       # sorted "a:b[:c...]" member key for dm/group
                                       # get-or-create (indexed; dm=2 ids, group>=3
                                       # so the keys never collide across kinds)
    event_id: Optional[str] = None     # kind='event': calendar event instance id
    event_end: Optional[str] = None    # ISO end of the event; drives auto-archive
    title: str = ""                    # event-title snapshot / optional group name;
                                       # dm/family titles render client-side
    created_at: float = Field(default_factory=time.time)
    archived: bool = False

class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    channel_id: str
    sender_member_id: str
    ts: float = Field(default_factory=time.time)
    type: str = 'text'  # 'text' | 'audio' | 'system' (audio reserved for voice memos)
    body: str
    # Photo moments (Presence slice): {kind:'photo', data_url, w, h} — a
    # client-downscaled JPEG rendition stored inline on the family's own box
    # (avatar precedent, bigger). Video stays out of v1.
    attachment: Optional[dict] = None
    card: Optional[dict] = None  # interactive card (e.g. action_proposal) rendered in chat
    # {emoji: [member_id, ...]} — toggled via /api/messages/{id}/react.
    # Reactions never push (the sender at the game is fire-and-forget).
    reactions: Dict[str, List[str]] = Field(default_factory=dict)
    # Set by /api/messages/{id} PATCH; surfaces render an "edited" marker.
    # Absent on every message that has never been edited.
    edited_ts: Optional[float] = None

class ChannelRead(BaseModel):
    channel_id: str
    member_id: str
    last_read_ts: float = 0.0

class Chore(BaseModel):
    # Family chore pot: self-claimed (marketplace, not solver-assigned).
    # Lifecycle: open -> claimed -> done -> verified | rejected (back to
    # claimed for redo). Recurring chores reopen after reopens_on.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    emoji: Optional[str] = None  # hand-picked glyph; None -> kid_glyphs keyword guess
    description: Optional[str] = ""
    points: int = 10
    recurrence: str = 'once'  # once | daily | weekly | monthly
    eligible_member_ids: List[str] = Field(default_factory=list)  # empty = any non-helper
    state: str = 'open'  # open | claimed | done | verified
    claimed_by: Optional[str] = None
    claimed_at: Optional[float] = None
    done_at: Optional[float] = None
    verified_by: Optional[str] = None
    verified_at: Optional[float] = None
    rejected_reason: Optional[str] = None
    reopens_on: Optional[str] = None  # ISO date; recurring verified reopen
    created_at: float = Field(default_factory=time.time)

class KidTask(BaseModel):
    # School/deadline task on a kid's own list (kid-support arc K4a).
    # Due dates and events only — never grades. No points (school is not
    # paid work) and no streaks (school pressure is what we're reducing).
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    member_id: str                     # the child this belongs to
    title: str
    due_date: str                      # YYYY-MM-DD
    kind: str = 'other'                # homework | test | project | bring | other
    notes: Optional[str] = ""
    source: str = 'manual'             # manual | agent | intake | ics | classroom
    source_ref: Optional[str] = None   # feed uid / message id for dedupe (K4b)
    status: str = 'open'               # open | done
    done_at: Optional[float] = None
    created_at: float = Field(default_factory=time.time)
    created_by_member_id: Optional[str] = None

class RoutineItem(BaseModel):
    # Personal daily-routine template ("brush teeth", "homework"): per member,
    # optional time of day, day-of-week mask. No points — streaks instead.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    member_id: str
    title: str
    emoji: Optional[str] = None  # hand-picked glyph; None -> kid_glyphs keyword guess
    # Which source item a routine-copy created this from. Lineage, not
    # content, is what makes re-copying safe around edits: retime or rename
    # the copy and it still says "I am Alex's a1", so a re-copy skips it
    # instead of re-importing the original.
    copied_from: Optional[str] = None
    time_of_day: Optional[str] = None      # "HH:MM" -> plotted on My Day
    days_of_week: List[int] = Field(default_factory=list)  # 0=Mon..6=Sun; empty = every day
    created_at: float = Field(default_factory=time.time)

class StatusBeat(BaseModel):
    # One beat on a StatusProtocol's timeline: (when, who, what) — the model
    # from docs/presence_status_design.md, family-authored. `when` is an
    # anchor±offset so the timeline is RELATIVE and reusable: chemo recovery
    # is start+1/start+2 (the hard days come AFTER the one-day event), a trip
    # prep-reminder is start-2, a homecoming beat is end+0. Offsets may land
    # outside the instance's own dates — that's the point.
    anchor: str = 'start'          # 'start' | 'end' of the dated instance
    offset_days: int = 0           # negative = before the anchor
    # kids -> kid surfaces (digest lead, My Day, dismissal push — no extra
    # pings); adults -> co-parent DM morning-of (affected member excluded);
    # affected -> the member themselves; everyone -> all of the above.
    audience: str = 'kids'         # 'kids' | 'adults' | 'affected' | 'everyone'
    message: str = ""              # the family's words for that day, verbatim
    # Optional need override FOR THAT DAY (e.g. protocol default 'cover' on
    # treatment day, beat 'give_space' on day+2 when driving is fine again).
    # A cover/help beat outside the instance dates extends solver
    # unavailability to that day too.
    need: Optional[str] = None

class StatusProtocol(BaseModel):
    # Presence & Status arc P1 (docs/presence_status_design.md): a reusable
    # family day-type ("Chemo Day", "Night Shift", "Trip Day") — what it
    # means, what the household needs, and how we tell everyone. Authored
    # once, in the family's OWN words (the system schedules and delivers the
    # messages; it never composes them). The emoji/name is just the skin.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str                            # "Chemo Day" — the family's label
    emoji: str = '💙'
    member_id: Optional[str] = None      # the affected member (usually a parent)
    # What the household needs on these days. Slice 1 stores + displays it;
    # the solver hooks (cover -> drop from rotation, clear_deck -> protect
    # the evening) are the next slice.
    # cover: parent out of the rotation | help: other parent is caregiving,
    # bring in outside help | clear_deck: family-time day, decline optional
    # things | give_space: home but resting, keep it low-key.
    need: str = 'give_space'
    kid_message: str = ""                # the words the kids get: plan + something they can do
    adult_message: str = ""              # co-parent logistics message
    # Calendar trigger words ("chemo", "night shift") — a matching calendar
    # event auto-sets the day (P2 sweep), spanning the event's own dates.
    keywords: List[str] = Field(default_factory=list)
    # P3 trip timeline: optional nightly call window during a multi-day span
    # ("19:30"). Rendered SOFT everywhere ("around 7:30") — a missed call
    # must read as "catch you tomorrow", never a broken chain.
    call_time: Optional[str] = None      # HH:MM
    # The timeline: relative beats (see StatusBeat). Empty = the built-in
    # positional defaults (day 1 message / "day N of M" / home day) — beats
    # override them wherever one lands.
    beats: List[StatusBeat] = Field(default_factory=list)
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)

class StatusDay(BaseModel):
    # One dated instance of a StatusProtocol. Date-bound BY DESIGN: a status
    # never lingers past its day, so stale-dial lies (worse than silence) are
    # structurally impossible. note is the one-tap "today's different" nudge.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    date: str                            # YYYY-MM-DD (span start)
    protocol_id: str
    # P3: an optional span end (inclusive) turns the instance into a
    # multi-day timeline (a trip, a hospital stay). None/equal = one day.
    # Surfaces become day-position aware: heads-up on day 1, "day N of M"
    # in the middle, an excited home-day beat on the last.
    end_date: Optional[str] = None       # YYYY-MM-DD
    note: str = ""
    set_by: Optional[str] = None         # member id; None = agent/system
    set_at: float = Field(default_factory=time.time)
    # P2 calendar trigger: 'calendar' = auto-set by the keyword sweep (the
    # calendar knows — the set-burden lands on nobody). source_detail carries
    # the matched event title. Clearing a calendar-set day writes a tombstone
    # so the sweep never re-sets what a parent dismissed.
    source: str = 'manual'               # 'manual' | 'calendar'
    source_detail: Optional[str] = None

class PrepKit(BaseModel):
    # Packing list matched to events with the SAME filter criteria routing
    # rules use (evaluated by the solver's does_event_match_rule, so semantics
    # are identical by construction: AND across criteria types, any/all
    # toggles within keywords and passengers). Items surface on My Day ride
    # cards and in the tomorrow digest push.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    items: List[str] = Field(default_factory=list)
    enabled: bool = True
    keywords: List[str] = Field(default_factory=list)
    keywords_match_all: bool = False
    passenger_ids: List[str] = Field(default_factory=list)
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)  # 0=Mon..6=Sun
    time_start: Optional[str] = None   # "HH:MM" — event starts at/after
    time_end: Optional[str] = None     # "HH:MM" — event ends at/before
    start_date: Optional[str] = None   # YYYY-MM-DD window
    end_date: Optional[str] = None
    location: Optional[str] = None     # substring match
    created_at: float = Field(default_factory=time.time)

class Reward(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    description: Optional[str] = ""
    cost: int = 50
    # Family goal: children pool pledges toward one shared reward (movie
    # night, eating out). Pledges are holds — see PoolContribution.
    pooled: bool = False
    # Pooled only: minimum pledge per child before a parent can grant
    # without forcing (0 = no minimum). Keeps one kid from riding free.
    min_share: int = 0
    created_at: float = Field(default_factory=time.time)

class Redemption(BaseModel):
    # Kid requests, parent approves (ledger deduction) or denies.
    # Pooled grants write one approved row with member_id=None, pooled=True
    # and the per-child split in contributions.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    reward_id: str
    reward_title: str
    cost: int
    member_id: Optional[str] = None
    state: str = 'pending'  # pending | approved | denied
    pooled: bool = False
    contributions: List[dict] = Field(default_factory=list)  # [{member_id, amount}]
    requested_at: float = Field(default_factory=time.time)
    decided_by: Optional[str] = None
    decided_at: Optional[float] = None

class PoolContribution(BaseModel):
    # A pledge toward a pooled reward. Holds points exactly like a pending
    # redemption (spendable = balance - pending - pledges); nothing touches
    # the ledger until a parent grants the pool, so withdrawing a pledge or
    # canceling the pool needs no refund machinery.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    reward_id: str
    member_id: str
    amount: int
    ts: float = Field(default_factory=time.time)

class PointsEntry(BaseModel):
    # Append-only ledger: balances are sums, history is the table.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    member_id: str
    delta: int
    reason: str = 'chore'  # chore | adjust | redeem (future)
    chore_id: Optional[str] = None
    chore_title: Optional[str] = None
    by_member_id: Optional[str] = None  # verifier
    ts: float = Field(default_factory=time.time)

class EventFilter(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    keywords_match_all: bool = False
    passenger_ids: List[str] = Field(default_factory=list)
    passengers: Any = None
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None

class Rule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    driver_id: str
    event_keyword: Optional[str] = None # Deprecated
    constraint_type: str  # e.g., 'required', 'preferred', 'unavailable', 'tolerance', 'duplicate', 'group', 'buffer'
    duplicate_action: Optional[str] = None
    tolerance_mins: int = 0
    tolerance_type: str = 'both'  # 'arrival', 'departure', 'both'
    grouping_period: str = 'daily'
    buffer_before_mins: int = 0
    buffer_after_mins: int = 0
    attendance_action: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    keywords_match_all: bool = False
    passenger_ids: List[str] = Field(default_factory=list)
    passengers: Any = None
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    filter_sets: List[EventFilter] = Field(default_factory=list)
    is_ai_generated: bool = False
    is_enabled: bool = True

class PriorityRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    match_type: Optional[str] = None       # Deprecated
    match_value: Optional[str] = None      # Deprecated
    weight_modifier: int
    keywords: List[str] = Field(default_factory=list)
    keywords_match_all: bool = False
    passenger_ids: List[str] = Field(default_factory=list)
    passengers: Any = None
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    is_ai_generated: bool = False
    is_enabled: bool = True

class ManualOverride(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_id: str
    driver_id: str
    event_title: Optional[str] = None
    date_str: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    # 'pwa' when a driver self-assigned via the PWA Assign-to-Me button.
    # Used to suppress the redundant "you gained this" push for that driver.
    source: Optional[str] = None

class ProtectedCommitment(BaseModel):
    """A standing piece of somebody's OWN life the solver defends (load arc
    A6). A run club, therapy, choir, a standing coffee.

    The finding this answers: an adult's own life existed in the app only as
    an OBSTACLE — a personal calendar event's entire function was to make you
    unavailable to drive. There was no concept of your time being FOR
    something, nothing that noticed when it eroded, and nothing that made it
    real by covering it. The app cannot make anyone rested; it can make sure
    the time exists, is defended, and is covered.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    member_id: str
    title: str                              # "Thursday run", in their words
    days_of_week: List[int] = Field(default_factory=list)   # 0=Mon
    time_start: str = "18:00"               # HH:MM
    time_end: str = "20:00"
    # When true, the watcher flags open drives that collide with the window a
    # few days out — wishing for time does not produce time; covered time does.
    needs_coverage: bool = False
    active: bool = True
    created_at: float = Field(default_factory=time.time)

class Request(BaseModel):
    """An ask, with a state (load arc A3).

    Two problems that turned out to be the same shape:

    A kid could REPORT but not ASK. Kid-as-sensor handles facts well
    ("practice moved") and routes them as parent-approvable cards, but there
    was no object for *"can you get me at 3 instead of 4"* — the single most
    common kid-to-parent logistics message in existence. It lived only as free
    text.

    An adult who wanted out of a drive could only TAKE it from their partner:
    the override lands and the other parent gets a bare "Schedule Updated"
    push with no indication it was an ask. That is socially terrible, and a
    large part of why the non-driving parent feels informed-at rather than
    invited.

    One object for both, because the state machine, the surfaces and the
    notification rails are identical — and because a teenager asking for a
    ride and a mother asking for Thursday evening should ride the same rails.

    **A request is always answered.** Silence is the failure mode this exists
    to fix, so an untouched request expires loudly rather than fading.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    from_member: str
    # None = the household (in practice: the parents). "Somebody please take
    # this" is a real ask and must not require picking a victim.
    to_member: Optional[str] = None
    kind: str = 'other'   # ride_change | pickup_early | swap_drive | take_task | cover | permission | other
    # What it is ABOUT: an event id, a task id, a date. Accepting a request
    # that names one performs the change — the request IS the mechanism, not
    # a note about one.
    subject_ref: Optional[str] = None
    subject_label: Optional[str] = ""
    body: str = ""                      # their own words, never generated
    status: str = 'open'                # open | accepted | declined | expired | cancelled
    reason: Optional[str] = ""          # why it was declined — blameless, and better than silence
    decided_by: Optional[str] = None
    decided_at: Optional[float] = None
    expires_at: Optional[float] = None
    created_at: float = Field(default_factory=time.time)

class HouseholdTask(BaseModel):
    """Work with a deadline and no destination (load arc A2 — the keystone).

    **Task = do something. Errand = go somewhere.** `Errand` requires a
    `location` and a `duration_mins` because an errand IS a drive the solver
    routes — so "sign the permission slip", "call the pediatrician", "renew
    the passports", "$12 for picture day" had nowhere to live at all. Keeping
    the line crisp is what stops "renew the passports" becoming a routing job
    competing for a Tuesday slot.

    `assigned_to` is OPTIONAL, and unassigned is a real state meaning *the
    household owes this*. That is where delegation and whose-turn live; an
    object that forces an owner at creation just moves the deciding back onto
    whoever typed it.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    notes: Optional[str] = ""
    due_date: Optional[str] = None          # YYYY-MM-DD; a task may have no deadline
    assigned_to: Optional[str] = None       # member id; None = the household owes it
    created_by: Optional[str] = None
    status: str = 'open'                    # open | done
    completed_at: Optional[float] = None
    completed_by: Optional[str] = None
    # Yearly is the point of this field: errands offer daily/weekly/monthly,
    # and annual is precisely the life-admin cadence — inspection, physicals,
    # passports, registration windows.
    recurrence: str = 'none'                # none | daily | weekly | monthly | yearly
    category: Optional[str] = 'general'     # paperwork | health | money | home | school | general
    effort_mins: Optional[int] = None
    # What this belongs to, when it belongs to something.
    occasion_id: Optional[str] = None
    member_id: Optional[str] = None         # the person it is ABOUT (not who does it)
    event_id: Optional[str] = None
    # Who covered it, when the answer is "somebody outside the house" (A1).
    assist_contact_id: Optional[str] = None
    source: str = 'manual'                  # manual | agent | intake | ics
    source_ref: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

class AssistContact(BaseModel):
    """Someone outside the household who does work for it (load arc A1).

    A carpool parent, the neighbour who comes to do the dishes, a sitter.
    **Carpool is a kind of help, not a kind of person** — which is why this is
    not `CarpoolDriver`: household work gets carried by people the app could
    not see at all, and that is the finding the whole load arc is built on.

    NOT a `FamilyMember`: no login, no PIN, no headcount, no wall board, no
    DMs. They are a contact precisely BECAUSE they have no account, which is
    the clean line against the `helper` role — an external person who DOES
    hold the app. Three points on one axis: a contact we only record, a
    `helper` with driving surfaces, a full member.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    phone: Optional[str] = ""
    email: Optional[str] = ""
    # How the family actually refers to them: "Emma's mom", "the Kellys' girl".
    relation_label: Optional[str] = ""
    # Free tags — carpool, housework, childcare, tutoring, pets. NOTHING
    # branches on this. Behaviour comes from what REFERENCES the contact: one
    # referenced by a drive is a carpool driver, one referenced by a chore is
    # house help. Branch on the tag instead and every new kind of help becomes
    # a code change, which is the trap this arc exists to walk the app out of.
    kinds: List[str] = Field(default_factory=list)
    # reciprocal | paid | volunteer. Earns its place: you owe a carpool parent
    # a TURN, you owe the girl who does the dishes MONEY, so turn-taking fires
    # for `reciprocal` and stays silent for `paid`. Not a reversal of the money
    # cut — no amounts, rates or balances are tracked anywhere.
    relationship: str = 'reciprocal'
    color_code: Optional[str] = None
    notes: Optional[str] = ""
    active: bool = True
    created_at: float = Field(default_factory=time.time)

class AssistAssignment(BaseModel):
    """This event is covered by someone outside the house.

    The third assignment state, alongside assigned-to-a-household-member and
    unassigned. To the solver a covered event is COVERED: not assignable, not
    unassigned, not ghost-eligible. It leaves the optimisation entirely, which
    is the whole point — outside help REMOVES load, and until now the app had
    no way to be told so. It also retires a standing false alarm: the watcher
    DM "🚨 No driver yet" for a ride that was always handled.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_id: str
    contact_id: str
    note: Optional[str] = ""
    created_at: float = Field(default_factory=time.time)

class StatusTier(BaseModel):
    name: str
    emoji: str = ''
    threshold: int = 0  # chore ladder: lifetime points earned; routine ladder: best-streak days

class Settings(BaseModel):
    # Evening push digest listing each driver's assignments for tomorrow.
    tomorrow_digest_enabled: bool = True
    tomorrow_digest_time: str = "20:00"  # HH:MM, server-local time
    # HA weather entity for the digest's forecast line. Empty = auto-detect
    # the first weather.* entity; weather silently drops out if HA is absent.
    weather_entity: str = ""
    # Weekly "Family Week in Review" recap Argyle posts into the family chat
    # channel: driving per driver, kid activities, chores/points, rewards,
    # routine completion. Sourced from evening daily_stats snapshots plus the
    # durable ledgers (services/family_digest.py).
    weekly_digest_enabled: bool = True
    weekly_digest_day: int = 6        # 0=Mon .. 6=Sun
    weekly_digest_time: str = "19:00"  # HH:MM, server-local time
    # Kid evening digest (kid-support arc K1): every child gets a "🌙
    # Tomorrow" Argyle DM (rides with resolved drivers, prep items, weather,
    # streak) after kid_digest_time — and the SAME content renders as a
    # per-kid strip on the routines kiosk (GET /api/kids/digests), so
    # phone-less kids see it on the wall panel. Kids with nothing tomorrow
    # get nothing.
    kid_digest_enabled: bool = True
    kid_digest_time: str = "19:30"    # HH:MM, server-local time
    # When the kiosk digest strip flips from TODAY to TOMORROW (family
    # request 2026-08-06: a "Tomorrow" board at 3pm answers the wrong
    # question). The evening DM is always tomorrow — it IS the look-ahead.
    kid_digest_cutover_time: str = "19:00"
    # Kid quiet hours: NO kid-facing sends inside this window (wraps
    # midnight; honored by the K1 digest and all future kid pushes). A
    # digest time inside the window never fires that day. Equal start/end
    # disables the window.
    kid_quiet_start: str = "20:30"
    kid_quiet_end: str = "07:00"
    # Where this family is willing to eat (meals arc M2). NOT physics — some
    # families eat full meals with utensils in the car, others won't eat in
    # the car at all. Default is PERMISSIVE: a wrong permission produces a
    # visible suggestion someone corrects in seconds, while a wrong
    # restriction hides eating slots invisibly and the feature just looks
    # useless. 'none' disables that modality's slots wholesale.
    # none | snack | handheld | full
    car_dining: str = "full"
    venue_dining: str = "full"
    # How a plate is built when nobody has said otherwise (meals arc M5).
    # A knob, not a rule: tonight's plate is editable, so this is only the
    # starting proposal.
    # The provisioning cycle (meals arc M6). Families do not plan "the next 7
    # days" — they plan up to the next grocery run, a day or two before it, and
    # buy for that span. Both of those are what the week plan is anchored to,
    # so the plan Argyle brings covers exactly what this trip has to buy for.
    # 0=Mon .. 6=Sun. UNSET means "work it out from our schedule" — a hardcoded
    # default here was wrong for exactly the family it shipped to (Saturday is
    # when their activities are, so it is the worst day for a 90-min trip).
    grocery_weekday: Optional[int] = None
    # How many people the cooking is for. 0/unset falls back to counting the
    # non-helper roster, which is a GUESS: a household is not a list of
    # profiles (people live elsewhere, a teenager eats at work). Overridable
    # on any single night via the plate's `serving_for`.
    household_headcount: int = 0
    grocery_plan_lead_days: int = 2   # ask "how does this look?" this early
    # How many nights one shop has to cover. Seven for most families, which is
    # why the span was hardcoded at 7 — but a household that shops every ten
    # days had three nights a cycle nothing ever bought for.
    grocery_cadence_days: int = 7
    meal_week_enabled: bool = True
    propose_shopping_errands: bool = True   # offer a trip for a list that has none
    # Prep reminders (M8). "The night before" is a human moment, not an
    # offset — this is when the household is still up and can start a soak.
    prep_reminders_enabled: bool = True
    prep_reminder_time: str = "20:30"       # evening nudge for night-before prep
    prep_morning_time: str = "08:00"        # morning-of prep
    # The kitchen as a resource model (occasions arc O0). These replace the
    # constants that were hardcoded inside `_totals_from_dishes` — cook=1 and
    # equipment=infinity — and the defaults reproduce exactly the old
    # behaviour, which is the reduction property the tests assert.
    kitchen_ovens: int = 1
    kitchen_burners: int = 4
    kitchen_cooks: int = 1                  # everyday default; a plate may raise it
    # Walmart cart (arc W1). The store id localizes the cart; the Impact
    # Radius trio is only used by families who have actually onboarded as
    # affiliates — the plain cart URL needs none of it and is the default.
    walmart_store_id: str = ""
    walmart_impact_publisher_id: str = ""
    walmart_impact_ad_id: str = ""
    walmart_impact_campaign_id: str = ""
    # School calendar (services/school.py): what a "school day" is. All
    # empty = plain weekday behavior. The designated calendar's all-day
    # events matching a no-school keyword mark school out; the year bounds
    # are how summer is known without guessing from event titles.
    school_calendar_id: str = ""
    school_year_start: str = ""       # YYYY-MM-DD, update once a year
    school_year_end: str = ""         # YYYY-MM-DD
    school_closed_keywords: str = ""  # comma list; empty = built-in default
    # Defaulted, and it MATTERS: POST /api/settings merges with
    # `exclude_unset=True` precisely so a client can send only the fields it
    # manages — but a required field makes every partial body a 422 before the
    # merge is ever reached. That silently broke the write half of settings
    # decentralisation: the meals page's "how we eat" panel, the kitchen
    # panel and the wall-panel setup all POST only their own keys and all got
    # "calendar_ids: Field required". The default cannot clobber a stored list
    # — unset fields are excluded from the merge, so absence still means
    # "leave it alone" — it only stops validation rejecting the request.
    calendar_ids: List[str] = Field(default_factory=list)
    # One of calendar_ids, starred in Config → General. The family's shared
    # calendar: intake proposals with no clear owner (and whole-family /
    # multi-member events) default here.
    default_calendar_id: str = ""
    # How many days the kiosk/dashboard renders. Display only.
    days_to_show: int = 7
    # How far ahead the schedule is actually built, progressively, one day at a
    # time. Independent of days_to_show: the wall panel showing 5 days must not
    # stop the solver from placing a monthly errand 30 days out.
    days_to_build: int = 30
    home_location: Optional[str] = None
    trip_hashtags: List[str] = Field(default_factory=list)
    # Cached durations come from Mapbox's free-flow 'driving' profile between
    # fixed addresses, so they do not go stale. A short TTL just re-buys the
    # same numbers: at 10 minutes this exceeded the 100k/month Matrix
    # allowance. Only shorten this if a traffic-aware profile is introduced.
    route_cache_duration_mins: int = 43200  # 30 days
    time_format_24h: bool = False
    disable_mapbox: bool = False
    disable_mapbox_matrix: bool = False
    disable_mapbox_directions: bool = False
    disable_mapbox_category: bool = False
    mapbox_matrix_limit: int = 90000
    mapbox_directions_limit: int = 90000
    mapbox_geocode_limit: int = 90000
    mapbox_searchbox_limit: int = 500
    mapbox_category_limit: int = 45000
    enable_mapbox_map_loads: bool = True
    mapbox_map_loads_limit: int = 45000
    llm_provider: str = ""
    llm_gemini_api_key: Optional[str] = None
    llm_gemini_model: str = "gemini-3.5-flash-lite"
    llm_ollama_url: str = "http://localhost:11434"
    llm_ollama_model: str = "qwen2.5:7b"
    # Family-hub / HA bridge. public_base_url is the family-facing HTTPS
    # origin (reverse proxy) used to build absolute deep links in
    # notifications. ha_base_url/ha_token are the dev fallback for the HA
    # API when not running as an add-on (supervisor token wins when present).
    public_base_url: str = ""
    ha_base_url: str = ""
    ha_token: str = ""
    # Music Assistant server for the Sendspin phone-player relay, e.g.
    # "ws://192.168.1.50:8927". Empty = auto-discover (official add-on
    # hostname, then the HA host on port 8927).
    ma_server_url: str = ""
    # Room announcements: HA area id -> the entity announce() must use there,
    # overriding the satellite-first/playing-first pick. Only rooms the family
    # has pinned appear; everything else resolves automatically.
    announce_targets: Dict[str, str] = Field(default_factory=dict)
    # Stages (load arc A4): the three ages where the kid bands change, stored
    # as CUTOFFS rather than four ranges — contiguous bands defined by cutoffs
    # cannot develop gaps or overlaps the way independently edited ranges can.
    # Defaults map to preschool / elementary / middle / high school; they are
    # configurable because school systems differ (US middle school usually
    # starts at 11-turning-12, so a fixed 12 puts a sixth grader in the wrong
    # stage for half the year).
    stage_cutoffs: List[int] = Field(default_factory=lambda: [6, 12, 15])
    family_philosophy: str = ""
    enable_standard_rules: bool = True
    enable_ai_rules: bool = True
    enable_standard_priority_rules: bool = True
    enable_ai_priority_rules: bool = True
    enable_ai_themes: bool = True
    # Car alerts (C2/C3, docs/car_telemetry_design.md): warn thresholds, the
    # family's home gas station (fuel-stop errand placement fallback), and
    # auto-approve for fuel-stop proposals. services/cars.py reads these off
    # the raw settings dict — the model fields exist so POST /api/settings
    # KEEPS them: Pydantic silently drops unknown fields, which ate every
    # "Save Alerts" click from v2.47 until v2.56.2.
    car_battery_warn_pct: float = 30
    car_fuel_warn_pct: float = 25
    car_auto_errand: bool = False
    car_fuel_station: str = ""
    # When True, the solver adds a quadratic penalty on each driver's total
    # load so work spreads across the roster instead of stacking onto the
    # highest-priority drivers ("bucket filling").
    load_balancing_enabled: bool = False
    # What "load" means: 'events' (count of events driven), 'driving_time'
    # (round-trip travel from the driver's home to each event — a proxy, since
    # true routes are only known after assignment), or 'occupied_time' (summed
    # event durations).
    load_balancing_metric: str = "occupied_time"
    # When False, the solver never invents "suggested driver" (ghost) routes
    # for unassigned events; they simply stay in the triage bucket.
    suggested_routes_enabled: bool = True
    # When True, Argyle watches the family chat for action-shaped messages and
    # offers a one-tap proposal card (implicit detection funnel). Opt-in: off by
    # default so the bot never butts into ordinary chatter.
    chat_suggestions_enabled: bool = False
    # Proactive parent watchers (services/watchers.py): a 30-minute sweep for
    # stuck state — unassigned events in the next 3 days, intake proposals
    # pending 3+ days, chores awaiting verification 48h+, week-old unclaimed
    # chores, stale reward requests, past-due errands, plus a WEEKLY prep-kit
    # idea check (the sweep's only LLM use; background tier). Each finding
    # notifies exactly once, delivered as ONE consolidated Argyle DM per
    # parent; quiet hours 21:00-08:00.
    proactive_watchers_enabled: bool = True
    # Customizable kid status tiers — two independent single-metric ladders.
    # None = built-in defaults (status_tiers.DEFAULT_CHORE_TIERS /
    # DEFAULT_ROUTINE_TIERS). In the model so config-page saves (a strict-
    # whitelist merge) never drop them.
    chore_status_tiers: Optional[List[StatusTier]] = None      # thresholds = lifetime points
    routine_status_tiers: Optional[List[StatusTier]] = None    # thresholds = best-streak days
    # Email intake (intake arc phase 2): a dedicated mailbox polled over IMAP;
    # allowlisted senders' messages are LLM-extracted into event/task
    # proposals a parent approves on /intake. The password is a Gmail app
    # password for the dedicated family account — never a personal login.
    ingest_email_enabled: bool = False
    ingest_email_host: str = "imap.gmail.com"
    ingest_email_user: str = ""
    ingest_email_password: str = ""
    # Optional ROUTING hints, not a gate: every message in the intake mailbox
    # is analyzed (the mailbox itself is the filter — the family curates what
    # gets forwarded there). Each entry {pattern, calendar_id} prefills a
    # proposal's target calendar when the pattern appears in the From address.
    ingest_sender_defaults: List[dict] = Field(default_factory=list)
    # --- The wall panel (a Chauffeur-only touch display, no Home Assistant
    # around it). `?panel=true` turns any page into panel mode: the top nav
    # becomes a bottom shelf of touch-sized buttons and everything already
    # gated on `?kiosk=true` lights up. These three are the panel's PROFILE —
    # what a standalone display shows when nobody is there to type a URL.
    # URL params (?widgets=, ?tabs=) still win, because an HA dashboard card
    # is a second panel with different needs and only the URL can say so.
    # Empty list = "use the default", never "show nothing": a blank profile
    # on a screen bolted to a wall is indistinguishable from a broken app.
    panel_widgets: List[str] = Field(default_factory=list)
    panel_tabs: List[str] = Field(default_factory=list)
    # Untouched for this long, any panel page returns to the home board. This
    # is what makes the panel an appliance rather than a browser: whatever
    # somebody wandered off into, the wall goes back to being the wall.
    # 0 disables it.
    panel_idle_return_seconds: int = 180
    # Per-tile size on the board: {'map': {'cols': 2, 'rows': 2}}. Absent means
    # 1x1. A wall board is a LAYOUT, not a list — the map and the calendar earn
    # more room than the intake counter, and only the household knows which.
    panel_tile_spans: Dict[str, Any] = Field(default_factory=dict)
    # What ONE row of the board's grid is worth, in pixels. Without it a span
    # of 2 meant "as tall as whatever two content-sized rows happened to be" —
    # a height decided by the other tiles in those rows rather than by the
    # household — and it did nothing whatsoever in the last row, where there
    # was no second row to occupy. A fixed unit makes `rows` mean something:
    # 2 rows is 2 units plus the gap, in the last row as anywhere else.
    panel_grid_row_height: int = 240
    # How many columns the board's grid is divided into. 12 (Home Assistant's
    # number) rather than 4, because 4 meant the SMALLEST thing anybody could
    # ask for was a quarter of the board — there was no half-column, no
    # third, nothing narrower than a quarter. Widths are spans of these, so a
    # quarter is 3 and an eighth is 1.5 rounded to 2. Existing sizes were
    # multiplied through on upgrade (migrations.migrate_tile_columns_v21212).
    panel_grid_columns: int = 12
    # How many days the calendar tile's agenda shows. A number the
    # household picks because the right one depends on how wide they made
    # the tile and what they use the board for — a fortnight is a planning
    # surface, three days is "what is happening now". Clamped 1-14, the
    # same range the calendar page's own agenda offers.
    panel_agenda_days: int = 5
    # light | dark | auto | sun. `auto` follows the DEVICE — which, embedded in
    # a Home Assistant dashboard, means following HA, because Chromium
    # propagates the embedding page's `color-scheme` into our frame. Opened
    # directly (the PWA over the tunnel, a browser shortcut) there is no
    # embedder, so `auto` falls back to the tablet's OS preference and a tablet
    # nobody ever told about dark mode reports light forever. `sun` answers the
    # same question server-side from HA's `sun.sun`, which is where the
    # household's own theme automation gets its answer too.
    panel_theme: str = 'dark'
    # Minutes to shift each `sun` switch by. TWO numbers, not one: switching to
    # dark 30 minutes AFTER sunset and back to light 30 minutes AFTER sunrise
    # are different amounts of sky. Matching darkness at both ends is +30 at
    # sunset and -30 at sunrise, which a single shared offset cannot say.
    panel_theme_sunset_offset_minutes: int = 0
    panel_theme_sunrise_offset_minutes: int = 0
    # The photograph the board floats on. A flat slab reads as a dashboard; a
    # full-bleed image with a scrim over it reads as a display, which is the
    # whole difference between this and a web page on a wall. Accepts a URL, or
    # a plain phrase ("mountains at dusk") which is handed to the Unsplash
    # endpoint that already backs trip artwork. Empty = the built-in gradient.
    panel_background: str = ''
    # Per-page override, keyed by nav slug: {'schedule': 'empty highway at
    # dawn', 'meals': 'https://…'}. A page absent from this map uses
    # `panel_background`. Same grammar as the default — a URL, or a phrase to
    # look one up — because a household that has to find eleven image URLs
    # will set zero of them.
    panel_page_backgrounds: Dict[str, str] = Field(default_factory=dict)
    # --- Screensaver (idle photo slideshow) ---
    # The master switch. Separate from the seconds so turning the screensaver
    # off and on again does not forget how long the household tuned the idle
    # wait to be.
    panel_screensaver_enabled: bool = True
    # After this long untouched, any panel page dims into a Ken Burns photo
    # slideshow with a clock. Independent of panel_idle_return_seconds: the
    # return-home makes the wall a consistent APPLIANCE, the screensaver makes
    # an untouched wall WORTH LOOKING AT. 0 also disables it.
    panel_screensaver_idle_seconds: int = 600
    # Where the pictures come from:
    #   photos     — the family's own Moments (photo attachments in event
    #                chats), served from the app's media store. The default:
    #                the family's wall shows the family.
    #   media      — image files under the HA /media share (subfolder below).
    #                This is the bridge to everything else: HA, a NAS, or
    #                Synology/Immich-style sync tools can drop photos there —
    #                including ones synced FROM Google Photos, whose own API
    #                no longer allows third-party library reads.
    #   background — no playlist; the panel wallpaper itself, slow-panned.
    panel_screensaver_source: str = 'photos'
    # Subfolder of /media scanned when source is 'media' (e.g. 'screensaver').
    # Empty scans /media itself. Traversal is rejected server-side.
    panel_screensaver_media_path: str = ''
    # Seconds each photo holds before crossfading to the next.
    panel_screensaver_dwell_seconds: int = 20

class TelemetryEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    driver_id: str
    event_id: str
    action: str  # e.g., 'pickup', 'dropoff', 'arrived'
    timestamp: float = Field(default_factory=time.time)
    details: Optional[str] = None

class Theme(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    description: str
    unassigned_penalty_multiplier: float = 1.0
    stickiness_bonus_multiplier: float = 1.0
    travel_time_penalty_multiplier: float = 1.0
    primary_driver_bonus_multiplier: float = 1.0
    same_location_bonus_multiplier: float = 1.0
    is_ai_generated: bool = False
    is_enabled: bool = True

class Errand(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    title: str
    duration_mins: int
    location: str
    priority: int = 2 # 1 High, 2 Medium, 3 Low
    is_completed: bool = False
    status: str = "pending" # 'pending', 'past_due', 'completed'
    last_scheduled_end: Optional[float] = None # Unix timestamp
    tags: List[str] = Field(default_factory=list)
    recurrence_rule: Optional[str] = None # e.g. 'daily', 'weekly', 'monthly'
    created_at: float = Field(default_factory=time.time)
    starts_on: Optional[float] = None # Optional Unix timestamp overriding created_at for cycle anchors
    window_days: Optional[int] = Field(default=None, description="Number of valid days to schedule this errand.")
    allowed_drivers: List[str] = Field(default_factory=list)
    required_drivers: List[str] = Field(default_factory=list)
    prohibited_drivers: List[str] = Field(default_factory=list)
    allowed_passengers: List[str] = Field(default_factory=list)
    required_passengers: List[str] = Field(default_factory=list)
    prohibited_passengers: List[str] = Field(default_factory=list)
    tolerance_mins: int = 0
    buffer_mins: int = 0
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    group_id: Optional[str] = None
    valid_days_of_week: List[int] = Field(default_factory=list)
    occasion_id: Optional[str] = None   # "pick up the cake" belongs to the party
    # WHICH line of the template this satisfies. The gap report can only show
    # an absence by matching against something, and an exact key beats keyword
    # guessing at the one job where a false match is worse than no report.
    occasion_key: Optional[str] = None

class ErrandRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    title: str = "New Errand Rule"
    constraint_type: str = "driver_assignment"
    window_days: Optional[int] = Field(default=None, description="Number of valid days to schedule this errand.")
    location: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    keywords_match_all: bool = False
    allowed_drivers: List[str] = Field(default_factory=list)
    required_drivers: List[str] = Field(default_factory=list)
    prohibited_drivers: List[str] = Field(default_factory=list)
    allowed_passengers: List[str] = Field(default_factory=list)
    required_passengers: List[str] = Field(default_factory=list)
    prohibited_passengers: List[str] = Field(default_factory=list)
    tolerance_mins: int = 0
    buffer_mins: int = 0
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    group_keyword: Optional[str] = None
    filter_sets: List[EventFilter] = Field(default_factory=list)
    valid_days_of_week: List[int] = Field(default_factory=list)
    is_enabled: bool = True

class ShoppingList(BaseModel):
    # Meals & provisioning arc M1. A STANDING list, not an errand field: a
    # recurring grocery errand regenerates every cycle while the list persists
    # across all of them, so the binding is by TAG (matched against
    # Errand.tags), never by errand id. See docs/meal_design.md.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    name: str = "Groceries"
    store: Optional[str] = None        # display name; matches Errand.location
    errand_tag: Optional[str] = None   # binds to whichever errand carries it
    is_default: bool = False
    occasion_key: Optional[str] = None  # which template line this satisfies
    # Membership attaches to the coarsest entity the occasion WHOLLY owns
    # (design principle 3). A list made for the shark party is the party's, so
    # an item added to it belongs to the party regardless of which page the
    # parent was standing on — there is no per-item tagging to keep in sync.
    occasion_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

class ShoppingItem(BaseModel):
    # Individually addressable so two people at the store never clobber each
    # other: there is no whole-list PUT, only per-item PATCH (design §M1).
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    list_id: str
    name: str
    qty: Optional[str] = None          # FREE TEXT ("2 lbs") — never parsed
    note: Optional[str] = None
    added_by: Optional[str] = None     # member id (attribution, not a gate)
    added_via: str = 'manual'          # manual|voice|photo|meal|barcode
    source_meal_id: Optional[str] = None   # M3 entries that drained here
    # EVERY night that wants this row, not just the first one to ask.
    # `source_meal_id` above records one dish, which is all a single drain
    # needs; it is not enough to ever take an item back OFF. Chicken wanted by
    # Monday and Thursday was one row remembering Monday, because a second
    # dish asking for an ingredient already on the list was skipped outright —
    # so changing Monday's dinner looked like it freed the chicken, when
    # Thursday still needed it. Claims are what make removal safe: an
    # ingredient stays while any planned night still wants the dish that
    # brought it. [{'dish_id', 'date', 'dish_name'}]
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    # WHICH SHOP RUN this item is for (ISO date), so a mid-week top-up does
    # not inherit the whole of next Saturday's list. Deliberately per ITEM and
    # not per list: the grocery list is STANDING (see ShoppingList above — the
    # errand regenerates every cycle while the list persists across all of
    # them), and a list per run is how a second list starts rotting while
    # everyone keeps adding milk to the main one. None means the next run.
    buy_on: Optional[str] = None
    # THE documented exception to list-level membership. The standing grocery
    # list is a container the occasion owns only PART of: the turkey wants to
    # be on the normal list, bought on the normal run, at the normal store,
    # because everything downstream (errand, shop day, cart) is keyed per-list
    # and a second list at the same store rots while the family puts the
    # turkey on the main one anyway. Same shape as `source_meal_id` directly
    # above — an item recording WHY it is here without the list belonging to
    # the thing that caused it.
    occasion_id: Optional[str] = None
    is_checked: bool = False
    checked_at: Optional[float] = None
    checked_by: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

class MealRule(BaseModel):
    """A standing fact about how THIS household eats.

    M9 modelled "these dishes come together", which is a property of a dish.
    These are not properties of any dish — they are rhythms, and they are the
    thing that makes a plan feel like this family's rather than a generic one:

      "we only eat meat about once a week"          -> frequency_cap
      "takeout is an occasional thing"              -> frequency_cap
      "we cook one kind of beans, eat it 2-3 days,  -> batch_cycle
       then make the next kind, then the next"

    Deliberately NOT a general predicate language. Two kinds, both drawn from
    what the family actually said, each enforced at the point where the
    composer picks dishes. The solver's Rule/ErrandRule is the precedent: named,
    listable, individually switchable, and boring to reason about.

    Selector clauses are ANDed, and empty clauses are ignored — so
    `sources=['ordered']` alone means all takeout, while `tags=['beef']` plus
    `types=['entree']` means beef mains only.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    name: str = ""
    kind: str = 'frequency_cap'        # frequency_cap | batch_cycle
    is_enabled: bool = True

    dish_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    types: List[str] = Field(default_factory=list)
    side_types: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    # Subtraction, because a tag is nearly always ALMOST right: "beans" is the
    # rotation the family described, except baked beans are not part of that
    # rotation at all. Without this the only way to express it is to abandon
    # the tag and enumerate every dish by hand.
    exclude_dish_ids: List[str] = Field(default_factory=list)

    # frequency_cap: at most `max_servings` of the matched set per window.
    max_servings: int = 1
    window_days: int = 7

    # batch_cycle: one member of the matched set is "the open pot". It keeps
    # being served for `dwell_days`, then the group advances to whichever
    # member has gone longest without — which is what cooking a big batch and
    # working through it actually looks like.
    dwell_days: int = 3

    created_at: float = Field(default_factory=time.time)


class PrepStep(BaseModel):
    """Work that happens OUTSIDE the cook window, and the reminder for it.

    This is the load the meal plan could not carry: soaking beans the night
    before is cognitively separate from cooking dinner, it happens on a
    different DAY, and forgetting it silently invalidates tomorrow's plan. The
    plate could already say a dish "needs a thaw head start" — a label with no
    time and no reminder attached, which is exactly the part that does not
    help.

    `when` is not a number by accident. "The night before" is a HUMAN moment
    (after dinner, before bed), not an offset: soaking rice for a 6pm dinner is
    something you do at 9pm the evening before, and `dinner - 12h` would put
    the reminder at 6am on the day. Encoding it as an offset gets the arithmetic
    right and the behaviour wrong.

    Per-DISH and opt-in, because whether rice gets soaked is a fact about this
    household, not about rice — the same reasoning as `MealIngredient.kind`.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    action: str                            # "soak", "marinate", "take out to thaw"
    when: str = 'hours_before'             # night_before | hours_before | morning_of
    hours: float = 1.0                     # only read when when == 'hours_before'
    note: Optional[str] = None

    def label(self) -> str:
        if self.when == 'night_before':
            return f"{self.action} — the night before"
        if self.when == 'morning_of':
            return f"{self.action} — that morning"
        h = int(self.hours) if float(self.hours).is_integer() else self.hours
        return f"{self.action} — {h}h before"


class MealIngredient(BaseModel):
    # Light structure only — quantity and unit are NEVER parsed. `kind` is the
    # trick that recovers most of inventory's value with none of its
    # maintenance: it is a property of the DISH ("tacos need fresh beef, and
    # the spices are always here"), stable forever, so there is nothing to
    # keep up to date and nothing to rot. Only `fresh` lines reach the
    # shopping list or gate feasibility.
    name: str
    kind: str = 'fresh'                # staple | fresh
    # A COMPONENT PLATE ("chicken, rice, beans, a veg, salad") is one meal, not
    # six — but its parts substitute for each other, and the first cut of this
    # schema could only express a fixed dish. `options` means "any ONE of
    # these satisfies this line": name='beans', options=['black','red','pinto'].
    # That single primitive covers both readings of a plate — separate lines
    # are AND (rice *and* salad), options within a line are OR (rice *or*
    # potatoes) — so nothing needs a component/ingredient split.
    options: List[str] = Field(default_factory=list)
    # 'protein' | 'starch' | 'vegetable' | 'side' | ... — free text, display
    # only. Deliberately NOT a controlled vocabulary or a slot the app fills:
    # that road ends at a meal-builder.
    role: Optional[str] = None
    optional: bool = False             # the salad nobody minds skipping

class DishCategory(BaseModel):
    """The family's OWN vocabulary for what goes on a plate, and how much.

    M5 shipped a fixed taxonomy — meal/entree/side plus vegetable/starch/salad/
    other — which is restaurant vocabulary imposed on a household. "Entree" is a
    word families do not use; "protein" is, for the ones who think
    nutritionally, and "a meat, a bread and a potato" is for the ones who don't.
    Worse, the fixed list actively lied: the extractor was told beans are a
    starch, so a family whose protein comes from beans had no protein on any
    plate the app composed. `MealComponent.role` had already reached this
    conclusion once — "deliberately NOT a controlled vocabulary... that road
    ends at a meal-builder" — before M5 built one anyway.

    A category IS its own composition rule, which is why this is one model and
    not two: "protein" and "one protein per plate" are the same sentence in
    every household that says it. `id` is stable and `name` is editable, so
    renaming "dessert" to "something sweet" propagates nowhere.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str                            # "protein", "starches/carbs"
    # One line, fed to the classifier — this is how the family teaches the
    # model their vocabulary instead of inheriting ours.
    description: str = ""
    # What a plate wants. The composer fills to `min_per_plate`; `max_per_plate`
    # is the ceiling that leftovers, pairings and the family's own hand may
    # reach but nothing may exceed.
    min_per_plate: int = 0
    max_per_plate: int = 1
    # A dish marked `type='meal'` is the whole plate and satisfies every
    # category on its own. Something sweet is the exception a family actually
    # wants — spaghetti night still ends with fruit — so the block says so
    # rather than the code hardcoding "dessert is special".
    with_complete_meal: bool = False
    order: int = 0
    created_at: float = 0.0


class Dish(BaseModel):
    # Meals & provisioning arc M4. THE DISH IS THE UNIT OF WORK — roasted
    # potatoes and mashed potatoes are different jobs with different times and
    # different shopping, and a plate's timing is the aggregate of its dishes.
    # M3 carried one set of times for a whole plate, which is the same
    # "one number cannot express a weeknight" mistake the four-number split
    # already fixed once, made again a level down.
    #
    # Dishes are REUSED across meals (rice is rice), which is also what makes
    # per-dish leftovers exact instead of a proportional guess.
    #
    # Still no steps, ever. A dish is (name, times, ingredients, portability)
    # — "roasted russet potatoes" is a dish; how to roast them is not our
    # business. That line does not move.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    name: str                          # "roasted russet potatoes"
    short_name: Optional[str] = None   # "potatoes" — what the family calls it

    # M5: what this dish IS, which is what lets a plate be COMPOSED by rule
    # instead of enumerated. A family does not eat 15-20 unrelated meals; they
    # eat combinations of maybe 25 dishes, so storing the combinations was
    # both lossy (the count froze at whatever was typed) and misleading (one
    # "meal" standing for a dozen dinners).
    #   meal — complete on its own (tacos, spaghetti and meatballs). Satisfies
    #          the whole composition; nothing is added beside it except the
    #          categories that opted in with `with_complete_meal`.
    #   dish — fills ONE slot on a plate, chosen from `category_ids`.
    #
    # Kept as a flag rather than dissolved into categories because the
    # alternative makes the family do arithmetic: if spaghetti & meat sauce were
    # tagged protein+starch against a plate wanting 2-3 vegetables, every
    # spaghetti night would arrive with vegetables to delete. "It's a meal" is
    # one word and it is what people actually say.
    type: str = 'dish'                 # meal | dish
    # The family's own categories (DishCategory ids). MULTIPLE categories mean
    # "can serve as any of these", NOT "counts as all of these at once" — a
    # dish fills at most one slot per plate. That is what lets black beans be
    # the protein next to rice and the starch next to a steak, which is exactly
    # what the old fixed `side_type` could not say.
    category_ids: List[str] = Field(default_factory=list)
    side_type: Optional[str] = None    # legacy (pre-v2.108) — migrated to categories
    role: Optional[str] = None         # legacy free-text label (pre-M5)

    # Kiosk board (arc K1). An image is NOT decoration here: a child who
    # cannot read fluently yet learns what is for dinner from the picture, and
    # that is the only argument that justifies carrying images at all. So the
    # family's OWN photo outranks a stock one — it is their food, and it also
    # answers "what does this look like when it's done".
    image_url: Optional[str] = None
    image_source: Optional[str] = None   # family | stock

    prep_ahead_mins: int = 0
    finish_mins: int = 0
    unattended_mins: int = 0
    # A LABEL, not a schedule: it says a head start exists but not when, and it
    # reminds nobody. `prep_steps` is the thing that actually fires.
    needs_ahead: str = 'none'          # none | thaw | marinate | slow_cooker
    prep_steps: List['PrepStep'] = Field(default_factory=list)

    holds_well: bool = False
    portability: str = 'none'          # none | handheld | utensils_ok

    # --- Occasions arc O0: the kitchen is a resource, and a dish occupies one.
    # `_totals_from_dishes` has always been a two-resource model with the
    # capacities hardcoded (cook=1 -> hands-on SUMS, equipment=infinity ->
    # unattended takes the MAX). Both constants invert the moment the family
    # hosts, so the capacities move to settings and the dish declares what it
    # actually occupies. See docs/occasion_design.md §O0.
    equipment: str = 'none'            # none | oven | burner
    # Oven dishes only, and it is the SHARING key: two dishes fit one oven when
    # their temperatures match. Space is the constraint people think of;
    # temperature is the one that actually blocks.
    oven_temp_f: Optional[int] = None
    serves: int = 4                    # what the stored times/ingredients assume
    # Made in WHOLE UNITS: a tray of lasagna, a cake, a sheet pan, a pot pie.
    # Scaling is continuous by default because most food is — cooking nine
    # portions of carrots really is 1.5 pans and 1.5 times the peeling — but a
    # tray is a tray. You cannot bake half of one, so feeding nine from a tray
    # that serves six means TWO trays: twice the ingredients, twice the work,
    # and a genuine surplus rather than a rounding error.
    whole_units: bool = False

    # Holiday and party food is not Tuesday food. Keeping turkey in the
    # standing pool just so it exists twice a year pollutes every picker for
    # the other fifty weeks — but it is deliberately NOT a MealRule: rules are
    # rhythms ("meat about once a week"), and "turkey is not a Tuesday food" is
    # a property of the dish. `tags` still carries WHICH occasion, which is why
    # these are two fields: mashed potatoes are everyday AND Thanksgiving, and
    # one field cannot say both. `is_active` stays what it is — retired, not
    # seasonal.
    scope: str = 'everyday'            # everyday | occasion

    source: str = 'prep'               # prep | ordered (a dish can be bought:
    vendor: Optional[str] = None       # rotisserie chicken alongside a salad
    order_lead_mins: int = 0           # you make)

    ingredients: List[MealIngredient] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    # Pairing (M9). DIRECTED and per-dish, deliberately not a compatibility
    # matrix: "brisket always comes with beans and fries" is one statement on
    # one dish, whereas a symmetric goes-with grid is O(n^2) of maintenance
    # that a family will never keep current — which is exactly why M5 refused
    # to model coherence and used a soft tag affinity instead. The asymmetry is
    # the whole point: brisket BRINGS beans and fries, while beans and fries
    # remain free to appear beside anything else.
    always_with: List[str] = Field(default_factory=list)   # dish ids that come too
    # The reverse constraint, also directed: never propose this dish unless one
    # of these is on the plate ("that sauce is only ever with the brisket").
    only_with: List[str] = Field(default_factory=list)

    # "Potatoes" is too vague to time or shop for — which kind, cooked how?
    # The model GUESSES rather than interrogating (entry must stay one
    # sentence), flags the guess here, and the family refines when they feel
    # like it. A gate at entry time is how a repertoire never gets filled.
    needs_detail: bool = False
    detail_question: Optional[str] = None

    last_served_at: Optional[float] = None
    is_active: bool = True
    created_at: float = Field(default_factory=time.time)

class PlateItem(BaseModel):
    # One dish on ONE evening's plate. Tonight's plate is composed by rule and
    # then edited freely — only one veg tonight, three tomorrow — so it is a
    # dated record like Leftover rather than structure on a stored meal.
    dish_id: str
    added_by: Optional[str] = None     # member id, when a person chose it
    source: str = 'auto'               # auto | manual | agent

class Plate(BaseModel):
    # The evening's actual dinner. Absent = nothing decided yet, and the
    # composer proposes one on demand; present = the family has touched it and
    # it holds still (the same pin-on-touch rule the slot swaps used).
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    date: str                          # YYYY-MM-DD
    items: List[PlateItem] = Field(default_factory=list)
    edited: bool = False
    # `edited` and `locked` are NOT the same statement. Editing is "we swapped
    # a side", and a bulk repropose is entitled to sweep it away. Locking is
    # "this is Mom's birthday dinner, do not touch it" — deliberate, dated, and
    # immune to the repropose that would otherwise wipe it a week early.
    locked: bool = False
    # WHY the night is spoken for. An empty locked plate with a note is how
    # "Grandma is bringing dinner" is expressed: nothing to cook, nothing to
    # shop for, and it does not read as a night nobody has planned yet.
    note: Optional[str] = None
    # What this night has already been OFFERED and turned down. Repropose is
    # otherwise a no-op: the composer is deterministic, so recomposing an
    # untouched night returns exactly what was on it. This is the only source
    # of variation, and it is a memory rather than randomness so the plan a
    # family looked at is still there when the page reloads.
    #
    # A row carrying only rejections has edited=False, so it neither pins the
    # night nor holds dishes still — and it is pruned with every other plate,
    # so a refusal expires on its own.
    rejected: List[str] = Field(default_factory=list)
    # Hosting (occasions arc O0). The WHOLE headcount, not the extra guests —
    # "we're having twelve people" is what somebody says, and making them
    # subtract their own family first is arithmetic the app should do. Absent =
    # an ordinary night, and every dish's stored `serves` stands.
    serving_for: Optional[int] = None
    # Hands available THIS night. Absent = the household default
    # (`kitchen_cooks`), because someone offering to help on Saturday is not a
    # statement about how this family cooks on a Tuesday.
    cooks: Optional[int] = None
    created_at: float = Field(default_factory=time.time)

class MealSlot(BaseModel):
    # One position on the plate, filled by exactly ONE of its dishes. A fixed
    # part is simply a slot with a single option, so there is no separate
    # notion of "fixed vs substitutable" to keep straight.
    #
    # `id` is load-bearing: "veggies x 2" produces TWO slots with the SAME
    # label, and keying choices/swaps off the label made them collide — one
    # pick moved both, and when both resolved to the same dish the duplicate
    # render key dropped a chip. Labels are for display only; identity is id.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    label: Optional[str] = None        # "beans", "vegetable" — may repeat
    dish_ids: List[str] = Field(default_factory=list)
    optional: bool = False             # the salad nobody minds skipping

class Meal(BaseModel):
    # Meals & provisioning arc M3 — the REPERTOIRE, not a recipe box. A recipe
    # answers "how do I make this"; an entry here answers "can we have this
    # today", which is a scheduling question and the only kind Chauffeur has
    # any business storing. Nobody in this family reads instructions to make
    # tacos. THERE ARE NO STEPS, EVER — that is the line between this and a
    # recipe box; `notes`/`link` cover the twice-a-year meal nobody remembers.
    #
    # M4: a meal is now a COMPOSITION of dish slots. Its own timing fields
    # below are the fallback for legacy entries with no slots — a composed
    # meal derives everything from its chosen dishes. The combinations are
    # never persisted: 3 beans x 5 vegetables is 15 dinners, not 15 rows.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    name: str
    slots: List[MealSlot] = Field(default_factory=list)
    # What the family actually typed, when the model shortened it into `name`
    # ("chicken, rice, beans (black/red/pinto), veggies…" -> "Chicken plate").
    # Kept so they can check the model read their plate correctly.
    description: Optional[str] = None

    # --- timing: four numbers, because one cannot express a real weeknight.
    # A 90-minute roast with 8 minutes hands-on is IDEAL when a parent is home
    # 4:30-6:00; a 25-minute stir-fry that is 25 minutes at the stove is
    # impossible on that same night.
    prep_ahead_mins: int = 0      # detachable work — schedulable into ANY earlier gap
    finish_mins: int = 0          # must happen near eating
    unattended_mins: int = 0      # oven/slow cooker; someone home at start + end
    needs_ahead: str = 'none'     # none | thaw | marinate | slow_cooker (lead time, not work)

    # --- place and persistence
    holds_well: bool = False      # survives split service and reheats
    portability: str = 'none'     # none | handheld | utensils_ok — matched to slot modality

    # --- acquisition. Ordered food is ORDINARY, not an emergency: "Thursday is
    # pizza from the usual place" is a planned meal that happens to need a stop.
    source: str = 'prep'          # prep | ordered | hybrid
    vendor: Optional[str] = None
    vendor_location: Optional[str] = None
    order_lead_mins: int = 0
    fulfillment: str = 'pickup'   # pickup | delivery

    effort: str = 'normal'        # easy | normal | project
    serves: int = 4
    tags: List[str] = Field(default_factory=list)
    ingredients: List[MealIngredient] = Field(default_factory=list)
    notes: Optional[str] = ""
    link: Optional[str] = None
    last_served_at: Optional[float] = None
    is_active: bool = True
    created_at: float = Field(default_factory=time.time)

class Leftover(BaseModel):
    # "We're having Sunday's chili tonight" / "the rice is leftover".
    # Deliberately NOT a field on Meal: leftovers are a property of the
    # OCCASION, not the dish — chili is chili whether it is simmered fresh or
    # reheated — so this is a dated override that expires on its own instead
    # of a flag someone has to remember to turn off.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    date: str                            # YYYY-MM-DD
    meal_id: Optional[str] = None        # a repertoire entry, or None for
    label: Optional[str] = None          # free-form ("Sunday's chili")
    # Component names that are already made. EMPTY means the WHOLE meal is
    # leftovers — the common case, and the only one where the time saved is
    # exactly known. (Legacy M3 path; `dish_ids` is the exact one.)
    parts: List[str] = Field(default_factory=list)
    # M4: leftovers by DISH. Because a dish carries its own times, marking the
    # rice as already made subtracts the rice's actual minutes instead of the
    # proportional-by-count estimate M3 had to guess with.
    dish_ids: List[str] = Field(default_factory=list)
    reheat_mins: int = 10
    created_at: float = Field(default_factory=time.time)

class Occasion(BaseModel):
    """A holiday, birthday, party or get-together — as CONTEXT, not a container.

    It owns nothing. Errands, shopping lists, trips and plates all keep their
    existing homes and their existing engines; this carries the anchor date,
    the window, the headcount and the dish tags, and gets passed IN to the
    things that generate work. See docs/occasion_design.md.

    Called Occasion rather than Holiday on purpose: "holiday" excludes
    birthdays, graduations and first-day-of-school (which are most instances)
    and in British English means a vacation, which is `TripMetadata`.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    title: str                              # "Thanksgiving 2026", "Ellie's 8th"
    kind: str = 'gathering'                 # thanksgiving|christmas|birthday|party|gathering
    anchor_date: str                        # YYYY-MM-DD — the day the thing happens
    # Guests in the house, prep, travel. Defaults to the anchor day alone.
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    # Which repertoire tags this occasion brings into play. Eligibility only —
    # a specific plate still has to CHOOSE them (design principle 6).
    dish_tags: List[str] = Field(default_factory=list)
    # Hands available across the window, when it differs from the household
    # default. Copied onto a plate by `set_plate_hosting`, never read behind
    # its back — one owner per number.
    cooks: Optional[int] = None
    notes: Optional[str] = None
    # Last year's instance. THE carryover link, and the whole reason the gap
    # report can say "this had a rental line last year and does not now" —
    # which is the only thing that can surface an absence.
    prior_occasion_id: Optional[str] = None
    status: str = 'planning'                # planning | done
    # What the interview has been TOLD. The occasion's own data, not a copy of
    # anything else — every answer is a fact nobody else stores, and each one
    # generates work that then lives in its normal home.
    answers: Dict[str, Any] = Field(default_factory=dict)
    # Checklist keys the family has explicitly waved off ("no cake this year").
    # Without this the gap report nags forever about a deliberate decision,
    # which is how a report stops being read.
    dismissed: List[str] = Field(default_factory=list)
    # Who from the household is actually coming: {member_id: bool}, and ONLY
    # for members somebody has decided about. Absent means "the default for
    # that role", which is what lets a member added next month behave sensibly
    # instead of silently missing from every occasion already on the books.
    #
    # The first cut counted every non-helper member automatically with no way
    # to say otherwise, which is wrong the moment a family has an adult who
    # lives elsewhere, a parent away that week, or a helper who IS invited to
    # the party. Attendance is a decision, not a property of the roster.
    attendance: Dict[str, bool] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class OccasionGuest(BaseModel):
    """Who is coming. Family members link by id; everyone else is just a name.

    Deliberately NOT an invitation system: outbound SMS/email to non-members
    is a different animal (deliverability, opt-outs, RSVP state) and a group
    text already works. The list earns its place by feeding HEADCOUNT and
    DIETARY constraints into the meal composer — that is the cross-entity
    payoff, and it needs no sending.
    """
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
    occasion_id: str
    name: str
    member_id: Optional[str] = None         # set when this is one of the family
    headcount: int = 1                      # "the Wilsons, 4"
    # Same grammar the solver and the meal composer already use: hard avoid,
    # soft dislike. A guest's allergy has to bind exactly like a family
    # member's, or the feature is decorative.
    dietary_avoid: List[str] = Field(default_factory=list)
    dietary_dislike: List[str] = Field(default_factory=list)
    staying_over: bool = False
    arrival: Optional[str] = None           # ISO datetime — airport runs, later
    departure: Optional[str] = None
    notes: Optional[str] = None
    created_at: float = Field(default_factory=time.time)


class TripPOI(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    location: str
    mapbox_id: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    why_picked: Optional[str] = None
    experience: Optional[str] = None
    image_url: Optional[str] = None
    link: Optional[str] = None
    notes: Optional[str] = None
    priority: str = "want" # "must", "want", "stretch"
    ideal_time_start: Optional[str] = None
    ideal_time_end: Optional[str] = None
    duration_mins: int = 60
    estimated_price_usd: Optional[float] = None
    is_scheduled: bool = False
    scheduled_start: Optional[float] = None
    scheduled_end: Optional[float] = None
    event_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    wikidata_id: Optional[str] = None
    opening_hours: Optional[str] = None
    website: Optional[str] = None
    phone_number: Optional[str] = None
    cuisine: Optional[str] = None
    internet_access: Optional[str] = None
    estimated_price_usd: Optional[float] = None
    is_live_price: bool = False
    is_background: bool = False
    valid_days_of_week: List[int] = Field(default_factory=list)
    occurrences: int = 1
    meal_type: Optional[str] = None      # 'breakfast'|'brunch'|'lunch'|'dinner'|'dessert'|'snack'
    dining_style: Optional[str] = None   # 'quick'|'casual'|'fine'
    parent_container: Optional[str] = None  # id of the background POI this lives inside
    days_claimed: int = 1                # background POIs only: number of full days claimed
    claimed_dates: List[str] = Field(default_factory=list)  # YYYY-MM-DD (local), set by the scheduler
    # Calendar-backed POIs: a POI that mirrors a real Google Calendar event linked
    # into the trip (e.g. a reservation someone booked). It is a FIXED anchor —
    # is_scheduled at the event's real time, never re-solved or auto-cleared, and
    # (being externally authored) its calendar event is never deletable by Chauffeur.
    is_external_event: bool = False
    source_event_id: Optional[str] = None  # the cal::id this POI mirrors (link key)

class TripRule(BaseModel):
    # extra='forbid' so agent-emitted phantom fields fail loudly instead of silently no-oping
    model_config = ConfigDict(extra='forbid')
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    description: str                  # human-readable, shown in chat / rules panel
    rule_type: str                    # 'day_restriction'|'block_restriction'|'budget_cap'|'day_capacity'|'keep_clear'|'spacing'|'template_override'
    # --- selectors (empty = not filtering on that axis) ---
    poi_ids: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    # --- parameters (used per rule_type) ---
    days_of_week: List[int] = Field(default_factory=list)  # 0=Mon .. 6=Sun
    trip_days: List[int] = Field(default_factory=list)     # 1-indexed day of trip
    blocks: List[str] = Field(default_factory=list)        # 'breakfast'..'evening'
    max_usd: Optional[float] = None
    max_active_mins: Optional[int] = None
    min_gap_days: Optional[int] = None
    template_start: Optional[str] = None  # 'HH:MM', template_override only
    template_end: Optional[str] = None
    # --- semantics ---
    hardness: str = 'soft'            # 'hard' | 'soft'
    weight: int = 50000               # soft rules only
    is_ai_generated: bool = False
    is_enabled: bool = True

class TripAccommodation(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    location: str
    mapbox_id: Optional[str] = None
    check_in_date: Optional[str] = None # YYYY-MM-DD
    check_out_date: Optional[str] = None # YYYY-MM-DD
    notes: Optional[str] = None
    event_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    wikidata_id: Optional[str] = None
    opening_hours: Optional[str] = None
    website: Optional[str] = None
    phone_number: Optional[str] = None
    cuisine: Optional[str] = None
    internet_access: Optional[str] = None
    image_url: Optional[str] = None
    estimated_price_usd: Optional[float] = None
    is_live_price: bool = False

class TripFlight(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    class_type: Optional[str] = None
    estimated_price_usd: Optional[float] = None
    is_live_price: bool = False
    notes: Optional[str] = None
    booking_link: Optional[str] = None

class TripMetadata(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_id: str
    is_draft: bool = False
    title: Optional[str] = None
    location: Optional[str] = None
    draft_start_day: Optional[int] = None # 0 = Monday, 6 = Sunday
    draft_duration_nights: Optional[int] = None
    mock_start_date: Optional[float] = None
    mock_end_date: Optional[float] = None
    background_url: Optional[str] = None
    notes: Optional[str] = None
    timeZone: Optional[str] = None
    budget_min_usd: Optional[float] = None
    budget_max_usd: Optional[float] = None
    flight_preferences: Optional[str] = None
    travelers: int = 1
    # An occasion may reference more than one trip (in-laws 22–26 Dec, then
    # skiing 27–30). Many-to-one, and the occasion's window spans both — the
    # trip keeps sole ownership of its own dates and its own scheduler.
    occasion_id: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)
    pois: List[TripPOI] = Field(default_factory=list)
    accommodations: List[TripAccommodation] = Field(default_factory=list)
    flights: List[TripFlight] = Field(default_factory=list)
    rules: List[TripRule] = Field(default_factory=list)

class CreateTripRequest(BaseModel):
    title: str
    location: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    start_day_of_week: Optional[int] = None
    duration_nights: Optional[int] = None
    calendar_id: Optional[str] = None
    budget_min_usd: Optional[float] = None
    budget_max_usd: Optional[float] = None
    attendees: List[str] = Field(default_factory=list)
    flight_preferences: Optional[str] = None
    travelers: int = 1
