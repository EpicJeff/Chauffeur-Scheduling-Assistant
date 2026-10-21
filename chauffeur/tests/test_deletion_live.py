"""Projects delete, the UI, live in a browser (spec rev 3 section 7; plan Task 7).

This file must NOT import tests/harness.py: the live tests need auth enforcement on
(memory: auth-flip-aftermath). It serves the real app on its own throwaway data
directory, signs people in the way the slice 2 live tests do, and drives the
shared Delete (templates/components/record_delete.html) on every surface.

Scenarios (each record set is seeded fresh, since a delete destroys it):
  * project Delete names its pieces and deletes: Delete in the project's ⋯, after Drop, for the owner
    or a parent who sees the project (one-list spec 2026-10-20 decision 4); one promptConfirm listing every thread, mission and program by title, ending
    "Linked trips, lists and events stay."; the project vanishes on return; the linked list stays;
  * a piece's Delete (thread, mission, program: the same preview and confirm for that record) in its
    record sheet, and Remove (every other linked kind: projects.remove_piece, unlink only) in the link
    sheet (one-list spec §3);
  * folding: a mission launched from a thread in the same project has no row of its own; the thread's
    sheet lists it with its open and Delete (the fold is the server's, projects._fold_target);
  * standalone fallback for a keeper-only viewer and for a mission whose thread piece is missing: the
    mission keeps its own row there;
  * the phone thread sheet fetches the thread's mission history and lists every mission (no five cap),
    each with open and Delete;
  * the admin thread sheet lists ALL of a thread's missions (the five cap at main.py's
    /api/threads/{thread_id}/missions removed), each with open and Delete;
  * a child owner gets "Ask a parent to delete this." when the project holds something she cannot see;
  * after a `changed` answer the UI shows showGlobalAlert and previews again; no browser dialogs.

Screenshots: DELETION_SHOTS=<dir> saves light and dark phone-width shots.
Run from chauffeur/:  python tests/test_deletion_live.py
"""
import atexit
import os
import shutil
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = tempfile.mkdtemp(prefix='chauffeur_deletion_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage  # noqa: E402

TOKENS = {}
SHOTS = os.environ.get('DELETION_SHOTS')
STAY = 'Linked trips, lists and events stay.'
ASK_A_PARENT = 'Ask a parent to delete this.'
CHANGED = 'This project changed. Look again.'
PHONE = {'width': 390, 'height': 844}
_PROGRAM = {'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': []}, 'phases': [],
            'source': {'origin': 'none', 'reason': 'test'},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


BAD = []   # every failed response the page saw: (status, url)


def _watch(page):
    page.on('response', lambda r: BAD.append((r.status, r.url)) if r.status >= 400 else None)


def clean(served, allow=()):
    """No page errors and no failed request beyond the ones a scenario expects.
    The browser logs every failed request as a console error; those are judged
    here by status and path instead. An adult's admin page has always been
    refused /api/settings (pre-existing, not this slice)."""
    allow = tuple(allow) + ((403, 'api/settings'),)
    errors = [e for e in served.errors() if not e.startswith('Failed to load resource')]
    unexpected = [(st, url) for st, url in BAD if not any(st == a and frag in url for a, frag in allow)]
    BAD.clear()
    check(not errors and not unexpected, f"no page errors or unexpected failed requests: {errors} {unexpected}")


# --- seeding -----------------------------------------------------------------

def _members():
    if TOKENS:
        return
    for m in ({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#287a72'},
              {'id': 'dad', 'name': 'Dad', 'role': 'parent', 'color_code': '#7a2850'},
              {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult', 'color_code': '#285a7a'},
              {'id': 'kid', 'name': 'Kate', 'role': 'child', 'stage_override': 'navigator', 'color_code': '#5a7a28'}):
        storage.add_member(m)
    for who in ('mom', 'dad', 'aunt', 'kid'):
        TOKENS[who] = storage.create_member_token(who)
    storage.set_app_state('projects_adopted_rev', 1)   # the startup migration must not re-wrap anything


def _id(prefix):
    return f'{prefix}-{uuid.uuid4().hex[:8]}'


def _project(title, owner='mom', audience='household', **extra):
    pid = _id('prj')
    storage.add_project({'id': pid, 'title': title, 'goal': title.lower(), 'done_when': 'it is done',
                         'owner_member_id': owner, 'created_by': owner, 'audience': audience,
                         'pieces': [], 'steps': [], **extra})
    return pid


def _thread(title, pid, owner='mom', **extra):
    from services import threads
    tid = threads.create(title=title, owner_member_id=owner, goal=title.lower(), kind='vendor',
                         counterparty_name='Ace', created_by=owner, project_id=pid)
    if extra:
        storage.update_thread(tid, extra)
    return tid


def _mission(goal, pid, thread=None, by='mom', status='done'):
    from services import projects
    row = {'goal': goal, 'created_by': by, 'tier': 'mission', 'status': status}
    if thread:
        row.update(origin_kind='thread', origin_ref=thread)
    mid = storage.add_mission(row)
    projects.adopt('mission', mid, None, project_id=pid)
    return mid


def _program(title, pid, member='mom'):
    from services import projects
    gid = _id('pr')
    from library_run_fixture import add_run   # a run reads its curriculum from the library
    add_run({'id': gid, 'member_id': member, 'title': title, 'state': 'active', **_PROGRAM})
    projects.adopt('program', gid, None, project_id=pid)
    return gid


def _list(name, pid):
    lid = _id('list')
    storage.add_shopping_list({'id': lid, 'name': name, 'title': name})
    project = storage.get_project(pid)
    storage.update_project(pid, {'pieces': (project.get('pieces') or []) + [{'kind': 'list', 'id': lid}]})
    return lid


def _gone(kind, rid):
    row = getattr(storage, 'get_' + kind)(rid)
    return row is None or bool(row.get('deleting'))


# --- serving and signing in --------------------------------------------------

def serve():
    from live_app import live_app
    served = live_app(_members)
    if served is not None:
        storage.update_settings({'auth_enforce': True, 'missions_enabled': True, 'programs_enabled': True})
    return served


def admin(page, served, who, width=None):
    _watch(page)
    if width:
        page.set_viewport_size(width)
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_admin_token': TOKENS[who], 'chauffeur_admin_token_for': who})


def pwa(page, served, who, theme='dark'):
    _watch(page)
    page.set_viewport_size(PHONE)
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_member_id': who, 'chauffeur_member_token': TOKENS[who], 'chauffeur_member_token_for': who,
                   'chauffeur_theme': theme})


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'), full_page=False)


def _admin_project(page, served, who, pid, pieces=True):
    admin(page, served, who)
    page.goto(served.url('projects?id=' + pid), wait_until='load')
    page.wait_for_selector('[data-project-detail]', timeout=15000)
    if pieces:
        page.wait_for_selector('[data-project-detail] [data-row]', state='attached', timeout=10000)
    else:
        # The detail draws only after the members load, so who may delete is
        # already decided; a beat lets the pieces request settle.
        page.wait_for_timeout(500)


def _open_projects(page):
    """Projects lives in More on the phone (one-list spec §5); as project_sheets_fixture.open_projects."""
    page.locator('#tab-more').click()
    page.locator('#pwa-feature-list').get_by_text('Projects', exact=True).first.click()
    page.wait_for_selector('#projects-container [data-project-card], #projects-container [data-project-detail]', timeout=15000)


def _phone_project(page, served, who, pid, theme='dark'):
    pwa(page, served, who, theme)
    page.goto(served.url('app'), wait_until='load')
    page.wait_for_selector('#tab-more', state='visible', timeout=20000)
    _open_projects(page)
    page.wait_for_selector(f'[data-project-id="{pid}"]', timeout=15000)
    page.locator(f'[data-project-id="{pid}"]').first.click()
    page.wait_for_selector('[data-project-detail]', timeout=10000)


def _menu(page, pick=None):
    """The project's ⋯ (promptChoice; one-list spec decision 4): its labels, then the option
    picked, or Cancel. An empty ⋯ is not drawn at all."""
    btn = page.locator('[data-project-detail] [data-project-menu]')
    if pick:
        btn.click(timeout=15000)
    elif not btn.is_visible():
        return []
    else:
        btn.click()
    if page.locator('#cc-choice-modal').count():   # the admin hosts' shared modal
        page.locator('#cc-choice-modal').wait_for(state='visible', timeout=5000)
        options, cancel = page.locator('#cc-choice-modal [data-prompt-choice]'), page.locator('#cc-choice-cancel-btn')
    else:                                          # the phone's own prompt family
        overlay = page.locator('.pwa-prompt-overlay:has([data-pick])').last
        overlay.wait_for(state='visible', timeout=5000)
        options, cancel = overlay.locator('[data-pick]'), overlay.locator('[data-no]')
    labels = [t.strip() for t in options.all_inner_texts()]
    if pick:
        options.filter(has_text=pick).first.click()
    else:
        cancel.click()
    return labels


def _open_sheet(page, key, words):
    """A row's title opens its record sheet (admin hosts)."""
    page.locator(f'[data-piece-open="{key}"]').click()
    page.wait_for_function("(w) => (document.querySelector('[data-record-sheet][data-open=\"true\"]') || {}).innerText?.includes(w)",
                           arg=words, timeout=15000)
    return page.locator('[data-record-sheet]')


def _open_logbook(page):
    """A finished mission's row sits in the folded Logbook (one-list spec §1): unfold it."""
    toggle = page.locator('[data-row-group-section="logbook"] > button[aria-expanded="false"]')
    if toggle.count():
        toggle.click()


def _close_sheet(page):
    page.locator('[data-record-sheet-close]').click()
    page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)


