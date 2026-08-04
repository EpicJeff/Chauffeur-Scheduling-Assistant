from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Any
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
    trip_id: Optional[str] = None
    poi_id: Optional[str] = None
    # Set by the refresh when every passenger on the event is away on a
    # background trip: excluded from solving but still shown on the calendar.
    trip_suppressed: bool = False

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
    driver_id: Optional[str] = None
    passenger_id: Optional[str] = None
    ha_person_entity: Optional[str] = None    # e.g. person.jeff
    notify_service: Optional[str] = None      # e.g. notify.mobile_app_jeffs_iphone
    media_player_entity: Optional[str] = None
    # School hours (K4c, children only): drive the school-day-end pickup
    # push and the morning launch line. Empty = no school-hour features.
    school_hours_start: Optional[str] = None  # HH:MM
    school_hours_end: Optional[str] = None    # HH:MM
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
    attachment: Optional[dict] = None  # reserved: {kind, url, duration_s, mime}
    card: Optional[dict] = None  # interactive card (e.g. action_proposal) rendered in chat

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
    time_of_day: Optional[str] = None      # "HH:MM" -> plotted on My Day
    days_of_week: List[int] = Field(default_factory=list)  # 0=Mon..6=Sun; empty = every day
    created_at: float = Field(default_factory=time.time)

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
    # Calendar trigger words for auto-suggest ("chemo", "night shift") —
    # stored now, matched in the next slice.
    keywords: List[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)

class StatusDay(BaseModel):
    # One dated instance of a StatusProtocol. Date-bound BY DESIGN: a status
    # never lingers past its day, so stale-dial lies (worse than silence) are
    # structurally impossible. note is the one-tap "today's different" nudge.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    date: str                            # YYYY-MM-DD
    protocol_id: str
    note: str = ""
    set_by: Optional[str] = None         # member id; None = agent/system
    set_at: float = Field(default_factory=time.time)

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
    # School calendar (services/school.py): what a "school day" is. All
    # empty = plain weekday behavior. The designated calendar's all-day
    # events matching a no-school keyword mark school out; the year bounds
    # are how summer is known without guessing from event titles.
    school_calendar_id: str = ""
    school_year_start: str = ""       # YYYY-MM-DD, update once a year
    school_year_end: str = ""         # YYYY-MM-DD
    school_closed_keywords: str = ""  # comma list; empty = built-in default
    calendar_ids: List[str]
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
    family_philosophy: str = ""
    enable_standard_rules: bool = True
    enable_ai_rules: bool = True
    enable_standard_priority_rules: bool = True
    enable_ai_priority_rules: bool = True
    enable_ai_themes: bool = True
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
