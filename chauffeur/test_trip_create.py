import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from main import create_trip_api
from models.schemas import CreateTripRequest

req = CreateTripRequest(
    title="Test Trip to Paris",
    location="Paris, France",
    start_day_of_week=6, # Sunday
    duration_nights=7,
    travelers=2
)

try:
    res = create_trip_api(req)
    print("Trip created:", res)
    if "event_id" in res:
        from services.storage import get_trip_metadata
        meta = get_trip_metadata(res["event_id"])
        print("Metadata mock start:", meta.get("mock_start_date"))
        print("Metadata draft duration:", meta.get("draft_duration_nights"))
except Exception as e:
    import traceback
    traceback.print_exc()
