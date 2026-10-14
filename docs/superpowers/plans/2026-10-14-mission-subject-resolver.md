# Subjects (resolver + subject on threads and missions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A thread or mission can stand inside a Chauffeur record (trip, occasion, event, member, contact, thread, program, list): one resolver finds it from words, its fresh state heads every planner step and the chat prompt, the situation inherits the record's audience, and a person can link, change or unlink it by hand.

**Architecture:** One new module `services/subjects.py` holds a per-kind registry (`visible`, `find`, `context`, `link`, `facets`) reusing the existing matchers and audience rules. Three fields on threads and missions (`subject_kind`, `subject_id`, `subject_rev`); a thread's missions read the thread's. One READ tool `find_in_chauffeur` serves chat, planner and satellite. Visibility of a bound situation = today's rule AND the subject's own.

**Tech Stack:** Python 3 / FastAPI / document-store storage (`services/storage.py`), the mission planner (`services/missions.py`), situations cards (`services/situations.py` + `static/situations.js`), Alpine templates, plain-script tests run from `chauffeur/` with `HA_BASE_URL` unset.

**Spec:** `docs/superpowers/specs/2026-10-14-mission-subject-resolver-design.md`

## Global Constraints

- Tests run from `chauffeur/` as `python tests/test_x.py` with `HA_BASE_URL` unset; never the whole suite.
- Every new route needs a rule in `services/auth.py` or the auth test flags it.
- No browser dialogs: `promptInput`, `promptChoice`, `promptConfirm`, `showGlobalAlert` only.
- `python tools/build_tailwind.py` after any template class change.
- Every HA/voice touchpoint degrades with no HA present.
- Nothing a person can do today is removed: free-text goals, the first-three-words dedupe for subject-less goals, today's `can_see` grants (the subject rule only narrows).
- Context budget: 1,500 characters per `context()` call (general or facet); 30 POIs in the general trip view; 5 candidates per kind, 8 overall.
- Trip dates come only from `trip_dates(event_id)` (draft → mock dates; real → `storage.get_cached_trips()` with age; none → unknown). Never Google per step.
- Codex split (the user's standing rule): Claude writes every test file and the docs; Codex implements against them via `/codex:rescue`; Claude gates, bumps `config.yaml`, updates `system_capabilities.md`, commits.

## Review Focus

1. A trip whose metadata row is missing (calendar-only trip): `find('trip')` must still list it from the trips snapshot and `context` must say "no itinerary on file", not throw. Test in Task 2.
2. A query that matches a thread AND the thread's own subject ("Disney"): `find_all` returns both; `resolve` must not call it a clear winner when the top two scores tie across kinds. Test in Task 1.
3. A parent retargets while the mission is `waiting_retry` (no ask, no browse): allowed; the retry step must read the new subject. Test in Task 6.
4. `find_in_chauffeur` called by the planner with an empty query: returns `{status:'error'}` and the planner gets a `refused` note, never a crash or an empty-string bind. Test in Task 4.
5. A thread bound to a private list whose `shared_with` excludes the thread's owner adult: the owner can still see their own thread (today's grant) but the subject chip, context and ABOUT are withheld, and `_dm_person` still DMs the creator (the mission ask) without the subject's words. Test in Task 3.

---

### Task 1: `services/subjects.py` — registry, visibility, find, resolve, link, facets

**Files:**
- Create: `services/subjects.py`
- Test: `tests/test_subjects.py` (scenarios A1–A9)

**Interfaces:**
- Consumes: `storage.get_all_trip_metadata`, `storage.get_cached_trips`, `storage.get_occasions(include_done=True)`, `storage.get_cached_schedule`, `storage.get_all_members`, `storage.get_assist_contacts`, `storage.get_threads(include_closed=True)`, `storage.get_programs()`, `storage.get_shopping_lists`; `scope.audience_allows`, `situations.can_see`, `agent_tools_v2._fold_name` (the sound fold), `agent_tools_v2._program_scope_id`.
- Produces:
  - `KINDS = ('trip', 'occasion', 'event', 'member', 'contact', 'thread', 'program', 'list')`
  - `visible(kind, row, viewer, spoken=False) -> bool`
  - `spoken_safe(kind, row) -> bool`
  - `find(kind, query, viewer, spoken=False) -> list[dict]` candidates `{kind, id, title, when, score}` (score float 0..1, 1.0 exact)
  - `find_all(query, viewer, kinds=None, spoken=False) -> list[dict]` (max 8)
  - `resolve(query, viewer, kinds=None, spoken=False) -> tuple[dict|None, list[dict]]`
  - `link(kind, id) -> str`
  - `facets(kind) -> list[str]`
  - `load(kind, id) -> dict|None` (the raw record; trip = metadata row merged with its snapshot row `{start, end, location, title}` when present)
  - `title_of(kind, row) -> str`

- [ ] **Step 1: Write the failing tests** — `tests/test_subjects.py` (header, fixture, A-scenarios). Use the `harness` import and the `check` helper like every other test. Fixture truncates `trip_metadata_table`, `trips_cache_table`, `occasions_table`, `occasion_guests_table`, `members_table`, `assist_contacts_table`, `threads_table`, `programs_table`, `shopping_lists_table`, `cache_table`, and seeds:

```python
MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
DAD = {'id': 'dad', 'name': 'Dad', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}

def _seed():
    for m in (MOM, DAD, AUNT, KID): storage.add_member(dict(m))
    # two trips: Disney (parents default), Hawaii (household)
    with storage.db_lock:
        storage.trip_metadata_table.insert({'id': 't1', 'event_id': 'ev_disney', 'title': 'Disney World', 'location': 'Orlando, FL', 'travelers': 4,
            'pois': [{'id': 'p1', 'name': 'Magic Kingdom', 'location': 'MK', 'category': 'sightseeing', 'is_scheduled': True, 'scheduled_start': 1800000000.0, 'scheduled_end': 1800028800.0, 'duration_mins': 480},
                     {'id': 'p2', 'name': "Chef Mickey's", 'location': 'Contemporary', 'category': 'food', 'meal_type': 'breakfast', 'is_scheduled': True, 'scheduled_start': 1800061200.0, 'scheduled_end': 1800064800.0, 'duration_mins': 60},
                     {'id': 'p3', 'name': 'Be Our Guest', 'location': 'MK', 'category': 'food', 'is_scheduled': False, 'duration_mins': 90}],
            'accommodations': [{'id': 'a1', 'name': 'Pop Century', 'location': 'Orlando', 'check_in_date': '2027-01-15', 'check_out_date': '2027-01-20'}],
            'flights': [{'id': 'f1', 'airline': 'Delta', 'flight_number': 'DL123', 'origin': 'RDU', 'destination': 'MCO', 'departure_time': '2027-01-15T08:00'}]})
        storage.trip_metadata_table.insert({'id': 't2', 'event_id': 'ev_hawaii', 'title': 'Hawaii', 'location': 'Maui', 'audience': 'household', 'pois': [], 'accommodations': [], 'flights': []})
    storage.set_cached_trips([{'id': 'ev_disney', 'title': 'Disney World', 'start': '2027-01-15', 'end': '2027-01-20', 'location': 'Orlando, FL'},
                              {'id': 'ev_hawaii', 'title': 'Hawaii', 'start': '2026-06-01', 'end': '2026-06-08', 'location': 'Maui'},
                              {'id': 'ev_beach', 'title': 'Beach weekend', 'start': '2027-03-05', 'end': '2027-03-07', 'location': 'OBX'}])
    storage.save_occasion({'id': 'o1', 'title': "Kate's 10th birthday", 'kind': 'birthday', 'anchor_date': '2027-02-14'})            # parents default
    storage.save_occasion({'id': 'o2', 'title': 'Thanksgiving', 'kind': 'thanksgiving', 'anchor_date': '2026-11-26', 'audience': 'household'})
    storage.add_shopping_list({'id': 'l1', 'name': 'Groceries', 'items': []})
    storage.add_shopping_list({'id': 'l2', 'name': 'Kate gifts', 'audience': 'private', 'shared_with': ['mom'], 'occasion_id': 'o1'})
    storage.add_program({'id': 'pr1', 'member_id': 'kid', 'title': 'Piano', 'state': 'active'})
    storage.add_program({'id': 'pr2', 'member_id': 'mom', 'title': 'Run a 10k', 'state': 'active'})
    storage.add_thread({'id': 'th1', 'title': 'Disney dining', 'goal': 'book the restaurants', 'kind': 'project', 'state': 'open', 'owner_member_id': 'mom', 'created_by': 'mom'})
    storage.add_thread({'id': 'th2', 'title': 'Pest control', 'kind': 'vendor', 'state': 'done', 'owner_member_id': 'mom', 'created_by': 'mom'})
    storage.set_cached_schedule({'events': [{'id': 'e1', 'title': 'Team Pictures', 'start': '2026-10-17T08:30:00', 'end': '2026-10-17T09:30:00', 'location': 'Field 3'}], 'assignments': {}, 'unassigned': ['e1']})
```

