import json
from models.schemas import TripMetadata
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))

print("Background POIs:")
for p in trip.pois:
    if getattr(p, 'is_background', False):
        print(f"{p.name}: valid_days={p.valid_days_of_week}, is_scheduled={p.is_scheduled}")

print("\nConstrained POIs:")
for p in trip.pois:
    if getattr(p, 'ideal_time_start', None) and getattr(p, 'valid_days_of_week', None):
        print(f"{p.name}: valid_days={p.valid_days_of_week}, is_scheduled={p.is_scheduled}")
