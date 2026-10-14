"""Subjects: the resolver over the family's own records (spec 2026-10-14,
docs/superpowers/specs/2026-10-14-mission-subject-resolver-design.md §1).

One registry in services/subjects.py knows eight kinds (trip, occasion, event,
member, contact, thread, program, list). Pinned here (Task 1):

  * matching reuses the existing tiers: exact 1.0, substring 0.85, first word
    0.75, sound-fold 0.7, close spelling (ratio >= 0.8);
  * visibility is the record's OWN rule and is applied BEFORE matching, so a
    viewer who may not see a record learns the same nothing as for a record
    that does not exist; `spoken` adds the kind-aware audience check (a trip
    or occasion with no audience set defaults to parents and is never said
    aloud);
  * upcoming and open rows outrank past and closed ones at equal score;
  * resolve() needs a clear winner (>= 0.7 and a 0.06 margin, the margin
    _match_person keeps between Grandpa and Grandma), and a tie ACROSS kinds
    is not a winner;
  * a calendar-only trip (no metadata row) is found from the trips snapshot.

Task 2 appends the context() scenarios below the Task 1 block.

Run from chauffeur/:  python tests/test_subjects.py
"""
import time

from harness import check  # noqa: F401
from services import storage

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
DAD = {'id': 'dad', 'name': 'Dad', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}

TABLES = ('trip_metadata_table', 'trips_cache_table', 'occasions_table', 'occasion_guests_table', 'members_table',
          'assist_contacts_table', 'threads_table', 'programs_table', 'shopping_lists_table', 'shopping_items_table',
          'cache_table', 'missions_table', 'mission_steps_table', 'app_state_table')


def _reset():
    for name in TABLES:
        getattr(storage, name).truncate()
    storage.get_settings = lambda: {'calendar_ids': ['primary']}


