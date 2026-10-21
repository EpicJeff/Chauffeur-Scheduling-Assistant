import asyncio
import datetime
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


async def migrate_shopping_slug_v2351():
    """`shopping` became `meals`, and every stored SHELF still says the old word.

    The page named Shopping was never about shopping in general — it plans
    dinners and keeps the one standing list a grocery run empties — so it is
    Meals & Groceries now, and Shopping & Lists is every other list a family
    keeps. `/shopping` still redirects, which covers bookmarks and pushes; what
    a redirect cannot reach is the household's own stored vocabulary:

      * `panel_tabs` / `panel_board_order` — the shelf, in the order somebody
        dragged it. An unknown slug is DROPPED by `resolve_tabs`, so without
        this a wall's Meals button silently disappears and reappears at the end
        of the shelf in the default order.
      * `panel_board_hidden` — a board somebody deliberately took OFF the
        shelf. Missing this is worse than the order: the board comes back.
      * `panel_shipped_backgrounds` — the photograph chosen for that board,
        keyed by slug.

    Keyed on app state and idempotent. The old keys are REMOVED rather than
    left beside the new ones: a shelf carrying both would draw two Meals
    buttons the moment `shopping` became a real slug again.
    """
    if storage.get_app_state('shopping_slug_meals_v2351'):
        return
    settings = storage.get_settings() or {}
    touched = []

    def _rename(seq):
        out, seen = [], set()
        for k in seq or []:
            k = 'meals' if k == 'shopping' else k
            if k not in seen:
                seen.add(k)
                out.append(k)
        return out

    for key in ('panel_tabs', 'panel_board_order', 'panel_board_hidden'):
        before = settings.get(key)
        if not isinstance(before, list) or 'shopping' not in before:
            continue
        settings[key] = _rename(before)
        touched.append(key)

    shipped = settings.get('panel_shipped_backgrounds')
    if isinstance(shipped, dict) and 'shopping' in shipped:
        # `setdefault`, so a household that has somehow already chosen a
        # picture for `meals` keeps the one they chose most recently.
        shipped.setdefault('meals', shipped.pop('shopping'))
        shipped.pop('shopping', None)
        settings['panel_shipped_backgrounds'] = shipped
        touched.append('panel_shipped_backgrounds')

    # The marker is set whether or not anything moved: a household with no
    # stored shelf has nothing to migrate and must not be re-checked on every
    # boot for the rest of the install's life.
    storage.set_app_state('shopping_slug_meals_v2351', time.time())
    if touched:
        storage.update_settings(settings)
        logger.info("v2.351.0 shelf: `shopping` became `meals` in "
                    + ", ".join(touched))


def migrate_retired_gemini_models_v2499324():
    """A stored `llm_gemini_model` that names a model Google has withdrawn
    (model_pools.RETIRED_MODELS) is moved to the schema default. The trip
    planner calls that setting directly, outside the pools, so a retired id
    there fails every trip rather than rotating. Idempotent: a live id is
    left alone, and nothing else in settings is touched."""
    from services import storage
    from services.model_pools import RETIRED_MODELS
    from models.schemas import Settings
    settings = storage.get_settings() or {}
    current = settings.get('llm_gemini_model')
    if current in RETIRED_MODELS:
        fallback = Settings.model_fields['llm_gemini_model'].default
        storage.patch_settings({'llm_gemini_model': fallback})
        logger.warning(f"[migrations] llm_gemini_model {current!r} was retired by Google; "
                       f"moved to {fallback!r}")


