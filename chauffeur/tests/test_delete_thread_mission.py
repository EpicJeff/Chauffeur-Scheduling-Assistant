"""Delete, by hand only: a thread takes its missions, their steps, their
screenshot folders and its asks with it; a single mission the same for
itself. Parent/adult; a child is refused; Argyle has no such tool. Built
2026-10-11 for the test clutter that was seeding later runs.

Since the projects-delete slice (spec 2026-10-18 rev 3) a delete is two
steps through services.deletion: GET /api/deletion/{kind}/{id}/preview names
what will go and hands back a token, DELETE /api/threads|missions/{id} with
{token} starts it. The record is hidden at once; deletion.maintain() removes
every row and file once no work is running. A DELETE with no token is a 400
"A confirmation is required."; a record the caller cannot see is a 404."""
import os
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, threads, missions, asks, access

TOKEN_REQUIRED = "A confirmation is required."
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}


def _reset():
    for t in (storage.threads_table, storage.missions_table, storage.mission_steps_table, storage.members_table,
              storage.asks_table, storage.app_state_table, storage.projects_table):
        t.truncate()
    storage.db.table('deletions').truncate()
    storage.add_member(dict(MOM))
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


def _http(who, method, path, **kwargs):
    from fastapi.testclient import TestClient
    import main
    headers = {'X-Member-Token': storage.create_member_token(who)}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        return TestClient(main.app).request(method, path, headers=headers, **kwargs)


def _delete(who, kind, rid):
    """The two steps a person takes: look, then confirm with what they saw."""
    path = {'thread': 'threads', 'mission': 'missions'}[kind]
    preview = _http(who, 'GET', f'/api/deletion/{kind}/{rid}/preview')
    token = preview.json().get('token') if preview.status_code == 200 else 'not-a-token'
    return preview, _http(who, 'DELETE', f'/api/{path}/{rid}', json={'token': token})


def _maintain(seconds=20):
    """Cleanup waits for registered work (a coalesced refresh timer, say), so give it a few passes."""
    import time
    from services import deletion
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        deletion.maintain()
        if not storage.get_deletions():
            return
        time.sleep(0.2)
    check(False, f"cleanup did not finish: {storage.get_deletions()}")


def scenario_deleting_a_thread_takes_everything_of_its_own():
    _reset()
    tid, m1, m2, other = _seed()
    d1 = missions.browse_dir(m1)
    storage.add_ask({'situation_kind': 'thread', 'situation_id': tid, 'to_name': 'Pest Co', 'state': 'sent', 'what': 'x'})
    preview, res = _delete('mom', 'thread', tid)
    check(preview.status_code == 200 and {i['id'] for i in preview.json()['items']} == {tid, m1, m2},
          f"the preview names the thread and its two missions: {preview.status_code} {preview.text[:200]}")
    check(res.status_code == 200, f"deleted: {res.status_code} {res.text[:200]}")
    check(access.record_view('thread', storage.get_thread(tid), dict(MOM)) is None
          and _http('mom', 'GET', f'/api/threads/{tid}/missions').status_code == 404, "hidden at once")
    _maintain()
    check(storage.get_thread(tid) is None and storage.get_mission(m1) is None and storage.get_mission(m2) is None, "thread and missions gone")
    check(not storage.get_mission_steps(m1) and not storage.get_mission_steps(m2), "their steps gone")
    check(not os.path.exists(d1), "their screenshot folders gone")
    check(not asks.asks_for('thread', tid), "its asks gone")
    check(storage.get_mission(other) and storage.get_mission_steps(other), "an unrelated mission is untouched")
    preview, res = _delete('mom', 'thread', 'nope')
    check(preview.status_code == 404 and res.status_code == 404, "a missing thread is honest")


def scenario_deleting_a_mission_takes_only_itself():
    _reset()
    tid, m1, m2, other = _seed()
    d2 = missions.browse_dir(m2)
    preview, res = _delete('mom', 'mission', m2)
    check(preview.status_code == 200 and [i['id'] for i in preview.json()['items']] == [m2],
          f"the preview names only the mission: {preview.status_code} {preview.text[:200]}")
    check(res.status_code == 200, f"deleted: {res.status_code} {res.text[:200]}")
    _maintain()
    check(storage.get_mission(m2) is None and not storage.get_mission_steps(m2) and not os.path.exists(d2), "gone with its steps and folder")
    check(storage.get_thread(tid) and storage.get_mission(m1), "the thread and its other mission stay")


