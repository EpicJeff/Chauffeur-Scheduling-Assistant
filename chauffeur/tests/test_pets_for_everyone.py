"""Pets for the whole household: discovery, the backfill, and grown-ups.

Four things, all of which were gaps rather than decisions:

  * A CRITTER STANDS WITH ITS PERSON. It appears in `effective_figure`, the
    one function every showcase surface already calls, so a pet turns up on
    the hearth, both sets of lanes, the home board, the editor card and the
    PWA's My Day from a single change.
  * NOBODY STARTS BEHIND. The avatar arc promised it; pets shipped without it.
    Lifetime chore points and routine history convert to XP exactly once.
  * EVERYONE PLAYS. A flat daily grant at the same rate for every member --
    adults have no chores to earn from, and giving it to them alone would have
    a child earning theirs with a broom while a parent collects for existing.
  * ADULTS CAN DRESS UP. Every unlock track reads zero for a parent forever,
    so the wardrobe was permanently shut to them. Granted by role -- and
    deliberately NOT celebrated, because confetti for a role grant is what
    would cheapen a child's earned one.

Run from chauffeur/:  python tests/test_pets_for_everyone.py
"""
import atexit
import base64
import os
import shutil
import sys
import tempfile
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_petsall_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import avatar_catalog as cat  # noqa: E402
from services import avatar_render  # noqa: E402


PAW = chr(0x1F43E)   # what the pet doors used to show
EGG = chr(0x1F95A)   # what they show before a critter exists


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    avatar_render._EFFECTIVE_CACHE.clear()


def _member(mid, name, role='child'):
    storage.add_member({"id": mid, "name": name, "role": role,
                        "color_code": "#3b82f6", "is_child": role == 'child'})
    return storage.get_member(mid)


def _figure_svg(member):
    url = avatar_render.effective_figure(member)
    return base64.b64decode(url.split(',', 1)[1]).decode('utf-8') if url else ''


# --- the critter stands with its person -----------------------------------

def test_a_pet_appears_beside_its_owners_figure():
    reset_db()
    m = _member("k1", "Ada")
    check('critter-companion' not in _figure_svg(m),
          "a companion drew for a member with no pet")
    storage.create_pet("k1", "Rocket", {'body': 'wedge', 'top': 'horns'},
                       {'base_color': 'Coral'}, 'ember')
    svg = _figure_svg(m)
    check('critter-companion' in svg, "the critter is not standing with them")
    check(svg.count('<svg') == 2, "expected exactly one nested critter")


def test_restyling_or_retiring_redraws_the_figure():
    reset_db()
    m = _member("k1", "Ada")
    pet = storage.create_pet("k1", "Rocket", {'body': 'blob'}, {}, 'ember')['pet']
    first = _figure_svg(m)
    storage.update_pet(pet['id'], {'look': {'base_color': 'Lime'}})
    check(_figure_svg(m) != first,
          "a restyled critter kept the old picture -- the cache ignores the pet")
    storage.retire_pet(pet['id'])
    check('critter-companion' not in _figure_svg(m),
          "a retired critter is still standing there")


def test_a_figure_still_draws_when_pets_are_broken():
    """A pet must never be able to cost somebody their avatar."""
    reset_db()
    m = _member("k1", "Ada")
    storage.create_pet("k1", "Rocket")
    import services.pet_render as pr
    saved = pr.render_svg
    try:
        pr.render_svg = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        avatar_render._EFFECTIVE_CACHE.clear()
        svg = _figure_svg(m)
        check(svg.startswith('<svg'), "a broken pet took the whole figure down")
        check('critter-companion' not in svg, "a broken pet drew anyway")
    finally:
        pr.render_svg = saved
        avatar_render._EFFECTIVE_CACHE.clear()


# --- nobody starts behind -------------------------------------------------

