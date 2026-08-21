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
    storage.drivers_table.insert({"id": "jeff", "name": "Jeff", "color_code": "#ff0000"})
    storage.drivers_table.insert({"id": "amy", "name": "Amy", "color_code": "#00ff00", "is_disabled": True})
    storage.passengers_table.insert({"id": "p-amy", "name": "amy "})  # name-merges onto Amy
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben"})   # passenger-only -> child default
    storage.ensure_members()

    members = storage.get_all_members()
    check(len(members) == 3, f"expected 3 members (Jeff, Amy, Ben), got {len(members)}")

    jeff = storage.get_member_by_driver_id("jeff")
    check(jeff and jeff["name"] == "Jeff" and jeff["can_drive"], "driver member carries name + can_drive")
    # `bio` left with the philosophy arc (v2.353.0): a driver has no such
    # field any more, and a member is seeded without one.
    check(jeff["color_code"] == "#ff0000", "driver colour copied")
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


def scenario_roles():
    storage.drivers_table.insert({"id": "jeff", "name": "Jeff"})
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben"})
    storage.ensure_members()
    check(storage.get_member_by_driver_id("jeff")["role"] == "adult",
          "driver members default to adult")
    check(storage.get_member_by_passenger_id("p-ben")["role"] == "child",
          "passenger-only members default to child")
    # legacy members without role get backfilled from is_child
    storage.add_member({"id": "legacy1", "name": "Old Kid", "is_child": True})
    storage.add_member({"id": "legacy2", "name": "Old Adult", "is_child": False})
    storage.ensure_member_roles()
    check(storage.get_member("legacy1")["role"] == "child", "is_child -> child backfill")
    check(storage.get_member("legacy2")["role"] == "adult", "default -> adult backfill")
    storage.ensure_member_roles()
    check(storage.get_member("legacy1")["role"] == "child", "backfill idempotent")


def scenario_pins_and_tokens():
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    check(not storage.verify_member_pin("mom", "1234"), "no PIN set -> verify False")
    check(storage.set_member_pin("mom", "4321"), "set pin")
    mom = storage.get_member("mom")
    check(mom["pin_hash"] and mom["pin_salt"] and mom["pin_hash"] != "4321",
          "pin stored hashed with salt")
    check(storage.verify_member_pin("mom", "4321"), "correct pin verifies")
    check(not storage.verify_member_pin("mom", "1111"), "wrong pin fails")
    check(not storage.verify_member_pin("mom", ""), "empty pin fails")

    t1 = storage.create_member_token("mom")
    t2 = storage.create_member_token("mom")
    check(t1 != t2 and len(t1) >= 32, "unique long tokens")
    check(storage.get_member_by_token(t1)["id"] == "mom", "token resolves member")
    check(storage.get_member_by_token("bogus") is None, "unknown token -> None")
    check(storage.get_member_by_token("") is None, "empty token -> None")
    storage.delete_member_tokens("mom")
    check(storage.get_member_by_token(t1) is None, "tokens revocable")

    storage.clear_member_pin("mom")
    check(not storage.get_member("mom")["pin_hash"], "pin cleared")


def scenario_calendars_migrate_up_to_the_person():
    storage.drivers_table.insert({"id": "jeff", "name": "Jeff", "calendar_ids": ["jeff@cal"]})
    storage.passengers_table.insert({"id": "p-ben", "name": "Ben", "calendar_ids": ["ben@cal"]})
    storage.ensure_members()
    storage.ensure_member_calendars()

    jeff = storage.get_member_by_driver_id("jeff")
    ben = storage.get_member_by_passenger_id("p-ben")
    check(jeff["calendar_ids"] == ["jeff@cal"], "driver calendar lifted onto the person")
    check(ben["calendar_ids"] == ["ben@cal"], "passenger calendar lifted onto the person")

    storage.ensure_member_calendars()
    check(storage.get_member_by_driver_id("jeff")["calendar_ids"] == ["jeff@cal"],
          "migration is idempotent")


