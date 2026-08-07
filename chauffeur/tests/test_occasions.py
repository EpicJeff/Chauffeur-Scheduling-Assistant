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
    _seed_categories()
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


def _members(with_helper=False):
    from models.schemas import FamilyMember
    roster = [('Dad', 'parent'), ('Mum', 'parent'), ('Ellie', 'child')]
    if with_helper:
        roster.append(('Marta', 'helper'))
    for name, role in roster:
        storage.add_member(FamilyMember(name=name, role=role).model_dump())


def _occasion(**kw):
    return occasions.create(kw.pop('title', 'Thanksgiving 2026'),
                            kw.pop('anchor_date', DAY),
                            kw.pop('kind', 'thanksgiving'),
                            kw.pop('window_start', WIN_START),
                            kw.pop('window_end', WIN_END),
                            kw.pop('dish_tags', ['thanksgiving']), **kw)


def _member_id(name):
    return next(m['id'] for m in storage.get_all_members() if m['name'] == name)


# The family vocabulary these scenarios compose against, mirroring the old
# fixed taxonomy one-for-one so occasion behaviour is unchanged by v2.108.
_OCCASION_CATEGORIES = [('protein', 1, 1, False), ('vegetables', 1, 1, False),
                        ('starches/carbs', 1, 1, False),
                        ('something sweet', 0, 1, True)]
_LEGACY_TO_CATEGORY = {'entree': 'protein', 'vegetable': 'vegetables',
                       'starch': 'starches/carbs', 'salad': 'vegetables',
                       'other': 'starches/carbs', 'dessert': 'something sweet'}


def _seed_categories():
    import time as _t
    for i, (name, lo, hi, with_meal) in enumerate(_OCCASION_CATEGORIES):
        storage.save_dish_category({
            'id': 'cat-' + name.split('/')[0].replace(' ', '-'), 'name': name,
            'description': '', 'min_per_plate': lo, 'max_per_plate': hi,
            'with_complete_meal': with_meal, 'order': i, 'created_at': _t.time()})
    storage.set_app_state('dish_categories_seeded', True)


def _category_id(name):
    return next(c['id'] for c in storage.get_dish_categories() if c['name'] == name)


def _dish(name, **kw):
    """Legacy `type=`/`side_type=` are translated to the family's categories."""
    from models.schemas import Dish
    if not storage.get_dish_categories():
        _seed_categories()
    legacy_type = kw.pop('type', None)
    legacy_side = kw.pop('side_type', None)
    if legacy_type == 'meal':
        kw['type'] = 'meal'
    elif legacy_type is not None or legacy_side is not None:
        kw['type'] = 'dish'
        cat = _LEGACY_TO_CATEGORY.get(legacy_side or legacy_type or '')
        if cat and not kw.get('category_ids'):
            kw['category_ids'] = [_category_id(cat)]
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


# --- O3: the planning intelligence -------------------------------------------

def scenario_the_imbalance_is_named_never_scored():
    """The research this arc came from is about WHO carries it. Every other
    product ships a shared checklist and calls that equity."""
    reset_db(); _members(); _settings()
    from models.schemas import Errand
    o = _occasion()
    for i in range(5):
        storage.add_errand(Errand(title=f'job {i}', duration_mins=30, location='X',
                                  occasion_id=o['id'],
                                  required_drivers=['mom']).model_dump())
    rows = occasions.insights(o['id'])['insights']
    load = [r for r in rows if r['kind'] == 'load']
    check(load and 'mom' in load[0]['text'],
          f"it names who is carrying it, got {load}")
    check('%' not in load[0]['text'] and 'score' not in load[0]['text'].lower(),
          "stated, never scored")


def scenario_three_jobs_is_not_a_fairness_problem():
    reset_db(); _members(); _settings()
    from models.schemas import Errand
    o = _occasion()
    for i in range(3):
        storage.add_errand(Errand(title=f'job {i}', duration_mins=30, location='X',
                                  occasion_id=o['id'],
                                  required_drivers=['mom']).model_dump())
    rows = occasions.insights(o['id'])['insights']
    check(not [r for r in rows if r['kind'] == 'load'],
          "a short list is not an imbalance worth raising")


def scenario_an_undecided_thing_carries_what_waiting_costs():
    """The app cannot decide. Making the price of not deciding concrete is
    most of the value."""
    reset_db(); _members(); _settings()
    o = occasions.create("Ellie's 8th", '2026-09-14', 'birthday')
    rows = occasions.insights(o['id'])['insights']
    dec = [r for r in rows if r['kind'] == 'decision']
    check(dec, f"the unanswered questions surface as decisions, got {rows}")
    check(any('cake' in d['text'].lower() for d in dec),
          f"including the cake, got {dec}")
    check(all('day' in d['text'] or 'today' in d['text'] or 'past' in d['text']
              for d in dec),
          f"and each says what waiting costs, got {dec}")

    occasions.answer(o['id'], 'cake', True)
    after = [r for r in occasions.insights(o['id'])['insights']
             if r['kind'] == 'decision']
    check(not any('cake' in d['text'].lower() for d in after),
          "a decided thing stops being a decision")


