"""Household materials through the real HTTP, image decode and house history paths."""
import hashlib
import io
import json
import struct
import zlib
from pathlib import Path
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from PIL import Image
from test_twin_ha_routes import Ctx, seed, ts
from services import auth, twin_library as library, twin_materials as materials

API = '/api/house/materials'


def test_successful_material_writes_push_update_but_reads_and_errors_do_not():
    import main
    seed()
    with Ctx() as c:
        def write(call):
            main.LAST_UPDATE_TIME = 0
            response = call()
            assert response.status_code == 200, response.text
            assert main.LAST_UPDATE_TIME > 0, 'material write must signal the existing SSE update'
            return response.json()
        row = write(lambda: c.client.post(API, headers=c.mum, json={'name': 'Live'}))
        mid = row['id']
        write(lambda: c.client.patch(f'{API}/{mid}', headers=c.mum, json={'params': {'tint': '#123456'}}))
        write(lambda: upload(c, mid))
        write(lambda: c.client.delete(f'{API}/{mid}/maps/base_color', headers=c.mum))
        write(lambda: c.client.post(f'{API}/{mid}/undo', headers=c.mum))
        write(lambda: c.client.post(f'{API}/{mid}/redo', headers=c.mum))
        duplicate = write(lambda: c.client.post(f'{API}/{mid}/duplicate', headers=c.mum))
        write(lambda: c.client.post(f"{API}/{duplicate['id']}/reset", headers=c.mum))
        main.LAST_UPDATE_TIME = 0
        assert c.client.get(API, headers=c.mum).status_code == 200
        assert c.client.get(f'{API}/{mid}', headers=c.mum).status_code == 200
        assert c.client.patch(f'{API}/{mid}', headers=c.mum, json={'params': {'tint': 'bad'}}).status_code == 400
        assert main.LAST_UPDATE_TIME == 0
        write(lambda: c.client.delete(f'{API}/{mid}', headers=c.mum))


def image(size=(64, 64), color=(90, 120, 150), fmt='PNG'):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format=fmt)
    return out.getvalue()


def create(c, **fields):
    r = c.client.post(API, headers=c.mum, json={'name': 'My brick', **fields})
    assert r.status_code == 200, r.text
    return r.json()


def upload(c, mid, data=None, slot='base_color'):
    return c.client.post(f'{API}/{mid}/maps/{slot}', headers=c.mum,
                         content=image() if data is None else data)


def file_url(record, slot='base_color'):
    return f"/api/house/twin/materials/{record['id']}/{record['maps'][slot]}"


def test_catalogue_lists_twelve_builtins_first_read_only():
    seed()
    with Ctx() as c:
        row = create(c)
        catalogue = c.client.get(API, headers=c.mum).json()
        builtins = catalogue['materials'][:12]
        assert all(r['builtin'] and r['revision'] == 0 and r['source'] == 'builtin' for r in builtins)
        assert {r['id'] for r in builtins} == {k for k, e in library.manifest().items() if e['kind'] == 'material'}
        assert catalogue['materials'][-1]['id'] == row['id']
        assert c.client.patch(f"{API}/{builtins[0]['id']}", headers=c.mum, json={'name': 'No'}).status_code == 400
        assert library.material_slot_error({'id': 'siding', 'color': '#123456'}) is None


def test_create_ingest_and_serve_immutable_map():
    seed()
    with Ctx() as c:
        row = create(c)
        assert row['params'] == dict(tint='#ffffff', roughness=None, metalness=None, normal_scale=1,
                                    normal_convention='gl', ao_intensity=1, tile_ft=[4, 4],
                                    rotation_deg=0, random_offset=False)
        assert row['created_by'] == 'mum'
        r = upload(c, row['id'])
        assert r.status_code == 200, r.text
        row = r.json()
        response = c.client.get(file_url(row), headers=c.panel)
        assert response.status_code == 200, response.text
        assert 'immutable' in response.headers['cache-control']
        assert Path(row['maps']['base_color']).name == hashlib.sha256(response.content).hexdigest()[:12] + '.jpg'
        assert Image.open(io.BytesIO(response.content)).size == (64, 64)
        assert (materials.root() / row['id'] / row['maps']['base_color']).is_file()


