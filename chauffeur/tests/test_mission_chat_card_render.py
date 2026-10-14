"""The chat's mission-ask card actually draws (node runs the PWA's renderCard),
so a mission's approval is a tap in the Argyle DM.

Pinned shapes:
  * `renderCard` routes `kind: 'mission_ask'` to a mission card that shows the
    question, and for a booking its facts, for a release the values that leave
    the house, for a hand-off a link to the page;
  * one button per option, in the server's order, each tagged with the
    option's id (`data-mission-act`) and reading the option's label, so the
    approve button reads the whole question like the thread card's does;
  * an answered card shows the outcome and no buttons;
  * a viewer who cannot act (a child) sees the question and no buttons;
  * the question is escaped.

Run from chauffeur/:  python tests/test_mission_chat_card_render.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_mcard_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_mcard_run_')
APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'app.html')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _chunk():
    """renderCard and the card renderers that follow it, up to answerAsk."""
    with open(APP, encoding='utf-8') as f:
        src = f.read()
    start = src.index('function renderCard(card)')
    end = src.index('async function answerAsk(', start)
    return src[start:end]


RELEASE = {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a1', 'ask': 'release', 'state': 'open',
           'goal': 'get the dishwasher fixed', 'site': 'bodewell.com',
           'question': 'Share with bodewell.com: Jeff · ffejnosliw@gmail.com · 27519?',
           'fields': ['first_name', 'email', 'zip'], 'values': {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'},
           'options': [{'id': 'release:a1:approve', 'verb': 'release', 'label': 'Share with bodewell.com: Jeff · ffejnosliw@gmail.com · 27519?', 'payload': {'decision': 'approve'}},
                       {'id': 'release:a1:decline', 'verb': 'release', 'label': 'Not these', 'payload': {'decision': 'decline'}},
                       {'id': 'release:a1:stop', 'verb': 'release', 'label': 'Stop the mission', 'payload': {'decision': 'stop'}}]}
SUBMIT = {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a2', 'ask': 'submit', 'state': 'open', 'goal': 'book it',
          'site': 'bodewell.com', 'url': 'https://bodewell.com/book', 'button': 'Book now',
          'facts': {'slot': 'Tue Oct 20 8-12', 'price': '$114.95'},
          'question': "Book at bodewell.com: slot Tue Oct 20 8-12; price $114.95 (button 'Book now')?",
          'options': [{'id': 'submit:a2:approve', 'verb': 'submit', 'label': "Book at bodewell.com: slot Tue Oct 20 8-12; price $114.95 (button 'Book now')?", 'payload': {'decision': 'approve'}},
                      {'id': 'submit:a2:decline', 'verb': 'submit', 'label': "I'll finish it myself", 'payload': {'decision': 'decline'}},
                      {'id': 'submit:a2:stop', 'verb': 'submit', 'label': 'Stop the mission', 'payload': {'decision': 'stop'}}]}
HANDOFF = {'kind': 'mission_ask', 'mission_id': 'm1', 'ask_id': 'a3', 'ask': 'handoff', 'state': 'open', 'goal': 'g',
           'url': 'https://bodewell.com/guest-schedule-service', 'question': 'I got as far as the form. Finish it on your phone <now>.',
           'options': [{'id': 'answer', 'verb': 'answer', 'label': 'I got as far as the form. Finish it on your phone <now>.', 'payload': {'ask': 'handoff'}}]}
ANSWERED = {**RELEASE, 'state': 'answered', 'outcome': 'Not these', 'options': []}

HARNESS = r"""
const fs = require('fs');
const [,, chunkPath, casesPath] = process.argv;
const cases = JSON.parse(fs.readFileSync(casesPath, 'utf8'));
global.window = global;
let role = 'parent';
function myRole() { return role; }
function mfEscape(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
eval(fs.readFileSync(chunkPath, 'utf8'));
const out = {};
for (const [name, c] of Object.entries(cases)) {
  role = c.role || 'parent';
  try { out[name] = renderCard(c.card); } catch (e) { out[name] = 'THREW ' + (e && e.stack || e); }
}
console.log(JSON.stringify(out));
"""

_RESULT = {}


def _run():
    if _RESULT:
        return _RESULT.get('data')
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the card was not drawn')
        return None
    chunk = os.path.join(SCRATCH, 'chunk.js')
    with open(chunk, 'w', encoding='utf-8') as f:
        f.write(_chunk())
    harness = os.path.join(SCRATCH, 'harness.js')
    with open(harness, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    cases = os.path.join(SCRATCH, 'cases.json')
    with open(cases, 'w', encoding='utf-8') as f:
        json.dump({'release': {'card': RELEASE}, 'submit': {'card': SUBMIT}, 'handoff': {'card': HANDOFF},
                   'answered': {'card': ANSWERED}, 'child': {'card': RELEASE, 'role': 'child'}}, f)
    proc = subprocess.run([node, harness, chunk, cases], capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=60)
    check(proc.returncode == 0, f"the card renderer threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def _buttons(html):
    return re.findall(r'<button[^>]*data-mission-act="([^"]+)"[^>]*>(.*?)</button>', html, re.S)


def scenario_release_card_draws_question_values_and_the_three_buttons():
    got = _run()
    if got is None:
        return
    html = got['release']
    check(not html.startswith('THREW'), html)
    check('Share with bodewell.com' in html and 'ffejnosliw@gmail.com' in html and '27519' in html, f"the question and values are on the card:\n{html}")
    btns = _buttons(html)
    check([b[0] for b in btns] == ['release:a1:approve', 'release:a1:decline', 'release:a1:stop'], f"three buttons, server order, tagged with the option id: {btns}")
    check('Share with bodewell.com' in btns[0][1] and 'Not these' in btns[1][1] and 'Stop the mission' in btns[2][1],
          f"each button reads its option's label (approve reads the whole question): {btns}")
    check('m1' in html, "the card names its mission so the tap can post to it")


def scenario_submit_card_lists_the_facts_and_the_button_it_will_press():
    got = _run()
    if got is None:
        return
    html = got['submit']
    check(not html.startswith('THREW'), html)
    check('Tue Oct 20 8-12' in html and '$114.95' in html and 'Book now' in html and 'bodewell.com' in html,
          f"the booking's facts, site and button are on the card:\n{html}")
    btns = _buttons(html)
    check([b[0] for b in btns] == ['submit:a2:approve', 'submit:a2:decline', 'submit:a2:stop'], f"three answers: {btns}")


def scenario_handoff_card_links_the_page_and_escapes_the_question():
    got = _run()
    if got is None:
        return
    html = got['handoff']
    check(not html.startswith('THREW'), html)
    check('href="https://bodewell.com/guest-schedule-service"' in html, f"a link to the page the person finishes on:\n{html}")
    check('&lt;now&gt;' in html and '<now>' not in html, f"the question is escaped:\n{html}")
    check(len(_buttons(html)) == 1 and _buttons(html)[0][0] == 'answer', f"one answer button: {_buttons(html)}")


def scenario_answered_card_shows_the_outcome_and_no_buttons():
    got = _run()
    if got is None:
        return
    html = got['answered']
    check(not html.startswith('THREW'), html)
    check(not _buttons(html) and '<button' not in html, f"no buttons once answered:\n{html}")
    check('Not these' in html, f"the decision is shown:\n{html}")


def scenario_a_child_sees_the_question_but_no_buttons():
    got = _run()
    if got is None:
        return
    html = got['child']
    check(not html.startswith('THREW'), html)
    check('Share with bodewell.com' in html, "the question still shows")
    check('<button' not in html, f"no buttons for a viewer who cannot act:\n{html}")


SCENARIOS = [
    scenario_release_card_draws_question_values_and_the_three_buttons,
    scenario_submit_card_lists_the_facts_and_the_button_it_will_press,
    scenario_handoff_card_links_the_page_and_escapes_the_question,
    scenario_answered_card_shows_the_outcome_and_no_buttons,
    scenario_a_child_sees_the_question_but_no_buttons,
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
