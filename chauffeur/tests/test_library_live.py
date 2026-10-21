"""Program library, live (spec 2026-10-19-program-library-design.md rev 3, section 5 "Live"; plan Task 6).

A checklist only: Task 6 writes the Playwright scenarios below this docstring, against a live
add-on run, with screenshots inspected in light and dark at phone width. A live test that needs
auth enforcement must not import tests/harness.py. No browser dialogs anywhere (showGlobalAlert,
promptConfirm, promptInput); buttons, not anchors, on the phone.

  1. Library page (/library, admin nav, Work group): one card per program with title, made-for,
     source chip, lesson count and the visible runners with their project as buttons.
  2. New program (adults): the create form shows "Everyone in the household will see this program
     as: {title}" above the title, the personal starting point is labelled "stays private to
     {name}'s run", and the age band defaults from the member's birthdate, else "any".
  3. Edit a program: inline lesson edit (title, steps, body or url, sessions, rotation label), drag
     to reorder, Add lesson; a refused editor sees "Only the person who made this program, or a
     parent, can change it."
  4. Archive (creator or parent): the card leaves the picker and stays on the library page.
  5. Delete: disabled while in use, with "In use by {names}'s project" for a runner the viewer
     sees, "In use by another project" otherwise; enabled and working once unused.
  6. Remove the current lesson: "{name} is on this lesson; her run moves to the next one." for a
     visible runner; a hidden runner is counted, never named.
  7. The picker (project page, + Add -> Program, now the one-pass setup sheet): library programs
     (title, made-for, visible runners; archived hidden) with "Make a new one" at the bottom; a
     parent's pick starts the program active, a child's waits for approval.
  8. The run's sheet (record sheet: "in the library ›" as a button and the lit rung; phone: "from
     the library: {title}" and the current lesson by name under its phase), never a count; the
     project's own row is title, subtitle and when (one-list spec §1), never a count either.
  9. The unresolved run: its row reads "Needs a program" with "Pick a program"; its sheet says "Its
     library program is missing" with Delete.
 10. Next / Back ("Another session on this") on the run; "Reached it" on a non-final phase keeps
     the run going.
 11. Phone: More -> Library opens the library home (buttons only).
 12. Light and dark themes, phone width (16px gutter, no horizontal scroll), screenshots inspected.
 13. (Task 1 review) An exhausted phase reads "every lesson done — reached it?" on its lit rung and
     never advances by itself.
 14. (Task 1 review) Look again (re-curate) asks first, saying progress starts over and scripts
     are regenerated.
 15. (Task 6 review) "from the library" on the phone's run sheet closes the sheet: the library's
     own controls take the tap. The phone's run card has no anchor, a lesson link is a button.
 16. (Task 6 review) A library lesson edit reaches a paused run's phone card (the resolved
     lesson's steps, never the phase's), and confirm titles show people's words unescaped.

Run from chauffeur/:  python tests/test_library_live.py   (LIBRARY_SHOTS=<dir> for screenshots)
"""
import atexit
import copy
import os
import re
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = tempfile.mkdtemp(prefix='chauffeur_library_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage  # noqa: E402

TOKENS = {}
SHOTS = os.environ.get('LIBRARY_SHOTS')
COUNT = re.compile(r'\b\d+\s*(?:of|/)\s*\d+\b')
PIANO, DRUMS, CHESS = 'lib-piano', 'lib-drums', 'lib-chess'
FOUND, SONGS = 'ph-found', 'ph-songs'
SCALES, CHORDS, TWINKLE = 'ls-scales', 'ls-chords', 'ls-twinkle'
REFUSAL = 'Only the person who made this program, or a parent, can change it.'
_BASELINE = {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}
_SHAPE = {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': []}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _library_row(lid, title, phases, lessons, origin='generated'):
    return {'id': lid, 'title': title, 'created_by': 'mom', 'archived': False,
            'made_for': {'age_band': 'explorer', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'complete beginner'},
            'source': {'origin': origin, 'reason': 'test'}, 'phases': phases, 'lessons': lessons}


PIANO_ROW = _library_row(PIANO, 'Learn piano', [
    {'id': FOUND, 'name': 'Foundations', 'weeks': 2, 'what': 'Hands and keys', 'steps': ['Old phase warm-up'],
     'milestone': 'Plays a C scale hands together', 'progression': 'One less reminder'},
    {'id': SONGS, 'name': 'Songs', 'weeks': 3, 'what': 'Whole tunes', 'steps': [],
     'milestone': 'Plays Twinkle for the family'}], [
    {'id': SCALES, 'phase_id': FOUND, 'title': 'Scales', 'sessions': 2, 'steps': ['C major, slowly'],
     'variants': [{'label': 'Session A', 'steps': ['Right hand']}, {'label': 'Session B', 'steps': ['Left hand']}]},
    {'id': CHORDS, 'phase_id': FOUND, 'title': 'Chords', 'sessions': 1, 'steps': ['C, F and G'], 'variants': []},
    {'id': TWINKLE, 'phase_id': SONGS, 'title': 'Twinkle', 'sessions': 2, 'steps': ['The melody'], 'variants': []}])
# The plan follows a lesson book, so the run sheet's ⋯ offers Plan without the book (P4).
PIANO_ROW['source']['book_spine'] = 'Piano Adventures'
KATE_SLOTS = [{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}, {'day': 4, 'time_start': '16:30'}]


def _progress(current=SCALES, lessons=None, judged=None):
    return {'current': current, 'lessons': copy.deepcopy(lessons or {}),
            'phases': {FOUND: {'weeks': 2, 'milestone_hit_at': (judged or {}).get(FOUND)},
                       SONGS: {'weeks': 3, 'milestone_hit_at': (judged or {}).get(SONGS)}}}


def _run(rid, member, library_id, project_id, progress=None, state='active'):
    from services import projects
    storage.add_program({'id': rid, 'member_id': member, 'library_id': library_id, 'state': state,
                         'shape': dict(_SHAPE), 'baseline': dict(_BASELINE), 'created_by': 'mom',
                         'progress': progress if progress is not None else {'current': None, 'lessons': {}, 'phases': {}}})
    projects.adopt('program', rid, None, project_id=project_id)


def seed():
    if TOKENS:
        return
    for m in ({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'email': 'mom@example.com', 'color_code': '#287a72'},
              {'id': 'dad', 'name': 'Dad', 'role': 'parent', 'color_code': '#7a2850'},
              {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult', 'color_code': '#285a7a'},
              {'id': 'kate', 'name': 'Kate', 'role': 'child', 'birthdate': '2017-02-01', 'color_code': '#5a7a28'},
              {'id': 'sam', 'name': 'Sam', 'role': 'child', 'color_code': '#7a5a28'}):
        storage.add_member(m)
    for who in ('mom', 'dad', 'aunt', 'kate', 'sam'):
        TOKENS[who] = storage.create_member_token(who)
    for pid, title, audience, owner in (('prj-piano', 'Piano for Kate', 'household', 'mom'), ('prj-sam', "Sam's music", 'private', 'mom'),
                                        ('prj-kate', 'My songs', 'parents', 'kate')):
        storage.add_project({'id': pid, 'title': title, 'goal': title, 'done_when': 'it is a habit', 'owner_member_id': owner,
                             'created_by': owner, 'audience': audience, 'pieces': [], 'steps': []})
    storage.add_library_program(copy.deepcopy(PIANO_ROW))
    storage.add_library_program(_library_row(DRUMS, 'Learn drums', [{'id': 'ph-beat', 'name': 'Beat', 'weeks': 2, 'steps': [], 'milestone': 'Keeps time'}],
                                             [{'id': 'ls-beat', 'phase_id': 'ph-beat', 'title': 'Quarter notes', 'sessions': 1, 'steps': ['Count four'], 'variants': []}]))
    storage.add_library_program(_library_row(CHESS, 'Learn chess', [{'id': 'ph-open', 'name': 'Openings', 'weeks': 2, 'steps': [], 'milestone': 'Plays a game'}],
                                             [{'id': 'ls-open', 'phase_id': 'ph-open', 'title': 'The opening', 'sessions': 1, 'steps': ['Centre pawns'], 'variants': []}],
                                             origin='cited'))
    # Kate's run is on the calendar for real: approved on three windows, so Change the days
    # has commitments to release and claim (programs spec §5.3).
    _run('run-kate', 'kate', PIANO, 'prj-piano', _progress(), state='proposed')
    _run('run-sam', 'sam', PIANO, 'prj-sam', _progress())
    _run('run-sam-drums', 'sam', DRUMS, 'prj-sam', {'current': 'ls-beat', 'lessons': {}, 'phases': {'ph-beat': {'weeks': 2, 'milestone_hit_at': None}}})
    _run('run-lost', 'kate', 'lib-gone', 'prj-piano')
    from services import programs
    approved = programs.approve('run-kate', 'mom', slots=KATE_SLOTS)
    check(approved['status'] == 'success' and storage.get_program('run-kate')['emissions']['commitment_ids'],
          f"the fixture's run claims its windows: {approved}")
    storage.set_app_state('projects_adopted_rev', 1)   # the startup migration must not re-wrap the fixture


def _stub_curation():
    """Making a program curates; no research or model call leaves this test."""
    from services import programs_curate

    def curate(title, profile, **kw):
        return {'phases': [{'name': 'Getting started', 'weeks': 2, 'milestone': 'Plays one whole piece',
                            'units': [{'title': 'First notes', 'sessions': 1, 'steps': ['Hold it right']}]}],
                'source': {'origin': 'generated', 'reason': 'test'}}
    programs_curate.curate = curate


def serve():
    from live_app import live_app
    served = live_app(seed)
    if served is not None:
        storage.update_settings({'auth_enforce': True, 'missions_enabled': True, 'programs_enabled': True})
        _stub_curation()
    return served


def admin(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_admin_token': TOKENS[who], 'chauffeur_admin_token_for': who})


def pwa(page, served, who, theme='dark'):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_member_id': who, 'chauffeur_member_token': TOKENS[who], 'chauffeur_member_token_for': who,
                   'chauffeur_theme': theme})


def _open_projects(page):
    """Projects lives in More on the phone (one-list spec §5); as project_sheets_fixture.open_projects."""
    page.locator('#tab-more').click()
    page.locator('#pwa-feature-list').get_by_text('Projects', exact=True).first.click()
    page.wait_for_selector('#projects-container [data-project-card], #projects-container [data-project-detail]', timeout=15000)


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'), full_page=True)


def _gone(rid):
    row = storage.get_program(rid)
    return row is None or bool(row.get('deleting'))


def _wait(cond, msg, tries=60):
    for _ in range(tries):
        value = cond()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError(msg)


def _card(page, lid):
    return page.locator(f'[data-library-list] [data-library-card][data-library-id="{lid}"]')


def _library(page, served, who, query=''):
    admin(page, served, who)
    page.goto(served.url('library' + query), wait_until='load')
    # The list draws cards; a program (?id=) opens on its course page (programs spec §3).
    page.wait_for_selector('[data-library-card], [data-course-header]', timeout=20000)


def _confirm_text(page):
    page.locator('#cc-confirm-modal').wait_for(state='visible', timeout=10000)
    return page.locator('#cc-confirm-modal').inner_text()


def _edit_by_hand(page, scope=''):
    """The course page keeps today's editor behind ⋯ › Edit by hand (spec §3.5): the admin
    page's ⋯ is #cc-choice-modal, the phone's its own prompt (.pwa-prompt-overlay)."""
    page.locator(f'{scope} [data-course-menu]'.strip()).first.click()
    if page.locator('#cc-choice-modal').count():
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        page.locator('#cc-choice-modal button', has_text='Edit by hand').click()
    else:
        page.locator('.pwa-prompt-overlay [data-pick]', has_text='Edit by hand').click()
    page.wait_for_selector(f'{scope} [data-edit-by-hand]'.strip(), timeout=5000)


def _project(page, served, who, pid='prj-piano'):
    admin(page, served, who)
    page.goto(served.url('projects?id=' + pid), wait_until='load')
    page.wait_for_selector('[data-project-detail]', timeout=20000)


def _reset_kate(progress=None):
    storage.update_program('run-kate', {'progress': progress or _progress()})
    from services import library
    library._invalidate()


def _restore_piano():
    """The course scenarios read Learn piano as seeded: earlier scenarios rename, add and remove
    its lessons, so the fixture's phases and lessons go back first (and Kate onto Scales)."""
    storage.update_library_program(PIANO, {'title': PIANO_ROW['title'], 'phases': copy.deepcopy(PIANO_ROW['phases']),
                                           'lessons': copy.deepcopy(PIANO_ROW['lessons']), 'archived': False})
    _reset_kate()


# 1 -------------------------------------------------------------------------
def scenario_the_library_page_lists_each_program():
    served = serve()
    if served is None:
        return
    from services import library
    with served.browser() as page:
        _library(page, served, 'mom')
        tab = page.locator('#page-tabs [data-tab-key="library"]')
        check(tab.count() == 1 and 'bg-blue-600' in (tab.get_attribute('class') or ''),
              "Library is a tab of the Work group, and the one shown")
        check(page.locator('#page-tabs [data-tab-key="projects"]').count() == 1, "beside Projects")
        check(_card(page, PIANO).count() == 1 and _card(page, DRUMS).count() == 1 and _card(page, CHESS).count() == 1,
              "one card per library program")
        card = _card(page, PIANO)
        text = card.inner_text()
        made_for = 'Made for ' + library.made_for_line(PIANO_ROW['made_for']) + ', 3 a week'
        for want in ('Learn piano', made_for, 'Assumes: complete beginner', 'Made by the app', '3 lessons'):
            check(want in text, f"the card says {want!r}: {text}")
        runners = card.locator('[data-library-runner]')
        check(runners.count() == 2 and all(runners.nth(i).evaluate('el => el.tagName') == 'BUTTON' for i in range(2)),
              "both runners Mom can see are buttons")
        labels = runners.all_inner_texts()
        check('Kate · Piano for Kate' in labels and "Sam · Sam's music" in labels, f"each runner with their project: {labels}")
        check('· cited' in _card(page, CHESS).inner_text(), "a cited plan's chip")
        check(not COUNT.search(text), f"no fraction on a library card: {text}")
        shot(page, 'library-admin-dark')
        check(served.errors() == [], f"no page errors: {served.errors()}")
    with served.browser() as page:
        _library(page, served, 'dad')
        card = _card(page, PIANO)
        text = card.inner_text()
        check('Kate · Piano for Kate' in text and 'Sam' not in text and 'and 1 more' in text,
              f"Dad sees Kate's run named and Sam's counted, never named: {text}")
        card.locator('[data-library-runner]').first.click()
        page.wait_for_url(re.compile(r'work\?tab=projects&id=prj-piano'), timeout=15000)
        page.wait_for_selector('[data-project-detail]', timeout=15000)
        check('Piano for Kate' in page.locator('[data-project-detail]').inner_text(), "a runner opens their project")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 2 -------------------------------------------------------------------------
def scenario_a_new_program_says_what_the_household_will_see():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _library(page, served, 'mom')
        page.locator('[data-library-new]').click()
        page.locator('[data-brief-by-hand]').click()
        form = page.locator('[data-library-create-form]')
        form.wait_for(state='visible')
        line, title = form.locator('[data-visibility-line]'), form.locator('input[name="title"]')
        check(line.evaluate('(el, t) => !!(el.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING)', title.element_handle()),
              "the publication line sits above the title")
        check(form.locator('select[name="age_band"]').input_value() == 'any', "a library program with nobody yet starts at any age")
        title.fill('Learn guitar')
        check(line.inner_text() == 'Everyone in the household will see this program as: Learn guitar',
              f"the line follows the typed title: {line.inner_text()}")
        form.locator('input[name="assumes"]').fill('complete beginner')
        form.locator('[data-library-create]').click()
        made = _wait(lambda: [r for r in storage.get_library_programs() if r['title'] == 'Learn guitar'], "the program was made")
        check(made[0]['created_by'] == 'mom' and made[0]['made_for']['age_band'] == 'any', f"made by Mom, public profile: {made[0]}")
        page.wait_for_selector('[data-library-detail]', timeout=10000)
        check('First notes' in page.locator('[data-library-detail]').inner_text(), "and it opens on its lessons")
        check(served.errors() == [], f"no page errors: {served.errors()}")

    # The project's Make a new one (the setup sheet's): the person's band, and the private starting point.
    with served.browser() as page:
        _project(page, served, 'mom')
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Program').first.click()
        form = page.locator('[data-setup-sheet]')
        form.wait_for(state='visible')
        page.wait_for_selector('[data-setup-pick]', timeout=10000)
        form.locator('[data-setup-who]').select_option('kate')
        form.locator('[data-setup-make-new]').click()
        fresh = form.locator('[data-setup-new]')
        fresh.wait_for(state='visible')
        check(fresh.locator('select[name="age_band"]').input_value() == 'explorer', "Kate's band comes from her birthdate")
        check(form.locator('[data-private-label]').inner_text() == "stays private to Kate's program", "the starting point is Kate's alone")
        line, title = fresh.locator('[data-visibility-line]'), fresh.locator('input[name="title"]')
        check(line.evaluate('(el, t) => !!(el.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING)', title.element_handle()),
              "the publication line sits above the title here too")
        form.locator('[data-setup-who]').select_option('sam')
        check(fresh.locator('select[name="age_band"]').input_value() == 'any', "no birthdate on file: any")
        check(form.locator('[data-private-label]').inner_text() == "stays private to Sam's program", "the label follows the person")
        form.locator('[data-setup-who]').select_option('kate')
        title.fill('Learn violin')
        check(line.inner_text() == 'Everyone in the household will see this program as: Learn violin', "the line follows")
        form.locator('input[name="starting_point"]').fill('knows the open strings')
        shot(page, 'setup-sheet-make-new')
        form.locator('[data-setup-start]').click()
        lib = _wait(lambda: [r for r in storage.get_library_programs() if r['title'] == 'Learn violin'], "the violin program was made")[0]
        run = _wait(lambda: [r for r in storage.get_programs(include_finished=True) if r.get('library_id') == lib['id']], "and a run")[0]
        check(run['member_id'] == 'kate' and run['state'] == 'active' and run['starting_point'] == 'knows the open strings',
              f"Kate's program starts in one pass and carries her starting point: {run}")
        check('open strings' not in repr(lib) and lib['made_for']['age_band'] == 'explorer', f"the library row never does: {lib}")
        page.wait_for_selector(f'[data-row="program:{run["id"]}"]', timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 3 -------------------------------------------------------------------------
def scenario_editing_a_program_inline():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _library(page, served, 'mom', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail]', timeout=10000)
        _edit_by_hand(page)
        chords = page.locator(f'[data-library-lesson][data-lesson-id="{CHORDS}"]')
        chords.locator('[data-lesson-edit]').click()
        form = chords.locator('[data-lesson-form]')
        form.locator('input[name="lesson_title"]').fill('Chords in C')
        form.locator('textarea[name="lesson_steps"]').fill('C chord\nF chord\nG chord')
        form.locator('input[name="lesson_sessions"]').fill('2')
        form.locator('select[name="lesson_material"]').select_option('url')
        form.locator('input[name="lesson_url"]').fill('https://example.com/chords')
        form.locator('[data-lesson-save]').click()
        lesson = _wait(lambda: next((l for l in storage.get_library_program(PIANO)['lessons']
                                     if l['id'] == CHORDS and l['title'] == 'Chords in C'), None), "the lesson saved")
        check(lesson['steps'] == ['C chord', 'F chord', 'G chord'] and lesson['sessions'] == 2
              and lesson['url'] == 'https://example.com/chords', f"title, steps, sessions and link: {lesson}")
        scales = page.locator(f'[data-library-lesson][data-lesson-id="{SCALES}"]')
        scales.locator('[data-lesson-edit]').click()
        scales.locator('[data-variant-row] input[name="variant_label"]').first.fill('Right hand day')
        scales.locator('textarea[name="lesson_body"]').fill('Thumb under on F')
        scales.locator('[data-lesson-save]').click()
        lesson = _wait(lambda: next((l for l in storage.get_library_program(PIANO)['lessons']
                                     if l['id'] == SCALES and l['variants'][0]['label'] == 'Right hand day'), None), "the rotation label saved")
        check(lesson['variants'][0]['steps'] == ['Right hand'] and lesson['body'] == 'Thumb under on F'
              and lesson['variants'][1]['label'] == 'Session B', f"the rotation kept its steps: {lesson}")
        shot(page, 'library-edit-dark')
        # Drag Chords above Scales; Up puts it back (the touch path).
        page.locator(f'[data-lesson-id="{CHORDS}"]').drag_to(page.locator(f'[data-lesson-id="{SCALES}"]'))
        _wait(lambda: [l['id'] for l in storage.get_library_program(PIANO)['lessons']][:2] == [CHORDS, SCALES], "dragging reorders")
        check(storage.get_program('run-kate')['progress']['current'] == SCALES, "a reorder moves no bookmark")
        page.wait_for_function(f"() => document.querySelector('[data-phase-id=\"{FOUND}\"] [data-library-lesson]').dataset.lessonId === '{CHORDS}'", timeout=10000)
        page.locator(f'[data-library-lesson][data-lesson-id="{SCALES}"] [data-lesson-up]').click()
        _wait(lambda: [l['id'] for l in storage.get_library_program(PIANO)['lessons']][:2] == [SCALES, CHORDS], "Up reorders")
        # Add lesson, through the shared input prompt.
        page.locator(f'[data-library-add-lesson][data-phase-id="{SONGS}"]').click()
        page.locator('#cc-input-modal').wait_for(state='visible')
        page.locator('#cc-input-field').fill('Ode to Joy')
        page.locator('#cc-input-ok-btn').click()
        added = _wait(lambda: next((l for l in storage.get_library_program(PIANO)['lessons'] if l['title'] == 'Ode to Joy'), None), "added")
        check(added['phase_id'] == SONGS, f"added to its phase: {added}")
        page.wait_for_selector(f'[data-lesson-id="{added["id"]}"]', timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")
    with served.browser() as page:
        _library(page, served, 'aunt', '?id=' + PIANO)
        refused = 'the server responded with a status of 403'
        page.wait_for_selector('[data-library-detail]', timeout=10000)
        check(page.locator('[data-library-refusal]').inner_text() == REFUSAL, "Aunt Jo reads the refusal where the controls would be")
        check(page.locator('[data-lesson-edit], [data-lesson-remove], [data-library-add-lesson], [data-library-delete]').count() == 0,
              "and no edit control is drawn for her")
        page.locator('[data-course-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        offered = page.locator('#cc-choice-options button').all_inner_texts()
        check(not any(w in l for l in offered for w in ('Edit by hand', 'Steer', 'Archive', 'Delete', 'Write lessons')),
              f"and her ⋯ offers no editing: {offered}")
        page.locator('#cc-choice-cancel-btn').click()
        status, detail = page.evaluate("""async (lid) => {
            const r = await fetch('api/library/' + lid, {method: 'PATCH', headers: {'Content-Type': 'application/json'},
                                                          body: JSON.stringify({title: 'Piano, my way'})});
            return [r.status, (await r.json()).detail];
        }""", PIANO)
        check(status == 403 and detail == REFUSAL, f"the server refuses her in the same words: {status} {detail}")
        others = [e for e in served.errors() if refused not in e]
        check(others == [] and len(served.errors()) - len(others) == 1, f"only the refused PATCH logged: {served.errors()}")


# 4 -------------------------------------------------------------------------
def scenario_archive_leaves_the_picker_not_the_library():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _library(page, served, 'mom')
        _card(page, CHESS).locator('[data-library-archive]').click()
        check('picker' in _confirm_text(page), "Archive asks first and says what it does")
        page.locator('#cc-confirm-execute-btn').click()
        _wait(lambda: storage.get_library_program(CHESS)['archived'], "archived")
        page.wait_for_selector(f'[data-library-list] [data-library-id="{CHESS}"] [data-library-archived]', timeout=10000)
        check(_card(page, CHESS).locator('[data-library-archive]').count() == 0, "stays on the page, Archive gone")
    with served.browser() as page:
        _project(page, served, 'mom')
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Program').first.click()
        page.wait_for_selector('[data-setup-pick]', timeout=10000)
        picks = page.locator('[data-setup-pick]')
        ids = [picks.nth(i).get_attribute('data-setup-pick') for i in range(picks.count())]
        check(CHESS not in ids and PIANO in ids, f"the archived program is not offered: {ids}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 5 -------------------------------------------------------------------------
def scenario_delete_waits_until_nobody_runs_it():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _library(page, served, 'dad')
        piano, drums = _card(page, PIANO), _card(page, DRUMS)
        check(piano.locator('[data-library-delete]').is_disabled() and drums.locator('[data-library-delete]').is_disabled(),
              "Delete is disabled while a run uses the program")
        check(piano.locator('[data-library-in-use]').inner_text() == "In use by Kate's project",
              f"a runner Dad sees is named: {piano.locator('[data-library-in-use]').inner_text()}")
        check(drums.locator('[data-library-in-use]').inner_text() == 'In use by another project',
              "a project Dad cannot see is never named")
        shot(page, 'library-delete-disabled-dark')
    with served.browser() as page:
        _library(page, served, 'mom')
        check(_card(page, PIANO).locator('[data-library-in-use]').inner_text() == "In use by Kate, Sam's project", "Mom sees both")
        chess = _card(page, CHESS)
        check(not chess.locator('[data-library-delete]').is_disabled(), "an unused program can be deleted")
        chess.locator('[data-library-delete]').click()
        _confirm_text(page)
        page.locator('#cc-confirm-execute-btn').click()
        _wait(lambda: storage.get_library_program(CHESS) is None, "deleted")
        page.wait_for_function(f"() => !document.querySelector('[data-library-id=\"{CHESS}\"]')", timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 7 -------------------------------------------------------------------------
def scenario_the_picker_starts_the_program():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _project(page, served, 'mom')
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Program').first.click()
        form = page.locator('[data-setup-sheet]')
        page.wait_for_selector('[data-setup-pick]', timeout=10000)
        row = form.locator(f'[data-setup-pick="{PIANO}"]')
        text = row.inner_text()
        check('Learn piano' in text and 'Made for ages' in text and 'Running it: Kate and Sam' in text,
              f"title, made-for and visible runners: {text}")
        order = form.evaluate("""f => [...f.querySelectorAll('[data-setup-pick], [data-setup-make-new]')]
                                     .map(el => el.hasAttribute('data-setup-make-new') ? 'new' : 'pick')""")
        check(order[-1] == 'new' and order.count('new') == 1, f"Make a new one comes after the list: {order}")
        shot(page, 'library-picker-dark')
        before = {r['id'] for r in storage.get_programs(include_finished=True)}
        row.click()
        page.wait_for_selector('[data-setup-slot]', timeout=10000)
        form.locator('[data-setup-start]').click()
        run = _wait(lambda: [r for r in storage.get_programs(include_finished=True) if r['id'] not in before], "a run")[0]
        check(run['library_id'] == PIANO and run['member_id'] == 'mom' and run['state'] == 'active'
              and run['shape']['minutes'] == 20, f"a parent's pick starts the program with its defaults: {run}")
        check(run['project_id'] == 'prj-piano', "in this project")
        piece = page.locator(f'[data-row="program:{run["id"]}"]')
        piece.first.wait_for(state='visible', timeout=10000)
        check(page.locator(f'[data-row="program:{run["id"]}"] [data-row-action="approve"]').count() == 0,
              f"nothing left to approve: {piece.first.inner_text()}")
        check(served.errors() == [], f"no page errors: {served.errors()}")
    with served.browser() as page:
        page.set_viewport_size({'width': 390, 'height': 844})
        refused = []
        page.on('response', lambda r: r.status == 403 and refused.append(r.url))
        pwa(page, served, 'kate')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_function("() => typeof setView === 'function' && !!document.getElementById('tab-more')", timeout=20000)
        page.wait_for_timeout(1500)
        page.evaluate("() => setView('projects')")   # an explorer reaches Projects from her own shell
        page.wait_for_selector('[data-project-id="prj-kate"]', timeout=15000)
        page.locator('[data-project-id="prj-kate"]').first.click()
        page.wait_for_selector('[data-project-add]', timeout=10000)
        page.locator('[data-project-add]').click()
        page.locator('[data-pick]', has_text='Program').first.click()
        page.wait_for_selector('[data-setup-pick]', timeout=10000)
        check(page.locator('[data-setup-make-new], [data-setup-new]').count() == 0, "a child picks; she never makes one")
        check(page.locator(f'[data-setup-pick="{PIANO}"]').count() == 1, "from the same library")
        check(page.locator('[data-setup-who]').is_disabled() and page.locator('[data-setup-who] option').count() == 1,
              "she starts one for herself only")
        check(page.locator('[data-setup-start]').inner_text().strip() == 'Ask to start the program', "and asks rather than starts")
        width = page.evaluate('() => [document.documentElement.scrollWidth, window.innerWidth]')
        check(width[0] <= width[1], f"no horizontal scroll on the phone: {width}")
        shot(page, 'library-picker-child-phone-dark')
        mine = [u for u in refused if '/library' in u or '/programs' in u or '/projects' in u]
        check(mine == [], f"nothing on these surfaces is refused: {mine}")
        others = [e for e in served.errors() if 'status of 403' not in e]
        check(others == [], f"no page errors: {served.errors()} (refused elsewhere in the kid shell: {refused})")


# 8 -------------------------------------------------------------------------
def scenario_the_run_card_names_the_lesson():
    served = serve()
    if served is None:
        return
    _reset_kate()
    with served.browser() as page:
        _project(page, served, 'mom')
        # The project's rows for the run (one-list spec §1): title, subtitle, when; the library
        # link and the lesson line live in its sheet, below.
        rows = page.locator('[data-row="program:run-kate"]')
        rows.first.wait_for(state='visible', timeout=10000)
        text = ' | '.join(rows.all_inner_texts())
        check(not COUNT.search(text), f"never a count: {text}")
        shot(page, 'run-card-admin-dark')
        page.locator('[data-piece-open="program:run-kate"]').click()
        sheet = page.locator('[data-record-sheet]')
        page.wait_for_selector(f'[data-record-sheet] [data-monitor-phase="{FOUND}"] [data-rung-current][data-rung="{SCALES}"]', timeout=15000)
        check(sheet.locator('[data-monitor]').inner_text().startswith('Learn piano'), "the program's name heads the sheet")
        link = sheet.locator('[data-library-link]')
        check(link.evaluate('el => el.tagName') == 'BUTTON' and link.inner_text().strip() == 'in the library ›',
              f"the library link is a button: {link.inner_text()}")
        body = sheet.inner_text()
        check(not COUNT.search(body), f"no count in the sheet either: {body[:400]}")
        shot(page, 'run-sheet-admin-dark')
        sheet.locator('[data-library-link]').click()
        page.wait_for_url(re.compile(r'library\?id=' + PIANO), timeout=15000)
        page.wait_for_selector('[data-library-detail]', timeout=15000)
        check('Learn piano' in page.locator('[data-library-detail]').inner_text(), "the button opens the library program")
        check(served.errors() == [], f"no page errors: {served.errors()}")
    with served.browser() as page:
        page.set_viewport_size({'width': 390, 'height': 844})
        pwa(page, served, 'mom')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_selector('#tab-more', state='visible', timeout=20000)
        _open_projects(page)
        page.wait_for_selector('[data-project-id="prj-piano"]', timeout=15000)
        page.locator('[data-project-id="prj-piano"]').first.click()
        page.wait_for_selector('[data-piece-open="program:run-kate"]', timeout=10000)
        check(page.locator('#projects-container a[href]').count() == 0, "the phone's project rows are buttons only")
        page.locator('[data-piece-open="program:run-kate"]').click()
        page.wait_for_selector('[data-piece-sheet] [data-current-lesson]', timeout=10000)
        sheet = page.locator('[data-piece-sheet]')
        check('Scales · Foundations' in sheet.locator('[data-current-lesson]').inner_text()
              and sheet.locator('[data-library-link]').inner_text().strip() == 'from the library: Learn piano',
              f"the phone's own program card: {sheet.inner_text()[:300]}")
        check(not COUNT.search(sheet.inner_text()), "no count on the phone")
        check(sheet.locator('a[href]').count() == 0, "buttons only on the phone's run card")
        shot(page, 'run-sheet-phone-dark')
        sheet.locator('[data-library-link]').click()
        page.wait_for_selector('#library-container [data-library-detail]', timeout=10000)
        check(page.locator('#library-container').is_visible(), "the phone opens its library home on the program")
        page.wait_for_function("() => !document.querySelector('[data-piece-sheet]') && !document.querySelector('.pwa-prompt-overlay')", timeout=5000)
        # The library's own controls take the tap: nothing covers them.
        _edit_by_hand(page, '#library-container')
        edit = page.locator(f'#library-container [data-lesson-id="{SCALES}"] [data-lesson-edit]')
        edit.click(timeout=5000)
        page.locator(f'#library-container [data-lesson-id="{SCALES}"] [data-lesson-form]').wait_for(state='visible', timeout=5000)
        shot(page, 'run-sheet-phone-to-library-dark')
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 16 ------------------------------------------------------------------------
def scenario_a_library_edit_reaches_a_paused_runs_phone_card():
    served = serve()
    if served is None:
        return
    from services import library
    _reset_kate(_progress(CHORDS))
    storage.update_program('run-kate', {'state': 'paused'})
    library._invalidate()
    library.update_lesson(PIANO, CHORDS, {'url': 'https://example.com/chords', 'body': ''}, storage.get_member('mom'))
    duet = library.add_lesson(PIANO, {'phase_id': SONGS, 'title': "Mom & Kate's duet", 'sessions': 1, 'steps': ['Together']},
                              storage.get_member('mom'))
    duet_id = next(l['id'] for l in duet['program']['lessons'] if l['title'] == "Mom & Kate's duet")
    try:
        with served.browser() as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            pwa(page, served, 'mom')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#tab-more', timeout=20000)
            page.locator('#tab-more').click()
            page.locator('[data-feature="library"]').click()
            home = page.locator('#library-container')
            home.locator(f'[data-library-card][data-library-id="{PIANO}"] [data-library-view]').click()
            _edit_by_hand(page, '#library-container')
            lesson = home.locator(f'[data-lesson-id="{CHORDS}"]')
            lesson.locator('[data-lesson-edit]').click()
            lesson.locator('textarea[name="lesson_steps"]').fill('Strum C, then F\nHold each for four')
            lesson.locator('[data-lesson-save]').click()
            _wait(lambda: next(l for l in storage.get_library_program(PIANO)['lessons'] if l['id'] == CHORDS)['steps']
                  == ['Strum C, then F', 'Hold each for four'], "the edit saved from the phone")
            # Confirm titles carry people's words as they are, escaped once.
            home.locator(f'[data-lesson-id="{duet_id}"] [data-lesson-remove]').click()
            overlay = page.locator('.pwa-prompt-overlay:has([data-yes]):has([data-no])').last
            overlay.wait_for(state='visible', timeout=10000)
            text = overlay.inner_text()
            check("Remove Mom & Kate's duet?" in text and '&amp;' not in text and '&#39;' not in text,
                  f"the phone's confirm shows the title unescaped: {text}")
            overlay.locator('[data-no]').click()

            page.reload(wait_until='load')
            page.wait_for_function("() => typeof setView === 'function'", timeout=20000)
            page.evaluate("() => setView('projects')")
            page.wait_for_selector('[data-project-id="prj-piano"]', timeout=15000)
            page.locator('[data-project-id="prj-piano"]').first.click()
            page.locator('[data-piece-open="program:run-kate"]').click()
            page.wait_for_selector('[data-piece-sheet] [data-current-lesson]', timeout=10000)
            sheet = page.locator('[data-piece-sheet]')
            body = sheet.inner_text()
            check('Strum C, then F' in body and 'Hold each for four' in body,
                  f"the paused run's card reads the edited lesson: {body[:500]}")
            check('Old phase warm-up' not in body, f"never the phase's own steps: {body[:500]}")
            check(sheet.locator('a[href]').count() == 0, "no anchor on the phone's run card")
            link = sheet.locator('button[data-lesson-url]')
            check(link.count() == 1 and link.inner_text().strip() == 'Open the lesson', "the lesson's page is a button")
            page.evaluate("() => { window.__opened = []; window.open = (u) => { window.__opened.push(u); return null; }; }")
            link.click()
            check(page.evaluate('() => window.__opened') == ['https://example.com/chords'], "and it opens that page")
            shot(page, 'run-paused-phone-edited-lesson-dark')
            check(served.errors() == [], f"no page errors: {served.errors()}")
        with served.browser() as page:
            _library(page, served, 'mom', '?id=' + PIANO)
            page.wait_for_selector('[data-library-detail]', timeout=10000)
            _edit_by_hand(page)
            page.locator(f'[data-lesson-id="{duet_id}"] [data-lesson-remove]').click()
            _confirm_text(page)
            title = page.locator('#cc-confirm-title').inner_text()
            check(title == "Remove Mom & Kate's duet?", f"the admin confirm's title is the words as typed: {title}")
            page.locator('#cc-confirm-cancel-btn').click()
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        library.remove_lesson(PIANO, duet_id, storage.get_member('mom'))
        storage.update_program('run-kate', {'state': 'active'})
        _reset_kate()


# 13 ------------------------------------------------------------------------
def scenario_an_exhausted_phase_waits_for_judgement():
    served = serve()
    if served is None:
        return
    stamp = time.time()
    _reset_kate(_progress(CHORDS, {SCALES: {'done_sessions': 2, 'completed_at': stamp},
                                   CHORDS: {'done_sessions': 2, 'completed_at': stamp}}))
    try:
        with served.browser() as page:
            _project(page, served, 'mom')
            # The ready-to-judge line and the lesson line live in the run's sheet (one-list spec §1).
            page.locator('[data-piece-open="program:run-kate"]').click()
            page.wait_for_selector('[data-record-sheet] [data-ready-to-judge]', timeout=15000)
            page.wait_for_function("() => (document.querySelector('[data-record-sheet] [data-ready-to-judge]') || {}).offsetParent !== null", timeout=15000)
            check(page.locator('[data-record-sheet] [data-ready-to-judge]').inner_text().strip() == '· every lesson done — reached it?',
                  "the phase waits on the person")
            check(page.locator(f'[data-record-sheet] [data-monitor-phase="{FOUND}"] [data-rung-current]').get_attribute('data-rung') == CHORDS
                  and page.locator(f'[data-record-sheet] [data-monitor-phase="{FOUND}"] [data-reached-it="{FOUND}"]').count() == 1,
                  "and has not moved on by itself: Reached it is beside the lit rung")
            shot(page, 'run-ready-to-judge-dark')
            check(storage.get_program('run-kate')['progress']['phases'][FOUND]['milestone_hit_at'] is None, "nothing was judged for her")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        _reset_kate()


# 10 ------------------------------------------------------------------------
def scenario_next_back_and_reached_it():
    served = serve()
    if served is None:
        return
    _reset_kate()
    try:
        with served.browser() as page:
            _project(page, served, 'mom')
            page.locator('[data-piece-open="program:run-kate"]').click()
            sheet = page.locator('[data-record-sheet]')
            page.wait_for_selector('[data-record-sheet] [data-unit-move="next"]', state='attached', timeout=15000)
            sheet.locator('[data-unit-move="next"]:visible').click()
            _wait(lambda: storage.get_program('run-kate')['progress']['current'] == CHORDS, "Next moves one lesson on")
            page.wait_for_selector(f'[data-record-sheet] [data-monitor-phase="{FOUND}"] [data-rung-current][data-rung="{CHORDS}"]', timeout=10000)
            back = sheet.locator('[data-unit-move="back"]:visible')
            check(back.inner_text().strip() == 'Another session on this', "Back keeps its name")
            back.click()
            _wait(lambda: storage.get_program('run-kate')['progress']['current'] == SCALES, "Back moves one lesson back")
            page.wait_for_selector(f'[data-record-sheet] [data-monitor-phase="{FOUND}"] [data-rung-current][data-rung="{SCALES}"]', timeout=10000)
            sheet.locator(f'[data-reached-it="{FOUND}"]').click()
            _confirm_text(page)
            page.locator('#cc-confirm-execute-btn').click()
            run = _wait(lambda: (lambda r: r if r['progress']['phases'][FOUND].get('milestone_hit_at') else None)(storage.get_program('run-kate')),
                        "Reached it judges the phase by its id")
            check(run['state'] == 'active' and run['progress']['current'] == TWINKLE, f"a non-final phase keeps the run going: {run['state']} {run['progress']}")
            page.wait_for_selector(f'[data-record-sheet] [data-monitor-phase="{SONGS}"] [data-rung-current][data-rung="{TWINKLE}"]', timeout=10000)
            shot(page, 'run-sheet-reached-it-dark')
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        _reset_kate()


# 6 -------------------------------------------------------------------------
def scenario_removing_the_current_lesson_says_who_is_on_it():
    served = serve()
    if served is None:
        return
    _reset_kate()
    with served.browser() as page:
        _library(page, served, 'dad', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail]', timeout=10000)
        _edit_by_hand(page)
        page.locator(f'[data-library-lesson][data-lesson-id="{SCALES}"] [data-lesson-remove]').click()
        text = _confirm_text(page)
        check('Kate is on this lesson; her run moves to the next one.' in text, f"the runner Dad sees, by name: {text}")
        check('1 other run is on this lesson' in text and 'Sam' not in text, f"the hidden one counted, never named: {text}")
        shot(page, 'library-remove-confirm-dark')
        page.locator('#cc-confirm-cancel-btn').click()
        check(any(l['id'] == SCALES for l in storage.get_library_program(PIANO)['lessons']), "Keep it keeps it")
        page.locator(f'[data-library-lesson][data-lesson-id="{SCALES}"] [data-lesson-remove]').click()
        _confirm_text(page)
        page.locator('#cc-confirm-execute-btn').click()
        _wait(lambda: not any(l['id'] == SCALES for l in storage.get_library_program(PIANO)['lessons']), "removed")
        check(storage.get_program('run-kate')['progress']['current'] == CHORDS, "her run moved to the next lesson")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 9 -------------------------------------------------------------------------
def scenario_an_unresolved_run_can_be_deleted_or_rebound():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _project(page, served, 'mom')
        # One-list rows (spec §1): the unresolved run's row says so and offers Pick a program;
        # its sheet carries the missing-program copy and Delete.
        row = page.locator('[data-row="program:run-lost"]')
        row.wait_for(state='visible', timeout=10000)
        text = row.inner_text()
        check('Needs a program' in text, f"the unresolved row: {text}")
        check(row.locator('[data-row-action="rebind"]').inner_text().strip() == 'Pick a program', "and Pick a program")
        shot(page, 'run-unresolved-admin-dark')
        row.locator('[data-row-title]').click()
        sheet = page.locator('[data-record-sheet]')
        page.wait_for_selector('[data-record-sheet] [data-run-unresolved]', timeout=15000)
        page.wait_for_function("() => (document.querySelector('[data-record-sheet] [data-run-unresolved]') || {}).offsetParent !== null", timeout=15000)
        check('Its library program is missing' in sheet.inner_text(), f"the unresolved copy: {sheet.inner_text()[:300]}")
        check(sheet.locator('[data-run-delete]:visible').count() == 1, "with Delete")
        check(sheet.locator('[data-library-link]:visible, [data-current-lesson]:visible').count() == 0, "and no lesson to name")
        page.locator('[data-record-sheet-close]').click()
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)
        row.locator('[data-row-action="rebind"]').click()
        page.locator('[data-prompt-choice]', has_text='Learn piano').first.click()
        _wait(lambda: storage.get_program('run-lost')['library_id'] == PIANO, "rebound to the program picked")
        page.wait_for_function("() => ![...document.querySelectorAll('[data-row=\"program:run-lost\"]')].some(r => r.innerText.includes('Needs a program'))", timeout=10000)
        page.locator('[data-piece-open="program:run-lost"]').click()
        page.wait_for_function("() => { const c = document.querySelector('[data-record-sheet] [data-monitor]'); return c && c.offsetParent !== null && c.innerText.startsWith('Learn piano') && !!c.querySelector('[data-library-link]'); }", timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")
    storage.update_program('run-lost', {'library_id': 'lib-gone'})
    from services import library
    library._invalidate()
    with served.browser() as page:
        page.set_viewport_size({'width': 390, 'height': 844})
        pwa(page, served, 'mom')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_selector('#tab-more', state='visible', timeout=20000)
        _open_projects(page)
        page.wait_for_selector('[data-project-id="prj-piano"]', timeout=15000)
        page.locator('[data-project-id="prj-piano"]').first.click()
        page.wait_for_selector('[data-piece-open="program:run-lost"]', timeout=10000)
        page.locator('[data-piece-open="program:run-lost"]').click()
        page.wait_for_selector('[data-piece-sheet] [data-run-unresolved]', timeout=10000)
        sheet = page.locator('[data-piece-sheet]')
        check('Its library program is missing' in sheet.inner_text() and sheet.locator('[data-run-rebind]').count() == 1
              and sheet.locator('[data-run-delete]').count() == 1, f"the phone's card offers both: {sheet.inner_text()[:300]}")
        shot(page, 'run-unresolved-phone-dark')
        sheet.locator('[data-run-delete]').click()
        overlay = page.locator('.pwa-prompt-overlay:has([data-yes]):has([data-no])').last
        overlay.wait_for(state='visible', timeout=10000)
        check('Its library program is missing' in overlay.inner_text(), f"the delete names the run: {overlay.inner_text()}")
        overlay.locator('[data-yes]').click()
        _wait(lambda: _gone('run-lost'), "Delete deletes the run")
        check(storage.get_library_program(PIANO) is not None, "never the library program")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 11 + 12 -------------------------------------------------------------------
def scenario_the_phone_library_home_light_and_dark():
    served = serve()
    if served is None:
        return
    for theme in ('dark', 'light'):
        with served.browser() as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            pwa(page, served, 'mom', theme)
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#tab-more', timeout=20000)
            page.locator('#tab-more').click()
            page.locator('[data-feature="library"]').click()
            page.wait_for_selector('#library-container [data-library-card]', timeout=15000)
            home = page.locator('#library-container')
            check(home.is_visible(), "More -> Library opens the library home")
            check(home.locator('a[href]').count() == 0, "buttons only on the phone")
            check(page.locator('#tab-more').get_attribute('aria-current') == 'page', "and More stays the tab you are in")
            width = page.evaluate('() => [document.documentElement.scrollWidth, window.innerWidth]')
            check(width[0] <= width[1], f"no horizontal scroll ({theme}): {width}")
            box = home.locator('[data-library-card]').first.bounding_box()
            check(box['x'] >= 15.5 and box['x'] + box['width'] <= 390 - 15.5, f"a 16px gutter ({theme}): {box}")
            shot(page, f'library-phone-{theme}')
            home.locator(f'[data-library-card][data-library-id="{PIANO}"] [data-library-view]').click()
            page.wait_for_selector('#library-container [data-library-detail]', timeout=10000)
            width = page.evaluate('() => [document.documentElement.scrollWidth, window.innerWidth]')
            check(width[0] <= width[1], f"no horizontal scroll in the program ({theme}): {width}")
            check(home.locator('a[href]').count() == 0, f"buttons only on the phone's course page ({theme})")
            box = home.locator('[data-course-header]').bounding_box()
            check(box['x'] >= 15.5 and box['x'] + box['width'] <= 390 - 15.5, f"a 16px gutter on the course page ({theme}): {box}")
            shot(page, f'library-phone-course-{theme}')
            _edit_by_hand(page, '#library-container')
            check(home.locator('[data-lesson-up]').count() > 0, "Up and Down stand in for drag on the phone")
            width = page.evaluate('() => [document.documentElement.scrollWidth, window.innerWidth]')
            check(width[0] <= width[1], f"no horizontal scroll while editing ({theme}): {width}")
            shot(page, f'library-phone-detail-{theme}')
            check(served.errors() == [], f"no page errors ({theme}): {served.errors()}")


# 14 ------------------------------------------------------------------------
def scenario_look_again_says_progress_starts_over():
    served = serve()
    if served is None:
        return
    picked = storage.get_app_state('library_live_picked')
    if not picked or not storage.get_program(picked):
        _run('run-mom-proposed', 'mom', PIANO, 'prj-piano', _progress(), state='proposed')
        picked = 'run-mom-proposed'
    with served.browser() as page:
        _project(page, served, 'mom')
        page.locator(f'[data-piece-open="program:{picked}"]').click()
        sheet = page.locator('[data-record-sheet]')
        sheet.get_by_role('button', name='Look again', exact=True).wait_for(state='visible', timeout=15000)
        sheet.get_by_role('button', name='Edit', exact=True).click()
        check(sheet.locator('[data-retitle-ruling]').inner_text() == 'The name belongs to the library program; rename the project instead.',
              "the retitle control is gone, and its place says why")
        check(sheet.locator('input[placeholder="The aim"]').count() == 0, "no aim to type")
        sheet.get_by_role('button', name='Look again', exact=True).click()
        text = _confirm_text(page)
        check('new library program' in text and 'Progress on this program starts over' in text and 'regenerated' in text,
              f"Look again says what it costs: {text}")
        shot(page, 'run-look-again-confirm-dark')
        page.locator('#cc-confirm-cancel-btn').click()
        check(storage.get_program(picked)['library_id'] == PIANO, "Not now changes nothing")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# Programs brief-and-course spec §4: one-pass setup ---------------------------
def scenario_setup_sheet_lands_active():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.wait_for_selector('[data-project-add]', timeout=15000)
        page.locator('[data-project-add]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        page.locator('#cc-choice-modal button', has_text='Program').click()
        page.wait_for_selector('[data-setup-sheet]', timeout=10000)
        page.locator('[data-setup-who]').select_option('sam')
        page.locator(f'[data-setup-pick="{DRUMS}"]').click()
        page.wait_for_selector('[data-setup-slot]', timeout=10000)
        n = page.locator('[data-setup-slot]').count()
        check(n >= 1, "the app proposed days once who and which are chosen")
        page.locator('[data-setup-slot]').first.locator('[data-slot-day]').select_option('4')
        shot(page, 'setup-sheet-filled')
        on_screen = sorted({(int(v), t) for v, t in page.evaluate("""() => [...document.querySelectorAll('[data-setup-slot]')]
            .map(r => [r.querySelector('[data-slot-day]').value, r.querySelector('[data-slot-time]').value])""")})
        page.locator('[data-setup-start]').click()
        page.wait_for_selector('[data-setup-sheet]', state='detached', timeout=15000)
        from services import storage
        run = next(r for r in storage.get_programs(include_finished=True) if r['member_id'] == 'sam' and r['library_id'] == DRUMS and r['project_id'] == 'prj-piano')
        check(run['state'] == 'active' and run['emissions']['commitment_ids'], f"one pass, active: {run['state']}")
        claimed = sorted((x['day'], x['time_start']) for x in run['shape']['slots'])
        check(claimed == on_screen and any(d == 4 for d, _ in claimed), f"the times on the sheet are the times claimed: {claimed} vs {on_screen}")
        shot(page, 'setup-sheet-active')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_setup_preview_failure_shows_retry():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.route('**/api/programs/preview-slots', lambda route: route.fulfill(status=500, body='{}'))
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.locator('[data-project-add]').click()
        page.locator('#cc-choice-modal button', has_text='Program').click()
        page.locator(f'[data-setup-pick="{DRUMS}"]').click()
        page.wait_for_selector('[data-setup-retry]', timeout=10000)
        check("Couldn't look at the week" in page.locator('[data-setup-sheet]').inner_text(), "the failure is said, with Retry")
        shot(page, 'setup-sheet-retry')


# Programs brief-and-course spec §5: the monitoring sheet ---------------------
def scenario_monitoring_sheet():
    served = serve()
    if served is None:
        return
    _reset_kate()
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'projects?id=prj-piano&piece=program:run-kate'), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"] [data-monitor-stats]', timeout=15000)
        sheet = page.locator('[data-record-sheet]')
        text = sheet.inner_text()
        for word in ('Re-shape', 'claim', 'footprint', 'ready to judge', 'rotation'):
            check(word not in text, f"no '{word}' on the sheet")
        check(page.locator('[data-reached-it]').count() == 2, "Reached it on every unjudged phase (P2)")
        check(page.locator('[data-rung-current]').count() == 1, "one lit rung")
        check(sheet.locator('button:visible').count() <= 8, f"a monitoring sheet, not a button wall: {sheet.locator('button:visible').count()}")
        stats = sheet.locator('[data-monitor-stats]').inner_text()
        check('sessions this week' in stats and ' of ' not in stats, f"a count, never a fraction (P1): {stats}")
        page.locator('[data-run-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Change the days', 'Program settings', 'Log a session', 'Start a session', 'Look again', 'Plan without the book', 'Pause', 'Done with it', 'Drop', 'Delete'):
            check(any(want in l for l in labels), f"⋯ holds {want}: {labels}")
        page.keyboard.press('Escape')
        shot(page, 'monitor-sheet')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_change_the_days_from_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'projects?id=prj-piano&piece=program:run-kate'), wait_until='load')
        page.wait_for_selector('[data-run-menu]', timeout=15000)
        page.locator('[data-run-menu]').click()
        page.locator('#cc-choice-modal button', has_text='Change the days').click()
        page.wait_for_selector('[data-days-editor] [data-setup-slot]', timeout=10000)
        page.locator('[data-days-editor] [data-setup-slot]').first.locator('[data-slot-day]').select_option('6')
        shot(page, 'monitor-change-the-days')
        page.locator('[data-days-save]').click()
        page.wait_for_selector('[data-days-editor]', state='detached', timeout=10000)
        from services import storage
        check(6 in storage.get_program('run-kate')['shape']['preferred_days'], "the days changed in one write")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_start_a_session_from_the_sheet():
    """⋯ › Start a session (P7) is the real Start: a window from the chooser opens the player on
    that window's lesson, and finishing it logs the session against that window's date."""
    served = serve()
    if served is None:
        return
    import datetime
    from services import programs
    _reset_kate()
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    moved = programs.replace_schedule('run-kate', [{'day': tomorrow.weekday(), 'time_start': '18:00'}], storage.get_member('mom'))
    check(moved['status'] == 'success', f"the fixture has a window tomorrow: {moved}")
    want = next(w for w in programs.practice_windows(tomorrow, tomorrow, 'kate') if w.get('program_id') == 'run-kate')
    before = len(storage.get_program('run-kate').get('sessions') or [])
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano&piece=program:run-kate'), wait_until='load')
        page.wait_for_selector('[data-run-menu]', timeout=15000)
        page.locator('[data-run-menu]').click()
        page.locator('#cc-choice-modal button', has_text='Start a session').click()
        page.wait_for_function("() => document.querySelector('#cc-choice-title') && document.querySelector('#cc-choice-title').innerText.includes('Which session?')", timeout=10000)
        page.locator('#cc-choice-modal button', has_text='Tomorrow').first.click()
        player = page.locator('[x-data="lessonPlayer()"]')
        player.wait_for(state='visible', timeout=10000)
        opened = page.evaluate("""() => { const w = Alpine.$data(document.querySelector('[x-data="lessonPlayer()"]')).w || {};
                                         return {date: w.date, lesson_id: w.lesson_id, variant_label: w.variant_label || '', program_id: w.program_id}; }""")
        check(opened == {'date': tomorrow.isoformat(), 'lesson_id': want['lesson_id'], 'variant_label': want.get('variant_label') or '',
                         'program_id': 'run-kate'}, f"the player opens on that window's lesson: {opened} vs {want}")
        shot(page, 'monitor-start-a-session')
        # Quiet first (headless has no speech engine to hand a send-off line to), then the player's
        # own finish(): the footer's last step, which asks "Log this session?".
        voice_off = player.get_by_role('button', name='Turn the voice off', exact=True)
        if voice_off.count():
            voice_off.click()
        page.evaluate("""() => { Alpine.$data(document.querySelector('[x-data="lessonPlayer()"]')).finish(); }""")
        _confirm_text(page)
        page.locator('#cc-confirm-execute-btn').click()
        run = _wait(lambda: (lambda r: r if len(r.get('sessions') or []) > before else None)(storage.get_program('run-kate')),
                    "finishing logs the session")
        last = run['sessions'][-1]
        check(last.get('slot_date') == tomorrow.isoformat() and last.get('lesson_id') == want['lesson_id'] and last.get('source') == 'asked',
              f"logged against that window: {last}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_failed_footprint_says_so_with_retry():
    """Spec §9: a proposal whose footprint read fails says so and offers Retry, never 'Working it out…' forever."""
    served = serve()
    if served is None:
        return
    if not storage.get_program('run-footprint'):
        _run('run-footprint', 'sam', DRUMS, 'prj-piano', {'current': 'ls-beat', 'lessons': {}, 'phases': {'ph-beat': {'weeks': 2, 'milestone_hit_at': None}}},
             state='proposed')
    with served.browser() as page:
        admin(page, served, 'mom')
        page.route('**/footprint', lambda route: route.fulfill(status=500, body='{}'))
        page.goto(served.url('projects?id=prj-piano&piece=program:run-footprint'), wait_until='load')
        page.wait_for_selector('[data-record-sheet] [data-footprint-retry]', timeout=15000)
        check("Couldn't work out the week" in page.locator('[data-record-sheet] [data-footprint-failed]').inner_text(), "the failure is said")
        shot(page, 'footprint-retry')
        page.unroute('**/footprint')
        page.locator('[data-record-sheet] [data-footprint-retry]').click()
        page.wait_for_selector('[data-record-sheet] [data-footprint-failed]', state='detached', timeout=10000)
        check(page.locator('[data-record-sheet]').get_by_role('button', name='Approve', exact=True).is_visible(), "Retry reads the week and Approve is back")
        check(not [e for e in served.errors() if 'status of 500' not in e], f"no page errors: {served.errors()}")


def scenario_escape_closes_only_the_top_sheet():
    """The setup sheet opened over a record sheet: one Escape closes the setup sheet alone."""
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano&piece=program:run-kate'), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"] [data-run-menu]', timeout=15000)
        page.evaluate("() => window.chfProgramSetup.open({runId: 'run-kate', projectId: 'prj-piano'})")
        page.wait_for_selector('[data-setup-sheet] [data-setup-slot]', timeout=10000)
        page.keyboard.press('Escape')
        page.wait_for_selector('[data-setup-sheet]', state='detached', timeout=5000)
        check(page.locator('[data-record-sheet][data-open="true"]').count() == 1, "the record sheet beneath stays open")
        page.keyboard.press('Escape')
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


# Programs brief-and-course spec §1-§3: the course page, Steer and the brief box --------
def scenario_course_page_at_rest():
    served = serve()
    if served is None:
        return
    _restore_piano()
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'library?id={PIANO}'), wait_until='load')
        page.wait_for_selector('[data-course-header]', timeout=15000)
        check(page.locator('[data-lesson-edit]').count() == 0 and page.locator('[data-lesson-up]').count() == 0, "no editor controls at rest")
        n = page.locator('[data-course-lesson]').count()
        check(n == 3 and page.locator('[data-lesson-preview]').count() == n, "one Preview per lesson")
        check(page.locator('[data-lesson-summary]').first.inner_text().strip() != '', "a sentence per lesson")
        check(page.locator('[data-script-chip]').count() <= 1, "chips only while writing or failed")
        text = page.locator('[data-course-source]').inner_text()
        check('lessons' in text and ('Based on' in text or 'Made by the app' in text or 'Practice time only' in text), f"source line: {text}")
        page.locator('[data-course-why]').click()
        check('Why' in page.locator('[data-course-header]').inner_text(), "Why this one unfolds")
        page.locator('[data-course-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Steer in words', 'Edit by hand', 'Write lessons', 'Make a variant', 'Archive', 'Delete', 'Start it for'):
            check(any(want in l for l in labels), f"⋯ holds {want}: {labels}")
        page.locator('#cc-choice-modal button', has_text='Edit by hand').click()
        page.wait_for_selector('[data-lesson-edit]', timeout=5000)
        check(page.locator('[data-lesson-up]').count() >= 1 and page.locator('[data-library-add-lesson]').count() >= 1, "Edit by hand reveals today's editor")
        shot(page, 'course-page')


def scenario_steer_posts_and_shows_changes():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.route('**/api/library/*/steer', lambda route: route.fulfill(status=200, content_type='application/json',
            body='{"status":"success","changes":["Scales: 3 sessions → 2","+ Duet with a parent after Chords"],"said":"Done.","program":{}}'))
        page.goto(served.url(f'library?id={PIANO}'), wait_until='load')
        page.wait_for_selector('[data-steer-box]', timeout=15000)
        page.locator('[data-steer-box]').fill('shorter scales and a duet')
        page.locator('[data-steer-send]').click()
        page.wait_for_selector('[data-steer-changes]', timeout=10000)
        check('Duet with a parent' in page.locator('[data-steer-changes]').inner_text(), "the change list is shown")
        shot(page, 'course-steer-changes')


def scenario_brief_box_on_the_list_page():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('library'), wait_until='load')
        page.wait_for_selector('[data-library-new]', timeout=15000)
        page.locator('[data-library-new]').click()
        page.wait_for_selector('[data-brief-box]', timeout=5000)
        check(page.locator('[data-brief-find]').count() == 1 and page.locator('[data-library-create-form] input[name="title"]').count() == 0, "the brief box leads; the form is folded")
        page.locator('[data-brief-by-hand]').click()
        page.wait_for_selector('[data-library-create-form] input[name="title"]', timeout=5000)
        shot(page, 'library-brief')


def scenario_phone_keeps_edit_by_hand_without_scripts():
    """The brief's phone scenario. The phone carries its own prompt family (app.html
    promptChoice: .pwa-prompt-overlay [data-pick]); #cc-choice-modal is the admin page's."""
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        pwa(page, served, 'mom')
        page.goto(served.url('app?view=library'), wait_until='load')
        page.wait_for_selector('[data-library-page]', timeout=15000)
        page.locator(f'[data-library-open][data-library-id="{PIANO}"]').first.click()
        page.wait_for_selector('[data-course-menu]', timeout=10000)
        page.locator('[data-course-menu]').click()
        page.wait_for_selector('.pwa-prompt-overlay [data-pick]', timeout=5000)
        labels = page.locator('.pwa-prompt-overlay [data-pick]').all_inner_texts()
        check(any('Edit by hand' in l for l in labels) and not any('Write lessons' in l for l in labels), f"phone: Edit by hand yes, Write lessons no (P3): {labels}")
        page.locator('.pwa-prompt-overlay [data-pick]', has_text='Edit by hand').click()
        page.wait_for_selector('[data-lesson-edit]', timeout=5000)
        check(page.locator('[data-script-edit]').count() == 0, "no script editor on the phone")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_preview_offers_each_session_and_each_runner():
    """Spec §3.3: one script plays at once; variants or a visible runner open a chooser, and
    "as Kate" plays her run's script through the run's own route."""
    served = serve()
    if served is None:
        return
    _restore_piano()
    with served.browser() as page:
        admin(page, served, 'dad')   # Dad sees Kate's run named, Sam's only counted
        asked = []
        page.on('request', lambda r: asked.append(r.url) if '/lesson' in r.url and r.method == 'GET' else None)
        page.goto(served.url(f'library?id={PIANO}'), wait_until='load')
        page.wait_for_selector('[data-course-header]', timeout=15000)
        found = page.locator(f'[data-course-phase="{FOUND}"]')
        check(found.inner_text().startswith('1 · Foundations · done when plays a C scale hands together'), f"the phase, numbered: {found.inner_text()[:120]}")
        check(found.locator('[data-phase-progression]').inner_text().strip() == 'Next time: One less reminder', "and its progression")
        check(page.locator(f'[data-course-phase="{SONGS}"] [data-phase-progression]').count() == 0, "only where one is set")
        shot(page, 'course-page-rest')
        scales = page.locator(f'[data-course-lesson="{SCALES}"]')
        check(scales.locator('[data-lesson-preview]').get_attribute('data-preview-choice') is not None, "a lesson with sessions opens a chooser")
        check('Session A' in scales.locator('[data-lesson-summary]').inner_text(), "the sessions are named inside the sentence")
        scales.locator('[data-lesson-preview]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-options button').all_inner_texts()
        check('Session A' in labels and 'Session B' in labels, f"each session: {labels}")
        check(any('as Kate' in l for l in labels) and not any('Sam' in l for l in labels), f"the visible runner only: {labels}")
        page.locator('#cc-choice-options button', has_text='Session A, as Kate').click()
        player = page.locator('[x-data="lessonPlayer()"]')
        player.wait_for(state='visible', timeout=10000)
        check(any('/api/programs/run-kate/lesson?lesson_id=' + SCALES in u and 'variant_label=Session%20A' in u for u in asked),
              f"as Kate reads her run's script: {asked}")
        check('Just a look' in player.inner_text(), "and it is a preview")
        player.get_by_role('button', name='Close session', exact=True).click()
        player.wait_for(state='hidden', timeout=5000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_steer_on_a_changed_program_says_read_again():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        # The DM course card's Steer lands here (chfLibrary.open(id, {steer: true})).
        page.goto(served.url(f'library?id={PIANO}&steer=1'), wait_until='load')
        page.wait_for_selector('[data-steer-box]', timeout=15000)
        page.wait_for_function("() => document.activeElement && document.activeElement.hasAttribute('data-steer-box')", timeout=5000)
        check('steer=' not in page.url, f"the address forgets the steer flag: {page.url}")
        # Someone else changes the program after this page read it: the revision moves on.
        from services import library
        library.update(PIANO, {'title': 'Learn piano'}, storage.get_member('dad'))
        sent = []
        page.on('request', lambda r: sent.append(r.post_data_json) if r.url.endswith('/steer') else None)
        page.locator('[data-steer-box]').fill('fewer scales')
        page.locator('[data-steer-send]').click()
        page.locator('#cc-alert-modal').wait_for(state='visible', timeout=15000)
        said = page.locator('#cc-alert-message').inner_text()
        check(said == 'The program changed; read it again.', f"a stale steer is refused in words: {said}")
        check(sent and isinstance(sent[0].get('revision'), int), f"the steer sent the revision it read: {sent}")
        check(page.locator('[data-steer-changes]').count() == 0, "and nothing claims to have changed")
        others = [e for e in served.errors() if 'status of 409' not in e]
        check(others == [], f"no page errors: {served.errors()}")


def scenario_find_a_plan_offers_to_start_it_for_the_person():
    """Spec §1 + P6 on the Library page: a brief naming Kate makes a library program, opens it,
    and offers Start it for Kate; the setup sheet opens with her chosen and her own words
    (starting point, days) prefilled. A refusal is said in the box, never a dialog."""
    served = serve()
    if served is None:
        return
    from services import program_brief
    real = program_brief.parse
    brief = {'title': 'Learn ukulele', 'for_member_id': 'kate',
             'profile': {'age_band': 'explorer', 'minutes': 20, 'sessions_per_week': 2, 'assumes': ''},
             'starting_point': 'knows two chords', 'preferred_days': [1, 3], 'target_date': None,
             'based_on': '', 'exclude_books': False, 'notes': ''}
    answers = [{'status': 'error', 'message': 'Say what Kate should learn.', 'alternatives': ['Learn ukulele']},
               {'status': 'success', 'brief': brief}]
    program_brief.parse = lambda *a, **k: answers.pop(0)
    try:
        with served.browser() as page:
            admin(page, served, 'mom')
            page.goto(served.url('library'), wait_until='load')
            page.wait_for_selector('[data-library-new]', timeout=15000)
            page.locator('[data-library-new]').click()
            page.locator('[data-brief-box]').fill('Something for Kate.')
            page.locator('[data-brief-find]').click()
            page.wait_for_selector('[data-brief-error]', timeout=10000)
            err = page.locator('[data-brief-error]').inner_text()
            check('Say what Kate should learn.' in err and 'Learn ukulele' in err, f"the refusal is said in the box: {err}")
            check(not page.locator('#cc-alert-modal').is_visible(), "never a dialog")
            bodies = []
            page.on('request', lambda r: bodies.append(r.post_data_json) if r.url.endswith('/api/programs/preview-slots') else None)
            page.locator('[data-brief-box]').fill('Ukulele for Kate, she knows two chords, Tuesdays and Thursdays.')
            page.locator('[data-brief-find]').click()
            text = _confirm_text(page)
            check('Start it for Kate?' in text, f"the page offers Start it for Kate: {text}")
            made = next(r for r in storage.get_library_programs() if r['title'] == 'Learn ukulele')
            check('knows two chords' not in repr(made), f"her starting point never reaches the library row: {made}")
            page.wait_for_function("() => (document.querySelector('[data-course-header]') || {}).innerText?.includes('Learn ukulele')", timeout=10000)
            page.locator('#cc-confirm-execute-btn').click()
            page.wait_for_selector('[data-setup-sheet] [data-setup-slot]', timeout=10000)
            sheet = page.locator('[data-setup-sheet]')
            check(sheet.locator('[data-setup-who]').input_value() == 'kate', "Kate is chosen")
            check(sheet.locator(f'[data-setup-pick="{made["id"]}"]').get_attribute('aria-pressed') == 'true', "on the program just made")
            check(sheet.locator('input[name="starting_point"]').input_value() == 'knows two chords', "her starting point is prefilled")
            check(bodies and bodies[-1].get('preferred_days') == [1, 3], f"the days she asked for seed the week: {bodies}")
            shot(page, 'library-brief-start-for')
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        program_brief.parse = real
        for r in storage.get_library_programs():
            if r['title'] == 'Learn ukulele':
                storage.delete_library_program(r['id'])


def scenario_make_a_variant_and_start_it_for_from_the_menu():
    """⋯ › Make a variant is today's re-curate: a NEW library program from this one's profile
    plus the words typed, the original untouched. ⋯ › Start it for… opens the setup sheet on
    the program."""
    served = serve()
    if served is None:
        return
    before = {r['id'] for r in storage.get_library_programs()}
    original = copy.deepcopy(storage.get_library_program(DRUMS))
    try:
        with served.browser() as page:
            admin(page, served, 'mom')
            page.goto(served.url(f'library?id={DRUMS}'), wait_until='load')
            page.wait_for_selector('[data-course-header]', timeout=15000)
            page.locator('[data-course-menu]').click()
            page.locator('#cc-choice-modal button', has_text='Make a variant').click()
            page.locator('#cc-input-modal').wait_for(state='visible', timeout=5000)
            page.locator('#cc-input-field').fill('more fills, fewer rests')
            page.locator('#cc-input-ok-btn').click()
            fresh = _wait(lambda: [r for r in storage.get_library_programs() if r['id'] not in before], "a variant was made")[0]
            check(fresh['made_for'] == original['made_for'] and fresh['created_by'] == 'mom', f"from the same profile: {fresh['made_for']}")
            now = storage.get_library_program(DRUMS)
            check(now['lessons'] == original['lessons'] and now['phases'] == original['phases'], "the original is untouched")
            page.wait_for_function(f"() => new URLSearchParams(location.search).get('id') === '{fresh['id']}'", timeout=10000)
            page.wait_for_selector('[data-course-header]', timeout=10000)
            page.locator('[data-course-menu]').click()
            page.locator('#cc-choice-modal button', has_text='Start it for').click()
            page.wait_for_selector(f'[data-setup-sheet] [data-setup-pick="{fresh["id"]}"][aria-pressed="true"]', timeout=10000)
            page.keyboard.press('Escape')
            page.wait_for_selector('[data-setup-sheet]', state='detached', timeout=5000)
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        for r in storage.get_library_programs():
            if r['id'] not in before:
                storage.delete_library_program(r['id'])


NONE_ID = 'lib-none'


def scenario_practice_time_only_offers_look_again():
    """Spec §1 + §10: a program whose research could not run reads "Practice time only ·
    {reason}" with Look again (a fresh curation from the same profile, asked first, never a
    browser dialog; this row stays), and Edit by hand still opens on its empty curriculum."""
    served = serve()
    if served is None:
        return
    if not storage.get_library_program(NONE_ID):
        row = _library_row(NONE_ID, 'Learn juggling', [], [], origin='none')
        row['source']['reason'] = 'research could not run'
        storage.add_library_program(row)
    before = {r['id'] for r in storage.get_library_programs()}
    _run('run-practice-only', 'kate', NONE_ID, 'prj-piano', state='proposed')
    try:
        with served.browser() as page:
            admin(page, served, 'mom')
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            page.goto(served.url(f'library?id={NONE_ID}'), wait_until='load')
            page.wait_for_selector('[data-course-header]', timeout=15000)
            source = page.locator('[data-course-source]').inner_text()
            check(source.startswith('Practice time only · research could not run') and '0 lessons' in source,
                  f"the source line says why there is no plan: {source}")
            check(page.locator('[data-look-again]').count() == 1, "with Look again on the source row")
            page.locator('[data-course-why]').click()
            why = page.locator('[data-course-why-text]').inner_text()
            check('Make a variant' not in why and 'no lessons yet' in why, f"the fold says what it means: {why}")
            page.locator('[data-course-menu]').click()
            page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
            check('Look again' in page.locator('#cc-choice-options button').all_inner_texts(), "and in ⋯")
            page.locator('#cc-choice-cancel-btn').click()
            shot(page, 'course-practice-time-only')
            page.locator('[data-look-again]').click()
            text = _confirm_text(page)
            check('Look again makes a fresh program from the same profile. This one stays in the library until you archive it.' in text,
                  f"Look again says what it does: {text}")
            check('1 run stays on this one; use Look again on the run itself to move a run.' in text, f'runners consequence: {text}')
            page.locator('#cc-confirm-cancel-btn').click()
            check({r['id'] for r in storage.get_library_programs()} == before, "Not now makes nothing")
            _edit_by_hand(page)
            check(page.locator('[data-edit-by-hand] [data-library-lesson]').count() == 0, "Edit by hand opens on no lessons")
            page.locator('[data-edit-done]').click()
            page.wait_for_selector('[data-edit-by-hand]', state='detached', timeout=5000)
            page.locator('[data-look-again]').click()
            _confirm_text(page)
            page.locator('#cc-confirm-execute-btn').click()
            fresh = _wait(lambda: [r for r in storage.get_library_programs() if r['id'] not in before], "a fresh program was curated")[0]
            check(fresh['title'] == 'Learn juggling' and fresh['made_for'] == storage.get_library_program(NONE_ID)['made_for'],
                  f"from the same profile: {fresh}")
            check(storage.get_library_program(NONE_ID) and not storage.get_library_program(NONE_ID).get('archived'), "this one stays")
            page.wait_for_function(f"() => new URLSearchParams(location.search).get('id') === '{fresh['id']}'", timeout=10000)
            check(dialogs == [], f"no browser dialog: {dialogs}")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        from services import projects
        removed = projects.remove_piece('prj-piano', 'program', 'run-practice-only', storage.get_member('mom'))
        check(removed['status'] == 'success', f'practice-only piece removed: {removed}')
        storage.delete_program('run-practice-only')
        for r in storage.get_library_programs():
            if r['id'] not in before or r['id'] == NONE_ID:
                storage.delete_library_program(r['id'])


def scenario_edit_by_hand_reaches_the_profile_and_reorder_and_asks_before_dropping():
    """Every hand verb stays reachable behind Edit by hand: the profile form and ▼ (the
    others are driven by the scenarios above). Done editing with an open form asks first."""
    served = serve()
    if served is None:
        return
    _restore_piano()
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'library?id={PIANO}'), wait_until='load')
        page.wait_for_selector('[data-course-header]', timeout=15000)
        _edit_by_hand(page)
        toggle = page.locator('[data-library-profile-toggle]')
        check(toggle.count() == 1, "The name and who it's made for is reachable")
        toggle.click()
        form = page.locator('[data-library-profile]')
        form.wait_for(state='visible', timeout=5000)
        check(form.locator('input[name="title"]').input_value() == 'Learn piano', "and opens on the program's profile")
        form.get_by_role('button', name='Cancel', exact=True).click()
        form.wait_for(state='detached', timeout=5000)
        page.locator(f'[data-library-lesson][data-lesson-id="{SCALES}"] [data-lesson-down]').click()
        _wait(lambda: [l['id'] for l in storage.get_library_program(PIANO)['lessons']][:2] == [CHORDS, SCALES], "▼ reorders")
        page.wait_for_function(f"() => document.querySelector('[data-phase-id=\"{FOUND}\"] [data-library-lesson]').dataset.lessonId === '{CHORDS}'", timeout=10000)
        page.locator(f'[data-library-lesson][data-lesson-id="{SCALES}"] [data-lesson-up]').click()
        _wait(lambda: [l['id'] for l in storage.get_library_program(PIANO)['lessons']][:2] == [SCALES, CHORDS], "and ▲ puts it back")
        # An open lesson form holds typing: Done editing asks before dropping it.
        chords = page.locator(f'[data-library-lesson][data-lesson-id="{CHORDS}"]')
        chords.locator('[data-lesson-edit]').click()
        chords.locator('input[name="lesson_title"]').fill('Chords, typed but not saved')
        page.locator('[data-edit-done]').click()
        text = _confirm_text(page)
        check('Drop the unsaved changes?' in text, f"Done editing asks first: {text}")
        page.locator('#cc-confirm-cancel-btn').click()
        check(chords.locator('input[name="lesson_title"]').input_value() == 'Chords, typed but not saved', "Keep editing keeps the typing")
        page.locator('[data-edit-done]').click()
        _confirm_text(page)
        page.locator('#cc-confirm-execute-btn').click()
        page.wait_for_selector('[data-edit-by-hand]', state='detached', timeout=5000)
        check(next(l for l in storage.get_library_program(PIANO)['lessons'] if l['id'] == CHORDS)['title'] == 'Chords', "nothing was saved")
        # Nothing open: Done editing just leaves.
        _edit_by_hand(page)
        page.locator('[data-edit-done]').click()
        page.wait_for_selector('[data-edit-by-hand]', state='detached', timeout=5000)
        check(not page.locator('#cc-confirm-modal').is_visible(), "without asking when nothing is open")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_unnamed_brief_explains_private_starting_point_once():
    served = serve()
    if served is None:
        return
    from unittest.mock import patch
    from services import program_brief
    brief = {'title': 'Learn harmonica', 'for_member_id': None,
             'profile': {'age_band': 'any', 'minutes': 20, 'sessions_per_week': 2, 'assumes': ''},
             'starting_point': 'knows two tunes', 'preferred_days': [], 'target_date': None,
             'notes': '', 'based_on': '', 'exclude_books': False}
    before = {r['id'] for r in storage.get_library_programs()}
    try:
        with patch.object(program_brief, 'parse', return_value={'status': 'success', 'brief': brief}), served.browser() as page:
            admin(page, served, 'mom')
            page.goto(served.url('library'), wait_until='load')
            page.locator('[data-library-new]').click()
            page.locator('[data-brief-box]').fill('Harmonica, already knows two tunes')
            page.locator('[data-brief-find]').click()
            notice = page.locator('[data-brief-notice]')
            notice.wait_for(state='visible', timeout=15000)
            check(notice.count() == 1 and notice.inner_text() == 'What they can already do was not kept; add it when you start it for someone.', 'once, inline in the brief box')
            check(page.locator('[data-brief-box]').is_visible() and not page.locator('#cc-alert-modal').is_visible(), 'brief box stays open without dialog')
            shot(page, 'brief-private-notice')
    finally:
        for row in storage.get_library_programs():
            if row['id'] not in before:
                storage.delete_library_program(row['id'])


SCENARIOS = [scenario_unnamed_brief_explains_private_starting_point_once,
             scenario_the_library_page_lists_each_program, scenario_a_new_program_says_what_the_household_will_see,
             scenario_editing_a_program_inline, scenario_archive_leaves_the_picker_not_the_library,
             scenario_delete_waits_until_nobody_runs_it, scenario_the_picker_starts_the_program,
             scenario_the_run_card_names_the_lesson, scenario_an_exhausted_phase_waits_for_judgement,
             scenario_next_back_and_reached_it, scenario_look_again_says_progress_starts_over,
             scenario_a_library_edit_reaches_a_paused_runs_phone_card,
             scenario_removing_the_current_lesson_says_who_is_on_it, scenario_an_unresolved_run_can_be_deleted_or_rebound,
             scenario_the_phone_library_home_light_and_dark,
             scenario_setup_sheet_lands_active, scenario_setup_preview_failure_shows_retry,
             scenario_monitoring_sheet, scenario_change_the_days_from_the_sheet,
             scenario_start_a_session_from_the_sheet, scenario_a_failed_footprint_says_so_with_retry,
             scenario_escape_closes_only_the_top_sheet,
             scenario_course_page_at_rest, scenario_steer_posts_and_shows_changes, scenario_brief_box_on_the_list_page,
             scenario_phone_keeps_edit_by_hand_without_scripts, scenario_preview_offers_each_session_and_each_runner,
             scenario_a_steer_on_a_changed_program_says_read_again, scenario_find_a_plan_offers_to_start_it_for_the_person,
             scenario_make_a_variant_and_start_it_for_from_the_menu, scenario_practice_time_only_offers_look_again,
             scenario_edit_by_hand_reaches_the_profile_and_reorder_and_asks_before_dropping]

if __name__ == "__main__":
    import traceback
    only = sys.argv[1:]
    failed = 0
    for fn in SCENARIOS:
        if only and not any(o in fn.__name__ for o in only):
            continue
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
