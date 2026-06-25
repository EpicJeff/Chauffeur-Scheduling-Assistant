from tinydb import TinyDB, Query
from typing import List, Optional
import os
import json
import threading

db_lock = threading.RLock()

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
    themes_table = db.table('themes')
    ai_feedback_table = db.table('ai_feedback')
    overrides_table = db.table('overrides')
    cache_table = db.table('schedule_cache')
    custom_schedules_table = db.table('custom_schedules')
    daily_schedules_table = db.table('daily_schedules')
    settings_table = db.table('settings')
    distance_cache_table = db.table('distance_cache')

    geocode_cache_table = db.table('geocode_cache')
    api_usage_table = db.table('api_usage')
    passengers_table = db.table('passengers')
    telemetry_table = db.table('telemetry')
    push_subscriptions_table = db.table('push_subscriptions')
    drive_status_table = db.table('drive_status')
    pending_notifications_table = db.table('pending_notifications')
    event_configs_table = db.table('event_configs')
    api_requests_log_table = db.table('api_requests_log')
    chat_history_table = db.table('chat_history')
    errands_table = db.table('errands')
    errand_rules_table = db.table('errand_rules')

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

def migrate_duplicate_rules():
    with db_lock:
        rules = rules_table.all()
        for r in rules:
            if r.get('constraint_type') == 'mutually_exclusive':
                r['constraint_type'] = 'duplicate'
                r['duplicate_action'] = 'schedule_one'
                rules_table.update(r, doc_ids=[r.doc_id])
            elif r.get('constraint_type') == 'ignore_mutually_exclusive':
                r['constraint_type'] = 'duplicate'
                r['duplicate_action'] = 'schedule_all'
                rules_table.update(r, doc_ids=[r.doc_id])

migrate_duplicate_rules()

def cleanup_corrupted_travel_times():
    with db_lock:
        QueryObj = Query()
        # Remove any cached travel time >= 120 minutes (like the corrupted 999 values)
        distance_cache_table.remove(QueryObj.minutes >= 120)

cleanup_corrupted_travel_times()

def prime_api_usage_seeding():
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    seeds = {
        'matrix': 117902,
        'directions': 2499,
        'geocode': 927
    }
    with db_lock:
        settings_docs = settings_table.all()
        settings = dict(settings_docs[0]) if settings_docs else {}
        has_seeded = settings.get('has_seeded_truth_2026_06', False)
        
        for endpoint, seed_val in seeds.items():
            log_records = api_requests_log_table.search(Query().endpoint == endpoint)
            log_sum = sum(r.get('count', 0) for r in log_records)
            expected_min = seed_val + log_sum
            
            res = api_usage_table.search((Query().month == current_month) & (Query().endpoint == endpoint))
            if res:
                current_val = res[0].get('count', 0)
                if current_val < expected_min:
                    api_usage_table.update({'count': expected_min}, (Query().month == current_month) & (Query().endpoint == endpoint))
            else:
                api_usage_table.insert({'month': current_month, 'endpoint': endpoint, 'count': expected_min})
                    
        if not has_seeded and settings_docs:
            settings['has_seeded_truth_2026_06'] = True
            settings_table.update(settings, doc_ids=[settings_docs[0].doc_id])

prime_api_usage_seeding()

# Geocode Cache
def mark_all_daily_schedules_dirty():
    with db_lock:
        for entry in daily_schedules_table.all():
            entry['events_hash'] = 'DIRTY'
            daily_schedules_table.update(entry, doc_ids=[entry.doc_id])

def clear_schedule_caches():
    with db_lock:
        custom_schedules_table.truncate()
        daily_schedules_table.truncate()
        cache_table.truncate()
        distance_cache_table.truncate()
        geocode_cache_table.truncate()

def purge_poisoned_caches():
    # Remove only poisoned entries to avoid wiping thousands of legitimate caches on startup
    with db_lock:
        distance_cache_table.remove(Query().minutes == 15)
        geocode_cache_table.remove(Query().lat == 0.0)

purge_poisoned_caches()

def get_cached_geocode(address: str):
    with db_lock:
        res = geocode_cache_table.search(Query().address == address.strip().lower())
        if res:
            record = res[0]
            lat = record.get('lat')
            lon = record.get('lon')
            try:
                float(lat)
                float(lon)
                return record
            except (ValueError, TypeError):
                print(f"Deleting corrupt geocode cache entry for: {address} (lat={lat}, lon={lon})")
                geocode_cache_table.remove(Query().address == address.strip().lower())
        return None

