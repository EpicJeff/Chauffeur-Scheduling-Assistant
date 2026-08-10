"""Requests — the ask as a first-class object (load arc A3).

Load-bearing properties:

  1. **A request is always answered.** Silence is the failure mode this exists
     to fix, so an unanswered ask expires LOUDLY — to the asker, who otherwise
     learns nothing, and to whoever owed the answer.
  2. **Accepting performs the change.** The request IS the mechanism, not a
     note about one.
  3. **Declining is first-class and blameless.** A no with a reason beats
     silence, so `reason` lives on the object.
  4. **One object for kid→parent and adult→adult**, because the state machine
     and the rails are identical.
  5. **An unaddressed ask belongs to every adult** — "somebody please take
     this" must not sit in nobody's list.

Run from chauffeur/:  python tests/test_requests.py
"""
from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import requests as reqsvc, storage

_SENT = []


def _reset():
    for t in (storage.requests_table, storage.members_table,
              storage.household_tasks_table, storage.overrides_table):
        t.truncate()
    _SENT.clear()
    # Capture DMs instead of firing the real chat fan-out.
    reqsvc._dm = lambda mid, body: _SENT.append((mid, body))


def _member(name, role='adult', **kw):
    from models.schemas import FamilyMember
    m = FamilyMember(name=name, role=role, **kw).model_dump()
    storage.add_member(m)
    return m


def scenario_a_kid_can_ask_not_only_report():
    """The single most common kid-to-parent logistics message in existence —
    "can you get me at 3 instead of 4" — had no object at all. Kid-as-sensor
    handles FACTS; this handles WANTS."""
    _reset()
    kid = _member("Lily", role='child')
    mum = _member("Lorena", role='parent')
    dad = _member("Jeff", role='parent')

    r = reqsvc.create(kid['id'], "can you get me at 3 instead of 4?",
                      kind='pickup_early')
    check(r['status'] == 'open' and r['from_member'] == kid['id'], f"got {r}")
    told = {mid for mid, _ in _SENT}
    check(told == {mum['id'], dad['id']},
          "an unaddressed ask reaches every adult — it must not sit in nobody's list")
    check(kid['id'] not in told, "and never bounces back to the asker")
    check(any('asking' in body and 'get me at 3' in body for _, body in _SENT),
          f"in the child's own words: {_SENT}")


def scenario_accepting_performs_the_change():
    """The request IS the mechanism. Accepting a task hand-off assigns the
    task; accepting a drive swap writes the override and re-solves."""
    _reset()
    mum = _member("Lorena", role='parent')
    dad = _member("Jeff", role='parent', driver_id='drv_jeff')

    from models.schemas import HouseholdTask
    task = HouseholdTask(title="Call the pediatrician").model_dump()
    storage.add_household_task(task)

    r = reqsvc.create(mum['id'], "can you take the pediatrician call?",
                      kind='take_task', to_member_id=dad['id'],
                      subject_ref=task['id'], subject_label=task['title'])
    res = reqsvc.decide(r['id'], True, dad['id'])
    check(res['status'] == 'success', f"got {res}")
    check(storage.get_household_task(task['id'])['assigned_to'] == dad['id'],
          "saying yes actually put it on his list")

    r2 = reqsvc.create(mum['id'], "can you take the 4pm run?", kind='swap_drive',
                       to_member_id=dad['id'], subject_ref='ev_soccer')
    res2 = reqsvc.decide(r2['id'], True, dad['id'])
    check(res2.get('schedule_dirty'), "a drive swap must re-solve the day")
    check(any(o.get('event_id') == 'ev_soccer' and o.get('driver_id') == 'drv_jeff'
              for o in storage.get_all_overrides()),
          "and the drive is actually his now")


def scenario_a_kind_that_names_nothing_performs_nothing():
    """A `permission` or a bare `other` is a conversation. Inventing an action
    for it would be the app guessing at what a family meant."""
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent', driver_id='d1')
    r = reqsvc.create(kid['id'], "can I stay late at Emma's?", kind='permission')
    reqsvc.decide(r['id'], True, dad['id'])
    check(not storage.get_all_overrides(), "nothing was invented")
    check(storage.get_request(r['id'])['status'] == 'accepted',
          "but the answer is recorded — yes is still an answer")


def scenario_declining_is_first_class_and_blameless():
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent')
    r = reqsvc.create(kid['id'], "can you get me at 3?")
    _SENT.clear()
    res = reqsvc.decide(r['id'], False, dad['id'], reason="I'm in a meeting until 5")
    check(res['status'] == 'success', f"got {res}")
    row = storage.get_request(r['id'])
    check(row['status'] == 'declined' and 'meeting' in row['reason'],
          "the reason lives on the object, not lost in a chat message")
    back = [b for mid, b in _SENT if mid == kid['id']]
    check(back and 'meeting until 5' in back[0],
          f"and the asker is TOLD why — a no with a reason beats silence: {back}")
    check(back and 'can' in back[0].lower(),
          "worded as an answer, not a rejection")


