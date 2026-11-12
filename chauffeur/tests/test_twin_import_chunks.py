"""Real HTTP chunk imports and archive budgets, isolated from household data."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

DATA = tempfile.TemporaryDirectory(prefix='twin_chunks_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA.name
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import auth, storage, twin_imports, twin_store
from fastapi.testclient import TestClient
import main


def model(triangles=1):
    return json.dumps({'asset': {'version': '2.0'}, 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'accessors': [{'count': triangles * 3}]}).encode()


def zipped():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('scene.gltf', model())
    return stream.getvalue()


class ChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.add_member({'id': 'chunk-parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'chunk-child', 'name': 'Child', 'role': 'child'})
        cls.parent = {'X-Member-Token': storage.create_member_token('chunk-parent')}
        cls.child = {'X-Member-Token': storage.create_member_token('chunk-child')}
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='chunk_case_')
        self.addCleanup(self.temp.cleanup)
        self.patcher = patch.object(twin_store, 'DATA_DIR', self.temp.name)
        self.patcher.start(); self.addCleanup(self.patcher.stop)
        real = storage.get_settings
        self.settings = patch.object(storage, 'get_settings', side_effect=lambda: {**real(), 'auth_enforce': True})
        self.settings.start(); self.addCleanup(self.settings.stop)

    def start(self, data, files=None):
        response = self.client.post('/api/house/editor/imports/uploads', headers=self.parent,
            json={'name': 'Car', 'size': len(data), 'files': files or [{'name': 'car.zip', 'size': len(data)}]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['chunk_bytes'], 4 * 1024 * 1024)
        return '/api/house/editor/imports/uploads/' + response.json()['upload_id']

    def put(self, path, index, data):
        return self.client.put(f'{path}/{index}', headers={**self.parent, 'Content-Type': 'application/octet-stream'}, content=data)

    def test_three_chunk_zip_and_loose_file_boundaries(self):
        data = zipped(); path = self.start(data)
        cuts = [data[:25], data[25:80], data[80:]]
        for index, chunk in enumerate(cuts):
            response = self.put(path, index, chunk)
            self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(path + '/finish', headers=self.parent)
        self.assertEqual(response.status_code, 200, response.text)
        entry = response.json()
        self.assertEqual((twin_imports.root() / entry['id'] / 'car.zip').read_bytes(), data)
        self.assertFalse((twin_imports.root() / '.uploads' / path.rsplit('/', 1)[1]).exists())
        raw = model() + b'buffer'
        path = self.start(raw, [{'name': 'scene.gltf', 'size': len(model())}, {'name': 'scene.bin', 'size': 6}])
        self.assertEqual(self.put(path, 0, raw).status_code, 200)
        self.assertEqual(self.client.post(path + '/finish', headers=self.parent).status_code, 200)

    def test_order_sizes_incomplete_and_cancel(self):
        data = zipped(); path = self.start(data)
        for index, body in [(1, data), (0, data + b'x'), (0, b''), (0, b'x' * (4 * 1024 * 1024 + 1))]:
            response = self.put(path, index, body)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIsInstance(response.json()['detail'], str)
        self.assertEqual(self.client.post(path + '/finish', headers=self.parent).status_code, 400)
        self.assertEqual(self.put(path, 0, data).status_code, 200)
        self.assertEqual(self.put(path, 0, data).status_code, 400)
        self.assertEqual(self.client.delete(path, headers=self.parent).status_code, 200)
        self.assertEqual(self.client.post(path + '/finish', headers=self.parent).status_code, 400)

    def test_expiry_and_two_concurrent(self):
        first = self.start(zipped()); self.start(zipped())
        with self.assertRaisesRegex(ValueError, 'Two models'):
            twin_imports.start_upload({'name': 'Third', 'size': 1, 'files': [{'name': 'a', 'size': 1}]})
        with patch.object(twin_imports.time, 'time', return_value=time.time() + 3601):
            self.start(zipped())
        self.assertEqual(self.put(first, 0, b'x').status_code, 400)
        self.assertEqual(len(list((twin_imports.root() / '.uploads').iterdir())), 1)

    def test_manifest_validation(self):
        base = {'name': 'Test', 'size': 1, 'files': [{'name': 'a', 'size': 1}]}
        for changes in [{'size': 2}, {'files': []}, {'files': [{'name': '../x', 'size': 1}]},
                        {'size': 2, 'files': [{'name': 'a', 'size': 1}] * 2},
                        {'files': [{'name': 'a', 'size': True}]},
                        {'files': [{'name': str(i), 'size': 1} for i in range(513)], 'size': 513},
                        {'files': [{'name': 'a', 'size': 51 * 1048576}], 'size': 51 * 1048576}]:
            response = self.client.post('/api/house/editor/imports/uploads', headers=self.parent, json={**base, **changes})
            self.assertEqual(response.status_code, 400, response.text)

    def test_every_route_is_parent_only(self):
        path = self.start(zipped())
        cases = [('POST', '/api/house/editor/imports/uploads', {}), ('PUT', path + '/0', None),
                 ('POST', path + '/finish', None), ('DELETE', path, None)]
        for method, url, body in cases:
            self.assertEqual(auth.resolve(method, url), auth.PARENTS)
            for headers in ({}, self.child):
                response = self.client.request(method, url, headers=headers, json=body)
                self.assertIn(response.status_code, (401, 403), response.text)

    def test_unexpected_finish_failure_is_json(self):
        path = self.start(zipped()); self.put(path, 0, zipped())
        with patch.object(twin_imports, 'create', side_effect=RuntimeError('test failure')):
            response = self.client.post(path + '/finish', headers=self.parent)
        self.assertEqual(response.status_code, 500)
        self.assertIn('test failure', response.json()['detail'])

    def test_uploaded_and_unpacked_limits_and_ratio(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('scene.gltf', model(570138))
            with archive.open('scene.bin', 'w') as output:
                # Fresh 16 KB, repeated once: ~26 MB uploaded, 51 MB unpacked.
                for _ in range(51 * 32):
                    block = os.urandom(16384); output.write(block); output.write(block)
        data = stream.getvalue()
        self.assertTrue(25 * 1048576 < len(data) < 28 * 1048576, len(data))
        entry = twin_imports.create({'car.zip': data}, 'EV9', 'car')
        self.assertTrue(entry['heavy']); self.assertIn('570k', entry['warning'])
        self.assertEqual((twin_imports.root() / entry['id'] / 'car.zip').read_bytes(), data)
        with patch.object(twin_imports, 'unpacked_limit_mb', return_value=50), self.assertRaisesRegex(ValueError, 'unpacks to 51 MB'):
            twin_imports.create({'car.zip': data}, 'EV9', 'car')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('scene.gltf', model())
            with archive.open('huge.bin', 'w') as output:
                for _ in range(201): output.write(bytes(1048576))
        with self.assertRaisesRegex(ValueError, 'limit is 200 MB'):
            twin_imports.create({'bomb.zip': stream.getvalue()}, 'Huge', 'other')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('scene.gltf', model()); archive.writestr('bomb.bin', bytes(1048576))
        with self.assertRaisesRegex(ValueError, '100 times'):
            twin_imports.create({'bomb.zip': stream.getvalue()}, 'Bomb', 'other')

    def test_triangle_cap_and_settings(self):
        entry = twin_imports.create({'scene.gltf': model(570138)}, 'EV9', 'car')
        self.assertTrue(entry['heavy']); self.assertIn('wall panel', entry['warning'])
        self.assertEqual(twin_imports.create({'scene.gltf': model(1000000)}, 'At cap', 'car')['triangles'], 1000000)
        with self.assertRaises(ValueError): twin_imports.create({'scene.gltf': model(1200000)}, 'Huge', 'car')
        self.assertEqual(self.client.put('/api/house/editor/import-settings', headers=self.parent, json={'unpacked_limit_mb': 230}).status_code, 200)
        self.assertEqual(self.client.get('/api/house/editor/import-settings', headers=self.parent).json()['unpacked_limit_mb'], 230)
        self.assertEqual(self.client.put('/api/house/editor/import-settings', headers=self.parent, json={'unpacked_limit_mb': 200}).status_code, 200)

    def test_zip_entry_count_and_saved_footprint(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('scene.gltf', model())
            for i in range(512): archive.writestr(f'{i}.bin', b'')
        with self.assertRaisesRegex(ValueError, '512'):
            twin_imports.create({'many.zip': stream.getvalue()}, 'Too many', 'other')
        entry = twin_imports.create({'scene.gltf': model()}, 'Car', 'car')
        path = '/api/house/editor/imports/' + entry['id']
        response = self.client.patch(path, headers=self.parent, json={'name': 'Car', 'size': [2, 1.8, 5]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(twin_imports.get(entry['id'])['size'], [2, 1.8, 5])
        self.assertEqual(self.client.patch(path, headers=self.parent, json={'name': 'Car', 'size': [-1, 2, 3]}).status_code, 400)


if __name__ == '__main__':
    try: unittest.main()
    finally:
        import gc
        storage.db.close()
        gc.collect()
        DATA.cleanup()
