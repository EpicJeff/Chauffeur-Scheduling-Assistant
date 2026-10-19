"""Program library, who may do what (spec 2026-10-19-program-library-design.md rev 3, section 2; plan Task 1 Step 2).

Pinned here, on the access fixture household (tests/access_fixture.py, R1-R17):

  * the library is public curriculum: every active member reads it (GET /api/library and
    /api/library/{id}) and `library.runners(lid, access.HOUSE)` serves the house; a disabled member
    and an identity-free request reach nothing;
  * `library.create(fields, actor)`: an adult or a parent; never a child or a helper;
  * `library.update/archive/add_lesson/update_lesson/remove_lesson/order_lessons` and
    `library.can_edit(row, viewer)`: the creator or any parent; anyone else is refused with
    "Only the person who made this program, or a parent, can change it.";
  * `library.delete(lid, actor)`: refused while any run references the row, in any state; the
    refusal names only runners whose project the viewer sees ("In use by Kate's project"),
    otherwise "In use by another project";
  * `library.runners(lid, viewer) -> {'named': [{name, project_id, project_title}], 'hidden': n}`:
    Dad never learns of Kate's excluded projects (R15, R17) through the library;
  * the run cells R3/R5p/R15/R17 and the keeper action gates are unchanged by a library binding;
  * a run's starting point never appears on any library surface;
  * test_access_register discovers the /api/library* routes, and the matrix probes in
    access_fixture (public curriculum vs restricted runner) match for every cell.

Run from chauffeur/:  python tests/test_library_access.py   (HA_BASE_URL unset)
"""
import importlib
import json
import traceback
from unittest.mock import patch

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
import access_fixture
from access_fixture import EDIT_REFUSAL, IN_USE_ANOTHER, LIBRARY_ROUTES, library_expected
from access_signed_in import request
from test_access_core import TABLE, COLS, KIND, load
from test_subjects import MOM, DAD, AUNT, KID
from services import storage, access, access_readers as reg
import main

UNCLE = {'id': 'uncle', 'name': 'Uncle Ray', 'role': 'adult'}
HAL = access_fixture.HAL
PROGRAM_KEYS = [k for k in TABLE if KIND[k] == 'program']
PROFILE = {'title': 'Learn the recorder', 'age_band': 'any', 'minutes': 15, 'sessions_per_week': 2,
           'assumes': 'complete beginner'}
CURATED = {'phases': [{'name': 'Breath', 'weeks': 2, 'what': 'Long notes', 'milestone': 'Hold a note for ten seconds',
                       'units': [{'n': 1, 'title': 'Long B', 'sessions': 1}]}],
           'source': {'origin': 'generated', 'plan_name': '', 'url': '', 'facts': [], 'reason': 'test'}}


def _svc():
    """services.library, imported per call: until Task 2 lands each scenario is red on its own."""
    return importlib.import_module('services.library')


def _ok(res):
    return (res or {}).get('status') in ('success', 'ok')


def _build():
    storage.add_library_program  # the library's storage door: red here until Task 2
    fx = access_fixture.build()
    storage.add_member(dict(UNCLE))
    fx.viewers['uncle'] = dict(UNCLE)
    return fx


def _shared(fx, keys=('R3', 'R5p', 'R15', 'R17'), created_by='aunt'):
    """One library row the given fixture runs all run; Aunt (an adult, not a parent) made it."""
    with patch('services.programs_curate.curate', return_value=CURATED):
        res = _svc().create(dict(PROFILE, title='Learn piano together'), dict(storage.get_member(created_by)))
    check(_ok(res), f'the shared row: {res}')
    lid = res['program']['id']
    for key in keys:
        storage.update_program(fx.ids[key], {'library_id': lid})
    return lid


def _project_of(fx, key):
    return storage.get_project(storage.get_program(fx.ids[key])['project_id'])


