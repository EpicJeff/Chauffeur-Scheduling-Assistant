# Project Access Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A thread, mission or program whose home project is private or parents is seen only by that project's audience, its own person, and a child owner's parents. This holds on every surface, and every reader is classified and tested.

**Architecture:** One module, `services/access.py`, decides `record_view(kind, row, viewer)` as `'full'`, `'keeper'` or `None`, using an acyclic composition: primitive base, then subject traversal, then project layer.
- Readers with no person use the named viewer `HOUSE`, never `None`.
- A `READERS` table, shaped like `auth.RULES`, classifies every route, Argyle tool and reader function, and a register test enforces it.
- A matrix test runs every classified reader as every fixture viewer and compares the projection it returns with the spec's §7 table.
- Surface classes are converted one task at a time. A `PENDING` set in the matrix shrinks to empty as each task lands.

**Tech Stack:** Python 3.14, FastAPI (`chauffeur/main.py`), the TinyDB-shaped storage over SQLite (`services/storage.py`), plain-script tests run from `chauffeur/` (`python tests/test_x.py`), and Starlette `TestClient`.

**Spec:** `docs/superpowers/specs/2026-10-16-project-access-rule-design.md` (revision 2, approved by the user 2026-10-16). Read it before any task. §3 is the rule, §4 the surface classes, §7 the expected cells, and §10 the capability removals the user approved.

## Global Constraints

- **Running tests:** from `chauffeur/` as plain scripts, with `HA_BASE_URL` unset (`unset HA_BASE_URL` in Bash). Run the task's own tests plus the neighbours it names. Never the whole suite.
- **Fixture data only.** Every test isolates storage through `tests/harness.py` (it sets `CHAUFFEUR_DATA_DIR` to a temp dir) or imports a test module that does. A live test that needs auth enforcement must **not** import `harness.py`. Use the `project_sheets_fixture` pattern instead.
- **Hidden means:**
  - a 404 shaped like a missing record (never 403);
  - the row dropped from a list or a search;
  - Argyle answering as if nothing matched;
  - "Busy" on calendar surfaces;
  - no finding and no DM.
- **Never pass `None` as a viewer** to `access`. Readers with no person pass `access.HOUSE`, or `access.HOUSE_PARENT` where the parents-only mission transcript variant applies.
- **One rule.** Every visibility decision for thread, mission and program goes through `access`. No new ad-hoc copies; the backed-out rounds' helpers (`subjects.record_visible`, `agent_tools_v2._piece_tool_visible`, `subjects.containing_project`) do not come back.
- **No browser dialogs** (`alert`, `confirm`, `prompt`). Use `showGlobalAlert`, `promptConfirm` and `promptInput` from `templates/components/control_center.html`.
- **Tailwind is precompiled.** After any template class change, run `python tools/build_tailwind.py` (from the repo root).
- **Every HA touchpoint degrades gracefully** with no Home Assistant present.
- **Never remove anything a person can do** beyond the three removals the user approved in spec §10.
- **Codex tasks** (2–10) leave changes in the working tree and do **not** bump `chauffeur/config.yaml` or commit (AGENTS.md). After review, Claude runs the gate, bumps the patch version (v2.499.N), and commits with the version in the subject and the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **PowerShell:** no double quotes in commit messages. Prefer the Bash tool for git.

## Review Focus

