"""The hand path. Every capability the agent has, a person has by tap."""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


def _denied(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _reset():
    storage.programs_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})


def scenario_the_endpoints_exist():
    import main
    paths = {r.path for r in main.app.routes}
    for p in ('/programs', '/api/programs', '/api/programs/{program_id}/approve',
              '/api/programs/{program_id}/session',
              '/api/programs/{program_id}/milestone',
              '/api/programs/{program_id}/pause',
              '/api/programs/{program_id}/drop'):
        check(p in paths, f"{p} must be reachable by hand")


def scenario_a_body_aim_is_refused_at_the_door():
    _reset()
    import main
    res = main.create_program(body={'member_id': 'kid',
                                    'title': 'lose 15 pounds'}, request=None)
    check(res.get('status') == 'error', f"got {res}")
    check(res.get('alternatives'), "and the behaviour version is offered")
    check(storage.get_programs(include_finished=True) == [],
          "and nothing was created to accept later")


def scenario_a_child_cannot_approve():
    _reset()
    import main
    check(_denied(main.approve_program, 'nope',
                  body={'member_id': 'kid'}, request=None) == 403,
          "approving claims the family's week — that is grown-up work")


def scenario_logging_a_session_is_reachable():
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'state': 'active'})
    res = main.log_program_session(pid, body={'minutes': 25,
                                              'member_id': 'kid'}, request=None)
    check(res.get('status') == 'success', f"got {res}")
    check(len(storage.get_program(pid)['sessions']) == 1, "and it counted")


if __name__ == '__main__':
    scenario_the_endpoints_exist()
    scenario_a_body_aim_is_refused_at_the_door()
    scenario_a_child_cannot_approve()
    scenario_logging_a_session_is_reachable()
    print("test_programs_endpoints OK")
