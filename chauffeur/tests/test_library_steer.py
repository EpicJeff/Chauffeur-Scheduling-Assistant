"""Steer: one validated candidate committed once with a server-computed change list (spec §2).
Run from chauffeur/: python tests/test_library_steer.py"""
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, library, library_steer, programs, library_scripts
from test_library_model import _fresh, _library, _project, MOM   # read that file: _library(title, created_by, minutes, sessions_per_week, b_sessions), _project(owner, title, audience)
AUNT = {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}


def _phase(lid):
    return storage.get_library_program(lid)['phases'][0]['id']


def _plan(edits, said='Changed.'):
    return lambda *a, **k: {'edits': edits, 'said': said}


def _row(lid):
    return storage.get_library_program(lid)


def scenario_steer_applies_one_candidate_with_a_change_list():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    edits = [{'op': 'update_lesson', 'lesson_id': ids[0], 'fields': {'sessions': 1}},
             {'op': 'add_lesson', 'phase_id': ph, 'after': ids[0], 'fields': {'title': 'Duet with a parent', 'sessions': 1, 'steps': ['play the tune'], 'summary': 'She plays the tune, you play the chords. 1 session.'}},
             {'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'plays Twinkle both hands'}}]
    with patch.object(library_steer, 'plan', _plan(edits)):
        res = library_steer.apply(lid, 'shorter scales, add a duet', MOM, _row(lid)['revision'])
    row = _row(lid)
    check(res['status'] == 'success' and row['revision'] == 1, f"committed once: {res.get('message')} rev={row['revision']}")
    titles = [l['title'] for l in row['lessons'] if l['phase_id'] == ph]
    check(titles[1] == 'Duet with a parent', f"placed after: {titles}")
    check(any('sessions' in c and '1' in c for c in res['changes']) and any('Duet with a parent' in c for c in res['changes'])
          and any('plays Twinkle both hands' in c for c in res['changes']), f"the change list names each move: {res['changes']}")
    duet = next(l for l in row['lessons'] if l['title'] == 'Duet with a parent')
    check(duet['origin'] == 'generated' and duet['summary'].startswith('She plays'), f"provenance and summary: {duet}")


def scenario_refusal_writes_nothing():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    before = _row(lid)
    edits = [{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'x'}}, {'op': 'remove_lesson', 'lesson_id': 'nope'}]
    with patch.object(library_steer, 'plan', _plan(edits)):
        res = library_steer.apply(lid, 'x', MOM, before['revision'])
    check(res['status'] == 'error' and _row(lid) == before, f"a bad edit aborts the whole steer: {res}")


def scenario_steer_empties_a_phase():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    count = len(_row(lid)['lessons'])
    with patch.object(library_steer, 'plan', _plan([{'op': 'remove_lesson', 'lesson_id': i} for i in ids])):
        res = library_steer.apply(lid, 'remove them all', MOM, _row(lid)['revision'])
    check(res['status'] == 'error' and len(_row(lid)['lessons']) == count and _row(lid)['phases'][0]['name'] in res['message'],
          f"a phase cannot be emptied: {res}")


def scenario_remove_then_add_in_one_steer_is_fine():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    edits = [{'op': 'remove_lesson', 'lesson_id': i} for i in ids] + [{'op': 'add_lesson', 'phase_id': ph, 'after': None, 'fields': {'title': 'Fresh start', 'steps': ['a']}}]
    with patch.object(library_steer, 'plan', _plan(edits)):
        res = library_steer.apply(lid, 'start over', MOM, _row(lid)['revision'])
    check(res['status'] == 'success' and [l['title'] for l in _row(lid)['lessons'] if l['phase_id'] == ph] == ['Fresh start'], f"validated once at the end: {res}")


def scenario_content_screens_refuse_loads():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    with patch.object(library_steer, 'plan', _plan([{'op': 'add_lesson', 'phase_id': ph, 'after': None, 'fields': {'title': 'Heavy', 'steps': ['bench 100 kg for 5']}}])):
        res = library_steer.apply(lid, 'add lifting', MOM, _row(lid)['revision'])
    check(res['status'] == 'error' and not any(l['title'] == 'Heavy' for l in _row(lid)['lessons']), f"a load prescription never lands: {res}")


def scenario_concurrent_steers():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    rev = _row(lid)['revision']
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'a'}}])):
        a = library_steer.apply(lid, 'a', MOM, rev)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'b'}}])):
        b = library_steer.apply(lid, 'b', MOM, rev)
    check(a['status'] == 'success' and b['status'] == 'error' and b['code'] == 409 and next(p for p in _row(lid)['phases'] if p['id'] == ph)['milestone'] == 'a',
          f"the second steer on a stale revision is refused: {b}")


