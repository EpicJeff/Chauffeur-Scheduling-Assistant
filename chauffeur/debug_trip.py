import sys
sys.path.append('.')
from main import _refresh_schedule_logic_impl
from services import storage, maps, calendar
import datetime

now = datetime.datetime.now().astimezone()
start = now.strftime('%Y-%m-%d')
end = (now + datetime.timedelta(days=7)).strftime('%Y-%m-%d')

try:
    print('Testing schedule fetch...')
    
    # Need to initialize calendar credentials by hitting the same path main does
    options = storage.get_settings()
    calendar_ids = options.get('calendar_ids', [])
    raw_events = calendar.fetch_upcoming_events(calendar_ids, days=7, start_date_str=start, end_date_str=end)
    print(f'Fetched {len(raw_events)} raw events')
    
    from main import refresh_schedule_logic
    res = refresh_schedule_logic(start_date_str=start, end_date_str=end, force_refresh=True, draft=False)
    
except Exception as e:
    import traceback
    traceback.print_exc()
