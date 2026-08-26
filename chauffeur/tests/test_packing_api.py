"""The packing endpoints, exercised the way the wall's card actually calls
them: GET /api/packing/day builds the day's outings with their kit items and
claim counts, POST /api/packing/claim moves one item's count up or down.

FastAPI's TestClient needs httpx, which is not installed in this environment
(`starlette.testclient` raises `RuntimeError` on import here), so these
scenarios call the endpoint functions directly -- the same pattern already in
use for the pets battle endpoints (`tests/test_pet_battles_api.py`): a plain
Python call with a dict standing in for the request body, and FastAPI's own
`HTTPException` caught by hand where a scenario expects a refusal.

Run from chauffeur/:  python tests/test_packing_api.py
"""
import datetime
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_packing_api_'))

from services import storage  # noqa: E402

DAY = '2026-09-08'


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()


def _ev(eid, hh, mm=0, dur=60, title=None, cal_ids=None):
    start = datetime.datetime(2026, 9, 8, hh, mm)
    return {'id': eid, 'title': title or eid,
            'start': start.isoformat(),
            'end': (start + datetime.timedelta(minutes=dur)).isoformat(),
            'calendar_ids': cal_ids or []}


def _seed_incident():
    """Soccer at 16:00, band at 17:30, one driver, no room to get home in
    between -- the same shape test_outings.py's incident fixture uses, now
    carrying two kits so the day endpoint has something to group."""
    reset_db()
    storage.add_driver({'id': 'd1', 'name': 'Dad', 'color_code': '#2563eb',
                        'group': 'primary', 'priority_index': 1})
    storage.add_passenger({'id': 'ellie', 'name': 'Ellie', 'calendar_ids': []})
    k1 = storage.add_prep_kit({'id': 'k1', 'name': 'Soccer bag',
                               'items': ['Water bottle'], 'enabled': True,
                               'per_person': True, 'keywords': ['soccer'],
                               'passenger_ids': ['ellie']})
    k2 = storage.add_prep_kit({'id': 'k2', 'name': 'Band bag',
                               'items': ['Sheet music'], 'enabled': True,
                               'per_person': True, 'keywords': ['band'],
                               'passenger_ids': ['ellie']})
    sched = {
        'events': [_ev('soccer', 16, cal_ids=['ellie']),
                  _ev('band', 17, 30, cal_ids=['ellie'])],
        'assignments': {'soccer': 'd1', 'band': 'd1'},
        'route_edges': {'d1': {'soccer': {'to_event': 'band', 'travel_mins': 20}}},
        'initial_edges': {}, 'final_edges': {}, 'cars': [], 'car_assignments': {},
    }
    storage.set_cached_schedule(sched)
    return k1, k2


def scenario_the_day_endpoint_groups_by_outing():
    """Two events on one trip are ONE packing job. That grouping IS the message
    — at four activities a day, a sentence saying 'you are not stopping home'
    would fire constantly and stop being read."""
    _seed_incident()
    import main
    out = main.packing_day(date=DAY)
    check(out['date'] == DAY, f"wrong day in the response: {out['date']}")
    outing_blocks = [b for b in out['blocks'] if b['kind'] == 'outing']
    check(len(outing_blocks) == 1,
          f"two events with no way home should be one outing block: {out['blocks']}")
    outing = outing_blocks[0]
    check(outing['event_ids'] == ['soccer', 'band'],
          f"the outing block does not carry both events: {outing['event_ids']}")
    check(outing['driver_id'] == 'd1' and outing['driver'] == 'Dad',
          f"the outing block lost its driver: {outing}")
    check(outing['color'] == '#2563eb',
          f"the outing block should carry the driver's real color_code: {outing['color']}")
    labels = sorted(i['label'] for g in outing['groups'] for i in g['items'])
    check(labels == ['Sheet music', 'Water bottle'],
          f"both kits' items should be on the outing block: {labels}")
    check(outing['needed'] == 2, f"needed should count one item from each kit: {outing['needed']}")
    check(outing['packed'] == 0, f"nothing has been packed yet: {outing['packed']}")


