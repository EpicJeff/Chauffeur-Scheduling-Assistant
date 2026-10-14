"""A thread or mission bound to a subject inherits the subject's audience
(spec 2026-10-14 §1 and §3, Codex review findings 2, 3 and 5).

Pinned here (Task 3):

  * three fields on threads and missions (subject_kind, subject_id,
    subject_rev); a thread's missions read the THREAD's subject, a manual
    mission its own (`missions.subject_of`);
  * `situations.can_see` = today's rule AND the subject's own visibility, so a
    mission transcript about a parents-only occasion is not an adult's to read;
    two people keep their row whatever it is about: a thread's owner and a
    mission's creator (they still see the row, never the subject's words);
  * a missing subject record (deleted) falls back to today's rule; a thread
    bound to a thread never recurses;
  * the endpoints and the DM go through it: missions_detail, missions_admin,
    list_situations, list_threads, and `_dm_person` (a parent the subject
    excludes is not DM'd an ask about it);
  * the view payload carries `subject` = {kind, id, title, link, rev} only for
    a viewer who may see the record.

Run from chauffeur/:  python tests/test_subject_audience.py
"""
from types import SimpleNamespace

from harness import check  # noqa: F401
from services import storage, missions, situations
from test_subjects import _reset, _seed, MOM, DAD, AUNT, KID


def _fresh():
    _reset()
    _seed()
    for t in (storage.chat_channels_table, storage.chat_messages_table):
        t.truncate()
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}


def _bind_thread(tid, kind, sid):
    storage.update_thread(tid, {'subject_kind': kind, 'subject_id': sid, 'subject_rev': 1})
    return storage.get_thread(tid)


def _mission(created_by='mom', origin=None, **subject):
    data = {'goal': 'plan it', 'origin_kind': 'thread' if origin else 'manual', 'origin_ref': origin,
            'created_by': created_by, 'tier': 'mission'}
    mid = storage.add_mission(data)
    if subject:
        storage.update_mission(mid, subject)
    return mid


def _as(member_id):
    from services import auth as _auth
    _auth.acting_member = lambda h, q, claimed=None: {'id': member_id} if member_id else {}
    _auth.impersonation_refused = lambda acting: False
    _auth.identify = lambda h, q: {'tier': _auth.MEMBER if member_id else _auth.SERVICE, 'member': None}
    return SimpleNamespace(headers={}, query_params={'member_id': member_id} if member_id else {})


def scenario_the_record_has_three_fields():
    _fresh()
    mid = _mission()
    m = storage.get_mission(mid)
    check(m.get('subject_kind') is None and m.get('subject_id') is None and m.get('subject_rev') == 0, f"mission defaults: {m}")
    tid = storage.add_thread({'title': 'Plain', 'kind': 'project', 'state': 'open', 'owner_member_id': 'mom', 'created_by': 'mom'})
    t = storage.get_thread(tid)
    check(t.get('subject_kind') is None and t.get('subject_id') is None and t.get('subject_rev') == 0, f"thread defaults: {t}")


def scenario_a_thread_origin_mission_reads_its_threads_subject():
    _fresh()
    _bind_thread('th1', 'trip', 'ev_disney')
    mid = _mission(origin='th1')
    check(missions.subject_of(storage.get_mission(mid)) == ('trip', 'ev_disney', 1), "the thread's subject")
    storage.update_mission(mid, {'subject_kind': 'occasion', 'subject_id': 'o2', 'subject_rev': 5})
    check(missions.subject_of(storage.get_mission(mid)) == ('trip', 'ev_disney', 1),
          "a thread mission's own fields are never read: the thread is the one authority")
    manual = _mission(subject_kind='occasion', subject_id='o2', subject_rev=2)
    check(missions.subject_of(storage.get_mission(manual)) == ('occasion', 'o2', 2), "a manual mission reads its own")
    check(missions.subject_of(storage.get_mission(_mission())) == (None, None, 0), "none")


def scenario_a_bound_situation_inherits_the_subjects_audience():
    _fresh()
    th = storage.get_thread('th1')
    check(situations.can_see('thread', th, AUNT), "an unbound thread: an adult sees it, as today")
    th = _bind_thread('th1', 'occasion', 'o1')
    check(not situations.can_see('thread', th, AUNT), "bound to a parents-only occasion: the adult no longer sees it")
    check(situations.can_see('thread', th, MOM), "a parent does")
    th = _bind_thread('th1', 'occasion', 'o2')
    check(situations.can_see('thread', th, AUNT), "a household occasion widens nothing and hides nothing")
    mid = _mission(created_by='mom', subject_kind='list', subject_id='l2', subject_rev=1)
    m = storage.get_mission(mid)
    check(not situations.can_see('mission', m, DAD) and situations.can_see('mission', m, MOM),
          "a mission about a private list: only who the list is shared with")
    check(not situations.can_see('mission', m, KID), "a child never, as today")


