"""Browse — a mission's browser, driven by Gemini Computer Use over Playwright.
Spec: docs/superpowers/specs/2026-10-10-browse-missions-design.md §1–2.

This module never pays; it books or submits only one approved press at a time (spec 2026-10-11). The guards below are code,
not prompt: a test holds each one. The paid key is read only through
model_pools.api_key_for_pool (pool 'cu').
"""
import hashlib
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
DEFAULT_CAPS = {'turns': 40, 'seconds': 600, 'captcha_attempts': 3}
W, H = 1440, 900
GOTO_TIMEOUT_MS = 45000
MEMORY_FLOOR_MB = 600
# Two word lists, two paths (spec 2026-10-11 §1). A submit word is a commitment a
# parent may approve; a pay word is money and no approval in this slice lifts it.
SUBMIT_WORDS = re.compile(r'\b(submit|book(ing)?|schedule now|confirm|reserve|send|apply|register|sign ?up|'
                          r'finish booking|complete booking|place (a |my |the )?request)\b', re.I)
PAY_WORDS = re.compile(r'\b(pay(ment)?|checkout|purchase|buy|order now|place (my |the |an )?order|charge|complete purchase)\b', re.I)
# A step word is the label of an intermediate step; it is evidence only in the
# fallback (an unfamiliar label over state asks; a step word there does not).
STEP_WORDS = re.compile(r'^\s*(next|continue|proceed|back|previous|step \d+)\b', re.I)
# Reading aid for the ledger only; never lets a control past the evidence.
NAVIGATION_WORDS = re.compile(r'\b(search|find|go|filter|sort|show|view|see|select|choose|close|cancel)\b', re.I)
# Commitment language in a control's scope: the shape of a review-and-commit page.
COMMIT_CONTEXT = re.compile(r'(by clicking|i agree|\bterms\b|authori[sz]e|you will be charged|\btotal\b|confirm your|review your)', re.I)
CONFIRMATION_MARKERS = re.compile(r'(confirmation (number|#|code)|has been (booked|scheduled|submitted|received)|we have received your|'
                                  r'thank you for your (request|booking|application|order|submission)|your appointment is)', re.I)
MONEY = re.compile(r'(\$\s?\d[\d,]*(?:\.\d{2})?|\d[\d,]*(?:\.\d{2})?\s?(?:USD|dollars))', re.I)
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
    "states only what the screen showed. End your report with one line: LEARNED: key=value; key=value. "
    "Never guess or invent a location, a name or any detail the family would have to supply: if the page "
    "needs one of the family's contact-card fields that you were not given, stop and end your report with "
    "one more line: NEED: field, field (fields: first_name, last_name, email, phone, street, apt, city, "
    "state, zip, preferred). When you were given a ZIP or city, type it and press Enter or the Find/Go "
    "button; never use a 'use my location' button, and never pick a suggested nearby place that is not the "
    "ZIP's own town. A result about 'the location detected' is not about the ZIP you were given: search by "
    "the ZIP before you report it. type_text_at clicks the box itself: no separate click first. If a "
    "human-verification check (a CAPTCHA, 'I'm not a robot') blocks you and you may not or cannot pass it, "
    "end your report with one more line: WALL: captcha."
)
WALL_LINE = re.compile(r'WALL:\s*captcha', re.I)
WALL_WORDS = re.compile(r"(captcha|not a robot|human[- ]verification|verify you are human).{0,120}"
                        r"(prevent|block|cannot|can't|could not|couldn't|unable|without completing|stopp)", re.I | re.S)
NEED_LINE = re.compile(r'NEED:\s*(.+)$', re.I | re.M)


def available() -> tuple:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False, 'no browser on this box (playwright is not installed)'
    try:
        with sync_playwright() as p:
            path = p.chromium.executable_path
        if (not path or not os.path.exists(path)) and not _system_chromium(path):
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


SYSTEM_CHROMIUM = ('chromium', 'chromium-browser', 'google-chrome', 'chrome')


# --- the network check (Missions drawer → Browser → "Check the network") ------
# Every browse connect on the HA VM timed out (2026-10-11) on an 8 Gbit link:
# that is DNS or a half-configured IPv6 inside the container, not bandwidth.
# This times each step apart so the drawer can say which, without a terminal.

