# Projects Front Door — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One chat tool, `start_project`, creates a project at once, posts its card first and plans inside it; every thread, mission and program carries a `project_id`, set at creation and by a one-time migration that wraps every existing row.

**Architecture:** `services/projects.py` gains `adopt` (find the project a record already belongs to, else create one from the record) and `adopt_existing` (the migration); `missions.launch`, `threads.create` and program creation take an explicit `project_id` and call `adopt` after the subject is bound. `services/agent_tools_v2.start_project` creates the project, posts a `project` chat card to the caller's Argyle DM and launches the planning mission bound to the project. The router declares `start_project` and drops `start_mission_for`, `propose_program` and `create_thread` from chat (they stay in the registry for plans). `situations`/`triage` learn the `project` kind so a conversation can hold a project as its focus.

**Tech Stack:** Python 3 / FastAPI, TinyDB-style tables over SQLite (`services/storage.py`), Pydantic models (`models/schemas.py`), vendored Alpine + vanilla JS in `templates/app.html`, plain-script tests under `chauffeur/tests/` using `harness.check`.

**Spec:** `docs/superpowers/specs/2026-10-15-projects-front-door-design.md` (Sections 1, 5, 6; slice 1). Builds on `docs/superpowers/specs/2026-10-15-projects-core-design.md`.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts: `python tests/test_x.py`; unset `HA_BASE_URL` first (`unset HA_BASE_URL` in bash). Never run the whole suite.
- Gate for this slice = the new tests plus: `tests/test_start_mission.py`, `tests/test_registry_parity.py`, `tests/test_subject_voice.py`, `tests/test_voice_identity.py`, `tests/test_project_planning.py`, `tests/test_project_argyle.py`, `tests/test_projects_tools.py`, `tests/test_project_portuguese.py`, `tests/test_planned_piano.py`, `tests/test_threads_agent_tools.py`, `tests/test_programs_agent_tools.py`, `tests/test_mission_subject.py`.
- Pre-existing failures, not ours: `tests/test_situation_tools.py` scenario_parity_both_ways; `tests/test_app_voice.py` 3 errors.
- No browser dialogs (`alert`/`confirm`/`prompt`); use `promptInput`, `promptConfirm`, `showGlobalAlert`.
- A project's words follow its audience: anything new that carries a project title (card, DM, tool message) checks `projects.can_see` / `situations.channel_visible` first.
- Body-goal rule: `projects.prepare_create` classifies; never pass `body_goal` from a client or tool.
- Identity never comes from model arguments: handlers take `actor`/`acting_member` from dispatch.
- Do not bump `chauffeur/config.yaml` and do not commit from a Codex task; Claude gates, documents, bumps and commits.
- Commit messages: no double quotes when committing through PowerShell; prefer the Bash tool.

## Review Focus

1. A thread-origin mission launched by `start_mission_for` (still callable from a plan row) must land in the THREAD's project, never a second one — Task 1 test `scenario_thread_origin_mission_joins_the_threads_project`.
2. A dropped project must not swallow new work: `adopt` on a record whose `project_id` points at a dropped project returns it unchanged (no silent re-wrap) — Task 1 test `scenario_adopt_is_idempotent_and_never_rewraps`.
3. A household voice request must never speak a parent's private project title through dedupe — Task 3 test `scenario_voice_dedupe_is_spoken_safe`.
4. The migration must survive a thread whose owner was archived or deleted (owner falls back to the parent of record) — Task 2 test `scenario_migration_handles_a_missing_owner`.
5. A child's `start_project` must leave a visible hand-off for a parent (the Needs you lane is slice 2; here the card line and `projects.needs_plan` flag) — Task 3 test `scenario_a_child_starts_a_project_and_a_parent_plans_it`.

---

### Task 1: `project_id` on every record and `projects.adopt`

