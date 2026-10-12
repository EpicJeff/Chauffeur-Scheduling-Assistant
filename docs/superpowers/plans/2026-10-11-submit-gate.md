# Submit Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A browse may book an appointment or submit a form, once, on a parent's tap, with the exact transaction re-checked at the press, every attempt on the record, and payment still a wall.

**Architecture:** The runner (`services/browse.py`) classifies every press by evidence, stops at a commitment with a `needs_submit` report carrying a complete DOM snapshot of the control's scope, and, when re-run with `approved`, presses exactly once only after the snapshot still matches and the mission engine's `on_attempt` authorizes under the lock. The mission engine (`services/missions.py`) turns `needs_submit` into a `submit` ask whose options carry the ask's id, records every attempt as a `submit_attempt` note with its own outcome, hands an unresolved attempt to a `verify` ask a parent resolves by tap, and lets only the mission's newest browse step move the mission. Situations, the API, the transcript template and a settings switch carry the taps.

**Tech Stack:** Python 3 (FastAPI, TinyDB-shaped storage over SQLite), Playwright (real Chromium in `test_browse_runner.py`), Alpine templates, the repo's scenario-style tests (`tests/*.py`, each a `SCENARIOS` list run by `python tests/<file>.py` from `chauffeur/`).

**Spec:** `docs/superpowers/specs/2026-10-11-submit-gate-design.md` (read it first; every rule below cites it).

## Global Constraints

- Tests run from `E:\repositories\Chauffeur\chauffeur` as `python tests/test_browse_runner.py` etc. (no pytest). Run ONLY the tests named in each task (memory rule: never the full sweep). Unset `HA_BASE_URL` first (`$env:HA_BASE_URL = ''`).
- `browse.py` never names the paid key (`llm_gemini_paid_api_key` must not appear in it); `missions.py` never names the mailer. Existing pins.
- Every change: bump `chauffeur/config.yaml` version, commit `"... (vX.Y.Z)"`, push. Commit messages via a file and `git commit -F` (PowerShell splits quotes). No `"` in messages. The version numbers written in this plan's commit messages are indicative: use the next number after the one in `config.yaml` at commit time.
- No browser dialogs in templates: `showGlobalAlert` only.
- `STOP_WORDS` is removed; nothing may import it afterwards (grep).
- `missions_submit_enabled` defaults ON (absent key = on): read as `settings.get('missions_submit_enabled', True)`.
- The device-verified sequence must keep running without a stop: contact form, "Next: Select Appliance" (`type=submit`), the "Dishwasher" tile, slot, then "Book appointment" asks. `scenario_submit_stop_by_words_not_by_type` and `scenario_enter_never_submits_a_booking_form` change meaning (a Book/Confirm press is now `needs_submit`, not `blocked`) and are updated, never deleted.
- Approval ids: `submit:<ask_id>:approve|decline|stop`, `verify:<verify_ask_id>:confirmed|failed|unsure`, `release:<ask_id>:approve|decline|stop`. A request with no `ask_id` is refused with `moved`, never defaulted.
- New template classes need `python tools/build_tailwind.py` (Tailwind is precompiled).

## Review Focus

1. **A control whose text is empty (an icon button with only an SVG).** `button` reads `''`; the gate must fall back to `aria-label`, then `title`, and a control with no text at all and final-action evidence still asks, with the question naming "an unlabeled button". Pinned in Task 3.
2. **A form inside an iframe (a third-party scheduling widget).** `elementFromPoint` in the main frame returns the `iframe` element; the scope is then the iframe element itself with empty text. The gate must treat an `IFRAME` under the point as "cannot classify": the press runs as today only if the model's intent has no `SUBMIT_WORDS`; the intent check still applies. Pinned in Task 3.
3. **A disabled control under the point.** A disabled Book button is not a commitment (nothing happens); the classification must skip `disabled` controls and let the click through so the model sees nothing changed. Pinned in Task 3.
4. **A scope whose text carries the current time ("Today 3:41 PM").** The approved press re-asks with `changed: ['text: changed']` every time; the spec accepts that (the correct answer when in doubt) but the question must say so plainly, and the re-ask must be a NEW ask id. Pinned in Task 5.
5. **A verify ask answered while the browse that caused it is still `browsing`.** Impossible by construction (the verify ask is written after the report), but a late approval of a `submit` ask whose mission is `browsing` for a different browse must answer `moved`, not resume a second worker. Pinned in Task 6.

---

### Task 1: Fixture pages and the counting endpoint

**Files:**
- Modify: `chauffeur/tests/browse_pages.py`

**Interfaces:**
- Produces: pages `/booking`, `/booking2`, `/sendapp`, `/agree`, `/cookie`, `/lockin`, `/tiles`, `/longform`, `/pricedcontinue`, `/thanks`, `/rejected`, `/payafter`, `/buynow`, `/iconbtn`, `/framed`, `/disabledbook`, `/fulltrip` and a `POST /booked` endpoint that counts hits in `H.posts` (a list of paths) and returns `/thanks`; `GET /posts` returns the count as text.

- [ ] **Step 1: Add the pages**

Add to `PAGES` in `chauffeur/tests/browse_pages.py`:

```python
    # --- submit gate fixtures (spec 2026-10-11) ---
    # A booking form: slot radios, a price line, Book appointment (type=submit, POSTs to /booked), Pay now.
    '/booking': ('<h1>Choose a slot</h1><form id="bf" action="/booked" method="post">'
                 '<p>Trip charge $114.95. Parts and labor not included.</p>'
                 '<label><input type="radio" name="slot" value="tue" checked> Tue, Oct 20 8AM-12PM</label>'
                 '<label><input type="radio" name="slot" value="thu"> Thu, Oct 22 8AM-12PM</label>'
                 '<label>Notes<input name="notes" value=""></label>'
                 '<button type="submit" id="book">Book appointment</button>'
                 '<button type="button" id="pay">Pay now</button></form>'),
    # The same form with Thursday checked and the price moved: the "page changed" fixture.
    '/booking2': ('<h1>Choose a slot</h1><form id="bf" action="/booked" method="post">'
                  '<p>Trip charge $124.95. Parts and labor not included.</p>'
                  '<label><input type="radio" name="slot" value="tue"> Tue, Oct 20 8AM-12PM</label>'
                  '<label><input type="radio" name="slot" value="thu" checked> Thu, Oct 22 8AM-12PM</label>'
                  '<label>Notes<input name="notes" value=""></label>'
                  '<button type="submit" id="book">Book appointment</button></form>'),
    # An unfamiliar final label on a form holding the person's data.
    '/sendapp': ('<h1>Application</h1><form action="/booked" method="post"><label>Zip *<input name="zip" value="27519"></label>'
                 '<button type="submit" id="send">Send application</button></form>'),
    # An agreement form whose submit control reads Accept: commitment text in the scope.
    '/agree': ('<h1>Terms</h1><form action="/booked" method="post"><p>By clicking Accept you authorize the service visit. I agree to the terms.</p>'
               '<label><input type="checkbox" name="ok" checked> I agree</label><button type="submit" id="accept">Accept</button></form>'),
    # A cookie banner: Accept as a type=button outside any form, no state in its scope.
    '/cookie': ('<h1>Welcome</h1><div role="dialog"><p>We use cookies.</p><button type="button" id="accept">Accept</button></div>'
                '<p>Page content. <a href="/start">Service</a></p>'),
    # A JS button outside any form beside a custom aria-checked slot picker: the only button in its scope.
    '/lockin': ('<h1>Pick a slot</h1><section id="picker"><p>Trip charge $114.95</p>'
                '<div role="radiogroup"><div role="radio" aria-checked="false" id="s1">Tue, Oct 20 8AM-12PM</div>'
                '<div role="radio" aria-checked="true" id="s2">Thu, Oct 22 8AM-12PM</div></div>'
                '<div role="button" id="lock" tabindex="0">Lock it in</div></section>'
                '<script>document.getElementById("lock").addEventListener("click", () => { location.href = "/thanks"; });</script>'),
    # The appliance-tile form the device run saw: eight sibling buttons inside a form with filled fields.
    '/tiles': ('<h1>Select appliance</h1><form action="/slots" method="get"><input type="hidden" name="first" value="Jeff">'
               '<label>Zip<input name="zip" value="27519"></label><div class="tiles">'
               + ''.join(f'<button type="submit" name="appliance" value="{a}" id="t{i}">{a}</button>'
                         for i, a in enumerate(['Refrigerator', 'Dishwasher', 'Range', 'Oven', 'Washer', 'Dryer', 'Microwave', 'Other']))
               + '</div></form>'),
    '/slots': '<h1>Slots</h1><a id="tobook" href="/booking">Choose a slot</a>',
    # A long form whose price line sits past 1,500 characters of text.
    '/longform': ('<h1>Review</h1><form action="/booked" method="post"><p>' + 'Lots of copy about the visit. ' * 70
                  + '</p><p>Total due at visit: $114.95</p><label><input type="radio" name="slot" value="tue" checked> Tue</label>'
                  '<button type="submit" id="book">Book appointment</button></form>'),
    # Continue as the last button under a total: a review-and-commit shape.
    '/pricedcontinue': ('<h1>Review your request</h1><form action="/booked" method="post"><p>Total: $114.95</p>'
                        '<label><input type="radio" name="slot" value="tue" checked> Tue</label><button type="submit" id="cont">Continue</button></form>'),
    # A multi-step Continue on a slot page with no price: runs.
    '/stepcontinue': ('<h1>Step 2 of 3</h1><form action="/booking" method="get"><label><input type="radio" name="slot" value="tue" checked> Tue</label>'
                      '<button type="submit" id="cont">Continue</button></form>'),
    '/thanks': '<h1>Thank you for your booking</h1><p>Confirmation number 12345. Tue, Oct 20 8AM-12PM.</p>',
    '/rejected': '<h1>Sorry</h1><p class="error">That slot was just taken. Pick another.</p><a href="/booking">Back</a>',
    # A payment page after the press.
    '/payafter': '<h1>Payment</h1><form><input name="cardnumber" autocomplete="cc-number"><input name="cvc" placeholder="CVC"><button type="submit">Pay now</button></form>',
    # A saved-card Buy now: no card field, pay word on the control.
    '/buynow': '<h1>Order</h1><form action="/booked" method="post"><p>Card ending 4242</p><button type="submit" id="buy">Buy now</button></form>',
    # An icon-only submit control (aria-label only).
    '/iconbtn': ('<h1>Request</h1><form action="/booked" method="post"><label>Zip<input name="zip" value="27519"></label>'
                 '<button type="submit" id="icon" aria-label="Submit request"><svg width="16" height="16"></svg></button></form>'),
    # A disabled Book button: nothing happens on a click.
    '/disabledbook': ('<h1>Choose a slot</h1><form action="/booked" method="post"><p>$114.95</p>'
                      '<button type="submit" id="book" disabled>Book appointment</button></form>'),
    # A third-party widget in an iframe.
    '/framedbook': '<h1>Schedule</h1><iframe id="w" src="/booking" style="width:600px;height:400px"></iframe>',
    # The device sequence, start to finish: contact form -> tiles -> slots -> booking.
    '/fulltrip': ('<h1>Step 1</h1><form action="/tiles" method="get">'
                  '<label>First Name *<input name="first" required></label>'
                  '<label>Email *<input name="email" type="email" required></label>'
                  '<label>Zip *<input name="zip" required></label>'
                  '<button type="submit" id="next">Next: Select Appliance</button></form>'),
```

- [ ] **Step 2: Add the counting POST endpoint**

In class `H`, add `posts = []` beside `port = 0`, and:

```python
    def do_POST(self):
        path = self.path.split('?')[0]
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        if path == '/booked':
            H.posts.append(path)
            self.send_response(303)
            self.send_header('Location', '/thanks' if len(H.posts) % 7 != 0 else '/rejected')
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()
```

Then in `do_GET`, before the `PAGES` lookup, add:

```python
        if path == '/posts':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(str(len(H.posts)).encode())
            return
```

(The `% 7` redirect to `/rejected` is never reached by a test that resets `H.posts` first; tests that want a rejection navigate to `/rejected` directly. Keep `/booked` → `/thanks` for every test by calling `browse_pages.H.posts.clear()` in `_reset`.)

- [ ] **Step 3: Verify the server serves them**

Run from `chauffeur/`:

```powershell
python -c "import sys; sys.path.insert(0,'tests'); from browse_pages import serve, H; import urllib.request as u; s,p=serve(); print(u.urlopen(f'http://127.0.0.1:{p}/booking').read()[:60]); r=u.urlopen(u.Request(f'http://127.0.0.1:{p}/booked', data=b'slot=tue', method='POST')); print(r.geturl(), u.urlopen(f'http://127.0.0.1:{p}/posts').read())"
```

Expected: the booking HTML head, then `http://127.0.0.1:<port>/thanks b'1'`.

- [ ] **Step 4: Commit**

```
test(browse): fixture pages for the submit gate - booking form with slot radios and price, Pay now, Send application, agreement Accept, cookie Accept, Lock it in beside an aria-checked picker, appliance tiles, long form, priced Continue, thanks and rejected pages, a counting POST endpoint (v2.499.384)
```

---

### Task 2: Word lists, scope, snapshot and classification helpers

**Files:**
- Modify: `chauffeur/services/browse.py:42` (replace `STOP_WORDS`), add helpers after `_under_click` (`:458-463`)
- Test: `chauffeur/tests/test_browse_runner.py`

**Interfaces:**
- Produces:
  - `SUBMIT_WORDS`, `PAY_WORDS`, `STEP_WORDS`, `NAVIGATION_WORDS`, `COMMIT_CONTEXT`, `CONFIRMATION_MARKERS`, `MONEY` (compiled regexes).
  - `_control_at(page, x, y) -> dict | None` and `_focused_control(page) -> dict | None` and `_control_by_text(page, text) -> dict | None`: each returns `{'text', 'type', 'tag', 'disabled': bool, 'iframe': bool, 'sole_submit': bool, 'only_button': bool, 'last_button': bool, 'is_submit_control': bool, 'state': {...}, 'handle': <JSHandle>}` or `None` when nothing is under the point.
  - `_snapshot_of(control: dict) -> dict`: `{'fields': {}, 'selected': [], 'text': '', 'text_sha': '', 'prices': []}` (the `state` key above, already filled by the JS; this just returns it).
  - `_classify(control: dict | None, intent: str) -> str`: `'pay'`, `'submit'` or `'run'`.
  - `_display(text: str) -> str` (first 300 chars).
  - `_is_confirmation(scan: dict) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `chauffeur/tests/test_browse_runner.py` (before `SCENARIOS`) and add each name to `SCENARIOS`:

```python
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


def scenario_classification_is_by_evidence_not_label():
    cases = [('/booking', '#book', '', 'submit'), ('/booking', '#pay', '', 'pay'), ('/buynow', '#buy', '', 'pay'),
             ('/sendapp', '#send', '', 'submit'), ('/agree', '#accept', '', 'submit'), ('/cookie', '#accept', '', 'run'),
             ('/lockin', '#lock', '', 'submit'), ('/tiles', '#t1', '', 'run'), ('/pricedcontinue', '#cont', '', 'submit'),
             ('/stepcontinue', '#cont', '', 'run'), ('/form', '#next', '', 'run'), ('/iconbtn', '#icon', '', 'submit'),
             ('/disabledbook', '#book', '', 'run'), ('/framedbook', '#w', '', 'run'), ('/framedbook', '#w', 'book the slot', 'submit'),
             ('/tiles', '#t1', 'confirm the booking', 'submit'), ('/cookie', '#accept', 'pay for it', 'pay')]
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
```

- [ ] **Step 2: Run to verify they fail**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_runner.py 2>&1 | Select-String "FAIL|passed"
```

Expected: the three new scenarios FAIL (`AttributeError: ... has no attribute 'SUBMIT_WORDS'`), the rest unchanged.

