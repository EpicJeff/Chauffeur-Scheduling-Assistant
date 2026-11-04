"""My Day's Needs-you pile, ranked: `pwaNeedsYou(inputs, now)` checked by
RUNNING it under node with no `document` and no `window`.

PWA reimagined slice 1, Task 4 (task-4-brief.md). Every card is
`{id, kind, icon, title, why, deadline, rank, open}`:
- request: "<from_name> asks: <body truncated 60>", "waiting on your
  answer", no deadline, rank 2, open fn pwaOpenNeedRequests;
- review (canReview only): done chore "<claimed_by_name> finished <title>" /
  "<points> points waiting on your yes"; redemption "<member_name> wants
  <reward_title>" / "<cost> points"; funded pool "<title> is funded" /
  "ready to grant"; rank 3; open view chores, section reviews;
- needs_driver (canAssign, starts within 7 days): '🚗', "<title> needs a
  driver", "<weekday> <h:mm> · nobody yet", deadline = start, rank 1, open
  fn openEventModal with the event key;
- task (dueSoon + stillOpen): '📚', the title, "due <label>" / "overdue",
  deadline = due date, rank 4, open fn openKidTaskDetail [id];
- proposal (parent, any): ONE card "N proposed events", "from <source_from
  of the first>", deadline = earliest start, rank 3, open view family,
  anchor proposals-container;
- situation (group now): icon from its kind, title, why = next move,
  deadline = due_at, rank 2, open view family, anchor mind-container;
- status: the protocol emoji, "<person>: <status name>", the logistical
  line, no deadline, rank 1, open fn pwaOpenStatusSheet.
Sort: deadline cards first by deadline, then rank, then title; the rest by
rank then title. Empty inputs -> [].

Review fixes pinned (2026-11-03): one proposal is singular and a missing
`source_from` falls back to `source_subject` (or 'from a photo' / empty),
never 'from undefined'; the drop-off and pick-up legs of one event
(`{base}_dropoff` / `{base}_pickup`) make ONE needs-driver card; a status
day with no person is titled by its status name alone.

`now` is 2026-11-03T15:12 local (a Tuesday); 2026-11-05 is a Thursday.
The function lives in static/pwa_myday.js; a missing one FAILS, never skips.
Missing node prints `  skip`.

Run from chauffeur/:  python tests/test_pwa_needs_you.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import check, clock_source, pure_source, run_node  # noqa: E402

WANTED = ['pwaNeedsYou', 'pwaConflictOf']
ALLOWED_FNS = {'pwaOpenNeedRequests', 'openEventModal', 'openKidTaskDetail', 'pwaOpenStatusSheet'}

PROBE = r"""
const NOW = new Date('2026-11-03T15:12:00');
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {},
             day_ms: {'2026-11-03': [new Date('2026-11-03').getTime(), new Date('2026-11-03T00:00:00').getTime()]},
             ms: {pickup: new Date('2026-11-05T17:10:00').getTime(),
                  situation: new Date('2026-11-05T09:00:00').getTime(),
                  proposal: new Date('2026-11-05T17:00:00').getTime()}};

const REQUESTS = [{id: 'rq1', from_name: 'Sam', body: 'Can you pick me up?'}];
const REVIEWS = {
  chores: [{id: 'ch1', title: 'Recycling', state: 'done', claimed_by_name: 'Sam', points: 15}],
  redemptions: [{id: 'rd1', member_name: 'Maya', reward_title: 'Movie night', cost: 40}],
  pools: [{id: 'pl1', title: 'Trampoline', funded: true}],
};
const DUE_SOON = [{id: 't1', title: 'Math worksheet', due_date: '2026-11-04', label: 'tomorrow'}];
const STILL_OPEN = [{id: 't0', title: 'Reading log', due_date: '2026-10-30', label: 'Oct 30', overdue: true}];
const PROPOSALS = [{id: 'p1', start: '2026-11-05T17:00:00', source_from: 'coach@club.org'},
                   {id: 'p2', start: '2026-11-06T09:00:00', source_from: 'school@district.org'}];
