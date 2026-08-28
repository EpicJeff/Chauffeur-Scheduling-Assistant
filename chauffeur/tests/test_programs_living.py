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


def _mk(start_days_ago=21, member_id='lily', target_date='2026-06-14',
       target_event_id='evt-campfire', phases=None):
    start = (datetime.date.today()
             - datetime.timedelta(days=start_days_ago)).isoformat()
    return storage.add_program({
        'member_id': member_id, 'title': 'Guitar', 'state': 'active',
        'shape': {'sessions_per_week': 3, 'minutes': 25,
                  'preferred_days': [1, 3, 5]},
        'baseline': {'start_date': start, 'target_date': target_date,
                     'target_event_id': target_event_id,
                     'rebaselined_at': None, 'rebaselines': 0},
        'phases': phases if phases is not None else
                  [{'name': 'Phase 1', 'weeks': 4, 'what': 'Chords',
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
    """Not just a string search over the row -- a structural guard. If
    `weekday_shortfall` ever cached its answer (a `gap_days` field, say, that
    a name-based banned-key screen and a plain substring search would both
    miss) this fails the moment it tries to write, which is the actual thing
    worth preventing."""
    _reset()
    pid = _mk()
    _log_on(pid, 1)      # Tuesdays happen
    _log_on(pid, 5)      # Saturdays happen
    # Thursdays (weekday 3) never do.
    row = storage.get_program(pid)

    real_update = storage.update_program
    real_append = storage.append_program_session

    def _must_not_write(*a, **kw):
        raise AssertionError("weekday_shortfall must never write to storage")

    storage.update_program = _must_not_write
    storage.append_program_session = _must_not_write
    try:
        short = programs.weekday_shortfall(row)
    finally:
        storage.update_program = real_update
        storage.append_program_session = real_append

    check(short and short['weekday'] == 3,
          f"it can name the day that keeps getting eaten, got {short}")
    blob = str(storage.get_program(pid))
    for word in ('missed', 'shortfall', 'streak'):
        check(word not in blob,
              f"and stored no '{word}' anywhere in the object")


def scenario_rebaseline_never_moves_a_date_the_world_fixed():
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


def scenario_rebaseline_compresses_phases_to_still_fit():
    """The design's rule for a fixed-date program: the target stays and the
    phases give way instead. Two weeks of runway is tight but real, so the
    phases must actually shrink -- and the shrink must actually be the thing
    that got saved, not just what the return value claims."""
    _reset()
    target = (datetime.date.today() + datetime.timedelta(days=20)).isoformat()
    pid = _mk(target_date=target, target_event_id='evt-fixed',
             phases=[{'name': 'Phase 1', 'weeks': 5, 'what': 'Chords',
                      'milestone': 'G to C', 'milestone_hit_at': None},
                     {'name': 'Phase 2', 'weeks': 5, 'what': 'Barre chords',
                      'milestone': 'F major', 'milestone_hit_at': None}])
    _log_on(pid, 1)      # one session a week against a shape of three
    row = storage.get_program(pid)
    out = programs.maybe_rebaseline(row)
    check(out is not None and out['fits'] is True,
          f"two weeks of runway is tight but real -- it must fit, got {out}")
    check(out['phases_changed'] is True,
          f"a real squeeze happened, so the claim of one must be honest, got {out}")
    weeks = [p['weeks'] for p in out['phases']]
    check(sum(weeks) <= 2, f"the phases now fit inside what's left, got {weeks}")
    check(all(w < 5 for w in weeks),
          f"and they were actually shrunk, not left alone, got {weeks}")
    check(all(w >= 1 for w in weeks), f"never compressed below one week, got {weeks}")
    stored = [p['weeks'] for p in storage.get_program(pid)['phases']]
    check(stored == weeks, "the compression is really persisted, not just returned")


def scenario_rebaseline_does_not_claim_a_squeeze_that_never_happened():
    """A fixed-date program that already has slack before its date must not
    be told 'I've tightened the phases' -- nothing was tightened. `fits` says
    it lands fine; `phases_changed` must say honestly that nothing moved."""
    _reset()
    target = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
    pid = _mk(target_date=target, target_event_id='evt-fixed',
             phases=[{'name': 'Phase 1', 'weeks': 2, 'what': 'Chords',
                      'milestone': 'G to C', 'milestone_hit_at': None}])
    _log_on(pid, 1)      # pace shortfall, but plenty of calendar slack
    row = storage.get_program(pid)
    out = programs.maybe_rebaseline(row)
    check(out is not None and out['fits'] is True,
          f"eight weeks of runway against a two-week phase already fits, got {out}")
    check(out['phases_changed'] is False,
          f"nothing needed shrinking, so nothing may claim to have shrunk, got {out}")


def scenario_rebaseline_admits_when_phases_cannot_fit():
    """Three days is not one more week, however hard the phases compress --
    the design's rule is that a plan which lies about fitting is worse than
    one that admits it is tight, so this must leave the phases exactly alone
    and say so rather than fake a fit."""
    _reset()
    target = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    original = [{'name': 'Phase 1', 'weeks': 4, 'what': 'Chords',
                'milestone': 'G to C', 'milestone_hit_at': None}]
    pid = _mk(target_date=target, target_event_id='evt-fixed',
             phases=[dict(p) for p in original])
    _log_on(pid, 1)
    row = storage.get_program(pid)
    out = programs.maybe_rebaseline(row)
    check(out is not None and out['fits'] is False,
          f"three days cannot hold even one more week, got {out}")
    check(out['phases'] == original,
          f"and it must not pretend to make room it doesn't have, got {out['phases']}")
    check(storage.get_program(pid)['phases'] == original,
          "the untouched phases are what actually got saved")


def scenario_rebaseline_stretches_when_nothing_pins_the_date():
    """No event anchors this one -- an undated target is the app's to move,
    same as before this round's fix. Phases are irrelevant here; there is
    nothing to compress because there is nothing fixed to compress against."""
    _reset()
    target = (datetime.date.today() + datetime.timedelta(days=60)).isoformat()
    pid = _mk(target_date=target, target_event_id=None)
    _log_on(pid, 1)
    row = storage.get_program(pid)
    out = programs.maybe_rebaseline(row)
    check(out is not None and out['fits'] is None,
          f"an undated target has nothing to compress against, got {out}")
    after = storage.get_program(pid)['baseline']
    want = (datetime.date.fromisoformat(target) + datetime.timedelta(days=14)).isoformat()
    check(after['target_date'] == want,
          f"so the date itself moves instead, got {after['target_date']}")


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


def scenario_one_bad_program_does_not_silence_the_rest():
    """`due_session_asks` walks every active program in one call -- a single
    member's malformed record must cost only that program's ask, the same
    way the drift/rebaseline loop in watchers.py already guards itself per
    program, never every other family member's practice check for the
    sweep."""
    _reset()
    storage.add_member({'id': 'jack', 'name': 'Jack', 'role': 'child'})
    good_pid = _mk(member_id='lily')
    bad_pid = _mk(member_id='jack')

    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    wd = yesterday.weekday()
    for pid, member in ((good_pid, 'lily'), (bad_pid, 'jack')):
        cid = uuid.uuid4().hex
        storage.add_protected_commitment({
            'id': cid, 'member_id': member, 'title': 'Practice',
            'days_of_week': [wd], 'time_start': '07:00', 'time_end': '07:25',
            'active': True})
        storage.update_program(pid, {'emissions': {'commitment_ids': [cid],
                                                    'thread_ids': [], 'event_ids': []}})

    from services import family_digest
    real = family_digest.in_member_quiet_hours

    def flaky(member, now=None):
        if member.get('id') == 'jack':
            raise RuntimeError('a malformed quiet-hours record, say')
        return real(member, now)

    family_digest.in_member_quiet_hours = flaky
    try:
        due = programs.due_session_asks()
    finally:
        family_digest.in_member_quiet_hours = real
    check(any(d['program']['id'] == good_pid for d in due),
          f"one member's bad record must not silence everyone else's, got {due}")


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
    scenario_rebaseline_never_moves_a_date_the_world_fixed()
    scenario_rebaseline_compresses_phases_to_still_fit()
    scenario_rebaseline_does_not_claim_a_squeeze_that_never_happened()
    scenario_rebaseline_admits_when_phases_cannot_fit()
    scenario_rebaseline_stretches_when_nothing_pins_the_date()
    scenario_rebaseline_does_not_chatter()
    scenario_a_hand_deleted_slot_is_noticed_not_recreated()
    scenario_a_paused_program_asks_nothing()
    scenario_one_bad_program_does_not_silence_the_rest()
    scenario_the_session_ask_tap_actually_logs_a_session()
    print("test_programs_living OK")
