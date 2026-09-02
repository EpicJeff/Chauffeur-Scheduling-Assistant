"""Deep think: reconcile new/update/retire by slug, consume noticings,
skip when nothing changed, hard cap on active insights. Suppression is
dismissed-only: acted and expired slugs may return."""
import datetime
import time
from harness import check
from models.schemas import ChatMessage
from services import storage, mind

CALLS = []

def _fake_pool(insights):
    def f(tier, api_key, system, prompt, **kw):
        CALLS.append({'tier': tier, 'prompt': prompt})
        return {'insights': insights}
    return f

def _reset():
    CALLS.clear()
    storage.mind_insights_table.truncate()
    storage.mind_noticings_table.truncate()
    storage.set_app_state('mind_last_snapshot_hash', None)
    storage.set_app_state('mind_think_requested', False)
    storage.get_settings = lambda: {'llm_gemini_api_key': 'k', 'mind_enabled': True,
                                    'mind_wake_start': '00:00', 'mind_wake_end': '00:00'}

NOON = datetime.datetime(2026, 8, 27, 12, 0)

def scenario_think_reconciles():
    _reset()
    storage.add_mind_insight({'slug': 'stays', 'line': 'old text', 'category': 'c'})
    storage.add_mind_insight({'slug': 'goes', 'line': 'done with', 'category': 'c'})
    nid = storage.add_mind_noticing({'line': 'n', 'source': 'chat'})
    mind._pool_call = _fake_pool([
        {'slug': 'stays', 'line': 'new text', 'category': 'c',
         'sensitivity': 'normal', 'domain': 'kids', 'confidence': 0.9},
        {'slug': 'fresh', 'line': 'brand new', 'category': 'overload',
         'sensitivity': 'sensitive', 'domain': 'kids', 'confidence': 0.7},
    ])
    res = mind.deep_think(NOON)
    check(res['status'] == 'thought', f"got {res}")
    check(CALLS and CALLS[0]['tier'] == 'heavy', "heavy tier")
    active = {r['slug']: r for r in storage.get_mind_insights(state='active')}
    check(set(active) == {'stays', 'fresh'}, f"reconciled to {set(active)}")
    check(active['stays']['line'] == 'new text', "kept slug updates in place")
    gone = storage.get_mind_insight_by_slug('goes')
    check(gone['state'] == 'retired' and gone['outcome'] == 'expired',
          "absent slug retires as expired")
    check(not storage.get_mind_noticings(consumed=False), "noticings consumed")

def scenario_unchanged_snapshot_skips():
    res = mind.deep_think(NOON)
    check(res['status'] == 'unchanged' and len(CALLS) == 1,
          f"identical snapshot makes no call, got {res}")

def scenario_force_overrides_hash():
    res = mind.deep_think(NOON, force=True)
    check(res['status'] == 'thought' and len(CALLS) == 2, "force thinks anyway")

def scenario_active_cap():
    _reset()
    mind._pool_call = _fake_pool([{'slug': f's{i}', 'line': 'x', 'category': 'c'}
                                  for i in range(12)])
    mind.deep_think(NOON, force=True)
    check(len(storage.get_mind_insights(state='active')) <= 7,
          "never more than mind_max_insights active")

def scenario_dismissed_insights_stay_dismissed():
    _reset()
    iid = storage.add_mind_insight({'slug': 'nagged', 'line': 'x', 'category': 'c'})
    storage.update_mind_insight(iid, {'state': 'retired', 'outcome': 'dismissed'})
    mind._pool_call = _fake_pool([{'slug': 'nagged', 'line': 'x again',
                                   'category': 'c'}])
    mind.deep_think(NOON, force=True)
    row = storage.get_mind_insight_by_slug('nagged')
    check(row['state'] == 'retired', "a dismissed slug is never resurrected")

def scenario_expired_can_return_dismissed_cannot():
    # Controller ruling: suppression is DISMISSED-only. An insight that aged
    # out of the lane (expired) comes back when the situation does; the
    # family never said no to it.
    _reset()
    i1 = storage.add_mind_insight({'slug': 'came-back', 'line': 'old', 'category': 'c'})
    storage.update_mind_insight(i1, {'state': 'retired', 'outcome': 'expired',
                                     'resolved_ts': time.time()})
    i2 = storage.add_mind_insight({'slug': 'said-no', 'line': 'y', 'category': 'c'})
    storage.update_mind_insight(i2, {'state': 'retired', 'outcome': 'dismissed',
                                     'resolved_ts': time.time()})
    mind._pool_call = _fake_pool([
        {'slug': 'came-back', 'line': 'it is back', 'category': 'c'},
        {'slug': 'said-no', 'line': 'y again', 'category': 'c'}])
    mind.deep_think(NOON, force=True)
    back = storage.get_mind_insight_by_slug('came-back')
    check(back['state'] == 'active' and back['line'] == 'it is back'
          and back['outcome'] is None,
          f"an expired slug returns when the situation does, got {back}")
    check(len([r for r in storage.get_mind_insights() if r['slug'] == 'came-back']) == 1,
          "the return revives the same row, no duplicate slug rows")
    check(storage.get_mind_insight_by_slug('said-no')['state'] == 'retired',
          "a dismissed slug still never comes back")

