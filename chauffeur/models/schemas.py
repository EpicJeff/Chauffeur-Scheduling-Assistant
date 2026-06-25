from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import uuid
import time

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

class EventFilter(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    keywords_match_all: bool = False
    passenger_ids: List[str] = Field(default_factory=list)
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
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
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
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
    passengers_match_all: bool = False
    days_of_week: List[int] = Field(default_factory=list)
    time_start: Optional[str] = None
    time_end: Optional[str] = None
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

class Settings(BaseModel):
    calendar_ids: List[str]
    days_to_show: int = 7
    home_location: Optional[str] = None
    trip_hashtags: List[str] = Field(default_factory=list)
    route_cache_duration_mins: int = 10
    time_format_24h: bool = False
    disable_mapbox: bool = False
    disable_mapbox_matrix: bool = False
    disable_mapbox_directions: bool = False
    mapbox_matrix_limit: int = 90000
    mapbox_directions_limit: int = 90000
    mapbox_geocode_limit: int = 90000
    llm_provider: str = ""
    llm_gemini_api_key: Optional[str] = None
    llm_gemini_model: str = "gemini-3.5-flash"
    llm_ollama_url: str = "http://localhost:11434"
    llm_ollama_model: str = "qwen2.5:7b"
    family_philosophy: str = ""
    enable_standard_rules: bool = True
    enable_ai_rules: bool = True
    enable_standard_priority_rules: bool = True
    enable_ai_priority_rules: bool = True
    enable_ai_themes: bool = True

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

class ErrandRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    doc_id: Optional[int] = None
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
    is_enabled: bool = True
