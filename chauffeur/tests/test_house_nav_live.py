"""The Home's navigation in real chromium: real-mouse entries and zones,
the eight-stop orbit (mouse, touch and keyboard), and the idle-return
snap.

Split out of test_house_live.py (Task 7) so tools/test.py's parallel sweep
can spread the file's ~21 Chromium scenarios across workers. This file
holds the navigation/orbit/swipe/idle scenarios; boot/lifecycle/leak
scenarios stayed in test_house_live.py, shell/mask/vault/clipper/
convexity/study-box moved to test_house_shell_live.py, and the facade pin/
worst case/roof-line audit/saved-facade reproduction moved to
test_house_facade_live.py. Shared helpers live in house_live_common.py
— imported, never run on its own.

Run from chauffeur/:  python tests/test_house_nav_live.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_house_nav_live_'))

from live_app import live_app
from house_live_common import check, _seed, DAY_LOCK_JS


def scenario_navigation_real_mouse():
    """Real clicks cover every exterior entry the street view can see,
    cross-room zones and fabric, a zone lean-in, two-step return, inert
    props, and sky exit.

    Project geometry through the current camera; verify candidate pixels
    with the production hit readers before clicking. Low quality keeps
    this behavioral scenario quick. Both high and low explicitly force
    the quality tier and disable automatic demotion.

    The garage block roof's south deck supplies the visible mudroom
    entry; the deeper porch now obscures the old west-skirt target.
    Garage supplies a sky pixel; the main room's roof surrounds its
    camera. The kitchen's own exterior entry is the back door on the
    north wall, which stop 0 cannot see, so this scenario orbits to stop
    5 to click it (massing arc 1, spec section 4). The high-quality
    registry scenario retains separate geometry, cutaway, and
    exterior-entry checks.
    """
    served = live_app()
    if served is None:
        return
    with served.browser() as page:
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_timeout(1800)

        check(page.evaluate("typeof window.chfNavProbe === 'function'"),
              'chfNavProbe must exist for a real-mouse test to derive its '
              'own pixels, never a hard-coded screen point')

        # MASSING ARC 1 (spec sections 2 and 4): the Kitchen marker moved
        # off the patio slider (interior now) onto the new back door, and
        # the Mudroom marker follows its deck's rename
        # (mudroom_cross_roof_south -> garage_block_roof_south). The
        # back door is on the main's NORTH wall, which stop 0 cannot see,
        # so three markers draw at the resting view; the Kitchen one
        # arrives further down, at the orbit stop that can see it.
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#house-hints:not([hidden]) .house-hint').length === 3",
            timeout=10000)
        hints = page.locator('#house-hints .house-hint')
        exterior_targets = set(hints.evaluate_all(
            "els => els.map(e => e.dataset.target)"))
        check(exterior_targets == {
            'front_door', 'garage_block_roof_south', 'garage_front'},
              'persistent exterior markers must identify every room entrance '
              'the street view can see')
        check(page.locator('#house-hints').evaluate(
            "e => getComputedStyle(e).pointerEvents") == 'none',
              'discovery markers must never intercept mouse or touch input')
        living_hint = page.locator(
            '#house-hints .house-hint[data-target="front_door"]')
        check(living_hint.locator('svg').count() == 5,
              'living-room marker must preview music, critters, tasks, '
              'programs and the parent Study')

        def probe(spec_js):
            page.wait_for_function("window.chfNavProbe({settled:true})",
                                   timeout=20000)
            p = page.evaluate('window.chfNavProbe(%s)' % spec_js)
            check(p is not None, 'no reachable canvas pixel for %s' % spec_js)
            return p

        def enter(room):
            if room == 'exterior':
                page.evaluate("window.chfHouseExit && window.chfHouseExit()")
            elif room == 'kitchen':
                page.evaluate("window.chfHouseEnter()")
            else:
                page.evaluate("window.chfHouseEnterRoom(%r)" % room)
            page.wait_for_function(
                "window.chfNavProbe({settled:true})", timeout=20000)

        enter('kitchen')
        page.wait_for_function(
            "() => document.querySelectorAll("
            "'#house-hints:not([hidden]) .house-hint').length === 5",
            timeout=10000)
        kitchen_hints = page.locator('#house-hints .house-hint')
        check(set(kitchen_hints.evaluate_all(
            "els => els.map(e => e.dataset.target)")) == {
                'fridge', 'counter', 'board', 'calendar', 'window'},
              'persistent kitchen markers must identify every actual zone')
        check(all(n == 1 for n in kitchen_hints.locator('svg').evaluate_all(
            "els => els.map(e => e.closest('.house-hint').querySelectorAll('svg').length)")),
              'each interior item marker must carry one feature icon')

        # The front service slope faces the built mudroom. Its back slope
        # covers the unbuilt extension and remains inert. The garage has
        # its own visible street-facing gable and door.
        enter('exterior')
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'must start at the sealed exterior')
        p = probe("{piece:'garage_block_roof_south'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'mudroom',
              'exterior tap on the block roof south deck must enter the '
              'mudroom -- slopeRooms gives that deck to the mudroom, the '
              'same street-adjacency rule as west_wall (spec section 5): '
              '%r' % p)
        # the mudroom's own street FACE is behind the porch and the main
        # block from here, exactly as its predecessor band was: the probe
        # says so, which is why the marker rides the deck above it. The
        # orbit's south-west stops (1 and 2) do see the face -- that is
        # scenario_orbit_eight_stops' mudroom_front probe.
        enter('exterior')
        check(page.evaluate("window.chfNavProbe({piece:'mudroom_front'})") is None,
              'the mudroom street face is not visible from the street view')

        enter('exterior')
        p = probe("{piece:'south_wall'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'exterior tap on the front facade must enter living: %r' % p)

        enter('exterior')
        p = probe("{entry:'front_door'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              'exterior tap on the front door must enter living: %r' % p)

        # The kitchen's exterior entry is the back door on the main's NORTH
        # wall, which the street view cannot see (the marker set pinned
        # above is the whole proof: back_door is not in it). The orbit is
        # what reaches it. Stop 5 is the one used here: with a0 = 43.55
        # degrees measured from +x toward +z, stop 5 sits at 268.55
        # degrees -- within a degree and a half of straight off the north
        # wall -- so the door is as face-on as this house ever gets it,
        # and the garage block (all of it west of x -7.15) stands clear of
        # the sight line to a door at x -2.0. Stops 4 and 6 also see it;
        # 5 sees it squarest. scenario_orbit_eight_stops walks all eight.
        enter('exterior')
        page.evaluate('window.chfOrbitTo(5)')
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        page.wait_for_function(
            "() => [...document.querySelectorAll('#house-hints .house-hint')]"
            ".some(e => e.dataset.target === 'back_door')", timeout=10000)
        check(page.evaluate(
            "[...document.querySelectorAll('#house-hints .house-hint')]"
            ".some(e => e.dataset.target === 'back_door')"),
              'the Kitchen marker is drawn at the stop that can see the '
              'back door')
        p = probe("{entry:'back_door'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'a real click on the back door must enter the kitchen: %r' % p)
        enter('exterior')
        check(page.evaluate('window.chfOrbitStop()') == 5,
              'leaving a room returns to the stop it was entered from')
        page.evaluate('window.chfOrbitTo(0)')
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)

        # (3) garage_shell fronts garage (already true pre-Task-7 via
        # gtag's per-mesh stamps -- pinned here as a still-must-hold
        # regression guard now that it also carries an explicit
        # regFabric room field).
        enter('exterior')
        p = probe("{front:'garage_front'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'garage',
              'exterior tap on the garage gable must enter the garage: %r' % p)

        # Every depth has an explicit way back. This matters most in the
        # garage: its close car view contains almost no sky or yard to tap.
        back = page.locator('#house-back')
        check(back.is_visible(), 'room view must expose a back control')
        check('Exterior' in back.inner_text(),
              'room-level back control must name the exterior destination')
        p = probe("{zone:'garage'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfNavProbe({settled:true})") ==
              {'mode': 'garage', 'focused': 'garage'},
              'car tap must reach the garage detail view')
        check('Garage' in back.inner_text(),
              'focused back control must name the room destination')
        back.click()
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfNavProbe({settled:true})") ==
              {'mode': 'garage', 'focused': None},
              'first back press must restore the full garage view')
        back.click()
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'second back press must restore the exterior view')

        # The button supplements the old background gesture. Even when a
        # detail is focused, visible sky or lawn still exits directly.
        enter('garage')
        page.evaluate("window.chfKitchenFocus('garage')")
        page.wait_for_function(
            "window.chfNavProbe({settled:true}) && "
            "window.chfNavProbe({settled:true}).focused === 'garage'",
            timeout=20000)
        # Put the focused state at the full-room camera so the garage's
        # known sky pixel is visible; chfHouseCam changes only the eye.
        page.evaluate("window.chfHouseCam(-14.05,9.6,21.3,-15.45,1.75,6.05)")
        page.wait_for_timeout(100)
        p = probe("{sky:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'visible sky must exit directly even while detail is focused')

        # spec section 5, rule 2: a zone belonging to ANOTHER room
        # navigates there -- replaces the old cross-room null-and-eject
        # this task deletes. radio is ZONE_ROOM-mapped to living but
        # sits in the shared open great room, visible from the kitchen's
        # own camera.
        enter('kitchen')
        p = probe("{zone:'radio'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'living',
              "tapping the radio's zone from the kitchen must walk into "
              'living, never eject to the exterior: %r' % p)

        # Rule 3 must also work without a zone behind the tapped wall.
        enter('kitchen')
        p = probe("{piece:'west_wall',zoneless:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'mudroom',
              'a zoneless west-wall tap must enter mudroom: %r' % p)

        # spec section 5, rule 1: a zone in the CURRENT room still leans
        # in (unchanged) -- a real click on the board, not the
        # programmatic chfKitchenFocus hand path, which stayed green
        # through the whole bug this task fixes and so proves nothing
        # about onTap.
        enter('kitchen')
        page.evaluate("window.__navEvents = []; "
                       "window.addEventListener('chf-kitchen-focus', "
                       "function (e) { window.__navEvents.push(e.detail); });")
        p = probe("{zone:'board'}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'leaning into the board must stay in the kitchen: %r' % p)
        events = page.evaluate("window.__navEvents")
        check(any(e.get('zone') == 'board' for e in events),
              "a real tap on the board must fire the SAME chf-kitchen-"
              'focus event the card overlay listens for: %r' % events)

        # A blank tap while leaned in first returns to the kitchen view.
        p = probe("{empty:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        state = page.evaluate("window.chfNavProbe({settled:true})")
        check(state == {'mode': 'kitchen', 'focused': None},
              'blank lean-in tap must return to room level: %r' % state)
        check(not page.is_visible('#focus-overlay'),
              'returning to room level must dismiss the focused card')

        # spec section 5, rule 4: the current room's OWN zoneless props
        # are INERT -- the exact bug report's own reproduction (an island
        # mis-tap no longer ejects to the sealed exterior). enterRoom
        # no-ops when already in that room (mode === name), so the board
        # lean-in just above would otherwise still be "focused" here --
        # out to the exterior and back, guaranteeing unfocused, so this
        # exercises rule 4 and not the kitchen's own (unrelated,
        # unchanged) two-step walk-out.
        enter('exterior')
        enter('kitchen')
        check(not page.is_visible('#focus-overlay'),
              'must start this check unfocused, or a leftover lean-in '
              'card would make the inert assertion below meaningless')
        p = probe("{point:[-0.4,1.085,0.9]}")   # the island counter top
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'kitchen',
              'a mis-tap on the island must stay in the kitchen, not '
              'eject to the sealed exterior (the reported bug): %r' % p)
        check(not page.is_visible('#focus-overlay'),
              'the island mis-tap must not mount a lean-in card either -- '
              'truly inert, not an accidental lean')

        # spec section 5, rule 5: sky OR yard exits. The garage camera sees
        # no sky since the envelope arc (its frame is interior, roofs and
        # lawn), so probe for any exit pixel -- the same test onTap runs.
        enter('garage')
        p = probe("{exit:true}")
        page.mouse.click(p['cx'], p['cy'])
        page.wait_for_timeout(1200)
        check(page.evaluate("window.chfHouseMode()") == 'exterior',
              'a sky or yard tap must still exit to the exterior: %r' % p)

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_orbit_eight_stops():
    """Spec 2026-09-16 section 4: eight tweened stops around the pivot; every
    stop settles clean, draws at least one marker, and every entrance is
    reachable from some stop."""
    served = live_app(_seed)
    if served is None:
        return
    with served.browser() as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=high&angle=3'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 3, '?angle=3 boots at stop 3')
        seen = {}
        for k in range(8):
            page.evaluate('window.chfOrbitTo(%d)' % k)
            page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
            # the markers are DEFERRED (scheduleHint, 1600 ms) so they cannot
            # flicker mid-tween: settle alone is 850 ms too early to count them.
            try:
                page.wait_for_function(
                    "() => document.querySelectorAll("
                    "'#house-hints:not([hidden]) .house-hint').length >= 1",
                    timeout=6000)
            except Exception:
                pass
            check(page.evaluate('window.chfHouseMode()') == 'exterior',
                  'orbit never leaves the exterior')
            n = page.locator('#house-hints:not([hidden]) .house-hint').count()
            check(n >= 1, 'stop %d draws at least one marker (got %d)' % (k, n))
            for spec in ("{entry:'front_door'}", "{entry:'back_door'}",
                         "{piece:'mudroom_front'}", "{front:'garage'}"):
                if page.evaluate('window.chfNavProbe(%s)' % spec):
                    seen.setdefault(spec, k)
        check(len(seen) == 4,
              'every entrance reachable from some stop: %r' % (seen,))
        # a swipe steps once
        before = page.evaluate('window.chfOrbitStop()')
        box = page.locator('#room canvas').bounding_box()
        page.mouse.move(box['x'] + box['width'] * 0.7, box['y'] + box['height'] * 0.5)
        page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * 0.3, box['y'] + box['height'] * 0.5, steps=8)
        page.mouse.up()
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'a left swipe advances one stop')
        check(page.evaluate('window.chfHouseMode()') == 'exterior',
              'a swipe must not double as a tap into a room')
        page.keyboard.press('ArrowLeft')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before, 'ArrowLeft steps back')
        # the chevrons are the hand path: exterior only, and they step
        page.wait_for_selector('.house-orbit[data-dir="1"]:not([hidden])', timeout=10000)
        page.click('.house-orbit[data-dir="1"]')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'the right chevron steps one stop')
        page.click('.house-orbit[data-dir="-1"]')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'the left chevron steps back')
        # The arrows belong to the HOUSE, not to whatever the person is
        # typing into on top of it. /house carries the Argyle textarea
        # (control_center.html #chat-input) and the music widget's search
        # box and volume slider, none of which set `house-card-open`, and
        # none of whose own handlers stop an arrow key from bubbling to
        # window -- so an unguarded branch turns "move the caret back one
        # character" into an 850 ms camera tween plus a solveShell.
        page.focus('#chat-input')
        page.keyboard.type('what time is soccer')
        page.keyboard.press('ArrowLeft')
        page.wait_for_timeout(1200)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'an arrow key inside a text field must not turn the house')
        check(page.evaluate("document.getElementById('chat-input').value")
              == 'what time is soccer',
              'the text field keeps what was typed into it')
        page.evaluate("document.getElementById('chat-input').value = '';"
                      "document.getElementById('chat-input').blur()")
        page.keyboard.press('ArrowRight')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'and with nothing focused the same key still steps the ring')
        page.keyboard.press('ArrowLeft')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'back to where the chevrons left it')
        # entering a room and leaving returns to the CURRENT stop
        page.evaluate("window.chfOrbitTo(5)")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        page.evaluate("window.chfHouseEnter()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitTo(2)') is False,
              'a room ignores orbit input (spec section 4: rooms stay fixed '
              'dioramas)')
        check(page.locator('.house-orbit[data-dir="1"]').is_hidden(),
              'the chevrons belong to the exterior only')
        page.evaluate("window.chfHouseExit()")
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 5,
              'exit returns to the stop you left from')
        check(not errors, 'zero console errors across the orbit: %r' % (errors[:3],))


def scenario_orbit_swipe_works_under_a_real_finger():
    """MASSING ARC 1 fix wave: the swipe on a TOUCH surface.

    `scenario_orbit_eight_stops` drives the swipe with `page.mouse`, which
    never exercises the gesture the wall panel actually gets. On a touch
    surface the browser owns the drag first: past its pan slop it claims
    the gesture, fires `pointercancel`, and `pointerup` never arrives on
    the canvas at all -- so a swipe handler built on pointerdown/pointerup
    alone is inert on the one surface that has no mouse. house.html's
    `#room canvas { touch-action: none }` is what stops the browser
    claiming it (the page cannot scroll anyway); house.js's
    `pointercancel` listener is the belt to that brace.

    Driven through CDP `Input.dispatchTouchEvent` rather than
    `page.touchscreen.tap` (which can only tap) in a context built with
    `has_touch=True`, so the events carry `pointerType: 'touch'` and the
    real touch-action machinery runs.
    """
    served = live_app(_seed)
    if served is None:
        return
    with served.browser(has_touch=True) as page:
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.add_init_script(DAY_LOCK_JS)
        page.goto(served.url('house?quality=low&angle=2'))
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == 2, '?angle=2 boots at stop 2')
        # the canvas must actually refuse the browser's own gestures, or the
        # drag below is a pan and the handler never hears its end.
        ta = page.evaluate(
            "getComputedStyle(document.querySelector('#room canvas')).touchAction")
        check(ta == 'none', "the canvas takes the gesture itself: touch-action %r" % ta)
        cdp = page.context.new_cdp_session(page)
        box = page.locator('#room canvas').bounding_box()
        y = box['y'] + box['height'] * 0.5
        x0 = box['x'] + box['width'] * 0.7
        x1 = box['x'] + box['width'] * 0.3
        check(abs(x1 - x0) >= 60, 'the drag clears the 60px threshold')

        def touch(kind, x=None):
            pts = [] if x is None else [{'x': x, 'y': y}]
            cdp.send('Input.dispatchTouchEvent',
                     {'type': kind, 'touchPoints': pts})

        before = page.evaluate('window.chfOrbitStop()')
        touch('touchStart', x0)
        for i in range(1, 9):                     # eight moves, past the slop
            touch('touchMove', x0 + (x1 - x0) * i / 8.0)
        touch('touchEnd')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == (before + 1) % 8,
              'a finger dragged left advances one stop (was %d, now %d)'
              % (before, page.evaluate('window.chfOrbitStop()')))
        check(page.evaluate('window.chfHouseMode()') == 'exterior',
              'a swipe must not double as a tap into a room')
        # and back the other way, so direction is pinned too
        touch('touchStart', x1)
        for i in range(1, 9):
            touch('touchMove', x1 + (x0 - x1) * i / 8.0)
        touch('touchEnd')
        page.wait_for_function("window.chfNavProbe({settled:true})", timeout=20000)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'a finger dragged right steps back')
        # a cancelled gesture leaves nothing armed: the next plain tap must
        # still read as a tap, not pair with the abandoned start point.
        touch('touchStart', x0)
        touch('touchMove', x1)
        touch('touchCancel')
        page.wait_for_timeout(200)
        check(page.evaluate('window.chfOrbitStop()') == before,
              'a cancelled drag turns nothing')
        check(not errors, 'zero console errors across the touch swipe: %r'
              % (errors[:3],))


def scenario_idle_return_snaps_the_orbit_home():
    """Spec 2026-09-16 sections 4/7: the panel's idle-return timer snaps the
    orbit back to stop 0, so the wall always rests on the street view.

    The timer is shortened through the setting the panel actually reads
    (`panel_idle_return_seconds`, served on /api/panel/profile as
    `idle_seconds`) rather than by stubbing the fetch: nav.html's
    `chfIdleRemaining` floors every period at three seconds, so the
    alternative -- a stale `chfPanelLastInput` written by an init script --
    would collapse the SCREENSAVER's period to the same three seconds and
    race it, and a screensaver that wins defers the return entirely
    (`_chfSsPendingHome`). The init script here carries the recorder instead.

    /house is not the home board, so nav.html's `goHome` navigates the panel
    away after the snap; the snap is caught on its way out through the
    house's own `chf-house-orbit` event (parked in sessionStorage, which
    survives the navigation) and the navigation itself is asserted after it.
    """
    from services import storage
    served = live_app(_seed)
    if served is None:
        return
    before = dict(storage.get_settings())
    storage.update_settings(dict(before, panel_idle_return_seconds=10))
    try:
        with served.browser() as page:
            page.add_init_script(DAY_LOCK_JS)
            page.add_init_script(
                "window.addEventListener('chf-house-orbit', function (e) {"
                "  try { sessionStorage.setItem('chfOrbitSeen',"
                "    String(e.detail.stop)); } catch (err) {}"
                "});")
            page.goto(served.url('house?quality=low&panel=true&angle=5'))
            page.wait_for_selector('#room canvas', timeout=20000)
            page.wait_for_function("window.chfNavProbe({settled:true})",
                                   timeout=20000)
            check(page.evaluate('window.chfOrbitStop()') == 5,
                  'the panel starts the idle wait off the street view')
            check(page.evaluate("sessionStorage.getItem('chfOrbitSeen')") is None,
                  'nothing has moved the orbit yet')
            # No input of any kind from here: every listener nav.html arms
            # (pointerdown/keydown/wheel/touchstart) would restart the clock.
            page.wait_for_url('**/home*', timeout=40000)
            check(page.evaluate("sessionStorage.getItem('chfOrbitSeen')") == '0',
                  'the idle return snapped the orbit to stop 0 before the '
                  'panel went home')
    finally:
        storage.update_settings(before)


def scenario_mirror_is_one_reflection():
    """Spec 2026-09-17 section 3.4: a mirrored plan is ONE reflection of the
    finished house, applied to a root group after the clip/merge/AO passes.

    What that has to mean, and what this pins:
      * the reflection is on the root and nowhere else -- same fabric count
        as the unmirrored build, houseRoot.scale.x -1, house meshes drawn
        through a negative determinant;
      * the house really is on the other side -- the garage door and its
        block's roof, west of the origin in the canonical plan, come out
        at POSITIVE world x, the door at exactly -x of where it stood;
      * lettering still reads forward -- every text mesh is counter-flipped
        back to a positive determinant, and the leaned-in car plaque's
        pixels correlate with its own canvas rather than with a mirrored
        copy of it;
      * every exterior marker is still findable from the ring, and a
        lean-in still lands on its card (the kitchen calendar), which is
        the whole camera boundary in one number.
    """
    import copy
    import io as _io
    import json

    from services import house_facade as hf
    from house_live_common import SEED_RNG_JS

    spec, _notes = hf.normalize(dict(copy.deepcopy(hf.CANONICAL), mirror=True))
    check(spec['mirror'] is True, 'the draft really asks for a mirror')
    served = live_app(_seed)
    if served is None:
        return

    # the four exterior markers the street view offers, in the shape
    # hintChoices() builds them (an `entry` is a live world box; a `piece`
    # and a `front` are FABRIC's own house-local boxes, which is the pair
    # the reflection has to get right in different ways).
    PROBES = [('front_door', {'entry': 'front_door'}),
              ('back_door', {'entry': 'back_door'}),
              ('mudroom_roof', {'piece': 'garage_block_roof_south'}),
              ('garage_front', {'front': 'garage_front'})]

    def boot(page, url):
        page.add_init_script(DAY_LOCK_JS)
        page.add_init_script(SEED_RNG_JS)
        page.goto(url)
        page.wait_for_selector('#room canvas', timeout=20000)
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)

    def reachable(page):
        """which markers the ring can find, walking all eight stops"""
        found = set()
        for k in range(8):
            page.evaluate('window.chfOrbitTo(%d)' % k)
            page.wait_for_function("window.chfNavProbe({settled:true})",
                                   timeout=20000)
            for name, probe in PROBES:
                if name in found:
                    continue
                if page.evaluate('window.chfNavProbe(%s)' % json.dumps(probe)):
                    found.add(name)
        page.evaluate('window.chfOrbitTo(0)')
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        return found

    CENTRE_X_JS = ("(n => { const b = window.chfWorldBox(n);"
                   " return b ? (b[0] + b[1]) / 2 : null; })")
    CAL_DIST_JS = ("(() => { const b = window.chfWorldBox('calendar');"
                   " const c = window.chfCamPose();"
                   " if (!b || !c) return null;"
                   " const dx = (b[0]+b[1])/2 - c.pos[0];"
                   " const dy = (b[2]+b[3])/2 - c.pos[1];"
                   " const dz = (b[4]+b[5])/2 - c.pos[2];"
                   " return Math.sqrt(dx*dx + dy*dy + dz*dz); })()")

    def lean_on_the_calendar(page):
        """chfKitchenFocus walks the room and then frames the card: two
        tweens, so settle twice before the camera has arrived."""
        page.evaluate("window.chfKitchenFocus('calendar')")
        for _ in range(2):
            page.wait_for_timeout(400)
            page.wait_for_function("window.chfNavProbe({settled:true})",
                                   timeout=20000)
        return page.evaluate(CAL_DIST_JS)

    with served.browser() as page:
        boot(page, served.url('house?quality=high'))
        plain_fabric = page.evaluate('window.chfShellFabric().length')
        plain = page.evaluate('window.chfMirror()')
        check(plain['mirror'] is False and plain['root'] == 1,
              'the canonical plan is not reflected: %r' % (plain,))
        check(plain['fabricDet'] > 0 and plain['textDet'] > 0,
              'nothing is drawn through a reflection unmirrored: %r' % (plain,))
        plain_text = plain['noMirrorCount']
        check(plain_text >= 7,
              'the canonical house already carries its text meshes '
              '(pane, calendar, hero plaque, critters, bus stop arm and one '
              'plaque per parked car): %d' % plain_text)
        plain_reach = reachable(page)
        plain_gd = page.evaluate(CENTRE_X_JS + "('garage_door')")
        check(plain_gd is not None and plain_gd < 0,
              'the canonical garage door stands WEST of the origin: %r'
              % (plain_gd,))
        plain_lean = lean_on_the_calendar(page)
        check(plain_lean is not None and plain_lean < 10.0,
              'the canonical lean-in stands at the card: %r' % (plain_lean,))

    with served.browser() as page:
        boot(page, served.url('house?quality=high&draft=' + hf.issue_draft(spec)))
        m = page.evaluate('window.chfMirror()')
        check(m['mirror'] and m['root'] == -1,
              'one reflection, and it is on the root: %r' % (m,))
        check(m['fabricDet'] < 0,
              'the house itself IS drawn reflected: %r' % (m,))
        check(m['textDet'] > 0,
              'every lettered mesh is counter-flipped back to a proper '
              'rotation, so its words read forward: %r' % (m,))
        check(m['noMirrorCount'] == plain_text,
              'the same text meshes stand in both plans: %d vs %d'
              % (m['noMirrorCount'], plain_text))
        check(page.evaluate('window.chfShellFabric().length') == plain_fabric,
              'a reflection builds no extra fabric and drops none: %d vs %d'
              % (page.evaluate('window.chfShellFabric().length'), plain_fabric))

        # the house really moved, and by exactly one reflection: the garage
        # door, west of the origin in the canonical plan, comes out east of
        # it at the mirror image of its own x, to the millimetre.
        cx = page.evaluate(CENTRE_X_JS + "('garage_door')")
        check(cx is not None and cx > 0,
              'the garage door is on the other side once mirrored: %r' % (cx,))
        check(abs(cx + plain_gd) < 0.01,
              'the garage door lands at exactly -x, not merely somewhere '
              'east: %r vs %r' % (cx, plain_gd))
        rx = page.evaluate(CENTRE_X_JS + "('garage_block_roof_south')")
        check(rx is not None and rx > 0,
              'the garage block roof went with it: %r' % (rx,))

        mirror_reach = reachable(page)
        check(mirror_reach == plain_reach,
              'every exterior marker the ring could find is still findable '
              'mirrored: %r vs %r' % (sorted(mirror_reach),
                                      sorted(plain_reach)))

        # the lean-in: the camera has to land on the MIRRORED calendar, at
        # the same remove from the card as it does in the canonical plan.
        # (An unflipped camera would stop the width of the house away, so
        # the number is not a near miss either way.)
        d = lean_on_the_calendar(page)
        check(d is not None and abs(d - plain_lean) < 0.05,
              'the lean-in stands off the mirrored calendar exactly as far '
              'as it stands off the canonical one: %r vs %r' % (d, plain_lean))

        # ... and the plaque it can see there reads FORWARD by pixel
        page.evaluate("window.chfHouseEnterRoom('garage')")
        page.wait_for_timeout(400)
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        url = page.evaluate('window.chfPlaqueCanvas(0)')
        rect = page.evaluate('window.chfPlaqueRect(0)')
        check(url and rect and rect['w'] > 20,
              'the garage view shows a car plaque big enough to read: %r'
              % (rect,))
        png = page.screenshot()
        import base64
        from PIL import Image, ImageChops, ImageOps
        want = Image.open(_io.BytesIO(base64.b64decode(url.split(',', 1)[1])))
        want = want.convert('L').resize((128, 64))
        shot = Image.open(_io.BytesIO(png)).convert('L')
        crop = shot.crop((int(rect['x']), int(rect['y']),
                          int(rect['x'] + rect['w']),
                          int(rect['y'] + rect['h']))).resize((128, 64))
        crop = ImageOps.autocontrast(crop)
        want = ImageOps.autocontrast(want)

        def diff(a, b):
            d = ImageChops.difference(a, b)
            px = list(d.getdata())
            return sum(px) / float(len(px))

        fwd = diff(crop, want)
        rev = diff(crop, want.transpose(Image.FLIP_LEFT_RIGHT))
        check(fwd < rev,
              'the plaque on screen matches its OWN canvas better than a '
              'mirrored copy of it (forward %.2f vs flipped %.2f)'
              % (fwd, rev))

        page.evaluate('window.chfHouseExit()')
        page.wait_for_function("window.chfNavProbe({settled:true})",
                               timeout=20000)
        errs = [e for e in served.errors() if 'WebGL' not in e]
        check(not errs, 'console clean: %r' % (errs[:3],))


if __name__ == '__main__':
    scenario_navigation_real_mouse()
    scenario_orbit_eight_stops()
    scenario_orbit_swipe_works_under_a_real_finger()
    scenario_idle_return_snaps_the_orbit_home()
    scenario_mirror_is_one_reflection()
    print("test_house_nav_live OK")
