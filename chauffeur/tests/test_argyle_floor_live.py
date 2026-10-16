"""Nothing ever sits under the Argyle bar. The bar is fixed over the bottom of
every admin page, so the page must end above it: with twelve wrapped threads
on Projects, scrolled to the end, the last project card sits wholly above
the bar; the same after an old /threads bookmark redirects; and with
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


def _last_project_clears_the_bar(page, scroller_js):
    """Scroll the overview to its end; its last card and whole section must
    end above the bar, including when reached through a retired bookmark."""
    root = 'body > .overflow-y-auto'
    page.wait_for_selector(f'{root} [data-project-id]', state='visible', timeout=15000)
    cards = page.locator(f'{root} [data-project-card]:visible')
    n = cards.count()
    check(n >= 12, f"twelve wrapped threads drawn: {n}")
    cards.nth(n - 1).scroll_into_view_if_needed()
    page.evaluate(scroller_js)
    page.wait_for_timeout(300)
    last = cards.nth(n - 1)
    check(last.locator('[data-project-id]').count() == 1, "the last card opens its project")
    box = last.bounding_box()
    bar = page.locator('#chat-overlay-container').bounding_box()
    sec = page.locator(f'{root} > *').first.bounding_box()      # the scroller's content, whole
    floor = page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--argyle-floor')")
    check(box and bar and sec, f"all drawn: {box} {bar} {sec}")
    check(box['y'] + box['height'] <= bar['y'], f"the last card sits above the bar: card bottom {box['y'] + box['height']:.0f}, bar top {bar['y']:.0f}, floor {floor!r}")
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
            check('tab=projects' in page.url, "the old Work tab redirects to Projects")
            floor = _last_project_clears_the_bar(page, "() => { const s = document.querySelector('body > .overflow-y-auto'); if (s) s.scrollTop = s.scrollHeight; }")
            check(floor.strip().endswith('px') and int(floor.strip()[:-2]) > 60, f"the floor is measured from the bar: {floor!r}")
            page.goto(served.url('threads'), wait_until='networkidle')
            check(page.url.split('?')[0].endswith('/projects'), "the old Threads bookmark redirects to Projects")
            _last_project_clears_the_bar(page, "() => { const s = document.querySelector('body > .overflow-y-auto'); if (s) s.scrollTop = s.scrollHeight; }")
            page.goto(served.url('work?tab=projects&chat=none'), wait_until='networkidle')
            page.wait_for_selector('body > .overflow-y-auto [data-project-id]', state='visible', timeout=15000)
            pad = page.evaluate("getComputedStyle(document.querySelector('body > .overflow-y-auto')).paddingBottom")
            check(pad == '0px' and page.evaluate("document.body.classList.contains('chat-none')"), f"chat=none: no bar, no floor: {pad}")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_argyle_floor_live')
