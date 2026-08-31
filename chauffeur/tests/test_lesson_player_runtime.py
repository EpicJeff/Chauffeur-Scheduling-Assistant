"""The player, exercised rather than read.

Reachability and the no-streak rule at the surface — the same discipline
test_programs_runtime.py applies to the pages this component lands on.
"""
import io
import os

from harness import check

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    return io.open(os.path.join(HERE, 'templates', rel), encoding='utf-8').read()


def scenario_component_exists_and_renders_the_four_beats():
    src = _read('components/lesson_player.html')
    for marker in ("'say'", "'do'", "'check'", "'show'"):
        check(marker in src, f"renders {marker} beats")
    check('stepsToScenes' in src,
          "fallback ladder: plain steps become beats client-side")
    check('got it' in src.lower(), "the check offers its taps")


def scenario_checks_are_never_stored():
    """A check tap advances the scene and nothing else. No fetch, no POST,
    no localStorage write may ride it."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'answerCheck\([^)]*\)\s*{([^}]*)}', src)
    check(m, "answerCheck exists")
    body = m.group(1)
    for forbidden in ('fetch', 'localStorage', 'api', 'POST'):
        check(forbidden not in body,
              f"a check tap must not {forbidden} — it only advances")


def scenario_programs_page_opens_the_player():
    src = _read('programs.html')
    check('lesson_player.html' in src, "the page includes the player")
    check('lesson-player:open' in src, "and a window can open it")


def scenario_no_streak_language_in_the_player():
    src = _read('components/lesson_player.html').lower()
    for word in ('streak', 'missed', 'in a row'):
        check(word not in src, f"the player never says {word!r}")


def scenario_programs_page_never_posts_from_the_player_directly():
    """The player only ever dispatches lesson-player:done; the PAGE is the
    one place that turns that into a write, and it has to reuse the
    existing session-log action rather than growing a second path to the
    same POST."""
    src = _read('programs.html')
    check('lesson-player:done' in src, "the page listens for the finish")
    check('onLessonDone' in src, "and handles it")
    import re
    m = re.search(r'onLessonDone\(detail\)\s*\{(.*?)\n                \},', src, re.S)
    check(m, "onLessonDone's body is findable")
    body = m.group(1) if m else ''
    check('this.logSession(p' in body,
          "by calling the exact log action the page already had")
    check('fetch(' not in body,
          "and never by growing a second path to the same POST")
    # Same act, same record: this used to file `source: 'added'` with no
    # slot_date while app.html filed `source: 'asked'` with one, so a
    # session finished after midnight from this page landed on the wrong
    # day -- `w.logged` stays false, tonight still offers Start, and the
    # "did it happen?" ask still fires.
    check("source: 'asked'" in body,
          "answering a scheduled slot is 'asked', the same source the PWA sends")
    check('slot_date: w.date' in body,
          "and it carries the window's own date, so the session files under "
          "the evening it was about")


def scenario_the_component_reads_the_panel_flag():
    """?panel=true sizes the player rather than forking it into a second
    component -- the kiosk-shares-logic / TripLogic pattern this app uses
    everywhere else a surface has both a personal and a wall presentation."""
    src = _read('components/lesson_player.html')
    check("get('panel')" in src, "the player reads the panel flag itself")
    check('panel-modal' in src,
          "and marks itself opaque on a wall board, the same class "
          "avatar_editor.html and the pet_* overlays already use for a "
          "full-screen modal (panel_skin.html's .panel-modal rule)")


def scenario_show_degrades_unknown_kinds_to_a_caption():
    """Only timer and metronome get a real picture in this task; any other
    primitive kind (keyboard/fretboard/cards/counter land later) has to
    fall back to its caption, mirroring sanitize_script's own degrade rule
    for a primitive the renderer does not recognise."""
    src = _read('components/lesson_player.html')
    check('isRenderableShow' in src,
          "a named gate between primitives this renderer draws and ones it does not")
    check("'timer'" in src and "'metronome'" in src,
          "the two primitives this task actually renders")


def scenario_sound_is_cleared_on_scene_change_and_close():
    """The countdown and the metronome must never survive past the scene —
    or the player — that started them."""
    src = _read('components/lesson_player.html')
    check('stopSound' in src, "one place that clears both timers")
    check(src.count('this.stopSound()') >= 3,
          "called from advance (scene change), close, and finish")


def scenario_check_taps_never_bubble_into_the_advance_handler():
    """Fix round 1, finding 1. The three check buttons sit inside the
    scene-area div, whose own handler is `scene().type !== 'check' &&
    advance()`. A tap runs answerCheck() -> advance() (idx already moved),
    then bubbles to that ancestor, which re-reads scene() against the
    ALREADY-advanced index — and if the new scene is not itself a check,
    the bubbled click double-advances: it skips a scene (killing whatever
    enterScene() just started for it) or finishes one scene early.
    Invisible today only because stepsToScenes always puts the check last,
    where the second read still sees 'check' and the `&&` short-circuits —
    a generated script's mid-lesson check would not be so lucky. Every
    check tap must stop propagation so it can never reach that handler."""
    src = _read('components/lesson_player.html')
    import re
    taps = re.findall(r'@click(\.stop)?="answerCheck\([^)]*\)"', src)
    check(len(taps) >= 3, f"all three check taps present, found {len(taps)}")
    check(all(m == '.stop' for m in taps),
          "every check tap must carry .stop, or it can bubble into the "
          "scene area's own tap-to-advance handler")
    # The offer chips replace those three taps in place on the same
    # check scene, so they sit inside the same ancestor and need the
    # identical guard for the identical reason.
    chips = re.findall(r'@click(\.stop)?="(acceptOffer|declineOffer)\(\)"', src)
    check(len(chips) == 2, f"both offer chips present, found {len(chips)}")
    check(all(m[0] == '.stop' for m in chips),
          "and both carry .stop, same handler, same bug")


def scenario_an_unrenderable_show_with_no_caption_still_says_something():
    """Fix round 1, finding 2. sayText() used to fall through text/caption
    to a bare ''. A `say` scene always has non-empty text (sanitize_script
    drops an empty or screened say beat outright), but a `show` scene is
    explicitly allowed an EMPTY caption even when its primitive is valid —
    services/program_lessons.py's sanitize_script only screens a caption
    when one is present (`if caption and _screened(...)`), so a well-formed
    keyboard/fretboard/cards/counter primitive (kinds this task does not
    draw yet) with no caption at all sails through. That scene lands on
    sayText() alone, and a bare '' meant a literally blank content area:
    no kicker, no ring, no metronome, no text. The fallback chain needs a
    real third term, not another empty string standing in for one."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r"sayText\(\)\s*\{([^}]*)\}", src)
    check(m, "sayText exists")
    body = m.group(1)
    check(body.count('||') >= 2, "text, caption, and a real fallback — three terms")
    check("New material" in body,
          "the last-resort term must be an actual sentence, not '' playing "
          "the part of one")


def scenario_fallback_ladder_never_produces_an_empty_scene_list():
    """Fix round 1, finding 2's companion ask: exercise the degenerate
    fallback ladder (steps: [], no unit_title, no milestone) rather than
    just reading it.

    stepsToScenes lives inside the component's own <script>, not as an
    importable Python function, and the coordinator's note was explicit
    that extracting it into something separately testable would be
    restructuring the component for testability — ruled out. So this
    asserts the one structural guarantee that actually makes the claim
    true, traced by hand against the current source: an empty w.unit_title
    skips the opening say; an empty w.steps skips every do (Array.forEach
    on [] never calls its callback); `!scenes.length && w.milestone` is
    false whenever w.milestone is ALSO falsy, so the fallback say is
    skipped too — and the final scenes.push for the check runs two lines
    later regardless, completely unguarded. A window with nothing at all
    to say therefore still ends up with exactly one scene: the check.

    The assertion below is what makes "unconditional and outside every
    guard" a checked fact rather than a claim: the check-push and the
    `return scenes` that follows it are adjacent, same-indentation lines
    with no closing brace between them. A guarded push (inside the `if`
    two lines above it, or any other conditional) would need to close
    that block before reaching the shared return, which would break this
    exact adjacency."""
    src = _read('components/lesson_player.html')
    check('stepsToScenes' in src, "the fallback ladder function exists")
    check(
        "scenes.push({type: 'check', ask: 'Good session?'});\n"
        "            return scenes;" in src,
        "the check push must be the line immediately before the return, "
        "with no closing brace in between — proof it sits outside every "
        "earlier `if`, so the scene list can never come back empty"
    )


def scenario_the_wall_and_the_pwa_reach_the_player():
    """Not "can open the player" -- open it with a REAL LESSON.

    The version of this scenario that shipped only looked for the string
    `lesson-player:open` in each file, which both surfaces had from the
    first slice, and it stayed green through an entire arc in which
    neither one ever fetched a lesson: both dispatched `lesson: null` on
    every tap and both always ran the P1 fallback ladder, so the sweep,
    the stored scripts, the origins and every primitive renderer were
    invisible on the phone and on the wall while the arc claimed the three
    tap sites reached the identical session.

    So this asserts the join itself, scoped to each surface's own fetch:
    the request that resolves the slot, and the dispatch that carries what
    came back."""
    import re
    pwa = _read('app.html')
    m = re.search(r'async function loadWindowLesson\(w\)\s*\{(.*?)\n        \}',
                  pwa, re.S)
    check(m, "the PWA has a lesson join at all")
    body = m.group(1) if m else ''
    check('api/programs/${w.program_id}/lesson?' in body,
          "and it asks the lesson endpoint for THIS window's program")
    for key in ('phase_name', 'unit_n', 'session_label'):
        check(key in body, f"with the whole slot key -- {key} is part of it")
    check('w._lesson = (await r.json()).lesson' in body,
          "and joins the answer onto the window the player is handed")
    check(re.search(r"lesson-player:open'[\s\S]{0,200}?lesson: w\._lesson", pwa),
          "the PWA's Start dispatch passes that lesson, not a bare null")
    check('await loadWindowLesson(w)' in pwa,
          "and the join is awaited before the dispatch that reads it")

    wall = _read('components/programs_card.html')
    m = re.search(r'async loadWindowLesson\(w\)\s*\{(.*?)\n            \},',
                  wall, re.S)
    check(m, "the wall card has a lesson join too")
    body = m.group(1) if m else ''
    # A panel is DEVICE: the signed-in lesson read answers it null forever
    # and correctly (it returns the stored row). The wall gets the
    # scenes-only projection instead -- the same shape of answer, decided
    # by what the endpoint returns rather than by widening a refused read,
    # exactly as api/programs/celebrations already is.
    check('lesson-scenes' in body,
          "through the scenes-only route a panel is actually allowed to call")
    for key in ('phase_name', 'unit_n', 'session_label'):
        check(key in body, f"with the whole slot key -- {key} is part of it")
    check('w._lesson = (await r.json()).lesson' in body,
          "and joins it onto the raw window the player is handed")
    check('this.loadWindowLesson(x.raw)' in wall,
          "called for today's windows as they load")
    check(re.search(r"lesson-player:open'[\s\S]{0,200}?lesson: w\.raw\._lesson", wall),
          "and the wall's Start dispatch passes that lesson, not a bare null")


def scenario_the_wall_reads_the_slot_key_off_the_window():
    """A panel is refused `GET /api/programs` outright, so it can never
    learn `current_unit` from a program row -- which is half a lesson's
    slot key. `practice_windows` carries `unit_n` for exactly this reason,
    derived from the same `unit_for` walk the unit title beside it came
    from, so one evening can never name two rungs."""
    from services import programs
    import inspect
    src = inspect.getsource(programs.practice_windows)
    check("'unit_n': int(unit.get('n') or 0)" in src,
          "the practice window carries its own rung")
    for page in ('app.html', 'components/programs_card.html'):
        check('unit_n: w.unit_n' in _read(page).replace('w.raw.', 'w.'),
              f"{page} takes the rung off the window, not from a second source")


def scenario_the_last_scene_is_never_an_ambient_tap():
    """Finishing offers an irreversible write -- append_program_session has
    no unlog and a logged session moves the rung on. A whole-screen tap
    target is the right shape for "next beat" and the wrong one for that,
    so the scene area's own handler goes inert on the last scene and the
    footer button is the only way out. Safe before this only by luck:
    stepsToScenes always ends on a `check`, but _SYSTEM asks for a check
    "near the end" and a generated script routinely ends on say/do/show."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'@click="scene\(\)\.type !== \'check\'([^"]*)"', src)
    check(m, "the scene area's tap handler is findable")
    check('!isLast()' in (m.group(1) if m else ''),
          "and it does nothing on the last scene")


def scenario_finishing_asks_before_it_logs():
    """The design says the final check merely PREFILLS the log ask. It was
    the log: whichever tap landed last POSTed a session immediately, on
    both listening surfaces. promptConfirm, never a browser dialog."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'async finish\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "finish() is findable")
    body = m.group(1) if m else ''
    check('promptConfirm' in body, "it asks first")
    for banned in ('confirm(', 'alert(', 'prompt('):
        check(banned not in body.replace('promptConfirm(', '')
                                .replace('promptInput(', ''),
              f"never a browser {banned} dialog (house rule)")
    check(re.search(r'promptConfirm[\s\S]*?dispatchEvent', body),
          "and the dispatch only happens after the ask")
    # Fix round: gated on whether the HOST announced a listener, not on
    # `panel` -- a non-panel host with no listener (the calendar page,
    # which owns no log-a-session action) asked the identical dishonest
    # question under the old gate. See
    # scenario_host_listen_flag_is_explicit_not_dom_sniffed and its
    # neighbours for the announcement side of this fix.
    check('this.hostListens' in body,
          "the ask is gated on whether the host announced a listener")
    check('!this.panel' not in body,
          "panel must no longer be what decides the ask")