NETCHECK_URLS = ('https://www.bodewell.com/', 'https://repair.geappliances.com/', 'https://cdn.playwright.dev/',
                 'https://generativelanguage.googleapis.com/')


def _ms(t0: float) -> int:
    return int((time.time() - t0) * 1000)


def _timed_dns(host: str, family) -> tuple:
    """(ms, addresses) for one address family; (None, []) when the lookup fails."""
    import socket
    t0 = time.time()
    try:
        infos = socket.getaddrinfo(host, 443, family, socket.SOCK_STREAM)
    except Exception:
        return None, []
    return _ms(t0), sorted({i[4][0] for i in infos})


def _net_verdict(r: dict) -> str:
    """One sentence a parent can act on, from the timings."""
    dns_any, dns4, c4, c6, get, status = (r.get('dns_any_ms'), r.get('dns_v4_ms'), r.get('connect_v4_ms'),
                                          r.get('connect_v6_ms'), r.get('get_ms'), r.get('status'))
    if dns_any is None and dns4 is None:
        return "DNS cannot resolve this host at all: the container's resolver is broken or the name is wrong."
    if dns4 is not None and dns4 > 2000 and (dns_any or 0) > 2000:
        return "DNS is slow both ways: the container's resolver (HA's DNS or the VM's upstream) is the holdup."
    if dns4 is not None and dns4 < 1000 and dns_any is not None and dns_any > 2000:
        return "The IPv6 (AAAA) lookup hangs while IPv4 is quick: IPv6 is half-configured on the VM. Disable IPv6 in HA Settings > System > Network, or pin the browser to IPv4."
    if c6 is not None and c6 > 5000 and c4 is not None and c4 < 1000:
        return "IPv6 connects hang while IPv4 is quick: IPv6 is half-configured on the VM. Disable IPv6 in HA Settings > System > Network, or pin the browser to IPv4."
    if c4 is None and dns4 is not None:
        return ("The name resolves but nothing connects on its port: the host does not serve HTTPS there (bodewell.com's "
                "apex does not; www. does) or a firewall blocks outbound HTTPS. A browse probes www. and http itself.")
    if get is None and status is None:
        return "The connect works but the page never answered: the site, or something between, is dropping the request."
    if (get or 0) > 5000:
        return "Connects are quick but the page is slow to answer: the site itself, or a proxy in the path."
    return "Fine: DNS, connects and the page all answered quickly."


def _pick_start(site: str, timeout_s: float = 4.0):
    """The URL a browse of `site` starts at: the first of https://site,
    https://www.site, http://site whose host accepts a connection. None when
    none does (the caller keeps the https guess and reports honestly)."""
    import socket
    from urllib.parse import urlsplit
    host_port = site.split('/')[0]
    host, _, port = host_port.partition(':')
    for scheme, h in (('https', host), ('https', 'www.' + host if not host.startswith('www.') else host), ('http', host)):
        p = int(port) if port else (443 if scheme == 'https' else 80)
        try:
            infos = socket.getaddrinfo(h, p, socket.AF_INET, socket.SOCK_STREAM)
        except Exception:
            continue
        if not infos:
            continue
        if _answers(infos[0][4][0], h, p, scheme == 'https', timeout_s):
            return f"{scheme}://{h}{':' + port if port else ''}"
    return None


def _answers(addr: str, host: str, port: int, tls: bool, timeout_s: float) -> bool:
    """A TCP connect, and for https a TLS handshake too: a host that accepts
    the socket but does not speak HTTPS on it is not an answer."""
    import socket
    import ssl
    try:
        with socket.create_connection((addr, port), timeout=timeout_s) as sock:
            if not tls:
                return True
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(sock, server_hostname=host):
                return True
    except Exception:
        return False


