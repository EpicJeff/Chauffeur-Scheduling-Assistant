"""Nothing ever sits under the Argyle bar. The bar is fixed over the bottom of
every admin page, so the page must end above it: with twelve threads on
/work?tab=threads, scrolled to the end, the last card's Delete button sits
wholly above the bar; the same on the standalone /threads page; and with
?chat=none there is no bar and no floor."""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='argyle_floor_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    from services import threads
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    for i in range(12):
        threads.create(f'Loop number {i + 1}', owner_member_id='mom', goal=f'close loop {i + 1}', created_by='mom')


def _last_delete_clears_the_bar(page, scroller_js):
    """Open the LAST card's details (a closed <details> keeps its layout boxes
    in Chrome but paints nothing, so Delete must be opened to be measured),
    scroll the page's scroller to its end, and the Delete row and the whole
    section must end above the bar."""
    root = 'body > .overflow-y-auto'          # the page's scroller, on /work and on /threads alike
    page.wait_for_selector(f'{root} details summary', state='attached', timeout=15000)
    summaries = page.locator(f'{root} details summary')
    n = summaries.count()
    check(n >= 12, f"twelve threads drawn: {n}")
    summaries.nth(n - 1).scroll_into_view_if_needed()
    summaries.nth(n - 1).click()
    page.wait_for_timeout(500)
    page.evaluate(scroller_js)
    page.wait_for_timeout(300)
    deletes = page.locator(f'{root} details[open] button:has-text("Delete")')
    check(deletes.count() >= 1, "the opened details shows its Delete")
    last = deletes.nth(deletes.count() - 1)
    box = last.bounding_box()
    bar = page.locator('#chat-overlay-container').bounding_box()
    sec = page.locator(f'{root} > *').first.bounding_box()      # the scroller's content, whole
    floor = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--argyle-floor')")
    check(box and bar and sec, f"all drawn: {box} {bar} {sec}")
    check(box['y'] + box['height'] <= bar['y'], f"the last Delete sits above the bar: delete bottom {box['y'] + box['height']:.0f}, bar top {bar['y']:.0f}, floor {floor!r}")
    check(sec['y'] + sec['height'] <= bar['y'], f"the whole section ends above the bar: section bottom {sec['y'] + sec['height']:.0f}, bar top {bar['y']:.0f}")
    return floor


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 700})
            page.goto(served.url('work?tab=threads'), wait_until='networkidle')
            floor = _last_delete_clears_the_bar(page, "() => { const s = document.querySelector('body > .overflow-y-auto'); if (s) s.scrollTop = s.scrollHeight; }")
            check(floor.strip().endswith('px') and int(floor.strip()[:-2]) > 60, f"the floor is measured from the bar: {floor!r}")
            page.goto(served.url('threads'), wait_until='networkidle')
            _last_delete_clears_the_bar(page, "() => { const s = document.querySelector('body > .overflow-y-auto'); if (s) s.scrollTop = s.scrollHeight; }")
            page.goto(served.url('work?tab=threads&chat=none'), wait_until='networkidle')
            page.wait_for_selector('body > .overflow-y-auto details summary', state='attached', timeout=15000)
            pad = page.evaluate("getComputedStyle(document.querySelector('body > .overflow-y-auto')).paddingBottom")
            check(pad == '0px' and page.evaluate("document.body.classList.contains('chat-none')"), f"chat=none: no bar, no floor: {pad}")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_argyle_floor_live')
