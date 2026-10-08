"""Intake says why it is waiting, and the daily allowance is a real control.

Runs the actual page against the actual app: a stored wait (an AI failure
with a retry time) must draw the amber strip with its reason, the next-try
time and a Try now button; today's request count shows against the
allowance; and the allowance field saves through /api/ingest/config.

Run from chauffeur/:  python tests/test_intake_wait_live.py [--out DIR]
"""
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='intake_wait_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app

from services import storage

OUT = sys.argv[sys.argv.index('--out') + 1] if '--out' in sys.argv else None


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': 'test-key'})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    storage.set_app_state('ingest_wait', {'reason': 'gemma-4-31b-it: HTTP Error 500: Internal',
                                          'retry_at': time.time() + 240, 'since': time.time(),
                                          'cap': False})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('intake'), wait_until='networkidle')
            strip = page.locator('[data-intake-wait]')
            check(strip.is_visible(), 'the wait strip is not shown for a stored wait')
            text = strip.inner_text()
            check('HTTP Error 500' in text, f'the strip does not say why: {text!r}')
            check('tries again at' in text and 'nothing is skipped' in text,
                  f'the strip does not say when: {text!r}')
            check(strip.get_by_role('button', name='Try now').is_visible(), 'no Try now button')
            usage = page.locator('[data-intake-usage]').inner_text()
            check('0 of 500' in usage, f'usage line wrong: {usage!r}')
            if OUT:
                os.makedirs(OUT, exist_ok=True)
                page.screenshot(path=os.path.join(OUT, 'intake-wait.png'))

            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="intake"][data-open]')
            page.fill('#ingestDailyLimit', '120')
            page.dispatch_event('#ingestDailyLimit', 'change')
            page.wait_for_selector('[data-settings-for~="intake"] [data-settings-status]:has-text("Saved")')
            check(storage.get_settings().get('ingest_daily_limit') == 120,
                  f"the allowance did not save: {storage.get_settings().get('ingest_daily_limit')}")
            check('0 of 120' in page.locator('[data-intake-usage]').inner_text(),
                  'the usage line did not pick up the new allowance')
            if OUT:
                page.locator('#ingest-daily-limit').screenshot(path=os.path.join(OUT, 'intake-limit.png'))
            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_intake_wait_live OK')


if __name__ == '__main__':
    main()
