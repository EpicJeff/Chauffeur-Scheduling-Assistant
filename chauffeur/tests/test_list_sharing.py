"""Per-list instance grants on shopping lists (family-network arc S8).

The §5 story: share the grocery list with one person without sharing lists
in general. `shared_with` is ADDITIVE and empty means everyone — the same
open default the other three allowlists use — so for the household it is a
no-op, and for a viewer whose `lists.shopping` is none it is exactly the
lists somebody handed them. A grant to see a list is a grant to USE it:
adding milk is the entire point of being handed the grocery list.

Run from chauffeur/:  python tests/test_list_sharing.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


class Req:
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


def _denied(fn, *args, **kw):
    try:
        fn(*args, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _seed():
    import main
    storage.members_table.truncate()
    storage.shopping_lists_table.truncate()
    storage.shopping_items_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "gran", "name": "Gran", "role": "adult",
                        "scope": {"preset": "keeping_up"}})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child"})
    default = storage.ensure_default_shopping_list()
    groceries = main.create_shopping_list(
        main.ShoppingListRequest(name="Kroger", store="Kroger"))
    toks = {mid: storage.create_member_token(mid)
            for mid in ("mom", "gran", "emma")}
    return default, groceries, toks


def scenario_sharing_hands_one_list_to_one_person():
    import main
    default, groceries, tok = _seed()
    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", store="Kroger", shared_with=["gran"]))

    seen = [l['name'] for l in main.list_shopping_lists(request=Req(tok['gran']))]
    check(seen == ["Kroger"],
          f"the grocery list and no other — got {seen}")
    check({l['id'] for l in main.list_shopping_lists(request=Req(tok['emma']))}
          == {default['id'], groceries['id']},
          "a household member still sees every list (the grant never narrows)")
    check({l['id'] for l in main.list_shopping_lists(request=Req())}
          == {default['id'], groceries['id']},
          "tokenless callers (panels) keep today's behaviour")


def scenario_a_grant_to_see_is_a_grant_to_use():
    import main
    default, groceries, tok = _seed()
    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", store="Kroger", shared_with=["gran"]))

    item = main.create_shopping_item(main.ShoppingItemRequest(
        name="Milk", list_id=groceries['id'], added_by="gran"),
        request=Req(tok['gran']))
    check(item and item['name'] == "Milk", "gran puts milk on the list she holds")
    check(isinstance(main.list_shopping_items(list_id=groceries['id'],
                                              request=Req(tok['gran'])), list),
          "and reads it back")
    check(_denied(main.list_shopping_items, list_id=default['id'],
                  request=Req(tok['gran'])) == 403,
          "the list nobody shared stays closed to her")
    check(_denied(main.create_shopping_item, main.ShoppingItemRequest(
        name="Eggs", list_id=default['id']), request=Req(tok['gran'])) == 403,
          "…for writes too")


def scenario_unshared_means_household_not_nobody():
    import main
    default, groceries, tok = _seed()
    check(len(main.list_shopping_lists(request=Req(tok['emma']))) == 2,
          "shared_with [] is household-wide — today's behaviour, untouched")
    check(main.list_shopping_lists(request=Req(tok['gran'])) == [],
          "…and a scope that hides lists hides unshared lists")


def scenario_a_typo_never_becomes_a_grant():
    import main
    default, groceries, tok = _seed()
    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", shared_with=["gran", "nobody-real"]))
    lst = storage.get_shopping_list(groceries['id'])
    check(lst.get('shared_with') == ["gran"],
          f"only real members survive the write: {lst.get('shared_with')}")


def scenario_private_means_only_these_people():
    """The closed counterpart to S8's open grant: audience='private' makes
    shared_with the WHOLE audience — no parent bypass (the gift may be FOR a
    parent), no panels, no other read path."""
    import main
    default, groceries, tok = _seed()
    storage.add_member({"id": "dad", "name": "Dad", "role": "parent"})
    tok['dad'] = storage.create_member_token('dad')

    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", store="Kroger", audience='private', shared_with=['mom']),
        request=Req(tok['emma']))
    lst = storage.get_shopping_list(groceries['id'])
    check(set(lst.get('shared_with') or []) == {'mom', 'emma'},
          f"whoever flips the switch is on the list — {lst.get('shared_with')}")

    check([l['id'] for l in main.list_shopping_lists(request=Req(tok['dad']))]
          == [default['id']],
          "a parent OFF the list does not see it — no parent bypass")
    check(groceries['id'] in {l['id']
                              for l in main.list_shopping_lists(request=Req(tok['mom']))},
          "a person ON the list keeps it")
    check([l['id'] for l in main.list_shopping_lists(request=Req())]
          == [default['id']],
          "anonymous surfaces (wall panels) never see a private list")

    check(_denied(main.list_shopping_items, list_id=groceries['id'],
                  request=Req(tok['dad'])) == 403, "items refuse the outsider")
    check(_denied(main.shopping_item_runs, list_id=groceries['id'],
                  request=Req(tok['dad'])) == 403, "the runs split refuses too")
    check(_denied(main.list_shopping_items, list_id=groceries['id'],
                  request=Req()) == 403, "…and the tokenless caller")
    check(_denied(main.edit_shopping_list, groceries['id'],
                  main.ShoppingListRequest(name="Mine now"),
                  request=Req(tok['dad'])) == 403, "editing is seeing")
    check(_denied(main.remove_shopping_list, groceries['id'],
                  request=Req(tok['dad'])) == 403, "so is deleting")
    check(isinstance(main.list_shopping_items(list_id=groceries['id'],
                                              request=Req(tok['mom'])), list),
          "a member reads it exactly as before")


def scenario_the_default_list_never_goes_private():
    """Every capture path (voice, photo, meal drain) falls back to the default
    list — private would silently eat the whole household's milk."""
    import main
    default, groceries, tok = _seed()
    check(_denied(main.edit_shopping_list, default['id'],
                  main.ShoppingListRequest(name="Groceries", is_default=True,
                                           audience='private'),
                  request=Req(tok['mom'])) == 400,
          "the default list refuses to go private")
    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", audience='private'), request=Req(tok['mom']))
    check(_denied(main.edit_shopping_list, groceries['id'],
                  main.ShoppingListRequest(name="Kroger", is_default=True),
                  request=Req(tok['mom'])) == 400,
          "…and a private list refuses to become the default")


