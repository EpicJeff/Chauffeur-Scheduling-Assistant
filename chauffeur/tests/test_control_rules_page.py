"""The rules page, its API and the two warnings (Task 6 of
docs/superpowers/plans/2026-11-09-ha-control-permissions.md; brief in
.superpowers/sdd/2026-11-09-ha-control-permissions/task-6-brief.md).

A parent sees and edits one grid of who may control what, in Config > People.
The page warns about scripts Chauffeur cannot read, and about Home Assistant
voice pipelines that answer commands locally before Argyle ever sees them.

CONTRACT these tests fix (the names did not exist when they were written):

* Routes, parent tier only (a rule for each in services/auth.py):
  - GET  /api/ha/control/rules -> {'rules': dict, 'kinds': [{'id','label'}],
         'warnings': {'unreadable_scripts': [...], 'local_handling': dict|None}}
  - POST /api/ha/control/rules, body = the whole grid -> validated, stored as
         settings['ha_control'] by merging into the settings row and saving it
         with storage.update_settings (which REPLACES the whole row, so every
         other setting must survive), returns the saved grid; a bad grid is a
         400 whose detail is the validate_rules sentence.
* control_rules.local_handling_warning(rules) -> dict | None.
* Component file: chauffeur/templates/components/control_rules.html, included
  in config.html (Config > People). Its root element carries the attribute
  `data-control-rules` and `x-data="controlRulesPage()"`.
* Alpine factory: a <script> in that component assigns
  `window.controlRulesPage = function () { return {...}; }`. The script runs
  with no DOM at load time and its methods use no Alpine magics ($el, $refs,
  $watch), so it runs under node. The returned object has:
    load()                       GET  chfBase + 'api/ha/control/rules'; fills
                                 this.rules, this.kinds, this.warnings
    setPerson(role, kind, value) sets rules.people[role][kind], then saves
    setPlace(place, kind, value) sets rules.places[place][kind], then saves
    save()                       POST chfBase + 'api/ha/control/rules' with the
                                 WHOLE grid; a refusal goes to showGlobalAlert
    placeLabel(place, kind)      'Yes' | 'No' | 'Ask who'; Yes on a proof kind
                                 reads 'Ask who' (or 'Ask who (needs proof)')
    placeOptions(place, kind)    [{value, label}]: Yes / Ask who / No, or only
                                 Ask who / No on a kind that needs proof
    placeSelected(place, kind)   the value shown selected ('ask' for a stored
                                 'yes' on a proof kind)
  Saving is immediate (no debounce), like saveAuthSettings().

Stubbed ha_api; the real FastAPI app with auth enforcement on; settings held
in memory so a save can be read back.

Run from chauffeur/ with HA_BASE_URL unset:  python tests/test_control_rules_page.py
"""
import copy
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from fastapi.testclient import TestClient

import main
from services import control_rules as cr, control_scripts as cs, ha_api, storage

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(HERE, 'templates')
COMPONENT = os.path.join(TPL, 'components', 'control_rules.html')
PANEL_SETTINGS = os.path.join(TPL, 'components', 'panel_settings.html')
BASE = '/api/hassio_ingress/tok/'

KIND_LABELS = [
    ('lights', 'Lights'), ('switches', 'Switches & fans'), ('media', 'TV & music'),
    ('climate', 'Climate'), ('blinds', 'Blinds & shades'),
    ('garage', 'Garage, doors & gates'), ('locks', 'Locks'), ('alarm', 'Alarm'),
    ('other', 'Everything else'),
]


def state(eid, st='off', **attrs):
    return {'entity_id': eid, 'state': st, 'attributes': attrs}


STATES = [
    state('light.a', friendly_name='Kitchen light'),
    state('lock.front', 'locked', friendly_name='Front door'),
    state('lock.back', 'locked', friendly_name='Back door'),
    state('cover.garage_door', 'closed', device_class='garage', friendly_name='Garage'),
    state('script.goodnight', friendly_name='Goodnight'),
    state('script.open_garage', friendly_name='Open garage'),
    state('script.lights_on', friendly_name='Lights on'),
    state('scene.lockdown', friendly_name='Lockdown', entity_id=['lock.front']),
    state('scene.movie', friendly_name='Movie', entity_id=['light.a']),
]

PIPELINES = {
    'pipelines': [
        {'id': 'p1', 'name': 'Home Assistant', 'conversation_engine': 'conversation.home_assistant',
         'prefer_local_intents': True},
        {'id': 'p2', 'name': 'Argyle', 'conversation_engine': 'conversation.chauffeur',
         'prefer_local_intents': False},
    ],
    'preferred_pipeline': 'p2',
}

SCRIPT_CONFIGS = {
    'script.goodnight': {'sequence': [
        {'action': 'light.turn_off', 'target': {'entity_id': '{{ states("input_text.room") }}'}}]},
    'script.open_garage': {'sequence': [
        {'action': 'cover.open_cover', 'target': {'entity_id': 'cover.garage_door'}}]},
    'script.lights_on': {'sequence': [
        {'action': 'light.turn_on', 'target': {'entity_id': 'light.a'}}]},
}
RELATED = {'script.open_garage': {'entity': ['cover.garage_door']},
           'script.lights_on': {'entity': ['light.a']}}


def _clear_pipeline_cache():
    # Contract (review ruling 5): the ~60 s pipeline-list cache can be cleared.
    clear = getattr(cr, 'clear_pipeline_cache', None)
    if clear:
        clear()


