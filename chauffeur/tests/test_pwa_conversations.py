"""The adult Messages list's rows, checked by RUNNING `pwaTimeLabel(ts, now)`,
`pwaPreviewLine(last, ctx)` and `pwaConversationRows(channels, ctx)` under node
with no `document` and no `window`.

PWA reimagined slice 4, Task 1 (task-1-brief.md). The three functions live at
the top level of static/pwa_messages.js; a missing one FAILS, never skips.
Missing node prints `  skip`.

CHANNEL PAYLOAD (GET api/channels?member_id=..., already sorted by last activity)
  channel = {id, kind: 'family'|'dm'|'group'|'event', member_ids: [memberId],
             title, last_message: {id, ts (seconds), body, sender_member_id,
             attachment} | null, unread: int}
  The Argyle DM is the 'dm' channel whose member_ids holds 'argyle'.

CTX (the pure functions never read the page; the page passes these in)
  members: [{id, name}]              first name = name.split(' ')[0]
  meId, now (a Date or ms), argyleAllowed
  display(channel) -> {name, color, avatar, image?}   (stands in for channelDisplay)
  previewLabel(last) -> string                        (stands in for momentPreviewLabel)

RULINGS PINNED HERE
  - time label: same day h:mm 12-hour, no leading zero, no AM/PM (9:40, 12:05);
    yesterday 'Yesterday'; within six days a short weekday ('Mon'); same year
    'Oct 28'; otherwise 'Oct 31, 2025'. Weekday and date text is computed in
    Python from the fixture dates, never from the real clock.
  - pinned = family first, then the Argyle DM, else a synthetic Argyle row when
    ctx.argyleAllowed; chats = every other channel in payload order.
  - unreadStyle: 0 'none', 1 'dot', >1 'count'.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_pwa_conversations.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import check, clock_source, pure_source, run_node  # noqa: E402

WANTED = ['pwaTimeLabel', 'pwaPreviewLine', 'pwaConversationRows']


def WD(y, m, d):
    return datetime.date(y, m, d).strftime('%a')


MON = WD(2026, 11, 2)    # two days before now
SAT = WD(2026, 10, 31)   # four days before now: inside the six-day window
YEST = 'Yesterday'


PROBE = r"""
// local-time seconds, so the labels never depend on the machine's zone
const T = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi, 0).getTime() / 1000;
const NOW = new Date(2026, 10, 4, 15, 12, 0);   // 2026-11-04T15:12 local
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};

const MEMBERS = [{id: 'me', name: 'Alex Rivera'}, {id: 'lorena', name: 'Lorena Diaz'},
                 {id: 'sam', name: 'Sam Rivera'}];
const items = (a) => (a && a.items) || [];
// same return shapes as templates/app.html momentPreviewLabel
const previewLabel = (msg) => {
  const its = items(msg.attachment);
  const clip = (msg.attachment || {}).kind === 'video';
  if (msg.body) return (clip ? '🎥 ' : '📷 ') + msg.body;
  if (its.length > 1) return '📷 ' + its.length + (its.every(i => i.kind === 'video') ? ' clips' : ' photos');
  return clip ? '🎥 Clip' : '📷 Photo';
};
// same return shapes as templates/app.html channelDisplay
const display = (c) => {
  if (c.kind === 'family') return {name: 'Family', color: '#3b82f6', avatar: '👨‍👩‍👧‍👦'};
  if (c.kind === 'event') return {name: c.title || 'Event chat', color: '#8b5cf6', avatar: '📸'};
  if (c.kind === 'group') return {name: c.title || 'Group', color: '#10b981', avatar: '👥'};
  if (c.member_ids.includes('argyle')) return {name: 'Argyle', color: '#8b5cf6', avatar: '✨'};
  return {name: 'Lorena Diaz', color: '#ec4899', avatar: 'L', image: '/img/lorena.png'};
};
const CTX = (over) => Object.assign({meId: 'me', members: MEMBERS, now: NOW, argyleAllowed: true,
                                      display, previewLabel}, over || {});

const msg = (id, ts, body, from, attachment) =>
  ({id, ts, body, sender_member_id: from, attachment: attachment || null});
