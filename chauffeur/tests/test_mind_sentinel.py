"""Sentinel: coalesced deltas -> one gemma call -> noticings. No deltas, no call.
Chat rows are seeded through the real ChatMessage schema so the field names
(body / sender_member_id) stay pinned — a mind.py reading 'text'/'member_id'
must fail here."""
import datetime
import time
from harness import check
from models.schemas import ChatMessage
from services import storage, mind


CALLS = []

def _fake_pool(tier, api_key, system, prompt, **kw):
    CALLS.append({'tier': tier, 'prompt': prompt})
    return {'noticings': [{'line': 'sunscreen is out', 'source': 'chat',
                           'urgency': 'low'}]}


def _ensure_family_channel():
    fam = storage.get_family_channel()
    if not fam:
        storage.chat_channels_table.insert({'id': 'fam1', 'kind': 'family',
                                            'member_ids': [], 'dm_key': None,
                                            'title': '', 'created_at': time.time(),
                                            'archived': False})
        fam = storage.get_family_channel()
    return fam


def _reset():
    CALLS.clear()
    storage.mind_noticings_table.truncate()
    for k in ('mind_chat_watermark', 'mind_event_state', 'mind_finding_keys',
              'mind_shop_hash'):
        storage.set_app_state(k, None)
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'mind_enabled': True}
    mind._pool_call = _fake_pool


def scenario_delta_produces_noticing():
    _reset()
    fam = _ensure_family_channel()
    storage.add_chat_message(ChatMessage(
        channel_id=fam['id'], sender_member_id='mom',
        body='we are out of sunscreen').model_dump())
    res = mind.sentinel_sweep()
    check(res['status'] == 'swept', f"delta sweeps, got {res}")
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'background',
          "one background-tier call per sweep")
    check('we are out of sunscreen' in CALLS[0]['prompt'],
          "the message BODY reaches the sentinel prompt")
    rows = storage.get_mind_noticings(consumed=False)
    check(rows and rows[0]['line'] == 'sunscreen is out', "noticing stored")


def scenario_no_deltas_no_call():
    res = mind.sentinel_sweep()          # watermark advanced by prior sweep
    check(res['status'] == 'no_deltas', f"quiet house makes no LLM call, got {res}")
    check(len(CALLS) == 1, "call count unchanged")


def scenario_cap_stops_calls():
    _reset()
    day_key = f"mind_calls:{__import__('datetime').date.today().isoformat()}"
    storage.set_app_state(day_key, {'sentinel': 400})
    fam = _ensure_family_channel()
    storage.add_chat_message(ChatMessage(
        channel_id=fam['id'], sender_member_id='mom',
        body='another line').model_dump())
    res = mind.sentinel_sweep()
    check(res['status'] == 'capped' and not CALLS, "cap reached = silent skip")


def _day(offset):
    return (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()


def scenario_calendar_deltas_name_events_and_see_ghosts():
    # Delta lines carry titles, never bare ids; ghost coverage is part of the
    # fingerprint, so an outside hand taking (or dropping) a ride is a change.
    _reset()
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'e1', 'title': 'Piano', 'start': f'{_day(1)}T15:00:00',
                        'end': f'{_day(1)}T16:00:00'}],
            'assignments': {}, 'ghost_assignments': {'e1': 'ghost_grandma'}}
        mind._gather_deltas(datetime.datetime.now())     # baseline, no storm
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'e1', 'title': 'Piano', 'start': f'{_day(1)}T15:00:00',
                        'end': f'{_day(1)}T16:00:00'},
                       {'id': 'e2', 'title': 'Dentist', 'start': f'{_day(2)}T09:00:00',
                        'end': f'{_day(2)}T10:00:00'}],
            'assignments': {}, 'ghost_assignments': {}}
        cal = [d for d in mind._gather_deltas(datetime.datetime.now())
               if d.startswith('[calendar]')]
        check(any(f'new: Dentist ({_day(2)}' in d for d in cal),
              f"a new event delta names the event and its date, got {cal}")
        check(any('changed: Piano' in d for d in cal),
              f"losing the ghost coverage is a named change, got {cal}")
        check(not any('new: e2' in d or 'changed: e1' in d for d in cal),
              "no bare event ids in delta lines")
    finally:
        storage.get_cached_schedule = orig


def scenario_past_events_expire_silently():
    # The cache is a rolling forward window: an event whose date has passed
    # falling out of it is time, not a removal. The Mind must never turn
    # history into "removed from the calendar" — that is how it once claimed
    # a weeks-old event was missing this week.
    _reset()
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'old', 'title': 'Recital', 'start': f'{_day(-14)}T15:00:00',
                        'end': f'{_day(-14)}T16:00:00'},
                       {'id': 'e1', 'title': 'Piano', 'start': f'{_day(1)}T15:00:00',
                        'end': f'{_day(1)}T16:00:00'}],
            'assignments': {}, 'ghost_assignments': {}}
        deltas = mind._gather_deltas(datetime.datetime.now())   # baseline
        # Past event was never tracked at all.
        state = dict(storage.get_app_state('mind_event_state') or {})
        check('old' not in state, "a past-dated event is never fingerprinted")
        # The past event vanishing from the cache produces NO delta.
        storage.get_cached_schedule = lambda: {
            'events': [{'id': 'e1', 'title': 'Piano', 'start': f'{_day(1)}T15:00:00',
                        'end': f'{_day(1)}T16:00:00'}],
            'assignments': {}, 'ghost_assignments': {}}
        cal = [d for d in mind._gather_deltas(datetime.datetime.now())
               if d.startswith('[calendar]')]
        check(cal == [], f"expiry is silent, got {cal}")
        # A stored FUTURE event that truly disappears still reads as removed.
        storage.get_cached_schedule = lambda: {
            'events': [], 'assignments': {}, 'ghost_assignments': {}}
        cal = [d for d in mind._gather_deltas(datetime.datetime.now())
               if d.startswith('[calendar]')]
        check(any('removed: Piano' in d for d in cal),
              f"a real removal of a future event still surfaces, got {cal}")
    finally:
        storage.get_cached_schedule = orig


if __name__ == '__main__':
    scenario_delta_produces_noticing()
    scenario_no_deltas_no_call()
    scenario_cap_stops_calls()
    scenario_calendar_deltas_name_events_and_see_ghosts()
    scenario_past_events_expire_silently()
    print("test_mind_sentinel OK")
