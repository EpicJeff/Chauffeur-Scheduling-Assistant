"""The two whole-feature switches: critters and rewards (household_features).

What the family asked for: a switch that hides the critter game from the wall
and the app entirely, and one that takes the rewards store away for a while.
Three promises, each run for real rather than read off the source:

  * OFF HIDES EVERYWHERE. The figure loses its companion, the member payload
    loses its pet keys, the tiles vanish, the rooms lose their laptop, the
    pages lose their doors, the routes refuse, and Argyle says it is off.
  * OFF NEVER TAKES. Pets, xp, rewards and pledges survive; a parent can still
    tidy the catalog and decide a request that was already waiting; a child
    can still withdraw a pledge (that gives points back).
  * ON IS EXACTLY BEFORE. Flip it back and every pet and reward is there.

Run from chauffeur/:  python tests/test_household_features.py
"""
import asyncio
import atexit
import os
import shutil
import sys
import tempfile
import time
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_features_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import household_features as hf  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage.patch_settings({'kid_quiet_start': '00:00', 'kid_quiet_end': '00:00'})


def _switch(**flags):
    storage.patch_settings(flags)


def _family():
    for mid, nm, role in (("k1", "Ada", "child"), ("k2", "Ben", "child"),
                          ("mom", "Mom", "parent")):
        storage.add_member({"id": mid, "name": nm, "role": role,
                            "color_code": "#3b82f6", "is_child": role == "child",
                            "created_at": time.time()})
    storage.adjust_points("k1", 200, "seed")


def _gate(path_template, method='GET'):
    """Run the app's global feature dependency the way FastAPI does: after
    routing, with the route TEMPLATE in scope."""
    import main
    from starlette.requests import Request
    route = type('R', (), {'path': path_template})()
    req = Request({'type': 'http', 'method': method, 'path': path_template,
                   'headers': [], 'query_string': b'', 'scheme': 'http',
                   'server': ('testserver', 80), 'root_path': '',
                   'route': route})
    try:
        asyncio.run(main._feature_gate(req))
        return None
    except Exception as exc:
        return exc


def _page(name, path, query=''):
    import main
    from starlette.requests import Request
    req = Request({'type': 'http', 'method': 'GET', 'path': path,
                   'query_string': query.encode('utf-8'), 'headers': [],
                   'app': main.app, 'router': main.app.router})
    return getattr(main, name)(req).body.decode('utf-8')


# --- defaults ----------------------------------------------------------------

def test_both_default_on():
    reset_db()
    check(hf.snapshot() == {'critters': True, 'rewards': True},
          "a household that never saw the switches must keep both features")
    check(_gate('/api/pets') is None and _gate('/api/rewards/{reward_id}/redeem', 'POST') is None,
          "the gate refused with both switches at their defaults")


def test_registered_on_the_chores_page():
    from services import settings_registry as reg
    rows = {e['key']: e for e in reg.ENTRIES}
    for key in ('critters_enabled', 'rewards_enabled'):
        check(key in rows and rows[key]['page'] == 'chores',
              "%s is not indexed on the chores page" % key)
    from models.schemas import Settings
    s = Settings()
    check(s.critters_enabled is True and s.rewards_enabled is True,
          "the model defaults are not ON")


# --- critters off -------------------------------------------------------------

