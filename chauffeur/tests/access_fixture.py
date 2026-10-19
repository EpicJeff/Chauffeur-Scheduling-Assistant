"""One fixture household for every access test (project access rule spec §6).

Import from chauffeur/tests. Builds fresh storage each call; never real data.
"""
from dataclasses import dataclass, field

import uuid

from test_front_door_chat import _fresh as _fresh_projects
from test_subjects import MOM, DAD, AUNT, KID
from services import storage, projects, threads

HAL = {'id': 'hal', 'name': 'Hal', 'role': 'helper'}
PAT = {'id': 'pat', 'name': 'Pat', 'role': 'parent', 'status': 'disabled'}
SIB = {'id': 'sib', 'name': 'Sam', 'role': 'child', 'is_child': True}


@dataclass
class Fx:
    ids: dict = field(default_factory=dict)
    projects: dict = field(default_factory=dict)
    viewers: dict = field(default_factory=dict)
    # Program library spec 2026-10-19 §1: the library row each fixture run is bound to, by rkey.
    # Empty until storage has the library helpers (the fixture must keep running without them).
    library: dict = field(default_factory=dict)

    def secret(self, rkey):
        return f'SECRET-{rkey}-WORDS'

    def title(self, rkey):
        return f'Title {rkey}'


def _project(audience, owner, title):
    return projects.create({'title': title, 'goal': 'g', 'done_when': 'd',
                            'owner_member_id': owner, 'audience': audience}, dict(MOM))['project']


def _listed_project(title, owner, audience, shared_with, actor):
    res = projects.create({'title': title, 'goal': 'g', 'done_when': 'd', 'owner_member_id': owner,
                           'audience': audience, 'shared_with': shared_with}, dict(actor))
    assert res['status'] == 'success', f'the fixture needs a {audience} project with a list: {res}'
    return res['project']


def _thread(fx, rkey, owner, project, **extra):
    if project is None and extra.get('subject_kind'):
        # A wrapper is born with the audience derived from its record AS IT STANDS (project
        # audiences spec §3), so a record that carries a private subject must carry it at
        # adoption. threads.create takes no subject: store the thread whole, then adopt it.
        creator = owner or 'mom'
        tid = storage.add_thread({'title': fx.title(rkey), 'goal': '', 'kind': 'project', 'owner_member_id': owner,
                                  'created_by': creator, 'next_action': fx.secret(rkey),
                                  'next_action_at': '2020-01-01', **extra})
        storage.append_thread_history(tid, {'kind': 'opened', 'text': f'Opened: {fx.title(rkey)}', 'who': creator})
        projects.adopt('thread', tid, storage.get_member(creator))
    else:
        tid = threads.create(title=fx.title(rkey), owner_member_id=owner, created_by=owner or 'mom',
                             project_id=project['id'] if project else None,
                             next_action=fx.secret(rkey), next_action_at='2020-01-01')
        if extra:
            storage.update_thread(tid, extra)
    storage.update_thread(tid, {'status_note': fx.secret(rkey), 'note_source': 'model'})
    fx.ids[rkey] = tid
    return tid


def _mission(fx, rkey, creator, project, **extra):
    mid = storage.add_mission({'goal': fx.title(rkey), 'created_by': creator, 'status': 'waiting_user',
                              'summary': fx.secret(rkey), 'status_note': fx.secret(rkey), **extra})
    storage.add_mission_step(mid, {'kind': 'ask', 'result_json': {'question': fx.secret(rkey) + '?'}})
    projects.adopt('mission', mid, None, project_id=project['id'] if project else None)
    fx.ids[rkey] = mid
    return mid


def library_ready():
    """Whether the program library (spec 2026-10-19) is in storage yet. Until it is, the fixture
    builds exactly the household it always built, so every existing cell runs unchanged."""
    return hasattr(storage, 'add_library_program')


def _clear_library():
    table = getattr(storage, 'library_programs_table', None)
    if table is not None:
        table.truncate()
        return
    for row in storage.get_library_programs() or []:
        storage.delete_library_program(row['id'])


