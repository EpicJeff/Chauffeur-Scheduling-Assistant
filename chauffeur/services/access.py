"""Who may see a thread, mission or program, on every surface.

The project access rule (docs/superpowers/specs/2026-10-16-project-access-rule-design.md).
record_view = primitive base, then subject traversal, then the project layer.
The call graph is acyclic: primitive bases never call back into this module.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Optional

from services import storage

HOUSE = {'id': None, 'role': 'adult', 'house': True}
HOUSE_PARENT = {'id': None, 'role': 'parent', 'house': True}
FULL, KEEPER = 'full', 'keeper'
WRITE_ROLES = ('parent', 'adult')
SCOPED_ROLES = ('child', 'helper', 'guest')
NOT_A_CHANNEL = object()

_cache = ContextVar('access_cache', default=None)


@contextmanager
def batch():
    """Memoise project/member lookups and live origins for one read-only call.

    Explicit, not request-wide: a write route that changes a project and then
    reads it back must never see the old row."""
    if _cache.get() is not None:
        yield
        return
    token = _cache.set({})
    try:
        yield
    finally:
        _cache.reset(token)


def _memo(key, load):
    cache = _cache.get()
    if cache is None:
        return load()
    if key not in cache:
        cache[key] = load()
    return cache[key]


def _get_project(pid):
    return _memo(('project', pid), lambda: storage.get_project(pid)) if pid else None


def _get_member(mid):
    return _memo(('member', mid), lambda: storage.get_member(mid)) if mid else None


def thread_mission(row):
    """Newest live mission by origin, indexed once per read-only batch."""
    def index():
        from services import missions
        out = {}
        for mission in storage.get_missions(status=missions.LIVE):
            if mission.get('origin_kind') != 'thread':
                continue
            ref = mission.get('origin_ref')
            previous = out.get(ref)
            if previous is None or (mission.get('created_at') or 0) >= (previous.get('created_at') or 0):
                out[ref] = mission
        return out
    return _memo('live_missions_by_origin', index).get(row.get('id'))


def is_house(viewer):
    """A reader with no person: HOUSE, HOUSE_PARENT, or a legacy id-less sentinel
    such as agent_tools_v2._REGISTRY_READER (its role still decides adult/parent)."""
    return bool(viewer) and (bool(viewer.get('house')) or not viewer.get('id'))


def _active(member):
    from services import projects
    return projects._active(member)


def _person(viewer):
    """The viewer as an active member, or None (HOUSE is not a person)."""
    if not viewer or is_house(viewer) or not _active(viewer):
        return None
    return viewer


@dataclass(frozen=True)
class Kind:
    keeper_field: str
    base: Callable[[dict, dict], bool]
    load: Callable[[str], Optional[dict]]
    keeper_verbs: Optional[frozenset]   # None: a keeper may do everything (programs)


KINDS: dict = {}


def register(kind, keeper_field, base, load, keeper_verbs=None):
    KINDS[kind] = Kind(keeper_field, base, load, keeper_verbs)


def keeper_id(kind, row):
    spec = KINDS.get(kind)
    kid = (row or {}).get(spec.keeper_field) if spec else None
    if not kid:
        return None
    return kid if _active(_get_member(kid)) else None


def _is_keeper(kind, row, viewer):
    person = _person(viewer)
    kid = keeper_id(kind, row)
    return bool(person and kid and person['id'] == kid)


def _parent_of_child_keeper(kind, row, viewer):
    from services import projects
    person = _person(viewer)
    if not person or not projects._parent(person):
        return False
    keeper = _get_member(keeper_id(kind, row))
    return bool(keeper and projects._child(keeper))


def _thread_base(row, viewer):
    return viewer.get('role') in WRITE_ROLES or _is_keeper('thread', row, viewer)


def _mission_base(row, viewer):
    return viewer.get('role') in WRITE_ROLES


def _program_base(row, viewer):
    return viewer.get('role') not in SCOPED_ROLES or _is_keeper('program', row, viewer)


def home_project(row):
    return _get_project((row or {}).get('project_id'))


def restricted(project):
    return bool(project) and project.get('audience') != 'household'


def project_visible(project, viewer):
    """projects.can_see, with a meaning for HOUSE and HOUSE_PARENT (spec §2)."""
    from services import projects
    if not project or not viewer:
        return False
    if is_house(viewer):
        return project.get('audience') in (('household', 'parents', 'shared')
                                           if viewer.get('role') == 'parent' else ('household',))
    return projects.can_see(project, viewer)


def _subjects_full(kind, row, viewer, home, visited):
    from services import subjects
    for skind, record in subjects.subject_records(kind, row):
        if skind == 'project' and home and record.get('id') == home.get('id'):
            continue        # checked once, by the project layer (spec §3)
        if skind in KINDS:
            key = (skind, record.get('id'))
            # A thread or mission subject must be readable in full (its keeper
            # projection hides words the outer record may quote); a program's
            # keeper projection IS the whole program (spec §3).
            enough = (FULL, KEEPER) if skind == 'program' else (FULL,)
            if key in visited or record_view(skind, record, viewer, _visited=visited) not in enough:
                return False
        elif skind in ('project', 'proposed_project'):
            if not project_visible(record, viewer):
                return False
        elif not subjects.visible(skind, record, viewer):
            return False
    return True


def _child_private_list(home, kind, row):
    """A child's own private list decides who of the parents sees its records (audience spec §1)."""
    return bool(home and home.get('audience') == 'private'
                and home.get('owner_member_id') and home.get('owner_member_id') == keeper_id(kind, row))