- [ ] **Step 3: Replace `STOP_WORDS` with the lists**

In `chauffeur/services/browse.py`, replace line 42 (`STOP_WORDS = ...`) with:

```python
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
```

Then update the module docstring line 4 from "This module never books, pays, submits or sends." to "This module never pays; it books or submits only one approved press at a time (spec 2026-10-11)."

- [ ] **Step 4: Add the control reader, the snapshot and the classifier**

After `_under_click` (keep it; `_action_words` uses it), add:

```python
_CONTROL_JS = """
(target) => {
  const sha = async (s) => {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s));
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
  };
  const label = (el) => ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '')).replace(/\\s+/g, ' ').trim().slice(0, 120);
  const isBtn = (el) => el.matches('button, input[type=submit], input[type=button], [role=button]');
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
  return sha(text).then(h => ({
    text: label(b), type: (b.getAttribute('type') || ''), tag: b.tagName, disabled: !!b.disabled, iframe: false,
    is_submit_control: !!form && (submits.includes(b) || (buttons.length === 1 && buttons[0] === b)),
    sole_submit: !!form && submits.length === 1 && submits[0] === b,
    only_button: buttons.length === 1 && buttons[0] === b,
    last_button: buttons.length > 0 && buttons.length <= 3 && buttons[buttons.length - 1] === b,
    state: {fields, selected, text, text_sha: h, prices},
  }));
}
"""


def _control_at(page, x, y):
    """The control under a point and the state of its scope (spec §1), or
    None when nothing pressable is there. `x, y` are page pixels."""
    try:
        h = page.evaluate_handle("([x, y]) => document.elementFromPoint(x, y)", [x, y])
        c = page.evaluate(_CONTROL_JS, h)
        if c:
            c['handle'] = h
        return c
    except Exception:
        return None


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
        c = page.evaluate(_CONTROL_JS, h)
        if c:
            c['handle'] = h
        return c
    except Exception:
        return None


def _control_by_text(page, text: str):
    """The model's SUBMIT: <text> resolved to a control: exact after whitespace
    collapsing, else the one control whose text contains it. None when none or many."""
    want = ' '.join((text or '').split()).lower()
    if not want:
        return None
    try:
        h = page.evaluate_handle("""(want) => {
            const all = [...document.querySelectorAll('button, input[type=submit], input[type=button], a, [role=button]')].filter(b => !b.disabled);
            const lab = (b) => ((b.innerText || b.value || b.getAttribute('aria-label') || b.getAttribute('title') || '')).replace(/\\s+/g, ' ').trim().toLowerCase();
            const exact = all.filter(b => lab(b) === want); if (exact.length === 1) return exact[0];
            const part = all.filter(b => lab(b).includes(want)); return part.length === 1 ? part[0] : null;
        }""", want)
        c = page.evaluate(_CONTROL_JS, h)
        if c:
            c['handle'] = h
        return c
    except Exception:
        return None


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
    if control and not control.get('iframe') and not control.get('disabled'):
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
```

Also replace the body of `_enter_target` to keep its callers working (it is used by Task 3 only through `_focused_control`; leave `_enter_target` in place unchanged).

