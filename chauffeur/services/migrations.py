import asyncio
import time
from services import storage
from services.maps import search_places
import logging

logger = logging.getLogger(__name__)

async def migrate_trip_metadata_v247():
    logger.info("Starting v2.4.7 POI migration...")
    
    with storage.db_lock:
        all_trips = storage.trip_metadata_table.all()
    
    for trip in all_trips:
        event_id = trip.get("event_id")
        if not event_id:
            continue
            
        updated = False
        
        # Check POIs
        pois = trip.get('pois', [])
        for poi in pois:
            if 'website' not in poi: # If one is missing, they all are
                name = poi.get('name', '')
                location = poi.get('location', '')
                logger.info(f"Backfilling POI: {name} in {location}")
                
                query = f"{name} {location}"
                try:
                    results = await search_places(query)
                    if results and len(results) > 0:
                        best = results[0]
                        poi['website'] = best.get('website')
                        poi['phone_number'] = best.get('phone_number')
                        poi['cuisine'] = best.get('cuisine')
                        poi['internet_access'] = best.get('internet_access')
                        updated = True
                except Exception as e:
                    logger.error(f"Error fetching {name}: {e}")
                    
                await asyncio.sleep(1) # Yield and prevent rate limit
                
        # Check Accommodations
        accs = trip.get('accommodations', [])
        for acc in accs:
            if 'website' not in acc:
                name = acc.get('name', '')
                location = acc.get('location', '')
                logger.info(f"Backfilling Accommodation: {name} in {location}")
                
                query = f"{name} {location}"
                try:
                    results = await search_places(query)
                    if results and len(results) > 0:
                        best = results[0]
                        acc['website'] = best.get('website')
                        acc['phone_number'] = best.get('phone_number')
                        acc['cuisine'] = best.get('cuisine')
                        acc['internet_access'] = best.get('internet_access')
                        updated = True
                except Exception as e:
                    logger.error(f"Error fetching {name}: {e}")
                    
                await asyncio.sleep(1) # Yield and prevent rate limit
                
        if updated:
            logger.info(f"Saving updated trip {event_id}...")
            storage.set_trip_metadata(event_id, trip)
            
    logger.info("Migration v2.4.7 complete!")

async def run_all_migrations():
    """Runs all data migrations in the background after startup"""
    await asyncio.sleep(5) # Let the app start up completely
    try:
        await migrate_trip_metadata_v247()
    except Exception as e:
        logger.error(f"Error running migrations: {e}")
