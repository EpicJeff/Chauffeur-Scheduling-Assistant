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
    for k in ('outcome', 'text', 'learned', 'stopped_at', 'wanted_fields', 'turns', 'actions', 'tokens_in', 'tokens_out', 'seconds', 'screenshots', 'filled'):
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
        tc = captured['config'].thinking_config
        check(tc is not None and tc.thinking_budget == browse.THINK_BUDGET and 1024 <= browse.THINK_BUDGET <= 4096,
              f"a bounded thinking budget per turn (turns ran 11-37 s of thinking, 2026-10-11): {tc}")
        browse._model_step_live([{'role': 'user', 'function_responses': [('click_at', {'url': 'u', 'safety_acknowledgement': 'true'}, b'\x89PNG')]}], {'llm_gemini_paid_api_key': 'paid'})
        parts = captured['contents'][-1].parts
        check(parts and parts[0].function_response and parts[0].function_response.response.get('safety_acknowledgement') == 'true'
              and parts[0].function_response.parts, "a function response carries the url, the acknowledgement and the screenshot")
    finally:
        browse._client = orig


def scenario_enter_never_submits_a_booking_form():
    """Review fix 1: Enter inside a form whose submit control is a stop word is
    the same as clicking it. A plain Next form may still be submitted by Enter."""
    _reset()
    cx, cy = _xy(f'{URL}/confirmform', 'input[name=zip]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': cx, 'y': cy, 'text': '27519', 'press_enter': True}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/confirmform', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'submit' in r['text'].lower() and '/form2' not in r['stopped_at'], f"Enter on a Confirm form is refused: {r}")
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': cx, 'y': cy, 'text': '27519'}}],
                                 [{'name': 'key_combination', 'args': {'keys': ['Enter']}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/confirmform', out_dir=OUT)
    check(r['outcome'] == 'blocked' and '/form2' not in r['stopped_at'], f"a bare Enter key press is refused the same way: {r}")
    zx, zy = _xy(f'{URL}/zip', 'input[name=zip]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': zx, 'y': zy, 'text': '27519', 'press_enter': True}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/zip', out_dir=OUT)
    check(r['outcome'] == 'done', f"Enter on a plain Next form passes: {r}")


def scenario_typing_guard_matches_whole_values_only():
    """Review fix 3: a short card value (apt '2', state 'NC') must not refuse
    every string that contains those characters."""
    storage.get_settings = lambda: {'contact_apt': '2', 'contact_state': 'NC', 'contact_zip': '27519', 'llm_gemini_paid_api_key': 'paid'}
    browse.free_memory_mb = lambda: 4096
    card = browse.contact_card()
    check(browse._personal_violation('Cafe CDT805P2N3S1', {}, card) is None, "a model number is not the apartment")
    check(browse._personal_violation('cancel', {}, card) is None, "'cancel' is not the state")
    check(browse._personal_violation('NC', {}, card) == 'state', "the state typed on its own is still refused")
    check(browse._personal_violation('zip 27519 please', {}, card) == 'zip', "a whole value inside a sentence is refused")
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': 300, 'y': 160, 'text': 'CDT805P2N3S1'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/zip', out_dir=OUT)
    check(r['outcome'] == 'done' and not r['filled'], f"typing a model number neither refuses nor claims apt was filled: {r}")


def scenario_only_main_frame_navigations_teach_the_allowlist():
    """Review fix 4: a redirecting subresource (an iframe, a beacon) must not
    allowlist its target."""
    _reset()
    other = f'http://localhost:{PORT}/other'
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': other}}], [{'name': 'navigate', 'args': {'url': other}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/withframe', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'left the site' in r['text'], f"the iframe's redirect taught nothing: {r}")


