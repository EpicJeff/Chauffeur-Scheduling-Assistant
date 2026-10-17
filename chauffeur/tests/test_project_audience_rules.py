"""Project audience rules beyond the basic model: normalization, edit authority, body-goal ordering,
fail-closed defaults, listed children and helpers, and the reply sender's projection guard
(spec 2026-10-16-project-audiences-shared-model-design.md sections 1, 2, 4, 6).

Run from chauffeur/:  python tests/test_project_audience_rules.py
"""
from harness import check  # noqa: F401
from services import storage, access
from test_projects import _fresh, _make, _p
from test_subjects import MOM, DAD, AUNT, KID
from test_project_audience_model import _seed_extra, _seen, HAL, SIB  # noqa: F401


def _frozen(project_id):
    row = storage.get_project(project_id)
    return {k: row.get(k) for k in ('title', 'goal', 'audience', 'shared_with', 'owner_member_id', 'body_goal', 'rev')}


def scenario_normalize_more():
    _fresh(); _seed_extra()
    par = _make('mom', MOM, title='Taxes', audience='parents', shared_with=['aunt'])
    check(par['shared_with'] == [], f"parents clears the list: {par}")
    house = _make('mom', MOM, title='Garage', audience='household', shared_with=['aunt', 'kid'])
    check(house['shared_with'] == [], "household clears it too")
    storage.update_member('hal', {'status': 'disabled'})
    kept = _make('mom', MOM, title='Party', audience='shared', shared_with=['aunt', 'hal'])
    check(set(kept['shared_with']) == {'aunt', 'hal'}, f"only archived members are filtered; a disabled one stays listed: {kept['shared_with']}")
    alone = _make('mom', MOM, title='Alone', audience='private', shared_with=[])
    check(alone['shared_with'] == ['mom'], f"an explicit empty private list still holds the owner: {alone['shared_with']}")
    own = _make('kid', KID, title='Mine only', audience='private', shared_with=['kid'])
    check(own['shared_with'] == ['kid'], f"a child's explicit list is taken as given, parents included or not: {own['shared_with']}")
    default = _make('kid', KID, title='Diary', audience='private')
    check(set(default['shared_with']) == {'kid', 'mom', 'dad'}, f"no list supplied: the child and every active parent: {default['shared_with']}")
    adult = _make('mom', MOM, title='Plain', audience='private')
    check(adult['shared_with'] == ['mom'], "no list for an adult: the owner")
    sh = _make('mom', MOM, title='Shared', audience='shared', shared_with=['aunt'])
    res = _p().update(sh['id'], {'owner_member_id': 'kid'}, dict(MOM))
    check(res['status'] == 'success' and set(storage.get_project(sh['id'])['shared_with']) == {'aunt', 'kid'},
          f"the new owner is listed in a shared project: {res}")
    pa = _make('mom', MOM, title='Patch', audience='shared', shared_with=['aunt', 'kid'])
    res = _p().update(pa['id'], {'shared_with': ['aunt', 'aunt', 'ghost']}, dict(MOM))
    check(res['status'] == 'success' and storage.get_project(pa['id'])['shared_with'] == ['aunt'],
          f"PATCH from a different list filters and de-duplicates (and is accepted): {res} {storage.get_project(pa['id'])['shared_with']}")
    _p().update(pa['id'], {'audience': 'shared', 'shared_with': []}, dict(MOM))
    row = storage.get_project(pa['id'])
    check(row['audience'] == 'parents' and row['shared_with'] == [], f"PATCH: an emptied shared list becomes parents: {row}")
    res = _p().update(pa['id'], {'audience': 'family'}, dict(MOM))
    check(res['status'] == 'error' and res['message'] == 'Choose household, parents, shared or private', f"{res}")
    kate = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['kid', 'mom'])
    for actor, title in ((KID, 'Dad surprise v2'), (MOM, 'Dad surprise v3')):
        res = _p().update(kate['id'], {'title': title}, dict(actor))
        row = storage.get_project(kate['id'])
        check(res['status'] == 'success' and row['title'] == title and set(row['shared_with']) == {'kid', 'mom'} and row['audience'] == 'private',
              f"{actor['id']} renames; Dad is not restored to an explicit list: {row}")
    child_house = _make('kid', KID, title='Club', audience='household')
    _p().update(child_house['id'], {'audience': 'private'}, dict(KID))
    check(set(storage.get_project(child_house['id'])['shared_with']) == {'kid', 'mom', 'dad'}, "a child's Make private: the child and the parents")
    adult_house = _make('mom', MOM, title='Shed', audience='household')
    _p().update(adult_house['id'], {'audience': 'private'}, dict(MOM))
    check(storage.get_project(adult_house['id'])['shared_with'] == ['mom'], "an adult's Make private: the owner")