**Files:**
- Modify: `chauffeur/models/schemas.py` (class `Thread` ~935, class `Program` ~764): add `project_id: Optional[str] = None`
- Modify: `chauffeur/services/storage.py:2978-2992` (`add_mission` defaults): add `'project_id': None`
- Modify: `chauffeur/services/projects.py` (new functions after `remove_piece`, ~line 740)
- Modify: `chauffeur/services/missions.py:1709-1737` (`launch`)
- Modify: `chauffeur/services/threads.py:289-320` (`create`)
- Modify: `chauffeur/services/agent_tools_v2.py:2396` (`propose_program`'s `add_program`) and `chauffeur/main.py:7401` (`POST /api/programs` `add_program`)
- Modify: `chauffeur/main.py:6060-6078` (`project_plan`), `chauffeur/services/projects.py:604-638` (`advance`)
- Test: `chauffeur/tests/test_project_adopt.py`

**Interfaces:**
- Produces: `projects.adopt(kind: str, record_id: str, actor: dict | None, project_id: str | None = None) -> str | None` — returns the project id now on the record (None if the record is missing). `projects.project_for(kind, record_id) -> dict | None`.
- Produces: `missions.launch(goal, origin_kind='manual', origin_ref=None, created_by=None, tier='mission', project_id=None, subject=None)` where `subject` is `(kind, sid)` bound BEFORE adoption; `threads.create(..., project_id=None)`; `programs.create_row(data: dict, project_id=None) -> str` (one wrapper around `storage.add_program` + `adopt`, used by both the endpoint and `propose_program`).

- [ ] **Step 1: Write the failing tests**

```python
"""Every thread, mission and program belongs to exactly one project
(front door spec §1, slice 1, Task 1).

Run from chauffeur/:  python tests/test_project_adopt.py
"""
from harness import check  # noqa: F401
from services import storage, missions, threads
from test_mission_subject import _fresh as _fresh_subjects, _thread, _mission
from test_subjects import MOM, DAD, KID


def _fresh():
    _fresh_subjects()
    storage.projects_table.truncate()
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'


def _p():
    from services import projects
    return projects


def scenario_a_thread_created_by_hand_gets_a_project():
    _fresh()
    tid = threads.create(title='Deck permit', owner_member_id='mom', goal='permit approved', kind='project', created_by='mom')
    t = storage.get_thread(tid)
    p = storage.get_project(t['project_id'])
    check(p and p['title'] == 'Deck permit' and p['goal'] == 'permit approved' and p['owner_member_id'] == 'mom'
          and p['audience'] == 'private' and p['state'] == 'active', f"wrapped: {p}")
    check(p['pieces'] == [{'kind': 'thread', 'id': tid}], f"the thread is its first piece: {p['pieces']}")


def scenario_a_childs_record_gets_a_parents_project():
    _fresh()
    from services import programs
    pid_prog = programs.create_row({'member_id': 'kid', 'title': 'Learn guitar', 'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': []},
                                    'phases': [], 'source': {'origin': 'none'}, 'created_by': 'mom'})
    p = storage.get_project(storage.get_program(pid_prog)['project_id'])
    check(p['owner_member_id'] == 'kid' and p['audience'] == 'parents' and p['title'] == 'Learn guitar', f"a kid's program: {p}")


def scenario_a_thread_origin_mission_joins_the_threads_project():
    _fresh()
    tid = threads.create(title='Dishwasher', owner_member_id='mom', goal='fixed', kind='vendor', created_by='mom')
    res = missions.launch('get the dishwasher fixed', origin_kind='thread', origin_ref=tid, created_by='mom')
    m = storage.get_mission(res['mission_id'])
    check(m['project_id'] == storage.get_thread(tid)['project_id'], "one project for the thread and its mission")
    check(len(storage.get_projects()) == 1, f"never a second project: {[p['title'] for p in storage.get_projects()]}")
    check(missions.subject_of(m) == (None, None, 0), "subject_of still reads the thread, unchanged")


def scenario_launch_binds_the_project_before_adopting():
    _fresh()
    proj = _p().create({'title': 'Learn Portuguese', 'goal': 'talk', 'done_when': 'order dinner', 'owner_member_id': 'mom'}, dict(MOM))['project']
    res = missions.launch('plan the next part', created_by='mom', project_id=proj['id'], subject=('project', proj['id']))
    m = storage.get_mission(res['mission_id'])
    check(m['project_id'] == proj['id'] and missions.subject_of(m)[:2] == ('project', proj['id']), f"bound and adopted into the same project: {m}")
    check(len(storage.get_projects()) == 1, "no wrapper project was made first")


def scenario_the_plan_route_and_advance_make_no_wrapper():
    _fresh()
    import main
    from test_subject_audience import _as
    proj = _p().create({'title': 'Bathroom', 'goal': 'done', 'done_when': 'tiled', 'owner_member_id': 'mom'}, dict(MOM))['project']
    out = main.project_plan(proj['id'], request=_as('mom'))
    check(storage.get_mission(out['mission_id'])['project_id'] == proj['id'] and len(storage.get_projects()) == 1, "plan route")
    _p().add_step(proj['id'], {'title': 'Find a tiler', 'owner': 'argyle', 'goal': 'three tilers nearby'}, dict(MOM))
    started = _p().advance(proj['id'])
    mids = [s['mission_id'] for s in storage.get_project(proj['id'])['steps'] if s.get('mission_id')]
    check(started and mids and storage.get_mission(mids[0])['project_id'] == proj['id'] and len(storage.get_projects()) == 1, "advance")


def scenario_adopt_is_idempotent_and_never_rewraps():
    _fresh()
    tid = threads.create(title='Deck permit', owner_member_id='mom', created_by='mom')
    first = storage.get_thread(tid)['project_id']
    check(_p().adopt('thread', tid, dict(MOM)) == first and len(storage.get_projects()) == 1, "a second adopt changes nothing")
    _p().set_state(first, 'dropped', dict(MOM))
    check(_p().adopt('thread', tid, dict(MOM)) == first and len(storage.get_projects()) == 1,
          "a record whose project was dropped is NOT re-wrapped by adopt")
    check(_p().adopt('thread', 'nope', dict(MOM)) is None, "a missing record adopts to nothing")


def scenario_a_planner_row_inside_a_project_joins_it():
    _fresh()
    proj = _p().create({'title': 'Learn Portuguese', 'goal': 'talk', 'done_when': 'order dinner', 'owner_member_id': 'mom'}, dict(MOM))['project']
    tid = threads.create(title='Teacher', owner_member_id='mom', created_by='mom', project_id=proj['id'])
    check(storage.get_thread(tid)['project_id'] == proj['id'] and len(storage.get_projects()) == 1, "an explicit project wins")
    check({'kind': 'thread', 'id': tid} in storage.get_project(proj['id'])['pieces'], "and the thread is a piece")


SCENARIOS = [scenario_a_thread_created_by_hand_gets_a_project, scenario_a_childs_record_gets_a_parents_project,
             scenario_a_thread_origin_mission_joins_the_threads_project, scenario_launch_binds_the_project_before_adopting,
             scenario_the_plan_route_and_advance_make_no_wrapper, scenario_adopt_is_idempotent_and_never_rewraps,
             scenario_a_planner_row_inside_a_project_joins_it]

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
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_adopt.py`
Expected: every scenario FAILS (`KeyError: 'project_id'`, `AttributeError: adopt`, `TypeError: unexpected keyword 'project_id'`).

- [ ] **Step 3: Add the field to the models and the mission defaults**

In `models/schemas.py`, inside `class Thread(BaseModel)` after `subject_history`, and inside `class Program(BaseModel)` after `created_by`:

```python
    project_id: Optional[str] = None          # every record belongs to one project (front door §1)
```

In `storage.add_mission`'s default row add `'project_id': None,` after `'subject_history': [],`.

- [ ] **Step 4: Write `adopt` and `project_for` in `services/projects.py`**

Append after `remove_piece`:

```python
_ADOPT_TABLES = {'thread': (storage.get_thread, storage.update_thread),
                 'mission': (storage.get_mission, storage.update_mission),
                 'program': (storage.get_program, storage.update_program)}


def project_for(kind, record_id):
    """The project a thread, mission or program belongs to, or None."""
    get, _ = _ADOPT_TABLES[kind]
    row = get(record_id) or {}
    return storage.get_project(row.get('project_id')) if row.get('project_id') else None


def _belongs_to(kind, row):
    """The project a record already belongs to by an earlier binding, if any."""
    from services import missions
    if kind == 'mission':
        skind, sid, _ = missions.subject_of(row)
        if skind == 'project' and storage.get_project(sid):
            return sid
        if row.get('origin_kind') == 'thread' and row.get('origin_ref'):
            thread = storage.get_thread(row['origin_ref']) or {}
            if thread.get('project_id') and storage.get_project(thread['project_id']):
                return thread['project_id']
    for project in storage.get_projects():
        if any(p.get('kind') == kind and p.get('id') == row.get('id') for p in project.get('pieces') or []):
            return project['id']
    return None


def _state_for(kind, row):
    st = row.get('state') if kind != 'mission' else row.get('status')
    if kind == 'thread':
        return {'done': 'done', 'dropped': 'dropped'}.get(st, 'active')
    if kind == 'program':
        return {'done': 'done', 'dropped': 'dropped', 'paused': 'paused'}.get(st, 'active')
    from services import missions
    if st in missions.LIVE or st == 'waiting_user':
        return 'active'
    return 'done' if st == 'done' else 'dropped'


def _wrapper_fields(kind, row, actor):
    """Title, goal, owner and audience for a project made from a record (§1)."""
    from services import situations
    if kind == 'thread':
        title, goal, owner = row.get('title') or '', row.get('goal') or row.get('title') or '', row.get('owner_member_id')
    elif kind == 'program':
        title, goal, owner = row.get('title') or '', row.get('title') or '', row.get('member_id')
    else:
        title, goal, owner = (row.get('goal') or '')[:80], row.get('goal') or '', row.get('created_by')
    member = storage.get_member(owner) if owner else None
    if not _active(member or {}):
        member = situations.parent_of_record()
    voice = bool(row.get('voice_shared') or row.get('requester_provenance'))
    audience = 'household' if voice else ('parents' if _child(member or {}) else 'private')
    return {'title': title or 'Untitled', 'goal': goal, 'done_when': '', 'owner_member_id': (member or {}).get('id'),
            'audience': audience}


def adopt(kind, record_id, actor, project_id=None):
    """Give a thread, mission or program its one project (front door §1).

    An explicit project wins; else the project the record already belongs to
    by binding; else a project made from the record. Idempotent: a record
    that has a project keeps it, even a dropped one (reopening is an act)."""
    get, update = _ADOPT_TABLES[kind]
    with storage.db_lock:
        row = get(record_id)
        if not row:
            return None
        if row.get('project_id') and storage.get_project(row['project_id']):
            return row['project_id']
        pid = project_id if project_id and storage.get_project(project_id) else _belongs_to(kind, row)
        if not pid:
            fields = _wrapper_fields(kind, row, actor)
            owner = storage.get_member(fields['owner_member_id']) or {}
            creator = actor if _active(actor or {}) else (owner if _active(owner) else None)
            if not creator:
                from services import situations
                creator = situations.parent_of_record()
            if not creator:
                return None
            prepared = prepare_create(fields, creator)
            if prepared['status'] != 'success':
                # A body-goal title a child typed, or an owner the actor may not
                # assign: fall back to the creator as owner, private.
                prepared = prepare_create({**fields, 'owner_member_id': creator['id'], 'audience': 'private'}, creator)
                if prepared['status'] != 'success':
                    return None
            project = prepared['project']
            project['state'] = _state_for(kind, row)
            pid = storage.add_project(project)
        update(record_id, {'project_id': pid})
        project = storage.get_project(pid)
        pieces = project.get('pieces') or []
        if not any(p.get('kind') == kind and p.get('id') == record_id for p in pieces):
            storage.update_project(pid, {'pieces': pieces + [{'kind': kind, 'id': record_id}]})
        return pid
```

Note: `prepare_create` requires the actor to be parent/adult/child and active, and only a parent may assign to someone else; the fallback above handles an adult owner's thread adopted by a different adult actor (owner becomes the actor). `storage.update_program` is the program updater (`storage.py:3480`).

- [ ] **Step 5: Thread the project through the create paths**

`services/threads.py` `create`: add parameter `project_id: str = None` at the end of the signature; after `storage.append_thread_history(...)` and before `return thread_id`:

```python
    from services import projects
    projects.adopt('thread', thread_id, storage.get_member(created_by) if created_by else None, project_id=project_id)
```

`services/missions.py` `launch`: signature becomes

```python
def launch(goal: str, origin_kind: str = 'manual', origin_ref=None,
           created_by=None, tier: str = 'mission', project_id: str = None,
           subject: tuple = None) -> dict:
```

After `_seed_thread_context` and before `_sit.touched('mission', mid)`:

```python
    if subject and subject[0] and subject[1]:
        from services import subjects
        storage.update_mission(mid, {'subject_kind': subject[0], 'subject_id': subject[1], 'subject_rev': 1,
                                     'subject_history': subjects.history_after_binding({}, subject[0], subject[1])})
    from services import projects
    projects.adopt('mission', mid, storage.get_member(created_by) if created_by else None, project_id=project_id)
```

`services/programs.py`: add

```python
def create_row(data: dict, project_id: str = None) -> str:
    """The one door for a new program row: stored, then adopted into its project."""
    pid = storage.add_program(data)
    from services import projects
    projects.adopt('program', pid, storage.get_member(data.get('created_by')) if data.get('created_by') else None,
                   project_id=project_id)
    return pid
```

Replace the two `storage.add_program({...})` calls (`agent_tools_v2.py:2396` in `propose_program`, `main.py:7401` in the programs POST endpoint) with `programs.create_row({...})` (import `programs` locally as the file already does for `clamp_shape`).

`main.py` `project_plan` (6060-6078): replace the `missions.launch(...)` + `storage.update_mission(mid, {'subject_kind': 'project', ...})` pair with

```python
        result = missions.launch('Help me plan the next part of this project: ' + project['title'], created_by=actor['id'],
                                 project_id=project_id, subject=('project', project_id))
        if result.get('status') != 'launched':
            raise HTTPException(status_code=400, detail=result.get('message') or 'Could not start planning')
        mid = result['mission_id']
        return {'status': 'success', 'mission_id': mid}
```

`services/projects.py` `advance` (~626-632): replace `missions.launch(step['goal'], created_by=creator['id'])` + the following `storage.update_mission(...)` subject write with

```python
            result = missions.launch(step['goal'], created_by=creator['id'], project_id=project_id,
                                     subject=('project', project_id))
            if result.get('status') != 'launched':
                continue
            mid = result['mission_id']
```

Also search for other `missions.launch(` callers that bind a project afterwards: `grep -n "missions.launch(\|_missions.launch(" services/*.py main.py`. `planned.py` build rows that create threads/programs inside a plan run `create_thread`/`propose_program` through the registry; make the registry handlers pass the plan's project: in `agent_tools_v2.handle_create_thread` and `handle_propose_program`, read `args.get('project_id')` and pass it through (`create_thread(..., project_id=...)`, `propose_program(..., project_id=...)`), adding `project_id: str = None` parameters to both functions that forward to `threads.create` / `programs.create_row`. In `services/planned.py`, where a stage's rows are executed (`run_stage`), inject the mission's project into each row's args: `args.setdefault('project_id', mission.get('project_id'))` for tools whose contract `creates` is `thread` or `program` (`CONTRACT[name].get('creates') in ('thread', 'program')`).

- [ ] **Step 6: Run the tests**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_adopt.py && python tests/test_project_planning.py && python tests/test_project_argyle.py && python tests/test_start_mission.py && python tests/test_threads_agent_tools.py && python tests/test_programs_agent_tools.py && python tests/test_planned_piano.py`
Expected: all PASS. If `test_planned_piano` shows two projects (the program's own wrapper beside the Portuguese project), the `run_stage` injection in Step 5 is missing.

- [ ] **Step 7: Commit**

```bash
git add chauffeur/models/schemas.py chauffeur/services/storage.py chauffeur/services/projects.py chauffeur/services/missions.py chauffeur/services/threads.py chauffeur/services/programs.py chauffeur/services/planned.py chauffeur/services/agent_tools_v2.py chauffeur/main.py chauffeur/tests/test_project_adopt.py
git commit -m "feat(projects): every thread, mission and program carries project_id - projects.adopt at every create path, bind before adopt on launch"
```

---

### Task 2: The migration — wrap every existing record

**Files:**
- Modify: `chauffeur/services/projects.py` (after `adopt`)
- Modify: `chauffeur/services/migrations.py:471-500` (`run_all_migrations`)
- Test: `chauffeur/tests/test_project_adopt.py` (append)

**Interfaces:**
- Consumes: `projects.adopt(kind, record_id, actor, project_id=None)` (Task 1).
- Produces: `projects.adopt_existing() -> dict` returning `{'threads': n, 'missions': n, 'programs': n, 'skipped': bool}`; app-state key `projects_adopted_rev` (int, 1 after the first run).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_project_adopt.py` before `SCENARIOS`, and add the names to `SCENARIOS`)

