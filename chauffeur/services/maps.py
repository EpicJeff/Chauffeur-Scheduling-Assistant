import contextlib
import os
from typing import Optional

import requests
import threading
from services import storage

geocode_lock = threading.Lock()
api_rate_lock = threading.Lock()
mapbox_geocode_lock = threading.Lock()
mapbox_routing_lock = threading.Lock()


# --- Cache-only travel lookups ----------------------------------------------
# A background sweep must never be able to buy a Matrix/Directions element on
# its own initiative -- that is exactly how this app burned ~118,000 Matrix
# elements against a 100,000/month allowance in June 2026. `services.negotiation`
# re-solves the same day many times unattended, and a shifted time or a swapped
# driver can ask `get_travel_time_minutes` for a pair the daily refresh never
# primed. `travel_cache_only()` turns that ask into a hard miss instead of an
# invitation to fetch. A depth counter, not a bool, so a replay called from
# inside another cache-only scope cannot accidentally re-enable buying on exit.
_cache_only_depth = 0


class UncachedTravelPair(Exception):
    """A travel-time pair was needed, under `travel_cache_only()`, that the
    cache does not have. The caller's job is to drop whatever it was trying to
    do, not to catch this and fetch anyway."""


@contextlib.contextmanager
def travel_cache_only():
    global _cache_only_depth
    _cache_only_depth += 1
    try:
        yield
    finally:
        _cache_only_depth -= 1


def travel_cache_only_active() -> bool:
    return _cache_only_depth > 0

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
    # -- skipped under travel_cache_only(): geocoding is its own live lookup,
    # and this floor is a realism nicety, not something a dropped candidate
    # needs. See travel_cache_only()'s docstring for why nothing here may fetch.
    min_time_mins = 0
    if not travel_cache_only_active():
        coords_origin = geocode_address(origin)
        coords_dest = geocode_address(destination)
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
        if cached == -1:
            return (900, 0) if return_traffic else 900
        return (max(cached, min_time_mins), 0) if return_traffic else max(cached, min_time_mins)

    if travel_cache_only_active():
        raise UncachedTravelPair(f"{origin} -> {destination}")

    # 2. If not in cache, fallback to priming the cache for just this pair
    prime_matrix_cache([origin, destination], ignore_age=not return_traffic)
    
    # 3. Check cache again
    cached = storage.get_cached_travel_time(origin.lower(), destination.lower(), max_age_mins=cache_duration, ignore_age=not return_traffic)
    if cached is not None:
        if cached == -1:
            return (900, 0) if return_traffic else 900
        return (max(cached, min_time_mins), 0) if return_traffic else max(cached, min_time_mins)
        
    # 4. Return fallback if API fails (do not cache so it retries later)
    fallback = max(MOCK_TIME, min_time_mins)
    return (fallback, 0) if return_traffic else fallback

def get_route_geometry(origin: str, destination: str, profile: str = "driving",
                       origin_lat: Optional[float] = None, origin_lng: Optional[float] = None,
                       dest_lat: Optional[float] = None, dest_lng: Optional[float] = None) -> Optional[dict]:
    """
    Returns the route geometry and duration using Mapbox Directions API.
    profile can be 'driving', 'walking', 'cycling', etc.
    Returns: {"duration_mins": float, "geometry": dict, "distance_meters": float} or None.
    """
    cache_origin = f"{origin_lat},{origin_lng}" if origin_lat is not None and origin_lng is not None else origin
    cache_dest = f"{dest_lat},{dest_lng}" if dest_lat is not None and dest_lng is not None else destination

    cached = storage.get_cached_route_geometry(cache_origin, cache_dest, profile)
    if cached:
        return cached

    mapbox_key = get_mapbox_api_key()
    if not mapbox_key:
        return None
        
    if origin_lat is not None and origin_lng is not None:
        coords_origin = (origin_lat, origin_lng)
    else:
        coords_origin = geocode_address(origin)
        
    if dest_lat is not None and dest_lng is not None:
        coords_dest = (dest_lat, dest_lng)
    else:
        coords_dest = geocode_address(destination)
        
    if not coords_origin or not coords_dest:
        return None
        
    lat_s, lon_s = coords_origin
    lat_d, lon_d = coords_dest
    
    if not check_usage_limits_and_spikes('directions', increment=1):
        return None
        
    url = f"https://api.mapbox.com/directions/v5/mapbox/{profile}/{lon_s},{lat_s};{lon_d},{lat_d}"
    params = {
        "access_token": mapbox_key,
        "overview": "full",
        "geometries": "geojson"
    }
    # Household toll policy — driving profiles only; `exclude=toll` is not a
    # valid parameter for walking/cycling.
    if profile in ("driving", "driving-traffic") and avoid_tolls_enabled():
        params["exclude"] = "toll"
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('routes') and len(data['routes']) > 0:
                route = data['routes'][0]
                result = {
                    "duration_mins": route['duration'] / 60.0,
                    "distance_meters": route['distance'],
                    "geometry": route['geometry']
                }
                storage.set_cached_route_geometry(cache_origin, cache_dest, profile, result)
                return result
    except Exception as e:
        print(f"Error fetching route geometry: {e}")
        
    return None

