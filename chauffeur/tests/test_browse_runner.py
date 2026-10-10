"""The runner's guards, in code, each with a test: domain, submit, payment,
personal data, release, CAPTCHA, caps, availability. Real Playwright against
a local site; a scripted fake model. Spec 2026-10-10 browse missions §2."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import check  # noqa: F401,E402
from services import storage, browse  # noqa: E402
from browse_pages import serve  # noqa: E402

SRV, PORT = serve()
SITE = f'127.0.0.1:{PORT}'
URL = f'http://{SITE}'
OUT = tempfile.mkdtemp(prefix='browse_test_')
CARD = {'first_name': 'Jeff', 'last_name': 'Wilson', 'email': 'ffejnosliw@gmail.com', 'phone': '919-327-7497', 'zip': '27519'}


def _script(*turns):
    """Each turn: a list of {'name','args'} calls, or a string = final text."""
    seq = list(turns)

    def fake(contents, settings):
        t = seq.pop(0) if seq else 'done'
        if isinstance(t, str):
            return {'calls': [], 'text': t, 'content': None, 'tokens': (100, 10)}
        return {'calls': t, 'text': '', 'content': None, 'tokens': (100, 10)}
    return fake


def _reset(consent=False, cap_turns=40):
    storage.get_settings = lambda: {**{f'contact_{k}': v for k, v in CARD.items()}, 'missions_captcha_attempts': consent,
                                    'llm_gemini_paid_api_key': 'paid'}
    browse.free_memory_mb = lambda: 4096


def _click(sel_text_xy):
    x, y = sel_text_xy
    return {'name': 'click_at', 'args': {'x': x, 'y': y}}


def _xy(page_url, selector):
    """Normalized 0-999 coordinates of an element's center on our pages."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width': 1440, 'height': 900})
        pg.goto(page_url)
        box = pg.locator(selector).first.bounding_box()
        b.close()
    return int((box['x'] + box['width'] / 2) * 1000 / 1440), int((box['y'] + box['height'] / 2) * 1000 / 900)


def scenario_done_report_shape():
    _reset()
    browse._model_step = _script('DONE. Earliest Tue 8-noon. Trip charge $114.95.')
    r = browse.run('read the page', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'done' and '$114.95' in r['text'], f"a plain finish: {r}")
    for k in ('outcome', 'text', 'learned', 'stopped_at', 'wanted_fields', 'turns', 'tokens_in', 'tokens_out', 'seconds', 'screenshots', 'filled'):
        check(k in r, f"report carries {k}")
    check(r['stopped_at'].endswith('/form2') and r['turns'] == 1 and r['screenshots'] and os.path.exists(r['screenshots'][0]), f"facts: {r}")


def scenario_submit_stop_by_words_not_by_type():
    _reset()
    nxt = _xy(f'{URL}/form', '#next')
    # 'Next: Select Appliance' is type=submit but not a booking word: allowed.
    browse._model_step = _script([_click(nxt)], 'DONE.')
    r = browse.run('go to step 2', SITE, dict(CARD), {}, start_url=f'{URL}/form', out_dir=OUT)
    # (The browser's own required-field validation keeps the empty form on
    # /form; what matters is that the guard let the click through: done, not blocked.)
    check(r['outcome'] == 'done', f"a multi-step Next passes the guard: {r['outcome']} {r['text']}")
    book = _xy(f'{URL}/form2', '#book')
    browse._model_step = _script([_click(book)], 'DONE.')
    r = browse.run('book it', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'submit' in r['text'].lower(), f"'Book appointment' (type=button) stops: {r}")
    conf = _xy(f'{URL}/form2', '#confirm')
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': conf[0], 'y': conf[1], 'intent': 'press the button'}}], 'DONE.')
    r = browse.run('confirm', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'blocked', "'Confirm' stops by its label even with a bland intent")
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': 500, 'y': 500, 'intent': 'click Schedule now to finish booking'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'blocked', "a booking intent stops even when the click lands on nothing")