```python
def scenario_migration_wraps_every_record_once():
    _fresh()
    storage.set_app_state('projects_adopted_rev', 0)
    tid = storage.add_thread({'title': 'Pest control', 'kind': 'vendor', 'state': 'waiting', 'owner_member_id': 'mom', 'created_by': 'mom'})
    live = storage.add_mission({'goal': 'get a quote', 'origin_kind': 'thread', 'origin_ref': tid, 'created_by': 'mom', 'tier': 'mission'})
    closed = storage.add_thread({'title': 'Old permit', 'kind': 'project', 'state': 'done', 'owner_member_id': 'dad', 'created_by': 'dad'})
    ended = storage.add_mission({'goal': 'book the dentist', 'created_by': 'mom', 'tier': 'mission', 'status': 'done'})
    prog = storage.add_program({'member_id': 'kid', 'title': 'Guitar', 'shape': {'sessions_per_week': 2, 'minutes': 15, 'preferred_days': []},
                                'phases': [], 'source': {'origin': 'none'}, 'created_by': 'mom', 'state': 'active'})
    out = _p().adopt_existing()
    check(out == {'threads': 2, 'missions': 2, 'programs': 1, 'skipped': False}, f"counted: {out}")
    pid = storage.get_thread(tid)['project_id']
    check(storage.get_mission(live)['project_id'] == pid, "a thread and its live mission are one project")
    check(storage.get_project(pid)['state'] == 'active', "an open thread is an active project")
    check(storage.get_project(storage.get_thread(closed)['project_id'])['state'] == 'done', "a done thread is a done project")
    check(storage.get_project(storage.get_mission(ended)['project_id'])['state'] == 'done', "an ended mission is a done project")
    kp = storage.get_project(storage.get_program(prog)['project_id'])
    check(kp['owner_member_id'] == 'kid' and kp['audience'] == 'parents', f"a kid's program is a parents project: {kp}")
    check(len(storage.get_projects()) == 4, f"four projects: {[p['title'] for p in storage.get_projects()]}")
    again = _p().adopt_existing()
    check(again['skipped'] is True and len(storage.get_projects()) == 4, "a second run does nothing")
    check(storage.get_app_state('projects_adopted_rev') == 1, "recorded")


def scenario_migration_handles_a_missing_owner():
    _fresh()
    storage.set_app_state('projects_adopted_rev', 0)
    tid = storage.add_thread({'title': 'Gutters', 'kind': 'vendor', 'state': 'open', 'owner_member_id': 'gone', 'created_by': 'gone'})
    _p().adopt_existing()
    p = storage.get_project(storage.get_thread(tid)['project_id'])
    check(p['owner_member_id'] in ('mom', 'dad') and p['audience'] == 'private', f"the parent of record stands in: {p}")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_adopt.py`
Expected: the two new scenarios FAIL with `AttributeError: adopt_existing`.

- [ ] **Step 3: Write `adopt_existing`**

Append to `services/projects.py`:

```python
ADOPTED_KEY = 'projects_adopted_rev'


def adopt_existing():
    """One-time wrap of every thread, mission and program (front door §1).

    Threads first so their missions join the thread's project; closed rows
    become done or dropped projects so old links still open. Recorded in
    app state; a later record is adopted at creation."""
    with storage.db_lock:
        if int(storage.get_app_state(ADOPTED_KEY) or 0) >= 1:
            return {'threads': 0, 'missions': 0, 'programs': 0, 'skipped': True}
        counts = {'threads': 0, 'missions': 0, 'programs': 0, 'skipped': False}
        for row in storage.get_threads(include_closed=True):
            if adopt('thread', row['id'], None):
                counts['threads'] += 1
        for row in storage.get_missions():
            if adopt('mission', row['id'], None):
                counts['missions'] += 1
        for row in storage.get_programs():
            if adopt('program', row['id'], None):
                counts['programs'] += 1
        storage.set_app_state(ADOPTED_KEY, 1)
        return counts
```

Check `storage.get_programs()` with no arguments returns every state (`storage.py:3467`); if it filters, pass `state=None` explicitly or iterate `storage.programs_table.all()`.

- [ ] **Step 4: Call it at startup**

In `services/migrations.py` add

```python
def migrate_projects_adopt_v2499517():
    """Front door slice 1: every thread, mission and program gets its project."""
    from services import projects
    out = projects.adopt_existing()
    if not out.get('skipped'):
        logger.info(f"[migrations] projects adopted: {out}")
```

and in `run_all_migrations()` append, after the last existing `try` block:

```python
    try:
        migrate_projects_adopt_v2499517()
    except Exception as e:
        logger.error(f"Error adopting records into projects: {e}")
```

- [ ] **Step 5: Run the tests**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_adopt.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add chauffeur/services/projects.py chauffeur/services/migrations.py chauffeur/tests/test_project_adopt.py
git commit -m "feat(projects): one-time migration wraps every thread, mission and program into a project, closed rows into done or dropped projects"
```

---

### Task 3: `start_project`, the project card, and the `project` situation kind

**Files:**
- Modify: `chauffeur/services/situations.py:22` (`KINDS`), `:44-57` (`load`), `:369` (`options_for` builder map), `:446-460` (`_state`, `_is_done`), `:484-496` (`_can_see_base`), `:634` (`_rows_of` — projects return `[]`)
- Modify: `chauffeur/services/projects.py` (new `card`, `needs_plan`)
- Modify: `chauffeur/services/agent_tools_v2.py` (new `start_project` after `start_mission_for` ~1900; `act_on_situation` project focus; `handle_start_project`)
- Test: `chauffeur/tests/test_front_door_chat.py`

**Interfaces:**
- Consumes: `projects.adopt`, `missions.launch(..., project_id, subject)` (Task 1).
- Produces: `agent_tools_v2.start_project(goal, title=None, for_member_name=None, acting_member=None, focus_key=None, voice_context=None, subject_kind=None, subject_id=None) -> dict` with `status` in `success|error|ambiguous`, keys `project_id`, `mission_id` (None when planning did not start), `message`. `projects.card(project, viewer) -> dict | None` with `kind='project'`, `project_id`, `title`, `goal`, `owner`, `owner_label`, `audience`, `state`, `planning` (`'started'|'off'|'needs_parent'`), `reason`, `can_edit`. `projects.needs_plan(project) -> bool` (active, no steps, no live mission bound). `situations.KINDS` includes `'project'`; `situations.load('project', id)` returns the row; `situations.can_see('project', row, viewer)` delegates to `projects.can_see`.

- [ ] **Step 1: Write the failing tests**

```python
"""The chat front door (front door spec §1, §5, §6, slice 1, Task 3):
start_project creates the project at once, posts its card first, plans inside.

Run from chauffeur/:  python tests/test_front_door_chat.py
"""
from harness import check  # noqa: F401
from services import storage, missions, situations, triage
from services import agent_tools_v2 as tools
from test_mission_subject import _fresh as _fresh_subjects, _plan
from test_subjects import MOM, DAD, AUNT, KID


def _fresh(missions_on=True):
    _fresh_subjects()
    storage.projects_table.truncate()
    base = storage.get_settings()
    storage.get_settings = (lambda s, on: (lambda: dict(s, missions_enabled=on)))(base, missions_on)
    from services import model_pools
    model_pools.api_key_for_pool = lambda pool, settings=None: 'k'
    _plan({'action': 'interview', 'questions': [{'key': 'level', 'ask': 'Where are you starting?', 'kind': 'text'}]})


def _dm_cards(member_id):
    argyle = storage.ensure_argyle_member()
    dm = storage.get_or_create_dm(argyle['id'], member_id)
    return [m for m in storage.get_channel_messages(dm['id']) if m.get('card')]


