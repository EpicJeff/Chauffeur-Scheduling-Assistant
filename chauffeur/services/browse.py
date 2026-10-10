"""Browse — a mission's browser, driven by Gemini Computer Use over Playwright.
Spec: docs/superpowers/specs/2026-10-10-browse-missions-design.md §1–2.

This module never books, pays, submits or sends. The guards below are code,
not prompt: a test holds each one. The paid key is read only through
model_pools.api_key_for_pool (pool 'cu').
"""
import logging
import os
import re
import time
from typing import Optional
from urllib.parse import urlparse

from services import storage

logger = logging.getLogger(__name__)

CONTACT_FIELDS = ('first_name', 'last_name', 'email', 'phone', 'street', 'apt', 'city', 'state', 'zip', 'preferred')


def contact_card(settings: Optional[dict] = None) -> dict:
    """The family's own contact details, filled once in the Missions drawer;
    only the non-empty fields. Never invented, never inferred."""
    s = settings if settings is not None else (storage.get_settings() or {})
    out = {}
    for f in CONTACT_FIELDS:
        v = (s.get(f'contact_{f}') or '')
        v = str(v).strip()
        if v:
            out[f] = v
    return out


# --- the runner -------------------------------------------------------------------

OUTCOMES = ('done', 'needs_release', 'captcha_failed', 'blocked', 'refused', 'capped', 'error')
DEFAULT_CAPS = {'turns': 40, 'seconds': 300, 'captcha_attempts': 3}
W, H = 1440, 900
MEMORY_FLOOR_MB = 600
STOP_WORDS = re.compile(r'\b(submit|book(ing)?|schedule now|confirm|place (my |the )?order|pay(ment)?|checkout|purchase|reserve|finish booking|complete booking)\b', re.I)
PAYMENT_PATTERNS = re.compile(r'(cc-number|cc-csc|cc-exp|card ?number|cvc|cvv|expir)', re.I)
CAPTCHA_MARKERS = re.compile(r'(captcha|verify you are human|i\'m not a robot|human verification)', re.I)
DENIED_MARKERS = re.compile(r'(access denied|unusual traffic|automated queries|blocked)', re.I)
# Labels a form uses for the contact card's fields → the card's field names.
CONTACT_LABELS = {
    'first_name': re.compile(r'first ?name', re.I), 'last_name': re.compile(r'last ?name|surname', re.I),
    'email': re.compile(r'e-?mail', re.I), 'phone': re.compile(r'phone|mobile|cell', re.I),
    'street': re.compile(r'street|address line|address\b', re.I), 'apt': re.compile(r'apt|suite|unit', re.I),
    'city': re.compile(r'\bcity\b|town', re.I), 'state': re.compile(r'\bstate\b|province', re.I),
    'zip': re.compile(r'zip|postal', re.I), 'preferred': re.compile(r'preferred (contact|communication)', re.I),
}
EMAIL_SHAPE = re.compile(r'[^@\s]+@[^@\s]+\.[a-z]{2,}', re.I)
PHONE_SHAPE = re.compile(r'(\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}')

RUNNER_SYSTEM = (
    "You are driving a browser for one family on ONE site to learn something. You may enter only the values "
    "you were given below; never invent a name, address, phone or email. Never click anything that submits, "
    "books, confirms, pays or orders. Stop and report when a form wants a value you were not given, when a "
    "payment field appears, when a human-verification check appears (unless told you may try, and then at "
    "most the allowed attempts), when the page says access denied, or when the goal is met. Your report "
    "states only what the screen showed. End your report with one line: LEARNED: key=value; key=value."
)


def available() -> tuple:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False, 'no browser on this box (playwright is not installed)'
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
        if not path or not os.path.exists(path):
            return False, 'no browser on this box (Chromium is not installed)'
    except Exception as e:
        return False, f'no browser on this box ({str(e)[:80]})'
    return True, ''


def free_memory_mb():
    try:
        with open('/proc/meminfo', encoding='utf-8') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except Exception:
        return None
    return None


