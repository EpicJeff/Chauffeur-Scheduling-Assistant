"""Household tasks — work with a deadline and no destination (load arc A2).

The keystone object. Load-bearing properties:

  1. **Task = do something. Errand = go somewhere.** An errand requires a
     location because it IS a drive the solver routes; keeping the line crisp
     is what stops "renew the passports" competing for a Tuesday slot.
  2. **Unassigned is a real state** meaning the household owes it. That is
     where delegation lives — and the moment it stops being fine is when the
     date arrives with nobody's name on it, which the watcher says out loud.
  3. **Yearly recurrence**, which errands cannot express and which is exactly
     the life-admin cadence: inspection, physicals, passports, registration.
  4. **The ledger states, never scores** — and assist-tier members are named
     separately, because covering is not carrying.

Run from chauffeur/:  python tests/test_household_tasks.py
"""
import datetime

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()


def _reset():
    for t in (storage.household_tasks_table, storage.members_table):
        t.truncate()


def _task(title="Sign the permission slip", **kw):
    from models.schemas import HouseholdTask
    row = HouseholdTask(title=title, **kw).model_dump()
    storage.add_household_task(row)
    return row


def _member(name, role='adult', **kw):
    from models.schemas import FamilyMember
    m = FamilyMember(name=name, role=role, **kw).model_dump()
    storage.add_member(m)
    return m


def scenario_a_task_needs_no_destination():
    """The whole reason the object exists: `Errand` demands `location` and
    `duration_mins`, so work with a deadline and nowhere to drive had no home
    anywhere in the app."""
    _reset()
    t = _task("Renew the passports", due_date=(TODAY + datetime.timedelta(days=40)).isoformat())
    got = storage.get_household_task(t['id'])
    check(got is not None, "it stores")
    check('location' not in got and 'duration_mins' not in got,
          "and it carries no destination — that is what makes it not an errand")
    check(got['assigned_to'] is None,
          "unassigned by default: the household owes it until somebody takes it")


def scenario_an_undated_task_is_real_and_never_late():
    """"Sort the garage" is work. It is not a deadline, and inventing one
    would put a false due date in front of the family."""
    _reset()
    _task("Sort the garage")
    _task("Call the dentist", due_date=TODAY.isoformat())
    rows = storage.get_household_tasks()
    check([r['title'] for r in rows] == ["Call the dentist", "Sort the garage"],
          f"dated work sorts first, undated after — never above: {[r['title'] for r in rows]}")

    from services import watchers
    found = watchers._household_task_findings(datetime.datetime.now())
    check(not any('garage' in msg.lower() for _, msg in found),
          "and an undated task is never chased as late")


def scenario_the_household_owing_something_is_said_out_loud():
    """Unassigned is fine until the date arrives with nobody's name on it."""
    from services import watchers
    _reset()
    now = datetime.datetime.now()
    _task("Permission slip", due_date=(TODAY + datetime.timedelta(days=1)).isoformat())
    _task("Book the MOT", due_date=(TODAY + datetime.timedelta(days=30)).isoformat())
    m = _member("Jeff")
    _task("Pay the deposit", due_date=(TODAY + datetime.timedelta(days=1)).isoformat(),
          assigned_to=m['id'])

    msgs = " | ".join(msg for _, msg in watchers._household_task_findings(now))
    check('Permission slip' in msgs,
          f"due tomorrow with nobody on it must be said: {msgs}")
    check('Book the MOT' not in msgs,
          "but a month out is not yet a problem")
    check('Pay the deposit' not in msgs,
          "and work with a name on it is not unclaimed")


def scenario_past_due_is_its_own_finding():
    from services import watchers
    _reset()
    _task("Send the form", due_date=(TODAY - datetime.timedelta(days=3)).isoformat())
    msgs = [msg for _, msg in watchers._household_task_findings(datetime.datetime.now())]
    check(any('Past due' in m and '3 days ago' in m for m in msgs),
          f"it says how late, not just that it is late: {msgs}")


def scenario_yearly_recurrence_is_the_point():
    """Errands offer daily/weekly/monthly. Annual is exactly the life-admin
    cadence, and it is why this object needed its own recurrence."""
    _reset()
    t = _task("Car inspection", due_date=f"{TODAY.year}-03-14", recurrence='yearly')
    row = storage.complete_household_task(t['id'], True)
    check(row['next_due_date'] == f"{TODAY.year + 1}-03-14",
          f"completing opens next year's, got {row.get('next_due_date')}")
    check(len(storage.get_household_tasks()) == 1,
          "exactly one open task remains — regenerate on completion, never a series")
    check(storage.get_household_task(t['id'])['status'] == 'done',
          "and this year's is closed")


def scenario_recurrence_edges_do_not_crash():
    _reset()
    check(storage._next_due('2026-01-31', 'monthly') == '2026-02-28',
          "the 31st of a 30-day month clamps rather than raising")
    check(storage._next_due('2024-02-29', 'yearly') == '2025-02-28',
          "29 Feb into a common year clamps too")
    check(storage._next_due(None, 'yearly') is None, "no date, no next one")
    check(storage._next_due('2026-01-01', 'none') is None, "and none means none")


def scenario_delegation_is_just_putting_a_name_on_it():
    from services import agent_tools_v2
    _reset()
    jeff = _member("Jeff")
    _member("Lorena")
    _task("Call the pediatrician", due_date=TODAY.isoformat())

    res = agent_tools_v2.claim_household_task("pediatrician", member_name="Lorena")
    check(res['status'] == 'success' and 'Lorena' in res['message'], f"got {res}")
    check(storage.get_household_tasks()[0]['assigned_to'] != jeff['id'],
          "it went to the person named, not the speaker")

    res = agent_tools_v2.get_household_tasks(assigned_to="Lorena")
    check('pediatrician' in res['message'], f"and it reads back on her list: {res}")

    res = agent_tools_v2.claim_household_task("pediatrician", member_name="Nobody Real")
    check(res['status'] == 'error' and 'Family members' in res['message'],
          "an unknown name lists the real roster rather than guessing")


