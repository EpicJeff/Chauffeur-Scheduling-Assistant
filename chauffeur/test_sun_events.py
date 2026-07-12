import json
import datetime
import zoneinfo
db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
tz = zoneinfo.ZoneInfo("America/New_York")

events = db.get("events", {}).values()
print("EVENTS ON SUNDAY (Day 6):")
for e in events:
    if not e.get("start"): continue
    start = datetime.datetime.fromtimestamp(e["start"], tz=datetime.timezone.utc).astimezone(tz)
    if start.weekday() == 6 and start.year == 2026 and start.month == 8:
        end = datetime.datetime.fromtimestamp(e["end"], tz=datetime.timezone.utc).astimezone(tz)
        print(f"Event: {e.get('title')} ({e.get('event_type')}) from {start.time()} to {end.time()}")
