from tinydb import TinyDB, Query
from typing import List, Optional
import os
import json
import threading
import time

db_lock = threading.RLock()

# CHAUFFEUR_DATA_DIR: test/tooling override so suites run against a temp dir
# instead of the live data files. Unset in normal operation.
if os.environ.get('CHAUFFEUR_DATA_DIR'):
    DB_PATH = os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'db.json')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
elif os.path.exists('/data/options.json'):
    DB_PATH = '/data/chauffeur_db.json'
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'db.json')
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Moment media (Presence slice): video clips live as FILES on the family's
# box — a 15 MB clip can't ride the inline data-URL path photos use.
#
# The archive defaults beside the database, on the add-on's /data volume. That
# is the WRONG disk for a family shooting 4K60 at two games a week: /data is a
# VM's virtual disk, and growing it means touching the VM. `media_root` in the
# add-on options points the archive somewhere else — HA's network storage
# mounts land under /media/<name> or /share/<name>, both of which this add-on
# now maps rw — so the bytes land on whatever big disk the house already has
# and the VM never changes size. Empty (the default) keeps the old location.
_LEGACY_MEDIA_DIR = os.path.join(os.path.dirname(DB_PATH), 'media')
MEDIA_DIR = _LEGACY_MEDIA_DIR


def _configured_media_root() -> Optional[str]:
    """`media_root` from the add-on options, if it names a usable directory.
    A root that is missing or unwritable (a NAS that did not come back after a
    reboot) must NEVER take the archive down: we log it and stay on the legacy
    location, where the older files still are, rather than writing into a path
    that will vanish when the mount reappears underneath us."""
    try:
        with open('/data/options.json') as f:
            root = (json.load(f).get('media_root') or '').strip()
    except Exception:
        root = (os.environ.get('CHAUFFEUR_MEDIA_ROOT') or '').strip()
    if not root:
        return None
    # NEVER mkdir the root itself. A media root is a MOUNT, and creating it
    # turns a typo'd mount name into a plain directory on the VM's own disk
    # that then passes every other check — the archive quietly goes to the one
    # place this option exists to avoid, with no error anywhere. Creating one
    # level is allowed only when the parent is itself a mount (a subfolder of
    # a real share), which is the only legitimate not-yet-there case.
    if not os.path.isdir(root):
        parent = os.path.dirname(root.rstrip('/')) or '/'
        if not (os.path.isdir(parent) and _is_separate_filesystem(parent)):
            print(f"[media] media_root {root!r} does not exist and its parent is "
                  f"not a mount — check the share name is spelled exactly as it "
                  f"appears in Home Assistant. Staying on {_LEGACY_MEDIA_DIR}")
            return None
        try:
            os.makedirs(root, exist_ok=True)
        except OSError as e:
            print(f"[media] media_root {root!r} could not be created ({e}) — "
                  f"staying on {_LEGACY_MEDIA_DIR}")
            return None
    try:
        probe = os.path.join(root, '.chauffeur_write_test')
        with open(probe, 'w') as f:
            f.write('ok')
        os.remove(probe)
    except OSError as e:
        print(f"[media] media_root {root!r} not writable ({e}) — "
              f"staying on {_LEGACY_MEDIA_DIR}")
        return None
    if not _is_separate_filesystem(root):
        # Exists and writable, but on the SAME filesystem as /data — so it is
        # a local folder, not a mount. Works, but buys nothing: the archive is
        # still on the volume you were trying to get it off.
        print(f"[media] WARNING: media_root {root!r} is on the same filesystem "
              f"as the database — it is a local folder, not a mounted share. "
              f"Media will still consume the add-on's data volume.")
    return root


def _is_separate_filesystem(path: str) -> bool:
    """Is this path on a different device than the database? A real network
    mount is; a directory that merely lives under /share or /media is not."""
    try:
        return os.stat(path).st_dev != os.stat(os.path.dirname(DB_PATH)).st_dev
    except OSError:
        return False


MEDIA_DIR = _configured_media_root() or _LEGACY_MEDIA_DIR


# Every root the archive has EVER lived in, oldest last. Populated at startup
# by register_media_root(). Changing media_root used to orphan everything at
# the old location — it dropped out of the lookup, so the files stopped
# resolving AND the migration stopped seeing them, which on a renamed share
# means the entire back catalogue silently disappears while new uploads work.
_MEDIA_ROOT_HISTORY: List[str] = []


def _media_roots() -> List[str]:
    """Every root a file might be in, active first. Historical roots and the
    legacy location stay in the lookup FOREVER, not just during a migration:
    each is a couple of isfile() calls on a miss, and it is what makes both
    moving the archive and CHANGING WHERE IT LIVES safe to interrupt."""
    roots = [MEDIA_DIR]
    seen = {os.path.normpath(MEDIA_DIR)}
    for r in list(_MEDIA_ROOT_HISTORY) + [_LEGACY_MEDIA_DIR]:
        if r and os.path.normpath(r) not in seen:
            seen.add(os.path.normpath(r))
            roots.append(r)
    return roots


def register_media_root():
    """Persist the active root so a later change never orphans what is here
    now. Called at startup, before the layout migration."""
    global _MEDIA_ROOT_HISTORY
    try:
        seen = list(get_app_state('media_roots_seen') or [])
        changed = False
        for r in (MEDIA_DIR, _LEGACY_MEDIA_DIR):
            if r and os.path.normpath(r) not in [os.path.normpath(s) for s in seen]:
                seen.append(r)
                changed = True
        if changed:
            set_app_state('media_roots_seen', seen)
        _MEDIA_ROOT_HISTORY = seen
    except Exception as e:
        print(f"[media] could not record media root history: {e}")


def adopt_media_root(path: str) -> bool:
    """Teach the app about a directory it never recorded — the recovery for a
    root that changed BEFORE history was kept (a renamed share). Returns True
    if it was newly added. The files there resolve immediately; the layout
    migration then relocates them into the active root."""
    global _MEDIA_ROOT_HISTORY
    seen = list(get_app_state('media_roots_seen') or [])
    if os.path.normpath(path) in [os.path.normpath(s) for s in seen]:
        _MEDIA_ROOT_HISTORY = seen
        return False
    seen.append(path)
    set_app_state('media_roots_seen', seen)
    _MEDIA_ROOT_HISTORY = seen
    return True


def _shard(name: str) -> str:
    """'ab/cd' from the id's own leading hex. Sharding by HASH rather than by
    date is what keeps this free: the id is already in every stored
    attachment URL, so a file's bucket is derivable and nothing in the
    database has to be rewritten. Siblings (.orig/.jpg/.tmp.mp4) share the
    stem and therefore land in the same bucket. ~27k files across 256
    directories instead of one, which is the difference between a directory
    listing being instant and being a problem after ten seasons."""
    stem = os.path.splitext(name)[0].split('.')[0]
    if len(stem) >= 4 and all(c in '0123456789abcdef' for c in stem[:4].lower()):
        return os.path.join(stem[:2], stem[2:4])
    return ''


def media_write_path(name: str) -> str:
    """Where a NEW media file goes: active root, sharded, parents created."""
    d = os.path.join(MEDIA_DIR, _shard(name))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, name)


def media_read_path(name: str) -> Optional[str]:
    """Find an existing media file wherever it actually is — sharded or flat,
    new root or legacy. Ordered so the common case (migrated, active root)
    hits first."""
    for root in _media_roots():
        shard = _shard(name)
        for d in ((os.path.join(root, shard), root) if shard else (root,)):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                return p
    # Local scratch last: a just-uploaded clip lives here as {stem}.orig until
    # its transcode lands, and the serving path falls back to it so a moment
    # sent seconds ago is never a 404. Deliberately NOT a media root — the
    # layout migration must never walk working files.
    p = os.path.join(media_scratch_dir(), name)
    return p if os.path.isfile(p) else None


def media_scratch_dir() -> str:
    """Local working space, ALWAYS beside the database and never on the media
    root. ffmpeg writing its output straight onto a CIFS mount is slow and
    fails badly; uploads streaming there hold the mount open for minutes. Both
    write here and move the finished file across."""
    d = os.path.join(os.path.dirname(DB_PATH), 'media_scratch')
    os.makedirs(d, exist_ok=True)
    return d


_MEDIA_FILE_RE = None


def _is_media_filename(name: str) -> bool:
    """A file this app owns: a 32-hex id plus a known extension, including the
    .orig and .tmp working files a pending transcode leaves behind."""
    global _MEDIA_FILE_RE
    if _MEDIA_FILE_RE is None:
        import re
        _MEDIA_FILE_RE = re.compile(
            r'^[a-f0-9]{32}(\.tmp)?\.(mp4|webm|mov|m4v|jpg|png|webp|orig)$')
    return bool(_MEDIA_FILE_RE.match(name or ''))


def migrate_media_layout(batch_limit: int = 0) -> dict:
    """Relocate media into the active root, sharded. Runs in the BACKGROUND
    and is safe to interrupt: `media_read_path` already finds files at either
    location and either layout, so nothing 404s while this walks — and if the
    destination is a mount that drops halfway, the files it has not reached
    are still being served from where they are. Idempotent; a second run over
    a migrated archive is a directory walk and no moves."""
    moved = errors = scanned = 0
    for root in _media_roots():
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                # ONLY our own files. media_root can be a share with other
                # things in it, and a migration that relocated every file it
                # found would rearrange somebody's documents into ab/cd
                # buckets — on their NAS.
                if not _is_media_filename(name):
                    continue
                scanned += 1
                src = os.path.join(dirpath, name)
                dst = os.path.join(MEDIA_DIR, _shard(name), name)
                if os.path.normpath(src) == os.path.normpath(dst):
                    continue
                if os.path.exists(dst):
                    continue     # already there; leave the stray alone
                try:
                    media_move_into_place(src, dst)
                    moved += 1
                except OSError as e:
                    errors += 1
                    if errors < 5:
                        print(f"[media] could not relocate {name}: {e}")
                if batch_limit and moved >= batch_limit:
                    return {'scanned': scanned, 'moved': moved, 'errors': errors,
                            'complete': False}
    # ALWAYS log, even a no-op. Gating this on moved-or-errors made "the
    # migration found nothing to do" and "the migration never ran" look
    # identical from the log, which is exactly the question you have after
    # pointing media_root somewhere new.
    print(f"[media] layout migration: {moved} moved, {errors} failed, "
          f"{scanned} scanned -> {MEDIA_DIR}")
    return {'scanned': scanned, 'moved': moved, 'errors': errors, 'complete': True}


def scratch_free_bytes() -> int:
    """Free space where uploads and transcodes work. This is the add-on's own
    volume — /data on the VM's virtual disk — NOT the media root. Filling it
    does not just fail an upload: Home Assistant shares that disk, and it
    fails badly when it runs out."""
    import shutil
    try:
        return shutil.disk_usage(media_scratch_dir()).free
    except OSError:
        return 0


def media_move_into_place(src: str, dst: str):
    """os.replace is atomic but same-filesystem only, and the media root may
    be a mount. Fall back to a cross-device move."""
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError:
        import shutil
        shutil.move(src, dst)

from tinydb.storages import Storage, touch
class AtomicJSONStorage(Storage):
    def __init__(self, path: str, create_dirs=False, encoding=None, **kwargs):
        super().__init__()
        self.path = path
        self.encoding = encoding
        self.kwargs = kwargs
        touch(path, create_dirs=create_dirs)

    def read(self) -> Optional[dict]:
        if not os.path.exists(self.path):
            return None
        size = os.path.getsize(self.path)
        if not size:
            return None
        with open(self.path, 'r', encoding=self.encoding) as handle:
            return json.load(handle)

    def write(self, data: dict):
        import uuid
        temp_path = self.path + '.' + str(uuid.uuid4()) + '.tmp'
        with open(temp_path, 'w', encoding=self.encoding) as handle:
            json.dump(data, handle, **self.kwargs)
            handle.flush()
            os.fsync(handle.fileno())
        import time
        for i in range(20):
            try:
                os.replace(temp_path, self.path)
                break
            except PermissionError:
                if i == 19:
                    raise
                time.sleep(0.05)

    def close(self) -> None:
        pass


def fix_corrupted_db(path):
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
        if not content:
            return
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            if "Extra data" in str(e):
                decoder = json.JSONDecoder()
                obj, idx = decoder.raw_decode(content)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(obj, f)
    except Exception:
        pass

# Storage engine toggle (docs/sqlite_migration_design.md). 'tinydb' is the
# legacy escape hatch; it will be removed one release after the swap soaks.
BACKEND = os.environ.get('CHAUFFEUR_STORAGE', 'sqlite').strip().lower()
if BACKEND not in ('tinydb', 'sqlite'):
    print(f"Unknown CHAUFFEUR_STORAGE={BACKEND!r}, falling back to tinydb")
    BACKEND = 'tinydb'

SQLITE_PATH = os.path.join(os.path.dirname(DB_PATH), 'chauffeur.sqlite3')

with db_lock:
    ROUTES_DB_PATH = os.path.join(os.path.dirname(DB_PATH), 'routes_cache.json')
    if BACKEND == 'sqlite':
        from services.storage_sqlite import SqliteStorage, migrate_from_tinydb
        if not os.path.exists(SQLITE_PATH):
            # first boot on sqlite: migrate legacy TinyDB files if present
            # (renames them to *.pre-sqlite.bak); fresh install -> empty DB
            fix_corrupted_db(DB_PATH)
            fix_corrupted_db(ROUTES_DB_PATH)
            migrate_from_tinydb(SQLITE_PATH, DB_PATH, ROUTES_DB_PATH)
        db = SqliteStorage(SQLITE_PATH)
        routes_db = db  # route_geometry lives in the same SQLite file
    else:
        fix_corrupted_db(DB_PATH)
        db = TinyDB(DB_PATH, storage=AtomicJSONStorage)
    drivers_table = db.table('drivers')
    rules_table = db.table('rules')
    priority_rules_table = db.table('priority_rules')
    overrides_table = db.table('overrides')
    cache_table = db.table('schedule_cache')
    # Trips as /api/trips last computed them. That endpoint reads Google live,
    # which a wall panel polling every 60 seconds must never do — so the
    # answer is written down each time somebody loads the trips page and the
    # home board reads the snapshot instead.
    trips_cache_table = db.table('trips_cache')
    custom_schedules_table = db.table('custom_schedules')
    daily_schedules_table = db.table('daily_schedules')
    settings_table = db.table('settings')
    distance_cache_table = db.table('distance_cache')

    geocode_cache_table = db.table('geocode_cache')
    api_usage_table = db.table('api_usage')
    passengers_table = db.table('passengers')
    telemetry_table = db.table('telemetry')
    push_subscriptions_table = db.table('push_subscriptions')
    drive_status_table = db.table('drive_status')
    member_positions_table = db.table('member_positions')
    live_traffic_table = db.table('live_traffic_cache')
    pending_notifications_table = db.table('pending_notifications')
    event_configs_table = db.table('event_configs')
    api_requests_log_table = db.table('api_requests_log')
    conversations_table = db.table('conversations')
    errands_table = db.table('errands')
    errand_rules_table = db.table('errand_rules')
    trip_metadata_table = db.table('trip_metadata')
    app_state_table = db.table('app_state')
    members_table = db.table('members')
    chat_channels_table = db.table('chat_channels')
    chat_messages_table = db.table('chat_messages')
    channel_reads_table = db.table('channel_reads')
    member_tokens_table = db.table('member_tokens')
    # Auth arc S3: single-use, expiring links for invite / verify / reset. A
    # table rather than a column on the member, because a person can have an
    # invite and a reset outstanding at once and a column would silently
    # overwrite one with the other.
    auth_links_table = db.table('auth_links')
    # Lockout counters that outlive a rebuild (auth arc S4).
    rate_limits_table = db.table('rate_limits')
    # Devices a PIN may re-open (auth arc S5); panels join them in S6.
    trusted_devices_table = db.table('trusted_devices')
    # Screens asking to be let in, waiting on a parent (auth arc S6).
    pending_pairings_table = db.table('pending_pairings')
    chores_table = db.table('chores')
    points_ledger_table = db.table('points_ledger')
    routines_table = db.table('routines')
    routine_checks_table = db.table('routine_checks')
    # Per-step ticks inside a routine item, keyed (routine_id, step_id,
    # date_str). Separate from routine_checks on purpose: streaks, day
    # bonuses and XP all read routine_checks, and a step row must never
    # count as an item completion.
    routine_step_checks_table = db.table('routine_step_checks')
    kid_tasks_table = db.table('kid_tasks')
    optional_decisions_table = db.table('optional_decisions')
    # Canceled occurrences. Unlike decisions these are NEVER pruned: the
    # record is the reschedule memory ("canceled, coach sick") and the
    # tombstone that keeps a resurrected ICS event canceled. Restoring sets
    # restored_at rather than deleting — the history is the point.
    event_cancellations_table = db.table('event_cancellations')
    shopping_lists_table = db.table('shopping_lists')
    shopping_items_table = db.table('shopping_items')
    meals_table = db.table('meals')
    leftovers_table = db.table('leftovers')
    dishes_table = db.table('dishes')
    dish_categories_table = db.table('dish_categories')
    plates_table = db.table('plates')
    walmart_items_table = db.table('walmart_items')
    meal_rules_table = db.table('meal_rules')
    occasions_table = db.table('occasions')
    occasion_guests_table = db.table('occasion_guests')
    rewards_table = db.table('rewards')
    redemptions_table = db.table('redemptions')
    pool_contributions_table = db.table('pool_contributions')
    ics_feeds_table = db.table('ics_feeds')
    event_proposals_table = db.table('event_proposals')
    agent_action_proposals_table = db.table('agent_action_proposals')
    ingest_log_table = db.table('ingest_log')
    prep_kits_table = db.table('prep_kits')
    prep_status_table = db.table('prep_status')
    packing_claims_table = db.table('packing_claims')
    daily_stats_table = db.table('daily_stats')
    # Live tallies of things that happen DURING a day (scrambles, mostly).
    # daily_stats is written once at 21:00, so anything counted as it happens
    # needs its own row or the nightly write clobbers it.
    day_counters_table = db.table('day_counters')
    cars_table = db.table('cars')
    status_protocols_table = db.table('status_protocols')
    status_days_table = db.table('status_days')
    assist_contacts_table = db.table('assist_contacts')
    # Active coverage only. Spent instance rows move to `assist_history`, which
    # is append-only and never read by a solve — the record survives forever
    # without the hot path paying for it.
    assist_assignments_table = db.table('assist_assignments')
    assist_history_table = db.table('assist_history')
    household_tasks_table = db.table('household_tasks')
    threads_table = db.table('threads')
    requests_table = db.table('requests')
    solve_packs_table = db.table('solve_packs')
    shift_refusals_table = db.table('shift_refusals')
    deals_table = db.table('deals')
    protected_exceptions_table = db.table('protected_exceptions')
    protected_commitments_table = db.table('protected_commitments')
    # Needs You (findings arc). A watcher finding with a LIFECYCLE: it opens
    # when the sweep sees the condition and closes when the sweep stops seeing
    # it, which is how a thing handled somewhere else in the app stops being
    # asked about. Identity is (kind, subject) so the same trouble is one row
    # across days, unlike the dated notify markers in app_state.
    findings_table = db.table('findings')
    # An ask that is out with a human (findings arc, slice 2). The reply comes
    # back as a text message the app cannot read, so the ASK is what the app
    # holds: state, and the nudges that turn a forgotten conversation into one
    # lock-screen tap.
    coverage_asks_table = db.table('coverage_asks')
    mind_noticings_table = db.table('mind_noticings')
    mind_insights_table = db.table('mind_insights')
    # Per-member music (favorites + recently chosen). OURS on purpose: Music
    # Assistant's lead has declined per-user libraries outright — MA 2.7 user
    # profiles scope providers and speakers, favourites stay one shared pile.
    # So the member-shaped shelf lives here, keyed by member_id + uri.
    # Avatar unlocks: APPEND-ONLY. A row exists or the piece is locked.
    # Never a derived set -- a cosmetic that revokes itself is the worst
    # thing a cosmetic system can do, and the streak bug proved we can
    # lose a value that only ever looked monotonic.
    avatar_unlocks_table = db.table('avatar_unlocks')
    # Pets. A pet is never deleted by the app -- retiring sets active=False so
    # the record outlives the fashion (pets arc rule 3). Deleting one is a
    # deliberate act by its owner or a parent, never a side effect.
    pets_table = db.table('pets')
    # Pet XP: APPEND-ONLY, and deliberately a SEPARATE ledger from points.
    # Points redeem for real money; xp buys nothing outside the game and
    # NOTHING converts between them in either direction. Sharing one ledger
    # would mean a kid choosing between levelling their critter and the family
    # movie-night pool, and would let battle winnings print money.
    pet_xp_ledger_table = db.table('pet_xp_ledger')
    # Battles. What is stored is the SEED and the two combatants that went in,
    # never the frames -- `pet_battle.resolve` is a pure function of exactly
    # those, so a replay reconstructs on any device, at any time, from about a
    # kilobyte.
    pet_battles_table = db.table('pet_battles')
    # Challenges between family members. A fight needs the other child's YES
    # before it happens -- a sibling must never be dragged into a battle, or
    # losing becomes a thing done TO you.
    pet_challenges_table = db.table('pet_challenges')
    music_favorites_table = db.table('music_favorites')
    music_recent_table = db.table('music_recent')

    if BACKEND != 'sqlite':
        fix_corrupted_db(ROUTES_DB_PATH)
        routes_db = TinyDB(ROUTES_DB_PATH, storage=AtomicJSONStorage)
    route_geometry_cache_table = routes_db.table('route_geometry')

def migrate_passengers_from_settings():
    with db_lock:
        settings_docs = settings_table.all()
        if not settings_docs:
            return
        
        settings = settings_docs[0]
        passenger_cals = settings.get('passenger_calendar_ids', [])
        metadata = settings.get('calendar_metadata', {})
        
        if not passenger_cals:
            return
            
        existing_passengers = passengers_table.all()
        existing_hashtags = {p.get('hashtag') for p in existing_passengers if p.get('hashtag')}
        
        for cal_id in passenger_cals:
            already_migrated = False
            for p in existing_passengers:
                if cal_id in p.get('calendar_ids', []):
                    already_migrated = True
                    break
            if already_migrated:
                continue
                
            meta = metadata.get(cal_id, {})
            name = meta.get('summary', cal_id)
            
            base_hashtag = '#' + ''.join(c.lower() for c in name if c.isalnum())
            if not base_hashtag or base_hashtag == '#':
                base_hashtag = '#passenger'
                
            hashtag = base_hashtag
            counter = 1
            while hashtag in existing_hashtags:
                hashtag = f"{base_hashtag}{counter}"
                counter += 1
                
            new_passenger = {
                'name': name,
                'hashtag': hashtag,
                'calendar_ids': [cal_id]
            }
            
            passengers_table.insert(new_passenger)
            existing_hashtags.add(hashtag)
            existing_passengers.append(new_passenger)
            
        # Remove passenger_calendar_ids so we don't migrate again
        settings.pop('passenger_calendar_ids', None)
        settings_table.update(settings, doc_ids=[settings.doc_id])

migrate_passengers_from_settings()

def migrate_duplicate_rules():
    with db_lock:
        rules = rules_table.all()
        for r in rules:
            if r.get('constraint_type') == 'mutually_exclusive':
                r['constraint_type'] = 'duplicate'
                r['duplicate_action'] = 'schedule_one'
                rules_table.update(r, doc_ids=[r.doc_id])
            elif r.get('constraint_type') == 'ignore_mutually_exclusive':
                r['constraint_type'] = 'duplicate'
                r['duplicate_action'] = 'schedule_all'
                rules_table.update(r, doc_ids=[r.doc_id])

migrate_duplicate_rules()

def ensure_members():
    """Family-member overlay: one record per human, linking legacy driver and
    passenger identities (which remain the solver's source of truth).
    Idempotent — re-run after driver/passenger adds to fill gaps. Passengers
    merge onto same-named members; passenger docs that predate the 'id'
    field get one backfilled. Never deletes or rewrites anything else."""
    import uuid as _uuid
    import time
    with db_lock:
        members = [dict(m) for m in members_table.all()]
        linked_drivers = {m.get('driver_id') for m in members if m.get('driver_id')}
        linked_passengers = {m.get('passenger_id') for m in members if m.get('passenger_id')}
        by_name = {}
        for m in members:
            by_name.setdefault((m.get('name') or '').strip().lower(), m)

        def new_member(name, **overrides):
            member = {
                'id': _uuid.uuid4().hex,
                'name': name,
                'color_code': '#3b82f6',
                'avatar': None,
                'bio': '',
                'can_drive': False,
                'is_child': False,
                'role': 'adult',
                'driver_id': None,
                'passenger_id': None,
                'calendar_ids': [],
                'ha_person_entity': None,
                'notify_service': None,
                'media_player_entity': None,
                'pin_hash': None,
                'pin_salt': None,
                'created_at': time.time(),
            }
            member.update(overrides)
            if member.get('is_child'):
                member['role'] = 'child'
            members_table.insert(member)
            by_name.setdefault(member['name'].strip().lower(), member)
            return member

        for d in drivers_table.all():
            d_id = d.get('id')
            if not d_id or d_id in linked_drivers:
                continue
            name = (d.get('name') or '').strip()
            existing = by_name.get(name.lower()) if name else None
            if existing is not None and not existing.get('driver_id'):
                # Same-named member without a driving link (e.g. added via
                # "+ Add a Person" or passenger-first): link, don't duplicate.
                members_table.update(
                    {'driver_id': d_id, 'can_drive': not d.get('is_disabled', False)},
                    Query().id == existing['id'])
                existing['driver_id'] = d_id
            else:
                new_member(
                    name or d_id,
                    color_code=d.get('color_code') or '#3b82f6',
                    can_drive=not d.get('is_disabled', False),
                    driver_id=d_id,
                )
            linked_drivers.add(d_id)

        for p in passengers_table.all():
            p_id = p.get('id')
            if not p_id:
                p_id = _uuid.uuid4().hex
                passengers_table.update({'id': p_id}, doc_ids=[p.doc_id])
            if p_id in linked_passengers:
                continue
            name = (p.get('name') or '').strip()
            existing = by_name.get(name.lower()) if name else None
            if existing is not None and not existing.get('passenger_id'):
                members_table.update({'passenger_id': p_id}, Query().id == existing['id'])
                existing['passenger_id'] = p_id
            else:
                new_member(name or p_id, is_child=True, passenger_id=p_id)
            linked_passengers.add(p_id)

ensure_members()

def ensure_member_roles():
    """Backfill `role` on members created before the role field existed:
    is_child -> child, everyone else -> adult. Parents are promoted manually
    in Config -> Family. Idempotent."""
    with db_lock:
        for m in members_table.all():
            if not m.get('role'):
                members_table.update(
                    {'role': 'child' if m.get('is_child') else 'adult'},
                    doc_ids=[m.doc_id])

ensure_member_roles()

def ensure_member_colors():
    """One-time seed of child identity colors. Person colors on the calendar
    used to be hash-assigned from the Google calendar id (see the PALETTE in
    calendar.get_calendar_metadata); now the member's color_code is the single
    source of truth everywhere. Children created passenger-first all sat at
    the default blue, so without seeding the switch would render every kid
    identical — adopt the hash color each kid was already showing. Adults
    chose their colors (inherited from the driver record at member creation)
    and are never touched. The color_seeded stamp makes this strictly
    one-shot: a child who later deliberately picks the default blue is not
    re-seeded on restart."""
    PALETTE = ["#3B82F6", "#10B981", "#8B5CF6", "#EC4899",
               "#14B8A6", "#F97316", "#06B6D4", "#84CC16"]
    with db_lock:
        pax_by_id = {p.get('id'): p for p in passengers_table.all()}
        for m in members_table.all():
            if m.get('color_seeded'):
                continue
            updates = {'color_seeded': True}
            is_child = m.get('role') == 'child' or m.get('is_child')
            if is_child and (m.get('color_code') or '').lower() == '#3b82f6':
                p = pax_by_id.get(m.get('passenger_id')) or {}
                cals = p.get('calendar_ids') or []
                if cals:
                    updates['color_code'] = PALETTE[sum(ord(c) for c in cals[0]) % len(PALETTE)]
            members_table.update(updates, doc_ids=[m.doc_id])

ensure_member_colors()

def _mirror_calendars_to_links(driver_id, passenger_id, cal_ids) -> bool:
    """Write a person's calendar list down onto their driver/passenger records.

    Those two fields are MIRRORS, not inputs: the member owns the list, and
    everything downstream (the solver's fetch set, matcher.py's ~20 reads of
    passenger.calendar_ids, the kid day view) keeps reading the records it
    always read. Caller holds db_lock. Returns True if anything moved."""
    changed = False
    if driver_id:
        for d in drivers_table.search(Query().id == driver_id):
            if (d.get('calendar_ids') or []) != list(cal_ids):
                drivers_table.update({'calendar_ids': list(cal_ids)}, doc_ids=[d.doc_id])
                changed = True
    if passenger_id:
        for p in passengers_table.search(Query().id == passenger_id):
            if (p.get('calendar_ids') or []) != list(cal_ids):
                passengers_table.update({'calendar_ids': list(cal_ids)}, doc_ids=[p.doc_id])
                changed = True
    return changed


def ensure_member_calendars():
    """Lift calendars from the driver/passenger records onto the person.

    Calendars used to live only on Driver and Passenger, which meant a person
    with neither profile could not have one at all — no presence on the family
    calendar, no way to be seen without being enrolled in the solver. The
    member now owns `calendar_ids`; this migrates existing setups by unioning
    each link's list upward, then mirroring the result back down.

    Runs the union every boot rather than once, so a legacy write straight to a
    driver/passenger record self-heals into the person's list instead of
    silently diverging. Idempotent."""
    with db_lock:
        drivers = {d.get('id'): dict(d) for d in drivers_table.all()}
        pax = {p.get('id'): dict(p) for p in passengers_table.all()}
        for m in members_table.all():
            member = dict(m)
            merged = [c for c in (member.get('calendar_ids') or []) if c and c.strip()]
            before = list(merged)
            for rec in (drivers.get(member.get('driver_id')),
                        pax.get(member.get('passenger_id'))):
                if not rec:
                    continue
                for c in (rec.get('calendar_ids') or []):
                    if c and c.strip() and c not in merged:
                        merged.append(c)
            if merged != before:
                members_table.update({'calendar_ids': merged}, doc_ids=[m.doc_id])
            _mirror_calendars_to_links(member.get('driver_id'),
                                       member.get('passenger_id'), merged)

ensure_member_calendars()

def set_member_calendars(member_id: str, cal_ids) -> bool:
    """The one place calendars are set. Writes the person's list and rewrites
    their driver/passenger mirrors to match, then drops the schedule caches —
    the set of calendars fetched is a solver input."""
    clean, seen = [], set()
    for c in (cal_ids or []):
        c = (c or '').strip()
        if c and c not in seen:
            seen.add(c)
            clean.append(c)
    with db_lock:
        res = members_table.search(Query().id == member_id)
        if not res:
            return False
        member = dict(res[0])
        prior = member.get('calendar_ids') or []
        members_table.update({'calendar_ids': clean}, Query().id == member_id)
        moved = _mirror_calendars_to_links(member.get('driver_id'),
                                           member.get('passenger_id'), clean)
        if moved or prior != clean:
            mark_all_daily_schedules_dirty()
            cache_table.truncate()
    return True

def ensure_family_channel():
    """Singleton all-family chat channel (kind='family', empty member_ids =
    implicitly everyone). Idempotent."""
    import uuid as _uuid
    import time
    with db_lock:
        if chat_channels_table.search(Query().kind == 'family'):
            return
        chat_channels_table.insert({
            'id': _uuid.uuid4().hex,
            'kind': 'family',
            'member_ids': [],
            'dm_key': None,
            'event_id': None,
            'event_end': None,
            'title': 'Family',
            'created_at': time.time(),
            'archived': False,
        })


# Fixed id for the Argyle assistant, the system member that agent chat replies
# are posted as. `system: True` lets the UI exclude it from the human family
# roster while still resolving "Argyle" as a message sender name.
ARGYLE_MEMBER_ID = "argyle"


def ensure_argyle_member() -> dict:
    """Idempotently create + return the Argyle system member."""
    import time
    with db_lock:
        res = members_table.search(Query().id == ARGYLE_MEMBER_ID)
        if res:
            return dict(res[0])
        member = {
            'id': ARGYLE_MEMBER_ID,
            'name': 'Argyle',
            'role': 'assistant',
            'is_child': False,
            'system': True,
            'driver_id': None,
            'passenger_id': None,
            'created_at': time.time(),
        }
        members_table.insert(member)
        return member

ensure_family_channel()

def stamp_member_on_push_subscriptions():
    """One-time enrichment: legacy push subscription rows know only driver_id;
    stamp the linked member_id so messaging can target members. Idempotent."""
    with db_lock:
        for sub in push_subscriptions_table.all():
            if sub.get('member_id') or not sub.get('driver_id'):
                continue
            member = members_table.search(Query().driver_id == sub['driver_id'])
            if member:
                push_subscriptions_table.update(
                    {'member_id': member[0]['id']}, doc_ids=[sub.doc_id])

stamp_member_on_push_subscriptions()

def cleanup_corrupted_travel_times():
    try:
        with db_lock:
            QueryObj = Query()
            # Remove any cached travel time >= 120 minutes (like the corrupted 999 values)
            distance_cache_table.remove(QueryObj.minutes >= 120)
    except Exception as e:
        print(f"Skipping travel time cleanup due to db lock/file contention: {e}")