(Occasions are written with `storage.save_occasion(data)` and guests with `storage.save_occasion_guest`; check the exact `add_shopping_list`, `add_program` and `add_thread` key requirements in `services/storage.py` and `models/schemas.py` before seeding; `add_program` validates keys through `_check_program_keys`.)

Scenarios (each a `def scenario_...():` calling `_reset(); _seed()` first):

- A1 `scenario_find_ranks_exact_over_substring_over_sound_fold`: `find('trip', 'Disney World', MOM)[0]['id'] == 'ev_disney'` with score 1.0; `find('trip', 'disney', MOM)[0]['id'] == 'ev_disney'`; `find('occasion', 'Thanksgivin', MOM)[0]['id'] == 'o2'` (fold); every candidate has `kind, id, title, when, score`.
- A2 `scenario_find_prefers_upcoming_and_open_at_a_tie`: `find('thread', 'control', MOM)` lists `th2` (closed) but `find_all('Disney', MOM)` lists `th1` (open) before any closed row; a past trip (`ev_hawaii`, 2026-06) ranks below an upcoming one at equal score.
- A3 `scenario_visibility_filters_before_matching`: `find('occasion', "Kate's", KID) == []` and `find('occasion', 'zzz', KID) == []` (the same empty); `find('occasion', 'Thanksgiving', KID)` finds `o2`; `find('list', 'gifts', DAD) == []` (private, shared_with mom only) and `find('list', 'gifts', MOM)` finds `l2`; `find('program', 'Piano', KID)` finds `pr1` and `find('program', '10k', KID) == []`; `find('program', 'Piano', MOM)` finds `pr1`; `find('trip', 'Disney', None) == []` (anonymous, parents default) and `find('trip', 'Hawaii', None)` finds it (household).
- A4 `scenario_spoken_requires_the_kinds_own_audience`: `spoken_safe('trip', load('trip', 'ev_disney')) is False`; `spoken_safe('trip', load('trip', 'ev_hawaii')) is True`; `find('trip', 'Disney', MOM, spoken=True) == []`; `find('trip', 'Hawaii', MOM, spoken=True)` finds it; a thread row with `sensitivity: 'sensitive'` is not spoken_safe.
- A5 `scenario_find_caps_and_find_all_merges`: seed 7 more occasions titled "Party 1".."Party 7"; `len(find('occasion', 'Party', MOM)) == 5`; `len(find_all('a', MOM)) <= 8`.
- A6 `scenario_resolve_needs_a_clear_margin`: `resolve('Disney World', MOM)` → `(cand, _)` with `cand['id'] == 'ev_disney'`; seed members Grandpa and Grandma as assist contacts; `resolve('Grandma', MOM, kinds=['contact'])[0]['title'] == 'Grandma'` (exact wins); `resolve('Grandpaa', MOM, kinds=['contact'])` → `(None, cands)` with both names in `cands`.
- A7 `scenario_resolve_never_calls_a_cross_kind_tie_a_winner` (Review Focus 2): thread `th1` is titled "Disney dining"; `resolve('Disney', MOM)` returns `None` and candidates containing both `ev_disney` and `th1`.
- A8 `scenario_link_and_facets`: `link('trip', 'ev_disney') == '/trip?event_id=ev_disney'`; `link('occasion', 'o1').startswith('/occasions')`; `link('thread', 'th1') == '/threads'`; `facets('trip') == ['flights', 'accommodations', 'dining', 'attractions']`; `facets('occasion') == ['guests', 'menu', 'lists', 'errands']`; `facets('program') == ['sessions']`; `facets('thread') == ['history']`; `facets('member') == []`.
- A9 `scenario_a_calendar_only_trip_is_found_from_the_snapshot` (Review Focus 1): `find('trip', 'Beach', MOM)[0]['id'] == 'ev_beach'` (no metadata row); `load('trip', 'ev_beach')['title'] == 'Beach weekend'`.

- [ ] **Step 2: Run to verify it fails**: `python tests/test_subjects.py` → every scenario FAIL with `ModuleNotFoundError: services.subjects`.

- [ ] **Step 3: Implement `services/subjects.py`**

