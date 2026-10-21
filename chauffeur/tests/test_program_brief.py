"""program_brief.parse and the public context (spec §1). Run from chauffeur/: python tests/test_program_brief.py"""
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, program_brief, programs_curate, model_pools

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True, 'birthdate': '2018-03-01'}
MEMBERS = [MOM, KID]


def _model(answer):
    return patch.object(model_pools, 'call_pool_json', lambda *a, **k: answer)


def scenario_brief_naming_a_child():
    with _model({'title': 'Learn piano', 'for': 'Kate', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'plays a tune one-handed',
                 'starting_point': 'plays Twinkle with her right hand', 'based_on': 'Piano Adventures', 'notes': 'evenings'}):
        res = program_brief.parse('Piano for Kate. She plays Twinkle with her right hand. 20 minutes, three evenings. Base it on Piano Adventures.', MOM, MEMBERS, surface='library')
    b = res['brief']
    check(res['status'] == 'success' and b['title'] == 'Learn piano' and b['for_member_id'] == 'kid' and b['profile']['minutes'] == 20
          and b['profile']['sessions_per_week'] == 3 and b['profile']['age_band'] != 'any' and b['based_on'] == 'Piano Adventures', f"parsed: {b}")


def scenario_brief_naming_nobody():
    with _model({'title': 'Learn guitar', 'minutes': None, 'sessions_per_week': None}):
        lib = program_brief.parse('a beginner guitar program', MOM, MEMBERS, surface='library')
        chat = program_brief.parse('I want to learn guitar', MOM, MEMBERS, surface='chat')
    check(lib['brief']['for_member_id'] is None and lib['brief']['profile']['minutes'] == 20 and lib['brief']['profile']['sessions_per_week'] == 3, f"library: nobody, defaults: {lib}")
    check(chat['brief']['for_member_id'] == 'mom', f"chat: the speaker (P6): {chat}")