These five inputs are implied by the spec but are the most likely to bite a person, and no single task's happy path exercises them. Each has its test in the owning task.
1. **A project's audience changes while things are open** (household → private, or private → household). A wall, a cached schedule, an open record sheet or a posted approve card must follow the new audience on the next read, with no restart. Pinned in Task 8 (cache narrowing) and Task 4 (stale card refuses).
2. **A member is disabled or archived while they are a keeper or a project owner.** Their records must not become visible to everyone (an empty keeper must never match an empty viewer id). The member must see nothing. Pinned in Task 1 (`scenario_inactive_keeper_and_viewer`).
3. **Two children of the same parents.** Kate's private project's pieces must not become visible to her sibling because "parents of a child keeper" is read as "any child". Pinned in Task 1 (`scenario_sibling_is_not_a_parent`).
4. **A thread subject chain that loops** (thread A about B, B about A). It must not recurse forever, and neither thread may leak. Pinned in Task 1 (`scenario_subject_cycle`).
5. **A record whose `project_id` names a deleted project.** It falls back to no home project (today's visibility), never to an exception that an entry point swallows into an empty page. Pinned in Task 1 (`scenario_missing_home_project`).

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `chauffeur/services/access.py` (new) | The rule: kinds, primitive bases, HOUSE, `record_view` / `record_visible` / `record_actable`, `project_visible`, `channel_view`, `conversation_view`, `mission_view`, `shared_screen_visible`, `schedule_view`, `finding_visible`, the `batch()` cache | 1 (core), 4, 5, 8, 9 (one function each) |
| `chauffeur/services/access_readers.py` (new) | The `READERS` table and `resolve_route` / `resolve_tool` | 1, then every task adds rows |
| `chauffeur/tests/access_fixture.py` (new) | The fixture household R1–R13, viewers and secret markers | 1 |
| `chauffeur/tests/test_access_core.py` (new) | Function-level cells of the rule (§3, §7 table) | 1 |
| `chauffeur/tests/test_access_matrix.py` (new) | Runs every classified reader as every viewer; `EXPECT`, `PROBES`, `PENDING` | 1 (frame), every task adds probes |
| `chauffeur/tests/test_access_register.py` (new) | The route, tool and function-reader classification guard | 1 |
| `chauffeur/tests/test_access_live.py` (new) | Browser proof: private piece through both deep-link forms on both sheet hosts | 11 |
| `services/situations.py`, `subjects.py`, `planned.py`, `projects.py`, `missions.py` | Become thin calls into `access` | 1, 5 |
| `main.py` routes | Class 4.1 and the surface routes | 3, 4, 6, 7, 8, 9 |
| `services/agent_tools_v2.py`, `agent_router.py`, `triage.py` | Classes 4.3/4.4 Argyle | 4 |
| `templates/components/control_center.html`, `templates/app.html`, conversation routes | §4.2 conversations by surface | 3 |
| `services/voice_approval.py`, `voice_tools.py` | §4.5 | 6 |
| `services/house_programs.py`, `house_attention.py`, `study.py`, `home_board.py`, `programs.py` (celebrations) | §4.6 | 7 |
| `main.py` (`_practice_events`, `/api/schedule`, `/api/practice-windows`, `/api/commitments`, `/api/packing/day`), `programs.py`, `family_day.py`, `family_digest.py`, `migrations.py` | §4.7 | 8 |
| `services/watchers.py`, `findings.py`, `replies.py`, `mind.py` | §4.8 | 9 |
| `services/projects.py` (`_change_piece`), `templates/components/projects_page.html`, `agent_tools_v2.add_to_project`, `migrations.py` | §10.1 removal | 2 |

---

### Task 1: The rule, the fixture, the matrix frame and the register (Claude)

**Files:**
- Create: `chauffeur/services/access.py`, `chauffeur/services/access_readers.py`, `chauffeur/tests/access_fixture.py`, `chauffeur/tests/test_access_core.py`, `chauffeur/tests/test_access_matrix.py`, `chauffeur/tests/test_access_register.py`
- Modify:
  - `chauffeur/services/situations.py`: `can_see` near :532, `_subject_visible` near :515, the keeper test in `view` near :587, `channel_visible` near :557;
  - `chauffeur/services/subjects.py`: `_thread_visible` :127, `_program_visible` :120;
  - `chauffeur/services/planned.py`: `is_keeper` :157;
  - `chauffeur/services/projects.py`: `_wrapped_visible` :36.

**Interfaces:**
- Produces (every later task uses these exact names):
  - `access.HOUSE`, `access.HOUSE_PARENT`, `access.FULL == 'full'`, `access.KEEPER == 'keeper'`
  - `access.is_house(viewer) -> bool`
  - `access.home_project(row) -> dict | None`, `access.restricted(project) -> bool`
  - `access.keeper_id(kind, row) -> str | None`
  - `access.project_visible(project, viewer) -> bool`
  - `access.record_view(kind, row, viewer, *, skip_project=False) -> 'full' | 'keeper' | None`
  - `access.record_visible(kind, row, viewer) -> bool`
  - `access.record_actable(kind, row, viewer, verb) -> bool`
  - `access.channel_view(kind, row, focus_key) -> 'full' | 'keeper' | None | access.NOT_A_CHANNEL`
  - `access.conversation_view(kind, row, viewer, focus_key) -> 'full' | 'keeper' | None`
  - `access.shared_screen_visible(kind, row, viewer) -> bool`
  - `access.batch()`: a context manager for list endpoints that memoises project and member lookups
  - `access_readers.READERS: list[tuple]`, `access_readers.resolve_route(method, path) -> tuple | None`, `access_readers.resolve_tool(name) -> tuple | None`, `access_readers.CLASSES`
  - In tests: `access_fixture.build() -> Fx`, with `Fx.ids['R1']…`, `Fx.viewers['mom'|'dad'|'aunt'|'kid'|'hal'|'pat'|'house']`, `Fx.secret(rkey) -> str` (the words only a FULL view contains) and `Fx.title(rkey) -> str`

- [ ] **Step 1: Write the fixture**

Create `chauffeur/tests/access_fixture.py`:

```python
"""One fixture household for every access test (project access rule spec §6).

Import from chauffeur/tests. Builds fresh storage each call; never real data.
"""
from dataclasses import dataclass, field

from test_front_door_chat import _fresh as _fresh_projects
from test_subjects import MOM, DAD, AUNT, KID
from services import storage, projects, threads

HAL = {'id': 'hal', 'name': 'Hal', 'role': 'helper'}
PAT = {'id': 'pat', 'name': 'Pat', 'role': 'parent', 'status': 'disabled'}
SIB = {'id': 'sib', 'name': 'Sam', 'role': 'child', 'is_child': True}


@dataclass
class Fx:
    ids: dict = field(default_factory=dict)
    projects: dict = field(default_factory=dict)
    viewers: dict = field(default_factory=dict)

    def secret(self, rkey):
        return f'SECRET-{rkey}-WORDS'

    def title(self, rkey):
        return f'Title {rkey}'


def _project(audience, owner, title):
    return projects.create({'title': title, 'goal': 'g', 'done_when': 'd',
                            'owner_member_id': owner, 'audience': audience}, dict(MOM))['project']


def _thread(fx, rkey, owner, project, **extra):
    tid = threads.create(title=fx.title(rkey), owner_member_id=owner, created_by=owner or 'mom',
                         project_id=project['id'] if project else None,
                         next_action=fx.secret(rkey), next_action_at='2020-01-01')
    if extra:
        storage.update_thread(tid, extra)
    storage.update_thread(tid, {'status_note': fx.secret(rkey), 'note_source': 'model'})
    fx.ids[rkey] = tid
    return tid


def _mission(fx, rkey, creator, project, **extra):
    mid = storage.add_mission({'goal': fx.title(rkey), 'created_by': creator, 'status': 'waiting_user',
                              'summary': fx.secret(rkey), 'status_note': fx.secret(rkey), **extra})
    storage.add_mission_step(mid, {'kind': 'ask', 'result_json': {'question': fx.secret(rkey) + '?'}})
    projects.adopt('mission', mid, None, project_id=project['id'] if project else None)
    fx.ids[rkey] = mid
    return mid


def _program(fx, rkey, member, project, **extra):
    pid = storage.add_program({'title': fx.title(rkey), 'member_id': member, 'state': 'active',
                               'why': fx.secret(rkey), **extra})
    projects.adopt('program', pid, None, project_id=project['id'] if project else None)
    fx.ids[rkey] = pid
    return pid


def build():
    """R1–R13 of spec §6. Returns Fx; storage is fresh."""
    _fresh_projects()
    for m in (HAL, PAT, SIB):
        storage.add_member(dict(m))
    fx = Fx()
    mom_private = _project('private', 'mom', 'Mom private')
    mom_parents = _project('parents', 'mom', 'Mom parents')
    household = _project('household', 'dad', 'Household')
    kate_private = _project('private', 'kid', 'Kate private')
    fx.projects.update(mom_private=mom_private, mom_parents=mom_parents, household=household,
                       kate_private=kate_private)

    _thread(fx, 'R1', 'aunt', mom_private)
    _mission(fx, 'R2', 'aunt', mom_private)
    _program(fx, 'R3', 'kid', mom_private)
    _thread(fx, 'R4', 'mom', mom_parents)
    _thread(fx, 'R5t', 'dad', household)
    _program(fx, 'R5p', 'kid', household)

    storage.save_occasion({'id': 'occ-kate-mom', 'title': 'Dad surprise', 'audience': 'private',
                           'shared_with': ['mom', 'kid']})
    _thread(fx, 'R6', 'kid', None, subject_kind='occasion', subject_id='occ-kate-mom')
    _thread(fx, 'R7', 'kid', mom_private, subject_kind='occasion', subject_id='occ-kate-mom')
    storage.save_occasion({'id': 'occ-parents', 'title': 'Parents only', 'audience': 'parents'})
    _thread(fx, 'R8', '', None, subject_kind='occasion', subject_id='occ-parents')

    origin = _thread(fx, 'R9origin', 'mom', mom_private)
    _mission(fx, 'R9a', 'mom', mom_private, origin_kind='thread', origin_ref=origin)
    _mission(fx, 'R9b', 'mom', household)

    _thread(fx, 'R10', 'dad', household, subject_kind='thread', subject_id=fx.ids['R1'])
    _mission(fx, 'R11', 'mom', kate_private, subject_kind='project', subject_id=kate_private['id'])

    with storage.db_lock:
        storage.trip_metadata_table.insert({'id': 'tp', 'event_id': 'ev_parents_trip', 'title': 'Parents trip',
                                            'audience': 'parents', 'pois': [], 'accommodations': [],
                                            'flights': []})
    storage.set_cached_trips([{'id': 'ev_parents_trip', 'title': 'Parents trip', 'start': '2027-01-01',
                               'end': '2027-01-03', 'location': 'X'}])
    _thread(fx, 'R12', 'mom', household,
            subject_history=[{'kind': 'trip', 'id': 'ev_parents_trip'}])
    _thread(fx, 'R13', 'dad', None)   # threads.create wraps it (slice 1 invariant)

    fx.viewers = {'mom': dict(MOM), 'dad': dict(DAD), 'aunt': dict(AUNT), 'kid': dict(KID),
                  'hal': dict(HAL), 'pat': dict(PAT), 'sib': dict(SIB)}
    from services import access
    fx.viewers['house'] = access.HOUSE
    return fx
```

- [ ] **Step 2: Write the core cells test (red)**

Create `chauffeur/tests/test_access_core.py`:

```python
"""Function-level cells of the project access rule (spec §3, §7 table).

Run from chauffeur/: python tests/test_access_core.py
"""
import traceback

from harness import check
import access_fixture
from services import access, storage, threads

F, K, X = 'full', 'keeper', None
# Spec §7, the person's-own-surface table. Columns: mom dad aunt kid hal pat house.
TABLE = {
    'R1':  (F, X, K, X, X, X, X),
    'R2':  (F, X, K, X, X, X, X),
    'R3':  (F, F, X, K, X, X, X),
    'R4':  (F, F, X, X, X, X, X),
    'R5t': (F, F, F, X, X, X, F),
    'R5p': (F, F, F, F, X, X, F),
    'R6':  (F, X, X, F, X, X, X),
    'R7':  (F, X, X, K, X, X, X),
    'R8':  (F, F, X, X, X, X, X),
    'R10': (F, K, X, X, X, X, X),
    'R11': (F, F, X, X, X, X, X),
    'R12': (F, F, X, X, X, X, X),
}
COLS = ('mom', 'dad', 'aunt', 'kid', 'hal', 'pat', 'house')
KIND = {'R1': 'thread', 'R2': 'mission', 'R3': 'program', 'R4': 'thread', 'R5t': 'thread',
        'R5p': 'program', 'R6': 'thread', 'R7': 'thread', 'R8': 'thread', 'R10': 'thread',
        'R11': 'mission', 'R12': 'thread', 'R13': 'thread', 'R9origin': 'thread',
        'R9a': 'mission', 'R9b': 'mission'}


def load(fx, rkey):
    kind = KIND[rkey]
    rid = fx.ids[rkey]
    return kind, {'thread': storage.get_thread, 'mission': storage.get_mission,
                  'program': storage.get_program}[kind](rid)


def scenario_the_table():
    fx = access_fixture.build()
    bad = []
    for rkey, row in TABLE.items():
        kind, rec = load(fx, rkey)
        for col, want in zip(COLS, row):
            got = access.record_view(kind, rec, fx.viewers[col])
            if got != want:
                bad.append(f'{rkey} {col}: want {want} got {got}')
    check(not bad, '\n'.join(bad))


def scenario_legacy_wrapped_record_is_as_today():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R13')
    for col in ('mom', 'dad', 'aunt', 'house'):
        check(access.record_view(kind, rec, fx.viewers[col]) == 'full', f'R13 {col}')
    check(access.record_view(kind, rec, fx.viewers['kid']) is None, 'R13 kid base')
    check(access.record_view(kind, rec, fx.viewers['pat']) is None, 'R13 pat inactive')


def scenario_house_parent_reads_parents_subjects_not_projects():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R8')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) == 'full', 'parents-only subject is HOUSE_PARENT')
    kind, rec = load(fx, 'R4')
    check(access.record_view(kind, rec, access.HOUSE_PARENT) is None, 'a parents PROJECT never opens to HOUSE')


def scenario_inactive_keeper_and_viewer():
    fx = access_fixture.build()
    storage.update_member('aunt', {'status': 'disabled'})
    kind, rec = load(fx, 'R1')
    check(access.record_view(kind, rec, dict(fx.viewers['aunt'], status='disabled')) is None, 'disabled keeper sees nothing')
    check(access.record_view(kind, rec, fx.viewers['dad']) is None, 'disabled keeper does not open the record')
    tid = threads.create(title='Unowned', owner_member_id='', created_by='mom',
                         project_id=fx.projects['mom_private']['id'])
    row = storage.get_thread(tid)
    check(access.record_view('thread', row, access.HOUSE) is None, 'empty owner never matches HOUSE (M1)')
    check(access.keeper_id('thread', row) is None, 'empty keeper id')


def scenario_sibling_is_not_a_parent():
    fx = access_fixture.build()
    kind, rec = load(fx, 'R3')
    check(access.record_view(kind, rec, fx.viewers['sib']) is None, 'a sibling is not a parent of the child keeper')


def scenario_subject_cycle():
    fx = access_fixture.build()
    a = threads.create(title='A', owner_member_id='mom', created_by='mom')
    b = threads.create(title='B', owner_member_id='mom', created_by='mom',
                       project_id=fx.projects['mom_private']['id'])
    storage.update_thread(a, {'subject_kind': 'thread', 'subject_id': b})
    storage.update_thread(b, {'subject_kind': 'thread', 'subject_id': a})
    check(access.record_view('thread', storage.get_thread(a), fx.viewers['dad']) is None, 'cycle hides A from Dad')
    check(access.record_view('thread', storage.get_thread(b), fx.viewers['dad']) is None, 'cycle hides B from Dad')


def scenario_missing_home_project():
    fx = access_fixture.build()
    tid = threads.create(title='Orphan', owner_member_id='dad', created_by='dad')
    storage.update_thread(tid, {'project_id': 'prj-gone'})
    check(access.record_view('thread', storage.get_thread(tid), fx.viewers['aunt']) == 'full',
          'a deleted home project falls back to today')


def scenario_actable():
    fx = access_fixture.build()
    _, r2 = load(fx, 'R2')
    aunt, dad = fx.viewers['aunt'], fx.viewers['dad']
    check(not access.record_actable('mission', r2, dad, 'answer'), 'Dad cannot act on R2')
    for verb in ('ack', 'delete', 'steer'):
        check(access.record_actable('mission', r2, aunt, verb), f'keeper may {verb}')
    for verb in ('approve_plan', 'run_stage', 'answer', 'release', 'submit', 'verify'):
        check(not access.record_actable('mission', r2, aunt, verb), f'keeper may not {verb}')
    _, r3 = load(fx, 'R3')
    check(access.record_actable('program', r3, fx.viewers['kid'], 'session'), 'child keeper acts on her program')


def scenario_situations_view_uses_the_rule():
    fx = access_fixture.build()
    from services import situations, planned
    v = situations.view('thread', fx.ids['R1'], fx.viewers['aunt'])
    check(v and fx.secret('R1') not in str(v), f'thread keeper redaction: {v}')
    check(situations.view('thread', fx.ids['R1'], fx.viewers['dad']) is None, 'Dad gets nothing')
    m = storage.get_mission(fx.ids['R2'])
    check(planned.is_keeper(m, fx.viewers['aunt']), 'planned.is_keeper follows access')
    v = situations.view('mission', fx.ids['R2'], fx.viewers['aunt'])
    check(v and fx.secret('R2') not in str(v), f'mission keeper projection: {v}')


def scenario_wrapper_project_follows_its_record():
    fx = access_fixture.build()
    from services import projects
    wrapper = projects.project_for('thread', fx.ids['R13'])
    check(access.project_visible(wrapper, access.HOUSE), 'HOUSE sees a wrapper of a household-visible record')
    check(access.project_visible(fx.projects['household'], access.HOUSE), 'HOUSE sees a household project')
    check(not access.project_visible(fx.projects['mom_private'], access.HOUSE), 'HOUSE never sees a private project')


def scenario_batch_memoises_projects():
    fx = access_fixture.build()
    calls = {'n': 0}
    real = storage.get_project
    def counting(pid):
        calls['n'] += 1
        return real(pid)
    storage.get_project = counting
    try:
        _, r1 = load(fx, 'R1')
        with access.batch():
            for _ in range(5):
                access.record_view('thread', r1, fx.viewers['mom'])
        check(calls['n'] <= 2, f'one project lookup per batch, got {calls["n"]}')
    finally:
        storage.get_project = real


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
```

- [ ] **Step 3: Run it to watch it fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_core.py`
Expected: every scenario FAILs with `ModuleNotFoundError: No module named 'services.access'` (or an ImportError in the fixture).

- [ ] **Step 4: Write `services/access.py`**

```python
"""Who may see a thread, mission or program, on every surface.

The project access rule (docs/superpowers/specs/2026-10-16-project-access-rule-design.md).
record_view = primitive base, then subject traversal, then the project layer.
The call graph is acyclic: primitive bases never call back into this module.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable, Optional

from services import storage

HOUSE = {'id': None, 'role': 'adult', 'house': True}
HOUSE_PARENT = {'id': None, 'role': 'parent', 'house': True}
FULL, KEEPER = 'full', 'keeper'
WRITE_ROLES = ('parent', 'adult')
SCOPED_ROLES = ('child', 'helper', 'guest')
NOT_A_CHANNEL = object()

_cache = ContextVar('access_cache', default=None)


@contextmanager
def batch():
    """Memoise project and member lookups for one read-only list call.

    Explicit, not request-wide: a write route that changes a project and then
    reads it back must never see the old row."""
    token = _cache.set({})
    try:
        yield
    finally:
        _cache.reset(token)


def _memo(key, load):
    cache = _cache.get()
    if cache is None:
        return load()
    if key not in cache:
        cache[key] = load()
    return cache[key]


def _get_project(pid):
    return _memo(('project', pid), lambda: storage.get_project(pid)) if pid else None


def _get_member(mid):
    return _memo(('member', mid), lambda: storage.get_member(mid)) if mid else None


def is_house(viewer):
    return bool(viewer) and bool(viewer.get('house'))


def _active(member):
    from services import projects
    return projects._active(member)


def _person(viewer):
    """The viewer as an active member, or None (HOUSE is not a person)."""
    if not viewer or is_house(viewer) or not _active(viewer):
        return None
    return viewer


@dataclass(frozen=True)
class Kind:
    keeper_field: str
    base: Callable[[dict, dict], bool]
    load: Callable[[str], Optional[dict]]
    keeper_verbs: Optional[frozenset]   # None: a keeper may do everything (programs)


KINDS: dict = {}


def register(kind, keeper_field, base, load, keeper_verbs=None):
    KINDS[kind] = Kind(keeper_field, base, load, keeper_verbs)


def keeper_id(kind, row):
    spec = KINDS.get(kind)
    kid = (row or {}).get(spec.keeper_field) if spec else None
    if not kid:
        return None
    return kid if _active(_get_member(kid)) else None


def _is_keeper(kind, row, viewer):
    person = _person(viewer)
    kid = keeper_id(kind, row)
    return bool(person and kid and person['id'] == kid)


def _parent_of_child_keeper(kind, row, viewer):
    from services import projects
    person = _person(viewer)
    if not person or not projects._parent(person):
        return False
    keeper = _get_member(keeper_id(kind, row))
    return bool(keeper and projects._child(keeper))


def _thread_base(row, viewer):
    return viewer.get('role') in WRITE_ROLES or _is_keeper('thread', row, viewer)


def _mission_base(row, viewer):
    return viewer.get('role') in WRITE_ROLES


def _program_base(row, viewer):
    return viewer.get('role') not in SCOPED_ROLES or _is_keeper('program', row, viewer)


def home_project(row):
    return _get_project((row or {}).get('project_id'))


def restricted(project):
    return bool(project) and not project.get('wrapped_from') and project.get('audience') in ('private', 'parents')


def project_visible(project, viewer):
    """projects.can_see, with a meaning for HOUSE and HOUSE_PARENT (spec §2)."""
    from services import projects
    if not project or not viewer:
        return False
    if is_house(viewer):
        if project.get('wrapped_from'):
            return projects._wrapped_visible(project, viewer)
        return project.get('audience') == 'household'
    return projects.can_see(project, viewer)


def _subjects_full(kind, row, viewer, home, visited):
    from services import subjects
    for skind, record in subjects.subject_records(kind, row):
        if skind == 'project' and home and record.get('id') == home.get('id'):
            continue        # checked once, by the project layer (spec §3)
        if skind in KINDS:
            key = (skind, record.get('id'))
            if key in visited or record_view(skind, record, viewer, _visited=visited) != FULL:
                return False
        elif skind in ('project', 'proposed_project'):
            if not project_visible(record, viewer):
                return False
        elif not subjects.visible(skind, record, viewer):
            return False
    return True


def record_view(kind, row, viewer, *, skip_project=False, _visited=None):
    """'full', 'keeper' or None for one viewer (spec §3)."""
    spec = KINDS.get(kind)
    if spec is None or not row or not viewer:
        return None
    if not is_house(viewer) and _person(viewer) is None:
        return None
    if not spec.base(row, viewer):
        return None
    visited = set(_visited or ()) | {(kind, row.get('id'))}
    home = home_project(row)
    subjects_ok = _subjects_full(kind, row, viewer, home, visited)
    layer_ok = (skip_project or not restricted(home)
                or _parent_of_child_keeper(kind, row, viewer)
                or project_visible(home, viewer))
    if subjects_ok and layer_ok:
        return FULL
    return KEEPER if _is_keeper(kind, row, viewer) else None


def record_visible(kind, row, viewer):
    return record_view(kind, row, viewer) is not None


def record_actable(kind, row, viewer, verb):
    view = record_view(kind, row, viewer)
    if view is None:
        return False
    if view == KEEPER:
        allowed = KINDS[kind].keeper_verbs
        return allowed is None or verb in allowed
    return True


def shared_screen_visible(kind, row, viewer):
    """HOUSE, plus what a signed-in person may see (spec §4.6)."""
    if record_visible(kind, row, HOUSE):
        return True
    return bool(_person(viewer)) and record_visible(kind, row, viewer)


register('thread', 'owner_member_id', _thread_base, lambda rid: storage.get_thread(rid),
         keeper_verbs=None)   # a thread keeper keeps every thread verb; view() drops mission options
register('mission', 'created_by', _mission_base, lambda rid: storage.get_mission(rid),
         keeper_verbs=frozenset({'ack', 'delete', 'steer'}))
register('program', 'member_id', _program_base, lambda rid: storage.get_program(rid),
         keeper_verbs=None)
```

Ruling written into the plan: the thread keeper keeps every thread verb (they carry the thread). The mission keeper keeps only OK (ack), Delete and steer. This matches today's `situations.view` filter, which drops `approve_plan`, `run_stage` and mission options other than steer.

- [ ] **Step 5: Route the existing helpers through `access`**

In `services/situations.py`, replace the body of `can_see` (near :532) with:

```python
def can_see(kind: str, row: dict, viewer: Optional[dict]) -> bool:
    if kind in ('thread', 'mission'):
        from services import access
        return access.record_view(kind, row, viewer) is not None
    return _can_see_base(kind, row, viewer)
```

In `_subject_visible` (near :515), replace the `if kind == 'thread':` branch with:

```python
    if kind == 'thread':
        from services import access
        return access.record_view('thread', record, viewer) == access.FULL
```

In `view` (near :577–:590), replace both keeper computations with one call:

```python
    keeper = False
    if kind in ('mission', 'thread'):
        from services import access
        keeper = access.record_view(kind, row, viewer) == access.KEEPER
    if keeper and kind == 'mission':
        from services import planned
        row = {**planned.keeper_view(row, viewer), 'plan': None,
               'status_note': '', 'note_source': 'fallback'}
    elif keeper and kind == 'thread':
        row = {**row, 'status_note': '', 'note_source': 'fallback', 'next_steps': [],
               'next_action': '',
               'history': [{'kind': 'mission', 'ts': h.get('ts')} if h.get('kind') == 'mission' else h
                           for h in row.get('history') or []]}
```

Clearing `next_action` for a thread keeper is new. The fixture's secret sits in `next_action`, and a keeper who cannot see the project must not read the project's planned next step on their thread.

In `services/subjects.py`:

```python
def _program_visible(row, viewer):
    from services import access
    return access.record_visible('program', row, viewer)


def _thread_visible(row, viewer):
    from services import access
    return access.record_visible('thread', row, viewer)
```

Existing callers pass `viewer=None` for "the household" (`_REGISTRY_READER` aside). `record_visible(..., None)` returns False. Tasks 4–9 replace those `None`s with `access.HOUSE`, and the matrix shows any that are left.

In `services/planned.py`:

```python
def is_keeper(mission, viewer) -> bool:
    """Ownership keeps the mission row, never what is hidden around it."""
    from services import access
    return access.record_view('mission', mission, viewer) == access.KEEPER
```

In `services/projects.py` `_wrapped_visible`, replace the two kind branches inside `try:` with:

```python
        from services import access
        return access.record_visible(kind, row, viewer)
```

- [ ] **Step 6: Run the core cells**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_core.py`
Expected: every scenario PASSes. If a §7 cell disagrees, re-read spec §3 before changing code; the table is the contract. If the table is wrong, stop and report.

- [ ] **Step 7: Write the register**

Create `chauffeur/services/access_readers.py`.
- One row per reader: `(id, cls, kinds, check)`.
- `id` is one of `('route', METHOD, template)`, `('route-prefix', METHOD_OR_*, prefix)`, `('tool', name)` or `('reader', 'module.function')`.
- `cls` is one of `CLASSES`.
- The rows come from spec Appendix A. Every route and tool must resolve; prefix rows classify whole unrelated families as `NONE`.

```python
"""Every reader of thread, mission and program words, classified (spec §5).

Shaped like auth.RULES. A route or Argyle tool with no row fails
tests/test_access_register.py, the way an unclassified route fails test_auth.
"""
CLASSES = ('4.1-signed-in', '4.2-conversation', '4.3-channel', '4.4-engine', '4.5-voice',
           '4.6-shared-screen', '4.7-calendar', '4.8-signals', 'INTERNAL', 'NONE')

R, P, T, F = 'route', 'route-prefix', 'tool', 'reader'

READERS = [
    # §4.1 threads
    ((R, 'GET', '/api/threads'), '4.1-signed-in', ('thread',), 'record_view'),
    ((R, 'POST', '/api/threads'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'GET', '/api/threads/{thread_id}/missions'), '4.1-signed-in', ('thread', 'mission'), 'record_view'),
    ((R, 'PATCH', '/api/threads/{thread_id}'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/note'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/advance'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'DELETE', '/api/threads/{thread_id}'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/close'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/draft'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/photo'), '4.1-signed-in', ('thread', 'mission'), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/send'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'POST', '/api/threads/{thread_id}/research'), '4.1-signed-in', ('thread',), 'record_actable'),
    # §4.1 missions
    ((R, 'GET', '/api/missions/admin'), '4.1-signed-in', ('mission',), 'record_view'),
    ((R, 'GET', '/api/missions/{mission_id}'), '4.1-signed-in', ('mission',), 'record_view'),
    ((R, 'POST', '/api/missions/launch'), '4.1-signed-in', ('mission', 'thread'), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/proposals/{proposal_id}/act'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'GET', '/api/missions/{mission_id}/shots/{name}'), '4.1-signed-in', ('mission',), 'record_view'),
    ((R, 'POST', '/api/missions/{mission_id}/release'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/submit'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/verify'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/plan/answers'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/answer'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'DELETE', '/api/missions/{mission_id}'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/drop'), '4.1-signed-in', ('mission',), 'record_actable'),
    ((R, 'POST', '/api/missions/{mission_id}/ack'), '4.1-signed-in', ('mission',), 'record_actable'),
    # §4.1 programs
    ((R, 'GET', '/api/programs'), '4.1-signed-in', ('program',), 'record_view'),
    ((R, 'POST', '/api/programs'), '4.1-signed-in', ('program',), 'record_actable'),
    ((P, 'POST', '/api/programs/{program_id}/'), '4.1-signed-in', ('program',), 'record_actable'),
    ((R, 'GET', '/api/programs/{program_id}/lesson'), '4.1-signed-in', ('program',), 'record_view'),
    ((R, 'PUT', '/api/programs/{program_id}/lesson'), '4.1-signed-in', ('program',), 'record_actable'),
    ((R, 'DELETE', '/api/programs/{program_id}/lesson'), '4.1-signed-in', ('program',), 'record_actable'),
    ((R, 'POST', '/api/programs/lessons/sweep'), '4.1-signed-in', ('program',), 'record_view'),
    ((R, 'GET', '/api/programs/{program_id}/footprint'), '4.1-signed-in', ('program',), 'record_view'),
    ((R, 'GET', '/api/commitments'), '4.7-calendar', ('program',), 'record_view'),
    # §4.1 situations, asks, projects, findings, proposals, study
    ((R, 'GET', '/api/situations'), '4.1-signed-in', ('thread', 'mission'), 'record_view'),
    ((R, 'GET', '/api/situations/{kind}/{sid}'), '4.1-signed-in', ('thread', 'mission'), 'record_view'),
    ((R, 'GET', '/api/subjects/{kind}/{sid}/situations'), '4.1-signed-in', ('thread', 'mission'), 'record_view'),
    ((R, 'POST', '/api/situations/{kind}/{sid}/act'), '4.1-signed-in', ('thread', 'mission'), 'record_actable'),
    ((R, 'POST', '/api/asks'), '4.1-signed-in', ('thread', 'mission'), 'record_actable'),
    ((R, 'POST', '/api/asks/{ask_id}/answer'), '4.1-signed-in', ('thread',), 'record_actable'),
    ((R, 'GET', '/api/projects'), '4.1-signed-in', ('thread', 'mission', 'program'), 'record_view'),
    ((R, 'GET', '/api/projects/elsewhere'), '4.1-signed-in', ('mission',), 'record_view'),
    ((R, 'GET', '/api/projects/for/{kind}/{record_id}'), '4.1-signed-in', ('thread', 'mission', 'program'), 'record_view'),
    ((R, 'GET', '/api/projects/{project_id}/pieces'), '4.1-signed-in', ('thread', 'mission', 'program'), 'record_view'),
    ((R, 'GET', '/api/projects/{project_id}'), '4.1-signed-in', ('thread', 'mission', 'program'), 'record_view'),
    ((R, 'POST', '/api/projects/{project_id}/pieces'), '4.1-signed-in', (), 'record_actable'),
    ((R, 'POST', '/api/projects/{project_id}/pieces/remove'), '4.1-signed-in', (), 'record_actable'),
    ((R, 'GET', '/api/subjects/search'), '4.1-signed-in', ('thread', 'program'), 'record_view'),
    ((R, 'GET', '/api/subjects/{kind}/{sid}/projects'), '4.1-signed-in', (), 'project_visible'),
    ((R, 'GET', '/api/findings'), '4.8-signals', ('thread', 'mission', 'program'), 'finding_visible'),
    ((R, 'GET', '/api/action-proposals'), '4.1-signed-in', ('mission',), 'record_view'),
    ((R, 'POST', '/api/action-proposals/{proposal_id}/act'), '4.1-signed-in', ('mission', 'program'), 'record_actable'),
    ((R, 'GET', '/api/study/state'), '4.6-shared-screen', ('thread', 'program'), 'shared_screen_visible'),
    # §4.2 conversations
    ((R, 'POST', '/api/chat'), '4.2-conversation', ('thread', 'mission', 'program'), 'conversation_view'),
    ((R, 'GET', '/api/chat/history'), '4.2-conversation', (), 'conversation_owner'),
    ((R, 'DELETE', '/api/chat/history'), '4.2-conversation', (), 'conversation_owner'),
    ((R, 'GET', '/api/chat/conversations'), '4.2-conversation', (), 'conversation_owner'),
    ((P, '*', '/api/chat/conversations'), '4.2-conversation', (), 'conversation_owner'),
    # §4.5 voice
    ((R, 'POST', '/api/v2/converse'), '4.5-voice', ('thread', 'mission', 'program'), 'record_view(HOUSE)'),
    # §4.6 shared screens
    ((R, 'GET', '/api/house/state'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((R, 'GET', '/api/house/programs/{program_id}/session'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((R, 'GET', '/api/programs/{program_id}/lesson-scenes'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((R, 'POST', '/api/programs/{program_id}/lesson-help'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((R, 'GET', '/api/programs/celebrations'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    # §4.7 calendar
    ((R, 'GET', '/api/practice-windows'), '4.7-calendar', ('program',), 'schedule_view'),
    ((R, 'GET', '/api/schedule'), '4.7-calendar', ('program',), 'schedule_view'),
    ((R, 'GET', '/api/packing/day'), '4.7-calendar', ('program',), 'schedule_view'),
    ((R, 'GET', '/api/debug/event_subjects'), 'INTERNAL', ('program',), 'parents-debug'),
    # Argyle tools (§4.3; the engine reaches them through READ_TOOLS, §4.4)
    *[((T, name), '4.3-channel', kinds, 'conversation_view') for name, kinds in [
        ('list_situations', ('thread', 'mission')), ('next_situation', ('thread', 'mission')),
        ('explain_situation', ('thread', 'mission')), ('act_on_situation', ('thread', 'mission')),
        ('start_ask', ('thread', 'mission')), ('mark_ask_sent', ('thread', 'mission')),
        ('answer_ask', ('thread', 'mission')), ('start_mission_for', ('thread', 'mission')),
        ('start_project', ()), ('list_projects', ()), ('get_project', ('thread', 'mission', 'program')),
        ('add_project_step', ()), ('add_to_project', ()), ('set_project_state', ('mission',)),
        ('set_step_state', ('mission',)), ('find_in_chauffeur', ('thread', 'program')),
        ('list_open_findings', ('thread', 'mission', 'program')),
        ('list_threads', ('thread',)), ('create_thread', ('thread',)),
        ('update_thread_action', ('thread',)), ('add_thread_note', ('thread',)),
        ('draft_thread_message', ('thread',)), ('close_thread', ('thread',)),
        ('launch_mission', ('mission', 'thread')), ('list_programs', ('program',)),
        ('program_progress', ('program',)), ('log_program_session', ('program',)),
        ('propose_program', ('program',))]],
    # Function readers (§4.3–§4.8 and INTERNAL), grep-guarded by the register test
    ((F, 'services.agent_router.process_agent_request'), '4.3-channel', ('thread', 'mission', 'program'), 'conversation_view'),
    ((F, 'services.triage.next_for'), '4.3-channel', ('thread', 'mission'), 'conversation_view'),
    ((F, 'services.triage.get_focus'), '4.3-channel', ('thread', 'mission'), 'conversation_view'),
    ((F, 'services.triage.focus_live_asks'), '4.3-channel', ('thread', 'mission'), 'conversation_view'),
    ((F, 'services.missions._apply_planner_action'), '4.4-engine', ('thread', 'mission', 'program'), 'mission_view'),
    ((F, 'services.missions._match_thread'), '4.4-engine', ('thread',), 'mission_view'),
    ((F, 'services.missions._seed_thread_context'), '4.4-engine', ('thread',), 'mission_view'),
    ((F, 'services.missions.ask_card'), '4.4-engine', ('mission',), 'mission_view'),
    ((F, 'services.missions._land_finish'), '4.8-signals', ('mission', 'thread'), 'record_view'),
    ((F, 'services.missions._dm_person'), '4.8-signals', ('mission',), 'record_view'),
    ((F, 'services.voice_approval.prepare'), '4.5-voice', ('mission', 'thread'), 'record_view(HOUSE)'),
    ((F, 'services.voice_approval.valid'), '4.5-voice', ('mission', 'thread'), 'record_view(HOUSE)'),
    ((F, 'services.house_programs.objects'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((F, 'services.house_programs.session'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((F, 'services.house_attention._programs'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((F, 'services.study._board'), '4.6-shared-screen', ('thread',), 'shared_screen_visible'),
    ((F, 'services.study._binders'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((F, 'services.programs.celebrations'), '4.6-shared-screen', ('program',), 'shared_screen_visible'),
    ((F, 'services.programs.due_practice_pushes'), '4.7-calendar', ('program',), 'record_view'),
    ((F, 'services.family_day._raw_blocks'), '4.7-calendar', ('program',), 'schedule_view'),
    ((F, 'services.family_digest.build_household_briefing'), '4.8-signals', ('program',), 'schedule_view'),
    ((F, 'services.watchers._thread_stalls'), '4.8-signals', ('thread',), 'record_view'),
    ((F, 'services.watchers._mission_states'), '4.8-signals', ('mission',), 'record_view'),
    ((F, 'services.watchers._program_findings'), '4.8-signals', ('program',), 'record_view'),
    ((F, 'services.replies._recipients'), '4.8-signals', ('thread',), 'record_view'),
    ((F, 'services.mind.snapshot'), '4.8-signals', ('thread', 'mission', 'program'), 'record_view(HOUSE)'),
    ((F, 'services.mind._gather_deltas'), '4.8-signals', ('thread', 'mission', 'program'), 'finding_visible'),
    # INTERNAL (spec Appendix A)
    *[((F, name), 'INTERNAL', (), 'raw') for name in [
        'services.situations.load', 'services.situations._facts', 'services.situations.refresh',
        'services.situations.options_for', 'services.situations._thread_mission', 'services.subjects.load',
        'services.subjects.subject_records', 'services.projects.adopt', 'services.projects.adopt_existing',
        'services.projects._work_missions', 'services.projects.advance', 'services.projects.resume_waiting',
        'services.projects._busy_intervals', 'services.projects.find_window', 'services.threads.match_inbound',
        'services.email_ingest._match_thread', 'services.threads.is_stalled', 'services.threads.stalled',
        'services.threads.open_by_owner', 'services.vitals.measure_day', 'services.missions.tick',
        'services.planned.reconcile', 'services.planned._bind_created',
        'services.program_lessons.generate_due', 'services.program_lessons.generate_for',
        'services.program_lessons._windows_to_scan', 'services.programs.maybe_rebaseline',
        'services.programs.orphaned_emissions', 'services.access']],
]

# Whole route families that read no piece's words.
NONE_PREFIXES = ['/api/trip', '/api/music', '/api/house/facades', '/api/house/neighborhood',
                 '/api/house/session', '/api/lessons/', '/api/coverage', '/api/negotiation',
                 '/api/kid-tasks', '/api/household-tasks', '/api/calendar', '/api/calendars',
                 '/api/rules', '/api/schedule/refresh']


def _match(template, path):
    return template == path


def resolve_route(method, path):
    for rid, cls, kinds, check in READERS:
        if rid[0] == R and rid[1] == method and _match(rid[2], path):
            return (rid, cls, kinds, check)
    for rid, cls, kinds, check in READERS:
        if rid[0] == P and rid[1] in ('*', method) and path.startswith(rid[2]):
            return (rid, cls, kinds, check)
    if any(path.startswith(p) for p in NONE_PREFIXES):
        return (('route-prefix', '*', path), 'NONE', (), 'none')
    return None


def resolve_tool(name):
    return next((r for r in READERS if r[0][0] == T and r[0][1] == name), None)
```

Ruling: the register classifies only the routes and tools that the keyword filter in the test selects (Step 8), plus the function readers. A route outside the keywords is out of scope for the guard, and spec §5's stated limit covers that. Classifying every one of the hundreds of unrelated routes would turn the table into noise that hides the rows that matter. Codex #11 asked for broader keywords, and the test takes them: the base keywords plus `chat`, `commitments`, `findings`, `overview`, `summary`, `history`, `converse`, `packing`.

- [ ] **Step 8: Write the register test**

Create `chauffeur/tests/test_access_register.py`:

```python
"""Every reader of piece words is classified (spec §5).

Run from chauffeur/: python tests/test_access_register.py
"""
import ast
import re
import traceback
from pathlib import Path

from harness import check
from services import access_readers as reg
from services import agent_tools_v2 as tools
import main

ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = re.compile(r'thread|mission|program|situation|asks?\b|action-proposal|project|practice|lesson|'
                      r'study|house|schedule|calendar|subjects|chat|commitments|findings|overview|'
                      r'summary|history|converse|packing')
TOOL_KEYWORDS = re.compile(r'thread|mission|program|project|situation|_ask|ask_|lesson|practice|finding|'
                           r'summar|overview|history')
GETTERS = re.compile(r'\b(get_thread|get_threads|get_mission|get_missions|get_mission_steps|get_program|'
                     r'get_programs|get_protected_commitments|get_findings|get_open_findings|'
                     r'get_cached_schedule|get_conversation|get_all_conversations)\(')


def scenario_every_keyword_route_is_classified():
    missing = []
    for route in main.app.routes:
        path = getattr(route, 'path', '')
        for method in sorted(getattr(route, 'methods', None) or []):
            if method in ('HEAD', 'OPTIONS') or not KEYWORDS.search(path):
                continue
            if not path.startswith('/api/'):
                continue          # page shells read no record (spec Appendix A)
            if reg.resolve_route(method, path) is None:
                missing.append(f'{method} {path}')
    check(not missing, 'unclassified routes:\n' + '\n'.join(missing))


def scenario_every_keyword_tool_is_classified():
    names = sorted(getattr(tools, 'TOOL_HANDLERS', {}).keys())
    check(names, 'the registry is enumerable')
    missing = [n for n in names if TOOL_KEYWORDS.search(n) and reg.resolve_tool(n) is None]
    check(not missing, 'unclassified tools:\n' + '\n'.join(missing))


def _functions_calling_getters(path, module):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            src = ast.get_source_segment(path.read_text(encoding='utf-8'), node) or ''
            if GETTERS.search(src):
                out.add(f'{module}.{node.name}')
    return out


def scenario_every_function_reader_is_classified():
    known = {r[0][1] for r in reg.READERS if r[0][0] == 'reader'}
    routes = {r[0][2] for r in reg.READERS if r[0][0] in ('route', 'route-prefix')}
    missing = []
    for path in sorted((ROOT / 'services').glob('*.py')):
        module = 'services.' + path.stem
        if module in ('services.storage', 'services.access', 'services.access_readers'):
            continue
        for fn in _functions_calling_getters(path, module):
            if fn not in known and module not in known:
                missing.append(fn)
    check(not missing, 'unclassified function readers (add a READERS row or INTERNAL):\n' + '\n'.join(sorted(missing)))
    check(routes, 'route rows exist')


def scenario_classes_are_known():
    bad = [r for r in reg.READERS if r[1] not in reg.CLASSES]
    check(not bad, f'unknown classes: {bad}')


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
```

- [ ] **Step 9: Run the register test and classify until it passes**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_register.py`
Expected first: FAIL, with lists of unclassified routes, tools and function readers.

For each listed name, read the function and add a row:
- the class whose spec §4 section describes it, if it shows piece words to a person, screen, speaker, DM, push, digest or LLM transcript others read;
- INTERNAL if it acts for everyone and shows nothing;
- NONE (a `NONE_PREFIXES` entry or a NONE row) if it never reads piece words.

Re-run until it PASSes. Record every NONE and INTERNAL decision that Appendix A did not already make in `.superpowers/sdd/2026-10-16-project-access-rule/register-rulings.md`, one line each with the reason. The reviewer reads that file.

- [ ] **Step 10: Write the matrix frame**

Create `chauffeur/tests/test_access_matrix.py`.
- Every classified, non-INTERNAL, non-NONE reader needs a probe, unless it is listed in `PENDING` with the task that owns it.
- A probe returns, for one record and one viewer, what the reader showed: `'full'`, `'keeper'` or `None`.
- Expected values are the core `TABLE` (§7), with the per-class differences from §7 applied by `expect(cls, rkey, col)`.

```python
"""Run every classified reader as every fixture viewer (spec §6, §7).

Run from chauffeur/: python tests/test_access_matrix.py [class-prefix]
"""
import sys
import traceback

from harness import check
import access_fixture
from test_access_core import TABLE, COLS, KIND
from services import access, access_readers as reg

F, K, X = 'full', 'keeper', None

# Reader rows whose task has not landed. Each task deletes its own rows; Task 11 asserts empty.
PENDING = {
    'task3': {r[0] for r in reg.READERS if r[1] == '4.1-signed-in'},
    'task4': {r[0] for r in reg.READERS if r[1] == '4.2-conversation'},
    'task5': {r[0] for r in reg.READERS if r[1] == '4.3-channel'},
    'task6': {r[0] for r in reg.READERS if r[1] == '4.4-engine'},
    'task7': {r[0] for r in reg.READERS if r[1] == '4.5-voice'},
    'task8': {r[0] for r in reg.READERS if r[1] == '4.6-shared-screen'},
    'task9': {r[0] for r in reg.READERS if r[1] == '4.7-calendar'},
    'task10': {r[0] for r in reg.READERS if r[1] == '4.8-signals'},
}

PROBES = {}     # reader id -> probe(fx, rkey, col) -> 'full' | 'keeper' | None


def probe(*reader_ids):
    def wrap(fn):
        for rid in reader_ids:
            PROBES[rid] = fn
        return fn
    return wrap


RANK = {None: 0, K: 1, F: 2}


def expect(cls, rkey, col):
    """Spec §7: the person's-own-surface table, then the per-class differences."""
    row = dict(zip(COLS, TABLE[rkey]))
    base, house = row[col], row['house']
    if KIND[rkey] == 'program':          # a program's keeper projection renders full (spec §3)
        base = F if base == K else base
    if cls == '4.5-voice':
        return house                      # a speaker has a room around it
    if cls == '4.6-shared-screen':
        return max((base, house), key=RANK.get)   # the house's view plus the person's own
    return base


def observed(text, fx, rkey):
    """Classify a reader's output: absent, keeper words only, or the full words."""
    if fx.title(rkey) not in text:
        return None
    return F if fx.secret(rkey) in text else K


def pending_ids():
    return set().union(*PENDING.values())


def scenario_every_reader_has_a_probe_or_is_pending():
    missing = [r[0] for r in reg.READERS
               if r[1] not in ('INTERNAL', 'NONE') and r[0] not in PROBES and r[0] not in pending_ids()]
    check(not missing, 'readers with no probe:\n' + '\n'.join(map(str, missing)))


def scenario_every_probe_matches_the_table():
    only = sys.argv[1] if len(sys.argv) > 1 else ''
    fx = access_fixture.build()
    bad = []
    for rid, cls, kinds, _check in reg.READERS:
        if rid not in PROBES or rid in pending_ids() or not cls.startswith(only):
            continue
        for rkey in TABLE:
            if KIND[rkey] not in kinds:
                continue
            for col in COLS:
                want = expect(cls, rkey, col)
                got = PROBES[rid](fx, rkey, col)
                if got == 'skip':
                    continue
                if got != want:
                    bad.append(f'{rid} {rkey} {col}: want {want} got {got}')
    check(not bad, '\n'.join(bad))


SCENARIOS = [v for k, v in list(globals().items()) if k.startswith('scenario_')]
if __name__ == '__main__':
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    print('pending readers:', len(pending_ids()))
    raise SystemExit(bool(failed))
```

- [ ] **Step 11: Run all three test files, plus the neighbours that `access` now sits under**

Run:
```bash
cd chauffeur && unset HA_BASE_URL
python tests/test_access_core.py && python tests/test_access_register.py && python tests/test_access_matrix.py
for t in test_subjects test_situations test_mission_subject test_subject_hardening test_projects test_front_door_hardening test_project_final_fixes test_planned_missions; do echo "== $t"; python tests/$t.py 2>&1 | grep -E "^(FAIL|PASS)|passed|Error" | grep -v "^PASS" | head -5; done
```
Expected: the three access files PASS, and the matrix reports a pending count.
- Neighbours: any FAIL is either a call site that passes `None` where it meant the household (fix it in this task by passing `access.HOUSE`) or a cell the old code got wrong.
- For the second kind, stop and report it with the spec line. Do not weaken the old test.
- Known pre-existing reds that are not ours: `test_situation_tools` scenario_parity_both_ways, and `test_agent_v2_bridge` missing `send_direct_message`.

- [ ] **Step 12: Commit**

```bash
cd /e/repositories/Chauffeur
# Bump chauffeur/config.yaml to the next patch (version: "2.499.N" -> "2.499.N+1") by editing that line.
git add chauffeur/services/access.py chauffeur/services/access_readers.py chauffeur/tests/access_fixture.py \
  chauffeur/tests/test_access_core.py chauffeur/tests/test_access_register.py chauffeur/tests/test_access_matrix.py \
  chauffeur/services/situations.py chauffeur/services/subjects.py chauffeur/services/planned.py \
  chauffeur/services/projects.py chauffeur/config.yaml .superpowers/sdd/2026-10-16-project-access-rule/register-rulings.md
git commit -m "feat(access): one rule for who sees a thread, mission or program - access.record_view with keeper projections and HOUSE, the readers register, the fixture household and the matrix frame (access rule Task 1) (v2.499.N)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Remove "add an existing thread, mission or program to a project" (Codex) — spec §10.1

**Files:**
- Modify:
  - `chauffeur/services/projects.py` `_change_piece` (:740);
  - `chauffeur/services/agent_tools_v2.py` `add_to_project` (registry :8505, function near :3851);
  - `chauffeur/templates/components/projects_page.html`: the Add-a-piece "existing record" search (`/api/subjects/search` caller);
  - `chauffeur/services/migrations.py`: a new migration, registered where the others are.
- Test: `chauffeur/tests/test_access_add_existing_removed.py` (new).

**Interfaces:**
- Consumes: nothing from Task 1 beyond the fixture.
- Produces: `projects.PIECE_LINK_KINDS`, the kinds that may still be linked: every registered subject kind except `thread`, `mission` and `program`.

- [ ] **Step 1: Write the failing test**

```python
"""Spec §10.1: threads, missions and programs are never linked into another project.

Run from chauffeur/: python tests/test_access_add_existing_removed.py
"""
import traceback

from harness import check
import access_fixture
from fastapi.testclient import TestClient
from unittest.mock import patch
from services import storage, projects, migrations
from services import agent_tools_v2 as tools
import main


def scenario_service_refuses_piece_kinds():
    fx = access_fixture.build()
    p = fx.projects['mom_private']
    for kind, rkey in (('thread', 'R5t'), ('mission', 'R9b'), ('program', 'R5p')):
        out = projects.add_piece(p['id'], kind, fx.ids[rkey], fx.viewers['mom'])
        check(out['status'] == 'error', f'{kind} refused: {out}')
    check(not any(x['kind'] in ('thread', 'mission', 'program')
                  for x in storage.get_project(p['id']).get('pieces') or []), 'nothing linked')


def scenario_other_kinds_still_link():
    fx = access_fixture.build()
    out = projects.add_piece(fx.projects['household']['id'], 'occasion', 'occ-parents', fx.viewers['mom'])
    check(out['status'] == 'success', f'occasion still links: {out}')


def scenario_route_and_tool_refuse():
    fx = access_fixture.build()
    token = {'X-Member-Token': storage.create_member_token('mom')}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        r = TestClient(main.app).post(f"/api/projects/{fx.projects['mom_private']['id']}/pieces",
                                      json={'kind': 'thread', 'id': fx.ids['R5t']}, headers=token)
    check(r.status_code in (400, 422) or r.json().get('status') == 'error', f'route refuses: {r.status_code} {r.text}')
    out = tools.add_to_project(project_title='Mom private', kind='thread', record_title='Title R5t',
                               acting_member=fx.viewers['mom'])
    check(out.get('status') == 'error', f'tool refuses: {out}')


def scenario_migration_drops_old_links():
    fx = access_fixture.build()
    pid = fx.projects['mom_private']['id']
    storage.update_project(pid, {'pieces': [{'kind': 'thread', 'id': fx.ids['R5t']},
                                            {'kind': 'occasion', 'id': 'occ-parents'}]})
    migrations.migrate_drop_piece_kind_links_v2499()
    kinds = [x['kind'] for x in storage.get_project(pid)['pieces']]
    check(kinds == ['occasion'], f'only non-piece links survive: {kinds}')
    check(storage.get_thread(fx.ids['R5t'])['project_id'] == fx.projects['household']['id'], 'home unchanged')


def scenario_the_page_offers_no_piece_kind_search():
    src = open('templates/components/projects_page.html', encoding='utf-8').read()
    check("kinds=thread" not in src and "'thread', 'mission', 'program'" not in src.split('addExisting')[-1][:400],
          'the existing-record search no longer offers piece kinds')
```

Adjust `add_to_project`'s parameter names in the test to the real signature (read near :3851) before running. The assertion stands.

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_add_existing_removed.py`
Expected: FAIL. The service links the thread, and `migrate_drop_piece_kind_links_v2499` does not exist.

- [ ] **Step 3: Implement**

In `services/projects.py`:

```python
PIECE_HOME_KINDS = ('thread', 'mission', 'program')   # live in a project through project_id only


def _link_kinds():
    from services import subjects
    return tuple(k for k in subjects.ADAPTERS if k not in PIECE_HOME_KINDS)
```

In `_change_piece`, after the `kind not in subjects.ADAPTERS` check:

```python
        if kind in PIECE_HOME_KINDS and not removing:
            return _error('Threads, missions and programs start inside a project; they are not linked')
```

Keep `removing=True` working for old links, so a stray link can still be taken off by hand until the migration runs.
- In `agent_tools_v2.add_to_project`, refuse the same three kinds with the same message before any lookup.
- In `projects_page.html`, the Add-a-piece "existing record" search passes only `projects.PIECE_LINK_KINDS` (render the list into the island from the server, or filter the `/api/subjects/search` results client-side to kinds not in `['thread','mission','program']`). The "new thread", "new program" and "launch work" forms stay.
- Add `migrate_drop_piece_kind_links_v2499()` to `services/migrations.py`, next to `migrate_projects_adopt_v2499517` (:471), and register it in the same startup list. For each project, keep the `pieces` entries whose kind is not in `PIECE_HOME_KINDS`, and write only when something changed. It is idempotent.

- [ ] **Step 4: Run to verify it passes, plus neighbours**

Run: `cd chauffeur && unset HA_BASE_URL && for t in test_access_add_existing_removed test_project_pieces test_projects test_projects_parity test_access_register; do python tests/$t.py 2>&1 | tail -3; done`
Expected: all PASS.
- If `test_project_pieces` asserts that a thread links, that assertion described the removed capability. Retarget it to an occasion and say so in the hand-off note.
- If `test_projects_parity` lists the existing-record search as a thread capability, mark that row as removed by §10.1 in its inventory with the spec reference. Do not delete the row silently.

- [ ] **Step 5: Hand off.** Leave the tree uncommitted and write a short note of what changed and what was run. Claude reviews, bumps, and commits with `feat(projects): threads, missions and programs are no longer linked into other projects; old links dropped (access rule Task 2) (v2.499.N)`.

---

### Task 3: Class 4.1, signed-in pages and by-id routes (Codex)

**Files:**
- Modify `chauffeur/main.py` for every class `4.1-signed-in` row in `access_readers.READERS`. The routes are listed in spec Appendix A with their line numbers as of v2.499.520. Also `services/chat_actions.py` (`log_program_session`, `reshape_program` near :309/:313) and `services/asks.py` `create` (:133).
- Test: add probes to `chauffeur/tests/test_access_matrix.py`, and remove `PENDING['task3']`.

**Interfaces:**
- Consumes: `access.record_view`, `record_actable`, `HOUSE`, `batch`.
- Produces: `main._piece_viewer(request) -> dict`. It returns the signed-in member (`storage.get_member(_acting_id(request, None))`), or `access.HOUSE` when no person resolves. It replaces `_situation_viewer`'s `parent_of_record` stand-in for piece reads; `_situation_viewer` still serves findings and insights unchanged. Also `main._piece_or_404(kind, rid, request, verb=None) -> (row, view)`.

- [ ] **Step 1: Write the probes (failing)**

Add to `test_access_matrix.py`:

```python
from fastapi.testclient import TestClient
from unittest.mock import patch
from services import storage
import main

_TOKENS = {}


def _client_get(fx, col, path):
    """GET as a fixture viewer with auth enforcement on; HOUSE has no token."""
    headers = {}
    if col != 'house':
        member = fx.viewers[col]
        if member.get('status') == 'disabled':
            return None          # refused at the door; nothing shown
        headers = {'X-Member-Token': _TOKENS.setdefault(col, storage.create_member_token(member['id']))}
    with patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True}):
        r = TestClient(main.app).get(path, headers=headers)
    return r


