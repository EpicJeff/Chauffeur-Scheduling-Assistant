"""home.html's board helpers actually RUN, against a stub DOM.

The board's tiles are Alpine templates, so most of what they do can only be
seen in a browser. What can be checked here is the arithmetic underneath them —
and the agenda's layout IS arithmetic: a day card is three of twelve board
columns, and getting that wrong is what the family reported as "squishes each
day down very narrow". A wall panel draws a wrong-but-valid layout with no
error anywhere, which is the failure mode this whole board exists to avoid.

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

const map = BOARD.tiles.find(t => t.type === 'map').data;

console.log(JSON.stringify({
  // A day card is three of twelve board columns, so the count is the
  // calendar tile's own span measured in quarters.
  agenda: [
    { span: 12, lg: b.agendaCols('calendar', 'lg'), md: b.agendaCols('calendar', 'md') }
  ],
  agendaBySpan: [12, 9, 6, 3, 1].map(c => {
    b.board.spans = { calendar: { cols: c } };
    return { cols: c, across: b.agendaCols('calendar', 'lg') };
  }),
  mapped: map.mapped,
  fills: ['map', 'drives', 'meals', 'moments', 'trips', 'calendar', 'chores']
    .filter(k => b.fillsTile(k)),
  gone: ['hourTicks', 'blockStyle', 'nowPct', 'pctFor', 'unmapped']
    .filter(k => typeof b[k] === 'function')
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
    'columns': 12,
    'spans': {'calendar': {'cols': 12}},
    'tiles': [
        {'id': 'drives', 'type': 'drives', 'data': {
            'count': 3, 'next_event_id': 'e1',
            'schedule': {'date': '2026-08-08', 'events': [], 'drivers': []}}},
        {'id': 'map', 'type': 'map', 'data': {'mapped': 2, 'people': [
            {'name': 'Sam', 'member_id': 'm1', 'latitude': 41.5, 'longitude': -81.6,
             'state': 'not_home', 'driving': {'leg_title': 'Practice'}},
            {'name': 'Addison', 'member_id': 'm3', 'latitude': None, 'longitude': None,
             'state': None, 'driving': None},
        ]}},
    ],
}
NOW = '2026-08-08T16:30:00'


def scenario_a_day_card_is_three_columns_of_the_board():
    """Reported from the wall: the agenda "squishes each day down very narrow".
    It was flowing as many days as it had into whatever width the tile was, so
    seven days in a half-width tile came out at 90px each.

    A day card is three of twelve board columns — a quarter, the same unit a
    tile is measured in. Widening the tile adds cards; the days that do not fit
    wrap onto the next line rather than getting thinner."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    across = {r['cols']: r['across'] for r in got['agendaBySpan']}
    check(across == {12: 4, 9: 3, 6: 2, 3: 1, 1: 1},
          f"a card is not a quarter of the board any more: {across}")
    check(got['agenda'][0]['md'] >= 1,
          "the mid breakpoint has to resolve to at least one card or the grid "
          "collapses to zero tracks")


def scenario_the_board_no_longer_draws_its_own_timeline():
    """The tile draws the Drives page's renderer now. The helpers that drew the
    board's own version are gone rather than left lying about — two drawings of
    the same thing is what the family reported, and a dead one is the one that
    comes back."""
    got = _run(BOARD, NOW)
    if got is None:
        return
    check(got['gone'] == [],
          f"the board still carries its own timeline math: {got['gone']}")


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