def scenario_the_wall_button_does_not_promise_a_write():
    """home.html registers no `lesson-player:done` listener, by design -- a
    panel authenticates as a place, not a person. "Log it?" there promised
    a write that was never coming and simply closed the modal.

    The gate used to be `panel` itself, which was dishonest in the OTHER
    direction too: a non-panel host with no listener (home.html opened as
    an ordinary page, or the calendar page, which owns no log-a-session
    action at all) asked the identical question with nothing behind it.
    It has to be gated on whether the host actually announced a
    listener."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'x-text="isLast\(\) \? ([^"]*)"', src)
    check(m, "the footer button's label expression is findable")
    label = m.group(1) if m else ''
    check("hostListens ? 'Log it?'" in label,
          f"a host that listens gets the log ask, got {label!r}")
    check("'Finish'" in label,
          f"and a host that does not listen gets an honest Finish, got {label!r}")
    check("panel ?" not in label,
          "panel must not be what this ternary branches on any more")
    check('lesson-player:done' not in _read('home.html'),
          "the wall really does not listen -- if that changes, so must this")
    check('window.chfHasLessonDoneListener = true' not in _read('home.html'),
          "and it must never announce a listener it does not have")


def scenario_the_player_says_where_the_lesson_came_from():
    """The spec: "source_url carried; the player shows the link." It was
    carried on every row and displayed nowhere, which left the whole
    cited/generated distinction -- the thing the curate module exists to
    defend -- invisible to the family, and Task 9's honest label for an
    uncited unit labelling nothing anybody sees."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'originLabel\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "originLabel() exists")
    body = m.group(1) if m else ''
    check('Written by the app' in body, "a generated lesson says so")
    check('sourceHost()' in body, "and a cited one names where it came from")
    check("plan's own steps" in body,
          "and the fallback ladder says it is playing the plain steps, "
          "rather than passing them off as a lesson")
    check(re.search(r'source_url[\s\S]{0,400}?x-text="sourceHost\(\)"', src),
          "and the source is rendered as a real link, not just computed")


def scenario_the_editor_can_reorder_and_names_its_source():
    """Two claims the shipped editor did not honour: the spec's own
    "reorder/edit/delete beats", and showing where a script came from."""
    import re
    src = _read('programs.html')
    m = re.search(r'moveLessonRow\(p, ph, label, i, delta\)\s*\{(.*?)\n                \},',
                  src, re.S)
    check(m, "the editor can move a beat")
    body = m.group(1) if m else ''
    check('splice' in body, "by splicing the draft, which IS the order")
    check('moveLessonRow(p, ph, label, i, -1)' in src, "there is an up tap")
    check('moveLessonRow(p, ph, label, i, 1)' in src, "and a down tap")
    check('lessonOriginLabel(p, ph, label)' in src,
          "and the disclosure names the origin")
    check('lessonSourceHost(p, ph, label)' in src, "and links the source")
    # The reason a slot has no script, when the answer is not "nothing has
    # tried yet" -- an empty api key fails every call forever and used to
    # be indistinguishable from a sweep that had not got there.
    check(re.search(r'lessonMeta\[lessonKey\(p, ph, label\)\] \|\| \{\}\)\.note', src),
          "and prints why a generation failed, where a person looks")


def scenario_the_wall_card_dispatches_the_raw_window_not_the_display_row():
    """components/programs_card.html's pgToday rows are a display shape --
    w.key/w.when/w.who/w.title/w.lesson/w.label -- built for this card's own
    strings, not the practice_windows row the player reads (steps,
    unit_title, milestone, title, session_label, program_id, member_id,
    logged). Losing the raw row here means the player would open on nothing
    but its own empty fallback, silently, until a real evening."""
    src = _read('components/programs_card.html')
    check('raw: w' in src,
          "the display mapping keeps the raw window under its own field")
    check('window: w.raw' in src,
          "and the open dispatch passes THAT, not the mapped display row")


def scenario_the_lesson_player_is_included_once_on_each_page_not_inside_the_card():
    """components/programs_card.html's rows() macro is IMPORTED by
    board_tile_body.html for every programs tile on a board, and a Jinja
    {% import %} discards a template's top-level markup (verified directly
    against this app's own Jinja environment, not assumed) -- so an include
    buried inside the card would only ever reach the wall by riding
    programs_card.html's OWN direct include elsewhere (home.html, for its
    <script>), which is correct today by coincidence and silently wrong the
    day that coupling changes. The include belongs on the PAGE, same as the
    other page-level singleton overlays (avatar_editor.html /
    pet_editor.html / pet_battle.html / pet_guide.html)."""
    card_src = _read('components/programs_card.html')
    check("include 'components/lesson_player.html'" not in card_src,
          "the CARD never includes the player itself")
    # calendar.html joined this list once family_calendar.html's shared
    # details dialog gained its own Start tap -- without the include
    # there, that page's dispatch of lesson-player:open would land on
    # nobody.
    for page in ('home.html', 'app.html', 'calendar.html'):
        src = _read(page)
        check(src.count("include 'components/lesson_player.html'") == 1,
              f"{page} includes the player exactly once")


def scenario_the_wall_tap_is_panel_sized():
    """A board tile is read across a room, not held in a hand -- the wall's
    Start tap has to be BIGGER than a phone chip, not merely present.

    Fix round 1, finding 2: the first cut matched the brief's own worked
    example (`py-2 px-4`) faithfully, and the brief's example was wrong --
    py-2 is SMALLER than the PWA's own session-sheet buttons
    (app.html's `py-2.5 px-4`), the opposite of panel-appropriate. This repo's
    established panel-tier convention is the `shellXl(b)` branch in
    components/chores_lanes.html's own claim button: `text-sm px-4 py-3`.

    Anchored to the Start button's own class attribute via re.search, the
    way scenario_the_pwa_reuses_its_existing_log_action_and_only_once
    anchors to the done-listener body -- a whole-file substring check for
    'py-2'/'px-4' would have stayed green by coincidence (both strings
    appear elsewhere in the file regardless of what this button says)."""
    import re
    src = _read('components/programs_card.html')
    m = re.search(r"lesson-player:open'.*?class=\"([^\"]*)\">\s*Start session",
                  src, re.S)
    check(m, "the Start button is findable by its own markup, class attribute captured")
    classes = m.group(1) if m else ''
    check('py-3' in classes,
          "panel padding has to beat the PWA's own py-2.5 -- py-3 is the "
          "shellXl panel-tier convention, not py-2")
    check('px-4' in classes, "the panel-tier horizontal padding")
    check('text-sm' in classes, "the panel-tier text size")


def scenario_the_pwa_reuses_its_existing_log_action_and_only_once():
    """Same discipline as
    scenario_programs_page_never_posts_from_the_player_directly, applied to
    app.html's own idiom: the PWA must not grow a second path to POST
    api/programs/{id}/session. And the listener that turns
    lesson-player:done into that call has to be registered exactly once, at
    load -- not inside openSessionSheet, which runs on every row tap and
    would otherwise stack a fresh listener (and a fresh log write) per sheet
    opened, logging one finished session N times over."""
    import re
    src = _read('app.html')
    check(src.count("addEventListener('lesson-player:done'") == 1,
          "the done handler is registered exactly once, not per sheet-open")
    m = re.search(r"addEventListener\('lesson-player:done',.*?\}\);", src, re.S)
    check(m, "the handler body is findable")
    check('askProgramSession' in (m.group(0) if m else ''),
          "and it calls the EXISTING log action, not a new one")


def scenario_music_primitives_render():
    """Task 11: keyboard and fretboard join metronome as real pictures, each
    a named JS function taking the primitive's own validated params (keys /
    dots) and returning markup built from them -- not a caption, and not a
    hand-written block per key/fret."""
    src = _read('components/lesson_player.html')
    import re
    check(re.search(r'keyboardSvg\(keys\)\s*\{', src), "keyboardSvg(keys) exists")
    check(re.search(r'fretboardSvg\(dots, muted\)\s*\{', src), "fretboardSvg(dots, muted) exists")
    check("kind === 'keyboard'" in src, "the show dispatch has a keyboard branch")
    check("kind === 'fretboard'" in src, "the show dispatch has a fretboard branch")
    check("kind === 'metronome'" in src, "metronome is still wired (Task 6)")
    check('keyboardSvg(scene().primitive.keys)' in src,
          "the keyboard branch feeds the renderer its own validated keys")
    check('fretboardSvg(scene().primitive.dots, scene().primitive.muted)' in src,
          "the fretboard branch feeds the renderer its own validated dots AND "
          "its optional muted-string list")
    check('<svg' in src, "drawn, not described")


def scenario_keyboard_and_fretboard_are_renderable_shows():
    """Anchored to isRenderableShow's OWN body, not the whole file -- a bare
    "'keyboard' in src" would pass by coincidence off the x-if condition
    alone even if the allow-list itself were never updated."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'isRenderableShow\(s\)\s*\{([^}]*)\}', src, re.S)
    check(m, "isRenderableShow exists")
    body = m.group(1) if m else ''
    for kind in ('keyboard', 'fretboard'):
        check(f"'{kind}'" in body,
              f"{kind} is in the renderable-show allow-list itself, not just somewhere in the file")


def scenario_keyboard_geometry_is_computed_not_hand_drawn():
    """The brief's own constraint: key-to-x arithmetic in JS, never a
    per-key list. Scoped to keyboardSvg's own body (bounded by the next
    function in source rather than a brace-count guess, since the body
    itself contains object literals) -- one small geometry table applied
    by a loop, and the octave comes from parsing the note name, not a
    lookup keyed on the whole note string."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'keyboardSvg\(keys\)\s*\{(.*?)fretboardSvg\(dots, muted\)', src, re.S)
    check(m, "keyboardSvg body is findable, bounded by the next function")
    body = m.group(1) if m else ''
    check(body.count('GEOM') >= 2,
          "one geometry table drives both white- and black-key placement, "
          "not a literal rect per note name")
    check('parseInt' in body,
          "the octave comes from parsing the note name arithmetically, not a per-note lookup")


def scenario_fretboard_window_starts_at_the_lowest_fretted_dot():
    """The brief's own formula: window start = max(1, min(dot frets)) --
    never below the first fret, and anchored to whichever dot is lowest on
    the neck rather than a fixed position. Scoped to fretboardSvg's own
    body, bounded by the next function in source."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable, bounded by the next function")
    body = m.group(1) if m else ''
    check('Math.max(1' in body and 'Math.min(' in body,
          "the window start is max(1, min(dot frets)), computed, not a fixed fret 1")


def scenario_remaining_primitives_render():
    """Task 12: cards and counter join keyboard/fretboard/timer/metronome
    as real pictures -- every kind program_lessons.py's PRIMITIVES dict
    validates now draws something."""
    src = _read('components/lesson_player.html')
    check("kind === 'cards'" in src, "the show dispatch has a cards branch")
    check("kind === 'counter'" in src, "the show dispatch has a counter branch")
    import re
    m = re.search(r'isRenderableShow\(s\)\s*\{([^}]*)\}', src, re.S)
    check(m, "isRenderableShow exists")
    body = m.group(1) if m else ''
    for kind in ('cards', 'counter'):
        check(f"'{kind}'" in body, f"{kind} is in the renderable-show allow-list itself")
    check('<svg' in src, "drawn, not described")


def scenario_counter_taps_are_never_sent():
    """A rep count is a within-scene convenience, not a record -- true of
    every function that drives the paced count, not just a tap handler.
    bumpCounter() (tap-per-rep) is gone; counterTap() is the single entry
    point the dial's own @click.stop calls, and it fans out to
    startCounterPace()/pauseCounter()/tickCounter() -- all of them, plus
    speakCount(), are checked here rather than just the one function a tap
    directly reaches, because a rep now advances on ITS OWN TIMER as well
    as on a tap, and it would be easy to guard the tap and forget the
    interval it starts."""
    src = _read('components/lesson_player.html')
    import re
    for fn in ('counterTap', 'startCounterPace', 'pauseCounter', 'tickCounter', 'speakCount'):
        m = re.search(fn + r'\([^)]*\)\s*\{(.*?)\n        \},', src, re.S)
        check(m, f"{fn} exists")
        body = m.group(1) if m else ''
        for forbidden in ('fetch', 'localStorage', 'api', 'POST'):
            check(forbidden not in body, f"{fn} never {forbidden}s")


def scenario_card_flips_are_never_sent():
    """Same discipline as the counter, and explicit in the design brief: a
    flip is scene-local, never a record of what a kid did or did not
    know."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'toggleCardFlip\([^)]*\)\s*\{([^}]*)\}', src)
    check(m, "toggleCardFlip exists")
    body = m.group(1) if m else ''
    for forbidden in ('fetch', 'localStorage', 'api', 'POST'):
        check(forbidden not in body, f"a card flip never {forbidden}")


def scenario_cards_and_counter_taps_never_bubble_into_advance():
    """The scene area's own handler is `scene().type !== 'check' &&
    advance()` -- a bare `show` scene does not skip it the way `check`
    does, so every interactive tap INSIDE a cards/counter primitive (flip,
    prev, next, bump) has to carry .stop or it both does its own thing AND
    advances past the scene in the same motion -- the same bug class the
    check buttons already guard against (see
    scenario_check_taps_never_bubble_into_the_advance_handler above)."""
    src = _read('components/lesson_player.html')
    import re
    for handler in ('toggleCardFlip', 'cardPrev', 'cardNext', 'counterTap'):
        taps = re.findall(r'@click(\.stop)?="' + handler + r'\(\)"', src)
        check(len(taps) >= 1, f"{handler} is wired to a tap")
        check(all(t == '.stop' for t in taps),
              f"every {handler} tap must carry .stop, or it can bubble into "
              f"the scene area's own tap-to-advance handler")


