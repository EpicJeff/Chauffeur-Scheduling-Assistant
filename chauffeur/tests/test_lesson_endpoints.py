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


def scenario_delete_clears_the_slot():
    pid = _reset()
    import main
    main.delete_program_lesson_api(pid, phase_name='F', unit_n=1,
                                   session_label='', request=None)
    check(storage.get_program_lesson(pid, {'phase_name': 'F', 'unit_n': 1,
                                           'session_label': ''}) is None,
          "gone; the sweep will write a fresh one")


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


if __name__ == '__main__':
    scenario_endpoints_exist()
    scenario_owner_reads_their_lesson()
    scenario_a_sibling_gets_null_not_the_lesson()
    scenario_a_missing_program_reads_as_a_null_lesson()
    scenario_edit_sanitizes_and_marks_edited()
    scenario_editing_a_cited_lesson_keeps_cited_screening()
    scenario_an_edit_that_sanitizes_to_nothing_is_a_soft_error()
    scenario_a_malformed_unit_n_is_a_400_not_a_crash()
    scenario_an_infinite_unit_n_is_a_400_not_a_crash()
    scenario_delete_clears_the_slot()
    scenario_a_child_cannot_edit_a_siblings_lesson()
    scenario_a_child_cannot_delete_a_siblings_lesson()
    scenario_a_parent_can_edit_a_childs_lesson()
    print("test_lesson_endpoints OK")
