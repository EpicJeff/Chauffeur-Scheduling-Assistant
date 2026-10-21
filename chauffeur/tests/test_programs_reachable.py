"""A program surface a driver cannot reach is a program surface nobody has.

Every part of the programs arc in the PWA -- tonight's session, the steps,
"Log a session", and the "did it happen?" ask -- was mounted inside
`renderMyDay` and nowhere else. My Day is a PASSENGER tab: `applyRoleTabs`
hides it outright for anyone who drives. So the household member most likely
to propose a program for themselves was the one member with no surface at all
for it, and the ask that was deliberately moved off a watcher DM and onto
"the owner's own card" landed on a card its owner could not open.

Nothing caught it because every piece worked. The endpoints answered, the
templates rendered, the scenarios passed -- the feature was simply hung on a
door half the house does not have.

So this asserts placement rather than behaviour, and says so: the program
surfaces must have a mount that is not `renderMyDay`, and the heartbeat that
draws them must run. It also syntax-checks every inline script in the two
templates that carry this arc, which is what a scripted edit to a 20,000-line
template most plausibly breaks.

The second half is the never-drop guard for the programs brief-and-course
slice (spec 2026-10-20-programs-brief-and-course-design.md, plan Task 9).
That slice moved nearly every program verb one tap deeper: the run sheet
became a monitoring sheet with one ⋯, the library program became a course
page with the editor behind ⋯ › Edit by hand, and Add a piece's program form
became the setup sheet. Each surface's inventory is written out below, and a
live scenario drives the real page (Playwright, with the test_library_live
fixture and helpers): it reads every verb off the page and, wherever the tap
is safe to take, takes it and backs out of the answer it opens. A verb that
drops out of a menu or a sheet goes red here, by name.

Run from chauffeur/:  python tests/test_programs_reachable.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# The live fixture points storage at its own temp data dir on import, before
# anything here imports main, so the source half and the live half share one.
import test_library_live as L  # noqa: E402
from services import storage  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TPL = os.path.join(HERE, 'templates')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _app():
    with open(os.path.join(TPL, 'app.html'), encoding='utf-8') as f:
        return f.read()


def _body(src: str, name: str) -> str:
    """The text of one function, from its declaration to the next one at the
    same indent. Crude on purpose -- it only has to be good enough to answer
    "is this call inside that function"."""
    m = re.search(r'\n(\s*)(?:async )?function ' + re.escape(name) + r'\s*\(',
                  src)
    check(m, f"{name}() must exist")
    indent = m.group(1)
    rest = src[m.end():]
    nxt = re.search(r'\n' + indent + r'(?:async )?function ', rest)
    return rest[:nxt.start()] if nxt else rest


def scenario_the_program_surfaces_have_a_driver_side_mount():
    """The rule, stated as the thing that was false: the blocks must be
    reachable from something other than the passenger tab."""
    src = _app()
    check('id="today-container"' in src,
          "the drives view needs somewhere to draw today")
    for fn in ('buildPracticeParts', 'refreshPracticeSection',
               'applyPracticeVisibility', 'refreshTodaySurfaces'):
        check(re.search(r'(?:async )?function ' + fn + r'\s*\(', src),
              f"{fn}() must exist")
    refresh = _body(src, 'refreshPracticeSection')
    check('buildPracticeParts(' in refresh,
          "the drives mount must build the same blocks My Day builds")
    check('today-content' in refresh,
          "and write them somewhere the drives view shows")


def scenario_my_day_and_the_drives_view_share_one_builder():
    """Two copies of "what is tonight's session" is how they start
    disagreeing about it."""
    src = _app()
    myday = _body(src, 'renderMyDay')
    check('buildPracticeParts(' in myday,
          "My Day must use the shared builder, not its own copy")
    check('renderPracticeNow(practiceNow(' not in myday,
          "and must not rebuild the block inline beside it")


def scenario_a_due_session_is_drawn_without_being_asked_for():
    """A window becoming due redrew nothing: the five-minute timer repaints
    the day panes and the foreground handler refetches the schedule, and
    neither touched these. An app left open showed the state it had when the
    phone went to sleep."""
    src = _app()
    tick = re.search(r'setInterval\(\(\) => \{(.*?)\}, 300000\);', src, re.S)
    check(tick, "the five-minute heartbeat must still exist")
    check('refreshTodaySurfaces()' in tick.group(1),
          "and must redraw today's surfaces, not only the schedule")
    viz = re.search(r"addEventListener\('visibilitychange', \(\) => \{"
                    r"\s*if \(document\.hidden\) return;(.*?)\}\);", src, re.S)
    check(viz and 'refreshTodaySurfaces()' in viz.group(1),
          "and coming back to the foreground must too")


def scenario_logging_a_session_redraws_whichever_surface_it_was_tapped_on():
    """Logging moves the ladder and clears the ask, so the surface has to
    repaint -- and it must not be the passenger one by name."""
    src = _app()
    for fn in ('askProgramSession', 'addProgramSession', 'markProgramMilestone'):
        body = _body(src, fn)
        check('afterProgramWrite()' in body,
              f"{fn}() must repaint through the shared path")
        check("currentView === 'myday'" not in body,
              f"{fn}() must not name the passenger tab as the only surface")


def scenario_every_inline_script_still_parses():
    """A scripted edit to a 20,000-line template breaks syntax before it
    breaks logic. Skips rather than fails where node is unavailable."""
    node = shutil.which('node')
    if not node:
        print("  (node unavailable -- syntax check skipped)")
        return
    import main  # the REAL Jinja environment, filters and globals and all

    class _Q(dict):
        def get(self, k, d=None):
            return dict.get(self, k, d)

    class _R:
        query_params = _Q()
        url = type('U', (), {'path': '/'})()
        headers = {}

    tmp = tempfile.mkdtemp()
    for name in ('app.html', 'components/programs_page.html'):
        html = main.templates.env.get_template(name).render(request=_R())
        blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>',
                            html, re.S)
        check(blocks, f"{name} must carry inline script to check")
        for i, block in enumerate(blocks):
            if not block.strip():
                continue
            path = os.path.join(tmp, f'{os.path.basename(name)}.{i}.js')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(block)
            res = subprocess.run([node, '--check', path],
                                 capture_output=True, text=True)
            check(res.returncode == 0,
                  f"{name} block {i} does not parse:\n{res.stderr[:400]}")


def scenario_the_drives_day_carries_what_my_day_carries():
    """The other blocks with the same hole. `renderRequests` runs for
    everyone by its own comment -- "both directions, for everyone" -- and
    drew on the passenger tab only, so an adult taking a drive from their
    partner asked a question the partner could not see. The status banner
    names its own victim: "how a kid (or the co-parent) sees what today is",
    and the co-parent is usually the one driving.

    Routines stay out on purpose: they are a child's, and a driver having no
    routine lane is not a hole.
    """
    src = _app()
    build = _body(src, 'buildPracticeParts')
    for call, why in (
            ('renderRequests(', "the asks have to reach a driver"),
            ('renderStatusBanner(', "and so does what today is"),
            ('renderDueSoonSection(', "and the deadline list, empty or not")):
        check(call in build, f"{call}) missing: {why}")
    check('renderRoutineSection(' not in build,
          "routines are a child's and stay on the child's tab")
    stack = _body(src, 'practiceStackHtml')
    for part in ('status', 'requests', 'dueSoon'):
        check(part in stack, f"the drives stack must draw {part}")
    # Programs still reach a driver -- in the drive list at their own time
    # and after it, not stacked above every drive (2026-09-26, "it is my
    # day, not my programs and my drives"; tests/test_myday_timeline_live.py
    # drives it in a browser).
    timeline = _body(src, 'buildTimeline')
    check('myDayProgramItems(' in timeline,
          "the driver's drive list must thread the program rows in")
    for part in ('now', 'programs'):
        check(f'p.{part}' not in stack,
              f"and the stack must not draw {part} above the drives as well")


def scenario_a_session_can_be_opened_and_finished():
    """The tap target the arc never had, and the one action that matters."""
    src = _app()
    check(re.search(r'function openSessionSheet\s*\(', src),
          "a session has to be openable")
    sheet = _body(src, 'openSessionSheet')
    for bit, why in (
            ('unit_title', 'which lesson it is'),
            ('unit_url', 'the link for a cited plan'),
            ('unit_body', "the words for one the app wrote"),
            ('session_label', 'which session of the rotation'),
            ('askProgramSession(', 'and a way to say it happened')):
        check(bit in sheet, f"the sheet must carry {why}")
    check('w.date' in sheet,
          "logging files under the evening it was about, not the tap")
    # Every surface that draws a window has to be able to open one.
    fam = _body(src, 'renderFamilyCard')
    check('openSessionSheet(' in fam,
          "the family tab's practice card was the one row that opened nothing")
    card = _body(src, 'renderProgramCard')
    check('openSessionSheet(' in card,
          "and the program card lists the sessions ahead as tap targets")


def scenario_the_tab_is_named_for_what_it_holds():
    """It stopped being only the drives the moment it carried the family's
    status, the asks, and tonight's practice."""
    src = _app()
    drives = re.search(r'id="tab-drives".*?</button>', src, re.S)
    check(drives, "the drives tab must exist")
    check('>My Day<' in drives.group(0),
          "the drives tab is My Day for somebody who drives")


