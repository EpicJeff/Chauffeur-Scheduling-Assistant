"""Program-owned lesson scripts, live (spec 2026-10-20-lesson-depth-design.md rev 3, sections 8 and 9 "Live").

Playwright scenarios against a live add-on run, with screenshots inspected in light and dark at
phone width. A live test that needs auth enforcement must not import tests/harness.py. No browser
dialogs anywhere (showGlobalAlert, promptConfirm, promptInput); buttons, not anchors, on the phone.

  1. Library page: each lesson row shows a chip (`no script yet` / `ready · about 12 min` /
     `failed · {note}` / `writing…`), Play for everyone, Edit and Regenerate for `can_edit`.
  2. Card header: Write lessons for `can_edit`; `Writing lessons · 2 of 4` when the job map holds
     an entry.
  3. Edit: add a teach row, fill title, text, two examples (`Dó | pt-BR`), speak; Save; reload;
     the fields come back; the thirteenth row on a 30-minute profile is accepted; the thirty-first
     refused. (Task 5 review) A failed read of the script shows Retry, draws no rows, keeps Add
     and Save off, and can never lead to a PUT.
  4. Play opens the player in preview with `{name}` filled with the viewer's name.
  5. Rhythms (`/rhythms`): a library run shows `Scripts live in the library: Learn piano` and no
     editor; an unconverted run still shows the editor. (The run editor lives in programs_page.html,
     which the Projects page's record sheet hosts; the scenario opens it there.)
  6. Settings drawer Lessons tab: `lesson_pool` select present; no Write lessons now; no report.
  7. Phone More → Library: chips and Play only; buttons, not anchors.
  8. Light and dark at phone width; screenshots inspected.

`library_scripts.write` is stubbed: it writes one fixed script synchronously through
`storage.edit_library_script` (so the chip flips to ready with no model call), and the
`Writing lessons · 2 of 4` line comes from a job entry faked in app_state `library_script_jobs`.

Run from chauffeur/:  python tests/test_library_scripts_live.py   (LIBRARY_SHOTS=<dir> for screenshots)
"""
import atexit
import copy
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = tempfile.mkdtemp(prefix='chauffeur_library_scripts_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage  # noqa: E402

TOKENS = {}
SHOTS = os.environ.get('LIBRARY_SHOTS')
PIANO, DRUMS = 'lib-piano', 'lib-drums'
FOUND, SONGS = 'ph-found', 'ph-songs'
SCALES, CHORDS, TWINKLE, BEAT = 'ls-scales', 'ls-chords', 'ls-twinkle', 'ls-beat'
_BASELINE = {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}
_SHAPE = {'sessions_per_week': 3, 'minutes': 30, 'preferred_days': []}
STUB_SCENES = [{'type': 'say', 'text': 'Written for you, {name}.'},
               {'type': 'do', 'text': 'Play it through twice.', 'seconds': 120}]
_SERVED = {}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _library_row(lid, title, phases, lessons, minutes=30):
    return {'id': lid, 'title': title, 'created_by': 'mom', 'archived': False,
            'made_for': {'age_band': 'explorer', 'minutes': minutes, 'sessions_per_week': 3, 'assumes': 'complete beginner'},
            'source': {'origin': 'generated', 'reason': 'test'}, 'phases': phases, 'lessons': lessons}


PIANO_ROW = _library_row(PIANO, 'Learn piano', [
    {'id': FOUND, 'name': 'Foundations', 'weeks': 2, 'what': 'Hands and keys', 'steps': [], 'milestone': 'Plays a C scale hands together'},
    {'id': SONGS, 'name': 'Songs', 'weeks': 3, 'what': 'Whole tunes', 'steps': [], 'milestone': 'Plays Twinkle for the family'}], [
    {'id': SCALES, 'phase_id': FOUND, 'title': 'Scales', 'sessions': 2, 'steps': ['C major, slowly'],
     'variants': [{'label': 'Session A', 'steps': ['Right hand']}, {'label': 'Session B', 'steps': ['Left hand']}]},
    {'id': CHORDS, 'phase_id': FOUND, 'title': 'Chords', 'sessions': 1, 'steps': ['C, F and G'], 'variants': []},
    {'id': TWINKLE, 'phase_id': SONGS, 'title': 'Twinkle', 'sessions': 2, 'steps': ['The melody'], 'variants': []}])


def _slot(lesson_id, label=''):
    return {'lesson_id': lesson_id, 'variant_label': label}


def _commit(library_id, slot, data):
    token = storage.claim_library_script(library_id, slot)
    check(token, f'the fixture claims {slot}')
    check(storage.commit_library_script(library_id, slot, token, data), f'the fixture commits {slot}')


def seed():
    if TOKENS:
        return
    for m in ({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'email': 'mom@example.com', 'color_code': '#287a72'},
              {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult', 'color_code': '#285a7a'},
              {'id': 'kate', 'name': 'Kate', 'role': 'child', 'birthdate': '2017-02-01', 'color_code': '#5a7a28'}):
        storage.add_member(m)
    for who in ('mom', 'aunt', 'kate'):
        TOKENS[who] = storage.create_member_token(who)
    storage.add_project({'id': 'prj-piano', 'title': 'Piano for Kate', 'goal': 'Piano for Kate', 'done_when': 'it is a habit',
                         'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household', 'pieces': [], 'steps': []})
    storage.add_library_program(copy.deepcopy(PIANO_ROW))
    storage.add_library_program(_library_row(DRUMS, 'Learn drums', [{'id': 'ph-beat', 'name': 'Beat', 'weeks': 2, 'steps': [], 'milestone': 'Keeps time'}],
                                             [{'id': BEAT, 'phase_id': 'ph-beat', 'title': 'Quarter notes', 'sessions': 1, 'steps': ['Count four'], 'variants': []}],
                                             minutes=20))
    _commit(PIANO, _slot(SCALES, 'Session A'), {'origin': 'generated', 'minutes': 12, 'scenes': [
        {'type': 'say', 'text': 'Hello {name}, find middle C.'},
        {'type': 'do', 'text': 'Right hand, C to G, slowly.', 'seconds': 300}]})
    _commit(PIANO, _slot(SCALES, 'Session B'), {'origin': 'generated', 'attempts': 1, 'note': 'the model was busy'})
    from services import projects
    storage.add_program({'id': 'run-kate', 'member_id': 'kate', 'library_id': PIANO, 'state': 'active',
                         'shape': dict(_SHAPE), 'baseline': dict(_BASELINE), 'created_by': 'mom',
                         'progress': {'current': SCALES, 'lessons': {},
                                      'phases': {FOUND: {'weeks': 2, 'milestone_hit_at': None},
                                                 SONGS: {'weeks': 3, 'milestone_hit_at': None}}}})
    projects.adopt('program', 'run-kate', None, project_id='prj-piano')
    # An unconverted run (no library_id): it keeps the per-slot editor on its record sheet. The
    # startup library migration (an async task after boot) would convert it, so it stands down here.
    # Written past add_program's door (its schema carries neither `title` nor `phases`), the
    # way the pre-library code stored a run: test_lesson_endpoints._legacy_add's shape.
    from services import migrations
    migrations.migrate_program_library_v2499 = lambda: None
    storage.programs_table.insert({
        'id': 'run-legacy', 'member_id': 'kate', 'title': 'Learn violin', 'state': 'active', 'created_by': 'mom',
        'starting_point': '', 'sessions': [], 'progress': {}, 'source': {'origin': 'generated', 'reason': 'test'},
        'shape': {'preferred_days': [], 'slots': [], 'sessions_per_week': 3, 'minutes': 30},
        'baseline': {**_BASELINE, 'start_date': time.strftime('%Y-%m-%d')},
        'emissions': {'commitment_ids': [], 'thread_ids': [], 'event_ids': []},
        'phases': [{'id': 'ph-bow', 'name': 'Bowing', 'weeks': 4, 'what': 'Open strings',
                    'steps': ['Long bows on A'], 'milestone': 'A steady open A'}]})
    projects.adopt('program', 'run-legacy', None, project_id='prj-piano')
    storage.set_app_state('projects_adopted_rev', 1)   # the startup migration must not re-wrap the fixture


def _stub_write():
    """Write lessons and Regenerate, without a model: one fixed script, written synchronously
    through the hand-edit door, for the asked slot or every slot still lacking one."""
    from services import library, library_scripts

    def write(library_id, actor, lesson_id=None, variant_label=''):
        row = storage.get_library_program(library_id)
        if not row:
            return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
        if not library.can_edit(row, actor):
            return {'status': 'error', 'code': 403, 'message': library.EDIT_REFUSAL}
        if library_scripts.job_state(library_id):
            return {'status': 'error', 'message': library_scripts.ALREADY}
        slots = [(l['id'], lab) for l, lab in library_scripts.slots_of(row)]
        if lesson_id:
            pairs = [(lid, lab) for lid, lab in slots if lid == lesson_id and lab == (variant_label or '')]
        else:
            pairs = [(lid, lab) for lid, lab in slots if library_scripts.needs_script(library_id, _slot(lid, lab))]
            if not pairs:
                return {'status': 'ok', 'job': None}   # the real write()'s answer when nothing needs a script
        for lid, lab in pairs:
            storage.edit_library_script(library_id, _slot(lid, lab), {'origin': 'generated', 'scenes': copy.deepcopy(STUB_SCENES), 'minutes': 3})
        WRITES.append((library_id, lesson_id, variant_label))
        return {'status': 'ok', 'job': {'job_id': 'stub', 'done': len(pairs), 'total': len(pairs)}}
    library_scripts.write = write


WRITES = []


def serve():
    if 'h' in _SERVED:
        return _SERVED['h']
    from live_app import live_app
    served = live_app(seed)
    if served is not None:
        storage.update_settings({'auth_enforce': True, 'missions_enabled': True, 'programs_enabled': True,
                                 'program_lessons_enabled': True})
        _stub_write()
    _SERVED['h'] = served
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


def shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name + '.png'), full_page=True)