def avoid_tolls_enabled() -> bool:
    """Whether drive times should be priced WITHOUT toll roads.

    Mapbox's default is tolls-allowed, which quietly priced every Apex drive
    over the NC-540 toll road — a 16-minute route the family may never take,
    reported as "17 minutes" against Apple's 20-minute free route. Whether a
    household drives tolls is a fact about the household, so it is a setting;
    the Matrix API cannot express `exclude=toll`, so turning this on routes
    every pair through the pairwise Directions tier instead.
    """
    return bool(get_map_option('routing_avoid_tolls', False))


# ── Day-of traffic ──────────────────────────────────────────────────────────
# Three layers of travel time, cheapest first (the static Matrix numbers the
# solver plans with are deliberately traffic-free and near-permanent — see
# system_capabilities "Travel Time"):
#   1. the static matrix          — planning baseline, bought once per pair
#   2. a MORNING pass, day of     — driving-traffic with depart_at, predictive
#      for each drive's planned hour, so the day reads realistic from breakfast
#   3. a T-60 REFINE              — live traffic an hour before the current
#      leave-at, when the number is about to be acted on
# Two requests per driving leg per day, hard-marked so they can never repeat
# (the 100k-element month came from a cache bug refetching every 10 minutes —
# the stage markers make that failure mode structurally impossible here).
# Surfaces never fetch: they read the day-of cache and fall back to static.

def _traffic_cache_key(addr: str, coords: tuple = None) -> str:
    """Day-of rows are keyed by COORDINATES, not by address strings.

    The same house arrives here as '…Apex, NC, USA' from a solver edge and
    '…Apex, North Carolina 27523, United States' from settings — string keys
    made the sweep's buys invisible to every reader. Geocoding is already
    cached for every address these paths carry, and four decimals (~11 m)
    is the same building. The raw string is the fallback so an ungeocodable
    pair still round-trips against itself.
    """
    coords = coords or geocode_address(addr)
    if coords:
        return f"{coords[0]:.4f},{coords[1]:.4f}"
    return (addr or '').strip().lower()


def get_day_of_traffic(origin: Optional[str], destination: Optional[str]) -> Optional[dict]:
    """Today's traffic row for a pair, whatever spelling the caller has."""
    if not origin or not destination:
        return None
    return storage.get_cached_day_of_traffic(_traffic_cache_key(origin),
                                             _traffic_cache_key(destination))


def fetch_traffic_minutes(origin: Optional[str], destination: Optional[str],
                          depart_at_ts: float = None,
                          stage: str = 'refine') -> Optional[int]:
    """One driving-traffic Directions request; writes the day-of cache.

    `depart_at_ts` asks Mapbox for PREDICTIVE traffic at that departure time
    (the morning pass); without it the answer is live traffic now (the
    refine). None on any failure — callers fall back to the static number,
    which can never be worse than before this existed.
    """
    if not origin or not destination:
        return None
    if origin.strip().lower() == destination.strip().lower():
        return None
    if get_map_option('disable_mapbox', False) \
            or get_map_option('disable_mapbox_directions', False):
        return None
    mapbox_key = get_mapbox_api_key()
    if not mapbox_key:
        return None
    coords_origin = geocode_address(origin)
    coords_dest = geocode_address(destination)
    if not coords_origin or not coords_dest:
        return None
    if not check_usage_limits_and_spikes('directions', increment=1):
        return None
    lat_s, lon_s = coords_origin
    lat_d, lon_d = coords_dest
    params = {"access_token": mapbox_key, "overview": "false"}
    if avoid_tolls_enabled():
        params["exclude"] = "toll"
    if depart_at_ts:
        import datetime as _dt
        params["depart_at"] = _dt.datetime.fromtimestamp(
            depart_at_ts).strftime('%Y-%m-%dT%H:%M')
    url = f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{lon_s},{lat_s};{lon_d},{lat_d}"
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            routes = (resp.json() or {}).get('routes') or []
            if routes:
                mins = int(round(float(routes[0].get('duration') or 0) / 60.0))
                if mins > 0:
                    storage.set_cached_day_of_traffic(
                        _traffic_cache_key(origin, coords_origin),
                        _traffic_cache_key(destination, coords_dest),
                        mins, stage)
                    return mins
        else:
            print(f"driving-traffic {resp.status_code}: {origin} -> {destination}")
    except Exception as e:
        print(f"driving-traffic error ({origin} -> {destination}): {e}")
    return None


