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

class Passenger(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    calendar_ids: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    requires_attendance: bool = False
    bio: Optional[str] = ""

class FamilyMember(BaseModel):
    # Overlay entity: one record per human. Drivers/passengers stay the
    # solver's source of truth; members link to them via driver_id /
    # passenger_id and carry hub-level identity (avatar, HA mappings).
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    color_code: str = '#3b82f6'
    avatar: Optional[str] = None  # emoji or static path; None -> initials
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
    pin_hash: Optional[str] = None            # pbkdf2; never exposed via API
    pin_salt: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

class ChatChannel(BaseModel):
    # Family messaging. Table names are chat_* to stay clear of the agent's
    # 'conversations' store.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: str = 'dm'  # 'family' | 'dm' | 'event'
    member_ids: List[str] = Field(default_factory=list)  # empty for 'family' = everyone
    dm_key: Optional[str] = None       # sorted "a:b" pair for kind='dm' (indexed lookup)
    event_id: Optional[str] = None     # kind='event': calendar event instance id
    event_end: Optional[str] = None    # ISO end of the event; drives auto-archive
    title: str = ""                    # event-title snapshot; dm/family titles render client-side
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

class RoutineItem(BaseModel):
    # Personal daily-routine template ("brush teeth", "homework"): per member,
    # optional time of day, day-of-week mask. No points — streaks instead.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    member_id: str
    title: str
    time_of_day: Optional[str] = None      # "HH:MM" -> plotted on My Day
    days_of_week: List[int] = Field(default_factory=list)  # 0=Mon..6=Sun; empty = every day
    created_at: float = Field(default_factory=time.time)

class Reward(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str
    description: Optional[str] = ""
    cost: int = 50
    created_at: float = Field(default_factory=time.time)

class Redemption(BaseModel):
    # Kid requests, parent approves (ledger deduction) or denies.
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    reward_id: str
    reward_title: str
    cost: int
    member_id: str
    state: str = 'pending'  # pending | approved | denied
    requested_at: float = Field(default_factory=time.time)
    decided_by: Optional[str] = None
    decided_at: Optional[float] = None

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

class Settings(BaseModel):
    # Evening push digest listing each driver's assignments for tomorrow.
    tomorrow_digest_enabled: bool = True
    tomorrow_digest_time: str = "20:00"  # HH:MM, server-local time
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
    llm_gemini_model: str = "gemini-3.5-flash"
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
