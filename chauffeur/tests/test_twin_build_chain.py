"""One Build for the whole place (plan .superpowers/sdd/
2026-11-07-house-editor-slice-1b-i, Task 6, with amendment A10): the lot,
then each building with drawings, then each shell, as chained builds.

- start({'part': 'place'}) plans lot (when the lot has a plot page), then each
  building with floor pages in place order, then each building without floor
  pages that has a footprint, in place order. A building with neither is
  skipped with the log event "Skipped <name>: it has no footprint yet." in the
  first build. Nothing to build is refused with "Add a building with drawings
  or a footprint first."
- the first build carries inputs['then'] (the remaining parts); only the last
  carries compose.
- a build with a non-empty then that reaches done creates the next part's
  build, records next (and the event next) and dispatches it, the same way it
  was run: an inline chain runs every successor inline.
- a paused, stopped or failed build never starts its next; resuming a chained
  build continues the chain; a start over ends the chain for good.
- A10: next is recorded once and is durable. Rereading (and answering) a
  finished build never creates a successor. recover() reconciles a done build
  with a non-empty then and no next (a crash between the two saves) by
  creating its successor exactly once.

The reader is test_twin_build_parts' PartReader with the L-shaped outline; its footprint is deliberately larger, so its only pause is fit. Sources are blank 17 x 11 inch PDFs.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_chain.py
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import traceback

# Never let a run touch chauffeur/data: the temp folder is set before any
# services import, unconditionally.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_chain_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_register as tr  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import _accept_all, _pdf, check  # noqa: E402
from test_twin_build_parts import (PartReader, _confirm_lot, _expect_value_error, _kinds,  # noqa: E402
                                   _l_local, _read_kinds, _wait)

SKIPPED_GARAGE = 'Skipped Garage: it has no footprint yet.'
NOTHING = 'Add a building with drawings or a footprint first.'
SHED_FOOTPRINT = [[120, 0], [130, 0], [130, 12], [120, 12]]
GARAGE_FOOTPRINT = [[140, 0], [160, 0], [160, 20], [140, 20]]
HOUSE_KINDS = ['draft', 'draft_rooms', 'fit']


# --- fakes and helpers ---------------------------------------------------------

class ThreadReader(PartReader):
    """PartReader with the L outline, noting the thread of every read and able
    to fail one step for good."""

    def __init__(self, *a, fail_at=None, **kw):
        super().__init__(*a, l_outline=True, **kw)
        self.threads = []
        self.fail_at = fail_at

    def __call__(self, kind, images, context, *, run, step):
        self.threads.append((kind, threading.get_ident()))
        if step == self.fail_at:
            self.calls.append({'kind': kind, 'step': step, 'context': {}, 'images': len(images)})
            raise RuntimeError('a bug, not a read error')
        return super().__call__(kind, images, context, run=run, step=step)


def _place():
    """The brief's place: a lot with a confirmed placement, Main house (id
    house) with a floor page and a footprint it fits, a shed with a footprint
    and no drawings, and a garage with neither. In place order the shed and
    the garage come before the house, so the planned order is the rule's, not
    the list's."""
    engine_tests._fresh()
    ts.add_building('Shed', 'shed')
    ts.add_building('Garage', 'garage')
    sheets = ts.save_source('drawing', 'house.pdf', _pdf(1))            # legacy upload: Main house, id house
    plot = ts.save_source('drawing', 'plot.pdf', _pdf(1), part='lot')
    ts.set_page_roles([
        {'source': sheets, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': plot, 'page': 1, 'role': 'plot', 'level': None, 'box': None, 'building': 'lot'}])
    _confirm_lot(plot)
    footprint = [tr.to_world({'position': [60.0, 80.0], 'rotation': 90}, p) for p in [[1.5 * x, 1.5 * y] for x, y in _l_local()]]
    ts.update_building('house', {'footprint': footprint, 'footprint_from': 'plot'})
    ts.update_building('shed', {'footprint': SHED_FOOTPRINT, 'footprint_from': 'typed'})
    order = [b['id'] for b in ts.place()['buildings']]
    check(order == ['shed', 'garage', 'house'], ('fixture: place order', order))
    check(next(b for b in ts.place()['buildings'] if b['id'] == 'garage')['footprint'] is None, 'fixture: garage')
    return sheets, plot


def _state_file(bid):
    """A build as saved on disk: the chain must be durable, not process-local."""
    return json.loads((Path(ts.DATA_DIR) / 'builds' / bid / 'state.json').read_text(encoding='utf-8'))


def _saved_builds():
    return sorted(p.parent.name for p in (Path(ts.DATA_DIR) / 'builds').glob('*/state.json'))


def _events(bid, kind):
    return [e for e in tb.status(bid)['events'] if e['type'] == kind]


def _trouble(st):
    return (st['state'], st.get('pause'), [e for e in st['events'] if e['type'] in ('error', 'question')][-3:])


def _follow(first, limit=10):
    """Accept every pause along the chain; return the chain's build ids."""
    ids, bid = [], first
    for _ in range(limit):
        ids.append(bid)
        st = _accept_all(bid)
        check(st['state'] == 'done', ('every build in the chain ends done', bid, _trouble(st)))
        bid = st['next']
        if bid is None:
            return ids
    raise AssertionError('the chain never ends')


def _run_place_chain():
    _place()
    reader = ThreadReader()
    first = tb.start({'part': 'place'}, reader=reader, inline=True)
    return _follow(first), reader


# --- the plan and the chain ----------------------------------------------------

def scenario_place_chain_order():
    _place()
    reader = ThreadReader()
    main = threading.get_ident()
    lot = tb.start({'part': 'place'}, reader=reader, inline=True)

    # The lot ran inline to done and its successor was created and run inline,
    # up to the house's fit pause, before start returned.
    st = tb.status(lot)
    check(st['state'] == 'done' and st['part'] == 'lot', ('the first build is the lot', st['part'], _trouble(st)))
    house = st['next']
    check(isinstance(house, str) and house != lot, ('the lot names its successor', st['next']))
    check(_saved_builds() == sorted([lot, house]), ('two builds so far', _saved_builds()))
    st = tb.status(house)
    check(st['state'] == 'paused' and st['part'] == 'house' and st['pause']['step'] == 'fit',
          ('an inline chain runs its successor inline, to its first pause', _trouble(st), st['part']))
    check(st['next'] is None, ('a paused build has no successor yet', st['next']))
    check(any(kind == 'outline' for kind, _ in reader.threads)
          and all(thread != main if kind == 'outline' else thread == main for kind, thread in reader.threads),
          ('only the outline read runs on a side thread in an inline chain', reader.threads))

    st = _accept_all(house)
    check(st['state'] == 'done', _trouble(st))
    shed = st['next']
    check(isinstance(shed, str) and shed not in (lot, house), ('the house names its successor', shed))
    st = tb.status(shed)
    check(st['state'] == 'done' and st['part'] == 'shed', ('the shell ran inline to done', _trouble(st), st['part']))
    check(st['next'] is None, ('the last build has no successor', st['next']))
    check(_saved_builds() == sorted([lot, house, shed]), ('three builds in turn', _saved_builds()))
    check(all(thread != main if kind == 'outline' else thread == main for kind, thread in reader.threads),
          reader.threads)

    chain = [lot, house, shed]
    check([tb.status(b)['part'] for b in chain] == ['lot', 'house', 'shed'], [tb.status(b)['part'] for b in chain])
    saved = [_state_file(b) for b in chain]
    check([s['next'] for s in saved] == [house, shed, None], ('next is saved', [s['next'] for s in saved]))
    check([s['inputs']['then'] for s in saved] == [['house', 'shed'], ['shed'], []],
          ('each build carries the parts after it', [s['inputs']['then'] for s in saved]))
    check([s['inputs']['compose'] for s in saved] == [False, False, True],
          ('only the last build composes', [s['inputs']['compose'] for s in saved]))
    check([len(_events(b, 'next')) for b in chain] == [1, 1, 0], ('one next event per handoff',
          [_events(b, 'next') for b in chain]))
    check(_kinds(lot) == ['lot', 'site'], _kinds(lot))
    check(_kinds(house) == HOUSE_KINDS, _kinds(house))
    check(_kinds(shed) == ['shell', 'compose'], _kinds(shed))
    check(sum(k == 'compose' for b in chain for k in _kinds(b)) == 1, 'one compose for the whole place')

    first_log = [e.get('text') for e in _events(lot, 'log')]
    check(SKIPPED_GARAGE in first_log, ('the first build says what it skipped', first_log))
    check(_read_kinds(reader).count('site') == 1 and 'plot' not in _read_kinds(reader),
          ('a confirmed lot is not read again', _read_kinds(reader)))
    plan = ts.current()
    check(sorted(b['id'] for b in plan['buildings']) == ['house', 'shed'], [b['id'] for b in plan['buildings']])
    check(plan['site'].get('lot'), ('the lot is in the plan', plan['site']))


def scenario_place_skips_shell_without_footprint():
    chain, _ = _run_place_chain()
    check([tb.status(b)['part'] for b in chain] == ['lot', 'house', 'shed'], [tb.status(b)['part'] for b in chain])
    check('garage' not in _state_file(chain[0])['inputs']['then'], ('the garage is not planned',
          _state_file(chain[0])['inputs']['then']))
    check(not any(b['id'] == 'garage' for b in ts.current()['buildings']), ('the garage is not built',
          [b['id'] for b in ts.current()['buildings']]))
    logs = [[e.get('text') for e in _events(b, 'log')] for b in chain]
    check(logs[0].count(SKIPPED_GARAGE) == 1, ('said once, in the first build', logs[0]))
    check(all(SKIPPED_GARAGE not in found for found in logs[1:]), ('and only there', logs))
    # With a footprint the garage builds too, as a shell after the shed: shells
    # come in place order.
    ts.update_building('garage', {'footprint': GARAGE_FOOTPRINT, 'footprint_from': 'typed'})
    first = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
    chain = _follow(first)
    check([tb.status(b)['part'] for b in chain] == ['lot', 'house', 'shed', 'garage'],
          [tb.status(b)['part'] for b in chain])
    check(not any(e.get('text') == SKIPPED_GARAGE for b in chain for e in _events(b, 'log')), 'nothing skipped')
    check(_kinds(chain[2]) == ['shell'] and _kinds(chain[3]) == ['shell', 'compose'],
          ('a shell inside a chain only builds its shell', _kinds(chain[2]), _kinds(chain[3])))
    check(any(b['id'] == 'garage' for b in ts.current()['buildings']), [b['id'] for b in ts.current()['buildings']])


def scenario_chain_stops_with_build():
    _place()
    reader = ThreadReader()
    lot = tb.start({'part': 'place'}, reader=reader, inline=True)
    house = tb.status(lot)['next']
    check(house and tb.status(house)['state'] == 'paused', ('the house pauses at fit', house))
    check(_saved_builds() == sorted([lot, house]) and tb.status(house)['next'] is None,
          ('no shed build while the house is paused', _saved_builds()))
    tb.stop(house)
    check(tb.status(house)['state'] == 'stopped', tb.status(house)['state'])
    check(_saved_builds() == sorted([lot, house]) and tb.status(house)['next'] is None,
          ('a stopped build never starts its next', _saved_builds()))
    tb.resume(house, inline=True)
    st = tb.status(house)
    check(st['state'] == 'paused' and st['pause']['step'] == 'fit', _trouble(st))
    check(_saved_builds() == sorted([lot, house]), ('still nothing after a resume to the pause', _saved_builds()))
    st = _accept_all(house)
    check(st['state'] == 'done', _trouble(st))
    shed = st['next']
    check(shed and tb.status(shed)['part'] == 'shed' and tb.status(shed)['state'] == 'done',
          ('resuming a chained build continues the chain', shed))
    check(_saved_builds() == sorted([lot, house, shed]), _saved_builds())


def scenario_failed_build_never_chains():
    _place()
    reader = ThreadReader(fail_at='draft_rooms')
    lot = tb.start({'part': 'place'}, reader=reader, inline=True)
    house = tb.status(lot)['next']
    st = _accept_all(house)
    check(st['state'] == 'failed', ('a bug in a read fails the build', _trouble(st)))
    check(st['next'] is None and _saved_builds() == sorted([lot, house]),
          ('a failed build never starts its next', st['next'], _saved_builds()))
    check(_state_file(house)['next'] is None, _state_file(house)['next'])


def scenario_chain_stops_on_start_over():
    # A start over while the house is paused: the chain is gone for good.
    _place()
    lot = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
    house = tb.status(lot)['next']
    check(house and tb.status(house)['state'] == 'paused', house)
    ts.start_over()
    count = len(tb._BUILDS)
    for attempt in (lambda: tb.answer(house, 'fit', {'accept': True}),
                    lambda: tb.resume(house, inline=True)):
        try:
            attempt()
        except (ts.StaleGeneration, KeyError):
            pass                # stale, or already forgotten with its files
        else:
            raise AssertionError('a build from before the start over cannot go on')
    check(len(tb._BUILDS) <= count and _saved_builds() == [], ('no build is created', len(tb._BUILDS), _saved_builds()))
    check(ts.current() is None and tb.latest() is None, 'nothing was built after the start over')

    # A stale worker: the house's read is in flight when the build is stopped
    # and the house started over. When the read returns, nothing follows.
    _place()
    reader = ThreadReader(block_at='draft_rooms')
    lot = tb.start({'part': 'place'}, reader=reader, inline=False)
    deadline = time.time() + 20
    while time.time() < deadline and not tb.status(lot).get('next'):
        time.sleep(0.05)
    house = tb.status(lot).get('next')
    check(house, ('the lot hands on to the house', _trouble(tb.status(lot))))
    check(reader.blocked.wait(20), 'the house reads its rooms before fit')
    tb.stop(house)
    ts.start_over()
    count = len(tb._BUILDS)
    reader.release.set()
    deadline = time.time() + 20
    while time.time() < deadline and tb._WORKERS.get(house, {}).get('busy'):
        time.sleep(0.05)
    check(not tb._WORKERS.get(house, {}).get('busy'), 'the stale worker returned')
    time.sleep(0.3)
    check(len(tb._BUILDS) == count, ('no build after the stale worker returns', len(tb._BUILDS), count))
    check(_saved_builds() == [] and ts.current() is None and tb.latest() is None,
          ('nothing is saved after a start over', _saved_builds()))


def scenario_nothing_to_build():
    engine_tests._fresh()
    _expect_value_error(lambda: tb.start({'part': 'place'}, reader=ThreadReader(), inline=True), NOTHING)
    # A garage with no drawings and no footprint, and a lot with no plot page.
    ts.add_building('Garage', 'garage')
    plot = ts.save_source('drawing', 'survey.pdf', _pdf(1), part='lot')
    ts.set_page_roles([{'source': plot, 'page': 1, 'role': 'survey', 'level': None, 'box': None, 'building': 'lot'}])
    _expect_value_error(lambda: tb.start({'part': 'place'}, reader=ThreadReader(), inline=True), NOTHING)
    check(tb.latest() is None and _saved_builds() == [], ('a refused start leaves no build', _saved_builds()))
    check(ts.current() is None, 'nothing was built')


# --- A10: the chain is durable -----------------------------------------------

def scenario_reread_finished_predecessor_creates_nothing():
    chain, _ = _run_place_chain()
    lot, house, shed = chain
    before = _saved_builds()
    check(len(before) == 3, before)
    # Rereading the lot's yard runs it to done again: no second house build.
    tb.reread(lot, 'site', reader=ThreadReader(), inline=True)
    st = tb.status(lot)
    check(st['state'] == 'done', _trouble(st))
    check(st['next'] == house and _state_file(lot)['next'] == house, ('next is recorded once', st['next'], house))
    check(_saved_builds() == before, ('a reread of a finished build creates nothing', _saved_builds(), before))
    check(len(_events(lot, 'next')) == 1, _events(lot, 'next'))
    # Rereading the house's fit pauses it; answering runs it to done again.
    tb.reread(house, 'fit', reader=ThreadReader(), inline=True)
    st = tb.status(house)
    check(st['state'] == 'paused' and st['pause']['step'] == 'fit', _trouble(st))
    st = _accept_all(house)
    check(st['state'] == 'done', _trouble(st))
    check(st['next'] == shed and _state_file(house)['next'] == shed, ('next is recorded once', st['next'], shed))
    check(_saved_builds() == before, ('an answer on a reread build creates nothing', _saved_builds(), before))
    check(len(_events(house, 'next')) == 1, _events(house, 'next'))


def scenario_recover_reconciles_crash_window():
    chain, _ = _run_place_chain()
    lot, house, old_shed = chain
    # The add-on died after the house was saved done and before its successor
    # was saved: the house has a non-empty then and no next, and no shed build.
    root = Path(ts.DATA_DIR) / 'builds'
    state = _state_file(house)
    check(state['state'] == 'done' and state['inputs']['then'] == ['shed'], (state['state'], state['inputs']))
    state['next'] = None
    state['events'] = [e for e in state['events'] if e['type'] != 'next']
    (root / house / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    shutil.rmtree(root / old_shed)
    tb._forget()
    check(_saved_builds() == sorted([lot, house]), _saved_builds())

    # A reread of the done house before any recover still creates nothing.
    tb.reread(house, 'draft_rooms', reader=ThreadReader(), inline=True)
    check(tb.status(house)['state'] == 'done', _trouble(tb.status(house)))
    check(_saved_builds() == sorted([lot, house]) and tb.status(house)['next'] is None,
          ('reread never creates a successor, even in the crash window', _saved_builds()))

    tb._forget()
    tb.recover()
    after = _saved_builds()
    check(len(after) == 3 and lot in after and house in after and old_shed not in after,
          ('recover creates the missing successor', after))
    shed = next(b for b in after if b not in (lot, house))
    check(tb.status(house)['next'] == shed and _state_file(house)['next'] == shed,
          ('the house now names it, on disk', _state_file(house)['next'], shed))
    check(len(_events(house, 'next')) == 1, _events(house, 'next'))
    saved = _state_file(shed)
    check(saved['inputs'].get('part') == 'shed' and saved['inputs']['then'] == [] and saved['inputs']['compose'] is True,
          ('the successor is the shed, last in the chain', saved['inputs']))
    check([s['kind'] for s in saved['steps']] == ['shell', 'compose'], [s['kind'] for s in saved['steps']])
    check(_state_file(lot)['next'] == house, ('a build that has next is left alone', _state_file(lot)['next']))

    # It runs on its own or waits to be resumed; either way it can finish.
    st = _wait(shed)
    if st['state'] != 'done':
        check(st['state'] in ('stopped', 'paused'), ('the successor is resumable', _trouble(st)))
        tb.resume(shed, reader=ThreadReader(), inline=True)
        st = tb.status(shed)
    check(st['state'] == 'done', _trouble(st))

    # Exactly once: recover again, with and without a restart, creates nothing.
    tb.recover()
    tb._forget()
    tb.recover()
    check(_saved_builds() == after, ('recover never creates a second successor', _saved_builds(), after))
    check(_state_file(house)['next'] == shed, _state_file(house)['next'])


SCENARIOS = (
    scenario_place_chain_order,
    scenario_place_skips_shell_without_footprint,
    scenario_chain_stops_with_build,
    scenario_failed_build_never_chains,
    scenario_chain_stops_on_start_over,
    scenario_nothing_to_build,
    scenario_reread_finished_predecessor_creates_nothing,
    scenario_recover_reconciles_crash_window,
)


def scenario_removed_part_is_skipped_mid_chain():
    _place()
    lot = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
    house = tb.status(lot)['next']
    check(tb.status(house)['state'] == 'paused', 'the house pauses before the shed is removed')
    ts.remove_building('shed')
    st = _accept_all(house)
    check(st['state'] == 'done' and st['next'] is None, _trouble(st))
    message = 'Skipped Shed: it is no longer part of your place.'
    check([e.get('text') for e in _events(house, 'log')].count(message) == 1,
          ('the predecessor explains the removed part', st['events']))
    check(any(p.get('by') == 'compose' for p in ts.current()['site']['planting']), 'the place is composed')
    check(_state_file(house)['inputs']['compose'] is True, 'the predecessor becomes the final part')
    before = _saved_builds()
    for _ in range(2):
        tb._forget()
        tb.recover()
        check(_saved_builds() == before and tb.status(house)['next'] is None, 'recovery creates nothing')
    check([e.get('text') for e in _events(house, 'log')].count(message) == 1, 'the skip is saved once')


def scenario_failing_successor_is_logged():
    _place()
    lot = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
    house = tb.status(lot)['next']
    original = tb.twin_place.shell_building
    calls = []

    def fail_shell(*args, **kwargs):
        calls.append(True)
        raise RuntimeError('successor shell failed')

    try:
        tb.twin_place.shell_building = fail_shell
        st = _accept_all(house)
        check(st['state'] == 'done' and st['next'] is None, _trouble(st))
        errors = _events(house, 'error')
        check(errors and errors[-1].get('text'), ('the predecessor records the handoff failure', st['events']))
        check(any(e['type'] == 'error' for e in _state_file(house)['events']), 'the error is durable')
        before = _saved_builds()
        for _ in range(2):
            tb._forget()
            tb.recover()
        check(len(calls) == 1 and _saved_builds() == before, ('recovery never retries the failure', calls))
    finally:
        tb.twin_place.shell_building = original
    tb._forget()
    tb.recover()
    check(_saved_builds() == before and tb.status(house)['next'] is None,
          'fixing the shell does not resurrect a failed chain')


SCENARIOS += (scenario_removed_part_is_skipped_mid_chain, scenario_failing_successor_is_logged)


def scenario_missing_footprint_reassigns_compose():
    for keep_garage, cleared in ((False, 'shed'), (True, 'shed'), (True, 'garage')):
        _place()
        ts.update_building('shed', {'name': 'Garden shed'})
        if keep_garage:
            ts.update_building('garage', {'footprint': GARAGE_FOOTPRINT, 'footprint_from': 'typed'})
        lot = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
        house = tb.status(lot)['next']
        # Model a restored place with its shell footprint cleared; the normal
        # update endpoint currently requires a nonempty footprint.
        with ts.LIFECYCLE, ts._LOCK:
            row = ts._state()
            next(b for b in row['place']['buildings'] if b['id'] == cleared)['footprint'] = None
            ts._save(row)
        st = _accept_all(house)
        name = 'Garden shed' if cleared == 'shed' else 'Garage'
        message = f'Skipped {name}: it has no footprint yet.'
        check([e.get('text') for e in _events(house, 'log')].count(message) == 1, 'the missing footprint is explained')
        final = st['next'] if keep_garage else house
        check(final and tb.status(final)['state'] == 'done', ('the new last part finishes', final))
        expected = ('garage' if cleared == 'shed' else 'shed') if keep_garage else 'house'
        check(tb.status(final)['part'] == expected, 'the remaining order is kept')
        check(_state_file(final)['inputs']['compose'] is True and _kinds(final)[-1] == 'compose',
              'composition moves to the new last part')
        check(any(p.get('by') == 'compose' for p in ts.current()['site']['planting']), 'the place is composed')
        check(not any(b['id'] == cleared for b in ts.current()['buildings']), 'the skipped shell is never built')


def scenario_recover_failure_is_reconciled_once():
    chain, _ = _run_place_chain()
    lot, house, shed = chain
    root = Path(ts.DATA_DIR) / 'builds'
    state = _state_file(house)
    state['next'] = None
    state['events'] = [e for e in state['events'] if e['type'] != 'next']
    (root / house / 'state.json').write_text(json.dumps(state), encoding='utf-8')
    shutil.rmtree(root / shed)
    original = tb.twin_place.shell_building
    calls = []

    def fail_shell(*args, **kwargs):
        calls.append(True)
        raise OSError('cannot create the recovered successor')

    try:
        tb.twin_place.shell_building = fail_shell
        for _ in range(2):
            tb._forget()
            tb.recover()
        check(len(calls) == 1, ('recovery reconciles a failed handoff once', calls))
        check(len(_events(house, 'error')) == 1, 'the recovery failure is saved on the predecessor')
        check(_saved_builds() == sorted([lot, house]), 'no successor was created')
    finally:
        tb.twin_place.shell_building = original


def scenario_successor_launch_failure_leaves_no_busy_worker():
    _place()
    lot = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
    house = tb.status(lot)['next']
    original = tb._save

    def fail_launch(build):
        if build['inputs'].get('part') == 'shed' and build['state'] == 'running':
            raise OSError('cannot save the successor launch')
        return original(build)

    try:
        tb._save = fail_launch
        st = _accept_all(house)
    finally:
        tb._save = original
    check(st['state'] == 'done' and _events(house, 'error'), 'the predecessor logs a launch failure')
    check(not any(w.get('busy') for w in tb._WORKERS.values()), 'no nonexistent worker is busy')
    check(not tb.running(), 'the failed launch does not block a new build')
    before = _saved_builds()
    tb._forget()
    tb.recover()
    check(_saved_builds() == before and len(_events(house, 'error')) == 1, 'recovery does not relaunch')
    shed = tb.start({'part': 'shed'}, reader=ThreadReader(), inline=True)
    check(tb.status(shed)['state'] == 'done', 'a new build is allowed after a launch failure')

    _place()
    lot = tb.start({'part': 'place'}, reader=ThreadReader(), inline=True)
    house = tb.status(lot)['next']
    dispatch = tb._dispatch

    def fail_dispatch(build, *args):
        if build['inputs'].get('part') == 'shed':
            raise RuntimeError('cannot start the successor worker')
        return dispatch(build, *args)

    try:
        tb._dispatch = fail_dispatch
        _accept_all(house)
    finally:
        tb._dispatch = dispatch
    check(_events(house, 'error'), 'a dispatch failure is also logged on the predecessor')
    check(not tb.running() and not any(w.get('busy') for w in tb._WORKERS.values()),
          'a dispatch failure leaves no active build or worker')


SCENARIOS += (scenario_missing_footprint_reassigns_compose, scenario_recover_failure_is_reconciled_once,
              scenario_successor_launch_failure_leaves_no_busy_worker)


if __name__ == '__main__':
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)
