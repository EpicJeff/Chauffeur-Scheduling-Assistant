# Browse missions, build 2 — the browse step — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A mission can say `browse` and a separate runner drives headless Chromium with Gemini Computer Use on the paid key, under code-level guards, stopping for a per-site release of the family's contact card, attempting a CAPTCHA only with recorded consent and a cap, and handing the person the link when it cannot go on. Nothing is ever submitted, booked or paid.

**Architecture:** `services/browse.py` is the runner: one `run(goal, site, released, consent, caps, start_url)` call executes the Computer Use loop (`generate_content` + `types.ComputerUse`, the path the spike proved) over Playwright, applies the guards after every model action, scans each page for required contact fields, payment fields and human checks, and returns one report. `services/missions.py` gains the `browse` action: the step runs in its own thread while the mission sits in a new `browsing` status; the report becomes the step's result and the outcome maps to running / a `release` ask / a `handoff` ask. The release and hand-off are `ask` steps with names, so the existing waiting_user machinery, the answer box, the DM and the situation card all carry them; the situation card gains one verb, `release`. The household contact card and the two new switches live in the Missions drawer. Chromium ships in the add-on image.

**Tech Stack:** `google-genai` (`client.models.generate_content`, `types.Tool(computer_use=...)`), `playwright` (sync API, Chromium headless), FastAPI, TinyDB-over-SQLite, Alpine, scenario tests; the runner's tests drive real Playwright against pages served by a local `http.server` thread with a scripted fake model.

**Spec:** `docs/superpowers/specs/2026-10-10-browse-missions-design.md` §1, §2, §5 and Appendices A–B. Build 1 (mail, photo) precedes; build 3 (conversation) follows.

## Global Constraints