def scenario_the_library_is_public_curriculum():
    fx = _build()
    check(set(fx.library) >= set(PROGRAM_KEYS), f'the fixture binds every run to a library row: {fx.library}')
    titles = [fx.title(k) for k in PROGRAM_KEYS]
    for col in ('mom', 'dad', 'aunt', 'kid', 'hal', 'uncle'):
        r = request(fx, col, 'GET', '/api/library')
        check(r.status_code == 200 and all(t in r.text for t in titles), f'{col} reads the library: {r.status_code} {r.text[:200]}')
        for key in PROGRAM_KEYS:
            r = request(fx, col, 'GET', f'/api/library/{fx.library[key]}')
            check(r.status_code == 200 and fx.title(key) in r.text, f'{col} reads {key}: {r.status_code} {r.text[:200]}')
    check(request(fx, 'pat', 'GET', '/api/library') is None, 'a disabled member is never let in')
    r = request(fx, 'house', 'GET', '/api/library')
    check(r.status_code in (401, 403), f'an identity-free request is refused at the door: {r.status_code}')
    out = _svc().runners(fx.library['R5p'], access.HOUSE)
    check([n['project_id'] for n in out['named']] == [fx.projects['household']['id']] and out['hidden'] == 0,
          f'the house reads the household runner: {out}')
    out = _svc().runners(fx.library['R3'], access.HOUSE)
    check(out['named'] == [] and out['hidden'] == 1, f'and counts the private one: {out}')


def scenario_create_is_for_an_adult_or_a_parent():
    fx = _build()
    lib = _svc()
    before = len(storage.get_library_programs())
    with patch('services.programs_curate.curate', return_value=CURATED):
        for member in (AUNT, MOM, UNCLE):
            res = lib.create(dict(PROFILE), dict(member))
            check(_ok(res) and res['program']['created_by'] == member['id'], f"{member['id']} creates: {res}")
            row = storage.get_library_program(res['program']['id'])
            check(row['made_for'] == {'age_band': 'any', 'minutes': 15, 'sessions_per_week': 2,
                                      'assumes': 'complete beginner'}, f"the public profile: {row['made_for']}")
        for member in (KID, HAL):
            res = lib.create(dict(PROFILE), dict(member))
            check(not _ok(res) and res.get('message'), f"{member['id']} is refused: {res}")
        check(len(storage.get_library_programs()) == before + 3, 'only the three adults made rows')
        r = request(fx, 'kid', 'POST', '/api/library', json=dict(PROFILE))
        check(r.status_code == 403, f'a child at the HTTP door: {r.status_code} {r.text[:200]}')
        r = request(fx, 'aunt', 'POST', '/api/library', json=dict(PROFILE))
        check(r.status_code == 200 and _ok(r.json()), f'an adult at the HTTP door: {r.status_code} {r.text[:200]}')
    check(len(storage.get_library_programs()) == before + 4, 'one more row, the adult\'s')


def scenario_editing_is_the_creators_or_a_parents():
    fx = _build()
    lib = _svc()
    lid = fx.library['R5p']                       # Aunt made every fixture row
    row = storage.get_library_program(lid)
    phase, lesson = row['phases'][0]['id'], row['lessons'][0]['id']
    for viewer, allowed in ((AUNT, True), (MOM, True), (DAD, True), (UNCLE, False), (KID, False),
                            (HAL, False), (access.HOUSE, False)):
        check(lib.can_edit(storage.get_library_program(lid), dict(viewer)) is allowed,
              f"can_edit {viewer.get('id')}: want {allowed}")
    for member in (UNCLE, KID, HAL):
        actor = dict(member)
        before = storage.get_library_program(lid)
        for name, call in (('update', lambda: lib.update(lid, {'title': 'Hijacked'}, actor)),
                           ('archive', lambda: lib.archive(lid, actor)),
                           ('add_lesson', lambda: lib.add_lesson(lid, {'phase_id': phase, 'title': 'X', 'sessions': 1}, actor)),
                           ('update_lesson', lambda: lib.update_lesson(lid, lesson, {'title': 'X'}, actor)),
                           ('remove_lesson', lambda: lib.remove_lesson(lid, lesson, actor)),
                           ('order_lessons', lambda: lib.order_lessons(lid, [l['id'] for l in reversed(before['lessons'])], actor)),
                           ('delete', lambda: lib.delete(lid, actor))):
            res = call()
            check(not _ok(res) and res.get('message') == EDIT_REFUSAL, f"{member['id']} {name}: {res}")
        check(storage.get_library_program(lid) == before, f"{member['id']}: nothing changed")
    for member in (AUNT, DAD, MOM):
        res = lib.update(lid, {'title': f"Edited by {member['id']}"}, dict(member))
        check(_ok(res) and storage.get_library_program(lid)['title'] == f"Edited by {member['id']}", f"{member['id']} edits: {res}")
    r = request(fx, 'uncle', 'PATCH', f'/api/library/{lid}', json={'title': 'Hijacked'})
    check(r.status_code == 403 and EDIT_REFUSAL in r.text, f'the HTTP refusal says why: {r.status_code} {r.text[:200]}')
    res = lib.archive(lid, dict(AUNT))
    check(_ok(res) and storage.get_library_program(lid)['archived'] is True, f'the creator archives: {res}')
    check(storage.get_program(fx.ids['R5p'])['library_id'] == lid, 'archiving touches no run')


