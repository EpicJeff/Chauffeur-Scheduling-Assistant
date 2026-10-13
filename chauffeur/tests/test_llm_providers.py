# chauffeur/tests/test_llm_providers.py
"""The two paid wire branches: what goes on the wire, what comes back. No network."""
import io
import json
import urllib.error
import urllib.request
from unittest import mock
from harness import check
from services import llm, llm_budget

SENT = []


def _fake_urlopen(responses):
    """responses: list of (status, body-dict) popped per call; a status >= 400 raises HTTPError."""
    seq = list(responses)
    def f(request, timeout=60):
        SENT.append((request.full_url, dict(request.header_items()), json.loads(request.data.decode('utf-8')) if request.data else None, request.get_method()))
        status, body = seq.pop(0)
        raw = json.dumps(body).encode('utf-8')
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, 'err', {}, io.BytesIO(raw))
        return io.BytesIO(raw)
    return f


CLAUDE_OK = (200, {'content': [{'type': 'thinking', 'thinking': ''}, {'type': 'text', 'text': '{"a": 1}'}],
                   'stop_reason': 'end_turn', 'usage': {'input_tokens': 12, 'output_tokens': 5}})
OPENAI_OK = (200, {'status': 'completed', 'output': [{'type': 'reasoning'}, {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"a": 1}'}]}],
                   'usage': {'input_tokens': 12, 'output_tokens': 5}})


def scenario_claude_request_shape():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([CLAUDE_OK])):
        metrics = {}
        res = llm._call_llm_json('anthropic', '', 'KEY', 'claude-haiku-5-5', 'SYS', 'USER', temperature=0.7,
                                 images=[{'mime': 'image/png', 'b64': 'AAAA'}], metrics=metrics, thinking_level='high',
                                 response_schema={'type': 'object'})
    url, headers, body, method = SENT[0]
    check(url == 'https://api.anthropic.com/v1/messages' and method == 'POST', url)
    check(headers.get('X-api-key') == 'KEY' and headers.get('Anthropic-version') == '2023-06-01', f'headers: {headers}')
    check(body['model'] == 'claude-haiku-5-5' and body['system'] == 'SYS', 'model and top-level system')
    check('temperature' not in body and 'thinking' not in body, 'no temperature, no thinking field')
    check(body['output_config']['effort'] == 'high', 'effort from thinking_level')
    check(body['output_config']['format'] == {'type': 'json_schema', 'schema': {'type': 'object'}}, 'schema -> output_config.format')
    check(body['max_tokens'] == 8192, 'default max_tokens')
    content = body['messages'][0]['content']
    check(content[0] == {'type': 'text', 'text': 'USER'}, 'user text first')
    check(content[1] == {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAAA'}}, 'image block')
    check(res == {'a': 1}, f'parsed JSON: {res}')
    check(metrics['promptTokenCount'] == 12 and metrics['candidatesTokenCount'] == 5 and metrics['modelVersion'] == 'claude-haiku-5-5', f'metrics mapped: {metrics}')


def scenario_claude_effort_defaults():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([CLAUDE_OK, CLAUDE_OK])):
        llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
        llm._call_llm_json('anthropic', '', 'K', 'claude-opus-5-5', 's', 'u')
    check(SENT[0][2]['output_config']['effort'] == 'low', 'lite/flash default low')
    check(SENT[1][2]['output_config']['effort'] == 'medium', 'pro default medium')


def scenario_claude_refusal_and_truncation():
    refused = (200, {'content': [], 'stop_reason': 'refusal', 'stop_details': {'category': 'cyber'}, 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([refused])):
        res = llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
    check(res.get('error', '').startswith('refused: cyber'), f'refusal is an error: {res}')
    cut = (200, {'content': [{'type': 'text', 'text': '{"a":'}], 'stop_reason': 'max_tokens', 'usage': {'output_tokens': 9}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([cut])):
        try:
            llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u', strict_json=True)
            check(False, 'strict + max_tokens must raise')
        except RuntimeError as e:
            check('Incomplete' in str(e), str(e))
    empty = (200, {'content': [{'type': 'thinking', 'thinking': ''}], 'stop_reason': 'end_turn', 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([empty])):
        try:
            llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
            check(False, 'an empty answer must raise the parse error, not crash elsewhere')
        except RuntimeError as e:
            check('Failed to parse' in str(e) or 'empty' in str(e).lower(), str(e))


def scenario_claude_429_and_5xx():
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(429, {'error': {'message': 'slow down'}})])):
        res = llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u')
    check(str(res.get('error', '')).startswith('429'), f'429 is a returned error: {res}')
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(503, {'error': {'message': 'overloaded'}})])):
        try:
            llm._call_llm_json('anthropic', '', 'K', 'claude-haiku-5-5', 's', 'u', transient_retries=0)
            check(False, '503 raises')
        except RuntimeError as e:
            check('503' in str(e), str(e))