def _text(r):
    return '' if r is None or r.status_code >= 400 else r.text


@probe(('route', 'GET', '/api/threads'), ('route', 'GET', '/api/situations'),
       ('route', 'GET', '/api/missions/admin'), ('route', 'GET', '/api/programs'),
       ('route', 'GET', '/api/projects'))
def _list_probe(fx, rkey, col):
    path = {'thread': '/api/threads', 'mission': '/api/missions/admin', 'program': '/api/programs'}[KIND[rkey]]
    if col == 'house':
        return 'skip'        # SIGNED_IN: an identity-free caller is refused at the door (spec §4)
    return observed(_text(_client_get(fx, col, path)), fx, rkey)


@probe(('route', 'GET', '/api/situations/{kind}/{sid}'), ('route', 'GET', '/api/missions/{mission_id}'),
       ('route', 'GET', '/api/projects/for/{kind}/{record_id}'))
def _by_id_probe(fx, rkey, col):
    kind = KIND[rkey]
    if col == 'house' or kind == 'program':
        return 'skip'
    r = _client_get(fx, col, f'/api/situations/{kind}/{fx.ids[rkey]}')
    if r is not None and r.status_code == 403:
        return 'FORBIDDEN-NOT-404'     # spec §4: never disclose existence
    return observed(_text(r), fx, rkey)
