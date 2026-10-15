"""The stage contract and the plan record (planned missions spec §1, §3; Codex
F2, F6, G2).

A build-stage row may use a tool only when `planned.CONTRACT` describes it:
which arguments are record ids (`targets`), whether it takes an idempotency
key (`idem`), what it creates (`creates`) and how many model calls it can make
(`model_calls`). Names are never accepted where an id is meant.

Pinned here (Task 6, block A — the core; the tools' conformance is
tests/test_stage_contract_tools.py):
  * the contract covers exactly the spec's eight domains plus `draft_message`;
  * every entry is well-formed, every tool is a registry handler or an admin
    action, every target argument is in the tool's schema;
  * `check_row` refuses a tool with no contract, a name-lookup argument
    (occasion_name, thread_title, list_name, trip_name), a target that is not
    an existing record of its kind, and accepts a `$ref`;
  * `check_rows` refuses more than 15 rows and more than 3 model-calling rows;
  * `snapshot` changes with any row, exclusion, goal, step budget, plan rev or
    subject triple, and is stable otherwise;
  * `new_plan` has the record's shape; a new mission has `plan: None`.

Run from chauffeur/:  python tests/test_stage_contract.py
"""
from harness import check  # noqa: F401
from services import storage, chat_actions, subjects
from services import agent_tools_v2 as tools
from test_subjects import _reset, _seed

EXPECTED = {
    'add_occasion', 'add_occasion_guests', 'set_occasion_attendance', 'answer_occasion_question', 'stamp_occasion_template',
    'add_occasion_dishes', 'set_occasion_menu', 'source_for_occasion', 'add_occasion_gift_list',
    'create_trip', 'add_trip_poi', 'add_trip_accommodation', 'manage_trip_flights', 'schedule_trip_itinerary',
    'propose_program',
    'create_list', 'add_shopping_items',
    'add_errand', 'create_event',
    'create_thread', 'add_thread_note', 'draft_thread_message',
    'add_household_task',
    'draft_message',
    # Projects core Task 8: a plan's stage can add to and move a project.
    'add_project_step', 'add_to_project', 'set_project_state', 'set_step_state',
}


def _planned():
    from services import planned
    return planned


def scenario_the_contract_covers_the_eight_domains():
    p = _planned()
    check(set(p.CONTRACT) == EXPECTED, f"exactly the spec's table: extra {sorted(set(p.CONTRACT) - EXPECTED)}, missing {sorted(EXPECTED - set(p.CONTRACT))}")
    for name, c in p.CONTRACT.items():
        check(set(c) >= {'targets', 'idem', 'creates', 'model_calls'}, f"{name} well-formed: {c}")
        check(isinstance(c['targets'], dict) and isinstance(c['idem'], bool) and isinstance(c['model_calls'], int) and c['model_calls'] >= 0,
              f"{name} types: {c}")
        if name == 'draft_message':
            continue
        check(name in tools.TOOL_HANDLERS or name in chat_actions.ADMIN_ACTIONS, f"{name} is a real door")
        props = ((tools.TOOL_SCHEMAS.get(name) or {}).get('properties') or {})
        if name in tools.TOOL_SCHEMAS:
            for arg in c['targets']:
                check(arg in props, f"{name}'s target {arg} is in its schema: {sorted(props)}")
    for name, c in p.CONTRACT.items():
        if c['idem'] and name in tools.TOOL_SCHEMAS:
            check('idem' in ((tools.TOOL_SCHEMAS[name] or {}).get('properties') or {}),
                  f"{name} claims a retry key, so its schema takes one")
    for name in ('add_occasion_dishes', 'source_for_occasion', 'propose_program'):
        check(p.CONTRACT[name]['model_calls'] >= 1, f"{name} calls a model")
    check(p.CONTRACT['propose_program']['model_calls'] >= 3, "the curator's research, shaping and retry are counted")
    check(p.CAPS == {'questions': 5, 'rounds': 2, 'stages': 7, 'rows': 15, 'model_rows': 3, 'stage_seconds': 120, 'work_steps': 12},
          f"the caps: {p.CAPS}")


