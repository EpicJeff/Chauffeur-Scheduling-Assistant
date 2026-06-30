import sys
sys.path.append('.')
from main import refresh_schedule_logic
import datetime
import traceback

now = datetime.datetime.now().astimezone()
start = now.strftime('%Y-%m-%d')
end = (now + datetime.timedelta(days=7)).strftime('%Y-%m-%d')

try:
    print('Testing API schedule call...')
    res = refresh_schedule_logic(start_date_str=start, end_date_str=end, draft=False, force_refresh=True)
    print('Total events returned:', len(res['events']))
    
    trips = [e for e in res['events'] if getattr(e, 'event_type', '') == 'background_trip']
    print('Trips found:', len(trips))
    for t in trips:
        print(f'  - {t.title} {t.start} to {t.end} pax: {getattr(t, "calendar_ids", [])}')
        
    print('\nOther events:')
    for e in res['events']:
        if getattr(e, 'event_type', '') != 'background_trip':
            loc = str(getattr(e, "location", ""))[:20]
            print(f'Event: {e.title[:30]:<30} | {e.start.strftime("%Y-%m-%d %H:%M")} | loc: {loc:<20} | pax: {getattr(e, "calendar_ids", [])} | type: {getattr(e, "event_type", "")}')
            
except Exception as e:
    traceback.print_exc()
