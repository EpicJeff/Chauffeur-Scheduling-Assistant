"""Section 4.2 probes: real HTTP dispatch, scoped history and SSE delivery."""
from unittest.mock import patch
from fastapi.testclient import TestClient
from harness import check
import access_fixture
from services import storage, access_readers, agent_router, agent_tools_v2 as tools, llm
from test_access_core import KIND
from access_signed_in import observed
from test_access_conversations import enforced, headers, conversation, stream_chunk, extra_contracts
import main


def register(probe):
    for rid, cls, kinds, _ in access_readers.READERS:
        if cls != '4.2-conversation':
            continue
        def run(fx, rkey, col, rid=rid):
            if rid[-1] not in ('/api/chat', '/api/v2/chat/stream'):
                # Empty-kind ownership rows run in the matrix's once-only
                # scenario_conversation_contracts hook, never per viewer.
                return 'skip'
            # Earlier reader probes intentionally rebuild storage. Keep this
            # reader's rows and ids together, as the channel probes do.
            fx = access_fixture.build()
            if col == 'pat':
                return None  # disabled member cannot get a token
            h = (headers(col) if col != 'house' else
                 {'X-Device-Token': storage.enrol_device_token('probe-panel', 'Panel')})
            surface = 'panel' if col == 'house' else 'admin'
            with enforced(), patch.object(llm, 'auto_name_conversation'):
                c = TestClient(main.app)
                if col == 'hal':
                    r = c.get('/api/chat/conversation?surface=admin', headers=h)
                    check(r.status_code == 403, 'helper chat facet remains refused')
                    return None
                conv = conversation(c, h, surface)
                if rid[-1] == '/api/chat':
                    if KIND[rkey] == 'program':
                        storage.update_program(fx.ids[rkey], {'phases': [{'name': fx.secret(rkey), 'units': []}]})
                    def fake(message, **kw):
                        if KIND[rkey] == 'program':
                            return tools.list_programs(acting_member=kw['acting_member'], focus_key=kw['focus_key'])
                        return tools.explain_situation(fx.ids[rkey], kind=KIND[rkey],
                            acting_member=kw['acting_member'], focus_key=kw['focus_key'])
                    with patch.object(agent_router, 'process_agent_request', side_effect=fake):
                        r = c.post('/api/chat?surface=' + surface, headers=h,
                                   json={'message': 'Explain', 'conversation_id': conv['id']})
                    check(r.status_code == 200 and 'error' not in r.json(), f'chat dispatch: {r.text}')
                    return observed(r.text, fx, rkey)
                if rid[-1] == '/api/v2/chat/stream':
                    # History already said stays readable regardless of later narrowing (4.2:165).
                    chunk = stream_chunk(h, conv['id'])
                    check('own words' in chunk and 'secret' not in chunk, 'only owned SSE events')
                    return 'skip'  # ownership assertions, not a new record projection
        probe(rid)(run)


if __name__ == '__main__':
    extra_contracts()
