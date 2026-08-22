"""Arrive By V1 — the time the family has to be standing there.

A buffer routing rule has worked and been invisible since it shipped: the
solver spaces conflicts by it and the drive plan leaves earlier for it, and no
surface has ever said so. A constraint the family cannot see is one they
cannot trust, check, or correct.

The fix is not "show the buffer" — it is to name the thing a buffer answers.
Three times per event, and they are not interchangeable:

    leave by / be ready   at home, before the drive     services/leave_by.py
    ARRIVE BY / be there  at the destination            services/arrive_by.py
    starts                the whistle blows             the event itself

The properties that matter, and why:

  1. **The earliest arrival wins — MAX, not precedence.** A household that set
     a 30-minute rule set it *because* clubs say 15 and they want more;
     precedence would silently undo the reason the rule exists.
  2. **A typed override REPLACES everything.** Somebody looked at this event
     and said a time; the app does not get to add to it.
  3. **The chip names its source.** "Your rule" and "the club says so" are
     different facts, and a parent deciding whether to argue needs to know
     which one they are looking at.
  4. **Silence beats a guess.** No location, all-day, no rule: no chip. A
     missed arrival costs a rule typed once; an invented one costs trust in
     every chip after it.
  5. **The matching is the SOLVER'S OWN.** The chip must state what the solver
     actually did — a second copy of the matching rules is a second thing to
     drift, and a chip that promises a buffer the solver ignored is worse than
     no chip.
  6. **The start time is never replaced** — this module returns an arrival
     ALONGSIDE the start, never instead of it. If the app says 10:00 and means
     warm-up, running late at 10:05 feels like missing a game that has not
     started, which is the anxiety the whole feature exists to remove.

Run from chauffeur/:  python tests/test_arrive_by.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage
from services import arrive_by
from models.schemas import Rule

DAY = datetime.date(2026, 9, 12)          # a Saturday
KICKOFF = datetime.datetime.combine(DAY, datetime.time(10, 15))
FINAL = datetime.datetime.combine(DAY, datetime.time(11, 30))


def _reset():
    with storage.db_lock:
        storage.event_configs_table.truncate()


def _event(**over):
    ev = {'id': 'ev1', 'title': 'U12 Blue vs Eagles', 'description': '',
          'start': KICKOFF.isoformat(), 'end': FINAL.isoformat(),
          'location': 'Riverside Park', 'all_day': False,
          'calendar_ids': ['cal-ellie']}
    ev.update(over)
    return ev


def _rule(**over):
    base = {'driver_id': 'd1', 'constraint_type': 'buffer',
            'keywords': ['vs'], 'buffer_before_mins': 15}
    base.update(over)
    return Rule(**base)


def scenario_a_buffer_rule_becomes_a_time_a_parent_can_say():
    """The whole point. 15 minutes of solver arithmetic becomes 10:00."""
    _reset()
    got = arrive_by.derive(_event(), rules=[_rule(buffer_reason='Warm-up')])
    check(got is not None, "a matching buffer rule produces an arrival")
    check(got['arrive_at'].endswith('10:00:00'), f"start minus the buffer: {got}")
    check(got['lead_mins'] == 15 and got['source'] == 'rule',
          f"and it says how much and from where: {got}")
    check(got['reason'] == 'Warm-up',
          "with the family's own word for why — a sentence, not a number")
    check('arrive_label' in got and got['arrive_label'],
          f"pre-formatted so no surface does its own clock: {got.get('arrive_label')}")

    # Property 6, asserted structurally: nothing here touches the start.
    check('start' not in got,
          "the module never returns a replacement start — every caller shows both")

    bare = arrive_by.derive(_event(), rules=[_rule()])
    check(bare['reason'] == arrive_by.DEFAULT_REASON,
          f"a rule with no reason still says something useful: {bare['reason']!r}")


def scenario_the_earliest_arrival_wins():
    """Property 1. Two rules match; the family's own longer one is the
    reason it was typed, and must not be undone by the shorter."""
    _reset()
    rules = [_rule(buffer_before_mins=15, buffer_reason='Warm-up'),
             _rule(buffer_before_mins=30, buffer_reason='Goalie warm-up')]
    got = arrive_by.derive(_event(), rules=rules)
    check(got['lead_mins'] == 30 and got['reason'] == 'Goalie warm-up',
          f"the earliest arrival wins, and brings its own reason: {got}")

    # Order must not decide it.
    got2 = arrive_by.derive(_event(), rules=list(reversed(rules)))
    check(got2['lead_mins'] == 30, "and the rule order is irrelevant")


def scenario_a_typed_override_replaces_rather_than_maxes():
    """Property 2. The one exception to max: a person said a time."""
    _reset()
    storage.set_event_config('ev1', {'arrive_lead_mins': 5,
                                     'arrive_reason': 'Just the once'})
    got = arrive_by.derive(_event(), rules=[_rule(buffer_before_mins=45)])
    check(got['lead_mins'] == 5 and got['source'] == 'override',
          f"5 beats 45 because a person said 5: {got}")
    check(got['reason'] == 'Just the once', "carrying their words")

    # An override of zero is a real answer — "no, we do not go early" — and
    # must not silently fall through to the rule it was written to overrule.
    storage.set_event_config('ev2', {'arrive_lead_mins': 0})
    off = arrive_by.derive(_event(id='ev2'), rules=[])
    check(off is None, "nothing to say when nothing asks for it")


def scenario_silence_beats_a_guess():
    """Property 4. None is the common answer and must stay cheap to say."""
    _reset()
    rules = [_rule(buffer_before_mins=15)]
    check(arrive_by.derive(_event(location=''), rules=rules) is None,
          "no location -> there is no arriving to do")
    check(arrive_by.derive(_event(all_day=True), rules=rules) is None,
          "an all-day event has no minute to be early to")
    check(arrive_by.derive(_event(start=None), rules=rules) is None,
          "and no start is no answer, not a crash")
    check(arrive_by.derive(_event(), rules=[]) is None,
          "no rule, no chip — the overwhelming majority of events")
    check(arrive_by.derive(_event(description='Bring water and shin pads.'),
                           rules=[]) is None,
          "a description with no arrival language says nothing (V3 fails closed)")


def scenario_the_matching_is_the_solvers_own():
    """Property 5. A chip promising a buffer the solver ignored is worse than
    no chip, so the matching is delegated rather than reimplemented."""
    _reset()
    ev = _event()
    check(arrive_by.derive(ev, rules=[_rule(keywords=['piano'])]) is None,
          "a rule whose keywords miss the event produces nothing")
    check(arrive_by.derive(ev, rules=[_rule(location='Riverside')]) is not None,
          "and the solver's location matching works here too")
    check(arrive_by.derive(ev, rules=[_rule(days_of_week=[0])]) is None,
          "a Monday rule does not fire on a Saturday game")
    check(arrive_by.derive(ev, rules=[_rule(days_of_week=[5])]) is not None,
          "the right weekday does")

    # Only BUFFER rules. A tolerance rule is a different sentence entirely.
    tol = Rule(driver_id='d1', constraint_type='tolerance', keywords=['vs'],
               tolerance_mins=20)
    check(arrive_by.derive(ev, rules=[tol]) is None,
          "a tolerance rule is not an early arrival")

    # A disabled rule is not in force, and must not be advertised as if it were.
    check(arrive_by.derive(ev, rules=[_rule(is_enabled=False)]) is None,
          "a switched-off rule produces no chip")


def scenario_a_broken_rule_never_costs_the_chip():
    """One malformed rule in a list must not take the arrival with it — and
    must not be silently treated as a match either."""
    _reset()

    class Exploding:
        constraint_type = 'buffer'
        is_enabled = True
        buffer_before_mins = 99

        def __getattr__(self, name):
            raise RuntimeError('boom')

    got = arrive_by.derive(_event(), rules=[Exploding(), _rule(buffer_before_mins=15)])
    check(got and got['lead_mins'] == 15,
          f"the good rule still answers: {got}")


def scenario_the_lead_is_clamped_to_something_sane():
    """A rule asking for half a day is a typo, not a warm-up."""
    _reset()
    got = arrive_by.derive(_event(), rules=[_rule(buffer_before_mins=6000)])
    check(got['lead_mins'] == arrive_by.MAX_LEAD_MINS,
          f"clamped rather than believed: {got['lead_mins']}")
    check(arrive_by.derive(_event(), rules=[_rule(buffer_before_mins=-30)]) is None,
          "and a negative buffer is nothing, never an arrival AFTER the start")


def scenario_the_after_buffer_mirrors_it():
    """"You are not leaving yet" is a different sentence from "be there by",
    so it is a separate call a surface can want on its own."""
    _reset()
    rules = [_rule(buffer_before_mins=0, buffer_after_mins=20,
                   buffer_reason='Team huddle')]
    check(arrive_by.derive(_event(), rules=rules) is None,
          "an after-only rule says nothing about arriving")
    trail = arrive_by.depart_after(_event(), rules=rules)
    check(trail and trail['depart_at'].endswith('11:50:00'),
          f"end plus the trail: {trail}")
    check(trail['trail_mins'] == 20 and trail['reason'] == 'Team huddle',
          f"with its own reason: {trail}")
    check(arrive_by.depart_after(_event(location=''), rules=rules) is None,
          "and the same silence rules apply")


def scenario_a_day_is_stamped_in_one_pass():
    """Property 5's corollary: one derivation, so two surfaces reading the
    same payload cannot disagree about when to be at the pitch."""
    _reset()
    rows = arrive_by.annotate(
        [_event(), _event(id='ev2', title='Piano lesson', keywords=None),
         _event(id='ev3', all_day=True)],
        rules=[_rule(buffer_before_mins=15, buffer_reason='Warm-up')])
    check(len(rows) == 3, "every event comes back, annotated or not")
    check(rows[0]['arrive_by']['lead_mins'] == 15, "the match is stamped")
    check('arrive_by' not in rows[1],
          "the one that matches nothing is left completely alone")
    check('arrive_by' not in rows[2], "and so is the all-day one")
    check(rows[0]['title'] == 'U12 Blue vs Eagles' and rows[0]['start'],
          "the event itself is untouched — this ANNOTATES, it never rewrites")


def scenario_the_reason_is_reachable_by_hand_and_by_agent():
    """Every capability needs a hand path, and a rule the family can only get
    by talking to Argyle is a rule they cannot correct."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = open(os.path.join(here, 'templates', 'config.html'), encoding='utf-8').read()
    check('newRule.buffer_reason' in cfg, "the rule editor has the field")
    check(cfg.count('buffer_reason') >= 3,
          "and it survives a save and an edit, not just the form")
    llm = open(os.path.join(here, 'services', 'llm.py'), encoding='utf-8').read()
    check('buffer_reason' in llm and 'never invent a reason' in llm,
          "the rule-writing prompt knows about it, and knows not to invent one")

    r = Rule(driver_id='d1', constraint_type='buffer', buffer_before_mins=15,
             buffer_reason='Warm-up')
    check(r.buffer_reason == 'Warm-up', "and it is a real field on the model")