def scenario_a_thaw_pushes_the_buy_date_back_on_its_own():
    """Nobody types this deadline — the meal model already knows."""
    reset_db(); _members(); _settings()
    o = _occasion()
    turkey = _dish('roast turkey', short_name='turkey', type='entree',
                   needs_ahead='thaw', serves=12)
    meals.set_plate_lock(DAY, True, 'Thanksgiving', [turkey['id']])
    rows = occasions.insights(o['id'])['insights']
    lead = [r for r in rows if r['kind'] == 'lead']
    check(lead and lead[0]['dish'] == 'turkey', f"the bird is flagged, got {rows}")
    check(lead[0]['by'] < DAY, f"with a date BEFORE the meal, got {lead[0]['by']}")
    check('bought before' in lead[0]['text'],
          f"and says it has to be bought first, got {lead[0]['text']}")


def scenario_an_ordered_dish_carries_its_lead_time():
    reset_db(); _members(); _settings()
    o = _occasion()
    cake = _dish('celebration cake', short_name='cake', type='dessert',
                 source='ordered', order_lead_mins=4320)     # three days
    meals.set_plate_lock(DAY, True, 'Thanksgiving', [cake['id']])
    lead = [r for r in occasions.insights(o['id'])['insights'] if r['kind'] == 'lead']
    check(lead and '3 day' in lead[0]['text'],
          f"three days ahead, said plainly, got {lead}")


def scenario_insights_fail_one_at_a_time():
    """A broken schedule cache must cost the family the one insight that
    needed it, never the whole panel."""
    reset_db(); _members(); _settings()
    o = _occasion()
    turkey = _dish('roast turkey', short_name='turkey', type='entree',
                   needs_ahead='thaw', serves=12)
    meals.set_plate_lock(DAY, True, 'Thanksgiving', [turkey['id']])
    broken = storage.get_cached_schedule
    storage.get_cached_schedule = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('boom'))
    try:
        rows = occasions.insights(o['id'])['insights']
    finally:
        storage.get_cached_schedule = broken
    check([r for r in rows if r['kind'] == 'lead'],
          f"the food-derived deadline survives a dead cache, got {rows}")


def scenario_insights_are_sayable():
    reset_db(); _members(); _settings()
    from services import agent_tools, agent_tools_v2
    check('get_occasion_insights' in {t['name'] for t in agent_tools_v2.get_available_tools()}
          and 'get_occasion_insights' in agent_tools.TOOL_HANDLERS,
          "the tool is in both stacks")
    o = _occasion()
    turkey = _dish('roast turkey', short_name='turkey', type='entree',
                   needs_ahead='thaw', serves=12)
    meals.set_plate_lock(DAY, True, 'Thanksgiving', [turkey['id']])
    res = agent_tools.execute_tool('get_occasion_insights',
                                   {'occasion_name': 'Thanksgiving'})
    check('thaw' in res['message'].lower(),
          f"it says the useful thing, got {res['message']}")


# --- The menu: curated ahead, in isolation -----------------------------------

def scenario_the_menu_is_the_locked_plate_and_survives_a_repropose():
    """It stores nothing of its own. That is what makes the run sheet, the
    shopping drain and the kitchen totals understand it for free - and a menu
    chosen three weeks out is exactly what `locked` was invented for."""
    reset_db(); _members(); _settings(sides_per_meal=1, include_dessert=False)
    o = _occasion()
    turkey = _dish('roast turkey', short_name='turkey', type='entree',
                   scope='occasion', tags=['thanksgiving'])
    pie = _dish('pumpkin pie', short_name='pie', type='dessert',
                scope='occasion', tags=['thanksgiving'])

    m = occasions.set_menu(o['id'], [turkey['id'], pie['id']])
    check([d['short_name'] for d in m['dishes']] == ['turkey', 'pie'],
          f"the menu is what was chosen, got {m['dishes']}")
    check(m['locked'], "and the night is locked, not merely edited")
    check(storage.get_plate(DAY)['note'] == o['title'],
          "with the occasion as the reason it is spoken for")

    meals.reset_plate(DAY)          # the BULK path, which must refuse
    after = occasions.menu(o['id'])
    check([d['short_name'] for d in after['dishes']] == ['turkey', 'pie'],
          f"a bulk repropose cannot sweep it away, got {after['dishes']}")


