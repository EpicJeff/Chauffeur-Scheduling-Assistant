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


def scenario_card_faces_run_the_same_screens_as_every_other_beat():
    """The hole this closes was live and verified: `_valid_cards` checked
    that a face was non-empty and nothing else, and the `show` branch
    screened the caption alone -- so a card BACK reading "About 300 -
    great for weight loss. Keep your wrist straight and rotate the elbow."
    survived verbatim on a generated origin and rendered through
    cardFace(). Both halves of the screen have to fire on a face: the body
    words on every origin, the physical prescription on generated."""
    body = pl.sanitize_script([
        {'type': 'show', 'caption': 'Chord names',
         'primitive': {'kind': 'cards',
                       'pairs': [{'front': 'G', 'back': 'About 300 calories'}]}},
    ], 'cited')
    check(body == [], f"a body-composition card face dies on EVERY origin, got {body}")
    physical = pl.sanitize_script([
        {'type': 'show', 'caption': 'Chord names',
         'primitive': {'kind': 'cards',
                       'pairs': [{'front': 'G', 'back': 'Keep your wrist straight'}]}},
    ], 'generated')
    check(physical == [],
          f"a generated card face may not prescribe a body, got {physical}")
    kept = pl.sanitize_script([
        {'type': 'show', 'caption': 'Chord names',
         'primitive': {'kind': 'cards',
                       'pairs': [{'front': 'G', 'back': 'Three fingers'}]}},
    ], 'generated')
    check(len(kept) == 1 and kept[0]['primitive']['pairs'][0]['back'] == 'Three fingers',
          f"a clean pair still survives, got {kept}")


def scenario_card_faces_are_capped_like_every_other_string():
    """Every other text field in a script is capped at 280 or 120; a card
    face was capped at nothing at all, so a 5000-character front was stored
    and shipped whole."""
    out = pl.sanitize_script([
        {'type': 'show', 'caption': 'Cards',
         'primitive': {'kind': 'cards',
                       'pairs': [{'front': 'x' * 5000, 'back': 'y' * 5000}]}},
    ], 'generated')
    check(len(out) == 1, f"the scene survives, got {out}")
    pair = out[0]['primitive']['pairs'][0]
    check(len(pair['front']) == pl.MAX_SHORT_TEXT
          and len(pair['back']) == pl.MAX_SHORT_TEXT,
          f"both faces clamped to {pl.MAX_SHORT_TEXT}, got "
          f"{len(pair['front'])}/{len(pair['back'])}")


def scenario_the_stored_primitive_is_rebuilt_not_the_models_own_dict():
    """`out.append({... 'primitive': prim ...})` stored the model's own
    object: any extra key it invented rode along past every cap and every
    screen, and the dict that reached storage was the same one the caller
    still held, so mutating the input afterwards rewrote a sanitized
    scene."""
    prim = {'kind': 'counter', 'target': 10, 'label': 'reps',
            'note': 'keep your wrist straight'}
    out = pl.sanitize_script([{'type': 'show', 'primitive': prim,
                               'caption': 'Ten'}], 'generated')
    check(len(out) == 1, f"the scene survives, got {out}")
    stored = out[0]['primitive']
    check(set(stored) == {'kind', 'target'},
          f"only the validated keys are kept, got {sorted(stored)}")
    check(stored is not prim, "and it is a new dict, not the caller's own")
    prim['target'] = 999
    check(stored['target'] == 10,
          f"so a later mutation of the input cannot rewrite it, got {stored}")


def scenario_every_primitive_kind_survives_the_rebuild():
    """Rebuilding from validated keys must not quietly drop a primitive it
    was only ever supposed to clean -- all six kinds still come through
    with the params their renderer reads."""
    scenes = pl.sanitize_script([
        {'type': 'show', 'primitive': {'kind': 'timer', 'seconds': 60}},
        {'type': 'show', 'primitive': {'kind': 'metronome', 'bpm': 80}},
        {'type': 'show', 'primitive': {'kind': 'keyboard', 'keys': ['C4', 'E4']}},
        {'type': 'show', 'primitive': {'kind': 'fretboard',
                                       'dots': [{'string': 5, 'fret': 2, 'finger': 2}]}},
        {'type': 'show', 'primitive': {'kind': 'cards',
                                       'pairs': [{'front': 'G', 'back': 'Three'}]}},
        {'type': 'show', 'primitive': {'kind': 'counter', 'target': 10}},
    ], 'generated')
    kinds = [s['primitive']['kind'] for s in scenes]
    check(kinds == ['timer', 'metronome', 'keyboard', 'fretboard',
                    'cards', 'counter'], f"all six still draw, got {kinds}")
    check(scenes[2]['primitive']['keys'] == ['C4', 'E4'], f"got {scenes[2]}")
    check(scenes[3]['primitive']['dots'] == [{'string': 5, 'fret': 2, 'finger': 2}],
          f"got {scenes[3]}")