cleanup_corrupted_travel_times()

# Geocode Cache
def mark_all_daily_schedules_dirty():
    # One update for every row, not one per row: TinyDB serializes the whole
    # database to disk on each write, so the per-row loop this replaced cost
    # ~9s for 71 rows against a 4.4MB db.json - on the request path of every
    # event-config save.
    with db_lock:
        daily_schedules_table.update({'events_hash': 'DIRTY'})

def clear_schedule_caches():
    with db_lock:
        custom_schedules_table.truncate()
        daily_schedules_table.truncate()
        cache_table.truncate()
        distance_cache_table.truncate()
        global _distance_mem_cache
        _distance_mem_cache = None
        geocode_cache_table.truncate()

def purge_poisoned_caches():
    # Remove only poisoned entries to avoid wiping thousands of legitimate caches on startup
    try:
        with db_lock:
            distance_cache_table.remove(Query().minutes == 15)
            geocode_cache_table.remove(Query().lat == 0.0)
            global _distance_mem_cache
            _distance_mem_cache = None
    except Exception as e:
        print(f"Skipping poisoned caches cleanup due to db lock/file contention: {e}")

purge_poisoned_caches()

def get_cached_geocode(address: str):
    with db_lock:
        res = geocode_cache_table.search(Query().address == address.strip().lower())
        if res:
            record = res[0]
            lat = record.get('lat')
            lon = record.get('lon')
            try:
                float(lat)
                float(lon)
                return record
            except (ValueError, TypeError):
                print(f"Deleting corrupt geocode cache entry for: {address} (lat={lat}, lon={lon})")
                geocode_cache_table.remove(Query().address == address.strip().lower())
        return None

def set_cached_geocode(address: str, lat: float, lon: float, display_name: str = "",
                       precision: str = 'exact'):
    """precision: 'exact' (street-level, final) | 'city' (city/state fallback
    — reusable but RETRYABLE, never a permanent pin) | 'failed'. ts enables
    the daily retry of non-exact entries (maps._usable_cached)."""
    import time
    try:
        lat = float(lat)
        lon = float(lon)
    except (ValueError, TypeError):
        print(f"Error: Refusing to cache invalid coordinates for {address}: lat={lat}, lon={lon}")
        return

    with db_lock:
        geocode_cache_table.upsert({
            'address': address.strip().lower(),
            'lat': lat,
            'lon': lon,
            'display_name': display_name,
            'precision': precision,
            'ts': time.time(),
        }, Query().address == address.strip().lower())

def delete_cached_geocode(address: str):
    """Purge an address's cached geocode — used when home_location changes so
    the new address always gets a fresh street-level lookup."""
    with db_lock:
        geocode_cache_table.remove(Query().address == address.strip().lower())

def heal_amputated_geocodes() -> int:
    """One-time v2.56.4 migration (main startup, app_state-gated).
    extract_street_address used to amputate the street line from 4-part
    digit-leading addresses (the Mapbox-canonical shape), so geocodes — and
    every Matrix travel time derived from them — could silently be
    city-center. Remove geocode rows whose address starts with a house
    number the display_name doesn't echo (poisoned or failed), and reset
    the distance/route/schedule caches so durations re-derive from healed
    coordinates. Matrix re-priming is a bounded one-time cost; wrong travel
    times forever is not."""
    import re
    with db_lock:
        removed = 0
        for r in geocode_cache_table.all():
            m = re.match(r'^\s*(\d+)\b', r.get('address') or '')
            if m and m.group(1) not in (r.get('display_name') or ''):
                geocode_cache_table.remove(doc_ids=[r.doc_id])
                removed += 1
        distance_cache_table.truncate()
        route_geometry_cache_table.truncate()
        _invalidate_schedule_caches()
        return removed

_distance_mem_cache = None

def _init_distance_mem_cache():
    global _distance_mem_cache
    if _distance_mem_cache is None:
        _distance_mem_cache = {}
        for row in distance_cache_table.all():
            o = row.get('origin', '')
            d = row.get('destination', '')
            if o and d:
                _distance_mem_cache[(o, d)] = row

# A cached duration of -1 means "we tried and failed to route this pair" (bad
# address, API outage). It suppresses retry storms that would burn API quota,
# but it must expire: the usual cause is transient, and callers on the
# ignore_age path would otherwise treat one bad afternoon as permanent truth.
UNROUTABLE = -1
UNROUTABLE_TTL_MINS = 24 * 60

def get_cached_travel_time(origin: str, destination: str, max_age_mins: int = 10, ignore_age: bool = False) -> Optional[int]:
    if not origin or not destination:
        return None
    import time
    orig_clean = origin.strip().lower()
    dest_clean = destination.strip().lower()
    with db_lock:
        _init_distance_mem_cache()
        cached_data = _distance_mem_cache.get((orig_clean, dest_clean))
        if cached_data:
            timestamp = cached_data.get('timestamp', 0)
            age_secs = time.time() - timestamp
            duration = cached_data.get('duration_mins', cached_data.get('minutes'))
            if duration == UNROUTABLE:
                # Always age-checked, even when ignore_age is set.
                if age_secs > UNROUTABLE_TTL_MINS * 60:
                    return None
                return duration
            if ignore_age or age_secs <= max_age_mins * 60:
                return duration
        return None

def set_cached_travel_time(origin: str, destination: str, duration_mins: int):
    if not origin or not destination:
        return
    import time
    orig_clean = origin.strip().lower()
    dest_clean = destination.strip().lower()
    with db_lock:
        _init_distance_mem_cache()
        QueryObj = Query()
        row = {
            'origin': orig_clean,
            'destination': dest_clean,
            'duration_mins': duration_mins,
            'timestamp': time.time()
        }
        _distance_mem_cache[(orig_clean, dest_clean)] = row
        distance_cache_table.upsert(row, (QueryObj.origin == orig_clean) & (QueryObj.destination == dest_clean))

def set_cached_travel_times_bulk(entries: List[dict]):
    if not entries: return
    import time
    with db_lock:
        _init_distance_mem_cache()
        rows_to_insert = []
        for entry in entries:
            origin = entry.get('origin')
            destination = entry.get('destination')
            duration_mins = entry.get('duration_mins')
            if not origin or not destination: continue
            
            orig_clean = origin.strip().lower()
            dest_clean = destination.strip().lower()
            
            row = {
                'origin': orig_clean,
                'destination': dest_clean,
                'duration_mins': duration_mins,
                'timestamp': time.time()
            }
            _distance_mem_cache[(orig_clean, dest_clean)] = row
            rows_to_insert.append(row)
            
        if rows_to_insert:
            # Note: For simplicity and speed in bulk caching, we just append (insert). 
            # We don't upsert because finding and updating thousands of rows individually in TinyDB is slow.
            # The mem cache will use the latest inserted row automatically because it's populated sequentially on init.
            distance_cache_table.insert_multiple(rows_to_insert)

def clear_route_caches():
    """Every cached duration and geometry, gone at once.

    For the settings that change what a "drive time" MEANS — the toll policy.
    The static distance cache is deliberately immortal (the solver reads it
    with no age check), so a policy flip must burn it, or the app keeps
    quoting the other policy's minutes indefinitely. Day-of traffic rows and
    the sweep's stage markers go with it so today re-prices under the new
    policy too.
    """
    global _distance_mem_cache
    with db_lock:
        distance_cache_table.truncate()
        live_traffic_table.truncate()
        route_geometry_cache_table.truncate()
        _distance_mem_cache = None
        mark_all_daily_schedules_dirty()
    set_app_state('traffic_sweep_done_v2', None)


def get_cached_day_of_traffic(origin: str, destination: str) -> Optional[dict]:
    """Today's traffic-aware duration for a pair, or None.

    A SEPARATE cache from the static matrix on purpose: the matrix is
    deliberately static (the solver's planning baseline), while these rows are
    day-of numbers written by the traffic sweep (morning pass + the T-60
    refine) and are only ever valid on the day they were fetched — yesterday's
    rush hour must not shade tomorrow morning's plan, so the date is part of
    the validity check rather than an age window.
    Returns {'duration_mins', 'stage', 'timestamp'}.
    """
    if not origin or not destination:
        return None
    import datetime as _dt
    with db_lock:
        row = live_traffic_table.get(
            (Query().origin == origin.strip().lower())
            & (Query().destination == destination.strip().lower()))
    if not row:
        return None
    ts = row.get('timestamp') or 0
    if _dt.date.fromtimestamp(ts) != _dt.date.today():
        return None
    try:
        return {'duration_mins': int(row.get('duration_mins')),
                'stage': row.get('stage') or 'morning', 'timestamp': ts}
    except (TypeError, ValueError):
        return None


def set_cached_day_of_traffic(origin: str, destination: str,
                              duration_mins: int, stage: str):
    if not origin or not destination:
        return
    import time
    with db_lock:
        o, d = origin.strip().lower(), destination.strip().lower()
        live_traffic_table.upsert(
            {'origin': o, 'destination': d,
             'duration_mins': int(duration_mins), 'stage': stage,
             'timestamp': time.time()},
            (Query().origin == o) & (Query().destination == d))


def get_cached_route_geometry(origin: str, destination: str, profile: str, max_age_mins: int = 10080) -> Optional[dict]:
    # Cache for 1 week by default (10080 mins)
    if not origin or not destination:
        return None
    import time
    orig_clean = origin.strip().lower()
    dest_clean = destination.strip().lower()
    with db_lock:
        QueryObj = Query()
        result = route_geometry_cache_table.search((QueryObj.origin == orig_clean) & (QueryObj.destination == dest_clean) & (QueryObj.profile == profile))
        if result:
            cached_data = result[0]
            if time.time() - cached_data.get('timestamp', 0) <= max_age_mins * 60:
                return cached_data.get('data')
            else:
                route_geometry_cache_table.remove(doc_ids=[result[0].doc_id])
    return None

def set_cached_route_geometry(origin: str, destination: str, profile: str, data: dict):
    if not origin or not destination:
        return
    import time
    orig_clean = origin.strip().lower()
    dest_clean = destination.strip().lower()
    with db_lock:
        QueryObj = Query()
        route_geometry_cache_table.upsert({
            'origin': orig_clean,
            'destination': dest_clean,
            'profile': profile,
            'data': data,
            'timestamp': time.time()
        }, (QueryObj.origin == orig_clean) & (QueryObj.destination == dest_clean) & (QueryObj.profile == profile))

# Driver CRUD
def get_all_drivers() -> List[dict]:
    with db_lock:
        drivers = []
        for d in drivers_table.all():
            doc = dict(d)
            doc['doc_id'] = d.doc_id
            if 'hashtags' not in doc:
                doc['hashtags'] = []
            drivers.append(doc)
        return drivers

def add_driver(driver_data: dict) -> int:
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        doc_id = drivers_table.insert(driver_data)
        ensure_members()
        # A new driving profile links to the person; push their calendars down
        # onto it so the profile arrives already mirrored.
        ensure_member_calendars()
        return doc_id

def update_driver_fields(driver_id: str, updates: dict) -> bool:
    """Partial update of a driver record by its string id (not doc_id).
    For cosmetic fields only (e.g. color_code synced from the member's
    identity color) — deliberately does NOT invalidate schedule caches,
    since nothing the solver reads changes."""
    with db_lock:
        return bool(drivers_table.update(updates, Query().id == driver_id))

def set_driver_rota_state(driver_id: str, disabled: bool) -> bool:
    """On or off the rota, by string id, INVALIDATING the schedule caches.

    Deliberately not `update_driver_fields`, which documents itself as
    cosmetic-only and skips invalidation: `is_disabled` is the one field on a
    driver the solver actually reads, so changing it without burning the
    cached schedule leaves every surface quoting a rota the solver no longer
    agrees with. Used when a member is archived (and restored)."""
    with db_lock:
        changed = bool(drivers_table.update({'is_disabled': bool(disabled)},
                                            Query().id == driver_id))
        if changed:
            custom_schedules_table.truncate()
            mark_all_daily_schedules_dirty()
            cache_table.truncate()
        return changed

