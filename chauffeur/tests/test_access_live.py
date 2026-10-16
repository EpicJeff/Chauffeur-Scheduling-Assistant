"""Browser proof for the project access rule (spec §6 live line, §4.2 widget surfaces).

A private piece, opened through both deep-link forms on the admin record sheet and
through the phone's piece sheet, discloses nothing to Dad and opens for Mom; the
admin widget and a wall panel each ask the server for their own conversation.

Run from chauffeur/: python tests/test_access_live.py
"""
from project_sheets_fixture import IDS, admin, check, pwa, serve, shot, storage

HIDDEN = 'That isn’t here, or isn’t yours to see.'


def _private_pieces():
    from services import projects, threads
    tid = threads.create(title='Private tiler quotation', owner_member_id='mom', created_by='mom',
                         project_id='prj-gift', next_action='Ring the tiler about the secret')
    pid = storage.add_program({'title': 'Private piano curriculum', 'member_id': 'mom', 'state': 'proposed'})
    projects.adopt('program', pid, None, project_id='prj-gift')
    return [('thread', tid, 'Private tiler quotation'), ('program', pid, 'Private piano curriculum')]


def _unexpected(errors):
    # A hidden piece is a 404 shaped like a missing record (spec §4); that
    # exact network line is expected, everything else is a page error.
    return [e for e in errors if not e.startswith('Failed to load resource: the server responded with a status of 404')]


def scenario_private_pieces_hidden_from_dad_on_both_hosts_and_addresses():
    served = serve()
    if served is None:
        return
    pieces = _private_pieces()
    with served.browser() as page:
        admin(page, served, 'dad')
        for kind, rid, title in pieces:
            for prefix in ('projects?', 'projects?id=' + IDS['bath'] + '&'):
                page.goto(served.url(prefix + 'piece=' + kind + ':' + rid), wait_until='load')
                page.get_by_text(HIDDEN, exact=True).first.wait_for(state='visible', timeout=15000)
                check(title not in page.locator('body').inner_text(), f'admin {prefix} hides {kind} from Dad')
        shot(page, 'access-admin-dad-hidden')
        pwa(page, served, 'dad')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(served.url('app'), wait_until='load')
        page.locator('#tab-projects').click(timeout=20000)
        page.wait_for_selector('[data-project-id="prj-bath"]', timeout=15000)
        for kind, rid, title in pieces:
            page.evaluate("d => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail:d}))",
                          {'kind': kind, 'id': rid})
            page.locator('[data-piece-sheet]').get_by_text(HIDDEN, exact=True).wait_for(state='visible', timeout=10000)
            check(title not in page.locator('body').inner_text(), f'phone hides {kind} from Dad')
            page.locator('[data-pwa-dismiss]').first.click()
        shot(page, 'access-phone-dad-hidden')
        check(_unexpected(served.errors()) == [], f'no unexpected page errors: {_unexpected(served.errors())}')


def scenario_private_pieces_open_for_mom():
    served = serve()
    if served is None:
        return
    pieces = _private_pieces()
    with served.browser() as page:
        admin(page, served, 'mom')
        for kind, rid, title in pieces:
            page.goto(served.url('projects?piece=' + kind + ':' + rid), wait_until='load')
            page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=15000)
            page.get_by_text(title).first.wait_for(state='visible', timeout=15000)
        shot(page, 'access-admin-mom-open')
        check(_unexpected(served.errors()) == [], f'no unexpected page errors: {_unexpected(served.errors())}')


def scenario_widget_asks_for_its_own_surface():
    """§4.2: the admin widget asks for the person's conversation; a panel page asks for the panel's."""
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        asked = []
        page.on('request', lambda r: asked.append(r.url) if 'api/chat/conversation?' in r.url else None)
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_timeout(1500)
        check(any('surface=admin' in u for u in asked), f'admin page asks for surface=admin: {asked}')
        asked.clear()
        page.goto(served.url('projects?panel=true&kiosk=true'), wait_until='load')
        page.wait_for_timeout(1500)
        check(not any('surface=admin' in u for u in asked), f'a panel page never asks for the admin surface: {asked}')
        check(not any('chauffeurActiveConvId' in k for k in page.evaluate('Object.keys(localStorage)')),
              'no invented conversation id in localStorage')


SCENARIOS = [scenario_private_pieces_hidden_from_dad_on_both_hosts_and_addresses,
             scenario_private_pieces_open_for_mom, scenario_widget_asks_for_its_own_surface]
if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