def scenario_the_menu_reports_what_it_costs_to_cook():
    """Choosing a menu and finding out it needs two ovens are the same
    decision; splitting them across two screens is how a family finds out on
    the day."""
    reset_db(); _members(); _settings(sides_per_meal=1, include_dessert=False)
    o = _occasion()
    turkey = _dish('roast turkey', short_name='turkey', type='entree',
                   scope='occasion', tags=['thanksgiving'], prep_ahead_mins=20,
                   finish_mins=20, unattended_mins=240, equipment='oven',
                   oven_temp_f=325, serves=12)
    pie = _dish('pumpkin pie', short_name='pie', type='dessert', scope='occasion',
                tags=['thanksgiving'], finish_mins=10, unattended_mins=45,
                equipment='oven', oven_temp_f=425)
    m = occasions.set_menu(o['id'], [turkey['id'], pie['id']])
    check(m['prep_ahead_mins'] + m['finish_mins'] == 50,
          f"hands-on comes back with it, got {m}")
    check(m['unattended_mins'] == 285,
          f"one oven at two temperatures queues, got {m['unattended_mins']}")
    check([c['temp_f'] for c in m['oven_conflicts']] == [325, 425],
          f"and the clash is named, got {m['oven_conflicts']}")


def scenario_another_occasions_dishes_never_enter_the_picker():
    """The birthday cake has no business in the Thanksgiving menu."""
    reset_db(); _members(); _settings()
    thanks = _occasion()
    occasions.create("Ellie's 8th", '2026-09-14', 'birthday', dish_tags=['birthday'])
    _dish('roast turkey', type='entree', scope='occasion', tags=['thanksgiving'])
    _dish('birthday cake', type='dessert', scope='occasion', tags=['birthday'])
    _dish('tacos', type='meal')

    pool = {d['name'] for d in occasions.menu(thanks['id'])['pool']}
    check('roast turkey' in pool, f"its own dishes are offered, got {pool}")
    check('tacos' in pool, "so is the everyday pool")
    check('birthday cake' not in pool,
          f"another occasion's food is not, got {pool}")


def scenario_dishes_added_through_an_occasion_are_born_occasion_only():
    """THE point of curating here: building a Thanksgiving menu must not put
    turkey and stuffing into the list a family looks at on a Tuesday."""
    reset_db(); _members(); _settings()
    o = _occasion()
    from models.schemas import Dish

    def fake(desc):
        made = []
        for name in [n.strip() for n in desc.split(',') if n.strip()]:
            d = Dish(name=name, type='side').model_dump()
            storage.add_dish(d)
            made.append(d)
        return {'added': made, 'existing': []}

    real = meals.add_dishes_from_text
    meals.add_dishes_from_text = fake
    try:
        res = occasions.add_dishes(o['id'], 'cornbread stuffing, cranberry sauce')
    finally:
        meals.add_dishes_from_text = real

    check(len(res['added']) == 2, f"both dishes saved, got {res}")
    for d in res['added']:
        saved = storage.get_dish(d['id'])
        check(saved['scope'] == 'occasion',
              f"{saved['name']} is occasion-only, got {saved['scope']}")
        check('thanksgiving' in saved['tags'],
              f"and carries the occasion's tag, got {saved['tags']}")

    # And therefore invisible to an ordinary night.
    _dish('tacos', type='entree')
    names = {d['name'] for d in meals.compose_plate('2026-12-20')}
    check('cornbread stuffing' not in names,
          f"nothing of it reaches a December Tuesday, got {names}")


def scenario_an_untagged_occasion_still_gets_its_dishes_marked():
    """Otherwise they fall straight back into the everyday pool the moment
    they are saved, which is the failure this whole surface exists to avoid."""
    reset_db(); _members(); _settings()
    o = occasions.create('Street party', '2026-07-04', 'party')   # no dish_tags
    from models.schemas import Dish

    def fake(desc):
        d = Dish(name=desc.strip(), type='side').model_dump()
        storage.add_dish(d)
        return {'added': [d], 'existing': []}

    real = meals.add_dishes_from_text
    meals.add_dishes_from_text = fake
    try:
        res = occasions.add_dishes(o['id'], 'hot dogs')
    finally:
        meals.add_dishes_from_text = real

    saved = storage.get_dish(res['added'][0]['id'])
    check(saved['scope'] == 'occasion', f"still occasion-only, got {saved['scope']}")
    check(saved['tags'], f"and given a tag to be eligible by, got {saved['tags']}")
    check(storage.get_occasion(o['id'])['dish_tags'] == saved['tags'],
          "the occasion adopts the same tag, or it could never open its own food")


def scenario_clearing_a_menu_releases_the_night_but_keeps_the_dishes():
    reset_db(); _members(); _settings(sides_per_meal=1, include_dessert=False)
    o = _occasion()
    turkey = _dish('roast turkey', short_name='turkey', type='entree',
                   scope='occasion', tags=['thanksgiving'])
    occasions.set_menu(o['id'], [turkey['id']])
    occasions.clear_menu(o['id'])
    check(not storage.get_plate(DAY), "the night is released")
    check(storage.get_dish(turkey['id']), "and the dish is untouched")