def scenario_a_claim_moves_the_count_and_comes_back():
    _seed_incident()
    import main
    outing_key = 'd1:soccer'
    item_key = 'k1:water bottle'
    res = main.packing_claim(payload={'outing_key': outing_key, 'item_key': item_key,
                                      'delta': 1, 'date': DAY})
    check(res['ok'] is True and res['packed'] == 1,
          f"a +1 claim should read back as packed=1: {res}")
    fresh = main.packing_day(date=DAY)
    block = next(b for b in fresh['blocks'] if b['kind'] == 'outing')
    item = next(i for g in block['groups'] for i in g['items']
               if i['key'] == item_key)
    check(item['packed'] == 1, f"a fresh GET should also see the claim: {item}")

    res2 = main.packing_claim(payload={'outing_key': outing_key, 'item_key': item_key,
                                       'delta': -1, 'date': DAY})
    check(res2['ok'] is True and res2['packed'] == 0,
          f"a -1 claim should bring the count back to 0: {res2}")
    fresh2 = main.packing_day(date=DAY)
    block2 = next(b for b in fresh2['blocks'] if b['kind'] == 'outing')
    item2 = next(i for g in block2['groups'] for i in g['items']
                if i['key'] == item_key)
    check(item2['packed'] == 0, f"a fresh GET should see the claim come back: {item2}")


def scenario_a_claim_needs_a_real_outing_and_item():
    """A garbage outing_key is refused, not filed -- a stale card cannot write
    a claim against a trip that no longer exists and never be seen again."""
    _seed_incident()
    import main
    from fastapi import HTTPException
    try:
        main.packing_claim(payload={'outing_key': 'not-a-real-outing',
                                    'item_key': 'k1:water bottle',
                                    'delta': 1, 'date': DAY})
        raise AssertionError("a claim against a fake outing was filed instead of refused")
    except HTTPException as e:
        check(e.status_code == 404, f"wrong refusal: {e.status_code}")
    check(storage.get_packing_claims(DAY) == [],
          "the refused claim was written anyway")


def scenario_a_garbage_item_key_on_a_real_outing_is_refused():
    """Fix round finding #2a: the endpoint validated `outing_key` against the
    day's real outings but trusted `item_key` outright — a garbage item_key
    against a REAL outing minted a fresh XP row (the once-guard keys on
    `ref_id=item_key`, so every distinct garbage string is a new grant) and
    filed a claim row nothing ever prunes. It must be refused, the same as a
    garbage outing_key already is."""
    _seed_incident()
    import main
    from fastapi import HTTPException
    try:
        main.packing_claim(payload={'outing_key': 'd1:soccer',
                                    'item_key': 'k1:not-a-real-item',
                                    'delta': 1, 'date': DAY})
        raise AssertionError("a claim against a garbage item_key was filed instead of refused")
    except HTTPException as e:
        check(e.status_code in (400, 404), f"wrong refusal: {e.status_code}")
    check(storage.get_packing_claims(DAY) == [],
          "the refused claim was written anyway")


def scenario_a_claimed_member_id_from_the_payload_never_reaches_the_ledger():
    """Fix round finding #2b: the endpoint trusted a client-asserted
    `member_id` — anyone on the DEVICE lane could mint XP to any member. No
    shipped surface produces a named claim yet (that is P3, which will derive
    identity server-side), so P1+P2 must ignore whatever member_id the
    payload sends and file every claim anonymously."""
    _seed_incident()
    import main
    from services import storage as _storage
    res = main.packing_claim(payload={'outing_key': 'd1:soccer',
                                      'item_key': 'k1:water bottle',
                                      'member_id': 'ellie', 'delta': 1, 'date': DAY})
    check(res['ok'] is True and res['packed'] == 1, f"the claim itself should still land: {res}")
    rows = _storage.get_packing_claims(DAY)
    check(len(rows) == 1 and rows[0].get('member_id') is None,
          f"a client-asserted member_id reached the ledger: {rows}")
    check(res.get('xp', 0) == 0,
          f"an anonymous claim should never mint XP through this path: {res}")


