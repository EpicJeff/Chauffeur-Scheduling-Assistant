"""Supply intake A3 — a duplicate that wants things is not a skip.

Reminder emails outnumber announcement emails, so this branch carries most of
the real traffic. Before A3 a reminder for an event already on the calendar
was stored `status: 'duplicate'` and rendered as a skip — correct when all it
carried was the event, wrong the moment it can carry supplies. "Already on
the calendar, but it wants three things" is a proposal.

The properties that matter, and why:

  1. **Only fresh supplies keep it alive.** A reminder repeats the whole
     flyer, so the second one asks for the same tri-fold board. Supplies
     already open on a list are filtered out, and a duplicate left with
     nothing is a skip exactly as before — otherwise this becomes a weekly
     card for the same three things.
  2. **It lands in the queue, not the skip drawer.** Status stays 'proposed';
     `supplies_only` is what changes the card.
  3. **It has exactly ONE target, enforced server-side.** A client that
     ignored the flag would otherwise create the very duplicate event dedupe
     just avoided.
  4. **'supplies' is never learned as a sender route.** It is not a routing
     choice; prefilling it would point ordinary proposals at a target that
     refuses them.
  5. **The dedupe record survives.** duplicate_of/start/source/rule are still
     written, so the skip is still auditable and the match still shown.

Run from chauffeur/:  python tests/test_supply_duplicates.py
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


def _prop(**over):
    base = {'title': 'Science fair', 'kind': 'event',
            'start': f"{SOON.isoformat()}T09:00:00",
            'end': f"{SOON.isoformat()}T11:00:00", 'all_day': False,
            'location': 'school gym', 'confidence': 0.9,
            'supplies': [{'name': 'tri-fold board', 'qty': '1', 'why': 'flyer'},
                         {'name': 'glue sticks', 'qty': None, 'why': None}]}
    base.update(over)
    return base


def _match(**over):
    m = {'title': 'Science fair', 'start': f"{SOON.isoformat()}T09:00:00",
         'source': 'event', 'rule': 'title', 'id': 'gid_existing'}
    m.update(over)
    return m


def scenario_a_duplicate_with_nothing_to_offer_is_still_a_skip():
    """Property 1, the unchanged half. Nothing about A3 loosens dedupe."""
    _reset()
    prop = _prop(supplies=[])
    status = email_ingest.mark_duplicate(prop, _match())
    check(status == 'duplicate' and prop['status'] == 'duplicate',
          f"no supplies -> the skip behaves exactly as before: {prop['status']}")
    check(prop['duplicate_of'] == 'Science fair' and prop['duplicate_rule'] == 'title',
          f"and the match record is written either way (property 5): {prop}")


def scenario_a_duplicate_carrying_fresh_supplies_reaches_the_queue():
    """Property 2. The event was already known and would have vanished; the
    tri-fold board would have gone with it."""
    _reset()
    prop = _prop()
    status = email_ingest.mark_duplicate(prop, _match())
    check(status == 'supplies_only', f"not a skip: {status}")
    check(prop['status'] == 'proposed' and prop['supplies_only'] is True,
          f"it lands in the queue a parent actually reads: {prop['status']}")
    check(prop['supplies_event_id'] == 'gid_existing',
          f"pointing at the event already on the calendar: {prop.get('supplies_event_id')}")
    check(prop['duplicate_of'] == 'Science fair',
          "and it still records what it matched — the skip stays auditable")


def scenario_supplies_already_on_a_list_do_not_come_back():
    """Property 1, the half that keeps this from becoming a nag. The second
    reminder repeats the flyer; only what nobody has yet survives."""
    from models.schemas import ShoppingList, ShoppingItem
    _reset()
    lst = ShoppingList(name="Groceries", is_default=True).model_dump()
    storage.add_shopping_list(lst)
    storage.add_shopping_item(
        ShoppingItem(list_id=lst['id'], name='Tri-Fold Board').model_dump())

    fresh = email_ingest._supplies_needing_a_home(
        [{'name': 'tri-fold board'}, {'name': 'glue sticks'}])
    check([s['name'] for s in fresh] == ['glue sticks'],
          f"case-insensitively matched against what is already open: {fresh}")

    prop = _prop()
    check(email_ingest.mark_duplicate(prop, _match()) == 'supplies_only',
          "one thing left is still a card")
    check([s['name'] for s in prop['supplies']] == ['glue sticks'],
          f"trimmed to what is actually missing: {prop['supplies']}")

    # And when the family has bought everything, it is a plain skip again.
    storage.add_shopping_item(
        ShoppingItem(list_id=lst['id'], name='glue sticks').model_dump())
    prop2 = _prop()
    check(email_ingest.mark_duplicate(prop2, _match()) == 'duplicate',
          "nothing left to want -> back to a silent skip")

    # A checked-off item is NOT still on the list: it was bought, and next
    # term's fair needs another one.
    for it in storage.get_shopping_items(lst['id']):
        storage.update_shopping_item(it['id'], {'is_checked': True})
    prop3 = _prop()
    check(email_ingest.mark_duplicate(prop3, _match()) == 'supplies_only',
          "bought is not the same as covered forever")


def scenario_a_list_failure_costs_a_re_offer_never_the_item():
    """Not knowing what is on the lists is survivable; an exception is not."""
    with mock.patch('services.storage.get_shopping_lists',
                    side_effect=RuntimeError('db gone')):
        out = email_ingest._supplies_needing_a_home([{'name': 'glue sticks'}])
    check([s['name'] for s in out] == ['glue sticks'],
          f"the supply survives the failure: {out}")


def scenario_the_card_has_exactly_one_target():
    """Property 3, enforced in the endpoint and not only in two UIs."""
    import main
    from fastapi import HTTPException
    _reset()
    prop = _prop()
    email_ingest.mark_duplicate(prop, _match())
    pid = storage.add_proposal(prop)

    try:
        main.approve_proposal(pid, main.ProposalApprove(calendar_id='cal1'),
                              mock.MagicMock())
        check(False, "a supplies-only card must not be approvable onto a calendar")
    except HTTPException as e:
        check(e.status_code == 400 and 'already on' in e.detail,
              f"refused, and says why: {e.detail}")
    check(storage.get_proposal(pid)['status'] == 'proposed',
          "and the card is untouched — no event, no half-approval")

    res = main.approve_proposal(pid, main.ProposalApprove(
        calendar_id='supplies', supplies=['tri-fold board', 'glue sticks']),
        mock.MagicMock())
    check(res['supplies_added'] == 2, f"the one real target works: {res}")
    items = storage.get_shopping_items()
    check(all(i['source_event_id'] == 'gid_existing' for i in items),
          f"tied to the event ALREADY on the calendar: {items}")
    check(all(i['needed_by'] == SOON.isoformat() for i in items),
          f"with the event's day as the deadline: {[i['needed_by'] for i in items]}")
    check(storage.get_proposal(pid)['status'] == 'approved', "and it resolves")

    # The inverse guard: an ordinary proposal cannot use the supplies target.
    _reset()
    pid2 = storage.add_proposal(_prop())
    try:
        main.approve_proposal(pid2, main.ProposalApprove(calendar_id='supplies'),
                              mock.MagicMock())
        check(False, "an ordinary proposal must not resolve as supplies-only")
    except HTTPException as e:
        check(e.status_code == 400, f"refused: {e.detail}")


def scenario_nothing_ticked_is_an_honest_no_op():
    """Unticking everything is a valid answer: the parent has read it and
    decided. It resolves the card without pretending anything was bought."""
    import main
    _reset()
    prop = _prop()
    email_ingest.mark_duplicate(prop, _match())
    pid = storage.add_proposal(prop)
    res = main.approve_proposal(pid, main.ProposalApprove(calendar_id='supplies'),
                                mock.MagicMock())
    check(res['supplies_added'] == 0 and 'Nothing ticked' in res['message'],
          f"says so plainly: {res}")
    check(storage.get_shopping_items() == [], "and buys nothing")


def scenario_supplies_is_never_learned_as_a_route():
    """Property 4. 'errand' is excluded for the same reason and is the
    precedent — a target that needs per-proposal context is not a preference."""
    storage.set_app_state('intake_learned_routes',
                          {'office@school.org': {'target': 'supplies', 'count': 3}})
    check(email_ingest.learned_route('office@school.org', 'event') is None,
          "a supplies approval never prefills the next proposal's target")
    storage.set_app_state('intake_learned_routes',
                          {'office@school.org': {'target': 'cal1', 'count': 3}})
    check(email_ingest.learned_route('office@school.org', 'event') == 'cal1',
          "an ordinary learned route still works")
    storage.set_app_state('intake_learned_routes', {})


def scenario_the_run_loop_counts_it_honestly():
    """A supplies-only item is proposed, not skipped, and the ingest log says
    which — the accountability trail is the whole reason skips are recorded."""
    _reset()
    logged = {}
    items = [{'kind': 'event', 'title': 'Science fair', 'date': SOON.isoformat(),
              'start_time': '09:00', 'confidence': 0.9,
              'supplies': [{'name': 'tri-fold board'}]}]
    sched = {'events': [{'id': 'gid_existing', 'title': 'Science fair',
                         'start': f"{SOON.isoformat()}T09:00:00",
                         'end': f"{SOON.isoformat()}T11:00:00"}]}
    with mock.patch('services.model_pools.call_pool_json',
                    return_value={'items': items}), \
         mock.patch('services.storage.get_settings',
                    return_value={'llm_gemini_api_key': 'k'}), \
         mock.patch('services.storage.get_cached_schedule', return_value=sched), \
         mock.patch('services.storage.add_ingest_log',
                    side_effect=lambda e, **kw: logged.update(e)):
        summary = email_ingest.run_photo_ingest('b64', 'image/jpeg', 'flyer')
    check(summary['proposed'] == 1 and summary['duplicates'] == 0,
          f"counted as proposed, not as a skip: {summary}")
    check(summary['supplies_only'] == 1, f"and named for what it is: {summary}")
    check('needing supplies' in logged.get('outcome', ''),
          f"the log row says what happened: {logged.get('outcome')!r}")
    rows = storage.get_proposals()
    check(len(rows) == 1 and rows[0]['supplies_only'] is True
          and rows[0]['status'] == 'proposed',
          f"one card, in the queue: {rows}")


def scenario_both_hand_paths_render_the_supplies_only_card():
    """A card that offers a calendar it must refuse is a trap, so both
    surfaces set the target instead of asking for it."""
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    intake = open(os.path.join(tpl, 'intake.html'), encoding='utf-8').read()
    for needle, what in (('p.supplies_only', 'the flag'),
                         ('Already on the calendar', 'the explanation'),
                         ("'supplies'", 'the single target')):
        check(needle in intake, f"intake.html carries {what}")
    check("t !== 'supplies'" in intake,
          "and 'supplies' is not treated as a calendar target (no attendee chips)")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    for needle, what in (('p.supplies_only', 'the flag'),
                         ('Already on the calendar', 'the explanation'),
                         ("t !== 'supplies'", 'the non-calendar target')):
        check(needle in app, f"app.html carries {what}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} supply-duplicate scenarios passed")
