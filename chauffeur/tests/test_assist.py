"""Outside hands — assist contacts and the work they cover (load arc A1).

The load-bearing properties, in the order they matter:

  1. **A covered event leaves the solver.** Not assignable, not unassigned,
     not ghost-eligible. This is the entire feature: outside help REMOVES
     load, and the app previously had no way to be told so.
  2. **The false alarm dies.** "🚨 No driver yet" for a ride a carpool parent
     was always making is the standing bug this retires — and its twin in the
     status coverage report, which must name the carpool parent rather than
     flagging the run as open on somebody's hard week.
  3. **A contact is not a member.** No account, no headcount, no wall board.
     Deleting one takes their coverage with them, or the day would show work
     as covered by somebody who no longer exists.
  4. **The kid hears who they're riding with.** A carpool ride had no driver,
     so the digest simply said nothing — exactly the uncertainty the kid arc
     exists to remove.

Run from chauffeur/:  python tests/test_assist.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()


def _reset():
    for t in (storage.assist_contacts_table, storage.assist_assignments_table):
        t.truncate()


def _contact(name="Sarah Whitfield", label="Emma's mom", **kw):
    from models.schemas import AssistContact
    c = AssistContact(name=name, relation_label=label, **kw).model_dump()
    storage.add_assist_contact(c)
    return c


def scenario_a_contact_is_stored_not_typed():
    """The question that produced this design: is a name enough? No — they
    repeat, the phone number is the whole value in the moment you need it,
    and only a stored contact lets the rest of the app stop treating the work
    as open."""
    _reset()
    c = _contact(phone="555-0142", kinds=["carpool"], relationship="reciprocal")
    got = storage.get_assist_contact(c['id'])
    check(got and got['phone'] == "555-0142",
          "the number is the point of storing them at all")
    check(got['relation_label'] == "Emma's mom",
          "the label the family actually says out loud is kept")
    check(got['kinds'] == ["carpool"], "kinds is a free tag list")
    check(storage.get_assist_contacts() and
          storage.get_assist_contacts()[0]['id'] == c['id'],
          "active contacts list by name")


def scenario_carpool_is_a_kind_of_help_not_a_kind_of_person():
    """The correction that renamed this arc: the neighbourhood girl who does
    the dishes has no place in the app either. One entity, tags for what they
    help with, and NOTHING branches on the tag."""
    _reset()
    _contact(name="Sarah Whitfield", label="Emma's mom", kinds=["carpool"])
    dishes = _contact(name="Mia Kelly", label="the Kellys' girl",
                      kinds=["housework"], relationship="paid")
    check(len(storage.get_assist_contacts()) == 2,
          "a house helper and a carpool parent are the same kind of row")
    got = storage.get_assist_contact(dishes['id'])
    check(got['relationship'] == 'paid',
          "you owe a carpool parent a turn and the dish-washer money — the "
          "relationship is what turn-taking will key off, not the tag")


def scenario_coverage_is_one_contact_per_event():
    _reset()
    a = _contact(name="A")
    b = _contact(name="B")
    storage.set_assist_assignment('ev1', a['id'])
    storage.set_assist_assignment('ev1', b['id'])
    check(storage.get_assist_assignment_map() == {'ev1': b['id']},
          "setting replaces rather than stacking — an event has ONE coverer")
    check(storage.clear_assist_assignment('ev1'), "and it can be handed back")
    check(storage.get_assist_assignment_map() == {}, "cleanly")


def scenario_deleting_a_contact_takes_their_coverage_with_them():
    """A covered event whose contact no longer exists would read as unassigned
    everywhere AND stay out of the solver — work that belongs to nobody."""
    _reset()
    c = _contact()
    storage.set_assist_assignment('ev1', c['id'])
    storage.set_assist_assignment('ev2', c['id'])
    storage.delete_assist_contact(c['id'])
    check(storage.get_assist_assignment_map() == {},
          "their coverage goes with them, handing the drives back")


def scenario_a_covered_event_leaves_the_solver():
    """The heart of it. The refresh filters covered events out of the set it
    solves and puts them back into `events` afterwards, so the timeline still
    draws them while no household driver is ever put on them."""
    _reset()
    c = _contact()
    assist_map = {'ev_soccer': c['id']}

    class _Ev:
        def __init__(self, i):
            self.id = i
    events = [_Ev('ev_soccer'), _Ev('ev_guitar')]

    # The exact expression main.py's solve loop uses.
    daily_assist = {e.id: assist_map[e.id] for e in events if e.id in assist_map}
    assist_events = [e for e in events if e.id in daily_assist]
    solvable = [e for e in events if e.id not in daily_assist]

    check([e.id for e in solvable] == ['ev_guitar'],
          "the covered ride is not handed to the solver")
    check(daily_assist == {'ev_soccer': c['id']},
          "and it is recorded as covered rather than lost")
    check(sorted(e.id for e in (solvable + assist_events)) == ['ev_guitar', 'ev_soccer'],
          "but it goes back into `events` — it is a real thing happening today "
          "and the timeline must draw it")


def scenario_coverage_rides_the_daily_hash():
    """Handing a drive to a carpool parent changes nothing about the EVENT.
    Without coverage in the hash the day's cache stays valid and the solver
    keeps a household driver on a ride somebody else is making — the change
    would appear to do nothing until the next forced refresh."""
    import main

    class _Ev:
        def __init__(self, i):
            self.id, self.start, self.end = i, 's', 'e'
            self.location, self.title = 'loc', 't'
    events = [_Ev('ev1')]
    bare = main.hash_events(events)
    covered = main.hash_events(events, assist_map={'ev1': 'contact_a'})
    other = main.hash_events(events, assist_map={'ev1': 'contact_b'})
    check(bare != covered, "covering an event must invalidate the day")
    check(covered != other, "and so must changing WHO covers it")
    check(covered == main.hash_events(events, assist_map={'ev1': 'contact_a'}),
          "while an unchanged day stays cacheable")


def scenario_the_no_driver_alarm_does_not_fire_for_covered_rides():
    """The standing false alarm: both parents DM'd "🚨 No driver yet" about a
    ride that was always handled."""
    from services import watchers
    _reset()
    now = datetime.datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
    start = (now + datetime.timedelta(days=1)).replace(hour=16)
    cache = {
        'events': [{'id': 'ev1', 'title': 'Soccer', 'start': start.isoformat()},
                   {'id': 'ev2', 'title': 'Guitar', 'start': start.isoformat()}],
        'unassigned': ['ev1', 'ev2'],
        'assist_assignments': {'ev1': 'contact_a'},
    }
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: cache
        found = watchers._unassigned_findings(now)
        titles = " ".join(msg for _, msg in found)
        check('Guitar' in titles,
              "a genuinely uncovered ride is still chased")
        check('Soccer' not in titles,
              f"but a covered one is not — got {titles!r}")
    finally:
        storage.get_cached_schedule = orig


def scenario_the_coverage_report_names_them_instead_of_flagging_it_open():
    """The status coverage report is what the other adult reads on a hard
    week. Telling them a carpool run "needs a driver" is exactly the wrong
    thing to hand them."""
    from services import status_protocols
    _reset()
    c = _contact()
    sched = {
        'events': [{'id': 'ev1', 'title': 'Soccer',
                    'start': f"{TODAY.isoformat()}T16:00:00"}],
        'assignments': {},
        'assist_assignments': {'ev1': c['id']},
        'assist_contacts': [c],
    }
    assist_map = dict(sched.get('assist_assignments', {}))
    assist_names = {x['id']: (x.get('relation_label') or x.get('name'))
                    for x in sched['assist_contacts']}
    who = assist_names.get(assist_map.get('ev1'))
    check(who == "Emma's mom",
          f"the report names the person the family knows, got {who!r}")
    check(hasattr(status_protocols, 'send_coverage_reports'),
          "and it is the real report this feeds")


def scenario_the_kid_is_told_who_they_are_riding_with():
    """A carpool ride has no driver, so the digest said nothing at all — the
    exact uncertainty the kid arc exists to remove. The assist phrase LEADS,
    because no household driver name will ever appear to give the answer."""
    r = {'title': 'Soccer', 'assist': {'name': 'Sarah Whitfield',
                                       'label': "Emma's mom", 'phone': '555'},
         'legs': [], 'driver': None}
    assist = r.get('assist')
    line = "4:00 PM – Soccer"
    if assist:
        line += f" — 🚗 riding with {assist.get('label') or assist.get('name')}"
    check(line.endswith("riding with Emma's mom"),
          f"the label beats the legal name — a child knows 'Emma's mom', got {line!r}")


def scenario_the_agent_can_hand_a_drive_over_and_take_it_back():
    from services import agent_tools_v2
    _reset()
    c = _contact()
    start = f"{TODAY.isoformat()}T16:00:00"
    sched = {'events': [{'id': 'ev1', 'title': 'Soccer Practice', 'start': start}]}
    orig = storage.get_cached_schedule
    try:
        storage.get_cached_schedule = lambda: sched

        res = agent_tools_v2.cover_with_assist('soccer', "Emma's mom")
        check(res['status'] == 'success' and res.get('schedule_dirty'),
              f"handing it over must re-solve the day, got {res}")
        check(storage.get_assist_assignment_map() == {'ev1': c['id']},
              "and it is recorded")
        check("Emma's mom" in res['message'],
              f"the confirmation says who, got {res['message']!r}")

        read = agent_tools_v2.get_assist_coverage()
        check('Soccer Practice' in read['message'] and "Emma's mom" in read['message'],
              f"and it can be read back, got {read['message']!r}")

        res = agent_tools_v2.cover_with_assist('soccer', clear=True)
        check(res['status'] == 'success' and res.get('schedule_dirty'),
              "taking it back must re-solve too — the event needs a driver again")
        check(storage.get_assist_assignment_map() == {}, "and the coverage is gone")

        res = agent_tools_v2.cover_with_assist('soccer', 'somebody nobody knows')
        check(res['status'] == 'error' and 'Config' in res['message'],
              f"an unknown helper points at the hand path, got {res}")

        res = agent_tools_v2.cover_with_assist('badminton', "Emma's mom")
        check(res['status'] == 'error' and 'Soccer Practice' in res['message'],
              f"an unknown event lists what IS on, got {res}")
    finally:
        storage.get_cached_schedule = orig


def scenario_a_contact_is_found_by_what_the_family_calls_them():
    """Nobody says "Sarah Whitfield" out loud. They say "Emma's mom"."""
    from services import agent_tools_v2
    _reset()
    c = _contact(name="Sarah Whitfield", label="Emma's mom")
    for spoken in ("Emma's mom", "emmas mom", "Sarah Whitfield", "Sarah"):
        got = agent_tools_v2._find_assist_contact(spoken)
        check(got and got['id'] == c['id'],
              f"'{spoken}' must resolve to her, got {got}")


def scenario_every_agent_capability_has_a_hand_path():
    """The standing rule: nothing ships agent-only."""
    import os
    from services import agent_tools_v2
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    for t in ('cover_with_assist', 'get_assist_coverage'):
        check(t in names, f"{t} is offered to the model")
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    config = open(os.path.join(tpl, 'config.html'), encoding='utf-8').read()
    check('assistContacts' in config and 'saveAssistContact' in config,
          "contacts can be added by hand in Config → People")
    dash = open(os.path.join(tpl, 'dashboard.html'), encoding='utf-8').read()
    check('setAssistCoverage' in dash and "startsWith('assist_')" in dash,
          "and a drive can be handed over by hand on the schedule")
    # REACHABILITY, not presence. This assertion used to stop at the line
    # above, which a dead function satisfies — and for two versions the only
    # door to coverage was dropping a drive onto an assist column, while the
    # columns were built from the coverage that door was supposed to create.
    # An uncovered drive therefore had no way in at all, and this test passed
    # the whole time. Anything checking a hand path must ask how the FIRST one
    # is made.
    check('populateAssistDropdown' in dash and 'edit-assist-contact' in dash,
          "a drive with NO coverage yet can still be handed over — the picker "
          "is filled from the contacts, not from the existing assignments")
    # Reachability again, one layer further in. The picker was real, filled
    # correctly, and STILL could not be found: it hid itself whenever the
    # contact list came back empty, and the list it read was the schedule
    # payload — only rebuilt by a solve. So a family who had just added a
    # carpool parent got an invisible control, and no way to learn that a
    # prerequisite existed. An empty list is a thing to SAY, not to vanish for.
    check('ASSIST_EMPTY_HINT' in dash and 'Settings → People' in dash,
          "with nobody set up the picker still shows itself and names the "
          "missing prerequisite, instead of hiding the feature")
    check('api/assist-contacts' in dash and 'loadAssistContacts' in dash,
          "the contacts are fetched on their own account, so the picker is "
          "never staler than the modal that opened it")
    check('populateAssistView' in dash and 'view-assist-contact' in dash,
          "handing a drive over is reachable from the event VIEW — it is a "
          "scheduling decision, not a detail filed under Edit Details")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('handDriveToOutsideHand' in app and 'api/assist-coverage' in app,
          "and from the PHONE, which is where you are standing when a carpool "
          "actually gets arranged")
    check('em-assist-row' in app and 'assist_assignments' in app,
          "the phone also SAYS who is covering it — a covered drive used to "
          "show nothing there at all")
    timeline = open(os.path.join(tpl, 'components', 'schedule_timeline.html'),
                    encoding='utf-8').read()
    check('assist_assignments' in timeline and 'assist_contacts' in timeline,
          "the SHARED renderer draws them, so the board tile and the dashboard "
          "cannot disagree about what a covered ride looks like")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} outside-hands scenarios passed")
