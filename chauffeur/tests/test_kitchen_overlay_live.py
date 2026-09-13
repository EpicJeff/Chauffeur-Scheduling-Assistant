"""The focus overlay in real chromium against the served app.

Pins cannot see whether Alpine actually mounts the Family Day island, or
whether the hero builder is on the page and escaping. Drive the real page:
the room's focus announcement is a plain CustomEvent, so the test speaks it
directly (the 3D raycast is the room's own business, proven by eye), and
what must follow is board-grade DOM inside the overlay — with zero console
errors, the live-app harness's whole point.

Run from chauffeur/:  python tests/test_kitchen_overlay_live.py
Set KITCHEN_SHOTS=<dir> to also save screenshots of both overlays.
"""
import datetime
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR',
                      tempfile.mkdtemp(prefix='chauffeur_kitchen_overlay_'))

import tpl_source
from live_app import live_app


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _seed():
    """An event TODAY whatever the clock says, so the hero and the
    Family Day both have something to show: upcoming when the evening
    allows, already under way when the test runs close to midnight (an
    on-now run is the hero too — that is the board's own rule)."""
    from services import storage
    now = datetime.datetime.now().replace(microsecond=0)
    late = now.replace(hour=23, minute=59, second=0)
    start = now + datetime.timedelta(minutes=45)
    end = start + datetime.timedelta(hours=1)
    if end > late:   # near midnight: run it NOW, ending at day's edge
        start, end = now - datetime.timedelta(minutes=5), late
    storage.add_driver({'id': 'd1', 'name': 'Alex', 'color': '#38bdf8'})
    # Pin the cache FUNCTION, not the row: the server's own boot refresh
    # rebuilds the cache from the (empty) calendars moments after boot and
    # would silently erase a seeded row mid-test. Same idiom as
    # test_kitchen_state — the server thread shares this process.
    sched = {
        'events': [{'id': 'e1', 'title': 'Soccer practice',
                    'start': start.isoformat(), 'end': end.isoformat()}],
        'assignments': {'e1': 'd1'},
    }
    storage.get_cached_schedule = lambda: sched


RECT = {'left': 420, 'top': 220, 'width': 520, 'height': 380}


def _focus(page, zone):
    page.evaluate(
        "z => window.dispatchEvent(new CustomEvent('chf-kitchen-focus',"
        " { detail: { zone: z, rect: z ? " + json.dumps(RECT) + " : null } }))",
        zone)


