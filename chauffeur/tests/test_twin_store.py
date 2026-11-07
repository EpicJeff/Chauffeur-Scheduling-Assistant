"""Twin plan storage: rounds, revert, the hand-edit log, drawing and photo
sources and the plan routes (spec docs/superpowers/specs/
2026-11-06-house-digital-twin-design.md sections 7, 8.1, 8.2; plan Task 2).

Run from chauffeur/:  python tests/test_twin_store.py
"""
import base64
import copy
import io
import json
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_store_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import storage  # noqa: E402


def check(cond, msg):
    # Local on purpose: tests/harness.py replaces storage.get_settings with a
    # fixed stub, which would hide every settings write this file checks.
    if not cond:
        raise AssertionError(msg)

from services import twin_plan as tp  # noqa: E402
from services import twin_store as ts  # noqa: E402
from services import twin_pdf  # noqa: E402

_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_poolhouse.plan.json')


def _plan():
    with open(_FIXTURE, encoding='utf-8') as f:
        return tp.normalize(json.load(f))[0]


def _fresh():
    storage.patch_settings({'house_twin': None})
    import shutil
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)


def _pdf(pages=2, w=792, h=612):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(w, h)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _png_size(b64):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64))).size


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def scenario_data_dir_sits_beside_the_database():
    check(ts.DATA_DIR == os.path.join(os.path.dirname(storage.DB_PATH), 'twin'), ts.DATA_DIR)


def scenario_pdf_pages_render():
    pages = twin_pdf.render_pages(_pdf(2, 1224, 792))      # 17x11 in at 72 pt/in
    check([p['page'] for p in pages] == [1, 2], 'pages numbered from 1')
    check(all(p['mime'] == 'image/png' for p in pages), 'png pages')
    w, h = _png_size(pages[0]['b64'])
    check(max(w, h) <= 2048 and w > h, f'long side capped at 2048, landscape kept: {w}x{h}')
    many = twin_pdf.render_pages(_pdf(20))
    check(len(many) == 16, f'at most 16 pages: {len(many)}')


def scenario_pdf_rejects_garbage():
    try:
        twin_pdf.render_pages(b'not a pdf')
    except ValueError:
        return
    raise AssertionError('garbage raises ValueError')


def scenario_rounds_push_and_revert():
    _fresh()
    a = _plan()
    b = copy.deepcopy(a)
    b['materials']['siding']['color'] = '#111111'
    check(ts.current() is None and ts.rounds() == [], 'empty to start')
    r1 = ts.push_round(a, 'draft', note='first', cost=0.5, run='run-1')
    r2 = ts.push_round(b, 'director', run='run-1')
    check(ts.current() == b, 'current is the latest round')
    r3 = ts.revert(r1)
    check(ts.current() == a, 'revert restores that plan')
    rows = ts.rounds()
    check([r['kind'] for r in rows] == ['draft', 'director', 'revert'], rows)
    check([r['id'] for r in rows] == [r1, r2, r3] and r1 < r2 < r3, 'ids increase')
    check(rows[0]['note'] == 'first' and rows[0]['cost'] == 0.5 and rows[0]['run'] == 'run-1', rows[0])
    check(os.path.exists(os.path.join(ts.DATA_DIR, 'rounds', f'{r1}.json')), 'plans live in files, not the settings row')
    try:
        ts.push_round(a, 'bogus')
    except ValueError:
        pass
    else:
        raise AssertionError('unknown round kind refused')


