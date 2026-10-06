"""The school list's hand path (v2.499.252): add, edit and delete a task.

POST/PUT/DELETE /api/kid-tasks existed for years with no screen calling
them; the PWA School sheet and the School page now do. These pin who may
write (the child on their own list, a parent or adult; never another child,
a helper or a guest) and what a hand edit may change on a task the school
feed owns (notes and type, never the title, date or class the next sync
would put back).

Called the way test_packing_api.py calls endpoints: plain function calls,
a stub request, HTTPException caught by hand.

Run from chauffeur/:  python tests/test_kid_task_hand_path.py
"""
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='kid_task_hand_path_'))

from fastapi import HTTPException  # noqa: E402

from services import storage  # noqa: E402

REQ = types.SimpleNamespace(headers={}, query_params={})


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _refused(fn, status=403):
    try:
        fn()
    except HTTPException as e:
        return e.status_code == status
    return False


def _seed():
    for t in (storage.members_table, storage.kid_tasks_table):
        t.truncate()
    storage.add_member({'id': 'ada', 'name': 'Ada', 'role': 'child', 'is_child': True})
    storage.add_member({'id': 'ben', 'name': 'Ben', 'role': 'child', 'is_child': True})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent'})
    storage.add_member({'id': 'nan', 'name': 'Nan', 'role': 'helper'})
    storage.ensure_school_class('ada', 'SCI.7', 'SCI.7')


def _req(**kw):
    import main
    base = dict(member_id='ada', title='Read chapter 4', due_date='2026-10-09',
                kind='homework')
    base.update(kw)
    return main.KidTaskRequest(**base)


def scenario_who_may_add():
    _seed()
    import main
    t = main.create_kid_task(_req(actor_id='ada', due_time='15:30', course_key='SCI.7'), REQ)
    check(t['member_id'] == 'ada' and t['due_time'] == '15:30', 'a child adds to their own list')
    check(t['course_key'] == 'SCI.7' and t.get('course_id'), 'with one of their classes')
    check(t['created_by_member_id'] == 'ada' and t['kind_locked'], 'the author and a hand-set kind')
    t2 = main.create_kid_task(_req(actor_id='mum', title='Permission slip', kind='bring'), REQ)
    check(t2['created_by_member_id'] == 'mum', "a parent adds to a child's list")
    check(_refused(lambda: main.create_kid_task(_req(actor_id='ben'), REQ)),
          "another child is refused")
    check(_refused(lambda: main.create_kid_task(_req(actor_id='nan'), REQ)),
          "a helper is refused")
    t3 = main.create_kid_task(_req(course_key='NOT.MINE'), REQ)
    check(t3['course_key'] is None, "a class that is not the child's is dropped")
    check(_refused(lambda: main.create_kid_task(_req(due_time='25:99'), REQ), 400),
          'a bad time is refused')
    check(_refused(lambda: main.create_kid_task(_req(member_id='mum'), REQ), 400),
          "a task belongs to a child's list")


def scenario_who_may_edit_and_delete():
    _seed()
    import main
    t = main.create_kid_task(_req(actor_id='ada'), REQ)
    out = main.edit_kid_task(t['id'], _req(actor_id='ada', title='Read chapter 5',
                                           due_date='2026-10-10', kind='test'), REQ)
    check(out['title'] == 'Read chapter 5' and out['due_date'] == '2026-10-10'
          and out['kind'] == 'test', 'the child edits their own task')
    check(_refused(lambda: main.edit_kid_task(t['id'], _req(actor_id='ben'), REQ)),
          "another child cannot edit it")
    check(_refused(lambda: main.edit_kid_task(t['id'], _req(member_id='ben', actor_id='mum'), REQ), 400),
          'a task cannot be moved to another child')
    check(_refused(lambda: main.remove_kid_task(t['id'], REQ, member_id='nan')),
          'a helper cannot delete it')
    check(storage.get_kid_task(t['id']), 'and it is still there')
    main.remove_kid_task(t['id'], REQ, member_id='mum')
    check(not storage.get_kid_task(t['id']), 'a parent deletes it')
    check(main.remove_kid_task(t['id'], REQ, member_id='mum')['status'] == 'ok',
          'deleting twice is harmless')


def scenario_a_feed_task_keeps_the_schools_copy():
    _seed()
    import main
    from models.schemas import KidTask
    task = KidTask(member_id='ada', title='Unit 3 worksheet', due_date='2026-10-09',
                   kind='homework', source='ics', source_ref='feed1:abc').model_dump()
    storage.add_kid_task(task)
    out = main.edit_kid_task(task['id'], _req(actor_id='ada', title='Unit 3 worksheet',
                                              due_date='2026-10-09', kind='test',
                                              notes='bring calculator'), REQ)
    check(out['notes'] == 'bring calculator' and out['kind'] == 'test' and out['kind_locked'],
          "a feed task's notes and type are the family's")
    check(_refused(lambda: main.edit_kid_task(task['id'], _req(actor_id='ada', title='Renamed',
                                                              due_date='2026-10-09'), REQ), 400),
          "its title follows the school's copy")
    check(_refused(lambda: main.remove_kid_task(task['id'], REQ, member_id='mum'), 400),
          'deleting it is refused (the sync would bring it back); checking it off is the way')
    check(storage.get_kid_task(task['id'])['title'] == 'Unit 3 worksheet', 'nothing changed')


SCENARIOS = [scenario_who_may_add, scenario_who_may_edit_and_delete,
             scenario_a_feed_task_keeps_the_schools_copy]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f'PASS  {fn.__name__}')
        except Exception:
            failed += 1
            print(f'FAIL  {fn.__name__}')
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