async def migrate_coverage_asks_v2499308():
    """coverage_asks → asks (the one ledger, spec §2). Idempotent by legacy_id.
    event_id + event_start are the authoritative link; situation_id is set
    only when a finding exists for that exact occurrence. The old table is
    left in place, read-only, for one release of recovery."""
    done = 0
    with storage.db_lock:
        legacy = [dict(r) for r in storage.coverage_asks_table.all()]
    state_map = {'waiting': 'sent', 'covered': 'yes', 'declined': 'no', 'expired': 'expired'}
    for r in legacy:
        if storage.get_ask_by_legacy_id(r['id']):
            continue
        start = None
        try:
            start = datetime.datetime.fromisoformat(
                str(r.get('event_start') or '').replace('Z', '+00:00')).replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
        fp = f"{r.get('event_id')}|{start.timestamp() if start else ''}"
        finding = storage.get_finding_by_identity(f"unassigned:{r.get('event_id')}")
        sid = finding['id'] if finding and finding.get('fingerprint') == fp else None
        state = state_map.get(r.get('state'), 'sent')
        storage.add_ask({
            'legacy_id': r['id'], 'situation_kind': 'finding', 'situation_id': sid,
            'event_id': str(r.get('event_id') or ''), 'event_start': r.get('event_start') or '',
            'event_title': r.get('event_title') or '', 'event_date': r.get('event_date') or '',
            'to_name': r.get('contact_name') or '', 'to_contact_id': r.get('contact_id') or None,
            'to_member_id': None, 'what': f"take {r.get('event_title') or 'the ride'}",
            'channel': 'text', 'asked_by': r.get('asked_by') or '',
            'asked_at': r.get('asked_at') or time.time(), 'sent_at': r.get('asked_at'),
            'state': state, 'nudges_sent': int(r.get('nudges_sent') or 0),
            'rearmed_at': r.get('rearmed_at'), 'answered_at': r.get('resolved_at'),
            'answered_by': r.get('resolved_by') or None,
            'outcome': 'applied' if state == 'yes' else None,
            'applied_at': r.get('resolved_at') if state == 'yes' else None,
            'unlocks': {'action_type': 'assist_assignment',
                        'payload': {'event_id': str(r.get('event_id') or ''),
                                    'contact_id': r.get('contact_id') or '',
                                    'event_title': r.get('event_title') or '',
                                    'event_date': r.get('event_date') or ''},
                        'fingerprint': fp},
            'draft_body': '', 'draft_subject': '', 'draft_source': 'template', 'link': None})
        done += 1
    if done:
        logger.info(f"v2.499.308 coverage_asks migration: {done} asks carried into the ledger")


def migrate_projects_adopt_v2499517():
    """Front door slice 1: every thread, mission and program gets its project."""
    from services import projects
    out = projects.adopt_existing()
    if not out.get('skipped'):
        logger.info(f"[migrations] projects adopted: {out}")


def migrate_project_audiences_v2499():
    """Audience spec ?3: every project onto the shared model, once per row."""
    from services import project_audience
    out = project_audience.convert_all()
    if out['converted']:
        logger.info(f"[migrations] project audiences converted: {out}")


def migrate_drop_piece_kind_links_v2499():
    """Access rule §10.1: drop cross-project and stale home-kind links only."""
    from services import projects
    getters = {'thread': storage.get_thread, 'mission': storage.get_mission,
               'program': storage.get_program}
    with storage.db_lock:
        for project in storage.get_projects():
            pieces = project.get('pieces') or []
            kept = []
            for piece in pieces:
                kind = piece.get('kind')
                if kind in projects.PIECE_HOME_KINDS:
                    record = getters[kind](piece.get('id'))
                    if record is None or (record.get('project_id')
                                          and record['project_id'] != project['id']):
                        continue
                # Keep native and unresolved memberships; these entries drive project views.
                kept.append(piece)
            if len(kept) != len(pieces):
                storage.update_project(project['id'], {'pieces': kept})


def migrate_remove_target_events_v2499():
    """Spec 10.3: retire calendar copies of program target dates, retry failures."""
    from services import calendar
    cal_id = ((storage.get_settings() or {}).get('calendar_ids') or ['primary'])[0]
    for row in storage.get_programs(include_finished=True):
        baseline = dict(row.get('baseline') or {})
        event_id = baseline.get('target_event_id')
        if not event_id:
            continue
        try:
            if not calendar.delete_event(cal_id, event_id):
                continue
        except Exception as exc:
            if getattr(getattr(exc, 'resp', None), 'status', None) not in (404, 410):
                logger.warning(f"Target-event removal will retry for {row['id']}: {exc}")
                continue
        baseline.pop('target_event_id', None)
        emissions = dict(row.get('emissions') or {})
        emissions['event_ids'] = [eid for eid in emissions.get('event_ids') or [] if eid != event_id]
        storage.update_program(row['id'], {'baseline': baseline, 'emissions': emissions})
        with storage.db_lock:
            storage._invalidate_schedule_caches()


def migrate_commitment_sources_v2499():
    """Backfill program provenance, including inactive and paused reservations."""
    for row in storage.get_programs(include_finished=True):
        for cid in (row.get('emissions') or {}).get('commitment_ids') or []:
            commitment = storage.get_protected_commitment(cid)
            if commitment and not commitment.get('source'):
                storage.update_protected_commitment(cid, {'source': {'kind': 'program', 'id': row['id']}})


