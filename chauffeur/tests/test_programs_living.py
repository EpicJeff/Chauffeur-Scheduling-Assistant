"""What happens to a program after the week gets hold of it.

The design's hardest constraint lives here: the app must be able to say
'Wednesdays keep getting eaten' without ever storing a miss.
"""
import datetime
import time
import uuid

from harness import check
from services import chat_actions, programs, storage


def _reset():
    storage.programs_table.truncate()
    storage.protected_commitments_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'lily', 'name': 'Lily', 'role': 'child'})


def _mk(start_days_ago=21):
    start = (datetime.date.today()
             - datetime.timedelta(days=start_days_ago)).isoformat()
    return storage.add_program({
        'member_id': 'lily', 'title': 'Guitar', 'state': 'active',
        'shape': {'sessions_per_week': 3, 'minutes': 25,
                  'preferred_days': [1, 3, 5]},
        'baseline': {'start_date': start, 'target_date': '2026-06-14',
                     'target_event_id': 'evt-campfire',
                     'rebaselined_at': None, 'rebaselines': 0},
        'phases': [{'name': 'Phase 1', 'weeks': 4, 'what': 'Chords',
                    'milestone': 'G to C', 'milestone_hit_at': None}]})


def _log_on(pid, weekday, weeks=3):
    """Log a session on a given weekday for each of the last `weeks` weeks."""
    today = datetime.date.today()
    for w in range(weeks):
        d = today - datetime.timedelta(days=today.weekday() - weekday + 7 * w)
        if d > today:
            d -= datetime.timedelta(days=7)
        ts = time.mktime(datetime.datetime(d.year, d.month, d.day, 19).timetuple())
        storage.append_program_session(pid, {'ts': ts, 'minutes': 25,
                                             'source': 'asked'})


def scenario_the_shortfall_is_derived_and_never_stored():
    _reset()
    pid = _mk()
    _log_on(pid, 1)      # Tuesdays happen
    _log_on(pid, 5)      # Saturdays happen
    # Thursdays (weekday 3) never do.
    row = storage.get_program(pid)
    short = programs.weekday_shortfall(row)
    check(short and short['weekday'] == 3,
          f"it can name the day that keeps getting eaten, got {short}")
    blob = str(row)
    for word in ('missed', 'shortfall', 'streak'):
        check(word not in blob,
              f"and stored no '{word}' anywhere in the object")


def scenario_rebaseline_stretches_but_never_moves_a_real_date():
    _reset()
    pid = _mk()
    _log_on(pid, 1)      # one session a week against a shape of three
    row = storage.get_program(pid)
    before = dict(row['baseline'])
    out = programs.maybe_rebaseline(row)
    after = storage.get_program(pid)['baseline']
    check(out is not None, "a persistent shortfall re-baselines")
    check(after['rebaselines'] == before['rebaselines'] + 1, f"got {after}")
    check(after['target_date'] == before['target_date'],
          "a date the world fixed is not the app's to move")
    check(after['target_event_id'] == 'evt-campfire', "and its event is untouched")


def scenario_rebaseline_does_not_chatter():
    _reset()
    pid = _mk()
    _log_on(pid, 1)
    programs.maybe_rebaseline(storage.get_program(pid))
    second = programs.maybe_rebaseline(storage.get_program(pid))
    check(second is None, "it will not re-baseline twice in a fortnight")


def scenario_a_hand_deleted_slot_is_noticed_not_recreated():
    _reset()
    pid = _mk()
    cid = storage.add_protected_commitment({
        'id': uuid.uuid4().hex,
        'member_id': 'lily', 'title': 'Guitar', 'days_of_week': [1],
        'time_start': '19:00', 'time_end': '19:25'})
    storage.update_program(pid, {'emissions': {'commitment_ids': [cid],
                                               'thread_ids': [], 'event_ids': []}})
    storage.delete_protected_commitment(cid)
    gone = programs.orphaned_emissions(storage.get_program(pid))
    check(gone == [cid], f"the program notices, got {gone}")
    still = [c['id'] for c in storage.get_protected_commitments()]
    check(cid not in still,
          "and never silently puts it back — that is how people stop trusting an app")


def scenario_a_paused_program_asks_nothing():
    _reset()
    pid = _mk()
    storage.add_protected_commitment({
        'id': uuid.uuid4().hex,
        'member_id': 'lily', 'title': 'Guitar', 'days_of_week': list(range(7)),
        'time_start': '07:00', 'time_end': '07:25'})
    programs.pause(pid)
    due = [d for d in programs.due_session_asks() if d['program']['id'] == pid]
    check(due == [], f"a paused program is silent, got {due}")


def scenario_the_session_ask_tap_actually_logs_a_session():
    """A finding that offers a tap which errors is a fake door. The session-ask
    finding's action carries `action_type: 'log_program_session'` -- this
    proves that type is a real, registered action whose approval really
    reaches `programs.log_session`, not just that the finding exists."""
    _reset()
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    pid = _mk()
    before = programs.progress(storage.get_program(pid))['sessions']
    prop = chat_actions.create_action_proposal(
        'log_program_session', 'Guitar: did it happen?',
        {'program_id': pid})
    check(prop['status'] == 'success',
          f"the finding's action_type is a real proposable action, got {prop}")
    res = chat_actions.act_on_proposal(prop['proposal_id'], 'approve',
                                       storage.get_member('dad'))
    check(res['status'] == 'success', f"the tap actually executes, got {res}")
    after = programs.progress(storage.get_program(pid))['sessions']
    check(after == before + 1,
          f"and a real session lands on the program, got {before} -> {after}")


if __name__ == '__main__':
    scenario_the_shortfall_is_derived_and_never_stored()
    scenario_rebaseline_stretches_but_never_moves_a_real_date()
    scenario_rebaseline_does_not_chatter()
    scenario_a_hand_deleted_slot_is_noticed_not_recreated()
    scenario_a_paused_program_asks_nothing()
    scenario_the_session_ask_tap_actually_logs_a_session()
    print("test_programs_living OK")
