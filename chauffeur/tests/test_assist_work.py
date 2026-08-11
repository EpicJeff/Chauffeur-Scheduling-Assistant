"""Outside hands hold work (load arc A1 slice 2).

The arc shipped the noun and one of its two verbs. A contact could be given a
DRIVE — except the only door was dragging onto a column drawn from existing
coverage, so the first hand-over was unreachable — and could not be given
housework at all. The story this pins down:

  **An outside hand can hold any unit of work the household hands over, and
  holding it never counts as the household carrying it.**

Load-bearing properties:

  1. **"Helps with" narrows a list; it never refuses.** Hiding somebody takes
     positive information — untagged and oddly-tagged contacts are offered
     everywhere, so nobody silently becomes unusable, and a new kind of help
     ("tutoring") still needs no code.
  2. **Both hand-over surfaces are REACHABLE by hand**, not merely present in
     the source. This is the property the old test missed.
  3. **Covering is not carrying**: a contact's finished task shows on the
     assisting side of the load ledger, never in the household's split.
  4. **Chores stay members-only, deliberately** — a paid helper must not earn
     points on the kids' ladder.

Run from chauffeur/:  python tests/test_assist_work.py
"""
import datetime
import os
import re

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import assist, storage

TPL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'templates')


def _reset():
    with storage.db_lock:
        storage.assist_contacts_table.truncate()
        storage.household_tasks_table.truncate()
        storage.members_table.truncate()


def _contact(name, kinds=None, **kw):
    from models.schemas import AssistContact
    c = AssistContact(name=name, kinds=kinds or [], **kw).model_dump()
    storage.add_assist_contact(c)
    return c


def scenario_helps_with_narrows_a_list_and_never_refuses():
    """The 13-year-old who does the dishes must not be offered as a driver —
    but a contact nobody has tagged must not vanish from every list either."""
    driver = {'kinds': ['carpool']}
    cleaner = {'kinds': ['housework']}
    both = {'kinds': ['carpool', 'housework']}
    untagged = {'kinds': []}
    tutor = {'kinds': ['tutoring']}

    check(assist.offers(driver, 'driving') and not assist.offers(driver, 'housework'),
          "a carpool parent is offered for drives only")
    check(assist.offers(cleaner, 'housework') and not assist.offers(cleaner, 'driving'),
          "the dishes helper is never offered as a driver")
    check(assist.offers(both, 'driving') and assist.offers(both, 'housework'),
          "somebody who does both is offered for both")
    check(assist.offers(untagged, 'driving') and assist.offers(untagged, 'housework'),
          "UNTAGGED is offered everywhere — hiding takes positive information, "
          "so a contact nobody has labelled never becomes unusable")
    check(assist.offers(tutor, 'driving') and assist.offers(tutor, 'housework'),
          "and an unrecognised kind of help says nothing about these two, so it "
          "costs nobody their place — a new kind of help still needs no code")
    check(assist.helps_with(driver) == ['driving'],
          f"'carpool' normalises to driving without a migration: {assist.helps_with(driver)}")
    check(assist.other_kinds({'kinds': ['carpool', 'tutoring']}) == ['tutoring'],
          "the free tags survive the split, so editing never drops 'tutoring'")


def scenario_the_filter_is_not_a_gate():
    """The server accepts any contact for any work. The tags shape a picker;
    the family knows things the tags do not."""
    import main
    from fastapi import BackgroundTasks
    _reset()
    cleaner = _contact("Maddie", kinds=['housework'])
    storage.set_cached_schedule({'events': [{'id': 'ev1', 'title': 'Practice'}]})

    res = main.set_assist_coverage(
        main.AssistCoverageRequest(event_id='ev1', contact_id=cleaner['id']),
        BackgroundTasks())
    check(res['status'] == 'success',
          f"a housework-tagged contact can still be given a drive if the family "
          f"says so — the tag shapes the list, not the rules: {res}")