def _seed():
    for m in (MOM, DAD, AUNT, KID):
        storage.add_member(dict(m))
    with storage.db_lock:
        storage.trip_metadata_table.insert({
            'id': 't1', 'event_id': 'ev_disney', 'title': 'Disney World', 'location': 'Orlando, FL', 'travelers': 4,
            'pois': [
                {'id': 'p1', 'name': 'Magic Kingdom', 'location': 'MK', 'category': 'sightseeing', 'is_scheduled': True,
                 'scheduled_start': 1800000000.0, 'scheduled_end': 1800028800.0, 'duration_mins': 480},
                {'id': 'p2', 'name': "Chef Mickey's", 'location': 'Contemporary', 'category': 'food', 'meal_type': 'breakfast',
                 'is_scheduled': True, 'scheduled_start': 1800061200.0, 'scheduled_end': 1800064800.0, 'duration_mins': 60},
                {'id': 'p3', 'name': 'Be Our Guest', 'location': 'MK', 'category': 'food', 'is_scheduled': False, 'duration_mins': 90}],
            'accommodations': [{'id': 'a1', 'name': 'Pop Century', 'location': 'Orlando',
                                'check_in_date': '2027-01-15', 'check_out_date': '2027-01-20'}],
            'flights': [{'id': 'f1', 'airline': 'Delta', 'flight_number': 'DL123', 'origin': 'RDU', 'destination': 'MCO',
                         'departure_time': '2027-01-15T08:00'}]})
        storage.trip_metadata_table.insert({'id': 't2', 'event_id': 'ev_hawaii', 'title': 'Hawaii', 'location': 'Maui',
                                            'audience': 'household', 'pois': [], 'accommodations': [], 'flights': []})
    storage.set_cached_trips([
        {'id': 'ev_disney', 'title': 'Disney World', 'start': '2027-01-15', 'end': '2027-01-20', 'location': 'Orlando, FL'},
        {'id': 'ev_hawaii', 'title': 'Hawaii', 'start': '2026-06-01', 'end': '2026-06-08', 'location': 'Maui'},
        {'id': 'ev_beach', 'title': 'Beach weekend', 'start': '2027-03-05', 'end': '2027-03-07', 'location': 'OBX'},
        {'id': 'ev_beach_old', 'title': 'Beach day', 'start': '2026-05-01', 'end': '2026-05-01', 'location': 'OBX'}])
    storage.save_occasion({'id': 'o1', 'title': "Kate's 10th birthday", 'kind': 'birthday', 'anchor_date': '2027-02-14'})
    storage.save_occasion({'id': 'o2', 'title': 'Thanksgiving', 'kind': 'thanksgiving', 'anchor_date': '2026-11-26',
                           'audience': 'household'})
    storage.add_shopping_list({'id': 'l1', 'name': 'Groceries'})
    storage.add_shopping_list({'id': 'l2', 'name': 'Kate gifts', 'audience': 'private', 'shared_with': ['mom'],
                               'occasion_id': 'o1'})
    storage.add_program({'id': 'pr1', 'member_id': 'kid', 'title': 'Piano', 'state': 'active'})
    storage.add_program({'id': 'pr2', 'member_id': 'mom', 'title': 'Run a 10k', 'state': 'active'})
    storage.add_thread({'id': 'th1', 'title': 'Disney dining', 'goal': 'book the restaurants', 'kind': 'project',
                        'state': 'open', 'owner_member_id': 'mom', 'created_by': 'mom'})
    storage.add_thread({'id': 'th2', 'title': 'Pest control', 'kind': 'vendor', 'state': 'done',
                        'owner_member_id': 'mom', 'created_by': 'mom'})
    storage.add_assist_contact({'id': 'c1', 'name': 'Grandma', 'relation_label': 'Grandma', 'phone': '555-0101', 'helps_with': ['driving']})
    storage.add_assist_contact({'id': 'c2', 'name': 'Grandpa', 'relation_label': 'Grandpa', 'phone': '555-0102', 'helps_with': ['driving']})
    storage.add_assist_contact({'id': 'c3', 'name': 'Celma', 'relation_label': 'Celma', 'phone': '555-0103', 'helps_with': []})
    storage.set_cached_schedule({'events': [{'id': 'e1', 'title': 'Team Pictures', 'start': '2026-10-17T08:30:00',
                                             'end': '2026-10-17T09:30:00', 'location': 'Field 3'}],
                                 'assignments': {}, 'unassigned': ['e1']})


def _fresh():
    _reset()
    _seed()
    from services import subjects
    return subjects


def _ids(cands):
    return [c['id'] for c in cands]


# --- Task 1 ------------------------------------------------------------------

def scenario_find_ranks_exact_over_substring_over_sound_fold():
    s = _fresh()
    exact = s.find('trip', 'Disney World', MOM)
    check(exact and exact[0]['id'] == 'ev_disney' and exact[0]['score'] == 1.0, f"exact title is 1.0: {exact}")
    check(set(exact[0]) >= {'kind', 'id', 'title', 'when', 'score'} and exact[0]['kind'] == 'trip', f"candidate shape: {exact[0]}")
    sub = s.find('trip', 'disney', MOM)
    check(sub and sub[0]['id'] == 'ev_disney' and sub[0]['score'] == 0.85, f"substring is 0.85: {sub}")
    fold = s.find('occasion', 'Thanksgivving', MOM)
    check(fold and fold[0]['id'] == 'o2' and fold[0]['score'] == 0.7, f"the sound fold finds a doubled letter at 0.7: {fold}")
    check(s.find('occasion', 'xylophone', MOM) == [], "no match is empty")


def scenario_find_prefers_upcoming_and_open_at_a_tie():
    s = _fresh()
    beach = s.find('trip', 'beach', MOM)
    check(_ids(beach)[:2] == ['ev_beach', 'ev_beach_old'], f"upcoming before past at an equal score: {beach}")
    closed = s.find('thread', 'control', MOM)
    check(_ids(closed) == ['th2'], f"a closed thread is still findable: {closed}")
    storage.add_thread({'id': 'th3', 'title': 'Pest control again', 'kind': 'vendor', 'state': 'open',
                        'owner_member_id': 'mom', 'created_by': 'mom'})
    both = s.find('thread', 'pest', MOM)
    check(_ids(both)[:2] == ['th3', 'th2'], f"open before closed at an equal score: {both}")


