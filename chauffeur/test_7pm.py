import json
import datetime
import zoneinfo

db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
tz = zoneinfo.ZoneInfo("America/New_York")

for p in trip.get("pois", []):
    if p.get("ideal_time_start") in ["17:25", "17:30"]:
        name = p.get("name")
        scheduled = p.get("is_scheduled")
        if scheduled and p.get("scheduled_start"):
            dt = datetime.datetime.fromtimestamp(p["scheduled_start"], tz=datetime.timezone.utc).astimezone(tz)
            print(f"{name}: ideal={p.get('ideal_time_start')}, scheduled_at={dt.time()}")