def scenario_counter_is_paced_not_tap_per_rep():
    """Fix round 2's whole point: "you cannot stop after each rep and tap
    your phone." bumpCounter() (one tap = one rep) is gone outright, and
    the ONE tap that remains starts a self-advancing pace rather than
    requiring one tap per rep."""
    src = _read('components/lesson_player.html')
    check('bumpCounter' not in src,
          "tap-per-rep is gone, not merely joined by the new paced version")
    check('counterTap' in src and 'startCounterPace' in src and 'tickCounter' in src,
          "the paced-count functions exist")


def scenario_counter_first_tap_announces_immediately_then_paces_itself():
    """"One tap starts it. The count then advances on a cadence on its own"
    -- a fresh start (counterVal === 0) ticks right away, the same pattern
    startMetronome() already uses for its own first click, and every
    following tick is scheduled spr seconds apart via setInterval, not
    triggered by another tap."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'startCounterPace\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "startCounterPace exists")
    body = m.group(1) if m else ''
    check(re.search(r'if \(this\.counterVal === 0\) this\.tickCounter\(\);', body),
          "a fresh start (counterVal 0) fires the first rep immediately")
    check(re.search(r'this\.counterTimer = setInterval\(\(\) => this\.tickCounter\(\), spr \* 1000\);', body),
          "and every rep after that is scheduled on the primitive's own pace, not another tap")


def scenario_counter_pause_and_resume_are_both_reachable():
    """"Pause and resume must be possible." counterTap() is the single
    handler for start/pause/resume, so its own branching -- not a separate
    pause button -- is what has to prove both directions are reachable: a
    tap while running pauses (does not silently no-op or restart from
    zero), and a tap while paused-but-not-done resumes via the exact same
    startCounterPace() a fresh start uses (which is what makes a resume NOT
    fire an extra immediate tick -- counterVal is already > 0 there)."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'counterTap\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "counterTap exists")
    body = m.group(1) if m else ''
    check(re.search(r'if \(this\.counterRunning\) \{ this\.pauseCounter\(\); return; \}', body),
          "a tap while running pauses it")
    check('this.startCounterPace();' in body,
          "and a tap while stopped (paused, or not yet started) resumes/starts "
          "the SAME pace function -- not a second, divergent resume path")


def scenario_counter_reaching_target_stops_itself_without_a_tap():
    """"Finishing at target should be visible and should not require a
    tap." tickCounter() -- called only from the interval, never from a
    tap directly -- has to stop its own pace the instant counterVal
    reaches target, proven structurally rather than merely asserting
    pauseCounter exists somewhere in the file."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'tickCounter\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "tickCounter exists")
    body = m.group(1) if m else ''
    check(body.count('this.pauseCounter()') >= 1,
          "tickCounter stops the pace itself once target is reached")
    check(re.search(r'if \(this\.counterVal >= target\) this\.pauseCounter\(\);', body),
          "checked again right after incrementing, so the interval never "
          "fires one extra tick past target")


def scenario_counter_done_state_is_visible_without_a_tap():
    """The dial itself has to show completion -- a status line and a style
    change on the dial's own container -- not merely stop silently."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'counterDone\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "counterDone() exists")
    m2 = re.search(r'counterStatusText\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m2, "counterStatusText() exists")
    status_body = m2.group(1) if m2 else ''
    check('All done' in status_body, "a done state has its own honest label")
    check('tap to pause' in status_body.lower() and 'tap to resume' in status_body.lower(),
          "and running vs paused are told apart too, not merged into one label")
    block = re.search(r"kind === 'counter'\">(.*?)</template>", src, re.S)
    check(block, "the counter template block is findable")
    counter_markup = block.group(1) if block else ''
    check('counterDone()' in counter_markup,
          "the dial's own container styling reads counterDone(), so "
          "completion is visible without requiring a tap to discover it")
    check('counterStatusText()' in counter_markup,
          "and the status line is actually rendered, not just computed")


def scenario_counter_speech_never_breaks_the_counter():
    """"Never let a missing or throwing speech API break the counter."
    speakCount() has to wrap window.speechSynthesis entirely in try/catch,
    check for a voice before speaking (the HA wall panel plausibly has
    none), and never use a browser dialog -- the standing house rule."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'speakCount\(n\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "speakCount exists")
    body = m.group(1) if m else ''
    check('try {' in body and 'catch (e)' in body,
          "the whole speech call is wrapped -- a throwing speechSynthesis "
          "can never break the counter")
    check('speechSynthesis' in body, "it uses the browser's own speech API")
    check(re.search(r'!synth \|\| !\(synth\.getVoices\(\) \|\| \[\]\)\.length', body),
          "and it checks for an available voice before speaking -- falling "
          "back to the tick alone (no voices, e.g. the wall panel) rather "
          "than calling speak() into the void")
    check('SpeechSynthesisUtterance' in body, "it speaks via the standard utterance API")
    for banned in ('alert(', 'confirm(', 'prompt('):
        check(banned not in body, f"never a browser {banned} dialog (house rule)")


def scenario_counter_speech_cancels_before_speaking_so_it_never_backlogs():
    """A cadence the browser cannot keep up with (a fast seconds_per_rep, a
    long spoken number) must never queue a backlog of stale numbers trailing
    behind the tick and the dial -- cancel() has to run before every
    speak()."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'speakCount\(n\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "speakCount exists")
    body = m.group(1) if m else ''
    cancel_pos = body.find('synth.cancel()')
    speak_pos = body.find('synth.speak(')
    check(cancel_pos != -1 and speak_pos != -1, "both landmarks are present")
    check(cancel_pos < speak_pos,
          "cancel() runs before speak(), so a fast cadence never leaves a "
          "backlog of un-spoken numbers behind")


def scenario_counter_reads_its_own_seconds_per_rep_with_a_default():
    """`seconds_per_rep` has to actually reach the pace, not just exist in
    the schema -- read off the CURRENT scene's own primitive, with a
    same-file default for a primitive stored before the field existed."""
    src = _read('components/lesson_player.html')
    check('COUNTER_DEFAULT_SPR' in src,
          "a client-side default exists for an older stored primitive with "
          "no seconds_per_rep field at all")
    check('s.primitive.seconds_per_rep' in src,
          "and the current scene's own value is what actually drives the pace")


def scenario_stop_sound_and_enter_scene_both_clear_the_counters_pace():
    """"Make sure stopSound() also stops the count, and that leaving the
    scene resets it" -- the counter is scene-local and must never survive a
    scene change or a close, exactly like the countdown timer and the
    metronome it sits beside."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'stopSound\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "stopSound exists")
    stop_body = m.group(1) if m else ''
    check('this.counterTimer' in stop_body and 'clearInterval(this.counterTimer)' in stop_body,
          "stopSound() clears the counter's own interval, not just the timer/metronome")
    check('this.counterRunning = false' in stop_body,
          "and resets its running flag, so a re-entered scene never reads a stale 'running' state")
    m2 = re.search(r'enterScene\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m2, "enterScene exists")
    enter_body = m2.group(1) if m2 else ''
    check('this.counterVal = 0' in enter_body,
          "counterVal itself resets on every entry, as it always has")
    check('clearInterval(this.counterTimer)' in enter_body,
          "and enterScene() ALSO clears counterTimer directly -- defensive "
          "even though advance() already runs stopSound() first, so a "
          "fresh open() (which never calls stopSound() before its first "
          "enterScene()) cannot inherit a running interval from nowhere")


def scenario_fretboard_open_strings_are_structurally_separate_from_fretted_dots():
    """Fix round 1, finding 1, carried into the vertical rewrite (fix round
    2). An open string (fret 0) used to clamp into the SAME column as a
    fret-1 dot -- visually identical, though a completely different
    instruction (nothing fretted vs finger down at fret 1). The vertical
    diagram keeps the SAME guarantee through a different mechanism: an open
    mark draws in the head area above the nut (y < gy, structurally above
    every fret ROW, never inside one), not merely "left of the grid" as the
    old horizontal diagram had it. Scoped to fretboardSvg's own body,
    bounded by the next function in source (the same anchor
    scenario_fretboard_window_starts_at_the_lowest_fretted_dot already
    uses)."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable, bounded by the next function")
    body = m.group(1) if m else ''
    check('openDots' in body and 'frettedDots' in body,
          "open (fret 0) and fretted (fret > 0) dots are split before either is drawn")
    # v2.448.1: the literal `${openColor}` (`#2dd4bf`, dark-only -- it sat on
    # the transparent scene canvas, invisible once the surface behind it
    # turned light-theme near-white) became `stroke="currentColor"` plus the
    # themed `text-teal-400` token, same teal, now theme-aware; the ring
    # itself is still a hollow (`fill="none"`), structurally-distinct shape.
    check('fill="none" class="text-teal-400"' in body and 'stroke="currentColor" stroke-width="2.5"></circle>' in body,
          "an open string draws as a hollow ring -- structurally distinct from a solid fretted dot")
    m2 = re.search(r'openDots\.forEach\(d => \{([\s\S]*?)\}\);', body)
    check(m2, "the openDots.forEach block is findable")
    open_block = m2.group(1) if m2 else ''
    check('gy - 24' in open_block,
          "the open marker's y sits ABOVE the nut (gy is the nut's own y), "
          "never inside a fret row")
    check('d.finger' not in open_block,
          "and it carries no finger number -- there is no finger on an open "
          "string, unlike the old horizontal version which printed one anyway")


def scenario_fretboard_muted_strings_draw_as_x_above_the_nut():
    """The user's report named a third mark books use beside O: a muted
    (never-played) string draws as an X, same row as an open O. The
    contract could not express "muted" before this fix at all --
    program_lessons._valid_fretboard gained an optional `muted` list for
    exactly this (see test_program_lessons.py) -- so this is new behaviour,
    not a carried-over pin."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable")
    body = m.group(1) if m else ''
    check('mutedStrings' in body, "muted strings are resolved into their own list")
    m2 = re.search(r'mutedStrings\.forEach\(s => \{([\s\S]*?)\}\);', body)
    check(m2, "the mutedStrings.forEach block is findable")
    muted_block = m2.group(1) if m2 else ''
    check('gy - 24' in muted_block,
          "the muted marker sits in the SAME row as an open marker, above the nut")
    check(muted_block.count('<line') == 2,
          "an X is two crossing lines, drawn as two <line> elements")
    check('!dotStrings.has(s)' in body,
          "a string that already carries a real dot (open or fretted) is "
          "excluded from muted -- the dot wins rather than drawing both marks")


def scenario_fretboard_is_vertical_low_e_left_high_e_right():
    """The whole point of the fix, pinned structurally: strings are VERTICAL
    lines (not horizontal rows) and string 6 (low E) sits at a smaller x
    than string 1 (high E) -- the book convention the user asked for, never
    a mirror or a face-to-face view. Proven by the geometry formula itself
    (colOf), not merely by absence of the old STR_GAP-as-a-y-offset code,
    and independently re-verified by actually EXECUTING the function under
    Node against six same-fret dots (see the fix report's own table) --
    this is the source-level companion to that runtime proof."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable")
    body = m.group(1) if m else ''
    check(re.search(r'colOf\s*=\s*string\s*=>\s*gx\s*\+\s*\(6\s*-\s*string\)\s*\*\s*STR_GAP', body),
          "colOf maps string number to x as gx + (6-string)*STR_GAP -- string "
          "6 (low E) lands at the smallest x (leftmost), string 1 (high E) "
          "at the largest (rightmost)")
    check(re.search(r'for \(let col = 0; col < 6; col\+\+\) \{\s*const x = gx \+ col \* STR_GAP;', body),
          "strings are drawn as 6 VERTICAL lines (constant x per string, "
          "varying y), not horizontal rows")
    check(re.search(r'for \(let f = 0; f <= WIN; f\+\+\) \{\s*const y = gy \+ f \* FRET_H;', body),
          "frets are drawn as HORIZONTAL lines at increasing y -- running "
          "down the neck, not across it")


def scenario_fretboard_nut_is_thick_only_when_the_window_starts_at_fret_one():
    """Book convention: the nut is a thick line across the top ONLY when
    fret 1 is in view; a window that starts higher up the neck draws an
    ordinary fret line there instead and names the real fret beside it
    (`${start}fr`), which the OLD horizontal diagram printed unconditionally
    regardless of whether it was really the nut."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable")
    body = m.group(1) if m else ''
    check("const isNut = start === 1 && f === 0;" in body,
          "the nut is identified structurally, not merely styled")
    check('stroke-width="${isNut ? 5 : 1.5}"' in body,
          "and only the nut gets the thicker stroke")
    m2 = re.search(r'if \(start > 1\) \{([\s\S]*?)\n            \}', body)
    check(m2, "a start>1 branch exists for the position marker")
    check('${start}fr' in (m2.group(1) if m2 else ''),
          "and it is the ONLY place the position label is drawn -- never "
          "printed when the window already starts at the nut")


def scenario_fretboard_window_widens_to_fit_the_real_span():
    """Fix round 1, finding 1's other half: a realistic one-finger-per-fret
    run across six frets used to lose frets 5 and 6 to the same fixed
    5-fret column. The window now widens to the dots' own span first,
    only falling back to a cap past a sane width."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable")
    body = m.group(1) if m else ''
    check('BASE_WIN' in body and 'MAX_WIN' in body,
          "the window has both a normal-chord floor and a cap, not one fixed constant")
    check(re.search(r'span\s*=\s*Math\.min\(', body),
          "the window's span is computed from the dots' own fret range, not hard-coded")
    check('Math.max(BASE_WIN, span)' in body,
          "WIN grows to the real span (up to the cap) rather than staying fixed at the base width")


