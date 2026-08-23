"""Supply intake A2 — the deadline spine.

"Add poster board to the list" is worth almost nothing. "The fair is Friday
and your shop run is Saturday" is the whole feature, and it is the piece both
halves of the arc share: the school supply and the birthday gift ask the same
question of the same machinery.

The properties that matter, and why:

  1. **The verdict is computed ONCE, server-side.** `item_runs` (the shopping
     page) and `/api/shopping/items` (the PWA House tab) both read
     `annotate_deadlines`. Two surfaces disagreeing about whether the poster
     board is late is worse than neither saying anything.
  2. **The solver's placement beats the weekday guess.** A shop-day setting is
     an average; a scheduled errand is a decision made against the real week.
  3. **No trip at all is LATE**, and it qualifies a list for the trip offer on
     its own — one tri-fold board needed Friday would never reach the
     five-item weight threshold, and it is the more urgent case.
  4. **Undated items stay ordinary.** Nearly every row has no deadline and
     must gain no chip, no group, and no nagging.
  5. **No count, no percentage, anywhere.** Findings name the ITEM, because
     "2 things are late" is the completion bar in another costume.

Run from chauffeur/:  python tests/test_supply_deadlines.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import shopping as _shop

# A fixed Monday so weekday arithmetic in the assertions is readable.
MONDAY = datetime.date(2026, 8, 24)
WED = MONDAY + datetime.timedelta(days=2)
FRI = MONDAY + datetime.timedelta(days=4)
SAT = MONDAY + datetime.timedelta(days=5)


def _reset():
    with storage.db_lock:
        storage.shopping_items_table.truncate()
        storage.shopping_lists_table.truncate()
        storage.errands_table.truncate()


def _list(**over):
    from models.schemas import ShoppingList
    lst = ShoppingList(name="Groceries", is_default=True,
                       errand_tag="groceries", store="Target").model_dump()
    lst.update(over)
    storage.add_shopping_list(lst)
    return lst


def _item(list_id, name, needed_by=None, **over):
    from models.schemas import ShoppingItem
    it = ShoppingItem(list_id=list_id, name=name,
                      needed_by=needed_by.isoformat() if needed_by else None,
                      **over).model_dump()
    storage.add_shopping_item(it)
    return it


def scenario_a_run_that_lands_in_time_is_not_an_alarm():
    """Property 4 and half of 5: a met deadline is information. It carries a
    verdict so the row can say "by Fri", and `late` is false."""
    _reset()
    lst = _list()
    _item(lst['id'], 'tri-fold board', FRI)
    _item(lst['id'], 'milk')

    rows = _shop.annotate_deadlines(storage.get_shopping_items(lst['id']),
                                    today=MONDAY, run_date=WED.isoformat())
    board = next(r for r in rows if r['name'] == 'tri-fold board')
    milk = next(r for r in rows if r['name'] == 'milk')
    check(board['deadline']['late'] is False and board['deadline']['days_left'] == 4,
          f"Wednesday's run makes Friday comfortably: {board['deadline']}")
    check('deadline' not in milk,
          "an undated row gains nothing at all — no chip, no key, no nagging")


def scenario_a_run_after_the_deadline_is_late():
    """The whole point. Saturday's run cannot serve a Friday deadline."""
    _reset()
    lst = _list()
    _item(lst['id'], 'tri-fold board', FRI)
    rows = _shop.annotate_deadlines(storage.get_shopping_items(lst['id']),
                                    today=MONDAY, run_date=SAT.isoformat())
    d = rows[0]['deadline']
    check(d['late'] is True and d['missed'] is False,
          f"late, but not yet missed — there is still time to act: {d}")
    check(d['run_date'] == SAT.isoformat(),
          "and it says WHICH run, because that is what tells a parent what to do")

    past = _shop.deadline_state({'needed_by': (MONDAY - datetime.timedelta(days=1)).isoformat()},
                                SAT.isoformat(), MONDAY)
    check(past['missed'] is True and past['days_left'] == -1,
          f"a deadline already gone reads as missed, not merely late: {past}")


def scenario_no_trip_at_all_is_late():
    """Property 3. A dated thing on a list with nowhere to happen is the
    quiet failure the whole slice exists to catch."""
    _reset()
    lst = _list()
    _item(lst['id'], 'tri-fold board', FRI)
    runs = _shop.run_dates(lst['id'], MONDAY)
    check(runs['has_trip'] is False, f"no errand bound to this list: {runs}")

    d = _shop.deadline_state({'needed_by': FRI.isoformat()}, None, MONDAY)
    check(d['late'] is True and d['run_date'] is None,
          f"nowhere to buy it is late by definition: {d}")


def scenario_the_solvers_placement_beats_the_weekday_guess():
    """Property 2. A weekday setting is an average; a scheduled errand is a
    decision made against the real week, with the drives accounted for."""
    _reset()
    lst = _list()
    from models.schemas import Errand
    errand = Errand(title="Groceries run", duration_mins=45, location="Target",
                    tags=['groceries'], recurrence_rule='weekly').model_dump()
    storage.add_errand(errand)

    with mock.patch('services.meals.shop_date',
                    return_value=(WED, None, None)), \
         mock.patch('services.storage.get_all_scheduled_errands',
                    return_value={errand['id']: f"{SAT.isoformat()}T10:00:00"}):
        runs = _shop.run_dates(lst['id'], MONDAY)
    check(runs['guess'] == WED.isoformat() and runs['scheduled'] == SAT.isoformat(),
          f"both are reported, because both are true at different moments: {runs}")
    check(runs['next'] == SAT.isoformat(),
          f"but the PLACEMENT is what a deadline is measured against: {runs['next']}")

    # A trip the solver put in the past says nothing about the shop that is coming.
    with mock.patch('services.meals.shop_date',
                    return_value=(WED, None, None)), \
         mock.patch('services.storage.get_all_scheduled_errands',
                    return_value={errand['id']: "2026-08-20T10:00:00"}):
        stale = _shop.run_dates(lst['id'], MONDAY)
    check(stale['next'] == WED.isoformat(),
          f"a placement already gone falls back to the guess: {stale}")