def _admin_confirm(page):
    page.locator('#cc-confirm-modal').wait_for(state='visible', timeout=10000)
    return page.locator('#cc-confirm-title').inner_text(), page.locator('#cc-confirm-message').inner_text()


def _phone_confirm(page):
    overlay = page.locator('.pwa-prompt-overlay:has([data-yes]):has([data-no])').last
    overlay.wait_for(state='visible', timeout=10000)
    return overlay


def _wait(cond, msg, page, tries=60):
    for _ in range(tries):
        if cond():
            return
        page.wait_for_timeout(250)
    check(False, msg)


def _no_dialogs(page, seen):
    page.on('dialog', lambda d: (seen.append(d.message), d.dismiss()))


# --- scenarios ---------------------------------------------------------------

def scenario_project_delete_names_its_pieces_and_deletes():
    served = serve()
    if served is None:
        return
    pid = _project('Garage clear-out')
    tid = _thread('Skip hire', pid)
    mid = _mission('Compare skip prices', pid, thread=tid)
    gid = _program('Sorting practice', pid)
    lid = _list('Hardware run', pid)
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        _admin_project(page, served, 'mom', pid)
        # Delete is the last item in ⋯, after Drop (one-list spec decision 4). A promptChoice
        # option has one style, so the old red button colour has no equivalent here.
        row = _menu(page)
        check('Delete' in row, f"the owner sees the project's Delete: {row}")
        check(row[-2:] == ['Drop', 'Delete'], f"Delete sits beside Drop: {row}")
        _menu(page, 'Delete')
        title, message = _admin_confirm(page)
        check(title == 'Delete “Garage clear-out”?', f"the confirmation names the project: {title}")
        for word in ('Conversations', 'Skip hire', 'Argyle’s work', 'Compare skip prices', 'Programs', 'Sorting practice'):
            check(word in message, f"the confirmation names {word}: {message}")
        check(message.strip().endswith(STAY), f"it ends with the linked kinds staying: {message}")
        check('Hardware run' not in message, f"a linked list is not named as going: {message}")
        check(message.index('Skip hire') < message.index('Compare skip prices') < message.index('Sorting practice'),
              f"grouped by kind: {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector(f'[data-project-id="{pid}"]', state='detached', timeout=10000)
        page.wait_for_selector('[data-project-detail]', state='detached', timeout=10000)
        check('id=' + pid not in page.url, f"the address no longer names it: {page.url}")
        check(all(_gone(k, r) for k, r in (('project', pid), ('thread', tid), ('mission', mid), ('program', gid))),
              "the project and its pieces are gone at once")
        check(storage.get_shopping_list(lid) is not None, "the linked list stays")
        check(dialogs == [], f"no browser dialogs: {dialogs}")
        clean(served)


def scenario_who_sees_the_project_delete():
    served = serve()
    if served is None:
        return
    pid = _project('Paint the fence', owner='aunt')
    with served.browser() as page:
        _admin_project(page, served, 'dad', pid, pieces=False)
        check('Delete' in _menu(page), "a parent who sees the project has Delete")
        _admin_project(page, served, 'aunt', pid, pieces=False)
        check('Delete' in _menu(page), "the owner has Delete")
    other = _project('Mom’s errands')
    with served.browser() as page:
        _admin_project(page, served, 'aunt', other, pieces=False)
        check('Delete' not in _menu(page), "another adult who is not the owner has none")
        clean(served)


def scenario_a_piece_delete_and_remove():
    served = serve()
    if served is None:
        return
    pid = _project('Bathroom refit')
    tid = _thread('Find a tiler', pid)
    mid = _mission('Price the tiles', pid)
    gid = _program('Grout practice', pid)
    lid = _list('Tile shop list', pid)
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        _admin_project(page, served, 'mom', pid)
        _open_logbook(page)   # the finished mission's row
        # One list (spec 2026-10-20 §3): a thread's, mission's or program's Delete lives in its
        # record sheet; a linked list's Remove lives in its link sheet (Open, Remove).
        sheet = _open_sheet(page, f'thread:{tid}', 'Find a tiler')
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=10000)
        check(sheet.get_by_role('button', name='Remove', exact=True).count() == 0, "no Remove on the thread")
        sheet.get_by_role('button', name='Delete', exact=True).last.click()
        title, message = _admin_confirm(page)
        check(title == 'Delete “Find a tiler”?' and 'Find a tiler' in message and message.strip().endswith(STAY),
              f"the thread's own preview: {title} / {message}")
        check('Price the tiles' not in message and 'Grout practice' not in message, f"only that record: {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=10000)
        page.wait_for_selector(f'[data-row="conversation:{tid}"]', state='detached', timeout=10000)
        check(_gone('thread', tid) and not _gone('project', pid), "the thread goes; the project stays")

        sheet = _open_sheet(page, f'mission:{mid}', 'Price the tiles')
        delete = sheet.get_by_role('button', name='Delete', exact=True)
        delete.first.wait_for(state='visible', timeout=10000)
        check(sheet.get_by_role('button', name='Remove', exact=True).count() == 0, "no Remove on the mission")
        delete.first.click()
        _admin_confirm(page)
        page.locator('#cc-confirm-cancel-btn').click()
        check(not _gone('mission', mid), "Keep it deletes nothing")
        delete.first.click()
        _admin_confirm(page)
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector(f'[data-row="argyle:{mid}"]', state='detached', timeout=10000)
        check(_gone('mission', mid) and not _gone('project', pid), "the last Argyle piece goes; the project stays")
        if page.locator('[data-record-sheet][data-open="true"]').count():
            _close_sheet(page)

        row = page.locator(f'[data-row="link:{lid}"]')
        check(row.count() == 1 and row.locator('a').count() == 0, "the linked list's row is buttons only")
        row.locator('[data-row-title]').click()
        link_sheet = page.locator('[data-link-sheet]')
        link = link_sheet.locator(f'[data-piece-link="list:{lid}"]')
        check(link.count() == 1 and link.evaluate('el => el.tagName') == 'BUTTON'
              and link_sheet.locator('a').count() == 0, "the linked piece opens from a button, not an anchor")
        check(link_sheet.locator('[data-link-remove]').count() == 1, "Remove on the linked list")
        check(link_sheet.get_by_role('button', name='Delete', exact=True).count() == 0, "no Delete on the linked list")
        with page.expect_request(lambda r: r.is_navigation_request(), timeout=10000) as went:
            link.click()
        check(went.value.url == served.url('shopping'), f"it opens the same address its link did: {went.value.url}")
        page.goto(served.url('projects?id=' + pid), wait_until='load')
        page.wait_for_selector(f'[data-row="link:{lid}"]', timeout=15000)
        page.locator(f'[data-row="link:{lid}"] [data-row-title]').click()
        page.locator('[data-link-sheet] [data-link-remove]').click()
        title, _ = _admin_confirm(page)
        check(title == 'Remove “Tile shop list”?', f"Remove names what it unlinks: {title}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector(f'[data-row="link:{lid}"]', state='detached', timeout=10000)
        check(storage.get_shopping_list(lid) is not None, "Remove leaves the list itself")
        check(not any(p.get('id') == lid for p in storage.get_project(pid).get('pieces') or []), "only the link goes")
        check(page.locator('[data-project-detail]').count() == 1, "the project stays open")

        # The program last: its Delete lived on the old piece card (owner or parent).
        sheet = _open_sheet(page, f'program:{gid}', 'Grout practice')
        check(sheet.get_by_role('button', name='Remove', exact=True).count() == 0, "no Remove on the program")
        sheet.get_by_role('button', name='Delete', exact=True).first.click(timeout=10000)
        title, message = _admin_confirm(page)
        check('Grout practice' in message and 'Programs' in message, f"the program's preview: {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector(f'[data-row="program:{gid}"]', state='detached', timeout=10000)
        check(_gone('program', gid), "the program goes")
        check(dialogs == [], f"no browser dialogs: {dialogs}")
        clean(served)


def scenario_a_run_delete_follows_the_project_owner():
    """A run's Delete sits in its sheet on both hosts, for the project's owner or a parent
    (deletion._authority), never for the run's own member alone; it deletes the run only."""
    served = serve()
    if served is None:
        return
    owned = _project('Aunt Jo’s garden', owner='aunt')
    run = _program('Pruning practice', owned, member='mom')
    other = _project('Mom’s fitness')
    theirs = _program('Stretching practice', other, member='aunt')
    for who in ('aunt', 'dad'):   # a fresh browser per person: one signed-in admin at a time
        with served.browser() as page:
            _admin_project(page, served, who, owned)
            sheet = _open_sheet(page, f'program:{run}', 'Pruning practice')
            sheet.get_by_role('button', name='Delete', exact=True).first.wait_for(state='visible', timeout=10000)   # {who} has it
            clean(served)
    with served.browser() as page:
        _admin_project(page, served, 'aunt', other)
        sheet = _open_sheet(page, f'program:{theirs}', 'Stretching practice')
        sheet.get_by_role('button', name='Log a session', exact=True).first.wait_for(state='visible', timeout=10000)
        check(sheet.get_by_role('button', name='Delete', exact=True).count() == 0,
              "the run's own member who neither owns the project nor is a parent has no Delete")
        clean(served)
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        _phone_project(page, served, 'aunt', owned)
        page.locator(f'[data-piece-open="program:{run}"]').click()
        delete = page.locator(f'[data-piece-sheet-delete="program:{run}"]')
        delete.wait_for(state='visible', timeout=10000)
        delete.click()
        overlay = _phone_confirm(page)
        check('Pruning practice' in overlay.inner_text() and STAY in overlay.inner_text(), f"the run's preview: {overlay.inner_text()}")
        overlay.locator('[data-yes]').click()
        page.wait_for_selector(f'[data-row="program:{run}"]', state='detached', timeout=10000)
        check(_gone('program', run) and not _gone('project', owned), "the run goes; the project stays")
        check(dialogs == [], f"no browser dialogs: {dialogs}")
        clean(served)


def scenario_a_changed_project_previews_again():
    served = serve()
    if served is None:
        return
    pid = _project('Loft insulation')
    _thread('Quote from Insul8', pid)
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        _admin_project(page, served, 'mom', pid)
        _menu(page, 'Delete')
        _, message = _admin_confirm(page)
        check('Quote from Insul8' in message and 'Second quote' not in message, f"the first look: {message}")
        late = _thread('Second quote', pid)    # someone adds to the project while the dialog is open
        page.locator('#cc-confirm-execute-btn').click()
        page.locator('#cc-alert-modal').wait_for(state='visible', timeout=10000)
        check(page.locator('#cc-alert-message').inner_text() == CHANGED, "changed is shown through showGlobalAlert")
        _, message = _admin_confirm(page)
        check('Second quote' in message, f"the preview ran again and names the new thread: {message}")
        check(not _gone('project', pid) and not _gone('thread', late), "nothing was deleted on the stale look")
        page.locator('#cc-alert-modal button').click()
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector('[data-project-detail]', state='detached', timeout=10000)
        check(_gone('project', pid) and _gone('thread', late), "the second confirmation deletes what it named")
        check(dialogs == [], f"no browser dialogs: {dialogs}")
        check(any(st == 409 and url.endswith('api/projects/' + pid) for st, url in BAD), f"the stale look was a 409: {BAD}")
        clean(served, allow=[(409, 'api/projects/' + pid)])


def _fold_fixture():
    secret = _project('Mom’s surprise', audience='private', shared_with=['mom'])
    pid = _project('Garden shed')
    mine = _thread('Shed base', pid)
    mine_m = _mission('Find a concrete layer', pid, thread=mine)
    # Aunt keeps her own thread and mission, but they are about a project she
    # cannot see: she reads both only as their keeper.
    aunts = _thread('Shed roof', pid, owner='aunt', subject={'kind': 'project', 'id': secret})
    aunts_m = _mission('Price roofing felt', pid, thread=aunts, by='aunt')
    return pid, mine, mine_m, aunts, aunts_m


def scenario_folding_when_the_thread_card_renders():
    served = serve()
    if served is None:
        return
    pid, mine, mine_m, aunts, aunts_m = _fold_fixture()
    with served.browser() as page:
        _admin_project(page, served, 'mom', pid)
        # One list (spec 2026-10-20 §1): the mission folds into its thread's row (no row of its
        # own); the thread's sheet lists it with its open and Delete.
        page.wait_for_selector(f'[data-row="conversation:{mine}"]', timeout=10000)
        check(page.locator(f'[data-row="argyle:{mine_m}"]').count() == 0, "the mission has no row of its own")
        page.evaluate("() => { window.__sheets = []; window.addEventListener('chf-record-sheet-open', e => window.__sheets.push(e.detail)); }")
        sheet = _open_sheet(page, f'thread:{mine}', 'Shed base')
        folded = sheet.locator(f'[data-thread-mission="{mine_m}"]')
        folded.wait_for(state='visible', timeout=10000)
        check(folded.locator(f'[data-thread-mission-open="{mine_m}"]').count() == 1
              and folded.locator(f'[data-thread-mission-delete="{mine_m}"]').count() == 1, "with its open and Delete")
        check('Find a concrete layer' in folded.inner_text(), "its own line, inside its thread's sheet")
        folded.locator(f'[data-thread-mission-open="{mine_m}"]').click()
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').dataset.kind === 'mission'", timeout=10000)
        sheets = page.evaluate('() => window.__sheets')
        check(sheets and sheets[-1]['kind'] == 'mission' and sheets[-1]['id'] == mine_m, f"open asks for the mission: {sheets}")
        page.keyboard.press('Escape')
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)
        sheet = _open_sheet(page, f'thread:{mine}', 'Shed base')
        sheet.locator(f'[data-thread-mission-delete="{mine_m}"]').click()
        _, message = _admin_confirm(page)
        check('Find a concrete layer' in message and 'Shed base' not in message, f"the folded Delete is the mission's own: {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector(f'[data-record-sheet] [data-thread-mission="{mine_m}"]', state='detached', timeout=10000)
        check(_gone('mission', mine_m) and not _gone('thread', mine), "only the mission goes")
        clean(served)


def scenario_standalone_for_a_keeper_only_viewer():
    served = serve()
    if served is None:
        return
    pid, mine, mine_m, aunts, aunts_m = _fold_fixture()
    with served.browser() as page:
        _admin_project(page, served, 'aunt', pid)
        _open_logbook(page)   # her finished mission's row
        page.wait_for_selector(f'[data-row="argyle:{aunts_m}"]', timeout=10000)
        mission = page.locator(f'[data-row="argyle:{aunts_m}"]')
        check(mission.count() == 1, "a keeper-only viewer keeps the mission's own row")
        check(mission.locator(f'[data-piece-open="mission:{aunts_m}"]').count() == 1, "with its own open")
        sheet = _open_sheet(page, f'mission:{aunts_m}', 'Price roofing felt')
        sheet.get_by_role('button', name='Delete', exact=True).first.wait_for(state='visible', timeout=10000)   # and its Delete
        _close_sheet(page)
        check(page.locator(f'[data-row="argyle:{mine_m}"]').count() == 0,
              "a mission she reads in full still folds under a thread she reads in full")
        clean(served)
    with served.browser() as page:
        _admin_project(page, served, 'mom', pid)
        page.wait_for_selector(f'[data-row="conversation:{aunts}"]', timeout=10000)
        check(page.locator(f'[data-row="argyle:{aunts_m}"]').count() == 0,
              "the same mission folds for a parent who reads both in full")


def scenario_standalone_for_a_missing_thread_piece():
    served = serve()
    if served is None:
        return
    pid = _project('Kitchen tap')
    tid = _thread('Plumber', pid)
    mid = _mission('Find a plumber', pid, thread=tid)
    project = storage.get_project(pid)
    storage.update_project(pid, {'pieces': [p for p in project['pieces'] if p.get('kind') != 'thread']})
    with served.browser() as page:
        _admin_project(page, served, 'mom', pid)
        _open_logbook(page)   # the finished mission's row
        page.wait_for_selector(f'[data-row="argyle:{mid}"]', timeout=10000)
        check(page.locator(f'[data-row="conversation:{tid}"]').count() == 0, "the thread has no row here")
        mission = page.locator(f'[data-row="argyle:{mid}"]')
        check(mission.locator(f'[data-piece-open="mission:{mid}"]').count() == 1, "the mission keeps its own row with open")
        sheet = _open_sheet(page, f'mission:{mid}', 'Find a plumber')
        sheet.get_by_role('button', name='Delete', exact=True).first.wait_for(state='visible', timeout=10000)   # and Delete
        clean(served)


def scenario_phone_folds_and_falls_back_without_history():
    served = serve()
    if served is None:
        return
    pid = _project('Bike shed')
    tid = _thread('Shed kit', pid)
    mid = _mission('Compare shed kits', pid, thread=tid)
    with served.browser() as page:
        _phone_project(page, served, 'mom', pid)
        page.wait_for_selector(f'[data-row="conversation:{tid}"]', timeout=10000)
        check(page.locator(f'[data-row="argyle:{mid}"]').count() == 0, "the phone folds it too: its sheet has history")
        page.locator(f'[data-piece-open="thread:{tid}"]').click()
        page.wait_for_selector(f'[data-piece-sheet] [data-thread-mission-open="{mid}"]', timeout=10000)
        check(page.locator(f'[data-piece-sheet] [data-thread-mission-delete="{mid}"]').count() == 1,
              "the thread's sheet lists it with its open and Delete")
        clean(served)
    # The no-history fallback (a phone surface whose thread sheet lists no missions) is gone:
    # the fold is the server's since the one list (projects._fold_target, THREAD_SHEET_HISTORY),
    # and every host's thread sheet lists the thread's missions.


def _many_missions():
    pid = _project('House move')
    tid = _thread('Removal firm', pid)
    mids = [_mission(f'Removal quote {n}', pid, thread=tid) for n in range(1, 8)]
    return pid, tid, mids


def scenario_the_phone_thread_sheet_lists_every_mission():
    served = serve()
    if served is None:
        return
    pid, tid, mids = _many_missions()
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        _phone_project(page, served, 'mom', pid)
        page.locator(f'[data-piece-open="thread:{tid}"]').click()
        page.wait_for_selector('[data-piece-sheet] [data-thread-missions]', timeout=10000)
        rows = page.locator('[data-piece-sheet] [data-thread-mission]')
        check(rows.count() == 7, f"all seven missions, no five cap: {rows.count()}")
        for mid in mids:
            check(page.locator(f'[data-thread-mission-open="{mid}"]').count() == 1
                  and page.locator(f'[data-thread-mission-delete="{mid}"]').count() == 1, f"open and Delete on {mid}")
        check(page.locator(f'[data-piece-sheet-delete="thread:{tid}"]').count() == 1, "the thread's own Delete")
        page.locator(f'[data-thread-mission-delete="{mids[0]}"]').click()
        overlay = _phone_confirm(page)
        text = overlay.inner_text()
        check('Removal quote 1' in text and STAY in text and 'Removal firm' not in text, f"the mission's preview: {text}")
        overlay.locator('[data-yes]').click()
        page.wait_for_function("(id) => !document.querySelector(`[data-thread-mission='${id}']`)"
                               " && document.querySelectorAll('[data-piece-sheet] [data-thread-mission]').length === 6",
                               arg=mids[0], timeout=10000)
        check(_gone('mission', mids[0]), "the mission is deleted from the phone sheet")
        page.locator(f'[data-thread-mission-open="{mids[1]}"]').click()
        page.wait_for_function("() => (document.querySelector('[data-piece-sheet]') || {}).innerText?.includes('Removal quote 2')",
                               timeout=10000)
        check(page.locator(f'[data-piece-sheet-delete="mission:{mids[1]}"]').count() == 1, "open shows the mission, with its Delete")
        check(dialogs == [], f"no browser dialogs: {dialogs}")
        clean(served)


def scenario_the_admin_thread_sheet_lists_every_mission():
    served = serve()
    if served is None:
        return
    pid, tid, mids = _many_missions()
    with served.browser() as page:
        _admin_project(page, served, 'mom', pid)
        page.locator(f'[data-piece-open="thread:{tid}"]').click()
        page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=10000)
        page.wait_for_function("() => document.querySelectorAll('[data-record-sheet] [data-thread-mission]').length === 7",
                               timeout=10000)
        for mid in mids:
            check(page.locator(f'[data-record-sheet] [data-thread-mission-open="{mid}"]').count() == 1
                  and page.locator(f'[data-record-sheet] [data-thread-mission-delete="{mid}"]').count() == 1,
                  f"open and Delete on {mid}")
        page.locator(f'[data-record-sheet] [data-thread-mission-delete="{mids[6]}"]').click()
        _, message = _admin_confirm(page)
        check('Removal quote 7' in message and 'Removal firm' not in message, f"the mission's own preview: {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_function("() => document.querySelectorAll('[data-record-sheet] [data-thread-mission]').length === 6",
                               timeout=10000)
        check(_gone('mission', mids[6]), "deleted from the admin thread sheet")
        page.locator(f'[data-record-sheet] [data-thread-mission-open="{mids[0]}"]').click()
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').dataset.kind === 'mission'", timeout=10000)
        clean(served)


def scenario_the_thread_sheet_delete_takes_its_missions():
    served = serve()
    if served is None:
        return
    pid = _project('Boiler service')
    tid = _thread('Gas engineer', pid)
    mid = _mission('Book the engineer', pid, thread=tid)
    with served.browser() as page:
        _admin_project(page, served, 'mom', pid)
        page.locator(f'[data-piece-open="thread:{tid}"]').click()
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=10000)
        page.locator('[data-record-sheet]').get_by_role('button', name='Delete', exact=True).last.click()
        _, message = _admin_confirm(page)
        check('Gas engineer' in message and 'Book the engineer' in message, f"the thread takes its mission: {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=10000)
        page.wait_for_selector(f'[data-row="conversation:{tid}"]', state='detached', timeout=10000)
        check(_gone('thread', tid) and _gone('mission', mid), "both gone; the sheet closed")
        clean(served)


def scenario_the_mission_sheet_delete_closes_the_sheet():
    served = serve()
    if served is None:
        return
    pid = _project('Car service')
    mid = _mission('Book an MOT', pid, status='waiting_user')
    with served.browser() as page:
        _admin_project(page, served, 'mom', pid)
        page.locator(f'[data-piece-open="mission:{mid}"]').click()
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Book an MOT')", timeout=15000)
        page.locator(f'#mission-answer-{mid}').wait_for(state='visible', timeout=15000)
        page.locator('[data-record-sheet]').get_by_role('button', name='Delete', exact=True).click()
        title, message = _admin_confirm(page)
        check(title == 'Delete “Book an MOT”?' and message.strip().endswith(STAY), f"the mission's own preview: {title} / {message}")
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=10000)
        page.wait_for_selector(f'[data-row="argyle:{mid}"]', state='detached', timeout=10000)
        check(_gone('mission', mid) and not _gone('project', pid), "the mission goes, the sheet closes, the project stays")
        clean(served)


def scenario_a_child_owner_is_asked_to_ask_a_parent():
    served = serve()
    if served is None:
        return
    pid = _project('Ride a bike', owner='kid', audience='parents')
    hidden = _mission('Find a bike shop', pid, by='mom', status='waiting_user')
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        _phone_project(page, served, 'kid', pid)
        check(page.locator(f'[data-row="argyle:{hidden}"]').count() == 0, "she cannot see the mission")
        _menu(page, 'Delete')
        toast = page.locator('#global-alert')
        toast.wait_for(state='attached', timeout=10000)
        page.wait_for_function("(t) => (document.getElementById('global-alert') || {}).textContent === t", arg=ASK_A_PARENT, timeout=10000)
        check(page.locator('.pwa-prompt-overlay').count() == 0, "no confirmation names anything")
        check(not _gone('project', pid) and not _gone('mission', hidden), "nothing is deleted")
        page.wait_for_timeout(400)   # the toast fades in
        shot(page, 'phone-child-ask-a-parent-dark')
        check(dialogs == [], f"no browser dialogs: {dialogs}")
        check(any(st == 403 and f'api/deletion/project/{pid}/preview' in url for st, url in BAD), f"the preview refused: {BAD}")
        clean(served, allow=[(403, f'api/deletion/project/{pid}/preview')])


def scenario_light_and_dark_at_phone_width():
    served = serve()
    if served is None:
        return
    for theme in ('dark', 'light'):
        pid = _project('Summer fete')
        tid = _thread('Bouncy castle hire', pid)
        _mission('Compare castle prices', pid, thread=tid)
        _program('Juggling practice', pid)
        _list('Fete shopping', pid)
        with served.browser() as page:
            _phone_project(page, served, 'mom', pid, theme)
            page.wait_for_selector(f'[data-row="conversation:{tid}"]', timeout=10000)
            check(page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), f"no sideways scroll ({theme})")
            page.locator(f'[data-row="conversation:{tid}"]').scroll_into_view_if_needed()
            shot(page, f'phone-project-pieces-{theme}')
            page.locator('[data-project-detail] [data-project-menu]').scroll_into_view_if_needed()
            shot(page, f'phone-project-actions-{theme}')
            _menu(page, 'Delete')
            overlay = _phone_confirm(page)
            text = overlay.inner_text()
            check('Bouncy castle hire' in text and 'Compare castle prices' in text and 'Juggling practice' in text
                  and STAY in text and 'Fete shopping' not in text, f"the phone confirmation ({theme}): {text}")
            shot(page, f'phone-project-confirm-{theme}')
            overlay.locator('[data-no]').click()
            page.locator(f'[data-piece-open="thread:{tid}"]').click()
            page.wait_for_selector('[data-piece-sheet] [data-thread-missions]', timeout=10000)
            shot(page, f'phone-thread-sheet-{theme}')
            clean(served)
    pid = _project('Window cleaning')
    tid = _thread('Window cleaner', pid)
    _mission('Find a window cleaner', pid, thread=tid)
    with served.browser() as page:
        admin(page, served, 'mom', width=PHONE)
        page.goto(served.url('projects?id=' + pid), wait_until='load')
        page.wait_for_selector(f'[data-row="conversation:{tid}"]', timeout=15000)
        page.locator(f'[data-row="conversation:{tid}"]').scroll_into_view_if_needed()
        shot(page, 'admin-phone-width-pieces-dark')
        _menu(page, 'Delete')
        _admin_confirm(page)
        shot(page, 'admin-phone-width-confirm-dark')
        page.locator('#cc-confirm-cancel-btn').click()
        clean(served)


SCENARIOS = [scenario_project_delete_names_its_pieces_and_deletes, scenario_who_sees_the_project_delete,
             scenario_a_piece_delete_and_remove, scenario_a_run_delete_follows_the_project_owner,
             scenario_a_changed_project_previews_again,
             scenario_folding_when_the_thread_card_renders, scenario_standalone_for_a_keeper_only_viewer,
             scenario_standalone_for_a_missing_thread_piece, scenario_phone_folds_and_falls_back_without_history,
             scenario_the_phone_thread_sheet_lists_every_mission, scenario_the_admin_thread_sheet_lists_every_mission,
             scenario_the_thread_sheet_delete_takes_its_missions, scenario_the_mission_sheet_delete_closes_the_sheet,
             scenario_a_child_owner_is_asked_to_ask_a_parent,
             scenario_light_and_dark_at_phone_width]

if __name__ == '__main__':
    import traceback
    failed = 0
    only = set(sys.argv[1:])
    for fn in SCENARIOS:
        if only and fn.__name__ not in only:
            continue
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