def _p():
    from services import projects
    return projects


def scenario_the_project_exists_at_once_and_its_card_comes_first():
    _fresh()
    out = tools.start_project('I want to learn Brazilian Portuguese', acting_member=dict(MOM), focus_key='channel:dm1')
    check(out['status'] == 'success' and out['project_id'] and out['mission_id'], f"started: {out}")
    p = storage.get_project(out['project_id'])
    check(p['goal'] == 'I want to learn Brazilian Portuguese' and p['owner_member_id'] == 'mom' and p['audience'] == 'private'
          and p['state'] == 'active', f"the project in the person's words: {p}")
    m = storage.get_mission(out['mission_id'])
    check(m['project_id'] == p['id'] and missions.subject_of(m)[:2] == ('project', p['id']), "the planning mission is bound and adopted")
    cards = _dm_cards('mom')
    check(cards and cards[0]['card']['kind'] == 'project' and cards[0]['card']['project_id'] == p['id'],
          f"the project card is the first card in Mom's DM: {[c['card']['kind'] for c in cards]}")
    check(cards[0]['card']['planning'] == 'started', f"and says planning started: {cards[0]['card']}")
    f = triage.get_focus('channel:dm1')
    check(f and f['kind'] == 'project' and f['id'] == p['id'], f"the project is the focus: {f}")


def scenario_approval_inside_the_started_project_appends_steps():
    _fresh()
    from services import planned
    out = tools.start_project('I want to learn Brazilian Portuguese', acting_member=dict(MOM))
    mid, pid = out['mission_id'], out['project_id']
    missions.step(storage.get_mission(mid))
    planned.answer_plan(mid, {'level': 'never'}, dict(MOM))
    _plan({'action': 'plan', 'steps': [{'id': 'p1', 'title': 'Attend a first class', 'owner': 'mom'}],
           'stages': [{'id': 's1', 'kind': 'work', 'title': 'Find meetups', 'why': 'practice', 'goal': 'meetups', 'step_budget': 2, 'makes': ['meetups']}]})
    missions.step(storage.get_mission(mid))
    card = missions.ask_card(storage.get_mission(mid))
    check(card['project']['id'] == pid, f"the plan card names the existing project, proposes no new one: {card.get('project')}")
    plan = storage.get_mission(mid)['plan']
    situations.act('mission', mid, 'approve_plan', option_id=f"approve_plan:{plan['rev']}:approve", payload={}, actor=dict(MOM))
    check(len(storage.get_projects()) == 1 and {s['title'] for s in storage.get_project(pid)['steps']} == {'Attend a first class', 'Find meetups'},
          f"steps appended to the one project: {[p['title'] for p in storage.get_projects()]}")


def scenario_dedupe_is_by_owner_subject_and_intent():
    _fresh()
    first = tools.start_project('learn Portuguese', for_member_name='Kate', acting_member=dict(MOM))
    again = tools.start_project('learn Portuguese', for_member_name='Kate', acting_member=dict(MOM))
    check(again['status'] == 'success' and again['project_id'] == first['project_id'] and 'already under way' in again['message'],
          f"the same goal for the same person is named, not doubled: {again}")
    other = tools.start_project('learn Portuguese', for_member_name='Mom', acting_member=dict(MOM))
    check(other['project_id'] != first['project_id'], "Kate's project never blocks Mom's")
    check(len(storage.get_projects()) == 2, f"two projects: {[p['title'] for p in storage.get_projects()]}")