def scenario_visibility_filters_before_matching():
    s = _fresh()
    check(s.find('occasion', "Kate's", KID) == [] and s.find('occasion', 'zzz', KID) == [],
          "a parents-only occasion and a missing one are the same nothing to a child")
    check(_ids(s.find('occasion', 'Thanksgiving', KID)) == ['o2'], "a household occasion is findable by a child")
    check(s.find('list', 'gifts', DAD) == [], "a private list is invisible to a parent it is not shared with")
    check(_ids(s.find('list', 'gifts', MOM)) == ['l2'], "and visible to the one it is shared with")
    check(_ids(s.find('program', 'Piano', KID)) == ['pr1'], "a child sees their own program")
    check(s.find('program', '10k', KID) == [], "and never someone else's")
    check(_ids(s.find('program', 'Piano', MOM)) == ['pr1'], "a parent sees every program")
    check(s.find('trip', 'Disney', None) == [], "an anonymous surface never sees a parents-default trip")
    check(_ids(s.find('trip', 'Hawaii', None)) == ['ev_hawaii'], "a household trip is anonymous-visible")
    check(s.find('member', 'Mom', KID) == [] and s.find('contact', 'Grandma', KID) == [],
          "people and outside contacts are parent/adult lookups")
    check(_ids(s.find('contact', 'Grandma', AUNT))[:1] == ['c1'], "an adult may look a contact up")


def scenario_spoken_requires_the_kinds_own_audience():
    s = _fresh()
    check(s.spoken_safe('trip', s.load('trip', 'ev_disney')) is False, "a trip with no audience defaults to parents: never spoken")
    check(s.spoken_safe('trip', s.load('trip', 'ev_hawaii')) is True, "a household trip may be said aloud")
    check(s.spoken_safe('occasion', s.load('occasion', 'o1')) is False, "a parents-default occasion is never spoken")
    check(s.find('trip', 'Disney', MOM, spoken=True) == [], "even a verified parent does not hear it on a speaker")
    check(_ids(s.find('trip', 'Hawaii', MOM, spoken=True)) == ['ev_hawaii'], "the household trip is found aloud")
    storage.add_thread({'id': 'th9', 'title': 'Therapy intake', 'kind': 'vendor', 'state': 'open', 'owner_member_id': 'mom',
                        'created_by': 'mom'})
    storage.update_thread('th9', {'sensitivity': 'sensitive'})
    check(s.spoken_safe('thread', storage.get_thread('th9')) is False, "a sensitive thread is never spoken")
    check(s.spoken_safe('thread', storage.get_thread('th1')) is False, "a thread never shared with the speakers is not spoken")
    storage.update_thread('th1', {'voice_shared': True})
    check(s.spoken_safe('thread', storage.get_thread('th1')) is True, "once voice-shared, it may be")


def scenario_find_caps_and_find_all_merges():
    s = _fresh()
    for i in range(1, 8):
        storage.save_occasion({'id': f'px{i}', 'title': f'Party {i}', 'kind': 'party', 'anchor_date': '2027-04-0' + str(i),
                               'audience': 'household'})
    check(len(s.find('occasion', 'Party', MOM)) == 5, "five per kind")
    allc = s.find_all('a', MOM)
    check(0 < len(allc) <= 8, f"eight overall: {len(allc)}")
    check(len({c['kind'] for c in s.find_all('Grand', MOM)}) >= 1, "find_all spans kinds")