def _library_row(fx, rkey):
    """One library row per fixture run, titled as the run so each record's title still names
    exactly one record once the title moves to the library (spec §1). Aunt made it: an adult
    creator who is not a parent, so the matrix can tell creator rights from parent rights."""
    phase = uuid.uuid4().hex
    lid = storage.add_library_program({
        'title': fx.title(rkey), 'created_by': 'aunt', 'archived': False,
        'made_for': {'age_band': 'any', 'minutes': 25, 'sessions_per_week': 3, 'assumes': ''},
        'source': {'origin': 'none', 'plan_name': '', 'url': '', 'facts': [], 'reason': 'fixture'},
        'phases': [{'id': phase, 'name': 'phase', 'weeks': 2, 'what': '', 'milestone': 'Done with it',
                    'steps': [], 'progression': '', 'rotation': []}],
        'lessons': [{'id': uuid.uuid4().hex, 'phase_id': phase, 'title': 'One', 'sessions': 1, 'steps': []},
                    {'id': uuid.uuid4().hex, 'phase_id': phase, 'title': 'Two', 'sessions': 1, 'steps': []}]})
    fx.library[rkey] = lid
    return lid


def _program(fx, rkey, member, project, **extra):
    if library_ready():
        lid = _library_row(fx, rkey)
        first = storage.get_library_program(lid)['lessons'][0]['id']
        extra = {'library_id': lid, 'progress': {'lessons': {}, 'current': first, 'phases': {}}, **extra}
    pid = storage.add_program({'title': fx.title(rkey), 'member_id': member, 'state': 'active',
                               'starting_point': fx.secret(rkey), **extra})
    projects.adopt('program', pid, None, project_id=project['id'] if project else None)
    fx.ids[rkey] = pid
    return pid


def build():
    """R1–R13 of spec §6, then R14–R17 of the project audience spec. Returns Fx; storage is fresh."""
    _fresh_projects()
    if library_ready():
        _clear_library()
    for m in (HAL, PAT, SIB):
        storage.add_member(dict(m))
    fx = Fx()
    mom_private = _project('private', 'mom', 'Mom private')
    mom_parents = _project('parents', 'mom', 'Mom parents')
    household = _project('household', 'dad', 'Household')
    kate_private = _project('private', 'kid', 'Kate private')
    fx.projects.update(mom_private=mom_private, mom_parents=mom_parents, household=household,
                       kate_private=kate_private)
    # Project audiences on the shared model (spec 2026-10-16): `shared` is the parents plus a
    # list; a child's explicit `private` list may leave a parent out. Both carry the list at
    # create, since a `shared` project with an empty list is stored as `parents`.
    mom_shared = _listed_project('Mom shared', 'mom', 'shared', ['aunt'], MOM)
    kate_no_dad = _listed_project('Kate no Dad', 'kid', 'private', ['kid', 'mom'], KID)
    mom_no_dad = _listed_project('Mom no Dad', 'mom', 'private', ['mom', 'kid'], MOM)
    fx.projects.update(mom_shared=mom_shared, kate_no_dad=kate_no_dad, mom_no_dad=mom_no_dad)

    _thread(fx, 'R1', 'aunt', mom_private)
    _mission(fx, 'R2', 'aunt', mom_private)
    _program(fx, 'R3', 'kid', mom_private)
    _thread(fx, 'R4', 'mom', mom_parents)
    _thread(fx, 'R5t', 'dad', household)
    _program(fx, 'R5p', 'kid', household)
    _program(fx, 'R5s', 'sib', household)  # sibling scope is not calendar secrecy

    storage.save_occasion({'id': 'occ-kate-mom', 'title': 'Dad surprise', 'audience': 'private',
                           'shared_with': ['mom', 'kid']})
    _thread(fx, 'R6', 'kid', None, subject_kind='occasion', subject_id='occ-kate-mom')
    _thread(fx, 'R7', 'kid', mom_private, subject_kind='occasion', subject_id='occ-kate-mom')
    storage.save_occasion({'id': 'occ-parents', 'title': 'Parents only', 'audience': 'parents'})
    _thread(fx, 'R8', '', None, subject_kind='occasion', subject_id='occ-parents')

    origin = _thread(fx, 'R9origin', 'mom', mom_private)
    _mission(fx, 'R9a', 'mom', mom_private, origin_kind='thread', origin_ref=origin)
    _mission(fx, 'R9b', 'mom', household)

    _thread(fx, 'R10', 'dad', household, subject_kind='thread', subject_id=fx.ids['R1'])
    _mission(fx, 'R11', 'mom', kate_private, subject_kind='project', subject_id=kate_private['id'])

    with storage.db_lock:
        storage.trip_metadata_table.insert({'id': 'tp', 'event_id': 'ev_parents_trip', 'title': 'Parents trip',
                                            'audience': 'parents', 'pois': [], 'accommodations': [],
                                            'flights': []})
    storage.set_cached_trips([{'id': 'ev_parents_trip', 'title': 'Parents trip', 'start': '2027-01-01',
                               'end': '2027-01-03', 'location': 'X'}])
    _thread(fx, 'R12', 'mom', household,
            subject_history=[{'kind': 'trip', 'id': 'ev_parents_trip'}])
    _thread(fx, 'R13', 'dad', None)   # threads.create wraps it (slice 1 invariant)
    _thread(fx, 'R14', 'kid', kate_no_dad)        # a child's private list leaves Dad out
    _program(fx, 'R15', 'kid', kate_no_dad)       # ... and so does the child's own program
    _thread(fx, 'R16', 'mom', mom_shared)         # parents plus Aunt; the child and the helper are out
    _program(fx, 'R17', 'kid', mom_no_dad)       # Mom's list also leaves Dad out of Kate's program

    fx.viewers = {'mom': dict(MOM), 'dad': dict(DAD), 'aunt': dict(AUNT), 'kid': dict(KID),
                  'hal': dict(HAL), 'pat': dict(PAT), 'sib': dict(SIB)}
    from services import access
    fx.viewers['house'] = access.HOUSE
    return fx