def scenario_both_hand_overs_are_reachable():
    """The property the old hand-path test missed: it asserted that
    `setAssistCoverage` EXISTED, which a dead function satisfies. Coverage's
    only door was dropping onto a column built from `assist_assignments` — so
    a drive with no coverage had no column, and the first hand-over could not
    be made by hand at all."""
    dash = open(os.path.join(TPL, 'dashboard.html'), encoding='utf-8').read()
    check('edit-assist-contact' in dash and 'populateAssistDropdown' in dash,
          "the event editor carries a 'hand to' picker")
    # Reachability: the picker is filled from the contact list, NOT from the
    # existing assignments — otherwise it is the same deadlock in a new shape.
    fill = dash.split('function populateAssistDropdown', 1)[1].split('function ', 1)[0]
    check('assistContactsFor' in fill,
          "and it is filled from the CONTACTS, so an uncovered drive still "
          "offers everyone who drives")
    check('setAssistCoverage' in fill,
          "choosing one hands the drive over")

    errands = open(os.path.join(TPL, 'errands.html'), encoding='utf-8').read()
    check('taskHands' in errands and 'Outside hands' in errands,
          "the task owner dropdown offers outside hands by hand")
    check("assist:" in errands,
          "and hands them the task under the prefixed id the server reads")

    config = open(os.path.join(TPL, 'config.html'), encoding='utf-8').read()
    check('toggleAssistSurface' in config and 'helps_with' in config,
          "'helps with' is set by pills on the contact, by hand")


def scenario_a_contact_can_hold_a_task_and_it_is_covering_not_carrying():
    import main
    _reset()
    from models.schemas import FamilyMember, HouseholdTask
    mom = FamilyMember(name="Lorena", role='parent').model_dump()
    storage.add_member(mom)
    girl = _contact("Maddie", kinds=['housework'], relation_label="the Kellys' girl")

    held = HouseholdTask(title="Do the dishes",
                         assigned_to=assist.make_id(girl['id'])).model_dump()
    storage.add_household_task(held)
    mine = HouseholdTask(title="Renew the passports", assigned_to=mom['id']).model_dump()
    storage.add_household_task(mine)

    rows = {t['title']: t for t in main.list_household_tasks()}
    check(rows["Do the dishes"]['assigned_to_name'] == 'Maddie'
          and rows["Do the dishes"]['assigned_to_assist'] is True,
          f"an outside hand reads as their NAME, never 'nobody yet': {rows['Do the dishes']}")
    check(rows["Renew the passports"]['assigned_to_assist'] is False,
          "and a member's task is unchanged")

    now = datetime.datetime.now().timestamp()
    storage.update_household_task(held['id'], {'status': 'done', 'completed_at': now})
    storage.update_household_task(mine['id'], {'status': 'done', 'completed_at': now})
    load = main.household_load(days=30)
    house = {r['name'] for r in load['household']}
    assisting = {r['name'] for r in load['assisting']}
    check('Maddie' in assisting and 'Maddie' not in house,
          f"covering is not carrying — she is visible, and not in the family's "
          f"split: household={house} assisting={assisting}")
    check('Lorena' in house, "the parent's own task still counts as carried")


def scenario_the_agent_can_hand_housework_over_too():
    from services import agent_tools_v2 as atv2
    from models.schemas import HouseholdTask
    _reset()
    girl = _contact("Maddie", kinds=['housework'])
    storage.add_household_task(HouseholdTask(title="Do the dishes").model_dump())

    res = atv2.claim_household_task("dishes", member_name="Maddie")
    check(res['status'] == 'success' and 'Maddie' in res['message'],
          f"a name that is nobody in the family is tried against the contacts: {res}")
    t = storage.get_household_tasks()[0]
    check(t['assigned_to'] == assist.make_id(girl['id']),
          f"stored under the prefixed id: {t['assigned_to']}")

    res = atv2.claim_household_task("dishes", member_name="Nobody At All")
    check(res['status'] == 'error' and "couldn't find" in res['message'],
          f"and a name that is nobody anywhere is still refused: {res}")


