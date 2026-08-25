"""The family packing card, drawn for real — before it moves.

Same bargain `test_chores_lanes_render.py` settled: jsdom does no layout, so
this cannot answer "is it readable" (that is `test_packing_card.py`'s job, in
a real browser) — but it is the only place a wiring mistake in the markup
itself would show up before a wall does. Two things this pins:

  * the interactivity gate. `packing_card.html`'s own comment is explicit that
    the OUTING ROW stays a button whether or not the card is interactive
    ("Expand/collapse is local state, not a server action"), so what
    `interactive: false` turns off is the CLAIM controls — the tick and the
    stepper — not navigation. A hidden button still answers `querySelector`,
    so this counts real buttons, not visibility;
  * merely drawing the card never POSTs. The GET that loads the day is the
    only request a mount is allowed to make.

Run from chauffeur/:  python tests/test_packing_card_render.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_packing_render_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_packing_render_run_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# One outing still needing a stepper item (two water bottles) and a tick item
# not yet packed, another already fully packed — the shapes the two branches
# of the group-items loop draw. `GET api/packing/day`'s real shape, per
# main.packing_day / tests/test_packing_api.py.
DAY = {
    'date': '2026-09-08', 'is_tomorrow': False,
    'outings': [
        {'key': 'd1:soccer', 'driver': 'Dad', 'color': '#2563eb', 'car': 'Van',
         'start': '2026-09-08T16:00:00', 'title': 'Soccer + swim',
         'groups': [
             {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie', 'theo'],
              'items': [
                  {'key': 'k1:water bottle', 'label': 'Water bottle',
                   'needed': 2, 'packed': 0},
                  {'key': 'k1:goggles', 'label': 'Goggles',
                   'needed': 1, 'packed': 0},
              ]},
         ], 'packed': 0, 'needed': 3},
        {'key': 'd1:band', 'driver': 'Dad', 'color': '#2563eb', 'car': 'Van',
         'start': '2026-09-08T18:00:00', 'title': 'Band practice',
         'groups': [
             {'kit_id': 'k2', 'kit': 'Band bag', 'people': ['ellie'],
              'items': [
                  {'key': 'k2:sheet music', 'label': 'Sheet music',
                   'needed': 1, 'packed': 1},
              ]},
         ], 'packed': 1, 'needed': 1},
    ],
}

HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

const posted = [];
const errors = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/home?panel=true',
  beforeParse(w) {
    w.fetch = (u, opt) => {
      if (opt && opt.method === 'POST') { posted.push(String(u)); }
      if (String(u).endsWith('api/packing/day')) {
        return Promise.resolve({ ok: true, text: () => Promise.resolve(''),
          json: () => Promise.resolve(data) });
      }
      return Promise.resolve({ ok: true, text: () => Promise.resolve(''),
        json: () => Promise.resolve({}) });
    };
    w.showGlobalAlert = () => {};
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.EventSource = function () { return { addEventListener() {}, close() {} }; };
  }
});
const win = dom.window;
win.addEventListener('error', e => {
  errors.push((e.error && e.error.message) || e.message || '');
});
win.document.addEventListener('DOMContentLoaded', () => {
  const s = win.document.createElement('script');
  s.textContent = fs.readFileSync(require.resolve('alpinejs/dist/cdn.js'), 'utf8');
  win.document.head.appendChild(s);
});

setTimeout(() => {
  const doc = win.document;
  const root = doc.getElementById('pk-root');
  const txt = e => e.textContent.replace(/\s+/g, ' ').trim();
  console.log(JSON.stringify({
    errors: errors,
    text: root ? txt(root) : '',
    // Every button drawn anywhere in the card — the row header (always a
    // button, interactive or not) plus, when interactive, the tick and the
    // stepper controls.
    buttons: root ? [...root.querySelectorAll('button')].map(b => txt(b)) : [],
    posted: posted,
  }));
  process.exit(0);
}, 2500);
"""


