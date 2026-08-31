"""The lesson script, forced into shapes the player can eat.

Same philosophy as programs.sanitize_slots: bounds live in the shape,
every door goes through them, and the model is never trusted to stay
inside a limit it was merely asked to respect.
"""
from harness import check
from services import program_lessons as pl


def _say(text='Sit comfortably at the keys.'):
    return {'type': 'say', 'text': text}


def scenario_scene_cap():
    scenes = [_say(f'beat {i}') for i in range(30)]
    out = pl.sanitize_script(scenes, 'generated')
    check(len(out) == pl.MAX_SCENES, f"capped at {pl.MAX_SCENES}, got {len(out)}")


def scenario_text_cap_and_type_whitelist():
    out = pl.sanitize_script([
        {'type': 'say', 'text': 'x' * 5000},
        {'type': 'shout', 'text': 'nope'},
        {'type': 'do', 'text': 'One-minute changes G to C', 'seconds': 999999,
         'metronome_bpm': 999},
        {'type': 'check', 'ask': 'Could you keep the beat?'},
    ], 'generated')
    check(len(out) == 3, f"unknown type dropped, got {out}")
    check(len(out[0]['text']) == pl.MAX_TEXT, "text clamped")
    check(out[1]['seconds'] <= 240 * 60, "seconds clamped")
    check(out[1]['metronome_bpm'] == 240, f"bpm clamped, got {out[1]}")


def scenario_unknown_primitive_dropped_bad_params_degrade():
    out = pl.sanitize_script([
        {'type': 'show', 'primitive': {'kind': 'hologram'}, 'caption': 'x'},
        {'type': 'show', 'primitive': {'kind': 'fretboard',
                                       'dots': [{'string': 9, 'fret': 40,
                                                 'finger': 7}]},
         'caption': 'G chord'},
        {'type': 'show', 'primitive': {'kind': 'keyboard',
                                       'keys': ['C4', 'E4', 'G4']},
         'caption': 'C major'},
    ], 'generated')
    check(len(out) == 2, f"unknown kind dropped entirely, got {out}")
    check(out[0]['type'] == 'say' and out[0]['text'] == 'G chord',
          f"bad params drop the visual, keep the caption, got {out[0]}")
    check(out[1]['type'] == 'show', "valid primitive survives")


def scenario_generated_origin_screens_physical_technique():
    """A generated lesson may structure practice; it may not prescribe what
    a body does. Enforced like load/dose: the scene is dropped, not
    reworded."""
    out = pl.sanitize_script([
        _say('Curl your wrist inward as you reach for the octave.'),
        _say('Play the passage slowly, then at tempo.'),
    ], 'generated')
    check(len(out) == 1 and 'wrist' not in out[0]['text'],
          f"physical prescription dropped for generated origin, got {out}")
    # The same sentence in a CITED lesson survives — a real teacher's page
    # may say it, and the citation carries the authority.
    out = pl.sanitize_script([_say('Relax your wrist between phrases.')],
                             'cited')
    check(len(out) == 1, "cited text is not technique-screened")


def scenario_body_screen_fires_on_every_origin():
    out = pl.sanitize_script([_say('This drill helps you lose weight fast.')],
                             'cited')
    check(out == [], "body-composition text never survives, cited or not")


def scenario_body_word_screen_fires_on_every_origin():
    """BODY_PHRASES is only half of curate's own screen -- the single words
    (calorie, bmi, skinny, ...) matter just as much, and a sanitizer that
    only imported the phrases let a body-composition WORD straight
    through. Checked on both origins: this is not the technique screen,
    which only fires on generated -- this one never lets up."""
    for origin in ('generated', 'cited'):
        out = pl.sanitize_script(
            [_say('This drill burns calories fast.')], origin)
        check(out == [], f"body-composition word dropped, origin={origin}, "
                         f"got {out}")


def scenario_hostile_non_list_scenes_never_raise():
    """`scenes or []` coalesces the FALSY shapes for free; the door still
    has to survive a TRUTHY non-list -- a bare int, float, or True --
    which used to reach the for loop itself and raise TypeError."""
    for bad in (42, 3.14, True, None, 'not a list'):
        out = pl.sanitize_script(bad, 'generated')
        check(out == [], f"non-list scenes yields no scenes, got {out} "
                         f"for {bad!r}")


def scenario_infinite_numerics_never_raise():
    """int(float('inf')) raises OverflowError, which a bare
    (TypeError, ValueError) guard does not catch -- and JSON hands this
    door exactly that shape for free (the bare token Infinity, or any
    numeral past a double's range). Every numeric field, on every
    validator that parses one, has to absorb it without raising."""
    out = pl.sanitize_script([
        {'type': 'do', 'text': 'a', 'seconds': float('inf')},
        {'type': 'do', 'text': 'b', 'metronome_bpm': float('inf')},
        {'type': 'show', 'primitive': {'kind': 'metronome',
                                       'bpm': float('inf')},
         'caption': 'tempo'},
        {'type': 'show', 'primitive': {'kind': 'timer',
                                       'seconds': float('inf')},
         'caption': 'timer'},
        {'type': 'show', 'primitive': {'kind': 'counter',
                                       'target': float('inf')},
         'caption': 'reps'},
        {'type': 'show', 'primitive': {'kind': 'fretboard',
                                       'dots': [{'string': float('inf'),
                                                 'fret': 1, 'finger': 1}]},
         'caption': 'chord'},
    ], 'generated')
    check(len(out) == 6, f"every inf-bearing scene survives, got {out}")
    check('seconds' not in out[0], "unparseable seconds silently omitted")
    check('metronome_bpm' not in out[1], "unparseable bpm silently omitted")
    check(out[2] == {'type': 'say', 'text': 'tempo'}, f"got {out[2]}")
    check(out[3] == {'type': 'say', 'text': 'timer'}, f"got {out[3]}")
    check(out[4] == {'type': 'say', 'text': 'reps'}, f"got {out[4]}")
    check(out[5] == {'type': 'say', 'text': 'chord'}, f"got {out[5]}")


def scenario_slot_of():
    w = {'program_id': 'p1', 'phase_name': 'Foundations', 'session_label': 'Technique',
         'date': '2026-09-01', 'unit_title': '', 'steps': []}
    s = pl.slot_of(w, unit_n=3)
    check(s == {'phase_name': 'Foundations', 'unit_n': 3,
                'session_label': 'Technique'}, f"got {s}")


if __name__ == '__main__':
    scenario_scene_cap()
    scenario_text_cap_and_type_whitelist()
    scenario_unknown_primitive_dropped_bad_params_degrade()
    scenario_generated_origin_screens_physical_technique()
    scenario_body_screen_fires_on_every_origin()
    scenario_body_word_screen_fires_on_every_origin()
    scenario_hostile_non_list_scenes_never_raise()
    scenario_infinite_numerics_never_raise()
    scenario_slot_of()
    print("test_program_lessons OK")
