"""Tests for the coverage ladder (services/coverage_options.py) — the answer
that has to arrive WITH the problem.

Load-bearing properties: a free driver is offered by name, an outside hand is
only ever offered from history, tier 3 names its reasons instead of listing
doors it cannot open, an ask holds state so the return trip is one tap, and
'we're skipping it' works on an event nobody ever marked optional.

Run from chauffeur/:  python tests/test_coverage_ladder.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import coverage_options as cov, storage

NOON = datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
THU = (NOON + datetime.timedelta(days=1)).replace(hour=17)


def _reset():
    for t in (storage.members_table, storage.drivers_table, storage.cache_table,
              storage.assist_contacts_table, storage.assist_assignments_table,
              storage.assist_history_table, storage.coverage_asks_table,
              storage.protected_commitments_table, storage.findings_table,
              storage.optional_decisions_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}


def _driver(d_id, name, member_id=None):
    with storage.db_lock:
        storage.drivers_table.insert({"id": d_id, "name": name, "hashtags": []})
    if member_id:
        storage.add_member({"id": member_id, "name": name, "role": "parent",
                            "driver_id": d_id})


def _event(ev_id="ev1", title="Soccer Practice", start=None, end=None):
    start = start or THU
    return {"id": ev_id, "title": title, "start": start.isoformat(),
            "end": (end or start + datetime.timedelta(hours=1)).isoformat()}


def _cache(events, assignments=None):
    cache = {"events": events, "assignments": assignments or {},
             "unassigned": [], "assist_assignments": {}}
    storage.set_cached_schedule(cache)
    return cache


def scenario_tier1_names_the_free_driver():
    _reset()
    _driver("d1", "Jeff", member_id="jeff")
    ev = _event()
    rung = cov.ladder(ev, _cache([ev]), NOON)
    check(rung['tier'] == 1, f"a free driver is tier 1, got {rung['tier']}")
    check("Jeff is free" in rung['line'], f"names them: {rung['line']}")
    check("override" in rung['line'],
          "and is honest that the solver already passed — this is an override, "
          f"not a bug we spotted: {rung['line']}")
    act = rung['actions'][0]
    check(act['action_type'] == 'reassign_driver' and act['payload']['driver_name'] == 'Jeff',
          f"the tap is a real assignment, got {act}")


def scenario_a_busy_driver_is_not_offered_and_says_why():
    _reset()
    _driver("d1", "Jeff", member_id="jeff")
    ev = _event()
    clash = _event("ev2", "Ava pickup", start=THU.replace(hour=17, minute=15))
    rung = cov.ladder(ev, _cache([ev, clash], {"ev2": "d1"}), NOON)
    check(rung['tier'] == 3, f"nobody free means tier 3, got {rung['tier']}")
    check("Jeff: driving Ava pickup" in rung['line'],
          f"and the reason is the drive itself: {rung['line']}")


def scenario_protected_time_is_a_reason_not_a_gap():
    _reset()
    _driver("d1", "Sarah", member_id="sarah")
    storage.add_protected_commitment({"id": "pc1", "member_id": "sarah",
                                      "title": "Thursday run",
                                      "days_of_week": [THU.weekday()],
                                      "time_start": "16:00", "time_end": "18:00",
                                      "active": True})
    ev = _event()
    rung = cov.ladder(ev, _cache([ev]), NOON)
    check(rung['tier'] == 3, "protected time takes them out of the free list")
    check("Thursday run" in rung['line'],
          f"named as the standing commitment it is: {rung['line']}")


def scenario_tier2_only_ever_comes_from_history():
    _reset()
    _driver("d1", "Jeff", member_id="jeff")
    ev = _event()
    clash = _event("ev2", "Ava pickup", start=THU)
    storage.add_assist_contact({"id": "c1", "name": "The Muellers",
                                "kinds": ["driving"], "active": True})
    storage.add_assist_contact({"id": "c2", "name": "A Stranger",
                                "kinds": ["driving"], "active": True})
    # Only the Muellers have actually covered this event before.
    storage.add_assist_history({"event_id": "ev1", "contact_id": "c1",
                                "event_title": "Soccer Practice",
                                "action": "covered", "scope": "instance"})
    rung = cov.ladder(ev, _cache([ev, clash], {"ev2": "d1"}), NOON)
    check(rung['tier'] == 2, f"a known hand is tier 2, got {rung['tier']}")
    check("Muellers" in rung['line'], f"offers the one with history: {rung['line']}")
    check("Stranger" not in rung['line'],
          "never a cold suggestion — that is how an app gets uninstalled")


def scenario_tier3_offers_only_doors_it_can_open():
    _reset()
    _driver("d1", "Jeff", member_id="jeff")
    ev = _event()
    clash = _event("ev2", "Ava pickup", start=THU)
    rung = cov.ladder(ev, _cache([ev, clash], {"ev2": "d1"}), NOON)
    types = {a['action_type'] for a in rung['actions']}
    check(types == {'ask_outside_hand', 'skip_occurrence'},
          f"ask someone new, or skip it — and nothing else, got {types}")
    check(rung['severity'] == 'decide', "and it is a decision, not an approval")
    check("can't cover" in rung['line'], f"said plainly: {rung['line']}")


def scenario_the_draft_is_a_text_a_person_would_send():
    _reset()
    ev = _event()
    text = cov.draft_ask(ev, "Beth")
    check(text.startswith("Beth, any chance"), f"opens like a text: {text}")
    check("http" not in text and "Chauffeur" not in text,
          "no link, no app branding — a confirm link between friends reads as "
          f"a flyer, which is why it was cut: {text}")


def scenario_an_ask_holds_state_and_one_tap_closes_it():
    _reset()
    ev = _event()
    _cache([ev])
    storage.add_assist_contact({"id": "c1", "name": "The Muellers",
                                "kinds": ["driving"], "active": True})
    res = cov.start_ask("ev1", "c1", asked_by="mom")
    check(res['status'] == 'success' and "any chance" in res['text'],
          f"the ask returns the words to send, got {res}")

    # While it is out, the ladder must not re-offer the rung we are standing on.
    rung = cov.ladder(ev, storage.get_cached_schedule(), NOON)
    check(rung['tier'] == 0 and "waiting" in rung['line'],
          f"an ask in flight IS the answer, got {rung}")

    ans = cov.answer_ask(res['ask_id'], 'covered', member_id='mom')
    check(ans['status'] == 'success', f"one tap answers it, got {ans}")
    check(storage.get_assist_assignment_map().get("ev1") == "c1",
          "and writes the coverage, which is what takes it out of the solve")

    cov.answer_ask(res['ask_id'], 'undo', member_id='mom')
    check(storage.get_assist_assignment_map().get("ev1") is None,
          "undo unwinds the coverage too, not just the ask")


def scenario_somebody_new_becomes_a_known_hand():
    """The point of asking for a name on confirm: next time they are a tier-2
    candidate instead of a blank field."""
    _reset()
    ev = _event()
    _cache([ev])
    res = cov.start_ask("ev1", asked_by="mom")
    cov.answer_ask(res['ask_id'], 'covered', member_id='mom', contact_name="Beth Ray")
    names = [c['name'] for c in storage.get_assist_contacts()]
    check("Beth Ray" in names, f"they are a contact now, got {names}")
    check(storage.get_assist_assignment_map().get("ev1"), "and they hold the drive")


def scenario_nudges_come_when_a_reply_would_exist():
    _reset()
    ev = _event()
    _cache([ev])
    res = cov.start_ask("ev1", asked_by="mom")
    check(cov.due_nudges(NOON) == [], "nothing is asked the moment it is sent")
    later = NOON + datetime.timedelta(hours=2)
    due = cov.due_nudges(later)
    check(len(due) == 1, f"an hour on, the question is worth asking, got {due}")
    check("Did" in cov.nudge_body(due[0]), f"and it is one question: {cov.nudge_body(due[0])}")

    # "Still waiting" re-arms rather than resolving: it is an answer about the
    # ask, not about the drive.
    cov.answer_ask(res['ask_id'], 'waiting')
    check(storage.get_coverage_ask(res['ask_id'])['state'] == 'waiting',
          "still waiting keeps it open")


def scenario_skipping_works_on_a_mandatory_event():
    """"We're skipping it" is a sentence a family may say about anything on the
    calendar — the optional flag governs day-by-day ATTENDANCE, not whether a
    family is allowed to not go once."""
    _reset()
    from services import chat_actions, optional_events
    ev = _event()          # no app_config: never marked optional
    _cache([ev])
    res = chat_actions._skip_occurrence({"event_id": "ev1"})
    check(res['status'] == 'success', f"the skip lands, got {res}")

    class _E:
        def __init__(self, d):
            self.__dict__.update(d)
            self.app_config = d.get('app_config') or {}
            self.optional_decision = None
    events = [_E(ev)]
    optional_events.stamp_decisions(events)
    check(events[0].optional_decision == 'skip',
          "and the solver is told, or the button did nothing")


SCENARIOS = [
    scenario_tier1_names_the_free_driver,
    scenario_a_busy_driver_is_not_offered_and_says_why,
    scenario_protected_time_is_a_reason_not_a_gap,
    scenario_tier2_only_ever_comes_from_history,
    scenario_tier3_offers_only_doors_it_can_open,
    scenario_the_draft_is_a_text_a_person_would_send,
    scenario_an_ask_holds_state_and_one_tap_closes_it,
    scenario_somebody_new_becomes_a_known_hand,
    scenario_nudges_come_when_a_reply_would_exist,
    scenario_skipping_works_on_a_mandatory_event,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
