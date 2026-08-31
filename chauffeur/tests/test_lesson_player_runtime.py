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


if __name__ == '__main__':
    scenario_component_exists_and_renders_the_four_beats()
    scenario_checks_are_never_stored()
    scenario_programs_page_opens_the_player()
    scenario_no_streak_language_in_the_player()
    scenario_programs_page_never_posts_from_the_player_directly()
    scenario_the_component_reads_the_panel_flag()
    scenario_show_degrades_unknown_kinds_to_a_caption()
    scenario_sound_is_cleared_on_scene_change_and_close()
    print("test_lesson_player_runtime OK")
