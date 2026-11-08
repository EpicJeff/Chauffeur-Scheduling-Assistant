"""The rooms read after the draft: containment that ignores floating-point
noise, and a heartbeat while it runs (plan
docs/superpowers/plans/2026-11-08-house-editor-whole-building-draft.md, Task 11;
spec docs/superpowers/specs/2026-11-08-house-editor-whole-building-draft-design.md
sections 4 and 6; .superpowers/sdd/2026-11-08-house-editor-whole-building-draft/task-11-fixes.md
fixes 1 and 3).

Fix 1. A room edge at y 14.33 against the outline's 14.333 is not "outside".
Before the containment check, room polygon vertices and interior-wall
endpoints within 0.5 ft of an outline edge or exterior wall line snap onto it;
then a point within 0.25 ft of the outline counts as inside.
- The recorded main-house rooms answer (draft_rooms-main-house.json) settles
  every room whose polygon lies within its level's outline grown by 0.5 ft.
- A room or interior wall reaching 2 ft outside still ghosts, with its why.
- Through a real build: a room 0.4 ft outside settles with its vertices on the
  outline, and an interior wall poking 0.4 ft out settles with its end on it.

Fix 3. The draft heartbeat also runs around the rooms read:
"Reading the rooms of the <building name> drawings, M:SS so far." at least
every 15 s on the injectable clock twin_build._clock, plain, no raw id.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_draft_rooms.py
"""
import copy
import json
import math
import os
import re
import sys
import tempfile
import time
import traceback

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_draft_rooms_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_store as ts  # noqa: E402
from test_twin_build import check  # noqa: E402
import test_twin_build_draft_side as side  # noqa: E402
from test_twin_build_draft_replay import ReplayReader, outside_by, recorded  # noqa: E402

OUTSIDE_ROOM = "This room extends outside its floor's outline."
OUTSIDE_WALL = "This interior wall extends outside its floor's outline."
ROOMS_BEAT = re.compile(r'^Reading the rooms of the Main house drawings, (\d+):(\d\d) so far\.$')
EPS = 1e-6


def _inch(v):
    return round(v * 12) / 12


def _main_house_for_check():
    """The main house as the rooms check sees it after normalize: levels and
    exterior walls from the recorded draft (inch-rounded, as normalize leaves
    them), rooms and interior walls from the recorded rooms answer, as read."""
    draft = recorded('draft-main-house.json')['building']
    rooms = recorded('draft_rooms-main-house.json')
    levels = [{**copy.deepcopy(l), 'outline': [[_inch(x), _inch(y)] for x, y in l['outline']],
               'state': 'settled', 'src': {'step': 'draft'}} for l in draft['levels']]
    walls = [{**copy.deepcopy(w), 'from': [_inch(c) for c in w['from']], 'to': [_inch(c) for c in w['to']],
              'state': 'settled', 'src': {'step': 'draft'}} for w in draft['walls']]
    walls += [{**copy.deepcopy(w), 'id': f'room-wall-{i}', 'state': 'settled', 'src': {'step': 'draft_rooms'}}
              for i, w in enumerate(rooms['walls'])]
    house_rooms = [{**copy.deepcopy(r), 'name': r['name'] or 'Room', 'id': f'room-{i}', 'state': 'settled',
                    'src': {'step': 'draft_rooms'}} for i, r in enumerate(rooms['rooms'])]
    return {'id': 'house', 'name': 'Main house', 'levels': levels, 'walls': walls, 'rooms': house_rooms,
            'openings': [], 'roof': {'sections': [], 'extensions': []}}


def _outline(house, lid):
    return next(l['outline'] for l in house['levels'] if l['id'] == lid)


# --- fix 1 ---------------------------------------------------------------------

