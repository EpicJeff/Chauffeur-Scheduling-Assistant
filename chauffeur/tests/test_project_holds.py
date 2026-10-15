"""Calendar holds for a person's step (Projects core spec §2 "On the calendar"),
Task 9.

  * `projects.find_window(member_id, minutes, by_date, now=None)` -> {date,
    start, end} | None: interval-based (not equal start times) over the member's
    schedule events (assigned to them as driver), their program practice windows
    and their other confirmed holds, between 08:00 and 21:00, from `now` to
    `by_date`, in 30-minute steps; None when nothing fits;
  * `projects.confirm_hold(project_id, step_id, hold, actor)` re-checks the
    window is free and stores it dated on the step (`hold`: date, start, end,
    confirmed_by); `clear_hold(...)` removes it; a child holds only their own
    steps; an Argyle step has no hold;
  * `projects.calendar_holds(start, end, viewer)` -> entries {date, start, end,
    member_id, title}: the step title for a viewer who can see the project,
    "Busy" for anyone else and for viewer None (the wall, speakers, the shared
    schedule, the Mind); a household project's title for everyone; holds outside
    the range (past ones) are not there;
  * `projects.driver_hold_rules(start, end)` -> one date-scoped
    Rule(constraint_type='unavailable', start_date=end_date=<date>) per hold of
    a member who drives; none for a non-driver; the matcher honours the date;
  * routes: POST /api/projects/{id}/steps/{step_id}/hold (main.project_step_hold:
    an empty body suggests a window, {date,start,end} confirms) and
    POST .../hold/clear (main.project_step_hold_clear).

Run from chauffeur/:  python tests/test_project_holds.py
"""
import datetime

from harness import check  # noqa: F401
from services import storage
from test_projects import _fresh, _p, _make
from test_subjects import MOM, DAD, AUNT, KID
from test_subject_audience import _as

DAY = '2027-03-06'          # a Saturday
NOW = datetime.datetime(2027, 3, 6, 7, 0)


def _setup():
    _fresh()
    storage.update_member('dad', {'driver_id': 'd_dad'})
    storage.set_cached_schedule({'events': [{'id': 'e9', 'title': 'Soccer', 'start': f'{DAY}T09:15:00',
                                             'end': f'{DAY}T10:30:00', 'location': 'Field 3'}],
                                 'assignments': {'e9': 'd_dad'}, 'unassigned': []})
    house = _make('mom', MOM, audience='household', title='Bathroom')
    tile = _p().add_step(house['id'], {'title': 'Tile the floor', 'owner': 'dad'}, dict(MOM))['step']
    paint = _p().add_step(house['id'], {'title': 'Paint the ceiling', 'owner': 'dad'}, dict(MOM))['step']
    return house, tile, paint


def scenario_the_finder_avoids_overlaps_and_says_when_nothing_fits():
    house, tile, paint = _setup()
    res = _p().confirm_hold(house['id'], paint['id'], {'date': DAY, 'start': '08:00', 'end': '09:00'}, dict(MOM))
    check(res['status'] == 'success', f"an earlier hold: {res}")
    w = _p().find_window('dad', 60, DAY, now=NOW)
    check(w == {'date': DAY, 'start': '10:30', 'end': '11:30'},
          f"not on the 8-9 hold, not overlapping soccer 9:15-10:30 (a 9:00 start would overlap): {w}")
    late = datetime.datetime(2027, 3, 6, 20, 30)
    check(_p().find_window('dad', 60, DAY, now=late) is None, "nothing fits before the due date: None")


def scenario_confirming_rechecks_and_stores_a_dated_hold():
    house, tile, paint = _setup()
    taken = _p().confirm_hold(house['id'], tile['id'], {'date': DAY, 'start': '09:00', 'end': '10:00'}, dict(MOM))
    check(taken['status'] == 'error', f"a window that overlaps soccer is refused: {taken}")
    ok = _p().confirm_hold(house['id'], tile['id'], {'date': DAY, 'start': '13:00', 'end': '16:00'}, dict(MOM))
    check(ok['status'] == 'success', f"confirmed: {ok}")
    hold = next(s for s in storage.get_project(house['id'])['steps'] if s['id'] == tile['id'])['hold']
    check(hold['date'] == DAY and hold['start'] == '13:00' and hold['end'] == '16:00' and hold['confirmed_by'] == 'mom',
          f"stored on the step: {hold}")
    check(_p().clear_hold(house['id'], tile['id'], dict(MOM))['status'] == 'success'
          and next(s for s in storage.get_project(house['id'])['steps'] if s['id'] == tile['id'])['hold'] is None, "cleared")
    kids = _make('kid', MOM, title='Learn to ride a bike')
    mine = _p().add_step(kids['id'], {'title': 'Practise', 'owner': 'kid'}, dict(MOM))['step']
    moms = _p().add_step(kids['id'], {'title': 'Buy a helmet', 'owner': 'mom'}, dict(MOM))['step']
    check(_p().confirm_hold(kids['id'], moms['id'], {'date': DAY, 'start': '13:00', 'end': '14:00'}, dict(KID))['status'] == 'error',
          "a child holds only their own steps")
    check(_p().confirm_hold(kids['id'], mine['id'], {'date': DAY, 'start': '13:00', 'end': '14:00'}, dict(KID))['status'] == 'success',
          "their own, yes")
    argyle = _p().add_step(house['id'], {'title': 'Find tile', 'owner': 'argyle', 'goal': 'three tiles'}, dict(MOM))['step']
    check(_p().confirm_hold(house['id'], argyle['id'], {'date': DAY, 'start': '13:00', 'end': '14:00'}, dict(MOM))['status'] == 'error',
          "an Argyle step has no hold")


