"""Tests for the shopping list (meals & provisioning arc M1).

Load-bearing properties, each traceable to docs/meal_design.md §M1:

- Tag binding survives the errand REGENERATING (the whole reason the list is
  its own entity and not a field on Errand).
- Per-item concurrency: interleaved writes to different items never clobber,
  and re-checking is idempotent — two people at the store is the normal case.
- Dedupe on unchecked items only (saying "milk" twice ≠ two milks; a re-add
  AFTER checking off is a genuinely new need).
- Capture is ungated for everyone including kids (principle 4) and lands with
  attribution.
- Photo capture stages candidates rather than auto-adding, and greys out what
  is already on the list.

Run from chauffeur/:  python tests/test_shopping.py
"""
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, shopping
from services.agent_tools_v2 import (add_shopping_items, get_shopping_list_items,
                                     check_off_shopping_item,
                                     remove_shopping_item_by_name)


def _reset():
    import main  # noqa: F401
    for t in (storage.shopping_lists_table, storage.shopping_items_table,
              storage.members_table, storage.errands_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child", "is_child": True})


def _mk_errand(title="Groceries", tags=None, location="Kroger"):
    """A recurring errand as the solver stores it — new id every cycle."""
    from models.schemas import Errand
    e = Errand(title=title, duration_mins=45, location=location,
               tags=tags if tags is not None else ["groceries"],
               recurrence_rule="weekly").model_dump()
    storage.add_errand(e)
    return e


# --- the binding ------------------------------------------------------------

def scenario_tag_binding_survives_errand_regeneration():
    _reset()
    import main
    lst = storage.ensure_default_shopping_list()
    check(lst.get('errand_tag') == 'groceries',
          f"default list ships bound to the groceries tag, got {lst.get('errand_tag')}")

    first = _mk_errand()
    bound = storage.find_shopping_lists_for_errand(first)
    check([l['id'] for l in bound] == [lst['id']], "list binds to this cycle's errand")

    # Next week the recurring errand regenerates: NEW id, same tag. A list
    # bound by errand id would now be orphaned; bound by tag it survives.
    storage.errands_table.truncate()
    second = _mk_errand()
    check(second['id'] != first['id'], "regenerated errand is a different row")
    bound2 = storage.find_shopping_lists_for_errand(second)
    check([l['id'] for l in bound2] == [lst['id']],
          "list still binds after the errand regenerates — the point of tag binding")

    # And the API surfaces it on the errand card.
    payload = main.shopping_for_errand(second['id'])
    check(payload['lists'] and payload['lists'][0]['id'] == lst['id'],
          "for-errand endpoint returns the bound list")


def scenario_store_fallback_and_no_false_binding():
    _reset()
    from models.schemas import ShoppingList
    costco = ShoppingList(name="Costco", store="Costco", errand_tag=None).model_dump()
    storage.add_shopping_list(costco)
    storage.ensure_default_shopping_list()

    e = _mk_errand(title="Costco run", tags=[], location="Costco")
    names = {l['name'] for l in storage.find_shopping_lists_for_errand(e)}
    check(names == {"Costco"},
          f"store==location is the convenience fallback when no tag is set, got {names}")

    unrelated = _mk_errand(title="Pharmacy", tags=["pharmacy"], location="Walgreens")
    check(storage.find_shopping_lists_for_errand(unrelated) == [],
          "an unrelated errand binds nothing — no accidental catch-all")


# --- concurrency: the app's first shared mutable document -------------------

def scenario_per_item_writes_do_not_clobber():
    _reset()
    import main
    from main import ShoppingItemRequest, ShoppingItemPatch
    lid = storage.ensure_default_shopping_list()['id']
    for n in ("milk", "eggs", "bread"):
        main.create_shopping_item(ShoppingItemRequest(name=n, list_id=lid))
    items = {i['name']: i for i in storage.get_shopping_items(lid)}

    # Two phones, interleaved, different items — the real store scenario.
    main.patch_shopping_item(items['milk']['id'], ShoppingItemPatch(is_checked=True))
    main.patch_shopping_item(items['bread']['id'], ShoppingItemPatch(qty="2 loaves"))
    main.patch_shopping_item(items['eggs']['id'], ShoppingItemPatch(is_checked=True))
    main.patch_shopping_item(items['milk']['id'], ShoppingItemPatch(note="whole"))

    after = {i['name']: i for i in storage.get_shopping_items(lid)}
    check(after['milk']['is_checked'] and after['milk']['note'] == "whole",
          "milk kept BOTH the check and the later note")
    check(after['bread']['qty'] == "2 loaves" and not after['bread']['is_checked'],
          "bread's qty edit survived writes to other items")
    check(after['eggs']['is_checked'], "eggs stayed checked")


def scenario_recheck_is_idempotent():
    _reset()
    import main
    from main import ShoppingItemRequest, ShoppingItemPatch
    lid = storage.ensure_default_shopping_list()['id']
    it = main.create_shopping_item(ShoppingItemRequest(name="milk", list_id=lid))
    first = main.patch_shopping_item(it['id'], ShoppingItemPatch(is_checked=True, member_id="momm"))
    second = main.patch_shopping_item(it['id'], ShoppingItemPatch(is_checked=True, member_id="kid1"))
    check(first['is_checked'] and second['is_checked'],
          "two phones tapping the same row both succeed rather than erroring")
    check(len(storage.get_shopping_items(lid)) == 1, "and it is still one item")

    back = main.patch_shopping_item(it['id'], ShoppingItemPatch(is_checked=False))
    check(not back['is_checked'] and back['checked_by'] is None,
          "unchecking clears the attribution too")


def scenario_ordering_open_first_then_checked():
    _reset()
    import main
    from main import ShoppingItemRequest, ShoppingItemPatch
    lid = storage.ensure_default_shopping_list()['id']
    made = [main.create_shopping_item(ShoppingItemRequest(name=n, list_id=lid))
            for n in ("milk", "eggs", "bread")]
    main.patch_shopping_item(made[0]['id'], ShoppingItemPatch(is_checked=True))
    order = [i['name'] for i in storage.get_shopping_items(lid)]
    check(order == ["eggs", "bread", "milk"],
          f"checked items sink; open stay in the order they were remembered — got {order}")


# --- dedupe -----------------------------------------------------------------

def scenario_dedupe_only_applies_to_open_items():
    _reset()
    import main
    from main import ShoppingItemRequest, ShoppingItemPatch
    lid = storage.ensure_default_shopping_list()['id']
    main.create_shopping_item(ShoppingItemRequest(name="milk", list_id=lid))
    dupe = main.create_shopping_item(ShoppingItemRequest(name="  MILK ", qty="2 gal", list_id=lid))
    check(dupe.get('deduped') and dupe.get('qty') == "2 gal",
          "case/whitespace-insensitive dedupe, and the new qty is merged in")
    check(len(storage.get_shopping_items(lid)) == 1, "still one milk")

    # Bought it, then someone notices we need more: a NEW need, not a dupe.
    main.patch_shopping_item(dupe['id'], ShoppingItemPatch(is_checked=True))
    again = main.create_shopping_item(ShoppingItemRequest(name="milk", list_id=lid))
    check(not again.get('deduped'), "re-adding after checking off creates a fresh item")
    check(len(storage.get_shopping_items(lid)) == 2, "two rows: one bought, one needed")


# --- capture (voice/agent), ungated, attributed ------------------------------

def scenario_kid_can_add_and_it_is_attributed():
    _reset()
    kid = storage.get_member("kid1")
    res = add_shopping_items("cereal", acting_member=kid)
    check(res['status'] == 'success', f"a child adding to the list is never refused: {res}")
    lid = storage.ensure_default_shopping_list()['id']
    items = storage.get_shopping_items(lid)
    check(items[0]['added_by'] == "kid1" and items[0]['added_via'] == 'voice',
          "attribution recorded (who noticed), which is not a permission gate")


def scenario_agent_multi_add_split_and_readback():
    _reset()
    add_shopping_items("milk, eggs and paper towels")
    lid = storage.ensure_default_shopping_list()['id']
    names = [i['name'] for i in storage.get_shopping_items(lid)]
    check(names == ["milk", "eggs", "paper towels"],
          f"commas AND the word 'and' split one utterance into items — got {names}")

    again = add_shopping_items("Milk")
    check("Already" in again['message'], f"dedupe is reported, not silent: {again['message']}")

    read = get_shopping_list_items()
    check("milk" in read['message'] and "paper towels" in read['message'],
          "the read's message IS the spoken answer")

    got = check_off_shopping_item("eggs")
    check("2 left" in got['message'], f"check-off reports what remains: {got['message']}")

    gone = remove_shopping_item_by_name("paper towels")
    check(gone['status'] == 'success', "removing something no longer wanted")
    left = [i['name'] for i in storage.get_shopping_items(lid, include_checked=False)]
    check(left == ["milk"], f"one open item left, got {left}")


def scenario_agent_disambiguates_rather_than_guessing():
    _reset()
    from models.schemas import ShoppingList
    storage.add_shopping_list(ShoppingList(name="Costco", store="Costco").model_dump())
    storage.add_shopping_list(ShoppingList(name="Corner store", store="Corner").model_dump())
    res = add_shopping_items("batteries", list_name="Co")
    check(res['status'] == 'error' and "Which list" in res['message'],
          f"ambiguous list name asks instead of picking — got {res['message']}")

    miss = check_off_shopping_item("something not there")
    check(miss['status'] in ('error', 'success'), "missing item never raises")


def scenario_named_list_routes_items_to_the_right_store():
    _reset()
    from models.schemas import ShoppingList
    # Real order of events: the default list exists first (created on first
    # capture), THEN the family adds a second store.
    default = storage.ensure_default_shopping_list()
    costco = ShoppingList(name="Costco", store="Costco").model_dump()
    storage.add_shopping_list(costco)

    add_shopping_items("paper towels", list_name="Costco")
    add_shopping_items("milk")
    check([i['name'] for i in storage.get_shopping_items(costco['id'])] == ["paper towels"],
          "named list gets its item")
    check([i['name'] for i in storage.get_shopping_items(default['id'])] == ["milk"],
          "unnamed capture falls back to the default list")


def scenario_default_list_is_created_on_first_use():
    _reset()
    check(storage.get_shopping_lists() == [], "fresh install has no lists")
    res = add_shopping_items("milk")
    check(res['status'] == 'success',
          "a voice add on a fresh install must not fail for lack of a list")
    check(len(storage.get_shopping_lists()) == 1, "exactly one list was created")


# --- photo capture -----------------------------------------------------------

def _fake_vision(payload):
    return mock.patch('services.model_pools.call_pool_json', return_value=payload)


def scenario_photo_stages_candidates_and_flags_existing():
    _reset()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    lid = storage.ensure_default_shopping_list()['id']
    add_shopping_items("milk")

    payload = {"kind": "shelf", "candidates": [
        {"name": "milk", "qty": None, "suggested": True, "why": "carton looks empty"},
        {"name": "orange juice", "qty": "1", "suggested": True, "why": "empty spot"},
        {"name": "ketchup", "qty": None, "suggested": False, "why": "still half full"},
    ]}
    with _fake_vision(payload):
        res = shopping.extract_items_from_photo("b64", "image/jpeg", "fridge")
    res['candidates'] = shopping.already_on_list(lid, res['candidates'])

    by = {c['name']: c for c in res['candidates']}
    check(res['kind'] == 'shelf', "photo kind drives the picker's wording")
    check(by['milk']['already'] and not by['milk']['suggested'],
          "something already open on the list is flagged and deselected")
    check(by['orange juice']['suggested'], "a genuine gap stays selected")
    check(not by['ketchup']['suggested'], "a full container is offered but not preselected")
    # Nothing was added: candidates are STAGED (a picker, not an approval gate).
    check(len(storage.get_shopping_items(lid)) == 1,
          "extraction must not add anything by itself")


def scenario_photo_handles_empty_and_failure_without_raising():
    _reset()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    with _fake_vision({"kind": "shelf", "candidates": []}):
        res = shopping.extract_items_from_photo("b64", "image/jpeg")
    check(res['candidates'] == [] and res['error'] is None,
          "an empty answer is a correct answer, not an error")

    with mock.patch('services.model_pools.call_pool_json', side_effect=RuntimeError("boom")):
        res = shopping.extract_items_from_photo("b64", "image/jpeg")
    check(res['error'] and res['candidates'] == [],
          "a vision failure degrades to an error message, never an exception")

    storage.get_settings = lambda: {}
    res = shopping.extract_items_from_photo("b64", "image/jpeg")
    check(res['error'] == 'no LLM API key configured', "no key is explained, not crashed")


def scenario_photo_dedupes_and_caps_candidates():
    _reset()
    storage.get_settings = lambda: {"llm_gemini_api_key": "test-key"}
    payload = {"kind": "handwritten", "candidates":
               [{"name": "milk", "suggested": True}, {"name": "MILK", "suggested": True}]
               + [{"name": f"item {i}", "suggested": True} for i in range(40)]}
    with _fake_vision(payload):
        res = shopping.extract_items_from_photo("b64", "image/jpeg")
    names = [c['name'].lower() for c in res['candidates']]
    check(names.count('milk') == 1, "duplicate candidates collapse")
    check(len(res['candidates']) <= 25, f"candidate list is capped, got {len(res['candidates'])}")


# --- both agent stacks -------------------------------------------------------

def scenario_tools_registered_in_both_stacks():
    _reset()
    from services import agent_tools, agent_tools_v2
    want = {"add_shopping_items", "get_shopping_list_items",
            "check_off_shopping_item", "remove_shopping_item_by_name"}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 (widget/Gemma) is missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS), "v1 schemas incomplete")
    check(want <= set(agent_tools.TOOL_HANDLERS), "v1 handlers incomplete")
    # v1 handlers must actually reach the same implementation.
    agent_tools.execute_tool("add_shopping_items", {"items": "salt"})
    lid = storage.ensure_default_shopping_list()['id']
    check([i['name'] for i in storage.get_shopping_items(lid)] == ["salt"],
          "the v1 bridge writes through to the same storage as v2")


