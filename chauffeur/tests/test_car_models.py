"""Car model assignments and derived LOD uploads through authenticated HTTP."""
import gc
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

WORKTREE = Path(__file__).resolve().parents[2]
DATA = tempfile.TemporaryDirectory(prefix='.car_models_test_', dir=WORKTREE)
os.environ['CHAUFFEUR_DATA_DIR'] = DATA.name
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(WORKTREE / 'chauffeur'))
from services import auth, storage, twin_imports, twin_store
from fastapi.testclient import TestClient
import main


def glb(triangles=12, padded_bytes=0):
    doc = {'asset': {'version': '2.0'}, 'nodes': [{'mesh': 0}],
           'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
           'accessors': [{'count': triangles * 3}]}
    raw = json.dumps(doc).encode()
    raw += b' ' * max(0, padded_bytes - len(raw))
    raw += b' ' * (-len(raw) % 4)
    return b'glTF' + struct.pack('<IIII', 2, len(raw) + 20, len(raw), 0x4E4F534A) + raw


class CarModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.add_member({'id': 'model-parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'model-child', 'name': 'Child', 'role': 'child'})
        cls.parent = {'X-Member-Token': storage.create_member_token('model-parent')}
        cls.child = {'X-Member-Token': storage.create_member_token('model-child')}
        cls.client = TestClient(main.app, raise_server_exceptions=False)

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='case_', dir=DATA.name)
        self.addCleanup(folder.cleanup)
        store = patch.object(twin_store, 'DATA_DIR', folder.name)
        store.start(); self.addCleanup(store.stop)
        real = storage.get_settings
        settings = patch.object(storage, 'get_settings', side_effect=lambda: {**real(), 'auth_enforce': True})
        settings.start(); self.addCleanup(settings.stop)
        refresh = patch.object(main, 'refresh_schedule_logic')
        refresh.start(); self.addCleanup(refresh.stop)
        storage.cars_table.truncate()
        self.car_model = twin_imports.create({'car.glb': glb(120)}, 'EV9 model', 'car')

    def create_car(self, **extra):
        response = self.client.post('/api/cars', headers=self.parent,
            json={'id': 'ev9', 'name': 'Family EV9', 'twin_model': self.car_model['id'], **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['doc_id']

    def test_drive_save_round_trips_model_and_clear(self):
        doc = self.create_car(body_type='suv')
        row = next(c for c in self.client.get('/api/cars', headers=self.parent).json() if c['doc_id'] == doc)
        self.assertEqual(row['twin_model'], self.car_model['id'])
        row['name'] = 'Renamed EV9'
        response = self.client.put(f'/api/cars/{doc}', headers=self.parent, json=row)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(storage.get_all_cars()[0]['twin_model'], self.car_model['id'])
        row['twin_model'] = None
        self.assertEqual(self.client.put(f'/api/cars/{doc}', headers=self.parent, json=row).status_code, 200)
        self.assertIsNone(storage.get_all_cars()[0]['twin_model'])

    def test_missing_and_wrong_kind_models_refused_on_create_and_update(self):
        wrong = twin_imports.create({'chair.glb': glb()}, 'Chair', 'furniture')
        doc = self.create_car()
        for asset in ('import-' + '0' * 32, wrong['id'], ''):
            for method, url in (('POST', '/api/cars'), ('PUT', f'/api/cars/{doc}')):
                with self.subTest(asset=asset, method=method):
                    response = self.client.request(method, url, headers=self.parent,
                        json={'name': 'Family EV9', 'twin_model': asset})
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertIsInstance(response.json()['detail'], str)
        self.assertEqual(storage.get_all_cars()[0]['twin_model'], self.car_model['id'])

    def test_delete_and_kind_change_name_using_car_even_when_disabled(self):
        self.create_car(is_disabled=True)
        url = '/api/house/editor/imports/' + self.car_model['id']
        for method, body in (('DELETE', None), ('PATCH', {'name': 'EV9 model', 'kind': 'decor'})):
            response = self.client.request(method, url, headers=self.parent, json=body)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn('Family EV9', response.json()['detail'])
        self.assertEqual(twin_imports.get(self.car_model['id'])['kind'], 'car')

    def upload_lod(self, data, name='lod1.glb'):
        body = {'name': 'EV9 model', 'asset_id': self.car_model['id'], 'lod': name,
                'size': len(data), 'files': [{'name': name, 'size': len(data)}], 'triangles': 999999}
        response = self.client.post('/api/house/editor/imports/uploads', headers=self.parent, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        url = '/api/house/editor/imports/uploads/' + response.json()['upload_id']
        for index, offset in enumerate(range(0, len(data), twin_imports.CHUNK_BYTES)):
            response = self.client.put(f'{url}/{index}', headers=self.parent,
                content=data[offset:offset + twin_imports.CHUNK_BYTES])
            self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post(url + '/finish', headers=self.parent)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_lod_attaches_same_entry_and_records_server_measured_count_and_bytes(self):
        data = glb(27)
        result = self.upload_lod(data)
        self.assertEqual(result['id'], self.car_model['id'])
        self.assertEqual(result['lods'], [{'name': 'lod1.glb', 'triangles': 27, 'bytes': len(data)}])
        self.assertEqual(len(twin_imports.catalog()), 1)
        self.assertEqual(result['triangles'], 120)
        served = self.client.get(f"/api/house/twin/imports/{result['id']}/lod1.glb", headers=self.parent)
        self.assertEqual(served.status_code, 200, served.text)
        self.assertEqual(served.content, data)
        result = self.upload_lod(glb(6), 'lod2.glb')
        self.assertEqual([l['name'] for l in result['lods']], ['lod1.glb', 'lod2.glb'])
        self.assertEqual((twin_imports.root() / result['id'] / 'car.glb').read_bytes(), glb(120))

    def test_derived_versions_bypass_uploaded_and_unpacked_limits(self):
        data = glb(8, padded_bytes=1024 * 1024 + 1024)
        with patch.object(twin_imports, 'limit_mb', return_value=1), patch.object(twin_imports, 'unpacked_limit_mb', return_value=1):
            result = self.upload_lod(data)
            ordinary = self.client.post('/api/house/editor/imports/uploads', headers=self.parent,
                json={'name': 'Original', 'size': len(data), 'files': [{'name': 'large.glb', 'size': len(data)}]})
            self.assertEqual(ordinary.status_code, 400, ordinary.text)
        self.assertEqual(result['lods'][0]['bytes'], len(data))

    def test_derived_cap_and_names_are_enforced(self):
        self.assertEqual(twin_imports.LOD_MAX_BYTES, 50 * 1024 * 1024)
        for size, name in ((twin_imports.LOD_MAX_BYTES + 1, 'lod1.glb'), (20, 'car.glb')):
            response = self.client.post('/api/house/editor/imports/uploads', headers=self.parent,
                json={'name': 'EV9 model', 'asset_id': self.car_model['id'], 'lod': name,
                      'size': size, 'files': [{'name': name, 'size': size}]})
            self.assertEqual(response.status_code, 400, response.text)
        with patch.object(twin_imports, 'LOD_MAX_BYTES', 20), self.assertRaisesRegex(ValueError, '50 MB'):
            twin_imports.attach_lod(self.car_model['id'], 'lod1.glb', glb())

    def test_derived_upload_requires_parent(self):
        url = '/api/house/editor/imports/uploads'
        self.assertEqual(auth.resolve('POST', url), auth.PARENTS)
        data = glb()
        for headers in ({}, self.child):
            response = self.client.post(url, headers=headers,
                json={'name': 'EV9 model', 'asset_id': self.car_model['id'], 'lod': 'lod1.glb',
                      'size': len(data), 'files': [{'name': 'lod1.glb', 'size': len(data)}]})
            self.assertIn(response.status_code, (401, 403), response.text)


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        storage.db.close()
        gc.collect()
        DATA.cleanup()