def test_update_keeps_id_and_bumps_revision():
    seed()
    with Ctx() as c:
        row = create(c)
        before = materials.catalogue()['revision']
        changed = c.client.patch(f"{API}/{row['id']}", headers=c.mum, json={'params': {'tint': '#123456'}}).json()
        assert changed['id'] == row['id'] and changed['revision'] == row['revision'] + 1
        assert materials.catalogue()['revision'] > before
        assert changed['params']['tile_ft'] == [4, 4]
        undone = c.client.post(f"{API}/{row['id']}/undo", headers=c.mum).json()
        assert undone['params']['tint'] == '#ffffff' and undone['revision'] > changed['revision']
        redone = c.client.post(f"{API}/{row['id']}/redo", headers=c.mum).json()
        assert redone['params']['tint'] == '#123456' and redone['revision'] > undone['revision']
        assert (materials.root() / row['id'] / 'revisions' / f"{row['revision']}.json").is_file()
        assert ts.current_id() == 2, 'material edits do not add house rounds'


def test_bad_images_refused_nothing_published():
    seed()
    with Ctx() as c:
        row = create(c)
        folder = materials.root() / row['id'] / 'maps'
        assert upload(c, row['id'], image(fmt='JPEG')[:-40]).status_code == 400
        assert not list(folder.glob('*'))
        r = upload(c, row['id'], image((5000, 5000)), slot='normal')
        assert r.status_code == 200, r.text
        data = c.client.get(file_url(r.json(), 'normal'), headers=c.mum).content
        assert Image.open(io.BytesIO(data)).size == (4096, 4096)
        assert r.json()['maps']['normal'].endswith('.png')
        assert upload(c, row['id'], image(color=(0, 0, 0))).status_code == 200, 'identical bytes reuse the immutable file'
        before = sorted(folder.iterdir())
        assert upload(c, row['id'], image(color=(0, 0, 0))).status_code == 200
        assert sorted(folder.iterdir()) == before


def test_delete_in_use_refused_history_archives():
    seed()
    with Ctx() as c:
        row = create(c)
        row = upload(c, row['id']).json()
        def assign(mid):
            r = c.client.post('/api/house/editor/op', headers=c.mum, json={'op': {
                'op': 'set_material', 'building': 'B1', 'target': {'wall': 's1', 'side': 'left'}, 'material': {'id': mid}}})
            assert r.status_code == 200, r.text
        assign(row['id'])
        used_round = ts.current_id()
        r = c.client.delete(f"{API}/{row['id']}", headers=c.mum)
        assert r.status_code == 400 and 'Used on' in r.text
        assert materials.uses(row['id'])['current']
        assign('red_brick_03')
        r = c.client.delete(f"{API}/{row['id']}", headers=c.mum)
        assert r.status_code == 200 and r.json() == {'archived': True}, r.text
        assert row['id'] not in [r['id'] for r in materials.catalogue()['materials']]
        assert row['id'] in [r['id'] for r in materials.catalogue(True)['materials']]
        ts.revert(used_round)
        assert ts.current_model()['buildings'][0]['walls'][0]['faces']['left']['id'] == row['id']
        assert library.material_slot_error({'id': row['id']}) is None
        assert c.client.get(file_url(row), headers=c.panel).status_code == 200


