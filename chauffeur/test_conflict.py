import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
local_tz = zoneinfo.ZoneInfo("America/New_York")

gg = next((p for p in trip.pois if "Garden Grill" in p.name), None)

print(f"Garden Grill: is_scheduled={gg.is_scheduled}")

for p in trip.pois:
    if p.is_scheduled and p.scheduled_start and not getattr(p, 'is_background', False):
        start_dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc).astimezone(local_tz)
        if start_dt.weekday() == 3: # Wednesday
            print(f"CONFLICT ON WEDNESDAY: {p.name} from {start_dt.time()}")