def scenario_one_string_every_surface():
    """V2's whole contract. Each surface renders the label the SERVER built,
    never its own concatenation — because a wall panel and a phone wording
    the same game differently is how a family stops believing either."""
    _reset()
    got = arrive_by.derive(_event(), rules=[_rule(buffer_reason='Warm-up')])
    check(got['label'] == 'Arrive 10:00 AM · Warm-up',
          f"one canonical string: {got['label']!r}")
    check(got['short_label'] == 'Arrive 10:00 AM',
          f"and a tight one for cramped rows: {got['short_label']!r}")

    trail = arrive_by.depart_after(
        _event(), rules=[_rule(buffer_after_mins=20, buffer_reason='Huddle')])
    check(trail['label'] == 'Leave 11:50 AM · Huddle',
          f"the mirror reads as its own sentence: {trail['label']!r}")

    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _read(*parts):
        return open(os.path.join(here, *parts), encoding='utf-8').read()

    # Every surface the family named. Each reads `.label`/`.short_label` off
    # the payload; none of them formats a time or joins a reason itself.
    for parts, what in (
            (('services', 'home_board.py'), 'the wall board rows'),
            (('templates', 'components', 'board_tile_body.html'), 'the wall tile'),
            (('services', 'drive_sheet.py'), 'the drive sheet payload'),
            (('templates', 'app.html'), 'the PWA'),
            (('templates', 'dashboard.html'), 'the event detail'),
            (('services', 'family_digest.py'), 'the drive digest')):
        check('arrive_by' in _read(*parts), f"{what} carries it")

    tile = _read('templates', 'components', 'board_tile_body.html')
    check('(r.arrive_by || {}).label' in tile,
          "the wall tile renders the server's label verbatim")
    app = _read('templates', 'app.html')
    check('r.arrive_by.label' in app and 'ab.label' in app,
          "and so does the PWA, on both the day card and the drive sheet")
    dash = _read('templates', 'dashboard.html')
    check('ab.label' in dash and 'your buffer rule' in dash,
          "the event detail shows the label AND names its source")


