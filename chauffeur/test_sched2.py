import main
from services import storage
from services import calendar

settings = storage.get_settings()
cals = settings.get("calendar_ids", [])
raw = calendar.fetch_upcoming_events(cals, start_date_str="2026-06-01T00:00:00Z", end_date_str="2026-06-30T23:59:59Z")
print("Num raw events:", len(raw))
