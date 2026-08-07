"""Navigation parity: every page reachable on desktop is reachable on a phone.

Written after Occasions shipped visible in the desktop bar and absent from the
mobile menu — the link had been inserted after the first `<a href="errands">`
in the file, which is the DESKTOP one, so the new entry landed in the wrong
list AND duplicated a desktop row. Nothing caught it because nothing compared
the two menus.

`nav.html` carries two independent copies of the navigation (a horizontal bar
for `md:` and up, and a `#mobile-menu` panel below it). Two hand-maintained
copies of the same list is a divergence waiting to happen, and this is the
cheap guard: whatever is in one must be in the other.

Run from chauffeur/:  python tests/test_nav.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

NAV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates', 'nav.html')

# Links that legitimately live in only one of the two menus. Anything else
# appearing here should be justified in a comment, not just silenced.
DESKTOP_ONLY = set()
MOBILE_ONLY = set()


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _menus():
    body = open(NAV, encoding='utf-8').read()
    split = body.index('id="mobile-menu"')
    desktop, mobile = body[:split], body[split:]
    grab = lambda s: [m for m in re.findall(r'<a\s+href="([^"#?]+)"', s)
                      if not m.startswith(('http', '/', '{'))]
    return grab(desktop), grab(mobile)


def scenario_every_page_is_in_both_menus():
    desktop, mobile = _menus()
    d, m = set(desktop), set(mobile)
    missing_mobile = d - m - DESKTOP_ONLY
    missing_desktop = m - d - MOBILE_ONLY
    check(not missing_mobile,
          f"on desktop but not reachable on a phone: {sorted(missing_mobile)}")
    check(not missing_desktop,
          f"on mobile but not on desktop: {sorted(missing_desktop)}")


def scenario_no_menu_repeats_a_link():
    """The same slip that hid Occasions on mobile also duplicated it on
    desktop — one bad insertion produces both symptoms, so both are checked."""
    desktop, mobile = _menus()
    for name, links in (('desktop', desktop), ('mobile', mobile)):
        dupes = {h for h in links if links.count(h) > 1}
        check(not dupes, f"{name} nav lists these twice: {sorted(dupes)}")


def scenario_occasions_and_find_a_setting_are_both_present():
    """The two pages this arc added, named explicitly: a generic parity check
    passes just as happily when BOTH menus have lost an entry."""
    desktop, mobile = _menus()
    for page in ('occasions', 'settings'):
        check(page in desktop, f"{page} missing from the desktop bar")
        check(page in mobile, f"{page} missing from the mobile menu")


def scenario_every_nav_page_has_a_route():
    """A link to a page the app does not serve is a 404 with a friendly icon."""
    import main
    desktop, mobile = _menus()
    routes = {r.path.strip('/') for r in main.app.routes if hasattr(r, 'path')}
    for page in sorted(set(desktop) | set(mobile)):
        check(page in routes, f"nav links to '{page}' but nothing serves it")


# Admin surfaces the kiosk hides WHOLESALE by element id (`isKiosk` → "no
# settings, no control center"), never through the `?tabs=` slug map. They are
# absent from SLUGS on purpose, and adding them would make them selectable on a
# wall display.
KIOSK_HIDDEN_BY_ID = {'config', 'settings'}


def scenario_the_kiosk_slug_map_knows_every_content_page():
    """`?tabs=` only hides links whose slug it recognises, so a content page
    missing from the map cannot be filtered off a kiosk card at all."""
    body = open(NAV, encoding='utf-8').read()
    slugs = dict(re.findall(r"'([a-z_0-9]+)':\s*'([a-z_0-9]+)'", body))
    desktop, mobile = _menus()
    for page in sorted((set(desktop) | set(mobile)) - KIOSK_HIDDEN_BY_ID):
        check(page in slugs, f"'{page}' is not in the kiosk SLUGS map")


def scenario_the_kiosk_hides_every_settings_surface():
    """"Kiosk is a display surface: no settings, no control center." Find-a-
    setting shipped without an id and so stayed visible on a wall display —
    a search box for the app's configuration, on the kitchen wall."""
    body = open(NAV, encoding='utf-8').read()
    kiosk = body[body.index('if (isKiosk) {'):]
    for el in ('settings-nav-item', 'mobile-settings-nav-item',
               'find-setting-nav-item', 'mobile-find-setting-nav-item'):
        check(f"getElementById('{el}')" in kiosk,
              f"kiosk never hides #{el}")
        check(f'id="{el}"' in body, f"#{el} is hidden but does not exist")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} nav scenarios passed")
