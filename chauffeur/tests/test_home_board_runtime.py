"""home.html's board helpers actually RUN, against a stub DOM.

The board's tiles are Alpine templates, so most of what they do can only be
seen in a browser. What can be checked here is the arithmetic underneath them —
and on these three tiles the arithmetic IS the tile. A timeline block is a
`top`/`height` pair in percent; get the sign wrong and a wall panel draws an
empty box with no error anywhere, which is precisely the failure mode this
whole board exists to avoid (you cannot tell a broken tile from a quiet one).

Same technique as test_nav_runtime: pull the script out of the rendered
template, run it in node against a DOM thin enough to be honest, and assert on
the values. Skips (rather than fails) when node is unavailable.

Run from chauffeur/:  python tests/test_home_board_runtime.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _board_script():
    src = open(os.path.join(TPL, 'home.html'), encoding='utf-8').read()
    blocks = re.findall(r'<script>(.*?)</script>', src, re.S)
    body = next((b for b in blocks if 'function homeBoard()' in b), None)
    check(body, "home.html no longer defines homeBoard()")
    return body


# A DOM thin enough to be honest. The helpers under test touch exactly three
# things — the URL, the panel theme attribute, and (in tone()) matchMedia — so
# those are what the stub provides. Anything else they reach for should fail
# loudly here rather than quietly on the wall.
HARNESS = r"""
globalThis.window = {
  location: { search: '', pathname: '/home' },
  matchMedia: function () { return { matches: false }; }
};
globalThis.document = {
  documentElement: { getAttribute: function () { return 'dark'; } },
  getElementById: function () { return null; },
  addEventListener: function () {}
};
globalThis.setInterval = function () { return 0; };
"""

PROBE = r"""
const b = homeBoard();
b.board = BOARD;
b.nowTs = new Date(NOW).getTime();

const drives = BOARD.tiles.find(t => t.key === 'drives').data;
const map = BOARD.tiles.find(t => t.key === 'map').data;
const w = drives.window;

const blocks = [];
drives.lanes.forEach(l => l.runs.forEach(r => blocks.push({
  id: r.id, style: b.blockStyle(r, w, l.color),
  top: b.pctFor(r.start, w), bottom: b.pctFor(r.end, w)
})));

