"""Delete, by hand only: a thread takes its missions, their steps, their
screenshot folders and its asks with it; a single mission the same for
itself. Parent/adult; a child is refused; Argyle has no such tool. Built
2026-10-11 for the test clutter that was seeding later runs."""
import os

from harness import check  # noqa: F401
from fastapi import HTTPException
from services import storage, threads, missions, asks


def _reset():
    for t in (storage.threads_table, storage.missions_table, storage.mission_steps_table, storage.members_table,
              storage.asks_table, storage.app_state_table):
        t.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True})
    storage.get_settings = lambda: {'missions_enabled': True, 'thread_stall_days': 7}


def _seed():
    tid = threads.create('GE Cafe Dishwasher Repair', owner_member_id='mom', created_by='mom')
    m1 = storage.add_mission({'goal': 'g1', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission', 'status': 'done'})
    m2 = storage.add_mission({'goal': 'g2', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    for m in (m1, m2):
        storage.add_mission_step(m, {'kind': 'note', 'name': 'x', 'result_json': {}})
        d = missions.browse_dir(m)
        with open(os.path.join(d, 'turn_01.png'), 'wb') as f:
            f.write(b'png')
    other = storage.add_mission({'goal': 'elsewhere', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(other, {'kind': 'note', 'name': 'x', 'result_json': {}})
    return tid, m1, m2, other


def scenario_deleting_a_thread_takes_everything_of_its_own():
    _reset()
    tid, m1, m2, other = _seed()
    d1 = missions.browse_dir(m1)
    storage.add_ask({'situation_kind': 'thread', 'situation_id': tid, 'to_name': 'Pest Co', 'state': 'sent', 'what': 'x'})
    res = threads.delete(tid)
    check(res['status'] == 'ok' and res['missions'] == 2, f"deleted with its two missions: {res}")
    check(storage.get_thread(tid) is None and storage.get_mission(m1) is None and storage.get_mission(m2) is None, "thread and missions gone")
    check(not storage.get_mission_steps(m1) and not storage.get_mission_steps(m2), "their steps gone")
    check(not os.path.exists(d1), "their screenshot folders gone")
    check(not asks.asks_for('thread', tid), "its asks gone")
    check(storage.get_mission(other) and storage.get_mission_steps(other), "an unrelated mission is untouched")
    check(threads.delete('nope')['status'] == 'not_found', "a missing thread is honest")


def scenario_deleting_a_mission_takes_only_itself():
    _reset()
    tid, m1, m2, other = _seed()
    d2 = missions.browse_dir(m2)
    res = missions.delete(m2)
    check(res['status'] == 'ok' and storage.get_mission(m2) is None and not storage.get_mission_steps(m2) and not os.path.exists(d2), f"gone with its steps and folder: {res}")
    check(storage.get_thread(tid) and storage.get_mission(m1), "the thread and its other mission stay")


def scenario_the_routes_are_parent_only():
    _reset()
    tid, m1, m2, other = _seed()
    import main

    def code(fn, *a, **kw):
        try:
            return 200, fn(*a, **kw)
        except HTTPException as e:
            return e.status_code, None
    check(code(main.delete_mission_route, m2, member_id='kid', request=None)[0] == 403, "a child cannot delete a mission")
    check(code(main.delete_thread_route, tid, member_id='kid', request=None)[0] == 403, "a child cannot delete a thread")
    c, body = code(main.delete_mission_route, m2, member_id='mom', request=None)
    check(c == 200 and storage.get_mission(m2) is None, f"a parent deletes a mission: {c} {body}")
    c, body = code(main.delete_thread_route, tid, member_id='mom', request=None)
    check(c == 200 and storage.get_thread(tid) is None and storage.get_mission(m1) is None, f"a parent deletes a thread: {c} {body}")
    check(code(main.delete_thread_route, tid, member_id='mom', request=None)[0] == 404, "gone is 404")


def scenario_argyle_has_no_delete_and_the_pages_have_the_buttons():
    from services import agent_tools_v2 as tools
    names = {t['name'] for t in tools.get_available_tools()} | set(tools.TOOL_HANDLERS)
    check(not [n for n in names if 'delete' in n and ('thread' in n or 'mission' in n)], f"no agent tool deletes a thread or a mission: {sorted(names)}")
    tp = open('templates/components/threads_page.html', encoding='utf-8').read()
    mp = open('templates/components/missions_page.html', encoding='utf-8').read()
    check('deleteThread(' in tp and 'showClosed' in tp and 'Show closed' in tp, "the thread page has Delete and the closed toggle")
    check('deleteMission(' in mp, "the missions page has Delete")
    check('promptConfirm' in tp.split('async deleteThread(')[1][:600] and 'promptConfirm' in mp.split('async deleteMission(')[1][:600], "both confirm first")


SCENARIOS = [scenario_deleting_a_thread_takes_everything_of_its_own, scenario_deleting_a_mission_takes_only_itself,
             scenario_the_routes_are_parent_only, scenario_argyle_has_no_delete_and_the_pages_have_the_buttons]

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