def test_duplicate_builtin_and_reset_to_source():
    seed()
    with Ctx() as c:
        aid = 'red_brick_03'
        cached = Path(ts.DATA_DIR) / 'library' / aid
        cached.mkdir(parents=True)
        for name in library.manifest()[aid]['files']:
            (cached / name).write_bytes(image())
        with patch.object(library, 'ensure', return_value=str(cached)):
            r = c.client.post(f'{API}/{aid}/duplicate', headers=c.mum)
        assert r.status_code == 200, r.text
        row = r.json()
        assert row['based_on'] == aid and row['source'] == 'user'
        assert set(row['maps']) == {'base_color', 'normal', 'roughness'}
        assert row['params']['tint'] == materials.get(aid)['params']['tint']
        assert all((materials.root() / row['id'] / name).is_file() for name in row['maps'].values())
        assert c.client.patch(f"{API}/{row['id']}", headers=c.mum, json={'params': {'tint': '#abcdef'}}).status_code == 200
        assert c.client.delete(f"{API}/{row['id']}/maps/normal", headers=c.mum).status_code == 200
        reset = c.client.post(f"{API}/{row['id']}/reset", headers=c.mum).json()
        assert reset['maps'] == row['maps'] and reset['params'] == row['params']
        duplicate = materials.duplicate(row['id'], 'mum')
        assert duplicate['id'] != row['id'] and duplicate['based_on'] == row['id']
        assert all((materials.root() / duplicate['id'] / f).is_file() for f in duplicate['maps'].values())


def test_parents_only():
    seed()
    with Ctx() as c:
        row = create(c)
        path = f"{API}/{row['id']}"
        writes = [('POST', API), ('PATCH', path), ('POST', path + '/duplicate'),
                  ('POST', path + '/maps/base_color'), ('DELETE', path + '/maps/base_color'),
                  *[('POST', path + '/' + op) for op in ('undo', 'redo', 'reset')], ('DELETE', path)]
        for headers in (c.kid, c.panel):
            for method, url in writes:
                r = c.client.request(method, url, headers=headers, json={})
                assert r.status_code in (401, 403), (method, url, r.status_code, r.text)
            for url in (API, path):
                assert c.client.get(url, headers=headers).status_code in (401, 403)
        for method, url in writes + [('GET', API), ('GET', path)]:
            template = url.replace(row['id'], '{id}').replace('/maps/base_color', '/maps/{slot}')
            assert auth.resolve(method, template) == auth.PARENTS, (method, template)
        assert auth.resolve('GET', '/api/house/twin/materials/{id}/{file:path}') == auth.WALL_OR_SERVICE


def test_nullable_auto_params_and_validation():
    seed()
    with Ctx() as c:
        row = create(c, params={'roughness': None, 'metalness': None})
        path = f"{API}/{row['id']}"
        for value in (0, 2, None):
            r = c.client.patch(path, headers=c.mum, json={'params': {'roughness': value, 'metalness': value}})
            assert r.status_code == 200, r.text
            assert r.json()['params']['roughness'] == value
            assert r.json()['params']['metalness'] == value
        for key in ('roughness', 'metalness'):
            for value in (-.01, 2.01, 'auto', True):
                r = c.client.patch(path, headers=c.mum, json={'params': {key: value}})
                assert r.status_code == 400, (key, value, r.text)
        for key in ('normal_scale', 'ao_intensity', 'rotation_deg'):
            assert c.client.patch(path, headers=c.mum, json={'params': {key: None}}).status_code == 400


def test_duplicate_of_builtin_keeps_its_roughness():
    seed()
    with Ctx() as c:
        for aid, roughness, metalness in (('red_brick_03', .85, 0), ('granite_tile', .22, 0), ('standing_seam', .45, .45)):
            cached = Path(ts.DATA_DIR) / 'library' / aid
            cached.mkdir(parents=True)
            for name in library.manifest()[aid].get('files', {}):
                (cached / name).write_bytes(image())
            with patch.object(library, 'ensure', return_value=str(cached)):
                r = c.client.post(f'{API}/{aid}/duplicate', headers=c.mum)
            assert r.status_code == 200, r.text
            row = r.json()
            assert row['params']['roughness'] == roughness, (aid, row['params'])
            assert row['params']['metalness'] == metalness, (aid, row['params'])
            assert row['source_snapshot']['params'] == row['params']
            copied = materials.duplicate(row['id'], 'mum')
            assert copied['params'] == row['params'], 'household duplicate preserves explicit values'


