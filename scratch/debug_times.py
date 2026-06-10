import sys
import os
sys.path.append('e:/repositories/Chauffeur/chauffeur')
from services import maps
from datetime import datetime
from services import storage
import json

data = storage.get_cached_schedule()
if data:
    events = data.get('events', [])
    e1 = next((e for e in events if "Shooting Mastery" in e.get('title', '')), None)
    e2 = next((e for e in events if "Warriors" in e.get('title', '')), None)
    if e1 and e2:
        print("Shooting Mastery:", e1.get('location'))
        print("Warriors:", e2.get('location'))
        loc1 = e1.get('location')
        loc2 = e2.get('location')
        print("Time from Home to Warriors:", maps.get_travel_time_minutes(data.get('home_location'), loc2))
        print("Time from Shooting Mastery to Warriors:", maps.get_travel_time_minutes(loc1, loc2))
    else:
        print("Events not found")
