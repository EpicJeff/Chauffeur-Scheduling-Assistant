"""Two spans, and a list that can be taken back off (meals arc M10).

The family's report, from using it: the plan for the NEXT shop only existed
inside the lead window — two days before the trip — so an idea landing on a
Monday had nowhere to go, and the list could not be built against the coming
run at all. Worse, in planning mode the window STARTED on the shop date, so the
last nights before the trip belonged to neither span and vanished off the page.

Opening the next span all week is only safe if changing your mind takes the
ingredients back off, or a plan you can edit for six days is a plan you buy for
twice. That is what claims are: every night that wants a row is recorded on it,
and an ingredient stays while any planned night still wants the dish that
brought it.

Matching is by DISH and not by (dish, night), and that is the load-bearing
choice. Plans change at the drop of a hat; what actually happens is that a meal
gets punted to another day and everything shifts. Per-night matching would
strip the list every time that happened.

Three things are never removed — a person's own item, something already in the
cart, and a row nobody can account for — and there is a scenario for each,
because each is a different way to throw away somebody's shopping.

Run from chauffeur/:  python tests/test_meal_runs.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# test_meals owns the temp data dir, the category seed and the dish factory.
# Re-implementing them here would be a second fixture drifting from the first.
from test_meals import check, reset_db, _seed_people, _settings, _dish  # noqa: E402
from services import storage, meals  # noqa: E402
from services import shopping as _shop  # noqa: E402

MONDAY = datetime.date(2026, 8, 10)       # the shop is Saturday the 15th


def _claim_pantry():
    """Two dinners that share an ingredient and each have one of their own —
    the only shape that can tell a correct un-add from a lucky one."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_cadence_days=7,
              sides_per_meal=0, include_dessert=False)
    chicken = _dish("roasted chicken", short_name="chicken", type='meal',
                    finish_mins=20, ingredients=[
                        {'name': 'chicken thighs', 'kind': 'fresh'},
                        {'name': 'olive oil', 'kind': 'fresh'}])
    stirfry = _dish("chicken stir fry", short_name="stir fry", type='meal',
                    finish_mins=20, ingredients=[
                        {'name': 'chicken thighs', 'kind': 'fresh'},
                        {'name': 'snow peas', 'kind': 'fresh'}])
    return chicken, stirfry


def _open_names(list_id=None):
    return sorted((i.get('name') or '') for i in
                  storage.get_shopping_items(list_id, include_checked=False))


def scenario_every_night_that_wants_an_ingredient_claims_it():
    """The bug under all of this: a second dish asking for something already on
    the list was skipped outright, so the row remembered only whoever asked
    first. One row, two claims — bought once, wanted twice."""
    chicken, stirfry = _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    meals.pin_plate('2026-08-17', [chicken])
    meals.pin_plate('2026-08-20', [stirfry])
    meals.dishes_to_shopping([chicken], lst, date_str='2026-08-17')
    meals.dishes_to_shopping([stirfry], lst, date_str='2026-08-20')

    rows = [i for i in storage.get_shopping_items(lst, include_checked=False)
            if i['name'] == 'chicken thighs']
    check(len(rows) == 1, f"chicken thighs bought twice: {len(rows)} rows")
    claims = rows[0].get('claims') or []
    check({c['dish_id'] for c in claims} == {chicken['id'], stirfry['id']},
          f"both nights have to claim the row, got {claims}")


def scenario_changing_a_night_takes_its_ingredients_back_off():
    """What the family asked for, and had wanted several times. Drop the stir
    fry and the snow peas go with it — but NOT the chicken thighs, which the
    other night still wants."""
    chicken, stirfry = _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    meals.pin_plate('2026-08-17', [chicken])
    meals.pin_plate('2026-08-20', [stirfry])
    meals.dishes_to_shopping([chicken], lst, date_str='2026-08-17')
    meals.dishes_to_shopping([stirfry], lst, date_str='2026-08-20')
    check('snow peas' in _open_names(lst), "setup: the peas never made it on")

    meals.remove_from_plate('2026-08-20', stirfry['id'])
    names = _open_names(lst)
    check('snow peas' not in names, f"the peas stayed after the dish went: {names}")
    check('chicken thighs' in names,
          f"the other night still wants chicken and it was taken off anyway: {names}")
    check('olive oil' in names, f"an untouched night lost its ingredient: {names}")


def scenario_punting_a_meal_to_another_night_costs_nothing():
    """Plans change at the drop of a hat, and what actually happens is that a
    meal gets punted and everything shifts. Matching claims per-NIGHT would
    strip the list every time; matching by dish is why it does not."""
    _chicken, stirfry = _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    meals.pin_plate('2026-08-20', [stirfry])
    meals.dishes_to_shopping([stirfry], lst, date_str='2026-08-20')

    meals.arrange_week([{'date': '2026-08-20', 'dish_ids': []},
                        {'date': '2026-08-21', 'dish_ids': [stirfry['id']]}])
    check('snow peas' in _open_names(lst),
          "moving a dinner to the next night unbought its ingredients")


def scenario_a_persons_own_item_is_never_taken_off():
    """Somebody saying "we're out of chicken thighs" is not a consequence of
    the meal plan and does not evaporate when the meal plan changes."""
    from models.schemas import ShoppingItem
    chicken, _stirfry = _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    storage.add_shopping_item(ShoppingItem(
        list_id=lst, name='chicken thighs', added_via='voice').model_dump())
    meals.pin_plate('2026-08-17', [chicken])
    meals.dishes_to_shopping([chicken], lst, date_str='2026-08-17')
    meals.remove_from_plate('2026-08-17', chicken['id'])
    check('chicken thighs' in _open_names(lst),
          "a hand-added need was deleted because a dish shared its name")


