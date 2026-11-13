"""Argyle in the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 7.4; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 11 and its
review amendments): the house_design tool edits through the same operations
as the hand path, refuses anyone but a parent, and a real agent turn through
POST /api/house/editor/say changes the house, is metered per provider request
as 'conversation', and stops cleanly at a spend checkpoint.

The provider HTTP layer (llm_budget.urlopen) is stubbed with Gemini bodies
whose text is the router's JSON contract; everything else is real.

Run from chauffeur/:  python tests/test_house_design_tool.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_house_design_tool_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import llm, storage  # noqa: E402
from services import agent_tools_v2  # noqa: E402
from services import twin_cost as tc  # noqa: E402
from services import twin_store as ts  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_edit_house.plan.json')
PRICED = next(iter(tc.PRICES))
PARENT_M = {'id': 'p1', 'name': 'Pat', 'role': 'parent'}
CHILD_M = {'id': 'k1', 'name': 'Kit', 'role': 'child'}


def check(cond, msg):
    # Local on purpose: tests/harness.py stubs storage.get_settings.
    if not cond:
        raise AssertionError(msg)


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Model:
    """Stands in for llm_budget.urlopen; answers each request with the next reply."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request, timeout=60):
        self.requests.append(request)
        text = json.dumps(self.replies.pop(0) if self.replies else {'message': 'Done.', 'tool_calls': []})
        body = {'candidates': [{'content': {'parts': [{'text': text}]}, 'finishReason': 'STOP'}],
                'usageMetadata': {'promptTokenCount': 900, 'candidatesTokenCount': 80}}
        return _Response(json.dumps(body).encode('utf-8'))


_real_settings = storage.get_settings


def _enforced():
    return patch.object(storage, 'get_settings', side_effect=lambda: {**_real_settings(), 'auth_enforce': True})


def _seed():
    storage.patch_settings({'house_twin': None, 'house_twin_cost': None, 'llm_provider': 'gemini',
                            'llm_gemini_api_key': 'k', 'llm_gemini_paid_api_key': 'paid-k'})
    shutil.rmtree(ts.DATA_DIR, ignore_errors=True)
    with open(FIXTURE, encoding='utf-8') as f:
        ts.push_round(json.load(f), 'build')


def _section(plan, sid):
    return next(s for s in plan['buildings'][0]['roof']['sections'] if s['id'] == sid)


TOKENS = {}


def _people():
    if not TOKENS:
        storage.add_member(dict(PARENT_M))
        storage.add_member(dict(CHILD_M))
        TOKENS['parent'] = {'X-Member-Token': storage.create_member_token('p1')}
        TOKENS['child'] = {'X-Member-Token': storage.create_member_token('k1')}
    return TOKENS


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app)


def scenario_tool_is_registered_and_never_runs_from_a_mission():
    from services import missions
    check('house_design' in agent_tools_v2.TOOL_SCHEMAS and 'house_design' in agent_tools_v2.TOOL_HANDLERS, 'registered')
    check('house_design' in agent_tools_v2.REGISTRY_EXCEPTIONS, 'mission exception declared')
    check('house_design' not in missions.proposable_tools(), 'never offered to a mission, like house and music')


