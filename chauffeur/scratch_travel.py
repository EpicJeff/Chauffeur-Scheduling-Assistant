import datetime
from zoneinfo import ZoneInfo
import services.maps as maps
from services import storage

def calculate_dynamic_trip_start(base_date_utc, home_loc, dest_loc):
    try:
        travel_time_mins = maps.get_travel_time_minutes(home_loc, dest_loc)
        if travel_time_mins <= 0:
            travel_time_mins = 0
            
        home_tz_str = maps.get_timezone(home_loc)
        home_tz = ZoneInfo(home_tz_str)
        
        # User wakes up and leaves at 8 AM local time on the start day
        leave_time_local = datetime.datetime(
            base_date_utc.year, base_date_utc.month, base_date_utc.day,
            8, 0, 0, tzinfo=home_tz
        )
        
        # Add travel time + 60 minutes for hotel check-in/overhead
        arrival_time_utc = leave_time_local.astimezone(datetime.timezone.utc) + datetime.timedelta(minutes=travel_time_mins + 60)
        
        dest_tz_str = maps.get_timezone(dest_loc)
        
        print(f"Leaving {home_loc} ({home_tz_str}) at {leave_time_local.strftime('%Y-%m-%d %H:%M')}")
        print(f"Travel time: {travel_time_mins} mins (approx {travel_time_mins/60:.1f} hours)")
        print(f"Arriving at {dest_loc} at {arrival_time_utc.astimezone(ZoneInfo(dest_tz_str)).strftime('%Y-%m-%d %H:%M')} ({dest_tz_str})")
        return arrival_time_utc
    except Exception as e:
        print("Error:", e)
        return base_date_utc + datetime.timedelta(hours=9)

print("--- Test 1 ---")
calculate_dynamic_trip_start(datetime.datetime(2030, 1, 5, tzinfo=datetime.timezone.utc), "265 Chestnut Walk Drive, Apex, NC, USA", "Paris, France")

print("\n--- Test 2 ---")
calculate_dynamic_trip_start(datetime.datetime(2030, 1, 5, tzinfo=datetime.timezone.utc), "265 Chestnut Walk Drive, Apex, NC, USA", "Charleston, SC")