- [ ] **Step 5: Run the three scenarios and the two existing guard scenarios**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_runner.py 2>&1 | Select-String "FAIL|passed"
```

Expected: the three new scenarios PASS. `scenario_submit_stop_by_words_not_by_type` and `scenario_enter_never_submits_a_booking_form` now FAIL with `NameError: STOP_WORDS` inside `run()`; that is Task 3's work. Nothing else fails.

- [ ] **Step 6: Commit**

```
feat(browse): the word lists split (SUBMIT_WORDS, PAY_WORDS, STEP_WORDS, COMMIT_CONTEXT, CONFIRMATION_MARKERS), a control record reads its scope (fields, selections incl. aria-checked, whole text, sha, prices), classification by evidence of a final action not by label (v2.499.385)
```

---

### Task 3: The gate in `run()`: `needs_submit`, the submit record, `SUBMIT:`, the switch

**Files:**
- Modify: `chauffeur/services/browse.py` (`OUTCOMES` `:37`, `RUNNER_SYSTEM` `:57-73`, `run()` `:650-889`)
- Test: `chauffeur/tests/test_browse_runner.py`

**Interfaces:**
- Consumes: Task 2's `_control_at`, `_focused_control`, `_control_by_text`, `_classify`, `_display`, `SUBMIT_WORDS`, `PAY_WORDS`.
- Produces: `run(goal, site, released, consent, caps=None, start_url=None, out_dir=None, approved=None, on_attempt=None) -> dict` (the two new keyword args are accepted here and used in Task 4). New outcome `needs_submit`; the report gains `submit` (the record), `attempt` (None) and `changed` (list). `SUBMIT_LINE = re.compile(r'SUBMIT:\s*(.+)$', re.I | re.M)`. Helper `_submit_record(page, control, intent, learned) -> dict`. `_system_text(settings) -> str`. The setting read `settings.get('missions_submit_enabled', True)`.

- [ ] **Step 1: Write the failing tests**

Replace `_reset` and the bodies of the two existing scenarios named below (their meaning changed: a Book or Confirm press is now a question, not a wall), and append the four new scenarios. Register the new names in `SCENARIOS`.

```python
def _reset(consent=False, cap_turns=40, submit=True):
    storage.get_settings = lambda: {**{f'contact_{k}': v for k, v in CARD.items()}, 'missions_captcha_attempts': consent,
                                    'llm_gemini_paid_api_key': 'paid', 'missions_submit_enabled': submit}
    browse.free_memory_mb = lambda: 4096
    from browse_pages import H
    H.posts.clear()


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
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': 500, 'y': 100, 'intent': 'submit the booking'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/form2', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == '' and r['submit']['intent'] == 'submit the booking', f"a submit intent on a blank spot asks by intent: {r.get('submit')}")


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
    browse._model_step = _script([{'name': 'key_combination', 'args': {'keys': ['Tab']}}, {'name': 'key_combination', 'args': {'keys': ['Tab']}},
                                  {'name': 'key_combination', 'args': {'keys': ['Tab']}}, {'name': 'key_combination', 'args': {'keys': ['Space']}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment', f"Space on the focused Book asks: {r['outcome']} {(r.get('submit') or {}).get('button')}")
    # The model's own exit: SUBMIT: <text>.
    browse._model_step = _script('I see the slot. LEARNED: slot=Tue, Oct 20 8AM-12PM\nSUBMIT: Book appointment')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/booking', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == 'Book appointment' and r['submit']['state']['selected'] and r['submit']['facts'] == {'slot': 'Tue, Oct 20 8AM-12PM'},
          f"SUBMIT: resolves the control, reads its scope, carries the facts: {r.get('submit')}")
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
    browse._model_step = _script([{'name': 'click_at', 'args': {'x': xy[0], 'y': xy[1], 'intent': 'book the slot in the widget'}}], 'DONE.')
    r = browse.run('x', SITE, {}, {}, start_url=f'{URL}/framedbook', out_dir=OUT)
    check(r['outcome'] == 'needs_submit' and r['submit']['button'] == '', "an iframe under the point: the intent still gates")
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
```

- [ ] **Step 2: Run to verify they fail**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_runner.py 2>&1 | Select-String "FAIL|passed"
```

Expected: the six scenarios above FAIL (`NameError: STOP_WORDS` inside `run()`, or `KeyError: 'submit'`).

- [ ] **Step 3: Outcomes, the prompt and the record builder**

In `browse.py`:

```python
OUTCOMES = ('done', 'needs_release', 'needs_submit', 'submitted', 'submit_rejected', 'submit_unknown',
            'captcha_failed', 'blocked', 'refused', 'capped', 'error')
SUBMIT_LINE = re.compile(r'SUBMIT:\s*(.+)$', re.I | re.M)
SUBMIT_TEXT = (" When the only way forward is a control that books, submits, confirms, reserves, sends or applies, do NOT "
               "press it: end your report with one more line: SUBMIT: <the button's exact text>. A parent decides.")
NO_SUBMIT_TEXT = " Booking and submitting are off for this family: never press such a control; stop and report."


def _system_text(settings: dict) -> str:
    """The runner's system text with the submit exit added or withheld by the switch."""
    on = (settings or {}).get('missions_submit_enabled', True)
    return RUNNER_SYSTEM + (SUBMIT_TEXT if on else NO_SUBMIT_TEXT)
```

In `RUNNER_SYSTEM`, change "Never click anything that submits, books, confirms, pays or orders." to "Never click anything that pays or orders."

After `_classify` add:

```python
def _submit_record(page, control, intent: str, learned: dict) -> dict:
    """The thing a parent is asked to approve (spec 2026-10-11 §1): the
    control, its page, its scope's whole state, the model's facts so far."""
    st = (control or {}).get('state') or {'fields': {}, 'selected': [], 'text': '', 'text_sha': '', 'prices': []}
    return {'button': (control or {}).get('text') or '', 'url': page.url, 'state': st, 'display': _display(st.get('text') or ''),
            'facts': dict(learned or {}), 'intent': intent or ''}
```

- [ ] **Step 4: Wire the gate into `run()`**

1. Signature: `def run(goal, site, released, consent, caps=None, start_url=None, out_dir=None, approved=None, on_attempt=None) -> dict`.
2. `report` gains `'submit': None, 'attempt': None, 'changed': []`.
3. New locals: `submit_on = bool(settings.get('missions_submit_enabled', True))`, `facts = {}`, `missed_submit = 0`. After every `_model_step`, `facts.update(_learned(step.get('text') or ''))`.
4. The first prompt uses `_system_text(settings) + '\n\n' + prompt`.
5. In the no-calls branch, before the `WALL_LINE` check:

```python
                m = SUBMIT_LINE.search(text)
                if m:
                    want = m.group(1).strip()
                    if not submit_on:
                        return finish('blocked', f'would submit: the model wanted to press "{want}"')
                    ctl = _control_by_text(page, want)
                    if not ctl or not (ctl.get('state') or {}).get('text'):
                        missed_submit += 1
                        if missed_submit >= 2:
                            return finish('blocked', f"could not find the control '{want}' at {page.url}")
                        contents.append({'role': 'user', 'parts': [{'text': f"no control reads '{want}'; click it, or name its text exactly as the page shows it"}]})
                        continue
                    report['submit'] = _submit_record(page, ctl, '', facts)
                    report['stopped_at'] = page.url
                    return finish('needs_submit', ctl['text'])
```

6. Define `gate` inside `run()` (after `page_checks`), and delete both `STOP_WORDS` click checks (old lines 800-806):

```python
    def gate(control, intent, how):
        """None to run the press; a finished report otherwise (Task 4 adds the
        'PRESS' return for an approved match). `how` is the ledger word."""
        kind = _classify(control, intent)
        if kind == 'run':
            return None
        label = (control or {}).get('text') or ''
        report['stopped_at'] = page.url
        if kind == 'pay':
            return finish('blocked', f"payment ({label or intent}): a control that takes money; do it yourself here: {page.url}")
        if not submit_on:
            return finish('blocked', f'would submit: a "{label or intent}" {how}')
        if control and not control.get('iframe') and not (control.get('state') or {}).get('text'):
            return finish('blocked', f"form state unreadable at {page.url}")
        report['submit'] = _submit_record(page, control, intent, facts)
        return finish('needs_submit', label or f"the control the model meant to {intent}")
```

At the click site (replacing the old checks):

```python
                ctl = focused = None
                if name.startswith('click') or name.startswith('double'):
                    ctl = _control_at(page, *_px(args['x'], args['y'])) if 'x' in args else None
                    stop = gate(ctl, intent, 'click')
                    if stop:
                        return stop
```

7. Replace the two `_enter_target` + `STOP_WORDS` checks (old lines 835-837 and 845-848) with `focused = _focused_control(page); stop = gate(focused, intent, 'Enter'); if stop: return stop`. Add Space:

```python
def _wants_space(name: str, args: dict) -> bool:
    if name in ('key_combination', 'press_key', 'hotkey'):
        k = args.get('keys') or args.get('key') or ''
        keys = k if isinstance(k, list) else [k]
        return any(str(x).strip().lower() in ('space', ' ') for x in keys)
    return False
```

and in the non-type branch, beside `if enter:`, add `if _wants_space(name, args): focused = _focused_control(page); stop = gate(focused, intent, 'Space'); if stop: return stop`.

8. `page_checks`' payment line: `return finish('blocked', f'payment (card field): this part needs a payment card; do it yourself here: {page.url}')`. (`finish_browse` routes on `'payment' in text.lower()`, unchanged.)

9. `_enter_target` is now unused: delete it.

- [ ] **Step 5: Run the runner tests**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_runner.py 2>&1 | Select-String "FAIL|passed"
```

Expected: all PASS. If the Space case focuses the wrong control, count `/booking`'s Tab stops (radio group = one stop, notes, Book) and fix the number of Tab presses in the test.

- [ ] **Step 6: Grep the pins**

```powershell
Select-String -Path services/browse.py -Pattern "STOP_WORDS|_enter_target|llm_gemini_paid_api_key"
```

Expected: no output.

- [ ] **Step 7: Commit**

```
feat(browse): the wall becomes a question - a commitment ends the run needs_submit with the control, page and the whole scope state; pay words and card fields are blocked: payment; SUBMIT: is the model's exit; Space and Enter go through the same gate; missions_submit_enabled off restores would submit (v2.499.386)
```

---

### Task 4: The approved press: match, authorize, one activation, the outcome

**Files:**
- Modify: `chauffeur/services/browse.py` (`run()`, beside `_act` `:520-566`)
- Test: `chauffeur/tests/test_browse_runner.py`

**Interfaces:**
- Consumes: Task 3's `gate`, `_submit_record`, `facts`, `report['submit']`, `_focused_control`, `_control_at`, `_is_confirmation`.
- Produces: `approved` (the submit record plus `ask_id`) and `on_attempt(record) -> bool` honoured. Outcomes `submitted`, `submit_rejected`, `submit_unknown`. `report['attempt'] = {ask_id, button, url, state, pressed_at, outcome: 'confirmed'|'rejected'|'continued'|'unknown', text, unasked?: True}`; `report['changed']: [str]` on a re-ask. Module-level `OUTCOME_LINE`, `AFTER_PRESS_TEXT`, `_norm(s)`, `_changed(approved_state, state) -> list[str]`, `_activate(page, name, args)`.

- [ ] **Step 1: Write the failing tests**

Append and register in `SCENARIOS`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_runner.py 2>&1 | Select-String "FAIL|passed"
```

Expected: the four new scenarios FAIL (wrong outcome, `KeyError: 'attempt'`).

- [ ] **Step 3: Module-level helpers**

```python
OUTCOME_LINE = re.compile(r'^(CONFIRMED|REJECTED|CONTINUED|UNKNOWN):\s*(.*)$', re.I | re.M)
AFTER_PRESS_TEXT = (" This run carries a parent's approval for ONE press. After that approved press, read the page and end your "
                    "report with exactly one of: CONFIRMED: <what the page says, with any confirmation number>, REJECTED: <the "
                    "error the page shows>, CONTINUED: <the next step the page shows> when the press only moved the form to "
                    "another step and nothing is booked or sent yet, or UNKNOWN: <what you see>. Do not act again.")


def _system_text(settings: dict, approved: bool = False) -> str:
    on = (settings or {}).get('missions_submit_enabled', True)
    return RUNNER_SYSTEM + (SUBMIT_TEXT if on else NO_SUBMIT_TEXT) + (AFTER_PRESS_TEXT if approved and on else '')


def _norm(s) -> str:
    return ' '.join(str(s or '').split()).lower()


def _changed(approved_state: dict, state: dict) -> list:
    """What differs between the approved snapshot and the page now, in words a parent reads (spec §1)."""
    a, s = approved_state or {}, state or {}
    out = []
    if [_norm(x) for x in a.get('selected') or []] != [_norm(x) for x in s.get('selected') or []]:
        out.append(f"selected: {', '.join(s.get('selected') or []) or 'nothing'} (approved: {', '.join(a.get('selected') or []) or 'nothing'})")
    af = {k: _norm(v) for k, v in (a.get('fields') or {}).items()}
    sf = {k: _norm(v) for k, v in (s.get('fields') or {}).items()}
    if af != sf:
        names = sorted((set(af) ^ set(sf)) | {k for k in af if k in sf and af[k] != sf[k]})
        out.append(f"fields: {', '.join(names)} changed")
    ap, sp = list(a.get('prices') or []), list(s.get('prices') or [])
    if ap != sp:
        new, gone = [p for p in sp if p not in ap], [p for p in ap if p not in sp]
        out.append(f"prices: {' '.join(new) or 'none'} appears; {' '.join(gone) or 'none'} does not")
    if (a.get('text_sha') or '') != (s.get('text_sha') or ''):
        out.append('text: changed')
    return out


def _activate(page, name, args):
    """One activation for an approved commitment (spec §1): a click of any
    kind, double-click included, is one click; a key is one press."""
    if name.startswith('click') or name.startswith('double'):
        x, y = _px(args['x'], args['y'])
        page.mouse.click(x, y, click_count=1)
    elif _wants_enter(name, args):
        page.keyboard.press('Enter')
    else:
        page.keyboard.press('Space')
    page.wait_for_timeout(900)
```

(The Task 3 `_system_text(settings)` is replaced by this two-argument form; Task 3's test still passes.)

- [ ] **Step 4: Wire the approved path into `run()`**

1. At the top of `run()`: `approved = dict(approved) if approved else None`; `pressed = False`; `after_press_refusals = 0`. The first prompt uses `_system_text(settings, approved=bool(approved))`.

2. `finish()` gains a first block so no attempt is ever left without an outcome and a cap or error after the press reads as unknown:

```python
        att = report.get('attempt')
        if att and not att.get('outcome'):
            att['outcome'] = 'unknown'
            if outcome in ('capped', 'error', 'done'):
                outcome = 'submit_unknown'
```

3. A second inner helper beside `finish`:

```python
    def finish_attempt(outcome, text):
        report['attempt']['outcome'] = outcome
        report['attempt']['text'] = (text or '')[:500]
        report['stopped_at'] = page.url
        return finish({'confirmed': 'submitted', 'rejected': 'submit_rejected', 'unknown': 'submit_unknown'}[outcome], (text or '').strip() or outcome)
```

4. In `gate`, after the `kind == 'pay'` and switch checks and before the `needs_submit` return, insert the approved path:

```python
        if approved and not pressed:
            if not (approved.get('state') or {}).get('text_sha'):
                report['submit'] = _submit_record(page, control, intent, facts)
                report['changed'] = ['state: the approved record held no form state']
                return finish('needs_submit', label)
            same_btn = _norm(label) == _norm(approved.get('button'))
            same_dom = _domain(page.url) == _domain(approved.get('url') or '')
            diffs = _changed(approved.get('state'), (control or {}).get('state'))
            if same_btn and same_dom and not diffs and control and not control.get('iframe'):
                rec = {'ask_id': approved.get('ask_id'), 'button': label, 'url': page.url, 'state': control['state'],
                       'pressed_at': time.time(), 'outcome': None, 'text': ''}
                try:
                    ok = bool(on_attempt(rec)) if on_attempt else True
                except Exception as e:
                    logger.warning(f"[browse] on_attempt failed: {e}")
                    ok = False
                if not ok:
                    return finish('blocked', 'approval withdrawn: the mission moved on before the press')
                report['attempt'] = rec
                return 'PRESS'
            report['submit'] = _submit_record(page, control, intent, facts)
            report['changed'] = diffs or ([f"button: '{label}' (approved: '{approved.get('button')}')"] if not same_btn else [f"site: {page.url}"])
            return finish('needs_submit', label)
```

`gate` returns `None`, `'PRESS'` or a report. Every call site becomes:

```python
                    stop = gate(ctl, intent, 'click')
                    if stop == 'PRESS':
                        press_now = True
                    elif stop:
                        return stop
```

with `press_now = False` set at the start of each call iteration (same for the Enter and Space sites, using `focused`).

5. Refusals after the press. Right after `report['turns_log'].append(line)`:

```python
                if pressed and name not in ('scroll_document', 'scroll_at', 'scroll', 'wait_5_seconds', 'wait', 'go_back'):
                    after_press_refusals += 1
                    line['action'] += ' (refused: the press is done)'
                    if after_press_refusals >= 2:
                        return finish_attempt('unknown', 'the model kept acting after the press')
                    results.append((name, args, {'error': 'the press is done; report what the page says'}))
                    continue
```

6. The activation. In the non-type branch replace `_act(page, name, args)` with:

```python
                        if press_now:
                            _activate(page, name, args)
                            pressed = True
                            line['action'] = f"press '{report['attempt']['button']}' (approved, ask {str(report['attempt']['ask_id'])[:8]})"
                        else:
                            _act(page, name, args)
```

In the type+Enter branch, after typing with `press_enter: False` and `focused = _focused_control(page); stop = gate(focused, intent, 'Enter')`: on `'PRESS'` call `_activate(page, 'key_combination', {'keys': ['Enter']})`, set `pressed = True` and the same ledger line; on `None` press Enter as today.

7. Payment after the press: in `page_checks`, before the payment `finish`, `if report.get('attempt') and not report['attempt'].get('outcome'): report['attempt']['outcome'] = 'unknown'` (the `finish()` block above does the same; this makes it explicit).

8. The confirmation backstop. In the `if page.url != before:` block, after `page_checks`:

```python
                    if not press_now and not pressed and (name.startswith('click') or name.startswith('double') or enter or _wants_space(name, args)) and _is_confirmation(scan):
                        src = ctl if (name.startswith('click') or name.startswith('double')) else focused
                        label = (src or {}).get('text') or ''
                        report['attempt'] = {'ask_id': None, 'button': label, 'url': before, 'state': (src or {}).get('state') or {},
                                             'pressed_at': time.time(), 'outcome': 'unknown', 'text': (scan.get('text') or '')[:300], 'unasked': True}
                        report['stopped_at'] = page.url
                        return finish('submit_unknown', f"confirmation page after an ungated press of '{label}'")
```

9. The outcome. In the no-calls branch, first thing when `pressed`:

```python
                if pressed:
                    m = OUTCOME_LINE.search(text)
                    kind = m.group(1).upper() if m else 'UNKNOWN'
                    body = (m.group(2) if m else text).strip()
                    if kind == 'CONTINUED':
                        scan = _scan(page)
                        if not _is_confirmation(scan) and scan.get('fields'):
                            report['attempt']['outcome'], report['attempt']['text'] = 'continued', body[:500]
                            approved, pressed = None, False
                            report['turns_log'].append({'turn': turn, 'action': 'continued: ' + body[:80], 'url': page.url, 'model_ms': model_ms, 'act_ms': 0})
                            contents.append({'role': 'user', 'parts': [{'text': 'Noted. Carry on with the goal; a further commitment needs a new SUBMIT: line.'}]})
                            continue
                        return finish_attempt('unknown', body or 'CONTINUED could not be corroborated')
                    return finish_attempt({'CONFIRMED': 'confirmed', 'REJECTED': 'rejected'}.get(kind, 'unknown'), body)
```

(`approved = None` here needs `approved` declared `nonlocal` in no inner function; it is a local of `run()` read by `gate`, so declare `nonlocal approved, pressed` inside `gate` is NOT needed for reading; only this assignment in the loop body itself, which is `run()`'s own scope, so no `nonlocal` anywhere. `gate` reads `pressed` and `approved` as closures; make sure `gate` never assigns them.)

- [ ] **Step 5: Run the runner tests**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_runner.py 2>&1 | Select-String "FAIL|passed"
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```
feat(browse): the approved press - button, domain and the whole scope state must match or the run re-asks with changed, on_attempt authorizes before one activation (a double-click is one click), the run ends at CONFIRMED / REJECTED / UNKNOWN with the attempt in the report, CONTINUED resumes unapproved, a confirmation page after an ungated press is an unasked attempt (v2.499.387)
```

---

### Task 5: The mission engine: asks, attempts, authorization, verification, the finish

**Files:**
- Modify: `chauffeur/services/missions.py` (`start_browse` `:293-328`, `finish_browse` `:331-393`, `release` `:409-459`, `_land_finish` `:524-552`, `_system_prompt` `:127-186`, `tick` `:785-792`)
- Test: `chauffeur/tests/test_browse_mission.py`

**Interfaces:**
- Consumes: the runner's `needs_submit` / `submitted` / `submit_rejected` / `submit_unknown` reports with `submit`, `attempt`, `changed` (Tasks 3-4).
- Produces:
  - `start_browse(mission, goal, site, start_url=None, released=None, approved=None) -> str`; with `approved`, the browse step's `args_json` carries `approved_ask_id` and `approval_spent: False`, and the runner is called with `approved=` and `on_attempt=_on_attempt_for(mid, sid)`.
  - `_on_attempt_for(mission_id, step_id) -> callable(record) -> bool` (the four checks under `db_lock`, writes the `submit_attempt` note).
  - `submit_question(domain, verb, facts, button) -> str`, `_submit_verb(record, goal) -> 'book'|'submit'`.
  - `submit(mission_id, decision, actor, ask_id) -> dict` with statuses `success` / `already` / `moved` / `refused` / `error`.
  - `verify(mission_id, ask_id, outcome, actor, detail='') -> dict`.
  - `release(mission_id, decision, actor, ask_id=None)`: a missing or stale `ask_id` answers `{'status': 'success', 'moved': True, ...}` and changes nothing (Task 6 flips the callers).
  - `attempts_for(mission_id) -> list[dict]` (the `submit_attempt` notes' `result_json` plus `step_id`).
  - Step names: ask `submit`, ask `verify`, note `submit_approved`, note `submit_attempt`, note `submitted`, note `submit_rejected`, note `submit_failed`, note `late_evidence`.

- [ ] **Step 1: Write the failing tests**

Append to `test_browse_mission.py` (register in `SCENARIOS`). Add to `_reset`: `storage.get_settings` gains `'missions_submit_enabled': True`.

```python
def _submit_report(**kw):
    rec = {'button': 'Book appointment', 'url': 'https://www.bodewell.com/schedule', 'intent': 'book the Tuesday slot',
           'state': {'fields': {'notes': ''}, 'selected': ['Tue, Oct 20 8AM-12PM'], 'text': 'Trip charge $114.95 Tue, Oct 20 8AM-12PM', 'text_sha': 'a' * 64, 'prices': ['$114.95']},
           'display': 'Trip charge $114.95 Tue, Oct 20 8AM-12PM', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}}
    return _report('needs_submit', text='Book appointment', submit={**rec, **kw.pop('submit', {})}, filled={'first_name': 'Jeff'}, **kw)


def _browse_to_submit(mid):
    missions._browse = lambda **kw: _submit_report()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'book the Tuesday slot', 'site': 'bodewell.com'}
    return missions.step(storage.get_mission(mid))


def scenario_needs_submit_becomes_an_ask_the_person_can_read():
    _reset()
    mid = _mission()
    row = _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    rj = ask['result_json']
    check(row['status'] == 'waiting_user' and ask['kind'] == 'ask' and ask['name'] == 'submit', f"the submit ask: {ask}")
    check(rj['question'] == "Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95 (button 'Book appointment')?", f"the question: {rj['question']}")
    check(rj['verb'] == 'book' and rj['button'] == 'Book appointment' and rj['state']['selected'] == ['Tue, Oct 20 8AM-12PM'] and rj['filled'] == {'first_name': 'Jeff'}
          and rj['browse']['start_url'] == 'https://www.bodewell.com/schedule' and rj['browse']['site'] == 'bodewell.com' and rj['changed'] == [], f"the shape: {rj}")
    check(SENT and rj['question'] in SENT[-1] and SENT[-1].endswith('Tap Book it on the Missions page or the thread card.'), f"the DM: {SENT}")
    check(missions.submit_question('x.com', 'submit', {}, 'Send application') == "Submit at x.com with the button 'Send application'?", "no facts: the button alone")
    check(missions._submit_verb({'button': 'Reserve'}, 'get it fixed') == 'book' and missions._submit_verb({'button': 'Send application'}, 'apply for the permit') == 'submit', "the verb")


def scenario_approve_needs_the_ask_id_and_resumes_with_the_record():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    runs = []
    missions._browse = lambda **kw: runs.append(kw) or _report('submitted', text='CONFIRMED: 12345', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'confirmed', 'text': 'Confirmation number 12345'})
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id='stale')
    check(res['status'] == 'success' and res.get('moved') and not runs and storage.get_mission(mid)['status'] == 'waiting_user', f"a stale id moves nothing: {res}")
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=None)
    check(res.get('moved') and not runs, "no id is refused, not defaulted")
    check(missions.submit(mid, 'approve', {'id': 'kid', 'role': 'child'}, ask_id=ask['id'])['status'] == 'refused', "a child cannot approve")
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    check(res['status'] == 'success' and len(runs) == 1, f"approve with the right id resumes: {res}")
    kw = runs[0]
    check(kw['approved']['button'] == 'Book appointment' and kw['approved']['ask_id'] == ask['id'] and kw['start_url'] == 'https://www.bodewell.com/schedule'
          and callable(kw['on_attempt']), f"the runner got the record, the ask id, the page and on_attempt: {list(kw)}")
    steps = storage.get_mission_steps(mid)
    bstep = [s for s in steps if s['kind'] == 'browse'][-1]
    check(bstep['args_json']['approved_ask_id'] == ask['id'], "the browse step carries the approval")
    check([s['name'] for s in steps if s['kind'] == 'note' and s['name'] in ('submit_approved', 'submitted')] == ['submit_approved', 'submitted'], f"the notes: {[s['name'] for s in steps]}")
    check(storage.get_mission(mid)['status'] == 'running', "after a confirmed press the planner runs on")
    res = missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    check(res.get('already') or res.get('moved'), f"a second tap is a no-op: {res}")


def scenario_decline_hands_off_and_stop_reads_the_attempts():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    res = missions.submit(mid, 'decline', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    last = storage.get_mission_steps(mid)[-1]
    check(res['status'] == 'success' and last['kind'] == 'ask' and last['name'] == 'handoff' and "did not press 'Book appointment'" in last['result_json']['question']
          and storage.get_mission(mid)['status'] == 'waiting_user', f"decline hands off: {last['result_json']['question']}")
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions.submit(mid, 'stop', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    check(storage.get_mission(mid)['status'] == 'blocked' and 'did not book' in storage.get_mission(mid)['error'], "stop with no attempt: did not book")
    _reset()
    mid = _mission()
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': 'b1', 'button': 'Book appointment', 'url': 'https://www.bodewell.com/s',
                                                                                          'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''}})
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions.submit(mid, 'stop', {'id': 'mom', 'role': 'parent'}, ask_id=ask['id'])
    err = storage.get_mission(mid)['error']
    check('may have gone through' in err and 'did not book' not in err, f"stop over an unresolved attempt warns: {err}")


def scenario_on_attempt_authorizes_under_the_lock():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    captured = {}
    missions._browse = lambda **kw: captured.update(kw) or _report('error', text='boom')      # keep the step live; we call on_attempt by hand
    missions._browse_async = True
    missions.start_browse = missions.start_browse       # (async: the thread runs; we need the step id now)
    missions._browse_async = False
    # Drive start_browse ourselves so the mission stays `browsing` while we probe on_attempt.
    rec_ask = ask['result_json']
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': ask['id'], 'approval_spent': False}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    on_attempt = missions._on_attempt_for(mid, sid)
    rec = {'ask_id': ask['id'], 'button': 'Book appointment', 'url': 'https://www.bodewell.com/schedule', 'state': rec_ask['state'], 'pressed_at': 2.0, 'outcome': None, 'text': ''}
    check(on_attempt(rec) is True, "the first call authorizes")
    notes = missions.attempts_for(mid)
    check(len(notes) == 1 and notes[0]['outcome'] is None and notes[0]['browse_step_id'] == sid and notes[0]['ask_id'] == ask['id'], f"the attempt note: {notes}")
    bstep = [s for s in storage.get_mission_steps(mid) if s['id'] == sid][0]
    check(bstep['args_json']['approval_spent'] is True, "the approval is spent")
    check(on_attempt(rec) is False, "a second call is refused (spent)")
    # A fresh step with a fresh approval but an unresolved attempt on the mission: refused.
    sid2 = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a9', 'approval_spent': False}, 'result_json': None})
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'a9'}) is False, "an unresolved attempt bars the mission")
    storage.update_mission_step(notes[0]['step_id'], {'result_json': {**notes[0], 'outcome': 'rejected'}})
    check(missions._on_attempt_for(mid, sid)({**rec}) is False, "an older step than the newest browse is refused")
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'wrong'}) is False, "a different ask id is refused")
    check(missions._on_attempt_for(mid, sid2)({**rec, 'ask_id': 'a9'}) is True, "with the attempt resolved, the newest step and its id authorize")
    storage.update_mission(mid, {'status': 'running'})
    sid3 = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a10', 'approval_spent': False}, 'result_json': None})
    for a in missions.attempts_for(mid):
        storage.update_mission_step(a['step_id'], {'result_json': {**a, 'outcome': 'rejected'}})
    check(missions._on_attempt_for(mid, sid3)({**rec, 'ask_id': 'a10'}) is False, "a mission that is not browsing (reclaimed, cancelled) refuses")


def scenario_a_late_worker_presses_nothing_after_a_reclaim():
    """The worker ran inline up to on_attempt; the tick reclaimed the mission meanwhile."""
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a1', 'approval_spent': False}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    storage.mission_steps_table.update({'ts': time.time() - missions.BROWSE_LOST_S - 5}, storage.Query().id == sid)
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'running', "reclaimed (no attempt yet: running, as before)")
    on_attempt = missions._on_attempt_for(mid, sid)
    check(on_attempt({'ask_id': 'a1', 'button': 'Book appointment', 'url': 'u', 'state': {}, 'pressed_at': 1.0, 'outcome': None, 'text': ''}) is False, "the late worker is refused")
    check(not missions.attempts_for(mid), "and wrote no attempt")


def scenario_outcomes_after_the_press_write_the_attempt_first():
    for outcome, att, want_status, want_note in (('submitted', 'confirmed', 'running', 'submitted'), ('submit_rejected', 'rejected', 'running', 'submit_rejected'),
                                                 ('submit_unknown', 'unknown', 'waiting_user', 'verify')):
        _reset()
        mid = _mission()
        _browse_to_submit(mid)
        ask = storage.get_mission_steps(mid)[-1]
        missions._browse = lambda **kw: _report(outcome, text=f'{att}: x', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': att, 'text': 'Confirmation number 12345' if att == 'confirmed' else 'x'})
        missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
        notes = missions.attempts_for(mid)
        check(len(notes) == 1 and notes[0]['outcome'] == att, f"{outcome}: the attempt note resolved {att}: {notes}")
        steps = storage.get_mission_steps(mid)
        last = steps[-1]
        check(storage.get_mission(mid)['status'] == want_status and last['name'] == want_note, f"{outcome}: status {storage.get_mission(mid)['status']} last {last['kind']}/{last['name']}")
        if outcome == 'submitted':
            check(last['result_json']['confirmation'] == '12345' and 'Tue, Oct 20 8AM-12PM' in last['result_json']['facts'].values(), f"the submitted note: {last['result_json']}")
        if outcome == 'submit_unknown':
            rj = last['result_json']
            check(last['kind'] == 'ask' and rj['attempt_step_id'] == notes[0]['step_id'] and rj['question'].startswith("I pressed 'Book appointment' at https://www.bodewell.com/schedule and could not read")
                  and not rj['payment'] and SENT[-1].startswith("I pressed"), f"the verify ask: {rj}")
            s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
            check(s['next_step']['verb'] == 'verify' and s['next_step']['id'] == f"verify:{last['id']}:confirmed", f"the card leads with the verify: {s['next_step']}")


def scenario_an_unresolved_attempt_forces_the_verify_whatever_the_report_says():
    for outcome, text in (('error', 'boom after the press'), ('capped', 'stopped after 40 turns'), ('blocked', 'payment (card field): this part needs a payment card')):
        _reset()
        mid = _mission()
        _browse_to_submit(mid)
        ask = storage.get_mission_steps(mid)[-1]

        def fake(**kw):
            # The worker pressed (on_attempt wrote the note) and then raised or hit a wall: no attempt in the report, or one with no outcome.
            kw['on_attempt']({'ask_id': kw['approved']['ask_id'], 'button': 'Book appointment', 'url': kw['start_url'], 'state': kw['approved']['state'], 'pressed_at': 1.0, 'outcome': None, 'text': ''})
            return _report(outcome, text=text, attempt=None if outcome == 'error' else {**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown' if outcome == 'blocked' else None, 'text': ''})
        missions._browse = fake
        missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
        notes = missions.attempts_for(mid)
        last = storage.get_mission_steps(mid)[-1]
        check(notes[0]['outcome'] == 'unknown' and last['kind'] == 'ask' and last['name'] == 'verify' and storage.get_mission(mid)['status'] == 'waiting_user',
              f"{outcome}: attempt unknown, verify ask, waiting: {notes[0]['outcome']} {last['name']} {storage.get_mission(mid)['status']}")
        if outcome == 'blocked':
            check(last['result_json']['payment'] is True and 'asked for payment' in last['result_json']['question'] and 'finish it on your phone' not in last['result_json']['question'].lower(),
                  f"payment after the press asks to verify, not to finish: {last['result_json']['question']}")


def scenario_verify_resolves_the_attempt_by_tap():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': 'spinner'})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    vask = storage.get_mission_steps(mid)[-1]
    res = missions.verify(mid, 'stale', 'confirmed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='12345')
    check(res.get('moved') and missions.attempts_for(mid)[0]['outcome'] == 'unknown', f"a stale verify card resolves nothing: {res}")
    res = missions.verify(mid, vask['id'], 'unsure', {'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    check(res['status'] == 'success' and storage.get_mission(mid)['status'] == 'waiting_user' and missions.attempts_for(mid)[0]['outcome'] == 'unknown', "unsure keeps waiting")
    res = missions.verify(mid, vask['id'], 'confirmed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='confirmation 12345')
    a = missions.attempts_for(mid)[0]
    check(res['status'] == 'success' and a['outcome'] == 'confirmed' and a['resolved_by'] == {'id': 'mom', 'name': 'Mom'} and a['detail'] == 'confirmation 12345' and a['resolved_at'] > 0, f"confirmed by hand: {a}")
    last = storage.get_mission_steps(mid)[-1]
    check(last['name'] == 'submitted' and last['result_json']['by_hand'] and storage.get_mission(mid)['status'] == 'running', f"a submitted note by hand, running: {last}")
    # Failed clears the bar; a fresh approve is still required.
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    vask = storage.get_mission_steps(mid)[-1]
    missions.verify(mid, vask['id'], 'failed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='nothing in my email')
    check(missions.attempts_for(mid)[0]['outcome'] == 'failed' and storage.get_mission_steps(mid)[-1]['name'] == 'submit_failed' and storage.get_mission(mid)['status'] == 'running', "failed: resolved, running")
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'fresh', 'approval_spent': False}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    check(missions._on_attempt_for(mid, sid)({'ask_id': 'fresh', 'button': 'B', 'url': 'u', 'state': {}, 'pressed_at': 1.0, 'outcome': None, 'text': ''}) is True, "a verified failure admits a fresh approved attempt")
    check(missions.verify(mid, vask['id'], 'confirmed', {'id': 'kid', 'role': 'child'})['status'] == 'refused', "a child cannot verify")


def scenario_a_late_report_never_overwrites_a_parents_answer_and_only_the_live_browse_moves_the_mission():
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    old_browse = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'browse'][-1]
    vask = storage.get_mission_steps(mid)[-1]
    missions.verify(mid, vask['id'], 'confirmed', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, detail='12345')
    # A newer browse starts and is live.
    sid2 = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g2', 'site': 'bodewell.com'}, 'result_json': None})
    storage.update_mission(mid, {'status': 'browsing'})
    # The old worker returns late, saying unknown again.
    a0 = missions.attempts_for(mid)[0]
    missions.finish_browse(mid, old_browse['id'], _report('submit_unknown', text='late', attempt={'ask_id': ask['id'], 'button': 'Book appointment', 'url': 'u', 'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': 'late worker'}))
    a1 = missions.attempts_for(mid)[0]
    check(a1['outcome'] == 'confirmed' and a1['resolved_by'] == a0['resolved_by'] and a1['late_reports'] == [{'outcome': 'unknown', 'text': 'late worker', 'ts': a1['late_reports'][0]['ts']}],
          f"the parent's answer stands; the late report is appended: {a1}")
    steps = storage.get_mission_steps(mid)
    check(any(s['name'] == 'late_evidence' for s in steps) and storage.get_mission(mid)['status'] == 'browsing'
          and [s for s in steps if s['id'] == sid2][0]['result_json'] is None, "a late_evidence note; the newer browse untouched; status unchanged")
    check([s for s in steps if s['id'] == old_browse['id']][0]['result_json']['text'] == 'late', "the late report is on its own step")
    check(not [s for s in steps if s['kind'] == 'ask' and s['idx'] > vask['idx']], "no new ask from a late report")


def scenario_the_reclaim_marks_a_pending_attempt_unknown_and_verifies():
    _reset()
    mid = _mission()
    sid = storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {'goal': 'g', 'site': 'bodewell.com', 'approved_ask_id': 'a1', 'approval_spent': True}, 'result_json': None})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': sid, 'button': 'Book appointment', 'url': 'https://www.bodewell.com/s',
                                                                                          'state': {}, 'pressed_at': time.time(), 'outcome': None, 'text': ''}})
    storage.update_mission(mid, {'status': 'browsing'})
    storage.mission_steps_table.update({'ts': time.time() - missions.BROWSE_LOST_S - 5}, storage.Query().id == sid)
    missions.tick()
    check(storage.get_mission(mid)['status'] == 'waiting_user' and missions.attempts_for(mid)[0]['outcome'] == 'unknown'
          and storage.get_mission_steps(mid)[-1]['name'] == 'verify', f"a dead worker's attempt: unknown, verify, never running: {storage.get_mission(mid)['status']}")


def scenario_an_unasked_attempt_is_recorded_after_the_fact():
    _reset()
    mid = _mission()
    missions._browse = lambda **kw: _report('submit_unknown', text="confirmation page after an ungated press of 'Go'",
                                            attempt={'ask_id': None, 'button': 'Go', 'url': 'https://www.bodewell.com/x', 'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': 'Thank you', 'unasked': True})
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    a = missions.attempts_for(mid)
    last = storage.get_mission_steps(mid)[-1]
    check(len(a) == 1 and a[0]['unasked'] and a[0]['outcome'] == 'unknown' and a[0]['ask_id'] is None and last['name'] == 'verify' and last['result_json']['attempt_step_id'] == a[0]['step_id'],
          f"the unasked attempt and its verify ask: {a} {last['name']}")


def scenario_the_finish_says_booked_and_the_planner_knows_the_rules():
    _reset()
    from services import threads
    tid = threads.create('Dishwasher repair', owner_member_id='mom', goal='get it fixed', created_by='mom')
    mid = storage.add_mission({'goal': 'book the dishwasher repair', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(mid, {'kind': 'browse', 'name': 'bodewell.com', 'args_json': {}, 'result_json': {'outcome': 'submitted', 'text': 'x', 'turns': 3}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a1', 'browse_step_id': 'b', 'button': 'Book appointment', 'url': 'u', 'state': {},
                                                                                          'pressed_at': 1.0, 'outcome': 'confirmed', 'text': 'Confirmation number 12345'}})
    storage.add_mission_step(mid, {'kind': 'note', 'name': 'submitted', 'result_json': {'verb': 'book', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}, 'confirmation': '12345', 'text': 'Confirmation number 12345'}})
    missions._llm = lambda m, s, u, st: {'action': 'finish', 'summary': 'Booked Bodewell for Tuesday.', 'next_action': 'Be home Tue Oct 20 8-12', 'next_action_at': '2026-10-20'}
    missions.step(storage.get_mission(mid))
    t = storage.get_thread(tid)
    last = [h for h in t['history'] if h['kind'] == 'mission'][-1]
    check('Booked: Tue, Oct 20 8AM-12PM, $114.95, confirmation 12345' in SENT[-1] and 'Nothing is booked' not in SENT[-1], f"the DM: {SENT[-1]}")
    check('Booked:' in last['text'] and t['next_action_at'] == '2026-10-20', f"the thread note and the appointment as the next step: {last} {t['next_action_at']}")
    src = missions._system_prompt(__import__('datetime').datetime.now(), {'missions_submit_enabled': True})
    check('submit_attempt' in src and 'never press again' in src.lower() and 'ask the person' in src.lower(), "the planner's attempt rule")
    check('book' in missions._system_prompt(__import__('datetime').datetime.now(), {'missions_submit_enabled': False}).lower()
          and 'booking is off' in missions._system_prompt(__import__('datetime').datetime.now(), {'missions_submit_enabled': False}).lower(), "the planner is told when booking is off")
    # A re-ask leads with the change and is a new ask id.
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    missions._browse = lambda **kw: _submit_report(changed=['selected: Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM)', 'text: changed'],
                                                   submit={'state': {'fields': {}, 'selected': ['Thu, Oct 22 8AM-12PM'], 'text': 't', 'text_sha': 'b' * 64, 'prices': ['$114.95']}})
    missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id'])
    ask2 = storage.get_mission_steps(mid)[-1]
    check(ask2['kind'] == 'ask' and ask2['name'] == 'submit' and ask2['id'] != ask['id'] and ask2['result_json']['question'].startswith('The page changed: selected Thu, Oct 22 8AM-12PM (approved: Tue, Oct 20 8AM-12PM). Book at bodewell.com:'),
          f"the re-ask: {ask2['result_json']['question']}")
    check(missions.submit(mid, 'approve', {'id': 'mom', 'name': 'Mom', 'role': 'parent'}, ask_id=ask['id']).get('moved'), "the spent id answers nothing")
```

- [ ] **Step 2: Run to verify they fail**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_mission.py 2>&1 | Select-String "FAIL|passed"
```

Expected: every new scenario FAILS (`AttributeError: module 'services.missions' has no attribute 'submit'`, etc.). The existing ones pass.

- [ ] **Step 3: Attempts, the question, the verb**

In `missions.py` after `_released_for`:

```python
# --- the submit gate (spec 2026-10-11) ----------------------------------------

BOOK_WORDS = re.compile(r'(book|schedul|appointment|reserv)', re.I)
UNRESOLVED = (None, 'unknown')


def attempts_for(mission_id: str) -> list:
    """Every submit_attempt on the mission, oldest first, each with its step id."""
    out = []
    for s in storage.get_mission_steps(mission_id):
        if s.get('kind') == 'note' and s.get('name') == 'submit_attempt' and isinstance(s.get('result_json'), dict):
            out.append({**s['result_json'], 'step_id': s['id']})
    return out


def _write_attempt(step_id: str, data: dict) -> None:
    storage.update_mission_step(step_id, {'result_json': {k: v for k, v in data.items() if k != 'step_id'}})


def _submit_verb(record: dict, goal: str) -> str:
    text = ' '.join([record.get('button') or '', record.get('intent') or '', goal or ''])
    return 'book' if BOOK_WORDS.search(text) else 'submit'


def submit_question(domain: str, verb: str, facts: dict, button: str) -> str:
    """Deterministic (spec §2): '{Book|Submit} at {domain}: {facts} (button '{button}')?'"""
    lead = 'Book' if verb == 'book' else 'Submit'
    vals = [str(v) for v in (facts or {}).values() if str(v).strip()]
    if vals:
        return f"{lead} at {domain}: {', '.join(vals)} (button '{button}')?"
    return f"{lead} at {domain} with the button '{button}'?"


def _on_attempt_for(mission_id: str, step_id: str):
    """The runner's authorization and record, in one lock (spec §2): this
    browse is live, its approval is this ask and unspent, no attempt on the
    mission is unresolved; then the attempt note and the spent mark."""
    def on_attempt(record: dict) -> bool:
        with storage.db_lock:
            mission = storage.get_mission(mission_id)
            if not mission or mission.get('status') != 'browsing':
                return False
            steps = storage.get_mission_steps(mission_id)
            newest = next((s for s in reversed(steps) if s.get('kind') == 'browse'), None)
            if not newest or newest['id'] != step_id:
                return False
            args = dict(newest.get('args_json') or {})
            if not args.get('approved_ask_id') or args.get('approved_ask_id') != record.get('ask_id') or args.get('approval_spent'):
                return False
            if any(a.get('outcome') in UNRESOLVED for a in attempts_for(mission_id)):
                return False
            storage.update_mission_step(step_id, {'args_json': {**args, 'approval_spent': True}})
            storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_attempt',
                                                  'result_json': {'ask_id': record.get('ask_id'), 'browse_step_id': step_id, 'button': record.get('button'),
                                                                  'url': record.get('url'), 'state': record.get('state') or {}, 'pressed_at': record.get('pressed_at') or time.time(),
                                                                  'outcome': None, 'text': ''}})
        return True
    return on_attempt
```

(`storage.db_lock` is `threading.RLock()` (`storage.py:8`), so the locking helpers may be called inside the lock.)

- [ ] **Step 4: `start_browse` with `approved`**

Change the signature to `def start_browse(mission, goal, site, start_url=None, released=None, approved=None) -> str`. The step's `args_json` becomes `{'goal': goal, 'site': site, 'start_url': start_url, **({'approved_ask_id': approved.get('ask_id'), 'approval_spent': False} if approved else {})}`. The runner kwargs gain `approved=approved, on_attempt=_on_attempt_for(mid, sid)` (so `sid` must be computed before `kw`; move the `kw = dict(...)` line below `sid = ...`). The fallback error report in `work()` gains `'submit': None, 'attempt': None, 'changed': []`.

- [ ] **Step 5: `finish_browse`: liveness, attempts, the unresolved rule, the asks**

Rewrite `finish_browse`:

```python
def finish_browse(mission_id: str, step_id: str, report: dict) -> None:
    """The report becomes the step's result. Only the mission's LIVE browse
    (status browsing, newest browse step == this step) may move the mission;
    a late report is evidence on its own step. Attempts are resolved first,
    a parent's resolution is never overwritten, and an unresolved attempt
    forces the verify hand-off whatever the report says (spec §2)."""
    from services import browse as _b
    mission = storage.get_mission(mission_id)
    if not mission:
        return
    steps = storage.get_mission_steps(mission_id)
    step_row = next((s for s in steps if s['id'] == step_id), None)
    args = (step_row or {}).get('args_json') or {}
    site = args.get('site') or ''
    _remember_site_page(site, report)
    day = datetime.date.today().isoformat()
    with storage.db_lock:
        counts = dict(storage.get_app_state(f'mission_calls:{day}') or {})
        counts['browse_turns'] = int(counts.get('browse_turns', 0)) + int(report.get('turns') or 0)
        storage.set_app_state(f'mission_calls:{day}', counts)
        newest = next((s for s in reversed(storage.get_mission_steps(mission_id)) if s.get('kind') == 'browse'), None)
        live = (storage.get_mission(mission_id) or {}).get('status') == 'browsing' and newest and newest['id'] == step_id
    shots = [os.path.basename(p) for p in report.get('screenshots') or []]
    storage.update_mission_step(step_id, {'result_json': {**report, 'screenshots': shots}})
    _resolve_attempts(mission_id, step_id, report, live)
    if not live:
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'browse',
                                              'result_json': {'note': 'the browse finished after the mission had moved on; its report is above'}})
        return
    outcome = report.get('outcome')
    text = report.get('text') or ''
    pending = [a for a in attempts_for(mission_id) if a.get('browse_step_id') == step_id and a.get('outcome') == 'unknown']
    if pending:
        _verify_ask(mission, pending[-1], payment=(outcome == 'blocked' and 'payment' in text.lower()))
        return
    if outcome == 'needs_submit' and report.get('submit'):
        _submit_ask(mission, args, report)
        return
    if outcome == 'submitted':
        a = next((x for x in reversed(attempts_for(mission_id)) if x.get('outcome') == 'confirmed'), None) or {}
        rec = report.get('submit') or {}
        facts = dict((report.get('attempt') or {}).get('facts') or report.get('learned') or {})
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submitted',
                                              'result_json': {'verb': _submit_verb({'button': a.get('button')}, mission.get('goal')), 'facts': facts,
                                                              'confirmation': _confirmation_number(a.get('text') or text), 'text': a.get('text') or text, 'by_hand': False}})
        _close(mission_id, 'running')
        return
    if outcome == 'submit_rejected':
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_rejected', 'result_json': {'error': text}})
        _close(mission_id, 'running')
        return
    if outcome == 'needs_release':
        ...   # unchanged body from today
    if outcome == 'captcha_failed' or (outcome == 'blocked' and 'payment' in text.lower()):
        ...   # unchanged body from today
    _close(mission_id, 'running')
