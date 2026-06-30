import json
from services import storage
events = storage.get_cached_daily_schedule("2026-07-14")
if events:
    for e in events.get("events", []):
        if e.get("event_type") == "background_trip" or "Check In" in e.get("title", ""):
            print(json.dumps(e, indent=2))