def test_history_converts_to_xp_exactly_once():
    reset_db()
    _member("p1", "Dad", role='parent')
    _member("k1", "Ada")
    storage.add_chore({'id': 'c1', 'title': 'Dishes', 'points': 40,
                       'recurrence': 'once', 'state': 'open'})
    storage.claim_chore('c1', 'k1')
    storage.mark_chore_done('c1', 'k1')
    storage.verify_chore('c1', 'p1')
    # pretend pets shipped after all that work
    with storage.db_lock:
        storage.pet_xp_ledger_table.truncate()
    check(storage.get_points_earned("k1") == 40, "the history did not survive")
    first = storage.sync_pet_xp("k1")
    check(first['backfilled'] == 40,
          "lifetime chore points did not convert: %s" % first)
    again = storage.sync_pet_xp("k1")
    check(again['backfilled'] == 0, "the backfill ran twice")
    check(storage.pet_level("k1") > 1, "the backfill bought no level at all")


def test_routine_history_converts_too():
    reset_db()
    _member("k1", "Ada")
    from datetime import date, timedelta
    storage.add_routine({'id': 'r1', 'member_id': 'k1', 'title': 'Teeth'})
    for i in range(1, 6):
        day = (date.today() - timedelta(days=i)).isoformat()
        storage.set_routine_check('r1', 'k1', day, True)
    with storage.db_lock:
        storage.pet_xp_ledger_table.truncate()
    out = storage.sync_pet_xp("k1")
    check(out['backfilled'] > 0, "routine history converted to nothing")


def test_a_member_with_no_history_is_not_penalised_or_paid_twice():
    reset_db()
    _member("k1", "Ada")
    out = storage.sync_pet_xp("k1")
    check(out['backfilled'] == 0, "xp appeared from nowhere")
    check(out['daily'] > 0, "the daily grant did not land")


# --- everyone plays -------------------------------------------------------

def test_the_daily_grant_is_the_same_for_everyone_and_once_a_day():
    reset_db()
    _member("k1", "Ada")
    _member("p1", "Dad", role='parent')
    kid = storage.sync_pet_xp("k1")['daily']
    adult = storage.sync_pet_xp("p1")['daily']
    check(kid == adult == storage.pet_xp_daily_grant(),
          "the grant differs by role: kid %s adult %s" % (kid, adult))
    for _ in range(5):
        check(storage.sync_pet_xp("p1")['daily'] == 0,
              "the daily grant paid more than once in a day")


def test_chores_still_dwarf_the_daily_grant():
    """The grant must not undercut the reason to do anything."""
    reset_db()
    _member("p1", "Dad", role='parent')
    _member("k1", "Ada")
    storage.sync_pet_xp("k1")
    grant_only = storage.get_pet_xp_balance("k1")
    for i in range(3):
        cid = 'c%d' % i
        storage.add_chore({'id': cid, 'title': 'Job', 'points': 15,
                           'recurrence': 'once', 'state': 'open'})
        storage.claim_chore(cid, 'k1')
        storage.mark_chore_done(cid, 'k1')
        storage.verify_chore(cid, 'p1')
    earned = storage.get_pet_xp_balance("k1") - grant_only
    check(earned > grant_only,
          "a day of chores (%d) earns less than showing up (%d)"
          % (earned, grant_only))


def test_an_adult_can_hatch_train_and_be_levelled_by_the_grant():
    reset_db()
    _member("p1", "Dad", role='parent')
    check('pet' in storage.create_pet("p1", "Bruiser"), "a parent could not hatch")
    for _ in range(30):                       # a month of showing up
        with storage.db_lock:
            storage.pet_xp_ledger_table.insert(
                {'id': os.urandom(8).hex(), 'member_id': 'p1',
                 'delta': storage.pet_xp_daily_grant(), 'reason': 'daily',
                 'ref_id': 'daily', 'date_str': 'd%d' % _, 'note': None,
                 'ts': 0})
    check(storage.pet_level("p1") >= 5,
          "a month of daily grants only reached level %d" % storage.pet_level("p1"))
    check(storage.pet_training_budget("p1") > 0, "an adult has no training points")


# --- awarding by hand -----------------------------------------------------

