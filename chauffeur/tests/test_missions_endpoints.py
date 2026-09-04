"""Mission endpoints: role gates, launch, answer resumes, approve rides the rail."""
from harness import check
from services import storage, missions


def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    import datetime as _dt
    storage.set_app_state(f"mission_calls:{_dt.date.today().isoformat()}", {})
    storage.get_settings = lambda: {'missions_enabled': True,
                                    'llm_gemini_api_key': 'F',
                                    'llm_gemini_paid_api_key': 'P'}


def scenario_child_cannot_launch():
    _reset()
    import main
    from fastapi import HTTPException
    try:
        main.missions_launch(body={'goal': 'x', 'member_id': 'kid'}, request=None)
        check(False, "child launch must raise")
    except HTTPException as e:
        check(e.status_code == 403, "child refused with 403")


def scenario_parent_launches_and_answers():
    _reset()
    import main
    res = main.missions_launch(body={'goal': 'plan picnic', 'member_id': 'mom'},
                               request=None)
    check(res['status'] == 'launched', "parent launches")
    mid = res['mission_id']
    storage.update_mission(mid, {'status': 'waiting_user'})
    out = main.missions_answer(mid, body={'text': 'budget is $50',
                                          'member_id': 'mom'}, request=None)
    row = storage.get_mission(mid)
    check(row['status'] == 'running', "an answer resumes the mission")
    notes = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'note']
    check(any('$50' in str(s.get('result_json')) for s in notes),
          "the answer lands on the transcript")


def scenario_admin_payload_shape():
    _reset()
    import main
    mid = missions.launch('g', created_by='mom')['mission_id']
    out = main.missions_admin(request=None)
    check(out['active'][0]['id'] == mid and 'steps' in out['active'][0],
          "active missions arrive with their transcript")
    check('history' in out, "history lane present")


def scenario_ack_and_drop():
    _reset()
    import main
    mid = missions.launch('g', created_by='mom')['mission_id']
    main.missions_drop(mid, body={'member_id': 'mom'}, request=None)
    check(storage.get_mission(mid)['status'] == 'dropped', "drop drops")
    main.missions_ack(mid, body={'member_id': 'mom'}, request=None)
    check(storage.get_mission(mid)['acknowledged_at'], "ack quiets the finding")


if __name__ == '__main__':
    scenario_child_cannot_launch()
    scenario_parent_launches_and_answers()
    scenario_admin_payload_shape()
    scenario_ack_and_drop()
    print("test_missions_endpoints OK")