def migrate_lesson_attempts_paused_v2499():
    """Give back lesson attempts a workflow pause spent (device-found 2026-10-19).

    Until v2.499.593 a background pool answer of `deferred` (llm_budget paused
    the workflow after Gemma 5xx bursts) carried no `transient` flag, so each
    forced sweep during an outage counted one of a slot's attempts and a
    lesson that never ran read "attempts exhausted". A slot whose recorded
    reason is a pause or a deferral, and that holds no script, gets its
    attempts back; real failures keep theirs. Idempotent: a zeroed row is
    left alone.
    """
    from services import storage
    words = ('paused', 'deferred', 'time budget exhausted')
    fixed = 0
    with storage.db_lock:
        for doc in storage.program_lessons_table.all():
            row = dict(doc)
            note = (row.get('note') or '').lower()
            if row.get('scenes') or not int(row.get('attempts') or 0) \
                    or not any(w in note for w in words):
                continue
            storage.program_lessons_table.update({'attempts': 0}, doc_ids=[doc.doc_id])
            fixed += 1
    if fixed:
        logger.info(f"[migrations] gave back attempts on {fixed} paused lesson slot(s)")
    return fixed


def migrate_program_library_v2499():
    """Split each legacy curriculum/run atomically; the binding is the last write."""
    from services import access, library, programs, stages

    converted = 0
    failed = []
    for snapshot in storage.get_programs(include_finished=True):
        try:
            with storage.db_lock, storage.db.transaction():
                # Re-read after acquiring the lock: another invocation may have converted it.
                run = storage.get_program(snapshot['id'])
                if not run or run.get('library_id') or 'phases' not in run or access.gone('program', run):
                    continue
                shape = dict(run.get('shape') or {})
                defaults = programs.clamp_shape(shape)
                for key in ('minutes', 'sessions_per_week'):
                    shape.setdefault(key, defaults[key])
                age = stages.age_of(storage.get_member(run.get('member_id')))
                profile = {'age_band': stages.stage_for_age(age) if age is not None else 'any',
                           'minutes': shape['minutes'], 'sessions_per_week': shape['sessions_per_week'],
                           'assumes': ''}
                curriculum = library.from_curated(run['title'], profile, run,
                                                  run.get('created_by') or run.get('member_id'))
                progress = programs.legacy_library_progress(run, curriculum)
                library_id = storage.add_library_program(curriculum)

                # Map the actual old ordinal (not today's bookmark) to its minted lesson.
                slots = {}
                for raw, phase in zip(run.get('phases') or [], curriculum['phases']):
                    lessons = [l for l in curriculum['lessons'] if l['phase_id'] == phase['id']]
                    for i, lesson in enumerate(lessons):
                        units = raw.get('units') or []
                        number = int(units[i].get('n') or 0) if units else 0
                        slots.setdefault((raw.get('name') or '', number), lesson)
                    # Actual legacy numbers take priority; fill ordinal aliases only
                    # after all real keys, including the missing-n zero key, exist.
                    for i, lesson in enumerate(lessons):
                        slots.setdefault((raw.get('name') or '', i + 1), lesson)
                for script in storage.program_lessons_table.search(storage.Query().program_id == run['id']):
                    if script.get('lesson_id'):
                        continue
                    lesson = slots.get((script.get('phase_name') or '', int(script.get('unit_n') or 0)))
                    if lesson is None:
                        raise ValueError(f"Cannot map legacy script {script['id']} on program {run['id']}")
                    label = str(script.get('session_label') or '')
                    if label and label not in {v.get('label') for v in lesson['variants']}:
                        raise ValueError(f"Cannot map legacy variant {label!r} on program {run['id']}")

                    def rekey(row, lesson_id=lesson['id'], variant_label=label):
                        for key in ('phase_name', 'unit_n', 'session_label'):
                            row.pop(key, None)
                        row.update(lesson_id=lesson_id, variant_label=variant_label)

                    storage.program_lessons_table.update(rekey, doc_ids=[script.doc_id])

                def strip_curriculum(row):
                    for key in ('title', 'source', 'phases'):
                        row.pop(key, None)

                storage.programs_table.update(strip_curriculum, storage.Query().id == run['id'])
                storage.update_program(run['id'], {'shape': shape, 'progress': progress})
                # Keep this a separate dict write: a failed mark rolls everything back.
                storage.programs_table.update({'library_id': library_id}, storage.Query().id == run['id'])
        except Exception:
            # The transaction has rolled back before logging or continuing.
            failed.append(snapshot['id'])
            logger.exception(f"[migrations] program {snapshot['id']} not converted")
            continue
        converted += 1
        # A later row may fail; already committed rows must still refresh readers.
        library._invalidate()
    if converted:
        logger.info(f"[migrations] program library converted: {converted}")
    if failed:
        logger.error(f"[migrations] program library failed ids: {failed}")
    return converted