def scenario_overlay_lives_on_the_real_page():
    # Seed AFTER boot: startup refresh rebuilds the schedule cache, so a
    # cache written before the server comes up is gone by the first request.
    served = live_app()
    if served is None:
        return
    _seed()
    shots = os.environ.get('KITCHEN_SHOTS', '')
    with served.browser() as page:
        # forced tier: the boot benchmark on a headless GPU can demote and
        # RELOAD the page mid-test, aborting whatever fetch was in flight
        page.goto(served.url('kitchen?quality=high'))
        page.wait_for_selector('#focus-overlay', state='attached')
        page.wait_for_timeout(600)   # alpine boot

        # calendar -> the Family Day card, the board's own read-only mode
        _focus(page, 'calendar')
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        check(page.is_visible('#focus-overlay'), "overlay shows on calendar focus")
        check('Soccer practice' in page.inner_text('#overlay-calendar'),
              "the Family Day card names the seeded event")
        check(page.evaluate(
                  "Alpine.$data(document.getElementById('overlay-calendar'))"
                  ".pkInteractive") is True,
              "the Family Day island mounts interactive — the card IS the board")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_calendar_overlay.png'))

        # door -> the hero card, the screensaver's compact form
        _focus(page, None)
        _focus(page, 'door')
        page.wait_for_selector('#overlay-door >> text=Soccer practice', timeout=8000)
        check(page.is_visible('#focus-overlay'), "overlay shows on door focus")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_door_overlay.png'))

        # unfocus -> gone
        _focus(page, None)
        page.wait_for_timeout(150)
        check(not page.is_visible('#focus-overlay'), "unfocus hides the overlay")

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_the_real_lean_in_wears_the_card():
    """The vision, end to end: the tap's own camera move (chfKitchenFocus
    drives the exact frameZone path), then the board's card ON the framed
    furniture — filling the zone's projected rect, not the old centred
    toast. Skipped politely when this machine's chromium has no WebGL,
    because then there is no room to lean into (the 2D fallback owns the
    page and draws its own detail)."""
    served = live_app()
    if served is None:
        return
    _seed()
    shots = os.environ.get('KITCHEN_SHOTS', '')
    with served.browser() as page:
        # forced tier: the boot benchmark on a headless GPU can demote and
        # RELOAD the page mid-test, aborting whatever fetch was in flight
        page.goto(served.url('kitchen?quality=high'))
        page.wait_for_timeout(1800)   # boot, benchmark warmup, first paint
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfKitchenFocus === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        page.evaluate(
            "window.__rect = null;"
            "window.addEventListener('chf-kitchen-focus',"
            " e => { if (e.detail && e.detail.rect) window.__rect = e.detail.rect; })")
        page.evaluate("window.chfKitchenFocus('calendar')")
        page.wait_for_selector('#overlay-calendar .agenda-event', timeout=8000)
        page.wait_for_timeout(450)    # tween settled + fade done
        geo = page.evaluate(
            "(() => { const r = document.getElementById('focus-overlay')"
            ".getBoundingClientRect();"
            " return { l: r.left, w: r.width, z: window.__rect }; })()")
        check(geo['z'] is not None, "the room announced the framed rect")
        ov_cx = geo['l'] + geo['w'] / 2
        zone_cx = geo['z']['left'] + geo['z']['width'] / 2
        check(abs(ov_cx - zone_cx) < 48,
              "the card sits ON the framed furniture, centred on its face")
        check(geo['w'] >= 300, "the card stays readable")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_calendar_leanin.png'))

        page.evaluate("window.chfKitchenFocus('door')")
        page.wait_for_selector('#overlay-door >> text=Soccer practice',
                               timeout=8000)
        page.wait_for_timeout(450)
        check(not page.is_visible('#overlay-calendar'),
              "switching zones swaps the card, never stacks them")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_door_leanin.png'))

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_other_zones_wear_their_cards():
    """The port: corkboard wears the real shopping-list card, the window
    wears the weather card — mounted through the board's own tile body,
    read-only, from one ?widgets= payload. A zone whose tile is empty
    (nothing seeded) keeps the tip, and that path is the fridge here."""
    served = live_app()
    if served is None:
        return
    _seed()
    from services import storage, ha_api
    storage.shopping_lists_table.truncate()
    storage.shopping_items_table.truncate()
    storage.add_shopping_list({'id': 'grocery', 'name': 'Groceries',
                               'is_default': True})
    storage.shopping_items_table.insert(
        {'id': 's1', 'name': 'Oat milk', 'list_id': 'grocery',
         'is_checked': False, 'created_at': 1})
    storage.shopping_items_table.insert(
        {'id': 's2', 'name': 'Eggs', 'list_id': 'grocery',
         'is_checked': False, 'created_at': 2})
    base = datetime.datetime.now().replace(hour=12, minute=0, second=0,
                                           microsecond=0)
    days = [{'condition': 'sunny', 'temperature': 70 + i, 'templow': 55,
             'precipitation_probability': 0,
             'datetime': (base + datetime.timedelta(days=i)).isoformat()}
            for i in range(5)]
    ha_api.get_weather_forecast = lambda e=None, kind='daily': days
    # the board payload is TTL-cached server-side; the previous scenario
    # already built it WITHOUT this stub, so drop that copy
    from services import home_board
    home_board.invalidate_cache()

    shots = os.environ.get('KITCHEN_SHOTS', '')
    with served.browser() as page:
        # forced tier: the boot benchmark on a headless GPU can demote and
        # RELOAD the page mid-test, aborting whatever fetch was in flight
        page.goto(served.url('kitchen?quality=high'))
        page.wait_for_timeout(1800)
        has_room = page.evaluate(
            "!!document.querySelector('#room canvas') && "
            "typeof window.chfKitchenFocus === 'function'")
        if not has_room:
            print("  skip  no WebGL room here — the fallback owns the page")
            return

        # Watch every single state the card passes through on its way up.
        # The list's contents arrive over three round trips, and for a year
        # the card filled that gap by ASSERTING the household had nothing on
        # its list — `items: []` read as "empty" when it only ever meant
        # "nobody has asked". On a board that was a flash; leaning into the
        # dollhouse pantry, where a WebGL frame sits between the mount and
        # the fetch's continuation, it was the whole lean-in, and the pantry
        # photographed as "Nothing on this list" over two eggs and a milk.
        page.evaluate("""() => {
            window.__saidEmpty = false;
            const tick = () => {
                const t = document.querySelector('#overlay-tile');
                // innerText, so a hidden empty state does not count — which
                // is the whole distinction being pinned here
                if (t && (t.innerText || '').indexOf('Nothing on this list') !== -1) {
                    window.__saidEmpty = true;
                }
                requestAnimationFrame(tick);
            };
            tick();
        }""")
        page.evaluate("window.chfKitchenFocus('board')")
        page.wait_for_selector('#overlay-tile >> text=Eggs', timeout=8000)
        check(not page.evaluate("window.__saidEmpty"),
              "the card never says the list is empty while it is still reading it")
        live_buttons = page.evaluate(
            "Array.from(document.querySelectorAll('#overlay-tile button'))"
            ".filter(b => b.offsetParent !== null && !b.disabled).length")
        check(live_buttons > 0,
              "the shopping card mounts interactive: real ticks, enabled")
        check(page.evaluate(
                  "document.getElementById('overlay-open').getAttribute('href')"
                  ".indexOf('lists') !== -1"),
              "the open chip is the door to the zone's own page")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_board_leanin.png'))

        page.evaluate("window.chfKitchenFocus('window')")
        page.wait_for_selector('#overlay-tile >> text=70', timeout=8000)
        check(not page.is_visible('#overlay-calendar'),
              "zone switch swaps the mounted card")
        if shots:
            page.screenshot(path=os.path.join(shots, 'kitchen_window_leanin.png'))

        # the radio wears the real Music Assistant player widget.
        # Condition-waits, not fixed sleeps: under a saturated sweep the
        # 650ms focus tween alone can outlive a 1400ms nap (flaked twice
        # on the 12-worker run, passed every standalone run).
        page.evaluate("window.chfKitchenFocus('radio')")
        page.wait_for_selector('#overlay-music', state='visible', timeout=8000)
        check(page.is_visible('#overlay-music'),
              "the radio wears the music widget (player half)")

        # nothing seeded for moments: the fridge keeps its tip-only lean-in
        page.evaluate("window.chfKitchenFocus('fridge')")
        page.wait_for_selector('#focus-overlay', state='hidden', timeout=8000)
        check(not page.is_visible('#focus-overlay'),
              "an empty tile hides the overlay instead of showing blank paper")

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


