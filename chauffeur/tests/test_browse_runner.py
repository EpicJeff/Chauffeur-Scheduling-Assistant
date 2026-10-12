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


def _reset(consent=False, cap_turns=40, submit=True):
    storage.get_settings = lambda: {**{f'contact_{k}': v for k, v in CARD.items()}, 'missions_captcha_attempts': consent,
                                    'llm_gemini_paid_api_key': 'paid', 'missions_submit_enabled': submit}
    browse.free_memory_mb = lambda: 4096
    from browse_pages import H
    H.posts.clear()


def _recording(*turns):
    """_script, plus the list of what each model call was shown last."""
    inner, seen = _script(*turns), []

    def fake(contents, settings):
        seen.append(contents[-1])
        return inner(contents, settings)
    return fake, seen


def _errors(seen) -> list:
    """Every error the runner answered the model with."""
    return [str(fr[1].get('error')) for c in seen if isinstance(c, dict) and 'function_responses' in c
            for fr in c['function_responses'] if fr[1].get('error')]


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
    # 'Next: Select Appliance' is type=submit, a step word, no price in its scope: it runs (the device run's second page).
    browse._model_step = _script([_click(nxt)], 'DONE.')
    r = browse.run('go to step 2', SITE, dict(CARD), {}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] == 'done', f"a multi-step Next passes the guard: {r['outcome']} {r['text']}")
    book = _xy(f'{URL}/form2', '#book')
    browse._model_step = _script([_click(book)], 'DONE.')
    r = browse.run('book it', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment', f"'Book appointment' (type=button) asks: {r['outcome']} {r.get('submit')}")
    conf = _xy(f'{URL}/form2', '#confirm')
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': conf[0], 'y': conf[1], 'intent': 'press the button'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Confirm', f"Confirm asks: {r['outcome']}")
    # A submit intent over a blank spot: no control, no state, so no question (it could never be re-checked).
    # Once the model is told to name the control; a second time the run ends blocked.
    blank = {'name': 'click_at', 'args': {'x': 500, 'y': 100, 'intent': 'submit the booking'}}
    fake, seen = _recording([blank], 'DONE.')
    browse._model_step = fake
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    told = _errors(seen)
    check(r['outcome'] == 'done' and r['submit'] is None and any('SUBMIT:' in e for e in told), f"a blank-spot submit intent is refused and the model told: {r['outcome']} {told}")
    browse._model_step = _script([blank], [blank], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'blocked' and r['text'].startswith('form state unreadable') and 'could not be resolved' in r['text'] and r['submit'] is None,
          f"the second time it is blocked, never a question with no button: {r['outcome']} {r['text']}")


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
    """Enter inside a form whose submit control is a commitment is the same as
    clicking it: needs_submit, nothing pressed. A plain Next form may still be
    submitted by Enter."""
    _reset()
    cx, cy = _xy(f'{URL}/confirmform', 'input[name=zip]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': cx, 'y': cy, 'text': '27519', 'press_enter': True}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/confirmform', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Confirm' and '/form2' not in r['stopped_at'], f"Enter on a Confirm form asks: {r['outcome']} {r['stopped_at']}")
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': cx, 'y': cy, 'text': '27519'}}],
                                 [{'name': 'key_combination', 'args': {'keys': ['Enter']}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/confirmform', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and '/form2' not in r['stopped_at'], f"a bare Enter asks the same way: {r['outcome']}")
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


def scenario_a_virtual_display_means_a_headed_browser():
    """2026-10-11: with consent on, reCAPTCHA challenged the headless browser
    three times. A headed Chromium on the add-on's virtual display (Xvfb,
    started by run.sh) is an ordinary browser to the check. The runner goes
    headed whenever a display is there and says which it used."""
    import os as _os
    orig = dict(_os.environ)
    try:
        _os.environ.pop('DISPLAY', None)
        check(browse._headless() is True, "no display: headless")
        _os.environ['DISPLAY'] = ':99'
        check(browse._headless() is False, "a display: headed")
    finally:
        _os.environ.clear()
        _os.environ.update(orig)
    sh = open('run.sh', encoding='utf-8').read()
    check('Xvfb' in sh and 'DISPLAY' in sh, "run.sh starts the virtual display when Xvfb is there")
    df = open('Dockerfile', encoding='utf-8').read()
    check('xvfb' in df.lower(), "the apt fallback installs xvfb beside chromium")
    _reset()
    browse._model_step = _script('DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/start', out_dir=OUT)
    check(r.get('browser') in ('headed', 'headless'), f"the report says which browser ran: {r.get('browser')}")


def _control(path, selector):
    """The runner's control record for the element at a page's selector."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width': 1440, 'height': 900})
        pg.goto(f'{URL}{path}')
        box = pg.locator(selector).first.bounding_box()
        c = browse._control_at(pg, box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        if c:
            c.pop('handle', None)
        b.close()
    return c


def scenario_word_lists_split_pay_from_submit():
    check(not hasattr(browse, 'STOP_WORDS'), "STOP_WORDS is gone")
    for w in ('Book appointment', 'Submit', 'Schedule now', 'Confirm', 'Reserve', 'Send', 'Apply', 'Register', 'Sign up', 'Place request'):
        check(browse.SUBMIT_WORDS.search(w) and not browse.PAY_WORDS.search(w), f"{w} is a submit word")
    for w in ('Pay now', 'Payment', 'Checkout', 'Purchase', 'Buy now', 'Order now', 'Place order', 'Complete purchase'):
        check(browse.PAY_WORDS.search(w), f"{w} is a pay word")
    for w in ('Next', 'Next: Select Appliance', 'Continue', 'Proceed', 'Back', 'Previous', 'Step 2'):
        check(browse.STEP_WORDS.search(w), f"{w} is a step word")
    for w in ('Accept', 'OK', 'Got it', 'Agree', 'Done', 'Finish'):
        check(not browse.STEP_WORDS.search(w) and not browse.SUBMIT_WORDS.search(w), f"{w} is on no list")
    check(browse.MONEY.findall('Trip charge $114.95 and 20 USD') == ['$114.95', '20 USD'], "money amounts")
    check(browse.CONFIRMATION_MARKERS.search('Thank you for your booking. Confirmation number 12345'), "a confirmation page")
    check(not browse.CONFIRMATION_MARKERS.search('Choose a slot. Trip charge $114.95'), "a form is not a confirmation")
    check(not browse.COMMIT_CONTEXT.search('This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply.'),
          "reCAPTCHA's legal line is not agreement language")
    for t in ('By continuing, you agree to our Terms of Service.', 'By booking you accept our terms'):
        check(browse.COMMIT_CONTEXT.search(t), f"{t!r} is agreement language")
    check(browse._keys_of({'keys': '\n'}) == ['enter'] and browse._keys_of({'keys': ['\r']}) == ['enter'], "a newline key is an Enter, never a Space")
    for t in ('By clicking Book you agree', 'I agree to the terms', 'Terms and Conditions', 'Total: $114.95', 'Review your request'):
        check(browse.COMMIT_CONTEXT.search(t), f"{t!r} is commitment language")
    for k, want in (({'keys': 'Shift+Enter'}, ['shift', 'enter']), ({'keys': ['Control', 'Enter']}, ['control', 'enter']),
                    ({'keys': 'NumpadEnter'}, ['enter']), ({'key': 'Return'}, ['enter']), ({'keys': ' '}, ['space']),
                    ({'keys': ['Spacebar']}, ['space']), ({'keys': 'Tab'}, ['tab'])):
        check(browse._keys_of(k) == want, f"{k}: {browse._keys_of(k)}")


def scenario_control_record_reads_the_scope():
    c = _control('/booking', '#book')
    check(c['text'] == 'Book appointment' and c['is_submit_control'] and c['sole_submit'] and not c['only_button'] and not c['disabled'], f"the Book control: {c}")
    st = c['state']
    check(st['selected'] == ['Tue, Oct 20 8AM-12PM'] and st['fields'] == {'notes': ''} and st['prices'] == ['$114.95']
          and 'Trip charge' in st['text'] and len(st['text_sha']) == 64, f"the snapshot: {st}")
    c = _control('/lockin', '#lock')
    check(c['tag'] == 'DIV' and c['only_button'] and c['state']['selected'] == ['Thu, Oct 22 8AM-12PM'] and c['state']['prices'] == ['$114.95'],
          f"an aria-checked picker is in selected; the scope is the section: {c}")
    c = _control('/tiles', '#t1')
    check(c['text'] == 'Dishwasher' and c['is_submit_control'] and not c['sole_submit'] and not c['only_button'] and not c['last_button'], f"a tile among eight: {c}")
    c = _control('/longform', '#book')
    check(c['state']['prices'] == ['$114.95'] and len(c['state']['text']) > 1500, "the whole text, no truncation; the far price is listed")
    c = _control('/iconbtn', '#icon')
    check(c['text'] == 'Submit request', f"an icon button reads its aria-label: {c}")
    c = _control('/disabledbook', '#book')
    check(c['disabled'], "a disabled control says so")
    c = _control('/framedbook', '#w')
    check(c['iframe'], "an iframe under the point says so")
    check(browse._display('x' * 400) == 'x' * 300, "display is 300 characters")
    import hashlib
    c = _control('/booking', '#book')
    check(len(c['state']['text_sha']) == 64 and c['state']['text_sha'] == hashlib.sha256(c['state']['text'].encode()).hexdigest(),
          "text_sha is the sha256 of the scope text, computed in Python")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={'width': 1440, 'height': 900})
        pg.goto(f'{URL}/booking')
        check(browse._control_at(pg, -5, -5) is None, "a point outside the viewport has no control")
        b.close()


def scenario_classification_is_by_evidence_not_label():
    cases = [('/booking', '#book', '', 'submit'), ('/booking', '#pay', '', 'pay'), ('/buynow', '#buy', '', 'pay'),
             ('/sendapp', '#send', '', 'submit'), ('/agree', '#accept', '', 'submit'), ('/cookie', '#accept', '', 'run'),
             ('/lockin', '#lock', '', 'submit'), ('/tiles', '#t1', '', 'run'), ('/pricedcontinue', '#cont', '', 'submit'),
             ('/stepcontinue', '#cont', '', 'run'), ('/form', '#next', '', 'run'), ('/iconbtn', '#icon', '', 'submit'),
             ('/disabledbook', '#book', '', 'run'), ('/framedbook', '#w', '', 'run'), ('/framedbook', '#w', 'book the slot', 'submit'),
             ('/tiles', '#t1', 'confirm the booking', 'submit'), ('/cookie', '#accept', 'pay for it', 'pay'),
             ('/fulltrip', '#next', '', 'run'), ('/agreecontinue', '#cont', '', 'submit'), ('/labelbook', '#bklabel', '', 'submit')]
    for path, sel, intent, want in cases:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            pg = b.new_page(viewport={'width': 1440, 'height': 900})
            pg.goto(f'{URL}{path}')
            box = pg.locator(sel).first.bounding_box()
            c = browse._control_at(pg, box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            got = browse._classify(c, intent)
            b.close()
        check(got == want, f"{path} {sel} intent={intent!r}: {got} (wanted {want})")
    check(browse._classify(None, 'book it') == 'submit' and browse._classify(None, '') == 'run', "no control: the intent alone decides")


def scenario_the_gate_returns_a_question_with_the_whole_transaction():
    _reset()
    book = _xy(f'{URL}/booking', '#book')
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': book[0], 'y': book[1], 'intent': 'book the Tuesday slot'}}], 'DONE.')
    r = browse.run('book Tue', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    s = r['submit']
    check(r['outcome'] == 'needs_submit' and s['button'] == 'Book appointment' and s['url'].endswith('/booking') and s['intent'] == 'book the Tuesday slot', f"the record: {s}")
    check(s['state']['selected'] == ['Tue, Oct 20 8AM-12PM'] and s['state']['prices'] == ['$114.95'] and len(s['state']['text_sha']) == 64
          and len(s['display']) <= 300 and 'Trip charge' in s['display'], f"state and display: {s['state']} {s['display'][:60]}")
    from browse_pages import H
    check(not H.posts and r['actions'] == 0, "nothing was pressed")
    check(r['turns_log'][-1]['action'].startswith('needs_submit: Book appointment'), f"the ledger: {r['turns_log'][-1]}")
    # Space on the focused Book button asks the same way (focus it by script, as a model's Tab presses would).
    # (A wait between the Tabs: the loop guard refuses a third identical key press in a row.)
    tab = {'name': 'key_combination', 'args': {'keys': ['Tab']}}
    browse._model_step = _script([tab, tab, {'name': 'wait', 'args': {}}, tab, {'name': 'key_combination', 'args': {'keys': ['Space']}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment', f"Space on the focused Book asks: {r['outcome']} {(r.get('submit') or {}).get('button')}")
    # The model's own exit: SUBMIT: <text>.
    browse._model_step = _script('I see the slot. LEARNED: slot=Tue, Oct 20 8AM-12PM\nSUBMIT: Book appointment')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment' and r['submit']['state']['selected'] and r['submit']['facts'] == {'slot': 'Tue, Oct 20 8AM-12PM'},
          f"SUBMIT: resolves the control, reads its scope, carries the facts: {r.get('submit')}")
    check(r is not None, "run never returns None")
    # A SUBMIT: naming a step control the classifier would run still asks: the model's naming is the evidence.
    browse._model_step = _script('SUBMIT: Continue')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/stepcontinue', out_dir=OUT)
    check(r is not None and r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Continue', f"SUBMIT: Continue asks: {r and r['outcome']}")
    # A SUBMIT: naming a control that is not there: told once, then blocked.
    browse._model_step = _script('SUBMIT: Reserve this', 'SUBMIT: Reserve this')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'could not find the control' in r['text'] and r['turns'] == 2, f"a missing control: {r['outcome']} {r['text']}")


def scenario_pay_words_are_a_wall_whatever_else():
    _reset()
    pay = _xy(f'{URL}/booking', '#pay')
    browse._model_step = _script([_click(pay)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'blocked' and r['text'].startswith('payment') and 'Pay now' in r['text'], f"Pay now is blocked: payment: {r['text']}")
    browse._model_step = _script('SUBMIT: Pay now')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'blocked' and r['text'].startswith('payment'), f"SUBMIT: Pay now is payment, not a question: {r['outcome']} {r['text']}")
    browse._model_step = _script('SUBMIT: Buy now')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/buynow', out_dir=OUT)
    check(r['outcome'] == 'blocked' and r['text'].startswith('payment'), f"SUBMIT: Buy now is payment: {r['outcome']} {r['text']}")
    buy = _xy(f'{URL}/buynow', '#buy')
    browse._model_step = _script([_click(buy)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/buynow', out_dir=OUT,
                   approved={'button': 'Buy now', 'url': f'{URL}/buynow', 'state': {'text_sha': 'x'}, 'ask_id': 'a1'}, on_attempt=lambda rec: True)
    check(r['outcome'] == 'blocked' and r['text'].startswith('payment'), f"a saved-card Buy now is payment even with approved set: {r['text']}")
    check(r['turns_log'][-1]['action'].startswith('blocked: payment (Buy now)'), f"the ledger names the control: {r['turns_log'][-1]}")


def scenario_the_fallback_classifies_unfamiliar_labels_by_evidence():
    _reset()
    for path, sel, want in (('/sendapp', '#send', 'needs_submit'), ('/agree', '#accept', 'needs_submit'), ('/cookie', '#accept', 'done'),
                            ('/lockin', '#lock', 'needs_submit'), ('/tiles', '#t1', 'done'), ('/pricedcontinue', '#cont', 'needs_submit'),
                            ('/stepcontinue', '#cont', 'done'), ('/iconbtn', '#icon', 'needs_submit'), ('/disabledbook', '#book', 'done'),
                            ('/framedbook', '#w', 'done')):
        xy = _xy(f'{URL}{path}', sel)
        browse._model_step = _script([_click(xy)], 'DONE.')
        r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}{path}', out_dir=OUT)
        check(r['outcome'] == want, f"{path} {sel}: {r['outcome']} (wanted {want}) {r['text'][:80]}")
    xy = _xy(f'{URL}/iconbtn', '#icon')
    browse._model_step = _script([_click(xy)], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/iconbtn', out_dir=OUT)
    check(r['submit']['button'] == 'Submit request', "an icon button's question names its aria-label")
    xy = _xy(f'{URL}/framedbook', '#w')
    framed = {'name': 'click_at', 'args': {'x': xy[0], 'y': xy[1], 'intent': 'book the slot in the widget'}}
    fake, seen = _recording([framed], 'DONE.')
    browse._model_step = fake
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/framedbook', out_dir=OUT)
    check(r['outcome'] == 'done' and r['submit'] is None and any('SUBMIT:' in e for e in _errors(seen)),
          f"an iframe under the point: the intent still gates, refused and told (no question it cannot answer): {r['outcome']}")
    browse._model_step = _script([framed], [framed], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/framedbook', out_dir=OUT)
    check(r['outcome'] == 'blocked' and r['text'].startswith('form state unreadable') and r['submit'] is None, f"twice: blocked: {r['outcome']} {r['text']}")
    xy = _xy(f'{URL}/longform', '#book')
    browse._model_step = _script([_click(xy)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/longform', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['state']['prices'] == ['$114.95'], f"the far price: {r['submit']['state']['prices']}")


def scenario_the_switch_off_restores_the_old_wall():
    _reset(submit=False)
    book = _xy(f'{URL}/booking', '#book')
    browse._model_step = _script([_click(book)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'would submit' in r['text'], f"switch off: blocked would submit: {r['outcome']} {r['text']}")
    browse._model_step = _script('SUBMIT: Book appointment')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'blocked' and 'would submit' in r['text'], "a SUBMIT: line with the switch off is the old wall too")
    check('SUBMIT:' not in browse._system_text({'missions_submit_enabled': False}) and 'SUBMIT:' in browse._system_text({}),
          "the model is told about the SUBMIT: exit only when the switch is on")


def _approved_for(path, selector='#book', ask_id='a1', intent=''):
    """A parent-approved record for the control on a fixture page, as the gate produces it."""
    _reset()
    xy = _xy(f'{URL}{path}', selector)
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': xy[0], 'y': xy[1], 'intent': intent}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}{path}', out_dir=OUT)
    assert r['outcome'] == 'needs_submit', r
    return {**r['submit'], 'ask_id': ask_id}, xy


def scenario_the_approved_press_runs_once_only_when_everything_matches():
    from browse_pages import H
    approved, xy = _approved_for('/booking')
    order = []
    browse._model_step = _script([_click(xy)], 'CONFIRMED: Thank you for your booking. Confirmation number 12345.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved,
                   on_attempt=lambda rec: order.append(('attempt', len(H.posts), rec['ask_id'])) or True)
    check(r['outcome'] == 'submitted' and len(H.posts) == 1 and order == [('attempt', 0, 'a1')], f"one press, the attempt recorded before it: {r['outcome']} posts={len(H.posts)} {order}")
    a = r['attempt']
    check(a['ask_id'] == 'a1' and a['button'] == 'Book appointment' and a['outcome'] == 'confirmed' and '12345' in a['text'] and a['pressed_at'] > 0
          and a['state']['selected'] == ['Tue, Oct 20 8AM-12PM'], f"the attempt travels with its outcome: {a}")
    check(any(e['action'].startswith("press 'Book appointment' (approved, ask a1") for e in r['turns_log']), f"the ledger: {[e['action'] for e in r['turns_log']]}")
    H.posts.clear()
    browse._model_step = _script([{'name': 'double_click_at', 'args': {'x': xy[0], 'y': xy[1]}}], 'CONFIRMED: booked')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submitted' and len(H.posts) == 1, f"an approved double-click lands one POST: {len(H.posts)}")
    H.posts.clear()
    nx, ny = _xy(f'{URL}/booking', 'input[name=notes]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': nx, 'y': ny, 'text': '', 'press_enter': True}}], 'CONFIRMED: booked')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submitted' and len(H.posts) == 1, f"an approved type+Enter lands one POST: {len(H.posts)} {r['text'][:80]}")


def scenario_the_approved_press_refuses_when_the_page_moved():
    from browse_pages import H
    approved, xy = _approved_for('/booking')
    xy2 = _xy(f'{URL}/booking2', '#book')
    browse._model_step = _script([_click(xy2)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking2', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'needs_submit' and not H.posts and r['submit']['state']['selected'] == ['Thu, Oct 22 8AM-12PM'], f"re-asked, nothing pressed: {r['outcome']} {len(H.posts)}")
    ch = r['changed']
    check(any(c.startswith('selected: Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM)') for c in ch)
          and any(c.startswith('prices: $124.95 appears; $114.95 does not') for c in ch) and 'text: changed' in ch, f"changed names what moved: {ch}")
    xy3 = _xy(f'{URL}/form2', '#book')
    browse._model_step = _script([_click(xy3)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'needs_submit' and not H.posts and r['changed'], "same label, different page state: re-ask")
    browse._model_step = _script([_click(xy)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: False)
    check(r['outcome'] == 'blocked' and 'approval withdrawn' in r['text'] and not H.posts and r['attempt'] is None, f"a false from on_attempt: {r['outcome']} {r['text']}")
    browse._model_step = _script([_click(xy)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved={**approved, 'state': {}}, on_attempt=lambda rec: True)
    check(r['outcome'] == 'needs_submit' and not H.posts and r['changed'] == ['state: the approved record held no form state'], "an empty approved state is a question, never a press")


def scenario_the_outcome_lines_and_the_end_of_the_run():
    from browse_pages import H, PAGES
    approved, xy = _approved_for('/booking')
    for line, want, att in (('REJECTED: That slot was just taken.', 'submit_rejected', 'rejected'), ('UNKNOWN: a spinner', 'submit_unknown', 'unknown'),
                            ('DONE. nothing to say', 'submit_unknown', 'unknown')):
        H.posts.clear()
        browse._model_step = _script([_click(xy)], line)
        r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
        check(r['outcome'] == want and r['attempt']['outcome'] == att, f"{line!r}: {r['outcome']} {r['attempt']['outcome']}")
    H.posts.clear()
    browse._model_step = _script([_click(xy)], [{'name': 'scroll_document', 'args': {'direction': 'down'}}], [_click(xy)], [_click(xy)], 'CONFIRMED: late')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submit_unknown' and len(H.posts) == 1 and any('the press is done' in e['action'] for e in r['turns_log']), f"no second press: {r['outcome']} posts={len(H.posts)}")
    H.posts.clear()
    browse._model_step = _script([_click(xy)])          # the model never answers: the cap ends it
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, caps={'turns': 2}, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submit_unknown' and r['attempt']['outcome'] == 'unknown', f"a cap after the press is unknown, never capped: {r['outcome']}")
    # A page that reads as a confirmation after an UNGATED press: submit_unknown with an unasked attempt.
    _reset()
    PAGES['/sneaky'] = '<h1>Hi</h1><div id="go" role="button" onclick="location.href=\'/thanks\'">Go</div><p>plain copy</p>'
    g = _xy(f'{URL}/sneaky', '#go')
    browse._model_step = _script([_click(g)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/sneaky', out_dir=OUT)
    check(r['outcome'] == 'submit_unknown' and r['attempt'] and r['attempt'].get('unasked') and r['attempt']['button'] == 'Go' and r['attempt']['outcome'] == 'unknown'
          and r['attempt']['ask_id'] is None, f"the confirmation backstop: {r['outcome']} {r.get('attempt')}")
    browse._model_step = _script([{'name': 'navigate', 'args': {'url': f'{URL}/thanks'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/cookie', out_dir=OUT)
    check(r['outcome'] == 'done' and not r['attempt'], "a navigate to a confirmation page is not a press: no backstop")


def scenario_continued_resumes_unapproved_and_payment_after_the_press_keeps_the_attempt():
    from browse_pages import H, PAGES
    approved2, xy = _approved_for('/stepcontinue', '#cont', ask_id='a2', intent='submit the slot')
    book = _xy(f'{URL}/booking', '#book')
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': xy[0], 'y': xy[1], 'intent': 'submit the slot'}}],
                                 'CONTINUED: the booking page with Tue selected', [_click(book)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/stepcontinue', out_dir=OUT, approved=approved2, on_attempt=lambda rec: True)
    check(r['outcome'] == 'needs_submit' and r['attempt']['outcome'] == 'continued' and r['submit']['button'] == 'Book appointment' and not H.posts,
          f"CONTINUED: the run goes on unapproved and the real commitment asks: {r['outcome']} {(r.get('attempt') or {}).get('outcome')}")
    approved, xy = _approved_for('/booking')
    browse._model_step = _script([_click(xy)], 'CONTINUED: next step')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submit_unknown' and r['attempt']['outcome'] == 'unknown', f"an uncorroborated CONTINUED (a confirmation page) is unknown: {r['outcome']}")
    PAGES['/bookpay'] = PAGES['/booking'].replace('action="/booked" method="post"', 'action="/payafter" method="get"')
    approved, xy = _approved_for('/bookpay')
    browse._model_step = _script([_click(xy)], 'UNKNOWN: a card form')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/bookpay', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'blocked' and 'payment' in r['text'] and r['attempt'] and r['attempt']['outcome'] == 'unknown', f"payment after the press keeps the attempt: {r['outcome']} {r.get('attempt')}")
    check('CONFIRMED:' in browse._system_text({}, approved=True) and 'CONFIRMED:' not in browse._system_text({}), "the outcome lines are taught only on an approved run")


def scenario_an_approved_run_that_writes_submit_presses_through_the_same_match():
    from browse_pages import H
    approved, xy = _approved_for('/booking')
    t = browse._system_text({}, approved={'button': 'Book appointment'})
    check('Book appointment' in t and 'SUBMIT:' not in t and 'CONFIRMED:' in t, "an approved run is told the control, not the SUBMIT: exit")
    browse._model_step = _script('SUBMIT: Book appointment', 'CONFIRMED: Confirmation number 12345')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submitted' and len(H.posts) == 1 and r['attempt']['outcome'] == 'confirmed', f"SUBMIT: on an approved run presses once: {r['outcome']} posts={len(H.posts)}")
    check(any('via SUBMIT:' in e['action'] for e in r['turns_log']), "the ledger says via SUBMIT:")
    H.posts.clear()
    browse._model_step = _script('SUBMIT: Book appointment')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking2', out_dir=OUT, approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'needs_submit' and not H.posts and any(c.startswith('selected:') for c in r['changed'])
          and any(c.startswith('prices:') for c in r['changed']), f"SUBMIT: on a moved page re-asks with changed: {r['outcome']} {r['changed']}")
    browse._model_step = _script('SUBMIT: Book appointment')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=lambda rec: False)
    check(r['outcome'] == 'blocked' and 'approval withdrawn' in r['text'] and not H.posts, "SUBMIT: with on_attempt false: withdrawn")


def scenario_the_approved_match_holes_are_closed():
    from browse_pages import H
    approved, xy = _approved_for('/booking')
    def boom(rec):
        raise RuntimeError('mission gone')
    browse._model_step = _script([_click(xy)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved, on_attempt=boom)
    check(r['outcome'] == 'blocked' and 'approval withdrawn' in r['text'] and not H.posts, f"on_attempt raising: {r['outcome']} {r['text']}")
    browse._model_step = _script([_click(xy)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved={**approved, 'url': 'https://elsewhere.example/x'}, on_attempt=lambda rec: True)
    check(r['outcome'] == 'needs_submit' and not H.posts and any(c.startswith('site:') for c in r['changed']), f"a domain mismatch re-asks with site: {r['changed']}")
    # Enter and Space in one combination, focus in the booking form: one on_attempt, one POST.
    calls = []
    approved_f, _ = _approved_for('/booking')
    nx, ny = _xy(f'{URL}/booking', 'input[name=notes]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': nx, 'y': ny, 'text': ''}}],
                                 [{'name': 'key_combination', 'args': {'keys': ['Enter', 'Space']}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT, approved=approved_f, on_attempt=lambda rec: calls.append(rec) or True)
    check(len(calls) == 1 and len(H.posts) == 1, f"Enter+Space gates once and presses once: on_attempt={len(calls)} posts={len(H.posts)} {r['outcome']}")
    # Approved on intent words alone: the re-run with no intent still goes through the approved path.
    H.posts.clear()
    approved_i, xy2 = _approved_for('/stepcontinue', '#cont', intent='submit the slot')
    browse._model_step = _script([_click(xy2)], 'CONTINUED: next')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/stepcontinue', out_dir=OUT, approved=approved_i, on_attempt=lambda rec: True)
    check(r['attempt'] is not None and len(H.posts) <= 1, f"an intent-approved control is pressed through the approved path: {r['outcome']} {r['attempt']}")


def scenario_an_unasked_press_after_continued_rides_beside_the_approved_attempt():
    """Review fix (Task 5, I2): the confirmation backstop never overwrites the
    approved attempt a CONTINUED already resolved; the unasked press is in
    attempts_extra."""
    from browse_pages import H, PAGES
    approved2, xy = _approved_for('/stepcontinue', '#cont', ask_id='a2', intent='submit the slot')
    PAGES['/sneaky'] = '<h1>Hi</h1><div id="go" role="button" onclick="location.href=\'/thanks\'">Go</div><p>plain copy</p>'
    g = _xy(f'{URL}/sneaky', '#go')
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': xy[0], 'y': xy[1], 'intent': 'submit the slot'}}],
                                 'CONTINUED: the booking page with Tue selected',
                                 [{'name': 'navigate', 'args': {'url': f'{URL}/sneaky'}}], [_click(g)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/stepcontinue', out_dir=OUT, approved=approved2, on_attempt=lambda rec: True)
    extra = r.get('attempts_extra') or []
    check(r['outcome'] == 'submit_unknown' and r['attempt']['outcome'] == 'continued' and r['attempt']['ask_id'] == 'a2'
          and len(extra) == 1 and extra[0]['unasked'] and extra[0]['button'] == 'Go' and extra[0]['outcome'] == 'unknown' and extra[0]['ask_id'] is None,
          f"the approved attempt stays continued, the unasked press rides beside it: {r['outcome']} {r.get('attempt')} {extra}")

def scenario_every_press_path_goes_through_the_gate():
    """Final review C1: type_text_at's click, a typed newline or space, a key
    chord in a string, a drag that lands where it grabbed, and Enter on a
    focused link each press a control; each one is gated like a click."""
    from browse_pages import H
    _reset()
    book = _xy(f'{URL}/booking', '#book')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': book[0], 'y': book[1], 'text': 'x'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment' and not H.posts,
          f"type_text_at aimed at Book: its click is the press, gated: {r['outcome']} posts={len(H.posts)}")
    cx, cy = _xy(f'{URL}/confirmform', 'input[name=zip]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': cx, 'y': cy, 'text': 'hello\n'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/confirmform', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Confirm' and '/form2' not in r['stopped_at'] and not H.posts,
          f"a typed newline is an Enter, gated: {r['outcome']} {r['stopped_at']}")
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': cx, 'y': cy, 'text': '27519'}}],
                                 [{'name': 'key_combination', 'args': {'keys': 'Shift+Enter'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/confirmform', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Confirm' and '/form2' not in r['stopped_at'],
          f"'Shift+Enter' as one string is an Enter, gated: {r['outcome']} {r['stopped_at']}")
    browse._model_step = _script([{'name': 'drag_and_drop', 'args': {'x': book[0], 'y': book[1], 'destination_x': book[0], 'destination_y': book[1]}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment' and not H.posts,
          f"a drag from Book to Book is a click, gated: {r['outcome']} posts={len(H.posts)}")
    tab = {'name': 'key_combination', 'args': {'keys': ['Tab']}}
    browse._model_step = _script([tab], [{'name': 'key_combination', 'args': {'keys': ['Enter']}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/linkbook', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book now' and not H.posts,
          f"Enter on a focused link styled as a button is gated: {r['outcome']} {(r.get('submit') or {}).get('button')} posts={len(H.posts)}")
    # A space typed while a button has focus would press it: refused, told, nothing pressed.
    fake, seen = _recording([tab], [{'name': 'type', 'args': {'text': 'a b'}}], 'DONE.')
    browse._model_step = fake
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/cookie', out_dir=OUT)
    check(r['outcome'] == 'done' and any(browse.TYPE_NOT_A_BOX in e for e in _errors(seen)) and any('(refused)' in e['action'] for e in r['turns_log']),
          f"a typed space on a focused button is refused: {r['outcome']} {_errors(seen)}")
    # Typing into a real text box still works.
    zx, zy = _xy(f'{URL}/zip', 'input[name=zip]')
    browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': zx, 'y': zy, 'text': '27519'}}], 'DONE.')
    r = browse.run('x', SITE, {'zip': '27519'}, {}, start_url=f'{URL}/zip', out_dir=OUT)
    check(r['outcome'] == 'done' and r['filled'] == {'zip': '27519'}, f"a text box types: {r['outcome']} {r['filled']}")


def scenario_an_in_page_confirmation_is_caught_by_the_backstop():
    """Final review I6: a JS button that books in place (the body becomes a
    confirmation, the URL never moves) is an unasked attempt too."""
    _reset()
    g = _xy(f'{URL}/ajaxbook', '#grab')
    browse._model_step = _script([_click(g)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/ajaxbook', out_dir=OUT)
    a = r.get('attempt') or {}
    check(r['outcome'] == 'submit_unknown' and a.get('unasked') and a.get('button') == 'Grab it' and a.get('outcome') == 'unknown'
          and r['stopped_at'].endswith('/ajaxbook'), f"an in-page confirmation after an ungated press: {r['outcome']} {a}")


def scenario_the_device_sequence_runs_ungated_until_book():
    """Final review I7, the device run end to end on the local site: the
    contact form (reCAPTCHA's legal line inside it), Next, the Dishwasher tile,
    the slot page, then Book appointment asks; the approved run presses once."""
    from browse_pages import H
    _reset()
    f = _xy(f'{URL}/fulltrip', 'input[name=first]')
    e = _xy(f'{URL}/fulltrip', 'input[name=email]')
    z = _xy(f'{URL}/fulltrip', 'input[name=zip]')
    nxt = _xy(f'{URL}/fulltrip', '#next')
    t1 = _xy(f'{URL}/tiles', '#t1')
    tob = _xy(f'{URL}/slots', '#tobook')
    book = _xy(f'{URL}/booking', '#book')
    typing = [{'name': 'type_text_at', 'args': {'x': f[0], 'y': f[1], 'text': 'Jeff'}},
              {'name': 'type_text_at', 'args': {'x': e[0], 'y': e[1], 'text': CARD['email']}},
              {'name': 'type_text_at', 'args': {'x': z[0], 'y': z[1], 'text': CARD['zip']}}]
    browse._model_step = _script(typing, [_click(nxt)], [_click(t1)], [_click(tob)], [_click(book)], 'DONE.')
    r = browse.run('book the dishwasher repair', SITE, dict(CARD), {}, start_url=f'{URL}/fulltrip', out_dir=OUT)
    urls = [x['url'] for x in r['turns_log']]
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment' and r['submit']['url'].endswith('/booking') and not H.posts,
          f"Next, the tile and the slot link run; Book asks: {r['outcome']} {r['text'][:80]} {urls}")
    check(any('/tiles' in u for u in urls) and any('/slots' in u for u in urls), f"the run went through every step: {urls}")
    approved = {**r['submit'], 'ask_id': 'a1'}
    browse._model_step = _script([_click(book)], 'CONFIRMED: Thank you for your booking. Confirmation number 12345.')
    r = browse.run('book the dishwasher repair', SITE, dict(CARD), {}, start_url=f'{URL}/booking', out_dir=OUT,
                   approved=approved, on_attempt=lambda rec: True)
    check(r['outcome'] == 'submitted' and len(H.posts) == 1 and r['attempt']['outcome'] == 'confirmed', f"the approved run presses once: {r['outcome']} posts={len(H.posts)}")


def scenario_the_re_review_holes_are_closed():
    """Final re-review: a confirmation an XHR renders seconds after an ungated
    press; the commonest agreement wording; a multi-line note in a textarea;
    a click on the label of a submit input."""
    from browse_pages import H
    _reset()
    g = _xy(f'{URL}/ajaxlate', '#grab')
    browse._model_step = _script([_click(g)], [{'name': 'wait', 'args': {}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/ajaxlate', out_dir=OUT)
    a = r.get('attempt') or {}
    check(r['outcome'] == 'submit_unknown' and a.get('unasked') and a.get('button') == 'Grab it' and '778' in (a.get('text') or ''),
          f"a confirmation 1.5 s after an ungated press is still an unasked attempt: {r['outcome']} {a}")
    c = _xy(f'{URL}/agreecontinue', '#cont')
    browse._model_step = _script([_click(c)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/agreecontinue', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Continue' and not H.posts,
          f"'By continuing, you agree to our Terms.' over a sole Continue asks: {r['outcome']} posts={len(H.posts)}")
    n = _xy(f'{URL}/notes', '#nt')
    values, orig_act = [], browse._act

    def act_and_read(page, name, args):
        orig_act(page, name, args)
        values.append(page.evaluate("document.getElementById('nt') ? document.getElementById('nt').value : null"))
    browse._act = act_and_read
    try:
        browse._model_step = _script([{'name': 'type_text_at', 'args': {'x': n[0], 'y': n[1], 'text': 'line1\nline2'}}], 'DONE.')
        r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/notes', out_dir=OUT)
    finally:
        browse._act = orig_act
    check(r['outcome'] == 'done' and values == ['line1\nline2'] and not H.posts,
          f"a newline in a textarea is a line break, not a submit: {r['outcome']} {values} posts={len(H.posts)}")
    lb = _xy(f'{URL}/labelbook', '#bklabel')
    browse._model_step = _script([_click(lb)], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/labelbook', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Go' and not H.posts,
          f"a click on the label of a submit input is that press, read by its label: {r['outcome']} {(r.get('submit') or {}).get('button')} posts={len(H.posts)}")


SCENARIOS = [scenario_done_report_shape,scenario_submit_stop_by_words_not_by_type, scenario_domain_allowlist_learns_redirects_only,
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
             scenario_a_recaptcha_badge_is_not_a_wall, scenario_the_browser_is_at_home, scenario_a_report_of_a_wall_is_the_wall,
             scenario_a_virtual_display_means_a_headed_browser, scenario_word_lists_split_pay_from_submit,
             scenario_control_record_reads_the_scope, scenario_classification_is_by_evidence_not_label,
             scenario_the_gate_returns_a_question_with_the_whole_transaction, scenario_pay_words_are_a_wall_whatever_else,
             scenario_the_fallback_classifies_unfamiliar_labels_by_evidence, scenario_the_switch_off_restores_the_old_wall,
             scenario_the_approved_press_runs_once_only_when_everything_matches, scenario_the_approved_press_refuses_when_the_page_moved,
             scenario_the_outcome_lines_and_the_end_of_the_run,
             scenario_continued_resumes_unapproved_and_payment_after_the_press_keeps_the_attempt,
             scenario_an_approved_run_that_writes_submit_presses_through_the_same_match, scenario_the_approved_match_holes_are_closed,
             scenario_an_unasked_press_after_continued_rides_beside_the_approved_attempt,
             scenario_every_press_path_goes_through_the_gate, scenario_an_in_page_confirmation_is_caught_by_the_backstop,
             scenario_the_device_sequence_runs_ungated_until_book, scenario_the_re_review_holes_are_closed]

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
