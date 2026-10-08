"""The feature switches, in a real browser: the pages still run with them off.

The unit file proves what the server hides. This proves the half only a
browser can see: with the pet editor never included and the rewards list
empty, the PWA, the wall and the chores page still boot without a single
script error, nothing draws a critter door, and a parent's tap on the switch
actually lands in settings.

Run from chauffeur/:  python tests/test_household_features_live.py [--out DIR]
"""
import os
import sys
import tempfile
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_features_live_')

from live_app import live_app  # noqa: E402
from services import storage  # noqa: E402

OUT = None
if '--out' in sys.argv:
    OUT = sys.argv[sys.argv.index('--out') + 1]
    os.makedirs(OUT, exist_ok=True)


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    for mid, nm, role in (("k1", "Ada", "child"), ("k2", "Ben", "child"),
                          ("mom", "Mom", "parent")):
        storage.add_member({"id": mid, "name": nm, "role": role,
                            "color_code": "#3b82f6", "is_child": role == "child",
                            "created_at": time.time()})
    storage.adjust_points("k1", 120, "seed")
    storage.create_pet("k1", "Rocket", {'body': 'wedge', 'top': 'horns'}, {}, 'ember')
    storage.add_reward({"id": "plain", "title": "Ice cream", "description": "",
                        "cost": 30, "pooled": False, "min_share": 0,
                        "created_at": time.time()})
    storage.add_reward({"id": "goal", "title": "Movie Night", "description": "",
                        "cost": 150, "pooled": True, "min_share": 0,
                        "created_at": time.time()})
    storage.patch_settings({'critters_enabled': False, 'rewards_enabled': False})


def _shot(page, name):
    if OUT:
        page.screenshot(path=os.path.join(OUT, name), full_page=True)


def run():
    served = live_app(seed)
    if served is None:
        return 0
    failed = 0
    scenarios = []

    def scenario(fn):
        scenarios.append(fn)
        return fn

    @scenario
    def chores_page_shows_both_switches_off_and_saves_a_tap():
        b = served.browser()
        with b as page:
            page.goto(served.url('chores'))
            page.wait_for_selector('#page-settings-gear')
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="chores"][data-open]')
            page.wait_for_selector('#petxp')
            crit = page.locator('input[x-model="features.critters_enabled"]')
            rew = page.locator('input[x-model="features.rewards_enabled"]')
            page.wait_for_function("() => document.querySelector('#rewards') !== null")
            check(not crit.is_checked() and not rew.is_checked(),
                  "the switches do not show the stored OFF")
            # the catalog editor still sees the stock while the shop is closed
            page.wait_for_selector('#rewards h4:has-text("Ice cream")')
            _shot(page, 'chores_switches_off.png')
            rew.click()
            page.wait_for_function(
                "() => fetch('api/settings').then(r => r.json()).then(s => s.rewards_enabled === true)")
            check(storage.get_settings().get('rewards_enabled') is True,
                  "the tap never reached settings")
            rew.click()
            page.wait_for_function(
                "() => fetch('api/settings').then(r => r.json()).then(s => s.rewards_enabled === false)")
            check(storage.get_settings().get('rewards_enabled') is False,
                  "switching back off did not save")
            check(not b.errors, "chores page script errors: %s" % b.errors)

    @scenario
    def a_reward_switches_off_and_a_chore_gets_a_season_by_hand():
        storage.patch_settings({'rewards_enabled': True})
        b = served.browser()
        with b as page:
            page.goto(served.url('chores'))
            page.wait_for_selector('#page-settings-gear')
            page.click('#page-settings-gear')
            page.wait_for_selector('[data-settings-for~="chores"][data-open]')
            page.wait_for_selector('#rewards h4:has-text("Ice cream")')
            box = page.locator('input[aria-label="Offer Ice cream"]')
            check(box.is_checked(), "a new reward does not show as on")
            box.click()
            page.wait_for_function(
                "() => fetch('api/rewards?manage=1').then(r => r.json())"
                ".then(rs => rs.some(r => r.title === 'Ice cream' && r.active === false))")
            check(not any(r.get('title') == 'Ice cream' and r.get('active') is not False
                          for r in storage.get_rewards()), "the tap never reached the reward")
            if OUT:
                page.locator('#rewards').screenshot(path=os.path.join(OUT, 'rewards_rows.png'))
            page.click('[data-settings-for~="chores"] [aria-label="Close settings"]')
            page.wait_for_selector('[data-settings-for~="chores"]', state='hidden')
            # a chore with the Summer preset, saved through the form
            page.fill('input[placeholder="Take out the trash"]', 'Mow the lawn')
            page.locator('button:has-text("Summer")').first.click()
            page.locator('button:has-text("Add Chore")').click()
            page.wait_for_selector('h4:has-text("Mow the lawn")')
            row = [c for c in storage.get_all_chores() if c.get('title') == 'Mow the lawn']
            check(row and row[0].get('season_start') == '06-01' and row[0].get('season_end') == '08-31',
                  "the season did not save: %s" % row)
            page.wait_for_timeout(300)
            _shot(page, 'chores_seasons.png')
            check(not b.errors, "chores page script errors: %s" % b.errors)
        storage.patch_settings({'rewards_enabled': False})

    @scenario
    def the_pwa_boots_with_no_critter_doors():
        b = served.browser()
        with b as page:
            page.goto(served.url('app'))
            page.wait_for_load_state('networkidle')
            check(page.evaluate("() => window.chfFeatureOn('critters')") is False,
                  "the PWA does not know critters are off")
            check(page.evaluate("() => typeof window.openPetEditor") == 'undefined',
                  "the PWA still ships the critter editor")
            check(page.locator('#btn-pet').count() == 0, "the header door is still there")
            names = page.evaluate("() => typeof pwaFeatures === 'function' ? pwaFeatures().map(i => i.id) : []")
            check('critter' not in names, "the More directory still offers critters: %s" % names)
            _shot(page, 'pwa_critters_off.png')
            check(not b.errors, "PWA script errors: %s" % b.errors)

    @scenario
    def the_wall_board_boots_without_pet_or_goal_cards():
        b = served.browser()
        with b as page:
            page.goto(served.url('home?panel=true'))
            page.wait_for_load_state('networkidle')
            check(page.evaluate("() => typeof window.openPetEditor") == 'undefined',
                  "the wall still ships the critter editor")
            _shot(page, 'wall_features_off.png')
            check(not b.errors, "wall script errors: %s" % b.errors)

    try:
        for fn in scenarios:
            try:
                fn()
                print("  ok   %s" % fn.__name__)
            except Exception:
                failed += 1
                print("  FAIL %s" % fn.__name__)
                traceback.print_exc()
    finally:
        served.stop()
    print("%d/%d passed" % (len(scenarios) - failed, len(scenarios)))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