def network_check(urls=None, timeout_s: float = 20.0) -> list:
    """Per URL: DNS any/IPv4 timings, connect timings IPv4 and IPv6 (when an
    AAAA exists), a plain GET, and a verdict. Never raises; a failed step is
    None in its column."""
    import socket
    import urllib.request
    from urllib.parse import urlparse
    out = []
    for url in (urls or NETCHECK_URLS):
        host = urlparse(url).hostname or url
        row = {'url': url, 'host': host, 'dns_any_ms': None, 'dns_v4_ms': None, 'connect_v4_ms': None,
               'connect_v6_ms': None, 'get_ms': None, 'status': None, 'verdict': ''}
        row['dns_any_ms'], _ = _timed_dns(host, 0)
        row['dns_v4_ms'], v4 = _timed_dns(host, socket.AF_INET)
        _, v6 = _timed_dns(host, socket.AF_INET6)
        port = urlparse(url).port or (443 if url.startswith('https') else 80)
        if v4:
            row['connect_v4_ms'] = _timed_connect_port(v4[0], socket.AF_INET, port, timeout_s)
        if v6 and socket.has_ipv6:
            row['connect_v6_ms'] = _timed_connect_port(v6[0], socket.AF_INET6, port, timeout_s)
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Chauffeur netcheck'}, method='GET')
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                resp.read(2048)
                row['status'] = resp.status
            row['get_ms'] = _ms(t0)
        except Exception as e:
            code = getattr(e, 'code', None)
            if code:
                row['status'] = int(code)
                row['get_ms'] = _ms(t0)
        row['verdict'] = _net_verdict(row)
        out.append(row)
    return out


def _timed_connect_port(addr: str, family, port: int, timeout_s: float):
    import socket
    t0 = time.time()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout_s)
            sock.connect((addr, port) if family == socket.AF_INET else (addr, port, 0, 0))
    except Exception:
        return None
    return _ms(t0)


def _system_chromium(bundled_path: str):
    """The add-on image falls back to Debian's chromium when Playwright's own
    download fails at build time (its CDN timed out on the HA box). None when
    the bundled binary is there (Playwright's own is used) or nothing is."""
    import shutil
    if bundled_path and os.path.exists(bundled_path):
        return None
    for name in SYSTEM_CHROMIUM:
        found = shutil.which(name)
        if found:
            return found
    return None


def _home_coords():
    """The household's home as (lat, lon) from the home address, geocoded
    through the app's cache (services.bus does the same); None without one."""
    try:
        from services import bus
        return bus._home_coords()
    except Exception:
        return None


def _new_context(browser, settings: dict):
    """The browser is AT HOME: the household's geolocation and timezone, so a
    site's 'use my location' answers the family's town and a calendar shows
    the family's day. No home address: no location at all, never a guess."""
    opts = {'viewport': {'width': W, 'height': H}, 'locale': 'en-US'}
    home = _home_coords()
    if home:
        opts['geolocation'] = {'latitude': float(home[0]), 'longitude': float(home[1])}
        opts['permissions'] = ['geolocation']
    tz = (settings or {}).get('timezone') or ''
    if tz:
        opts['timezone_id'] = tz
    return browser.new_context(**opts)


def _headless() -> bool:
    """Headed on the add-on's virtual display (run.sh starts Xvfb and sets
    DISPLAY): an ordinary browser to a site's human check. Headless anywhere
    without a display (the dev box, a box without Xvfb)."""
    return not os.environ.get('DISPLAY')


def _launch(headless: bool = None):
    """Test seam: tests replace this to simulate a missing binary."""
    from playwright.sync_api import sync_playwright
    if headless is None:
        headless = _headless()
    pw = sync_playwright().start()
    try:
        system = _system_chromium(pw.chromium.executable_path)
        kw = {'headless': headless, 'args': [f'--window-size={W},{H}']}
        if system:
            kw['executable_path'] = system
        browser = pw.chromium.launch(**kw)
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
# Thinking per turn, bounded: turns ran 11-37 s of thinking on the device (2026-10-11).
THINK_BUDGET = 2048


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
        thinking_config=types.ThinkingConfig(include_thoughts=True, thinking_budget=THINK_BUDGET))
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


def _goto(page, url: str):
    """Open a page the way a person does: wait for it to be readable; if its
    scripts hang (bodewell.com on the device: 30 s and no DOMContentLoaded),
    settle for the document having arrived and look at what rendered."""
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=GOTO_TIMEOUT_MS)
    except Exception as e:
        if 'Timeout' not in str(e) and 'timeout' not in str(e):
            raise
        page.goto(url, wait_until='commit', timeout=GOTO_TIMEOUT_MS)
        page.wait_for_timeout(1500)


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


INTERSTITIAL_MARKERS = re.compile(r"(verify you are human|i'm not a robot|human verification|checking your browser|"
                                  r"just a moment|unusual traffic|are you a robot|complete the security check)", re.I)