```

(Keep the two `...` blocks exactly as they are today; only their position moves.) The `facts` for the `submitted` note: the runner's `attempt` does not carry facts, so take them from the approved ask: `facts = dict(((_pending_submit_ask(mission_id, a.get('ask_id')) or {}).get('result_json') or {}).get('facts') or report.get('learned') or {})` where

```python
def _ask_by_id(mission_id: str, ask_id: str):
    return next((s for s in storage.get_mission_steps(mission_id) if s.get('kind') == 'ask' and s['id'] == ask_id), None)


def _confirmation_number(text: str) -> str:
    m = re.search(r'confirmation\s*(?:number|#|code|no\.?)?\s*[:#]?\s*([A-Z0-9-]{4,})', text or '', re.I)
    return m.group(1) if m else ''
```

Use `_ask_by_id` in place of `_pending_submit_ask`. The helpers:

```python
def _resolve_attempts(mission_id: str, step_id: str, report: dict, live: bool) -> None:
    """The report's attempt onto its note; a human resolution is never overwritten;
    an unasked attempt is added after the fact; a pending attempt on this step with
    nothing said about it is unknown now (nothing is left to the reclaim)."""
    rep = report.get('attempt') or None
    notes = attempts_for(mission_id)
    if rep and rep.get('unasked'):
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_attempt',
                                              'result_json': {'ask_id': None, 'browse_step_id': step_id, 'button': rep.get('button') or '', 'url': rep.get('url') or '',
                                                              'state': rep.get('state') or {}, 'pressed_at': rep.get('pressed_at') or time.time(), 'outcome': 'unknown',
                                                              'text': rep.get('text') or '', 'unasked': True}})
        return
    for a in notes:
        if a.get('browse_step_id') != step_id:
            continue
        if rep and a.get('ask_id') == rep.get('ask_id'):
            if a.get('resolved_by'):
                late = list(a.get('late_reports') or []) + [{'outcome': rep.get('outcome') or 'unknown', 'text': (rep.get('text') or '')[:300], 'ts': time.time()}]
                _write_attempt(a['step_id'], {**a, 'late_reports': late})
                if (rep.get('outcome') or 'unknown') != a.get('outcome'):
                    storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'late_evidence',
                                                          'result_json': {'note': f"the browser later reported '{(rep.get('text') or rep.get('outcome') or '')[:120]}'; {a['resolved_by'].get('name') or 'the parent'}'s answer stands"}})
            else:
                _write_attempt(a['step_id'], {**a, 'outcome': rep.get('outcome') or 'unknown', 'text': (rep.get('text') or '')[:500]})
        elif a.get('outcome') is None and live:
            _write_attempt(a['step_id'], {**a, 'outcome': 'unknown'})