def scenario_fretboard_overflow_gets_a_visibly_approximate_marker():
    """Fix round 1, finding 1: past the widened window's cap, a dot used
    to clamp to the edge column and render exactly like a real, in-place
    dot -- a confidently-wrong chord diagram. It now draws dashed and
    amber, with its real fret number written alongside, so the
    approximation cannot be mistaken for a position."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable")
    body = m.group(1) if m else ''
    check('inWindow' in body, "in-window vs out-of-window dots are distinguished before drawing")
    check('stroke-dasharray' in body,
          "an out-of-window dot draws dashed, not as a solid filled circle")
    check('${d.fret}fr' in body,
          "an out-of-window dot's real fret number is written next to it, not hidden by the approximation")


def scenario_keyboard_signals_a_dropped_highlight_rather_than_hiding_it():
    """Fix round 1, finding 3. keys=['C2','G4'] used to render octaves 2-3
    and let G4 vanish with no signal at all. A capped window may still
    decide WHICH two octaves to keep; it may no longer stay silent about
    a highlighted key it then drew nothing for."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'keyboardSvg\(keys\)\s*\{(.*?)fretboardSvg\(dots, muted\)', src, re.S)
    check(m, "keyboardSvg body is findable, bounded by the next function")
    body = m.group(1) if m else ''
    check(re.search(r'dropped\s*=\s*notes\.filter\(', body),
          "a `dropped` count is computed from keys that fell outside the capped window")
    check('more' in body and '&#8594;' in body,
          "a dropped highlight leaves a visible marker (an arrow, a count), not a silent gap")