def _member(mid, role):
    if not storage.get_member(mid):
        storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active'})
    return storage.get_member(mid)


def _permissive():
    rules = cr.default_rules({})
    rules['proof'] = {k: False for k in cr.KINDS}
    for row in rules['people'].values():
        row.update({k: 'yes' for k in cr.KINDS})
    for row in rules['places'].values():
        row.update({k: 'yes' for k in cr.KINDS})
    return rules


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _member('mum', 'parent')
        _member('kid', 'child')
        cls.mum = storage.create_member_token('mum', proof='password', minted_on='personal')
        cls.kid = storage.create_member_token('kid', proof='pin', minted_on='personal')
        cls.panel = storage.enrol_device_token('panel-rules', 'Rules panel', by_member='mum')

    def setUp(self):
        self.pipelines = copy.deepcopy(PIPELINES)
        self.exposed = {'lock.front': True, 'light.a': True, 'lock.back': False}
        self.orig = {n: getattr(ha_api, n) for n in (
            'mode', 'is_available', 'get_states', 'get_state', 'ws_command', 'get_exposed',
            'get_area_map', 'get_entity_registry', 'get_device_registry', 'get_script_config')}
        ha_api.mode = lambda: 'direct'
        ha_api.is_available = lambda: True
        ha_api.get_states = lambda ttl=5: copy.deepcopy(STATES)
        ha_api.get_state = lambda eid: next((copy.deepcopy(s) for s in STATES if s['entity_id'] == eid), None)
        ha_api.get_area_map = lambda ttl=60: []
        ha_api.get_entity_registry = lambda ttl=300: []
        ha_api.get_device_registry = lambda ttl=300: []
        ha_api.get_script_config = lambda object_id: None
        ha_api.get_exposed = lambda ttl=60: dict(self.exposed)

        def ws(command, timeout=8, **fields):
            if command == 'assist_pipeline/pipeline/list':
                return copy.deepcopy(self.pipelines)
            if command == 'homeassistant/expose_entity/list':
                return {'exposed_entities': {k: {'conversation': v} for k, v in self.exposed.items()}}
            if command == 'search/related':
                return copy.deepcopy(RELATED.get(fields.get('item_id'), {}))
            if command == 'script/config':
                cfg = SCRIPT_CONFIGS.get(fields.get('entity_id'))
                return {'config': copy.deepcopy(cfg)} if cfg else None
            return None
        ha_api.ws_command = ws
        cs.clear_cache()
        _clear_pipeline_cache()

        # Settings live in memory: update_settings replaces the WHOLE row,
        # exactly as storage does, so a save that drops other keys shows up.
        base = dict(storage.get_settings() or {})
        base.pop('ha_control', None)
        base.pop('panel_allow_unsafe_controls', None)
        self.store = {**base, 'auth_enforce': True, 'sentinel_setting': 'kept'}

        self.update_calls, self.patch_calls = [], []

        def save(data):
            self.update_calls.append(copy.deepcopy(data))
            self.store.clear()
            self.store.update(copy.deepcopy(data))

        def merge(updates):
            self.patch_calls.append(copy.deepcopy(updates))
            self.store.update(copy.deepcopy(updates))
        self.patches = [
            patch.object(storage, 'get_settings', side_effect=lambda: copy.deepcopy(self.store)),
            patch.object(storage, 'update_settings', side_effect=save),
            patch.object(storage, 'patch_settings', side_effect=merge),
        ]
        for p in self.patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        for n, fn in self.orig.items():
            setattr(ha_api, n, fn)
        cs.clear_cache()
        _clear_pipeline_cache()

    def get_rules(self, token=None, **headers):
        if token:
            headers['X-Member-Token'] = token
        return self.client.get('/api/ha/control/rules', headers=headers)

    def post_rules(self, body, token=None, **headers):
        if token:
            headers['X-Member-Token'] = token
        return self.client.post('/api/ha/control/rules', json=body, headers=headers)


class RulesApi(_Base):
    def test_rules_api_parent_only(self):
        r = self.get_rules(self.kid)
        self.assertEqual(r.status_code, 403, r.text)
        r = self.get_rules(**{'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 403, 'a wall panel is a place, not a parent: ' + r.text)
        r = self.post_rules(cr.default_rules({}), self.kid)
        self.assertEqual(r.status_code, 403, r.text)
        self.assertNotIn('ha_control', self.store)

        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body['rules'], cr.default_rules({}))
        self.assertEqual([(k['id'], k['label']) for k in body['kinds']], KIND_LABELS)
        self.assertEqual(len(body['kinds']), 9)
        self.assertIn('unreadable_scripts', body['warnings'])
        self.assertIn('local_handling', body['warnings'])

    def test_rules_api_round_trip(self):
        who = cr.Who(role='child', member_id='kid', place=None, proven=True)
        self.assertTrue(cr.check(who, ['light.a']).allowed, 'defaults let a child switch a light')

        grid = cr.default_rules({})
        grid['people']['child']['lights'] = 'no'
        grid['places']['panel']['locks'] = 'ask'
        grid['proof']['climate'] = True
        r = self.post_rules(grid, self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), grid, 'the POST returns the saved grid')

        self.assertEqual(self.store.get('ha_control'), grid)
        self.assertEqual(self.store.get('sentinel_setting'), 'kept',
                         'saving the grid must not wipe the rest of the settings row')
        self.assertTrue(self.store.get('auth_enforce'))

        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['rules'], grid)
        self.assertFalse(cr.check(who, ['light.a']).allowed, 'check() follows the saved grid')

    def test_rules_api_rejects_bad_grid(self):
        grid = cr.default_rules({})
        grid['people']['child']['lights'] = 'ask'   # a person is Yes or No, never Ask who
        r = self.post_rules(grid, self.mum)
        self.assertEqual(r.status_code, 400, r.text)
        detail = r.json().get('detail')
        self.assertIsInstance(detail, str, r.text)
        self.assertIn('child', detail)
        self.assertTrue(detail.strip().endswith('.'), f'a sentence, got {detail!r}')
        self.assertNotIn('ha_control', self.store, 'a refused grid is never saved')

        r = self.post_rules({'enabled': True}, self.mum)   # incomplete grid
        self.assertEqual(r.status_code, 400, r.text)
        self.assertNotIn('ha_control', self.store)


