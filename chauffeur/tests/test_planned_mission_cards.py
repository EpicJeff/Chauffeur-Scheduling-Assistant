"""The planned mission's cards, the finish, and the progress line (spec §6–§7).
Task 10.

Python half:
  * `missions.ask_card` for 'interview' (the round's questions with kind and
    choices), 'plan' (stages with makes and state) and 'stage' (build rows, or
    a work stage's goal), each carrying its approve_plan / run_stage options;
  * finishing a planned mission marks the plan 'done', refuses while a stage
    is proposed or running, and sends a 'mission_done' card listing the
    drafts (to, words) and, for an occasion subject, what is still open
    (`occasions.gap_report`);
  * the subject page's back-link row carries `plan_line`:
    "Plan: stage <n> of <m> — <title>".
Node half (jsdom, the app's own renderCard and situations.js):
  * an interview card draws one control per question kind, a "You decide"
    per question and a "Send answers" button;
  * a plan card lists the stages with what each makes; a stage card lists its
    rows (or a work stage's goal) and the results once run; every option is a
    tagged button;
  * a mission_done card shows each draft with Copy and Share, escaped;
  * `Situations.planStepperHtml(plan)` draws every stage with its state.

Run from chauffeur/:  python tests/test_planned_mission_cards.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile

from harness import check  # noqa: F401
from services import storage, missions, situations
from test_planned_missions import _fresh, _interviewed, _planned_mission, _approved, _staged, _plan_of, ROWS, STAGES
from test_mission_subject import _plan, _step
from test_subjects import MOM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = tempfile.mkdtemp(prefix='chauffeur_plan_cards_')


def _card(mid):
    return missions.ask_card(storage.get_mission(mid))


# --- Python half ----------------------------------------------------------------

def scenario_p1_ask_cards_carry_their_shape_and_options():
    _fresh()
    mid = _interviewed()
    c = _card(mid)
    check(c['ask'] == 'interview' and all({'key', 'ask', 'kind'} <= set(q) for q in c['questions']), f"interview: {c}")
    mid = _planned_mission()
    c = _card(mid)
    check(c['ask'] == 'plan' and [s['id'] for s in c['stages']] == ['s1', 's2'] and c['stages'][0]['makes'], f"plan: {c.get('stages')}")
    check(any(o['verb'] == 'approve_plan' and o['id'].endswith(':approve') for o in c['options']), f"with its options: {c['options']}")
    mid, st = _staged()
    c = _card(mid)
    check(c['ask'] == 'stage' and [r['id'] for r in c['rows']] == ['r1', 'r2'] and c['rows'][0]['summary'], f"stage: {c.get('rows')}")
    check(any(o['verb'] == 'run_stage' and o['id'].endswith(':approve') for o in c['options']), "with Do this")


def scenario_p2_the_finish_lists_the_drafts_and_what_is_left():
    _fresh()
    sent = []
    missions._post = lambda dm, argyle, body, card=None: sent.append(card) or {'id': f'm{len(sent)}'}
    rows = [{'id': 'r1', 'tool': 'draft_message', 'args': {'to': 'Grandma', 'words': 'Party at 2 <sharp>!'}, 'summary': 'Invite Grandma'}]
    mid, st = _staged(rows)
    storage.update_mission(mid, {'subject_kind': 'occasion', 'subject_id': 'o2', 'subject_rev': 1,
                                 'subject_history': [{'kind': 'occasion', 'id': 'o2'}]})
    plan = _plan_of(mid)
    plan['stages'][0]['subject'] = list(missions.subject_of(storage.get_mission(mid)))
    from services import planned
    plan['stages'][0]['snapshot'] = planned.snapshot(plan['stages'][0], plan['stages'][0]['subject'], plan['rev'])
    storage.update_mission(mid, {'plan': plan})
    planned.run_stage(mid, 's1', plan['stages'][0]['snapshot'], dict(MOM))
    _plan({'action': 'finish', 'summary': 'Planned.', 'next_action': 'send the invitations'})
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_user' or _plan_of(mid)['state'] != 'done',
          "a work stage still pending keeps the plan open")
    plan = _plan_of(mid)
    plan['stages'][1]['state'] = 'skipped'
    storage.update_mission(mid, {'plan': plan, 'status': 'running'})
    _plan({'action': 'finish', 'summary': 'Planned.', 'next_action': 'send the invitations'})
    _step(mid)
    check(_plan_of(mid)['state'] == 'done', f"the plan is done: {_plan_of(mid)['state']}")
    done = [c for c in sent if c and c.get('kind') == 'mission_done']
    check(done and done[-1]['drafts'] == [{'to': 'Grandma', 'words': 'Party at 2 <sharp>!'}], f"the drafts: {done and done[-1]}")
    check(isinstance(done[-1].get('open'), list), "and what the occasion still lacks")


def scenario_p3_the_subject_page_shows_where_the_plan_is():
    _fresh()
    import main
    from test_subject_audience import _as
    mid = _approved()
    storage.update_mission(mid, {'subject_kind': 'occasion', 'subject_id': 'o2', 'subject_rev': 1,
                                 'subject_history': [{'kind': 'occasion', 'id': 'o2'}]})
    rows = main.subject_situations('occasion', 'o2', request=_as('mom'))
    line = next((r.get('plan_line') for r in rows if r['id'] == mid), None)
    check(line == 'Plan: stage 1 of 2 — The party and its people', f"the progress line: {rows}")


# --- Node half ------------------------------------------------------------------

def _chunk():
    src = open(os.path.join(ROOT, 'templates', 'app.html'), encoding='utf-8').read()
    start = src.index('function renderCard(card)')
    return src[start:src.index('async function answerAsk(', start)]


CARDS = {
    'interview': {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a1', 'ask': 'interview', 'state': 'open', 'goal': 'party',
                  'question': '', 'options': [],
                  'questions': [{'key': 'headcount', 'ask': 'How many?', 'kind': 'number'},
                                {'key': 'cake', 'ask': 'A cake?', 'kind': 'yesno'},
                                {'key': 'theme', 'ask': 'Theme?', 'kind': 'text'},
                                {'key': 'venue', 'ask': 'Where?', 'kind': 'choice', 'choices': ['Home', 'Park']},
                                {'key': 'day', 'ask': 'Which day?', 'kind': 'date'}]},
    'plan': {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a2', 'ask': 'plan', 'state': 'open', 'goal': 'party', 'question': '',
             'stages': [{'id': 's1', 'kind': 'build', 'title': 'The party', 'makes': ['the occasion', 'guests'], 'state': 'pending'},
                        {'id': 's2', 'kind': 'work', 'title': 'Find a bakery', 'makes': ['two bakeries'], 'state': 'pending'}],
             'project': {'title': 'Kate turns ten', 'goal': 'a party she remembers', 'done_when': 'the last guest leaves'},
             'steps': [{'id': 'p1', 'title': 'Pick the theme with Kate', 'owner': 'mom', 'needs': []}],
             'options': [{'id': 'approve_plan:1:approve', 'verb': 'approve_plan', 'label': 'Looks good', 'payload': {}},
                         {'id': 'approve_plan:1:drop:s2', 'verb': 'approve_plan', 'label': 'Leave out: Find a bakery', 'payload': {}}]},
    'stage': {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a3', 'ask': 'stage', 'state': 'open', 'goal': 'party', 'question': '',
              'rows': [{'id': 'r1', 'summary': 'Make the party', 'state': 'done', 'result': {'message': 'Made it.'}},
                       {'id': 'r2', 'summary': 'Add the Wilsons', 'state': 'proposed'}],
              'options': [{'id': 'run_stage:s1:abc:approve', 'verb': 'run_stage', 'label': 'Do this', 'payload': {}},
                          {'id': 'run_stage:s1:abc:exclude:r2', 'verb': 'run_stage', 'label': 'Leave out: Add the Wilsons', 'payload': {}}]},
    'work': {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a4', 'ask': 'stage', 'state': 'open', 'goal': 'party', 'question': '',
             'stage_kind': 'work', 'work_goal': 'find two bakeries', 'found': {'bakeries': ['Publix']},
             'options': [{'id': 'run_stage:s2:def:resume', 'verb': 'run_stage', 'label': 'Carry on', 'payload': {}}]},
    'done': {'kind': 'mission_done', 'mission_id': 'm1', 'summary': 'Planned.', 'open': ['Order the cake'],
             'drafts': [{'to': 'Grandma', 'words': 'Party at 2 <sharp>!'}]},
}

HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const [,, chunkPath, sitPath, casesPath] = process.argv;
const dom = new JSDOM('<!doctype html><body></body>');
global.window = dom.window; global.document = dom.window.document;
function myRole() { return 'parent'; }
function mfEscape(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
eval(fs.readFileSync(chunkPath, 'utf8'));
eval(fs.readFileSync(sitPath, 'utf8'));
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
const out = {};
for (const [k, c] of Object.entries(cases)) { try { out[k] = renderCard(c); } catch (e) { out[k] = 'THREW ' + e.stack; } }
out.stepper = window.Situations.planStepperHtml({ state: 'running', stages: [
  { id: 's1', title: 'The party', state: 'done' }, { id: 's2', title: 'Find a bakery', state: 'running' },
  { id: 's3', title: 'Supplies', state: 'pending' }] });
console.log(JSON.stringify(out));
"""

