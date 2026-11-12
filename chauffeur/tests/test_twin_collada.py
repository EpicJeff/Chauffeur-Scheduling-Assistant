"""Collada/KMZ run through authenticated chunk, confirm and resource routes."""
import gc
import unittest
from unittest.mock import patch

import test_twin_import_chunks as chunks
from collada_fixture import dae, packed, PNG, TGA


class ColladaTests(unittest.TestCase):
    setUpClass = chunks.ChunkTests.__dict__['setUpClass']
    setUp = chunks.ChunkTests.setUp
    start = chunks.ChunkTests.start
    put = chunks.ChunkTests.put

    def upload(self, files):
        raw = b''.join(files.values())
        path = self.start(raw, [{'name': n, 'size': len(d)} for n, d in files.items()])
        self.assertEqual(self.put(path, 0, raw).status_code, 200)
        return self.client.post(path + '/finish', headers=self.parent)

    def test_loose_dae_png_and_tga_confirm_and_serving(self):
        for texture, data in [('texture.png', PNG), ('texture.tga', TGA)]:
            response = self.upload({'folder/scene.dae': dae('../' + texture), texture: data})
            self.assertEqual(response.status_code, 200, response.text)
            entry = response.json()
            self.assertIsNone(entry['triangles'])
            route = '/api/house/editor/imports/' + entry['id']
            response = self.client.patch(route, headers=self.parent,
                json={'name': 'Collada', 'triangles': 1, 'size': [2.54, 5.08, 1.27]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['triangles'], 1)
            resource = '/api/house/twin/imports/' + entry['id'] + '/' + texture
            self.assertEqual(self.client.get(resource, headers=self.child).content, data)

    def test_kmz_and_zip_keep_original_and_choose_model(self):
        for ext in ('kmz', 'zip'):
            files = {'models/scene.dae': dae('../textures/texture.png'), 'textures/texture.png': PNG}
            if ext == 'kmz':
                files['doc.kml'] = b'<kml><Placemark><Model><Link><href>models/scene.dae</href></Link></Model></Placemark></kml>'
            raw = packed(files)
            response = self.upload({'model.' + ext: raw})
            self.assertEqual(response.status_code, 200, response.text)
            entry = response.json()
            self.assertEqual(entry['model'], 'model.kmz' if ext == 'kmz' else 'models/scene.dae')
            self.assertEqual((chunks.twin_imports.root() / entry['id'] / ('model.' + ext)).read_bytes(), raw)
            response = self.client.patch('/api/house/editor/imports/' + entry['id'], headers=self.parent,
                json={'name': ext, 'triangles': 570000})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()['heavy'])

    def test_exactly_one_model_and_kmz_kml_validation(self):
        for files in ({'a.dae': dae(), 'b.dae': dae()},
                      {'a.dae': dae(), 'a.gltf': chunks.model()},
                      {'a.kmz': packed({'a.dae': dae(), 'b.dae': dae()})},
                      {'a.kmz': packed({'a.dae': dae(), 'doc.kml': b'<kml/>'})},
                      {'a.kmz': packed({'a.dae': dae('missing.png')}), 'missing.png': PNG}):
            response = self.upload(files)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIsInstance(response.json()['detail'], str)

    def test_confirmation_requires_integer_count_limits_and_keeps_gltf_server_count(self):
        entry = self.upload({'a.dae': dae()}).json()
        route = '/api/house/editor/imports/' + entry['id']
        response = self.client.patch(route, headers=self.parent, json={'name': 'Missing count'})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('triangle count', response.json()['detail'])
        for count in (None, True, -1, 1.5, '3', 1200000):
            response = self.client.patch(route, headers=self.parent, json={'name': 'Bad', 'triangles': count})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn('triangle', response.json()['detail'])
            self.assertIsNone(chunks.twin_imports.get(entry['id'])['triangles'])
        for count, heavy in ((300000, False), (570000, True), (1000000, True)):
            response = self.client.patch(route, headers=self.parent, json={'name': 'Good', 'triangles': count})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['heavy'], heavy)
        gltf = self.upload({'a.gltf': chunks.model(570000)}).json()
        response = self.client.patch('/api/house/editor/imports/' + gltf['id'], headers=self.parent,
            json={'name': 'glTF', 'triangles': 1})
        self.assertEqual(response.json()['triangles'], 570000)

    def test_external_missing_and_invalid_xml_resources_refused(self):
        for uri in ('../../secret.png', 'https://evil.test/x.png', '/texture.png',
                    'file:///C:/texture.png', r'C:\texture.png', '%2e%2e/texture.png', 'missing.png'):
            for ext in ('dae', 'kmz', 'zip'):
                files = {'a.dae': dae(uri), 'texture.png': PNG}
                response = self.upload(files if ext == 'dae' else {'a.' + ext: packed(files)})
                self.assertEqual(response.status_code, 400, (uri, ext, response.text))
        for data in (b'<xml/>', b'<COLLADA>', b'<!DOCTYPE COLLADA [<!ENTITY x "x">]><COLLADA/>'):
            self.assertEqual(self.upload({'a.dae': data}).status_code, 400)

    def test_kmz_budgets_and_zip_guards_still_apply(self):
        for files, message in (({'a.dae': dae(), '../bad': b'x'}, 'relative'),
                               ({'a.dae': dae(), **{str(i): b'' for i in range(512)}}, '512')):
            response = self.upload({'a.kmz': packed(files)})
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn(message, response.json()['detail'])
        with patch.object(chunks.twin_imports, 'unpacked_limit_mb', return_value=0):
            response = self.upload({'a.kmz': packed({'a.dae': dae()})})
            self.assertEqual(response.status_code, 400)
            self.assertIn('unpacks', response.json()['detail'])


if __name__ == '__main__':
    try:
        unittest.main()
    finally:
        chunks.storage.db.close()
        gc.collect()
        chunks.DATA.cleanup()