def test_critters_off_hides_and_keeps():
    import main
    from services import avatar_render, home_board, kitchen_room
    reset_db()
    _family()
    pet = storage.create_pet("k1", "Rocket", {'body': 'wedge', 'top': 'horns'}, {}, 'ember')['pet']
    storage.grant_pet_xp("k1", 40, 'grant')
    member = storage.get_member("k1")

    on_payload = main._public_member(member) if hasattr(main, '_public_member') else None
    _switch(critters_enabled=False)
    check(not hf.critters_enabled(), "the switch did not read back off")

    # the routes
    for path, method in (('/api/pets', 'GET'), ('/api/pets/{pet_id}', 'GET'),
                         ('/api/pets/battle', 'POST'), ('/api/pets/xp/adjust', 'POST')):
        exc = _gate(path, method)
        check(exc is not None and getattr(exc, 'status_code', None) == 404,
              "%s %s still answers with critters off" % (method, path))
    check(_gate('/api/chores') is None, "the critter switch reached an unrelated route")

    # the figure: no companion composited, and the cache noticed the flip
    check(avatar_render._companion("k1") == '', "the critter still stands beside its owner")
    check(avatar_render._companion_key("k1") == '-', "the figure cache would serve the old critter")

    # the member payload every surface keys its pet doors on
    if on_payload is not None:
        off = main._public_member(member)
        for k in ('pet_id', 'pet_name', 'pet_xp', 'pet_hint'):
            check(k not in off, "member payload still carries %s" % k)
    check(main._pet_door("k1") == {'pet_id': None, 'pet_name': None},
          "the avatar editor still gets a critter door")

    # tiles, catalog, rooms
    check(home_board._tile_pets(None) is None, "the pets tile still draws")
    pets_meta = next(w for w in home_board.catalog()['widgets'] if w['key'] == 'pets')
    check(pets_meta.get('available') is False and 'critters' in (pets_meta.get('requires') or ''),
          "the tile palette still offers pets as if they were on")
    room = kitchen_room._pet()
    check(room.get('calm') and not room.get('pets'), "the kitchen still reports critters")

    # Argyle, both stacks (v1 handlers delegate to these)
    from services import agent_tools_v2 as v2
    for res in (v2.get_pet_status(), v2.award_pet_xp("Ada", 5),
                v2.challenge_pet_battle("Ada", "Ben")):
        check('switched off' in res.get('message', ''), "Argyle acted with critters off: %s" % res)

    # NOTHING TAKEN: the pet and its xp are untouched, and xp still mints
    check(storage.get_pet(pet['id']) is not None, "switching off deleted the pet")
    before = storage.get_pet_xp_balance("k1")
    storage.grant_pet_xp("k1", 5, 'grant')
    check(storage.get_pet_xp_balance("k1") == before + 5, "xp stopped adding up while off")

    # ON AGAIN is exactly before
    _switch(critters_enabled=True)
    check(_gate('/api/pets') is None, "the routes did not come back")
    check(avatar_render._companion("k1") != '', "the critter did not come back to its owner")
    check(main._pet_door("k1")['pet_id'] == pet['id'], "the editor door did not come back")
    check(home_board._tile_pets(None) is not None, "the pets tile did not come back")


def test_critters_off_pages_have_no_doors():
    reset_db()
    _family()
    _switch(critters_enabled=False)
    app = _page('driver_app', '/app')
    check('window.chfFeatures = {"critters": false' in app,
          "the PWA head does not carry the switch")
    check('window.openPetEditor' not in app and 'window.openPetBattle' not in app,
          "the PWA still ships the critter editor/arena")
    check('id="btn-pet"' not in app, "the PWA header still has the critter door")
    home = _page('home_board_page', '/home', 'panel=true')
    check('window.openPetEditor' not in home, "the wall still ships the critter editor")
    _switch(critters_enabled=True)
    app = _page('driver_app', '/app')
    check('window.openPetEditor' in app and 'id="btn-pet"' in app,
          "switching back on did not bring the PWA doors back")


# --- rewards off ---------------------------------------------------------------

def _rewards():
    storage.add_reward({"id": "plain", "title": "Ice cream", "description": "",
                        "cost": 30, "pooled": False, "min_share": 0,
                        "created_at": time.time()})
    storage.add_reward({"id": "goal", "title": "Movie Night", "description": "",
                        "cost": 150, "pooled": True, "min_share": 0,
                        "created_at": time.time()})