def scenario_authority_more():
    from services import projects
    _fresh()
    wanted = {
        'audience': lambda row: row['audience'] == 'parents' and row['shared_with'] == [] and row['owner_member_id'] == 'mom',
        'shared_with': lambda row: row['audience'] == 'shared' and set(row['shared_with']) == {'aunt', 'kid'} and row['owner_member_id'] == 'mom',
        'owner_member_id': lambda row: row['owner_member_id'] == 'dad' and row['audience'] == 'shared' and set(row['shared_with']) == {'aunt', 'dad'},
    }
    for patch in ({'audience': 'parents'}, {'shared_with': ['aunt', 'kid']}, {'owner_member_id': 'dad'}):
        p = _make('mom', MOM, title='Shared', audience='shared', shared_with=['aunt'])
        res = _p().update(p['id'], patch, dict(DAD))
        row = storage.get_project(p['id'])
        check(res['status'] == 'success', f"a visible non-owner parent may {patch}: {res}")
        check(wanted[next(iter(patch))](row), f"and the edit is saved, not just accepted: {patch} -> {_frozen(p['id'])}")
        check(row['title'] == 'Shared' and row['goal'] == 'hold a conversation', "and nothing else moved")
    p = _make('mom', MOM, title='Shared', audience='shared', shared_with=['aunt'])
    check(_p().can_edit_audience(storage.get_project(p['id']), dict(DAD)), "and the payload flag says so")
    kate = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['kid', 'mom'])
    before = _frozen(kate['id'])
    for patch in ({'shared_with': ['kid', 'mom', 'dad']}, {'audience': 'household'}, {'owner_member_id': 'dad'},
                  {'audience': 'shared', 'shared_with': ['dad']}):
        res = _p().update(kate['id'], patch, dict(DAD))
        check(res['status'] == 'error', f"Dad cannot reach into Kate's list with {patch}: {res}")
        check(_frozen(kate['id']) == before, f"and nothing was stored: {_frozen(kate['id'])}")
    check(not _p().can_edit_audience(storage.get_project(kate['id']), dict(DAD)), "no audience edit for a parent who cannot see it")
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    res = _p().update(p['id'], {'goal': 'A better goal'}, dict(AUNT))
    check(res['status'] == 'success' and storage.get_project(p['id'])['goal'] == 'A better goal', f"a listed adult edits the goal: {res}")
    res = projects.add_step(p['id'], {'title': 'Book the venue'}, dict(AUNT))
    check(res['status'] == 'success' and [s['title'] for s in storage.get_project(p['id'])['steps']] == ['Book the venue'], f"and adds a step: {res}")
    before = _frozen(p['id'])
    res = _p().update(p['id'], {'title': 'Party v2', 'audience': 'household'}, dict(AUNT))
    check(res['status'] == 'error' and _frozen(p['id']) == before, f"a mixed patch is refused whole, nothing applied: {res} {_frozen(p['id'])}")
    for patch in ({'shared_with': ['aunt', 'dad']}, {'owner_member_id': 'aunt'}, {'audience': 'shared'}):
        before = _frozen(p['id'])
        res = _p().update(p['id'], patch, dict(AUNT))
        check(res['status'] == 'error' and _frozen(p['id']) == before, f"{patch}: {res}")