const SITUATIONS = [
  {id: 's1', kind: 'finding', title: 'Thursday has no driver', next_move: 'Ask Lorena',
   due_at: '2026-11-05T09:00:00', group: 'now'},
  {id: 's2', kind: 'finding', title: 'Gym bag for Friday', next_move: 'Pack it Thursday night',
   due_at: '2026-11-04T07:00:00', group: 'later'},
];
const UNASSIGNED = [
  {id: 'piano', title: "Kate's pickup", start: '2026-11-05T17:10:00', end: '2026-11-05T17:10:00', key: 'piano-key'},
  {id: 'camp', title: 'Camp drop-off', start: '2026-11-12T08:00:00', end: '2026-11-12T08:00:00', key: 'camp-key'},
];
const STATUS_DAYS = [{id: 'sd1', person_name: 'Maya', status_name: 'Sick day', emoji: '\u{1F912}', line: 'Home all day'}];

function inputs(over) {
  return Object.assign({role: 'parent', requests: [], reviews: {chores: [], redemptions: [], pools: []},
                        dueSoon: [], stillOpen: [], proposals: [], situations: [], unassigned: [],
                        statusDays: [], canReview: true, canAssign: true}, over || {});
}
const FULL = () => inputs({requests: REQUESTS, reviews: REVIEWS, dueSoon: DUE_SOON, stillOpen: STILL_OPEN,
                           proposals: PROPOSALS, situations: SITUATIONS, unassigned: UNASSIGNED,
                           statusDays: STATUS_DAYS});
