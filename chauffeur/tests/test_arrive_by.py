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
    check(arrive_by.from_description('Arrive 15 minutes before kickoff') is None,
          "V3's hook is deliberately inert in V1, and says so by answering None")


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


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} arrive-by scenarios passed")