def scenario_the_day_is_one_page_with_a_jump_row():
    """Three stacked boxes, each with a fixed slice of the screen and its own
    scrollbar, meant the day arrived pre-divided: intake in one letterbox,
    Argyle in a second, the agenda in whatever was left -- which on a busy day
    was nothing, and the events the tab exists for sat below the fold of a box
    nobody thinks to scroll. The House tab had already solved this shape.
    """
    src = _app()
    check('id="screen-anchors"' in src, "the jump row needs a home")
    for gone in ('max-h-[45%] border-b border-gray-800 bg-gray-950',
                 'max-h-[35%] border-b border-gray-800 bg-gray-950',
                 'max-h-[60%] border-b border-gray-800 bg-gray-950'):
        check(gone not in src,
              f"no section may keep a fixed slice of the screen: {gone}")
    sections = _body(src, 'paneSectionsHtml')
    for wrapper in ('proposals-container', 'mind-container', 'today-container'):
        check(wrapper in sections,
              f"{wrapper} is a section inside the pane now")
    anchors = _body(src, 'renderScheduleAnchors')
    check("parts.length > 1" in anchors,
          "one section is not a story -- the row draws at two or more, the "
          "same rule renderHouseAnchors uses")
    for target in ('today-container', 'proposals-container', 'mind-container',
                   'pane-events', 'pane-drives'):
        check(target in anchors, f"{target} must be reachable from the row")