def live_adjusted_trigger(notif: dict) -> float:
    """When a Time-to-Leave push should actually fire, given today's traffic.

    Reads the day-of cache ONLY — the sweep does the buying. EARLIER only:
    the static number is essentially free-flow, so a slower day-of reading
    moves the departure up; a faster one is noise and never delays a plan
    somebody may already be acting on.
    """
    trigger = float(notif.get('trigger_timestamp') or 0)
    origin, dest = notif.get('origin'), notif.get('destination')
    try:
        static = float(notif.get('travel_static_mins') or 0)
    except (TypeError, ValueError):
        return trigger
    if not origin or not dest or static <= 0:
        return trigger
    row = get_day_of_traffic(origin, dest)
    if not row or row['duration_mins'] <= static:
        return trigger
    return trigger - (row['duration_mins'] - static) * 60.0


_SWEEP_EVERY_SECS = 120
_last_sweep_ts = 0.0


def run_day_of_traffic_sweep(now_ts: float = None) -> dict:
    """The two scheduled passes, driven off the pending Time-to-Leave
    notifications (which carry each leg's route and static minutes).

    Stage markers live in app_state keyed `notif_id:stage` and reset daily.
    A marker is set BEFORE its fetch (the weekly-digest precedent): a failing
    address gets one shot per stage per day, never a retry storm against the
    Directions quota — the refine is the retry.
    """
    global _last_sweep_ts
    import time
    import datetime as _dt
    now_ts = now_ts or time.time()
    if now_ts - _last_sweep_ts < _SWEEP_EVERY_SECS:
        return {'skipped': 'throttled'}
    _last_sweep_ts = now_ts
    settings = storage.get_settings() or {}
    if settings.get('traffic_live_enabled') is False:
        return {'skipped': 'disabled'}
    # Absent means 6, but an explicit 0 means MIDNIGHT — the same absent-vs-
    # zero discipline the panel's idle return already keeps. `or 6` ate the
    # zero, so a household that set the morning buy to midnight silently got
    # six o'clock, and the sweep test only passed because the suite happened
    # to run after 6am.
    raw = settings.get('traffic_morning_hour')
    try:
        morning_hour = 6 if raw is None else int(raw)
    except (TypeError, ValueError):
        morning_hour = 6
    today = _dt.date.fromtimestamp(now_ts).isoformat()
    # _v2: the key namespace moved when the cache went coordinate-keyed —
    # markers from the string-keyed hour get one re-buy under the new keys.
    state = storage.get_app_state('traffic_sweep_done_v2') or {}
    if state.get('date') != today:
        state = {'date': today, 'done': {}}
    done = dict(state.get('done') or {})
    fetched = 0
    for notif in storage.get_pending_notifications():
        origin, dest = notif.get('origin'), notif.get('destination')
        trigger = float(notif.get('trigger_timestamp') or 0)
        try:
            static = float(notif.get('travel_static_mins') or 0)
        except (TypeError, ValueError):
            continue
        if not origin or not dest or static <= 0 or not trigger:
            continue
        # Today's legs only, and not already behind us.
        if _dt.date.fromtimestamp(trigger).isoformat() != today \
                or trigger < now_ts - 600:
            continue
        nid = str(notif.get('notif_id'))
        if f"{nid}:morning" not in done \
                and _dt.datetime.fromtimestamp(now_ts).hour >= morning_hour:
            done[f"{nid}:morning"] = True
            if fetch_traffic_minutes(origin, dest, depart_at_ts=trigger,
                                     stage='morning') is not None:
                fetched += 1
        # T-60, measured against the CURRENT departure — the morning pass may
        # already have pulled it earlier, and the hour is anchored to when
        # somebody will actually stand up.
        if f"{nid}:refine" not in done \
                and now_ts >= live_adjusted_trigger(notif) - 3600:
            done[f"{nid}:refine"] = True
            if fetch_traffic_minutes(origin, dest, stage='refine') is not None:
                fetched += 1
    storage.set_app_state('traffic_sweep_done_v2', {'date': today, 'done': done})
    return {'fetched': fetched}