def scenario_tool_documents_connected_operation_arguments():
    schema = agent_tools_v2.TOOL_SCHEMAS['house_design']
    description = schema['properties']['edit']['description']
    arguments = {
        'move_joint': ('joint', 'to'), 'move_wall': ('wall', 'by'), 'move_room': ('room', 'by'),
        'split_wall': ('wall', 'at'), 'draw_room': ('level', 'polygon'),
        'split_room': ('room', 'from', 'to'), 'delete': ('id',),
        'add_wall': ('level', 'from', 'to'), 'add_opening': ('wall', 'kind', 'at', 'width', 'sill', 'head'),
        'move_hosted': ('id', 'host', 'at', 'z', 'offset'),
        'resize_opening': ('id', 'width', 'sill', 'head', 'at'),
        'add_anchor': ('kind', 'host'), 'add_item': ('asset', 'host', 'rotation', 'scale'),
        'draw_roof': ('area', 'plate', 'pitch', 'overhang'), 'roof_over': ('rooms', 'null'),
        'set_roof_edge': ('roof', 'edge', 'setting', 'pitch', 'clip'),
        'move_roof_edge': ('roof', 'edge', 'by', 'detach'),
        'add_dormer': ('roof', 'edge', 'at', 'width', 'pitch'), 'move_dormer': ('id', 'at', 'width'),
        'add_level': ('name', 'elevation', 'ceiling'), 'move_building': ('to',),
        'rotate_building': ('rotation', 'about'), 'set': ('id', 'field', 'value'),
        'set_material': ('target', 'material'), 'accept_proposal': ('id',), 'dismiss_proposal': ('id',),
        'move_site_item': ('list', 'index', 'at'), 'delete_site_item': ('list', 'index'),
        'add_site_item': ('list', 'asset', 'at'),
    }
    for op, keys in arguments.items():
        marker = op + ' ('
        check(marker in description, f'{op} needs its argument shape')
        clause = description.split(marker, 1)[1].split(';', 1)[0]
        check(all(key in clause for key in keys), f'{op} needs {keys}: {clause}')
    for shape in ('{wall, side, at, z}', '{floor: room, u, v}', '{ceiling: room, u, v}',
                  '{wall, side}', '{room, surface', '{roof}', '{level, role}', '{building, role}',
                  '{id, color}', 'left|right', 'floor|ceiling|walls', 'rectilinear',
                  '0-based', '<piece>:proposal', 'planting|furniture', 'lot feet'):
        check(shape in description, f'missing shape or coordinate convention: {shape}')
    # Same budget as test_twin_model_devices: 5,057 characters after terrain pads and porch foundations.
    check(len(json.dumps(schema)) <= 6000, 'keep the tool schema compact')  # stairs, porch slots and yard rooms added (5,689 at v2.499.836)


def scenario_tool_edits_through_the_same_operations():
    _seed()
    _people()
    out = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {
        'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}}, actor=storage.get_member('p1'))
    check(out.get('status') == 'ok', out)
    s = _section(ts.current(), 'roof-1')
    check(s['pitch'] == 8 and s['pitch_source'] == 'person', s)
    status = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=storage.get_member('p1'))
    check(status.get('status') == 'ok' and (status.get('summary') or status.get('message')), status)
    check(len(json.dumps(status)) < 2000, 'status is a summary, never the plan')
    bad = agent_tools_v2.execute_tool('house_design', {'action': 'edit', 'edit': {
        'op': 'set', 'piece': 'wall-1', 'field': 'from', 'value': [0, 0]}}, actor=storage.get_member('p1'))
    check(bad.get('status') in ('error', 'refused') and bad.get('message'), bad)


def scenario_tool_refuses_non_parents():
    _seed()
    _people()
    for actor in (storage.get_member('k1'), None):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=actor)
        check('Only a parent can change the house.' in (out.get('message') or ''), out)


def scenario_a_real_turn_edits_the_house_and_is_metered():
    _seed()
    tokens = _people()
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {
            'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}}}]},
        {'message': 'Set the roof pitch to 8:12.', 'tool_calls': []},
    ])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model):
        r = c.post('/api/house/editor/say', headers=tokens['parent'],
                   json={'message': 'the roof is 8/12', 'selection': None, 'history': []})
    check(r.status_code == 200, r.text)
    body = r.json()
    check(body['reply'] == 'Set the roof pitch to 8:12.' and body['changed'] is True and body['summary'], body)
    check(_section(ts.current(), 'roof-1')['pitch'] == 8, 'the house changed through the real router')
    conv = [e for e in tc.entries() if e['stage'] == 'conversation']
    check(len(conv) == len(model.requests) >= 2, (len(conv), len(model.requests)))
    check(abs(body['cost'] - sum(e['usd'] for e in conv)) < 1e-9, (body['cost'], conv))


def scenario_a_child_cannot_talk_the_house_into_changing():
    _seed()
    tokens = _people()
    c = _client()
    with _enforced():
        r = c.post('/api/house/editor/say', headers=tokens['child'], json={'message': 'hi'})
    check(r.status_code in (401, 403), r.status_code)


def scenario_say_stops_at_a_due_checkpoint_before_any_request():
    _seed()
    tokens = _people()
    per_million = tc.price(PRICED, 1_000_000, 0)[0]
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': int(10.5 / per_million * 1_000_000),
                              'output_tokens': 0, 'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    model = Model([{'message': 'hi', 'tool_calls': []}])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model):
        r = c.post('/api/house/editor/say', headers=tokens['parent'], json={'message': 'hi'})
    check(r.status_code == 409 and r.json()['detail']['checkpoint'] == 10.0, r.text)
    check(model.requests == [], 'no request made')


