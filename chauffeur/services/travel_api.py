import os
import json
import re
from typing import Optional
from serpapi import GoogleSearch

class QuotaExceededError(Exception):
    pass

def get_serpapi_key() -> Optional[str]:
    """Retrieves SerpApi Key from configuration or environment."""
    api_key = None
    
    # 1. Try Home Assistant options.json
    options_file = '/data/options.json'
    if os.path.exists(options_file):
        try:
            with open(options_file, 'r') as f:
                options = json.load(f)
            api_key = options.get('serpapi_api_key')
        except Exception:
            pass

    # 2. Try environment variables
    if not api_key:
        api_key = os.environ.get('SERPAPI_API_KEY')
        
    # 3. Try serpapi_api_key.txt (for local dev)
    if not api_key:
        api_key_file = os.path.join(os.path.dirname(__file__), '..', 'serpapi_api_key.txt')
        if os.path.exists(api_key_file):
            try:
                with open(api_key_file, 'r') as f:
                    api_key = f.read().strip()
            except Exception:
                pass
                
    return api_key

def extract_iata_code(location_str: str) -> Optional[str]:
    """Attempts to extract a 3-letter IATA code from a string like 'JFK' or 'New York (JFK)'"""
    if not location_str:
        return None
    
    match = re.search(r'\(([A-Z]{3})\)', location_str)
    if match:
        return match.group(1)
        
    match = re.search(r'\b([A-Z]{3})\b', location_str)
    if match:
        return match.group(1)
        
    return None

def check_for_quota_error(results: dict):
    if "error" in results and "exhausted your monthly allowance" in results["error"].lower():
        raise QuotaExceededError("SerpApi quota exceeded.")
    if "error" in results and "Invalid API key" in results["error"]:
        raise Exception("Invalid SerpApi key.")

def get_live_flight_price(origin: str, destination: str, departure_date: str, travelers: int = 1) -> Optional[float]:
    """Fetches the lowest available flight price from Google Flights via SerpApi."""
    api_key = get_serpapi_key()
    if not api_key:
        return None
        
    origin_iata = extract_iata_code(origin)
    dest_iata = extract_iata_code(destination)
    
    if not origin_iata or not dest_iata:
        print(f"Could not extract IATA codes from '{origin}' to '{destination}'")
        return None
        
    params = {
      "engine": "google_flights",
      "departure_id": origin_iata,
      "arrival_id": dest_iata,
      "outbound_date": departure_date,
      "adults": str(travelers),
      "currency": "USD",
      "hl": "en",
      "api_key": api_key
    }
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        check_for_quota_error(results)
        
        # Check best flights first
        best_flights = results.get('best_flights', [])
        if best_flights and best_flights[0].get('price'):
            return float(best_flights[0]['price'])
            
        # Check other flights
        other_flights = results.get('other_flights', [])
        if other_flights and other_flights[0].get('price'):
            return float(other_flights[0]['price'])
            
    except QuotaExceededError:
        raise
    except Exception as e:
        print(f"Error fetching flight price via SerpApi: {e}")
        
    return None

def get_live_hotel_price(location: str, check_in_date: str, check_out_date: str, travelers: int = 1) -> Optional[float]:
    """Fetches the average hotel price for a location from Google Hotels via SerpApi."""
    api_key = get_serpapi_key()
    if not api_key:
        return None
        
    params = {
      "engine": "google_hotels",
      "q": location,
      "check_in_date": check_in_date,
      "check_out_date": check_out_date,
      "adults": str(travelers),
      "currency": "USD",
      "hl": "en",
      "api_key": api_key
    }
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        check_for_quota_error(results)
        
        properties = results.get('properties', [])
        prices = []
        for prop in properties:
            rate = prop.get('rate_per_night', {}).get('lowest')
            if rate:
                # Sometimes it's returned as a string like "$120"
                if isinstance(rate, str):
                    clean_rate = rate.replace('$', '').replace(',', '')
                    try:
                        prices.append(float(clean_rate))
                    except:
                        pass
                else:
                    prices.append(float(rate))
                    
        if prices:
            prices.sort()
            cheapest = prices[:5]
            return sum(cheapest) / len(cheapest)
            
    except QuotaExceededError:
        raise
    except Exception as e:
        print(f"Error fetching hotel price via SerpApi: {e}")
        
    return None

def get_live_flight_schedule(origin: str, destination: str, departure_date: str, travelers: int = 1) -> Optional[dict]:
    """
    Fetches the best outbound flight schedule from Google Flights via SerpApi.
    Returns: {"departure_time": "YYYY-MM-DD HH:MM", "arrival_time": "YYYY-MM-DD HH:MM", "duration_mins": int}
    """
    api_key = get_serpapi_key()
    if not api_key:
        return None
        
    origin_iata = extract_iata_code(origin)
    dest_iata = extract_iata_code(destination)
    
    if not origin_iata or not dest_iata:
        print(f"Could not extract IATA codes from '{origin}' to '{destination}'")
        return None
        
    params = {
      "engine": "google_flights",
      "departure_id": origin_iata,
      "arrival_id": dest_iata,
      "outbound_date": departure_date,
      "type": "2", # One way
      "adults": str(travelers),
      "currency": "USD",
      "hl": "en",
      "api_key": api_key
    }
    
    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        check_for_quota_error(results)
        
        best_flights = results.get('best_flights', [])
        if best_flights:
            flight = best_flights[0]
            legs = flight.get('flights', [])
            if legs:
                first_leg = legs[0]
                last_leg = legs[-1]
                
                dep_time = first_leg.get('departure_airport', {}).get('time')
                arr_time = last_leg.get('arrival_airport', {}).get('time')
                duration = flight.get('total_duration')
                
                if dep_time and arr_time:
                    return {
                        "departure_time": dep_time,
                        "arrival_time": arr_time,
                        "duration_mins": duration
                    }
    except QuotaExceededError:
        raise
    except Exception as e:
        print(f"Error fetching flight schedule via SerpApi: {e}")
        
    return None
