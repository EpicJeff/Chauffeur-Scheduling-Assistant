import json
db = json.load(open("data/db.json", "r"))
trip = db.get("trip_metadata", {}).get("14", {})
for p in trip.get("pois", []):
    if "Chef Mickey" in p.get("name"):
        print(f"Chef Mickey opening hours: {p.get('opening_hours')}")