- Run from `E:\repositories\Chauffeur\chauffeur` with `..\venv\Scripts\python.exe`; tests with `HA_BASE_URL` unset. `pip install playwright google-genai` into the venv first (the dev box already has Chromium 1234 for Playwright).
- Gate for this build: `python tools/test.py browse missions settings_registry situation agent_v2_bridge tailwind_build` plus the live test of Task 7. Never the full sweep. `tests/test_browse_smoke_real.py` runs only with `CHF_BROWSE_SMOKE=1` and is never in the gate.
- The paid key is read only through `model_pools.api_key_for_pool` (`test_missions_pins` scans every service file for the key's name; `browse.py` must never name it). Pool `cu` bills the paid key; no free fallback.
- Never submit, book, pay, or type an unreleased personal value: these are code guards in `browse.py`, each with its own test, independent of the prompt.
- The mission step must never block the 30-second push beat: the runner runs in a daemon thread; the mission sits in `browsing` meanwhile.
- Screenshots are stored under the data dir (`browse/<mission_id>/`), served by a parent-gated route, never under the moments media root (the wall's screensaver draws from there).
- `python tools/build_tailwind.py` after any template class change.
- Every commit bumps `config.yaml` (continuing from build 1's last version +1, +1 per commit), message ends `(vX.Y.Z)`, push. Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Persisted prose is normal English.

## Review Focus

1. **A form whose "Next" button is `type=submit`** on a multi-step flow: it must pass (it is not a booking), while a button labelled "Book appointment" or "Confirm" must stop the run, whatever its type. Pinned in Task 2 (`scenario_submit_stop_by_words_not_by_type`).
2. **A site that redirects to a sibling domain** (geappliances.com → bodewell.com) must be allowed once learned; a click to a third domain is undone, then stopped. Pinned in Task 2 (`scenario_domain_allowlist_learns_redirects_only`).
3. **The model types an email that is not the family's** (invented): refused by the typing guard even though no release is involved. Pinned in Task 2 (`scenario_typing_guard_refuses_any_unreleased_personal_shape`).
4. **The runner thread dies** (exception, process restart) with the mission in `browsing`: the tick reclaims it after 10 minutes, records the loss, and the mission continues as `running`. Pinned in Task 4 (`scenario_a_lost_browse_is_reclaimed_by_the_tick`).
5. **Two approvals of the same release** (double tap, two parents): the browse resumes once. Pinned in Task 5 (`scenario_release_approved_twice_resumes_once`).

---

### Task 1: The household contact card, the consent switch, the browse cap

**Files:**
- Modify: `models/schemas.py` (Settings fields), `services/settings_registry.py`, `templates/components/missions_page.html`
- Create: `services/browse.py` (only `contact_card`, `CONTACT_FIELDS` for now; the runner comes in Task 2)
- Test: `tests/test_browse_settings.py` (new)

**Interfaces:**
- Produces: `browse.CONTACT_FIELDS = ('first_name','last_name','email','phone','street','apt','city','state','zip','preferred')`; `browse.contact_card(settings=None) -> dict` of non-empty values keyed by field; settings keys `contact_<field>`, `missions_captcha_attempts` (bool, default False), `mission_cap_browse_turns` (int, default 400).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_browse_settings.py
"""The household contact card and the two browse switches: schema, registry,
drawer. Spec 2026-10-10 browse missions §1, §5."""
from harness import check  # noqa: F401
from services import storage, browse, settings_registry
from models.schemas import Settings


def scenario_contact_card_reads_only_filled_fields():
    storage.get_settings = lambda: {'contact_first_name': 'Jeff', 'contact_last_name': 'Wilson',
                                    'contact_email': 'ffejnosliw@gmail.com', 'contact_phone': '919-327-7497',
                                    'contact_street': '', 'contact_zip': '27519'}
    card = browse.contact_card()
    check(card == {'first_name': 'Jeff', 'last_name': 'Wilson', 'email': 'ffejnosliw@gmail.com',
                   'phone': '919-327-7497', 'zip': '27519'}, f"filled fields only: {card}")
    check(set(browse.CONTACT_FIELDS) == {'first_name', 'last_name', 'email', 'phone', 'street', 'apt', 'city', 'state', 'zip', 'preferred'}, "the ten fields")


def scenario_settings_schema_and_registry_know_every_key():
    s = Settings()
    for f in browse.CONTACT_FIELDS:
        check(hasattr(s, f'contact_{f}'), f"Settings has contact_{f}")
    check(s.missions_captcha_attempts is False and s.mission_cap_browse_turns == 400, "defaults: consent off, 400 turns")
    keys = {e['key'] for e in settings_registry.ENTRIES}
    for k in [f'contact_{f}' for f in browse.CONTACT_FIELDS] + ['missions_captcha_attempts', 'mission_cap_browse_turns']:
        check(k in keys, f"{k} is registered")
    src = open('templates/components/missions_page.html', encoding='utf-8').read()
    for k in ('contact_first_name', 'contact_zip', 'missions_captcha_attempts', 'mission_cap_browse_turns'):
        check(f's.{k}' in src, f"the drawer binds {k}")
    check("settings_section('contact-card'" in src, "the contact card is its own section")


SCENARIOS = [scenario_contact_card_reads_only_filled_fields, scenario_settings_schema_and_registry_know_every_key]

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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

Check the registry's list name first (`grep -n "^ENTRIES\|^REGISTRY\|^SETTINGS" services/settings_registry.py`) and use it.

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_browse_settings.py`
Expected: `ImportError: cannot import name 'browse'`.

- [ ] **Step 3: `services/browse.py`, first slice**

```python
"""Browse — a mission's browser, driven by Gemini Computer Use over Playwright.
Spec: docs/superpowers/specs/2026-10-10-browse-missions-design.md §1–2.

This module never books, pays, submits or sends. The guards below are code,
not prompt: a test holds each one. The paid key is read only through
model_pools.api_key_for_pool (pool 'cu').
"""
from typing import Optional

from services import storage

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
```

- [ ] **Step 4: Schema, registry, drawer**

`models/schemas.py` (Settings, after `thread_cap_photo_reads`):

```python
    # Browse missions: the household contact card (the family's own details,
    # released per site per mission) and the browser's switches.
    contact_first_name: Optional[str] = ''
    contact_last_name: Optional[str] = ''
    contact_email: Optional[str] = ''
    contact_phone: Optional[str] = ''
    contact_street: Optional[str] = ''
    contact_apt: Optional[str] = ''
    contact_city: Optional[str] = ''
    contact_state: Optional[str] = ''
    contact_zip: Optional[str] = ''
    contact_preferred: Optional[str] = ''        # text | email | phone
    missions_captcha_attempts: Optional[bool] = False
    mission_cap_browse_turns: Optional[int] = 400
```

`services/settings_registry.py` (after the missions entries):

```python
    _e('contact_first_name', 'missions', 'Contact card: first name',
       "The family's own contact details, filled once. A mission releases them to a site only after a parent approves that site, once per mission.",
       page='work?tab=missions', anchor='contact-card'),
    _e('contact_last_name', 'missions', 'Contact card: last name', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_email', 'missions', 'Contact card: email', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_phone', 'missions', 'Contact card: phone', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_street', 'missions', 'Contact card: street', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_apt', 'missions', 'Contact card: apt / suite', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_city', 'missions', 'Contact card: city', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_state', 'missions', 'Contact card: state', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_zip', 'missions', 'Contact card: ZIP', 'See first name.', page='work?tab=missions', anchor='contact-card'),
    _e('contact_preferred', 'missions', 'Contact card: preferred contact', 'text, email or phone.', page='work?tab=missions', anchor='contact-card'),
    _e('missions_captcha_attempts', 'missions', 'Let Argyle attempt human-verification checks',
       "Off by default. On, a browse may tick a CAPTCHA checkbox and try at most two image challenges, then hands the page to you.",
       page='work?tab=missions', anchor='browse'),
    _e('mission_cap_browse_turns', 'missions', 'Daily browse-turn cap',
       "Hard ceiling on browser actions Argyle takes per day across missions (default 400), billed on the paid key.",
       page='work?tab=missions', anchor='browse'),
```

`templates/components/missions_page.html`: inside the drawer, after the `missions-settings` section's closing `{% endcall %}`, add two sections (the drawer macro adds jump chips at three or more):

```html
            {% call settings_section('browse', 'Browser') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-3">
                <label class="flex items-center justify-between bg-gray-800 rounded-xl border border-gray-700 px-4 py-3">
                    <span class="text-sm font-semibold text-gray-200">Let Argyle attempt human-verification checks</span>
                    <input type="checkbox" x-model="s.missions_captcha_attempts" @change="save()" class="h-5 w-5 accent-pink-400">
                </label>
                <p class="text-[11px] text-gray-500 -mt-1 px-1">Off: a browse stops at a CAPTCHA and hands you the page. On: one checkbox and up to two image challenges, then it hands over.</p>
                <div class="bg-gray-800 rounded-xl border border-gray-700 px-4 py-3">
                    <div class="text-xs font-semibold text-gray-400 mb-1">Daily browse-turn cap</div>
                    <input type="number" min="0" x-model.number="s.mission_cap_browse_turns" @change="save()"
                        class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-white">
                </div>
            </div>
            {% endcall %}
            {% call settings_section('contact-card', 'Household contact card') %}
            <div class="bg-gray-900 rounded-xl p-4 space-y-2">
                <p class="text-[11px] text-gray-500 px-1">The family's own details. A mission shows you exactly which of these a site wants before any of them leave the house; approve once per site per mission.</p>
                <div class="grid grid-cols-2 gap-2">
                    <input placeholder="First name" x-model="s.contact_first_name" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="Last name" x-model="s.contact_last_name" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="Email" x-model="s.contact_email" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="Phone" x-model="s.contact_phone" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="Street" x-model="s.contact_street" @change="save()" class="col-span-2 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="Apt / suite" x-model="s.contact_apt" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="City" x-model="s.contact_city" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="State" x-model="s.contact_state" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <input placeholder="ZIP" x-model="s.contact_zip" @change="save()" class="bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                    <select x-model="s.contact_preferred" @change="save()" class="col-span-2 bg-gray-800 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-sm">
                        <option value="">Preferred contact: not set</option>
                        <option value="text">Text</option><option value="email">Email</option><option value="phone">Phone</option>
                    </select>
                </div>
            </div>
            {% endcall %}
```

In the page script: add every new key to the defaults object (`contact_first_name: '', … contact_preferred: '', missions_captcha_attempts: false, mission_cap_browse_turns: 400`) and to `save()`'s payload (strings as `(this.s.contact_x || '').trim()`, the bool as `!!this.s.missions_captcha_attempts`, the cap as `Math.max(0, parseInt(..., 10) || 0)`). Confirm `save()` posts only the keys it names (it does: the paid key is excluded on purpose). Run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 5: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_browse_settings.py` and `..\venv\Scripts\python.exe tools\test.py settings_registry missions_endpoints settings_drawer_work tailwind_build`
Expected: `2/2`; the registry audit finds every key inside the Missions drawer; the drawer live test still passes with three sections (chips appear).

- [ ] **Step 6: Commit**

```bash
git add services/browse.py models/schemas.py services/settings_registry.py templates/components/missions_page.html static/tailwind.css static/tailwind-app.css tests/test_browse_settings.py config.yaml
git commit -m "feat(browse): the household contact card, the CAPTCHA consent switch and the browse-turn cap in the Missions drawer (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 2: The runner — guards first

**Files:**
- Modify: `services/browse.py`
- Modify: `requirements.txt` (`playwright`, `google-genai`)
- Create: `tests/test_browse_runner.py`, `tests/browse_pages.py` (the local test site)

**Interfaces:**
- Produces:
  - `browse.run(goal: str, site: str, released: dict, consent: dict, caps: dict = None, start_url: str = None, out_dir: str = None) -> dict` (the report of spec §2).
  - `browse._model_step(contents, settings) -> dict` seam: `{'calls': [{'name', 'args'}], 'text': str, 'content': <object to append to contents or None>, 'tokens': (in, out)}`; tests replace it. `browse._model_step_live` is the real one (Task 3).
  - `browse._launch(headless=True)` seam returning a Playwright `(playwright, browser)`; `browse.available() -> (bool, reason)`; `browse.free_memory_mb() -> int | None`.
  - `browse.OUTCOMES`, `browse.STOP_WORDS`, `browse.CONTACT_LABELS`, `browse.PAYMENT_PATTERNS`, `browse.CAPTCHA_MARKERS`, `browse.DEFAULT_CAPS = {'turns': 40, 'seconds': 300, 'captcha_attempts': 3}`.

- [ ] **Step 1: The local test site** — `tests/browse_pages.py`:

```python
"""A tiny site for the runner's tests, served on 127.0.0.1 by a thread. A
second hostname (localhost) plays the 'other domain'."""
import http.server
import threading

PAGES = {
    '/start': '<h1>Service</h1><a id="go" href="/form">Schedule service</a> <a id="away" href="http://localhost:{port}/other">Marketplace</a> <a id="redir" href="/redir">Partner</a>',
    '/form': ('<h1>Step 1</h1><form action="/form2" method="get">'
              '<label>First Name *<input name="first" required></label>'
              '<label>Email *<input name="email" type="email" required></label>'
              '<label>Zip *<input name="zip" required></label>'
              '<button type="submit" id="next">Next: Select Appliance</button></form>'),
    '/form2': '<h1>Step 2</h1><p>Earliest: Tue 8-noon. Trip charge $114.95</p><button id="book" type="button">Book appointment</button><button id="confirm" type="submit">Confirm</button>',
    '/pay': '<h1>Payment</h1><form><input name="cardnumber" autocomplete="cc-number"><input name="cvc" placeholder="CVC"></form>',
    '/captcha': '<h1>Check</h1><p>Please verify you are human</p><div id="recaptcha"><iframe src="/anchor?k=recaptcha" title="reCAPTCHA"></iframe></div>',
    '/anchor': '<input type="checkbox" id="recaptcha-anchor">',
    '/denied': '<h1>Access denied</h1><p>unusual traffic from your network</p>',
    '/other': '<h1>Other site</h1>',
    '/zip': '<h1>Where</h1><form><label>Zip *<input name="zip" required></label><button type="submit">Next</button></form>',
}


class H(http.server.BaseHTTPRequestHandler):
    port = 0

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/redir':
            self.send_response(302); self.send_header('Location', f'http://localhost:{self.port}/other'); self.end_headers(); return
        body = PAGES.get(path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        body = body.replace('{port}', str(self.port))
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers()
        self.wfile.write(f'<html><body>{body}</body></html>'.encode())

    def log_message(self, *a):
        pass


def serve():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
    H.port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]
```

- [ ] **Step 2: Write the failing tests** — `tests/test_browse_runner.py`:

```python
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
    r = browse.run('go to step 2', SITE, {}, {}, start_url=f'{URL}/form', out_dir=OUT)
    check(r['outcome'] != 'blocked', f"a multi-step Next passes: {r['outcome']} {r['text']}")
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


SCENARIOS = [scenario_done_report_shape, scenario_submit_stop_by_words_not_by_type, scenario_domain_allowlist_learns_redirects_only,
             scenario_payment_field_stops_before_typing, scenario_required_contact_fields_pause_for_release,
             scenario_typing_guard_refuses_any_unreleased_personal_shape, scenario_captcha_consent_off_stops_untouched,
             scenario_captcha_consent_on_is_capped, scenario_caps_and_availability]

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
```

- [ ] **Step 3: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_browse_runner.py`
Expected: FAIL with `AttributeError: module 'services.browse' has no attribute '_model_step'`.

- [ ] **Step 4: The runner** — append to `services/browse.py`:

```python
import base64
import json
import logging
import os
import re
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

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
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
    except Exception:
        pw.stop()
        raise
    return pw, browser


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or '').lower()
    parts = host.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 and not host.replace('.', '').isdigit() else host


def _model_step_live(contents, settings):
    """Task 3 fills this in. Until then the runner refuses without a model."""
    raise RuntimeError('no model')


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


def _personal_violation(text: str, released: dict, card: dict):
    """A typed string that is a contact-card value not released, or any email
    or phone shape when none was released. Returns the offending field name."""
    t = (text or '').strip()
    if not t:
        return None
    for name, value in card.items():
        if value and value.lower() in t.lower() and name not in released:
            return name
    if EMAIL_SHAPE.search(t) and 'email' not in released:
        return 'email'
    if PHONE_SHAPE.search(t) and len(re.sub(r'\D', '', t)) >= 10 and 'phone' not in released:
        return 'phone'
    return None


def _act(page, name, args):
    if name in ('click_at', 'click', 'double_click_at', 'double_click'):
        x, y = _px(args['x'], args['y']); page.mouse.click(x, y, click_count=2 if 'double' in name else 1)
    elif name in ('type_text_at', 'type'):
        if 'x' in args:
            x, y = _px(args['x'], args['y']); page.mouse.click(x, y); page.wait_for_timeout(150)
            if args.get('clear_before_typing', True):
                page.keyboard.press('Control+A'); page.keyboard.press('Backspace')
        page.keyboard.type(str(args.get('text', '')))
        if args.get('press_enter'):
            page.keyboard.press('Enter')
    elif name in ('navigate', 'open_web_browser'):
        if args.get('url'):
            page.goto(args['url'], wait_until='domcontentloaded', timeout=30000)
    elif name in ('scroll_document', 'scroll_at', 'scroll'):
        mag = int(args.get('magnitude') or args.get('magnitude_in_pixels') or 600)
        d = args.get('direction', 'down')
        if 'x' in args:
            x, y = _px(args['x'], args['y']); page.mouse.move(x, y)
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
        x, y = _px(args['x'], args['y']); page.mouse.move(x, y)
    elif name == 'drag_and_drop':
        x1, y1 = _px(args['x'], args['y']); x2, y2 = _px(args['destination_x'], args['destination_y'])
        page.mouse.move(x1, y1); page.mouse.down(); page.mouse.move(x2, y2); page.mouse.up()
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
              'turns': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0.0, 'screenshots': [], 'filled': {}}

    def finish(outcome, text):
        report['outcome'] = outcome; report['text'] = text; report['seconds'] = round(time.time() - t0, 1)
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
    try:
        ctx = browser.new_context(viewport={'width': W, 'height': H}, locale='en-US')
        page = ctx.new_page()
        page.on('response', lambda r: allowed.add(_domain(r.headers.get('location', '')))
                if 300 <= r.status < 400 and r.headers.get('location', '').startswith('http') and _domain(r.url) in allowed else None)
        page.goto(start, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(800)
        shot = page.screenshot(type='png')
        report['screenshots'].append(os.path.join(out_dir, 'turn_00.png')); open(report['screenshots'][-1], 'wb').write(shot)
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
            step = _model_step(contents, settings)
            report['turns'] = turn
            ti, to = step.get('tokens') or (0, 0); report['tokens_in'] += int(ti); report['tokens_out'] += int(to)
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
                        if v and v.lower() in str(args.get('text') or '').lower():
                            report['filled'][k] = v
                if name in ('navigate', 'open_web_browser') and args.get('url') and _domain(args['url']) not in allowed:
                    strikes += 1
                    if strikes > 1:
                        return finish('blocked', f'left the site: {args["url"]}')
                    results.append((name, args, {'error': 'that is another site; stay on ' + site})); continue
                before = page.url
                try:
                    _act(page, name, args); res = {}
                except Exception as e:
                    res = {'error': str(e)[:160]}
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
                shot = page.screenshot(type='png')
                p = os.path.join(out_dir, f'turn_{turn:02d}.png'); open(p, 'wb').write(shot); report['screenshots'].append(p)
                results.append((name, args, res))
            contents.append({'role': 'user', 'function_responses': [(n, {'url': page.url, **r}, shot) for n, a, r in results]})
        return finish('capped', f"stopped after {caps['turns']} turns")
    except Exception as e:
        logger.warning(f"[browse] run failed: {e}")
        return finish('error', str(e)[:200])
    finally:
        try:
            browser.close(); pw.stop()
        except Exception:
            pass
```

The `contents` list uses a neutral shape (`{'role','parts'|'function_responses'}`) that `_model_step_live` (Task 3) converts to `google.genai.types`; the fake in tests ignores it. Add `playwright` and `google-genai` to `requirements.txt`.

- [ ] **Step 5: Run the runner tests**

Run: `..\venv\Scripts\python.exe tests\test_browse_runner.py`
Expected: `9/9 scenarios passed`. Expect to iterate on `_scan`'s label matching against the test pages (the `*` in a label text marks required) and on the redirect listener (Playwright's `response` event carries the 302 with its `location` header). Fix the runner, not the assertions.

- [ ] **Step 6: Commit**

```bash
git add services/browse.py requirements.txt tests/test_browse_runner.py tests/browse_pages.py config.yaml
git commit -m "feat(browse): the runner with its guards in code - domain, submit, payment, personal data, release, CAPTCHA, caps, availability (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 3: The live model step and pool `cu`

**Files:**
- Modify: `services/browse.py` (`_model_step_live`)
- Modify: `services/model_pools.py` (`DEFAULT_POOLS['cu']`, `TIER_CHAINS['browse']`, `api_key_for_pool`)
- Test: `tests/test_browse_runner.py` (two scenarios), `tests/test_missions_pools.py` (one)

**Interfaces:**
- Produces: `model_pools.DEFAULT_POOLS['cu'] = ['gemini-3.8-flash']`, `TIER_CHAINS['browse'] = ['cu']`, `api_key_for_pool('cu', s)` → the paid key; `browse._model_step_live(contents, settings)` converting the neutral `contents` to `google.genai.types` and calling `generate_content` with `types.Tool(computer_use=types.ComputerUse(environment=types.Environment.ENVIRONMENT_BROWSER))`; `browse.MODEL = 'gemini-3.8-flash'`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_browse_runner.py` before `SCENARIOS`; add them to it)

```python
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
            captured['model'] = model; captured['contents'] = contents; captured['config'] = config
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
        step2 = browse._model_step_live([{'role': 'user', 'function_responses': [('click_at', {'url': 'u', 'safety_acknowledgement': 'true'}, b'\x89PNG')]}], {'llm_gemini_paid_api_key': 'paid'})
        parts = captured['contents'][-1].parts
        check(parts and parts[0].function_response and parts[0].function_response.response.get('safety_acknowledgement') == 'true'
              and parts[0].function_response.parts, "a function response carries the url, the acknowledgement and the screenshot")
    finally:
        browse._client = orig
```

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_browse_runner.py`
Expected: the two new scenarios FAIL (`DEFAULT_POOLS` has no `cu`; `browse` has no `_client`).

- [ ] **Step 3: Pool and key** — `services/model_pools.py`:

```python
    # Browse missions (services/browse.py): Gemini Computer Use on flash,
    # billed on the paid key like the pro pool. One model; no free fallback.
    'cu': ["gemini-3.8-flash"],
```

in `DEFAULT_POOLS`; `'browse': ['cu'],` in `TIER_CHAINS`; in `api_key_for_pool`: `if pool_name in ('pro', 'cu'):` returns the paid key (update the docstring: "the pro and cu pools bill the paid key").

- [ ] **Step 4: The live step** — in `services/browse.py` replace `_model_step_live`:

```python
MODEL = 'gemini-3.8-flash'


def _client(api_key: str):
    from google import genai
    return genai.Client(api_key=api_key)


def _to_types(contents: list):
    from google.genai import types
    out = []
    for c in contents:
        if hasattr(c, 'parts') and not isinstance(c, dict):
            out.append(c); continue
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
```

- [ ] **Step 5: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_browse_runner.py` and `..\venv\Scripts\python.exe tools\test.py missions_pools missions_pins`
Expected: `11/11`; pools and pins green (the pin's allowed readers are unchanged: browse.py never names the key).

- [ ] **Step 6: Commit**

```bash
git add services/browse.py services/model_pools.py tests/test_browse_runner.py config.yaml
git commit -m "feat(browse): the live computer-use step on pool cu, billed on the paid key only (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 4: `browse` as a mission action, in its own thread

**Files:**
- Modify: `services/missions.py` (`_system_prompt` lines, `step` `browse` branch, `_run_browse`, `finish_browse`, `tick` reclaim, `_dm_person`, `browse_dir`)
- Modify: `services/situations.py` (`_is_done` unchanged; `_group`/`needs_attention` treat `browsing` as moving — check they do: `needs_attention` for a mission is "any answer/do option"; a `browsing` mission has none → `moving`)
- Modify: `main.py` (`GET /api/missions/{id}/shots/{name}`, parent-gated, serving from `browse_dir`)
- Test: `tests/test_browse_mission.py` (new)

**Interfaces:**
- Produces:
  - Mission status `browsing` (between `running` and the report).
  - `missions._browse = browse.run` (test seam); `missions.start_browse(mission, goal, site, start_url=None, released=None) -> step_id` (adds the `browse` step, sets `browsing`, starts the thread); `missions.finish_browse(mission_id, step_id, report)` (writes the result, maps the outcome).
  - Outcome mapping: `done`/`refused`/`capped`/`error`/`blocked (left the site)` → `running` (the planner reads the report); `needs_release` → an `ask` step named `release` + `waiting_user` + DM; `captcha_failed`, `blocked (payment)` → an `ask` step named `handoff` + `waiting_user` + DM.
  - `missions._dm_person(mission, text)` posts to the creator's Argyle DM (parents of record when none).
  - `missions.BROWSE_LOST_S = 600`; `tick` reclaims a `browsing` mission whose browse step is older than that.
  - `missions.browse_dir(mission_id) -> path` under `<data dir>/browse/<mission_id>`.
  - `_bump_call('browse_turns', cap)` counted after each run by its turns; a run refuses to start when today's count is at the cap.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_browse_mission.py
"""browse as a mission action: the report is a step; outcomes map to running,
a release ask, or a hand-off ask; the tick reclaims a lost browse; the
person is told. A fake runner; no browser. Spec 2026-10-10 §2."""
import time
from datetime import date

from harness import check  # noqa: F401
from services import storage, missions, situations

SENT = []


def _reset():
    for t in (storage.missions_table, storage.mission_steps_table, storage.members_table, storage.app_state_table,
              storage.chat_channels_table, storage.chat_messages_table, storage.threads_table):
        t.truncate()
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'llm_gemini_api_key': 'k',
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519'}
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {})
    situations.REFRESH_DELAY_S = 0
    situations._pool_call = lambda *a, **k: {}
    SENT.clear()
    missions._post = lambda dm, argyle, body, card=None: SENT.append(body) or {'id': 'm'}
    missions._browse_async = False          # run the runner inline in tests


def _report(outcome, **kw):
    base = {'outcome': outcome, 'text': kw.pop('text', outcome), 'learned': {}, 'stopped_at': 'https://bodewell.com/guest-schedule-service',
            'wanted_fields': [], 'turns': 7, 'tokens_in': 1000, 'tokens_out': 50, 'seconds': 30.0, 'screenshots': [], 'filled': {}}
    return {**base, **kw}


def _mission():
    return storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})


def scenario_browse_action_runs_the_runner_and_transcribes():
    _reset()
    calls = []
    missions._browse = lambda **kw: calls.append(kw) or _report('done', text='Earliest Tue 8-noon. Trip $114.95', learned={'fee': '$114.95'})
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'find appointment windows and the trip charge', 'site': 'bodewell.com'}
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'running', f"after a done browse the planner runs on: {row['status']}")
    steps = storage.get_mission_steps(mid)
    b = [s for s in steps if s['kind'] == 'browse'][0]
    check(b['args_json']['site'] == 'bodewell.com' and b['result_json']['outcome'] == 'done' and '$114.95' in b['result_json']['text'], f"the step: {b}")
    check(calls and calls[0]['site'] == 'bodewell.com' and calls[0]['released'] == {} and 'consent' in calls[0], f"the runner got the goal, site, no release: {calls[0]}")
    counts = storage.get_app_state(f"mission_calls:{date.today().isoformat()}") or {}
    check(counts.get('browse_turns') == 7, f"turns counted against the day: {counts}")
    check(not SENT, "a done browse tells nobody; the planner decides")


def scenario_needs_release_pauses_with_the_values_and_tells_the_person():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['first_name', 'email', 'zip'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'waiting_user', "the mission waits")
    ask = storage.get_mission_steps(mid)[-1]
    check(ask['kind'] == 'ask' and ask['name'] == 'release' and ask['result_json']['site'] == 'bodewell.com'
          and ask['result_json']['fields'] == ['first_name', 'email', 'zip']
          and ask['result_json']['values'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com', 'zip': '27519'}, f"the release ask: {ask}")
    check(ask['result_json']['browse']['goal'] == 'g' and ask['result_json']['browse']['start_url'].startswith('https://bodewell.com'), "the pending browse rides on the ask")
    check(SENT and 'bodewell.com' in SENT[0] and 'Jeff' in SENT[0] and 'ffejnosliw@gmail.com' in SENT[0], f"the DM shows the exact values: {SENT}")
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check(s['next_step']['verb'] == 'release' and s['next_step']['id'] == 'release:approve', f"the card's next step is the approval: {s['next_step']}")
    check([o['id'] for o in s['options'] if o['verb'] == 'release'] == ['release:approve', 'release:decline', 'release:stop'], "approve, not these, stop")


def scenario_captcha_and_payment_hand_off():
    for outcome, text in (('captcha_failed', '3 attempts at the human-verification check failed'), ('blocked', 'this part needs a payment card; do it yourself here')):
        _reset()
        missions._browse = lambda **kw: _report(outcome, text=text, filled={'first_name': 'Jeff'})
        mid = _mission()
        missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
        row = missions.step(storage.get_mission(mid))
        check(row['status'] == 'waiting_user', f"{outcome}: hand-off waits on the person")
        ask = storage.get_mission_steps(mid)[-1]
        check(ask['kind'] == 'ask' and ask['name'] == 'handoff' and 'bodewell.com' in ask['result_json']['url']
              and ask['result_json']['filled'] == {'first_name': 'Jeff'} and 'question' in ask['result_json'], f"the hand-off ask: {ask}")
        check(SENT and 'bodewell.com' in SENT[0] and 'Jeff' in SENT[0] and 'tell me what you found' in SENT[0].lower(), f"the DM: {SENT}")
        s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
        check(s['next_step']['verb'] == 'answer', "the card asks for the answer")


def scenario_left_the_site_and_refusals_are_notes_the_planner_reads():
    _reset()
    for outcome in ('refused', 'capped', 'error'):
        missions._browse = lambda **kw: _report(outcome, text='x')
        mid = _mission()
        missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
        row = missions.step(storage.get_mission(mid))
        check(row['status'] == 'running' and not SENT, f"{outcome}: the planner reads it, nobody is paged")


def scenario_browse_cap_refuses_before_running():
    _reset()
    storage.set_app_state(f"mission_calls:{date.today().isoformat()}", {'browse_turns': 400})
    ran = []
    missions._browse = lambda **kw: ran.append(1) or _report('done')
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    last = storage.get_mission_steps(mid)[-1]
    check(not ran and last['kind'] == 'note' and 'cap' in (last['result_json'].get('note') or ''), f"the day's cap refuses the run: {last}")


def scenario_a_lost_browse_is_reclaimed_by_the_tick():
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    out = missions.tick()
    check(storage.get_mission(mid)['status'] == 'browsing', "a fresh browse is left alone")
    storage.mission_steps_table.update({'ts': time.time() - missions.BROWSE_LOST_S - 5}, storage.Query().id == sid)
    missions.tick()
    row = storage.get_mission(mid)
    check(row['status'] == 'running', f"an old browse with no result is reclaimed: {row['status']}")
    last = storage.get_mission_steps(mid)[-1]
    check(last['kind'] == 'note' and 'lost' in (last['result_json'].get('note') or ''), "and the loss is on the transcript")


def scenario_browsing_mission_is_moving_not_done():
    _reset()
    mid = _mission()
    storage.update_mission(mid, {'status': 'browsing'})
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check(s['group'] == 'moving' and not s['needs_attention'], f"browsing is moving: {s['group']}")


SCENARIOS = [scenario_browse_action_runs_the_runner_and_transcribes, scenario_needs_release_pauses_with_the_values_and_tells_the_person,
             scenario_captcha_and_payment_hand_off, scenario_left_the_site_and_refusals_are_notes_the_planner_reads,
             scenario_browse_cap_refuses_before_running, scenario_a_lost_browse_is_reclaimed_by_the_tick,
             scenario_browsing_mission_is_moving_not_done]

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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} scenarios passed")
    raise SystemExit(1 if failed else 0)
```

`storage.Query` may not be exported; use `from tinydb import Query` if not. The `release` verb and options come in Task 5; until then the second scenario's last two checks fail. Run this file's first scenario and the others now; the whole file goes green in Task 5.

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_browse_mission.py`
Expected: FAIL across the board (`missions` has no `_post`, no `_browse`, the `browse` action is "unparsed").

- [ ] **Step 3: The engine** — `services/missions.py`:

Prompt (in `_system_prompt`, add an action line and Appendix B's planner rules):

```python
        '{"action":"browse","goal":"<what to learn or do on the site, in words>","site":"<the site, e.g. bodewell.com>"}\n'
```

after the `research` line, and after "Prefer finishing with a small set…":

```python
        "To find a thing's details, search our own mail (search_mail) before "
        "the web. To deal with a company, prefer its official site. Use browse "
        "only for what reading cannot answer, and name the site. Before any "
        "form that wants the family's details, expect a release step and wait "
        "for it. A browse that stops at a wall is a result, not a failure: the "
        "person is handed the link. Never claim a booking, a price or a slot a "
        "browse did not show.\n"
```

Constants and helpers (near the top):

```python
BROWSE_LOST_S = 600
BROWSE_CAP_DEFAULT = 400
_browse_async = True                     # tests run the runner inline


def browse_dir(mission_id: str) -> str:
    d = os.path.join(os.path.dirname(storage.DB_PATH), 'browse', mission_id)
    os.makedirs(d, exist_ok=True)
    return d


def _browse_live(**kw):
    from services import browse
    return browse.run(**kw)


_browse = _browse_live


def _post(dm, argyle, body, card=None):
    from services.agent_tools_v2 import _post_chat_message
    return _post_chat_message(dm, argyle, body, card=card)


def _dm_person(mission: dict, text: str) -> None:
    """One message to whoever started the mission (the parents when nobody
    did), in their Argyle DM. Never raises."""
    try:
        argyle = storage.ensure_argyle_member()
        who = storage.get_member(mission.get('created_by') or '') if mission.get('created_by') else None
        people = [who] if who else [m for m in storage.get_all_members() if m.get('role') == 'parent' and not m.get('system')]
        for m in people:
            _post(storage.get_or_create_dm(argyle['id'], m['id']), argyle, text)
    except Exception as e:
        logger.warning(f"[missions] DM failed: {e}")


def _released_for(mission: dict, site: str) -> dict:
    from services import browse as _b
    card = _b.contact_card()
    for r in mission.get('releases') or []:
        if r.get('site') == _b._domain(f'https://{site}' if '://' not in site else site):
            return {f: card[f] for f in r.get('fields') or [] if f in card}
    return {}


def start_browse(mission: dict, goal: str, site: str, start_url: str = None, released: dict = None) -> str:
    mid = mission['id']
    settings = storage.get_settings() or {}
    cap = int(settings.get('mission_cap_browse_turns', BROWSE_CAP_DEFAULT))
    day = datetime.date.today().isoformat()
    used = int((storage.get_app_state(f'mission_calls:{day}') or {}).get('browse_turns', 0))
    if used >= cap:
        storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                       'result_json': {'note': f"browse cap ({cap} turns/day) reached; try tomorrow or raise it"}})
        return ''
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': site, 'args_json': {'goal': goal, 'site': site, 'start_url': start_url},
                                         'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    kw = dict(goal=goal, site=site, released=released if released is not None else _released_for(mission, site),
              consent={'captcha': bool(settings.get('missions_captcha_attempts'))}, start_url=start_url, out_dir=browse_dir(mid))

    def work():
        try:
            report = _browse(**kw)
        except Exception as e:
            report = {'outcome': 'error', 'text': str(e)[:200], 'learned': {}, 'stopped_at': start_url or site, 'wanted_fields': [],
                      'turns': 0, 'tokens_in': 0, 'tokens_out': 0, 'seconds': 0, 'screenshots': [], 'filled': {}}
        finish_browse(mid, sid, report)

    if _browse_async:
        threading.Thread(target=work, daemon=True).start()
    else:
        work()
    return sid


def finish_browse(mission_id: str, step_id: str, report: dict) -> None:
    from services import browse as _b
    mission = storage.get_mission(mission_id)
    if not mission:
        return
    step_row = next((s for s in storage.get_mission_steps(mission_id) if s['id'] == step_id), None)
    args = (step_row or {}).get('args_json') or {}
    site = args.get('site') or ''
    # Count the day's turns, whatever the outcome.
    day = datetime.date.today().isoformat()
    with storage.db_lock:
        counts = dict(storage.get_app_state(f'mission_calls:{day}') or {})
        counts['browse_turns'] = int(counts.get('browse_turns', 0)) + int(report.get('turns') or 0)
        storage.set_app_state(f'mission_calls:{day}', counts)
    shots = [os.path.basename(p) for p in report.get('screenshots') or []]
    storage.update_mission_step(step_id, {'result_json': {**report, 'screenshots': shots}})
    outcome = report.get('outcome')
    text = report.get('text') or ''
    if outcome == 'needs_release':
        card = _b.contact_card()
        fields = [f for f in report.get('wanted_fields') or [] if f in card]
        missing = [f for f in report.get('wanted_fields') or [] if f not in card]
        if not fields:
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'browse',
                                                  'result_json': {'note': f"the form wants {', '.join(missing)}; the contact card has none of it (Missions settings)"}})
            _close(mission_id, 'running'); return
        values = {f: card[f] for f in fields}
        domain = _b._domain(f'https://{site}')
        q = f"Share with {domain}: " + ' · '.join(values.values()) + '?'
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'release',
                                              'result_json': {'question': q, 'site': domain, 'fields': fields, 'values': values,
                                                              'missing': missing,
                                                              'browse': {'goal': args.get('goal'), 'site': site, 'start_url': report.get('stopped_at')}}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, f"Argyle needs a yes: {q} (mission: {mission.get('goal')}). Approve on the Missions page or the thread card.")
        return
    if outcome == 'captcha_failed' or (outcome == 'blocked' and 'payment' in text.lower()):
        url = report.get('stopped_at') or ''
        filled = report.get('filled') or {}
        reason = text
        q = (f"I got as far as {url}. " + (f"Filled so far: {', '.join(f'{k}={v}' for k, v in filled.items())}. " if filled else '')
             + f"{reason}. Finish it on your phone and tell me what you found.")
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff',
                                              'result_json': {'question': q, 'url': url, 'filled': filled, 'reason': reason}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return
    _close(mission_id, 'running')