def set_cached_geocode(address: str, lat: float, lon: float, display_name: str = ""):
    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        print(f"Error: Refusing to cache invalid coordinates for {address}: lat={lat}, lon={lon}")
        return
        
    with db_lock:
        geocode_cache_table.upsert({
            'address': address.strip().lower(),
            'lat': lat,
            'lon': lon,
            'display_name': display_name
        }, Query().address == address.strip().lower())

def get_cached_travel_time(origin: str, destination: str, max_age_mins: int = 10, ignore_age: bool = False) -> Optional[int]:
    if not origin or not destination:
        return None
    import time
    orig_clean = origin.strip().lower()
    dest_clean = destination.strip().lower()
    with db_lock:
        QueryObj = Query()
        result = distance_cache_table.search((QueryObj.origin == orig_clean) & (QueryObj.destination == dest_clean))
        if result:
            cached_data = result[0]
            timestamp = cached_data.get('timestamp', 0)
            if ignore_age or time.time() - timestamp <= max_age_mins * 60:
                return cached_data['minutes']
        return None

def set_cached_travel_time(origin: str, destination: str, minutes: int):
    if not origin or not destination:
        return
    import time
    orig_clean = origin.strip().lower()
    dest_clean = destination.strip().lower()
    with db_lock:
        QueryObj = Query()
        distance_cache_table.upsert(
            {'origin': orig_clean, 'destination': dest_clean, 'minutes': int(minutes), 'timestamp': time.time()},
            (QueryObj.origin == orig_clean) & (QueryObj.destination == dest_clean)
        )

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
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return drivers_table.insert(driver_data)