def delete_driver(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        drivers_table.remove(doc_ids=[doc_id])

# Passenger CRUD
def get_all_passengers() -> List[dict]:
    with db_lock:
        passengers = []
        for p in passengers_table.all():
            doc = dict(p)
            doc['doc_id'] = p.doc_id
            
            # Auto-migrate string 'hashtag' to list 'hashtags'
            if 'hashtag' in doc:
                old_tag = doc.pop('hashtag')
                if 'hashtags' not in doc:
                    doc['hashtags'] = []
                if old_tag and old_tag not in doc['hashtags']:
                    doc['hashtags'].append(old_tag)
                # Save migration
                passengers_table.update({'hashtags': doc['hashtags']}, doc_ids=[doc['doc_id']])
                try:
                    passengers_table.update(db.table('passengers').update(db.delete('hashtag'), doc_ids=[doc['doc_id']]))
                except:
                    # Depending on TinyDB version, deleting a field might differ.
                    passengers_table.update({'hashtag': None}, doc_ids=[doc['doc_id']])
                
            if 'hashtags' not in doc:
                doc['hashtags'] = []
                
            passengers.append(doc)
        return passengers

def get_passengers() -> List[dict]:
    with db_lock:
        return passengers_table.all()

def get_all_conversations() -> List[dict]:
    import time
    with db_lock:
        cutoff = time.time() - (30 * 86400)
        conversations_table.remove(Query().updated_at < cutoff)
        return conversations_table.all()

def get_conversation(conv_id: str) -> Optional[dict]:
    with db_lock:
        res = conversations_table.search(Query().id == conv_id)
        return res[0] if res else None

def create_conversation(conv_data: dict) -> str:
    with db_lock:
        conversations_table.insert(conv_data)
        return conv_data['id']

def update_conversation(conv_id: str, conv_data: dict) -> None:
    with db_lock:
        conversations_table.update(conv_data, Query().id == conv_id)

def delete_conversation(conv_id: str) -> None:
    with db_lock:
        conversations_table.remove(Query().id == conv_id)

def add_message_to_conversation(conv_id: str, message: dict) -> None:
    import time
    with db_lock:
        conv = conversations_table.search(Query().id == conv_id)
        if conv:
            c = conv[0]
            if 'messages' not in c:
                c['messages'] = []
            c['messages'].append(message)
            c['updated_at'] = time.time()
            conversations_table.update(c, Query().id == conv_id)
        else:
            # Fallback for old behaviour or unknown conv, but ideally we should have a default general conv.
            pass

def clear_chat_history() -> None:
    with db_lock:
        conversations_table.truncate()

def add_passenger(passenger_data: dict) -> int:
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        doc_id = passengers_table.insert(passenger_data)
        ensure_members()
        ensure_member_calendars()
        return doc_id

def update_passenger(doc_id: int, passenger_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        passengers_table.update(passenger_data, doc_ids=[doc_id])

def delete_passenger(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        passengers_table.remove(doc_ids=[doc_id])

def get_all_cars() -> List[dict]:
    with db_lock:
        cars = []
        for c in cars_table.all():
            doc = dict(c)
            doc['doc_id'] = c.doc_id
            cars.append(doc)
        return cars

def add_car(car_data: dict) -> int:
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return cars_table.insert(car_data)

def update_car(doc_id: int, car_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        cars_table.update(car_data, doc_ids=[doc_id])

def delete_car(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        cars_table.remove(doc_ids=[doc_id])

# Family member CRUD (overlay entity; see FamilyMember in models/schemas.py)
def get_all_members(include_system: bool = False,
                    include_archived: bool = False) -> List[dict]:
    """The human family. **Argyle and archived people are excluded by default.**

    Argyle is a `system: True` member so that agent replies have a sender
    identity, and the original note said the flag "lets the UI exclude it from
    the human family roster". Leaving that to each caller meant exactly one
    surface ever did (`app.html`), so the assistant turned up in the People
    config, in occasion attendance, in presence, in digests — anywhere people
    are listed. A default that has to be remembered 57 times is not a default.

    So exclusion moved here, to the boundary. `include_system=True` is for the
    handful of places that resolve a message SENDER by id and would otherwise
    render Argyle's own messages as "Unknown".

    ARCHIVED members ride the same boundary for the same reason. Archiving is
    this app's "delete": the person leaves every list, picker, roster, digest
    and assignment target, while every message they sent and every chore they
    ever did keeps its author. That is only coherent because `get_member(id)`
    still answers for them — the LIST forgets you, the RECORD does not — so
    `include_archived=True` is for the rare roster that must show the departed
    (the archived view in config, and any by-id resolution that starts from a
    list rather than an id).
    """
    with db_lock:
        members = []
        for m in members_table.all():
            doc = dict(m)
            doc['doc_id'] = m.doc_id
            if not include_system and doc.get('system'):
                continue
            if not include_archived and doc.get('status') == 'archived':
                continue
            members.append(doc)
        return members


# --- Member status: active | disabled | archived ---
# Two different facts, deliberately one field, because they are a LADDER:
#   active    — normal.
#   disabled  — ACCESS revoked. Cannot sign in with a password, cannot use a
#               PIN, cannot spend an outstanding invite link; every session
#               dies and every device their sign-ins vouched stops being
#               trusted ground. They stay fully visible in the family: on the
#               schedule, in history, on the map. This is "you can't get in",
#               never "you don't exist".
#   archived  — HIDDEN as well: out of every list, picker and assignment
#               target, off the rota. Implies disabled (nobody archived keeps
#               a way in). Reversible, because the record never left.
#
# NOT called `is_disabled`, which already exists on `Driver` and means
# something else entirely — out of the solver, off the rota. v2.258.1 was a
# bug caused by exactly that scheduling flag leaking into identity, so the two
# concepts get two different field names and the UI does the disambiguating.
MEMBER_STATUSES = ('active', 'disabled', 'archived')

def member_status(member: dict) -> str:
    """Absent means active — every member predating this field, which is all
    of them, must read as normal rather than as locked out."""
    s = (member or {}).get('status')
    return s if s in MEMBER_STATUSES else 'active'

def member_has_access(member: dict) -> bool:
    return member_status(member) == 'active'

def set_member_status(member_id: str, status: str) -> Optional[dict]:
    if status not in MEMBER_STATUSES:
        return None
    with db_lock:
        if not members_table.search(Query().id == member_id):
            return None
        members_table.update({'status': status}, Query().id == member_id)
    return get_member(member_id)

def get_member(member_id: str) -> Optional[dict]:
    with db_lock:
        res = members_table.search(Query().id == member_id)
        return dict(res[0]) if res else None

def get_member_by_driver_id(driver_id: str) -> Optional[dict]:
    with db_lock:
        res = members_table.search(Query().driver_id == driver_id)
        return dict(res[0]) if res else None

def get_member_by_passenger_id(passenger_id: str) -> Optional[dict]:
    with db_lock:
        res = members_table.search(Query().passenger_id == passenger_id)
        return dict(res[0]) if res else None

def add_member(member_data: dict) -> int:
    with db_lock:
        return members_table.insert(member_data)

def update_member(member_id: str, member_data: dict) -> bool:
    with db_lock:
        return bool(members_table.update(member_data, Query().id == member_id))

def delete_member(member_id: str) -> None:
    with db_lock:
        members_table.remove(Query().id == member_id)

def merge_members(keep_id: str, absorb_id: str) -> Optional[dict]:
    """Move driver/passenger links (and unset HA mappings) from absorb onto
    keep, then delete absorb. Legacy driver/passenger records untouched."""
    with db_lock:
        keep = members_table.search(Query().id == keep_id)
        absorb = members_table.search(Query().id == absorb_id)
        if not keep or not absorb:
            return None
        keep, absorb = dict(keep[0]), dict(absorb[0])
        updates = {}
        if not keep.get('driver_id') and absorb.get('driver_id'):
            updates['driver_id'] = absorb['driver_id']
            updates['can_drive'] = absorb.get('can_drive', True)
        if not keep.get('passenger_id') and absorb.get('passenger_id'):
            updates['passenger_id'] = absorb['passenger_id']
        for f in ('ha_person_entity', 'notify_service', 'media_player_entity', 'avatar', 'image'):
            if not keep.get(f) and absorb.get(f):
                updates[f] = absorb[f]
        # Calendars are the person's, so a merge unions them — the absorbed
        # record is about to be deleted and its list would otherwise vanish
        # (the link mirrors only carry the ones a driver/passenger profile had).
        merged_cals = list(keep.get('calendar_ids') or [])
        for c in (absorb.get('calendar_ids') or []):
            if c and c not in merged_cals:
                merged_cals.append(c)
        if merged_cals != (keep.get('calendar_ids') or []):
            updates['calendar_ids'] = merged_cals
        if updates:
            members_table.update(updates, Query().id == keep_id)
        members_table.remove(Query().id == absorb_id)
        keep.update(updates)
        ensure_member_calendars()
        return keep

def split_member(member_id: str, link: str) -> Optional[dict]:
    """Detach 'driver' or 'passenger' link into a fresh member (undo for a
    bad name-match merge). Returns the new member, or None."""
    import uuid as _uuid
    import time
    with db_lock:
        res = members_table.search(Query().id == member_id)
        if not res:
            return None
        member = dict(res[0])
        link_field = 'driver_id' if link == 'driver' else 'passenger_id'
        link_value = member.get(link_field)
        if not link_value:
            return None
        # Refuse to split a member's only link (would leave an empty husk).
        other_field = 'passenger_id' if link_field == 'driver_id' else 'driver_id'
        if not member.get(other_field):
            return None
        new = {
            'id': _uuid.uuid4().hex,
            'name': member.get('name', ''),
            'color_code': member.get('color_code', '#3b82f6'),
            'avatar': None,
            'bio': '',
            'can_drive': link == 'driver' and member.get('can_drive', False),
            'is_child': member.get('is_child', False) if link == 'passenger' else False,
            'driver_id': link_value if link == 'driver' else None,
            'passenger_id': link_value if link == 'passenger' else None,
            # Filled from the detached record's mirror by ensure_member_calendars
            # below: both halves start with the calendars the merge had shared.
            'calendar_ids': [],
            'ha_person_entity': None,
            'notify_service': None,
            'media_player_entity': None,
            'pin': None,
            'created_at': time.time(),
        }
        clear = {link_field: None}
        if link == 'driver':
            clear['can_drive'] = False
        members_table.update(clear, Query().id == member_id)
        members_table.insert(new)
        ensure_member_calendars()
        return new

# --- Member PINs and device tokens ---
# PINs gate identity switching in the PWA and (with parent role) privileged
# actions like chore verification. pbkdf2 with per-member salt; a successful
# auth mints a per-device token stored client-side.

def _hash_pin(pin: str, salt: str) -> str:
    import hashlib
    return hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'),
                               bytes.fromhex(salt), 100_000).hex()

def set_member_pin(member_id: str, pin: str) -> bool:
    import os as _os
    salt = _os.urandom(16).hex()
    with db_lock:
        return bool(members_table.update(
            {'pin_hash': _hash_pin(pin, salt), 'pin_salt': salt},
            Query().id == member_id))

def clear_member_pin(member_id: str) -> bool:
    with db_lock:
        return bool(members_table.update(
            {'pin_hash': None, 'pin_salt': None}, Query().id == member_id))

def verify_member_pin(member_id: str, pin: str) -> bool:
    import hmac
    member = get_member(member_id)
    if not member or not member.get('pin_hash') or not member.get('pin_salt'):
        return False
    return hmac.compare_digest(member['pin_hash'],
                               _hash_pin(pin or '', member['pin_salt']))

# --- Trusted devices (auth arc S5) ---
# What makes it safe to KEEP the PIN rather than delete it. A PIN is four
# digits: fine as "let me back in on the kitchen tablet", hopeless as the only
# thing between the public internet and a child's account. So a PIN opens a
# device that has already been trusted, and nothing else.
#
# A device earns trust by somebody signing in on it with a password, or by a
# parent naming it. S6 reuses this table for wall panels, which are the same
# idea carried further: a place rather than a person.


def trust_device(device_id: str, label: str = None, by_member: str = None,
                 kind: str = 'personal') -> dict:
    import time
    now = time.time()
    row = {'device_id': device_id, 'label': label or 'A device',
           'kind': kind, 'trusted_by': by_member,
           'created_at': now, 'last_seen': now}
    with db_lock:
        existing = trusted_devices_table.search(Query().device_id == device_id)
        if existing:
            keep = {'last_seen': now}
            if label:
                keep['label'] = label
            trusted_devices_table.update(keep, Query().device_id == device_id)
            return {**existing[0], **keep}
        trusted_devices_table.insert(row)
    return row


# --- Pairing requests: the DEVICE asks, a parent approves (auth arc S6) ---
# The direction matters and an earlier draft had it backwards. A parent minted
# a code and somebody typed it into the panel, which meant the secret
# travelled TO the untrusted screen and a human stood at a hallway touchscreen
# entering six digits and a label. Every pairing flow anybody has actually
# used — a TV, a console, a streaming box — works the other way: the device
# displays a code, and the human carries it to a surface where they are
# already signed in. Approval then happens where authentication already is,
# and the panel never takes input at all.


def request_pairing(device_id: str, code: str, ttl_minutes: int = 15,
                    context: dict = None) -> dict:
    """A screen asking to be let in. One live request per device — asking
    again replaces the old code rather than leaving two valid."""
    import time
    now = time.time()
    row = {'device_id': device_id, 'code': code, 'requested_at': now,
           'expires_at': now + ttl_minutes * 60, 'approved_at': None,
           'device_token': None, 'label': None,
           # Carried so the approving parent can tell whether the thing asking
           # is the thing in front of them, rather than approving a code blind.
           'context': context or {}}
    with db_lock:
        pending_pairings_table.remove(Query().device_id == device_id)
        pending_pairings_table.insert(row)
    return row


def get_pairing_by_code(code: str) -> Optional[dict]:
    import time
    if not code:
        return None
    with db_lock:
        rows = pending_pairings_table.search(Query().code == str(code))
    live = [r for r in rows if not r.get('approved_at')
            and r.get('expires_at', 0) > time.time()]
    return live[0] if live else None


def get_pairing_by_device(device_id: str) -> Optional[dict]:
    if not device_id:
        return None
    with db_lock:
        rows = pending_pairings_table.search(Query().device_id == device_id)
    return rows[0] if rows else None


def approve_pairing(code: str, label: str, by_member: str = None) -> Optional[dict]:
    """Mint the device's token and mark the request done. The panel is
    polling for exactly this."""
    import time
    row = get_pairing_by_code(code)
    if not row:
        return None
    token = enrol_device_token(row['device_id'], label, by_member=by_member)
    with db_lock:
        pending_pairings_table.update(
            {'approved_at': time.time(), 'device_token': token, 'label': label},
            Query().device_id == row['device_id'])
    return {**row, 'device_token': token, 'label': label}


def clear_pairing(device_id: str) -> None:
    with db_lock:
        pending_pairings_table.remove(Query().device_id == device_id)


def enrol_device_token(device_id: str, label: str, by_member: str = None) -> str:
    """Give a device its own credential (auth arc S6).

    A wall panel is a PLACE, not a person: it must come up after a power cut
    at 6am with nobody in the room, so it cannot hold a member's session. It
    holds this instead — a long-lived token that grants board reads and the
    interactive board actions a wall legitimately performs, and never admin.
    It gets the powers of the room it is bolted to, not the powers of whoever
    last walked past it."""
    import secrets
    token = secrets.token_urlsafe(32)
    trust_device(device_id, label=label, by_member=by_member, kind='panel')
    with db_lock:
        trusted_devices_table.update({'device_token': token, 'kind': 'panel'},
                                     Query().device_id == device_id)
    return token


def get_device_by_token(token: str) -> Optional[dict]:
    if not token:
        return None
    with db_lock:
        rows = trusted_devices_table.search(Query().device_token == token)
    return rows[0] if rows else None


def get_trusted_device(device_id: str) -> Optional[dict]:
    if not device_id:
        return None
    with db_lock:
        rows = trusted_devices_table.search(Query().device_id == device_id)
    return rows[0] if rows else None


def get_trusted_devices() -> List[dict]:
    with db_lock:
        return sorted(trusted_devices_table.all(),
                      key=lambda r: -(r.get('last_seen') or 0))


def untrust_device(device_id: str) -> None:
    with db_lock:
        trusted_devices_table.remove(Query().device_id == device_id)


def touch_device(device_id: str) -> None:
    """Last seen, so a stale tablet is recognisable on the list a parent
    revokes from — 'the one nobody has used since March' is how a person
    actually identifies a device they no longer own."""
    import time
    if not device_id:
        return
    with db_lock:
        trusted_devices_table.update({'last_seen': time.time()},
                                     Query().device_id == device_id)


# --- Rate limiting that survives a restart (auth arc S4) ---
# It used to be a module-level dict, which this project resets on every
# release — and a lockout that a rebuild clears is one an attacker waits out.
# Keyed by an opaque string so the same machinery counts a member and an IP.

_RATE_BASE_SECONDS = 30
_RATE_MAX_SECONDS = 3600

# The two counters do DIFFERENT JOBS and must not share a threshold.
#
# Per member, 5 is right: it is protection against somebody guessing one
# person's PIN, and five wrong tries is already an unusual number of typos.
#
# Per IP it would be a household-wide outage. `CF-Connecting-IP` is the
# CLIENT's public address, and the PWA is installed against the cloudflared
# hostname — so every phone in the house arrives from the same home IP even
# when everyone is sitting in the kitchen. At a threshold of five, one kid
# fumbling their PIN would lock out both parents and the wall panel,
# escalating to an hour if it happened again. That is a self-inflicted denial
# of service on the family, and it would have presented as a mystery outage.
#
# So the IP counter is a COARSE NET for enumeration — somebody walking the
# whole family, or scripting one account — and is set far above anything a
# household of fumbling humans produces in a day.
_RATE_MAX_FAILS = 5
_RATE_IP_MAX_FAILS = 50


def _rate_threshold(key: str) -> int:
    return _RATE_IP_MAX_FAILS if key.startswith('ip:') else _RATE_MAX_FAILS


def rate_locked(key: str) -> bool:
    import time
    with db_lock:
        rows = rate_limits_table.search(Query().key == key)
    return bool(rows) and rows[0].get('locked_until', 0) > time.time()


def rate_record(key: str, ok: bool) -> None:
    """Success clears the slate; failure counts, and the lockout DOUBLES each
    time it trips — a fat-fingered PIN costs seconds, a script costs hours."""
    import time
    with db_lock:
        rows = rate_limits_table.search(Query().key == key)
        if ok:
            if rows:
                rate_limits_table.remove(Query().key == key)
            return
        entry = rows[0] if rows else {'key': key, 'fails': 0, 'trips': 0,
                                      'locked_until': 0}
        entry['fails'] = entry.get('fails', 0) + 1
        if entry['fails'] >= _rate_threshold(key):
            entry['fails'] = 0
            entry['trips'] = entry.get('trips', 0) + 1
            backoff = min(_RATE_BASE_SECONDS * (2 ** (entry['trips'] - 1)),
                          _RATE_MAX_SECONDS)
            entry['locked_until'] = time.time() + backoff
        if rows:
            rate_limits_table.update(entry, Query().key == key)
        else:
            rate_limits_table.insert(entry)


def rate_clear(key: str) -> None:
    with db_lock:
        rate_limits_table.remove(Query().key == key)


# --- Passwords (auth arc S3) ---
# Same PBKDF2 shape as the PIN above and deliberately so: one hashing story in
# the codebase, no new dependency in the add-on image. The iteration count is
# higher because a password is the credential that faces the public internet
# while a PIN, after S5, only ever re-opens an already-trusted device.

_PW_ITERATIONS = 260_000


def _hash_password(password: str, salt: str) -> str:
    import hashlib
    return hashlib.pbkdf2_hmac('sha256', (password or '').encode('utf-8'),
                               bytes.fromhex(salt), _PW_ITERATIONS).hex()


def set_member_password(member_id: str, password: str) -> bool:
    import os as _os
    salt = _os.urandom(16).hex()
    with db_lock:
        return bool(members_table.update(
            {'password_hash': _hash_password(password, salt),
             'password_salt': salt}, Query().id == member_id))


def verify_member_password(member_id: str, password: str) -> bool:
    import hmac
    member = get_member(member_id)
    if not member or not member.get('password_hash') or not member.get('password_salt'):
        return False
    return hmac.compare_digest(
        member['password_hash'], _hash_password(password or '', member['password_salt']))


def clear_member_password(member_id: str) -> bool:
    with db_lock:
        return bool(members_table.update(
            {'password_hash': None, 'password_salt': None}, Query().id == member_id))


def get_member_by_email(email: str) -> Optional[dict]:
    """Case-insensitive, because nobody remembers how they capitalised it."""
    wanted = (email or '').strip().lower()
    if not wanted:
        return None
    for m in get_all_members(include_system=True):
        if (m.get('email') or '').strip().lower() == wanted:
            return m
    return None


# --- Invite / verify / reset links (auth arc S3) ---

def create_auth_link(member_id: str, kind: str, ttl_hours: int = 168) -> str:
    """A single-use link. Seven days by default: long enough that a
    grandparent who opens mail on Sunday still gets in, short enough that a
    forwarded invite does not stay live for a year."""
    import secrets
    import time
    token = secrets.token_urlsafe(32)
    with db_lock:
        auth_links_table.insert({
            'token': token, 'member_id': member_id, 'kind': kind,
            'created_at': time.time(),
            'expires_at': time.time() + ttl_hours * 3600,
            'used_at': None})
    return token


def peek_auth_link(token: str) -> Optional[dict]:
    """Look without spending — so the set-password PAGE can say whether the
    link is still good before the person types anything into it."""
    import time
    if not token:
        return None
    with db_lock:
        rows = auth_links_table.search(Query().token == token)
    if not rows:
        return None
    link = rows[0]
    if link.get('used_at') or link.get('expires_at', 0) < time.time():
        return None
    return link


def consume_auth_link(token: str) -> Optional[dict]:
    """Spend it. Single use is the whole point: a reset link sitting in a
    mailbox forever is a spare key under the mat."""
    import time
    link = peek_auth_link(token)
    if not link:
        return None
    with db_lock:
        auth_links_table.update({'used_at': time.time()}, Query().token == token)
    return link


def invalidate_auth_links(member_id: str, kind: str = None) -> None:
    """Used when a password is set: every other outstanding link for that
    person dies with it."""
    import time
    q = Query().member_id == member_id
    if kind:
        q = q & (Query().kind == kind)
    with db_lock:
        auth_links_table.update({'used_at': time.time()}, q)


def create_member_token(member_id: str) -> str:
    import uuid as _uuid
    import time
    token = _uuid.uuid4().hex + _uuid.uuid4().hex
    with db_lock:
        member_tokens_table.insert({
            'token': token, 'member_id': member_id, 'created_at': time.time()})
        # Housekeeping: keep the newest ~20 tokens per member.
        rows = sorted(member_tokens_table.search(Query().member_id == member_id),
                      key=lambda r: r.get('created_at', 0))
        if len(rows) > 20:
            member_tokens_table.remove(doc_ids=[r.doc_id for r in rows[:len(rows) - 20]])
    return token

# Decision 8 (auth arc S8): sessions live 90 days. Long enough that a
# grandparent is not re-typing a password they have forgotten; short enough
# that a lost phone's session dies on its own even when nobody thinks to
# revoke it. The PIN re-opens a trusted device afterwards (Decision 4c), so
# the common renewal is four digits rather than a password.
MEMBER_TOKEN_TTL_SECONDS = 90 * 86400

def get_member_by_token(token: str) -> Optional[dict]:
    import time
    if not token:
        return None
    with db_lock:
        rows = member_tokens_table.search(Query().token == token)
        if not rows:
            return None
        row = rows[0]
        created = row.get('created_at')
        if not created:
            # A row from before tokens carried a birthday is grandfathered
            # from NOW rather than guessed at: expiring the whole installed
            # base at deploy time would sign every phone out at once, which
            # is this arc's cardinal sin.
            created = time.time()
            member_tokens_table.update({'created_at': created},
                                       doc_ids=[row.doc_id])
        if time.time() - created > MEMBER_TOKEN_TTL_SECONDS:
            # Expired means GONE, not merely refused — a dead token left in
            # the table would come back to life if the TTL were ever raised.
            member_tokens_table.remove(doc_ids=[row.doc_id])
            return None
    member = get_member(row['member_id'])
    # Belt and braces on the status ladder: disabling already deletes every
    # session, so a live token for a disabled member should not exist — but
    # "should not exist" is not a check, and this is the single chokepoint
    # every authenticated request passes through.
    if member is not None and not member_has_access(member):
        return None
    return member

def delete_member_tokens(member_id: str) -> int:
    with db_lock:
        removed = member_tokens_table.remove(Query().member_id == member_id)
    try:
        return len(removed)
    except TypeError:
        return 0

def untrust_devices_vouched_by(member_id: str) -> int:
    """The other half of 'sign out everywhere' (Decision 8): the devices this
    member's own password sign-ins vouched for stop being trusted ground, so
    their PIN cannot quietly re-open the stolen phone that prompted this.
    PERSONAL devices only — a wall panel is the room's credential, not this
    person's, and a parent-named device was somebody's deliberate act."""
    if not member_id:
        return 0
    with db_lock:
        removed = trusted_devices_table.remove(
            (Query().trusted_by == member_id) & (Query().kind == 'personal'))
    try:
        return len(removed)
    except TypeError:
        return 0

# --- Chores + points ledger ---
# Marketplace model: chores sit in a family pot, members claim them, parents
# verify. Points ledger is append-only; balances are sums. Lifecycle
# maintenance (recurring reopen, stale-claim release) runs lazily on read.

CHORE_CLAIM_CAP = 3
CHORE_STALE_CLAIM_HOURS = 48

def _chore_reset_fields(chore: dict = None):
    """The fields that put a chore back in play.

    An OWNED chore comes back to its owner; everything else goes back to the
    pot. That is the line between the two concepts: owning the lawn is an
    arrangement that outlives any one week, while being assigned tonight's
    dishes is about tonight — so `assigned_by` is always cleared here, or a
    helper who comes twice a week would be handed the dishes every day."""
    import time as _t
    base = {'state': 'open', 'claimed_by': None, 'claimed_at': None,
            'done_at': None, 'verified_by': None, 'verified_at': None,
            'rejected_reason': None, 'reopens_on': None, 'assigned_by': None}
    owner = (chore or {}).get('owner')
    if owner:
        base.update({'state': 'claimed', 'claimed_by': owner,
                     'claimed_at': _t.time()})
    return base

def _chore_maintenance():
    import time
    from datetime import date
    today = date.today().isoformat()
    now = time.time()
    with db_lock:
        for c in chores_table.all():
            if (c.get('state') == 'verified' and c.get('recurrence') != 'once'
                    and c.get('reopens_on') and c['reopens_on'] <= today):
                chores_table.update(_chore_reset_fields(c), doc_ids=[c.doc_id])
            elif (c.get('state') == 'claimed' and not c.get('owner')
                    and not c.get('assigned_by') and c.get('claimed_at')
                    and now - c['claimed_at'] > CHORE_STALE_CLAIM_HOURS * 3600):
                # Claimed then ignored: release back to the pot. Neither an
                # owned chore nor one a parent assigned is ever released —
                # nobody claimed those, so there is no claim to go stale, and
                # dropping them would quietly undo somebody's decision.
                chores_table.update({'state': 'open', 'claimed_by': None,
                                     'claimed_at': None, 'rejected_reason': None},
                                    doc_ids=[c.doc_id])

def get_all_chores() -> List[dict]:
    _chore_maintenance()
    with db_lock:
        out = []
        for c in chores_table.all():
            doc = dict(c)
            doc['doc_id'] = c.doc_id
            out.append(doc)
        return out

def get_chore(chore_id: str) -> Optional[dict]:
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        return dict(res[0]) if res else None

def add_chore(data: dict) -> str:
    with db_lock:
        chores_table.insert(data)
        return data['id']

def update_chore(chore_id: str, data: dict) -> bool:
    with db_lock:
        return bool(chores_table.update(data, Query().id == chore_id))

def delete_chore(chore_id: str):
    with db_lock:
        chores_table.remove(Query().id == chore_id)

def reopen_chore(chore_id: str) -> str:
    """Manual return to the pot: 'verified' (reopen early / run again) or
    'claimed' (parent-side release). NOT 'done' — that's finished work
    awaiting verification; discarding it silently is what reject-with-reason
    is for. Points from a prior verification are never touched (undoing a
    payout is a separate, explicit ledger adjustment).
    Returns 'ok' | 'missing' | 'not_reopenable'."""
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        if not res:
            return 'missing'
        if res[0].get('state') not in ('verified', 'claimed'):
            return 'not_reopenable'
        chores_table.update(_chore_reset_fields(), Query().id == chore_id)
        return 'ok'

def count_active_claims(member_id: str) -> int:
    with db_lock:
        return sum(1 for c in chores_table.all()
                   if c.get('claimed_by') == member_id
                   and c.get('state') in ('claimed', 'done'))

def claim_chore(chore_id: str, member_id: str) -> str:
    """Returns 'ok' | 'not_open' | 'cap' | 'missing'."""
    import time
    _chore_maintenance()
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        if not res:
            return 'missing'
        if res[0].get('state') != 'open':
            return 'not_open'
        active = sum(1 for c in chores_table.all()
                     if c.get('claimed_by') == member_id
                     and c.get('state') in ('claimed', 'done'))
        if active >= CHORE_CLAIM_CAP:
            return 'cap'
        chores_table.update({'state': 'claimed', 'claimed_by': member_id,
                             'claimed_at': time.time(), 'rejected_reason': None},
                            Query().id == chore_id)
        return 'ok'

def unclaim_chore(chore_id: str, member_id: str) -> bool:
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        if not res or res[0].get('state') != 'claimed' \
                or res[0].get('claimed_by') != member_id:
            return False
        # You can put back what you picked up; you cannot put back what you
        # were given. An owned chore is the arrangement itself, and an
        # assigned one is a parent's decision — both are theirs to undo.
        if res[0].get('owner') or res[0].get('assigned_by'):
            return False
        chores_table.update({'state': 'open', 'claimed_by': None,
                             'claimed_at': None, 'rejected_reason': None},
                            Query().id == chore_id)
        return True

def mark_chore_done(chore_id: str, member_id: str) -> bool:
    import time
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        if not res or res[0].get('state') != 'claimed' \
                or res[0].get('claimed_by') != member_id:
            return False
        chores_table.update({'state': 'done', 'done_at': time.time()},
                            Query().id == chore_id)
        return True

def _chore_next_reopen(recurrence: str) -> Optional[str]:
    from datetime import date, timedelta
    today = date.today()
    if recurrence == 'daily':
        return (today + timedelta(days=1)).isoformat()
    if recurrence == 'weekly':
        return (today + timedelta(days=7)).isoformat()
    if recurrence == 'monthly':
        try:
            from dateutil.relativedelta import relativedelta
            return (today + relativedelta(months=1)).isoformat()
        except Exception:
            return (today + timedelta(days=30)).isoformat()
    return None

def verify_chore(chore_id: str, verifier_member_id: str) -> Optional[dict]:
    """done -> verified. Awards points to the claimant IF they are a child
    (adults are claimable-but-pointless by design). Recurring chores get a
    reopens_on date. Returns {'chore', 'awarded', 'pet_xp'} or None."""
    import time
    import uuid as _uuid
    from datetime import date
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        if not res or res[0].get('state') != 'done':
            return None
        chore = dict(res[0])
        updates = {'state': 'verified', 'verified_by': verifier_member_id,
                   'verified_at': time.time(),
                   'reopens_on': _chore_next_reopen(chore.get('recurrence', 'once'))}
        chores_table.update(updates, Query().id == chore_id)
        chore.update(updates)
        awarded = 0
        claimant = members_table.search(Query().id == chore.get('claimed_by'))
        if claimant and claimant[0].get('role') == 'child' and chore.get('points', 0) > 0:
            awarded = int(chore['points'])
            points_ledger_table.insert({
                'id': _uuid.uuid4().hex,
                'member_id': chore['claimed_by'],
                'delta': awarded,
                'reason': 'chore',
                'chore_id': chore_id,
                'chore_title': chore.get('title'),
                'by_member_id': verifier_member_id,
                'ts': time.time(),
            })
    # Pet xp, minted from the SAME event and never instead of it -- a kid
    # must not have to choose between levelling their critter and the family
    # movie-night pool. Outside the points lock because this ledger is its
    # own; keyed on the chore id so a re-verify of the same instance cannot
    # mint twice.
    #
    # Unlike points, this is NOT children-only. Points are children-only
    # because they cost a parent real money; xp costs nothing and buys
    # nothing outside the game, and a parent's critter has to be able to
    # level or it drags every level-matched fight down to its own floor.
    xp_awarded = 0
    if chore.get('claimed_by') and int(chore.get('points', 0) or 0) > 0:
        xp_awarded = grant_pet_xp(
            chore['claimed_by'],
            round(int(chore['points']) * pet_xp_rate('pet_xp_per_chore_point')),
            'chore', ref_id=chore_id, date_str=date.today().isoformat(),
            note=chore.get('title'))
    return {'chore': chore, 'awarded': awarded, 'pet_xp': xp_awarded}

def reject_chore(chore_id: str, verifier_member_id: str, reason: str) -> Optional[dict]:
    """done -> claimed (redo). No forfeiture — points just wait for a pass."""
    with db_lock:
        res = chores_table.search(Query().id == chore_id)
        if not res or res[0].get('state') != 'done':
            return None
        chores_table.update({'state': 'claimed', 'done_at': None,
                             'rejected_reason': reason or 'Needs another pass'},
                            Query().id == chore_id)
        out = dict(res[0])
        out.update({'state': 'claimed', 'rejected_reason': reason})
        return out

def get_points_balance(member_id: str) -> int:
    with db_lock:
        return sum(int(e.get('delta', 0))
                   for e in points_ledger_table.search(Query().member_id == member_id))

def get_points_earned(member_id: str) -> int:
    """Lifetime positive points (chore awards + manual adds). Redemptions and
    resets are negative and don't subtract here, so this is monotonic — used
    for status tiers, which should never be taken away when a kid spends points."""
    with db_lock:
        return sum(d for e in points_ledger_table.search(Query().member_id == member_id)
                   if (d := int(e.get('delta', 0))) > 0)

def get_points_ledger(member_id: str, limit: int = 25) -> List[dict]:
    with db_lock:
        rows = [dict(e) for e in points_ledger_table.search(Query().member_id == member_id)]
    rows.sort(key=lambda e: e.get('ts', 0), reverse=True)
    return rows[:limit]

def get_all_point_balances() -> List[dict]:
    """[{member_id, name, color_code, avatar, balance}] for child members."""
    from services import avatar_render
    balances = []
    for m in get_all_members():
        if m.get('role') != 'child':
            continue
        balances.append({
            'member_id': m['id'], 'name': m.get('name'),
            'color_code': m.get('color_code'), 'avatar': m.get('avatar'),
            # the chip decision lives in avatar_render (photo vs character)
            'image': avatar_render.effective_image(m),
            'balance': get_points_balance(m['id']),
        })
    balances.sort(key=lambda b: -b['balance'])
    return balances

def adjust_points(member_id: str, delta: int, note: str = '',
                  by_member_id: str = None) -> int:
    """Manual point adjustment. The ledger is append-only — corrections are
    new 'adjust' entries, never edits — so history stays auditable. Returns
    the new balance. chore_title carries the note so every ledger renderer
    shows the reason without a schema change."""
    import time
    import uuid as _uuid
    with db_lock:
        points_ledger_table.insert({
            'id': _uuid.uuid4().hex,
            'member_id': member_id,
            'delta': int(delta),
            'reason': 'adjust',
            'chore_id': None,
            'chore_title': (note or '').strip() or 'Manual adjustment',
            'by_member_id': by_member_id,
            'ts': time.time(),
        })
    return get_points_balance(member_id)

def reset_points(member_id: str = None, by_member_id: str = None) -> dict:
    """Zero balances via compensating 'adjust' entries (history preserved).
    member_id None = every child. Pending redemptions are auto-denied and
    pool pledges released first: either kind of hold against a zeroed
    balance could never be honored and would wedge future spending (holds
    count as spent)."""
    targets = [m for m in get_all_members()
               if m.get('role') == 'child'
               and (member_id is None or m['id'] == member_id)]
    denied = 0
    released_pledges = 0
    results = []
    for m in targets:
        for red in get_redemptions(m['id'], 'pending'):
            if decide_redemption(red['id'], by_member_id, approve=False):
                denied += 1
        with db_lock:
            released_pledges += len(pool_contributions_table.search(Query().member_id == m['id']))
            pool_contributions_table.remove(Query().member_id == m['id'])
        balance = get_points_balance(m['id'])
        if balance != 0:
            adjust_points(m['id'], -balance, 'Points reset', by_member_id)
        results.append({'member_id': m['id'], 'name': m.get('name'),
                        'cleared': balance})
    return {'members': results, 'denied_redemptions': denied,
            'released_pledges': released_pledges}

# --- Daily routines + streaks ---
# Personal templates checked off per day. A day is "complete" when every item
# scheduled for that day is checked; days with nothing scheduled are neutral
# (they neither extend nor break streaks). No points by design.

def get_routines(member_id: str = None) -> List[dict]:
    with db_lock:
        rows = routines_table.search(Query().member_id == member_id) if member_id \
            else routines_table.all()
        return [dict(r) for r in rows]

# --- Kid tasks (school/deadline list, kid-support arc K4a) ---
# Due dates only, never grades; no points, no streaks — see
# docs/k4_school_design.md scope guards.

def get_kid_tasks(member_id: str = None, include_done: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(t) for t in kid_tasks_table.all()]
    if member_id:
        rows = [t for t in rows if t.get('member_id') == member_id]
    if not include_done:
        rows = [t for t in rows if t.get('status') != 'done']
    rows.sort(key=lambda t: (t.get('due_date') or '9999', t.get('title') or ''))
    return rows

def get_kid_task(task_id: str) -> Optional[dict]:
    with db_lock:
        res = kid_tasks_table.search(Query().id == task_id)
        return dict(res[0]) if res else None

def add_kid_task(data: dict) -> str:
    with db_lock:
        kid_tasks_table.insert(data)
        return data['id']

def update_kid_task(task_id: str, data: dict) -> bool:
    with db_lock:
        return bool(kid_tasks_table.update(data, Query().id == task_id))

def delete_kid_task(task_id: str):
    with db_lock:
        kid_tasks_table.remove(Query().id == task_id)

def complete_kid_task(task_id: str, done: bool = True) -> Optional[dict]:
    import time as _time
    with db_lock:
        res = kid_tasks_table.search(Query().id == task_id)
        if not res:
            return None
        kid_tasks_table.update({'status': 'done' if done else 'open',
                                'done_at': _time.time() if done else None},
                               Query().id == task_id)
        out = dict(res[0])
        out['status'] = 'done' if done else 'open'
        return out

# --- Optional-event decisions (phase 2) ---
# A per-OCCURRENCE choice for an event flagged optional in its event config:
# (google_id of the instance or series, event date) -> 'attend' | 'skip'.
# Deliberately a separate table from event_configs: a decision is what the
# family chose THAT DAY, a config is what the event IS — and a programmatic
# decision write must never clobber the series config's passengers/attendance.

def get_optional_decisions() -> List[dict]:
    with db_lock:
        return [dict(r) for r in optional_decisions_table.all()]

def get_optional_decision(google_ids, date: str) -> Optional[str]:
    """The decision for one occurrence. `google_ids` is the candidate id list
    (instance id first, then the recurring series id) — first hit wins,
    mirroring the event-config lookup order."""
    ids = [str(g) for g in google_ids if g]
    with db_lock:
        rows = optional_decisions_table.search(Query().date == date)
    for gid in ids:
        for r in rows:
            if r.get('google_id') == gid:
                return r.get('decision')
    return None

def set_optional_decision(google_id: str, date: str, decision: str,
                          decided_by: str = None):
    import time as _time
    q = Query()
    with db_lock:
        optional_decisions_table.remove((q.google_id == google_id) & (q.date == date))
        if decision in ('attend', 'skip'):
            optional_decisions_table.insert({
                'google_id': google_id, 'date': date, 'decision': decision,
                'decided_by': decided_by, 'ts': _time.time()})

def prune_optional_decisions(before_date: str):
    """Decisions expire with the day — yesterday's 'skip' says nothing about
    next week's occurrence."""
    with db_lock:
        optional_decisions_table.remove(Query().date < before_date)

# --- Event cancellations ---
# Same keying as optional decisions (instance google id first, series id as
# fallback, plus the occurrence date) — but rows are HISTORY, not state that
# expires: an active row (restored_at None) is the tombstone that keeps a
# canceled occurrence out of the solve and suppresses the ICS resurrection;
# a restored row is the paper trail.

def get_event_cancellations(active_only: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in event_cancellations_table.all()]
    if active_only:
        rows = [r for r in rows if not r.get('restored_at')]
    rows.sort(key=lambda r: (r.get('date') or '', r.get('ts') or 0), reverse=True)
    return rows

def get_event_cancellation(google_ids, date: str) -> Optional[dict]:
    """The ACTIVE cancellation for one occurrence, first candidate id wins —
    mirrors get_optional_decision."""
    ids = [str(g) for g in google_ids if g]
    with db_lock:
        rows = [dict(r) for r in event_cancellations_table.search(Query().date == date)]
    for gid in ids:
        for r in rows:
            if r.get('google_id') == gid and not r.get('restored_at'):
                return r
    return None

def any_event_cancellation(google_ids, date: str) -> Optional[dict]:
    """Active OR restored — the feed detector must not re-cancel an
    occurrence a person deliberately restored."""
    ids = [str(g) for g in google_ids if g]
    with db_lock:
        rows = [dict(r) for r in event_cancellations_table.search(Query().date == date)]
    for gid in ids:
        for r in rows:
            if r.get('google_id') == gid:
                return r
    return None

def add_event_cancellation(rec: dict) -> dict:
    import time as _time
    rec = dict(rec)
    rec.setdefault('ts', _time.time())
    rec.setdefault('restored_at', None)
    with db_lock:
        event_cancellations_table.insert(rec)
    return rec

def restore_event_cancellation(google_ids, date: str) -> Optional[dict]:
    """Mark the active row restored (never delete — the record is the point).
    Returns the row that was restored, or None."""
    import time as _time
    rec = get_event_cancellation(google_ids, date)
    if not rec:
        return None
    q = Query()
    with db_lock:
        event_cancellations_table.update(
            {'restored_at': _time.time()},
            (q.google_id == rec['google_id']) & (q.date == date))
    rec['restored_at'] = _time.time()
    return rec

# --- Outside hands (load arc A1) ---
# Contacts who do work for this household without holding the app, and the
# work they cover. Assignments are keyed by event_id — one covered event has
# exactly one contact, the same shape `overrides` uses for drivers.

def get_assist_contacts(include_inactive: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(c) for c in assist_contacts_table.all()]
    if not include_inactive:
        rows = [c for c in rows if c.get('active', True)]
    rows.sort(key=lambda c: (c.get('name') or '').lower())
    return rows

def get_assist_contact(contact_id: str) -> Optional[dict]:
    if not contact_id:
        return None
    with db_lock:
        res = assist_contacts_table.search(Query().id == contact_id)
        return dict(res[0]) if res else None

def add_assist_contact(data: dict) -> str:
    with db_lock:
        assist_contacts_table.insert(data)
        return data['id']

def update_assist_contact(contact_id: str, data: dict) -> bool:
    with db_lock:
        return bool(assist_contacts_table.update(data, Query().id == contact_id))

def delete_assist_contact(contact_id: str):
    """Remove the contact AND the coverage that pointed at them — a covered
    event whose contact no longer exists would read as unassigned everywhere
    and quietly re-enter the solver, which is the false alarm this feature is
    here to kill."""
    with db_lock:
        gone = [dict(a) for a in assist_assignments_table.search(Query().contact_id == contact_id)]
        assist_contacts_table.remove(Query().id == contact_id)
        assist_assignments_table.remove(Query().contact_id == contact_id)
    # The history keeps them: deleting a contact removes them from the app, not
    # from what actually happened.
    for a in gone:
        add_assist_history({'event_id': a.get('event_id'), 'contact_id': contact_id,
                            'scope': a.get('scope') or 'instance',
                            'event_date': a.get('event_date') or '',
                            'event_title': a.get('event_title') or '',
                            'action': 'contact_deleted', 'actor': ''})

def get_assist_assignments() -> List[dict]:
    """The ACTIVE table only — coverage that can still affect a solve. Past
    instance rows live in `assist_history` and are never read here, which is
    what keeps this O(current arrangements) instead of O(every carpool the
    family has ever agreed to)."""
    with db_lock:
        return [dict(a) for a in assist_assignments_table.all()]

def get_assist_assignment_map() -> dict:
    """{key: contact_id} where key is either an instance event_id or a bare
    recurring series google id. Callers resolve an event against BOTH via
    `services.assist.coverage_for` — instance wins, so "Emma's mom has
    Tuesdays, except this one" is expressible."""
    return {a['event_id']: a['contact_id'] for a in get_assist_assignments()
            if a.get('event_id') and a.get('contact_id')}

def add_assist_history(row: dict) -> dict:
    """Append-only. Every coverage change lands here and nothing ever deletes
    from it: the family's history of who carried what is the point, and the
    active table stays small precisely because this one absorbs the past."""
    import time as _time
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'ts': _time.time(), **row}
    with db_lock:
        assist_history_table.insert(row)
    return row

def set_assist_assignment(event_id: str, contact_id: str, note: str = "",
                          scope: str = 'instance', event_date: str = None,
                          event_title: str = None, actor: str = None) -> dict:
    """One contact per key: setting replaces rather than stacking.

    `event_date` is stored rather than derived because archiving must be a
    date comparison over this table alone — looking the date up from the
    schedule would make the sweep depend on a solve, and a series row has no
    single date to look up in the first place."""
    import time as _time
    import uuid as _uuid
    scope = 'series' if scope == 'series' else 'instance'
    row = {'id': _uuid.uuid4().hex, 'event_id': event_id, 'contact_id': contact_id,
           'note': note or "", 'scope': scope, 'event_date': event_date or '',
           'event_title': event_title or '', 'created_at': _time.time()}
    with db_lock:
        assist_assignments_table.remove(Query().event_id == event_id)
        assist_assignments_table.insert(row)
    add_assist_history({'event_id': event_id, 'contact_id': contact_id,
                        'scope': scope, 'event_date': event_date or '',
                        'event_title': event_title or '', 'action': 'covered',
                        'actor': actor or ''})
    return row

def clear_assist_assignment(event_id: str, actor: str = None) -> bool:
    with db_lock:
        gone = [dict(a) for a in assist_assignments_table.search(Query().event_id == event_id)]
        removed = bool(assist_assignments_table.remove(Query().event_id == event_id))
    for a in gone:
        add_assist_history({'event_id': event_id, 'contact_id': a.get('contact_id'),
                            'scope': a.get('scope') or 'instance',
                            'event_date': a.get('event_date') or '',
                            'event_title': a.get('event_title') or '',
                            'action': 'cleared', 'actor': actor or ''})
    return removed

def archive_past_assist_assignments(before_date: str) -> int:
    """Move spent INSTANCE coverage out of the active table. A series row is a
    standing arrangement with no end date, so it never archives — it leaves
    only when somebody clears it. An instance row for a day that has passed
    can no longer change any solve, and keeping it would make every refresh
    pay for every carpool ride the family has ever taken."""
    if not before_date:
        return 0
    with db_lock:
        rows = [dict(a) for a in assist_assignments_table.all()]
    doomed = [a for a in rows
              if (a.get('scope') or 'instance') != 'series'
              and (a.get('event_date') or '') and a['event_date'] < before_date]
    for a in doomed:
        add_assist_history({'event_id': a.get('event_id'), 'contact_id': a.get('contact_id'),
                            'scope': a.get('scope') or 'instance',
                            'event_date': a.get('event_date') or '',
                            'event_title': a.get('event_title') or '',
                            'action': 'archived', 'actor': ''})
    if doomed:
        with db_lock:
            for a in doomed:
                assist_assignments_table.remove(Query().id == a['id'])
    return len(doomed)

def get_assist_history(contact_id: str = None, since_ts: float = None,
                       limit: int = 200) -> List[dict]:
    """Newest first. The record the family can be shown later — who covered
    what, when it was agreed, and when it came back."""
    with db_lock:
        rows = [dict(a) for a in assist_history_table.all()]
    if contact_id:
        rows = [r for r in rows if r.get('contact_id') == contact_id]
    if since_ts:
        rows = [r for r in rows if (r.get('ts') or 0) >= since_ts]
    rows.sort(key=lambda r: r.get('ts') or 0, reverse=True)
    return rows[:max(1, int(limit or 200))]

# --- Protected commitments (load arc A6) ---

def get_protected_commitments(member_id: str = None,
                              include_inactive: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(c) for c in protected_commitments_table.all()]
    if member_id:
        rows = [c for c in rows if c.get('member_id') == member_id]
    if not include_inactive:
        rows = [c for c in rows if c.get('active', True)]
    rows.sort(key=lambda c: (c.get('title') or '').lower())
    return rows

def add_protected_commitment(data: dict) -> str:
    # Cache invalidation on every mutation, same as status days: a protected
    # window moves driver availability, and a stale cache would keep placing
    # drives inside the very evening this exists to defend.
    with db_lock:
        protected_commitments_table.insert(data)
        _invalidate_schedule_caches()
    return data['id']

def update_protected_commitment(commitment_id: str, data: dict) -> bool:
    with db_lock:
        ok = bool(protected_commitments_table.update(data, Query().id == commitment_id))
        if ok:
            _invalidate_schedule_caches()
    return ok

def delete_protected_commitment(commitment_id: str):
    with db_lock:
        protected_commitments_table.remove(Query().id == commitment_id)
        _invalidate_schedule_caches()

# --- Needs You findings ---
# Storage only. The lifecycle rules (what opens, what auto-closes, what never
# reopens) live in services/findings.py — this layer holds rows and nothing
# else, so the sweep's semantics are readable in one file.

def get_findings(state: str = None, kind: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(f) for f in findings_table.all()]
    if state:
        rows = [f for f in rows if f.get('state') == state]
    if kind:
        rows = [f for f in rows if f.get('kind') == kind]
    rows.sort(key=lambda f: f.get('created_at') or 0)
    return rows

def get_finding(finding_id: str) -> Optional[dict]:
    if not finding_id:
        return None
    with db_lock:
        res = findings_table.search(Query().id == finding_id)
        return dict(res[0]) if res else None

def get_finding_by_identity(identity: str) -> Optional[dict]:
    """The row for this (kind, subject), whatever state it is in — the dismissed
    ones matter most here: they are how a settled answer stays settled."""
    if not identity:
        return None
    with db_lock:
        res = findings_table.search(Query().identity == identity)
    if not res:
        return None
    rows = sorted((dict(r) for r in res), key=lambda f: f.get('created_at') or 0)
    return rows[-1]

def add_finding(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'created_at': time.time(), 'state': 'open',
           **data}
    with db_lock:
        findings_table.insert(row)
    return row['id']

def update_finding(finding_id: str, data: dict) -> bool:
    with db_lock:
        return bool(findings_table.update(data, Query().id == finding_id))

def prune_findings(before_ts: float) -> int:
    """Resolved rows older than the cutoff. Open rows are NEVER pruned — an
    open finding is live state, and age is not a reason to forget it."""
    with db_lock:
        rows = [dict(f) for f in findings_table.all()]
        doomed = [f['id'] for f in rows
                  if f.get('state') != 'open'
                  and (f.get('resolved_at') or f.get('created_at') or 0) < before_ts]
        for fid in doomed:
            findings_table.remove(Query().id == fid)
    return len(doomed)

# --- Mind (noticings queue + insights lane) ---

def add_mind_noticing(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'ts': time.time(), 'consumed_at': None, **data}
    with db_lock:
        mind_noticings_table.insert(row)
    return row['id']

def get_mind_noticings(consumed: bool = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in mind_noticings_table.all()]
    if consumed is True:
        rows = [r for r in rows if r.get('consumed_at')]
    elif consumed is False:
        rows = [r for r in rows if not r.get('consumed_at')]
    rows.sort(key=lambda r: r.get('ts') or 0)
    return rows

def consume_mind_noticings(ids: List[str]) -> int:
    now = time.time()
    n = 0
    with db_lock:
        for nid in ids:
            n += len(mind_noticings_table.update({'consumed_at': now},
                                                 Query().id == nid))
    return n

def mark_mind_noticings_checked(ids: List[str]) -> int:
    """Promoter rung (Task 4): marks noticings as already asked-about, so a
    held/errored promote call doesn't re-ask the same urgent line forever."""
    n = 0
    with db_lock:
        for nid in ids:
            n += len(mind_noticings_table.update({'promoted_checked': True},
                                                 Query().id == nid))
    return n

def add_mind_insight(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'created_ts': time.time(), 'state': 'active',
           'outcome': None, 'resolved_ts': None, 'sensitivity': 'normal',
           'detail': '', 'domain': '', 'proposal_json': None, 'confidence': None,
           **data}
    with db_lock:
        mind_insights_table.insert(row)
    return row['id']

def update_mind_insight(insight_id: str, data: dict) -> bool:
    with db_lock:
        return bool(mind_insights_table.update(data, Query().id == insight_id))

def get_mind_insights(state: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in mind_insights_table.all()]
    if state:
        rows = [r for r in rows if r.get('state') == state]
    rows.sort(key=lambda r: r.get('created_ts') or 0)
    return rows

def get_mind_insight_by_slug(slug: str) -> Optional[dict]:
    with db_lock:
        res = mind_insights_table.search(Query().slug == slug)
        return dict(res[0]) if res else None

def prune_mind(insights_before_ts: float, noticings_before_ts: float = None) -> int:
    """Old noticings and old RETIRED insights, each on its own clock (spec:
    noticings 14d, retired insights 120d). Active insights are live state and
    never pruned — same rule as findings."""
    if noticings_before_ts is None:
        noticings_before_ts = insights_before_ts
    doomed = 0
    with db_lock:
        for r in [dict(x) for x in mind_noticings_table.all()]:
            if (r.get('ts') or 0) < noticings_before_ts:
                mind_noticings_table.remove(Query().id == r['id'])
                doomed += 1
        for r in [dict(x) for x in mind_insights_table.all()]:
            if r.get('state') != 'active' \
                    and (r.get('resolved_ts') or r.get('created_ts') or 0) \
                    < insights_before_ts:
                mind_insights_table.remove(Query().id == r['id'])
                doomed += 1
    return doomed

# --- Coverage asks (findings arc, slice 2) ---

def get_coverage_asks(state: str = None, event_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(a) for a in coverage_asks_table.all()]
    if state:
        rows = [a for a in rows if a.get('state') == state]
    if event_id:
        rows = [a for a in rows if a.get('event_id') == event_id]
    rows.sort(key=lambda a: a.get('asked_at') or 0)
    return rows

def get_coverage_ask(ask_id: str) -> Optional[dict]:
    if not ask_id:
        return None
    with db_lock:
        res = coverage_asks_table.search(Query().id == ask_id)
        return dict(res[0]) if res else None

def add_coverage_ask(data: dict) -> str:
    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'asked_at': time.time(), 'state': 'waiting',
           'nudges_sent': 0, **data}
    with db_lock:
        coverage_asks_table.insert(row)
    return row['id']

def update_coverage_ask(ask_id: str, data: dict) -> bool:
    with db_lock:
        return bool(coverage_asks_table.update(data, Query().id == ask_id))

# --- Requests (load arc A3) ---
# An ask with a state. A request is ALWAYS answered: silence is the failure
# mode this exists to fix.

def get_requests(status: str = None, to_member: str = None,
                 from_member: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in requests_table.all()]
    if status:
        rows = [r for r in rows if r.get('status') == status]
    if to_member:
        # An unaddressed request is FOR the household, so it belongs in every
        # adult's list — "somebody please take this" must not sit in nobody's.
        rows = [r for r in rows
                if r.get('to_member') == to_member or not r.get('to_member')]
    if from_member:
        rows = [r for r in rows if r.get('from_member') == from_member]
    rows.sort(key=lambda r: r.get('created_at') or 0, reverse=True)
    return rows

def get_request(request_id: str) -> Optional[dict]:
    with db_lock:
        res = requests_table.search(Query().id == request_id)
        return dict(res[0]) if res else None

def add_request(data: dict) -> str:
    with db_lock:
        requests_table.insert(data)
        return data['id']

def update_request(request_id: str, data: dict) -> bool:
    with db_lock:
        return bool(requests_table.update(data, Query().id == request_id))

def expire_stale_requests(now_ts: float = None) -> List[dict]:
    """Anything past its expiry becomes `expired` — LOUDLY, not silently.
    Callers announce it: an ask that just fades away is the exact failure this
    object exists to prevent."""
    import time as _time
    now_ts = now_ts or _time.time()
    expired = []
    for r in get_requests(status='open'):
        if r.get('expires_at') and r['expires_at'] <= now_ts:
            update_request(r['id'], {'status': 'expired'})
            r['status'] = 'expired'
            expired.append(r)
    return expired

# --- Household tasks (load arc A2) ---
# Work with a deadline and no destination. Task = do something, errand = go
# somewhere; keeping that line crisp is what keeps "renew the passports" out
# of the solver's Tuesday.

def get_household_tasks(assigned_to: str = None, include_done: bool = False,
                        unassigned_only: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(t) for t in household_tasks_table.all()]
    if assigned_to:
        rows = [t for t in rows if t.get('assigned_to') == assigned_to]
    if unassigned_only:
        rows = [t for t in rows if not t.get('assigned_to')]
    if not include_done:
        rows = [t for t in rows if t.get('status') != 'done']
    # Dated work first, in date order; undated work after it. A task with no
    # deadline is real ("sort the garage") but it must never push a dated one
    # down the list.
    rows.sort(key=lambda t: (t.get('due_date') or '9999-99-99',
                             (t.get('title') or '').lower()))
    return rows

def get_household_task(task_id: str) -> Optional[dict]:
    with db_lock:
        res = household_tasks_table.search(Query().id == task_id)
        return dict(res[0]) if res else None

def add_household_task(data: dict) -> str:
    with db_lock:
        household_tasks_table.insert(data)
        return data['id']

def update_household_task(task_id: str, data: dict) -> bool:
    with db_lock:
        return bool(household_tasks_table.update(data, Query().id == task_id))

def delete_household_task(task_id: str):
    with db_lock:
        household_tasks_table.remove(Query().id == task_id)

def _next_due(due_date: str, recurrence: str) -> Optional[str]:
    """The next occurrence after `due_date`. Yearly is the one that matters
    here — errands cannot express it, and annual is exactly the life-admin
    cadence (inspection, physicals, passports, registration windows)."""
    import datetime as _dt
    if not due_date or recurrence in (None, '', 'none'):
        return None
    try:
        d = _dt.date.fromisoformat(due_date)
    except ValueError:
        return None
    if recurrence == 'daily':
        return (d + _dt.timedelta(days=1)).isoformat()
    if recurrence == 'weekly':
        return (d + _dt.timedelta(days=7)).isoformat()
    if recurrence == 'monthly':
        month = d.month + 1
        year = d.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        # Clamp the day: the 31st of a 30-day month is the 30th, not a crash.
        import calendar as _cal
        day = min(d.day, _cal.monthrange(year, month)[1])
        return _dt.date(year, month, day).isoformat()
    if recurrence == 'yearly':
        try:
            return d.replace(year=d.year + 1).isoformat()
        except ValueError:           # 29 Feb into a common year
            return d.replace(year=d.year + 1, day=28).isoformat()
    return None

def complete_household_task(task_id: str, done: bool = True,
                            member_id: str = None) -> Optional[dict]:
    """Completing a recurring task closes this one and opens the next, the
    same shape recurring errands use — regenerate on completion rather than
    scheduling the whole series ahead."""
    import time as _time
    import uuid as _uuid
    with db_lock:
        res = household_tasks_table.search(Query().id == task_id)
        if not res:
            return None
        row = dict(res[0])
        patch = {'status': 'done' if done else 'open',
                 'completed_at': _time.time() if done else None,
                 'completed_by': member_id if done else None}
        household_tasks_table.update(patch, Query().id == task_id)
        row.update(patch)
        follow = None
        if done and row.get('recurrence') not in (None, '', 'none'):
            nxt = _next_due(row.get('due_date'), row.get('recurrence'))
            if nxt:
                follow = dict(row)
                follow.update({'id': _uuid.uuid4().hex, 'due_date': nxt,
                               'status': 'open', 'completed_at': None,
                               'completed_by': None, 'created_at': _time.time()})
                household_tasks_table.insert(follow)
    if follow:
        row['next_task_id'] = follow['id']
        row['next_due_date'] = follow['due_date']
    return row

# --- Threads: open loops with people outside the family ---

def get_thread(thread_id: str) -> Optional[dict]:
    with db_lock:
        res = threads_table.search(Query().id == thread_id)
        return dict(res[0]) if res else None

def add_thread(data: dict) -> str:
    from models.schemas import Thread
    with db_lock:
        # Build through Thread model to apply all defaults
        thread = Thread(**data)
        row = thread.model_dump()
        threads_table.insert(row)
        return row['id']

def get_threads(state: str = None, owner: str = None, include_closed: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(t) for t in threads_table.all()]

    # Filter by state if provided
    if state:
        rows = [t for t in rows if t.get('state') == state]

    # Filter by owner if provided
    if owner:
        rows = [t for t in rows if t.get('owner_member_id') == owner]

    # Filter out closed threads unless requested
    if not include_closed:
        rows = [t for t in rows if t.get('state') not in ('done', 'dropped')]

    # Sort by next_action_at (None last) then created_at
    rows.sort(key=lambda t: (
        (t.get('next_action_at') or '9999-99-99'),
        t.get('created_at', 0)
    ))

    return rows

def update_thread(thread_id: str, data: dict) -> bool:
    with db_lock:
        return bool(threads_table.update(data, Query().id == thread_id))

def append_thread_history(thread_id: str, entry: dict) -> bool:
    with db_lock:
        res = threads_table.search(Query().id == thread_id)
        if not res:
            return False
        row = dict(res[0])
        # Stamp ts if not present
        if 'ts' not in entry:
            entry['ts'] = time.time()
        # Append to history
        row['history'].append(entry)
        threads_table.update({'history': row['history']}, Query().id == thread_id)
        return True

def delete_thread(thread_id: str):
    with db_lock:
        threads_table.remove(Query().id == thread_id)

# --- Shopping lists (meals & provisioning arc M1) ---
# A STANDING list bound to a recurring errand by TAG, never by errand id: the
# errand regenerates each cycle, the list outlives all of them. Items are
# individually addressable — there is no whole-list write anywhere in this
# module, which is what makes two people shopping at once safe.
# See docs/meal_design.md §M1.

def get_shopping_lists() -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in shopping_lists_table.all()]
    rows.sort(key=lambda l: (not l.get('is_default'), (l.get('name') or '').lower()))
    return rows

def get_shopping_list(list_id: str) -> Optional[dict]:
    with db_lock:
        res = shopping_lists_table.search(Query().id == list_id)
        return dict(res[0]) if res else None

def add_shopping_list(data: dict) -> str:
    with db_lock:
        shopping_lists_table.insert(data)
        return data['id']

def update_shopping_list(list_id: str, data: dict) -> bool:
    with db_lock:
        return bool(shopping_lists_table.update(data, Query().id == list_id))

def delete_shopping_list(list_id: str):
    with db_lock:
        shopping_lists_table.remove(Query().id == list_id)
        shopping_items_table.remove(Query().list_id == list_id)

def ensure_default_shopping_list() -> dict:
    """The list every capture path falls back to when no list is named.
    Created on first use so a fresh install never 404s a voice add."""
    from models.schemas import ShoppingList
    lists = get_shopping_lists()
    for l in lists:
        if l.get('is_default'):
            return l
    if lists:
        update_shopping_list(lists[0]['id'], {'is_default': True})
        lists[0]['is_default'] = True
        return lists[0]
    fresh = ShoppingList(name="Groceries", is_default=True,
                         errand_tag="groceries").model_dump()
    add_shopping_list(fresh)
    return fresh

def get_shopping_items(list_id: str = None, include_checked: bool = True) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in (
            shopping_items_table.search(Query().list_id == list_id) if list_id
            else shopping_items_table.all())]
    if not include_checked:
        rows = [i for i in rows if not i.get('is_checked')]
    # unchecked first, then oldest-first within each group: the shopping order
    # is the order things were remembered, and checked items sink out of the way.
    rows.sort(key=lambda i: (bool(i.get('is_checked')), i.get('created_at') or 0))
    return rows