def scenario_the_agent_can_add_read_and_finish():
    from services import agent_tools_v2
    _reset()
    _member("Jeff")
    res = agent_tools_v2.add_household_task("Sign the permission slip", due="tomorrow")
    check(res['status'] == 'success', f"got {res}")
    rows = storage.get_household_tasks()
    check(len(rows) == 1 and rows[0]['due_date'] ==
          (TODAY + datetime.timedelta(days=1)).isoformat(),
          f"a spoken deadline becomes a date: {rows}")
    check(rows[0]['assigned_to'] is None,
          "and nobody is volunteered by the act of writing it down")

    res = agent_tools_v2.get_household_tasks(unassigned_only=True)
    check('permission slip' in res['message'].lower(), f"got {res}")

    res = agent_tools_v2.complete_household_task("permission")
    check(res['status'] == 'success', f"got {res}")
    check(not storage.get_household_tasks(), "and it leaves the open list")

    res = agent_tools_v2.add_household_task("Sort the garage")
    check(res['status'] == 'success' and storage.get_household_tasks()[0]['due_date'] is None,
          "a task with no deadline stays undated rather than inventing one")


def scenario_the_ledger_states_and_never_scores():
    """No percentages, no leaderboard, no chart. And covering is not
    carrying: an assist-tier member is named separately, never folded into
    the household's split."""
    import main
    _reset()
    jeff = _member("Jeff", role='parent')
    lor = _member("Lorena", role='parent')
    teen = _member("James", role='child', assist_tier='assist')

    import time as _t
    for i in range(7):
        _task(f"job{i}", assigned_to=lor['id'], status='done', completed_at=_t.time())
    for i in range(2):
        _task(f"jobj{i}", assigned_to=jeff['id'], status='done', completed_at=_t.time())
    for i in range(5):
        _task(f"jobt{i}", assigned_to=teen['id'], status='done', completed_at=_t.time())

    data = main.household_load(days=30)
    names = [r['name'] for r in data['household']]
    check(set(names) == {'Jeff', 'Lorena'},
          f"the split is the household's; the teenager is not in it: {names}")
    check([r['name'] for r in data['assisting']] == ['James'],
          "he is named separately — he covers work, he does not carry the load")
    check(data['line'] and '7 of the 9' in data['line'],
          f"one sentence that counts and names: {data.get('line')!r}")
    check('%' not in (data['line'] or '') and 'more than' not in (data['line'] or ''),
          "and never scores, ranks, or compares")


def scenario_intake_finally_has_somewhere_to_put_a_permission_slip():
    """The capture layer's extraction prompt already names 'permission slip
    due, payment due, picture day'. Until this target existed they fitted
    nowhere: not a calendar event, not an errand (which demands a location),
    not a kid task (a child's own school list)."""
    import inspect
    import main
    src = inspect.getsource(main.approve_proposal) if hasattr(main, 'approve_proposal') else ''
    if not src:
        src = open(main.__file__, encoding='utf-8').read()
    check("== 'household_task'" in src,
          "the approval router accepts a household_task target")
    check('storage.add_household_task' in src,
          "and lands the proposal on the household list")


def scenario_every_agent_capability_has_a_hand_path():
    import os
    import re
    from services import agent_tools_v2
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    for t in ('add_household_task', 'get_household_tasks', 'complete_household_task',
              'claim_household_task', 'get_household_load'):
        check(t in names, f"{t} is offered to the model")
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    errands = open(os.path.join(tpl, 'errands.html'), encoding='utf-8').read()
    check('addHouseholdTask' in errands and 'openTaskEditor' in errands
          and 'saveTaskEdit' in errands and 'completeTask' in errands,
          "adding, editing/assigning and finishing all work by hand on the "
          "errands page")
    # Assigning is an EDIT of the task, not a side effect of the create form.
    # The old claimTask() read the new-task owner dropdown when you clicked
    # "nobody yet" on a row, so two unrelated-looking controls were coupled.
    check('function claimTask' not in errands,
          "and assigning never again reads the create form's dropdown")
    check(re.search(r"openTaskEditor\([^)]*\)[^>]*>\s*nobody yet", errands),
          "'nobody yet' opens that same editor rather than acting invisibly")
    # Template copy wraps across lines, so compare on collapsed whitespace —
    # a raw substring check on prose is a test that breaks on reformatting.
    flat = re.sub(r'\s+', ' ', errands)
    check('is a drive' in flat and 'nowhere to drive' in flat,
          "and the page teaches the distinction the object depends on: an "
          "errand is a drive, a task is work with nowhere to drive")


def scenario_the_wall_says_what_nobody_has_taken():
    from services import home_board
    _reset()
    m = _member("Jeff")
    _task("Permission slip", due_date=(TODAY + datetime.timedelta(days=2)).isoformat())
    _task("Pay deposit", due_date=(TODAY - datetime.timedelta(days=1)).isoformat(),
          assigned_to=m['id'])
    tile = home_board._tile_tasks(datetime.datetime.now())
    check(tile and tile['tasks'][0]['title'] == 'Pay deposit',
          f"past due leads, as on every other surface: {tile}")
    check(tile['unclaimed'] == 1, "and the count of work nobody has is carried")
    check(tile['tasks'][1]['unclaimed'] is True and tile['tasks'][1]['who'] is None,
          "'nobody yet' is a state the tile can render, not a blank")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} household-task scenarios passed")