def test_recorded_rooms_settle_within_half_a_foot():
    house = _main_house_for_check()
    # Synthetic pieces 2 ft outside: the side bump's room run 2 ft past x 70,
    # and an interior wall from inside the bump to 2 ft past it.
    house['rooms'].append({'id': 'room-out', 'name': 'Out', 'level': 'L1', 'state': 'settled',
                           'src': {'step': 'draft_rooms'},
                           'polygon': [[59, 22], [72, 22], [72, 42], [59, 42]]})
    house['walls'].append({'id': 'wall-out', 'level': 'L1', 'from': [65, 30], 'to': [72, 30], 'height': 10,
                           'thickness': .33, 'exterior': False, 'state': 'settled', 'src': {'step': 'draft_rooms'}})
    expected = {r['id']: outside_by(r['polygon'], _outline(house, r['level'])) > .5 + EPS for r in house['rooms']}
    check(sum(expected.values()) == 1 and expected['room-out'],
          ('test setup: every recorded room lies within its outline grown by 0.5 ft',
           sorted(k for k, v in expected.items() if v)))
    tb._check_draft_rooms(house, {'id': 'draft_rooms', 'kind': 'draft_rooms'})
    wrong = [(r['level'], r['polygon'], r.get('state'), r.get('why')) for r in house['rooms']
             if r['id'] != 'room-out' and r.get('state') == 'ghost']
    check(not wrong, ('every recorded room within 0.5 ft of its outline settles',
                      f'{len(wrong)} of {len(house["rooms"]) - 1} ghosted', wrong[:3]))
    out = next(r for r in house['rooms'] if r['id'] == 'room-out')
    check(out.get('state') == 'ghost' and out.get('why') == OUTSIDE_ROOM,
          ('a room 2 ft outside still ghosts, with its why', out.get('state'), out.get('why')))
    wall = next(w for w in house['walls'] if w['id'] == 'wall-out')
    check(wall.get('state') == 'ghost' and wall.get('why') == OUTSIDE_WALL,
          ('an interior wall 2 ft outside still ghosts, with its why', wall.get('state'), wall.get('why')))
    inner = [(w['from'], w['to'], w.get('why')) for w in house['walls']
             if w['src']['step'] == 'draft_rooms' and w['id'] != 'wall-out' and w.get('state') == 'ghost']
    check(not inner, ('every recorded interior wall settles', inner[:3]))


def test_build_snaps_rooms_and_walls_onto_the_outline():
    draft = recorded('draft-main-house.json')
    rooms = recorded('draft_rooms-main-house.json')
    bump = next(r for r in rooms['rooms'] if r['level'] == 'L1'
                and sorted(map(tuple, r['polygon'])) == [(59, 22), (59, 42), (70, 22), (70, 42)])
    bump['polygon'] = [[59, 22], [70.4, 22], [70.4, 42], [59, 42]]        # 0.4 ft past x 70
    garage = next(r for r in rooms['rooms'] if r['level'] == 'L1'
                  and sorted(map(tuple, r['polygon'])) == [(37, 0), (37, 22), (59, 0), (59, 22)])
    garage['polygon'] = [[37, -2], [59, -2], [59, 22], [37, 22]]          # 2 ft past y 0
    poke = next(w for w in rooms['walls'] if w['level'] == 'L1' and w['from'] == [0, 36] and w['to'] == [14.33, 36])
    poke['from'] = [-0.4, 36]                                             # 0.4 ft past x 0
    side._drawn_house()
    reader = ReplayReader(draft, rooms)
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = side._finish(b)
    check(st['state'] == 'done', (st['state'], st.get('pause'), side._trouble(st)))
    house = next(h for h in ts.current()['buildings'] if h['id'] == 'house')
    outline = _outline(house, 'L1')
    placed = [r for r in house['rooms'] if (r.get('src') or {}).get('step') == 'draft_rooms' and r['level'] == 'L1']

    def find(x0, x1, y0, y1):
        return [r for r in placed if abs(min(p[0] for p in r['polygon']) - x0) <= .6
                and abs(max(p[0] for p in r['polygon']) - x1) <= .6
                and abs(min(p[1] for p in r['polygon']) - y0) <= .6
                and abs(max(p[1] for p in r['polygon']) - y1) <= .6]

    near = find(59, 70, 22, 42)
    check(len(near) == 1, ('test setup: the side-bump room is in the plan', len(near)))
    check(near[0].get('state') != 'ghost', ('a room 0.4 ft outside settles', near[0].get('state'), near[0].get('why')))
    check(outside_by(near[0]['polygon'], outline) <= .01,
          ('its vertices snap onto the outline', near[0]['polygon']))
    far = find(37, 59, -2, 22)
    check(len(far) == 1 and far[0].get('state') == 'ghost' and far[0].get('why') == OUTSIDE_ROOM,
          ('a room 2 ft outside still ghosts, with its why', [(r.get('state'), r.get('why')) for r in far]))
    walls = [w for w in house['walls'] if (w.get('src') or {}).get('step') == 'draft_rooms' and w['level'] == 'L1'
             and abs(w['from'][1] - 36) <= .1 and abs(w['to'][1] - 36) <= .1]
    check(len(walls) == 1, ('test setup: the interior wall at y 36 is in the plan',
                            [(w['from'], w['to']) for w in walls]))
    check(walls[0].get('state') != 'ghost', ('an interior wall poking 0.4 ft out settles',
                                             walls[0].get('state'), walls[0].get('why')))
    check(min(walls[0]['from'][0], walls[0]['to'][0]) >= -.01,
          ('its end snaps onto the outline', walls[0]['from'], walls[0]['to']))