def scenario_cards_container_is_panel_aware_like_its_siblings():
    """Fix round 1, finding 2. keyboard/fretboard both bind
    `:class="panel ? 'max-w-2xl' : ...'"` on their own container; cards'
    outer box was the one primitive left on a static max-w-sm, so a long
    (up to the sanitizer's own 280-char MAX_TEXT) pair face in panel mode
    grew the card tall enough to push Prev/Next and the position dots
    against the footer. Scoped to the cards template block itself, bounded
    by the counter block that follows it, so this cannot pass by
    coincidence off keyboard/fretboard's OWN panel-aware classes
    elsewhere in the file."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r"kind === 'cards'\">(.*?)kind === 'counter'\"", src, re.S)
    check(m, "the cards template block is findable, bounded by the counter block that follows it")
    block = m.group(1) if m else ''
    check(":class=\"panel ? 'max-w-2xl' : 'max-w-sm'\"" in block,
          "the cards container binds the same panel-aware max-width its keyboard/fretboard siblings use")
    check('class="w-full max-w-sm' not in block,
          "the old STATIC max-w-sm is gone, not merely joined by a conflicting bound class")


def scenario_preview_flag_flows_from_open_to_state():
    """lesson-player:open's detail may carry `preview: true` -- open() has
    to take it as a third argument and store it on the component, or
    neither the footer's label nor finish()'s own guard (both read
    `this.preview`) would ever see it."""
    import re
    src = _read('components/lesson_player.html')
    check('$event.detail.preview' in src,
          "the window listener passes the detail's preview flag through")
    m = re.search(r'open\(w, lesson, preview\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "open() takes a third preview argument")
    body = m.group(1) if m else ''
    check('this.preview = !!preview' in body,
          "and stores it on the component, coerced to a real boolean")


def scenario_preview_footer_button_closes_instead_of_asking_to_log():
    """In preview the final-scene button must not promise a log write --
    it closes instead. The label expression now branches on `hostListens`
    (a host that announced a listener, vs one that did not) rather than
    `panel`; preview extends that same ternary rather than growing a
    second, independent one, and it is checked FIRST so it wins over the
    hostListens branch too (a preview opened on a page that DOES listen
    still just closes, never "Log it?"). Anchored to the same x-text
    attribute scenario_the_wall_button_does_not_promise_a_write already
    pins."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'x-text="isLast\(\) \? ([^"]*)"', src)
    check(m, "the footer button's label expression is findable")
    label = m.group(1) if m else ''
    check("(preview ? 'Close' : (hostListens ? 'Log it?' : 'Finish'))" in label,
          f"preview is checked first and closes rather than asking, got {label!r}")


def scenario_preview_marker_shows_in_the_header():
    """A preview must be visibly a preview while it plays -- a marker in
    the header, scoped to the header block (bounded by its own close
    button), not a bare substring anywhere in the file."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'<!-- header:.*?@click="close\(\)"', src, re.S)
    check(m, "the header block is findable, bounded by its own close button")
    header = m.group(0) if m else ''
    check('x-show="preview"' in header,
          "an element in the header is gated on the preview flag")
    check('streak' not in header.lower() and 'nothing gets saved' in header.lower(),
          "and says so in the player's own reassuring voice, not a bare technical label")


def scenario_preview_never_reaches_the_session_log_path():
    """A preview must never write anything, proven end to end rather than
    only at the button: finish() has to check `this.preview` and return
    BEFORE either the promptConfirm ask or the lesson-player:done dispatch
    -- both fire unconditionally for a real session, and neither has any
    OTHER gate that tells a preview apart from the real thing. onLessonDone
    (programs.html) and the done listener (app.html) both only ever act on
    that dispatch, so a dispatch that can never fire in preview is what
    keeps a preview from ever reaching either one -- proven here by the
    guard's POSITION in the source, not merely that it exists somewhere in
    the function."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'async finish\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "finish() is findable")
    body = m.group(1) if m else ''
    m2 = re.search(r'if\s*\(this\.preview\)\s*\{([^}]*)\}', body)
    check(m2, "finish() carries a dedicated preview guard")
    guard = m2.group(1) if m2 else ''
    check('return' in guard, "and the guard returns immediately")
    check('dispatchEvent' not in guard and 'promptConfirm' not in guard,
          "the guard itself neither asks nor dispatches -- it only closes")
    preview_pos = body.find('this.preview')
    confirm_pos = body.find('promptConfirm')
    dispatch_pos = body.find('dispatchEvent')
    check(preview_pos != -1 and confirm_pos != -1 and dispatch_pos != -1,
          "all three landmarks are present in finish()")
    check(preview_pos < confirm_pos,
          "the preview guard runs before the log ask can ever fire")
    check(preview_pos < dispatch_pos,
          "the preview guard runs before the done dispatch -- the one thing "
          "onLessonDone/app.html's listener react to -- can ever fire")


def scenario_the_lesson_editor_offers_a_play_tap():
    """The hand path's own preview (Task 2): a 'Play this' tap beside the
    existing edit/hide toggle for each rotation label, scoped to that
    summary row alone (bounded by the disclosure's own expanded-content
    div), not a bare substring anywhere on the page."""
    import re
    src = _read('programs.html')
    m = re.search(
        r'@click="toggleLesson\(p, ph, label\)".*?'
        r'<div class="mt-2 space-y-2" x-show="lessonOpen\[lessonKey\(p, ph, label\)\]"',
        src, re.S)
    check(m, "the summary row is findable, bounded by the disclosure's own expanded content")
    row = m.group(0) if m else ''
    check('@click="playLesson(p, ph, label)"' in row,
          "a Play tap sits beside the edit/hide toggle, in the same row")


def scenario_play_lesson_reads_storage_fresh_never_the_unsaved_draft():
    """'THAT slot's stored scenes' -- playLesson must not reuse lessonDraft
    (which may hold an edit not yet saved) or route through loadLesson
    (which would silently overwrite an in-progress edit the moment Play is
    tapped). It does its own fetch of the same GET the editor's own
    load/save already use, and opens in preview with an honest window
    stand-in built from what the editor actually has on screen."""
    import re
    src = _read('programs.html')
    m = re.search(r'async playLesson\(p, ph, label\)\s*\{(.*?)\n                \},', src, re.S)
    check(m, "playLesson is findable")
    body = m.group(1) if m else ''
    check('fetch(' in body, "it does its own fetch")
    check('lessonDraft' not in body, "never reusing the (possibly unsaved) draft")
    check('loadLesson(' not in body,
          "and never routes through loadLesson, which would overwrite an in-progress edit")
    check('preview: true' in body, "and opens the player in preview")
    check('this.slotSteps(ph, label)' in body,
          "the window stand-in carries this slot's own steps -- the fallback "
          "ladder's raw material when there is no stored script")
    check('unit.title' in body,
          "and the phase's CURRENT unit's real title, not a placeholder")


def scenario_slot_steps_matches_the_rotation_vs_flat_branch_the_readonly_view_uses():
    """The read-only steps/rotation blocks above already branch on
    `(ph.rotation || []).length` for a labeled slot vs `ph.steps` for an
    unlabeled one -- slotSteps has to resolve the identical two shapes, or
    a rotated phase's preview would show the wrong session's steps."""
    import re
    src = _read('programs.html')
    m = re.search(r'slotSteps\(ph, label\)\s*\{(.*?)\n                \},', src, re.S)
    check(m, "slotSteps is findable")
    body = m.group(1) if m else ''
    check('(ph.rotation || [])' in body, "it resolves the rotation array for a labeled slot")
    check("s.label || ''" in body, "matched on that exact label")
    check('ph.steps || []' in body, "and falls back to the flat phase steps when there is no label")


def scenario_sweep_report_play_tap_only_on_rows_that_wrote_something():
    """After a forced run, each row that produced a lesson should be
    playable; a skipped row -- including one skipped because it already
    had a lesson, which is the editor's own Play to offer, not this
    report's -- has nothing this tap promises to show. Scoped to the
    sweep-report's own row template, bounded by its closing tag."""
    import re
    src = _read('programs.html')
    m = re.search(
        r'<template x-for="\(slot, idx\) in \(sweepReport \? sweepReport\.slots : \[\]\)"'
        r'[\s\S]*?</template>', src)
    check(m, "the sweep-report row template is findable")
    block = m.group(0) if m else ''
    check('playSweepSlot(slot)' in block, "the block offers a Play tap at all")
    # The skipped row is a bare, childless div -- x-text sets its whole
    # content -- verified unchanged, so nothing tappable could have been
    # added to it; only its ORIGIN sibling could have gained the button.
    check('<div x-show="!slot.origin" class="text-amber-400" x-text="slot.skipped"></div>' in block,
          "the skipped row stays a bare label with nothing added to it")
    origin_pos = block.find('x-show="slot.origin"')
    skipped_pos = block.find('x-show="!slot.origin"')
    play_pos = block.find('playSweepSlot(slot)')
    check(-1 not in (origin_pos, skipped_pos, play_pos), "all three landmarks are present")
    check(origin_pos < play_pos < skipped_pos,
          "the Play tap sits inside the origin (wrote-something) row, before "
          "the skipped row begins")


def scenario_play_sweep_slot_fetches_by_program_id_and_previews():
    """The report entry itself carries no scenes and names a program only
    by TITLE -- not an id, and not guaranteed unique -- so playSweepSlot
    has to fetch through the `program_id` sweep_report now names, exactly
    the scoped GET the editor's own playLesson uses, and open in preview."""
    import re
    src = _read('programs.html')
    m = re.search(r'async playSweepSlot\(slot\)\s*\{(.*?)\n                \},', src, re.S)
    check(m, "playSweepSlot is findable")
    body = m.group(1) if m else ''
    check('slot.program_id' in body, "it fetches by the id sweep_report now names")
    check('fetch(' in body, "through a real fetch")
    check('preview: true' in body, "and opens the player in preview")


def scenario_sweep_report_entries_carry_a_program_id_for_the_play_tap():
    """The report otherwise names a program only by TITLE, so a client
    wanting to preview what a row wrote could not resolve which program to
    call GET /api/programs/{id}/lesson on. Checked by source, the same way
    this file already checks a backend function it does not execute
    (scenario_the_wall_reads_the_slot_key_off_the_window, above) rather
    than re-running the whole sweep fixture machinery
    test_program_lessons.py already owns end to end."""
    import inspect
    from services import program_lessons
    src = inspect.getsource(program_lessons.sweep_report)
    check("'program_id': row.get('id')" in src,
          "each report entry carries the program's real id")


# ── Family Day / calendar: the Start tap in the shared details dialog ──────
#
# The lesson player was reachable from Programs, the wall's programs card
# and the PWA -- but not from the surface the household actually looks at
# most, because the Family Day card and the calendar both answer a tap
# through _typedDetailsHtml (family_calendar.html), the ONE shared builder
# for a typed event's details, and that builder offered no way to start a
# practice session it was already describing in full.


def scenario_family_calendar_offers_a_start_tap_for_practice():
    """The one surface the design brief calls out by name: the shared
    event-details dialog (family_calendar.html's _typedDetailsHtml) showed
    a session's unit/steps/progression/milestone in full and offered no
    way to start it -- on the Family Day card, the calendar grid, and the
    wall's own calendar card alike, since all three open the identical
    dialog through the identical builder."""
    import re
    src = _read('components/family_calendar.html')
    m = re.search(r'if \(props\.isPractice\) \{(.*?)\n    \}', src, re.S)
    check(m, "the isPractice branch is findable")
    body = m.group(1) if m else ''
    check('id="modal-practice-start"' in body,
          "a Start tap lives inside the shared builder's own practice branch")
    check('Start session' in body, "labelled the same as every other Start tap")
    check(re.search(r'\(w\.program_id && !w\.logged\)\s*\?', body),
          "offered only when there is a program to ask and nothing logged yet")


def scenario_start_tap_is_wired_from_the_real_practice_payload():
    """The button _typedDetailsHtml draws carries no handler of its own --
    it is a plain button with an id, wired in _openEventDetails after the
    innerHTML swap, the same pattern modal-config-btn already uses just
    above it. Proven by finding the wiring itself, not merely the id --
    a bare substring for 'modal-practice-start' would pass even if the id
    were only ever drawn and never read back."""
    import re
    src = _read('components/family_calendar.html')
    m = re.search(r"const typedContainer = document\.getElementById\('modal-typed-container'\);"
                  r"(.*?)const descContainer", src, re.S)
    check(m, "the wiring site between the typed container and the "
             "description container is findable")
    wiring = m.group(1) if m else ''
    check("getElementById('modal-practice-start')" in wiring,
          "the button is looked up by the same id it was drawn with")
    check(re.search(r"startBtn\.onclick = \(\) => _startPracticeSession\(props\.practice\)", wiring),
          "and wired to open with the REAL practice payload, not a copy")


def scenario_start_practice_session_reuses_the_two_shapes_its_siblings_already_use():
    """Not a third request shape: the same panel/signed-in split
    programs.html's loadWindowLesson and programs_card.html's wall variant
    already use, reused rather than invented -- a panel reads the
    scenes-only WALL projection with no auth header, everywhere else reads
    the full row with whatever member token this browser holds."""
    import re
    src = _read('components/family_calendar.html')
    m = re.search(r'async function _startPracticeSession\(w\)\s*\{(.*?)\n\}', src, re.S)
    check(m, "_startPracticeSession is findable")
    body = m.group(1) if m else ''
    check("get('panel') === 'true'" in body,
          "panel-ness is read the same way lesson_player.html itself reads it")
    check('api/programs/${w.program_id}/lesson-scenes?' in body,
          "the panel branch reads the scenes-only WALL projection")
    check('api/programs/${w.program_id}/lesson?' in body,
          "the signed-in branch reads the full row")
    for key in ('phase_name', 'unit_n', 'session_label'):
        check(key in body, f"the slot key is whole -- {key} is part of it")
    check('chauffeur_member_token' in body,
          "the signed-in branch carries whatever member token this "
          "browser holds, the same key programs.html's authHeaders() reads")
    check('X-Member-Token' in body,
          "over the same header programs.html sends it in")
    check("method: 'POST'" not in body and 'method:"POST"' not in body,
          "this fetch only ever reads -- POSTing a session is the HOST's "
          "job, never this dialog's, and never the player's")


def scenario_start_practice_session_never_blocks_the_tap_on_a_failed_fetch():
    """The arc's standing rule: the player never blocks practice. A failed
    or empty fetch must still open the player, on its own fallback
    ladder -- proven by POSITION, not merely that a try/catch exists
    somewhere in the function: the dispatch has to sit textually AFTER
    the catch, so nothing inside the try/catch can prevent it from
    running."""
    import re
    src = _read('components/family_calendar.html')
    m = re.search(r'async function _startPracticeSession\(w\)\s*\{(.*?)\n\}', src, re.S)
    check(m, "_startPracticeSession is findable")
    body = m.group(1) if m else ''
    check('try {' in body and 'catch (e)' in body, "the fetch is guarded")
    catch_pos = body.rfind('catch (e)')
    dispatch_pos = body.find("dispatchEvent(new CustomEvent('lesson-player:open'")
    check(catch_pos != -1 and dispatch_pos != -1, "both landmarks are present")
    check(catch_pos < dispatch_pos,
          "the dispatch sits after the catch, so a failed fetch still opens "
          "the player -- on lesson: null, its own fallback ladder")


def scenario_start_practice_session_closes_the_dialog_before_dispatching():
    """"Close the details dialog when the player opens, so the two are not
    stacked" -- proven by position, the same discipline
    scenario_preview_never_reaches_the_session_log_path already applies to
    finish()'s own guard."""
    import re
    src = _read('components/family_calendar.html')
    m = re.search(r'async function _startPracticeSession\(w\)\s*\{(.*?)\n\}', src, re.S)
    check(m, "_startPracticeSession is findable")
    body = m.group(1) if m else ''
    close_pos = body.find('_closeEventModal()')
    dispatch_pos = body.find("dispatchEvent(new CustomEvent('lesson-player:open'")
    check(close_pos != -1 and dispatch_pos != -1, "both landmarks are present")
    check(close_pos < dispatch_pos,
          "the details dialog closes before the player opens, so the two "
          "are never stacked")


def scenario_start_practice_session_carries_the_practice_windows_own_unit_n():
    """The slot key needs unit_n, and it does not have to be minted here:
    practice_windows already emits it (services/programs.py) and it rides
    the payload all the way to this dialog -- family_day.py's block carries
    `practice: ev.get('practice') or None` and the calendar's own event
    mapper carries `practice: ev.practice || null`, both the WHOLE window
    dict, never a hand-picked subset -- so _startPracticeSession can read
    it straight off what the dialog already holds, with no backend change
    required."""
    import re
    from services import programs
    import inspect
    src = inspect.getsource(programs.practice_windows)
    check("'unit_n': int(unit.get('n') or 0)" in src,
          "the practice window carries its own rung")
    check("'logged': _already_logged(row, day)" in src,
          "and whether a session for it already happened")
    fd_src = io.open(os.path.join(HERE, 'services', 'family_day.py'),
                     encoding='utf-8').read()
    check("'practice': ev.get('practice') or None" in fd_src,
          "the Family Day card's own block carries the WHOLE practice payload")
    cal_src = _read('components/family_calendar.html')
    m = re.search(r'async function _startPracticeSession\(w\)\s*\{(.*?)\n\}', cal_src, re.S)
    check(m, "_startPracticeSession is findable")
    check('unit_n: w.unit_n' in (m.group(1) if m else ''),
          "and the opener reads it straight off the payload, not a second lookup")


# ── The wall's dishonest confirmation, fixed ────────────────────────────
#
# finish() used to ask "Log this session?" on every non-panel host, whether
# or not anybody was listening for lesson-player:done -- home.html opened
# as an ordinary page (no ?panel=true) confirmed a write that was never
# coming. Adding a Start tap to Family Day makes that path front-and-centre
# (home.html hosts both the Family Day card and the wall's calendar card),
# so the ask now gates on an explicit announcement from the host instead.


def scenario_host_listen_flag_is_explicit_not_dom_sniffed():
    """The player cannot reliably discover whether `window` carries a
    `lesson-player:done` listener -- there is no introspection for a
    CustomEvent's listeners, and programs.html's own listener is an Alpine
    directive (`@lesson-player:done.window`), not even a bare
    addEventListener a script could search for. So a host has to announce
    itself, the same way window.chfBase and the other chf-prefixed globals
    already announce a capability of the page to whatever shared component
    reads it."""
    import re
    src = _read('components/lesson_player.html')
    check('hostListens: !!window.chfHasLessonDoneListener,' in src,
          "the flag is read once, explicitly, at construction -- the same "
          "way `panel` is read just above it")
    m = re.search(r'async finish\(\)\s*\{(.*?)\n        \},', src, re.S)
    check(m, "finish() is findable")
    check('this.hostListens' in (m.group(1) if m else ''),
          "and finish() actually reads what it announces")


def scenario_hosts_that_log_a_session_announce_they_listen():
    """programs.html and app.html each turn lesson-player:done into a real
    write (onLessonDone / askProgramSession) -- both have to set the flag
    lesson_player.html's finish() reads, right next to their own listener,
    or the honest fix just moves the lie from 'always asks on non-panel'
    to 'never asks at all, even where a write really happens'."""
    for page in ('programs.html', 'app.html'):
        src = _read(page)
        check('window.chfHasLessonDoneListener = true' in src,
              f"{page} announces that it listens")


def scenario_hosts_with_no_log_action_never_announce():
    """home.html and calendar.html own no session-log action to call --
    neither may claim to listen, or finish() would ask a question with
    nothing behind it again, just relocated to a different host."""
    for page in ('home.html', 'calendar.html'):
        src = _read(page)
        check('window.chfHasLessonDoneListener = true' not in src,
              f"{page} must never announce a listener it does not have")
        check("addEventListener('lesson-player:done'" not in src,
              f"{page} really has no listener to announce")


# ── Light-theme legibility (v2.448.1) ───────────────────────────────────
#
# A real user's report: the PWA in light theme showed white text on a
# near-white background -- unreadable. Root cause was `text-white`, a
# LITERAL Tailwind color that never runs through static/theme.css's
# `[data-theme]` remap the way `bg-gray-*`/`text-gray-*` do. Confirmed by a
# real render (Jinja + compiled tailwind-app.css + Alpine + headless
# Chromium, both [data-theme] values, WCAG contrast measured against the
# actual composited background) rather than by reading source: every scene
# type and every `show` primitive was audited, not only the reported spot.
#
# tools/tailwind/tailwind.app.config.js documents the intended contract in
# its own header comment: "white and black are deliberately NOT tokenized:
# text-white on a solid accent fill must stay white in both themes.
# Surface-level primary text uses text-gray-100 instead." The nine
# `text-white` uses split exactly along that line -- seven were surface
# text sitting on the themed `bg-gray-950/95` root (or a nested
# `bg-gray-800`/`bg-teal-900/40` tile that inverts with it) and moved to
# `text-gray-100`; two sit on `bg-teal-700`/`bg-blue-600`, both
# theme-invariant solid fills (identical rgb in light and dark per
# static/theme.css), and correctly stayed `text-white`.


def scenario_text_white_survives_only_on_invariant_accent_fills():
    """The fix's central claim, checked structurally: every remaining
    literal `text-white` in the file sits in a class list that ALSO carries
    one of the two theme-invariant solid accent fills this component uses
    (`bg-teal-700`, `bg-blue-600` -- identical rgb in both
    static/theme.css themes, confirmed by rendering both and measuring). A
    `text-white` anywhere else is exactly the reported bug: surface text
    that stops being visible the instant the surface itself inverts."""
    import re
    src = _read('components/lesson_player.html')
    classes = re.findall(r'class="([^"]*\btext-white\b[^"]*)"', src)
    # The COUNT is not the rule and never was -- the rule is that every
    # one of them sits on an invariant fill, checked below. A primary
    # action added later (the offer's accept chip) legitimately grows this
    # list; a `text-white` on the themed surface is what must not.
    check(len(classes) >= 2,
          f"the invariant-fill text-white uses should still be here, "
          f"found {len(classes)}: {classes}")
    for cls in classes:
        check('bg-teal-700' in cls or 'bg-blue-600' in cls,
              f"text-white must sit beside an invariant solid fill, got {cls!r}")


def scenario_surface_text_uses_the_gray_100_token_not_literal_white():
    """The other half of the same claim: the seven elements that USED to be
    `text-white` on the themed surface now read `text-gray-100` -- the
    exact token `app.html`'s own <body> uses for surface-level primary text
    (`<body class="bg-gray-950 text-gray-100" ...>`), and the token
    tailwind.app.config.js's header comment names as `text-white`'s
    themed replacement. Anchored to each element's own x-text/x-show so
    this cannot pass by a bare word-count coincidence."""
    src = _read('components/lesson_player.html')
    import re
    anchors = [
        (r'text-gray-100[^"]*"[^>]*x-text="\(w \|\| \{\}\)\.title', 'header title'),
        (r'text-gray-100[^"]*"[^>]*x-text="sayText\(\)"', 'say beat text'),
        (r'text-gray-100[^"]*"[^>]*x-text="scene\(\)\.text"', 'do beat text'),
        (r'text-gray-100[^"]*"[^>]*x-text="scene\(\)\.ask"', 'check ask text'),
        (r'text-gray-100 text-center" x-text="cardFace\(\)"', 'card face text'),
        (r'text-gray-100[^"]*"[^>]*x-text="counterVal"', 'counter dial number'),
        (r'text-gray-100"[^>]*x-text="fmtClock\(timeLeft\)"', 'countdown ring readout'),
    ]
    for pattern, label in anchors:
        check(re.search(pattern, src), f"{label} should read text-gray-100")


def scenario_check_button_active_state_stays_theme_invariant():
    """Fix round finding: the "Got it" button's base fill (`bg-teal-700`) is
    theme-invariant, but its OLD `:active` press state (`bg-teal-800`) was
    not -- 800 is in static/theme.css's inverting tier, and in light theme
    it resolves to a near-white mint (rgb(153,246,228)), which is exactly
    as unreadable under white text as the reported bug, just for the
    instant a finger is actually down. `active:brightness-90` darkens
    whatever the invariant base fill already is, by a fixed multiplier, so
    it can never depend on which theme is active."""
    src = _read('components/lesson_player.html')
    check('bg-teal-800' not in src,
          "the light-breaking active state must be gone outright, not just joined by a fix")
    import re
    check(re.search(r'bg-teal-700 text-white font-bold active:brightness-90', src),
          "the Got it button presses via a theme-invariant brightness shift, not a shade swap")


def scenario_metadata_text_is_gray_400_not_gray_500():
    """Measured, not assumed: text-gray-500 (this component's OLD metadata
    color) renders at 4.18:1 against the true bg-gray-950 root in DARK
    theme alone -- under even this file's own relaxed 4.5 floor for
    non-bold body text, and the file's OWN neighboring comment already
    named text-gray-400 as the intended metadata color
    ("docs/ui_design_guide.md (\"metadata text-[11px] ... text-gray-400\")")
    before this fix made the code match it. text-gray-400 measures 7.85:1
    dark / 7.23:1 light on the same real background. Five spots carried the
    stale color: the session-label subtitle, the cards position counter,
    the counter's "of N" caption, the metronome bpm label, and the footer
    origin label."""
    src = _read('components/lesson_player.html')
    check('text-gray-500' not in src,
          "no text-gray-500 should remain anywhere in the component")
    import re
    anchors = [
        (r'text-gray-400 truncate"[^>]*x-text="\(w \|\| \{\}\)\.session_label"', 'session label'),
        (r'text-gray-400"[^>]*x-text="\(cardIdx \+ 1\)', 'cards position counter'),
        (r"text-gray-400\"[^>]*x-text=\"'of ' \+", 'counter "of N" caption'),
        (r'text-gray-400"[^>]*x-text="metroBpm\(\) \+', 'metronome bpm label'),
        (r'font-semibold text-gray-400"[^>]*x-text="originLabel\(\)"', 'footer origin label'),
    ]
    for pattern, label in anchors:
        check(re.search(pattern, src), f"{label} should read text-gray-400")


def scenario_svg_elements_on_the_transparent_canvas_never_hardcode_a_dark_only_color():
    """Every hardcoded colour drawn on the SVG's own TRANSPARENT canvas --
    which shows whatever the themed scene-area background actually is --
    used a value tuned only for dark: `rgba(255,255,255,X)` structural
    lines (invisible past ~1.1:1 once the surface behind them turns
    near-white) and a literal `#2dd4bf`/`#94a3b8`/`#f59e0b` for the
    countdown ring, the open-string ring, the position label and the
    out-of-window "ghost" marks. Measured: the ring's progress stroke alone
    fell from a passing 10.64:1 in dark to a failing 1.74:1 in light. Fixed
    by `stroke`/`fill="currentColor"` plus a themed `text-*` class (the
    SAME tokens already proven correct elsewhere in this file, e.g. the
    kicker's own `text-teal-400`) rather than a hand-picked literal, so
    each one resolves through static/theme.css exactly like any other
    themed text in the component."""
    src = _read('components/lesson_player.html')
    # The countdown ring is plain template markup (not JS-generated), so a
    # file-wide check is safe for its two literals -- neither one has any
    # OTHER legitimate use left in the file.
    for banned, why in [
        ('rgba(255,255,255,0.10)', 'countdown ring track'),
        ('stroke="#2dd4bf"', 'countdown ring progress / fretboard open-string ring'),
        ('fill="#94a3b8"', 'fretboard position label'),
    ]:
        check(banned not in src, f"{why} must not hardcode a dark-only literal ({banned!r})")
    import re
    # fretboardSvg's own body, scoped -- rgba(255,255,255,0.35) legitimately
    # SURVIVES elsewhere in the file (the keyboard's self-contained black-key
    # border, see the next scenario), so string/fret-line removal has to be
    # checked here rather than file-wide.
    fret_body_m = re.search(r'fretboardSvg\(dots, muted\)\s*\{(.*?)cardFace\(', src, re.S)
    check(fret_body_m, "fretboardSvg body is findable")
    fret_body = fret_body_m.group(1) if fret_body_m else ''
    check('rgba(255,255,255,0.35)' not in fret_body,
          "fretboard string lines must not hardcode a dark-only literal")
    check('rgba(255,255,255,0.5)"' not in fret_body,
          "fretboard fret lines must not hardcode a dark-only literal")
    # fretboardSvg's local `ghost`/`openColor` consts existed ONLY to carry
    # these now-removed literals -- their disappearance is proof the
    # removal was structural, not a second, still-hardcoded copy elsewhere.
    check('ghost' not in fret_body,
          "no leftover reference to the removed 'ghost' constant")
    check('openColor' not in fret_body,
          "no leftover reference to the removed 'openColor' constant")
    # And the replacements are the themed tokens, not a second literal:
    check(fret_body.count('class="text-gray-400/70"') >= 2,
          "both the string-line loop and the fret-line loop use the themed line color")
    check('class="text-teal-400"' in fret_body, "the open-string ring uses the themed teal token")
    check('class="text-slate-400"' in fret_body, "the position label uses the themed slate token")
    check(fret_body.count('class="text-amber-400"') >= 3,
          "the out-of-window ghost ring + finger number + fret label all use the themed amber token")


def scenario_self_contained_svg_shapes_keep_their_literal_fills():
    """The flip side of the previous scenario, so the fix cannot overreach:
    a shape that paints its OWN fully opaque area -- a piano key, a
    fretted-dot fill, the finger number printed on top of it, a muted
    string's X -- never depends on the themed scene background showing
    through, because nothing of that background is visible through an
    opaque shape. These stay literal, unmeasured-by-theme constants on
    purpose; changing them would be motion with no legibility reason
    behind it. slate-500 (`#64748b`, the muted-X stroke) is additionally
    theme-INVARIANT in static/theme.css itself (identical rgb both
    themes), independently confirming it never needed the fix at all."""
    src = _read('components/lesson_player.html')
    for literal, why in [
        ("accent = '#2dd4bf'", 'keyboard highlighted-key fill (opaque key shape)'),
        ("'#f1f5f9'", 'keyboard white-key fill (opaque key shape)'),
        ("'#1e293b'", 'keyboard black-key fill (opaque key shape)'),
        ('stroke="rgba(255,255,255,0.35)"', "the black key's own border, painted "
                                             "on its OWN opaque fill, not the scene background"),
        ("solid = '#0f766e'", 'fretboard fretted-dot fill (opaque dot shape)'),
        ('fill="#fff"', 'the finger number printed on the opaque dot fill'),
        ('stroke="#64748b"', 'the muted-string X (theme-invariant slate-500 besides)'),
    ]:
        check(literal in src, f"{why} should still be the literal constant, unchanged")


# --- Argyle's voice inside the session ----------------------------------


def scenario_the_speech_wrapper_can_never_break_a_scene():
    """A voiceless device -- a wall panel with no speech engine, a browser
    that throws on getVoices -- still runs the whole lesson. Speech is an
    enhancement, and the wrapper is the only place that promise is kept.

    Two functions, one door: `say` decides WHERE a line goes (this room's
    speaker, or this device), `sayLocal` is the browser wrapper itself.
    Everything in-beat calls the second directly, because a cue at 0:30
    cannot afford a round trip; see the room-voice scenarios below."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        say\(text, lang, tone\) \{(.*?)\n        \},', src, re.S)
    check(m, "say(text, lang, tone) exists as the one session-level door")
    check('this.muted' in (m.group(1) if m else ''),
          "and the mute tap silences it at that door")
    m = re.search(r'\n        sayLocal\(text, lang, tone\) \{(.*?)\n        \},',
                  src, re.S)
    check(m, "sayLocal(text, lang, tone) is the browser wrapper")
    body = m.group(1) if m else ''
    check('try {' in body and 'catch' in body,
          "and everything it touches is inside a try/catch")
    check('speechSynthesis' in body, "it speaks through the browser's own engine")
    check('.cancel()' in body,
          "cancelling first, so a new line never queues behind a stale one")
    check('this.muted' in body,
          "and it is silenced too, since in-beat lines reach it directly")


def scenario_a_scene_speaks_its_own_line_on_entry():
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        enterScene\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "enterScene body is findable")
    body = m.group(1) if m else ''
    check('s.speak' in body, "a scene's spoken line is said when it opens")
    check('s.tone' in body and 's.speak_lang' in body,
          "with its own voice and tone, not a fixed one")
    check('s.chime' in body, "and its chime, where the scene asks for one")


def scenario_the_mute_tap_is_reachable_and_gates_the_voice():
    """One tap silences Argyle for the session without touching a scene --
    a lesson in a quiet house is the same lesson."""
    src = _read('components/lesson_player.html')
    check('muted: false' in src, "the flag is session-local state")
    check('toggleMute()' in src, "and a tap flips it")
    import re
    m = re.search(r'toggleMute\(\) \{(.*?)\},', src, re.S)
    body = m.group(1) if m else ''
    for forbidden in ('fetch', 'localStorage', 'api'):
        check(forbidden not in body,
              f"muting is not a preference anyone records -- no {forbidden}")


def scenario_the_greeting_is_the_players_own_words_never_the_models():
    """The one thing a model never writes: how Argyle addresses the person
    in front of it. Template strings off the window's own fields, so there
    is no call to fail and nothing to screen."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'greetingLine\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "greetingLine() exists")
    body = m.group(1) if m else ''
    check('member_name' in body and 'title' in body,
          "built from the window's member and program")
    for forbidden in ('fetch', 'scenes', 'lesson'):
        check(forbidden not in body,
              f"and never from {forbidden} -- a greeting is not model text")
    m2 = re.search(r'sendOffLine\(\) \{(.*?)\n        \},', src, re.S)
    check(m2, "sendOffLine() exists too")
    check('fetch' not in (m2.group(1) if m2 else ''), "same rule on the way out")


def scenario_a_preview_is_never_greeted():
    """A preview plays the scenes and ends in nothing. Being welcomed to a
    session nobody is having is the one place the marker chip is not
    enough."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        open\(w, lesson, preview\) \{(.*?)\n        \},', src, re.S)
    check(m, "open() body is findable")
    body = m.group(1) if m else ''
    check('this.preview' in body and 'greetingLine' in body,
          "the greeting is spoken from open()")
    check(re.search(r'if \(!this\.preview\)[^\n]*greetingLine', body),
          f"and only when this is a real session, got {body!r}")


def scenario_stopping_the_sound_stops_the_voice_too():
    """Speech is exactly as scene-local as the metronome: advancing,
    closing or finishing must not leave a sentence still being read into
    a room nobody is in."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        stopSound\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "stopSound body is findable")
    body = m.group(1) if m else ''
    check('speechSynthesis' in body and 'cancel' in body,
          f"and it cancels whatever is being spoken, got {body!r}")


def scenario_the_chime_shares_the_players_one_audio_context():
    """The counter and the metronome already share playClick(); a chime is
    the same short Web Audio figure at a different pitch, and a third
    implementation of it would be the second time this file learned that
    lesson."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'playChime\(kind\) \{(.*?)\n        \},', src, re.S)
    check(m, "playChime(kind) exists")
    body = m.group(1) if m else ''
    check('this.audio' in body, "on the player's own AudioContext")
    check('this.muted' in body, "and the mute tap silences it too")
    check("'fanfare'" in body, "with a two-note figure for the fanfare")


# --- cues: what Argyle says mid-drill -----------------------------------


def _cue_scheduler_under_node():
    """The cue-due predicate, extracted and actually RUN.

    Timing is the one thing reading a function cannot verify -- the
    fretboard round taught this file that lesson about geometry and a
    scheduler is the same class of thing. `cuesDueAt` is deliberately pure
    (no `this`, no clock of its own) precisely so it can be lifted out and
    driven by a fake one here.
    """
    import json
    import os
    import re
    import shutil
    import subprocess
    import tempfile
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return None
    src = _read('components/lesson_player.html')
    m = re.search(r'\n        cuesDueAt\(cues, elapsed, fired\) \{(.*?)\n        \},',
                  src, re.S)
    check(m, "cuesDueAt(cues, elapsed, fired) is findable and pure")
    body = m.group(1)
    check('this.' not in body,
          f"and it stays pure -- no player state inside it, got {body!r}")
    harness = r'''
const CUES = [{at: 0, say: 'Go'}, {at: 10, count: true},
              {at: 30, say: 'Switch sides'}, {at: 30, chime: true},
              {at: 55, say: 'Ten to go'}];
const out = {};
// A whole beat, second by second, exactly once each -- the order they
// fire in and the second each one lands on.
let fired = 0;
const order = [];
for (let t = 0; t <= 60; t++) {
    const due = cuesDueAt(CUES, t, fired);
    due.forEach(c => order.push([t, c.say || (c.count ? 'COUNT' : 'CHIME')]));
    fired += due.length;
}
out.order = order;
out.total = fired;
// The same beat, but the clock jumps 0 -> 40 (a tab that was backgrounded,
// a slow device): everything owed by 40 comes at once, nothing is skipped.
let f2 = 0;
const jump = cuesDueAt(CUES, 40, f2).map(c => c.at);
out.jump = jump;
// And re-entering a beat from zero owes everything again.
out.replay = cuesDueAt(CUES, 60, 0).length;
// Nothing is ever owed twice.
out.afterAll = cuesDueAt(CUES, 60, CUES.length).length;
console.log(JSON.stringify(out));
'''
    scratch = tempfile.mkdtemp(prefix='chauffeur_cues_')
    path = os.path.join(scratch, 'run.mjs')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('function cuesDueAt(cues, elapsed, fired) {' + body + '\n}\n'
                + harness)
    proc = subprocess.run([node, path], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=60)
    check(proc.returncode == 0, f"the scheduler threw:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def scenario_cues_fire_once_each_in_order():
    got = _cue_scheduler_under_node()
    if got is None:
        return
    check([row[0] for row in got['order']] == [0, 10, 30, 30, 55],
          f"each cue lands on its own second, got {got['order']}")
    check([row[1] for row in got['order']]
          == ['Go', 'COUNT', 'Switch sides', 'CHIME', 'Ten to go'],
          f"in the order the script wrote them, got {got['order']}")
    check(got['total'] == 5, f"and exactly once each, got {got['total']}")
    check(got['afterAll'] == 0, "a finished beat owes nothing more")


def scenario_a_clock_that_jumps_still_owes_every_cue():
    """A backgrounded tab, a locked phone, a slow board: the clock comes
    back late. Cues are owed by elapsed time, never by a chain of
    setTimeouts that a stalled tab silently swallows, so everything due
    arrives together rather than being skipped."""
    got = _cue_scheduler_under_node()
    if got is None:
        return
    check(got['jump'] == [0, 10, 30, 30],
          f"everything owed by 0:40 arrives at 0:40, got {got['jump']}")
    check(got['replay'] == 5,
          f"and re-entering the beat owes all of them again, got {got['replay']}")


def scenario_the_cue_scheduler_rides_the_beats_own_timer():
    """One clock. The countdown ring, the metronome and the cues cannot
    disagree about how far into a beat we are if only one of them is
    counting."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        startTimer\(secs\) \{(.*?)\n        \},', src, re.S)
    check(m, "startTimer body is findable")
    body = m.group(1) if m else ''
    check('fireCuesTo' in body,
          f"the timer's own tick is what fires cues, got {body!r}")
    check('setTimeout' not in body,
          "never a second, drifting chain of timeouts beside it")
    m2 = re.search(r'\n        enterScene\(\) \{(.*?)\n        \},', src, re.S)
    check('startCues' in (m2.group(1) if m2 else ''),
          "and a do-beat arms its cues on entry")


def scenario_cues_never_outlive_their_scene():
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        stopSound\(\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('this.cues = []' in body and 'cuesFired' in body,
          f"stopSound forgets the beat's cues, got {body!r}")


def scenario_a_cue_stores_nothing():
    src = _read('components/lesson_player.html')
    import re
    for fn in ('startCues', 'fireCuesTo', 'runCue'):
        m = re.search(r'\n        ' + fn + r'\([^)]*\) \{(.*?)\n        \},',
                      src, re.S)
        check(m, f"{fn} exists")
        body = m.group(1) if m else ''
        for forbidden in ('fetch', 'localStorage', 'api'):
            check(forbidden not in body,
                  f"a cue is said and forgotten -- {fn} must not {forbidden}")


# --- pitch, and the tuner -----------------------------------------------


def _pitch_under_node():
    """The pitch detector, driven by synthesized sound rather than read.

    A detector that is merely plausible-looking is worthless: it either
    lands on the note or it does not, and the only way to know is to
    generate a wave whose frequency is already known and ask. Same lesson
    the fretboard round taught this file about geometry, one sense over.
    """
    import json
    import os
    import re
    import shutil
    import subprocess
    import tempfile
    node = shutil.which('node')
    if not node:
        print('  skip  node is not installed')
        return None
    src = _read('components/lesson_player.html')
    fns = {}
    for name, sig in [('autoCorrelate', r'autoCorrelate\(buf, sampleRate\)'),
                      ('hzToNote', r'hzToNote\(hz\)'),
                      ('peaksToBpm', r'peaksToBpm\(times\)')]:
        m = re.search(r'\n        ' + sig + r' \{(.*?)\n        \},', src, re.S)
        check(m, f"{name} is findable")
        body = m.group(1)
        check('this.' not in body,
              f"{name} must stay pure so it can be run here, got {body!r}")
        fns[name] = 'function ' + name + '(' \
            + {'autoCorrelate': 'buf, sampleRate', 'hzToNote': 'hz',
               'peaksToBpm': 'times'}[name] + ') {' + body + '\n}\n'
    harness = r'''
const SR = 44100;
function tone(hz, {harmonics = 0, noise = 0} = {}) {
    const buf = new Float32Array(2048);
    for (let i = 0; i < buf.length; i++) {
        let v = Math.sin(2 * Math.PI * hz * i / SR);
        for (let h = 2; h <= 1 + harmonics; h++) {
            v += Math.sin(2 * Math.PI * hz * h * i / SR) / h;
        }
        // Deterministic pseudo-noise: a fixed irrational walk, so the
        // same test runs the same way on every machine, forever.
        if (noise) v += noise * (((i * 2654435761) % 1000) / 500 - 1);
        buf[i] = v / 2;
    }
    return buf;
}
const out = {};
out.a4 = autoCorrelate(tone(440), SR);
out.g3 = autoCorrelate(tone(196), SR);
out.rich = autoCorrelate(tone(220, {harmonics: 3, noise: 0.05}), SR);
out.silence = autoCorrelate(new Float32Array(2048), SR);
out.notes = [440, 196, 261.63, 82.41].map(hz => hzToNote(hz));
// A click train at a steady 100 bpm is 0.6s apart.
out.bpm100 = peaksToBpm([0, 0.6, 1.2, 1.8, 2.4]);
out.bpm_none = peaksToBpm([1.0]);
console.log(JSON.stringify(out));
'''
    scratch = tempfile.mkdtemp(prefix='chauffeur_pitch_')
    path = os.path.join(scratch, 'run.mjs')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(''.join(fns.values()) + harness)
    proc = subprocess.run([node, path], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=60)
    check(proc.returncode == 0, f"the detector threw:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _within_a_semitone(got, want):
    return got is not None and abs(1200 * (__import__('math').log2(got / want))) < 100


def scenario_the_pitch_detector_lands_on_the_note():
    got = _pitch_under_node()
    if got is None:
        return
    check(_within_a_semitone(got['a4'], 440),
          f"a 440 sine reads as A4, got {got['a4']}")
    check(_within_a_semitone(got['g3'], 196),
          f"a 196 sine reads as G3, got {got['g3']}")
    check(_within_a_semitone(got['rich'], 220),
          f"and a real instrument -- harmonics on top, noise underneath -- "
          f"still reads its fundamental, got {got['rich']}")


def scenario_silence_is_not_a_note():
    """The failure mode that matters most: a detector that answers
    anyway. A tuner needle jumping around an empty room is worse than a
    tuner that says nothing."""
    got = _pitch_under_node()
    if got is None:
        return
    check(got['silence'] is None, f"silence reads as nothing, got {got['silence']}")


def scenario_a_frequency_becomes_a_note_name_the_validator_would_accept():
    got = _pitch_under_node()
    if got is None:
        return
    import re
    names = [n['name'] for n in got['notes']]
    check(names == ['A4', 'G3', 'C4', 'E2'],
          f"the four known frequencies name themselves, got {names}")
    for n in names:
        check(re.match(r'^[A-G][#b]?[0-8]$', n),
              f"and in the same grammar the sanitizer validates, got {n}")


def scenario_the_tempo_reader_counts_the_gaps_not_the_peaks():
    got = _pitch_under_node()
    if got is None:
        return
    check(abs(got['bpm100'] - 100) < 1,
          f"peaks 0.6s apart are 100 bpm, got {got['bpm100']}")
    check(got['bpm_none'] is None,
          f"and one peak is not a tempo -- a tempo is a GAP, got "
          f"{got['bpm_none']}")


def scenario_a_pitch_scene_advances_on_the_target_being_held():
    """Not on one lucky frame. A note has to hold, or a passing overtone
    from the wrong string finishes the scene for you."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        listenTick\(\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('hzToNote' in body, f"the tick names what it heard, got {body!r}")
    check('pitchHeldSince' in body or 'heldSince' in body,
          "and requires it to have held")


def scenario_the_tuner_draws_a_needle_not_a_verdict():
    """A tuner says WHICH note and how far off. It never says good."""
    src = _read('components/lesson_player.html')
    check("primitive.kind === 'tuner'" in src, "the player draws a tuner")
    check('tunerCents' in src, "with a distance from the note in cents")
    for word in ('good', 'perfect', 'well done', 'nice'):
        import re
        check(not re.search(r'>\s*' + word, src, re.I),
              f"and never a verdict like {word!r}")


# --- the microphone -----------------------------------------------------


def scenario_the_mic_is_asked_for_lazily_and_never_at_open():
    """A lesson that opens by demanding a microphone is a lesson most
    households refuse once and never trust again. Asked at the first
    scene that actually listens, and only there."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        open\(w, lesson, preview\) \{(.*?)\n        \},', src, re.S)
    check('getUserMedia' not in (m.group(1) if m else ''),
          "open() never touches the microphone")
    m2 = re.search(r'\n        async startListening\(s\) \{(.*?)\n        \},',
                   src, re.S)
    check(m2, "startListening exists")
    body = m2.group(1) if m2 else ''
    check('getUserMedia' in body, f"and it is where the ask happens, got {body!r}")


def scenario_the_mic_is_released_on_every_way_out():
    """Open only inside a listening scene. Advancing, closing and
    finishing all pass through stopSound(), which is the one place that
    can be relied on."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        stopSound\(\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('releaseMic' in body, f"stopSound releases it, got {body!r}")
    m2 = re.search(r'\n        releaseMic\(\) \{(.*?)\n        \},', src, re.S)
    check(m2, "releaseMic exists")
    rel = m2.group(1) if m2 else ''
    check('.stop()' in rel, "it stops the track itself, not just the node")
    check('micOn' in rel, "and the indicator goes with it")


def scenario_nothing_heard_is_ever_recorded_or_sent():
    """The rule the whole listening slice hangs on. Not a policy in a
    docstring -- there is no recorder in the file and no request anywhere
    near the audio path."""
    src = _read('components/lesson_player.html')
    check('MediaRecorder' not in src, "there is no recorder in this file")
    import re
    for fn in (r'async startListening\(s\)', r'listenTick\(\)', r'releaseMic\(\)'):
        m = re.search(r'\n        ' + fn + r' \{(.*?)\n        \},', src, re.S)
        check(m, f"{fn} is findable")
        body = m.group(1) if m else ''
        for forbidden in ('fetch(', 'localStorage', 'XMLHttpRequest', 'WebSocket'):
            check(forbidden not in body,
                  f"the audio path must never {forbidden}")


def scenario_a_missing_or_refused_mic_degrades_to_a_tap():
    """A wall panel plausibly has no microphone at all, and a household
    may simply say no. Either way the scene still plays and still
    advances -- it just becomes a tap, and says so."""
    src = _read('components/lesson_player.html')
    check('micDenied' in src, "the refusal is a state the markup can read")
    check('Tap when you have' in src or 'tap when' in src.lower(),
          "and the scene offers the tap instead")
    import re
    m = re.search(r'\n        async startListening\(s\) \{(.*?)\n        \},',
                  src, re.S)
    body = m.group(1) if m else ''
    check('catch' in body and 'micDenied' in body,
          f"a refusal is caught and named, never thrown at the scene, "
          f"got {body!r}")


def scenario_the_mic_indicator_is_always_visible_while_it_is_open():
    src = _read('components/lesson_player.html')
    check('micOn' in src, "there is an on-air flag")
    import re
    check(re.search(r'x-show="micOn"', src),
          "and something on screen bound directly to it")


# --- explain this -------------------------------------------------------


def scenario_explain_this_asks_and_never_writes():
    src = _read('components/lesson_player.html')
    check('Explain this' in src, "the tap exists and says what it does")
    import re
    m = re.search(r'\n        async explainThis\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "explainThis exists")
    body = m.group(1) if m else ''
    check('lesson-help' in body, f"it asks the help route, got {body!r}")
    check('this.say(' in body, "and says the answer out loud")
    # localStorage appears once, READ-ONLY, for the member token every
    # other lesson fetch in this app already sends. Nothing is written.
    check('localStorage.setItem' not in body and 'removeItem' not in body,
          "and writes nothing to the device")
    for forbidden in ('lesson-player:done', "'PUT'"):
        check(forbidden not in body,
              f"asking is not an outcome -- no {forbidden}")


def scenario_explain_this_is_hidden_in_a_preview():
    """A preview spends nothing. The daily cap is a household's one
    free-tier quota and a look at a lesson nobody is having is the last
    thing that should be spending it."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'x-show="[^"]*explainable\(\)[^"]*"', src)
    check(m, "the tap is gated on explainable()")
    m2 = re.search(r'\n        explainable\(\) \{(.*?)\n        \},', src, re.S)
    check(m2, "explainable exists")
    body = m2.group(1) if m2 else ''
    check('this.preview' in body and 'usingLesson' in body,
          f"never in a preview, and never on the fallback ladder -- there "
          f"is no stored beat to explain, got {body!r}")


def scenario_an_unanswerable_question_says_so():
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        async explainThis\(\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('helpText' in body, "the answer lands somewhere visible")
    check("couldn" in body.lower() or 'could not' in body.lower(),
          f"and an empty answer says so rather than failing silently, "
          f"got {body!r}")


# --- hint ladders -------------------------------------------------------


def scenario_a_hint_ladder_reveals_one_rung_at_a_time():
    src = _read('components/lesson_player.html')
    check("primitive.kind === 'hints'" in src, "the player draws a ladder")
    check('Another hint' in src, "with a tap for the next-narrower nudge")
    check('hintIdx' in src, "and a position of its own")
    import re
    m = re.search(r'\n        nextHint\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "nextHint exists")
    body = m.group(1) if m else ''
    check('hintIdx' in body, f"it moves the rung, got {body!r}")
    for forbidden in ('fetch', 'localStorage', 'api/'):
        check(forbidden not in body,
              f"how many hints somebody needed is never recorded -- no "
              f"{forbidden}")


def scenario_a_hint_ladder_shows_position_never_a_score():
    """"3 of 4 hints used" is a completion percentage with the division
    left undone, which is one of the six progress rules. The ladder draws
    where you are, the way the unit ladder draws a rung."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r"primitive\.kind === 'hints'\"\>(.*?)</template>", src, re.S)
    check(m, "the hints block is findable")
    block = m.group(1) if m else ''
    check('hintIdx + 1' not in block or '/' not in block.split('hintIdx + 1')[1][:80],
          f"never an n-of-m count, got {block!r}")
    check('used' not in block.lower(), "and never says how many were used")


def scenario_the_answer_is_the_last_rung_not_a_shortcut():
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        hintRungs\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "hintRungs exists")
    body = m.group(1) if m else ''
    check('steps' in body and 'concat' in body and 'answer' in body,
          f"the answer is appended AFTER the steps, so the rung index has "
          f"no special case at the bottom and no shortcut past them, "
          f"got {body!r}")
    check('hintRungs()[this.hintIdx]' in src,
          "and the text shown is just that position")


# --- offers, and again slower -------------------------------------------


def scenario_not_yet_offers_rather_than_taking_over():
    """Offered, never automatic. A tap declines it and the session moves
    on exactly as it did before offers existed -- which is also what a
    check with no offer still does."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        answerCheck\(kind\) \{(.*?)\n        \},', src, re.S)
    check(m, "answerCheck takes which tap it was")
    body = m.group(1) if m else ''
    check('not_yet_offer' in body and 'offerOpen' in body,
          f"a not-yet tap on a check that offers one opens it, got {body!r}")
    check('advance()' in body, "and every other tap advances as before")
    check('Next time' in src, "the decline is a visible chip, not a dismissal")


def scenario_accepting_an_offer_splices_this_session_only():
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        acceptOffer\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "acceptOffer exists")
    body = m.group(1) if m else ''
    check('splice' in body, f"it splices into the live scene list, got {body!r}")
    check('this.idx + 1' in body, "immediately after the beat that offered it")
    for forbidden in ('fetch', 'localStorage', 'api/'):
        check(forbidden not in body,
              f"and records nothing about having done so -- no {forbidden}")


def scenario_an_offer_can_never_offer_again():
    """The server drops nested offers; the client must not reintroduce
    one by splicing scenes that carry their own. Belt and braces, because
    a spliced scene is the one path into the list that never went through
    open()."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        acceptOffer\(\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('not_yet_offer' in body,
          f"the splice strips any offer riding a spliced scene, got {body!r}")


def scenario_every_drill_can_be_run_again_slower():
    """Deterministic, no model, no offer needed: the commonest thing a
    person wants mid-drill is the same drill, slower."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        againSlower\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "againSlower exists")
    body = m.group(1) if m else ''
    check('SLOWER' in body, "it scales by one named factor")
    check('metronome_bpm' in body and 'cues' in body,
          f"the beat, the click and the cues all slow together, got {body!r}")
    for forbidden in ('fetch', 'localStorage'):
        check(forbidden not in body, f"and it stores nothing -- no {forbidden}")
    check('Again, slower' in src, "and the tap says what it does")


# --- wait beats ---------------------------------------------------------


def scenario_a_wait_beat_renders_its_own_countdown():
    src = _read('components/lesson_player.html')
    check("scene().type === 'wait'" in src, "the player draws a wait beat")
    check('waitLeft' in src, "with a countdown of its own")
    import re
    m = re.search(r'\n        startWait\(s\) \{(.*?)\n        \},', src, re.S)
    check(m, "startWait exists")
    body = m.group(1) if m else ''
    check('api/lessons/wait' in body,
          f"and arms the call before the waiting starts, got {body!r}")


def scenario_a_wait_says_out_loud_that_it_will_call_you_back():
    """The whole point of a wait beat is that you go away. A countdown
    nobody is watching is a countdown that needed to say so."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        startWait\(s\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('this.say(' in body, f"it says it, got {body!r}")


def scenario_closing_a_wait_leaves_the_call_armed():
    """Honest consequence of the no-persistence rule, stated on the
    surface rather than hidden: the announce survives the player closing
    because it lives in app_state, and reopening starts the lesson from
    the top because a lesson keeps no place."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        stopSound\(\) \{(.*?)\n        \},', src, re.S)
    body = m.group(1) if m else ''
    check('waitTimer' in body,
          "the on-screen countdown stops with the scene")
    check('lessons/wait' not in body,
          "but nothing cancels the call -- the room is still expecting it")
    check('you can close this' in src.lower() or 'close this' in src.lower(),
          "and the surface says so out loud")


# --- the room voice -----------------------------------------------------


def scenario_only_session_level_lines_reach_the_room():
    """Two channels, split by latency, and the split is the design. What
    is said BETWEEN beats can afford a round trip through Home Assistant;
    what is said INSIDE one -- a cue at 0:30, a rep count -- cannot, and
    an in-beat line routed through a room would arrive after the moment
    it was about."""
    src = _read('components/lesson_player.html')
    import re
    for fn, wanted in [('runCue', False), ('speakCount', False),
                       ('tickCounter', False)]:
        m = re.search(r'\n        ' + fn + r'\([^)]*\) \{(.*?)\n        \},',
                      src, re.S)
        check(m, f"{fn} is findable")
        check(('roomSay' in m.group(1)) == wanted,
              f"{fn} must not send an in-beat line through a room")
    m = re.search(r'\n        say\(text, lang, tone\) \{(.*?)\n        \},',
                  src, re.S)
    check('roomSay' in (m.group(1) if m else ''),
          "and say() is the one place the room fork lives, so every "
          "session-level line takes it without a second call site")


def scenario_the_room_voice_is_a_panel_only_fork():
    """A teenager's lesson on their own phone does not play to the
    kitchen. The room channel exists because a WALL board has no speaker
    worth the name and is standing in a room that does."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        roomSay\(text\) \{(.*?)\n        \},', src, re.S)
    check(m, "roomSay(text) exists")
    body = m.group(1) if m else ''
    check('this.panel' in body, "and it is panel-only")
    check('this.room' in body, "and needs a room to speak into")
    check('this.preview' in body,
          "a preview never speaks into a room -- nobody asked the house to "
          "listen to a look")
    check('/api/lessons/speak' in body or 'lessons/speak' in body,
          f"routed through the speak endpoint, got {body!r}")


def scenario_the_room_is_asked_once_and_remembered_on_the_device():
    """No board-level or device-level room binding exists in this app: the
    music card's own room is a per-CARD option, which is right for music
    (a card deliberately sends audio somewhere else) and wrong for a
    screen, which is in exactly one room and cannot have two cards in two
    of them. So the panel asks, once, and keeps the answer where a
    per-viewer convenience belongs."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'\n        async askRoom\(\) \{(.*?)\n        \},', src, re.S)
    check(m, "askRoom() exists")
    body = m.group(1) if m else ''
    check('promptInput' in body, "asked with the house's own prompt")
    for banned in ('prompt(', 'confirm(', 'alert('):
        check(banned not in body, f"never a browser {banned} dialog")
    check('localStorage' in body, "and kept on the device that answered")
    m2 = re.search(r'\n        loadRoom\(\) \{(.*?)\n        \},', src, re.S)
    check(m2, "loadRoom() exists")
    check('chfLessonRoom' in (m2.group(1) if m2 else ''),
          "with a host-set override ahead of it, so a board that ever does "
          "learn its own room has a door to land in")


if __name__ == '__main__':
    scenario_component_exists_and_renders_the_four_beats()
    scenario_checks_are_never_stored()
    scenario_programs_page_opens_the_player()
    scenario_no_streak_language_in_the_player()
    scenario_programs_page_never_posts_from_the_player_directly()
    scenario_the_component_reads_the_panel_flag()
    scenario_show_degrades_unknown_kinds_to_a_caption()
    scenario_sound_is_cleared_on_scene_change_and_close()
    scenario_check_taps_never_bubble_into_the_advance_handler()
    scenario_an_unrenderable_show_with_no_caption_still_says_something()
    scenario_fallback_ladder_never_produces_an_empty_scene_list()
    scenario_the_wall_and_the_pwa_reach_the_player()
    scenario_the_wall_reads_the_slot_key_off_the_window()
    scenario_the_last_scene_is_never_an_ambient_tap()
    scenario_finishing_asks_before_it_logs()
    scenario_the_wall_button_does_not_promise_a_write()
    scenario_the_player_says_where_the_lesson_came_from()
    scenario_the_editor_can_reorder_and_names_its_source()
    scenario_the_wall_card_dispatches_the_raw_window_not_the_display_row()
    scenario_the_lesson_player_is_included_once_on_each_page_not_inside_the_card()
    scenario_the_wall_tap_is_panel_sized()
    scenario_the_pwa_reuses_its_existing_log_action_and_only_once()
    scenario_music_primitives_render()
    scenario_keyboard_and_fretboard_are_renderable_shows()
    scenario_keyboard_geometry_is_computed_not_hand_drawn()
    scenario_fretboard_window_starts_at_the_lowest_fretted_dot()
    scenario_remaining_primitives_render()
    scenario_counter_taps_are_never_sent()
    scenario_card_flips_are_never_sent()
    scenario_cards_and_counter_taps_never_bubble_into_advance()
    scenario_counter_is_paced_not_tap_per_rep()
    scenario_counter_first_tap_announces_immediately_then_paces_itself()
    scenario_counter_pause_and_resume_are_both_reachable()
    scenario_counter_reaching_target_stops_itself_without_a_tap()
    scenario_counter_done_state_is_visible_without_a_tap()
    scenario_counter_speech_never_breaks_the_counter()
    scenario_counter_speech_cancels_before_speaking_so_it_never_backlogs()
    scenario_counter_reads_its_own_seconds_per_rep_with_a_default()
    scenario_stop_sound_and_enter_scene_both_clear_the_counters_pace()
    scenario_fretboard_open_strings_are_structurally_separate_from_fretted_dots()
    scenario_fretboard_muted_strings_draw_as_x_above_the_nut()
    scenario_fretboard_is_vertical_low_e_left_high_e_right()
    scenario_fretboard_nut_is_thick_only_when_the_window_starts_at_fret_one()
    scenario_fretboard_window_widens_to_fit_the_real_span()
    scenario_fretboard_overflow_gets_a_visibly_approximate_marker()
    scenario_keyboard_signals_a_dropped_highlight_rather_than_hiding_it()
    scenario_cards_container_is_panel_aware_like_its_siblings()
    scenario_preview_flag_flows_from_open_to_state()
    scenario_preview_footer_button_closes_instead_of_asking_to_log()
    scenario_preview_marker_shows_in_the_header()
    scenario_preview_never_reaches_the_session_log_path()
    scenario_the_lesson_editor_offers_a_play_tap()
    scenario_play_lesson_reads_storage_fresh_never_the_unsaved_draft()
    scenario_slot_steps_matches_the_rotation_vs_flat_branch_the_readonly_view_uses()
    scenario_sweep_report_play_tap_only_on_rows_that_wrote_something()
    scenario_play_sweep_slot_fetches_by_program_id_and_previews()
    scenario_sweep_report_entries_carry_a_program_id_for_the_play_tap()
    scenario_family_calendar_offers_a_start_tap_for_practice()
    scenario_start_tap_is_wired_from_the_real_practice_payload()
    scenario_start_practice_session_reuses_the_two_shapes_its_siblings_already_use()
    scenario_start_practice_session_never_blocks_the_tap_on_a_failed_fetch()
    scenario_start_practice_session_closes_the_dialog_before_dispatching()
    scenario_start_practice_session_carries_the_practice_windows_own_unit_n()
    scenario_host_listen_flag_is_explicit_not_dom_sniffed()
    scenario_hosts_that_log_a_session_announce_they_listen()
    scenario_hosts_with_no_log_action_never_announce()
    scenario_text_white_survives_only_on_invariant_accent_fills()
    scenario_surface_text_uses_the_gray_100_token_not_literal_white()
    scenario_check_button_active_state_stays_theme_invariant()
    scenario_metadata_text_is_gray_400_not_gray_500()
    scenario_svg_elements_on_the_transparent_canvas_never_hardcode_a_dark_only_color()
    scenario_self_contained_svg_shapes_keep_their_literal_fills()
    scenario_the_speech_wrapper_can_never_break_a_scene()
    scenario_a_scene_speaks_its_own_line_on_entry()
    scenario_the_mute_tap_is_reachable_and_gates_the_voice()
    scenario_the_greeting_is_the_players_own_words_never_the_models()
    scenario_a_preview_is_never_greeted()
    scenario_stopping_the_sound_stops_the_voice_too()
    scenario_the_chime_shares_the_players_one_audio_context()
    scenario_cues_fire_once_each_in_order()
    scenario_a_clock_that_jumps_still_owes_every_cue()
    scenario_the_cue_scheduler_rides_the_beats_own_timer()
    scenario_cues_never_outlive_their_scene()
    scenario_a_cue_stores_nothing()
    scenario_the_pitch_detector_lands_on_the_note()
    scenario_silence_is_not_a_note()
    scenario_a_frequency_becomes_a_note_name_the_validator_would_accept()
    scenario_the_tempo_reader_counts_the_gaps_not_the_peaks()
    scenario_a_pitch_scene_advances_on_the_target_being_held()
    scenario_the_tuner_draws_a_needle_not_a_verdict()
    scenario_the_mic_is_asked_for_lazily_and_never_at_open()
    scenario_the_mic_is_released_on_every_way_out()
    scenario_nothing_heard_is_ever_recorded_or_sent()
    scenario_a_missing_or_refused_mic_degrades_to_a_tap()
    scenario_the_mic_indicator_is_always_visible_while_it_is_open()
    scenario_explain_this_asks_and_never_writes()
    scenario_explain_this_is_hidden_in_a_preview()
    scenario_an_unanswerable_question_says_so()
    scenario_a_hint_ladder_reveals_one_rung_at_a_time()
    scenario_a_hint_ladder_shows_position_never_a_score()
    scenario_the_answer_is_the_last_rung_not_a_shortcut()
    scenario_not_yet_offers_rather_than_taking_over()
    scenario_accepting_an_offer_splices_this_session_only()
    scenario_an_offer_can_never_offer_again()
    scenario_every_drill_can_be_run_again_slower()
    scenario_a_wait_beat_renders_its_own_countdown()
    scenario_a_wait_says_out_loud_that_it_will_call_you_back()
    scenario_closing_a_wait_leaves_the_call_armed()
    scenario_only_session_level_lines_reach_the_room()
    scenario_the_room_voice_is_a_panel_only_fork()
    scenario_the_room_is_asked_once_and_remembered_on_the_device()
    print("test_lesson_player_runtime OK")
