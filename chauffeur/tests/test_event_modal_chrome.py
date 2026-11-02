"""The schedule page's event dialog is chrome: fixed title and close, fixed
actions, a body that scrolls, and a second column for rules and diagnostics on
a landscape browser (2026-11-02).

Device report with a screenshot: with solver diagnostics the dialog grew past
the screen; its close button sat under the sticky sub nav (added later, at
z-[60] against the dialog's z-50) and scrolled away with the content; the
action buttons needed a scroll to reach; and the bottom fell under the Argyle
dock (z-[80]). A second report the same minute: the Drives settings drawer's
rule chips drew over the drawer's title when scrolled, because the chip rows
and the drawer's sticky header were both z-10 and the later node wins.

The live half serves the app and opens the dialog with eight diagnostic cards
at a laptop viewport: the close button and every footer button must be the
thing under the pointer (nothing above them), only the body may scroll, and at
`lg` the diagnostics sit beside the details, below them on a narrow screen.
Skips without playwright, like every live test.

Run from chauffeur/:  python tests/test_event_modal_chrome.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness import check  # noqa: E402  (isolates CHAUFFEUR_DATA_DIR)
from live_app import live_app  # noqa: E402
from services import storage  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(ROOT, 'templates')
SHOTS = os.path.join(ROOT, 'probe_shots')


def scenario_the_markup():
    page = open(os.path.join(TPL, 'dashboard.html'), encoding='utf-8').read()
    i = page.index('id="event-modal"')
    shell = page[i:i + 400]
    check('z-[90]' in shell and 'z-50' not in shell, "the dialog sits above the sticky nav (z-[60]) and the Argyle dock (z-[80])")
    check('id="event-modal-panel"' in page and 'flex flex-col overflow-hidden' in page[i:i + 700],
          "the panel is a column that never scrolls itself")
    check('id="modal-view-body" class="flex-1 min-h-0 overflow-y-auto' in page, "only the body scrolls")
    check('id="event-modal-close"' in page and page.index('id="event-modal-close"') < page.index('id="modal-view-body"'),
          "the close button is in the header, above the scrolling body")
    check('id="modal-view-footer" class="shrink-0' in page and page.index('id="modal-view-footer"') > page.index('id="deal-result"'),
          "the actions are a fixed footer after the body")
    check('id="modal-side"' in page and 'function setModalSide' in page and "'lg:grid-cols-2'" in page,
          "rules and diagnostics are a second column on a landscape browser")
    check('id="modal-edit-mode" class="hidden flex-col min-h-0"' in page and page.count('onclick="closeEventModal()"') >= 2,
          "edit mode has the same chrome, with its own close")
    rules = open(os.path.join(TPL, 'components', 'drive_rules.html'), encoding='utf-8').read()
    check('flex flex-col z-10"' not in rules, "a rule's matched-event chip carries no z-index of its own")
    drawer = open(os.path.join(TPL, 'components', 'settings_drawer.html'), encoding='utf-8').read()
    check('sticky top-0 z-20 bg-gray-800' in drawer, "the drawer's sticky header paints over everything it scrolls")


CARDS = ''.join(
    f'<div class="bg-gray-900 border border-yellow-900 p-4 rounded-lg"><div class="font-bold text-blue-300">Driver {i}</div>'
    f'<div class="text-gray-300">Passenger cannot travel from/to \'Practice\' in time.</div></div>' for i in range(8))

SETUP = """() => {
    const g = id => document.getElementById(id);
    g('view-title').textContent = 'Fall/Winter Girls Resurrection – 11 & Under Training';
    g('diagnostics-list').innerHTML = %s;
    g('diagnostics-section').classList.remove('hidden');
    g('tab-content-diagnostics').classList.remove('hidden');
    g('modal-tabs').classList.remove('hidden');
    setModalSide(true);
    g('event-modal').classList.remove('hidden');
    return true;
}""" % repr(CARDS)

PROBE = """() => {
    const g = id => document.getElementById(id);
    const r = el => { const b = el.getBoundingClientRect(); return {top: b.top, bottom: b.bottom, left: b.left, right: b.right}; };
    const under = el => { const b = el.getBoundingClientRect();
        const hit = document.elementFromPoint((b.left + b.right) / 2, (b.top + b.bottom) / 2);
        return !!hit && (hit === el || el.contains(hit)); };
    const body = g('modal-view-body'), panel = g('event-modal-panel');
    return {
        h: window.innerHeight, w: window.innerWidth,
        close: r(g('event-modal-close')), closeHit: under(g('event-modal-close')),
        edit: r(g('edit-details-btn')), editHit: under(g('edit-details-btn')),
        cancel: r(g('cancel-event-btn')), cancelHit: under(g('cancel-event-btn')),
        bodyScrolls: body.scrollHeight > body.clientHeight,
        sideScrolls: g('modal-side').scrollHeight > g('modal-side').clientHeight,
        panelScrolls: panel.scrollHeight > panel.clientHeight + 1,
        main: r(g('modal-main')), side: r(g('modal-side')),
    };
}"""


def scenario_live():
    def seed():
        storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'color_code': '#6366f1'})
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser(color_scheme='dark')
        with handle as page:
            page.set_viewport_size({'width': 1440, 'height': 800})
            # The schedule page keeps a stream open, so 'networkidle' never comes.
            page.goto(served.url('dashboard_v2'), wait_until='domcontentloaded')
            page.wait_for_selector('#event-modal', state='attached')
            page.wait_for_function("() => typeof setModalSide === 'function'")
            page.evaluate(SETUP)
            p = page.evaluate(PROBE)
            check(0 <= p['close']['top'] and p['close']['bottom'] <= p['h'] and p['closeHit'],
                  f"the close button is on screen and nothing covers it: {p['close']} hit={p['closeHit']}")
            check(p['edit']['bottom'] <= p['h'] and p['editHit'] and p['cancelHit'],
                  f"the action buttons are on screen without scrolling and nothing covers them: {p['edit']}")
            check(not p['panelScrolls'], f"the panel never scrolls: {p}")
            check(p['side']['left'] >= p['main']['right'] - 1,
                  f"at a laptop width the diagnostics sit beside the details: main={p['main']} side={p['side']}")
            check(p['sideScrolls'] and not p['bodyScrolls'],
                  f"at a laptop width the diagnostics column scrolls on its own, the details stay put: {p}")
            os.makedirs(SHOTS, exist_ok=True)
            page.screenshot(path=os.path.join(SHOTS, 'event_modal_diagnostics_landscape.png'))
            page.evaluate("() => { document.getElementById('modal-side').scrollTop = 400; }")
            p2 = page.evaluate(PROBE)
            check(p2['close'] == p['close'] and p2['edit'] == p['edit'] and p2['main'] == p['main'],
                  "scrolling the diagnostics moves neither the chrome nor the details")
            page.set_viewport_size({'width': 820, 'height': 1100})
            p3 = page.evaluate(PROBE)
            check(p3['side']['left'] < p3['main']['right'] - 1,
                  f"on a narrow screen the diagnostics go below the details: main={p3['main']} side={p3['side']}")
            check(p3['bodyScrolls'] and not p3['panelScrolls'], f"on a narrow screen the body scrolls as one: {p3}")
            check(p3['closeHit'] and p3['editHit'], "the chrome holds on a narrow screen too")
            page.screenshot(path=os.path.join(SHOTS, 'event_modal_diagnostics_portrait.png'))
            page.click('#event-modal-close')
            check(page.evaluate("() => document.getElementById('event-modal').classList.contains('hidden')"),
                  "the close button closes the dialog")
        # A signed-out page's 401 on a parents-only fetch is the auth tier working, not a page error.
        errs = [e for e in handle.errors if 'favicon' not in str(e) and '401' not in str(e)]
        check(not errs, f"no page errors: {errs}")
    finally:
        served.stop()


if __name__ == '__main__':
    scenario_the_markup()
    print('  ok  scenario_the_markup')
    scenario_live()
    print('  ok  scenario_live')
    print('event-modal chrome scenarios passed')
