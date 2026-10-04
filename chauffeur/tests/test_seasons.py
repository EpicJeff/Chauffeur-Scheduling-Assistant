"""Seasons and the per-reward switch (services/seasons.py).

The family's ask: seasonal rewards should not sit in the store all year, each
reward needs its own on/off, and chores and rewards both want date ranges --
summer, the cool months, the holidays -- so they show only then.

Promises, run against the real endpoints:

  * A WINDOW RECURS EVERY YEAR, inclusive both ends, and one whose start is
    after its end wraps New Year. No window is all year.
  * OUT OF SEASON (or switched off) HIDES FROM THE FAMILY and refuses the ask
    -- claim, redeem, pledge -- while the Chores page still lists every row.
  * WORK UNDER WAY IS NEVER YANKED: a chore done-and-waiting or claimed out
    of the pot stays visible after its season ends; an owner's standing job
    and the open pot go quiet.
  * NOTHING IS TAKEN: switching off or leaving season deletes nothing, and an
    editor that never sends a season cannot wipe one out.

Run from chauffeur/:  python tests/test_seasons.py
"""
import atexit
import datetime
import os
import shutil
import sys
import tempfile
import time
import traceback

_TMP = tempfile.mkdtemp(prefix="chauffeur_seasons_test_")
os.environ["CHAUFFEUR_DATA_DIR"] = _TMP
atexit.register(lambda: shutil.rmtree(_TMP, ignore_errors=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import storage  # noqa: E402
from services import seasons  # noqa: E402

D = datetime.date


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def reset_db():
    with storage.db_lock:
        for name, val in list(vars(storage).items()):
            if name.endswith("_table"):
                val.truncate()
    storage.patch_settings({'kid_quiet_start': '00:00', 'kid_quiet_end': '00:00',
                            'rewards_enabled': True})


def _mmdd(days):
    d = D.today() + datetime.timedelta(days=days)
    return '%02d-%02d' % (d.month, d.day)


IN = {'season_start': _mmdd(-1), 'season_end': _mmdd(1)}
OUT = {'season_start': _mmdd(10), 'season_end': _mmdd(20)}


def _family():
    for mid, nm, role in (("k1", "Ada", "child"), ("mom", "Mom", "parent")):
        storage.add_member({"id": mid, "name": nm, "role": role,
                            "color_code": "#3b82f6", "is_child": role == "child",
                            "created_at": time.time()})
    storage.adjust_points("k1", 500, "seed")


def _http(fn, *a, **kw):
    from fastapi import HTTPException
    try:
        return fn(*a, **kw), None
    except HTTPException as e:
        return None, e


# --- the window ----------------------------------------------------------------

def test_window_is_yearly_inclusive_and_wraps():
    summer = {'season_start': '06-01', 'season_end': '08-31'}
    check(seasons.in_season(summer, D(2026, 6, 1)) and seasons.in_season(summer, D(2031, 8, 31)),
          "the ends of a season are not inclusive, or the year leaked in")
    check(not seasons.in_season(summer, D(2026, 9, 1)), "September is not summer")
    hol = {'season_start': '11-15', 'season_end': '01-05'}
    for d in (D(2026, 11, 15), D(2026, 12, 31), D(2027, 1, 1), D(2027, 1, 5)):
        check(seasons.in_season(hol, d), "the holidays did not wrap New Year at %s" % d)
    check(not seasons.in_season(hol, D(2027, 1, 6)), "the holidays never ended")
    check(seasons.in_season({}, D(2026, 2, 3)) and
          seasons.in_season({'season_start': '06-01'}, D(2026, 2, 3)),
          "no window (or half of one) must mean all year")
    check(seasons.label(hol) == 'Nov 15 – Jan 5', "label: %r" % seasons.label(hol))


def test_clean_refuses_what_a_parent_could_mistype():
    check(seasons.clean('', '') == (None, None), "blank should be all year")
    check(seasons.clean('06-01', '08-31') == ('06-01', '08-31'),
          "a valid window did not survive")
    check(seasons.clean('02-29', '03-10') == ('02-29', '03-10'), "Feb 29 is a real date")
    for bad in (('06-01', ''), ('02-30', '03-01'), ('13-01', '01-01'), ('06-01', '06-01')):
        try:
            seasons.clean(*bad)
            raise AssertionError("accepted %r" % (bad,))
        except ValueError:
            pass


def test_work_under_way_is_never_yanked():
    today = D(2026, 1, 10)
    summer = {'season_start': '06-01', 'season_end': '08-31'}
    rule = lambda **kw: seasons.chore_offered(dict(summer, **kw), today)
    check(not rule(state='open'), "the out-of-season pot is still offered")
    check(not rule(state='verified'), "last period's finished row is still offered")
    check(not rule(state='claimed', owner='k1'), "an owner's job sits on their list all winter")
    check(rule(state='done'), "a done chore vanished before a parent could verify it")
    check(rule(state='claimed'), "a child's claim vanished mid-job")


# --- chores through the endpoints -----------------------------------------------

def test_chores_out_of_season_hide_from_the_family_not_the_editor():
    import main
    from fastapi import BackgroundTasks
    reset_db()
    _family()
    _, err = _http(main.create_chore, main.ChoreCreateRequest(title='Mow the lawn', **OUT),
                   BackgroundTasks())
    check(err is None, "a seasonal chore could not be created: %s" % err)
    main.create_chore(main.ChoreCreateRequest(title='Shovel snow', **IN), BackgroundTasks())
    main.create_chore(main.ChoreCreateRequest(title='Dishes'), BackgroundTasks())
    family = {c['title'] for c in main.list_chores()}
    check(family == {'Shovel snow', 'Dishes'}, "family sees %s" % family)
    editor = {c['title']: c for c in main.list_chores(manage=True)}
    check(set(editor) == {'Mow the lawn', 'Shovel snow', 'Dishes'}, "the editor lost a row")
    mow = editor['Mow the lawn']
    check(mow['in_season'] is False and mow['offered'] is False and mow['season_label'],
          "the editor cannot say why the row is quiet: %s" % mow)
    _, err = _http(main.claim_chore_endpoint, mow['id'], main.ChoreMemberRequest(member_id='k1'))
    check(err is not None and err.status_code == 409, "an out-of-season chore was claimed")
    # Argyle sees the family's list, not the editor's
    from services import agent_tools_v2 as v2
    check('Mow the lawn' not in v2.list_chores().get('message', ''), "Argyle lists it out of season")


def test_an_editor_that_never_sends_a_season_keeps_it():
    import main
    from fastapi import BackgroundTasks
    reset_db()
    _family()
    c = main.create_chore(main.ChoreCreateRequest(title='Rake leaves', **OUT), BackgroundTasks())
    main.edit_chore(c['id'], main.ChoreCreateRequest(title='Rake the leaves'))
    got = storage.get_chore(c['id'])
    check(got['season_start'] == OUT['season_start'], "an old editor wiped the season")
    main.edit_chore(c['id'], main.ChoreCreateRequest(title='Rake the leaves',
                                                     season_start=None, season_end=None))
    check(storage.get_chore(c['id']).get('season_start') is None,
          "clearing the season to all year did not take")
    _, err = _http(main.edit_chore, c['id'],
                   main.ChoreCreateRequest(title='x', season_start='02-30', season_end='03-01'))
    check(err is not None and err.status_code == 400 and 'real dates' in err.detail,
          "a bad date was not refused in words: %s" % err)


# --- rewards --------------------------------------------------------------------

def test_each_reward_has_its_own_switch():
    import main
    from fastapi import BackgroundTasks
    reset_db()
    _family()
    ice = main.create_reward(main.RewardRequest(title='Ice cream', cost=30))
    pool = main.create_reward(main.RewardRequest(title='Pool day', cost=40, **OUT))
    goal = main.create_reward(main.RewardRequest(title='Movie Night', cost=100, pooled=True))
    check(ice['active'] is True, "a new reward is not on")
    check({r['title'] for r in main.list_rewards()} == {'Ice cream', 'Movie Night'},
          "the out-of-season reward is in the store")

    # a request and a pledge already waiting, then both switched off
    rid = storage.request_redemption(ice['id'], 'k1')
    check(storage.contribute_to_pool(goal['id'], 'k1', 20)[0] == 'ok', "seed pledge")
    main.set_reward_active(ice['id'], main.RewardActiveRequest(active=False))
    main.set_reward_active(goal['id'], main.RewardActiveRequest(active=False))
    check(main.list_rewards() == [], "switched-off rewards are still in the store")
    editor = {r['title']: r for r in main.list_rewards(manage=True)}
    check(len(editor) == 3 and editor['Ice cream']['active'] is False
          and editor['Pool day']['in_season'] is False,
          "the editor lost a row or its state: %s" % editor)

    _, err = _http(main.redeem_reward, ice['id'], main.ChoreMemberRequest(member_id='k1'),
                   BackgroundTasks())
    check(err is not None and err.status_code == 409, "a switched-off reward was redeemed")
    _, err = _http(main.contribute_to_pool_endpoint, goal['id'],
                   main.PoolContributeRequest(member_id='k1', amount=5), BackgroundTasks())
    check(err is not None and err.status_code == 409, "a switched-off goal took a pledge")
    _, err = _http(main.redeem_reward, pool['id'], main.ChoreMemberRequest(member_id='k1'),
                   BackgroundTasks())
    check(err is not None and err.status_code == 409, "an out-of-season reward was redeemed")

    # nothing taken: the waiting request and the pledge are still there
    check(any(r['id'] == rid for r in storage.get_redemptions(state='pending')),
          "switching off dropped the waiting request")
    check(storage.get_pool_contributions(reward_id=goal['id']), "switching off dropped the pledge")

    # the wall and Argyle
    from services import home_board, agent_tools_v2 as v2
    check(home_board._tile_chores_goals(None) is None, "the wall shows a switched-off goal")
    check('Movie Night' not in v2.get_family_goals().get('message', ''),
          "Argyle lists a switched-off goal")

    # an edit that does not mention `active` leaves it alone
    main.edit_reward(ice['id'], main.RewardRequest(title='Ice cream!', cost=30))
    check(storage.get_rewards() and next(r for r in storage.get_rewards()
                                         if r['id'] == ice['id'])['active'] is False,
          "editing the title switched the reward back on")
    main.set_reward_active(ice['id'], main.RewardActiveRequest(active=True))
    check('Ice cream!' in {r['title'] for r in main.list_rewards()}, "switching on did not restore it")


def test_chores_page_has_the_hand_paths():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(here, 'templates', 'chores.html'), encoding='utf-8').read()
    check("setRewardActive(rw, $event.target.checked)" in src, "no per-reward switch on the page")
    check(src.count("{{ season_editor(") == 2, "the season picker is not on both forms")
    lanes = open(os.path.join(here, 'templates', 'components', 'chores_lanes.html'),
                 encoding='utf-8').read()
    check("api/chores${this.manageCatalog ? '?manage=1' : ''}" in lanes,
          "the Chores page would only ever list in-season chores")


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