def scenario_domain_allowlist_learns_redirects_only():
    _reset()
    away = _xy(f'{URL}/start', '#away')
    browse._model_step = _script([_click(away)], [_click(away)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'left the site' in r['text'], f"a link to another domain: undone once, then stopped: {r}")
    redir = _xy(f'{URL}/start', '#redir')
    browse._model_step = _script([_click(redir)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'done' and 'localhost' in r['stopped_at'], f"a server redirect to another domain is learned and allowed: {r}")
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'http://localhost:{PORT}/other'}}], [{'name': 'navigate', 'args': {'url': f'http://localhost:{PORT}/other'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'blocked', "a direct navigate to an unlearned domain is stopped")


def scenario_payment_field_stops_before_typing():
    _reset()
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'{URL}/pay'}}], [{'name': 'type_text_at', 'args': {'x': 100, 'y': 100, 'text': '4111'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'payment' in r['text'].lower() and r['turns'] <= 2, f"a payment page ends the run before any typing: {r}")


def scenario_required_contact_fields_pause_for_release():
    _reset()
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'{URL}/form'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'needs_release' and set(r['wanted_fields']) == {'first_name', 'email', 'zip'}, f"the form's contact fields are named: {r}")
    check(not r['filled'], "nothing typed")
    # Released: the same page proceeds; the model may type the released values.
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': 300, 'y': 160, 'text': 'Jeff'}}], 'DONE.')
    r = browse.run('x', SITE, {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'}, {}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] == 'done' and r['filled'].get('first_name') == 'Jeff', f"released fields may be typed and are reported: {r}")


def scenario_typing_guard_refuses_any_unreleased_personal_shape():
    _reset()
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': 300, 'y': 160, 'text': 'someone@else.com'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/zip', out_dir=OUT)
    check(r['outcome'] in ('needs_release', 'blocked') and 'email' in r['text'].lower(), f"an invented email is refused: {r}")
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': 300, 'y': 160, 'text': 'Wilson'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/zip', out_dir=OUT)
    check(r['outcome'] in ('needs_release', 'blocked') and 'last_name' in r['text'], f"a contact-card value not released is refused: {r}")
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': 300, 'y': 160, 'text': '27519'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/zip', out_dir=OUT)
    check(r['outcome'] == 'done', "a released value types fine")


def scenario_captcha_consent_off_stops_untouched():
    _reset(consent=False)
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'{URL}/captcha'}}], [{'name': 'click_at', 'args': {'x': 100, 'y': 100, 'safety_decision': {'decision': 'require_confirmation', 'explanation': 'CAPTCHA'}}}], 'DONE.')
    r = browse.run('x', SITE, {}, {'captcha': False}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'captcha_failed' and r['turns'] <= 2, f"stops at the check, touches nothing: {r}")


def scenario_captcha_consent_on_is_capped():
    _reset(consent=True)
    cap = {'name': 'click_at', 'args': {'x': 100, 'y': 100, 'safety_decision': {'decision': 'require_confirmation', 'explanation': 'The action involves interacting with a CAPTCHA'}}}
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'{URL}/captcha'}}], [cap], [cap], [cap], [cap], 'DONE.')
    r = browse.run('x', SITE, {}, {'captcha': True}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'captcha_failed' and 'attempts' in r['text'].lower(), f"three attempts allowed, the fourth ends it: {r}")
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'{URL}/denied'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {'captcha': True}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'captcha_failed' and 'denied' in r['text'].lower(), "an access-denied page ends it")