# --- fix 3 ---------------------------------------------------------------------

class RoomsHookReader(side.SideReader):
    """SideReader, plus rooms_hook(run) run on the calling thread before the
    rooms read answers."""

    def __init__(self, rooms_hook=None, **kw):
        super().__init__(**kw)
        self.rooms_hook = rooms_hook
        self.rooms_returned_seq = None

    def __call__(self, kind, images, context, *, run, step):
        if kind == 'draft_rooms' and self.rooms_hook:
            try:
                self.rooms_hook(run)
            finally:
                events = side._events(run)
                self.rooms_returned_seq = max((e['seq'] for e in events), default=0)
        return super().__call__(kind, images, context, run=run, step=step)


def _beats(events):
    return [e for e in events if e['type'] == 'log' and ROOMS_BEAT.match(e.get('text') or '')]


def test_heartbeat_during_rooms_read():
    side._drawn_house()
    now, saved = side._fake_clock()
    try:
        def rooms_hook(run):
            # A blocked 50 s rooms read: advance the fake clock in 1 s ticks;
            # at each 15 s mark give the heartbeat a moment (real time).
            for elapsed in range(1, 51):
                now[0] += 1.0
                if elapsed % 15 == 0:
                    side._wait(lambda: len(_beats(side._events(run))) >= elapsed // 15, 3)
                else:
                    time.sleep(0.005)

        reader = RoomsHookReader(rooms_hook=rooms_hook)
        b = tb.start({'part': 'house'}, reader=reader, inline=False)
        st = side._finish(b)
        reader.outline_returned.wait(10)
        # After the rooms read the heartbeat stops.
        before = len(_beats(tb.status(b)['events']))
        now[0] += 40.0
        time.sleep(0.5)
        after = len(_beats(tb.status(b)['events']))
    finally:
        side._restore_clock(saved)
    check(st['state'] == 'done', (st['state'], st.get('pause'), side._trouble(st)))
    events = tb.status(b)['events']
    beats = _beats(events)
    logs = [(e.get('step'), e.get('text')) for e in events if e['type'] == 'log']
    check(len(beats) >= 3, ('a 50 s rooms read: at least 3 heartbeat lines naming the building', logs))
    times = [int(m.group(1)) * 60 + int(m.group(2)) for m in (ROOMS_BEAT.match(e['text']) for e in beats)]
    check(times == sorted(times) and 45 <= max(times) <= 51, ('M:SS counts the rooms read so far', times))
    check(all(e.get('step') == 'draft_rooms' for e in beats), ('the lines belong to the rooms step',
                                                               [e.get('step') for e in beats]))
    draft_settled = [e['seq'] for e in events if e['type'] == 'settled' and e.get('step') == 'draft']
    check(draft_settled and all(e['seq'] > draft_settled[0] for e in beats)
          and reader.rooms_returned_seq is not None and all(e['seq'] <= reader.rooms_returned_seq for e in beats),
          ('the lines go out while the rooms read is in flight', [e['seq'] for e in beats], draft_settled[:1],
           reader.rooms_returned_seq))
    for e in beats:
        text = e['text']
        check('draft_rooms' not in text and b not in text and not re.search(r'\bL\d\b', text),
              ('plain words, no raw id', text))
    check(after == before, ('no rooms heartbeat after the rooms read returns', before, after))


TESTS = (
    test_recorded_rooms_settle_within_half_a_foot,
    test_build_snaps_rooms_and_walls_onto_the_outline,
    test_heartbeat_during_rooms_read,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
