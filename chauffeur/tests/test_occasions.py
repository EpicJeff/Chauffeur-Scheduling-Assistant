"""Occasions arc O1 — the occasion as CONTEXT, not a container.

The rules under test are the ones the design brief spent the most argument on:
membership attaches to the coarsest wholly-owned entity, eligibility is not
selection, and deleting the context never deletes the work.
"""
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_occasions_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage, maps, meals, occasions  # noqa: E402


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage._distance_mem_cache = None
    maps.get_travel_time_minutes = lambda a, b, *args, **kw: (
        0 if (a or "").lower() == (b or "").lower() else 15)

DAY = '2026-11-26'
WIN_START = '2026-11-25'
WIN_END = '2026-11-29'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _settings(**over):
    base = {"calendar_ids": ["primary"], "home_location": "1 Home St"}
    base.update(over)
    storage.get_settings = lambda: base
    return base


def _members():
    from models.schemas import FamilyMember
    for name, role in (('Dad', 'parent'), ('Mum', 'parent'), ('Ellie', 'child')):
        storage.add_member(FamilyMember(name=name, role=role).model_dump())


def _occasion(**kw):
    return occasions.create(kw.pop('title', 'Thanksgiving 2026'),
                            kw.pop('anchor_date', DAY),
                            kw.pop('kind', 'thanksgiving'),
                            kw.pop('window_start', WIN_START),
                            kw.pop('window_end', WIN_END),
                            kw.pop('dish_tags', ['thanksgiving']), **kw)


def _dish(name, **kw):
    from models.schemas import Dish
    d = Dish(name=name, **kw).model_dump()
    storage.add_dish(d)
    return d


def scenario_the_window_is_a_range_never_an_empty_one():
    """An occasion with no window is its own anchor day. An empty range would
    make every "is this in the window" test silently false, which is the kind
    of bug that looks like the feature simply not working."""
    reset_db()
    bare = occasions.create('Ellie birthday', DAY, 'birthday')
    lo, hi = occasions.window(bare)
    check(lo.isoformat() == DAY and hi.isoformat() == DAY,
          f"a bare occasion covers its own day, got {lo}–{hi}")
    check(occasions.covers(bare, DAY), "and covers it")
    check(not occasions.covers(bare, '2026-11-27'), "and nothing else")


def scenario_eligibility_is_not_selection():
    """THE line the whole arc draws. A window makes holiday dishes AVAILABLE;
    it must not propose turkey for four days running."""
    reset_db(); _members()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('roast turkey', type='entree', scope='occasion', tags=['thanksgiving'])
    _dish('tacos', type='entree')
    _dish('steamed broccoli', type='side', side_type='vegetable')

    before = {d['name'] for d in meals.compose_plate(DAY)}
    check('roast turkey' not in before,
          f"with no occasion the turkey stays put away, got {before}")

    _occasion()
    week = meals.compose_week(WIN_START, 5)
    served = [{x['name'] for x in d['dishes']} for d in week]
    check(any('roast turkey' in s for s in served),
          f"inside the window it becomes eligible, got {served}")
    turkey_days = sum(1 for s in served if 'roast turkey' in s)
    check(turkey_days < len(served),
          f"but the week is not turkey every night, got {turkey_days}/{len(served)}")

    after = {d['name'] for d in meals.compose_plate('2026-12-05')}
    check('roast turkey' not in after,
          f"and outside the window it is put away again, got {after}")


def scenario_a_tag_the_occasion_does_not_name_stays_shut():
    """The window opens the tags it names, not every occasion dish in the
    cupboard — Thanksgiving must not put the birthday cake in play."""
    reset_db(); _members()
    _settings(sides_per_meal=1, include_dessert=True)
    _dish('roast turkey', type='entree', scope='occasion', tags=['thanksgiving'])
    _dish('birthday cake', type='dessert', scope='occasion', tags=['birthday'])
    _dish('tacos', type='entree')
    _dish('fresh fruit', type='dessert')
    _occasion()

    names = {d['name'] for day in meals.compose_week(WIN_START, 5)
             for d in day['dishes']}
    check('birthday cake' not in names,
          f"the cake belongs to a different occasion, got {names}")


def scenario_a_guests_allergy_binds_like_a_family_members():
    """Without this the guest list is decorative — and it is the whole reason
    the list exists, given the arc deliberately sends no invitations."""
    reset_db(); _members()
    _settings(sides_per_meal=1, include_dessert=False)
    _dish('shrimp curry', type='entree', tags=['shellfish'])
    _dish('tacos', type='entree')
    _dish('rice', type='side', side_type='starch')
    o = _occasion()

    occasions.add_guest(o['id'], 'the Wilsons', 4, dietary_avoid=['shellfish'])
    names = {d['name'] for d in meals.compose_plate(DAY)}
    check('shrimp curry' not in names,
          f"nothing a guest cannot eat is proposed, got {names}")
    check(occasions.headcount(o['id']) == 7,
          f"three of us plus four of them, got {occasions.headcount(o['id'])}")