# --- the page itself ---------------------------------------------------------
# Every UI bug in this arc so far has been invisible to the backend suite: a
# dead confirm dialog, an unreachable editor, and a `this.loadRepertoire()`
# call left pointing at a function a refactor deleted (which surfaced to the
# family as "Could not add that" while the save had actually worked). These
# are cheap static checks against exactly that class of failure.

def _shopping_html():
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(os.path.dirname(here), 'templates', 'shopping.html')
    with open(path, encoding='utf-8') as f:
        return f.read()


def scenario_every_referenced_method_exists():
    import re
    src = _shopping_html()
    body = src[src.index('function shoppingPage()'):]

    defined = set(re.findall(r'\n\s+(?:async\s+)?(\w+)\s*\(', body))
    defined |= set(re.findall(r'\n\s+(\w+)\s*:', body))          # data props
    defined |= set(re.findall(r'\bget\s+(\w+)\s*\(', body))      # getters

    called = set(re.findall(r'this\.(\w+)\s*\(', body))
    missing = called - defined
    check(not missing,
          f"the component calls methods it does not define: {sorted(missing)}")

    # Same for handlers wired from markup.
    markup = src[:src.index('function shoppingPage()')]
    from_markup = set(re.findall(r'[@:]?\w*click="(\w+)\(', markup))
    from_markup |= set(re.findall(r'x-text="(\w+)\(', markup))
    from_markup |= set(re.findall(r'x-show="(\w+)\(', markup))
    globals_ok = {'showGlobalAlert', 'promptConfirm', 'promptInput'}
    missing_ui = from_markup - defined - globals_ok
    check(not missing_ui,
          f"markup wires handlers that do not exist: {sorted(missing_ui)}")


