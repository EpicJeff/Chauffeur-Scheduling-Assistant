"""Deep think: reconcile new/update/retire by slug, consume noticings,
skip when nothing changed, hard cap on active insights."""
import datetime
from harness import check
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

if __name__ == '__main__':
    scenario_think_reconciles()
    scenario_unchanged_snapshot_skips()
    scenario_force_overrides_hash()
    scenario_active_cap()
    scenario_dismissed_insights_stay_dismissed()
    print("test_mind_think OK")
