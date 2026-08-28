"""What approving a program does to the week.

One approval covers the whole footprint, shown before the tap -- a drip of
approvals is the named killer of assistants. And it applies the way negotiation
proved: pre-flight everything, local writes before the one external write, stamp
each emission as it lands.
"""
from harness import check
from services import programs, storage


def _reset():
    storage.programs_table.truncate()
    storage.protected_commitments_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})


def _mk():
    return storage.add_program({
        'member_id': 'lily', 'title': 'Play campfire songs by summer',
        'shape': {'sessions_per_week': 3, 'minutes': 25,
                  'preferred_days': [1, 3, 5]},
        'phases': [{'name': 'Phase 1', 'weeks': 4, 'what': 'Three chords',
                    'milestone': 'G to C', 'milestone_hit_at': None}]})


def scenario_slots_match_the_shape():
    _reset()
    slots = programs.propose_slots('lily', {'sessions_per_week': 3,
                                            'minutes': 25,
                                            'preferred_days': [1, 3, 5]})
    check(len(slots) == 3, f"one slot per session a week, got {slots}")
    check({s['day'] for s in slots} == {1, 3, 5},
          f"on the days they asked for, got {slots}")
    for s in slots:
        check(s['time_start'] < s['time_end'], f"a real window, got {s}")


def scenario_the_footprint_is_visible_before_the_tap():
    _reset()
    fp = programs.footprint(storage.get_program(_mk()))
    check(len(fp['slots']) == 3, f"it says what time it claims, got {fp}")
    check('thread' in fp and 'event' in fp,
          "and what else it would create, so nothing is a surprise")


def scenario_approval_claims_the_time():
    _reset()
    pid = _mk()
    res = programs.approve(pid, 'mom')
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'active', f"the program is live, got {row['state']}")
    check(row['approved_by'] == 'mom', "and records who approved it")
    ids = row['emissions']['commitment_ids']
    check(len(ids) == 3, f"three practice slots were really created, got {ids}")
    for cid in ids:
        rows = [c for c in storage.get_protected_commitments() if c['id'] == cid]
        check(rows and rows[0]['member_id'] == 'lily',
              f"and belong to whose program it is, got {rows}")


def scenario_a_failed_external_write_says_what_already_happened():
    """The calendar is the one write that reaches another system, so it goes
    last -- and when it refuses, the program must not imply nothing happened."""
    _reset()
    pid = _mk()
    storage.update_program(pid, {'baseline': {'start_date': None,
                                              'target_date': '2026-06-14',
                                              'target_event_id': None,
                                              'rebaselined_at': None,
                                              'rebaselines': 0}})
    from services import calendar as _cal
    real = _cal.create_event
    _cal.create_event = lambda *a, **kw: (_ for _ in ()).throw(
        RuntimeError('calendar said no'))
    try:
        res = programs.approve(pid, 'mom')
        row = storage.get_program(pid)
        check(res['status'] == 'error', f"it reports the failure, got {res}")
        check('already' in (res.get('message') or '').lower()
              or row['emissions']['commitment_ids'],
              f"and does not pretend nothing happened, got {res}")
    finally:
        _cal.create_event = real


def scenario_approving_twice_does_not_claim_twice():
    _reset()
    pid = _mk()
    programs.approve(pid, 'mom')
    before = len(storage.get_program(pid)['emissions']['commitment_ids'])
    res = programs.approve(pid, 'mom')
    after = len(storage.get_program(pid)['emissions']['commitment_ids'])
    check(res['status'] == 'error', f"a second approval is refused, got {res}")
    check(before == after, "and claims no more of the week")


if __name__ == '__main__':
    scenario_slots_match_the_shape()
    scenario_the_footprint_is_visible_before_the_tap()
    scenario_approval_claims_the_time()
    scenario_a_failed_external_write_says_what_already_happened()
    scenario_approving_twice_does_not_claim_twice()
    print("test_programs_footprint OK")