def scenario_the_start_time_is_never_replaced():
    """The anxiety this whole feature exists to remove: if the app says
    10:00 and means warm-up, running late at 10:05 feels like missing a game
    that has not started. Every surface shows BOTH, start dominant."""
    _reset()
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    rows = arrive_by.annotate([_event()],
                              rules=[_rule(buffer_before_mins=15)])
    check(rows[0]['start'] == KICKOFF.isoformat(),
          f"annotation leaves the real start exactly as it was: {rows[0]['start']}")
    check(rows[0]['arrive_by']['arrive_at'] != rows[0]['start'],
          "the arrival is a SECOND time, not a rewritten one")

    tile = open(os.path.join(here, 'templates', 'components',
                             'board_tile_body.html'), encoding='utf-8').read()
    # The row's own time is still rendered from leave/ready/at, untouched by
    # the arrival, and the arrival sits on its own line beneath it.
    check('r.leave_label || r.ready_label || r.at' in tile,
          "the wall row's time slot is unchanged")
    app = open(os.path.join(here, 'templates', 'app.html'), encoding='utf-8').read()
    check('${timeStr}' in app and 'r.arrive_by.label' in app,
          "the PWA card shows the event time AND the arrival, not one or other")


# --- V3: the club's own words ------------------------------------------------

