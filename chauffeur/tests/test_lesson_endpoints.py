"""Lessons ride the same permission rails as the programs they belong to.

Read, hand-edit, clear -- the only door either program_lessons.py's
sanitizer or storage.py's lesson CRUD has onto HTTP. Every rule tested here
is a rule those two modules already enforce (sanitize_script's caps and
screens, upsert_program_lesson's edited:true refusal); this file is only
proving the endpoint asks them correctly and gates who is asking.
"""
from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from fastapi import HTTPException

from services import storage


class Req:
    """Same shape as test_programs_endpoints.py's own Req -- a minimal
    stand-in carrying only what `_acting_id`/`_auth.acting_member` read: a
    bearer token on the header."""
    def __init__(self, token=None):
        self.headers = {'x-member-token': token} if token else {}
        self.query_params = {}


def _denied(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except HTTPException as e:
        return e.status_code


def _reset():
    storage.programs_table.truncate()
    storage.program_lessons_table.truncate()
    storage.members_table.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'kid', 'name': 'Lily', 'role': 'child'})
    pid = storage.add_program({'member_id': 'kid', 'title': 'Play guitar',
                               'shape': {'sessions_per_week': 2, 'minutes': 20}})
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                        'session_label': ''},
                                  {'origin': 'generated',
                                   'scenes': [{'type': 'say', 'text': 'hi'}]})
    return pid


def scenario_endpoints_exist():
    import main
    lesson_routes = [r for r in main.app.routes
                     if getattr(r, 'path', None) ==
                     '/api/programs/{program_id}/lesson']
    methods = set()
    for r in lesson_routes:
        methods |= (getattr(r, 'methods', None) or set())
    check({'GET', 'PUT', 'DELETE'} <= methods,
          f"the lesson must be reachable by hand for read, edit and clear, "
          f"got {methods}")


def scenario_the_wall_route_exists_and_is_wall_tier():
    """The one lesson route a panel may call. A `?panel=true` board
    identifies as DEVICE, so `_program_list_scope` hands the signed-in read
    `_NOBODY` and it answers null forever -- correctly, since that route
    returns the stored row. Without a WALL-tier projection beside it the
    wall board could only ever play the fallback ladder, while the arc
    claimed the wall and the hand opened the same session."""
    import main
    from services import auth
    paths = [getattr(r, 'path', None) for r in main.app.routes]
    check('/api/programs/{program_id}/lesson-scenes' in paths,
          "the scenes-only route is registered")
    check(auth.resolve('GET', '/api/programs/{program_id}/lesson-scenes')
          == auth.WALL, "and a panel may call it")
    check(auth.resolve('GET', '/api/programs/{program_id}/lesson')
          == auth.SIGNED_IN, "while the row read beside it stays signed-in")


def scenario_the_wall_route_returns_scenes_only():
    """Scoped by what it RETURNS, the way api/programs/celebrations is --
    never the stored row. No id, no model, no edited flag, no created_at:
    a wall is read by whoever is in the room."""
    pid = _reset()
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                        'session_label': ''},
                                  {'origin': 'cited',
                                   'source_url': 'https://jg.example/s1',
                                   'model': 'gemma-4-31b-it', 'edited': True,
                                   'scenes': [{'type': 'say', 'text': 'hi'}]})
    import main
    res = main.program_lesson_scenes(pid, phase_name='F', unit_n=1,
                                     session_label='')
    lesson = res['lesson']
    check(set(lesson) == {'scenes', 'origin', 'source_url'},
          f"scenes, origin and the link, nothing else, got {sorted(lesson)}")
    check(lesson['scenes'][0]['text'] == 'hi', f"got {lesson}")
    check(lesson['source_url'] == 'https://jg.example/s1',
          "the wall says where its lesson came from too")