def get_shopping_item(item_id: str) -> Optional[dict]:
    with db_lock:
        res = shopping_items_table.search(Query().id == item_id)
        return dict(res[0]) if res else None

def find_open_shopping_item(list_id: str, name: str) -> Optional[dict]:
    """Case-insensitive match against UNCHECKED items on a list. Saying 'milk'
    twice should not put milk on the list twice; a re-add after checking off
    is a genuinely new need, so checked rows never match."""
    low = (name or '').strip().lower()
    if not low:
        return None
    for it in get_shopping_items(list_id, include_checked=False):
        if (it.get('name') or '').strip().lower() == low:
            return it
    return None

def add_shopping_item(data: dict) -> str:
    with db_lock:
        shopping_items_table.insert(data)
        return data['id']

def update_shopping_item(item_id: str, data: dict) -> bool:
    """The ONLY item write path. Per-item merge, so concurrent edits to
    different items on the same list cannot clobber one another."""
    with db_lock:
        return bool(shopping_items_table.update(data, Query().id == item_id))

def delete_shopping_item(item_id: str):
    with db_lock:
        shopping_items_table.remove(Query().id == item_id)

def check_shopping_item(item_id: str, checked: bool = True,
                        by_member_id: str = None) -> Optional[dict]:
    """Idempotent: re-checking an already-checked item is a no-op success, so
    two phones tapping the same row race harmlessly."""
    import time as _time
    with db_lock:
        res = shopping_items_table.search(Query().id == item_id)
        if not res:
            return None
        was_checked = bool(res[0].get('is_checked'))
        patch = {'is_checked': bool(checked),
                 'checked_at': _time.time() if checked else None,
                 'checked_by': by_member_id if checked else None}
        shopping_items_table.update(patch, Query().id == item_id)
        out = dict(res[0])
        out.update(patch)
    # Checking off is the ONLY moment the app learns what this household
    # actually buys — and clear_checked_shopping_items then deletes the row, so
    # without a tally here the history is destroyed every shop. Counted outside
    # the lock, and only on the false->true edge so re-checking a row that two
    # phones both tapped does not inflate it.
    if checked and not was_checked:
        record_purchase(out.get('name'))
        return out

def record_purchase(name: str, when: float = None) -> None:
    """Tally what the household really buys, by normalized name.

    Kept in app_state rather than as rows: this is a small, bounded frequency
    table (a family buys ~50 things), it is never joined against anything, and
    it has to outlive the shopping items themselves — which are deleted on
    every post-shop sweep.
    """
    import time as _time
    key = ' '.join((name or '').strip().lower().split())
    if not key:
        return
    tally = dict(get_app_state('purchase_tally') or {})
    row = dict(tally.get(key) or {})
    row['count'] = int(row.get('count') or 0) + 1
    row['last_at'] = when or _time.time()
    row['label'] = (name or '').strip()
    tally[key] = row
    # Bounded: keep the 200 most recently bought so a decade of one-offs never
    # crowds out the weekly staples.
    if len(tally) > 200:
        keep = sorted(tally.items(), key=lambda kv: kv[1].get('last_at') or 0,
                      reverse=True)[:200]
        tally = dict(keep)
    set_app_state('purchase_tally', tally)


def get_purchase_tally() -> dict:
    return dict(get_app_state('purchase_tally') or {})


def clear_checked_shopping_items(list_id: str) -> int:
    """Sweep after a shop. Returns how many went."""
    doomed = [i['id'] for i in get_shopping_items(list_id) if i.get('is_checked')]
    with db_lock:
        for iid in doomed:
            shopping_items_table.remove(Query().id == iid)
    return len(doomed)

def find_shopping_lists_for_errand(errand: dict) -> List[dict]:
    """Lists bound to an errand. Tag match is the contract (errand_tag against
    Errand.tags); store==location is a convenience fallback so a list still
    finds its errand before anyone has thought about tags."""
    if not errand:
        return []
    tags = {str(t).strip().lower() for t in (errand.get('tags') or []) if str(t).strip()}
    loc = (errand.get('location') or '').strip().lower()
    out = []
    for l in get_shopping_lists():
        tag = (l.get('errand_tag') or '').strip().lower()
        store = (l.get('store') or '').strip().lower()
        if (tag and tag in tags) or (store and loc and store == loc):
            out.append(l)
    return out

# --- Meal repertoire (meals & provisioning arc M3) ---
# Fit, not method. See docs/meal_design.md §M3 and models.schemas.Meal.

def get_meals(include_inactive: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(m) for m in meals_table.all()]
    if not include_inactive:
        rows = [m for m in rows if m.get('is_active', True)]
    # Least-recently-served first: rotation is the point of last_served_at.
    rows.sort(key=lambda m: (m.get('last_served_at') or 0, (m.get('name') or '').lower()))
    return rows

def get_meal(meal_id: str) -> Optional[dict]:
    with db_lock:
        res = meals_table.search(Query().id == meal_id)
        return dict(res[0]) if res else None

def find_meal_by_name(name: str) -> Optional[dict]:
    low = (name or '').strip().lower()
    if not low:
        return None
    rows = get_meals(include_inactive=True)
    for m in rows:
        if (m.get('name') or '').strip().lower() == low:
            return m
    for m in rows:
        if low in (m.get('name') or '').strip().lower():
            return m
    return None

def add_meal(data: dict) -> str:
    with db_lock:
        meals_table.insert(data)
        return data['id']

def update_meal(meal_id: str, data: dict) -> bool:
    with db_lock:
        return bool(meals_table.update(data, Query().id == meal_id))

def delete_meal(meal_id: str):
    with db_lock:
        meals_table.remove(Query().id == meal_id)

def mark_meal_served(meal_id: str, when: float = None) -> Optional[dict]:
    """Set where attention already is — the surface that SUGGESTED the meal
    offers a one-tap 'we had this'. Rotation maintains itself or it does not
    get maintained."""
    import time as _time
    if not update_meal(meal_id, {'last_served_at': when or _time.time()}):
        return None
    return get_meal(meal_id)

# --- Dishes (meals arc M4) ---
# The unit of WORK. Reused across meals, so they are stored once and
# referenced by MealSlot.dish_ids. See models.schemas.Dish.

# --- Dish categories (v2.108: the family's own plate vocabulary) ---

# The fixed taxonomy this replaces, and what each old value becomes. Seeding
# from the repertoire rather than handing the family a blank slate is the whole
# difference between "one-time setup" and "re-enter your 25 dishes".
_LEGACY_CATEGORY_SEED = [
    # (key, name, description, from-type, from-side_type)
    ('protein', 'protein',
     'the main source of protein — meat, fish, beans, eggs, tofu, a protein pasta',
     'entree', None),
    ('vegetable', 'vegetables', 'vegetables, cooked or raw', 'side', 'vegetable'),
    ('starch', 'starches/carbs',
     'rice, potatoes, pasta, bread and other carbohydrates', 'side', 'starch'),
    ('salad', 'salad', 'a green or cold salad', 'side', 'salad'),
    ('other', 'other', 'anything else that goes alongside', 'side', 'other'),
    ('sweet', 'something sweet',
     'fruit, a cookie, ice cream — whatever ends a meal', 'dessert', None),
]


def ensure_dish_categories():
    """Seed the family's categories from the repertoire they already have.

    ONE-SHOT, stamped in app_state: a family that deletes "salad" must not find
    it resurrected on the next boot. Only categories that actually describe a
    dish they own are created, so nobody inherits an empty "other".

    The seeded ranges reproduce the old behavior as closely as a richer model
    can: one protein, `sides_per_meal` worth of sides distributed vegetables
    first, and something sweet iff `include_dessert` was on. All of it is then
    editable, which is the point.
    """
    import uuid as _uuid
    import time
    with db_lock:
        if get_app_state('dish_categories_seeded'):
            return
        dishes = [dict(d) for d in dishes_table.all()]
        if not dishes and not dish_categories_table.all():
            # Fresh install: seed the common shape so day one is not a blank
            # slate either, but leave it entirely editable.
            wanted = ['protein', 'vegetable', 'starch', 'sweet']
        else:
            wanted = []
            for key, _n, _d, from_type, from_side in _LEGACY_CATEGORY_SEED:
                for d in dishes:
                    if (d.get('type') or 'side') != from_type:
                        continue
                    if from_side and (d.get('side_type') or 'other') != from_side:
                        continue
                    wanted.append(key)
                    break
        if not wanted:
            set_app_state('dish_categories_seeded', True)
            return

        settings = get_settings() or {}
        try:
            sides_n = max(0, min(6, int(settings.get('sides_per_meal', 2))))
        except (TypeError, ValueError):
            sides_n = 2
        dessert_on = settings.get('include_dessert')
        dessert_on = True if dessert_on is None else bool(dessert_on)

        # Idempotent by NAME as well as by stamp. The stamp alone was enough
        # only while nothing ever cleared it; a second run then created a
        # duplicate "protein" rather than doing nothing, and two categories of
        # the same name are indistinguishable to everyone except the composer.
        existing = {str(c.get('name') or '').strip().lower(): dict(c)
                    for c in dish_categories_table.all()}
        by_key, order = {}, len(existing)
        remaining_sides = sides_n
        for key, name, desc, _ft, _fs in _LEGACY_CATEGORY_SEED:
            if key not in wanted:
                continue
            prior = existing.get(name.strip().lower())
            if prior:
                by_key[key] = prior['id']
                continue
            if key == 'protein':
                lo, hi, with_meal = 1, 1, False
            elif key == 'sweet':
                lo, hi, with_meal = (1 if dessert_on else 0), 1, True
            else:
                lo = 1 if remaining_sides > 0 else 0
                remaining_sides -= lo
                hi = lo + 1
                with_meal = False
            rec = {'id': _uuid.uuid4().hex, 'name': name, 'description': desc,
                   'min_per_plate': lo, 'max_per_plate': hi,
                   'with_complete_meal': with_meal, 'is_main': key == 'protein',
                   'order': order,
                   'created_at': time.time()}
            dish_categories_table.insert(rec)
            by_key[key] = rec['id']
            order += 1

        # Assign every existing dish, and collapse the old type vocabulary:
        # everything that is not a whole meal is simply a dish now.
        for d in dishes:
            old_type = d.get('type') or 'side'
            patch = {}
            if old_type == 'meal':
                patch['type'] = 'meal'
            else:
                patch['type'] = 'dish'
            if not (d.get('category_ids') or []):
                cid = None
                if old_type == 'entree':
                    cid = by_key.get('protein')
                elif old_type == 'dessert':
                    cid = by_key.get('sweet')
                elif old_type == 'side':
                    cid = by_key.get(d.get('side_type') or 'other') or by_key.get('other')
                if cid:
                    patch['category_ids'] = [cid]
            if d.get('id'):
                dishes_table.update(patch, Query().id == d['id'])
        set_app_state('dish_categories_seeded', True)


def get_dish_categories() -> List[dict]:
    """The family's blocks, MAIN FIRST — and the main is a stored flag.

    `is_main` is data rather than position because position here is an
    accident: ties on `order` fall back to NAME, so renaming a category could
    silently promote it. The invariant (exactly one main) is defended at the
    read: none flagged promotes the first block — which is also the zero-cost
    migration for every install predating the flag — and several flagged
    keeps the first. Returning the main first is what keeps "the first block
    is the main dish" true on every screen.
    """
    with db_lock:
        rows = [dict(c) for c in dish_categories_table.all()]
    rows.sort(key=lambda c: (c.get('order') or 0,
                             (c.get('name') or '').lower()))
    mains = [c for c in rows if c.get('is_main')]
    if rows and len(mains) != 1:
        keep = (mains[0] if mains else rows[0])['id']
        with db_lock:
            for c in rows:
                want = c['id'] == keep
                if bool(c.get('is_main')) != want:
                    dish_categories_table.update({'is_main': want},
                                                 Query().id == c['id'])
                c['is_main'] = want
    rows.sort(key=lambda c: (0 if c.get('is_main') else 1,
                             c.get('order') or 0,
                             (c.get('name') or '').lower()))
    return rows


def set_main_dish_category(cat_id: str) -> None:
    """Exclusive by construction: flag one, clear the rest."""
    with db_lock:
        for c in dish_categories_table.all():
            dish_categories_table.update({'is_main': c.get('id') == cat_id},
                                         doc_ids=[c.doc_id])
        mark_all_daily_schedules_dirty()

def get_dish_category(cat_id: str) -> Optional[dict]:
    with db_lock:
        res = dish_categories_table.search(Query().id == cat_id)
        return dict(res[0]) if res else None

def save_dish_category(data: dict) -> dict:
    with db_lock:
        dish_categories_table.upsert(data, Query().id == data['id'])
        mark_all_daily_schedules_dirty()
    return data

def delete_dish_category(cat_id: str) -> int:
    """Removing a category unassigns it from every dish. A dish left with no
    category is not deleted — it simply fills no slot until somebody says what
    it is, which is visible in the editor rather than silent."""
    touched = 0
    with db_lock:
        dish_categories_table.remove(Query().id == cat_id)
        for d in dishes_table.all():
            ids = d.get('category_ids') or []
            if cat_id in ids:
                dishes_table.update({'category_ids': [i for i in ids if i != cat_id]},
                                    doc_ids=[d.doc_id])
                touched += 1
    return touched


def get_dishes(include_inactive: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(d) for d in dishes_table.all()]
    if not include_inactive:
        rows = [d for d in rows if d.get('is_active', True)]
    rows.sort(key=lambda d: ((d.get('role') or 'zzz'), (d.get('name') or '').lower()))
    return rows

def get_dish(dish_id: str) -> Optional[dict]:
    with db_lock:
        res = dishes_table.search(Query().id == dish_id)
        return dict(res[0]) if res else None

def get_dishes_by_ids(dish_ids: List[str]) -> List[dict]:
    by_id = {d['id']: d for d in get_dishes(include_inactive=True)}
    return [by_id[i] for i in (dish_ids or []) if i in by_id]

def find_dish_by_name(name: str) -> Optional[dict]:
    """Dishes are reused, so a name match is how a second meal picks up the
    rice the first one already defined."""
    low = (name or '').strip().lower()
    if not low:
        return None
    rows = get_dishes(include_inactive=True)
    for key in ('name', 'short_name'):
        for d in rows:
            if (d.get(key) or '').strip().lower() == low:
                return d
    for d in rows:
        if low in (d.get('name') or '').strip().lower():
            return d
    return None

def find_dish_for_reuse(name: str) -> Optional[dict]:
    """EXACT match only — the reuse path must not merge distinct dishes.

    `find_dish_by_name` falls back to substring so the agent can resolve "the
    potatoes", but reusing on a substring would let a later generic
    "potatoes" silently bind to "roasted russet potatoes" (and inherit its
    times, ingredients and any stale flag). Rice is rice; rice is not fried
    rice.
    """
    low = (name or '').strip().lower()
    if not low:
        return None
    for d in get_dishes(include_inactive=True):
        if (d.get('name') or '').strip().lower() == low:
            return d
    return None


def add_dish(data: dict) -> str:
    with db_lock:
        dishes_table.insert(data)
        return data['id']

def update_dish(dish_id: str, data: dict) -> bool:
    with db_lock:
        return bool(dishes_table.update(data, Query().id == dish_id))

def delete_dish(dish_id: str):
    with db_lock:
        dishes_table.remove(Query().id == dish_id)

def get_dishes_by_type(dish_type: str, side_type: str = None) -> List[dict]:
    rows = [d for d in get_dishes() if (d.get('type') or 'side') == dish_type]
    if side_type:
        rows = [d for d in rows if (d.get('side_type') or 'other') == side_type]
    return rows


# --- Tonight's plate (meals arc M5) ---
# Composed by rule, then edited freely. Dated, so it expires on its own.

def get_plate(date_str: str) -> Optional[dict]:
    with db_lock:
        res = plates_table.search(Query().date == date_str)
        return dict(res[0]) if res else None

def save_plate(data: dict) -> dict:
    with db_lock:
        plates_table.upsert(data, Query().date == data['date'])
    return data

def delete_plate(date_str: str):
    with db_lock:
        plates_table.remove(Query().date == date_str)

# --- Meal rules (arc M11) ---
# How this household eats, as opposed to what it eats. Small table, read on
# every compose, so it is loaded whole rather than queried per dish.

def get_meal_rules(include_disabled: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in meal_rules_table.all()]
    if not include_disabled:
        rows = [r for r in rows if r.get('is_enabled', True)]
    return sorted(rows, key=lambda r: (r.get('created_at') or 0))

def get_meal_rule(rule_id: str) -> Optional[dict]:
    with db_lock:
        res = meal_rules_table.search(Query().id == rule_id)
        return dict(res[0]) if res else None

def save_meal_rule(data: dict) -> dict:
    with db_lock:
        meal_rules_table.upsert(data, Query().id == data['id'])
    return data

def update_meal_rule(rule_id: str, patch: dict) -> bool:
    with db_lock:
        return bool(meal_rules_table.update(patch, Query().id == rule_id))

def delete_meal_rule(rule_id: str):
    with db_lock:
        meal_rules_table.remove(Query().id == rule_id)


# --- Walmart item mapping (arc W1) ---
# Keyed by NORMALIZED NAME, not by shopping item id: the family buys roughly
# the same fifty things forever, so the map is written once and reused by every
# future list, whether the line came from a meal, a photo or someone's voice.

def get_walmart_item(name_key: str) -> Optional[dict]:
    with db_lock:
        res = walmart_items_table.search(Query().name_key == name_key)
        return dict(res[0]) if res else None

def save_walmart_item(data: dict) -> dict:
    with db_lock:
        walmart_items_table.upsert(data, Query().name_key == data['name_key'])
    return data

def delete_walmart_item(name_key: str):
    with db_lock:
        walmart_items_table.remove(Query().name_key == name_key)

def get_walmart_items() -> List[dict]:
    with db_lock:
        return sorted([dict(r) for r in walmart_items_table.all()],
                      key=lambda r: (r.get('name') or '').lower())


def get_plates_between(start_date: str, end_date: str) -> List[dict]:
    """Every pinned plate in an inclusive date range (meals arc M6)."""
    with db_lock:
        rows = [dict(p) for p in plates_table.all()]
    return sorted([p for p in rows
                   if start_date <= (p.get('date') or '') <= end_date],
                  key=lambda p: p.get('date') or '')

def prune_plates(before_date: str) -> int:
    with db_lock:
        rows = [dict(p) for p in plates_table.all()]
    doomed = [p for p in rows if (p.get('date') or '') < before_date]
    with db_lock:
        for p in doomed:
            plates_table.remove(Query().date == p['date'])
    return len(doomed)


def dishes_needing_detail() -> List[dict]:
    return [d for d in get_dishes() if d.get('needs_detail')]

# --- Occasions (occasions arc O1) ---
# Context objects, not containers: they own nothing and are passed IN to the
# things that generate work. See docs/occasion_design.md.

def get_occasions(include_done: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(o) for o in occasions_table.all()]
    if not include_done:
        rows = [o for o in rows if (o.get('status') or 'planning') != 'done']
    rows.sort(key=lambda o: (o.get('anchor_date') or '9999-12-31'))
    return rows

def get_occasion(occasion_id: str) -> Optional[dict]:
    with db_lock:
        res = occasions_table.search(Query().id == occasion_id)
        return dict(res[0]) if res else None

def save_occasion(data: dict) -> dict:
    with db_lock:
        occasions_table.upsert(data, Query().id == data['id'])
    return data

def update_occasion(occasion_id: str, patch: dict) -> bool:
    with db_lock:
        return bool(occasions_table.update(patch, Query().id == occasion_id))

def delete_occasion(occasion_id: str):
    """Deleting the CONTEXT must not delete the work. Errands, lists and trips
    outlive it with their `occasion_id` cleared — the whole point of a context
    object is that nothing lives inside it."""
    with db_lock:
        occasions_table.remove(Query().id == occasion_id)
        occasion_guests_table.remove(Query().occasion_id == occasion_id)
        for table in (errands_table, shopping_lists_table, shopping_items_table):
            table.update({'occasion_id': None}, Query().occasion_id == occasion_id)

def get_occasion_guests(occasion_id: str) -> List[dict]:
    with db_lock:
        rows = [dict(g) for g in
                occasion_guests_table.search(Query().occasion_id == occasion_id)]
    rows.sort(key=lambda g: (g.get('created_at') or 0))
    return rows

def save_occasion_guest(data: dict) -> dict:
    with db_lock:
        occasion_guests_table.upsert(data, Query().id == data['id'])
    return data

def update_occasion_guest(guest_id: str, patch: dict) -> bool:
    with db_lock:
        return bool(occasion_guests_table.update(patch, Query().id == guest_id))

def delete_occasion_guest(guest_id: str):
    with db_lock:
        occasion_guests_table.remove(Query().id == guest_id)

# --- Leftovers (meals arc M3) ---
# Date-scoped so they expire on their own; nobody has to remember to clear a
# flag. See models.schemas.Leftover.

def get_leftovers(date_str: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(l) for l in leftovers_table.all()]
    if date_str:
        rows = [l for l in rows if l.get('date') == date_str]
    rows.sort(key=lambda l: l.get('created_at') or 0)
    return rows

def add_leftover(data: dict) -> str:
    with db_lock:
        leftovers_table.insert(data)
        return data['id']

def delete_leftover(leftover_id: str):
    with db_lock:
        leftovers_table.remove(Query().id == leftover_id)

def clear_leftovers(date_str: str) -> int:
    doomed = [l['id'] for l in get_leftovers(date_str)]
    with db_lock:
        for lid in doomed:
            leftovers_table.remove(Query().id == lid)
    return len(doomed)

def prune_leftovers(before_date: str) -> int:
    """Yesterday's leftovers are not tonight's dinner."""
    doomed = [l['id'] for l in get_leftovers() if (l.get('date') or '') < before_date]
    with db_lock:
        for lid in doomed:
            leftovers_table.remove(Query().id == lid)
    return len(doomed)

def add_routine(data: dict) -> str:
    with db_lock:
        routines_table.insert(data)
        return data['id']

def update_routine(routine_id: str, data: dict) -> bool:
    with db_lock:
        return bool(routines_table.update(data, Query().id == routine_id))

def delete_routine(routine_id: str):
    with db_lock:
        routines_table.remove(Query().id == routine_id)
        routine_checks_table.remove(Query().routine_id == routine_id)
        routine_step_checks_table.remove(Query().routine_id == routine_id)

def _routine_scheduled_on(routine: dict, date_obj) -> bool:
    days = routine.get('days_of_week') or []
    return not days or date_obj.weekday() in days

def routines_for_day(member_id: str, date_str: str) -> List[dict]:
    from datetime import date
    d = date.fromisoformat(date_str)
    items = [r for r in get_routines(member_id) if _routine_scheduled_on(r, d)]
    with db_lock:
        checked = {c['routine_id'] for c in routine_checks_table.search(
            (Query().member_id == member_id) & (Query().date_str == date_str))}
        step_rows = routine_step_checks_table.search(Query().date_str == date_str)
    steps_by_routine = {}
    for s in step_rows:
        steps_by_routine.setdefault(s['routine_id'], set()).add(s.get('step_id'))
    for r in items:
        r['checked'] = r['id'] in checked
        if r.get('steps'):
            r['steps_checked'] = sorted(steps_by_routine.get(r['id'], set()))
    items.sort(key=lambda r: (r.get('time_of_day') is None, r.get('time_of_day') or '', r.get('title', '')))
    return items