def scenario_a_rebuilt_pane_gets_its_sections_back():
    """Panes are replaced wholesale, which throws away every node the section
    renderers wrote into. `renderProposals` builds real nodes with handlers
    bound on them, so a cached HTML string could not be replayed -- the
    renderers have to run again."""
    src = _app()
    build = _body(src, 'buildTimeline')
    check('paintPaneSections()' in build,
          "rebuilding the panes must repaint what they contain")
    paint = _body(src, 'paintPaneSections')
    for fn in ('renderProposals()', 'renderMind()', 'refreshPracticeSection(',
               'renderScheduleAnchors()'):
        check(fn in paint, f"{fn} must run after a rebuild")


def scenario_last_nights_session_is_not_the_next_one():
    """"Coming up" filtered on `!w.logged` alone, which is a different
    question: a session nobody ever answered stays unlogged forever, so last
    night's nine o'clock sat at the top of the list as the next thing to do
    and stayed there. A window that has ENDED is behind you whatever the log
    says -- chasing an unanswered one is the "did it happen?" ask's job, and
    it has its own row."""
    src = _app()
    check(re.search(r'function upcomingWindows\s*\(', src),
          "one helper decides what is still ahead")
    up = _body(src, 'upcomingWindows')
    check('time_end' in up,
          "a window that has already ended is not coming up")
    card = _body(src, 'renderProgramCard')
    check('upcomingWindows(' in card and 'w.date + w.time_start' not in card,
          "the card must ask the helper rather than re-filtering on logged")
    label = _body(src, 'sessionDateLabel')
    check('Yesterday' in label,
          "and a day already gone must not read as a weekday still to come")
    anchor = _body(src, 'reanchorIfDayChanged')
    check('practiceBuiltAt = 0' in anchor,
          "a day that turned over invalidates a fetch made for the old one")


def scenario_a_child_who_cannot_tap_still_has_a_surface():
    """The person a program belongs to is not always the person who can
    operate the app. A parent's day has to carry a small child's program, and
    the session sheet has to let them finish it -- the server always allowed
    that and only the button disagreed."""
    src = _app()
    fetch = _body(src, 'fetchMyPrograms')
    check('owner_practices_alone' in fetch,
          "a parent's day must include programs whose owner cannot run one alone")
    check('own_account' not in fetch,
          "and must not ask about accounts -- a child with a PIN on a shared "
          "iPad has no account and can still see their own session")
    check("['parent', 'adult'].includes(currentMemberRole())" in fetch,
          "and only a grown-up's day does")
    sheet = _body(src, 'openSessionSheet')
    check('grown' in sheet and 'mine || grown' in sheet,
          "the Done button must not be owner-only")
    card = _body(src, 'renderProgramCard')
    check('member_name' in card,
          "a card that can be somebody else's has to say whose")


def scenario_a_session_can_be_started_ahead_of_its_window():
    """Free time today should let a person do tomorrow's session now. The
    sheet's Start used to be gated on the window being dated today; Done
    (saying it happened, without doing it here) stays today-or-earlier."""
    src = _app()
    sheet = _body(src, 'openSessionSheet')
    check("w.date === todayStr()" not in sheet, 'Start is no longer today-only')
    check(re.search(r"const startBtn = [^\n]*w\.date >= todayStr\(\)", sheet),
          'Start is offered for today and every window ahead')
    check(re.search(r"const canLog = [^\n]*w\.date <= todayStr\(\)", sheet),
          'Done still never claims a session that has not happened')
    check(re.search(r"const startBtn = [^\n]*!w\.logged", sheet),
          'a logged window offers no Start')


# ---------------------------------------------------------------------------
# The never-drop guard, live (programs brief-and-course spec; plan Task 9).
# Every verb a person had on the old run card, library page and program form,
# and the ones the slice added, by the surface that holds it now. Each tuple is
# the inventory its scenario reads off the real page.

RUN_MENU = ('Change the days', 'Program settings', 'Log a session', 'Start a session', 'Look again',
            'Plan without the book', 'Pause', 'Done with it', 'Drop', 'Delete')
