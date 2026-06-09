import os
from typing import Optional

import requests
from services import storage

def get_travel_time_minutes(origin: Optional[str], destination: Optional[str]) -> int:
    """
    Returns the travel time between two locations in minutes.
    In Phase 2, this is a mock. In Phase 3, this will call Google Maps API.
    """
    if not origin or not destination:
        return 0
    if origin.lower() == destination.lower():
        return 0
    
    # MOCK fallback implementation
    MOCK_TIME = 15
    
    # 1. Check cache first
    cached = storage.get_cached_travel_time(origin.lower(), destination.lower())
    if cached is not None:
        return cached
        
    # 2. If not cached, try calling Google Maps API
    api_key = get_api_key()
    if api_key:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origin,
            "destinations": destination,
            "key": api_key,
            "units": "imperial"
        }
        try:
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            if data.get("status") == "OK":
                elements = data.get("rows", [{}])[0].get("elements", [{}])
                element = elements[0]
                if element.get("status") == "OK":
                    duration_seconds = element.get("duration", {}).get("value", MOCK_TIME * 60)
                    minutes = max(1, duration_seconds // 60)
                    storage.set_cached_travel_time(origin.lower(), destination.lower(), minutes)
                    return minutes
        except Exception as ex:
            print(f"Distance Matrix API error: {ex}")
            
    # 3. Cache and return fallback if API fails or no key
    storage.set_cached_travel_time(origin.lower(), destination.lower(), MOCK_TIME)
    return MOCK_TIME

def get_api_key() -> Optional[str]:
    api_key = None
    
    # 1. Try to load from Home Assistant Add-on options
    import os
    import json
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            api_key = options.get('google_maps_api_key')
        except Exception:
            pass

    # 2. Try to load from environment variable
    if not api_key:
        api_key = os.environ.get('GOOGLE_MAPS_API_KEY')

    # 3. Try to load from local file
    if not api_key:
        api_key_file = os.path.join(os.path.dirname(__file__), '..', 'maps_api_key.txt')
        if os.path.exists(api_key_file):
            with open(api_key_file, 'r') as f:
                api_key = f.read().strip()
                
    return api_key

def get_home_location() -> Optional[str]:
    from services import storage
    home_loc = None
    
    # 1. Try local app settings
    settings = storage.get_settings()
    if settings.get('home_location'):
        home_loc = settings.get('home_location')
        
    # 2. Try HA options.json
    if not home_loc:
        import os
        import json
        options_file = '/data/options.json'
        if os.path.exists(options_file):
            try:
                with open(options_file, 'r') as f:
                    options = json.load(f)
                home_loc = options.get('home_location')
            except Exception:
                pass

    # 3. Try Environment Variable
    if not home_loc:
        home_loc = os.environ.get('HOME_LOCATION')
        
    return home_loc if home_loc and str(home_loc).strip() != "" else None

def autocomplete_location(input_text: str) -> list[dict]:
    """
    Calls the Google Maps Places Autocomplete API.
    Returns a list of dicts: {"description": "123 Main St..."}
    """
    api_key = get_api_key()
    
    if not api_key:
        return []
        
    url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
    params = {
        "input": input_text,
        "key": api_key,
        "types": "geocode|establishment" # standard places
    }
    
    try:
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        if data.get("status") == "OK":
            return [{"description": p["description"]} for p in data.get("predictions", [])]
        return []
    except Exception as ex:
        print(f"Places API error: {ex}")
        return []