def scenario_the_routes_are_parent_only_and_need_a_confirmation():
    _reset()
    tid, m1, m2, other = _seed()
    kid_thread = threads.create('Kate homework', owner_member_id='kid', created_by='kid')
    for kind, rid, path in (('mission', m2, 'missions'), ('thread', tid, 'threads')):
        r = _http('mom', 'DELETE', f'/api/{path}/{rid}', json={})
        check(r.status_code == 400 and TOKEN_REQUIRED in r.text, f"{kind}: no token is a 400: {r.status_code} {r.text[:200]}")
        check(not (storage.get_thread(rid) if kind == 'thread' else storage.get_mission(rid)).get('deleting'),
              f"{kind}: and deletes nothing")
    _, r = _delete('kid', 'mission', m2)
    check(r.status_code == 404, f"a child cannot see, so cannot delete, a mission: {r.status_code}")
    _, r = _delete('kid', 'thread', tid)
    check(r.status_code == 404, f"a child cannot delete a parent's thread: {r.status_code}")
    token = _http('mom', 'GET', f'/api/deletion/thread/{kid_thread}/preview').json()['token']
    r = _http('kid', 'DELETE', f'/api/threads/{kid_thread}', json={'token': token})
    check(r.status_code == 403 and not storage.get_thread(kid_thread).get('deleting'),
          f"a child cannot delete even her own thread: {r.status_code} {r.text[:200]}")
    _, r = _delete('mom', 'mission', m2)
    check(r.status_code == 200 and access.record_view('mission', storage.get_mission(m2), dict(MOM)) is None,
          f"a parent deletes a mission: {r.status_code} {r.text[:200]}")
    _, r = _delete('mom', 'thread', tid)
    check(r.status_code == 200, f"a parent deletes a thread: {r.status_code} {r.text[:200]}")
    _, r = _delete('mom', 'thread', tid)
    check(r.status_code == 404, "gone is 404")
    _maintain()
    check(storage.get_thread(tid) is None and storage.get_mission(m1) is None, "and after cleanup nothing is left")


def scenario_the_helpers_delegate_to_the_deletion_service():
    """threads.delete(thread_id) and missions.delete(mission_id) keep their signatures and become thin
    calls into services.deletion: a missing record is {'status': 'not_found'}; an existing one starts a
    deletion (hidden at once) and is gone with everything of its own after maintain()."""
    _reset()
    tid, m1, m2, other = _seed()
    d1 = missions.browse_dir(m1)
    storage.add_ask({'situation_kind': 'thread', 'situation_id': tid, 'to_name': 'Pest Co', 'state': 'sent', 'what': 'x'})
    check(threads.delete('nope') == {'status': 'not_found'}, "a missing thread is honest")
    check(missions.delete('nope') == {'status': 'not_found'}, "a missing mission is honest")
    res = missions.delete(other)
    check(res.get('status') == 'ok', f"the mission helper starts a deletion: {res}")
    rows = [r for r in storage.get_deletions() if r['kind'] == 'mission' and r['root_id'] == other]
    check(len(rows) == 1 and storage.get_mission(other).get('deleting') == rows[0]['id'],
          f"through the deletion service: a deletions row, and the mission stamped at once: {storage.get_deletions()}")
    res = threads.delete(tid)
    check(res.get('status') == 'ok', f"the thread helper starts a deletion: {res}")
    rows = [r for r in storage.get_deletions() if r['kind'] == 'thread' and r['root_id'] == tid]
    check(len(rows) == 1 and {tuple(x)[1] for x in rows[0]['closure']} >= {tid, m1, m2},
          f"its closure is the thread and both its missions: {rows}")
    check(access.record_view('thread', storage.get_thread(tid), dict(MOM)) is None, "hidden at once")
    _maintain()
    check(storage.get_thread(tid) is None and storage.get_mission(m1) is None and storage.get_mission(m2) is None
          and storage.get_mission(other) is None, "all gone after maintain()")
    check(not storage.get_mission_steps(m1) and not os.path.exists(d1) and not asks.asks_for('thread', tid),
          "with their steps, screenshot folders and asks")


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
             scenario_the_routes_are_parent_only_and_need_a_confirmation,
             scenario_the_helpers_delegate_to_the_deletion_service,
             scenario_argyle_has_no_delete_and_the_pages_have_the_buttons]

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