```

Check `storage.update_mission_step` exists (`grep -n "def update_mission_step" services/storage.py`); add it beside `add_mission_step` if not:

```python
def update_mission_step(step_id: str, data: dict) -> bool:
    with db_lock:
        return bool(mission_steps_table.update(data, Query().id == step_id))
```

Also the mission row needs a `releases` list: `storage.add_mission` defaults do not include it; `_released_for` tolerates its absence. Imports at the top of `missions.py`: `os`, `threading` (check they are present).

The `step()` branch, after `research`:

```python
    if action == 'browse':
        goal = (res.get('goal') or '').strip()
        site = (res.get('site') or '').strip().lower().replace('https://', '').replace('http://', '').split('/')[0]
        if not goal or not site:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused',
                                           'result_json': {'note': 'browse needs a goal and a site'}})
            return storage.get_mission(mid)
        start_browse(storage.get_mission(mid), goal, site)
        return storage.get_mission(mid)
```

The `tick()` reclaim, before the `running = …` line:

```python
    # A browse whose thread died (crash, restart) must not strand the mission.
    for row in storage.get_missions(status='browsing'):
        steps = storage.get_mission_steps(row['id'])
        b = next((s for s in reversed(steps) if s.get('kind') == 'browse'), None)
        if b and b.get('result_json') is None and (b.get('ts') or 0) < ts - BROWSE_LOST_S:
            storage.add_mission_step(row['id'], {'kind': 'note', 'name': 'browse',
                                                 'result_json': {'note': 'the browse was lost (no result after 10 minutes)'}})
            storage.update_mission(row['id'], {'status': 'running'})
