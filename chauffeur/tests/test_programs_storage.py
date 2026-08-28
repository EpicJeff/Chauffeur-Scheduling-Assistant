"""A program: an aim, a cited path, a shape, and a log that only grows.

The six progress rules from the design are enforced by what this object
CANNOT express. These scenarios are the enforcement.
"""
from harness import check
from services import programs, storage


def _reset():
    storage.programs_table.truncate()


def _mk(**kw):
    data = {'member_id': 'lily', 'title': 'Play campfire songs by summer',
            'shape': {'sessions_per_week': 3, 'minutes': 25,
                      'preferred_days': [1, 3, 5]}}
    data.update(kw)
    return storage.add_program(data)


def scenario_roundtrip_and_defaults():
    _reset()
    pid = _mk()
    row = storage.get_program(pid)
    check(row['state'] == 'proposed', f"a new program is only proposed, got {row['state']}")
    check(row['sessions'] == [], "and has done nothing yet")
    check(row['emissions'] == {'commitment_ids': [], 'thread_ids': [],
                               'event_ids': []},
          f"and claims nothing yet, got {row['emissions']}")
    check(row['source']['hand_written'] is False,
          "hand_written defaults false — it becomes true only when curation finds nothing")


def scenario_sessions_are_append_only():
    _reset()
    pid = _mk()
    storage.append_program_session(pid, {'minutes': 25, 'source': 'asked'})
    storage.append_program_session(pid, {'minutes': 10, 'source': 'added'})
    log = storage.get_program(pid)['sessions']
    check(len(log) == 2 and log[0]['minutes'] == 25,
          f"entries keep their order, got {log}")
    check(all(e.get('ts') for e in log), "and are stamped")


def scenario_progress_only_counts_up():
    _reset()
    pid = _mk()
    for _ in range(4):
        storage.append_program_session(pid, {'minutes': 25, 'source': 'asked'})
    p = programs.progress(storage.get_program(pid))
    check(p['sessions'] == 4 and p['minutes'] == 100, f"got {p}")
    check(p['milestones_hit'] == 0, "no milestone claimed yet")
    check(set(p) == {'sessions', 'minutes', 'milestones_hit', 'phase'},
          f"exactly the declared interface, no total to divide by, got {sorted(p)}")


def scenario_no_streak_can_be_derived():
    """The central rule. A streak needs a current-run or a last-gap; if the
    object cannot hold one, no surface can ever render one."""
    _reset()
    pid = _mk()
    storage.append_program_session(pid, {'minutes': 25, 'source': 'asked'})
    row = storage.get_program(pid)
    banned = ('streak', 'current_run', 'run_length', 'last_session_gap',
              'days_since', 'missed', 'missed_count', 'target_weight',
              'calories', 'rank', 'vs_member')
    flat = (set(row) | set(row.get('shape') or {}) | set(row.get('baseline') or {})
            | set(row.get('source') or {}) | set(row.get('emissions') or {}))
    for phase in row.get('phases') or []:
        flat |= set(phase)
    for session in row.get('sessions') or []:
        flat |= set(session)
    for bad in banned:
        check(bad not in flat, f"the schema must not be able to hold '{bad}'")


def scenario_banned_keys_are_refused_not_ignored():
    """Finding 1: a screen on every write path, not just the one the model
    validates -- update_program bypasses the model entirely, and phases/
    source/shape/baseline/emissions/session entries are all Dict[str, Any],
    so pydantic waves their content through unchecked."""
    _reset()
    pid = _mk()

    def _raises(fn):
        try:
            fn()
            return False
        except ValueError:
            return True

    check(_raises(lambda: storage.update_program(pid, {'streak': 5})),
          "a top-level banned key on update_program must raise")
    check(_raises(lambda: _mk(phases=[{'name': 'Phase 1', 'streak': 3}])),
          "a banned key inside a phase must raise at creation")
    check(_raises(lambda: storage.append_program_session(
              pid, {'minutes': 10, 'missed_count': 2})),
          "a banned key on a session entry must raise on append")
    # and none of it stuck
    row = storage.get_program(pid)
    check('streak' not in row, "the rejected update must not have landed")
    check(len(row['sessions']) == 0, "the rejected session must not have landed")


def scenario_a_milestone_can_only_be_hit():
    _reset()
    pid = _mk(phases=[{'name': 'Phase 1', 'weeks': 4, 'what': 'Three chords',
                       'milestone': 'switch G to C without looking',
                       'milestone_hit_at': None}])
    phase = storage.get_program(pid)['phases'][0]
    check(set(phase) == {'name', 'weeks', 'what', 'milestone', 'milestone_hit_at'},
          f"a phase carries no way to record a miss, got {sorted(phase)}")


def scenario_listing_hides_what_is_over():
    _reset()
    a, b = _mk(), _mk(title='Couch to 5K')
    storage.update_program(b, {'state': 'dropped'})
    check(len(storage.get_programs()) == 1, "a dropped program is out of the way")
    check(len(storage.get_programs(include_finished=True)) == 2, "but not gone")
    check(storage.get_programs(member_id='lily')[0]['id'] == a, "filter by whose it is")


if __name__ == '__main__':
    scenario_roundtrip_and_defaults()
    scenario_sessions_are_append_only()
    scenario_progress_only_counts_up()
    scenario_no_streak_can_be_derived()
    scenario_banned_keys_are_refused_not_ignored()
    scenario_a_milestone_can_only_be_hit()
    scenario_listing_hides_what_is_over()
    print("test_programs_storage OK")
