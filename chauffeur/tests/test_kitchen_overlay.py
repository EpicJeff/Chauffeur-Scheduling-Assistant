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
    for comp in ('family_calendar', 'pack_dialog', 'pet_editor', 'pet_battle',
                 'music_widget'):
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
    check('zoneFaceNormal' in js,
          "card zones lean in FACE-ON (oblique cards break the illusion)")
    check('.bg-gray-900' in html,
          "the paper reskin covers the pack panel's dark constants")
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


def scenario_the_study_card_is_pin_scoped_and_text_only():
    """The study's lean-in card (v2.499.158). Its rows are built off the
    furniture the house fetched with the parent's own visit token -- never
    off api/home_board, which a wall device reads without a person -- and
    every family-typed word lands through textContent. The room's painted
    detail layer, which study.js never handed to the house before, stands
    up only for a zone that wears no card."""
    html = _src('templates', 'house.html')
    check('id="overlay-study"' in html, "house.html carries the study card surface")
    check('#overlay-study' in html, "the study surface starts hidden like its siblings")
    check('overlay-study' not in _src('templates', 'kitchen.html'),
          "the kitchen page carries no study surface (the branch is inert there)")
    ov = _src('static', 'kitchen_overlay.js')
    for needed in ('overlay-study', 'chfStudyCard', 'renderStudy', '/^study_/',
                   "study_tray: 'intake'", 'study_board: { mode', "study_map: 'trips'",
                   'card.empty'):
        check(needed in ov, f"kitchen_overlay.js carries {needed}")
    tiles = re.search(r'var ZONE_TILES = \{(.*?)\};', ov, re.S)
    check(tiles and 'study' not in tiles.group(1),
          "study zones never wear a board tile (the board payload is wall-readable)")
    body = re.search(r'function renderStudy\(card\) \{(.*?)\n  \}\n', ov, re.S)
    check(body, "the study renderer is where the pin expects it")
    for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'fetch('):
        check(banned not in body.group(1), f"renderStudy never uses {banned}")
    check(body.group(1).count('.textContent = ') >= 4,
          "every word on the study card lands through textContent")
    hs = _src('static', 'house_study.js')
    for needed in ('card:card', 'focus:focus', 'face:face', 'detailState:detailState',
                   'built.detail.paint', 'built.detail.show', 'built.data(', 'built.summary('):
        check(needed in hs, f"house_study.js carries {needed}")
    check('innerHTML' not in hs, "house_study.js is data and geometry, never markup")
    sj = _src('static', 'study.js')
    check('detail: { paint: detailPaint, show: detailShow }' in sj,
          "study.js hands its detail layer to the embed host")
    check('tick: t => stepGraph(t)' in sj, "study.js hands the monitor graph's tick to the host")
    check('glass: sky' in sj, "the window names its pane as the face a card hangs on")
    check('m.material.map = t; m.material.needsUpdate = true;' in sj,
          "a panel paints the mesh's CURRENT material (the house clones them per zone)")
    check('mat.map = t' not in sj, "no paint writes to the captured original material")
    house = _src('static', 'house.js')
    for needed in ('window.chfStudyCard', 'window.chfStudyDetail',
                   'webgl.studyWorld.focus(key)', 'webgl.studyWorld.face(key)',
                   'webgl.studyWorld.tick(', 'study_tray: 0.7',
                   "calc(var(--panel-shelf-h, 0px) + 64px)"):
        check(needed in house, f"house.js carries {needed}")


if __name__ == '__main__':
    scenario_overlay_layer_present_and_wired()
    scenario_overlay_never_writes_and_stays_escaped()
    scenario_overlay_sources_stay_wall_reachable()
    scenario_kitchen_template_renders_with_overlay()
    scenario_the_study_card_is_pin_scoped_and_text_only()
    print("test_kitchen_overlay OK")