def scenario_body_goal_reclassification():
    from services import planned
    _fresh()
    p = _make('mom', MOM, title='Plan the party', audience='private', shared_with=['aunt'])
    before = _frozen(p['id'])
    res = _p().update(p['id'], {'title': 'Reach 70 kg'}, dict(MOM))
    check(res['status'] == 'error' and _frozen(p['id']) == before, f"editing a listed private project into a body goal is refused whole: {res}")
    check(storage.get_project(p['id'])['body_goal'] is False, "and it is not classified")
    res = _p().create({'title': 'Reach 70 kg', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom',
                       'audience': 'private', 'shared_with': ['aunt']}, dict(MOM))
    check(res['status'] == 'error', f"a body goal cannot be created with anyone else on its list: {res}")
    ok = _p().create({'title': 'Reach 70 kg', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom',
                      'audience': 'private', 'shared_with': ['mom']}, dict(MOM))
    check(ok['status'] == 'success' and ok['project']['body_goal'] and ok['project']['shared_with'] == ['mom'], f"owner alone is fine: {ok}")
    shaped, err = planned._project_for_plan({'id': 'm1', 'subject_kind': None}, {
        'title': 'Reach 70 kg', 'goal': 'g', 'done_when': 'd', 'owner': 'mom',
        'audience': 'private', 'shared_with': ['aunt']}, dict(MOM))
    check(shaped is None and err, f"the plan shape refuses it too: {shaped} {err}")


def scenario_planner_menu_stays_closed():
    import datetime
    from services import missions
    prompt = missions._system_prompt(datetime.datetime(2027, 1, 4, 9, 0), {})
    line = next((l for l in prompt.splitlines() if l.startswith('{"action":"plan"')), '')
    check('"audience":"private|parents|household"' in line, f"the plan action still offers private, parents and household: {line[:160]}")
    check('shared' not in line, "and never offers to choose people or the shared value")


def scenario_unknown_audience_fails_closed():
    from services import scope
    _fresh()
    check(scope.AUDIENCE_DEFAULTS.get('project') == 'private', "a project with no audience reads as private")
    check(scope.audience_of({}, 'project') == 'private' and scope.audience_of({'audience': 'secret-club'}, 'project') == 'private',
          "and so does an unknown value")
    for audience in ({}, {'audience': 'secret-club'}, {'audience': None}):
        row = {'id': 'p', 'owner_member_id': 'mom', 'shared_with': [], **audience}
        check(_p().can_see(row, dict(MOM)), f"{audience}: the owner still sees it")
        check(not _p().can_see(row, dict(DAD)) and not _p().can_see(row, dict(AUNT)),
              f"{audience}: not a parent, not an adult (a 'parents' default would show Dad)")
        check(not access.project_visible(row, access.HOUSE) and not access.project_visible(row, access.HOUSE_PARENT),
              f"{audience}: not the house either")


def scenario_listed_children_and_helpers():
    _fresh(); _seed_extra()
    shared = _make('mom', MOM, title='Party', audience='shared', shared_with=['kid', 'hal'])
    check(_seen(shared) == {'mom', 'dad', 'kid', 'hal'}, f"shared: the parents, the owner and the listed child and helper only: {_seen(shared)}")
    private = _make('mom', MOM, title='Gift', audience='private', shared_with=['kid', 'hal'])
    check(_seen(private) == {'mom', 'kid', 'hal'}, f"private: exactly the list: {_seen(private)}")
    check(not _p().can_see(storage.get_project(shared['id']), dict(SIB)) and not _p().can_see(storage.get_project(private['id']), dict(SIB)),
          "an unlisted sibling sees neither")


def scenario_send_refuses_a_hidden_recipient():
    from services import threads, replies
    _fresh()
    p = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['kid', 'mom'])
    tid = threads.create(title='Gift ideas', owner_member_id='kid', created_by='kid', project_id=p['id'])
    thread = storage.get_thread(tid)
    entry = {'kind': 'received', 'text': 'Received from Shop: hello', 'message_id': 'm1'}
    posts = []
    real_post, real_recipients = replies._post, replies._recipients
    replies._post = lambda dm, argyle, body, card=None: posts.append((dm, body)) or {'id': 'x'}
    try:
        replies._recipients = lambda t: [storage.get_member('dad')]
        sent = replies._send(thread, entry, None)
        check(sent is False and not posts, f"a recipient whose projection is None gets nothing, and delivery says so: {sent} {posts}")
        replies._recipients = lambda t: [storage.get_member('dad'), storage.get_member('mom')]
        sent = replies._send(thread, entry, None)
        who = [set(dm.get('members') or dm.get('member_ids') or []) for dm, body in posts]
        check(sent is True and len(posts) == 1 and 'mom' in who[0] and 'dad' not in who[0], f"only the readable candidate is posted to: {who}")
    finally:
        replies._post, replies._recipients = real_post, real_recipients


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