```python
"""Subjects: a Chauffeur record a thread or mission stands inside (spec 2026-10-14)."""
import datetime, difflib, time
from typing import Optional
from services import storage, scope

KINDS = ('trip', 'occasion', 'event', 'member', 'contact', 'thread', 'program', 'list')
FACETS = {'trip': ['flights', 'accommodations', 'dining', 'attractions'],
          'occasion': ['guests', 'menu', 'lists', 'errands'],
          'program': ['sessions'], 'thread': ['history'],
          'event': [], 'member': [], 'contact': [], 'list': []}
PER_KIND, OVERALL, BUDGET = 5, 8, 1500
WRITE_ROLES = ('parent', 'adult')

def facets(kind): return list(FACETS.get(kind, []))

# --- rows ------------------------------------------------------------------
def _trip_rows():
    snap = {t.get('id'): t for t in (storage.get_cached_trips() or {}).get('trips') or []}
    rows = {}
    for m in storage.get_all_trip_metadata():
        s = snap.get(m.get('event_id')) or {}
        rows[m['event_id']] = {**m, 'id': m['event_id'], 'title': m.get('title') or s.get('title') or 'Trip',
                              'start': s.get('start'), 'end': s.get('end'), 'location': m.get('location') or s.get('location')}
    for eid, s in snap.items():
        rows.setdefault(eid, {'id': eid, 'event_id': eid, 'title': s.get('title') or 'Trip', 'start': s.get('start'),
                              'end': s.get('end'), 'location': s.get('location'), 'audience': 'household', 'pois': [], 'accommodations': [], 'flights': [], '_calendar_only': True})
    return list(rows.values())

def _rows(kind):
    if kind == 'trip': return _trip_rows()
    if kind == 'occasion': return storage.get_occasions(include_done=True)
    if kind == 'event': return list((storage.get_cached_schedule() or {}).get('events') or [])
    if kind == 'member': return [m for m in storage.get_all_members() if not m.get('system')]
    if kind == 'contact': return storage.get_assist_contacts()
    if kind == 'thread': return storage.get_threads(include_closed=True)
    if kind == 'program': return storage.get_programs(include_finished=True)
    if kind == 'list': return storage.get_shopping_lists()
    return []

def load(kind, sid):
    return next((r for r in _rows(kind) if str(r.get('id')) == str(sid)), None)

def title_of(kind, row):
    if kind == 'contact': return row.get('relation_label') or row.get('name') or ''
    return row.get('title') or row.get('name') or ''

# --- visibility -------------------------------------------------------------
def visible(kind, row, viewer, spoken=False):
    if row is None: return False
    role = (viewer or {}).get('role')
    if kind in ('trip', 'occasion'):
        ok = scope.audience_allows(row, kind, viewer)
    elif kind == 'list':
        ok = scope.audience_allows(row, 'shopping_list', viewer)
    elif kind == 'program':
        from services.agent_tools_v2 import _program_scope_id
        ok = viewer is not None and (_program_scope_id(viewer) is None or row.get('member_id') == viewer.get('id'))
    elif kind == 'thread':
        from services import situations
        ok = situations.can_see('thread', row, viewer)
    elif kind == 'event':
        ok = scope.audience_allows(row, 'calendar_event', viewer)
    else:                                   # member, contact
        ok = role in WRITE_ROLES
    return bool(ok) and (not spoken or spoken_safe(kind, row))

def spoken_safe(kind, row):
    typ = {'list': 'shopping_list', 'event': 'calendar_event', 'trip': 'trip', 'occasion': 'occasion'}.get(kind, 'calendar_event')
    return bool(scope.audience_allows(row, typ, None)) and row.get('sensitivity') != 'sensitive' \
        and not row.get('private') and str(row.get('visibility') or '').lower() not in ('private', 'confidential')

# --- matching (the existing tiers) -----------------------------------------
def _score(query, title):
    from services.agent_tools_v2 import _fold_name
    q, t = query.strip().lower(), (title or '').strip().lower()
    if not q or not t: return 0.0
    if q == t: return 1.0
    if q in t or t in q: return 0.85
    if q.split()[0] == t.split()[0]: return 0.75
    if _fold_name(q) == _fold_name(t): return 0.7
    r = difflib.SequenceMatcher(None, _fold_name(q), _fold_name(t)).ratio()
    return r if r >= 0.8 else 0.0

def _when(kind, row):
    for k in ('start', 'anchor_date', 'next_action_at'):
        if row.get(k): return str(row[k])[:10]
    return ''

def _closed(kind, row):
    today = datetime.date.today().isoformat()
    if kind in ('trip', 'occasion', 'event'):
        w = _when(kind, row); return bool(w) and w < today
    if kind == 'thread': return row.get('state') in ('done', 'dropped')
    if kind == 'program': return row.get('state') in ('done', 'dropped')
    return False

def find(kind, query, viewer, spoken=False):
    out = []
    for row in _rows(kind):
        if not visible(kind, row, viewer, spoken): continue
        s = _score(query, title_of(kind, row))
        if s <= 0: continue
        out.append({'kind': kind, 'id': str(row.get('id')), 'title': title_of(kind, row), 'when': _when(kind, row), 'score': s, '_closed': _closed(kind, row)})
    out.sort(key=lambda c: (-c['score'], c['_closed'], c['when'] or '9999'))
    return [{k: v for k, v in c.items() if k != '_closed'} for c in out[:PER_KIND]]

def find_all(query, viewer, kinds=None, spoken=False):
    cands = [c for k in (kinds or KINDS) for c in find(k, query, viewer, spoken)]
    cands.sort(key=lambda c: (-c['score'], c['when'] or '9999'))
    return cands[:OVERALL]

def resolve(query, viewer, kinds=None, spoken=False):
    cands = find_all(query, viewer, kinds, spoken)
    if cands and cands[0]['score'] >= 0.8 and (len(cands) == 1 or cands[0]['score'] - cands[1]['score'] >= 0.06):
        return cands[0], cands
    return None, cands

def link(kind, sid):
    return {'trip': f'/trip?event_id={sid}', 'occasion': f'/occasions#{sid}', 'event': f'/app?event={sid}',
            'member': f'/app?member={sid}', 'contact': '/drives?settings=outside-hands', 'thread': '/threads',
            'program': f'/programs#{sid}', 'list': f'/shopping#{sid}'}.get(kind, '/')
```

Confirm `_fold_name` exists in `agent_tools_v2` (the sound fold `_match_person` uses); if it is named differently, import that name. `_score` keeps the margin rule `_match_person` uses (0.8 floor, 0.06 margin).

- [ ] **Step 4: Run** `python tests/test_subjects.py` → A1–A9 PASS. Fix seeding keys as the storage validators demand.
- [ ] **Step 5: Commit** (Claude: gate, bump `config.yaml`, note in `system_capabilities.md`): `feat(subjects): the resolver - one registry over trips, occasions, events, people, contacts, threads, programs and lists; visibility filtered before matching; existing match tiers and margin`.

---

### Task 2: `context()` per kind, trip dates, facets

**Files:**
- Modify: `services/subjects.py`
- Test: `tests/test_subjects.py` (scenarios B1–B7)

**Interfaces:**
- Produces: `trip_dates(event_id) -> {start, end, source: 'draft'|'calendar'|'unknown', age_s}`; `context(kind, sid, viewer, spoken=False, facet=None) -> str|None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_subjects.py`):

- B1 `scenario_context_is_none_for_missing_and_excluded_alike`: `context('occasion', 'nope', MOM) is None`; `context('occasion', 'o1', KID) is None`; `context('occasion', 'o1', MOM)` contains "Kate's 10th birthday" and "2027-02-14" or "February".
- B2 `scenario_trip_context_general_view`: text contains "Disney World", "Orlando", "4 travel", "Pop Century", "DL123", "Magic Kingdom", "Chef Mickey's"; "facets: flights, accommodations, dining, attractions" appears; `len(text) <= 1500`.
- B3 `scenario_trip_dining_facet_lists_food_pois_with_windows`: `context('trip', 'ev_disney', MOM, facet='dining')` contains "Chef Mickey's" and "breakfast" and "Be Our Guest" and "not scheduled", and does NOT contain "Magic Kingdom"; `facet='attractions'` contains "Magic Kingdom" and not "Chef Mickey's"; `facet='flights'` contains "DL123"; `facet='accommodations'` contains "Pop Century" and "5 nights".
- B4 `scenario_trip_context_caps_pois_and_says_how_many_more`: seed a trip with 40 POIs; general view names 30 and says "and 10 more"; `len <= 1500`.
- B5 `scenario_trip_dates_say_their_source_and_age`: draft trip (`is_draft: True`, `mock_start_date`/`mock_end_date`) → `trip_dates` source 'draft' and context says the dates; `ev_disney` with the snapshot written now → source 'calendar', context does not mention age; patch `storage.get_cached_trips` to return `{'trips': [...], 'at': time.time() - 9*3600}` → context contains "9 hours ago"; no snapshot row and no draft → source 'unknown' and context contains "dates unknown".
- B6 `scenario_occasion_context_filters_linked_lists_by_viewer`: `context('occasion', 'o1', MOM)` names "Kate gifts"; `context('occasion', 'o1', DAD)` (a parent, allowed the occasion, excluded from the private list) does NOT contain "Kate gifts"; `facet='guests'` lists the seeded guests with headcount.
- B7 `scenario_other_kinds_context` + Review Focus 1: event → "Team Pictures", "no driver yet", "Field 3"; member → "Mom (parent)"; contact → relation label and helps-with, phone absent when `spoken=True`; thread → title, state, next action; program → "Piano", "Kate"; list → "Groceries" and item count; `context('trip', 'ev_beach', MOM)` contains "no itinerary on file".

- [ ] **Step 2: Run** → B1–B7 FAIL (`AttributeError: context`).

- [ ] **Step 3: Implement** in `services/subjects.py`:

```python
def trip_dates(event_id):
    m = storage.get_trip_metadata(event_id) or {}
    if m.get('is_draft') and m.get('mock_start_date'):
        f = lambda ts: datetime.date.fromtimestamp(float(ts)).isoformat()
        return {'start': f(m['mock_start_date']), 'end': f(m['mock_end_date']) if m.get('mock_end_date') else None, 'source': 'draft', 'age_s': 0}
    snap = storage.get_cached_trips() or {}
    row = next((t for t in snap.get('trips') or [] if t.get('id') == event_id), None)
    if row and row.get('start'):
        return {'start': row['start'], 'end': row.get('end'), 'source': 'calendar', 'age_s': max(0, time.time() - float(snap.get('at') or time.time()))}
    return {'start': None, 'end': None, 'source': 'unknown', 'age_s': None}

def _age_words(age_s):
    if age_s is None or age_s < 3600: return ''
    h = int(age_s // 3600)
    return f" (as the calendar had them {h} hours ago)" if h < 48 else f" (as the calendar had them {h // 24} days ago)"

def _clip(lines, budget=BUDGET):
    out, used = [], 0
    for ln in lines:
        if used + len(ln) + 1 > budget: break
        out.append(ln); used += len(ln) + 1
    return '\n'.join(out)

def _fmt_window(poi):
    if not poi.get('is_scheduled') or not poi.get('scheduled_start'): return 'not scheduled'
    a = datetime.datetime.fromtimestamp(float(poi['scheduled_start']))
    b = datetime.datetime.fromtimestamp(float(poi['scheduled_end'])) if poi.get('scheduled_end') else None
    return a.strftime('%a %b %d %I:%M %p').replace(' 0', ' ') + (b.strftime(' to %I:%M %p').replace(' 0', ' ') if b else '')

def _trip_context(row, viewer, spoken, facet):
    d = trip_dates(row['event_id'])
    head = [f"TRIP: {row['title']}" + (f", {row['location']}" if row.get('location') else '')]
    if d['source'] == 'unknown': head.append("Dates unknown; confirm them before booking anything.")
    else: head.append(f"Dates: {d['start']} to {d['end'] or '?'}{_age_words(d['age_s'])}" + (" (draft)" if d['source'] == 'draft' else ''))
    if row.get('travelers'): head.append(f"{row['travelers']} travellers.")
    head.append("facets: " + ', '.join(FACETS['trip']))
    pois = row.get('pois') or []
    food = [p for p in pois if (p.get('category') or '') == 'food']
    other = [p for p in pois if (p.get('category') or '') != 'food']
    def poi_line(p):
        meal = f" ({p['meal_type']})" if p.get('meal_type') else ''
        return f"- {p.get('name')}{meal}, {p.get('category') or 'other'}: {_fmt_window(p)}" + (f", {p['location']}" if p.get('location') else '')
    def acc_lines():
        out = []
        for a in row.get('accommodations') or []:
            nights = ''
            try:
                n = (datetime.date.fromisoformat(a['check_out_date']) - datetime.date.fromisoformat(a['check_in_date'])).days
                nights = f", {n} nights"
            except Exception: pass
            out.append(f"- {a.get('name')}, {a.get('location') or ''}: {a.get('check_in_date') or '?'} to {a.get('check_out_date') or '?'}{nights}")
        return out or ['- none on file']
    def flight_lines():
        return [f"- {f.get('airline') or ''} {f.get('flight_number') or ''} {f.get('origin') or '?'} to {f.get('destination') or '?'} {f.get('departure_time') or ''}".strip()
                for f in row.get('flights') or []] or ['- none on file']
    if facet == 'dining': return _clip(head + ['DINING:'] + ([poi_line(p) for p in sorted(food, key=lambda p: p.get('scheduled_start') or 9e12)] or ['- none on file']))
    if facet == 'attractions': return _clip(head + ['ATTRACTIONS:'] + ([poi_line(p) for p in other] or ['- none on file']))
    if facet == 'flights': return _clip(head + ['FLIGHTS:'] + flight_lines())
    if facet == 'accommodations': return _clip(head + ['ACCOMMODATIONS:'] + acc_lines())
    if row.get('_calendar_only') and not pois: return _clip(head + ['No itinerary on file for this trip.'])
    scheduled = sorted([p for p in pois if p.get('is_scheduled')], key=lambda p: p.get('scheduled_start') or 0) + [p for p in pois if not p.get('is_scheduled')]
    body = ['ACCOMMODATIONS:'] + acc_lines() + ['FLIGHTS:'] + flight_lines() + ['STOPS (dining is category food):'] + [poi_line(p) for p in scheduled[:30]]
    if len(scheduled) > 30: body.append(f"- and {len(scheduled) - 30} more")
    return _clip(head + body)
```

Then `_occasion_context` (from `occasions.contents`; lists re-filtered with `scope.audience_allows(l, 'shopping_list', viewer)`; facets guests/menu/lists/errands; menu = dish tags + items named "dish" if the Occasions arc stores them; read `occasions.py` for the dish list helper before writing), `_event_context` (title, date and time from `start`, location, driver from `assignments` via `storage.get_all_drivers` name lookup or "no driver yet", passengers from `passengers`/`passenger_names` when present), `_member_context`, `_contact_context` (omit `phone`/`email` values when `spoken`), `_thread_context` (title, goal, state, counterparty, next action + date, last three `history` entries' `text`), `_program_context` (title, member name, state, this week's sessions if the program row carries `sessions`/`plan`; read `services/programs.py` for the field), `_list_context` (name, count, first ten item names). Then:

```python
def context(kind, sid, viewer, spoken=False, facet=None):
    row = load(kind, sid)
    if not visible(kind, row, viewer, spoken): return None
    if facet and facet not in FACETS.get(kind, []): facet = None
    fn = {'trip': _trip_context, 'occasion': _occasion_context, 'event': _event_context, 'member': _member_context,
          'contact': _contact_context, 'thread': _thread_context, 'program': _program_context, 'list': _list_context}[kind]
    return fn(row, viewer, spoken, facet)
```

- [ ] **Step 4: Run** `python tests/test_subjects.py` → all A and B PASS.
- [ ] **Step 5: Commit**: `feat(subjects): context in words per kind, facets, trip dates with their source and age, linked lists re-filtered per viewer`.

---

### Task 3: The fields, `subject_of`, audience inheritance, view payload

**Files:**
- Modify: `models/schemas.py` (Thread: three fields), `services/storage.py:2977` (`add_mission` row defaults), `services/missions.py` (`subject_of`, `_dm_person` recipients), `services/situations.py` (`can_see`, `view` payload), `main.py:6085-6111` (`missions_admin`, `missions_detail`), `main.py:6738` (`list_threads`)
- Test: `tests/test_subject_audience.py`

**Interfaces:**
- Produces: `missions.subject_of(mission) -> (kind, id, rev) | (None, None, 0)`; `situations.subject_view(kind, row, viewer) -> {kind, id, title, link, rev} | None`; view payload key `subject`.

- [ ] **Step 1: Write the failing tests** — `tests/test_subject_audience.py` with the Task 1 fixture (import `_seed` from `test_subjects`) plus threads/missions:

- `scenario_a_thread_origin_mission_reads_its_threads_subject`: thread `th1` with `subject_kind='trip', subject_id='ev_disney'`; mission `origin_kind='thread', origin_ref='th1'` → `missions.subject_of(m) == ('trip', 'ev_disney', 0)`; a manual mission with its own fields returns its own; a thread-origin mission with stale own fields still returns the thread's.
- `scenario_a_bound_situation_inherits_the_subjects_audience`: thread `th1` bound to occasion `o1` (parents default): `situations.can_see('thread', row, AUNT) is False` (an adult could see it before), `True` for MOM; bound to `o2` (household) → AUNT True; a mission bound to the private list `l2` (shared_with mom) → `can_see('mission', row, DAD) is False`.
- `scenario_detail_admin_and_lists_apply_it`: `main.missions_detail` for AUNT on a mission about `o1` raises 403 (use the `_auth` monkeypatch from `test_situation_endpoints._as`); `main.missions_admin` for AUNT omits it; `situations.list_situations(AUNT)` omits the thread; `main.list_threads(request=...)` for AUNT omits it (read how `list_threads` resolves its viewer; if it has none today, add `_mind_actor` the way `missions_admin` does).
- `scenario_dm_skips_the_excluded_parent_but_keeps_the_creator` (Review Focus 5): mission created by `dad`, no thread, bound to `l2` (shared_with mom only), status waiting_user with a `question` ask; `_dm_person(mission, 'q')` with `missions._post` captured → one DM to dad (creator) whose text does not contain "Kate gifts"; a mission with `created_by=None` DMs mom only (dad excluded).
- `scenario_view_carries_the_subject_only_for_an_allowed_viewer`: `situations.view('thread', 'th1', MOM)['subject'] == {'kind': 'occasion', 'id': 'o1', 'title': "Kate's 10th birthday", 'link': '/occasions#o1', 'rev': 0}`; for a thread bound to `l2`, `view(..., DAD)` — DAD cannot see the thread at all now (returns None from `list`), but a thread OWNED by dad bound to `l2`: `view('thread', tid, DAD)['subject'] is None` and `can_see` True (today's owner grant stands, the subject's words are withheld).