def scenario_every_call_in_a_turn_is_checked_against_the_page_it_lands_on():
    """Review fix 5: a click that lands on the payment page followed by a type
    in the SAME turn must stop before the typing."""
    _reset()
    cont = _xy(f'{URL}/topay', '#cont')
    browse._model_step = _script([_click(cont), {'name': 'type_text_at', 'args': {'x': 100, 'y': 100, 'text': '4111'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/topay', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'payment' in r['text'].lower() and r['actions'] == 1, f"the payment page stops the turn mid-way, before the type: {r}")


def scenario_domain_keeps_two_label_public_suffixes():
    """Review fix 8: bbc.co.uk is a site; co.uk is not."""
    check(browse._domain('https://www.bbc.co.uk/x') == 'bbc.co.uk', browse._domain('https://www.bbc.co.uk/x'))
    check(browse._domain('https://shop.example.com.au/') == 'example.com.au', "com.au")
    check(browse._domain('https://www.bodewell.com/guest') == 'bodewell.com' and browse._domain('http://127.0.0.1:8/') == '127.0.0.1'
          and browse._domain('http://localhost:8/') == 'localhost', "plain domains, ips and localhost unchanged")


def scenario_system_chromium_is_the_fallback_when_the_bundle_is_missing():
    """The add-on image: Playwright's CDN download can time out at build time,
    so the image falls back to Debian's chromium; the runner launches that
    one when the bundled binary is absent."""
    import os as _os
    import shutil as _sh
    orig_exists, orig_which = _os.path.exists, _sh.which
    try:
        _os.path.exists = lambda p: False
        _sh.which = lambda n: '/usr/bin/chromium' if n == 'chromium' else None
        check(browse._system_chromium('/nope/chrome') == '/usr/bin/chromium', "the bundle is missing: the system chromium is used")
        _sh.which = lambda n: None
        check(browse._system_chromium('/nope/chrome') is None, "neither: nothing (the runner refuses honestly)")
        _os.path.exists = lambda p: True
        check(browse._system_chromium('/bundled/chrome') is None, "the bundle exists: Playwright's own is used")
    finally:
        _os.path.exists, _sh.which = orig_exists, orig_which
    df = open('Dockerfile', encoding='utf-8').read()
    check('PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT' in df and 'apt-get install -y --no-install-recommends chromium' in df,
          "the image waits longer for the download and falls back to the apt chromium")


def scenario_typing_into_a_contact_field_is_a_release_question_even_with_an_empty_card():
    """2026-10-11, the first live run: the card was empty, the page wanted a
    ZIP, and the model guessed a city. A guess is worthless: typing anything
    into a field labelled like a contact-card field that is not released ends
    the run needs_release naming that field, card or no card."""
    storage.get_settings = lambda: {'llm_gemini_paid_api_key': 'paid'}      # an empty card
    browse.free_memory_mb = lambda: 4096
    zx, zy = _xy(f'{URL}/locate', 'input[name=postal]')      # NOT marked required: the scan does not see it
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': zx, 'y': zy, 'text': '35203'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/locate', out_dir=OUT)
    check(r['outcome'] == 'needs_release' and r['wanted_fields'] == ['zip'] and r['actions'] == 0, f"an invented ZIP never lands: {r}")
    # A released value types fine into the same box.
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': zx, 'y': zy, 'text': '27519'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/locate', out_dir=OUT)
    check(r['outcome'] == 'done' and r['filled'] == {'zip': '27519'}, f"released: typed: {r}")


def scenario_the_model_can_say_what_it_needs_and_knows_what_the_card_holds():
    """The runner names the card's FILLED fields (never their values) and gives
    the model one exit: a NEED: line, which is a release question."""
    _reset()
    seen = []

    def fake(contents, settings):
        seen.append(contents[0]['parts'][0]['text'])
        return {'calls': [], 'text': "The page wants a service ZIP and a street before it shows slots. NEED: zip, street", 'content': None, 'tokens': (1, 1)}
    browse._model_step = fake
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r['outcome'] == 'needs_release' and r['wanted_fields'] == ['zip', 'street'], f"NEED: is a release question: {r}")
    check('first_name' in seen[0] and 'zip' in seen[0] and 'Jeff' not in seen[0] and '27519' not in seen[0], f"the prompt names the card's fields, never values: {seen[0][-400:]}")
    storage.get_settings = lambda: {'llm_gemini_paid_api_key': 'paid'}
    seen.clear()
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check('nothing yet' in seen[0].lower() and r['outcome'] == 'needs_release', f"an empty card is said plainly, and NEED still asks: {seen[0][-300:]}")


def scenario_the_clock_is_ten_minutes():
    check(browse.DEFAULT_CAPS['seconds'] == 600 and browse.DEFAULT_CAPS['turns'] == 40, f"caps: {browse.DEFAULT_CAPS}")


def scenario_a_slow_page_does_not_end_the_run():
    """bodewell.com on the device: 'Page.goto: Timeout 30000ms exceeded'
    waiting for domcontentloaded. A page whose HTML came but whose scripts
    hang is a page to look at, not an error."""
    _reset()
    orig = browse.GOTO_TIMEOUT_MS
    browse.GOTO_TIMEOUT_MS = 800
    browse._model_step = _script('DONE. LEARNED: title=Slow site')
    try:
        r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/hang', out_dir=OUT)
        check(r['outcome'] == 'done' and r['learned'].get('title') == 'Slow site', f"the run went on with what rendered: {r}")
    finally:
        browse.GOTO_TIMEOUT_MS = orig


def scenario_the_start_url_is_the_host_that_answers():
    """bodewell.com does not serve https on its apex (only www., and plain
    http): a browse that starts at https://{site} hangs on any network. The
    runner probes the candidates and starts at the one that connects."""
    _reset()
    browse._model_step = _script('DONE.')
    r = browse.run('x', SITE, {}, {}, out_dir=OUT)        # no start_url: the probe picks
    check(r['outcome'] == 'done' and r['stopped_at'].startswith(f'http://{SITE}'), f"https refused, www refused, http answered: {r['stopped_at']} {r['outcome']} {r['text']}")
    check(browse._pick_start('127.0.0.1:1') is None or browse._pick_start('127.0.0.1:1').startswith('https://'),
          "nothing answers: the https guess stands and the run reports the failure honestly")


def scenario_every_turn_is_on_the_ledger():
    """40 turns and nobody can say where they went (2026-10-11). The report
    carries one line per call: the turn, the action in words, the page it
    left the browser on, the model's and the action's milliseconds."""
    _reset()
    go = _xy(f'{URL}/start', '#go')
    fx, fy = _xy(f'{URL}/form', 'input[name=first]')
    browse._model_step = _script([{'name': 'scroll_document', 'args': {'direction': 'down'}}], [_click(go)],
                                 [{'name': 'type_text_at', 'args': {'x': fx, 'y': fy, 'text': 'Jeff'}}], 'DONE.')
    r = browse.run('x', SITE, {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'}, {}, start_url=f'{URL}/start', out_dir=OUT)
    log = r.get('turns_log') or []
    check(len(log) == 4 and [e['turn'] for e in log] == [1, 2, 3, 4], f"one line per turn, the finish included: {log}")
    for e in log:
        for k in ('turn', 'action', 'url', 'model_ms', 'act_ms'):
            check(k in e, f"a line carries {k}: {e}")
    check('scroll' in log[0]['action'] and 'down' in log[0]['action'], f"a scroll in words: {log[0]}")
    check('click' in log[1]['action'] and 'Schedule service' in log[1]['action'] and log[1]['url'].endswith('/form'), f"a click names what it hit and where it landed: {log[1]}")
    check('type' in log[2]['action'] and 'Jeff' not in log[2]['action'] and 'first_name' in log[2]['action'], f"a type names the field, never the value: {log[2]}")
    check(log[3]['action'].startswith('finish'), f"the finish is a line too: {log[3]}")


def scenario_the_same_click_three_times_is_told_so():
    """A model that keeps clicking the same spot on the same page burns the
    turns. The third identical action on an unchanged page is refused with a
    nudge instead of executed."""
    _reset()
    seen = []
    nothing = _xy(f'{URL}/form2', 'h1')          # a heading: clicking it changes nothing

    def fake(contents, settings):
        seen.append(contents[-1])
        if len(seen) <= 4:
            return {'calls': [_click(nothing)], 'text': '', 'content': None, 'tokens': (1, 1)}
        return {'calls': [], 'text': 'DONE.', 'content': None, 'tokens': (1, 1)}
    browse._model_step = fake
    r = browse.run('x', SITE, dict(CARD), {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'done' and r['actions'] == 2, f"the third and fourth identical clicks did not run: actions={r['actions']}")
    nudges = [c for c in seen if 'function_responses' in c and any('already' in str(fr[1].get('error', '')) for fr in c['function_responses'])]
    check(len(nudges) >= 2, f"the model was told it already did that: {len(nudges)}")
    check(any('repeat' in e['action'] for e in r['turns_log']), f"the ledger says the turn was a repeat: {r['turns_log']}")


def scenario_a_recaptcha_badge_is_not_a_wall():
    """2026-10-11: the ZIP dialog had reCAPTCHA's invisible badge and legal
    line on it, as most forms do; the scan called it a CAPTCHA and bailed with
    consent off before the model acted. A badge is not a challenge: only an
    interstitial page, or the model saying it faces a check, is."""
    _reset(consent=False)
    zx, zy = _xy(f'{URL}/zipdialog', 'input[name=postal]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': zx, 'y': zy, 'text': '27519'}}], 'DONE. LEARNED: ok=1')
    r = browse.run('x', SITE, {'zip': '27519'}, {'captcha': False}, start_url=f'{URL}/zipdialog', out_dir=OUT)
    check(r['outcome'] == 'done' and r['filled'] == {'zip': '27519'}, f"the form with a badge is worked, consent off: {r['outcome']} {r['text']}")
    # A cookie banner on that page (require_confirmation, no CAPTCHA in the explanation) is acknowledged, not a bail.
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': 500, 'y': 500, 'safety_decision': {'decision': 'require_confirmation', 'explanation': 'The action accepts cookies'}}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {'captcha': False}, start_url=f'{URL}/zipdialog', out_dir=OUT)
    check(r['outcome'] == 'done', f"a cookie banner on a badge page is not a CAPTCHA: {r['outcome']} {r['text']}")
    # The real interstitial still stops with consent off (scenario_captcha_consent_off_stops_untouched covers it).


def scenario_the_browser_is_at_home():
    """2026-10-11: "Use my current location" on the site found nothing, because
    a headless browser on the VM has no location, and the model read the
    site's "no service areas for the location detected" as no service for the
    ZIP. The browse context carries the household's geolocation (the home
    address, geocoded) and timezone."""
    _reset()
    orig_home, orig_settings = browse._home_coords, storage.get_settings
    browse._home_coords = lambda: (35.73, -78.85)
    storage.get_settings = lambda: {'llm_gemini_paid_api_key': 'paid', 'timezone': 'America/New_York'}
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = browse._new_context(b, storage.get_settings())
            pg = ctx.new_page()
            pg.goto(f'{URL}/where')
            pg.wait_for_function("document.getElementById('pos').textContent !== 'pending'", timeout=5000)
            pos, tz = pg.locator('#pos').inner_text(), pg.locator('#tz').inner_text()
            b.close()
        check(pos == '35.73,-78.85' and tz == 'America/New_York', f"the page sees home and the family's clock: {pos} {tz}")
        browse._home_coords = lambda: None
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            ctx = browse._new_context(b, {})
            pg = ctx.new_page()
            pg.goto(f'{URL}/where')
            pg.wait_for_function("document.getElementById('pos').textContent !== 'pending'", timeout=5000)
            pos = pg.locator('#pos').inner_text()
            b.close()
        check(pos.startswith('denied'), f"no home address: the site is told nothing rather than a guess: {pos}")
    finally:
        browse._home_coords, storage.get_settings = orig_home, orig_settings
    check('location detected' in browse.RUNNER_SYSTEM and 'Enter' in browse.RUNNER_SYSTEM and 'suggest' in browse.RUNNER_SYSTEM.lower(),
          "the model is told: type the ZIP and press Enter/Find, never a nearby suggestion; a 'location detected' result is not about the ZIP")


def scenario_a_report_of_a_wall_is_the_wall():
    """2026-10-11, the guest form filled: the model wrote "A reCAPTCHA ('I'm not
    a robot') appeared, preventing further navigation" and the runner recorded
    done, so no hand-off reached the person and the planner went elsewhere. A
    final report that says a human check blocked it, or ends with WALL:
    captcha, is captcha_failed; a report that merely mentions one is not."""
    _reset(consent=False)
    browse._model_step = _script("A reCAPTCHA human-verification check (\"I'm not a robot\") appeared above the NEXT button, preventing further navigation without completing verification. No availability was displayed. LEARNED: availability=unknown")
    r = browse.run('x', SITE, dict(CARD), {'captcha': False}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] == 'captcha_failed' and 'robot' in r['text'], f"the wall in words is the wall: {r['outcome']} {r['text'][:80]}")
    browse._model_step = _script("The form needs a photo of the label. WALL: captcha")
    r = browse.run('x', SITE, dict(CARD), {'captcha': False}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] == 'captcha_failed', f"the WALL: line is the wall: {r['outcome']}")
    browse._model_step = _script("Earliest Tue 8-noon; trip charge $114.95. No captcha was needed. LEARNED: fee=$114.95")
    r = browse.run('x', SITE, dict(CARD), {'captcha': False}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] == 'done' and r['learned'].get('fee') == '$114.95', f"a mention is not a wall: {r['outcome']}")
    check('WALL:' in browse.RUNNER_SYSTEM and 'type_text_at' in browse.RUNNER_SYSTEM, "the model is told the WALL: exit and that typing clicks the box itself")


