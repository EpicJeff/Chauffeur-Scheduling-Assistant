import json
from models.schemas import TripMetadata
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))

pois = []
for p in trip.pois:
    if "Boma" in p.name or "Magic Kingdom" in p.name or "Be Our Guest" in p.name:
        pois.append(p)
    elif "Disney Springs" in p.name:
        pois.append(p)

print("Unsorted:")
for p in pois:
    print(f"{p.name} - ideal: {p.ideal_time_start}, valid: {p.valid_days_of_week}")

pois_sorted = sorted(
    pois, 
    key=lambda p: (bool(getattr(p, "ideal_time_start", None)), bool(getattr(p, "valid_days_of_week", None))), 
    reverse=True
)
print("\nSorted:")
for p in pois_sorted:
    print(f"{p.name} - ideal: {p.ideal_time_start}, valid: {p.valid_days_of_week}")