- [ ] **Step 2: Run** → FAIL on `subject_of`/`subject` key.
- [ ] **Step 3: Implement**: schema fields `subject_kind: Optional[str] = None`, `subject_id: Optional[str] = None`, `subject_rev: int = 0` on `Thread`; `add_mission` defaults the same three; `missions.subject_of`:

```python
def subject_of(mission):
    if (mission or {}).get('origin_kind') == 'thread' and mission.get('origin_ref'):
        t = storage.get_thread(mission['origin_ref']) or {}
        return (t.get('subject_kind'), t.get('subject_id'), int(t.get('subject_rev') or 0)) if t.get('subject_kind') else (None, None, 0)
    return (mission.get('subject_kind'), mission.get('subject_id'), int(mission.get('subject_rev') or 0)) if (mission or {}).get('subject_kind') else (None, None, 0)
```

`situations.can_see`: after today's result for thread/mission, `if ok and kind in ('thread','mission'): k, sid, _ = _subject_of(kind, row); if k: from services import subjects; ok = subjects.visible(k, subjects.load(k, sid), viewer)` — EXCEPT the owner grant on a thread (`row.get('owner_member_id') == viewer.get('id')`) keeps `ok` True (Review Focus 5) while `subject_view` returns None. `subject_view(kind, row, viewer)` builds `{kind, id, title, link, rev}` via `subjects.load/title_of/link` only when `subjects.visible`. `view()` adds `'subject': subject_view(kind, row, viewer)`. `missions_detail`: `actor = _mind_actor(request, None)`; `if not situations.can_see('mission', row, actor): raise HTTPException(403)`. `missions_admin`: filter both lists by `can_see` for the actor. `list_threads`: filter by `can_see('thread', t, actor)`. `_dm_person`: `people = [m for m in people if situations.can_see('mission', mission_row, m)]` where the creator is kept when they own it (a creator who may not see the subject still gets the ask; the ask text never carries subject words because `_dm_person` only posts the ask's own text).

- [ ] **Step 4: Run** `python tests/test_subject_audience.py`, plus `tests/test_situations.py`, `tests/test_situation_endpoints.py`, `tests/test_mission_chat_cards.py`, `tests/test_missions_endpoints.py` → PASS.
- [ ] **Step 5: Commit**: `feat(subjects): subject fields on threads and missions, a thread's missions read the thread's, a bound situation inherits its subject's audience (can_see, detail, admin list, thread list, DMs), view carries the subject`.

---

### Task 4: `find_in_chauffeur` tool, planner `subject` action, fresh ABOUT

**Files:**
- Modify: `services/agent_tools_v2.py` (tool schema class `FindInChauffeurTool`, `find_in_chauffeur()`, `handle_find_in_chauffeur`, entries in `get_available_tools`, `TOOL_SCHEMAS`, `TOOL_HANDLERS`), `services/missions.py` (`READ_TOOLS`, `_audience_viewer`, `_system_prompt`, `step` tool branch + `subject` action)
- Test: `tests/test_mission_subject.py` (scenarios A)

**Interfaces:**
- Produces: `agent_tools_v2.find_in_chauffeur(query, kind='', facet='', acting_member=None, spoken=False) -> {status, candidates, context}`; `missions._audience_viewer(mission) -> dict`; planner action `{"action":"subject","kind","id"}`; `missions.about_block(mission) -> str`.

- [ ] **Step 1: Write the failing tests** (`tests/test_mission_subject.py`, fixture from `test_subjects._seed` plus the mission fixture from `test_mission_steer`):

- A1 `scenario_find_in_chauffeur_finds_and_reads_a_clear_winner`: `tools.find_in_chauffeur('Disney World', acting_member=MOM)` → `status 'success'`, `candidates[0]['id'] == 'ev_disney'`, `context` contains "TRIP: Disney World"; with `facet='dining'` the context contains "Chef Mickey's"; `find_in_chauffeur('Disney', acting_member=MOM)` (trip + thread tie) → `context is None` and two candidates; `find_in_chauffeur('', acting_member=MOM)` → `status 'error'` (Review Focus 4); `find_in_chauffeur("Kate's", acting_member=KID)` → `candidates == []`.
- A2 `scenario_planner_read_stores_candidates_only`: mission (manual, mom) ; `missions._llm` returns `{'action':'tool','tool':'find_in_chauffeur','args':{'query':'Disney World'}}`; `missions.step` → the stored step `result_json` has `candidates` and NO `context` key (or `context` None); `missions.READ_TOOLS` contains `'find_in_chauffeur'`.
- A3 `scenario_subject_action_binds_a_manual_mission_and_the_thread_of_a_thread_mission`: manual mission, `_llm` → `{'action':'subject','kind':'trip','id':'ev_disney'}`; after `step`, `storage.get_mission(mid)['subject_kind'] == 'trip'` and a `note` step named `subject`; thread-origin mission on `th1` (unbound) → the THREAD gets the fields and the mission's own stay None; thread already bound → a note named `refused` and nothing changes; `{'action':'subject','kind':'trip','id':'nope'}` → `refused`.
- A4 `scenario_every_step_leads_with_fresh_about`: mission bound to `ev_disney`; capture the system prompt handed to `_llm`; it contains `ABOUT: trip "Disney World"` and "Chef Mickey's"; rename the POI in storage between two steps → the second prompt carries the new name; the stored steps never contain "ABOUT:".
- A5 `scenario_about_is_withheld_when_the_audience_viewer_may_not_see`: a mission about the private list `l2` created by dad (`_audience_viewer` → a parent of record who may see it, i.e. mom when dad cannot) carries ABOUT; a mission about a record nobody of record may see (seed a private list with `shared_with: []`) carries no ABOUT and the planner is told "the subject is not readable here".

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**. Tool (next to `get_occasion`):

```python
class FindInChauffeurTool(BaseModel):
    """Finds something the family already has in Chauffeur (a trip, a party or holiday, a calendar event, a person, an outside contact, a thread, a program, a list) from a few words, and reads its current state when the match is clear."""
    query: str = Field(..., description="Words naming it: 'the Disney trip', 'Kate's birthday', 'Grandma'.")
    kind: Optional[str] = Field("", description="One of trip, occasion, event, member, contact, thread, program, list; omit to search everything.")
    facet: Optional[str] = Field("", description="A part to read in full: trip flights|accommodations|dining|attractions; occasion guests|menu|lists|errands; program sessions; thread history.")

def find_in_chauffeur(query: str, kind: str = '', facet: str = '', acting_member: dict = None, spoken: bool = False):
    from services import subjects
    q = (query or '').strip()
    if not q: return {"status": "error", "message": "Say what to look for."}
    kinds = [kind] if kind in subjects.KINDS else None
    winner, cands = subjects.resolve(q, acting_member, kinds=kinds, spoken=spoken)
    ctx = subjects.context(winner['kind'], winner['id'], acting_member, spoken=spoken, facet=facet or None) if winner else None
    return {"status": "success", "candidates": cands, "context": ctx,
            "message": (f"Found {winner['title']}." if winner else ("Nothing by that name." if not cands else "More than one: " + '; '.join(c['title'] for c in cands)))}
```

