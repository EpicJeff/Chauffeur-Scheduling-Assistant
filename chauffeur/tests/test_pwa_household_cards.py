"""The Household tab's five ranked cards and Argyle's one-line lead, checked by
RUNNING `pwaHouseholdCards(inputs)` and `pwaHouseholdLead(cards)` under node
with no `document` and no `window`.

PWA reimagined slice 3, Task 1 (task-1-brief.md). Both functions live at the top
level of static/pwa_household.js; a missing one FAILS, never skips. Missing node
prints `  skip`.

INPUT SHAPES (build to these; they mirror today's payloads)
  inputs = {role, canReview, listsOnly, meId, today: 'YYYY-MM-DD',
            facets: {chores, rewards, tasks, lists, projects},  # 'all'|'none'|...
            chores, balances, rewards, redemptions, householdTasks, lists,
            runs, projects, programs, members, nextWindowFor}
  meId (ADDED to the brief's list): the viewer's member id; a non-parent's
    chores score counts only open chores whose `eligible_member_ids` holds meId (an empty list means anyone).
  chores[]: {id, title, state: 'open'|'claimed'|'done'|'verified', claimed_by,
             claimed_by_name, eligible_member_ids: [memberId]}      (/api/chores rows)
  redemptions[]: {id, member_id, member_name, reward_title, cost, state:'pending'}
  balances[]: {member_id, name, balance}
  rewards[] (pools): {id, title, pct, funded: bool}
  householdTasks[]: {id, title, due_date: 'YYYY-MM-DD'|null, past_due, due_today,
                     assigned_to_name}
  lists[]: {id, name, open_count, is_default}
  runs: {next: 'YYYY-MM-DD'} | {}   (the `runs` field of GET /api/shopping/runs: run_dates(); `next` is an ISO date string)
  projects[]: {id, title, state, lane, owner_member_id}
  programs[]: {id, title, state, member_id, unit_n, total_units}
  nextWindowFor(programId) -> {start: ISO} | null
CARD: {id, icon, title, line, pills: [{text, tone}], faces: [memberId],
      lead: {reviews, overdueTitle, shopDay, windowProgram, windowTime} (structured, the lead never parses pill text),
       progress: 0..1|null, score, open: {screen: id}}

RULINGS PINNED HERE
  - weekday names are FULL names ('Thursday'), from `today`, never the clock;
    times are 12-hour h:mm with no AM/PM ('4:30').
  - tasks: "N due this week" counts open tasks dated tomorrow..today+6 AND
    today, never the overdue ones (those are named by "<title> is overdue");
    score = 3*past_due + 2*due_today + 1*(dated within the week, not overdue,
    not today).
  - a non-parent never sees pending redemptions (no request pill, no score) and
    never "done waiting on you".
  - lead: count words one..nine spelled, 10+ digits; "One thing wants your
    yes." / "Two things want your yes."; the count comes from the hot pills
    "K to check" and "N request(s)"; second sentence is the first that applies
    of "Shop day is today/tomorrow." then "<title> is overdue." then
    "<program> is at <h:mm>."; at most two sentences; "All quiet in the house."
    when every score is 0.

Run from chauffeur/ with HA_BASE_URL unset:
    python tests/test_pwa_household_cards.py
"""
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pwa_pure import check, clock_source, pure_source, run_node  # noqa: E402

WANTED = ['pwaHouseholdCards', 'pwaHouseholdLead']

TODAY = '2026-11-04'
TOMORROW = '2026-11-05'
IN_FIVE = '2026-11-09'
IN_EIGHT = '2026-11-12'


def WD(iso):
    return datetime.date.fromisoformat(iso[:10]).strftime('%A')


