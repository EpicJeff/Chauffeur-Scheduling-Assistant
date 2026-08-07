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


def scenario_the_interview_generates_rather_than_records():
    """The difference between planning help and a form. Answering headcount
    does not store a number - it scales every plate inside the window."""
    reset_db(); _members(); _settings()
    o = _occasion()
    iv = occasions.interview(o['id'])
    check([q['key'] for q in iv['questions']][:2] == ['headcount', 'cooking_hands'],
          f"it asks the things that cascade first, got {iv['questions']}")

    res = occasions.answer(o['id'], 'headcount', 16)
    check(res['generated'], f"answering generates work, got {res}")
    plate = storage.get_plate(DAY) or {}
    check(plate.get('serving_for') == 16,
          f"the anchor day is cooking for 16, got {plate.get('serving_for')}")
    edge = storage.get_plate(WIN_END) or {}
    check(edge.get('serving_for') == 16, "and so is the last day of the window")
    check(not storage.get_plate('2026-12-05'), "while a day outside it is untouched")


def scenario_headcount_never_overwrites_a_specific_statement():
    """A general answer must not stamp over what somebody said about one night."""
    reset_db(); _members(); _settings()
    o = _occasion()
    meals.set_plate_hosting(DAY, serving_for=6, cooks=1)
    occasions.answer(o['id'], 'headcount', 16)
    check((storage.get_plate(DAY) or {}).get('serving_for') == 6,
          "the night the family set by hand keeps its own number")
    check((storage.get_plate(WIN_END) or {}).get('serving_for') == 16,
          "and the rest of the window still takes the answer")


def scenario_the_report_is_a_diff_not_an_inventory():
    """A list of what exists cannot answer "have I forgotten anything" - the
    gap is invisible by construction."""
    reset_db(); _members(); _settings()
    o = occasions.create("Ellie's 8th", '2026-09-14', 'birthday')
    occasions.answer(o['id'], 'cake', True)
    keys = {g['key'] for g in occasions.gap_report(o['id'])['gaps']}
    check('cake' in keys and 'party_supplies' in keys,
          f"it names what is missing, got {keys}")

    occasions.apply_template(o['id'])
    after = {g['key'] for g in occasions.gap_report(o['id'])['gaps']}
    check('cake' not in after,
          f"and stops naming it once the errand exists, got {after}")
    errs = [e for e in storage.get_all_errands() if e.get('occasion_key') == 'cake']
    check(len(errs) == 1 and errs[0]['window_days'] >= 1,
          f"the errand carries a real deadline, got {errs}")


def scenario_unanswered_is_not_no():
    """A family that has not been asked about a cake must not be told they are
    missing one. That is how a report becomes noise instead of a signal."""
    reset_db(); _members(); _settings()
    o = occasions.create("Ellie's 8th", '2026-09-14', 'birthday')
    keys = {g['key'] for g in occasions.gap_report(o['id'])['gaps']}
    check('cake' not in keys, f"silence is not a yes, got {keys}")
    occasions.answer(o['id'], 'cake', False)
    keys = {g['key'] for g in occasions.gap_report(o['id'])['gaps']}
    check('cake' not in keys, "and an explicit no keeps it out too")


def scenario_a_settled_decision_stops_coming_back():
    reset_db(); _members(); _settings()
    o = occasions.create("Ellie's 8th", '2026-09-14', 'birthday')
    check('party_supplies' in {g['key'] for g in occasions.gap_report(o['id'])['gaps']},
          "it starts on the list")
    occasions.dismiss(o['id'], 'party_supplies')
    check('party_supplies' not in {g['key'] for g in occasions.gap_report(o['id'])['gaps']},
          "and a waved-off line never comes back")


def scenario_last_year_surfaces_what_the_template_never_knew():
    """The rented tables nobody thought to model. Only the prior instance can
    show that kind of absence."""
    reset_db(); _members(); _settings()
    from models.schemas import Errand
    last = occasions.create('Thanksgiving 2025', '2025-11-27', 'thanksgiving')
    storage.add_errand(Errand(title='Collect the rented tables - Thanksgiving 2025',
                              duration_mins=30, location='Rentals',
                              occasion_id=last['id']).model_dump())
    this = occasions.create('Thanksgiving 2026', DAY, 'thanksgiving')
    check(this['prior_occasion_id'] == last['id'], "linked to last year")

    rep = occasions.gap_report(this['id'])
    prior_gaps = [g for g in rep['gaps'] if g['source'] == 'prior']
    check(any('rented tables' in g['label'] for g in prior_gaps),
          f"last year's line shows as missing, got {prior_gaps}")
    check(all('had this' in (g.get('note') or '') for g in prior_gaps),
          "and says where it came from")
    check(rep['has_prior'], "the report knows it had something to compare with")


def scenario_gaps_are_ordered_by_slack_and_carry_no_percentage():
    reset_db(); _members(); _settings()
    o = occasions.create("Ellie's 8th", '2026-09-14', 'birthday')
    occasions.answer(o['id'], 'cake', True)
    occasions.answer(o['id'], 'gifts', True)
    rep = occasions.gap_report(o['id'])
    slacks = [g['slack_days'] for g in rep['gaps']]
    check(slacks == sorted(slacks), f"tightest first, got {slacks}")
    check('percent' not in str(rep) and 'pct' not in str(rep),
          "and nothing anywhere is a percentage")


def scenario_the_watcher_anticipates_but_does_not_nag():
    """Anticipation is the half of the load a page cannot carry - but only
    inside a lead window, and never about a settled decision."""
    import datetime as _dt
    reset_db(); _members(); _settings()
    from services import watchers
    soon = (_dt.date.today() + _dt.timedelta(days=2)).isoformat()
    o = occasions.create('Ellie birthday', soon, 'birthday')
    occasions.answer(o['id'], 'cake', True)
    keys = [k for k, _ in watchers._occasion_findings(_dt.datetime.now())]
    check(any(k.startswith('occasion_gap:') for k in keys),
          f"a party in two days with an unbought cake gets a nudge, got {keys}")

    far = (_dt.date.today() + _dt.timedelta(days=200)).isoformat()
    o2 = occasions.create('Christmas', far, 'christmas')
    occasions.answer(o2['id'], 'gifts', True)
    keys2 = [k for k, _ in watchers._occasion_findings(_dt.datetime.now())]
    check(not any(o2['id'] in k for k in keys2),
          "but something 200 days out is not a heads-up, it is nagging")


def scenario_the_gap_report_is_sayable():
    reset_db(); _members(); _settings()
    from services import agent_tools, agent_tools_v2
    check('get_occasion_gaps' in {t['name'] for t in agent_tools_v2.get_available_tools()}
          and 'get_occasion_gaps' in agent_tools.TOOL_HANDLERS,
          "the tool is in both stacks")
    o = occasions.create("Ellie's 8th", '2026-09-14', 'birthday')
    occasions.answer(o['id'], 'cake', True)
    res = agent_tools.execute_tool('get_occasion_gaps', {'occasion_name': 'Ellie'})
    check('cake' in res['message'].lower(),
          f"it names what is missing, got {res['message']}")
    check('%' not in res['message'], "and quotes no percentage")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} occasion scenarios passed")
