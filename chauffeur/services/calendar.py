import datetime
import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from models.schemas import Event

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')

import google.auth
from google.oauth2.service_account import Credentials
import json

import threading
_local_storage = threading.local()
_global_creds = None
_creds_lock = threading.Lock()

def get_calendar_service():
    global _global_creds
    # Each thread must have its own service client to prevent socket sharing and SSL errors
    if hasattr(_local_storage, 'service'):
        return _local_storage.service
        
    if _global_creds is None:
        with _creds_lock:
            if _global_creds is None:
                creds = None
                # 1. Try to load from Home Assistant Add-on options
                options_file = '/data/options.json'
                if os.path.exists(options_file):
                    try:
                        with open(options_file, 'r') as f:
                            options = json.load(f)
                        raw_sa_json = options.get('google_service_account_json')
                        if raw_sa_json:
                            sa_info = json.loads(raw_sa_json)
                            creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
                    except Exception as e:
                        print(f"Failed to load credentials from HA options.json: {e}")

                if not creds:
                    # 2. Try to load from local credentials.json
                    if os.path.exists(CREDENTIALS_FILE):
                        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
                        
                if not creds:
                    # 3. Fall back to default application credentials
                    creds, _ = google.auth.default(scopes=SCOPES)
                    
                _global_creds = creds
                
    service = build('calendar', 'v3', credentials=_global_creds, static_discovery=True)
    _local_storage.service = service
    return service

def _fetch_single_calendar(cal_id, time_min, time_max):
    service = get_calendar_service()
    try:
        events = []
        page_token = None
        while True:
            events_result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime',
                pageToken=page_token
            ).execute()
            events.extend(events_result.get('items', []))
            page_token = events_result.get('nextPageToken')
            if not page_token:
                break
        return cal_id, events
    except Exception as ex:
        print(f"Error fetching from calendar {cal_id}: {ex}")
        return cal_id, []

def fetch_upcoming_events(calendar_ids: list[str], days=7, start_date_str=None, end_date_str=None) -> list[Event]:
    if start_date_str and end_date_str:
        if 'T' in start_date_str:
            time_min = start_date_str
            time_max = end_date_str
        else:
            start_dt = datetime.datetime.fromisoformat(start_date_str).astimezone()
            end_dt = datetime.datetime.fromisoformat(end_date_str).astimezone()
            time_min = start_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            time_max = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()
    else:
        now_local = datetime.datetime.now().astimezone()
        start_of_day = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        time_min = start_of_day.isoformat()
        
        # Target day is today + (days - 1). End of day is 23:59:59.
        target_date = now_local + datetime.timedelta(days=days-1)
        end_of_target_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        time_max = end_of_target_day.isoformat()
        
    # Group events by (title, start, end, location)
    grouped_events = {}
    
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(calendar_ids) or 1)) as executor:
        futures = [executor.submit(_fetch_single_calendar, cal_id, time_min, time_max) for cal_id in calendar_ids]
        for future in concurrent.futures.as_completed(futures):
            cal_id, events = future.result()
            for e in events:
                # Handle all-day events vs timed events
                start_str = e['start'].get('dateTime', e['start'].get('date'))
                end_str = e['end'].get('dateTime', e['end'].get('date'))
                
                # Python 3.11+ fromisoformat handles "Z"
                start_str = start_str.replace('Z', '+00:00')
                end_str = end_str.replace('Z', '+00:00')
                
                is_all_day = False
                if len(start_str) <= 10:  # YYYY-MM-DD
                    is_all_day = True
                    start_dt = datetime.datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                    end_dt = datetime.datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                else:
                    start_dt = datetime.datetime.fromisoformat(start_str)
                    end_dt = datetime.datetime.fromisoformat(end_str)
                
                title = e.get('summary', '(No Title)')
                location = e.get('location', None)
                description = e.get('description', None)
                loc_key = location.strip().lower() if location else ""
                
                group_key = (title.strip().lower(), start_dt, end_dt, loc_key)
                
                internal_id = f"{cal_id}::{e['id']}"
                
                if group_key not in grouped_events:
                    grouped_events[group_key] = {
                        "title": title,
                        "start": start_dt,
                        "end": end_dt,
                        "location": location,
                        "description": description,
                        "all_day": is_all_day,
                        "calendar_ids": [],
                        "source_event_ids": [],
                        "recurring_event_id": e.get('recurringEventId') or (e['id'].split('_')[0] if '_' in e.get('id', '') else None)
                    }
                
                grouped_events[group_key]["calendar_ids"].append(cal_id)
                grouped_events[group_key]["source_event_ids"].append(internal_id)
            
    # Convert grouped dictionary into Event objects
    all_events = []
    for g in grouped_events.values():
        # Use the first source_event_id as the primary unique ID for the solver
        primary_id = g["source_event_ids"][0]
        event_obj = Event(
            id=primary_id,
            title=g["title"],
            start=g["start"],
            end=g["end"],
            location=g["location"],
            description=g["description"],
            calendar_ids=g["calendar_ids"],
            source_event_ids=g["source_event_ids"],
            recurring_event_id=g.get("recurring_event_id"),
            all_day=g.get("all_day", False)
        )
        all_events.append(event_obj)
        
    return all_events

_metadata_cache = {}
_metadata_cache_lock = threading.Lock()

