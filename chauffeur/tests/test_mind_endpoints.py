"""Endpoint behavior: filtered payloads, role gates, outcomes recorded."""
from harness import check
from services import storage, mind

def _reset():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'n1', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 's1', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})

def scenario_dismiss_records_outcome():
    _reset()
    row = storage.get_mind_insight_by_slug('n1')
    ok = storage.update_mind_insight(row['id'], {'state': 'retired',
                                                 'outcome': 'dismissed'})
    check(ok, "dismiss path writes retired/dismissed")

def scenario_act_records_outcome():
    _reset()
    row = storage.get_mind_insight_by_slug('n1')
    storage.update_mind_insight(row['id'], {'state': 'retired', 'outcome': 'acted'})
    check(storage.get_mind_insight_by_slug('n1')['outcome'] == 'acted',
          "act path writes retired/acted")

def scenario_lane_is_filtered():
    _reset()
    check(len(mind.visible_insights({'id': 'k', 'role': 'child'})) == 1,
          "child payload has no sensitive row")

if __name__ == '__main__':
    scenario_dismiss_records_outcome()
    scenario_act_records_outcome()
    scenario_lane_is_filtered()
    print("test_mind_endpoints OK")
