"""Tests for kid-as-sensor proposal mirroring (kid-support arc K3).

Load-bearing properties: a proposal card created from a CHILD's private
Argyle DM is mirrored into the family channel (where the approvers are) and
the proposal is re-bound there so the approval outcome lands where parents
saw the card; parent/family contexts don't mirror; a child's approval tap
stays refused.

Run from chauffeur/:  python tests/test_kid_sensor.py
"""
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, chat_actions


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.chat_channels_table,
              storage.chat_messages_table, storage.channel_reads_table,
              storage.agent_action_proposals_table):
        t.truncate()
    storage.get_settings = lambda: {"calendar_ids": ["primary"]}
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child", "is_child": True})
    storage.ensure_argyle_member()
    storage.ensure_family_channel()


def _proposal_card(summary="Practice moved to 5pm Thursday"):
    res = chat_actions.create_action_proposal(
        "create_event", summary,
        {"title": "Soccer Practice", "start": "2126-01-01T17:00:00", "end": "2126-01-01T18:00:00"},
        created_by_member_id="kid1")
    check(res["status"] == "success", "proposal created")
    return res["proposal_id"], res["card"]


def _mention(channel, sender, reply, card):
    import main
    with mock.patch('services.agent_router.process_agent_request',
                    return_value={"message": reply, "card": card}):
        main._run_argyle_mention(channel, sender, "@argyle practice moved to 5 on thursday")


def scenario_kid_dm_card_mirrors_to_family():
    _reset()
    kid = storage.get_member("kid1")
    dm = storage.get_or_create_dm("argyle", "kid1")
    pid, card = _proposal_card()
    _mention(dm, kid, "Got it — I've flagged that for your parents! 💪", card)

    dm_msgs = storage.get_channel_messages(dm["id"])
    check(dm_msgs and dm_msgs[-1]["sender_member_id"] == "argyle"
          and dm_msgs[-1].get("card"), "Argyle replied in the kid's DM with the card")
    fam = storage.get_family_channel()
    fam_msgs = storage.get_channel_messages(fam["id"])
    check(len(fam_msgs) == 1 and "Addison flagged this for a parent" in fam_msgs[0]["body"],
          f"card mirrored to the family channel, got {[m['body'] for m in fam_msgs]}")
    check((fam_msgs[0].get("card") or {}).get("proposal_id") == pid,
          "mirror carries the SAME proposal card")
    prop = storage.get_action_proposal(pid)
    check(prop.get("channel_id") == fam["id"],
          "proposal re-bound to the family channel so the outcome lands with parents")


def scenario_parent_dm_does_not_mirror():
    _reset()
    mom = storage.get_member("momm")
    dm = storage.get_or_create_dm("argyle", "momm")
    pid, card = _proposal_card("Reassign Thursday pickup to Dad")
    _mention(dm, mom, "Proposed.", card)

    fam_msgs = storage.get_channel_messages(storage.get_family_channel()["id"])
    check(fam_msgs == [], "a parent's own DM proposal stays in their DM")
    check(storage.get_action_proposal(pid).get("channel_id") == dm["id"],
          "proposal stays bound to the parent's DM")


def scenario_family_channel_no_double_post():
    _reset()
    kid = storage.get_member("kid1")
    fam = storage.get_family_channel()
    pid, card = _proposal_card()
    _mention(fam, kid, "Flagged for your parents!", card)

    fam_msgs = storage.get_channel_messages(fam["id"])
    check(len(fam_msgs) == 1, f"kid asking IN the family channel posts once, got {len(fam_msgs)}")
    check(storage.get_action_proposal(pid).get("channel_id") == fam["id"],
          "proposal bound to the family channel")


def scenario_child_approval_still_refused():
    _reset()
    pid, card = _proposal_card()
    res = chat_actions.act_on_proposal(pid, "approve", storage.get_member("kid1"))
    check(res["status"] == "error" and "parent" in res["message"].lower(),
          f"a child's Approve tap is refused, got {res}")
    check(storage.get_action_proposal(pid).get("status") == "proposed",
          "the proposal stays open for a real parent")


SCENARIOS = [
    scenario_kid_dm_card_mirrors_to_family,
    scenario_parent_dm_does_not_mirror,
    scenario_family_channel_no_double_post,
    scenario_child_approval_still_refused,
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