RUN_MENU_PAUSED = ('Resume',)
RUN_BODY = ('Reached it', 'Another session on this', 'Move on', '▶ Preview', 'Remove')
PROPOSED = ('What it adds to the week', 'Not these times?', 'Approve', 'Dismiss', 'Edit', 'Look again',
            'Plan without the book')
COURSE_MENU = ('Steer in words', 'Edit by hand', 'Write lessons', 'Make a variant', 'Archive', 'Delete',
               'Start it for…')
COURSE_PRACTICE_TIME_ONLY = ('Look again',)
EDIT_BY_HAND = ('[data-library-profile-toggle]', '[data-lesson-up]', '[data-lesson-down]', '[data-lesson-edit]',
                '[data-lesson-remove]', '[data-library-add-lesson]', '[data-script-edit]', '[data-script-regenerate]',
                '[data-script-reset]')
PHONE_COURSE_MENU = ('Steer in words', 'Edit by hand', 'Make a variant', 'Archive', 'Delete')
PHONE_EDIT_BY_HAND = EDIT_BY_HAND[:6]
LIST_PAGE = ('[data-brief-box]', '[data-brief-find]', '[data-brief-by-hand]')
SETUP_SHEET = ('[data-setup-who]', '[data-setup-pick]', '[data-setup-make-new]', '[data-slot-day]', '[data-slot-time]',
               '[data-setup-add-time]', '[data-setup-minutes]', 'input[type="date"]', '[data-setup-start]')

PROPOSED_RUN = 'run-reach-proposed'
EMPTY_LIB = 'lib-reach-none'
PAUSED_LINE = 'Paused · nothing is on the calendar until you resume'
_SERVED = {}


def _serve():
    """One served app for the whole guard (None, having said so, without playwright)."""
    if 'h' not in _SERVED:
        _SERVED['h'] = L.serve()
    return _SERVED['h']


def _choices(page):
    page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
    return [t.strip() for t in page.locator('#cc-choice-options button').all_inner_texts()]


def _offers(labels, inventory, where):
    for verb in inventory:
        check(any(l.startswith(verb) for l in labels), f"{where} must offer {verb!r}: {labels}")


def _choose(page, label):
    page.locator('#cc-choice-options button').filter(has_text=re.compile(r'^\s*' + re.escape(label))).first.click()


def _asks(page, words):
    """The tap asked first (promptConfirm, never a browser dialog): read it, keep the thing."""
    modal = page.locator('#cc-confirm-modal')
    modal.wait_for(state='visible', timeout=10000)
    text = modal.inner_text()
    check(words in text, f"the tap asks {words!r}: {text}")
    page.locator('#cc-confirm-cancel-btn').click()
    modal.wait_for(state='hidden', timeout=5000)


def _visible(loc, what):
    check(loc.count() >= 1 and loc.first.is_visible(), f"{what} must be on the page")
    return loc.first


def _no_dialogs(page, seen):
    page.on('dialog', lambda d: (seen.append(d.message), d.dismiss()))


def _run_sheet(page, served, rid):
    L.admin(page, served, 'mom')
    page.goto(served.url(f'projects?id=prj-piano&piece=program:{rid}'), wait_until='load')
    return page.locator('[data-record-sheet]')