```

Add one probe per remaining 4.1 row in the same style.
- **Write routes** (PATCH, note, advance, delete, close, draft, photo, send, research, release, submit, verify, answer, drop, ack, approve, program actions, asks, proposals act, launch with `origin_ref`) are acted, not read. Their probe POSTs with the smallest valid body and returns `'full'` when the action is accepted (2xx), `None` on 404, and `'FORBIDDEN-NOT-404'` on 403.
- For writes, the expected cell is `record_actable`. Add an `ACT` table next to `TABLE` from spec §7 "Acting": Dad on R2 is None for every mission verb; Aunt on R2 is accepted only for ack, delete and steer; Aunt approving R3 gets 404; Dad approving R3 is accepted.
- Re-seed the fixture (`access_fixture.build()`) before each write probe, because writes change state.

- [ ] **Step 2: Run to verify they fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_matrix.py 4.1`
Expected: FAIL rows such as `GET /api/threads R5t kid: want None got full` (child sees unbound threads), `Dad on R2 answer: want None got full`, and `situations/... want None got FORBIDDEN-NOT-404`.

- [ ] **Step 3: Implement**

Add to `main.py`, next to `_situation_viewer`:

```python
def _piece_viewer(request):
    """The signed-in member, or HOUSE when no person resolves (access rule §4)."""
    from services import access
    mid = _acting_id(request, None)
    member = storage.get_member(mid) if mid else None
    return member or access.HOUSE


_PIECE_LOAD = {'thread': lambda rid: storage.get_thread(rid),
               'mission': lambda rid: storage.get_mission(rid),
               'program': lambda rid: storage.get_program(rid)}


def _piece_or_404(kind, rid, request, verb=None):
    """Load a piece the caller may see (and act on, with verb); else 404 shaped like missing."""
    from services import access
    row = _PIECE_LOAD[kind](rid)
    viewer = _piece_viewer(request)
    ok = row is not None and (access.record_actable(kind, row, viewer, verb) if verb
                              else access.record_visible(kind, row, viewer))
    if not ok:
        raise HTTPException(status_code=404, detail=f'No such {kind}')
    return row, access.record_view(kind, row, viewer)
```