# ── The lean-out has to stop the polling.
#
# Every self-fetching card starts a `setInterval` in its `start*()`. On a
# board that is invisible — the tile is mounted for the life of the document.
# On the dollhouse the same cards are worn by FURNITURE: mounted on a lean-in,
# torn out on the lean-out, several times an evening. Alpine tearing down an
# `x-if` subtree does not touch a `setInterval`, so for a long time every
# lean-in left its timers running.
#
# Measured on /house before the fix: three lean-ins into the shopping zone
# registered six live intervals — [300000, 60000] x 3, one pair per lean-in,
# none cleared — and with no card on screen the page went on asking for the
# list three times a minute, permanently, on a scene whose entire discipline
# is render-on-demand.
#
# This pins it two ways, because one alone is weak. The counts come from an
# instrumented setInterval/clearInterval pair installed BEFORE any page
# script runs, so nothing on the page can hide a timer from it; and then the
# orphans are FIRED, which turns "some numbers survived" into the thing that
# actually costs — requests the server answers for a card nobody is looking
# at. The cadences are read out of the component rather than typed here, so
# a poll that changes cannot leave this test quietly measuring nothing.
TIMER_PROBE = """
(() => {
  const si = window.setInterval, ci = window.clearInterval;
  window.__t = { live: new Map(), made: [] };
  window.setInterval = function (fn, ms) {
    const id = si.apply(window, arguments);
    window.__t.live.set(id, { ms: ms, fn: fn });
    window.__t.made.push(ms);
    return id;
  };
  window.clearInterval = function (id) {
    window.__t.live.delete(id);
    return ci.apply(window, arguments);
  };
  /* every live interval, as [id, ms] pairs — playwright cannot carry a Map */
  window.__live = () => Array.from(window.__t.live.entries()).map(e => [e[0], e[1].ms]);
  /* what the next tick WOULD have done, now: the orphan's own callback */
  window.__fire = (ids) => {
    let n = 0;
    ids.forEach(i => {
      const rec = window.__t.live.get(i);
      if (!rec) return;
      n++;
      try { rec.fn(); } catch (e) { /* an orphan throwing still counts */ }
    });
    return n;
  };
})();
"""


