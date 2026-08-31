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
    scenario_generate_due_end_to_end()
    scenario_sweep_respects_the_switch()
    scenario_sweep_respects_programs_enabled_too()
    scenario_generate_due_reaches_two_days_out()
    print("test_program_lessons OK")