def prime_matrix_cache(locations: list[str], ignore_age: bool = False):
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
        c1 = storage.get_cached_travel_time(l1.lower(), l2.lower(), max_age_mins=cache_duration, ignore_age=ignore_age)
        c2 = storage.get_cached_travel_time(l2.lower(), l1.lower(), max_age_mins=cache_duration, ignore_age=ignore_age)
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
    
    failed_locs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_loc = {executor.submit(geocode_address, loc): loc for loc in unique_locs}
        for future in concurrent.futures.as_completed(future_to_loc):
            loc = future_to_loc[future]
            try:
                c = future.result()
                if c:
                    coords.append(c)
                    loc_names.append(loc)
                else:
                    failed_locs.append(loc)
            except Exception as e:
                print(f"Error parallel geocoding {loc}: {e}")
                failed_locs.append(loc)
            
    if failed_locs:
        bulk_entries = []
        for f_loc in failed_locs:
            for other_loc in locations:
                if f_loc.lower() != other_loc.lower():
                    bulk_entries.append({"origin": f_loc.lower(), "destination": other_loc.lower(), "duration_mins": -1})
                    bulk_entries.append({"origin": other_loc.lower(), "destination": f_loc.lower(), "duration_mins": -1})
        if bulk_entries:
            storage.set_cached_travel_times_bulk(bulk_entries)
            
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
        # The Matrix API cannot say `exclude=toll`, so a no-tolls household
        # must skip straight to the pairwise Directions tier — a matrix
        # answer priced over the toll road is wrong, not merely imprecise.
        avoid_tolls = avoid_tolls_enabled()
        elements = len(src_indices) * len(dest_indices)

        # --- TIER 1: Mapbox Matrix API ---
        if mapbox_key and not disable_mapbox and not disable_matrix and not avoid_tolls and check_usage_limits_and_spikes('matrix', elements):
            url = f"https://api.mapbox.com/directions-matrix/v1/mapbox/driving/{coord_str}"
            params = {
                "access_token": mapbox_key,
                "sources": src_str,
                "destinations": dest_str,
                "annotations": "duration,distance"
            }
            try:
                with mapbox_routing_lock:
                    import time as local_time
                    if not hasattr(fetch_matrix_chunk, "last_matrix_time"):
                        fetch_matrix_chunk.last_matrix_time = 0
                    elapsed = local_time.time() - fetch_matrix_chunk.last_matrix_time
                    if elapsed < 0.25:
                        local_time.sleep(0.25 - elapsed)
                        
                    resp = requests.get(url, params=params, timeout=10)
                    fetch_matrix_chunk.last_matrix_time = local_time.time()
                if resp.status_code == 200:
                    data = resp.json()
                    durations = data.get("durations", [])
                    
                    bulk_entries = []
                    for s_i, src_idx in enumerate(src_indices):
                        for d_i, dest_idx in enumerate(dest_indices):
                            if src_idx == dest_idx:
                                continue
                            
                            if s_i < len(durations) and durations[s_i] and d_i < len(durations[s_i]):
                                dur_sec = durations[s_i][d_i]
                                if dur_sec is not None:
                                    mins = int(round(dur_sec / 60.0))
                                else:
                                    mins = -1
                                bulk_entries.append({
                                    "origin": all_locs[src_idx].lower(), 
                                    "destination": all_locs[dest_idx].lower(), 
                                    "duration_mins": mins
                                })
                    storage.set_cached_travel_times_bulk(bulk_entries)
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
                        if avoid_tolls:
                            params["exclude"] = "toll"
                        try:
                            with mapbox_routing_lock:
                                import time as local_time
                                if not hasattr(fetch_matrix_chunk, "last_matrix_time"):
                                    fetch_matrix_chunk.last_matrix_time = 0
                                elapsed = local_time.time() - fetch_matrix_chunk.last_matrix_time
                                if elapsed < 0.25:
                                    local_time.sleep(0.25 - elapsed)
                                
                                resp = requests.get(url, params=params, timeout=5)
                                fetch_matrix_chunk.last_matrix_time = local_time.time()
                                
                            if resp.status_code == 200:
                                data = resp.json()
                                routes = data.get("routes", [])
                                if routes:
                                    dur_sec = routes[0].get("duration", -1)
                                    if dur_sec == -1:
                                        mins = -1
                                    else:
                                        mins = int(round(dur_sec / 60.0))
                                else:
                                    mins = -1
                                storage.set_cached_travel_time(all_locs[s_idx].lower(), all_locs[d_idx].lower(), mins)
                                success_count += 1
                            else:
                                print(f"Mapbox Directions API failed: {resp.status_code}")
                                storage.set_cached_travel_time(all_locs[s_idx].lower(), all_locs[d_idx].lower(), -1)
                        except Exception as ex:
                            print(f"Mapbox Directions API error: {ex}")
                            storage.set_cached_travel_time(all_locs[s_idx].lower(), all_locs[d_idx].lower(), -1)
                            
                    if success_count == len(pairs_to_query):
                        return True
                    
        # --- TIER 3: OSRM ---
        disable_osrm = get_map_option('disable_osrm', False)
        if disable_osrm:
            print("OSRM fallback is disabled. Matrix chunk calculation failed.")
            bulk_entries = []
            for s_idx in src_indices:
                for d_idx in dest_indices:
                    if s_idx != d_idx:
                        bulk_entries.append({"origin": all_locs[s_idx].lower(), "destination": all_locs[d_idx].lower(), "duration_mins": -1})
            storage.set_cached_travel_times_bulk(bulk_entries)
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
                    import time as local_time
                    elapsed = local_time.time() - fetch_matrix_chunk.last_osrm_time
                    if elapsed < 1.1:
                        local_time.sleep(1.1 - elapsed)
                    resp = requests.get(url, params=params, timeout=10)
                    
                    if resp.status_code == 429:
                        # Tell all other threads to back off for 2 extra seconds
                        fetch_matrix_chunk.last_osrm_time = local_time.time() + 2.0
                    else:
                        fetch_matrix_chunk.last_osrm_time = local_time.time()
                    
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
                bulk_entries = []
                for s_i, src_idx in enumerate(src_indices):
                    for d_i, dest_idx in enumerate(dest_indices):
                        if src_idx == dest_idx:
                            continue
                        
                        if s_i < len(durations) and durations[s_i] and d_i < len(durations[s_i]):
                            dur_sec = durations[s_i][d_i]
                            if dur_sec is not None:
                                mins = int(round(dur_sec / 60.0))
                            else:
                                mins = -1
                            bulk_entries.append({
                                "origin": all_locs[src_idx].lower(), 
                                "destination": all_locs[dest_idx].lower(), 
                                "duration_mins": mins
                            })
                storage.set_cached_travel_times_bulk(bulk_entries)
                return True
            else:
                print(f"OSRM Matrix API failed: {resp.status_code if resp else 'None'}")
                bulk_entries = []
                for s_idx in src_indices:
                    for d_idx in dest_indices:
                        if s_idx != d_idx:
                            bulk_entries.append({"origin": all_locs[s_idx].lower(), "destination": all_locs[d_idx].lower(), "duration_mins": -1})
                storage.set_cached_travel_times_bulk(bulk_entries)
        except Exception as e:
            print(f"OSRM Matrix error: {e}")
            bulk_entries = []
            for s_idx in src_indices:
                for d_idx in dest_indices:
                    if s_idx != d_idx:
                        bulk_entries.append({"origin": all_locs[s_idx].lower(), "destination": all_locs[d_idx].lower(), "duration_mins": -1})
            storage.set_cached_travel_times_bulk(bulk_entries)
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
    address = strip_url_noise(address).strip(' ,;')
    if not address:
        return None  # a location that was nothing but a link: not a place
        
    if mapbox_key and not disable_mapbox and check_usage_limits_and_spikes('geocode', 1):
        # Mapbox has a 256 char / 20 word limit. Truncate for Mapbox request.
        mapbox_address = address
        if len(mapbox_address) > 200:
            mapbox_address = mapbox_address[:200]
        words = mapbox_address.split()
        if len(words) > 18:
            mapbox_address = " ".join(words[:18])
            
        url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{urllib.parse.quote(mapbox_address)}.json"
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
            elif resp.status_code != 422:
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
            "User-Agent": "ChauffeurScheduleAssistant/1.0",
            "Accept-Language": "en-US,en;q=0.9"
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

