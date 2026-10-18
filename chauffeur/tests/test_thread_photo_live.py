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
    tid = threads.create('Pest control', owner_member_id='mom', counterparty_name='Pest Co', created_by='mom')
    legacy = storage.save_photo_bytes(PNG, 'image/png')
    storage.append_thread_history(tid, {'kind': 'photo', 'media_id': legacy['id'], 'url': legacy['url'],
                                       'text': 'legacy photo', 'who': 'mom'})
    open(os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'label.png'), 'wb').write(PNG)


def _open_record(page, served, title):
    row = next(r for r in storage.get_threads(include_closed=True) if r['title'] == title)
    page.goto(served.url('threads?id=' + row['id']), wait_until='networkidle')
    page.wait_for_selector('[data-record-sheet][data-open="true"][data-kind="thread"] details[open]', timeout=15000)


def _photos_load(page, selector, count):
    page.wait_for_function('''({selector, count}) => {
        const photos = [...document.querySelectorAll(selector)];
        return photos.length === count && photos.every(img => img.complete && img.naturalWidth > 0);
    }''', arg={'selector': selector, 'count': count}, timeout=10000)
    sources = page.locator(selector).evaluate_all('(imgs) => imgs.map(img => img.src)')
    check(any('thread_id=' in src for src in sources), f'a new photo uses its thread URL: {sources}')
    check(any('thread_id=' not in src for src in sources), f'a legacy photo uses the media URL: {sources}')


def main():
    served = live_app(seed)
    if served is None:
        return
    png_path = os.path.join(os.environ['CHAUFFEUR_DATA_DIR'], 'label.png')
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            _open_record(page, served, 'Pest control')
            page.wait_for_selector('[data-record-sheet][data-kind=thread] .situation-card', timeout=15000)
            page.wait_for_selector('[data-record-sheet][data-kind=thread] details[open]')
            page.wait_for_timeout(300)
            check(page.locator('[data-record-sheet][data-kind=thread] details[open] button:has-text("Photo")').count() == 1, "the Photo button is in the details")
            page.locator('[data-record-sheet][data-kind=thread] details[open] input[type=file][data-thread-photo]').first.set_input_files(png_path)
            page.wait_for_timeout(2500)
            row = [t for t in storage.get_threads() if t['title'] == 'Pest control'][0]
            photos = [h for h in row['history'] if h['kind'] == 'photo']
            check(len(photos) == 2 and photos[-1]['text'] == 'photo added (not read)', f"stored through the page (no key: not read): {photos}")
            page.wait_for_selector('[data-record-sheet][data-kind=thread] details[open] img.thread-photo', timeout=10000)
            _photos_load(page, '[data-record-sheet][data-kind=thread] details[open] img.thread-photo', 2)
            tl = page.locator('[data-record-sheet][data-kind=thread] details[open] .thread-photo-text').last.inner_text()
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
            check(len([h for h in row['history'] if h['kind'] == 'photo']) == 3, "stored through the PWA too")
            page.evaluate('(id) => openPieceSheet({kind: "thread", id, title: "Pest control"})', row['id'])
            _photos_load(page, '[data-piece-sheet] img.thread-photo', 3)
            check(not b.errors, f"PWA script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_thread_photo_live')