def scenario_a_stale_round_never_moves_current():
    _fresh()
    a = _plan()
    b = copy.deepcopy(a)
    b['materials']['siding']['color'] = '#333333'
    r1 = ts.push_round(a, 'draft')
    check(ts.current_id() == r1, 'current id tracks the latest round')
    r2 = ts.push_round(b, 'hand', base=r1)
    check(ts.current_id() == r2, 'a fresh base moves current')
    r3 = ts.push_round(a, 'director', base=r1)        # based on r1, but r2 landed first
    check(ts.current_id() == r2 and ts.current() == b, 'a stale result does not overwrite newer work')
    rows = {r['id']: r for r in ts.rounds()}
    check(rows[r3]['stale'] is True and rows[r2]['stale'] is False, 'the stale round is kept, flagged')
    c = copy.deepcopy(b)
    c['materials']['roof']['color'] = '#444444'
    try:
        ts.save_hand_edit(c, 'late edit', base=r1)
    except ts.StaleRound:
        pass
    else:
        raise AssertionError('a hand edit on a stale base raises StaleRound')
    check(ts.current() == b and ts.fixes() == [], 'nothing logged for a refused edit')


def scenario_concurrent_pushes_get_unique_ids():
    import threading
    _fresh()
    a = _plan()
    ids, errs = [], []

    def push():
        try:
            ids.append(ts.push_round(a, 'hand'))
        except Exception as e:      # noqa: BLE001
            errs.append(e)
    threads = [threading.Thread(target=push) for _ in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check(not errs and len(set(ids)) == 12, f'twelve unique ids: {ids} {errs}')
    check(len(ts.rounds()) == 12, 'twelve rounds recorded')
    for i in ids:
        check(os.path.exists(os.path.join(ts.DATA_DIR, 'rounds', f'{i}.json')), f'round file {i}')


def scenario_hand_edits_log_each_changed_leaf():
    _fresh()
    a = _plan()
    ts.push_round(a, 'draft')
    b = copy.deepcopy(a)
    b['materials']['siding']['color'] = '#222222'
    b['buildings'][0]['walls'][2]['height'] = 9.5
    rid = ts.save_hand_edit(b, 'drawing says 9-6 at the rear')
    fixes = ts.fixes()
    check(sorted(f['path'] for f in fixes) == ['buildings[id=pool_house].walls[id=rear].height', 'materials.siding.color'], fixes)
    check(all(f['kind'] == 'extraction' for f in fixes), 'building and material fixes are extraction misses')
    wall = [f for f in fixes if f['path'].endswith('height')][0]
    check(wall['before'] == a['buildings'][0]['walls'][2]['height'] and wall['after'] == 9.5, wall)
    check(all(f['reason'] == 'drawing says 9-6 at the rear' and f['round'] == rid for f in fixes), fixes)
    check(ts.rounds()[-1]['kind'] == 'hand' and ts.current()['materials']['siding']['color'] == '#222222', 'hand round current')


def scenario_hand_edits_record_compose_overrides():
    from services import twin_compose, twin_library
    _fresh()
    plan, _ = twin_compose.compose(_plan(), twin_library.kit('modern_farmhouse'), seed=2)
    rid = ts.push_round(plan, 'draft')
    shrubs = [i for i in plan['site']['planting'] if i.get('by') == 'compose' and i['kind'] == 'shrub']
    edited = copy.deepcopy(plan)
    edited['site']['planting'] = [i for i in edited['site']['planting'] if i.get('id') != shrubs[0]['id']]
    ts.save_hand_edit(edited, 'that shrub blocks the hose bib', base=rid)
    ov = ts.current()['site']['compose_overrides']
    check(shrubs[0]['id'] in ov['removed'], f'a hand deletion of a compose item is remembered: {ov}')


def _js_round_trip(obj):
    # JSON.stringify/parse in the browser turns 6.0 into 6
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _js_round_trip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_js_round_trip(v) for v in obj]
    return obj


def scenario_an_unchanged_editor_save_logs_nothing():
    _fresh()
    rid = ts.push_round(_plan(), 'draft')
    ts.save_hand_edit(_js_round_trip(ts.current()), 'no change', base=rid)
    check(ts.fixes() == [], f'the editor round trip is not an extraction miss: {len(ts.fixes())} fixes')


