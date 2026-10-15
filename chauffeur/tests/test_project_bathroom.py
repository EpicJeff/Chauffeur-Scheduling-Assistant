"""Acceptance: "renovate the bathroom" as a project with an ordered checklist
(Projects core spec §6, Task 12). Real registry; the model is faked.

  demo (Mom) -> find tile (Argyle, research) -> order tile (Argyle, a write) -> tile the floor (Aunt Jo)

  * approved once; research waits for the demo (the mission parks);
  * Mom ticks demo: research runs by itself and finishes with what it found;
  * the order is a write, so it comes back as a "Do this" card; nothing is
    written before the tap; after it, the list exists and is a piece;
  * Aunt Jo cannot tick tiling before the order step is done; after, she can.

Run from chauffeur/:  python tests/test_project_bathroom.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations
from test_planned_missions import _fresh as _fresh_planned, _plan_of
from test_mission_subject import _plan, _step, _mission
from test_subjects import MOM, AUNT


def _fresh():
    _fresh_planned(step_cap=200)
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = lambda: dict(base, missions_enabled=True)


def _stage(mid, sid):
    return next(s for s in _plan_of(mid)['stages'] if s['id'] == sid)


def _step_row(pid, title):
    return next(s for s in storage.get_project(pid)['steps'] if s['title'] == title)


def scenario_the_bathroom():
    from services import planned, projects
    _fresh()
    mid = _mission(created_by='mom')
    storage.update_mission(mid, {'goal': 'renovate the bathroom'})
    _plan({'action': 'interview', 'questions': [{'key': 'budget', 'ask': 'Budget?', 'kind': 'number'}]})
    _step(mid)
    planned.answer_plan(mid, {'budget': 3000}, dict(MOM))
    _plan({'action': 'plan',
           'project': {'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it every day', 'owner': 'mom', 'audience': 'household'},
           'steps': [{'id': 'demo', 'title': 'Demo the old tile', 'owner': 'mom', 'needs': []},
                     {'id': 'lay', 'title': 'Tile the floor', 'owner': 'aunt', 'needs': ['order']}],
           'stages': [{'id': 'find', 'kind': 'work', 'title': 'Find tile', 'why': 'x', 'goal': 'three tiles under $5 a square',
                       'step_budget': 4, 'makes': ['three tiles'], 'needs': ['demo']},
                      {'id': 'order', 'kind': 'build', 'title': 'Order tile', 'why': 'x', 'makes': ['a tile order list'], 'needs': ['find']}]})
    _step(mid)
    situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{_plan_of(mid)['rev']}:approve", payload={}, actor=dict(MOM))
    pid = storage.get_projects()[0]['id']
    _step(mid)
    check(storage.get_mission(mid)['status'] == 'waiting_step' and _stage(mid, 'find')['state'] == 'pending',
          "research waits for the demo")
    res = projects.set_step_state(pid, _step_row(pid, 'Demo the old tile')['id'], 'done', dict(MOM))
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'running', "the demo frees it")
    _step(mid)
    check(_stage(mid, 'find')['state'] == 'running', "research runs by itself")
    _plan({'action': 'stage_done', 'stage_id': 'find', 'summary': 'Three tiles', 'found': {'tiles': ['Ivory matte', 'Slate grey', 'Sand']}})
    _step(mid)
    check(_step_row(pid, 'Find tile')['state'] == 'done', "and finishes with what it found")
    before = {l['name'] for l in storage.get_shopping_lists()}
    _plan({'action': 'stage', 'stage_id': 'order', 'rows': [
        {'id': 'r1', 'tool': 'create_list', 'args': {'name': 'Tile order'}, 'summary': 'A tile order list'},
        {'id': 'r2', 'tool': 'add_shopping_items', 'needs': ['r1'], 'args': {'list_id': {'$ref': 'r1', 'kind': 'list'},
                                                                           'items': 'Ivory matte tile x 40, thinset, grout'},
         'summary': 'The tile and supplies'}]})
    _step(mid)
    st = _stage(mid, 'order')
    check(st['state'] == 'proposed' and {l['name'] for l in storage.get_shopping_lists()} == before,
          "the order comes back as a card; nothing written yet")
    lay = _step_row(pid, 'Tile the floor')['id']
    check(projects.set_step_state(pid, lay, 'done', dict(AUNT))['status'] == 'error', "tiling waits for the order")
    situations.act('mission', mid, 'run_stage', option_id=f"run_stage:order:{st['snapshot']}:approve", payload={}, actor=dict(MOM))
    lists = [l for l in storage.get_shopping_lists() if l['name'] == 'Tile order']
    check(lists and {'kind': 'list', 'id': lists[0]['id']} in [{'kind': p['kind'], 'id': p['id']} for p in storage.get_project(pid)['pieces']],
          "the list exists and is a piece")
    check(_step_row(pid, 'Order tile')['state'] == 'done', "the order step is done")
    check(projects.set_step_state(pid, lay, 'done', dict(AUNT))['status'] == 'success', "now Aunt Jo can tick tiling")


SCENARIOS = [scenario_the_bathroom]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