def shot_el(locator, name):
    """The element itself: these pages scroll inside a container, so a full-page shot clips them."""
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        locator.screenshot(path=os.path.join(SHOTS, name + '.png'))


def _wait(cond, msg, tries=60):
    for _ in range(tries):
        value = cond()
        if value:
            return value
        time.sleep(0.25)
    raise AssertionError(msg)


def _library(page, served, who, query=''):
    admin(page, served, who)
    page.goto(served.url('library' + query), wait_until='load')
    page.wait_for_selector('[data-library-card]', timeout=20000)


def _line(page, lesson_id, label=''):
    return page.locator(f'[data-library-lesson][data-lesson-id="{lesson_id}"] [data-lesson-script][data-variant="{label}"]')


def _chip(page, lesson_id, label=''):
    return _line(page, lesson_id, label).locator('[data-script-chip]').inner_text().strip()


def _editor(page, lesson_id, label=''):
    return page.locator(f'[data-library-lesson][data-lesson-id="{lesson_id}"] [data-script-editor][data-variant="{label}"]')


def _confirm_text(page):
    page.locator('#cc-confirm-modal').wait_for(state='visible', timeout=10000)
    return page.locator('#cc-confirm-modal').inner_text()


def _fake_job(library_id, done, total, lesson_id):
    jobs = storage.get_app_state('library_script_jobs') or {}
    jobs[library_id] = {'job_id': 'fake-job', 'started_at': time.time(), 'last_progress_at': time.time(),
                        'total': total, 'done': done, 'failed': 0, 'lesson_id': lesson_id, 'variant_label': ''}
    storage.set_app_state('library_script_jobs', jobs)