def scenario_change_list_names_visible_runners_only():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    seen = _project(owner='kid', title='Piano for Kate', audience='household'); hidden = _project(owner='dad', title='Secret', audience='private')
    base = {'library_id': lid, 'shape': {}, 'created_by': 'mom', 'starting_point': '', 'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}
    programs.create_row({**base, 'member_id': 'kid'}, project_id=seen['id'])
    programs.create_row({**base, 'member_id': 'dad', 'created_by': 'dad'}, project_id=hidden['id'])
    first = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph][0]
    with patch.object(library_steer, 'plan', _plan([{'op': 'remove_lesson', 'lesson_id': first}])):
        res = library_steer.apply(lid, 'drop the first', AUNT, _row(lid)['revision'])
    text = ' '.join(res['changes'])
    check('Kate' in text and 'Dad' not in text and '1 more' in text, f"runners through the visible projection: {res['changes']}")


def scenario_scripts_regenerated_hand_edits_kept_stale():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    storage.edit_library_script(lid, {'lesson_id': ids[0], 'variant_label': ''}, {'scenes': [{'type': 'say', 'text': 'hi'}]})
    storage.claim_library_script(lid, {'lesson_id': ids[2], 'variant_label': ''})
    storage.commit_library_script(lid, {'lesson_id': ids[2], 'variant_label': ''}, storage.get_library_script(lid, {'lesson_id': ids[2], 'variant_label': ''})['claim'],
                                  {'scenes': [{'type': 'say', 'text': 'gen'}], 'origin': 'generated', 'minutes': 10})
    queued = []
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids[0], 'fields': {'steps': ['new a']}},
                                                     {'op': 'update_lesson', 'lesson_id': ids[2], 'fields': {'steps': ['new b']}}])), \
         patch.object(library_scripts, 'write', lambda lid_, actor, lesson_id=None, variant_label='', **kw: queued.append(lesson_id) or {'status': 'ok', 'job': None}):
        res = library_steer.apply(lid, 'rewrite steps', MOM, _row(lid)['revision'])
    hand = storage.get_library_script(lid, {'lesson_id': ids[0], 'variant_label': ''})
    gen = storage.get_library_script(lid, {'lesson_id': ids[2], 'variant_label': ''})
    check(res['status'] == 'success' and hand['edited'] and hand['scenes'] and hand.get('stale'), f"a hand edit stays, marked stale: {hand}")
    check(gen is None or not gen.get('scenes'), "a generated script is dropped for rewriting")
    check(ids[2] in queued and ids[0] not in queued, f"only the generated one is re-queued: {queued}")


def scenario_child_and_archived_refused():
    _fresh(); lid = _library('Piano')['L']
    with patch.object(library_steer, 'plan', _plan([])):
        check(library_steer.apply(lid, 'x', KID, 0)['status'] == 'error', "a child cannot steer")
        library.archive(lid, MOM)
        check(library_steer.apply(lid, 'x', MOM, _row(lid)['revision'])['status'] == 'error', "archived refused")


def scenario_http_route():
    _fresh(); lid = _library('Piano')['L']; ph = _phase(lid)
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'z'}}])):
        r = c.post(f'/api/library/{lid}/steer', json={'text': 'z', 'revision': _row(lid)['revision']}, headers={'X-Member-Token': storage.create_member_token('mom')})
    check(r.status_code == 200 and r.json()['status'] == 'success' and r.json()['changes'], f"route: {r.text}")
    r = c.post(f'/api/library/{lid}/steer', json={'text': 'z', 'revision': 0}, headers={'X-Member-Token': storage.create_member_token('mom')})
    check(r.status_code == 409, f"stale revision: {r.status_code}")