def resolve_routable_location(location: str) -> str:
    """Venue-only event location ("Mills Park Middle School") -> a routable
    "Name, street address" the solver can actually geocode and route to.

    Agent-created events (intake approvals, chat create_event, errands) carry
    whatever location string the LLM extracted, which is usually a bare venue
    name. Resolve it once at creation time through the normal geocoder
    (Mapbox with home-proximity bias, Nominatim fallback, geocode_cache-backed)
    and store the geocoder's full display name.

    Safety rails: anything already containing a digit (street number, zip,
    "Field 3") passes through untouched, as does anything the geocoder can't
    resolve — this must never block or distort event creation."""
    loc = (location or '').strip()
    if not loc:
        return location  # preserve None/'' exactly as given
    if any(ch.isdigit() for ch in loc):
        return loc
    try:
        cached = storage.get_cached_geocode(loc)
        display = (cached or {}).get('display_name')
        if not display:
            res = _geocode_address_api_lookup(loc)
            if not res:
                return loc
            lat, lon, display = res
            storage.set_cached_geocode(loc, lat, lon, display)
        display = (display or '').strip()
        if not display:
            return loc
        # Mapbox/Nominatim display names usually already lead with the venue
        # name; only prepend it when they don't, so it stays human-readable.
        return display if loc.lower() in display.lower() else f"{loc}, {display}"
    except Exception as ex:
        print(f"Location resolve failed for '{loc}': {ex}")
        return loc

_URL_IN_LOCATION = None


def strip_url_noise(address: str) -> str:
    """Drop link text from a location string.

    Calendar feeds routinely put a ticket/coupon link where the address goes
    (PlayMetrics: `LOCATION:https://tickets.nccourage.com/...`). A geocoder
    does NOT reject a URL — Mapbox tokenizes it and matches the fragments, so
    that string resolves to "Paces, Virginia", 130 miles from the family, and
    the solver plans a real drive to it. Strip the URL and keep whatever
    genuine address sat beside it; an all-link location becomes ''.
    """
    global _URL_IN_LOCATION
    if not address:
        return ''
    if _URL_IN_LOCATION is None:
        import re as _r
        _URL_IN_LOCATION = (
            _r.compile(r'\b(?:[a-z][a-z0-9+.-]*://|www\.|mailto:|tel:)\S+', _r.I),
            _r.compile(r'\s+'),
        )
    url_re, ws_re = _URL_IN_LOCATION
    cleaned = url_re.sub(' ', address)
    return ws_re.sub(' ', cleaned).strip(' ,;|-–—')


