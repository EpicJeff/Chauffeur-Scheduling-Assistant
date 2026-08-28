"""What happens to a program after the week gets hold of it.

The design's hardest constraint lives here: the app must be able to say
'Wednesdays keep getting eaten' without ever storing a miss.
"""
import datetime
import time
import uuid

from harness import check
from services import chat_actions, programs, storage, watchers


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


_WEEKDAY_NAMES = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                  'Saturday', 'Sunday')


def scenario_rebaseline_admits_when_phases_cannot_fit():
    """Three days is not one more week, however hard the phases compress --
    the design's rule is that a plan which lies about fitting is worse than
    one that admits it is tight, so this must leave the phases exactly alone
    and say so rather than fake a fit.

    And the finding's own sentence must not slip back into claiming a
    squeeze that never happened -- checked against the absence of the false
    claim, not just the presence of the honest half, because a message test
    that only greps for a true phrase survives a rewrite that reintroduces
    the false one right next to it."""
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
    day = watchers._eaten_days(out)
    line = watchers._rebaseline_line(row.get('title'), day, out).lower()
    check('tight against the date' in line, f"the honest half survives, got {line}")
    check('as short as they can go' not in line
          and 'shortened' not in line and 'shorter' not in line,
          f"and it must not claim a squeeze that never happened, got {line}")


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
    check(out is not None and out['fits'] is None and out['date_moved'] is True,
          f"an undated target has nothing to compress against, but the date "
          f"really moves, got {out}")
    after = storage.get_program(pid)['baseline']
    want = (datetime.date.fromisoformat(target) + datetime.timedelta(days=14)).isoformat()
    check(after['target_date'] == want,
          f"so the date itself moves instead, got {after['target_date']}")


def scenario_an_event_with_no_date_claims_no_room_was_made():
    """Latent edge case: malformed baseline data (an event id with no date --
    the schema always populates both together, so this should never happen
    in practice) must not read as 'I gave the plan more room'. That sentence
    is only true when a date actually moved, and the stretch path never runs
    without a `target_date` to move -- so `date_moved` must come back False
    and the finding must not claim otherwise."""
    _reset()
    pid = _mk(target_date=None, target_event_id='evt-fixed')
    _log_on(pid, 1)
    row = storage.get_program(pid)
    out = programs.maybe_rebaseline(row)
    check(out is not None and out['fits'] is None and out['date_moved'] is False,
          f"nothing to compress against and nothing to stretch, got {out}")
    day = watchers._eaten_days(out)
    line = watchers._rebaseline_line(row.get('title'), day, out).lower()
    check('more room' not in line,
          f"nothing moved, so nothing may claim room was made, got {line}")


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


def _elapsed_slot(pid, member_id='lily'):
    """A claimed practice window that ended yesterday morning, so the grace
    period has certainly passed whatever time of day this test runs."""
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    cid = uuid.uuid4().hex
    storage.add_protected_commitment({
        'id': cid, 'member_id': member_id, 'title': 'Guitar',
        'days_of_week': [yesterday.weekday()], 'time_start': '07:00',
        'time_end': '07:25', 'active': True})
    storage.update_program(pid, {'emissions': {'commitment_ids': [cid],
                                               'thread_ids': [], 'event_ids': []}})
    return cid, yesterday


def scenario_the_session_ask_never_reaches_a_parent():
    """The one place in this arc where the app could claim more than
    happened. `program_session` was a `dm=True` finding, `run_watchers` DMs
    PARENTS only, `/api/findings` is parent/adult gated and the "Yes, it
    happened" card is admin gated -- so both parents were asked whether a
    kid's guitar session happened and either could tap yes for something
    nobody witnessed. The question belongs to the person whose program it is,
    so it is no longer a finding at all."""
    _reset()
    pid = _mk()
    _elapsed_slot(pid)
    due = programs.due_session_asks()
    check(any(d['program']['id'] == pid for d in due),
          f"the slot really is unanswered, got {due}")
    found = watchers._program_findings(datetime.datetime.now())
    check(not [f for f in found if f.kind == 'program_session'],
          f"and nothing asks a parent about it, got {[f.kind for f in found]}")
    for f in found:
        act = (f.action or {}).get('action_type')
        check(act != 'log_program_session',
              f"no parent-tappable card confirms a session they did not see, got {f}")


def scenario_the_ask_rides_the_owners_own_surface():
    """Where the question went instead: `GET /api/programs` carries the
    pending ask, so the PWA card the owner already fetches can prompt them --
    and answering with the slot's own date files the session under the
    evening it was about, not the morning they got round to tapping."""
    _reset()
    import main
    pid = _mk()
    cid, slot_day = _elapsed_slot(pid)
    res = main.list_programs_api(member_id='lily')
    ask = res['programs'][0].get('due_ask')
    check(ask and ask['slot_date'] == slot_day.isoformat(),
          f"the owner's own list carries the question, got {ask}")
    check(slot_day.strftime('%A') in ask['body'],
          f"naming the evening it is about, got {ask}")

    programs.log_session(pid, source='asked', slot_date=ask['slot_date'])
    logged = programs.sessions_between(storage.get_program(pid), slot_day, slot_day)
    check(len(logged) == 1,
          f"the answer lands on THAT day, got {storage.get_program(pid)['sessions']}")
    after = main.list_programs_api(member_id='lily')['programs'][0].get('due_ask')
    check(after is None, f"and the prompt clears, got {after}")