def scenario_resolve_needs_a_clear_margin():
    s = _fresh()
    win, _ = s.resolve('Disney World', MOM)
    check(win and win['id'] == 'ev_disney', f"an exact title wins: {win}")
    win, _ = s.resolve('Grandma', MOM, kinds=['contact'])
    check(win and win['title'] == 'Grandma', f"exact Grandma over Grandpa (0.857 apart is a margin): {win}")
    none, cands = s.resolve('Grand', MOM, kinds=['contact'])
    check(none is None and {'c1', 'c2'} <= set(_ids(cands)), f"Grand is both: no winner, both offered: {none} {cands}")
    win, _ = s.resolve('Selma', MOM, kinds=['contact'])
    check(win and win['id'] == 'c3', f"a sound-fold match is a winner when it is the only one (Celma heard as Selma): {win}")


def scenario_resolve_never_calls_a_cross_kind_tie_a_winner():
    s = _fresh()
    none, cands = s.resolve('Disney', MOM)
    check(none is None and {'ev_disney', 'th1'} <= set(_ids(cands)),
          f"the trip and the thread about it tie: ask which, never guess: {none} {cands}")


def scenario_link_and_facets():
    s = _fresh()
    # Relative paths to pages that exist: absolute ones escape the ingress prefix.
    check(s.link('trip', 'ev_disney') == 'trip?event_id=ev_disney', s.link('trip', 'ev_disney'))
    check(s.link('occasion', 'o1') == 'occasions', s.link('occasion', 'o1'))
    check(s.link('thread', 'th1') == 'threads', s.link('thread', 'th1'))
    check(s.link('contact', 'c1') == 'drive_setup' and s.link('list', 'l1') == 'shopping', "contacts and lists")
    import main
    pages = {r.path for r in main.app.routes}
    for kind in s.KINDS:
        check('/' + s.link(kind, 'x').split('?')[0] in pages, f"{kind} links to a page that exists: {s.link(kind, 'x')}")
    check(s.facets('trip') == ['flights', 'accommodations', 'dining', 'attractions'], s.facets('trip'))
    check(s.facets('occasion') == ['guests', 'menu', 'lists', 'errands'], s.facets('occasion'))
    check(s.facets('program') == ['sessions'] and s.facets('thread') == ['history'] and s.facets('member') == [], "facets per kind")
    check(tuple(s.KINDS) == ('trip', 'occasion', 'event', 'member', 'contact', 'thread', 'program', 'list'), s.KINDS)
    check(s.title_of('contact', s.load('contact', 'c1')) == 'Grandma', "a contact is named by what we call them")


def scenario_a_calendar_only_trip_is_found_from_the_snapshot():
    s = _fresh()
    got = s.find('trip', 'Beach weekend', MOM)
    check(got and got[0]['id'] == 'ev_beach' and got[0]['when'] == '2027-03-05', f"no metadata row, found anyway: {got}")
    row = s.load('trip', 'ev_beach')
    check(row and row['title'] == 'Beach weekend', f"load merges the snapshot: {row}")
    check(s.load('trip', 'nope') is None and s.load('occasion', 'nope') is None, "a missing id loads None")



# --- Task 2: context() --------------------------------------------------------

import datetime as _dt
import re as _re


def scenario_context_is_none_for_missing_and_excluded_alike():
    s = _fresh()
    check(s.context('occasion', 'nope', MOM) is None, "a missing record reads None")
    check(s.context('occasion', 'o1', KID) is None, "a record the viewer may not see reads the same None")
    text = s.context('occasion', 'o1', MOM)
    check(text and "Kate's 10th birthday" in text and '2027-02-14' in text, f"a visible occasion reads in words: {text}")
    check(s.context('trip', 'ev_disney', MOM, spoken=True) is None, "a parents-default trip has no spoken context")


def scenario_trip_context_general_view():
    s = _fresh()
    text = s.context('trip', 'ev_disney', MOM)
    for want in ('Disney World', 'Orlando', '4 travel', 'Pop Century', 'DL123', 'Magic Kingdom', "Chef Mickey's",
                 'facets: flights, accommodations, dining, attractions'):
        check(want in text, f"general view names {want!r}:\n{text}")
    check(len(text) <= 1500, f"within the budget: {len(text)}")


