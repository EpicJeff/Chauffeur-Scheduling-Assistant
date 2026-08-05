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
                    results = search_places(query)
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
                    results = search_places(query)
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

async def migrate_geocode_amputation_v2564():
    """One-time heal for the extract_street_address amputation bug: 4-part
    digit-leading addresses (the Mapbox-canonical shape, incl. HOME) lost
    their street line and geocoded to the city center — poisoning the
    geocode cache AND every cached Matrix travel time derived from it.
    Purges sniffably-wrong geocode rows and resets distance/route/schedule
    caches once (app_state-gated); re-priming is a bounded one-time cost."""
    if storage.get_app_state('geocode_amputation_healed'):
        return
    storage.set_app_state('geocode_amputation_healed', time.time())
    removed = await asyncio.to_thread(storage.heal_amputated_geocodes)
    logger.info(f"v2.56.4 geocode heal: purged {removed} suspect geocode rows; "
                f"distance/route/schedule caches reset")


async def migrate_moment_clips_v2590():
    """One-time retranscode of moment clips uploaded before the ffmpeg
    pipeline (v2.59.0): raw phone clips (HEVC .mov especially) don't play on
    Chrome-based wall panels. For every video attachment whose file predates
    the pipeline, transcode to H.264 mp4 under a fresh id and repoint the
    message attachment — renderers pick the new URL up on the next fetch.
    Skips silently when ffmpeg is absent (bare dev env)."""
    if storage.get_app_state('moment_clips_transcoded'):
        return
    storage.set_app_state('moment_clips_transcoded', time.time())
    if not storage._ffmpeg_path():
        return

    def _work():
        import os
        from tinydb import Query
        migrated = 0
        with storage.db_lock:
            msgs = [dict(m) for m in storage.chat_messages_table.all()]
        for m in msgs:
            att = m.get('attachment') or {}
            url = str(att.get('url') or '')
            if att.get('kind') != 'video' or not url.startswith('/api/media/'):
                continue
            old_id = url.rsplit('/', 1)[-1]
            old_path = storage.media_file_path(old_id)
            # Already-pending transcodes (.orig fallback) heal themselves;
            # only settled raw files need the pass.
            if not old_path or old_path.endswith('.orig'):
                continue
            stem = old_id.split('.')[0]
            storage.media_move_into_place(
                old_path, storage.media_write_path(stem + '.orig'))
            storage._transcode_media(stem)   # synchronous here — startup task
            new_id = stem + '.mp4'
            if storage.media_file_path(new_id):
                with storage.db_lock:
                    storage.chat_messages_table.update(
                        {'attachment': {'kind': 'video',
                                        'url': f'/api/media/{new_id}',
                                        'mime': 'video/mp4'}},
                        Query().id == m['id'])
                migrated += 1
        return migrated

    migrated = await asyncio.to_thread(_work)
    if migrated:
        logger.info(f"v2.59.0 moment clips: retranscoded {migrated} pre-pipeline clip(s)")


async def migrate_inline_photos_v2620():
    """One-time move of inline photo moments into the media store (v2.62.0).
    Photos used to be stored base64-inline on the message, which bloated the
    database and made every message scan drag megabytes around — the real
    cost behind the old aggressive downscaling. Rewrites each attachment to
    a media-store URL; the file keeps the exact bytes already sent, so
    nothing is re-encoded or lost. Video posters need no migration (they
    generate on first request)."""
    if storage.get_app_state('inline_photos_filed'):
        return
    storage.set_app_state('inline_photos_filed', time.time())

    def _work():
        from tinydb import Query
        migrated = 0
        with storage.db_lock:
            msgs = [dict(m) for m in storage.chat_messages_table.all()]
        for m in msgs:
            att = m.get('attachment') or {}
            if att.get('kind') != 'photo' or not att.get('data_url'):
                continue
            saved = storage.save_photo_data_url(att['data_url'])
            if not saved:
                continue
            new_att = {'kind': 'photo', 'url': saved['url'], 'mime': saved['mime']}
            for k in ('w', 'h'):
                if att.get(k) is not None:
                    new_att[k] = att[k]
            with storage.db_lock:
                storage.chat_messages_table.update({'attachment': new_att},
                                                   Query().id == m['id'])
            migrated += 1
        return migrated

    migrated = await asyncio.to_thread(_work)
    if migrated:
        logger.info(f"v2.62.0 moments: filed {migrated} inline photo(s) into the media store")


async def migrate_media_layout_v2660():
    """Relocate the media archive into the active root, hash-sharded (v2.66.0).
    Deliberately NOT app-state gated like the others: the media root is a
    SETTING, so this has to run again whenever it changes. It is a directory
    walk with no moves once settled, and `media_read_path` serves from either
    location and either layout throughout — so a run interrupted by a mount
    dropping out leaves nothing broken, just partly moved."""
    res = await asyncio.to_thread(storage.migrate_media_layout)
    logger.info(f"v2.66.0 media layout: moved {res['moved']}, "
                f"failed {res['errors']}, scanned {res['scanned']} "
                f"-> {storage.MEDIA_DIR}")


async def run_all_migrations():
    """Runs all data migrations in the background after startup"""
    await asyncio.sleep(5) # Let the app start up completely
    try:
        await migrate_geocode_amputation_v2564()
    except Exception as e:
        logger.error(f"Error running geocode heal migration: {e}")
    try:
        await migrate_trip_metadata_v247()
    except Exception as e:
        logger.error(f"Error running migrations: {e}")
    try:
        await migrate_moment_clips_v2590()
    except Exception as e:
        logger.error(f"Error running moment clip migration: {e}")
    try:
        await migrate_inline_photos_v2620()
    except Exception as e:
        logger.error(f"Error running inline photo migration: {e}")
    # LAST: the two above write media, so let them settle before relocating.
    try:
        await migrate_media_layout_v2660()
    except Exception as e:
        logger.error(f"Error running media layout migration: {e}")