def scenario_the_wall_route_reads_null_for_anything_it_cannot_resolve():
    """A missing program, an unknown slot, a bad unit_n and a slot whose
    only row is a recorded failure all read the same: null, which every
    surface plays as the plain steps. Nothing here is a refusal wearing a
    read's clothes."""
    pid = _reset()
    import main
    check(main.program_lesson_scenes('nope', phase_name='F', unit_n=1,
                                     session_label='')['lesson'] is None,
          "no such program")
    check(main.program_lesson_scenes(pid, phase_name='Other', unit_n=1,
                                     session_label='')['lesson'] is None,
          "no such slot")
    check(main.program_lesson_scenes(pid, phase_name='F', unit_n=10 ** 30,
                                     session_label='')['lesson'] is None,
          "a huge finite unit_n is a null read, never a crash")
    check(main.program_lesson_scenes(pid, phase_name='F', unit_n=None,
                                     session_label='')['lesson'] is None,
          "and None reads as unit 0, which holds nothing here")
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 2,
                                        'session_label': ''},
                                  {'origin': 'generated', 'scenes': [],
                                   'attempts': 3, 'note': 'API key not valid'})
    check(main.program_lesson_scenes(pid, phase_name='F', unit_n=2,
                                     session_label='')['lesson'] is None,
          "a recorded failure is not a lesson — the wall plays the steps")


def scenario_owner_reads_their_lesson():
    """The control-center's own trusted-place reading -- no token, no
    claim -- sees the household's lessons, same as it sees the whole
    household's programs elsewhere on this page."""
    pid = _reset()
    import main
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=1,
                                      session_label='', request=None)
    check(res['lesson'] and res['lesson']['scenes'][0]['text'] == 'hi',
          f"got {res}")


def scenario_a_sibling_gets_null_not_the_lesson():
    """Read scope here is deliberately softer than the write gate: a
    resolved child who does not own this program learns nothing by asking,
    not even that a lesson exists -- null and 'nothing generated yet' are
    indistinguishable, which is exactly what the player's fallback ladder
    already treats them as. The owner, and a parent, both still see it."""
    pid = _reset()
    import main
    storage.add_member({'id': 'sib', 'name': 'Sam', 'role': 'child'})
    sib_token = storage.create_member_token('sib')
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=1,
                                      session_label='', request=Req(sib_token))
    check(res == {'lesson': None},
          f"a sibling must see nothing, not even that it exists, got {res}")

    kid_token = storage.create_member_token('kid')
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=1,
                                      session_label='', request=Req(kid_token))
    check(res['lesson'] and res['lesson']['scenes'][0]['text'] == 'hi',
          f"the owner must see their own, got {res}")

    mom_token = storage.create_member_token('mom')
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=1,
                                      session_label='', request=Req(mom_token))
    check(res['lesson'] and res['lesson']['scenes'][0]['text'] == 'hi',
          f"a parent must see the household's, got {res}")


def scenario_a_missing_program_reads_as_a_null_lesson():
    import main
    res = main.get_program_lesson_api('nope', phase_name='F', unit_n=1,
                                      session_label='', request=None)
    check(res == {'lesson': None}, f"got {res}")


# --- unit_n magnitude (fix round 1): int() converts any FINITE magnitude
# without complaint -- 10**30 and 1e300 are both ordinary valid JSON numbers
# -- so a huge-but-finite unit_n is a different failure shape from the
# non-numeric-string / literal-Infinity cases below (those raise inside
# int() itself; this one does not). Unchecked, it would reach
# storage._lesson_query's sqlite3 driver and raise THAT layer's own
# unhandled OverflowError converting an out-of-range Python int to a SQLite
# INTEGER. GET reads it the same way it reads a sibling's lesson or a
# missing program: null, never a crash and never a 403/400 -- an
# unreachable slot is an unreachable slot.

def scenario_a_huge_finite_unit_n_reads_as_no_lesson_on_get():
    pid = _reset()
    import main
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=10**30,
                                      session_label='', request=None)
    check(res == {'lesson': None}, f"got {res}")


def scenario_a_huge_finite_float_unit_n_reads_as_no_lesson_on_get():
    pid = _reset()
    import main
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=1e300,
                                      session_label='', request=None)
    check(res == {'lesson': None}, f"got {res}")