def scenario_trip_facets_read_one_part_in_full():
    s = _fresh()
    dining = s.context('trip', 'ev_disney', MOM, facet='dining')
    check("Chef Mickey's" in dining and 'breakfast' in dining and 'Be Our Guest' in dining and 'not scheduled' in dining,
          f"dining = the food POIs, meal type and window, unscheduled named:\n{dining}")
    check('Magic Kingdom' not in dining, "dining leaves the attractions out")
    attractions = s.context('trip', 'ev_disney', MOM, facet='attractions')
    check('Magic Kingdom' in attractions and "Chef Mickey's" not in attractions, f"attractions = every other POI:\n{attractions}")
    check('DL123' in s.context('trip', 'ev_disney', MOM, facet='flights'), "flights facet")
    acc = s.context('trip', 'ev_disney', MOM, facet='accommodations')
    check('Pop Century' in acc and '5 nights' in acc, f"accommodations with nights:\n{acc}")
    check(s.context('trip', 'ev_disney', MOM, facet='bogus') == s.context('trip', 'ev_disney', MOM),
          "an unknown facet is the general view")


def scenario_trip_context_caps_pois_and_says_how_many_more():
    s = _fresh()
    pois = [{'id': f'q{i}', 'name': f'Stop number {i:02d} with a longish name', 'location': 'Somewhere', 'category': 'sightseeing',
             'is_scheduled': False, 'duration_mins': 60} for i in range(40)]
    with storage.db_lock:
        storage.trip_metadata_table.insert({'id': 't5', 'event_id': 'ev_big', 'title': 'Big trip', 'audience': 'household',
                                            'pois': pois, 'accommodations': [], 'flights': []})
    text = s.context('trip', 'ev_big', MOM)
    check(len(text) <= 1500, f"within the budget: {len(text)}")
    shown = len(_re.findall(r'Stop number \d\d', text))
    more = _re.search(r'and (\d+) more', text)
    check(more and shown + int(more.group(1)) == 40 and shown <= 30,
          f"names what fits (at most 30) and says how many more, always: shown {shown}, tail {more and more.group(0)}")


def scenario_trip_dates_say_their_source_and_age():
    s = _fresh()
    d = s.trip_dates('ev_disney')
    check(d['source'] == 'calendar' and d['start'] == '2027-01-15', f"a real trip's dates are the calendar snapshot's: {d}")
    check('hours ago' not in s.context('trip', 'ev_disney', MOM), "a fresh snapshot says no age")
    with storage.db_lock:
        storage.trips_cache_table.update({'at': time.time() - 9 * 3600})
    check('9 hours ago' in s.context('trip', 'ev_disney', MOM), "an old snapshot says how old")
    noon = lambda y, m, dd: _dt.datetime(y, m, dd, 12).timestamp()
    with storage.db_lock:
        storage.trip_metadata_table.insert({'id': 't6', 'event_id': 'ev_draft', 'title': 'Draft getaway', 'is_draft': True,
                                            'audience': 'household', 'mock_start_date': noon(2027, 5, 1),
                                            'mock_end_date': noon(2027, 5, 4), 'pois': [], 'accommodations': [], 'flights': []})
        storage.trip_metadata_table.insert({'id': 't7', 'event_id': 'ev_ghost', 'title': 'Ghost trip', 'audience': 'household',
                                            'pois': [], 'accommodations': [], 'flights': []})
    draft = s.trip_dates('ev_draft')
    check(draft['source'] == 'draft' and draft['start'] == '2027-05-01' and draft['end'] == '2027-05-04', f"a draft's mock dates: {draft}")
    dtext = s.context('trip', 'ev_draft', MOM)
    check('2027-05-01' in dtext and 'draft' in dtext.lower(), f"said as a draft:\n{dtext}")
    ghost = s.trip_dates('ev_ghost')
    check(ghost['source'] == 'unknown' and ghost['start'] is None, f"no snapshot, no draft: unknown: {ghost}")
    check('dates unknown' in s.context('trip', 'ev_ghost', MOM).lower(), "and the context says so")


