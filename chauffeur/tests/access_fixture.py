"""One fixture household for every access test (project access rule spec §6).

Import from chauffeur/tests. Builds fresh storage each call; never real data.
"""
from dataclasses import dataclass, field

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

    def secret(self, rkey):
        return f'SECRET-{rkey}-WORDS'

    def title(self, rkey):
        return f'Title {rkey}'


def _project(audience, owner, title):
    return projects.create({'title': title, 'goal': 'g', 'done_when': 'd',
                            'owner_member_id': owner, 'audience': audience}, dict(MOM))['project']


def _thread(fx, rkey, owner, project, **extra):
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


def _program(fx, rkey, member, project, **extra):
    pid = storage.add_program({'title': fx.title(rkey), 'member_id': member, 'state': 'active',
                               'starting_point': fx.secret(rkey), **extra})
    projects.adopt('program', pid, None, project_id=project['id'] if project else None)
    fx.ids[rkey] = pid
    return pid


def build():
    """R1–R13 of spec §6. Returns Fx; storage is fresh."""
    _fresh_projects()
    for m in (HAL, PAT, SIB):
        storage.add_member(dict(m))
    fx = Fx()
    mom_private = _project('private', 'mom', 'Mom private')
    mom_parents = _project('parents', 'mom', 'Mom parents')
    household = _project('household', 'dad', 'Household')
    kate_private = _project('private', 'kid', 'Kate private')
    fx.projects.update(mom_private=mom_private, mom_parents=mom_parents, household=household,
                       kate_private=kate_private)

    _thread(fx, 'R1', 'aunt', mom_private)
    _mission(fx, 'R2', 'aunt', mom_private)
    _program(fx, 'R3', 'kid', mom_private)
    _thread(fx, 'R4', 'mom', mom_parents)
    _thread(fx, 'R5t', 'dad', household)
    _program(fx, 'R5p', 'kid', household)

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

    fx.viewers = {'mom': dict(MOM), 'dad': dict(DAD), 'aunt': dict(AUNT), 'kid': dict(KID),
                  'hal': dict(HAL), 'pat': dict(PAT), 'sib': dict(SIB)}
    from services import access
    fx.viewers['house'] = access.HOUSE
    return fx
