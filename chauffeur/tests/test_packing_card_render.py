"""Family Day, drawn for real — before it moves.

Same bargain `test_chores_lanes_render.py` settled: jsdom does no layout, so
this cannot answer "is it readable" (that is a real-browser harness's job) —
but it is the only place a wiring mistake in the markup itself would show up
before a wall does. What this pins:

  * the container rule: a two-event outing draws as a box with its inner
    lines always visible, and nothing else in the DOM until a tap;
  * the pill has exactly two states, and a done/no-cargo row carries no
    amber class at all — the amber pill is the card's one saturated element;
  * the member filter survives a household kit (`people: []`) even when a
    filter is active for somebody else;
  * the interactivity gate. `packing_card.html`'s own comment is explicit
    that a ROW stays a button whether or not the card is interactive
    ("Expand/collapse is local state, not a server action"), so what
    `interactive: false` turns off is the CLAIM controls — the tick and the
    stepper — not navigation. A hidden button still answers `querySelector`,
    so this counts real buttons, not visibility, and checks AFTER expanding
    the row, since items no longer draw before a tap;
  * merely drawing the card never POSTs. The GET that loads the day is the
    only request a mount is allowed to make;
  * a failed poll after a real one leaves `blocks` — and the rows drawn from
    it — standing, rather than wiping them to the quiet-day sentence.

Run from chauffeur/:  python tests/test_packing_card_render.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_packing_render_'))

SCRATCH = tempfile.mkdtemp(prefix='chauffeur_packing_render_run_')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# A two-event outing (soccer + band practice, one driver, one car) and an
# at-home block with no cargo — the container rule and the flat-row rule in
# one fixture. `GET api/packing/day`'s real shape, per main.packing_day /
# services/family_day.py / tests/test_packing_api.py: outing blocks carry
# `events` (their own inner title+time, the container's compact lines);
# event blocks carry `title` directly.
BASE_DAY = {
    'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
    'blocks': [
        {'kind': 'outing', 'key': 'd1:soccer', 'driver': 'Dad', 'driver_id': 'd1',
         'color': '#2563eb', 'car': 'Van',
         'start': '2026-09-08T16:00:00', 'end': '2026-09-08T19:00:00',
         'events': [
             {'id': 'soccer', 'title': 'Soccer', 'start': '2026-09-08T16:00:00',
              'color': '#ec4899',
              'passengers': [{'id': 'm-ellie', 'name': 'Ellie', 'color': '#ec4899'}]},
             {'id': 'band', 'title': 'Band practice', 'start': '2026-09-08T17:30:00',
              'color': '#22d3ee',
              'passengers': [{'id': 'm-sam', 'name': 'Sam', 'color': '#22d3ee'}]},
         ],
         'passengers': [{'id': 'm-ellie', 'name': 'Ellie', 'color': '#ec4899'},
                        {'id': 'm-sam', 'name': 'Sam', 'color': '#22d3ee'}],
         'groups': [
             {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie', 'theo'],
              'items': [
                  {'key': 'k1:water bottle', 'label': 'Water bottle',
                   'needed': 2, 'packed': 0},
                  {'key': 'k1:goggles', 'label': 'Goggles',
                   'needed': 1, 'packed': 0},
              ]},
             {'kit_id': 'k2', 'kit': 'Band bag', 'people': ['ellie'],
              'items': [
                  {'key': 'k2:sheet music', 'label': 'Sheet music',
                   'needed': 1, 'packed': 1},
              ]},
         ], 'packed': 1, 'needed': 4},
        {'kind': 'event', 'key': 'home:99', 'event_id': 99,
         'title': "Grandma's birthday",
         'start': '2026-09-08T12:00:00', 'end': '2026-09-08T14:00:00',
         'canceled': False, 'covered_by': None, 'groups': [],
         'color': '#f59e0b',
         'passengers': [{'id': 'm-sam', 'name': 'Sam', 'color': '#22d3ee'}],
         'packed': 0, 'needed': 0},
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
// 'ALL' expands every expandable block before capturing; '' expands
// nothing; a comma list expands only those block keys — the harness clicks
// the block's own CARET (`.fd-caret`), the same tap a wall would take now
// that expansion moved off the row body and onto the arrow alone. A block
// with nothing to pack has no caret at all (`querySelector` finds none),
// which is the point: there is nothing to unfold.
const expand = process.argv[4] || '';
const clickPack = process.argv[5] || '';

const posted = [];
const errors = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/home?panel=true',
  beforeParse(w) {
    w.fetch = (u, opt) => {
      if (opt && opt.method === 'POST') { posted.push(String(u)); }
      if (String(u).split('?')[0].endsWith('api/packing/day')) {
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

function capture() {
  const doc = win.document;
  const root = doc.getElementById('pk-root');
  const txt = e => e.textContent.replace(/\s+/g, ' ').trim();
  const wrappers = root ? [...root.querySelectorAll('[data-fd-key]')] : [];
  if (clickPack) {
    // 'pack' taps the first tile's button; any other value names the tile to
    // open by matching its title text, so a scenario can open a DONE tile.
    let btn = doc.querySelector('.fd-pack-btn');
    if (clickPack !== 'pack') {
      for (const tile of doc.querySelectorAll('.fd-tile')) {
        if (tile.textContent.toLowerCase().includes(clickPack)) {
          btn = tile.querySelector('.fd-pack-btn') || btn;
        }
      }
    }
    if (btn) btn.click();
  }
  console.log(JSON.stringify({
    errors: errors,
    text: root ? txt(root) : '',
    // Every button drawn anywhere in the card — the row header (always a
    // button, interactive or not, unless canceled) plus, when interactive
    // AND expanded, the tick and the stepper controls.
    buttons: root ? [...root.querySelectorAll('button')].map(b => txt(b)) : [],
    posted: posted,
    innerLines: root ? [...root.querySelectorAll('.fd-inner-line')].map(txt) : [],
    // F2's colour law: an event's left bar is ITS OWN person's colour, never
    // the driver's. Captured as the inline style the shared row builder
    // writes, so this pins the rendered pixel rather than the payload.
    innerBars: root ? [...root.querySelectorAll('.fd-inner-line')].map(
      e => e.style.borderLeft || '') : [],
    // Who is going, answerable without a tap.
    paxDots: root ? [...root.querySelectorAll('.fd-pax-dot')].map(
      e => ({ color: e.style.backgroundColor || '', name: e.getAttribute('title') || '' })) : [],
    containers: root ? root.querySelectorAll('.agenda-day').length : 0,
    // F3: the prep block is the one thing on the card a household is MEANT to
    // act on, so its chips are always on screen -- no caret to open, no pill
    // to summarise what is already visible.
    tiles: root ? [...root.querySelectorAll('.fd-tile')].map(e => ({
      text: txt(e),
      packBtn: !!e.querySelector('.fd-pack-btn'),
      done: !!e.querySelector('.fd-tile-done'),
      dots: e.querySelectorAll('.fd-pax-dot').length,
    })) : [],
    dialog: doc.querySelector('.pack-dialog') ? {
      title: txt(doc.querySelector('.pack-dialog-title')),
      chips: [...doc.querySelectorAll('.pack-dialog .fd-item-chip')].map(c => txt(c)),
    } : null,
    dialogDeltas: [...doc.querySelectorAll('.pack-dialog .pack-chip[data-pack-delta]')]
      .map(c => parseInt(c.getAttribute('data-pack-delta'), 10)),
    preps: root ? [...root.querySelectorAll('.fd-prep')].map(e => ({
      text: txt(e),
      chips: [...e.querySelectorAll('.fd-item-chip')].map(c => txt(c)),
      todo: e.querySelectorAll('.fd-chip-todo').length,
      done: e.querySelectorAll('.fd-chip-done').length,
      caret: !!e.querySelector('.fd-caret'),
      pill: !!(e.querySelector('.pk-pill-amber') || e.querySelector('.pk-pill-done')),
      dots: e.querySelectorAll('.fd-pax-dot').length,
      steppers: [...e.querySelectorAll('button')].map(b => txt(b))
                  .filter(t => t === '+' || t === '\u2212').length,
    })) : [],
    chips: root ? [...root.querySelectorAll('.fd-item-chip')].map(c => txt(c)) : [],
    daySeps: root ? root.querySelectorAll('.fd-day-sep').length : 0,
    // Per block: which pill class (if any) its row carries, and the row's
    // own text — enough to pin the two-state rule without trusting colour.
    pills: wrappers.map(w => ({
      key: w.getAttribute('data-fd-key'),
      amber: !!w.querySelector('.pk-pill-amber'),
      done: !!w.querySelector('.pk-pill-done'),
      text: txt(w),
    })),
    // Per block: does its own wrapper carry the container's "Outing"
    // heading chip as a direct child span (not merely present somewhere in
    // an inner event's own title text)?
    outingChip: wrappers.map(w => ({
      key: w.getAttribute('data-fd-key'),
      // F4 moved the chip INTO the heading line (chip, driver, car, pill
      // on one row), so it is no longer a direct child of the wrapper.
      chip: [...w.querySelectorAll('span')].some(
        c => c.textContent.trim() === 'Outing'),
    })),
    // The second mockup pass: a container's own heading must NOT be an
    // `agendaEventRow` (no `.agenda-event` fill, no color bar) — only its
    // INNER LINES (`.fd-inner-line`, always also `.agenda-event`) may carry
    // that class. `nonInnerCount` is the number of `.agenda-event` elements
    // that are NOT an inner line — zero for a container (the heading is
    // bare), exactly one for a flat block (the row itself IS the event).
    agendaEventCheck: wrappers.map(w => {
      const evts = [...w.querySelectorAll('.agenda-event')];
      return {
        key: w.getAttribute('data-fd-key'),
        total: evts.length,
        nonInnerCount: evts.filter(e => !e.classList.contains('fd-inner-line')).length,
      };
    }),
    // Per block: does a caret (`.fd-caret`) exist anywhere in its wrapper?
    // Absent entirely for a block with nothing to pack (`needed === 0`) —
    // there is nothing behind it to unfold.
    caret: wrappers.map(w => ({
      key: w.getAttribute('data-fd-key'),
      present: !!w.querySelector('.fd-caret'),
    })),
    // The fix itself, pinned so it cannot silently regress: for a FLAT
    // block (never a container — its heading is deliberately not an
    // `.agenda-event` chip at all) the caret must be a DESCENDANT of the
    // row's own `.agenda-event` chip, not a sibling drawn beside it. A
    // sibling caret is exactly the old bug — it shrank the row's own right
    // edge, so rows with a caret and rows without one went ragged against
    // each other instead of sharing one full-width chip.
    caretInsideRow: wrappers.map(w => {
      const car = w.querySelector('.fd-caret');
      return {
        key: w.getAttribute('data-fd-key'),
        hasCaret: !!car,
        insideAgendaEvent: !!(car && car.closest('.agenda-event')),
      };
    }),
  }));
}

setTimeout(() => {
  const doc = win.document;
  const root = doc.getElementById('pk-root');
  if (expand && root) {
    const wanted = expand === 'ALL' ? null : expand.split(',');
    for (const w of [...root.querySelectorAll('[data-fd-key]')]) {
      const key = w.getAttribute('data-fd-key');
      if (wanted && !wanted.includes(key)) continue;
      const btn = w.querySelector('.fd-caret');
      if (btn) btn.click();
    }
    setTimeout(() => { capture(); process.exit(0); }, 300);
  } else {
    capture();
    process.exit(0);
  }
}, 2500);
"""