def scenario_occasion_context_filters_linked_lists_by_viewer():
    s = _fresh()
    storage.save_occasion_guest({'id': 'g1', 'occasion_id': 'o1', 'name': 'The Wilsons', 'headcount': 4})
    mom = s.context('occasion', 'o1', MOM)
    check('Kate gifts' in mom, f"the list's own audience allows mom:\n{mom}")
    dad = s.context('occasion', 'o1', DAD)
    check(dad and 'Kate gifts' not in dad, f"a parent the private list excludes never reads its name:\n{dad}")
    guests = s.context('occasion', 'o1', MOM, facet='guests')
    check('The Wilsons' in guests and '4' in guests, f"guests facet with headcount:\n{guests}")
    for f in ('menu', 'lists', 'errands'):
        check(isinstance(s.context('occasion', 'o1', MOM, facet=f), str), f"{f} facet reads")
    check('Kate gifts' not in s.context('occasion', 'o1', DAD, facet='lists'), "the lists facet filters too")


def scenario_other_kinds_read_in_words():
    s = _fresh()
    ev = s.context('event', 'e1', MOM)
    check('Team Pictures' in ev and 'no driver yet' in ev.lower() and 'Field 3' in ev, f"event:\n{ev}")
    me = s.context('member', 'mom', MOM)
    check('Mom' in me and 'parent' in me, f"member:\n{me}")
    gran = s.context('contact', 'c1', MOM)
    check('Grandma' in gran and 'driving' in gran and '555-0101' in gran, f"contact, by hand:\n{gran}")
    aloud = s.context('contact', 'c1', MOM, spoken=True)
    check(aloud and '555-0101' not in aloud and 'phone' in aloud.lower(), f"aloud: the channel, never the number:\n{aloud}")
    th = s.context('thread', 'th1', MOM)
    check('Disney dining' in th and 'open' in th and 'book the restaurants' in th, f"thread:\n{th}")
    pr = s.context('program', 'pr1', MOM)
    check('Piano' in pr and 'Kate' in pr and 'active' in pr, f"program:\n{pr}")
    li = s.context('list', 'l1', MOM)
    check('Groceries' in li, f"list:\n{li}")
    beach = s.context('trip', 'ev_beach', MOM)
    check('no itinerary on file' in beach.lower(), f"a calendar-only trip says it has no itinerary:\n{beach}")
    for kind, sid in (('event', 'e1'), ('member', 'mom'), ('contact', 'c1'), ('thread', 'th1'), ('program', 'pr1'),
                      ('list', 'l1'), ('occasion', 'o2')):
        check(len(s.context(kind, sid, MOM)) <= 1500, f"{kind} within the budget")


SCENARIOS = [
    scenario_find_ranks_exact_over_substring_over_sound_fold,
    scenario_find_prefers_upcoming_and_open_at_a_tie,
    scenario_visibility_filters_before_matching,
    scenario_spoken_requires_the_kinds_own_audience,
    scenario_find_caps_and_find_all_merges,
    scenario_resolve_needs_a_clear_margin,
    scenario_resolve_never_calls_a_cross_kind_tie_a_winner,
    scenario_link_and_facets,
    scenario_a_calendar_only_trip_is_found_from_the_snapshot,
    scenario_context_is_none_for_missing_and_excluded_alike,
    scenario_trip_context_general_view,
    scenario_trip_facets_read_one_part_in_full,
    scenario_trip_context_caps_pois_and_says_how_many_more,
    scenario_trip_dates_say_their_source_and_age,
    scenario_occasion_context_filters_linked_lists_by_viewer,
    scenario_other_kinds_read_in_words,
]

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
