"""Spec §10.1: threads, missions and programs are never linked into another project.

Run from chauffeur/: python tests/test_access_add_existing_removed.py
"""
import traceback
import subprocess
from pathlib import Path

from harness import check
import access_fixture
from fastapi.testclient import TestClient
from unittest.mock import patch
from services import storage, projects, migrations, access
from services import agent_tools_v2 as tools
import main


def scenario_service_refuses_piece_kinds():
    fx = access_fixture.build()
    p = fx.projects['mom_private']
    # Adoption seeds home entries; isolate the target link list for this assertion.
    storage.update_project(p['id'], {'pieces': []})
    for kind, rkey in (('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p')):
        out = projects.add_piece(p['id'], kind, fx.ids[rkey], fx.viewers['mom'])
        check(out['status'] == 'error', f'{kind} refused: {out}')
    check(not any(x['kind'] in ('thread', 'mission', 'program')
                  for x in storage.get_project(p['id']).get('pieces') or []), 'nothing linked')


def scenario_other_kinds_still_link():
    fx = access_fixture.build()
    out = projects.add_piece(fx.projects['household']['id'], 'occasion', 'occ-parents', fx.viewers['mom'])
    check(out['status'] == 'success', f'occasion still links: {out}')


def scenario_route_and_tool_refuse():
    fx = access_fixture.build()
    token = {'X-Member-Token': storage.create_member_token('mom')}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        r = TestClient(main.app).post(f"/api/projects/{fx.projects['mom_private']['id']}/pieces",
                                      json={'kind': 'thread', 'id': fx.ids['R5t']}, headers=token)
    check(r.status_code in (400, 422) or r.json().get('status') == 'error', f'route refuses: {r.status_code} {r.text}')
    out = tools.add_to_project(project_id=fx.projects['mom_private']['id'], kind='thread', id=fx.ids['R5t'],
                               acting_member=fx.viewers['mom'])
    check(out.get('status') == 'error', f'tool refuses: {out}')


def scenario_migration_drops_old_links():
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    storage.update_project(pid, {'pieces': [{'kind': 'thread', 'id': fx.ids['R5t']},
                                            {'kind': 'occasion', 'id': 'occ-parents'}]})
    migrations.migrate_drop_piece_kind_links_v2499()
    kinds = [x['kind'] for x in storage.get_project(pid)['pieces']]
    check(kinds == ['occasion'], f'only non-piece links survive: {kinds}')
    check(storage.get_thread(fx.ids['R5t'])['project_id'] == fx.projects['household']['id'], 'home unchanged')


def scenario_the_page_offers_no_piece_kind_search():
    src = open('templates/components/projects_page.html', encoding='utf-8').read()
    check("kinds=thread" not in src and "'thread', 'mission', 'program'" not in src.split('addExisting')[-1][:400],
          'the existing-record search no longer offers piece kinds')


def scenario_migration_keeps_native_project_cards():
    fx = access_fixture.build()
    pid = fx.projects['household']['id']
    viewer = fx.viewers['mom']
    before = storage.get_project(pid)
    view_ids = [p['id'] for p in projects.view(before, viewer)['pieces']]
    card_ids = [p['id'] for p in projects.piece_cards(before, viewer)]
    check(view_ids and card_ids, 'fixture has visible native pieces and cards')
    check({p['kind'] for p in projects.piece_cards(before, viewer)} ==
          {'thread', 'mission', 'program'}, 'fixture exercises all three home kinds')
    migrations.migrate_drop_piece_kind_links_v2499()
    after = storage.get_project(pid)
    check([p['id'] for p in projects.view(after, viewer)['pieces']] == view_ids,
          'view keeps the same native piece ids in order')
    check([p['id'] for p in projects.piece_cards(after, viewer)] == card_ids,
          'piece_cards keeps the same native piece ids in order')
    check(after['pieces'] == before['pieces'], 'native entries retain all metadata')


def scenario_tool_refuses_before_lookup():
    with patch.object(tools, '_project_write_refusal', side_effect=AssertionError('no lookup')):
        for kind in ('thread', 'mission', 'program'):
            out = tools.add_to_project('missing-project', kind, 'missing-record')
            check(out.get('status') == 'error' and out.get('message') ==
                  'Threads, missions and programs start inside a project; they are not linked',
                  f'tool refuses {kind} before lookup: {out}')


