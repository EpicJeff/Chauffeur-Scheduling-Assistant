from services.travel_api import get_serpapi_key, extract_iata_code, check_for_quota_error, QuotaExceededError
from serpapi import GoogleSearch

def test_flight_schedule():
    api_key = get_serpapi_key()
    if not api_key:
        print("No SerpApi key found.")
        return
        
    params = {
      "engine": "google_flights",
      "departure_id": "RDU",
      "arrival_id": "CDG",
      "outbound_date": "2030-01-05",  # Future date
      "adults": "1",
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
                
                print(f"Departure: {dep_time}")
                print(f"Arrival: {arr_time}")
                print(f"Total Duration: {duration} mins")
            else:
                print("No legs found in best flight.")
        else:
            print("No best flights found.")
    except Exception as e:
        print(f"Error: {e}")

test_flight_schedule()