def extract_street_address(address: str) -> str:
    if not address or not address.strip(' ,;'):
        return ""
    parts = [p.strip() for p in address.split(',') if p.strip()]
    if len(parts) <= 1:
        return address.strip(' ,;')
        
    import re
    first_digit_index = -1
    for i, part in enumerate(parts):
        if re.match(r'^\s*\d', part):
            first_digit_index = i
            break

    if first_digit_index == 0:
        # Already starts with the house number — this IS the street address.
        # The old code fell through to the >3-parts "drop the business name"
        # heuristic, which amputated the street line from Mapbox-canonical
        # addresses ("123 St, City, State ZIP, United States" → "City, State
        # ZIP, United States") and geocoded HOME to the city center (v2.56.4).
        return ", ".join(parts)

    if first_digit_index > 0:
        # If the part is just a number/zip code near the end, only drop the first part (business name)
        if first_digit_index >= len(parts) - 3 and re.match(r'^\s*\d+\s*$', parts[first_digit_index].split()[0]):
            return ", ".join(parts[1:])
        else:
            return ", ".join(parts[first_digit_index:])

    if len(parts) > 3:
        return ", ".join(parts[1:])

    return address

_TZ_FINDER = None

def get_timezone(address: str) -> str:
    coords = geocode_address(address)
    if not coords:
        return "UTC"
    lat, lon = coords
    try:
        # TimezoneFinder() loads a large polygon dataset from disk — constructing it
        # per call costs seconds. Build once, reuse forever.
        global _TZ_FINDER
        if _TZ_FINDER is None:
            from timezonefinder import TimezoneFinder
            _TZ_FINDER = TimezoneFinder(in_memory=True)
        tz = _TZ_FINDER.timezone_at(lng=lon, lat=lat)
        return tz or "UTC"
    except ImportError:
        return "UTC"

GEOCODE_RETRY_SECS = 24 * 3600  # non-exact cache entries retry daily


def _usable_cached(cached, want_address: str):
    """(coords_or_None, should_retry). Exact street-level hits are final.
    City-fallback and failed entries are RETRYABLE once per day — a single
    bad geocode (rate limit, network blip) must never weld an address to the
    city center forever, which is exactly what the old permanent cache did
    to home_location (v2.56.4). Legacy rows have no precision field, so
    they're sniffed: an address that starts with a house number whose cached
    display_name doesn't contain that number is a city-level result wearing
    an exact entry's key."""
    import re as _re
    import time as _time
    if not cached:
        return None, True
    try:
        lat, lon = float(cached.get('lat')), float(cached.get('lon'))
    except (ValueError, TypeError):
        return None, True
    failed = (lat == 0.0 and lon == 0.0)
    precision = cached.get('precision')
    if precision is None and not failed:
        m = _re.match(r'^\s*(\d+)\b', want_address or '')
        if m and m.group(1) not in (cached.get('display_name') or ''):
            precision = 'city'  # legacy poisoned entry — heal it
        else:
            precision = 'exact'
    stale = (_time.time() - float(cached.get('ts') or 0)) >= GEOCODE_RETRY_SECS
    if failed:
        return None, stale
    if precision == 'city':
        return (lat, lon), stale
    return (lat, lon), False