def scenario_check_row_wants_ids_never_names():
    _reset()
    _seed()
    p = _planned()
    check('not stage-ready' in (p.check_row({'id': 'r1', 'tool': 'adjust_points', 'args': {}}) or ''), "no contract, no row")
    check(p.check_row({'id': 'r1', 'tool': 'add_occasion_guests', 'args': {'occasion_name': "Kate's 10th birthday", 'who': 'The Wilsons'}}),
          "a name lookup is refused")
    err = p.check_row({'id': 'r1', 'tool': 'add_occasion_guests', 'args': {'occasion_id': "Kate's 10th birthday", 'who': 'The Wilsons'}})
    check(err and 'id' in err, f"a title in an id slot is refused: {err}")
    check(p.check_row({'id': 'r1', 'tool': 'add_occasion_guests', 'args': {'occasion_id': 'o1', 'who': 'The Wilsons'}}) is None,
          "an existing occasion id is fine")
    check(p.check_row({'id': 'r2', 'tool': 'add_occasion_guests',
                       'args': {'occasion_id': {'$ref': 'r1', 'kind': 'occasion'}, 'who': 'The Wilsons'}}) is None,
          "a $ref to an earlier row's created record is fine")
    check(p.check_row({'id': 'r3', 'tool': 'add_trip_poi', 'args': {'trip_id': 'ev_nope', 'title': 'x'}}), "a trip that does not exist")
    check(p.check_row({'id': 'r4', 'tool': 'draft_message', 'args': {'to': 'Grandma', 'words': 'Come to the party'}}) is None,
          "a mission-local draft needs no target")


def scenario_check_rows_caps_size_and_model_rows():
    _reset()
    _seed()
    p = _planned()
    many = [{'id': f'r{i}', 'tool': 'draft_message', 'args': {'to': 'x', 'words': 'y'}} for i in range(16)]
    check(p.check_rows(many), "16 rows refused")
    check(p.check_rows(many[:15]) is None, "15 rows fine")
    models = [{'id': f'm{i}', 'tool': 'source_for_occasion', 'args': {'occasion_id': 'o1', 'needed': 'x'}} for i in range(4)]
    check(p.check_rows(models), "4 model-calling rows refused")
    check(p.check_rows(models[:3]) is None, "3 fine")


def scenario_snapshots_cover_what_was_shown():
    p = _planned()
    build = {'id': 's1', 'kind': 'build', 'rows': [{'id': 'r1', 'tool': 'draft_message', 'args': {'to': 'a', 'words': 'b'}, 'state': 'proposed'}]}
    subj = ['occasion', 'o1', 1]
    a = p.snapshot(build, subj, plan_rev=1)
    check(a == p.snapshot(build, subj, plan_rev=1), "stable")
    changed = {**build, 'rows': [{**build['rows'][0], 'args': {'to': 'a', 'words': 'c'}}]}
    check(p.snapshot(changed, subj, plan_rev=1) != a, "a row's args")
    excluded = {**build, 'rows': [{**build['rows'][0], 'state': 'excluded'}]}
    check(p.snapshot(excluded, subj, plan_rev=1) != a, "an exclusion")
    check(p.snapshot(build, ['occasion', 'o1', 2], plan_rev=1) != a, "the subject revision")
    work = {'id': 's2', 'kind': 'work', 'goal': 'find lessons', 'step_budget': 8}
    w = p.snapshot(work, subj, plan_rev=1)
    check(p.snapshot({**work, 'goal': 'find a piano'}, subj, plan_rev=1) != w, "a work stage's goal")
    check(p.snapshot({**work, 'step_budget': 9}, subj, plan_rev=1) != w, "its budget")
    check(p.snapshot(work, subj, plan_rev=2) != w, "the plan's rev")


def scenario_the_plan_record_and_the_mission_default():
    _reset()
    p = _planned()
    plan = p.new_plan()
    check(plan['state'] == 'interviewing' and plan['rev'] == 0 and plan['questions'] == [] and plan['stages'] == []
          and plan.get('approved_by') is None, f"the record: {plan}")
    mid = storage.add_mission({'goal': 'x', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    check('plan' in storage.get_mission(mid) and storage.get_mission(mid)['plan'] is None, "a new mission carries no plan")


SCENARIOS = [
    scenario_the_contract_covers_the_eight_domains,
    scenario_check_row_wants_ids_never_names,
    scenario_check_rows_caps_size_and_model_rows,
    scenario_snapshots_cover_what_was_shown,
    scenario_the_plan_record_and_the_mission_default,
]

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