# --- unit_n type (fix round 2): fix round 1's own guard compared unit_n
# against _LESSON_UNIT_N_MAX BEFORE normalising it, which is exactly the
# defect class the round existed to close, just on values the round's own
# probes never tried. `None` (`0 <= None` raises TypeError) is a NEW gap
# fix round 1 introduced on GET/DELETE -- PUT was always safe here, since
# its int(body.get('unit_n') or 0) already normalised before comparing. A
# non-numeric string on GET/DELETE is a PRE-EXISTING gap neither round
# fixed until now: pre-round-1 it escaped as a ValueError from storage's
# own int(); post-round-1 it escaped as a TypeError from main.py's
# unnormalised comparison instead -- never actually fixed, just moved.

def scenario_a_none_unit_n_is_treated_as_zero_on_get():
    """Proves the fix restores the pre-round-1 behaviour exactly -- None
    resolves to slot 0 and that slot's real content comes back -- not just
    that it stopped crashing."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'shape': {'sessions_per_week': 2, 'minutes': 20}})
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 0,
                                        'session_label': ''},
                                  {'origin': 'generated',
                                   'scenes': [{'type': 'say', 'text': 'zero slot'}]})
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n=None,
                                      session_label='', request=None)
    check(res['lesson'] and res['lesson']['scenes'][0]['text'] == 'zero slot',
          f"None must coerce to 0 and find that slot, got {res}")


def scenario_a_non_numeric_unit_n_reads_as_no_lesson_on_get():
    pid = _reset()
    import main
    res = main.get_program_lesson_api(pid, phase_name='F', unit_n='abc',
                                      session_label='', request=None)
    check(res == {'lesson': None}, f"got {res}")


def scenario_edit_sanitizes_and_marks_edited():
    pid = _reset()
    import main
    res = main.put_program_lesson_api(pid, body={
        'phase_name': 'F', 'unit_n': 1, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'mine'},
                   {'type': 'shout', 'text': 'dropped'}]}, request=None)
    check(res.get('status') == 'ok', f"got {res}")
    row = storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''})
    check(row['edited'] is True and len(row['scenes']) == 1,
          f"sanitized and marked, got {row}")


def scenario_editing_a_cited_lesson_keeps_cited_screening():
    """The sanitizer runs on every PUT using the slot's EXISTING origin --
    never reset to 'generated' by the mere act of a hand edit -- so a cited
    lesson keeps the citation's looser physical-technique rule (a real
    teacher's page may say 'relax your wrist'; the generated-only screen
    would otherwise silently drop that scene)."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'shape': {'sessions_per_week': 2, 'minutes': 20}})
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                        'session_label': ''},
                                  {'origin': 'cited',
                                   'source_url': 'https://teacher.example/lesson',
                                   'scenes': [{'type': 'say', 'text': 'hi'}]})
    res = main.put_program_lesson_api(pid, body={
        'phase_name': 'F', 'unit_n': 1, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'relax your wrist a little'}]},
        request=None)
    check(res.get('status') == 'ok', f"got {res}")
    row = storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''})
    check(row['origin'] == 'cited', f"origin must survive the edit, got {row}")
    check(row['source_url'] == 'https://teacher.example/lesson',
          f"and so must the citation, got {row}")
    check(len(row['scenes']) == 1 and 'wrist' in row['scenes'][0]['text'],
          f"cited text keeps the looser screen, got {row['scenes']}")


def scenario_an_edit_that_sanitizes_to_nothing_is_a_soft_error():
    """Nothing survivable is a fine answer for the sanitizer -- the
    fallback ladder plays the plain steps either way -- but it must not
    silently wipe a slot that already held real content."""
    pid = _reset()
    import main
    res = main.put_program_lesson_api(pid, body={
        'phase_name': 'F', 'unit_n': 1, 'session_label': '',
        'scenes': [{'type': 'shout', 'text': 'nope'}]}, request=None)
    check(res.get('status') == 'error', f"got {res}")
    row = storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''})
    check(row['scenes'][0]['text'] == 'hi',
          f"the slot's existing lesson must survive a refused edit, got {row}")