def scenario_delta_zero_is_refused_not_treated_as_plus_one():
    """Fix round finding #2c: `int(payload.get('delta') or 1)` silently
    turned an explicit `delta: 0` into +1. `delta` is parsed explicitly now,
    and 0 is invalid — not a quiet +1."""
    _seed_incident()
    import main
    from fastapi import HTTPException
    try:
        main.packing_claim(payload={'outing_key': 'd1:soccer',
                                    'item_key': 'k1:water bottle',
                                    'delta': 0, 'date': DAY})
        raise AssertionError("delta: 0 was treated as a claim instead of refused")
    except HTTPException as e:
        check(e.status_code == 400, f"wrong refusal for delta 0: {e.status_code}")
    check(storage.get_packing_claims(DAY) == [],
          "a delta: 0 request still filed a claim")


def _seed_home_event():
    """An at-home event needing a kit -- no driver, no outing, still a
    happening with something to pack."""
    reset_db()
    storage.add_passenger({'id': 'ellie', 'name': 'Ellie', 'calendar_ids': []})
    k1 = storage.add_prep_kit({'id': 'k1', 'name': 'Piano bag',
                               'items': ['Sheet music'], 'enabled': True,
                               'per_person': True, 'keywords': ['piano'],
                               'passenger_ids': ['ellie']})
    sched = {
        'events': [_ev('piano', 14, title='Piano recital', cal_ids=['ellie'])],
        'assignments': {}, 'route_edges': {}, 'initial_edges': {}, 'final_edges': {},
        'cars': [], 'car_assignments': {},
    }
    storage.set_cached_schedule(sched)
    return k1


def scenario_a_home_block_takes_claims_too():
    """A home block claims items the same way an outing does — the envelope
    moved from `outings` to `blocks`, the claim path did not."""
    _seed_home_event()
    import main
    out = main.packing_day(date=DAY)
    home_blocks = [b for b in out['blocks'] if b['kind'] == 'event']
    check(len(home_blocks) == 1, f"expected one home block: {out['blocks']}")
    block = home_blocks[0]
    check(block['key'] == 'home:piano', f"home blocks key as home:<event_id>: {block['key']}")
    labels = [i['label'] for g in block['groups'] for i in g['items']]
    check(labels == ['Sheet music'], f"the home block should carry its kit's items: {block}")

    res = main.packing_claim(payload={'outing_key': 'home:piano', 'item_key': 'k1:sheet music',
                                      'delta': 1, 'date': DAY})
    check(res['ok'] is True and res['packed'] == 1,
          f"a claim against a home block should move the count: {res}")
    fresh = main.packing_day(date=DAY)
    fresh_block = next(b for b in fresh['blocks'] if b['kind'] == 'event')
    item = next(i for g in fresh_block['groups'] for i in g['items'])
    check(item['packed'] == 1, f"a fresh GET should also see the claim: {item}")


def _seed_bare_drive():
    """A driven trip with no kit at all."""
    reset_db()
    storage.add_driver({'id': 'd1', 'name': 'Dad', 'color_code': '#2563eb',
                        'group': 'primary', 'priority_index': 1})
    sched = {
        'events': [_ev('errand', 10, title='Hardware store')],
        'assignments': {'errand': 'd1'},
        'route_edges': {}, 'initial_edges': {}, 'final_edges': {},
        'cars': [], 'car_assignments': {},
    }
    storage.set_cached_schedule(sched)


def scenario_a_drive_with_nothing_to_pack_still_draws():
    """Rule flip 1: a drive is a happening whether or not it has cargo. The
    old endpoint dropped an outing with nothing to pack; the day endpoint
    must not."""
    _seed_bare_drive()
    import main
    out = main.packing_day(date=DAY)
    outing_blocks = [b for b in out['blocks'] if b['kind'] == 'outing']
    check(len(outing_blocks) == 1, f"a cargo-less outing should still draw: {out['blocks']}")
    block = outing_blocks[0]
    check(block['groups'] == [], f"no kit means no groups: {block['groups']}")
    check(block['needed'] == 0, f"no kit means nothing needed: {block['needed']}")