def test_a_parent_can_award_xp_and_it_is_parents_only():
    import main
    from fastapi import HTTPException
    reset_db()
    _member("k1", "Ada")
    parent = _member("p1", "Dad", role='parent')
    token = storage.issue_member_token("p1") if hasattr(storage, 'issue_member_token') else None
    res = storage.adjust_pet_xp("k1", 120)
    check(res['balance'] == 120, "the award did not land: %s" % res)
    check(storage.pet_level("k1") > 1, "the award bought no level")
    try:
        main.adjust_pet_xp_endpoint(
            main.PetXpAdjustRequest(member_id="k1", delta=50), None)
        raise AssertionError("anybody could award xp")
    except HTTPException as e:
        check(e.status_code == 403, "wrong refusal: %s" % e.status_code)


def test_taking_xp_back_can_never_undo_a_level():
    reset_db()
    _member("k1", "Ada")
    storage.adjust_pet_xp("k1", 500)
    level = storage.pet_level("k1")
    storage.adjust_pet_xp("k1", -490)
    check(storage.pet_level("k1") == level,
          "taking xp back cost a level a child had already reached")
    check(storage.get_pet_xp_balance("k1") == 10, "the balance is wrong")


def test_the_award_tool_is_in_both_agent_stacks():
    from services import agent_tools, agent_tools_v2
    reset_db()
    _member("k1", "Ada")
    msg = agent_tools_v2.award_pet_xp("Ada", 40)['message']
    check('40' in msg and 'level' in msg.lower(), "bad spoken answer: %r" % msg)
    check('award_pet_xp' in agent_tools.TOOL_SCHEMAS
          and 'award_pet_xp' in agent_tools.TOOL_HANDLERS,
          "missing from the loop's stack")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    router = open(os.path.join(here, 'services', 'agent_router.py'),
                  encoding='utf-8').read()
    check('func_name == "award_pet_xp"' in router,
          "missing from the chat widget's stack")


def test_the_agent_cannot_reach_the_points_ledger_through_xp():
    from services import agent_tools_v2
    reset_db()
    _member("k1", "Ada")
    before = storage.get_points_balance("k1")
    agent_tools_v2.award_pet_xp("Ada", 999)
    check(storage.get_points_balance("k1") == before,
          "an xp award moved real-money points")


# --- adults can dress up --------------------------------------------------

def test_an_adult_owns_the_whole_wardrobe():
    reset_db()
    parent = _member("p1", "Dad", role='parent')
    storage.sync_avatar_unlocks("p1")
    owned = set(storage.get_avatar_unlocks("p1"))
    missing = [cat.item_id(i['slot'], i['key']) for i in cat.unlockable_items()
               if cat.item_id(i['slot'], i['key']) not in owned]
    check(not missing, "a parent is still locked out of %d items" % len(missing))


def test_a_role_grant_is_never_celebrated():
    """Confetti for a role grant is exactly what would cheapen a child's
    earned one."""
    reset_db()
    _member("p1", "Dad", role='parent')
    fresh = storage.sync_avatar_unlocks("p1")
    unlockables = {cat.item_id(i['slot'], i['key']) for i in cat.unlockable_items()}
    celebrated = [i for i in fresh if i in unlockables]
    check(not celebrated,
          "%d earned-tier items were queued for celebration" % len(celebrated))


def test_a_child_still_has_to_earn_theirs():
    reset_db()
    _member("k1", "Ada")
    storage.sync_avatar_unlocks("k1")
    owned = set(storage.get_avatar_unlocks("k1"))
    locked = [i for i in cat.unlockable_items()
              if cat.item_id(i['slot'], i['key']) not in owned]
    check(locked, "a child was handed the wardrobe -- the economy is gone")


# --- the doors ------------------------------------------------------------