def set_routine_check(routine_id: str, member_id: str, date_str: str, checked: bool) -> bool:
    import time
    with db_lock:
        routine = routines_table.search(Query().id == routine_id)
        if not routine or routine[0].get('member_id') != member_id:
            return False
        q = (Query().routine_id == routine_id) & (Query().date_str == date_str)
        if checked:
            routine_checks_table.upsert(
                {'routine_id': routine_id, 'member_id': member_id,
                 'date_str': date_str, 'ts': time.time()}, q)
        else:
            routine_checks_table.remove(q)
    # ROUTINES FINALLY HAVE A SINK. They have always earned a streak and
    # nothing else -- the complaint the avatar arc opened with -- so this is
    # the first thing a kept routine actually buys.
    #
    # Unticking does NOT claw the xp back: rule 3 says a thing earned is never
    # taken away, and a box tapped by accident must not cost a child anything.
    # `grant_pet_xp` is idempotent per (routine, day), so the ticking is not a
    # faucet either.
    if checked:
        grant_pet_xp(member_id, pet_xp_rate('pet_xp_per_routine'), 'routine',
                     ref_id=routine_id, date_str=date_str, once=True)
        _grant_routine_day_bonus(member_id, date_str)
    return True


def sync_routine_step_rows(routine_id: str, date_str: str, checked: bool):
    """The big-motion cascade for a PARENT-row tap: ticking the item ticks
    every step, unticking it clears them for a fresh start. Deliberately not
    inside set_routine_check — a single STEP untick also removes the item
    check (the item is only done when wholly done) and must leave its
    sibling steps alone."""
    with db_lock:
        routine = routines_table.search(Query().id == routine_id)
        steps = (routine[0].get('steps') or []) if routine else []
        q = (Query().routine_id == routine_id) & (Query().date_str == date_str)
        routine_step_checks_table.remove(q)
        if checked and steps:
            import time
            for s in steps:
                routine_step_checks_table.insert(
                    {'routine_id': routine_id, 'step_id': s.get('id'),
                     'date_str': date_str, 'ts': time.time()})


def set_routine_step_check(routine_id: str, member_id: str, date_str: str,
                           step_id: str, checked: bool) -> Optional[dict]:
    """Tick one step. Returns {'steps_checked', 'item_checked'} or None when
    the routine/step isn't this member's. The ITEM completes itself when the
    last step ticks — through set_routine_check, so XP and the day bonus fire
    exactly as a direct item tap would (idempotent, steps mint nothing of
    their own) — and un-completes when any step unticks."""
    import time
    with db_lock:
        routine = routines_table.search(Query().id == routine_id)
        if not routine or routine[0].get('member_id') != member_id:
            return None
        steps = routine[0].get('steps') or []
        step_ids = [s.get('id') for s in steps]
        if step_id not in step_ids:
            return None
        q = ((Query().routine_id == routine_id) & (Query().date_str == date_str)
             & (Query().step_id == step_id))
        if checked:
            routine_step_checks_table.upsert(
                {'routine_id': routine_id, 'step_id': step_id,
                 'date_str': date_str, 'ts': time.time()}, q)
        else:
            routine_step_checks_table.remove(q)
        done = {r.get('step_id') for r in routine_step_checks_table.search(
            (Query().routine_id == routine_id) & (Query().date_str == date_str))}
    all_done = set(step_ids) <= done
    set_routine_check(routine_id, member_id, date_str, all_done)
    return {'steps_checked': sorted(done & set(step_ids)),
            'item_checked': all_done}


def _grant_routine_day_bonus(member_id: str, date_str: str) -> int:
    """The whole day's routine, done. Idempotent per (member, day) -- and it
    survives unticking, which is deliberate: having finished the day once is a
    thing that happened."""
    try:
        due = routines_for_day(member_id, date_str)
    except (ValueError, TypeError):
        return 0                       # a malformed date is not a finished day
    if not due or not all(r.get('checked') for r in due):
        return 0
    return grant_pet_xp(member_id, pet_xp_rate('pet_xp_routine_all_bonus'),
                        'routine_all', ref_id='day', date_str=date_str, once=True)

_MAX_STREAK_SCAN_DAYS = 3650  # a decade; a guard against a bad date_str, not a policy


def _stored_best_streak(member_id: str) -> int:
    """The persisted lifetime best. Tiers (and, later, avatar unlocks) hang off
    this, so it lives on the member record rather than being re-derived."""
    m = get_member(member_id)
    try:
        return int((m or {}).get('best_routine_streak') or 0)
    except (TypeError, ValueError):
        return 0


def compute_streak(member_id: str, window_days: int = 90) -> dict:
    """{current, best, today_complete, today_total, today_done}.

    `current` walks back from today over `window_days` (today counts only once
    complete, otherwise the walk starts at yesterday).

    `best` is a LIFETIME high-water mark, not a windowed one: it scans from the
    first recorded check and is persisted on the member, so it survives the
    window rolling past an old run, routines being edited or deleted, and
    checks being pruned. Routine status tiers read this value -- a badge that
    silently demotes itself is worse than no badge at all.
    """
    from datetime import date, timedelta
    floor = _stored_best_streak(member_id)
    routines = get_routines(member_id)
    if not routines:
        # No routines today doesn't undo the streak they already ran.
        return {'current': 0, 'best': floor, 'today_complete': False,
                'today_total': 0, 'today_done': 0}
    today = date.today()
    with db_lock:
        all_checks = routine_checks_table.search(Query().member_id == member_id)
    checks_by_day = {}
    for c in all_checks:
        checks_by_day.setdefault(c['date_str'], set()).add(c['routine_id'])

    def day_state(d):
        scheduled = {r['id'] for r in routines if _routine_scheduled_on(r, d)}
        if not scheduled:
            return 'neutral'
        return 'complete' if scheduled <= checks_by_day.get(d.isoformat(), set()) else 'incomplete'

    # current streak: walk back from today; an incomplete today doesn't
    # break it (the day isn't over), it just doesn't count yet.
    current = 0
    d = today
    if day_state(d) == 'incomplete':
        d = d - timedelta(days=1)
    steps = 0
    while steps < window_days:
        state = day_state(d)
        if state == 'complete':
            current += 1
        elif state == 'incomplete':
            break
        d = d - timedelta(days=1)
        steps += 1

    # best: every day from the first recorded check forward, so an old run is
    # never aged out. Earlier days are not walked -- there was nothing to
    # complete then, and a day we skip could only ever have broken a run.
    earliest = today
    for ds in checks_by_day:
        try:
            earliest = min(earliest, date.fromisoformat(ds))
        except (ValueError, TypeError):
            continue  # one malformed row must not sink the whole tally
    span = max(0, min((today - earliest).days, _MAX_STREAK_SCAN_DAYS))
    best = run = 0
    for i in range(span, -1, -1):
        state = day_state(today - timedelta(days=i))
        if state == 'complete':
            run += 1
            best = max(best, run)
        elif state == 'incomplete':
            run = 0
    best = max(best, current)
    if best > floor:
        update_member(member_id, {'best_routine_streak': best})
    else:
        best = floor  # the record outlives the evidence

    today_sched = {r['id'] for r in routines if _routine_scheduled_on(r, today)}
    today_done = len(today_sched & checks_by_day.get(today.isoformat(), set()))
    return {'current': current, 'best': best,
            'today_complete': bool(today_sched) and today_done == len(today_sched),
            'today_total': len(today_sched), 'today_done': today_done}

# --- Avatars (unlock ledger + config) ---
# The ledger is append-only and the counters it reads are all monotonic
# high-water marks. See services/avatar_catalog.py for the two rules.

def count_routine_completions(member_id: str) -> int:
    """Total routine completions ever, as a persisted high-water mark.

    set_routine_check upserts one row per (routine, day), so this cannot be
    farmed by re-ticking. Unticking removes the row, which is why the total is
    stored rather than counted fresh -- undoing today must not take back a
    piece of clothing earned last month."""
    m = get_member(member_id)
    try:
        floor = int((m or {}).get('routine_completions_total') or 0)
    except (TypeError, ValueError):
        floor = 0
    with db_lock:
        live = len(routine_checks_table.search(Query().member_id == member_id))
    if live > floor:
        update_member(member_id, {'routine_completions_total': live})
        return live
    return floor


def avatar_counter(member_id: str, track: str) -> int:
    """The value an unlock track is measured against."""
    from services import avatar_catalog as cat
    if track == cat.TRACK_STREAK:
        return compute_streak(member_id).get('best', 0)
    if track == cat.TRACK_POINTS:
        return get_points_earned(member_id)
    return count_routine_completions(member_id)


def get_avatar_unlocks(member_id: str) -> List[str]:
    """Every item_id this member owns. Order is not meaningful."""
    with db_lock:
        rows = avatar_unlocks_table.search(Query().member_id == member_id)
    return sorted({r.get('item_id') for r in rows if r.get('item_id')})


def grant_avatar_unlock(member_id: str, item_id: str, source: str = 'grant') -> bool:
    """Append one row. Idempotent -- returns True only the first time, so
    callers can use the return value to decide whether to celebrate."""
    import time
    with db_lock:
        q = (Query().member_id == member_id) & (Query().item_id == item_id)
        if avatar_unlocks_table.search(q):
            return False
        avatar_unlocks_table.insert({'member_id': member_id, 'item_id': item_id,
                                     'source': source, 'unlocked_at': time.time()})
        return True


def sync_avatar_unlocks(member_id: str) -> List[str]:
    """Grant everything this member has earned but does not yet own, and
    return only what was newly granted so the caller can celebrate it.

    Doubles as the backfill: free pieces and already-passed thresholds are
    granted on the first call, so nobody who was here before the feature
    starts behind. Safe to call on every routine tick."""
    from services import avatar_catalog as cat
    owned = set(get_avatar_unlocks(member_id))
    fresh = []
    for item in cat.free_items():
        iid = cat.item_id(item['slot'], item['key'])
        if iid not in owned and grant_avatar_unlock(member_id, iid, 'default'):
            fresh.append(iid)
    # AN ADULT HAS NO WAY TO EARN ANY OF THIS. Chore points are awarded to
    # children by design, so every unlock track reads zero for a parent
    # forever -- they were locked out of the wardrobe permanently, which is
    # not a design decision anybody made, it is a gap.
    #
    # Granted as `role`, and deliberately NOT returned as `fresh`: the
    # celebration is for EARNING something, and firing confetti at a parent
    # for a role grant is exactly what would cheapen a child's unlock.
    m = get_member(member_id) or {}
    if m.get('role') == 'parent':
        for item in cat.unlockable_items():
            iid = cat.item_id(item['slot'], item['key'])
            if iid not in owned:
                grant_avatar_unlock(member_id, iid, 'role')
        return fresh

    cache = {}
    for item in cat.unlockable_items():
        iid = cat.item_id(item['slot'], item['key'])
        if iid in owned:
            continue
        track = item['track']
        if track not in cache:
            cache[track] = avatar_counter(member_id, track)
        if cache[track] >= item['threshold'] and grant_avatar_unlock(member_id, iid, track):
            fresh.append(iid)
    return fresh


def get_avatar_config(member_id: str) -> dict:
    """The member's saved look, with missing required slots filled
    DETERMINISTICALLY from the member id.

    Day one, before anyone opens the editor, every member gets a distinct,
    decent-looking character rather than one shared bald default -- building a
    look is then an upgrade, not a chore. Hash-seeded so the same member always
    gets the same face. Skin tone is deliberately NOT randomised: it is
    identity, not decoration, and a wrong guess is worse than the renderer's
    neutral default. It stays whatever the member (or their parent) picks."""
    import hashlib
    from services import avatar_catalog as cat
    m = get_member(member_id) or {}
    cfg = dict(m.get('avatar_config') or {})
    from services import avatar_render
    seed = int.from_bytes(hashlib.md5((member_id or '').encode()).digest()[:8], 'big')
    # Faces draw only from the head of each list (Default, Happy, ...): the
    # catalog orders expressions pleasant-first, and nobody's day-one default
    # should be the ScreamOpen or Vomit mouth they never chose.
    _FACE_POOL = {'eyes': 3, 'eyebrow': 2, 'mouth': 3, 'nose': 1}
    for slot in cat.get_slots():
        key = slot['key']
        if slot.get('required') and not cfg.get(key):
            choices = [i for i in cat.items_for_slot(key) if i['tier'] == 'free']
            choices = choices[:_FACE_POOL.get(key) or len(choices)]
            if choices:
                cfg[key] = choices[seed % len(choices)]['key']
                seed //= max(len(choices), 2)
    _PALS = {'hair_color': avatar_render.HAIR_COLORS,
             'clothe_color': avatar_render.CLOTHE_COLORS,
             'bottoms_color': avatar_render.CLOTHE_COLORS}
    for pal, table in _PALS.items():
        if not cfg.get(pal):
            names = sorted(table)
            cfg[pal] = names[seed % len(names)]
            seed //= max(len(names), 2)
    return cfg


def set_avatar_config(member_id: str, config: dict) -> dict:
    """Save a look, dropping anything the member has not unlocked or that does
    not exist. Returns {'config': saved, 'rejected': [...]}.

    Validation is here rather than in the endpoint on purpose: the ledger is
    the authority on what someone may wear, and an editor is only ever a
    convenient way to ask."""
    from services import avatar_catalog as cat
    from services import avatar_render
    owned = set(get_avatar_unlocks(member_id))
    _pals = tuple(avatar_render._PALETTES) + ('build', 'height')
    clean, rejected = {}, []
    for slot_key, item_key in (config or {}).items():
        if slot_key in _pals:
            continue                       # palettes are handled below, not slots
        if not cat.get_slot(slot_key):
            rejected.append(slot_key)
            continue
        if item_key in (None, '', 'Blank'):
            clean[slot_key] = item_key or None
            continue
        if not cat.get_item(slot_key, item_key):
            rejected.append(cat.item_id(slot_key, item_key))
            continue
        if cat.item_id(slot_key, item_key) not in owned:
            rejected.append(cat.item_id(slot_key, item_key))
            continue
        clean[slot_key] = item_key
    # Every palette slot the renderer knows, not a hand-kept list -- the
    # hand-kept version silently dropped bottoms_color the day it shipped.
    for pal in _pals:
        if pal in (config or {}):
            clean[pal] = config[pal]
    update_member(member_id, {'avatar_config': clean})
    return {'config': clean, 'rejected': rejected}


# --- Pets ---
# Sidekicks with stats. Everything here is FREE: species, look, name and
# element cost nothing and always will, because rule 1 gates power and never
# identity. What gets earned (xp, training, extra slots) lands in P2/P5 and
# touches none of the fields below.

# One pet to begin with, and the second slot is itself a reward rather than a
# thing you are simply given. P5 replaces the constant with an earned count;
# every caller already asks the function, so that change stays in one place.
PET_SLOTS_FREE = 1
PET_NAME_MAX = 24


def pet_slots(member_id: str) -> int:
    """How many pets this member may keep active: the free one, plus any
    bought with xp."""
    return PET_SLOTS_FREE + pet_slots_bought(member_id)


# --- pet xp (P2) ----------------------------------------------------------
# The membrane, in one place: this ledger is written by chores, routines and
# (later) battles, and read by levels and training. It never touches
# `points_ledger` and `points_ledger` never touches it.

# Defaults; a household can retune them in Settings.
PET_XP_RATES = {
    'pet_xp_per_chore_point': 1.0,   # a 10-point chore mints 10 xp
    'pet_xp_per_routine': 3,
    'pet_xp_routine_all_bonus': 10,
}

PACKING_XP = 2                       # one item packed; a routine item is 3


def pet_xp_rate(key: str):
    s = get_settings() or {}
    val = s.get(key, PET_XP_RATES[key])
    try:
        return type(PET_XP_RATES[key])(val)
    except (TypeError, ValueError):
        return PET_XP_RATES[key]


def grant_pet_xp(member_id: str, delta: int, reason: str, ref_id: str = None,
                 date_str: str = None, note: str = None, once: bool = False) -> int:
    """Append one xp row. Returns what was actually minted (0 if nothing).

    `once` makes the row IDEMPOTENT on (member, reason, ref_id, date_str), and
    it is the whole anti-farm story for routines: `set_routine_check` upserts
    one check row per (routine, day), but a child can tick and untick a box
    all afternoon. Without the guard that is an xp faucet.

    Chores deliberately do NOT pass it. A recurring chore is a real second
    piece of work when it comes round again, and points mint every time it is
    verified -- xp minting on exactly the same events as points is the point.
    Making it once-per-chore would have silently starved every daily chore
    after its first day."""
    import time
    import uuid as _uuid
    delta = int(delta or 0)
    if not delta or not member_id:
        return 0
    with db_lock:
        if once and ref_id is not None:
            q = ((Query().member_id == member_id) & (Query().reason == reason)
                 & (Query().ref_id == ref_id))
            if date_str is not None:
                q = q & (Query().date_str == date_str)
            if pet_xp_ledger_table.search(q):
                return 0
        row = {'id': _uuid.uuid4().hex, 'member_id': member_id,
               'delta': delta, 'reason': reason, 'ref_id': ref_id,
               'date_str': date_str, 'note': note, 'ts': time.time()}
        pet_xp_ledger_table.insert(row)
    return delta


PET_XP_DAILY_GRANT = 15


def pet_xp_daily_grant() -> int:
    s = get_settings() or {}
    try:
        return max(0, int(s.get('pet_xp_daily_grant', PET_XP_DAILY_GRANT)))
    except (TypeError, ValueError):
        return PET_XP_DAILY_GRANT


def sync_pet_xp(member_id: str) -> dict:
    """Bring a member up to date: the work they did BEFORE pets existed, and
    today's showing-up grant. Safe to call on every read.

    THE BACKFILL IS THE POINT. The avatar arc already promised that "nobody
    who was here before the feature starts behind", and pets shipped without
    honouring it -- a child with two thousand lifetime chore points started at
    level 1 beside a sibling with a hundred. Both rows are idempotent, so this
    converts a history exactly once and never again.

    THE DAILY GRANT GOES TO EVERYONE, at the same rate. Giving it to adults
    only would have a child sweeping the floor for xp while a parent collects
    it for existing, which is a fair thing for a seven-year-old to resent.
    Everyone gets the same small amount for the app being used, and anybody
    who does chores or routines still races past it -- which is the incentive
    we actually want."""
    from datetime import date
    out = {'backfilled': 0, 'daily': 0}
    # 1. history, once, ever
    points = get_points_earned(member_id)
    if points:
        out['backfilled'] += grant_pet_xp(
            member_id, round(points * pet_xp_rate('pet_xp_per_chore_point')),
            'backfill', ref_id='chore_points', once=True,
            note='chores done before critters existed')
    routines = count_routine_completions(member_id)
    if routines:
        out['backfilled'] += grant_pet_xp(
            member_id, routines * pet_xp_rate('pet_xp_per_routine'),
            'backfill', ref_id='routine_history', once=True,
            note='routines kept before critters existed')
    # 2. today, once a day
    grant = pet_xp_daily_grant()
    if grant:
        out['daily'] = grant_pet_xp(member_id, grant, 'daily', ref_id='daily',
                                    date_str=date.today().isoformat(), once=True,
                                    note='for showing up')
    return out


def adjust_pet_xp(member_id: str, delta: int, by_member_id: str = None,
                  reason_note: str = None) -> dict:
    """A parent handing out (or taking back) xp by hand, exactly as they can
    with chore points. Returns {'balance','level'} or {'error'}.

    Taking xp back can lower a BALANCE and never a level: level comes from
    lifetime earned, so nothing a parent does here can undo something a child
    already achieved."""
    if not get_member(member_id):
        return {'error': 'No such member'}
    delta = int(delta or 0)
    if not delta:
        return {'error': 'Nothing to change'}
    grant_pet_xp(member_id, delta, 'adjust',
                 note=('%s (by %s)' % (reason_note or 'adjusted', by_member_id))
                 if by_member_id else (reason_note or 'adjusted'))
    return {'balance': get_pet_xp_balance(member_id),
            'level': pet_level(member_id)}


def get_pet_xp_balance(member_id: str) -> int:
    """Everything minted minus everything spent -- what is left to spend."""
    with db_lock:
        return sum(int(e.get('delta', 0))
                   for e in pet_xp_ledger_table.search(Query().member_id == member_id))


def get_pet_xp_earned(member_id: str) -> int:
    """Lifetime xp EARNED. Drives level, so spending never costs a level --
    the same shape as points vs status tiers, and for the same reason: a thing
    you have already achieved is not a thing a purchase can take away."""
    with db_lock:
        return sum(d for e in pet_xp_ledger_table.search(Query().member_id == member_id)
                   if (d := int(e.get('delta', 0))) > 0)


def pet_spend_hint(member_id: str) -> dict:
    """{balance, hint, can_spend} -- what this member could buy right now.

    A currency nobody can see is not a reward, and a balance with nothing to
    do is just a number. So the SAME function answers both questions, and
    every surface reads it rather than each one working out affordability
    slightly differently: the nudge and the display are the same thing.

    Silent on purpose when there is nothing to buy. A badge that is always
    lit stops meaning anything."""
    balance = get_pet_xp_balance(member_id)
    pets = get_pets(member_id)
    hint = None
    if pets and balance >= PET_MOVE_COST:
        from services import pet_catalog
        known = set(pet_known_moves(pets[0]))
        if any(m['key'] not in known for m in pet_catalog.moves()):
            hint = 'teach a new move'
    if balance >= PET_SLOT_COST and len(pets) >= pet_slots(member_id):
        hint = 'get another critter'
    if not pets:
        hint = 'hatch a critter'
    return {'balance': balance, 'hint': hint, 'can_spend': bool(hint)}


def get_pet_xp_ledger(member_id: str, limit: int = 25) -> List[dict]:
    with db_lock:
        rows = [dict(e) for e in
                pet_xp_ledger_table.search(Query().member_id == member_id)]
    rows.sort(key=lambda r: r.get('ts') or 0, reverse=True)
    return rows[:limit]


def pet_level(member_id: str) -> int:
    from services import pet_catalog
    return pet_catalog.level_for_xp(get_pet_xp_earned(member_id))


def pet_level_progress(member_id: str) -> dict:
    from services import pet_catalog
    return pet_catalog.level_progress(get_pet_xp_earned(member_id))


def _with_level(pet: Optional[dict]) -> Optional[dict]:
    """A pet's level is DERIVED from its owner's lifetime xp, never stored.

    Stamped on every read so the stored field can never drift, and so a write
    that tries to set it is not merely ignored but overwritten."""
    if not pet:
        return pet
    pet = dict(pet)
    pet['level'] = pet_level(pet.get('member_id') or '')
    return pet


def _pet_look(species: dict, look: dict) -> tuple:
    """Validate a look against the BAKED ART, never a hand-kept list.

    Anything unknown is dropped rather than rejected wholesale: a pet with one
    unrecognised part is still a pet, and a child should never lose a creature
    because a slot name drifted."""
    import re
    from services import pet_render as pr
    species = dict(species or {})
    look = dict(look or {})
    clean_species, clean_look, rejected = {}, {}, []

    for slot, target in (('body', clean_species), ('top', clean_species),
                         ('eyes', clean_look), ('mouth', clean_look),
                         ('pattern', clean_look), ('cheeks', clean_look)):
        val = species.get(slot) if target is clean_species else look.get(slot)
        if val in (None, '', 'none'):
            # pattern and cheeks are genuinely optional; a body and a face are
            # not, and fall back to the default rather than rendering a hole.
            if slot in ('pattern', 'cheeks'):
                target[slot] = None
                continue
            val = pr.DEFAULTS.get(slot)
        if val not in pr.parts(slot):
            rejected.append('%s:%s' % (slot, val))
            val = pr.DEFAULTS.get(slot)
        target[slot] = val

    for slot in ('base_color', 'accent_color'):
        val = look.get(slot)
        if val in pr.BASE_COLORS or (isinstance(val, str)
                                     and re.fullmatch(r'#[0-9a-fA-F]{6}', val or '')):
            clean_look[slot] = val
        else:
            if val:
                rejected.append('%s:%s' % (slot, val))
            clean_look[slot] = pr.DEFAULTS[slot]
    return clean_species, clean_look, rejected


def _pet_name(name: str, fallback: str = 'Critter') -> str:
    import re
    name = re.sub(r'\s+', ' ', str(name or '')).strip()[:PET_NAME_MAX]
    return name or fallback


def get_pets(member_id: Optional[str] = None,
             include_retired: bool = False) -> List[dict]:
    with db_lock:
        rows = [dict(p) for p in (
            pets_table.search(Query().member_id == member_id) if member_id
            else pets_table.all())]
    if not include_retired:
        rows = [p for p in rows if p.get('active', True)]
    return [_with_level(p) for p in
            sorted(rows, key=lambda p: p.get('created_at') or 0)]


def get_pet(pet_id: str) -> Optional[dict]:
    with db_lock:
        res = pets_table.search(Query().id == pet_id)
    return _with_level(dict(res[0])) if res else None


def get_active_pet(member_id: str) -> Optional[dict]:
    """The one that shows up on a board and would walk into a battle."""
    pets = get_pets(member_id)
    return pets[0] if pets else None


def create_pet(member_id: str, name: str = '', species: Optional[dict] = None,
               look: Optional[dict] = None, type_: str = None) -> dict:
    """Hatch one. Returns {'pet', 'rejected'} or {'error'}.

    Free, for everyone, once -- see PET_SLOTS_FREE. Adults included: a parent
    with a critter is a real opponent, and PvP is level-matched so nobody can
    lean on a kid with it."""
    import time
    import uuid as _uuid
    from services import pet_catalog
    if not get_member(member_id):
        return {'error': 'No such member'}
    if len(get_pets(member_id)) >= pet_slots(member_id):
        return {'error': 'No free pet slot'}
    clean_species, clean_look, rejected = _pet_look(species, look)
    pet = {
        'id': _uuid.uuid4().hex,
        'member_id': member_id,
        'name': _pet_name(name),
        'species': clean_species,
        'look': clean_look,
        'type': pet_catalog.coerce(type_),
        'level': 1,
        'training': {},
        'moves': [],
        'active': True,
        'created_at': time.time(),
    }
    with db_lock:
        pets_table.insert(pet)
    return {'pet': _with_level(pet), 'rejected': rejected}


def update_pet(pet_id: str, fields: Optional[dict] = None) -> dict:
    """Rename, restyle, re-element. Returns {'pet', 'rejected'} or {'error'}.

    Only ever touches the free fields. Level, training and moves are the
    earned half and are not writable from here -- an editor must not be able
    to hand out what a ledger is supposed to."""
    from services import pet_catalog
    pet = get_pet(pet_id)
    if not pet:
        return {'error': 'No such pet'}
    fields = dict(fields or {})
    updates, rejected = {}, []
    if 'name' in fields:
        updates['name'] = _pet_name(fields['name'], pet.get('name') or 'Critter')
    if 'species' in fields or 'look' in fields:
        species, look, rejected = _pet_look(
            fields.get('species', pet.get('species')),
            fields.get('look', pet.get('look')))
        updates['species'], updates['look'] = species, look
    if 'type' in fields:
        if pet_catalog.valid(fields['type']):
            updates['type'] = fields['type']
        else:
            rejected.append('type:%s' % fields['type'])
    if updates:
        with db_lock:
            pets_table.update(updates, Query().id == pet_id)
        pet.update(updates)
    return {'pet': _with_level(pet), 'rejected': rejected}


def retire_pet(pet_id: str, retired: bool = True) -> Optional[dict]:
    """Free the slot WITHOUT losing the creature (rule 3). Reversible, as long
    as bringing it back would not overfill the member's slots."""
    pet = get_pet(pet_id)
    if not pet:
        return None
    if not retired and len(get_pets(pet['member_id'])) >= pet_slots(pet['member_id']):
        return None
    with db_lock:
        pets_table.update({'active': not retired}, Query().id == pet_id)
    pet['active'] = not retired
    return pet


# --- training, moves and slots (P5) ---------------------------------------
# WHAT XP CAN AND CANNOT BUY.
#
# Not species, not colours, not any part of how a critter looks -- rule 1 says
# identity is free and P1 shipped a test that every part and colour is
# choosable. The design brief listed "species unlocks" and "cosmetic parts"
# as sinks; it was wrong, and it has been corrected rather than obeyed.
#
# Not stat training either, and that one is a real decision. Training points
# come free with each level and can be moved around as often as a child likes,
# because training is the BUILD -- the thing level-matching deliberately
# preserves so that thinking about your critter still pays in a family fight.
# Charging for it would mean the sibling with more xp has the better build,
# which is the whole thing this arc exists to avoid.
#
# So what is left is BREADTH, and it is genuinely the interesting half:
#   * moves from OTHER elements -- coverage, the one real strategic purchase
#   * a second pet
PET_MOVE_COST = 60
PET_SLOT_COST = 500


def pet_native_moves(pet: dict) -> List[str]:
    """The four a critter has always known: its own element's kit, free."""
    from services import pet_catalog
    return pet_catalog.default_moves((pet or {}).get('type'))


def pet_known_moves(pet: dict) -> List[str]:
    """Everything it may equip -- its own element's four, plus anything
    bought."""
    known = list(pet_native_moves(pet))
    for k in ((pet or {}).get('known_moves') or []):
        if k not in known:
            known.append(k)
    return known


def learn_pet_move(pet_id: str, move_key: str) -> dict:
    """Buy a move from another element. Returns {'pet','spent'} or {'error'}.

    Coverage is the point: an ember critter that learns a tide move stops
    being helpless against the thing that beats it. A real decision with a
    real cost, which is what a sink is supposed to be."""
    from services import pet_catalog
    pet = get_pet(pet_id)
    if not pet:
        return {'error': 'No such pet'}
    mv = pet_catalog.move(move_key)
    if not mv:
        return {'error': 'No such move'}
    if move_key in pet_known_moves(pet):
        return {'error': 'Already knows it'}
    member_id = pet.get('member_id')
    if get_pet_xp_balance(member_id) < PET_MOVE_COST:
        return {'error': 'Not enough XP'}
    grant_pet_xp(member_id, -PET_MOVE_COST, 'spend', ref_id=pet_id,
                 note='learned %s' % mv['name'])
    known = list(pet.get('known_moves') or [])
    known.append(move_key)
    with db_lock:
        pets_table.update({'known_moves': known}, Query().id == pet_id)
    return {'pet': get_pet(pet_id), 'spent': PET_MOVE_COST}


def set_pet_moves(pet_id: str, moves: List[str]) -> dict:
    """Equip up to four, only ever from what the creature already knows -- the
    ledger decides what may be equipped, never the editor."""
    pet = get_pet(pet_id)
    if not pet:
        return {'error': 'No such pet'}
    allowed = pet_known_moves(pet)
    clean, rejected = [], []
    for k in (moves or []):
        if k in allowed and k not in clean:
            clean.append(k)
        else:
            rejected.append(k)
    clean = clean[:4]
    if not clean:
        # Never leave a critter with nothing to do in a fight.
        clean = pet_native_moves(pet)[:4]
    with db_lock:
        pets_table.update({'moves': clean}, Query().id == pet_id)
    return {'pet': get_pet(pet_id), 'rejected': rejected}


def pet_training_budget(member_id: str) -> int:
    from services import pet_battle
    return pet_battle.training_budget(pet_level(member_id))


def set_pet_training(pet_id: str, training: dict) -> dict:
    """Spend the level's training points. FREE and freely re-spent -- a child
    must be able to try a build, lose, and try another without paying for the
    experiment."""
    from services import pet_battle
    from services import pet_catalog
    pet = get_pet(pet_id)
    if not pet:
        return {'error': 'No such pet'}
    budget = pet_training_budget(pet.get('member_id'))
    want = {}
    for stat in pet_catalog.STATS:
        try:
            v = max(0, int((training or {}).get(stat, 0) or 0))
        except (TypeError, ValueError):
            v = 0
        want[stat] = min(v, pet_battle.TRAINING_STAT_CAP)

    # OVER BUDGET SCALES THE SHAPE DOWN; it does not fill stats in whatever
    # order the tuple happens to be in. Walking STATS and stopping at the
    # budget meant asking for 999 attack got you 24 hp and no attack at all --
    # the child's actual intent thrown away because 'hp' sorts first. Scaling
    # is also what level-matching does to a training budget, so a pet squeezed
    # by either route keeps the same shape.
    total = sum(want.values())
    scaled = total > budget
    if scaled and total:
        clean = {s: int(v * budget / total) for s, v in want.items()}
        # hand the rounding remainder to the biggest asks first, so a build
        # does not quietly lose points to floor()
        left = budget - sum(clean.values())
        for stat in sorted(want, key=lambda k: -want[k]):
            if left <= 0:
                break
            if clean[stat] < min(want[stat], pet_battle.TRAINING_STAT_CAP):
                clean[stat] += 1
                left -= 1
    else:
        clean = dict(want)

    with db_lock:
        pets_table.update({'training': clean}, Query().id == pet_id)
    return {'pet': get_pet(pet_id), 'budget': budget,
            'spent': sum(clean.values()), 'scaled': scaled}


def pet_slots_bought(member_id: str) -> int:
    with db_lock:
        return len(pet_xp_ledger_table.search(
            (Query().member_id == member_id) & (Query().reason == 'pet_slot')))


def buy_pet_slot(member_id: str) -> dict:
    """The long carrot. A second critter is the reward rather than a thing you
    are handed -- and it arrives at your own level instead of as a weakling,
    because xp belongs to the member."""
    if not get_member(member_id):
        return {'error': 'No such member'}
    if get_pet_xp_balance(member_id) < PET_SLOT_COST:
        return {'error': 'Not enough XP'}
    grant_pet_xp(member_id, -PET_SLOT_COST, 'pet_slot', note='a second critter')
    return {'slots': pet_slots(member_id), 'spent': PET_SLOT_COST}


# --- battles (P4) ---------------------------------------------------------