def scenario_person_with_no_profile_can_hold_a_calendar():
    # The whole point: drives themselves, chauffeurs nobody, still on the calendar.
    storage.add_member({"id": "vovo", "name": "Vovo", "role": "adult",
                        "driver_id": None, "passenger_id": None, "calendar_ids": []})
    check(storage.set_member_calendars("vovo", ["vovo@cal"]), "set calendars on an unlinked person")
    check(storage.get_member("vovo")["calendar_ids"] == ["vovo@cal"], "stored on the member")
    check(not storage.set_member_calendars("ghost", ["x@cal"]), "unknown member -> False")


def scenario_links_mirror_the_person():
    storage.drivers_table.insert({"id": "teen", "name": "Teen"})
    storage.passengers_table.insert({"id": "p-teen", "name": "Teen"})
    storage.ensure_members()
    m = storage.get_member_by_driver_id("teen")
    check(m["passenger_id"] == "p-teen", "precondition: one person, both profiles")

    storage.set_member_calendars(m["id"], ["a@cal", "b@cal"])
    d = next(d for d in storage.get_all_drivers() if d["id"] == "teen")
    p = next(p for p in storage.get_all_passengers() if p["id"] == "p-teen")
    check(d["calendar_ids"] == ["a@cal", "b@cal"], "driver record mirrors the person")
    check(p["calendar_ids"] == ["a@cal", "b@cal"], "passenger record mirrors the person")

    # Removal propagates too — the mirror is rewritten, never merged.
    storage.set_member_calendars(m["id"], ["a@cal"])
    d = next(d for d in storage.get_all_drivers() if d["id"] == "teen")
    p = next(p for p in storage.get_all_passengers() if p["id"] == "p-teen")
    check(d["calendar_ids"] == ["a@cal"], "removing a calendar shrinks the driver mirror")
    check(p["calendar_ids"] == ["a@cal"], "removing a calendar shrinks the passenger mirror")

    # ...and a later union pass must not resurrect what was removed.
    storage.ensure_member_calendars()
    check(storage.get_member(m["id"])["calendar_ids"] == ["a@cal"],
          "self-heal union must not undo a deliberate removal")


def scenario_calendar_writes_are_deduped_and_trimmed():
    storage.add_member({"id": "m", "name": "M", "calendar_ids": []})
    storage.set_member_calendars("m", ["  a@cal ", "a@cal", "", None, "b@cal"])
    check(storage.get_member("m")["calendar_ids"] == ["a@cal", "b@cal"],
          "blanks dropped, whitespace trimmed, duplicates collapsed")


def scenario_new_profile_inherits_the_persons_calendars():
    storage.add_member({"id": "solo", "name": "Solo", "calendar_ids": []})
    storage.set_member_calendars("solo", ["solo@cal"])
    # Adding a driving profile later must not leave it calendar-blind.
    storage.add_driver({"id": "solo-d", "name": "Solo", "color_code": "#fff"})
    d = next(d for d in storage.get_all_drivers() if d["id"] == "solo-d")
    check(storage.get_member_by_driver_id("solo-d")["id"] == "solo", "linked to the existing person")
    check(d["calendar_ids"] == ["solo@cal"], "new driving profile inherits the person's calendars")


def scenario_merge_unions_calendars():
    storage.add_member({"id": "keep", "name": "Keep", "calendar_ids": ["k@cal"]})
    storage.add_member({"id": "gone", "name": "Gone", "calendar_ids": ["g@cal"]})
    merged = storage.merge_members("keep", "gone")
    check(merged["calendar_ids"] == ["k@cal", "g@cal"],
          "merge keeps both people's calendars instead of dropping the absorbed one")


SCENARIOS = [
    scenario_migration_links_drivers_and_passengers,
    scenario_calendars_migrate_up_to_the_person,
    scenario_person_with_no_profile_can_hold_a_calendar,
    scenario_links_mirror_the_person,
    scenario_calendar_writes_are_deduped_and_trimmed,
    scenario_new_profile_inherits_the_persons_calendars,
    scenario_merge_unions_calendars,
    scenario_roles,
    scenario_pins_and_tokens,
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