def scenario_a_malformed_unit_n_is_a_400_not_a_crash():
    """storage's own int(slot.get('unit_n') or 0) raises a bare ValueError
    on anything it cannot parse -- built assuming a slot this module minted
    itself. The HTTP boundary is the one place a raw request body reaches
    that call, so it is the one place that has to turn a bad TYPE into a
    400 instead of a 500."""
    pid = _reset()
    import main
    code = _denied(main.put_program_lesson_api, pid, body={
        'phase_name': 'F', 'unit_n': 'not-a-number', 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'hi'}]}, request=None)
    check(code == 400, f"a non-numeric unit_n must be a 400, got {code}")


def scenario_an_infinite_unit_n_is_a_400_not_a_crash():
    """int(float('inf')) raises OverflowError, not ValueError or TypeError
    -- and JSON hands this door exactly that shape for free, since a bare
    `Infinity` token parses under json.loads."""
    pid = _reset()
    import main
    code = _denied(main.put_program_lesson_api, pid, body={
        'phase_name': 'F', 'unit_n': float('inf'), 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'hi'}]}, request=None)
    check(code == 400, f"an infinite unit_n must be a 400, got {code}")


def scenario_a_huge_finite_unit_n_is_a_400_on_put():
    """The failure shape the try/except above does NOT catch: int(10**30)
    raises nothing at all, so only the explicit range check below it stands
    between this and storage's own unhandled OverflowError."""
    pid = _reset()
    import main
    code = _denied(main.put_program_lesson_api, pid, body={
        'phase_name': 'F', 'unit_n': 10**30, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'hi'}]}, request=None)
    check(code == 400, f"a huge finite unit_n must be a 400, got {code}")


def scenario_a_huge_finite_float_unit_n_is_a_400_on_put():
    pid = _reset()
    import main
    code = _denied(main.put_program_lesson_api, pid, body={
        'phase_name': 'F', 'unit_n': 1e300, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'hi'}]}, request=None)
    check(code == 400,
          f"a huge finite float unit_n must be a 400, got {code}")