def _submit_ask(mission: dict, args: dict, report: dict) -> None:
    from services import browse as _b
    rec = report['submit']
    site = args.get('site') or ''
    domain = _b._domain(rec.get('url') or f'https://{site}')
    verb = _submit_verb(rec, mission.get('goal'))
    q = submit_question(domain, verb, rec.get('facts') or {}, rec.get('button') or 'the button')
    changed = list(report.get('changed') or [])
    if changed:
        q = f"The page changed: {changed[0]}. {q}"
    storage.add_mission_step(mission['id'], {'kind': 'ask', 'name': 'submit',
                                             'result_json': {'question': q, 'verb': verb, 'site': domain, 'url': rec.get('url'), 'button': rec.get('button'), 'state': rec.get('state') or {},
                                                             'display': rec.get('display') or '', 'facts': rec.get('facts') or {}, 'intent': rec.get('intent') or '',
                                                             'filled': report.get('filled') or {}, 'changed': changed,
                                                             'browse': {'goal': args.get('goal'), 'site': site, 'start_url': rec.get('url'), 'released': _released_for(mission, site)}}})
    _close(mission['id'], 'waiting_user')
    label = 'Book it' if verb == 'book' else 'Submit it'
    _dm_person(mission, f"{q} (mission: {mission.get('goal')}). Tap {label} on the Missions page or the thread card.")


def _verify_ask(mission: dict, attempt: dict, payment: bool = False) -> None:
    url, button = attempt.get('url') or '', attempt.get('button') or 'the button'
    if payment:
        q = f"I pressed '{button}' at {url}; the page then asked for payment, which I never enter. Check whether the request went through, then tell me below."
    else:
        q = f"I pressed '{button}' at {url} and could not read whether it went through. Check your email or the site, then tell me below."
    ask = (_ask_by_id(mission['id'], attempt.get('ask_id')) or {}).get('result_json') or {}
    storage.add_mission_step(mission['id'], {'kind': 'ask', 'name': 'verify',
                                             'result_json': {'question': q, 'attempt_step_id': attempt['step_id'], 'button': button, 'url': url,
                                                             'facts': ask.get('facts') or {}, 'display': ask.get('display') or '', 'payment': bool(payment)}})
    _close(mission['id'], 'waiting_user')
    _dm_person(mission, q + " (Tap It went through / It did not go through on the Missions page or the thread card.)")
```

The DM test expects `SENT[-1].startswith("I pressed")`: keep the question first.

- [ ] **Step 6: `submit()`, `verify()`, and `release(..., ask_id)`**

```python
def _pending_ask(mission_id: str, name: str):
    steps = storage.get_mission_steps(mission_id)
    ask = next((s for s in reversed(steps) if s.get('kind') == 'ask'), None)
    return ask if ask and ask.get('name') == name else None