console.log(JSON.stringify({
  ticks: b.hourTicks(w),
  nowPct: b.nowPct(w),
  outsideWindow: (() => { b.nowTs = new Date(w.end).getTime() + 3600000;
                          const v = b.nowPct(w);
                          b.nowTs = new Date(NOW).getTime(); return v; })(),
  blocks: blocks,
  unmapped: b.unmapped(map.people).map(p => p.name),
  fills: ['map', 'drives', 'meals', 'moments', 'trips', 'calendar', 'chores']
    .filter(k => b.fillsTile(k)),
  badWindow: b.hourTicks({ start: 'nonsense', end: 'nonsense' })
}));
"""


def _run(board, now):
    node = shutil.which('node')
    if not node:
        print("  skip  node not installed — the board helpers were not executed")
        return None
    js = (HARNESS + _board_script()
          + PROBE.replace('BOARD', json.dumps(board)).replace('NOW', json.dumps(now)))
    path = os.path.join(tempfile.gettempdir(), 'chauffeur_home_board_probe.js')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(js)
    proc = subprocess.run([node, path], capture_output=True, text=True, timeout=30)
    check(proc.returncode == 0,
          f"the board's helpers threw in node:\n{proc.stderr[:2000]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


# The fixture is one ordinary weekday evening: a drive under way, a second
# driver overlapping it, and a family half of whom Home Assistant can see.
BOARD = {
    'tiles': [
        {'key': 'drives', 'data': {
            'window': {'start': '2026-08-08T15:00:00', 'end': '2026-08-08T20:00:00'},
            'count': 3,
            'lanes': [
                {'driver_id': 'drv1', 'driver': 'Sam', 'color': '#ef4444', 'runs': [
                    {'id': 'e1', 'title': 'Practice', 'at': '4:00 PM', 'live': True,
                     'start': '2026-08-08T16:00:00', 'end': '2026-08-08T17:30:00'},
                    {'id': 'e3', 'title': 'Piano', 'at': '7:00 PM', 'live': False,
                     'start': '2026-08-08T19:00:00', 'end': '2026-08-08T20:00:00'}]},
                {'driver_id': 'drv2', 'driver': 'Vovo', 'color': '#8b5cf6', 'runs': [
                    {'id': 'e2', 'title': 'Pickup', 'at': '5:45 PM', 'live': False,
                     'start': '2026-08-08T17:45:00', 'end': '2026-08-08T18:15:00'}]},
            ]}},
        {'key': 'map', 'data': {'mapped': 2, 'people': [
            {'name': 'Sam', 'member_id': 'm1', 'latitude': 41.5, 'longitude': -81.6,
             'state': 'not_home', 'driving': {'leg_title': 'Practice'}},
            {'name': 'Vovo', 'member_id': 'm2', 'latitude': 41.4, 'longitude': -81.7,
             'state': 'home', 'driving': None},
            {'name': 'Addison', 'member_id': 'm3', 'latitude': None, 'longitude': None,
             'state': None, 'driving': None},
        ]}},
    ],
}
NOW = '2026-08-08T16:30:00'


def scenario_a_block_is_where_and_as_tall_as_its_drive():
    """The whole tile is this sum. A 90-minute drive on a five-hour window is
    30% of the tile, one hour in from the top — and `height` must never come
    out negative, which is what a `bottom - top` on a clamped pair does the
    moment a drive runs past the end of the window."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    by_id = {b['id']: b for b in got['blocks']}
    e1 = by_id['e1']
    check(abs(e1['top'] - 20) < 0.01,
          f"a 4pm drive on a 3pm-8pm window starts a fifth of the way down, got {e1['top']}")
    check(abs((e1['bottom'] - e1['top']) - 30) < 0.01,
          f"90 minutes of five hours is 30% of the tile, got {e1['bottom'] - e1['top']}")
    check('height: 30%' in e1['style'] and 'top: 20%' in e1['style'],
          f"the style says something else than the numbers do: {e1['style']}")
    check('outline' in e1['style'],
          "the drive under way is not marked, so the one block that is HAPPENING "
          "looks like the three that are not")
    check('outline' not in by_id['e3']['style'], "and the others are not marked")
    for b in got['blocks']:
        check(b['bottom'] >= b['top'],
              f"block {b['id']} has negative height: {b}")


def scenario_now_is_on_the_tile_or_it_is_not_drawn():
    """A "now" line pinned to the top or bottom edge is a line that LIES —
    it says the present moment is the start of the evening. Outside the window
    it is simply not drawn."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    check(abs(got['nowPct'] - 30) < 0.01,
          f"4:30pm on a 3pm-8pm window is 30% down, got {got['nowPct']}")
    check(got['outsideWindow'] is None,
          f"an hour past the last drive there is no line to draw, got {got['outsideWindow']}")


def scenario_the_hour_rail_is_readable_at_tile_size():
    """Hour lines are what make a block's height read as a duration. But one
    per hour on a twelve-hour Saturday is a hatched box, so the step opens up
    rather than the labels overlapping."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    labels = [t['label'] for t in got['ticks']]
    check(labels == ['3p', '4p', '5p', '6p', '7p', '8p'],
          f"an hour a line across a five-hour window, got {labels}")
    check(all(0 <= t['pct'] <= 100 for t in got['ticks']),
          f"a tick outside the tile, got {got['ticks']}")
    check(got['badWindow'] == [],
          "a window the server could not compute must draw no rail rather than "
          "loop forever building one")


def scenario_a_pin_cannot_say_where_somebody_is_going():
    """The chips are not a leftovers list. Somebody with no pin belongs there
    because there is nowhere else to say where they are — and somebody DRIVING
    belongs there too, pin or not, because "en route to practice" is the more
    useful half and a marker cannot carry it."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    check(got['unmapped'] == ['Sam', 'Addison'],
          f"the driver and the untracked child, and not the parent sitting at "
          f"home with a pin on her, got {got['unmapped']}")


def scenario_the_drawn_tiles_are_the_ones_given_their_slot():
    """A map or a timeline sized to its content is an inch tall in a 240px
    box, and a text tile stretched to fill is a paragraph with a hole under
    it. The two lists have to stay distinct."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    check(set(got['fills']) == {'map', 'drives', 'meals', 'moments', 'trips'},
          f"the tiles drawn into their slot have drifted: {got['fills']}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} home-board runtime scenarios passed")
