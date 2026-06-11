import re

with open('chauffeur/services/storage.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_functions = """
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

"""

cache_funcs = """def set_cached_schedule(schedule_data: dict):
    with db_lock:
        cache_table.truncate()
        cache_table.insert(schedule_data)
"""
if cache_funcs in content and "def save_custom_schedule" not in content:
    content = content.replace(cache_funcs, cache_funcs + new_functions)
    with open('chauffeur/services/storage.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("Updated storage.py!")
else:
    print("Could not find cache_funcs or already patched")
