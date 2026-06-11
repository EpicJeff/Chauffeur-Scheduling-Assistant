import re

with open('chauffeur/services/storage.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Add the new table definition
table_str = "cache_table = db.table('schedule_cache')\n    custom_schedules_table = db.table('custom_schedules')"
content = content.replace("cache_table = db.table('schedule_cache')", table_str)

# Add the new functions
new_functions = """
def save_custom_schedule(start_date: str, end_date: str, schedule_data: dict, events_hash: str):
    with db_lock:
        custom_schedules_table.upsert({
            'start_date': start_date,
            'end_date': end_date,
            'schedule': schedule_data,
            'events_hash': events_hash
        }, (Query().start_date == start_date) & (Query().end_date == end_date))

def get_custom_schedule(start_date: str, end_date: str) -> Optional[dict]:
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

"""

# Append at the end of schedule cache section
cache_funcs = """def save_cache(schedule_data: dict):
    with db_lock:
        cache_table.truncate()
        cache_table.insert(schedule_data)
"""
content = content.replace(cache_funcs, cache_funcs + new_functions)

# Wait, if `update_settings` is called, it should clear custom schedules
clear_hooks = [
    "def update_settings(settings_data: dict):\n    with db_lock:",
    "def update_rule(doc_id: int, rule_data: dict):\n    with db_lock:",
    "def update_priority_rule(doc_id: int, rule_data: dict):\n    with db_lock:",
    "def update_passenger(doc_id: int, passenger_data: dict):\n    with db_lock:",
    "def update_driver(doc_id: int, driver_data: dict):\n    with db_lock:",
    "def add_override(override_data: dict) -> int:\n    with db_lock:",
    "def delete_override(doc_id: int):\n    with db_lock:",
]

for hook in clear_hooks:
    if hook in content:
        content = content.replace(hook, hook + "\n        custom_schedules_table.truncate()")

with open('chauffeur/services/storage.py', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated storage.py!")
