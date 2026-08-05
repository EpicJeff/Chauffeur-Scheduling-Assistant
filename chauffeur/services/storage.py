from tinydb import TinyDB, Query
from typing import List, Optional
import os
import json
import threading

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
    return None


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
    themes_table = db.table('themes')
    ai_feedback_table = db.table('ai_feedback')
    overrides_table = db.table('overrides')
    cache_table = db.table('schedule_cache')
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
    chores_table = db.table('chores')
    points_ledger_table = db.table('points_ledger')
    routines_table = db.table('routines')
    routine_checks_table = db.table('routine_checks')
    kid_tasks_table = db.table('kid_tasks')
    rewards_table = db.table('rewards')
    redemptions_table = db.table('redemptions')
    pool_contributions_table = db.table('pool_contributions')
    ics_feeds_table = db.table('ics_feeds')
    event_proposals_table = db.table('event_proposals')
    agent_action_proposals_table = db.table('agent_action_proposals')
    ingest_log_table = db.table('ingest_log')
    prep_kits_table = db.table('prep_kits')
    prep_status_table = db.table('prep_status')
    daily_stats_table = db.table('daily_stats')
    cars_table = db.table('cars')
    status_protocols_table = db.table('status_protocols')
    status_days_table = db.table('status_days')

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
                    bio=d.get('bio') or '',
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
                new_member(name or p_id, is_child=True, passenger_id=p_id,
                           bio=p.get('bio') or '')
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
        return doc_id

def update_driver_fields(driver_id: str, updates: dict) -> bool:
    """Partial update of a driver record by its string id (not doc_id).
    For cosmetic fields only (e.g. color_code synced from the member's
    identity color) — deliberately does NOT invalidate schedule caches,
    since nothing the solver reads changes."""
    with db_lock:
        return bool(drivers_table.update(updates, Query().id == driver_id))

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
def get_all_members() -> List[dict]:
    with db_lock:
        members = []
        for m in members_table.all():
            doc = dict(m)
            doc['doc_id'] = m.doc_id
            members.append(doc)
        return members

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
        if updates:
            members_table.update(updates, Query().id == keep_id)
        members_table.remove(Query().id == absorb_id)
        keep.update(updates)
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

def get_member_by_token(token: str) -> Optional[dict]:
    if not token:
        return None
    with db_lock:
        rows = member_tokens_table.search(Query().token == token)
    return get_member(rows[0]['member_id']) if rows else None

def delete_member_tokens(member_id: str):
    with db_lock:
        member_tokens_table.remove(Query().member_id == member_id)

# --- Chores + points ledger ---
# Marketplace model: chores sit in a family pot, members claim them, parents
# verify. Points ledger is append-only; balances are sums. Lifecycle
# maintenance (recurring reopen, stale-claim release) runs lazily on read.

CHORE_CLAIM_CAP = 3
CHORE_STALE_CLAIM_HOURS = 48

def _chore_reset_fields():
    return {'state': 'open', 'claimed_by': None, 'claimed_at': None,
            'done_at': None, 'verified_by': None, 'verified_at': None,
            'rejected_reason': None, 'reopens_on': None}

