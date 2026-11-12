"""Slice 4a object contracts and real import HTTP requests; no browser/network."""
import base64
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
import zipfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='twin_objects_'))
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import auth, storage, twin_imports, twin_objects, twin_model_ops, twin_model_bridge, twin_store, twin_edit, twin_plan


def triangle():
    buffer = struct.pack('<9f', -1, 0, 0, 1, 0, 0, 0, 2, 0)
    return {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
            'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
            'buffers': [{'uri': 'data:application/octet-stream;base64,' + base64.b64encode(buffer).decode(), 'byteLength': len(buffer)}],
            'bufferViews': [{'buffer': 0, 'byteLength': len(buffer)}],
            'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [-1, 0, 0], 'max': [1, 2, 0]}]}


def glb():
    data = json.dumps(triangle()).encode()
    data += b' ' * (-len(data) % 4)
    return b'glTF' + struct.pack('<IIII', 2, len(data) + 20, len(data), 0x4E4F534A) + data


class ObjectTests(unittest.TestCase):
    def test_defaults_preserve_legacy_and_schema_is_single_source(self):
        before = {'id': 'old', 'kind': 'tree', 'height': 22, 'rotation': 65, 'scale': .7, 'elevation': 3}
        saved = deepcopy(before)
        read = twin_objects.defaults(before, 'planting')
        self.assertEqual(before, saved)
        self.assertEqual(read['scale'], .7)
        self.assertEqual(read['rotation'], 65)
        self.assertTrue(read['casts_shadow'])
        self.assertEqual(read['visible_in'], ['viewer', 'editor'])
        self.assertEqual(read['height'], 22)
        self.assertEqual(twin_objects.SCHEMA, json.loads((Path(__file__).parents[1] / 'static/twin/object_schema.json').read_text()))

    def test_every_property_validates_and_update_is_atomic(self):
        piece = {'id': 'free', 'object_kind': 'lamp'}
        values = {'name': 'Garden lamp', 'rotation': 450, 'pitch': -15, 'roll': 30, 'scale': .05, 'scale_axes': [1, 2, 3],
                  'tint': '#123456', 'casts_shadow': False, 'visible_in': ['editor'], 'elevation': 4,
                  'emissive': True, 'emissive_color': '#ffffff', 'light_entity': 'light.garden'}
        twin_objects.update(piece, values)
        self.assertEqual(piece['rotation'], 90)
        for field, value in [('scale', .049), ('scale', 20.01), ('scale', True), ('scale', float('nan')), ('scale_axes', [1, 2]),
                             ('scale_axes', [1, 2, 21]), ('rotation', float('inf')), ('tint', 'red'), ('casts_shadow', 1),
                             ('visible_in', ['visitor']), ('visible_in', ['editor', 'editor']), ('light_entity', 'switch.lamp'),
                             ('emissive', 'yes'), ('name', 'x' * 101), ('object_kind', 'pool'), ('nonsense', 1)]:
            before = deepcopy(piece)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                twin_objects.update(piece, {'name': 'Not saved', field: value})
            self.assertEqual(piece, before)
        with self.assertRaises(ValueError):
            twin_objects.update({'host': {'floor': 'room'}}, {'pitch': 15})
        with self.assertRaises(ValueError):
            twin_objects.update({}, {'emissive': True})

    def test_site_and_hosted_ops_and_history_roundtrip(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text())
        model = twin_model_bridge.assemble(twin_plan.normalize(fixture)[0])[0]
        model['site']['furniture'] = [{'id': 'chair', 'at': [1, 2], 'scale': .7}]
        changed, _ = twin_model_ops.apply(model, {'op': 'set_object', 'list': 'furniture', 'index': 0, 'properties': {'scale': 20, 'rotation': 90}})
        self.assertEqual(changed['site']['furniture'][0]['scale'], 20)
        self.assertEqual(model['site']['furniture'][0]['scale'], .7)
        b = changed['buildings'][0]
        b['items'].append({'id': 'test-chair', 'asset': 'chair', 'host': {'floor': b['rooms'][0]['id'], 'u': .5, 'v': .5}, 'scale': 1})
        updated, _ = twin_model_ops.apply(changed, {'op': 'set_object', 'building': b['id'], 'id': 'test-chair', 'properties': {'name': 'Chair', 'tint': '#112233'}})
        item = next(p for p in updated['buildings'][0]['items'] if p['id'] == 'test-chair')
        self.assertEqual(item['host'], b['items'][-1]['host'])
        self.assertEqual(item['name'], 'Chair')
        with patch.object(twin_store, 'current_model', return_value=changed), patch.object(twin_store, 'current', return_value=twin_model_bridge.flatten(changed)):
            with patch.object(twin_store, 'update_model', return_value=123) as save:
                twin_edit.save({'op': 'set_object', 'building': b['id'], 'id': 'test-chair', 'properties': {'scale': 1.5}}, 'parent')
                self.assertEqual(save.call_args.args[1], 'edit')
                saved = save.call_args.args[0](changed)
                self.assertEqual(next(p for p in saved['buildings'][0]['items'] if p['id'] == 'test-chair')['scale'], 1.5)

    def test_opening_models_and_hinges_validate(self):
        entry = twin_imports.create({'window.glb': glb()}, 'Window', 'window')
        opening = {'kind': 'window'}
        twin_objects.update(opening, {'model': entry['id'], 'hinge': 'right', 'swing': 'fixed'}, opening=True)
        self.assertEqual(opening['model'], entry['id'])
        for values in [{'model': 'missing'}, {'swing': 'sideways'}, {'hinge': 2}]:
            with self.assertRaises(ValueError):
                twin_objects.update(opening, values, opening=True)
        with self.assertRaises(ValueError):
            twin_objects.update({'kind': 'door'}, {'model': entry['id']}, opening=True)

    def test_composed_plant_properties_survive_recomposition(self):
        from services import twin_compose, twin_library
        plan = twin_plan.normalize(json.loads((Path(__file__).parent / 'fixtures/twin_poolhouse.plan.json').read_text()))[0]
        kit = twin_library.kit('modern_farmhouse')
        plan = twin_compose.compose(plan, kit)[0]
        plant = next(p for p in plan['site']['planting'] if p.get('by') == 'compose')
        model = twin_model_bridge.assemble(plan)[0]
        index = next(i for i, p in enumerate(model['site']['planting']) if p['id'] == plant['id'])
        changed = twin_model_ops.apply(model, {'op': 'set_object', 'list': 'planting', 'index': index,
                                             'properties': {'scale': 1.5, 'rotation': 90, 'tint': '#abcdef', 'name': 'My tree'}})[0]
        recomposed = twin_compose.compose(twin_model_bridge.flatten(changed), kit)[0]
        final = next(p for p in recomposed['site']['planting'] if p['id'] == plant['id'])
        self.assertEqual((final['scale'], final['rotation'], final['tint'], final['name']), (1.5, 90, '#abcdef', 'My tree'))

    def test_glb_zip_resources_and_budgets(self):
        entry = twin_imports.create({'model.glb': glb()}, 'Small', 'furniture')
        self.assertEqual(entry['triangles'], 1)
        self.assertEqual((twin_imports.root() / entry['id'] / 'model.glb').read_bytes(), glb())
        doc = triangle(); doc['buffers'][0]['uri'] = 'mesh.bin'
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('folder/model.gltf', json.dumps(doc)); z.writestr('folder/mesh.bin', struct.pack('<9f', *range(9)))
        bundled = twin_imports.create({'model.zip': archive.getvalue()}, 'Bundle', 'decor')
        self.assertIn('model.zip', bundled['files'])
        self.assertIn('folder/mesh.bin', bundled['files'])
        for files in [{'../bad.glb': glb()}, {'model.gltf': json.dumps(doc).encode()}, {'model.dae': b'<xml/>'}, {'model.kmz': b'bad'}]:
            with self.assertRaises(ValueError):
                twin_imports.create(files, 'Bad', 'other')
        doc = triangle(); doc['buffers'][0]['uri'] = 'https://example.invalid/tracker.bin'
        with self.assertRaises(ValueError):
            twin_imports.create({'model.gltf': json.dumps(doc).encode()}, 'Remote', 'other')
        doc = triangle(); doc['accessors'][0]['count'] = 3000003
        with self.assertRaises(ValueError):
            twin_imports.create({'model.gltf': json.dumps(doc).encode()}, 'Huge', 'other')
        with patch.object(twin_imports, 'limit_mb', return_value=1), self.assertRaises(ValueError):
            twin_imports.create({'model.glb': b'x' * (1024 * 1024 + 1)}, 'Huge', 'other')

    def test_import_routes_auth_size_serving_rename_and_placed_delete(self):
        from fastapi.testclient import TestClient
        import main
        storage.add_member({'id': 'objects-parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'objects-child', 'name': 'Child', 'role': 'child'})
        parent = {'X-Member-Token': storage.create_member_token('objects-parent')}
        child = {'X-Member-Token': storage.create_member_token('objects-child')}
        real = storage.get_settings
        client = TestClient(main.app)
        with patch.object(storage, 'get_settings', side_effect=lambda: {**real(), 'auth_enforce': True}):
            for headers in ({}, child):
                self.assertIn(client.post('/api/house/editor/imports', headers=headers, files={'files': ('chair.glb', glb())}, data={'name': 'Chair', 'kind': 'furniture'}).status_code, (401, 403))
            response = client.post('/api/house/editor/imports', headers=parent, files={'files': ('chair.glb', glb())}, data={'name': 'Chair', 'kind': 'furniture'})
            self.assertEqual(response.status_code, 200, response.text)
            asset = response.json()['id']; route = '/api/house/twin/imports/' + asset + '/chair.glb'
            self.assertEqual(client.get(route, headers=parent).content, glb())
            self.assertIn(client.get(route, headers={'CF-Connecting-IP': '203.0.113.9'}).status_code, (401, 403))
            self.assertEqual(client.get(route, headers=child).status_code, 200)
            self.assertEqual(client.get('/api/house/twin/imports/' + asset + '/.asset.json', headers=parent).status_code, 404)
            self.assertEqual(client.patch('/api/house/editor/imports/' + asset, headers=parent, json={'name': 'New chair'}).json()['name'], 'New chair')
            placed = {'site': {'furniture': [{'id': 'chair', 'asset': asset}]}}
            with patch.object(twin_store, 'current_model', return_value=placed):
                response = client.delete('/api/house/editor/imports/' + asset, headers=parent)
                self.assertEqual(response.status_code, 400, response.text)
                self.assertIn('Yard: chair', response.text)
            with patch.object(twin_store, 'current_model', return_value=None), patch.object(twin_store, '_state', return_value={'rounds': []}):
                self.assertEqual(client.delete('/api/house/editor/imports/' + asset, headers=parent).status_code, 200)
            self.assertEqual(client.get(route, headers=parent).status_code, 404)
            self.assertEqual(client.put('/api/house/editor/import-settings', headers=parent, json={'limit_mb': 1}).status_code, 200)
            response = client.post('/api/house/editor/imports', headers=parent, files={'files': ('large.glb', b'x' * (1024 * 1024 + 1))}, data={'name': 'Large', 'kind': 'furniture'})
            self.assertEqual(response.status_code, 400)
            self.assertIn('1 MB', response.text)
        self.assertEqual(auth.resolve('GET', '/api/house/twin/imports/{asset_id}/{name:path}'), auth.WALL_OR_SERVICE)

    def test_import_route_takes_gltf_folders_and_zips_and_never_answers_bare_500(self):
        """User 2026-11-12: a glTF zip or loose files gave "The house could not answer" (a
        non-JSON reply). Real glTF shapes import through the route, and any unexpected failure
        is a JSON reason the editor can show."""
        import io, struct, zipfile
        from fastapi.testclient import TestClient
        import main
        storage.add_member({'id': 'gltf-parent', 'name': 'Parent', 'role': 'parent'})
        parent = {'X-Member-Token': storage.create_member_token('gltf-parent')}
        positions = [0, 0, 0, 1, 0, 0, 1, 1, 0]
        binary = struct.pack('<9f', *positions)
        doc = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
               'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
               'buffers': [{'uri': 'scene.bin', 'byteLength': len(binary)}],
               'bufferViews': [{'buffer': 0, 'byteLength': len(binary)}],
               'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3', 'min': [0, 0, 0], 'max': [1, 1, 0]}]}
        loose = {'scene.gltf': json.dumps(doc).encode(), 'scene.bin': binary}
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.post('/api/house/editor/imports', headers=parent, data={'name': 'Loose', 'kind': 'other'},
                               files=[('files', (n, d, 'application/octet-stream')) for n, d in loose.items()])
        self.assertEqual(response.status_code, 200, response.text)
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, 'w') as archive:
            for n, d in loose.items():
                archive.writestr('chair/' + n, d)
        response = client.post('/api/house/editor/imports', headers=parent, data={'name': 'Zipped', 'kind': 'other'},
                               files={'files': ('chair.zip', packed.getvalue(), 'application/zip')})
        self.assertEqual(response.status_code, 200, response.text)
        with patch.object(twin_imports, 'create', side_effect=KeyError('images')):
            response = client.post('/api/house/editor/imports', headers=parent, data={'name': 'Broken', 'kind': 'other'},
                                   files=[('files', (n, d, 'application/octet-stream')) for n, d in loose.items()])
        self.assertEqual(response.status_code, 500)
        self.assertIn('could not be imported', response.json()['detail'])
        self.assertIn('KeyError', response.json()['detail'])


if __name__ == '__main__':
    unittest.main()