def scenario_the_club_is_read_out_of_the_description():
    """The text was ALWAYS there — ics_sync copies the ICS DESCRIPTION onto
    the Google event, so Playmetrics' "arrive by 10:00" has been sitting in
    the event body unread. This is a parse, not a capture."""
    for text, want in (
            ("Please arrive 15 minutes before game time for warm-ups.", 15),
            ("Arrive by 10:00 AM.", 15),
            ("Players arrive 30 minutes prior to kickoff.", 30),
            ("Arrival: 9:45am", 30),
            ("Check-in at 9:30 am, game at 10:15.", 45),
            ("Be there 20 mins early.", 20)):
        got = arrive_by.from_description(text, KICKOFF)
        check(got and got['lead_mins'] == want,
              f"{text!r} -> {want}, got {got}")

    got = arrive_by.from_description("Please arrive 15 minutes before for warm-ups.",
                                     KICKOFF)
    check('15 minutes' in got['reason'],
          f"the club's own phrasing becomes the reason: {got['reason']!r}")


def scenario_the_parser_fails_closed():
    """The half that matters more. A missed arrival costs a rule typed once;
    an invented one costs trust in every chip after it — and a wrong arrival
    is indistinguishable from a right one until somebody is standing in an
    empty car park."""
    for text in ("Gates open at 9:30 am.",
                 "Bus departs at 9:00 am.",
                 "Pick-up at 11:30 am.",
                 "Parking opens at 9:00 am.",
                 "U12 Blue vs Eagles at Riverside Park.",
                 "See league rules. Refunds must be requested 30 minutes before the season.",
                 "Arrive at 11:00 PM.",
                 ""):
        check(arrive_by.from_description(text, KICKOFF) is None,
              f"{text!r} must yield nothing")

    # A red herring SHARING A LINE with a real instruction must not kill it:
    # the disqualifier is judged against its own sentence, not the whole text.
    got = arrive_by.from_description("Gates open at 9:00 am. Players arrive 9:45 am.",
                                     KICKOFF)
    check(got and got['lead_mins'] == 30,
          f"the real instruction survives its neighbour: {got}")

    # Club descriptions trail off into league rules and refund policies; a
    # "30 minutes before" buried on line twelve is not this game's arrival.
    buried = chr(10).join(["Game day!"] + ["filler"] * 10
                          + ["Please arrive 30 minutes before."])
    check(arrive_by.from_description(buried, KICKOFF) is None,
          "only the first few lines are read")

    # No start means an absolute time cannot be turned into a lead at all.
    check(arrive_by.from_description("Arrive by 10:00 AM.", None) is None,
          "an absolute time with nothing to measure against yields nothing")


