"""/threads on the situation card: groups, the next step as the primary
button, details that hold the old forms, the send box posting what is
typed, and nothing lost. Run from chauffeur/."""
import datetime
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='threads_page_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')
TODAY = datetime.date.today()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    from services import threads, mailer
    storage.update_settings({'llm_gemini_api_key': '', 'thread_stall_days': 7})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    threads.create('Deck permit with the county', owner_member_id='mom', next_action='call county',
                   next_action_at=(TODAY - datetime.timedelta(days=3)).isoformat(),
                   counterparty_name='County', counterparty_email='permits@county.gov', created_by='mom')
    tid = threads.create('Pool opening', owner_member_id='mom', kind='vendor', next_action='wait for the quote',
                         counterparty_name='Pool guy', created_by='mom')
    storage.update_thread(tid, {'state': 'waiting'})
    done = threads.create('Old fence quote', owner_member_id='mom', created_by='mom')
    threads.close(done, 'done', who='mom')
    # No key in a test: stand in for the model so the draft box opens with
    # Argyle's words, which the person then overwrites.
    threads._pool_call = lambda *a, **k: {'subject': 'Deck permit', 'body': 'ARGYLE DRAFT'}
    # The send box must post what is typed: stub the mailer to record it.
    mailer.configured = lambda settings: True
    sent = []
    mailer.send = lambda to, subject, body, settings=None: (sent.append((to, subject, body)) or {'sent': True, 'reason': None})
    mailer._test_sent = sent


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            # /work hosts the Mind lane too (hidden tab, its own cards): scope
            # the wait to the threads section.
            page.wait_for_selector('#threads .situation-card')
            groups = page.locator('#threads [data-sit-group]').all_inner_texts()
            groups = [g.lower() for g in groups]          # the headings render uppercase
            check(any('needs you now' in g for g in groups) and any('waiting on them' in g for g in groups),
                  f"groups by situation: {[g[:30] for g in groups]}")
            first = page.locator('[data-sit-group="now"] .situation-card').first
            check('Deck permit' in first.locator('.sit-title').inner_text(), "the overdue thread needs you now")
            check(first.locator('.sit-next button').first.inner_text().startswith('Set the next step'),
                  "the primary button is the next step")
            # Details hold the old forms; Advance from the card opens them.
            first.locator('.sit-next button').first.click()
            page.wait_for_selector('[data-sit-group="now"] details[open] input[placeholder="What has to happen next"]')
            page.fill('[data-sit-group="now"] details[open] input[placeholder="What has to happen next"]', 'email the inspector')
            # The note form's Save sits first in the markup, hidden; the advance form's is the visible one.
            page.locator('[data-sit-group="now"] details[open] button:has-text("Save"):visible').first.click()
            page.wait_for_timeout(800)
            row = [t for t in storage.get_threads(include_closed=True) if 'Deck permit' in t['title']][0]
            check(row['next_action'] == 'email the inspector', f"advance saved through the old form: {row['next_action']}")
            # The send box posts what is typed, never the draft.
            deck = page.locator('#threads .situation-card:has-text("Deck permit")').first
            # Once the next step is set, drafting may be the primary button or a quiet one.
            deck.locator('button:has-text("Draft a message")').first.click()
            page.wait_for_selector('details[open] textarea[placeholder="Body"]', timeout=15000)
            page.fill('details[open] textarea[placeholder="Body"]', 'TYPED BY A PERSON')
            page.fill('details[open] input[placeholder="Send to"]', 'permits@county.gov')
            page.locator('details[open] button:has-text("Send")').first.click()
            page.wait_for_timeout(300)
            page.locator('button:has-text("Send")').last.click()      # promptConfirm's Send
            page.wait_for_timeout(800)
            from services import mailer
            check(mailer._test_sent and mailer._test_sent[-1][2] == 'TYPED BY A PERSON',
                  f"send posted the box, got {mailer._test_sent}")
            # Nothing lost: Work this, Edit, Add note, Research still reachable.
            for label in ('Work this', 'Edit', 'Add note', 'Research'):
                check(page.locator(f'details button:has-text("{label}")').count() >= 1, f"{label} still has a home")
            # Closed group folded, with the done thread inside.
            check(page.locator('[data-sit-group="done"] .situation-card').count() == 0, "closed starts folded")
            page.locator('[data-sit-group="done"] button').first.click()
            page.wait_for_timeout(300)
            check('Old fence' in page.locator('[data-sit-group="done"]').inner_text(), "unfolded: the done thread")
            _shot(page, 'threads-page')
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print("test_threads_page_live OK")
