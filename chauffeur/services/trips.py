"""Draft trip creation shared by the Trips page and agent tools."""
from threading import RLock

from models.schemas import CreateTripRequest
from services import storage

_create_lock = RLock()


def create_draft(req: CreateTripRequest, idem: str = None, *, travelers: int = None) -> str:
    """Create a page-shaped draft, or return the draft already made for idem.

    The page derives travelers from attendees; tools may supply a headcount
    without inventing attendee identities.
    """
    if idem is None:
        return _create_draft(req, travelers=travelers)
    with _create_lock:
        for trip in storage.get_all_trip_metadata():
            if trip.get('idem') == idem:
                return trip['event_id']
        return _create_draft(req, idem, travelers)


def _create_draft(req: CreateTripRequest, idem: str = None, travelers: int = None) -> str:
    import uuid
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo
    from services import maps
    from services.travel_api import get_live_flight_schedule

    draft_id = f"draft_trip_{uuid.uuid4().hex}"

    if req.start_date and req.end_date:
        # Exact dates provided
        def parse_date(d_str):
            if len(d_str) == 10:
                return datetime.strptime(d_str, "%Y-%m-%d").replace(tzinfo=timezone.utc, hour=9)
            return datetime.fromisoformat(d_str.replace('Z', '+00:00'))

        try:
            mock_start = parse_date(req.start_date)
            mock_end = parse_date(req.end_date)
        except Exception:
            mock_start = datetime.now(timezone.utc)
            mock_end = mock_start + timedelta(days=1)
    else:
        # Flexible dates: Calculate mock start
        base = datetime(2030, 1, 1, tzinfo=timezone.utc)
        day_of_week = req.start_day_of_week if req.start_day_of_week is not None else 0 # default Monday
        offset = (day_of_week - base.weekday()) % 7
        if offset < 0:
            offset += 7

        # 1. Determine Home Location and travel time
        home_loc = maps.get_home_location()
        dest_loc = req.location or "Unknown"
        travel_time_mins = maps.get_travel_time_minutes(home_loc, dest_loc) if home_loc else -1

        arrival_utc = None

        # 2. Determine Departure date string for flight searches
        mock_departure_base = base + timedelta(days=offset)
        dep_date_str = mock_departure_base.strftime("%Y-%m-%d")

        # 3. If driving is impossible (> 15 hrs approx) or failed (-1)
        if home_loc and (travel_time_mins == -1 or travel_time_mins >= 900):
            flight_schedule = get_live_flight_schedule(home_loc, dest_loc, dep_date_str)
            if flight_schedule and "arrival_time" in flight_schedule:
                try:
                    # arrival_time is '2030-01-05 14:40'
                    arr_dt = datetime.strptime(flight_schedule["arrival_time"], "%Y-%m-%d %H:%M")
                    # It's local to destination. Convert to UTC properly.
                    dest_tz_str = maps.get_timezone(dest_loc)
                    dest_tz = ZoneInfo(dest_tz_str)
                    arr_dt_local = arr_dt.replace(tzinfo=dest_tz)
                    # Add 1 hour buffer for airport overhead
                    arrival_utc = arr_dt_local.astimezone(timezone.utc) + timedelta(hours=1)
                except Exception as e:
                    print(f"Failed to parse flight schedule arrival time: {e}")

        # 4. Fallback to driving or generic fallback
        if not arrival_utc:
            if home_loc and travel_time_mins > 0:
                try:
                    home_tz_str = maps.get_timezone(home_loc)
                    home_tz = ZoneInfo(home_tz_str)
                    # Assume 8 AM departure
                    leave_time = datetime(mock_departure_base.year, mock_departure_base.month, mock_departure_base.day, 8, 0, 0, tzinfo=home_tz)
                    arrival_utc = leave_time.astimezone(timezone.utc) + timedelta(minutes=travel_time_mins + 60)
                except Exception as e:
                    print(f"Failed to calculate driving arrival time: {e}")

            if not arrival_utc:
                # Absolute fallback: 9 AM UTC
                arrival_utc = mock_departure_base + timedelta(hours=9)

        mock_start = arrival_utc
        duration = req.duration_nights or 1
        mock_end = mock_start + timedelta(days=duration)

    metadata = {
        "event_id": draft_id,
        "is_draft": True,
        "title": req.title,
        "location": req.location,
        "draft_start_day": req.start_day_of_week,
        "draft_duration_nights": req.duration_nights,
        "mock_start_date": mock_start.timestamp(),
        "mock_end_date": mock_end.timestamp(),
        "budget_min_usd": req.budget_min_usd,
        "budget_max_usd": req.budget_max_usd,
        "flight_preferences": req.flight_preferences,
        "attendees": req.attendees,
        # S4: the create form asked "Show this on the family wall?". Absent
        # means the closed default (parents) — never write a guess.
        "audience": req.audience if req.audience in ('household', 'parents',
                                                     'shared') else None,
        "travelers": max(1, len(req.attendees)) if req.attendees else 1,
        "pois": [],
        "accommodations": [],
        "flights": [],
        "activities": []
    }
    if travelers is not None:
        metadata["travelers"] = travelers
    if idem is not None:
        metadata["idem"] = idem
    storage.set_trip_metadata(draft_id, metadata)
    return draft_id
