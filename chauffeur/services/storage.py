from tinydb import TinyDB, Query
from typing import List, Optional
import os
import json
import threading

db_lock = threading.Lock()

if os.path.exists('/data/options.json'):
    DB_PATH = '/data/chauffeur_db.json'
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db.json')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def fix_corrupted_db(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        if not content:
            return
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            if "Extra data" in str(e):
                decoder = json.JSONDecoder()
                obj, idx = decoder.raw_decode(content)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(obj, f)
    except Exception:
        pass

with db_lock:
    fix_corrupted_db(DB_PATH)
    db = TinyDB(DB_PATH)
    drivers_table = db.table('drivers')
    rules_table = db.table('rules')
    priority_rules_table = db.table('priority_rules')
    overrides_table = db.table('overrides')
    cache_table = db.table('schedule_cache')
    settings_table = db.table('settings')
    distance_cache_table = db.table('distance_cache')
    polyline_cache_table = db.table('polyline_cache')
    passengers_table = db.table('passengers')
    telemetry_table = db.table('telemetry')
    push_subscriptions_table = db.table('push_subscriptions')
    drive_status_table = db.table('drive_status')

def migrate_passengers_from_settings():
    with db_lock:
        settings_docs = settings_table.all()
        if not settings_docs:
            return
        
        settings = settings_docs[0]
        passenger_cals = settings.get('passenger_calendar_ids', [])
        metadata = settings.get('calendar_metadata', {})
        
        if not passenger_cals:
            return
            
        existing_passengers = passengers_table.all()
        existing_hashtags = {p.get('hashtag') for p in existing_passengers if p.get('hashtag')}
        
        for cal_id in passenger_cals:
            already_migrated = False
            for p in existing_passengers:
                if cal_id in p.get('calendar_ids', []):
                    already_migrated = True
                    break
            if already_migrated:
                continue
                
            meta = metadata.get(cal_id, {})
            name = meta.get('summary', cal_id)
            
            base_hashtag = '#' + ''.join(c.lower() for c in name if c.isalnum())
            if not base_hashtag or base_hashtag == '#':
                base_hashtag = '#passenger'
                
            hashtag = base_hashtag
            counter = 1
            while hashtag in existing_hashtags:
                hashtag = f"{base_hashtag}{counter}"
                counter += 1
                
            new_passenger = {
                'name': name,
                'hashtag': hashtag,
                'calendar_ids': [cal_id]
            }
            
            passengers_table.insert(new_passenger)
            existing_hashtags.add(hashtag)
            existing_passengers.append(new_passenger)
            
        # Remove passenger_calendar_ids so we don't migrate again
        settings.pop('passenger_calendar_ids', None)
        settings_table.update(settings, doc_ids=[settings.doc_id])

migrate_passengers_from_settings()

def get_cached_route_info(origin: str, destination: str, max_age_mins: int = 10) -> Optional[dict]:
    import time
    with db_lock:
        QueryObj = Query()
        result = polyline_cache_table.search((QueryObj.origin == origin) & (QueryObj.destination == destination))
        if result:
            cached_data = result[0]
            timestamp = cached_data.get('timestamp', 0)
            if time.time() - timestamp <= max_age_mins * 60:
                return cached_data.get('info')
        return None

def set_cached_route_info(origin: str, destination: str, info: dict):
    import time
    with db_lock:
        QueryObj = Query()
        polyline_cache_table.remove((QueryObj.origin == origin) & (QueryObj.destination == destination))
        polyline_cache_table.insert({'origin': origin, 'destination': destination, 'info': info, 'timestamp': time.time()})

def get_cached_travel_time(origin: str, destination: str, max_age_mins: int = 10) -> Optional[int]:
    import time
    with db_lock:
        QueryObj = Query()
        result = distance_cache_table.search((QueryObj.origin == origin) & (QueryObj.destination == destination))
        if result:
            cached_data = result[0]
            timestamp = cached_data.get('timestamp', 0)
            if time.time() - timestamp <= max_age_mins * 60:
                return cached_data['minutes']
        return None

def set_cached_travel_time(origin: str, destination: str, minutes: int):
    import time
    with db_lock:
        QueryObj = Query()
        distance_cache_table.remove((QueryObj.origin == origin) & (QueryObj.destination == destination))
        distance_cache_table.insert({'origin': origin, 'destination': destination, 'minutes': minutes, 'timestamp': time.time()})

# Driver CRUD
def get_all_drivers() -> List[dict]:
    with db_lock:
        drivers = []
        for d in drivers_table.all():
            doc = dict(d)
            doc['doc_id'] = d.doc_id
            if 'hashtags' not in doc:
                doc['hashtags'] = []
            drivers.append(doc)
        return drivers