# --- Program library routes (spec 2026-10-19 §2, §4): expectations and matrix probes ----------
# Rows for routes that do not exist yet: the matrix only runs a probe for a READERS row, so
# these stay inert until the library routes and their READERS rows land (Task 2), and then
# every one of them must match. The library is public curriculum: every active member reads it.
# What is restricted is the RUNNER beside it (named only when the viewer sees the run's
# project) and the run's private starting point (never on a library surface at all).
EDIT_REFUSAL = "Only the person who made this program, or a parent, can change it."
IN_USE_ANOTHER = "In use by another project"
LIBRARY_ROUTES = {
    ('route', 'GET', '/api/library'): 'read',
    ('route', 'POST', '/api/library'): 'create',
    ('route', 'GET', '/api/library/{id}'): 'read',
    ('route', 'PATCH', '/api/library/{id}'): 'edit',
    ('route', 'DELETE', '/api/library/{id}'): 'delete',
    ('route', 'POST', '/api/library/{id}/archive'): 'edit',
    ('route', 'POST', '/api/library/{id}/lessons'): 'edit',
    ('route', 'PATCH', '/api/library/{id}/lessons/{lesson_id}'): 'edit',
    ('route', 'DELETE', '/api/library/{id}/lessons/{lesson_id}'): 'edit',
    ('route', 'POST', '/api/library/{id}/lessons/order'): 'edit',
}
# Whose run each fixture library row carries (the in-use refusal names the runner).
RUNNER_NAME = {'R3': 'Kate', 'R5p': 'Kate', 'R5s': 'Sam', 'R15': 'Kate', 'R17': 'Kate'}


def runner_visible(rkey, col):
    """A runner is named to a viewer who sees that run's PROJECT (spec §2); fixture knowledge only."""
    from access_signed_in import project_visible
    return project_visible(None, rkey, col)


def library_expected(rid, fx, rkey, col, value):
    """The matrix's expectation for a library route cell; any other reader keeps `value`."""
    what = LIBRARY_ROUTES.get(rid)
    if what is None:
        return value
    if col == 'house':
        return 'skip'                     # signed-in routes: the house is refused at the door
    if col == 'pat':
        return None                       # a disabled member reaches nothing
    if what == 'read':
        return 'curriculum+runner' if runner_visible(rkey, col) else 'curriculum'
    if col in ('kid', 'hal'):
        return 'FORBIDDEN-NOT-404'        # a child never creates or edits; a helper is not an adult
    if what == 'delete':                  # every fixture row has a run: refused, never deleted
        return 'IN-USE-NAMED' if runner_visible(rkey, col) else 'IN-USE-ANOTHER'
    return 'full'                         # Aunt made the row; Mom and Dad are parents