def _seed_single_item():
    """One kit, one passenger -- needed is exactly 1."""
    reset_db()
    storage.add_driver({'id': 'd1', 'name': 'Dad', 'color_code': '#2563eb',
                        'group': 'primary', 'priority_index': 1})
    storage.add_passenger({'id': 'ellie', 'name': 'Ellie', 'calendar_ids': []})
    k1 = storage.add_prep_kit({'id': 'k1', 'name': 'Soccer bag',
                               'items': ['Water bottle'], 'enabled': True,
                               'per_person': True, 'keywords': ['soccer'],
                               'passenger_ids': ['ellie']})
    sched = {
        'events': [_ev('soccer', 16, cal_ids=['ellie'])],
        'assignments': {'soccer': 'd1'},
        'route_edges': {}, 'initial_edges': {}, 'final_edges': {},
        'cars': [], 'car_assignments': {},
    }
    storage.set_cached_schedule(sched)
    return k1


def scenario_the_server_caps_a_claim_at_needed():
    """Two walls racing past the client's disabled button must not file a
    surplus claim: an add against a full item is a no-op returning the
    current count, not a fresh row."""
    _seed_single_item()
    import main
    outing_key, item_key = 'd1:soccer', 'k1:water bottle'
    res1 = main.packing_claim(payload={'outing_key': outing_key, 'item_key': item_key,
                                       'delta': 1, 'date': DAY})
    check(res1['packed'] == 1, f"the first claim should land: {res1}")
    res2 = main.packing_claim(payload={'outing_key': outing_key, 'item_key': item_key,
                                       'delta': 1, 'date': DAY})
    check(res2['packed'] == 1,
          f"a claim against a full item should be a no-op, not push past needed: {res2}")
    rows = [r for r in storage.get_packing_claims(DAY)
            if r.get('outing_key') == outing_key and r.get('item_key') == item_key]
    check(len(rows) == 1, f"the capped add should not have filed a second row: {rows}")


def _seed_canceled_home_event():
    reset_db()
    storage.add_passenger({'id': 'ellie', 'name': 'Ellie', 'calendar_ids': []})
    storage.add_prep_kit({'id': 'k1', 'name': 'Piano bag',
                          'items': ['Sheet music'], 'enabled': True,
                          'per_person': True, 'keywords': ['piano'],
                          'passenger_ids': ['ellie']})
    ev = _ev('piano', 14, title='Piano recital', cal_ids=['ellie'])
    ev['canceled'] = True
    sched = {
        'events': [ev],
        'assignments': {}, 'route_edges': {}, 'initial_edges': {}, 'final_edges': {},
        'cars': [], 'car_assignments': {},
    }
    storage.set_cached_schedule(sched)


def scenario_a_canceled_block_carries_no_items():
    """Canceled is drawn, struck, but claims nothing -- filing gear against a
    trip that fell through would nag a decision already made."""
    _seed_canceled_home_event()
    import main
    out = main.packing_day(date=DAY)
    check(len(out['blocks']) == 1, f"expected one block: {out['blocks']}")
    block = out['blocks'][0]
    check(block['canceled'] is True, f"a canceled event should draw struck: {block}")
    check(block['groups'] == [], f"a canceled block should carry no items: {block['groups']}")


def scenario_the_card_can_ask_for_several_days():
    """The agenda this card replaces shows a week, and prep for tomorrow
    morning has to be visible tonight -- one day cannot hold that."""
    _seed_incident()
    import main
    res = main.packing_day(date=DAY, days=3)
    check(len(res['days']) == 3, f"asked for three days, got {len(res.get('days', []))}")
    dates = [d['date'] for d in res['days']]
    check(dates == sorted(dates) and len(set(dates)) == 3,
          f"days should run forward without repeating: {dates}")
    check(res['blocks'] == res['days'][0]['blocks'],
          "day one must stay at the top level so an older card keeps working")
    check(res['days'][0]['label'] and res['days'][1]['label'],
          f"every day should carry a label: {[d.get('label') for d in res['days']]}")