def delete_driver(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
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

def add_chat_message(role: str, content: str) -> None:
    import time
    with db_lock:
        chat_history_table.insert({
            'role': role,
            'content': content,
            'timestamp': time.time()
        })

def get_chat_history(limit: int = 100) -> list:
    with db_lock:
        msgs = chat_history_table.all()
        msgs.sort(key=lambda x: x.get('timestamp', 0))
        return msgs[-limit:]

def clear_chat_history() -> None:
    with db_lock:
        chat_history_table.truncate()

def add_passenger(passenger_data: dict) -> int:
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return passengers_table.insert(passenger_data)

def update_passenger(doc_id: int, passenger_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        passengers_table.update(passenger_data, doc_ids=[doc_id])

def delete_passenger(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        passengers_table.remove(doc_ids=[doc_id])

def add_telemetry_event(event_data: dict) -> int:
    with db_lock:
        doc_id = telemetry_table.insert(event_data)
        all_events = telemetry_table.all()
        if len(all_events) > 200:
            all_events.sort(key=lambda x: x.get('timestamp', 0))
            excess = len(all_events) - 200
            doc_ids_to_remove = [e.doc_id for e in all_events[:excess]]
            telemetry_table.remove(doc_ids=doc_ids_to_remove)
        return doc_id

def get_telemetry_events(limit: int = 50) -> List[dict]:
    with db_lock:
        events = telemetry_table.all()
        events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return events[:limit]

def clear_telemetry_events():
    with db_lock:
        telemetry_table.truncate()

# Rule CRUD
def get_all_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            
            # Auto-migrate
            needs_update = False
            if 'keywords' not in doc:
                doc['keywords'] = []
                if doc.get('event_keyword'):
                    doc['keywords'].append(doc['event_keyword'])
                    doc['event_keyword'] = None
                needs_update = True
            
            if 'passenger_ids' not in doc: 
                doc['passenger_ids'] = []
                needs_update = True
            if 'days_of_week' not in doc: 
                doc['days_of_week'] = []
                needs_update = True
            if 'time_start' not in doc: 
                doc['time_start'] = None
                needs_update = True
            if 'time_end' not in doc: 
                doc['time_end'] = None
                needs_update = True
                
            if needs_update:
                rules_table.update(doc, doc_ids=[doc['doc_id']])
                
            rules.append(doc)
        return rules

def _is_duplicate_rule(r1: dict, r2: dict) -> bool:
    import json
    def normalize(v):
        if isinstance(v, dict):
            return {k: normalize(val) for k, val in v.items() if k not in ('id', 'doc_id', 'created_at')}
        elif isinstance(v, list):
            norm_list = [normalize(val) for val in v]
            try:
                return sorted(norm_list)
            except TypeError:
                return sorted(norm_list, key=lambda x: json.dumps(x, sort_keys=True))
        return v
    return normalize(r1) == normalize(r2)

def purge_duplicate_rules():
    with db_lock:
        seen = []
        to_delete = []
        for r in rules_table.all():
            is_dup = False
            for s in seen:
                if _is_duplicate_rule(s, r):
                    is_dup = True
                    break
            if is_dup:
                to_delete.append(r.doc_id)
            else:
                seen.append(r)
        if to_delete:
            rules_table.remove(doc_ids=to_delete)
            
        seen_p = []
        to_delete_p = []
        for p in priority_rules_table.all():
            is_dup = False
            for s in seen_p:
                if _is_duplicate_rule(s, p):
                    is_dup = True
                    break
            if is_dup:
                to_delete_p.append(p.doc_id)
            else:
                seen_p.append(p)
        if to_delete_p:
            priority_rules_table.remove(doc_ids=to_delete_p)

purge_duplicate_rules()

def add_rule(rule_data: dict) -> int:
    with db_lock:
        for existing in rules_table.all():
            if _is_duplicate_rule(existing, rule_data):
                return existing.doc_id
                
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return rules_table.insert(rule_data)

def update_rule(doc_id: int, rule_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        rules_table.update(rule_data, doc_ids=[doc_id])

def delete_rule(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        rules_table.remove(doc_ids=[doc_id])

# Priority Rule CRUD
def get_all_priority_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in priority_rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            
            # Auto-migrate
            needs_update = False
            if 'keywords' not in doc:
                doc['keywords'] = []
                match_type = doc.get('match_type')
                match_value = doc.get('match_value')
                if match_type == 'keyword' and match_value:
                    doc['keywords'].append(match_value)
                needs_update = True
                
            if 'passenger_ids' not in doc:
                doc['passenger_ids'] = []
                match_type = doc.get('match_type')
                match_value = doc.get('match_value')
                if match_type == 'calendar' and match_value:
                    # In legacy, we matched raw calendar ids, but we'll adapt to passenger_ids if it's there
                    pass
                needs_update = True
                
            if 'days_of_week' not in doc: 
                doc['days_of_week'] = []
                needs_update = True
            if 'time_start' not in doc: 
                doc['time_start'] = None
                needs_update = True
            if 'time_end' not in doc: 
                doc['time_end'] = None
                needs_update = True
                
            if needs_update:
                priority_rules_table.update(doc, doc_ids=[doc['doc_id']])
                
            rules.append(doc)
        return rules

def add_priority_rule(rule_data: dict) -> int:
    with db_lock:
        for existing in priority_rules_table.all():
            if _is_duplicate_rule(existing, rule_data):
                return existing.doc_id
                
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return priority_rules_table.insert(rule_data)

def update_priority_rule(doc_id: int, rule_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        priority_rules_table.update(rule_data, doc_ids=[doc_id])

def delete_priority_rule(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        priority_rules_table.remove(doc_ids=[doc_id])

# Errand Rules CRUD
def get_all_errand_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in errand_rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            rules.append(doc)
        return rules

def add_errand_rule(rule_data: dict) -> int:
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return errand_rules_table.insert(rule_data)

def update_errand_rule(doc_id: int, rule_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        errand_rules_table.update(rule_data, doc_ids=[doc_id])

def delete_errand_rule(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        errand_rules_table.remove(doc_ids=[doc_id])

# Themes CRUD
def get_all_themes() -> List[dict]:
    with db_lock:
        themes = []
        for t in themes_table.all():
            doc = dict(t)
            doc['doc_id'] = t.doc_id
            themes.append(doc)
        return themes

def add_theme(theme_data: dict) -> int:
    with db_lock:
        return themes_table.insert(theme_data)

def delete_theme(doc_id: int):
    with db_lock:
        themes_table.remove(doc_ids=[doc_id])

def update_theme(doc_id: int, theme_data: dict):
    with db_lock:
        themes_table.update(theme_data, doc_ids=[doc_id])

# AI Feedback
def get_recent_ai_feedback(limit: int = 20) -> List[dict]:
    with db_lock:
        feedback = ai_feedback_table.all()
        feedback.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return feedback[:limit]

def add_ai_feedback(context: str):
    import time
    with db_lock:
        ai_feedback_table.insert({'timestamp': time.time(), 'context': context})

def invalidate_daily_schedule_cache_for_event(event_id: str):
    with db_lock:
        cache_docs = cache_table.all()
        if not cache_docs:
            mark_all_daily_schedules_dirty()
            custom_schedules_table.truncate()
            return
            
        cache = cache_docs[0]
        events = cache.get("events", [])
        
        target_events = []
        for e in events:
            e_id = e.get("id")
            orig_id = e.get("original_event_id")
            recur_id = e.get("recurring_event_id")
            if (e_id == event_id or 
                (orig_id and orig_id == event_id) or 
                (recur_id and recur_id == event_id)):
                target_events.append(e)
                
        if not target_events:
            mark_all_daily_schedules_dirty()
            custom_schedules_table.truncate()
            return
            
        import datetime
        dates_to_invalidate = set()
        for e in target_events:
            start_str = e.get("start")
            end_str = e.get("end")
            if not start_str:
                continue
            try:
                if len(start_str) >= 10:
                    start_dt = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    end_dt = datetime.datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else start_dt
                    
                    curr = start_dt.date()
                    end_date = end_dt.date()
                    while curr <= end_date:
                        dates_to_invalidate.add(curr.strftime("%Y-%m-%d"))
                        curr += datetime.timedelta(days=1)
            except Exception as ex:
                print(f"Error parsing date strings {start_str} / {end_str}: {ex}")
                dates_to_invalidate.add(start_str[:10])
                
        for date_str in dates_to_invalidate:
            entry = daily_schedules_table.get(Query().date_str == date_str)
            if entry:
                entry['events_hash'] = 'DIRTY'
                daily_schedules_table.update(entry, doc_ids=[entry.doc_id])
            
        custom_schedules_table.truncate()

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
    invalidate_daily_schedule_cache_for_event(override_data['event_id'])
    with db_lock:
        # Overrides are unique per event_id, so remove existing if present
        overrides_table.remove(Query().event_id == override_data['event_id'])
        return overrides_table.insert(override_data)

def delete_override(doc_id: int):
    with db_lock:
        override = overrides_table.get(doc_id=doc_id)
        event_id = override.get('event_id') if override else None
    if event_id:
        invalidate_daily_schedule_cache_for_event(event_id)
    with db_lock:
        overrides_table.remove(doc_ids=[doc_id])

def delete_override_by_event(event_id: str):
    from tinydb import Query
    invalidate_daily_schedule_cache_for_event(event_id)
    with db_lock:
        overrides_table.remove(Query().event_id == event_id)


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

def save_custom_schedule(start_date: str, end_date: str, schedule_data: dict, events_hash: str):
    with db_lock:
        custom_schedules_table.upsert({
            'start_date': start_date,
            'end_date': end_date,
            'schedule': schedule_data,
            'events_hash': events_hash
        }, (Query().start_date == start_date) & (Query().end_date == end_date))

def get_custom_schedule(start_date: str, end_date: str):
    with db_lock:
        res = custom_schedules_table.search((Query().start_date == start_date) & (Query().end_date == end_date))
        if res:
            return res[0]
        return None

def get_all_custom_schedule_keys():
    with db_lock:
        return [{'start_date': doc['start_date'], 'end_date': doc['end_date']} for doc in custom_schedules_table.all()]

def clear_custom_schedules():
    with db_lock:
        custom_schedules_table.truncate()
        daily_schedules_table.truncate()

def get_cached_daily_schedule(date_str: str):
    with db_lock:
        res = daily_schedules_table.search(Query().date_str == date_str)
        if res:
            return res[0]
        return None

def get_all_scheduled_errands() -> dict:
    with db_lock:
        errand_schedules = {}
        for daily in daily_schedules_table.all():
            sched = daily.get('schedule', {})
            for se in sched.get('scheduled_errands', []):
                errand_schedules[se.get('id')] = se.get('start')
        return errand_schedules

def save_cached_daily_schedule(date_str: str, schedule_data: dict, events_hash: str, options: list = None, ai_status: str = 'evaluating', selected_index: int = 0, llm_reasoning: str = ""):
    with db_lock:
        existing = daily_schedules_table.get(Query().date_str == date_str)
        
        # If we are only updating options/ai_status, keep existing options if not provided
        if existing and existing.get('events_hash') == events_hash:
            if options is None:
                options = existing.get('options', [])
            if not llm_reasoning and ai_status == 'evaluating':
                ai_status = existing.get('ai_status', 'evaluating')
                selected_index = existing.get('selected_index', 0)
                llm_reasoning = existing.get('llm_reasoning', '')
                
        daily_schedules_table.upsert({
            'date_str': date_str,
            'schedule': schedule_data,
            'events_hash': events_hash,
            'options': options or [],
            'ai_status': ai_status,
            'selected_index': selected_index,
            'llm_reasoning': llm_reasoning
        }, Query().date_str == date_str)


# Settings CRUD
def get_settings() -> dict:
    with db_lock:
        all_settings = settings_table.all()
        if not all_settings:
            return {"calendar_ids": []}
        return dict(all_settings[0])

def update_settings(settings_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        settings_table.truncate()
        settings_table.insert(settings_data)

# API Usage Tracker
def get_mapbox_usage(month: str, endpoint: str) -> int:
    """Returns the usage count for the given month (YYYY-MM) and endpoint ('directions' or 'geocode')"""
    with db_lock:
        res = api_usage_table.search((Query().month == month) & (Query().endpoint == endpoint))
        if res:
            return res[0].get('count', 0)
        return 0

def increment_mapbox_usage(month: str, endpoint: str, amount: int = 1):
    with db_lock:
        res = api_usage_table.search((Query().month == month) & (Query().endpoint == endpoint))
        if res:
            new_count = res[0].get('count', 0) + amount
            api_usage_table.update({'count': new_count}, (Query().month == month) & (Query().endpoint == endpoint))
        else:
            api_usage_table.insert({'month': month, 'endpoint': endpoint, 'count': amount})

def log_api_request(endpoint: str, count: int = 1):
    import time
    with db_lock:
        api_requests_log_table.insert({
            'timestamp': time.time(),
            'endpoint': endpoint,
            'count': count
        })
        three_days_ago = time.time() - (3 * 24 * 3600)
        api_requests_log_table.remove(Query().timestamp < three_days_ago)

def get_rolling_usage(endpoint: str, seconds: int) -> int:
    import time
    with db_lock:
        now = time.time()
        start_time = now - seconds
        q = Query()
        records = api_requests_log_table.search((q.endpoint == endpoint) & (q.timestamp >= start_time))
        return sum(r.get('count', 0) for r in records)

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
        q = Query()
        drive_status_table.upsert({'leg_id': leg_id, 'status': status}, q.leg_id == leg_id)

# --- Pending Notifications ---
def save_pending_notifications(notifications: List[dict]):
    with db_lock:
        pending_notifications_table.truncate()
        if notifications:
            pending_notifications_table.insert_multiple(notifications)

def get_pending_notifications() -> List[dict]:
    with db_lock:
        return pending_notifications_table.all()

def mark_notification_fired(notif_id: str):
    with db_lock:
        q = Query()
        pending_notifications_table.update({'fired': True}, q.notif_id == notif_id)

def get_event_config(google_id: str) -> Optional[dict]:
    with db_lock:
        q = Query()
        res = event_configs_table.search(q.google_id == google_id)
        if res:
            return res[0]
        return None

def set_event_config(google_id: str, config_data: dict):
    invalidate_daily_schedule_cache_for_event(google_id)
    with db_lock:
        q = Query()
        config_data['google_id'] = google_id
        event_configs_table.upsert(config_data, q.google_id == google_id)

def delete_event_config(google_id: str):
    invalidate_daily_schedule_cache_for_event(google_id)
    with db_lock:
        q = Query()
        event_configs_table.remove(q.google_id == google_id)

def get_completed_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'completed')]

# --- Errands ---
def get_all_errands() -> List[dict]:
    with db_lock:
        errands = []
        for e in errands_table.all():
            doc = dict(e)
            doc['doc_id'] = e.doc_id
            errands.append(doc)
        return errands

def add_errand(errand_data: dict) -> int:
    with db_lock:
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        custom_schedules_table.truncate()
        return errands_table.insert(errand_data)

def update_errand(doc_id: int, errand_data: dict):
    with db_lock:
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        custom_schedules_table.truncate()
        errands_table.update(errand_data, doc_ids=[doc_id])

def delete_errand(doc_id: int):
    with db_lock:
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        custom_schedules_table.truncate()
        errands_table.remove(doc_ids=[doc_id])