```

Check `storage.get_missions(status=...)` accepts a string (it does: the engine test uses it).

- [ ] **Step 4: The screenshots route** — `main.py`, beside the mission endpoints:

```python
@app.get("/api/missions/{mission_id}/shots/{name}")
def mission_shot(mission_id: str, name: str, request: Request = None):
    """A browse step's screenshot (parent-gated like the transcript). Lives
    under the data dir, never under the moments media root."""
    _mind_actor(request, request.query_params.get('member_id') if request else None)
    from services import missions as _missions
    import re as _re
    if not _re.fullmatch(r'[a-z0-9_]+\.png', name or ''):
        raise HTTPException(status_code=404, detail="No such image")
    path = os.path.join(_missions.browse_dir(mission_id), name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="No such image")
    return FileResponse(path, media_type='image/png')
```

Register it in `services/auth.py` RULES wherever `/api/missions/{mission_id}` is classified (same tier). Add a check to `test_browse_mission.py`:

```python
def scenario_shots_route_is_classified():
    from services import auth
    check(auth.resolve('GET', '/api/missions/x/shots/turn_01.png') == auth.resolve('GET', '/api/missions/x'), "the shot is gated like the transcript")
```

- [ ] **Step 5: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_browse_mission.py` and `..\venv\Scripts\python.exe tools\test.py missions_engine missions_pins missions_endpoints situation auth`
Expected: all but the two `release`-verb checks pass (they land in Task 5); related green. `test_missions_pins.scenario_missions_cannot_reach_the_mailer` still holds (`_post` goes through `agent_tools_v2._post_chat_message`, not the mailer).

