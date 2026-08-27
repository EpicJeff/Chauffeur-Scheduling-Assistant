"""Sentinel: coalesced deltas -> one gemma call -> noticings. No deltas, no call."""
import time
from harness import check
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
    storage.chat_messages_table.insert({'id': 'mA', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'we are out of sunscreen'})
    res = mind.sentinel_sweep()
    check(res['status'] == 'swept', f"delta sweeps, got {res}")
    check(len(CALLS) == 1 and CALLS[0]['tier'] == 'background',
          "one background-tier call per sweep")
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
    storage.chat_messages_table.insert({'id': 'mB', 'channel_id': fam['id'],
                                        'member_id': 'mom', 'ts': time.time(),
                                        'text': 'another line'})
    res = mind.sentinel_sweep()
    check(res['status'] == 'capped' and not CALLS, "cap reached = silent skip")


if __name__ == '__main__':
    scenario_delta_produces_noticing()
    scenario_no_deltas_no_call()
    scenario_cap_stops_calls()
    print("test_mind_sentinel OK")