def scenario_every_model_word_is_screened():
    for fields in ({'title': 'bench 100 kg'}, {'summary': 'take 20 mg'},
                   {'body': 'take 20 mg'}, {'url': 'https://example.test/100 kg'},
                   {'variants': [{'label': 'bench 100 kg', 'steps': ['play']}]},
                   {'variants': [{'label': 'A', 'steps': ['play'], 'body': 'take 20 mg'}]},
                   {'variants': [{'label': 'A', 'steps': ['play'], 'url': '100 kg'}]},
                   {'steps': ['练习这些琴键然后继续']},
                   {'summary': 'safe ' * 70 + '100 kg'}):
        _fresh(); lid = _library()['L']; before = _row(lid)
        with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': before['lessons'][0]['id'], 'fields': fields}])):
            result = library_steer.apply(lid, 'change', MOM, 0)
        check(result['status'] == 'error' and _row(lid) == before, f'whole plan refused: {fields}: {result}')
    for edit in ({'op': 'update_profile', 'fields': {'title': 'bench 100 kg'}},
                 {'op': 'update_profile', 'fields': {'assumes': 'take 20 mg'}},
                 {'op': 'update_profile', 'fields': {'title': 'lose 20 pounds'}}):
        _fresh(); lid = _library()['L']; before = _row(lid)
        with patch.object(library_steer, 'plan', _plan([edit])):
            result = library_steer.apply(lid, 'change', MOM, 0)
        check(result['status'] == 'error' and _row(lid) == before, f'profile refused: {result}')
    with patch.object(library_steer, 'plan', _plan([], said='take 20 mg')):
        result = library_steer.apply(lid, 'change', MOM, 0)
    check(result['status'] == 'error' and _row(lid) == before, 'said is screened too')


def scenario_plan_is_one_free_proposal_and_malformed_plans_refused():
    from services import model_pools
    _fresh(); lid = _library()['L']; before = _row(lid)
    with patch.object(model_pools, 'call_pool_json', return_value={'edits': [], 'said': 'Fine.'}) as call:
        check(library_steer.plan(before, 'gentler', {}) == {'edits': [], 'said': 'Fine.'}, 'plan only proposes')
    check(call.call_count == 1 and call.call_args.kwargs['paid_ok'] is False, 'one call, paid fallback disabled')
    check(_row(lid) == before, 'plan cannot mutate storage')
    for edits in ([None], [{'op': 'unknown'}], [{'op': 'order_lessons', 'ids': []}],
                  [{'op': 'add_lesson', 'phase_id': _phase(lid), 'after': 'missing', 'fields': {'title': 'x'}}],
                  [{'op': 'update_lesson', 'lesson_id': before['lessons'][0]['id'], 'fields': {'steps': 'bad shape'}}]):
        with patch.object(library_steer, 'plan', _plan(edits)):
            result = library_steer.apply(lid, 'change', MOM, 0)
        check(result['status'] == 'error' and _row(lid) == before, f'malformed plan writes nothing: {result}')


def scenario_provenance_and_server_diff_and_runners():
    from test_library_model import _run
    _fresh(); ids = _library(); lid = ids['L']; rid = _run(ids)
    hidden = _project(owner='dad', title='Secret', audience='private')
    _run(ids, member='dad', project=hidden)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': {'sessions': 3, 'summary': 'Sit comfortably. 3 sessions.'}}], said='All lessons removed.')):
        res = library_steer.apply(lid, 'change', AUNT, 0)
    row = _row(lid)
    check(row['lessons'][0]['origin'] == 'cited' and row['lessons'][1]['origin'] == 'cited', 'metadata edits keep the citation')
    check('changed by the app' not in library.get(lid, MOM)['source_line'], 'metadata edits do not change source line')
    changes = ' '.join(res['changes'])
    check('Kate' in changes and 'Dad' not in changes and '1 more' in changes and 'All lessons removed' not in changes, f'computed resize impact: {changes}')
    check(storage.get_program(rid)['progress']['current'] == ids['A'], 'resize preserves current lesson')