def _has_captcha(scan: dict) -> bool:
    """A page that IS a human check: an interstitial whose body is little
    but the check. A reCAPTCHA badge, its legal line or an invisible anchor
    iframe on an ordinary form (most forms have them) is not a wall; whether
    a widget on a form blocks is for the model to say (require_confirmation
    with CAPTCHA in its explanation), never for the page text."""
    text = ' '.join((scan.get('text') or '').split())
    return len(text) < 1200 and bool(INTERSTITIAL_MARKERS.search(text))


def _is_denied(scan: dict) -> bool:
    return bool(DENIED_MARKERS.search((scan.get('text') or '')[:600]))


def _under_click(page, x, y) -> dict:
    return page.evaluate("""([x, y]) => {
        const el = document.elementFromPoint(x, y); if (!el) return {text: '', type: '', tag: ''};
        const b = el.closest('button, input[type=submit], input[type=button], a, [role=button]') || el;
        return { text: ((b.innerText || b.value || b.getAttribute('aria-label') || '')).trim().slice(0, 120), type: (b.getAttribute('type') || ''), tag: b.tagName };
    }""", [x, y])


_CONTROL_JS = """
(target) => {
  const label = (el) => ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '')).replace(/\\s+/g, ' ').trim().slice(0, 120);
  const resolve = (el) => {
    if (!el) return null;
    if (el.tagName === 'IFRAME') return {iframe: true, el};
    const b = el.closest('button, input[type=submit], input[type=button], a, [role=button]');
    return b ? {iframe: false, el: b} : null;
  };
  const r = resolve(target);
  if (!r) return null;
  if (r.iframe) return {text: '', type: '', tag: 'IFRAME', disabled: false, iframe: true, sole_submit: false, only_button: false,
                        last_button: false, is_submit_control: false, state: {fields: {}, selected: [], text: '', text_sha: '', prices: []}};
  const b = r.el;
  const form = b.form || b.closest('form');
  const scope = form || b.closest('dialog, [role=dialog], [role=form], [role=group], main, section, article') || document.body;
  const buttons = [...scope.querySelectorAll('button, input[type=submit], input[type=button], [role=button]')].filter(x => !x.disabled);
  const submits = form ? [...form.querySelectorAll('button:not([type=button]):not([type=reset]), input[type=submit]')] : [];
  const fields = {};
  scope.querySelectorAll('input, textarea, select').forEach(i => {
    const t = (i.type || 'text').toLowerCase();
    if (['hidden', 'submit', 'button', 'checkbox', 'radio', 'password', 'reset', 'file', 'image'].includes(t)) return;
    const ac = (i.getAttribute('autocomplete') || '') + ' ' + (i.name || '') + ' ' + (i.placeholder || '');
    if (/cc-|card ?number|cvc|cvv|expir/i.test(ac)) return;
    if (t === 'select-one' || t === 'select-multiple' || i.tagName === 'SELECT') return;
    fields[i.name || i.id || ('field' + Object.keys(fields).length)] = i.value || '';
  });
  const selected = [];
  scope.querySelectorAll('input:checked, option:checked, [aria-checked="true"], [aria-selected="true"], [aria-pressed="true"]').forEach(x => {
    let t = '';
    if (x.tagName === 'OPTION') t = x.label || x.text;
    else if (x.tagName === 'INPUT') { const l = x.closest('label') || (x.id && document.querySelector(`label[for="${x.id}"]`)); t = l ? l.innerText : (x.value || ''); }
    else t = x.innerText || x.getAttribute('aria-label') || '';
    t = (t || '').replace(/\\s+/g, ' ').trim(); if (t) selected.push(t);
  });
  const text = (scope.innerText || '').replace(/\\s+/g, ' ').trim();
  const prices = (text.match(/(\\$\\s?\\d[\\d,]*(?:\\.\\d{2})?|\\d[\\d,]*(?:\\.\\d{2})?\\s?(?:USD|dollars))/gi) || []);
  return ({
    text: label(b), type: (b.getAttribute('type') || ''), tag: b.tagName, disabled: !!b.disabled, iframe: false,
    is_submit_control: !!form && (submits.includes(b) || (buttons.length === 1 && buttons[0] === b)),
    sole_submit: !!form && submits.length === 1 && submits[0] === b,
    only_button: buttons.length === 1 && buttons[0] === b,
    last_button: buttons.length > 0 && buttons.length <= 3 && buttons[buttons.length - 1] === b,
    state: {fields, selected, text, text_sha: '', prices},
  });
}
"""