def scenario_a_checkpoint_inside_the_turn_stops_cleanly():
    # The first request crosses $10; the router's next request must stop with
    # the checkpoint, not be treated as a model failure.
    _seed()
    tokens = _people()
    per_dollar = tc.price(PRICED, 1_000_000, 0)[0]
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': int(9.99 / per_dollar * 1_000_000),
                              'output_tokens': 0, 'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    check(tc.blocking_checkpoint() is None, 'just under the checkpoint')
    failures = []
    from services import model_pools
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {'action': 'status'}}]},
        {'message': 'never reached', 'tool_calls': []},
    ])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model), \
            patch.object(model_pools, 'note_failure', lambda *a, **k: failures.append(a)), \
            patch.object(tc, 'price', lambda m, i, o: (0.05, True)):
        r = c.post('/api/house/editor/say', headers=tokens['parent'], json={'message': 'status?'})
    check(r.status_code == 409 and r.json()['detail']['checkpoint'] == 10.0, r.text)
    check(len(model.requests) == 1 and failures == [], (len(model.requests), failures))


def scenario_describe_is_short_even_for_a_whole_building():
    _seed()
    _people()
    parent = storage.get_member('p1')
    wall = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'wall-1'}, actor=parent)
    check(wall.get('status') == 'ok' and "'" in json.dumps(wall), wall)          # feet-inches in plain words
    whole = agent_tools_v2.execute_tool('house_design', {'action': 'describe', 'piece': 'house'}, actor=parent)
    check(whole.get('status') == 'ok' and len(json.dumps(whole)) < 1500, len(json.dumps(whole)))
    check('wall-5' not in json.dumps(whole), 'a building is described by counts, not every piece')


def scenario_accept_and_reread_drive_the_build():
    import test_twin_build as engine_tests
    from services import twin_build as tb
    engine_tests._fresh()
    _people()
    _, _, photo = engine_tests._sources()
    reader = engine_tests.Reader()
    b = tb.start(engine_tests._inputs(photo), reader=reader, inline=True)
    parent = storage.get_member('p1')
    with patch.object(__import__('services.twin_reads', fromlist=['read']), 'read', reader):
        out = agent_tools_v2.execute_tool('house_design', {'action': 'accept'}, actor=parent)
        check(out.get('status') == 'ok', out)
        deadline = __import__('time').time() + 20
        while tb.status(b)['state'] == 'running' and __import__('time').time() < deadline:
            __import__('time').sleep(0.1)
        check(tb.status(b)['pause'] and tb.status(b)['pause']['step'] == 'registration:L2', tb.status(b)['pause'])
        before = len(reader.calls)
        out = agent_tools_v2.execute_tool('house_design', {'action': 'reread', 'step': 'rooms:L1'}, actor=parent)
        check(out.get('status') == 'ok', out)
        deadline = __import__('time').time() + 20
        while tb.status(b)['state'] == 'running' and __import__('time').time() < deadline:
            __import__('time').sleep(0.1)
        check([c['step'] for c in reader.calls[before:]].count('rooms:L1') == 1, reader.calls[before:])


def scenario_house_design_is_refused_off_the_editor():
    # The tool exists only inside the house editor: a PWA chat turn whose model
    # emits a house_design edit is refused and the house is unchanged.
    _seed()
    _people()
    from services import agent_router
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {
            'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 12}}}]},
        {'message': 'ok', 'tool_calls': []},
    ])
    with patch.object(llm.llm_budget, 'urlopen', model):
        agent_router.process_agent_request('make the roof steeper', source='pwa',
                                           acting_member=storage.get_member('p1'))
    check(_section(ts.current(), 'roof-1')['pitch'] == 6, 'the house is unchanged off the editor')