PET_PVE_DAILY_CAP = 5
PET_PVE_LOSS_XP = 5


def pet_pve_cap() -> int:
    s = get_settings() or {}
    try:
        return max(0, int(s.get('pet_pve_daily_cap', PET_PVE_DAILY_CAP)))
    except (TypeError, ValueError):
        return PET_PVE_DAILY_CAP


def pet_battles_today(member_id: str, date_str: str = None) -> int:
    from datetime import date
    date_str = date_str or date.today().isoformat()
    with db_lock:
        return len(pet_battles_table.search(
            (Query().member_id == member_id) & (Query().date_str == date_str)))


def pet_combatant_for(pet_id: str):
    """A stored pet as a fighter. None if there is no such pet."""
    from services import pet_battle
    pet = get_pet(pet_id)
    if not pet:
        return None
    m = get_member(pet.get('member_id')) or {}
    return pet_battle.combatant(
        pet.get('name') or 'Critter', pet.get('type'), pet.get('species'),
        level=pet.get('level') or 1, training=pet.get('training'),
        moves=(pet.get('moves') or pet_native_moves(pet)),
        pet_id=pet_id, owner=m.get('name'))


def run_pet_battle(pet_id: str, opponent: str, seed: int = None) -> dict:
    """Fight, award, record. Returns {'battle', 'replay'} or {'error'}.

    THE CAP DOES NOT REFUSE THE FUN. Past the daily limit the battle still
    runs and the replay still plays -- only the xp stops, and the record says
    so. Refusing to let a child play with the thing they built, because they
    already played five times, is a punishment; paying nothing for the sixth
    is just an economy.
    """
    import time
    import uuid as _uuid
    from datetime import date
    from services import pet_battle, pet_catalog
    mine = pet_combatant_for(pet_id)
    if not mine:
        return {'error': 'No such pet'}
    pet = get_pet(pet_id)
    member_id = pet.get('member_id')

    npc_key = opponent[4:] if str(opponent).startswith('npc:') else None
    if npc_key:
        theirs = pet_battle.npc_combatant(npc_key)
        npc = pet_catalog.npc(npc_key)
        if not theirs:
            return {'error': 'No such opponent'}
        # PvE is NOT level-matched: the machine is where the grind is allowed
        # to pay off, because losing to it hurts nobody's feelings.
        level_match = False
        win_xp = int((npc or {}).get('xp') or 15)
    else:
        theirs = pet_combatant_for(opponent)
        if not theirs:
            return {'error': 'No such opponent'}
        level_match = True
        win_xp = 30

    if seed is None:
        seed = int.from_bytes(os.urandom(4), 'big')
    replay = pet_battle.resolve(mine, theirs, seed=seed, level_match=level_match)
    won = replay['winner'] == 'a'

    today = date.today().isoformat()
    capped = pet_battles_today(member_id, today) >= pet_pve_cap()
    awarded = 0
    if not capped:
        awarded = win_xp if won else PET_PVE_LOSS_XP
        awarded = grant_pet_xp(member_id, awarded, 'battle', note=(
            'beat %s' % theirs['name'] if won else 'fought %s' % theirs['name']))

    row = {
        'id': _uuid.uuid4().hex,
        'member_id': member_id,
        'date_str': today,
        'pet_id': pet_id,
        'opponent': opponent,
        'opponent_name': theirs['name'],
        'seed': int(seed),
        'level_match': level_match,
        # The INPUTS, not the frames. resolve() is pure over exactly these.
        'a_in': mine, 'b_in': theirs,
        'winner': replay['winner'],
        'won': won,
        'pair': None,               # PvE has no pair; the counter skips it
        'xp': awarded,
        'capped': bool(capped),
        'created_at': time.time(),
    }
    with db_lock:
        pet_battles_table.insert(row)
    return {'battle': row, 'replay': replay, 'awarded': awarded,
            'capped': bool(capped),
            'remaining': max(0, pet_pve_cap() - pet_battles_today(member_id, today))}


# --- challenges (P6) ------------------------------------------------------
# PvP, and the two rules that make it safe to put in a house with siblings in
# it. Level-matching lives in the resolver; these are the other two.
#
# 1. CONSENT. A challenge is an invitation, not an event. Nothing resolves
#    until the other child accepts, and declining costs nothing and is never
#    announced as a forfeit.
# 2. NO STANDING. Both sides are paid, the loser meaningfully, and there is no
#    ladder, no ranking and no win-loss record anywhere -- a battle is a toy,
#    not a position in the family.

PET_PVP_WIN_XP = 30
PET_PVP_LOSS_XP = 18
PET_PVP_PAIR_CAP = 3
CHALLENGE_TTL_HOURS = 24


def pet_pvp_pair_cap() -> int:
    s = get_settings() or {}
    try:
        return max(0, int(s.get('pet_pvp_pair_cap', PET_PVP_PAIR_CAP)))
    except (TypeError, ValueError):
        return PET_PVP_PAIR_CAP


def pet_pvp_enabled() -> bool:
    """A household may turn sibling battles off entirely and keep the rest."""
    s = get_settings() or {}
    return bool(s.get('pet_pvp_enabled', True))


def _pair_key(a: str, b: str) -> str:
    return '|'.join(sorted([a or '', b or '']))


def pet_pvp_battles_today(a: str, b: str, date_str: str = None) -> int:
    from datetime import date
    date_str = date_str or date.today().isoformat()
    key = _pair_key(a, b)
    with db_lock:
        return len(pet_battles_table.search(
            (Query().date_str == date_str) & (Query().pair == key)))


def create_pet_challenge(from_member: str, to_member: str) -> dict:
    """Invite a sibling. Returns {'challenge'} or {'error'}."""
    import time
    import uuid as _uuid
    if not pet_pvp_enabled():
        return {'error': 'Battles between people are switched off'}
    if from_member == to_member:
        return {'error': 'Pick somebody else'}
    mine, theirs = get_active_pet(from_member), get_active_pet(to_member)
    if not mine:
        return {'error': 'Hatch a critter first'}
    if not theirs:
        return {'error': 'They have no critter yet'}
    with db_lock:
        open_already = pet_challenges_table.search(
            (Query().from_member == from_member) & (Query().to_member == to_member)
            & (Query().state == 'pending'))
    if open_already:
        return {'error': 'You already asked them'}
    ch = {'id': _uuid.uuid4().hex, 'from_member': from_member,
          'to_member': to_member, 'from_pet': mine['id'], 'to_pet': theirs['id'],
          'state': 'pending', 'battle_id': None, 'created_at': time.time()}
    with db_lock:
        pet_challenges_table.insert(ch)
    return {'challenge': ch}


def get_pet_challenges(member_id: str = None, state: str = 'pending') -> List[dict]:
    """Everything waiting on somebody. Expired invitations are swept on read
    rather than by a job -- an invitation from yesterday is not a thing a kid
    should still be able to trip over."""
    import time
    cutoff = time.time() - CHALLENGE_TTL_HOURS * 3600
    with db_lock:
        rows = [dict(c) for c in pet_challenges_table.all()]
        stale = [c['id'] for c in rows
                 if c.get('state') == 'pending' and (c.get('created_at') or 0) < cutoff]
        if stale:
            pet_challenges_table.update({'state': 'expired'},
                                        Query().id.one_of(stale))
            for c in rows:
                if c['id'] in stale:
                    c['state'] = 'expired'
    out = [c for c in rows if not state or c.get('state') == state]
    if member_id:
        out = [c for c in out if member_id in (c.get('from_member'),
                                               c.get('to_member'))]
    out.sort(key=lambda c: c.get('created_at') or 0, reverse=True)
    return out


def respond_pet_challenge(challenge_id: str, accept: bool,
                          seed: int = None) -> dict:
    """Yes or no. Declining is free, silent and final -- it is not a forfeit,
    it is not recorded as a loss, and nothing announces it."""
    import time
    from datetime import date
    from services import pet_battle
    with db_lock:
        res = pet_challenges_table.search(Query().id == challenge_id)
    if not res:
        return {'error': 'No such challenge'}
    ch = dict(res[0])
    if ch.get('state') != 'pending':
        return {'error': 'Already answered'}
    if not accept:
        with db_lock:
            pet_challenges_table.update({'state': 'declined',
                                         'decided_at': time.time()},
                                        Query().id == challenge_id)
        return {'challenge': dict(ch, state='declined')}

    mine = pet_combatant_for(ch['from_pet'])
    theirs = pet_combatant_for(ch['to_pet'])
    if not mine or not theirs:
        with db_lock:
            pet_challenges_table.update({'state': 'expired'},
                                        Query().id == challenge_id)
        return {'error': 'One of the critters is gone'}

    if seed is None:
        seed = int.from_bytes(os.urandom(4), 'big')
    # LEVEL-MATCHED, always, between people. This is the line the whole arc
    # rests on: the fight is decided by build, typing and luck, never by who
    # did more chores.
    replay = pet_battle.resolve(mine, theirs, seed=seed, level_match=True)

    today = date.today().isoformat()
    pair = _pair_key(ch['from_member'], ch['to_member'])
    capped = pet_pvp_battles_today(ch['from_member'], ch['to_member'], today) \
        >= pet_pvp_pair_cap()
    won_by = ch['from_member'] if replay['winner'] == 'a' else ch['to_member']
    lost_by = ch['to_member'] if replay['winner'] == 'a' else ch['from_member']
    awards = {}
    if not capped:
        # BOTH sides are paid, and the loser meaningfully. A child who says
        # yes and loses must not come away with nothing.
        awards[won_by] = grant_pet_xp(won_by, PET_PVP_WIN_XP, 'battle',
                                      note='won a family battle')
        awards[lost_by] = grant_pet_xp(lost_by, PET_PVP_LOSS_XP, 'battle',
                                       note='fought a family battle')

    import uuid as _uuid
    row = {'id': _uuid.uuid4().hex, 'member_id': ch['from_member'],
           'date_str': today, 'pair': pair, 'pet_id': ch['from_pet'],
           'opponent': ch['to_pet'], 'opponent_name': theirs['name'],
           'seed': int(seed), 'level_match': True,
           'a_in': mine, 'b_in': theirs, 'winner': replay['winner'],
           'won': replay['winner'] == 'a', 'xp': awards.get(ch['from_member'], 0),
           'capped': bool(capped), 'challenge_id': challenge_id,
           'created_at': time.time()}
    with db_lock:
        pet_battles_table.insert(row)
        pet_challenges_table.update({'state': 'accepted', 'battle_id': row['id'],
                                     'decided_at': time.time()},
                                    Query().id == challenge_id)
    return {'challenge': dict(ch, state='accepted', battle_id=row['id']),
            'battle': row, 'replay': replay, 'awards': awards,
            'capped': bool(capped)}


def get_pet_battles(member_id: str = None, limit: int = 20) -> List[dict]:
    with db_lock:
        allrows = [dict(b) for b in pet_battles_table.all()]
    if member_id:
        # Both sides of a family battle own it -- the row is filed under the
        # challenger, but the sibling who accepted was equally there.
        their_pets = {p['id'] for p in get_pets(member_id, include_retired=True)}
        rows = [b for b in allrows
                if b.get('member_id') == member_id
                or b.get('opponent') in their_pets]
    else:
        rows = allrows
    rows.sort(key=lambda r: r.get('created_at') or 0, reverse=True)
    return rows[:limit]


def get_pet_battle(battle_id: str) -> Optional[dict]:
    with db_lock:
        res = pet_battles_table.search(Query().id == battle_id)
    return dict(res[0]) if res else None


def replay_pet_battle(battle_id: str) -> Optional[dict]:
    """Reconstruct a stored fight, move for move, from its seed."""
    from services import pet_battle
    b = get_pet_battle(battle_id)
    if not b:
        return None
    return pet_battle.resolve(b['a_in'], b['b_in'], seed=b['seed'],
                              level_match=b.get('level_match', True))


def delete_pet(pet_id: str) -> bool:
    """A deliberate act, exposed so the hand path is complete. Nothing in the
    app calls this on its own."""
    with db_lock:
        return bool(pets_table.remove(Query().id == pet_id))


# --- Prep kits ---
# Packing lists matched to events by title keywords. Setup is meant to be
# agent-assisted (the /routines page's Suggest flow), kept honest by parent
# review before saving.

def get_prep_kits() -> List[dict]:
    with db_lock:
        return [dict(k) for k in prep_kits_table.all()]

def add_prep_kit(data: dict) -> str:
    with db_lock:
        prep_kits_table.insert(data)
        return data['id']

def update_prep_kit(kit_id: str, data: dict) -> bool:
    with db_lock:
        return bool(prep_kits_table.update(data, Query().id == kit_id))

def delete_prep_kit(kit_id: str):
    with db_lock:
        prep_kits_table.remove(Query().id == kit_id)

# --- Daily stats snapshots (weekly family digest) ---
# The combined schedule cache is forward-looking, so each evening's
# per-driver/per-kid numbers are snapshotted here before the day rolls out.

def upsert_daily_stats(date_str: str, data: dict):
    with db_lock:
        daily_stats_table.upsert(data, Query().date == date_str)

def get_daily_stats(date_strs: List[str]) -> List[dict]:
    wanted = set(date_strs)
    with db_lock:
        return [dict(r) for r in daily_stats_table.all() if r.get('date') in wanted]


def bump_day_counter(date_str: str, key: str, by: int = 1) -> int:
    """Tally something as it happens (services/vitals.py reads these at night).

    Deliberately fire-and-forget for callers: a counter that throws must never
    take down the thing it was counting."""
    with db_lock:
        res = day_counters_table.search(Query().date == date_str)
        row = dict(res[0]) if res else {'date': date_str}
        row[key] = int(row.get(key) or 0) + by
        day_counters_table.upsert(row, Query().date == date_str)
    return row[key]


def get_day_counters(date_str: str) -> dict:
    with db_lock:
        res = day_counters_table.search(Query().date == date_str)
        return dict(res[0]) if res else {}


def prune_day_counters(before_date: str) -> int:
    """Counters older than the vitals window are dead weight."""
    with db_lock:
        doomed = [r['date'] for r in day_counters_table.all()
                  if str(r.get('date') or '') < before_date]
        for d in doomed:
            day_counters_table.remove(Query().date == d)
    return len(doomed)

# --- Rewards + redemptions ---

def get_rewards() -> List[dict]:
    with db_lock:
        return [dict(r) for r in rewards_table.all()]

def add_reward(data: dict) -> str:
    with db_lock:
        rewards_table.insert(data)
        return data['id']

def update_reward(reward_id: str, data: dict) -> bool:
    with db_lock:
        ok = bool(rewards_table.update(data, Query().id == reward_id))
        if ok and data.get('pooled') is False:
            # No longer a family goal: outstanding pledges have nothing to
            # fund, release the holds.
            pool_contributions_table.remove(Query().reward_id == reward_id)
        return ok

def delete_reward(reward_id: str):
    with db_lock:
        rewards_table.remove(Query().id == reward_id)
        pool_contributions_table.remove(Query().reward_id == reward_id)

def get_redemptions(member_id: str = None, state: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in redemptions_table.all()]
    if member_id:
        rows = [r for r in rows if r.get('member_id') == member_id]
    if state:
        rows = [r for r in rows if r.get('state') == state]
    rows.sort(key=lambda r: r.get('requested_at', 0), reverse=True)
    return rows

def get_spendable_points(member_id: str) -> int:
    """Balance minus every hold: pending redemption requests AND pool
    pledges. Both are promises against the balance that haven't hit the
    ledger yet, so both must count or a kid could spend points twice."""
    balance = get_points_balance(member_id)
    pending = sum(r['cost'] for r in get_redemptions(member_id, 'pending'))
    pledged = sum(c['amount'] for c in get_pool_contributions(member_id=member_id))
    return balance - pending - pledged

def request_redemption(reward_id: str, member_id: str) -> str:
    """Returns redemption id | 'missing' | 'pooled' | 'insufficient'.
    Pending requests and pool pledges count against the spendable balance
    so a kid can't double-spend."""
    import time
    import uuid as _uuid
    with db_lock:
        reward = rewards_table.search(Query().id == reward_id)
        if not reward:
            return 'missing'
        reward = dict(reward[0])
    if reward.get('pooled'):
        return 'pooled'
    if get_spendable_points(member_id) < reward.get('cost', 0):
        return 'insufficient'
    redemption = {
        'id': _uuid.uuid4().hex, 'reward_id': reward_id,
        'reward_title': reward.get('title'), 'cost': int(reward.get('cost', 0)),
        'member_id': member_id, 'state': 'pending',
        'requested_at': time.time(), 'decided_by': None, 'decided_at': None,
    }
    with db_lock:
        redemptions_table.insert(redemption)
    return redemption['id']

def decide_redemption(redemption_id: str, decider_member_id: str, approve: bool,
                      override: bool = False) -> Optional[dict]:
    """Approve deducts points via the ledger; deny just closes it.

    Returns the redemption, None if it isn't pending, or `'insufficient'` when
    approving would take the child negative and no override was given.

    The request path already holds points against the balance
    (`get_spendable_points` subtracts pending requests and pool pledges), so a
    kid cannot ask for more than they would have left. The hole this closes is
    later: a parent `adjust_points` downward does not cancel existing holds
    (`reset_points` does — a hold against a zeroed balance can never be
    honoured), so an approved-months-later request could deduct points that
    are no longer there. Refusing by default makes the balance mean something;
    the override exists because a parent saying "have it anyway" is a real
    decision, and is stamped on the row rather than being invisible.
    """
    import time
    import uuid as _uuid
    with db_lock:
        rows = redemptions_table.search(Query().id == redemption_id)
        if not rows or rows[0].get('state') != 'pending':
            return None
        red = dict(rows[0])
        # Denials never bounds-check: closing a request costs nothing, and
        # reset_points relies on being able to deny holds against a zero.
        if approve and not override \
                and get_points_balance(red['member_id']) < int(red.get('cost', 0)):
            return 'insufficient'
        updates = {'state': 'approved' if approve else 'denied',
                   'decided_by': decider_member_id, 'decided_at': time.time()}
        if approve and override:
            updates['overridden'] = True
        redemptions_table.update(updates, Query().id == redemption_id)
        red.update(updates)
        if approve:
            points_ledger_table.insert({
                'id': _uuid.uuid4().hex, 'member_id': red['member_id'],
                'delta': -int(red['cost']), 'reason': 'redeem',
                'chore_id': None, 'chore_title': red['reward_title'],
                'by_member_id': decider_member_id, 'ts': time.time(),
            })
    return red

# --- Pooled rewards (family goals) ---
# A pooled reward is funded by pledges from several children ("Family Movie
# Night, 200 pts"). A pledge is a HOLD, exactly like a pending redemption:
# it reduces spendable points but writes nothing to the ledger until a
# parent grants the pool — so withdrawing a pledge or canceling the whole
# pool needs no refund machinery. The pool can never exceed the reward's
# cost (contributions clamp to what's remaining), so a grant deducts each
# child exactly what they pledged.

def get_pool_contributions(reward_id: str = None, member_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(c) for c in pool_contributions_table.all()]
    if reward_id:
        rows = [c for c in rows if c.get('reward_id') == reward_id]
    if member_id:
        rows = [c for c in rows if c.get('member_id') == member_id]
    rows.sort(key=lambda c: c.get('ts', 0))
    return rows

def get_pool_status(reward: dict) -> dict:
    """Progress summary for one pooled reward: total pledged, the per-child
    split (enriched with name/color for thermometer segments), and whether
    it is funded / who is still short of min_share."""
    contribs = get_pool_contributions(reward_id=reward['id'])
    # ONE list, two different questions, and they want different answers.
    # Naming a past contribution is history — a child who has since left the
    # family still pledged those points and their segment must keep its name
    # and colour. Being STILL SHORT is a live roster question, and listing a
    # departed child as owing points toward a reward nobody will buy them is
    # nonsense. So: index everybody, but chase only the present.
    members = {m['id']: m for m in get_all_members(include_archived=True)}
    enriched = [{
        'member_id': c['member_id'],
        'member_name': (members.get(c['member_id']) or {}).get('name'),
        'color_code': (members.get(c['member_id']) or {}).get('color_code'),
        'amount': int(c.get('amount', 0)),
    } for c in contribs]
    pledged = sum(c['amount'] for c in enriched)
    cost = int(reward.get('cost', 0))
    min_share = int(reward.get('min_share', 0) or 0)
    short = []
    if min_share > 0:
        by_member = {c['member_id']: c['amount'] for c in enriched}
        short = [m.get('name') for m in members.values()
                 if m.get('role') == 'child'
                 and member_status(m) != 'archived'
                 and by_member.get(m['id'], 0) < min_share]
    return {'pledged': pledged, 'cost': cost, 'remaining': max(0, cost - pledged),
            'funded': pledged >= cost, 'contributions': enriched,
            'min_share': min_share, 'short': short}

def contribute_to_pool(reward_id: str, member_id: str, amount: int):
    """Pledge points toward a pooled reward. Returns ('ok', pledged_amount)
    with the possibly-clamped amount, or an error string: 'missing' |
    'not_pooled' | 'invalid' | 'full' | 'insufficient'. Repeat pledges from
    the same child add to their existing one."""
    import time
    import uuid as _uuid
    with db_lock:
        rows = rewards_table.search(Query().id == reward_id)
        if not rows:
            return 'missing', 0
        reward = dict(rows[0])
    if not reward.get('pooled'):
        return 'not_pooled', 0
    amount = int(amount)
    if amount <= 0:
        return 'invalid', 0
    status = get_pool_status(reward)
    if status['remaining'] <= 0:
        return 'full', 0
    amount = min(amount, status['remaining'])
    if get_spendable_points(member_id) < amount:
        return 'insufficient', 0
    with db_lock:
        q = (Query().reward_id == reward_id) & (Query().member_id == member_id)
        existing = pool_contributions_table.search(q)
        if existing:
            pool_contributions_table.update(
                {'amount': int(existing[0].get('amount', 0)) + amount,
                 'ts': time.time()}, q)
        else:
            pool_contributions_table.insert({
                'id': _uuid.uuid4().hex, 'reward_id': reward_id,
                'member_id': member_id, 'amount': amount, 'ts': time.time(),
            })
    return 'ok', amount

def withdraw_pool_pledge(reward_id: str, member_id: str) -> int:
    """Releases a child's whole pledge on one pool. Returns the amount
    released (0 = no pledge existed)."""
    with db_lock:
        q = (Query().reward_id == reward_id) & (Query().member_id == member_id)
        rows = pool_contributions_table.search(q)
        if not rows:
            return 0
        pool_contributions_table.remove(q)
        return int(rows[0].get('amount', 0))

def clear_pool(reward_id: str) -> int:
    """Releases every pledge on a pool (parent cancel). Returns how many
    pledges were released."""
    with db_lock:
        n = len(pool_contributions_table.search(Query().reward_id == reward_id))
        pool_contributions_table.remove(Query().reward_id == reward_id)
        return n

def grant_pool(reward_id: str, decider_member_id: str, force: bool = False):
    """Parent grants a funded pool: one negative 'redeem' ledger entry per
    contributor for exactly their pledge, one approved redemption row
    (pooled=True, member_id None) for history/digest, pledges cleared.
    Returns (redemption_row, None) or (None, 'missing'|'unfunded'|'short')."""
    import time
    import uuid as _uuid
    with db_lock:
        rows = rewards_table.search(Query().id == reward_id)
        if not rows or not dict(rows[0]).get('pooled'):
            return None, 'missing'
        reward = dict(rows[0])
    status = get_pool_status(reward)
    if not status['funded']:
        return None, 'unfunded'
    if status['short'] and not force:
        return None, 'short'
    now = time.time()
    with db_lock:
        for c in status['contributions']:
            if c['amount'] <= 0:
                continue
            points_ledger_table.insert({
                'id': _uuid.uuid4().hex, 'member_id': c['member_id'],
                'delta': -int(c['amount']), 'reason': 'redeem',
                'chore_id': None, 'chore_title': reward.get('title'),
                'by_member_id': decider_member_id, 'ts': now,
            })
        redemption = {
            'id': _uuid.uuid4().hex, 'reward_id': reward_id,
            'reward_title': reward.get('title'), 'cost': status['pledged'],
            'member_id': None, 'state': 'approved', 'pooled': True,
            'contributions': [{'member_id': c['member_id'], 'amount': c['amount']}
                              for c in status['contributions']],
            'requested_at': now, 'decided_by': decider_member_id, 'decided_at': now,
        }
        redemptions_table.insert(redemption)
        pool_contributions_table.remove(Query().reward_id == reward_id)
    return redemption, None

# --- Family messaging (chat_channels / chat_messages / channel_reads) ---

_MESSAGES_PER_CHANNEL_CAP = 500

def get_channel(channel_id: str) -> Optional[dict]:
    with db_lock:
        res = chat_channels_table.search(Query().id == channel_id)
        return dict(res[0]) if res else None

def get_family_channel() -> Optional[dict]:
    with db_lock:
        res = chat_channels_table.search(Query().kind == 'family')
        return dict(res[0]) if res else None

def get_or_create_dm(member_a: str, member_b: str) -> dict:
    import uuid as _uuid
    import time
    pair = sorted([member_a, member_b])
    dm_key = ':'.join(pair)
    with db_lock:
        res = chat_channels_table.search(Query().dm_key == dm_key)
        if res:
            return dict(res[0])
        channel = {
            'id': _uuid.uuid4().hex,
            'kind': 'dm',
            'member_ids': pair,
            'dm_key': dm_key,
            'event_id': None,
            'event_end': None,
            'title': '',
            'created_at': time.time(),
            'archived': False,
        }
        chat_channels_table.insert(channel)
        return channel

def get_or_create_group(member_ids: List[str], title: str = '') -> dict:
    """Group chat with an explicit member set (>=3 members incl. the creator).
    Get-or-create keyed on the sorted member set, same idea as DMs — the
    family channel stays the special implicit-everyone channel; groups are for
    arbitrary subsets ("parents only"). A provided title refreshes an
    existing group's name."""
    import uuid as _uuid
    import time
    ids = sorted(set(member_ids))
    group_key = ':'.join(ids)
    with db_lock:
        res = chat_channels_table.search(Query().dm_key == group_key)
        if res:
            existing = dict(res[0])
            if title and title != existing.get('title'):
                chat_channels_table.update({'title': title}, Query().id == existing['id'])
                existing['title'] = title
            return existing
        channel = {
            'id': _uuid.uuid4().hex,
            'kind': 'group',
            'member_ids': ids,
            'dm_key': group_key,
            'event_id': None,
            'event_end': None,
            'title': title or '',
            'created_at': time.time(),
            'archived': False,
        }
        chat_channels_table.insert(channel)
        return channel

def get_or_create_event_channel(event_id: str, title: str = '',
                                event_end: str = None) -> dict:
    import uuid as _uuid
    import time
    with db_lock:
        res = chat_channels_table.search(Query().event_id == event_id)
        if res:
            existing = dict(res[0])
            # keep the snapshot fresh if the event was renamed/moved
            updates = {}
            if title and title != existing.get('title'):
                updates['title'] = title
            if event_end and event_end != existing.get('event_end'):
                updates['event_end'] = event_end
            if updates:
                chat_channels_table.update(updates, Query().id == existing['id'])
                existing.update(updates)
            return existing
        channel = {
            'id': _uuid.uuid4().hex,
            'kind': 'event',
            'member_ids': [],  # household-visible, like the family channel
            'dm_key': None,
            'event_id': event_id,
            'event_end': event_end,
            'title': title or 'Event chat',
            'created_at': time.time(),
            'archived': False,
        }
        chat_channels_table.insert(channel)
        return channel

# Channel kind → the chat facet that gates its DISCOVERY (family-network S6,
# §6A). Membership still does the work for dm/group — 'all' on chat.dms means
# "your DMs are yours", never "read everyone's".
_CHANNEL_KIND_FACET = {'family': 'chat.family', 'dm': 'chat.dms',
                       'group': 'chat.groups', 'event': 'chat.event_threads'}


def add_channel_member(channel_id: str, member_id: str) -> Optional[dict]:
    """Family-network S11: let somebody into ONE channel. On event threads
    member_ids stays ADDITIVE — [] is still household-visible, and a
    populated list only ever grants outside hands, never narrows the
    household (can_see treats instance membership as additive over the
    facet, §7)."""
    with db_lock:
        res = chat_channels_table.search(Query().id == channel_id)
        if not res:
            return None
        c = dict(res[0])
        ids = list(c.get('member_ids') or [])
        if member_id not in ids:
            ids.append(member_id)
            chat_channels_table.update({'member_ids': ids},
                                       Query().id == channel_id)
            c['member_ids'] = ids
        return c


def remove_channel_member(channel_id: str, member_id: str) -> Optional[dict]:
    with db_lock:
        res = chat_channels_table.search(Query().id == channel_id)
        if not res:
            return None
        c = dict(res[0])
        ids = [i for i in (c.get('member_ids') or []) if i != member_id]
        chat_channels_table.update({'member_ids': ids}, Query().id == channel_id)
        c['member_ids'] = ids
        return c


def get_channels_for_member(member_id: str) -> List[dict]:
    """Family channel + this member's DMs/groups + non-archived event threads,
    filtered by the member's chat scope (family-network S6): a helper's list
    is DMs-only exactly as before (chat.family/groups/event_threads: none),
    and a member whose class level is 'none' still sees a channel they are an
    EXPLICIT member of — instance grants are additive, the Slack
    external-guest shape. Event threads whose event ended >7 days ago are
    archived on the way out."""
    from datetime import datetime, timedelta, timezone
    from services import scope
    member = get_member(member_id)
    with db_lock:
        out = []
        for c in chat_channels_table.all():
            c = dict(c)
            if c.get('kind') in ('dm', 'group') and member_id not in (c.get('member_ids') or []):
                continue  # membership does the work; the facet gates discovery
            if member is not None and not scope.can_see(
                    member, _CHANNEL_KIND_FACET.get(c.get('kind') or '', 'chat.groups'),
                    instance_member_ids=c.get('member_ids') or []):
                continue
            if c.get('kind') == 'event' and not c.get('archived') and c.get('event_end'):
                try:
                    end = datetime.fromisoformat(c['event_end'])
                    if end.tzinfo is None:
                        end = end.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - end) > timedelta(days=7):
                        chat_channels_table.update({'archived': True}, Query().id == c['id'])
                        c['archived'] = True
                except Exception:
                    pass
            if c.get('archived'):
                continue
            out.append(c)
        return out

# --- Moment media files (Presence: video clips; served by /api/media/{id}) ---

_MEDIA_EXT_BY_MIME = {'video/mp4': '.mp4', 'video/webm': '.webm',
                      'video/quicktime': '.mov', 'video/x-m4v': '.m4v'}
_MEDIA_MIME_BY_EXT = {v: k for k, v in _MEDIA_EXT_BY_MIME.items()}
# Serving also covers poster frames, which are never an upload target.
_MEDIA_SERVE_MIME = dict(_MEDIA_MIME_BY_EXT, **{'.jpg': 'image/jpeg',
                                                '.png': 'image/png',
                                                '.webp': 'image/webp'})
_VIDEO_EXTS = tuple(_MEDIA_MIME_BY_EXT)
_MEDIA_ID_RE = None  # compiled lazily


def _ffmpeg_path() -> Optional[str]:
    import shutil
    return shutil.which('ffmpeg')


def _ffprobe_path() -> Optional[str]:
    import shutil
    return shutil.which('ffprobe')


# A wall panel is the weakest player in the house — a Raspberry Pi decoding in
# software, because Chromium there has no reliable hardware H.264 path. What it
# can sustain is bounded by PIXELS PER SECOND, so both halves of that get a cap
# and neither is negotiable at playback time.
_CLIP_LONG_SIDE = 1280      # cap the LONG side, whichever way the phone was held
_CLIP_MAX_FPS = 30          # phones shoot 60; slow-mo shoots 240