def scenario_two_matches_ask_which():
    _fresh()
    a = _p().create({'title': 'Learn Portuguese', 'goal': 'learn Portuguese fast', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    b = _p().create({'title': 'Portuguese trip', 'goal': 'learn Portuguese basics', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    out = tools.start_project('learn Portuguese', acting_member=dict(MOM))
    check(out['status'] == 'ambiguous' and {a['title'], b['title']} <= set(out['message'].split('; ')[0] + out['message']),
          f"asks which rather than suppressing: {out}")
    check(len(storage.get_projects()) == 2, "nothing created")


def scenario_voice_dedupe_is_spoken_safe():
    _fresh()
    from services import voice_identity as voice
    _p().create({'title': 'Secret Portuguese', 'goal': 'learn Portuguese', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))
    ctx = voice.VoiceContext('ha', 'assist_satellite.kitchen', 'r', 'g', service_revision=voice._revision(), paired=True)
    out = tools.start_project('learn Portuguese', acting_member=None, voice_context=ctx, focus_key='voice:1')
    check('Secret' not in (out.get('message') or ''), f"a household voice request never hears a parent's private project: {out}")
    check(out['status'] == 'success' and storage.get_project(out['project_id'])['audience'] == 'household',
          f"a voice-started project is household, owned by the parent of record: {out}")


def scenario_not_a_project_drops_project_and_mission_in_one_write():
    _fresh()
    out = tools.start_project('get the dishwasher fixed', acting_member=dict(MOM))
    res = _p().set_state(out['project_id'], 'dropped', dict(MOM))
    check(res['status'] == 'success' and storage.get_project(out['project_id'])['state'] == 'dropped', "dropped")
    check(storage.get_mission(out['mission_id'])['status'] in ('dropped', 'blocked', 'done'), f"its planning mission is over: {storage.get_mission(out['mission_id'])['status']}")


def scenario_missions_off_still_creates_the_project():
    _fresh(missions_on=False)
    out = tools.start_project('renovate the bathroom', acting_member=dict(MOM))
    check(out['status'] == 'success' and out['project_id'] and out['mission_id'] is None, f"project without planning: {out}")
    card = _dm_cards('mom')[0]['card']
    check(card['planning'] == 'off' and 'Missions are off' in card['reason'], f"the card says why: {card}")


def scenario_a_child_starts_a_project_and_a_parent_plans_it():
    _fresh()
    out = tools.start_project('learn to ride a bike', acting_member=dict(KID))
    p = storage.get_project(out['project_id'])
    check(out['status'] == 'success' and out['mission_id'] is None and p['owner_member_id'] == 'kid' and p['audience'] == 'parents',
          f"created, nothing launched: {out} {p}")
    card = _dm_cards('kid')[0]['card']
    check(card['planning'] == 'needs_parent' and 'Ask a parent' in card['reason'], f"the kid's card: {card}")
    check(_p().needs_plan(p) is True, "flagged for a parent's Needs you")
    check(storage.get_missions() == [], "no mission a child cannot answer")


def scenario_body_goal_pins_private_and_refuses_a_child():
    _fresh()
    out = tools.start_project('get down to 185 lbs', acting_member=dict(MOM))
    p = storage.get_project(out['project_id'])
    check(p['body_goal'] is True and p['audience'] == 'private', f"an adult's body goal is private: {p}")
    kid = tools.start_project('lose 10 pounds', acting_member=dict(KID))
    check(kid['status'] == 'error' and not any(x['owner_member_id'] == 'kid' for x in storage.get_projects()), f"never for a minor: {kid}")


def scenario_channel_refusal_has_no_words():
    _fresh()
    from services import subjects
    orig = subjects.channel_humans
    subjects.channel_humans = lambda key: [dict(MOM), dict(KID)] if key == 'channel:fam' else orig(key)
    try:
        out = tools.start_project('plan a surprise for Kate', acting_member=dict(MOM), focus_key='channel:fam')
    finally:
        subjects.channel_humans = orig
    check(out['status'] == 'refused' and 'surprise' not in out['message'] and storage.get_projects() == [],
          f"refused with no words in a channel some member may not see: {out}")


def scenario_a_correction_with_a_project_focus_reaches_its_live_mission():
    _fresh()
    out = tools.start_project('get the dishwasher fixed', acting_member=dict(MOM), focus_key='channel:dm1')
    missions.step(storage.get_mission(out['mission_id']))   # the interview is asked; the mission waits on the person
    res = tools.act_on_situation(kind='project', situation_id=out['project_id'], verb='answer',
                                 payload={'text': 'use the manufacturer instead'}, acting_member=dict(MOM), focus_key='channel:dm1')
    check(res['status'] in ('success', 'planned'), f"the project focus resolved to its live mission: {res}")
    steps = storage.get_mission_steps(out['mission_id'])
    check(any('manufacturer' in str(s.get('result_json') or s.get('name') or '') for s in steps), f"the steer landed on the mission: {[s['name'] for s in steps]}")


def scenario_a_new_goal_on_a_focused_project_plans_inside_it():
    _fresh()
    out = tools.start_project('renovate the bathroom', acting_member=dict(MOM), focus_key='channel:dm1')
    storage.update_mission(out['mission_id'], {'status': 'done'})
    more = tools.start_project('find a tiler', acting_member=dict(MOM), focus_key='channel:dm1')
    check(more['project_id'] == out['project_id'] and more['mission_id'] != out['mission_id'] and len(storage.get_projects()) == 1,
          f"a new goal on the focused project is new planning inside it: {more}")


SCENARIOS = [scenario_the_project_exists_at_once_and_its_card_comes_first, scenario_approval_inside_the_started_project_appends_steps,
             scenario_dedupe_is_by_owner_subject_and_intent, scenario_two_matches_ask_which, scenario_voice_dedupe_is_spoken_safe,
             scenario_not_a_project_drops_project_and_mission_in_one_write, scenario_missions_off_still_creates_the_project,
             scenario_a_child_starts_a_project_and_a_parent_plans_it, scenario_body_goal_pins_private_and_refuses_a_child,
             scenario_channel_refusal_has_no_words, scenario_a_correction_with_a_project_focus_reaches_its_live_mission,
             scenario_a_new_goal_on_a_focused_project_plans_inside_it]

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
    raise SystemExit(1 if failed else 0)
```

`storage.get_channel_messages(channel_id, after_ts=None, ...)` is at `services/storage.py:6663`.

- [ ] **Step 2: Run to verify failure**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_front_door_chat.py`
Expected: every scenario FAILS with `AttributeError: module 'services.agent_tools_v2' has no attribute 'start_project'`.

- [ ] **Step 3: Teach `situations` and `triage` the `project` kind**

`services/situations.py`:

```python
KINDS = ('finding', 'insight', 'thread', 'mission', 'project')
```

In `load`, before `return None`:

```python
    if kind == 'project':
        return storage.get_project(sid)
```

In `options_for`, the builder map gains `'project': lambda row: []` (a project's taps are its own routes; `act` on a project is never offered). In `_state` / `_is_done` make a project done when `row.get('state') in ('done', 'dropped')` (read both functions first; `_is_done` likely keys on `state` for threads — add the project branch beside it). In `_can_see_base`, before the final `return role in WRITE_ROLES`:

```python
    if kind == 'project':
        from services import projects
        return projects.can_see(row, viewer)
```

`_rows_of('project', ...)` falls through to `return []` already. `triage._alive` then works for a project focus: `load` returns the row, `options_for` returns `[]`, `_is_done` is False while active or paused.

- [ ] **Step 4: `projects.card` and `projects.needs_plan`**

Append to `services/projects.py`:

```python
AUDIENCE_LABEL = {'private': 'Private', 'parents': 'Parents', 'household': 'Household'}


def needs_plan(project):
    """An active project with no steps and no live planning: a parent's Needs you row."""
    from services import missions
    if project.get('state') != 'active' or project.get('steps'):
        return False
    return not any(m.get('status') in missions.LIVE for m in _work_missions(project))


def card(project, viewer, planning='started', reason=''):
    """The project chat card (front door §1); None for a viewer who may not see it."""
    if not can_see(project, viewer):
        return None
    owner = storage.get_member(project.get('owner_member_id')) or {}
    return {'kind': 'project', 'project_id': project['id'], 'title': project.get('title') or '',
            'goal': project.get('goal') or '', 'owner': project.get('owner_member_id'),
            'owner_label': owner.get('name') if _active(owner) else 'Unassigned',
            'audience': project.get('audience'), 'audience_label': AUDIENCE_LABEL.get(project.get('audience'), ''),
            'state': project.get('state'), 'planning': planning, 'reason': reason,
            'can_edit': can_act(project, viewer), 'body_goal': bool(project.get('body_goal'))}
```

- [ ] **Step 5: Write `start_project`** in `services/agent_tools_v2.py`, directly after `start_mission_for`:

```python
def _project_intent(goal, subject_title=None):
    return _intent_words(goal, subject_title) or [w for w in (goal or '').lower().split() if len(w) > 2][:2]


def start_project(goal: str, title: str = None, for_member_name: str = None, acting_member: dict = None,
                  focus_key: str = None, voice_context=None, subject_kind: str = None, subject_id: str = None) -> Dict[str, Any]:
    """The one chat door for anything that takes steps, time or outside people
    (front door §1): the project is created at once, its card is posted
    first, then Argyle plans inside it. A child's project waits for a parent
    to plan it. Voice acts as the parent of record, household audience."""
    from services.voice_identity import VoiceContext
    from services import storage, subjects, situations, projects, missions as _missions, triage as _tri
    spoken = isinstance(voice_context, VoiceContext)
    goal = (goal or '').strip()
    if not goal:
        return {"status": "error", "message": "Say what you want to get done."}
    actor = situations.parent_of_record() if spoken else acting_member
    if not actor or not actor.get('id'):
        return {"status": "error", "message": "Only a signed-in family member can start a project."}
    # Whose project: the caller's, or a named member (parent/adult only).
    owner = actor
    if for_member_name and not spoken:
        owner, refusal = _resolve_named_member_or_refuse(actor, for_member_name, 'start a project for someone else')
        if refusal:
            return refusal
    # A channel some member may not see the result: no words (core spec §5).
    audience = 'household' if spoken else ('parents' if (owner.get('role') == 'child' or owner.get('is_child')) else 'private')
    if focus_key and str(focus_key).startswith('channel:'):
        humans = subjects.channel_humans(focus_key) or []
        probe = {'owner_member_id': owner['id'], 'audience': audience, 'state': 'active'}
        if humans and not all(projects.can_see(probe, h) for h in humans):
            return {"status": "refused", "message": "Ask me about that in your own Argyle chat."}
    subject = subjects.load(subject_kind, subject_id) if subject_kind in subjects.KINDS and subject_id else None
    if subject is None or not subjects.visible(subject_kind, subject, actor, spoken):
        subject_kind = subject_id = None
    subject_title = subjects.title_of(subject_kind, subject) if subject_kind else None
    intent = _project_intent(goal, subject_title)
    # The continuation rule: a new goal said while a project is the focus and
    # none of its missions is live is new planning INSIDE that project.
    f = _tri.get_focus(focus_key) if focus_key else None
    if f and f.get('kind') == 'project':
        focused = storage.get_project(f['id'])
        if focused and focused.get('state') == 'active' and projects.can_act(focused, actor) \
                and not any(m.get('status') in _missions.LIVE for m in projects._work_missions(focused)):
            res = _missions.launch(goal, created_by=actor['id'], project_id=focused['id'], subject=('project', focused['id']))
            if res.get('status') == 'launched':
                return {"status": "success", "project_id": focused['id'], "mission_id": res['mission_id'],
                        "message": f"On it, inside \"{focused['title']}\"."}
    # Dedupe: same owner, same subject (when one was named), same intent, visible
    # to the caller (and spoken-safe, household, for voice).
    matches = []
    for p in storage.get_projects():
        if p.get('state') not in ('active', 'paused') or p.get('owner_member_id') != owner['id']:
            continue
        if not projects.can_see(p, actor):
            continue
        if spoken and (p.get('audience') != 'household' or not subjects.spoken_safe('project', p)):
            continue
        if subject_kind and not any(x.get('kind') == subject_kind and x.get('id') == subject_id for x in p.get('pieces') or []):
            continue
        hay = ((p.get('title') or '') + ' ' + (p.get('goal') or '')).lower()
        if intent and all(w in hay for w in intent):
            matches.append(p)
    if len(matches) == 1:
        p = matches[0]
        _tri.set_focus(focus_key, 'project', p['id'], p.get('title') or '')
        return {"status": "success", "project_id": p['id'], "mission_id": None,
                "message": f"That's already under way: \"{p['title']}\". Tell me what to add to it."}
    if len(matches) > 1:
        return {"status": "ambiguous", "message": "Which one: " + '; '.join(p['title'] for p in matches) + "?"}
    # Create the project in the person's words (the body-goal rule inside).
    fields = {'title': (title or goal)[:80], 'goal': goal, 'done_when': '', 'owner_member_id': owner['id'], 'audience': audience}
    created = projects.create(fields, actor)
    if created['status'] != 'success':
        return {"status": "error", "message": created.get('message') or 'Could not start that project.'}
    project = created['project']
    if subject_kind:
        projects.add_piece(project['id'], subject_kind, subject_id, actor)
    if spoken:
        storage.update_project(project['id'], {'requester_provenance': voice_context.provenance()})
    # Plan inside it: a parent or adult's planning mission, bound before adoption.
    planning, reason, mission_id = 'started', '', None
    if actor.get('role') == 'child' or actor.get('is_child'):
        planning, reason = 'needs_parent', 'Ask a parent to plan it with Argyle.'
    else:
        res = _missions.launch('Help me plan the next part of this project: ' + project['title'], created_by=actor['id'],
                               project_id=project['id'], subject=('project', project['id']))
        if res.get('status') == 'launched':
            mission_id = res['mission_id']
            if spoken:
                storage.update_mission(mission_id, {'requester_provenance': voice_context.provenance()})
        else:
            planning, reason = 'off', (res.get('message') or 'Planning is off.').replace('Config → Missions', 'Projects settings')
    # The card comes first, in the owner's DM (and the actor's when they differ).
    argyle = storage.ensure_argyle_member()
    for m in {owner['id']: owner, actor['id']: actor}.values():
        member = storage.get_member(m['id'])
        card = projects.card(project, member, planning=planning, reason=reason) if member else None
        if card:
            body = f"Started a project: {project['title']}"
            _post_chat_message(storage.get_or_create_dm(argyle['id'], member['id']), argyle, body, card=card)
    _tri.set_focus(focus_key, 'project', project['id'], project.get('title') or '')
    tail = {'started': "I'll ask a couple of questions, then show you a plan.",
            'needs_parent': 'A parent can plan it with Argyle from the Projects page.',
            'off': reason}[planning]
    return {"status": "success", "project_id": project['id'], "mission_id": mission_id,
            "message": f"Started a project: \"{project['title']}\". {tail}"}
```

Notes for the implementer: `_resolve_named_member_or_refuse` is at `agent_tools_v2.py:2221`; `subjects.channel_humans` exists (`subjects.py`); `projects.create` returns `{'status': 'error', 'message': ...}` for a child's body goal (the body-goal rule), which is the refusal the test expects. `missions.launch` with missions off returns `{'status': 'disabled', 'message': 'Missions are switched off (Config → Missions).'}` — the card's reason must contain "Missions are off": map it explicitly: `reason = 'Missions are off (Projects settings).' if res.get('status') == 'disabled' else res.get('message')`.

- [ ] **Step 6: Project focus in `act_on_situation`**

Find it: `grep -n "def act_on_situation" services/agent_tools_v2.py`. At the top of the function, before the row is loaded:

```python
    if kind == 'project':
        from services import storage as _st, projects as _pj, missions as _ms
        project = _st.get_project(situation_id or '')
        if not project or not _pj.can_see(project, acting_member):
            return {"status": "error", "message": "That is no longer here."}
        live = [m for m in _pj._work_missions(project) if m.get('status') in _ms.LIVE]
        if len(live) != 1:
            return {"status": "error", "message": ("Nothing is running on that project right now." if not live else
                    "Which one: " + '; '.join((m.get('goal') or '')[:60] for m in live) + "?")}
        kind, situation_id = 'mission', live[0]['id']
```

The rest of the function then acts on the mission with verb `answer` as today (`missions.answer` records a steer when the mission is not waiting — `scenario_answer_when_not_waiting_is_a_steer` in `tests/test_start_mission.py` is the precedent).

- [ ] **Step 7: Run the tests**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_front_door_chat.py && python tests/test_situation_tools.py; python tests/test_triage.py 2>/dev/null || true`
Expected: `test_front_door_chat.py` all PASS; `test_situation_tools.py` unchanged from baseline (the pre-existing parity failure only). If `scenario_two_matches_ask_which` fails on the message assertion, both titles must appear in `out['message']`.

- [ ] **Step 8: Commit**

```bash
git add chauffeur/services/situations.py chauffeur/services/projects.py chauffeur/services/agent_tools_v2.py chauffeur/tests/test_front_door_chat.py
git commit -m "feat(projects): start_project - the project is created at once, its card posted first, planning inside it; project focus; dedupe by owner, subject and intent"
```

---

### Task 4: Declare `start_project`, retire the three chat tools from the declaration, reword the router

**Files:**
- Modify: `chauffeur/services/agent_tools_v2.py:4381` (`get_available_tools`: remove the `start_mission_for` (4956), `create_thread` (4979) and `propose_program` (5084) entries, add `start_project`), `:6563` (add `class StartProjectTool`), `:7121` (`TOOL_SCHEMAS`), `:8386` (`handle_start_project`), `:8748` (`REGISTRY_EXCEPTIONS`), `:8900` (`TOOL_HANDLERS`)
- Modify: `chauffeur/services/agent_router.py:316-346` (guidance), `:529` (`TERMINAL_ACTION_TOOLS`), `:1001` (dispatch branch)
- Modify: `chauffeur/services/voice_tools.py:7-8` (`TOOLS`)
- Modify tests: `chauffeur/tests/test_start_mission.py:56-84, 345-351`, `chauffeur/tests/test_registry_parity.py` (NEW_WRITES keeps `propose_program`; the declared-set scenario), `chauffeur/tests/test_subject_voice.py:53-62`, `chauffeur/tests/test_voice_identity.py:232`, `chauffeur/tests/test_project_portuguese.py`
- Test: `chauffeur/tests/test_front_door_router.py`

**Interfaces:**
- Consumes: `agent_tools_v2.start_project` (Task 3).
- Produces: `start_project` in `get_available_tools()`, `TOOL_SCHEMAS`, `TOOL_HANDLERS` (`handle_start_project(args, actor=None)`), `voice_tools.TOOLS`, `agent_router.TERMINAL_ACTION_TOOLS`; `start_mission_for`, `create_thread`, `propose_program` NOT in `get_available_tools()` but still in `TOOL_HANDLERS`/`TOOL_SCHEMAS`.

- [ ] **Step 1: Write the failing router tests**

```python
"""The router routes goals to start_project and nothing else (front door §1, Task 4).

Run from chauffeur/:  python tests/test_front_door_router.py
"""
from harness import check  # noqa: F401
from services import storage, agent_router, voice_tools
from services import agent_tools_v2 as tools
from test_front_door_chat import _fresh
from test_subjects import MOM


def _route(text, reply_tool, args, **kw):
    """One model round that calls `reply_tool`, then a concluding round."""
    orig = agent_router.call_gemma_with_fallback
    seen = {}

    def fake(prompt, tools_, system):
        seen.setdefault('declared', {t['name'] for t in tools_})
        seen.setdefault('system', system)
        if 'n' in seen:
            return {'tool_calls': [], 'message': 'done'}
        seen['n'] = 1
        return {'tool_calls': [{'name': reply_tool, 'arguments': args}], 'message': ''}
    agent_router.call_gemma_with_fallback = fake
    try:
        res = agent_router.process_agent_request(text, **kw)
    finally:
        agent_router.call_gemma_with_fallback = orig
    return res, seen


def scenario_the_declared_set():
    declared = {t['name'] for t in tools.get_available_tools()}
    check('start_project' in declared, "start_project is declared to chat")
    for name in ('start_mission_for', 'propose_program', 'create_thread'):
        check(name not in declared, f"{name} left the chat declaration")
        check(name in tools.TOOL_HANDLERS and name in tools.TOOL_SCHEMAS, f"{name} still reaches the registry for plans")
    check('start_project' in tools.TOOL_HANDLERS and 'start_project' in tools.TOOL_SCHEMAS, "registered")
    desc = next(t for t in tools.get_available_tools() if t['name'] == 'start_project')['description']
    for phrase in ('learn', 'fixed', 'pricing', 'enter'):
        check(phrase in desc.lower(), f"the description names the case: {phrase}")
    src = open('services/agent_router.py', encoding='utf-8').read()
    check('"start_project"' in src.split('TERMINAL_ACTION_TOOLS = {')[1].split('}')[0], "terminal")
    check('start_mission_for' not in src.split('ARGYLE ACTS IN THE WORLD')[1].split('SHARED SPEAKER')[0],
          "the acts-in-the-world paragraph names start_project, not the old tool")
    check('start_project' in voice_tools.TOOLS and 'start_mission_for' not in voice_tools.TOOLS, "voice allowlist")


def scenario_portuguese_through_the_router():
    _fresh()
    res, seen = _route('I want to learn Brazilian Portuguese', 'start_project', {'goal': 'I want to learn Brazilian Portuguese'},
                       source='pwa', acting_member=dict(MOM), focus_key='channel:dm1')
    check('propose_program' not in seen['declared'] and 'start_project' in seen['declared'], f"the model saw one door: {sorted(seen['declared'])[:5]}")
    rows = storage.get_projects()
    check(len(rows) == 1 and rows[0]['goal'] == 'I want to learn Brazilian Portuguese', f"a project, not a program: {rows}")
    check(res['message'].startswith('Started a project'), f"terminal reply: {res['message']}")


def scenario_a_direct_action_stays_direct():
    _fresh()
    res, seen = _route('assign Grandma to drive Barney to soccer tomorrow', 'propose_family_action',
                       {'summary': 'Assign Grandma to drive Barney to soccer tomorrow', 'action_type': 'reassign_driver', 'payload': {}},
                       source='pwa', acting_member=dict(MOM))
    check(storage.get_projects() == [], "no project for a direct action")
    check('start_project' in seen['system'] and 'propose_family_action' in seen['system'], "the guidance names both doors")


def scenario_voice_starts_a_household_project_as_the_parent_of_record():
    _fresh()
    res, seen = _route('get the dishwasher fixed', 'start_project', {'goal': 'get the dishwasher fixed'}, focus_key='voice:9')
    rows = storage.get_projects()
    check(len(rows) == 1 and rows[0]['audience'] == 'household' and rows[0]['owner_member_id'] == 'mom', f"voice: {rows}")
    check(res['message'].startswith('Started a project'), f"spoken reply: {res['message']}")


SCENARIOS = [scenario_the_declared_set, scenario_portuguese_through_the_router, scenario_a_direct_action_stays_direct,
             scenario_voice_starts_a_household_project_as_the_parent_of_record]

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
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_front_door_router.py`
Expected: all FAIL (`start_project` not declared).

- [ ] **Step 3: Declare the tool**

In `get_available_tools()` replace the `start_mission_for` entry (4956-4964) with:

```python
        {
            "name": "start_project",
            "description": "The one door for anything that takes steps, time, research, a company, a teacher or a practice plan: 'I want to learn Brazilian Portuguese', 'get the dishwasher fixed', 'renovate the bathroom', 'start Ben on a couch to 5k', 'go on their website and enter our details to get appointment times and pricing', 'get a quote from X'. Starts a PROJECT at once (the person sees its card and can rename it or say it is not a project), then Argyle asks a couple of questions and shows a plan inside it; a program, outside conversations and Argyle's own work fall out of the plan. Argyle CAN browse a company's website and fill its forms with the family's details (released by a parent first) to reach prices, slots and quotes; it stops short of booking or paying. Never for a change to the schedule or a record right now (assign a driver, add an item, send a message): those are direct tools or propose_family_action. Anyone for themselves; naming someone else is parent/adult only.",
            "parameters": {"type": "object",
                           "properties": {"goal": {"type": "string", "description": "What they want, in their words."},
                                          "title": {"type": "string", "description": "A short name, if they gave one."},
                                          "for_member_name": {"type": "string", "description": "Whose project, if not the caller's own."},
                                          "subject_kind": {"type": "string", "description": "The subject kind from find_in_chauffeur, when the goal names something the family already has."},
                                          "subject_id": {"type": "string", "description": "The subject id from find_in_chauffeur."}},
                           "required": ["goal"]}
        },
```

Delete the `create_thread` entry (4979-4995) and the `propose_program` entry (5084-5097) from `get_available_tools()` only. Keep `launch_mission` (5039) declared but reword its description's "use start_mission_for, which opens the thread too" to "use start_project".

Add beside `StartMissionForTool` (6563):

```python
class StartProjectTool(BaseModel):
    """Start a project for anything that takes steps, time or people outside the family; Argyle plans inside it."""
    goal: str = Field(..., description="What they want, in their words.")
    title: Optional[str] = Field(None, description="A short name, if given.")
    for_member_name: Optional[str] = Field(None, description="Whose project, if not the caller's own.")
    subject_kind: Optional[str] = Field(None, description="The subject kind from find_in_chauffeur.")
    subject_id: Optional[str] = Field(None, description="The subject id from find_in_chauffeur.")
```

`TOOL_SCHEMAS` gains `"start_project": StartProjectTool.model_json_schema(),`. Add after `handle_start_mission_for`:

```python
def handle_start_project(args: dict, actor=None) -> dict:
    return start_project(args.get('goal') or '', title=args.get('title'), for_member_name=args.get('for_member_name'),
                         acting_member=actor or _registry_parent(),
                         subject_kind=args.get('subject_kind'), subject_id=args.get('subject_id'))
```

`TOOL_HANDLERS` gains `"start_project": handle_start_project,`. In `services/planned.py` `CONTRACT`, add `'start_project': _contract(creates='project'),` only if the registry-parity test demands a contract row for every handler (read `tests/test_stage_contract.py` first); otherwise leave plans without it — a plan plans inside its own project.

- [ ] **Step 4: The router**

`services/agent_router.py`:
- `TERMINAL_ACTION_TOOLS` (529): replace `"start_mission_for",` with `"start_project",` (keep the comment).
- Dispatch branch (1001): add `"start_project",` to the tuple beside `"start_mission_for"` (both stay dispatchable; a plan or a test may still call the old one).
- Guidance (316-330): rewrite the ARGYLE ACTS IN THE WORLD block:

```python
    system_prompt += ("\nARGYLE ACTS IN THE WORLD through projects. One rule: a request that changes the schedule or a "
                      "record RIGHT NOW (reassign a driver, add a list item, send a message, claim a chore, add an errand) "
                      "is a direct tool or propose_family_action; anything that takes steps, time, research, a company, a "
                      "teacher or a practice plan ('I want to learn Portuguese', 'get the dishwasher fixed', 'renovate the "
                      "bathroom', 'get times and pricing', 'enter my information', 'get a quote', 'start Ben on a couch to 5k') "
                      "is start_project: the project is created at once and Argyle plans inside it. Inside a project Argyle "
                      "can browse a company's website and fill its forms with the family's details (a parent releases them "
                      "first) to get appointment times, prices and quotes, search the family's own mailbox, and read a photo "
                      "a person adds. It never books, pays, submits or sends on its own. Never say you cannot browse the web "
                      "or fill out forms. A plain web question with no site to act on is research. Before start_project for "
                      "a goal that names something the family already has (a trip, a party, an event, a person, a list), call "
                      "find_in_chauffeur and pass the winner as subject_kind and subject_id; if it returns more than one, ask which. "
                      'A correction or new preference about work already running on the project we are talking about '
                      '("use the manufacturer instead", "not that company", "only mornings") is act_on_situation with verb answer '
                      'on that project, never a new project. '
                      + release_instruction)
```

- Voice line (346): `"A household request can start a project with start_project.\n"`.

`services/voice_tools.py` `TOOLS`: replace `'start_mission_for'` with `'start_project'`.

- [ ] **Step 5: Update the tests that pinned the old door**

- `tests/test_start_mission.py` `scenario_declared_dispatched_terminal`: the first `check` becomes `check('start_mission_for' not in decl and 'start_mission_for' in tools.TOOL_HANDLERS and 'start_mission_for' in tools.TOOL_SCHEMAS, "registry only")`; the terminal check becomes `'"start_project"'`; the fake's tool call becomes `start_project` with the same goal, and the final check `res['message'].startswith('Started a project')` with `storage.get_missions()[0]['created_by'] == 'mom'`.
- `tests/test_start_mission.py` `scenario_the_model_is_told_argyle_acts_on_websites`: `'start_project' in src`; the description lookup uses `start_project` and asserts `'enter'` and `'pricing'`.
- `tests/test_subject_voice.py:53-62` and `tests/test_voice_identity.py:232`: `voice_tools.dispatch('start_project', {...})`; the assertions on the opened thread become assertions on the project (`storage.get_projects()[0]['pieces']` holds the subject when one was speakable; a non-speakable subject is dropped exactly as before).
- `tests/test_registry_parity.py`: no change expected (`propose_program` stays in `TOOL_HANDLERS` and `NEW_WRITES`; `scenario_nothing_else_opens` still fakes `propose_program` on the propose-only rail — the rail refuses by name, declared or not). Run it; if `scenario_every_declared_tool_has_a_registry_handler_or_a_reason` flags `start_project`, it is registered by Step 3, so it passes.
- `tests/test_project_portuguese.py`: replace the direct `_mission` + `storage.update_mission(goal)` opening with `out = tools.start_project('I want to learn Portuguese', acting_member=dict(MOM)); mid = out['mission_id']; pid = out['project_id']`, and after approval assert `len(storage.get_projects()) == 1` and the steps landed on `pid` (the plan appends; the `_plan` call drops its `'project'` key).

- [ ] **Step 6: Run the gate**

Run from `chauffeur/` with `HA_BASE_URL` unset: `python tests/test_front_door_router.py && python tests/test_front_door_chat.py && python tests/test_start_mission.py && python tests/test_registry_parity.py && python tests/test_subject_voice.py && python tests/test_voice_identity.py && python tests/test_project_portuguese.py && python tests/test_planned_piano.py && python tests/test_stage_contract.py && python tests/test_stage_contract_tools.py && python tests/test_mission_subject.py`
Expected: all PASS except the pre-existing `test_situation_tools` parity (not in this list) and `test_app_voice` errors.

- [ ] **Step 7: Commit**

```bash
git add chauffeur/services/agent_tools_v2.py chauffeur/services/agent_router.py chauffeur/services/voice_tools.py chauffeur/services/planned.py chauffeur/tests/test_front_door_router.py chauffeur/tests/test_start_mission.py chauffeur/tests/test_subject_voice.py chauffeur/tests/test_voice_identity.py chauffeur/tests/test_project_portuguese.py
git commit -m "feat(projects): one chat door - start_project declared, start_mission_for, propose_program and create_thread leave the chat declaration, router guidance rewritten"
```

---

### Task 5: The project card on the phone

**Files:**
- Modify: `chauffeur/templates/app.html:5236-5241` (`renderCard`), add `renderProjectCard` beside `renderMissionDoneCard` (~5285)
- Create: `chauffeur/tests/test_project_card_live.py` (jsdom node run through `tests/test_planned_mission_cards.py`'s `_chunk` / `_run` helpers)
- Run: `python tools/build_tailwind.py` after the template change

**Interfaces:**
- Consumes: the `project` card shape from `projects.card` (Task 3): `project_id, title, goal, owner_label, audience, audience_label, state, planning, reason, can_edit, body_goal`.
- Produces: card buttons calling existing routes: Rename → `PATCH /api/projects/{id}` `{title}` via `promptInput`; audience → `PATCH /api/projects/{id}` `{audience}`; Not a project → `promptConfirm` then `POST /api/projects/{id}/state` `{state: 'dropped'}`. Both routes act as the signed-in member (`main.py:6038`, `:6049`) so a child may act on their own card.

- [ ] **Step 1: Write the failing node test.** `tests/test_planned_mission_cards.py` runs the app's own `renderCard` under jsdom: `_chunk()` (line 106) cuts the source from `function renderCard(card)` to the end of the card renderers, `_run()` (161) writes a node script with a `cases` dict, calls `renderCard` on each and returns `out[k]` HTML. Create `tests/test_project_card_live.py` importing those two helpers (`from test_planned_mission_cards import _chunk, _run_cases` — if `_run` is not parameterised, copy it as `_run_cases(cases) -> dict` taking the cases dict) with:

```python
"""The project chat card renders from the app's own renderCard (front door §1, Task 5).

Run from chauffeur/:  python tests/test_project_card_live.py
"""
from harness import check  # noqa: F401
from test_planned_mission_cards import _chunk, _run_cases

CARD = {'kind': 'project', 'project_id': 'p1', 'title': 'Learn Portuguese', 'goal': 'I want to learn Brazilian Portuguese',
        'owner_label': 'Mom', 'audience': 'private', 'audience_label': 'Private', 'state': 'active',
        'planning': 'started', 'reason': '', 'can_edit': True, 'body_goal': False}


def scenario_project_card_renders():
    out = _run_cases({'base': CARD, 'xss': {**CARD, 'title': '<script>x</script>'},
                      'off': {**CARD, 'planning': 'off', 'reason': 'Missions are off (Projects settings).'},
                      'kid': {**CARD, 'planning': 'needs_parent', 'reason': 'Ask a parent to plan it with Argyle.', 'audience': 'parents'},
                      'body': {**CARD, 'body_goal': True},
                      'done': {**CARD, 'state': 'dropped'}})
    for text in ('Learn Portuguese', 'I want to learn Brazilian Portuguese', 'Private', 'Rename', 'Not a project', 'Share with parents'):
        check(text in out['base'], f"the card shows {text}: {out['base'][:200]}")
    check('<script' not in out['xss'], "escaped")
    check('Missions are off' in out['off'], "says why planning is off")
    check('Ask a parent' in out['kid'], "a kid's card says who plans it")
    check('Share with' not in out['body'], "a body goal cannot leave private")
    check('Not a project' not in out['done'], "a dropped project offers no buttons")
    check("projectCardDrop('p1')" in out['base'], "Not a project calls the drop handler")


def scenario_the_handlers_hit_the_project_routes():
    src = _chunk()
    drop = src.split('async function projectCardDrop')[1].split('async function')[0] if 'async function projectCardDrop' in src else ''
    check("/state" in drop and "state: 'dropped'" in drop and 'promptConfirm' in drop, f"drop posts state=dropped after a promptConfirm: {drop[:300]}")
    rename = src.split('async function projectCardRename')[1].split('async function')[0] if 'async function projectCardRename' in src else ''
    check('promptInput' in rename and 'PATCH' in src.split('async function projectCardPatch')[1].split('async function')[0], "rename prompts and patches")
    check('confirm(' not in drop and 'prompt(' not in rename.replace('promptInput(', ''), "no browser dialogs")


SCENARIOS = [scenario_project_card_renders, scenario_the_handlers_hit_the_project_routes]

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
    raise SystemExit(1 if failed else 0)
```

If `_chunk()`'s end marker stops before the new `renderProjectCard`, move the new functions to sit between `renderCard` and that marker (read `_chunk` first; it slices on a fixed function name).

- [ ] **Step 2: Run to verify failure**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_card_live.py`
Expected: FAIL — `renderCard` returns `''` for kind `project`.

- [ ] **Step 3: Render the card**

In `renderCard` add `if (card.kind === 'project') return renderProjectCard(card);` before the `action_proposal` line. Add:

```javascript
        function renderProjectCard(card) {
            const ladder = [];
            if (card.can_edit && !card.body_goal) {
                if (card.audience !== 'private') ladder.push(['private', 'Make private']);
                if (card.audience !== 'parents') ladder.push(['parents', 'Share with parents']);
                if (card.audience !== 'household' && myRole() !== 'child') ladder.push(['household', 'Share with the household']);
            }
            const note = card.planning === 'started' ? 'Argyle will ask a couple of questions, then show a plan.' : (card.reason || '');
            const buttons = card.can_edit && card.state === 'active' ? `<div class="flex flex-wrap gap-2 mt-2">
                <button onclick="projectCardRename('${mfEscape(card.project_id)}')" class="px-3 py-1 rounded-lg text-xs font-semibold bg-gray-700 text-gray-200">Rename</button>
                ${ladder.map(([a, label]) => `<button onclick="projectCardAudience('${mfEscape(card.project_id)}','${a}')" class="px-3 py-1 rounded-lg text-xs font-semibold bg-gray-700 text-gray-200">${label}</button>`).join('')}
                <button onclick="projectCardDrop('${mfEscape(card.project_id)}')" class="px-3 py-1 rounded-lg text-xs font-semibold bg-gray-800 text-gray-400 border border-gray-700">Not a project</button>
            </div>` : '';
            return `<div class="mt-1 px-3 py-2 rounded-xl bg-gray-900 border border-gray-700" data-project-card="${mfEscape(card.project_id)}">
                <div class="flex items-center gap-2"><span class="text-xs uppercase tracking-wide text-teal-300 font-bold">Project</span>
                    <span class="px-1.5 py-0.5 rounded text-xs bg-gray-800 text-gray-300">${mfEscape(card.audience_label || '')}</span></div>
                <div class="text-sm text-gray-100 font-semibold mt-1">${mfEscape(card.title || '')}</div>
                <div class="text-xs text-gray-300 mt-0.5">${mfEscape(card.goal || '')}</div>
                <div class="text-xs text-gray-500 mt-0.5">${mfEscape(card.owner_label || '')}${card.state !== 'active' ? ' · ' + mfEscape(card.state) : ''}</div>
                ${note ? `<div class="text-xs text-gray-400 mt-1">${mfEscape(note)}</div>` : ''}${buttons}</div>`;
        }
        async function projectCardPatch(id, body) {
            const r = await fetch(`${apiBase}api/projects/${encodeURIComponent(id)}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
            if (!r.ok) showGlobalAlert('Could not change that project.');
        }
        async function projectCardRename(id) {
            const title = await promptInput('Rename the project', '');
            if (title && title.trim()) await projectCardPatch(id, {title: title.trim()});
        }
        async function projectCardAudience(id, audience) { await projectCardPatch(id, {audience}); }
        async function projectCardDrop(id) {
            if (!await promptConfirm('Not a project? This drops it and stops Argyle’s planning.')) return;
            const r = await fetch(`${apiBase}api/projects/${encodeURIComponent(id)}/state`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({state: 'dropped'})});
            if (!r.ok) showGlobalAlert('Could not drop that project.');
        }
```

Plain JSON headers, as `actOnProposal` (`app.html:5437`) sends them: the PWA's session identifies the member. `promptInput` / `promptConfirm` / `showGlobalAlert` come from `templates/components/control_center.html` which `app.html` includes.

- [ ] **Step 4: Rebuild Tailwind and run**

Run: `cd chauffeur && python tools/build_tailwind.py && unset HA_BASE_URL && python tests/test_project_card_live.py && python tests/test_planned_mission_cards.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/templates/app.html chauffeur/static/tailwind.css chauffeur/tests/test_project_card_live.py
git commit -m "feat(projects): the project chat card on the phone - Rename, the audience ladder, Not a project"
```

---

### Task 6: Audience sweep, documentation

**Files:**
- Test: `chauffeur/tests/test_front_door_audience.py`
- Modify: `chauffeur/system_capabilities.md` (top block), `docs/superpowers/specs/2026-10-15-projects-front-door-design.md` (status line: slice 1 BUILT)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the audience tests**

```python
"""Every new surface that carries a project's words checks the audience (front door §5, Task 6).

Run from chauffeur/:  python tests/test_front_door_audience.py
"""
from harness import check  # noqa: F401
from services import storage
from services import agent_tools_v2 as tools
from test_front_door_chat import _fresh, _dm_cards
from test_subjects import MOM, DAD, AUNT, KID


def _p():
    from services import projects
    return projects


def scenario_the_card_follows_the_audience():
    _fresh()
    out = tools.start_project('get down to 185 lbs', acting_member=dict(MOM))
    p = storage.get_project(out['project_id'])
    check(_p().card(p, dict(DAD)) is None and _p().card(p, dict(KID)) is None, "a private body goal has no card for anyone else")
    check(_dm_cards('dad') == [], "and nothing in Dad's DM")
    kid = tools.start_project('learn to ride a bike', acting_member=dict(KID))
    kp = storage.get_project(kid['project_id'])
    check(_p().card(kp, dict(MOM)) and _p().card(kp, dict(AUNT)) is None, "a kid's project: parents yes, another adult no")


def scenario_the_wrapped_record_narrows_only():
    _fresh()
    from services import threads
    tid = threads.create(title='Pest control', owner_member_id='aunt', created_by='aunt')
    p = storage.get_project(storage.get_thread(tid)['project_id'])
    check(p['audience'] == 'private' and _p().can_see(p, dict(MOM)) and not _p().can_see(p, dict(KID)),
          "an adult's wrapped thread: parents see it (as they saw the thread), a child does not")
    from services import situations
    check(situations.can_see('thread', storage.get_thread(tid), dict(MOM)), "the thread itself is seen exactly as before")


def scenario_the_focus_never_leaks_in_a_shared_channel():
    _fresh()
    from services import subjects, triage
    out = tools.start_project('plan a surprise for Kate', acting_member=dict(MOM), focus_key='channel:dm1')
    orig = subjects.channel_humans
    subjects.channel_humans = lambda key: [dict(MOM), dict(KID)] if key == 'channel:fam' else orig(key)
    try:
        res = tools.list_projects(acting_member=dict(MOM), focus_key='channel:fam')
    finally:
        subjects.channel_humans = orig
    check('surprise' not in (res.get('message') or ''), f"list_projects in the family channel says nothing of it: {res}")


SCENARIOS = [scenario_the_card_follows_the_audience, scenario_the_wrapped_record_narrows_only, scenario_the_focus_never_leaks_in_a_shared_channel]

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
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_front_door_audience.py`
Expected: PASS if Tasks 1-4 hold; a failure here is a defect in those tasks, fixed there.

- [ ] **Step 3: Document**

In `chauffeur/system_capabilities.md` replace the NEXT block's slice-1 sentence with a BUILT entry: the invariant (`project_id` on every thread, mission, program; `projects.adopt`; the one-time migration `adopt_existing`, closed rows into done/dropped projects), `start_project` (card first, planning inside, child waits for a parent, dedupe by owner + subject + intent, spoken-safe voice, channel refusal), the declared set change, the project focus, the card's three options, and the test files. Update the spec's header status: "Slice 1 BUILT (version), slices 2 and 3 pending."

- [ ] **Step 4: Commit**

```bash
git add chauffeur/tests/test_front_door_audience.py chauffeur/system_capabilities.md docs/superpowers/specs/2026-10-15-projects-front-door-design.md
git commit -m "test(projects): front door audience sweep; document slice 1"
```

(Claude bumps `chauffeur/config.yaml` and amends the version into the capabilities line at the final gate.)

---

## Build split (the user's standing rule)

- Claude writes every test file first (Tasks 1-6 Step 1) and commits them red.
- Codex (`codex:rescue`, background) takes **Task 1** (adopt, the create-path threading, planned row injection) and **Task 2** (migration), with `tests/test_project_adopt.py` as the contract and the gate list above.
- Claude builds **Task 3** (`start_project`, situations/triage kind), **Task 4** (declaration, router guidance, voice allowlist, test updates) and **Task 5** (the card template).
- Task 6 is Claude's; whoever did not write a task reviews it (`/codex:review --base <ref>` on Claude's diffs; Claude's read plus the gate on Codex's).
