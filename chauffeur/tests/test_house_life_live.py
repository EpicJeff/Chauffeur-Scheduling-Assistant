"""Family drawers and the bounded Study visit, through the served browser."""
from urllib.parse import urlparse, parse_qs
from test_house_live import live_app, _seed, check
from services import storage
from models.schemas import Chore, RoutineItem, PrepKit


def scenario_house_life():
    served = live_app()
    _seed()
    storage.add_member({'id': 'house-parent', 'name': 'Jordan', 'role': 'parent'})
    storage.set_member_pin('house-parent', '1234')
    personal = storage.create_member_token('house-parent')
    storage.add_chore(Chore(title='Feed the pets', owner='k1', state='claimed', claimed_by='k1').model_dump())
    storage.add_routine(RoutineItem(member_id='k1', title='Brush teeth', time_of_day='07:00').model_dump())
    storage.add_household_task({'id': 'house-task', 'title': 'Replace the air filter', 'due_date': '2020-01-01', 'status': 'open'})
    storage.add_prep_kit(PrepKit(id='house-kit', name='Soccer bag', items=['Water bottle'], keywords=['soccer'], per_person=False).model_dump())
    with served.browser() as page:
        def packs(route):
            response = route.fetch()
            data = response.json()
            data['mudroom'] = {'bags': 2, 'packing_known': True, 'calm': False, 'packs': [
                {'name': 'Practice', 'packed': 1, 'needed': 3, 'ready': False, 'attention': True},
                {'name': 'School', 'packed': 2, 'needed': 2, 'ready': True, 'attention': False}]}
            route.fulfill(response=response, json=data)
        page.route('**/api/house/state*', packs)
        page.goto(served.url('house?quality=low&panel=true'))
        page.wait_for_function('window.chfHouseState && chfHouseState() && window.Alpine')
        page.wait_for_function("document.querySelector('[data-house-action=packing] .house-life-count').textContent === '2'")
        for key, content in [('chores', 'Feed the pets'), ('routines', 'Brush teeth'),
                             ('programs', 'practice'), ('tasks', 'Replace the air filter'),
                             ('errands', 'Manage with parent PIN'), ('packing', 'Soccer practice')]:
            page.locator('[data-house-action="' + key + '"]').click()
            page.wait_for_function('(text) => document.querySelector(".house-life-body").innerText.includes(text)', arg=content)
            if key == 'packing':
                page.locator('.house-life-body .fd-pack-btn').first.click()
                page.locator('#pack-dialog-root [data-pack-item]').first.click()
                page.wait_for_selector('#pack-dialog-root .fd-chip-done')
                page.locator('#pack-dialog-root [data-pack-close]').click()
            page.locator('.house-life-drawer header button').click()
            check(page.evaluate('chfHouseMode()') == 'exterior', 'drawer preserves camera position')
        page.evaluate("chfHouseEnterRoom('kitchen')")
        page.wait_for_function('chfNavProbe({settled:true})')
        point = page.evaluate("chfNavProbe({action:'packing'})")
        check(point, 'visible packing bag has a canvas target')
        page.mouse.click(point['cx'], point['cy'])
        page.wait_for_selector('.house-life-shade', state='visible')
        check(page.locator('#house-life-title').inner_text() == 'Packing', 'bag opens packing')
        page.locator('.house-life-drawer header button').click()

        page.locator('[data-house-action=study]').click()
        page.wait_for_selector('#cc-input-field', state='visible')
        page.fill('#cc-input-field', '1234')
        page.click('#cc-input-ok-btn')
        page.wait_for_url(lambda url: urlparse(url).path.endswith('/study'))
        page.wait_for_selector('#house-return')
        check('panel' not in parse_qs(urlparse(page.url).query), 'PIN unlock releases panel latch for admin controls')
        visit = page.evaluate('chfHouseParent().token')
        check(storage.get_member_by_token(visit)['id'] == 'house-parent', 'temporary visit carries parent identity')
        page.goto(served.url('errands'))
        page.locator('#house-return').click()
        page.wait_for_url(lambda url: urlparse(url).path.endswith('/house') and 'panel=true' in url)
        check(parse_qs(urlparse(page.url).query).get('quality') == ['low'], 'return preserves house preferences')
        page.wait_for_function("sessionStorage.getItem('chauffeur_house_parent') === null")
        page.wait_for_timeout(300)
        check(storage.get_member_by_token(visit) is None, 'return revokes parent visit')
        check(storage.get_member_by_token(personal) is not None, 'personal sign-in survives')
        page.go_back()
        page.wait_for_url(lambda url: urlparse(url).path.endswith('/house'))
        check(not page.evaluate('chfHouseParent()'), 'browser back cannot revive parent visit')
        check(not served.errors(), 'no browser errors: ' + str(served.errors()))


if __name__ == '__main__':
    scenario_house_life()
    print('House life browser passed')