def scenario_one_day_is_still_the_default():
    _seed_incident()
    import main
    res = main.packing_day(date=DAY)
    check(len(res['days']) == 1, f"default should be a single day: {res.get('days')}")
    check('blocks' in res and 'all_day' in res,
          "the legacy top-level shape must survive")


def scenario_prep_lands_in_the_day_before_the_outing_it_serves():
    """F1 drew the list at the moment it was too late. A prep block is a
    position in the list, not an appointment -- and claiming against the
    outing moves the prep block's own count, because they are two views of
    one truth."""
    _seed_incident()
    import main
    res = main.packing_day(date=DAY, days=2)
    preps = [b for d in res['days'] for b in d['blocks'] if b['kind'] == 'prep']
    check(preps, f"no prep block was placed at all: "
                 f"{[b['kind'] for d in res['days'] for b in d['blocks']]}")
    p = preps[0]
    check(p['tiles'] and all(t['for_key'] and t['title'] for t in p['tiles']),
          f"every tile must name the outing it serves: {p}")
    check(p['tiles'] and p['needed'] > 0,
          f"a prep block should carry tiles with items: {p}")
    check(all(t['groups'] for t in p['tiles']),
          f"every tile should carry its own event's list: {p['tiles']}")
    for_key = p['tiles'][0]['for_key']
    src = [b for d in res['days'] for b in d['blocks']
           if b['kind'] != 'prep' and b['key'] == for_key]
    check(src and src[0]['needed'] == p['needed'],
          "the prep block and its outing must agree on what is needed")
    check(p['start'] <= p['tiles'][0]['depart'],
          f"prep must sit before the thing it is for: {p['start']}")


def scenario_a_tick_on_the_outing_shows_on_its_prep_block():
    """One truth, two views: the claim is stored against the outing and the
    item, never against the place a finger touched it."""
    _seed_incident()
    import main
    res = main.packing_day(date=DAY, days=2)
    p = [b for d in res['days'] for b in d['blocks'] if b['kind'] == 'prep'][0]
    item = p['tiles'][0]['groups'][0]['items'][0]
    main.packing_claim(payload={'outing_key': p['tiles'][0]['for_key'],
                                'item_key': item['key'], 'delta': 1,
                                'date': DAY})
    fresh = main.packing_day(date=DAY, days=2)
    p2 = [b for d in fresh['days'] for b in d['blocks']
          if b['key'] == p['key']][0]
    check(p2['packed'] == 1,
          f"the prep block did not see the outing's claim: {p2['packed']}")


def scenario_a_prep_key_is_not_itself_claimable():
    """The prep block is a lens. Letting it hold claims of its own would make
    two counts for one bag, and they would drift."""
    _seed_incident()
    import main
    from fastapi import HTTPException
    res = main.packing_day(date=DAY, days=2)
    p = [b for d in res['days'] for b in d['blocks'] if b['kind'] == 'prep'][0]
    item = p['tiles'][0]['groups'][0]['items'][0]
    try:
        main.packing_claim(payload={'outing_key': p['key'],
                                    'item_key': item['key'], 'delta': 1,
                                    'date': DAY})
    except HTTPException as e:
        check(e.status_code == 404, f"expected a 404, got {e.status_code}")
        return
    raise AssertionError("a claim filed against a prep key was accepted")


