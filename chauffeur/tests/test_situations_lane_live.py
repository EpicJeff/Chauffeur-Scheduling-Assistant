"""The Needs-you lane, actually drawn: one builder on /mind and the PWA
Family tab, the primary button is the next step, a finding gets its first
hand path, the wall tile is read-only. Set CHF_SHOTS=<dir> for screenshots.
Run from chauffeur/:  python tests/test_situations_lane_live.py
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='situations_lane_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')
NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'mind_enabled': True})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    storage.add_driver({'id': 'mom', 'name': 'Mom', 'color_code': '#6366f1'})
    start = (NOON + datetime.timedelta(days=2)).replace(hour=16)
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat(),
                                             'end': start.isoformat()}], 'assignments': {}, 'unassigned': ['ev1']})
    storage.add_finding({'identity': 'unassigned:ev1', 'kind': 'unassigned', 'severity': 'approve',
                         'line': '🚨 No driver yet: Soccer', 'subject_type': 'event', 'subject_id': 'ev1',
                         'due_at': start.timestamp(), 'state': 'open', 'fingerprint': f"ev1|{start.timestamp()}"})
    storage.add_mind_insight({'slug': 'q', 'line': 'A quiet week for Kate', 'category': 'c', 'approach': 'ask Kate about Thursday',
                              'identity': 'c:1', 'refs': ['kate'], 'confidence': 0.8})
    storage.add_mind_insight({'slug': 's', 'line': 'SECRET', 'category': 'c', 'approach': 'x', 'identity': 'c:2',
                              'refs': ['kate'], 'sensitivity': 'sensitive'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=mind'), wait_until='networkidle')
            page.wait_for_selector('.situation-card')
            cards = page.locator('.situation-card')
            check(cards.count() == 3, f"/mind draws the parent's full lane, got {cards.count()}")
            first = cards.first
            check('Soccer' in first.locator('.sit-title').inner_text(), "the decide finding ranks first")
            nxt = first.locator('.sit-next button').first.inner_text()
            check(nxt.startswith('Assign'), f"the primary button is the next step, got {nxt!r}")
            check(first.locator('.sit-note[data-source="fallback"]').count() == 1, "no key: the fallback note is marked")
            _shot(page, 'mind-lane')
            first.locator('.sit-options button:has-text("Dismiss")').click()
            page.wait_for_timeout(800)
            check(page.locator('.situation-card').count() == 2, "a finding can be dismissed from a screen now")
            check(not b.errors, f"/mind script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('app'), wait_until='networkidle')
            # Signed in as the parent, the way the other PWA live tests do it.
            # (Sensitivity filtering by viewer is pinned by
            # test_situation_endpoints; a local-origin session is a trusted
            # place, so it cannot be exercised through this browser.)
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'mom');")
            page.goto(served.url('app'), wait_until='networkidle')
            # The Family pane that hosts #mind-content only exists after a
            # full solve (see test_leave_times_live for that machinery). The
            # wiring under test is the PWA's own fetch + the shared builder +
            # role gating, so give fetchMind() its container and call it.
            page.evaluate("() => { document.body.insertAdjacentHTML('beforeend', '<div id=\"mind-content\"></div>'); }")
            page.evaluate("async () => { await fetchMind(); }")
            page.wait_for_selector('#mind-content .situation-card', timeout=15000)
            titles = page.locator('#mind-content .situation-card .sit-title').all_inner_texts()
            # The Soccer finding was dismissed on /mind above (same server);
            # the parent sees both insights, sensitive included.
            check(titles == ['A quiet week for Kate', 'SECRET'],
                  f"the PWA Family tab draws the same lane for the parent: {titles}")
            nxt = page.locator('#mind-content .sit-next button').first.inner_text()
            check(nxt.startswith('Plan:'), f"an insight leads with its plan step, got {nxt!r}")
            _shot(page, 'pwa-lane')
            # The House tab's threads: the same builder, the parent's own
            # threads, the note form riding inside the card. (The thread is
            # opened here, after the lane counts above, which it would join.)
            from services import threads
            threads.create('Deck permit', owner_member_id='mom', next_action='call county', created_by='mom')
            # #house-threads is the real House tab container (not shown until
            # that tab is picked), so the cards are checked attached, not visible.
            page.evaluate("async () => { await fetchHouseThreads(); }")
            page.wait_for_selector('#house-threads .situation-card', state='attached', timeout=15000)
            check('Deck permit' in page.locator('#house-threads .sit-title').first.text_content(), "the House tab draws the parent's thread as a card")
            check(page.locator('#house-threads form input[id^="house-thread-note-"]').count() == 1, "the note form rides inside the card")
            check(not b.errors, f"PWA script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1920, 'height': 1080})
            page.goto(served.url('home?panel=true'), wait_until='networkidle')
            page.wait_for_timeout(1500)
            hit = page.locator('text=A quiet week for Kate')
            if hit.count():
                body = page.evaluate("() => document.body.innerText")
                check('SECRET' not in body, "the tile is identity-free")
                tile = hit.first.locator('xpath=ancestor::*[contains(@class, \"tile\")][1]')
                if tile.count():
                    check(tile.locator('button').count() == 0, "the wall tile is read-only")
                _shot(page, 'wall-tile')
            check(not b.errors, f"wall script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_situations_lane_live OK")
