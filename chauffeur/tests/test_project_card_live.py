"""The project chat card renders from the app's own renderCard (front door §1, Task 5).

Node half, as tests/test_planned_mission_cards.py: the card renderers are cut
out of templates/app.html and run under jsdom with the real situations.js.

Run from chauffeur/:  python tests/test_project_card_live.py
"""
import json
import os
import shutil
import subprocess

from harness import check  # noqa: F401
from test_planned_mission_cards import _chunk, HARNESS, SCRATCH, ROOT

CARD = {'kind': 'project', 'project_id': 'p1', 'title': 'Learn Portuguese', 'goal': 'I want to learn Brazilian Portuguese',
        'owner_label': 'Mom', 'audience': 'private', 'audience_label': 'Private', 'state': 'active',
        'planning': 'started', 'reason': '', 'can_edit': True, 'body_goal': False,
        'shared_with': [], 'can_edit_audience': True}
LEGACY = {k: v for k, v in CARD.items() if k not in ('shared_with', 'can_edit_audience')}


def _run_cases(cases):
    node = shutil.which('node')
    if not node or subprocess.run([node, '-e', "require.resolve('jsdom')"], capture_output=True, cwd=SCRATCH).returncode != 0:
        print('  skip  node/jsdom not available')
        return None
    paths = {}
    for name, text in (('chunk.js', _chunk()), ('harness.js', HARNESS), ('cases.json', json.dumps(cases))):
        paths[name] = os.path.join(SCRATCH, name)
        with open(paths[name], 'w', encoding='utf-8') as f:
            f.write(text)
    proc = subprocess.run([node, paths['harness.js'], paths['chunk.js'], os.path.join(ROOT, 'static', 'situations.js'), paths['cases.json']],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=SCRATCH, timeout=120)
    check(proc.returncode == 0, f"render threw:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_project_card_renders():
    out = _run_cases({'base': CARD, 'xss': {**CARD, 'title': '<script>x</script>'},
                      'off': {**CARD, 'planning': 'off', 'reason': 'Missions are off (Projects settings).'},
                      'kid': {**CARD, 'planning': 'needs_parent', 'reason': 'Ask a parent to plan it with Argyle.', 'audience': 'parents'},
                      'body': {**CARD, 'body_goal': True},
                      'done': {**CARD, 'state': 'dropped'},
                      'handoff': {**CARD, 'planning': 'needs_plan', 'reason': 'Kate started this project.', 'audience': 'parents'},
                      'listed': {**CARD, 'audience': 'shared', 'audience_label': 'Parents and chosen people', 'can_edit_audience': False},
                      'legacy': LEGACY})
    if out is None:
        return
    for text in ('Learn Portuguese', 'I want to learn Brazilian Portuguese', 'Private', 'Rename', 'Not a project', 'Share with parents'):
        check(text in out['base'], f"the card shows {text}: {out['base'][:200]}")
    check('<script' not in out['xss'], "escaped")
    check('Missions are off' in out['off'], "says why planning is off")
    check('Ask a parent' in out['kid'], "a kid's card says who plans it")
    check('Share with' not in out['body'], "a body goal cannot leave private")
    # Audience spec §5: who sees it is gated on can_edit_audience, with Choose people… beside the quick choices.
    check('Choose people…' in out['base'] and "projectCardChoose('p1')" in out['base'], "the owner's card offers Choose people…")
    check('Only you' in out['body'] and 'Choose people' not in out['body'] and 'Make private' not in out['body'],
          f"a body goal reads Only you and offers no picker: {out['body'][:300]}")
    check('Rename' in out['listed'] and not any(t in out['listed'] for t in ('Make private', 'Share with', 'Choose people')),
          f"a listed adult may act but not choose who sees it: {out['listed'][:400]}")
    check('Parents and chosen people' in out['listed'], "the chip reads the saved audience")
    check('Share with parents' in out['legacy'] and 'Choose people' in out['legacy'],
          "a card saved before can_edit_audience keeps its old gate (the server still refuses)")
    check('Not a project' not in out['done'], "a dropped project offers no buttons")
    check("projectCardDrop('p1')" in out['base'], "Not a project calls the drop handler")
    check('Plan it with Argyle' in out['handoff'] and "projectCardPlan('p1')" in out['handoff'], "a parent's hand-off card plans it")
    check('Plan it with Argyle' not in out['base'], "only the hand-off card offers it")


def scenario_the_handlers_hit_the_project_routes():
    src = _chunk()
    check('async function projectCardDrop' in src and 'async function projectCardRename' in src and 'async function projectCardPatch' in src,
          "the three handlers live beside renderCard")
    drop = src.split('async function projectCardDrop')[1].split('async function')[0] if 'async function projectCardDrop' in src else ''
    check("/state" in drop and "state: 'dropped'" in drop and 'promptConfirm' in drop, f"drop posts state=dropped after a promptConfirm: {drop[:300]}")
    rename = src.split('async function projectCardRename')[1].split('async function')[0] if 'async function projectCardRename' in src else ''
    patch = src.split('async function projectCardPatch')[1].split('async function')[0] if 'async function projectCardPatch' in src else ''
    check('promptInput' in rename and "'PATCH'" in patch, "rename prompts and patches")
    plan = src.split('async function projectCardPlan')[1].split('async function')[0] if 'async function projectCardPlan' in src else ''
    check('/plan' in plan and "'POST'" in plan, f"Plan it with Argyle posts to the project's plan route: {plan[:200]}")
    check('confirm(' not in drop.replace('promptConfirm(', '') and 'prompt(' not in rename.replace('promptInput(', ''), "no browser dialogs")
    choose = src.split('async function projectCardChoose')[1].split('function renderPlanQuestion')[0] if 'async function projectCardChoose' in src else ''
    check("'chf-audience-sheet-open'" in choose and "'PATCH'" in choose and 'can_edit_audience' in choose,
          f"Choose people… re-reads the project, opens the shared picker's sheet and patches: {choose[:300]}")
    bare = choose.replace('showGlobalAlert(', '').replace('promptConfirm(', '').replace('promptInput(', '')
    check(not any(d in bare for d in ('alert(', 'confirm(', 'prompt(')), "no browser dialogs in Choose people…")


SCENARIOS = [scenario_project_card_renders, scenario_the_handlers_hit_the_project_routes]

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
    raise SystemExit(1 if failed else 0)
