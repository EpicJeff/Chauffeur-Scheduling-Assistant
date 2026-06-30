import sys
sys.path.append('.')
from services import storage
import datetime

cache = storage.get_cached_schedule()
events = cache.get("events", [])
print(f"Loaded {len(events)} events from cache.")

trips = [e for e in events if getattr(e, 'event_type', '') == 'background_trip']
print(f"Trips found: {len(trips)}")
for t in trips:
    print(f"Trip: {t.title} ({t.start} to {t.end})")
    print(f"  Calendar IDs: {getattr(t, 'calendar_ids', [])}")
    print(f"  ID: {t.id}")

# Re-simulate trip_metadata building
trip_metadata = []
for e in trips:
    applicable_entities = set()
    if hasattr(e, 'calendar_ids') and e.calendar_ids:
        for cid in e.calendar_ids:
            applicable_entities.add(f"passenger_{cid}")
    if not applicable_entities:
        applicable_entities.add('global')
    trip_metadata.append({
        "id": e.id,
        "start": e.start,
        "end": e.end,
        "location": e.location,
        "entities": applicable_entities
    })

print("\nSimulating filtering logic:")
for e in events:
    if getattr(e, 'event_type', '') == 'background_trip': continue
    
    all_pax_on_trip = True
    cids = getattr(e, 'calendar_ids', [])
    if not cids:
        all_pax_on_trip = False
    else:
        for cid in cids:
            pax_entity = f"passenger_{cid}"
            on_trip = False
            for tm in trip_metadata:
                if pax_entity in tm['entities'] or 'global' in tm['entities']:
                    if tm['start'] <= e.start and tm['end'] >= e.end:
                        on_trip = True
                        print(f"  -> {e.title} matches trip time for {pax_entity}!")
                        break
            if not on_trip:
                all_pax_on_trip = False
                break
                
    if all_pax_on_trip:
        print(f"FILTERED OUT: {e.title} ({e.start}) - ALL PAX ON TRIP")
    else:
        # Check if it falls inside the trip time AT ALL
        for tm in trip_metadata:
            if tm['start'] <= e.start and tm['end'] >= e.end:
                print(f"KEPT BUT IN TRIP TIME: {e.title} ({e.start}) - cids: {cids}")

