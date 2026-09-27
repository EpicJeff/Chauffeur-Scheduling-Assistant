"""My Day is one timeline: a program's session sits among the drives at its
own time, as a row that opens on a tap.

User report (2026-09-26): "When there are programs on the current day, they
take up a huge amount of real estate and push the drives so far out of view
... It is my day, not my programs and my drives." My Day drew a full practice
card, then a "My Programs" section of whole program cards (steps, lesson,
sessions ahead, three buttons each), and only THEN the drives -- so a noon
guitar session sat above a morning drive, and every program cost a screen.

Pinned here in a real browser against the served app:
  * today's session is ONE compact row between the drive before it and the
    drive after it, in time order;
  * it opens on a tap and closes again, and opened it is the whole program
    card (nothing a person could do before is gone);
  * a program with no session today is a compact row AFTER the day, never
    above it;
  * nothing about programs sits above the first drive.

Run from chauffeur/:  python tests/test_myday_timeline_live.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_myday_timeline_'))

from harness import check
from services import storage


def _seed():
    today = datetime.date.today()
    iso = today.isoformat()
    for t in ('members_table', 'programs_table', 'protected_commitments_table'):
        getattr(storage, t).truncate()
    storage.add_passenger({'id': 'p1', 'name': 'Lily', 'calendar_ids': ['p1']})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child',
                        'passenger_id': 'p1'})

    def program(pid, title, cid, days, start, end):
        storage.add_protected_commitment({
            'id': cid, 'member_id': 'kid', 'title': title + ' practice',
            'days_of_week': days, 'time_start': start, 'time_end': end,
            'active': True})
        storage.add_program({
            'id': pid, 'member_id': 'kid', 'title': title, 'state': 'active',
            'phases': [{'name': 'Basics', 'what': 'Open chords and a strum.',
                        'steps': ['Tune up', 'G-C-D changes, five minutes',
                                  'Strum along to one song'],
                        'milestone': 'Clean changes at 60 bpm'}],
            'shape': {'sessions_per_week': len(days), 'minutes': 30,
                      'preferred_days': []},
            'baseline': {'start_date': iso, 'target_date': None,
                         'target_event_id': None, 'rebaselined_at': None,
                         'rebaselines': 0},
            'emissions': {'commitment_ids': [cid], 'thread_ids': [],
                          'event_ids': []}})

    # Guitar every day at noon: between the morning and the evening drive.
    program('prog-guitar', 'Guitar', 'c-guitar', list(range(7)), '12:00', '12:30')
    # Running on every day EXCEPT today: no session today, so it belongs
    # after the day, not in it.
    program('prog-run', 'Running', 'c-run',
            [d for d in range(7) if d != today.weekday()], '17:00', '17:30')

    sched = {'events': [
        {'id': 'e-am', 'title': 'Swim team', 'calendar_ids': ['p1'],
         'start': iso + 'T07:00:00', 'end': iso + 'T08:00:00'},
        {'id': 'e-pm', 'title': 'Piano lesson', 'calendar_ids': ['p1'],
         'start': iso + 'T18:00:00', 'end': iso + 'T19:00:00'},
    ], 'assignments': {}}
    storage.get_cached_schedule = lambda: sched


ORDER_JS = """() => {
  const wrap = document.getElementById('myday-content');
  const all = [...wrap.querySelectorAll('*')];
  const at = txt => all.findIndex(el => el.children.length === 0 &&
                                   (el.textContent || '').includes(txt));
  const row = wrap.querySelector('[data-myday-program="prog-guitar"]');
  const other = wrap.querySelector('[data-myday-program="prog-run"]');
  const body = row && row.querySelector('[data-myday-body]');
  return {
    swim: at('Swim team'), piano: at('Piano lesson'),
    guitarRow: row ? all.indexOf(row) : -1,
    runRow: other ? all.indexOf(other) : -1,
    rowHeight: row ? row.getBoundingClientRect().height : 0,
    bodyShown: !!(body && body.offsetParent),
    guitarRows: wrap.querySelectorAll('[data-myday-program="prog-guitar"]').length,
    programsHeader: at('My Program'),
  };
}"""


def scenario_a_session_sits_in_the_day_as_a_row_that_opens():
    from live_app import live_app
    served = live_app(_seed)
    if served is None:
        return
    try:
        handle = served.browser()
        with handle as page:
            page.goto(served.url('app'))
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'kid')")
            page.goto(served.url('app'))
            page.wait_for_timeout(1200)
            skip = page.get_by_text('Skip', exact=True)
            if skip.count():
                skip.first.click()
                page.wait_for_timeout(400)
            page.evaluate("if (typeof setView === 'function') setView('myday')")
            page.wait_for_function(
                "(document.getElementById('myday-content') || {}).textContent"
                " && document.getElementById('myday-content').textContent.includes('Piano lesson')",
                timeout=15000)
            page.wait_for_timeout(600)
            o = page.evaluate(ORDER_JS)
            check(o['guitarRow'] >= 0, 'the Guitar session is drawn: %r' % o)
            check(o['guitarRows'] == 1,
                  'Guitar appears once, not as a session AND a program card: %r' % o)
            check(o['swim'] < o['guitarRow'] < o['piano'],
                  'the noon session sits between the 7am and 6pm drives: %r' % o)
            check(o['runRow'] > o['piano'],
                  'a program with no session today comes after the day: %r' % o)
            check(o['programsHeader'] < 0 or o['programsHeader'] > o['piano'],
                  'nothing about programs heads the day: %r' % o)
            check(not o['bodyShown'], 'the session row starts closed: %r' % o)
            check(o['rowHeight'] < 90,
                  'closed, a session costs one row, not a screen: %r' % o)

            page.click('[data-myday-program="prog-guitar"] [data-myday-toggle]')
            page.wait_for_timeout(200)
            opened = page.evaluate(ORDER_JS)
            check(opened['bodyShown'], 'a tap opens the session: %r' % opened)
            body = page.locator('[data-myday-program="prog-guitar"] [data-myday-body]')
            for words in ('G-C-D changes', 'Add a session', 'Reached it',
                          'Clean changes at 60 bpm'):
                check(body.get_by_text(words, exact=False).first.is_visible(),
                      'opened, the whole program card is there: %r missing' % words)
            page.click('[data-myday-program="prog-guitar"] [data-myday-toggle]')
            page.wait_for_timeout(200)
            check(not page.evaluate(ORDER_JS)['bodyShown'],
                  'and a second tap closes it')
            shots = os.environ.get('MYDAY_SHOTS')
            if shots:
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(shots, 'myday-closed.png'))
                page.click('[data-myday-program="prog-guitar"] [data-myday-toggle]')
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(shots, 'myday-open.png'))
    finally:
        served.stop()
    check(not handle.errors, 'the page threw: %r' % handle.errors[:3])


DRIVES_ORDER_JS = """() => {
  const today = new Date().toLocaleDateString('en-CA');
  const pane = document.getElementById('pane-' + currentDates.indexOf(today));
  if (!pane) return { err: 'no today pane' };
  const all = [...pane.querySelectorAll('*')];
  const at = txt => all.findIndex(el => el.children.length === 0 &&
                                   (el.textContent || '').includes(txt));
  const row = pane.querySelector('[data-myday-program="prog-guitar"]');
  const body = row && row.querySelector('[data-myday-body]');
  const today_ = document.getElementById('today-content');
  return {
    swim: at('Swim team'), piano: at('Piano lesson'),
    guitarRow: row ? all.indexOf(row) : -1,
    guitarRows: pane.querySelectorAll('[data-myday-program="prog-guitar"]').length,
    runRow: all.indexOf(pane.querySelector('[data-myday-program="prog-run"]')),
    rowHeight: row ? row.getBoundingClientRect().height : 0,
    bodyShown: !!(body && body.offsetParent),
    stackHasProgram: !!(today_ && /Guitar|Running/.test(today_.textContent || '')),
  };
}"""


def scenario_the_drivers_my_day_threads_sessions_into_the_drives():
    """The same law on the driver's tab, which is ALSO labelled "My Day"
    (`tab-drives`). The user's report was about this one: a parent who
    drives never sees the passenger lens, and here the practice-now card
    and whole program cards stacked above every drive."""
    from live_app import live_app

    def seed():
        _seed()
        storage.add_member({'id': 'dad', 'name': 'Jeff', 'role': 'parent',
                            'driver_id': 'd1'})
        storage.add_driver({'id': 'd1', 'name': 'Jeff', 'color_code': '#38bdf8'})
        # the two programs belong to the parent here: his own day
        for pid in ('prog-guitar', 'prog-run'):
            storage.update_program(pid, {'member_id': 'dad'})
        for cid in ('c-guitar', 'c-run'):
            storage.update_protected_commitment(cid, {'member_id': 'dad'})

    served = live_app(seed)
    if served is None:
        return
    iso = datetime.date.today().isoformat()
    sched = {
        'events': [
            {'id': 'e-am', 'title': 'Swim team', 'location': 'Pool',
             'start': iso + 'T07:00:00', 'end': iso + 'T08:00:00', 'calendar_ids': []},
            {'id': 'e-pm', 'title': 'Piano lesson', 'location': 'Studio',
             'start': iso + 'T18:00:00', 'end': iso + 'T19:00:00', 'calendar_ids': []}],
        'assignments': {'e-am': 'd1', 'e-pm': 'd1'},
        'route_edges': {}, 'initial_edges': {}, 'final_edges': {}}
    try:
        handle = served.browser()
        with handle as page:
            page.goto(served.url('app'))
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'dad');"
                          "localStorage.setItem('chauffeur_driver_id', 'd1')")
            page.goto(served.url('app'))
            page.wait_for_timeout(1500)
            skip = page.get_by_text('Skip', exact=True)
            if skip.count():
                skip.first.click()
                page.wait_for_timeout(400)
            page.evaluate("setView('drives')")
            page.wait_for_timeout(1500)
            # the drives as a fetch would hand them over, then the same
            # rebuild a fetch triggers
            page.evaluate("""async (s) => {
                scheduleData = Object.assign({}, scheduleData || {}, s);
                selectedDriverId = 'd1';
                await refreshPracticeSection(true);
                buildTimeline();
            }""", sched)
            page.wait_for_function(
                "!!document.querySelector('[data-myday-program=\"prog-guitar\"]')",
                timeout=15000)
            o = page.evaluate(DRIVES_ORDER_JS)
            check(not o.get('err'), 'today has a pane: %r' % o)
            check(o['guitarRows'] == 1, 'Guitar appears once: %r' % o)
            check(o['swim'] < o['guitarRow'] < o['piano'],
                  'the noon session sits between the 7am and 6pm drives: %r' % o)
            check(o['runRow'] > o['piano'],
                  'a program with no session today comes after the drives: %r' % o)
            check(not o['stackHasProgram'],
                  'the Today block above the drives carries no program: %r' % o)
            check(not o['bodyShown'] and o['rowHeight'] < 90,
                  'the session starts as one closed row: %r' % o)
            page.click('[data-myday-program="prog-guitar"] [data-myday-toggle]')
            page.wait_for_timeout(200)
            check(page.evaluate(DRIVES_ORDER_JS)['bodyShown'], 'and a tap opens it')
            shots = os.environ.get('MYDAY_SHOTS')
            if shots:
                page.set_viewport_size({'width': 390, 'height': 844})
                page.click('[data-myday-program="prog-guitar"] [data-myday-toggle]')
                page.wait_for_timeout(300)
                page.evaluate("document.querySelector('[data-myday-program=\"prog-guitar\"]').scrollIntoView({block:'center'})")
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(shots, 'drives-closed.png'))
    finally:
        served.stop()
    check(not handle.errors, 'the page threw: %r' % handle.errors[:3])


if __name__ == '__main__':
    scenario_a_session_sits_in_the_day_as_a_row_that_opens()
    scenario_the_drivers_my_day_threads_sessions_into_the_drives()
    print('test_myday_timeline_live OK')
