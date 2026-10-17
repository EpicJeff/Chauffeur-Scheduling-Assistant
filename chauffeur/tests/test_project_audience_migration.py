"""The project audience migration and live wrapper derivation (spec 2026-10-16, section 3, rev 3).

Existing wrappers are test data, so there is no legacy snapshot: every wrapper, old or new, gets its
audience from one rule, project_audience.derive_for_record(kind, row, owner_id) judged by secrecy
(not role). A row converted once is stamped audience_rev 2 and never touched again.

Run from chauffeur/:  python tests/test_project_audience_migration.py
"""
from harness import check  # noqa: F401
from services import storage, access
from test_projects import _fresh, _p
from test_subjects import MOM, DAD, AUNT, KID


def _legacy(owner, audience, title='Legacy', **extra):
    """A row exactly as the old code stored it (no audience_rev, no shared_with)."""
    return storage.add_project({'title': title, 'goal': 'g', 'done_when': 'd', 'owner_member_id': owner,
                                'audience': audience, 'state': 'active', 'steps': [], 'pieces': [],
                                'created_by': owner, 'body_goal': False, **extra})


def _seen(pid, members=(MOM, DAD, AUNT, KID)):
    row = storage.get_project(pid)
    return {m['id'] for m in members if _p().can_see(row, dict(m))}


def _convert():
    from services import project_audience
    return project_audience.convert_all()


def _wrapped_thread(owner, **thread_fields):
    """A thread and its wrapper project. threads.create takes no subject, so a thread that must
    carry one AT adoption is stored first and adopted second, as adopt sees it."""
    from services import threads, projects
    if not thread_fields:
        tid = threads.create(title='Wrapped', owner_member_id=owner, created_by=owner or 'mom')
    else:
        creator = owner or 'mom'
        tid = storage.add_thread({'title': 'Wrapped', 'goal': '', 'kind': 'project', 'state': 'open',
                                  'owner_member_id': owner, 'created_by': creator, **thread_fields})
        projects.adopt('thread', tid, storage.get_member(creator))
    return tid, storage.get_thread(tid)['project_id']


def _reset(pid, **extra):
    """Put a wrapper back to a not-yet-converted row (no rev, no list); it converts with the live rule."""
    storage.update_project(pid, {'audience': 'parents', 'shared_with': None, 'audience_rev': None, **extra})


def scenario_plain_rows():
    _fresh()
    hh, par = _legacy('mom', 'household'), _legacy('mom', 'parents')
    adult, child = _legacy('mom', 'private'), _legacy('kid', 'private')
    body = _legacy('mom', 'private', title='Reach 70 kg', body_goal=True)
    _convert()
    check(storage.get_project(hh)['audience'] == 'household' and storage.get_project(par)['audience'] == 'parents', "unchanged")
    check(not storage.get_project(hh)['shared_with'] and not storage.get_project(par)['shared_with'], "no list on household or parents")
    check(storage.get_project(adult)['shared_with'] == ['mom'], "adult private: the owner")
    check(set(storage.get_project(child)['shared_with']) == {'kid', 'mom', 'dad'}, "child private: the child and the parents")
    check(storage.get_project(body)['shared_with'] == ['mom'], "body goal first")
    check(all(storage.get_project(p).get('audience_rev') == 2 for p in (hh, par, adult, child, body)), "every row stamped")


def scenario_open_record_wrapper_is_household():
    """Dad's plain thread: the house and every adult read it, so its wrapper is household."""
    _fresh()
    tid, pid = _wrapped_thread('dad')
    _reset(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['audience'] == 'household' and not row['shared_with'], f"secrecy, not role, decides: {row}")
    check(_seen(pid) == {'mom', 'dad', 'aunt', 'kid'}, f"everyone sees the project name: {_seen(pid)}")
    check(access.project_visible(row, access.HOUSE), "the house reads it too")
    from services import situations
    check(not situations.can_see('thread', storage.get_thread(tid), dict(KID)), "a child still cannot open the thread (piece rule)")