def _unreadable_control() -> dict:
    """A control that could not be read: unclassifiable like an iframe, and
    never None (None means the page showed nothing pressable)."""
    return {'error': True, 'text': '', 'type': '', 'tag': '', 'disabled': False, 'iframe': False, 'sole_submit': False,
            'only_button': False, 'last_button': False, 'is_submit_control': False,
            'state': {'fields': {}, 'selected': [], 'text': '', 'text_sha': '', 'prices': []}}


def _read_control(page, h):
    """Evaluate the control reader on a handle. text_sha is computed here (no
    crypto.subtle: it is missing on plain-http pages). One retry after a short
    wait; a second failure is an `error` record, never None."""
    c = None
    for attempt in (1, 2):
        try:
            c = page.evaluate(_CONTROL_JS, h)
            break
        except Exception as e:
            if attempt == 1:
                try:
                    page.wait_for_timeout(300)
                except Exception:
                    pass
                continue
            logger.warning(f"[browse] control read failed: {e}")
            return _unreadable_control()
    if not c:
        try:
            h.dispose()
        except Exception:
            pass
        return None
    st = c.get('state') or {}
    st['text_sha'] = hashlib.sha256((st.get('text') or '').encode('utf-8')).hexdigest()
    c['state'] = st
    c['handle'] = h
    return c


def _control_at(page, x, y):
    """The control under a point and the state of its scope (spec §1), or
    None when nothing pressable is there. `x, y` are page pixels."""
    try:
        h = page.evaluate_handle("([x, y]) => document.elementFromPoint(x, y)", [x, y])
    except Exception as e:
        logger.warning(f"[browse] control read failed: {e}")
        return _unreadable_control()
    return _read_control(page, h)


def _focused_control(page):
    """What Space or Enter on a focused button would press: the focused element
    itself when it is a control; for Enter inside a form, the form's default
    submit control (as `_enter_target`, but the whole record)."""
    try:
        h = page.evaluate_handle("""() => {
            const el = document.activeElement; if (!el) return null;
            if (el.matches('button, input[type=submit], input[type=button], [role=button]')) return el;
            const f = el.form; if (!f) return null;
            return f.querySelector('button:not([type=button]):not([type=reset]), input[type=submit]');
        }""")
    except Exception as e:
        logger.warning(f"[browse] control read failed: {e}")
        return _unreadable_control()
    return _read_control(page, h)


def _control_by_text(page, text: str):
    """The model's SUBMIT: <text> resolved to a control: exact after whitespace
    collapsing, else the one control whose text contains it. None when none or many."""
    want = ' '.join((text or '').split()).lower()
    if not want:
        return None
    try:
        h = page.evaluate_handle("""(want) => {
            const all = [...document.querySelectorAll('button, input[type=submit], input[type=button], a, [role=button]')].filter(b => !b.disabled);
            const lab = (b) => ((b.innerText || b.value || b.getAttribute('aria-label') || b.getAttribute('title') || '')).replace(/\s+/g, ' ').trim().toLowerCase();
            const exact = all.filter(b => lab(b) === want); if (exact.length === 1) return exact[0];
            const part = all.filter(b => lab(b).includes(want)); return part.length === 1 ? part[0] : null;
        }""", want)
    except Exception as e:
        logger.warning(f"[browse] control read failed: {e}")
        return _unreadable_control()
    return _read_control(page, h)


def _snapshot_of(control: dict) -> dict:
    return control.get('state') or {'fields': {}, 'selected': [], 'text': '', 'text_sha': '', 'prices': []}


def _display(text: str) -> str:
    return (text or '')[:300]


def _is_confirmation(scan: dict) -> bool:
    return bool(CONFIRMATION_MARKERS.search((scan.get('text') or '')[:4000]))