def scenario_removed_lessons_and_variant_labels_delete_and_name_hand_scripts():
    _fresh(); ids = _library(); lid = ids['L']
    dropped_variant = {'lesson_id': ids['B'], 'variant_label': 'Session A'}
    kept_variant = {'lesson_id': ids['B'], 'variant_label': 'Session B'}
    removed_lesson = {'lesson_id': ids['D'], 'variant_label': ''}
    for slot in (dropped_variant, removed_lesson):
        _script(lid, slot, edited=True)
    _script(lid, kept_variant)
    kept = storage.get_library_script(lid, kept_variant)
    variants = _row(lid)['lessons'][1]['variants'][1:]
    with patch.object(library_steer, 'plan', _plan([
            {'op': 'update_lesson', 'lesson_id': ids['B'], 'fields': {'variants': variants}},
            {'op': 'remove_lesson', 'lesson_id': ids['D']}])):
        res = library_steer.apply(lid, 'change', MOM, 0)
    check(res['status'] == 'success', str(res))
    for slot in (dropped_variant, removed_lesson):
        check(storage.get_library_script(lid, slot) is None, 'removed hand script goes with its slot')
    check(storage.get_library_script(lid, kept_variant) == kept, 'unchanged remaining variant script stays')
    changes = ' '.join(res['changes'])
    check('Five-finger scale' in changes and 'Session A' in changes and 'Hands together' in changes
          and changes.count('hand-written script went with it') == 2, f'deleted hand scripts named: {changes}')


def scenario_rotation_count_change_removes_the_unnamed_hand_slot():
    _fresh(); ids = _library(); lid = ids['L']; slot = {'lesson_id': ids['A'], 'variant_label': ''}
    _script(lid, slot, edited=True)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'],
            'fields': {'variants': [{'label': 'Duet', 'steps': ['Play']} ]}}])):
        res = library_steer.apply(lid, 'add rotation', MOM, 0)
    check(res['status'] == 'success' and storage.get_library_script(lid, slot) is None, 'the old unnamed slot is removed')
    check(any('Posture and middle C' in line and 'hand-written script went with it' in line for line in res['changes']), 'removed unnamed hand script is named')


def scenario_stale_projection_and_fresh_hand_edit():
    _fresh(); ids = _library(); lid = ids['L']; slot = {'lesson_id': ids['A'], 'variant_label': ''}
    _script(lid, slot, edited=True)
    storage.mark_library_script_stale(lid, slot, True)
    check(library.get(lid, MOM)['scripts'][ids['A']]['']['stale'], 'view exposes stale')
    storage.edit_library_script(lid, slot, {'scenes': [{'type': 'say', 'text': 'current'}]})
    check(storage.get_library_script(lid, slot)['stale'] is False, 'fresh hand edit clears stale')


def scenario_revision_rechecked_after_model_and_http_validation():
    _fresh(); lid = _library()['L']
    def concurrent(*args):
        library.update(lid, {'title': 'New title'}, MOM)
        return {'edits': [], 'said': 'Fine.'}
    with patch.object(library_steer, 'plan', concurrent):
        check(library_steer.apply(lid, 'change', MOM, 0)['code'] == 409, 'commit rechecks revision after model')
    from fastapi.testclient import TestClient
    import main
    c = TestClient(main.app); headers = {'X-Member-Token': storage.create_member_token('mom')}
    for body in ({'text': 'x'}, {'text': 'x', 'revision': None}, {'text': 'x', 'revision': []}, {'text': 'x', 'revision': True}):
        r = c.post(f'/api/library/{lid}/steer', json=body, headers=headers)
        check(r.status_code == 400, f'invalid revision: {r.status_code} {r.text}')