def _library_entry(data, lid):
    """The one library row with this id inside a response, wherever the route nests it."""
    if isinstance(data, dict):
        if data.get('id') == lid:
            return data
        data = list(data.values())
    if isinstance(data, list):
        for item in data:
            found = _library_entry(item, lid)
            if found is not None:
                return found
    return None


def library_read_probe(rid, fx, rkey, col):
    import json
    from access_signed_in import request
    if col == 'house':
        return 'skip'
    lid = fx.library[rkey]
    r = request(fx, col, 'GET', rid[-1].replace('{id}', lid))
    if r is None or r.status_code in (401, 404):
        return None
    if r.status_code == 403:
        return 'FORBIDDEN-NOT-404'
    if not 200 <= r.status_code < 300:
        return f'HTTP {r.status_code}: {r.text[:140]}'
    if fx.secret(rkey) in r.text:
        return 'LEAK: the run starting point reached a library payload'
    entry = _library_entry(r.json(), lid)
    if entry is None or entry.get('title') != fx.title(rkey):
        return 'NO-CURRICULUM'
    project_id = storage.get_program(fx.ids[rkey])['project_id']
    # One program's page may carry its runners beside the row; the list must carry them in it.
    scope = r.json() if rid[-1] == '/api/library/{id}' else entry
    return 'curriculum+runner' if project_id in json.dumps(scope) else 'curriculum'


def library_write_probe(rid, fx, rkey, col):
    from unittest.mock import patch
    from access_signed_in import request
    if col == 'house':
        return 'skip'
    fx = build()                          # every write starts with a fresh household
    lid = fx.library[rkey]
    row = storage.get_library_program(lid)
    method, path = rid[1], rid[-1].replace('{id}', lid)
    path = path.replace('{lesson_id}', row['lessons'][0]['id'])
    body = {}
    if rid[-1] == '/api/library':
        body = {'title': 'Learn the recorder', 'age_band': 'any', 'minutes': 15, 'sessions_per_week': 2,
                'assumes': 'complete beginner'}
    elif method == 'PATCH' and path.endswith(lid):
        body = {'title': f'Edited by {col}'}
    elif path.endswith('/lessons'):
        body = {'phase_id': row['phases'][0]['id'], 'title': 'Three', 'sessions': 1, 'steps': []}
    elif method == 'PATCH':
        body = {'title': f'Lesson edited by {col}'}
    elif path.endswith('/order'):
        body = {'ids': [lesson['id'] for lesson in reversed(row['lessons'])]}
    with patch('services.programs_curate.curate', return_value={'phases': [], 'source': {'origin': 'none'}}):
        r = request(fx, col, method, path, json=body)
    if r is None or r.status_code in (401, 404):
        return None
    after = storage.get_library_program(lid)
    if 'In use by' in r.text:
        if after is None:
            return 'REFUSED-BUT-DELETED'
        if IN_USE_ANOTHER in r.text:
            return 'IN-USE-ANOTHER'
        named = "In use by " + RUNNER_NAME[rkey] + "'s project"
        return 'IN-USE-NAMED' if named in r.text else f'IN-USE-WORDS: {r.text[:140]}'
    if r.status_code == 403:
        if rid[-1] != '/api/library' and EDIT_REFUSAL not in r.text:
            return f'FORBIDDEN-WRONG-WORDS: {r.text[:140]}'
        if rid[-1] != '/api/library' and after != row:
            return 'REFUSED-BUT-CHANGED'
        return 'FORBIDDEN-NOT-404'
    if not 200 <= r.status_code < 300:
        return f'HTTP {r.status_code}: {r.text[:140]}'
    if r.json().get('status') in ('error', 'refused', 'not_found'):
        return f'ACTION-NOT-ACCEPTED: {r.text[:160]}'
    if method == 'PATCH' and path.endswith(lid) and (after or {}).get('title') != f'Edited by {col}':
        return 'ACCEPTED-BUT-NOT-STORED'
    return 'full'


def register_library(probe):
    """Attach the library probes to the matrix (tests/test_access_matrix.py)."""
    for rid, what in LIBRARY_ROUTES.items():
        fn = library_read_probe if what == 'read' else library_write_probe

        def run(fx, rkey, col, rid=rid, fn=fn):
            return fn(rid, fx if fn is library_write_probe else build(), rkey, col)
        probe(rid)(run)