def record_view(kind, row, viewer, *, skip_project=False, _visited=None):
    """'full', 'keeper' or None for one viewer (spec §3)."""
    spec = KINDS.get(kind)
    if spec is None or not row or not viewer:
        return None
    if not is_house(viewer) and _person(viewer) is None:
        return None
    if not spec.base(row, viewer):
        return None
    visited = set(_visited or ()) | {(kind, row.get('id'))}
    home = home_project(row)
    subjects_ok = _subjects_full(kind, row, viewer, home, visited)
    layer_ok = (skip_project or not restricted(home)
                or (_parent_of_child_keeper(kind, row, viewer) and not _child_private_list(home, kind, row))
                or project_visible(home, viewer))
    if subjects_ok and layer_ok:
        return FULL
    return KEEPER if _is_keeper(kind, row, viewer) else None


def record_visible(kind, row, viewer):
    return record_view(kind, row, viewer) is not None


def mission_reader(mission):
    """HOUSE or HOUSE_PARENT for the mission's existing subject audience."""
    from services import subjects

    def seen(kind, row, viewer):
        if kind in KINDS:
            return record_view(kind, row, viewer) == FULL
        if kind in ('project', 'proposed_project'):
            return project_visible(row, viewer)
        return subjects.visible(kind, row, viewer)

    records = subjects.subject_records('mission', mission or {})
    if records and all(not seen(k, r, HOUSE) and seen(k, r, HOUSE_PARENT) for k, r in records):
        return HOUSE_PARENT
    return HOUSE


def mission_view(mission, kind, row):
    """What a mission's own reads may see (spec §4.4)."""
    if not row:
        return None
    if (kind == 'thread' and mission.get('origin_kind') == 'thread'
            and row.get('id') == mission.get('origin_ref')):
        return FULL
    reader = mission_reader(mission)
    if mission.get('project_id') and row.get('project_id') == mission.get('project_id'):
        return record_view(kind, row, reader, skip_project=True)
    return record_view(kind, row, reader)


def channel_view(kind, row, focus_key):
    """The projection every human in a channel may receive (spec §4.3)."""
    from services import subjects, situations
    humans = subjects.channel_humans(focus_key)
    if humans is None:
        return NOT_A_CHANNEL
    if not restricted(home_project(row)):
        return FULL if situations._legacy_channel_visible(kind, row, humans) else None
    views = [record_view(kind, row, h) if h else None for h in humans]
    if not views or any(v is None for v in views):
        return None
    return KEEPER if KEEPER in views else FULL