def test_the_pwa_has_a_way_in_for_every_role():
    """My Day is the kid lens; adults never see it. The header is on every
    view for everybody, which is what a built-in feature needs."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(here, 'templates', 'app.html'), encoding='utf-8').read()
    head = app[:app.index('</header>')]
    check('openPetEditor' in head,
          "the PWA header has no way into pets, so an adult has none at all")
    check('openPetEditor' in app and 'openPetBattle' in app,
          "the PWA cannot reach the editor or the arena")
    editor = open(os.path.join(here, 'templates', 'components',
                               'avatar_editor.html'), encoding='utf-8').read()
    check('openPetEditor' in editor,
          "the avatar editor -- reachable from every showcase surface -- has "
          "no door to the critter standing next to the figure")


def test_the_door_to_a_pet_is_the_pet():
    """A paw print named an anatomy none of the critters have -- they are
    blobs -- and it said the same thing to a child who has hatched one as to
    a child who never has. The button shows the creature now, and an EGG
    before there is one: the invitation the board card already makes."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(here, 'templates', 'app.html'), encoding='utf-8').read()
    head = app[:app.index('</header>')]
    check(PAW not in head, "the header still shows a paw print")
    check('pet-face' in head and EGG in head,
          "the header door draws neither the critter nor an egg")
    check('petFaceSrc' in app and '/svg?crop=chip' in app,
          "nothing in the PWA fetches the critter's art for the door")
    check('paintPetFace' in app, "the door is never painted")
    # The whole of paintIdentityChip, which every identity change runs
    # through -- driver, passenger, restore-on-open and avatar-saved alike.
    chip = app[app.index('function paintIdentityChip'):]
    chip = chip[:chip.index('async function')]
    check('updatePetBadge' in chip,
          "the door is painted only from My Day, which no adult ever sees")
    check("addEventListener('pet-saved'" in app,
          "hatching or redressing leaves the door showing the old creature")
    myday = app[app.index('function kidHeader'):app.index('function updatePetBadge')]
    check(PAW not in myday, "My Day still labels the critter with a paw print")
    check('petFaceSrc' in myday, "My Day's chip does not draw the critter")

    editor = open(os.path.join(here, 'templates', 'components',
                               'avatar_editor.html'), encoding='utf-8').read()
    check(PAW not in editor, "the avatar editor still shows a paw print")
    check('petId' in editor and EGG in editor,
          "the avatar editor's door draws neither the critter nor an egg")


def test_the_editor_is_told_which_critter_to_draw():
    """The avatar editor holds a door to the pet but knew nothing about it.
    One lookup on a payload it already fetches -- not a second round trip."""
    import main
    reset_db()
    _member("k1", "Ada")
    before = main.get_avatar_endpoint("k1")
    check('pet_id' in before and before['pet_id'] is None,
          "a member with no critter gets no honest empty answer")
    storage.create_pet("k1", "Rocket", {}, {}, 'ember')
    after = main.get_avatar_endpoint("k1")
    check(after.get('pet_id'), "the avatar payload does not name the critter")
    check(after.get('pet_name') == 'Rocket',
          "the avatar payload cannot label the door")
    svg = main.pet_svg_endpoint(after['pet_id'], crop='chip')
    check(b'<svg' in svg.body, "the door's art does not render")


# --- the balance is visible, and it says what it is for -------------------

def test_the_hint_is_silent_until_there_is_something_to_buy():
    """A badge that is always lit stops meaning anything."""
    reset_db()
    _member("k1", "Ada")
    check(storage.pet_spend_hint("k1")['hint'] == 'hatch a critter',
          "somebody with no critter was not pointed at hatching one")
    storage.create_pet("k1", "Rocket", {}, {}, 'ember')
    check(storage.pet_spend_hint("k1")['hint'] is None,
          "a broke owner was nudged to spend nothing")
    storage.grant_pet_xp("k1", storage.PET_MOVE_COST, 'grant')
    check(storage.pet_spend_hint("k1")['hint'] == 'teach a new move',
          "an affordable move was not surfaced")
    storage.grant_pet_xp("k1", storage.PET_SLOT_COST, 'grant')
    check(storage.pet_spend_hint("k1")['hint'] == 'get another critter',
          "an affordable slot was not surfaced")


def test_a_pet_that_knows_everything_stops_nagging():
    reset_db()
    _member("k1", "Ada")
    from services import pet_catalog
    pet = storage.create_pet("k1", "Rocket", {}, {}, 'ember')['pet']
    storage.grant_pet_xp("k1", storage.PET_MOVE_COST * 40, 'grant')
    for m in pet_catalog.moves():
        storage.learn_pet_move(pet['id'], m['key'])
    hint = storage.pet_spend_hint("k1")['hint']
    check(hint != 'teach a new move',
          "a critter that knows every move is still being told to learn one")


