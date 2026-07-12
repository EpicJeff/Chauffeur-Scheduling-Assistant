import json
import datetime
import zoneinfo

db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
tz = zoneinfo.ZoneInfo("America/New_York")

print("SCHEDULED POIS ON DAY 6 (Sunday):")
for p in trip.get("pois", []):
    if p.get("is_scheduled") and p.get("scheduled_start"):
        dt = datetime.datetime.fromtimestamp(p["scheduled_start"], tz=datetime.timezone.utc).astimezone(tz)
        if dt.weekday() == 6:
            print(f"  {p.get('name')} at {dt.time()} to {datetime.datetime.fromtimestamp(p['scheduled_end'], tz=datetime.timezone.utc).astimezone(tz).time()} (is_bg={p.get('is_background')})")
