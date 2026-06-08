from tinydb import TinyDB, Query
from typing import List, Optional
import os

if os.path.exists('/data/options.json'):
    DB_PATH = '/data/chauffeur_db.json'
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db.json')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

db = TinyDB(DB_PATH)
drivers_table = db.table('drivers')
rules_table = db.table('rules')
priority_rules_table = db.table('priority_rules')
overrides_table = db.table('overrides')
cache_table = db.table('schedule_cache')
settings_table = db.table('settings')
distance_cache_table = db.table('distance_cache')

def get_cached_travel_time(origin: str, destination: str) -> Optional[int]:
    QueryObj = Query()
    result = distance_cache_table.search((QueryObj.origin == origin) & (QueryObj.destination == destination))
    if result:
        return result[0]['minutes']
    return None

def set_cached_travel_time(origin: str, destination: str, minutes: int):
    # Overwrite if exists
    QueryObj = Query()
    distance_cache_table.remove((QueryObj.origin == origin) & (QueryObj.destination == destination))
    distance_cache_table.insert({'origin': origin, 'destination': destination, 'minutes': minutes})

# Driver CRUD
def get_all_drivers() -> List[dict]:
    # Include doc_id in the returned dictionary for frontend deletion
    drivers = []
    for d in drivers_table.all():
        doc = dict(d)
        doc['doc_id'] = d.doc_id
        drivers.append(doc)
    return drivers

def add_driver(driver_data: dict) -> int:
    return drivers_table.insert(driver_data)

def delete_driver(doc_id: int):
    drivers_table.remove(doc_ids=[doc_id])

# Rule CRUD
def get_all_rules() -> List[dict]:
    rules = []
    for r in rules_table.all():
        doc = dict(r)
        doc['doc_id'] = r.doc_id
        rules.append(doc)
    return rules

def add_rule(rule_data: dict) -> int:
    return rules_table.insert(rule_data)

def update_rule(doc_id: int, rule_data: dict):
    rules_table.update(rule_data, doc_ids=[doc_id])

def delete_rule(doc_id: int):
    rules_table.remove(doc_ids=[doc_id])

# Priority Rule CRUD
def get_all_priority_rules() -> List[dict]:
    rules = []
    for r in priority_rules_table.all():
        doc = dict(r)
        doc['doc_id'] = r.doc_id
        rules.append(doc)
    return rules

def add_priority_rule(rule_data: dict) -> int:
    return priority_rules_table.insert(rule_data)

def update_priority_rule(doc_id: int, rule_data: dict):
    priority_rules_table.update(rule_data, doc_ids=[doc_id])

def delete_priority_rule(doc_id: int):
    priority_rules_table.remove(doc_ids=[doc_id])

# Overrides CRUD
def get_all_overrides() -> List[dict]:
    overrides = []
    for r in overrides_table.all():
        doc = dict(r)
        doc['doc_id'] = r.doc_id
        overrides.append(doc)
    return overrides

def add_override(override_data: dict) -> int:
    # Overrides are unique per event_id, so remove existing if present
    overrides_table.remove(Query().event_id == override_data['event_id'])
    return overrides_table.insert(override_data)

def delete_override(doc_id: int):
    overrides_table.remove(doc_ids=[doc_id])

def get_cached_schedule() -> dict:
    cache = cache_table.all()
    if cache:
        return cache[0]
    return {}

def set_cached_schedule(schedule_data: dict):
    cache_table.truncate()
    cache_table.insert(schedule_data)

# Settings CRUD
def get_settings() -> dict:
    all_settings = settings_table.all()
    if not all_settings:
        return {"calendar_ids": []}
    return dict(all_settings[0])

def update_settings(settings_data: dict):
    settings_table.truncate()
    settings_table.insert(settings_data)