def scenario_parents_only_record_wrapper_is_parents():
    _fresh()
    storage.save_occasion({'id': 'occ-pa', 'title': 'Parents only', 'audience': 'parents'})
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-pa')
    _reset(pid, audience='household')
    _convert()
    row = storage.get_project(pid)
    check(row['audience'] == 'parents', f"a secret record never qualifies for household: {row}")
    check(_seen(pid) == {'mom', 'dad'} and not access.project_visible(row, access.HOUSE), f"parents only: {_seen(pid)}")
    check(access.project_visible(row, access.HOUSE_PARENT), "the engine acting for the parent of record still reads it")


def scenario_record_open_to_parents_and_a_listed_adult_is_shared():
    _fresh()
    storage.save_occasion({'id': 'occ-sh', 'title': 'Party', 'audience': 'shared', 'shared_with': ['aunt']})
    tid, pid = _wrapped_thread('mom', subject_kind='occasion', subject_id='occ-sh')
    _reset(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['audience'] == 'shared' and row['shared_with'] == ['aunt'], f"parents plus the others: {row}")
    check(_seen(pid) == {'mom', 'dad', 'aunt'}, f"{_seen(pid)}")


def scenario_childs_program_wrapper():
    _fresh()
    from services import projects
    prog = storage.add_program({'title': 'Guitar', 'member_id': 'kid', 'state': 'active'})
    projects.adopt('program', prog, None)
    pid = storage.get_program(prog)['project_id']
    _reset(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['owner_member_id'] == 'kid' and row['audience'] == 'household', f"Kate keeps her program's project: {row}")
    check(_seen(pid) == {'mom', 'dad', 'aunt', 'kid'}, f"{_seen(pid)}")


def scenario_subject_restricted_owner_moves():
    _fresh()
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-dad')
    _reset(pid, owner_member_id='dad')
    _convert()
    row = storage.get_project(pid)
    check(row['owner_member_id'] == 'mom' and 'dad' not in _seen(pid), f"a hidden owner hands over to a parent in the set: {row}")
    check(row['audience'] == 'private' and row['shared_with'] == ['mom'], f"{row}")


def scenario_empty_set_goes_untitled():
    _fresh()
    storage.save_occasion({'id': 'occ-nobody', 'title': 'x', 'audience': 'private', 'shared_with': ['ghost']})
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-nobody')
    _reset(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['title'] == 'Untitled project' and row['goal'] == '' and row['audience'] == 'private', f"{row}")
    check(row['shared_with'] == [row['owner_member_id']] and _seen(pid) == {row['owner_member_id']}, f"only the owner: {row}")


def scenario_missing_record_wrapper():
    _fresh()
    tid, pid = _wrapped_thread('mom')
    storage.delete_thread(tid)
    _reset(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['audience'] == 'private' and row['shared_with'] == [row['owner_member_id']], f"{row}")


def scenario_body_goal_wrapper_is_private_first():
    _fresh()
    tid, pid = _wrapped_thread('mom')
    _reset(pid, body_goal=True)
    _convert()
    row = storage.get_project(pid)
    check(row['audience'] == 'private' and row['shared_with'] == ['mom'], f"a body goal never takes a record's audience: {row}")


def scenario_interrupted_migration_resumes():
    _fresh()
    a, b = _legacy('kid', 'private', title='A'), _legacy('kid', 'private', title='B')
    _convert()
    storage.update_project(a, {'shared_with': ['kid', 'mom']})            # Kate took Dad off since
    storage.update_project(b, {'audience_rev': None, 'shared_with': None})  # never converted
    _convert()
    check(storage.get_project(a)['shared_with'] == ['kid', 'mom'], "a converted row is left alone")
    check(set(storage.get_project(b)['shared_with']) == {'kid', 'mom', 'dad'}, "the rest converts")
    check(_convert()['converted'] == 0, "a second run is a no-op")


