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


async def migrate_clip_playback_v21311():
    """One-time re-pass over stored clips that are too heavy for the wall panel.

    The transcode profile before v2.131.1 capped the WIDTH, so every clip shot
    upright — which is most of them — kept its full height, and a portrait
    1080x1920 came through untouched at more than double the pixels of the
    720p landscape clip the cap was written for. Frame rate was never capped at
    all. Those clips are already stored and already juddering on the Pi; the
    new profile only helps the ones uploaded after it.

    So: re-encode in place, and ONLY the ones that need it. The media id and
    its URL do not change (same stem, same .mp4), so nothing referencing the
    moment has to be rewritten and no cache is invalidated beyond the day the
    serving headers already allow. A clip that is already inside the budget is
    left alone — re-encoding it would cost a generation of quality to change
    nothing."""
    if storage.get_app_state('clip_playback_repass'):
        return
    storage.set_app_state('clip_playback_repass', time.time())
    if not (storage._ffmpeg_path() and storage._ffprobe_path()):
        return

    def _needs_repass(path: str) -> bool:
        """Cheap ffprobe: over the pixel budget, over the frame budget, or a
        pixel format no hardware decoder will take. Unreadable = leave alone."""
        import subprocess
        try:
            out = subprocess.run(
                [storage._ffprobe_path(), '-v', 'error', '-select_streams', 'v:0',
                 '-show_entries', 'stream=width,height,pix_fmt',
                 '-of', 'default=noprint_wrappers=1:nokey=1', path],
                check=True, capture_output=True, timeout=30).stdout.decode().split()
        except Exception:
            return False
        if len(out) < 3:
            return False
        try:
            # Coded dimensions, so a rotated clip reads sideways — irrelevant
            # here, because the test is on the LONG side either way.
            long_side = max(int(out[0]), int(out[1]))
        except ValueError:
            return False
        return (long_side > storage._CLIP_LONG_SIDE
                or storage._probe_fps(path) > storage._CLIP_MAX_FPS + 2
                or out[2] != 'yuv420p')

    def _work():
        from tinydb import Query
        seen, redone = set(), 0
        with storage.db_lock:
            msgs = [dict(m) for m in storage.chat_messages_table.all()]
        for m in msgs:
            att = m.get('attachment') or {}
            url = str(att.get('url') or '')
            if att.get('kind') != 'video' or not url.startswith('/api/media/'):
                continue
            media_id = url.rsplit('/', 1)[-1]
            if media_id in seen:
                continue          # the same clip can be posted in two channels
            seen.add(media_id)
            path = storage.media_file_path(media_id)
            # A `.orig` still in place means the first transcode never finished
            # — that one heals itself and must not be raced.
            if not path or path.endswith('.orig') or not _needs_repass(path):
                continue
            stem = media_id.split('.')[0]
            storage.media_move_into_place(
                path, storage.media_write_path(stem + '.orig'))
            storage._transcode_media(stem)   # restores the original on failure
            redone += 1
        return redone

    redone = await asyncio.to_thread(_work)
    if redone:
        logger.info(f"v2.131.1 clip playback: re-encoded {redone} clip(s) "
                    f"to the wall-panel budget")


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
    # Record where the archive lives BEFORE relocating, so the next time
    # media_root changes the old location is still in the lookup.
    storage.register_media_root()
    res = await asyncio.to_thread(storage.migrate_media_layout)
    logger.info(f"v2.66.0 media layout: moved {res['moved']}, "
                f"failed {res['errors']}, scanned {res['scanned']} "
                f"-> {storage.MEDIA_DIR}")


async def migrate_tile_columns_v21212():
    """The board went from a 4-column grid to a 12-column one, so every stored
    tile width has to be multiplied through or the whole layout silently
    shrinks to a third of itself.

    Four columns meant the NARROWEST thing anybody could ask for was a quarter
    of the board. Twelve is Home Assistant's number, for the same reason: it
    divides by 2, 3, 4 and 6, so halves, thirds and quarters all exist. A tile
    that said `cols: 2` meant half the board and must now say 6.

    Rows are untouched — they were already a count of a fixed unit.
    """
    if storage.get_app_state('tile_columns_scaled_v12'):
        return
    storage.set_app_state('tile_columns_scaled_v12', time.time())
    settings = storage.get_settings() or {}
    spans = settings.get('panel_tile_spans') or {}
    if not spans:
        return
    # The board used to be four wide; the factor is how many new columns one
    # old column became. Read from the setting rather than hardcoded, so a
    # household that had already chosen a different number is scaled to THAT.
    try:
        columns = int(settings.get('panel_grid_columns', 12) or 12)
    except (TypeError, ValueError):
        columns = 12
    factor = max(1, columns // 4)
    scaled, touched = {}, 0
    for key, span in spans.items():
        if not isinstance(span, dict):
            continue
        out = dict(span)
        try:
            cols = int(span.get('cols') or 1)
        except (TypeError, ValueError):
            cols = 1
        if cols > 0:
            out['cols'] = min(24, cols * factor)
            touched += 1
        scaled[key] = out
    if touched:
        settings['panel_tile_spans'] = scaled
        storage.update_settings(settings)
        logger.info(f"Scaled {touched} tile width(s) to the 12-column board")


async def migrate_chore_owner_v21730():
    """`Chore.assigned_to` (v2.172.0) already meant OWNER — it survived every
    recurrence and was exempt from the stale-claim release — so it is renamed
    to say so, and `assigned_to` now means the per-instance assignment that
    the same field could not express: work that must happen daily but is only
    sometimes done by the same person.

    Keyed on app state and idempotent. The old field is left in place rather
    than deleted: it costs nothing, and a row that still carries it is how
    anybody debugging an upgraded database can see where the owner came from.
    """
    if storage.get_app_state('chore_owner_migrated_v21730'):
        return
    moved = 0
    with storage.db_lock:
        for c in storage.chores_table.all():
            if c.get('assigned_to') and not c.get('owner'):
                storage.chores_table.update({'owner': c['assigned_to']},
                                            doc_ids=[c.doc_id])
                moved += 1
    storage.set_app_state('chore_owner_migrated_v21730', True)
    if moved:
        logger.info(f"v2.173.0 chores: {moved} assignment(s) became owners")


async def run_all_migrations():
    """Runs all data migrations in the background after startup"""
    await asyncio.sleep(5) # Let the app start up completely
    try:
        await migrate_chore_owner_v21730()
    except Exception as e:
        logger.error(f"Error running chore owner migration: {e}")
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
    try:
        await migrate_clip_playback_v21311()
    except Exception as e:
        logger.error(f"Error running clip playback migration: {e}")
    # LAST: the two above write media, so let them settle before relocating.
    try:
        await migrate_media_layout_v2660()
    except Exception as e:
        logger.error(f"Error running media layout migration: {e}")
    try:
        await migrate_tile_columns_v21212()
    except Exception as e:
        logger.error(f"Error running tile column migration: {e}")