def geocode_address(address: str) -> Optional[tuple[float, float]]:
    if not address or not address.strip():
        return None

    # Link-only locations are not places. Settle here rather than burning an
    # API call, a cache row and the city/state fallback on a URL.
    if not strip_url_noise(address):
        return None

    # Extract the core street address first to avoid wasting geocoding requests
    cleaned_address = extract_street_address(address)

    coords, retry = _usable_cached(storage.get_cached_geocode(cleaned_address), cleaned_address)
    if not retry:
        # exact hit (final) — or a fresh cached failure (None): both settle
        # without touching the API; failures re-try daily via ts.
        return coords
    last_resort = coords  # a stale city-level hit: retry now, but never lose it

    # Street-level lookup for the cleaned address
    res = _geocode_address_api_lookup(cleaned_address)
    if res:
        lat, lon, display_name = res
        storage.set_cached_geocode(cleaned_address, lat, lon, display_name)
        if cleaned_address != address:
            storage.set_cached_geocode(address, lat, lon, display_name)
        return lat, lon

    # If the cleaned address lookup failed, fallback to the original detailed address
    if cleaned_address != address:
        coords, retry = _usable_cached(storage.get_cached_geocode(address), address)
        if coords and not retry:
            return coords
        last_resort = last_resort or coords
        print(f"Geocoding failed for cleaned address '{cleaned_address}'. Retrying with original: '{address}'")
        res_orig = _geocode_address_api_lookup(address)
        if res_orig:
            lat, lon, display_name = res_orig
            storage.set_cached_geocode(address, lat, lon, display_name)
            return lat, lon

    # Street-level failed: city/state fallback (last 3 address components).
    # Cached under the full address as precision='city' — reused today,
    # RETRIED at street level tomorrow. Never a permanent pin.
    parts = address.split(',')
    if len(parts) >= 3:
        city_state = ", ".join([p.strip() for p in parts[-3:]])
        coords, retry = _usable_cached(storage.get_cached_geocode(city_state), city_state)
        if not coords or retry:
            print(f"Geocoding failed for full address. Retrying with city/state: '{city_state}'")
            res = _geocode_address_api_lookup(city_state)
            if res:
                lat, lon, display_name = res
                storage.set_cached_geocode(city_state, lat, lon, display_name)
                coords = (lat, lon)
        if coords:
            row = storage.get_cached_geocode(city_state) or {}
            storage.set_cached_geocode(address, coords[0], coords[1],
                                       row.get('display_name') or city_state,
                                       precision='city')
            return coords

    if last_resort:
        return last_resort  # stale city coords beat nothing — retry again tomorrow

    # Cache the failure (daily retry via ts) so we don't spam the API
    storage.set_cached_geocode(cleaned_address, 0.0, 0.0, "FAILED_GEOCODE", precision='failed')
    if cleaned_address != address:
        storage.set_cached_geocode(address, 0.0, 0.0, "FAILED_GEOCODE", precision='failed')
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
                    "language": "en"
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
                "language": "en"
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
        "limit": 5,
        "lang": "en"
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

    import math

    def _dist_m(lat1, lon1, lat2, lon2):
        R = 6371000.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
        return 2 * R * math.asin(math.sqrt(a))

    def _looks_like_rental_listing(name, osm_type):
        # OSM free-text search surfaces private vacation rentals whose names embed
        # landmark names ("Loftly ... apartment ... near Disney, Magic Kingdom ...").
        # These pollute a landmark query and must never outrank the real POI.
        nl = (name or "").lower()
        if osm_type in ("apartment", "chalet", "guest_house", "hostel", "caravan_site", "static_caravan"):
            return True
        if len(name or "") > 70:
            return True
        listing_kw = ("2br", "1br", "3br", "4br", "2ba", "1ba", "3ba", "/night", "per night",
                      "sleeps", "free parking", "free wifi", "free cable", "gated community",
                      "near disney", "close to disney", "spacious", "cozy retreat")
        if sum(1 for k in listing_kw if k in nl) >= 2:
            return True
        return False

    # 1. Nominatim (OpenStreetMap): rich extratags (wikidata, opening_hours, website),
    #    but poor relevance for landmark names — so it enriches, it doesn't decide.
    nominatim_results = []
    with api_rate_lock:
        if not hasattr(geocode_address, "last_nominatim_time"):
            geocode_address.last_nominatim_time = 0
        now = time.time()
        elapsed = now - geocode_address.last_nominatim_time
        if elapsed < 1.1:
            time.sleep(1.1 - elapsed)

        headers = {'User-Agent': 'ChauffeurScheduleAssistant/1.0 (https://github.com/EpicJeff/Chauffeur-Scheduling-Assistant)'}
        nom_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query)}&format=json&limit=5&extratags=1"
        if center_lat is not None and center_lon is not None:
            viewbox = f"{center_lon - 0.5},{center_lat + 0.5},{center_lon + 0.5},{center_lat - 0.5}"
            nom_url += f"&viewbox={viewbox}&bounded=0"

        try:
            resp = requests.get(nom_url, headers=headers, timeout=10)
            geocode_address.last_nominatim_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                for item in data:
                    lat = float(item.get("lat", 0))
                    lon = float(item.get("lon", 0))
                    name = item.get("name", query)
                    if _looks_like_rental_listing(name, item.get("type")):
                        continue  # drop vacation-rental listing junk
                    address = item.get("display_name", "")
                    extratags = item.get("extratags", {}) or {}
                    storage.set_cached_geocode(address, lat, lon, address)
                    nominatim_results.append({
                        "name": name,
                        "address": address,
                        "distance_meters": 0,
                        "lat": lat,
                        "lon": lon,
                        "source": "nominatim",
                        "wikidata_id": extratags.get("wikidata"),
                        "opening_hours": extratags.get("opening_hours"),
                        "website": extratags.get("website") or extratags.get("contact:website"),
                        "phone_number": extratags.get("phone") or extratags.get("contact:phone"),
                        "cuisine": extratags.get("cuisine"),
                        "internet_access": extratags.get("internet_access")
                    })
        except Exception as ex:
            print(f"Nominatim API exception in search_places: {ex}")

    # 2. Mapbox Search Box: authoritative, proximity-biased POI/address results — it
    #    won't return random Airbnb listings for a landmark query. This is the source
    #    of the real address whenever Mapbox is available.
    mapbox_results = []
    if mapbox_key and not disable_mapbox:
        try:
            check_usage_limits_and_spikes('searchbox', 1)
            url_fwd = "https://api.mapbox.com/search/searchbox/v1/forward"
            params_fwd = {"access_token": mapbox_key, "q": query, "limit": 5, "language": "en"}
            if center_lon is not None and center_lat is not None:
                params_fwd['proximity'] = f"{center_lon},{center_lat}"
            resp = requests.get(url_fwd, params=params_fwd, timeout=5)
            if resp.status_code == 200:
                for f in resp.json().get("features", []):
                    props = f.get("properties", {})
                    name = props.get("name", "")
                    place = props.get("place_formatted", "")
                    full_address = f"{name}, {place}".strip(", ")
                    coords = f.get("geometry", {}).get("coordinates", [])
                    if name and coords and len(coords) == 2:
                        lon, lat = coords[0], coords[1]
                        storage.set_cached_geocode(full_address, float(lat), float(lon), full_address)
                        mapbox_results.append({
                            "name": name,
                            "address": full_address,
                            "distance_meters": props.get("distance", 0),
                            "lat": lat,
                            "lon": lon,
                            "source": "mapbox_forward",
                            "mapbox_id": props.get("mapbox_id"),
                            "wikidata_id": None,
                            "opening_hours": None,
                            "website": None,
                            "phone_number": None,
                            "cuisine": None,
                            "internet_access": None
                        })
        except Exception as ex:
            print(f"Mapbox Forward API exception: {ex}")

    # 3. Prefer Mapbox for the real name/address/coords; backfill extratags
    #    (wikidata/hours/website) from the nearest matching Nominatim result — same
    #    place, so a landmark keeps its wikidata while shedding the listing junk.
    if mapbox_results:
        for m in mapbox_results:
            best, best_d = None, 300.0   # metres — same-place threshold
            for n in nominatim_results:
                d = _dist_m(m["lat"], m["lon"], n["lat"], n["lon"])
                if d < best_d:
                    best, best_d = n, d
            if best:
                for k in ("wikidata_id", "opening_hours", "website", "phone_number", "cuisine", "internet_access"):
                    if not m.get(k) and best.get(k):
                        m[k] = best[k]
        return mapbox_results

    # No Mapbox available/enabled — fall back to the junk-filtered Nominatim results.
    return nominatim_results


