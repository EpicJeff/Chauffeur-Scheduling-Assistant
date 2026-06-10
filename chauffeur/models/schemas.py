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
    source_event_ids: List[str]

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

class Passenger(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    calendar_ids: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    requires_attendance: bool = False

class Rule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    driver_id: str
    event_keyword: str
    constraint_type: str  # e.g., 'required', 'preferred', 'unavailable'

class PriorityRule(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    match_type: str       # 'keyword' or 'calendar'
    match_value: str
    weight_modifier: int

class ManualOverride(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    event_id: str
    driver_id: str
    created_at: float = Field(default_factory=time.time)

class Settings(BaseModel):
    calendar_ids: List[str]
    days_to_show: int = 7
    home_location: Optional[str] = None
    route_cache_duration_mins: int = 10

class TelemetryEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    driver_id: str
    event_id: str
    action: str  # e.g., 'pickup', 'dropoff', 'arrived'
    timestamp: float = Field(default_factory=time.time)
    details: Optional[str] = None