PROBE = r"""
const TODAY = '2026-11-04';
const out = {document_defined: typeof document !== 'undefined',
             window_defined: typeof window !== 'undefined', cases: {}};

const CHORES = [
  {id: 'c1', title: 'Dishes', state: 'open', claimed_by: null, claimed_by_name: null, eligible_member_ids: ['p1', 'a1', 'k1']},
  {id: 'c2', title: 'Trash', state: 'open', claimed_by: null, claimed_by_name: null, eligible_member_ids: ['k1']},
  {id: 'c3', title: 'Laundry', state: 'claimed', claimed_by: 'k2', claimed_by_name: 'Maya', eligible_member_ids: ['k2']},
  {id: 'c4', title: 'Vacuum', state: 'claimed', claimed_by: 'k2', claimed_by_name: 'Maya', eligible_member_ids: ['k2']},
  {id: 'c5', title: 'Recycling', state: 'done', claimed_by: 'k3', claimed_by_name: 'Sam', eligible_member_ids: ['k3']},
  {id: 'c6', title: 'Mow', state: 'done', claimed_by: 'k3', claimed_by_name: 'Sam', eligible_member_ids: ['k3']},
  {id: 'c7', title: 'Old one', state: 'verified', claimed_by: 'k3', claimed_by_name: 'Sam', eligible_member_ids: ['k3']},
];
const DONE1 = [CHORES[4]];
const RD1 = {id: 'rd1', member_id: 'k2', member_name: 'Maya', reward_title: 'Movie night', cost: 40, state: 'pending'};
const RD2 = {id: 'rd2', member_id: 'k3', member_name: 'Sam', reward_title: 'Pizza night', cost: 25, state: 'pending'};
const BALANCES = [{member_id: 'k2', name: 'Maya', balance: 55}, {member_id: 'k3', name: 'Sam', balance: 20},
                  {member_id: 'k1', name: 'Lee', balance: 9}];
const POOL = {id: 'pl1', title: 'Trampoline', pct: 60, funded: false};
const POOL_FUNDED = {id: 'pl1', title: 'Trampoline', pct: 100, funded: true};
const T_OVERDUE = {id: 't1', title: 'Pay water bill', due_date: '2026-11-02', past_due: true, due_today: false, assigned_to_name: 'Dana'};
const T_TODAY = {id: 't2', title: 'Call plumber', due_date: '2026-11-04', past_due: false, due_today: true, assigned_to_name: 'Dana'};
const T_SAT = {id: 't3', title: 'Order filters', due_date: '2026-11-07', past_due: false, due_today: false, assigned_to_name: 'Dana'};
const T_FAR = {id: 't4', title: 'Winter tires', due_date: '2026-12-20', past_due: false, due_today: false, assigned_to_name: 'Dana'};
const T_NONE = {id: 't5', title: 'Sort photos', due_date: null, past_due: false, due_today: false, assigned_to_name: 'Dana'};
const LISTS = [{id: 'l1', name: 'Groceries', open_count: 7, is_default: true},
               {id: 'l2', name: 'Hardware', open_count: 3, is_default: false},
               {id: 'l3', name: 'Costco', open_count: 2, is_default: false},
               {id: 'l4', name: 'Garden', open_count: 1, is_default: false}];
const LISTS_QUIET = LISTS.map(l => Object.assign({}, l, {open_count: 0}));
const PROJECTS = [
  {id: 'pr2', title: 'Garage', state: 'active', lane: 'doing', owner_member_id: 'k2'},
  {id: 'pr1', title: 'Deck rebuild', state: 'active', lane: 'needs_you', owner_member_id: 'p1'},
  {id: 'pr3', title: 'Old shed', state: 'done', lane: 'done', owner_member_id: 'k1'},
];
const PROGRAMS = [
  {id: 'pg1', title: 'Piano', state: 'active', member_id: 'k2', unit_n: 3, total_units: 12},
  {id: 'pg2', title: 'Spanish', state: 'paused', member_id: 'k3', unit_n: null, total_units: null},
  {id: 'pg3', title: 'Chess', state: 'done', member_id: 'k1', unit_n: 9, total_units: 9},
];
const OWN_PROJECT = [{id: 'prL', title: 'Learn piano', state: 'active', lane: 'doing', owner_member_id: 'k2'}];
const OWN_PROGRAM = [{id: 'pgL', title: 'Learn piano', state: 'active', member_id: 'k2', unit_n: 3, total_units: 20,
                      project_id: 'prL'}];
const WIN_THU = {pg1: {start: '2026-11-05T16:30:00'}, pg2: {start: '2026-11-06T09:00:00'}};
const WIN_TODAY = {pg1: {start: '2026-11-04T16:30:00'}};
const winFor = (m) => (id) => m[id] || null;

function inp(over) {
  return Object.assign({
    role: 'parent', canReview: true, listsOnly: false, meId: 'p1', today: TODAY,
    facets: {chores: 'all', rewards: 'all', tasks: 'all', lists: 'all', projects: 'all'},
    chores: [], balances: [], rewards: [], redemptions: [], householdTasks: [], lists: [],
    runs: {}, projects: [], programs: [], members: [], nextWindowFor: () => null,
  }, over || {});
}
const ADULT = (over) => inp(Object.assign({role: 'adult', canReview: false, meId: 'a1'}, over || {}));
const summary = (cs) => cs.map(c => ({
  id: c.id, icon_is_text: typeof c.icon === 'string' && c.icon.length > 0,
  title_is_text: typeof c.title === 'string' && c.title.length > 0,
  title: c.title,
  line: c.line, pills: c.pills, faces: c.faces, progress: c.progress, score: c.score, open: c.open}));
const cards = (i) => summary(pwaHouseholdCards(i));
const lead = (i) => pwaHouseholdLead(pwaHouseholdCards(i));

const FULL = () => inp({chores: CHORES, balances: BALANCES, rewards: [POOL], redemptions: [RD1, RD2],
  householdTasks: [T_SAT, T_OVERDUE, T_FAR], lists: LISTS, projects: PROJECTS, programs: PROGRAMS,
  nextWindowFor: winFor(WIN_THU)});

const CASES = {
  order_follows_need: () => cards(inp({chores: DONE1, redemptions: [RD1], lists: LISTS})),
  full_parent_order: () => cards(FULL()),
  zero_scores_sink_stable: () => cards(inp({householdTasks: [T_OVERDUE], projects: PROJECTS})),
  all_empty: () => cards(inp()),
  lists_only_is_one_card: () => cards(Object.assign(FULL(), {listsOnly: true})),
  granted_list_with_scope_none: () => cards(ADULT({listsOnly: true, lists: [LISTS[0]],
    facets: {chores: 'none', rewards: 'all', tasks: 'all', lists: 'none', projects: 'all'}})),
  scope_none_without_lists: () => cards(ADULT({lists: [],
    facets: {chores: 'all', rewards: 'all', tasks: 'all', lists: 'none', projects: 'all'}})),
  facet_none_hides_the_card: () => cards(Object.assign(FULL(),
    {facets: {chores: 'none', rewards: 'all', tasks: 'all', lists: 'all', projects: 'all'}})),
  keeping_up_preset: () => cards(ADULT({chores: CHORES, redemptions: [RD1], rewards: [POOL],
    // keeping_up: lists.shopping none and nothing shared with her, so the
    // server returned no lists (a shared list WOULD keep the card: see
    // granted_list_with_scope_none).
    householdTasks: [T_OVERDUE], lists: [], projects: PROJECTS, programs: PROGRAMS,
    facets: {chores: 'all', rewards: 'mine', tasks: 'none', lists: 'none', projects: 'all'}})),
  chores_parent: () => cards(inp({chores: CHORES})),
  chores_adult: () => cards(ADULT({chores: CHORES})),
  chores_adult_anyone: () => cards(ADULT({chores: [{id: 'c8', title: 'Sweep', state: 'open', claimed_by: null, claimed_by_name: null, eligible_member_ids: []}, CHORES[1]]})),
  rewards_parent: () => cards(inp({redemptions: [RD1, RD2], balances: BALANCES, rewards: [POOL]})),
  rewards_one_request: () => cards(inp({redemptions: [RD1]})),
  rewards_adult_funded: () => cards(ADULT({redemptions: [RD1], balances: BALANCES, rewards: [POOL_FUNDED]})),
  rewards_adult_pool: () => cards(ADULT({redemptions: [RD1], rewards: [POOL]})),
  tasks_overdue: () => cards(inp({householdTasks: [T_SAT, T_OVERDUE, T_FAR]})),
  tasks_open_only: () => cards(inp({householdTasks: [T_NONE, T_FAR]})),
  tasks_empty: () => cards(inp()),
  tasks_today_and_week: () => cards(inp({householdTasks: [T_SAT, T_TODAY]})),
  lists_tomorrow: () => cards(inp({lists: LISTS, runs: {next: '2026-11-05'}})),
  lists_today: () => cards(inp({lists: LISTS, runs: {next: TODAY}})),
  lists_in_five: () => cards(inp({lists: LISTS, runs: {next: '2026-11-09'}})),
  lists_in_eight: () => cards(inp({lists: LISTS, runs: {next: '2026-11-12'}})),
  lists_quiet: () => cards(inp({lists: LISTS_QUIET})),
  program_in_its_project: () => cards(inp({projects: OWN_PROJECT, programs: OWN_PROGRAM})),
  projects_window_thursday: () => cards(inp({projects: PROJECTS, programs: PROGRAMS, nextWindowFor: winFor(WIN_THU)})),
  // slice 5 task 1: inputs.use24h words the window time as HH:mm
  projects_window_thursday_24h: () => cards(inp({projects: PROJECTS, programs: PROGRAMS,
    nextWindowFor: winFor(WIN_THU), use24h: true})),
  projects_window_raw_24h: () => cards(inp({projects: PROJECTS, programs: PROGRAMS, use24h: true,
    nextWindowFor: winFor({pg1: {date: '2026-11-05', time_start: '09:05', time_end: '10:00'}})})),
  projects_window_today: () => cards(inp({projects: PROJECTS, programs: PROGRAMS, nextWindowFor: winFor(WIN_TODAY)})),
  projects_window_raw: () => cards(inp({projects: PROJECTS, programs: PROGRAMS,
    nextWindowFor: winFor({pg1: {date: '2026-11-05', time_start: '16:30', time_end: '17:00'}})})),
  chores_you_claimed: () => cards(inp({chores: [{id: 'c9', title: 'Unload the dishwasher', state: 'claimed', claimed_by: 'p1', claimed_by_name: 'Alex', eligible_member_ids: []}]})),
  lead_two_with_shop_day: () => lead(inp({chores: DONE1, redemptions: [RD1], lists: LISTS,
    runs: {next: '2026-11-05'}, householdTasks: [T_OVERDUE]})),
  lead_two_with_overdue: () => lead(inp({chores: DONE1, redemptions: [RD1], lists: LISTS,
    householdTasks: [T_OVERDUE]})),
  lead_only_two_sentences: () => lead(inp({chores: DONE1, redemptions: [RD1], lists: LISTS,
    runs: {next: '2026-11-05'}, householdTasks: [T_OVERDUE], programs: [PROGRAMS[0]],
    nextWindowFor: winFor(WIN_TODAY)})),
  lead_one_thing: () => lead(inp({chores: DONE1})),
  lead_three_things: () => lead(inp({chores: [CHORES[4], CHORES[5]], redemptions: [RD1]})),
  lead_program_only: () => lead(inp({programs: [PROGRAMS[0]], nextWindowFor: winFor(WIN_TODAY)})),
  lead_program_tomorrow: () => lead(inp({projects: PROJECTS, programs: [PROGRAMS[0]], nextWindowFor: winFor(WIN_THU)})),
  lead_shop_today_only: () => lead(ADULT({lists: LISTS, runs: {next: TODAY}})),
  lead_overdue_adult: () => lead(ADULT({householdTasks: [T_OVERDUE]})),
  lead_quiet: () => lead(inp()),
  lead_quiet_lists: () => lead(inp({lists: LISTS_QUIET})),
  lead_nine: () => pwaHouseholdLead([{id: 'chores', score: 27, pills: [{text: '9 to check', tone: 'hot'}], lead: {reviews: 9}}]),
  lead_ten: () => pwaHouseholdLead([{id: 'chores', score: 30, pills: [{text: '10 to check', tone: 'hot'}], lead: {reviews: 10}}]),
  lead_sums_across_cards: () => pwaHouseholdLead([
    {id: 'chores', score: 6, pills: [{text: '2 to check', tone: 'hot'}], lead: {reviews: 2}},
    {id: 'rewards', score: 6, pills: [{text: '2 requests', tone: 'hot'}], lead: {reviews: 2}}]),
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
        _CACHE['out'] = run_node(clock_source() + pure_source('pwa_household.js', WANTED) + '\n' + PROBE)
    return _CACHE['out']


def _case(name):
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return None
    got = out['cases'][name]
    check('error' not in got, f"{name} threw under node:\n{got.get('error')}")
    return got['value']


def _cards(name):
    val = _case(name)
    if val is not None:
        check(isinstance(val, list), f"{name}: pwaHouseholdCards did not return an array: {val!r}")
    return val


def _by_id(cs):
    return {c['id']: c for c in cs}


def _texts(card):
    return [p['text'] for p in card['pills']]


def _ids(cs):
    return [c['id'] for c in cs]


def _scores(cs):
    return [c['score'] for c in cs]


def scenario_is_pure():
    out = _out()
    if out is None:
        print("  skip  node is not installed")
        return
    check(not out['document_defined'] and not out['window_defined'],
          "the probe leaked a document/window global")
    for name, got in out['cases'].items():
        check('error' not in got, f"{name} threw with no document/window:\n{got.get('error')}")


def scenario_every_card_has_its_shape():
    got = _cards('full_parent_order')
    if got is None:
        return
    check(len(got) == 5, f"a parent with every facet gets five cards, got {_ids(got)!r}")
    for c in got:
        check(c['icon_is_text'] and c['title_is_text'], f"{c['id']} card needs an icon and a title: {c!r}")
        check(c['open'] == {'screen': c['id']}, f"{c['id']} card must open its own screen, got {c['open']!r}")
        check(isinstance(c['pills'], list) and all(p['tone'] in ('plain', 'hot', 'ok') for p in c['pills']),
              f"{c['id']} pills {c['pills']!r}")
        check(isinstance(c['faces'], list), f"{c['id']} faces must be an array, got {c['faces']!r}")
        check(isinstance(c['score'], (int, float)), f"{c['id']} score {c['score']!r}")


def scenario_order_follows_need():
    got = _cards('order_follows_need')
    if got is None:
        return
    check(_ids(got) == ['chores', 'rewards', 'lists', 'tasks', 'projects'],
          f"a done chore and a pending redemption outrank quiet lists, then the zeros: {_ids(got)!r}")
    check(_scores(got) == [3, 3, 1, 0, 0], f"scores 3 (done chore), 3 (pending), 1 (open list), 0, 0: {_scores(got)!r}")
    full = _cards('full_parent_order')
    check(_ids(full) == ['chores', 'rewards', 'tasks', 'projects', 'lists'],
          f"score descending beats the stable order (projects 3 over lists 1): {_ids(full)!r}")
    check(_scores(full) == [8, 6, 4, 3, 1], f"full parent scores {_scores(full)!r}, expected [8, 6, 4, 3, 1]")


def scenario_zero_scores_sink_stable():
    got = _cards('zero_scores_sink_stable')
    if got is None:
        return
    check(_ids(got) == ['tasks', 'projects', 'chores', 'rewards', 'lists'],
          f"tied scores keep chores/rewards/tasks/lists/projects order and zeros sink: {_ids(got)!r}")
    check(_scores(got) == [3, 3, 0, 0, 0], f"scores {_scores(got)!r}")
    empty = _cards('all_empty')
    check(_ids(empty) == ['chores', 'rewards', 'tasks', 'lists', 'projects'] and set(_scores(empty)) == {0},
          f"with nothing at all every card scores 0 in the stable order: {_ids(empty)!r} {_scores(empty)!r}")


def scenario_lists_only_is_one_card():
    got = _cards('lists_only_is_one_card')
    if got is None:
        return
    check(_ids(got) == ['lists'], f"listsOnly means the lists card alone, got {_ids(got)!r}")
    granted = _cards('granted_list_with_scope_none')
    check(granted is not None and [c['id'] for c in granted] == ['lists'],
          f"lists.shopping none + a list the server still shared (the grandmother's grocery list) = the one Lists card: "
          f"{[c['id'] for c in (granted or [])]!r}")
    none = _cards('scope_none_without_lists')
    check(none is not None and 'lists' not in [c['id'] for c in none],
          f"lists.shopping none with no list shared = no Lists card: {[c['id'] for c in (none or [])]!r}")


def scenario_facet_none_hides_the_card():
    got = _cards('facet_none_hides_the_card')
    if got is None:
        return
    check(_ids(got) == ['rewards', 'tasks', 'projects', 'lists'],
          f"facets.chores 'none' drops only the chores card: {_ids(got)!r}")
    kept = _cards('keeping_up_preset')
    check(_ids(kept) == ['projects', 'chores', 'rewards'],
          f"keeping_up: tasks and lists 'none' are absent, 'mine' still shows: {_ids(kept)!r}")
    check(_scores(kept) == [3, 1, 0], f"keeping_up scores (projects 3, eligible-open chore 1, pool 0): {_scores(kept)!r}")


def scenario_chores_line_and_pills():
    got = _cards('chores_parent')
    if got is None:
        return
    c = _by_id(got)['chores']
    check(c['line'] == '2 open · Maya has 2 claimed · 2 done waiting on you',
          f"parent chores line {c['line']!r}")
    check(_texts(c) == ['2 to check', 'Dishes · open', 'Trash · open'],
          f"parent chores pills {_texts(c)!r}")
    check(c['pills'][0]['tone'] == 'hot', f"the check pill is hot: {c['pills'][0]!r}")
    check(c['score'] == 8, f"parent chores score 3*2 done + 2 open = 8, got {c['score']!r}")
    a = _by_id(_cards('chores_adult'))['chores']
    check(a['line'] == '2 open · Maya has 2 claimed', f"adult chores line {a['line']!r}, never 'waiting on you'")
    check(not any('to check' in t for t in _texts(a)) and all(p['tone'] != 'hot' for p in a['pills']),
          f"an adult gets no check pill: {_texts(a)!r}")
    you = _by_id(_cards('chores_you_claimed'))['chores']
    check('you have 1 claimed' in you['line'] and 'Alex has' not in you['line'],
          f"the viewer's own claims read as 'you', never their name: {you['line']!r}")
    anyone = _by_id(_cards('chores_adult_anyone'))['chores']
    check(anyone['score'] == 1,
          f"an open chore with an empty eligible_member_ids is for anyone, so an adult scores it: {anyone['score']!r} (Trash is k1-only)")
    check(a['score'] == 1, f"adult score counts only open chores eligible for meId (Dishes): {a['score']!r}")


def scenario_rewards_progress_and_request_pill():
    got = _cards('rewards_parent')
    if got is None:
        return
    c = _by_id(got)['rewards']
    check('Maya asked for Movie night · 40 pts' in c['line'], f"rewards line {c['line']!r}")
    check(_texts(c) == ['2 requests', 'Maya 55 pts', 'Sam 20 pts'],
          f"request pill then two balances only: {_texts(c)!r}")
    check(c['pills'][0]['tone'] == 'hot', f"the request pill is hot: {c['pills'][0]!r}")
    check(c['score'] == 6, f"two pending = 6, got {c['score']!r}")
    one = _by_id(_cards('rewards_one_request'))['rewards']
    check(_texts(one)[0] == '1 request' and one['score'] == 3, f"singular request pill: {one!r}")
    fund = _by_id(_cards('rewards_adult_funded'))['rewards']
    check('Family goal: Trampoline funded' in fund['line'], f"funded pool line {fund['line']!r}")
    check(fund['score'] == 2, f"a funded pool scores 2 and an adult's pending redemptions add nothing: {fund['score']!r}")
    check(all(p['tone'] != 'hot' for p in fund['pills']) and not any('request' in t for t in _texts(fund)),
          f"an adult gets no request pill: {_texts(fund)!r}")
    pool = _by_id(_cards('rewards_adult_pool'))['rewards']
    check(pool['line'] == 'Trampoline 60%', f"top goal line {pool['line']!r}")
    check(abs(pool['progress'] - 0.6) < 1e-9, f"top goal progress is pct/100, got {pool['progress']!r}")
    check(pool['score'] == 0, f"an unfunded goal with no review rights scores 0: {pool['score']!r}")


def scenario_tasks_overdue_first():
    got = _cards('tasks_overdue')
    if got is None:
        return
    c = _by_id(got)['tasks']
    check(c['line'] == '1 due this week · Pay water bill is overdue', f"tasks line {c['line']!r}")
    check(_texts(c) == ['1 overdue', 'Order filters · ' + WD('2026-11-07')], f"tasks pills {_texts(c)!r}")
    check(c['pills'][0]['tone'] == 'hot', f"overdue pill is hot: {c['pills'][0]!r}")
    check(c['score'] == 4, f"3 for the overdue + 1 for the week, got {c['score']!r}")
    open_only = _by_id(_cards('tasks_open_only'))['tasks']
    check(open_only['line'] == '2 open', f"open-only line {open_only['line']!r}")
    check(all(p['tone'] != 'hot' for p in open_only['pills']), f"nothing overdue means nothing hot: {open_only['pills']!r}")
    check('Winter tires · Dec 20' in _texts(open_only),
          f"a task beyond six days names its date, never a bare weekday: {_texts(open_only)!r}")
    empty = _by_id(_cards('tasks_empty'))['tasks']
    check(empty['line'] == 'Nothing on the list' and empty['score'] == 0, f"empty tasks card {empty!r}")
    week = _by_id(_cards('tasks_today_and_week'))['tasks']
    check(week['line'] == '2 due this week', f"today and Saturday are both this week: {week['line']!r}")
    check(week['score'] >= 3 and all(p['tone'] != 'hot' for p in week['pills']), f"today+week card {week!r}")


def scenario_lists_shop_day_tomorrow():
    got = _cards('lists_tomorrow')
    if got is None:
        return
    c = _by_id(got)['lists']
    check(c['line'] == 'Groceries 7 · Hardware 3 · Costco 2', f"lists line (three lists max) {c['line']!r}")
    check(_texts(c) == ['Shop day tomorrow', '4 lists'], f"lists pills {_texts(c)!r}")
    check([p['tone'] for p in c['pills']] == ['hot', 'plain'], f"tones {[p['tone'] for p in c['pills']]!r}")
    check(c['score'] == 2, f"shop day tomorrow scores 2, got {c['score']!r}")
    today = _by_id(_cards('lists_today'))['lists']
    check(_texts(today)[0] == 'Shop day today' and today['score'] == 2, f"shop day today {today!r}")
    five = _by_id(_cards('lists_in_five'))['lists']
    check(_texts(five) == ['Shop day ' + WD('2026-11-09'), '4 lists'] and five['score'] == 1,
          f"shop day five days out names the weekday and scores 1: {five!r}")
    eight = _by_id(_cards('lists_in_eight'))['lists']
    check(_texts(eight) == ['4 lists'] and eight['score'] == 1, f"shop day beyond 7 days is not a pill: {eight!r}")
    quiet = _by_id(_cards('lists_quiet'))['lists']
    check(quiet['score'] == 0, f"lists with nothing open score 0, got {quiet['score']!r}")


def scenario_projects_faces_and_next_window():
    got = _cards('projects_window_thursday')
    if got is None:
        return
    c = _by_id(got)['projects']
    check(c['line'] == 'Deck rebuild · Garage · Piano (lesson 3 of 12)',
          f"needs_you first, three titles, program with its lesson: {c['line']!r}")
    check(_texts(c) == ['Piano · ' + WD('2026-11-05') + ' 4:30', '4 running'],
          f"soonest window then the running count (done work excluded): {_texts(c)!r}")
    check([p['tone'] for p in c['pills']] == ['hot', 'plain'], f"tones {[p['tone'] for p in c['pills']]!r}")
    check(c['faces'] == ['p1', 'k2', 'k3'], f"owners deduplicated in order: {c['faces']!r}")
    check(c['score'] == 3, f"one needs_you project = 3, got {c['score']!r}")
    today = _by_id(_cards('projects_window_today'))['projects']
    check(today['score'] == 4, f"a window today adds 1, got {today['score']!r}")
    check(_texts(today)[0] == 'Piano · ' + WD(TODAY) + ' 4:30', f"today's window pill {_texts(today)!r}")
    raw = _by_id(_cards('projects_window_raw'))['projects']
    check(_texts(raw)[0] == 'Piano · ' + WD('2026-11-05') + ' 4:30',
          f"a raw practice-window row (date + time_start, the GET api/practice-windows shape) names the same window: {_texts(raw)!r}")


def scenario_window_pill_honours_use24h():
    """inputs.use24h true: 'Piano · Thursday 16:30' (raw row 09:05 reads
    '09:05'); the 12-hour pin in the thursday scenario is untouched."""
    got = _cards('projects_window_thursday_24h')
    if got is None:
        return
    c = _by_id(got)['projects']
    check(_texts(c)[0] == 'Piano · ' + WD('2026-11-05') + ' 16:30',
          f"use24h window pill {_texts(c)!r}, expected 'Piano · {WD('2026-11-05')} 16:30'")
    raw = _by_id(_cards('projects_window_raw_24h'))['projects']
    check(_texts(raw)[0] == 'Piano · ' + WD('2026-11-05') + ' 09:05',
          f"a raw window row with use24h reads {_texts(raw)!r}, expected 'Piano · {WD('2026-11-05')} 09:05'")


def scenario_lead_sentences():
    exp = {
        'lead_two_with_shop_day': 'Two things want your yes. Shop day is tomorrow.',
        'lead_two_with_overdue': 'Two things want your yes. Pay water bill is overdue.',
        'lead_only_two_sentences': 'Two things want your yes. Shop day is tomorrow.',
        'lead_one_thing': 'One thing wants your yes.',
        'lead_three_things': 'Three things want your yes.',
        'lead_program_only': 'Piano is at 4:30.',
        'lead_shop_today_only': 'Shop day is today.',
        'lead_overdue_adult': 'Pay water bill is overdue.',
        'lead_quiet': 'All quiet in the house.',
        'lead_quiet_lists': 'All quiet in the house.',
        'lead_nine': 'Nine things want your yes.',
        'lead_ten': '10 things want your yes.',
        'lead_sums_across_cards': 'Four things want your yes.',
    }
    for name, want in exp.items():
        got = _case(name)
        if got is None:
            return
        check(got == want, f"{name}: got {got!r}, expected {want!r}")
    tomorrow = _case('lead_program_tomorrow')
    check(tomorrow == 'Nothing needs your yes.',
          f"a session tomorrow is never 'is at 4:30' (that reads as today); with nothing to say and the house not quiet "
          f"the lead is 'Nothing needs your yes.': {tomorrow!r}")


def scenario_lead_is_at_most_two_sentences():
    got = _case('lead_only_two_sentences')
    if got is None:
        return
    check(got.count('.') <= 2,
          f"at most two sentences even with a shop day, an overdue task and a lesson: {got!r}")


def scenario_a_program_and_its_project_count_once():
    """A program lives in its project (programs.create_row adopts it): the
    Projects card names the project once, with the lesson suffix, and counts
    one thing running."""
    got = _cards('program_in_its_project')
    if got is None:
        return
    card = next((c for c in got if c['id'] == 'projects'), None)
    check(card is not None and card['line'] == 'Learn piano (lesson 3 of 20)',
          f"the project and its program read once: {card and card['line']!r}")
    texts = [p['text'] for p in (card or {}).get('pills', [])]
    check('1 running' in texts, f"one thing running, not two: {texts!r}")


def scenario_projects_card_is_projects():
    """The user's ruling 2026-11-04 (slice 7): the card opens Projects, no
    Programs tab; programs still feed its line, lead and next-session pill."""
    got = _cards('full_parent_order')
    if got is None:
        return
    card = next((c for c in got if c['id'] == 'projects'), None)
    check(card is not None and card['title'] == 'Projects', f"the projects card title {card and card['title']!r}")


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
    print(f"\n{len(SCENARIOS) - failed}/{len(SCENARIOS)} pwa household-card scenarios passed")
    sys.exit(1 if failed else 0)