def scenario_archive_idempotent_and_shared_summary():
    from services import migrations
    _fresh(); lid = _library()['L']
    library.archive(lid, MOM); before = _row(lid)
    check(library.archive(lid, MOM)['status'] == 'success' and _row(lid) == before, 'repeated archive succeeds without write')
    _fresh(); lid = _library()['L']
    for steps, expected in ((['Play.'], 'Play. 2 sessions.'), ([123], '123. 2 sessions.')):
        row = library.from_curated('Piano', {}, {'phases': [{'name': 'Start', 'units': [{'steps': steps, 'sessions': 2}]}]}, 'mom')
        check(row['lessons'][0]['summary'] == expected, 'curation summary')
        result = library.add_lesson(lid, {'phase_id': _phase(lid), 'title': 'New', 'steps': steps, 'sessions': 2}, MOM)
        check(result['program']['lessons'][-1]['summary'] == expected, 'hand summary')
        lessons = _row(lid)['lessons']; lessons[0].update(steps=steps, sessions=2); lessons[0].pop('summary', None)
        storage.update_library_program(lid, {'lessons': lessons})
        storage.set_app_state('library_revision_summary_v2499', False)
        migrations.migrate_library_revision_summary_v2499()
        check(_row(lid)['lessons'][0]['summary'] == expected, 'migration summary')


def scenario_real_job_requeues_all_slots_and_late_hand_edit_wins():
    import threading
    real_write = _REAL_WRITE
    _fresh(); ids = _library(); lid = ids['L']
    entered = threading.Event(); release = threading.Event(); calls = []
    def generate(row, lesson, label, settings, **kw):
        calls.append((lesson['id'], label))
        entered.set()
        check(release.wait(5), 'job released')
        slot = {'lesson_id': lesson['id'], 'variant_label': label}
        token = storage.claim_library_script(lid, slot, revision=row['revision'])
        if token:
            storage.commit_library_script(lid, slot, token, {'scenes': [{'type': 'say', 'text': 'new'}]})
        return storage.get_library_script(lid, slot)
    edits = [{'op': 'update_lesson', 'lesson_id': ids[k], 'fields': {'steps': ['New steps']}} for k in ('A', 'B', 'D')]
    with patch.object(library_scripts, 'write', real_write), patch.object(library_scripts, 'generate_script', generate), patch.object(library_steer, 'plan', _plan(edits)):
        result = library_steer.apply(lid, 'rewrite', MOM, 0)
        check(entered.wait(2), 'actual background job started')
        hand_slot = {'lesson_id': ids['D'], 'variant_label': ''}
        storage.edit_library_script(lid, hand_slot, {'scenes': [{'type': 'say', 'text': 'Late hand edit'}]})
        release.set()
        import time
        end = time.monotonic() + 5
        while library_scripts.job_state(lid) and time.monotonic() < end:
            time.sleep(.01)
        check(library_scripts.job_state(lid) is None, 'all queued slots finish')
    check(result['status'] == 'success', str(result))
    check(set(calls) == {(ids['A'], ''), (ids['B'], 'Session A'), (ids['B'], 'Session B')}, f'every generated slot queued, hand skipped: {calls}')
    check(storage.get_library_script(lid, hand_slot)['scenes'][0]['text'] == 'Late hand edit', 'late hand edit never overwritten')


def scenario_one_validation_commit_and_reconciliation_per_run():
    import copy
    from test_library_model import _run
    _fresh(); ids = _library(); lid = ids['L']
    runs = [_run(ids, member=member) for member in ('kid', 'sib')]
    before = _row(lid); snapshot = copy.deepcopy(before)
    edits = [{'op': 'update_profile', 'fields': {'sessions_per_week': 3, 'assumes': 'knows middle C'}},
             {'op': 'update_phase', 'phase_id': ids['P1'], 'fields': {'name': 'Keyboard'}},
             {'op': 'order_lessons', 'ids': [ids[k] for k in 'ADBCE']},
             {'op': 'update_lesson', 'lesson_id': ids['D'], 'fields': {'title': 'Together'}}]
    cand, touched = library_steer._apply(before, edits)
    check(before == snapshot and cand != before and not touched, 'pure changes build one copy')
    with patch.object(library_steer, 'plan', _plan(edits)), patch.object(library, '_commit', wraps=library._commit) as commit, \
            patch.object(library, 'valid_curriculum', wraps=library.valid_curriculum) as valid, \
            patch.object(programs, 'reconcile_progress', wraps=programs.reconcile_progress) as reconcile:
        result = library_steer.apply(lid, 'change', MOM, 0)
    check(result['status'] == 'success' and commit.call_count == 1 and valid.call_count == 1, 'one commit and validation')
    check(sorted(c.args[0]['id'] for c in reconcile.call_args_list) == sorted(runs), 'each run reconciled once')
    changes = ' '.join(result['changes'])
    check(all(word in changes for word in ('Made for ' + library.made_for_line(cand['made_for']), '3 a week', 'knows middle C', 'Keyboard', 'Together', 'reordered')), f'each change reported: {changes}')