def scenario_an_evening_the_family_gave_up_is_never_asked_about():
    """Cross-arc: negotiation's `lift_protected` records a protected
    exception for ONE date -- an evening the family agreed to spend
    elsewhere, not one anybody failed to practise on. Asking "did it happen?"
    about it is the app forgetting a deal it brokered itself."""
    _reset()
    pid = _mk()
    cid, slot_day = _elapsed_slot(pid)
    storage.add_protected_exception(cid, slot_day.isoformat())
    due = [d for d in programs.due_session_asks() if d['program']['id'] == pid]
    check(due == [], f"a lifted evening asks nothing, got {due}")


def scenario_a_deactivated_window_is_not_a_deleted_one():
    """`orphaned_emissions` compared against `get_protected_commitments()`,
    whose default hides `active: False` -- so switching a window off for a
    fortnight looked exactly like deleting it: the drift finding fired and
    the id was forgotten for good, which meant switching it back on could
    never re-link."""
    _reset()
    pid = _mk()
    cid, _ = _elapsed_slot(pid)
    storage.update_protected_commitment(cid, {'active': False})
    row = storage.get_program(pid)
    check(programs.orphaned_emissions(row) == [],
          "deactivating is not deleting")
    storage.delete_protected_commitment(cid)
    check(programs.orphaned_emissions(storage.get_program(pid)) == [cid],
          "deleting still is")


def scenario_the_drift_finding_carries_an_offer_the_app_can_perform():
    """It asked "want it back, or shall I re-shape the week?" with no action
    attached and no endpoint that could re-emit -- `approve()` demands
    `proposed` -- while `forget_emissions` erased the ids, so even a
    hand-restored commitment could never re-link. The program became an
    active zombie that still re-baselined every fortnight."""
    _reset()
    storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'parent'})
    pid = _mk()
    cid, _ = _elapsed_slot(pid)
    storage.delete_protected_commitment(cid)
    found = [f for f in watchers._program_findings(datetime.datetime.now())
             if f.kind == 'program_drift' and f.subject_id == pid]
    check(len(found) == 1, f"the drift is noticed once, got {found}")
    act = found[0].action
    check(act and act['action_type'] == 'reshape_program',
          f"and it carries its solution, got {act}")

    prop = chat_actions.create_action_proposal(
        act['action_type'], act['label'], act['payload'])
    check(prop['status'] == 'success', f"a real proposable action, got {prop}")
    res = chat_actions.act_on_proposal(prop['proposal_id'], 'approve',
                                       storage.get_member('dad'))
    check(res['status'] == 'success', f"the tap really executes, got {res}")
    check(storage.get_program(pid)['state'] == 'proposed',
          "and the program can be approved again, which is the offer it made")
    check(storage.get_protected_commitments(member_id='lily') == [],
          "nothing was silently re-created -- a person still taps the footprint")


def scenario_the_last_milestone_finishes_the_program():
    """Nothing anywhere set a program `done`: `mark_milestone` stamped a hit
    date and stopped, and the archive's "Done" half could never populate. A
    finished program kept its weekly commitments and kept asking forever, and
    the only exit read "Dropped. The time is back."""
    _reset()
    pid = _mk(phases=[{'name': 'Phase 1', 'weeks': 4, 'what': 'Chords',
                       'milestone': 'G to C', 'milestone_hit_at': None},
                      {'name': 'Phase 2', 'weeks': 4, 'what': 'Songs',
                       'milestone': 'A whole song', 'milestone_hit_at': None}])
    _elapsed_slot(pid)
    programs.mark_milestone(pid, 'Phase 1')
    check(storage.get_program(pid)['state'] == 'active',
          "one of two is not the end")
    res = programs.mark_milestone(pid, 'Phase 2')
    check(res['status'] == 'success' and res.get('schedule_dirty'),
          f"the last one finishes it, got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'done' and row.get('finished_at'),
          f"reaching the end is not the same as abandoning it, got {row['state']}")
    check(storage.get_protected_commitments(member_id='lily') == [],
          "and the practice time really goes back")
    check(programs.due_session_asks() == [],
          "a finished program stops asking whether it happened")


def scenario_a_person_can_say_it_is_finished():
    """The other half of done -- the design says done is the last milestone
    OR a person saying so, and only the first was ever built."""
    _reset()
    pid = _mk()
    _elapsed_slot(pid)
    res = programs.finish(pid)
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_program(pid)
    check(row['state'] == 'done' and row.get('finished_at'), f"got {row['state']}")
    check(storage.get_protected_commitments(member_id='lily') == [],
          "the evenings go back, same as dropping -- what differs is the record")