def scenario_a_checkpoint_mid_turn_still_reports_what_changed():
    _seed()
    tokens = _people()
    per_million = tc.price(PRICED, 1_000_000, 0)[0]
    tc.record('step:walls', [{'model': PRICED, 'input_tokens': int(9.99 / per_million * 1_000_000),
                              'output_tokens': 0, 'images': 0, 'prompt_chars': 0, 'max_output_tokens': 0}])
    model = Model([
        {'message': '', 'tool_calls': [{'name': 'house_design', 'arguments': {
            'action': 'edit', 'edit': {'op': 'set', 'piece': 'roof-1', 'field': 'pitch', 'value': 8}}}]},
        {'message': 'never reached', 'tool_calls': []},
    ])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model), \
            patch.object(tc, 'price', lambda m, i, o: (0.05, True)):
        r = c.post('/api/house/editor/say', headers=tokens['parent'], json={'message': 'roof 8/12'})
    check(r.status_code == 409, r.text)
    detail = r.json()['detail']
    check(detail['checkpoint'] == 10.0 and detail.get('changed') is True and detail.get('summary'), detail)


def scenario_long_messages_are_capped():
    _seed()
    tokens = _people()
    model = Model([{'message': 'ok', 'tool_calls': []}])
    c = _client()
    with _enforced(), patch.object(llm.llm_budget, 'urlopen', model):
        r = c.post('/api/house/editor/say', headers=tokens['parent'],
                   json={'message': 'x' * 20000, 'history': [{'role': 'user', 'content': 'y' * 20000}] * 30})
    check(r.status_code in (200, 400), r.status_code)
    if r.status_code == 200:
        import re
        sent = model.requests[0].data.decode('utf-8')
        longest = lambda ch: max((len(m) for m in re.findall(ch + '+', sent)), default=0)
        check(longest('x') <= 4000 and longest('y') <= 4000, ('message and history capped', longest('x'), longest('y')))


def _parent():
    _people()
    return storage.get_member('p1')


def _place_pdf():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (612, 396), (255, 255, 255)).save(buf, format='PDF', resolution=72)
    return buf.getvalue()


def scenario_add_detached_garage():
    _seed()
    out = agent_tools_v2.execute_tool('house_design', {
        'action': 'add_building', 'name': 'Detached garage', 'kind': 'Garage'}, actor=_parent())
    check(out == {'status': 'ok', 'changed': True, 'summary': 'Added Detached garage.'}, out)
    garage = next((b for b in ts.place()['buildings'] if b['id'] == 'detached-garage'), None)
    check(garage and garage['kind'] == 'garage' and garage['name'] == 'Detached garage', ts.place())
    again = agent_tools_v2.execute_tool('house_design', {
        'action': 'add_building', 'name': 'detached garage', 'kind': 'garage'}, actor=_parent())
    check(again['status'] == 'error' and 'already a building called' in again['message'], again)


def scenario_shed_size_and_roof():
    _seed()
    parent = _parent()
    agent_tools_v2.execute_tool('house_design', {'action': 'add_building', 'name': 'Shed', 'kind': 'shed'}, actor=parent)
    out = agent_tools_v2.execute_tool('house_design', {
        'action': 'set_building', 'building': 'Shed', 'size': [10, 12], 'shell': {'roof': 'gable'}}, actor=parent)
    check(out == {'status': 'ok', 'changed': True, 'summary': 'Updated Shed.'}, out)
    # No other footprints exist, so the rectangle starts at x 10, y 10.
    shed = next(b for b in ts.place()['buildings'] if b['id'] == 'shed')
    check(shed['footprint'] == [[10, 10], [20, 10], [20, 22], [10, 22]], shed['footprint'])
    check(shed['footprint_from'] == 'typed' and shed['shell']['roof'] == 'gable'
          and shed['shell_from'] == 'person', shed)
    # A second sized building lands to the right of the first, 10 ft apart.
    agent_tools_v2.execute_tool('house_design', {'action': 'add_building', 'name': 'Barn', 'kind': 'barn'}, actor=parent)
    agent_tools_v2.execute_tool('house_design', {
        'action': 'set_building', 'building': 'barn', 'size': [20, 30]}, actor=parent)
    barn = next(b for b in ts.place()['buildings'] if b['id'] == 'barn')
    check(barn['footprint'] == [[30, 10], [50, 10], [50, 40], [30, 40]], barn['footprint'])