class Warnings(_Base):
    def test_local_handling_warning(self):
        warning = cr.local_handling_warning(cr.default_rules({}))
        self.assertIsNotNone(warning)
        self.assertEqual(warning['pipelines'], ['Home Assistant'])
        devices = {d['entity_id']: d for d in warning['devices']}
        self.assertIn('lock.front', devices)
        self.assertEqual(devices['lock.front']['kind'], 'locks')
        self.assertEqual(devices['lock.front']['name'], 'Front door')
        self.assertNotIn('lock.back', devices, 'not exposed to Assist, so HA voice cannot reach it')
        self.assertNotIn('light.a', devices, 'lights are not restricted by default')

        # The same warning rides the page payload.
        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        local = r.json()['warnings']['local_handling']
        self.assertEqual(local['pipelines'], ['Home Assistant'])
        self.assertIn('lock.front', [d['entity_id'] for d in local['devices']])

        # A kind is restricted by any role 'no' or any place not 'yes', even
        # with its proof box unchecked.
        rules = _permissive()
        self.assertIsNone(cr.local_handling_warning(rules), 'nothing restricted, nothing to warn about')
        rules['people']['guest']['lights'] = 'no'
        names = [d['entity_id'] for d in (cr.local_handling_warning(rules) or {}).get('devices', [])]
        self.assertEqual(names, ['light.a'])
        rules = _permissive()
        rules['places']['unknown_voice']['locks'] = 'ask'
        names = [d['entity_id'] for d in (cr.local_handling_warning(rules) or {}).get('devices', [])]
        self.assertEqual(names, ['lock.front'])

        # No pipeline prefers local handling: no warning.
        for p in self.pipelines['pipelines']:
            p['prefer_local_intents'] = False
        _clear_pipeline_cache()
        self.assertIsNone(cr.local_handling_warning(cr.default_rules({})))
        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()['warnings']['local_handling'])

    def test_local_handling_warning_no_ha(self):
        # Review Focus 4: no Home Assistant means no warning and a working page.
        ha_api.mode = lambda: 'unconfigured'
        ha_api.is_available = lambda: False
        ha_api.ws_command = lambda command, timeout=8, **fields: None
        ha_api.get_exposed = lambda ttl=60: {}
        ha_api.get_states = lambda ttl=5: []
        self.assertIsNone(cr.local_handling_warning(cr.default_rules({})))
        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()['warnings']['local_handling'])
        self.assertEqual(r.json()['warnings']['unreadable_scripts'], [])

        # A Home Assistant that fails mid-read degrades the same way.
        def boom(*a, **k):
            raise RuntimeError('HA went away')
        ha_api.mode = lambda: 'direct'
        ha_api.ws_command = boom
        ha_api.get_exposed = boom
        ha_api.get_states = boom
        cs.clear_cache()
        self.assertIsNone(cr.local_handling_warning(cr.default_rules({})))
        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(r.json()['warnings']['local_handling'])

    def test_unreadable_scripts_in_payload(self):
        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        rows = {row['entity_id']: row for row in r.json()['warnings']['unreadable_scripts']}
        self.assertIn('script.goodnight', rows, rows)
        self.assertEqual(rows['script.goodnight']['name'], 'Goodnight')
        self.assertTrue(rows['script.goodnight']['reason'].strip())
        self.assertNotIn('script.open_garage', rows, 'a readable script is judged by what it touches')


# --- the page --------------------------------------------------------------

NODE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
globalThis.window = globalThis;
const forbidden = [];
for (const name of ['alert', 'confirm', 'prompt']) {
  globalThis[name] = function () { forbidden.push(name); throw new Error('browser dialog: ' + name); };
}
const alerts = [];
globalThis.showGlobalAlert = function (msg) { alerts.push(String(msg)); };
globalThis.promptConfirm = async function () { return true; };
globalThis.promptInput = async function () { return null; };
function El() {
  const el = { style: {}, dataset: {}, children: [], classList: { add(){}, remove(){}, contains(){ return false; }, toggle(){} },
    appendChild(c){ el.children.push(c); return c; }, addEventListener(){}, removeEventListener(){},
    setAttribute(){}, getAttribute(){ return null; }, querySelector(){ return null; }, querySelectorAll(){ return []; } };
  return el;
}
globalThis.document = { getElementById(){ return null; }, createElement(){ return El(); },
  querySelector(){ return null; }, querySelectorAll(){ return []; }, addEventListener(){}, removeEventListener(){},
  body: El(), documentElement: El() };
