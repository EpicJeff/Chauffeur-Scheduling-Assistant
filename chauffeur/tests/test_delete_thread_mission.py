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


_NODE_RUN = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const script = src.split('<script>')[1].split('</script>')[0];
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
(async () => {
  const out = {};
  for (const [name, c] of Object.entries(cases)) {
    const log = {requests: [], confirms: [], alerts: [], done: 0};
    const replies = c.replies.slice();
    const window = {
      fetch: async (url, init) => {
        log.requests.push({url, method: (init && init.method) || 'GET', body: init && init.body ? JSON.parse(init.body) : null});
        const [status, body] = replies.shift();
        return {ok: status >= 200 && status < 300, status, json: async () => body};
      },
      promptConfirm: async (title, message, yes, no) => { log.confirms.push({title, message, yes, no}); return c.confirm.shift(); },
      showGlobalAlert: (m) => log.alerts.push(m),
    };
    const document = {getElementById: (id) => (c.wall && id === 'cc-confirm-message') ? {} : null};
    new Function('window', 'document', 'fetch', script)(window, document, window.fetch);
    log.result = await window.chfDeleteRecord({kind: c.kind, id: c.id, title: c.title, apiBase: '', onDone: () => { log.done++; }});
    out[name] = log;
  }
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e.stack); process.exit(1); });
"""


def _run_delete_helper(cases):
    """Run the shared Delete (templates/components/record_delete.html) under
    node with the server's answers stubbed: the critical path actually runs."""
    import json
    import shutil
    import subprocess
    import tempfile
    node = shutil.which('node')
    if not node:
        print('  skip  node not available')
        return None
    with tempfile.TemporaryDirectory() as tmp:
        run, data = os.path.join(tmp, 'run.js'), os.path.join(tmp, 'cases.json')
        with open(run, 'w', encoding='utf-8') as f:
            f.write(_NODE_RUN)
        with open(data, 'w', encoding='utf-8') as f:
            json.dump(cases, f)
        proc = subprocess.run([node, run, os.path.abspath('templates/components/record_delete.html'), data],
                              capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    check(proc.returncode == 0, f"the helper threw:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_argyle_has_no_delete_and_the_pages_have_the_buttons():
    """No agent tool deletes; the thread and mission pages keep their Delete, now the shared
    two-step (preview, one promptConfirm, DELETE with the token), never a token-less DELETE."""
    from services import agent_tools_v2 as tools
    names = {t['name'] for t in tools.get_available_tools()} | set(tools.TOOL_HANDLERS)
    check(not [n for n in names if 'delete' in n and ('thread' in n or 'mission' in n)], f"no agent tool deletes a thread or a mission: {sorted(names)}")
    tp = open('templates/components/threads_page.html', encoding='utf-8').read()
    mp = open('templates/components/missions_page.html', encoding='utf-8').read()
    check('deleteThread(' in tp and 'showClosed' in tp and 'Show closed' in tp, "the thread page has Delete and the closed toggle")
    check('deleteMission(' in mp, "the missions page has Delete")
    thread_delete = tp.split('async deleteThread(')[1][:700]
    mission_delete = mp.split('async deleteMission(')[1][:700]
    check('chfDeleteRecord' in thread_delete and 'chfDeleteRecord' in mission_delete, "both confirm first, through the shared two-step")
    check("method: 'DELETE'" not in thread_delete and "method: 'DELETE'" not in mission_delete, "neither sends a DELETE of its own")
    check('record_delete_script()' in tp and 'record_delete_script()' in mp, "both pages carry the shared helper")

    items = [{'kind': 'thread', 'id': 't1', 'title': 'GE Cafe Dishwasher Repair'},
             {'kind': 'mission', 'id': 'm1', 'title': 'g1'}, {'kind': 'mission', 'id': 'm2', 'title': 'g2'}]
    ok = [200, {'status': 'ok', 'token': 'tok-1', 'items': items, 'links': 0}]
    out = _run_delete_helper({
        'deleted': {'kind': 'thread', 'id': 't1', 'title': 'GE Cafe Dishwasher Repair', 'confirm': [True],
                    'replies': [ok, [200, {'status': 'ok'}]]},
        'kept': {'kind': 'thread', 'id': 't1', 'title': 'GE Cafe Dishwasher Repair', 'confirm': [False], 'replies': [ok]},
        'changed': {'kind': 'project', 'id': 'p1', 'title': 'Kitchen', 'confirm': [True, True],
                    'replies': [ok, [409, {'detail': 'This project changed. Look again.'}],
                                [200, {'status': 'ok', 'token': 'tok-2', 'items': items[:1], 'links': 0}], [200, {'status': 'ok'}]]},
        'refused': {'kind': 'project', 'id': 'p1', 'title': 'Kitchen', 'confirm': [],
                    'replies': [[403, {'detail': 'Ask a parent to delete this.'}]]},
        'wall': {'kind': 'mission', 'id': 'm1', 'title': '<b>g1</b>', 'confirm': [False], 'wall': True,
                 'replies': [[200, {'status': 'ok', 'token': 't', 'items': [{'kind': 'mission', 'id': 'm1', 'title': '<b>g1</b> **x**'}]}]]},
    })
    if out is None:
        return
    d = out['deleted']
    check([r['method'] for r in d['requests']] == ['GET', 'DELETE'] and d['requests'][0]['url'] == 'api/deletion/thread/t1/preview'
          and d['requests'][1]['url'] == 'api/threads/t1' and d['requests'][1]['body'] == {'token': 'tok-1'},
          f"preview, then DELETE with the token it handed back: {d['requests']}")
    msg = d['confirms'][0]['message']
    check(d['confirms'][0]['title'] == 'Delete “GE Cafe Dishwasher Repair”?' and d['confirms'][0]['yes'] == 'Delete', f"one confirm: {d['confirms']}")
    check(msg.index('GE Cafe Dishwasher Repair') < msg.index('g1') < msg.index('g2') and msg.endswith('Linked trips, lists and events stay.'),
          f"titles one per line, grouped by kind, then the linked kinds stay: {msg!r}")
    check(d['result'] == 'deleted' and d['done'] == 1 and not d['alerts'], f"done once, nothing to say: {d}")
    k = out['kept']
    check(k['result'] == 'cancelled' and [r['method'] for r in k['requests']] == ['GET'] and k['done'] == 0, f"Keep it deletes nothing: {k}")
    c = out['changed']
    check(c['alerts'] == ['This project changed. Look again.'] and len(c['confirms']) == 2
          and [r['method'] for r in c['requests']] == ['GET', 'DELETE', 'GET', 'DELETE'] and c['requests'][3]['body'] == {'token': 'tok-2'}
          and c['requests'][1]['url'] == 'api/projects/p1' and c['result'] == 'deleted',
          f"changed is said, previewed again, and the new look is what is confirmed: {c}")
    r = out['refused']
    check(r['alerts'] == ['Ask a parent to delete this.'] and not r['confirms'] and len(r['requests']) == 1 and r['result'] == 'refused'
          and r['done'] == 0, f"a refusal is shown verbatim and names nothing: {r}")
    w = out['wall']
    check('<b>' not in w['confirms'][0]['message'] and '&lt;b&gt;g1&lt;/b&gt; &#42;&#42;x&#42;&#42;' in w['confirms'][0]['message'],
          f"the wall's HTML confirm gets people's words as text: {w['confirms'][0]['message']!r}")


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