def scenario_delete_is_refused_while_any_run_exists():
    fx = _build()
    lib = _svc()
    lid = _shared(fx, keys=('R15',))              # Kate's run in Kate's list, which leaves Dad out
    for state in ('proposed', 'active', 'paused', 'done', 'dropped'):
        storage.update_program(fx.ids['R15'], {'state': state})
        res = lib.delete(lid, dict(DAD))
        check(not _ok(res) and res.get('message') == IN_USE_ANOTHER and 'Kate' not in json.dumps(res),
              f'{state}: Dad learns only that it is in use: {res}')
        res = lib.delete(lid, dict(MOM))
        check(not _ok(res) and "In use by Kate's project" in (res.get('message') or ''), f'{state}: Mom is told whose: {res}')
        res = lib.delete(lid, dict(AUNT))
        check(not _ok(res) and res.get('message') == IN_USE_ANOTHER, f'{state}: Aunt made it but cannot see the project: {res}')
        check(storage.get_library_program(lid) is not None, f'{state}: the row stays')
    storage.update_program(fx.ids['R5p'], {'library_id': lid})   # a second run, in the household project
    res = lib.delete(lid, dict(DAD))
    words = json.dumps(res)
    check(not _ok(res) and "In use by Kate's project" in (res.get('message') or '')
          and 'Kate no Dad' not in words and fx.projects['kate_no_dad']['id'] not in words,
          f'only the runner Dad can see is named: {res}')
    r = request(fx, 'dad', 'DELETE', f'/api/library/{lid}', json={})
    check('In use by' in r.text and 'Kate no Dad' not in r.text and storage.get_library_program(lid),
          f'the HTTP refusal: {r.status_code} {r.text[:200]}')
    for key in ('R15', 'R5p'):
        storage.programs_table.remove(storage.Query().id == fx.ids[key])
    check(_ok(lib.delete(lid, dict(AUNT))) and storage.get_library_program(lid) is None, 'unused: the creator deletes it')


def scenario_runners_hide_projects_the_viewer_cannot_see():
    fx = _build()
    lid = _shared(fx)
    p = {k: _project_of(fx, k) for k in ('R3', 'R5p', 'R15', 'R17')}
    want = {'mom': ({'R3', 'R5p', 'R15', 'R17'}, 0), 'dad': ({'R5p'}, 3), 'aunt': ({'R5p'}, 3),
            'kid': ({'R5p', 'R15', 'R17'}, 1), 'hal': ({'R5p'}, 3), 'house': ({'R5p'}, 3)}
    for col, (keys, hidden) in want.items():
        out = _svc().runners(lid, fx.viewers[col])
        named = {n['project_id'] for n in out['named']}
        check(named == {p[k]['id'] for k in keys} and out['hidden'] == hidden, f'{col}: {out}')
        for n in out['named']:
            check(n['name'] == 'Kate' and n['project_title'] == storage.get_project(n['project_id'])['title'],
                  f'{col}: a named runner is the person and the project: {n}')
        words = json.dumps(out)
        for k in ('R3', 'R5p', 'R15', 'R17'):
            if k not in keys:
                check(p[k]['id'] not in words and p[k]['title'] not in words, f'{col} never learns of {k}: {out}')
    for path in (f'/api/library/{lid}', '/api/library'):
        r = request(fx, 'dad', 'GET', path)
        hidden = [p[k] for k in ('R3', 'R15', 'R17')]
        check(r.status_code == 200 and not any(h['title'] in r.text or h['id'] in r.text for h in hidden),
              f"Dad's {path} names only what he sees: {r.text[:300]}")
        runners = access_fixture._runners_in(access_fixture._library_entry(r.json(), lid)
                                             if path == '/api/library' else r.json())
        check(runners and runners['hidden'] == 3
              and [n.get('project_id') for n in runners['named']] == [p['R5p']['id']],
              f'{path}: the runner projection Dad gets: {runners}')