def scenario_tomorrow_mornings_trip_is_packed_tonight():
    """The bug the wall caught: a Saturday full of morning trips showed no
    prep at all. Their prep belongs to FRIDAY EVENING, and the endpoint was
    working out "does this have anything to pack?" from today's blocks only —
    so every next-morning trip looked empty and never got a block placed."""
    import datetime
    import main
    k1, _k2 = _seed_incident()
    # Move the incident's events to tomorrow MORNING, which is the case that
    # was silently dropped.
    sched = storage.get_cached_schedule()
    tomorrow = (datetime.date.fromisoformat(DAY) + datetime.timedelta(days=1))
    for ev in sched['events']:
        ev['start'] = f"{tomorrow.isoformat()}T07:30:00"
        ev['end'] = f"{tomorrow.isoformat()}T08:30:00"
    storage.set_cached_schedule(sched)

    res = main.packing_day(date=DAY, days=1)
    preps = [b for b in res['days'][0]['blocks'] if b['kind'] == 'prep']
    check(preps, "tomorrow morning's trip got no prep block tonight — the "
                 "whole point of the placement rule")
    check(preps[0]['tiles'] and preps[0]['needed'] > 0,
          f"the prep block came through with nothing to pack: {preps[0]}")
    anchor = preps[0]['start'][:10]
    check(anchor == DAY,
          f"the prep block should sit on tonight, not {anchor}")


def scenario_a_claim_from_a_prep_block_is_filed_against_its_outing():
    """A tap on a chip inside a prep block came back 404 and told the
    household its packing could not be saved. The prep block is a VIEW; the
    claim belongs to the outing it serves."""
    import main
    _seed_incident()
    res = main.packing_day(date=DAY, days=2)
    prep = [b for d in res['days'] for b in d['blocks'] if b['kind'] == 'prep'][0]
    tile = prep['tiles'][0]
    item = tile['groups'][0]['items'][0]
    out = main.packing_claim(payload={'outing_key': tile['for_key'],
                                      'item_key': item['key'], 'delta': 1,
                                      'date': tile['depart'][:10]})
    check(out['ok'] and out['packed'] == 1,
          f"a claim filed the way the card now files it should stick: {out}")


def scenario_a_group_says_which_events_wanted_it():
    """A surface that lists the work event by event needs to know whose work
    it is — the counts stay outing-wide, the attribution is new."""
    import main
    _seed_incident()
    res = main.packing_day(date=DAY)
    outing = [b for b in res['blocks'] if b['kind'] == 'outing'][0]
    for g in outing['groups']:
        check(g.get('event_ids'),
              f"a kit group should name the events that pulled it in: {g}")
        check(all(e in outing['event_ids'] for e in g['event_ids']),
              f"a group named an event that is not on its outing: {g}")


def scenario_a_tile_carries_only_its_own_events_list():
    """You work one event at a time, so a tile shows that event's list — not
    the whole trip's."""
    import main
    _seed_incident()
    res = main.packing_day(date=DAY, days=2)
    prep = [b for d in res['days'] for b in d['blocks'] if b['kind'] == 'prep'][0]
    check(len(prep['tiles']) >= 1, f"expected tiles: {prep}")
    total = sum(t['needed'] for t in prep['tiles'])
    check(prep['needed'] == total,
          f"the block's count must be its tiles' counts: {prep['needed']} vs {total}")
    for t in prep['tiles']:
        check(t['event_id'] and t['title'],
              f"a tile must name its event: {t}")
        check('done' in t, f"a tile must say whether it is finished: {t}")


def scenario_packing_a_tile_finishes_it():
    """Once everything on a tile is claimed it reads as done, and so does the
    block that holds it."""
    import main
    _seed_incident()
    res = main.packing_day(date=DAY, days=2)
    prep = [b for d in res['days'] for b in d['blocks'] if b['kind'] == 'prep'][0]
    tile = prep['tiles'][0]
    for g in tile['groups']:
        for item in g['items']:
            for _ in range(item['needed']):
                main.packing_claim(payload={'outing_key': tile['for_key'],
                                            'item_key': item['key'], 'delta': 1,
                                            'date': tile['depart'][:10]})
    fresh = main.packing_day(date=DAY, days=2)
    p2 = [b for d in fresh['days'] for b in d['blocks']
          if b['key'] == prep['key']][0]
    t2 = [t for t in p2['tiles'] if t['key'] == tile['key']][0]
    check(t2['done'], f"a fully claimed tile should read as done: {t2}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} packing api scenarios passed")