SCENARIOS = [scenario_done_report_shape, scenario_submit_stop_by_words_not_by_type, scenario_domain_allowlist_learns_redirects_only,
             scenario_payment_field_stops_before_typing, scenario_required_contact_fields_pause_for_release,
             scenario_typing_guard_refuses_any_unreleased_personal_shape, scenario_captcha_consent_off_stops_untouched,
             scenario_captcha_consent_on_is_capped, scenario_caps_and_availability,
             scenario_pool_cu_bills_the_paid_key_only, scenario_live_step_builds_the_computer_use_call,
             scenario_enter_never_submits_a_booking_form, scenario_typing_guard_matches_whole_values_only,
             scenario_only_main_frame_navigations_teach_the_allowlist,
             scenario_every_call_in_a_turn_is_checked_against_the_page_it_lands_on, scenario_domain_keeps_two_label_public_suffixes,
             scenario_system_chromium_is_the_fallback_when_the_bundle_is_missing,
             scenario_typing_into_a_contact_field_is_a_release_question_even_with_an_empty_card,
             scenario_the_model_can_say_what_it_needs_and_knows_what_the_card_holds, scenario_the_clock_is_ten_minutes,
             scenario_a_slow_page_does_not_end_the_run, scenario_the_start_url_is_the_host_that_answers,
             scenario_every_turn_is_on_the_ledger, scenario_the_same_click_three_times_is_told_so,
             scenario_a_recaptcha_badge_is_not_a_wall, scenario_the_browser_is_at_home, scenario_a_report_of_a_wall_is_the_wall]

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