def _launch(headless: bool = True):
    """Test seam: tests replace this to simulate a missing binary."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
    except Exception:
        pw.stop()
        raise
    return pw, browser


# Two-label public suffixes under which a site keeps three labels
# (bbc.co.uk is a site; co.uk is not). Enough for the family's world.
PUBLIC_SUFFIXES = frozenset({'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'com.au', 'net.au', 'org.au', 'co.nz', 'co.jp',
                             'com.br', 'co.za', 'com.mx', 'co.in', 'com.sg', 'co.kr', 'com.ar', 'com.tr'})


def _domain(url: str) -> str:
    """The registrable domain the allowlist works in: the last two labels, or
    three under a known public suffix; an IP or a bare host stays itself."""
    host = (urlparse(url).hostname or '').lower()
    parts = host.split('.')
    if len(parts) < 2 or host.replace('.', '').isdigit():
        return host
    if len(parts) >= 3 and '.'.join(parts[-2:]) in PUBLIC_SUFFIXES:
        return '.'.join(parts[-3:])
    return '.'.join(parts[-2:])


MODEL = 'gemini-3.8-flash'


def _client(api_key: str):
    """Test seam: tests hand back a fake client."""
    from google import genai
    from google.genai import types
    # A hung request must not hold the runner's thread past the mission's reclaim.
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=120_000))


def _to_types(contents: list):
    from google.genai import types
    out = []
    for c in contents:
        if hasattr(c, 'parts') and not isinstance(c, dict):
            out.append(c)
            continue
        if 'parts' in c:
            parts = []
            for p in c['parts']:
                if 'text' in p:
                    parts.append(types.Part(text=p['text']))
                elif 'image' in p:
                    parts.append(types.Part.from_bytes(data=p['image'], mime_type='image/png'))
            out.append(types.Content(role=c.get('role', 'user'), parts=parts))
        elif 'function_responses' in c:
            parts = [types.Part(function_response=types.FunctionResponse(
                name=n, response=r,
                parts=[types.FunctionResponsePart(inline_data=types.FunctionResponseBlob(mime_type='image/png', data=shot))]))
                for n, r, shot in c['function_responses']]
            out.append(types.Content(role='user', parts=parts))
    return out


def _model_step_live(contents, settings):
    """One computer-use turn on gemini-3.8-flash (pool cu, paid key)."""
    from google.genai import types
    from services import model_pools
    key = model_pools.api_key_for_pool('cu', settings)
    client = _client(key)
    config = types.GenerateContentConfig(
        temperature=1, top_p=0.95, max_output_tokens=8192,
        tools=[types.Tool(computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER))],
        thinking_config=types.ThinkingConfig(include_thoughts=True))
    typed = _to_types(contents)
    resp = client.models.generate_content(model=MODEL, contents=typed, config=config)
    um = resp.usage_metadata
    tokens = (int(getattr(um, 'prompt_token_count', 0) or 0),
              int(getattr(um, 'candidates_token_count', 0) or 0) + int(getattr(um, 'thoughts_token_count', 0) or 0)) if um else (0, 0)
    cand = resp.candidates[0] if resp.candidates else None
    parts = (cand.content.parts if cand and cand.content else None) or []
    calls = [{'name': p.function_call.name, 'args': dict(p.function_call.args or {})} for p in parts if p.function_call]
    text = ' '.join(p.text for p in parts if p.text and not getattr(p, 'thought', False))
    # The runner holds the neutral list; the model's Content is appended as-is
    # (it is already a types.Content), and _to_types passes it through.
    return {'calls': calls, 'text': text, 'content': cand.content if cand else None, 'tokens': tokens}


_model_step = _model_step_live


def _px(x, y):
    return int(x) * W / 1000, int(y) * H / 1000


def _scan(page) -> dict:
    """What the page wants and warns about: required contact fields (by label
    text or input name), payment fields, human checks, access denied."""
    return page.evaluate("""() => {
        const labelFor = (el) => {
            const parts = [];
            if (el.id) { const l = document.querySelector(`label[for="${el.id}"]`); if (l) parts.push(l.innerText); }
            const p = el.closest('label'); if (p) parts.push(p.innerText);
            parts.push(el.name || '', el.placeholder || '', el.getAttribute('aria-label') || '', el.getAttribute('autocomplete') || '');
            return parts.join(' ');
        };
        const inputs = [...document.querySelectorAll('input, select, textarea')].filter(i => i.type !== 'hidden');
        const fields = inputs.map(i => ({ label: labelFor(i), required: !!(i.required || i.getAttribute('aria-required') === 'true' || /\\*/.test(labelFor(i))), type: i.type || '' }));
        const text = (document.body && document.body.innerText || '').slice(0, 4000);
        const frames = [...document.querySelectorAll('iframe')].map(f => (f.src || '') + ' ' + (f.title || ''));
        return { fields, text, frames };
    }""")


def _wanted(scan: dict, released: dict, card: dict) -> list:
    out = []
    for f in scan.get('fields') or []:
        if not f.get('required'):
            continue
        for name, rx in CONTACT_LABELS.items():
            if rx.search(f.get('label') or '') and name not in released and name not in out:
                out.append(name)
    return out


def _is_payment(scan: dict) -> bool:
    return any(PAYMENT_PATTERNS.search(f.get('label') or '') for f in scan.get('fields') or [])


def _has_captcha(scan: dict) -> bool:
    return bool(CAPTCHA_MARKERS.search(scan.get('text') or '') or any(CAPTCHA_MARKERS.search(fr) for fr in scan.get('frames') or []))


def _is_denied(scan: dict) -> bool:
    return bool(DENIED_MARKERS.search((scan.get('text') or '')[:600]))


def _under_click(page, x, y) -> dict:
    return page.evaluate("""([x, y]) => {
        const el = document.elementFromPoint(x, y); if (!el) return {text: '', type: '', tag: ''};
        const b = el.closest('button, input[type=submit], input[type=button], a, [role=button]') || el;
        return { text: ((b.innerText || b.value || b.getAttribute('aria-label') || '')).trim().slice(0, 120), type: (b.getAttribute('type') || ''), tag: b.tagName };
    }""", [x, y])


def _enter_target(page) -> str:
    """What Enter would press: the focused element's form's default submit
    control, by its text. '' when the focus is outside a form (an address
    bar, a search box with no form, nothing focused)."""
    try:
        return page.evaluate("""() => {
            const el = document.activeElement; const f = el && el.form; if (!f) return '';
            const b = f.querySelector('button:not([type=button]):not([type=reset]), input[type=submit]');
            return b ? ((b.innerText || b.value || b.getAttribute('aria-label') || '')).trim().slice(0, 120) : '';
        }""") or ''
    except Exception:
        return ''


def _wants_enter(name: str, args: dict) -> bool:
    if name in ('type_text_at', 'type'):
        return bool(args.get('press_enter'))
    if name in ('key_combination', 'press_key', 'hotkey'):
        k = args.get('keys') or args.get('key') or ''
        keys = k if isinstance(k, list) else [k]
        return any(str(x).strip().lower() in ('enter', 'return') for x in keys)
    return False


def _contains_value(text: str, value: str) -> bool:
    """A card value typed as a whole word (or, for a value under three
    characters such as an apartment number or a state code, typed on its
    own). Substring containment refused 'Cafe CDT805P2N3S1' as the apartment
    '2' and 'cancel' as the state 'NC'."""
    t = (text or '').strip().lower()
    v = (value or '').strip().lower()
    if not t or not v:
        return False
    if len(v) < 3:
        return t == v
    return re.search(r'(?<!\w)' + re.escape(v) + r'(?!\w)', t) is not None


def _personal_violation(text: str, released: dict, card: dict):
    """A typed string that is a contact-card value not released, or any email
    or phone shape when none was released. Returns the offending field name."""
    t = (text or '').strip()
    if not t:
        return None
    for name, value in card.items():
        if _contains_value(t, value) and name not in released:
            return name
    if EMAIL_SHAPE.search(t) and 'email' not in released:
        return 'email'
    if PHONE_SHAPE.search(t) and len(re.sub(r'\D', '', t)) >= 10 and 'phone' not in released:
        return 'phone'
    return None


def _act(page, name, args):
    if name in ('click_at', 'click', 'double_click_at', 'double_click'):
        x, y = _px(args['x'], args['y'])
        page.mouse.click(x, y, click_count=2 if 'double' in name else 1)
    elif name in ('type_text_at', 'type'):
        if 'x' in args:
            x, y = _px(args['x'], args['y'])
            page.mouse.click(x, y)
            page.wait_for_timeout(150)
            if args.get('clear_before_typing', True):
                page.keyboard.press('Control+A')
                page.keyboard.press('Backspace')
        page.keyboard.type(str(args.get('text', '')))
        if args.get('press_enter'):
            # The loop already asked what Enter would press (the never-submit guard).
            page.keyboard.press('Enter')
    elif name in ('navigate', 'open_web_browser'):
        if args.get('url'):
            page.goto(args['url'], wait_until='domcontentloaded', timeout=30000)
    elif name in ('scroll_document', 'scroll_at', 'scroll'):
        mag = int(args.get('magnitude') or args.get('magnitude_in_pixels') or 600)
        d = args.get('direction', 'down')
        if 'x' in args:
            x, y = _px(args['x'], args['y'])
            page.mouse.move(x, y)
        dx, dy = {'down': (0, mag), 'up': (0, -mag), 'right': (mag, 0), 'left': (-mag, 0)}.get(d, (0, mag))
        page.mouse.wheel(dx, dy)
    elif name == 'go_back':
        page.go_back(wait_until='domcontentloaded')
    elif name == 'go_forward':
        page.go_forward(wait_until='domcontentloaded')
    elif name in ('wait_5_seconds', 'wait'):
        page.wait_for_timeout(2000)
    elif name in ('key_combination', 'press_key', 'hotkey'):
        k = args.get('keys') or args.get('key') or ''
        page.keyboard.press('+'.join(k) if isinstance(k, list) else str(k))
    elif name == 'hover_at':
        x, y = _px(args['x'], args['y'])
        page.mouse.move(x, y)
    elif name == 'drag_and_drop':
        x1, y1 = _px(args['x'], args['y'])
        x2, y2 = _px(args['destination_x'], args['destination_y'])
        page.mouse.move(x1, y1)
        page.mouse.down()
        page.mouse.move(x2, y2)
        page.mouse.up()
    page.wait_for_timeout(900)


def _learned(text: str) -> dict:
    m = re.search(r'LEARNED:\s*(.+)$', text or '', re.I | re.M)
    out = {}
    if m:
        for part in m.group(1).split(';'):
            if '=' in part:
                k, v = part.split('=', 1)
                out[k.strip()[:40]] = v.strip()[:200]
    return out


def run(goal: str, site: str, released: dict, consent: dict, caps: dict = None, start_url: str = None,
        out_dir: str = None) -> dict:
    """Drive one goal on one site. Returns the report (spec §2). Never raises."""
    caps = {**DEFAULT_CAPS, **(caps or {})}
    settings = storage.get_settings() or {}
    card = contact_card(settings)
    released = {k: v for k, v in (released or {}).items() if v}
    consent = dict(consent or {})
    consent.setdefault('captcha', bool(settings.get('missions_captcha_attempts')))
    out_dir = out_dir or os.path.join(os.path.dirname(storage.DB_PATH), 'browse', 'adhoc')
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    report = {'outcome': 'error', 'text': '', 'learned': {}, 'stopped_at': start_url or '', 'wanted_fields': [],
              'turns': 0, 'actions': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0.0, 'screenshots': [], 'filled': {}}

    def finish(outcome, text):
        report['outcome'] = outcome
        report['text'] = text
        report['seconds'] = round(time.time() - t0, 1)
        return report

    from services import model_pools
    if not model_pools.api_key_for_pool('cu', settings):
        return finish('refused', 'no paid key: a browse bills the paid key only')
    mem = free_memory_mb()
    if mem is not None and mem < MEMORY_FLOOR_MB:
        return finish('refused', f'not enough room for a browser right now ({mem} MB free)')
    try:
        pw, browser = _launch(headless=True)
    except Exception as e:
        return finish('refused', f'no browser on this box ({str(e)[:100]})')
    allowed = {_domain(f'http://{site}' if '://' not in site else site)}
    start = start_url or (site if '://' in site else f'https://{site}')
    captcha_attempts = 0
    strikes = 0

    def learn_redirect(r):
        # A server redirect FROM an allowed domain teaches its target
        # (geappliances.com → bodewell.com); a link the model clicks does not.
        try:
            # Only the page itself moving: a beacon, a script or an iframe
            # that redirects teaches nothing.
            if not r.request.is_navigation_request() or r.frame != page.main_frame:
                return
            loc = r.headers.get('location', '')
            if 300 <= r.status < 400 and loc.startswith('http') and _domain(r.url) in allowed:
                allowed.add(_domain(loc))
        except Exception:
            pass

    def page_checks(scan):
        """Payment, access denied, a form wanting unreleased fields, a check
        with consent off: each ends the run. None when the page is fine."""
        report['stopped_at'] = page.url
        if _is_payment(scan):
            return finish('blocked', f'this part needs a payment card; do it yourself here: {page.url}')
        if _is_denied(scan):
            return finish('captcha_failed', f'the site answered access denied at {page.url}')
        wanted = _wanted(scan, released, card)
        if wanted:
            report['wanted_fields'] = wanted
            return finish('needs_release', f"the form at {page.url} wants: {', '.join(wanted)}")
        if _has_captcha(scan) and not consent.get('captcha'):
            return finish('captcha_failed', f'a human-verification check at {page.url}; not attempted (consent is off)')
        return None

    try:
        ctx = browser.new_context(viewport={'width': W, 'height': H}, locale='en-US')
        page = ctx.new_page()
        page.on('response', learn_redirect)
        page.goto(start, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(800)
        shot = page.screenshot(type='png')
        report['screenshots'].append(os.path.join(out_dir, 'turn_00.png'))
        with open(report['screenshots'][-1], 'wb') as f:
            f.write(shot)
        given = ', '.join(f"{k}={v}" for k, v in released.items()) or 'nothing'
        prompt = (f"GOAL: {goal}\nSITE: {site}\nValues you may enter: {given}.\n"
                  + ("You may attempt a human-verification check, at most the allowed attempts.\n" if consent.get('captcha') else
                     "Do NOT attempt any human-verification check; stop and report instead.\n"))
        contents = [{'role': 'user', 'parts': [{'text': RUNNER_SYSTEM + '\n\n' + prompt}, {'image': shot}]}]
        for turn in range(1, caps['turns'] + 1):
            if time.time() - t0 > caps['seconds']:
                return finish('capped', f"stopped after {caps['seconds']} s")
            # The page first: what it wants and warns about, before the model acts on it.
            scan = _scan(page)
            stop = page_checks(scan)
            if stop:
                return stop
            step = _model_step(contents, settings)
            report['turns'] = turn
            ti, to = step.get('tokens') or (0, 0)
            report['tokens_in'] += int(ti)
            report['tokens_out'] += int(to)
            if step.get('content') is not None:
                contents.append(step['content'])
            calls = step.get('calls') or []
            if not calls:
                text = step.get('text') or ''
                report['learned'] = _learned(text)
                return finish('done', text.strip() or 'finished with nothing to report')
            results = []
            for call in calls:
                name, args = call.get('name') or '', dict(call.get('args') or {})
                intent = str(args.get('intent') or '')
                sd = args.get('safety_decision') or {}
                if sd.get('decision') == 'require_confirmation':
                    if CAPTCHA_MARKERS.search(str(sd.get('explanation') or '')) or _has_captcha(scan):
                        if not consent.get('captcha'):
                            return finish('captcha_failed', f'a human-verification check at {page.url}; not attempted (consent is off)')
                        captcha_attempts += 1
                        if captcha_attempts > caps['captcha_attempts']:
                            return finish('captcha_failed', f"{caps['captcha_attempts']} attempts at the human-verification check failed at {page.url}")
                if name.startswith('click') and STOP_WORDS.search(intent):
                    return finish('blocked', f'would submit: the model meant to "{intent}"')
                if name.startswith('click') and 'x' in args:
                    x, y = _px(args['x'], args['y'])
                    el = _under_click(page, x, y)
                    if STOP_WORDS.search(el.get('text') or ''):
                        return finish('blocked', f'would submit: a "{el.get("text")}" button')
                if name in ('type_text_at', 'type'):
                    bad = _personal_violation(args.get('text'), released, card)
                    if bad:
                        report['wanted_fields'] = [bad]
                        return finish('needs_release', f'the model wanted to type a {bad} that was not released')
                    for k, v in released.items():
                        if _contains_value(str(args.get('text') or ''), v):
                            report['filled'][k] = v
                if name in ('navigate', 'open_web_browser') and args.get('url') and _domain(args['url']) not in allowed:
                    strikes += 1
                    if strikes > 1:
                        return finish('blocked', f'left the site: {args["url"]}')
                    results.append((name, args, {'error': 'that is another site; stay on ' + site}))
                    continue
                before = page.url
                enter = _wants_enter(name, args)
                if enter and name in ('type_text_at', 'type'):
                    # Type first (focus lands with the click), then ask what Enter would press.
                    try:
                        _act(page, name, {**args, 'press_enter': False})
                    except Exception as e:
                        pass
                    target = _enter_target(page)
                    if STOP_WORDS.search(target):
                        return finish('blocked', f'would submit: Enter would press "{target}"')
                    try:
                        page.keyboard.press('Enter')
                        page.wait_for_timeout(900)
                        res = {}
                    except Exception as e:
                        res = {'error': str(e)[:160]}
                else:
                    if enter:
                        target = _enter_target(page)
                        if STOP_WORDS.search(target):
                            return finish('blocked', f'would submit: Enter would press "{target}"')
                    try:
                        _act(page, name, args)
                        res = {}
                    except Exception as e:
                        res = {'error': str(e)[:160]}
                report['actions'] += 1
                if _domain(page.url) not in allowed:
                    strikes += 1
                    if strikes > 1:
                        return finish('blocked', f'left the site: {page.url}')
                    try:
                        page.go_back(wait_until='domcontentloaded')
                    except Exception:
                        page.goto(before, wait_until='domcontentloaded')
                    res = {'error': 'that led to another site; undone. Stay on ' + site}
                if sd:
                    res['safety_acknowledgement'] = 'true'
                if page.url != before:
                    # The call moved the page: the next call in this turn must
                    # not act on a payment page, a wall or an unreleased form.
                    scan = _scan(page)
                    stop = page_checks(scan)
                    if stop:
                        return stop
                shot = page.screenshot(type='png')
                p = os.path.join(out_dir, f'turn_{turn:02d}.png')
                with open(p, 'wb') as f:
                    f.write(shot)
                report['screenshots'].append(p)
                results.append((name, args, res))
            contents.append({'role': 'user', 'function_responses': [(n, {'url': page.url, **r}, shot) for n, a, r in results]})
        return finish('capped', f"stopped after {caps['turns']} turns")
    except Exception as e:
        logger.warning(f"[browse] run failed: {e}")
        return finish('error', str(e)[:200])
    finally:
        try:
            browser.close()
            pw.stop()
        except Exception:
            pass
