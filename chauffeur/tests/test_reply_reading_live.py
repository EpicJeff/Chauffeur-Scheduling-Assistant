"""The reading line and 'Argyle got it wrong' on /threads, and the timeline
shows what Argyle read beside the reply. Run from chauffeur/."""
import datetime
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='reply_reading_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'thread_stall_days': 7})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    from services import threads, mailer, replies, asks
    mailer.send = lambda to, subject, body, settings=None: {'sent': True}
    mailer.configured = lambda *a, **k: True
    replies._post = lambda *a, **k: {'id': 'x'}
    tid = threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co',
                         counterparty_email='ops@pestco.example', created_by='mom')
    res = threads.send_drafted(tid, 'Can you come Friday?', 'B', 'ops@pestco.example', who='mom', intent='come Friday morning')
    threads.match_inbound('ops@pestco.example', 'Re: Can you come Friday?', 'Friday at 9 works.', message_id='<m1>')
    # No key in a test: stand in for the reading the poll would have made.
    asks.record_reading(res['ask_id'], 'yes', '<m1>', summary='Friday 9am works')
    storage.update_thread_history_entry(tid, {'message_id': '<m1>'},
                                        {'reading': {'answer': 'yes', 'summary': 'Friday 9am works', 'ts': time.time(), 'source': 'argyle'}})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('#threads .situation-card', timeout=15000)
            card = page.locator('#threads .situation-card:has-text("Pest control")').first
            line = card.locator('[data-ask-line]').first.inner_text()
            check('Argyle read their reply as yes' in line and 'Friday 9am works' in line, f"the reading line: {line}")
            check(card.locator('button:has-text("Argyle got it wrong")').count() == 1, "the revert button is on the card")
            check(card.locator('.sit-next button').first.inner_text().startswith('Confirm with Pest Co'),
                  "the next step is the confirm")
            # The timeline, under the card's details, shows what Argyle read.
            page.locator('#threads details summary').first.click()
            page.wait_for_timeout(400)
            # Every entry carries the span; only the reply's is shown.
            tl = ' '.join(page.locator('#threads details[open] .thread-reading:visible').all_inner_texts())
            check('yes' in tl and 'Friday 9am works' in tl, f"the timeline shows the reading: {tl}")
            card.locator('button:has-text("Argyle got it wrong")').first.click()
            page.wait_for_timeout(1500)
            card = page.locator('#threads .situation-card:has-text("Pest control")').first
            line = card.locator('[data-ask-line]').first.inner_text()
            check('waiting' in line and 'Argyle read' not in line, f"after the tap, waiting again: {line}")
            check(card.locator('.sit-next button').first.inner_text().startswith('Read their reply'), "next step: read it")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_reply_reading_live')
