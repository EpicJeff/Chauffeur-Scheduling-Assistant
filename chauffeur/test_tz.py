import json
from models.schemas import TripMetadata
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
print(f"Timezone: {getattr(trip, 'timeZone', None)}")
print(f"Location: {getattr(trip, 'location', None)}")
