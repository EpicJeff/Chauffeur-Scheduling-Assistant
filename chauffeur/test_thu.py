import json
import datetime
import zoneinfo

db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
tz = zoneinfo.ZoneInfo("America/New_York")

print("SCHEDULED POIS ON THURSDAY (Day 3):")
for p in trip.get("pois", []):
    if p.get("is_scheduled") and p.get("scheduled_start") and not p.get("is_background"):
        dt = datetime.datetime.fromtimestamp(p["scheduled_start"], tz=datetime.timezone.utc).astimezone(tz)
        if dt.weekday() == 3:
            print(f"  {p.get('name')} at {dt.time()} (Priority: {p.get('priority')})")