const FAMILY = {id: 'ch-fam', kind: 'family', member_ids: ['me', 'lorena', 'sam'], title: '', unread: 0,
                last_message: msg('m1', T(2026, 11, 4, 9, 40), 'Pizza tonight?', 'sam')};
const ARGYLE_DM = {id: 'ch-arg', kind: 'dm', member_ids: ['me', 'argyle'], title: '', unread: 1,
                   last_message: msg('m2', T(2026, 11, 3, 18, 5), 'Dinner is at six.', 'argyle')};
const LORENA_DM = {id: 'ch-lor', kind: 'dm', member_ids: ['me', 'lorena'], title: '', unread: 2,
                   last_message: msg('m3', T(2026, 11, 4, 15, 12), 'Did you move the dentist?', 'lorena')};
const EVENT = {id: 'ch-evt', kind: 'event', member_ids: ['me', 'sam'], title: 'Soccer', unread: 0,
               last_message: msg('m4', T(2026, 11, 2, 12, 0), '', 'me',
                 {kind: 'image', items: [{kind: 'image'}, {kind: 'image'}, {kind: 'image'}]})};
const GROUP = {id: 'ch-grp', kind: 'group', member_ids: ['me', 'lorena', 'sam'], title: 'Carpool', unread: 0,
               last_message: msg('m5', T(2025, 10, 31, 8, 0), 'Thanks all', 'me')};
const EMPTY = {id: 'ch-new', kind: 'group', member_ids: ['me', 'sam'], title: 'New', unread: 0, last_message: null};
// payload order is the server's: most recent activity first (family is NOT first here)
const PAYLOAD = [LORENA_DM, EVENT, FAMILY, ARGYLE_DM, GROUP];
const NO_DM = [LORENA_DM, FAMILY, EVENT, GROUP];
const rowsOf = (cs, over) => pwaConversationRows(cs, CTX(over));
const brief = (r) => ({id: r.id, kind: r.kind, name: r.name, time: r.time, preview: r.preview,
                       unread: r.unread, unreadStyle: r.unreadStyle});

const labels = () => {
  const L = (y, mo, d, h, mi) => pwaTimeLabel(T(y, mo, d, h, mi), NOW);
  return {
    today_morning: L(2026, 11, 4, 9, 40),
    today_now: L(2026, 11, 4, 15, 12),
    today_afternoon: L(2026, 11, 4, 15, 5),
    today_noon: L(2026, 11, 4, 12, 5),
    today_after_midnight: L(2026, 11, 4, 0, 5),
    yesterday_evening: L(2026, 11, 3, 23, 50),
    yesterday_morning: L(2026, 11, 3, 0, 10),
    monday: L(2026, 11, 2, 10, 0),
    saturday: L(2026, 10, 31, 10, 0),
    same_year: L(2026, 10, 28, 10, 0),
    january: L(2026, 1, 15, 10, 0),
    last_year: L(2025, 10, 31, 10, 0),
    now_as_ms: pwaTimeLabel(T(2026, 11, 4, 9, 40), NOW.getTime()),
  };
};

// slice 5 task 1: pwaTimeLabel(ts, now, opts), opts.use24h words today's time as HH:mm
const labels24 = () => {
  const O = {use24h: true};
  return {
    morning: pwaTimeLabel(T(2026, 11, 4, 9, 40), NOW, O),
    afternoon: pwaTimeLabel(T(2026, 11, 4, 16, 40), NOW, O),
    after_midnight: pwaTimeLabel(T(2026, 11, 4, 0, 5), NOW, O),
    afternoon_h12: pwaTimeLabel(T(2026, 11, 4, 16, 40), NOW, {use24h: false}),
    afternoon_no_opts: pwaTimeLabel(T(2026, 11, 4, 16, 40), NOW),
    yesterday: pwaTimeLabel(T(2026, 11, 3, 23, 50), NOW, O),
    monday: pwaTimeLabel(T(2026, 11, 2, 10, 0), NOW, O),
  };
};