def scenario_wrapper_whose_record_names_it():
    _fresh()
    tid, pid = _wrapped_thread('mom')
    storage.update_thread(tid, {'subject_kind': 'project', 'subject_id': pid})
    _reset(pid)
    _convert()   # must terminate
    row = storage.get_project(pid)
    check(row.get('audience_rev') == 2 and 'mom' in _seen(pid), f"a self-reference converts once and the owner keeps it: {row}")


def scenario_deleting_the_record_changes_nobody():
    _fresh()
    tid, pid = _wrapped_thread('dad')
    _convert()
    before = _seen(pid)
    storage.delete_thread(tid)
    check(_seen(pid) == before, f"the project keeps its audience: {before} -> {_seen(pid)}")
    _convert()
    check(_seen(pid) == before, "and a later conversion pass does not move it either")


def scenario_new_wrapper_born_household():
    _fresh()
    tid, pid = _wrapped_thread('dad')
    row = storage.get_project(pid)
    check(row.get('audience_rev') == 2 and row['audience'] == 'household', f"Dad's plain thread is born a converted household wrapper: {row}")
    check(access.project_visible(row, access.HOUSE) and 'aunt' in _seen(pid), "the house and Aunt see it")


def scenario_new_wrapper_derives_live():
    _fresh()
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    tid, pid = _wrapped_thread('kid', subject_kind='occasion', subject_id='occ-dad')
    row = storage.get_project(pid)
    check(row.get('audience_rev') == 2 and 'dad' not in _seen(pid), f"a new wrapper is born converted and narrow: {row}")
    check(_seen(pid) == {'kid', 'mom'}, f"exactly the record's readers: {_seen(pid)}")


def scenario_binding_narrows_once():
    """No writer service exists (the writers are inline storage.update_thread calls in missions.py,
    agent_tools_v2.py and planned.py), so this calls project_audience.narrow_on_bind directly after
    writing the subject the way those callers do."""
    _fresh()
    from services import project_audience
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    tid, pid = _wrapped_thread('mom')
    check(storage.get_project(pid)['audience'] == 'household' and 'dad' in _seen(pid), "the fixture: a household wrapper Dad sees")
    storage.update_thread(tid, {'subject_kind': 'occasion', 'subject_id': 'occ-dad', 'subject_rev': 1})
    project_audience.narrow_on_bind('thread', storage.get_thread(tid))
    check('dad' not in _seen(pid), f"binding a private occasion narrows the wrapper: {storage.get_project(pid)}")
    check(_seen(pid) == {'mom'}, f"the people who may read the record keep it: {_seen(pid)}")
    narrowed = storage.get_project(pid)
    storage.update_thread(tid, {'subject_kind': 'occasion', 'subject_id': 'o2', 'subject_rev': 2})   # o2: a household occasion
    project_audience.narrow_on_bind('thread', storage.get_thread(tid))
    after = storage.get_project(pid)
    check(after['audience'] == narrowed['audience'] and after['shared_with'] == narrowed['shared_with']
          and after['owner_member_id'] == narrowed['owner_member_id'], f"a wider subject never widens it: {narrowed} -> {after}")
    check('dad' not in _seen(pid), "Dad is still out")


def scenario_binding_never_touches_a_real_project():
    _fresh()
    from services import project_audience, threads
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    res = _p().create({'title': 'Garage', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))
    pid = res['project']['id']
    tid = threads.create(title='In a real project', owner_member_id='mom', created_by='mom', project_id=pid)
    storage.update_thread(tid, {'subject_kind': 'occasion', 'subject_id': 'occ-dad', 'subject_rev': 1})
    project_audience.narrow_on_bind('thread', storage.get_thread(tid))
    check(storage.get_project(pid)['audience'] == 'household' and 'dad' in _seen(pid),
          "only a wrapper narrows; a person's own project keeps the audience they chose")


