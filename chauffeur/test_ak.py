import json
db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
for p in trip.get("pois", []):
    if "Akershus" in p.get("name"):
        print(f"Akershus constraints: valid_days={p.get('valid_days_of_week')}, ideal_start={p.get('ideal_time_start')}, is_bg={p.get('is_background')}, location={p.get('location')}")
