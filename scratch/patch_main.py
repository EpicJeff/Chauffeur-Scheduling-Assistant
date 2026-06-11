import re

with open('chauffeur/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the memory cache logic from get_schedule
old_get_schedule = '''@app.get("/api/schedule")
def get_schedule(start_date: str = None, end_date: str = None):
    try:
        completed = storage.get_completed_drives()
        
        # check cache first if no custom dates
        if not start_date and not end_date:
            cached = storage.get_cached_schedule()
            if cached:
                cached["completed_drives"] = completed
                return cached
                
        # Check memory cache for custom dates
        if start_date and end_date:
            cache_key = f"{start_date}_{end_date}"
            if cache_key in custom_schedule_cache:
                entry = custom_schedule_cache[cache_key]
                # 5 minute expiration (same as background sync)
                import datetime
                if datetime.datetime.now().timestamp() - entry['time'] < 300:
                    data = entry['data']
                    data["completed_drives"] = completed
                    return data

        # otherwise fetch fresh
        try:
            res = refresh_schedule_logic(start_date, end_date)
            if start_date and end_date and "error" not in res:
                import datetime
                custom_schedule_cache[f"{start_date}_{end_date}"] = {
                    'time': datetime.datetime.now().timestamp(),
                    'data': res
                }
            res["completed_drives"] = completed
            return res
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc(), "error_debug": str(e)}
    except Exception as e:
        return {"error": str(e)}'''

new_get_schedule = '''@app.get("/api/schedule")
def get_schedule(start_date: str = None, end_date: str = None, force_refresh: bool = False):
    try:
        completed = storage.get_completed_drives()
        
        # check default cache if no custom dates
        if not start_date and not end_date and not force_refresh:
            cached = storage.get_cached_schedule()
            if cached:
                cached["completed_drives"] = completed
                return cached

        # Fetch using lazy solving logic
        try:
            res = refresh_schedule_logic(start_date, end_date, force_refresh=force_refresh)
            if "error" not in res:
                res["completed_drives"] = completed
            return res
        except Exception as e:
            import traceback
            return {"error": str(e), "traceback": traceback.format_exc(), "error_debug": str(e)}
    except Exception as e:
        return {"error": str(e)}'''

if old_get_schedule in content:
    content = content.replace(old_get_schedule, new_get_schedule)
else:
    print("WARNING: Could not find old get_schedule")

# Now update refresh_schedule_logic to hash events and check TinyDB cache
old_def = "def refresh_schedule_logic(start_date_str=None, end_date_str=None):"
new_def = """import hashlib

def hash_events(events_list):
    sorted_events = sorted(events_list, key=lambda e: getattr(e, 'id', ''))
    parts = []
    for e in sorted_events:
        parts.append(f"{getattr(e, 'id', '')}|{getattr(e, 'start', '')}|{getattr(e, 'end', '')}|{getattr(e, 'location', '')}|{getattr(e, 'title', '')}")
    return hashlib.sha256("||".join(parts).encode('utf-8')).hexdigest()

def refresh_schedule_logic(start_date_str=None, end_date_str=None, force_refresh=False):"""

content = content.replace(old_def, new_def)

# Find where events are fetched
old_fetch = """    try:
        all_fetched_events = calendar.fetch_upcoming_events(all_cals_to_fetch, days=days_to_show, start_date_str=start_date_str, end_date_str=end_date_str)
    except Exception as e:
        return {"error": f"Failed to fetch events: {str(e)}"}"""

new_fetch = """    try:
        all_fetched_events = calendar.fetch_upcoming_events(all_cals_to_fetch, days=days_to_show, start_date_str=start_date_str, end_date_str=end_date_str)
    except Exception as e:
        return {"error": f"Failed to fetch events: {str(e)}"}
        
    # Lazy Solving Check
    current_events_hash = hash_events(all_fetched_events)
    if start_date_str and end_date_str and not force_refresh:
        cached_custom = storage.get_custom_schedule(start_date_str, end_date_str)
        if cached_custom and cached_custom.get('events_hash') == current_events_hash:
            return cached_custom['schedule']
"""
content = content.replace(old_fetch, new_fetch)

# Now find where it returns the payload
old_return = """        # Only cache the default "next 7 days" view. Custom dates aren't cached to disk.
        if not start_date_str and not end_date_str:
            storage.save_cache(payload)
            
        return payload"""

new_return = """        # Cache the default "next 7 days" view
        if not start_date_str and not end_date_str:
            storage.save_cache(payload)
        else:
            # Save custom schedule to TinyDB persistently
            storage.save_custom_schedule(start_date_str, end_date_str, payload, current_events_hash)
            
        return payload"""

content = content.replace(old_return, new_return)

with open('chauffeur/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Updated main.py!")
