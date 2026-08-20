"""Event-channel membership (family-network arc S11, §8.5).

Event threads were `member_ids: []` by construction — household-visible and
nothing else expressible. Membership is now real and ADDITIVE: [] is still
the household (today's behaviour, untouched), and a populated list only ever
lets OUTSIDE hands in — a helper or guest granted one thread reads it, talks
in it, is pinged for it, and holds no other. Letting somebody into family
memory is a parent's act, on event threads only.

Run from chauffeur/:  python tests/test_event_membership.py
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


class Req:
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


def _denied(fn, *args, **kw):
    try:
        fn(*args, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _seed():
    storage.members_table.truncate()
    storage.chat_channels_table.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "dad", "name": "Dad", "role": "adult"})
    storage.add_member({"id": "nan", "name": "Nanny", "role": "helper"})
    storage.add_member({"id": "cuz", "name": "Cousin", "role": "guest"})
    ch = storage.get_or_create_event_channel("ev1", "Emma's game")
    return ch, {mid: storage.create_member_token(mid)
                for mid in ("mom", "dad", "nan", "cuz")}


def scenario_letting_someone_in_is_a_parents_act():
    import main
    ch, tok = _seed()
    check(_denied(main.add_channel_member_api, ch['id'],
                  main.ChannelMemberRequest(member_id="nan"),
                  request=Req(tok['dad'])) == 403,
          "a non-parent adult cannot open family memory to an outside hand")
    got = main.add_channel_member_api(ch['id'],
                                      main.ChannelMemberRequest(member_id="nan"),
                                      request=Req(tok['mom']))
    check(got['member_ids'] == ["nan"], "a parent can")
    dm = storage.get_or_create_dm("mom", "dad")
    check(_denied(main.add_channel_member_api, dm['id'],
                  main.ChannelMemberRequest(member_id="nan"),
                  request=Req(tok['mom'])) == 400,
          "a DM's pair is fixed at creation — this door is event threads only")


def scenario_one_thread_and_no_other():
    import main
    ch, tok = _seed()
    other = storage.get_or_create_event_channel("ev2", "Jack's recital")
    check(_denied(main.get_messages, ch['id'], request=Req(tok['nan'])) == 403,
          "before the grant: refused")
    main.add_channel_member_api(ch['id'],
                                main.ChannelMemberRequest(member_id="nan"),
                                request=Req(tok['mom']))
    check(isinstance(main.get_messages(ch['id'], request=Req(tok['nan'])), list),
          "after: the helper reads the one thread they were let into")
    check(_denied(main.get_messages, other['id'], request=Req(tok['nan'])) == 403,
          "…and no other")
    visible = [c['id'] for c in storage.get_channels_for_member("nan")]
    check(visible == [ch['id']],
          f"their channel list is exactly that thread: {visible}")
    pinged = {m['id'] for m in main._channel_recipient_members(
        storage.get_channel(ch['id']))}
    check('nan' in pinged, "and its pings now reach them (S10's audience)")


def scenario_a_member_talks_freely_once_inside():
    import main
    from fastapi import BackgroundTasks
    ch, tok = _seed()
    main.add_channel_member_api(ch['id'],
                                main.ChannelMemberRequest(member_id="cuz"),
                                request=Req(tok['mom']))
    msg = main.send_message(ch['id'], main.SendMessageRequest(
        sender_member_id="cuz", body="What a game!"), BackgroundTasks(),
        request=Req(tok['cuz']))
    check(msg and msg['body'] == "What a game!",
          "added by somebody who can, talking freely once inside (§6B)")
    check(_denied(main.send_message, ch['id'], main.SendMessageRequest(
        sender_member_id="nan", body="hi"), BackgroundTasks(),
        request=Req(tok['nan'])) == 403,
          "an outside hand NOT let in still cannot post words into the thread")


def scenario_the_grant_is_additive_never_narrowing():
    import main
    ch, tok = _seed()
    main.add_channel_member_api(ch['id'],
                                main.ChannelMemberRequest(member_id="nan"),
                                request=Req(tok['mom']))
    check(isinstance(main.get_messages(ch['id'], request=Req(tok['dad'])), list),
          "a populated member_ids never locks the household out (§7: empty "
          "means everyone, populated only ADDS)")
    visible = [c['id'] for c in storage.get_channels_for_member("dad")]
    check(ch['id'] in visible, "the thread stays on every household list")


def scenario_removal_closes_the_door_again():
    import main
    ch, tok = _seed()
    main.add_channel_member_api(ch['id'],
                                main.ChannelMemberRequest(member_id="nan"),
                                request=Req(tok['mom']))
    main.remove_channel_member_api(ch['id'], "nan", request=Req(tok['mom']))
    check(_denied(main.get_messages, ch['id'], request=Req(tok['nan'])) == 403,
          "removed: the thread is family memory again")


SCENARIOS = [
    scenario_letting_someone_in_is_a_parents_act,
    scenario_one_thread_and_no_other,
    scenario_a_member_talks_freely_once_inside,
    scenario_the_grant_is_additive_never_narrowing,
    scenario_removal_closes_the_door_again,
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