- [ ] **Step 6: Commit**

```bash
git add services/missions.py services/storage.py services/auth.py main.py tests/test_browse_mission.py config.yaml
git commit -m "feat(missions): browse as one action in its own thread; outcomes become a release ask, a hand-off ask, or a note the planner reads; the tick reclaims a lost browse (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 5: The release — verb, endpoint, resume

**Files:**
- Modify: `services/missions.py` (`release(mission_id, decision, actor)`)
- Modify: `services/situations.py` (`VERBS` + `release`, `_options_mission`, `_run`)
- Modify: `static/situations.js` (`VERB_LABELS.release`), `services/agent_tools_v2.py` (`act_on_situation` enum)
- Modify: `main.py` (`POST /api/missions/{id}/release`)
- Test: `tests/test_browse_mission.py`

**Interfaces:**
- Produces: `missions.release(mission_id, decision: 'approve'|'decline'|'stop', actor) -> dict`; approve appends `{site, fields, approved_by, at}` to the mission's `releases`, notes `release_approved`, and re-runs the pending browse with the released values (`start_browse(..., start_url=pending.start_url, released=values)`); decline → a `handoff` ask + DM; stop → `_close(blocked, 'the family kept its details')`. Idempotent: a release already acted on returns `already`.
- Situation options on a mission whose last `ask` step is `release`: `release:approve` ("Share with {site}"), `release:decline` ("Not these"), `release:stop` ("Stop the mission"); verb `release` in `VERBS`, `VERB_LABELS`, the tool enum; `act` → `missions.release`.

- [ ] **Step 1: Write the failing tests** (append)

```python
def scenario_release_approved_resumes_with_the_values_once():
    _reset()
    runs = []
    seq = [_report('needs_release', wanted_fields=['first_name', 'email']), _report('done', text='Tue 8-noon')]
    missions._browse = lambda **kw: runs.append(kw) or seq.pop(0)
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    res = situations.act('mission', mid, 'release', option_id='release:approve', actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'success', f"approve through the card: {res}")
    row = storage.get_mission(mid)
    check(row['status'] == 'running' and row['releases'][0]['site'] == 'bodewell.com' and row['releases'][0]['fields'] == ['first_name', 'email']
          and row['releases'][0]['approved_by'] == 'mom', f"recorded: {row.get('releases')}")
    check(len(runs) == 2 and runs[1]['released'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'} and runs[1]['start_url'].startswith('https://bodewell.com'),
          f"the browse resumed where it stopped with the released values: {runs[1]}")
    # The same site again in this mission: no second ask.
    seq.append(_report('needs_release', wanted_fields=['first_name']))
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g2', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    check(runs[-1]['released'] == {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'}, "released values ride every later browse of that site")


