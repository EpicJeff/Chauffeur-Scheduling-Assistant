"""Mind storage: noticings queue + insights lane, findings-trio conventions."""
import time
from harness import check
from services import storage


def _reset():
    storage.mind_noticings_table.truncate()
    storage.mind_insights_table.truncate()


def scenario_noticing_roundtrip():
    _reset()
    nid = storage.add_mind_noticing({'line': 'sunscreen mentioned in chat',
                                     'source': 'chat', 'urgency': 'low',
                                     'refs': []})
    rows = storage.get_mind_noticings(consumed=False)
    check(len(rows) == 1 and rows[0]['id'] == nid,
          "an unconsumed noticing is visible")
    check(rows[0].get('consumed_at') is None, "fresh noticing is unconsumed")
    n = storage.consume_mind_noticings([nid])
    check(n == 1, "consume reports one row touched")
    check(storage.get_mind_noticings(consumed=False) == [],
          "consumed noticing leaves the unconsumed view")
    check(len(storage.get_mind_noticings(consumed=True)) == 1,
          "consumed noticing still exists for the audit trail")


def scenario_insight_lifecycle():
    _reset()
    iid = storage.add_mind_insight({'slug': 'ellie-overload', 'line': 'Six activity nights',
                                    'detail': '', 'domain': 'kids',
                                    'sensitivity': 'sensitive', 'category': 'overload',
                                    'proposal_json': None, 'confidence': 0.8})
    row = storage.get_mind_insight_by_slug('ellie-overload')
    check(row and row['id'] == iid, "insight retrievable by slug")
    check(row['state'] == 'active', "new insight defaults active")
    check(storage.update_mind_insight(iid, {'state': 'retired', 'outcome': 'dismissed',
                                            'resolved_ts': time.time()}),
          "update by id succeeds")
    check(storage.get_mind_insights(state='active') == [],
          "retired insight leaves the active view")
    check(storage.get_mind_insights(state='retired')[0]['outcome'] == 'dismissed',
          "outcome survives on the retired record")


def scenario_prune_spares_active():
    _reset()
    old = time.time() - 200 * 86400
    a = storage.add_mind_insight({'slug': 'keep-me', 'line': 'x', 'category': 'c'})
    b = storage.add_mind_insight({'slug': 'old-retired', 'line': 'y', 'category': 'c'})
    storage.update_mind_insight(a, {'created_ts': old})
    storage.update_mind_insight(b, {'state': 'retired', 'outcome': 'expired',
                                    'resolved_ts': old, 'created_ts': old})
    storage.add_mind_noticing({'line': 'stale', 'source': 'chat'})
    storage.mind_noticings_table.update({'ts': old})
    doomed = storage.prune_mind(time.time() - 120 * 86400)
    check(doomed == 2, f"prune removes old retired insight + old noticing, got {doomed}")
    check(storage.get_mind_insight_by_slug('keep-me'),
          "ACTIVE insights are never pruned regardless of age")


if __name__ == '__main__':
    scenario_noticing_roundtrip()
    scenario_insight_lifecycle()
    scenario_prune_spares_active()
    print("test_mind_storage OK")