def scenario_an_outside_hand_claims_a_chore_like_any_adult():
    """Recurring housework — dishes, vacuuming — is a CHORE, and an outside
    hand is not a new concept in it: an adult already claims a chore and earns
    nothing (`verify_chore` awards points only to a child), so a contact is
    the same shape. They widen the id space and change no rule.

    (An earlier version of this file asserted chores were members-only. That
    was wrong twice over: the points argument was already handled by the
    role check, and household tasks could not hold the work anyway — their
    recurrence needs a due date, which dishes do not have.)"""
    import main
    from fastapi import BackgroundTasks
    from models.schemas import Chore, FamilyMember
    _reset()
    with storage.db_lock:
        storage.chores_table.truncate()
        storage.points_ledger_table.truncate()
    kid = FamilyMember(name="Ellie", role='child').model_dump()
    storage.add_member(kid)
    mom = FamilyMember(name="Lorena", role='parent').model_dump()
    storage.add_member(mom)
    girl = _contact("Maddie", kinds=['housework'])
    hand_id = assist.make_id(girl['id'])

    created = main.create_chore(main.ChoreCreateRequest(
        title="Deep clean the kitchen", recurrence='weekly', points=10,
        owner=hand_id), BackgroundTasks())
    chore = storage.get_chore(created['id'])
    check(chore['state'] == 'claimed' and chore['claimed_by'] == hand_id,
          f"owning IS holding it — it never sits in the pot: {chore['state']}")

    # The kids' pot never shows it, because it is not open at all.
    from fastapi import HTTPException
    try:
        main.claim_chore_endpoint(chore['id'], main.ChoreMemberRequest(member_id=kid['id']))
        check(False, "a kid must not be able to take somebody's owned chore")
    except HTTPException as e:
        check(e.status_code == 409, f"owned work is not claimable: {e.detail}")

    # One tap records it: a contact has no login, so claim->done cannot be
    # walked by them. That is the ONLY way outside help differs from a kid.
    rec = main.record_chore_endpoint(chore['id'],
                                     main.ChoreMemberRequest(member_id=hand_id),
                                     BackgroundTasks())
    check(rec['state'] == 'done' and rec['claimed_by'] == hand_id,
          f"recorded as hers, awaiting the usual verification: {rec['state']}")
    rows = {c['title']: c for c in main.list_chores()}
    row = rows["Deep clean the kitchen"]
    check(row['claimed_by_name'] == 'Maddie' and row['claimed_by_assist'] is True,
          f"and she is NAMED, not blank: {row}")
    check(row['owner_name'] == 'Maddie', f"the owner resolves too: {row['owner_name']}")

    res = storage.verify_chore(chore['id'], mom['id'])
    check(res and res['awarded'] == 0,
          f"she earns nothing — exactly what an adult claiming a chore earns: {res}")
    check(not storage.points_ledger_table.all(),
          "so the kids' points economy is untouched")

    # The differentiator that sent us here: a chore recurs with NO deadline.
    check(res['chore']['reopens_on'],
          f"and it comes back tomorrow on its own: {res['chore'].get('reopens_on')}")
    check(storage._next_due(None, 'daily') is None,
          "whereas a household task's recurrence needs a due date — which is "
          "why dishes never fitted there, and why a chore is the right home")

    # An OWNED chore comes back to its owner: that is the arrangement.
    with storage.db_lock:
        storage.chores_table.update({'reopens_on': '2000-01-01'},
                                    storage.Query().id == chore['id'])
    # get_all_chores() is what runs _chore_maintenance — the reopen sweep.
    back = next(c for c in storage.get_all_chores() if c['id'] == chore['id'])
    check(back['state'] == 'claimed' and back['claimed_by'] == hand_id,
          f"the recurrence returns it to its owner: {back['state']}/{back.get('claimed_by')}")


