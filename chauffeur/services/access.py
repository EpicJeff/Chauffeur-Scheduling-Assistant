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
    """Memoise project and member lookups for one read-only list call.

    Explicit, not request-wide: a write route that changes a project and then
    reads it back must never see the old row."""
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
    return bool(project) and not project.get('wrapped_from') and project.get('audience') in ('private', 'parents')


def project_visible(project, viewer):
    """projects.can_see, with a meaning for HOUSE and HOUSE_PARENT (spec §2)."""
    from services import projects
    if not project or not viewer:
        return False
    if is_house(viewer):
        if project.get('wrapped_from'):
            return projects._wrapped_visible(project, viewer)
        return project.get('audience') == 'household'
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
                or _parent_of_child_keeper(kind, row, viewer)
                or project_visible(home, viewer))
    if subjects_ok and layer_ok:
        return FULL
    return KEEPER if _is_keeper(kind, row, viewer) else None


def record_visible(kind, row, viewer):
    return record_view(kind, row, viewer) is not None


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


register('thread', 'owner_member_id', _thread_base, lambda rid: storage.get_thread(rid),
         keeper_verbs=None)   # a thread keeper keeps every thread verb; view() drops mission options
register('mission', 'created_by', _mission_base, lambda rid: storage.get_mission(rid),
         keeper_verbs=frozenset({'ack', 'delete', 'steer'}))
register('program', 'member_id', _program_base, lambda rid: storage.get_program(rid),
         keeper_verbs=None)
