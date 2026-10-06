"""The dish grid and its editor sheet, actually served (v2.499.249).

The Meals tab's dish list was one long column: every row carried a dozen open
controls whether anything was set or not. It became a wrapping grid of the
wall's week-board cards, with every control moved into one editor sheet the
card opens. Three claims only a browser can check:

  - the grid wraps (several cards to a row) and a dish whose picture fails to
    load shows the type tint, not a broken image;
  - a tap opens the sheet, and the controls that used to live on the row are
    all there and still write (Whole meal round-trips to the server);
  - the grid's own filter narrows by the family's categories.

Run from chauffeur/:  python tests/test_dish_grid_live.py
"""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='dish_grid_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app

from services import storage


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


CATS = [('cat-protein', 'protein', True), ('cat-vegetables', 'vegetables', False),
        ('cat-starches', 'starches/carbs', False)]


def seed():
    from models.schemas import Dish
    storage.update_settings({'household_headcount': 4})
    for i, (cid, name, main) in enumerate(CATS):
        storage.save_dish_category({'id': cid, 'name': name, 'min_per_plate': 1,
                                    'max_per_plate': 1, 'order': i, 'is_main': main})
    for kw in (
            dict(name='Grilled chicken', category_ids=['cat-protein'], prep_ahead_mins=5,
                 finish_mins=10, tags=['kid-favorite']),
            dict(name='Turkey meatballs', category_ids=['cat-protein'], serves=12),
            dict(name='Rice', category_ids=['cat-starches']),
            dict(name='Steamed broccoli', category_ids=['cat-vegetables'],
                 image_url='/static/does-not-exist.jpg', image_source='stock'),
            dict(name='Black beans', category_ids=['cat-protein', 'cat-starches']),
            dict(name='Tacos', type='meal'),
            dict(name='Strawberry shortcake', scope='occasion')):
        storage.add_dish(Dish(**kw).model_dump())


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        handle = served.browser()
        with handle as page:
            page.set_viewport_size({'width': 1400, 'height': 900})
            page.goto(served.url('meals'), wait_until='networkidle')
            page.wait_for_timeout(1500)

            cards = page.locator('.dish-card')
            # The occasion dish is hidden behind its toggle, never gone.
            check(cards.count() == 6, f'expected 6 everyday dishes, got {cards.count()}')
            tops = page.evaluate("""() => [...document.querySelectorAll('.dish-card')]
                .map(c => Math.round(c.getBoundingClientRect().top))""")
            check(tops.count(tops[0]) >= 4, f'the grid does not wrap across the row: {tops}')

            broccoli = page.locator('.dish-card', has_text='Steamed broccoli')
            check(broccoli.locator('img').count() == 0,
                  'a picture that failed to load is still in the card')

            page.get_by_role('button', name='Show occasion dishes (1)').click()
            page.wait_for_timeout(200)
            check(page.locator('.dish-card').count() == 7, 'the occasion toggle did not show it')

            # The family's categories filter the grid.
            page.click('[data-dish-filter="cat-starches"]')
            page.wait_for_timeout(200)
            names = page.locator('.dish-card').all_inner_texts()
            check(len(names) == 2 and all(('Rice' in n or 'Black beans' in n) for n in names),
                  f'the starches filter showed {names}')
            page.click('[data-dish-filter="all"]')
            page.wait_for_timeout(200)

            # The sheet carries every control the row used to.
            page.locator('.dish-card', has_text='Grilled chicken').click()
            page.wait_for_timeout(300)
            sheet = page.get_by_role('dialog', name='Grilled chicken')
            check(sheet.is_visible(), 'tapping a card did not open its editor')
            for label in ('Use my photo', 'Whole meal', 'protein', 'By the tray', 'Any night',
                          'Occasions only', '+ Always comes with', '+ Only served with',
                          '+ Add a prep step', '+ Add a tag', 'Delete this dish'):
                check(sheet.get_by_text(label, exact=True).count() >= 1,
                      f'the editor sheet lost "{label}"')
            check(sheet.get_by_text('kid-favorite', exact=True).count() == 1, 'the dish tag is not in the sheet')

            sheet.get_by_role('button', name='Whole meal').click()
            page.wait_for_timeout(1200)
            saved = [d for d in storage.get_dishes() if d['name'] == 'Grilled chicken'][0]
            check(saved.get('type') == 'meal', f'Whole meal did not save: {saved.get("type")}')

            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
            check(page.get_by_role('dialog').count() == 0, 'Escape did not close the sheet')

            # Leftovers read off the card: 12 servings in a small household.
            meat = page.locator('.dish-card', has_text='Turkey meatballs').inner_text()
            check('night' in meat, f'the leftover nights flag is missing: {meat!r}')

            # The broccoli's picture 404s on purpose; that is the fallback
            # being tested, not a fault.
            errors = [e for e in handle.errors if 'Failed to load resource' not in e]
            check(not errors, f'page errors: {errors[:3]}')
    finally:
        served.stop()
    print('test_dish_grid_live OK')


if __name__ == '__main__':
    main()
