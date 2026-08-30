"""A practice window nobody can see is an hour everybody books over.

An approved program claimed the week and then no shared surface drew it: the
window became a `ProtectedCommitment`, which the solver honours through
`member.driver_id` and which is deliberately private everywhere else. The
effect on a family was an invisible arrangement one person had to remember,
with no cue when it arrived and nothing saying what to do in it.
"""
import datetime

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import programs as prog
from services import storage


def _reset():
    storage.programs_table.truncate()
    storage.members_table.truncate()
    storage.protected_commitments_table.truncate()
    storage.app_state_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent',
                        'driver_id': 'D1'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})


def _program(member_id='mom', state='active', day=None, start='19:00',
             end='19:30', steps=None):
    """An approved program, with its window standing where approve() puts it."""
    day = datetime.date.today().weekday() if day is None else day
    cid = storage.add_protected_commitment({
        'id': 'c1', 'member_id': member_id, 'title': 'Guitar',
        'days_of_week': [day], 'time_start': start, 'time_end': end,
        'active': True})
    pid = storage.add_program({
        'member_id': member_id, 'title': 'Guitar', 'state': state,
        'phases': [{'name': 'Grade 1', 'weeks': 4, 'what': 'Open chords',
                    'steps': steps if steps is not None
                             else ['One minute changes: G to C'],
                    'milestone': 'G-C-D without looking',
                    'milestone_hit_at': None}],
        'emissions': {'commitment_ids': [cid], 'thread_ids': [],
                      'event_ids': []}})
    return pid, cid


def scenario_an_approved_window_has_a_date_a_time_and_the_session():
    _reset()
    today = datetime.date.today()
    _program()
    out = prog.practice_windows(today, today)
    check(len(out) == 1, f"today's window is there, got {out}")
    w = out[0]
    check(w['time_start'] == '19:00' and w['time_end'] == '19:30',
          f"with the hour it claimed, got {w}")
    check(w['member_name'] == 'Mom' and w['title'] == 'Guitar',
          f"and whose it is, so nobody books over it blind, got {w}")
    check(w['steps'] == ['One minute changes: G to C'],
          f"and what the session IS -- a time with no content is what made "
          f"this invisible twice over, got {w}")


def scenario_only_a_live_program_holds_time():
    """Pause releases the commitments outright and a proposal never claimed
    any, so neither may draw an hour on somebody else's day."""
    today = datetime.date.today()
    for state in ('proposed', 'paused', 'done', 'dropped'):
        _reset()
        _program(state=state)
        check(prog.practice_windows(today, today) == [],
              f"a {state} program claims no time")
    _reset()
    _program(state='active')
    check(len(prog.practice_windows(today, today)) == 1,
          "an active one does")


def scenario_a_released_commitment_stops_drawing():
    """The feed reads the LIVE commitment, not the id the program remembers.
    A window deleted by hand is gone from the day the moment it is gone."""
    _reset()
    today = datetime.date.today()
    pid, cid = _program()
    storage.delete_protected_commitment(cid)
    check(prog.practice_windows(today, today) == [],
          "a window that no longer exists is not drawn from a stale id")


def scenario_the_feed_spans_the_days_it_is_asked_for():
    _reset()
    today = datetime.date.today()
    _program(day=(today + datetime.timedelta(days=3)).weekday())
    check(prog.practice_windows(today, today) == [],
          "a window on another weekday is not today's")
    week = prog.practice_windows(today, today + datetime.timedelta(days=6))
    check(len(week) == 1, f"but it is this week's, got {week}")
    check(week[0]['date'] == (today + datetime.timedelta(days=3)).isoformat(),
          f"on the right date, got {week[0]}")


def scenario_a_window_announces_itself_once():
    """The only cue this arc had arrived AFTERWARDS -- the "did it happen?"
    ask, about a session nothing had told anybody to start."""
    _reset()
    now = datetime.datetime.now().replace(hour=19, minute=2, second=0,
                                          microsecond=0)
    _program(day=now.date().weekday())
    due = prog.due_practice_pushes(now)
    check(len(due) == 1, f"a window that just started is due, got {due}")
    check(due[0]['steps'], "and it carries the steps, not just the hour")

    prog.mark_practice_pushed([due[0]['push_key']])
    check(prog.due_practice_pushes(now) == [],
          "and it is announced exactly once, across restarts")


def scenario_a_window_is_not_announced_early_late_or_after_it_was_logged():
    _reset()
    base = datetime.datetime.now().replace(hour=19, minute=0, second=0,
                                           microsecond=0)
    pid, _ = _program(day=base.date().weekday())
    check(prog.due_practice_pushes(base - datetime.timedelta(minutes=5)) == [],
          "nothing fires before the window starts")
    check(prog.due_practice_pushes(base + datetime.timedelta(minutes=45)) == [],
          "and a push that arrives long after the moment it describes is "
          "worse than none")
    prog.log_session(pid, minutes=20, source='added')
    check(prog.due_practice_pushes(base + datetime.timedelta(minutes=2)) == [],
          "and a session already logged is not asked to start")


def scenario_the_feed_carries_programs_and_nothing_else():
    """Commitments that did not come from a program stay exactly as private
    as they were -- the erosion finding in services/watchers.py says somebody's
    own life is nobody else's business, and this does not reopen that."""
    _reset()
    today = datetime.date.today()
    storage.add_protected_commitment({
        'id': 'private1', 'member_id': 'mom', 'title': 'Therapy',
        'days_of_week': list(range(7)), 'time_start': '08:00',
        'time_end': '09:00', 'active': True})
    _program()
    titles = [w['title'] for w in prog.practice_windows(today, today)]
    check(titles == ['Guitar'],
          f"a commitment nobody's program claimed is not published, got {titles}")


def scenario_the_endpoint_is_reachable_by_hand():
    _reset()
    import main
    today = datetime.date.today().isoformat()
    check('/api/practice-windows' in {r.path for r in main.app.routes},
          "the feed has a route")
    _program()
    res = main.practice_windows_api(start_date=today, end_date=today)
    check(len(res['windows']) == 1, f"and it answers, got {res}")


if __name__ == '__main__':
    scenario_an_approved_window_has_a_date_a_time_and_the_session()
    scenario_only_a_live_program_holds_time()
    scenario_a_released_commitment_stops_drawing()
    scenario_the_feed_spans_the_days_it_is_asked_for()
    scenario_a_window_announces_itself_once()
    scenario_a_window_is_not_announced_early_late_or_after_it_was_logged()
    scenario_the_feed_carries_programs_and_nothing_else()
    scenario_the_endpoint_is_reachable_by_hand()
    print("test_practice_windows OK")