def get_calendar_metadata(calendar_ids: list[str]) -> dict:
    """
    Fetches the summary and assigns a deterministic background color for each calendar 
    from the Google Calendar API. Cached in memory and fetched in parallel to prevent bottlenecks.
    """
    global _metadata_cache
    service = get_calendar_service()
    
    PALETTE = [
        "#3B82F6", # Blue
        "#10B981", # Green
        "#8B5CF6", # Purple
        "#EC4899", # Pink
        "#14B8A6", # Teal
        "#F97316", # Orange
        "#06B6D4", # Cyan
        "#84CC16"  # Lime
    ]

    missing_cals = []
    with _metadata_cache_lock:
        for cal_id in calendar_ids:
            if cal_id not in _metadata_cache:
                missing_cals.append(cal_id)

    if missing_cals:
        def _fetch_meta(cal_id):
            local_service = get_calendar_service()
            color_index = sum(ord(c) for c in cal_id) % len(PALETTE)
            cal_color = PALETTE[color_index]
            try:
                cal = local_service.calendars().get(calendarId=cal_id).execute()
                summary = cal.get("summary")
            except Exception as ex:
                try:
                    cal = local_service.calendarList().get(calendarId=cal_id).execute()
                    summary = cal.get("summary")
                except Exception as ex2:
                    summary = None
                    
            if not summary or summary == "Unknown Calendar":
                from services import storage
                for p in storage.get_passengers():
                    if cal_id in p.get('calendar_ids', []):
                        summary = f"{p.get('name', 'Unknown')}'s Calendar"
                        break
                if not summary:
                    for d in storage.get_all_drivers():
                        if cal_id in d.get('calendar_ids', []):
                            summary = f"{d.get('name', 'Driver')}'s Calendar"
                            break
                            
            if not summary:
                summary = "Unknown Calendar"
                
            return cal_id, {
                "summary": summary,
                "backgroundColor": cal_color,
                "foregroundColor": "#FFFFFF"
            }

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(10, len(missing_cals) or 1)) as executor:
            futures = [executor.submit(_fetch_meta, cal_id) for cal_id in missing_cals]
            for future in concurrent.futures.as_completed(futures):
                cal_id, meta = future.result()
                with _metadata_cache_lock:
                    _metadata_cache[cal_id] = meta

    with _metadata_cache_lock:
        return {cal_id: _metadata_cache[cal_id] for cal_id in calendar_ids if cal_id in _metadata_cache}

def update_event_details(source_event_ids: list[str], details: dict):
    """
    Updates the details (summary, description, location, start, end) for multiple Google Calendar events.
    """
    service = get_calendar_service()
    
    # Map current calendars to their event IDs
    current_cals = {}
    for source_id in source_event_ids:
        c_id, e_id = source_id.split('::', 1)
        current_cals[c_id] = e_id
        
    # Handle Guest Additions/Removals via duplicating/deleting events
    if 'attendees' in details:
        desired_cals = set(details['attendees'])
        cals_to_remove = set(current_cals.keys()) - desired_cals
        cals_to_add = desired_cals - set(current_cals.keys())
        
        # Get base event before we potentially delete everything
        base_event = None
        if cals_to_add and current_cals:
            base_c_id, base_e_id = next(iter(current_cals.items()))
            try:
                base_event = service.events().get(calendarId=base_c_id, eventId=base_e_id).execute()
            except Exception as ex:
                print(f"Error fetching base event for cloning: {ex}")
                
        # 1. Remove events from calendars that were unchecked
        for c_id in cals_to_remove:
            e_id = current_cals[c_id]
            try:
                service.events().delete(calendarId=c_id, eventId=e_id).execute()
                print(f"Removed guest event from {c_id}")
            except Exception as ex:
                print(f"Error removing event from {c_id}: {ex}")
                
        # We also need to remove these from current_cals so we don't try to update them later
        for c_id in cals_to_remove:
            del current_cals[c_id]
            
        # 2. Add events to calendars that were newly checked
        if cals_to_add and base_event:
            new_event = {
                'summary': details.get('title', base_event.get('summary', '(No Title)')),
                'location': details.get('location', base_event.get('location', '')),
                'description': details.get('description', base_event.get('description', '')),
                'start': {'dateTime': details['start']} if 'start' in details else base_event.get('start'),
                'end': {'dateTime': details['end']} if 'end' in details else base_event.get('end'),
            }
            
            for c_id in cals_to_add:
                try:
                    service.events().insert(calendarId=c_id, body=new_event).execute()
                    print(f"Added guest event to {c_id}")
                except Exception as ex:
                    print(f"Error adding event to {c_id}: {ex}")
                    
    # Now update the remaining existing events
    for cal_id, original_id in current_cals.items():
        try:
            event = service.events().get(calendarId=cal_id, eventId=original_id).execute()
            
            if 'title' in details:
                event['summary'] = details['title']
            if 'description' in details:
                event['description'] = details['description']
            if 'location' in details:
                event['location'] = details['location']
                
            # Time updates
            if 'start' in details and 'end' in details:
                event['start'] = {'dateTime': details['start']}
                event['end'] = {'dateTime': details['end']}
                
            service.events().update(calendarId=cal_id, eventId=original_id, body=event).execute()
        except Exception as ex:
            print(f"Error updating details for {cal_id}: {ex}")

def write_event_color(calendar_id: str, event_id: str, color_id: str):
    """
    Updates the color of an event.
    color_id must be a string '1' through '11'.
    """
    service = get_calendar_service()
    original_id = event_id.split('::', 1)[-1]
    try:
        event = service.events().get(calendarId=calendar_id, eventId=original_id).execute()
        event['colorId'] = color_id
        service.events().update(calendarId=calendar_id, eventId=original_id, body=event).execute()
    except Exception as ex:
        print(f"Error updating color for {event_id}: {ex}")
