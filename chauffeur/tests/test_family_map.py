"""Tests for the family map locations assembler (main.family_locations).

Run from chauffeur/:  python tests/test_family_map.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="chauffeur_family_map_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage, ha_api  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def _member(mid, name, **kw):
    doc = {"id": mid, "name": name, "color_code": "#3b82f6", "avatar": None,
           "bio": "", "can_drive": False, "is_child": False, "driver_id": None,
           "passenger_id": None, "ha_person_entity": None, "notify_service": None,
           "media_player_entity": None, "pin": None, "created_at": time.time()}
    doc.update(kw)
    storage.add_member(doc)
    return doc


FAKE_STATES = {
    "person.jeff": {"entity_id": "person.jeff", "state": "not_home",
                    "last_updated": "2026-07-31T12:00:00+00:00",
                    "attributes": {"latitude": 40.1, "longitude": -75.2, "gps_accuracy": 12}},
    "person.ben": {"entity_id": "person.ben", "state": "home",
                   "last_updated": "2026-07-31T11:00:00+00:00",
                   "attributes": {}},  # router-based tracker: no coords
}


def scenario_locations_assembly():
    import main
    _member("m1", "Jeff", driver_id="jeff", can_drive=True, ha_person_entity="person.jeff")
    _member("m2", "Ben", is_child=True, ha_person_entity="person.ben")
    _member("m3", "NoHA")

    # Jeff is mid-drive: schedule cache + in-progress leg
    storage.set_cached_schedule({
        "events": [{"id": "evt9", "title": "Soccer Pickup", "start": "2026-07-31T15:00:00"}],
        "assignments": {"evt9": "jeff"},
    })
    storage.mark_drive_status("route_evt9_1", "in_progress")

    with mock.patch.object(ha_api, 'get_state', side_effect=lambda e: FAKE_STATES.get(e)):
        locations = main.family_locations()

    by_id = {l['member_id']: l for l in locations}
    check(len(locations) == 3, "every member returned")

    jeff = by_id["m1"]
    check(jeff["latitude"] == 40.1 and jeff["longitude"] == -75.2, "coords from HA person")
    check(jeff["state"] == "not_home" and jeff["gps_accuracy"] == 12, "state + accuracy")
    check(jeff["driving"] == {"leg_title": "Soccer Pickup"},
          f"en-route enrichment from in-progress leg, got {jeff['driving']}")

    ben = by_id["m2"]
    check(ben["state"] == "home" and ben["latitude"] is None,
          "router-based tracker: state without coords")
    check(ben["driving"] is None, "non-driver has no driving context")

    noha = by_id["m3"]
    check(noha["state"] is None and noha["latitude"] is None, "unmapped member returns nulls")


def scenario_leg_id_collapse():
    import main
    check(main._leg_event_id("init_evt42") == "evt42", "init prefix")
    check(main._leg_event_id("route_evt42_2") == "evt42", "route prefix + index")
    check(main._leg_event_id("final_evt42") == "evt42", "final prefix")
    check(main._leg_event_id("evt42_dropoff") == "evt42_dropoff",
          "leg variants of split events stay distinct")


def scenario_ha_unreachable_degrades():
    import main
    _member("m1", "Jeff", ha_person_entity="person.jeff")
    with mock.patch.object(ha_api, 'get_state', return_value=None):
        locations = main.family_locations()
    check(locations[0]["state"] is None and locations[0]["latitude"] is None,
          "HA down -> nulls, no exception")


def scenario_the_drive_sheets_own_fix_puts_a_driver_on_the_map():
    """A household with no Home Assistant companion app was simply absent
    from their own map. The drive sheet reports a position while somebody is
    driving, and that is enough to draw them — second source, never a
    replacement: a member WITH a live HA tracker keeps it."""
    import main
    reset_db()
    _member("m1", "Jeff", driver_id="jeff", can_drive=True)      # no HA entity
    _member("m2", "Amy", ha_person_entity="person.jeff")         # HA-tracked
    storage.set_member_position("m1", 40.5, -75.9, 18, time.time())
    storage.set_member_position("m2", 1.0, 1.0, 18, time.time())

    with mock.patch.object(ha_api, 'get_state', side_effect=lambda e: FAKE_STATES.get(e)):
        by_id = {l['member_id']: l for l in main.family_locations()}

    check(by_id["m1"]["latitude"] == 40.5 and by_id["m1"]["longitude"] == -75.9,
          f"the app's own fix draws the untracked driver, got {by_id['m1']}")
    check(by_id["m1"]["last_updated"], "and carries a timestamp like any other")
    check(by_id["m2"]["latitude"] == 40.1,
          "a live HA tracker still wins for the member who has one")


def scenario_the_map_stays_under_overlays():
    """Leaflet's panes/controls carry z-index 400–1000 and escape into the
    page whenever no ancestor forms a stacking context. The hearth's
    clip-playing mode strips every backdrop-filter (Pi video decode), which
    removed the accidental stacking context that had contained them — so
    VIDEOS in the moments overlay slid behind the map tile while photos sat
    on top. The map container must isolate itself, so its z-order can never
    depend on what the page around it is doing."""
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    core = open(_os.path.join(root, 'templates', 'components',
                              'family_map_core.html'), encoding='utf-8').read()
    check("el.style.isolation = 'isolate'" in core
          and core.index("isolation = 'isolate'") < core.index('L.map(el'),
          "the map container no longer isolates its stacking context — "
          "Leaflet floats over overlays whenever backdrop-filters stand down")
    # The container was only half of it: the map TILE's own chrome (the ⌖
    # button and the empty-note chip) rides z-[500] OUTSIDE the Leaflet
    # container, and the wrapper is rebuilt by x-html on every poll — so the
    # containment must live in the template, not in post-render JS.
    tile = open(_os.path.join(root, 'templates', 'components',
                              'board_tile_body.html'), encoding='utf-8').read()
    import re as _re
    wrapper = _re.search(r'x-if="t\.type === \'map\' && !t\.data\.empty">.*?<div class="([^"]*)"',
                         tile, _re.S)
    check(wrapper and 'isolate' in wrapper.group(1),
          "the map tile wrapper lost its isolate class — the ⌖ and chips "
          "float over overlays again after every poll")
    # And a HOSTED card is somebody else's DOM: HA's own map card ships its
    # own Leaflet. Every cell the host dresses must isolate too.
    host = open(_os.path.join(root, 'static', 'ha_card_host.js'),
                encoding='utf-8').read()
    check(host.count("container.style.isolation = 'isolate'") >= 3,
          "a hosted-card cell no longer isolates — an embedded HA map card "
          "floats over the page's overlays")


SCENARIOS = [
    scenario_locations_assembly,
    scenario_the_drive_sheets_own_fix_puts_a_driver_on_the_map,
    scenario_leg_id_collapse,
    scenario_ha_unreachable_degrades,
    scenario_the_map_stays_under_overlays,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            reset_db()
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
