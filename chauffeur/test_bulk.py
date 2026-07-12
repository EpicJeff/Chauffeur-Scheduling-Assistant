import json
from models.schemas import TripMetadata
import datetime
import zoneinfo
import services.storage as storage
db = json.load(open("data/db_copy.json", "r"))
trip = TripMetadata(**db.get("trip_metadata", {}).get("14"))
trip.is_draft = True
trip.mock_start_date = int(datetime.datetime.now().timestamp())
trip.mock_end_date = trip.mock_start_date + (7 * 86400)

import sys
import unittest.mock as mock
mock_storage = mock.MagicMock()
mock_storage.get_settings.return_value = {"calendar_ids": ["dummy"]}
sys.modules['services.storage'] = mock_storage

from services.trip_planner import schedule_pois_bulk

for p in trip.pois:
    p.is_scheduled = False
    p.scheduled_start = None
    p.scheduled_end = None

print("Running bulk scheduler...")
for res in schedule_pois_bulk(trip):
    name = next((p.name for p in trip.pois if p.id == res['poi_id']), 'Unknown')
    if "Garden Grill" in name:
        print(f"{name}: success={res.get('success')}, reason={res.get('reason')}")
        if 'suggested_fixes' in res:
            print(f"  Fixes: {res['suggested_fixes']}")
            
for p in trip.pois:
    if p.is_scheduled and p.scheduled_start:
        dt = datetime.datetime.fromtimestamp(p.scheduled_start, tz=datetime.timezone.utc).astimezone(zoneinfo.ZoneInfo("America/New_York"))
        print(f"SCHEDULED: {p.name} at {dt.strftime('%a %H:%M')}")