def scenario_membership_is_list_level_with_one_documented_exception():
    """Tag the list, not the item — except on the standing grocery list, which
    the occasion owns only part of."""
    reset_db()
    from models.schemas import ShoppingList, ShoppingItem
    o = _occasion()
    party = ShoppingList(name='Shark party', occasion_id=o['id']).model_dump()
    storage.add_shopping_list(party)
    storage.add_shopping_item(ShoppingItem(list_id=party['id'], name='favour bags').model_dump())

    standing = ShoppingList(name='Groceries', is_default=True).model_dump()
    storage.add_shopping_list(standing)
    storage.add_shopping_item(ShoppingItem(list_id=standing['id'], name='milk').model_dump())
    storage.add_shopping_item(ShoppingItem(list_id=standing['id'], name='turkey',
                                           occasion_id=o['id']).model_dump())

    c = occasions.contents(o['id'])
    check([l['name'] for l in c['lists']] == ['Shark party'],
          f"the party's own list belongs to it, got {c['lists']}")
    check([i['name'] for i in c['loose_items']] == ['turkey'],
          f"and only the tagged item off the standing list, got {c['loose_items']}")


def scenario_deleting_the_context_never_deletes_the_work():
    """Nothing lives inside an occasion, so nothing may be lost with it. A
    family that believes otherwise will never delete one."""
    reset_db()
    from models.schemas import ShoppingList, ShoppingItem, Errand
    o = _occasion()
    lst = ShoppingList(name='Shark party', occasion_id=o['id']).model_dump()
    storage.add_shopping_list(lst)
    storage.add_shopping_item(ShoppingItem(list_id=lst['id'], name='favour bags').model_dump())
    err = Errand(title='pick up the cake', duration_mins=20, location='Bakery',
                 occasion_id=o['id']).model_dump()
    storage.add_errand(err)

    storage.delete_occasion(o['id'])
    check(not storage.get_occasion(o['id']), "the occasion is gone")
    kept = storage.get_shopping_lists()
    check([l['name'] for l in kept] == ['Shark party'], f"the list survives, got {kept}")
    check(kept[0].get('occasion_id') is None, "with its link cleared")
    errs = storage.get_all_errands()
    check(len(errs) == 1 and errs[0].get('occasion_id') is None,
          f"and so does the errand, got {errs}")
    check(len(storage.get_shopping_items(lst['id'])) == 1, "items untouched")


def scenario_carryover_links_backwards_and_only_on_a_real_match():
    """A wrong link is worse than none — it would diff Thanksgiving against a
    birthday — so the bar is match or nothing, never nearest."""
    reset_db()
    last = occasions.create('Thanksgiving 2025', '2025-11-27', 'thanksgiving')
    party = occasions.create('Ellie birthday', '2026-03-02', 'birthday')
    this = occasions.create('Thanksgiving 2026', DAY, 'thanksgiving')
    check(this['prior_occasion_id'] == last['id'],
          f"it finds last year's, got {this.get('prior_occasion_id')}")
    check(party['prior_occasion_id'] is None,
          "and a first birthday links to nothing rather than to a guess")
    check(last['prior_occasion_id'] is None, "links only ever go backwards")


def scenario_the_tools_are_in_both_stacks_and_speak_plainly():
    reset_db(); _members()
    _settings()
    from services import agent_tools, agent_tools_v2
    want = {'add_occasion', 'get_occasion', 'add_occasion_guests',
            'source_for_occasion'}
    v2 = {t['name'] for t in agent_tools_v2.get_available_tools()}
    check(want <= v2, f"v2 missing {want - v2}")
    check(want <= set(agent_tools.TOOL_SCHEMAS)
          and want <= set(agent_tools.TOOL_HANDLERS),
          f"v1 missing {want - set(agent_tools.TOOL_HANDLERS)}")

    agent_tools.execute_tool('add_occasion', {
        'title': 'Thanksgiving 2026', 'anchor_date': DAY, 'kind': 'thanksgiving',
        'window_start': WIN_START, 'window_end': WIN_END,
        'dish_tags': 'thanksgiving'})
    rows = storage.get_occasions()
    check(len(rows) == 1 and rows[0]['title'] == 'Thanksgiving 2026',
          f"the v1 bridge writes through, got {rows}")

    res = agent_tools.execute_tool('add_occasion_guests', {
        'occasion_name': 'Thanksgiving', 'who': 'the Wilsons',
        'headcount': 4, 'cannot_eat': 'shellfish'})
    check('7 eating' in res['message'],
          f"and answers with the new headcount, got {res['message']}")
    check('shellfish' in res['message'], "naming what it will keep off the plan")

    read = agent_tools.execute_tool('get_occasion', {'occasion_name': 'Thanksgiving'})
    check('the Wilsons' in read['message'], f"the read-back is plain, got {read}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} occasion scenarios passed")
