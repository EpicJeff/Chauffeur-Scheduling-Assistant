"""The 3D house on the wall panel (?panel=true&kiosk=true), in real Chromium:
Argyle stays reachable and attention is never lost to a floor change.

The house, the fake Home Assistant, the panel session and the camera are
tests/house_twin_live_harness.py's (read its docstring first).

What the page must give:
- Argyle on the twin wall. The orb (#panel-chat-orb, components/control_center.html)
  is the only way into Argyle on a panel (voice-acts-panel-talk arc, v2.499.777).
  Tapping it opens #chat-overlay-container: the chat box is drawn (not display:none,
  not visibility:hidden, not transparent), the text box takes the focus, and when the
  panel's room has a satellite (GET api/panel/talk says available) the mic button
  #chat-talk-btn is in the box and can be pressed. The wall still shows no top nav
  and no editing link.
- Attention on every level (twin design 5.1: attention states push through at every
  level). An unlocked lock on a floor the person is not looking at stays drawn: its
  marker sprite is shown while every calm marker of that floor is hidden, and the
  floor picker's button for its floor carries data-attention. Once the lock is locked
  again the marker goes back with its floor and the button loses data-attention.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_house_twin_wall_live.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import house_twin_live_harness as L  # noqa: E402

check = L.check
FAKE = L.FAKE
WALL = 'tier=low&test=1&panel=true&kiosk=true'

DRAWN_JS = """(sel) => {
    const node = document.querySelector(sel);
    if (!node) return null;
    const s = getComputedStyle(node), r = node.getBoundingClientRect();
    let opacity = 1;
    for (let p = node; p && p.nodeType === 1; p = p.parentElement) opacity *= Number(getComputedStyle(p).opacity);
    return {display: s.display, visibility: s.visibility, opacity, width: r.width, height: r.height,
            hidden: node.classList.contains('hidden'), x: r.left + r.width / 2, y: r.top + r.height / 2};
}"""


def _drawn(page, sel):
    d = page.evaluate(DRAWN_JS, sel)
    return bool(d) and d['display'] != 'none' and d['visibility'] != 'hidden' and d['opacity'] > 0.5 \
        and d['width'] > 0 and d['height'] > 0, d


def _talk_available(page):
    """The panel's room has a satellite: api/panel/talk says so (the route itself is
    tests/test_panel_talk.py's)."""
    def handle(route):
        if route.request.method == 'GET':
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'available': True, 'state': 'idle'}))
        else:
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'ok': True}))
    page.route('**/api/panel/talk', handle)


def scenario_orb_opens_argyle_on_the_twin_wall():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    with s.browser(launch_args=L.GPU_ARGS) as page:
        _talk_available(page)
        L.open_twin(page, s, query=WALL)
        check(page.evaluate("() => document.documentElement.hasAttribute('data-twin-wall')"), 'this is the wall view')
        orb = page.locator('#panel-chat-orb')
        check(orb.count() == 1, 'the wall has the Argyle orb')
        ok, d = _drawn(page, '#panel-chat-orb')
        check(ok, ('the orb is drawn on the twin wall', d))
        ok, d = _drawn(page, '#chat-overlay-container')
        check(not ok, ('before a tap the chat box is collapsed into the orb', d))

        orb.click()
        page.wait_for_timeout(600)
        ok, d = _drawn(page, '#chat-overlay-container')
        check(ok, ('tapping the orb opens Argyle\'s chat box on the twin wall', d))
        ok, d = _drawn(page, '#chat-input')
        check(ok, ('the chat box\'s text box is drawn', d))
        check(page.evaluate("() => document.activeElement && document.activeElement.id") == 'chat-input',
              'the text box takes the focus')
        check(L.wait_for(page, lambda: _drawn(page, '#chat-talk-btn')[0], 6),
              ('tap-to-talk is reachable: the mic button is in the open chat box', _drawn(page, '#chat-talk-btn')[1]))
        mic = page.evaluate(DRAWN_JS, '#chat-talk-btn')
        hit = page.evaluate("([x, y]) => { const n = document.elementFromPoint(x, y); "
                            "return n && (n.id === 'chat-talk-btn' || !!n.closest('#chat-talk-btn')); }",
                            [mic['x'], mic['y']])
        check(hit, ('nothing covers the mic button', mic))

        # The wall stays a wall: no top nav, no editing link.
        ok, d = _drawn(page, '#top-nav-bar')
        check(not ok, ('the top nav stays hidden on the wall', d))
        check(page.locator('#twin-edit').count() == 0, 'no Edit the house link on the wall')

        # Escape closes it back into the orb.
        page.keyboard.press('Escape')
        page.wait_for_timeout(600)
        check(not _drawn(page, '#chat-overlay-container')[0], 'Escape collapses the chat box')
        check(_drawn(page, '#panel-chat-orb')[0], 'and the orb is back')
        L.no_errors(s)