def scenario_old_links_can_be_removed():
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    for kind, key in (('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p')):
        sid = fx.ids[key]
        record = access.KINDS[kind].load(sid)
        kept = {'kind': 'occasion', 'id': 'occ-parents', 'added_by': 'mom'}
        storage.update_project(pid, {'pieces': [{'kind': kind, 'id': sid}, kept]})
        out = projects.remove_piece(pid, kind, sid, fx.viewers['mom'])
        check(out['status'] == 'success' and storage.get_project(pid)['pieces'] == [kept],
              f'an old {kind} link can still be removed: {out}')
        check(access.KINDS[kind].load(sid) == record, f'{kind} record and home unchanged')


def scenario_old_links_can_be_removed_through_route():
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    token = {'X-Member-Token': storage.create_member_token('mom')}
    client = TestClient(main.app)
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        for kind, key in (('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p')):
            body = {'kind': kind, 'id': fx.ids[key]}
            storage.update_project(pid, {'pieces': [body]})
            r = client.post(f'/api/projects/{pid}/pieces/remove', json=body, headers=token)
            check(r.status_code == 200 and r.json()['status'] == 'success',
                  f'route removes {kind}: {r.status_code} {r.text}')
            check(storage.get_project(pid)['pieces'] == [], f'{kind} link removed')
            r = client.post(f'/api/projects/{pid}/pieces', json=body, headers=token)
            check(r.status_code == 400, f'route still refuses adding {kind}: {r.text}')
            check(storage.get_project(pid)['pieces'] == [], f'{kind} link stays removed')


def scenario_removing_home_links_requires_visible_records():
    fx = access_fixture.build()
    pid = fx.projects['household']['id']
    # An adult's program in Mom's private project is hidden from Dad too.
    storage.update_program(fx.ids['R3'], {'member_id': 'aunt'})
    token = {'X-Member-Token': storage.create_member_token('dad')}
    client = TestClient(main.app)
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        for kind, key in (('thread', 'R1'), ('mission', 'R2'), ('program', 'R3')):
            for sid in (fx.ids[key], 'missing-record'):
                body = {'kind': kind, 'id': sid}
                storage.update_project(pid, {'pieces': [body]})
                out = projects.remove_piece(pid, kind, sid, fx.viewers['dad'])
                check(out.get('message') == 'No such visible record', f'{kind} refused: {out}')
                r = client.post(f'/api/projects/{pid}/pieces/remove', json=body, headers=token)
                check(r.status_code == 400 and r.json()['detail'] == 'No such visible record',
                      f'route refuses hidden/missing {kind}: {r.text}')
                check(storage.get_project(pid)['pieces'] == [body], 'refusal leaves link alone')


def _migration_keeps_unresolved_membership(null_project_id):
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    expected = []
    for kind, key in (('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p')):
        row = access.KINDS[kind].load(fx.ids[key])
        row['id'] = f'unresolved-{kind}'
        if null_project_id:
            row['project_id'] = None
        else:
            row.pop('project_id')
        with storage.db_lock:
            getattr(storage, kind + 's_table').insert(row)
        loaded = access.KINDS[kind].load(row['id'])
        check(('project_id' in loaded) == null_project_id, 'fixture preserves absent versus null')
        expected.append({'kind': kind, 'id': row['id'], 'added_by': 'mom', 'added_at': 123})
    storage.update_project(pid, {'pieces': expected})
    before = storage.get_project(pid)
    migrations.migrate_drop_piece_kind_links_v2499()
    check(storage.get_project(pid) == before, 'unresolved entries and project metadata survive unchanged')
    with patch.object(storage, 'update_project', side_effect=AssertionError('no repeat writes')):
        migrations.migrate_drop_piece_kind_links_v2499()


def scenario_migration_keeps_absent_project_id():
    _migration_keeps_unresolved_membership(False)


def scenario_migration_keeps_null_project_id():
    _migration_keeps_unresolved_membership(True)