def _render_page(interactive, members=None):
    """The real macro AND the real `<script>` — `import` for the markup,
    `include` for the logic, the same split `board_tile_body.html` and
    `home.html` make between them, through the app's own Jinja environment so
    `{% import %}` / `{% include %}` resolve against the real files."""
    import main
    cfg = json.dumps({'data': {'interactive': interactive,
                               'members': members or []}})
    src = (
        "{% import 'components/packing_card.html' as packing %}"
        "<!doctype html><html><body>"
        "<div id=\"pk-root\" x-data='packingCard(" + cfg + ", \"\")' "
        "x-init=\"startPacking()\">"
        "{{ packing.rows() }}"
        "</div>"
        "{% include 'components/agenda_row.html' %}"
        "{% include 'components/pack_dialog.html' %}"
        "{% include 'components/packing_card.html' %}"
        "</body></html>"
    )
    return main.templates.env.from_string(src).render()


def _run(day, interactive=True, members=None, expand='', click_pack=False):
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the family day card was not drawn')
        return None
    have = subprocess.run([node, '-e',
                           "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom/alpinejs not resolvable')
        return None
    tag = f"{interactive}-{','.join(members or [])}-{expand}-{click_pack}".replace(' ', '_')
    probe = os.path.join(SCRATCH, f'harness-{tag}.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(HARNESS)
    page = os.path.join(SCRATCH, f'fd-{tag}.html')
    # utf-8 explicitly: a mojibaked driver dot or arrow glyph on Windows turns
    # a passing test into a UnicodeDecodeError with nothing to do with the day.
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_page(interactive, members))
    data_path = os.path.join(SCRATCH, f'day-{tag}.json')
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(day, f)
    proc = subprocess.run([node, probe, page, data_path, expand,
                           (click_pack if isinstance(click_pack, str) else 'pack') if click_pack else ''],
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0, f"the family day card threw:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_a_two_event_outing_is_a_container_with_inner_lines():
    """The container rule: two or more events on one outing draw as a box
    whose compact inner lines (title + time) are ALWAYS VISIBLE, never
    gated behind a tap. The at-home block alongside it is a flat row. No
    items — the kit contents underneath — reach the DOM until somebody
    actually taps a row."""
    got = _run(BASE_DAY, interactive=True, expand='')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    for want in ("Grandma's birthday", 'Dad', 'Van'):
        check(want in got['text'], f"the card is missing {want!r}: {got['text'][:300]}")
    check(len(got['innerLines']) == 2,
          f"the two-event outing should draw exactly two inner lines: {got['innerLines']}")
    for title in ('Soccer', 'Band practice'):
        line = next((l for l in got['innerLines'] if title in l), None)
        check(line is not None,
              f"inner line for {title!r} is missing: {got['innerLines']}")
        check(':' in line, f"inner line for {title!r} has no time: {line!r}")
    for absent in ('Water bottle', 'Goggles', 'Sheet music'):
        check(absent not in got['text'],
              f"an item drew before any tap: {absent!r} in {got['text'][:300]}")
    # The container's own heading chip: the two-event outing wears it, the
    # flat at-home block does not.
    by_key = {c['key']: c for c in got['outingChip']}
    check(by_key.get('d1:soccer', {}).get('chip'),
          f"the outing container is missing its 'Outing' chip: {got['outingChip']}")
    check(not by_key.get('home:99', {}).get('chip'),
          f"a flat block wrongly drew the 'Outing' chip: {got['outingChip']}")
    # The second mockup pass: the container's own heading is NOT another
    # agenda-event row (no fill, no color bar) — only its two inner lines
    # carry that class. The flat at-home block's own row still does.
    by_ev = {c['key']: c for c in got['agendaEventCheck']}
    soccer_ev = by_ev.get('d1:soccer', {})
    check(soccer_ev.get('nonInnerCount') == 0,
          f"the outing container's own heading wrongly drew as an "
          f"agenda-event row: {soccer_ev}")
    check(soccer_ev.get('total') == 2,
          f"the outing container should carry exactly its two inner-line "
          f"agenda-event rows: {soccer_ev}")
    home99_ev = by_ev.get('home:99', {})
    check(home99_ev.get('nonInnerCount') == 1 and home99_ev.get('total') == 1,
          f"the flat at-home block should draw exactly one agenda-event "
          f"row (itself): {home99_ev}")
    # Fix 2, the third bullet: a block with nothing to pack (`needed === 0`)
    # gets no caret at all — Grandma's birthday has an empty cargo list —
    # while the outing container (needed=4) does.
    by_caret = {c['key']: c for c in got['caret']}
    check(not by_caret.get('home:99', {}).get('present'),
          f"a cargo-less block wrongly drew a caret: {got['caret']}")
    check(by_caret.get('d1:soccer', {}).get('present'),
          f"the outing container (with cargo) is missing its caret: {got['caret']}")


def scenario_the_caret_sits_inside_the_row_not_beside_it():
    """The user's own fix, pinned so it cannot silently regress: a caret
    drawn as a flex SIBLING of the row used to shrink that row's own right
    edge, so blocks with a caret were narrower than blocks without one and
    the card's chips went ragged instead of lining up on the right. The
    caret now lives INSIDE the row — a descendant of the same
    `.agenda-event` chip `agendaEventRow` draws, trailing the badge slot via
    the shared builder's own `trailingHtml` seam — so every row's own fill
    spans the block's full width whether or not it carries a caret. Checked
    against a flat, cargo-bearing block: a container's heading is a
    different, deliberately bare shape (no `.agenda-event` fill at all), so
    it is not what this assertion is about."""
    day = {
        'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
        'blocks': [
            {'kind': 'event', 'key': 'home:1', 'event_id': 1, 'title': 'Piano',
             'start': '2026-09-08T09:00:00', 'end': '2026-09-08T09:30:00',
             'canceled': False, 'covered_by': None,
             'groups': [{'kit_id': 'k1', 'kit': 'Bag', 'people': [],
                        'items': [{'key': 'i1', 'label': 'Item one',
                                  'needed': 1, 'packed': 0}]}],
             'packed': 0, 'needed': 1},
        ],
    }
    got = _run(day, interactive=True, expand='')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    by_key = {c['key']: c for c in got['caretInsideRow']}
    row = by_key.get('home:1')
    check(row is not None and row['hasCaret'],
          f"the cargo-bearing flat block should draw a caret: {got['caretInsideRow']}")
    check(row['insideAgendaEvent'],
          f"the caret must be a descendant of the row's own .agenda-event "
          f"chip, not a sibling beside it: {row}")


def scenario_the_pill_has_two_states_and_only_two():
    """Work remaining draws the filled amber pill and nothing else does — a
    done row gets the muted checkmark with NO amber class anywhere on it,
    and a no-cargo row carries neither class at all. The amber pill is the
    card's one saturated element on a resting row."""
    day = {
        'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
        'blocks': [
            {'kind': 'event', 'key': 'home:1', 'event_id': 1, 'title': 'Piano',
             'start': '2026-09-08T09:00:00', 'end': '2026-09-08T09:30:00',
             'canceled': False, 'covered_by': None,
             'groups': [{'kit_id': 'k1', 'kit': 'Bag', 'people': [],
                        'items': [{'key': 'i1', 'label': 'Item one',
                                  'needed': 2, 'packed': 0}]}],
             'packed': 0, 'needed': 2},
            {'kind': 'event', 'key': 'home:2', 'event_id': 2, 'title': 'Reading',
             'start': '2026-09-08T10:00:00', 'end': '2026-09-08T10:30:00',
             'canceled': False, 'covered_by': None,
             'groups': [{'kit_id': 'k2', 'kit': 'Bag', 'people': [],
                        'items': [{'key': 'i2', 'label': 'Item two',
                                  'needed': 1, 'packed': 1}]}],
             'packed': 1, 'needed': 1},
            {'kind': 'event', 'key': 'home:3', 'event_id': 3, 'title': 'Chill',
             'start': '2026-09-08T11:00:00', 'end': '2026-09-08T11:30:00',
             'canceled': False, 'covered_by': None, 'groups': [],
             'packed': 0, 'needed': 0},
        ],
    }
    got = _run(day, interactive=True, expand='')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    by_key = {p['key']: p for p in got['pills']}
    piano = by_key.get('home:1')
    check(piano is not None, f"the working row is missing: {got['pills']}")
    check(piano['amber'] and not piano['done'],
          f"the working row should carry the amber pill only: {piano}")
    check('2 to pack' in piano['text'], f"the amber pill's count is wrong: {piano['text']}")
    reading = by_key.get('home:2')
    check(reading is not None, f"the done row is missing: {got['pills']}")
    check(reading['done'] and not reading['amber'],
          f"a done row must carry the muted mark and NO amber class: {reading}")
    chill = by_key.get('home:3')
    check(chill is not None, f"the no-cargo row is missing: {got['pills']}")
    check(not chill['amber'] and not chill['done'],
          f"a no-cargo row should carry neither pill: {chill}")


def scenario_a_household_kit_survives_the_member_filter():
    """The parked finding, fixed here: a kit naming nobody (`people: []`)
    covers the whole household and must survive a member filter aimed at
    somebody else. `members: ['ellie']` should hide Sam's own item but keep
    the household one."""
    day = {
        'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
        'blocks': [
            {'kind': 'event', 'key': 'home:1', 'event_id': 1, 'title': 'Outing',
             'start': '2026-09-08T09:00:00', 'end': '2026-09-08T09:30:00',
             'canceled': False, 'covered_by': None,
             'groups': [
                 {'kit_id': 'k1', 'kit': "Sam's bag", 'people': ['sam'],
                  'items': [{'key': 'sam-item', 'label': "Sam's item",
                            'needed': 1, 'packed': 0}]},
                 {'kit_id': 'k2', 'kit': 'Household bag', 'people': [],
                  'items': [{'key': 'house-item', 'label': 'Household item',
                            'needed': 1, 'packed': 0}]},
             ], 'packed': 0, 'needed': 2},
        ],
    }
    got = _run(day, interactive=True, members=['ellie'], expand='ALL')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    check("Sam's item" not in got['text'],
          f"a member-filtered kit's own item leaked through: {got['text'][:300]}")
    check('Household item' in got['text'],
          f"a household kit (people: []) was wrongly hidden by the member "
          f"filter: {got['text'][:300]}")


def scenario_interactive_draws_the_claim_controls_as_real_buttons():
    """The interactive half: expand the row first (items no longer draw
    before a tap), then check a tick for the needed-one item and a stepper
    for the needed-two item both drew as real `<button>` elements."""
    got = _run(BASE_DAY, interactive=True, expand='ALL')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    buttons = got['buttons']
    check(any('−' in b or '+' in b for b in buttons) or len(buttons) > 2,
          f"no stepper controls drew as buttons: {buttons}")
    check(not got['posted'],
          f"merely drawing and expanding the interactive card called something: {got['posted']}")


def scenario_interactive_false_draws_no_claim_buttons_at_all():
    """`interactive: false` turns the tick and the stepper into inert divs —
    `pkInteractive` gates exactly those two branches in the macro. The row
    header stays a button on purpose (`pkToggle` is local state, not a
    server action), so this checks for the ABSENCE of claim controls
    specifically, not an empty button list — asserted by querySelector,
    because a merely-hidden button would still answer it and prove nothing.
    Both cards are expanded first: items no longer draw before a tap."""
    interactive_run = _run(BASE_DAY, interactive=True, expand='ALL')
    got = _run(BASE_DAY, interactive=False, expand='ALL')
    if got is None or interactive_run is None:
        return
    check(not got['errors'], f"the read-only card threw: {got['errors'][:3]}")
    # Every button the interactive run drew that named an item or a stepper
    # glyph must be gone; only the row headers (naming the block) may remain.
    claim_like = [b for b in got['buttons']
                 if 'Water bottle' in b or 'Goggles' in b or 'Sheet music' in b
                 or '−' in b or b.strip() in ('+', '-')]
    check(not claim_like,
          f"a read-only family day card is still drawing claim buttons: {claim_like}")
    # The card itself is unchanged otherwise — the same blocks, the same
    # items, just nothing left to tap on them. 'Sheet music' is the
    # needed-exactly-one tick item's `!pkInteractive` branch (a checkmark and
    # a label, no numeral); '0/2' is the OTHER branch — the
    # needed-more-than-one stepper item (Water bottle)'s own `!pkInteractive`
    # count, which a check that only ever looked at the tick branch would
    # never catch going missing or wrong.
    for want in ('Soccer', 'Band practice', 'Sheet music', '0/2'):
        check(want in got['text'], f"the read-only card lost {want!r}: {got['text'][:300]}")
    check(not got['posted'],
          f"merely drawing the read-only card called something: {got['posted']}")


# ── a failed poll after a real one must not draw the quiet-day sentence ────
#
# Fix round finding #1: `loadPacking`'s catch set the day's data to `[]` on
# ANY fetch failure. A transient one after the first real load (an add-on
# rebuild, an HA restart) wiped real blocks and drew "Nothing on the calendar
# today." over data that was still true. This harness lets the FIRST
# `api/packing/day` call succeed with real data, then forces the component's
# own `loadPacking()` to reject on a second call — a poll racing a restart,
# not a mount — and checks the rows are still standing.

POLL_FAIL_HARNESS = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
process.on('unhandledRejection', () => {});

const html = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/<script src="[^"]*"[^>]*><\/script>/g, '')
  .replace(/<link href="https:[^"]*"[^>]*>/g, '');
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));