def test_page_manifest_carries_household_material():
    seed()
    with Ctx() as c:
        row = upload(c, create(c)['id']).json()
        entry = materials.page_manifest()[row['id']]
        assert entry == {'kind': 'material', 'household': True, 'revision': row['revision'],
                         'maps': {s: f"materials/{row['id']}/{f}" for s, f in row['maps'].items()}, 'params': row['params']}
        for page in ('/house/editor', '/house/twin'):
            r = c.client.get(page, headers=c.mum)
            assert r.status_code == 200 and 'window.twinManifest' in r.text and row['id'] in r.text, r.text[:500]


def test_validation_limits_and_unreferenced_delete():
    seed()
    with Ctx() as c:
        row = create(c)
        path = f"{API}/{row['id']}"
        for params in ({'roughness': 3}, {'metalness': -1}, {'normal_scale': 5}, {'ao_intensity': 3},
                       {'tile_ft': [0, 4]}, {'rotation_deg': 360}, {'tint': 'red'},
                       {'normal_convention': 'bad'}, {'random_offset': 1}, {'roughness': '1'}, {'unknown': 1}):
            assert c.client.patch(path, headers=c.mum, json={'params': params}).status_code == 400, params
        for change in ({'id': 'changed'}, {'maps': {'normal': '../outside.png'}}, {'source': 'builtin'}):
            assert c.client.patch(path, headers=c.mum, json=change).status_code == 400, change
        assert upload(c, row['id'], slot='unknown').status_code == 400
        with patch.object(materials, 'MAX_INPUT_BYTES', 10):
            assert upload(c, row['id']).status_code == 400
        with patch.object(materials, 'MAX_MATERIAL_BYTES', 10):
            assert upload(c, row['id']).status_code == 400
        assert not list((materials.root() / row['id'] / 'maps').glob('*'))
        assert c.client.post(path + '/undo', headers=c.mum).status_code == 400
        before = materials.catalogue()['revision']
        assert c.client.delete(path, headers=c.mum).json() == {'archived': False}
        assert not (materials.root() / row['id']).exists()
        assert materials.catalogue()['revision'] > before


def test_saved_house_references_archive_and_redo_branch():
    seed()
    with Ctx() as c:
        row = create(c)
        # A saved house alone retains the bytes even when no round uses the id.
        from services import twin_house_saves as saves
        document = saves.current_document('Material fixture', 'mum')
        document['model']['buildings'][0]['materials']['siding'] = {'id': row['id']}
        saves._write(document)
        assert materials.uses(row['id']) == {'current': [], 'history': True}
        assert materials.delete(row['id'], 'mum') == {'archived': True}
        assert row['id'] in materials.page_manifest()
        other = create(c)
        materials.update(other['id'], {'params': {'roughness': 0.5}}, 'mum')
        materials.undo(other['id'])
        materials.update(other['id'], {'params': {'metalness': 0}}, 'mum')
        try:
            materials.redo(other['id'])
        except ValueError:
            pass
        else:
            raise AssertionError('editing after undo clears redo')


def test_chunk_upload_reuses_model_upload_transport():
    seed()
    with Ctx() as c:
        row = create(c)
        data = image()
        endpoint = '/api/house/editor/imports/uploads'
        body = {'name': 'Texture', 'size': len(data), 'files': [{'name': 'color.png', 'size': len(data)}],
                'material_id': row['id'], 'slot': 'base_color', 'material_actor': 'forged'}
        for headers in (c.kid, c.panel):
            assert c.client.post(endpoint, headers=headers, json=body).status_code in (401, 403)
        r = c.client.post(endpoint, headers=c.mum, json=body)
        assert r.status_code == 200, r.text
        upload_id = r.json()['upload_id']
        upload_path = endpoint + '/' + upload_id
        assert c.client.put(upload_path + '/0', headers=c.mum, content=data[:20]).status_code == 200
        assert c.client.post(upload_path + '/finish', headers=c.mum).status_code == 400
        assert c.client.put(upload_path + '/1', headers=c.mum, content=data[20:]).status_code == 200
        r = c.client.post(upload_path + '/finish', headers=c.mum)
        assert r.status_code == 200, r.text
        assert r.json()['maps']['base_color'].endswith('.jpg')
        assert r.json()['created_by'] == 'mum'
        from services import twin_imports
        assert not (twin_imports.root() / '.uploads' / upload_id).exists()
        body['size'] = body['files'][0]['size'] = materials.MAX_INPUT_BYTES + 1
        assert c.client.post(endpoint, headers=c.mum, json=body).status_code == 400