def scenario_both_surfaces_read_one_verdict():
    """Property 1. `item_runs` and the items endpoint must not be able to
    disagree, so they call the same function."""
    import main
    _reset()
    lst = _list()
    _item(lst['id'], 'tri-fold board', FRI)

    with mock.patch('services.meals.shop_date', return_value=(SAT, None, None)):
        runs = _shop.item_runs(lst['id'], MONDAY)
        via_items = main.list_shopping_items(list_id=lst['id'], request=None)

    grouped = [i for g in runs['groups'] for i in g['items']]
    board = next(i for i in grouped if i['name'] == 'tri-fold board')
    check(board['deadline']['late'] is True,
          f"the runs view says late: {board.get('deadline')}")
    other = via_items[0]['deadline']
    check(other['late'] == board['deadline']['late']
          and other['run_date'] == board['deadline']['run_date']
          and other['needed_by'] == board['deadline']['needed_by'],
          f"and the items view says the same thing: {other} vs {board['deadline']}")
    check([r['name'] for r in runs['late']] == ['tri-fold board'],
          f"with a top-level roll-up naming the ITEM, never a count: {runs['late']}")


def scenario_the_now_group_is_never_late():
    """The top-up group IS the go-today trip. Flagging its rows as late would
    be the app arguing with a decision the family already made."""
    _reset()
    lst = _list()
    _item(lst['id'], 'tri-fold board', WED,
          buy_on=MONDAY.isoformat())
    with mock.patch('services.meals.shop_date', return_value=(SAT, None, None)):
        runs = _shop.item_runs(lst['id'], MONDAY)
    now_group = next(g for g in runs['groups'] if g['key'] == 'now')
    check(len(now_group['items']) == 1
          and now_group['items'][0]['deadline']['late'] is False,
          f"the top-up serves it today: {now_group['items'][0].get('deadline')}")


def scenario_a_deadline_earns_a_list_its_trip():
    """Property 3 again, at the offer. Weight (5+ items) was the only reason a
    list could get a trip proposed; one dated thing is the second, and it
    would never reach five."""
    _reset()
    lst = _list(name="School stuff", is_default=False, errand_tag=None)
    _item(lst['id'], 'tri-fold board', FRI)

    rows = _shop.lists_needing_a_trip(min_items=5, today=MONDAY)
    check(len(rows) == 1 and rows[0]['because'] == 'deadline',
          f"one item, and it still qualifies: {rows}")
    check(rows[0]['deadline_item']['name'] == 'tri-fold board',
          "naming the thing that is driving it")

    delivered = {}
    with mock.patch('services.storage.get_settings',
                    return_value={'propose_shopping_errands': True}):
        _shop.propose_shopping_errands(
            now=datetime.datetime.combine(MONDAY, datetime.time(9, 0)),
            deliver=lambda summary, payload, body: delivered.update(
                summary=summary, body=body, payload=payload))
    check('tri-fold board' in delivered['summary'],
          f"the offer leads with the dated thing, not a count: {delivered['summary']!r}")
    check('1 thing' not in delivered['body'],
          f"quoting '1 thing waiting' would read as trivial: {delivered['body']!r}")
    check('no trip scheduled' in delivered['body'],
          f"and says what is actually wrong: {delivered['body']!r}")


def scenario_the_watcher_names_the_item_not_a_count():
    """Property 5. A surface you have to open is one you do not open, so this
    also lives in the sweep — one finding per late thing."""
    from services import watchers
    _reset()
    lst = _list(name="Groceries")
    _item(lst['id'], 'tri-fold board', FRI)
    _item(lst['id'], 'milk')

    now = datetime.datetime.combine(MONDAY, datetime.time(9, 0))
    found = watchers._supply_deadline_findings(now)
    check(len(found) == 1, f"only the dated one is a finding: {found}")
    key, line = found[0].key, found[0].line
    check(key.startswith('supply_late:'), f"dedup key is per item: {key}")
    check('tri-fold board' in line and 'no trip scheduled' in line,
          f"it names the thing and the reason: {line!r}")

    with mock.patch('services.shopping.deadline_findings',
                    side_effect=RuntimeError('boom')):
        check(watchers._supply_deadline_findings(now) == [],
              "a shopping problem must never cost the sweep its other findings")


def scenario_both_hand_paths_show_the_deadline():
    """Two list surfaces, one verdict — and a family who turned notes off has
    not asked to stop being told the run will miss the science fair."""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    comp = open(os.path.join(tpl, 'components', 'shopping_lists.html'),
                encoding='utf-8').read()
    for needle, what in (('deadlineChip', 'the deadline chip'),
                         ('deadlineWhy', 'the which-way-is-it-late line'),
                         ('it.deadline.late', 'amber only when the run misses')):
        check(needle in comp, f"the shopping list rows carry {what}")
    check(comp.index('const why = this.deadlineWhy(it);')
          < comp.index("if (this.listShow('note')"),
          "the deadline reason is not behind the note toggle")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    for needle, what in (('houseDeadlineBits', 'the deadline chip'),
                         ('no trip scheduled for this list', 'the no-trip reason')):
        check(needle in app, f"the PWA House rows carry {what}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} supply-deadline scenarios passed")
