# Projects Front Door — Slice 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One Projects page with lanes opens a project detail whose pieces are cards; a thread, mission or program opens in a sheet that carries everything its old page could do; then the Threads, Missions and Programs pages retire behind redirects and their settings move into the Projects drawer — the retirement only after a parity test is green.

**Architecture:** Server: `services/projects.py` gains `piece_cards`, `lane`, `overview_row`, `elsewhere`, `locate`; four read endpoints and a `project_id` on the three create endpoints. Admin: a new `components/record_sheet.html` (framed like the settings drawer) mounts the three EXISTING components in a `sheet_mode` that shows one record at a time, so every control the old page had is the same markup in the sheet. Phone: the Projects tab dispatches the same event and `app.html` draws the piece in its `_pwaModal` action sheet with the phone's own builders. Retirement: settings sections move into partials rendered in one Projects drawer; old addresses redirect to `projects?piece=<kind>:<id>`, which the page resolves through an audience-checked lookup.

**Tech Stack:** Python 3 / FastAPI, Jinja2 templates, vendored Alpine 3, vanilla JS (`static/situations.js`, `static/mission_transcript.js`), precompiled Tailwind (`tools/build_tailwind.py`), plain-script tests under `chauffeur/tests/` with `harness.check`, Playwright live tests through `tests/live_app.py`.

**Spec:** `docs/superpowers/specs/2026-10-15-projects-front-door-design.md` Sections 2, 3 and 5 (slice 2), with the parity inventory `docs/superpowers/specs/2026-10-15-projects-front-door-inventory.md`. Slice 1 (built v2.499.518) gives every thread, mission and program a `project_id`.

## Decisions this plan makes (each is a ruling under the approved spec)

1. **A sheet body is the existing component in `sheet_mode`, not a rebuild.** `threads_page.html`, `missions_page.html` and `programs_page.html` take a Jinja `sheet_mode` flag: the page title, intro, settings drawer and create form are skipped (`{% if not _sheet %}{# sheet:hide #}…{% endif %}{# /sheet:hide #}`), the list shows only the record the sheet asks for, and its details open. Every other control is the same markup, so parity is structural and the parity test can prove it.
2. **The admin hosts mount the record sheet; the phone draws its own.** `projects_page.html` stays host-agnostic and only dispatches `chf-record-sheet-open`. `work.html` and `projects.html` include `components/projects_admin.html` (the record sheet, later the drawer). The phone app has none of `MissionTranscript`, `settings_drawer.js` or `chfPersonToken`, and Decision 8 keeps the phone's surfaces, so `app.html` answers the event with the phone's own builders (`Situations.cardHtml` plus the House thread note and photo; `renderProgramCard`) in `_pwaModal`.
3. **Old links resolve in the page, never in the redirect.** `/threads?id=T` redirects to `projects?piece=thread:T`; the page asks `GET /api/projects/for/thread/T` (signed in, audience-checked) and opens the project and the sheet, the record alone (a keeper), or says it is not here. The shell redirect never names a project.
4. **Settings move as partials inside one Projects drawer.** Each component's drawer sections move into `components/{threads,missions,programs}_settings.html`; the Projects drawer renders each partial inside a small island that uses the owning component's own `x-data` function with a settings-only init, so every input keeps its save method. This happens in the retirement task, because two drawers holding the same anchors on one page would collide.
5. **Lanes are computed on the server** (`projects.lane`), once per viewer, and returned with the list, so the phone and the admin page agree.
6. **"Something already in Chauffeur" from the project side searches** (`GET /api/subjects/search?q=` over `subjects.find_all`); the record-side "Add to a project" picker stays as it is.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts: `python tests/test_x.py`, `HA_BASE_URL` unset. Never run the whole suite.
- Pre-existing failures, not ours: `tests/test_situation_tools.py` scenario_parity_both_ways; `tests/test_agent_v2_bridge.py` "missing send_direct_message".
- No browser dialogs: `showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice` only.
- After any template class change: `python tools/build_tailwind.py`.
- UI work reads `chauffeur/docs/ui_design_guide.md` first; same concept = same builder; every UI task ends with a screenshot from its live test (`PROJECTS_SHOTS=<scratchpad dir>`), dark theme, looked at before the commit.
- A component on an admin page reads identity through `chfPersonToken()` / `chfPersonId()`, never the PWA keys.
- Every new route needs a rule in `services/auth.py` (the `/api/projects/*` and `/api/subjects/*` SIGNED_IN wildcards already cover the new ones; page redirects are ANYONE like the pages they replace).
- A project's or record's words reach only a viewer who may see them (`projects.can_see`, `situations.can_see`, `subjects.visible`), in a channel only if every person there may.
- Never remove anything a person can do: the three pages retire only when `tests/test_projects_parity.py` is green (Task 6). Tasks 7 and 8 do not start before that.
- Vendored Alpine: coerce every `:disabled` with `!!`.
- Do not bump `chauffeur/config.yaml` and do not commit from a Codex task.

## Review Focus

1. A viewer who may see a record but not its project (a mission keeper) follows an old link: they get the record alone in the sheet, never a 404 and never the project's words — Task 3 `scenario_a_keeper_gets_the_record_alone`.
2. A closed (done or dropped) thread opened in the sheet: it shows, with its history, even though the old page folds closed rows away — Task 3 `scenario_a_closed_thread_opens_in_the_sheet`.
3. Opening a second record of the same kind while the sheet is open: only the new record shows, its details open, nothing of the first one lingers — Task 3 `scenario_switching_records_shows_only_the_new_one`.
4. A child on the project detail: no Open on a mission they may not see, no "Work for Argyle" or "A conversation with someone outside" in Add a piece — Tasks 1 and 2 `scenario_a_child_sees_only_their_pieces`, `scenario_add_a_piece_for_a_child`.
5. An old bookmark with no id (`/threads`, `/programs`) lands on Projects, the programs one with the Programs filter on — Task 7 `scenario_bookmarks_without_an_id`.

---

### Task 1: The server side of the detail page (Codex)

**Files:**
- Modify: `chauffeur/services/projects.py` (`view` ~line 900: mission pieces; new functions after `card`)
- Modify: `chauffeur/main.py` (`projects_list` ~6004; new routes right after it and before `project_detail`; `create_thread` ~6975; `missions_launch` ~6292; `create_program` ~7350)
- Test: `chauffeur/tests/test_project_pieces.py`

**Interfaces:**
- Produces: `projects.SHEET_KINDS = ('thread', 'mission', 'program')`; `projects.piece_cards(project, viewer) -> list[dict]` — each `{kind, id, title, link, sheet: bool, situation?: dict, program?: {state, member_id, phase}}`; `projects.lane(project, viewer, cards=None) -> str` in `projects.LANES = ('needs_you', 'moving', 'waiting', 'paused', 'closed')`; `projects.overview_row(project, viewer) -> dict` = `view(...)` plus `lane`, `card_next`, `has_program`, `needs_plan`; `projects.elsewhere(viewer) -> list[dict]` (situation views); `projects.locate(kind, record_id, viewer) -> {'project_id': str|None, 'record_visible': bool}`.
- Produces routes: `GET /api/projects` rows are `overview_row`; `GET /api/projects/elsewhere` → `{'situations': [...]}`; `GET /api/projects/for/{kind}/{record_id}` → `locate(...)`; `GET /api/projects/{project_id}/pieces` → `{'pieces': [...]}`; `GET /api/subjects/search?q=` → `{'candidates': [{kind, id, title}]}`; `POST /api/threads`, `POST /api/missions/launch`, `POST /api/programs` accept `project_id` (403 unless the caller `can_act` on that project).

- [ ] **Step 1: Write the failing test** `chauffeur/tests/test_project_pieces.py`:

```python
"""The detail page's server side (front door spec §2, slice 2, Task 1).

  * piece cards: one per piece the viewer may see, drawn by kind; missions are
    pieces too; a thread or mission card carries its situation view;
  * lanes: closed, paused, needs you (a question, a decision, a program to
    approve, a child's project with no plan), moving, waiting;
  * your work elsewhere: a keeper's missions whose project they may not see;
  * locate: where an old link lands, audience-checked;
  * creating inside a project: only into a project you may change.

Run from chauffeur/:  python tests/test_project_pieces.py
"""
from fastapi import HTTPException

from harness import check  # noqa: F401
from services import storage, missions, threads
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID
from test_subject_audience import _as


def _p():
    from services import projects
    return projects


def _bath():
    return _p().create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'tiled', 'owner_member_id': 'mom',
                        'audience': 'household'}, dict(MOM))['project']


def scenario_piece_cards_by_kind():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', goal='tile by May', created_by='mom', project_id=p['id'])
    mid = missions.launch('find three tilers', created_by='mom', project_id=p['id'])['mission_id']
    _p().add_piece(p['id'], 'list', 'l1', dict(MOM))
    cards = {c['kind']: c for c in _p().piece_cards(storage.get_project(p['id']), dict(MOM))}
    check(set(cards) == {'thread', 'mission', 'list'}, f"one card per kind: {sorted(cards)}")
    check(cards['thread']['sheet'] and cards['thread']['situation']['id'] == tid, "a thread opens in the sheet, with its situation")
    check(cards['mission']['sheet'] and cards['mission']['title'] == 'find three tilers' and cards['mission']['situation'],
          f"a mission is a piece now: {cards['mission']}")
    check(not cards['list']['sheet'] and cards['list']['link'], "a list keeps its own page")


def scenario_a_child_sees_only_their_pieces():
    _fresh()
    p = _bath()
    missions.launch('find three tilers', created_by='mom', project_id=p['id'])
    threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    kinds = [c['kind'] for c in _p().piece_cards(storage.get_project(p['id']), dict(KID))]
    check('mission' not in kinds and 'thread' not in kinds, f"a child sees no mission or thread of the house: {kinds}")


def scenario_a_hidden_mission_is_not_a_card():
    _fresh()
    p = _bath()
    mid = missions.launch('buy the secret gift', created_by='mom', project_id=p['id'])['mission_id']
    storage.update_mission(mid, {'subject_kind': 'list', 'subject_id': 'l2', 'subject_rev': 1})   # Mom's private list
    kinds = [c['id'] for c in _p().piece_cards(storage.get_project(p['id']), dict(DAD))]
    check(mid not in kinds, "Dad never sees the mission he may not see")


def scenario_lanes():
    _fresh()
    p = _bath()
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'waiting', "nothing to do: waiting")
    _p().add_step(p['id'], {'title': 'Pick the tile', 'owner': 'mom'}, dict(MOM))
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'moving', "Mom's own next step: moving")
    check(_p().lane(storage.get_project(p['id']), dict(DAD)) == 'waiting', "for Dad it is waiting")
    _p().set_state(p['id'], 'paused', dict(MOM))
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'paused', "paused")
    _p().set_state(p['id'], 'done', dict(MOM))
    check(_p().lane(storage.get_project(p['id']), dict(MOM)) == 'closed', "closed")
    kid = _p().create({'title': 'Ride a bike', 'goal': 'ride', 'done_when': 'x', 'owner_member_id': 'kid'}, dict(KID))['project']
    check(_p().lane(storage.get_project(kid['id']), dict(MOM)) == 'needs_you', "a child's unplanned project needs a parent")
    check(_p().lane(storage.get_project(kid['id']), dict(KID)) == 'waiting', "the child waits for it")
    q = _bath()
    storage.add_program({'id': 'prq', 'member_id': 'mom', 'title': 'Tiling basics', 'state': 'proposed'})
    _p().adopt('program', 'prq', dict(MOM), project_id=q['id'])
    check(_p().lane(storage.get_project(q['id']), dict(MOM)) == 'needs_you', "a program to approve needs a parent")


def scenario_the_overview_row():
    _fresh()
    p = _bath()
    storage.add_program({'id': 'pr1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active'})
    _p().adopt('program', 'pr1', dict(MOM), project_id=p['id'])
    import main
    rows = {r['id']: r for r in main.projects_list(request=_as('mom'))['projects']}
    row = rows[p['id']]
    check(row['lane'] == 'waiting' and row['has_program'] is True and 'card_next' in row, f"overview row: {row}")


def scenario_your_work_elsewhere():
    _fresh()
    hidden = _p().create({'title': 'Surprise', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']
    mid = missions.launch('book the venue', created_by='aunt', project_id=hidden['id'])['mission_id']
    rows = _p().elsewhere(dict(AUNT))
    check([r['id'] for r in rows] == [mid], f"Aunt keeps her mission's row: {rows}")
    check(_p().elsewhere(dict(MOM)) == [], "Mom sees it in its project, not elsewhere")


def scenario_locate():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    check(_p().locate('thread', tid, dict(MOM)) == {'project_id': p['id'], 'record_visible': True}, "Mom: the project and the record")
    hidden = _p().create({'title': 'Surprise', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']
    mid = missions.launch('book the venue', created_by='aunt', project_id=hidden['id'])['mission_id']
    check(_p().locate('mission', mid, dict(AUNT)) == {'project_id': None, 'record_visible': True}, "a keeper: the record alone")
    check(_p().locate('thread', tid, dict(KID)) == {'project_id': None, 'record_visible': False}, "a child: nothing")
    check(_p().locate('thread', 'nope', dict(MOM)) == {'project_id': None, 'record_visible': False}, "a missing record: nothing")
    check(_p().locate('trip', 'x', dict(MOM)) == {'project_id': None, 'record_visible': False}, "a kind with no sheet: nothing")


def scenario_routes():
    _fresh()
    import main
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'])
    check(main.projects_for_record('thread', tid, request=_as('mom'))['project_id'] == p['id'], "for route")
    check(main.project_pieces(p['id'], request=_as('mom'))['pieces'][0]['id'] == tid, "pieces route")
    check(main.projects_elsewhere(request=_as('mom')) == {'situations': []}, "elsewhere route")
    found = main.subjects_search(q='Bathroom', request=_as('mom'))['candidates']
    check(isinstance(found, list) and all(set(c) == {'kind', 'id', 'title'} for c in found), f"search answers kind, id, title only: {found}")
    check(main.subjects_search(q='  ', request=_as('mom')) == {'candidates': []}, "an empty search finds nothing")


def scenario_creating_inside_a_project():
    _fresh()
    import main
    p = _bath()
    out = main.create_thread(body={'title': 'Plumber', 'project_id': p['id']}, request=_as('mom'))
    check(storage.get_thread(out['id'])['project_id'] == p['id'], "a thread made inside the project")
    private = _p().create({'title': 'Mine', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom'}, dict(MOM))['project']
    try:
        main.create_thread(body={'title': 'Sneaky', 'project_id': private['id']}, request=_as('dad'))
        check(False, "Dad may not add to Mom's private project")
    except HTTPException as e:
        check(e.status_code == 403, f"refused: {e.status_code}")
    res = main.missions_launch(body={'goal': 'find three tilers', 'tier': 'flash', 'project_id': p['id']}, request=_as('mom'))
    m = storage.get_mission(res['mission_id'])
    check(m['project_id'] == p['id'] and missions.subject_of(m)[:2] == ('project', p['id']), f"launched inside it: {m}")


SCENARIOS = [scenario_piece_cards_by_kind, scenario_a_child_sees_only_their_pieces, scenario_a_hidden_mission_is_not_a_card,
             scenario_lanes, scenario_the_overview_row, scenario_your_work_elsewhere, scenario_locate, scenario_routes,
             scenario_creating_inside_a_project]

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

- [ ] **Step 2: Run it to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_pieces.py`
Expected: every scenario FAILS (`AttributeError: module 'services.projects' has no attribute 'piece_cards'` and friends).