def scenario_a_parsed_arrival_joins_the_same_max():
    """V3 is a SOURCE, not a second system: it feeds the same max-wins
    derivation V1 built, and says so in `source`."""
    _reset()
    ev = _event(description="Please arrive 15 minutes before for warm-ups.")

    got = arrive_by.derive(ev, rules=[])
    check(got and got['source'] == 'description' and got['lead_mins'] == 15,
          f"no rule needed — the club said it: {got}")

    # The family's longer standing rule still wins, because it was typed for
    # exactly this reason: clubs say 15 and this household wants 30.
    both = arrive_by.derive(ev, rules=[_rule(buffer_before_mins=30,
                                             buffer_reason='Goalie warm-up')])
    check(both['lead_mins'] == 30 and both['source'] == 'rule',
          f"max still wins across sources: {both}")

    # And a shorter rule does NOT drag the club's instruction later.
    shorter = arrive_by.derive(ev, rules=[_rule(buffer_before_mins=5)])
    check(shorter['lead_mins'] == 15 and shorter['source'] == 'description',
          f"the earliest arrival wins whichever source it came from: {shorter}")

    # A typed override still replaces everything, club included.
    storage.set_event_config('ev1', {'arrive_lead_mins': 5})
    over = arrive_by.derive(ev, rules=[_rule(buffer_before_mins=30)])
    check(over['lead_mins'] == 5 and over['source'] == 'override',
          f"a person overruling the app is not argued with: {over}")


def scenario_a_long_club_sentence_does_not_break_the_chip():
    """The parsed reason is the club's whole sentence — that is what makes the
    chip checkable against the email — and a whole sentence does not fit in a
    chip. The sentence travels; the label stays a label."""
    _reset()
    ev = _event(description="Please arrive 15 minutes before game time so the "
                            "team can complete warm-ups together.")
    got = arrive_by.derive(ev, rules=[])
    check(len(got['reason']) > 24, f"the sentence is kept whole: {got['reason']!r}")
    check(got['label'] == got['short_label'],
          f"but the label does not try to wear it: {got['label']!r}")

    short = arrive_by.derive(_event(), rules=[_rule(buffer_reason='Warm-up')])
    check(short['label'].endswith('· Warm-up'),
          f"a short reason still rides the label: {short['label']!r}")


def scenario_it_survives_the_trip_from_solve_to_screen():
    """The wiring, RUN rather than read.

    The first cut of V2 stamped only the per-day payload, while the wall
    board, the drive sheet, the digest and My Day all read the
    WHOLE-SCHEDULE cache — so every surface was wired to a field nothing ever
    set and absolutely nothing appeared. The stamp is inside a try/except, so
    a break here is silent: this has to exercise the real objects.
    """
    from models.schemas import Event
    _reset()

    ev = Event(id='ev1', title='U12 Blue vs Eagles', description='',
               start=KICKOFF, end=FINAL, location='Riverside Park',
               calendar_ids=['cal-ellie'], source_event_ids=['ev1'])

    # 1. The derivation takes an Event MODEL, which is what the refresh has.
    got = arrive_by.derive(ev, [_rule(buffer_reason='Warm-up')], None)
    check(got and got['lead_mins'] == 15,
          f"derive works on the model, not just on a dict: {got}")

    # 2. The model can actually hold it. A plain attribute assignment onto a
    #    pydantic model without the field declared raises, and the refresh
    #    swallows that — which is precisely how this stayed invisible.
    ev.arrive_by = got
    ev.depart_after = arrive_by.depart_after(
        ev, [_rule(buffer_after_mins=20, buffer_reason='Huddle')], None)
    check(ev.arrive_by and ev.depart_after, "both fields assign cleanly")

    # 3. And it survives serialisation, which is how it reaches the cache.
    d = ev.dict()
    check(d.get('arrive_by', {}).get('label', '').startswith('Arrive'),
          f"the label reaches the payload: {d.get('arrive_by')}")
    check(d.get('depart_after', {}).get('trail_mins') == 20,
          f"and so does the mirror: {d.get('depart_after')}")

    # 4. The surfaces read it off the cached event dict, so the dict shape
    #    they expect is the shape serialisation produces.
    for key in ('label', 'short_label', 'arrive_at', 'source', 'reason'):
        check(key in d['arrive_by'], f"the cached event carries {key}")

    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    m = open(os.path.join(here, 'main.py'), encoding='utf-8').read()
    stamp = m.find('_ev.arrive_by = _arrive_by.derive')
    payload = m.find('"events": list(all_events_for_ui.values())')
    check(stamp != -1 and payload != -1 and stamp < payload,
          "the stamp happens BEFORE the whole-schedule payload is built")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} arrive-by scenarios passed")