def conversation_view(kind, row, viewer, focus_key):
    """What Argyle may show here: the channel's common projection, else the speaker's."""
    from services import subjects
    humans = subjects.channel_humans(focus_key)
    # A person's Argyle DM is their own surface. This exception belongs
    # here, not in channel_humans: another speaker still uses the audience's
    # common projection (controller ruling, 2026-10-16).
    if (humans is not None and len(humans) == 1 and humans[0]
            and (viewer or {}).get('id') == humans[0].get('id')):
        return record_view(kind, row, viewer)
    view = channel_view(kind, row, focus_key)
    return record_view(kind, row, viewer) if view is NOT_A_CHANNEL else view


def record_actable(kind, row, viewer, verb):
    view = record_view(kind, row, viewer)
    if view is None:
        return False
    if view == KEEPER:
        allowed = KINDS[kind].keeper_verbs
        return allowed is None or verb in allowed
    return True


def shared_screen_visible(kind, row, viewer):
    """HOUSE, plus what a signed-in person may see (spec §4.6)."""
    if record_visible(kind, row, HOUSE):
        return True
    return bool(_person(viewer)) and record_visible(kind, row, viewer)


def finding_visible(finding, viewer):
    """A finding derives its audience from its source record, now (spec §4.8)."""
    kind = finding.get('subject_type')
    if kind not in KINDS or not finding.get('subject_id'):
        return True
    row = KINDS[kind].load(finding['subject_id'])
    return row is None or record_visible(kind, row, viewer)


def neutral_signal_line(kind, row):
    """A keeper's signal names the record, never its next action or question."""
    title = row.get('title') or (row.get('goal') if kind == 'mission' else None) or kind
    return f'Argyle needs a parent on {title}'


def finding_view(finding, viewer, *, focus_key=NOT_A_CHANNEL):
    """Project source-derived words before a finding leaves a read surface."""
    kind = finding.get('subject_type')
    spec = KINDS.get(kind)
    row = spec.load(finding.get('subject_id')) if spec and finding.get('subject_id') else None
    if row is None:
        return finding
    projection = (record_view(kind, row, viewer) if focus_key is NOT_A_CHANNEL else
                  conversation_view(kind, row, viewer, focus_key))
    if projection is None:
        return None
    if projection != KEEPER or kind not in ('thread', 'mission'):
        return finding
    # Keep lifecycle metadata, but no cached note, proposal or free-text field.
    out = {k: finding[k] for k in ('id', 'identity', 'kind', 'severity', 'subject_type', 'subject_id',
           'state', 'created_at', 'last_seen_at', 'due_at', 'resolved_at', 'resolved_by',
           'snoozed_until', 'sit_owner_member_id', 'sit_owned_at', 'rev') if k in finding}
    out['line'] = neutral_signal_line(kind, row)
    return out


def private_recipients(kind, row):
    """Who a restricted record's DM-worthy signal goes to (access spec §4.8, audience spec §4)."""
    from services import projects
    home = home_project(row)
    keeper = keeper_id(kind, row)
    child_keeper = bool(keeper) and projects._child(_get_member(keeper) or {})
    members = [m for m in storage.get_all_members() if projects._active(m)]
    out = [keeper] if keeper else []
    audience = (home or {}).get('audience')
    if audience in ('parents', 'shared', 'private') and home.get('owner_member_id'):
        out.append(home['owner_member_id'])
    if child_keeper or audience in ('parents', 'shared'):
        out += [m['id'] for m in members if projects._parent(m)]
    if audience in ('shared', 'private'):
        out += list(home.get('shared_with') or [])
    by_id = {m['id']: m for m in members}
    return [mid for mid in dict.fromkeys(out)
            if mid in by_id and record_view(kind, row, by_id[mid]) is not None]


NEUTRAL_PRACTICE_KEYS = ('member_id', 'color', 'date', 'time_start', 'time_end')


def practice_hidden(program, viewer, *, shared=False):
    """Only a restricted home can hide calendar words (scope is not secrecy)."""
    visible = shared_screen_visible if shared else record_visible
    return bool(program and restricted(home_project(program))
                and not visible('program', program, viewer))