_OUT = {}


def _run():
    if 'error' in _OUT:
        raise _OUT['error']             # a broken harness fails every node scenario
    if 'v' in _OUT:
        return _OUT['v']
    try:
        return _run_once()
    except Exception as e:
        _OUT['error'] = e
        raise


def _run_once():
    _OUT['v'] = None
    node = shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, cwd=SCRATCH).returncode != 0:
        print('  skip  node/jsdom not available')
        return None
    paths = {}
    for name, text in (('chunk.js', _chunk()), ('harness.js', HARNESS), ('cases.json', json.dumps(CARDS))):
        paths[name] = os.path.join(SCRATCH, name)
        with open(paths[name], 'w', encoding='utf-8') as f:
            f.write(text)
    proc = subprocess.run([node, paths['harness.js'], paths['chunk.js'], os.path.join(ROOT, 'static', 'situations.js'), paths['cases.json']],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"render threw:\n{proc.stderr[-1500:]}")
    _OUT['v'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _OUT['v']


def scenario_n1_an_interview_card_has_one_control_per_kind():
    out = _run()
    if out is None:
        return
    h = out['interview']
    check('THREW' not in h, h)
    check('type="number"' in h and 'data-q="headcount"' in h, "a number box")
    check(re.search(r'data-q="cake"[^>]*>', h) and ('Yes' in h and 'No' in h), "yes/no")
    check('<select' in h and 'Park' in h, "a choice")
    check('type="date"' in h, "a date")
    check(h.count('data-you-decide') == 5, "a You decide on each question")
    check('data-plan-answers="m1"' in h and 'Send answers' in h, "one Send answers button")


def scenario_n2_plan_and_stage_cards_list_their_parts():
    out = _run()
    if out is None:
        return
    p = out['plan']
    check('The party' in p and 'the occasion' in p and 'Find a bakery' in p, f"the stages and what they make:\n{p}")
    check('data-mission-act="approve_plan:1:approve"' in p and 'data-mission-act="approve_plan:1:drop:s2"' in p, "the options as buttons")
    check('Kate turns ten' in p and 'the last guest leaves' in p and 'Pick the theme with Kate' in p,
          f"the project it will become and your steps (Projects core Task 7):\n{p}")
    s = out['stage']
    check('Make the party' in s and 'Made it.' in s and 'Add the Wilsons' in s, f"rows and a result:\n{s}")
    check('data-mission-act="run_stage:s1:abc:approve"' in s, "Do this")
    w = out['work']
    check('find two bakeries' in w and 'Publix' in w and 'Carry on' in w, f"a work stage's goal and what it found:\n{w}")
    check('bakeries: Publix' in w and '{' not in w.split('find two bakeries')[1].split('Carry on')[0],
          f"what it found reads as a line, never a JSON dump:\n{w}")


def scenario_n3_the_done_card_hands_over_the_drafts():
    out = _run()
    if out is None:
        return
    d = out['done']
    check('Grandma' in d and '&lt;sharp&gt;' in d and '<sharp>' not in d, f"escaped words:\n{d}")
    check('data-copy' in d and 'data-share' in d, "Copy and Share")
    check('Order the cake' in d, "what is still open")


def scenario_n4_the_stepper_shows_every_stage():
    out = _run()
    if out is None:
        return
    h = out['stepper']
    for title in ('The party', 'Find a bakery', 'Supplies'):
        check(title in h, f"{title} in the stepper")
    check(re.search(r'data-stage-state="done"', h) and re.search(r'data-stage-state="running"', h), f"states:\n{h}")


SCENARIOS = [
    scenario_p1_ask_cards_carry_their_shape_and_options,
    scenario_p2_the_finish_lists_the_drafts_and_what_is_left,
    scenario_p3_the_subject_page_shows_where_the_plan_is,
    scenario_n1_an_interview_card_has_one_control_per_kind,
    scenario_n2_plan_and_stage_cards_list_their_parts,
    scenario_n3_the_done_card_hands_over_the_drafts,
    scenario_n4_the_stepper_shows_every_stage,
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