def _script(lid, slot, edited=False):
    data = {'scenes': [{'type': 'say', 'text': 'Keep ' + slot['variant_label']}], 'minutes': 9}
    if edited:
        storage.edit_library_script(lid, slot, data)
    else:
        token = storage.claim_library_script(lid, slot)
        check(token, 'claim created')
        check(storage.commit_library_script(lid, slot, token, data), 'generated script stored')


def scenario_phase_title_profile_and_lesson_metadata_leave_scripts_untouched():
    for edit_for in (
            lambda ids: {'op': 'update_phase', 'phase_id': ids['P1'], 'fields': {'milestone': 'Play a duet'}},
            lambda ids: {'op': 'update_phase', 'phase_id': ids['P1'], 'fields': {'name': 'Keys', 'progression': 'Play smoothly'}},
            # minutes stay 30: a lesson-length change DOES touch scripts now (next scenario).
            lambda ids: {'op': 'update_profile', 'fields': {'title': 'Keyboard', 'minutes': 30, 'sessions_per_week': 3}},
            lambda ids: {'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': {'title': 'Posture', 'sessions': 3, 'summary': 'Sit. 3 sessions.'}}):
        _fresh(); ids = _library(); lid = ids['L']
        _script(lid, {'lesson_id': ids['A'], 'variant_label': ''})
        _script(lid, {'lesson_id': ids['D'], 'variant_label': ''}, edited=True)
        before = storage.get_library_scripts(lid)
        with patch.object(library_steer, 'plan', _plan([edit_for(ids)])), patch.object(library_scripts, 'write') as write:
            result = library_steer.apply(lid, 'change', MOM, 0)
        check(result['status'] == 'success' and storage.get_library_scripts(lid) == before and not write.called,
              f'no scripts touched for metadata/phase/profile: {result}')


def scenario_a_steer_that_changes_the_lesson_length_outdates_scripts_and_writes_nothing():
    """The one profile field scripts are written against (2026-10-23, tests/test_set_aside.py): a
    generated script records the 30 it was written for and Write lessons picks it up; a hand edit
    is flagged stale and never rewritten; nothing is scheduled by the steer itself."""
    _fresh(); ids = _library(); lid = ids['L']
    gen_slot = {'lesson_id': ids['A'], 'variant_label': ''}
    hand_slot = {'lesson_id': ids['D'], 'variant_label': ''}
    _script(lid, gen_slot)
    _script(lid, hand_slot, edited=True)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_profile', 'fields': {'minutes': 20}}])), \
            patch.object(library_scripts, 'write') as write:
        result = library_steer.apply(lid, 'shorter sessions', MOM, 0)
    check(result['status'] == 'success' and storage.get_library_program(lid)['made_for']['minutes'] == 20, f'the steer landed: {result}')
    gen = storage.get_library_script(lid, gen_slot)
    hand = storage.get_library_script(lid, hand_slot)
    check(gen['scenes'] and not gen.get('stale') and int(gen.get('budget') or 0) == 30,
          f'the generated script stays playable and records the 30 it was written for: {gen}')
    check(hand['scenes'] and hand.get('edited') and hand.get('stale') is True and not hand.get('budget'),
          f'the hand edit stays, flagged stale: {hand}')
    check(library_scripts.needs_script(lid, gen_slot) and not library_scripts.needs_script(lid, hand_slot),
          'Write lessons rewrites the generated one and leaves the hand edit alone')
    check(not write.called, 'the steer schedules nothing; a person taps Write lessons')


