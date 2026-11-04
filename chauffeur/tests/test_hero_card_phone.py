"""HeroCard's phone skin (PWA reimagined, slice 1, task 5).

My Day's hero is the wall's HeroCard wearing a phone skin: one renderer, so
the phone and the wall cannot disagree about what is next. The phone call is
`HeroCard.html(next, { phone: true, now })` and returns a
`<section class="pwa-hero">` with a kicker ("<kind label> · <countdown>"), the
big line, who, meta and one or two buttons whose onclick are the action `run`
strings. The wall's call (no `phone`) must stay BYTE-IDENTICAL: the board, the
screensaver corner and the kitchen overlay all read it.

The golden for the wall is computed here from the COMMITTED component
(`git show HEAD:...`), run in the same node process as the working tree with
the clock frozen, so the test proves the wall path did not move rather than
comparing against a hand-saved string that would rot.

Node scenarios skip (not fail) when node is not installed.

Run from chauffeur/:  python tests/test_hero_card_phone.py
"""
import html as _html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(APP_DIR)
TPL = os.path.join(APP_DIR, 'templates')
COMPONENT = os.path.join(TPL, 'components', 'hero_card.html')
APP_HTML = os.path.join(TPL, 'app.html')
SHELL_CSS = os.path.join(APP_DIR, 'static', 'pwa_shell.css')