Handler: `handle_find_in_chauffeur(args)` → `find_in_chauffeur(args.get('query') or '', args.get('kind') or '', args.get('facet') or '', acting_member=_registry_parent_or(args))` — in the planner, `missions.step` must call it with the mission's audience viewer: add to `missions.step` before `execute_tool`: `if name == 'find_in_chauffeur': out = agent_tools_v2.find_in_chauffeur(**(res.get('args') or {}), acting_member=_audience_viewer(mission)); stored = {**out, 'context': None}` and feed `out` (with context) to the model via the step's result for THIS call only — simplest: store `stored`, and append the context to the next `_user_prompt` through a transient `mission['_last_context']` kept in memory only (a module-level dict keyed by mission id, cleared after the next step builds its prompt). `_audience_viewer(mission)`: `k, sid, _ = subject_of(mission)`; if no subject → `agent_tools_v2._REGISTRY_READER`; else the creator when `subjects.visible(k, row, creator)`, else the first parent of record who may see it, else `None`. `about_block(mission)`: `k, sid, _ = subject_of(mission)`; if none → ''; `ctx = subjects.context(k, sid, _audience_viewer(mission))`; if `ctx is None` → "ABOUT: the subject is not readable here; do not guess its contents.\n"; else `f'ABOUT: {k} "{title}"\n{ctx}\n(This is the record as it stands now; it outranks anything older in the transcript. Facets: {", ".join(subjects.facets(k)) or "none"}.)\n'`. `_system_prompt` inserts `about_block(mission)` after `_family_context` (signature grows `mission=None`). The `subject` action in `step`:

```python
    if action == 'subject':
        from services import subjects
        k, sid = (res.get('kind') or '').strip(), str(res.get('id') or '').strip()
        row = subjects.load(k, sid) if k in subjects.KINDS else None
        if not row:
            storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused', 'result_json': {'note': 'no such record to bind'}})
            return storage.get_mission(mid)
        if mission.get('origin_kind') == 'thread' and mission.get('origin_ref'):
            t = storage.get_thread(mission['origin_ref']) or {}
            if t.get('subject_kind'):
                storage.add_mission_step(mid, {'kind': 'note', 'name': 'refused', 'result_json': {'note': f"already about {t['subject_kind']} {t['subject_id']}; a person unlinks it"}})
                return storage.get_mission(mid)
            storage.update_thread(t['id'], {'subject_kind': k, 'subject_id': sid, 'subject_rev': int(t.get('subject_rev') or 0) + 1})
        else:
            storage.update_mission(mid, {'subject_kind': k, 'subject_id': sid, 'subject_rev': int(mission.get('subject_rev') or 0) + 1})
        storage.add_mission_step(mid, {'kind': 'note', 'name': 'subject', 'result_json': {'kind': k, 'id': sid, 'title': subjects.title_of(k, row)}})
        return storage.get_mission(mid)
```

System prompt addition: the JSON form `{"action":"subject","kind":"<kind>","id":"<id from find_in_chauffeur>"}` and the sentence "When the goal names something the family already has and no ABOUT block is above, call find_in_chauffeur first and bind it with the subject action; when ABOUT is above, it is the truth, not the transcript's older reading; a subject_changed note means re-read before acting."

- [ ] **Step 4: Run** `python tests/test_mission_subject.py` + `tests/test_missions_engine.py`, `tests/test_browse_mission.py`, `tests/test_mission_steer.py` → PASS.
- [ ] **Step 5: Commit**: `feat(subjects): find_in_chauffeur READ tool for chat and planner (candidates stored, context never), the planner binds with a subject action (the thread for a thread mission, only when unbound), fresh ABOUT heads every step`.

---

### Task 5: `start_mission_for` with a subject, focus reuse, dedupe, router rule, chat ABOUT

**Files:**
- Modify: `services/agent_tools_v2.py:1764-1830` (`start_mission_for`), `services/agent_router.py:262-300` (focus block + rule)
- Test: `tests/test_mission_subject.py` (scenarios B), `tests/test_agent_driver_tools.py` (one router scenario)

- [ ] **Step 1: Write the failing tests**:

- B1 `scenario_start_mission_for_writes_the_subject_on_the_thread`: `tools.start_mission_for('book dining for the Disney trip', acting_member=MOM, focus_key='conv:1', subject_kind='trip', subject_id='ev_disney')` → thread has the fields; `missions.subject_of(mission) == ('trip','ev_disney',1)`.
- B2 `scenario_focus_thread_is_reused_only_on_a_compatible_subject`: focus on an open thread with no live mission and no subject → reused and bound; focus thread bound to `ev_hawaii` + new goal with `ev_disney` → a NEW thread; focus thread bound to `ev_disney` → reused.
- B3 `scenario_dedupe_needs_subject_and_intent`: live mission "book flights for Disney" on a thread bound to `ev_disney`; `start_mission_for('book dining for Disney', ..., subject_id='ev_disney')` → a new mission (status success, different `mission_id`); `start_mission_for('book flights to Disney', ..., subject_id='ev_disney')` → "already under way" with the first mission id; subject-less goals keep the first-three-words rule (reuse the existing test in `test_start_mission.py` unchanged).
- Router (in `test_agent_driver_tools.py`, after `scenario_router_injects_the_family_roster`, same `fake_gemma` capture): focus a thread bound to `ev_disney` via `triage.set_focus('conv:9', 'thread', tid, 'Disney dining')`; `agent_router.process_agent_request('what is left to book', source='pwa', member_id='mom', focus_key='conv:9')` (match the real kwargs of `process_agent_request`) → captured system prompt contains `ABOUT: trip "Disney World"` and the rule text "call find_in_chauffeur"; with a child as the member the prompt has no ABOUT.

- [ ] **Step 2: Run** → FAIL (`unexpected keyword subject_kind`).
- [ ] **Step 3: Implement**: `start_mission_for(goal, title=None, acting_member=None, focus_key=None, voice_context=None, subject_kind=None, subject_id=None)`; validate the pair with `subjects.load` and `subjects.visible(..., acting_member, spoken)` (invalid → ignore silently, proceed subject-less). Dedupe loop: when a subject is given, match `m` only if `subject_of(m)[:2] == (subject_kind, subject_id)` and `_intent_words(goal, title_words) == _intent_words(m['goal'], title_words)` where `_intent_words` = first three content words (len > 2) after removing the subject title's words; without a subject keep today's rule. Focus reuse: `t.get('subject_kind') in (None, subject_kind) and (t.get('subject_id') in (None, subject_id))` else `tid = None`. After `_threads.create` or reuse: if subject given and the thread is unbound → `storage.update_thread(tid, {'subject_kind', 'subject_id', 'subject_rev': +1})`. Router: in the focus block, after `_nxt`, `sv = _s.get('subject')`; if `sv`: `ctx = subjects.context(sv['kind'], sv['id'], _viewer)`; append `f'\nABOUT: {sv["kind"]} "{sv["title"]}"\n{ctx}\n'` when `ctx`. Rule text in the ARGYLE ACTS block: "Before start_mission_for for a goal that names something the family has (a trip, a party, an event, a person, a list), call find_in_chauffeur and pass the winner as subject_kind and subject_id; if it returns more than one, ask which." Tool schema for `start_mission_for` gains the two optional string fields.

- [ ] **Step 4: Run** `tests/test_mission_subject.py`, `tests/test_start_mission.py`, `tests/test_agent_driver_tools.py` → PASS.
- [ ] **Step 5: Commit**: `feat(subjects): start_mission_for carries a resolved subject, reuses a focus thread only on a compatible one, dedupes on subject plus intent; the router resolves before starting and the chat prompt carries ABOUT for a bound focus thread`.

