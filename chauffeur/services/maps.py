import os
from typing import Optional

import requests
import threading
from services import storage

geocode_lock = threading.Lock()
api_rate_lock = threading.Lock()
mapbox_geocode_lock = threading.Lock()
mapbox_routing_lock = threading.Lock()

def get_map_option(key: str, default: any) -> any:
    settings = storage.get_settings()
    if key in settings and settings[key] is not None:
        return settings[key]
        
    import json
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            if key in options:
                val = options[key]
                if val is not None:
                    return val
        except Exception:
            pass
    return default

def fire_home_assistant_alert(endpoint: str, reason: str, current_usage: int):
    import os
    import requests
    supervisor_token = os.environ.get('SUPERVISOR_TOKEN')
    if not supervisor_token:
        print(f"HA API Alert would fire: {reason} for Mapbox {endpoint} (usage={current_usage})")
        return
        
    url = "http://supervisor/core/api/events/chauffeur_api_alert"
    headers = {
        "Authorization": f"Bearer {supervisor_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "endpoint": endpoint,
        "reason": reason,
        "current_usage": current_usage,
        "message": f"CRITICAL: Chauffeur detected a rapid increase in Mapbox {endpoint} usage: {reason}. Current usage is {current_usage}."
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=5)
        if resp.status_code not in (200, 201):
            print(f"Failed to fire HA event: {resp.status_code} {resp.text}")
        else:
            print(f"Successfully fired HA event chauffeur_api_alert: {reason}")
    except Exception as e:
        print(f"Exception firing HA event: {e}")

def check_usage_limits_and_spikes(endpoint: str, increment: int = 1, check_only: bool = False) -> bool:
    import datetime
    current_month = datetime.datetime.now().strftime("%Y-%m")
    
    # Handle searchbox endpoint mapping
    usage_key = 'searchbox_sessions' if endpoint == 'searchbox' else endpoint
    
    # 1. Fetch current monthly usage count
    monthly_usage = storage.get_mapbox_usage(current_month, usage_key)
    
    # 2. Get limit setting
    if endpoint == 'searchbox':
        default_limit = 500
    elif endpoint == 'category':
        default_limit = 45000
    else:
        default_limit = 90000
    limit = get_map_option(f'mapbox_{endpoint}_limit', default_limit)
    
    # Check if monthly limit is already reached
    if monthly_usage >= limit:
        return False
        
    if check_only:
        return True
        
    # Check if a spike has occurred (rapid increase in the last 1 hour)
    if endpoint == 'matrix':
        spike_threshold = 5000
    elif endpoint in ('searchbox', 'category'):
        spike_threshold = 100
    else:
        spike_threshold = 500
        
    hourly_usage = storage.get_rolling_usage(usage_key, 3600)
    
    # If adding this would trigger a spike alert
    if hourly_usage + increment >= spike_threshold and hourly_usage < spike_threshold:
        reason = f"Usage in the last hour exceeded {spike_threshold} units (current rolling hourly usage is {hourly_usage + increment})"
        fire_home_assistant_alert(endpoint, reason, monthly_usage + increment)
        
    # Also log request and increment usage
    storage.increment_mapbox_usage(current_month, usage_key, increment)
    storage.log_api_request(usage_key, increment)
    return True

def get_cache_duration() -> int:
    settings = storage.get_settings()
    if 'route_cache_duration_mins' in settings and settings['route_cache_duration_mins'] is not None:
        return int(settings['route_cache_duration_mins'])
        
    import json
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            if 'route_cache_duration_mins' in options:
                return int(options.get('route_cache_duration_mins', 1440))
        except Exception:
            pass
            
    return 1440