def scenario_a_none_unit_n_is_treated_as_zero_on_put():
    """PUT was never vulnerable to fix round 1's gap -- its own
    int(body.get('unit_n') or 0) already normalised None before any
    comparison existed. Added for symmetry with the GET/DELETE fix and to
    lock the shared behaviour in across all three verbs together."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'shape': {'sessions_per_week': 2, 'minutes': 20}})
    res = main.put_program_lesson_api(pid, body={
        'phase_name': 'F', 'unit_n': None, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'zero slot'}]}, request=None)
    check(res.get('status') == 'ok', f"got {res}")
    row = storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 0,
                                           'session_label': ''})
    check(row and row['scenes'][0]['text'] == 'zero slot',
          f"None must coerce to 0 and land on that slot, got {row}")


def scenario_an_abc_unit_n_is_a_400_on_put():
    """Same shape scenario_a_malformed_unit_n_is_a_400_not_a_crash already
    covers with a different string -- kept as its own scenario so all
    three verbs are tested against the identical 'abc' value the coordinator
    named, for direct comparison."""
    pid = _reset()
    import main
    code = _denied(main.put_program_lesson_api, pid, body={
        'phase_name': 'F', 'unit_n': 'abc', 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'hi'}]}, request=None)
    check(code == 400, f"got {code}")


def scenario_delete_clears_the_slot():
    pid = _reset()
    import main
    main.delete_program_lesson_api(pid, phase_name='F', unit_n=1,
                                   session_label='', request=None)
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''}) is None,
          "gone; the sweep will write a fresh one")


def scenario_a_huge_finite_unit_n_is_a_400_on_delete():
    """DELETE's unit_n arrives as a plain function argument in every
    existing scenario here (the direct-call idiom), so the FastAPI query
    typing that would reject a non-numeric string never enters into it --
    but magnitude is not shape, and nothing upstream of the handler bounds
    it either."""
    pid = _reset()
    import main
    code = _denied(main.delete_program_lesson_api, pid, phase_name='F',
                   unit_n=10**30, session_label='', request=None)
    check(code == 400, f"a huge finite unit_n must be a 400, got {code}")
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''}) is not None,
          "the refused delete must not have touched the real slot")


def scenario_a_huge_finite_float_unit_n_is_a_400_on_delete():
    pid = _reset()
    import main
    code = _denied(main.delete_program_lesson_api, pid, phase_name='F',
                   unit_n=1e300, session_label='', request=None)
    check(code == 400,
          f"a huge finite float unit_n must be a 400, got {code}")
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''}) is not None,
          "the refused delete must not have touched the real slot")


def scenario_a_none_unit_n_is_treated_as_zero_on_delete():
    """Fix round 2: DELETE carried the exact same fix-round-1 gap as GET
    (`0 <= None` raising TypeError before the value was ever normalised).
    None must coerce to 0 and clear THAT slot, not crash and not touch the
    unrelated real slot at unit_n=1."""
    _reset()
    import main
    pid = storage.add_program({'member_id': 'kid', 'title': 'Guitar',
                               'shape': {'sessions_per_week': 2, 'minutes': 20}})
    storage.upsert_program_lesson(pid, {'phase_name': 'F', 'unit_n': 0,
                                        'session_label': ''},
                                  {'origin': 'generated',
                                   'scenes': [{'type': 'say', 'text': 'zero slot'}]})
    main.delete_program_lesson_api(pid, phase_name='F', unit_n=None,
                                   session_label='', request=None)
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 0,
                                           'session_label': ''}) is None,
          "None must coerce to 0 and clear that slot")


def scenario_a_non_numeric_unit_n_is_a_400_on_delete():
    pid = _reset()
    import main
    code = _denied(main.delete_program_lesson_api, pid, phase_name='F',
                   unit_n='abc', session_label='', request=None)
    check(code == 400, f"got {code}")
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''}) is not None,
          "the refused delete must not have touched the real slot")


# --- Denial: ownership, not role, exactly as test_programs_endpoints.py's
# own "ownership, not role" block already established for every other write
# on a program. A lesson belongs to the program it is slotted under, so the
# same rule has to hold one layer down.

def scenario_a_child_cannot_edit_a_siblings_lesson():
    _reset()
    import main
    mom_pid = storage.add_program({'member_id': 'mom', 'title': 'Spanish',
                                   'shape': {'sessions_per_week': 1, 'minutes': 20}})
    kid_token = storage.create_member_token('kid')
    code = _denied(main.put_program_lesson_api, mom_pid, body={
        'phase_name': 'F', 'unit_n': 1, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'nope'}]},
        request=Req(kid_token))
    check(code == 403,
          f"a child editing a PARENT's program's lesson must be refused, got {code}")
    check(storage.get_program_lesson(mom_pid, {'phase_name': 'F', 'unit_n': 1,
                                               'session_label': ''}) is None,
          "and nothing was written")


def scenario_a_child_cannot_delete_a_siblings_lesson():
    _reset()
    import main
    mom_pid = storage.add_program({'member_id': 'mom', 'title': 'Spanish',
                                   'shape': {'sessions_per_week': 1, 'minutes': 20}})
    storage.upsert_program_lesson(mom_pid, {'phase_name': 'F', 'unit_n': 1,
                                            'session_label': ''},
                                  {'origin': 'generated',
                                   'scenes': [{'type': 'say', 'text': 'hola'}]})
    kid_token = storage.create_member_token('kid')
    code = _denied(main.delete_program_lesson_api, mom_pid, phase_name='F',
                   unit_n=1, session_label='', request=Req(kid_token))
    check(code == 403,
          f"a child deleting a PARENT's program's lesson must be refused, got {code}")
    check(storage.get_program_lesson(mom_pid, {'phase_name': 'F', 'unit_n': 1,
                                               'session_label': ''}) is not None,
          "and it survives the refused attempt")


def scenario_a_parent_can_edit_a_childs_lesson():
    """The mirror of the denial above -- a parent standing in is exactly
    as reachable here as it already is for session/milestone/pause/drop."""
    pid = _reset()
    import main
    mom_token = storage.create_member_token('mom')
    res = main.put_program_lesson_api(pid, body={
        'phase_name': 'F', 'unit_n': 1, 'session_label': '',
        'scenes': [{'type': 'say', 'text': 'from mom'}]},
        request=Req(mom_token))
    check(res.get('status') == 'ok', f"got {res}")
    row = storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''})
    check(row['scenes'][0]['text'] == 'from mom', f"got {row}")


# --- POST /api/programs/lessons/sweep: the forced, seen sweep -----------
# The verb itself (which slots get written, why the rest were skipped) is
# program_lessons.sweep_report's own job and is proven in depth over in
# test_program_lessons.py; this file's job, same as every scenario above
# it, is only that the endpoint asks it correctly and gates who is asking.
# sweep_report is monkeypatched throughout so these never spend a model
# call and never need a real practice-window fixture to prove the wiring.

def _fake_sweep_report(report=None):
    """A stand-in for program_lessons.sweep_report that records every call
    it received (kwargs only -- the endpoint calls it that way) and hands
    back a fixed, well-shaped report."""
    calls = []
    def fake(**kw):
        calls.append(kw)
        return dict(report or {'wrote': 0, 'skipped': 0, 'slots': []})
    return calls, fake


def scenario_forced_sweep_endpoint_exists_as_post():
    import main
    routes = [r for r in main.app.routes
             if getattr(r, 'path', None) == '/api/programs/lessons/sweep']
    methods = set()
    for r in routes:
        methods |= (getattr(r, 'methods', None) or set())
    check('POST' in methods,
          f"the forced sweep must be reachable by hand, got {methods}")


def scenario_forced_sweep_refuses_a_child():
    """Household-wide work, same rule as approve_program: a child cannot
    force a sweep across every active program, only a parent/adult (or the
    control-center standing in for one) can."""
    _reset()
    import main
    kid_token = storage.create_member_token('kid')
    code = _denied(main.sweep_program_lessons_now, body={},
                   request=Req(kid_token))
    check(code == 403, f"a child cannot force the household sweep, got {code}")


def scenario_forced_sweep_allows_a_parent():
    _reset()
    import main
    from services import program_lessons as pl
    calls, fake = _fake_sweep_report()
    orig = pl.sweep_report
    pl.sweep_report = fake
    try:
        mom_token = storage.create_member_token('mom')
        res = main.sweep_program_lessons_now(body={}, request=Req(mom_token))
    finally:
        pl.sweep_report = orig
    check(len(calls) == 1, f"a parent reaches sweep_report, got {calls}")
    check(res == {'wrote': 0, 'skipped': 0, 'slots': []}, f"got {res}")


def scenario_forced_sweep_allows_the_control_center_with_no_claim():
    """request=None is the trusted-place reading _mind_actor already gives
    every other control-center admin action; _approver_of_record stands in
    the household's own parent of record, exactly like approve_program
    already does."""
    _reset()
    import main
    from services import program_lessons as pl
    calls, fake = _fake_sweep_report()
    orig = pl.sweep_report
    pl.sweep_report = fake
    try:
        res = main.sweep_program_lessons_now(body={}, request=None)
    finally:
        pl.sweep_report = orig
    check(len(calls) == 1, f"the control-center reaches sweep_report, got {calls}")
    check(res == {'wrote': 0, 'skipped': 0, 'slots': []}, f"got {res}")


def scenario_forced_sweep_refuses_when_programs_are_off():
    """The switches are never bypassed, only the day marker is -- and the
    refusal has to happen BEFORE sweep_report is ever called, in words,
    rather than a quiet empty-looking report indistinguishable from 'ran
    and found nothing due'."""
    _reset()
    import main
    from services import program_lessons as pl
    calls, fake = _fake_sweep_report()
    orig_sweep = pl.sweep_report
    pl.sweep_report = fake
    orig_settings = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'programs_enabled': False}
    try:
        res = main.sweep_program_lessons_now(body={}, request=None)
    finally:
        storage.get_settings = orig_settings
        pl.sweep_report = orig_sweep
    check(res.get('status') == 'error' and res.get('message'),
          f"a clear refusal, got {res}")
    check(len(calls) == 0,
          "sweep_report is never called once the switch says no")