---

### Task 6: Retarget and the `subject` verb

**Files:**
- Modify: `services/subjects.py` (`retarget`), `services/situations.py` (`VERBS`, `_options_thread`, `_options_mission`, `_run`), `services/agent_tools_v2.py` (`act_on_situation` verb enum + payload)
- Test: `tests/test_subject_retarget.py`

**Interfaces:**
- Produces: `subjects.retarget(sit_kind, sid, new_kind, new_id, actor) -> {status, message, candidates?}`; option ids `subject` (bind/change) and `subject:clear`; `act` payload `{query}` | `{kind, id}` | `{clear: true}`.

- [ ] **Step 1: Write the failing tests**:
- `scenario_retarget_refused_while_an_ask_is_pending_or_browsing`: thread with a live mission waiting on a `release` ask → `retarget('thread', tid, 'trip', 'ev_hawaii', MOM)` → `status 'refused'`, message contains "pending"; mission `browsing` → refused; mission `waiting_retry` (Review Focus 3) → success and the next `_system_prompt` carries Hawaii.
- `scenario_retarget_bumps_rev_notes_and_dismisses_proposals`: thread bound to Disney with a running mission holding a `proposal` step whose action proposal is `proposed` → after retarget to Hawaii: `subject_rev` 2, a `note` step `subject_changed` with old and new titles, the proposal's status `dismissed`; `retarget(..., None, None, MOM)` clears (fields None, rev bumped, note says "unlinked").
- `scenario_subject_verb_through_act`: `situations.options_for('thread', row)` has an option `id == 'subject'` labelled "Link to something in Chauffeur" (unbound) / "About: Disney World (change)" (bound) and, when bound, `subject:clear` "Unlink"; `situations.act('thread', tid, 'subject', option_id='subject', payload={'query': 'Disney World'}, actor=MOM)` → success, bound; `payload={'query': 'Disney'}` (tie) → `status 'choose'`, `candidates` list; `payload={'kind':'trip','id':'ev_hawaii'}` → bound; `option_id='subject:clear', payload={'clear': True}` → cleared; a child → refused; a manual mission card has the same option.
- `scenario_act_on_situation_subject_verb`: `tools.act_on_situation(verb='subject', text='Disney World', acting_member=MOM, focus_key='conv:1')` binds the focus thread.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**. `retarget`:

```python
def retarget(sit_kind, sid, new_kind, new_id, actor):
    from services import missions as _m, situations as _sit
    if (actor or {}).get('role') not in WRITE_ROLES: return {'status': 'refused', 'message': 'Only a parent or adult can do that.'}
    row = _sit.load(sit_kind, sid)
    if not row: return {'status': 'error', 'message': 'That is no longer here.'}
    live = [m for m in storage.get_missions(status=['running', 'browsing', 'waiting_user', 'waiting_retry'])
            if (sit_kind == 'mission' and m['id'] == sid) or (sit_kind == 'thread' and m.get('origin_kind') == 'thread' and m.get('origin_ref') == sid)]
    for m in live:
        if m.get('status') == 'browsing' or _m.tap_only_ask_pending(m['id']):
            return {'status': 'refused', 'message': 'Finish or stop the pending step first; then change what this is about.'}
    if new_kind:
        rec = load(new_kind, new_id)
        if not rec or not visible(new_kind, rec, actor): return {'status': 'error', 'message': 'Nothing by that name you can see.'}
    old_k, old_id = row.get('subject_kind'), row.get('subject_id')
    rev = int(row.get('subject_rev') or 0) + 1
    fields = {'subject_kind': new_kind or None, 'subject_id': new_id or None, 'subject_rev': rev}
    (storage.update_thread if sit_kind == 'thread' else storage.update_mission)(sid, fields)
    old_t = title_of(old_k, load(old_k, old_id)) if old_k and load(old_k, old_id) else None
    new_t = title_of(new_kind, load(new_kind, new_id)) if new_kind else None
    for m in live:
        storage.add_mission_step(m['id'], {'kind': 'note', 'name': 'subject_changed', 'result_json': {'from': old_t, 'to': new_t, 'rev': rev, 'note': ('unlinked' if not new_kind else f'now about {new_t}') + '; re-read before acting'}})
        for s in storage.get_mission_steps(m['id']):
            pid = (s.get('result_json') or {}).get('proposal_id') if s.get('kind') == 'proposal' else None
            prop = storage.get_action_proposal(pid) if pid else None
            if prop and prop.get('status') == 'proposed':
                storage.update_action_proposal(pid, {'status': 'dismissed'})
    _sit.bump_rev(sit_kind, sid); _sit.request_refresh(sit_kind, sid)
    return {'status': 'success', 'message': ('Unlinked.' if not new_kind else f'Now about {new_t}.'), 'rev': rev}
```

`situations`: add `'subject'` to `VERBS`; in `_options_thread` and `_options_mission` (manual missions only, i.e. `origin_kind != 'thread'`) append `_opt('subject', label, {})` and, when bound, `_opt('subject', 'Unlink', {'clear': True}, 'clear')` — keep them at the back, before close; `_run` branch:

```python
    if verb == 'subject':
        from services import subjects
        if p.get('clear'): return subjects.retarget(kind, sid, None, None, actor)
        if p.get('kind') and p.get('id'): return subjects.retarget(kind, sid, p['kind'], p['id'], actor)
        q = (p.get('query') or '').strip()
        if not q: return {'status': 'error', 'message': 'Say what it is about.'}
        winner, cands = subjects.resolve(q, actor)
        if winner: return subjects.retarget(kind, sid, winner['kind'], winner['id'], actor)
        return {'status': 'choose', 'message': 'Which one?' if cands else 'Nothing by that name.', 'candidates': cands}
```

`act` must let `query`, `kind`, `id`, `clear` through for verb `subject` (extend the free-payload merge). `act_on_situation`: add `'subject'` to the enum and `payload['query'] = text` for it.

- [ ] **Step 4: Run** `tests/test_subject_retarget.py`, `tests/test_situations.py`, `tests/test_situation_tools.py`, `tests/test_mission_steer.py` → PASS.
- [ ] **Step 5: Commit**: `feat(subjects): retarget guarded while an ask is pending or a browse is live (rev, subject_changed note, pending proposals dismissed), the subject verb on thread and mission cards and through act_on_situation`.

---

### Task 7: Hand path — chip, picker flow, back-link

**Files:**
- Modify: `static/situations.js` (`cardHtml` chip, `act` branch for verb `subject`), `main.py` (`GET /api/subjects/{kind}/{sid}/situations`), `services/auth.py` (route rule), `templates/trip.html` (one line under `#trip-location`), `templates/occasions.html` (one line per card)
- Test: `tests/test_subject_hand_path.py` (python + node)

- [ ] **Step 1: Write the failing tests**:
- Python `scenario_backlink_endpoint_is_viewer_filtered`: thread bound to `o1` with a live mission; `main.subject_situations('occasion', 'o1', request=_Req('mom'))` → one row `{kind:'thread', id, title, next_step}`; for AUNT → `[]`; for KID → 403; `services/auth.py` has a rule for `/api/subjects/*` (grep the rules list in the test).
- Node (jsdom, the `test_pwa_assign_other_driver.py` harness pattern, loading `static/situations.js` whole): `cardHtml(s, {canWrite: true})` with `s.subject = {kind:'trip', id:'ev_disney', title:'Disney World', link:'/trip?event_id=ev_disney'}` contains `data-sit-subject` and the title and the href; with `s.subject = null` no chip; `act(s, {verb:'subject', id:'subject', payload:{}}, ctx)` with `promptInput` stubbed to return 'Disney' and `fetch` stubbed to answer `{status:'choose', candidates:[{kind:'trip',id:'ev_disney',title:'Disney World'},{kind:'thread',id:'th1',title:'Disney dining'}]}` on the first post → `promptChoice` is called with two options and the second post carries `{kind:'trip', id:'ev_disney'}`; `promptInput` returning null posts nothing; option `subject:clear` posts `{clear:true}` after `promptConfirm`.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**. `situations.js` `cardHtml`: after the meta line, `const subj = s.subject ? `<div class="sit-subject text-[11px] text-indigo-300 mt-0.5" data-sit-subject="${esc(s.subject.kind)}:${esc(s.subject.id)}">About: <a class="underline underline-offset-2" href="${esc(ctx.apiBase ? ctx.apiBase.replace(/\/$/, '') + s.subject.link : s.subject.link)}">${esc(s.subject.title)}</a></div>` : '';` inserted into the card. `act`: before the generic post,

