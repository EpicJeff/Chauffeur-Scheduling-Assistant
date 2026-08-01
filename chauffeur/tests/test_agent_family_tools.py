"""Tests for the family-hub agent tools (agent_tools_v2: messaging, chores,
routines). Verifies identity resolution (PWA driver vs named vs unknown),
helper restrictions, message storage, DM creation, chore claiming, and
routine status. No network, no LLM, never touches data/ — fan-out is skipped
because `main` is not imported.

Run from chauffeur/:  python tests/test_agent_family_tools.py
"""
import atexit
import os
import shutil
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="chauffeur_famtools_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.schemas import Chore, FamilyMember, RoutineItem  # noqa: E402
from services import storage  # noqa: E402
from services import agent_tools_v2 as tools  # noqa: E402

PASS = 0
FAIL = 0


def check(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def setup_family():
    storage.add_driver({'id': 'd_mom', 'name': 'Mom', 'color_code': '#f00',
                        'group': 'primary', 'priority_index': 1, 'calendar_ids': []})
    storage.ensure_members()
    mom = next(m for m in storage.get_all_members() if m['name'] == 'Mom')
    storage.update_member(mom['id'], {'role': 'parent'})
    storage.add_member(FamilyMember(name='Ben', role='child', is_child=True).model_dump())
    storage.add_member(FamilyMember(name='Nanny Sue', role='helper').model_dump())
    members = {m['name']: m for m in storage.get_all_members()}
    return members['Mom'], members['Ben'], members['Nanny Sue']


def test_messaging(mom, ben, nanny):
    print("messaging tools ...")
    # Unknown speaker: must ask, not guess.
    res = tools.send_family_message("dinner at 6")
    check(res['status'] == 'error' and 'who this is from' in res['message'],
          f"unknown sender asks: {res}")

    # PWA driver identity (trusted, server-side).
    res = tools.send_family_message("dinner at 6", sender_driver_id='d_mom')
    check(res['status'] == 'success' and 'Mom' in res['message'], f"PWA send: {res}")

    # Named sender (voice/admin).
    res = tools.send_family_message("I fed the dog", from_member='ben')
    check(res['status'] == 'success' and 'Ben' in res['message'], f"named send: {res}")

    fam = storage.get_family_channel()
    msgs = storage.get_channel_messages(fam['id'])
    check(len(msgs) == 2, f"two messages stored, got {len(msgs)}")
    check(msgs[0]['sender_member_id'] == mom['id'], "sender is Mom's member id")

    # Helper cannot post to family channel.
    res = tools.send_family_message("hi", from_member='Nanny Sue')
    check(res['status'] == 'error', f"helper blocked from family channel: {res}")

    # DM: created with both member ids.
    res = tools.send_direct_message('Ben', "I'll be late", sender_driver_id='d_mom')
    check(res['status'] == 'success', f"DM send: {res}")
    dm = storage.get_or_create_dm(mom['id'], ben['id'])
    dm_msgs = storage.get_channel_messages(dm['id'])
    check(len(dm_msgs) == 1 and dm_msgs[0]['body'] == "I'll be late", "DM stored")

    # Helper DM rules: helper -> child blocked, helper -> parent allowed.
    res = tools.send_direct_message('Ben', "hi", from_member='Nanny Sue')
    check(res['status'] == 'error', f"helper->child DM blocked: {res}")
    res = tools.send_direct_message('Mom', "running 10 min late", from_member='Nanny Sue')
    check(res['status'] == 'success', f"helper->parent DM allowed: {res}")
    # Child -> helper blocked (relay via family channel).
    res = tools.send_direct_message('Nanny Sue', "hi", from_member='Ben')
    check(res['status'] == 'error', f"child->helper DM blocked: {res}")

    # Reads.
    res = tools.get_family_messages()
    check(res['status'] == 'success' and 'dinner at 6' in res['message']
          and 'I fed the dog' in res['message'], f"read family messages: {res['message']!r}")
    # Unknown recipient lists the family.
    res = tools.send_direct_message('Zorp', "hi", sender_driver_id='d_mom')
    check(res['status'] == 'error' and 'Mom' in res['message'], "unknown recipient lists names")


def test_chores(mom, ben, nanny):
    print("chore tools ...")
    storage.add_chore(Chore(title='Take out the trash', points=15).model_dump())
    storage.add_chore(Chore(title='Dishes', points=10,
                            eligible_member_ids=[ben['id']]).model_dump())

    res = tools.list_chores()
    check(res['status'] == 'success' and 'Take out the trash' in res['message'],
          f"list shows open chores: {res['message']!r}")

    # Claim needs an actor.
    res = tools.claim_chore('trash')
    check(res['status'] == 'error' and 'Who is claiming' in res['message'],
          f"claim without actor asks: {res}")

    # Named claim (voice): Ben takes the trash.
    res = tools.claim_chore('trash', member_name='Ben')
    check(res['status'] == 'success' and 'Ben' in res['message'] and '15' in res['message'],
          f"named claim: {res}")

    # Already claimed.
    res = tools.claim_chore('trash', member_name='Mom')
    check(res['status'] == 'error' and 'open' in res['message'].lower(),
          f"double-claim rejected: {res}")

    # Eligibility list enforced: Mom is not eligible for Dishes.
    res = tools.claim_chore('dishes', member_name='Mom')
    check(res['status'] == 'error' and 'eligible' in res['message'], f"eligibility: {res}")
    res = tools.claim_chore('dishes', sender_driver_id=None, member_name='Ben')
    check(res['status'] == 'success', f"eligible member claims: {res}")

    # Helper cannot claim.
    storage.add_chore(Chore(title='Water plants', points=5).model_dump())
    res = tools.claim_chore('water', member_name='Nanny Sue')
    check(res['status'] == 'error', f"helper claim blocked: {res}")

    res = tools.list_chores()
    check('Claimed' in res['message'] and 'Ben' in res['message'],
          f"list shows claims: {res['message']!r}")


def test_routines(mom, ben, nanny):
    print("routine tools ...")
    import datetime
    r1 = RoutineItem(member_id=ben['id'], title='Brush teeth').model_dump()
    r2 = RoutineItem(member_id=ben['id'], title='Feed dog').model_dump()
    storage.add_routine(r1)
    storage.add_routine(r2)

    res = tools.get_routine_status('Ben')
    check(res['status'] == 'success' and '0/2' in res['message']
          and 'Brush teeth' in res['message'], f"unstarted routine: {res['message']!r}")

    today = datetime.date.today().isoformat()
    storage.set_routine_check(r1['id'], ben['id'], today, True)
    storage.set_routine_check(r2['id'], ben['id'], today, True)
    res = tools.get_routine_status('Ben')
    check('2/2' in res['message'] and 'all done' in res['message'],
          f"completed routine: {res['message']!r}")

    res = tools.get_routine_status('Mom')
    check(res['status'] == 'success' and 'no routine items' in res['message'],
          f"no routine: {res['message']!r}")
    res = tools.get_routine_status('Zorp')
    check(res['status'] == 'error', "unknown member errors")


if __name__ == '__main__':
    mom, ben, nanny = setup_family()
    test_messaging(mom, ben, nanny)
    test_chores(mom, ben, nanny)
    test_routines(mom, ben, nanny)
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