def scenario_content_provenance_and_existing_fact_citations():
    from services import programs_curate
    for citation, expected in (({}, 'generated'), ({'cite': 1}, 'cited'), ({'cite': '[1]'}, 'cited'),
                               ({'url': 'https://example.test/read/'}, 'cited'),
                               ({'cite': 2}, 'generated'), ({'url': 'https://invented.test'}, 'generated')):
        _fresh(); ids = _library(); lid = ids['L']
        storage.update_library_program(lid, {'source': {'origin': 'cited', 'plan_name': 'Piano',
                                         'facts': [{'url': 'https://example.test/read', 'claim': 'Play slowly'}]}})
        with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'],
                'fields': {'steps': ['Play softly'], **citation}}])):
            result = library_steer.apply(lid, 'change', MOM, 0)
        lesson = _row(lid)['lessons'][0]
        check(result['status'] == 'success' and lesson['origin'] == expected, f'citation resolved against facts: {citation}: {result}')
        if expected == 'cited':
            check(lesson['url'] == 'https://example.test/read' and lesson['source_index'] == 1, 'canonical URL and index retained')
        else:
            check('1 lesson changed by the app' in result['program']['source_line'], 'app changes reported')
    for field in ('steps', 'body', 'url', 'variants'):
        _fresh(); ids = _library(); lid = ids['L']
        values = {'steps': ['Play gently'], 'body': 'Try a duet.', 'url': 'https://new.test',
                  'variants': [{'label': 'Duet', 'steps': ['Play softly']}]}
        with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': {field: values[field]}}])):
            result = library_steer.apply(lid, 'change', MOM, 0)
        check(result['status'] == 'success' and _row(lid)['lessons'][0]['origin'] == 'generated', f'{field} changes material')


def scenario_variant_relabel_rekeys_by_position_without_rewriting():
    import copy
    _fresh(); ids = _library(); lid = ids['L']
    a = {'lesson_id': ids['B'], 'variant_label': 'Session A'}
    b = {'lesson_id': ids['B'], 'variant_label': 'Session B'}
    _script(lid, a, edited=True); _script(lid, b)
    before = [storage.get_library_script(lid, slot) for slot in (a, b)]
    variants = copy.deepcopy(_row(lid)['lessons'][1]['variants'])
    # Swap labels: the scripts must follow position, with no slot collision.
    variants[0]['label'], variants[1]['label'] = variants[1]['label'], variants[0]['label']
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['B'], 'fields': {'variants': variants}}])), \
            patch.object(library_scripts, 'write') as write:
        res = library_steer.apply(lid, 'rename sessions', MOM, 0)
    check(res['status'] == 'success' and not write.called, 'relabel queues no rewriting')
    for original, slot in zip(before, (b, a)):
        check(storage.get_library_script(lid, slot) == {**original, 'variant_label': slot['variant_label']}, 'hand and generated scripts rekeyed intact')
    check(library.get(lid, MOM)['scripts'][ids['B']]['Session B']['edited'], 'rekeyed hand script remains reachable')


def scenario_model_caps_and_numeric_refusals():
    from services import programs_curate as curate
    _fresh(); ids = _library(); lid = ids['L']
    fields = {'title': 'a' * 250, 'sessions': 50, 'body': 'b' * 2500,
              'variants': [{'label': 'c' * 250, 'steps': ['Play'], 'body': 'd' * 2500}]}
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': fields}])):
        res = library_steer.apply(lid, 'change', MOM, 0)
    lesson = _row(lid)['lessons'][0]
    check(res['status'] == 'success' and lesson['sessions'] == curate.MAX_UNIT_SESSIONS, 'model pacing capped at four')
    check(len(lesson['title']) == curate.UNIT_TITLE_CHARS and len(lesson['body']) == curate.UNIT_BODY_CHARS
          and len(lesson['variants'][0]['label']) == curate.LABEL_CHARS
          and len(lesson['variants'][0]['body']) == curate.UNIT_BODY_CHARS, 'curator lengths reused')
    for bad_fields in ({'steps': ['Play'] * (curate.MAX_STEPS + 1)},
                       {'variants': [{'label': 'A', 'steps': ['Play'] * (curate.MAX_STEPS + 1)}]}):
        before = _row(lid)
        with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': bad_fields}])):
            res = library_steer.apply(lid, 'change', MOM, before['revision'])
        check(res['status'] == 'error' and '8 steps' in res['message'] and _row(lid) == before, 'step-limit refusal is explicit and atomic')
    from fastapi.testclient import TestClient
    import main
    client = TestClient(main.app)
    for edit in ({'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': {'sessions': float('inf')}},
                 {'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': {'sessions': 'oops'}},
                 {'op': 'update_profile', 'fields': {'minutes': float('inf')}}):
        before = _row(lid)
        with patch.object(library_steer, 'plan', _plan([edit])):
            response = client.post(f'/api/library/{lid}/steer', json={'text': 'change', 'revision': before['revision']},
                                   headers={'X-Member-Token': storage.create_member_token('mom')})
        check(response.status_code == 200 and response.json()['status'] == 'error' and _row(lid) == before, 'bad numeric model value refuses without 500')