- [ ] **Step 3: Mission pieces in `projects.view`**

In `projects.view`, the piece loop becomes:

```python
    result['pieces'] = []
    for piece in project.get('pieces') or []:
        kind, sid = piece.get('kind'), piece.get('id')
        if kind == 'mission':
            # Missions have no subject adapter (they are never what something is
            # ABOUT), so their piece reads the mission row and its own audience.
            from services import situations
            row = storage.get_mission(sid)
            if row is not None and situations.can_see('mission', row, viewer):
                result['pieces'].append({'kind': kind, 'id': sid, 'title': (row.get('goal') or '')[:80],
                                         'link': f'projects?piece=mission:{sid}'})
            continue
        row = subjects.load(kind, sid)
        if row is not None and subjects.visible(kind, row, viewer):
            result['pieces'].append({'kind': kind, 'id': sid,
                                     'title': subjects.title_of(kind, row),
                                     'link': subjects.link(kind, sid)})
```

- [ ] **Step 4: The new functions** — append after `card` in `services/projects.py`:

```python
SHEET_KINDS = ('thread', 'mission', 'program')
LANES = ('needs_you', 'moving', 'waiting', 'paused', 'closed')


def _record_visible(kind, row, viewer):
    from services import situations, subjects
    if kind == 'program':
        return subjects.visible('program', row, viewer)
    return situations.can_see(kind, row, viewer)


def piece_cards(project, viewer):
    """One card per piece the viewer may see, drawn by its kind (front door §2)."""
    from services import situations, programs
    out = []
    for piece in view(project, viewer).get('pieces', []):
        kind, sid = piece['kind'], piece['id']
        card = {**piece, 'sheet': kind in SHEET_KINDS}
        if kind in ('thread', 'mission'):
            card['situation'] = situations.view(kind, sid, viewer)
            if card['situation'] is None:
                continue
        elif kind == 'program':
            row = storage.get_program(sid) or {}
            phase = (programs.progress(row) or {}).get('phase') or {}
            card['program'] = {'state': row.get('state'), 'member_id': row.get('member_id'),
                               'phase': phase.get('name') or ''}
        out.append(card)
    return out


def lane(project, viewer, cards=None):
    """Which overview lane a project sits in for this viewer (front door §2)."""
    state = project.get('state')
    if state in ('done', 'dropped'):
        return 'closed'
    if state == 'paused':
        return 'paused'
    viewer = viewer or {}
    if needs_plan(project) and _parent(viewer) and viewer.get('id') != project.get('owner_member_id'):
        return 'needs_you'
    cards = piece_cards(project, viewer) if cards is None else cards
    steps = project.get('steps') or []
    if not _child(viewer) and any(s.get('owner') == 'argyle' and (s.get('question') or s.get('state') == 'blocked')
                                  for s in steps):
        return 'needs_you'
    groups = [(c.get('situation') or {}).get('group') for c in cards]
    if 'now' in groups:
        return 'needs_you'
    if _parent(viewer) and any((c.get('program') or {}).get('state') == 'proposed' for c in cards):
        return 'needs_you'
    mine = [s for s in steps if s.get('state') == 'todo' and s.get('owner') == viewer.get('id')
            and _needs_satisfied(s, steps)]
    if mine or 'moving' in groups or 'in_hand' in groups or any(s.get('state') == 'doing' for s in steps):
        return 'moving'
    return 'waiting'


def overview_row(project, viewer):
    """A project's overview card: its view, its lane and the one line it says next."""
    row = view(project, viewer)
    cards = piece_cards(project, viewer)
    planless = needs_plan(project)
    nxt = (row.get('next_step') or {}).get('title') or ''
    if not nxt and planless:
        nxt = 'Needs a plan'
    if not nxt:
        nxt = next(((c['situation'].get('next_step') or {}).get('label') or ''
                    for c in cards if (c.get('situation') or {}).get('next_step')), '')
    row.update(lane=lane(project, viewer, cards), card_next=nxt,
               has_program=any(c['kind'] == 'program' for c in cards), needs_plan=planless)
    return row


def elsewhere(viewer):
    """Missions this person started whose project they may not see: a keeper's
    rows, drawn with the keeper projection (front door §2)."""
    from services import situations
    if not viewer or not viewer.get('id'):
        return []
    out = []
    for m in storage.get_missions():
        if m.get('created_by') != viewer['id'] or not m.get('project_id'):
            continue
        project = storage.get_project(m['project_id'])
        if project is None or can_see(project, viewer):
            continue
        v = situations.view('mission', m['id'], viewer)
        if v and v.get('group') != 'done':
            out.append(v)
    return out


def locate(kind, record_id, viewer):
    """Where an old link lands (front door §3): the record's project when the
    viewer may see both, else the record alone when they may see that."""
    if kind not in _ADOPT_TABLES:
        return {'project_id': None, 'record_visible': False}
    row = _ADOPT_TABLES[kind][0](record_id)
    if not row:
        return {'project_id': None, 'record_visible': False}
    visible = _record_visible(kind, row, viewer)
    project = storage.get_project(row.get('project_id')) if row.get('project_id') else None
    return {'project_id': project['id'] if project and visible and can_see(project, viewer) else None,
            'record_visible': bool(visible)}
```

`needs_plan`, `_parent`, `_child`, `_needs_satisfied`, `_ADOPT_TABLES`, `view`, `can_see` already exist in this module (slices A and 1).

- [ ] **Step 5: The routes** — in `main.py`, `projects_list` becomes:

```python
@app.get("/api/projects")
def projects_list(request: Request = None):
    from services import projects
    actor = _situation_viewer(request)
    return {'projects': [projects.overview_row(row, actor) for row in storage.get_projects()
                         if projects.can_see(row, actor)]}
```

and directly after `projects_create`, BEFORE `@app.get("/api/projects/{project_id}")` (a literal path must be declared before the parameter path that would swallow it):

```python
@app.get("/api/projects/elsewhere")
def projects_elsewhere(request: Request = None):
    from services import projects
    return {'situations': projects.elsewhere(_situation_viewer(request))}


@app.get("/api/projects/for/{kind}/{record_id}")
def projects_for_record(kind: str, record_id: str, request: Request = None):
    """Where an old Threads, Missions or Programs link lands (front door §3)."""
    from services import projects
    return projects.locate(kind, record_id, _situation_viewer(request))


@app.get("/api/projects/{project_id}/pieces")
def project_pieces(project_id: str, request: Request = None):
    from services import projects
    actor = _situation_viewer(request)
    return {'pieces': projects.piece_cards(_project_for_actor(project_id, actor), actor)}


@app.get("/api/subjects/search")
def subjects_search(q: str = '', request: Request = None):
    """Something already in Chauffeur, found from a project's Add a piece."""
    from services import subjects
    actor = _situation_viewer(request)
    if not (q or '').strip():
        return {'candidates': []}
    return {'candidates': [{'kind': c['kind'], 'id': c['id'], 'title': c['title']}
                           for c in subjects.find_all(q, actor)]}
```

`/api/subjects/search` must be declared before any `@app.get("/api/subjects/{kind}/...")` with the same segment count; the existing ones have four segments, so place it next to `subject_projects` (~6232).

- [ ] **Step 6: Creating inside a project** — add near `_project_for_actor`:

```python
def _project_to_join(body, actor):
    """A record made inside a project goes only into a project the person may change."""
    pid = (body or {}).get('project_id')
    if not pid:
        return None
    from services import projects
    if not projects.can_act(storage.get_project(pid), actor):
        raise HTTPException(status_code=403, detail="You cannot add to this project")
    return pid
```

`create_thread`: pass `project_id=_project_to_join(body, actor)` to `_threads.create(...)`.
`missions_launch`: `pid = _project_to_join(body, actor)` before the launch; pass `project_id=pid, subject=('project', pid) if pid else None` to `_missions.launch(...)`.
`create_program`: before the `_prog.create_row({...})` call, `pid = _project_to_join(body, storage.get_member(actor_id) if actor_id else None)`; pass `project_id=pid` to `create_row`.