def _clear_jobs():
    storage.set_app_state('library_script_jobs', {})


# 1 -------------------------------------------------------------------------
def scenario_each_lesson_row_says_where_its_script_stands():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        _library(page, served, 'mom', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
        check(_chip(page, SCALES, 'Session A') == 'ready · about 12 min', f"a ready script: {_chip(page, SCALES, 'Session A')}")
        check(_chip(page, SCALES, 'Session B') == 'failed · the model was busy', f"a failed one: {_chip(page, SCALES, 'Session B')}")
        check(_chip(page, CHORDS) == 'no script yet', f"none yet: {_chip(page, CHORDS)}")
        check(page.locator(f'[data-lesson-id="{SCALES}"] [data-lesson-script]').count() == 2, "one line per rotation label")
        lines = page.locator('[data-library-detail] [data-lesson-script]')
        check(lines.count() == 4, f"four slots in Learn piano, got {lines.count()}")
        for i in range(lines.count()):
            row = lines.nth(i)
            check(row.locator('[data-script-play]').count() == 1, "Play on every line")
            check(row.locator('[data-script-edit]').count() == 1 and row.locator('[data-script-regenerate]').count() == 1,
                  "Edit and Regenerate for the program's maker")
        shot(page, 'scripts-admin-dark')
        page.set_viewport_size({'width': 390, 'height': 844})
        shot_el(page.locator('[data-library-detail]'), 'scripts-admin-phone-width-dark')
        page.set_viewport_size({'width': 1400, 'height': 1000})
        # Regenerate asks first, then writes this one lesson (the stub writes at once).
        _line(page, CHORDS).locator('[data-script-regenerate]').click()
        text = _confirm_text(page)
        check('Rewrite this lesson?' in text and 'keeps the plain steps' in text, f"Regenerate asks first: {text}")
        page.locator('#cc-confirm-cancel-btn').click()
        check(not WRITES, "Cancel writes nothing")
        _line(page, CHORDS).locator('[data-script-regenerate]').click()
        _confirm_text(page)
        page.locator('#cc-confirm-execute-btn').click()
        _wait(lambda: WRITES and WRITES[-1] == (PIANO, CHORDS, ''), "Regenerate starts the write for that lesson only")
        page.wait_for_function(f"""() => {{
            const el = document.querySelector('[data-lesson-id="{CHORDS}"] [data-lesson-script] [data-script-chip]');
            return el && el.innerText.startsWith('ready');
        }}""", timeout=10000)
        check(_line(page, CHORDS).locator('[data-script-edited]').is_visible(), "the stub wrote through the hand-edit door")
        # A hand-edited script says its edit goes away.
        _line(page, CHORDS).locator('[data-script-regenerate]').click()
        text = _confirm_text(page)
        check('hand-edited' in text and 'Your edit goes away' in text, f"a hand edit is named: {text}")
        page.locator('#cc-confirm-cancel-btn').click()
        check(served.errors() == [], f"no page errors: {served.errors()}")
    with served.browser() as page:
        _library(page, served, 'aunt', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
        check(page.locator('[data-script-play]').count() == 4, "Play for everyone")
        check(page.locator('[data-script-edit], [data-script-regenerate], [data-library-write]').count() == 0,
              "no Edit, Regenerate or Write lessons for someone who may not change the program")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 2 -------------------------------------------------------------------------
def scenario_the_card_writes_lessons_and_says_how_far_it_has_got():
    served = serve()
    if served is None:
        return
    _fake_job(PIANO, 2, 4, TWINKLE)
    try:
        with served.browser() as page:
            _library(page, served, 'mom')
            piano = page.locator(f'[data-library-list] [data-library-card][data-library-id="{PIANO}"] [data-library-write]')
            drums = page.locator(f'[data-library-list] [data-library-card][data-library-id="{DRUMS}"] [data-library-write]')
            check(piano.inner_text().strip() == 'Writing lessons · 2 of 4', f"the job's progress on the card: {piano.inner_text()}")
            check(piano.is_disabled(), "and Write lessons waits while it runs")
            check(drums.inner_text().strip() == 'Write lessons' and drums.is_enabled(), "an idle program offers Write lessons")
            shot(page, 'scripts-card-writing-dark')
            page.locator(f'[data-library-list] [data-library-card][data-library-id="{PIANO}"] [data-library-view]').click()
            page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
            check(_chip(page, TWINKLE) == 'writing…', f"the lesson being written: {_chip(page, TWINKLE)}")
            check(_line(page, TWINKLE).locator('[data-script-regenerate]').is_disabled(), "Regenerate waits for the job")
            # The page reads the library again every 10 seconds while a job shows, and stops after.
            _clear_jobs()
            page.wait_for_function(f"""() => {{
                const el = document.querySelector('[data-lesson-id="{TWINKLE}"] [data-lesson-script] [data-script-chip]');
                return el && el.innerText === 'no script yet';
            }}""", timeout=15000)
            check(page.locator('[data-library-detail] [data-library-write]').inner_text().strip() == 'Write lessons',
                  "the card's button comes back once the job is done")
            page.locator('[data-library-back]').click()
            page.locator(f'[data-library-list] [data-library-card][data-library-id="{DRUMS}"] [data-library-write]').click()
            _wait(lambda: WRITES and WRITES[-1] == (DRUMS, None, ''), "Write lessons starts the program's job")
            check((storage.get_library_script(DRUMS, _slot(BEAT)) or {}).get('scenes'), "and its lesson has a script")
            page.locator(f'[data-library-list] [data-library-card][data-library-id="{DRUMS}"] [data-library-view]').click()
            page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
            check(_chip(page, BEAT) == 'ready · about 3 min', f"the chip reads ready: {_chip(page, BEAT)}")
            check(served.errors() == [], f"no page errors: {served.errors()}")
        with served.browser() as page:
            _library(page, served, 'aunt')
            check(page.locator('[data-library-write]').count() == 0, "Write lessons is for the program's maker or a parent")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        _clear_jobs()


# 3 -------------------------------------------------------------------------
def scenario_the_editor_writes_a_teach_beat_and_honours_the_length():
    served = serve()
    if served is None:
        return
    storage.delete_library_script(PIANO, _slot(TWINKLE))
    with served.browser() as page:
        _library(page, served, 'mom', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
        _line(page, TWINKLE).locator('[data-script-edit]').click()
        ed = _editor(page, TWINKLE)
        ed.wait_for(state='visible', timeout=10000)
        ed.get_by_text('No script yet. Add a beat, or Regenerate to have the app write one.').wait_for(state='visible', timeout=10000)
        options = ed.locator('select[name="scene_add_type"] option').all_inner_texts()
        check(options[:3] == ['Say', 'Do', 'Teach'] and 'Check' in options and 'Wait' in options, f"Add offers every type: {options}")
        ed.locator('select[name="scene_add_type"]').select_option('teach')
        ed.locator('[data-script-add]').click()
        row = ed.locator('[data-script-row][data-type="teach"]')
        row.locator('input[name="teach_title"]').fill('Middle C')
        row.locator('textarea[name="teach_text"]').fill('C sits just left of the two black keys. Find the pair, step left.')
        row.locator('textarea[name="teach_examples"]').fill('Play C, rest, C\nDó | pt-BR')
        row.locator('input[name="teach_speak"]').fill('Find the two black keys. Step left of them.')
        shot_el(ed, 'scripts-editor-teach-dark')
        ed.locator('[data-script-save]').click()
        saved = _wait(lambda: (storage.get_library_script(PIANO, _slot(TWINKLE)) or {}).get('scenes'), "the teach beat saved")
        check(saved == [{'type': 'teach', 'text': 'C sits just left of the two black keys. Find the pair, step left.', 'title': 'Middle C',
                         'examples': [{'text': 'Play C, rest, C'}, {'text': 'Dó', 'speak_lang': 'pt-BR'}],
                         'speak': 'Find the two black keys. Step left of them.'}], f"every field, the language tag split off: {saved}")
        page.reload(wait_until='load')
        page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=20000)
        _line(page, TWINKLE).locator('[data-script-edit]').click()
        row = _editor(page, TWINKLE).locator('[data-script-row][data-type="teach"]')
        row.wait_for(state='visible', timeout=10000)
        check(row.locator('input[name="teach_title"]').input_value() == 'Middle C', "the title comes back")
        check(row.locator('textarea[name="teach_text"]').input_value().startswith('C sits just left'), "the text comes back")
        check(row.locator('textarea[name="teach_examples"]').input_value() == 'Play C, rest, C\nDó | pt-BR', "the examples come back, tag and all")
        check(row.locator('input[name="teach_speak"]').input_value() == 'Find the two black keys. Step left of them.', "the speak comes back")
        # A 30-minute program holds 30 beats: the thirteenth is accepted, the thirty-first refused.
        ed = _editor(page, TWINKLE)
        ed.locator('select[name="scene_add_type"]').select_option('say')
        for n in range(2, 31):
            ed.locator('[data-script-add]').click()
            if n == 13:
                check(ed.locator('[data-script-row]').count() == 13, "a thirteenth beat is accepted")
                check(not page.locator('#cc-alert-modal').is_visible(), "with nothing refused")
        check(ed.locator('[data-script-row]').count() == 30, "thirty beats on a 30-minute program")
        says = ed.locator('[data-script-row][data-type="say"] input[name="scene_text"]')
        for i in range(says.count()):
            says.nth(i).fill(f'Beat {i + 2}.')
        ed.locator('[data-script-add]').click()
        page.locator('#cc-alert-modal').wait_for(state='visible', timeout=5000)
        said = page.locator('#cc-alert-message').inner_text()
        check(said == '30 beats is the most a 30-minute lesson holds.', f"the thirty-first is refused in words: {said}")
        check(ed.locator('[data-script-row]').count() == 30, "and not added")
        page.evaluate('closeGlobalAlert()')
        # Move the teach beat to the end and save: the server keeps all thirty, in order.
        ed.locator('[data-script-row]').first.locator('[data-script-row-down]').click()
        ed.locator('[data-script-save]').click()
        saved = _wait(lambda: (lambda s: s if len(s) == 30 else None)((storage.get_library_script(PIANO, _slot(TWINKLE)) or {}).get('scenes') or []),
                      "thirty beats saved")
        check(saved[0] == {'type': 'say', 'text': 'Beat 2.'} and saved[1]['type'] == 'teach', f"reordered: {saved[:2]}")
        check(storage.get_library_script(PIANO, _slot(TWINKLE))['edited'], "a hand edit is marked")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 3b (Task 5 review) ----------------------------------------------------------
def scenario_a_failed_read_can_never_become_a_save():
    """A transient failure reading a script is not an empty script: the editor says so with
    Retry, draws no rows, keeps Add and Save off, and even a direct call to addScriptRow and
    saveScript sends no PUT; the stored script is untouched. Retry reads it and editing opens."""
    served = serve()
    if served is None:
        return
    slot = _slot(SCALES, 'Session A')
    before = storage.get_library_script(PIANO, slot)['scenes']
    with served.browser() as page:
        _library(page, served, 'mom', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
        puts = []
        page.on('request', lambda r: puts.append(r.url) if r.method == 'PUT' and '/script' in r.url else None)

        def outage(route):
            if route.request.method == 'GET':
                route.fulfill(status=500, content_type='application/json', body='{"detail": "test outage"}')
            else:
                route.continue_()
        target = lambda url: f'/lessons/{SCALES}/script' in url and 'fill=1' not in url  # noqa: E731
        page.route(target, outage)
        _line(page, SCALES, 'Session A').locator('[data-script-edit]').click()
        ed = _editor(page, SCALES, 'Session A')
        failed = ed.locator('[data-script-load-failed]')
        failed.wait_for(state='visible', timeout=10000)
        check('test outage' in failed.inner_text() and failed.locator('[data-script-retry]').count() == 1,
              f"the failure is said, with Retry: {failed.inner_text()}")
        check(ed.locator('[data-script-row]').count() == 0, "no rows from a read that failed")
        check(not ed.get_by_text('No script yet').is_visible(), "and it is not mistaken for an empty script")
        check(ed.locator('[data-script-add]').is_disabled() and ed.locator('[data-script-save]').is_disabled(),
              "Add and Save stay off")
        page.evaluate("""async ([lid, lesson, lab]) => {
            const d = Alpine.$data(document.querySelector('[data-library-page]'));
            const lp = d.programs.find(p => p.id === lid);
            const l = lp.lessons.find(x => x.id === lesson);
            d.addScriptRow(lp, l, lab);
            await d.saveScript(lp, l, lab);
        }""", [PIANO, SCALES, 'Session A'])
        page.wait_for_timeout(500)
        check(puts == [], f"a failed read can never lead to a PUT: {puts}")
        check(ed.locator('[data-script-row]').count() == 0, "not even a forced Add draws a row")
        check(storage.get_library_script(PIANO, slot)['scenes'] == before, "the stored script is untouched")
        shot_el(ed, 'scripts-editor-read-failed-dark')
        page.unroute(target, outage)
        failed.locator('[data-script-retry]').click()
        ed.locator('[data-script-row]').first.wait_for(state='visible', timeout=10000)
        check(ed.locator('[data-script-row]').count() == len(before) and not failed.is_visible(), "Retry reads the stored script")
        check(ed.locator('[data-script-save]').is_enabled() and ed.locator('[data-script-add]').is_enabled(), "and editing opens")
        refused = 'the server responded with a status of 500'
        others = [e for e in served.errors() if refused not in e]
        check(others == [], f"no page errors beyond the faked outage: {served.errors()}")


# 4 -------------------------------------------------------------------------
def scenario_play_previews_the_script_filled_for_the_viewer():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.set_viewport_size({'width': 390, 'height': 844})
        _library(page, served, 'mom', '?id=' + PIANO)
        page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
        _line(page, SCALES, 'Session A').locator('[data-script-play]').click()
        player = page.locator('[x-data="lessonPlayer()"]')
        player.wait_for(state='visible', timeout=10000)
        page.wait_for_function("() => document.querySelector('[x-data=\"lessonPlayer()\"]').innerText.includes('Hello Mom, find middle C.')",
                               timeout=10000)
        text = player.inner_text()
        check('{name}' not in text, f"{{name}} is filled: {text[:300]}")
        check('Just a look' in text and 'Learn piano' in text and 'Session A' in text, f"a preview of this lesson: {text[:300]}")
        shot(page, 'scripts-play-phone-dark')
        player.get_by_role('button', name='Close session', exact=True).click()
        player.wait_for(state='hidden', timeout=5000)
        check(page.locator('[x-data="lessonPlayer()"]').count() == 1, "one player on the library page")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 5 -------------------------------------------------------------------------
def scenario_a_library_run_points_at_the_library_and_a_legacy_run_keeps_its_editor():
    served = serve()
    if served is None:
        return
    check(not storage.get_program('run-legacy').get('library_id'), "the legacy fixture stayed unconverted")
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.wait_for_selector('[data-project-detail]', timeout=20000)
        page.locator('[data-piece-open="program:run-kate"]').click()
        sheet = page.locator('[data-record-sheet]')
        # The monitoring sheet (programs spec §5.1): the header's "in the library ›" is the
        # run's one way to its library program, where the scripts live.
        link = sheet.locator('[data-library-link]:visible')
        link.wait_for(state='visible', timeout=15000)
        check(link.count() == 1 and link.inner_text().strip() == 'in the library ›'
              and sheet.locator('[data-monitor]').inner_text().startswith('Learn piano'),
              f"one link to the library: {link.all_inner_texts()}")
        check(link.evaluate('el => el.tagName') == 'BUTTON', "a button, not an anchor")
        body = sheet.inner_text()
        check('▸ edit' not in body and 'Add a beat' not in body, f"no per-run editor for a library run: {body[:600]}")
        shot(page, 'scripts-run-sheet-dark')
        link.click()
        page.wait_for_url('**/library?id=' + PIANO, timeout=15000)
        page.wait_for_selector('[data-library-detail]', timeout=15000)
        check(served.errors() == [], f"no page errors: {served.errors()}")
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.wait_for_selector('[data-project-detail]', timeout=20000)
        page.locator('[data-piece-open="program:run-legacy"]').click()
        sheet = page.locator('[data-record-sheet]')
        page.wait_for_function("() => (document.querySelector('[data-record-sheet]') || {}).innerText.includes('▸ edit')", timeout=15000)
        check(sheet.locator('[data-scripts-in-library]').count() == 0, "an unconverted run has no library link")
        sheet.get_by_text('▸ edit').first.click()
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Add a beat')", timeout=10000)
        shot(page, 'scripts-legacy-editor-dark')
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 6 -------------------------------------------------------------------------
def scenario_the_drawer_picks_the_writing_model():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('work?tab=projects#lessons'), wait_until='load')
        page.wait_for_selector('[data-settings-for~="projects"][data-open="true"]', timeout=15000)
        lessons = page.locator('[data-settings-for~="projects"] section#lessons')
        select = lessons.locator('select[x-model="s.lesson_pool"]')
        check(select.count() == 1, "the Lessons tab has the writing-model select")
        page.wait_for_function("() => document.querySelector('select[x-model=\"s.lesson_pool\"]').value === 'heavy'", timeout=10000)
        check(select.locator('option').all_inner_texts() == ['Best available', 'Low cost'], "two pools, said plainly")
        text = lessons.inner_text()
        check('Write lessons now' not in text and 'Wrote ' not in text, f"no Write lessons now and no report: {text}")
        shot(page, 'scripts-drawer-dark')
        select.select_option('background')
        _wait(lambda: storage.get_settings().get('lesson_pool') == 'background', "the pool saves")
        page.reload(wait_until='load')
        page.wait_for_selector('[data-settings-for~="projects"][data-open="true"]', timeout=15000)
        page.wait_for_function("() => document.querySelector('select[x-model=\"s.lesson_pool\"]').value === 'background'", timeout=10000)
        page.locator('select[x-model="s.lesson_pool"]').select_option('heavy')
        _wait(lambda: storage.get_settings().get('lesson_pool') == 'heavy', "and back")
        check(served.errors() == [], f"no page errors: {served.errors()}")


# 7 + 8 ---------------------------------------------------------------------
def scenario_the_phone_shows_chips_and_play_light_and_dark():
    served = serve()
    if served is None:
        return
    _fake_job(PIANO, 2, 4, TWINKLE)
    try:
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
                card = home.locator(f'[data-library-card][data-library-id="{PIANO}"]')
                check(card.locator('[data-library-writing]').inner_text().strip() == 'Writing lessons · 2 of 4',
                      f"the phone says the job is running: {card.inner_text()}")
                check(home.locator('[data-library-write]').count() == 0, "but Write lessons is the admin page's")
                shot(page, f'scripts-phone-list-{theme}')
                card.locator('[data-library-view]').click()
                page.wait_for_selector('#library-container [data-library-detail] [data-lesson-script]', timeout=10000)
                check(home.locator('[data-script-chip]').count() == 4 and home.locator('[data-script-play]').count() == 4,
                      "chips and Play on every line")
                check(home.locator('[data-script-edit], [data-script-regenerate], [data-script-editor]').count() == 0,
                      "and nothing else of the scripts on the phone")
                check(home.locator('a[href]').count() == 0, "buttons only on the phone")
                width = page.evaluate('() => [document.documentElement.scrollWidth, window.innerWidth]')
                check(width[0] <= width[1], f"no horizontal scroll ({theme}): {width}")
                box = home.locator('[data-library-detail] [data-library-card]').first.bounding_box()
                check(box['x'] >= 15.5 and box['x'] + box['width'] <= 390 - 15.5, f"a 16px gutter ({theme}): {box}")
                shot(page, f'scripts-phone-detail-{theme}')
                shot_el(home.locator('[data-library-detail]'), f'scripts-phone-detail-full-{theme}')
                _line(page, SCALES, 'Session A').locator('[data-script-play]').click()
                player = page.locator('[x-data="lessonPlayer()"]')
                player.wait_for(state='visible', timeout=10000)
                page.wait_for_function("() => document.querySelector('[x-data=\"lessonPlayer()\"]').innerText.includes('Hello Mom')", timeout=10000)
                shot(page, f'scripts-phone-play-{theme}')
                check(served.errors() == [], f"no page errors ({theme}): {served.errors()}")
    finally:
        _clear_jobs()


# 9 -------------------------------------------------------------------------
FLUTE, BREATH = 'lib-flute', 'ls-breath'


def _poll_running(page):
    return page.evaluate("() => !!Alpine.$data(document.querySelector('[data-library-page]'))._poll")


def scenario_reset_clears_a_script_and_an_archived_program_keeps_its_hands_off():
    """Reset (spec §1) asks, then clears the stored script; a write with nothing
    to do (job null, or a job of total 0) never flashes "0 of 0" or polls; an
    archived program shows Play but no Edit, Regenerate, Reset or Write lessons."""
    served = serve()
    if served is None:
        return
    _clear_jobs()
    storage.edit_library_script(DRUMS, _slot(BEAT), {'origin': 'generated', 'scenes': copy.deepcopy(STUB_SCENES), 'minutes': 3})
    if not storage.get_library_program(FLUTE):
        row = _library_row(FLUTE, 'Learn flute', [{'id': 'ph-air', 'name': 'Air', 'weeks': 2, 'steps': [], 'milestone': 'A long note'}],
                           [{'id': BREATH, 'phase_id': 'ph-air', 'title': 'Long notes', 'sessions': 1, 'steps': ['Breathe low'], 'variants': []}])
        row['archived'] = True
        storage.add_library_program(row)
        storage.edit_library_script(FLUTE, _slot(BREATH), {'origin': 'generated', 'scenes': copy.deepcopy(STUB_SCENES), 'minutes': 3})
    try:
        with served.browser() as page:
            _library(page, served, 'mom')
            card = f'[data-library-list] [data-library-card][data-library-id="{DRUMS}"]'
            # Nothing left to write: the answer carries job null, the card stays as it was.
            before = len(WRITES)
            page.locator(card + ' [data-library-write]').click()
            page.wait_for_function("() => !Alpine.$data(document.querySelector('[data-library-page]')).busy", timeout=10000)
            btn = page.locator(card + ' [data-library-write]')
            check(btn.inner_text().strip() == 'Write lessons' and btn.is_enabled(), f"nothing to write leaves the card alone: {btn.inner_text()}")
            check(len(WRITES) == before, "and the stub saw nothing to write")
            check(not _poll_running(page), "and no poll starts")
            # A job of total 0 in storage reads as no job at all.
            _fake_job(DRUMS, 0, 0, '')
            page.reload(wait_until='load')
            page.wait_for_selector(card, timeout=20000)
            check(page.locator(card + ' [data-library-write]').inner_text().strip() == 'Write lessons',
                  f"a total-0 job never reads 0 of 0: {page.locator(card).inner_text()}")
            check('0 of 0' not in page.locator('[data-library-list]').inner_text(), "nowhere on the list")
            check(not _poll_running(page), "and starts no poll")
            _clear_jobs()
            # Reset: asks, Keep it keeps, Clear clears and the editor reads the empty slot again.
            page.locator(card + ' [data-library-view]').click()
            page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
            _line(page, BEAT).locator('[data-script-edit]').click()
            ed = _editor(page, BEAT)
            ed.locator('[data-script-row]').first.wait_for(state='visible', timeout=10000)
            reset = ed.locator('[data-script-reset]')
            check(reset.is_visible() and reset.is_enabled(), "Reset is offered once the stored script is read")
            shot_el(ed, 'scripts-editor-reset-dark')
            reset.click()
            text = _confirm_text(page)
            check('Clear this script?' in text and 'nightly retry' in text, f"Reset asks first: {text}")
            page.locator('#cc-confirm-cancel-btn').click()
            time.sleep(0.5)
            check((storage.get_library_script(DRUMS, _slot(BEAT)) or {}).get('scenes'), "Keep it keeps the script")
            reset.click()
            _confirm_text(page)
            page.locator('#cc-confirm-execute-btn').click()
            _wait(lambda: not (storage.get_library_script(DRUMS, _slot(BEAT)) or {}).get('scenes'), "Clear removes the stored script")
            page.wait_for_function(f"""() => {{
                const el = document.querySelector('[data-lesson-id="{BEAT}"] [data-lesson-script] [data-script-chip]');
                return el && el.innerText === 'no script yet';
            }}""", timeout=10000)
            _wait(lambda: ed.locator('[data-script-row]').count() == 0 and 'No script yet' in ed.inner_text(), "the editor reads the empty slot")
            check(not ed.locator('[data-script-reset]').is_visible(), "and Reset goes with nothing left to clear")
            # An archived program: Play, nothing that writes.
            page.locator('[data-library-back]').click()
            flute = page.locator(f'[data-library-list] [data-library-card][data-library-id="{FLUTE}"]')
            flute.wait_for(state='visible', timeout=10000)
            check(flute.locator('[data-library-write]').count() == 0, "no Write lessons on an archived card")
            flute.locator('[data-library-view]').click()
            page.wait_for_selector('[data-library-detail] [data-lesson-script]', timeout=10000)
            arch = page.locator('[data-library-detail]')
            check(arch.locator('[data-script-play]').count() == 1, "Play stays on an archived program")
            check(arch.locator('[data-script-edit], [data-script-regenerate], [data-script-reset], [data-script-editor], [data-library-write]').count() == 0,
                  "and no Edit, Regenerate, Reset or Write lessons")
            shot_el(arch, 'scripts-archived-dark')
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        _clear_jobs()


SCENARIOS = [scenario_each_lesson_row_says_where_its_script_stands,
             scenario_the_card_writes_lessons_and_says_how_far_it_has_got,
             scenario_the_editor_writes_a_teach_beat_and_honours_the_length,
             scenario_a_failed_read_can_never_become_a_save,
             scenario_play_previews_the_script_filled_for_the_viewer,
             scenario_a_library_run_points_at_the_library_and_a_legacy_run_keeps_its_editor,
             scenario_the_drawer_picks_the_writing_model,
             scenario_the_phone_shows_chips_and_play_light_and_dark,
             scenario_reset_clears_a_script_and_an_archived_program_keeps_its_hands_off]

if __name__ == '__main__':
    import traceback
    only = sys.argv[1:]
    failed = 0
    for fn in SCENARIOS:
        if only and not any(o in fn.__name__ for o in only):
            continue
        try:
            fn()
            print(f'PASS {fn.__name__}')
        except Exception:
            failed += 1
            print(f'FAIL {fn.__name__}')
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