def scenario_live_run_sheet_menu_offers_every_verb():
    """⋯ on the monitoring sheet: every verb is offered, and each one's tap lands
    (an editor opens, a chooser asks which session, a confirm asks first)."""
    served = _serve()
    if served is None:
        return
    L._reset_kate()
    dialogs = []
    with served.browser() as page:
        _no_dialogs(page, dialogs)
        sheet = _run_sheet(page, served, 'run-kate')
        page.wait_for_selector('[data-record-sheet][data-open="true"] [data-monitor-stats]', timeout=15000)
        menu = sheet.locator('[data-run-menu]')
        menu.click()
        _offers(_choices(page), RUN_MENU, 'the run sheet ⋯')
        page.locator('#cc-choice-cancel-btn').click()

        def land(label, then):
            menu.click()
            _choices(page)
            _choose(page, label)
            then()

        def editor(sel):
            def go():
                box = sheet.locator(sel)
                box.wait_for(state='visible', timeout=10000)
                box.get_by_role('button', name='Cancel', exact=True).click()
                box.wait_for(state='detached', timeout=5000)
            return go

        def which_session():
            page.wait_for_function("() => (document.querySelector('#cc-choice-title') || {}).innerText?.includes('Which session?')"
                                   " && !document.querySelector('#cc-choice-modal').classList.contains('hidden')", timeout=10000)
            page.locator('#cc-choice-cancel-btn').click()

        land('Change the days', editor('[data-days-editor]'))
        land('Program settings', editor('[data-run-settings]'))
        land('Log a session', lambda: sheet.locator('input[placeholder="min"]').wait_for(state='visible', timeout=5000))
        land('Start a session', which_session)
        land('Look again', lambda: _asks(page, 'Look for a plan again?'))
        land('Plan without the book', lambda: _asks(page, 'Plan without the book?'))
        land('Done with it', lambda: _asks(page, 'Done with it?'))
        land('Drop', lambda: _asks(page, 'Drop this program?'))
        land('Delete', lambda: _asks(page, 'Delete'))
        # Pause takes effect on the tap; the paused sheet's ⋯ offers Resume, which puts it back.
        land('Pause', lambda: sheet.get_by_text(PAUSED_LINE).wait_for(state='visible', timeout=10000))
        menu.click()
        _offers(_choices(page), RUN_MENU_PAUSED, "a paused run's ⋯")
        _choose(page, 'Resume')
        sheet.get_by_text(PAUSED_LINE).wait_for(state='hidden', timeout=10000)
        L._wait(lambda: storage.get_program('run-kate')['state'] == 'active', "Resume puts the run back")
        check(dialogs == [], f"no browser dialog: {dialogs}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_live_run_sheet_body_offers_every_verb():
    """The monitoring sheet's own body: Reached it on every unjudged phase (P2), the lit
    rung's Another session on this / Move on, Preview on a rung, Remove in the log."""
    served = _serve()
    if served is None:
        return
    from services import programs
    L._reset_kate()
    if not any(s.get('id') for s in storage.get_program('run-kate').get('sessions') or []):
        logged = programs.log_session('run-kate', source='added')
        check(logged.get('status') == 'success', f"the fixture logs a session: {logged}")
    with served.browser() as page:
        sheet = _run_sheet(page, served, 'run-kate')
        page.wait_for_selector(f'[data-record-sheet] [data-monitor-phase="{L.FOUND}"] [data-rung-current]', timeout=15000)
        phases = storage.get_program('run-kate')['progress']['phases'] or {}
        unjudged = [ph for ph, v in phases.items() if not v.get('milestone_hit_at')]
        check(len(unjudged) == 2, f"the fixture has two unjudged phases: {unjudged}")
        seen = []   # each verb as the page reads it; the inventory is checked against these
        for ph in unjudged:
            btn = _visible(sheet.locator(f'[data-reached-it="{ph}"]'), f"Reached it on phase {ph}")
            seen.append(btn.inner_text().strip())
        sheet.locator(f'[data-reached-it="{unjudged[-1]}"]').first.click()
        _asks(page, 'Reached this milestone?')
        rung = sheet.locator('[data-rung-current]')
        check(rung.count() == 1, "one lit rung")
        for sel in ('[data-unit-move="back"]', '[data-unit-move="next"]'):
            btn = _visible(rung.locator(sel), f"{sel} on the lit rung")
            check(btn.is_enabled(), f"{btn.inner_text()} is live")
            seen.append(btn.inner_text().strip())
        rung.locator('[role="button"]').first.click()
        preview = rung.locator('[data-rung-preview]')
        preview.first.wait_for(state='visible', timeout=5000)
        check(preview.count() == 2, f"Preview on the rung, one per session: {preview.all_inner_texts()}")
        seen += [t.strip().split(' · ')[0] for t in preview.all_inner_texts()]
        preview.first.click()
        player = page.locator('[x-data="lessonPlayer()"]')
        player.wait_for(state='visible', timeout=10000)
        player.get_by_role('button', name='Close session', exact=True).click()
        player.wait_for(state='hidden', timeout=5000)
        sheet.locator('[data-monitor-log] button', has_text='Session log').click()
        remove = _visible(sheet.locator('[data-session-remove]'), "Remove in the session log")
        seen.append(remove.inner_text().strip())
        remove.click()
        _asks(page, 'Remove this session?')
        missing = [verb for verb in RUN_BODY if verb not in seen]
        check(not missing and seen.count(RUN_BODY[0]) == len(unjudged),
              f"the run sheet body must offer {missing} (Reached it once per unjudged phase): {seen}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_live_proposed_block_offers_every_verb():
    """A proposal in the record sheet: What it adds to the week, Not these times?,
    Approve and Dismiss, with Edit, Look again and Plan without the book beside them."""
    served = _serve()
    if served is None:
        return
    if not storage.get_program(PROPOSED_RUN):
        L._run(PROPOSED_RUN, 'sam', L.PIANO, 'prj-piano', L._progress(), state='proposed')
    with served.browser() as page:
        sheet = _run_sheet(page, served, PROPOSED_RUN)
        approve = sheet.get_by_role('button', name='Approve', exact=True)
        approve.wait_for(state='visible', timeout=15000)
        _visible(sheet.get_by_text(PROPOSED[0]), PROPOSED[0])
        for verb in PROPOSED[1:]:
            _visible(sheet.get_by_role('button', name=verb, exact=True), f"the proposed block: {verb}")
        sheet.get_by_role('button', name=PROPOSED[1], exact=True).click()
        _visible(sheet.locator('[data-setup-slot]'), 'the times to change')
        sheet.get_by_role('button', name='Save these times', exact=True).wait_for(state='visible', timeout=5000)
        sheet.get_by_role('button', name='Cancel', exact=True).first.click()
        approve.click()
        _asks(page, 'Approve this program?')
        sheet.get_by_role('button', name=PROPOSED[3], exact=True).click()
        _asks(page, 'Dismiss this proposal?')
        sheet.get_by_role('button', name=PROPOSED[4], exact=True).click()
        for sel, what in (('input[type="number"][max="7"]', 'sessions a week'), ('input[type="date"]', 'the target date')):
            _visible(sheet.locator(sel), f"Edit opens {what}")
        sheet.get_by_text('Close', exact=True).click()   # the Edit toggle, not the sheet's ✕
        sheet.get_by_role('button', name=PROPOSED[5], exact=True).click()
        _asks(page, 'Look for a plan again?')
        sheet.get_by_role('button', name=PROPOSED[6], exact=True).click()
        _asks(page, 'Plan without the book?')
        check(storage.get_program(PROPOSED_RUN)['state'] == 'proposed', "every tap was backed out of")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_live_course_page_menu_offers_every_verb():
    """The course page's ⋯, and Look again on a Practice-time-only program (its source
    row and its ⋯), each tap landing where it should."""
    served = _serve()
    if served is None:
        return
    L._restore_piano()
    if not storage.get_library_program(EMPTY_LIB):
        row = L._library_row(EMPTY_LIB, 'Learn knots', [], [], origin='none')
        row['source']['reason'] = 'research could not run'
        storage.add_library_program(row)
    before = {r['id'] for r in storage.get_library_programs()}
    try:
        with served.browser() as page:
            L.admin(page, served, 'mom')
            page.goto(served.url(f'library?id={L.PIANO}'), wait_until='load')
            page.wait_for_selector('[data-course-header]', timeout=15000)
            menu = page.locator('[data-course-menu]')
            menu.click()
            _offers(_choices(page), COURSE_MENU, 'the course page ⋯')
            page.locator('#cc-choice-cancel-btn').click()

            def land(label, then):
                menu.click()
                _choices(page)
                _choose(page, label)
                then()

            def steer():
                page.wait_for_function("() => document.activeElement && document.activeElement.hasAttribute('data-steer-box')", timeout=5000)
                _visible(page.locator('[data-steer-send]'), 'Steer send')

            def edit_by_hand():
                page.wait_for_selector('[data-edit-by-hand]', timeout=5000)
                page.locator('[data-edit-done]').click()
                page.wait_for_selector('[data-edit-by-hand]', state='detached', timeout=5000)

            def variant():
                page.locator('#cc-input-modal').wait_for(state='visible', timeout=5000)
                page.locator('#cc-input-cancel-btn').click()
                page.locator('#cc-input-modal').wait_for(state='hidden', timeout=5000)

            def delete_in_use():
                page.locator('#cc-alert-modal').wait_for(state='visible', timeout=5000)
                said = page.locator('#cc-alert-message').inner_text()
                check(said.startswith('In use by'), f"Delete on a program in use says who: {said}")
                page.locator('#cc-alert-modal button', has_text='OK').click()
                page.locator('#cc-alert-modal').wait_for(state='hidden', timeout=5000)

            def start_it_for():
                page.wait_for_selector(f'[data-setup-sheet] [data-setup-pick="{L.PIANO}"][aria-pressed="true"]', timeout=10000)
                page.keyboard.press('Escape')
                page.wait_for_selector('[data-setup-sheet]', state='detached', timeout=5000)

            land('Steer in words', steer)
            land('Edit by hand', edit_by_hand)
            # Write lessons is read off the menu, never tapped here: its tap starts the
            # writing job at once (test_library_scripts_live drives it).
            land('Make a variant', variant)
            land('Archive', lambda: _asks(page, 'Archive Learn piano?'))
            land('Delete', delete_in_use)
            land('Start it for…', start_it_for)
            check(not storage.get_library_program(L.PIANO).get('archived'), "Keep it kept it")

            page.goto(served.url(f'library?id={EMPTY_LIB}'), wait_until='load')
            page.wait_for_selector('[data-course-header]', timeout=15000)
            _visible(page.locator('[data-look-again]'), 'Look again on the source row')
            page.locator('[data-look-again]').click()
            _asks(page, 'Look again makes a fresh program from the same profile.')
            menu.click()
            _offers(_choices(page), COURSE_PRACTICE_TIME_ONLY, "a Practice-time-only page's ⋯")
            _choose(page, 'Look again')
            _asks(page, 'Look again makes a fresh program from the same profile.')
            check({r['id'] for r in storage.get_library_programs()} == before, "nothing was made")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        for r in storage.get_library_programs():
            if r['id'] not in before or r['id'] == EMPTY_LIB:
                storage.delete_library_program(r['id'])


def scenario_live_edit_by_hand_offers_every_verb():
    """Behind ⋯ › Edit by hand: the profile form, ▲ ▼ Edit Remove on every lesson,
    Add lesson on every phase, and a script's Edit, Regenerate and Reset."""
    served = _serve()
    if served is None:
        return
    L._restore_piano()
    slot = {'lesson_id': L.SCALES, 'variant_label': 'Session A'}
    if not (storage.get_library_script(L.PIANO, slot) or {}).get('scenes'):
        token = storage.claim_library_script(L.PIANO, slot)
        check(token and storage.commit_library_script(L.PIANO, slot, token, {
            'origin': 'generated', 'minutes': 3,
            'scenes': [{'type': 'say', 'text': 'Written for you, {name}.'}, {'type': 'do', 'text': 'Play it twice.', 'seconds': 60}]}),
            "the fixture stores a script")
    with served.browser() as page:
        L.admin(page, served, 'mom')
        page.goto(served.url(f'library?id={L.PIANO}'), wait_until='load')
        page.wait_for_selector('[data-course-header]', timeout=15000)
        L._edit_by_hand(page)
        editor = page.locator('[data-edit-by-hand]')
        for sel in EDIT_BY_HAND[:-1]:   # Reset is the script editor's; read once it opens
            _visible(editor.locator(sel), f"Edit by hand: {sel}")
        editor.locator('[data-library-profile-toggle]').click()
        profile = editor.locator('[data-library-profile]')
        profile.wait_for(state='visible', timeout=5000)
        _visible(profile.locator('input[name="title"]'), 'the profile form')
        profile.get_by_role('button', name='Cancel', exact=True).click()
        profile.wait_for(state='detached', timeout=5000)
        lessons = editor.locator('[data-library-lesson]')
        check(lessons.count() == 3, f"every lesson is listed: {lessons.count()}")
        for i in range(lessons.count()):
            row = lessons.nth(i)
            for sel in EDIT_BY_HAND[1:5]:
                _visible(row.locator(sel), f"{sel} on lesson {row.get_attribute('data-lesson-id')}")
        check(editor.locator('[data-lesson-up]:enabled').count() >= 1 and editor.locator('[data-lesson-down]:enabled').count() >= 1,
              "▲ and ▼ can each move something")
        chords = editor.locator(f'[data-library-lesson][data-lesson-id="{L.CHORDS}"]')
        chords.locator('[data-lesson-edit]').click()
        _visible(chords.locator('[data-lesson-form]'), 'Edit opens the lesson form')
        chords.locator('[data-lesson-edit]').click()
        chords.locator('[data-lesson-form]').wait_for(state='detached', timeout=5000)
        chords.locator('[data-lesson-remove]').click()
        _asks(page, 'Remove Chords?')
        adds = editor.locator('[data-library-add-lesson]')
        check(adds.count() == 2, f"Add lesson on every phase: {adds.count()}")
        adds.first.click()
        page.locator('#cc-input-modal').wait_for(state='visible', timeout=5000)
        page.locator('#cc-input-cancel-btn').click()
        page.locator('#cc-input-modal').wait_for(state='hidden', timeout=5000)
        line = editor.locator(f'[data-library-lesson][data-lesson-id="{L.SCALES}"] [data-lesson-script][data-variant="Session A"]')
        _visible(line.locator('[data-script-play]'), 'Play on a script')
        line.locator('[data-script-regenerate]').click()
        _asks(page, 'Rewrite')
        line.locator('[data-script-edit]').click()
        script = editor.locator(f'[data-library-lesson][data-lesson-id="{L.SCALES}"] [data-script-editor][data-variant="Session A"]')
        script.locator('[data-script-row]').first.wait_for(state='visible', timeout=10000)
        reset = _visible(script.locator(EDIT_BY_HAND[-1]), 'Reset in the script editor')
        check(reset.is_enabled(), "Reset is offered once the stored script is read")
        line.locator('[data-script-edit]').click()
        script.wait_for(state='detached', timeout=5000)
        page.locator('[data-edit-done]').click()
        page.wait_for_selector('[data-edit-by-hand]', state='detached', timeout=5000)
        check([l['id'] for l in storage.get_library_program(L.PIANO)['lessons']] == [L.SCALES, L.CHORDS, L.TWINKLE],
              "every tap was backed out of")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_live_list_page_offers_every_verb():
    """The Library list page: the brief box leads with Find a plan, and Fill it in by
    hand keeps the form."""
    served = _serve()
    if served is None:
        return
    with served.browser() as page:
        L.admin(page, served, 'mom')
        page.goto(served.url('library'), wait_until='load')
        page.wait_for_selector('[data-library-new]', timeout=15000)
        page.locator('[data-library-new]').click()
        for sel in LIST_PAGE:
            _visible(page.locator(sel), f"the list page: {sel}")
        find = page.locator('[data-brief-find]')
        check(find.inner_text().strip().startswith('Find a plan'), f"Find a plan reads: {find.inner_text()}")
        by_hand = page.locator('[data-brief-by-hand]')
        check(by_hand.inner_text().strip().startswith('Fill it in by hand'), f"Fill it in by hand reads: {by_hand.inner_text()}")
        by_hand.click()
        _visible(page.locator('[data-library-create-form] input[name="title"]'), 'the hand form')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_live_setup_sheet_offers_every_verb():
    """The setup sheet from + Add › Program: who, which, Make a new one, the days and
    times with + Add a time, minutes, the target date and Start the program."""
    served = _serve()
    if served is None:
        return
    with served.browser() as page:
        L.admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.wait_for_selector('[data-project-add]', timeout=15000)
        page.locator('[data-project-add]').click()
        _choices(page)
        _choose(page, 'Program')
        sheet = page.locator('[data-setup-sheet]')
        sheet.wait_for(state='visible', timeout=10000)
        who = sheet.locator('[data-setup-who]')
        check(who.is_enabled() and who.locator('option').count() >= 2, "a parent chooses who")
        who.select_option('sam')
        sheet.locator('[data-setup-make-new]').click()
        _visible(sheet.locator('[data-setup-new] input[name="title"]'), 'Make a new one opens its form')
        sheet.locator(f'[data-setup-pick="{L.DRUMS}"]').click()
        slots = sheet.locator('[data-setup-slot]')
        slots.first.wait_for(state='visible', timeout=10000)
        for sel in SETUP_SHEET:
            _visible(sheet.locator(sel), f"the setup sheet: {sel}")
        n = slots.count()
        sheet.locator('[data-setup-add-time]').click()
        check(slots.count() == n + 1, f"+ Add a time adds a row: {n} -> {slots.count()}")
        start = sheet.locator('[data-setup-start]')
        check(start.is_enabled() and start.inner_text().strip() == 'Start the program', f"Start reads: {start.inner_text()}")
        page.keyboard.press('Escape')
        sheet.wait_for(state='detached', timeout=5000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_live_phone_keeps_edit_by_hand():
    """P3: the phone's course page keeps Edit by hand (profile, ▲ ▼ Edit Remove, Add
    lesson); only the script editor, Regenerate and Write lessons stay admin-only."""
    served = _serve()
    if served is None:
        return
    L._restore_piano()
    with served.browser() as page:
        L.pwa(page, served, 'mom')
        page.goto(served.url('app?view=library'), wait_until='load')
        page.wait_for_selector('[data-library-page]', timeout=15000)
        page.locator(f'[data-library-open][data-library-id="{L.PIANO}"]').first.click()
        page.wait_for_selector('[data-course-menu]', timeout=10000)
        page.locator('[data-course-menu]').click()
        page.wait_for_selector('.pwa-prompt-overlay [data-pick]', timeout=5000)
        labels = [t.strip() for t in page.locator('.pwa-prompt-overlay [data-pick]').all_inner_texts()]
        _offers(labels, PHONE_COURSE_MENU, "the phone's course ⋯")
        check(not any(l.startswith('Write lessons') for l in labels), f"Write lessons stays admin-only: {labels}")
        page.locator('.pwa-prompt-overlay [data-pick]', has_text='Edit by hand').click()
        editor = page.locator('[data-edit-by-hand]')
        editor.wait_for(state='visible', timeout=5000)
        for sel in PHONE_EDIT_BY_HAND:
            _visible(editor.locator(sel), f"the phone's Edit by hand: {sel}")
        check(editor.locator('[data-script-edit], [data-script-regenerate], [data-script-editor]').count() == 0,
              "no script editor on the phone")
        check(served.errors() == [], f"no page errors: {served.errors()}")


LIVE = (scenario_live_run_sheet_menu_offers_every_verb, scenario_live_run_sheet_body_offers_every_verb,
        scenario_live_proposed_block_offers_every_verb, scenario_live_course_page_menu_offers_every_verb,
        scenario_live_edit_by_hand_offers_every_verb, scenario_live_list_page_offers_every_verb,
        scenario_live_setup_sheet_offers_every_verb, scenario_live_phone_keeps_edit_by_hand)


if __name__ == '__main__':
    os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp())
    scenario_the_program_surfaces_have_a_driver_side_mount()
    scenario_my_day_and_the_drives_view_share_one_builder()
    scenario_a_due_session_is_drawn_without_being_asked_for()
    scenario_logging_a_session_redraws_whichever_surface_it_was_tapped_on()
    scenario_the_drives_day_carries_what_my_day_carries()
    scenario_a_session_can_be_opened_and_finished()
    scenario_the_tab_is_named_for_what_it_holds()
    scenario_the_day_is_one_page_with_a_jump_row()
    scenario_a_rebuilt_pane_gets_its_sections_back()
    scenario_last_nights_session_is_not_the_next_one()
    scenario_a_child_who_cannot_tap_still_has_a_surface()
    scenario_every_inline_script_still_parses()
    scenario_a_session_can_be_started_ahead_of_its_window()
    only = sys.argv[1:]
    for live in LIVE:
        if only and not any(o in live.__name__ for o in only):
            continue
        live()
        print(f"PASS {live.__name__}")
    print("test_programs_reachable OK")
