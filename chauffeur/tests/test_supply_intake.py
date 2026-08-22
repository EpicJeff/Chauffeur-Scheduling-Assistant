"""Supply intake A1 — the things a dated item needs, onto a real list.

A flyer says "science fair Friday, bring a tri-fold board". Until now the
board survived only as prose in the proposal's notes, which nobody re-reads
in a shop. It is now a first-class array on the extraction, ticked on the
approval card, and written as real `ShoppingItem`s.

The properties that matter, and why:

  1. **A supply is an ATTRIBUTE, not a target.** It rides whichever branch of
     approval the parent picked — calendar event, drive errand, household
     task, kid task — and `source_event_id` records whatever id that branch
     made. Modelling it as its own proposal kind would invent a
     which-event-is-this matching problem that a field does not have.
  2. **The parent's ticks are authoritative.** `supplies` on the request is
     the list of names still ticked; unticking is how a thing does not get
     bought. An absent array writes NOTHING — an older client must not
     silently create rows.
  3. **A garbled supply must never cost the family the event.** Malformed
     entries drop individually; the date is the load-bearing half.
  4. **`needed_by` is the point** (design §A2). Every write carries the day
     the thing stops being useful, which is what later lets the app notice
     that the fair is Friday and the shop run is Saturday.

Run from chauffeur/:  python tests/test_supply_intake.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import email_ingest

TODAY = datetime.date.today()
SOON = TODAY + datetime.timedelta(days=4)


def _reset():
    with storage.db_lock:
        storage.event_proposals_table.truncate()
        storage.shopping_items_table.truncate()
        storage.shopping_lists_table.truncate()
        storage.household_tasks_table.truncate()


def _proposal(**over):
    base = {'title': "Science fair", 'kind': 'event',
            'start': f"{SOON.isoformat()}T09:00:00",
            'end': f"{SOON.isoformat()}T11:00:00", 'all_day': False,
            'location': 'school gym', 'notes': 'bring your board',
            'source_from': 'office@school.org', 'source_subject': 'Science fair',
            'supplies': [{'name': 'tri-fold board', 'qty': '1', 'why': 'flyer says bring one'},
                         {'name': 'glue sticks', 'qty': None, 'why': None}]}
    base.update(over)
    return storage.add_proposal(base)


def scenario_supplies_survive_normalization():
    """The array rides `normalize_item` with the rest of the extraction —
    same call, no second LLM round-trip (that is what makes this affordable)."""
    item = {'kind': 'event', 'title': 'Science fair',
            'date': SOON.isoformat(), 'start_time': '09:00', 'confidence': 0.9,
            'supplies': [{'name': 'Tri-fold board', 'qty': '1', 'why': 'flyer'},
                         {'name': 'glue sticks'}]}
    prop = email_ingest.normalize_item(item)
    check(prop is not None, "the item itself normalizes")
    names = [s['name'] for s in prop['supplies']]
    check(names == ['Tri-fold board', 'glue sticks'], f"both carried: {names}")
    check(prop['supplies'][0]['qty'] == '1' and prop['supplies'][1]['qty'] is None,
          f"qty is free text and never invented: {prop['supplies']}")

    bare = email_ingest.normalize_item(
        {'kind': 'event', 'title': 'Practice', 'date': SOON.isoformat(),
         'start_time': '17:00', 'confidence': 0.9})
    check(bare['supplies'] == [],
          f"no supplies key -> an empty list, the expected common answer: {bare['supplies']}")


def scenario_a_garbled_supply_never_costs_the_event():
    """Property 3. A malformed entry drops on its own; the date is the
    load-bearing half of a proposal and must survive a bad supply line."""
    item = {'kind': 'event', 'title': 'Food drive', 'date': SOON.isoformat(),
            'start_time': None, 'confidence': 0.8,
            'supplies': ['a bare string', {'name': ''}, None,
                         {'name': 'shoebox'}, {'name': 'SHOEBOX'}]}
    prop = email_ingest.normalize_item(item)
    check(prop is not None, "the item still normalizes around the junk")
    check([s['name'] for s in prop['supplies']] == ['shoebox'],
          f"junk and the case-duplicate dropped, the real one kept: {prop['supplies']}")

    many = email_ingest.normalize_item(
        {'kind': 'task', 'title': 'Party', 'date': SOON.isoformat(),
         'confidence': 0.9,
         'supplies': [{'name': f'thing {i}'} for i in range(20)]})
    check(len(many['supplies']) == email_ingest.MAX_SUPPLIES,
          f"capped at {email_ingest.MAX_SUPPLIES}: {len(many['supplies'])}")


def scenario_the_prompt_refuses_money_and_owned_clothing():
    """Precision is the product (design principle 1). The rules live in the
    prompt, so this asserts the prompt actually carries them — a silent edit
    that drops them is how the grocery list starts collecting "$5"."""
    src = email_ingest.EXTRACTION_SYSTEM
    for needle, what in (('"supplies"', 'the supplies field'),
                         ('Money is not a supply', 'the money rule'),
                         ('already owns', 'the owned-clothing rule'),
                         ('NEVER invent a quantity', 'the no-invented-quantity rule'),
                         ('expected answer for most items', 'the empty-is-correct rule')):
        check(needle in src, f"the extraction prompt states {what}")


def scenario_supplies_ride_every_approval_target():
    """Property 1. Four branches, four id kinds, one write path."""
    import main
    _reset()

    # (a) calendar event — the common case; the event's own day is the deadline.
    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_fair'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', supplies=['tri-fold board', 'glue sticks']),
            mock.MagicMock())
    check(res['supplies_added'] == 2, f"both written: {res}")
    check('🛒' in res['message'], f"and the message says so: {res['message']!r}")
    items = storage.get_shopping_items()
    check(len(items) == 2, f"two rows on a real list: {len(items)}")
    check(all(i['source_event_id'] == 'gid_fair' for i in items),
          f"provenance is the google id the branch just made: {items}")
    check(all(i['needed_by'] == SOON.isoformat() for i in items),
          f"needed_by is the event's day (design §A2): {[i['needed_by'] for i in items]}")
    check(all(i['added_via'] == 'intake' for i in items),
          f"attributed to intake: {[i['added_via'] for i in items]}")
    check('Science fair' in (items[0]['note'] or ''),
          f"the note answers 'why is this here' in the aisle: {items[0]['note']!r}")

    # (b) drive errand
    _reset()
    pid = _proposal()
    with mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x), \
         mock.patch('main.create_errand'):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='errand', location='Target', duration_mins=30,
            supplies=['glue sticks']), mock.MagicMock())
    items = storage.get_shopping_items()
    check(res['supplies_added'] == 1 and len(items) == 1,
          f"the errand branch writes them too: {res}")
    check(items[0]['source_event_id'] == res['errand_id'],
          f"pointing at the errand: {items[0]['source_event_id']} vs {res['errand_id']}")

    # (c) household task
    _reset()
    pid = _proposal(kind='task', all_day=True, start=SOON.isoformat(),
                    end=SOON.isoformat(), location=None)
    res = main.approve_proposal(pid, main.ProposalApprove(
        calendar_id='household_task', supplies=['tri-fold board']), mock.MagicMock())
    items = storage.get_shopping_items()
    check(res['supplies_added'] == 1 and items[0]['source_event_id'] == res['task_id'],
          f"the household-task branch writes them, pointing at the task: {res}")

    # (d) kid school list
    _reset()
    member = {'id': 'kid1', 'name': 'Ellie', 'role': 'child'}
    with mock.patch('services.storage.get_member', return_value=member), \
         mock.patch('services.storage.add_kid_task'):
        pid = _proposal(kind='task', all_day=True, start=SOON.isoformat(),
                        end=SOON.isoformat(), location=None)
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='tasks:kid1', supplies=['glue sticks']), mock.MagicMock())
    items = storage.get_shopping_items()
    check(res['supplies_added'] == 1 and len(items) == 1,
          f"the kid-task branch writes them too: {res}")


def scenario_the_ticks_are_authoritative():
    """Property 2. Unticking is how a thing does not get bought, and an
    absent array writes nothing at all."""
    import main
    _reset()

    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_a'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', supplies=['glue sticks']), mock.MagicMock())
    items = storage.get_shopping_items()
    check(res['supplies_added'] == 1 and [i['name'] for i in items] == ['glue sticks'],
          f"only the ticked one was bought: {[i['name'] for i in items]}")

    _reset()
    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_b'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        res = main.approve_proposal(pid, main.ProposalApprove(calendar_id='cal1'),
                                    mock.MagicMock())
    check(res['supplies_added'] == 0 and storage.get_shopping_items() == [],
          "an approval that never mentions supplies writes NOTHING")

    # A name that is not on the proposal cannot be smuggled in by the client.
    _reset()
    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_c'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', supplies=['a pony']), mock.MagicMock())
    check(res['supplies_added'] == 0 and storage.get_shopping_items() == [],
          "the proposal is the source of truth for WHAT the names mean")


def scenario_the_parent_routes_the_list_never_the_model():
    """Design principle 4. The model does not know this family's lists, so a
    named list is honoured and an unknown one falls back to the default
    rather than 404ing an approval that already wrote a calendar event."""
    import main
    from models.schemas import ShoppingList
    _reset()
    school = ShoppingList(name="School stuff", store="Target").model_dump()
    storage.add_shopping_list(school)

    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_d'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', supplies=['tri-fold board'],
            supplies_list_id=school['id']), mock.MagicMock())
    items = storage.get_shopping_items()
    check(len(items) == 1 and items[0]['list_id'] == school['id'],
          f"the parent's chosen list wins: {items}")

    _reset()
    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_e'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', supplies=['tri-fold board'],
            supplies_list_id='no-such-list'), mock.MagicMock())
    items = storage.get_shopping_items()
    default = storage.ensure_default_shopping_list()
    check(res['status'] == 'approved' and len(items) == 1
          and items[0]['list_id'] == default['id'],
          f"a stale list id falls back rather than losing the approval: {items}")


def scenario_a_failed_supply_write_never_undoes_the_event():
    """The event is already in Google Calendar by the time supplies are
    written. A storage failure here must cost the supplies, not the event."""
    import main
    _reset()
    pid = _proposal()
    with mock.patch('services.calendar.insert_event', return_value='gid_f'), \
         mock.patch('services.calendar.get_calendar_timezone', return_value=None), \
         mock.patch('services.maps.resolve_routable_location', side_effect=lambda x: x), \
         mock.patch('services.storage.add_shopping_item',
                    side_effect=RuntimeError('disk on fire')):
        res = main.approve_proposal(pid, main.ProposalApprove(
            calendar_id='cal1', supplies=['tri-fold board']), mock.MagicMock())
    check(res['status'] == 'approved' and res['event_id'] == 'gid_f',
          f"the event still landed: {res}")
    check(res['supplies_added'] == 0, f"and the failure is reported as zero: {res}")
    check(storage.get_proposal(pid)['status'] == 'approved', "proposal resolved")


def scenario_both_hand_paths_carry_the_supplies_section():
    """Every capability needs a hand path, and intake has TWO surfaces — the
    dashboard page and the PWA card. A supply section on only one of them is
    a feature that vanishes depending on which screen the parent picked up."""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    intake = open(os.path.join(tpl, 'intake.html'), encoding='utf-8').read()
    for needle, what in (('Needs buying', 'the supplies section'),
                         ('toggleSupply', 'per-supply ticking'),
                         ('body.supplies', 'the approve body carrying the ticks'),
                         ('supplies_list_id', 'the list picker'),
                         ('api/shopping/lists', 'the list fetch')):
        check(needle in intake, f"intake.html carries {what}")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    for needle, what in (('Needs buying', 'the supplies section'),
                         ('data-supply=', 'per-supply ticking'),
                         ('body.supplies', 'the approve body carrying the ticks'),
                         ('f-supplylist', 'the list picker'),
                         ('proposalLists', 'the list fetch')):
        check(needle in app, f"app.html carries {what}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} supply-intake scenarios passed")
