import json
db = json.load(open("data/db.json", "r"))
for trip_id, trip in db.get("trip_metadata", {}).items():
    for p in trip.get("pois", []):
        if p.get("ideal_time_start") == "17:25" or p.get("ideal_time_start") == "17:30":
            print(f"Trip ID: {trip_id}, POI Name: {p.get('name')}, Scheduled: {p.get('is_scheduled')}, Constraints: {p.get('valid_days_of_week')}, {p.get('ideal_time_start')}")
            if not p.get("is_scheduled"):
                # find what got scheduled around 17:25
                for op in trip.get("pois", []):
                    if op.get("is_scheduled") and op.get("scheduled_start"):
                        import datetime
                        import zoneinfo
                        tz = zoneinfo.ZoneInfo("America/New_York")
                        dt = datetime.datetime.fromtimestamp(op["scheduled_start"], tz=datetime.timezone.utc).astimezone(tz)
                        if dt.hour == 17 and (dt.minute >= 0 and dt.minute <= 45):
                            print(f"  Conflict Candidate: {op.get('name')} at {dt.time()} on Day {dt.weekday()} (Constraints: {op.get('valid_days_of_week')}, {op.get('ideal_time_start')})")