def scenario_forced_sweep_refuses_when_lessons_are_off():
    _reset()
    import main
    from services import program_lessons as pl
    calls, fake = _fake_sweep_report()
    orig_sweep = pl.sweep_report
    pl.sweep_report = fake
    orig_settings = storage.get_settings
    storage.get_settings = lambda: {'calendar_ids': ['primary'],
                                    'program_lessons_enabled': False}
    try:
        res = main.sweep_program_lessons_now(body={}, request=None)
    finally:
        storage.get_settings = orig_settings
        pl.sweep_report = orig_sweep
    check(res.get('status') == 'error' and res.get('message'),
          f"a clear refusal, got {res}")
    check(len(calls) == 0,
          "sweep_report is never called once the switch says no")


def scenario_forced_sweep_passes_start_offset_zero_and_force_true():
    """The two things that make this button different from waiting for
    tonight: it scans from TODAY (start_offset=0, not generate_due's own
    1) and it runs regardless of whether today's automatic pass already
    happened (force=True). Defaults for days/limit mirror the docstring:
    three days, MAX_SLOTS_PER_PASS slots."""
    _reset()
    import main
    from services import program_lessons as pl
    calls, fake = _fake_sweep_report()
    orig = pl.sweep_report
    pl.sweep_report = fake
    try:
        res = main.sweep_program_lessons_now(body={}, request=None)
    finally:
        pl.sweep_report = orig
    check(len(calls) == 1, f"called once, got {calls}")
    kw = calls[0]
    check(kw.get('start_offset') == 0, f"scans from today, got {kw}")
    check(kw.get('force') is True, f"bypasses the marker, got {kw}")
    check(kw.get('days') == 3, f"default days, got {kw}")
    check(kw.get('limit') == pl.MAX_SLOTS_PER_PASS, f"default limit, got {kw}")
    check(res == {'wrote': 0, 'skipped': 0, 'slots': []},
          "the report comes back exactly as sweep_report returned it")


