"""A moment can be added to yesterday's event from My Day.

User report (2026-09-28): "there is no way to add moments for events that
happened in the past ... uploading can sometimes be difficult at the
activities." My Day stopped at today, its cards had no way into the event's
thread, and the thread refused anyone the schedule had not placed there.

Pinned here in a real browser against the served app:
  * My Day's back arrow goes past today, and the day before reads Yesterday;
  * a card for an event that has started offers "Add a moment", and the tap
    opens that event's thread with the photo picker;
  * an event that has not started yet offers nothing.

Run from chauffeur/:  python tests/test_moments_past_days_live.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_moments_past_'))

from harness import check
from services import storage


def _seed():
    today = datetime.date.today()
    y = (today - datetime.timedelta(days=1)).isoformat()
    t = (today + datetime.timedelta(days=1)).isoformat()
    storage.members_table.truncate()
    storage.chat_channels_table.truncate()
    storage.add_passenger({'id': 'p1', 'name': 'Lily', 'calendar_ids': ['p1']})
    # An adult passenger: the child shell (v2.499.21x) hides a child's day
    # arrows by design, so the back-arrow path is pinned on an adult.
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'adult',
                        'passenger_id': 'p1'})
    sched = {'events': [
        {'id': 'e-game', 'title': 'Soccer game', 'calendar_ids': ['p1'],
         'start': y + 'T10:00:00', 'end': y + 'T11:00:00'},
        {'id': 'e-next', 'title': 'Piano recital', 'calendar_ids': ['p1'],
         'start': t + 'T18:00:00', 'end': t + 'T19:00:00'},
    ], 'assignments': {}}
    storage.get_cached_schedule = lambda: sched


CARD_JS = """(title) => {
  const wrap = document.getElementById('myday-content');
  const card = [...wrap.children].find(el => (el.textContent || '').includes(title));
  const btn = card && [...card.querySelectorAll('button')]
      .find(b => (b.textContent || '').includes('Add a moment'));
  return { card: !!card, button: !!btn,
           label: (document.getElementById('current-day-label') || {}).textContent };
}"""


def scenario_yesterdays_event_takes_a_moment():
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
            if skip.count() and skip.first.is_visible():
                skip.first.click()
                page.wait_for_timeout(400)
            page.evaluate("if (typeof setView === 'function') setView('myday')")
            page.wait_for_timeout(800)
            check(not page.evaluate(
                "document.getElementById('btn-prev-day').disabled"),
                  "My Day's back arrow is open at today")
            page.click('#btn-prev-day')
            page.wait_for_function(
                "(document.getElementById('myday-content') || {}).textContent"
                " && document.getElementById('myday-content').textContent.includes('Soccer game')",
                timeout=15000)
            o = page.evaluate(CARD_JS, 'Soccer game')
            check(o['label'] == 'Yesterday', 'the day before reads Yesterday: %r' % o)
            check(o['button'], "yesterday's game offers Add a moment: %r" % o)

            shots = os.environ.get('MYDAY_SHOTS')
            if shots:
                page.set_viewport_size({'width': 390, 'height': 844})
                page.wait_for_timeout(300)
                page.screenshot(path=os.path.join(shots, 'myday-yesterday-moment.png'))

            page.get_by_text('Add a moment').first.click()
            page.wait_for_function(
                "getComputedStyle(document.getElementById('thread-view')).display !== 'none'",
                timeout=10000)
            page.wait_for_timeout(400)
            title = page.evaluate("document.getElementById('thread-title').textContent")
            check('Soccer game' in title, "the tap opens the game's thread: %r" % title)
            ch = [c for c in storage.chat_channels_table.all() if c.get('kind') == 'event']
            check(len(ch) == 1 and ch[0].get('event_id') == 'e-game',
                  'the thread is the base event\'s: %r' % ch)
            check(page.locator('#thread-photo-input').count() == 1,
                  'and the photo picker is there to use')
            if shots:
                page.screenshot(path=os.path.join(shots, 'myday-yesterday-thread.png'))

            page.evaluate("setView('myday'); mydayOffset = 1; renderMyDay()")
            page.wait_for_function(
                "(document.getElementById('myday-content') || {}).textContent"
                " && document.getElementById('myday-content').textContent.includes('Piano recital')",
                timeout=15000)
            o = page.evaluate(CARD_JS, 'Piano recital')
            check(o['card'] and not o['button'],
                  'an event that has not started offers no moment yet: %r' % o)
    finally:
        served.stop()
    # Leaving a page cuts its live streams; that reset is the test moving on.
    errors = [e for e in handle.errors if 'ERR_CONNECTION_RESET' not in e]
    check(not errors, 'the page threw: %r' % errors[:3])


if __name__ == '__main__':
    scenario_yesterdays_event_takes_a_moment()
    print('test_moments_past_days_live OK')
