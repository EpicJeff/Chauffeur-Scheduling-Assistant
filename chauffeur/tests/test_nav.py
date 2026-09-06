"""Navigation parity: every page reachable one way is reachable every way.

Written after Occasions shipped visible in the desktop bar and absent from the
mobile menu — the link had been inserted after the first `<a href="errands">`
in the file, which is the DESKTOP one, so the new entry landed in the wrong
list AND duplicated a desktop row. Nothing caught it because nothing compared
the two menus.

The cause was two hand-maintained copies of the same list. The wall-panel arc
would have made it three (desktop bar, mobile menu, panel shelf), so nav.html
now carries ONE `NAV_ITEMS` list and loops it three times. That kills the
divergence this file was written to catch — so these scenarios moved up a
level and now guard the thing that replaced it:

  - the single list is complete and well-formed (every field every renderer
    reads),
  - all three renderers actually loop it, rather than one of them quietly
    growing a hardcoded copy again,
  - every destination is servable and filterable,
  - and the kiosk still hides every settings surface, which is the one rule
    that keeps a wall display from being a configuration console.

Run from chauffeur/:  python tests/test_nav.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NAV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates', 'nav.html')

BODY = open(NAV, encoding='utf-8').read()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _items():
    """The NAV_ITEMS entries, parsed out of the Jinja literal."""
    block = BODY[BODY.index('{% set NAV_ITEMS'):BODY.index("{% set _path")]
    items = []
    for chunk in re.findall(r"\{'slug':(.*?)\]\}", block, re.S):
        entry = {}
        for key in ('slug', 'href', 'label', 'short', 'match'):
            m = re.search(r"'%s': '([^']+)'" % key, "{'slug':" + chunk)
            if m:
                entry[key] = m.group(1)
        entry['paths'] = re.findall(r"'(M[^']+)'", chunk)
        items.append(entry)
    return items


def scenario_the_item_list_is_complete():
    """Every renderer reads every field. A missing `short` renders an empty
    shelf button — a 32px icon with nothing under it, on the surface with the
    least room to be ambiguous."""
    items = _items()
    check(len(items) >= 10, f"only parsed {len(items)} nav items — the list moved?")
    for it in items:
        for key in ('slug', 'href', 'label', 'short', 'match'):
            check(it.get(key), f"nav item {it.get('slug') or it} has no {key}")
        check(it['paths'], f"nav item {it['slug']} has no icon path")


def scenario_no_item_is_listed_twice():
    """The slip that hid Occasions on mobile also duplicated it on desktop —
    one bad insertion produced both symptoms."""
    for key in ('slug', 'href'):
        seen = [it[key] for it in _items()]
        dupes = {v for v in seen if seen.count(v) > 1}
        check(not dupes, f"NAV_ITEMS repeats {key}: {sorted(dupes)}")


def scenario_all_three_renderers_loop_the_list():
    """The point of the refactor. If a renderer stops deriving its links from
    NAV_ITEMS, it has grown its own copy again and the divergence is back.

    The shelf loops SHELF_ITEMS rather than NAV_ITEMS directly — it is the same
    list, ordered and filtered by the server so the buttons do not shuffle
    after the page paints — so what matters is that it is BUILT from NAV_ITEMS
    in the same breath."""
    for anchor, what in (('id="top-nav-bar"', 'desktop bar'),
                         ('id="mobile-menu"', 'mobile menu'),
                         ('id="panel-shelf"', 'panel shelf')):
        check(anchor in BODY, f"the {what} is gone")
        section = BODY[BODY.index(anchor):]
        # the next renderer's anchor bounds this one
        ends = [section.index(a) for a in ('id="mobile-menu"', 'id="panel-shelf"', '<script>')
                if a in section and section.index(a) > 0]
        section = section[:min(ends)] if ends else section
        if what == 'panel shelf':
            # The shelf builds a `SHELF_ITEMS` list of its own until
            # v2.193.0, when boards joined it: it now loops ONE server-resolved
            # order (`shelf_order`, which carries `board:<slug>` entries too)
            # and looks each slug up in NAV_ITEMS. Two loops over two orders is
            # exactly how the boards ended up in a position the panel profile
            # did not know about — see test_board_pages.
            check('{% for slug in _order %}' in section,
                  "the shelf no longer renders one server-resolved order")
            check('for item in NAV_ITEMS if item.slug == slug' in section,
                  "the shelf no longer resolves its slugs against NAV_ITEMS — "
                  "hardcoded copy?")
        else:
            check('{% for item in NAV_ITEMS %}' in section,
                  f"the {what} does not loop NAV_ITEMS — hardcoded copy?")


def scenario_the_shelf_arrives_in_its_final_order():
    """Reported from the wall: the shelf buttons reorder after the page loads,
    so you watch them jump.

    v2.119.0 made the order real but applied it in JavaScript, once the panel
    profile arrived — which is a rearrangement the family sees. The server
    already knows the answer (`shelf_order` is the same `resolve_tabs` the
    profile endpoint returns), so the first byte is already correct."""
    import main
    check('shelf_order' in main.templates.env.globals,
          "the template can no longer ask the server for the shelf order, so "
          "the order is back to being applied after the paint")
    check('{% set _order = shelf_order(request) %}' in BODY,
          "nav.html does not resolve the shelf order at render time")
    ordered = BODY.index('{% set _order = shelf_order(request) %}')
    rendered = BODY.index('{% for slug in _order %}')
    check(ordered < rendered, "the shelf is rendered before it is ordered")


def scenario_every_nav_page_has_a_route():
    """A link to a page the app does not serve is a 404 with a friendly icon."""
    import main
    routes = {r.path.strip('/') for r in main.app.routes if hasattr(r, 'path')}
    for it in _items():
        check(it['href'] in routes,
              f"nav links to '{it['href']}' but nothing serves it")


def scenario_the_bare_address_lands_on_the_board():
    """An address with nothing after it is asking "what is going on", which is
    the board's whole job — the driver schedule was the right answer only when
    it was the whole app. The query string has to survive the redirect or a
    panel pointed at the bare host arrives as an ordinary web page."""
    import main
    import inspect
    src = inspect.getsource(main.root_redirect)
    check('"home"' in src or "'home'" in src,
          "the root no longer redirects to the home board")
    check('query' in src,
          "the redirect drops the query string, so ?panel=true is lost")


def scenario_the_home_board_is_in_the_nav():
    """The shelf drops the wordmark, so Home stops being a logo and has to be
    a destination. Named explicitly: a parity check passes just as happily
    when every renderer has lost the same entry."""
    slugs = {it['slug'] for it in _items()}
    for slug in ('home', 'occasions'):
        check(slug in slugs, f"'{slug}' is missing from NAV_ITEMS")


ADMIN_ONLY_SLUGS = ('intake', 'mind', 'study', 'threads', 'programs',
                    'work', 'rhythms')


def scenario_every_slug_is_filterable():
    """`?tabs=` only hides links whose slug the panel profile recognises, so a
    content page missing from that vocabulary cannot be filtered off a kiosk
    card or a shelf at all."""
    from services import home_board
    # Five exceptions, every one deliberate: intake (v2.232.0) is mail
    # approvals and IMAP settings, mind (v2.426.13) is dial settings plus the
    # full sensitive insight lane, study (v2.453.0) is that same lane drawn
    # as a room — the evidence board pins insight lines and thread titles,
    # so it is the Mind's own content with a nicer frame — threads
    # (v2.429.8) is vendor/project correspondence, counterparty emails and
    # the odd employment-screening thread, and programs (task 5) is proposing
    # and approving a family member's program. All five are admin surfaces,
    # all five already off DEFAULT_TABS for that reason. A shelf vocabulary
    # with members that are not boards is an exception to explain forever;
    # each keeps its desktop-nav link, it is simply not something a wall
    # panel can show.
    for it in _items():
        if it['slug'] in ADMIN_ONLY_SLUGS:
            check(it['slug'] not in home_board.NAV_SLUGS,
                  f"{it['slug']} is back in the shelf vocabulary — it is an "
                  "admin page, and the shelf is boards")
            continue
        check(it['slug'] in home_board.NAV_SLUGS,
              f"'{it['slug']}' is in the nav but not in home_board.NAV_SLUGS")


def scenario_the_tab_defaults_are_real_slugs():
    """A default that names a slug nothing renders silently shortens the shelf
    on every panel that never set one."""
    from services import home_board
    slugs = {it['slug'] for it in _items()}
    for slug in home_board.DEFAULT_TABS:
        check(slug in slugs, f"DEFAULT_TABS names '{slug}', which the nav does not render")


def scenario_the_kiosk_hides_every_settings_surface():
    """"Kiosk is a display surface: no settings, no control center." Find-a-
    setting shipped without an id and so stayed visible on a wall display —
    a search box for the app's configuration, on the kitchen wall."""
    kiosk = BODY[BODY.index('if (isKiosk) {'):]
    for el in ('settings-nav-item', 'mobile-settings-nav-item',
               'find-setting-nav-item', 'mobile-find-setting-nav-item'):
        check(f"'{el}'" in kiosk, f"kiosk never hides #{el}")
        check(f'id="{el}"' in BODY, f"#{el} is hidden but does not exist")


