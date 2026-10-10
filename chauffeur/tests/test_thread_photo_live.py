"""The camera button on /threads and the PWA House card; the timeline shows
the thumbnail and the transcription. Browse missions build 1, Task 4."""
import base64
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='thread_photo_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    storage.update_settings({'llm_gemini_api_key': '', 'thread_stall_days': 7})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    from services import threads
    threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co', created_by='mom')
    open(os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'label.png'), 'wb').write(PNG)


def main():
    served = live_app(seed)
    if served is None:
        return
    png_path = os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'label.png')
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            page.wait_for_selector('#threads .situation-card', timeout=15000)
            page.locator('#threads details summary').first.click()
            page.wait_for_timeout(300)
            check(page.locator('#threads details[open] button:has-text("Photo")').count() == 1, "the Photo button is in the details")
            page.locator('#threads details[open] input[type=file][data-thread-photo]').first.set_input_files(png_path)
            page.wait_for_timeout(2500)
            row = [t for t in storage.get_threads() if t['title'] == 'Pest control'][0]
            photos = [h for h in row['history'] if h['kind'] == 'photo']
            check(len(photos) == 1 and photos[0]['text'] == 'photo added (not read)', f"stored through the page (no key: not read): {photos}")
            page.wait_for_selector('#threads details[open] img.thread-photo', timeout=10000)
            tl = page.locator('#threads details[open] .thread-photo-text').first.inner_text()
            check('not read' in tl, f"the timeline shows the photo line: {tl}")
            check(not b.errors, f"script errors: {b.errors}")

        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("localStorage.setItem('chauffeur_member_id', 'mom');")
            page.goto(served.url('app'), wait_until='networkidle')
            page.evaluate("async () => { await fetchHouseThreads(); }")
            page.wait_for_selector('#house-threads .situation-card', state='attached', timeout=15000)
            check(page.locator('#house-threads input[type=file][data-thread-photo]').count() == 1, "the House card has a camera input")
            page.locator('#house-threads input[type=file][data-thread-photo]').first.set_input_files(png_path)
            page.wait_for_timeout(2500)
            row = [t for t in storage.get_threads() if t['title'] == 'Pest control'][0]
            check(len([h for h in row['history'] if h['kind'] == 'photo']) == 2, "stored through the PWA too")
            check(not b.errors, f"PWA script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_thread_photo_live')