def scenario_brief_without_an_aim():
    with _model({'title': '', 'for': 'Kate'}):
        res = program_brief.parse('something for Kate on Tuesdays', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error' and 'aim' in res['message'].lower(), f"no aim, no program: {res}")


def scenario_every_free_text_is_screened():
    with _model({'title': 'Get fit', 'notes': 'lose 10 kg by June'}):
        res = program_brief.parse('x', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error', f"a body target in notes is refused: {res}")
    with _model({'title': 'Learn piano', 'starting_point': 'plays Twinkle', 'assumes': 'plays Twinkle'}):
        res = program_brief.parse('x', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error' and 'private' in res['message'].lower(), f"the starting point copied into the public assumes is refused: {res}")


def scenario_public_context_and_research_question():
    ctx = programs_curate.public_context({'age_band': 'any', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'beginner'}, notes='prefers songs over drills', based_on='Piano Adventures')
    check('prefers songs' in ctx and 'Piano Adventures' in ctx and 'Twinkle' not in ctx, f"public context carries notes and based_on, never a starting point: {ctx}")
    seen = {}
    def fake_research(question, read_pages=0):
        seen['q'] = question
        return {'status': 'ok', 'facts': [], 'sources': []}
    from services import web
    with patch.object(web, 'research', fake_research), patch.object(programs_curate, '_fallback', lambda *a, **k: {'phases': [], 'source': programs_curate._source_none('test')}):
        programs_curate.curate('learn piano', {'age_band': 'any', 'minutes': 20, 'sessions_per_week': 3, 'assumes': ''}, brief={'based_on': 'Piano Adventures', 'notes': 'songs'})
    check('Piano Adventures' in seen['q'], f"a named method is searched for: {seen['q']}")


def scenario_create_from_brief_route():
    for t in (storage.library_programs_table, storage.members_table):
        t.truncate()
    storage.add_member(dict(MOM)); storage.add_member(dict(KID))
    import main
    from fastapi.testclient import TestClient
    with _model({'title': 'Learn piano', 'for': 'Kate'}), \
         patch.object(programs_curate, 'curate', lambda *a, **k: {'phases': [{'name': 'F', 'weeks': 1, 'steps': ['a'], 'milestone': 'm', 'units': [{'title': 'U', 'sessions': 1}]}], 'source': {'origin': 'generated', 'reason': 'no_plan'}}), \
         patch('services.library_scripts.write', lambda *a, **k: {'status': 'ok', 'job': None}):
        r = TestClient(main.app).post('/api/library', json={'brief': 'Piano for Kate'}, headers={'X-Member-Token': storage.create_member_token('mom')})
    body = r.json()
    check(r.status_code == 200 and body['status'] == 'success' and body['program']['title'] == 'Learn piano' and body['for_member_id'] == 'kid', f"a brief makes a library row and names the person: {r.text}")


def scenario_brief_route_hands_back_the_private_fields():
    for t in (storage.library_programs_table, storage.members_table):
        t.truncate()
    storage.add_member(dict(MOM)); storage.add_member(dict(KID))
    import json
    import main
    from fastapi.testclient import TestClient
    secret = 'plays Twinkle with her right hand'
    with _model({'title': 'Learn piano', 'for': 'Kate', 'starting_point': secret, 'preferred_days': [1, 3],
                 'target_date': '2027-06-01', 'assumes': 'complete beginner'}), \
         patch.object(programs_curate, 'curate', lambda *a, **k: {'phases': [{'name': 'F', 'weeks': 1, 'steps': ['a'], 'milestone': 'm', 'units': [{'title': 'U', 'sessions': 1}]}], 'source': {'origin': 'generated', 'reason': 'no_plan'}}), \
         patch('services.library_scripts.write', lambda *a, **k: {'status': 'ok', 'job': None}):
        r = TestClient(main.app).post('/api/library', json={'brief': 'Piano for Kate'}, headers={'X-Member-Token': storage.create_member_token('mom')})
    body = r.json()
    check(body.get('brief') == {'starting_point': secret, 'preferred_days': [1, 3], 'target_date': '2027-06-01'},
          f"the requester gets her own words back for the setup sheet: {r.text}")
    rows = storage.get_library_programs()
    check(len(rows) == 1 and secret not in json.dumps(rows[0]) and 'starting_point' not in rows[0]
          and secret not in json.dumps(body['program']), f"the library row never carries the starting point: {rows}")


def scenario_parse_stays_on_the_free_chain():
    seen = []
    def fake(*a, **k):
        seen.append((a, k))
        return {'title': 'Learn piano'}
    with patch.object(model_pools, 'call_pool_json', fake):
        program_brief.parse('piano', MOM, MEMBERS, surface='library')
    check(len(seen) == 1 and seen[0][0][0] == 'interactive' and seen[0][1].get('paid_ok') is False,
          f"one interactive call that never reaches the paid key: {seen}")
    with _model({'error': 'all pools busy'}):
        res = program_brief.parse('piano', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error' and 'by hand' in res['message'], f"a failed read says so and offers the form: {res}")


def scenario_chat_refuses_a_name_it_cannot_find():
    with _model({'title': 'Learn piano', 'for': 'Grandpa'}):
        chat = program_brief.parse('piano for Grandpa', MOM, MEMBERS, surface='chat')
        lib = program_brief.parse('piano for Grandpa', MOM, MEMBERS, surface='library')
    check(chat['status'] == 'error' and 'Grandpa' in chat['message'], f"chat never hands a stranger's program to the speaker: {chat}")
    check(lib['status'] == 'success' and lib['brief']['for_member_id'] is None, f"the library makes it for nobody: {lib}")


def scenario_the_brief_reaches_the_curator_prompt():
    seen = {}
    def fake_fallback(title, per_week, api_key, context, answer, uncited=False):
        seen['context'] = context
        return {'phases': [], 'source': programs_curate._source_none('test')}
    from services import web
    with patch.object(web, 'research', lambda question, read_pages=0: {'status': 'ok', 'facts': [], 'sources': []}), \
         patch.object(programs_curate, '_fallback', fake_fallback):
        programs_curate.curate('learn piano', {'age_band': 'any', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'beginner'},
                               brief={'based_on': 'Piano Adventures', 'notes': 'songs over drills'})
    check('Piano Adventures' in seen['context'] and 'songs over drills' in seen['context'] and 'Assumes: beginner' in seen['context'],
          f"the one public context is what the curator reads: {seen}")


def scenario_brief_route_refusals():
    for t in (storage.library_programs_table, storage.members_table):
        t.truncate()
    storage.add_member(dict(MOM)); storage.add_member(dict(KID))
    import main
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    with patch.object(model_pools, 'call_pool_json', side_effect=AssertionError('a child spends no model call')):
        r = client.post('/api/library', json={'brief': 'Piano for me'}, headers={'X-Member-Token': storage.create_member_token('kid')})
    check(r.status_code == 403 and not storage.get_library_programs(), f"a child never makes a library row: {r.status_code} {r.text}")
    with _model({'title': 'Get fit', 'notes': 'lose 10 kg by June'}):
        r = client.post('/api/library', json={'brief': 'x'}, headers={'X-Member-Token': storage.create_member_token('mom')})
    check(r.json()['status'] == 'error' and not storage.get_library_programs(), f"a screened brief makes nothing: {r.text}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
