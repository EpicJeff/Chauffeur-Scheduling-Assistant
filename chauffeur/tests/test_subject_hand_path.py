"""The hand path for subjects (spec 2026-10-14 §4): a person sees what a
thread or mission is about, links it, changes it, unlinks it, and sees from
the trip or occasion what Argyle has going about it.

Pinned here (Task 7):

  * `GET /api/subjects/{kind}/{sid}/situations` (main.subject_situations):
    the open threads and live manual missions about that record, each with
    its next step; parent/adult only (a child 403); filtered per viewer by
    `situations.can_see` (an adult the record's audience excludes gets []);
    a route rule exists for it;
  * the trip page and the occasion page fetch it;
  * the one card builder (static/situations.js, run here in jsdom) draws an
    "About:" chip linking to the record when the view carries `subject`, and
    nothing when it does not;
  * the `subject` option's tap asks with promptInput, posts {query}; a
    'choose' answer asks which with promptChoice and posts {kind, id}; a
    cancelled prompt posts nothing; Unlink asks promptConfirm and posts
    {clear: true}. No browser dialogs.

Run from chauffeur/:  python tests/test_subject_hand_path.py
"""
import json
import os
import shutil
import subprocess
import tempfile

from harness import check  # noqa: F401
from services import storage, situations
from test_mission_subject import _fresh, _mission, _thread
from test_subject_audience import _as

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix='chauffeur_subject_hand_')


def scenario_the_backlink_endpoint_is_viewer_filtered():
    _fresh()
    import main
    from fastapi import HTTPException
    tid = _thread('Kate party planning', subject_kind='occasion', subject_id='o1', subject_rev=1)
    mid = _mission(created_by='mom', subject_kind='occasion', subject_id='o1', subject_rev=1)
    _thread('Unrelated')
    rows = main.subject_situations('occasion', 'o1', request=_as('mom'))
    got = {(r['kind'], r['id']) for r in rows}
    check(got == {('thread', tid), ('mission', mid)}, f"the thread and the manual mission about it: {rows}")
    check(all('title' in r and 'next_step' in r for r in rows), f"each with a title and its next step: {rows}")
    check(main.subject_situations('occasion', 'o1', request=_as('aunt')) == [],
          "an adult the parents-only occasion excludes sees nothing about it")
    try:
        main.subject_situations('occasion', 'o1', request=_as('kid'))
        check(False, "a child is refused")
    except HTTPException as e:
        check(e.status_code == 403, f"403 for a child, got {e.status_code}")
    tmid = _mission(created_by='mom', origin=tid)
    rows = main.subject_situations('occasion', 'o1', request=_as('mom'))
    check(('mission', tmid) not in {(r['kind'], r['id']) for r in rows}, "a thread's mission rides on its thread's row, not twice")
    from services import auth
    check(any(r[1] == '/api/subjects/*' for r in auth.RULES), "a route rule exists for the endpoint")


def scenario_the_trip_and_occasion_pages_fetch_it():
    trip = open(os.path.join(ROOT, 'templates', 'trip.html'), encoding='utf-8').read()
    check('api/subjects/trip/' in trip and 'trip-argyle' in trip, "the trip page asks what Argyle has going about it")
    occ = open(os.path.join(ROOT, 'templates', 'occasions.html'), encoding='utf-8').read()
    check('api/subjects/occasion/' in occ, "the occasion page does too")


HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const [,, srcPath] = process.argv;
const dom = new JSDOM('<!doctype html><body></body>');
global.window = dom.window; global.document = dom.window.document;
let inputs = [], choices = [], confirms = [], posts = [], replies = [], asked = {};
window.showGlobalAlert = () => {};
window.promptInput = async (t) => { asked.input = t; return inputs.shift(); };
window.promptChoice = async (t, b, opts) => { asked.choice = opts; return choices.shift(); };
window.promptConfirm = async () => confirms.shift();
global.fetch = window.fetch = async (url, opts) => { posts.push({ url, body: JSON.parse(opts.body) }); const r = replies.shift() || { status: 'success' }; return { ok: true, json: async () => r }; };
for (const name of ['alert', 'confirm', 'prompt']) window[name] = () => { throw new Error('browser dialog: ' + name); };
for (const name of ['showGlobalAlert', 'promptInput', 'promptChoice', 'promptConfirm', 'alert', 'confirm', 'prompt']) global[name] = window[name];
eval(fs.readFileSync(srcPath, 'utf8'));
const S = window.Situations;
const base = { kind: 'thread', id: 'th1', title: 'Disney dining', options: [], next_step: null, asks: [], state: 'open',
               since: null, people: [], status_note: '', note_source: 'fallback' };
