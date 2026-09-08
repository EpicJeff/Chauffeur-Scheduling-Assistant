"""The Home's one feed. H1: the house speaks with the kitchen's voice —
same eight sections, same laws, pinned HERE so H2's garage/curb sections
join an already-lawed file.

Spec: docs/superpowers/specs/2026-09-08-house-design.md.
"""
import io
import json
import os
import time

from harness import check
from services import storage, house_room


def _reset():
    storage.shopping_items_table.truncate()
    storage.pets_table.truncate()
    storage.chat_channels_table.truncate()
    storage.chat_messages_table.truncate()
    storage.get_settings = lambda: {}


def scenario_h1_house_speaks_with_the_kitchens_voice():
    _reset()
    storage.get_cached_schedule = lambda: {}
    st = house_room.state(since_ts=time.time())
    check(st['status'] == 'ok', "the empty house still answers ok")
    for zone in ('fridge', 'counter', 'board', 'door', 'calendar', 'radio',
                 'window', 'pet'):
        check(zone in st, f"{zone} section present")
        check(st[zone].get('calm') is True, f"{zone} calm when empty")


def scenario_family_safe_pin():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'house_room.py'),
        encoding='utf-8').read()
    for banned in ('from services import threads', 'import missions',
                   'import mind', 'import watchers', 'import occasions',
                   'mailer', 'send_drafted'):
        check(banned not in src, f"house_room.py never touches {banned}")
    _reset()
    storage.get_cached_schedule = lambda: {}
    blob = json.dumps(house_room.state(since_ts=0)).lower()
    for banned in ('counterparty', 'gift', 'sensitive', 'insight', 'finding'):
        check(banned not in blob, f"state JSON never carries '{banned}'")


def scenario_the_house_never_writes():
    src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'house_room.py'),
        encoding='utf-8').read()
    for verb in ('.insert(', '.update(', '.remove(', 'set_app_state',
                 'add_mission', 'add_finding', 'add_thread'):
        check(verb not in src, f"house_room.py never writes ({verb})")


def scenario_endpoint_and_gate():
    _reset()
    storage.get_cached_schedule = lambda: {}
    import main
    out = main.house_state_api(since=0, request=None)
    check(out['status'] == 'ok' and 'fridge' in out, "the API serves the house")
    auth_src = io.open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'services', 'auth.py'),
        encoding='utf-8').read()
    check("'/api/house/state', WALL_OR_SERVICE" in auth_src,
          "wall DEVICES may read the house (family-safe by construction)")
    check("'/house', ANYONE" in auth_src, "the shell serves anyone")


def scenario_house_template_pins():
    p = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'templates', 'house.html')
    check(os.path.exists(p), "house.html exists")
    src = io.open(p, encoding='utf-8').read()
    check('<title>The Home</title>' in src, "the page says its name")
    check('The Kitchen' not in src, "no leftover kitchen copy")
    check('HOUSE_STATE_URL' in src and 'api/house/state' in src,
          "the page points at the house feed")
    check("static/house.js" in src, "the page loads house.js")
    check("static/kitchen_overlay.js" in src,
          "the overlay is reused verbatim until H4 renames it")
    check('panel-page-title' in src, "one-title-per-page marker present")
    check('chfBase' in src, "state URL rides chfBase, never a self-computed depth")
    for dialog in ('alert(', 'confirm(', 'prompt('):
        check(dialog not in src, f"no browser dialogs ({dialog})")


if __name__ == '__main__':
    scenario_h1_house_speaks_with_the_kitchens_voice()
    scenario_family_safe_pin()
    scenario_the_house_never_writes()
    scenario_endpoint_and_gate()
    scenario_house_template_pins()
    print("test_house_state OK")
