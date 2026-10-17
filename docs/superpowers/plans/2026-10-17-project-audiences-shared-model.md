# Project Audiences on the Shared Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project's own audience (household / parents / shared / private with a `shared_with` list, read through `scope.audience_allows`) decides who sees it; wrapper projects stop borrowing their record's visibility live.

**Architecture:** `projects.can_see` becomes "owner, or `scope.audience_allows(project, 'project', viewer)`". One validator, `projects.normalize_audience`, shapes every write; a separate edit authority (`projects.can_edit_audience`) guards audience, list and owner. A one-time migration converts every row (wrappers through the same derivation new records use), stamped per row with `audience_rev: 2`; binding a subject onto a wrapped record narrows its wrapper once; then `_wrapped_visible` is deleted. The people picker is extracted from the shopping share popover into one component used by lists and projects.

**Tech Stack:** Python 3.14, FastAPI (`chauffeur/main.py`), TinyDB-shaped storage over SQLite (`services/storage.py`), plain-script tests from `chauffeur/` (`python tests/test_x.py`), Alpine.js templates, Playwright live tests.

**Spec:** `docs/superpowers/specs/2026-10-16-project-audiences-shared-model-design.md` rev 3 (rev 2 approved 2026-10-17; rev 3 section 3 per the user's ruling that wrappers are test data, option A). Read it before any task: §1 meaning, §2 writing and edit authority, §3 migration, §4 readers, §5 UI.

## Global Constraints

- **Running tests:** from `chauffeur/`, `HA_BASE_URL` unset (`unset HA_BASE_URL` in Bash). Run the task's own tests plus the named neighbours. Never the whole suite.
- **Fixture data only:** tests isolate storage through `tests/harness.py` or a module that imports it. A live test that needs auth enforcement must not import `harness.py`.
- **Audience values:** exactly `household`, `parents`, `shared`, `private`. Refusal text: "Choose household, parents, shared or private".
- **Body goal pin:** `private`, `shared_with == [owner]`, adult owner. Refusal text unchanged: "A body goal must belong to an adult and stay private".
- **Edit authority refusal text:** "Only the owner or a parent can change who sees this project".
- **Hidden means** a 404 shaped like a missing record, a dropped row, "Busy" on calendar surfaces, no DM.
- **Never pass `None` as a viewer** to `access`; house readers use `access.HOUSE` / `HOUSE_PARENT`.
- **No browser dialogs.** `showGlobalAlert`, `promptConfirm`, `promptInput` only.
- **Tailwind is precompiled:** after any template class change run `python tools/build_tailwind.py` from the repo root.
- **Do not push between Task 2 and Task 3.** Task 2 makes legacy rows read under the new rule before the migration exists; Task 3 converts them. Push only after Task 3's gate is green.
- **Codex tasks** (2, 3, 4) leave changes in the working tree and never bump `chauffeur/config.yaml` or commit (AGENTS.md). Claude reviews, runs the gate, bumps the patch version (v2.499.N) and commits with the version in the subject and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Reviews cross models:** Codex-built tasks are reviewed by Claude; Claude-built tasks (1, 5) are reviewed by Codex (`codex-companion.mjs task --model gpt-6.1-sol --effort high`, read-only).
- **PowerShell:** no double quotes in commit messages; use the Bash tool for git.

## Review Focus

1. **A member is archived or disabled while on a `shared_with` list.** They must see nothing, and the list must not error or show their name as a live member. Pinned in Task 1 `scenario_inactive_member_on_list`.
2. **The owner changes to someone outside a private list.** The new owner sees the project at once; the old owner stays on the list only if they were already listed. Pinned in Task 1 `scenario_owner_change_adds_new_owner`.
3. **A project PATCH that only renames.** It must not trip the edit-authority check or reshape the list (a listed adult renames freely). Pinned in Task 1 `scenario_listed_adult_renames_but_cannot_widen`.
4. **The migration crashes halfway and restarts.** Converted rows are left alone (a parent removed since stays removed); unconverted rows convert from legacy visibility. Pinned in Task 1 `scenario_interrupted_migration_resumes`.
5. **A record whose subject is its own wrapper project.** The derivation must not recurse forever and must not widen. Pinned in Task 1 `scenario_wrapper_whose_record_names_it`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `chauffeur/tests/test_project_audience_model.py` (new) | Model cells, normalize, edit authority, plans, recipients | 1 |
| `chauffeur/tests/test_project_audience_migration.py` (new) | Migration and live adopt derivation | 1 |
| `chauffeur/tests/access_fixture.py`, `access_signed_in.py` | New `shared` project and Kate's private-without-Dad project, expected cells | 1 |
| `chauffeur/services/scope.py` | `AUDIENCE_DEFAULTS['project']` | 2 |
| `chauffeur/services/projects.py` | `can_see`, `normalize_audience`, `can_edit_audience`, `update`, `prepare_create`, labels, `card`/`view` payload | 2; 3 (adopt, delete `_wrapped_visible`) |
| `chauffeur/services/project_audience.py` (new) | Frozen legacy visibility, `audience_from_set`, `derive_for_record`, `convert_all` | 3 |
| `chauffeur/services/access.py` | child-private bypass rule (2), `restricted`/`project_visible` wrapper branches removed (3), `private_recipients` (4) | 2, 3, 4 |
| `chauffeur/services/planned.py` | carry `shared_with` | 2 |
| `chauffeur/services/replies.py` | refuse a None projection | 4 |
| `chauffeur/services/home_board.py` | digest adds `shared_with` | 2 |
| `chauffeur/services/access_readers.py` | explicit PATCH row | 2 |
| `chauffeur/services/migrations.py` | `migrate_project_audiences_v2499` after the adopt migration | 3 |
| `chauffeur/templates/components/audience_picker.html` (new) | The one people picker | 5 |
| `chauffeur/templates/shopping.html`, `components/projects_page.html`, `app.html` | Use the picker | 5 |
| `chauffeur/tests/test_audience_picker_live.py` (new) | Shopping popover unchanged + project picker + chat card | 5 |

---

### Task 1 (Claude): the tests

**Files:**
- Create: `chauffeur/tests/test_project_audience_model.py`, `chauffeur/tests/test_project_audience_migration.py`
- Modify: `chauffeur/tests/access_fixture.py`, `chauffeur/tests/access_signed_in.py`, `chauffeur/tests/test_projects.py:61-71`, `chauffeur/tests/test_front_door_audience.py:17-36`, `chauffeur/tests/test_project_adopt.py:147-158`

**Interfaces (produced, implemented by Tasks 2-4):**
- `projects.normalize_audience(row: dict, list_given: bool) -> str | None` mutates `row['audience']`, `row['shared_with']`; returns an error message or None.
- `projects.can_edit_audience(project: dict, viewer: dict) -> bool`
- `projects.card(...)` and `projects.view(...)` include `shared_with` (list of `{'id','name'}`), `can_edit_audience`, `body_goal`.
- `project_audience.audience_from_set(viewer_ids: set, owner_id: str, house_ok: bool) -> (audience, shared_with)`
- `project_audience.convert_all() -> {'converted': int, 'skipped': int}`; rows get `audience_rev: 2`.
- `project_audience.derive_for_record(kind, row, base_audience, owner_id) -> (owner_id, audience, shared_with)`
- `access.private_recipients(kind, row) -> list[str]` (filtered to active members with a non-None `record_view`).

- [ ] **Step 1: Write `test_project_audience_model.py`**

```python
"""Project audiences on the shared model (spec 2026-10-16-project-audiences-shared-model-design.md).

Run from chauffeur/:  python tests/test_project_audience_model.py
"""
from harness import check  # noqa: F401
from services import storage, access
from test_projects import _fresh, _make, _p
from test_subjects import MOM, DAD, AUNT, KID

HAL = {'id': 'hal', 'name': 'Hal', 'role': 'helper'}
SIB = {'id': 'sib', 'name': 'Sam', 'role': 'child', 'is_child': True}


def _seed_extra():
    for m in (HAL, SIB):
        storage.add_member(dict(m))


def _seen(project, members=(MOM, DAD, AUNT, KID, HAL, SIB)):
    project = storage.get_project(project['id'])
    return {m['id'] for m in members if _p().can_see(project, dict(m))}


def scenario_each_value():
    _fresh(); _seed_extra()
    house = _make('mom', MOM, title='Garage', audience='household')
    parents = _make('aunt', AUNT, title='Aunt plan', audience='parents')
    shared = _make('mom', MOM, title='Party', audience='shared', shared_with=['aunt'])
    private = _make('mom', MOM, title='Mine', audience='private', shared_with=['kid'])
    check(_seen(house) == {'mom', 'dad', 'aunt', 'kid', 'hal', 'sib'}, f"household: everyone {_seen(house)}")
    check(_seen(parents) == {'mom', 'dad', 'aunt'}, f"parents: the parents and the owner {_seen(parents)}")
    check(_seen(shared) == {'mom', 'dad', 'aunt'}, f"shared: parents, owner, list {_seen(shared)}")
    check(_seen(private) == {'mom', 'kid'}, f"private: exactly the list, owner added {_seen(private)}")
    for p, ok in ((house, True), (parents, False), (shared, False), (private, False)):
        check(access.project_visible(storage.get_project(p['id']), access.HOUSE) is ok, f"house reader: {p['title']}")


def scenario_child_private_defaults_and_explicit_list():
    _fresh()
    implicit = _make('kid', KID, title='Diary', audience='private')
    check(_seen(implicit) == {'kid', 'mom', 'dad'}, f"a child's private with no list: child + parents {_seen(implicit)}")
    surprise = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['mom'])
    check(_seen(surprise) == {'kid', 'mom'}, f"a child's explicit list leaves Dad out {_seen(surprise)}")
    adult = _make('mom', MOM, title='Mine', audience='private')
    check(_seen(adult) == {'mom'}, "an adult's private with no list: the owner")


def scenario_normalize():
    _fresh(); _seed_extra()
    storage.update_member('hal', {'status': 'archived'})
    p = _make('mom', MOM, title='Party', audience='shared', shared_with=['aunt', 'aunt', 'ghost', 'hal'])
    check(p['shared_with'] == ['aunt'], f"filtered and de-duplicated: {p['shared_with']}")
    empty = _make('mom', MOM, title='Empty share', audience='shared', shared_with=['ghost'])
    check(empty['audience'] == 'parents' and empty['shared_with'] == [], f"empty shared becomes parents: {empty}")
    hh = _make('mom', MOM, title='House', audience='household', shared_with=['aunt'])
    check(hh['shared_with'] == [], "household clears the list")
    bad = _p().create({'title': 'x', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'mom', 'audience': 'family'}, dict(MOM))
    check(bad['status'] == 'error' and bad['message'] == 'Choose household, parents, shared or private', f"{bad}")


def scenario_body_goal_pin():
    _fresh()
    p = _make('mom', MOM, title='Reach 70 kg', audience='private')
    check(p['body_goal'] and p['shared_with'] == ['mom'], f"body goal: private to the owner {p}")
    for patch in ({'audience': 'household'}, {'audience': 'private', 'shared_with': ['mom', 'dad']}):
        res = _p().update(p['id'], patch, dict(MOM))
        check(res['status'] == 'error' and 'body goal' in res['message'], f"pin holds against {patch}: {res}")


def scenario_listed_adult_renames_but_cannot_widen():
    _fresh()
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    res = _p().update(p['id'], {'title': 'Party v2'}, dict(AUNT))
    check(res['status'] == 'success', f"a listed adult renames: {res}")
    for patch in ({'audience': 'household'}, {'shared_with': ['aunt', 'dad']}, {'owner_member_id': 'aunt'}):
        res = _p().update(p['id'], patch, dict(AUNT))
        check(res['status'] == 'error' and res['message'] == 'Only the owner or a parent can change who sees this project',
              f"a listed adult cannot {patch}: {res}")
    check(not _p().can_edit_audience(storage.get_project(p['id']), dict(AUNT)), "no audience edit for Aunt")
    check(_p().can_edit_audience(storage.get_project(p['id']), dict(MOM)), "the owner edits")


def scenario_two_request_escalation_refused():
    _fresh()
    p = _make('mom', MOM, title='Shared', audience='shared', shared_with=['aunt'])
    take = _p().update(p['id'], {'owner_member_id': 'aunt'}, dict(AUNT))
    widen = _p().update(p['id'], {'audience': 'household'}, dict(AUNT))
    check(take['status'] == 'error' and widen['status'] == 'error', f"no take-then-widen: {take} {widen}")
    check(storage.get_project(p['id'])['audience'] == 'shared', "still shared")


def scenario_owner_change_adds_new_owner():
    _fresh()
    p = _make('mom', MOM, title='Mine', audience='private')
    res = _p().update(p['id'], {'owner_member_id': 'dad'}, dict(MOM))
    row = storage.get_project(p['id'])
    check(res['status'] == 'success' and 'dad' in row['shared_with'], f"the new owner is listed: {row}")


def scenario_inactive_member_on_list():
    _fresh()
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    storage.update_member('aunt', {'status': 'disabled'})
    check('aunt' not in _seen(p, (MOM, DAD, {**AUNT, 'status': 'disabled'})), "a disabled member sees nothing")
    v = _p().view(storage.get_project(p['id']), dict(MOM))
    check(all(e['id'] != 'aunt' for e in v['shared_with']), f"a disabled member is not shown as listed: {v['shared_with']}")


def scenario_payloads():
    _fresh()
    p = _make('mom', MOM, title='Party', audience='private', shared_with=['aunt'])
    row = storage.get_project(p['id'])
    card = _p().card(row, dict(AUNT))
    check(card['can_edit_audience'] is False and card['body_goal'] is False
          and {'id': 'aunt', 'name': 'Aunt Jo'} in card['shared_with'], f"card: {card}")
    view = _p().view(row, dict(MOM))
    check(view['can_edit_audience'] is True and 'body_goal' in view, f"view: {view}")


def scenario_child_private_list_beats_parent_bypass():
    from services import threads
    _fresh()
    p = _make('kid', KID, title='Dad surprise', audience='private', shared_with=['mom'])
    tid = threads.create(title='Gift ideas', owner_member_id='kid', created_by='kid', project_id=p['id'])
    row = storage.get_thread(tid)
    check(access.record_view('thread', row, dict(DAD)) is None, "Dad, left off Kate's list, sees none of its records")
    check(access.record_view('thread', row, dict(MOM)) == access.FULL, "Mom, listed, does")
    check('dad' not in access.private_recipients('thread', row), "Dad gets no DM")


def scenario_recipients_union_and_filter():
    from services import threads
    _fresh(); _seed_extra()
    p = _make('mom', MOM, title='Mine', audience='private', shared_with=['hal'])
    tid = threads.create(title='Quotes', owner_member_id='aunt', created_by='mom', project_id=p['id'])
    got = access.private_recipients('thread', storage.get_thread(tid))
    check('aunt' in got, f"the keeper keeps their notices: {got}")
    check('hal' not in got, f"a listed helper who cannot read the thread gets nothing: {got}")
    check('mom' in got and 'dad' not in got, f"the list, not the parents: {got}")


def scenario_plan_carries_the_list():
    from services import planned
    check('shared_with' in planned.RESHAPE, "plan reshape carries the list")
    _fresh()
    shaped, err = planned._project_for_plan({'id': 'm1', 'subject_kind': None}, {
        'title': 'Party', 'goal': 'g', 'done_when': 'd', 'owner': 'mom',
        'audience': 'private', 'shared_with': ['aunt']}, dict(MOM))
    check(err is None and set(shaped['shared_with']) == {'aunt', 'mom'},
          f"a proposed list survives into the approval shape: {shaped} {err}")


def scenario_patch_route_registered():
    from services import access_readers
    rows = [r for r in access_readers.READERS if r[0][1] == 'PATCH' and r[0][2] == '/api/projects/{project_id}']
    check(rows and rows[0][1] == '4.1-signed-in', f"PATCH /api/projects/{{id}} has its own row: {rows}")


if __name__ == '__main__':
    import sys
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            fn()
            print('ok', name)
    sys.exit(0)
```

- [ ] **Step 2: Write `test_project_audience_migration.py`**

```python
"""The project audience migration and live adopt derivation (spec §3).

Run from chauffeur/:  python tests/test_project_audience_migration.py
"""
from harness import check  # noqa: F401
from services import storage, access
from test_projects import _fresh, _p
from test_subjects import MOM, DAD, AUNT, KID


def _legacy(owner, audience, title='Legacy', **extra):
    """A row exactly as the old code stored it (no audience_rev, no shared_with)."""
    return storage.add_project({'title': title, 'goal': 'g', 'done_when': 'd', 'owner_member_id': owner,
                                'audience': audience, 'state': 'active', 'steps': [], 'pieces': [],
                                'created_by': owner, 'body_goal': False, **extra})


def _seen(pid, members=(MOM, DAD, AUNT, KID)):
    row = storage.get_project(pid)
    return {m['id'] for m in members if _p().can_see(row, dict(m))}


def _convert():
    from services import project_audience
    return project_audience.convert_all()


def scenario_plain_rows():
    _fresh()
    hh, par = _legacy('mom', 'household'), _legacy('mom', 'parents')
    adult, child = _legacy('mom', 'private'), _legacy('kid', 'private')
    body = _legacy('mom', 'private', title='Reach 70 kg', body_goal=True)
    _convert()
    check(storage.get_project(hh)['audience'] == 'household' and storage.get_project(par)['audience'] == 'parents', "unchanged")
    check(storage.get_project(adult)['shared_with'] == ['mom'], "adult private: the owner")
    check(set(storage.get_project(child)['shared_with']) == {'kid', 'mom', 'dad'}, "child private: the child and the parents")
    check(storage.get_project(body)['shared_with'] == ['mom'], "body goal first")
    check(all(storage.get_project(p).get('audience_rev') == 2 for p in (hh, par, adult, child, body)), "every row stamped")


def _wrapped_thread(owner, **thread_fields):
    from services import threads
    tid = threads.create(title='Wrapped', owner_member_id=owner, created_by=owner or 'mom', **thread_fields)
    return tid, storage.get_thread(tid)['project_id']


def _make_legacy(pid, audience='parents', **extra):
    """Put a wrapper back in the shape the old adopt stored (front door slice 1)."""
    storage.update_project(pid, {'audience': audience, 'shared_with': None, 'audience_rev': None, **extra})


def scenario_wrapper_keeps_todays_exact_set():
    _fresh()
    tid, pid = _wrapped_thread('dad')
    _make_legacy(pid)   # legacy: Aunt reads Dad's thread but not its parents wrapper; Kate reads neither
    _convert()
    check(_seen(pid) == {'mom', 'dad'}, f"today's exact set, no widening: {_seen(pid)}")


def scenario_subject_restricted_owner_moves():
    _fresh()
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-dad')
    _make_legacy(pid, owner_member_id='dad')
    _convert()
    row = storage.get_project(pid)
    check(row['owner_member_id'] != 'dad' and 'dad' not in _seen(pid), f"a hidden owner hands over: {row}")


def scenario_empty_set_goes_untitled():
    _fresh()
    storage.save_occasion({'id': 'occ-nobody', 'title': 'x', 'audience': 'private', 'shared_with': ['ghost']})
    tid, pid = _wrapped_thread('', subject_kind='occasion', subject_id='occ-nobody')
    _make_legacy(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['title'] == 'Untitled project' and row['goal'] == '' and row['audience'] == 'private', f"{row}")


def scenario_missing_record_wrapper():
    _fresh()
    tid, pid = _wrapped_thread('mom')
    storage.delete_thread(tid)
    _make_legacy(pid)
    _convert()
    row = storage.get_project(pid)
    check(row['audience'] == 'private' and row['shared_with'] == [row['owner_member_id']], f"{row}")


def scenario_household_promotion_needs_legacy_household():
    _fresh()
    tid, pid = _wrapped_thread('kid')
    _make_legacy(pid)
    _convert()
    check(storage.get_project(pid)['audience'] != 'household', "a parents wrapper never becomes household")


def scenario_interrupted_migration_resumes():
    _fresh()
    a, b = _legacy('kid', 'private', title='A'), _legacy('kid', 'private', title='B')
    _convert()
    storage.update_project(a, {'shared_with': ['kid', 'mom']})            # Kate took Dad off since
    storage.update_project(b, {'audience_rev': None, 'shared_with': None})  # never converted
    _convert()
    check(storage.get_project(a)['shared_with'] == ['kid', 'mom'], "a converted row is left alone")
    check(set(storage.get_project(b)['shared_with']) == {'kid', 'mom', 'dad'}, "the rest converts")
    check(_convert()['converted'] == 0, "a second run is a no-op")


def scenario_wrapper_whose_record_names_it():
    _fresh()
    tid, pid = _wrapped_thread('mom')
    storage.update_thread(tid, {'subject_kind': 'project', 'subject_id': pid})
    _make_legacy(pid)
    _convert()   # must terminate
    check('aunt' not in _seen(pid), "no widening through a self-reference")


def scenario_deleting_the_record_changes_nobody():
    _fresh()
    tid, pid = _wrapped_thread('dad')
    _convert()
    before = _seen(pid)
    storage.delete_thread(tid)
    check(_seen(pid) == before, f"the project keeps its audience: {before} -> {_seen(pid)}")


def scenario_new_wrapper_derives_live():
    _fresh()
    storage.save_occasion({'id': 'occ-dad', 'title': 'Dad surprise', 'audience': 'private', 'shared_with': ['mom', 'kid']})
    tid, pid = _wrapped_thread('kid', subject_kind='occasion', subject_id='occ-dad')
    row = storage.get_project(pid)
    check(row.get('audience_rev') == 2 and 'dad' not in _seen(pid), f"a new wrapper is born converted and narrow: {row}")


if __name__ == '__main__':
    import sys
    for name, fn in list(globals().items()):
        if name.startswith('scenario_'):
            fn()
            print('ok', name)
    sys.exit(0)
```

- [ ] **Step 3: Extend the access fixture.** In `tests/access_fixture.py` `build()`, after `kate_private`:

```python
    mom_shared = _project('shared', 'mom', 'Mom shared')
    storage.update_project(mom_shared['id'], {'shared_with': ['aunt']})
    kate_no_dad = projects.create({'title': 'Kate no Dad', 'goal': 'g', 'done_when': 'd', 'owner_member_id': 'kid',
                                   'audience': 'private', 'shared_with': ['kid', 'mom']}, dict(KID))['project']
    fx.projects.update(mom_shared=mom_shared, kate_no_dad=kate_no_dad)
    _thread(fx, 'R14', 'kid', kate_no_dad)
    _program(fx, 'R15', 'kid', kate_no_dad)
    _thread(fx, 'R16', 'mom', mom_shared)
```

In `tests/access_signed_in.py`, add expected cells: R14 and R15 are FULL for kid and mom, None for dad, aunt, hal, sib, house (R15 keeper view for kid); R16 FULL for mom, dad, aunt; None for kid, hal, sib, house. Update `kate_private` (R11 row, :76-89): unchanged (a no-list child private keeps both parents). Update the house cells for adults-only wrappers (R13): `house` no longer sees R13's wrapper project.

- [ ] **Step 4: Update the pinned tests, without weakening.**
  - `test_projects.py:66`: `"a child's project is never private from their parents"` becomes `"a child's private with no list includes both parents"`; add one line asserting an explicit `shared_with=['kid','mom']` hides it from Dad.
  - `test_front_door_audience.py:17-36` and `test_project_adopt.py:147-158`: replace "the wrapper is narrowed by its record now" with "the wrapper is born with its derived audience; a later subject change on the record does not change it"; keep every negative (who must NOT see) assertion.

- [ ] **Step 5: Run and confirm red.**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_audience_model.py; python tests/test_project_audience_migration.py`
Expected: FAIL (`normalize_audience`/`can_edit_audience`/`project_audience` missing).

- [ ] **Step 6: Commit the red tests** (they are not in any gate yet).

```bash
git add chauffeur/tests && git commit -m "test(projects): audience model and migration contract, red (v2.499.N)"
```

---

### Task 2 (Codex): the model, normalize, edit authority, payloads, plans

**Files:** Modify `services/scope.py:583-591`, `services/projects.py:12-14, 67-82, 94-182, 913-940, 1059-1062`, `services/access.py:120-126, 182-199`, `services/planned.py:257, 281-294, 746-751`, `services/home_board.py:5334`, `services/access_readers.py` (PATCH row before the `/api/projects` prefix row at :341).

**Interfaces:** produces everything in Task 1's list except `project_audience.*` and `private_recipients`.

- [ ] **Step 1: scope default.** `AUDIENCE_DEFAULTS['project'] = 'private'`.

- [ ] **Step 2: projects.py constants and `can_see`.**

```python
AUDIENCES = ('household', 'parents', 'shared', 'private')
EDITABLE = ('title', 'goal', 'done_when', 'owner_member_id', 'audience', 'shared_with', 'target_date')
AUDIENCE_KEYS = ('audience', 'shared_with', 'owner_member_id')


def can_see(project, viewer):
    """The owner always; anyone else by the shared audience model (scope.audience_allows)."""
    if not project or not _active(viewer):
        return False
    if project.get('wrapped_from') and project.get('audience_rev') != 2 and not _wrapped_visible(project, viewer):
        return False   # removed in Task 3 with the migration
    if viewer['id'] == project.get('owner_member_id'):
        return True
    from services import scope
    return scope.audience_allows(project, 'project', viewer)


def can_edit_audience(project, viewer):
    return bool(can_see(project, viewer) and (viewer['id'] == project.get('owner_member_id') or _parent(viewer)))
```

- [ ] **Step 3: `normalize_audience`, called from `_validate`'s callers before `_validate`.**

```python
def _listable(mid):
    m = storage.get_member(mid) if isinstance(mid, str) else None
    return bool(m and not m.get('system') and mid != 'argyle' and (m.get('status') or 'active') != 'archived')


def normalize_audience(row, list_given):
    """Shape audience + shared_with in place (spec §2); return an error message or None."""
    audience = row.get('audience')
    if audience not in AUDIENCES:
        return 'Choose household, parents, shared or private'
    owner_id = row.get('owner_member_id')
    owner = storage.get_member(owner_id) or {}
    ids = []
    for mid in (row.get('shared_with') or []) if list_given else []:
        if _listable(mid) and mid not in ids:
            ids.append(mid)
    if audience in ('household', 'parents'):
        ids = []
    elif audience == 'private':
        if not list_given:
            ids = [owner_id] + ([m['id'] for m in storage.get_all_members() if _parent(m) and _active(m)]
                                if _child(owner) else [])
        if owner_id not in ids:
            ids.insert(0, owner_id)
    elif audience == 'shared' and not ids:
        audience = 'parents'
    row['audience'], row['shared_with'] = audience, list(dict.fromkeys(ids))
    return None
```

`_validate` drops its audience check (normalize owns it) and keeps the body-goal check, now: `row.get('body_goal') and (_child(owner) or row['audience'] != 'private' or row.get('shared_with') != [row['owner_member_id']])`.

- [ ] **Step 4: `prepare_create`.** After `row.setdefault('audience', ...)` (unchanged defaults), call `normalize_audience(row, 'shared_with' in fields)` and return its error. Stamp `row['audience_rev'] = 2`.

- [ ] **Step 5: `update` with edit authority.**

```python
        patch = {key: fields[key] for key in EDITABLE if key in fields}
        touches = any(k in patch and patch[k] != project.get(k) for k in AUDIENCE_KEYS)
        if touches and not can_edit_audience(project, actor):
            return _error('Only the owner or a parent can change who sees this project')
        proposed = {**project, **patch}
        list_given = 'shared_with' in patch or (proposed.get('audience') == project.get('audience')
                                                 and project.get('audience_rev') == 2)
        message = normalize_audience(proposed, list_given)
        if message:
            return _error(message)
        if proposed['owner_member_id'] != project['owner_member_id'] and proposed['audience'] in ('private', 'shared') \
                and proposed['owner_member_id'] not in proposed['shared_with']:
            proposed['shared_with'].append(proposed['owner_member_id'])
        patch.update(audience=proposed['audience'], shared_with=proposed['shared_with'], audience_rev=2)
```

then the existing `_classify`/`_validate`/owner-assignment checks run on `proposed` as today.

- [ ] **Step 6: labels and payloads.**

```python
AUDIENCE_LABEL = {'private': 'Private', 'parents': 'Parents', 'shared': 'Parents and chosen people',
                  'household': 'Household'}


def audience_label(project):
    names = [n for n in (_listed(project)) if n['id'] != project.get('owner_member_id')]
    if project.get('audience') == 'private' and names:
        return 'Only ' + ', '.join([ (storage.get_member(project['owner_member_id']) or {}).get('name') or 'the owner']
                                   + [n['name'] for n in names])
    return AUDIENCE_LABEL.get(project.get('audience'), '')


def _listed(project):
    out = []
    for mid in project.get('shared_with') or []:
        m = storage.get_member(mid)
        if _active(m or {}):
            out.append({'id': mid, 'name': m.get('name') or ''})
    return out
```

`card()` uses `audience_label(project)`, adds `'shared_with': _listed(project)`, `'can_edit_audience': can_edit_audience(project, viewer)`. `view()` adds `audience_label`, `shared_with`, `can_edit_audience`, `body_goal`.

- [ ] **Step 7: access bypass rule** (`access.record_view`).

```python
def _child_private_list(home, kind, row):
    """A child's own private list decides who of the parents sees its records (audience spec §1)."""
    return bool(home and home.get('audience') == 'private'
                and home.get('owner_member_id') and home.get('owner_member_id') == keeper_id(kind, row))
...
    layer_ok = (skip_project or not restricted(home)
                or (_parent_of_child_keeper(kind, row, viewer) and not _child_private_list(home, kind, row))
                or project_visible(home, viewer))
```

- [ ] **Step 8: plans carry the list.** `RESHAPE` adds `'shared_with'`; in the proposal whitelist (:746-751) the non-existing keys tuple adds `'shared_with'`; `_project_for_plan` passes `shared_with` through `EDITABLE` (already, after Step 2).

- [ ] **Step 9: digest and register.** `home_board._access_input_digest` project fields add `'shared_with', 'audience_rev'`. `access_readers.READERS` gains, above the prefix row:

```python
    ((R, 'PATCH', '/api/projects/{project_id}'), '4.1-signed-in', (), 'projects.can_act; projects.can_edit_audience'),
```

- [ ] **Step 10: run.** `python tests/test_project_audience_model.py` (all except `scenario_recipients_union_and_filter`, Task 4), `test_projects.py`, `test_project_private.py`, `test_body_goal.py`, `test_projects_audience.py`, `test_access_register.py`, `test_audience.py`, `test_scope.py`, `test_subject_audience.py`, `test_project_kid.py`, `test_front_door_chat.py`, `test_start_mission.py`. Expected: PASS. Leave changes uncommitted; Claude reviews, gates, bumps, commits (not pushed).

---

### Task 3 (Codex): migration, live derivation, delete the wrapper path

**Files:** Create `services/project_audience.py`. Modify `services/projects.py` (`_wrapper_fields`, `adopt`, delete `_wrapped_visible`, `_GATE`, the Task 2 wrapper clause in `can_see`), `services/access.py:141-158` (`restricted`, `project_visible`), `services/migrations.py` (new function after `migrate_projects_adopt_v2499517`, registered after it at :583).

- [ ] **Step 1: `project_audience.py`** (spec §3 rev 3: no legacy snapshot; existing wrappers are test data).

```python
"""Project audiences on the shared model: wrapper derivation and the one-time conversion (spec §3 rev 3)."""
from services import storage

REV = 2


def _sees(kind, row, member):
    from services import access
    return access.record_view(kind, row, member, skip_project=True) is not None


def audience_from_set(viewer_ids, owner_id):
    from services import projects
    members = [m for m in storage.get_all_members() if projects._active(m)]
    parents = {m['id'] for m in members if projects._parent(m)}
    ids = set(viewer_ids) | ({owner_id} if owner_id else set())
    if parents <= ids:
        rest = sorted(ids - parents - {owner_id})
        return ('shared', rest) if rest else ('parents', [])
    return 'private', [owner_id] + sorted(ids - {owner_id})


def _new_owner(kind, row, viewer_ids):
    from services import access, projects
    keeper = access.keeper_id(kind, row) if row else None
    if keeper in viewer_ids:
        return keeper
    members = [m for m in storage.get_all_members() if projects._active(m) and m['id'] in viewer_ids]
    for test in (projects._parent, lambda m: m.get('role') == 'adult'):
        for m in members:
            if test(m):
                return m['id']
    return None


def derive_for_record(kind, row, owner_id):
    """(owner_id, audience, shared_with, retitle) for a wrapper around this record."""
    from services import access, projects
    if row is None:
        return owner_id, 'private', [owner_id], False
    members = [m for m in storage.get_all_members() if projects._active(m)]
    grown = [m for m in members if projects._parent(m) or (m.get('role') == 'adult' and not projects._child(m))]
    if _sees(kind, row, access.HOUSE) and all(_sees(kind, row, m) for m in grown):
        return owner_id, 'household', [], False
    seen = {m['id'] for m in members if _sees(kind, row, m)}
    if owner_id not in seen:
        new = _new_owner(kind, row, seen)
        if not new:
            return owner_id, 'private', [owner_id], True
        owner_id = new
    audience, rest = audience_from_set(seen, owner_id)
    return owner_id, audience, rest, False


def _convert(project):
    from services import projects
    owner = project.get('owner_member_id')
    if project.get('body_goal'):
        return {'audience': 'private', 'shared_with': [owner]}
    src = project.get('wrapped_from') or {}
    if src.get('kind') in projects._ADOPT_TABLES and src.get('id'):
        record = projects._ADOPT_TABLES[src['kind']][0](src['id'])
        new_owner, audience, rest, retitle = derive_for_record(src['kind'], record, owner)
        patch = {'owner_member_id': new_owner, 'audience': audience, 'shared_with': rest}
        if retitle:
            patch.update(title='Untitled project', goal='')
        return patch
    row = {'audience': project.get('audience') if project.get('audience') in projects.AUDIENCES else 'private',
           'owner_member_id': owner, 'shared_with': None}
    projects.normalize_audience(row, False)
    return {'audience': row['audience'], 'shared_with': row['shared_with']}


def convert_all():
    with storage.db_lock:
        rows = [p for p in storage.get_projects() if p.get('audience_rev') != REV]
        for p in rows:
            storage.update_project(p['id'], {**_convert(p), 'audience_rev': REV})
        return {'converted': len(rows), 'skipped': 0}


def narrow_on_bind(kind, row):
    """A wrapped record got a new subject: narrow its wrapper once, never widen (spec §3 'Binding narrows once')."""
    from services import projects
    project = storage.get_project((row or {}).get('project_id'))
    if not project or not project.get('wrapped_from') or project.get('body_goal'):
        return
    new_owner, audience, rest, _ = derive_for_record(kind, row, project.get('owner_member_id'))
    candidate = {**project, 'owner_member_id': new_owner, 'audience': audience, 'shared_with': rest}
    members = [m for m in storage.get_all_members() if projects._active(m)]
    now = {m['id'] for m in members if projects.can_see(project, m)}
    after = {m['id'] for m in members if projects.can_see(candidate, m)}
    if after < now:
        storage.update_project(project['id'], {'owner_member_id': new_owner, 'audience': audience,
                                               'shared_with': rest, 'audience_rev': REV})
```

`narrow_on_bind` is called after every write that sets `subject_kind`/`subject_id`/`subject_history` on a thread, mission or program (find the writers with `grep -n "subject_kind" services/*.py main.py`: subject binding, thread/mission/program updates, plan bindings in `planned.py`).

`access.project_visible` for house readers: `HOUSE` passes `household` only; `HOUSE_PARENT` (the mission engine acting for the parent of record) passes `household`, `parents` and `shared`, never a `private` list.

- [ ] **Step 2: adopt uses `derive_for_record`.** In `projects.adopt`, after `fields = _wrapper_fields(...)`, replace the audience with the derived one and pass the list explicitly:

```python
            owner_id, audience, listed, retitle = project_audience.derive_for_record(kind, row, fields['owner_member_id'])
            fields.update(owner_member_id=owner_id, audience=audience, shared_with=listed)
            if retitle:
                fields.update(title='Untitled project', goal='')
```

- [ ] **Step 3: delete the wrapper visibility path.** Remove `_wrapped_visible`, `_GATE`, the wrapper clause in `can_see`; `access.restricted` becomes `bool(project) and project.get('audience') != 'household'`; `access.project_visible` for house readers follows Step 1's HOUSE / HOUSE_PARENT rule.

- [ ] **Step 4: migration.** In `services/migrations.py`:

```python
def migrate_project_audiences_v2499():
    """Audience spec §3: every project onto the shared model, once per row."""
    from services import project_audience
    out = project_audience.convert_all()
    if out['converted']:
        logger.info(f"[migrations] project audiences converted: {out}")
```

registered in the runner directly after the `migrate_projects_adopt_v2499517()` block, in its own try/except.

- [ ] **Step 5: run.** `test_project_audience_migration.py`, `test_project_audience_model.py`, `test_project_adopt.py`, `test_front_door_audience.py`, `test_front_door_hardening.py`, `test_triage.py`, `test_access_matrix.py`, `test_access_core.py`, `test_access_calendar.py`, `test_project_holds.py`. Expected: PASS except `scenario_recipients_union_and_filter`. Claude reviews, gates, bumps, commits, then pushes Tasks 1-3.

---

### Task 4 (Codex): recipients and the reply sender

**Files:** Modify `services/access.py:317-329`, `services/replies.py:164-176`.

- [ ] **Step 1: `private_recipients`.**

```python
def private_recipients(kind, row):
    """Who a restricted record's DM-worthy signal goes to (access spec §4.8, audience spec §4)."""
    from services import projects
    home = home_project(row)
    keeper = keeper_id(kind, row)
    child_keeper = bool(keeper) and projects._child(_get_member(keeper) or {})
    members = [m for m in storage.get_all_members() if projects._active(m)]
    out = [keeper] if keeper else []
    audience = (home or {}).get('audience')
    if child_keeper or audience in ('parents', 'shared'):
        out += [m['id'] for m in members if projects._parent(m)]
    if audience in ('shared', 'private'):
        out += list(home.get('shared_with') or [])
    by_id = {m['id']: m for m in members}
    return [mid for mid in dict.fromkeys(out)
            if mid in by_id and record_view(kind, row, by_id[mid]) is not None]
```

- [ ] **Step 2: `replies._send`** computes `view = access.record_view('thread', thread, m)` once per recipient; `if view is None: continue`; the body is the neutral line when `view == access.KEEPER`.

- [ ] **Step 3: run.** `test_project_audience_model.py` (all), `test_access_matrix.py`, `access_shared_signals` cells via `test_access_matrix.py`, `test_replies*.py` (`ls tests | grep replies`), `test_watchers*.py` touching private recipients (`grep -l private_recipients tests/*.py`). Expected: PASS.

---

### Task 5 (Claude): the picker and the UI

**Files:** Create `templates/components/audience_picker.html`, `tests/test_audience_picker_live.py`. Modify `templates/shopping.html:1104-1153, 3541-3596`, `templates/components/projects_page.html:32-35, 238-260, 419` (create form, detail Audience row in the settings sheet), `templates/app.html:5370-5402`.

- [ ] **Step 1: live test first** (`test_audience_picker_live.py`, no `harness.py`; follow `project_sheets_fixture`):
  - shopping: a household list's share popover lists members, toggling a keeping-up member keeps the household audience and its `shared_with` grant; the default list hides the Private switch; a private list re-reads the server's list (actor added) after save;
  - projects: create a `shared` project with Aunt from the picker, reload, the detail Audience row reads "Parents and chosen people"; as Aunt (listed adult) the Audience row is absent;
  - chat card: "Choose people…" shown for Mom, absent for Aunt; a body-goal card shows "Only you" and no picker;
  - screenshots saved and inspected.
- [ ] **Step 2: extract the component.** `audience_picker.html` is an Alpine partial taking `{kind, values, allowPrivate, audience, shared_with}` and emitting `audience-picked` with `{audience, shared_with}`; it never computes a kind's rules. Shopping includes it with `values=['household','private']`, `allowPrivate=!list.is_default`, and keeps its existing PUT and re-read.
- [ ] **Step 3: projects page and chat card** use the component; gate on `can_edit_audience`; body goal shows "Only you".
- [ ] **Step 4:** `python tools/build_tailwind.py`; run the live test and `test_project_card_live.py`, `test_projects_detail_live.py`, `test_list_sharing.py`. Expected: PASS. Codex reviews (read-only), then commit.

---

### Task 6 (Claude): close-out

- [ ] Whole-branch review: Codex reviews Task 1 and 5 diffs; a Claude reviewer subagent reviews Tasks 2-4 together against the spec.
- [ ] Gate: every file named in Tasks 2-5 once more, plus `test_access_matrix.py` full.
- [ ] `chauffeur/system_capabilities.md` top entry (BUILT, not device-verified; device steps: rebuild; open a project's Audience row, pick Shared with Aunt, check Aunt's phone; Kate creates a private project leaving Dad out, check Dad's phone and the calendar shows Busy); NEXT becomes the delete spec.
- [ ] Memory: `projects-delete-slice.md` and `projects-arc.md` updated; bump, commit, push.
