"""Models mode server contract through HTTP and real object operations."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

DATA = tempfile.TemporaryDirectory(prefix='model_records_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA.name
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import auth, storage, twin_imports, twin_library, twin_materials, twin_objects, twin_store
from services import twin_model_ops, twin_model_bridge, twin_plan
from fastapi.testclient import TestClient
import main

API = '/api/house/models'
BUILTIN = 'mid_century_lounge_chair'
PARTS = [dict(key='Wood', name='Wood', triangles=1, has_uv=True, opaque=True)]


def glb():
    raw = json.dumps({'asset': {'version': '2.0'}, 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'accessors': [{'count': 3}]}).encode()
    raw += b' ' * (-len(raw) % 4)
    return b'glTF' + struct.pack('<IIII', 2, len(raw) + 20, len(raw), 0x4E4F534A) + raw


class RecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.add_member({'id': 'model-parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'model-child', 'name': 'Child', 'role': 'child'})
        cls.parent = {'X-Member-Token': storage.create_member_token('model-parent')}
        cls.child = {'X-Member-Token': storage.create_member_token('model-child')}
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='model_case_')
        self.addCleanup(folder.cleanup)
        for target, name, value in [(twin_store, 'DATA_DIR', folder.name),
                                    (twin_store, 'current_model', None)]:
            p = patch.object(target, name, return_value=value) if name == 'current_model' else patch.object(target, name, value)
            p.start(); self.addCleanup(p.stop)
        real = storage.get_settings
        p = patch.object(storage, 'get_settings', side_effect=lambda: {**real(), 'auth_enforce': True})
        p.start(); self.addCleanup(p.stop)
        self.entry = twin_imports.create({'scene.glb': glb()}, 'Test chair', 'furniture')
        # The import inspector's client-side parts stamp is already present.
        self.entry['parts'] = deepcopy(PARTS)
        (twin_imports.root() / self.entry['id'] / twin_imports.META).write_text(json.dumps(self.entry), encoding='utf-8')
        self.asset = self.entry['id']
        self.material = twin_materials.create({'name': 'Test wood'}, 'model-parent')['id']

    def get(self, asset=None):
        r = self.client.get(f'{API}/{asset or self.asset}', headers=self.parent)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def change(self, changes, record=None, asset=None, status=200):
        asset = asset or self.asset
        record = record or self.get(asset)
        r = self.client.patch(f'{API}/{asset}', headers=self.parent, json={'revision': record['revision'], **changes})
        self.assertEqual(r.status_code, status, r.text)
        return r.json()

    def override(self):
        return {'Wood': {'material': self.material, 'texture': 'model', 'tiles': 2}}

    def upload_start(self, level, percent):
        raw = glb()
        r = self.client.post('/api/house/editor/imports/uploads', headers=self.parent, json={
            'name': 'Test chair', 'asset_id': self.asset, 'lod': level, 'percent': percent,
            'size': len(raw), 'files': [{'name': level, 'size': len(raw)}]})
        self.assertEqual(r.status_code, 200, r.text)
        url = '/api/house/editor/imports/uploads/' + r.json()['upload_id']
        self.assertEqual(self.client.put(url + '/0', headers=self.parent, content=raw).status_code, 200)
        return url

    def test_catalog_lists_imports_and_builtins(self):
        r = self.client.get(API, headers=self.parent)
        self.assertEqual(r.status_code, 200, r.text)
        rows = {m['id']: m for m in r.json()['models']}
        self.assertFalse(rows[self.asset]['builtin'])
        self.assertTrue(rows[BUILTIN]['builtin'])
        self.assertEqual(rows[BUILTIN]['lod_percent'], [100, 25, 5])

    def test_patch_sets_fix_and_materials(self):
        before = self.get()
        row = self.change({'fix': {'height_m': .8, 'turn': 90}, 'materials': self.override()}, before)
        self.assertEqual(row['revision'], before['revision'] + 1)
        self.assertEqual(row['fix'], {'height_m': .8, 'turn': 90})
        self.assertEqual(row['materials'], self.override())
        self.assertEqual(self.get(), row)

    def test_revision_conflict_409(self):
        before = self.get()
        current = self.change({'fix': {'turn': 90}}, before)
        body = self.change({'fix': {'turn': 180}}, before, status=409)
        self.assertEqual(body['record'], current)
        self.assertIsInstance(body['detail'], str)

    def test_refuses_unknown_part(self):
        body = self.change({'materials': {'Nope': {'material': self.material}}}, status=400)
        self.assertIn('Unknown part', body['detail'])

    def test_refuses_unknown_material(self):
        self.change({'materials': {'Wood': {'material': 'missing'}}}, status=400)

    def test_stale_lod_upload_refused(self):
        url = self.upload_start('lod1.glb', 25)
        self.change({'lod_percent': [100, 40, 5]})
        r = self.client.post(url + '/finish', headers=self.parent)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn('record', r.json())
        self.assertFalse(any(l['name'] == 'lod1.glb' for l in self.get()['lods']))
        self.assertFalse((twin_imports.root() / self.asset / 'lod1.glb').exists())

    def test_full_below_100_lod0(self):
        self.change({'lod_percent': [60, 25, 5]})
        url = self.upload_start('lod0.glb', 60)
        r = self.client.post(url + '/finish', headers=self.parent)
        self.assertEqual(r.status_code, 200, r.text)
        lod = next(l for l in r.json()['lods'] if l['name'] == 'lod0.glb')
        self.assertEqual((lod['percent'], lod['revision'], lod['triangles'], lod['bytes']), (60, 1, 1, len(glb())))
        self.assertIn('lod0.glb', self.get()['files'])
        self.change({'lod_percent': [100, 25, 5]})
        self.assertNotIn('lod0.glb', self.get()['files'])
        self.assertFalse((twin_imports.root() / self.asset / 'lod0.glb').exists())

    def test_kind_change_keeps_overrides(self):
        self.change({'fix': {'turn': 90}, 'materials': self.override(), 'lod_percent': [60, 25, 5]})
        r = self.client.patch('/api/house/editor/imports/' + self.asset, headers=self.parent,
                              json={'name': 'New name', 'kind': 'decor'})
        self.assertEqual(r.status_code, 200, r.text)
        row = self.get()
        self.assertEqual(row['fix'], {'turn': 90})
        self.assertEqual(row['materials'], self.override())
        self.assertEqual(row['lod_percent'], [60, 25, 5])

    def test_builtin_record_persists(self):
        row = self.change({'fix': {'turn': 90}}, asset=BUILTIN)
        path = Path(twin_store.DATA_DIR) / 'library_models' / (BUILTIN + '.json')
        self.assertTrue(path.exists())
        with patch.object(twin_library, '_urlopen', side_effect=lambda *a, **kw: io.BytesIO(b'fake cache')):
            twin_library.ensure(BUILTIN)
        self.assertEqual(self.get(BUILTIN), row)
        self.change({'lod_percent': [60, 25, 5]}, asset=BUILTIN, status=400)

    def test_copy_model_materials_validated(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
        model = twin_model_bridge.assemble(twin_plan.normalize(fixture)[0])[0]
        b = model['buildings'][0]
        b['items'].append({'id': 'model-copy', 'asset': self.asset,
                          'host': {'floor': b['rooms'][0]['id'], 'u': .5, 'v': .5}})
        props = {'model_materials': {'Wood': {'material': 'original'}}}
        op = {'op': 'set_object', 'building': b['id'], 'id': 'model-copy', 'properties': props}
        changed = twin_model_ops.apply(model, op)[0]
        self.assertEqual(changed['buildings'][0]['items'][-1]['model_materials'], props['model_materials'])
        for collection in ('furniture', 'planting'):
            model['site'][collection] = [{'id': 'copy', 'asset': self.asset, 'at': [1, 2]}]
            changed = twin_model_ops.apply(model, {'op': 'set_object', 'list': collection, 'index': 0, 'properties': props})[0]
            self.assertEqual(changed['site'][collection][0]['model_materials'], props['model_materials'])
        with self.assertRaisesRegex(ValueError, 'Unknown part'):
            twin_objects.update({'asset': self.asset}, {'model_materials': {'Nope': {'material': 'original'}}})
        twin_imports.rename(self.asset, 'Door', 'door')
        opening = {'kind': 'door', 'model': self.asset}
        twin_objects.update(opening, props, opening=True)
        with self.assertRaisesRegex(ValueError, 'Unknown part'):
            twin_objects.update(opening, {'model_materials': {'Nope': {'material': 'original'}}}, opening=True)

    def test_material_in_use_by_model(self):
        self.change({'materials': self.override()})
        self.assertIn('Model Test chair: Wood', twin_materials.uses(self.material)['current'])
        with self.assertRaisesRegex(ValueError, 'Used on'):
            twin_materials.delete(self.material, 'model-parent')
        self.change({'materials': {}})
        model = {'buildings': [{'id': 'b', 'items': [{'name': 'Copy', 'asset': self.asset, 'model_materials': self.override()}]}]}
        with patch.object(twin_store, 'current_model', return_value=model):
            self.assertIn('Copy: Wood', twin_materials.uses(self.material)['current'])
            with self.assertRaisesRegex(ValueError, 'Used on'):
                twin_materials.delete(self.material, 'model-parent')

    def test_undo_redo_reset(self):
        first = self.change({'fix': {'turn': 90}, 'materials': self.override()})
        second = self.change({'lod_percent': [60, 25, 5], 'fix': {'turn': 180}})
        for action, expected in [('undo', first), ('redo', second), ('reset', {'lod_percent': [100, 25, 5]})]:
            before = self.get()
            r = self.client.post(f'{API}/{self.asset}/{action}', headers=self.parent, json={'revision': before['revision']})
            self.assertEqual(r.status_code, 200, r.text)
            row = r.json()
            self.assertEqual(row['revision'], before['revision'] + 1)
            for key in ('lod_percent', 'fix', 'materials'):
                self.assertEqual(row.get(key), expected.get(key))
            stale = self.client.post(f'{API}/{self.asset}/{action}', headers=self.parent, json={'revision': before['revision']})
            self.assertEqual(stale.status_code, 409, stale.text)

    def test_parts_stamp_once(self):
        self.change({'parts': PARTS, 'parts_version': 1})
        self.change({'parts': PARTS}, status=400)

    def test_parts_regeneration_keeps_orphans(self):
        self.change({'materials': self.override()})
        parts = [dict(PARTS[0], key='Metal', name='Metal')]
        row = self.change({'parts': parts, 'parts_version': 1})
        self.assertEqual(row['materials'], self.override())
        self.assertEqual(row['orphans'], ['Wood'])
        self.assertEqual(self.get(), row)
        self.assertEqual(self.change({'materials': self.override()})['orphans'], ['Wood'])
        # An altered assignment still refuses the missing key.
        self.change({'materials': {'Wood': {**self.override()['Wood'], 'tiles': 3}}}, status=400)

    def test_lod_revisions_survive_invalidation_and_undo(self):
        for level, percent in [('lod1.glb', 25), ('lod2.glb', 5)]:
            url = self.upload_start(level, percent)
            self.assertEqual(self.client.post(url + '/finish', headers=self.parent).status_code, 200)
        before = self.get()
        changed = self.change({'lod_percent': [100, 40, 5]})
        self.assertEqual([l['name'] for l in changed['lods']], ['lod2.glb'])
        self.assertNotIn('lod1.glb', changed['files'])
        self.assertEqual(changed['lods'][0], before['lods'][1])
        url = self.upload_start('lod1.glb', 40)
        self.assertEqual(self.client.post(url + '/finish', headers=self.parent).status_code, 200)
        mid = next(l for l in self.get()['lods'] if l['name'] == 'lod1.glb')
        self.assertEqual((mid['percent'], mid['revision']), (40, 2))
        revision = self.get()['revision']
        r = self.client.post(f'{API}/{self.asset}/undo', headers=self.parent, json={'revision': revision})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['lod_percent'], [100, 25, 5])
        self.assertFalse(any(l['name'] == 'lod1.glb' for l in r.json()['lods']))
        url = self.upload_start('lod1.glb', 25)
        self.assertEqual(self.client.post(url + '/finish', headers=self.parent).status_code, 200)
        self.assertEqual(next(l for l in self.get()['lods'] if l['name'] == 'lod1.glb')['revision'], 3)

    def test_history_only_model_material_is_archived(self):
        self.change({'materials': self.override()})
        self.change({'materials': {}})
        self.assertEqual(twin_materials.uses(self.material), {'current': [], 'history': True})
        self.assertEqual(twin_materials.delete(self.material, 'model-parent'), {'archived': True})
        r = self.client.post(f'{API}/{self.asset}/undo', headers=self.parent, json={'revision': self.get()['revision']})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['materials'], self.override())

    def test_history_copy_and_all_copy_labels(self):
        piece = {'id': 'copy', 'name': 'Copy', 'asset': self.asset, 'model_materials': self.override()}
        for model in ({'buildings': [{'id': 'b', 'openings': [dict(piece, model=self.asset)]}]},
                      {'site': {'furniture': [piece]}}, {'site': {'planting': [piece]}}):
            with patch.object(twin_store, 'current_model', return_value=model):
                self.assertEqual(twin_materials.uses(self.material)['current'], ['Copy: Wood'])
        round_id = 123
        path = Path(twin_store.DATA_DIR) / 'rounds' / f'{round_id}.json'
        path.parent.mkdir()
        path.write_text(json.dumps(model), encoding='utf-8')
        with patch.object(twin_store, 'rounds', return_value=[{'id': round_id}]):
            self.assertTrue(twin_materials.uses(self.material)['history'])
            self.assertTrue(twin_materials.delete(self.material, 'model-parent')['archived'])

    def test_concurrent_record_writes_have_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from services import twin_model_records as records
        revision = self.get()['revision']
        def write(turn):
            try:
                return records.update(self.asset, {'fix': {'turn': turn}}, revision)
            except records.Conflict as exc:
                return exc
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, (90, 180)))
        self.assertEqual(sum(isinstance(r, records.Conflict) for r in results), 1)
        self.assertEqual(self.get()['revision'], revision + 1)
        self.assertEqual(len(records.history(self.asset)['undo']), 1)

    def test_copy_switch_validates_against_new_model_atomically(self):
        other = twin_imports.create({'other.glb': glb()}, 'Other door', 'door')
        twin_imports.rename(self.asset, 'Door', 'door')
        piece = {'kind': 'door', 'model': self.asset, 'model_materials': {'Wood': {'material': 'original'}}}
        before = deepcopy(piece)
        with self.assertRaises(ValueError):
            twin_objects.update(piece, {'model': 'missing'}, opening=True)
        self.assertEqual(piece, before)
        twin_objects.update(piece, {'model_materials': {}, 'model': other['id']}, opening=True)
        self.assertEqual(piece['model'], other['id'])

    def test_stale_copy_parts_do_not_block_unrelated_edits(self):
        # Old copies may outlive a part-key regeneration. Loading the house or
        # naming the copy must preserve them for the renderer's original fallback.
        piece = {'asset': self.asset, 'model_materials': {'Gone': {'material': 'original'}}}
        self.assertIsNone(twin_objects.error(piece))
        twin_objects.update(piece, {'name': 'Old copy'})
        self.assertEqual(piece['model_materials'], {'Gone': {'material': 'original'}})
        with self.assertRaisesRegex(ValueError, 'Unknown part'):
            twin_objects.update(piece, {'model_materials': {'Gone': {'material': self.material}}})

    def test_legacy_upload_defaults_and_record_revision(self):
        from services import twin_model_records as records
        before = self.get()
        attached = twin_imports.attach_lod(self.asset, 'lod1.glb', glb())
        self.assertEqual(attached['revision'], before['revision'] + 1)
        self.assertEqual(attached['lods'][0]['percent'], 25)
        with self.assertRaises(records.Conflict):
            records.update(self.asset, {'fix': {}}, before['revision'])
        self.change({'lod_percent': [100, 40, 5]})
        with self.assertRaises(records.Conflict):
            twin_imports.attach_lod(self.asset, 'lod1.glb', glb())

    def test_auth_rows(self):
        from services import access_readers
        for path in (API, API + '/{asset_id}'):
            self.assertEqual(auth.resolve('GET', path), auth.WALL_OR_SERVICE)
            self.assertIsNotNone(access_readers.resolve_route('GET', path))
        for method, path in [('PATCH', f'{API}/{self.asset}'), *[('POST', f'{API}/{self.asset}/{a}') for a in ('undo', 'redo', 'reset')]]:
            self.assertEqual(auth.resolve(method, path.replace(self.asset, '{asset_id}')), auth.PARENTS)
            self.assertIsNotNone(access_readers.resolve_route(method, path.replace(self.asset, '{asset_id}')))
            for headers in ({}, self.child):
                r = self.client.request(method, path, headers=headers, json={'revision': 0})
                self.assertIn(r.status_code, (401, 403), r.text)

    def test_file_cache_and_validation_errors(self):
        r = self.client.get(f'/api/house/twin/imports/{self.asset}/scene.glb', headers=self.parent)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers.get('cache-control'), 'no-cache')
        for changes in ({'fix': {'turn': 45}}, {'lod_percent': [100, 20, 30]}, {'revision': True},
                        {'materials': {'Wood': {'material': self.material, 'texture': 'real', 'tiles': 2}}},
                        {'materials': {'Wood': {'material': {}}}},
                        {'materials': {'Wood': {'material': self.material, 'texture': []}}},
                        {'name': 'No'}, {'parts': [{'key': 'Wood'}]}):
            self.change(changes, status=400)
        self.assertEqual(self.client.get(API + '/unknown', headers=self.parent).status_code, 404)

    def test_legacy_regen_starts_at_one(self):
        path = twin_imports.root() / self.asset / twin_imports.META
        raw = json.loads(path.read_text(encoding='utf-8'))
        raw['lods'] = [{'name': 'lod1.glb', 'triangles': 1, 'bytes': len(glb())}]
        raw['files']['lod1.glb'] = True
        (path.parent / 'lod1.glb').write_bytes(glb())
        path.write_text(json.dumps(raw), encoding='utf-8')
        self.assertEqual(self.get()['lods'][0]['revision'], 0)
        self.assertEqual(self.get()['lods'][0]['percent'], 25)
        for expected in (1, 2):
            url = self.upload_start('lod1.glb', 25)
            r = self.client.post(url + '/finish', headers=self.parent)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['lods'][0]['revision'], expected)
        # A separate record write must also preserve the legacy zero counter.
        from services import twin_model_records as records
        other = twin_imports.create({'scene.glb': glb()}, 'Legacy', 'furniture')
        other_path = twin_imports.root() / other['id'] / twin_imports.META
        other.update(lods=raw['lods'], files=raw['files'])
        other_path.write_text(json.dumps(other), encoding='utf-8')
        (other_path.parent / 'lod1.glb').write_bytes(glb())
        records.update(other['id'], {'fix': {'turn': 90}}, records.get(other['id'])['revision'])
        self.assertEqual(twin_imports.attach_lod(other['id'], 'lod1.glb', glb(), 25)['lods'][0]['revision'], 1)

    def test_opening_model_switch_drops_unknown_keys(self):
        other = twin_imports.create({'door.glb': glb()}, 'Door', 'door')
        path = twin_imports.root() / other['id'] / twin_imports.META
        raw = json.loads(path.read_text(encoding='utf-8'))
        raw['parts'] = [dict(PARTS[0], key='Metal', name='Metal')]
        path.write_text(json.dumps(raw), encoding='utf-8')
        before = {'kind': 'door', 'model': self.asset, 'model_materials': {
            'Wood': {'material': 'original'}, 'Metal': {'material': 'original'}}}
        twin_objects.update(before, {'model': other['id']}, opening=True)
        self.assertEqual(before['model_materials'], {'Metal': {'material': 'original'}})
        twin_objects.update(before, {'model': None}, opening=True)
        self.assertEqual(before['model_materials'], {})

    def test_paste_copy_with_stale_keys(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
        model = twin_model_bridge.assemble(twin_plan.normalize(fixture)[0])[0]
        b = model['buildings'][0]
        twin_imports.rename(self.asset, 'Door', 'door')
        overrides = {'Gone': {'material': 'original'}, 'Wood': {'material': 'original'}}
        wall = b['walls'][0]
        b['openings'] = []
        added = twin_model_ops.apply(model, {'op': 'add_opening', 'building': b['id'],
            'wall': wall['id'], 'kind': 'door', 'at': 2, 'width': 2, 'sill': 0, 'head': 7,
            'model': self.asset, 'model_materials': overrides})[0]
        self.assertEqual(added['buildings'][0]['openings'][-1]['model_materials'], {'Wood': {'material': 'original'}})
        # Free and hosted copy creation use the same pruning semantics.
        for collection in ('furniture', 'planting'):
            added = twin_model_ops.apply(model, {'op': 'add_site_item', 'list': collection,
                'asset': self.asset, 'at': [1, 2], 'model_materials': overrides})[0]
            self.assertEqual(added['site'][collection][-1]['model_materials'], {'Wood': {'material': 'original'}})
        added = twin_model_ops.apply(model, {'op': 'add_item', 'building': b['id'], 'asset': self.asset,
            'host': {'floor': b['rooms'][0]['id'], 'u': .5, 'v': .5}, 'model_materials': overrides})[0]
        self.assertEqual(added['buildings'][0]['items'][-1]['model_materials'], {'Wood': {'material': 'original'}})

    def test_edit_other_field_with_stale_keys(self):
        piece = {'asset': self.asset, 'model_materials': {'Gone': {'material': 'original'}}}
        twin_objects.update(piece, {'name': 'Edited', 'model_materials': {
            **piece['model_materials'], 'Wood': {'material': self.material, 'texture': 'real'}}})
        self.assertEqual(piece['name'], 'Edited')
        self.assertEqual(piece['model_materials']['Gone'], {'material': 'original'})
        before = deepcopy(piece)
        with self.assertRaisesRegex(ValueError, 'Unknown part'):
            twin_objects.update(piece, {'model_materials': {**piece['model_materials'], 'Gone': {'material': self.material}}})
        self.assertEqual(piece, before)

    def test_orphans_round_trip(self):
        self.change({'materials': self.override()})
        self.change({'parts': [dict(PARTS[0], key='Metal', name='Metal')], 'parts_version': 1})
        before = self.get()
        self.assertEqual(before['orphans'], ['Wood'])
        after = self.change({'materials': {**before['materials'], 'Metal': {'material': self.material, 'texture': 'real'}}})
        self.assertEqual(after['materials']['Wood'], before['materials']['Wood'])
        for action, expected in (('undo', before), ('redo', after)):
            r = self.client.post(f'{API}/{self.asset}/{action}', headers=self.parent, json={'revision': self.get()['revision']})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['materials'], expected['materials'])
            self.assertEqual(r.json()['orphans'], ['Wood'])

    def test_builtin_follows_manifest(self):
        self.change({'parts': PARTS, 'parts_version': 1}, asset=BUILTIN)
        edited = self.change({'fix': {'turn': 90}, 'materials': self.override()}, asset=BUILTIN)
        path = Path(twin_store.DATA_DIR) / 'library_models' / f'{BUILTIN}.json'
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertFalse(set(saved) & {'files', 'model', 'source', 'licence', 'kind', 'id', 'name', 'cost'})
        # Old full-record files must not freeze manifest metadata either.
        path.write_text(json.dumps({**saved, 'files': {'old.glb': 'old'}, 'model': 'old.glb', 'source': 'old'}), encoding='utf-8')
        manifest = twin_library.manifest()
        manifest[BUILTIN].update(files={'other.glb': 'new', 'explicit.glb': 'newer'}, model='explicit.glb', source='new-source')
        with patch.object(twin_library, 'manifest', return_value=manifest):
            row = self.get(BUILTIN)
        self.assertEqual(row['files'], manifest[BUILTIN]['files'])
        self.assertEqual(row['model'], 'explicit.glb')
        self.assertEqual(row['source'], 'new-source')
        self.assertEqual(row['fix'], edited['fix'])
        self.assertEqual(row['materials'], edited['materials'])

    def test_archived_material_refused_when_new(self):
        self.change({'materials': self.override()})
        piece = {'asset': self.asset}
        twin_objects.update(piece, {'model_materials': self.override()})
        path = twin_materials.root() / self.material / 'material.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        raw['archived'] = True
        path.write_text(json.dumps(raw), encoding='utf-8')
        changed = {'Wood': {**self.override()['Wood'], 'tiles': 3}}
        self.change({'materials': changed}, status=400)
        self.change({'materials': {}})
        self.change({'materials': self.override()}, status=400)
        for candidate, values in (({}, self.override()), (piece, changed)):
            target = {'asset': self.asset, **deepcopy(candidate)}
            before = deepcopy(target)
            with self.assertRaisesRegex(ValueError, 'material'):
                twin_objects.update(target, {'model_materials': values})
            self.assertEqual(target, before)
        # Unchanged archived assignments round-trip, including copy property saves.
        twin_objects.update(piece, {'name': 'Still here', 'model_materials': deepcopy(piece['model_materials'])})
        revision = self.get()['revision']
        r = self.client.post(f'{API}/{self.asset}/undo', headers=self.parent, json={'revision': revision})
        self.assertEqual(r.status_code, 200, r.text)
        self.change({'fix': {'turn': 90}, 'materials': self.override()})

    def test_empty_stamp_refused(self):
        blank = self.get(BUILTIN)
        for change in ({'parts_version': 1}, {'parts': [], 'parts_version': 1}):
            self.change(change, asset=BUILTIN, status=400)
            self.assertEqual(self.get(BUILTIN), blank)
        self.change({'parts': PARTS}, asset=BUILTIN)
        self.assertEqual(self.change({'parts_version': 1}, asset=BUILTIN)['parts_version'], 1)

    def test_save_failure_keeps_files(self):
        from services import twin_model_records as records
        twin_imports.attach_lod(self.asset, 'lod1.glb', glb(), 25)
        path = twin_imports.root() / self.asset / twin_imports.META
        before = path.read_bytes()
        row = self.get()
        with patch.object(records, '_json', side_effect=OSError('record write failed')):
            with self.assertRaisesRegex(OSError, 'record write failed'):
                records.update(self.asset, {'lod_percent': [100, 40, 5]}, row['revision'])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual((path.parent / 'lod1.glb').read_bytes(), glb())
        self.assertEqual(self.get(), row)

    def test_history_write_failure_is_best_effort(self):
        from services import twin_model_records as records
        write = records._json
        def fail_history(path, value):
            if path.name == '.model-history.json':
                raise OSError('history unavailable')
            return write(path, value)
        with patch.object(records, '_json', side_effect=fail_history):
            row = records.update(self.asset, {'fix': {'turn': 90}}, self.get()['revision'])
        self.assertEqual(row['fix'], {'turn': 90})
        self.assertEqual(self.get(), row)

    def test_plan_save_refuses_bad_entry_shape(self):
        from services import twin_director, twin_model
        fixture = json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
        fixture = twin_plan.normalize(fixture)[0]
        invalid = ['x', {}, {'material': 3}, {'material': 'original', 'extra': True},
                   {'material': 'original', 'texture': 'wrong'}]
        for entry in invalid:
            with self.subTest(entry=entry):
                materials = {'Wood': entry}
                self.assertIsNotNone(twin_objects.error({'model_materials': materials}))
                plan = deepcopy(fixture)
                plan['site']['furniture'] = [{'id': 'bad', 'asset': self.asset, 'at': [1, 2], 'model_materials': materials}]
                response = self.client.put('/api/house/twin/plan', headers=self.parent, json={'plan': plan, 'reason': 'Invalid shape'})
                self.assertEqual(response.status_code, 400, response.text)
                model = twin_model_bridge.assemble(fixture)[0]
                model['buildings'][0]['items'].append({'id': 'bad', 'asset': self.asset,
                    'host': {'floor': model['buildings'][0]['rooms'][0]['id'], 'u': .5, 'v': .5}, 'model_materials': materials})
                with self.assertRaises(ValueError):
                    twin_model.normalize(model)
                kit = twin_library.kit('modern_farmhouse')
                with self.assertRaises(ValueError):
                    twin_director._ordinary_addition('furniture', {'asset': next(iter(kit['furniture'].values())),
                        'at': [1, 2], 'model_materials': materials}, fixture['site'], kit, [])

    def test_composed_yard_keeps_edits_with_part_materials(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
        properties = {'name': 'Touched plant', 'scale': 1.5, 'model_materials': self.override()}
        for malformed in (False, True):
            with self.subTest(malformed=malformed):
                authored = deepcopy(properties)
                if malformed:
                    authored['model_materials'] = {'Wood': 'bad'}
                overrides = {'properties': {'p1': authored}}
                original = deepcopy(overrides)
                expected = {key: value for key, value in properties.items() if not malformed or key != 'model_materials'}
                notes = []
                cleaned = twin_plan._compose_overrides(overrides, notes)
                self.assertEqual(cleaned.get('properties', {}).get('p1'), expected)
                self.assertEqual(overrides, original, 'validation must not mutate the stored edits')
                self.assertEqual(bool(notes), malformed)
                plan = deepcopy(fixture)
                plan.setdefault('site', {})['compose_overrides'] = overrides
                normalized = twin_plan.normalize(plan)[0]
                self.assertEqual(normalized['site']['compose_overrides']['properties']['p1'], expected)
                model = twin_model_bridge.assemble(normalized)[0]
                self.assertEqual(model['site']['compose_overrides']['properties']['p1'], expected)
        # Other invalid fields still follow the existing refusal rule.
        notes = []
        bad_scale = twin_plan._compose_overrides({'properties': {'p1': {**properties, 'scale': 21}}}, notes)
        self.assertNotIn('p1', bad_scale.get('properties', {}))
        self.assertTrue(notes)

    def test_polyhaven_prefixed_copy_takes_part_materials(self):
        from services import twin_director, twin_model_records as records
        self.change({'parts': PARTS, 'parts_version': 1}, asset=BUILTIN)
        kit = twin_library.kit('modern_farmhouse')
        piece = twin_director._ordinary_addition('furniture', {'asset': BUILTIN, 'at': [1, 2]}, {}, kit, [])
        self.assertEqual(piece['asset'], 'polyhaven:' + BUILTIN)
        twin_objects.update(piece, {'name': 'Director chair', 'model_materials': self.override()}, 'furniture')
        self.assertIsNone(twin_objects.error(piece, 'furniture'))
        self.assertEqual(piece['model_materials'], self.override())
        self.assertEqual(records.get(piece['asset']), self.get(BUILTIN))
        self.assertEqual(twin_objects.validate('model', piece['asset'], twin_objects.SCHEMA['opening']['model']), piece['asset'])
        self.assertEqual(records.history(piece['asset']), records.history(BUILTIN))
        self.assertEqual(twin_objects.placements({'site': {'furniture': [piece]}}, BUILTIN), ['Yard: Director chair'])
        with patch.object(twin_store, 'current_model', return_value={'site': {'furniture': [piece]}}):
            self.assertIn('Director chair: Wood', twin_materials.uses(self.material)['current'])
            with self.assertRaisesRegex(ValueError, 'Used on'):
                twin_materials.delete(self.material, 'model-parent')
        before = deepcopy(piece)
        with self.assertRaisesRegex(ValueError, 'Unknown part'):
            twin_objects.update(piece, {'model_materials': {'Gone': {'material': self.material}}}, 'furniture')
        self.assertEqual(piece, before)

    def test_move_and_paste_keep_archived_entries(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
        model = twin_model_bridge.assemble(twin_plan.normalize(fixture)[0])[0]
        b = model['buildings'][0]
        host = {'floor': b['rooms'][0]['id'], 'u': .5, 'v': .5}
        overrides = {**self.override(), 'Gone': {'material': 'original'}}
        source = {'id': 'moving-copy', 'asset': self.asset, 'host': host, 'model_materials': overrides}
        b['items'].append(source)
        path = twin_materials.root() / self.material / 'material.json'
        raw = json.loads(path.read_text(encoding='utf-8'))
        raw['archived'] = True
        path.write_text(json.dumps(raw), encoding='utf-8')
        # These are the delete/add batches emitted by Move to.
        moved = twin_model_ops.apply_batch(model, {'ops': [
            {'op': 'delete', 'building': b['id'], 'id': source['id']},
            {'op': 'add_site_item', 'list': 'furniture', 'id': source['id'], 'asset': self.asset,
             'at': [1, 2], 'model_materials': overrides}]})[0]
        self.assertEqual(moved['site']['furniture'][-1]['model_materials'], self.override())
        returned = twin_model_ops.apply_batch(moved, {'ops': [
            {'op': 'delete_site_item', 'list': 'furniture', 'id': source['id']},
            {'op': 'add_item', 'building': b['id'], 'id': source['id'], 'asset': self.asset,
             'host': host, 'model_materials': overrides}]})[0]
        self.assertEqual(returned['buildings'][0]['items'][-1]['model_materials'], self.override())
        self.assertEqual(model['buildings'][0]['items'][-1], source, 'moves must retain the caller-owned source model')
        # Clipboard paste/duplicate reaches these same creation operations.
        pasted = twin_model_ops.apply(model, {'op': 'add_item', 'building': b['id'], 'asset': self.asset,
            'host': host, 'model_materials': overrides})[0]
        self.assertEqual(pasted['buildings'][0]['items'][-1]['model_materials'], self.override())
        for collection in ('furniture', 'planting'):
            pasted = twin_model_ops.apply(model, {'op': 'add_site_item', 'list': collection, 'asset': self.asset,
                'at': [1, 2], 'model_materials': overrides})[0]
            self.assertEqual(pasted['site'][collection][-1]['model_materials'], self.override())
        twin_imports.rename(self.asset, 'Door', 'door')
        model['buildings'][0]['openings'] = []
        opening_op = {'op': 'add_opening', 'building': b['id'], 'wall': b['walls'][0]['id'], 'kind': 'door',
            'at': 2, 'width': 2, 'sill': 0, 'head': 7, 'model': self.asset, 'model_materials': overrides}
        pasted = twin_model_ops.apply(model, opening_op)[0]
        self.assertEqual(pasted['buildings'][0]['openings'][-1]['model_materials'], self.override())
        for op in ({'op': 'add_item', 'building': b['id'], 'asset': self.asset, 'host': host},
                   {'op': 'add_site_item', 'list': 'furniture', 'asset': self.asset, 'at': [1, 2]}, opening_op):
            with self.assertRaisesRegex(ValueError, 'unknown library material'):
                twin_model_ops.apply(model, {**op, 'model_materials': {'Wood': {'material': 'missing'}}})
        # Hand assignment on an existing copy must remain strict.
        before = deepcopy(source)
        with self.assertRaisesRegex(ValueError, 'unknown library material'):
            twin_objects.update(source, {'model_materials': {'Wood': {**self.override()['Wood'], 'tiles': 3}}})
        self.assertEqual(source, before)
        self.change({'materials': self.override()}, status=400)


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        import gc
        RecordTests.client.close()
        storage.db.close()
        gc.collect()
        DATA.cleanup()
