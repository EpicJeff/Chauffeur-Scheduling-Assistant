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


SCENARIOS = [
    scenario_sharing_hands_one_list_to_one_person,
    scenario_a_grant_to_see_is_a_grant_to_use,
    scenario_unshared_means_household_not_nobody,
    scenario_a_typo_never_becomes_a_grant,
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