def submit(mission_id: str, decision: str, actor: dict, ask_id: str = None) -> dict:
    """A parent's answer to a submit ask (spec §2). The ask id IS the approval:
    a stale or missing id answers `moved` and changes nothing."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can approve a booking.'}
    mission = storage.get_mission(mission_id)
    if not mission:
        return {'status': 'error', 'message': 'No such mission.'}
    moved = {'status': 'success', 'moved': True, 'message': 'That question has moved on; look at the card again.'}
    with storage.db_lock:
        row = storage.get_mission(mission_id)
        ask = _pending_ask(mission_id, 'submit')
        if not ask or row.get('status') != 'waiting_user':
            return {'status': 'success', 'already': True, 'message': 'That was already answered.'}
        if not ask_id or ask['id'] != ask_id:
            return moved
        if decision == 'approve':
            storage.update_mission(mission_id, {'status': 'running'})
    rj = ask.get('result_json') or {}
    rec = {k: rj.get(k) for k in ('button', 'url', 'state', 'display', 'facts', 'intent')}
    if decision == 'approve':
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_approved', 'result_json': {'ask_id': ask_id, 'button': rec['button'], 'url': rec['url'], 'approved_by': actor.get('id')}})
        pending = rj.get('browse') or {}
        start_browse(storage.get_mission(mission_id), pending.get('goal') or mission.get('goal'), pending.get('site') or rj.get('site'),
                     start_url=rec['url'], released=pending.get('released'), approved={**rec, 'ask_id': ask_id})
        return {'status': 'success', 'message': ('Booking' if rj.get('verb') == 'book' else 'Submitting') + ' it now.'}
    if decision == 'decline':
        q = f"I got as far as {rec['url']}. I did not press '{rec['button']}'. Finish it yourself and tell me what you found."
        storage.add_mission_step(mission_id, {'kind': 'ask', 'name': 'handoff', 'result_json': {'question': q, 'url': rec['url'], 'filled': rj.get('filled') or {}, 'reason': 'not approved'}})
        _close(mission_id, 'waiting_user')
        _dm_person(mission, q)
        return {'status': 'success', 'message': 'Left it to you.'}
    if decision == 'stop':
        _close(mission_id, 'blocked', error=_stop_text(mission_id, rec))
        return {'status': 'success', 'message': 'Stopped.'}
    return {'status': 'error', 'message': 'approve, decline or stop'}


def _stop_text(mission_id: str, rec: dict) -> str:
    atts = attempts_for(mission_id)
    conf = next((a for a in reversed(atts) if a.get('outcome') == 'confirmed'), None)
    if conf:
        return f"stopped; the booking already made stands (confirmation {_confirmation_number(conf.get('text') or conf.get('detail') or '') or 'on record'})"
    open_ = next((a for a in reversed(atts) if a.get('outcome') in UNRESOLVED), None)
    if open_:
        return f"stopped; a press of '{open_.get('button')}' at {open_.get('url')} may have gone through: check your email or the site"
    return 'the family did not book'


def verify(mission_id: str, ask_id: str, outcome: str, actor: dict, detail: str = '') -> dict:
    """A parent resolves an attempt by tap: confirmed, failed or unsure (spec §2)."""
    if not actor or (actor.get('role') or '') not in ('parent', 'adult'):
        return {'status': 'refused', 'message': 'Only a parent or adult can answer that.'}
    mission = storage.get_mission(mission_id)
    if not mission:
        return {'status': 'error', 'message': 'No such mission.'}
    if outcome not in ('confirmed', 'failed', 'unsure'):
        return {'status': 'error', 'message': 'confirmed, failed or unsure'}
    with storage.db_lock:
        ask = _pending_ask(mission_id, 'verify')
        if not ask or not ask_id or ask['id'] != ask_id:
            return {'status': 'success', 'moved': True, 'message': 'That question has moved on; look at the card again.'}
        rj = ask.get('result_json') or {}
        att = next((a for a in attempts_for(mission_id) if a['step_id'] == rj.get('attempt_step_id')), None)
        if not att:
            return {'status': 'error', 'message': 'No attempt to resolve.'}
        if outcome == 'unsure':
            return {'status': 'success', 'message': 'Still waiting; tell me when you know.'}
        _write_attempt(att['step_id'], {**att, 'outcome': outcome, 'resolved_by': {'id': actor.get('id'), 'name': actor.get('name') or ''},
                                        'resolved_at': time.time(), 'detail': (detail or '').strip()[:300]})
    if outcome == 'confirmed':
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submitted',
                                              'result_json': {'verb': _submit_verb({'button': att.get('button')}, mission.get('goal')), 'facts': rj.get('facts') or {},
                                                              'confirmation': _confirmation_number(detail), 'text': (detail or '').strip(), 'by_hand': True,
                                                              'by': actor.get('name') or ''}})
    else:
        storage.add_mission_step(mission_id, {'kind': 'note', 'name': 'submit_failed', 'result_json': {'detail': (detail or '').strip()}})
    _close(mission_id, 'running')
    return {'status': 'success', 'message': 'Noted; carrying on.' if outcome == 'confirmed' else 'Noted; it did not go through.'}
```

`release(mission_id, decision, actor, ask_id=None)`: after the existing `ask`/status check, add `if not ask_id or ask['id'] != ask_id: return {'status': 'success', 'moved': True, 'message': 'That question has moved on; look at the card again.'}`. (Existing tests call `release` without an id and will fail here; Task 6 updates them together with the callers. Until then, make the check `if ask_id is not None and ask['id'] != ask_id` and tighten it in Task 6. Note this in the Task 6 steps.)

- [ ] **Step 7: The reclaim, the finish, the planner**

`tick()` reclaim block:

```python
    for row in storage.get_missions(status='browsing'):
        steps = storage.get_mission_steps(row['id'])
        b = next((s for s in reversed(steps) if s.get('kind') == 'browse'), None)
        if b and b.get('result_json') is None and (b.get('ts') or 0) < ts - BROWSE_LOST_S:
            storage.add_mission_step(row['id'], {'kind': 'note', 'name': 'browse',
                                                 'result_json': {'note': 'the browse was lost (no result after 10 minutes)'}})
            pending = [a for a in attempts_for(row['id']) if a.get('browse_step_id') == b['id'] and a.get('outcome') is None]
            if pending:
                for a in pending:
                    _write_attempt(a['step_id'], {**a, 'outcome': 'unknown'})
                _verify_ask(row, {**pending[-1], 'outcome': 'unknown'})
            else:
                storage.update_mission(row['id'], {'status': 'running'})
```

`_land_finish`: replace `tail = ' Nothing is booked.' if touched_site else ''` with:

```python
    booked = next((s for s in reversed(storage.get_mission_steps(mission['id'])) if s.get('kind') == 'note' and s.get('name') == 'submitted'), None)
    if booked:
        rj = booked.get('result_json') or {}
        facts = ', '.join(str(v) for v in (rj.get('facts') or {}).values())
        lead = 'Booked' if rj.get('verb') == 'book' else 'Submitted'
        tail = f" {lead}: {facts}" + (f", confirmation {rj['confirmation']}" if rj.get('confirmation') else '') + (f" (confirmed by {rj['by']})" if rj.get('by_hand') and rj.get('by') else '') + '.'
    else:
        tail = ' Nothing is booked.' if touched_site else ''
```

and append `tail` to the thread history `text` too: `'text': summary + tail`.

`_system_prompt(now, settings)`: after the browse paragraph add

```python
        + ("A browse may end needs_submit: a parent is asked to approve the press; wait for it. A `submit_attempt` on the transcript whose "
           "outcome is not confirmed, rejected, continued or failed is a commitment that may have happened: never press again on this "
           "mission; ask the person. After a `submitted` note the thing IS booked: say so, and never book it twice.\n"
           if (settings or {}).get('missions_submit_enabled', True) else
           "Booking is off for this family: a browse never books or submits; hand the person the link instead.\n")
```

Also `_user_prompt`'s browse compaction gains `'submit': {'button': (rj.get('submit') or {}).get('button')} if rj.get('submit') else None, 'attempt': {'outcome': (rj.get('attempt') or {}).get('outcome')} if rj.get('attempt') else None`.

- [ ] **Step 8: Run the mission tests**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_mission.py 2>&1 | Select-String "FAIL|passed"
```

Expected: all PASS. (`scenario_a_lost_browse_is_reclaimed_by_the_tick` and `scenario_a_browse_that_returns_after_the_mission_moved_on_changes_nothing` still pass: no attempt, same behaviour.)

- [ ] **Step 9: Pin check and commit**

```powershell
Select-String -Path services/missions.py -Pattern "mailer|send_direct_message\(" | Measure-Object
```

Expected: the `EXCLUDED_TOOLS` mention only (count 1).

```
feat(missions): the submit gate in the engine - needs_submit becomes a submit ask whose id is the approval, on_attempt authorizes under the lock and writes the attempt, outcomes resolve the attempt first, an unresolved attempt forces a verify ask whatever the report says, a parent resolves by tap, late reports are evidence only and never overwrite a parent, only the live browse moves the mission, the finish says Booked (v2.499.388)
```

---

### Task 6: Situations: the verbs, the id-bearing options, the thread routing, the tool refusal

**Files:**
- Modify: `chauffeur/services/situations.py` (`VERBS` `:24-26`, `_options_thread` `:228`, `_options_mission` `:249-275`, `needs_attention` `:370-373`, `_run` `:690-692`)
- Modify: `chauffeur/services/missions.py` (`release` ask_id tightened)
- Modify: `chauffeur/services/agent_tools_v2.py:1506-1513` (refuse `submit` and `verify` too; the `act_on_situation` verb enum)
- Modify: `chauffeur/static/situations.js:7-12` (`VERB_LABELS`)
- Modify: `chauffeur/services/triage.py` (find `tier(`; a `submit` or `verify` next step ranks tier 0 like `release`)
- Test: `chauffeur/tests/test_browse_mission.py`

**Interfaces:**
- Consumes: Task 5's `missions.submit`, `missions.verify`, `missions.release(..., ask_id)`.
- Produces: option ids `submit:<ask_id>:approve|decline|stop`, `verify:<ask_id>:confirmed|failed|unsure`, `release:<ask_id>:approve|decline|stop` on a mission; the thread form `submit:mission:<mid>:<ask_id>:approve` (and the rest). `act(kind, sid, verb, option_id, payload)` routes `submit`, `verify`, `release` with the id taken from the option, never from the payload.

- [ ] **Step 1: Write the failing tests**

Update the two existing scenarios that read `release:approve` ids: in `scenario_needs_release_pauses_with_the_values_and_tells_the_person` the expected ids become `f'release:{ask_id}:approve'` etc. where `ask_id = storage.get_mission_steps(mid)[-1]['id']`; in `scenario_release_approved_resumes_with_the_values_once` and `scenario_release_declined_hands_off_and_stop_blocks` pass `option_id=f'release:{ask_id}:approve'` / `:decline`; in `scenario_release_approved_twice_resumes_once` and the other direct `missions.release(...)` calls, pass `ask_id=storage.get_mission_steps(mid)[-1]['id']` (read it before the first approve; the second approve with the same id answers `already`). In `scenario_missing_card_fields_are_asked_for_not_handed_off` the same ask keeps waiting across both Share taps, so one id serves both. Then append:

```python
def scenario_submit_and_verify_options_carry_the_ask_id_and_route_from_the_thread():
    _reset()
    from services import threads
    tid = threads.create('Dishwasher repair', owner_member_id='mom', goal='get it fixed', created_by='mom')
    mid = storage.add_mission({'goal': 'book the dishwasher repair', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    _browse_to_submit(mid)
    ask = storage.get_mission_steps(mid)[-1]
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    ids = [o['id'] for o in s['options'] if o['verb'] == 'submit']
    check(ids == [f"submit:{ask['id']}:approve", f"submit:{ask['id']}:decline", f"submit:{ask['id']}:stop"], f"the mission's options: {ids}")
    check(s['next_step']['label'] == 'Book it' and s['needs_attention'], f"the lead: {s['next_step']}")
    t = situations.view('thread', tid, {'id': 'mom', 'role': 'parent'})
    tids = [o['id'] for o in t['options'] if o['verb'] == 'submit']
    check(tids[0] == f"submit:mission:{mid}:{ask['id']}:approve", f"the thread routes with the id: {tids}")
    res = situations.act('thread', tid, 'submit', option_id=f"submit:mission:{mid}:stale:approve", actor={'id': 'mom', 'role': 'parent'})
    check(res['status'] == 'refused' and storage.get_mission(mid)['status'] == 'waiting_user', f"a stale option is not on the table: {res}")
    runs = []
    missions._browse = lambda **kw: runs.append(kw) or _report('submit_unknown', text='UNKNOWN', attempt={**kw['approved'], 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''})
    res = situations.act('thread', tid, 'submit', option_id=tids[0], actor={'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    check(res['status'] == 'success' and len(runs) == 1 and runs[0]['approved']['ask_id'] == ask['id'], f"Book it from the thread resumes with the ask id: {res}")
    vask = storage.get_mission_steps(mid)[-1]
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    vids = [o['id'] for o in s['options'] if o['verb'] == 'verify']
    check(vids == [f"verify:{vask['id']}:confirmed", f"verify:{vask['id']}:failed", f"verify:{vask['id']}:unsure"] and s['next_step']['label'] == 'It went through', f"the verify options: {vids} {s['next_step']}")
    res = situations.act('mission', mid, 'verify', option_id=vids[0], payload={'text': 'confirmation 777'}, actor={'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    a = missions.attempts_for(mid)[0]
    check(res['status'] == 'success' and a['outcome'] == 'confirmed' and a['detail'] == 'confirmation 777', f"the detail rides the payload text: {a}")
    from services import triage
    _reset()
    mid = _mission()
    _browse_to_submit(mid)
    check(triage.tier(situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})) == 0, "a submit ask ranks tier 0")


def scenario_submit_and_verify_verbs_are_tap_only_everywhere():
    import re
    from services import agent_tools_v2 as tools
    for v in ('submit', 'verify'):
        check(v in situations.VERBS, f"the verb {v}")
        src = open('static/situations.js', encoding='utf-8').read()
        check(f"'{v}'" in re.search(r"VERB_LABELS\s*=\s*\{([^}]*)\}", src).group(1), f"the card label for {v}")
        res = tools.act_on_situation(ref='x', verb=v, acting_member={'id': 'mom', 'role': 'parent'})
        check(res['status'] == 'error' and 'tap' in res['message'].lower(), f"the chat tool refuses {v}: {res}")
    enum = next(t for t in tools.get_available_tools() if t['name'] == 'act_on_situation')['parameters']['properties']['verb']['enum']
    check('submit' not in enum and 'verify' not in enum, "the new tap-only verbs are not offered to the model (release stays listed; its handler refuses, pinned elsewhere)")


def scenario_release_options_carry_the_ask_id():
    _reset()
    missions._browse = lambda **kw: _report('needs_release', wanted_fields=['email'])
    mid = _mission()
    missions._llm = lambda m, s, u, st: {'action': 'browse', 'goal': 'g', 'site': 'bodewell.com'}
    missions.step(storage.get_mission(mid))
    ask = storage.get_mission_steps(mid)[-1]
    s = situations.view('mission', mid, {'id': 'mom', 'role': 'parent'})
    check([o['id'] for o in s['options'] if o['verb'] == 'release'] == [f"release:{ask['id']}:approve", f"release:{ask['id']}:decline", f"release:{ask['id']}:stop"], "release ids carry the ask")
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id=None)
    check(res.get('moved') and storage.get_mission(mid)['status'] == 'waiting_user', f"no ask id: refused, not defaulted: {res}")
    res = missions.release(mid, 'approve', {'id': 'mom', 'role': 'parent'}, ask_id='old')
    check(res.get('moved'), "a stale id moves nothing")
```

- [ ] **Step 2: Run to verify they fail**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_mission.py 2>&1 | Select-String "FAIL|passed"
```

Expected: the three new scenarios FAIL; the edited release scenarios FAIL until the ids land.

- [ ] **Step 3: Implement**

`situations.py`:

```python
VERBS = frozenset({'assign', 'ask', 'plan', 'prepare', 'do', 'done', 'skip',
                   'research', 'draft', 'advance', 'answer', 'close', 'snooze',
                   'dismiss', 'own', 'unread', 'release', 'submit', 'verify'})
```

`_options_mission`, the `waiting_user` branch:

```python
        name = (asked or {}).get('name')
        aid = (asked or {}).get('id') or ''
        if name == 'release':
            out.append(_opt('release', rj.get('question') or f"Share with {rj.get('site')}", {'decision': 'approve'}, f'{aid}:approve'))
            out.append(_opt('release', 'Not these', {'decision': 'decline'}, f'{aid}:decline'))
            out.append(_opt('release', 'Stop the mission', {'decision': 'stop'}, f'{aid}:stop'))
        elif name == 'submit':
            # A booking happens only on this tap (spec 2026-10-11); the id is the approval.
            out.append(_opt('submit', 'Book it' if rj.get('verb') == 'book' else 'Submit it', {'decision': 'approve'}, f'{aid}:approve'))
            out.append(_opt('submit', "I'll finish it myself", {'decision': 'decline'}, f'{aid}:decline'))
            out.append(_opt('submit', 'Stop the mission', {'decision': 'stop'}, f'{aid}:stop'))
        elif name == 'verify':
            out.append(_opt('verify', 'It went through', {'outcome': 'confirmed'}, f'{aid}:confirmed'))
            out.append(_opt('verify', 'It did not go through', {'outcome': 'failed'}, f'{aid}:failed'))
            out.append(_opt('verify', "Still can't tell", {'outcome': 'unsure'}, f'{aid}:unsure'))
        else:
            ... (the existing `answer` option)
```

`_options_thread`: `if o['verb'] in ('answer', 'release', 'submit', 'verify'):`. `needs_attention`: `('answer', 'do', 'release', 'submit', 'verify')`. In `act()`, the free-payload merge: add `'verify'` to the verbs that take `text` (`if verb in ('answer', 'advance', 'draft', 'research', 'verify')`). In `_run`:

```python
    if verb in ('release', 'submit', 'verify'):
        from services import missions as _m
        # The ask id is the option's, never the payload's: `<verb>:<ask_id>:<decision>`.
        bits = (p.get('_option_id') or '').split(':')
        ask_id = bits[1] if len(bits) >= 3 else None
        if verb == 'release':
            return _m.release(sid, p.get('decision'), actor, ask_id=ask_id)
        if verb == 'submit':
            return _m.submit(sid, p.get('decision'), actor, ask_id=ask_id)
        return _m.verify(sid, ask_id, p.get('outcome'), actor, detail=p.get('text') or '')
```

and in `act()` before `_run`: `p['_option_id'] = opt['id']`. (`_opt(verb, label, payload, sub)` builds the id as `f"{verb}:{sub}"`; check its definition near line 30 and keep that shape.)

`triage.py:62`: `if lead.startswith(('answer:mission:', 'release:mission:', 'submit:mission:', 'verify:mission:')):` (a mission in `waiting_user` is already tier 0 at `:68`).

`tests/test_start_mission.py` also reads release ids without an ask id (`:157`, `:160`, `:214`, `:359-360`, `:368`): read `ask_id = [s for s in storage.get_mission_steps(mid) if s['kind'] == 'ask'][-1]['id']` in each scenario and use `f'release:mission:{mid}:{ask_id}:approve'` (and `:decline`, `:stop`; the mission-kind form `f'release:{ask_id}:approve'` at `:360`). Run `python tests/test_start_mission.py` in Step 4 as well.

`static/situations.js` `VERB_LABELS`: add `'submit': 'Book it', 'verify': 'Did it go through?'`.

`agent_tools_v2.py:1506`: `if verb in ('release', 'submit', 'verify'):` with the message "Booking, submitting and sharing the family's details take a tap, not a word: tap it on the Missions page, the thread card or the DM card." Find the `act_on_situation` schema's `verb` enum (grep `'enum'` near `act_on_situation` in `TOOL_SCHEMAS`) and remove `release` if present; do not add the new verbs.

`missions.release`: tighten to `if not ask_id or ask['id'] != ask_id: return moved` (Task 5 left it lenient).

- [ ] **Step 4: Run the mission tests**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_mission.py 2>&1 | Select-String "FAIL|passed"; python tests/test_start_mission.py 2>&1 | Select-String "FAIL|passed"
```

Expected: all PASS in both files.

- [ ] **Step 5: Commit**

```
feat(situations): submit and verify verbs, tap-only; every release, submit and verify option carries its ask id and the thread routes it; the chat tool refuses all three; triage ranks a submit or verify tier 0 (v2.499.389)
```

---

### Task 7: The API, the switch, the transcript, the live pages

**Files:**
- Modify: `chauffeur/main.py:5834-5846` (release takes `ask_id`; add `/submit` and `/verify`)
- Modify: `chauffeur/services/settings_registry.py:669` (add `missions_submit_enabled`)
- Modify: `chauffeur/templates/components/missions_page.html:95-101` (the toggle), `:261-269` + `:302-321` (load/save keys), `:573-582` (`releaseMission` passes the ask id; add `submitMission`, `verifyMission`)
- Modify: `chauffeur/templates/components/threads_page.html:585-592` (same three)
- Modify: `chauffeur/templates/components/mission_transcript.html:70`, `:107-129`, `:145-148` (the submit and verify ask blocks, the notes)
- Modify: `chauffeur/static/mission_transcript.js` (`isReleasePending` becomes `isTapAskPending`; `release(apiBase, id, decision, askId)`, `submit(...)`, `verify(...)`)
- Modify: `chauffeur/templates/components/missions_page.html:221` (`!isTapAskPending(mission)`)
- Test: `chauffeur/tests/test_browse_page_live.py`, `chauffeur/tests/test_browse_thread_live.py`, `chauffeur/tests/test_browse_mission.py` (the route classification pin)

**Interfaces:**
- Consumes: Task 5's `missions.submit/verify/release`, Task 6's option ids.
- Produces: `POST /api/missions/{id}/submit {decision, ask_id}`, `POST /api/missions/{id}/verify {ask_id, outcome, detail}`, `POST /api/missions/{id}/release {decision, ask_id}`; `window.MissionTranscript.submit(apiBase, missionId, decision, askId)`, `.verify(apiBase, missionId, askId, outcome, detail)`, `.release(apiBase, missionId, decision, askId)`, `.isTapAskPending(mission)`.

- [ ] **Step 1: Write the failing tests**

`test_browse_mission.py`, append:

```python
def scenario_submit_and_verify_routes_are_classified_like_release():
    from services import auth
    for path in ('/api/missions/x/submit', '/api/missions/x/verify'):
        check(auth.resolve('POST', path) == auth.resolve('POST', '/api/missions/x/release'), f"{path} is gated like release")
```

`test_browse_page_live.py`: extend `seed()` with a second mission in `waiting_user` on a `submit` ask and a third on a `verify` ask:

```python
    m2 = storage.add_mission({'goal': 'book the dishwasher repair', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    storage.add_mission_step(m2, {'kind': 'ask', 'name': 'submit', 'result_json': {
        'question': "Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95 (button 'Book appointment')?", 'verb': 'book', 'site': 'bodewell.com',
        'url': 'https://www.bodewell.com/schedule', 'button': 'Book appointment', 'state': {'fields': {'notes': ''}, 'selected': ['Tue, Oct 20 8AM-12PM'], 'text': 't', 'text_sha': 'a' * 64, 'prices': ['$114.95']},
        'display': 'Trip charge $114.95', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}, 'intent': '', 'filled': {'first_name': 'Jeff'}, 'changed': [],
        'browse': {'goal': 'book', 'site': 'bodewell.com', 'start_url': 'https://www.bodewell.com/schedule', 'released': {}}}})
    storage.update_mission(m2, {'status': 'waiting_user'})
    m3 = storage.add_mission({'goal': 'register for the permit', 'origin_kind': 'manual', 'created_by': 'mom', 'tier': 'mission'})
    a3 = storage.add_mission_step(m3, {'kind': 'note', 'name': 'submit_attempt', 'result_json': {'ask_id': 'a', 'browse_step_id': 'b', 'button': 'Send application', 'url': 'https://permits.example/a',
                                                                                             'state': {}, 'pressed_at': 1.0, 'outcome': 'unknown', 'text': ''}})
    storage.add_mission_step(m3, {'kind': 'ask', 'name': 'verify', 'result_json': {'question': "I pressed 'Send application' at https://permits.example/a and could not read whether it went through. Check your email or the site, then tell me below.",
                                                                                 'attempt_step_id': a3, 'button': 'Send application', 'url': 'https://permits.example/a', 'facts': {}, 'display': '', 'payment': False}})
    storage.update_mission(m3, {'status': 'waiting_user'})
```

and in `main()` after the existing checks:

```python
            book = page.locator('#missions .situation-card:has-text("book the dishwasher")').first
            check(book.locator('.sit-next button').first.inner_text() == 'Book it', "the submit card leads with Book it")
            det = book.locator('xpath=../following-sibling::details[1]').first
            det.locator('summary').first.click(); page.wait_for_timeout(500)
            tl = det.inner_text()
            check("Book at bodewell.com" in tl and 'Tue, Oct 20 8AM-12PM' in tl and 'first_name' in tl and det.locator('button:has-text("Book it")').count() == 1
                  and det.locator('button:has-text("I\'ll finish it myself")').count() == 1 and det.locator('button:has-text("Stop")').count() == 1, f"the submit ask block: {tl[:400]}")
            check(not det.locator('input[placeholder="Type your answer"]').first.is_visible(), "a submit is answered by its buttons")
            det.locator('button:has-text("Book it")').first.click(); page.wait_for_timeout(1500)
            m2 = [x for x in storage.get_missions() if x['goal'] == 'book the dishwasher repair'][0]
            steps = storage.get_mission_steps(m2['id'])
            check(any(s['name'] == 'submit_approved' for s in steps), f"Book it approved with the ask id: {[s['name'] for s in steps]}")
            if page.locator('#cc-alert-modal').is_visible():
                page.locator('#cc-alert-modal button:has-text("OK")').click()
            perm = page.locator('#missions .situation-card:has-text("permit")').first
            check(perm.locator('.sit-next button').first.inner_text() == 'It went through', "the verify card leads with It went through")
            det = perm.locator('xpath=../following-sibling::details[1]').first
            det.locator('summary').first.click(); page.wait_for_timeout(500)
            det.locator('input[placeholder="Confirmation number or what you saw"]').first.fill('confirmation 4242')
            det.locator('button:has-text("It went through")').first.click(); page.wait_for_timeout(1500)
            m3 = [x for x in storage.get_missions() if x['goal'] == 'register for the permit'][0]
            from services import missions as _m
            a = _m.attempts_for(m3['id'])[0]
            check(a['outcome'] == 'confirmed' and a['detail'] == 'confirmation 4242' and m3['status'] == 'running', f"It went through resolved the attempt with the detail: {a} {m3['status']}")
```

The seed's `missions._browse` fake must return a `submitted` report for the Book it tap: `{'outcome': 'submitted', 'text': 'CONFIRMED: 12345', ..., 'submit': None, 'changed': [], 'attempt': {'ask_id': kw['approved']['ask_id'], ...,'outcome': 'confirmed', 'text': 'Confirmation number 12345'}}`; make the fake a `def` taking `**kw`.

`test_browse_thread_live.py`: in `seed()`, give the Gutters mission a `submit` ask instead of the handoff (same shape as `m2` above, site `gutterco.example`, button `Book now`) and in `main()` check `gutters.locator('.sit-next button').first.inner_text() == 'Book it'`, click it, and check the mission's steps carry `submit_approved`. Keep a hand-off fixture: move the hand-off to a fourth thread 'Roof' so the link check still runs.

- [ ] **Step 2: Run to verify they fail**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_mission.py 2>&1 | Select-String "FAIL|passed"; python tests/test_browse_page_live.py; python tests/test_browse_thread_live.py
```

Expected: the route pin fails (`/submit` resolves differently or 404s); the live tests fail at the Book it lead.

- [ ] **Step 3: The API**

`main.py`, `missions_release`: `res = _missions.release(mission_id, (body.get('decision') or '').strip(), actor, ask_id=(body.get('ask_id') or None))`. Then:

```python
@app.post("/api/missions/{mission_id}/submit")
def missions_submit(mission_id: str, body: dict = Body(default={}), request: Request = None):
    """A submit ask answered by hand (spec 2026-10-11): approve re-runs the
    browse with the approved record and presses once; decline hands over;
    stop blocks. The ask id is the approval; a stale one answers moved."""
    from services import missions as _missions
    actor = _approver_of_record(_mind_actor(request, body.get('member_id')))
    res = _missions.submit(mission_id, (body.get('decision') or '').strip(), actor, ask_id=(body.get('ask_id') or None))
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') == 'error':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res


@app.post("/api/missions/{mission_id}/verify")
def missions_verify(mission_id: str, body: dict = Body(default={}), request: Request = None):
    """A parent resolves an attempt the browser could not read: confirmed,
    failed or unsure, with a detail (a confirmation number)."""
    from services import missions as _missions
    actor = _approver_of_record(_mind_actor(request, body.get('member_id')))
    res = _missions.verify(mission_id, body.get('ask_id') or None, (body.get('outcome') or '').strip(), actor, detail=body.get('detail') or '')
    if res.get('status') == 'refused':
        raise HTTPException(status_code=403, detail=res.get('message'))
    if res.get('status') == 'error':
        raise HTTPException(status_code=400, detail=res.get('message'))
    return res
```

`auth.py`: `/api/missions/*` already covers both (`SIGNED_IN`); the pin passes once the routes exist. If `auth.resolve` returns a per-route record that differs for unknown paths, add nothing: the wildcard matches.

- [ ] **Step 4: The switch**

`settings_registry.py`, after the `missions_captcha_attempts` entry:

```python
    _e('missions_submit_enabled', 'missions', 'Argyle may book and submit forms with your approval',
       "On by default. A browse that reaches a Book, Confirm, Submit or Send button stops and asks; a parent taps Book it and the "
       "browser presses once. Payment is never pressed, on or off. Off: the browser stops at such a button and hands you the page.",
       page='work?tab=missions', anchor='browse'),
```

`missions_page.html` Browser section, before the CAPTCHA toggle:

```html
                <label class="flex items-center justify-between bg-gray-800 rounded-xl border border-gray-700 px-4 py-3">
                    <span class="text-sm font-semibold text-gray-200">Argyle may book and submit forms with your approval</span>
                    <input type="checkbox" x-model="s.missions_submit_enabled" @change="save()" class="h-5 w-5 accent-pink-400">
                </label>
                <p class="text-[11px] text-gray-500 -mt-1 px-1">On: a Book or Submit button becomes a question you answer with a tap, then the browser presses it once. Payment is never pressed. Off: it hands you the page instead.</p>
```

`s` gains `missions_submit_enabled: true`; `save()` sends `missions_submit_enabled: !!this.s.missions_submit_enabled`. In `load()`, the loop already copies non-null keys; an absent key keeps `true` (the default).

- [ ] **Step 5: The transcript**

`mission_transcript.js`:

```js
    isTapAskPending(mission) {
      const asks = (mission.steps || []).filter(s => s.kind === 'ask');
      return asks.length > 0 && ['release', 'submit', 'verify'].includes(asks[asks.length - 1].name);
    },
    isReleasePending(mission) { return this.isTapAskPending(mission); },
    lastAskId(mission) {
      const asks = (mission.steps || []).filter(s => s.kind === 'ask');
      return asks.length ? asks[asks.length - 1].id : null;
    },
    async _post(apiBase, path, body) {
      const r = await fetch(apiBase + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.detail || "That didn't work.");
      return d;
    },
    // Every tap carries the ask's id: a stale card can never answer a newer question.
    release(apiBase, missionId, decision, askId) { return this._post(apiBase, `api/missions/${missionId}/release`, { decision, ask_id: askId }); },
    submit(apiBase, missionId, decision, askId) { return this._post(apiBase, `api/missions/${missionId}/submit`, { decision, ask_id: askId }); },
    verify(apiBase, missionId, askId, outcome, detail) { return this._post(apiBase, `api/missions/${missionId}/verify`, { ask_id: askId, outcome, detail: detail || '' }); },
```

`missions_page.html` and `threads_page.html` component methods (both files, same code; the missions page refreshes with `this.loadAdmin()`, the threads page with `this.load()`):

```js
                isTapAskPending(mission) { return window.MissionTranscript.isTapAskPending(mission); },
                async releaseMission(m, decision, step) {
                    try {
                        const d = await window.MissionTranscript.release(this.apiBase, m.id, decision, (step && step.id) || window.MissionTranscript.lastAskId(m));
                        if (d.message) showGlobalAlert(d.message);
                        await this.loadAdmin();
                    } catch (e) { showGlobalAlert(e.message || "That didn't work."); }
                },
                async submitMission(m, decision, step) {
                    try {
                        const d = await window.MissionTranscript.submit(this.apiBase, m.id, decision, step.id);
                        if (d.message) showGlobalAlert(d.message);
                        await this.loadAdmin();
                    } catch (e) { showGlobalAlert(e.message || "That didn't work."); }
                },
                async verifyMission(m, outcome, step) {
                    try {
                        const d = await window.MissionTranscript.verify(this.apiBase, m.id, step.id, outcome, (this.verifyDetail || {})[m.id] || '');
                        if (d.message) showGlobalAlert(d.message);
                        await this.loadAdmin();
                    } catch (e) { showGlobalAlert(e.message || "That didn't work."); }
                },
```

with `verifyDetail: {}` added to each component's state. Replace `isReleasePending` uses with `isTapAskPending` (`missions_page.html:221`, `:573`, `threads_page.html:585`). The release buttons in `mission_transcript.html:114-116` pass `step`: `releaseMission(mission, 'approve', step)`.

`mission_transcript.html`: change line 70's exclusion to `!['release', 'handoff', 'submit', 'verify'].includes(step.name)`. After the release block add:

```html
                                            <!-- submit: the transaction the way the site has it, and the three answers.
                                                 The browser presses only on Book it (spec 2026-10-11). -->
                                            <template x-if="step.kind === 'ask' && step.name === 'submit'">
                                                <div class="mt-1 bg-amber-500/10 border border-amber-500/30 rounded-xl p-2">
                                                    <div class="text-sm text-amber-200" x-text="(step.result_json || {}).question || ''"></div>
                                                    <div class="text-[11px] text-gray-400 mt-0.5" x-show="(((step.result_json || {}).state || {}).selected || []).length"
                                                         x-text="'Selected: ' + ((((step.result_json || {}).state || {}).selected) || []).join(' · ')"></div>
                                                    <div class="text-[11px] text-gray-400" x-show="Object.keys((step.result_json || {}).filled || {}).length"
                                                         x-text="'Filled: ' + Object.entries((step.result_json || {}).filled || {}).map(([k, v]) => k + '=' + v).join(', ')"></div>
                                                    <div class="text-[11px] text-gray-500 mt-0.5" x-text="(step.result_json || {}).display || ''"></div>
                                                    <div class="flex flex-wrap gap-2 mt-1.5" x-show="mission.status === 'waiting_user' && isLastAsk(mission, step)">
                                                        <button @click="submitMission(mission, 'approve', step)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700"
                                                                x-text="(step.result_json || {}).verb === 'book' ? 'Book it' : 'Submit it'"></button>
                                                        <button @click="submitMission(mission, 'decline', step)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">I'll finish it myself</button>
                                                        <button @click="submitMission(mission, 'stop', step)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Stop</button>
                                                    </div>
                                                </div>
                                            </template>
                                            <!-- verify: the browser pressed and could not read the result; the parent says what happened. -->
                                            <template x-if="step.kind === 'ask' && step.name === 'verify'">
                                                <div class="mt-1 bg-amber-500/10 border border-amber-500/30 rounded-xl p-2">
                                                    <div class="text-sm text-amber-200"><span x-text="(step.result_json || {}).question || ''"></span>
                                                        <a :href="(step.result_json || {}).url" target="_blank" rel="noopener" class="text-blue-400 underline underline-offset-2 ml-1">Open it</a></div>
                                                    <div class="mt-1.5" x-show="mission.status === 'waiting_user' && isLastAsk(mission, step)">
                                                        <input type="text" x-model="verifyDetail[mission.id]" placeholder="Confirmation number or what you saw"
                                                               class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-1.5 text-white text-sm mb-1.5">
                                                        <div class="flex flex-wrap gap-2">
                                                            <button @click="verifyMission(mission, 'confirmed', step)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-blue-600 text-white active:bg-blue-700">It went through</button>
                                                            <button @click="verifyMission(mission, 'failed', step)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">It did not go through</button>
                                                            <button @click="verifyMission(mission, 'unsure', step)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700">Still can't tell</button>
                                                        </div>
                                                    </div>
                                                </div>
                                            </template>
                                            <template x-if="step.kind === 'note' && ['submit_approved', 'submit_attempt', 'submitted', 'submit_rejected', 'submit_failed', 'late_evidence'].includes(step.name)">
                                                <div class="text-xs text-gray-400 italic mt-1" x-text="submitNoteText(step)"></div>
                                            </template>
```

and in line 147's exclusion list add the six note names. `submitNoteText(step)` goes in `mission_transcript.js` (and is delegated from both components like `stepResultText`):

```js
    submitNoteText(step) {
      const r = step.result_json || {};
      if (step.name === 'submit_approved') return `Approved: press '${r.button || ''}'.`;
      if (step.name === 'submit_attempt') return `Pressed '${r.button || ''}' at ${r.url || ''}: ${r.outcome || 'no answer yet'}` + (r.resolved_by ? ` (${r.resolved_by.name || 'a parent'} said so)` : '') + '.';
      if (step.name === 'submitted') return (r.verb === 'book' ? 'Booked' : 'Submitted') + (r.confirmation ? `, confirmation ${r.confirmation}` : '') + (r.by_hand ? ` (confirmed by ${r.by || 'a parent'})` : '') + '.';
      if (step.name === 'submit_rejected') return `The site rejected it: ${r.error || ''}`;
      if (step.name === 'submit_failed') return `Did not go through${r.detail ? ': ' + r.detail : ''}.`;
      return r.note || '';
    },
```

Run `python tools/build_tailwind.py` after the template edits.

- [ ] **Step 6: Run the tests**

```powershell
$env:HA_BASE_URL = ''; python tests/test_browse_mission.py 2>&1 | Select-String "FAIL|passed"; python tests/test_browse_page_live.py; python tests/test_browse_thread_live.py
```

Expected: all PASS, both live tests print `PASS`.

- [ ] **Step 7: Commit**

```
feat(missions): Book it, I'll finish it myself, Stop and It went through / It did not go through / Still can't tell on the Missions page and the thread card, every tap carrying its ask id; POST /submit and /verify; release takes ask_id; the missions_submit_enabled switch in the Browser drawer (v2.499.390)
```

---

### Task 8: End to end, the capabilities doc, the memory

**Files:**
- Test: `chauffeur/tests/test_start_mission.py`
- Modify: `chauffeur/system_capabilities.md:3-5` (version line, a new block at the top)
- Modify: `docs/superpowers/specs/2026-10-11-submit-gate-design.md:3` (status: BUILT)
- Modify: `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\browse-missions-arc.md` and `MEMORY.md` (the arc line)

- [ ] **Step 1: Write the failing end-to-end scenario**

Append to `test_start_mission.py` and add the name to its `SCENARIOS` list (`:376`):

```python
def scenario_the_dishwasher_is_booked_on_a_tap():
    """Spec 2026-10-11: after the slots are read the browse asks, the parent taps Book it, the attempt lands,
    the resumed browse confirms, the mission finishes Booked; nothing proposed, nothing paid."""
    _reset(); _dm_capture()
    storage.get_settings = lambda: {'missions_enabled': True, 'llm_gemini_paid_api_key': 'paid', 'thread_stall_days': 7, 'missions_submit_enabled': True,
                                    'contact_first_name': 'Jeff', 'contact_email': 'ffejnosliw@gmail.com', 'contact_zip': '27519'}
    missions._browse_async = False
    res = tools.start_mission_for('Get availability and pricing for GE Bodewell service for a 2021 GE Cafe dishwasher and book the earliest slot', acting_member=MOM, focus_key='voice:1')
    mid, tid = res['mission_id'], res['thread_id']
    rec = {'button': 'Book appointment', 'url': 'https://www.bodewell.com/schedule', 'intent': 'book Tue',
           'state': {'fields': {}, 'selected': ['Tue, Oct 20 8AM-12PM'], 'text': 'Trip charge $114.95 Tue, Oct 20 8AM-12PM', 'text_sha': 'c' * 64, 'prices': ['$114.95']},
           'display': 'Trip charge $114.95', 'facts': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}}
    runs = []

    def fake(**kw):
        runs.append(kw)
        base = {'learned': {'slot': 'Tue, Oct 20 8AM-12PM', 'price': '$114.95'}, 'stopped_at': rec['url'], 'wanted_fields': [], 'turns': 9, 'tokens_in': 1, 'tokens_out': 1,
                'seconds': 1, 'screenshots': [], 'filled': {'first_name': 'Jeff'}, 'submit': None, 'attempt': None, 'changed': []}
        if kw.get('approved'):
            ok = kw['on_attempt']({'ask_id': kw['approved']['ask_id'], 'button': 'Book appointment', 'url': rec['url'], 'state': rec['state'], 'pressed_at': time.time(), 'outcome': None, 'text': ''})
            assert ok, "the engine must authorize the press"
            return {**base, 'outcome': 'submitted', 'text': 'CONFIRMED: Confirmation number 12345',
                    'attempt': {**kw['approved'], 'pressed_at': time.time(), 'outcome': 'confirmed', 'text': 'Confirmation number 12345'}}
        return {**base, 'outcome': 'needs_submit', 'text': 'Book appointment', 'submit': rec}
    missions._browse = fake
    plan = [{'action': 'browse', 'goal': 'find the slots and the fee, then book the earliest', 'site': 'bodewell.com'},
            {'action': 'finish', 'summary': 'Bodewell comes Tue Oct 20 8-12; trip charge $114.95.', 'next_action': 'Be home Tue Oct 20 8-12', 'next_action_at': '2026-10-20'}]
    missions._llm = lambda m, s, u, st: plan.pop(0)
    row = missions.step(storage.get_mission(mid))
    ask = storage.get_mission_steps(mid)[-1]
    check(row['status'] == 'waiting_user' and ask['name'] == 'submit' and ask['result_json']['question'].startswith('Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95'), f"the ask: {ask['result_json']['question']}")
    check(SENT[-1].endswith('Tap Book it on the Missions page or the thread card.'), f"the DM: {SENT[-1]}")
    s = situations.view('thread', tid, MOM)
    check(s['next_step']['label'] == 'Book it' and s['next_step']['id'] == f"submit:mission:{mid}:{ask['id']}:approve", f"the thread card leads with Book it: {s['next_step']}")
    res = situations.act('thread', tid, 'submit', option_id=s['next_step']['id'], actor=MOM)
    check(res['status'] == 'success' and len(runs) == 2 and runs[1]['approved']['ask_id'] == ask['id'], f"Book it resumed the browse with the record: {res}")
    atts = missions.attempts_for(mid)
    check(len(atts) == 1 and atts[0]['outcome'] == 'confirmed', f"one attempt, confirmed: {atts}")
    check(storage.get_mission(mid)['status'] == 'running', "the planner runs on")
    row = missions.step(storage.get_mission(mid))
    check(row['status'] == 'done', f"finished: {row['status']}")
    check('Booked: Tue, Oct 20 8AM-12PM, $114.95, confirmation 12345' in SENT[-1] and 'Nothing is booked' not in SENT[-1], f"the finish says Booked: {SENT[-1]}")
    t = storage.get_thread(tid)
    check(t['next_action_at'] == '2026-10-20' and 'Booked:' in [h for h in t['history'] if h['kind'] == 'mission'][-1]['text'], "the thread's next step is the appointment")
    check(not [st for st in storage.get_mission_steps(mid) if st['kind'] == 'proposal'] and not storage.get_action_proposals() if hasattr(storage, 'get_action_proposals') else True, "nothing proposed")
    check(all('payment' not in (st.get('result_json') or {}).get('text', '') for st in storage.get_mission_steps(mid) if st['kind'] == 'browse'), "nothing paid")
```

(`import time` at the top of the file.)

- [ ] **Step 2: Run it**

```powershell
$env:HA_BASE_URL = ''; python tests/test_start_mission.py 2>&1 | Select-String "FAIL|PASS|passed"
```

Expected: PASS for the new scenario (everything it needs shipped in Tasks 5-6). If it fails, the failure is a real integration bug: fix it in the owning module, not in the test.

- [ ] **Step 3: The capabilities doc**

`system_capabilities.md`: line 3 becomes `**Living specification. Current through v2.499.391 (2026-10-12).**`. Insert a new block after line 5 (the device-verified paragraph):

```markdown
**The submit gate: a browse may book or submit a form, on a parent's tap (v2.499.384–.391; spec `docs/superpowers/specs/2026-10-11-submit-gate-design.md`; `services/browse.py` `SUBMIT_WORDS`/`PAY_WORDS`/`STEP_WORDS`/`COMMIT_CONTEXT`/`CONFIRMATION_MARKERS`, `_control_at`/`_focused_control`/`_control_by_text`/`_classify`/`_changed`/`_activate`, outcomes `needs_submit`/`submitted`/`submit_rejected`/`submit_unknown`; `services/missions.py` `submit`/`verify`/`_on_attempt_for`/`attempts_for`/`_resolve_attempts`/`_submit_ask`/`_verify_ask`/`_stop_text`; `services/situations.py` verbs `submit`/`verify`; `main.py` `POST /api/missions/{id}/submit` + `/verify`, `/release` takes `ask_id`; setting `missions_submit_enabled` (default on, Missions drawer → Browser); tests `test_browse_runner.py` (gate, approved press, outcomes, one activation counted at the fixture's POST endpoint), `test_browse_mission.py` (asks, ids, on_attempt, verify, late reports, reclaim), `test_browse_page_live.py`/`test_browse_thread_live.py` (the buttons), `test_start_mission.py` `scenario_the_dishwasher_is_booked_on_a_tap`).** NOT device-verified.

- **Two word lists, two paths.** `SUBMIT_WORDS` (book, submit, confirm, reserve, send, apply, register, sign up, …) is a commitment a parent may approve; `PAY_WORDS` (pay, checkout, purchase, buy, order now, place order, charge) is money and ends the run `blocked: payment` with or without a card field, approval or not. `STOP_WORDS` is gone.
- **Classification is by evidence, never by label.** Every click, double-click, Enter and Space resolves the control under it and its scope (its form, or the nearest dialog/section/main, else body). Submitting a form is not by itself a commitment ("Next: Select Appliance" runs). A control asks when: a submit or pay word is in its text or the model's intent; its scope carries a price or commitment language ("by clicking", "I agree", "terms", "authorize", "total", "confirm your", "review your") and it is the scope's sole submit control or only/last button; or its label is not a step word (next, continue, proceed, back, previous, "Step N") and it is the sole submit control or only button over a scope that holds state. Everything else runs: the "Dishwasher" tile among eight, a cookie banner's "Accept", "Continue" on a priceless step. A disabled control or an iframe under the point is unclassifiable and runs unless the intent says otherwise. Backstop: an ungated press that lands on a page reading as a confirmation ends `submit_unknown` with an `unasked` attempt. Policy: nothing commits without a tap; enforcement: best-effort, every slip recorded and handed to the person.
- **The question carries the whole transaction.** `submit = {button, url, state{fields, selected (native + aria-checked/selected/pressed), text (whole), text_sha, prices}, display (300 chars, never compared), facts (the model's LEARNED pairs), intent}`. A snapshot is never empty: an unreadable scope is `blocked: form state unreadable`; `SUBMIT: <text>` naming no control is told once, then `blocked: could not find the control`.
- **The approved press.** `run(..., approved, on_attempt)`: the control's text, the domain and the whole state (selected, fields, text_sha) must match or the run re-asks `needs_submit` with `changed` ("selected: Thu … (approved: Tue …)", "prices: $124.95 appears; $114.95 does not", "text: changed"); then `on_attempt(record)` must return true (the engine: mission `browsing`, this is the newest browse step, `approved_ask_id` matches and unspent, no unresolved attempt on the mission; writes the `submit_attempt` note and marks the approval spent, all under `db_lock`; false = `blocked: approval withdrawn`, no press). Exactly one activation (a double-click is one click). After it, only scroll/wait/go_back; the model ends with `CONFIRMED:`/`REJECTED:`/`CONTINUED:`/`UNKNOWN:` → `submitted`/`submit_rejected`/(corroborated: attempt `continued`, the run goes on unapproved)/`submit_unknown`; no line, a cap or an error after the press is `submit_unknown`. The attempt and its outcome travel in the report.
- **The mission.** `needs_submit` → ask `submit` ("Book at bodewell.com: Tue, Oct 20 8AM-12PM, $114.95 (button 'Book appointment')?", the DM ends "Tap Book it on the Missions page or the thread card."), options `submit:<ask_id>:approve|decline|stop` ("Book it"/"Submit it", "I'll finish it myself", "Stop the mission"); the thread routes `submit:mission:<mid>:<ask_id>:…`. The ask id IS the approval: a stale or missing id answers `moved`; release gained the same discipline (`release:<ask_id>:…`, `/release {decision, ask_id}`). Approve re-runs the browse with the record; decline hands off ("I did not press '{button}'"); stop reads the attempts ("did not book" only with none or all resolved; a confirmed one "stands"; an unresolved one "may have gone through").
- **Attempts.** `finish_browse` first decides liveness (mission `browsing` AND newest browse step is this step); a late report parks on its own step as evidence and moves nothing. It then resolves the attempt note (a human resolution is never overwritten: the late outcome goes to `late_reports` and a `late_evidence` note says the parent's answer stands), writes `unknown` on any pending attempt of this step, and any `unknown` attempt forces the `verify` ask whatever the report says (error, capped, payment wall). `verify` ask: "I pressed '{button}' at {url} and could not read whether it went through…" (payment variant: "the page then asked for payment, which I never enter"), options `verify:<verify_ask_id>:confirmed|failed|unsure` + a detail box; `missions.verify` resolves the attempt server-side through `attempt_step_id` with `resolved_by`/`resolved_at`/`detail`; confirmed → `submitted` note `by_hand`, failed → `submit_failed` (clears the one-press bar; a new press still needs a fresh ask), unsure keeps waiting. The reclaim marks a dead worker's pending attempt `unknown` and raises the verify ask, never `running`. The finish says "Booked: {facts}, confirmation {n} (confirmed by {name})" instead of "Nothing is booked", and the thread's next step is the appointment.
- **The planner** is told: wait for the parent on `needs_submit`; an attempt not confirmed/rejected/continued/failed means never press again on this mission, ask the person; after a `submitted` note the thing IS booked. With the switch off: "booking is off; hand the person the link."
- **The chat tool refuses `submit`, `verify` and `release`**: taps only, never words.
```

- [ ] **Step 4: The spec status and the memory**

Spec line 3: prepend `**BUILT v2.499.384–.391 (2026-10-12), NOT device-verified.** `. Memory `browse-missions-arc.md`: add a dated line "2026-10-12: submit gate BUILT v2.499.384–.391 (spec 2026-10-11-submit-gate-design.md), NOT device-verified; flip nothing: `missions_submit_enabled` defaults on; next = device run of the dishwasher booking, then voice identity (PIN), then payment slice." and update the `MEMORY.md` hook for that line to say "submit gate BUILT v2.499.384–.391, NOT device-verified".

- [ ] **Step 5: Commit**

```
docs(capabilities): the submit gate shipped - two word lists, classification by evidence, the whole transaction in the question, one approved activation, attempts with their own outcomes, verify by tap, late reports as evidence; spec marked BUILT (v2.499.391)
```
