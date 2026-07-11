import sys, json
import services.storage as storage
storage.get_settings = lambda: {"calendar_ids": ["dummy"]}
from models.schemas import TripMetadata
db = json.load(open("data/db_copy.json", "r"))
meta = db.get("trip_metadata", {}).get("14")
meta["is_draft"] = True
meta["mock_start_date"] = 1786593600
meta["mock_end_date"] = 1787198400
trip = TripMetadata(**meta)
import services.trip_planner as tp
poi_ids = [p.id for p in trip.pois]
for res in tp.schedule_pois_bulk(trip, poi_ids):
    print(res)