def migrate_library_scripts_v2499():
    """Every per-run script of a library run goes; the library job rewrites them from public inputs.
    Edited rows are logged by id, never their text. Idempotent."""
    from services import storage
    with storage.db_lock:
        library_runs = {r['id'] for r in storage.programs_table.all() if r.get('library_id')}
        gone = edited = 0
        for doc in storage.program_lessons_table.all():
            if doc.get('program_id') not in library_runs:
                continue
            if doc.get('edited'):
                edited += 1
                logger.info(f"[migrations] library script edit retired: run {doc.get('program_id')} lesson {doc.get('lesson_id')} "
                            f"variant {doc.get('variant_label')!r} scenes {len(doc.get('scenes') or [])} row {doc.get('id')}")
            storage.program_lessons_table.remove(doc_ids=[doc.doc_id])
            gone += 1
    if gone:
        logger.info(f"[migrations] library scripts: {gone} per-run rows retired ({edited} hand-edited)")


def migrate_program_session_ids_v2499():
    """Every logged session gets a stable id so one can be removed by name (programs spec §5.1)."""
    import uuid
    with storage.db_lock, storage.db.transaction():
        if storage.get_app_state('program_session_ids_v2499'):
            return
        for run in storage.get_programs(include_finished=True):
            sessions = run.get('sessions') or []
            if all(s.get('id') for s in sessions):
                continue
            storage.update_program(run['id'], {'sessions': [{**s, 'id': s.get('id') or uuid.uuid4().hex} for s in sessions]})
        storage.set_app_state('program_session_ids_v2499', time.time())


def migrate_library_revision_summary_v2499():
    """Library rows gain a revision counter and lessons a parent-facing summary and origin (programs spec §6)."""
    from services.library import default_summary
    with storage.db_lock, storage.db.transaction():
        if storage.get_app_state('library_revision_summary_v2499'):
            return
        for row in storage.get_library_programs():
            origin = (row.get('source') or {}).get('origin') or 'none'
            lessons = []
            for l in row.get('lessons') or []:
                try:
                    sessions = int(l.get('sessions') or 1)
                except (TypeError, ValueError, OverflowError):
                    sessions = 1
                summary = l.get('summary') or default_summary(l.get('steps'), sessions)
                lessons.append({**l, 'summary': summary, 'origin': l.get('origin') or origin})
            storage.update_library_program(row['id'], {'lessons': lessons, 'revision': int(row.get('revision') or 0)})
        storage.set_app_state('library_revision_summary_v2499', time.time())


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
    try:
        await migrate_coverage_asks_v2499308()
    except Exception as e:
        logger.error(f"Error running coverage asks migration: {e}")
    try:
        migrate_retired_gemini_models_v2499324()
    except Exception as e:
        logger.error(f"Error running retired model migration: {e}")
    # LAST: the two above write media, so let them settle before relocating.
    try:
        await migrate_media_layout_v2660()
    except Exception as e:
        logger.error(f"Error running media layout migration: {e}")
    try:
        await migrate_tile_columns_v21212()
    except Exception as e:
        logger.error(f"Error running tile column migration: {e}")
    try:
        await migrate_shopping_slug_v2351()
    except Exception as e:
        logger.error(f"Error running shopping slug migration: {e}")
    try:
        migrate_projects_adopt_v2499517()
    except Exception as e:
        logger.error(f"Error adopting records into projects: {e}")
    try:
        migrate_project_audiences_v2499()
    except Exception as e:
        logger.error(f"Error converting project audiences: {e}")
    try:
        migrate_drop_piece_kind_links_v2499()
    except Exception as e:
        logger.error(f"Error dropping project piece-kind links: {e}")
    for migrate in (migrate_commitment_sources_v2499, migrate_remove_target_events_v2499):
        try:
            migrate()
        except Exception as e:
            logger.error(f"Error in {migrate.__name__}: {e}")
    try:
        migrate_lesson_attempts_paused_v2499()
    except Exception as e:
        logger.error(f"Error giving back paused lesson attempts: {e}")
    try:
        migrate_program_library_v2499()
    except Exception as e:
        logger.error(f"Error converting program library: {e}")
    try:
        migrate_library_scripts_v2499()
    except Exception as e:
        logger.error(f"Error retiring per-run library scripts: {e}")
    try:
        migrate_program_session_ids_v2499()
    except Exception as e:
        logger.error(f"Error assigning program session ids: {e}")
    try:
        migrate_library_revision_summary_v2499()
    except Exception as e:
        logger.error(f"Error assigning library revisions and summaries: {e}")