def scenario_caps_and_availability():
    _reset()
    browse._model_step = _script(*([[{'name': 'scroll_document', 'args': {'direction': 'down'}}]] * 5))
    r = browse.run('x', SITE, {}, {}, caps={'turns': 3, 'seconds': 300}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'capped' and r['turns'] == 3, f"turn cap: {r}")
    browse.free_memory_mb = lambda: 100
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'refused' and 'room' in r['text'].lower(), f"memory floor: {r}")
    browse.free_memory_mb = lambda: 4096
    orig = browse._launch

    def no_browser(headless=True):
        raise RuntimeError("Executable doesn't exist")
    browse._launch = no_browser
    try:
        r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
        check(r['outcome'] == 'refused' and 'browser' in r['text'].lower(), f"no binary: {r}")
    finally:
        browse._launch = orig
    storage.get_settings = lambda: {'llm_gemini_api_key': 'free'}
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'refused' and 'paid' in r['text'].lower(), "no paid key: refused before any turn")


def scenario_pool_cu_bills_the_paid_key_only():
    from services import model_pools
    check(model_pools.DEFAULT_POOLS.get('cu') == ['gemini-3.8-flash'] and model_pools.TIER_CHAINS.get('browse') == ['cu'], "pool cu, tier browse")
    check(model_pools.api_key_for_pool('cu', {'llm_gemini_api_key': 'free', 'llm_gemini_paid_api_key': 'paid'}) == 'paid', "cu bills the paid key")
    check(model_pools.api_key_for_pool('cu', {'llm_gemini_api_key': 'free'}) == '', "no paid key: nothing, never the free key")
    src = open('services/browse.py', encoding='utf-8').read()
    check('llm_gemini_paid_api_key' not in src and 'api_key_for_pool' in src, "browse.py reads the key through the resolver only")


def scenario_live_step_builds_the_computer_use_call():
    """The live step converts the neutral contents and sends the computer-use
    tool; the client is faked so no network is touched."""
    captured = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            captured['model'] = model
            captured['contents'] = contents
            captured['config'] = config
            from google.genai import types
            fc = types.FunctionCall(name='click_at', args={'x': 10, 'y': 20, 'safety_decision': {'decision': 'require_confirmation', 'explanation': 'cookie'}})
            cand = types.Candidate(content=types.Content(role='model', parts=[types.Part(function_call=fc)]))
            return types.GenerateContentResponse(candidates=[cand], usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=5, candidates_token_count=2))

    class FakeClient:
        models = FakeModels()
    orig = browse._client
    browse._client = lambda key: FakeClient()
    try:
        step = browse._model_step_live([{'role': 'user', 'parts': [{'text': 'hi'}, {'image': b'\x89PNG'}]}], {'llm_gemini_paid_api_key': 'paid'})
        check(step['calls'] == [{'name': 'click_at', 'args': {'x': 10, 'y': 20, 'safety_decision': {'decision': 'require_confirmation', 'explanation': 'cookie'}}}], f"calls parsed: {step['calls']}")
        check(step['tokens'] == (5, 2) and step['content'] is not None, "usage and the model content to append")
        check(captured['model'] == browse.MODEL, "the cu model")
        tool = captured['config'].tools[0]
        check(getattr(tool, 'computer_use', None) is not None, "the computer-use tool is on the call")
        browse._model_step_live([{'role': 'user', 'function_responses': [('click_at', {'url': 'u', 'safety_acknowledgement': 'true'}, b'\x89PNG')]}], {'llm_gemini_paid_api_key': 'paid'})
        parts = captured['contents'][-1].parts
        check(parts and parts[0].function_response and parts[0].function_response.response.get('safety_acknowledgement') == 'true'
              and parts[0].function_response.parts, "a function response carries the url, the acknowledgement and the screenshot")
    finally:
        browse._client = orig


SCENARIOS = [scenario_done_report_shape, scenario_submit_stop_by_words_not_by_type, scenario_domain_allowlist_learns_redirects_only,
             scenario_payment_field_stops_before_typing, scenario_required_contact_fields_pause_for_release,
             scenario_typing_guard_refuses_any_unreleased_personal_shape, scenario_captcha_consent_off_stops_untouched,
             scenario_captcha_consent_on_is_capped, scenario_caps_and_availability,
             scenario_pool_cu_bills_the_paid_key_only, scenario_live_step_builds_the_computer_use_call]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    SRV.shutdown()
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
