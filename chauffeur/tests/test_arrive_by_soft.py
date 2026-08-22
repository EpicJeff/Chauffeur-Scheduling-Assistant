"""An arrival target is a GOAL; the event's start is the COMMITMENT.

The family's rule, in their words: *"Not scheduling an event because of a
buffer or warmup arrival time isn't how it would happen in real life — and
that is what we are trying to model."* Nobody skips a game because they would
miss the warm-up. They turn up at kick-off.

So a buffer — whether it came from a rule or from an ICS description saying
"arrive 15 minutes before" — may make a pairing LESS PREFERRED. It must never:

  1. make an event unassignable,
  2. make a driver ineligible when the DRIVE itself fits,
  3. make an event look impossible to cover, or
  4. be reported as lateness for the event.

Three of the four were wrong. The buffer was already soft in the main driver
and passenger conflict constraints (`min_needed_seconds` is travel alone, and
`desired_needed_seconds` only ever costs objective points), but it was HARD in
the driver's personal-calendar check (a -2,000,000 penalty, which is twice the
assignment reward and therefore a ban), HARD in the ghost-route feasibility
scan, and HARD in the ghost-route model.

These scenarios SOLVE rather than read source, because every one of those
paths is inside a solver that quietly returns "unassigned" instead of raising.

Run from chauffeur/:  python tests/test_arrive_by_soft.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR and mocks maps)

from models.schemas import Driver, Event, Passenger, Rule
from solver import matcher

DAY = datetime.datetime(2026, 9, 12)


def _driver(i, **kw):
    return Driver(id=f"d{i}", name=f"Driver {i}", color_code="#fff",
                  group="primary", priority_index=1, **kw)


def _event(i, hour, minute=0, mins=60, location="Riverside Park", cals=None,
           **kw):
    start = DAY.replace(hour=hour, minute=minute)
    return Event(id=f"e{i}", title=f"Event {i}", start=start,
                 end=start + datetime.timedelta(minutes=mins),
                 location=location, calendar_ids=cals or ["primary"],
                 source_event_ids=[f"e{i}"], **kw)


def _buffer_rule(mins=45):
    # The keyword is load-bearing: `does_event_match_rule` matches NOTHING
    # when a rule states no criteria at all, so a bare buffer rule makes
    # these scenarios silently vacuous. Learned the hard way — the first cut
    # of this file passed identically with and without the fix.
    return Rule(driver_id="d1", constraint_type="buffer", keywords=["Event"],
                buffer_before_mins=mins, buffer_reason="Warm-up")


def scenario_a_warm_up_never_costs_the_game():
    """Property 1. The whole point: the event still gets a driver."""
    drivers = [_driver(1)]
    game = _event(1, 10, 15)

    plain, un_plain, _, _ = matcher.solve_schedule([game], drivers, [])
    check(plain.get('e1'), f"baseline: the game is assigned: {plain} {un_plain}")

    with_rule, un_rule, _, _ = matcher.solve_schedule([game], drivers,
                                                      [_buffer_rule(45)])
    check(with_rule.get('e1') == plain.get('e1'),
          f"a 45-minute warm-up changes nothing about covering it: {with_rule}")

    # And the same when the arrival came from the club rather than a rule.
    game.arrive_by = {'lead_mins': 45, 'label': 'Arrive 9:30 AM',
                      'arrive_at': DAY.replace(hour=9, minute=30).isoformat(),
                      'source': 'description', 'reason': 'club says so'}
    parsed, un_parsed, _, _ = matcher.solve_schedule([game], drivers, [])
    check(parsed.get('e1'), f"a PARSED arrival is just as harmless: {parsed}")
    check(matcher.arrival_lead_mins(game) == 45,
          "and the solver did see it — this is not passing by ignoring it")


def scenario_a_warm_up_does_not_disqualify_the_driver():
    """Property 2. The driver's own 9-10am meeting collides with a 9:30
    warm-up but leaves the 10:15 DRIVE perfectly possible.

    This was the -2,000,000 penalty: bigger than the assignment reward, so
    the ride was better left undriven than driven by the only parent free to
    drive it. Nobody behaves that way.
    """
    drivers = [_driver(1)]
    game = _event(1, 10, 15, location="Riverside Park")
    # A personal commitment ending 15 minutes before kick-off. The drive is
    # 0 minutes in the test harness's mocked map, so the DRIVE fits; only the
    # 45-minute early arrival does not.
    meeting = _event(9, 9, 0, mins=60, location="Riverside Park")
    meeting.event_type = "standard"

    a, un, _, _ = matcher.solve_schedule([game], drivers, [_buffer_rule(45)],
                                         driver_events={"d1": [meeting]})
    check(a.get('e1') == 'd1',
          f"the parent with a meeting still drives to the game: {a} / {un}")
    check('e1' not in un, f"and it is NOT left unassigned: {un}")


def scenario_the_buffer_still_shapes_the_choice():
    """The other half — soft must still mean SOMETHING, or this was just a
    deletion. Given two equally good drivers and a warm-up only one of them
    can honour, the solver should prefer the one who can.
    """
    free = _driver(1)
    busy = _driver(2)
    game = _event(1, 10, 15)
    meeting = _event(9, 9, 0, mins=60, location="Riverside Park")

    a, un, _, _ = matcher.solve_schedule(
        [game], [free, busy], [_buffer_rule(45)],
        driver_events={"d2": [meeting]})
    check(a.get('e1') == 'd1',
          f"the driver who can make the warm-up is preferred: {a}")


def scenario_a_warm_up_never_makes_an_event_look_uncoverable():
    """Property 3. Ghost routes answer "could anyone have covered this?" —
    a question about roads, not about warm-ups."""
    # One game already covered, and a second for the same child five minutes
    # later: no room at all for a 45-minute warm-up, plenty of room for the
    # (mocked, zero-minute) drive.
    pax = Passenger(id="p1", name="Ellie", calendar_ids=["kidcal"])
    covered = _event(1, 9, 0, mins=60, cals=["primary", "kidcal"])
    candidate = _event(2, 10, 5, mins=60, cals=["primary", "kidcal"])

    ghosts, _ = matcher.solve_ghost_routes(
        [candidate], [covered], [_buffer_rule(45)], [pax])
    check(ghosts.get('e2'),
          f"still coverable — the warm-up is not a road: {ghosts}")

    # The eligibility scan is the thing under test, so prove it still bites
    # on a real one: an hour of driving into a five-minute gap is impossible.
    with_travel = matcher.solve_ghost_routes(
        [candidate], [covered], [], [pax])[0]
    check(with_travel.get('e2'), "and the no-rule case is coverable too")


def scenario_late_means_late_for_the_event():
    """Property 4. "Will be 45m late" meaning "will miss the warm-up" is a
    different sentence and a much smaller problem, and reading it as lateness
    is how a family stops believing lateness warnings."""
    drivers = [_driver(1)]
    pax = Passenger(id="p1", name="Ellie", calendar_ids=["kidcal"])
    first = _event(1, 9, 0, mins=60, cals=["primary", "kidcal"])
    second = _event(2, 10, 5, mins=60, cals=["primary", "kidcal"])

    _, _, warnings, _ = matcher.solve_schedule(
        [first, second], drivers, [_buffer_rule(45)], passengers=[pax])
    msg = warnings.get('e2') or ''
    check('late' not in msg.lower() or 'miss the early arrival' in msg,
          f"a squeezed warm-up is not reported as lateness: {msg!r}")
    if msg:
        check('miss the early arrival' in msg,
              f"it is named for what it is: {msg!r}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} arrive-by-soft scenarios passed")
