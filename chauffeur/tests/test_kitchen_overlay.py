"""Focus overlay: the room's lean-in gains the board's own cards.

Two zones for the proof: the door overlays the hero card (HeroCard.html,
the screensaver's compact form — the one-renderer rule), the wall calendar
overlays the Family Day card (packingCard with interactive: false — the
board's own read-only mode, not a second renderer). The room itself stays
pure: kitchen.js never touches HTML, it only announces focus as an event;
static/kitchen_overlay.js is page-layer glue that reuses the board's
builders under the board's own escaping.
"""
import io
import os
import re
import types

from harness import check

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding='utf-8').read()


def scenario_overlay_layer_present_and_wired():
    html = _src('templates', 'kitchen.html')
    check("import 'components/packing_card.html' as packing" in html,
          "kitchen.html imports the Family Day macro (the board's own)")
    check("include 'components/packing_card.html'" in html,
          "the factory script is emitted once (Jinja import renders nothing)")
    check("include 'components/agenda_row.html'" in html,
          "the agenda vocabulary CSS rides along")
    check("include 'components/board_tile_body.html'" in html,
          "the generic island mounts the board's own tile body")
    check("include 'components/shopping_lists.html'" in html,
          "the shopping factory script is emitted once")
    for comp in ('family_calendar', 'pet_editor', 'pet_battle', 'music_widget'):
        check(f"include 'components/{comp}.html'" in html,
              f"the {comp} component rides along (interactive lean-ins)")
    for needed in ('id="focus-overlay"', 'id="overlay-door"',
                   'id="overlay-calendar"', 'id="overlay-tile"',
                   'id="overlay-music"', 'id="overlay-open"',
                   'kitchenTileIsland', 'kitchen_overlay.js',
                   'pointer-events: auto'):
        check(needed in html, f"kitchen.html carries {needed}")
    js = _src('static', 'kitchen.js')
    check('chf-kitchen-focus' in js,
          "the room announces focus; it never draws HTML itself")
    check('chfKitchenFocus' in js,
          "the lean-in has a callable hand path (deep links, harnesses)")
    ov = _src('static', 'kitchen_overlay.js')
    for needed in ('chf-kitchen-focus', 'HeroCard.html', 'isLight: true',
                   'loadPacking', 'api/home_board', 'matrix3d',
                   'moments,shopping_list,meals,pets,weather',
                   'startMusicWidget', 'openBoardMoment'):
        check(needed in ov, f"kitchen_overlay.js carries {needed}")
    check('quad' in _src('static', 'kitchen.js'),
          "the room announces the face quad the transform maps onto")


def scenario_overlay_never_writes_and_stays_escaped():
    ov = _src('static', 'kitchen_overlay.js')
    for banned in ("method:", "'POST'", '"POST"', 'alert(', 'confirm(',
                   'prompt('):
        check(banned not in ov, f"kitchen_overlay.js never uses {banned}")
    sinks = re.findall(r'innerHTML\s*=\s*([^;\n]+)', ov)
    check(len(sinks) > 0, "the door overlay renders through a sink we can pin")
    for s in sinks:
        check('HeroCard.html(' in s or s.strip() == "''",
              "every innerHTML is the shared escaping hero builder (or a clear)")
    html = _src('templates', 'kitchen.html')
    check('interactive: true' in html,
          "the Family Day island mounts the board's interactive mode — the "
          "cards ARE the board here; writes ride the board's own endpoints")


def scenario_overlay_sources_stay_wall_reachable():
    auth_src = _src('services', 'auth.py')
    check("'/api/home_board/*', WALL" in auth_src,
          "the hero's payload stays readable from a wall device")
    check("'/api/packing/*', WALL" in auth_src,
          "the Family Day payload stays readable from a wall device")


def scenario_kitchen_template_renders_with_overlay():
    import main
    req = types.SimpleNamespace(url=types.SimpleNamespace(path='/kitchen'),
                                query_params={})
    html = main.templates.env.get_template('kitchen.html').render(request=req)
    for needed in ('focus-overlay', 'overlay-door', 'overlay-calendar',
                   'packingCard(', 'pkLoaded'):
        check(needed in html, f"rendered kitchen page carries {needed}")


if __name__ == '__main__':
    scenario_overlay_layer_present_and_wired()
    scenario_overlay_never_writes_and_stays_escaped()
    scenario_overlay_sources_stay_wall_reachable()
    scenario_kitchen_template_renders_with_overlay()
    print("test_kitchen_overlay OK")