SHOWN_JS = """() => {
    const v = window.__twin;
    return Object.fromEntries(Object.entries(v.groups.levels).map(([k, g]) => [k, g.visible]));
}"""


def _other_floor(page):
    """A floor of another building: picking it hides the pool house's ground floor."""
    levels = page.evaluate('() => Object.keys(window.__twin.groups.levels)')
    others = [k for k in levels if not k.startswith(L.POOL + ':')]
    check(others, ('the seeded place has a building besides the pool house', levels))
    return others[0]


def scenario_attention_on_a_hidden_floor_still_shows():
    s = L.serve()
    if s is None:
        return
    L.reset()
    L.facts()
    FAKE.states['lock.back_door']['state'] = 'unlocked'
    with s.browser(launch_args=L.GPU_ARGS) as page:
        L.open_twin(page, s, query=WALL)
        L.wait_look(page, 'dev-back-lock', 'attention')
        other = _other_floor(page)
        floor = page.locator(f'[data-view="{other}"]').locator('visible=true')
        check(floor.count() == 1, ('the wall\'s floor picker offers the other floor', other))
        floor.first.click()
        L.H.settle(page, 3)
        check(page.evaluate('() => window.__twin.state.view') == other, 'the floor control picks the other floor')
        shown = page.evaluate(SHOWN_JS)
        check(shown.get(L.FLOOR) is False, ('the pool house\'s floor is hidden now', shown))
        L.refresh(page)

        lock = L.sprite(page, 'dev-back-lock')
        check(lock['visible'], ('an unlocked lock on a hidden floor still shows its marker', lock))
        check(L.drawn_full(lock), ('drawn at full strength', lock))
        for calm in ('dev-k-lamp', 'dev-k-coffee', 'dev-hall-light'):
            row = L.sprite(page, calm)
            check(not row['visible'], ('a calm marker on the hidden floor stays hidden', calm, row))
        flagged = page.evaluate("() => [...document.querySelectorAll('#twin-views [data-attention]')].map(b => b.dataset.view)")
        check(L.FLOOR in flagged, ('the floor picker flags the floor that holds the unlocked lock', flagged))
        check(other not in flagged, ('a floor with nothing wanting attention is not flagged', flagged))

        # Locked again: the marker goes back with its floor and the flag clears.
        FAKE.states['lock.back_door']['state'] = 'locked'
        L.refresh(page)
        L.wait_look(page, 'dev-back-lock', 'off')
        lock = L.sprite(page, 'dev-back-lock')
        check(not lock['visible'], ('a locked lock on a hidden floor hides with its floor', lock))
        flagged = page.evaluate("() => [...document.querySelectorAll('#twin-views [data-attention]')].map(b => b.dataset.view)")
        check(flagged == [], ('nothing is flagged once the lock is locked', flagged))
        L.no_errors(s)


SCENARIOS = [
    scenario_orb_opens_argyle_on_the_twin_wall,
    scenario_attention_on_a_hidden_floor_still_shows,
]


if __name__ == '__main__':
    L.run(SCENARIOS)