def scenario_mid_think_chat_is_not_skipped():
    # The chat cutoff is captured when the snapshot is taken; a message that
    # lands DURING the (long) LLM call must stay ahead of the watermark.
    _reset()
    fam = storage.get_family_channel()
    if not fam:
        storage.chat_channels_table.insert({'id': 'fam1', 'kind': 'family',
                                            'member_ids': [], 'dm_key': None,
                                            'title': '', 'created_at': time.time(),
                                            'archived': False})
        fam = storage.get_family_channel()

    def pool(tier, api_key, system, prompt, **kw):
        storage.add_chat_message(ChatMessage(
            channel_id=fam['id'], sender_member_id='dad',
            body='mid-think message', ts=time.time() + 0.01).model_dump())
        return {'insights': []}

    mind._pool_call = pool
    res = mind.deep_think(NOON, force=True)
    check(res['status'] == 'thought', f"got {res}")
    wm = float(storage.get_app_state('mind_chat_snapshot_ts') or 0)
    row = [m for m in storage.get_channel_messages(fam['id'])
           if m.get('body') == 'mid-think message'][0]
    check(wm < row['ts'],
          "the watermark predates the mid-think message: the next snapshot sees it")

def scenario_think_stores_approach_and_spares_parked_rows():
    _reset()
    import time as _t
    snoozed = storage.add_mind_insight({'slug': 'parked', 'line': 'z',
                                        'category': 'c'})
    storage.update_mind_insight(snoozed, {'snoozed_until': _t.time() + 86400})
    held = storage.add_mind_insight({'slug': 'held', 'line': 'h',
                                     'category': 'c'})
    storage.update_mind_insight(held, {'state': 'in_hand', 'plan_json': {
        'created_ts': 1.0, 'steps': [{'id': 's1', 'kind': 'human',
                                      'text': 't', 'owner_member_id': None,
                                      'owner_name': '', 'due': '2026-09-09',
                                      'status': 'open', 'proposal_json': None}]}})
    mind._pool_call = _fake_pool([
        {'slug': 'fresh', 'line': 'new', 'category': 'c',
         'sensitivity': 'normal', 'domain': 'kids', 'confidence': 0.9,
         'approach': 'ask an outside hand to cover Tuesday'},
        {'slug': 'held', 'line': 'updated text', 'category': 'c',
         'sensitivity': 'normal', 'domain': 'kids', 'confidence': 0.9},
    ])
    res = mind.deep_think(NOON)
    check(res['status'] == 'thought', f"got {res}")
    fresh = storage.get_mind_insight_by_slug('fresh')
    check(fresh['approach'] == 'ask an outside hand to cover Tuesday',
          f"approach stored, got {fresh.get('approach')}")
    parked = storage.get_mind_insight_by_slug('parked')
    check(parked['state'] == 'active' and parked['outcome'] is None,
          "omitted snoozed row is NOT retired — a snooze is not a dismiss")
    h = storage.get_mind_insight_by_slug('held')
    check(h['state'] == 'in_hand' and h['line'] == 'updated text',
          "re-emitted in-hand slug updates fields, keeps state")
    check('snoozed until' in CALLS[0]['prompt']
          and 'in hand' in CALLS[0]['prompt'],
          "the prompt shows the model what is parked and what is in hand")

def scenario_a_revived_slug_starts_clean():
    """I3: reviving reused the same row and kept whatever was hanging off it.
    An acted slug came back carrying the plan whose steps were all closed
    (a checklist of last month's work), the proposal_json still wired to the
    Approve button, and a snooze that would silence it the moment it
    returned. It is a NEW observation; it arrives with nothing attached."""
    _reset()
    iid = storage.add_mind_insight({'slug': 'returns', 'line': 'old',
                                    'category': 'c'})
    storage.update_mind_insight(iid, {
        'state': 'retired', 'outcome': 'acted', 'resolved_ts': time.time(),
        'snoozed_until': time.time() + 86400,
        'proposal_json': {'proposal_id': 'old-pr', 'summary': 'stale'},
        'plan_json': {'created_ts': 1.0, 'steps': [
            {'id': 's1', 'kind': 'human', 'text': 'done long ago',
             'owner_member_id': None, 'owner_name': '', 'due': '2026-01-01',
             'status': 'done', 'proposal_json': None}]}})
    mind._pool_call = _fake_pool([{'slug': 'returns', 'line': 'it is back',
                                   'category': 'c'}])
    mind.deep_think(NOON, force=True)
    row = storage.get_mind_insight_by_slug('returns')
    check(row['state'] == 'active' and row['line'] == 'it is back',
          f"the slug returns, got {row['state']}")
    check(row['plan_json'] is None, f"no stale checklist, got {row['plan_json']}")
    check(row['proposal_json'] is None,
          f"no stale Approve button, got {row['proposal_json']}")
    check(row['snoozed_until'] is None,
          f"and it is not born parked, got {row['snoozed_until']}")
    check(mind.visible_insights({'id': 'mom', 'role': 'parent'}, now=NOON),
          "so it is actually in the lane")


if __name__ == '__main__':
    scenario_think_reconciles()
    scenario_unchanged_snapshot_skips()
    scenario_force_overrides_hash()
    scenario_active_cap()
    scenario_dismissed_insights_stay_dismissed()
    scenario_expired_can_return_dismissed_cannot()
    scenario_mid_think_chat_is_not_skipped()
    scenario_think_stores_approach_and_spares_parked_rows()
    scenario_a_revived_slug_starts_clean()
    print("test_mind_think OK")