def _probe_fps(path: str) -> float:
    """Frames per second of a clip's video stream, or 0 if it can't be read.

    Deliberately the ONLY thing read back from ffprobe. Dimensions are not:
    ffprobe reports the CODED size, and a phone records portrait as landscape
    plus a 90° display matrix, so a clip that plays 1080x1920 probes as
    1920x1080. ffmpeg's filter chain sees the frame after auto-rotation, which
    is why the scaler below works in `iw`/`ih` expressions rather than in
    numbers computed here — those would be sideways for exactly the clips this
    is most needed for."""
    probe = _ffprobe_path()
    if not probe:
        return 0.0
    import subprocess
    try:
        out = subprocess.run(
            [probe, '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=avg_frame_rate',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            check=True, capture_output=True, timeout=30).stdout.decode().strip()
        num, _, den = out.partition('/')
        return float(num) / float(den or 1) if float(den or 1) else 0.0
    except Exception:
        return 0.0


# finalize_media_upload starts a thread per clip, so three moments landing
# together launched three ffmpeg processes, each happy to take every core on a
# box that is also serving the uploads still in flight. Queueing costs latency
# on the last clip and protects everything else. Posters are single-frame
# extracts (cheap, but a gallery can ask for dozens at once), so they get their
# own, looser gate rather than competing with a full transcode.
_TRANSCODE_GATE = threading.Semaphore(1)
_POSTER_GATE = threading.Semaphore(2)


def poster_available(stem: str) -> bool:
    """Can a poster for this clip actually be served? Either it already
    exists, or ffmpeg is here to make one on request. Callers must not
    advertise a poster URL otherwise — a 404 renders as an empty tile."""
    if media_read_path(stem + '.jpg'):
        return True
    return bool(_ffmpeg_path())


def generate_poster(stem: str) -> bool:
    """Extract a still frame from a clip as {stem}.jpg — the thumbnail every
    video tile shows. Without it a <video> tile is just a black box (browsers
    don't reliably paint a frame for preload=metadata), and tiles would have
    to download video bytes to show anything. Seeks 1s in (the very first
    frame is often a blur or a black lead-in) and falls back to frame 0 for
    clips shorter than that. Cheap and idempotent; safe to call on demand."""
    if not _ffmpeg_path():
        return False
    src = None
    for name in [stem + e for e in _VIDEO_EXTS] + [stem + '.orig']:
        p = media_read_path(name)
        if p:
            src = p
            break
    if not src:
        return False
    out = media_write_path(stem + '.jpg')
    # Beside the destination, so the os.replace below stays atomic.
    tmp = os.path.join(os.path.dirname(out), stem + '.tmp.jpg')
    import subprocess
    for seek in ('1', '0'):
        try:
            with _POSTER_GATE:
                subprocess.run(
                    [_ffmpeg_path(), '-y', '-ss', seek, '-i', src, '-frames:v', '1',
                     '-vf', "scale='min(640,iw)':-2", '-q:v', '4', tmp],
                    check=True, capture_output=True, timeout=120)
            if os.path.getsize(tmp) > 0:
                os.replace(tmp, out)
                return True
        except Exception:
            continue
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    return False


def _transcode_media(stem: str):
    """Background: normalize {stem}.orig to a wall-panel-playable H.264 mp4 at
    {stem}.mp4 — phones record HEVC .mov that Chrome-based wall panels cannot
    decode, and a raw 4K clip is ~10x the size it needs to be. Atomic swap onto
    the SAME media id the attachment already references; until it lands, the
    serving endpoint falls back to the original bytes. On any failure the
    original is renamed into place (store-as-is — never lose the moment).

    What "playable" means is set by the weakest screen in the house, and the
    first version of this only got it right for clips shot sideways:

      - It capped the WIDTH at 1280. Phones are held upright, so a portrait
        1080x1920 clip matched `min(1280,iw)` at its own width and came out
        untouched at 2.1 megapixels a frame — more than double a 720p
        landscape one, on the one player least able to afford it. A 4K
        portrait clip came out 1280x2276, nearly 3 MP. The cap is on the LONG
        side now, so the budget is the same however the phone was held.
      - It kept the source frame rate. 60 fps is the phone default for 1080p
        and slow-mo runs at 120 or 240; halving that halves the decode work
        for motion nobody can see on a kitchen wall.
      - It let the pixel format follow the input. An iPhone HDR clip is
        10-bit, and x264 will happily answer with High 10 — a profile no
        hardware decoder anywhere will touch, so it falls to software on
        every device in the house, not just the panel.

    Together those are up to a 4x cut in pixels per second, which is the
    number that decides whether a clip plays smoothly or judders."""
    import subprocess
    orig = media_read_path(stem + '.orig') or media_write_path(stem + '.orig')
    final = media_write_path(stem + '.mp4')
    # ffmpeg encodes to LOCAL scratch, never straight onto the media root —
    # a multi-minute write onto a network mount is slow and fails badly.
    tmp = os.path.join(media_scratch_dir(), stem + '.tmp.mp4')
    # Scale the budget with the input. A flat 600 s was fine for a 500 MB cap
    # but silently fails a long 4K clip now that the cap is 2 GB — and a
    # transcode timeout means the ORIGINAL is kept as-is, so the one file
    # that most needed shrinking is the one stored at full size.
    try:
        mb = os.path.getsize(orig) / (1024 * 1024)
    except OSError:
        mb = 0
    budget = int(min(3600, max(600, mb * 3)))
    # Fit inside a LONG_SIDE box without ever scaling up, in ffmpeg's own
    # expression language so it runs on the auto-rotated frame (see _probe_fps
    # on why this cannot be arithmetic done here). `min(1, cap/max(iw,ih))` is
    # the scale factor — 1 for anything already small enough — and the
    # round(../2)*2 keeps both sides even, which yuv420p requires. Rounding
    # rather than truncating because the factor is floating point: 3840 * (1280
    # / 3840) lands a hair under 1280 and truncation would ship 1278x718, which
    # looks like a bug even though it plays fine. The single quotes are load
    # bearing — a comma inside min() would otherwise read as the end of this
    # filter and the start of the next one.
    _fit = f"min(1,{_CLIP_LONG_SIDE}/max(iw,ih))"
    chain = [f"scale=w='round(iw*{_fit}/2)*2':h='round(ih*{_fit}/2)*2'"]
    if _probe_fps(orig) > _CLIP_MAX_FPS + 2:   # 59.94 is 60; 30.1 is not 60
        chain.append(f'fps={_CLIP_MAX_FPS}')
    try:
        # The gate is held only around ffmpeg, so queued clips do not burn
        # their own timeout budget waiting for a slot.
        # Run it nice. A 4K decode will take every core it is given, and this
        # box is also running Home Assistant — a pegged CPU reads to the
        # supervisor as an unresponsive add-on.
        nice = None
        if hasattr(os, 'nice'):
            nice = lambda: os.nice(10)   # noqa: E731 — preexec_fn wants a callable
        with _TRANSCODE_GATE:
            # -threads 2 bounds BOTH cpu and peak memory. Frame-level threading
            # holds a decoded frame per thread, and at 4K those are large —
            # unbounded on a small VM that is also running Home Assistant, the
            # OOM killer gets to choose what dies, and it does not choose us.
            # Costs wall-clock on a big clip; the timeout budget already scales.
            subprocess.run(
                [_ffmpeg_path(), '-y', '-threads', '2', '-i', orig,
                 '-vf', ','.join(chain),
                 '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26',
                 # 8-bit 4:2:0 Main: the only combination every decoder in the
                 # house takes in hardware. Without the pix_fmt an HDR source
                 # yields High 10 and nothing can.
                 '-pix_fmt', 'yuv420p', '-profile:v', 'main',
                 '-threads', '2',
                 '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', tmp],
                check=True, capture_output=True, timeout=budget, preexec_fn=nice)
        media_move_into_place(tmp, final)
        os.remove(orig)
        generate_poster(stem)   # thumbnail, so tiles never show a black box
        print(f"[media] transcoded {stem}.mp4")
    except Exception as e:
        # ffmpeg's own stderr is the only thing that explains a kill (OOM,
        # signal, codec) — capture_output swallows it otherwise.
        err = getattr(e, 'stderr', b'') or b''
        if isinstance(err, bytes):
            err = err.decode('utf-8', 'replace')
        print(f"[media] transcode failed for {stem} (storing as-is): {e}"
              + (f"\n[media] ffmpeg stderr tail: {err.strip()[-800:]}" if err else ''))
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
            if os.path.exists(orig):
                media_move_into_place(orig, final)
        except OSError:
            pass


def finalize_media_upload(src_path: str, mime: str) -> Optional[dict]:
    """Take a fully-written upload temp file and register it as moment media;
    returns {'id', 'url', 'mime'} or None for an unsupported mime (the temp
    is removed either way on failure). With ffmpeg available (the add-on
    image ships it) the clip is normalized to H.264 720p mp4 in the
    background and the returned id is the FINAL .mp4 id — the original
    serves in the meantime. Without ffmpeg (bare dev env) the original is
    stored as-is under its native extension."""
    import threading
    import uuid as _uuid
    ext = _MEDIA_EXT_BY_MIME.get((mime or '').lower().split(';')[0])
    if not ext:
        try:
            os.remove(src_path)
        except OSError:
            pass
        return None
    stem = _uuid.uuid4().hex
    if _ffmpeg_path():
        # The raw upload stays LOCAL. It used to be moved onto the media root
        # first, which meant a 200 MB original crossed the network mount, was
        # read back across it to transcode, and only then produced a ~15 MB
        # keeper — three trips over SMB for a file that is about to be
        # deleted. Now only the finished clip and its poster ever cross.
        media_move_into_place(src_path,
                              os.path.join(media_scratch_dir(), stem + '.orig'))
        threading.Thread(target=_transcode_media, args=(stem,), daemon=True).start()
        media_id = stem + '.mp4'
        return {'id': media_id, 'url': f'/api/media/{media_id}', 'mime': 'video/mp4'}
    media_id = stem + ext
    media_move_into_place(src_path, media_write_path(media_id))
    return {'id': media_id, 'url': f'/api/media/{media_id}',
            'mime': _MEDIA_MIME_BY_EXT[ext]}


_PHOTO_EXT_BY_MIME = {'image/jpeg': '.jpg', 'image/jpg': '.jpg',
                      'image/png': '.png', 'image/webp': '.webp'}


def save_photo_data_url(data_url: str) -> Optional[dict]:
    """Persist an inline photo data URL as a FILE in the media store, the way
    clips already are. Photos used to live base64-inline on the message,
    which bloated the database and dragged megabytes through every message
    scan — that, not disk space, was what forced hard downscaling. Returns
    {'id','url','mime'} or None if the data URL is unusable."""
    import base64
    import uuid as _uuid
    try:
        head, _, b64 = str(data_url or '').partition(',')
        if not head.startswith('data:image/') or not b64:
            return None
        mime = head.split(':', 1)[1].split(';', 1)[0].lower()
        ext = _PHOTO_EXT_BY_MIME.get(mime)
        if not ext:
            return None
        raw = base64.b64decode(b64)
    except Exception:
        return None
    if not raw:
        return None
    media_id = _uuid.uuid4().hex + ext
    with open(media_write_path(media_id), 'wb') as f:
        f.write(raw)
    return {'id': media_id, 'url': f'/api/media/{media_id}',
            'mime': _MEDIA_SERVE_MIME.get(ext, 'image/jpeg')}


def save_media_file(data: bytes, mime: str) -> Optional[dict]:
    """Bytes convenience wrapper over finalize_media_upload (tests, small
    clips). Large uploads should stream to a temp file instead."""
    import uuid as _uuid
    tmp = os.path.join(media_scratch_dir(), _uuid.uuid4().hex + '.part')
    with open(tmp, 'wb') as f:
        f.write(data)
    return finalize_media_upload(tmp, mime)


def media_file_path(media_id: str) -> Optional[str]:
    """Validated absolute path for a media id, or None (bad id / missing).
    The id regex doubles as the traversal guard. While a transcode is
    pending, the {stem}.orig fallback serves so a just-sent moment is never
    a 404."""
    global _MEDIA_ID_RE
    if _MEDIA_ID_RE is None:
        import re
        _MEDIA_ID_RE = re.compile(r'^[a-f0-9]{32}\.(mp4|webm|mov|m4v|jpg|png|webp)$')
    if not _MEDIA_ID_RE.match(media_id or ''):
        return None
    stem, ext = os.path.splitext(media_id)
    path = media_read_path(media_id)
    if path:
        return path
    if ext == '.jpg':
        # Poster frames are derived, so a miss is repairable rather than a
        # 404: generate it now (heals clips that predate posters). Never
        # fall through to .orig — that would serve video bytes as an image.
        return media_read_path(media_id) if generate_poster(stem) else None
    return media_read_path(stem + '.orig')


def media_mime(media_id: str) -> str:
    return _MEDIA_SERVE_MIME.get(os.path.splitext(media_id)[1], 'application/octet-stream')


def attachment_items(att) -> List[dict]:
    """Every media in a moment, cover first.

    One item for an ordinary moment, N for an album — so a caller can iterate
    without first asking which it has. THE only place that knows the album
    rule: `items` present means album, absent means the attachment IS the
    media, and `items[0]` is always the same media the top level mirrors.

    Any future migration that rewrites attachments (see the three in
    services/migrations.py that already read/replace top-level `kind`/`url`)
    MUST iterate this — or the equivalent of it — rather than touching only
    the top-level fields. A migration that replaces the whole attachment dict
    from top-level fields alone will silently flatten every album down to its
    cover, discarding every other item with no error anywhere."""
    att = att or {}
    items = att.get('items')
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    return [att] if (att.get('url') or att.get('data_url')) else []


def _delete_media_for_attachment(att):
    """Free the files ONE media owns. Split out from the message sweep so the
    single-item delete route and the whole-message delete share one definition
    of what a media owns — the suffix list is exactly the kind of thing that
    grows on one side and not the other."""
    url = str((att or {}).get('url') or '')
    if not url.startswith('/api/media/'):
        return
    media_id = url.rsplit('/', 1)[-1]
    stem = media_id.split('.')[0]
    if not (len(stem) == 32 and all(c in '0123456789abcdef' for c in stem)):
        return
    for name in (media_id, stem + '.orig', stem + '.tmp.mp4', stem + '.jpg'):
        # Wherever it actually is — sharded or flat, new root or the legacy
        # one a half-finished migration left it in.
        p = media_read_path(name)
        if not p:
            continue
        try:
            os.remove(p)
        except OSError:
            pass


def _delete_media_for_messages(msgs):
    """Best-effort file cleanup when messages roll off the retention cap or are
    deleted outright — a pruned moment must not orphan its clip (or a pending
    transcode's working files) on disk. Iterates EVERY item: an album's
    non-cover media has no other collector, because moments are exempt from
    the retention cap."""
    for m in msgs:
        att = (m.get('attachment') or {}) if isinstance(m, dict) else {}
        for item in attachment_items(att):
            _delete_media_for_attachment(item)


def add_chat_message(message: dict) -> dict:
    with db_lock:
        chat_messages_table.insert(message)
        # Retention cap per channel: household chat, not an archive — EXCEPT
        # moments. A photo/clip is the one thing in a family chat nobody wants
        # aged out ("all moments available forever"), so attachment-bearing
        # messages are exempt and only ordinary chatter is pruned.
        msgs = chat_messages_table.search(Query().channel_id == message['channel_id'])
        overflow = len(msgs) - _MESSAGES_PER_CHANNEL_CAP
        if overflow > 0:
            msgs.sort(key=lambda m: m.get('ts', 0))
            stale = [m for m in msgs if not m.get('attachment')][:overflow]
            if stale:
                _delete_media_for_messages(stale)   # defensive; moments never here
                chat_messages_table.remove(doc_ids=[m.doc_id for m in stale])
        return message

def toggle_message_reaction(message_id: str, member_id: str, emoji: str) -> Optional[dict]:
    """Toggle one member's reaction emoji on a message. Returns the updated
    message dict, or None if the message doesn't exist. Reactions are
    {emoji: [member_id, ...]}; empty lists are pruned."""
    with db_lock:
        res = chat_messages_table.search(Query().id == message_id)
        if not res:
            return None
        msg = dict(res[0])
        reactions = dict(msg.get('reactions') or {})
        ids = list(reactions.get(emoji) or [])
        if member_id in ids:
            ids.remove(member_id)
        else:
            ids.append(member_id)
        if ids:
            reactions[emoji] = ids
        else:
            reactions.pop(emoji, None)
        chat_messages_table.update({'reactions': reactions}, Query().id == message_id)
        msg['reactions'] = reactions
        return msg

def get_chat_message(message_id: str) -> Optional[dict]:
    with db_lock:
        res = chat_messages_table.search(Query().id == message_id)
        return dict(res[0]) if res else None


def delete_chat_message(message_id: str) -> Optional[dict]:
    """Remove a message outright — no tombstone. Returns the deleted message
    (callers need its channel_id to refresh open threads) or None if it was
    already gone. Deleting the ROW is not enough: moments are exempt from the
    retention cap, so nothing else will ever come along and collect the clip,
    poster and transcode working files — without this they leak forever."""
    with db_lock:
        res = chat_messages_table.search(Query().id == message_id)
        if not res:
            return None
        msg = dict(res[0])
        _delete_media_for_messages([msg])
        chat_messages_table.remove(Query().id == message_id)
        return msg


def remove_attachment_item(message_id: str, media_id: str) -> Optional[dict]:
    """Drop ONE media out of a moment, by media id.

    Keyed by id rather than by position on purpose: two people clearing frames
    out of the same album, or one client working from a stale copy, would
    otherwise remove a different photo than the one on screen — and a silently
    wrong deletion of family media is unrecoverable. If the SAME id appears
    more than once in one album, every occurrence is removed together — the
    safe direction, since freeing only one position would leave the surviving
    duplicate pointing at a file that no longer exists.

    The whole read-modify-write runs under ONE lock acquisition (db_lock is
    reentrant, so delete_chat_message's own acquisition nests fine). Splitting
    the read from the write would let two concurrent deletes of DIFFERENT
    frames both read the same starting list and each write back a version
    that silently un-deletes the other's frame while still freeing its file —
    exactly the "two people clearing frames out of the same album" case this
    function exists to protect against.

    Returns {'message': <updated or None>, 'deleted_message': bool}, or None if
    the message has no such media."""
    if not media_id:
        return None                      # empty id must never mass-match url-less items
    with db_lock:
        res = chat_messages_table.search(Query().id == message_id)
        if not res:
            return None
        msg = dict(res[0])
        att = msg.get('attachment') or {}
        items = attachment_items(att)
        # Partitioned BY POSITION, not by value: an album may legitimately hold
        # two entries that compare equal, and `i not in keep` would then
        # quietly free the file the survivor still points at.
        hit = [n for n, i in enumerate(items)
               if str(i.get('url') or '').rsplit('/', 1)[-1] == media_id]
        if not hit:
            return None                  # no such media in this message
        keep = [i for n, i in enumerate(items) if n not in set(hit)]
        gone = [items[n] for n in hit]

        # The LAST media takes the message with it. A moment is media plus a
        # caption; the caption alone is not a moment, and a stranded line of
        # text where a photo was is not what anyone meant by "delete this".
        if not keep:
            return {'message': delete_chat_message(message_id), 'deleted_message': True}

        # An album of two that loses one was never an album — collapse to a
        # plain attachment so "one photo" keeps exactly one representation.
        new_att = dict(keep[0]) if len(keep) == 1 else {**keep[0], 'items': keep}
        chat_messages_table.update({'attachment': new_att}, Query().id == message_id)
        for item in gone:
            _delete_media_for_attachment(item)
        msg['attachment'] = new_att
        return {'message': msg, 'deleted_message': False}


def edit_chat_message(message_id: str, body: str) -> Optional[dict]:
    """Rewrite a message's text, stamping edited_ts so surfaces can mark it.
    The attachment is deliberately untouched — swapping the photo out from
    under a caption is delete-and-repost, not an edit."""
    import time
    with db_lock:
        res = chat_messages_table.search(Query().id == message_id)
        if not res:
            return None
        msg = dict(res[0])
        edited_ts = time.time()
        chat_messages_table.update({'body': body, 'edited_ts': edited_ts},
                                   Query().id == message_id)
        msg['body'] = body
        msg['edited_ts'] = edited_ts
        return msg


def get_event_moment_index() -> List[dict]:
    """One entry per EVENT that has moments — the gallery's top level. No time
    limit by design: moments are exempt from the chat retention cap, so this
    is the family's whole history. Newest event first; cover = newest moment.
    Archived event channels are included (a season is worth keeping)."""
    with db_lock:
        channels = {c['id']: dict(c) for c in chat_channels_table.search(Query().kind == 'event')}
        if not channels:
            return []
        buckets = {}
        for m in chat_messages_table.all():
            ch = channels.get(m.get('channel_id'))
            if not ch or not m.get('attachment'):
                continue
            b = buckets.get(ch['id'])
            if b is None:
                b = buckets[ch['id']] = {
                    'channel_id': ch['id'], 'event_id': ch.get('event_id'),
                    'event_title': ch.get('title') or 'Family moment',
                    'count': 0, 'media_count': 0, 'latest_ts': 0.0, 'cover': None,
                    'sender_ids': set(),
                }
            b['count'] += 1
            b['media_count'] += len(attachment_items(m.get('attachment')))
            b['sender_ids'].add(m.get('sender_member_id'))
            if (m.get('ts') or 0) >= b['latest_ts']:
                b['latest_ts'] = m.get('ts') or 0
                b['cover'] = dict(m)
    return sorted(buckets.values(), key=lambda b: b['latest_ts'], reverse=True)


def get_channel_moments(channel_id: str) -> List[dict]:
    """Every moment in one event's thread, newest first (no time limit)."""
    with db_lock:
        msgs = [dict(m) for m in chat_messages_table.search(Query().channel_id == channel_id)]
    msgs = [m for m in msgs if m.get('attachment')]
    msgs.sort(key=lambda m: m.get('ts', 0), reverse=True)
    return msgs


def get_recent_event_moments(since_ts: float, limit: int = 20) -> List[dict]:
    """Photo moments (messages with an attachment) from event channels, newest
    first — the kiosk hearth feed. Each row is the message plus its channel's
    event_id/title."""
    with db_lock:
        channels = {c['id']: dict(c) for c in chat_channels_table.search(Query().kind == 'event')}
        if not channels:
            return []
        out = []
        for m in chat_messages_table.all():
            m = dict(m)
            ch = channels.get(m.get('channel_id'))
            if not ch or not m.get('attachment') or m.get('ts', 0) < since_ts:
                continue
            m['event_id'] = ch.get('event_id')
            m['event_title'] = ch.get('title')
            out.append(m)
    out.sort(key=lambda m: m.get('ts', 0), reverse=True)
    return out[:limit]

def count_event_moments_since(since_ts: float) -> int:
    """How many moments have landed since `since_ts` — the wall panel's
    catch-up badge, and nothing more. Counted rather than fetched on purpose:
    the badge wants a number, and pulling the feed to length() it would drag
    every attachment (older ones are inline data URLs) across the wire once a
    minute on every panel page.

    A MOMENT is one message. A share carrying several photos counts once."""
    with db_lock:
        channels = {c['id'] for c in chat_channels_table.search(Query().kind == 'event')}
        if not channels:
            return 0
        return sum(1 for m in chat_messages_table.all()
                   if m.get('channel_id') in channels and m.get('attachment')
                   and (m.get('ts') or 0) > since_ts)


def get_channel_messages(channel_id: str, after_ts: float = None,
                         limit: int = 50) -> List[dict]:
    """Ascending by ts; the LAST `limit` messages (optionally after after_ts)."""
    with db_lock:
        msgs = [dict(m) for m in chat_messages_table.search(Query().channel_id == channel_id)]
    if after_ts is not None:
        msgs = [m for m in msgs if m.get('ts', 0) > after_ts]
    msgs.sort(key=lambda m: m.get('ts', 0))
    return msgs[-limit:] if limit else msgs

def set_last_read(channel_id: str, member_id: str, ts: float):
    with db_lock:
        channel_reads_table.upsert(
            {'channel_id': channel_id, 'member_id': member_id, 'last_read_ts': ts},
            (Query().channel_id == channel_id) & (Query().member_id == member_id))

def get_unread_counts(member_id: str) -> dict:
    """{channel_id: unread_count} for every channel visible to the member."""
    with db_lock:
        reads = {r['channel_id']: r.get('last_read_ts', 0)
                 for r in channel_reads_table.search(Query().member_id == member_id)}
    counts = {}
    for c in get_channels_for_member(member_id):
        last_read = reads.get(c['id'], 0)
        with db_lock:
            msgs = chat_messages_table.search(Query().channel_id == c['id'])
            counts[c['id']] = sum(
                1 for m in msgs
                if m.get('ts', 0) > last_read and m.get('sender_member_id') != member_id)
    return counts

def add_telemetry_event(event_data: dict) -> int:
    with db_lock:
        doc_id = telemetry_table.insert(event_data)
        all_events = telemetry_table.all()
        if len(all_events) > 200:
            all_events.sort(key=lambda x: x.get('timestamp', 0))
            excess = len(all_events) - 200
            doc_ids_to_remove = [e.doc_id for e in all_events[:excess]]
            telemetry_table.remove(doc_ids=doc_ids_to_remove)
        return doc_id

def get_telemetry_events(limit: int = 50) -> List[dict]:
    with db_lock:
        events = telemetry_table.all()
        events.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return events[:limit]

def clear_telemetry_events():
    with db_lock:
        telemetry_table.truncate()

# Rule CRUD
def get_all_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            
            # Auto-migrate
            needs_update = False
            if 'keywords' not in doc:
                doc['keywords'] = []
                if doc.get('event_keyword'):
                    doc['keywords'].append(doc['event_keyword'])
                    doc['event_keyword'] = None
                needs_update = True
            
            if 'passenger_ids' not in doc: 
                doc['passenger_ids'] = []
                needs_update = True
            if 'days_of_week' not in doc: 
                doc['days_of_week'] = []
                needs_update = True
            if 'time_start' not in doc: 
                doc['time_start'] = None
                needs_update = True
            if 'time_end' not in doc: 
                doc['time_end'] = None
                needs_update = True
                
            if needs_update:
                rules_table.update(doc, doc_ids=[doc['doc_id']])
                
            rules.append(doc)
        return rules

def _is_duplicate_rule(r1: dict, r2: dict) -> bool:
    import json
    def normalize(v):
        if isinstance(v, dict):
            return {k: normalize(val) for k, val in v.items() if k not in ('id', 'doc_id', 'created_at')}
        elif isinstance(v, list):
            norm_list = [normalize(val) for val in v]
            try:
                return sorted(norm_list)
            except TypeError:
                return sorted(norm_list, key=lambda x: json.dumps(x, sort_keys=True))
        return v
    return normalize(r1) == normalize(r2)

def purge_duplicate_rules():
    with db_lock:
        seen = []
        to_delete = []
        for r in rules_table.all():
            is_dup = False
            for s in seen:
                if _is_duplicate_rule(s, r):
                    is_dup = True
                    break
            if is_dup:
                to_delete.append(r.doc_id)
            else:
                seen.append(r)
        if to_delete:
            rules_table.remove(doc_ids=to_delete)
            
        seen_p = []
        to_delete_p = []
        for p in priority_rules_table.all():
            is_dup = False
            for s in seen_p:
                if _is_duplicate_rule(s, p):
                    is_dup = True
                    break
            if is_dup:
                to_delete_p.append(p.doc_id)
            else:
                seen_p.append(p)
        if to_delete_p:
            priority_rules_table.remove(doc_ids=to_delete_p)

purge_duplicate_rules()

def add_rule(rule_data: dict) -> int:
    with db_lock:
        for existing in rules_table.all():
            if _is_duplicate_rule(existing, rule_data):
                return existing.doc_id
                
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return rules_table.insert(rule_data)

def update_rule(doc_id: int, rule_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        rules_table.update(rule_data, doc_ids=[doc_id])

def delete_rule(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        rules_table.remove(doc_ids=[doc_id])

# Priority Rule CRUD
def get_all_priority_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in priority_rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            
            # Auto-migrate
            needs_update = False
            if 'keywords' not in doc:
                doc['keywords'] = []
                match_type = doc.get('match_type')
                match_value = doc.get('match_value')
                if match_type == 'keyword' and match_value:
                    doc['keywords'].append(match_value)
                needs_update = True
                
            if 'passenger_ids' not in doc:
                doc['passenger_ids'] = []
                match_type = doc.get('match_type')
                match_value = doc.get('match_value')
                if match_type == 'calendar' and match_value:
                    # In legacy, we matched raw calendar ids, but we'll adapt to passenger_ids if it's there
                    pass
                needs_update = True
                
            if 'days_of_week' not in doc: 
                doc['days_of_week'] = []
                needs_update = True
            if 'time_start' not in doc: 
                doc['time_start'] = None
                needs_update = True
            if 'time_end' not in doc: 
                doc['time_end'] = None
                needs_update = True
                
            if needs_update:
                priority_rules_table.update(doc, doc_ids=[doc['doc_id']])
                
            rules.append(doc)
        return rules

def add_priority_rule(rule_data: dict) -> int:
    with db_lock:
        for existing in priority_rules_table.all():
            if _is_duplicate_rule(existing, rule_data):
                return existing.doc_id
                
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return priority_rules_table.insert(rule_data)

def update_priority_rule(doc_id: int, rule_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        priority_rules_table.update(rule_data, doc_ids=[doc_id])

def delete_priority_rule(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        priority_rules_table.remove(doc_ids=[doc_id])

# Errand Rules CRUD
def get_all_errand_rules() -> List[dict]:
    with db_lock:
        rules = []
        for r in errand_rules_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            rules.append(doc)
        return rules

def add_errand_rule(rule_data: dict) -> int:
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        return errand_rules_table.insert(rule_data)

def update_errand_rule(doc_id: int, rule_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        errand_rules_table.update(rule_data, doc_ids=[doc_id])

def delete_errand_rule(doc_id: int):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        errand_rules_table.remove(doc_ids=[doc_id])

def invalidate_daily_schedule_cache_for_event(event_id: str):
    with db_lock:
        cache_docs = cache_table.all()
        if not cache_docs:
            mark_all_daily_schedules_dirty()
            custom_schedules_table.truncate()
            return
            
        cache = cache_docs[0]
        events = cache.get("events", [])
        
        target_events = []
        for e in events:
            e_id = e.get("id")
            orig_id = e.get("original_event_id")
            recur_id = e.get("recurring_event_id")
            if (e_id == event_id or 
                (orig_id and orig_id == event_id) or 
                (recur_id and recur_id == event_id)):
                target_events.append(e)
                
        if not target_events:
            mark_all_daily_schedules_dirty()
            custom_schedules_table.truncate()
            return
            
        import datetime
        dates_to_invalidate = set()
        for e in target_events:
            start_str = e.get("start")
            end_str = e.get("end")
            if not start_str:
                continue
            try:
                if len(start_str) >= 10:
                    start_dt = datetime.datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                    end_dt = datetime.datetime.fromisoformat(end_str.replace('Z', '+00:00')) if end_str else start_dt
                    
                    curr = start_dt.date()
                    end_date = end_dt.date()
                    while curr <= end_date:
                        dates_to_invalidate.add(curr.strftime("%Y-%m-%d"))
                        curr += datetime.timedelta(days=1)
            except Exception as ex:
                print(f"Error parsing date strings {start_str} / {end_str}: {ex}")
                dates_to_invalidate.add(start_str[:10])
                
        for date_str in dates_to_invalidate:
            entry = daily_schedules_table.get(Query().date_str == date_str)
            if entry:
                entry['events_hash'] = 'DIRTY'
                daily_schedules_table.update(entry, doc_ids=[entry.doc_id])
            
        custom_schedules_table.truncate()

# Overrides CRUD
def get_all_overrides() -> List[dict]:
    with db_lock:
        overrides = []
        for r in overrides_table.all():
            doc = dict(r)
            doc['doc_id'] = r.doc_id
            overrides.append(doc)
        return overrides

def add_override(override_data: dict) -> int:
    invalidate_daily_schedule_cache_for_event(override_data['event_id'])
    # An override written ON the day of the event is a scramble — somebody
    # rearranged the driving while the day was already running. Overrides set
    # ahead of time are just planning and are not counted (services/vitals.py).
    # The date lives on the event, not on the override, so it is looked up.
    try:
        import datetime as _dt
        today = _dt.date.today().isoformat()
        ev_id = str(override_data.get('event_id') or '')
        cache = get_cached_schedule() or {}
        ev = next((e for e in (cache.get('events') or [])
                   if str(e.get('id')) == ev_id), None)
        if ev and str(ev.get('start') or '')[:10] == today:
            bump_day_counter(today, 'late_override')
    except Exception:
        pass
    with db_lock:
        # Overrides are unique per event_id, so remove existing if present
        overrides_table.remove(Query().event_id == override_data['event_id'])
        return overrides_table.insert(override_data)

def delete_override(doc_id: int):
    with db_lock:
        override = overrides_table.get(doc_id=doc_id)
        event_id = override.get('event_id') if override else None
    if event_id:
        invalidate_daily_schedule_cache_for_event(event_id)
    with db_lock:
        overrides_table.remove(doc_ids=[doc_id])

def delete_override_by_event(event_id: str):
    from tinydb import Query
    invalidate_daily_schedule_cache_for_event(event_id)
    with db_lock:
        def match_func(val):
            return val == event_id or str(val).startswith(event_id + '_')
        overrides_table.remove(Query().event_id.test(match_func))


# Schedule Cache
def get_cached_schedule() -> dict:
    with db_lock:
        cache = cache_table.all()
        if cache:
            return cache[0]
        return {}

def set_cached_schedule(schedule_data: dict):
    with db_lock:
        cache_table.truncate()
        cache_table.insert(schedule_data)

def set_cached_trips(trips: List[dict]):
    """Snapshot of the assembled trips list (id/title/start/end/location/
    background_url), written whenever /api/trips runs."""
    with db_lock:
        trips_cache_table.truncate()
        trips_cache_table.insert({'trips': trips, 'at': time.time()})

def get_cached_trips() -> dict:
    with db_lock:
        rows = trips_cache_table.all()
        return dict(rows[0]) if rows else {}

def save_custom_schedule(start_date: str, end_date: str, schedule_data: dict, events_hash: str):
    with db_lock:
        custom_schedules_table.upsert({
            'start_date': start_date,
            'end_date': end_date,
            'schedule': schedule_data,
            'events_hash': events_hash
        }, (Query().start_date == start_date) & (Query().end_date == end_date))

def get_custom_schedule(start_date: str, end_date: str):
    with db_lock:
        res = custom_schedules_table.search((Query().start_date == start_date) & (Query().end_date == end_date))
        if res:
            return res[0]
        return None

def get_all_custom_schedule_keys():
    with db_lock:
        return [{'start_date': doc['start_date'], 'end_date': doc['end_date']} for doc in custom_schedules_table.all()]

def clear_custom_schedules():
    with db_lock:
        custom_schedules_table.truncate()
        daily_schedules_table.truncate()

def get_cached_daily_schedule(date_str: str):
    with db_lock:
        res = daily_schedules_table.search(Query().date_str == date_str)
        if res:
            return res[0]
        return None

def get_all_scheduled_errands() -> dict:
    with db_lock:
        errand_schedules = {}
        for daily in daily_schedules_table.all():
            sched = daily.get('schedule', {})
            for se in sched.get('scheduled_errands', []):
                errand_schedules[se.get('id')] = se.get('start')
        return errand_schedules

def save_cached_daily_schedule(date_str: str, schedule_data: dict, events_hash: str):
    """One schedule per day. There used to be several — an `options` list, an
    `ai_status`, a `selected_index` and the model's `llm_reasoning`, from the
    themed-alternatives arc that was switched off in June 2026 and removed in
    v2.353.0. Rows written before then still carry those keys; nothing reads
    them, and they cost a few bytes until the day's hash changes."""
    with db_lock:
        daily_schedules_table.upsert({
            'date_str': date_str,
            'schedule': schedule_data,
            'events_hash': events_hash,
        }, Query().date_str == date_str)
        
        # Invalidate any custom range caches that might have relied on old daily data
        custom_schedules_table.truncate()


# --- Solve packs: what the solver was actually given, per day -------------
# Negotiation (docs/superpowers/specs/2026-08-28-negotiation-design.md) replays
# a day to ask what would happen if one thing changed. Rebuilding the solver's
# world from storage would drift -- driver_events is built during the calendar
# fetch and the rule list is assembled inside the refresh -- and a drifted
# replay answers a different question than the schedule did. So the refresh
# writes down what it handed the solver, and the negotiator replays that.

def save_solve_pack(date_str: str, pack: dict):
    with db_lock:
        solve_packs_table.upsert({**pack, 'date': date_str},
                                 Query().date == date_str)

def get_solve_pack(date_str: str) -> Optional[dict]:
    with db_lock:
        res = solve_packs_table.search(Query().date == date_str)
        return dict(res[0]) if res else None

def prune_solve_packs(before_date: str) -> int:
    """Yesterday's pack answers no question anybody will ask."""
    with db_lock:
        rows = [dict(r) for r in solve_packs_table.all()]
        stale = [r for r in rows if (r.get('date') or '') < before_date]
        for r in stale:
            solve_packs_table.remove(Query().date == r['date'])
        return len(stale)


# --- Protected exceptions: one evening given up, not a commitment deleted --
# A negotiated lift is for ONE date. Deleting the commitment would turn a
# favour into a permanent loss of the one thing on the calendar that is a
# person's own.

def add_protected_exception(commitment_id: str, date_str: str) -> str:
    with db_lock:
        row = {'commitment_id': str(commitment_id), 'date': str(date_str),
               'created_at': time.time()}
        protected_exceptions_table.upsert(
            row, (Query().commitment_id == str(commitment_id))
                 & (Query().date == str(date_str)))
        return f"{commitment_id}:{date_str}"

def get_protected_exceptions(commitment_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(r) for r in protected_exceptions_table.all()]
    if commitment_id:
        rows = [r for r in rows if str(r.get('commitment_id')) == str(commitment_id)]
    return rows


# --- Shift refusals: the movable flag, learned rather than declared -------
# The app cannot know that moving a calendar record moves the actual practice,
# and guessing wrong produces a deal that makes the family look ridiculous to a
# coach. So the ask is the gate -- and a no is remembered, per series, so the
# same question is not asked twice.

def add_shift_refusal(series_key: str, title: str = '', member_id: str = None):
    with db_lock:
        shift_refusals_table.upsert(
            {'series_key': str(series_key), 'title': title or '',
             'refused_by': member_id or '', 'refused_at': time.time()},
            Query().series_key == str(series_key))

def get_shift_refusals() -> List[dict]:
    with db_lock:
        return [dict(r) for r in shift_refusals_table.all()]

def clear_shift_refusal(series_key: str) -> bool:
    """A flag the app taught itself must be untaught by hand."""
    with db_lock:
        return bool(shift_refusals_table.remove(
            Query().series_key == str(series_key)))


# --- Deals: a set of parts, each one a person giving something up --------
# Parts live inside the deal row rather than in a table of their own: a part
# has no life outside its deal, and the thing every caller actually wants is
# "the deal this part belongs to".

def add_deal(data: dict) -> str:
    from models.schemas import Deal
    with db_lock:
        row = Deal(**data).model_dump()
        deals_table.insert(row)
        return row['id']

def get_deal(deal_id: str) -> Optional[dict]:
    with db_lock:
        res = deals_table.search(Query().id == deal_id)
        return dict(res[0]) if res else None

def get_deals(state: str = None, since_ts: float = None,
              seed_event_id: str = None) -> List[dict]:
    with db_lock:
        rows = [dict(d) for d in deals_table.all()]
    if state:
        rows = [d for d in rows if d.get('state') == state]
    if since_ts is not None:
        rows = [d for d in rows if (d.get('created_at') or 0) >= since_ts]
    if seed_event_id:
        rows = [d for d in rows if str(d.get('seed_event_id')) == str(seed_event_id)]
    rows.sort(key=lambda d: d.get('created_at') or 0, reverse=True)
    return rows

def update_deal(deal_id: str, data: dict) -> bool:
    with db_lock:
        return bool(deals_table.update(data, Query().id == deal_id))

def claim_deal(deal_id: str, expected_state: str, new_state: str) -> bool:
    """Compare-and-set on a deal's state. True only for whoever got there first.

    Applying a deal is not idempotent -- an event shifted twice is 30 minutes
    from where anybody agreed -- and the last two people can answer in the
    same second, since FastAPI runs sync handlers in a threadpool. Read and
    write happen under one hold of `db_lock`, which every other deal write in
    this module also takes, so the window between "still asking" and "mine
    now" cannot be entered twice.
    """
    with db_lock:
        rows = deals_table.search(Query().id == deal_id)
        if not rows or dict(rows[0]).get('state') != expected_state:
            return False
        return bool(deals_table.update({'state': new_state},
                                       Query().id == deal_id))

def prune_deals(before_ts: float) -> int:
    """Deals older than the fairness window answer no question anybody asks.

    Nothing reads a settled deal after that: fairness counts 14 days back, the
    runner-up exclusion the same, and the finding surfaces only open ones. The
    table is otherwise append-only and every `get_deals()` call deserialises
    all of it, so pruning is what keeps a tap cheap a year from now. Open
    deals (`draft`/`asking`/`applying`) are never pruned however old, because
    somebody may still be about to answer one.
    """
    with db_lock:
        rows = [dict(r) for r in deals_table.all()]
        stale = [r for r in rows
                 if (r.get('created_at') or 0) < before_ts
                 and r.get('state') not in ('draft', 'asking', 'applying')]
        for r in stale:
            deals_table.remove(Query().id == r['id'])
        return len(stale)

def get_deal_by_part(part_id: str) -> Optional[dict]:
    with db_lock:
        for row in deals_table.all():
            for p in (row.get('parts') or []):
                if str(p.get('id')) == str(part_id):
                    return dict(row)
    return None

def update_deal_part(part_id: str, data: dict) -> bool:
    row = get_deal_by_part(part_id)
    if not row:
        return False
    parts = []
    for p in row.get('parts') or []:
        parts.append({**p, **data} if str(p.get('id')) == str(part_id) else p)
    return update_deal(row['id'], {'parts': parts})


# Settings CRUD
def get_settings() -> dict:
    with db_lock:
        all_settings = settings_table.all()
        if not all_settings:
            return {"calendar_ids": []}
        return dict(all_settings[0])

def update_settings(settings_data: dict):
    with db_lock:
        custom_schedules_table.truncate()
        mark_all_daily_schedules_dirty()
        settings_table.truncate()
        settings_table.insert(settings_data)

# API Usage Tracker
def get_mapbox_usage(month: str, endpoint: str) -> int:
    """Returns the usage count for the given month (YYYY-MM) and endpoint ('directions' or 'geocode')"""
    with db_lock:
        res = api_usage_table.search((Query().month == month) & (Query().endpoint == endpoint))
        if res:
            return res[0].get('count', 0)
        return 0

def increment_mapbox_usage(month: str, endpoint: str, amount: int = 1):
    with db_lock:
        res = api_usage_table.search((Query().month == month) & (Query().endpoint == endpoint))
        if res:
            new_count = res[0].get('count', 0) + amount
            api_usage_table.update({'count': new_count}, (Query().month == month) & (Query().endpoint == endpoint))
        else:
            api_usage_table.insert({'month': month, 'endpoint': endpoint, 'count': amount})

def log_api_request(endpoint: str, count: int = 1):
    import time
    with db_lock:
        api_requests_log_table.insert({
            'timestamp': time.time(),
            'endpoint': endpoint,
            'count': count
        })
        three_days_ago = time.time() - (3 * 24 * 3600)
        api_requests_log_table.remove(Query().timestamp < three_days_ago)

def get_rolling_usage(endpoint: str, seconds: int) -> int:
    import time
    with db_lock:
        now = time.time()
        start_time = now - seconds
        q = Query()
        records = api_requests_log_table.search((q.endpoint == endpoint) & (q.timestamp >= start_time))
        return sum(r.get('count', 0) for r in records)

# Push Subscriptions
def save_push_subscription(driver_id: str, subscription_info: dict, member_id: str = None):
    # Keyed by endpoint, NOT driver_id: one row per device/browser, so a
    # driver can receive pushes on several devices. (Keying by driver_id
    # meant enabling push on a second device silently replaced the first.)
    # member_id is the hub identity used by messaging; resolved from
    # driver_id when the caller doesn't supply it.
    with db_lock:
        if not member_id and driver_id:
            linked = members_table.search(Query().driver_id == driver_id)
            if linked:
                member_id = linked[0]['id']
        endpoint = (subscription_info or {}).get('endpoint')
        row = {'driver_id': driver_id, 'member_id': member_id,
               'subscription': subscription_info}
        if endpoint:
            row['endpoint'] = endpoint
            push_subscriptions_table.upsert(row, Query().endpoint == endpoint)
        else:
            push_subscriptions_table.upsert(row, Query().driver_id == driver_id)

def delete_push_subscription_by_endpoint(endpoint: str):
    """Prune a dead subscription (push service returned 404/410 for it)."""
    with db_lock:
        q = Query()
        try:
            push_subscriptions_table.remove(q.endpoint == endpoint)
        except Exception:
            pass
        try:
            # Legacy rows saved before the endpoint column existed
            push_subscriptions_table.remove(q.subscription.endpoint == endpoint)
        except Exception:
            pass

def get_push_subscriptions(driver_id: str = None):
    with db_lock:
        if driver_id:
            return push_subscriptions_table.search(Query().driver_id == driver_id)
        return push_subscriptions_table.all()

def get_push_subscriptions_for_member(member_id: str):
    with db_lock:
        return push_subscriptions_table.search(Query().member_id == member_id)

# --- Generic app state (small persistent key/value markers, e.g. the
# "tomorrow digest already sent today" date so restarts don't re-send) ---
def get_app_state(key: str, default=None):
    with db_lock:
        rows = app_state_table.search(Query().key == key)
        return rows[0].get('value') if rows else default

def set_app_state(key: str, value):
    with db_lock:
        app_state_table.upsert({'key': key, 'value': value}, Query().key == key)

# Drive Status
def mark_drive_status(leg_id: str, status: str, **fields):
    """Upsert MERGES rather than replaces: completing a leg must not erase
    the ETA the start wrote, because the arrival endpoints and their tests
    still read it afterwards. Extra fields ride along on the same row
    (started_at, eta_ts, pending_eta_ts, arrival_nudged_ts) — the leg is
    the natural key for all of them and a second table would just be a
    join nobody needs."""
    with db_lock:
        q = Query()
        existing = drive_status_table.search(q.leg_id == leg_id)
        row = dict(existing[0]) if existing else {'leg_id': leg_id}
        row['status'] = status
        row.update(fields)
        drive_status_table.upsert(row, q.leg_id == leg_id)

def get_drive_status(leg_id: str) -> Optional[dict]:
    with db_lock:
        rows = drive_status_table.search(Query().leg_id == leg_id)
    return dict(rows[0]) if rows else None

def get_drive_status_rows(status: str) -> List[dict]:
    """Full rows, unlike the two id-list helpers below — the arrival nudge
    needs eta_ts and its own sent-marker, not just the leg id."""
    with db_lock:
        return [dict(d) for d in drive_status_table.search(Query().status == status)]

# --- Day-of attendance overrides (the retro-split) ---
# {event_id: {'action': 'split'|'stay', 'ts': ...}} in app_state. Instance-
# scoped and deliberately short-lived: 48 hours covers today and tonight's
# solves, and then the calendar is the truth again — a driver's Tuesday
# declaration must never quietly reshape next Tuesday's recurrence.
_ATTENDANCE_TTL_SECS = 48 * 3600

def get_attendance_overrides() -> dict:
    import time
    rows = dict(get_app_state('attendance_overrides') or {})
    cutoff = time.time() - _ATTENDANCE_TTL_SECS
    return {k: v for k, v in rows.items()
            if isinstance(v, dict) and (v.get('ts') or 0) >= cutoff}

def set_attendance_override(event_id: str, action: str) -> None:
    import time
    rows = get_attendance_overrides()      # read-through prunes the stale
    rows[str(event_id)] = {'action': action, 'ts': time.time()}
    set_app_state('attendance_overrides', rows)

# --- Pending Notifications ---
def save_pending_notifications(notifications: List[dict]):
    with db_lock:
        pending_notifications_table.truncate()
        if notifications:
            pending_notifications_table.insert_multiple(notifications)

def get_pending_notifications() -> List[dict]:
    with db_lock:
        return pending_notifications_table.all()

def mark_notification_fired(notif_id: str):
    with db_lock:
        q = Query()
        pending_notifications_table.update({'fired': True}, q.notif_id == notif_id)

def get_event_config(google_id: str) -> Optional[dict]:
    with db_lock:
        q = Query()
        res = event_configs_table.search(q.google_id == google_id)
        if res:
            return res[0]
        return None

def set_event_config(google_id: str, config_data: dict):
    invalidate_daily_schedule_cache_for_event(google_id)
    with db_lock:
        q = Query()
        config_data['google_id'] = google_id
        event_configs_table.upsert(config_data, q.google_id == google_id)

def delete_event_config(google_id: str):
    invalidate_daily_schedule_cache_for_event(google_id)
    with db_lock:
        q = Query()
        event_configs_table.remove(q.google_id == google_id)

# Prep status: the driver's "stuff is in the car" checkoff, keyed by the
# PARENT event instance id (split _dropoff/_pickup legs share one checkoff;
# _unrolled_ recurrence instances stay distinct). Unconfirming removes the
# row, so the table only ever holds confirmations.
def set_prep_confirmed(event_id: str, confirmed: bool, member_id: str = None):
    import time
    with db_lock:
        if confirmed:
            prep_status_table.upsert(
                {'event_id': event_id, 'confirmed_by': member_id, 'ts': time.time()},
                Query().event_id == event_id)
        else:
            prep_status_table.remove(Query().event_id == event_id)

def get_confirmed_preps() -> List[str]:
    with db_lock:
        return [doc['event_id'] for doc in prep_status_table.all()]

# A packing CLAIM: one person (or one anonymous pair of hands at the wall)
# has packed one of something for one outing on one day.
#
# A count, not a checkbox, because an item needs as many as there are people
# it covers — two children at one practice need two water bottles, and a
# single tick is how one of them goes thirsty.
#
# `member_id` is None for a tap on the wall. The wall has no identity and
# guessing one would be a lie with a currency attached: `prep_status` already
# writes a `confirmed_by` nobody ever reads, and this does not repeat it.
def add_packing_claim(outing_key: str, item_key: str, date_str: str,
                      member_id: str = None) -> int:
    """Record one claim. Returns the xp minted (0 for an anonymous tap)."""
    import time
    import uuid as _uuid
    with db_lock:
        packing_claims_table.insert({
            'id': _uuid.uuid4().hex, 'outing_key': str(outing_key),
            'item_key': str(item_key), 'date_str': str(date_str),
            'member_id': member_id, 'ts': time.time()})
    if not member_id:
        return 0
    # Packing your own bag is real work and the household wanted it to feel
    # that way — but it is not a chore somebody assigned (no points) and not a
    # habit (no routine, no streak). `once` per (member, item, day) is the
    # same anti-faucet guard routines pass, because a child can tick and untick
    # a box all afternoon.
    return grant_pet_xp(member_id, PACKING_XP, 'prep',
                        ref_id=str(item_key), date_str=str(date_str), once=True)


def remove_packing_claim(outing_key: str, item_key: str, date_str: str,
                         member_id: str = None) -> bool:
    """Drop ONE claim — the member's own if named, else any anonymous one.

    The xp is never clawed back: a thing earned is never taken away, and a box
    tapped by accident must not cost a child anything.
    """
    with db_lock:
        rows = packing_claims_table.search(
            (Query().outing_key == str(outing_key))
            & (Query().item_key == str(item_key))
            & (Query().date_str == str(date_str)))
        if member_id:
            mine = [r for r in rows if r.get('member_id') == member_id]
            rows = mine or [r for r in rows if not r.get('member_id')]
        else:
            anon = [r for r in rows if not r.get('member_id')]
            rows = anon or rows
        if not rows:
            return False
        packing_claims_table.remove(Query().id == rows[0]['id'])
        return True


def get_packing_claims(date_str: str) -> List[dict]:
    with db_lock:
        return packing_claims_table.search(Query().date_str == str(date_str))

def get_completed_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'completed')]

def get_in_progress_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'in_progress')]

# --- Roll call (who is actually in the car) ---
# Kept on the drive_status row rather than a table of its own: the leg is the
# natural key, mark_drive_status already merges extra fields, and a roll call
# outlives nothing that the leg does not outlive. Absent member = never
# tapped, which is the normal case and means nothing bad.
def set_roll_call(leg_id: str, member_id: str, aboard) -> dict:
    """`aboard` True / False / None (untaps back to unanswered)."""
    with db_lock:
        q = Query()
        existing = drive_status_table.search(q.leg_id == leg_id)
        row = dict(existing[0]) if existing else {'leg_id': leg_id,
                                                  'status': 'pending'}
        roll = dict(row.get('roll_call') or {})
        if aboard is None:
            roll.pop(str(member_id), None)
        else:
            roll[str(member_id)] = bool(aboard)
        row['roll_call'] = roll
        drive_status_table.upsert(row, q.leg_id == leg_id)
        return roll

def get_roll_call(leg_id: str) -> dict:
    with db_lock:
        rows = drive_status_table.search(Query().leg_id == leg_id)
    return dict((rows[0].get('roll_call') or {})) if rows else {}

# --- Member positions reported BY THE APP ---
# The Home Assistant companion app is the better tracker and stays the first
# source everywhere. This is the lane for the phone that does not have it: the
# drive sheet posts a fix while a drive is running, which is the only window
# where the app has any business knowing where somebody is. One row per
# member, overwritten — a location history is not something this app keeps.
def set_member_position(member_id: str, lat: float, lng: float,
                        accuracy=None, ts: float = None, source: str = 'app'):
    import time as _time
    with db_lock:
        member_positions_table.upsert(
            {'member_id': str(member_id), 'latitude': float(lat),
             'longitude': float(lng),
             'gps_accuracy': float(accuracy) if accuracy is not None else None,
             'ts': float(ts if ts is not None else _time.time()),
             'source': source},
            Query().member_id == str(member_id))

def get_member_position(member_id: str) -> Optional[dict]:
    with db_lock:
        rows = member_positions_table.search(Query().member_id == str(member_id))
    return dict(rows[0]) if rows else None

def clear_member_position(member_id: str):
    with db_lock:
        member_positions_table.remove(Query().member_id == str(member_id))

# --- Errands ---
def get_all_errands() -> List[dict]:
    with db_lock:
        errands = []
        for e in errands_table.all():
            doc = dict(e)
            doc['doc_id'] = e.doc_id
            errands.append(doc)
        return errands

def add_errand(errand_data: dict) -> int:
    with db_lock:
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        custom_schedules_table.truncate()
        return errands_table.insert(errand_data)

def update_errand(doc_id: int, errand_data: dict):
    with db_lock:
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        custom_schedules_table.truncate()
        errands_table.update(errand_data, doc_ids=[doc_id])

def delete_errand(doc_id: int):
    with db_lock:
        mark_all_daily_schedules_dirty()
        cache_table.truncate()
        custom_schedules_table.truncate()
        errands_table.remove(doc_ids=[doc_id])

# --- Trip Metadata ---
def get_all_trip_metadata() -> List[dict]:
    with db_lock:
        return [dict(t) for t in trip_metadata_table.all()]

def get_trip_metadata(event_id: str) -> Optional[dict]:
    with db_lock:
        from tinydb import Query
        res = trip_metadata_table.search(Query().event_id == event_id)
        if res:
            return res[0]
        return None

def set_trip_metadata(event_id: str, metadata: dict):
    with db_lock:
        from tinydb import Query
        metadata['event_id'] = event_id
        trip_metadata_table.upsert(metadata, Query().event_id == event_id)

def delete_trip_metadata(event_id: str):
    with db_lock:
        from tinydb import Query
        trip_metadata_table.remove(Query().event_id == event_id)

def update_conversation_title(conversation_id: str, title: str):
    with db_lock:
        from tinydb import Query
        Conv = Query()
        import time
        conversations_table.update({'title': title, 'updated_at': time.time()}, Conv.id == conversation_id)


# --- ICS feed subscriptions (intake arc phase 1, services/ics_sync.py) ---

def get_ics_feeds() -> List[dict]:
    with db_lock:
        return ics_feeds_table.all()

def get_ics_feed(feed_id: str) -> Optional[dict]:
    with db_lock:
        res = ics_feeds_table.search(Query().id == feed_id)
        return res[0] if res else None

def add_ics_feed(feed: dict) -> str:
    import uuid
    feed = dict(feed)
    feed.setdefault('id', uuid.uuid4().hex)
    feed.setdefault('enabled', True)
    feed.setdefault('event_map', {})
    feed.setdefault('event_count', 0)
    feed.setdefault('last_synced', None)
    feed.setdefault('last_status', 'never synced')
    with db_lock:
        ics_feeds_table.insert(feed)
    return feed['id']

def update_ics_feed(feed_id: str, updates: dict) -> None:
    with db_lock:
        ics_feeds_table.update(updates, Query().id == feed_id)

def delete_ics_feed(feed_id: str) -> None:
    with db_lock:
        ics_feeds_table.remove(Query().id == feed_id)

# --- Email intake: proposals + activity log (services/email_ingest.py) ---

def patch_settings(updates: dict) -> None:
    """Merge keys into settings WITHOUT the schedule-cache invalidation that
    update_settings() performs — for keys (email intake creds/allowlist) that
    cannot affect the solver."""
    with db_lock:
        docs = settings_table.all()
        current = dict(docs[0]) if docs else {}
        current.update(updates)
        settings_table.truncate()
        settings_table.insert(current)

def get_proposals(status: str = None) -> List[dict]:
    with db_lock:
        if status:
            return event_proposals_table.search(Query().status == status)
        return event_proposals_table.all()

def get_proposal(proposal_id: str) -> Optional[dict]:
    with db_lock:
        res = event_proposals_table.search(Query().id == proposal_id)
        return res[0] if res else None

def add_proposal(proposal: dict) -> str:
    import uuid, time
    proposal = dict(proposal)
    proposal.setdefault('id', uuid.uuid4().hex)
    proposal.setdefault('status', 'proposed')
    proposal.setdefault('created_at', time.time())
    with db_lock:
        event_proposals_table.insert(proposal)
    return proposal['id']

def update_proposal(proposal_id: str, updates: dict) -> None:
    with db_lock:
        event_proposals_table.update(updates, Query().id == proposal_id)


# --- Agent action proposals (chat "propose -> approve" cards) -----------------
# Distinct from event_proposals (email intake): these carry a typed action the
# agent wants a human to approve before it mutates the schedule.

def add_action_proposal(proposal: dict) -> str:
    import uuid, time
    proposal = dict(proposal)
    proposal.setdefault('id', uuid.uuid4().hex)
    proposal.setdefault('status', 'proposed')
    proposal.setdefault('created_at', time.time())
    with db_lock:
        agent_action_proposals_table.insert(proposal)
    return proposal['id']

def get_action_proposal(proposal_id: str) -> Optional[dict]:
    with db_lock:
        res = agent_action_proposals_table.search(Query().id == proposal_id)
        return dict(res[0]) if res else None

def update_action_proposal(proposal_id: str, updates: dict) -> None:
    with db_lock:
        agent_action_proposals_table.update(updates, Query().id == proposal_id)

def get_action_proposals(status: str = None, limit: int = 25) -> List[dict]:
    """Newest-first action proposals, optionally filtered by status (C3: the
    dashboard's pending-approvals banner reads status='proposed')."""
    with db_lock:
        rows = [dict(r) for r in agent_action_proposals_table.all()
                if status is None or r.get('status') == status]
        rows.sort(key=lambda r: r.get('created_at', 0), reverse=True)
        return rows[:limit]

def add_ingest_log(entry: dict, cap: int = 200) -> None:
    """Append an accountability row. CONSECUTIVE IDENTICAL rows (same
    from/subject/outcome — in practice a repeated '(poll)' error while the
    mailbox is unreachable, e.g. a DNS outage hitting every 10-minute poll)
    collapse into the previous row: ts bumps to the latest occurrence,
    `count` increments, `first_ts` keeps the start. A day-long outage is one
    line of history instead of the entire capped log."""
    import time
    entry = dict(entry)
    entry.setdefault('ts', time.time())
    with db_lock:
        rows = sorted(ingest_log_table.all(), key=lambda r: r.get('ts', 0))
        if rows:
            last = rows[-1]
            if all(last.get(k) == entry.get(k) for k in ('from', 'subject', 'outcome')):
                ingest_log_table.update(
                    {'ts': entry['ts'],
                     'count': int(last.get('count') or 1) + 1,
                     'first_ts': last.get('first_ts') or last.get('ts')},
                    doc_ids=[last.doc_id])
                return
        ingest_log_table.insert(entry)
        if len(rows) + 1 > cap:
            for r in rows[:len(rows) + 1 - cap]:
                ingest_log_table.remove(doc_ids=[r.doc_id])

def get_ingest_log(limit: int = 50) -> List[dict]:
    with db_lock:
        rows = sorted(ingest_log_table.all(), key=lambda r: r.get('ts', 0), reverse=True)
        return rows[:limit]


# --- Status protocols & status days (Presence & Status arc P1/P2) ------------
# Reusable family day-types + their dated instances. P2: status days feed the
# solver (need='cover'/'help' -> the affected member's driver is out of the
# rotation that date), so day/protocol mutations invalidate the schedule
# caches exactly like rule mutations do.

def _invalidate_schedule_caches():
    custom_schedules_table.truncate()
    mark_all_daily_schedules_dirty()
    cache_table.truncate()

def get_all_status_protocols() -> List[dict]:
    with db_lock:
        return [dict(r) for r in status_protocols_table.all()]

def get_status_protocol(protocol_id: str) -> Optional[dict]:
    with db_lock:
        res = status_protocols_table.search(Query().id == protocol_id)
        return dict(res[0]) if res else None

def add_status_protocol(data: dict) -> str:
    import uuid, time
    data = dict(data)
    data.setdefault('id', uuid.uuid4().hex)
    data.setdefault('created_at', time.time())
    with db_lock:
        status_protocols_table.insert(data)
    return data['id']

def update_status_protocol(protocol_id: str, updates: dict) -> None:
    with db_lock:
        status_protocols_table.update(updates, Query().id == protocol_id)
        _invalidate_schedule_caches()  # need/member changes move driver availability

def delete_status_protocol(protocol_id: str) -> None:
    """Deleting a protocol also drops its dated instances — an orphaned
    status day would render as an unexplained blank on kid surfaces."""
    with db_lock:
        status_protocols_table.remove(Query().id == protocol_id)
        status_days_table.remove(Query().protocol_id == protocol_id)
        _invalidate_schedule_caches()

def get_status_days(start: str = None, end: str = None) -> List[dict]:
    """Dated instances, date-ascending, optionally windowed [start, end]
    (ISO dates, inclusive — string compare is safe on YYYY-MM-DD). A
    multi-day span (P3: end_date set) is returned when it OVERLAPS the
    window, so an ongoing trip still surfaces mid-span."""
    with db_lock:
        rows = []
        for r in status_days_table.all():
            span_end = r.get('end_date') or r.get('date', '')
            if start is not None and span_end < start:
                continue
            if end is not None and r.get('date', '') > end:
                continue
            rows.append(dict(r))
        rows.sort(key=lambda r: (r.get('date', ''), r.get('set_at', 0)))
        return rows

def get_status_day(day_id: str) -> Optional[dict]:
    with db_lock:
        res = status_days_table.search(Query().id == day_id)
        return dict(res[0]) if res else None

def add_status_day(data: dict) -> str:
    """One instance of a given protocol per date: setting the same protocol
    on the same day again just refreshes the note/setter instead of stacking
    duplicate banners (and duplicate announcements read as nagging)."""
    import uuid, time
    data = dict(data)
    data.setdefault('id', uuid.uuid4().hex)
    data.setdefault('set_at', time.time())
    with db_lock:
        q = (Query().date == data.get('date')) & (Query().protocol_id == data.get('protocol_id'))
        existing = status_days_table.search(q)
        if existing:
            status_days_table.update(
                {'note': data.get('note', ''), 'set_by': data.get('set_by'),
                 'end_date': data.get('end_date'), 'set_at': data['set_at']}, q)
            _invalidate_schedule_caches()  # a span end may have moved
            return dict(existing[0])['id']
        status_days_table.insert(data)
        _invalidate_schedule_caches()
    return data['id']

def delete_status_day(day_id: str) -> Optional[dict]:
    """Remove and return the instance (the caller announces the correction —
    'never guessing' means changes of plan get said out loud too). Clearing a
    calendar-set day writes a dismissal tombstone so the keyword sweep never
    re-sets what a parent explicitly cleared (pruned past 30 days)."""
    import time
    with db_lock:
        res = status_days_table.search(Query().id == day_id)
        if not res:
            return None
        row = dict(res[0])
        status_days_table.remove(Query().id == day_id)
        if row.get('source') == 'calendar':
            tombs = dict(get_app_state('status_auto_dismissed') or {})
            cutoff = time.time() - 30 * 86400
            tombs = {k: v for k, v in tombs.items() if v >= cutoff}
            tombs[f"{row.get('date')}:{row.get('protocol_id')}"] = time.time()
            set_app_state('status_auto_dismissed', tombs)
        _invalidate_schedule_caches()
        return row

def status_auto_dismissed(date: str, protocol_id: str) -> bool:
    tombs = get_app_state('status_auto_dismissed') or {}
    return f"{date}:{protocol_id}" in tombs


# --- Per-member music: favorites + recently chosen -------------------------
#
# The row shape is what a music surface DRAWS (uri, media_type, name, image,
# subtitle) — a snapshot taken at the moment of the tap, not a reference to be
# re-resolved. Deliberate: re-resolving every shelf row through Music
# Assistant would make the family's own shelf unavailable exactly when MA is,
# and a favourite whose provider was removed should still be visible to
# un-favourite.

_MUSIC_ITEM_KEYS = ('uri', 'media_type', 'name', 'image', 'subtitle')
_MUSIC_RECENT_CAP = 30


def _music_item(item: dict) -> dict:
    return {k: item.get(k) for k in _MUSIC_ITEM_KEYS}


def get_music_favorites(member_id: str) -> list:
    with db_lock:
        rows = [dict(r) for r in
                music_favorites_table.search(Query().member_id == member_id)]
    rows.sort(key=lambda r: r.get('added_at', 0), reverse=True)
    return rows


def add_music_favorite(member_id: str, item: dict) -> dict:
    """Idempotent on (member, uri): a double-tapped heart is one favourite."""
    import time as _time
    with db_lock:
        q = Query()
        existing = music_favorites_table.search(
            (q.member_id == member_id) & (q.uri == item.get('uri')))
        if existing:
            return dict(existing[0])
        row = {'member_id': member_id, 'added_at': _time.time(),
               **_music_item(item)}
        music_favorites_table.insert(row)
        return row


def remove_music_favorite(member_id: str, uri: str) -> bool:
    with db_lock:
        q = Query()
        removed = music_favorites_table.remove(
            (q.member_id == member_id) & (q.uri == uri))
    return bool(removed)


def record_music_play(member_id: str, item: dict):
    """One row per (member, uri): replaying something moves it to the front
    rather than papering the shelf with duplicates. Capped per member —
    'recently' is a shelf, not a history."""
    import time as _time
    with db_lock:
        q = Query()
        music_recent_table.remove(
            (q.member_id == member_id) & (q.uri == item.get('uri')))
        music_recent_table.insert({'member_id': member_id,
                                   'played_at': _time.time(),
                                   **_music_item(item)})
        rows = music_recent_table.search(q.member_id == member_id)
        overflow = len(rows) - _MUSIC_RECENT_CAP
        if overflow > 0:
            rows.sort(key=lambda r: r.get('played_at', 0))
            music_recent_table.remove(
                doc_ids=[r.doc_id for r in rows[:overflow]])


def get_music_recent(member_id: str, limit: int = 12) -> list:
    with db_lock:
        rows = [dict(r) for r in
                music_recent_table.search(Query().member_id == member_id)]
    rows.sort(key=lambda r: r.get('played_at', 0), reverse=True)
    return rows[:limit]


# Runs last: the seed reads settings and dishes, both defined above. One-shot
# and stamped, so a family's edits to their own vocabulary are never undone.
ensure_dish_categories()