def scenario_an_undated_program_really_stretches():
    """The common program has no `target_date` -- it is the default from the
    chat tool and from the page unless somebody types one. Re-baselining
    incremented a counter, burned the fortnight cooldown, touched neither
    phases nor dates, and still posted "want to try a different day?"""
    _reset()
    pid = _mk(target_date=None, target_event_id=None)
    _log_on(pid, 1)
    row = storage.get_program(pid)
    before = [p['weeks'] for p in row['phases']]
    out = programs.maybe_rebaseline(row)
    check(out is not None, f"it still fires, got {out}")
    after = [p['weeks'] for p in storage.get_program(pid)['phases']]
    check(all(a > b for a, b in zip(after, before)),
          f"and the timeline actually stretches, {before} -> {after}")
    check(out.get('stretched') is True, f"and says so honestly, got {out}")
    line = watchers._rebaseline_line('Guitar', watchers._eaten_days(out), out)
    check('more room' in line, f"which the sentence may then claim, got {line}")


def scenario_a_tied_shortfall_names_no_single_day():
    """With nothing logged, every preferred day is equally empty and the
    strict `>` always named the first -- so a program with Mon/Wed/Fri and an
    empty log said "Mondays keep getting eaten" about three identical days.
    The whole value of that sentence is naming the right one."""
    _reset()
    pid = storage.add_program({
        'member_id': 'lily', 'title': 'Guitar', 'state': 'active',
        'shape': {'sessions_per_week': 3, 'minutes': 25,
                  'preferred_days': [0, 2, 4]},
        'baseline': {'start_date': (datetime.date.today()
                                    - datetime.timedelta(days=21)).isoformat(),
                     'target_date': None, 'target_event_id': None,
                     'rebaselined_at': None, 'rebaselines': 0},
        'phases': [{'name': 'Phase 1', 'weeks': 4, 'what': 'Chords',
                    'milestone': 'G to C', 'milestone_hit_at': None}]})
    short = programs.weekday_shortfall(storage.get_program(pid))
    check(short and short['weekday'] is None,
          f"a tie names nobody, got {short}")
    check(short['weekdays'] == [0, 2, 4], f"got {short}")
    out = programs.maybe_rebaseline(storage.get_program(pid))
    line = watchers._rebaseline_line('Guitar', watchers._eaten_days(out), out)
    check(line.startswith('🎸 Guitar: These days keep getting eaten'),
          f"it says 'these days' rather than guessing, got {line}")
    for name in _WEEKDAY_NAMES:
        check(name not in line, f"and names no weekday at all, got {line}")


def scenario_programs_off_means_off():
    """`programs_enabled` gated only the sweep, so with it off a household
    could still propose a program, spend a research run and claim the week.
    A setting named for a feature governs the feature."""
    _reset()
    import main
    # tests/harness.py stubs `get_settings` outright, so the switch is flipped
    # by swapping that stub rather than by writing a row nothing reads.
    real = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'programs_enabled': False}
    try:
        res = main.create_program(body={'member_id': 'lily', 'title': 'learn guitar',
                                        'for_member_id': 'lily'}, request=None)
        check(res.get('status') == 'error', f"proposing is refused, got {res}")
        check(storage.get_programs(include_finished=True) == [],
              "and nothing was created")
        pid = _mk()
        _elapsed_slot(pid)
        check(programs.due_asks_for(storage.get_program(pid)) == [],
              "and no question is asked either")
    finally:
        storage.get_settings = real


if __name__ == '__main__':
    scenario_the_shortfall_is_derived_and_never_stored()
    scenario_rebaseline_never_moves_a_date_the_world_fixed()
    scenario_rebaseline_compresses_phases_to_still_fit()
    scenario_rebaseline_does_not_claim_a_squeeze_that_never_happened()
    scenario_rebaseline_admits_when_phases_cannot_fit()
    scenario_rebaseline_stretches_when_nothing_pins_the_date()
    scenario_an_event_with_no_date_claims_no_room_was_made()
    scenario_rebaseline_does_not_chatter()
    scenario_a_hand_deleted_slot_is_noticed_not_recreated()
    scenario_a_paused_program_asks_nothing()
    scenario_one_bad_program_does_not_silence_the_rest()
    scenario_the_session_ask_tap_actually_logs_a_session()
    scenario_the_session_ask_never_reaches_a_parent()
    scenario_the_ask_rides_the_owners_own_surface()
    scenario_an_evening_the_family_gave_up_is_never_asked_about()
    scenario_a_deactivated_window_is_not_a_deleted_one()
    scenario_the_drift_finding_carries_an_offer_the_app_can_perform()
    scenario_the_last_milestone_finishes_the_program()
    scenario_a_person_can_say_it_is_finished()
    scenario_an_undated_program_really_stretches()
    scenario_a_tied_shortfall_names_no_single_day()
    scenario_programs_off_means_off()
    print("test_programs_living OK")