const CASES = {
  labels24,
  rows_full: () => { const r = rowsOf(PAYLOAD); return {pinned: r.pinned.map(brief), chats: r.chats.map(brief)}; },
  rows_full_shape: () => { const r = rowsOf(PAYLOAD);
    const all = r.pinned.concat(r.chats);
    return {keys: all.map(x => Object.keys(x).sort()),
            lorena: r.chats[0], family: r.pinned[0], argyle: r.pinned[1]}; },
  rows_no_dm: () => { const r = rowsOf(NO_DM); return {pinned: r.pinned, chats: r.chats.map(x => x.id)}; },
  rows_no_dm_not_allowed: () => { const r = rowsOf(NO_DM, {argyleAllowed: false});
    return {pinned: r.pinned.map(x => x.id), chats: r.chats.map(x => x.id)}; },
  rows_reordered: () => { const r = rowsOf([GROUP, ARGYLE_DM, EVENT, FAMILY, LORENA_DM]);
    return {pinned: r.pinned.map(x => x.id), chats: r.chats.map(x => x.id)}; },
  rows_empty_channel: () => rowsOf([FAMILY, EMPTY]).chats.map(brief),
  labels,
  pv_mine: () => pwaPreviewLine(msg('x', 1, 'On my way', 'me'), CTX()),
  pv_other: () => pwaPreviewLine(LORENA_DM.last_message, CTX()),
  pv_argyle: () => pwaPreviewLine(ARGYLE_DM.last_message, CTX()),
  pv_photos: () => pwaPreviewLine(EVENT.last_message, CTX()),
  pv_photo_with_body: () => pwaPreviewLine(msg('y', 1, 'Look', 'lorena', {kind: 'image', items: [{kind: 'image'}]}), CTX()),
  pv_null: () => pwaPreviewLine(null, CTX()),
  pv_unknown_sender: () => pwaPreviewLine(msg('z', 1, 'Hi', 'ghost'), CTX()),
};
for (const [name, fn] of Object.entries(CASES)) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String((e && e.stack) || e)}; }
}
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _out():
    if 'out' not in _CACHE:
        _CACHE['out'] = run_node(clock_source() + pure_source('pwa_messages.js', WANTED) + '\n' + PROBE)
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value']


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_family_then_argyle_pinned():
    got = _case('rows_full')
    if got is None:
        return
    check([r['id'] for r in got['pinned']] == ['ch-fam', 'ch-arg'],
          f"pinned is the family channel then the Argyle DM, wherever they sit in the payload: {got['pinned']!r}")
    fam, arg = got['pinned']
    check(fam['kind'] == 'family' and fam['name'] == 'Family' and fam['time'] == '9:40'
          and fam['preview'] == 'Sam: Pizza tonight?',
          f"family row {fam!r}")
    check(arg['kind'] == 'dm' and arg['name'] == 'Argyle' and arg['time'] == YEST
          and arg['preview'] == 'Argyle: Dinner is at six.' and arg['unread'] == 1,
          f"the real Argyle DM is the Argyle row (named through display), never a synthetic one: {arg!r}")
    shape = _case('rows_full_shape')
    want_keys = sorted(['id', 'kind', 'name', 'color', 'avatar', 'image', 'time', 'preview', 'unread', 'unreadStyle'])
    for ks in shape['keys']:
        check(all(k in ks for k in want_keys), f"every row carries {want_keys!r}, got {ks!r}")
    check(shape['lorena']['color'] == '#ec4899' and shape['lorena']['avatar'] == 'L'
          and shape['lorena']['image'] == '/img/lorena.png',
          f"color, avatar and image come from ctx.display: {shape['lorena']!r}")
    check(shape['family']['avatar'] == '👨‍👩‍👧‍👦' and shape['family']['color'] == '#3b82f6',
          f"family row display {shape['family']!r}")