def scenario_hand_and_steer_use_the_same_candidate_mutations():
    cases = [
        ('_change_profile', lambda lid, ids: library.update(lid, {'title': 'Keyboard'}, MOM),
         lambda ids: {'op': 'update_profile', 'fields': {'title': 'Piano again'}}),
        ('_change_update_phase', lambda lid, ids: library.update_phase(lid, ids['P1'], {'name': 'Keys'}, MOM),
         lambda ids: {'op': 'update_phase', 'phase_id': ids['P1'], 'fields': {'name': 'First keys'}}),
        ('_change_add_lesson', lambda lid, ids: library.add_lesson(lid, {'phase_id': ids['P1'], 'title': 'Duet'}, MOM, after=ids['A']),
         lambda ids: {'op': 'add_lesson', 'phase_id': ids['P1'], 'after': ids['A'], 'fields': {'title': 'Another duet'}}),
        ('_change_update_lesson', lambda lid, ids: library.update_lesson(lid, ids['A'], {'title': 'Posture'}, MOM),
         lambda ids: {'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': {'title': 'Sit tall'}}),
        ('_change_remove_lesson', lambda lid, ids: library.remove_lesson(lid, ids['D'], MOM),
         lambda ids: {'op': 'remove_lesson', 'lesson_id': ids['A']}),
        ('_change_order', lambda lid, ids: library.order_lessons(lid, [ids[k] for k in 'ADBCE'], MOM),
         lambda ids: {'op': 'order_lessons', 'ids': [ids[k] for k in 'BDAEC']})]
    for helper_name, hand, edit_for in cases:
        _fresh(); ids = _library(); lid = ids['L']
        with patch.object(library, helper_name, wraps=getattr(library, helper_name)) as helper:
            result = hand(lid, ids)
            check(result['status'] == 'success' and helper.called, f'hand uses {helper_name}')
            helper.reset_mock()
            candidate, _ = library_steer._apply(_row(lid), [edit_for(ids)])
            check(helper.called and candidate != _row(lid), f'steer uses {helper_name} to change the candidate')


def scenario_steer_drops_invented_lesson_and_variant_urls():
    for cited in (False, True):
        _fresh(); ids = _library(); lid = ids['L']
        storage.update_library_program(lid, {'source': {'origin': 'cited', 'facts': [{'url': 'https://example.test/read'}]}})
        fields = {'steps': ['Play gently'], 'url': 'https://invented.test/lesson',
                  'variants': [{'label': 'Session A', 'steps': ['Play'], 'url': 'https://invented.test/a'}]}
        if cited:
            fields['source_index'] = 1
            fields['variants'][0]['url'] = 'https://example.test/read/'
        with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids['A'], 'fields': fields}])):
            result = library_steer.apply(lid, 'change', MOM, 0)
        lesson = _row(lid)['lessons'][0]
        check(result['status'] == 'success', f'steer committed: {result}')
        check(lesson['origin'] == ('cited' if cited else 'generated') and lesson.get('url') == ('https://example.test/read' if cited else ''), 'lesson uses only canonical cited URLs')
        check(lesson['variants'][0].get('url', '') == ('https://example.test/read' if cited else ''), 'variants use only cited URLs')


_REAL_WRITE = library_scripts.write
SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            with patch.object(library_scripts, 'write', return_value={'status': 'ok', 'job': None}):
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