def scenario_deleting_one_item_logs_one_fix():
    from services import twin_compose, twin_library
    _fresh()
    plan, _ = twin_compose.compose(_plan(), twin_library.kit('modern_farmhouse'), seed=2)
    rid = ts.push_round(plan, 'draft')
    edited = copy.deepcopy(plan)
    edited['buildings'][0]['walls'] = [w for w in edited['buildings'][0]['walls'] if w['id'] != 'stair_wall']
    shrub = next(i for i in edited['site']['planting'] if i.get('by') == 'compose')
    edited['site']['planting'] = [i for i in edited['site']['planting'] if i is not shrub]
    ts.save_hand_edit(edited, 'no stair wall; drop a shrub', base=rid)
    fixes = ts.fixes()
    check(len(fixes) == 2, f'one fix per deleted item: {[f["path"] for f in fixes]}')
    wall = next(f for f in fixes if 'walls' in f['path'])
    plant = next(f for f in fixes if 'planting' in f['path'])
    check(wall['kind'] == 'extraction' and wall['after'] is None and wall['before']['id'] == 'stair_wall', wall)
    check(plant['kind'] == 'yard', 'yard edits are not counted as extraction misses')
    check(not any('compose_overrides' in f['path'] for f in fixes), 'derived override bookkeeping is not a fix')


def scenario_photos_are_stored_upright_and_model_sized():
    from PIL import Image
    _fresh()
    im = Image.new('RGB', (4000, 3000), (120, 130, 140))
    exif = im.getexif()
    exif[0x0112] = 6                                  # rotate 90: shown portrait
    buf = io.BytesIO()
    im.save(buf, format='JPEG', exif=exif.tobytes())
    sid = ts.save_source('photo', 'phone.jpg', buf.getvalue())
    out = ts.source_images(sid)[0]
    w, h = _png_size(out['b64'])
    check(out['mime'] == 'image/jpeg' and max(w, h) <= 2048 and h > w, f'upright, at most 2048 px: {w}x{h}')


def scenario_long_drawing_sets_report_what_was_kept():
    _fresh()
    sid = ts.save_source('drawing', 'big set.pdf', _pdf(20))
    row = next(s for s in ts.sources() if s['id'] == sid)
    check(row['pages'] == 16 and row['total_pages'] == 20, row)


