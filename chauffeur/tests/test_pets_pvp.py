"""Sibling battles: consent, level-matching, and the absence of a scoreboard.

This is the slice that could actually hurt a child, so it is the one with the
most tests. Three promises:

  * CONSENT. A challenge is an invitation, never an event. Nothing resolves
    until the other child says yes; declining is free, silent, and is not a
    forfeit. Not even the agent may accept on somebody's behalf -- otherwise a
    kid could be dragged into a fight by a sibling talking to a speaker in
    another room.
  * LEVEL-MATCHING. A family fight is never decided by who did more chores.
    Both sides drop to the lower level and the smaller training budget.
  * NO STANDING. Both sides are paid, the loser meaningfully, and nothing
    anywhere records who beat whom. A battle is a toy, not a position in the
    family.

Run from chauffeur/:  python tests/test_pets_pvp.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_petpvp_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage.patch_settings({'pet_pvp_enabled': True,
                            'pet_pvp_pair_cap': storage.PET_PVP_PAIR_CAP})


def _pair(xp_a=0, xp_b=0):
    for mid, nm in (("k1", "Ada"), ("k2", "Ben")):
        storage.add_member({"id": mid, "name": nm, "role": "child",
                            "color_code": "#3b82f6", "is_child": True})
    if xp_a:
        storage.grant_pet_xp("k1", xp_a, 'grant')
    if xp_b:
        storage.grant_pet_xp("k2", xp_b, 'grant')
    storage.create_pet("k1", "Rocket", {'body': 'wedge', 'top': 'horns'}, {}, 'ember')
    storage.create_pet("k2", "Pickle", {'body': 'blob', 'top': 'nub'}, {}, 'tide')


# --- consent --------------------------------------------------------------

def test_a_challenge_resolves_nothing_on_its_own():
    reset_db()
    _pair()
    before = storage.get_pet_xp_balance("k2")
    res = storage.create_pet_challenge("k1", "k2")
    check(res['challenge']['state'] == 'pending', "a challenge auto-resolved")
    check(not storage.get_pet_battles("k2"), "a battle happened without a yes")
    check(storage.get_pet_xp_balance("k2") == before,
          "xp moved before anyone agreed")


def test_declining_is_free_and_is_not_a_loss():
    reset_db()
    _pair()
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    before = {m: storage.get_pet_xp_balance(m) for m in ("k1", "k2")}
    out = storage.respond_pet_challenge(ch['id'], False)
    check(out['challenge']['state'] == 'declined', "declining did not stick")
    check(not storage.get_pet_battles("k2"), "declining produced a battle")
    for m in ("k1", "k2"):
        check(storage.get_pet_xp_balance(m) == before[m],
              "declining moved %s's xp" % m)


def test_only_the_person_asked_may_answer():
    reset_db()
    _pair()
    import main
    from fastapi import HTTPException
    storage.set_member_pin("k2", "1234")          # k2 now has to prove it
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    try:
        main.respond_pet_challenge_endpoint(
            ch['id'], main.PetChallengeReplyRequest(accept=True))
        raise AssertionError("a challenge was accepted without the asked "
                             "child's say-so")
    except HTTPException as e:
        check(e.status_code == 403, "wrong refusal: %s" % e.status_code)


def test_the_agent_can_ask_but_never_accept():
    """Handing consent to an assistant would mean a kid could be dragged into
    a fight by a sibling talking to a speaker in another room."""
    from services import agent_tools_v2, agent_tools
    reset_db()
    _pair()
    msg = agent_tools_v2.challenge_pet_battle("Ada", "Ben")['message']
    check('up to them' in msg.lower(), "the agent did not say it was an ask: %r" % msg)
    check(storage.get_pet_challenges("k2")[0]['state'] == 'pending',
          "the agent resolved the challenge itself")
    names = ' '.join(agent_tools.TOOL_SCHEMAS)
    check('accept' not in names and 'respond_pet' not in names,
          "an accept-on-behalf tool exists: %s" % names)


def test_you_cannot_challenge_yourself_or_the_petless():
    reset_db()
    _pair()
    storage.add_member({"id": "k3", "name": "Cleo", "role": "child",
                        "color_code": "#a855f7", "is_child": True})
    check(storage.create_pet_challenge("k1", "k1").get('error'),
          "a child challenged themselves")
    check(storage.create_pet_challenge("k1", "k3").get('error'),
          "a child with no critter was challenged")
    check(storage.create_pet_challenge("k3", "k1").get('error'),
          "a child with no critter issued a challenge")


def test_a_household_can_switch_family_battles_off():
    reset_db()
    _pair()
    storage.patch_settings({'pet_pvp_enabled': False})
    check(storage.create_pet_challenge("k1", "k2").get('error'),
          "challenges still worked with pvp off")
    storage.patch_settings({'pet_pvp_enabled': True})
    check('challenge' in storage.create_pet_challenge("k1", "k2"),
          "turning it back on did not work")


def test_yesterdays_invitation_does_not_linger():
    import time
    reset_db()
    _pair()
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    with storage.db_lock:
        storage.pet_challenges_table.update(
            {'created_at': time.time() - (storage.CHALLENGE_TTL_HOURS + 1) * 3600},
            storage.Query().id == ch['id'])
    check(not storage.get_pet_challenges("k2"),
          "a day-old invitation was still waiting")


# --- level matching -------------------------------------------------------

def test_more_chores_does_not_win_a_family_fight():
    """THE test. A child who has done far more still wins about half.

    Both critters are deliberately IDENTICAL in species and element, so the
    only difference between them is the thing being measured. The first cut of
    this test gave the grinder Ember and the sibling Tide and read 0.00 --
    which was tide beating ember exactly as designed, not level-matching
    failing. A fairness test that also varies the type chart measures the type
    chart."""
    reset_db()
    _pair(xp_a=20000, xp_b=0)                  # miles apart
    check(storage.pet_level("k1") > storage.pet_level("k2") + 10,
          "the levels are not far enough apart to be a real test")
    pet_a, pet_b = storage.get_active_pet("k1"), storage.get_active_pet("k2")
    same = {'species': {'body': 'steps', 'top': 'nub'}, 'type': 'ember'}
    storage.update_pet(pet_a['id'], same)
    storage.update_pet(pet_b['id'], same)
    storage.set_pet_training(pet_a['id'], {'atk': 60, 'spe': 60, 'hp': 60})
    wins = 0
    rounds = 200
    for i in range(rounds):
        ch = storage.create_pet_challenge("k1", "k2")['challenge']
        out = storage.respond_pet_challenge(ch['id'], True, seed=i)
        if out['replay']['winner'] == 'a':
            wins += 1
    rate = wins / rounds
    check(0.35 <= rate <= 0.65,
          "the grinder wins %.2f of family fights -- level matching is not "
          "holding" % rate)


def test_a_family_fight_is_always_level_matched():
    reset_db()
    _pair(xp_a=5000, xp_b=0)
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    out = storage.respond_pet_challenge(ch['id'], True, seed=1)
    check(out['replay']['level_matched'] is True, "a family fight was not matched")
    check(out['replay']['a']['level'] == out['replay']['b']['level'],
          "levels differ inside a matched fight")


# --- the payout, and the absence of a table ------------------------------

def test_both_sides_are_paid_and_the_loser_meaningfully():
    reset_db()
    _pair()
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    out = storage.respond_pet_challenge(ch['id'], True, seed=2)
    check(len(out['awards']) == 2, "only one side was paid: %s" % out['awards'])
    lo = min(out['awards'].values())
    hi = max(out['awards'].values())
    check(lo >= storage.PET_PVP_LOSS_XP, "the loser got %d" % lo)
    check(lo >= hi * 0.5,
          "losing pays %d against %d -- too thin to be worth saying yes" % (lo, hi))


def test_the_pair_cap_stops_the_xp_and_not_the_fight():
    reset_db()
    _pair()
    cap = storage.pet_pvp_pair_cap()
    for i in range(cap):
        ch = storage.create_pet_challenge("k1", "k2")['challenge']
        out = storage.respond_pet_challenge(ch['id'], True, seed=i)
        check(not out['capped'], "capped early at %d" % (i + 1))
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    out = storage.respond_pet_challenge(ch['id'], True, seed=99)
    check(out['capped'], "the pair cap never engaged")
    check(not out['awards'], "a capped fight still paid: %s" % out['awards'])
    check(out['replay']['turns'], "the cap refused the fight itself")


def test_the_pair_cap_is_per_pair():
    reset_db()
    _pair()
    storage.add_member({"id": "k3", "name": "Cleo", "role": "child",
                        "color_code": "#a855f7", "is_child": True})
    storage.create_pet("k3", "Mossy", {'body': 'round', 'top': 'fin'}, {}, 'leaf')
    for i in range(storage.pet_pvp_pair_cap() + 1):
        ch = storage.create_pet_challenge("k1", "k2")['challenge']
        storage.respond_pet_challenge(ch['id'], True, seed=i)
    ch = storage.create_pet_challenge("k1", "k3")['challenge']
    out = storage.respond_pet_challenge(ch['id'], True, seed=1)
    check(not out['capped'],
          "one pairing used up another pairing's allowance")


def test_there_is_no_scoreboard_anywhere():
    """No ladder, no ranking, no win-loss record. If one ever appears it will
    appear here first."""
    import main
    reset_db()
    _pair()
    for i in range(3):
        ch = storage.create_pet_challenge("k1", "k2")['challenge']
        storage.respond_pet_challenge(ch['id'], True, seed=i)
    banned = ('wins', 'losses', 'record', 'ranking', 'rank', 'streak',
              'leaderboard', 'standings')
    payloads = [main.pet_challenges_endpoint(member_id="k1"),
                main.pet_battles_endpoint(member_id="k1"),
                main.list_pets_endpoint(member_id="k1"),
                main.pet_xp_endpoint("k1")]
    for payload in payloads:
        blob = repr(payload).lower()
        for word in banned:
            check(('"%s"' % word) not in blob and ("'%s'" % word) not in blob,
                  "a %s appeared in an API payload" % word)
    import datetime
    from services import home_board
    tile = home_board._BUILDERS['pets'](datetime.datetime.now(), config={})
    blob = repr(tile).lower()
    for word in banned:
        check(("'%s'" % word) not in blob, "a %s appeared on the pets card" % word)


def test_both_children_own_the_battle():
    reset_db()
    _pair()
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    storage.respond_pet_challenge(ch['id'], True, seed=4)
    check(len(storage.get_pet_battles("k1")) == 1, "the challenger lost the battle")
    check(len(storage.get_pet_battles("k2")) == 1,
          "the child who accepted cannot see the fight they were in")


def test_a_family_battle_replays_from_its_seed_like_any_other():
    reset_db()
    _pair()
    ch = storage.create_pet_challenge("k1", "k2")['challenge']
    out = storage.respond_pet_challenge(ch['id'], True, seed=77)
    again = storage.replay_pet_battle(out['battle']['id'])
    check(again == out['replay'], "a family battle did not replay identically")


# --- the surfaces ---------------------------------------------------------

def test_quiet_hours_silence_the_ping_and_not_the_invitation():
    """Silencing a notification is kindness. Deleting the thing it was about
    is not."""
    import main
    reset_db()
    _pair()
    storage.patch_settings({'kid_quiet_hours_enabled': True,
                            'kid_quiet_start': '00:00', 'kid_quiet_end': '23:59'})
    res = main.create_pet_challenge_endpoint(
        main.PetChallengeRequest(from_member="k1", to_member="k2"))
    check(res['notified'] is False, "a ping went out during quiet hours")
    check(storage.get_pet_challenges("k2"),
          "quiet hours ate the invitation itself")
    storage.patch_settings({'kid_quiet_hours_enabled': False})


def test_the_hand_path_and_both_agent_stacks():
    from services import agent_tools, auth
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'templates', 'components')
    overlay = open(os.path.join(base, 'pet_battle.html'), encoding='utf-8').read()
    for needle in ('challenge(', 'answer(ch, true)', 'answer(ch, false)', 'rivals'):
        check(needle in overlay, "the overlay has no hand path for %s" % needle)
    for tool in ('challenge_pet_battle', 'get_pet_status'):
        check(tool in agent_tools.TOOL_SCHEMAS, "%s missing from the loop's schemas" % tool)
        check(tool in agent_tools.TOOL_HANDLERS, "%s missing from the loop's handlers" % tool)
    router = open(os.path.join(os.path.dirname(base), '..', 'services',
                               'agent_router.py'), encoding='utf-8').read()
    for tool in ('challenge_pet_battle', 'get_pet_status'):
        check('func_name == "%s"' % tool in router,
              "%s is not wired into the chat widget's stack" % tool)
    for method, path in (('POST', '/api/pets/challenge'),
                         ('POST', '/api/pets/challenge/{challenge_id}/respond'),
                         ('GET', '/api/pets/challenges')):
        check(auth.resolve(method, path) is not None,
              "%s %s is unclassified" % (method, path))


def run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        try:
            t()
            print("  ok   %s" % t.__name__)
        except Exception:
            failed += 1
            print("  FAIL %s" % t.__name__)
            traceback.print_exc()
    print("%d/%d passed" % (len(tests) - failed, len(tests)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