def _classify(control, intent: str) -> str:
    """'pay', 'submit' or 'run' for one press (spec §1, evidence of a final
    action). Submitting a form is not by itself a commitment."""
    intent = intent or ''
    if PAY_WORDS.search(intent):
        return 'pay'
    if control and not control.get('iframe') and not control.get('disabled') and not control.get('error'):
        label = control.get('text') or ''
        if PAY_WORDS.search(label):
            return 'pay'
        if SUBMIT_WORDS.search(label) or SUBMIT_WORDS.search(intent):
            return 'submit'
        st = control.get('state') or {}
        final_pos = control.get('sole_submit') or control.get('only_button') or control.get('last_button')
        has_state = bool(st.get('fields') or st.get('selected'))
        if (st.get('prices') or COMMIT_CONTEXT.search(st.get('text') or '')) and final_pos:
            return 'submit'
        if not STEP_WORDS.search(label) and (control.get('sole_submit') or control.get('only_button')) and has_state:
            return 'submit'
        return 'run'
    # No control resolved (nothing under the point, a disabled control, an iframe): the intent is the remaining check.
    if SUBMIT_WORDS.search(intent):
        return 'submit'
    return 'run'


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
            _goto(page, args['url'])
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


def _needed(text: str) -> list:
    """The model's NEED: line, as contact-card field names, in its order."""
    m = NEED_LINE.search(text or '')
    if not m:
        return []
    out = []
    for part in re.split(r'[,\s]+', m.group(1).lower()):
        f = part.strip('.;:')
        if f in CONTACT_FIELDS and f not in out:
            out.append(f)
    return out


def _field_at(page, x, y):
    """The contact-card field a text box under the point stands for (by its
    label, name, placeholder or autocomplete), or None. Typing anything into
    such a box without that field released is a guess, and a guess is a
    release question, not an action."""
    try:
        label = page.evaluate("""([x, y]) => {
            const el = document.elementFromPoint(x, y); if (!el) return '';
            const i = el.closest('input, textarea, select') || (el.tagName === 'LABEL' && el.control) || null;
            if (!i || (i.type && ['hidden', 'submit', 'button', 'checkbox', 'radio'].includes(i.type))) return '';
            const parts = [];
            if (i.id) { const l = document.querySelector(`label[for="${i.id}"]`); if (l) parts.push(l.innerText); }
            const p = i.closest('label'); if (p) parts.push(p.innerText);
            parts.push(i.name || '', i.placeholder || '', i.getAttribute('aria-label') || '', i.getAttribute('autocomplete') || '');
            return parts.join(' ');
        }""", [x, y]) or ''
    except Exception:
        return None
    for name, rx in CONTACT_LABELS.items():
        if rx.search(label):
            return name
    return None