Apply them to every class 4.1 route:
- **By-id reads and writes:** call `_piece_or_404(kind, id, request, verb)` before the existing role check. Keep the role check: `record_actable` adds to it and does not replace it. Verb names match the route's last path segment (`answer`, `release`, `submit`, `verify`, `drop`, `ack`, `delete`, `note`, `advance`, `close`, `draft`, `photo`, `send`, `research`, `approve`, `session`, `milestone`, `finish`, `reshape`, `pause`, `resume`, `edit`, `unit`, `lesson`).
- **List reads** (`/api/threads`, `/api/missions/admin`, `/api/programs`, `/api/situations`, `/api/projects`, `/api/projects/{id}`, `/api/projects/{id}/pieces`, `/api/subjects/search`, `/api/subjects/{kind}/{sid}/situations`, `/api/action-proposals`, `/api/projects/elsewhere`, `/api/programs/lessons/sweep`): wrap the body in `with access.batch():` and drop rows where `access.record_view(kind, row, _piece_viewer(request))` is None. For the situations and projects lists, pass the viewer through to `situations.list_situations` and `projects.piece_cards` instead of filtering after the fact.
- **Keeper rows** in lists carry the keeper projection already built by `situations.view` / `planned.keeper_view`. Do not rebuild it.
- **`/api/threads` checks every row** (spec §4.1); delete the `subject_kind or subject_history` gate (:7029–7033).
- **`POST /api/missions/launch`** with `origin_ref`: `_piece_or_404('thread', origin_ref, request, 'mission')`. Use the 404 when it fails.
- **`POST /api/asks`:** `_piece_or_404(kind, sid, request, 'ask')` before building the ask.
- **`chat_actions` `log_program_session` and `reshape_program`:** before `_execute`, require `access.record_actable('program', row, approver, verb)`. `approver` is the member acting on the proposal (`act_on_proposal` already resolves it).
- **`/api/findings`** belongs to Task 9. Leave it.
- **Existing `_situation_viewer` callers** that read findings or insights keep `_situation_viewer`.

- [ ] **Step 4: Run to verify, plus neighbours**

Run:
```bash
cd chauffeur && unset HA_BASE_URL
python tests/test_access_matrix.py 4.1
for t in test_access_register test_projects_parity test_retire_redirects test_project_final_fixes test_projects test_situations test_threads_api test_missions_api test_programs_api test_auth; do [ -f tests/$t.py ] && { echo "== $t"; python tests/$t.py 2>&1 | grep -E "^(FAIL)|passed" | head -5; }; done
```
Expected: the 4.1 matrix PASSes, and the neighbours stay green. A neighbour that asserted a child receives another person's unbound thread was asserting the leak spec §4.1 closes: retarget it and name the spec line in the hand-off note.

- [ ] **Step 5: Hand off.** Remove the `task3` entry from `PENDING`. Claude reviews, bumps, and commits with `fix(access): every signed-in page and by-id route asks access - 404 for hidden pieces, keeper projections in lists, HOUSE for identity-free callers (access rule Task 3) (v2.499.N)`.

---

### Task 4: Conversations belong to their surface (Codex) — spec §4.2, §10.2

**Files:**
- Modify:
  - `chauffeur/main.py`: `POST /api/chat` (:18482), `GET /api/chat/history` (:18618), `DELETE /api/chat/history`, `GET /api/chat/conversations`, and the conversation create route;
  - `chauffeur/services/storage.py`: conversations (:1263–1300), adding `get_surface_conversation`;
  - `chauffeur/templates/components/control_center.html` (:886–:965);
  - `chauffeur/templates/app.html`: remove the dead `kiosk-chat-popup`, `kiosk-chat-fab`, `toggleKioskChat` and `loadChatHistory` (:10373–:10525), `updateAgentFab` (:941–:962) and its callers (:916, :7260), and `static/app_voice.js:104` (the popup close);
  - `static/pwa_shell.css:131` and `static/pwa_child_shell.css:13`: drop `#kiosk-chat-fab` from the selectors.
