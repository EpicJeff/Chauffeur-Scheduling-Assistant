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
    
    # MOCK implementation: 15 minutes travel time between any two different locations
    return 15

def autocomplete_location(input_text: str) -> list[dict]:
    """
    Calls the Google Maps Places Autocomplete API.
    Returns a list of dicts: {"description": "123 Main St..."}
    """
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
