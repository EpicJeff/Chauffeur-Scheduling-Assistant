"""The errands page and the errands cards are one drawing.

The wall panel's Errands button used to open the admin page: a task editor, an
owner dropdown, a recurrence select and a natural-language errand parser, on a
screen with no keyboard. What a wall wants is the two lists and the tick that
finishes something — so the lists moved into macros
(components/errand_lists.html) that the page and the `task_list` /
`errand_list` board cards both render.

The failure this file exists to catch is the one the chores conversion taught:
jsdom does no layout, so "the element exists" proves very little. What is
pinned here is the shape an extraction actually breaks —

  * the page still draws every row, in the three bands (past due, waiting,
    completed), with the editors it is the only surface entitled to;
  * a CARD draws the same rows and NO editor — a wall panel is reachable by
    every child in the house, and "hidden" is not a permission model, so the
    edit and delete buttons must not be in the DOM at all;
  * `interactive: false` takes the tick-boxes out the same way;
  * the section toggles gate real sections, and the member filter and row cap
    are applied to the card's own copy rather than to the page's;
  * the builders ship CONFIG, never rows: these cards self-fetch, and a payload
    cached for twenty seconds would keep handing back a box that was ticked
    fifteen seconds ago.

Run from chauffeur/:  python tests/test_errand_lists_render.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_errlist_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_errlist_run_')
TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')

import tpl_source  # noqa: E402
from services import home_board  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


TASKS = [
    {'id': 't1', 'title': 'Sign the permission slip', 'due_date': '2020-01-01',
     'past_due': True, 'assigned_to': None, 'assigned_to_name': None,
     'recurrence': 'none'},
    {'id': 't2', 'title': 'Renew the passports', 'due_date': '2099-01-01',
     'past_due': False, 'assigned_to': 'm1', 'assigned_to_name': 'Dad',
     'recurrence': 'yearly'},
]
ERRANDS = [
    {'id': 'e1', 'doc_id': 1, 'title': 'Dry cleaning', 'location': 'Main St',
     'duration_mins': 30, 'priority': 1, 'status': 'past_due',
     'is_completed': False, 'starts_on': 1600000000, 'shopping_lists': []},
    {'id': 'e2', 'doc_id': 2, 'title': 'Post office', 'location': None,
     'duration_mins': 15, 'priority': 2, 'status': 'pending',
     'is_completed': False, 'starts_on': 1600000000, 'shopping_lists': []},
    {'id': 'e3', 'doc_id': 3, 'title': 'Library books', 'location': None,
     'duration_mins': 20, 'priority': 2, 'status': 'completed',
     'is_completed': True, 'starts_on': 1600000000, 'shopping_lists': []},
]

HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const routes = {
  'api/household-tasks': data.tasks,
  'api/errands': data.errands,
  'api/members': [], 'api/drivers': [], 'api/passengers': [],
  'api/assist-contacts': [],
};
const errors = [];
const wrote = [];

const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/errands',
  beforeParse(w) {
    w.fetch = (u, opt) => {
      const method = (opt && opt.method) || 'GET';
      if (method !== 'GET') wrote.push(method + ' ' + String(u));
      if (String(u).includes('household-load')) {
        return Promise.resolve({ ok: true,
          json: () => Promise.resolve({ line: 'A fair week.' }) });
      }
      const key = Object.keys(routes).find(k => String(u).includes(k));
      return Promise.resolve({ ok: true, text: () => Promise.resolve(''),
        json: () => Promise.resolve(key ? routes[key] : []) });
    };
    w.showGlobalAlert = () => {};
    w.promptConfirm = () => Promise.resolve(false);
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
    w.innerWidth = 1600;
  }
});
const win = dom.window;
win.addEventListener('error', e => {
  const m = (e.error && e.error.message) || e.message || '';
  if (!/EventSource/.test(m)) errors.push(m);
});
win.document.addEventListener('DOMContentLoaded', () => {
  const s = win.document.createElement('script');
  s.textContent = fs.readFileSync(require.resolve('alpinejs/dist/cdn.js'), 'utf8');
  win.document.head.appendChild(s);
});

setTimeout(() => {
  const doc = win.document;
  const txt = e => e.textContent.replace(/\s+/g, ' ').trim();
  const body = txt(doc.body);

  // The card wrappers, run against the same rows the page just drew. Driving
  // them here rather than mounting a whole board keeps the assertions about
  // the SLICING, which is what a card actually changes.
  const card = (fn, cfg) => {
    const c = win[fn]({ data: cfg }, '');
    c.tasks = c.onTasks(JSON.parse(JSON.stringify(data.tasks)));
    c.errands = c.onErrands(JSON.parse(JSON.stringify(data.errands)));
    return c;
  };
  const owned = card('taskListCard', { members: ['m1'] });
  const unclaimed = card('taskListCard', { unclaimed_only: true });
  const capped = card('errandListCard', { count: 1 });
  const pastOnly = card('errandListCard', { past_due_only: true });
  const noWhen = card('errandListCard', { parts: { when: false } });
  const inert = card('errandListCard', { interactive: false });

  console.log(JSON.stringify({
    errors: errors,
    body: body,
    // Every row the page drew, and the buttons it drew them with.
    checkboxes: doc.querySelectorAll('input[type="checkbox"]').length,
    editButtons: [...doc.querySelectorAll('button')].map(txt)
      .filter(t => t === '✎' || t === '✕').length,
    // Nothing may be written just by looking at the page.
    wrote: wrote,
    cards: {
      owned: owned.tasks.map(t => t.title),
      unclaimed: unclaimed.tasks.map(t => t.title),
      cappedOpen: capped.openErrands().length,
      pastOnlyShows: { past: pastOnly.listShow('past_due'),
                       open: pastOnly.listShow('open'),
                       done: pastOnly.listShow('completed') },
      noWhenShows: { when: noWhen.listShow('when'), open: noWhen.listShow('open') },
      inertInteractive: inert.listsInteractive,
      defaultInteractive: card('errandListCard', {}).listsInteractive,
      bands: { past: capped.pastDueErrands().map(e => e.title),
               open: capped.openErrands().map(e => e.title),
               done: capped.doneErrands().map(e => e.title) },
    },
  }));
  process.exit(0);
}, 2500);
"""