def scenario_openai_request_shape():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([OPENAI_OK])):
        metrics = {}
        res = llm._call_llm_json('openai', '', 'KEY', 'gpt-6-luna', 'SYS', 'USER', temperature=0.7,
                                 images=[{'mime': 'image/jpeg', 'b64': 'BBBB'}], metrics=metrics,
                                 response_schema={'type': 'object'}, max_output_tokens=2000)
    url, headers, body, method = SENT[0]
    check(url == 'https://api.openai.com/v1/responses' and method == 'POST', url)
    check(headers.get('Authorization') == 'Bearer KEY', f'bearer: {headers}')
    check(body['model'] == 'gpt-6-luna' and body['instructions'] == 'SYS', 'model and instructions')
    check('temperature' not in body, 'no temperature')
    check(body['reasoning'] == {'effort': 'low'} and body['max_output_tokens'] == 2000, 'effort + max_output_tokens')
    check(body['text']['format'] == {'type': 'json_schema', 'name': 'result', 'schema': {'type': 'object'}, 'strict': False}, body['text'])
    item = body['input'][0]
    check(item['role'] == 'user' and item['content'][0] == {'type': 'input_text', 'text': 'USER'}, 'input_text')
    check(item['content'][1] == {'type': 'input_image', 'image_url': 'data:image/jpeg;base64,BBBB', 'detail': 'auto'}, 'input_image')
    check(res == {'a': 1} and metrics['promptTokenCount'] == 12 and metrics['modelVersion'] == 'gpt-6-luna', f'{res} {metrics}')


def scenario_openai_json_object_and_incomplete():
    SENT.clear()
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([OPENAI_OK])):
        llm._call_llm_json('openai', '', 'K', 'gpt-6-luna', 's', 'u', strict_json=True)
    check(SENT[0][2]['text']['format'] == {'type': 'json_object'}, 'strict without a schema = json_object')
    partial = (200, {'status': 'incomplete', 'incomplete_details': {'reason': 'max_output_tokens'},
                     'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"a": 1} and more'}]}], 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([partial])):
        try:
            llm._call_llm_json('openai', '', 'K', 'gpt-6-luna', 's', 'u', strict_json=True)
            check(False, 'incomplete + strict raises')
        except RuntimeError as e:
            check('Incomplete' in str(e), str(e))
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([partial])):
        res = llm._call_llm_json('openai', '', 'K', 'gpt-6-luna', 's', 'u')
    check(res == {'a': 1}, f'incomplete without strict still yields the JSON it holds: {res}')


def scenario_call_model_dispatch_and_text():
    SENT.clear()
    title = (200, {'content': [{'type': 'text', 'text': 'Dishwasher repair appointment'}], 'stop_reason': 'end_turn', 'usage': {}})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([title])):
        res = llm.call_model('anthropic:claude-haiku-5-5', 'K', 's', 'u', text=True)
    check(res == {'text': 'Dishwasher repair appointment'}, f'text=True returns prose untouched: {res}')
    check(SENT[0][2]['model'] == 'claude-haiku-5-5', 'the bare id goes on the wire')
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([OPENAI_OK])):
        res = llm.call_model('openai:gpt-6-luna', 'K', 's', 'u')
    check(res == {'a': 1}, 'openai dispatch')


def scenario_connection_tests_cost_no_tokens():
    SENT.clear()
    listing = (200, {'data': [{'id': 'claude-haiku-5-5'}, {'id': 'claude-sonnet-5-5'}]})
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([listing])):
        ok, msg = llm.test_llm_connection('anthropic', api_key='K', model='claude-opus-5-5')
    check(SENT[0][0] == 'https://api.anthropic.com/v1/models' and SENT[0][3] == 'GET', SENT[0][:1])
    check(ok and 'claude-opus-5-5' in msg and 'not' in msg, f'a table id the key cannot see is said loudly: {msg}')
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(200, {'data': [{'id': 'gpt-6-luna'}]})])):
        ok, msg = llm.test_llm_connection('openai', api_key='K', model='gpt-6-luna')
    check(ok and '1 model' in msg, msg)
    with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([(401, {'error': {'message': 'bad key'}})])):
        ok, msg = llm.test_llm_connection('openai', api_key='K')
    check(not ok and 'bad key' in msg, msg)
    ok, msg = llm.test_llm_connection('anthropic', api_key='')
    check(not ok and 'key' in msg.lower(), msg)


def scenario_voice_guard_reads_the_lite_pool():
    from services import app_voice
    class Turn:
        def remaining(self): return 30
    tok = app_voice.current.set(Turn())
    try:
        with mock.patch.object(llm_budget, 'urlopen', _fake_urlopen([CLAUDE_OK])):
            from services import storage
            real = storage.get_settings
            storage.get_settings = lambda: {'llm_provider': 'anthropic', 'llm_anthropic_api_key': 'A'}
            try:
                res = llm.call_model('anthropic:claude-haiku-5-5', 'A', 's', 'u')
                check(res == {'a': 1}, f'haiku is allowed on a voice turn: {res}')
                res = llm.call_model('anthropic:claude-sonnet-5-5', 'A', 's', 'u')
                check('error' in res and 'voice' in res['error'], f'sonnet is not: {res}')
            finally:
                storage.get_settings = real
    finally:
        app_voice.current.reset(tok)


if __name__ == '__main__':
    scenario_claude_request_shape()
    scenario_claude_effort_defaults()
    scenario_claude_refusal_and_truncation()
    scenario_claude_429_and_5xx()
    scenario_openai_request_shape()
    scenario_openai_json_object_and_incomplete()
    scenario_call_model_dispatch_and_text()
    scenario_connection_tests_cost_no_tokens()
    scenario_voice_guard_reads_the_lite_pool()
    print('test_llm_providers OK')
