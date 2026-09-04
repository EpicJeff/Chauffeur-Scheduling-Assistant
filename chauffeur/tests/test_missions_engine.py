"""Engine behavior with a scripted fake LLM. Storage scenarios first."""
from harness import check
from services import storage


def _reset():
    storage.missions_table.truncate()
    storage.mission_steps_table.truncate()


def scenario_mission_rows_round_trip():
    _reset()
    mid = storage.add_mission({'goal': 'find a magician', 'origin_kind': 'manual',
                               'created_by': 'mom', 'tier': 'mission'})
    row = storage.get_mission(mid)
    check(row and row['status'] == 'running' and row['step_count'] == 0
          and row['acknowledged_at'] is None,
          "defaults: running, zero steps, unacknowledged")
    storage.add_mission_step(mid, {'kind': 'llm', 'name': 'plan',
                                   'result_json': {'action': 'finish'}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'done'})
    steps = storage.get_mission_steps(mid)
    check([s['idx'] for s in steps] == [0, 1], "steps auto-index in order")
    check(storage.update_mission(mid, {'status': 'done'}), "update writes")
    check(storage.get_missions(status='done')[0]['id'] == mid, "status filter")
    check(storage.get_missions(status=['done', 'blocked'])[0]['id'] == mid,
          "list filter")


def scenario_prune_spares_active_and_steps_follow():
    _reset()
    old = storage.add_mission({'goal': 'g', 'origin_kind': 'manual'})
    storage.add_mission_step(old, {'kind': 'note', 'name': 'n'})
    storage.update_mission(old, {'status': 'done', 'finished_at': 1.0})
    live = storage.add_mission({'goal': 'g2', 'origin_kind': 'manual'})
    n = storage.prune_missions(before_ts=2.0)
    check(n == 1 and storage.get_mission(live) and not storage.get_mission(old),
          "prune eats old terminal rows only")
    check(storage.get_mission_steps(old) == [], "pruned mission takes its steps")


if __name__ == '__main__':
    scenario_mission_rows_round_trip()
    scenario_prune_spares_active_and_steps_follow()
    print("test_missions_engine OK")