- Test: `chauffeur/tests/test_access_conversations.py` (new); add probes for the 4.2 rows and remove `PENDING['task4']`.

**Interfaces:**
- Produces:
  - `storage.get_surface_conversation(kind, owner) -> dict`. It gets or creates the one live conversation for `(kind, owner)`, where `kind in ('admin', 'panel')` and `owner` is a member id or a device id.
  - `main._chat_surface(request) -> (kind, owner, viewer)`:
    - a member token on a non-panel page gives `('admin', member_id, member)`;
    - a device token gives `('panel', device_id, access.HOUSE)`;
    - a member on a page loaded with `panel=true` gives `('panel', device_id or 'anon-panel', access.HOUSE)`;
    - otherwise it is refused.
  - `access.conversation_view(kind, row, viewer, focus_key)` (added to `access.py` in Task 5, which owns channels). Here, `POST /api/chat` passes `viewer` from `_chat_surface` as the acting member, or HOUSE for panels.

- [ ] **Step 1: Confirm the dead popup is unreachable.** This is a check the user asked for, not a skip.

Run:
```bash
cd chauffeur && grep -n "data-audience\|dataset.audience" static/pwa_shell.js templates/app.html
grep -n "data-child-stage\|childStage" static/*.js templates/app.html | head
```
Expected: the audience is always `adult` or `child`; adults hide the FAB (`pwa_shell.css:131`); and every `child` audience also carries `data-child-stage` (`pwa_child_shell.css:13`).
- If any audience can see `#kiosk-chat-fab`, STOP. Report it with the file and line; the removal then needs the user's approval.

- [ ] **Step 2: Write the failing test**

```python
"""Spec §4.2: every Argyle conversation belongs to its surface.

Run from chauffeur/: python tests/test_access_conversations.py
"""
import traceback
from pathlib import Path
from unittest.mock import patch

from harness import check
import access_fixture
from fastapi.testclient import TestClient
from services import storage
import main

ROOT = Path(__file__).resolve().parents[1]


def _enforced():
    return patch.object(storage, 'get_settings', return_value={**storage.get_settings(), 'auth_enforce': True})


def scenario_admin_conversation_is_the_persons():
    fx = access_fixture.build()
    mom = {'X-Member-Token': storage.create_member_token('mom')}
    dad = {'X-Member-Token': storage.create_member_token('dad')}
    with _enforced():
        c = TestClient(main.app)
        conv = c.get('/api/chat/conversation?surface=admin', headers=mom).json()['conversation']
        check(conv['surface'] == {'kind': 'admin', 'owner': 'mom'}, f'owned: {conv}')
        storage.add_message_to_conversation(conv['id'], {'role': 'assistant', 'content': fx.secret('R1')})
        r = c.get(f"/api/chat/history?conversation_id={conv['id']}", headers=dad)
        check(r.status_code == 404, f'Dad cannot read Mom\'s conversation: {r.status_code}')
        listed = c.get('/api/chat/conversations', headers=dad).json()['conversations']
        check(all(x['id'] != conv['id'] for x in listed), 'Dad cannot list it')


def scenario_panel_conversation_reads_as_house():
    fx = access_fixture.build()
    token = storage.enrol_device_token('panel-kitchen', 'Kitchen')
    seen = {}
    def fake(message, **kw):
        seen.update(kw)
        return {'message': 'ok'}
    with _enforced(), patch.object(main, 'process_agent_request', side_effect=fake):
        c = TestClient(main.app)
        conv = c.get('/api/chat/conversation?surface=panel', headers={'X-Device-Token': token}).json()['conversation']
        check(conv['surface'] == {'kind': 'panel', 'owner': 'panel-kitchen'}, f'panel owns it: {conv}')
        c.post('/api/chat', json={'message': 'hi', 'conversation_id': conv['id']}, headers={'X-Device-Token': token})
    from services import access
    check(seen.get('acting_member') == access.HOUSE, f"Argyle on a panel reads as HOUSE: {seen.get('acting_member')}")


def scenario_legacy_conversations_are_parents_read_only():
    fx = access_fixture.build()
    storage.create_conversation({'id': 'old-general', 'type': 'general', 'messages': [], 'updated_at': 9e9})
    with _enforced():
        c = TestClient(main.app)
        aunt = {'X-Member-Token': storage.create_member_token('aunt')}
        mom = {'X-Member-Token': storage.create_member_token('mom')}
        check(c.get('/api/chat/history?conversation_id=old-general', headers=aunt).status_code == 404, 'adult cannot read legacy')
        check(c.get('/api/chat/history?conversation_id=old-general', headers=mom).status_code == 200, 'parent can read legacy')
        r = c.post('/api/chat', json={'message': 'hi', 'conversation_id': 'old-general'}, headers=mom)
        check(r.status_code in (404, 409), f'Argyle never answers into legacy: {r.status_code}')


def scenario_widget_asks_server_for_its_conversation():
    src = (ROOT / 'templates/components/control_center.html').read_text(encoding='utf-8')
    check('chauffeurActiveConvId' not in src, 'no invented localStorage id')
    check('api/chat/conversation?surface=' in src, 'asks the server')


def scenario_dead_pwa_popup_is_gone():
    src = (ROOT / 'templates/app.html').read_text(encoding='utf-8')
    for marker in ('kiosk-chat-popup', 'kiosk-chat-fab', 'toggleKioskChat', 'loadChatHistory'):
        check(marker not in src, f'{marker} removed')
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_conversations.py`
Expected: FAIL, because there is no `/api/chat/conversation` route, Dad reads Mom's history, and so on.

- [ ] **Step 4: Implement**

- **`storage.get_surface_conversation(kind, owner)`:** search `conversations_table` for `surface == {'kind': kind, 'owner': owner}` and not `legacy`. If there is none, create `{'id': 'conv_' + uuid4().hex, 'type': 'surface', 'surface': {...}, 'messages': [], 'created_at': now, 'updated_at': now}`. Because `get_all_conversations` prunes after 30 days of no update, a surface conversation is recreated on its next use.
- **New route `GET /api/chat/conversation?surface=admin|panel`:** auth tier WALL. Add an `auth.RULES` row; `test_auth` flags it otherwise. It uses `_chat_surface(request)`, refusing an admin surface without a member (401) and a panel surface without a device or member (401), and returns `{'conversation': row}`.
- **`GET /api/chat/history` and `DELETE /api/chat/history`:** only for the owner. That is a member whose id equals the `surface.owner` of an `admin` conversation, or the device or a parent for a `panel` conversation. Legacy rows (no `surface`) are for parents only. Satellite sessions keep their existing parent-only rule. Anything else gets a 404. `DELETE` with no id clears only the caller's own conversation, no longer every conversation (`storage.clear_chat_history` stays for tests only).
- **`GET /api/chat/conversations`:** the caller's own surface conversations; plus legacy and voice rows for parents only.
- **`POST /api/chat`:**
  - resolve `(kind, owner, viewer) = _chat_surface(request)`;
  - refuse a `conversation_id` the caller does not own (404) and a legacy one (409 "That conversation is history; start a new one");
  - pass `acting_member=viewer` (HOUSE for panels) and `focus_key='conv:' + id`.
  - Remove the `parent_of_record` substitution for identity-free callers in `agent_router` tool dispatch (:1001–1050): no member means `access.HOUSE` for situation and project tools, and `access.HOUSE` for thread and program tools. In `agent_router`, "no member" is now always HOUSE, never a parent stand-in (spec §4.2).
- **`control_center.html`:** replace the localStorage id (:886–:889) with a call to `api/chat/conversation?surface=` + (`new URLSearchParams(location.search).get('panel') === 'true' ? 'panel' : 'admin'`), storing the id in memory only. Keep the 30-second bubble behaviour exactly as it is. The user parked the history view as backlog (memory `agent-history-surfaces-gap`).
- **`app.html`:** remove the dead popup block, the FAB, `toggleKioskChat`, `loadChatHistory`, `activeConversationId`, `updateAgentFab` and its two call sites. Remove the popup-close lines in `app_voice.js:104–105` and `#kiosk-chat-fab` in the two CSS selectors. Run `python tools/build_tailwind.py` from the repo root.

- [ ] **Step 5: Run to verify, plus neighbours**

Run:
```bash
cd chauffeur && unset HA_BASE_URL
for t in test_access_conversations test_access_register test_access_matrix test_auth test_agent_router test_chat_api test_voice_session; do [ -f tests/$t.py ] && { echo "== $t"; python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -5; }; done
```
Expected: all PASS.

- [ ] **Step 6: Hand off.** Remove the `task4` entry from `PENDING`. Claude reviews (including a manual look at an admin page and a `?panel=true` page with the widget, via the run skill), bumps, and commits with `feat(chat): every Argyle conversation belongs to its surface - the admin widget per person, a wall panel per device reading as the house, old shared conversations parents-only history; the hidden PWA popup removed (access rule Task 4) (v2.499.N)`.

---

### Task 5: Argyle in DMs and channels (Codex) — spec §4.3

**Files:**
- Modify:
  - `chauffeur/services/access.py`: add `channel_view` and `conversation_view`;
  - `chauffeur/services/situations.py`: `channel_visible` :557 becomes a thin call;
  - `chauffeur/services/agent_tools_v2.py`: every class `4.3-channel` tool row, and `_match_thread` (:1915), `_match_program` (:2430), `_thread_reader`, `_program_reader`, `_program_scope_id` callers, and the registry wrappers (:8491–:9062) that pass `_REGISTRY_READER`;
  - `chauffeur/services/agent_router.py`: focus injection :264–:308 and tool dispatch :1001–:1100;
  - `chauffeur/services/triage.py`: `next_for`, `get_focus`, `focus_live_asks`, `_alive`.
- Test: probes for the 4.3 rows, and remove `PENDING['task5']`.

**Interfaces:**
- Consumes: `record_view`, `KEEPER`, `FULL`, `home_project`, `restricted`.
- Produces:

```python
def channel_view(kind, row, focus_key):
    """The projection every human in a channel may receive (spec §4.3)."""
    from services import subjects, situations
    humans = subjects.channel_humans(focus_key)
    if humans is None:
        return NOT_A_CHANNEL
    if not restricted(home_project(row)):
        return FULL if situations._legacy_channel_visible(kind, row, humans) else None
    views = [record_view(kind, row, h) if h else None for h in humans]
    if not views or any(v is None for v in views):
        return None
    return KEEPER if KEEPER in views else FULL


def conversation_view(kind, row, viewer, focus_key):
    """What Argyle may show here: the channel's common projection, else the speaker's."""
    view = channel_view(kind, row, focus_key)
    return record_view(kind, row, viewer) if view is NOT_A_CHANNEL else view
```

  - `situations._legacy_channel_visible(kind, row, humans)` is today's body of `channel_visible` (every member passes `_subject_visible` for every subject record). `channel_visible(kind, row, focus_key)` becomes `access.conversation_view(kind, row, None, focus_key) not in (None,)` for channel focus keys, and keeps its project branch.
  - `agent_tools_v2._render_at(kind, row, view, viewer)`: renders a situation, thread or program row at a given projection, using `situations.view` with a viewer whose projection matches. For `KEEPER`, render as the keeper: `situations.view(kind, rid, {'id': access.keeper_id(kind, row), **keeper_member})`. Tools, FOCUS and ABOUT all use it.

- [ ] **Step 1: Write the probes (failing)**

Probes call each tool handler directly, as `tools.<fn>(..., acting_member=fx.viewers[col], focus_key=<dm or group>)`, and classify the output with `observed(json.dumps(out), fx, rkey)`.

There are three focus contexts, listed in an `EXPECT_CHANNEL` table that implements spec §7's group-channel line:
- `col`'s own DM (`storage.get_or_create_dm(argyle_id, member_id)`): expected values from `TABLE`.
- The family channel: unrestricted rows follow today's rule (the test asserts the old result by calling `situations._legacy_channel_visible`); R1–R4, R7, R10 and R11 are None.
- A Mom+Aunt group: R1 and R2 are `keeper` for both speakers; R3 and R4 are None.

