"""chat.initiate — the guest case (family-network arc S6, §6B).

Initiation is the thing that makes a guest a guest: they may be ADDED to a
conversation by somebody who can, and talk freely once inside, and can never
open one — the Slack external-guest shape. The old hardcoded helper checks
(create_dm, create_group, get_channels_for_member) become one capability
that varies per person, with today's behaviour reproduced for every existing
role and exactly one documented delta from the §9 table: a household adult
may now open a DM with a helper.

Run from chauffeur/:  python tests/test_chat_initiate.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


def _denied(fn, *args, **kw):
    try:
        fn(*args, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _seed():
    storage.members_table.truncate()
    storage.chat_channels_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult"})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child"})
    storage.add_member({"id": "nan", "name": "Nanny", "role": "helper"})
    # No creatable path to this role until S15 — seeded at the storage layer
    # to pin the behaviour before the role ships.
    storage.add_member({"id": "cuz", "name": "Cousin", "role": "guest"})
    storage.ensure_family_channel()


def _dm(a, b):
    import main
    return main.create_dm_channel(main.DmChannelRequest(member_id=a, other_member_id=b))


def _group(creator, others, title="g"):
    import main
    return main.create_group_channel(
        main.GroupChannelRequest(member_id=creator, member_ids=others, title=title))


def scenario_a_guest_can_never_open_a_conversation():
    _seed()
    check(_denied(_dm, "cuz", "mom") == 403,
          "initiate none: not even with a parent")
    check(_denied(_group, "cuz", ["mom", "dad"]) == 403,
          "and cannot found a group either")


def scenario_a_guest_added_is_a_guest_inside():
    _seed()
    g = _group("dad", ["mom", "cuz"])
    check(g and "cuz" in g["member_ids"],
          "an adult (initiate: anyone) may add a guest to a group")
    visible = storage.get_channels_for_member("cuz")
    check([c["id"] for c in visible] == [g["id"]],
          f"the guest's list is exactly the rooms they were let into — no "
          f"family channel, no event threads: {[c['kind'] for c in visible]}")


def scenario_todays_helper_rules_survive_the_rewrite():
    _seed()
    check(_dm("nan", "mom") is not None, "helper→parent stays fine")
    check(_denied(_dm, "nan", "dad") == 403, "helper→adult stays refused")
    check(_denied(_dm, "emma", "nan") == 403,
          "a kid still cannot DM the nanny (household excludes helpers)")
    check(_denied(_group, "mom", ["dad", "nan"]) == 403,
          "a helper can be added to no group, even by a parent — hard none, "
          "not invited")


def scenario_the_one_documented_delta():
    _seed()
    check(_dm("dad", "nan") is not None,
          "a household adult (initiate: anyone) may now open a DM with a "
          "helper — the §9 table's decision, replacing the both-ways hardcode")


def scenario_household_never_reaches_a_guest():
    _seed()
    check(_denied(_dm, "emma", "cuz") == 403,
          "a kid (initiate: household) cannot open a DM with a guest")
    check(_denied(_group, "emma", ["dad", "cuz"]) == 403,
          "or found a group containing one")
    g = _group("emma", ["dad", "mom"])
    check(g is not None, "kids keep founding household groups exactly as today")


SCENARIOS = [
    scenario_a_guest_can_never_open_a_conversation,
    scenario_a_guest_added_is_a_guest_inside,
    scenario_todays_helper_rules_survive_the_rewrite,
    scenario_the_one_documented_delta,
    scenario_household_never_reaches_a_guest,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