def scenario_something_already_bought_is_never_taken_off():
    """The mid-week top-up: bought on Wednesday, Thursday's dinner changes.
    Rewriting the list to pretend it was never bought helps nobody."""
    chicken, _stirfry = _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    meals.pin_plate('2026-08-17', [chicken])
    meals.dishes_to_shopping([chicken], lst, date_str='2026-08-17')
    row = next(i for i in storage.get_shopping_items(lst)
               if i['name'] == 'chicken thighs')
    storage.check_shopping_item(row['id'], True)

    meals.remove_from_plate('2026-08-17', chicken['id'])
    after = storage.get_shopping_item(row['id'])
    check(after and after.get('is_checked'),
          "an item already in the cart was removed when the plan changed")


def scenario_an_item_nobody_can_account_for_is_left_alone():
    """A meal item from before claims existed carries none. Unexplained is not
    the same as unwanted, and guessing wrong throws away real shopping."""
    from models.schemas import ShoppingItem
    _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    storage.add_shopping_item(ShoppingItem(
        list_id=lst, name='mystery paste', added_via='meal',
        source_meal_id='a-dish-that-no-longer-exists').model_dump())
    meals.reconcile_claims()
    check('mystery paste' in _open_names(lst),
          "a claimless meal item was deleted rather than left alone")


def scenario_the_window_holds_both_spans():
    """Both, always. The next shop's plan used to exist only inside the lead
    window, and planning mode started ON the shop date — so the last nights
    before the trip belonged to neither span."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_plan_lead_days=2, grocery_cadence_days=7)
    win = meals.plan_window(storage.get_settings(), MONDAY)
    spans = {s['key']: s for s in win['spans']}
    check(set(spans) == {'current', 'next'}, f"two spans, got {list(spans)}")
    check(spans['current']['start'] == '2026-08-10' and spans['current']['days'] == 5,
          f"the current span runs out at the trip, got {spans['current']}")
    check(spans['next']['start'] == '2026-08-15' and spans['next']['days'] == 7,
          f"the next span starts at the shop, got {spans['next']}")
    check(win['start'] == '2026-08-15' and win['days'] == 7,
          "start/days must keep pointing at the span being bought for")

    thursday = datetime.date(2026, 8, 13)
    cur = next(s for s in meals.plan_window(storage.get_settings(), thursday)['spans']
               if s['key'] == 'current')
    check(cur['days'] == 2,
          f"the nights before the trip belong to the current span, got {cur}")


def scenario_the_cadence_decides_how_many_nights_a_shop_covers():
    """Seven for most families, which is why it was hardcoded — but a household
    that shops every ten days had three nights a cycle nothing bought for."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_cadence_days=10)
    win = meals.plan_window(storage.get_settings(), MONDAY)
    check(win['days'] == 10 and win['cadence_days'] == 10, f"got {win['days']}")
    nxt = next(s for s in win['spans'] if s['key'] == 'next')
    check(nxt['days'] == 10, f"the bought-for span is the cadence, got {nxt}")


def scenario_a_night_before_the_shop_is_a_top_up_not_the_big_run():
    """The run that buys for a night is the one BEFORE it. A night falling
    before the next run means the plan changed after the shopping was done, and
    what it needs cannot wait for Saturday."""
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_cadence_days=7)
    s = storage.get_settings()
    check(meals.buy_on_for('2026-08-12', s, MONDAY) == '2026-08-10',
          "a night before the next run is a top-up, bought as soon as possible")
    check(meals.buy_on_for('2026-08-16', s, MONDAY) == '2026-08-15',
          "a night inside the next span is bought on that run")
    check(meals.buy_on_for('2026-08-24', s, MONDAY) == '2026-08-22',
          "a night beyond it is bought on the run before it, not the next one")


def scenario_the_list_splits_by_the_trip_it_is_for():
    """A mid-week dash for tonight's re-planned dinner must not arrive carrying
    all of Saturday — and the rest is offered rather than hidden, because
    standing in a store is the best moment to be asked."""
    from models.schemas import ShoppingItem
    reset_db(); _seed_people()
    _settings(grocery_weekday=5, grocery_cadence_days=7)
    lst = storage.ensure_default_shopping_list()['id']
    for name, when in (('heavy cream', '2026-08-10'), ('ground beef', '2026-08-15')):
        storage.add_shopping_item(ShoppingItem(
            list_id=lst, name=name, added_via='meal', buy_on=when).model_dump())
    storage.add_shopping_item(ShoppingItem(list_id=lst, name='milk').model_dump())

    runs = _shop.item_runs(lst, MONDAY)
    groups = {g['key']: [i['name'] for i in g['items']] for g in runs['groups']}
    check(runs['top_up'], "a needed-sooner item did not register as a top-up")
    check(groups.get('now') == ['heavy cream'],
          f"the top-up carries only what cannot wait, got {groups.get('now')}")
    check(sorted(groups.get('next') or []) == ['ground beef', 'milk'],
          f"an item added by hand belongs to the next run, got {groups.get('next')}")


def scenario_approving_the_span_buys_for_the_run_that_covers_it():
    """The whole point of the arc, end to end: the coming trip's nights are
    pinned, their ingredients land on the list, and every one of them is marked
    for the run that has to buy it."""
    chicken, _stirfry = _claim_pantry()
    lst = storage.ensure_default_shopping_list()['id']
    res = meals.approve_week('2026-08-15', 3, lst)
    check(res['day_count'] == 3, f"the span was not pinned, got {res}")
    rows = storage.get_shopping_items(lst, include_checked=False)
    check(rows, "approving the span bought nothing at all")
    stray = [i['name'] for i in rows if i.get('buy_on') != '2026-08-15']
    check(not stray, f"items landed on the wrong run: {stray}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} meal-run scenarios passed")
