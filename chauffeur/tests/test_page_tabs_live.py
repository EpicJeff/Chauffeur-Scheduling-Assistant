"""Page groups, actually clicked (v2.499.247).

The admin pages that carried several unrelated things side by side (Work,
Rhythms, Errands) became tab groups: one nav entry, a strip of tabs under the
bar, one view at a time. Which block is visible is decided by a stylesheet the
strip writes, so the only honest test is a real layout engine — a source pin
can confirm the markup and still miss a page that renders blank.

Run from chauffeur/:  python tests/test_page_tabs_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='page_tabs_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from live_app import live_app


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _visible(page, sel):
    return page.evaluate(
        "(s) => { const el = document.querySelector(s);"
        " return !!el && getComputedStyle(el).display !== 'none'; }", sel)


def main():
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_viewport_size({'width': 1400, 'height': 900})

        # Work opens on Mind; the other two organs are out of sight.
        page.goto(served.url('work'), wait_until='domcontentloaded')
        check(_visible(page, '#page-tabs'), 'the Work page has no tab strip')
        check(_visible(page, '[data-page-tab="mind"]'), 'Mind is not the default view')
        check(not _visible(page, '[data-page-tab="threads"]'), 'Threads shows beside Mind')

        # A click switches in place and the address keeps the tab.
        page.click('#page-tabs [data-tab-key="threads"]')
        page.wait_for_timeout(200)
        check(_visible(page, '[data-page-tab="threads"]'), 'clicking Threads did not show it')
        check(not _visible(page, '[data-page-tab="mind"]'), 'Mind still shows after Threads')
        check('tab=threads' in page.url, f'the URL forgot the tab: {page.url}')
        # ...and the tab param never leaks onto a link to another page.
        intake = page.get_attribute('#page-tabs [data-tab-key="intake"]', 'href')
        check('tab=' not in intake, f'Intake link carries a tab: {intake}')

        # A reload with the tab opens straight onto it.
        page.goto(served.url('rhythms?tab=programs'), wait_until='domcontentloaded')
        check(_visible(page, '[data-page-tab="programs"]'), 'rhythms?tab=programs did not open Programs')
        check(not _visible(page, '[data-page-tab="routines"]'), 'Routines shows beside Programs')
        chores = page.get_attribute('#page-tabs [data-tab-key="chores"]', 'href')
        check(chores.endswith('chores'), f'the Chores tab is not a link to /chores: {chores}')

        # Errands defaults to errands; Tasks is one click away.
        page.goto(served.url('errands'), wait_until='domcontentloaded')
        check(_visible(page, '[data-page-tab="errands"]'), 'Errands is not the default view')
        check(not _visible(page, '[data-page-tab="tasks"]'), 'Tasks shows beside Errands')
        page.click('#page-tabs [data-tab-key="tasks"]')
        page.wait_for_timeout(200)
        check(_visible(page, '#new-task-title'), 'the Tasks tab does not show the task input')

        # A panel keeps its own navigation and sees every block.
        page.goto(served.url('work?panel=true'), wait_until='domcontentloaded')
        check(page.query_selector('#page-tabs') is None, 'a panel draws the tab strip')
        check(_visible(page, '[data-page-tab="threads"]'), 'a panel lost a Work block')

        check(not errors, f'page errors: {errors[:3]}')
    print('test_page_tabs_live OK')


if __name__ == '__main__':
    main()
