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
    is_disabled: bool = False
    calendar_ids: List[str] = Field(default_factory=list)

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