def scenario_the_owner_and_the_creator_keep_their_row_but_not_the_subjects_words():
    _fresh()
    tid = storage.add_thread({'title': 'Aunt Jo errand', 'kind': 'project', 'state': 'open', 'owner_member_id': 'aunt', 'created_by': 'aunt'})
    th = _bind_thread(tid, 'occasion', 'o1')
    check(situations.can_see('thread', th, AUNT), "the owner keeps her own thread")
    v = situations.view('thread', tid, AUNT)
    check(v is not None and v.get('subject') is None, f"but never reads what it is about: {v and v.get('subject')}")
    mid = _mission(created_by='dad', subject_kind='list', subject_id='l2', subject_rev=1)
    m = storage.get_mission(mid)
    check(situations.can_see('mission', m, DAD), "the creator keeps the mission he started")
    check(situations.view('mission', mid, DAD).get('subject') is None, "without the private list's name")
    check(situations.view('mission', mid, MOM).get('subject') == {'kind': 'list', 'id': 'l2', 'title': 'Kate gifts',
                                                                  'link': '/shopping#l2', 'rev': 1}, "mom reads it")


def scenario_missing_subjects_fall_back_and_threads_never_recurse():
    _fresh()
    th = _bind_thread('th1', 'occasion', 'gone')
    check(situations.can_see('thread', th, AUNT), "a deleted subject protects nothing: today's rule")
    check(situations.view('thread', 'th1', MOM).get('subject') is None, "and draws no chip")
    tid = storage.add_thread({'title': 'Loop B', 'kind': 'project', 'state': 'open', 'owner_member_id': 'mom', 'created_by': 'mom'})
    _bind_thread('th1', 'thread', tid)
    _bind_thread(tid, 'thread', 'th1')
    check(situations.can_see('thread', storage.get_thread('th1'), MOM) in (True, False), "a cycle answers, never recurses")
    selfref = _bind_thread('th2', 'thread', 'th2')
    check(situations.can_see('thread', selfref, MOM) in (True, False), "a thread about itself answers")


def scenario_the_endpoints_apply_it():
    _fresh()
    import main
    from fastapi import HTTPException
    th = _bind_thread('th1', 'occasion', 'o1')
    mid = _mission(origin='th1')
    try:
        main.missions_detail(mid, request=_as('aunt'))
        check(False, "an adult may not read a transcript about a parents-only occasion")
    except HTTPException as e:
        check(e.status_code == 403, f"403, got {e.status_code}")
    check(main.missions_detail(mid, request=_as('mom'))['id'] == mid, "a parent may")
    active = main.missions_admin(request=_as('aunt'))['active']
    check(mid not in [m['id'] for m in active], "the admin list omits it for the adult")
    check(mid in [m['id'] for m in main.missions_admin(request=_as('mom'))['active']], "and keeps it for mom")
    rows = situations.list_situations(AUNT, kinds=['thread'])
    check('th1' not in [r['id'] for r in rows], "list_situations omits it")
    threads = main.list_threads(request=_as('aunt'))['threads']
    check('th1' not in [t['id'] for t in threads], "the Threads page list omits it")
    check('th1' in [t['id'] for t in main.list_threads(request=_as('mom'))['threads']], "and keeps it for mom")
    check(any(t['id'] == 'th2' for t in main.list_threads(include_closed=True, request=_as('aunt'))['threads']),
          "an unbound thread is untouched")
    # The browse screenshots are the transcript's pictures: same gate (review finding, Task 3).
    import os
    shot_dir = missions.browse_dir(mid)
    with open(os.path.join(shot_dir, 'turn_1.png'), 'wb') as f:
        f.write(b'png')
    req = _as('aunt'); req.query_params = {'member_id': 'aunt'}
    try:
        main.mission_shot(mid, 'turn_1.png', request=req)
        check(False, "an adult may not see a parents-only mission's screenshots")
    except HTTPException as e:
        check(e.status_code == 403, f"403 for the screenshot, got {e.status_code}")
    req = _as('mom'); req.query_params = {'member_id': 'mom'}
    check(main.mission_shot(mid, 'turn_1.png', request=req) is not None, "mom may")


def scenario_the_dm_skips_the_excluded_parent_but_keeps_the_creator():
    _fresh()
    sent = []
    orig = missions._post
    missions._post = lambda dm, argyle, body, card=None: sent.append((dm.get('member_ids'), body)) or {'id': f'm{len(sent)}'}
    try:
        nobody = _mission(created_by=None, subject_kind='list', subject_id='l2', subject_rev=1)
        missions._dm_person(storage.get_mission(nobody), 'Which store?')
        to = [ids for ids, _ in sent]
        check(len(to) == 1 and 'mom' in to[0] and 'dad' not in to[0], f"only the parent the list is shared with: {to}")
        sent.clear()
        dads = _mission(created_by='dad', subject_kind='list', subject_id='l2', subject_rev=1)
        missions._dm_person(storage.get_mission(dads), 'Which store?')
        check(len(sent) == 1 and 'dad' in sent[0][0], f"the creator still hears about his mission: {sent}")
        check('Kate gifts' not in sent[0][1], "and the DM is the ask's own words, never the subject's")
    finally:
        missions._post = orig


SCENARIOS = [
    scenario_the_record_has_three_fields,
    scenario_a_thread_origin_mission_reads_its_threads_subject,
    scenario_a_bound_situation_inherits_the_subjects_audience,
    scenario_the_owner_and_the_creator_keep_their_row_but_not_the_subjects_words,
    scenario_missing_subjects_fall_back_and_threads_never_recurse,
    scenario_the_endpoints_apply_it,
    scenario_the_dm_skips_the_excluded_parent_but_keeps_the_creator,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