```js
    if (option.verb === 'subject') {
      let payload;
      if (option.payload && option.payload.clear) {
        if (window.promptConfirm && !await promptConfirm('Unlink it?', s.title, 'Unlink', 'Keep')) return;
        payload = { clear: true };
      } else {
        const q = window.promptInput ? await promptInput('What is this about?', 'A trip, a party, an event, a person, a list…') : null;
        if (!q) return;
        payload = { query: q };
      }
      try {
        let data = await post(ctx, `api/situations/${s.kind}/${s.id}/act`, { verb: 'subject', option_id: option.id, payload });
        if (data.status === 'choose' && (data.candidates || []).length && window.promptChoice) {
          const pick = await promptChoice('Which one?', '', data.candidates.map(c => ({ value: `${c.kind}:${c.id}`, label: `${c.title} (${c.kind})` })));
          if (!pick) return;
          const [kind, id] = pick.split(/:(.+)/);
          data = await post(ctx, `api/situations/${s.kind}/${s.id}/act`, { verb: 'subject', option_id: option.id, payload: { kind, id } });
        }
        if (data.message) alert_(data.message);
      } catch (e) { alert_(e.message); }
      if (ctx.onChange) ctx.onChange();
      return;
    }
```

`main.py`:

```python
@app.get("/api/subjects/{kind}/{sid}/situations")
def subject_situations(kind: str, sid: str, request: Request = None):
    from services import situations as _sit, subjects as _subj, missions as _m
    actor = _mind_actor(request, None)
    if (actor or {}).get('role') not in ('parent', 'adult'):
        raise HTTPException(status_code=403, detail="Parents and adults only")
    out = []
    for t in storage.get_threads():
        if (t.get('subject_kind'), t.get('subject_id')) == (kind, sid) and _sit.can_see('thread', t, actor):
            v = _sit.view('thread', t['id'], actor); out.append({'kind': 'thread', 'id': t['id'], 'title': t.get('title'), 'next_step': (v or {}).get('next_step')})
    for m in storage.get_missions(status=['running', 'browsing', 'waiting_user', 'waiting_retry']):
        if m.get('origin_kind') != 'thread' and (m.get('subject_kind'), m.get('subject_id')) == (kind, sid) and _sit.can_see('mission', m, actor):
            v = _sit.view('mission', m['id'], actor); out.append({'kind': 'mission', 'id': m['id'], 'title': m.get('goal'), 'next_step': (v or {}).get('next_step')})
    return out
```

Auth rule next to the missions rules: `(ANY, '/api/subjects/*', SIGNED_IN, 'schedule.logistics')` (pick the facet the threads routes use; read the neighbouring rules). `trip.html`: under `#trip-location` a `<div id="trip-argyle" class="text-xs text-indigo-300 mt-1" style="display:none"></div>` filled on load by `fetch(apiBase + 'api/subjects/trip/' + eventId + '/situations')` → each row "Argyle: <title> — <next step label>" linking to `/threads`; `occasions.html`: the same inside each card via an `x-init` fetch into `o._argyle`. Rebuild Tailwind.

- [ ] **Step 4: Run** `tests/test_subject_hand_path.py`, `tests/test_auth.py` and `tests/test_route_facets.py` (the route-classification tests), `tests/test_situation_endpoints.py` → PASS.
- [ ] **Step 5: Commit**: `feat(subjects): the hand path - About chip on every card, Link to something in Chauffeur with promptInput then promptChoice, Unlink, and the trip and occasion pages show what Argyle has going about them`.

---

### Task 8: The satellite rail

**Files:**
- Modify: `services/voice_tools.py` (`TOOLS`, `dispatch` branches), `services/agent_router.py` (spoken ABOUT only when `spoken_safe`)
- Test: `tests/test_subject_voice.py`

- [ ] **Step 1: Write the failing tests** (build a `VoiceContext` the way `tests/test_voice_identity.py` does; read its fixture first):
- `scenario_dispatch_finds_only_what_may_be_spoken`: `voice_tools.dispatch('find_in_chauffeur', {'query': 'Hawaii'}, ctx_verified_mom)` → `ev_hawaii`; `{'query': 'Disney World'}` → `candidates == []` (parents-default trip is not spoken_safe); household voice (`ctx` with no verified member) → Hawaii still found (household), Disney not.
- `scenario_dispatch_start_mission_for_forwards_the_subject`: `dispatch('start_mission_for', {'goal': 'book the condo', 'subject_kind': 'trip', 'subject_id': 'ev_hawaii'}, ctx_verified_mom, focus_key='voice:1')` → the thread has the subject; the same with `ev_disney` → the subject is dropped (not spoken_safe) and the mission starts subject-less.
- `scenario_spoken_prompt_carries_about_only_when_safe`: `agent_router.process_agent_request(..., source='voice', voice_context=ctx, focus_key='voice:1')` with the focus thread bound to Hawaii → captured prompt has ABOUT; bound to Disney → no ABOUT (and no title).

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**: `TOOLS |= {'find_in_chauffeur'}`; in `dispatch`, before the `start_mission_for` branch: `if name == 'find_in_chauffeur': return tools.find_in_chauffeur(args.get('query') or '', args.get('kind') or '', args.get('facet') or '', acting_member=ctx.verified_member(), spoken=True)`; the `start_mission_for` branch forwards `subject_kind=args.get('subject_kind'), subject_id=args.get('subject_id')` (and `start_mission_for` drops a pair that is not `spoken_safe` when `voice_context` is set). Router: for `source == 'voice'` a separate small block: focus via `_tri.get_focus(focus_key)`; if the thread has a subject and `subjects.spoken_safe(kind, row)` → append the ABOUT block built with `viewer = voice_context.verified_member()`, `spoken=True`.

- [ ] **Step 4: Run** `tests/test_subject_voice.py`, `tests/test_voice_identity.py`, `tests/test_voice_tools*.py` → PASS.
- [ ] **Step 5: Commit**: `feat(subjects): the satellite rail - find_in_chauffeur spoken-safe, start_mission_for forwards a spoken-safe subject, spoken ABOUT only when the record may be said aloud`.

---

### Task 9: Documentation and memory

**Files:**
- Modify: `chauffeur/system_capabilities.md` (one entry at the top replacing the "Spec only" line), `C:\Users\ffejn\.claude\projects\e--repositories-Chauffeur\memory\mission-subject-model.md` (status → BUILT, device steps), `MEMORY.md` line, the spec's Status line.

- [ ] **Step 1**: Write the capabilities entry (what shipped, every module and test named, "NOT device-verified", the device steps: rebuild; say "book dining for the Disney trip" to Argyle; open the thread card and see About; tap Link to something in Chauffeur on a plain thread; open the trip page and see the Argyle line; on the satellite "Hey Argyle, what is on the Hawaii trip").
- [ ] **Step 2**: Update the memory file and the MEMORY.md line; set the spec status to BUILT with the version range.
- [ ] **Step 3: Commit**: `docs(subjects): capabilities entry, memory, spec status (vX)`.