def _render_errands():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/errands'),
                                query_params={})
    return main.templates.env.get_template('errands.html').render(request=req)


_RESULT = {}


def _run():
    if _RESULT:
        return _RESULT.get('data')
    _RESULT['data'] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the lists were not drawn')
        return None
    have = subprocess.run([node, '-e',
                           "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom/alpinejs not resolvable')
        return None
    probe = os.path.join(SCRATCH, 'harness.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    page = os.path.join(SCRATCH, 'errands.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_errands())
    data = os.path.join(SCRATCH, 'data.json')
    with open(data, 'w', encoding='utf-8') as f:
        json.dump({'tasks': TASKS, 'errands': ERRANDS}, f)
    proc = subprocess.run([node, probe, page, data], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0, f"the errands page threw:\n{proc.stderr[-2000:]}")
    _RESULT['data'] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULT['data']


def scenario_the_page_draws_both_lists_from_the_shared_macros():
    got = _run()
    if got is None:
        return
    check(not got['errors'], f"the page threw while drawing: {got['errors'][:3]}")
    for want in ('Sign the permission slip', 'Renew the passports',
                 'Dry cleaning', 'Post office', 'Library books'):
        check(want in got['body'], f"{want!r} never reached the page")
    # The three bands are what a flat list cannot say.
    check('Past due' in got['body'], "the past-due band is gone from the page")
    check('Completed' in got['body'], "the completed band is gone from the page")
    check('Reschedule' in got['body'],
          "a past-due errand lost its Reschedule button")
    # And the sentence the load ledger says out loud, which is the one part of
    # this page that states the shape of the week without scoring anybody.
    check('A fair week.' in got['body'], "the household load sentence is gone")
    check('nobody yet' in got['body'],
          "an unassigned task stopped saying so out loud")


def scenario_looking_at_the_page_writes_nothing():
    """The oldest bug in this shape: a render that PUTs every row back because
    a checkbox binding fired on the way in."""
    got = _run()
    if got is None:
        return
    check(not got['wrote'], f"drawing the page called something: {got['wrote']}")


def scenario_the_page_keeps_its_editors_and_a_card_has_none():
    """The whole point of the conversion. The page is where a task is written,
    renamed, reassigned and deleted; the wall is where it is ticked off. Not
    hidden on the wall — ABSENT, because a wall panel is reachable by every
    child in the house and `x-show` is not a permission model."""
    got = _run()
    if got is None:
        return
    check(got['editButtons'] >= 4,
          f"the page lost its per-row edit/delete controls: {got['editButtons']}")

    # The card side is a markup fact: board_tile_body renders the macros with
    # no editor expression at all, so there is nothing to draw.
    body = open(os.path.join(TPL, 'components', 'board_tile_body.html'),
                encoding='utf-8').read()
    for card in ('task_list', 'errand_list'):
        block = body[body.index(f"t.type === '{card}'"):]
        block = block[:block.index('</template>')]
        check('interactive=' in block or 'interactive' in block,
              f"the {card} card does not pass its interactive flag")
        check('edit=' not in block and 'remove=' not in block,
              f"the {card} card is drawing the page's editors on a wall")


def scenario_a_card_filters_caps_and_gates_its_own_copy():
    got = _run()
    if got is None:
        return
    c = got['cards']
    check(c['owned'] == ['Renew the passports'],
          f"the owner filter did not slice the card: {c['owned']}")
    check(c['unclaimed'] == ['Sign the permission slip'],
          f"'only what nobody has taken' did not slice the card: {c['unclaimed']}")
    # The cap is PER BAND: a long completed list must never be able to push
    # the past-due band off a wall.
    check(c['bands']['past'] == ['Dry cleaning'] and c['bands']['open'] == ['Post office'],
          f"the row cap was applied across the bands instead of within them: "
          f"{c['bands']}")
    check(c['pastOnlyShows'] == {'past': True, 'open': False, 'done': False},
          f"'past due only' did not win over the section toggles: "
          f"{c['pastOnlyShows']}")
    check(c['noWhenShows'] == {'when': False, 'open': True},
          f"turning one section off took another with it: {c['noWhenShows']}")


def scenario_interactive_is_on_by_default_and_can_be_turned_off():
    """The conversion paradigm: an inert list is the glance tile with extra
    steps, so the tick is on unless somebody says otherwise — and off has to
    really mean off, for the wall that is only a display."""
    got = _run()
    if got is None:
        return
    check(got['cards']['defaultInteractive'] is True,
          "a card nobody configured came up inert")
    check(got['cards']['inertInteractive'] is False,
          "a card set to display-only stayed interactive")
    for key in ('task_list', 'errand_list'):
        meta = next(w for w in home_board.WIDGETS if w['key'] == key)
        opt = next(o for o in meta['options'] if o['key'] == 'interactive')
        check(opt['default'] is True,
              f"{key} does not offer an interactive tick by default")


def scenario_the_builders_ship_config_and_never_rows():
    """Board rule 2: a card either rides the payload or fetches, never both.
    These fetch, so the payload must carry no rows — twenty seconds of cache
    is twenty seconds of a ticked box coming back unticked."""
    from services import storage
    real_t, real_e = storage.get_household_tasks, storage.get_all_errands
    try:
        storage.get_household_tasks = lambda **kw: list(TASKS)
        storage.get_all_errands = lambda: list(ERRANDS)
        t = home_board._tile_task_list(None, config={'count': 3})
        e = home_board._tile_errand_list(None, config={'show_completed': False})
        check(set(t) == {'interactive', 'count', 'members', 'unclaimed_only', 'parts'},
              f"the task-list payload carries more than config: {sorted(t)}")
        check(set(e) == {'interactive', 'count', 'past_due_only', 'parts'},
              f"the errand-list payload carries more than config: {sorted(e)}")
        check(e['parts']['completed'] is False and e['parts']['open'] is True,
              f"a section toggle did not reach the card: {e['parts']}")
        # And an unconfigured feature still has no tile — the one question the
        # client cannot answer for itself.
        storage.get_household_tasks = lambda **kw: []
        storage.get_all_errands = lambda: []
        check(home_board._tile_task_list(None) is None,
              "a household that has never made a task gets a tile about tasks")
        check(home_board._tile_errand_list(None) is None,
              "a household that has never made an errand gets a tile about them")
    finally:
        storage.get_household_tasks, storage.get_all_errands = real_t, real_e


def scenario_the_errands_board_is_the_two_lists_and_no_editors():
    """What a wall actually lands on when somebody taps Errands."""
    page = home_board.builtin_page('errands', {})
    # Chrome dropped before comparing: shipped boards open with a heading now,
    # and what this defends is the ORDER of the two lists, not the absence of
    # anything else on the screen.
    types_ = [w['type'] for w in page['widgets']
              if w['type'] not in home_board.BARE_TILES]
    check(types_ == ['task_list', 'errand_list'],
          f"the errands board is not the two lists: {types_}")
    by_id = {w['id']: w['config'] for w in page['widgets']}
    check(by_id['errand_list'].get('show_completed') is False,
          f"the wall leads with what is already done: {by_id['errand_list']}")
    # And nothing in the app draws an editor into a card.
    src = tpl_source.read('home.html')
    check('new-errand-input' not in src and 'task-edit-modal' not in src,
          "an errands editor was pulled onto the board")


def scenario_the_shared_logic_is_emitted_once_per_page():
    """`import` renders nothing and `include` renders everything — mixing them
    up is how a page ends up with two copies of the same function and the
    second one silently wins."""
    for name in ('errands.html', 'home.html'):
        src = tpl_source.read(name)
        check(src.count('function errandListsLogic') == 1,
              f"{name} emits the shared list logic "
              f"{src.count('function errandListsLogic')} times")
    page = open(os.path.join(TPL, 'errands.html'), encoding='utf-8').read()
    check("import 'components/errand_lists.html'" in page,
          "the errands page stopped rendering the shared macros")
    # The page's own script must stay free of server-side templating: the jsdom
    # harnesses execute it as plain JavaScript.
    for block in re.findall(r'<script>(.*?)</script>', page, re.S):
        check('{{' not in block, "Jinja leaked into the errands page's script")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} errand-list scenarios passed")