def _encode_polyline(coords, precision=5):
    """GeoJSON [lon, lat] pairs -> encoded polyline string (standard lat,lng
    delta encoding), for Search Box search-along-route."""
    factor = 10 ** precision
    output = []
    prev_lat = prev_lon = 0
    for lon, lat in coords:
        ilat, ilon = round(lat * factor), round(lon * factor)
        for v in (ilat - prev_lat, ilon - prev_lon):
            v = ~(v << 1) if v < 0 else (v << 1)
            while v >= 0x20:
                output.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            output.append(chr(v + 63))
        prev_lat, prev_lon = ilat, ilon
    return ''.join(output)


def search_category(category: str, lat: float = None, lon: float = None, limit: int = 10,
                    route_coords=None, time_deviation_mins: float = 8):
    """Mapbox Search Box category search (e.g. 'gas_station'), either near a
    point (lat/lon proximity) or ALONG A ROUTE when route_coords (GeoJSON
    [lon, lat] pairs) is given — search-along-route via sar_type=isochrone
    with a polyline-encoded route, results constrained to a time_deviation-
    minute detour. No session token; billed under the 'category' cap. Used by
    the C3 car-stop proposals. Returns [{name, address, lat, lon}]; [] when
    Mapbox is unavailable — callers must have a non-Mapbox fallback."""
    mapbox_key = get_mapbox_api_key()
    settings = storage.get_settings()
    if not mapbox_key or settings.get('disable_mapbox', False):
        return []
    try:
        check_usage_limits_and_spikes('category', 1)
        url = f"https://api.mapbox.com/search/searchbox/v1/category/{category}"
        params = {"access_token": mapbox_key, "limit": max(1, min(int(limit), 25)),
                  "language": "en"}
        if route_coords:
            # Downsample: no need to send thousands of vertices for a suburban run.
            step = max(1, len(route_coords) // 200)
            params.update({
                "sar_type": "isochrone",
                "route": _encode_polyline(route_coords[::step]),
                "route_geometry": "polyline",
                "time_deviation": max(1, float(time_deviation_mins)),
                "navigation_profile": "driving",
                "origin": f"{route_coords[0][0]},{route_coords[0][1]}",
            })
        elif lat is not None and lon is not None:
            params["proximity"] = f"{lon},{lat}"
        else:
            return []
        resp = requests.get(url, params=params, timeout=8)
        if resp.status_code != 200:
            return []
        out = []
        for f in resp.json().get("features", []):
            props = f.get("properties", {})
            name = props.get("name", "")
            place = props.get("place_formatted", "")
            coords = f.get("geometry", {}).get("coordinates", [])
            if name and coords and len(coords) == 2:
                full_address = f"{name}, {place}".strip(", ")
                storage.set_cached_geocode(full_address, float(coords[1]), float(coords[0]), full_address)
                out.append({"name": name, "address": full_address,
                            "lat": float(coords[1]), "lon": float(coords[0])})
        return out
    except Exception as ex:
        print(f"Mapbox category search exception: {ex}")
        return []
