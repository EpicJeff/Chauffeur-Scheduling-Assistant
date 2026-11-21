"""Stage preferences through real routes, rendered drawer and its runtime save path."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_stage_')
os.environ.pop('HA_BASE_URL', None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from services import auth, settings_registry, storage, twin_stage, twin_store
import main


PLAN = {'buildings': [{'position': [10, 20], 'rotation': 90, 'walls': [
    {'from': [0, 0], 'to': [20, 0]}, {'from': [20, 0], 'to': [20, 10]}]}],
    'site': {'lot': [[-50, -40], [60, -40], [60, 80], [-50, 80]]}}


class StageTests(unittest.TestCase):
    def setUp(self):
        for table in (storage.members_table, storage.member_tokens_table, storage.trusted_devices_table,
                      storage.app_state_table, storage.settings_table):
            table.truncate()
        storage.add_member({'id': 'parent', 'name': 'Parent', 'role': 'parent'})
        storage.add_member({'id': 'kid', 'name': 'Kid', 'role': 'child'})
        self.parent = {'X-Member-Token': storage.create_member_token('parent', proof='password')}
        self.kid = {'X-Member-Token': storage.create_member_token('kid', proof='password')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('wall', 'Wall', 'parent')}
        self.client = TestClient(main.app)
        self.url = '/api/house/twin/stage'
        self.plan = patch.object(twin_store, 'current', return_value=PLAN)
        self.plan.start()
        self.addCleanup(self.plan.stop)

    def test_default_beyond_farthest_corner_from_rotated_house_centre(self):
        response = self.client.get(self.url, headers=self.parent)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertAlmostEqual(result['centre'][0], 5)
        self.assertAlmostEqual(result['centre'][1], -30)
        self.assertAlmostEqual(result['radius'], 120 + (55**2 + 70**2)**.5)
        self.assertEqual(result['radius'], result['default_radius'])
        self.assertIsNone(result['radius_override'])
        self.assertIsNone(storage.get_app_state(twin_stage.KEY), 'Reading a default must not store it.')

    def test_default_clamp_and_no_lot_fallback(self):
        self.assertEqual(twin_stage.read({'buildings': []})['radius'], 120)
        large = {'site': {'lot': [[-2000, -2000], [2000, -2000], [0, 2000]]}}
        self.assertEqual(twin_stage.read(large)['radius'], 1000)

    def test_override_range_round_trip_reset_and_no_model_or_schedule_write(self):
        storage.settings_table.insert({'house_twin': {'current': 7, 'rounds': [7]}})
        before = storage.get_settings()['house_twin']
        with patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
            for radius in (30, 321.5, 1000):
                response = self.client.put(self.url, headers=self.parent, json={'radius': radius})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['radius'], radius)
                self.assertEqual(storage.get_app_state(twin_stage.KEY), radius)
                self.assertEqual(self.client.get(self.url, headers=self.parent).json()['radius'], radius)
            self.assertEqual(self.client.put(self.url, headers=self.parent, json={'radius': None}).status_code, 200)
            self.assertIsNone(storage.get_app_state(twin_stage.KEY))
            dirty.assert_not_called()
        self.assertEqual(storage.get_settings()['house_twin'], before)

    def test_invalid_payload_is_422_and_preserves_previous_value(self):
        storage.set_app_state(twin_stage.KEY, 200)
        for value in (29.99, 1000.01, True, False, '120', [], {}):
            response = self.client.put(self.url, headers=self.parent, json={'radius': value})
            self.assertEqual(response.status_code, 422, (value, response.text))
            self.assertEqual(storage.get_app_state(twin_stage.KEY), 200)
        for body in ({}, {'radius': 120, 'other': 1}):
            self.assertEqual(self.client.put(self.url, headers=self.parent, json=body).status_code, 422)
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError):
                twin_stage.save({'radius': value})

    def test_both_settings_routes_are_parents_only(self):
        for method in ('GET', 'PUT'):
            self.assertEqual(auth.resolve(method, self.url), auth.PARENTS)
        with patch.object(auth, 'enforcing', return_value=True):
            for headers in (self.kid, self.panel, {}):
                for method in ('GET', 'PUT'):
                    response = self.client.request(method, self.url, headers=headers,
                                                   **({'json': {'radius': 200}} if method == 'PUT' else {}))
                    self.assertIn(response.status_code, (401, 403), (method, headers, response.text))

    def test_viewer_and_editor_serve_same_stage_even_when_editor_plan_is_unchanged(self):
        storage.set_app_state(twin_stage.KEY, 280)
        with patch('services.twin_site.start_bearing_job'), patch('services.twin_build.latest', return_value=None), \
                patch.object(twin_store, 'current_id', return_value=7):
            viewer = self.client.get('/api/house/twin', headers=self.panel)
            editor = self.client.get('/api/house/editor/state?have_round=7', headers=self.parent)
        self.assertEqual(viewer.status_code, 200, viewer.text)
        self.assertEqual(editor.status_code, 200, editor.text)
        self.assertEqual(viewer.json()['stage'], editor.json()['stage'])
        self.assertEqual(viewer.json()['stage']['radius'], 280)
        self.assertNotIn('plan', editor.json(), 'Radius must arrive even when the plan is elided.')

    def test_registry_and_rendered_desk_only_drawer(self):
        entry = settings_registry.BY_KEY[twin_stage.KEY]
        self.assertEqual((entry['page'], entry['anchor']), ('house/twin', 'twin-stage-settings'))
        self.assertEqual(settings_registry.audit(), {'missing': [], 'stale': []})
        self.assertNotIn(twin_stage.KEY, [e['key'] for e in settings_registry.audit_ui()['unreachable']])
        from test_settings_drawer import _elements, _render
        for query in ('', 'panel=true', 'kiosk=true', 'tabs=twin', 'panel=true&kiosk=true'):
            rows = _elements(_render('/house/twin', query))
            field = [(attrs, parents) for attrs, parents in rows if attrs.get('id') == 'house_twin_stage_radius_ft']
            self.assertEqual(len(field), 0 if query else 1, query)
            scrub = [attrs for attrs, _ in rows if attrs.get('id') == 'twin-time-scrub']
            self.assertEqual(len(scrub), 1, query)
            self.assertEqual((scrub[0]['min'], scrub[0]['max']), ('0', '24'))
            self.assertAlmostEqual(float(scrub[0]['step']), 1 / 12)
            if not query:
                attrs, parents = field[0]
                self.assertEqual((attrs['min'], attrs['max']), ('30', '1000'))
                self.assertTrue(any(a.get('data-settings-for') == 'twin' for a in parents))

    def test_mirror_setting_round_trip_auth_payload_and_validation(self):
        key = twin_stage.MIRROR_KEY
        entry = settings_registry.BY_KEY[key]
        self.assertEqual((entry['group'], entry['page'], entry['anchor']),
                         (settings_registry.BY_KEY[twin_stage.KEY]['group'], 'house/twin', 'twin-stage-settings'))
        self.assertEqual(self.client.get(self.url, headers=self.parent).json()['mirror_still_hz'], 10)
        self.assertIsNone(storage.get_app_state(key))
        url = '/api/house/twin/mirror'
        self.assertEqual(auth.resolve('PUT', url), auth.PARENTS)
        with patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
            for hz in (0, 30, 15, 10, 5, 2):
                response = self.client.put(url, headers=self.parent, json={'mirror_still_hz': hz})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['mirror_still_hz'], hz)
                self.assertEqual(storage.get_app_state(key), hz)
                self.assertEqual(self.client.get(self.url, headers=self.parent).json()['mirror_still_hz'], hz)
            dirty.assert_not_called()
        for body in ({}, {'mirror_still_hz': 10, 'extra': 1}, *[{'mirror_still_hz': v} for v in (None, True, False, '10', -1, 60, [], {})]):
            self.assertEqual(self.client.put(url, headers=self.parent, json=body).status_code, 422, body)
            self.assertEqual(storage.get_app_state(key), 2)
        with patch.object(auth, 'enforcing', return_value=True):
            for headers in (self.kid, self.panel, {}):
                self.assertIn(self.client.put(url, headers=headers, json={'mirror_still_hz': 10}).status_code, (401, 403))
        with patch('services.twin_site.start_bearing_job'), patch('services.twin_build.latest', return_value=None), patch.object(twin_store, 'current_id', return_value=7):
            self.assertEqual(self.client.get('/api/house/twin', headers=self.panel).json()['stage']['mirror_still_hz'], 2)
            self.assertEqual(self.client.get('/api/house/editor/state?have_round=7', headers=self.parent).json()['stage']['mirror_still_hz'], 2)
        from test_settings_drawer import _elements, _render
        for query in ('', 'panel=true', 'kiosk=true', 'tabs=twin'):
            rows = _elements(_render('/house/twin', query))
            fields = [(a, parents) for a, parents in rows if a.get('id') == key]
            self.assertEqual(len(fields), 0 if query else 1)
            if fields:
                self.assertTrue(any(a.get('data-settings-for') == 'twin' for a in fields[0][1]))
                options = [a['value'] for a, parents in rows if 'value' in a and any(p.get('id') == key for p in parents)]
                self.assertEqual(options, ['0', '30', '15', '10', '5', '2'])

    def test_probe_cloud_setting_round_trip_auth_payload_and_drawer(self):
        key = twin_stage.PROBE_CLOUD_KEY
        entry = settings_registry.BY_KEY[key]
        self.assertEqual((entry['group'], entry['page'], entry['anchor']),
                         (settings_registry.BY_KEY[twin_stage.KEY]['group'], 'house/twin', 'twin-stage-settings'))
        self.assertEqual(self.client.get(self.url, headers=self.parent).json()['probe_cloud_s'], 30)
        self.assertIsNone(storage.get_app_state(key))
        url = '/api/house/twin/probe-cloud'
        self.assertEqual(auth.resolve('PUT', url), auth.PARENTS)
        before = storage.get_settings().get('house_twin')
        with patch.object(storage, 'mark_all_daily_schedules_dirty') as dirty:
            for seconds in (4, 10, 30, 60):
                response = self.client.put(url, headers=self.parent, json={'probe_cloud_s': seconds})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['probe_cloud_s'], seconds)
                self.assertEqual(storage.get_app_state(key), seconds)
                self.assertEqual(self.client.get(self.url, headers=self.parent).json()['probe_cloud_s'], seconds)
            dirty.assert_not_called()
        self.assertEqual(storage.get_settings().get('house_twin'), before)
        for body in ({}, {'probe_cloud_s': 30, 'extra': 1}, *[{'probe_cloud_s': v} for v in (None, True, False, '30', -1, 0, 5, [], {})]):
            self.assertEqual(self.client.put(url, headers=self.parent, json=body).status_code, 422, body)
            self.assertEqual(storage.get_app_state(key), 60)
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaises(ValueError):
                twin_stage.save_probe_cloud({'probe_cloud_s': value})
        with patch.object(auth, 'enforcing', return_value=True):
            for headers in (self.kid, self.panel, {}):
                self.assertIn(self.client.put(url, headers=headers, json={'probe_cloud_s': 30}).status_code, (401, 403))
        with patch('services.twin_site.start_bearing_job'), patch('services.twin_build.latest', return_value=None), patch.object(twin_store, 'current_id', return_value=7):
            self.assertEqual(self.client.get('/api/house/twin', headers=self.panel).json()['stage']['probe_cloud_s'], 60)
            self.assertEqual(self.client.get('/api/house/editor/state?have_round=7', headers=self.parent).json()['stage']['probe_cloud_s'], 60)
        storage.set_app_state(key, '10')
        self.assertEqual(twin_stage.read()['probe_cloud_s'], 30, 'invalid persisted value falls back safely')
        from test_settings_drawer import _elements, _render
        for query in ('', 'panel=true', 'kiosk=true', 'tabs=twin', 'panel=true&kiosk=true'):
            rows = _elements(_render('/house/twin', query))
            fields = [(a, parents) for a, parents in rows if a.get('id') == key]
            self.assertEqual(len(fields), 0 if query else 1)
            if fields:
                self.assertTrue(any(a.get('id') == 'twin-stage-settings' for a in fields[0][1]))
                self.assertEqual(fields[0][0]['aria-describedby'], 'twin-probe-cloud-help')
                options = [a for a, parents in rows if 'value' in a and any(p.get('id') == key for p in parents)]
                self.assertEqual([a['value'] for a in options], ['4', '10', '30', '60'])
                self.assertEqual([a['value'] for a in options if 'selected' in a], ['30'])

    def test_drawer_runtime_load_save_reset_refusal_and_stop(self):
        from twin_editor_dom import PRELUDE, run_node
        driver = r'''
const {mountStageSettings,defaultStage} = await import(file('static/twin/stage_settings.js'));
for (const [plan,expected] of input.defaults) {
 const got=defaultStage(plan);
 for (const axis of [0,1]) assert.ok(Math.abs(got.centre[axis]-expected.centre[axis])<1e-9);
 assert.ok(Math.abs(got.radius-expected.radius)<1e-9);assert.equal(got.radius_override,null);
}
const calls=[], stages=[], statuses=[], mirrors=[], intervals=[];
const field=document.getElementById('house_twin_stage_radius_ft');
const save=document.getElementById('twin-stage-save'), reset=document.getElementById('twin-stage-reset');
window.chfSettingsSaving=()=>statuses.push('saving');window.chfSettingsSaved=(ok,msg)=>statuses.push([ok,msg]);
let fail=false;
const api=async(path,init)=>{
 calls.push([path,init]);
 if(fail)return {ok:false,json:async()=>({detail:'Radius refused.'})};
 return {ok:true,json:async()=>({centre:[5,-30],radius:init ? (JSON.parse(init.body).radius ?? 210) : 200,default_radius:210,radius_override:200,mirror_still_hz:init && path.endsWith('/mirror') ? JSON.parse(init.body).mirror_still_hz : 10,probe_cloud_s:init && path.endsWith('/probe-cloud') ? JSON.parse(init.body).probe_cloud_s : 30})};
};
const mounted=mountStageSettings({setStage:s=>stages.push(s),setMirrorStillHz:hz=>mirrors.push(hz),setProbeCloudSeconds:s=>intervals.push(s)},{api});
const cloud=document.getElementById('house_twin_probe_cloud_s'),cloudSave=document.getElementById('twin-probe-cloud-save');
assert.equal(cloud.disabled,true);click(cloudSave);assert.equal(calls.length,0,'cannot save before loading');
await mounted.reload();assert.equal(field.value,'200');assert.equal(save.disabled,false);
assert.equal(cloud.value,'30');assert.equal(cloud.disabled,false);
cloud.value='60';click(cloudSave);await new Promise(r=>setTimeout(r,0));
assert.equal(calls.at(-1)[0],'api/house/twin/probe-cloud');assert.equal(calls.at(-1)[1].method,'PUT');assert.deepEqual(JSON.parse(calls.at(-1)[1].body),{probe_cloud_s:60});assert.deepEqual(intervals,[60]);
const mirror=document.getElementById('house_twin_mirror_still_hz');assert.equal(mirror.value,'10');
mirror.value='5';click(document.getElementById('twin-mirror-save'));await new Promise(r=>setTimeout(r,0));
assert.equal(calls.at(-1)[0],'api/house/twin/mirror');assert.equal(JSON.parse(calls.at(-1)[1].body).mirror_still_hz,5);assert.deepEqual(mirrors,[5]);
field.value='250';click(save);await new Promise(r=>setTimeout(r,0));
assert.equal(JSON.parse(calls.at(-1)[1].body).radius,250);assert.equal(stages.at(-1).radius,250);
click(reset);await new Promise(r=>setTimeout(r,0));assert.equal(JSON.parse(calls.at(-1)[1].body).radius,null);assert.equal(field.value,'210');
field.value='2';const count=calls.length;click(save);await new Promise(r=>setTimeout(r,0));assert.equal(calls.length,count);assert.equal(statuses.at(-1)[0],false);
fail=true;field.value='300';click(save);await new Promise(r=>setTimeout(r,0));assert.equal(statuses.at(-1)[0],false);assert.equal(stages.at(-1).radius,210);
const mirrorCount=mirrors.length;click(document.getElementById('twin-mirror-save'));await new Promise(r=>setTimeout(r,0));assert.equal(mirrors.length,mirrorCount);assert.equal(statuses.at(-1)[0],false);
click(cloudSave);await new Promise(r=>setTimeout(r,0));assert.deepEqual(intervals,[60]);assert.equal(statuses.at(-1)[0],false);
mounted.stop();const stopped=calls.length;click(reset);click(document.getElementById('twin-mirror-save'));click(cloudSave);await new Promise(r=>setTimeout(r,0));assert.equal(calls.length,stopped);
const getElement=document.getElementById.bind(document);
document.getElementById=id=>id==='twin-stage-settings' ? null : getElement(id);
const wall=mountStageSettings({},{api});await wall.reload();assert.equal(calls.length,stopped);wall.stop();
console.log('stage drawer runtime passed');
'''
        plans = [PLAN, {}, {'buildings': [{'levels': [{'outline': [[0, 0], [20, 0], [20, 12]]}]}]},
                 {'site': {'lot': [[-2000, -2000], [2000, -2000], [0, 2000]]}}]
        code, output = run_node(PRELUDE + driver, {'root': ROOT.as_posix(),
                               'defaults': [[plan, twin_stage.default_stage(plan)] for plan in plans]})
        self.assertEqual(code, 0, output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
