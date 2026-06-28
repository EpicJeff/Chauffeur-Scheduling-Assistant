import sys
sys.path.append('.')
from services import storage
from services.calendar import fetch_upcoming_events
from datetime import datetime as dt, timedelta
import re

calendar_ids = storage.get_settings().get('calendar_ids', [])
trip_hashtags = storage.get_settings().get('trip_hashtags', [])
now = dt.now()
start_date = (now - timedelta(days=30)).strftime('%Y-%m-%d')
end_date = (now + timedelta(days=365)).strftime('%Y-%m-%d')

raw_events = fetch_upcoming_events(calendar_ids, start_date_str=start_date, end_date_str=end_date)
print(f'Total fetched events: {len(raw_events)}')

def fuzzy(text, tag):
    if not text or not tag: return False
    clean = re.sub(r'<[^>]+>', ' ', text)
    words = [w.lower().strip('.,;?!()[]{}"\'') for w in clean.split()]
    return tag.lower().strip('.,;?!()[]{}"\'') in words

trips = []
for e in raw_events:
    is_trip = False
    title = getattr(e, 'title', '')
    desc = getattr(e, 'description', '')
    if any(fuzzy(title, t) or fuzzy(desc, t) for t in trip_hashtags):
        is_trip = True
    config = storage.get_event_config(e.id)
    if config and config.get('is_trip'):
        is_trip = True
    if is_trip: trips.append((e.id, title, e.start))

print(f'Total trips found: {len(trips)}')
for t in trips:
    print(t[1], t[2], t[0])
