"""The settings drawer on the Work tabs, actually clicked (settings-drawer arc).

A drawer is a fixed overlay inside a page's Alpine island; whether it covers
the viewport, opens from the gear, saves, reports and closes is only true in
a layout engine. One file for the shell and the slice-1 pilots; later
slices add their own files.

Set CHF_SHOTS=<dir> to save the screenshots the arc requires.
Run from chauffeur/:  python tests/test_settings_drawer_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='settings_drawer_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

SHOTS = os.environ.get('CHF_SHOTS')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _visible(page, sel):
    return page.evaluate(
        "(s) => { const el = document.querySelector(s);"
        " return !!el && getComputedStyle(el).display !== 'none'; }", sel)


def _changed(before, after):
    return {k for k in set(before) | set(after) if before.get(k) != after.get(k)}


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'))


def seed():
    storage.update_settings({'llm_gemini_api_key': 'test-key', 'thread_stall_days': 7,
                             'mind_enabled': False, 'missions_enabled': False})
    storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            M = '[data-settings-for~="mind"]'
            page.goto(served.url('work?tab=mind'), wait_until='networkidle')
            # Rule 4: off says so in the work area, with a way back on.
            page.wait_for_selector('[data-page-tab="mind"] [data-settings-off]', state='visible')
            check(not _visible(page, M), 'the Mind drawer starts open')
            _shot(page, 'mind-closed-desktop')
            page.click('[data-page-tab="mind"] [data-settings-off] button')
            page.wait_for_selector(M + '[data-open]')
            _shot(page, 'mind-open-desktop')
            before = storage.get_settings()
            page.check(M + ' input[x-model="s.mind_enabled"]')
            page.wait_for_selector(M + ' [data-settings-status]:has-text("Saved")')
            check('mind_enabled' in _changed(before, storage.get_settings()), 'turning the Mind on did not save')
            page.click(M + ' [aria-label="Close settings"]')
            page.wait_for_timeout(150)
            check(not _visible(page, '[data-page-tab="mind"] [data-settings-off]'), 'the off line outlived the switch')
            # heads-ups deep link (was test_config_small_moves_live's path)
            page.goto(served.url('work?tab=threads#heads-ups'), wait_until='networkidle')
            page.wait_for_selector(M + '[data-open]')
            check(_visible(page, '#proactiveWatchersEnabled'), 'heads-ups is not reachable in the drawer')
            _shot(page, 'mind-headsups-desktop')
            page.click(M + ' [aria-label="Close settings"]')

            # Phone: the sheet, closed (off line) and open.
            page.set_viewport_size({'width': 390, 'height': 844})
            storage.update_settings({'mind_enabled': False})
            page.goto(served.url('work?tab=mind'), wait_until='networkidle')
            _shot(page, 'mind-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(M + '[data-open]')
            _shot(page, 'mind-open-phone')

            # Missions: seven controls in the drawer; the paid key is set / not set only.
            page.set_viewport_size({'width': 1300, 'height': 900})
            X = '[data-settings-for~="missions"]'
            page.goto(served.url('work?tab=missions'), wait_until='networkidle')
            page.wait_for_selector('[data-page-tab="missions"] [data-settings-off]', state='visible')
            _shot(page, 'missions-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(X + '[data-open]')
            check(page.inner_text(X + ' [data-paid-key-state]').strip() == 'Not set', 'key state is not Not set')
            page.fill('#llmGeminiPaidApiKey', 'paid-123')
            page.dispatch_event('#llmGeminiPaidApiKey', 'change')
            page.wait_for_selector(X + ' [data-settings-status]:has-text("Saved")')
            check(storage.get_settings().get('llm_gemini_paid_api_key') == 'paid-123', 'the paid key did not save')
            page.reload(wait_until='networkidle')
            page.click('#page-settings-gear')
            page.wait_for_selector(X + '[data-open]')
            check(page.input_value('#llmGeminiPaidApiKey') == '', 'the stored key is shown in the field')
            check(page.inner_text(X + ' [data-paid-key-state]').strip() == 'Set', 'key state is not Set')
            page.fill(X + ' input[x-model\\.number="s.mission_cap_launch"]', '4')
            page.dispatch_event(X + ' input[x-model\\.number="s.mission_cap_launch"]', 'change')
            page.wait_for_selector(X + ' [data-settings-status]:has-text("Saved")')
            check(storage.get_settings().get('llm_gemini_paid_api_key') == 'paid-123',
                  'saving another control wiped the paid key')
            check(storage.get_settings().get('mission_cap_launch') == 4, 'the launch cap did not save')
            _shot(page, 'missions-open-desktop')
            page.click(X + ' [aria-label="Close settings"]')

            # Intake: the mailbox in the drawer, saved as you go (no Save button).
            I = '[data-settings-for~="intake"]'
            page.goto(served.url('intake'), wait_until='networkidle')
            _shot(page, 'intake-closed-desktop')
            page.click('#page-settings-gear')
            page.wait_for_selector(I + '[data-open]')
            check(page.locator(I + ' button:has-text("Save Settings")').count() == 0, 'Intake still has a Save button')
            posts = []
            page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and r.url.endswith('/api/ingest/config') else None)
            host = I + ' input[x-model="config.ingest_email_host"]'
            page.click(host)
            page.keyboard.press('Control+A')
            page.keyboard.type('imap.example.com', delay=20)
            page.wait_for_timeout(300)
            check(not posts, f'typing saved per keystroke: {len(posts)} posts')
            page.click('#ingestDailyLimit')          # blur commits the host
            page.wait_for_selector(I + ' [data-settings-status]:has-text("Saved")')
            check(len(posts) == 1, f'one blur, {len(posts)} saves')
            check(storage.get_settings().get('ingest_email_host') == 'imap.example.com', 'the host did not save')
            _shot(page, 'intake-open-desktop')
            page.click(I + ' [aria-label="Close settings"]')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('intake'), wait_until='networkidle')
            _shot(page, 'intake-closed-phone')
            page.click('#page-settings-gear')
            page.wait_for_selector(I + '[data-open]')
            _shot(page, 'intake-open-phone')
            page.click(I + ' [aria-label="Close settings"]')

            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_settings_drawer_work_live OK')


if __name__ == '__main__':
    main()