def scenario_who_sees_what_on_the_calendar():
    _fresh()
    private = _make('mom', MOM, title='Get down to 185 lbs')
    walk = _p().add_step(private['id'], {'title': 'Long walk', 'owner': 'mom'}, dict(MOM))['step']
    _p().confirm_hold(private['id'], walk['id'], {'date': DAY, 'start': '08:00', 'end': '09:00'}, dict(MOM))
    house = _make('mom', MOM, audience='household', title='Garage')
    sweep = _p().add_step(house['id'], {'title': 'Sweep the garage', 'owner': 'mom'}, dict(MOM))['step']
    _p().confirm_hold(house['id'], sweep['id'], {'date': DAY, 'start': '10:00', 'end': '11:00'}, dict(MOM))
    start, end = datetime.date(2027, 3, 1), datetime.date(2027, 3, 31)

    def titles(viewer):
        return sorted(h['title'] for h in _p().calendar_holds(start, end, viewer))
    check(titles(dict(MOM)) == ['Long walk', 'Sweep the garage'], f"the owner sees her step: {titles(dict(MOM))}")
    check(titles(dict(DAD)) == ['Busy', 'Sweep the garage'], f"the spouse sees Busy for the private one: {titles(dict(DAD))}")
    check(titles(None) == ['Busy', 'Sweep the garage'], f"the wall, speakers and the shared schedule see Busy: {titles(None)}")
    check(all(h['member_id'] == 'mom' for h in _p().calendar_holds(start, end, None)), "and whose time it is")
    past = _p().calendar_holds(datetime.date(2027, 3, 7), end, dict(MOM))
    check(past == [], f"a hold before the range is not on the calendar: {past}")


def scenario_a_drivers_hold_blocks_that_date_only():
    house, tile, paint = _setup()
    _p().confirm_hold(house['id'], tile['id'], {'date': DAY, 'start': '13:00', 'end': '16:00'}, dict(MOM))
    kids = _make('kid', MOM, title='Learn to ride a bike')
    practise = _p().add_step(kids['id'], {'title': 'Practise', 'owner': 'kid'}, dict(MOM))['step']
    _p().confirm_hold(kids['id'], practise['id'], {'date': DAY, 'start': '13:00', 'end': '14:00'}, dict(MOM))
    rules = _p().driver_hold_rules(datetime.date(2027, 3, 1), datetime.date(2027, 3, 31))
    check(len(rules) == 1 and rules[0].driver_id == 'd_dad' and rules[0].constraint_type == 'unavailable'
          and rules[0].start_date == DAY and rules[0].end_date == DAY, f"one dated rule, for the driver only: {rules}")
    from solver import matcher
    from test_override_conflicts import mk_driver
    from models.schemas import Event

    def at(start):
        return Event(id='e1', title='Soccer Practice', start=start, end=start + datetime.timedelta(hours=1),
                     location='Field', calendar_ids=['primary'], source_event_ids=['e1'])
    dad = mk_driver('d_dad', 'Dad')
    that_day = at(datetime.datetime(2027, 3, 6, 14, 0))
    next_week = at(datetime.datetime(2027, 3, 13, 14, 0))
    check(any('unavailable' in r for r in matcher.explain_assignment_conflicts(that_day, dad, rules)),
          "unavailable during the hold")
    check(not any('unavailable' in r for r in matcher.explain_assignment_conflicts(next_week, dad, rules)),
          "not the same time next week")


def scenario_the_routes():
    house, tile, paint = _setup()
    import main
    suggestion = main.project_step_hold(house['id'], tile['id'], {'minutes': 60, 'by_date': DAY}, request=_as('mom'))
    w = suggestion.get('window')
    check(w and datetime.date.today().isoformat() <= w['date'] <= DAY, f"a suggestion between today and the due date: {suggestion}")
    done = main.project_step_hold(house['id'], tile['id'], {'date': DAY, 'start': '13:00', 'end': '14:00'}, request=_as('dad'))
    check(done['status'] == 'success', f"confirmed by route: {done}")
    main.project_step_hold_clear(house['id'], tile['id'], request=_as('dad'))
    check(next(s for s in storage.get_project(house['id'])['steps'] if s['id'] == tile['id'])['hold'] is None, "cleared by route")


SCENARIOS = [
    scenario_the_finder_avoids_overlaps_and_says_when_nothing_fits,
    scenario_confirming_rechecks_and_stores_a_dated_hold,
    scenario_who_sees_what_on_the_calendar,
    scenario_a_drivers_hold_blocks_that_date_only,
    scenario_the_routes,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
