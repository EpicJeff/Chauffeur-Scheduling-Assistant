import json
import datetime
import zoneinfo
db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
tz = zoneinfo.ZoneInfo("America/New_York")

for p in trip.get("pois", []):
    if p.get("is_background") and p.get("scheduled_start"):
        start = datetime.datetime.fromtimestamp(p["scheduled_start"], tz=datetime.timezone.utc).astimezone(tz)
        if start.weekday() == 6:
            end = datetime.datetime.fromtimestamp(p["scheduled_end"], tz=datetime.timezone.utc).astimezone(tz)
            print(f"ANCHOR: {p.get('name')} bounds: {start} to {end}")