def test_the_balance_reaches_the_surfaces_that_show_it():
    import datetime
    import main
    from services import home_board
    reset_db()
    _member("k1", "Ada")
    storage.create_pet("k1", "Rocket", {}, {}, 'ember')
    storage.grant_pet_xp("k1", 400, 'grant')
    roster = main._public_member(storage.get_member("k1"))
    check(roster.get('pet_xp') == 400, "the PWA roster has no balance")
    check('pet_hint' in roster, "the PWA roster cannot nudge")
    tile = home_board._BUILDERS['pets'](datetime.datetime.now(), config={})
    row = tile['members'][0]
    check(row.get('xp') == 400, "the board card has no balance")
    check(main.pet_xp_endpoint("k1").get('hint') is not None
          or storage.pet_spend_hint("k1")['hint'] is None,
          "the xp endpoint disagrees with the hint")


def test_every_surface_that_should_show_xp_does():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = open(os.path.join(here, 'templates', 'app.html'), encoding='utf-8').read()
    check('pet-xp-badge' in app and 'pet_xp' in app,
          "the PWA never shows a balance")
    head = app[:app.index('</header>')]
    check('pet-xp-badge' in head,
          "the balance is not on the header, so an adult never sees it")
    editor = open(os.path.join(here, 'templates', 'components',
                               'pet_editor.html'), encoding='utf-8').read()
    band = editor[:editor.index('<!-- tabs -->')]
    check('balance' in band,
          "the balance is still buried in one tab instead of the preview band")
    card = open(os.path.join(here, 'templates', 'components',
                             'board_tile_body.html'), encoding='utf-8').read()
    check('m.hint' in card, "the board card cannot nudge")


# --- the rules, where a child can read them ------------------------------

def test_the_guide_exists_and_is_reachable_from_the_game():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    comp = os.path.join(here, 'templates', 'components')
    guide = open(os.path.join(comp, 'pet_guide.html'), encoding='utf-8').read()
    check('openPetGuide' in guide and 'maybeOpenPetGuide' in guide,
          "the guide cannot be opened")
    for page in ('app.html', 'home.html', 'chores.html', 'routines.html'):
        src = open(os.path.join(here, 'templates', page), encoding='utf-8').read()
        check("components/pet_guide.html" in src,
              "%s cannot show the rules" % page)
    for host in ('pet_editor.html', 'pet_battle.html'):
        src = open(os.path.join(comp, host), encoding='utf-8').read()
        check('openPetGuide' in src, "%s has no way to the rules" % host)


def test_the_guide_states_the_promises_it_has_to_state():
    """The four things a child most needs to know are the four this arc spent
    the most effort making true. If a rule ever changes, this fails and the
    words get changed with it."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    g = open(os.path.join(here, 'templates', 'components', 'pet_guide.html'),
             encoding='utf-8').read().lower()
    for phrase, why in (
            ('never costs anything', 'that looks are free'),
            ('level-matched', 'that a family fight ignores who did more chores'),
            ('no best element', 'that no element is better than another'),
            ('even when you lose', 'that losing still pays'),
            ('leaderboard', 'that nobody keeps score')):
        check(phrase in g, "the guide never tells a child %s" % why)


def test_the_ring_is_drawn_rather_than_x_for_ed():
    """A <template x-for> inside an <svg> is parsed in the HTML namespace, so
    Alpine clones <line> and <circle> as HTML elements and the browser draws
    nothing at all -- silently. The ring is built as a string for that reason
    and must stay that way."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    g = open(os.path.join(here, 'templates', 'components', 'pet_guide.html'),
             encoding='utf-8').read()
    check('ringSvg()' in g, "the ring builder is gone")
    svg_start = g.index('<svg')
    if svg_start > 0:
        pass
    check('<svg viewBox' not in g,
          "an inline <svg> is back in the markup -- if it holds an x-for it "
          "will render as an empty box")


# --- one PIN gate ---------------------------------------------------------