def scenario_a_do_beat_is_session_shaped_not_an_afternoon():
    """MAX_DO_SECONDS was 240*60 -- four hours, which is
    `programs.MAX_MINUTES` in seconds: the ceiling on a whole SESSION,
    handed to one beat inside it, under a comment saying the opposite."""
    check(pl.MAX_DO_SECONDS <= 60 * 60,
          f"one beat is minutes, got {pl.MAX_DO_SECONDS}s")
    out = pl.sanitize_script([{'type': 'do', 'text': 'Play slowly',
                               'seconds': 999999}], 'generated')
    check(out[0]['seconds'] == pl.MAX_DO_SECONDS, f"clamped, got {out}")


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


# --- storage: a lesson lives beside the program, keyed on its slot ---

def _lreset():
    from services import storage
    storage.program_lessons_table.truncate()


def scenario_lesson_roundtrip_by_slot():
    from services import storage
    _lreset()
    slot = {'phase_name': 'Foundations', 'unit_n': 1, 'session_label': 'Technique'}
    storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say()], 'model': 'gemma-4-31b-it'})
    row = storage.get_program_lesson('p1', slot)
    check(row and row['origin'] == 'generated' and row['edited'] is False,
          f"got {row}")
    check(storage.get_program_lesson('p1', {**slot, 'unit_n': 2}) is None,
          "a different unit is a different lesson")


def scenario_upsert_replaces_same_slot():
    from services import storage
    _lreset()
    slot = {'phase_name': 'F', 'unit_n': 1, 'session_label': ''}
    storage.upsert_program_lesson('p1', slot, {'origin': 'generated',
                                               'scenes': [_say('v1')]})
    storage.upsert_program_lesson('p1', slot, {'origin': 'generated',
                                               'scenes': [_say('v2')]})
    row = storage.get_program_lesson('p1', slot)
    check(row['scenes'][0]['text'] == 'v2', "same slot, one row")


def scenario_edited_is_never_regenerated_over():
    from services import storage
    _lreset()
    slot = {'phase_name': 'F', 'unit_n': 1, 'session_label': ''}
    storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say('mine')], 'edited': True})
    wrote = storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say('robot')]})
    check(wrote == '', "generation bounces off a hand edit")
    check(storage.get_program_lesson('p1', slot)['scenes'][0]['text'] == 'mine',
          "the hand edit stands")
    wrote = storage.upsert_program_lesson('p1', slot, {
        'origin': 'generated', 'scenes': [_say('mine v2')], 'edited': True})
    check(wrote != '', "a hand may replace a hand")


def scenario_delete_one_lesson():
    from services import storage
    _lreset()
    slot = {'phase_name': 'F', 'unit_n': 1, 'session_label': ''}
    other = {'phase_name': 'F', 'unit_n': 2, 'session_label': ''}
    storage.upsert_program_lesson('p1', slot, {'scenes': []})
    storage.upsert_program_lesson('p1', other, {'scenes': []})
    gone = storage.delete_program_lesson('p1', slot)
    check(gone is True, f"a row was there, got {gone}")
    check(storage.get_program_lesson('p1', slot) is None,
          "that slot's lesson is gone")
    check(storage.get_program_lesson('p1', other) is not None,
          "a different slot in the same program keeps its lesson")
    gone_again = storage.delete_program_lesson('p1', slot)
    check(gone_again is False, f"nothing left there the second time, got {gone_again}")


def scenario_delete_clears_a_program():
    from services import storage
    _lreset()
    storage.upsert_program_lesson('p1', {'phase_name': 'F', 'unit_n': 1,
                                         'session_label': ''}, {'scenes': []})
    storage.upsert_program_lesson('p2', {'phase_name': 'F', 'unit_n': 1,
                                         'session_label': ''}, {'scenes': []})
    n = storage.delete_program_lessons('p1')
    check(n == 1, f"one program's lessons gone, got {n}")
    check(storage.get_program_lesson('p2', {'phase_name': 'F', 'unit_n': 1,
                                            'session_label': ''}) is not None,
          "the other program keeps its lesson")


def scenario_none_slot_and_data_never_raise():
    """slot=None and data=None are at least as realistic off an HTTP JSON
    body -- an omitted key parses to a bare null -- as the {} this door
    already handled correctly. Every public function has to degrade a null
    exactly like it already degrades {}, never raise: the same bar Task 4's
    scenario_hostile_non_list_scenes_never_raise holds sanitize_script to."""
    from services import storage
    _lreset()
    check(storage.get_program_lesson('p1', None) is None,
          "get on a null slot returns None, not a crash")
    check(storage.delete_program_lesson('p1', None) is False,
          "delete on a null slot returns a falsy result, not a crash")
    check(storage.delete_program_lesson('p1', None) is False,
          "and again: still falsy, still no crash")
    wrote = storage.upsert_program_lesson('p1', None, None)
    check(bool(wrote), f"upsert on null slot AND null data still writes, got {wrote!r}")
    check(storage.get_program_lesson('p1', {}) is not None,
          "a null slot and an empty slot land on the same row")


