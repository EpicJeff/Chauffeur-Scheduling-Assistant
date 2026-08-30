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

Run from chauffeur/:  python tests/test_programs_reachable.py
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    for name in ('app.html', 'programs.html'):
        html = main.templates.env.get_template(name).render(request=_R())
        blocks = re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>',
                            html, re.S)
        check(blocks, f"{name} must carry inline script to check")
        for i, block in enumerate(blocks):
            if not block.strip():
                continue
            path = os.path.join(tmp, f'{name}.{i}.js')
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
    for part in ('status', 'requests', 'now', 'programs', 'dueSoon'):
        check(part in stack, f"the drives stack must draw {part}")


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


if __name__ == '__main__':
    os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp())
    scenario_the_program_surfaces_have_a_driver_side_mount()
    scenario_my_day_and_the_drives_view_share_one_builder()
    scenario_a_due_session_is_drawn_without_being_asked_for()
    scenario_logging_a_session_redraws_whichever_surface_it_was_tapped_on()
    scenario_the_drives_day_carries_what_my_day_carries()
    scenario_a_session_can_be_opened_and_finished()
    scenario_the_tab_is_named_for_what_it_holds()
    scenario_every_inline_script_still_parses()
    print("test_programs_reachable OK")
