import json
db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
for p in trip.get("pois", []):
    if p.get("name") in ["Crystal Palace Character Dining", "Columbia Harbour House", "The Plaza Restaurant"]:
        print(f"{p.get('name')}: constraints: valid_days={p.get('valid_days_of_week')}, ideal_start={p.get('ideal_time_start')}")