def _chore_maintenance():
    import time
    from datetime import date
    today = date.today().isoformat()
    now = time.time()
    with db_lock:
        for c in chores_table.all():
            if (c.get('state') == 'verified' and c.get('recurrence') != 'once'
                    and c.get('reopens_on') and c['reopens_on'] <= today):
                chores_table.update(_chore_reset_fields(), doc_ids=[c.doc_id])
            elif (c.get('state') == 'claimed' and c.get('claimed_at')
                    and now - c['claimed_at'] > CHORE_STALE_CLAIM_HOURS * 3600):
                # Claimed then ignored: release back to the pot.
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
    reopens_on date. Returns {'chore', 'awarded'} or None."""
    import time
    import uuid as _uuid
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
        return {'chore': chore, 'awarded': awarded}

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
    balances = []
    for m in get_all_members():
        if m.get('role') != 'child':
            continue
        balances.append({
            'member_id': m['id'], 'name': m.get('name'),
            'color_code': m.get('color_code'), 'avatar': m.get('avatar'),
            'image': m.get('image'),
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
    for r in items:
        r['checked'] = r['id'] in checked
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
        return True

def compute_streak(member_id: str, window_days: int = 90) -> dict:
    """{current, best, today_complete, today_total, today_done} over the
    window. current counts back from today (today included only once
    complete, otherwise from yesterday)."""
    from datetime import date, timedelta
    routines = get_routines(member_id)
    if not routines:
        return {'current': 0, 'best': 0, 'today_complete': False,
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

    best = run = 0
    for i in range(window_days, -1, -1):
        state = day_state(today - timedelta(days=i))
        if state == 'complete':
            run += 1
            best = max(best, run)
        elif state == 'incomplete':
            run = 0
    today_sched = {r['id'] for r in routines if _routine_scheduled_on(r, today)}
    today_done = len(today_sched & checks_by_day.get(today.isoformat(), set()))
    return {'current': current, 'best': best,
            'today_complete': bool(today_sched) and today_done == len(today_sched),
            'today_total': len(today_sched), 'today_done': today_done}

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

def decide_redemption(redemption_id: str, decider_member_id: str, approve: bool) -> Optional[dict]:
    """Approve deducts points via the ledger; deny just closes it."""
    import time
    import uuid as _uuid
    with db_lock:
        rows = redemptions_table.search(Query().id == redemption_id)
        if not rows or rows[0].get('state') != 'pending':
            return None
        red = dict(rows[0])
        updates = {'state': 'approved' if approve else 'denied',
                   'decided_by': decider_member_id, 'decided_at': time.time()}
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
    members = {m['id']: m for m in get_all_members()}
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

def get_channels_for_member(member_id: str) -> List[dict]:
    """Family channel + this member's DMs/groups + non-archived event threads.
    Helpers (external drivers/nannies) see only their DMs — no family channel,
    groups, or event threads. Event threads whose event ended >7 days ago are
    archived on the way out."""
    from datetime import datetime, timedelta, timezone
    member = get_member(member_id)
    is_helper = bool(member) and member.get('role') == 'helper'
    with db_lock:
        out = []
        for c in chat_channels_table.all():
            c = dict(c)
            if is_helper and c.get('kind') != 'dm':
                continue
            if c.get('kind') in ('dm', 'group') and member_id not in (c.get('member_ids') or []):
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
    """Background: normalize {stem}.orig to H.264 720p mp4 at {stem}.mp4 —
    phones record HEVC .mov that Chrome-based wall panels cannot decode, and
    a raw 4K clip is ~10x the size it needs to be. Atomic swap onto the SAME
    media id the attachment already references; until it lands, the serving
    endpoint falls back to the original bytes. On any failure the original
    is renamed into place (store-as-is — never lose the moment)."""
    import subprocess
    orig = media_read_path(stem + '.orig') or media_write_path(stem + '.orig')
    final = media_write_path(stem + '.mp4')
    # ffmpeg encodes to LOCAL scratch, never straight onto the media root —
    # a multi-minute write onto a network mount is slow and fails badly.
    tmp = os.path.join(media_scratch_dir(), stem + '.tmp.mp4')
    try:
        subprocess.run(
            [_ffmpeg_path(), '-y', '-i', orig,
             '-vf', "scale='min(1280,iw)':-2",
             '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '26',
             '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', tmp],
            check=True, capture_output=True, timeout=600)
        media_move_into_place(tmp, final)
        os.remove(orig)
        generate_poster(stem)   # thumbnail, so tiles never show a black box
        print(f"[media] transcoded {stem}.mp4")
    except Exception as e:
        print(f"[media] transcode failed for {stem} (storing as-is): {e}")
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
        media_move_into_place(src_path, media_write_path(stem + '.orig'))
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


def _delete_media_for_messages(msgs):
    """Best-effort file cleanup when messages roll off the retention cap —
    a pruned moment must not orphan its clip (or a pending transcode's
    working files) on disk."""
    for m in msgs:
        att = (m.get('attachment') or {}) if isinstance(m, dict) else {}
        url = str(att.get('url') or '')
        if url.startswith('/api/media/'):
            media_id = url.rsplit('/', 1)[-1]
            stem = media_id.split('.')[0]
            if not (len(stem) == 32 and all(c in '0123456789abcdef' for c in stem)):
                continue
            for name in (media_id, stem + '.orig', stem + '.tmp.mp4', stem + '.jpg'):
                # Wherever it actually is — sharded or flat, new root or the
                # legacy one a half-finished migration left it in.
                p = media_read_path(name)
                if not p:
                    continue
                try:
                    os.remove(p)
                except OSError:
                    pass


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
                    'count': 0, 'latest_ts': 0.0, 'cover': None,
                    'sender_ids': set(),
                }
            b['count'] += 1
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

# Themes CRUD
def get_all_themes() -> List[dict]:
    with db_lock:
        themes = []
        for t in themes_table.all():
            doc = dict(t)
            doc['doc_id'] = t.doc_id
            themes.append(doc)
        return themes

def add_theme(theme_data: dict) -> int:
    with db_lock:
        return themes_table.insert(theme_data)

def delete_theme(doc_id: int):
    with db_lock:
        themes_table.remove(doc_ids=[doc_id])

def update_theme(doc_id: int, theme_data: dict):
    with db_lock:
        themes_table.update(theme_data, doc_ids=[doc_id])

# AI Feedback
def get_recent_ai_feedback(limit: int = 20) -> List[dict]:
    with db_lock:
        feedback = ai_feedback_table.all()
        feedback.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return feedback[:limit]

def add_ai_feedback(context: str):
    import time
    with db_lock:
        ai_feedback_table.insert({'timestamp': time.time(), 'context': context})

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

def save_cached_daily_schedule(date_str: str, schedule_data: dict, events_hash: str, options: list = None, ai_status: str = 'evaluating', selected_index: int = 0, llm_reasoning: str = ""):
    with db_lock:
        existing = daily_schedules_table.get(Query().date_str == date_str)
        
        # If we are only updating options/ai_status, keep existing options if not provided
        if existing and existing.get('events_hash') == events_hash:
            if options is None:
                options = existing.get('options', [])
            if not llm_reasoning and ai_status == 'evaluating':
                ai_status = existing.get('ai_status', 'evaluating')
                selected_index = existing.get('selected_index', 0)
                llm_reasoning = existing.get('llm_reasoning', '')
                
        daily_schedules_table.upsert({
            'date_str': date_str,
            'schedule': schedule_data,
            'events_hash': events_hash,
            'options': options or [],
            'ai_status': ai_status,
            'selected_index': selected_index,
            'llm_reasoning': llm_reasoning
        }, Query().date_str == date_str)
        
        # Invalidate any custom range caches that might have relied on old daily data
        custom_schedules_table.truncate()


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
def mark_drive_status(leg_id: str, status: str):
    with db_lock:
        q = Query()
        drive_status_table.upsert({'leg_id': leg_id, 'status': status}, q.leg_id == leg_id)

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

def get_completed_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'completed')]

def get_in_progress_drives():
    with db_lock:
        return [doc['leg_id'] for doc in drive_status_table.search(Query().status == 'in_progress')]

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