def scenario_daily_work_stays_in_the_pot_and_is_assigned_per_night():
    """The case that forced the split. The dishes have to be done every day,
    and the helper is only in two or three days a week — so she cannot OWN
    them, or they would come back to her on the days she is not there. They
    stay ownerless in the pot, and a parent hands out one night's."""
    import main
    from fastapi import BackgroundTasks, HTTPException
    from models.schemas import FamilyMember
    _reset()
    with storage.db_lock:
        storage.chores_table.truncate()
    mom = FamilyMember(name="Lorena", role='parent').model_dump()
    storage.add_member(mom)
    kid = FamilyMember(name="Ellie", role='child').model_dump()
    storage.add_member(kid)
    girl = _contact("Maddie", kinds=['housework'])
    hand_id = assist.make_id(girl['id'])

    created = main.create_chore(main.ChoreCreateRequest(
        title="Do the dishes", recurrence='daily', points=5), BackgroundTasks())
    chore = storage.get_chore(created['id'])
    check(chore['state'] == 'open' and not chore.get('owner'),
          "daily work nobody owns sits in the pot")

    # Monday: she is in, so tonight's is hers.
    main.assign_chore_endpoint(chore['id'], main.ChoreAssignRequest(
        member_id=hand_id, assigned_by=mom['id']))
    c = storage.get_chore(chore['id'])
    check(c['claimed_by'] == hand_id and c['assigned_by'] == mom['id'],
          f"assigned for tonight, and it is recorded WHO decided: {c.get('assigned_by')}")
    check(not c.get('owner'), "without becoming her permanent job")

    # A parent's decision is not the holder's to undo.
    check(not storage.unclaim_chore(chore['id'], hand_id),
          "the holder cannot hand back work they were given")

    # She has no login, so a parent marks it done; verification reopens it.
    main.record_chore_endpoint(chore['id'], main.ChoreMemberRequest(member_id=hand_id),
                               BackgroundTasks())
    storage.verify_chore(chore['id'], mom['id'])
    with storage.db_lock:
        storage.chores_table.update({'reopens_on': '2000-01-01'},
                                    storage.Query().id == chore['id'])
    back = next(c for c in storage.get_all_chores() if c['id'] == chore['id'])
    check(back['state'] == 'open' and not back.get('claimed_by')
          and not back.get('assigned_by'),
          f"and TOMORROW it is back in the pot, not handed to somebody who is "
          f"not there: {back['state']}/{back.get('claimed_by')}")

    # Tuesday: Ellie takes it herself, and earns for it.
    main.claim_chore_endpoint(chore['id'], main.ChoreMemberRequest(member_id=kid['id']))
    check(storage.unclaim_chore(chore['id'], kid['id']),
          "work she CHOSE is hers to put back — the difference the stamp records")

    # An owned chore is not assignable: that arrangement changes in the editor.
    owned = main.create_chore(main.ChoreCreateRequest(
        title="Mow the lawn", recurrence='weekly', owner=kid['id']), BackgroundTasks())
    try:
        main.assign_chore_endpoint(owned['id'], main.ChoreAssignRequest(
            member_id=mom['id'], assigned_by=mom['id']))
        check(False, "an owned chore must not be assignable out from under its owner")
    except HTTPException as e:
        check(e.status_code == 409, f"owned work is changed in the editor: {e.detail}")


def scenario_a_kid_can_own_a_chore():
    """"My son mows the lawn every week. I don't want to assign it to him
    every week and it doesn't need to be up for grabs because no one else
    can/will do it." A kid marks their own owned work done — only outside
    help needs a parent for that, because they have no login — and it still
    earns points, because he is still a child doing a chore."""
    import main
    from fastapi import BackgroundTasks
    from models.schemas import FamilyMember
    _reset()
    with storage.db_lock:
        storage.chores_table.truncate()
        storage.points_ledger_table.truncate()
    kid = FamilyMember(name="Ellie", role='child').model_dump()
    storage.add_member(kid)
    mom = FamilyMember(name="Lorena", role='parent').model_dump()
    storage.add_member(mom)

    created = main.create_chore(main.ChoreCreateRequest(
        title="Mow the lawn", points=10, recurrence='weekly', owner=kid['id']),
        BackgroundTasks())
    chore = storage.get_chore(created['id'])
    check(chore['owner'] == kid['id'] and chore['claimed_by'] == kid['id'],
          "an owned chore is his from the moment the arrangement is made")
    check(storage.mark_chore_done(chore['id'], kid['id']),
          "and HE marks it done — no parent needed, unlike outside help")
    res = storage.verify_chore(chore['id'], mom['id'])
    check(res['awarded'] == 10,
          f"a child still earns points for work he owns: {res['awarded']}")

    # Clearing the owner puts it back up for grabs.
    main.edit_chore(chore['id'], main.ChoreCreateRequest(
        title="Mow the lawn", points=10, recurrence='weekly', owner=None))
    check(storage.get_chore(chore['id'])['state'] == 'open',
          "removing the owner returns it to the pot")


def scenario_the_chore_hand_path_is_reachable():
    chores_ui = open(os.path.join(TPL, 'chores.html'), encoding='utf-8').read()
    check('choreEdit.owner' in chores_ui and "'assist:' + h.id" in chores_ui,
          "an owner is set by hand in the editor, member or outside hand")
    check('recordChoreFor' in chores_ui and 'did it' in chores_ui,
          "and one tap records that outside help did it, since they cannot "
          "mark it themselves")
    app = open(os.path.join(TPL, 'app.html'), encoding='utf-8').read()
    check('openAssignChore' in app and 'Assign' in app,
          "and tonight's occurrence is handed out with a button beside Claim")
    check("isParent && !c.owner" in app,
          "parent-only, and never on a chore somebody owns")
    cc = open(os.path.join(TPL, 'components', 'control_center.html'), encoding='utf-8').read()
    check('promptChoice' in cc,
          "the person picker is a shared modal, not a browser dialog")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} outside-hands-work scenarios passed")