def scenario_remove_refusal_words():
    _seed()
    parent = _parent()
    agent_tools_v2.execute_tool('house_design', {'action': 'add_building', 'name': 'Shed', 'kind': 'shed'}, actor=parent)
    ts.save_source('drawing', 's.pdf', _place_pdf(), part='shed')
    out = agent_tools_v2.execute_tool('house_design', {'action': 'remove_building', 'building': 'shed'}, actor=parent)
    check(out == {'status': 'error', 'message': "Move or remove this building's pages first."}, out)
    check(any(b['id'] == 'shed' for b in ts.place()['buildings']), 'still there')
    agent_tools_v2.execute_tool('house_design', {'action': 'add_building', 'name': 'Barn', 'kind': 'barn'}, actor=parent)
    out = agent_tools_v2.execute_tool('house_design', {'action': 'remove_building', 'building': 'BARN'}, actor=parent)
    check(out == {'status': 'ok', 'changed': True, 'summary': 'Removed Barn.'}, out)
    check(not any(b['id'] == 'barn' for b in ts.place()['buildings']), ts.place())


def scenario_status_mentions_place():
    _seed()
    parent = _parent()
    agent_tools_v2.execute_tool('house_design', {'action': 'add_building', 'name': 'Shed', 'kind': 'shed'}, actor=parent)
    agent_tools_v2.execute_tool('house_design', {'action': 'set_building', 'building': 'shed', 'size': [10, 12]}, actor=parent)
    ts.save_source('drawing', 'h.pdf', _place_pdf(), part='house')
    out = agent_tools_v2.execute_tool('house_design', {'action': 'status'}, actor=parent)
    summary = out['summary']
    check(summary.startswith('Your place: 2 buildings ('), summary)
    check('Shed (Shed, no drawings, footprint)' in summary, summary)
    check('(Main house, drawings, no footprint)' in summary, summary)
    check('). Lot: plot plan not read, placement not confirmed.' in summary, summary)
    check(summary.index('Lot:') < summary.index('Build:'), 'the place comes first, then the existing text')
    check(len(json.dumps(out)) < 2000, 'still a summary')


def scenario_kid_refused():
    _seed()
    _people()
    calls = ({'action': 'add_building', 'name': 'Shed', 'kind': 'shed'},
             {'action': 'set_building', 'building': 'house', 'name': 'Home'},
             {'action': 'remove_building', 'building': 'house'})
    for actor in (storage.get_member('k1'), None):
        for call in calls:
            out = agent_tools_v2.execute_tool('house_design', call, actor=actor)
            check('Only a parent can change the house.' in (out.get('message') or ''), out)
    check(not any(b['id'] == 'shed' for b in ts.place()['buildings']), 'nothing added')


def scenario_status_drawings_follows_moved_pages():
    _seed()
    garage = ts.add_building('Garage', 'garage')['id']
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(2):
        doc.new_page(612, 396)
    buf = io.BytesIO()
    doc.save(buf)
    sid = ts.save_source('drawing', 'garage.pdf', buf.getvalue(), part=garage)
    ts.set_page_roles([{'source': sid, 'page': 1, 'building': 'house', 'role': 'other'},
                       {'source': sid, 'page': 2, 'building': 'lot', 'role': 'other'}])
    check(next(s for s in ts.sources() if s['id'] == sid)['part'] == garage, ts.sources())
    summary = agent_tools_v2.house_design_status()['summary']
    check('Garage (Garage, no drawings,' in summary, summary)
    check('(Main house, drawings,' in summary, summary)


if __name__ == '__main__':
    for fn in (scenario_status_drawings_follows_moved_pages,
               scenario_tool_is_registered_and_never_runs_from_a_mission,
               scenario_tool_documents_connected_operation_arguments,
               scenario_tool_edits_through_the_same_operations,
               scenario_tool_refuses_non_parents,
               scenario_a_real_turn_edits_the_house_and_is_metered,
               scenario_a_child_cannot_talk_the_house_into_changing,
               scenario_say_stops_at_a_due_checkpoint_before_any_request,
               scenario_a_checkpoint_inside_the_turn_stops_cleanly,
               scenario_describe_is_short_even_for_a_whole_building,
               scenario_accept_and_reread_drive_the_build,
               scenario_house_design_is_refused_off_the_editor,
               scenario_a_checkpoint_mid_turn_still_reports_what_changed,
               scenario_long_messages_are_capped,
               scenario_add_detached_garage,
               scenario_shed_size_and_roof,
               scenario_remove_refusal_words,
               scenario_status_mentions_place,
               scenario_kid_refused):
        fn()
        print('  ok ', fn.__name__)
