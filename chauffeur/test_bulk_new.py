import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
import services.storage as storage
db = json.load(open("data/db.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True

# mock storage
import sys
import unittest.mock as mock
mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage

from services.trip_planner import schedule_pois_bulk

# Set all to unscheduled
for p in trip.pois:
    if not p.is_background:
        p.is_scheduled = False
        p.scheduled_start = None
        p.scheduled_end = None

print("Running bulk scheduler...")
res_list = list(schedule_pois_bulk(trip, [p.id for p in trip.pois if not p.is_background]))

for res in res_list:
    name = next((p.name for p in trip.pois if p.id == res['poi_id']), 'Unknown')
    if "Chef Mickey" in name:
        print(f"{name}: success={res.get('success')}, reason={res.get('reason')}")
        if 'suggested_fixes' in res:
            print(f"  Fixes: {res['suggested_fixes']}")
            
for p in trip.pois:
    if p.is_scheduled and p.scheduled_start and not p.is_background:
        dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc).astimezone(zoneinfo.ZoneInfo("America/New_York"))
        if dt.weekday() == 3: # Thursday
            print(f"Thu: {p.name} at {dt.strftime('%H:%M')}")