globalThis.addEventListener = function () {};
globalThis.location = { pathname: '/config', search: '', origin: 'http://chauffeur.local', href: 'http://chauffeur.local/config' };
const mem = {};
globalThis.localStorage = { getItem(k){ return k in mem ? mem[k] : null; }, setItem(k, v){ mem[k] = String(v); }, removeItem(k){ delete mem[k]; } };
window.chfBase = input.base;

const calls = [];
let postStatus = 200, postBody = null;
globalThis.fetch = async function (url, opts) {
  opts = opts || {};
  const method = (opts.method || 'GET').toUpperCase();
  calls.push({ url: String(url), method, body: opts.body === undefined ? null : String(opts.body) });
  if (method === 'GET') return new Response(JSON.stringify(input.payload), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const body = postStatus === 200 ? (opts.body || '{}') : JSON.stringify(postBody);
  return new Response(body, { status: postStatus, headers: { 'Content-Type': 'application/json' } });
};
const flush = () => new Promise(r => setTimeout(r, 100));

(async function () {
  const out = { forbidden, alerts, calls };
  try {
    for (const src of input.scripts) vm.runInThisContext(src);
    out.factory = typeof window.controlRulesPage;
    if (typeof window.controlRulesPage !== 'function') { console.log(JSON.stringify(out)); return; }
    const page = window.controlRulesPage();
    await page.load(); await flush();
    out.loaded = { rules: page.rules, kinds: page.kinds };
    out.afterLoadCalls = calls.length;

    await page.setPerson('child', 'lights', 'no'); await flush();
    out.personPosts = calls.filter(c => c.method === 'POST').map(c => ({ url: c.url, body: JSON.parse(c.body) }));

    await page.setPlace('panel', 'locks', 'yes'); await flush();
    await page.setPlace('panel', 'climate', 'ask'); await flush();
    await page.setPlace('panel', 'alarm', 'no'); await flush();
    out.labels = {
      locks: page.placeLabel('panel', 'locks'),
      lights: page.placeLabel('panel', 'lights'),
      climate: page.placeLabel('panel', 'climate'),
      alarm: page.placeLabel('panel', 'alarm'),
    };
    out.lastPost = JSON.parse(calls.filter(c => c.method === 'POST').pop().body);

    postStatus = 400; postBody = { detail: input.refusal };
    await page.setPerson('child', 'media', 'no'); await flush();
    out.alertsAfterRefusal = alerts.slice();
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  console.log(JSON.stringify(out));
})();
"""


def _node():
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('node is not installed')
    return node


def _scripts(page_html, needle):
    blocks = re.findall(r'<script(\s[^>]*)?>(.*?)</script>', page_html, re.S)
    return [body for attrs, body in blocks if needle in body and 'src=' not in (attrs or '')]


def run_node(harness, payload):
    d = tempfile.mkdtemp(prefix='chf_rules_js_')
    try:
        js = os.path.join(d, 'harness.js')
        data = os.path.join(d, 'input.json')
        with open(js, 'w', encoding='utf-8') as f:
            f.write(harness)
        with open(data, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
        r = subprocess.run([_node(), js, data], capture_output=True, text=True,
                           encoding='utf-8', timeout=60)
        if r.returncode != 0 or not r.stdout.strip():
            raise AssertionError(f'node failed ({r.returncode}): {r.stderr[-3000:]}')
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(d, ignore_errors=True)


class Page(_Base):
    def config_page(self):
        r = self.client.get('/config', headers={'X-Member-Token': self.mum})
        self.assertEqual(r.status_code, 200, r.text[:500])
        return r.text

    def test_page_renders(self):
        self.assertTrue(os.path.exists(COMPONENT), f'missing component {COMPONENT}')
        page = self.config_page()
        self.assertIn('data-control-rules', page, 'the rules component is included in Config')
        self.assertIn('controlRulesPage()', page)
        text = html.unescape(page)
        for copy_line in (
            'Chauffeur can control Home Assistant devices',
            'Off: nothing anywhere operates a device. Reading still works.',
            'Needs proof of who you are',
            'Ask who needs voice ID turned on for the speaker.',
            "Each person's own access can narrow this further.",
            'Scripts that start other automations are judged only by what they touch directly.',
        ):
            self.assertIn(copy_line, text)

        scripts = _scripts(page, 'controlRulesPage')
        self.assertTrue(scripts, 'no inline script defines window.controlRulesPage')
        payload = self.get_rules(self.mum).json()
        out = run_node(NODE_HARNESS, {
            'base': BASE, 'scripts': scripts, 'payload': payload,
            'refusal': 'The child card for media must be yes or no.',
        })
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['forbidden'], [], 'browser dialogs are banned')
        self.assertEqual(out['factory'], 'function')

        gets = [c for c in out['calls'][:out['afterLoadCalls']] if c['method'] == 'GET']
        self.assertEqual([c['url'] for c in gets], [BASE + 'api/ha/control/rules'],
                         'load() reads the rules relative to chfBase, never root-relative')
        self.assertEqual(out['loaded']['rules'], payload['rules'])

        # Toggling a person cell posts the FULL grid, immediately.
        posts = out['personPosts']
        self.assertEqual(len(posts), 1, posts)
        self.assertEqual(posts[0]['url'], BASE + 'api/ha/control/rules')
        expected = copy.deepcopy(payload['rules'])
        expected['people']['child']['lights'] = 'no'
        self.assertEqual(posts[0]['body'], expected)
        cr.validate_rules(copy.deepcopy(posts[0]['body']))

        # The screen never claims more than happens: Yes on a proof kind asks.
        labels = dict(out['labels'])
        self.assertIn(labels.pop('locks'), ('Ask who', 'Ask who (needs proof)'))
        self.assertEqual(labels, {'lights': 'Yes', 'climate': 'Ask who', 'alarm': 'No'})
        self.assertEqual(out['lastPost']['places']['panel']['locks'], 'yes')
        self.assertEqual(out['lastPost']['places']['panel']['alarm'], 'no')

        # A refused save is told through showGlobalAlert.
        self.assertTrue(any('child card for media' in a for a in out['alertsAfterRefusal']),
                        out['alertsAfterRefusal'])

    def test_old_switch_gone_from_boards_drawer(self):
        from services import settings_registry as reg

        with open(PANEL_SETTINGS, encoding='utf-8') as f:
            self.assertFalse('panel_allow_unsafe_controls' in f.read(),
                             'the Boards drawer (panel_settings.html) still renders the old lock switch')
        page = self.config_page()
        self.assertNotIn('x-model="panel.panel_allow_unsafe_controls"', page)

        self.assertIsNone(reg.owner('panel_allow_unsafe_controls'), 'retired from the registry')
        entry = reg.BY_KEY.get('ha_control')
        self.assertIsNotNone(entry, 'the grid has a registry entry')
        self.assertEqual((entry['group'], entry['label'], entry['page'], entry['anchor']),
                         ('integrations', 'Who can control what', 'config', 'people'))

        # The old switch still seeds the defaults for a household that never saved a grid.
        self.assertEqual(cr.default_rules({'panel_allow_unsafe_controls': True})['places']['panel']['locks'], 'ask')
        self.assertEqual(cr.default_rules({})['places']['panel']['locks'], 'no')
        self.store['panel_allow_unsafe_controls'] = True
        r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['rules']['places']['panel']['garage'], 'ask')


# --- review rulings (Claude review of 75b5c385) ------------------------------
#
# 1. POST saves through storage.patch_settings({'ha_control': grid}); never
#    update_settings (which re-dirties every schedule).
# 2. GET and POST /api/ha/control/rules have their own PARENTS rows in
#    services/auth.py, not only the /api/ha/* catch-all.
# 3. control_rules.KIND_LABELS sits beside KINDS (same order) and the GET's
#    kinds come from it.
# 4. local_handling_warning also names Assist-exposed scripts and scenes that
#    touch a restricted kind, and exposed scripts Chauffeur cannot read.
# 5. The pipeline list is cached ~60 s; control_rules.clear_pipeline_cache()
#    empties it.
# 6. The component loads when its <details> opens (@toggle / x-on:toggle), not
#    on page init, and a second open does not fetch again; after a successful
#    save `saving` is false before the warnings refresh finishes.
# 7. A save error handled by chfSettingsSaved(false, msg) (it returns truthy)
#    is not shown again through showGlobalAlert.
# 8. The status line under a place cell shows only when its text differs from
#    the selected button's text.
# 9. config.html's Argyle setting no longer says locks always need a parent;
#    it points at the Who can control what grid.

PAGE_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
globalThis.window = globalThis;
const forbidden = [];
for (const name of ['alert', 'confirm', 'prompt']) {
  globalThis[name] = function () { forbidden.push(name); throw new Error('browser dialog: ' + name); };
}
const alerts = [];
globalThis.showGlobalAlert = function (msg) { alerts.push(String(msg)); };
function El() {
  const el = { style: {}, dataset: {}, children: [], classList: { add(){}, remove(){}, contains(){ return false; }, toggle(){} },
    appendChild(c){ el.children.push(c); return c; }, addEventListener(){}, removeEventListener(){},
    setAttribute(){}, getAttribute(){ return null; }, querySelector(){ return null; }, querySelectorAll(){ return []; } };
  return el;
}
globalThis.document = { getElementById(){ return null; }, createElement(){ return El(); },
  querySelector(){ return null; }, querySelectorAll(){ return []; }, addEventListener(){}, removeEventListener(){},
  body: El(), documentElement: El() };
globalThis.addEventListener = function () {};
globalThis.location = { pathname: '/config', search: '', origin: 'http://chauffeur.local', href: 'http://chauffeur.local/config' };
const mem = {};
globalThis.localStorage = { getItem(k){ return k in mem ? mem[k] : null; }, setItem(k, v){ mem[k] = String(v); }, removeItem(k){ delete mem[k]; } };
window.chfBase = input.base;

// GET answers follow input.gets ('ok' | 'hang'), the last repeating; POST
// answers follow input.posts ({status, body}); a 200 echoes the grid.
const calls = [];
let getN = 0, postN = 0;
globalThis.fetch = function (url, opts) {
  opts = opts || {};
  const method = (opts.method || 'GET').toUpperCase();
  calls.push({ url: String(url), method, body: opts.body === undefined ? null : String(opts.body) });
  const json = (status, body) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  if (method === 'GET') {
    const gets = input.gets || ['ok'];
    const mode = gets[Math.min(getN++, gets.length - 1)];
    if (mode === 'hang') return new Promise(() => {});
    return Promise.resolve(json(200, input.payload));
  }
  const posts = input.posts || [{ status: 200 }];
  const r = posts[Math.min(postN++, posts.length - 1)];
  return Promise.resolve(r.status === 200 ? json(200, JSON.parse(opts.body)) : json(r.status, r.body));
};
const flush = (ms) => new Promise(r => setTimeout(r, ms || 100));
// Evaluate an Alpine expression from the template against the component.
function evalIn(page, expr, locals) {
  return new Function('__page', '__locals', 'with (__page) { with (__locals) { return (' + expr + '); } }')(page, locals || {});
}
// An event handler (@toggle="...") is a statement, not an expression.
function runIn(page, stmt, locals) {
  return new Function('__page', '__locals', 'with (__page) { with (__locals) { ' + stmt + ' } }')(page, locals || {});
}
const out = { forbidden, alerts, calls };
(async function () {
  try {
    for (const src of input.scripts) vm.runInThisContext(src);
    const scenario = new Function('input', 'out', 'flush', 'calls', 'alerts', 'evalIn', 'runIn',
                                  'return (async () => {' + input.scenario + '})();');
    await scenario(input, out, flush, calls, alerts, evalIn, runIn);
  } catch (e) {
    out.error = String(e && e.stack || e);
  }
  process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));
})();
"""


def _open_tag(page_html, marker):
    """The opening tag of the element carrying `marker`, attributes unescaped."""
    i = page_html.index(marker)
    start = page_html.rindex('<', 0, i)
    end = page_html.index('>', i)
    return page_html[start:end + 1]


def _attr(tag, *names):
    for name in names:
        m = re.search(r'(?:^|\s)' + re.escape(name) + r'="([^"]*)"', tag)
        if m:
            return html.unescape(m.group(1))
    return None


class ReviewRulings(_Base):
    config_page = Page.config_page

    def page_run(self, scenario, **extra):
        page = self.config_page()
        scripts = _scripts(page, 'controlRulesPage')
        self.assertTrue(scripts, 'no inline script defines window.controlRulesPage')
        payload = self.get_rules(self.mum).json()
        out = run_node(PAGE_HARNESS, {'base': BASE, 'scripts': scripts, 'payload': payload,
                                      'scenario': scenario, **extra})
        self.assertNotIn('error', out, out.get('error'))
        self.assertEqual(out['forbidden'], [], 'browser dialogs are banned')
        return out, page, payload

    # --- 1 ---------------------------------------------------------------

    def test_post_saves_through_patch_settings(self):
        grid = cr.default_rules({})
        grid['people']['guest']['media'] = 'no'
        r = self.post_rules(grid, self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.update_calls), 0,
                         'saved through update_settings, which re-dirties every schedule')
        self.assertEqual(self.patch_calls, [{'ha_control': grid}])
        self.assertEqual(self.store.get('ha_control'), grid)
        self.assertEqual(self.store.get('sentinel_setting'), 'kept')
        self.assertTrue(self.store.get('auth_enforce'))

    # --- 2 ---------------------------------------------------------------

    def test_rules_routes_have_their_own_auth_rows(self):
        from services import auth
        for method in ('GET', 'POST'):
            row = next((rule for rule in auth.RULES
                        if auth._rule_matches(rule[0], rule[1], method, '/api/ha/control/rules')), None)
            self.assertIsNotNone(row, method)
            self.assertEqual(row[1], '/api/ha/control/rules',
                             f'{method} resolves through {row[1]!r}, not a row of its own')
            self.assertEqual(row[2], auth.PARENTS)
            self.assertEqual(auth.resolve(method, '/api/ha/control/rules'), auth.PARENTS)
        r = self.post_rules(cr.default_rules({}), **{'X-Device-Token': self.panel})
        self.assertEqual(r.status_code, 403, 'a wall panel cannot rewrite the rules: ' + r.text)
        self.assertNotIn('ha_control', self.store)

    # --- 3 ---------------------------------------------------------------

    def test_kind_labels_beside_kinds(self):
        self.assertTrue(hasattr(cr, 'KIND_LABELS'), 'control_rules.KIND_LABELS is missing')
        labels = cr.KIND_LABELS
        if isinstance(labels, dict):
            self.assertEqual(list(labels), list(cr.KINDS))
            values = list(labels.values())
            renamed = {k: f'#{v}' for k, v in labels.items()}
        else:
            values = list(labels)
            renamed = type(labels)(f'#{v}' for v in labels)
        self.assertEqual(len(values), len(cr.KINDS))
        self.assertEqual(values, [label for _, label in KIND_LABELS])
        with patch.object(cr, 'KIND_LABELS', renamed):
            r = self.get_rules(self.mum)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([k['label'] for k in r.json()['kinds']], [f'#{label}' for _, label in KIND_LABELS],
                         "the page's labels come from KIND_LABELS")

    # --- 4 ---------------------------------------------------------------

    def test_local_handling_names_scripts_and_scenes(self):
        self.exposed = {'script.open_garage': True, 'script.goodnight': True, 'script.lights_on': True,
                        'scene.lockdown': True, 'scene.movie': True, 'light.a': True}
        warning = cr.local_handling_warning(cr.default_rules({})) or {}
        names = {d['entity_id'] for d in warning.get('devices', [])}
        self.assertIn('script.open_garage', names, 'an exposed script that opens the garage')
        self.assertIn('script.goodnight', names, 'an exposed script Chauffeur cannot read')
        self.assertIn('scene.lockdown', names, 'an exposed scene that sets a lock')
        for harmless in ('script.lights_on', 'scene.movie', 'light.a'):
            self.assertNotIn(harmless, names, f'{harmless} touches nothing restricted')

    # --- 5 ---------------------------------------------------------------

    def test_pipeline_list_cached(self):
        listed = []
        ws = ha_api.ws_command

        def counting(command, timeout=8, **fields):
            if command == 'assist_pipeline/pipeline/list':
                listed.append(command)
            return ws(command, timeout=timeout, **fields)
        ha_api.ws_command = counting
        cr.local_handling_warning(cr.default_rules({}))
        cr.local_handling_warning(cr.default_rules({}))
        self.assertEqual(len(listed), 1, 'two reads within a minute list the pipelines once')
        self.assertTrue(hasattr(cr, 'clear_pipeline_cache'), 'control_rules.clear_pipeline_cache is missing')
        cr.clear_pipeline_cache()
        cr.local_handling_warning(cr.default_rules({}))
        self.assertEqual(len(listed), 2, 'clearing the cache reads the pipelines again')

    # --- 6 ---------------------------------------------------------------

    def test_loads_when_opened_not_on_page_init(self):
        page = self.config_page()
        tag = _open_tag(page, 'data-control-rules')
        init = _attr(tag, 'x-init') or ''
        self.assertNotIn('load(', init, 'the rules are not fetched on page load')
        toggle = _attr(tag, '@toggle', 'x-on:toggle')
        self.assertIsNotNone(toggle, 'the <details> loads on @toggle')

        out, _, _ = self.page_run(r"""
          const page = window.controlRulesPage();
          page.$el = { open: true };
          page.$event = { target: { open: true } };
          runIn(page, input.toggle); await flush();
          out.afterFirst = calls.filter(c => c.method === 'GET').length;
          out.loaded = !!page.rules;
          runIn(page, input.toggle); await flush();
          out.afterSecond = calls.filter(c => c.method === 'GET').length;
        """, toggle=toggle)
        self.assertEqual(out['afterFirst'], 1)
        self.assertTrue(out['loaded'])
        self.assertEqual(out['afterSecond'], 1, 'opening again does not fetch the rules again')

    def test_saving_clears_before_warnings_refresh(self):
        out, _, _ = self.page_run(r"""
          const page = window.controlRulesPage();
          await page.load(); await flush();
          page.setPerson('child', 'lights', 'no');   // its warnings refresh never answers
          await flush(200);
          out.saving = page.saving;
          out.posted = calls.filter(c => c.method === 'POST').length;
        """, gets=['ok', 'hang'])
        self.assertEqual(out['posted'], 1)
        self.assertFalse(out['saving'], 'the fieldset is enabled again once the grid is saved')

    # --- 7 ---------------------------------------------------------------

    def test_save_error_shown_once(self):
        out, _, _ = self.page_run(r"""
          out.saved = [];
          window.chfSettingsSaving = () => {};
          window.chfSettingsSaved = (ok, msg) => { out.saved.push([ok, msg || null]); return true; };
          const page = window.controlRulesPage();
          await page.load(); await flush();
          await page.setPerson('child', 'media', 'no'); await flush();
        """, posts=[{'status': 400, 'body': {'detail': 'The child card for media must be yes or no.'}}])
        self.assertEqual(out['saved'], [[False, 'The child card for media must be yes or no.']])
        self.assertEqual(out['alerts'], [], 'chfSettingsSaved already showed it')

    # --- 8 ---------------------------------------------------------------

    def test_place_status_only_when_it_differs(self):
        page = self.config_page()
        buttons = {}
        for m in re.finditer(r'<button\b([^>]*)>(.*?)</button>', page, re.S):
            hit = re.search(r"""setPlace\(\s*['"]panel['"]\s*,\s*kind\.id\s*,\s*['"](yes|ask|no)['"]\s*\)""",
                            html.unescape(m.group(1)))
            if hit:
                buttons[hit.group(1)] = {'xtext': _attr(m.group(1), 'x-text'),
                                         'text': html.unescape(re.sub(r'<[^>]+>', '', m.group(2))).strip()}
        # Static buttons, or buttons built from placeOptions() (ruling A below).
        self.assertTrue(set(buttons) == {'yes', 'ask', 'no'} or 'placeOptions(' in page, buttons)
        status = None
        for m in re.finditer(r'<(\w+)\b([^>]*)>', page):
            xtext = _attr(m.group(2), 'x-text') or ''
            if re.search(r"""placeLabel\(\s*['"]panel['"]""", xtext):
                status = {'xtext': xtext, 'xshow': _attr(m.group(2), 'x-show')}
                break

        cases = [('lights', 'yes', False), ('locks', 'yes', True), ('climate', 'ask', False),
                 ('alarm', 'no', True), ('locks', 'ask', True)]
        out, _, _ = self.page_run(r"""
          const page = window.controlRulesPage();
          await page.load(); await flush();
          out.rows = [];
          for (const [kind, value, proof] of input.cases) {
            page.rules.places.panel[kind] = value;
            page.rules.proof[kind] = proof;
            const scope = { kind: { id: kind } };
            let button;
            if (input.buttons[value]) {
              const b = input.buttons[value];
              button = b.xtext ? String(evalIn(page, b.xtext, scope)) : b.text;
            } else {
              const chosen = page.placeSelected('panel', kind);
              button = (page.placeOptions('panel', kind).find(o => o.value === chosen) || {}).label;
            }
            let shown = false, text = null;
            if (input.status) {
              text = String(evalIn(page, input.status.xtext, scope));
              shown = input.status.xshow ? !!evalIn(page, input.status.xshow, scope) : true;
            }
            out.rows.push({ kind, value, proof, button, shown, text });
          }
        """, buttons=buttons if set(buttons) == {'yes', 'ask', 'no'} else {}, status=status, cases=cases)
        for row in out['rows']:
            if row['text'] is not None:
                self.assertEqual(row['shown'], row['text'] != row['button'],
                                 f"status under {row['kind']}={row['value']}: {row}")
            if row['value'] == 'yes' and row['proof']:
                visible = [row['button']] + ([row['text']] if row['shown'] else [])
                self.assertTrue(any(v in ('Ask who', 'Ask who (needs proof)') for v in visible)
                                and 'Yes' not in visible, f'the screen never claims a plain Yes: {row}')

    # --- A: proof kinds offer Ask who / No at places (screenshots, 043c5a64)

    def test_proof_kind_place_offers_ask_or_no(self):
        page = self.config_page()
        start = page.index('data-control-rules')
        component = html.unescape(page[start:page.index('</details>', start)])
        self.assertFalse('Ask who (needs proof)' in component,
                         'the component still renders an "Ask who (needs proof)" button beside "Ask who"')
        self.assertIn('placeOptions(', component, 'the place buttons are built from placeOptions()')

        out, _, _ = self.page_run(r"""
          const page = window.controlRulesPage();
          await page.load(); await flush();
          out.hasHelpers = typeof page.placeOptions === 'function' && typeof page.placeSelected === 'function';
          if (!out.hasHelpers) return;
          const look = (place, kind) => ({
            options: page.placeOptions(place, kind).map(o => [o.value, o.label]),
            selected: page.placeSelected(place, kind),
          });
          page.rules.proof.locks = true;
          page.rules.places.panel.locks = 'yes';
          page.rules.places.unknown_voice.locks = 'yes';
          out.proofPanel = look('panel', 'locks');
          out.proofVoice = look('unknown_voice', 'locks');
          await page.setPlace('panel', 'locks', 'ask'); await flush();
          out.saved = JSON.parse(calls.filter(c => c.method === 'POST').pop().body).places.panel.locks;
          page.rules.proof.locks = false;
          out.plainAsk = look('panel', 'locks');
          page.rules.places.panel.locks = 'yes';
          out.plainYes = look('panel', 'locks');
        """)
        self.assertTrue(out['hasHelpers'], 'window.controlRulesPage() has placeOptions() and placeSelected()')
        two = [['ask', 'Ask who'], ['no', 'No']]
        three = [['yes', 'Yes'], ['ask', 'Ask who'], ['no', 'No']]
        self.assertEqual(out['proofPanel'], {'options': two, 'selected': 'ask'},
                         'a stored yes on a proof kind reads as Ask who')
        self.assertEqual(out['proofVoice'], {'options': two, 'selected': 'ask'})
        self.assertEqual(out['saved'], 'ask')
        self.assertEqual(out['plainAsk'], {'options': three, 'selected': 'ask'})
        self.assertEqual(out['plainYes'], {'options': three, 'selected': 'yes'})

    # --- B: role rows and place rows share one row markup

    def test_role_and_place_rows_share_markup(self):
        page = self.config_page()

        def row_shape(title):
            i = page.index('>' + title + '</h3>')
            m = re.compile(r'<template\s+x-for="[^"]*kinds[^"]*"[^>]*>').search(page, i)
            self.assertIsNotNone(m, title)
            body = page[m.end():page.index('</template>', m.end())]
            tags = re.findall(r'<(\w+)\b([^>]*)>', body)
            self.assertTrue(tags, title)

            def shape(pred, what):
                hit = next(((tag, attrs) for tag, attrs in tags if pred(attrs)), None)
                self.assertIsNotNone(hit, f'{title}: no {what}')
                return hit[0], ' '.join(sorted((_attr(hit[1], 'class') or '').split()))
            return {
                'row': (tags[0][0], ' '.join(sorted((_attr(tags[0][1], 'class') or '').split()))),
                'label': shape(lambda a: _attr(a, 'x-text') == 'kind.label', 'kind label'),
                'control': shape(lambda a: _attr(a, 'role') == 'group', 'segmented control'),
            }
        role, place = row_shape('Parent'), row_shape('Wall panel')
        self.assertEqual(role, place, 'a role row and a place row are built by the same row markup')

    # --- 9 ---------------------------------------------------------------

    def test_argyle_setting_points_at_grid(self):
        page = html.unescape(self.config_page())
        self.assertFalse('Locks, alarms and garage doors always need a parent or adult.' in page,
                         'config.html still says locks always need a parent or adult')
        i = page.index('authSettings.house_control_unexposed')
        label = page[i:page.index('</label>', i)]
        self.assertIn('Who can control what', label, 'the Argyle setting points at the grid')


if __name__ == '__main__':
    unittest.main()