def test_concurrent_updates_preserve_independent_params_and_revision_counter():
    seed()
    row = materials.create({'name': 'Concurrent'}, 'mum')
    before = materials.catalogue()['revision']
    changes = [{'params': {'roughness': 0.4}}, {'params': {'metalness': 0.3}},
               {'params': {'ao_intensity': 0.2}}, {'params': {'normal_scale': 2}}]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda change: materials.update(row['id'], change, 'mum'), changes))
    current = materials.get(row['id'])
    assert current['revision'] == row['revision'] + len(changes)
    assert sorted(r['revision'] for r in results) == list(range(2, 6))
    assert materials.catalogue()['revision'] == before + len(changes)
    for change in changes:
        assert all(current['params'][key] == value for key, value in change['params'].items())


def test_iteration_never_locks_a_material():
    seed()
    with Ctx() as c:
        row = create(c)
        folder = materials.root() / row['id']
        assert materials.MAX_FILES == 16
        with patch.object(materials, 'MAX_MATERIAL_BYTES', 2048):
            for n in range(30):
                r = upload(c, row['id'], image(color=(n * 8, 30, 50)))
                assert r.status_code == 200, (n, r.text)
                assert len(list((folder / 'maps').glob('*'))) <= 20
                assert len(list((folder / 'revisions').glob('*.json'))) <= 20
                for snapshot in (folder / 'revisions').glob('*.json'):
                    record = json.loads(snapshot.read_text(encoding='utf-8'))
                    assert all((folder / filename).is_file() for filename in record['maps'].values())


def test_patch_cannot_archive_or_relabel():
    seed()
    with Ctx() as c:
        row = create(c)
        path = f"{API}/{row['id']}"
        for fields in ({'archived': True}, {'archived': False}, {'source': 'polyhaven'},
                       {'source': 'user'}, {'source_snapshot': None},
                       {'source_snapshot': {'maps': {}, 'params': row['params']}}):
            assert c.client.patch(path, headers=c.mum, json=fields).status_code == 400, fields
            assert c.client.post(API, headers=c.mum, json={'name': 'Forged', **fields}).status_code == 400, fields
        assert materials.get(row['id']) == row


def test_huge_dimensions_refused_before_decode():
    seed()
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    with Ctx() as c:
        row = create(c)
        for width, height in ((12000, 12000), (16385, 1)):
            data = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 0, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(b'\x00\x00')) + chunk(b'IEND', b''))
            assert len(data) < 1024
            from PIL import PngImagePlugin
            with patch.object(PngImagePlugin.PngImageFile, 'load', side_effect=AssertionError('decoded huge image')) as load:
                r = upload(c, row['id'], data, 'height')
            assert r.status_code == 400, r.text
            assert not load.called, 'dimensions must be refused before pixel allocation'
        assert not list((materials.root() / row['id'] / 'maps').glob('*'))


def test_sixteen_bit_height_scaled_not_clipped():
    seed()
    with Ctx() as c:
        row = create(c)
        for mode, fmt in (('I;16', 'PNG'), ('I', 'TIFF')):
            source = (Image.frombytes(mode, (2, 1), struct.pack('<HH', 65535, 32768)) if mode == 'I;16'
                      else Image.frombytes(mode, (2, 1), struct.pack('<ii', 65535, 32768)))
            stream = io.BytesIO()
            source.save(stream, format=fmt)
            r = upload(c, row['id'], stream.getvalue(), 'height')
            assert r.status_code == 200, r.text
            data = c.client.get(file_url(r.json(), 'height'), headers=c.mum).content
            decoded = Image.open(io.BytesIO(data)).convert('L')
            pixels = [decoded.getpixel((x, 0)) for x in range(2)]
            assert pixels[0] == 255 and abs(pixels[1] - 128) <= 1, (mode, pixels)