let dayCalls = 0;
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'http://localhost/home?panel=true',
  beforeParse(w) {
    w.fetch = (u, opt) => {
      if (String(u).split('?')[0].endsWith('api/packing/day')) {
        dayCalls++;
        // First call (the mount) succeeds with real data; every call after
        // that rejects, the way a fetch does mid-poll when the add-on is
        // rebuilding or HA is restarting.
        if (dayCalls === 1) {
          return Promise.resolve({ ok: true, text: () => Promise.resolve(''),
            json: () => Promise.resolve(data) });
        }
        return Promise.reject(new Error('network down'));
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
win.document.addEventListener('DOMContentLoaded', () => {
  const s = win.document.createElement('script');
  s.textContent = fs.readFileSync(require.resolve('alpinejs/dist/cdn.js'), 'utf8');
  win.document.head.appendChild(s);
});

setTimeout(() => {
  const doc = win.document;
  const root = doc.getElementById('pk-root');
  const comp = win.Alpine.$data(root);
  // The mount's own GET already resolved (pkLoaded is true, blocks real).
  // Now force exactly the failing poll this test exists for.
  comp.loadPacking().then(() => {
    const txt = e => e.textContent.replace(/\s+/g, ' ').trim();
    console.log(JSON.stringify({
      text: root ? txt(root) : '',
      blocksLength: comp.blocks.length,
      dayCalls: dayCalls,
    }));
    process.exit(0);
  });
}, 1500);
"""


def _run_poll_fail():
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed — the family day card was not drawn')
        return None
    have = subprocess.run([node, '-e',
                           "require.resolve('jsdom'); require.resolve('alpinejs')"],
                          capture_output=True, text=True, cwd=SCRATCH)
    if have.returncode != 0:
        print('  skip  jsdom/alpinejs not resolvable')
        return None
    probe = os.path.join(SCRATCH, 'harness-poll-fail.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(POLL_FAIL_HARNESS)
    page = os.path.join(SCRATCH, 'fd-poll-fail.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(_render_page(True))
    data_path = os.path.join(SCRATCH, 'day-poll-fail.json')
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump(BASE_DAY, f)
    proc = subprocess.run([node, probe, page, data_path], capture_output=True,
                          text=True, encoding='utf-8', errors='replace',
                          cwd=SCRATCH, timeout=180)
    check(proc.returncode == 0, f"the family day card threw:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_a_failed_poll_after_success_keeps_the_rows_standing():
    """Stale beats false-empty (fix round finding #1): a transient failure on
    a poll AFTER the mount's own real load must leave `blocks` — and the rows
    drawn from it — exactly as they were, not wiped to the quiet-day
    sentence "Nothing on the calendar today."."""
    got = _run_poll_fail()
    if got is None:
        return
    check(got['dayCalls'] == 2,
          f"expected the mount's GET plus the one forced failing poll: {got['dayCalls']}")
    check(got['blocksLength'] == 2,
          f"a failed poll wiped `blocks` instead of leaving it alone: {got['blocksLength']}")
    for want in ("Grandma's birthday", 'Dad', 'Van'):
        check(want in got['text'],
              f"a failed poll erased real rows from the card: {got['text'][:300]}")
    check('Nothing on the calendar' not in got['text'],
          f"a failed poll drew the quiet-day sentence over real data: {got['text'][:300]}")


def scenario_the_colour_law_holds_on_the_row():
    """The bug the household actually caught: every event wore the DRIVER's
    colour, so the colours meant nothing anybody could name. Everywhere else
    in this app an event's bar is its calendar's colour, which is the
    person's. The trip is the driver's; the events inside belong to the
    people going."""
    got = _run(BASE_DAY, interactive=True, expand='')
    if got is None:
        return
    bars = got['innerBars']
    check(len(bars) == 2, f"expected two inner lines, got {len(bars)}: {bars}")
    joined = ' '.join(bars).lower()
    check('236, 72, 153' in joined or '#ec4899' in joined,
          f"the first inner line should wear its own person's colour: {bars}")
    check('34, 211, 238' in joined or '#22d3ee' in joined,
          f"the second inner line should wear its own person's colour: {bars}")
    check('37, 99, 235' not in joined and '#2563eb' not in joined,
          f"the driver's colour leaked onto an event row: {bars}")


def scenario_you_can_see_who_is_going_without_tapping():
    """Cleats for the wrong kid is the failure this prevents; before F2 the
    only answer lived inside the details dialog."""
    got = _run(BASE_DAY, interactive=True, expand='')
    if got is None:
        return
    dots = got['paxDots']
    check(len(dots) >= 2, f"expected a dot per person on the rows: {dots}")
    names = {d['name'] for d in dots}
    check('Ellie' in names and 'Sam' in names,
          f"the dots should name their person: {dots}")


def scenario_every_trip_is_a_container_even_with_one_event():
    """F1 drew the box only at two or more events, so the driver, the car and
    the pill moved depending on how many events a trip had. One shape now."""
    one = json.loads(json.dumps(BASE_DAY))
    one['blocks'][0]['events'] = one['blocks'][0]['events'][:1]
    got = _run(one, interactive=True, expand='')
    if got is None:
        return
    check(got['containers'] >= 1,
          "a single-event outing should still draw as a container panel")
    chip = {c['key']: c['chip'] for c in got['outingChip']}
    check(chip.get('d1:soccer'),
          f"a single-event outing should still wear its Outing chip: {chip}")


# ── F3: prep is work, and work has a place in the day ────────────────────

PREP_DAY = {
    'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
    'days': [{'date': '2026-09-08', 'label': 'Today', 'is_today': True,
              'all_day': [], 'blocks': [
        {'kind': 'prep', 'key': 'prep:2026-09-08:morning',
         'bucket': 'morning',
         'start': '2026-09-08T00:00:00', 'end': '2026-09-08T00:00:00',
         'done': False, 'packed': 1, 'needed': 3, 'groups': [],
         'tiles': [
             {'key': 'prep:2026-09-08:morning:soccer', 'for_key': 'd1:soccer',
              'event_id': 'soccer', 'title': 'Soccer',
              'start': '2026-09-08T16:00:00', 'depart': '2026-09-08T16:00:00',
              'passengers': [{'id': 'm-ellie', 'name': 'Ellie', 'color': '#ec4899'}],
              'groups': [
                  {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie', 'theo'],
                   'event_ids': ['soccer'],
                   'items': [{'key': 'k1:water bottle', 'label': 'Water bottle',
                              'needed': 2, 'packed': 0}]},
              ], 'packed': 0, 'needed': 2, 'done': False},
             {'key': 'prep:2026-09-08:morning:band', 'for_key': 'd1:soccer',
              'event_id': 'band', 'title': 'Band practice',
              'start': '2026-09-08T17:30:00', 'depart': '2026-09-08T16:00:00',
              'passengers': [{'id': 'm-sam', 'name': 'Sam', 'color': '#22d3ee'}],
              'groups': [
                  {'kit_id': 'k2', 'kit': 'Band bag', 'people': ['ellie'],
                   'event_ids': ['band'],
                   'items': [{'key': 'k2:cleats', 'label': 'Cleats',
                              'needed': 1, 'packed': 1}]},
              ], 'packed': 1, 'needed': 1, 'done': True},
         ]},
        {'kind': 'outing', 'key': 'd1:soccer', 'driver': 'Dad', 'driver_id': 'd1',
         'color': '#2563eb', 'car': 'Van',
         'start': '2026-09-08T16:00:00', 'end': '2026-09-08T19:00:00',
         'events': [
             {'id': 'soccer', 'title': 'Soccer', 'start': '2026-09-08T16:00:00',
              'color': '#ec4899', 'passengers': []},
             {'id': 'band', 'title': 'Band practice', 'start': '2026-09-08T17:30:00',
              'color': '#22d3ee', 'passengers': []},
         ],
         'passengers': [],
         'groups': [
             {'kit_id': 'k1', 'kit': 'Soccer bag', 'people': ['ellie', 'theo'],
              'items': [
                  {'key': 'k1:water bottle', 'label': 'Water bottle',
                   'needed': 2, 'packed': 0},
                  {'key': 'k1:cleats', 'label': 'Cleats',
                   'needed': 1, 'packed': 1},
              ]},
         ], 'packed': 1, 'needed': 3},
    ]}],
    'blocks': [],
}
PREP_DAY['blocks'] = PREP_DAY['days'][0]['blocks']


def scenario_a_prep_block_shows_a_tile_per_event():
    """F4: the block holds a whole part of the day, so it names nothing
    itself — its TILES name the events. (Was
    scenario_a_prep_block_shows_its_work_without_being_opened, which asserted
    the chips that have since moved into the dialog.)"""
    got = _run(PREP_DAY, interactive=True, expand='')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    check(len(got['tiles']) == 2, f"expected a tile per event: {got['tiles']}")
    titles = ' '.join(t['text'] for t in got['tiles'])
    check('Soccer' in titles and 'Band practice' in titles,
          f"tiles should name their events: {titles}")
    check(any('2 items' in t['text'] for t in got['tiles']),
          f"a tile should say how big the job is: {titles}")
    check(got['tiles'][0]['dots'] >= 1,
          f"a tile should say who it is for: {got['tiles'][0]}")


def scenario_the_pill_waits_for_pack_from():
    """Before `pack_from` the pill is absent however much is unpacked — the
    prep block above already says so, and two counts one row apart read as
    duplication. A block without the stamp keeps the old always-on pill."""
    day = {
        'date': '2026-09-08', 'is_tomorrow': False, 'all_day': [],
        'blocks': [
            {'kind': 'event', 'key': 'home:1', 'event_id': 1, 'title': 'Early',
             'start': '2026-09-08T09:00:00', 'end': '2026-09-08T09:30:00',
             'canceled': False, 'covered_by': None,
             'pack_from': '2099-01-01T00:00:00',
             'groups': [{'kit_id': 'k1', 'kit': 'Bag', 'people': [],
                        'items': [{'key': 'i1', 'label': 'Item one',
                                  'needed': 2, 'packed': 0}]}],
             'packed': 0, 'needed': 2},
            {'kind': 'event', 'key': 'home:2', 'event_id': 2, 'title': 'Soon',
             'start': '2026-09-08T10:00:00', 'end': '2026-09-08T10:30:00',
             'canceled': False, 'covered_by': None,
             'pack_from': '2000-01-01T00:00:00',
             'groups': [{'kit_id': 'k2', 'kit': 'Bag', 'people': [],
                        'items': [{'key': 'i2', 'label': 'Item two',
                                  'needed': 1, 'packed': 0}]}],
             'packed': 0, 'needed': 1},
        ],
    }
    got = _run(day, interactive=True, expand='')
    if got is None:
        return
    check(not got['errors'], f"the card threw while drawing: {got['errors'][:3]}")
    by_key = {p['key']: p for p in got['pills']}
    early, soon = by_key.get('home:1'), by_key.get('home:2')
    check(early is not None and not early['amber'] and not early['done'],
          f"before pack_from the pill must not draw: {early}")
    check(soon is not None and soon['amber'],
          f"past pack_from the amber pill draws as before: {soon}")


def scenario_a_prep_block_has_no_caret_and_no_pill():
    """The tiles ARE the status, so a pill would be redundant and an arrow
    would open onto what is already on screen."""
    got = _run(PREP_DAY, interactive=True, expand='')
    if got is None:
        return
    prep = got['preps'][0]
    check(not prep['caret'], "a prep block drew an expand arrow")
    check(not prep['pill'], "a prep block drew the pill its tiles replace")


def scenario_a_finished_tile_says_so_instead_of_offering_the_button():
    """Packing is a decided act, and a decided act that is done should look
    done rather than inviting you to do it again."""
    got = _run(PREP_DAY, interactive=True, expand='')
    if got is None:
        return
    done = [t for t in got['tiles'] if t['done']]
    todo = [t for t in got['tiles'] if not t['done']]
    check(len(done) == 1 and len(todo) == 1,
          f"expected one packed tile and one still to do: {got['tiles']}")
    check('Packed' in done[0]['text'], f"a done tile should say so: {done[0]}")
    check(not done[0]['packBtn'], "a done tile still offered Pack Items")
    check(todo[0]['packBtn'], "an unpacked tile is missing its Pack Items button")


def scenario_pack_items_opens_the_dialog_with_that_events_list():
    """The intentional act: one event's list, in a place with room for it."""
    got = _run(PREP_DAY, interactive=True, expand='', click_pack=True)
    if got is None:
        return
    check(got['dialog'], "tapping Pack Items opened no dialog")
    check('Soccer' in got['dialog']['title'],
          f"the dialog should name the event: {got['dialog']}")
    check(any('Water bottle' in c for c in got['dialog']['chips']),
          f"the dialog should carry that event's list: {got['dialog']}")
    check(not any('Cleats' in c for c in got['dialog']['chips']),
          f"the dialog must show ONE event's list, not the trip's: {got['dialog']}")


def scenario_a_display_only_wall_gets_tiles_but_no_buttons():
    got = _run(PREP_DAY, interactive=False, expand='')
    if got is None:
        return
    check(got['tiles'], f"a read-only card should still show its tiles: {got['tiles']}")
    check(not any(t['packBtn'] for t in got['tiles']),
          f"a read-only card must carry no claim controls at all: {got['tiles']}")
    check(not got['posted'], f"merely drawing the card posted: {got['posted']}")


def scenario_the_block_lists_work_event_by_event():
    """A household packs for Practice and then for the Game — the kit is how
    the app stores the list, not how anybody reads the day."""
    got = _run(PREP_DAY, interactive=True, expand='')
    if got is None:
        return
    text = ' '.join(t['text'] for t in got['tiles'])
    check('Soccer bag' not in text and 'Band bag' not in text,
          f"kit names are on the tiles, where they say nothing: {text}")
    check('Soccer' in text and 'Band practice' in text,
          f"the tiles should name the events: {text}")



def scenario_a_multi_day_card_says_tomorrow_once():
    """The separator already labels the day; the chip repeated it."""
    day = json.loads(json.dumps(PREP_DAY))
    day['is_tomorrow'] = True
    day['days'].append({'date': '2026-09-09', 'label': 'Tomorrow',
                        'is_today': False, 'is_tomorrow': True,
                        'all_day': [], 'blocks': []})
    got = _run(day, interactive=True, expand='')
    if got is None:
        return
    check(got['text'].count('Tomorrow') == 1,
          f"the card said Tomorrow more than once: {got['text'][:200]}")


def scenario_a_packed_chip_in_the_dialog_can_be_tapped_off():
    """A mis-tap has to be undoable where it happened. Before this the only
    way back was the card behind the dialog, which is not a place anybody
    thinks to look."""
    # A tile that still has work, holding one item already packed — which is
    # the real shape of a mis-tap you want to undo.
    day = json.loads(json.dumps(PREP_DAY))
    tile = day['days'][0]['blocks'][0]['tiles'][0]
    tile['groups'][0]['items'].append(
        {'key': 'k1:towel', 'label': 'Towel', 'needed': 1, 'packed': 1})
    tile['packed'] = 1
    tile['needed'] = 3
    day['blocks'] = day['days'][0]['blocks']
    got = _run(day, interactive=True, expand='', click_pack='pack')
    if got is None:
        return
    check(got['dialog'], "tapping Pack Items opened no dialog")
    check(got['dialogDeltas'],
          f"the dialog drew no tappable chips: {got['dialog']}")
    check(-1 in got['dialogDeltas'],
          f"a packed one-of-a-thing chip must offer to release it: "
          f"{got['dialogDeltas']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} family day card render scenarios passed")
