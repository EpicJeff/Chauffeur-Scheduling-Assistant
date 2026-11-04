"""My Day's greeting and Argyle's one sentence, checked by RUNNING
`pwaGreeting`, `pwaBriefFacts` and `pwaBriefSentence` under node with no
`document` and no `window`.

PWA reimagined slice 1, Task 3 (task-3-brief.md):
- `pwaGreeting(hour, name)` -> {word, first}: 05-11 'Good morning', 12-16
  'Good afternoon', 17-04 'Good evening'; `first` is the first whitespace
  token of the name, or 'there' when it is empty.
- `pwaBriefFacts({rows, role, isDriver, needs})` counts drive / ride /
  session rows and turns Needs-you cards into `unusual` facts whose rank is
  the card's rank: needs_driver -> "<title> <day> still needs a driver.",
  status -> "<status label> for <person> today." (or "<status label> today." with no person).
- `pwaBriefSentence(facts)`: "Nothing on the road today." / "One drive
  today" / "<N spelled out up to twelve> drives today", plus " and <n>
  ride(s)", a full stop, then one space and the TOP-ranked unusual text.
  Never more than two sentences; never a number the facts do not hold.

The cards in `facts_from_cards` are built by hand in Task 4's card shape
(`{id, kind, icon, title, why, deadline, rank, open}`) so this file does not
depend on `pwaNeedsYou` being built first.

Review fixes pinned (2026-11-03): the unusual text is appended verbatim
('Dr. Patel' is not rewritten to 'Dr; Patel'); rides with no drives read
'One ride today.' / 'Two rides today.', never 'Zero drives'; a status with
no person (built by hand AND by `pwaNeedsYou`, which this file now also
extracts) never reads 'undefined'.

The functions live in static/pwa_myday.js; a missing one FAILS, never skips.
Missing node prints `  skip`.

Run from chauffeur/:  python tests/test_pwa_brief_sentence.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import check, pure_source, run_node  # noqa: E402

WANTED = ['pwaGreeting', 'pwaBriefSentence', 'pwaBriefFacts', 'pwaNeedsYou']

UNUSUAL = [
    {'kind': 'status', 'text': 'Sick day for Maya today.', 'rank': 3},
    {'kind': 'needs_driver', 'text': "Kate's pickup Thursday still needs a driver.", 'rank': 1},
    {'kind': 'review', 'text': 'Sam finished Recycling and is waiting on your OK.', 'rank': 2},
]

PROBE = r"""
const UNUSUAL = %(unusual)s;
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};
function F(drives, rides, unusual) {
  return {drives, rides, sessions: 0, firstDrive: null, lastEnd: null, unusual: unusual || []};
}
function row(kind, start, end, title) {
  return {kind, start, end, title, place: '', meta: '', state: 'upcoming', primary: '', secondary: '',
          legId: '', eventId: ''};
}
const CASES = {
  greeting_bands: () => {
    const got = {};
    for (const h of [2, 4, 5, 8, 11, 12, 15, 16, 17, 20, 23]) got[h] = pwaGreeting(h, 'Jeff').word;
    return got;
  },
  first_name_only: () => ({full: pwaGreeting(9, 'Jeff Nelson').first, empty: pwaGreeting(9, '').first,
                           spaced: pwaGreeting(9, '  Lorena  Nelson ').first}),
  two_drives_plain: () => pwaBriefSentence(F(2, 0)),
  drive_and_ride: () => pwaBriefSentence(F(1, 1)),
  nothing_on_the_road: () => pwaBriefSentence(F(0, 0)),
  one_unusual_only: () => pwaBriefSentence(F(2, 0, UNUSUAL)),
  numbers_survive: () => ({three_two: pwaBriefSentence(F(3, 2)),
                           twelve: pwaBriefSentence(F(12, 0)),
                           thirteen: pwaBriefSentence(F(13, 0))}),
  never_three_sentences: () => [F(0, 0, UNUSUAL), F(1, 0, UNUSUAL), F(4, 3, UNUSUAL), F(1, 1, UNUSUAL.slice(2))]
    .map(pwaBriefSentence),
  facts_from_cards: () => {
    const rows = [
      row('event', '2026-11-03T12:00:00', '2026-11-03T13:00:00', 'Lunch with Ana'),
      row('drive', '2026-11-03T18:00:00', '2026-11-03T18:20:00', 'Pick-up: Swim'),
      row('drive', '2026-11-03T15:40:00', '2026-11-03T15:58:00', 'Drop-off: Swim'),
      row('ride', '2026-11-03T16:00:00', '2026-11-03T16:00:00', 'Lorena drives you to piano'),
      row('session', '2026-11-03T19:00:00', '2026-11-03T19:30:00', 'Piano practice'),
    ];
    const needs = [
      {id: 'needs_driver:piano', kind: 'needs_driver', icon: '\u{1F697}', title: "Kate's pickup needs a driver",
       why: 'Thursday 5:10 PM · nobody yet', deadline: new Date('2026-11-05T17:10:00'), rank: 1,
       open: {fn: 'openEventModal', args: ['piano-key']}},
      {id: 'status:sd1', kind: 'status', icon: '\u{1F912}', title: 'Maya: Sick day', why: 'Home all day',
       deadline: null, rank: 1, open: {fn: 'pwaOpenStatusSheet'}},
    ];
    const f = pwaBriefFacts({rows, role: 'parent', isDriver: true, needs});
    const plain = pwaBriefFacts({rows, role: 'parent', isDriver: true, needs: []});
    return {drives: f.drives, rides: f.rides, sessions: f.sessions,
            firstDrive: f.firstDrive ? f.firstDrive.title : null,
            unusual: (f.unusual || []).map(u => ({kind: u.kind, text: u.text, rank: u.rank})),
            plain_unusual: plain.unusual};
  },
  household_task_facts: () => {
    const card = (id, title, why) => ({id, kind: 'household_task', icon: '☑️', title, why,
                                       deadline: new Date('2026-11-03T00:00:00'), rank: 2, open: {screen: 'tasks'}});
    const needs = [card('household_task:h2', 'Call the plumber', 'overdue'),
                   card('household_task:h1', 'Take the bins out', 'due today')];
    return pwaBriefFacts({rows: [], role: 'parent', isDriver: true, needs}).unusual
      .filter(u => u.kind === 'household_task').map(u => u.text);
  },
  abbreviations_survive_in_unusual_text: () => pwaBriefSentence(F(1, 0, [
    {kind: 'needs_driver', text: 'Dr. Patel checkup Thursday still needs a driver.', rank: 1}])),
  one_ride_no_drives_reads_naturally: () => ({one: pwaBriefSentence(F(0, 1)), two: pwaBriefSentence(F(0, 2))}),
  status_without_a_person_has_no_undefined: () => {
    const hand = {id: 'status:sd9', kind: 'status', icon: '❄', title: 'Snow day', why: 'School closed',
                  deadline: null, rank: 1, open: {fn: 'pwaOpenStatusSheet'}};
    const built = pwaNeedsYou({role: 'parent', statusDays: [{id: 'sd9', status_name: 'Snow day', emoji: '❄',
                                                             line: 'School closed'}]}, new Date('2026-11-03T15:12:00'));
    const facts = needs => (pwaBriefFacts({rows: [], role: 'parent', isDriver: true, needs}).unusual || [])
      .filter(u => u.kind === 'status').map(u => u.text);
    return {hand: facts([hand]), built: facts(built), built_sentence: pwaBriefSentence(
      pwaBriefFacts({rows: [], role: 'parent', isDriver: true, needs: built}))};
  },
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
        import json
        _CACHE['out'] = run_node(pure_source('pwa_myday.js', WANTED) + '\n'
                                 + PROBE % {'unusual': json.dumps(UNUSUAL)})
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None, False
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value'], True


def _digits(s):
    return re.findall(r'\d+', s)


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_greeting_bands():
    got, ran = _case('greeting_bands')
    if not ran:
        return
    want = {2: 'Good evening', 4: 'Good evening', 5: 'Good morning', 8: 'Good morning',
            11: 'Good morning', 12: 'Good afternoon', 15: 'Good afternoon', 16: 'Good afternoon',
            17: 'Good evening', 20: 'Good evening', 23: 'Good evening'}
    for hour, word in want.items():
        check(got[str(hour)] == word, f"pwaGreeting({hour}) word {got[str(hour)]!r}, expected {word!r}")


def scenario_first_name_only():
    got, ran = _case('first_name_only')
    if not ran:
        return
    check(got['full'] == 'Jeff', f"'Jeff Nelson' greets {got['full']!r}, expected 'Jeff'")
    check(got['empty'] == 'there', f"an empty name greets {got['empty']!r}, expected 'there'")
    check(got['spaced'] == 'Lorena', f"'  Lorena  Nelson ' greets {got['spaced']!r}, expected 'Lorena'")


def scenario_two_drives_plain():
    got, ran = _case('two_drives_plain')
    if ran:
        check(got == 'Two drives today.', f"two drives read {got!r}, expected 'Two drives today.'")


def scenario_drive_and_ride():
    got, ran = _case('drive_and_ride')
    if ran:
        check(got == 'One drive today and one ride.',
              f"one drive + one ride read {got!r}, expected 'One drive today and one ride.'")


def scenario_nothing_on_the_road():
    got, ran = _case('nothing_on_the_road')
    if ran:
        check(got == 'Nothing on the road today.',
              f"no drives, no rides read {got!r}, expected 'Nothing on the road today.'")


def scenario_one_unusual_only():
    """Three unusual facts ranked 3, 1, 2: only the rank-1 text is appended."""
    got, ran = _case('one_unusual_only')
    if not ran:
        return
    top = UNUSUAL[1]['text']
    check(got == 'Two drives today. ' + top,
          f"expected 'Two drives today. {top}', got {got!r}")
    for u in (UNUSUAL[0], UNUSUAL[2]):
        check(u['text'] not in got, f"the rank-{u['rank']} fact leaked into the sentence: {got!r}")


def scenario_numbers_survive():
    """Counts are spelled out up to twelve; past that the digits ARE the
    count. No other number appears."""
    got, ran = _case('numbers_survive')
    if not ran:
        return
    s = got['three_two']
    check('Three' in s and 'two' in s, f"3 drives + 2 rides must read 'Three' and 'two', got {s!r}")
    check(not _digits(s), f"3 drives + 2 rides wrote a digit: {s!r}")
    check('Twelve' in got['twelve'] and not _digits(got['twelve']),
          f"12 drives must read 'Twelve' with no digit, got {got['twelve']!r}")
    check(_digits(got['thirteen']) == ['13'],
          f"13 drives must carry exactly the number 13, got {got['thirteen']!r}")


def scenario_never_three_sentences():
    got, ran = _case('never_three_sentences')
    if not ran:
        return
    for s in got:
        check(isinstance(s, str) and s.strip(), f"pwaBriefSentence returned {s!r}")
        check(s.strip().count('. ') <= 1, f"more than two sentences: {s!r}")
        check(s.strip().endswith('.'), f"the sentence does not end with a full stop: {s!r}")


def scenario_facts_from_cards():
    got, ran = _case('facts_from_cards')
    if not ran:
        return
    check((got['drives'], got['rides'], got['sessions']) == (2, 1, 1),
          f"rows hold 2 drives, 1 ride, 1 session; facts counted "
          f"{got['drives']!r}/{got['rides']!r}/{got['sessions']!r}")
    check(got['firstDrive'] == 'Drop-off: Swim',
          f"firstDrive is the earliest drive 'Drop-off: Swim', got {got['firstDrive']!r}")
    check(got['plain_unusual'] == [], f"no cards, no late drive: unusual must be [], got {got['plain_unusual']!r}")
    unusual = {u['kind']: u for u in got['unusual']}
    check(len(got['unusual']) == 2 and set(unusual) == {'needs_driver', 'status'},
          f"two cards must make two unusual facts (needs_driver, status), got {got['unusual']!r}")
    want = {'needs_driver': "Kate's pickup Thursday still needs a driver.",
            'status': 'Sick day for Maya today.'}
    for kind, text in want.items():
        check((unusual[kind]['text'] or '').lower() == text.lower(),
              f"{kind} fact reads {unusual[kind]['text']!r}, expected {text!r}")
        check(unusual[kind]['rank'] == 1, f"{kind} fact rank {unusual[kind]['rank']!r}, the card's rank is 1")


def scenario_abbreviations_survive_in_unusual_text():
    """The unusual text is appended as written: a full stop inside it
    ('Dr. Patel') is not a sentence break to rewrite."""
    got, ran = _case('abbreviations_survive_in_unusual_text')
    if not ran:
        return
    check('Dr. Patel' in got, f"'Dr. Patel' must survive verbatim, got {got!r}")
    check(got == 'One drive today. Dr. Patel checkup Thursday still needs a driver.',
          f"expected 'One drive today. Dr. Patel checkup Thursday still needs a driver.', got {got!r}")


def scenario_one_ride_no_drives_reads_naturally():
    """No drives, only rides: the count of drives is not read out as 'Zero'."""
    got, ran = _case('one_ride_no_drives_reads_naturally')
    if not ran:
        return
    check(got['one'] == 'One ride today.', f"0 drives + 1 ride read {got['one']!r}, expected 'One ride today.'")
    check(got['two'] == 'Two rides today.', f"0 drives + 2 rides read {got['two']!r}, expected 'Two rides today.'")


def scenario_status_without_a_person_has_no_undefined():
    """A family-wide status ('Snow day', no person) reads as itself. Checked
    on a hand-built card titled 'Snow day' AND on the card pwaNeedsYou builds
    from a statusDays row with no person_name, which is the real path."""
    got, ran = _case('status_without_a_person_has_no_undefined')
    if not ran:
        return
    for source in ('hand', 'built'):
        texts = got[source]
        check(len(texts) == 1, f"{source} status card must make one status fact, got {texts!r}")
        check('Snow day' in texts[0], f"{source} status fact must read 'Snow day', got {texts[0]!r}")
        check('undefined' not in texts[0], f"{source} status fact says 'undefined': {texts[0]!r}")
    check('undefined' not in got['built_sentence'],
          f"Argyle's sentence says 'undefined': {got['built_sentence']!r}")


def scenario_household_task_facts():
    got, ran = _case('household_task_facts')
    if ran:
        check(got == ['Call the plumber is overdue.', 'Take the bins out is due today.'],
              f"household_task cards read {got!r}, expected '<title> is overdue.' / '<title> is due today.'")


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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa brief sentence scenarios passed")
    sys.exit(1 if failed else 0)
