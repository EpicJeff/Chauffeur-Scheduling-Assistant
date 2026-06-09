import os
from typing import Optional

import requests
from services import storage

def get_cache_duration() -> int:
    import json
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            if 'route_cache_duration_mins' in options:
                return int(options.get('route_cache_duration_mins', 10))
        except Exception:
            pass
            
    # Fallback to local settings
    settings = storage.get_settings()
    return int(settings.get('route_cache_duration_mins', 10))


def get_travel_time_minutes(origin: Optional[str], destination: Optional[str], departure_time: Optional[int] = None, return_traffic: bool = False):
    """
    Returns the travel time between two locations in minutes.
    If return_traffic is True, returns (minutes, delay_mins).
    """
    if not origin or not destination:
        return (0, 0) if return_traffic else 0
    if origin.lower() == destination.lower():
        return (0, 0) if return_traffic else 0
    
    # MOCK fallback implementation
    MOCK_TIME = 15
    
    cache_duration = get_cache_duration()
    
    # 1. Check cache first
    cached = storage.get_cached_travel_time(origin.lower(), destination.lower(), max_age_mins=cache_duration)
    if cached is not None:
        return (cached, 0) if return_traffic else cached
        
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
        
        if departure_time is not None:
            params["departure_time"] = departure_time
        else:
            params["departure_time"] = "now"
            
        try:
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            if data.get("status") == "OK":
                elements = data.get("rows", [{}])[0].get("elements", [{}])
                element = elements[0]
                if element.get("status") == "OK":
                    duration_seconds = element.get("duration", {}).get("value", MOCK_TIME * 60)
                    minutes = max(1, duration_seconds // 60)
                    
                    delay_mins = 0
                    if "duration_in_traffic" in element:
                        traffic_seconds = element["duration_in_traffic"].get("value", duration_seconds)
                        traffic_mins = max(1, traffic_seconds // 60)
                        delay_mins = max(0, traffic_mins - minutes)
                        minutes = traffic_mins # Use traffic time as the actual travel time
                        
                    storage.set_cached_travel_time(origin.lower(), destination.lower(), minutes)
                    return (minutes, delay_mins) if return_traffic else minutes
        except Exception as ex:
            print(f"Distance Matrix API error: {ex}")
            
    # 3. Cache and return fallback if API fails or no key
    storage.set_cached_travel_time(origin.lower(), destination.lower(), MOCK_TIME)
    return (MOCK_TIME, 0) if return_traffic else MOCK_TIME

def get_route_polyline(origin: str, destination: str) -> Optional[str]:
    """
    Returns the encoded polyline string for the route between origin and destination.
    """
    if not origin or not destination:
        return None
    if origin.lower() == destination.lower():
        return None
        
    cache_duration = get_cache_duration()
    
    # 1. Check cache
    cached = storage.get_cached_polyline(origin.lower(), destination.lower(), max_age_mins=cache_duration)
    if cached is not None:
        return cached
        
    # 2. Call Google Directions API
    api_key = get_api_key()
    if api_key:
        url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": origin,
            "destination": destination,
            "key": api_key,
            "mode": "driving"
        }
        
        try:
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            if data.get("status") == "OK":
                routes = data.get("routes", [])
                if routes:
                    polyline = routes[0].get("overview_polyline", {}).get("points")
                    if polyline:
                        storage.set_cached_polyline(origin.lower(), destination.lower(), polyline)
                        return polyline
                else:
                    print(f"Directions API: No routes found for {origin} -> {destination}")
            else:
                print(f"Directions API failed: status={data.get('status')}, error={data.get('error_message')}")
        except Exception as ex:
            print(f"Directions API exception for polyline: {ex}")
            
    return None

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

def get_google_maps_url(locations: list[str]) -> str:
    import urllib.parse
    if not locations:
        return ""
    if len(locations) == 1:
        return f"https://www.google.com/maps/dir/?api=1&destination={urllib.parse.quote(locations[0])}"
    
    origin = urllib.parse.quote(locations[0])
    destination = urllib.parse.quote(locations[-1])
    waypoints = "|".join([urllib.parse.quote(loc) for loc in locations[1:-1]])
    
    url = f"https://www.google.com/maps/dir/?api=1&origin={origin}&destination={destination}"
    if waypoints:
        url += f"&waypoints={waypoints}"
    return url

def get_apple_maps_url(locations: list[str]) -> str:
    import urllib.parse
    if not locations:
        return ""
    if len(locations) == 1:
        return f"http://maps.apple.com/?daddr={urllib.parse.quote(locations[0])}"
    
    # Apple Maps doesn't support waypoints via URL scheme in the same way, 
    # but we can set start (saddr) and destination (daddr). 
    # For a multi-stop route on Apple Maps, we unfortunately just pass the origin and final destination.
    origin = urllib.parse.quote(locations[0])
    destination = urllib.parse.quote(locations[-1])
    return f"http://maps.apple.com/?saddr={origin}&daddr={destination}"