def scenario_existing_search_excludes_before_route_limit():
    fx = access_fixture.build()
    for i in range(5):
        storage.add_thread({'id': f'crowd-t{i}', 'title': 'Crowded', 'owner_member_id': 'mom'})
        storage.add_program({'id': f'crowd-p{i}', 'title': 'Crowded', 'member_id': 'mom'})
    storage.save_occasion({'id': 'crowd-occasion', 'title': 'Crowded party', 'audience': 'parents'})
    token = {'X-Member-Token': storage.create_member_token('mom')}
    client = TestClient(main.app)
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        unfiltered = client.get('/api/subjects/search', params={'q': 'Crowded'}, headers=token)
        check(unfiltered.status_code == 200, unfiltered.text)
        candidates = unfiltered.json()['candidates']
        check(len(candidates) == 8 and all(c['kind'] in ('thread', 'program') for c in candidates),
              f'fixture crowds the occasion out of the default top eight: {candidates}')
        r = client.get('/api/subjects/search', params={'q': 'Crowded', 'exclude': 'thread,mission,program'},
                       headers=token)
        check(r.status_code == 200, r.text)
        check(r.json()['candidates'] == [{'kind': 'occasion', 'id': 'crowd-occasion', 'title': 'Crowded party'}],
              f'allowed occasion survives the route limit: {r.text}')


def scenario_migration_is_idempotent_and_keeps_other_links():
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    kept = {'kind': 'occasion', 'id': 'occ-parents', 'added_by': 'mom', 'added_at': 123}
    native = storage.get_project(pid)['pieces']
    expected = [kept] + native
    storage.update_project(pid, {'pieces': expected + [
        {'kind': kind, 'id': fx.ids[key]}
        for kind, key in (('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p'))] + [
        {'kind': kind, 'id': 'missing-record'} for kind in ('thread', 'mission', 'program')]})
    before = storage.get_project(pid)
    migrations.migrate_drop_piece_kind_links_v2499()
    after = storage.get_project(pid)
    check(after['pieces'] == expected, 'native and other links keep order and metadata')
    check({k: v for k, v in after.items() if k not in ('pieces', 'updated_at', 'rev')} ==
          {k: v for k, v in before.items() if k not in ('pieces', 'updated_at', 'rev')},
          'project metadata is preserved')
    check(after['rev'] == before['rev'] + 1, 'changed project advances its revision once')
    with patch.object(storage, 'update_project', side_effect=AssertionError('no repeat writes')):
        migrations.migrate_drop_piece_kind_links_v2499()


def scenario_existing_picker_filters_at_runtime():
    src = Path('templates/components/projects_page.html').read_text(encoding='utf-8')
    script = src.split('<script>', 1)[1].split('</script>', 1)[0]
    probe = r'''
global.window = {};
global.location = {search: ''};
global.document = {documentElement: {dataset: {}}};
global.promptInput = async () => 'Parents';
const assert = require('node:assert/strict');
(async () => {
    const page = projectsPage();
    const candidates = ['thread', 'mission', 'program', 'occasion', 'list', 'trip']
        .map(kind => ({kind, id: kind, title: kind}));
    page.request = async path => {
        const url = new URL(path, 'http://localhost/');
        assert.equal(url.searchParams.get('q'), 'Parents');
        assert.deepEqual(url.searchParams.get('exclude').split(',').sort(), ['mission', 'program', 'thread']);
        return {candidates};
    };
    let offered;
    global.promptChoice = async (title, body, options) => { offered = options; return 'occasion:occasion'; };
    let posted;
    page.mutate = async (path, body) => { posted = body; return true; };
    page.loadPieces = async () => {};
    await page.pickExisting({id: 'project'});
    assert.equal(page.error, '');
    assert.deepEqual(offered.map(o => o.value), ['occasion:occasion', 'list:list', 'trip:trip']);
    assert.deepEqual(posted, {kind: 'occasion', id: 'occasion'});
    page.request = async () => ({candidates: candidates.slice(0, 3)});
    global.promptChoice = async () => { throw Error('no forbidden choices'); };
    let alert;
    global.showGlobalAlert = message => { alert = message; };
    await page.pickExisting({id: 'project'});
    assert.equal(page.error, '');
    assert.equal(alert, 'Nothing by that name.');
})().catch(e => { console.error(e); process.exitCode = 1; });
'''
    out = subprocess.run(['node', '-e', script + probe], capture_output=True, text=True)
    check(out.returncode == 0, out.stdout + out.stderr)


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