def scenario_an_unanswered_ask_expires_loudly():
    """The whole point. An ask that quietly evaporates is the failure this
    object exists to prevent."""
    import time
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent')
    r = reqsvc.create(kid['id'], "can somebody bring my cleats?")
    storage.update_request(r['id'], {'expires_at': time.time() - 1})
    _SENT.clear()

    n = reqsvc.sweep()
    check(n == 1, f"one expired, got {n}")
    check(storage.get_request(r['id'])['status'] == 'expired', "and is marked so")
    to_kid = [b for mid, b in _SENT if mid == kid['id']]
    to_dad = [b for mid, b in _SENT if mid == dad['id']]
    check(to_kid and 'Nobody got back to you' in to_kid[0],
          f"the asker learns it went unanswered: {to_kid}")
    check(to_dad and 'unanswered' in to_dad[0],
          f"and so does whoever owed the answer: {to_dad}")

    check(reqsvc.sweep() == 0, "and it only says so once")


def scenario_an_answered_request_cannot_be_answered_twice():
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent')
    mum = _member("Lorena", role='parent')
    r = reqsvc.create(kid['id'], "can you get me at 3?")
    reqsvc.decide(r['id'], True, dad['id'])
    res = reqsvc.decide(r['id'], False, mum['id'])
    check(res['status'] == 'error' and 'accepted' in res['message'],
          f"the second answer is refused and says why, got {res}")


def scenario_only_the_asker_can_withdraw():
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent')
    r = reqsvc.create(kid['id'], "can you get me at 3?")
    check(reqsvc.cancel(r['id'], dad['id'])['status'] == 'error',
          "somebody else cannot withdraw your ask")
    check(reqsvc.cancel(r['id'], kid['id'])['status'] == 'success',
          "but you can take back your own")


def scenario_the_summary_shows_both_directions():
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent')
    reqsvc.create(kid['id'], "can you get me at 3?")
    reqsvc.create(dad['id'], "can you feed the dog?", to_member_id=kid['id'])

    dad_view = reqsvc.summary_for(dad['id'])
    check(len(dad_view['waiting_on_me']) == 1 and len(dad_view['mine']) == 1,
          f"an adult sees what is owed and what they are waiting on: {dad_view}")
    kid_view = reqsvc.summary_for(kid['id'])
    check(len(kid_view['waiting_on_me']) == 1 and len(kid_view['mine']) == 1,
          f"and so does the child — same rails, same object: {kid_view}")


def scenario_the_agent_can_ask_and_answer():
    from services import agent_tools_v2
    _reset()
    kid = _member("Lily", role='child')
    dad = _member("Jeff", role='parent')

    res = agent_tools_v2.make_request("can you get me at 3 instead of 4?",
                                      acting_member=kid)
    check(res['status'] == 'success' and 'answer' in res['message'],
          f"the reply promises an answer, never the answer itself: {res}")

    res = agent_tools_v2.get_requests(acting_member=dad)
    check('Lily is asking' in res['message'], f"got {res}")

    res = agent_tools_v2.answer_request(False, reason="I'm in a meeting", acting_member=dad)
    check(res['status'] == 'success' and 'meeting' in res['message'], f"got {res}")

    res = agent_tools_v2.get_requests(acting_member=dad)
    check('Nothing waiting' in res['message'], "and it clears once answered")

    res = agent_tools_v2.make_request("", acting_member=kid)
    check(res['status'] == 'error', "an empty ask is refused rather than sent")


def scenario_the_agent_asks_which_one_rather_than_guessing():
    from services import agent_tools_v2
    _reset()
    kid = _member("Lily", role='child')
    sib = _member("James", role='child')
    dad = _member("Jeff", role='parent')
    reqsvc.create(kid['id'], "can you get me at 3?")
    reqsvc.create(sib['id'], "can I go to Ben's after school?")

    res = agent_tools_v2.answer_request(True, acting_member=dad)
    check(res['status'] == 'error' and 'Which one' in res['message'],
          f"two open asks and no hint must not be guessed at: {res}")
    res = agent_tools_v2.answer_request(True, which="cleats", acting_member=dad)
    check(res['status'] == 'error', "and a hint that matches nothing is refused too")
    res = agent_tools_v2.answer_request(True, which="Ben", acting_member=dad)
    check(res['status'] == 'success', f"a hint that resolves works: {res}")


def scenario_every_agent_capability_has_a_hand_path():
    import os
    import re
    from services import agent_tools_v2
    names = [t['name'] for t in agent_tools_v2.get_available_tools()]
    for t in ('make_request', 'get_requests', 'answer_request'):
        check(t in names, f"{t} is offered to the model")
    tpl = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'templates')
    app = open(os.path.join(tpl, 'app.html'), encoding='utf-8').read()
    check('askForSomething' in app and 'answerRequest' in app
          and 'cancelRequest' in app,
          "asking, answering and withdrawing all work by hand in the PWA")
    flat = re.sub(r'\s+', ' ', app)
    check('Ask for something' in flat, "and the ask has a visible way in")


def scenario_the_kid_persona_separates_asking_from_reporting():
    """Reporting a fact and asking for a change used to come out the same."""
    import inspect
    import re
    from services import agent_router
    # Prompt text is assembled from wrapped string literals, so compare on
    # the concatenated, whitespace-collapsed form.
    src = re.sub(r'"\s*\n\s*"', '', inspect.getsource(agent_router))
    src = re.sub(r'\s+', ' ', src)
    check('make_request' in src and 'propose_family_action for FACTS' in src,
          "the kid prompt draws the line explicitly")
    check('never promise the answer' in src,
          "and forbids promising an answer it does not have")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} request scenarios passed")