def scenario_a_private_list_always_has_somebody():
    """Fail-safe over fail-secret: a private list nobody can see is a bug, so
    the flip requires at least one member and membership edits may never empty
    it."""
    import main
    default, groceries, tok = _seed()
    check(_denied(main.edit_shopping_list, groceries['id'],
                  main.ShoppingListRequest(name="Kroger", audience='private'),
                  request=Req()) == 400,
          "no actor, no members — the flip is refused, not stored")
    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", audience='private'), request=Req(tok['mom']))
    check(_denied(main.edit_shopping_list, groceries['id'],
                  main.ShoppingListRequest(name="Kroger", shared_with=[]),
                  request=Req(tok['mom'])) == 400,
          "a membership edit may not leave a private list empty")


def scenario_the_agent_cannot_be_talked_into_it():
    """Both agent stacks resolve lists through the same filter: a private list
    is unfindable by name for anybody off it — including the caller with no
    resolved member at all (HA satellite, admin dashboard chat)."""
    import main
    from services import agent_tools_v2 as atv2
    default, groceries, tok = _seed()
    main.edit_shopping_list(groceries['id'], main.ShoppingListRequest(
        name="Kroger", store="Kroger", audience='private'),
        request=Req(tok['mom']))

    res = atv2.get_shopping_list_items("Kroger", acting_member=None)
    check(res['status'] == 'error',
          "an anonymous voice surface cannot read the private list")
    res = atv2.add_shopping_items("socks", list_name="Kroger",
                                  acting_member=storage.get_member('emma'))
    check(res['status'] == 'error',
          "a member off the list cannot write to it by name")
    res = atv2.get_shopping_list_items("Kroger",
                                       acting_member=storage.get_member('mom'))
    check(res['status'] == 'success',
          "the member it belongs to talks to it as always")


SCENARIOS = [
    scenario_sharing_hands_one_list_to_one_person,
    scenario_a_grant_to_see_is_a_grant_to_use,
    scenario_unshared_means_household_not_nobody,
    scenario_a_typo_never_becomes_a_grant,
    scenario_private_means_only_these_people,
    scenario_the_default_list_never_goes_private,
    scenario_a_private_list_always_has_somebody,
    scenario_the_agent_cannot_be_talked_into_it,
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