def add_driver(driver_data: dict) -> int:
    with db_lock:
        return drivers_table.insert(driver_data)

def delete_driver(doc_id: int):
    with db_lock:
        drivers_table.remove(doc_ids=[doc_id])

# Passenger CRUD
def get_all_passengers() -> List[dict]:
    with db_lock:
        passengers = []
        for p in passengers_table.all():
            doc = dict(p)
            doc['doc_id'] = p.doc_id
            
            # Auto-migrate string 'hashtag' to list 'hashtags'
            if 'hashtag' in doc:
                old_tag = doc.pop('hashtag')
                if 'hashtags' not in doc:
                    doc['hashtags'] = []
                if old_tag and old_tag not in doc['hashtags']:
                    doc['hashtags'].append(old_tag)
                # Save migration
                passengers_table.update({'hashtags': doc['hashtags']}, doc_ids=[doc['doc_id']])
                try:
                    passengers_table.update(db.table('passengers').update(db.delete('hashtag'), doc_ids=[doc['doc_id']]))
                except:
                    # Depending on TinyDB version, deleting a field might differ.
                    passengers_table.update({'hashtag': None}, doc_ids=[doc['doc_id']])
                
            if 'hashtags' not in doc:
                doc['hashtags'] = []
                
            passengers.append(doc)
        return passengers

def get_passengers() -> List[dict]:
    with db_lock:
        return passengers_table.all()

def add_passenger(passenger_data: dict) -> int:
    with db_lock:
        return passengers_table.insert(passenger_data)

def update_passenger(doc_id: int, passenger_data: dict):
    with db_lock:
        passengers_table.update(passenger_data, doc_ids=[doc_id])

def delete_passenger(doc_id: int):
    with db_lock:
        passengers_table.remove(doc_ids=[doc_id])

def add_telemetry_event(event_data: dict) -> int:
    with db_lock:
        return telemetry_table.insert(event_data)

def get_telemetry_events(limit: int = 50) -> List[dict]:
    with db_lock:
        events = telemetry_table.all()
        events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return events[:limit]

# Rule CRUD
def get_all_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            rules.append(doc)
        return rules

def add_rule(rule_data: dict) -> int:
    with db_lock:
        return rules_table.insert(rule_data)

def update_rule(doc_id: int, rule_data: dict):
    with db_lock:
        rules_table.update(rule_data, doc_ids=[doc_id])

def delete_rule(doc_id: int):
    with db_lock:
        rules_table.remove(doc_ids=[doc_id])

# Priority Rule CRUD
def get_all_priority_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in priority_rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            rules.append(doc)
        return rules

def add_priority_rule(rule_data: dict) -> int:
    with db_lock:
        return priority_rules_table.insert(rule_data)

def update_priority_rule(doc_id: int, rule_data: dict):
    with db_lock:
        priority_rules_table.update(rule_data, doc_ids=[doc_id])

def delete_priority_rule(doc_id: int):
    with db_lock:
        priority_rules_table.remove(doc_ids=[doc_id])

# Overrides CRUD
def get_all_overrides() -> List[dict]:
    with db_lock:
        overrides = []
        for r in overrides_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            overrides.append(doc)
        return overrides

def add_override(override_data: dict) -> int:
    with db_lock:
        # Overrides are unique per event_id, so remove existing if present
        overrides_table.remove(Query().event_id == override_data['event_id'])
        return overrides_table.insert(override_data)

def delete_override(doc_id: int):
    with db_lock:
        overrides_table.remove(doc_ids=[doc_id])

# Schedule Cache
def get_cached_schedule() -> dict:
    with db_lock:
        cache = cache_table.all()
        if cache:
            return cache[0]
        return {}

def set_cached_schedule(schedule_data: dict):
    with db_lock:
        cache_table.truncate()
        cache_table.insert(schedule_data)

# Settings CRUD
def get_settings() -> dict:
    with db_lock:
        all_settings = settings_table.all()
        if not all_settings:
            return {"calendar_ids": []}
        return dict(all_settings[0])

def update_settings(settings_data: dict):
    with db_lock:
        settings_table.truncate()
        settings_table.insert(settings_data)

# Push Subscriptions
def save_push_subscription(driver_id: str, subscription_info: dict):
    with db_lock:
        push_subscriptions_table.upsert({'driver_id': driver_id, 'subscription': subscription_info}, Query().driver_id == driver_id)

def get_push_subscriptions(driver_id: str = None):
    with db_lock:
        if driver_id:
            return push_subscriptions_table.search(Query().driver_id == driver_id)
        return push_subscriptions_table.all()

# Drive Status
def mark_drive_status(leg_id: str, status: str):
    with db_lock:
        drive_status_table.upsert({'leg_id': leg_id, 'status': status}, Query().leg_id == leg_id)

def get_completed_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'completed')]