# --- generation: one slot's script, from the right source, or nothing ---

def _program_row(origin='generated', unit_url=''):
    return {'id': 'p9', 'member_id': 'kid', 'title': 'Play guitar',
            'source': {'origin': origin},
            'shape': {'minutes': 20}}


def _window():
    return {'program_id': 'p9', 'phase_name': 'Foundations',
            'session_label': 'Technique', 'steps': ['One-minute changes G-C'],
            'unit_title': 'Stage 1', 'unit_url': '', 'unit_body': 'Chords first.',
            'milestone': 'Play a song', 'progression': 'Add D when G-C is clean'}


def scenario_generated_origin_uses_pool_and_stores():
    from services import storage, program_lessons as pl
    storage.program_lessons_table.truncate()
    calls = {}
    def fake_pool(tier, api_key, system, prompt, **kw):
        calls['tier'] = tier
        return {'scenes': [{'type': 'say', 'text': 'Chords are shapes.'},
                           {'type': 'do', 'text': 'One-minute changes G-C',
                            'seconds': 60}], '_model': 'gemma-4-31b-it'}
    import services.model_pools as mp
    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        lid = pl.generate_for(_program_row(), _window(), {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(lid, "stored a lesson")
    check(calls['tier'] == 'background', "nobody is waiting — background tier")
    row = storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'})
    check(row['origin'] == 'generated' and row['model'] == 'gemma-4-31b-it',
          f"got {row}")


def scenario_cited_needs_its_page_or_stays_silent():
    """The unit HAS a url and the fetch fails: an outage, and an outage is
    never papered over -- no script, ever, not even a generated one."""
    from services import storage, program_lessons as pl, web
    storage.program_lessons_table.truncate()
    w = {**_window(), 'unit_url': 'https://jg.example/s1'}
    orig = web.read_page
    web.read_page = lambda url: None
    try:
        lid = pl.generate_for(_program_row(origin='cited'), w, {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        web.read_page = orig
    check(lid is None, "no page, no script")
    check(storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'}) is None,
          "and nothing stored")


def scenario_cited_with_no_url_falls_through_to_generated():
    """The unit has NO url at all -- not an outage, a different fact about
    the world. programs_curate's own anti-hallucination guard
    (_clean_units) legitimately emits exactly this shape whenever a unit's
    claimed source was never actually read, and the design's book-spine
    answer applies: structure generated from the plan's own steps, labelled
    honestly, rather than a slot permanently silent for a reason that has
    nothing to do with an outage. read_page must never even be called for
    a page that was never claimed."""
    from services import storage, program_lessons as pl, web
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    calls = {'read_page': 0}
    def spy_read_page(url):
        calls['read_page'] += 1
        return None
    def fake_pool(tier, api_key, system, prompt, **kw):
        return {'scenes': [{'type': 'say', 'text': 'Warm up first.'}],
               '_model': 'gemma-4-31b-it'}
    orig_read, orig_pool = web.read_page, mp.call_pool_json
    web.read_page, mp.call_pool_json = spy_read_page, fake_pool
    try:
        # _window() already sets unit_url='' -- no override needed.
        lid = pl.generate_for(_program_row(origin='cited'), _window(),
                              {'n': 1}, {'llm_gemini_api_key': 'k'})
    finally:
        web.read_page, mp.call_pool_json = orig_read, orig_pool
    check(lid, "a lesson was still stored -- structure, not silence")
    check(calls['read_page'] == 0,
          "no url means read_page is never called")
    row = storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'})
    check(row['origin'] == 'generated' and row['source_url'] == '',
          f"honestly labelled generated, no source claimed, got {row}")


def scenario_cited_carries_its_source():
    from services import storage, program_lessons as pl, web
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    w = {**_window(), 'unit_url': 'https://jg.example/s1'}
    orig_read, orig_pool = web.read_page, mp.call_pool_json
    web.read_page = lambda url: 'Stage 1: learn G and C. Practice changes.'
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'G and C first.'}],
        '_model': 'gemini-3.5-flash-lite'}
    try:
        lid = pl.generate_for(_program_row(origin='cited'), w, {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        web.read_page, mp.call_pool_json = orig_read, orig_pool
    row = storage.get_program_lesson('p9', {'phase_name': 'Foundations',
                                            'unit_n': 1,
                                            'session_label': 'Technique'})
    check(lid and row['origin'] == 'cited'
          and row['source_url'] == 'https://jg.example/s1', f"got {row}")


def scenario_generation_survives_a_pool_error():
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {'error': '429 quota', 'transient': True}
    try:
        lid = pl.generate_for(_program_row(), _window(), {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(lid is None, "a failed call stores nothing and raises nothing")


def scenario_existing_lesson_skips_before_spending_a_call():
    """Storage already refuses to overwrite a HAND EDIT; this covers the
    other half of the rule -- a slot that already has any lesson at all is
    not regenerated either, and that has to be checked before a model call
    (or a page fetch) is spent finding out."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    slot = pl.slot_of(_window(), unit_n=1)
    storage.upsert_program_lesson('p9', slot, {
        'origin': 'generated',
        'scenes': [{'type': 'say', 'text': 'already here'}]})
    calls = {'n': 0}
    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'scenes': [], '_model': 'x'}
    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        lid = pl.generate_for(_program_row(), _window(), {'n': 1},
                              {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(lid is None, "nothing new for a slot that already has a lesson")
    check(calls['n'] == 0, "no model call spent finding that out")
    row = storage.get_program_lesson('p9', slot)
    check(row['scenes'][0]['text'] == 'already here',
          f"the existing lesson is untouched, got {row}")


def scenario_a_slot_that_always_fails_stops_costing_a_call():
    """A script that always sanitizes to nothing used to re-spend a full
    model call every night, forever, silently. The failure is recorded
    instead: a scenes-less row carrying the reason and an attempt count,
    and after MAX_ATTEMPTS chargeable failures nothing else is spent."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    calls = {'n': 0}

    def fake_pool(*a, **k):
        calls['n'] += 1
        # Survives JSON, dies in the screens ('pounds' is a BODY_WORD) --
        # the exact shape that used to cost a call a night for the life of
        # the unit, because nothing recorded that it had failed before.
        return {'scenes': [{'type': 'say', 'text': 'Practise off 10 pounds.'}],
                '_model': 'gemma-4-31b-it'}

    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        for _ in range(6):
            pl.generate_for(_program_row(), _window(), {'n': 1},
                            {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(calls['n'] == pl.MAX_ATTEMPTS,
          f"six nights, {pl.MAX_ATTEMPTS} calls, got {calls['n']}")
    row = storage.get_program_lesson('p9', pl.slot_of(_window(), unit_n=1))
    check(row and not row['scenes'],
          f"the record holds no scenes, so the ladder still plays, got {row}")
    check(row.get('note'), f"and it says why, in words: {row}")
    check(pl.needs_lesson('p9', pl.slot_of(_window(), unit_n=1)) is False,
          "and the slot no longer asks for a call")


def scenario_a_transient_failure_is_recorded_but_never_counted():
    """A 429 tonight is not a reason to stop trying a slot that may live
    for weeks -- the pool already says which failures are transient, and
    only the others spend an attempt. The reason is still written down,
    because "every call fails and the toggle says lessons are on" is
    exactly the state that has to be legible somewhere."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    calls = {'n': 0}

    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'error': '429 quota', 'transient': True}

    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        for _ in range(5):
            pl.generate_for(_program_row(), _window(), {'n': 1},
                            {'llm_gemini_api_key': 'k'})
    finally:
        mp.call_pool_json = orig
    check(calls['n'] == 5, f"a transient failure keeps retrying, got {calls['n']}")
    row = storage.get_program_lesson('p9', pl.slot_of(_window(), unit_n=1))
    check(row and row.get('attempts') == 0 and '429' in (row.get('note') or ''),
          f"recorded, never counted, got {row}")


def scenario_a_hard_pool_error_does_spend_an_attempt():
    """The empty-api-key case: not transient, fails identically forever.
    That one has to stop, and has to leave the reason where a person
    looks."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.program_lessons_table.truncate()
    calls = {'n': 0}

    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'error': 'API key not valid', 'transient': False}

    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        for _ in range(6):
            pl.generate_for(_program_row(), _window(), {'n': 1},
                            {'llm_gemini_api_key': ''})
    finally:
        mp.call_pool_json = orig
    check(calls['n'] == pl.MAX_ATTEMPTS,
          f"it stops after {pl.MAX_ATTEMPTS}, got {calls['n']}")
    row = storage.get_program_lesson('p9', pl.slot_of(_window(), unit_n=1))
    check('API key' in (row.get('note') or ''),
          f"and the reason is readable, got {row}")


def scenario_a_recorded_failure_never_becomes_a_lesson():
    """The row that records a failure must stay invisible to every reader
    that asks "is there a lesson": no scenes means the fallback ladder,
    on every surface, exactly as before."""
    from services import storage, program_lessons as pl
    storage.program_lessons_table.truncate()
    slot = pl.slot_of(_window(), unit_n=1)
    pl._record_attempt('p9', slot, 'generated', '', 'nothing survived')
    row = storage.get_program_lesson('p9', slot)
    check(row['scenes'] == [], f"no scenes, got {row}")
    check(row['edited'] is False, "and it is not a hand edit")


def scenario_a_hand_edit_is_never_bounced_by_a_recorded_failure():
    """needs_lesson has to answer False for an edited slot BEFORE it looks
    at attempts, or a slot that failed three times and was then written by
    hand would read as backed-off rather than as done."""
    from services import storage, program_lessons as pl
    storage.program_lessons_table.truncate()
    slot = pl.slot_of(_window(), unit_n=1)
    storage.upsert_program_lesson('p9', slot, {
        'origin': 'generated', 'attempts': 99, 'edited': True,
        'scenes': [{'type': 'say', 'text': 'mine'}]})
    check(pl.needs_lesson('p9', slot) is False,
          "a slot that already has a script never asks for a call")


# --- the nightly sweep: tomorrow's lessons, written tonight -----------

def _due_fixture(cid='pl-c1', day_offset=1):
    """An active program with one evening claimed `day_offset` days out (a
    plain tomorrow by default), in the shape approve()/_emit_commitments
    actually write (services/programs.py) -- not a hand-typed guess at it.
    Two things a first draft of this fixture got wrong against that code:
    add_protected_commitment writes the dict it is given straight into
    storage and returns data['id'], it does not mint one, so the row
    needs an 'id' already on it; and the field is 'title' (what
    _emit_commitments writes), never 'label'. `day_offset` exists so the
    far edge of generate_due's scan (two days out, not one) can be proven
    reached by a window that lands NOWHERE nearer -- a single weekday
    picked 2-3 calendar days apart never repeats inside that span, so the
    commitment cannot accidentally also match a closer day."""
    import datetime
    from services import storage
    storage.programs_table.truncate()
    storage.program_lessons_table.truncate()
    storage.protected_commitments_table.truncate()
    target = datetime.date.today() + datetime.timedelta(days=day_offset)
    pid = storage.add_program({'member_id': 'kid', 'title': 'Play guitar',
                               'shape': {'sessions_per_week': 1, 'minutes': 20},
                               'phases': [{'name': 'Foundations',
                                           'steps': ['One-minute changes G-C'],
                                           'weeks': 4}]})
    storage.update_program(pid, {'state': 'active'})
    cid = storage.add_protected_commitment({
        'id': cid, 'member_id': 'kid', 'title': 'Practice', 'active': True,
        'days_of_week': [target.weekday()],
        'time_start': '17:00', 'time_end': '17:20'})
    row = storage.get_program(pid)
    storage.update_program(pid, {'emissions': {**row['emissions'],
                                               'commitment_ids': [cid]}})
    return pid


def _due_fixture_many(n=3, day_offset=1):
    """`n` active programs all claiming the same evening. The only way to
    put more than one window inside generate_due's three-day scan: a single
    commitment names one weekday, and a weekday repeats every seven days,
    so one program can never match twice in three."""
    import datetime
    from services import storage
    storage.programs_table.truncate()
    storage.program_lessons_table.truncate()
    storage.protected_commitments_table.truncate()
    target = datetime.date.today() + datetime.timedelta(days=day_offset)
    for i in range(n):
        pid = storage.add_program({
            'member_id': 'kid', 'title': f'Program {i}',
            'shape': {'sessions_per_week': 1, 'minutes': 20},
            'phases': [{'name': 'Foundations',
                        'steps': ['One-minute changes G-C'], 'weeks': 4}]})
        storage.update_program(pid, {'state': 'active'})
        cid = f'pl-many-{i}'
        storage.add_protected_commitment({
            'id': cid, 'member_id': 'kid', 'title': 'Practice', 'active': True,
            'days_of_week': [target.weekday()],
            'time_start': f'{17 + i}:00', 'time_end': f'{17 + i}:20'})
        row = storage.get_program(pid)
        storage.update_program(pid, {'emissions': {**row['emissions'],
                                                   'commitment_ids': [cid]}})


def scenario_the_sweep_is_capped_per_pass():
    """One pass may not be unbounded. Every slot it reaches is up to four
    pool candidates at a 180-second gemma timeout, and the marker is a
    date -- so an app that was down overnight and restarts at 07:00 runs
    the WHOLE sweep in the school run. The lookahead absorbs the rest."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture_many(3)
    calls = {'n': 0}

    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
                '_model': 'gemma-4-31b-it'}

    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        wrote = pl.generate_due(limit=2)
    finally:
        mp.call_pool_json = orig
    check(wrote == 2, f"three windows, a cap of two, got {wrote}")
    check(calls['n'] == 2, f"and exactly two calls spent, got {calls['n']}")


def scenario_the_pass_budget_counts_calls_not_windows():
    """A cap on iteration would be no cap on cost: a pass that spent its
    whole allowance on slots which already had a script would leave the one
    slot that needed a call unwritten while spending nothing."""
    import datetime
    from services import storage, programs, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture_many(3)
    tomorrow = datetime.date.today() + datetime.timedelta(days=1)
    ws = programs.practice_windows(tomorrow, tomorrow + datetime.timedelta(days=2))
    check(len(ws) == 3, f"the fixture must make three windows, got {len(ws)}")
    for w in ws[:2]:
        row = storage.get_program(w['program_id'])
        phase = programs.progress(row).get('phase') or {}
        unit = programs.unit_for(row, phase) or {}
        storage.upsert_program_lesson(
            w['program_id'], pl.slot_of(w, unit_n=int(unit.get('n') or 0)),
            {'origin': 'generated',
             'scenes': [{'type': 'say', 'text': 'already here'}]})
    calls = {'n': 0}

    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
                '_model': 'gemma-4-31b-it'}

    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        wrote = pl.generate_due(limit=1)
    finally:
        mp.call_pool_json = orig
    check(wrote == 1,
          f"the two already-scripted slots cost nothing and the third is "
          f"still written, got {wrote}")
    check(calls['n'] == 1, f"one call, as budgeted, got {calls['n']}")


def scenario_the_sweep_runs_on_the_slow_loop_not_the_push_loop():
    """It shipped awaited INLINE in the 30-second push loop, ahead of the
    departure notifications and practice pushes that loop exists to fire on
    time. poll_schedule is the loop that already owns slow work (a CP-SAT
    re-solve, a Google-backed trips rebuild) and has nothing behind it that
    cares about a minute. Scoped to poll_schedule's own body, not a bare
    substring search of a 15,000-line file."""
    import io
    import os
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = io.open(os.path.join(here, 'main.py'), encoding='utf-8').read()
    m = re.search(r'async def poll_schedule\(\):(.*?)await asyncio\.sleep\(300\)',
                  src, re.S)
    check(m, "poll_schedule's body is findable")
    check('generate_due' in (m.group(1) if m else ''),
          "the lesson sweep runs on the 300s loop")
    # `.generate_due` is the CALL; a bare 'generate_due' also matches the
    # prose in the comment above it, which is not a wiring.
    check(src.count('.generate_due') == 1,
          "and is called exactly once — never from two loops at all")


def scenario_generate_due_end_to_end():
    """The critical path, RUN rather than read: real storage, real windows,
    mocked model. One active program with a window tomorrow gets exactly
    one lesson; the second call the same day does nothing."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture('pl-c1')
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
        '_model': 'gemma-4-31b-it'}
    try:
        wrote = pl.generate_due()
        wrote_again = pl.generate_due()
    finally:
        mp.call_pool_json = orig
    check(wrote == 1, f"one window, one lesson, got {wrote}")
    check(wrote_again == 0, "self-throttled: one pass a day")


def scenario_sweep_respects_the_switch():
    """Off means off -- and genuinely off, not a coincidence: the fixture
    is fresh (no lesson yet exists for this slot), so a zero here can only
    come from the settings check, not from generate_for's own "already has
    a lesson" skip. storage.get_settings is reassigned directly rather than
    routed through update_settings: harness.py (and every other sweep test
    beside it, e.g. test_watchers.scenario_master_toggle) stubs get_settings
    to a constant lambda at import time, so a write through update_settings
    is never seen by a caller that reads get_settings back afterwards."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture('pl-c2')
    orig_settings = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'program_lessons_enabled': False}
    calls = {'n': 0}
    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'scenes': [{'type': 'say', 'text': 'x'}], '_model': 'x'}
    orig_pool = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        wrote = pl.generate_due()
    finally:
        storage.get_settings = orig_settings
        mp.call_pool_json = orig_pool
    check(wrote == 0, f"off means off, got {wrote}")
    check(calls['n'] == 0, "the switch stops the sweep before any model call")


def scenario_sweep_respects_programs_enabled_too():
    """The OLDER master toggle gates this sweep as well -- programs_enabled
    off has to cost the same zero, not just the new program_lessons_enabled,
    since the sweep is downstream of the whole Programs arc."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture('pl-c3')
    orig_settings = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'programs_enabled': False}
    orig_pool = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {'scenes': [], '_model': 'x'}
    try:
        wrote = pl.generate_due()
    finally:
        storage.get_settings = orig_settings
        mp.call_pool_json = orig_pool
    check(wrote == 0, f"programs_enabled off means off too, got {wrote}")


def scenario_generate_due_reaches_two_days_out():
    """The scan is practice_windows(tomorrow, tomorrow+2d), matching the
    design's Generation pipeline section, so a slot due the evening after
    tomorrow already gets tonight's sweep rather than waiting for the one
    right before it -- a skipped or failed night still leaves a second
    chance. The fixture's window lands ONLY on the far edge (today+3,
    i.e. tomorrow+2) and nowhere nearer, so a pass here proves the scan
    actually reaches that far -- under the narrower single-day-of-slack
    range this replaced, this exact fixture would have produced zero."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture('pl-c4', day_offset=3)
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
        '_model': 'gemma-4-31b-it'}
    try:
        wrote = pl.generate_due()
    finally:
        mp.call_pool_json = orig
    check(wrote == 1, f"a window two days past tomorrow is still reached, got {wrote}")


# --- the forced sweep: generate_due, but seen ---------------------------

def scenario_sweep_report_start_offset_zero_reaches_today():
    """generate_due starts at tomorrow; sweep_report's whole reason to
    take its own start_offset is that the forced button has to show
    TODAY's windows too. day_offset=0 lands the fixture's window on today
    and nowhere else inside a 4-day scan, so this fails under
    generate_due's own tomorrow-first start. Also the closest thing to an
    end-to-end proof that the report NAMES what it wrote, not just how
    many: the one entry has to carry the program, the phase, the unit and
    the date, plus the origin and scene count generate_for actually
    stored."""
    import datetime
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture('pl-so0', day_offset=0)
    today = datetime.date.today().isoformat()
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
        '_model': 'gemma-4-31b-it'}
    try:
        out = pl.sweep_report(start_offset=0)
    finally:
        mp.call_pool_json = orig
    check(out['wrote'] == 1 and out['skipped'] == 0,
          f"today's window is reached and written, got {out}")
    check(len(out['slots']) == 1, f"one slot named, got {out['slots']}")
    slot = out['slots'][0]
    check(slot['program'] == 'Play guitar', f"names the program, got {slot}")
    check(slot['phase'] == 'Foundations', f"names the phase, got {slot}")
    check(slot['unit_n'] == 0, f"names the unit, got {slot}")
    check(slot['date'] == today, f"names today, not tomorrow, got {slot}")
    check(slot['origin'] == 'generated' and slot['scenes'] == 1,
          f"names what generate_for actually stored, got {slot}")


def scenario_sweep_report_force_bypasses_the_marker():
    """A marker that already says today ran must not stop a person from
    running the sweep again by hand the same evening -- that is the entire
    point of the admin endpoint this backs. Without force the identical
    marker still gates it, exactly like generate_due; this proves both
    halves together so they can never quietly drift apart."""
    import datetime
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    _due_fixture('pl-fbm', day_offset=0)
    storage.set_app_state('program_lessons_swept',
                          datetime.date.today().isoformat())
    calls = {'n': 0}
    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}],
                '_model': 'gemma-4-31b-it'}
    orig = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        # Checked BETWEEN the two calls, not after both: forced spends a
        # real call by design, so calls['n'] can only prove blocked spent
        # none if it is read before forced has had a chance to run at all.
        blocked = pl.sweep_report(start_offset=0, force=False)
        check(blocked == {'wrote': 0, 'skipped': 0, 'slots': []},
              f"without force, today's own marker still blocks it, got {blocked}")
        check(calls['n'] == 0, "and no call was spent finding that out")
        forced = pl.sweep_report(start_offset=0, force=True)
    finally:
        mp.call_pool_json = orig
    check(forced['wrote'] == 1, f"force runs right past the same marker, got {forced}")


def scenario_sweep_report_lessons_switch_still_refuses_even_forced():
    """force bypasses the day marker and NOTHING else. The switch is the
    household saying it does not want this at all, so a forced call has to
    refuse exactly like generate_due already does -- never run a pass
    generate_due itself would have skipped."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    _due_fixture('pl-sw1', day_offset=0)
    orig_settings = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'program_lessons_enabled': False}
    calls = {'n': 0}
    def fake_pool(*a, **k):
        calls['n'] += 1
        return {'scenes': [{'type': 'say', 'text': 'x'}], '_model': 'x'}
    orig_pool = mp.call_pool_json
    mp.call_pool_json = fake_pool
    try:
        out = pl.sweep_report(start_offset=0, force=True)
    finally:
        storage.get_settings = orig_settings
        mp.call_pool_json = orig_pool
    check(out == {'wrote': 0, 'skipped': 0, 'slots': []},
          f"program_lessons_enabled off refuses even forced, got {out}")
    check(calls['n'] == 0, "the switch stops it before any model call")


def scenario_sweep_report_programs_switch_still_refuses_even_forced():
    """The OLDER master toggle gates the forced sweep too, same as it
    already gates generate_due (scenario_sweep_respects_programs_enabled_
    too) -- this sweep is downstream of the whole Programs arc, forced or
    not."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    _due_fixture('pl-sw2', day_offset=0)
    orig_settings = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'programs_enabled': False}
    orig_pool = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {'scenes': [], '_model': 'x'}
    try:
        out = pl.sweep_report(start_offset=0, force=True)
    finally:
        storage.get_settings = orig_settings
        mp.call_pool_json = orig_pool
    check(out == {'wrote': 0, 'skipped': 0, 'slots': []},
          f"programs_enabled off refuses too, forced or not, got {out}")


def scenario_sweep_report_names_why_a_slot_was_skipped():
    """The whole feature is the WHY -- generate_due itself only ever
    returns a count, which cannot tell these apart. Three programs share
    one evening, each skipped for a different reason: one already has a
    lesson, one already burned every attempt, and one asks for a call that
    comes back with nothing sanitize_script can use."""
    import datetime
    from services import storage, programs, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture_many(3, day_offset=0)
    ws = programs.practice_windows(
        datetime.date.today(), datetime.date.today() + datetime.timedelta(days=3))
    check(len(ws) == 3, f"the fixture must make three windows, got {len(ws)}")
    by_title = {w['title']: w for w in ws}
    w0, w1 = by_title['Program 0'], by_title['Program 1']
    storage.upsert_program_lesson(
        w0['program_id'], pl.slot_of(w0, unit_n=0),
        {'origin': 'generated',
         'scenes': [{'type': 'say', 'text': 'already here'}]})
    storage.upsert_program_lesson(
        w1['program_id'], pl.slot_of(w1, unit_n=0),
        {'origin': 'generated', 'scenes': [], 'attempts': pl.MAX_ATTEMPTS,
         'note': 'nothing survived'})
    orig = mp.call_pool_json
    # Valid JSON, nothing sanitize_script keeps -- generate_for spends the
    # call and still comes back with None.
    mp.call_pool_json = lambda *a, **k: {'scenes': [], '_model': 'x'}
    try:
        out = pl.sweep_report(start_offset=0, force=True)
    finally:
        mp.call_pool_json = orig
    reasons = {s['program']: s.get('skipped') for s in out['slots']}
    check(reasons.get('Program 0') == 'already has a lesson', f"got {reasons}")
    check(reasons.get('Program 1') == 'attempts exhausted', f"got {reasons}")
    check(reasons.get('Program 2') == 'generation returned nothing', f"got {reasons}")
    check(out['wrote'] == 0 and out['skipped'] == 3, f"got {out}")


def scenario_sweep_report_names_over_the_pass_limit():
    """The fourth reason: a slot that DOES need a call but the pass's own
    budget is already spent. Three fresh programs, a cap of two -- the
    third has to name itself as over the limit, not as any of the other
    three reasons, so tomorrow's pass (or another forced one) knows
    exactly what is still owed."""
    from services import storage, program_lessons as pl
    import services.model_pools as mp
    storage.set_app_state('program_lessons_swept', '')
    _due_fixture_many(3, day_offset=0)
    orig = mp.call_pool_json
    mp.call_pool_json = lambda *a, **k: {
        'scenes': [{'type': 'say', 'text': 'Chords are shapes.'}], '_model': 'x'}
    try:
        out = pl.sweep_report(start_offset=0, limit=2, force=True)
    finally:
        mp.call_pool_json = orig
    check(out['wrote'] == 2 and out['skipped'] == 1,
          f"two written, one held back by the limit, got {out}")
    over = [s for s in out['slots'] if s.get('skipped') == 'over the pass limit']
    check(len(over) == 1, f"named as over the pass limit, got {out['slots']}")


if __name__ == '__main__':
    scenario_scene_cap()
    scenario_text_cap_and_type_whitelist()
    scenario_unknown_primitive_dropped_bad_params_degrade()
    scenario_card_faces_run_the_same_screens_as_every_other_beat()
    scenario_card_faces_are_capped_like_every_other_string()
    scenario_the_stored_primitive_is_rebuilt_not_the_models_own_dict()
    scenario_every_primitive_kind_survives_the_rebuild()
    scenario_a_do_beat_is_session_shaped_not_an_afternoon()
    scenario_generated_origin_screens_physical_technique()
    scenario_body_screen_fires_on_every_origin()
    scenario_body_word_screen_fires_on_every_origin()
    scenario_hostile_non_list_scenes_never_raise()
    scenario_infinite_numerics_never_raise()
    scenario_slot_of()
    scenario_lesson_roundtrip_by_slot()
    scenario_upsert_replaces_same_slot()
    scenario_edited_is_never_regenerated_over()
    scenario_delete_one_lesson()
    scenario_delete_clears_a_program()
    scenario_none_slot_and_data_never_raise()
    scenario_generated_origin_uses_pool_and_stores()
    scenario_cited_needs_its_page_or_stays_silent()
    scenario_cited_with_no_url_falls_through_to_generated()
    scenario_cited_carries_its_source()
    scenario_generation_survives_a_pool_error()
    scenario_existing_lesson_skips_before_spending_a_call()
    scenario_a_slot_that_always_fails_stops_costing_a_call()
    scenario_a_transient_failure_is_recorded_but_never_counted()
    scenario_a_hard_pool_error_does_spend_an_attempt()
    scenario_a_recorded_failure_never_becomes_a_lesson()
    scenario_a_hand_edit_is_never_bounced_by_a_recorded_failure()
    scenario_the_sweep_is_capped_per_pass()
    scenario_the_pass_budget_counts_calls_not_windows()
    scenario_the_sweep_runs_on_the_slow_loop_not_the_push_loop()
    scenario_generate_due_end_to_end()
    scenario_sweep_respects_the_switch()
    scenario_sweep_respects_programs_enabled_too()
    scenario_generate_due_reaches_two_days_out()
    scenario_sweep_report_start_offset_zero_reaches_today()
    scenario_sweep_report_force_bypasses_the_marker()
    scenario_sweep_report_lessons_switch_still_refuses_even_forced()
    scenario_sweep_report_programs_switch_still_refuses_even_forced()
    scenario_sweep_report_names_why_a_slot_was_skipped()
    scenario_sweep_report_names_over_the_pass_limit()
    print("test_program_lessons OK")