def scenario_forced_sweep_passes_custom_days_and_limit():
    _reset()
    import main
    from services import program_lessons as pl
    calls, fake = _fake_sweep_report()
    orig = pl.sweep_report
    pl.sweep_report = fake
    try:
        main.sweep_program_lessons_now(body={'days': 7, 'limit': 2},
                                       request=None)
    finally:
        pl.sweep_report = orig
    check(calls[0].get('days') == 7 and calls[0].get('limit') == 2,
          f"a caller's own days/limit reach sweep_report, got {calls[0]}")


def scenario_forced_sweep_a_non_numeric_days_is_a_400():
    """Same shape as unit_n's own boundary above: a bad TYPE must land as
    a 400, never a 500 out of a bare int()."""
    _reset()
    import main
    code = _denied(main.sweep_program_lessons_now,
                   body={'days': 'abc'}, request=None)
    check(code == 400, f"a non-numeric days must be a 400, got {code}")


def scenario_forced_sweep_a_non_numeric_limit_is_a_400():
    _reset()
    import main
    code = _denied(main.sweep_program_lessons_now,
                   body={'limit': 'abc'}, request=None)
    check(code == 400, f"a non-numeric limit must be a 400, got {code}")


def scenario_forced_sweep_an_infinite_limit_is_a_400():
    """int(float('inf')) raises OverflowError, not ValueError or
    TypeError -- and JSON hands this door exactly that shape for free, a
    bare Infinity token parsing cleanly under json.loads."""
    _reset()
    import main
    code = _denied(main.sweep_program_lessons_now,
                   body={'limit': float('inf')}, request=None)
    check(code == 400, f"an infinite limit must be a 400, got {code}")