function cards(inp) {
  const got = pwaNeedsYou(inp, NOW);
  if (!Array.isArray(got)) return {not_an_array: String(got)};
  return got.map(c => ({id: c.id, kind: c.kind, icon: c.icon, title: c.title, why: c.why, rank: c.rank,
                        deadline_ms: c.deadline == null ? null : new Date(c.deadline).getTime(),
                        open: c.open}));
}
const LONG = 'Can you pick me up from the library after the robotics meeting runs late again tonight please';
const CASES = {
  // The calendar's Conflict rule, shared by buildFamilyCards and the pile
  // (pwaConflictOf over scheduleData.diagnostics[eventId], a map of reasons
  // {type, text}): a conflict only when every reason exists and none is an
  // optimization; one distinct text is the reason, mixed texts none.
  conflict_rule: () => ({
    empty: pwaConflictOf({}),
    none: pwaConflictOf(undefined),
    hard: pwaConflictOf({d1: {type: 'hard', text: 'Sam is in two places at 4:30'}, d2: {type: 'hard', text: 'Sam is in two places at 4:30'}}),
    mixed_text: pwaConflictOf({d1: {type: 'hard', text: 'A'}, d2: {type: 'hard', text: 'B'}}),
    optimization: pwaConflictOf({d1: {type: 'hard', text: 'A'}, d2: {type: 'optimization', text: 'cheaper'}}),
    missing_reason: pwaConflictOf({d1: {type: 'hard', text: 'A'}, d2: null}),
  }),
  empty_pile_is_absent: () => cards(inputs()),
  deadlines_come_first: () => cards(inputs({requests: REQUESTS, dueSoon: DUE_SOON})),
  needs_driver_outranks_review_on_the_same_day: () => cards(inputs({reviews: REVIEWS, unassigned: UNASSIGNED.slice(0, 1)})),
  non_parent_gets_no_reviews: () => cards(inputs({role: 'adult', canReview: false, canAssign: true,
    reviews: REVIEWS, proposals: PROPOSALS, unassigned: UNASSIGNED})),
  proposals_fold_into_one_card: () => cards(inputs({proposals: PROPOSALS})),
  status_is_rank_one_without_deadline: () => cards(inputs({requests: REQUESTS, statusDays: STATUS_DAYS})),
  unassigned_beyond_seven_days_is_skipped: () => cards(inputs({unassigned: UNASSIGNED})),
  request_body_is_truncated: () => cards(inputs({requests: [{id: 'rq2', from_name: 'Sam', body: LONG}]})),
  full_pile: () => cards(FULL()),
  // slice 5 task 1: pwaNeedsYou(inputs, now, opts), opts.use24h words the clock
  needs_driver_24h: () => {
    const inp = inputs({unassigned: UNASSIGNED.slice(0, 1)});
    const why = (opts) => (opts === undefined ? pwaNeedsYou(inp, NOW) : pwaNeedsYou(inp, NOW, opts))[0].why;
    return {h24: why({use24h: true}), h12_false: why({use24h: false}), h12_empty: why({}), h12_absent: why()};
  },
  // slice 6 task 1: an unconfirmed packing kit is a card (pwaNeedsYouInputs
  // feeds only unconfirmed kits; a confirmed one never reaches the input)
  packing_is_a_card: () => {
    const primary = "openActionSheet('Home','Riverside','Soccer practice','soccer','init_soccer')";
    const inp = inputs({packing: [{eventId: 'soccer', title: 'Soccer practice', items: ['soccer bag', 'water'],
      leaveAt: '2026-11-03T15:40:00', primary}]});
    return {cards: cards(inp), h24: pwaNeedsYou(inp, NOW, {use24h: true})[0].why,
            leave_ms: new Date('2026-11-03T15:40:00').getTime()};
  },
  confirmed_packing_is_not: () => ({empty: cards(inputs({packing: []})), absent: cards(inputs())}),
  one_proposal_is_singular_and_sourced: () => cards(inputs({proposals: [
    {id: 'p3', start: '2026-11-07T19:00:00', source_subject: 'Fall concert'}]})),
  proposal_without_a_source: () => cards(inputs({proposals: [{id: 'p4', start: '2026-11-07T19:00:00'}]})),
  needs_driver_merges_dropoff_and_pickup: () => cards(inputs({unassigned: [
    {id: 'piano_dropoff', title: 'Dropoff: Piano', start: '2026-11-05T16:50:00', end: '2026-11-05T16:50:00', key: 'piano-drop-key'},
    {id: 'piano_pickup', title: 'Pickup: Piano', start: '2026-11-05T18:00:00', end: '2026-11-05T18:00:00', key: 'piano-pick-key'},
    {id: 'chess_pickup', title: 'Pickup: Chess', start: '2026-11-04T17:00:00', end: '2026-11-04T17:00:00', key: 'chess-key'}]})),
  status_card_without_a_person: () => cards(inputs({statusDays: [
    {id: 'sd9', status_name: 'Snow day', emoji: '❄', line: 'School closed'}]})),
  household_task_due_today_is_a_card: () => ({
    today: cards(inputs({householdTasks: [{id: 'h1', title: 'Take the bins out', due_date: '2026-11-03',
      past_due: false, due_today: true, assigned_to_name: null}]})),
    overdue: cards(inputs({householdTasks: [{id: 'h2', title: 'Call the plumber', due_date: '2026-11-01',
      past_due: true, due_today: false, assigned_to_name: 'Lorena'}]})),
  }),
  thread_in_now_is_a_card: () => ({
    now: cards(inputs({threads: [{id: 'th1', kind: 'thread', title: 'Dentist for Sam',
      next_move: 'Call the office', due_at: '2026-11-05T09:00:00', group: 'now'}]})),
    soon: cards(inputs({threads: [{id: 'th2', kind: 'thread', title: 'Summer camp',
      next_move: 'Compare prices', due_at: '2026-11-20T09:00:00', group: 'soon'}]})),
  }),
  household_tasks_outrank_quiet_lists_but_not_a_needs_driver: () => cards(inputs({
    unassigned: UNASSIGNED.slice(0, 1),
    householdTasks: [{id: 'h2', title: 'Call the plumber', due_date: '2026-11-01', past_due: true,
      due_today: false, assigned_to_name: null}]})),
  a_closed_chores_door_is_not_a_crash: () => {
    // /api/chores answers 403 {"detail": "Requires chores.board"} for a scope
    // without the chores door; fetchChores used to store that object. The
    // pile must treat any non-array review source as empty, never throw.
    const out = pwaNeedsYou(inputs({canReview: true,
      reviews: {chores: {detail: 'Requires chores.board'}, redemptions: {detail: 'x'}, pools: null},
      requests: [{id: 'r1', from_name: 'Sam', body: 'Ride?'}]}), NOW);
    return out.map(c => c.kind);
  },
  // slice 5 task 5: the calendar's Conflict rule on the needs-driver card.
  // An unassigned row carries the calendar card's own fields, isConflict and
  // conflictReason (templates/app.html conflictFor / familyDriverChips).
  needs_driver_conflict_wording: () => {
    const rows = [
      {id: 'swim', title: 'Swim meet', start: '2026-11-05T17:10:00', end: '2026-11-05T17:10:00', key: 'swim-key',
       isConflict: true, conflictReason: 'Alex is driving Sam'},
      {id: 'chess', title: 'Chess club', start: '2026-11-04T17:00:00', end: '2026-11-04T17:00:00', key: 'chess-key',
       isConflict: false, conflictReason: 'stale reason'},
      {id: 'art', title: 'Art class', start: '2026-11-06T16:00:00', end: '2026-11-06T16:00:00', key: 'art-key',
       isConflict: true, conflictReason: null},
    ];
    const swim24 = pwaNeedsYou(inputs({unassigned: rows.slice(0, 1)}), NOW, {use24h: true})[0];
    return {cards: cards(inputs({unassigned: rows})), h24: swim24 && swim24.why};
  },
};
for (const [name, fn] of Object.entries(CASES)) {
  try { out.cases[name] = {value: fn()}; }
  catch (e) { out.cases[name] = {error: String((e && e.stack) || e)}; }
}
out.long = LONG;
console.log(JSON.stringify(out));
"""

_CACHE = {}


def _out():
    if 'out' not in _CACHE:
        _CACHE['out'] = run_node(clock_source() + pure_source('pwa_myday.js', WANTED) + '\n' + PROBE)
    return _CACHE['out']


def _cards(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    check(isinstance(got['value'], list), f"{name}: pwaNeedsYou did not return an array: {got['value']!r}")
    return got['value']


def _ms(key):
    return _out()['ms'][key]


def _open_has(card, **want):
    for k, v in want.items():
        check((card.get('open') or {}).get(k) == v,
              f"{card['kind']} card {card['title']!r} open.{k} is {(card.get('open') or {}).get(k)!r}, expected {v!r}")


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_empty_pile_is_absent():
    got = _cards('empty_pile_is_absent')
    if got is not None:
        check(got == [], f"nothing waiting must be [], got {got!r}")


def scenario_deadlines_come_first():
    got = _cards('deadlines_come_first')
    if got is None:
        return
    check([c['kind'] for c in got] == ['task', 'request'],
          f"a task due tomorrow comes before a request with no deadline, got {[c['kind'] for c in got]!r}")
    task, req = got
    check(task['title'] == 'Math worksheet' and task['why'] == 'due tomorrow' and task['rank'] == 4,
          f"task card {task!r}")
    check(task['icon'] == '\U0001F4DA', f"task icon {task['icon']!r}, expected the books")
    check(task['deadline_ms'] is not None, "a due-soon task's deadline is its due date, got none")
    _open_has(task, fn='openKidTaskDetail', args=['t1'])
    check(req['title'] == 'Sam asks: Can you pick me up?', f"request title {req['title']!r}")
    check(req['why'] == 'waiting on your answer' and req['rank'] == 2 and req['deadline_ms'] is None,
          f"request card {req!r}")
    check(req['icon'] == '\U0001F64B', f"request icon {req['icon']!r}")
    _open_has(req, fn='pwaOpenNeedRequests')


def scenario_needs_driver_outranks_review_on_the_same_day():
    got = _cards('needs_driver_outranks_review_on_the_same_day')
    if got is None:
        return
    kinds = [c['kind'] for c in got]
    check(kinds == ['needs_driver', 'review', 'review', 'review'],
          f"the uncovered pickup comes before the three reviews, got {kinds!r}")
    nd = got[0]
    check(nd['rank'] == 1 and nd['deadline_ms'] == _ms('pickup'),
          f"needs_driver card rank {nd['rank']!r}, deadline must be the event start: {nd!r}")
    check([c['title'] for c in got[1:]] == ['Maya wants Movie night', 'Sam finished Recycling',
                                            'Trampoline is funded'],
          f"reviews share rank 3 and no deadline, so they sort by title: {[c['title'] for c in got[1:]]!r}")


def scenario_non_parent_gets_no_reviews():
    got = _cards('non_parent_gets_no_reviews')
    if got is None:
        return
    kinds = [c['kind'] for c in got]
    check('review' not in kinds, f"canReview is false, yet review cards appeared: {kinds!r}")
    check('proposal' not in kinds, f"proposals are a parent's card, an adult got one: {kinds!r}")
    check(kinds == ['needs_driver'], f"an adult who can assign still sees the uncovered pickup, got {kinds!r}")


def scenario_proposals_fold_into_one_card():
    got = _cards('proposals_fold_into_one_card')
    if got is None:
        return
    check(len(got) == 1 and got[0]['kind'] == 'proposal', f"two proposals make ONE card, got {got!r}")
    p = got[0]
    check(p['title'] == '2 proposed events', f"proposal title {p['title']!r}, expected '2 proposed events'")
    check(p['why'] == 'from coach@club.org', f"proposal why {p['why']!r}, expected 'from coach@club.org'")
    check(p['deadline_ms'] == _ms('proposal'), "the proposal card's deadline is the earliest start (Thu 5:00 PM)")
    check(p['rank'] == 3, f"proposal rank {p['rank']!r}, expected 3")
    _open_has(p, view='family', anchor='proposals-container')


def scenario_status_is_rank_one_without_deadline():
    got = _cards('status_is_rank_one_without_deadline')
    if got is None:
        return
    check([c['kind'] for c in got] == ['status', 'request'],
          f"status (rank 1) comes before a request (rank 2), got {[c['kind'] for c in got]!r}")
    s = got[0]
    check(s['title'] == 'Maya: Sick day', f"status title {s['title']!r}, expected 'Maya: Sick day'")
    check(s['why'] == 'Home all day', f"status why {s['why']!r}, expected the logistical line")
    check(s['icon'] == '\U0001F912', f"status icon {s['icon']!r}, expected the protocol emoji")
    check(s['rank'] == 1 and s['deadline_ms'] is None, f"status card {s!r}")
    _open_has(s, fn='pwaOpenStatusSheet')


def scenario_unassigned_beyond_seven_days_is_skipped():
    got = _cards('unassigned_beyond_seven_days_is_skipped')
    if got is None:
        return
    check(len(got) == 1, f"the camp drop-off is 9 days out and must be skipped, got {[c['title'] for c in got]!r}")
    nd = got[0]
    check(nd['kind'] == 'needs_driver' and nd['title'] == "Kate's pickup needs a driver",
          f"needs_driver card {nd!r}")
    check(nd['icon'] == '\U0001F697', f"needs_driver icon {nd['icon']!r}")
    why = nd['why'] or ''
    check(why.startswith('Thursday') and '5:10' in why and why.endswith('· nobody yet'),
          f"needs_driver why {why!r}, expected 'Thursday 5:10 PM · nobody yet'")
    check(nd['deadline_ms'] == _ms('pickup'), "needs_driver deadline is the event start")
    _open_has(nd, fn='openEventModal')
    args = (nd.get('open') or {}).get('args')
    check(isinstance(args, list) and len(args) == 1 and isinstance(args[0], str) and args[0],
          f"openEventModal needs the one event key as its argument, got {args!r}")


def scenario_needs_driver_honours_use24h():
    """The same Thursday pickup (17:10): 'Thursday 17:10 · nobody yet' with
    {use24h: true}; the 12-hour wording stays with false, {} or no opts."""
    got = _out()
    if got is None:
        print("  skip  node is not installed")
        return
    got = got['cases']['needs_driver_24h']
    check('error' not in got, f"needs_driver_24h threw under node:\n{got.get('error')}")
    got = got['value']
    check(got['h24'] == 'Thursday 17:10 · nobody yet', f"use24h why {got['h24']!r}, expected 'Thursday 17:10 · nobody yet'")
    for key in ('h12_false', 'h12_empty', 'h12_absent'):
        why = got[key]
        check(why.startswith('Thursday') and '5:10' in why and 'PM' in why and why.endswith('· nobody yet'),
              f"{key} why {why!r}, expected the 12-hour 'Thursday 5:10 PM · nobody yet'")


def scenario_request_body_is_truncated():
    got = _cards('request_body_is_truncated')
    if got is None:
        return
    title = got[0]['title']
    long_body = _out()['long']
    check(title.startswith('Sam asks: ' + long_body[:50]), f"request title {title!r}")
    body = title[len('Sam asks: '):]
    check(len(body) <= 61, f"the body is truncated to 60 (plus an ellipsis at most), got {len(body)}: {body!r}")


def scenario_full_pile_is_ranked():
    """Deadlines first by time, then the rest by rank then title."""
    got = _cards('full_pile')
    if got is None:
        return
    want = [
        ('task', 'Reading log'),
        ('task', 'Math worksheet'),
        ('situation', 'Thursday has no driver'),
        ('proposal', '2 proposed events'),
        ('needs_driver', "Kate's pickup needs a driver"),
        ('status', 'Maya: Sick day'),
        ('request', 'Sam asks: Can you pick me up?'),
        ('review', 'Maya wants Movie night'),
        ('review', 'Sam finished Recycling'),
        ('review', 'Trampoline is funded'),
    ]
    check([(c['kind'], c['title']) for c in got] == want,
          "the pile is out of order:\n  got  " + repr([(c['kind'], c['title']) for c in got])
          + "\n  want " + repr(want))
    by_title = {c['title']: c for c in got}
    check(by_title['Reading log']['why'] == 'overdue', f"a still-open task reads 'overdue': {by_title['Reading log']!r}")
    _open_has(by_title['Reading log'], fn='openKidTaskDetail', args=['t0'])
    sit = by_title['Thursday has no driver']
    check(sit['why'] == 'Ask Lorena' and sit['rank'] == 2 and sit['deadline_ms'] == _ms('situation'),
          f"situation card {sit!r}")
    check(isinstance(sit['icon'], str) and sit['icon'], f"situation icon {sit['icon']!r}")
    _open_has(sit, view='family', anchor='mind-container')
    check('Gym bag for Friday' not in by_title, "a situation outside group 'now' leaked into the pile")
    reviews = {
        'Sam finished Recycling': '15 points waiting on your yes',
        'Maya wants Movie night': '40 points',
        'Trampoline is funded': 'ready to grant',
    }
    for title, why in reviews.items():
        card = by_title[title]
        check(card['why'] == why and card['rank'] == 3 and card['deadline_ms'] is None,
              f"review card {card!r}, expected why {why!r}, rank 3, no deadline")
        _open_has(card, view='chores', section='reviews')
    check(len({c['id'] for c in got}) == len(got) and all(c['id'] for c in got),
          f"every card needs its own id: {[c['id'] for c in got]!r}")


def scenario_packing_is_a_card():
    """Slice 6 task 1: inputs.packing = [{eventId, title, items, leaveAt,
    primary}] -> one card {kind 'packing', icon, title 'Pack for <title>',
    why '<items joined ", "> \u00b7 leave <time>', deadline = leaveAt, rank 2,
    open {run: primary}} (pwaOpenNeed runs open.run)."""
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    got = out['cases']['packing_is_a_card']
    check('error' not in got, f"packing_is_a_card threw under node:\n{got.get('error')}")
    val = got['value']
    cards = val['cards']
    check(len(cards) == 1 and cards[0]['kind'] == 'packing', f"one packing card expected, got {cards!r}")
    c = cards[0]
    check(c['icon'] == '\U0001F392', f"packing icon {c['icon']!r}, expected the backpack")
    check(c['title'] == 'Pack for Soccer practice', f"packing title {c['title']!r}")
    check(c['why'] == 'soccer bag, water \u00b7 leave 3:40', f"packing why {c['why']!r}, expected 'soccer bag, water \u00b7 leave 3:40'")
    check(val['h24'] == 'soccer bag, water \u00b7 leave 15:40', f"use24h packing why {val['h24']!r}")
    check(c['rank'] == 2, f"packing rank {c['rank']!r}, expected 2")
    check(c['deadline_ms'] == val['leave_ms'], f"packing deadline {c['deadline_ms']!r}, expected leaveAt")
    want = "openActionSheet('Home','Riverside','Soccer practice','soccer','init_soccer')"
    check(c['open'] == {'run': want}, f"packing open {c['open']!r}, expected {{'run': <primary>}}")


def scenario_confirmed_packing_is_not():
    """A confirmed kit never reaches the pile: pwaNeedsYouInputs filters it, so
    the pure function sees an empty (or absent) packing list and draws none."""
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    got = out['cases']['confirmed_packing_is_not']
    check('error' not in got, f"confirmed_packing_is_not threw under node:\n{got.get('error')}")
    check(got['value']['empty'] == [] and got['value']['absent'] == [],
          f"no packing input, no packing card: {got['value']!r}")


def scenario_one_proposal_is_singular_and_sourced():
    """One proposal with no `source_from` but a `source_subject`: the title
    is singular and `why` names the subject; with no known source at all,
    `why` is 'from a photo' or empty, never 'from undefined'."""
    got = _cards('one_proposal_is_singular_and_sourced')
    if got is None:
        return
    check(len(got) == 1 and got[0]['kind'] == 'proposal', f"one proposal makes one card, got {got!r}")
    p = got[0]
    check(p['title'] in ('1 proposed event', 'One proposed event'),
          f"one proposal titled {p['title']!r}, expected '1 proposed event' or 'One proposed event'")
    why = p['why'] or ''
    check('Fall concert' in why, f"proposal why {why!r} must name the source subject 'Fall concert'")
    check('undefined' not in why, f"proposal why says 'undefined': {why!r}")
    bare = _cards('proposal_without_a_source')
    check(len(bare) == 1, f"a sourceless proposal still makes one card, got {bare!r}")
    bare_why = bare[0]['why'] or ''
    check('undefined' not in bare_why, f"a proposal with no known source reads why {bare_why!r}")
    check(bare_why in ('', 'from a photo'),
          f"a proposal with no known source reads why {bare_why!r}, expected 'from a photo' or empty")


def scenario_needs_driver_merges_dropoff_and_pickup():
    """`piano_dropoff` and `piano_pickup` are the two legs of one event (the
    `{base}_dropoff` / `{base}_pickup` convention, services/leave_by.py
    _base_id, services/assist.py LEG_SUFFIXES): ONE needs-driver card for
    the piano, a separate one for chess."""
    got = _cards('needs_driver_merges_dropoff_and_pickup')
    if got is None:
        return
    nd = [c for c in got if c['kind'] == 'needs_driver']
    titles = [c['title'] for c in nd]
    piano = [t for t in titles if 'Piano' in t]
    check(len(piano) == 1, f"the piano drop-off and pick-up must make ONE needs-driver card, got {titles!r}")
    check(len(nd) == 2, f"piano and chess are two events, so two needs-driver cards, got {titles!r}")
    check(len({c['id'] for c in got}) == len(got), f"card ids must stay unique: {[c['id'] for c in got]!r}")
    for c in nd:
        check('undefined' not in (c['title'] + (c['why'] or '')), f"needs-driver card says 'undefined': {c!r}")
        _open_has(c, fn='openEventModal')


def scenario_status_card_without_a_person():
    """A family-wide status day (no person_name, no member_name): the title
    is the status name alone."""
    got = _cards('status_card_without_a_person')
    if got is None:
        return
    check(len(got) == 1 and got[0]['kind'] == 'status', f"one status day makes one card, got {got!r}")
    s = got[0]
    check('undefined' not in s['title'], f"status title says 'undefined': {s['title']!r}")
    check(s['title'] == 'Snow day', f"status title {s['title']!r}, expected 'Snow day'")
    check(s['why'] == 'School closed', f"status why {s['why']!r}, expected the logistical line")


def scenario_every_card_has_a_hand_path():
    got = _cards('full_pile')
    if got is None:
        return
    check(got, "the full pile drew no cards")
    for c in got:
        o = c.get('open') or {}
        check(o.get('view') or o.get('fn') or o.get('screen'),
              f"{c['kind']} card {c['title']!r} opens nothing: {o!r}")
        if o.get('screen'):
            check(o['screen'] in ('chores', 'rewards', 'tasks', 'lists', 'projects'),
                  f"{c['kind']} card {c['title']!r} opens an unknown Household screen {o['screen']!r}")
        if o.get('fn'):
            check(o['fn'] in ALLOWED_FNS,
                  f"{c['kind']} card {c['title']!r} opens {o['fn']!r}, not one of {sorted(ALLOWED_FNS)}")


def scenario_a_closed_chores_door_is_not_a_crash():
    kinds = _cards('a_closed_chores_door_is_not_a_crash')
    if kinds is None:
        return
    check(kinds == ['request'], f"a 403 object in the review sources must yield no review cards and keep the rest: {kinds!r}")


def scenario_household_task_due_today_is_a_card():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    got = out['cases']['household_task_due_today_is_a_card']
    check('error' not in got, f"threw under node: {got.get('error')}")
    val = got['value']
    today = val['today']
    check(len(today) == 1 and today[0]['kind'] == 'household_task',
          f"a household task due today is ONE household_task card, got {today!r}")
    c = today[0]
    check(c['icon'] == '☑️', f"household_task icon {c['icon']!r}, expected the ballot box with check")
    check(c['title'] == 'Take the bins out', f"household_task title {c['title']!r}")
    check(c['why'] == 'due today', f"household_task why {c['why']!r}, expected 'due today'")
    check(c['rank'] == 2, f"household_task rank {c['rank']!r}, expected 2")
    check(c['deadline_ms'] in _out()['day_ms']['2026-11-03'],
          f"deadline must be the due_date (UTC or local midnight), got {c['deadline_ms']!r}")
    check(c['open'] == {'screen': 'tasks'}, f"household_task open {c['open']!r}, expected {{'screen': 'tasks'}}")
    over = val['overdue']
    check(len(over) == 1 and over[0]['kind'] == 'household_task' and over[0]['why'] == 'overdue',
          f"a past-due task reads 'overdue': {over!r}")


def scenario_thread_in_now_is_a_card():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    got = out['cases']['thread_in_now_is_a_card']
    check('error' not in got, f"threw under node: {got.get('error')}")
    val = got['value']
    now = val['now']
    check(len(now) == 1 and now[0]['kind'] == 'thread', f"a thread in group 'now' is ONE thread card, got {now!r}")
    c = now[0]
    check(c['icon'] == '🧵', f"thread icon {c['icon']!r}, expected the spool of thread")
    check(c['title'] == 'Dentist for Sam' and c['why'] == 'Call the office',
          f"thread title/why {c['title']!r}/{c['why']!r}, why is the next move")
    check(c['rank'] == 2 and c['deadline_ms'] == _ms('situation'),
          f"thread rank/deadline {c['rank']!r}/{c['deadline_ms']!r}, expected 2 and its due_at")
    _open_has(c, view='family', anchor='house-threads')
    check(val['soon'] == [], f"a thread in group 'soon' is no card, got {val['soon']!r}")


def scenario_household_tasks_outrank_quiet_lists_but_not_a_needs_driver():
    got = _cards('household_tasks_outrank_quiet_lists_but_not_a_needs_driver')
    if got is None:
        return
    kinds = [c['kind'] for c in got]
    check(sorted(kinds) == ['household_task', 'needs_driver'], f"both cards must be present, got {kinds!r}")
    # The overdue task's deadline (Nov 1) is earlier than the pickup's (Nov 5), and
    # deadline cards sort by deadline first: the rule is deadline, then rank.
    check(kinds == ['household_task', 'needs_driver'],
          f"deadline cards sort by deadline: the Nov 1 overdue task comes before the Nov 5 pickup, got {kinds!r}")
    nd = [c for c in got if c['kind'] == 'needs_driver'][0]
    check(nd['rank'] == 1 and nd['deadline_ms'] == _ms('pickup'), f"needs_driver card {nd!r}")


def scenario_needs_driver_conflict_wording():
    """Slice 5 task 5, the calendar's Conflict rule: an unassigned row with
    `isConflict: true` and a `conflictReason` (the fields the family card
    carries, app.html ~9859/9884-9887, filled from the solver diagnostics by
    `conflictFor`) reads '<weekday> <time> · <conflictReason>' instead of
    '· nobody yet'; `isConflict: false` keeps '· nobody yet' whatever
    conflictReason says; a conflict with no reason never prints
    'undefined'/'null'. The card stays a rank-1 needs_driver opening the event."""
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    got = out['cases']['needs_driver_conflict_wording']
    check('error' not in got, f"needs_driver_conflict_wording threw under node:\n{got.get('error')}")
    val = got['value']
    by = {c['title']: c for c in val['cards']}
    check(set(by) == {'Swim meet needs a driver', 'Chess club needs a driver', 'Art class needs a driver'},
          f"three needs-driver cards: {list(by)!r}")
    swim = by['Swim meet needs a driver']
    check(swim['why'] == 'Thursday 5:10 PM · Alex is driving Sam',
          f"a conflict reads its reason, never 'nobody yet': {swim['why']!r}, expected 'Thursday 5:10 PM · Alex is driving Sam'")
    check(swim['kind'] == 'needs_driver' and swim['rank'] == 1 and swim['deadline_ms'] == _ms('pickup'),
          f"the conflict card is still a rank-1 needs_driver due at the start: {swim!r}")
    _open_has(swim, fn='openEventModal', args=['swim-key'])
    check(val['h24'] == 'Thursday 17:10 · Alex is driving Sam', f"use24h conflict why {val['h24']!r}")
    chess = by['Chess club needs a driver']
    check(chess['why'] == 'Wednesday 5:00 PM · nobody yet',
          f"isConflict false keeps 'nobody yet' and ignores a stale conflictReason: {chess['why']!r}")
    art = by['Art class needs a driver']['why'] or ''
    check(art.startswith('Friday 4:00 PM · ') and 'undefined' not in art and 'null' not in art,
          f"a conflict with no reason still reads '<weekday> <time> · ...' and never undefined/null: {art!r}")



def scenario_conflict_rule_is_the_calendars():
    got = _case('conflict_rule') if '_case' in globals() else None
    if got is None:
        out = _out()
        if out is None:
            return
        got = out['cases']['conflict_rule']['value']
    check(got['empty'] is None and got['none'] is None, f"no diagnostics, no conflict: {got!r}")
    check(got['hard'] == {'conflictReason': 'Sam is in two places at 4:30'}, f"every reason hard, one text: {got['hard']!r}")
    check(got['mixed_text'] == {'conflictReason': None}, f"a conflict with mixed texts has no single reason: {got['mixed_text']!r}")
    check(got['optimization'] is None, f"an optimization reason keeps the event assignable: {got['optimization']!r}")
    check(got['missing_reason'] is None, f"a missing reason keeps the event assignable: {got['missing_reason']!r}")

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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa needs-you scenarios passed")
    sys.exit(1 if failed else 0)