def test_file_get_404s():
    seed()
    with Ctx() as c:
        row = create(c)
        for mid in (row['id'], 'red_brick_03', 'material-missing'):
            r = c.client.get(f'/api/house/twin/materials/{mid}/maps/000000000000.png', headers=c.panel)
            assert r.status_code == 404, (mid, r.text)
            assert 'immutable' not in r.headers.get('cache-control', '')


def test_public_builtin_and_editable_helpers():
    seed()
    row = materials.create({'name': 'Editable'}, 'mum')
    assert materials.builtin_rows()[:12] == materials.catalogue()['materials'][:12]
    assert materials.require_editable(row['id']) == row
    try:
        materials.require_editable('red_brick_03')
    except ValueError as exc:
        assert 'read-only' in str(exc)
    else:
        raise AssertionError('built-in is editable')


def test_usage_refusal_groups_named_surfaces_and_counts():
    seed()
    with Ctx() as c:
        row = create(c)
        def assign(model):
            building = model['buildings'][0]
            building['name'] = 'Main House'
            for wall in building['walls'][:2]:
                wall['faces'] = {'left': {'id': row['id']}}
            model['site']['fence'] = [{'id': 'fence', 'name': 'Fence', 'height': 6,
                                       'polyline': [[2, 2], [30, 2]], 'materials': {'boards': {'id': row['id']}}}]
            return model
        ts.update_model(assign, state_mutator=lambda state: state['place']['buildings'][0].update(name='Main House'))
        r = c.client.delete(f"{API}/{row['id']}", headers=c.mum)
        assert r.status_code == 400, r.text
        assert r.json()['detail'] == 'Used on 3 surfaces: Main House walls (2), Fence boards (1)', r.text


def test_live_bytes_over_cap_refused():
    seed()
    with Ctx() as c:
        row = upload(c, create(c)['id']).json()
        folder = materials.root() / row['id'] / 'maps'
        before = sorted(folder.iterdir())
        revision = materials.catalogue()['revision']
        with patch.object(materials, 'MAX_MATERIAL_BYTES', 10):
            r = upload(c, row['id'], image(color=(240, 0, 0)))
        assert r.status_code == 400 and '200 MB' in r.text
        assert sorted(folder.iterdir()) == before
        assert materials.get(row['id']) == row
        assert materials.catalogue()['revision'] == revision


def test_gc_keeps_source_and_all_retained_undo_redo_maps():
    seed()
    original = materials.create({'name': 'Source'}, 'mum')
    original = materials.set_image(original['id'], 'base_color', image(), 'mum')
    row = materials.duplicate(original['id'], 'mum')
    folder = materials.root() / row['id']
    source_file = row['maps']['base_color']
    for n in range(30):
        materials.set_image(row['id'], 'base_color', image(color=(n * 8, 0, 80)), 'mum')
    assert len(list((folder / 'revisions').glob('*.json'))) == 20
    assert len(list((folder / 'maps').glob('*'))) == 21, 'source plus twenty retained states'
    assert (folder / source_file).is_file(), 'source survives eviction of its initial revision'
    for _ in range(19):
        undone = materials.undo(row['id'])
        assert all((folder / filename).is_file() for filename in undone['maps'].values())
    try:
        materials.undo(row['id'])
    except ValueError:
        pass
    else:
        raise AssertionError('undo escaped retained snapshots')
    for _ in range(19):
        redone = materials.redo(row['id'])
        assert all((folder / filename).is_file() for filename in redone['maps'].values())
    reset = materials.reset_to_source(row['id'], 'mum')
    assert reset['maps'] == row['maps']
    assert (folder / source_file).is_file()


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=8)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
