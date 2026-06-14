import os
from typing import Optional

import requests
import threading
from services import storage

geocode_lock = threading.Lock()

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
    if not origin or not destination:
        return (0, 0) if return_traffic else 0
    if origin.lower() == destination.lower():
        return (0, 0) if return_traffic else 0
    
    MOCK_TIME = 15
    cache_duration = get_cache_duration()
    
    # 1. Check cache first
    cached = storage.get_cached_travel_time(origin.lower(), destination.lower(), max_age_mins=cache_duration, ignore_age=not return_traffic)
    if cached is not None:
        return (cached, 0) if return_traffic else cached
        
    # 2. Call get_route_info to guarantee identical times for the scheduler and the map displays
    info = get_route_info(origin, destination, ignore_age=not return_traffic)
    if info and "duration" in info:
        import re
        dur_str = info["duration"]
        sec = int(re.sub(r'\D', '', dur_str)) if dur_str else (MOCK_TIME * 60)
        minutes = max(1, sec // 60)
        
        delay_mins = 0
        if info.get("staticDuration"):
            static_sec = int(re.sub(r'\D', '', info["staticDuration"]))
            static_mins = max(1, static_sec // 60)
            delay_mins = max(0, minutes - static_mins)
            
        storage.set_cached_travel_time(origin.lower(), destination.lower(), minutes)
        return (minutes, delay_mins) if return_traffic else minutes
        
    return (MOCK_TIME, 0) if return_traffic else MOCK_TIME
            
    # 3. Cache and return fallback if API fails
    storage.set_cached_travel_time(origin.lower(), destination.lower(), MOCK_TIME)
    return (MOCK_TIME, 0) if return_traffic else MOCK_TIME

def get_route_info(origin: str, destination: str, ignore_age: bool = False) -> Optional[dict]:
    """
    Returns a dictionary with the encoded polyline string, distance, and duration for the route.
    """
    if not origin or not destination:
        return None
    if origin.lower() == destination.lower():
        return None
        
    cache_duration = get_cache_duration()
    
    # 1. Check cache
    cached = storage.get_cached_route_info(origin.lower(), destination.lower(), max_age_mins=cache_duration, ignore_age=ignore_age)
    if cached is not None:
        return cached
        
    # 2. Geocode origin and destination
    orig_coords = geocode_address(origin)
    dest_coords = geocode_address(destination)
    
    if not orig_coords or not dest_coords:
        print(f"Could not geocode {origin} or {destination}")
        return None
        
    orig_lat, orig_lon = orig_coords
    dest_lat, dest_lon = dest_coords
    
    # 3. Call OSRM API
    # Format: lon,lat;lon,lat
    url = f"http://router.project-osrm.org/route/v1/driving/{orig_lon},{orig_lat};{dest_lon},{dest_lat}"
    params = {
        "overview": "full",
        "steps": "false",
        "annotations": "false"
    }
    
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get("routes", [])
            if routes:
                route = routes[0]
                polyline = route.get("geometry")
                duration_sec = route.get("duration", 0)
                distance_m = route.get("distance", 0)
                
                if polyline:
                    info = {
                        "polyline": polyline,
                        "distanceMeters": distance_m,
                        "duration": f"{int(duration_sec)}s",
                        "staticDuration": f"{int(duration_sec)}s"
                    }
                    storage.set_cached_route_info(origin.lower(), destination.lower(), info)
                    return info
            else:
                print(f"OSRM API: No routes found for {origin} -> {destination}")
        else:
            print(f"OSRM API failed: status={resp.status_code}, body={resp.text}")
    except Exception as ex:
        print(f"OSRM API exception for route info: {ex}")
            
    return None

# Deleted get_api_key

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

def geocode_address(address: str) -> Optional[tuple[float, float]]:
    if not address or not address.strip():
        return None
        
    cached = storage.get_cached_geocode(address)
    if cached:
        return cached.get('lat'), cached.get('lon')
        
    with geocode_lock:
        # Check cache again inside the lock in case another thread just fetched it
        cached = storage.get_cached_geocode(address)
        if cached:
            return cached.get('lat'), cached.get('lon')
            
        # Rate limit: Nominatim requires max 1 request per second
        import time
        time.sleep(1.1)
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 1
        }
        headers = {
            "User-Agent": "ChauffeurScheduleAssistant/1.0"
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    display_name = data[0].get("display_name", "")
                    storage.set_cached_geocode(address, lat, lon, display_name)
                    return lat, lon
            print(f"Geocoding failed for {address}: {resp.status_code} {resp.text}")
        except Exception as ex:
            print(f"Geocoding error for {address}: {ex}")
            
    return None

def autocomplete_location(input_text: str) -> list[dict]:
    """
    Calls the Photon API (based on OpenStreetMap) for autocomplete.
    Returns a list of dicts: {"description": "123 Main St..."}
    """
    if not input_text or len(input_text) < 3:
        return []
        
    url = "https://photon.komoot.io/api/"
    params = {
        "q": input_text,
        "limit": 5
    }
    headers = {
        "User-Agent": "ChauffeurScheduleAssistant/1.0"
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            results = []
            for feature in data.get("features", []):
                p = feature.get("properties", {})
                
                parts = []
                if p.get("name"): parts.append(p.get("name"))
                elif p.get("street"):
                    s = p.get("street")
                    if p.get("housenumber"):
                        s = f"{p.get('housenumber')} {s}"
                    parts.append(s)
                    
                if p.get("city"): parts.append(p.get("city"))
                if p.get("state"): parts.append(p.get("state"))
                
                if parts:
                    results.append({"description": ", ".join(parts)})
            return results
        return []
    except Exception as ex:
        print(f"Photon autocomplete error: {ex}")
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