def _coarse(v):
    try:
        return int(float(v) // 20)
    except Exception:
        return None


def _action_words(page, name: str, args: dict) -> str:
    """One line a person can read on the transcript. A type names the field
    or the length, never the text (it may be a released value)."""
    try:
        if name.startswith('click') or name.startswith('double'):
            el = _under_click(page, *_px(args.get('x', 0), args.get('y', 0))) if 'x' in args else {}
            what = (el.get('text') or '').strip().replace('\n', ' ')[:40]
            return f"{'double-click' if 'double' in name else 'click'} ({args.get('x')},{args.get('y')})" + (f" '{what}'" if what else '')
        if name in ('type_text_at', 'type'):
            field = _field_at(page, *_px(args['x'], args['y'])) if 'x' in args else None
            n = len(str(args.get('text') or ''))
            return f"type into {field or 'a box'} ({n} chars)" + (' + Enter' if args.get('press_enter') else '')
        if name in ('navigate', 'open_web_browser'):
            return f"navigate {str(args.get('url') or '')[:80]}"
        if name.startswith('scroll'):
            return f"scroll {args.get('direction', 'down')}"
        if name in ('key_combination', 'press_key', 'hotkey'):
            k = args.get('keys') or args.get('key') or ''
            return 'press ' + ('+'.join(k) if isinstance(k, list) else str(k))
        if name in ('wait_5_seconds', 'wait'):
            return 'wait'
        return name or 'action'
    except Exception:
        return name or 'action'


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
              'turns': 0, 'actions': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0.0, 'screenshots': [], 'filled': {},
              'turns_log': [], 'browser': 'headless' if _headless() else 'headed'}

    def finish(outcome, text):
        report['outcome'] = outcome
        report['text'] = text
        report['seconds'] = round(time.time() - t0, 1)
        if outcome != 'done':
            report['turns_log'].append({'turn': report['turns'], 'action': f"{outcome}: {str(text)[:80]}",
                                        'url': report.get('stopped_at') or '', 'model_ms': 0, 'act_ms': 0})
        return report

    from services import model_pools
    if not model_pools.api_key_for_pool('cu', settings):
        return finish('refused', 'no paid key: a browse bills the paid key only')
    mem = free_memory_mb()
    if mem is not None and mem < MEMORY_FLOOR_MB:
        return finish('refused', f'not enough room for a browser right now ({mem} MB free)')
    try:
        pw, browser = _launch()
    except Exception as e:
        return finish('refused', f'no browser on this box ({str(e)[:100]})')
    allowed = {_domain(f'http://{site}' if '://' not in site else site)}
    start = start_url or (site if '://' in site else (_pick_start(site) or f'https://{site}'))
    captcha_attempts = 0
    strikes = 0
    last_sig, repeats = None, 0

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
        ctx = _new_context(browser, settings)
        page = ctx.new_page()
        page.on('response', learn_redirect)
        _goto(page, start)
        page.wait_for_timeout(800)
        shot = page.screenshot(type='png')
        report['screenshots'].append(os.path.join(out_dir, 'turn_00.png'))
        with open(report['screenshots'][-1], 'wb') as f:
            f.write(shot)
        given = ', '.join(f"{k}={v}" for k, v in released.items()) or 'nothing'
        holds = ', '.join(f for f in CONTACT_FIELDS if f in card)
        prompt = (f"GOAL: {goal}\nSITE: {site}\nValues you may enter: {given}.\n"
                  + (f"The family's contact card holds these fields (values come only when released): {holds}.\n" if holds
                     else "The family's contact card holds nothing yet; ask with NEED: for any field the page wants.\n")
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
            t_model = time.time()
            step = _model_step(contents, settings)
            model_ms = _ms(t_model)
            report['turns'] = turn
            ti, to = step.get('tokens') or (0, 0)
            report['tokens_in'] += int(ti)
            report['tokens_out'] += int(to)
            if step.get('content') is not None:
                contents.append(step['content'])
            calls = step.get('calls') or []
            if not calls:
                text = step.get('text') or ''
                report['turns_log'].append({'turn': turn, 'action': 'finish: ' + ' '.join(text.split())[:80], 'url': page.url,
                                            'model_ms': model_ms, 'act_ms': 0})
                report['learned'] = _learned(text)
                needed = [f for f in _needed(text) if f not in released]
                if needed:
                    report['wanted_fields'] = needed
                    return finish('needs_release', text.strip() or f"the page needs: {', '.join(needed)}")
                if WALL_LINE.search(text) or WALL_WORDS.search(text):
                    # The model met the check and stopped: that is the wall, and
                    # the person gets the page, not a 'done' the planner reads past.
                    return finish('captcha_failed', text.strip())
                return finish('done', text.strip() or 'finished with nothing to report')
            results = []
            for i_call, call in enumerate(calls):
                name, args = call.get('name') or '', dict(call.get('args') or {})
                intent = str(args.get('intent') or '')
                sd = args.get('safety_decision') or {}
                words = _action_words(page, name, args)
                line = {'turn': turn, 'action': words, 'url': page.url, 'model_ms': model_ms if i_call == 0 else 0, 'act_ms': 0}
                report['turns_log'].append(line)
                # The same action on the same unchanged page, a third time, is
                # a loop: refuse it and tell the model, instead of burning the turn.
                sig = (name, _coarse(args.get('x')), _coarse(args.get('y')), str(args.get('text') or '')[:40],
                       str(args.get('url') or ''), str(args.get('direction') or ''), page.url)
                if sig == last_sig:
                    repeats += 1
                else:
                    last_sig, repeats = sig, 0
                if repeats >= 2 and name not in ('wait_5_seconds', 'wait') and sd.get('decision') != 'require_confirmation':
                    # (A repeated CAPTCHA click is an attempt; its own cap counts it.)
                    line['action'] += ' (repeat, refused)'
                    results.append((name, args, {'error': 'you already did exactly that twice and the page did not change; '
                                                          'try something else: another element, a scroll, or report what you see'}))
                    continue
                if sd.get('decision') == 'require_confirmation':
                    if CAPTCHA_MARKERS.search(str(sd.get('explanation') or '')):
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
                    if 'x' in args:
                        field = _field_at(page, *_px(args['x'], args['y']))
                        if field and field not in released:
                            report['wanted_fields'] = [field]
                            return finish('needs_release', f"the page's {field} box wants the family's {field}; nothing was typed")
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
                t_act = time.time()
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
                line['act_ms'] = _ms(t_act)
                line['url'] = page.url
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
