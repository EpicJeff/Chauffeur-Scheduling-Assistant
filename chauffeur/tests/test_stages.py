"""Stages — the child that grows (load arc A4).

Load-bearing properties:

  1. **A birthdate only ever SUGGESTS.** A pin always wins, and individual
     capability overrides bend single switches — kids differ, and a single
     number should not be destiny.
  2. **The bands are cutoffs, configurable, and sanitised hard** — contiguous
     bands cannot develop gaps, and garbage settings fall back rather than
     making a stage unreachable.
  3. **Growing up is granted, never silently switched.** The suggestion moving
     past the acknowledgement raises a moment; nothing changes until a parent
     confirms, and the watcher says so once per transition.
  4. **Nothing is deleted when a child moves up.** The points ledger survives
     a Navigator; it just stops leading the screen.
  5. **The gate is server-side.** A Sprout's ask is refused in the service,
     not just hidden in the UI.

Run from chauffeur/:  python tests/test_stages.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import stages, storage

TODAY = datetime.date.today()


def _reset(settings=None):
    for t in (storage.members_table, storage.requests_table, storage.points_ledger_table):
        t.truncate()
    storage.get_settings = (lambda: settings) if settings else (lambda: {})


def _kid(name, age=None, **kw):
    from models.schemas import FamilyMember
    bd = None
    if age is not None:
        bd = TODAY.replace(year=TODAY.year - age) - datetime.timedelta(days=30)
        bd = bd.isoformat()
    m = FamilyMember(name=name, role='child', birthdate=bd, **kw).model_dump()
    storage.add_member(m)
    return m


def scenario_the_bands_map_to_school_shapes():
    """0-5 / 6-11 / 12-14 / 15-18 — preschool, elementary, middle, high."""
    _reset()
    for age, want in ((3, 'sprout'), (5, 'sprout'), (6, 'explorer'),
                      (11, 'explorer'), (12, 'navigator'), (14, 'navigator'),
                      (15, 'copilot'), (17, 'copilot')):
        got = stages.stage_for_age(age)
        check(got == want, f"age {age} → {want}, got {got}")


def scenario_the_cutoffs_are_configurable_and_sanitised():
    """Middle school often starts at eleven; a fixed twelve puts a sixth
    grader in the wrong stage for half the year. And garbage settings fall
    back rather than making a band unreachable."""
    _reset(settings={'stage_cutoffs': [6, 11, 15]})
    check(stages.stage_for_age(11) == 'navigator',
          "a family whose middle school starts at 11 just sets the number")
    for bad in ([12, 6, 15], [6, 6, 15], "6,12,15", [6, 12], None, [0, 12, 15]):
        _reset(settings={'stage_cutoffs': bad})
        check(stages.cutoffs() == [6, 12, 15],
              f"garbage cutoffs {bad!r} fall back to the defaults")


def scenario_a_birthdate_only_ever_suggests():
    _reset()
    k = _kid("Lily", age=13)
    check(stages.stage_of(k) == 'navigator', "13 suggests navigator")
    k['stage_override'] = 'explorer'
    check(stages.stage_of(k) == 'explorer',
          "a pin always wins — kids differ, and a number is not destiny")
    k2 = _kid("NoBirthday")
    check(stages.stage_of(k2) == 'explorer',
          "no birthdate lands in the safe middle, never a crash or a Sprout lockdown")


def scenario_capabilities_are_a_bundle_with_single_switch_overrides():
    """A mature eleven-year-old can hold request rights without being aged up
    wholesale."""
    _reset()
    k = _kid("Ellie", age=9)
    caps = stages.capabilities(k)
    check(caps['show_points'] and caps['can_request'] and not caps['assignable_tasks'],
          f"an Explorer's bundle: {caps}")
    k['capability_overrides'] = {'assignable_tasks': True}
    check(stages.capabilities(k)['assignable_tasks'] is True,
          "one switch bends without moving the stage")
    check(stages.capabilities(k)['show_points'] is True,
          "and the rest of the bundle is untouched")

    teen = _kid("James", age=16)
    tcaps = stages.capabilities(teen)
    check(not tcaps['show_points'] and tcaps['can_drive'] and tcaps['private_location'],
          f"a Copilot: points retire, driving and privacy arrive: {tcaps}")


def scenario_adults_are_not_staged():
    from models.schemas import FamilyMember
    _reset()
    adult = FamilyMember(name="Jeff", role='parent').model_dump()
    check(stages.can(adult, 'can_request') and stages.can(adult, 'assignable_tasks'),
          "an adult simply can — stages are a kid concept")
    check(stages.stage_of(adult) is None, "and they have no stage at all")


def scenario_growing_up_is_granted_never_silently_switched():
    _reset()
    k = _kid("Lily", age=12, stage_acknowledged='explorer')
    pending = stages.pending_promotions()
    check(len(pending) == 1 and pending[0]['to'] == 'navigator',
          f"the age moved past the acknowledgement — that raises a MOMENT: {pending}")
    check(pending[0]['grants'],
          "and the moment names what is new, out loud")

    res = stages.acknowledge(k['id'], 'navigator')
    check(res['status'] == 'success' and 'Navigator' in res['message'], f"got {res}")
    check(not stages.pending_promotions(),
          "confirmed: the moment is consumed")

    k2 = _kid("Pinned", age=13, stage_override='explorer', stage_acknowledged='explorer')
    check(not any(p['member_id'] == k2['id'] for p in stages.pending_promotions()),
          "a pinned child is never nagged to move — the pin IS the answer")


def scenario_the_watcher_says_so_once_per_transition():
    from services import watchers
    _reset()
    _kid("Lily", age=12, stage_acknowledged='explorer')
    found = watchers._stage_findings(datetime.datetime.now())
    check(len(found) == 1 and 'ready to be a Navigator' in found[0][1],
          f"one line to the parents: {found}")
    key = found[0][0]
    check(key.endswith(':navigator'),
          f"the dedup key is (child, stage) so it fires once per TRANSITION, "
          f"not once per sweep: {key}")


def scenario_nothing_is_deleted_when_a_child_moves_up():
    """The current role-flip behaviour — where growing up erases the evidence
    you were ever six — is the exact opposite of what a family wants."""
    _reset()
    k = _kid("Lily", age=12, stage_acknowledged='explorer')
    storage.points_ledger_table.insert({'member_id': k['id'], 'delta': 25,
                                        'reason': 'chore', 'ts': 1000.0})
    stages.acknowledge(k['id'], 'navigator')
    m = storage.get_member(k['id'])
    check(m['role'] == 'child', "still a child member — the kid lens survives")
    rows = [r for r in storage.points_ledger_table.all()
            if r.get('member_id') == k['id']]
    check(rows and rows[0]['delta'] == 25,
          "the points ledger is untouched — it stops LEADING, it is not erased")
    check(stages.capabilities(m)['show_points'] is False,
          "which is exactly the difference between hiding and deleting")


def scenario_a_sprouts_ask_is_refused_server_side():
    """The gate lives in the service, not the UI — no surface can forget it."""
    from services import requests as reqsvc
    _reset()
    reqsvc._dm = lambda mid, body: None
    sprout = _kid("Rosie", age=4)
    from models.schemas import FamilyMember
    dad = FamilyMember(name="Jeff", role='parent').model_dump()
    storage.add_member(dad)

    res = reqsvc.create(sprout['id'], "can I have a puppy?")
    check(res.get('status') == 'error' and 'grown-up' in res['message'],
          f"a Sprout's wants go through a parent in person: {res}")
    check(not storage.get_requests(),
          "and nothing was stored")

    explorer = _kid("Ellie", age=8)
    res = reqsvc.create(explorer['id'], "can you get me at 3?")
    check(res.get('status') == 'open',
          "an Explorer's ask goes through — asking is a granted capability")


def scenario_the_members_api_carries_the_capabilities():
    """The PWA shell asks for a capability BY NAME — so the payload has to
    carry them, or every surface would be working out ages."""
    import main
    _reset()
    _kid("Lily", age=13)
    out = main.get_members()
    kid = next(m for m in out if m.get('name') == 'Lily')
    check(kid.get('stage') == 'navigator' and isinstance(kid.get('capabilities'), dict),
          f"stage and switch list ride the members payload: {kid.get('stage')}")
    check(kid['capabilities'].get('show_points') is False,
          "and the switches are the resolved ones, overrides applied")


def scenario_household_jobs_arrive_with_navigator():
    """`assignable_tasks` is a real gate, not a declared switch: both agent
    stacks funnel through agent_tools_v2, and the API refuses at the same
    door the errands page hides."""
    from services import agent_tools_v2 as atv2
    _reset()
    storage.household_tasks_table.truncate()
    ellie = _kid("Ellie", age=9)          # Explorer: not yet
    james = _kid("James", age=16)         # Copilot: yes

    res = atv2.add_household_task("Renew the passports", assign_to="Ellie")
    check(res['status'] == 'error' and 'Navigator' in res['message'],
          f"an Explorer is not handed the passport renewal: {res}")
    check(not storage.get_household_tasks(),
          "and nothing was stored")

    res = atv2.add_household_task("Take the bins out", assign_to="James")
    check(res['status'] == 'success',
          f"a Copilot holds real household jobs: {res}")

    atv2.add_household_task("Call the pediatrician")
    res = atv2.claim_household_task("Call the pediatrician", member_name="Ellie")
    check(res['status'] == 'error' and 'Navigator' in res['message'],
          f"the claim door is the same door: {res}")

    ellie['capability_overrides'] = {'assignable_tasks': True}
    storage.update_member(ellie['id'], {'capability_overrides': {'assignable_tasks': True}})
    res = atv2.claim_household_task("Call the pediatrician", member_name="Ellie")
    check(res['status'] == 'success',
          f"a single-switch override opens it without aging her up: {res}")

    # And the API endpoint refuses at the same altitude.
    import main
    from fastapi import HTTPException
    from models.schemas import HouseholdTask
    rosie = _kid("Rosie", age=4)
    try:
        main.create_household_task(HouseholdTask(title="Mow the lawn",
                                                 assigned_to=rosie['id']))
        check(False, "a Sprout assignment should raise")
    except HTTPException as e:
        check('Navigator' in str(e.detail), f"the refusal names the stage: {e.detail}")


def scenario_whereabouts_go_to_the_family_not_the_kiosk():
    """`private_location`: with no viewer (the wall panel, /map) a
    Navigator's zone and pin are withheld and the row says so; any family
    member's own app sees the pin. Driving context survives either way —
    that is the schedule speaking, not the phone."""
    import main
    from services import ha_api
    from models.schemas import FamilyMember
    _reset()
    dad = FamilyMember(name="Jeff", role='parent',
                       ha_person_entity='person.jeff').model_dump()
    storage.add_member(dad)
    lily = _kid("Lily", age=13)           # Navigator: private_location on
    storage.update_member(lily['id'], {'ha_person_entity': 'person.lily'})
    ellie = _kid("Ellie", age=9)          # Explorer: the kiosk may say
    storage.update_member(ellie['id'], {'ha_person_entity': 'person.ellie'})

    real_get_state = ha_api.get_state
    ha_api.get_state = lambda ent: {'state': 'school', 'last_updated': 'now',
                                    'attributes': {'latitude': 39.1, 'longitude': -94.6}}
    try:
        kiosk = {r['name']: r for r in main.family_locations()}
        check(kiosk['Lily'].get('private') and kiosk['Lily']['latitude'] is None
              and kiosk['Lily']['state'] is None,
              f"the kiosk gets a 🔒 row, not a zone word: {kiosk['Lily']}")
        check(kiosk['Ellie']['latitude'] == 39.1,
              "an Explorer's pin still shows — privacy arrives with the stage")
        check(kiosk['Jeff']['latitude'] == 39.1, "adults are untouched")

        family = {r['name']: r for r in main.family_locations(viewer=dad['id'])}
        check(family['Lily']['latitude'] == 39.1 and not family['Lily'].get('private'),
              f"the family sees the pin: {family['Lily']}")

        nobody = {r['name']: r for r in main.family_locations(viewer='not-a-member')}
        check(nobody['Lily'].get('private'),
              "an invented viewer id is a kiosk, not a key")
    finally:
        ha_api.get_state = real_get_state


def scenario_driving_arrives_with_copilot():
    """`can_drive`: a driver named for a child member is that child learning
    to drive. Below Copilot the API refuses; at Copilot the profile is
    created AND the kid lands on the assist tier — covering is not
    carrying."""
    import main
    from fastapi import BackgroundTasks, HTTPException
    from models.schemas import Driver
    _reset()
    storage.drivers_table.truncate()
    ellie = _kid("Ellie", age=9)
    james = _kid("James", age=16)

    try:
        main.create_driver(Driver(id='drv_ellie', name='Ellie', color_code='#fff'),
                           BackgroundTasks())
        check(False, "an Explorer's driving profile should be refused")
    except HTTPException as e:
        check('Copilot' in str(e.detail), f"the refusal names the stage: {e.detail}")
    check(not storage.get_all_drivers(), "and no driver record exists")

    main.create_driver(Driver(id='drv_james', name='James', color_code='#fff'),
                       BackgroundTasks())
    check(len(storage.get_all_drivers()) == 1, "a Copilot's profile is created")
    m = storage.get_member(james['id'])
    check(m.get('assist_tier') == 'assist',
          "and he COVERS drives without CARRYING the household's share — "
          "his drives stay out of the adults' ledger")

    grandma = main.create_driver(Driver(id='drv_gma', name='Grandma', color_code='#fff'),
                                 BackgroundTasks())
    check(grandma['status'] == 'created',
          "a name matching no member is none of this gate's business")


def scenario_the_hand_path_exists():
    import os
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    config = open(os.path.join(tpl, 'config.html'), encoding='utf-8').read()
    check('acknowledgeStage' in config and 'memberEdit.birthdate' in config
          and 'pinStage' in config and 'saveStageCutoffs' in config,
          "birthdays (on the identity card), pins, cutoffs and the confirmation "
          "moment all work by hand")
    check('startCutoffDrag' in config and 'stageKidMarkers' in config,
          "the cutoff timeline is draggable and shows the kids on it")
    check('Nothing is ever deleted' in config,
          "and the promise is written where the parent makes the decision")
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('kidCan(' in app and 'kidHorizonDays' in app,
          "the PWA shell asks for capabilities by name")
    check('glyph_scale' in app and 'kidShell(' in app,
          "the shell reads glyph scale and density — a Sprout's picture book "
          "and a Copilot's plain schedule are the same template")
    errands = open(os.path.join(tpl, 'errands.html'), encoding='utf-8').read()
    check('assignable_tasks' in errands,
          "the task owner dropdown opens to stage-capable kids by hand")
    check("(member.capabilities || {}).can_drive" in config,
          "and '+ Driving' appears on a Copilot kid's row by hand")
    fmap = open(os.path.join(tpl, 'components', 'family_map_core.html'),
                encoding='utf-8').read()
    check('loc.private' in fmap and 'viewer=' in fmap,
          "the map sends who is looking and renders the 🔒 chip")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} stage scenarios passed")