def scenario_wrapper_audience_stays_authoritative_after_the_record_changes():
    """The converted audience is the project's own: it differs from its record's readers on purpose
    (narrower and wider), and neither deleting the record nor changing what it is about moves it.
    A retained live gate fails the wider case, since a missing record used to read as visible."""
    _fresh()
    from services import threads
    # Narrower: the record is open to everyone; the person made the project Mom's alone.
    tid, pid = _wrapped_thread('mom')
    storage.update_project(pid, {'audience': 'private', 'shared_with': ['mom']})
    # Wider: the record is Mom-only (a private occasion), the person made the project household.
    storage.save_occasion({'id': 'occ-mom', 'title': 'Mom only', 'audience': 'private', 'shared_with': ['mom']})
    tid2, pid2 = _wrapped_thread('mom', subject_kind='occasion', subject_id='occ-mom')
    storage.update_project(pid2, {'audience': 'household', 'shared_with': []})
    for step in ('as is', 'record deleted', 'subject changed', 'converted again'):
        if step == 'record deleted':
            storage.delete_thread(tid)
            storage.delete_thread(tid2)
        elif step == 'subject changed':
            storage.save_occasion({'id': 'occ-open', 'title': 'Open', 'audience': 'household'})
        elif step == 'converted again':
            _convert()
        check(_seen(pid) == {'mom'} and not access.project_visible(storage.get_project(pid), access.HOUSE),
              f"{step}: the narrower project stays Mom's alone: {_seen(pid)}")
        check(_seen(pid2) == {'mom', 'dad', 'aunt', 'kid'} and access.project_visible(storage.get_project(pid2), access.HOUSE),
              f"{step}: the wider project stays household for everyone, the house included: {_seen(pid2)}")


def scenario_mission_wrapper_converts_by_its_missions_readers():
    _fresh()
    from services import projects
    open_mission = storage.add_mission({'goal': 'Open errand', 'created_by': 'mom', 'status': 'running'})
    projects.adopt('mission', open_mission, dict(MOM))
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    secret = storage.add_mission({'goal': 'Surprise errand', 'created_by': 'mom', 'status': 'running',
                                  'subject_kind': 'occasion', 'subject_id': 'occ-dad', 'subject_rev': 1,
                                  'subject_history': [{'kind': 'occasion', 'id': 'occ-dad'}]})
    projects.adopt('mission', secret, dict(MOM))
    for mid in (open_mission, secret):
        _reset(storage.get_mission(mid)['project_id'])
    _convert()
    open_row = storage.get_project(storage.get_mission(open_mission)['project_id'])
    secret_row = storage.get_project(storage.get_mission(secret)['project_id'])
    check(open_row['audience'] == 'household', f"an open mission's wrapper is household: {open_row}")
    check(secret_row['audience'] == 'private' and secret_row['shared_with'] == ['mom'] and 'dad' not in _seen(secret_row['id']),
          f"a mission about Dad's surprise is Mom's alone: {secret_row}")


def scenario_owner_moves_keeper_first_then_parent_then_adult():
    _fresh()
    storage.save_occasion({'id': 'occ-ma', 'title': 'Mom and Aunt', 'audience': 'private', 'shared_with': ['mom', 'aunt']})
    # Keeper first: Aunt keeps the thread, the project was Dad's, Dad is hidden, Mom is a parent in the set.
    tid, pid = _wrapped_thread('aunt', subject_kind='occasion', subject_id='occ-ma')
    _reset(pid, owner_member_id='dad')
    _convert()
    check(storage.get_project(pid)['owner_member_id'] == 'aunt', f"the record's keeper before any parent: {storage.get_project(pid)}")
    # Parent before adult: no keeper in the set (the thread has none), Mom and Aunt both read it.
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-ma')
    _reset(pid, owner_member_id='dad')
    _convert()
    check(storage.get_project(pid)['owner_member_id'] == 'mom', f"a parent before an adult: {storage.get_project(pid)}")
    # Adult last: only Aunt reads it.
    storage.save_occasion({'id': 'occ-a', 'title': 'Aunt only', 'audience': 'private', 'shared_with': ['aunt']})
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-a')
    _reset(pid, owner_member_id='mom')
    _convert()
    row = storage.get_project(pid)
    check(row['owner_member_id'] == 'aunt' and row['audience'] == 'private' and row['shared_with'] == ['aunt'], f"an adult when no parent can: {row}")


