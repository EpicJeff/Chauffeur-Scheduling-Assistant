"""The PWA's errand card and modal carry the placement's why and offer Steer.

Spec §4.5: both projections of a scheduled errand keep `why` through to the
card; the modal shows the why line and a Steer button under Complete's own
predicate (`ev.isErrand && selectedDriverId`); an unplaced errand is reachable
through the "Errands not placed" row. Run under node by extracting the exact
functions from app.html so a unit test cannot pass on a fixture the real
projection would have dropped.

Run from chauffeur/:  python tests/test_pwa_errand_steer.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(os.path.dirname(HERE), 'templates')
sys.path.insert(0, HERE)
from test_moment_media_token import _function_text, _run_node, check  # noqa: E402

APP = open(os.path.join(TPL, 'app.html'), encoding='utf-8').read()

ROW = {'id': 'er1', 'title': 'Costco run', 'start_time': '2026-10-27T16:10:00', 'end_time': '2026-10-27T16:40:00',
       'start': '2026-10-27T16:10:00', 'end': '2026-10-27T16:40:00',
       'location': 'Costco', 'driver': {'id': 'd1', 'name': 'Jeff'}, 'event_type': 'errand',
       'why': {'kind': 'on_the_way', 'detour_mins': 6, 'driver_name': 'Jeff',
               'leg': {'from': 'Home', 'to': 'Soccer'}, 'text': "on Jeff's way to Soccer, +6 min"}}

PRELUDE = ("var scheduleData = {scheduled_errands: [%s], events: [], assignments: {}, ghost_assignments: {}, driver_events: {}};\n"
           % json.dumps(ROW)
           + "var selectedDriverId = 'd1'; var selectedMemberId = 'm1'; var currentView = 'family';\n"
           + "var formatTime = s => String(s); var mfEscape = s => String(s);\n"
           + "var driversData = []; var passengersData = []; var membersData = []; var window = globalThis;\n"
           + "var document = { getElementById: () => null, querySelectorAll: () => [] };\n"
           # The ride cards are another builder's; this probe is about the errand rows.
           + "var buildFamilyCards = () => []; var familyPaxBadges = () => '';\n")


def scenario_the_family_projection_keeps_why():
    fn_family = _function_text(APP, 'function buildFamilyByDate()')
    got = _run_node(PRELUDE + fn_family + r"""
var byDate = buildFamilyByDate();
var card = Object.values(byDate).flat().find(c => c.isErrand);
console.log(JSON.stringify({why: card ? card.why : null, found: !!card}));
""")
    if got is None:
        print("  skip  node is not installed")
        return
    check(got['found'], "the projection still draws the errand card")
    check(got['why'] and got['why']['text'] == "on Jeff's way to Soccer, +6 min",
          f"the agenda projection keeps why: {got}")


def scenario_the_modal_shows_why_and_steer_under_completes_predicate():
    src = APP
    check('id="em-why"' in src and 'id="em-steer-btn"' in src, "the modal has a why line and a Steer button")
    at = src.index("const completeBtn = document.getElementById('em-complete-btn')")
    block = src[at - 1500:at + 2500]
    check("getElementById('em-steer-btn')" in block and 'ev.isErrand && selectedDriverId' in block,
          "Steer is shown exactly where Complete is, under the same predicate")
    check("getElementById('em-why')" in block and ('ev.why' in block or 'ev.whyText' in block),
          "the modal reads the card's why")
    # Both eventData projections hand `why` on.
    check(src.count('why: card.why') + src.count('why: ev.why') >= 2,
          "both eventData projections carry why (card.why and ev.why)")


def scenario_unplaced_errands_have_a_row_and_open_the_sheet():
    src = APP
    check('id="unplaced-errands"' in src or "id=\\\"unplaced-errands\\\"" in src or "unplaced-errands" in src,
          "the Errands not placed row exists")
    check('function renderUnplacedErrands' in src and 'pwaSteerErrand(' in src,
          "it renders from /api/errands and opens the same steer flow")
    fn = _function_text(src, 'async function pwaSteerErrand(ref)')
    shared = open(os.path.join(os.path.dirname(TPL), 'static', 'errand_steer.js'), encoding='utf-8').read()
    got = _run_node(r"""
var apiBase = ''; var puts = [];
var memberToken = () => 't'; var showGlobalAlert = () => {}; var selectedDriverId = 'd1';
var window = globalThis;
window.ChfErrandSteer = { STEER_WINDOWS: { morning: ['08:00','12:00'], midday: ['11:00','14:00'], afternoon: ['14:00','17:00'], evening: ['17:00','20:00'] } };
globalThis.fetch = async (url, init) => {
  if (init && init.method === 'PUT') { puts.push({url, body: JSON.parse(init.body)}); return {ok: true, json: async () => ({})}; }
  if (String(url).includes('api/drivers')) return {ok: true, json: async () => [{id: 'd2', name: 'Lorena'}]};
  return {ok: true, json: async () => [{id: 'er1', doc_id: 7, title: 'Costco run', location: 'Costco', duration_mins: 30,
    skip_dates: [], generation: 2, unplaced: {reason: 'no_driver', text: 'x'}}]};
};
var answers = ['driver', 'd2'];
globalThis.promptChoice = async () => answers.shift();
""" + shared + fn + r"""
pwaSteerErrand({id: 'er1'}).then(() => console.log(JSON.stringify({puts})));
""")
    if got is None:
        print("  skip  node is not installed")
        return
    check(len(got['puts']) == 1 and got['puts'][0]['url'].endswith('api/errands/7')
          and got['puts'][0]['body']['once_driver_id'] == 'd2' and got['puts'][0]['body']['title'] == 'Costco run',
          f"Someone else writes the whole record with once_driver_id: {got}")
    body = got['puts'][0]['body']
    check('unplaced' not in body and 'generation' not in body, "read-only keys are stripped before the PUT")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} pwa errand steer scenarios passed")