def scenario_release_approved_twice_resumes_once():
    _reset()
    runs = []
    seq = [_report('needs_release', wanted_fields=['zip']), _report('done')]
    missions._browse = lambda **kw: runs.append(kw) or seq.pop(0)
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    a = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
    b = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'})
    check(a['status'] == 'success' and b.get('already') and len(runs) == 2, f"a second approve is a no-op: {b} runs={len(runs)}")


def scenario_release_declined_hands_off_and_stop_blocks():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    res = situations.act('mission', mid, 'release', option_id='release:decline', actor={'id': 'mom', 'role': 'parent'})
    last = storage.get_mission_steps(mid)[-1]
    check(res['status'] == 'success' and last['kind'] == 'ask' and last['name'] == 'handoff' and storage.get_mission(mid)['status'] == 'waiting_user', f"decline hands off: {last}")
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions.step(storage.get_mission(mid))
    res = missions.release(mid, 'stop', {'id': 'mom', 'role': 'parent'})
    check(storage.get_mission(mid)['status'] == 'blocked' and 'kept' in (storage.get_mission(mid).get('error') or ''), "stop blocks the mission honestly")
    check(missions.release(mid, 'approve', {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a child cannot release")


def scenario_release_verb_is_in_the_closed_set_everywhere():
    import re
    from services import agent_tools_v2 as tools
    check('release' in situations.VERBS, "the verb")
    src = open('static/situations.js', encoding='utf-8').read()
    check("'release'" in re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1), "the card label")
    enum = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']['enum']
    check('release' in enum, "the tool enum")
```

Add all four to `SCENARIOS`.

- [ ] **Step 2: Run to verify they fail**

Run: `..\venv\Scripts\python.exe tests\test_browse_mission.py`
Expected: FAIL (`release` is not a verb; `missions.release` missing).

- [ ] **Step 3: `missions.release`**

```python
def release(mission_id: str, decision: str, actor: dict) -> dict:
    """The person's answer to a release ask: approve (record the site and
    fields on the mission and resume the pending browse with the values),
    decline (hand the page over), stop (block the mission)."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can release the family\'s details.'}
    mission = storage.get_mission(mission_id)
    if not mission:
        return {'status': 'error', 'message': 'No such mission.'}
    steps = storage.get_mission_steps(mission_id)
    ask = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
    if not ask or ask.get('name') != 'release' or mission.get('status') != 'waiting_user':
        return {'status': 'success', 'already': True, 'message': 'That release was already answered.'}
    rj = ask.get('result_json') or {}
    if decision == 'approve':
        rel = {'site': rj.get('site'), 'fields': rj.get('fields') or [], 'approved_by': actor.get('id'), 'at': time.time()}
        with storage.db_lock:
            row = storage.get_mission(mission_id)
            if row.get('status') != 'waiting_user':
                return {'status': 'success', 'already': True, 'message': 'Already answered.'}
            storage.update_mission(mission_id, {'releases': (row.get('releases') or []) + [rel], 'status': 'running'})
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'release_approved', 'result_json': {'site': rel['site'], 'fields': rel['fields']}})
        pending = rj.get('browse') or {}
        start_browse(storage.get_mission(mission_id), pending.get('goal') or mission.get('goal'), pending.get('site') or rel['site'],
                     start_url=pending.get('start_url'), released=rj.get('values') or {})
        return {'status': 'success', 'message': f"Shared with {rel['site']}. Carrying on."}
    if decision == 'decline':
        url = ((rj.get('browse') or {}).get('start_url')) or ''
        q = f"I got as far as {url}. The form wants {', '.join(rj.get('fields') or [])}, which you kept. Finish it on your phone and tell me what you found."
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff', 'result_json': {'question': q, 'url': url, 'filled': {}, 'reason': 'details not shared'}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return {'status': 'success', 'message': 'Kept. Finish it on your phone and tell me what you found.'}
    if decision == 'stop':
        _close(mission_id, 'blocked', error='the family kept its details')
        return {'status': 'success', 'message': 'Stopped.'}
    return {'status': 'error', 'message': 'approve, decline or stop'}
```

- [ ] **Step 4: Situations** — `VERBS` gains `'release'`; in `_options_mission`, replace the `waiting_user` branch:

```python
    if row.get('status') == 'waiting_user':
        asked = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
        rj = (asked or {}).get('result_json') or {}
        if (asked or {}).get('name') == 'release':
            out.append(_opt('release', f"Share with {rj.get('site')}", {'decision': 'approve'}, 'approve'))
            out.append(_opt('release', 'Not these', {'decision': 'decline'}, 'decline'))
            out.append(_opt('release', 'Stop the mission', {'decision': 'stop'}, 'stop'))
        else:
            q = rj.get('question') or 'Argyle has a question'
            out.append(_opt('answer', q, {}))
```

In `_run`, before `if verb == 'unread':`:

```python
    if verb == 'release':
        from services import missions as _m
        return _m.release(sid, p.get('decision'), actor)
```

`static/situations.js` `VERB_LABELS`: `'release': 'Share'`. `agent_tools_v2` `act_on_situation` enum: add `"release"`. The mission card's `release` verb needs no prompt (`act` only prompts for advance/answer/draft/research).

- [ ] **Step 5: The endpoint** — `main.py`:

```python
@app.post("/api/missions/{mission_id}/release")
def missions_release(mission_id: str, body: dict = Body(default={}), request: Request = None):
    from services import missions as _missions
    actor = _approver_of_record(_mind_actor(request, body.get('member_id')))
    res = _missions.release(mission_id, (body.get('decision') or '').strip(), actor)
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') == 'error':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res
```

Classify it in `auth.RULES` like `/api/missions/{id}/answer`.

- [ ] **Step 6: Run the tests**

Run: `..\venv\Scripts\python.exe tests\test_browse_mission.py` and `..\venv\Scripts\python.exe tools\test.py situation missions auth triage`
Expected: all scenarios pass, including Task 4's two deferred checks; `test_situation_tools.scenario_parity_both_ways` sees `release` in all three places.

- [ ] **Step 7: Commit**

```bash
git add services/missions.py services/situations.py static/situations.js services/agent_tools_v2.py services/auth.py main.py tests/test_browse_mission.py config.yaml
git commit -m "feat(missions): the release - approve shares the contact card with one site for this mission and resumes the browse; decline hands over; stop blocks (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 6: The transcript shows a browse, a release and a hand-off

**Files:**
- Modify: `templates/components/mission_transcript.html` (branches for `browse`, `ask/release`, `ask/handoff`, `note/release_approved`)
- Modify: `templates/components/missions_page.html` (`releaseMission(mission, decision)`; the answer box's heading for a hand-off shows the link)
- Test: `tests/test_missions_page_live.py` (one scenario added) or a new `tests/test_browse_page_live.py`

**Interfaces:** consumes the step shapes from Tasks 4–5 and `POST /api/missions/{id}/release`, `GET /api/missions/{id}/shots/{name}`.

- [ ] **Step 1: Write the failing live test** — `tests/test_browse_page_live.py`:

```python
"""/missions draws a browse step with its report and last screenshot, a release
ask with Approve / Not these / Stop, and a hand-off with its link."""
import os
import sys
import tempfile

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='browse_page_live_'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live_app import live_app
from services import storage

PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c63f8ff1f0003030200f0b3c2d10000000049454e44ae426082')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    from services import missions
    storage.update_settings({'llm_gemini_api_key': '', 'missions_enabled': True, 'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com'})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'color_code': '#6366f1'})
    mid = storage.add_mission({'goal': 'get the dishwasher fixed', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    open(os.path.join(missions.browse_dir(mid), 'turn_03.png'), 'wb').write(PNG)
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'find slots', 'site': 'bodewell.com'},
                                   'result_json': {'outcome': 'needs_release', 'text': 'the form wants first_name, email', 'learned': {}, 'turns': 3,
                                                   'stopped_at': 'https://bodewell.com/guest-schedule-service', 'screenshots': ['turn_03.png'], 'filled': {}}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'release', 'result_json': {'question': 'Share with bodewell.com: Jeff · ffejnosliw@gmail.com?', 'site': 'bodewell.com',
                                                                                     'fields': ['first_name', 'email'], 'values': {'first_name': 'Jeff', 'email': 'ffejnosliw@gmail.com'},
                                                                                     'browse': {'goal': 'find slots', 'site': 'bodewell.com', 'start_url': 'https://bodewell.com/guest-schedule-service'}}})
    storage.update_mission(mid, {'status': 'waiting_user'})
    missions._browse = lambda **kw: {'outcome': 'captcha_failed', 'text': 'the check failed', 'learned': {}, 'stopped_at': 'https://bodewell.com/x', 'wanted_fields': [],
                                     'turns': 2, 'tokens_in': 1, 'tokens_out': 1, 'seconds': 1, 'screenshots': [], 'filled': {'first_name': 'Jeff'}}
    missions._browse_async = False


def main():
    served = live_app(seed)
    if served is None:
        return
    try:
        b = served.browser(color_scheme='dark')
        with b as page:
            page.set_viewport_size({'width': 1300, 'height': 900})
            page.goto(served.url('work?tab=missions'), wait_until='networkidle')
            page.wait_for_selector('#missions .situation-card', timeout=15000)
            card = page.locator('#missions .situation-card').first
            check(card.locator('.sit-next button').first.inner_text().startswith('Share with bodewell.com'), "the card's next step is the release")
            page.locator('#missions details summary').first.click()
            page.wait_for_timeout(400)
            tl = page.locator('#missions details[open]').first.inner_text()
            check('bodewell.com' in tl and 'needs_release' in tl and 'first_name' in tl, f"the browse step shows its outcome: {tl[:300]}")
            check(page.locator('#missions details[open] img.browse-shot').count() == 1, "the last screenshot is drawn")
            check('Jeff' in tl and 'ffejnosliw@gmail.com' in tl, "the release shows the exact values")
            page.locator('#missions details[open] button:has-text("Not these")').first.click()
            page.wait_for_timeout(1500)
            row = storage.get_missions()[0]
            steps = storage.get_mission_steps(row['id'])
            check(steps[-1]['kind'] == 'ask' and steps[-1]['name'] == 'handoff', f"Not these hands off: {steps[-1]}")
            page.wait_for_timeout(1200)
            tl = page.locator('#missions details[open]').first.inner_text()
            check('Finish it on your phone' in tl and page.locator('#missions details[open] a[href^="https://bodewell.com"]').count() >= 1, "the hand-off shows its link")
            check(not b.errors, f"script errors: {b.errors}")
    finally:
        served.stop()


if __name__ == '__main__':
    main()
    print('PASS test_browse_page_live')
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_browse_page_live.py`
Expected: FAIL at "the browse step shows its outcome" or the screenshot check.

- [ ] **Step 3: The transcript** — in `templates/components/mission_transcript.html`, after the `ask` branch:

```html
                                            <!-- browse: the runner's report, its outcome and its last screenshot -->
                                            <template x-if="step.kind === 'browse'">
                                                <div class="mt-1">
                                                    <div class="text-xs text-gray-400" x-text="'Browsed ' + (step.name || '') + ' — ' + ((step.result_json || {}).outcome || 'running…')"></div>
                                                    <div class="text-sm text-gray-200 mt-0.5 whitespace-pre-wrap" x-text="(step.result_json || {}).text || ''"></div>
                                                    <div class="text-[11px] text-gray-500 mt-0.5" x-show="(step.result_json || {}).stopped_at" x-text="'Stopped at ' + ((step.result_json || {}).stopped_at || '')"></div>
                                                    <template x-if="((step.result_json || {}).screenshots || []).length">
                                                        <img class="browse-shot rounded-lg border border-gray-800 mt-1 max-h-48"
                                                             :src="apiBase + 'api/missions/' + mission.id + '/shots/' + ((step.result_json || {}).screenshots || []).slice(-1)[0]" alt="">
                                                    </template>
                                                </div>
                                            </template>
                                            <template x-if="step.kind === 'ask' && step.name === 'release'">
                                                <div class="mt-1 bg-amber-500/10 border border-amber-500/30 rounded-xl p-2">
                                                    <div class="text-sm text-amber-200" x-text="(step.result_json || {}).question || ''"></div>
                                                    <div class="text-[11px] text-gray-400 mt-0.5" x-text="'Fields: ' + ((step.result_json || {}).fields || []).join(', ')"></div>
                                                    <div class="flex flex-wrap gap-2 mt-1.5" x-show="mission.status === 'waiting_user' && isLastAsk(step)">
                                                        <button @click="releaseMission(mission, 'approve')" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white">Share</button>
                                                        <button @click="releaseMission(mission, 'decline')" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Not these</button>
                                                        <button @click="releaseMission(mission, 'stop')" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Stop</button>
                                                    </div>
                                                </div>
                                            </template>
                                            <template x-if="step.kind === 'ask' && step.name === 'handoff'">
                                                <div class="mt-1 text-sm text-amber-200">
                                                    <span x-text="(step.result_json || {}).question || ''"></span>
                                                    <a :href="(step.result_json || {}).url" target="_blank" rel="noopener" class="text-blue-400 underline underline-offset-2 ml-1">Open it</a>
                                                </div>
                                            </template>
                                            <template x-if="step.kind === 'note' && step.name === 'release_approved'">
                                                <div class="text-xs text-gray-400 italic mt-1" x-text="'Shared with ' + ((step.result_json || {}).site || '') + '.'"></div>
                                            </template>
```

Update the `ask` branch to `step.kind === 'ask' && !['release', 'handoff'].includes(step.name)` so a release is not also shown as "Argyle asks". Update the fall-through JSON line's exclusion list to skip `browse` and the new notes. In the page script (`missions_page.html`), add:

```javascript
                isLastAsk(step) { const asks = (this.active || []).flatMap(m => m.steps.filter(s => s.kind === 'ask')); return asks.length && asks[asks.length - 1].id === step.id; },
                async releaseMission(m, decision) {
                    try {
                        const r = await fetch(this.apiBase + `api/missions/${m.id}/release`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ decision }) });
                        const d = await r.json().catch(() => ({}));
                        if (!r.ok) { showGlobalAlert(d.detail || "That didn't work."); return; }
                        if (d.message) showGlobalAlert(d.message);
                        await this.load();
                    } catch (e) { showGlobalAlert("That didn't work."); }
                },
```

Match the page's real state names (`active`, `load`) by reading the component first; if the transcript is included in two scopes (active and history), `isLastAsk` must work in both (compute from `mission.steps` directly: `mission.steps.filter(s => s.kind === 'ask').slice(-1)[0]?.id === step.id`). The `<img :src>` must carry the token on admin pages where the fetch wrapper cannot help (`chfAuthUrl`); mirror the v2.499.323 rule. Run `..\venv\Scripts\python.exe tools\build_tailwind.py`.

- [ ] **Step 4: Run the live test and related**

Run: `..\venv\Scripts\python.exe tests\test_browse_page_live.py` then `..\venv\Scripts\python.exe tools\test.py missions_page_live missions_endpoints template_js tailwind_build`
Expected: PASS; `test_missions_endpoints` markup contracts hold (`mission_transcript.html` included exactly twice; no `alert(`).

- [ ] **Step 5: Commit**

```bash
git add templates/components/mission_transcript.html templates/components/missions_page.html static/tailwind.css static/tailwind-app.css tests/test_browse_page_live.py config.yaml
git commit -m "feat(missions): the transcript shows a browse with its screenshot, a release with Share / Not these / Stop, and a hand-off with its link (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

### Task 7: The image, the smoke test, docs

**Files:**
- Modify: `Dockerfile`, `requirements.txt` (already has the two packages from Task 2)
- Create: `tests/test_browse_smoke_real.py` (env-gated)
- Modify: `system_capabilities.md`, `docs/roadmap.md`, memory `browse-missions-arc.md`

- [ ] **Step 1: Dockerfile**

```dockerfile
FROM python:3.11-slim

ENV LANG C.UTF-8

# ffmpeg: moment clips transcode to H.264 720p mp4 on upload — phones record
# HEVC .mov that Chrome-based wall panels cannot decode, and raw uploads are
# 10x the size. (services/storage.py falls back to store-as-is without it.)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chromium for browse missions (services/browse.py). Headless only; the
# runner refuses honestly when this is missing, so a failed install here
# degrades to "no browser on this box", never a crash.
RUN python -m playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN chmod a+x /app/run.sh

CMD [ "/app/run.sh" ]
```

A structural check in `tests/test_browse_settings.py`: `check('playwright install --with-deps chromium' in open('Dockerfile').read(), "the image ships Chromium")`.

- [ ] **Step 2: The smoke test** — `tests/test_browse_smoke_real.py`:

```python
"""Opt-in only: CHF_BROWSE_SMOKE=1 runs the real runner against the real
Bodewell flow with NO released values and consent off. It must reach the
guest form and stop with needs_release naming the contact fields. Spends
real money (a few cents). Never in the gate."""
import os
import sys
import tempfile

if os.environ.get('CHF_BROWSE_SMOKE') != '1':
    print('SKIP test_browse_smoke_real (set CHF_BROWSE_SMOKE=1)'); sys.exit(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services import storage, browse  # noqa: E402

key = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'gemini_paid_api_key.txt')).read().strip()
storage.get_settings = lambda: {'llm_gemini_paid_api_key': key, 'missions_captcha_attempts': False}
r = browse.run("Find the online scheduling flow for an in-home dishwasher repair (Cafe CDT805P2N3S1) and learn the earliest "
               "appointment windows and the service-call fee. Enter nothing personal.", 'geappliances.com', {}, {'captcha': False},
               start_url='https://www.geappliances.com/service', out_dir=tempfile.mkdtemp(prefix='browse_smoke_'))
print(r['outcome'], r['turns'], r['tokens_in'], r['tokens_out'], r['seconds'], r['stopped_at'])
print(r['text'][:800])
assert r['outcome'] in ('needs_release', 'captcha_failed'), r
assert 'bodewell.com' in r['stopped_at'], r
print('PASS test_browse_smoke_real')
```

Make sure `tools/test.py` skips it in sweeps (it exits 0 with SKIP when the env var is unset; confirm the runner treats exit 0 as pass).

- [ ] **Step 3: Docs**

`system_capabilities.md`: bump "Current through" and add an entry at the top in house style covering: the contact card and its release (one card per site per mission, the exact values, approve/decline/stop), the runner and its guards (domain with learned redirects, submit by words not by type, payment, personal data, release detection by page scan, consented capped CAPTCHA, turn/time caps, memory floor, missing binary), pool `cu` on the paid key with `mission_cap_browse_turns`, the `browsing` status and the tick's reclaim, the hand-off DM, the screenshots route, the transcript's new branches, the Dockerfile change, the Interactions API finding (Appendix A), "Not device-verified". `docs/roadmap.md`: one line. Memory `browse-missions-arc.md`: build 2 shipped, versions, NOT device-verified, build 3 next.

- [ ] **Step 4: Run the gate**

Run: `..\venv\Scripts\python.exe tools\test.py browse missions settings_registry situation agent_v2_bridge tailwind_build`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile tests/test_browse_smoke_real.py tests/test_browse_settings.py system_capabilities.md docs/roadmap.md config.yaml
git commit -m "feat(browse): Chromium in the add-on image, the opt-in real-site smoke test, and the build-2 capabilities entry (vX.Y.Z)" -m "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git push
```

---

## Self-review notes

- **Spec coverage.** §1: contact card (T1), release card with exact values, per site per mission, approve/decline/stop (T4–T6), never a payment field (T2). §2: runner contract and report (T2), every guard with its test (T2), CAPTCHA policy with consent and cap (T2), hand-off DM and `waiting_user` (T4), resume from `stopped_at` with released fields (T5), pool `cu` on the paid key and the turn cap (T3–T4), what the planner sees (T4: the report is the step's result, compacted by `_user_prompt`), the image (T7), the runner's fixed prompt and the planner's rules (T2, T4). §5: settings (T1), screenshots under the data dir with a gated route (T4), transcript surfaces (T6), tests, the smoke test (T7).
- **Deviation from the spec, deliberate:** the release and hand-off are `ask` steps with names rather than new step kinds, so the existing `waiting_user`, answer box, DM and card paths carry them with one new verb (`release`). The situation card shows the hand-off through the `answer` verb (the question carries the link).
- **Not covered by a test here:** the resume path when the page no longer holds the form (spec: restart the goal once). The runner always starts at `start_url`; if the page is gone the model navigates itself. Ledger it as a known simplification.
- **Review Focus** 1–5 pinned in T2 (three), T4, T5.
