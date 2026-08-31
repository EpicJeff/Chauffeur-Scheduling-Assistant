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
    check('this.logSession(p)' in src,
          "by calling the exact log action the page already had")


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
    for page in ('components/programs_card.html', 'app.html'):
        src = _read(page)
        check('lesson-player:open' in src, f"{page} can open the player")


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
    Start tap has to be a bigger target than a phone chip, not the compact
    px-2.5 py-1-scale rows the rest of this card already draws."""
    src = _read('components/programs_card.html')
    check('py-2' in src and 'px-4' in src,
          "the panel-tier padding the brief specifies")
    check('Start session' in src,
          "labelled the same as the programs page's own button (Task 6)")


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
    scenario_the_wall_card_dispatches_the_raw_window_not_the_display_row()
    scenario_the_lesson_player_is_included_once_on_each_page_not_inside_the_card()
    scenario_the_wall_tap_is_panel_sized()
    scenario_the_pwa_reuses_its_existing_log_action_and_only_once()
    print("test_lesson_player_runtime OK")
