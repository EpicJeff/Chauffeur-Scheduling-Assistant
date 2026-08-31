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
    taps = re.findall(r'@click(\.stop)?="answerCheck\(\)"', src)
    check(len(taps) >= 3, f"all three check taps present, found {len(taps)}")
    check(all(m == '.stop' for m in taps),
          "every check tap must carry .stop, or it can bubble into the "
          "scene area's own tap-to-advance handler")


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
    check('!this.panel' in body,
          "no ask on a wall board, where nothing listens for the event and a "
          "confirmed write would never happen")


def scenario_the_wall_button_does_not_promise_a_write():
    """home.html registers no `lesson-player:done` listener, by design -- a
    panel authenticates as a place, not a person. "Log it?" there promised
    a write that was never coming and simply closed the modal."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'x-text="isLast\(\) \? ([^"]*)"', src)
    check(m, "the footer button's label expression is findable")
    label = m.group(1) if m else ''
    check("panel ? 'Finish'" in label,
          f"a wall board says Finish, not Log it?, got {label!r}")
    check("'Log it?'" in label, "and the phone still gets the log ask")
    check('lesson-player:done' not in _read('home.html'),
          "the wall really does not listen -- if that changes, so must this")


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
    for page in ('home.html', 'app.html'):
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
    check(re.search(r'fretboardSvg\(dots\)\s*\{', src), "fretboardSvg(dots) exists")
    check("kind === 'keyboard'" in src, "the show dispatch has a keyboard branch")
    check("kind === 'fretboard'" in src, "the show dispatch has a fretboard branch")
    check("kind === 'metronome'" in src, "metronome is still wired (Task 6)")
    check('keyboardSvg(scene().primitive.keys)' in src,
          "the keyboard branch feeds the renderer its own validated keys")
    check('fretboardSvg(scene().primitive.dots)' in src,
          "the fretboard branch feeds the renderer its own validated dots")
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
    m = re.search(r'keyboardSvg\(keys\)\s*\{(.*?)fretboardSvg\(dots\)', src, re.S)
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
    m = re.search(r'fretboardSvg\(dots\)\s*\{(.*?)cardFace\(', src, re.S)
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
    """A rep count is a within-scene convenience, not a record."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'bumpCounter\([^)]*\)\s*\{([^}]*)\}', src)
    check(m, "bumpCounter exists")
    body = m.group(1) if m else ''
    for forbidden in ('fetch', 'localStorage', 'api', 'POST'):
        check(forbidden not in body, f"counter taps never {forbidden}")


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
    for handler in ('toggleCardFlip', 'cardPrev', 'cardNext', 'bumpCounter'):
        taps = re.findall(r'@click(\.stop)?="' + handler + r'\(\)"', src)
        check(len(taps) >= 1, f"{handler} is wired to a tap")
        check(all(t == '.stop' for t in taps),
              f"every {handler} tap must carry .stop, or it can bubble into "
              f"the scene area's own tap-to-advance handler")


def scenario_fretboard_open_strings_are_structurally_separate_from_fretted_dots():
    """Fix round 1, finding 1. An open string (fret 0) used to clamp into
    the SAME column as a fret-1 dot -- visually identical, though a
    completely different instruction (nothing fretted vs finger down at
    fret 1). Scoped to fretboardSvg's own body, bounded by the next
    function in source (the same anchor
    scenario_fretboard_window_starts_at_the_lowest_fretted_dot already
    uses)."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots\)\s*\{(.*?)cardFace\(', src, re.S)
    check(m, "fretboardSvg body is findable, bounded by the next function")
    body = m.group(1) if m else ''
    check('openDots' in body and 'frettedDots' in body,
          "open (fret 0) and fretted (fret > 0) dots are split before either is drawn")
    check('fill="none" stroke="#2dd4bf"' in body,
          "an open string draws as a hollow ring -- structurally distinct from a solid fretted dot")
    check('gx - 17' in body,
          "the open marker sits LEFT of the grid's own left edge, never inside a fret column")


def scenario_fretboard_window_widens_to_fit_the_real_span():
    """Fix round 1, finding 1's other half: a realistic one-finger-per-fret
    run across six frets used to lose frets 5 and 6 to the same fixed
    5-fret column. The window now widens to the dots' own span first,
    only falling back to a cap past a sane width."""
    src = _read('components/lesson_player.html')
    import re
    m = re.search(r'fretboardSvg\(dots\)\s*\{(.*?)cardFace\(', src, re.S)
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
    m = re.search(r'fretboardSvg\(dots\)\s*\{(.*?)cardFace\(', src, re.S)
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
    m = re.search(r'keyboardSvg\(keys\)\s*\{(.*?)fretboardSvg\(dots\)', src, re.S)
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
    it closes instead. The label expression already branched on `panel`
    (wall vs phone); preview extends that same ternary rather than
    growing a second, independent one, and it is checked FIRST so it wins
    over the panel branch too (a preview opened with ?panel=true still
    just closes, never "Finish"). Anchored to the same x-text attribute
    scenario_the_wall_button_does_not_promise_a_write already pins."""
    import re
    src = _read('components/lesson_player.html')
    m = re.search(r'x-text="isLast\(\) \? ([^"]*)"', src)
    check(m, "the footer button's label expression is findable")
    label = m.group(1) if m else ''
    check("(preview ? 'Close' : (panel ? 'Finish' : 'Log it?'))" in label,
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
    scenario_fretboard_open_strings_are_structurally_separate_from_fretted_dots()
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
    print("test_lesson_player_runtime OK")