def neutral_practice(event):
    """The Busy copy of a practice event (spec §4.7): structure, no words."""
    import hashlib
    practice = event.get('practice') or {}
    return {'id': 'busy-' + hashlib.sha1(str(event.get('id')).encode()).hexdigest()[:12],
            'title': 'Busy', 'description': '', 'start': event.get('start'), 'end': event.get('end'),
            'all_day': event.get('all_day', False), 'event_type': 'practice',
            'calendar_ids': event.get('calendar_ids') or [],
            'practice': {k: practice.get(k) for k in NEUTRAL_PRACTICE_KEYS}}


def schedule_view(blob, viewer):
    """Apply the current audience to a schedule blob, row by row, at read time."""
    import copy
    if not blob:
        return blob
    out = copy.copy(blob)
    with batch():
        programs = {}
        def visible(pid):
            if pid not in programs:
                row = storage.get_program(pid)
                programs[pid] = not practice_hidden(row, HOUSE if is_house(viewer) else viewer)
            return programs[pid]
        events = []
        for ev in blob.get('events') or []:
            pid = ((ev.get('practice') or {}).get('program_id')) if ev.get('event_type') == 'practice' else None
            events.append(ev if not pid or visible(pid) else neutral_practice(ev))
        out['events'] = events
    return out


def cached_schedule(viewer=HOUSE, *, blob=None):
    """One consumption boundary for stored schedules and caller-supplied blobs."""
    return schedule_view(storage.get_cached_schedule() if blob is None else blob, viewer) or {}


def event_view(event, viewer=HOUSE):
    """Apply the same rule when a reader already resolved an event by id."""
    return schedule_view({'events': [event]}, viewer)['events'][0] if event else event


def commitment_view(row, viewer=HOUSE, *, programs=None):
    """An emitted reservation follows its program's current audience."""
    source = (row or {}).get('source') or {}
    programs = {} if programs is None else programs
    program = None
    if source.get('kind') == 'program':
        pid = source.get('id')
        if pid not in programs:
            programs[pid] = storage.get_program(pid)
        program = programs[pid]
    if program is None:
        # Legacy emissions can precede the provenance backfill. An orphaned
        # source has no authority; only a surviving emitter can restrict it.
        def emitters():
            out = {}
            for program in storage.get_programs(include_finished=True):
                for cid in (program.get('emissions') or {}).get('commitment_ids') or []:
                    out.setdefault(cid, program)
            return out
        program = _memo('commitment_emitters', emitters).get((row or {}).get('id'))
    if program and not record_visible('program', program, viewer):
        return {k: v for k, v in dict(row, title='Busy').items() if k != 'source'}
    return row


def shared_schedule_view(blob, viewer=HOUSE):
    """Shared-screen practice words, checked against the current program.

    Task 9 owns the general calendar view. These readers use the shared
    screen union (§4.6), including a signed-in child's household practices.
    """
    out = dict(blob or {})
    with batch():
        visible = {}
        events = []
        neutral_ids = set()
        for event in out.get('events') or []:
            pid = (event.get('practice') or {}).get('program_id')
            if pid:
                if pid not in visible:
                    row = storage.get_program(pid)
                    visible[pid] = not practice_hidden(row, viewer, shared=True)
                event = event if visible[pid] else neutral_practice(event)
            if event.get('event_type') == 'practice' and not (event.get('practice') or {}).get('program_id'):
                # Per-day cache merges may contain both an earlier neutral
                # copy and the original event. They represent the same time.
                if event.get('id') in neutral_ids:
                    continue
                neutral_ids.add(event.get('id'))
            events.append(event)
        out['events'] = events
    return out


register('thread', 'owner_member_id', _thread_base, lambda rid: storage.get_thread(rid),
         keeper_verbs=None)   # a thread keeper keeps every thread verb; view() drops mission options
register('mission', 'created_by', _mission_base, lambda rid: storage.get_mission(rid),
         keeper_verbs=frozenset({'ack', 'delete', 'steer', 'drop', 'own'}))
register('program', 'member_id', _program_base, lambda rid: storage.get_program(rid),
         keeper_verbs=None)