def scenario_run_cells_and_keeper_gates_are_unchanged():
    fx = _build()
    _shared(fx)
    bad = []
    for key in PROGRAM_KEYS:
        kind, rec = load(fx, key)
        for col, want in zip(COLS, TABLE[key]):
            got = access.record_view(kind, rec, fx.viewers[col])
            if got != want:
                bad.append(f'{key} {col}: want {want} got {got}')
    check(not bad, '\n'.join(bad))
    _, r3 = load(fx, 'R3')
    check(access.record_actable('program', r3, fx.viewers['kid'], 'session'), 'a child keeper acts on her own run')
    check(not access.record_actable('program', r3, fx.viewers['dad'], 'session'), 'Dad does not')
    r = request(fx, 'kid', 'POST', f"/api/programs/{fx.ids['R3']}/approve", json={})
    check(r.status_code == 403, f'approval stays grown-up work: {r.status_code}')


def scenario_a_runs_starting_point_never_reaches_a_library_surface():
    fx = _build()
    lid = _shared(fx)
    secrets = [fx.secret(k) for k in PROGRAM_KEYS]
    for col in ('mom', 'dad', 'aunt', 'kid', 'hal'):
        for path in ['/api/library', f'/api/library/{lid}'] + [f'/api/library/{fx.library[k]}' for k in PROGRAM_KEYS]:
            r = request(fx, col, 'GET', path)
            check(r.status_code == 200 and not any(s in r.text for s in secrets), f'{col} {path}: {r.text[:200]}')
        out = json.dumps(_svc().runners(lid, fx.viewers[col]))
        check(not any(s in out for s in secrets), f'{col} runners: {out}')
    rows = json.dumps(storage.get_library_programs())
    check(not any(s in rows for s in secrets), 'and no library row holds one')


def scenario_register_discovers_the_library_routes():
    _build()
    served = {(m, getattr(r, 'path', '')) for r in main.app.routes for m in (getattr(r, 'methods', None) or [])}
    missing = [f'{rid[1]} {rid[2]}' for rid in LIBRARY_ROUTES if (rid[1], rid[2]) not in served]
    check(not missing, 'library routes not served:\n' + '\n'.join(missing))
    unclassified = [f'{rid[1]} {rid[2]}' for rid in LIBRARY_ROUTES if reg.resolve_route(rid[1], rid[2]) is None]
    check(not unclassified, 'library routes with no READERS row:\n' + '\n'.join(unclassified))
    for path in ('/api/library', '/api/library/{id}'):
        row = reg.resolve_route('GET', path)
        check(row[0] == ('route', 'GET', path) and row[2] == ('program',),
              f'runner-returning routes carry kinds (program,): {row}')
    import test_access_register as register
    for fn in register.SCENARIOS:
        fn()


def scenario_matrix_probes_match_the_library_table():
    fx = _build()
    probes = {}
    access_fixture.register_library(lambda rid: (lambda fn: probes.__setitem__(rid, fn)))
    bad = []
    for rid, what in LIBRARY_ROUTES.items():
        keys = PROGRAM_KEYS if what == 'read' else ('R5p', 'R15')
        for key in keys:
            for col in COLS:
                want = library_expected(rid, fx, key, col, None)
                try:
                    got = probes[rid](fx, key, col)
                except Exception as exc:
                    got = f'{type(exc).__name__}: {exc}'
                if got != want:
                    bad.append(f'{rid[1]} {rid[2]} {key} {col}: want {want} got {got}')
    check(not bad, '\n'.join(bad))


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
    print(f'\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed')
    raise SystemExit(bool(failed))