def get_travel_time_minutes(origin: Optional[str], destination: Optional[str], departure_time: Optional[int] = None, return_traffic: bool = False):
    if not origin or not destination:
        return (0, 0) if return_traffic else 0
    if origin.lower() == destination.lower():
        return (0, 0) if return_traffic else 0
        
    # Check if they geocode to the same coordinates (e.g. same building, different gym/room)
    coords_origin = geocode_address(origin)
    coords_dest = geocode_address(destination)
    min_time_mins = 0
    if coords_origin and coords_dest:
        if coords_origin == coords_dest:
            return (0, 0) if return_traffic else 0
        import math
        lat1, lon1 = coords_origin
        lat2, lon2 = coords_dest
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        dist_km = R * c
        # Assume max speed of 120 km/h (2 km/min) -> min time = dist_km / 2
        min_time_mins = int(dist_km / 2.0)
    
    MOCK_TIME = 15
    cache_duration = get_cache_duration()
    
    # 1. Check cache first
    cached = storage.get_cached_travel_time(origin.lower(), destination.lower(), max_age_mins=cache_duration, ignore_age=not return_traffic)
    if cached is not None:
        return (max(cached, min_time_mins), 0) if return_traffic else max(cached, min_time_mins)
        
    # 2. If not in cache, fallback to priming the cache for just this pair
    prime_matrix_cache([origin, destination])
    
    # 3. Check cache again
    cached = storage.get_cached_travel_time(origin.lower(), destination.lower(), max_age_mins=cache_duration, ignore_age=not return_traffic)
    if cached is not None:
        return (max(cached, min_time_mins), 0) if return_traffic else max(cached, min_time_mins)
        
    # 4. Return fallback if API fails (do not cache so it retries later)
    fallback = max(MOCK_TIME, min_time_mins)
    return (fallback, 0) if return_traffic else fallback

