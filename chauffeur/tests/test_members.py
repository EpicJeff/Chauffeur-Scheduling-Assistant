"""Tests for the family-member overlay (services/storage.py ensure_members + CRUD).

Members are one-record-per-human links over the legacy drivers/passengers
tables. Same harness as test_storage.py: temp data dir, runs once per storage
backend.

Run from chauffeur/:  python tests/test_members.py
"""
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_members_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None


def scenario_migration_links_drivers_and_passengers():
    storage.drivers_table.insert({"id": "jeff", "name": "Jeff", "color_code": "#ff0000", "bio": "dad"})
    storage.drivers_table.insert({"id": "amy", "name": "Amy", "color_code": "#00ff00", "is_disabled": True})
    storage.passengers_table.insert({"id": "p-amy", "name": "amy "})  # name-merges onto Amy
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben"})   # passenger-only -> child default
    storage.ensure_members()

    members = storage.get_all_members()
    check(len(members) == 3, f"expected 3 members (Jeff, Amy, Ben), got {len(members)}")

    jeff = storage.get_member_by_driver_id("jeff")
    check(jeff and jeff["name"] == "Jeff" and jeff["can_drive"], "driver member carries name + can_drive")
    check(jeff["color_code"] == "#ff0000" and jeff["bio"] == "dad", "driver color/bio copied")
    check(jeff["passenger_id"] is None, "Jeff has no passenger link")

    amy = storage.get_member_by_driver_id("amy")
    check(amy and amy["passenger_id"] == "p-amy", "same-name passenger merges onto driver member")
    check(not amy["can_drive"], "disabled driver -> can_drive False")
    check(not amy["is_child"], "merged driver+passenger member is not defaulted to child")

    ben = storage.get_member_by_passenger_id("p-ben")
    check(ben and ben["is_child"] and ben["driver_id"] is None, "passenger-only member defaults to child")


def scenario_migration_idempotent():
    storage.drivers_table.insert({"id": "jeff", "name": "Jeff", "color_code": "#f00"})
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben"})
    storage.ensure_members()
    storage.ensure_members()
    storage.ensure_members()
    check(len(storage.get_all_members()) == 2, "re-runs must not duplicate members")


def scenario_passenger_id_backfill():
    # settings-migrated passengers predate the 'id' field
    storage.passengers_table.insert({"name": "Legacy Kid", "calendar_ids": ["cal1"]})
    storage.ensure_members()
    raw = storage.passengers_table.all()[0]
    check(raw.get("id"), "ensure_members must backfill a passenger id")
    member = storage.get_member_by_passenger_id(raw["id"])
    check(member and member["name"] == "Legacy Kid", "backfilled passenger gets a member")
    storage.ensure_members()
    check(len(storage.get_all_members()) == 1, "backfill must not duplicate on re-run")


def scenario_add_driver_and_passenger_backfill():
    storage.add_driver({"id": "new-driver", "name": "Newbie", "color_code": "#00f"})
    check(storage.get_member_by_driver_id("new-driver") is not None,
          "add_driver must create the member")
    storage.add_passenger({"id": "p-new", "name": "New Kid"})
    check(storage.get_member_by_passenger_id("p-new") is not None,
          "add_passenger must create the member")
    # API-created passenger sharing a member's name merges onto it
    storage.add_passenger({"id": "p-newbie", "name": "Newbie"})
    m = storage.get_member_by_driver_id("new-driver")
    check(m["passenger_id"] == "p-newbie", "same-name passenger merges onto existing member")
    check(len(storage.get_all_members()) == 2, "no extra member for the merged passenger")


def scenario_member_crud():
    storage.add_member({"id": "m1", "name": "Solo", "color_code": "#123456"})
    m = storage.get_member("m1")
    check(m and m["name"] == "Solo", "get_member by id")
    check(storage.update_member("m1", {"avatar": "🚗", "is_child": True}), "update returns True")
    m = storage.get_member("m1")
    check(m["avatar"] == "🚗" and m["is_child"], "update applied")
    check(not storage.update_member("nope", {"name": "x"}), "update of missing member returns False")
    storage.delete_member("m1")
    check(storage.get_member("m1") is None, "delete removes member")


def scenario_merge_and_split():
    storage.drivers_table.insert({"id": "sam-d", "name": "Sam"})
    storage.passengers_table.insert({"id": "sam-p", "name": "Sammy"})  # different name: two members
    storage.ensure_members()
    check(len(storage.get_all_members()) == 2, "precondition: two members")

    keep = storage.get_member_by_driver_id("sam-d")
    absorb = storage.get_member_by_passenger_id("sam-p")
    storage.update_member(absorb["id"], {"ha_person_entity": "person.sam"})

    merged = storage.merge_members(keep["id"], absorb["id"])
    check(merged["driver_id"] == "sam-d" and merged["passenger_id"] == "sam-p",
          "merge moves the passenger link onto keep")
    check(merged["ha_person_entity"] == "person.sam", "merge carries unset HA mappings over")
    check(len(storage.get_all_members()) == 1, "absorbed member deleted")
    check(storage.merge_members(keep["id"], "ghost") is None, "merge with missing member -> None")

    split = storage.split_member(keep["id"], "passenger")
    check(split and split["passenger_id"] == "sam-p" and split["driver_id"] is None,
          "split detaches passenger link into a new member")
    kept = storage.get_member(keep["id"])
    check(kept["passenger_id"] is None and kept["driver_id"] == "sam-d", "kept member loses the link")
    check(len(storage.get_all_members()) == 2, "split creates the second member")
    check(storage.split_member(split["id"], "passenger") is None,
          "splitting a member's only link is refused")


SCENARIOS = [
    scenario_migration_links_drivers_and_passengers,
    scenario_migration_idempotent,
    scenario_passenger_id_backfill,
    scenario_add_driver_and_passenger_backfill,
    scenario_member_crud,
    scenario_merge_and_split,
]

if __name__ == "__main__":
    import traceback

    if "CHAUFFEUR_STORAGE" not in os.environ:
        import subprocess
        worst = 0
        for be in ("tinydb", "sqlite"):
            env = dict(os.environ, CHAUFFEUR_STORAGE=be)
            print(f"=== backend: {be} ===")
            rc = subprocess.call([sys.executable, os.path.abspath(__file__)], env=env)
            worst = max(worst, rc)
        raise SystemExit(worst)

    backend = getattr(storage, "BACKEND", "tinydb")
    print(f"storage backend: {backend}  (data dir: {_TMP})")
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