(async () => {
  const out = {};
  out.chip = S.cardHtml(Object.assign({}, base, { subject: { kind: 'trip', id: 'ev_disney', title: 'Disney World', link: 'trip?event_id=ev_disney', rev: 1 } }), { canWrite: true, apiBase: '../' });
  out.noChip = S.cardHtml(Object.assign({}, base, { subject: null }), { canWrite: true });
  const ctx = { apiBase: '', memberId: 'mom' };
  const opt = { id: 'subject', verb: 'subject', label: 'Link to something in Chauffeur', payload: {} };
  inputs = ['Disney']; choices = ['trip:ev_disney']; replies = [{ status: 'choose', candidates: [
    { kind: 'trip', id: 'ev_disney', title: 'Disney World' }, { kind: 'thread', id: 'th9', title: 'Disney dining' }] }, { status: 'success', message: 'Now about Disney World.' }];
  await S.act(base, opt, ctx);
  out.pick = { posts, offered: asked.choice };
  posts = []; inputs = [null];
  await S.act(base, opt, ctx);
  out.cancel = posts;
  posts = []; confirms = [true];
  await S.act(base, { id: 'subject:clear', verb: 'subject', label: 'Unlink', payload: { clear: true } }, ctx);
  out.unlink = posts;
  posts = []; confirms = [false];
  await S.act(base, { id: 'subject:clear', verb: 'subject', label: 'Unlink', payload: { clear: true } }, ctx);
  out.keep = posts;
  console.log(JSON.stringify(out));
})().catch(e => { console.log(JSON.stringify({ error: String(e && e.stack || e) })); });
"""

_RESULT = {}


def _run():
    if 'data' in _RESULT:
        return _RESULT['data']
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return None
    if subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, cwd=SCRATCH).returncode != 0:
        print('  skip  jsdom not resolvable')
        return None
    h = os.path.join(SCRATCH, 'harness.js')
    with open(h, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    proc = subprocess.run([node, h, os.path.join(ROOT, 'static', 'situations.js')], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"the card builder threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    check('error' not in _RESULT['data'], f"the run threw: {_RESULT['data'].get('error')}")
    return _RESULT['data']


def scenario_the_card_draws_the_about_chip():
    got = _run()
    if got is None:
        return
    chip = got['chip']
    check('data-sit-subject="trip:ev_disney"' in chip and 'Disney World' in chip and 'href="../trip?event_id=ev_disney"' in chip,
          f"the chip names the record and links to it:\n{chip}")
    check('data-sit-subject' not in got['noChip'], "no subject, no chip")


def scenario_the_subject_tap_asks_then_picks():
    got = _run()
    if got is None:
        return
    posts = got['pick']['posts']
    check(len(posts) == 2 and posts[0]['url'].endswith('api/situations/thread/th1/act'), f"two posts to the act endpoint: {posts}")
    check(posts[0]['body']['verb'] == 'subject' and posts[0]['body']['payload'] == {'query': 'Disney'}, f"first the words: {posts[0]}")
    check(posts[1]['body']['payload'] == {'kind': 'trip', 'id': 'ev_disney'}, f"then the picked one: {posts[1]}")
    check(len(got['pick']['offered'] or []) == 2, f"both candidates were offered: {got['pick']['offered']}")
    check(got['cancel'] == [], "a cancelled prompt posts nothing")
    check(len(got['unlink']) == 1 and got['unlink'][0]['body']['payload'] == {'clear': True}, f"Unlink posts clear: {got['unlink']}")
    check(got['keep'] == [], "declining the confirm posts nothing")


SCENARIOS = [
    scenario_the_backlink_endpoint_is_viewer_filtered,
    scenario_the_trip_and_occasion_pages_fetch_it,
    scenario_the_card_draws_the_about_chip,
    scenario_the_subject_tap_asks_then_picks,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