def scenario_sources_store_pages_and_photos():
    _fresh()
    sid = ts.save_source('drawing', 'pool house.pdf', _pdf(3))
    pid = ts.save_source('photo', 'dusk.jpg', base64.b64decode(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=='))
    rows = {s['id']: s for s in ts.sources()}
    check(rows[sid]['kind'] == 'drawing' and rows[sid]['pages'] == 3 and rows[sid]['filename'] == 'pool house.pdf', rows[sid])
    check(rows[pid]['kind'] == 'photo' and rows[pid]['pages'] == 1, rows[pid])
    two = ts.source_images(sid, [1, 3])
    check(len(two) == 2 and all(i['mime'] == 'image/png' and i['b64'] for i in two), 'chosen pages only')
    check(len(ts.source_images(sid)) == 3, 'all pages by default')
    photo = ts.source_images(pid)
    check(len(photo) == 1 and photo[0]['mime'] == 'image/jpeg', photo and photo[0]['mime'])
    try:
        ts.save_source('drawing', 'x.pdf', b'garbage')
    except ValueError:
        pass
    else:
        raise AssertionError('an unreadable drawing raises ValueError')


def _img_bytes(fmt, frames=1):
    from PIL import Image
    buf = io.BytesIO()
    ims = [Image.new('RGB', (8, 8), (i * 40, 90, 120)) for i in range(frames)]
    if frames > 1:
        ims[0].save(buf, format=fmt, save_all=True, append_images=ims[1:])
    else:
        ims[0].save(buf, format=fmt)
    return buf.getvalue()


def scenario_photos_are_checked_by_content_not_name():
    _fresh()
    png_as_jpg = ts.save_source('photo', 'dusk.jpg', _img_bytes('PNG'))
    check(ts.source_images(png_as_jpg)[0]['mime'] == 'image/jpeg', 'PNG bytes named .jpg are accepted and stored as the JPEG model copy')
    mpo = ts.save_source('photo', 'phone.jpg', _img_bytes('MPO', frames=2))
    check(ts.source_images(mpo)[0]['mime'] == 'image/jpeg', 'a multi-picture (MPO) phone JPEG is accepted as JPEG')
    for bad, name in ((b'not an image', 'x.jpg'), (_img_bytes('GIF'), 'x.png')):
        try:
            ts.save_source('photo', name, bad)
        except ValueError:
            continue
        raise AssertionError(f'{name} with non-JPEG/PNG content raises ValueError')


def scenario_rendering_a_drawing_does_not_block_reads():
    import threading
    import time
    _fresh()
    ts.push_round(_plan(), 'draft')
    entered, release = threading.Event(), threading.Event()
    orig = twin_pdf.render_pages

    def slow(data, *a, **k):
        entered.set()
        release.wait(10)
        return orig(data, *a, **k)
    ts.twin_pdf.render_pages = slow
    try:
        t = threading.Thread(target=lambda: ts.save_source('drawing', 'big.pdf', _pdf(1)))
        t.start()
        check(entered.wait(10), 'render started')
        t0 = time.monotonic()
        check(ts.current() is not None and ts.rounds(), 'reads answer while a drawing renders')
        check(time.monotonic() - t0 < 1.0, 'and answer promptly')
        release.set()
        t.join(10)
    finally:
        ts.twin_pdf.render_pages = orig
        release.set()
    check(len(ts.sources()) == 1, 'the upload still completes')


def scenario_routes_round_trip_through_the_app():
    _fresh()
    c = _client()
    r = c.post('/api/house/twin/sources', data={'kind': 'drawing'},
               files={'file': ('sheets.pdf', _pdf(2), 'application/pdf')})
    check(r.status_code == 200 and r.json()['pages'] == 2, f'{r.status_code} {r.text}')
    r = c.get('/api/house/twin/sources')
    check(r.status_code == 200 and len(r.json()['sources']) == 1, r.text)
    plan = _plan()
    r = c.put('/api/house/twin/plan', json={'plan': plan, 'reason': 'first hand save'})
    check(r.status_code == 200 and isinstance(r.json()['round'], int), r.text)
    r = c.get('/api/house/twin')
    body = r.json()
    check(r.status_code == 200 and body['plan'] == plan and len(body['rounds']) == 1
          and body['kit_id'] == 'modern_farmhouse', r.text[:300])
    p2 = copy.deepcopy(plan)
    p2['materials']['roof']['color'] = '#000000'
    rid2 = c.put('/api/house/twin/plan', json={'plan': p2, 'reason': 'roof is darker'}).json()['round']
    r = c.get('/api/house/twin/fixes')
    check(r.status_code == 200 and [f['path'] for f in r.json()['fixes']] == ['materials.roof.color'], r.text)
    first = c.get('/api/house/twin').json()['rounds'][0]['id']
    r = c.post('/api/house/twin/revert', json={'round': first})
    check(r.status_code == 200 and c.get('/api/house/twin').json()['plan'] == plan, r.text)
    check(rid2 > first, 'ids increase through the routes')


def scenario_bad_requests_are_400s_not_500s():
    _fresh()
    c = _client()
    r = c.post('/api/house/twin/sources', data={'kind': 'drawing'},
               files={'file': ('x.pdf', b'garbage', 'application/pdf')})
    check(r.status_code == 400, f'unreadable pdf: {r.status_code}')
    r = c.post('/api/house/twin/sources', data={'kind': 'video'},
               files={'file': ('x.mp4', b'1234', 'video/mp4')})
    check(r.status_code == 400, f'unknown kind: {r.status_code}')
    r = c.put('/api/house/twin/plan', json={'plan': {'units': 'm'}, 'reason': 'x'})
    check(r.status_code == 400, f'invalid plan: {r.status_code}')
    r = c.put('/api/house/twin/plan', json={'plan': _plan(), 'reason': ''})
    check(r.status_code == 400, f'a hand save needs a reason: {r.status_code}')
    r = c.post('/api/house/twin/revert', json={'round': 999})
    check(r.status_code == 404, f'unknown round: {r.status_code}')
    first = c.put('/api/house/twin/plan', json={'plan': _plan(), 'reason': 'seed'}).json()['round']
    c.put('/api/house/twin/plan', json={'plan': _plan(), 'reason': 'second', 'base': first})
    r = c.put('/api/house/twin/plan', json={'plan': _plan(), 'reason': 'late', 'base': first})
    check(r.status_code == 409, f'a stale base is a 409: {r.status_code}')
    _fresh()
    r = c.get('/api/house/twin')
    check(r.status_code == 200 and r.json()['plan'] is None, 'empty twin is a 200 with no plan')


def scenario_junk_plans_are_400s_once_a_plan_exists():
    _fresh()
    c = _client()
    c.put('/api/house/twin/plan', json={'plan': _plan(), 'reason': 'seed'})
    for junk in (None, [], 'x', {'site': 'junk'}, {'site': [1]}, {'site': None}, {'site': {'planting': 5}}):
        r = c.put('/api/house/twin/plan', json={'plan': junk, 'reason': 'junk'})
        check(r.status_code == 400, f'{junk!r} with a current round -> {r.status_code}')


def scenario_uploads_over_40mb_are_413():
    c = _client()
    r = c.post('/api/house/twin/sources', data={'kind': 'photo'},
               files={'file': ('big.jpg', b'\xff' * (40 * 1024 * 1024 + 1), 'image/jpeg')})
    check(r.status_code == 413, f'{r.status_code}')


def scenario_auth_rules_are_declared():
    from services import auth
    want = {('GET', '/api/house/twin'): auth.WALL_OR_SERVICE,
            ('POST', '/api/house/twin/sources'): auth.PARENTS,
            ('GET', '/api/house/twin/sources'): auth.PARENTS,
            ('PUT', '/api/house/twin/plan'): auth.PARENTS,
            ('POST', '/api/house/twin/revert'): auth.PARENTS,
            ('GET', '/api/house/twin/fixes'): auth.PARENTS}
    for (m, p), tier in want.items():
        check(auth.resolve(m, p) == tier, f'{m} {p} -> {auth.resolve(m, p)}')


if __name__ == '__main__':
    for fn in (scenario_data_dir_sits_beside_the_database,
               scenario_pdf_pages_render,
               scenario_pdf_rejects_garbage,
               scenario_rounds_push_and_revert,
               scenario_a_stale_round_never_moves_current,
               scenario_concurrent_pushes_get_unique_ids,
               scenario_hand_edits_log_each_changed_leaf,
               scenario_an_unchanged_editor_save_logs_nothing,
               scenario_deleting_one_item_logs_one_fix,
               scenario_photos_are_stored_upright_and_model_sized,
               scenario_long_drawing_sets_report_what_was_kept,
               scenario_hand_edits_record_compose_overrides,
               scenario_sources_store_pages_and_photos,
               scenario_photos_are_checked_by_content_not_name,
               scenario_rendering_a_drawing_does_not_block_reads,
               scenario_routes_round_trip_through_the_app,
               scenario_bad_requests_are_400s_not_500s,
               scenario_junk_plans_are_400s_once_a_plan_exists,
               scenario_uploads_over_40mb_are_413,
               scenario_auth_rules_are_declared):
        fn()
        print('  ok ', fn.__name__)