def scenario_wrapped_from_is_provenance_only():
    _fresh()
    tid, pid = _wrapped_thread('dad')
    _reset(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['wrapped_from'] == {'kind': 'thread', 'id': tid}, f"conversion keeps the provenance: {row['wrapped_from']}")
    before = _seen(pid)
    storage.update_project(pid, {'wrapped_from': None})
    check(_seen(pid) == before and access.project_visible(storage.get_project(pid), access.HOUSE), "visibility never reads it")
    storage.update_project(pid, {'wrapped_from': {'kind': 'thread', 'id': 'gone'}})
    check(_seen(pid) == before, "nor does a dangling one change it")


def scenario_a_childs_private_list_is_frozen_once_converted():
    _fresh()
    kid = _legacy('kid', 'private', title='Kate diary')
    _convert()
    listed = set(storage.get_project(kid)['shared_with'])
    check(listed == {'kid', 'mom', 'dad'}, f"the child and today's parents: {listed}")
    storage.update_member('kid', {'role': 'adult', 'is_child': False})
    storage.add_member({'id': 'step', 'name': 'Step', 'role': 'parent'})
    _convert()
    row = storage.get_project(kid)
    check(set(row['shared_with']) == listed, f"adulthood and a new parent do not edit the list: {row['shared_with']}")
    members = [dict(MOM), dict(DAD), {'id': 'step', 'name': 'Step', 'role': 'parent'}, {'id': 'kid', 'name': 'Kate', 'role': 'adult'}]
    check({m['id'] for m in members if _p().can_see(row, m)} == {'mom', 'dad', 'kid'}, "the parents who were on it still see it; a parent added later does not")


def scenario_the_numbered_migration_runs_after_adoption():
    """Runtime: the real async runner, on fixture storage, with its 5 s start-up sleep skipped."""
    import asyncio
    from services import migrations
    check(hasattr(migrations, 'migrate_project_audiences_v2499'), "the migration is named migrate_project_audiences_v2499")
    _fresh()
    kid = _legacy('kid', 'private', title='Kate diary')
    tid, pid = _wrapped_thread('dad')
    _reset(pid)
    order = []

    def recording(name):
        real = getattr(migrations, name)

        def run(*args, **kwargs):
            order.append(name)
            return real(*args, **kwargs)
        return run

    real_sleep = asyncio.sleep

    async def no_wait(delay, *args, **kwargs):
        return await real_sleep(0)
    saved = {n: getattr(migrations, n) for n in ('migrate_projects_adopt_v2499517', 'migrate_project_audiences_v2499')}
    try:
        for name in saved:
            setattr(migrations, name, recording(name))
        migrations.asyncio.sleep = no_wait
        asyncio.run(migrations.run_all_migrations())
    finally:
        migrations.asyncio.sleep = real_sleep
        for name, fn in saved.items():
            setattr(migrations, name, fn)
    check(order == ['migrate_projects_adopt_v2499517', 'migrate_project_audiences_v2499'],
          f"the audience conversion runs once, after the adoption: {order}")
    check(storage.get_project(kid).get('audience_rev') == 2 and set(storage.get_project(kid)['shared_with']) == {'kid', 'mom', 'dad'},
          "and the runner really converted the legacy rows")
    check(storage.get_project(pid).get("audience_rev") == 2 and storage.get_project(pid)["audience"] == "household", f"wrappers too: {storage.get_project(pid)}")


if __name__ == '__main__':
    import sys
    import traceback
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            try:
                fn()
                print('PASS', name)
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    sys.exit(1 if failed else 0)
