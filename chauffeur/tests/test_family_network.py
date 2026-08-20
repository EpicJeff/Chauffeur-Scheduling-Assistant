"""Family-network arc, Phase 1 (docs/family_network_design.md §10, §12 S1-S2).

S1 closes the five live holes — read endpoints that never asked who was
looking. The shape under test everywhere: a TOKEN-resolved viewer is refused
what is not theirs (dark or not), while a tokenless caller keeps today's
behaviour until `auth_enforce` flips (the route guard owns anonymity; these
checks own identity).

S2 is the helper's contribution path: moments.contribute = when_present,
enforced at the send endpoint and offered by the capture sweep.

Run from chauffeur/:  python tests/test_family_network.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


class Req:
    """The slice of a Request that _acting_id/acting_member read."""
    def __init__(self, token=None, query=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = query or {}


def _seed():
    storage.members_table.truncate()
    storage.chat_channels_table.truncate()
    storage.conversations_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent", "is_child": False})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult", "is_child": False})
    storage.add_member({"id": "emma", "name": "Emma", "role": "child", "is_child": True})
    storage.add_member({"id": "jack", "name": "Jack", "role": "child", "is_child": True})
    storage.add_member({"id": "nan", "name": "Nanny", "role": "helper", "is_child": False,
                        "driver_id": "d_nan"})
    return {mid: storage.create_member_token(mid)
            for mid in ("mom", "dad", "emma", "jack", "nan")}


def _denied(fn, *args, **kw):
    try:
        fn(*args, **kw)
        return None
    except HTTPException as e:
        return e.status_code


# --- Hole 1: GET /api/channels/{id}/messages --------------------------------

def scenario_dm_read_requires_membership():
    import main
    tok = _seed()
    dm = storage.get_or_create_dm("mom", "dad")
    check(_denied(main.get_messages, dm['id'], request=Req(tok['emma'])) == 403,
          "a kid's token cannot read the parents' DM by id")
    check(isinstance(main.get_messages(dm['id'], request=Req(tok['mom'])), list),
          "a member of the DM still reads it")
    check(isinstance(main.get_messages(dm['id'], request=Req()), list),
          "a tokenless caller keeps today's behaviour while dark (guard's job)")


def scenario_helper_reads_dms_only():
    import main
    tok = _seed()
    ev = storage.get_or_create_event_channel("ev1", "Emma's game")
    check(_denied(main.get_messages, ev['id'], request=Req(tok['nan'])) == 403,
          "an event thread is family memory — the helper's read is refused")
    check(isinstance(main.get_messages(ev['id'], request=Req(tok['dad'])), list),
          "household members keep event threads")
    dm = storage.get_or_create_dm("nan", "mom")
    check(isinstance(main.get_messages(dm['id'], request=Req(tok['nan'])), list),
          "the helper's own DM stays theirs")


# --- Hole 2: GET /api/family/locations --------------------------------------

def scenario_locations_claim_stops_unmasking_once_enforcing():
    import main
    from services import stages, auth
    tok = _seed()
    orig_can, orig_settings = stages.can, storage.get_settings
    stages.can = lambda m, cap: True  # every kid is private-stage for this test

    def private_rows(viewer=None, request=None):
        rows = main.family_locations(viewer=viewer, request=request)
        return {r['member_id'] for r in rows if r.get('private')}

    try:
        check(private_rows() == {"emma", "jack"},
              "viewerless (kiosk) callers get the lock chip, not coordinates")
        check(private_rows(viewer="mom", request=Req()) == set(),
              "while dark, the bare claim still unlocks — grace, counted")
        storage.get_settings = lambda: {"auth_enforce": True}
        check(private_rows(viewer="mom", request=Req()) == {"emma", "jack"},
              "once enforcing, a spoofed viewer id no longer unmasks a kid")
        check(private_rows(request=Req(tok['mom'])) == set(),
              "the token unlocks family eyes with no claim at all")
        check(_denied(main.family_locations, viewer="dad",
                      request=Req(tok['emma'])) == 403,
              "a token naming somebody else is impersonation, refused")
    finally:
        stages.can, storage.get_settings = orig_can, orig_settings
        auth.reset_audit()


# --- Hole 3: GET /api/members/{id}/day --------------------------------------

def scenario_day_is_self_or_household_adult():
    import main
    tok = _seed()
    check(_denied(main.member_day, "emma", request=Req(tok['jack'])) == 403,
          "a sibling's token cannot read Emma's day")
    check(_denied(main.member_day, "emma", request=Req(tok['nan'])) == 403,
          "a helper's token cannot read Emma's day")
    check(isinstance(main.member_day("emma", request=Req(tok['emma'])), dict),
          "Emma reads her own day")
    check(isinstance(main.member_day("emma", request=Req(tok['dad'])), dict),
          "a household adult reads a kid's day")
    check(isinstance(main.member_day("emma", request=Req()), dict),
          "tokenless callers keep today's behaviour while dark")


# --- Hole 4: GET /api/chat/conversations + history --------------------------

def scenario_voice_sessions_are_not_household_reading():
    import main
    tok = _seed()
    storage.create_conversation({"id": "gen1", "type": "general", "title": "Chat",
                                 "messages": [], "created_at": 1.0, "updated_at": 9e12})
    storage.create_conversation({"id": "voice-abc", "type": "voice", "title": "🎙️ hi",
                                 "messages": [{"role": "user", "content": "secret"}],
                                 "created_at": 1.0, "updated_at": 9e12})
    ids = lambda req: {c['id'] for c in main.get_conversations(request=req)['conversations']}
    check(ids(Req()) == {"gen1"}, "anonymous callers see only the shared widget thread")
    check(ids(Req(tok['emma'])) == {"gen1"}, "a kid sees only the shared widget thread")
    check(ids(Req(tok['mom'])) == {"gen1", "voice-abc"}, "a parent sees the lot")
    check(_denied(main.get_chat_history, "voice-abc", request=Req(tok['emma'])) == 403,
          "the history door agrees with the list door")
    hist = main.get_chat_history("voice-abc", request=Req(tok['mom']))['history']
    check(hist and hist[0]['content'] == "secret", "a parent still reads a voice session")


# --- Hole 5: POST /api/members role whitelist -------------------------------

def scenario_member_create_enforces_the_role_whitelist():
    import main
    from models.schemas import FamilyMember
    _seed()
    check(_denied(main.create_member,
                  FamilyMember(name="Eve", role="superadmin")) == 400,
          "a create cannot mint a role no preset knows")
    main.create_member(FamilyMember(id="newkid", name="Kid", role="child"))
    m = storage.get_member("newkid")
    check(m and m.get('is_child') is True, "is_child stays in step with role on create")


# --- S2: moments.contribute = when_present ----------------------------------

_TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
             "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def _seed_live_event_with_helper_driving():
    """A 60-minute event that started five minutes ago, driven by the nanny."""
    import datetime
    now = datetime.datetime.now()
    ev = {"id": "ev1", "title": "Emma's game",
          "start": (now - datetime.timedelta(minutes=5)).isoformat(),
          "end": (now + datetime.timedelta(minutes=55)).isoformat()}
    storage.set_cached_schedule({"events": [ev],
                                 "assignments": {"ev1": "d_nan"},
                                 "matched_rules": {}})


def scenario_present_helper_hands_over_a_moment():
    import main
    from fastapi import BackgroundTasks
    tok = _seed()
    _seed_live_event_with_helper_driving()
    ch = storage.get_or_create_event_channel("ev1", "Emma's game")

    photo = main.SendMessageRequest(sender_member_id="nan", body="Great game!",
                                    attachment={"kind": "photo", "data_url": _TINY_PNG})
    main.send_message(ch['id'], photo, BackgroundTasks(), request=Req(tok['nan']))
    msgs = storage.get_channel_messages(ch['id'])
    check(any(m.get('sender_member_id') == 'nan' and m.get('attachment')
              for m in msgs),
          "the helper the schedule placed at the event hands the family a moment")

    text = main.SendMessageRequest(sender_member_id="nan", body="nice weather")
    check(_denied(main.send_message, ch['id'], text, BackgroundTasks(),
                  request=Req(tok['nan'])) == 403,
          "text-only stays barred — the surface is a photo handover, not a seat")


def scenario_absent_helper_is_refused():
    import main
    from fastapi import BackgroundTasks
    tok = _seed()
    _seed_live_event_with_helper_driving()
    other = storage.get_or_create_event_channel("ev2", "Jack's recital")
    photo = main.SendMessageRequest(sender_member_id="nan", body="",
                                    attachment={"kind": "photo", "data_url": _TINY_PNG})
    check(_denied(main.send_message, other['id'], photo, BackgroundTasks(),
                  request=Req(tok['nan'])) == 403,
          "an event the schedule does not place the helper at fails closed")


def scenario_capture_prompt_reaches_the_helper():
    from services import presence
    _seed()
    _seed_live_event_with_helper_driving()
    orig = presence.prompt_worthiness
    presence.prompt_worthiness = lambda ev, present_ids, d: 'moment'
    sent = []
    try:
        presence.run_capture_prompts(lambda m, title, body, path: sent.append(m['id']))
    finally:
        presence.prompt_worthiness = orig
    check("nan" in sent,
          "the capture sweep asks the helper holding the camera, not just adults")


def scenario_the_guest_role_exists_at_last():
    """S15: the answer to §1, creatable now that everything it needs exists.
    The §13 API-level assertion rides the earlier slices: a guest reaches
    presence.moments and pets (test_route_facets), their channel list is
    their invited rooms (test_chat_initiate), the moments ping is theirs
    (test_fanout_scope), and every other facet answers none (test_scope)."""
    import main
    from models.schemas import FamilyMember
    _seed()
    main.create_member(FamilyMember(id="cousin", name="Cousin", role="guest"))
    m = storage.get_member("cousin")
    check(m and m.get('role') == 'guest' and m.get('is_child') is False,
          "a guest can finally be created through the front door")
    from services import scope
    reachable = {f for f in scope.FACETS if scope.reach(m, f) != 'none'}
    check(reachable == {'presence.moments', 'pets'},
          f"…and arrives holding exactly the social surfaces: {sorted(reachable)}")


SCENARIOS = [
    scenario_dm_read_requires_membership,
    scenario_helper_reads_dms_only,
    scenario_locations_claim_stops_unmasking_once_enforcing,
    scenario_day_is_self_or_household_adult,
    scenario_voice_sessions_are_not_household_reading,
    scenario_member_create_enforces_the_role_whitelist,
    scenario_present_helper_hands_over_a_moment,
    scenario_absent_helper_is_refused,
    scenario_capture_prompt_reaches_the_helper,
    scenario_the_guest_role_exists_at_last,
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