- [ ] **Step 7: Run the tests**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_pieces.py && python tests/test_auth.py && python tests/test_projects.py && python tests/test_projects_tools.py && python tests/test_project_adopt.py && python tests/test_front_door_hardening.py && python tests/test_threads_endpoints.py && python tests/test_programs_endpoints.py && python tests/test_projects_live.py`
Expected: all PASS (`test_projects_live.py` reads `/api/projects`; its cards only need fields `view` already had).

- [ ] **Step 8: Commit** (Claude, after review)

```bash
git add chauffeur/services/projects.py chauffeur/main.py chauffeur/tests/test_project_pieces.py
git commit -m "feat(projects): piece cards, lanes, your work elsewhere, old-link lookup and creating inside a project (front door slice 2, Task 1)"
```

---

### Task 2: The Projects page — lanes, the detail view, piece cards, Add a piece (Claude)

**Files:**
- Modify: `chauffeur/templates/components/projects_page.html` (whole list block, the open project, the script)
- Create: `chauffeur/templates/components/project_piece_forms.html`
- Modify: `chauffeur/templates/app.html:442` (`{% set projects_host = 'phone' %}` before the include)
- Create: `chauffeur/tests/project_sheets_fixture.py` (shared seed and sign-in helpers for Tasks 2–6)
- Test: `chauffeur/tests/test_projects_detail_live.py`

**Interfaces:**
- Consumes: Task 1 routes and row fields (`lane`, `card_next`, `has_program`, `needs_plan`, `pieces[].situation|program|sheet`).
- Produces: the event `window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind, id, title, projectId}}))`; markers `[data-lane="<lane>"]`, `[data-lane-filter="programs"]`, `[data-project-detail]`, `[data-project-back]`, `[data-piece="<kind>:<id>"]`, `[data-piece-open="<kind>:<id>"]`, `[data-add-piece]`, form roots `[data-piece-form="thread|mission|program"]` with submit `[data-piece-create]`; existing markers kept (`[data-project-id]`, `[data-step-*]`, `[data-new-project]`, `[data-create-project]`); `projectsPage(host)` where `host` is `'admin'` or `'phone'`.

- [ ] **Step 1: The shared fixture** `chauffeur/tests/project_sheets_fixture.py`:

```python
"""One seed and the sign-in helpers for the slice 2 live tests (front door spec §2-§3).

Its own throwaway data directory, set before storage is imported, the way
tests/test_projects_live.py does it."""
import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = tempfile.mkdtemp(prefix='chauffeur_sheets_live_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))

from services import storage  # noqa: E402

TOKENS, IDS = {}, {}
SHOTS = os.environ.get('PROJECTS_SHOTS')
_PROGRAM = {'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': []}, 'phases': [],
            'source': {'origin': 'none', 'reason': 'test'},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def seed():
    if TOKENS:
        return
    from services import projects, threads
    for m in ({'id': 'mom', 'name': 'Mom', 'role': 'parent', 'email': 'mom@example.com', 'color_code': '#287a72'},
              {'id': 'dad', 'name': 'Dad', 'role': 'parent', 'color_code': '#7a2850'},
              {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult', 'color_code': '#285a7a'},
              {'id': 'kid', 'name': 'Kate', 'role': 'child', 'stage_override': 'navigator', 'color_code': '#5a7a28'}):
        storage.add_member(m)
    for who in ('mom', 'dad', 'aunt', 'kid'):
        TOKENS[who] = storage.create_member_token(who)
    storage.add_project({'id': 'prj-bath', 'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'we use it every day',
                         'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household', 'pieces': [], 'steps': []})
    IDS['bath'] = 'prj-bath'
    IDS['thread'] = threads.create(title='Tiler', owner_member_id='mom', goal='tile by May', kind='vendor',
                                   counterparty_name='Ace Tile', next_action='Call Ace back', created_by='mom',
                                   project_id='prj-bath')
    IDS['closed'] = threads.create(title='Old permit', owner_member_id='mom', goal='permit', created_by='mom',
                                   project_id='prj-bath')
    storage.update_thread(IDS['closed'], {'state': 'done'})
    IDS['mission'] = storage.add_mission({'goal': 'Find three tilers', 'created_by': 'mom', 'tier': 'mission', 'status': 'running'})
    projects.adopt('mission', IDS['mission'], None, project_id='prj-bath')
    for pid, title, state in (('pr-prop', 'Tiling basics', 'proposed'), ('pr-live', 'Strength basics', 'active')):
        storage.add_program({'id': pid, 'member_id': 'mom', 'title': title, 'state': state, **_PROGRAM})
        projects.adopt('program', pid, None, project_id='prj-bath')
    storage.add_project({'id': 'prj-gift', 'title': 'Surprise party', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom',
                         'created_by': 'mom', 'audience': 'private', 'pieces': [], 'steps': []})
    IDS['keeper'] = storage.add_mission({'goal': 'Book the venue', 'created_by': 'aunt', 'tier': 'mission', 'status': 'running'})
    projects.adopt('mission', IDS['keeper'], None, project_id='prj-gift')
    storage.add_project({'id': 'prj-bike', 'title': 'Ride a bike', 'goal': 'ride to school', 'done_when': 'no hands',
                         'owner_member_id': 'kid', 'created_by': 'kid', 'audience': 'parents', 'pieces': [], 'steps': []})
    storage.set_app_state('projects_adopted_rev', 1)   # the startup migration must not re-wrap the fixture


def serve():
    from live_app import live_app
    served = live_app(seed)
    if served is not None:
        storage.update_settings({'auth_enforce': True, 'missions_enabled': True, 'programs_enabled': True})
    return served


def admin(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_admin_token': TOKENS[who], 'chauffeur_admin_token_for': who})


def pwa(page, served, who):
    page.goto(served.url('api/account/setup'))
    page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                  {'chauffeur_member_id': who, 'chauffeur_member_token': TOKENS[who], 'chauffeur_member_token_for': who,
                   'chauffeur_theme': 'dark'})


def shot(page, name):
    if SHOTS:
        page.screenshot(path=os.path.join(SHOTS, name + '.png'), full_page=True)
```

- [ ] **Step 2: Write the failing live test** `chauffeur/tests/test_projects_detail_live.py`:

```python
"""The Projects page: lanes, a project's detail with its pieces, Add a piece
(front door spec §2, slice 2, Task 2). Run from chauffeur/:
python tests/test_projects_detail_live.py   (PROJECTS_SHOTS=<dir> for screenshots)"""
from project_sheets_fixture import IDS, admin, check, serve, shot, storage


def _opened(page):
    return page.evaluate("() => { const out = []; window.addEventListener('chf-record-sheet-open', e => out.push(e.detail)); window.__sheets = out; }")


def scenario_lanes_and_the_programs_filter():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('[data-lane="needs_you"]', timeout=15000)
        needs = page.locator('[data-lane="needs_you"]').inner_text()
        check('Ride a bike' in needs and 'Bathroom' in needs, f"Kate's unplanned project and the program to approve: {needs}")
        check('Needs a plan' in needs, "the card says what it needs")
        page.locator('[data-lane-filter="programs"]').click()
        body = page.locator('[data-lane]').all_inner_texts()
        check(any('Bathroom' in t for t in body) and not any('Ride a bike' in t for t in body), f"Programs filter: {body}")
        shot(page, 'slice2-lanes')
        page.goto(served.url('projects?lane=programs'), wait_until='load')
        page.wait_for_selector('[data-lane-filter="programs"][aria-pressed="true"]', timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_the_detail_view_and_its_pieces():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=15000)
        page.locator(f'[data-project-id="{IDS["bath"]}"]').first.click()
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        check('id=' + IDS['bath'] in page.url, f"the address names the project: {page.url}")
        for key in (f'thread:{IDS["thread"]}', f'mission:{IDS["mission"]}', 'program:pr-prop', 'program:pr-live'):
            check(page.locator(f'[data-piece="{key}"]').count() == 1, f"a card for {key}")
            check(page.locator(f'[data-piece-open="{key}"]').count() == 1, f"Open on {key}")
        check('Tiler' in page.locator(f'[data-piece="thread:{IDS["thread"]}"]').inner_text(), "the thread's situation card")
        _opened(page)
        page.locator(f'[data-piece-open="thread:{IDS["thread"]}"]').click()
        sheets = page.evaluate('() => window.__sheets')
        check(sheets and sheets[0]['kind'] == 'thread' and sheets[0]['id'] == IDS['thread'] and sheets[0]['projectId'] == IDS['bath'],
              f"Open asks for the sheet: {sheets}")
        shot(page, 'slice2-detail')
        page.locator('[data-project-back]').click()
        page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=10000)
        check('id=' not in page.url, f"back drops the project from the address: {page.url}")
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_add_a_piece_inside_the_project():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-add-piece]', timeout=15000)
        page.locator('[data-add-piece]').click()
        page.locator('[data-prompt-choice]', has_text='A conversation with someone outside').first.click()
        form = page.locator('[data-piece-form="thread"]')
        form.locator('input[name="title"]').fill('Plumber')
        form.locator('input[name="counterparty_name"]').fill('Bob Pipes')
        form.locator('[data-piece-create]').click()
        for _ in range(40):
            rows = [t for t in storage.get_threads() if t.get('title') == 'Plumber']
            if rows:
                break
            page.wait_for_timeout(250)
        check(rows and rows[0]['project_id'] == IDS['bath'] and rows[0]['counterparty_name'] == 'Bob Pipes', f"made inside: {rows}")
        page.wait_for_selector(f'[data-piece="thread:{rows[0]["id"]}"]', timeout=10000)
        page.locator('[data-add-piece]').click()
        page.locator('[data-prompt-choice]', has_text='Work for Argyle').first.click()
        form = page.locator('[data-piece-form="mission"]')
        form.locator('textarea[name="goal"]').fill('Compare three plumbers')
        form.locator('select[name="tier"]').select_option('flash')
        form.locator('[data-piece-create]').click()
        for _ in range(40):
            ms = [m for m in storage.get_missions() if m.get('goal') == 'Compare three plumbers']
            if ms:
                break
            page.wait_for_timeout(250)
        check(ms and ms[0]['project_id'] == IDS['bath'] and ms[0]['tier'] == 'flash', f"launched inside, Flash kept: {ms}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_add_a_piece_for_a_child():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'kid')
        page.goto(served.url('projects?id=prj-bike'), wait_until='load')
        page.wait_for_selector('[data-add-piece]', timeout=15000)
        page.locator('[data-add-piece]').click()
        choices = page.locator('[data-prompt-choice]').all_inner_texts()
        check('Work for Argyle' not in choices and 'A conversation with someone outside' not in choices,
              f"a child adds no Argyle work and no outside conversation: {choices}")
        check(any('practice program' in c for c in choices), f"but may propose their own program: {choices}")


SCENARIOS = [scenario_lanes_and_the_programs_filter, scenario_the_detail_view_and_its_pieces,
             scenario_add_a_piece_inside_the_project, scenario_add_a_piece_for_a_child]

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

The admin `promptChoice` (`templates/components/control_center.html` ~1505) builds its option buttons with no marker the test can find. Add one attribute there, nothing else: after `b.textContent = o.label;` add `b.setAttribute('data-prompt-choice', o.value);`. (The phone's `promptChoice` already marks its buttons `data-pick`; the phone tests do not click a choice.)

- [ ] **Step 3: Run it to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_projects_detail_live.py`
Expected: FAIL — no `[data-lane]`, no `[data-project-detail]`.

- [ ] **Step 4: The template.** In `projects_page.html`:

(a) The root becomes `<section x-data="projectsPage({{ (projects_host|default('admin'))|tojson }})" …>` (every other attribute unchanged).

(b) Replace the block from `<p class="text-xs text-gray-500 italic px-1" x-show="!loading && !error && !shownProjects.length">No projects yet.</p>` through the closing `</div>` of `<div class="space-y-2">` (the whole `x-for="project in shownProjects"` list including the inline open project) with:

```html
    <template x-if="!opened">
        <div>
            <div class="flex flex-wrap items-center gap-2 mb-3">
                <button type="button" data-lane-filter="programs" @click="programsOnly = !programsOnly" :aria-pressed="programsOnly ? 'true' : 'false'"
                        :class="programsOnly ? 'bg-teal-700 text-white border-teal-600' : 'bg-gray-800 text-gray-300 border-gray-700'"
                        class="text-xs font-bold px-2.5 py-1.5 rounded-lg border">Programs</button>
                <label class="ml-auto flex items-center gap-2 text-[11px] text-gray-500 cursor-pointer select-none">
                    <input type="checkbox" x-model="showClosed" @change="rememberClosed()" class="h-3.5 w-3.5 accent-teal-400"><span>Show closed</span>
                </label>
            </div>
            <p class="text-xs text-gray-500 italic px-1" x-show="!loading && !error && !shownProjects.length">No projects yet.</p>
            <template x-for="ln in lanes" :key="ln.key">
                <div class="mb-5" :data-lane="ln.key">
                    <button type="button" x-show="ln.key === 'closed'" @click="closedOpen = !closedOpen"
                            class="w-full flex items-center justify-between text-xs font-black uppercase tracking-widest px-1 mb-2 text-gray-600">
                        <span x-text="ln.label + ' (' + ln.items.length + ')'"></span>
                        <span class="normal-case font-semibold" x-text="closedOpen ? 'Hide' : 'Show'"></span>
                    </button>
                    <div x-show="ln.key !== 'closed'" class="text-xs font-black uppercase tracking-widest px-1 mb-2" :class="ln.titleClass" x-text="ln.label"></div>
                    <div class="space-y-2" x-show="ln.key !== 'closed' || closedOpen">
                        <template x-for="project in ln.items" :key="project.id">
                            <article data-project-card class="bg-gray-900 border border-gray-800 rounded-2xl p-3">
                                <button type="button" :data-project-id="project.id" @click="open(project)" class="w-full text-left">
                                    <span class="flex items-start justify-between gap-2">
                                        <span class="text-sm font-bold text-gray-100" x-text="project.title"></span>
                                        <span class="text-xs font-bold px-1.5 py-0.5 rounded shrink-0" :class="chip(project.state)" x-text="project.state"></span>
                                    </span>
                                    <span class="block text-[11px] text-gray-500 mt-0.5" x-text="memberName(project.owner_member_id)"></span>
                                    <span class="block text-xs text-gray-400 mt-1" x-text="project.card_next || ''"></span>
                                    <span class="block text-xs text-gray-500 mt-1" x-text="project.steps_done + ' of ' + project.steps_total + ' done'"></span>
                                </button>
                            </article>
                        </template>
                    </div>
                </div>
            </template>
            <template x-if="elsewhere.length && !programsOnly">
                <div class="mb-5" data-lane="elsewhere">
                    <div class="text-xs font-black uppercase tracking-widest px-1 mb-2 text-gray-500">Your work elsewhere</div>
                    <div class="space-y-2" data-pieces>
                        <template x-for="s in elsewhere" :key="s.id">
                            <div :data-piece="'mission:' + s.id">
                                <div x-html="window.Situations.cardHtml(s, sitCtx())"></div>
                                <button type="button" :data-piece-open="'mission:' + s.id" @click="openSheet('mission', s.id, s.title, null)"
                                        class="mt-1 text-xs font-bold text-teal-300 underline underline-offset-2">Open</button>
                            </div>
                        </template>
                    </div>
                </div>
            </template>
        </div>
    </template>
    <template x-if="opened && detail">
        <div data-project-detail class="space-y-3">
            <button type="button" data-project-back @click="back()" class="text-xs font-semibold text-gray-400 underline underline-offset-2">← All projects</button>
            <template x-for="project in [detail]" :key="project.id">
                <article data-project-card class="bg-gray-900 border border-gray-800 rounded-2xl p-3 space-y-2.5">
                    <div class="flex items-start justify-between gap-2">
                        <h3 class="text-base font-bold text-gray-100" x-text="project.title"></h3>
                        <span class="text-xs font-bold px-1.5 py-0.5 rounded shrink-0" :class="chip(project.state)" x-text="project.state"></span>
                    </div>
                    <!-- (c) the open project's body, moved here -->
                </article>
            </template>
        </div>
    </template>
```

(c) Into the `<!-- (c) … -->` slot, move the old open project's body verbatim (from `<p class="text-sm text-gray-300"><span class="text-gray-500">Goal: </span>` through the Pause/Resume/Done/Drop button row), with three changes:
- the "Open Argyle’s work and answer" anchor becomes
  `<template x-if="step.mission_id && !isChild()"><button type="button" :data-piece-open="'mission:' + step.mission_id" @click="openSheet('mission', step.mission_id, step.title, project.id)" class="text-blue-400 underline underline-offset-2">Open Argyle’s work and answer</button></template>`;
- the "Pieces" and "Conversations" blocks are replaced by:

```html
                    <div class="space-y-2" data-pieces>
                        <div class="text-sm font-bold text-gray-300">Pieces</div>
                        <p class="text-xs text-gray-500 italic" x-show="!(pieces[project.id] || []).length">No pieces attached yet.</p>
                        <template x-for="card in (pieces[project.id] || [])" :key="card.kind + ':' + card.id">
                            <div :data-piece="card.kind + ':' + card.id">
                                <template x-if="card.situation"><div x-html="window.Situations.cardHtml(card.situation, sitCtx())"></div></template>
                                <template x-if="card.kind === 'program'">
                                    <div class="bg-gray-900 border border-gray-800 rounded-2xl p-3">
                                        <div class="flex items-start justify-between gap-2">
                                            <span class="text-sm font-bold text-gray-100" x-text="card.title"></span>
                                            <span class="text-xs font-bold px-1.5 py-0.5 rounded shrink-0" :class="chip(card.program.state)" x-text="card.program.state"></span>
                                        </div>
                                        <p class="text-xs text-gray-400 mt-1" x-show="card.program.phase" x-text="card.program.phase"></p>
                                        <p class="text-xs text-blue-300 mt-1" x-show="card.program.state === 'proposed'">Proposed: see its week and approve it here.</p>
                                    </div>
                                </template>
                                <template x-if="!card.sheet"><a :href="apiBase + card.link" class="text-xs text-blue-400 underline underline-offset-2" x-text="card.title"></a></template>
                                <template x-if="card.sheet">
                                    <button type="button" :data-piece-open="card.kind + ':' + card.id" @click="openSheet(card.kind, card.id, card.title, project.id)"
                                            class="mt-1 text-xs font-bold text-teal-300 underline underline-offset-2">Open</button>
                                </template>
                            </div>
                        </template>
                    </div>
                    <template x-if="project.can_act && project.state === 'active'">
                        <div class="space-y-2">
                            <button type="button" data-add-piece @click="addPiece(project)" :disabled="!!busy"
                                    class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700 disabled:opacity-50">Add a piece</button>
                            {% include 'components/project_piece_forms.html' %}
                        </div>
                    </template>
```

(d) `chauffeur/templates/components/project_piece_forms.html` (inside the project scope; `pieceForm` is the open form):

```html
{# Add a piece's three forms (front door §2): the old Threads create form, the
   Missions launch card with its tier, the Programs propose form. Each makes the
   record inside this project (project_id), with the same fields its page had. #}
<template x-if="pieceForm && pieceForm.projectId === project.id && pieceForm.kind === 'thread'">
    <form data-piece-form="thread" class="space-y-2 bg-gray-950/60 border border-gray-800 rounded-xl p-3" @submit.prevent="createPiece()">
        <input name="title" required x-model="pieceForm.title" placeholder="Who or what (e.g. Pest control)" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
        <textarea name="goal" x-model="pieceForm.goal" placeholder="What resolving it looks like" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm"></textarea>
        <div class="flex gap-2">
            <select name="kind" x-model="pieceForm.thread_kind" class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
                <option value="vendor">A company or person</option><option value="project">An errand of ours</option>
            </select>
            <select name="owner_member_id" x-model="pieceForm.owner_member_id" class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
                <template x-for="m in owners().filter(m => m.role !== 'child')" :key="m.id"><option :value="m.id" x-text="m.name"></option></template>
            </select>
        </div>
        <select name="contact_id" x-model="pieceForm.contact_id" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
            <option value="">Someone not in contacts</option>
            <template x-for="c in contacts" :key="c.id"><option :value="c.id" x-text="c.name"></option></template>
        </select>
        <template x-if="!pieceForm.contact_id">
            <div class="flex gap-2">
                <input name="counterparty_name" x-model="pieceForm.counterparty_name" placeholder="Their name" class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
                <input name="counterparty_email" type="email" x-model="pieceForm.counterparty_email" placeholder="Their email" class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
            </div>
        </template>
        <div class="flex gap-2">
            <input name="next_action" x-model="pieceForm.next_action" placeholder="First next step" class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
            <input name="next_action_at" type="date" x-model="pieceForm.next_action_at" class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
        </div>
        <div class="flex gap-2">
            <button data-piece-create :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white disabled:opacity-50">Start the conversation</button>
            <button type="button" @click="pieceForm = null" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Cancel</button>
        </div>
    </form>
</template>
<template x-if="pieceForm && pieceForm.projectId === project.id && pieceForm.kind === 'mission'">
    <form data-piece-form="mission" class="space-y-2 bg-gray-950/60 border border-gray-800 rounded-xl p-3" @submit.prevent="createPiece()">
        <textarea name="goal" required x-model="pieceForm.goal" rows="2" placeholder="What should Argyle work on?" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm resize-none"></textarea>
        <div class="flex gap-2">
            <select name="tier" x-model="pieceForm.tier" class="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
                <option value="mission">Pro (paid)</option><option value="flash">Flash (free, benchmark)</option>
            </select>
            <button data-piece-create :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white disabled:opacity-50">Launch</button>
            <button type="button" @click="pieceForm = null" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Cancel</button>
        </div>
    </form>
</template>
<template x-if="pieceForm && pieceForm.projectId === project.id && pieceForm.kind === 'program'">
    <form data-piece-form="program" class="space-y-2 bg-gray-950/60 border border-gray-800 rounded-xl p-3" @submit.prevent="createPiece()">
        <input name="title" required x-model="pieceForm.title" placeholder="The aim (e.g. learn guitar)" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
        <template x-if="!isChild()">
            <select name="for_member_id" x-model="pieceForm.for_member_id" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
                <template x-for="m in owners()" :key="m.id"><option :value="m.id" x-text="m.name"></option></template>
            </select>
        </template>
        <input name="starting_point" x-model="pieceForm.starting_point" placeholder="Where they are starting (what they can already do)" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
        <div class="flex gap-2">
            <label class="flex-1 text-xs text-gray-400">Sessions a week<input name="sessions_per_week" type="number" min="1" max="7" x-model.number="pieceForm.sessions_per_week" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-gray-100 text-sm"></label>
            <label class="flex-1 text-xs text-gray-400">Minutes<input name="minutes" type="number" min="5" max="240" x-model.number="pieceForm.minutes" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-gray-100 text-sm"></label>
            <label class="flex-1 text-xs text-gray-400">Target<input name="target_date" type="date" x-model="pieceForm.target_date" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-gray-100 text-sm"></label>
        </div>
        <div class="flex flex-wrap gap-1">
            <template x-for="d in [0,1,2,3,4,5,6]" :key="d">
                <button type="button" @click="togglePieceDay(d)" :aria-pressed="pieceForm.preferred_days.includes(d) ? 'true' : 'false'"
                        :class="pieceForm.preferred_days.includes(d) ? 'bg-teal-700 text-white' : 'bg-gray-800 text-gray-400'"
                        class="text-[11px] font-bold px-2 py-1 rounded" x-text="['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][d]"></button>
            </template>
        </div>
        <div class="flex gap-2">
            <button data-piece-create :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white disabled:opacity-50">Propose it</button>
            <button type="button" @click="pieceForm = null" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Cancel</button>
        </div>
    </form>
</template>
```

Check the day numbering against `programs_page.html:230` (`draft.preferred_days.includes(d - 1)` over `d` 1..7, so 0 = Monday); the propose body sends the same list.

- [ ] **Step 5: The script.** In `projectsPage`:

```js
function projectsPage(host = 'admin') {
    return {
        host, apiBase: window.chfBase !== undefined ? window.chfBase : '',
        projects: [], members: [], myId: '', loading: false, busy: false, error: '',
        creating: false, opened: null, hold: null, pieces: {}, elsewhere: [], contacts: [], pieceForm: null,
        programsOnly: new URLSearchParams(location.search).get('lane') === 'programs',
        closedOpen: false,
        showClosed: (() => { try { return localStorage.getItem('chf_projects_show_closed') === '1'; } catch (e) { return false; } })(),
        // …the existing fields (sproutSection, shownProjects, draft, headers, request, isChild, isParent, owners, defaultAudience) unchanged…
        rememberClosed() { try { localStorage.setItem('chf_projects_show_closed', this.showClosed ? '1' : '0'); } catch (e) { /* private window */ } },
        get detail() { return this.projects.find(p => p.id === this.opened) || null; },
        get lanes() {
            const rows = this.shownProjects.filter(p => !this.programsOnly || p.has_program);
            const by = key => rows.filter(p => (p.lane || 'waiting') === key);
            const all = [
                {key: 'needs_you', label: 'Needs you', titleClass: 'text-amber-400', items: by('needs_you')},
                {key: 'moving', label: 'Moving', titleClass: 'text-teal-300', items: by('moving')},
                {key: 'waiting', label: 'Waiting', titleClass: 'text-gray-500', items: by('waiting')},
                {key: 'paused', label: 'Paused', titleClass: 'text-gray-500', items: by('paused')},
                {key: 'closed', label: 'Done & dropped', titleClass: 'text-gray-600', items: by('closed')},
            ];
            return all.filter(l => l.items.length && (l.key !== 'closed' || this.showClosed));
        },
        memberName(id) { const m = this.members.find(m => m.id === id); return m ? m.name : ''; },
        setAddress(params) {
            if (this.host !== 'admin') return;
            const q = new URLSearchParams(location.search);
            for (const [k, v] of Object.entries(params)) { if (v === null || v === undefined) q.delete(k); else q.set(k, v); }
            const s = q.toString();
            history.replaceState(history.state, '', location.pathname + (s ? '?' + s : '') + location.hash);
        },
        sitCtx() {
            return {apiBase: this.apiBase, canWrite: !this.isChild(), readOnly: false,
                    memberId: this.host === 'phone' ? this.myId : undefined,
                    lookup: (kind, id) => this.situationById(id), onChange: () => this.load()};
        },
        situationById(id) {
            for (const cards of Object.values(this.pieces)) { const c = cards.find(c => c.id === id && c.situation); if (c) return c.situation; }
            return this.elsewhere.find(s => s.id === id) || null;
        },
        bindCards() { this.$nextTick(() => this.$root.querySelectorAll('[data-pieces]').forEach(el => window.Situations && window.Situations.bind(el, this.sitCtx()))); },
        openSheet(kind, id, title, projectId) {
            window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind, id, title: title || '', projectId: projectId || null}}));
        },
        async loadPieces(p) {
            try { this.pieces[p.id] = (await this.request('api/projects/' + encodeURIComponent(p.id) + '/pieces')).pieces || []; }
            catch (e) { this.error = e.message; }
            this.bindCards();
        },
        async open(p) {
            try {
                const data = await this.request('api/projects/' + encodeURIComponent(p.id));
                this.projects = this.projects.map(row => row.id === p.id ? {...row, ...data.project} : row);
                this.opened = p.id; this.hold = null; this.pieceForm = null;
                this.setAddress({id: p.id});
                await this.loadPieces(p);
            } catch (e) { this.error = e.message; }
        },
        back() { this.opened = null; this.hold = null; this.pieceForm = null; this.setAddress({id: null, piece: null}); },
        async fromAddress() {
            if (this.host !== 'admin') return;
            const q = new URLSearchParams(location.search);
            const id = q.get('id'), piece = q.get('piece') || '';
            const [kind, rid] = piece.includes(':') ? piece.split(':', 2) : [null, null];
            if (id && !this.opened) { const p = this.projects.find(p => p.id === id); if (p) await this.open(p); }
            if (!kind || !rid) return;
            if (!id) {
                const where = await this.request('api/projects/for/' + encodeURIComponent(kind) + '/' + encodeURIComponent(rid)).catch(() => null);
                if (where && where.project_id) { const p = this.projects.find(p => p.id === where.project_id); if (p) await this.open(p); }
                else if (!(where && where.record_visible)) { this.error = 'That isn’t here, or isn’t yours to see.'; return; }
            }
            this.openSheet(kind, rid, '', this.opened);
        },
        async addPiece(p) {
            const options = [{value: 'existing', label: 'Something already in Chauffeur'}];
            if (!this.isChild()) options.push({value: 'thread', label: 'A conversation with someone outside'}, {value: 'mission', label: 'Work for Argyle'});
            options.push({value: 'program', label: 'A practice program'});
            const pick = await promptChoice('Add a piece', '', options);
            if (!pick) return;
            if (pick === 'existing') return this.pickExisting(p);
            if (pick === 'thread' && !this.contacts.length) this.contacts = await this.request('api/assist-contacts').catch(() => []) || [];
            this.pieceForm = {projectId: p.id, kind: pick, title: '', goal: '', thread_kind: 'vendor', owner_member_id: this.myId,
                              contact_id: '', counterparty_name: '', counterparty_email: '', next_action: '', next_action_at: '',
                              tier: 'mission', for_member_id: this.myId, starting_point: '', sessions_per_week: 3, minutes: 25,
                              preferred_days: [], target_date: ''};
        },
        togglePieceDay(d) { const days = this.pieceForm.preferred_days; const i = days.indexOf(d); if (i === -1) days.push(d); else days.splice(i, 1); },
        async pickExisting(p) {
            const q = await promptInput('Add something already in Chauffeur', 'A trip, an occasion, a list, a program…', {okText: 'Find it'});
            if (!q || !q.trim()) return;
            try {
                const found = (await this.request('api/subjects/search?q=' + encodeURIComponent(q.trim()))).candidates || [];
                if (!found.length) { showGlobalAlert('Nothing by that name.'); return; }
                const pick = await promptChoice('Which one?', '', found.map(c => ({value: c.kind + ':' + c.id, label: c.title + ' (' + c.kind + ')'})));
                if (!pick) return;
                const [kind, id] = pick.split(':', 2);
                if (await this.mutate('api/projects/' + encodeURIComponent(p.id) + '/pieces', {kind, id})) await this.loadPieces(p);
            } catch (e) { this.error = e.message; }
        },
        async createPiece() {
            const f = this.pieceForm;
            if (!f || this.busy) return;
            const project = this.detail;
            const body = f.kind === 'thread'
                ? {title: f.title.trim(), goal: f.goal, kind: f.thread_kind, owner_member_id: f.owner_member_id, contact_id: f.contact_id || null,
                   counterparty_name: f.counterparty_name, counterparty_email: f.counterparty_email, next_action: f.next_action,
                   next_action_at: f.next_action_at || null, project_id: f.projectId}
                : f.kind === 'mission'
                ? {goal: f.goal.trim(), tier: f.tier, project_id: f.projectId}
                : {title: f.title.trim(), for_member_id: f.for_member_id || this.myId, member_id: this.myId || null,
                   starting_point: f.starting_point.trim(), sessions_per_week: f.sessions_per_week || 3, minutes: f.minutes || 25,
                   preferred_days: f.preferred_days, target_date: f.target_date || null, project_id: f.projectId};
            const path = {thread: 'api/threads', mission: 'api/missions/launch', program: 'api/programs'}[f.kind];
            if (await this.mutate(path, body)) { this.pieceForm = null; if (project) await this.loadPieces(project); }
        },
        // …the existing ordered, chip, foundLines, stepState, windowLabel, mutate, create, stepPath, writeStep, tick, cancel,
        //   suggest, pickTime, keepHold, state, addStep, plan methods unchanged, EXCEPT:
        //   plan(p): after a successful mutate, `await this.loadPieces(p)` instead of openConversations;
        //   openConversations and `conversations` are removed (pieces replace them).
    };
}
```

and `load()` changes three lines: reset `pieces`/`elsewhere` instead of `conversations` when the person changes; after `this.projects = data.projects…`, fetch `this.elsewhere = this.isChild() ? [] : ((await this.request('api/projects/elsewhere').catch(() => ({situations: []}))).situations || []); this.bindCards();`; and replace the `?id=` block with `await this.fromAddress();` (guarded so it runs once: `if (!this._addressed) { this._addressed = true; await this.fromAddress(); }`). When `this.opened` is set on a reload, also `await this.loadPieces(this.detail)` so cards follow the state.

(e) `app.html:442`: `{% set projects_host = 'phone' %}` on the line before `{% include 'components/projects_page.html' %}`.

- [ ] **Step 6: Build Tailwind and run**

Run: `cd chauffeur && python tools/build_tailwind.py && unset HA_BASE_URL && PROJECTS_SHOTS=<scratchpad> python tests/test_projects_detail_live.py && python tests/test_projects_live.py`
Expected: PASS, both. Open `slice2-lanes.png` and `slice2-detail.png` and check them against the design guide (cards, chips and empty states match the Programs-page vocabulary the component already uses; nothing overlaps at 390px — rerun `scenario_the_detail_view_and_its_pieces` at `page.set_viewport_size({'width': 390, 'height': 844})` once by hand).

- [ ] **Step 7: Commit**

```bash
git add chauffeur/templates/components/projects_page.html chauffeur/templates/components/project_piece_forms.html chauffeur/templates/app.html chauffeur/templates/components/control_center.html chauffeur/static/tailwind*.css chauffeur/tests/project_sheets_fixture.py chauffeur/tests/test_projects_detail_live.py
git commit -m "feat(projects): the Projects page - lanes with a Programs filter, a project's detail with its pieces as cards, Add a piece with the old create forms, your work elsewhere (front door slice 2, Task 2)"
```

---

### Task 3: The record sheet, and threads and missions in sheet mode (Claude)

**Files:**
- Create: `chauffeur/templates/components/record_sheet.html`
- Create: `chauffeur/templates/components/projects_admin.html`
- Modify: `chauffeur/templates/work.html` (projects section), `chauffeur/templates/projects.html`
- Modify: `chauffeur/templates/components/threads_page.html` (root 6-7, wrap 9-91, script `threadsPage`, `groups`)
- Modify: `chauffeur/templates/components/missions_page.html` (root 17, wrap 19-150, wrap the launch card 164-180, script `missionsSettings`, `groups`, `startPolling`)
- Test: `chauffeur/tests/test_record_sheet_live.py`

**Interfaces:**
- Consumes: `chf-record-sheet-open` `{kind, id, title, projectId}` (Task 2).
- Produces: the window event `chf-record-sheet` `{kind, id}` (kind `null` when the sheet closes); markers `[data-record-sheet]` (with `data-kind`), `[data-record-sheet-close]`; `threadsPage(sheet=false)`, `missionsSettings(sheet=false)` with `onSheet(detail)`; the Jinja flag `sheet_mode`; the strip markers `{# sheet:hide #}` / `{# /sheet:hide #}` the parity test relies on.

- [ ] **Step 1: Write the failing live test** `chauffeur/tests/test_record_sheet_live.py`:

```python
"""A piece opens in the record sheet with everything its old page could do
(front door spec §2, slice 2, Tasks 3 and 4). Run from chauffeur/:
python tests/test_record_sheet_live.py   (PROJECTS_SHOTS=<dir> for screenshots)"""
from project_sheets_fixture import IDS, admin, check, serve, shot


def _sheet(page, key):
    page.locator(f'[data-piece-open="{key}"]').first.click()
    page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=10000)
    return page.locator('[data-record-sheet]')


def scenario_a_thread_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-piece-open]', timeout=15000)
        sheet = _sheet(page, f'thread:{IDS["thread"]}')
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=10000)
        text = sheet.inner_text()
        for label in ('Draft email', 'Add note', 'Advance', 'Research', 'Photo', 'Work this', 'Edit', 'Delete', 'Call Ace back', 'Ace Tile'):
            check(label in text, f"the thread sheet has {label}")
        check('Old permit' not in text, "only the thread asked for")
        check('Threads settings' not in page.content() and 'Stalls after' not in text, "no drawer and no page chrome in the sheet")
        check('piece=thread' in page.url, f"the address names the piece: {page.url}")
        shot(page, 'slice2-thread-sheet')
        page.keyboard.press('Escape')
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)
        check('piece=' not in page.url, f"closing drops the piece: {page.url}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_closed_thread_opens_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath'] + '&piece=thread:' + IDS['closed']), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=15000)
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=10000)
        text = page.locator('[data-record-sheet]').inner_text()
        check('Old permit' in text and 'Tiler' not in text, f"a closed thread shows by itself: {text[:300]}")


def scenario_switching_records_shows_only_the_new_one():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath'] + '&piece=thread:' + IDS['closed']), wait_until='load')
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=15000)
        page.evaluate("(id) => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind: 'thread', id}}))", IDS['thread'])
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Call Ace back')", timeout=10000)
        text = page.locator('[data-record-sheet]').inner_text()
        check('Old permit' not in text, f"nothing of the first record lingers: {text[:300]}")


def scenario_a_mission_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-piece-open]', timeout=15000)
        sheet = _sheet(page, f'mission:{IDS["mission"]}')
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Find three tilers')", timeout=15000)
        text = sheet.inner_text()
        for label in ('Send', 'Drop', 'Delete'):
            check(label in text, f"the mission sheet has {label}")
        check('Launch a mission' not in text and 'Missions settings' not in page.content(), "no launch card and no drawer in the sheet")
        shot(page, 'slice2-mission-sheet')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_keeper_gets_the_record_alone():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'aunt')
        page.goto(served.url('projects?piece=mission:' + IDS['keeper']), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=15000)
        check('Surprise party' not in page.content(), "never the project's words")
        check(page.locator('[data-project-detail]').count() == 0, "no project opened")
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('[data-lane="elsewhere"]', timeout=15000)
        check('Book the venue' in page.locator('[data-lane="elsewhere"]').inner_text(), "Aunt's work elsewhere lists it")


SCENARIOS = [scenario_a_thread_in_the_sheet, scenario_a_closed_thread_opens_in_the_sheet, scenario_switching_records_shows_only_the_new_one,
             scenario_a_mission_in_the_sheet, scenario_a_keeper_gets_the_record_alone]

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

- [ ] **Step 2: Run it to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_record_sheet_live.py`
Expected: FAIL — no `[data-record-sheet]`.

- [ ] **Step 3: The record sheet** `chauffeur/templates/components/record_sheet.html`:

```html
{# The record sheet (front door §2): a project's thread, mission or program, one at
   a time, beside the Projects page. Framed like the settings drawer (same width,
   header and close) but it is not the drawer: the drawer holds a page's settings
   only. Each body is the record's own component in sheet mode, so every control
   its old page had is the same markup here. Admin hosts only (work.html,
   projects.html); the phone draws its own sheet in app.html. #}
{% set sheet_mode = true %}
<div x-data="chfRecordSheet()" x-show="rsOpen" x-cloak data-record-sheet :data-kind="rsKind" :data-open="rsOpen ? 'true' : null"
     @chf-record-sheet-open.window="show($event.detail)" @keydown.escape.window="rsOpen && close()" @click.self="close()"
     class="fixed inset-0 z-[80] bg-black/40 flex justify-end items-end md:items-stretch">
    <div tabindex="-1" role="dialog" aria-modal="true" :aria-label="rsLabel()"
         :class="rsKind === 'program' ? 'md:w-[48rem]' : 'md:w-[40rem]'"
         class="bg-gray-800 w-full h-[88vh] md:h-full overflow-y-auto border-t md:border-t-0 md:border-l border-gray-700 rounded-t-2xl md:rounded-none flex flex-col outline-none">
        <div class="sticky top-0 z-10 bg-gray-800 border-b border-gray-700 px-4 py-3 flex items-center gap-3">
            <h2 class="flex-1 min-w-0 text-lg font-extrabold text-white truncate" x-text="rsLabel()"></h2>
            <button type="button" data-record-sheet-close @click="close()" title="Close" aria-label="Close"
                    class="w-8 h-8 shrink-0 rounded-full bg-gray-900 text-white hover:bg-gray-700 font-bold">✕</button>
        </div>
        <div class="px-2 pt-2 pb-8">
            <div x-show="rsKind === 'thread'">{% include 'components/threads_page.html' %}</div>
            <div x-show="rsKind === 'mission'">{% include 'components/missions_page.html' %}</div>
            <div x-show="rsKind === 'program'">{% include 'components/programs_page.html' %}</div>
        </div>
    </div>
</div>
<script>
function chfRecordSheet() {
    return {
        rsOpen: false, rsKind: null, rsId: null, rsTitle: '',
        rsLabel() { return this.rsTitle || ({thread: 'Conversation', mission: 'Argyle’s work', program: 'Program'}[this.rsKind] || ''); },
        rsAddress(piece) {
            const q = new URLSearchParams(location.search);
            if (piece) q.set('piece', piece); else q.delete('piece');
            const s = q.toString();
            history.replaceState(history.state, '', location.pathname + (s ? '?' + s : '') + location.hash);
        },
        show(d) {
            if (!d || !['thread', 'mission', 'program'].includes(d.kind) || !d.id) return;
            this.rsKind = d.kind; this.rsId = d.id; this.rsTitle = d.title || ''; this.rsOpen = true;
            window.dispatchEvent(new CustomEvent('chf-record-sheet', {detail: {kind: d.kind, id: d.id}}));
            this.rsAddress(d.kind + ':' + d.id);
        },
        close() {
            this.rsOpen = false; this.rsKind = null; this.rsId = null; this.rsTitle = '';
            window.dispatchEvent(new CustomEvent('chf-record-sheet', {detail: {kind: null, id: null}}));
            this.rsAddress(null);
            window.dispatchEvent(new CustomEvent('chf-projects-open'));   // the project's cards re-read what changed
        },
    };
}
</script>
```

Names are `rs…` on purpose: the three components are nested inside this island and Alpine resolves a name a child does not define from its parent, so a plain `open` or `kind` here would leak into theirs.

`chauffeur/templates/components/projects_admin.html`:

```html
{# What the admin hosts of the Projects page add around the shared component
   (front door §2-§3): the record sheet now; the Projects drawer and the
   switched-off notices in the retirement task. The phone app never includes it. #}
{% include 'components/record_sheet.html' %}
```

`work.html`: inside `<section id="projects" data-page-tab="projects">`, after the projects include, add `{% include 'components/projects_admin.html' %}`. `projects.html`: after the projects include, the same line.

- [ ] **Step 4: Threads in sheet mode.** In `threads_page.html`:

Root (lines 6-7) becomes:

```html
{% set _sheet = sheet_mode|default(false) %}
        <div x-data="threadsPage({{ 'true' if _sheet else 'false' }})" x-init="{{ '' if _sheet else 'load()' }}"
            {% if _sheet %}@chf-record-sheet.window="onSheet($event.detail)"{% else %}x-effect="window.chfSetPageTabCount && window.chfSetPageTabCount('threads', groups[0].items.length)"{% endif %}
            class="{{ 'px-1 py-1' if _sheet else 'panel-page max-w-2xl mx-auto px-4 py-6' }}" x-cloak>
            {% if _sheet %}<p class="text-xs text-gray-500 italic px-1" x-show="only && loadedOnce && !groups.length">That conversation isn’t here, or isn’t yours to see.</p>{% endif %}
```

Wrap lines 9-91 (title, intro, the settings drawer call, the create form, the Show closed toggle — everything above `<div x-ref="lane">`) as:

```
            {% if not _sheet %}{# sheet:hide #}
            … lines 9-91 unchanged …
            {% endif %}{# /sheet:hide #}
```

Script: `function threadsPage(sheet = false)` and add to the returned object:

```js
                sheet, only: null, loadedOnce: false,
                onSheet(d) {
                    if (!d || d.kind !== 'thread' || !d.id) { this.only = null; return; }
                    this.only = d.id;
                    this.detailsOpen = { [d.id]: true };
                    this.load();
                },
```

In `load()`, set `this.loadedOnce = true;` right after `this.situations = sd2.situations || [];`. The `groups` getter becomes:

```js
                get groups() {
                    const by = (g) => this.situations.filter(s => s.group === g && (!this.sheet || s.id === this.only));
                    const all = this._allGroups(by);
                    if (this.sheet) return all.filter(g => g.items.length).map(g => ({ ...g, folded: false }));
                    return this.showClosed ? all : all.filter(g => g.key !== 'done');
                },
```

- [ ] **Step 5: Missions in sheet mode.** In `missions_page.html`:

Root (line 17) becomes:

```html
{% set _sheet = sheet_mode|default(false) %}
        <div x-data="missionsSettings({{ 'true' if _sheet else 'false' }})" x-init="{{ 'load(); startPolling()' if _sheet else 'load(); loadAdmin(); startPolling()' }}"
            {% if _sheet %}@chf-record-sheet.window="onSheet($event.detail)"{% endif %}
            class="{{ 'px-1 py-1' if _sheet else 'panel-page max-w-2xl mx-auto px-4 py-6' }}" x-cloak>
```

Wrap lines 19-150 (title, intro, `settings_off`, the whole drawer) in `{% if not _sheet %}{# sheet:hide #}` … `{% endif %}{# /sheet:hide #}`, and the launch card (164-180, the `<div class="bg-gray-800 rounded-2xl border border-gray-700 p-4">` holding "Launch a mission") the same way.

Script: `function missionsSettings(sheet = false)`, add:

```js
                sheet, only: null,
                onSheet(d) {
                    if (!d || d.kind !== 'mission' || !d.id) { this.only = null; return; }
                    this.only = d.id;
                    this.detailsOpen = { [d.id]: true };
                    this.loadAdmin();
                },
```

`groups` filters `s => s.group === g && (!this.sheet || s.id === this.only)` and, when `this.sheet`, returns only non-empty groups. `startPolling` polls only when there is something to watch: `if (document.visibilityState === 'visible' && (!this.sheet || this.only)) this.loadAdmin();`.

- [ ] **Step 6: Build Tailwind and run**

Run: `cd chauffeur && python tools/build_tailwind.py && unset HA_BASE_URL && PROJECTS_SHOTS=<scratchpad> python tests/test_record_sheet_live.py && python tests/test_projects_detail_live.py && python tests/test_projects_live.py && python tests/test_start_mission.py && python tests/test_planned_mission_cards.py`
Expected: the five record-sheet scenarios PASS except the program one (Task 4); the others PASS. Look at `slice2-thread-sheet.png` and `slice2-mission-sheet.png`: the frame matches the settings drawer's (header, ✕, scroll inside), the card and details read as they did on the old pages.

Also open `/work?tab=threads` and `/work?tab=missions` once by hand (or with `page.goto` in a scratch script) and check the old pages are unchanged (title, drawer, create form, lanes): sheet mode must not touch them until retirement.

- [ ] **Step 7: Commit**

```bash
git add chauffeur/templates/components/record_sheet.html chauffeur/templates/components/projects_admin.html chauffeur/templates/work.html chauffeur/templates/projects.html chauffeur/templates/components/threads_page.html chauffeur/templates/components/missions_page.html chauffeur/static/tailwind*.css chauffeur/tests/test_record_sheet_live.py
git commit -m "feat(projects): the record sheet - a project's thread or mission opens beside it with its old page's controls, one record at a time, the keeper's record alone (front door slice 2, Task 3)"
```

---

### Task 4: Programs in sheet mode (Claude)

**Files:**
- Modify: `chauffeur/templates/components/programs_page.html` (root 14-17, wrap 19-248, script `programsPage`, `sections`)
- Test: `chauffeur/tests/test_record_sheet_live.py` (add `scenario_a_program_in_the_sheet`)

**Interfaces:**
- Consumes: `chf-record-sheet` (Task 3), `sheet_mode`.
- Produces: `programsPage(sheet=false)` with `onSheet(detail)`.

- [ ] **Step 1: Add the failing scenario** to `test_record_sheet_live.py` (and to `SCENARIOS`):

```python
def scenario_a_program_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-piece-open="program:pr-live"]', timeout=15000)
        sheet = _sheet(page, 'program:pr-live')
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Strength basics')", timeout=15000)
        text = sheet.inner_text()
        for label in ('Log a session', 'Pause', 'Finished', 'Re-shape the week', 'Drop'):
            check(label in text, f"the active program sheet has {label}")
        check('Tiling basics' not in text and 'Programs settings' not in page.content(), "one program, no drawer")
        page.evaluate("() => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind: 'program', id: 'pr-prop'}}))")
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Tiling basics')", timeout=10000)
        text = page.locator('[data-record-sheet]').inner_text()
        for label in ('Look again', 'Dismiss'):
            check(label in text, f"the proposed program sheet has {label}")
        check('Strength basics' not in text, "only the new one")
        shot(page, 'slice2-program-sheet')
        check(served.errors() == [], f"no page errors: {served.errors()}")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_record_sheet_live.py`
Expected: `scenario_a_program_in_the_sheet` FAILS (the program component shows its whole page or nothing).

- [ ] **Step 3: The change.** In `programs_page.html`:

Root (14-17) becomes:

```html
{% set _sheet = sheet_mode|default(false) %}
<div x-data="programsPage({{ 'true' if _sheet else 'false' }})" x-init="{{ 'readIdentity()' if _sheet else 'load()' }}"
     @lesson-player:done.window="onLessonDone($event.detail)"
     {% if _sheet %}@chf-record-sheet.window="onSheet($event.detail)"{% else %}x-effect="window.chfSetPageTabCount && window.chfSetPageTabCount('programs', programs.filter(p => p.state === 'proposed' && canAct(p)).length)"{% endif %}
     class="{{ 'px-1 py-1' if _sheet else 'panel-page max-w-2xl mx-auto px-4 py-6' }}" x-cloak>
```

(the non-sheet class is the file's current one, `panel-page max-w-2xl mx-auto px-4 py-6`). Wrap 19-248 (title, intro, the drawer with its three sections, `settings_off`, the propose form) in `{% if not _sheet %}{# sheet:hide #}` … `{% endif %}{# /sheet:hide #}`.

Script: `function programsPage(sheet = false)`; add:

```js
                sheet, only: null,
                onSheet(d) {
                    if (!d || d.kind !== 'program' || !d.id) { this.only = null; return; }
                    this.only = d.id;
                    this.archiveOpen = true;
                    this.load();
                },
```

`sections` becomes:

```js
                get sections() {
                    const keep = list => this.sheet ? list.filter(p => p.id === this.only) : list;
                    const all = [
                        { key: 'proposed', label: 'Proposed', titleClass: 'text-blue-400',
                          items: keep(this.proposedList), empty: 'Nothing proposed yet.', archived: false },
                        { key: 'live', label: 'Under way', titleClass: 'text-gray-500',
                          items: keep(this.liveList), empty: 'No program is active yet.', archived: false },
                        { key: 'archive', label: 'Done & dropped (' + this.archiveList.length + ')',
                          titleClass: 'text-gray-600',
                          items: keep(this.archiveList), empty: 'Nothing finished yet.', archived: true },
                    ];
                    return this.sheet ? all.filter(s => s.items.length) : all;
                },
```

The lesson player include (825) stays: no admin host of the Projects page includes a second one (`work.html` and `projects.html` do not; `rhythms.html` hosts no record sheet).

- [ ] **Step 4: Build Tailwind and run**

Run: `cd chauffeur && python tools/build_tailwind.py && unset HA_BASE_URL && PROJECTS_SHOTS=<scratchpad> python tests/test_record_sheet_live.py && python tests/test_projects_live.py && python tests/test_programs_endpoints.py`
Expected: PASS. Look at `slice2-program-sheet.png`: the wider frame, the card reads as on the Programs page; open `/rhythms?tab=programs` once and check the page is unchanged.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/templates/components/programs_page.html chauffeur/static/tailwind*.css chauffeur/tests/test_record_sheet_live.py
git commit -m "feat(projects): a project's program opens in the wider record sheet with its plan, lessons, footprint and every action (front door slice 2, Task 4)"
```

---

### Task 5: The phone's piece sheet (Claude)

**Files:**
- Modify: `chauffeur/templates/app.html` (`renderHouseThreads` ~6538: extract the note/photo builder; `afterProgramWrite`; new `openPieceSheet` beside `openSessionSheet` ~1925)
- Test: `chauffeur/tests/test_project_sheets_phone_live.py`

**Interfaces:**
- Consumes: `chf-record-sheet-open` (Task 2); `GET /api/situations/{kind}/{sid}`; `GET /api/programs?include_finished=true`; `renderProgramCard(p, commitmentsById)`; `_pwaModal(inner, wire)`.
- Produces: `houseThreadExtras(s, canNote) -> string` (one builder for the House lane and the sheet); `openPieceSheet(detail)`; `refreshPieceSheet()`; marker `[data-piece-sheet]` on the sheet body.

- [ ] **Step 1: Write the failing live test** `chauffeur/tests/test_project_sheets_phone_live.py`:

```python
"""A project's piece in the phone's action sheet (front door spec §2, slice 2, Task 5).
Run from chauffeur/:  python tests/test_project_sheets_phone_live.py"""
from project_sheets_fixture import IDS, check, pwa, serve, shot


def _projects_tab(page, served, who):
    page.set_viewport_size({'width': 390, 'height': 844})
    pwa(page, served, who)
    page.goto(served.url('app'), wait_until='load')
    page.wait_for_selector('#tab-projects', timeout=20000)
    page.locator('#tab-projects').click()


def scenario_a_parent_opens_a_thread_and_a_program():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        _projects_tab(page, served, 'mom')
        page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=15000)
        page.locator(f'[data-project-id="{IDS["bath"]}"]').first.click()
        page.wait_for_selector(f'[data-piece-open="thread:{IDS["thread"]}"]', timeout=10000)
        page.locator(f'[data-piece-open="thread:{IDS["thread"]}"]').click()
        page.wait_for_selector('[data-piece-sheet]', timeout=10000)
        text = page.locator('[data-piece-sheet]').inner_text()
        check('Tiler' in text and 'Add note' in text and 'Add a photo' in text, f"the thread's card with note and photo: {text[:300]}")
        shot(page, 'slice2-phone-thread')
        page.locator('[data-pwa-dismiss]').first.click()
        page.locator('[data-piece-open="program:pr-live"]').click()
        page.wait_for_selector('[data-piece-sheet]', timeout=10000)
        check('Strength basics' in page.locator('[data-piece-sheet]').inner_text(), "the phone's own program card")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_child_has_no_mission_to_open():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        _projects_tab(page, served, 'kid')
        page.wait_for_selector('[data-project-id="prj-bike"]', timeout=15000)
        page.locator('[data-project-id="prj-bike"]').first.click()
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        check(page.locator('[data-piece-open^="mission:"]').count() == 0, "no mission for a child")


SCENARIOS = [scenario_a_parent_opens_a_thread_and_a_program, scenario_a_child_has_no_mission_to_open]

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

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_project_sheets_phone_live.py`
Expected: FAIL at `[data-piece-sheet]` (nothing answers the event on the phone).

- [ ] **Step 3: One builder for the thread extras.** In `renderHouseThreads`, move the `extraHtml` arrow's body into a top-level function and call it:

```js
        // The House lane's note and photo controls on a thread, one builder for
        // the lane and for a project's piece sheet (front door §2).
        function houseThreadExtras(s, canNote) {
            if (!canNote) return '';
            return `<form onsubmit="houseAddThreadNote(event, '${mfEscape(s.id)}')" class="flex gap-2 mt-2.5">
                        <input type="text" id="house-thread-note-${mfEscape(s.id)}" placeholder="A call made, a document received…" autocomplete="off"
                            class="flex-1 bg-gray-950 border border-gray-700 rounded-xl px-3 py-2 text-[13px] text-gray-100 placeholder-gray-600">
                        <button type="submit" class="px-3 rounded-xl bg-gray-800 border border-gray-700 text-gray-300 text-xs font-bold active:bg-gray-700 shrink-0">Add note</button>
                    </form>
                    <label class="inline-flex items-center gap-1 text-xs text-gray-400 mt-1.5 cursor-pointer">📷 Add a photo
                        <input type="file" accept="image/*" capture="environment" class="hidden" data-thread-photo
                               onchange="houseAddThreadPhoto(event, '${mfEscape(s.id)}')"></label>`;
        }
```

and `extraHtml: (s) => houseThreadExtras(s, canNote)`. In `houseAddThreadPhoto` and `houseAddThreadNote`, after the existing `fetchHouseThreads()` calls, add `refreshPieceSheet();`.

- [ ] **Step 4: The sheet.** Beside `openSessionSheet`:

```js
        // A project's thread, mission or program on the phone (front door §2):
        // the Projects tab asks for it; the phone's own builders draw it in the
        // action sheet. The admin record sheet never loads here.
        let pieceSheet = null;   // {detail, close}
        async function pieceSheetBody(kind, id) {
            if (kind === 'program') {
                const r = await fetch(`${apiBase}api/programs?include_finished=true`);
                const d = r.ok ? await r.json() : { programs: [] };
                const p = (d.programs || []).find(x => x.id === id);
                return p ? renderProgramCard(p, {}) : '';
            }
            const r = await fetch(`${apiBase}api/situations/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
            if (!r.ok || !window.Situations) return '';
            const s = await r.json();
            const canNote = ['parent', 'adult'].includes(currentMemberRole());
            return window.Situations.cardHtml(s, pieceSheetCtx(s)) + (kind === 'thread' ? houseThreadExtras(s, canNote) : '');
        }
        function pieceSheetCtx(s) {
            return { apiBase, canWrite: ['parent', 'adult'].includes(currentMemberRole()), readOnly: false,
                     memberId: selectedMemberId, lookup: () => s, onChange: () => refreshPieceSheet() };
        }
        async function openPieceSheet(detail) {
            if (!detail || !['thread', 'mission', 'program'].includes(detail.kind) || !detail.id) return;
            if (pieceSheet) pieceSheet.close();
            const html = await pieceSheetBody(detail.kind, detail.id);
            const inner = `<div class="pwa-sheet-head"><span>${mfEscape(detail.title || '')}</span>
                    <button class="pwa-sheet-close" data-close aria-label="Close">&#215;</button></div>
                <div data-piece-sheet class="space-y-2">${html || '<p class="text-xs text-gray-500 italic">That isn’t here, or isn’t yours to see.</p>'}</div>`;
            _pwaModal(inner, (overlay, close) => {
                pieceSheet = { detail, close: () => { pieceSheet = null; close(); }, overlay };
                overlay.querySelector('[data-close]').onclick = () => pieceSheet && pieceSheet.close();
                const body = overlay.querySelector('[data-piece-sheet]');
                if (detail.kind !== 'program' && window.Situations) window.Situations.bind(body, pieceSheetCtx(null));
            });
        }
        async function refreshPieceSheet() {
            if (!pieceSheet) return;
            const body = pieceSheet.overlay.querySelector('[data-piece-sheet]');
            if (body) body.innerHTML = await pieceSheetBody(pieceSheet.detail.kind, pieceSheet.detail.id);
            window.dispatchEvent(new CustomEvent('chf-projects-open'));
        }
        window.addEventListener('chf-record-sheet-open', (e) => openPieceSheet(e.detail));
```

Read `_pwaModal` (3232-3245) before writing: if its header already draws a close (`[data-pwa-dismiss]`), drop the `pwa-sheet-head` block above and wire that control instead; keep one close only. In `afterProgramWrite()`, add `refreshPieceSheet();` at its end.

- [ ] **Step 5: Run**

Run: `cd chauffeur && python tools/build_tailwind.py && unset HA_BASE_URL && PROJECTS_SHOTS=<scratchpad> python tests/test_project_sheets_phone_live.py && python tests/test_projects_live.py && python tests/test_pwa_adult_shell_live.py`
Expected: PASS. Look at `slice2-phone-thread.png` against the design guide's sheet rules (25px heading, 22px padding, one green primary, scroll within 85dvh).

- [ ] **Step 6: Commit**

```bash
git add chauffeur/templates/app.html chauffeur/static/tailwind*.css chauffeur/tests/test_project_sheets_phone_live.py
git commit -m "feat(projects): the phone's piece sheet - a project's thread, mission or program opens in the action sheet with the phone's own cards (front door slice 2, Task 5)"
```

---

### Task 6: The parity test — the gate for retirement (Claude)

**Files:**
- Create: `chauffeur/tests/test_projects_parity.py`

**Interfaces:**
- Consumes: the strip markers `{# sheet:hide #}` / `{# /sheet:hide #}` (Tasks 3–4); every file the sheets and the Projects page render.
- Produces: `PARITY` (one row per inventory capability) that Task 8 extends with the settings rows.

- [ ] **Step 1: Write the test.** Every inventory row names where it lives after retirement and one marker that must be present there in what is actually RENDERED (sheet-hidden regions stripped). The live scenarios of Tasks 2–5 prove the sheet renders those files for a record; this table proves nothing the old pages held was left behind in a hidden region or deleted.

```python
"""Parity: every capability of the Threads, Missions and Programs pages lives in a
piece sheet, the Projects page or the Projects drawer before those pages retire
(front door spec §2 "Parity rule", slice 2, Task 6). One row per inventory line
(docs/superpowers/specs/2026-10-15-projects-front-door-inventory.md).

Run from chauffeur/:  python tests/test_projects_parity.py
"""
import os
import re

from harness import check  # noqa: F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = 'templates/components/'
TP, MP, PP, MT = T + 'threads_page.html', T + 'missions_page.html', T + 'programs_page.html', T + 'mission_transcript.html'
PJ, PF, APP = T + 'projects_page.html', T + 'project_piece_forms.html', 'templates/app.html'
SJ, MTJ = 'static/situations.js', 'static/mission_transcript.js'

# (inventory line, file, marker)
PARITY = [
    # Threads
    ('Threads: create (title, goal, kind, owner, contact or name+email, first next action and date)', PF, 'data-piece-form="thread"'),
    ('Threads: create posts the counterparty and next action', PJ, 'counterparty_name: f.counterparty_name'),
    ('Threads: lanes', PJ, 'data-lane'),
    ('Threads: show closed, remembered', PJ, 'chf_projects_show_closed'),
    ('Threads: card options through ACT', TP, 'window.Situations.cardHtml(s, cardCtx())'),
    ('Threads: set or change the next step', TP, 'submitAdvance('),
    ('Threads: draft a message', TP, 'requestDraft('),
    ('Threads: look something up', TP, 'submitResearch('),
    ('Threads: the asks ledger and reply options', SJ, 'asks'),
    ('Threads: history with photos and readings', TP, 't.history'),
    ('Threads: missions opened from the thread', TP, 'threadMissions[t.id]'),
    ('Threads: send a draft', TP, 'sendDraft('),
    ('Threads: add a note', TP, 'submitNote('),
    ('Threads: photo', TP, 'uploadPhoto('),
    ('Threads: work this', TP, 'workThis('),
    ('Threads: edit', TP, 'submitEdit('),
    ('Threads: done or drop', TP, 'closeThread('),
    ('Threads: delete', TP, 'deleteThread('),
    # Missions
    ('Missions: launch a goal with a tier', PF, 'name="tier"'),
    ('Missions: launch posts the tier', PJ, 'tier: f.tier'),
    ('Missions: the plan stepper', MP, 'planStepperHtml'),
    ('Missions: card options through ACT', MP, 'window.Situations.cardHtml(s, cardCtx())'),
    ('Missions: the transcript', MP, "include 'components/mission_transcript.html'"),
    ('Missions: answer or steer', MP, 'sendAnswer('),
    ('Missions: drop', MP, 'drop('),
    ('Missions: OK', MP, 'ack('),
    ('Missions: delete', MP, 'deleteMission('),
    ('Missions: proposal approve or dismiss', MT, 'proposalAct('),
    ('Missions: release, submit, verify', MT, 'releaseMission('),
    ('Missions: submit', MT, 'submitMission('),
    ('Missions: verify', MT, 'verifyMission('),
    ('Missions: transcript helpers', MTJ, 'actProposal'),
    ('Missions: the keeper and anyone with a record but not its project', PJ, "api/projects/for/"),
    ('Missions: your work elsewhere', PJ, 'data-lane="elsewhere"'),
    # Programs
    ('Programs: propose (aim, whom, start, sessions, minutes, days, target)', PF, 'data-piece-form="program"'),
    ('Programs: propose posts the shape', PJ, 'preferred_days: f.preferred_days'),
    ('Programs: the shelf', PJ, 'data-lane-filter="programs"'),
    ('Programs: Part of', PP, 'chfPartOf('),
    ('Programs: why this one, also considered', PP, 'whyText('),
    ('Programs: the lesson ladder and open the lesson', PP, 'toggleLesson('),
    ('Programs: play a lesson', PP, 'playLesson('),
    ('Programs: tonight windows and start session', PP, 'todayWindowsFor('),
    ('Programs: lesson editor add', PP, 'addLessonRow('),
    ('Programs: lesson editor remove', PP, 'removeLessonRow('),
    ('Programs: lesson editor reorder', PP, 'moveLessonRow('),
    ('Programs: lesson editor save', PP, 'saveLesson('),
    ('Programs: lesson regenerate', PP, 'regenerateLesson('),
    ('Programs: another session or move on', PP, 'moveUnit('),
    ('Programs: reached it', PP, 'markMilestone('),
    ('Programs: not these times', PP, 'startSlotEdit('),
    ('Programs: save the times', PP, 'saveSlots('),
    ('Programs: plan without the book', PP, 'replanWithoutBooks('),
    ('Programs: approve, claim this time', PP, 'approveProgram('),
    ('Programs: edit a proposal', PP, 'saveEdit('),
    ('Programs: look again', PP, 'lookAgain('),
    ('Programs: dismiss', PP, 'dismissProgram('),
    ('Programs: log a session', PP, 'logSession('),
    ('Programs: pause', PP, 'pauseProgram('),
    ('Programs: resume', PP, 'resumeProgram('),
    ('Programs: finished', PP, 'finishProgram('),
    ('Programs: re-shape the week', PP, 'reshapeProgram('),
    ('Programs: drop', PP, 'dropProgram('),
    # Phone surfaces stay (Decision 8)
    ('Phone: House threads', APP, 'renderHouseThreads'),
    ('Phone: House thread note and photo', APP, 'houseThreadExtras('),
    ('Phone: the program card', APP, 'renderProgramCard('),
    ('Phone: the session sheet', APP, 'openSessionSheet('),
    ('Phone: a project piece in the action sheet', APP, 'openPieceSheet('),
    ('Phone: mission chat cards', APP, 'renderMissionAskCard('),
]


def _rendered(path):
    """The file as a sheet renders it: sheet-hidden regions removed."""
    text = open(os.path.join(ROOT, path), encoding='utf-8').read()
    return re.sub(r'\{# sheet:hide #\}.*?\{# /sheet:hide #\}', '', text, flags=re.S)


def scenario_every_inventory_line_has_a_home():
    missing = [(line, path, marker) for line, path, marker in PARITY if marker not in _rendered(path)]
    check(not missing, "no home for: " + '; '.join(f"{l} ({p}: {m})" for l, p, m in missing))


def scenario_the_hidden_regions_are_only_chrome():
    for path in (TP, MP, PP):
        text = open(os.path.join(ROOT, path), encoding='utf-8').read()
        opened, closed = text.count('{# sheet:hide #}'), text.count('{# /sheet:hide #}')
        check(opened == closed and opened >= 1, f"{path}: balanced sheet-hidden regions ({opened}/{closed})")
        hidden = ''.join(re.findall(r'\{# sheet:hide #\}(.*?)\{# /sheet:hide #\}', text, flags=re.S))
        for marker in ('cardHtml(', 'sendAnswer(', 'approveProgram(', 'submitNote('):
            check(marker not in hidden, f"{path}: a record control hides in a sheet-hidden region: {marker}")


def scenario_the_sheets_mount_the_components():
    sheet = open(os.path.join(ROOT, T + 'record_sheet.html'), encoding='utf-8').read()
    for comp in ('threads_page.html', 'missions_page.html', 'programs_page.html'):
        check(f"include 'components/{comp}'" in sheet, f"the record sheet mounts {comp}")
    check('{% set sheet_mode = true %}' in sheet, "in sheet mode")
    for host in ('templates/work.html', 'templates/projects.html'):
        check("components/projects_admin.html" in open(os.path.join(ROOT, host), encoding='utf-8').read(), f"{host} hosts the sheet")


SCENARIOS = [scenario_every_inventory_line_has_a_home, scenario_the_hidden_regions_are_only_chrome, scenario_the_sheets_mount_the_components]

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

- [ ] **Step 2: Run the gate**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_projects_parity.py && python tests/test_record_sheet_live.py && python tests/test_projects_detail_live.py && python tests/test_project_sheets_phone_live.py`
Expected: all PASS. A missing row is a parity gap: fix the sheet or the Projects page, never the table. If a marker is simply worded differently in the file, correct the marker after reading the line (a ruling in the ledger).

To prove the table bites, delete `{# /sheet:hide #}` from the threads root wrap in a scratch copy, run `scenario_every_inventory_line_has_a_home` against it, see it fail, restore.

- [ ] **Step 3: Commit**

```bash
git add chauffeur/tests/test_projects_parity.py
git commit -m "test(projects): the parity gate - every Threads, Missions and Programs capability has a home in a sheet, the Projects page or the phone (front door slice 2, Task 6)"
```

**Retirement gate:** Tasks 7 and 8 start only after this commit with the four commands above green.

---

### Task 7: Redirects, navigation and links (Codex)

**Files:**
- Modify: `chauffeur/main.py` (`/threads` ~1867, `/missions` ~1816, `/programs` ~1871, `/work` ~1810, `/rhythms` ~1769)
- Modify: `chauffeur/templates/nav.html:113-136` (`PAGE_GROUPS`), `:734` (kiosk hide list)
- Modify: `chauffeur/templates/work.html` (drop the missions and threads sections), `chauffeur/templates/rhythms.html` (drop the programs section)
- Modify: `chauffeur/services/subjects.py:661,671` (thread and program links)
- Modify: `chauffeur/templates/occasions.html:133`, `chauffeur/templates/trip.html:1120`, `chauffeur/static/study.js:147,636`, `chauffeur/static/house.js:246`, `chauffeur/static/kitchen_overlay.js:94`, `chauffeur/services/watchers.py:463,473`
- Test: `chauffeur/tests/test_retire_redirects.py`

**Interfaces:**
- Consumes: `projects?piece=<kind>:<id>` resolved by the page (Task 2), `projects?lane=programs` (Task 2).
- Produces: the redirects; links that land on the Projects page.

- [ ] **Step 1: Write the failing test** `chauffeur/tests/test_retire_redirects.py`:

```python
"""The Threads, Missions and Programs pages retire behind redirects (front door
spec §3, slice 2, Task 7). Run from chauffeur/:  python tests/test_retire_redirects.py"""
import os

from fastapi.testclient import TestClient

from harness import check  # noqa: F401
import main
from services import subjects

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = TestClient(main.app)


def _to(path):
    r = CLIENT.get(path, follow_redirects=False)
    check(r.status_code in (302, 307), f"{path} redirects: {r.status_code}")
    return r.headers['location']


def scenario_records_land_on_their_sheet():
    check(_to('/threads?id=T1') == 'projects?piece=thread:T1', "a thread link")
    check(_to('/missions?id=M1') == 'projects?piece=mission:M1', "a mission link")
    check(_to('/programs?id=P1') == 'projects?piece=program:P1', "a program link")
    check(_to('/work?tab=threads&id=T1') == 'projects?piece=thread:T1', "the Work tab form")
    check(_to('/work?tab=missions&id=M1') == 'projects?piece=mission:M1', "the Work tab form")
    check(_to('/rhythms?tab=programs&id=P1') == 'projects?piece=program:P1', "the Rhythms tab form")


def scenario_bookmarks_without_an_id():
    check(_to('/threads') == 'projects', "Threads")
    check(_to('/missions') == 'projects', "Missions")
    check(_to('/programs') == 'projects?lane=programs', "Programs keeps one place for all programs")
    check(_to('/work?tab=threads') == 'work?tab=projects', "the Work tab")
    check(_to('/rhythms?tab=programs') == 'projects?lane=programs', "the Rhythms tab")
    check(CLIENT.get('/work?tab=mind', follow_redirects=False).status_code == 200, "the Mind tab stays")
    check(CLIENT.get('/rhythms?tab=routines', follow_redirects=False).status_code == 200, "Routines stays")


def scenario_navigation():
    nav = open(os.path.join(ROOT, 'templates', 'nav.html'), encoding='utf-8').read()
    groups = nav.split('{% set PAGE_GROUPS = {')[1].split('} %}')[0]
    for gone in ("'key': 'threads'", "'key': 'missions'", "'key': 'programs'"):
        check(gone not in groups, f"the tab is gone: {gone}")
    for kept in ("'key': 'projects'", "'key': 'intake'", "'key': 'mind'", "'key': 'chores'", "'key': 'routines'"):
        check(kept in groups, f"the tab stays: {kept}")
    check("'projects'" in nav.split("kioskTabs.includes")[0].split("forEach(slug")[0][-400:], "the kiosk hides Projects")
    work = open(os.path.join(ROOT, 'templates', 'work.html'), encoding='utf-8').read()
    check("components/missions_page.html" not in work and "components/threads_page.html" not in work, "Work hosts neither page")
    rhythms = open(os.path.join(ROOT, 'templates', 'rhythms.html'), encoding='utf-8').read()
    check("components/programs_page.html" not in rhythms, "Rhythms no longer hosts Programs")


def scenario_links_land_on_projects():
    check(subjects.link('thread', 'T1') == 'projects?piece=thread:T1', "a thread's subject link")
    check(subjects.link('program', 'P1') == 'projects?piece=program:P1', "a program's subject link")
    for rel, old in (('templates/occasions.html', "apiBase + 'threads'"), ('templates/trip.html', "apiBase + 'threads'"),
                     ('static/study.js', "'/programs'"), ('static/house.js', "'programs'],"), ('static/kitchen_overlay.js', "study_binders: 'programs'")):
        check(old not in open(os.path.join(ROOT, rel), encoding='utf-8').read(), f"{rel} no longer links to a retired page")
    watchers = open(os.path.join(ROOT, 'services', 'watchers.py'), encoding='utf-8').read()
    check('/missions' not in watchers, "the watcher's words name the Projects page")


SCENARIOS = [scenario_records_land_on_their_sheet, scenario_bookmarks_without_an_id, scenario_navigation, scenario_links_land_on_projects]

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

- [ ] **Step 2: Run to verify it fails**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_retire_redirects.py`
Expected: FAIL (`/threads` answers 200).

- [ ] **Step 3: The redirects.** In `main.py`:

```python
def _retired_to(kind: str, request: Request, empty: str):
    """An old Threads, Missions or Programs address (front door §3): the page
    resolves the record and its project itself, so the redirect names no project."""
    rid = request.query_params.get('id')
    return RedirectResponse(f'projects?piece={kind}:{rid}' if rid else empty)


@app.get("/threads")
def threads_page(request: Request):
    return _retired_to('thread', request, 'projects')

@app.get("/missions")
def missions_page(request: Request):
    return _retired_to('mission', request, 'projects')

@app.get("/programs")
def programs_page(request: Request):
    return _retired_to('program', request, 'projects?lane=programs')
```

`/work`: before the template response, `tab = request.query_params.get('tab'); if tab in ('threads', 'missions'): return _retired_to(tab[:-1], request, 'work?tab=projects')`.
`/rhythms`: after the growing-up redirect, `if request.query_params.get('tab') == 'programs': return _retired_to('program', request, 'projects?lane=programs')`.

Delete `templates/threads.html`, `templates/missions.html` and `templates/programs.html` (nothing renders them any more). In `work.html` remove the `missions` and `threads` `<section>`s; in `rhythms.html` remove the `programs` `<section>`; update both comments to say what each page now hosts. In `nav.html` `PAGE_GROUPS` remove the `programs`, `threads` and `missions` entries; in the kiosk hide list (734) add `'projects'` and keep the others.

`services/auth.py`: the `/threads`, `/missions`, `/programs` rules stay ANYONE (they are redirects now); update their comments.

- [ ] **Step 4: The links.**
- `subjects.py:661`: `link=lambda sid: f'projects?piece=thread:{sid}'`; `:671`: `link=lambda sid: f'projects?piece=program:{sid}'`.
- `occasions.html:133` and `trip.html:1120`: `'projects'` in place of `'threads'` (the Argyle line names its thread's project; with no id it lands on the overview).
- `study.js:147,636`, `house.js:246`, `kitchen_overlay.js:94`: `'projects?lane=programs'` (or `/projects?lane=programs` where the original had a leading slash) in place of the programs page.
- `watchers.py:463,473`: "the Projects page" in place of "/missions".

- [ ] **Step 5: Run**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_retire_redirects.py && python tests/test_subjects.py && python tests/test_subject_registry.py && python tests/test_projects_detail_live.py && python tests/test_record_sheet_live.py && python tests/test_auth.py`
Expected: PASS (`tests/test_auth.py` scenario_a_every_route_is_classified covers the new routes through the existing wildcards).

- [ ] **Step 6: Commit** (Claude, after review)

```bash
git add -A chauffeur/main.py chauffeur/templates chauffeur/static chauffeur/services/subjects.py chauffeur/services/watchers.py chauffeur/services/auth.py chauffeur/tests/test_retire_redirects.py
git commit -m "feat(projects): Threads, Missions and Programs retire behind redirects to the Projects page and its sheets; navigation and links follow (front door slice 2, Task 7)"
```

---

### Task 8: The settings move into the Projects drawer (Claude)

**Files:**
- Create: `chauffeur/templates/components/threads_settings.html`, `missions_settings.html`, `programs_settings.html`
- Modify: `chauffeur/templates/components/threads_page.html`, `missions_page.html`, `programs_page.html` (the drawer markup moves out; the sheet-hidden regions shrink to title, intro and create form)
- Modify: `chauffeur/templates/components/projects_admin.html`
- Modify: `chauffeur/templates/components/threads_page.html` and `programs_page.html` scripts (`loadSettings()`)
- Modify: `chauffeur/services/settings_registry.py:658-764` (`page=` for every threads, missions and programs entry)
- Test: `chauffeur/tests/test_projects_parity.py` (settings rows), `chauffeur/tests/test_settings_registry.py` (unchanged, must stay green), `chauffeur/tests/test_record_sheet_live.py` (add `scenario_the_projects_drawer`)

**Interfaces:**
- Consumes: the three components' own save methods (`saveStallDays`, `save`, `savePaidKey`, `removePaidKey`, `netcheck`, `saveProgramSettings`, `runLessonSweep`, `playSweepSlot`).
- Produces: one drawer `data-settings-for="projects"` with sections `missions-settings`, `browse`, `contact-card`, `threads-settings`, `programs-settings`, `lessons`, `programs-pacing`; registry `page='work?tab=projects'` for all of them.

- [ ] **Step 1: Extend the parity table** in `test_projects_parity.py` (append to `PARITY`; `S = T + '{}_settings.html'`):

```python
    ('Settings: thread stall days', T + 'threads_settings.html', 'saveStallDays('),
    ('Settings: missions on, paid key, pool, caps', T + 'missions_settings.html', 'savePaidKey('),
    ('Settings: remove the paid key', T + 'missions_settings.html', 'removePaidKey('),
    ('Settings: browser and check the network', T + 'missions_settings.html', 'netcheck('),
    ('Settings: the household contact card', T + 'missions_settings.html', 's.contact_first_name'),
    ('Settings: programs on and generation', T + 'programs_settings.html', 's.programs_enabled'),
    ('Settings: lessons and write lessons now', T + 'programs_settings.html', 'runLessonSweep('),
    ('Settings: play a swept slot', T + 'programs_settings.html', 'playSweepSlot('),
    ('Settings: pacing', T + 'programs_settings.html', 's.programs_research_pages'),
    ('Settings: one Projects drawer', T + 'projects_admin.html', "settings_drawer('projects'"),
    ('Settings: missions off, turn on', T + 'projects_admin.html', "'missions-settings'"),
    ('Settings: programs off, turn on', T + 'projects_admin.html', "'programs-settings'"),
```

and the live scenario in `test_record_sheet_live.py` (add to `SCENARIOS`):

```python
def scenario_the_projects_drawer():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('work?tab=projects#threads-settings'), wait_until='load')
        page.wait_for_selector('[data-settings-for~="projects"][data-open="true"]', timeout=15000)
        drawer = page.locator('[data-settings-for~="projects"]')
        text = drawer.inner_text()
        for label in ('Stalls after', 'Household contact card', 'Pacing'):
            check(label in text, f"the Projects drawer holds {label}")
        box = drawer.locator('#threadStallDays')
        box.fill('9'); box.dispatch_event('change')
        from project_sheets_fixture import storage
        for _ in range(40):
            if (storage.get_settings() or {}).get('thread_stall_days') == 9:
                break
            page.wait_for_timeout(250)
        check((storage.get_settings() or {}).get('thread_stall_days') == 9, "the moved input still saves")
        shot(page, 'slice2-projects-drawer')
        check(served.errors() == [], f"no page errors: {served.errors()}")
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd chauffeur && unset HA_BASE_URL && python tests/test_projects_parity.py && python tests/test_record_sheet_live.py`
Expected: the settings rows and `scenario_the_projects_drawer` FAIL.

- [ ] **Step 3: Move the sections.**
- `threads_settings.html`: the `{% call settings_section('threads-settings', 'Stalls') %} … {% endcall %}` block (threads_page.html 18-31) verbatim, with the macro import line `{% from 'components/settings_drawer.html' import settings_section with context %}` at the top. Remove the `{% call settings_drawer('threads', 'Threads') %}` / `{% endcall %}` pair and its content from threads_page.html.
- `missions_settings.html`: the three sections (missions_page.html 28-149: `missions-settings`, `browse`, `contact-card`) verbatim with the same import line. Remove the drawer call and its content from missions_page.html; the `settings_off` line (26) moves to `projects_admin.html` (below).
- `programs_settings.html`: the three sections (programs_page.html 30-177, including the hand-written `lessons` section with its sweep report) verbatim with the same import. Remove the drawer call and content from programs_page.html; its `settings_off` line (179) moves to `projects_admin.html`.

After the move, the `{# sheet:hide #}` regions in the three components wrap only the title, intro and create form; the parity table's `scenario_the_hidden_regions_are_only_chrome` keeps passing.

- [ ] **Step 4: Settings-only loads.** In `threadsPage` add:

```js
                async loadSettings() {
                    try {
                        const r = await fetch(this.apiBase + 'api/settings');
                        const sd = r.ok ? await r.json() : {};
                        if (sd.thread_stall_days !== undefined && sd.thread_stall_days !== null) this.s.thread_stall_days = sd.thread_stall_days;
                    } catch (e) { /* the drawer shows the default */ }
                },
```

In `programsPage` add `async loadSettings() { this.readIdentity(); try { const r = await fetch(this.apiBase + 'api/settings'); const d = r.ok ? await r.json() : {}; for (const k of Object.keys(this.s)) if (d[k] !== undefined) this.s[k] = d[k]; this.settingsLoaded = true; } catch (e) { /* defaults */ } },` (read `load()` 924-951 first and copy its exact settings block if it differs). `missionsSettings().load()` already loads only settings.

- [ ] **Step 5: The Projects drawer.** `projects_admin.html` becomes:

```html
{# What the admin hosts of the Projects page add around the shared component
   (front door §2-§3): the switched-off notices, the one Projects drawer, the
   record sheet. Each settings partial sits in a small island of its owning
   component, so every input saves through the method it always used. The
   phone app never includes this file. #}
{% from 'components/settings_drawer.html' import settings_drawer, settings_off with context %}
<div x-data="missionsSettings()" x-init="load()">
    {{ settings_off('Argyle’s work is off — Argyle runs none.', 'projects', 'missions-settings', 'loaded && !s.missions_enabled') }}
</div>
<div x-data="programsPage()" x-init="loadSettings()">
    {{ settings_off('Programs are off — no program is proposed or claims a week.', 'projects', 'programs-settings', 'settingsLoaded && !s.programs_enabled') }}
</div>
{% call settings_drawer('projects', 'Projects', sections=[('missions-settings', 'Argyle’s work'), ('browse', 'Browser'), ('contact-card', 'Contact card'), ('threads-settings', 'Threads'), ('programs-settings', 'Programs'), ('lessons', 'Lessons'), ('programs-pacing', 'Pacing')]) %}
<div x-data="missionsSettings()" x-init="load()" class="flex flex-col gap-6">{% include 'components/missions_settings.html' %}</div>
<div x-data="threadsPage()" x-init="loadSettings()" class="flex flex-col gap-6">{% include 'components/threads_settings.html' %}</div>
<div x-data="programsPage()" x-init="loadSettings()" class="flex flex-col gap-6">{% include 'components/programs_settings.html' %}</div>
{% endcall %}
{% include 'components/record_sheet.html' %}
```

Copy the `settings_off` wording from the original lines (missions_page.html:26, programs_page.html:179) with "Missions" read as "Argyle’s work" where the sentence names the page. Check the macro's caller sits inside no Alpine `<template>` and under no `transform` ancestor (design guide); `work.html`'s `<section data-page-tab="projects">` qualifies.

`programsPage()` is defined in `programs_page.html`'s script, which the record sheet includes after this point; Alpine starts after every script has run, so the island resolves it. The same holds for `threadsPage` and `missionsSettings`.

- [ ] **Step 6: The registry.** In `services/settings_registry.py`, every entry with `page='work?tab=missions'`, `page='work?tab=threads'` or `page='rhythms?tab=programs'` becomes `page='work?tab=projects'` (anchors unchanged).

- [ ] **Step 7: Run**

Run: `cd chauffeur && python tools/build_tailwind.py && unset HA_BASE_URL && python tests/test_projects_parity.py && python tests/test_settings_registry.py && PROJECTS_SHOTS=<scratchpad> python tests/test_record_sheet_live.py && python tests/test_projects_detail_live.py && python tests/test_retire_redirects.py`
Expected: PASS. `test_settings_registry.py` `scenario_no_setting_is_unreachable` proves every moved anchor sits inside the drawer for tab `projects` on `work.html`. Look at `slice2-projects-drawer.png` (chips across the top, each section as it was).

- [ ] **Step 8: Commit**

```bash
git add chauffeur/templates/components chauffeur/services/settings_registry.py chauffeur/static/tailwind*.css chauffeur/tests/test_projects_parity.py chauffeur/tests/test_record_sheet_live.py
git commit -m "feat(projects): one Projects drawer holds Argyle's work, Threads and Programs settings, the switched-off notices move with them, the settings index follows (front door slice 2, Task 8)"
```

---

## Build split (the user's standing rule)

Claude writes every test first. Codex (`codex:rescue`, background) builds **Task 1** (the server side) and **Task 7** (redirects, navigation, links), each with its test file as the contract and the gate commands above. Claude builds **Tasks 2, 3, 4, 5, 6 and 8** (templates, the sheet, the phone, the drawer: convention-heavy work with screenshots). Whoever did not write a task reviews it; a whole-branch Codex review runs at the end. Claude runs the gates, updates `system_capabilities.md`, bumps the version and commits.