def test_rewards_off_closes_the_shop_and_keeps_the_stock():
    import main
    from services import home_board
    reset_db()
    _family()
    _rewards()
    check(storage.contribute_to_pool("goal", "k1", 50) == ("ok", 50), "seed pledge")
    check(storage.request_redemption("plain", "k1") not in (None, 'missing', 'insufficient'),
          "seed request")
    _switch(rewards_enabled=False)

    # the family's view is empty; the catalog editor still sees the stock
    check(main.list_rewards() == [], "the store is still open to the family")
    check(len(main.list_rewards(manage=True)) == 2, "the catalog editor lost the stock")

    # the asks refuse; giving points back and deciding never do
    for path in ('/api/rewards/{reward_id}/redeem', '/api/rewards/{reward_id}/contribute'):
        exc = _gate(path, 'POST')
        check(exc is not None and getattr(exc, 'status_code', None) == 409,
              "%s still accepts asks with rewards off" % path)
    for path in ('/api/rewards/{reward_id}/withdraw', '/api/redemptions/{redemption_id}/decide',
                 '/api/rewards', '/api/rewards/{reward_id}/pool/decide'):
        check(_gate(path, 'POST') is None, "%s was closed with the shop" % path)

    # the wall
    check(home_board._tile_chores_goals(None) is None, "the family-goals card still draws")
    lanes = home_board._tile_chores_lanes(None)
    check(lanes and lanes['parts']['rewards'] is False and lanes['parts']['goals'] is False,
          "the lanes still offer rewards/goals: %s" % (lanes or {}).get('parts'))
    check(lanes['parts']['available'] is True, "the lanes lost their chores with the shop")
    goals_meta = next(w for w in home_board.catalog()['widgets'] if w['key'] == 'chores_rewards')
    check(goals_meta.get('available') is False, "the palette still offers family goals")

    # Argyle
    from services import agent_tools_v2 as v2
    check('switched off' in v2.get_family_goals().get('message', ''), "Argyle listed goals")
    res = v2.contribute_to_family_goal("Movie Night", 10, member_name="Ada")
    check('switched off' in res.get('message', ''), "Argyle pledged with rewards off: %s" % res)

    # NOTHING TAKEN
    check(len(storage.get_rewards()) == 2, "switching off deleted rewards")
    check(storage.get_pool_contributions(reward_id="goal"), "switching off dropped the pledge")
    check(storage.get_redemptions(state='pending'), "switching off dropped the waiting request")

    _switch(rewards_enabled=True)
    check(len(main.list_rewards()) == 2, "the store did not reopen")
    check(home_board._tile_chores_goals(None) is not None, "the goals card did not come back")


def test_flipping_a_switch_reloads_the_walls():
    import main
    from fastapi import BackgroundTasks
    from models.schemas import Settings
    reset_db()
    main.LAST_PROFILE_TIME = 0.0
    orig = main.trigger_background_refresh
    main.trigger_background_refresh = lambda *a, **k: None
    try:
        main.update_settings(Settings(rewards_enabled=False), BackgroundTasks())
        check(main.LAST_PROFILE_TIME > 0, "walls were not told to reload onto the new shape")
        main.LAST_PROFILE_TIME = 0.0
        main.update_settings(Settings(rewards_enabled=False), BackgroundTasks())
        check(main.LAST_PROFILE_TIME == 0.0, "a save that changed nothing reloaded every wall")
    finally:
        main.trigger_background_refresh = orig
        _switch(rewards_enabled=True)


def test_chores_page_carries_both_switches():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, 'templates', 'chores.html'), encoding='utf-8').read()
    check('x-model="features.critters_enabled"' in src and
          'x-model="features.rewards_enabled"' in src,
          "the chores page has no hand path for the switches")
    check('id="rewards"' in src, "the registry's rewards anchor has nowhere to land")


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print("  ok   %s" % t.__name__)
        except Exception:
            failed += 1
            print("  FAIL %s" % t.__name__)
            traceback.print_exc()
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
