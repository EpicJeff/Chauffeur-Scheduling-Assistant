import sys
import json
import datetime, zoneinfo

with open('e:/repositories/Chauffeur/chauffeur/data/db_copy.json', 'r') as f:
    db = json.load(f)

meta = db.get('trip_metadata', {}).get('14')
meta['is_draft'] = True
meta['mock_start_date'] = 1786593600
meta['mock_end_date'] = 1787198400

from models.schemas import TripMetadata, TripPOI
trip = TripMetadata(**meta)

import services.storage as storage
def dummy_settings():
    return {'calendar_ids': ['dummy']}
storage.get_settings = dummy_settings

import services.trip_planner as tp

poi = next((p for p in trip.pois if 'Tusker' in p.name), None)

def trace_lines(frame, event, arg):
    if event == 'line' and 'trip_planner.py' in frame.f_code.co_filename:
        if frame.f_code.co_name == 'find_slots':
            loc = frame.f_locals
            if 'slot_local' in loc and loc['slot_local'].hour == 12 and loc['slot_local'].minute == 0:
                if frame.f_lineno == 513:
                    print(f"local_tz is {loc.get('local_tz')}")
                    print(f"slot_local is {loc.get('slot_local')}")
                    print(f"slot_start is {loc.get('slot_start')}")
    return trace_lines

sys.settrace(trace_lines)
tp.schedule_poi(trip, poi)
sys.settrace(None)
