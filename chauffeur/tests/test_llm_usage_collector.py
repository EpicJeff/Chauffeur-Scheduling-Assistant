"""Every model request the house editor makes is gated and counted (spec
docs/superpowers/specs/2026-11-07-house-editor-design.md section 9; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 6 and its
review amendment): llm.collect_usage(before, after) sees each provider
request, Gemini, Claude and OpenAI alike, with the tokens the provider
reported; `before` runs ahead of each request and can stop it.

The provider HTTP layer (llm_budget.urlopen) is stubbed with canned bodies in
each provider's real shape. No network.

Run from chauffeur/:  python tests/test_llm_usage_collector.py
"""
import io
import json
import os
import sys
import tempfile
import urllib.error

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_llm_usage_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import llm  # noqa: E402

GEMINI = 'gemini-3-pro'
CLAUDE = 'anthropic:claude-sonnet-5-5'
OPENAI = 'openai:gpt-6.1'
ANSWER = '{"ok": true}'
BODIES = {
    GEMINI: {'candidates': [{'content': {'parts': [{'text': ANSWER}]}, 'finishReason': 'STOP'}],
             'usageMetadata': {'promptTokenCount': 120, 'candidatesTokenCount': 40, 'thoughtsTokenCount': 5},
             'modelVersion': GEMINI},
    CLAUDE: {'content': [{'type': 'text', 'text': ANSWER}], 'stop_reason': 'end_turn',
             'usage': {'input_tokens': 120, 'output_tokens': 45}},
    OPENAI: {'status': 'completed', 'usage': {'input_tokens': 120, 'output_tokens': 45},
             'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': ANSWER}]}]},
}
HOSTS = {GEMINI: 'generativelanguage.googleapis.com', CLAUDE: 'api.anthropic.com', OPENAI: 'api.openai.com'}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Stub:
    """Stands in for llm_budget.urlopen; records every request it receives."""

    def __init__(self, body=None, fail=None):
        self.body, self.fail, self.requests = body, fail, []

    def __call__(self, request, timeout=60):
        self.requests.append(request)
        if self.fail:
            raise self.fail
        return _Response(json.dumps(self.body).encode('utf-8'))

    def __enter__(self):
        self.original = llm.llm_budget.urlopen
        llm.llm_budget.urlopen = self
        return self

    def __exit__(self, *exc):
        llm.llm_budget.urlopen = self.original
        return False


def scenario_each_provider_reports_tokens():
    for model in (GEMINI, CLAUDE, OPENAI):
        with Stub(BODIES[model]) as stub, llm.collect_usage() as rows:
            llm.call_model(model, 'k', 'sys', 'hello', strict_json=True, transient_retries=0)
        check(rows == [{'model': model, 'input_tokens': 120, 'output_tokens': 45, 'images': 0,
                        'prompt_chars': 8, 'max_output_tokens': 0}], (model, rows))
        check(len(stub.requests) == 1, (model, stub.requests))
        req = stub.requests[0]
        check(HOSTS[model] in req.full_url, (model, req.full_url))
        wire = model.split(':', 1)[1] if ':' in model else model
        if model == GEMINI:
            check(f'/models/{wire}' in req.full_url, req.full_url)
        else:
            check(json.loads(req.data.decode('utf-8'))['model'] == wire, (model, req.data[:200]))


def scenario_images_and_output_cap_are_counted():
    img = {'mime': 'image/png', 'b64': 'iVBORw0KGgo='}
    with Stub(BODIES[CLAUDE]), llm.collect_usage() as rows:
        llm.call_model(CLAUDE, 'k', 'sys', 'hello', images=[img, img], max_output_tokens=4096,
                       strict_json=True, transient_retries=0)
    check(rows[0]['images'] == 2 and rows[0]['max_output_tokens'] == 4096, rows)


def scenario_no_collector_no_change():
    with Stub(BODIES[GEMINI]):
        out = llm.call_model(GEMINI, 'k', 'sys', 'hello', strict_json=True, transient_retries=0)
    check(out == {'ok': True}, out)


def scenario_nested_collectors_both_see_the_request():
    with Stub(BODIES[OPENAI]), llm.collect_usage() as outer:
        with llm.collect_usage() as inner:
            llm.call_model(OPENAI, 'k', 'sys', 'hello', strict_json=True, transient_retries=0)
    check(len(outer) == 1 and inner == outer, (outer, inner))


def scenario_before_can_stop_a_request():
    seen = []

    def stop():
        raise RuntimeError('checkpoint')
    with Stub(BODIES[GEMINI]) as stub, llm.collect_usage(before=stop, after=seen.append) as rows:
        try:
            llm.call_model(GEMINI, 'k', 'sys', 'hello', strict_json=True, transient_retries=0)
        except RuntimeError as exc:
            check('checkpoint' in str(exc), exc)
        else:
            raise AssertionError('before() must stop the request')
    check(stub.requests == [] and rows == [] and seen == [], (stub.requests, rows, seen))


def scenario_after_sees_failures_too():
    seen, calls = [], []
    fail = urllib.error.HTTPError('https://api.anthropic.com/v1/messages', 500, 'boom', {}, io.BytesIO(b'{}'))
    with Stub(fail=fail), llm.collect_usage(before=lambda: calls.append(1), after=seen.append) as rows:
        try:
            llm.call_model(CLAUDE, 'k', 'sys', 'hello', strict_json=True, transient_retries=0)
        except Exception:
            pass
    check(calls == [1] and len(seen) == 1 and seen == rows, (calls, seen, rows))
    check(seen[0]['model'] == CLAUDE and seen[0]['input_tokens'] is None and seen[0]['output_tokens'] is None, seen)


if __name__ == '__main__':
    for fn in (scenario_each_provider_reports_tokens,
               scenario_images_and_output_cap_are_counted,
               scenario_no_collector_no_change,
               scenario_nested_collectors_both_see_the_request,
               scenario_before_can_stop_a_request,
               scenario_after_sees_failures_too):
        fn()
        print('  ok ', fn.__name__)