def _card_cadences():
    """The shopping card's two polls, read from the component that owns them:
    the list card's own (which lists exist) and the pane's (what is on one)."""
    src = tpl_source.read('components/shopping_lists.html')
    out = []
    for name in ('SHOPPING_LISTS_POLL_MS', 'SHOPPING_POLL_MS'):
        m = re.search(r'\b' + name + r'\s*=\s*(\d+)', src)
        check(m, f"components/shopping_lists.html no longer defines {name}")
        out.append(int(m.group(1)))
    return out


def _seed_a_list():
    from services import storage, ha_api, home_board
    storage.shopping_lists_table.truncate()
    storage.shopping_items_table.truncate()
    storage.add_shopping_list({'id': 'grocery', 'name': 'Groceries',
                               'is_default': True})
    storage.shopping_items_table.insert(
        {'id': 's1', 'name': 'Oat milk', 'list_id': 'grocery',
         'is_checked': False, 'created_at': 1})
    # the weather zone is the OTHER exit: leaving the shopping zone for another
    # card-bearing one is how the leak was found, and it unmounts differently
    # (the tile swaps under the island) than an unfocus does.
    base = datetime.datetime.now().replace(hour=12, minute=0, second=0,
                                           microsecond=0)
    ha_api.get_weather_forecast = lambda e=None, kind='daily': [
        {'condition': 'sunny', 'temperature': 70 + i, 'templow': 55,
         'precipitation_probability': 0,
         'datetime': (base + datetime.timedelta(days=i)).isoformat()}
        for i in range(5)]
    home_board.invalidate_cache()


def scenario_leaning_out_stops_the_cards_polling():
    """Lean in, lean out, three times — and nothing keeps asking."""
    served = live_app()
    if served is None:
        return
    _seed()
    _seed_a_list()
    slow, quick = _card_cadences()
    with served.browser() as page:
        # before ANY page script: a card that armed its timer during boot
        # would otherwise be invisible to this
        page.add_init_script(TIMER_PROBE)
        asked = []
        page.on('request',
                lambda r: 'api/shopping' in r.url and asked.append(r.url))
        # the dollhouse, where the cards are worn by furniture. ?quality=low so
        # a GPU-less machine still boots the real page (and cannot demote-and-
        # reload mid-test); the lean-in is spoken as the CustomEvent the room
        # announces, so this runs with or without WebGL.
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#focus-overlay', state='attached')
        page.wait_for_timeout(2000)   # alpine boot, the room's own boot timers

        # everything the IDLE page runs. The hearth polls a minute, the theme
        # five seconds — real timers that must survive, so the question is
        # never "how many" but "which ones are NEW and still alive".
        before = {i for i, _ in page.evaluate("window.__live()")}

        exits = [None, 'window', None]
        for out in exits:
            _focus(page, 'board')
            page.wait_for_selector('#overlay-tile >> text=Oat milk', timeout=8000)
            _focus(page, out)
            if out is None:
                page.wait_for_selector('#focus-overlay', state='hidden',
                                       timeout=8000)
            else:
                page.wait_for_selector('#overlay-tile >> text=70', timeout=8000)
            page.wait_for_timeout(150)   # alpine tears down on its own tick
        _focus(page, None)
        page.wait_for_selector('#focus-overlay', state='hidden', timeout=8000)
        page.wait_for_timeout(200)

        made = page.evaluate("window.__t.made")
        armed = [ms for ms in made if ms in (slow, quick)]
        check(len(armed) >= 2 * len(exits),
              "the card never armed its polls — this scenario would pass "
              f"without measuring anything (cadences seen: {sorted(set(made))})")

        live = page.evaluate("window.__live()")
        orphans = [(i, ms) for i, ms in live
                   if i not in before and ms in (slow, quick)]
        check(not orphans,
              f"{len(orphans)} of the card's polls outlived the lean-out "
              f"(cadences {[ms for _, ms in orphans]}) — a lean-in that never "
              f"stops is a wall that asks the server more every evening")

        # and the thing that actually costs: what those orphans would ask for.
        # Fired rather than waited out, so the pin is exact instead of a
        # sixty-five-second nap that a slow machine could still lose.
        strays = [(i, ms) for i, ms in live if i not in before]
        asked.clear()
        fired = page.evaluate("ids => window.__fire(ids)",
                              [i for i, _ in strays])
        page.wait_for_timeout(600)
        check(not asked,
              f"{len(asked)} shopping requests with no card mounted "
              f"(fired {fired} surviving timers): " + '; '.join(asked[:4]))

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_a_mounted_card_still_polls():
    """The other half, and the one a careless fix breaks: while the card IS
    on screen its poll must still be running at the cadence it always had.
    `destroy()` fires on teardown alone — this is what says so out loud."""
    served = live_app()
    if served is None:
        return
    _seed()
    _seed_a_list()
    slow, quick = _card_cadences()
    with served.browser() as page:
        page.add_init_script(TIMER_PROBE)
        page.goto(served.url('house?quality=low'))
        page.wait_for_selector('#focus-overlay', state='attached')
        page.wait_for_timeout(2000)
        before = {i for i, _ in page.evaluate("window.__live()")}

        _focus(page, 'board')
        page.wait_for_selector('#overlay-tile >> text=Oat milk', timeout=8000)
        page.wait_for_timeout(400)

        live = page.evaluate("window.__live()")
        mounted = sorted(ms for i, ms in live if i not in before)
        check(mounted == sorted([slow, quick]),
              "a mounted card must still hold both of its polls — "
              f"found {mounted}, expected {sorted([slow, quick])}")

        # and they still DO something: fire them and the server hears it.
        asked = []
        page.on('request',
                lambda r: 'api/shopping' in r.url and asked.append(r.url))
        page.evaluate("ids => window.__fire(ids)",
                      [i for i, ms in live if i not in before])
        page.wait_for_timeout(600)
        check(asked, "the mounted card's poll asked for nothing")

        errs = [e for e in served.errors()
                if 'WebGL' not in e and 'GroupMarker' not in e]
        check(not errs, 'no console errors: ' + '; '.join(errs[:3]))


