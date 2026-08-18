"""Avatar slots, the unlock ledger, and the rules that must never bend.

Run from chauffeur/:  python tests/test_avatars.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import time
import traceback
from datetime import date, timedelta

_TMP = tempfile.mkdtemp(prefix="chauffeur_avatars_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import avatar_catalog as cat  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def _member(mid, name="Kid", role="child"):
    storage.add_member({"id": mid, "name": name, "role": role,
                        "color_code": "#3b82f6", "is_child": role == "child",
                        "created_at": time.time()})


def _routine(rid, member_id, title="Teeth", days=None):
    storage.add_routine({"id": rid, "member_id": member_id, "title": title,
                         "time_of_day": None, "days_of_week": days or [],
                         "created_at": time.time()})


# --- the two rules ------------------------------------------------------

def scenario_identity_is_free():
    """Every piece a person uses to say 'this is me' costs nothing. Hair,
    faces, glasses, and the cultural/medical pieces especially."""
    free = {(i['slot'], i['key']) for i in cat.free_items()}
    for key in ('LongHairCurly', 'ShortHairDreads01', 'NoHair', 'Hijab',
                'Turban', 'Eyepatch'):
        check(('top', key) in free, f"{key} must be free (identity)")
    for key in ('Prescription01', 'Round', 'Sunglasses'):
        check(('eyewear', key) in free, f"eyewear {key} must be free")
    for key in ('BeardLight', 'MoustacheFancy'):
        check(('facial_hair', key) in free, f"facial hair {key} must be free")
    # ...and everyone starts dressed.
    for slot in ('clothes', 'bottoms', 'shoes', 'top'):
        check(any(s == slot for s, _ in free), f"{slot} needs a free option")

    # Decoration, by contrast, is earned.
    unlock = {(i['slot'], i['key']) for i in cat.unlockable_items()}
    check(('top', 'WinterHat1') in unlock, "novelty hats are earned")
    check(all(s == 'graphic' for s, _ in unlock if s == 'graphic'), "graphics earned")
    check(not any(s == 'graphic' for s, _ in free), "no graphic is free")


def scenario_unlock_is_never_lost():
    """Append-only. Losing routines, deleting checks, or a bad day must never
    take back a piece already earned."""
    _member("kid")
    _routine("r1", "kid")
    today = date.today()
    for off in range(0, 30):
        storage.set_routine_check("r1", "kid", (today - timedelta(days=off)).isoformat(), True)

    fresh = storage.sync_avatar_unlocks("kid")
    check(fresh, "a 30-completion member unlocks something")
    owned = set(storage.get_avatar_unlocks("kid"))
    check(cat.item_id('top', 'Hat') in owned, "Hat (20 completions) earned")
    check(cat.item_id('bottoms', 'Shorts') in owned, "Shorts (10) earned")

    # Wipe the evidence entirely.
    storage.delete_routine("r1")
    check(storage.count_routine_completions("kid") >= 30,
          "the completion total is a high-water mark")
    still = set(storage.get_avatar_unlocks("kid"))
    check(owned <= still, "nothing was revoked when the routine vanished")
    check(not storage.sync_avatar_unlocks("kid"), "re-sync grants nothing twice")


def scenario_grant_is_idempotent():
    _member("kid")
    iid = cat.item_id('neck', 'Chain')
    check(storage.grant_avatar_unlock("kid", iid, 'grant'), "first grant sticks")
    check(not storage.grant_avatar_unlock("kid", iid, 'grant'), "second is a no-op")
    check(storage.get_avatar_unlocks("kid").count(iid) == 1, "exactly one row")


def scenario_backfill_never_starts_you_behind():
    """Somebody who was here before avatars existed already earned things."""
    _member("kid")
    storage.adjust_points("kid", 200, "chores from before avatars existed")
    _routine("r1", "kid")
    today = date.today()
    for off in range(0, 12):
        storage.set_routine_check("r1", "kid", (today - timedelta(days=off)).isoformat(), True)
    storage.sync_avatar_unlocks("kid")
    owned = set(storage.get_avatar_unlocks("kid"))
    for item in cat.free_items():
        check(cat.item_id(item['slot'], item['key']) in owned,
              f"free item {item['key']} granted by backfill")
    check(cat.item_id('bottoms', 'Shorts') in owned, "already-passed routine threshold granted")
    check(cat.item_id('clothes', 'BlazerShirt') in owned,
          "already-passed CHORE-points threshold granted too")


# --- config validation --------------------------------------------------

def scenario_cannot_wear_what_you_have_not_earned():
    """The ledger is the authority, not the editor."""
    _member("kid")
    storage.sync_avatar_unlocks("kid")
    res = storage.set_avatar_config("kid", {
        'top': 'LongHairCurly',        # free -> kept
        'clothes': 'BlazerShirt',      # locked -> dropped
        'bottoms': 'Trousers',         # free -> kept
        'shoes': 'WellyBoots',         # locked -> dropped
        'nonsense_slot': 'x',          # not a slot -> dropped
        'top_that_is_not_real': 'y',   # not a slot -> dropped
    })
    cfg = res['config']
    check(cfg.get('top') == 'LongHairCurly', "free item kept")
    check(cfg.get('bottoms') == 'Trousers', "free bottoms kept")
    check('clothes' not in cfg, "locked blazer refused")
    check('shoes' not in cfg, "locked wellies refused")
    check(cat.item_id('clothes', 'BlazerShirt') in res['rejected'], "rejection reported")
    check('nonsense_slot' in res['rejected'], "unknown slot reported")

    saved = storage.get_avatar_config("kid")
    check(saved.get('top') == 'LongHairCurly', "config persisted")
    check(saved.get('clothes'), "required slot defaults rather than rendering bare")


def scenario_required_slots_always_render():
    _member("kid")
    cfg = storage.get_avatar_config("kid")
    for slot in cat.get_slots():
        if slot.get('required'):
            check(cfg.get(slot['key']), f"required slot {slot['key']} defaulted")


def scenario_conflicts_are_reported_not_enforced():
    """A bow cannot sit on a woolly hat. The renderer skips it; the ledger
    still says you own it."""
    check('hair_accessory' in cat.conflicts({'top': 'WinterHat1', 'hair_accessory': 'Bow'}),
          "bow conflicts with headwear")
    check(not cat.conflicts({'top': 'LongHairBob', 'hair_accessory': 'Bow'}),
          "bow is fine on hair")
    check('graphic' in cat.conflicts({'clothes': 'Hoodie', 'graphic': 'Pizza'}),
          "a chest graphic needs the graphic shirt")
    check(not cat.conflicts({'clothes': 'GraphicShirt', 'graphic': 'Pizza'}),
          "graphic shirt carries the graphic")


def scenario_slots_are_well_formed():
    """Guardrails on the data, since content will be added by hand forever."""
    zs = [s['z'] for s in cat.SLOTS]
    check(len(zs) == len(set(zs)), "z-order values are unique")
    slot_keys = {s['key'] for s in cat.SLOTS}
    for i in cat.ITEMS:
        check(i['slot'] in slot_keys, f"item {i['key']} names a real slot")
        if i['tier'] == 'unlock':
            check(i.get('track') and i.get('threshold'),
                  f"unlockable {i['key']} needs a track and a threshold")
    seen = set()
    for i in cat.ITEMS:
        pair = (i['slot'], i['key'])
        check(pair not in seen, f"duplicate item {pair}")
        seen.add(pair)
    # waist must paint above clothes or every belt is invisible under a hem
    z = {s['key']: s['z'] for s in cat.SLOTS}
    check(z['waist'] > z['clothes'], "belts paint above the top")
    check(z['hair_accessory'] > z['top'], "hair extras paint above hair")
    check(z['bottoms'] < z['clothes'], "the top paints over the waistband")


def scenario_tracks_are_monotonic():
    """Every counter an unlock hangs off must only ever rise."""
    _member("kid")
    _routine("r1", "kid")
    today = date.today()
    for off in range(0, 5):
        storage.set_routine_check("r1", "kid", (today - timedelta(days=off)).isoformat(), True)
    before = storage.count_routine_completions("kid")
    check(before == 5, f"5 completions counted, got {before}")
    # untick everything; the total must hold
    for off in range(0, 5):
        storage.set_routine_check("r1", "kid", (today - timedelta(days=off)).isoformat(), False)
    check(storage.count_routine_completions("kid") == 5,
          "unticking does not take back the total")
    # re-ticking the same days does not inflate it either
    for off in range(0, 5):
        storage.set_routine_check("r1", "kid", (today - timedelta(days=off)).isoformat(), True)
    check(storage.count_routine_completions("kid") == 5,
          "re-ticking the same days is not farmable")


SCENARIOS = [
    scenario_identity_is_free,
    scenario_unlock_is_never_lost,
    scenario_grant_is_idempotent,
    scenario_backfill_never_starts_you_behind,
    scenario_cannot_wear_what_you_have_not_earned,
    scenario_required_slots_always_render,
    scenario_conflicts_are_reported_not_enforced,
    scenario_slots_are_well_formed,
    scenario_tracks_are_monotonic,
]


if __name__ == "__main__":
    if "CHAUFFEUR_STORAGE" not in os.environ:
        import subprocess
        worst = 0
        for be in ("tinydb", "sqlite"):
            env = dict(os.environ, CHAUFFEUR_STORAGE=be)
            print(f"=== backend: {be} ===")
            worst = max(worst, subprocess.call([sys.executable, os.path.abspath(__file__)], env=env))
        raise SystemExit(worst)

    print(f"storage backend: {getattr(storage, 'BACKEND', 'tinydb')}  (data dir: {_TMP})")
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
