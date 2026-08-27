"""Chat can read the lane; sensitivity respects the asking member's role."""
from harness import check
from services import storage, agent_tools_v2

def _seed():
    storage.mind_insights_table.truncate()
    storage.add_mind_insight({'slug': 'a', 'line': 'normal', 'category': 'c',
                              'sensitivity': 'normal'})
    storage.add_mind_insight({'slug': 'b', 'line': 'secret', 'category': 'c',
                              'sensitivity': 'sensitive'})

def scenario_list_respects_role():
    _seed()
    parent = agent_tools_v2.list_insights(member_role='parent')
    child = agent_tools_v2.list_insights(member_role='child')
    check(len(parent['insights']) == 2, "parent sees all")
    check(len(child['insights']) == 1, "child payload has no sensitive row")

def scenario_dismiss_tool():
    _seed()
    row = storage.get_mind_insight_by_slug('a')
    res = agent_tools_v2.dismiss_insight(insight_id=row['id'])
    check(res['status'] == 'success', f"got {res}")
    check(storage.get_mind_insight_by_slug('a')['outcome'] == 'dismissed',
          "outcome recorded")

def scenario_dismiss_gated_for_child():
    _seed()
    row = storage.get_mind_insight_by_slug('a')
    res = agent_tools_v2.dismiss_insight(insight_id=row['id'], member_role='child')
    check(res['status'] == 'error', f"child dismiss refused, got {res}")
    check(storage.get_mind_insight_by_slug('a')['outcome'] is None,
          "refused dismiss writes nothing")

def scenario_registered():
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    check('list_insights' in names and 'dismiss_insight' in names,
          "both tools in the catalog")

if __name__ == '__main__':
    scenario_list_respects_role()
    scenario_dismiss_tool()
    scenario_dismiss_gated_for_child()
    scenario_registered()
    print("test_mind_agent_tools OK")