def test_every_overlay_goes_through_the_one_gate():
    """A child tapped their face and entered a PIN, opened their critter and
    entered it again, went to battle and entered it a third time. Each overlay
    was gating on its own and none of them told the next: the kiosk pad
    RETURNED a token and never stored it, while the PWA's own sign-in did."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    comp = os.path.join(here, 'templates', 'components')
    cc = open(os.path.join(comp, 'control_center.html'), encoding='utf-8').read()
    check('chfMemberToken' in cc and 'chfStoreMemberToken' in cc,
          "the shared gate is gone from control_center")
    check("localStorage.setItem('chauffeur_member_token'" in cc,
          "the gate does not STORE the token, so the next overlay re-prompts")
    for f in ('avatar_editor.html', 'pet_editor.html', 'pet_battle.html'):
        src = open(os.path.join(comp, f), encoding='utf-8').read()
        opener = src[src.index('window.open'):src.index('dispatchEvent')]
        check('chfMemberToken' in opener,
              "%s still gates on its own" % f)
        check('api/members/' not in opener,
              "%s still has a PIN pad of its own" % f)


def test_a_cancelled_pin_does_not_open_the_overlay_anyway():
    """The gate answers '' for "no gate needed" and null for "asked and
    refused". A caller handed only a member id cannot tell those apart itself,
    and treating both as falsy opened the editor for somebody who backed
    out."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    comp = os.path.join(here, 'templates', 'components')
    cc = open(os.path.join(comp, 'control_center.html'), encoding='utf-8').read()
    check("if (!member.has_pin) return '';" in cc,
          "the gate no longer distinguishes 'no PIN needed' from 'refused'")
    for f in ('avatar_editor.html', 'pet_editor.html', 'pet_battle.html'):
        src = open(os.path.join(comp, f), encoding='utf-8').read()
        check('token === null' in src,
              "%s does not check for a refusal specifically" % f)


def test_a_stale_token_is_dropped_rather_than_failing_forever():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ed = open(os.path.join(here, 'templates', 'components', 'pet_editor.html'),
              encoding='utf-8').read()
    check('chfClearMemberToken' in ed,
          "a 403 leaves the dead token in place, so every save fails quietly")


# --- the shelf is a door that swings both ways ----------------------------

def test_a_shelved_critter_can_actually_come_back():
    """The retire button has always promised the creature 'can come back any
    time'. Nothing in the app ever asked for a retired pet, so it could
    not."""
    import main
    reset_db()
    _member("k1", "Ada")
    pet = storage.create_pet("k1", "Rocket", {'body': 'wedge'}, {}, 'ember')['pet']
    main.retire_pet_endpoint(pet['id'], main.PetRetireRequest(retired=True))
    check(not main.list_pets_endpoint(member_id="k1")['pets'],
          "a shelved critter is still on the shelf list")
    shelved = main.list_pets_endpoint(member_id="k1", include_retired=True)['pets']
    check(len(shelved) == 1 and shelved[0]['active'] is False,
          "the shelf cannot be listed at all")
    check(shelved[0].get('svg', '').startswith('<svg'),
          "a shelved critter has no picture, so the shelf cannot draw it")
    back = main.retire_pet_endpoint(pet['id'], main.PetRetireRequest(retired=False))
    check(back['pet']['active'] is True, "it could not come back")
    check(len(storage.get_pets("k1")) == 1, "it came back but is not active")


def test_bringing_one_back_over_the_limit_is_refused_in_words():
    import main
    from fastapi import HTTPException
    reset_db()
    _member("k1", "Ada")
    first = storage.create_pet("k1", "Rocket")['pet']
    main.retire_pet_endpoint(first['id'], main.PetRetireRequest(retired=True))
    storage.create_pet("k1", "Second")
    try:
        main.retire_pet_endpoint(first['id'], main.PetRetireRequest(retired=False))
        raise AssertionError("a critter came back with no slot to come back to")
    except HTTPException as e:
        check(e.status_code == 400 and 'slot' in (e.detail or '').lower(),
              "the refusal does not say why: %s" % e.detail)
    check(storage.get_pet(first['id']) is not None,
          "the refusal ate the record")


def test_the_editor_can_reach_the_shelf():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ed = open(os.path.join(here, 'templates', 'components', 'pet_editor.html'),
              encoding='utf-8').read()
    check('include_retired=true' in ed,
          "the editor never asks for shelved critters, so it cannot show them")
    check('bringBack(' in ed and 'On the shelf' in ed,
          "the editor has no way to bring one back")


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