def scenario_intake_stays_off_shared_screens():
    """Intake is mail approvals and IMAP credentials. It is in the nav for the
    browser and hidden on every kiosk unless a card opts back in."""
    kiosk = BODY[BODY.index('if (isKiosk) {'):]
    check('data-slug="intake"' in kiosk or "'intake'" in kiosk,
          "the kiosk no longer hides intake")


def scenario_mind_stays_off_shared_screens():
    """Mind's admin page carries dial settings and the full insight lane,
    sensitive rows included — the one thing the feature exists to keep off a
    shared screen. It is in the nav for the browser and hidden on every kiosk
    unless a card opts back in, same as intake."""
    check('mind' in ADMIN_ONLY_SLUGS,
          "mind dropped out of the admin-only exception list")
    kiosk = BODY[BODY.index('if (isKiosk) {'):]
    check("'mind'" in kiosk or 'data-slug="mind"' in kiosk,
          "the kiosk no longer hides mind")


def scenario_study_stays_off_shared_screens():
    """The Study draws the Mind's own lane as a room: the evidence board pins
    insight lines and thread titles, and its state endpoint is the same
    parent/adult gate. A room is a friendlier frame, not a weaker one — same
    discipline as intake, mind, threads and programs: nav link for the
    browser, hidden on every kiosk unless a card opts back in."""
    check('study' in ADMIN_ONLY_SLUGS,
          "study dropped out of the admin-only exception list")
    kiosk = BODY[BODY.index('if (isKiosk) {'):]
    check("'study'" in kiosk or 'data-slug="study"' in kiosk,
          "the kiosk no longer hides study")


def scenario_threads_stays_off_shared_screens():
    """Threads carries counterparty emails and the odd employment-screening
    loop — household administration, not something a shared wall display
    should show unread. Same discipline as intake and mind: nav link for the
    browser, hidden on every kiosk unless a card opts back in."""
    check('threads' in ADMIN_ONLY_SLUGS,
          "threads dropped out of the admin-only exception list")
    kiosk = BODY[BODY.index('if (isKiosk) {'):]
    check("'threads'" in kiosk or 'data-slug="threads"' in kiosk,
          "the kiosk no longer hides threads")


def scenario_programs_stays_off_shared_screens():
    """Programs (task 5) is proposing and approving a family member's
    program — household administration, same discipline as intake, mind and
    threads: nav link for the browser, hidden on every kiosk unless a card
    opts back in."""
    check('programs' in ADMIN_ONLY_SLUGS,
          "programs dropped out of the admin-only exception list")
    kiosk = BODY[BODY.index('if (isKiosk) {'):]
    check("'programs'" in kiosk or 'data-slug="programs"' in kiosk,
          "the kiosk no longer hides programs")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} nav scenarios passed")