def scenario_forced_sweep_a_huge_finite_days_is_a_400():
    """The failure shape the try/except alone does not catch: int(10**30)
    raises nothing, so only the explicit range check stops it reaching
    datetime.timedelta downstream."""
    _reset()
    import main
    code = _denied(main.sweep_program_lessons_now,
                   body={'days': 10**30}, request=None)
    check(code == 400, f"a huge finite days must be a 400, got {code}")


def scenario_forced_sweep_a_negative_days_is_a_400():
    _reset()
    import main
    code = _denied(main.sweep_program_lessons_now,
                   body={'days': -1}, request=None)
    check(code == 400, f"a negative days must be a 400, got {code}")


if __name__ == '__main__':
    scenario_endpoints_exist()
    scenario_the_wall_route_exists_and_is_wall_tier()
    scenario_the_wall_route_returns_scenes_only()
    scenario_the_wall_route_reads_null_for_anything_it_cannot_resolve()
    scenario_owner_reads_their_lesson()
    scenario_a_sibling_gets_null_not_the_lesson()
    scenario_a_missing_program_reads_as_a_null_lesson()
    scenario_a_huge_finite_unit_n_reads_as_no_lesson_on_get()
    scenario_a_huge_finite_float_unit_n_reads_as_no_lesson_on_get()
    scenario_a_none_unit_n_is_treated_as_zero_on_get()
    scenario_a_non_numeric_unit_n_reads_as_no_lesson_on_get()
    scenario_edit_sanitizes_and_marks_edited()
    scenario_editing_a_cited_lesson_keeps_cited_screening()
    scenario_an_edit_that_sanitizes_to_nothing_is_a_soft_error()
    scenario_a_malformed_unit_n_is_a_400_not_a_crash()
    scenario_an_infinite_unit_n_is_a_400_not_a_crash()
    scenario_a_huge_finite_unit_n_is_a_400_on_put()
    scenario_a_huge_finite_float_unit_n_is_a_400_on_put()
    scenario_a_none_unit_n_is_treated_as_zero_on_put()
    scenario_an_abc_unit_n_is_a_400_on_put()
    scenario_delete_clears_the_slot()
    scenario_a_huge_finite_unit_n_is_a_400_on_delete()
    scenario_a_huge_finite_float_unit_n_is_a_400_on_delete()
    scenario_a_none_unit_n_is_treated_as_zero_on_delete()
    scenario_a_non_numeric_unit_n_is_a_400_on_delete()
    scenario_a_child_cannot_edit_a_siblings_lesson()
    scenario_a_child_cannot_delete_a_siblings_lesson()
    scenario_a_parent_can_edit_a_childs_lesson()
    scenario_forced_sweep_endpoint_exists_as_post()
    scenario_forced_sweep_refuses_a_child()
    scenario_forced_sweep_allows_a_parent()
    scenario_forced_sweep_allows_the_control_center_with_no_claim()
    scenario_forced_sweep_refuses_when_programs_are_off()
    scenario_forced_sweep_refuses_when_lessons_are_off()
    scenario_forced_sweep_passes_start_offset_zero_and_force_true()
    scenario_forced_sweep_passes_custom_days_and_limit()
    scenario_forced_sweep_a_non_numeric_days_is_a_400()
    scenario_forced_sweep_a_non_numeric_limit_is_a_400()
    scenario_forced_sweep_an_infinite_limit_is_a_400()
    scenario_forced_sweep_a_huge_finite_days_is_a_400()
    scenario_forced_sweep_a_negative_days_is_a_400()
    print("test_lesson_endpoints OK")
