"""Fan-out audiences read scope (family-network arc S10).

Scope reaches the things the server sends unprompted. A push not sent is
invisible — there is no audit mode for an absence — so each site is pinned
here instead: the channel-message audience asks the same chat facets the
channel list reads (the weekly digest, posted into the family channel,
inherits it for free); the moment audience asks presence.moments and
narrows by sees_people; and a broad send that names its facet skips a
member whose reach is none, because the server must not push what the app
would refuse to show.

Run from chauffeur/:  python tests/test_fanout_scope.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import presence, storage


def _seed():
    storage.members_table.truncate()
    storage.chat_channels_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult",
                        "driver_id": "d_dad"})
    storage.add_member({"id": "gran", "name": "Gran", "role": "adult",
                        "scope": {"preset": "keeping_up"}})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child",
                        "is_child": True, "passenger_id": "p_emma"})
    storage.add_member({"id": "nan", "name": "Nanny", "role": "helper"})
    # No creatable path to this role until S15 — seeded to pin the audience
    # before the role ships.
    storage.add_member({"id": "cuz", "name": "Cousin", "role": "guest"})


def scenario_family_pings_reach_who_may_see_the_room():
    import main
    _seed()
    storage.ensure_family_channel()
    fam = storage.get_family_channel()
    ids = {m['id'] for m in main._channel_recipient_members(fam)}
    check('nan' not in ids, "a helper is not pinged for the family room")
    check('cuz' not in ids, "nor a guest — invited means added, not ambient")
    check({'mom', 'dad', 'gran', 'emma'} <= ids,
          "the household, kids included, exactly as today — and the weekly "
          "digest posts here, so its audience is this one")


def scenario_event_pings_honour_explicit_membership():
    import main
    _seed()
    ch = storage.get_or_create_event_channel("ev1", "Emma's game")
    ids = {m['id'] for m in main._channel_recipient_members(ch)}
    check('nan' not in ids and 'cuz' not in ids,
          "outside hands are outside the thread's pings")
    ch2 = dict(ch, member_ids=['cuz'])
    ids2 = {m['id'] for m in main._channel_recipient_members(ch2)}
    check('cuz' in ids2,
          "…until somebody explicitly adds them (S11's shape, honoured now)")


def scenario_moment_pings_go_to_who_may_see_moments():
    _seed()
    sched = {'events': [{'id': 'ev1', 'title': "Emma's game",
                         'calendar_ids': ['p_emma']}],
             'assignments': {'ev1': 'd_dad'}, 'matched_rules': {}}
    storage.add_passenger({'id': 'p_emma', 'name': 'Emma',
                           'calendar_ids': [], 'hashtags': []})
    ch = storage.get_or_create_event_channel("ev1", "Emma's game")
    ids = {m['id'] for m in presence.moment_push_audience(ch, sched)}
    check('dad' not in ids, "the driver standing there is never pinged")
    check('mom' in ids, "the kept-away parent is")
    check('gran' in ids,
          "the keeping-up grandparent too — Emma is one of her people")
    check('emma' not in ids, "kids ride their existing surfaces — no new pings")
    check('nan' not in ids, "helpers fall out via scope, as the role filter had it")
    check('cuz' in ids, "a guest is IN: the moments ping is the one thing they get")


def scenario_a_narrowed_scope_skips_the_adults_dinner():
    _seed()
    sched = {'events': [{'id': 'ev9', 'title': "Anniversary dinner",
                         'calendar_ids': []}],
             'assignments': {'ev9': 'd_dad'}, 'matched_rules': {}}
    ch = storage.get_or_create_event_channel("ev9", "Anniversary dinner")
    ids = {m['id'] for m in presence.moment_push_audience(ch, sched)}
    check('mom' in ids, "the kept-away parent still gets the dinner moment")
    check('gran' not in ids,
          "the keeping-up grandparent does not — none of her people was there")


def scenario_a_named_facet_gates_the_send():
    import main
    _seed()
    sent = []
    real = main.send_push_to_member
    main.send_push_to_member = lambda mid, *a, **k: sent.append(mid)
    # QUIET HOURS OFF, explicitly. `_notify_member_lanes` drops a non-urgent
    # send inside them, and a member with no settings is inside the default
    # window all evening — so this scenario passed in the afternoon and failed
    # after about nine at night, which is exactly the shape of a test nobody
    # trusts. What is under test here is the FACET gate; the quiet-hour gate is
    # `test_kid_pushes`' business and must not be able to answer for it.
    from services import family_digest as _fd
    real_quiet = _fd.in_member_quiet_hours
    _fd.in_member_quiet_hours = lambda *a, **k: False
    try:
        gran = storage.get_member('gran')
        main._notify_member_lanes(gran, "Drives", "…", facet='schedule.logistics')
        check(sent == [], "reach none: the server must not push what the app "
                          "would refuse to show")
        main._notify_member_lanes(gran, "Moments", "…", facet='presence.moments')
        check(sent == ['gran'], "reach all: the send goes out")
        main._notify_member_lanes(gran, "Chore", "…")
        check(sent == ['gran', 'gran'], "no facet named: self-targeted sends "
                                        "are untouched")
    finally:
        main.send_push_to_member = real
        _fd.in_member_quiet_hours = real_quiet


SCENARIOS = [
    scenario_family_pings_reach_who_may_see_the_room,
    scenario_event_pings_honour_explicit_membership,
    scenario_moment_pings_go_to_who_may_see_moments,
    scenario_a_narrowed_scope_skips_the_adults_dinner,
    scenario_a_named_facet_gates_the_send,
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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