def scenario_dialog_helpers_are_called_with_a_message():
    """promptConfirm/promptInput dereference `message` unconditionally, so a
    one-argument call throws inside the promise executor: it never settles,
    the await parks forever, and the button silently does nothing."""
    import re
    src = _shopping_html()
    bad = []
    for fn in ('promptConfirm', 'promptInput'):
        for m in re.finditer(r'(?<![\w.])' + fn + r'\s*\(', src):
            depth, args, in_s, esc = 0, 1, None, False
            for ch in src[m.end() - 1:]:
                if esc:
                    esc = False
                    continue
                if ch == '\\':
                    esc = True
                    continue
                if in_s:
                    if ch == in_s:
                        in_s = None
                    continue
                if ch in '"\'`':
                    in_s = ch
                    continue
                if ch in '([{':
                    depth += 1
                elif ch in ')]}':
                    depth -= 1
                    if depth == 0:
                        break
                elif ch == ',' and depth == 1:
                    args += 1
            if args < 2:
                bad.append(f"{fn} at offset {m.start()}")
    check(not bad, f"single-argument dialog calls fail SILENTLY: {bad}")


def scenario_api_calls_go_through_apibase():
    """Bare relative fetches break under Home Assistant ingress."""
    import re
    src = _shopping_html()
    bare = re.findall(r"fetch\(\s*['\"]api/", src)
    check(not bare, f"{len(bare)} fetch call(s) skip apiBase")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    passed = 0
    for fn in SCENARIOS:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(SCENARIOS)} shopping scenarios passed")