# --- Attendance: the roster is a decision, not a property -------------------

def scenario_the_whole_roster_is_listed_not_just_the_attendees():
    """The original defect: every non-helper was counted automatically with no
    way to say otherwise. A list you can only ADD to cannot express "Grandad
    isn't coming this year"."""
    reset_db(); _members(with_helper=True); _settings()
    o = _occasion()
    rows = occasions.attendance(o['id'])
    check({r['name'] for r in rows} == {'Dad', 'Mum', 'Ellie', 'Marta'},
          f"every household member is offered, got {[r['name'] for r in rows]}")
    check(all(not r['decided'] for r in rows),
          "and none of them counts as decided until somebody says so")


def scenario_helpers_start_out_and_everyone_else_starts_in():
    """Role decides the DEFAULT only. A helper is external by definition, so
    they start out — and are one tap from being in."""
    reset_db(); _members(with_helper=True); _settings()
    o = _occasion()
    by = {r['name']: r for r in occasions.attendance(o['id'])}
    check(by['Dad']['attending'] and by['Ellie']['attending'],
          "the household is in by default")
    check(not by['Marta']['attending'],
          "the helper is not, until invited")
    check(occasions.headcount(o['id']) == 3,
          f"so the count is the three of them, got {occasions.headcount(o['id'])}")


def scenario_anyone_can_be_toggled_either_way():
    """Role cannot tell a resident adult from a grandparent five hundred miles
    away, which is exactly why these are taps rather than something derived."""
    reset_db(); _members(with_helper=True); _settings()
    o = _occasion()
    occasions.set_attendance(o['id'], _member_id('Dad'), False)
    occasions.set_attendance(o['id'], _member_id('Marta'), True)
    by = {r['name']: r for r in occasions.attendance(o['id'])}
    check(not by['Dad']['attending'], "a parent can be away that week")
    check(by['Marta']['attending'], "and a helper can be genuinely invited")
    check(by['Dad']['decided'] and by['Marta']['decided'],
          "both now read as decided rather than defaulted")
    check(occasions.headcount(o['id']) == 3,
          f"one out, one in, still three, got {occasions.headcount(o['id'])}")


def scenario_a_new_member_takes_the_default_on_occasions_already_booked():
    """Storing only the DECISIONS is what makes this work — a stored attendee
    list would leave somebody added next month silently missing from every
    occasion already on the books."""
    reset_db(); _members(); _settings()
    o = _occasion()
    occasions.set_attendance(o['id'], _member_id('Dad'), False)
    from models.schemas import FamilyMember
    storage.add_member(FamilyMember(name='Baby', role='child').model_dump())
    by = {r['name']: r for r in occasions.attendance(o['id'])}
    check(by['Baby']['attending'] and not by['Baby']['decided'],
          f"the new arrival is in by default, got {by.get('Baby')}")
    check(not by['Dad']['attending'], "and the earlier decision is untouched")


def scenario_attendance_and_guests_both_feed_the_headcount_once():
    """A guest row naming a member must not be counted twice — the roster
    already has them."""
    reset_db(); _members(); _settings()
    o = _occasion()
    occasions.add_guest(o['id'], 'the Wilsons', 4)
    occasions.add_guest(o['id'], 'Ellie', 1, member_id=_member_id('Ellie'))
    check(occasions.headcount(o['id']) == 7,
          f"three of us plus four of them, got {occasions.headcount(o['id'])}")
    occasions.set_attendance(o['id'], _member_id('Mum'), False)
    check(occasions.headcount(o['id']) == 6,
          f"and one fewer when somebody drops out, got {occasions.headcount(o['id'])}")


def scenario_attendance_is_sayable_in_both_stacks():
    reset_db(); _members(with_helper=True); _settings()
    from services import agent_tools, agent_tools_v2
    check('set_occasion_attendance' in {t['name'] for t in agent_tools_v2.get_available_tools()}
          and 'set_occasion_attendance' in agent_tools.TOOL_HANDLERS,
          "the tool is in both stacks")
    _occasion()
    res = agent_tools.execute_tool('set_occasion_attendance', {
        'occasion_name': 'Thanksgiving', 'who': 'Dad', 'coming': False})
    check('not coming' in res['message'] and '2 eating' in res['message'],
          f"it answers with the new headcount, got {res['message']}")

    miss = agent_tools_v2.set_occasion_attendance('Thanksgiving', 'Aunt Jo', False)
    check(miss['status'] == 'error' and 'guest' in miss['message'],
          f"and points a non-member at the guest path, got {miss}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} occasion scenarios passed")