def prime_matrix_cache(locations: list[str]):
    from services import storage
    if not locations:
        return
        
    unique_locs = list(set([loc for loc in locations if loc and loc.strip()]))
    if len(unique_locs) < 2:
        return
        
    cache_duration = get_cache_duration()
    from itertools import combinations
    missing_locs = set()
    for l1, l2 in combinations(unique_locs, 2):
        c1 = storage.get_cached_travel_time(l1.lower(), l2.lower(), max_age_mins=cache_duration, ignore_age=False)
        c2 = storage.get_cached_travel_time(l2.lower(), l1.lower(), max_age_mins=cache_duration, ignore_age=False)
        if c1 is None or c2 is None:
            missing_locs.add(l1)
            missing_locs.add(l2)
            
    unique_locs = list(missing_locs)
    if len(unique_locs) < 2:
        return

    import concurrent.futures
    # Geocode all locations in parallel
    coords = []
    loc_names = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_loc = {executor.submit(geocode_address, loc): loc for loc in unique_locs}
        for future in concurrent.futures.as_completed(future_to_loc):
            loc = future_to_loc[future]
            try:
                c = future.result()
                if c:
                    coords.append(c)
                    loc_names.append(loc)
            except Exception as e:
                print(f"Error parallel geocoding {loc}: {e}")
            
    if len(coords) < 2:
        return
        
    import datetime
    import time
    mapbox_key = get_mapbox_api_key()
    settings = storage.get_settings()
    disable_mapbox = settings.get('disable_mapbox', False)
    current_month = datetime.datetime.now().strftime("%Y-%m")
    
    def fetch_matrix_chunk(src_indices, dest_indices, all_coords, all_locs):
        chunk_indices = list(set(src_indices + dest_indices))
        if len(chunk_indices) < 2:
            return
            
        coord_strings = []
        for idx in chunk_indices:
            try:
                lat, lon = all_coords[idx]
                lat_f = float(lat)
                lon_f = float(lon)
                coord_strings.append(f"{lon_f},{lat_f}")
            except (ValueError, TypeError, IndexError) as ex:
                print(f"Warning: Skipping invalid coordinate at index {idx}: {all_coords[idx] if idx < len(all_coords) else 'out of bounds'}, error: {ex}")
                continue
            
        if len(coord_strings) < 2:
            return
            
        coord_str = ";".join(coord_strings)
        
        local_src = []
        local_dest = []
        for i in src_indices:
            try:
                local_src.append(chunk_indices.index(i))
            except ValueError:
                pass
        for i in dest_indices:
            try:
                local_dest.append(chunk_indices.index(i))
            except ValueError:
                pass
                
        if not local_src or not local_dest:
            return
        
        src_str = ";".join(map(str, local_src))
        dest_str = ";".join(map(str, local_dest))
        
        disable_matrix = get_map_option('disable_mapbox_matrix', False)
        disable_directions = get_map_option('disable_mapbox_directions', False)
        elements = len(src_indices) * len(dest_indices)
        
        # --- TIER 1: Mapbox Matrix API ---
        if mapbox_key and not disable_mapbox and not disable_matrix and check_usage_limits_and_spikes('matrix', elements):
            url = f"https://api.mapbox.com/directions-matrix/v1/mapbox/driving/{coord_str}"
            params = {
                "access_token": mapbox_key,
                "sources": src_str,
                "destinations": dest_str,
                "annotations": "duration,distance"
            }
            try:
                with mapbox_routing_lock:
                    import time
                    if not hasattr(fetch_matrix_chunk, "last_matrix_time"):
                        fetch_matrix_chunk.last_matrix_time = 0
                    now = time.time()
                    elapsed = now - fetch_matrix_chunk.last_matrix_time
                    if elapsed < 0.25:
                        time.sleep(0.25 - elapsed)
                        
                    resp = requests.get(url, params=params, timeout=10)
                    fetch_matrix_chunk.last_matrix_time = time.time()
                if resp.status_code == 200:
                    data = resp.json()
                    durations = data.get("durations", [])
                    
                    for s_i, src_idx in enumerate(src_indices):
                        for d_i, dest_idx in enumerate(dest_indices):
                            if src_idx == dest_idx:
                                continue
                            
                            if s_i < len(durations) and durations[s_i] and d_i < len(durations[s_i]) and durations[s_i][d_i] is not None:
                                dur_sec = durations[s_i][d_i]
                                mins = int(round(dur_sec / 60.0))
                                storage.set_cached_travel_time(all_locs[src_idx].lower(), all_locs[dest_idx].lower(), mins)
                    return True
                else:
                    print(f"Mapbox Matrix API failed: {resp.status_code} {resp.text}")
            except Exception as e:
                print(f"Mapbox Matrix error: {e}")
                
        # --- TIER 2: Mapbox Directions API (Individual pairwise requests) ---
        if mapbox_key and not disable_mapbox and not disable_directions:
            pairs_to_query = []
            for s_idx in src_indices:
                for d_idx in dest_indices:
                    if s_idx == d_idx:
                        continue
                    # Check if already cached (indefinite reuse of DB records to protect API limits)
                    c = storage.get_cached_travel_time(all_locs[s_idx].lower(), all_locs[d_idx].lower(), max_age_mins=cache_duration, ignore_age=True)
                    if c is None:
                        pairs_to_query.append((s_idx, d_idx))
                        
            if not pairs_to_query:
                # Everything is already cached! No need to do anything.
                return True
                
            if pairs_to_query:
                max_pairs = get_map_option('mapbox_directions_max_pairs', 50)
                disable_osrm = get_map_option('disable_osrm', False)
                if len(pairs_to_query) > max_pairs and not disable_osrm:
                    print(f"Too many pairs to query via Directions API ({len(pairs_to_query)} > {max_pairs}). Cascading to OSRM to protect limits and avoid long runtimes.")
                else:
                    if len(pairs_to_query) > max_pairs:
                        print(f"Querying {len(pairs_to_query)} pairs via Directions API (OSRM fallback disabled).")
                    else:
                        print(f"Mapbox Matrix unavailable/over limit. Querying Directions API for {len(pairs_to_query)} pairs.")
                    success_count = 0
                    for s_idx, d_idx in pairs_to_query:
                        if not check_usage_limits_and_spikes('directions', 1):
                            print("Mapbox Directions API limit reached. Cascading to OSRM.")
                            break
                            
                        try:
                            lat_s, lon_s = all_coords[s_idx]
                            lat_d, lon_d = all_coords[d_idx]
                            lat_s_f = float(lat_s)
                            lon_s_f = float(lon_s)
                            lat_d_f = float(lat_d)
                            lon_d_f = float(lon_d)
                        except (ValueError, TypeError, IndexError) as ex:
                            print(f"Warning: Skipping pairwise routing due to invalid coordinates: {ex}")
                            continue
                            
                        url = f"https://api.mapbox.com/directions/v5/mapbox/driving/{lon_s_f},{lat_s_f};{lon_d_f},{lat_d_f}"
                        params = {
                            "access_token": mapbox_key,
                            "overview": "false"
                        }
                        try:
                            with mapbox_routing_lock:
                                import time
                                if not hasattr(fetch_matrix_chunk, "last_matrix_time"):
                                    fetch_matrix_chunk.last_matrix_time = 0
                                now = time.time()
                                elapsed = now - fetch_matrix_chunk.last_matrix_time
                                if elapsed < 0.25:
                                    time.sleep(0.25 - elapsed)
                                
                                resp = requests.get(url, params=params, timeout=5)
                                fetch_matrix_chunk.last_matrix_time = time.time()
                                
                            if resp.status_code == 200:
                                data = resp.json()
                                routes = data.get("routes", [])
                                if routes:
                                    dur_sec = routes[0].get("duration", 900)
                                    mins = int(round(dur_sec / 60.0))
                                    storage.set_cached_travel_time(all_locs[s_idx].lower(), all_locs[d_idx].lower(), mins)
                                    success_count += 1
                            else:
                                print(f"Mapbox Directions API failed: {resp.status_code}")
                        except Exception as ex:
                            print(f"Mapbox Directions API error: {ex}")
                            
                    if success_count == len(pairs_to_query):
                        return True
                    
        # --- TIER 3: OSRM ---
        disable_osrm = get_map_option('disable_osrm', False)
        if disable_osrm:
            print("OSRM fallback is disabled. Matrix chunk calculation failed.")
            return False
            
        url = f"http://router.project-osrm.org/table/v1/driving/{coord_str}"
        params = {
            "sources": src_str,
            "destinations": dest_str,
            "annotations": "duration,distance"
        }
        try:
            resp = None
            for attempt in range(3):
                with api_rate_lock:
                    if not hasattr(fetch_matrix_chunk, "last_osrm_time"):
                        fetch_matrix_chunk.last_osrm_time = 0
                    elapsed = time.time() - fetch_matrix_chunk.last_osrm_time
                    if elapsed < 1.1:
                        time.sleep(1.1 - elapsed)
                    resp = requests.get(url, params=params, timeout=10)
                    
                    if resp.status_code == 429:
                        # Tell all other threads to back off for 2 extra seconds
                        fetch_matrix_chunk.last_osrm_time = time.time() + 2.0
                    else:
                        fetch_matrix_chunk.last_osrm_time = time.time()
                    
                if resp.status_code == 200:
                    break
                elif resp.status_code == 429:
                    print(f"OSRM API rate limited. Retrying attempt {attempt+1}/3...")
                    # We already backed off the global timer, so just wait for our next turn
                else:
                    break
                    
            if resp and resp.status_code == 200:
                data = resp.json()
                durations = data.get("durations", [])
                for s_i, src_idx in enumerate(src_indices):
                    for d_i, dest_idx in enumerate(dest_indices):
                        if src_idx == dest_idx:
                            continue
                        
                        if s_i < len(durations) and durations[s_i] and d_i < len(durations[s_i]) and durations[s_i][d_i] is not None:
                            dur_sec = durations[s_i][d_i]
                            mins = int(round(dur_sec / 60.0))
                            storage.set_cached_travel_time(all_locs[src_idx].lower(), all_locs[dest_idx].lower(), mins)
                return True
            else:
                print(f"OSRM Matrix API failed: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"OSRM Matrix error: {e}")
        return False
        
    matrix_usage = storage.get_mapbox_usage(current_month, 'matrix')
    matrix_limit = get_map_option('mapbox_matrix_limit', 90000)
    
    use_mapbox_matrix = (
        mapbox_key and 
        not disable_mapbox and 
        not get_map_option('disable_mapbox_matrix', False) and 
        matrix_usage < matrix_limit
    )
    
    N = len(coords)
    chunk_size = 12 if use_mapbox_matrix else 50
    if N <= chunk_size:
        fetch_matrix_chunk(list(range(N)), list(range(N)), coords, loc_names)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(0, N, chunk_size):
                src_chunk = list(range(i, min(i+chunk_size, N)))
                for j in range(0, N, chunk_size):
                    dest_chunk = list(range(j, min(j+chunk_size, N)))
                    futures.append(executor.submit(fetch_matrix_chunk, src_chunk, dest_chunk, coords, loc_names))
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Error in parallel matrix fetch: {e}")

def get_mapbox_api_key() -> Optional[str]:
    import os
    import json
    
    api_key = None
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            api_key = options.get('mapbox_api_key')
        except Exception:
            pass

    if not api_key:
        api_key = os.environ.get('MAPBOX_API_KEY')

    if not api_key:
        api_key_file = os.path.join(os.path.dirname(__file__), '..', 'mapbox_api_key.txt')
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

def _geocode_address_api_lookup(address: str) -> Optional[tuple[float, float, str]]:
    import urllib.parse
    mapbox_key = get_mapbox_api_key()
    disable_mapbox = get_map_option('disable_mapbox', False)
    
    # Try to get a local coordinate center from home_location to improve geocoding
    center_lon, center_lat = None, None
    settings = storage.get_settings()
    home_loc = get_home_location()
    if home_loc:
        cached_home = storage.get_cached_geocode(home_loc)
        if cached_home:
            try:
                clat = float(cached_home.get('lat', 0))
                clon = float(cached_home.get('lon', 0))
                if clat != 0.0 and clon != 0.0:
                    center_lat, center_lon = clat, clon
            except (ValueError, TypeError):
                pass
    
    if mapbox_key and not disable_mapbox and check_usage_limits_and_spikes('geocode', 1):
        url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{urllib.parse.quote(address)}.json"
        params = {
            "access_token": mapbox_key,
            "limit": 1
        }
        if center_lon is not None and center_lat is not None:
            params['proximity'] = f"{center_lon},{center_lat}"
        try:
            with mapbox_geocode_lock:
                import time
                if not hasattr(_geocode_address_api_lookup, "last_time"):
                    _geocode_address_api_lookup.last_time = 0
                now = time.time()
                elapsed = now - _geocode_address_api_lookup.last_time
                if elapsed < 0.11:
                    time.sleep(0.11 - elapsed)
                
                resp = requests.get(url, params=params, timeout=5)
                _geocode_address_api_lookup.last_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    lon, lat = features[0]["center"]
                    display_name = features[0].get("place_name", "")
                    return float(lat), float(lon), display_name
            else:
                print(f"Mapbox Geocoding API failed: {resp.status_code}")
        except Exception as ex:
            print(f"Mapbox Geocoding API exception: {ex}")
            
    # Fallback to Nominatim
    with api_rate_lock:
        import time
        if not hasattr(geocode_address, "last_nominatim_time"):
            geocode_address.last_nominatim_time = 0
        now = time.time()
        elapsed = now - geocode_address.last_nominatim_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
        
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address,
            "format": "json",
            "limit": 1
        }
        if center_lon is not None and center_lat is not None:
            # Create a ~50km viewbox around home for Nominatim (preference, not strict bound)
            params["viewbox"] = f"{center_lon-0.5},{center_lat-0.5},{center_lon+0.5},{center_lat+0.5}"
            
        headers = {
            "User-Agent": "ChauffeurScheduleAssistant/1.0"
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            geocode_address.last_nominatim_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                    display_name = data[0].get("display_name", "")
                    return float(lat), float(lon), display_name
        except Exception as e:
            print(f"Nominatim error: {e}")
            
    return None

def extract_street_address(address: str) -> str:
    if not address or not address.strip():
        return ""
    parts = [p.strip() for p in address.split(',')]
    if len(parts) <= 1:
        return address
        
    import re
    # Find the first part that starts with a digit (e.g. street number)
    for i, part in enumerate(parts):
        if re.match(r'^\s*\d', part):
            return ", ".join(parts[i:])
            
    return address

def geocode_address(address: str) -> Optional[tuple[float, float]]:
    if not address or not address.strip():
        return None
        
    # Extract the core street address first to avoid wasting geocoding requests
    cleaned_address = extract_street_address(address)
    
    # Check cache for cleaned address first
    cached = storage.get_cached_geocode(cleaned_address)
    if cached:
        try:
            lat = float(cached.get('lat'))
            lon = float(cached.get('lon'))
            if lat == 0.0 and lon == 0.0:
                return None
            return lat, lon
        except (ValueError, TypeError):
            pass

    # Call API lookup for cleaned address
    res = _geocode_address_api_lookup(cleaned_address)
    if res:
        lat, lon, display_name = res
        storage.set_cached_geocode(cleaned_address, lat, lon, display_name)
        if cleaned_address != address:
            storage.set_cached_geocode(address, lat, lon, display_name)
        return lat, lon

    # If the cleaned address lookup failed, fallback to the original detailed address
    if cleaned_address != address:
        print(f"Geocoding failed for cleaned address '{cleaned_address}'. Retrying with original: '{address}'")
        cached_orig = storage.get_cached_geocode(address)
        if cached_orig:
            try:
                lat = float(cached_orig.get('lat'))
                lon = float(cached_orig.get('lon'))
                if lat == 0.0 and lon == 0.0:
                    return None
                return lat, lon
            except (ValueError, TypeError):
                pass

        res_orig = _geocode_address_api_lookup(address)
        if res_orig:
            lat, lon, display_name = res_orig
            storage.set_cached_geocode(address, lat, lon, display_name)
            return lat, lon

    # Write failed status to cache for both
    storage.set_cached_geocode(cleaned_address, 0.0, 0.0, "FAILED_GEOCODE")
    if cleaned_address != address:
        storage.set_cached_geocode(address, 0.0, 0.0, "FAILED_GEOCODE")
    return None



def autocomplete_location(input_text: str, session_token: str = None) -> list[dict]:
    """
    Calls Mapbox Search Box API if session token is provided and within limits.
    Otherwise falls back to Geocoding API, then to Photon API.
    Returns a list of dicts: {"description": "...", "mapbox_id": "...", "is_searchbox": bool}
    """
    if not input_text or len(input_text) < 3:
        return []
        
    import datetime
    import urllib.parse
    mapbox_key = get_mapbox_api_key()
    disable_mapbox = get_map_option('disable_mapbox', False)
    
    if mapbox_key and not disable_mapbox:
        current_month = datetime.datetime.now().strftime("%Y-%m")
        # Check if we can use Search Box API
        if session_token:
            if check_usage_limits_and_spikes('searchbox', check_only=True):
                # Use Search Box API
                url = "https://api.mapbox.com/search/searchbox/v1/suggest"
                params = {
                    "access_token": mapbox_key,
                    "session_token": session_token,
                    "q": input_text,
                    "limit": 5,
                    "types": "address,poi"
                }
                try:
                    resp = requests.get(url, params=params, timeout=5)
                    if resp.status_code == 200:
                        data = resp.json()
                        suggestions = data.get("suggestions", [])
                        results = []
                        for s in suggestions:
                            name = s.get("name")
                            place = s.get("place_formatted")
                            desc = f"{name}, {place}" if place else name
                            if desc:
                                results.append({
                                    "description": desc,
                                    "mapbox_id": s.get("mapbox_id"),
                                    "is_searchbox": True
                                })
                        return results
                    else:
                        print(f"Mapbox Search Box Suggest API failed: {resp.status_code} {resp.text}")
                except Exception as ex:
                    print(f"Mapbox Search Box Suggest API exception: {ex}")

        # Fallback to Geocoding API v5
        if check_usage_limits_and_spikes('geocode', 1):
            url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{urllib.parse.quote(input_text)}.json"
            params = {
                "access_token": mapbox_key,
                "autocomplete": "true",
                "limit": 5,
                "types": "address,poi"
            }
            try:
                resp = requests.get(url, params=params, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    return [{"description": f.get("place_name")} for f in features if f.get("place_name")]
                else:
                    print(f"Mapbox Autocomplete API failed: {resp.status_code}")
            except Exception as ex:
                print(f"Mapbox Autocomplete API exception: {ex}")
            
    # Fallback to Photon
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

def retrieve_location(mapbox_id: str, session_token: str) -> Optional[dict]:
    import datetime
    mapbox_key = get_mapbox_api_key()
    if not mapbox_key or not mapbox_id or not session_token:
        return None
        
    url = f"https://api.mapbox.com/search/searchbox/v1/retrieve/{mapbox_id}"
    params = {
        "access_token": mapbox_key,
        "session_token": session_token
    }
    try:
        resp = requests.get(url, params=params, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            features = data.get("features", [])
            if features:
                f = features[0]
                props = f.get("properties", {})
                name = props.get("name", "")
                place = props.get("place_formatted", "")
                desc = f"{name}, {place}".strip(', ') if place else name
                
                coords = f.get("geometry", {}).get("coordinates", [])
                if desc and coords and len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
                    # Cache the geocode so backend doesn't need to look it up later
                    storage.set_cached_geocode(desc, float(lat), float(lon), desc)
                    
                    # Increment session usage since a retrieve was successfully made
                    check_usage_limits_and_spikes('searchbox', 1)
                    
                    return {
                        "name": desc,
                        "lat": lat,
                        "lon": lon
                    }
        else:
            print(f"Mapbox Search Box Retrieve API failed: {resp.status_code} {resp.text}")
    except Exception as ex:
        print(f"Mapbox Search Box Retrieve API exception: {ex}")
    return None

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
    import re
    if not locations:
        return ""
        
    def clean_loc(loc: str) -> str:
        parts = loc.split(',')
        if len(parts) > 1 and not re.search(r'\d', parts[0]) and re.search(r'\d', parts[1]):
            return ','.join(parts[1:]).strip()
        return loc
        
    cleaned_locs = [clean_loc(l) for l in locations]
    
    if len(cleaned_locs) == 1:
        return f"http://maps.apple.com/?daddr={urllib.parse.quote(cleaned_locs[0])}"

    # Apple Maps doesn't support waypoints via URL scheme in the same way,
    # but we can set start (saddr) and destination (daddr).
    # For a multi-stop route on Apple Maps, we unfortunately just pass the origin and final destination.
    origin = urllib.parse.quote(cleaned_locs[0])
    destination = urllib.parse.quote(cleaned_locs[-1])
    return f"http://maps.apple.com/?saddr={origin}&daddr={destination}"

def search_places(query: str, proximity_location: str = None) -> list[dict]:
    import datetime
    import urllib.parse
    import time
    
    mapbox_key = get_mapbox_api_key()
    disable_mapbox = get_map_option('disable_mapbox', False)
    
    # Geocode proximity location if provided
    center_lon, center_lat = None, None
    if proximity_location:
        cached = storage.get_cached_geocode(proximity_location)
        if cached and float(cached.get('lat', 0)) != 0.0:
            center_lat, center_lon = float(cached.get('lat')), float(cached.get('lon'))
        else:
            coords = geocode_address(proximity_location)
            if coords:
                center_lat, center_lon = coords

    disable_mapbox_category = get_map_option('disable_mapbox_category', False)

    if mapbox_key and not disable_mapbox:
        success = False
        
        # 1. Try Mapbox Category Search API first (optimized for POIs)
        if not disable_mapbox_category and check_usage_limits_and_spikes('category', 1):
            category_slug = query.strip().replace(" ", "_").lower()
            url_cat = f"https://api.mapbox.com/search/searchbox/v1/category/{urllib.parse.quote(category_slug)}"
            params_cat = {
                "access_token": mapbox_key,
                "limit": 5,
            }
            if center_lon is not None and center_lat is not None:
                params_cat['proximity'] = f"{center_lon},{center_lat}"
                
            try:
                resp_cat = requests.get(url_cat, params=params_cat, timeout=5)
                if resp_cat.status_code == 200:
                    data = resp_cat.json()
                    features = data.get("features", [])
                    if features:
                        success = True
                        results = []
                        for f in features:
                            props = f.get("properties", {})
                            name = props.get("name", "")
                            place = props.get("place_formatted", "")
                            full_address = f"{name}, {place}".strip(", ")
                            coords = f.get("geometry", {}).get("coordinates", [])
                            distance = props.get("distance", 0)
                            
                            if name and coords and len(coords) == 2:
                                lon, lat = coords[0], coords[1]
                                storage.set_cached_geocode(full_address, float(lat), float(lon), full_address)
                                results.append({
                                    "name": name,
                                    "address": full_address,
                                    "distance_meters": distance,
                                    "lat": lat,
                                    "lon": lon,
                                    "source": "mapbox_category"
                                })
                        return results
            except Exception as ex:
                print(f"Mapbox Category API exception: {ex}")
            
        # 2. Fallback to Mapbox Forward Search if Category Search fails (e.g. for specific brands like "Target")
        if not success and check_usage_limits_and_spikes('searchbox', 1, check_only=True):
            check_usage_limits_and_spikes('searchbox', 1)
            url_fwd = "https://api.mapbox.com/search/searchbox/v1/forward"
            params_fwd = {
                "access_token": mapbox_key,
                "q": query,
                "limit": 5,
            }
            if center_lon is not None and center_lat is not None:
                params_fwd['proximity'] = f"{center_lon},{center_lat}"
                
            try:
                resp = requests.get(url_fwd, params=params_fwd, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    features = data.get("features", [])
                    results = []
                    for f in features:
                        props = f.get("properties", {})
                        name = props.get("name", "")
                        place = props.get("place_formatted", "")
                        full_address = f"{name}, {place}".strip(", ")
                        coords = f.get("geometry", {}).get("coordinates", [])
                        distance = props.get("distance", 0)
                        
                        if name and coords and len(coords) == 2:
                            lon, lat = coords[0], coords[1]
                            storage.set_cached_geocode(full_address, float(lat), float(lon), full_address)
                            results.append({
                                "name": name,
                                "address": full_address,
                                "distance_meters": distance,
                                "lat": lat,
                                "lon": lon,
                                "source": "mapbox_forward"
                            })
                    return results
            except Exception as ex:
                print(f"Mapbox Forward API exception: {ex}")
            
    # Fallback to Nominatim OpenStreetMap search
    with api_rate_lock:
        if not hasattr(geocode_address, "last_nominatim_time"):
            geocode_address.last_nominatim_time = 0
        now = time.time()
        elapsed = now - geocode_address.last_nominatim_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)
            
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": query,
            "format": "json",
            "limit": 5
        }
        if center_lon is not None and center_lat is not None:
            # Create a ~20km viewbox around center for Nominatim
            params["viewbox"] = f"{center_lon-0.2},{center_lat-0.2},{center_lon+0.2},{center_lat+0.2}"
            params["bounded"] = 1
            
        headers = {
            "User-Agent": "ChauffeurScheduleAssistant/1.0"
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            geocode_address.last_nominatim_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data:
                    lat = float(item["lat"])
                    lon = float(item["lon"])
                    display_name = item.get("display_name", "")
                    # Cache it
                    storage.set_cached_geocode(display_name, lat, lon, display_name)
                    results.append({
                        "name": item.get("name") or display_name.split(',')[0],
                        "address": display_name,
                        "distance_meters": 0, # Nominatim doesn't directly give distance in this API
                        "lat": lat,
                        "lon": lon
                    })
                return results
        except Exception as e:
            print(f"Nominatim error: {e}")
            
    return []