def _render_page(interactive):
    """The real macro AND the real `<script>` — `import` for the markup,
    `include` for the logic, the same split `board_tile_body.html` and
    `home.html` make between them, through the app's own Jinja environment so
    `{% import %}` / `{% include %}` resolve against the real files."""
    import main
    cfg = json.dumps({'data': {'interactive': interactive, 'members': []}})
    src = (
        "{% import 'components/packing_card.html' as packing %}"
        "<!doctype html><html><body>"
        "<div id=\"pk-root\" x-data='packingCard(" + cfg + ", \"\")' "
        "x-init=\"startPacking()\">"
        "{{ packing.rows() }}"
        "</div>"
        "{% include 'components/packing_card.html' %}"
        "</body></html>"
    )
    return main.templates.env.from_string(src).render()


_RESULTS = {}


def _run(interactive):
    if interactive in _RESULTS:
        return _RESULTS[interactive]
    _RESULTS[interactive] = None
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the packing card was not drawn')
        return None
    have = subprocess.run([node, '-e',
                           "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom/alpinejs not resolvable')
        return None
    probe = os.path.join(SCRATCH, f'harness-{interactive}.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    page = os.path.join(SCRATCH, f'packing-{interactive}.html')
    # utf-8 explicitly: a mojibaked driver dot or arrow glyph on Windows turns
    # a passing test into a UnicodeDecodeError with nothing to do with packing.
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_page(interactive))
    data = os.path.join(SCRATCH, 'day.json')
    if not os.path.exists(data):
        with open(data, 'w', encoding='utf-8') as f:
            json.dump(DAY, f)
    proc = subprocess.run([node, probe, page, data], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0, f"the packing card threw:\n{proc.stderr[-2000:]}")
    _RESULTS[interactive] = json.loads(proc.stdout.strip().splitlines()[-1])
    return _RESULTS[interactive]


def scenario_the_card_draws_both_outings_as_one_row_each():
    got = _run(True)
    if got is None:
        return
    check(not got['errors'], f"the packing card threw while drawing: {got['errors'][:3]}")
    for want in ('Soccer + swim', 'Band practice', 'Dad', 'Van'):
        check(want in got['text'], f"the card is missing {want!r}: {got['text'][:300]}")


def scenario_interactive_draws_the_claim_controls_as_real_buttons():
    """The interactive half: a tick for the needed-one item, a stepper for
    the needed-two item — both real `<button>` elements a tap can reach."""
    got = _run(True)
    if got is None:
        return
    buttons = got['buttons']
    check(any('−' in b or '+' in b for b in buttons) or len(buttons) > 2,
          f"no stepper controls drew as buttons: {buttons}")
    check(not got['posted'],
          f"merely drawing the interactive card called something: {got['posted']}")


def scenario_interactive_false_draws_no_claim_buttons_at_all():
    """`interactive: false` turns the tick and the stepper into inert divs —
    `pkInteractive` gates exactly those two branches in the macro. The row
    header stays a button on purpose (`pkToggle` is local state, not a
    server action), so this checks for the ABSENCE of claim controls
    specifically, not an empty button list — asserted by querySelector,
    because a merely-hidden button would still answer it and prove nothing."""
    interactive_run = _run(True)
    got = _run(False)
    if got is None or interactive_run is None:
        return
    check(not got['errors'], f"the read-only card threw: {got['errors'][:3]}")
    # Every button the interactive run drew that named an item or a stepper
    # glyph must be gone; only the row headers (naming the outing) may remain.
    claim_like = [b for b in got['buttons']
                 if 'Water bottle' in b or 'Goggles' in b or 'Sheet music' in b
                 or '−' in b or b.strip() in ('+', '-')]
    check(not claim_like,
          f"a read-only packing card is still drawing claim buttons: {claim_like}")
    # The card itself is unchanged otherwise — the same outings, the same
    # fractions, just nothing left to tap on the items. '1/1' is the
    # needed-exactly-one tick item's (Sheet music) `!pkInteractive` branch;
    # '0/2' is the OTHER branch — the needed-more-than-one stepper item
    # (Water bottle)'s own `!pkInteractive` count, which a check that only
    # ever looked at the tick branch would never catch going missing or
    # wrong.
    for want in ('Soccer + swim', 'Band practice', '1/1', '0/2'):
        check(want in got['text'], f"the read-only card lost {want!r}: {got['text'][:300]}")
    check(not got['posted'],
          f"merely drawing the read-only card called something: {got['posted']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing-card render scenarios passed")