def scenario_argyle_synthetic_when_no_dm():
    got = _case('rows_no_dm')
    if got is None:
        return
    check([r['id'] for r in got['pinned']] == ['ch-fam', None],
          f"no Argyle DM + argyleAllowed: family then a synthetic Argyle row (id null): {got['pinned']!r}")
    syn = got['pinned'][1]
    want = {'id': None, 'kind': 'argyle', 'name': 'Argyle', 'preview': 'Ask me anything.', 'time': ''}
    check(all(syn.get(k) == v for k, v in want.items()), f"synthetic row {syn!r}, expected {want!r}")
    check(got['chats'] == ['ch-lor', 'ch-evt', 'ch-grp'], f"chats exclude the pinned family: {got['chats']!r}")
    off = _case('rows_no_dm_not_allowed')
    check(off['pinned'] == ['ch-fam'], f"argyleAllowed false and no DM: no Argyle row at all: {off['pinned']!r}")
    check(off['chats'] == ['ch-lor', 'ch-evt', 'ch-grp'], f"chats {off['chats']!r}")


def scenario_chats_keep_payload_order():
    got = _case('rows_full')
    if got is None:
        return
    check([r['id'] for r in got['chats']] == ['ch-lor', 'ch-evt', 'ch-grp'],
          f"chats are every non-pinned channel in payload order (the server sorts): {got['chats']!r}")
    re_ = _case('rows_reordered')
    check(re_['pinned'] == ['ch-fam', 'ch-arg'] and re_['chats'] == ['ch-grp', 'ch-evt', 'ch-lor'],
          f"a different payload order flows through untouched: {re_!r}")


def scenario_time_labels():
    got = _case('labels')
    if got is None:
        return
    exp = {
        'today_morning': '9:40',
        'today_now': '3:12',
        'today_afternoon': '3:05',
        'today_noon': '12:05',
        'today_after_midnight': '12:05',
        'yesterday_evening': YEST,
        'yesterday_morning': YEST,
        'monday': MON,
        'saturday': SAT,
        'same_year': 'Oct 28',
        'january': 'Jan 15',
        'last_year': 'Oct 31, 2025',
        'now_as_ms': '9:40',
    }
    for name, want in exp.items():
        check(got[name] == want, f"{name}: got {got[name]!r}, expected {want!r}")


def scenario_time_labels_honour_use24h():
    """{use24h: true} words only today's clock time: 09:40, 16:40, 00:05;
    Yesterday, the weekday and dates are unchanged; false/absent stays 4:40."""
    got = _case('labels24')
    if got is None:
        return
    exp = {'morning': '09:40', 'afternoon': '16:40', 'after_midnight': '00:05',
           'afternoon_h12': '4:40', 'afternoon_no_opts': '4:40',
           'yesterday': YEST, 'monday': MON}
    for name, want in exp.items():
        check(got[name] == want, f"use24h {name}: got {got[name]!r}, expected {want!r}")


def scenario_preview_lines():
    exp = {
        'pv_mine': 'You: On my way',
        'pv_other': 'Lorena: Did you move the dentist?',
        'pv_argyle': 'Argyle: Dinner is at six.',
        'pv_photos': 'You: 📷 3 photos',
        'pv_photo_with_body': 'Lorena: 📷 Look',
        'pv_null': 'No messages yet',
    }
    for name, want in exp.items():
        got = _case(name)
        if got is None:
            return
        check(got == want, f"{name}: got {got!r}, expected {want!r}")
    unk = _case('pv_unknown_sender')
    check(unk.endswith('Hi'), f"an unknown sender still shows the text: {unk!r}")
    rows = _case('rows_empty_channel')
    check(rows[0]['preview'] == 'No messages yet' and rows[0]['time'] == '',
          f"a channel with no last_message reads 'No messages yet' with an empty time: {rows!r}")


def scenario_unread_styles():
    got = _case('rows_full')
    if got is None:
        return
    by = {r['id']: r for r in got['pinned'] + got['chats']}
    check((by['ch-fam']['unread'], by['ch-fam']['unreadStyle']) == (0, 'none'), f"0 is none: {by['ch-fam']!r}")
    check((by['ch-arg']['unread'], by['ch-arg']['unreadStyle']) == (1, 'dot'), f"1 is a dot: {by['ch-arg']!r}")
    check((by['ch-lor']['unread'], by['ch-lor']['unreadStyle']) == (2, 'count'), f"2 is a count: {by['ch-lor']!r}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {fn.__name__}: {e}")
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa conversation scenarios passed")
    sys.exit(1 if failed else 0)
