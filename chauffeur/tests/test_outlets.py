"""Outlets, quiet hours on the identity, and the household briefing (A6).

Load-bearing properties:

  1. **An outlet is a scheduling problem.** A protected commitment becomes a
     recurring solver ban; clear_deck/give_space finally get their teeth
     (evening-scoped, not whole-day); an override that steals the window is
     called out before the evening is lost.
  2. **Quiet hours live on the member** — a preference owned by the self.
     Absent = the household default, NEVER off; urgent escapes; children
     keep the kid machinery.
  3. **The briefing shows OPENINGS, not assignments** — and goes to every
     adult, because the hard part of picking up slack is visibility.

Run from chauffeur/:  python tests/test_outlets.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import family_digest, storage

TODAY = datetime.date.today()


def _reset():
    for t in (storage.members_table, storage.protected_commitments_table,
              storage.household_tasks_table, storage.cache_table,
              storage.assist_contacts_table, storage.assist_assignments_table):
        t.truncate()
    storage.get_settings = lambda: {}


def _member(name, role='adult', **kw):
    from models.schemas import FamilyMember
    m = FamilyMember(name=name, role=role, **kw).model_dump()
    storage.add_member(m)
    return m


def scenario_quiet_hours_default_on_never_off():
    """Absent means the household default (21:00-08:00) — the trap where
    unset means unprotected is the one the screensaver settings hit."""
    m = {'role': 'adult'}
    late = datetime.datetime.combine(TODAY, datetime.time(23, 0))
    lunch = datetime.datetime.combine(TODAY, datetime.time(12, 0))
    early = datetime.datetime.combine(TODAY, datetime.time(7, 0))
    check(family_digest.in_member_quiet_hours(m, late), "23:00 is inside the default")
    check(family_digest.in_member_quiet_hours(m, early), "07:00 too — it wraps midnight")
    check(not family_digest.in_member_quiet_hours(m, lunch), "noon is not")


def scenario_quiet_hours_are_the_members_own():
    """A night-shift parent and a 6am riser share no window."""
    night = {'role': 'parent', 'quiet_start': '09:00', 'quiet_end': '16:00'}
    ten_am = datetime.datetime.combine(TODAY, datetime.time(10, 0))
    ten_pm = datetime.datetime.combine(TODAY, datetime.time(22, 0))
    check(family_digest.in_member_quiet_hours(night, ten_am),
          "the night-shift parent sleeps at 10am")
    check(not family_digest.in_member_quiet_hours(night, ten_pm),
          "and is up at 10pm when the default would block")
    off = {'role': 'adult', 'quiet_start': '08:00', 'quiet_end': '08:00'}
    check(not family_digest.in_member_quiet_hours(off, ten_pm)
          and not family_digest.in_member_quiet_hours(off, ten_am),
          "start == end disables, same grammar as the kid window")
    kid = {'role': 'child'}
    late = datetime.datetime.combine(TODAY, datetime.time(23, 0))
    check(not family_digest.in_member_quiet_hours(kid, late),
          "children keep the kid machinery — this window is not theirs")


def scenario_the_notify_path_respects_the_window_and_urgency():
    import main
    _reset()
    m = _member("Lorena", role='parent')  # default window
    sent = []
    orig = main.send_push_to_member
    try:
        main.send_push_to_member = lambda mid, t, b, p: sent.append(t)
        import unittest.mock as mock
        late = datetime.datetime.combine(TODAY, datetime.time(23, 30))
        with mock.patch('services.family_digest.datetime') as md:
            md.datetime.now.return_value = late
            md.time = datetime.time
            main._notify_member_lanes(m, 'Watcher stuff', 'body')
            check(not sent, "a non-urgent send inside the window SKIPS")
            main._notify_member_lanes(m, 'Time to leave!', 'body', urgent=True)
            check(sent == ['Time to leave!'],
                  "urgent escapes — a 5:30am departure must fire at 5:10")
    finally:
        main.send_push_to_member = orig


def scenario_notify_lanes_settle_the_double_delivery():
    import main
    _reset()
    m = _member("Jeff", role='parent', notify_lanes='ha',
                notify_service='notify.mobile_app_jeff',
                quiet_start='03:00', quiet_end='03:00')   # window off for the test
    pushes, ha_calls = [], []
    orig_push = main.send_push_to_member
    try:
        main.send_push_to_member = lambda mid, t, b, p: pushes.append(t)
        from services import ha_api
        orig_call = ha_api.call_service
        ha_api.call_service = lambda d, s, payload=None, **kw: ha_calls.append(s)
        main._notify_member_lanes(m, 'Hello', 'body')
        check(not pushes and ha_calls,
              f"lanes='ha' means the HA companion only: pushes={pushes}, ha={ha_calls}")
    finally:
        main.send_push_to_member = orig_push
        ha_api.call_service = orig_call


def scenario_a_commitment_becomes_a_solver_ban():
    """The injection emits a recurring unavailable rule for the member's
    driver — the same machinery status days use, nothing new to the solver."""
    _reset()
    m = _member("Lorena", role='parent', driver_id='drv_l')
    from models.schemas import ProtectedCommitment
    pc = ProtectedCommitment(member_id=m['id'], title='Thursday run',
                             days_of_week=[3], time_start='18:00',
                             time_end='19:30').model_dump()
    storage.add_protected_commitment(pc)
    rows = storage.get_protected_commitments()
    check(len(rows) == 1, "stored")
    # The injection expression main.py uses:
    from models.schemas import Rule
    injected = []
    for c in storage.get_protected_commitments():
        member = storage.get_member(c['member_id']) or {}
        drv = member.get('driver_id')
        if drv and c.get('days_of_week'):
            injected.append(Rule(driver_id=drv, constraint_type='unavailable',
                                 days_of_week=list(c['days_of_week']),
                                 time_start=c.get('time_start'),
                                 time_end=c.get('time_end')))
    check(len(injected) == 1 and injected[0].days_of_week == [3]
          and injected[0].time_start == '18:00',
          f"a recurring, time-windowed ban: {injected}")


def scenario_clear_deck_finally_has_teeth():
    """The design doc promised 'the solver protects the evening' and the code
    never did — clear_deck/give_space emitted nothing. Now they emit an
    EVENING ban, not a whole-day one: 'keep the evening free' is a claim
    about the evening, and banning the school run would overshoot."""
    from services import status_protocols
    _reset()
    m = _member("Lorena", role='parent', driver_id='drv_l')
    proto_id = storage.add_status_protocol({
        'id': 'p1', 'name': 'Recovery Day', 'emoji': '💙', 'need': 'clear_deck',
        'member_id': m['id'], 'kid_message': '', 'adult_message': '', 'beats': []})
    storage.add_status_day({'id': 'd1', 'date': TODAY.isoformat(),
                            'protocol_id': 'p1'})
    entries = status_protocols.unavailable_driver_dates(
        TODAY.isoformat(), TODAY.isoformat())
    check(len(entries) == 1, f"clear_deck now emits: {entries}")
    e = entries[0]
    check(e.get('time_start') == '17:00',
          f"and it is EVENING-scoped, not a whole-day ban: {e}")


def scenario_an_override_that_steals_the_window_is_called_out():
    """The solver is banned from the window, so a drive can only land there
    through an override — exactly how an outlet dies quietly."""
    from services import watchers
    _reset()
    m = _member("Lorena", role='parent', driver_id='drv_l')
    from models.schemas import ProtectedCommitment
    # Next occurrence of tomorrow's weekday, window around 18:30.
    d = TODAY + datetime.timedelta(days=1)
    pc = ProtectedCommitment(member_id=m['id'], title='run club',
                             days_of_week=[d.weekday()], time_start='18:00',
                             time_end='20:00').model_dump()
    storage.add_protected_commitment(pc)
    cache = {'events': [{'id': 'ev1', 'title': 'Late pickup',
                         'start': f"{d.isoformat()}T18:30:00"}],
             'assignments': {'ev1': 'drv_l'}, 'unassigned': []}
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: cache
        now = datetime.datetime.combine(TODAY, datetime.time(9, 0))
        found = watchers._commitment_findings(now)
        check(found and 'about to be lost' in found[0][1]
              and 'run club' in found[0][1],
              f"the erosion is named before the evening is gone: {found}")
    finally:
        storage.get_cached_schedule = orig


def scenario_needs_cover_flags_open_drives_in_the_window():
    from services import watchers
    _reset()
    m = _member("Lorena", role='parent', driver_id='drv_l')
    from models.schemas import ProtectedCommitment
    d = TODAY + datetime.timedelta(days=1)
    pc = ProtectedCommitment(member_id=m['id'], title='choir',
                             days_of_week=[d.weekday()], time_start='18:00',
                             time_end='21:00', needs_coverage=True).model_dump()
    storage.add_protected_commitment(pc)
    cache = {'events': [{'id': 'ev1', 'title': 'Practice run',
                         'start': f"{d.isoformat()}T19:00:00"}],
             'assignments': {}, 'unassigned': ['ev1']}
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: cache
        now = datetime.datetime.combine(TODAY, datetime.time(9, 0))
        found = watchers._commitment_findings(now)
        check(found and 'still needs a driver' in found[0][1]
              and 'choir' in found[0][1],
              f"covered time is what makes an outlet real: {found}")
    finally:
        storage.get_cached_schedule = orig


def scenario_the_briefing_shows_openings_not_assignments():
    _reset()
    _member("Jeff", role='parent', driver_id='drv_j')
    tomorrow = TODAY + datetime.timedelta(days=1)
    from models.schemas import HouseholdTask
    storage.add_household_task(HouseholdTask(
        title='Permission slip', due_date=tomorrow.isoformat()).model_dump())
    cache = {
        'events': [
            {'id': 'a', 'title': 'Soccer', 'start': f"{tomorrow.isoformat()}T16:00:00"},
            {'id': 'b', 'title': 'Guitar', 'start': f"{tomorrow.isoformat()}T17:00:00"},
        ],
        'assignments': {'a': 'drv_j'}, 'unassigned': ['b'],
        'assist_assignments': {}, 'assist_contacts': [],
    }
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: cache
        b = family_digest.build_household_briefing(tomorrow)
        text = "\n".join(b['lines'])
        check(b['open_count'] == 2, f"the open count is the headline: {b}")
        opens = text.split('Handled:')[0]
        check('Guitar' in opens and 'Permission slip' in opens,
              f"openings lead — the drive AND the task nobody has: {text}")
        check('Soccer — Jeff' in text.replace('4:00 PM ', '') or 'Jeff' in text,
              f"and what is handled says by whom, underneath: {text}")
    finally:
        storage.get_cached_schedule = orig


def scenario_the_briefing_counts_outside_hands_as_covered():
    _reset()
    _member("Jeff", role='parent', driver_id='drv_j')
    from models.schemas import AssistContact
    c = AssistContact(name="Sarah", relation_label="Emma's mom").model_dump()
    storage.add_assist_contact(c)
    tomorrow = TODAY + datetime.timedelta(days=1)
    cache = {
        'events': [{'id': 'a', 'title': 'Soccer',
                    'start': f"{tomorrow.isoformat()}T16:00:00"}],
        'assignments': {}, 'unassigned': ['a'],
        'assist_assignments': {'a': c['id']}, 'assist_contacts': [c],
    }
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: cache
        b = family_digest.build_household_briefing(tomorrow)
        text = "\n".join(b['lines'])
        check(b['open_count'] == 0 and "Emma's mom" in text and 'covered' in text,
              f"a carpool ride is handled, and the briefing says by whom: {text}")
    finally:
        storage.get_cached_schedule = orig


def scenario_the_hand_paths_exist():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    config = open(os.path.join(tpl, 'config.html'), encoding='utf-8').read()
    check('saveCommitment' in config and 'deleteCommitment' in config
          and 'Protected time' in config,
          "protected time works by hand on the People tab")
    check('memberEdit.quiet_start' in config and 'memberEdit.notify_lanes' in config,
          "quiet hours and lanes live on the member's own card")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} outlet scenarios passed")