Add three named regression probes:
- **`B1_household_piece_readable_by_engine`:** `tools.list_threads(acting_member=access.HOUSE)` shows R5t.
- **`B2_channel_program_rule`:** in the family channel, Mom asking `list_programs` sees her own unrestricted program.
- **`I2_keeper_own_dm`:** Kate's DM `list_programs` shows R3; Aunt's DM `list_threads` shows R1 at keeper projection.
- **`M5_unmatched_launch_falls_back`:** in Dad's DM, `launch_mission(thread_title='Title R1')` launches a plain mission, and the reply and the mission's seeded steps do not contain `Title R1`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_matrix.py 4.3`
Expected: FAIL. For example, the Mom+Aunt channel shows R2 in full when Mom asks.

- [ ] **Step 3: Implement**

- Add `channel_view` and `conversation_view` to `access.py` exactly as above.
- **Every 4.3 tool:**
  - replace its visibility gate with `view = access.conversation_view(kind, row, acting_member or access.HOUSE, focus_key)`;
  - drop the row when `view` is None;
  - render through `_render_at(kind, row, view, acting_member)`.
- **The title matchers** (`_match_thread`, `_match_program`, `missions._match_thread` when called from `launch_mission`) take `(title, viewer, focus_key)` and search only rows whose `conversation_view` is not None.
  - The not-found hint lists only visible titles.
  - `launch_mission` with no visible match launches a plain mission (the pre-round-2 fallback).
- **The registry wrappers** pass `access.HOUSE` where they passed `_REGISTRY_READER`, and `access.HOUSE_PARENT` where they passed `_registry_parent()` for writes. `_REGISTRY_READER` stays only as an alias of `access.HOUSE`.
- **`agent_router`:**
  - FOCUS and ABOUT injection render at `conversation_view` for the focus record;
  - when the projection is `KEEPER`, ABOUT carries no subject context (`subjects.context` is skipped) and FOCUS uses the keeper title only;
  - the voice focus branch belongs to Task 7, so leave it.
- **`triage`:** filter with `conversation_view`. `_alive` filters too.

- [ ] **Step 4: Run to verify, plus neighbours**

Run:
```bash
cd chauffeur && unset HA_BASE_URL
python tests/test_access_matrix.py 4.3
for t in test_situation_tools test_subject_hardening test_agent_router test_threads_tools test_programs_tools test_front_door_chat test_triage test_access_register; do [ -f tests/$t.py ] && { echo "== $t"; python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -5; }; done
```
Expected: PASS, apart from the known pre-existing red `test_situation_tools scenario_parity_both_ways`.

- [ ] **Step 5: Hand off.** Remove `task5` from `PENDING`. Commit message: `fix(access): Argyle shows a piece only at the projection everyone in the conversation may receive; title matching searches only visible records and falls back without naming hidden ones (access rule Task 5) (v2.499.N)`.

---

### Task 6: The mission engine (Codex) — spec §4.4

**Files:**
- Modify:
  - `chauffeur/services/access.py`: add `mission_view`;
  - `chauffeur/services/missions.py`: `read_viewer` :429, `_apply_planner_action` (tool branch :1471, find branch :1481, subject branch :1518, draft branch :1619), `_match_thread` :309, `_seed_thread_context` :1691, `launch` :1715, `ask_card` :342, `_finder` :441 (unchanged for the subject only).
- Test: probes for the 4.4 rows; remove `PENDING['task6']`.

**Interfaces:**

```python
def mission_reader(mission):
    """HOUSE or HOUSE_PARENT: today's missions.read_viewer, with the named viewers."""
    from services import subjects

    def seen(k, r, v):
        if k in KINDS:
            return record_view(k, r, v) == FULL
        if k in ('project', 'proposed_project'):
            return project_visible(r, v)
        return subjects.visible(k, r, v)

    records = subjects.subject_records('mission', mission or {})
    if records and all(not seen(k, r, HOUSE) and seen(k, r, HOUSE_PARENT) for k, r in records):
        return HOUSE_PARENT
    return HOUSE


def mission_view(mission, kind, row):
    """What a mission's own reads may see (spec §4.4)."""
    if not row:
        return None
    if (kind == 'thread' and mission.get('origin_kind') == 'thread'
            and row.get('id') == mission.get('origin_ref')):
        return FULL
    reader = mission_reader(mission)
    if mission.get('project_id') and row.get('project_id') == mission.get('project_id'):
        return record_view(kind, row, reader, skip_project=True)
    return record_view(kind, row, reader)
```

`missions.read_viewer(mission)` returns `access.mission_reader(mission)`. Keep the name; its callers stay.

- [ ] **Step 1: Write the probes (failing)**

The probes run `missions._apply_planner_action` with a stubbed planner action for each branch, on R9a (a mission in Mom's private project with an origin thread) and on R9b (a household-project mission):
- **I6:** R9a's `draft` action drafts from its origin thread R9origin. Stub `threads.draft_message` to echo its context, and expect the origin's secret in the stored draft step.
- **Own project:** R9a's tool action `list_threads` sees R1 (same project, `skip_project`) and R9origin.
- **Never wider:** R9b's tool action `list_threads` and its `draft` action naming `Title R1` see nothing of R1; the draft falls back to a plain draft and the stored steps never contain `Title R1` or R1's secret.
- **Seeding:** `missions.launch(..., origin_ref=R1)` called by a household mission's creator path refuses to seed R1's context unless `mission_view(new_mission, 'thread', R1)` passes. Assert the seeded step is absent.

- [ ] **Step 2: Run to verify they fail.** `python tests/test_access_matrix.py 4.4`. Expected: R9a cannot draft from its origin (round 3's I6), or R9b reads R1.

- [ ] **Step 3: Implement.** Every engine read of a thread, mission or program goes through `access.mission_view(mission, kind, row)`.
- **Tool branch:** `execute_tool(actor=missions.read_viewer(m))`, with Task 5's tools treating `skip_project` for the mission's own project. Pass `mission_id` through the tool context and have the tool use `mission_view` when `mission_id` is present.
- **Draft branch:** origin thread first; otherwise `_match_thread(title, mission=m)` searching rows where `mission_view` is not None.
- **`_seed_thread_context`:** seeds only when `mission_view` passes.
- **`ask_card`:** renders the project title and goal only when `mission_view` for the project's pieces passes. The card goes to the mission's own DM recipient (Task 9 decides who that is).

- [ ] **Step 4: Run to verify, plus neighbours**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_matrix.py 4.4 && for t in test_mission_subject test_planned_missions test_missions test_mission_engine test_front_door_chat; do [ -f tests/$t.py ] && python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -3; done`
Expected: PASS.

- [ ] **Step 5: Hand off.** Remove `task6` from `PENDING`. Commit message: `fix(access): a mission reads the household, its own project's pieces and its origin thread, never its creator's other private records (access rule Task 6) (v2.499.N)`.

---

### Task 7: Voice (Codex) — spec §4.5

**Files:**
- Modify:
  - `chauffeur/services/voice_approval.py`: `valid` :43, `prepare` :70, `intercept` :142;
  - `chauffeur/services/voice_tools.py`: `dispatch` :34;
  - `chauffeur/services/agent_router.py`: the voice focus injection :294–:308.
- Test: probes for the 4.5 rows; remove `PENDING['task7']`.

- [ ] **Step 1: Write the probes (failing)**

- `voice_tools.dispatch('find_in_chauffeur', {'query': 'Title R…'}, verified_member=fx.viewers[col])` returns R5t only when it is `spoken_safe`, and never R1–R4, R7, R10 or R11, whoever the verified speaker is. The voice column is the HOUSE column (`expect('4.5-voice', …)`).
- **Voice approval of an ask on R2:** create an ask step on R2 with a pending approval, then call `voice_approval.prepare(text='approve it', member=fx.viewers['mom'])`. Expect the refusal line `That one's private — open it on your phone.` and no state change on R2.

- [ ] **Step 2: Run to verify they fail.** `python tests/test_access_matrix.py 4.5`. Expected: Mom's verified voice approves R2, because voice uses `can_see` with the speaker.

- [ ] **Step 3: Implement.**
- Every voice read uses `access.record_view(kind, row, access.HOUSE)`, plus the existing `spoken_safe` check.
- `prepare` and `intercept` refuse with the spoken line above when the target record's `record_view(…, access.HOUSE)` is None, even when the verified speaker could see it. Return the line as the spoken reply, and leave the ask open.
- The voice focus ABOUT injection uses HOUSE.

- [ ] **Step 4: Run to verify, plus neighbours**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_matrix.py 4.5 && for t in test_voice_approval test_voice_tools test_voice_session test_voice_enrollment; do [ -f tests/$t.py ] && python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -3; done`
Expected: PASS.

- [ ] **Step 5: Hand off.** Remove `task7` from `PENDING`. Commit message: `fix(access): voice reads as the house, and a spoken approval of a private piece is refused aloud (access rule Task 7) (v2.499.N)`.

---

### Task 8: Shared screens (Codex) — spec §4.6

**Files:**
- Modify:
  - `chauffeur/services/house_programs.py` (`objects` :22, `session` :37);
  - `chauffeur/services/house_attention.py` (`_programs` :46);
  - `chauffeur/services/study.py` (`_board` :56, `_binders` :391);
  - `chauffeur/services/programs.py` (`celebrations` :1477);
  - `chauffeur/services/home_board.py` (`_tile_programs` :2027, `_tile_mind` :2748);
  - `chauffeur/main.py`: `/api/house/state` :6564, `/api/house/programs/{id}/session` :6732, `/api/programs/{id}/lesson-scenes` :7875, `/api/programs/{id}/lesson-help` :8094, `/api/programs/celebrations` :8264, `/api/study/state` :6696.
- Test: probes for the 4.6 rows; remove `PENDING['task8']`.

**Interfaces:**
- Consumes: `access.shared_screen_visible(kind, row, viewer)`. The viewer is the signed-in person if any, else `access.HOUSE`; `main._piece_viewer(request)` from Task 3.

- [ ] **Step 1: Write the probes (failing)**

- Each shared-screen reader is called as a panel (a device token, which gives HOUSE) and as each signed-in person. Classify with `observed`.
- Expected values come from `expect('4.6-shared-screen', …)`: the anonymous wall gets the HOUSE column; a person gets HOUSE ∪ their own column.
- Add round 3's **I4** probe: Kate signed in sees R5p's window titled and R3 titled; Aunt sees R5p but not R3.
- Add a counts probe: `house_attention` counts exclude R3 for HOUSE and include it for Mom.

- [ ] **Step 2: Run to verify they fail.** `python tests/test_access_matrix.py 4.6`. Expected: R3 appears on the anonymous wall (`house_programs.objects` lists every program).

- [ ] **Step 3: Implement.**
- Every reader filters rows with `access.shared_screen_visible(kind, row, viewer)` and returns 404 for a by-id shared-screen route whose row fails.
- Thread the viewer from the route into each service function as a new keyword `viewer=` (default `access.HOUSE`), so internal callers stay correct.
- `/api/study/state` passes the signed-in person.

- [ ] **Step 4: Run to verify, plus neighbours**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_matrix.py 4.6 && for t in test_house_programs test_house_room test_study test_home_board test_programs_card test_lesson_player; do [ -f tests/$t.py ] && python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -3; done`
Expected: PASS.

- [ ] **Step 5: Hand off.** Remove `task8` from `PENDING`. Commit message: `fix(access): walls, House, Study and lesson screens show the house's view plus the signed-in person's own (access rule Task 8) (v2.499.N)`.

---

### Task 9: Calendar, commitments, pushes, and no target-date events (Codex) — spec §4.7, §10.3

**Files:**
- Modify:
  - `chauffeur/services/access.py`: add `schedule_view` and `neutral_practice`;
  - `chauffeur/main.py`: `_practice_events` :19389, `/api/schedule` :21376, `/api/practice-windows` :7679, `/api/commitments` :5327, `/api/packing/day` :11723, and the `get_cached_schedule` readers in `agent_tools_v2.py` (:73, :127, :1212);
  - `chauffeur/services/programs.py`: the emission loop near :982, `approve` target event :1076–:1110, `footprint` :831/:841, `maybe_rebaseline` :1312–:1324, `due_practice_pushes` :782;
  - `chauffeur/services/family_day.py` :141;
  - `chauffeur/services/family_digest.py` :370;
  - `chauffeur/services/migrations.py`: two migrations.
- Test: probes for the 4.7 rows; `chauffeur/tests/test_access_calendar.py` (new) for the migrations and the cache-narrowing case; remove `PENDING['task9']`.

**Interfaces:**

```python
NEUTRAL_PRACTICE_KEYS = ('member_id', 'color', 'date', 'time_start', 'time_end')


def neutral_practice(event):
    """The Busy copy of a practice event (spec §4.7): structure, no words."""
    import hashlib
    practice = event.get('practice') or {}
    return {'id': 'busy-' + hashlib.sha1(str(event.get('id')).encode()).hexdigest()[:12],
            'title': 'Busy', 'description': '', 'start': event.get('start'), 'end': event.get('end'),
            'all_day': event.get('all_day', False), 'event_type': 'practice',
            'calendar_ids': event.get('calendar_ids') or [],
            'practice': {k: practice.get(k) for k in NEUTRAL_PRACTICE_KEYS}}


def schedule_view(blob, viewer):
    """Apply the current audience to a schedule blob, row by row, at read time."""
    import copy
    if not blob:
        return blob
    out = copy.copy(blob)
    with batch():
        programs = {}
        def visible(pid):
            if pid not in programs:
                row = storage.get_program(pid)
                programs[pid] = bool(row) and (record_visible('program', row, viewer)
                                               if not is_house(viewer) else record_visible('program', row, HOUSE))
            return programs[pid]
        events = []
        for ev in blob.get('events') or []:
            pid = ((ev.get('practice') or {}).get('program_id')) if ev.get('event_type') == 'practice' else None
            events.append(ev if not pid or visible(pid) else neutral_practice(ev))
        out['events'] = events
    return out
```

Ruling: the neutral copy's event id is a hash, because the real id embeds `program_id` (`practice-{program_id}-{date}-{time}`, `main.py` :19455). Restoring a viewer's titles needs no separate step, because `schedule_view` runs per viewer at read time on the whole cached blob. That replaces the "restore only when the cached copy is neutral" mechanism of spec §4.7 with the simpler equivalent spec §4.7 also states ("redaction at consumption, not at caching"): the cache keeps full words, and every read redacts.

- [ ] **Step 1: Write the tests (failing)**

Matrix probes:
- `/api/schedule`, `/api/practice-windows` and `/api/packing/day` as the panel (HOUSE) and as each person. A secret-string sweep of the whole JSON for R3's `title`, `secret`, `unit_title`, `steps` and `milestone` words. Expected values from §7's calendar line: B (None) for HOUSE, Aunt and Hal; full for Mom, Dad and Kate.
- `/api/commitments` shows R3's commitment as "Busy" for Aunt.

`test_access_calendar.py`:

```python
def scenario_cache_narrowing_takes_effect_at_read():
    fx = access_fixture.build()
    hh = fx.projects['household']
    pid = fx.ids['R5p']
    storage.set_cached_schedule({'events': [{'id': f'practice-{pid}-2026-10-16-17:00', 'title': 'Title R5p',
        'event_type': 'practice', 'description': 'SECRET-R5p-WORDS', 'start': '2026-10-16T17:00:00',
        'end': '2026-10-16T17:30:00', 'calendar_ids': ['kid'],
        'practice': {'program_id': pid, 'member_id': 'kid', 'color': '#123456', 'unit_title': 'SECRET-R5p-WORDS',
                     'date': '2026-10-16', 'time_start': '17:00', 'time_end': '17:30'}}]})
    storage.update_project(hh['id'], {'audience': 'private'})
    from services import access
    out = access.schedule_view(storage.get_cached_schedule(), access.HOUSE)
    text = json.dumps(out)
    check('SECRET-R5p' not in text and 'Title R5p' not in text and pid not in text, 'narrowed at read')
    check(out['events'][0]['practice']['color'] == '#123456', 'colour kept')
    out = access.schedule_view(storage.get_cached_schedule(), fx.viewers['dad'])
    check('SECRET-R5p' in json.dumps(out), 'the owner of the household-now-private project still reads it')


def scenario_no_target_event_is_written():
    fx = access_fixture.build()
    created = []
    with patch('services.calendar.create_event', side_effect=lambda *a, **k: created.append(a) or 'ev1'):
        pid = storage.add_program({'title': 'T', 'member_id': 'mom', 'state': 'proposed',
                                   'baseline': {'target_date': '2027-01-01'}, 'proposal': {'slots': []}})
        programs.approve(pid, dict(MOM))
    check(not created, f'no calendar event for a target date: {created}')


def scenario_migration_deletes_old_target_events():
    deleted = []
    pid = storage.add_program({'title': 'T', 'member_id': 'mom', 'state': 'active',
                               'baseline': {'target_date': '2027-01-01', 'target_event_id': 'ev-old'},
                               'emissions': {'event_ids': ['ev-old'], 'commitment_ids': []}})
    with patch('services.calendar.delete_event', side_effect=lambda cal, ev: deleted.append(ev) or True):
        migrations.migrate_remove_target_events_v2499()
    row = storage.get_program(pid)
    check(deleted == ['ev-old'] and not row['baseline'].get('target_event_id')
          and 'ev-old' not in row['emissions']['event_ids'], f'removed: {deleted} {row}')


def scenario_commitment_sources_backfilled():
    fx = access_fixture.build()
    pid = fx.ids['R3']
    cid = storage.add_protected_commitment({'id': 'c1', 'member_id': 'kid', 'title': 'Title R3',
                                            'days_of_week': [1], 'time_start': '17:00', 'time_end': '17:30', 'active': True})
    storage.update_program(pid, {'emissions': {'commitment_ids': [cid], 'event_ids': []}})
    migrations.migrate_commitment_sources_v2499()
    check(storage.get_protected_commitment(cid)['source'] == {'kind': 'program', 'id': pid}, 'source set')
```

Match the calendar module path and the delete function name to the real ones (`release_commitments` :273 shows the delete path) before running. The assertions stand.

Also test that `due_practice_pushes` for R3 with Hal as driver yields "Practice time" and no title, and that `family_digest` never lists a `Busy` practice or a hold as "nobody yet".

- [ ] **Step 2: Run to verify they fail.** `python tests/test_access_matrix.py 4.7 && python tests/test_access_calendar.py`. Expected: secret words reach HOUSE, a target event is created, and the migrations are missing.

- [ ] **Step 3: Implement.**
- Every listed reader passes its blob through `access.schedule_view(blob, viewer)`, with `viewer = main._piece_viewer(request)` on routes and `access.HOUSE` for the digest, the Mind and the panel-facing Argyle calendar tools.
- `/api/practice-windows` builds windows then applies the same `neutral_practice` per window.
- The program emission loop adds `'source': {'kind': 'program', 'id': row['id']}`.
- `/api/commitments` replaces `title` with `'Busy'` when the source program fails `record_visible`.
- Remove the target-event block in `approve`, and the target-event mentions in `footprint` and `maybe_rebaseline`. Do not touch `baseline.target_date` itself.
- Add the two migrations and register them.
- `due_practice_pushes` builds the message per recipient.
- `family_digest` skips events whose title is `Busy` and whose `event_type` is `practice` or `project_hold`.

- [ ] **Step 4: Run to verify, plus neighbours**

Run:
```bash
cd chauffeur && unset HA_BASE_URL
python tests/test_access_matrix.py 4.7 && python tests/test_access_calendar.py
for t in test_programs test_programs_api test_program_emissions test_practice_windows test_family_day test_family_digest test_schedule_api test_scope_schedule test_project_holds; do [ -f tests/$t.py ] && { echo "== $t"; python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -3; }; done
```
Expected: PASS. A neighbour asserting that a target event is created asserted the capability §10.3 removed: retarget it to assert no event, and name the spec line in the hand-off note.

- [ ] **Step 5: Hand off.** Remove `task9` from `PENDING`. Commit message: `fix(access): a private program's time reads Busy everywhere at read time, its commitments and pushes follow it, and target dates no longer write calendar events (access rule Task 9) (v2.499.N)`.

---

### Task 10: Signals, findings, the Mind and DMs (Codex) — spec §4.8

**Files:**
- Modify:
  - `chauffeur/services/access.py`: add `finding_visible`;
  - `chauffeur/services/watchers.py` (`_thread_stalls` :405, `_mission_states` :448, `_program_findings` :537, `run_watchers` :859, `_post_action_cards` :966, `_heads_up_line` :831);
  - `chauffeur/services/findings.py`: the open and historical reads;
  - `chauffeur/services/agent_tools_v2.py`: `list_open_findings` :1380;
  - `chauffeur/main.py`: `GET /api/findings` :5383;
  - `chauffeur/services/replies.py`: `_recipients` :150, `flush_pending_dms` :186;
  - `chauffeur/services/missions.py`: `_dm_person` :486;
  - `chauffeur/services/planned.py`: `_ask` :204;
  - `chauffeur/services/mind.py`: `snapshot` threads :263, the findings section, `_gather_deltas` :698.
- Test: probes for the 4.8 rows; remove `PENDING['task10']`.

**Interfaces:**

```python
def finding_visible(finding, viewer):
    """A finding derives its audience from its source record, now (spec §4.8)."""
    kind = finding.get('subject_type')
    if kind not in KINDS or not finding.get('subject_id'):
        return True
    row = KINDS[kind].load(finding['subject_id'])
    return row is None or record_visible(kind, row, viewer)


def private_recipients(kind, row):
    """Who a restricted record's DM-worthy signal goes to (spec §4.8)."""
    from services import projects
    home = home_project(row)
    out = []
    keeper = keeper_id(kind, row)
    if keeper:
        out.append(keeper)
    child_keeper = bool(keeper) and projects._child(_get_member(keeper) or {})
    if (home and home.get('audience') == 'parents') or child_keeper:
        out += [m['id'] for m in storage.get_all_members()
                if projects._parent(m) and projects._active(m) and record_visible(kind, row, m)]
    return list(dict.fromkeys(out))
```

- [ ] **Step 1: Write the probes (failing)**

- **Pre-existing finding:** add a finding `{'subject_type': 'thread', 'subject_id': R1, 'line': 'Title R1 SECRET-R1-WORDS', 'state': 'open'}`. `GET /api/findings` and `list_open_findings` hide it from Dad and HOUSE and show it to Mom and Aunt. The Mind snapshot (`mind.snapshot()`) never contains `Title R1`.
- **R1 stalled past paging:** `watchers._thread_stalls(now)` makes no household Finding for R1, and `run_watchers` sends a DM only to Aunt (capture via `storage.get_or_create_dm` messages). A quiet R1 stall does nothing.
- **R4 waiting:** a DM to Mom and Dad.
- **R6 and R8 (subject-only):** today's household path (round 3's I3).
- **Pat:** never a recipient.
- **A creator-less mission** in Mom's private project: `missions._dm_person` sends a DM only to the parents who pass `record_visible`.
- **Round 3's M3:** a restricted item with no recipient does not refresh `at` on the next sweep.

- [ ] **Step 2: Run to verify they fail.** `python tests/test_access_matrix.py 4.8`.

- [ ] **Step 3: Implement** spec §4.8 bullet by bullet.
- **Finding reads:** every finding read filters with `finding_visible(f, viewer)` (viewer: the person, or HOUSE for the Mind and the wall).
- **Watcher collectors:** a collector checks `access.restricted(access.home_project(row))` first.
  - If restricted and the signal would DM on the household path (`dm=True` and paging severity), send a private DM to `private_recipients` through the existing watcher DM path with the same `watcher_notified` dedupe, and create no Finding.
  - If restricted and quiet, do nothing.
  - Otherwise, the old path.
- **`replies._recipients` and `missions._dm_person`** use `private_recipients` for restricted records, and `record_visible` filtering for the creator-less case.

- [ ] **Step 4: Run to verify, plus neighbours**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_access_matrix.py 4.8 && for t in test_watchers test_findings test_needs_you test_replies test_mind test_mind_endpoints test_watcher_policy; do [ -f tests/$t.py ] && python tests/$t.py 2>&1 | grep -E "^FAIL|passed" | head -3; done`
Expected: PASS.

- [ ] **Step 5: Hand off.** Remove `task10` from `PENDING`. Commit message: `fix(access): findings follow their source record, a private record's urgent signal goes privately to its people, and the Mind reads as the house (access rule Task 10) (v2.499.N)`.

---

### Task 11: Live proof, empty PENDING, whole-branch review, docs (Claude, then Codex review)

**Files:**
- Create: `chauffeur/tests/test_access_live.py` (restores the slice-2 scenario that the back-out removed, against the new rule).
- Modify: `chauffeur/tests/test_access_matrix.py` (assert `PENDING` is empty), `chauffeur/system_capabilities.md`, `chauffeur/config.yaml`.

- [ ] **Step 1: Write the live test**

Model it on `tests/project_sheets_fixture.py`, without importing `harness.py`. With a private thread R1 and program R3 in Mom's private project, it checks both deep-link forms (`projects?piece=thread:<id>` and `projects?id=<bath>&piece=…`) on the admin record sheet, and the phone's piece sheet via `chf-record-sheet-open`:
- **Dad:** sees "That isn't here, or isn't yours to see." and no title.
- **Mom:** the sheet opens with the title.

Allow only the expected 404 network log lines in `served.errors()`.

- [ ] **Step 2: Assert PENDING is empty**

```python
def scenario_nothing_pending():
    check(not pending_ids(), f'readers still pending: {sorted(map(str, pending_ids()))}')
```

- [ ] **Step 3: Run the whole access gate**

Run:
```bash
cd chauffeur && unset HA_BASE_URL
for t in test_access_core test_access_register test_access_matrix test_access_add_existing_removed test_access_conversations test_access_calendar test_access_live; do echo "== $t"; python tests/$t.py 2>&1 | grep -E "^(FAIL|PASS)|passed" | grep -v "^PASS" | head -5; done
```
Expected: no FAIL lines.

- [ ] **Step 4: Codex whole-branch adversarial review.** Dispatch through `/codex:rescue` with the spec, this plan, and the diff `git diff <Task 1 base>..HEAD`. Ask Codex to verify each finding against the code and to report severity, `path:line`, scenario and fix. Fix the findings with RED→GREEN tests (Claude writes the tests; small fixes can go to Codex), then re-run Step 3.

- [ ] **Step 5: Docs, bump, push**

- Add a top entry to `system_capabilities.md`: "BUILT, NOT device-verified: the project access rule …", covering:
  - the promise;
  - `services/access.py` and the register;
  - the three §10 removals in the user's words;
  - the conversation-per-surface change;
  - DEVICE STEPS:
    1. Rebuild.
    2. On the phone as Mom, start "a private surprise for Dad"; on Dad's phone, Projects, the Argyle DM, the wall and the calendar show nothing of it.
    3. The kitchen wall's Argyle bubble answers without private words.
    4. Mom's admin widget conversation is hers.
    5. A program with a target date makes no calendar event.

  Replace the NEXT line. Remove the "KNOWN LIMITATION" sentence from the slice-2 entry, and point it to this entry.
- Bump the version, then commit with `docs(access): the project access rule shipped …` and push.
- Update the memory `projects-arc.md` handoff paragraph.

---

## Self-review notes (writing-plans checklist)

1. **Spec coverage:**

   | Spec section | Task |
   |---|---|
   | §2 terms | 1 |
   | §3 rule | 1 |
   | §4 authentication-first | 3 (HOUSE only for identity-free callers; SIGNED_IN probes skip `house`) |
   | §4.1 | 3 |
   | §4.2 | 4 |
   | §4.3 | 5 |
   | §4.4 | 6 |
   | §4.5 | 7 |
   | §4.6 | 8 |
   | §4.7 | 9 |
   | §4.8 | 10 |
   | §5 `access.py` / caching / helpers / `READERS` | 1, with the `batch()` ruling |
   | §6 fixture, matrix, register, live | 1 and 11 |
   | §7 cells | 1 (`TABLE`, `ACT` in 3) and per-class probes in 3–10 |
   | §8 split | Task headers |
   | §10.1 | 2 |
   | §10.2 | 4 |
   | §10.3 | 9 |

2. **Deviations, each stated in its task:**
   - Caching is an explicit `access.batch()` on list calls, not request-wide middleware. A request-wide cache would serve a stale project row to a write route that changes the project and reads it back.
   - Schedule restore is subsumed by read-time redaction.
   - The register classifies keyword-selected routes and tools, with broadened keywords, not literally every route. This is spec §5's stated limit made concrete.

   The user sees these at review.

3. **Placeholder scan:** the `v2.499.N` in commit messages is the next patch number at commit time (Claude bumps it). That is not a placeholder for content. Probe bodies for the many write routes in Task 3 are specified by one rule (POST minimal body, 2xx is accepted, 404 is hidden, 403 is a defect) and an `ACT` table, not repeated per route.

4. **Type consistency:** `record_view` / `KEEPER` / `FULL` / `HOUSE` / `HOUSE_PARENT` / `NOT_A_CHANNEL` / `batch` / `mission_reader` / `mission_view` / `channel_view` / `conversation_view` / `shared_screen_visible` / `schedule_view` / `neutral_practice` / `finding_visible` / `private_recipients` are each defined in exactly one task and used with the same signature after it.