class Skip(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


# --- fixtures --------------------------------------------------------------

NOW = '2026-11-03T15:12:00'

START_RUN = "openActionSheet('Home','Riverside fields','Soccer practice','soccer','init_soccer')"
COVER_RUN = "openEventModal('soccer')"
DONE_RUN = "toggleRoutine('r1', true)"

# The shape Task 2's pwaHeroNext produces for a drive.
DRIVE_NEXT = {
    'kind': 'drive', 'start': '2026-11-03T16:00:00', 'end': '2026-11-03T17:00:00',
    'title': 'Take Maya to soccer practice', 'location': 'Riverside fields',
    'leave_at': '2026-11-03T15:40:00', 'leave_label': 'Leave at 3:40 PM',
    'travel_mins': 18, 'driver': None, 'live': False, 'minutes_until': 28,
    'meta': '18 min drive · the Highlander',
    'actions': [{'label': 'Start drive', 'run': START_RUN},
                {'label': 'Ask for cover', 'run': COVER_RUN}],
}

ROUTINE_NEXT = {
    'kind': 'routine', 'start': '2026-11-03T16:00:00', 'end': '2026-11-03T16:30:00',
    'title': 'Piano practice', 'location': '', 'live': False, 'driver': None,
    'actions': [{'label': 'Done', 'run': DONE_RUN}],
}
ROUTINE_DURING = '2026-11-03T16:10:00'

# A passenger's next ride carries the ride row's own buttons (slice 6): up to
# THREE on the phone, in order; an entry missing its label or run never paints.
RIDE_NEXT = {
    'kind': 'ride', 'start': '2026-11-03T16:00:00', 'end': '2026-11-03T17:00:00',
    'title': 'Soccer practice', 'location': 'Riverside fields', 'live': False, 'driver': None,
    'actions': [{'label': 'Where?', 'run': "pwaWhere('d1')"},
                {'label': 'Message', 'run': "messageMember('d1')"},
                {'label': 'Add a moment', 'run': "openEventThread('soccer')"},
                {'label': 'Broken'}, {'run': "nope()"}],
}

# A wall-shaped hero that walks more of the wall template's branches (colour,
# driver, arrive-by, optional, pack chip, outing), for the golden only.
WALL_RICH_NEXT = {
    'id': 'e1', 'kind': 'event', 'title': 'Soccer <Practice> & "Drills"',
    'location': "Riverside fields", 'at': '4:00 PM',
    'start': '2026-11-03T16:00:00', 'end': '2026-11-03T17:00:00',
    'leave_at': '2026-11-03T15:40:00', 'leave_label': '3:40 PM',
    'travel_mins': 18, 'traffic_delay_mins': 4, 'driver': 'Mom', 'color': '#e11d48',
    'optional': True, 'optional_decision': None,
    'arrive_by': {'arrive_label': '3:50 PM', 'short_label': 'there by 3:50',
                  'reason': 'warm-up'},
    'pack': {'needed': 3, 'packed': 1},
    'outing': {'then': [{'title': 'Groceries', 'at': '5:15 PM'}], 'back_at': '6:00 PM'},
}


# --- node harness ----------------------------------------------------------

_PROBE = r"""
const fs = require('fs');
const vm = require('vm');
const [headPath, workPath, dataPath] = process.argv.slice(2);
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

function body(src) {
    const m = /<script[^>]*>([\s\S]*?)<\/script>/.exec(src);
    if (!m) throw new Error('no <script> block in hero_card.html');
    return m[1].replace(/\{%[\s\S]*?%\}/g, '').replace(/\{\{[\s\S]*?\}\}/g, '""');
}

// frozenIso: a clock pinned for `new Date()` with no argument, so the wall
// path (which reads its own clock) renders the same text in HEAD and in the
// working tree. Absent, the real clock runs, which proves the phone path
// reads opts.now rather than the machine's time.
function load(src, frozenIso) {
    const ctx = { window: {}, console: console };
    ctx.document = { createElement: () => ({ style: {} }), querySelector: () => null,
                     getElementById: () => null, documentElement: { style: {} } };
    if (frozenIso) {
        const Real = Date;
        const fixed = new Real(frozenIso).getTime();
        class Frozen extends Real {
            constructor(...a) { if (a.length === 0) super(fixed); else super(...a); }
            static now() { return fixed; }
        }
        ctx.Date = Frozen;
    }
    vm.createContext(ctx);
    vm.runInContext(body(src), ctx);
    const hc = ctx.window.HeroCard;
    if (!hc) throw new Error('window.HeroCard was not defined');
    return { hc, Date: ctx.Date || Date };
}

function attempt(fn) {
    try { return { ok: true, value: fn() }; }
    catch (e) { return { ok: false, error: String(e && e.stack || e) }; }
}

const out = { golden: {}, phone: {}, countdown: {} };
const head = load(fs.readFileSync(headPath, 'utf8'), data.now);
const workFrozen = load(fs.readFileSync(workPath, 'utf8'), data.now);
const wallOpts = { plain: {}, light: { isLight: true }, compact: { compact: true } };
for (const [nk, next] of Object.entries(data.wall)) {
    for (const [ok, opts] of Object.entries(wallOpts)) {
        const key = nk + '/' + ok;
        out.golden[key] = {
            head: attempt(() => head.hc.html(next, Object.assign({}, opts))),
            work: attempt(() => workFrozen.hc.html(next, Object.assign({}, opts))),
        };
    }
}

const work = load(fs.readFileSync(workPath, 'utf8'), null);
for (const [k, c] of Object.entries(data.phone)) {
    const now = new Date(c.now);
    out.phone[k] = attempt(() => work.hc.html(c.next, { phone: true, now }));
    out.countdown[k] = attempt(() => work.hc.countdown(c.next, now).text);
}
process.stdout.write(JSON.stringify(out));
"""

_CACHE = {}


def _node_results():
    if 'r' in _CACHE:
        return _CACHE['r']
    node = shutil.which('node')
    if not node:
        raise Skip('node is not installed - the hero card was not run')
    git = subprocess.run(['git', 'show', 'HEAD:chauffeur/templates/components/hero_card.html'],
                         cwd=REPO, capture_output=True)
    check(git.returncode == 0,
          f"could not read the committed hero_card.html: {git.stderr.decode('utf-8', 'replace')}")
    scratch = tempfile.mkdtemp(prefix='chauffeur_hero_phone_')
    head_path = os.path.join(scratch, 'hero_card_head.html')
    with open(head_path, 'wb') as f:
        f.write(git.stdout)
    probe = os.path.join(scratch, 'probe.js')
    with open(probe, 'w', encoding='utf-8') as f:
        f.write(_PROBE)
    data_path = os.path.join(scratch, 'data.json')
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump({
            'now': NOW,
            'wall': {'drive': DRIVE_NEXT, 'rich': WALL_RICH_NEXT},
            'phone': {
                'drive': {'next': DRIVE_NEXT, 'now': NOW},
                'routine_before': {'next': ROUTINE_NEXT, 'now': NOW},
                'routine_during': {'next': ROUTINE_NEXT, 'now': ROUTINE_DURING},
                'ride_three': {'next': RIDE_NEXT, 'now': NOW},
            },
        }, f)
    proc = subprocess.run([node, probe, head_path, COMPONENT, data_path],
                          capture_output=True, text=True, encoding='utf-8', timeout=60)
    check(proc.returncode == 0, f"the node probe crashed:\n{proc.stderr}")
    _CACHE['r'] = json.loads(proc.stdout)
    return _CACHE['r']


def _phone(key):
    r = _node_results()
    res = r['phone'][key]
    check(res['ok'], f"HeroCard.html(next, {{phone:true, now}}) threw for {key}:\n{res.get('error')}")
    cd = r['countdown'][key]
    check(cd['ok'], f"HeroCard.countdown threw for {key}: {cd.get('error')}")
    return res['value'] or '', cd['value'] or ''


# --- a tiny DOM over the markup ---------------------------------------------

_VOID = {'br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'col', 'embed'}


class _Els(HTMLParser):
    """Every element with its tag, attributes (unescaped by html.parser) and
    full text content."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.done = [], []

    def handle_starttag(self, tag, attrs):
        el = {'tag': tag, 'attrs': dict(attrs), 'text': ''}
        if tag in _VOID:
            self.done.append(el)
        else:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.done.append({'tag': tag, 'attrs': dict(attrs), 'text': ''})

    def handle_data(self, data):
        for el in self.stack:
            el['text'] += data

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]['tag'] == tag:
                self.done.extend(reversed(self.stack[i:]))
                del self.stack[i:]
                return


def _elements(markup):
    p = _Els()
    p.feed(markup)
    p.close()
    return p.done + p.stack


def _classes(el):
    return (el['attrs'].get('class') or '').split()


def _find(markup, cls, tag=None):
    return [e for e in _elements(markup)
            if cls in _classes(e) and (tag is None or e['tag'] == tag)]


def _text(el):
    return re.sub(r'\s+', ' ', el['text']).strip()


def _one(markup, cls, tag=None):
    found = _find(markup, cls, tag)
    check(len(found) == 1,
          f"expected exactly one {tag or ''}.{cls} in the phone hero, found {len(found)}:\n{markup}")
    return found[0]


def _assert_phone_section(out):
    check('class="pwa-hero"' in out,
          f"HeroCard.html(next, {{phone:true, now}}) must return the "
          f"<section class=\"pwa-hero\"> skin, got the wall markup:\n{out[:600]}")
    sec = _one(out, 'pwa-hero', 'section')
    check(sec, 'no section.pwa-hero')


# --- scenarios: the wall did not move ----------------------------------------

def scenario_wall_output_is_byte_identical_to_head():
    r = _node_results()
    check(r['golden'], 'no golden cases ran')
    for key, pair in sorted(r['golden'].items()):
        check(pair['head']['ok'], f"the COMMITTED HeroCard.html threw for {key}: {pair['head'].get('error')}")
        check(pair['work']['ok'], f"the working-tree HeroCard.html threw for {key}: {pair['work'].get('error')}")
        check(pair['head']['value'], f"the committed wall render for {key} was empty")
        check(pair['work']['value'] == pair['head']['value'],
              f"the wall's HeroCard.html moved for {key} - the board, the screensaver "
              f"and the kitchen overlay read it byte for byte.\nHEAD:\n{pair['head']['value']}"
              f"\nWORKING TREE:\n{pair['work']['value']}")


# --- scenarios: the phone skin -----------------------------------------------

def scenario_phone_drive_is_the_pwa_hero_section():
    out, _ = _phone('drive')
    _assert_phone_section(out)


def scenario_phone_drive_kicker_names_the_departure_and_the_countdown():
    out, cd = _phone('drive')
    _assert_phone_section(out)
    check(cd == 'leave in 28 min', f"fixture sanity: the countdown at 3:12 for a 3:40 leave: {cd!r}")
    k = _text(_one(out, 'pwa-hero-kicker'))
    check('Next departure' in k, f"a drive's kicker says 'Next departure': {k!r}")
    check(cd in k, f"the kicker carries HeroCard.countdown(next, now).text ({cd!r}): {k!r}")


def scenario_phone_drive_big_who_and_meta():
    out, _ = _phone('drive')
    _assert_phone_section(out)
    big = _one(out, 'pwa-hero-big', 'h2')
    check(_text(big) == 'Leave at 3:40 PM', f"a drive's big line is its leave_label: {_text(big)!r}")
    who = _text(_one(out, 'pwa-hero-who'))
    check(who == 'Take Maya to soccer practice', f"who is next.title: {who!r}")
    meta = _text(_one(out, 'pwa-hero-meta'))
    check('Riverside fields' in meta and '18 min drive' in meta,
          f"meta is place · travel (+ car): {meta!r}")


def scenario_phone_drive_has_two_buttons_running_the_actions():
    out, _ = _phone('drive')
    _assert_phone_section(out)
    buttons = [e for e in _elements(out) if e['tag'] == 'button']
    check(len(buttons) == 2, f"a drive with two actions renders exactly two buttons: {len(buttons)}")
    prim = _one(out, 'pwa-btn-primary', 'button')
    sec = _one(out, 'pwa-btn-secondary', 'button')
    check(_text(prim) == 'Start drive', f"primary label: {_text(prim)!r}")
    check(_html.unescape(prim['attrs'].get('onclick') or '') == START_RUN,
          f"primary onclick must be actions[0].run: {prim['attrs'].get('onclick')!r}")
    check(_text(sec) == 'Ask for cover', f"secondary label: {_text(sec)!r}")
    check(_html.unescape(sec['attrs'].get('onclick') or '') == COVER_RUN,
          f"secondary onclick must be actions[1].run: {sec['attrs'].get('onclick')!r}")
    check(buttons[0] is prim or _classes(buttons[0]) == _classes(prim),
          "the primary button comes first")


def scenario_phone_ride_paints_the_rows_three_buttons():
    out, _ = _phone('ride_three')
    buttons = [e for e in _elements(out) if e['tag'] == 'button']
    check([_text(b) for b in buttons] == ['Where?', 'Message', 'Add a moment'],
          f"a ride hero paints its three row buttons in order and drops entries without a label or run: {[_text(b) for b in buttons]!r}")
    check('undefined' not in out, "no button reads or runs 'undefined'")


def scenario_phone_routine_before_start_is_up_next_with_one_button():
    out, cd = _phone('routine_before')
    _assert_phone_section(out)
    k = _text(_one(out, 'pwa-hero-kicker'))
    check('Up next' in k and 'Right now' not in k, f"a routine not yet started reads 'Up next': {k!r}")
    check(cd and cd in k, f"the kicker carries the countdown ({cd!r}): {k!r}")
    buttons = [e for e in _elements(out) if e['tag'] == 'button']
    check(len(buttons) == 1, f"one action renders one button: {len(buttons)}")
    check(_text(buttons[0]) == 'Done' and 'pwa-btn-primary' in _classes(buttons[0]),
          f"the lone button is the primary 'Done': {buttons[0]}")
    check(_html.unescape(buttons[0]['attrs'].get('onclick') or '') == DONE_RUN,
          f"Done runs actions[0].run: {buttons[0]['attrs'].get('onclick')!r}")
    check(not _find(out, 'pwa-btn-secondary'), "no secondary button without a second action")
    who = _text(_one(out, 'pwa-hero-who'))
    check(who == 'Piano practice', f"who is next.title: {who!r}")


def scenario_phone_routine_underway_is_right_now():
    out, cd = _phone('routine_during')
    _assert_phone_section(out)
    k = _text(_one(out, 'pwa-hero-kicker'))
    check('Right now' in k, f"a routine inside start..end reads 'Right now': {k!r}")
    check(cd and cd in k, f"the kicker carries the countdown ({cd!r}): {k!r}")
    check(len([e for e in _elements(out) if e['tag'] == 'button']) == 1, "still one button")


def scenario_phone_markup_has_no_script_and_no_inline_hue():
    for key in ('drive', 'routine_before', 'routine_during'):
        out, _ = _phone(key)
        _assert_phone_section(out)
        check('<script' not in out.lower(), f"the phone hero carries no <script> ({key})")
        bad = re.findall(r'style\s*=\s*"[^"]*(?:hsl|rgb|#[0-9a-fA-F]{3})[^"]*"', out)
        check(not bad, f"the phone accent comes from CSS tokens, not an inline hue ({key}): {bad}")


# --- scenarios: the page loads it, the sheet skins it ------------------------

def scenario_app_html_includes_hero_card_and_agenda_row():
    src = _read(APP_HTML)
    for comp in ('hero_card', 'agenda_row'):
        check(re.search(r"\{%\s*include\s+['\"]components/" + comp + r"\.html['\"]\s*%\}", src),
              f"app.html must include components/{comp}.html (the phone shares the wall's builder)")


def scenario_pwa_shell_css_has_the_hero_skin():
    css = _read(SHELL_CSS)
    check(re.search(r'\.pwa-hero\s*\{', css), "pwa_shell.css has no `.pwa-hero {` rule")
    for sel in ('.pwa-hero-kicker', '.pwa-btn-primary', '.pwa-btn-secondary'):
        check(re.search(re.escape(sel) + r'(?![\w-])', css), f"pwa_shell.css has no {sel} rule")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Skip as e:
            print(f"  skip  {fn.__name__}: {e}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} hero card phone scenarios passed")
    sys.exit(1 if failed else 0)