def scenario_late_card_response_cannot_restore_old_focus():
    """A board response held until after blur must not reopen its card."""
    served = live_app()
    if served is None:
        return
    from services import storage
    storage.shopping_lists_table.truncate()
    storage.shopping_items_table.truncate()
    storage.add_shopping_list({'id': 'grocery', 'name': 'Groceries', 'is_default': True})
    storage.shopping_items_table.insert({'id': 'late-item', 'name': 'Oat milk',
        'list_id': 'grocery', 'is_checked': False, 'created_at': 1})
    with served.browser() as page:
        # Exercise the page-layer consumer directly; 3D clicks are covered
        # by test_house_live. Hold just the overlay's board request.
        page.route('**/house.js*', lambda route: route.fulfill(
            content_type='application/javascript', body=''))
        page.add_init_script("""(() => {
          const original = window.fetch;
          window.fetch = function (url, opts) {
            if (String(url).includes('api/home_board?widgets=')) {
              return new Promise(resolve => {
                window.__releaseBoard = body => resolve(new Response(body,
                  {status:200, headers:{'Content-Type':'application/json'}}));
              });
            }
            return original.apply(this, arguments);
          };
        })();""")
        page.goto(served.url('house?quality=low'))
        page.wait_for_function('window.Alpine && window.Alpine.$data(document.getElementById("overlay-tile"))')
        payload = page.request.get(served.url('api/home_board?widgets=shopping_list')).text()
        _focus(page, 'board')
        page.wait_for_function('typeof window.__releaseBoard === "function"')
        _focus(page, None)
        page.evaluate('body => window.__releaseBoard(body)', payload)
        page.evaluate('() => new Promise(resolve => setTimeout(resolve, 100))')
        check(not page.is_visible('#focus-overlay'),
              'a late board response must not restore a dismissed card')
        _focus(page, 'board')
        page.wait_for_selector('#focus-overlay', state='visible')
        page.wait_for_function(
            "document.getElementById('focus-overlay').innerText.includes('Oat milk')")
        _focus(page, None)


if __name__ == '__main__':
    scenario_overlay_lives_on_the_real_page()
    scenario_the_real_lean_in_wears_the_card()
    scenario_other_zones_wear_their_cards()
    scenario_leaning_out_stops_the_cards_polling()
    scenario_a_mounted_card_still_polls()
    scenario_late_card_response_cannot_restore_old_focus()
    print("test_kitchen_overlay_live OK")
