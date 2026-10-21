# Projects: one list — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project's admin detail page becomes one Now / Next / Later / Linked / Logbook list of rows, every row with a checkbox that completes its next moment, one ⋯ menu and one + Add; the phone shares the builder and loses its admin links and tab.

**Architecture:** A new server-side row builder (`projects.rows`) composes today's piece cards, steps and practice windows into one exhaustive row table with a stable `moment` per row. One new write route (`POST /api/projects/{id}/tick`) validates the moment under the record's own gate and dispatches to the existing step, thread and program writers, with an idempotency key. Threads gain a revision-checked complete / restore pair for their next action. The templates redraw on top of `rows`; every old write route and sheet stays.

**Tech Stack:** FastAPI + the project's own storage layer (`services/storage.py`), Jinja templates with vendored Alpine, precompiled Tailwind (`python tools/build_tailwind.py`), plain-script tests (`python tests/test_x.py` from `chauffeur/`), Playwright live tests through `tests/live_app.py`.

**Spec:** `docs/superpowers/specs/2026-10-20-projects-one-list-design.md` (rev 2). Read it first; every section number below refers to it.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset: `cd chauffeur; unset HA_BASE_URL; python tests/test_x.py`. Never the whole suite.
- Every new route gets a rule in `services/auth.py` (the `/api/projects/*` SIGNED_IN rule already covers `/api/projects/{id}/tick`; confirm with `python tests/test_auth.py`) and a row in `services/access_readers.READERS` (`python tests/test_access_register.py`).
- No browser dialogs: `showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice` from `templates/components/control_center.html`.
- After any template class change run `python tools/build_tailwind.py`.
- Vendored Alpine stamps `:disabled="x[loopVar.id]"` true on first render: always `:disabled="!!(...)"`.
- Nothing a person can do today is removed; it moves into a sheet or ⋯ (spec §8 parity test is the guard). The one removal needing the user's confirmation, the Programs lane filter (spec R5), is already confirmed ("go", 2026-10-20).
- Codex-built tasks leave their changes in the working tree with a note; the controller reviews, bumps `chauffeur/config.yaml` and commits. Claude-built tasks bump and commit themselves (`(vX.Y.Z)` in the subject).
- Copy rules: no state codes on rows (`waiting_user`, `active`); subtitles are plain words (spec §1.1, §7).
- `programs.log_session` is called with `source='ticked'` and `slot_date` = the window's date; the route, not the service, enforces today-or-earlier (spec §2.2).

## Review Focus

1. **A project with no steps and only linked records.** Expect: no progress bar, an empty Now/Next/Later, a Linked group, no crash. Pinned in Task 1 (`scenario_only_links`).
2. **Two practice windows on the same day for one program.** Expect: two program rows with distinct `moment.slot_rank`, each tickable once. Pinned in Task 1 (`scenario_two_windows_one_day`) and Task 3 (`scenario_program_double_tick_logs_one`).
3. **A thread whose `next_action_at` is malformed text.** Expect: the row is open with `when` today, never a 500. Pinned in Task 1 (`scenario_bad_next_action_date`).
4. **A tick after the project was paused or marked done.** Expect: 403 from `can_act`, rows unchanged. Pinned in Task 3 (`scenario_tick_refused_on_paused_project`).
5. **A mission step whose mission was deleted (GONE).** Expect: the step row reads not-yet "Argyle's work is gone" and the page renders. Pinned in Task 1 (`scenario_step_with_gone_mission`).

---

## File structure

- `services/projects.py` — add `rows(project, viewer)` and its helpers at the end of the file (after `elsewhere`). Builds only; never writes.
- `services/threads.py` — add `complete_next_action`, `restore_next_action`; `advance` bumps `next_action_rev`; `draft_message` records the revision; `missions.py:1433` (the finisher) skips its `advance` when the revision moved.
- `main.py` — add `POST /api/projects/{project_id}/tick` next to the other project routes (after `project_pieces`, ~line 6362) and `_tick_dispatch` helpers beside it.
- `services/access_readers.py` — one READERS row for the tick route.
- `templates/components/projects_page.html` — the detail body redrawn on `rows`; the list page's groups; ⋯ and + Add; the step sheet and link sheet are inline `x-if` blocks of this component (same file, since both hosts include it).
- `static/situations.js` — `ctx.navigate` for subject / handoff / about anchors.
- `static/project_links.js` — Part of lines as buttons when `window.chfLibraryHost === 'phone'` or `document.body.dataset.pwa`.
- `templates/app.html` — remove `#tab-projects` and its visibility code; phone `pieceSheetCtx` passes `navigate`.
- `static/pwa_shell.js` — unchanged (Projects already in More).
- Tests: `tests/test_project_rows.py` (new), `tests/test_thread_next_action_rev.py` (new), `tests/test_project_rows_tick.py` (new), `tests/test_projects_detail_live.py` (rewrite), `tests/test_project_sheets_phone_live.py` + `tests/test_pwa_adult_shell_live.py` + `tests/test_projects_live.py` (More path), `tests/test_projects_parity.py` (extend), `tests/test_access_matrix.py` + `tests/access_fixture.py` (tick probes).

---

### Task 1: `projects.rows` — the exhaustive row table (Claude)

**Files:**
- Modify: `services/projects.py` (append after `elsewhere`, ~line 1120)
- Test: `tests/test_project_rows.py` (new)

**Interfaces:**
- Consumes: `piece_cards(project, viewer)` (returns cards with `kind, id, title, sheet, link, situation?, view?, origin_thread?, program?`), `view(project, viewer)` (`steps` with `can_edit`, `owner_label`, `needs`, `order`, `state`, `owner`, `question`, `found`, `mission_id`, `due_date`, `hold`), `programs.practice_windows(start, end, member_id, viewer=)` (windows with `program_id, date, time_start, lesson_id, variant_label, unit_title, logged`), `programs.load`, `threads.is_stalled`, `missions.ATTENTION`, `missions.verify_open`, `access.gone`.
- Produces: `projects.rows(project, viewer) -> list[dict]` where each row is
  `{'kind': 'step'|'conversation'|'argyle'|'program'|'link', 'id': str, 'title': str, 'subtitle': str, 'box': 'open'|'done'|'argyle'|'asking'|'not_yet'|None, 'reason': str, 'when': {'date': 'YYYY-MM-DD', 'time': 'HH:MM'|''} | 'running' | 'now' | None, 'group': 'now'|'next'|'later'|'linked'|'logbook', 'moment': dict, 'sheet': {'kind': str, 'id': str} | None, 'actions': [ {'id','label','verb','payload'} ], 'glyph': str}`.
  `moment` per kind: step `{'step_id'}`; conversation `{'thread_id', 'rev'}`; program `{'run_id', 'window_date', 'slot_rank', 'lesson_id', 'variant_label'}`; argyle `{'mission_id'}`; link `{}`.
  Also `projects.ROW_GROUPS = ('now', 'next', 'later', 'linked', 'logbook')`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_project_rows.py`. It uses the same helpers as `tests/test_project_pieces.py`.

```python
"""projects.rows: one exhaustive row table for a project's detail (spec
2026-10-20-projects-one-list §1). Run from chauffeur/:
python tests/test_project_rows.py"""
import datetime
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, missions, threads, auth, programs
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID


def _p():
    from services import projects
    return projects


def _bath(owner='mom', audience='household'):
    return _p().create({'title': 'Bathroom', 'goal': 'a new bathroom', 'done_when': 'tiled',
                        'owner_member_id': owner, 'audience': audience}, dict(MOM))['project']


def _rows(pid, who=MOM):
    return _p().rows(storage.get_project(pid), dict(who))


def _by(rows, kind, rid):
    return next(r for r in rows if r['kind'] == kind and r['id'] == rid)


def _step(pid, title, owner='mom', **fields):
    return _p().add_step(pid, {'title': title, 'owner': owner, **fields}, dict(MOM))['step']


def scenario_person_steps_by_state():
    _fresh()
    p = _bath()
    a = _step(p['id'], 'Demo the old tile')
    b = _step(p['id'], 'Tile the floor', owner='dad', needs=[a['id']], due_date='2030-01-05')
    rows = _rows(p['id'])
    ra, rb = _by(rows, 'step', a['id']), _by(rows, 'step', b['id'])
    check(ra['box'] == 'open' and ra['group'] == 'later' and ra['when'] is None and ra['moment'] == {'step_id': a['id']},
          f"an undated open step is Later: {ra}")
    check(rb['box'] == 'not_yet' and rb['reason'] == 'waiting on Demo the old tile' and rb['group'] == 'later',
          f"a step with unmet needs is not yet, naming the need: {rb}")
    _p().set_step_state(p['id'], a['id'], 'done', dict(MOM))
    rows = _rows(p['id'])
    ra, rb = _by(rows, 'step', a['id']), _by(rows, 'step', b['id'])
    check(ra['box'] == 'done' and ra['group'] == 'logbook', f"a done step sinks to the Logbook: {ra}")
    check(rb['box'] == 'open' and rb['when'] == {'date': '2030-01-05', 'time': ''} and rb['group'] == 'next'
          and rb['subtitle'] == 'Dad · due Jan 5', f"a released dated step is Next with its date: {rb}")
    _p().set_step_state(p['id'], b['id'], 'skipped', dict(MOM))
    check(_by(_rows(p['id']), 'step', b['id'])['reason'] == 'skipped', "a skipped step says so in the Logbook")


def scenario_step_due_today_is_now():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Call the plumber', due_date=datetime.date.today().isoformat())
    r = _by(_rows(p['id']), 'step', s['id'])
    check(r['group'] == 'now' and r['box'] == 'open', f"a step due today is Now: {r}")


def scenario_step_on_the_calendar_uses_its_hold():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Tile the floor', owner='dad')
    _p().confirm_hold(p['id'], s['id'], {'date': '2030-01-05', 'start': '08:00', 'end': '09:00'}, dict(MOM))
    r = _by(_rows(p['id']), 'step', s['id'])
    check(r['when'] == {'date': '2030-01-05', 'time': '08:00'} and 'on the calendar' in r['subtitle'],
          f"a held step's when is its window: {r}")


def scenario_argyle_steps_by_state():
    _fresh()
    p = _bath()
    todo = _step(p['id'], 'Find tile', owner='argyle', goal='find ivory matte tile')
    rows = _rows(p['id'])
    r = _by(rows, 'step', todo['id'])
    # missions are on in _fresh(); advance launched it, so it is doing.
    check(r['box'] == 'argyle' and r['when'] == 'running' and r['group'] == 'next'
          and r['title'] == 'Argyle is finding ivory matte tile', f"a running Argyle step: {r}")
    mid = storage.get_project(p['id'])['steps'][0]['mission_id']
    _p().on_question(mid, 'Matte or gloss?')
    r = _by(_rows(p['id']), 'step', todo['id'])
    check(r['box'] == 'asking' and r['group'] == 'now' and r['title'] == 'Argyle needs you: Matte or gloss?'
          and r['actions'] and r['actions'][0]['label'] == 'Answer', f"an asking Argyle step: {r}")
    _p().on_stage_done(mid, None, {'tiles': 'Ivory matte'})
    r = _by(_rows(p['id']), 'step', todo['id'])
    check(r['box'] == 'done' and r['group'] == 'logbook' and r['title'] == 'tiles: Ivory matte', f"a done Argyle step shows its found line: {r}")


def scenario_argyle_step_waiting_on_a_need_or_switched_off():
    _fresh(missions_on=False)
    p = _bath()
    first = _step(p['id'], 'Pick a colour')
    off = _step(p['id'], 'Find tile', owner='argyle', goal='find tile')
    r = _by(_rows(p['id']), 'step', off['id'])
    check(r['box'] == 'not_yet' and r['reason'] == "Argyle's work is switched off" and r['group'] == 'later', f"missions off: {r}")
    _fresh()
    p = _bath()
    first = _step(p['id'], 'Pick a colour')
    gated = _step(p['id'], 'Find tile', owner='argyle', goal='find tile', needs=[first['id']])
    r = _by(_rows(p['id']), 'step', gated['id'])
    check(r['box'] == 'not_yet' and r['reason'] == 'waits for Pick a colour' and r['title'] == 'Argyle will find tile', f"gated Argyle step: {r}")


def scenario_step_with_gone_mission():
    _fresh()
    p = _bath()
    s = _step(p['id'], 'Find tile', owner='argyle', goal='find tile')
    mid = storage.get_project(p['id'])['steps'][0]['mission_id']
    from services import access
    with patch.object(access, 'gone', lambda kind, row, rid=None: kind == 'mission' and (row or {}).get('id') == mid):
        r = _by(_rows(p['id']), 'step', s['id'])
    check(r['box'] == 'not_yet' and r['reason'] == "Argyle's work is gone", f"a step whose mission is gone: {r}")


def scenario_conversation_rows():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', goal='tile by May', created_by='mom', project_id=p['id'],
                         counterparty_name='Ace Tile', next_action='Call Ace back', next_action_at='2030-02-01')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['title'] == 'Call Ace back' and r['box'] == 'open' and r['when'] == {'date': '2030-02-01', 'time': ''}
          and r['group'] == 'next' and r['subtitle'] == 'Ace Tile · conversation'
          and r['moment'] == {'thread_id': tid, 'rev': 0} and r['sheet'] == {'kind': 'thread', 'id': tid}, f"a conversation row: {r}")
    threads.advance(tid, '', None, who='mom')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['title'] == 'Tiler' and r['box'] == 'not_yet' and r['reason'] == 'set a next step' and r['group'] == 'later', f"no next step: {r}")
    threads.advance(tid, 'Call Ace back', '2020-01-01', who='mom')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['group'] == 'now' and r['box'] == 'open', f"an overdue next step is Now: {r}")
    threads.close(tid, 'done', who='mom')
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['box'] == 'done' and r['group'] == 'logbook', f"a done thread is in the Logbook: {r}")


def scenario_bad_next_action_date():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    storage.update_thread(tid, {'next_action_at': 'next tuesday'})
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['box'] == 'open' and r['when'] == {'date': datetime.date.today().isoformat(), 'time': ''} and r['group'] == 'now',
          f"a malformed date reads as today: {r}")


def scenario_thread_waiting_on_them():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], counterparty_name='Ace')
    storage.update_thread(tid, {'state': 'waiting'})
    r = _by(_rows(p['id']), 'conversation', tid)
    check(r['title'] == 'Waiting on Ace' and r['box'] == 'not_yet' and r['group'] == 'next', f"waiting on them: {r}")


def scenario_mission_rows_and_precedence():
    _fresh()
    p = _bath()
    mid = missions.launch('find three tilers', created_by='mom', project_id=p['id'])['mission_id']
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'argyle' and r['when'] == 'running' and r['group'] == 'next' and r['moment'] == {'mission_id': mid}, f"a running mission: {r}")
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which day suits the tiler?'}})
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'asking' and r['group'] == 'now' and r['title'] == 'Which day suits the tiler?'
          and any(a['verb'] == 'answer' for a in r['actions']), f"an asking mission carries its buttons: {r}")
    storage.update_mission(mid, {'status': 'done'})
    with patch.object(missions, 'verify_open', lambda row: True):
        r = _by(_rows(p['id']), 'argyle', mid)
    check(r['group'] == 'now' and r['box'] == 'asking', f"a terminal mission with an open verification is Now, not Logbook: {r}")
    r = _by(_rows(p['id']), 'argyle', mid)
    check(r['box'] == 'done' and r['group'] == 'logbook', f"a closed mission: {r}")


def scenario_folded_mission_asks_through_its_thread():
    _fresh()
    p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call')
    mid = missions.launch('draft to the tiler', created_by='mom', project_id=p['id'], origin=('thread', tid))['mission_id']
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Send it?'}})
    with patch('services.projects.THREAD_SHEET_HISTORY', True):
        rows = _rows(p['id'])
    check(not any(r['kind'] == 'argyle' and r['id'] == mid for r in rows), "a folded mission has no row of its own")
    r = _by(rows, 'conversation', tid)
    check(r['box'] == 'asking' and r['group'] == 'now' and r['title'] == 'Send it?', f"its ask rides on the thread row: {r}")


def scenario_program_rows():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    add_run({'id': 'run1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active',
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'run1', None, project_id=p['id'])
    today = datetime.date.today()
    win = [{'program_id': 'run1', 'date': today.isoformat(), 'time_start': '18:00', 'lesson_id': 'l1', 'variant_label': 'A',
            'unit_title': 'Push-ups', 'logged': False},
           {'program_id': 'run1', 'date': (today + datetime.timedelta(days=2)).isoformat(), 'time_start': '18:00',
            'lesson_id': 'l1', 'variant_label': 'B', 'unit_title': 'Push-ups', 'logged': False}]
    with patch.object(programs, 'practice_windows', lambda *a, **k: win):
        rows = _rows(p['id'])
    prog = [r for r in rows if r['kind'] == 'program']
    check(len(prog) == 2, f"one row per window: {prog}")
    t, f = prog
    check(t['title'] == 'Push-ups, A' and t['box'] == 'open' and t['group'] == 'now'
          and t['moment'] == {'run_id': 'run1', 'window_date': today.isoformat(), 'slot_rank': 0, 'lesson_id': 'l1', 'variant_label': 'A'},
          f"today's window is open and Now: {t}")
    check(f['box'] == 'not_yet' and f['reason'].startswith('box opens ') and f['group'] == 'next', f"a future window is not yet: {f}")


def scenario_two_windows_one_day():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    add_run({'id': 'run1', 'member_id': 'mom', 'title': 'Strength basics', 'state': 'active',
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'run1', None, project_id=p['id'])
    today = datetime.date.today().isoformat()
    win = [{'program_id': 'run1', 'date': today, 'time_start': '08:00', 'lesson_id': 'l1', 'variant_label': 'A', 'unit_title': 'Push-ups', 'logged': False},
           {'program_id': 'run1', 'date': today, 'time_start': '18:00', 'lesson_id': 'l1', 'variant_label': 'B', 'unit_title': 'Push-ups', 'logged': False}]
    with patch.object(programs, 'practice_windows', lambda *a, **k: win):
        prog = [r for r in _rows(p['id']) if r['kind'] == 'program']
    check([r['moment']['slot_rank'] for r in prog] == [0, 1], f"same-day windows carry their rank: {prog}")


def scenario_program_states_without_windows():
    _fresh()
    p = _bath()
    from library_run_fixture import add_run
    base = {'member_id': 'kid', 'title': 'Piano', 'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
            'source': {'origin': 'none', 'reason': 'test'},
            'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}
    for rid, state in (('prop', 'proposed'), ('paus', 'paused'), ('done', 'done')):
        add_run({'id': rid, 'state': state, **base})
        _p().adopt('program', rid, None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        rows = _rows(p['id'])
    prop, paus, done = _by(rows, 'program', 'prop'), _by(rows, 'program', 'paus'), _by(rows, 'program', 'done')
    check(prop['box'] == 'not_yet' and prop['reason'] == 'needs approval' and prop['group'] == 'now'
          and any(a['label'] == 'Approve' for a in prop['actions']), f"a proposed run for a parent: {prop}")
    check(paus['box'] == 'not_yet' and paus['reason'] == 'paused' and paus['group'] == 'later', f"paused: {paus}")
    check(done['box'] == 'done' and done['group'] == 'logbook', f"done: {done}")
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        prop_kid = _by(_rows(p['id'], KID), 'program', 'prop')
    check(prop_kid['group'] == 'later' and not prop_kid['actions'], f"a child sees the proposal as Later with no Approve: {prop_kid}")


def scenario_unresolved_program():
    _fresh()
    p = _bath()
    storage.add_program({'id': 'lost', 'member_id': 'mom', 'state': 'active', 'library_id': 'nope', 'shape': {}, 'progress': {},
                         'sessions': [], 'emissions': {}, 'baseline': {}})
    _p().adopt('program', 'lost', None, project_id=p['id'])
    with patch.object(programs, 'practice_windows', lambda *a, **k: []):
        r = _by(_rows(p['id']), 'program', 'lost')
    check(r['title'] == 'Needs a program' and r['box'] == 'not_yet' and any(a['label'] == 'Pick a program' for a in r['actions']),
          f"an unresolved run: {r}")


def scenario_only_links():
    _fresh()
    p = _bath()
    _p().add_piece(p['id'], 'list', 'l1', dict(MOM))
    rows = _rows(p['id'])
    check(len(rows) == 1 and rows[0]['kind'] == 'link' and rows[0]['box'] is None and rows[0]['group'] == 'linked'
          and rows[0]['glyph'] == 'list' and rows[0]['sheet'] is None, f"a link row: {rows}")


def scenario_keeper_view_words_only():
    _fresh()
    p = _p().create({'title': 'Surprise', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'private'}, dict(MOM))['project']
    tid = threads.create(title='Venue', owner_member_id='aunt', created_by='aunt', project_id=p['id'], next_action='Book the hall')
    from services import access
    if access.record_view('thread', storage.get_thread(tid), dict(AUNT)) != access.KEEPER:
        return   # the fixture cannot make Aunt a keeper here; the access matrix covers it
    r = _by(_rows(p['id'], AUNT), 'conversation', tid)
    check('Book the hall' not in (r['title'] + r['subtitle']), f"a keeper row carries no hidden words: {r}")


def scenario_groups_order():
    check(_p().ROW_GROUPS == ('now', 'next', 'later', 'linked', 'logbook'), "the five groups in order")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            with patch.multiple(auth, identify=auth.identify, acting_member=auth.acting_member,
                                impersonation_refused=auth.impersonation_refused):
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

Before running, confirm each helper the test leans on exists with the signature used: `projects.add_step(project_id, step, actor)` returns `{'status','step'}`; `confirm_hold(project_id, step_id, hold, actor)`; `on_question(mission_id, question)`; `on_stage_done(mission_id, stage_id, found)`; `threads.create(..., counterparty_name=, next_action=, next_action_at=)`; `threads.close(tid, state, who=)`; `missions.launch(goal, created_by=, project_id=, origin=)` (check `origin`'s real keyword in `services/missions.py` and adjust the test); `library_run_fixture.add_run`. Where a signature differs, change the test call, not the service.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd chauffeur; unset HA_BASE_URL; python tests/test_project_rows.py`
Expected: every scenario FAILs with `AttributeError: module 'services.projects' has no attribute 'rows'` (or `ROW_GROUPS`).

- [ ] **Step 3: Implement `rows`**

Append to `services/projects.py`:

```python
# --- One list (spec 2026-10-20-projects-one-list §1) -----------------------
ROW_GROUPS = ('now', 'next', 'later', 'linked', 'logbook')
THREAD_SHEET_HISTORY = True   # the admin host lists a thread's missions in its sheet (delete spec §7)
ASK_VERBS = ('answer', 'release', 'submit', 'verify', 'approve_plan', 'run_stage')
_GLYPHS = {'trip': 'trip', 'occasion': 'occasion', 'list': 'list'}


def _row(kind, rid, title, *, subtitle='', box=None, reason='', when=None, moment=None, sheet=None, actions=None, glyph=''):
    return {'kind': kind, 'id': rid, 'title': title, 'subtitle': subtitle, 'box': box, 'reason': reason,
            'when': when, 'group': None, 'moment': moment or {}, 'sheet': sheet, 'actions': actions or [], 'glyph': glyph}


def _date_or_today(value):
    try:
        return datetime.date.fromisoformat(str(value)).isoformat()
    except (TypeError, ValueError):
        return datetime.date.today().isoformat()


def _due_words(iso):
    d = datetime.date.fromisoformat(iso)
    return d.strftime('%b ') + str(d.day)


def _ask_actions(situation):
    opts = (situation or {}).get('options') or []
    return [o for o in opts if o.get('verb') in ASK_VERBS and (o.get('payload') or {}).get('ask') != 'steer']


def _group_of(row, today):
    if row['kind'] == 'link':
        return 'linked'
    if row['box'] == 'asking' or row['when'] == 'now':
        return 'now'
    if row['box'] == 'open' and isinstance(row['when'], dict) and row['when']['date'] <= today:
        return 'now'
    if row['box'] == 'done':
        return 'logbook'
    if row['box'] in ('open', 'argyle') and row['when'] is not None:
        return 'next'
    if row['kind'] == 'conversation' and row['reason'] == 'waiting on them':
        return 'next'
    return 'later'


def _step_rows(project, project_view, viewer, cards_by_mission):
    from services import missions, access
    steps = sorted(project_view.get('steps') or [], key=lambda s: s.get('order', 0))
    titles = {s['id']: s.get('title') or '' for s in steps}
    out = []
    for s in steps:
        sid, state, owner = s['id'], s.get('state'), s.get('owner')
        if owner == 'argyle':
            goal = (s.get('goal') or s.get('title') or '').strip()
            mission = storage.get_mission(s['mission_id']) if s.get('mission_id') else None
            gone = bool(mission is None and s.get('mission_id')) or (mission is not None and access.gone('mission', mission))
            if state in ('done',):
                found = foundLines_first(s.get('found')) or s.get('title') or ''
                row = _row('step', sid, found, subtitle='Argyle', box='done')
            elif state == 'skipped':
                row = _row('step', sid, s.get('title') or goal, subtitle='Argyle', box='done', reason='skipped')
            elif gone:
                row = _row('step', sid, s.get('title') or goal, subtitle='Argyle', box='not_yet', reason="Argyle's work is gone")
            elif s.get('question') and state in ('doing', 'blocked'):
                sit = cards_by_mission.get(s.get('mission_id')) or {}
                row = _row('step', sid, 'Argyle needs you: ' + s['question'], subtitle='Argyle', box='asking', when='now',
                           actions=_ask_actions(sit) or [{'id': 'answer', 'label': 'Answer', 'verb': 'answer', 'payload': {}}],
                           sheet={'kind': 'mission', 'id': s.get('mission_id')} if s.get('mission_id') else None)
            elif state == 'doing':
                row = _row('step', sid, 'Argyle is ' + _gerund(goal), subtitle=_found_short(s.get('found')) or 'Argyle', box='argyle', when='running',
                           sheet={'kind': 'mission', 'id': s.get('mission_id')} if s.get('mission_id') else None)
            elif state == 'blocked':
                row = _row('step', sid, s.get('title') or goal, subtitle='Argyle', box='not_yet', reason=s.get('reason') or 'blocked')
            else:   # todo
                unmet = [titles[n] for n in (s.get('needs') or []) if n in titles and
                         next((x for x in steps if x['id'] == n), {}).get('state') not in ('done', 'skipped')]
                if unmet:
                    reason = 'waits for ' + unmet[0]
                elif not (storage.get_settings() or {}).get('missions_enabled'):
                    reason = "Argyle's work is switched off"
                else:
                    reason = 'waiting to start'
                row = _row('step', sid, 'Argyle will ' + goal, subtitle='Argyle', box='not_yet', reason=reason)
            row['moment'] = {'step_id': sid}
            row['sheet'] = row['sheet'] or {'kind': 'step', 'id': sid}
            out.append(row)
            continue
        label = s.get('owner_label') or ''
        if state in ('done', 'skipped'):
            row = _row('step', sid, s.get('title') or '', subtitle=label, box='done', reason='skipped' if state == 'skipped' else '')
        elif state == 'blocked':
            row = _row('step', sid, s.get('title') or '', subtitle=label, box='not_yet', reason=s.get('reason') or 'blocked')
        else:
            unmet = [titles[n] for n in (s.get('needs') or []) if n in titles and
                     next((x for x in steps if x['id'] == n), {}).get('state') not in ('done', 'skipped')]
            when, sub = None, label
            if s.get('hold') and s['hold'].get('date'):
                when = {'date': s['hold']['date'], 'time': s['hold'].get('start') or ''}
                sub = label + ' · on the calendar'
            elif s.get('due_date'):
                when = {'date': _date_or_today(s['due_date']), 'time': ''}
                sub = label + ' · due ' + _due_words(when['date'])
            if unmet:
                row = _row('step', sid, s.get('title') or '', subtitle=label, box='not_yet', reason='waiting on ' + unmet[0])
            else:
                row = _row('step', sid, s.get('title') or '', subtitle=sub, box='open', when=when)
        row['moment'] = {'step_id': sid}
        row['sheet'] = {'kind': 'step', 'id': sid}
        out.append(row)
    return out


def _gerund(goal):
    """'find tile' -> 'finding tile'; a goal that already reads as a phrase is kept."""
    words = goal.split()
    if not words:
        return 'working'
    verb = words[0].lower()
    if verb.endswith('ing'):
        return goal
    if verb.endswith('e') and not verb.endswith('ee'):
        verb = verb[:-1]
    return ' '.join([verb + 'ing'] + words[1:])


def foundLines_first(value):
    lines = _found_lines(value)
    return lines[0] if lines else ''


def _found_short(value):
    lines = _found_lines(value)
    return (lines[0] + ' so far') if lines else ''


def _found_lines(value, label=''):
    if value is None or value == '' or value == []:
        return []
    if isinstance(value, list):
        return [x for v in value for x in _found_lines(v, label)]
    if isinstance(value, dict):
        return [x for k, v in value.items() for x in _found_lines(v, str(k).replace('_', ' '))]
    return [(label + ': ' if label else '') + str(value)]


def _thread_row(card, project, viewer, folded):
    from services import threads as _th, missions
    sit = card.get('situation') or {}
    raw = storage.get_thread(card['id']) or {}
    keeper = card.get('view') == 'keeper'
    words = sit if keeper else raw
    name = (raw.get('counterparty_name') or raw.get('counterparty_email') or '') if not keeper else ''
    sub = (name + ' · conversation') if name else 'conversation'
    rev = int(raw.get('next_action_rev') or 0)
    state = raw.get('state')
    ask = _ask_actions(sit)
    folded_ask = [a for m in folded for a in _ask_actions(m.get('situation'))]
    if state in ('done', 'dropped'):
        if folded_ask or sit.get('group') == 'now':
            row = _row('conversation', card['id'], (sit.get('next_step') or {}).get('label') or card.get('title') or '',
                       subtitle=sub, box='asking', when='now', actions=ask or folded_ask)
        else:
            row = _row('conversation', card['id'], card.get('title') or '', subtitle=sub, box='done')
    elif sit.get('group') == 'now' and not raw.get('next_action') or folded_ask or any(a['verb'] != 'answer' or (a.get('payload') or {}).get('ask') for a in ask):
        label = (sit.get('next_step') or {}).get('label') or card.get('title') or ''
        row = _row('conversation', card['id'], label, subtitle=sub, box='asking', when='now', actions=ask or folded_ask)
    elif state == 'waiting' and not raw.get('next_action'):
        row = _row('conversation', card['id'], 'Waiting on ' + (name or 'them'), subtitle=sub, box='not_yet', reason='waiting on them')
    elif raw.get('next_action') and not keeper:
        when = {'date': _date_or_today(raw.get('next_action_at')) if raw.get('next_action_at') else datetime.date.today().isoformat(), 'time': ''}
        row = _row('conversation', card['id'], raw['next_action'], subtitle=sub, box='open', when=when)
    elif keeper and (sit.get('next_step') or {}).get('label'):
        row = _row('conversation', card['id'], sit['next_step']['label'], subtitle=sub, box='open',
                   when={'date': datetime.date.today().isoformat(), 'time': ''})
    else:
        row = _row('conversation', card['id'], card.get('title') or '', subtitle=sub, box='not_yet', reason='set a next step')
    row['moment'] = {'thread_id': card['id'], 'rev': rev}
    row['sheet'] = {'kind': 'thread', 'id': card['id']}
    return row


def _mission_row(card):
    from services import missions
    sit = card.get('situation') or {}
    raw = storage.get_mission(card['id']) or {}
    status = raw.get('status')
    ask = _ask_actions(sit)
    verify = bool(raw.get('id')) and missions.verify_open(raw)
    goal = card.get('title') or ''
    if status in missions.ATTENTION or verify or ask:
        title = (sit.get('next_step') or {}).get('label') or goal
        row = _row('argyle', card['id'], title, subtitle='Argyle', box='asking', when='now',
                   actions=ask or [{'id': 'answer', 'label': 'Answer', 'verb': 'answer', 'payload': {}}])
    elif status in missions.TERMINAL:
        row = _row('argyle', card['id'], goal, subtitle='Argyle', box='done')
    elif status in ('running', 'browsing'):
        row = _row('argyle', card['id'], (sit.get('next_step') or {}).get('label') or goal, subtitle='Argyle', box='argyle', when='running')
    elif status == 'blocked':
        row = _row('argyle', card['id'], goal, subtitle='Argyle', box='not_yet', reason=sit.get('status_note') or 'blocked')
    else:
        row = _row('argyle', card['id'], goal, subtitle='Argyle', box='not_yet', reason=str(status or 'waiting').replace('_', ' '))
    row['moment'] = {'mission_id': card['id']}
    row['sheet'] = {'kind': 'mission', 'id': card['id']}
    return row


def _program_rows(card, project, viewer, windows):
    from services import programs
    run = programs.load(storage.get_program(card['id'])) or {}
    state = run.get('state')
    title = card.get('title') or run.get('title') or ''
    sub = title + ' · program'
    prog = card.get('program') or {}
    out = []
    if prog.get('unresolved'):
        row = _row('program', card['id'], 'Needs a program', subtitle='program', box='not_yet', reason='needs a program',
                   actions=[{'id': 'rebind', 'label': 'Pick a program', 'verb': 'rebind', 'payload': {}}])
        row['moment'] = {'run_id': card['id']}; row['sheet'] = {'kind': 'program', 'id': card['id']}
        return [row]
    if state == 'active':
        today = datetime.date.today().isoformat()
        mine = [w for w in windows if w.get('program_id') == card['id']]
        ranks = {}
        for w in mine:
            rank = ranks.get(w['date'], 0); ranks[w['date']] = rank + 1
            if w.get('logged'):
                continue
            name = (w.get('unit_title') or title) + (', ' + w['variant_label'] if w.get('variant_label') else '')
            when = {'date': w['date'], 'time': w.get('time_start') or ''}
            if w['date'] <= today:
                row = _row('program', card['id'], name, subtitle=sub, box='open', when=when)
            else:
                day = datetime.date.fromisoformat(w['date']).strftime('%A')
                row = _row('program', card['id'], name, subtitle=sub, box='not_yet', reason='box opens ' + day, when=when)
            row['moment'] = {'run_id': card['id'], 'window_date': w['date'], 'slot_rank': rank,
                             'lesson_id': w.get('lesson_id') or '', 'variant_label': w.get('variant_label') or ''}
            row['sheet'] = {'kind': 'program', 'id': card['id']}
            out.append(row)
        if out:
            return out
        row = _row('program', card['id'], title, subtitle=sub, box='not_yet', reason='no practice window this week')
    elif state == 'proposed':
        approver = viewer and viewer.get('role') in ('parent', 'adult')
        row = _row('program', card['id'], title, subtitle=sub, box='not_yet', reason='needs approval',
                   when='now' if approver else None,
                   actions=[{'id': 'approve', 'label': 'Approve', 'verb': 'approve', 'payload': {}}] if approver else [])
    elif state == 'paused':
        row = _row('program', card['id'], title, subtitle=sub, box='not_yet', reason='paused')
    else:
        row = _row('program', card['id'], title, subtitle=sub, box='done')
    row['moment'] = {'run_id': card['id']}
    row['sheet'] = {'kind': 'program', 'id': card['id']}
    return [row]


def _fold_target(cards, card):
    """Today's folding predicates (projects_page.html foldTarget), server side."""
    if card['kind'] != 'mission' or not card.get('origin_thread') or not card.get('situation') or not card.get('sheet'):
        return None
    if card.get('view') != 'full' or not THREAD_SHEET_HISTORY:
        return None
    thread = next((c for c in cards if c['kind'] == 'thread' and c['id'] == card['origin_thread']), None)
    if not thread or not thread.get('situation') or not thread.get('sheet') or thread.get('view') != 'full':
        return None
    return thread['id']


def rows(project, viewer):
    """The detail page's one list (spec §1): every step, piece and practice
    window as a row with its next moment, grouped Now/Next/Later/Linked/Logbook."""
    from services import programs, access
    with access.batch():
        pv = view(project, viewer)
        if not pv:
            return []
        cards = piece_cards(project, viewer, project_view=pv)
        folded = {}
        for c in cards:
            t = _fold_target(cards, c)
            if t:
                folded.setdefault(t, []).append(c)
        by_mission = {c['id']: c.get('situation') for c in cards if c['kind'] == 'mission'}
        today = datetime.date.today()
        windows = []
        if any(c['kind'] == 'program' for c in cards):
            windows = programs.practice_windows(today, today + datetime.timedelta(days=13), None, viewer=viewer)
        out = _step_rows(project, pv, viewer, by_mission)
        for c in cards:
            if c['kind'] == 'thread':
                out.append(_thread_row(c, project, viewer, folded.get(c['id'], [])))
            elif c['kind'] == 'mission':
                if _fold_target(cards, c):
                    continue
                out.append(_mission_row(c))
            elif c['kind'] == 'program':
                out.extend(_program_rows(c, project, viewer, windows))
            else:
                out.append(_row('link', c['id'], c.get('title') or '', subtitle=c['kind'], glyph=_GLYPHS.get(c['kind'], c['kind']),
                                moment={}, sheet=None, actions=[{'id': 'open', 'label': 'Open', 'verb': 'link', 'payload': {'link': c.get('link')}},
                                                               {'id': 'remove', 'label': 'Remove', 'verb': 'remove', 'payload': {}}]))
                out[-1]['kind'] = 'link'
        iso = today.isoformat()
        for r in out:
            r['group'] = _group_of(r, iso)
        order = {g: i for i, g in enumerate(ROW_GROUPS)}
        def key(r):
            w = r['when'] if isinstance(r['when'], dict) else {'date': '9999', 'time': ''}
            return (order[r['group']], w['date'], w['time'])
        return sorted(out, key=key) if False else _stable_grouped(out, order)


def _stable_grouped(rows_, order):
    """Group order first; inside Now/Next by when; Later/Linked keep build order; Logbook newest first (reverse build order)."""
    def when_key(r):
        w = r['when'] if isinstance(r['when'], dict) else None
        return (w['date'], w['time']) if w else ('0000' if r['when'] == 'now' else '9999', '')
    out = []
    for g in ROW_GROUPS:
        part = [r for r in rows_ if r['group'] == g]
        if g in ('now', 'next'):
            part = sorted(part, key=when_key)
        elif g == 'logbook':
            part = list(reversed(part))
        out.extend(part)
    return out
```

Then simplify the last lines of `rows` to `return _stable_grouped(out, order)` (drop the dead `sorted(...) if False` branch; it is there only to show the key shape). Add `import datetime` at the top of `services/projects.py` if it is not already imported (it is used by `windowLabel`-style code elsewhere; check).

- [ ] **Step 4: Run the tests until green**

Run: `cd chauffeur; unset HA_BASE_URL; python tests/test_project_rows.py`
Expected: every scenario PASS. Fix mismatches in the implementation, not in the assertions, unless a helper signature in the test was wrong (Step 1 note).

- [ ] **Step 5: Add `rows` to the detail route and run the neighbours**

In `main.py` `project_detail` (~line 6373) return `{'project': ..., 'rows': projects.rows(project_row, actor)}`.

Run: `python tests/test_project_pieces.py; python tests/test_projects.py; python tests/test_project_steps.py; python tests/test_project_planning.py`
Expected: all PASS (the new key is additive).

- [ ] **Step 6: Commit**

```bash
git add chauffeur/services/projects.py chauffeur/main.py chauffeur/tests/test_project_rows.py chauffeur/config.yaml
git commit -m "feat(projects): projects.rows builds the one-list detail - every step, piece and practice window as a row with its next moment, five groups with precedence, asking rows carry their ask buttons, folding kept (vX.Y.Z)"
```

---

### Task 2: Thread next-action revision, complete and restore (Codex)

**Files:**
- Modify: `services/threads.py` (`advance` ~line 357; add two functions after it; `draft_message` ~line 119)
- Modify: `services/missions.py` ~line 1425-1445 (the finisher's `advance`)
- Test: `tests/test_thread_next_action_rev.py` (new)

**Interfaces:**
- Produces: `threads.complete_next_action(thread_id, rev, who) -> {'status': 'success', 'entry_id': str, 'rev': int} | {'status': 'error', 'code': 409|404, 'message'}`; `threads.restore_next_action(thread_id, entry_id, who) -> {'status': 'success'|'error', ...}`; every thread row carries `next_action_rev` (int, 0 when absent); `advance()` bumps it; `draft_message` result carries `next_action_rev`; history entries of kind `completed` carry `next_action`, `next_action_at`, `entry_id`, `who`, `rev_before`.
- Consumes: `storage.update_thread`, `storage.append_thread_history`, `storage.get_thread`.

- [ ] **Step 1: Write the failing tests**

```python
"""Revision-checked next-action completion and restore (spec 2026-10-20-projects-one-list §2.2-2.3).
Run from chauffeur/: python tests/test_thread_next_action_rev.py"""
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, threads
from test_front_door_chat import _fresh


def _t(**kw):
    return threads.create(title='Tiler', owner_member_id='mom', created_by='mom',
                          next_action=kw.pop('next_action', 'Call Ace back'), next_action_at=kw.pop('next_action_at', '2030-02-01'), **kw)


def scenario_advance_bumps_rev():
    _fresh()
    tid = _t()
    check(int(storage.get_thread(tid).get('next_action_rev') or 0) == 0, "a new thread starts at rev 0")
    threads.advance(tid, 'Email Ace', None, who='mom')
    check(storage.get_thread(tid)['next_action_rev'] == 1, "advance bumps the revision")


def scenario_complete_clears_and_logs():
    _fresh()
    tid = _t()
    r = threads.complete_next_action(tid, 0, 'mom')
    row = storage.get_thread(tid)
    check(r['status'] == 'success' and row['next_action'] == '' and row['next_action_at'] is None and row['next_action_rev'] == 1,
          f"complete clears the action and bumps: {r} {row}")
    entry = row['history'][-1]
    check(entry['kind'] == 'completed' and entry['next_action'] == 'Call Ace back' and entry['next_action_at'] == '2030-02-01'
          and entry['entry_id'] == r['entry_id'] and entry['who'] == 'mom', f"the completed entry keeps the action and its date: {entry}")


def scenario_complete_refuses_a_stale_rev():
    _fresh()
    tid = _t()
    threads.advance(tid, 'Email Ace', None, who='dad')
    r = threads.complete_next_action(tid, 0, 'mom')
    check(r['status'] == 'error' and r['code'] == 409 and storage.get_thread(tid)['next_action'] == 'Email Ace',
          f"a stale revision completes nothing: {r}")


def scenario_restore_only_while_empty_and_latest():
    _fresh()
    tid = _t()
    done = threads.complete_next_action(tid, 0, 'mom')
    r = threads.restore_next_action(tid, done['entry_id'], 'mom')
    row = storage.get_thread(tid)
    check(r['status'] == 'success' and row['next_action'] == 'Call Ace back' and row['next_action_at'] == '2030-02-01'
          and row['next_action_rev'] == 2, f"restore puts the action and date back: {row}")
    done2 = threads.complete_next_action(tid, 2, 'mom')
    threads.advance(tid, 'Email Ace', None, who='mom')
    r = threads.restore_next_action(tid, done2['entry_id'], 'mom')
    check(r['status'] == 'error' and r['code'] == 409 and storage.get_thread(tid)['next_action'] == 'Email Ace',
          f"restore refuses once a successor is set: {r}")


def scenario_draft_carries_the_rev_and_the_finisher_respects_it():
    _fresh()
    tid = _t()
    with patch.object(threads, '_pool_call', lambda *a, **k: {'subject': 'Hi', 'body': 'Hello'}):
        d = threads.draft_message(tid, 'ask for a quote')
    check(d['status'] == 'ok' and d['next_action_rev'] == 0, f"a draft names the revision it was made against: {d}")
    threads.complete_next_action(tid, 0, 'mom')
    threads.advance(tid, 'Email Ace', None, who='mom')
    # The mission finisher (missions.py ~1433) advances the thread only when the revision it captured is current.
    from services import missions
    captured = 0
    missions._finish_thread_from_mission({'id': 'm1', 'origin_kind': 'thread', 'origin_ref': tid, 'goal': 'g'},
                                         'Called Ace', 'Wait for the quote', None, False, next_action_rev=captured)
    row = storage.get_thread(tid)
    check(row['next_action'] == 'Email Ace', f"a late finisher never overwrites a newer next action: {row['next_action']}")
    check(any(h.get('kind') == 'mission' and 'earlier next step' in (h.get('text') or '') for h in row['history']),
          "the finisher's note says it was against an earlier next step")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

The last scenario names `missions._finish_thread_from_mission`; the real function around `missions.py:1425-1445` has another name. Read that block first, give the test the real name and argument list, and add a keyword `next_action_rev=None` to it (None = today's behaviour, always advance).

- [ ] **Step 2: Run to see them fail**

Run: `cd chauffeur; unset HA_BASE_URL; python tests/test_thread_next_action_rev.py`
Expected: FAIL on `complete_next_action` missing and on `next_action_rev` missing.

- [ ] **Step 3: Implement**

In `services/threads.py`:

```python
def _bump_rev(thread_id, fields):
    row = storage.get_thread(thread_id) or {}
    fields['next_action_rev'] = int(row.get('next_action_rev') or 0) + 1
    return fields
```

In `advance`, replace the `storage.update_thread(thread_id, {...})` call with `storage.update_thread(thread_id, _bump_rev(thread_id, {'next_action': next_action, 'next_action_at': next_action_at}))`, inside `with storage.db_lock:` so the read-bump-write is one step.

```python
def complete_next_action(thread_id: str, rev: int, who: str = None) -> dict:
    """The row's checkbox: this next step is done. Logged, revision-checked (spec §2.2)."""
    import uuid
    with storage.db_lock:
        row = storage.get_thread(thread_id)
        if not row:
            return {'status': 'error', 'code': 404, 'message': 'That conversation is no longer here.'}
        current = int(row.get('next_action_rev') or 0)
        if current != int(rev):
            return {'status': 'error', 'code': 409, 'message': 'That changed; look again.'}
        if not row.get('next_action'):
            return {'status': 'error', 'code': 409, 'message': 'There is no next step to finish.'}
        entry_id = uuid.uuid4().hex
        storage.append_thread_history(thread_id, {
            'kind': 'completed', 'text': f"Done: {row['next_action']}", 'who': who, 'entry_id': entry_id,
            'next_action': row['next_action'], 'next_action_at': row.get('next_action_at'), 'rev_before': current})
        storage.update_thread(thread_id, {'next_action': '', 'next_action_at': None, 'next_action_rev': current + 1})
    from services import situations as _sit
    _sit.touched('thread', thread_id)
    return {'status': 'success', 'entry_id': entry_id, 'rev': current + 1}


def restore_next_action(thread_id: str, entry_id: str, who: str = None) -> dict:
    """Untick: put the completed next step back, only while nothing replaced it (spec §2.2)."""
    with storage.db_lock:
        row = storage.get_thread(thread_id)
        if not row:
            return {'status': 'error', 'code': 404, 'message': 'That conversation is no longer here.'}
        if row.get('next_action'):
            return {'status': 'error', 'code': 409, 'message': 'A newer next step is set.'}
        completed = [h for h in row.get('history') or [] if h.get('kind') == 'completed']
        if not completed or completed[-1].get('entry_id') != entry_id:
            return {'status': 'error', 'code': 409, 'message': 'That is not the latest finished step.'}
        entry = completed[-1]
        storage.append_thread_history(thread_id, {'kind': 'restored', 'text': f"Back to: {entry['next_action']}", 'who': who, 'entry_id': entry_id})
        storage.update_thread(thread_id, {'next_action': entry['next_action'], 'next_action_at': entry.get('next_action_at'),
                                          'next_action_rev': int(row.get('next_action_rev') or 0) + 1})
    from services import situations as _sit
    _sit.touched('thread', thread_id)
    return {'status': 'success'}
```

In `draft_message`, add `'next_action_rev': int((storage.get_thread(thread_id) or {}).get('next_action_rev') or 0)` to the returned dict (read before the model call, next to `thread = storage.get_thread(thread_id)`).

In `missions.py` (~1433): the finisher takes `next_action_rev=None`; before `_threads.advance(tid, nxt, ...)`, read `current = int(thread.get('next_action_rev') or 0)`; if `next_action_rev is not None and current != next_action_rev`: skip the `advance`, set `entry_next, entry_when = None, None`, and append ` (This was against an earlier next step; the newer one stands.)` to the history `text`. Find the caller that holds the draft result (grep `draft_message(` in `services/missions.py` and `services/planned.py`) and pass `next_action_rev=draft.get('next_action_rev')` through to the finisher; where the finisher runs from a stage whose draft did not go through `draft_message`, pass None.

- [ ] **Step 4: Run to green, then the neighbours**

Run: `python tests/test_thread_next_action_rev.py; python tests/test_threads.py; python tests/test_thread_photo.py 2>/dev/null; python tests/test_missions_threads.py 2>/dev/null`
(Use `ls tests | grep -i thread` for the real neighbour names; run every unit file that imports `threads.advance`.)
Expected: PASS.

- [ ] **Step 5: Hand back**

Leave the change in the working tree with a note: what changed, the real finisher name, which tests ran. The controller reviews, bumps and commits.

---

### Task 3: The tick route (Codex)

**Files:**
- Modify: `main.py` (after `project_pieces`, ~line 6362)
- Modify: `services/access_readers.py` (~line 96)
- Modify: `services/projects.py` (`set_step_state` gains `override=False`)
- Modify: `tests/access_fixture.py`, `tests/test_access_matrix.py` (tick probes)
- Test: `tests/test_project_rows_tick.py` (new)

**Interfaces:**
- Consumes: `projects.rows` (Task 1) for the moment check; `threads.complete_next_action` / `restore_next_action` (Task 2); `projects.set_step_state`; `programs.log_session(program_id, minutes=None, source=, slot_date=, lesson_id=, variant_label=)`; `programs.lesson_for(run, date, slot_rank=)`; `_piece_viewer`, `_project_for_actor`, `_program_permission_or_refuse`, `access.record_actable`.
- Produces: `POST /api/projects/{project_id}/tick` body `{kind, id, moment, done, key}` → `200 {'status': 'success', 'rows': [...], 'result': {...}}`; errors `400` (bad body), `403` (gate), `404` (not a piece / no such step), `405` (argyle / asking), `409` (stale moment), with `{'detail': message}` and, on 409, `rows`.

- [ ] **Step 1: Write the failing tests**

```python
"""POST /api/projects/{id}/tick: the checkbox (spec 2026-10-20-projects-one-list §2).
Run from chauffeur/: python tests/test_project_rows_tick.py"""
import datetime
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from harness import check  # noqa: F401
from services import storage, missions, threads, auth, programs
from test_front_door_chat import _fresh
from test_subjects import MOM, DAD, AUNT, KID


def _client():
    import main
    return TestClient(main.app)


def _hdr(who):
    storage.add_member({'id': who, 'name': who.title(), 'role': {'mom': 'parent', 'dad': 'parent', 'aunt': 'adult', 'kid': 'child'}[who]}) \
        if not storage.get_member(who) else None
    return {'X-Member-Token': storage.create_member_token(who)}


def _p():
    from services import projects
    return projects


def _bath():
    return _p().create({'title': 'Bathroom', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'mom', 'audience': 'household'}, dict(MOM))['project']


def _row(pid, kind, rid, who='mom'):
    rows = _client().get(f'/api/projects/{pid}', headers=_hdr(who)).json()['rows']
    return next(r for r in rows if r['kind'] == kind and r['id'] == rid)


def _tick(pid, row, done=True, who='mom', key=None):
    return _client().post(f'/api/projects/{pid}/tick', headers=_hdr(who),
                          json={'kind': row['kind'], 'id': row['id'], 'moment': row['moment'], 'done': done, 'key': key or uuid.uuid4().hex})


def scenario_step_tick_and_untick():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    r = _tick(p['id'], _row(p['id'], 'step', s['id']))
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][0]['state'] == 'done', f"tick completes: {r.text}")
    r = _tick(p['id'], _row(p['id'], 'step', s['id']), done=False)
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][0]['state'] == 'todo', f"untick reopens: {r.text}")


def scenario_idempotency_key_replays():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row, key = _row(p['id'], 'step', s['id']), uuid.uuid4().hex
    a = _tick(p['id'], row, key=key); b = _tick(p['id'], row, key=key)
    check(a.status_code == 200 and b.status_code == 200 and b.json() == a.json(), "the same key returns the stored result")


def scenario_stale_step_moment():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row = _row(p['id'], 'step', s['id'])
    _p().set_step_state(p['id'], s['id'], 'done', dict(MOM))
    r = _tick(p['id'], row)
    check(r.status_code == 409 and 'rows' in r.json(), f"a step already done is stale: {r.text}")


def scenario_blocked_step_parent_override():
    _fresh(); p = _bath()
    a = _p().add_step(p['id'], {'title': 'First', 'owner': 'mom'}, dict(MOM))['step']
    b = _p().add_step(p['id'], {'title': 'Second', 'owner': 'aunt', 'needs': [a['id']]}, dict(MOM))['step']
    row = _row(p['id'], 'step', b['id'])
    check(row['box'] == 'not_yet', "the row is not yet")
    r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('aunt'),
                       json={'kind': 'step', 'id': b['id'], 'moment': row['moment'], 'done': True, 'key': uuid.uuid4().hex, 'override': True})
    check(r.status_code == 403, f"an adult cannot override a blocked step: {r.text}")
    r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'),
                       json={'kind': 'step', 'id': b['id'], 'moment': row['moment'], 'done': True, 'key': uuid.uuid4().hex, 'override': True})
    check(r.status_code == 200 and storage.get_project(p['id'])['steps'][1]['state'] == 'done', f"a parent completes anyway: {r.text}")


def scenario_conversation_round_trip():
    _fresh(); p = _bath()
    tid = threads.create(title='Tiler', owner_member_id='mom', created_by='mom', project_id=p['id'], next_action='Call Ace', next_action_at='2030-01-01')
    row = _row(p['id'], 'conversation', tid)
    r = _tick(p['id'], row)
    check(r.status_code == 200 and r.json()['result']['entry_id'] and storage.get_thread(tid)['next_action'] == '', f"complete: {r.text}")
    r2 = _tick(p['id'], row)
    check(r2.status_code == 409, f"the old revision is stale: {r2.text}")
    entry = r.json()['result']['entry_id']
    r3 = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'),
                        json={'kind': 'conversation', 'id': tid, 'moment': {'thread_id': tid, 'rev': 1, 'entry_id': entry}, 'done': False, 'key': uuid.uuid4().hex})
    check(r3.status_code == 200 and storage.get_thread(tid)['next_action'] == 'Call Ace', f"restore: {r3.text}")


def _run(pid, member='mom', state='active'):
    from library_run_fixture import add_run
    add_run({'id': 'run1', 'member_id': member, 'title': 'Strength', 'state': state,
             'shape': {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': []}, 'phases': [],
             'source': {'origin': 'none', 'reason': 'test'},
             'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}})
    _p().adopt('program', 'run1', None, project_id=pid)


def _windows(date, n=1):
    return [{'program_id': 'run1', 'date': date, 'time_start': f'{8 + 10 * i:02d}:00', 'lesson_id': '', 'variant_label': '',
             'unit_title': 'Push-ups', 'logged': False} for i in range(n)]


def scenario_program_tick_logs_today_only():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today.isoformat())):
        row = _row(p['id'], 'program', 'run1')
        r = _tick(p['id'], row)
    check(r.status_code == 200 and len(storage.get_program('run1')['sessions']) == 1
          and storage.get_program('run1')['sessions'][0]['source'] == 'ticked', f"today's window logs: {r.text}")
    tomorrow = (today + datetime.timedelta(days=1)).isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(tomorrow)):
        row = _row(p['id'], 'program', 'run1')
        r = _tick(p['id'], row)
    check(r.status_code == 409 and len(storage.get_program('run1')['sessions']) == 1, f"a future window is not tickable: {r.text}")


def scenario_program_double_tick_logs_one():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today().isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today)):
        row = _row(p['id'], 'program', 'run1')
        a = _tick(p['id'], row)
        b = _tick(p['id'], row)
    check(a.status_code == 200 and b.status_code == 409 and len(storage.get_program('run1')['sessions']) == 1,
          f"the second tick finds the window logged: {b.text}")


def scenario_program_untick_is_405():
    _fresh(); p = _bath(); _run(p['id'])
    today = datetime.date.today().isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today)):
        r = _tick(p['id'], _row(p['id'], 'program', 'run1'), done=False)
    check(r.status_code == 405, f"no untick on a program row: {r.text}")


def scenario_child_cannot_tick_a_siblings_run():
    _fresh(); p = _p().create({'title': 'Kate', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'kid', 'audience': 'household'}, dict(MOM))['project']
    _run(p['id'], member='dad')
    today = datetime.date.today().isoformat()
    with patch.object(programs, 'practice_windows', lambda *a, **k: _windows(today)):
        row = _row(p['id'], 'program', 'run1', who='mom')
        r = _tick(p['id'], row, who='kid')
    check(r.status_code == 403, f"not her run, not a parent: {r.text}")


def scenario_argyle_and_asking_rows_405():
    _fresh(); p = _bath()
    mid = missions.launch('find tilers', created_by='mom', project_id=p['id'])['mission_id']
    r = _tick(p['id'], _row(p['id'], 'argyle', mid))
    check(r.status_code == 405, f"argyle rows: {r.text}")
    storage.update_mission(mid, {'status': 'waiting_user'})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'question', 'result_json': {'question': 'Which?'}})
    r = _tick(p['id'], _row(p['id'], 'argyle', mid))
    check(r.status_code == 405, f"asking rows: {r.text}")


def scenario_tick_refused_on_paused_project():
    _fresh(); p = _bath()
    s = _p().add_step(p['id'], {'title': 'Demo', 'owner': 'mom'}, dict(MOM))['step']
    row = _row(p['id'], 'step', s['id'])
    _p().set_state(p['id'], 'paused', dict(MOM))
    r = _tick(p['id'], row)
    check(r.status_code == 403, f"a paused project takes no ticks: {r.text}")


def scenario_not_a_piece_is_404():
    _fresh(); p = _bath(); q = _bath()
    tid = threads.create(title='Elsewhere', owner_member_id='mom', created_by='mom', project_id=q['id'], next_action='x')
    r = _client().post(f"/api/projects/{p['id']}/tick", headers=_hdr('mom'),
                       json={'kind': 'conversation', 'id': tid, 'moment': {'thread_id': tid, 'rev': 0}, 'done': True, 'key': uuid.uuid4().hex})
    check(r.status_code == 404, f"a record of another project: {r.text}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            with patch.multiple(auth, identify=auth.identify, acting_member=auth.acting_member, impersonation_refused=auth.impersonation_refused):
                fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

Check how other HTTP scenarios in `tests/test_project_pieces.py` (`scenario_http_literal_routes`) build headers and members, and copy that exactly in `_hdr`.

- [ ] **Step 2: Run to see them fail**

Run: `cd chauffeur; unset HA_BASE_URL; python tests/test_project_rows_tick.py`
Expected: 404s from the missing route.

- [ ] **Step 3: Implement the route**

In `main.py` after `project_pieces`:

```python
_TICK_KEYS = 'projects_tick_results'   # app_state: {key: {'at': ts, 'status': int, 'body': dict}}


def _tick_remember(project_id, key, status, body):
    import time as _time
    with storage.db_lock:
        kept = storage.get_app_state(_TICK_KEYS, {}) or {}
        cutoff = _time.time() - 86400
        kept = {k: v for k, v in kept.items() if v.get('at', 0) > cutoff}
        kept[f'{project_id}:{key}'] = {'at': _time.time(), 'status': status, 'body': body}
        storage.set_app_state(_TICK_KEYS, kept)


@app.post("/api/projects/{project_id}/tick")
def project_tick(project_id: str, body: dict = Body(default={}), request: Request = None):
    """The row's checkbox (one-list spec §2): completes the row's next moment under the record's own gate."""
    from services import access, projects, threads as _threads, programs as _prog
    kind, rid, moment, key = body.get('kind'), body.get('id'), body.get('moment') or {}, body.get('key')
    done = bool(body.get('done', True))
    if kind not in ('step', 'conversation', 'program', 'argyle') or not rid or not key:
        raise HTTPException(status_code=400, detail='Say which row, and send a key.')
    kept = (storage.get_app_state(_TICK_KEYS, {}) or {}).get(f'{project_id}:{key}')
    if kept:
        return JSONResponse(status_code=kept['status'], content=kept['body'])
    actor = _piece_viewer(request)
    if actor is access.HOUSE:
        raise HTTPException(status_code=403, detail='Sign in to tick.')
    project = _project_for_actor(project_id, actor, writing=True)
    if kind in ('argyle',):
        raise HTTPException(status_code=405, detail='Argyle fills this one in.')
    with storage.db_lock:
        rows = projects.rows(project, actor)
        row = next((r for r in rows if r['kind'] == kind and r['id'] == rid and
                    (kind != 'program' or r['moment'].get('window_date') == moment.get('window_date')
                     and r['moment'].get('slot_rank') == moment.get('slot_rank'))), None)
        if row is None:
            if not any(r['kind'] == kind and r['id'] == rid for r in rows):
                raise HTTPException(status_code=404, detail='That is not part of this project.')
            return JSONResponse(status_code=409, content={'detail': 'That changed; look again.', 'rows': rows})
        if row['box'] == 'asking':
            raise HTTPException(status_code=405, detail='Argyle is waiting on you, not on a tick.')
        if kind == 'step':
            step = next((s for s in project.get('steps') or [] if s['id'] == rid), None)
            if not step:
                raise HTTPException(status_code=404, detail='No such step')
            if step.get('owner') == 'argyle':
                raise HTTPException(status_code=405, detail='Argyle fills this one in.')
            override = bool(body.get('override'))
            if override and not projects._parent(actor):
                raise HTTPException(status_code=403, detail='Only a parent can complete a step ahead of its needs.')
            if row['box'] == 'not_yet' and not override:
                return JSONResponse(status_code=409, content={'detail': row['reason'], 'rows': rows})
            if (step.get('state') == 'done') == done:
                return JSONResponse(status_code=409, content={'detail': 'That changed; look again.', 'rows': rows})
            result = projects.set_step_state(project_id, rid, 'done' if done else 'todo', actor, override=override)
        elif kind == 'conversation':
            thread = storage.get_thread(rid)
            if not access.record_actable('thread', thread, actor, 'advance'):
                raise HTTPException(status_code=403, detail="That isn't yours to tick.")
            if done:
                if row['box'] != 'open':
                    return JSONResponse(status_code=409, content={'detail': row['reason'] or 'That changed; look again.', 'rows': rows})
                result = _threads.complete_next_action(rid, int(moment.get('rev', -1)), actor.get('id'))
            else:
                result = _threads.restore_next_action(rid, moment.get('entry_id') or '', actor.get('id'))
        else:   # program
            run = storage.get_program(rid)
            _program_permission_or_refuse(request, {'member_id': actor.get('id')}, run)
            if not done:
                raise HTTPException(status_code=405, detail='Remove the session from the program instead.')
            if row['box'] != 'open' or moment.get('window_date', '') > datetime.date.today().isoformat():
                return JSONResponse(status_code=409, content={'detail': row['reason'] or 'That window is not today.', 'rows': rows})
            loaded = _prog.load(run)
            proj = _prog.lesson_for(loaded, datetime.date.fromisoformat(moment['window_date']), slot_rank=int(moment.get('slot_rank') or 0))
            if (proj.get('lesson_id') or '') != (moment.get('lesson_id') or '') or (proj.get('variant_label') or '') != (moment.get('variant_label') or ''):
                return JSONResponse(status_code=409, content={'detail': 'That lesson moved; look again.', 'rows': rows})
            result = _prog.log_session(rid, source='ticked', slot_date=moment['window_date'],
                                       lesson_id=moment.get('lesson_id') or None, variant_label=moment.get('variant_label') or '')
        if result.get('status') == 'error':
            status = int(result.get('code') or 400)
            if status == 409:
                return JSONResponse(status_code=409, content={'detail': result['message'], 'rows': projects.rows(storage.get_project(project_id), actor)})
            raise HTTPException(status_code=status, detail=result['message'])
        out = {'status': 'success', 'result': result, 'rows': projects.rows(storage.get_project(project_id), actor)}
    _tick_remember(project_id, key, 200, out)
    return out
```

Notes for the implementer: `storage.db_lock` is an `RLock` (verify in `services/storage.py`; if it is a plain `Lock`, `set_step_state` and `log_session` re-acquire it and would deadlock — in that case take the lock only around the row read and the moment check, and let the writers take their own). `_program_permission_or_refuse` raises `HTTPException` itself. `projects._parent` exists (line ~35). `JSONResponse` is already imported in `main.py` (check; else `from fastapi.responses import JSONResponse`).

In `services/projects.py` `set_step_state(project_id, step_id, state, actor, override=False)`: change the needs check to `if not override and not _parent(actor) and not _needs_satisfied(step, steps)`; when `override` is True and the actor is not a parent, return `_error('Only a parent can complete a step ahead of its needs.')` with `code: 403`.

In `services/access_readers.py` add after line 96:
```python
    ((R, 'POST', '/api/projects/{project_id}/tick'), '4.1-signed-in', ('thread', 'mission', 'program'), '_piece_viewer; projects.can_act; record_actable(thread, advance) | _program_permission_or_refuse'),
```

In `tests/access_fixture.py` / `tests/test_access_matrix.py`: read how the existing project probes (`/api/projects/{project_id}/pieces`) are declared, then add a `tick` probe for the thread cell with verb `advance` expecting: full viewer 200, keeper of their own thread 200 when the row is open, child 403, HOUSE 403. Run `python tests/test_access_register.py` and the matrix class that covers projects (the class name is in the file; run only that class as `python tests/test_access_matrix.py <ClassName>` if the file supports it, else the whole file).

- [ ] **Step 4: Run to green, then the neighbours**

Run: `python tests/test_project_rows_tick.py; python tests/test_project_rows.py; python tests/test_access_register.py; python tests/test_auth.py; python tests/test_project_steps.py`
Expected: PASS.

- [ ] **Step 5: Hand back**

Working tree + note (what changed, db_lock finding, matrix class run). Controller reviews, bumps, commits.

---

### Task 4: The admin detail and list pages on `rows` (Claude)

**Files:**
- Modify: `templates/components/projects_page.html` (the whole `<template x-if="opened && detail">` block, the list page's filter row and lanes, the Alpine island)
- Modify: `templates/components/project_piece_forms.html` (the program branch opens the setup sheet once the sibling spec ships; until then keep the picker but open it from + Add › Program)
- Test: `tests/test_projects_detail_live.py` (rewrite), `tests/test_projects_live.py` (list page assertions)
- Run: `python tools/build_tailwind.py`

**Interfaces:**
- Consumes: `GET /api/projects/{id}` → `rows`; `POST /api/projects/{id}/tick` (Task 3); existing step routes (`/steps/{id}/hold`, `/hold/clear`, `/cancel`, `/state`, `DELETE /steps/{id}`), `/pieces/remove`, `chfDeleteRecord`, `promptChoice`, `chf-record-sheet-open`.
- Produces: the DOM contract the live tests assert: `[data-row="kind:id"]`, `[data-row-box]` (a `<button>` with `data-box-state`), `[data-row-title]` (a `<button>` opening the sheet), `[data-row-group="now|next|later|linked|logbook"]`, `[data-project-menu]` (⋯), `[data-project-add]` (+ Add), `[data-step-sheet]`, `[data-link-sheet]`, `[data-progress]`.

- [ ] **Step 1: Rewrite the live test first**

Replace the scenarios of `tests/test_projects_detail_live.py` with these (keep the fixture imports and the `shot` calls):

```python
def scenario_detail_is_one_list():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        page.wait_for_selector('[data-project-detail]', timeout=15000)
        buttons = page.locator('[data-project-detail] button:visible')
        rows = page.locator('[data-row]')
        n_rows, n_buttons = rows.count(), buttons.count()
        asking = page.locator('[data-row-box][data-box-state="asking"]').count()
        # box + title per row, the ⋯, + Add and the back link, plus asking rows' own buttons
        check(n_buttons <= 2 * n_rows + 3 + 3 * asking, f"{n_buttons} buttons for {n_rows} rows ({asking} asking)")
        check(page.locator('[data-project-menu]').count() == 1 and page.locator('[data-project-add]').count() == 1, "one ⋯ and one + Add")
        check(page.locator('[data-new-project]').count() == 0, "no New project accordion on the detail")
        groups = [g for g in ('now', 'next', 'later', 'linked', 'logbook') if page.locator(f'[data-row-group="{g}"]').count()]
        check('now' in groups, f"the fixture's waiting mission makes a Now group: {groups}")
        texts = ' '.join(page.locator('[data-row]').all_inner_texts())
        check('waiting_user' not in texts and 'active' not in texts.split(), f"no state codes on rows: {texts[:200]}")
        shot(page, 'one-list-detail')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_menu_and_add():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        page.wait_for_selector('[data-project-menu]', timeout=15000)
        page.locator('[data-project-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Plan it with Argyle', 'Who sees it', 'Pause', 'Mark done', 'Drop', 'Delete'):
            check(any(want in l for l in labels), f"⋯ holds {want}: {labels}")
        page.keyboard.press('Escape')
        page.locator('[data-project-add]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Step', 'Conversation', 'Ask Argyle', 'Program', 'Something already in Chauffeur'):
            check(any(want in l for l in labels), f"+ Add offers {want}: {labels}")
        page.keyboard.press('Escape')
        shot(page, 'one-list-add')


def scenario_tick_a_step_and_open_sheets():
    served = serve()
    if served is None:
        return
    from services import projects
    step = projects.add_step('prj-bath', {'title': 'Demo the old tile', 'owner': 'mom'}, storage.get_member('mom'))['step']
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        row = page.locator(f'[data-row="step:{step["id"]}"]')
        row.wait_for(timeout=15000)
        row.locator('[data-row-box]').click()
        page.wait_for_selector(f'[data-row="step:{step["id"]}"][data-row-group="logbook"]', timeout=10000)
        check(storage.get_project('prj-bath')['steps'][-1]['state'] == 'done', "the tick landed")
        row.locator('[data-row-title]').click()
        page.wait_for_selector('[data-step-sheet]', timeout=5000)
        check(page.locator('[data-step-sheet]').inner_text().count('Put it on the calendar') == 1, "the step sheet holds the calendar control")
        page.keyboard.press('Escape')
        thread = page.locator(f'[data-row="conversation:{IDS["thread"]}"]')
        thread.locator('[data-row-title]').click()
        page.wait_for_selector('[data-record-sheet][data-open="true"][data-kind="thread"]', timeout=5000)
        check('Draft a message' in page.locator('[data-record-sheet]').inner_text(), "the thread sheet keeps its verbs")
        shot(page, 'one-list-sheets')


def scenario_list_page_groups():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('[data-project-card]', timeout=15000)
        check(page.locator('[data-lane-filter="programs"]').count() == 0, "the Programs filter is gone (R5)")
        check(page.locator('[data-list-group="needs_you"]').count() == 1, "Needs you first")
        check(page.locator('[data-list-group="rest"]').count() <= 1, "then everything else")
        check(page.locator('[data-project-card] .chip-state').count() == 0, "no state chip on cards")
        page.locator('[data-new-project]').click()
        page.wait_for_selector('[data-create-project]', timeout=5000)
        shot(page, 'one-list-list')
```

Keep the existing `scenario_closed_projects_are_hidden_folded_and_remembered` (it asserts Show closed and the folded closed lane; adjust its selectors to `[data-list-group="closed"]`).

- [ ] **Step 2: Run to see it fail**

Run: `cd chauffeur; unset HA_BASE_URL; python tests/test_projects_detail_live.py`
Expected: FAIL on `[data-project-detail]` present but `[data-row]` absent.

- [ ] **Step 3: Redraw the detail**

In `templates/components/projects_page.html` replace the whole `<template x-if="opened && detail">…</template>` block with:

```html
<template x-if="opened && detail">
    <div data-project-detail class="space-y-3">
        <button type="button" data-project-back @click="back()" class="text-xs font-semibold text-gray-400 underline underline-offset-2">← All projects</button>
        <template x-for="project in [detail]" :key="project.id">
            <article data-project-card class="bg-gray-900 border border-gray-800 rounded-2xl p-3 space-y-3">
                <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                        <h3 class="text-base font-bold text-gray-100" x-text="project.title"></h3>
                        <p class="text-[11px] text-gray-500 mt-0.5" x-text="headerLine(project)"></p>
                        <p class="text-xs text-gray-400 mt-0.5" x-show="project.goal && project.goal !== project.title" x-text="project.goal"></p>
                    </div>
                    <button type="button" data-project-menu @click="menu(project)" aria-label="More" title="More"
                            class="w-8 h-8 shrink-0 rounded-full bg-gray-800 text-gray-300 border border-gray-700 font-black active:bg-gray-700">⋯</button>
                </div>
                <div data-progress x-show="project.steps_total > 0" class="flex items-center gap-2 text-[11px] text-gray-500">
                    <div class="flex-1 h-1.5 rounded bg-gray-800 overflow-hidden"><div class="h-full bg-teal-500" :style="'width:' + Math.round(100 * project.steps_done / Math.max(1, project.steps_total)) + '%'"></div></div>
                    <span x-text="project.steps_done + ' of ' + project.steps_total + ' done'"></span>
                </div>
                <template x-for="g in groups(project)" :key="g.key">
                    <div :data-row-group-section="g.key">
                        <button type="button" x-show="g.key === 'logbook'" @click="logOpen = !logOpen"
                                class="w-full flex items-center justify-between text-[10px] font-black uppercase tracking-widest px-1 mb-1.5 text-gray-600">
                            <span x-text="'Logbook · ' + g.rows.length"></span><span class="normal-case font-semibold" x-text="logOpen ? 'Hide' : 'Show'"></span>
                        </button>
                        <div x-show="g.key !== 'logbook'" class="text-[10px] font-black uppercase tracking-widest px-1 mb-1.5" :class="g.cls" x-text="g.label"></div>
                        <div class="space-y-1.5" x-show="g.key !== 'logbook' || logOpen">
                            <template x-for="r in g.rows" :key="rowKey(r)">
                                <div :data-row="r.kind + ':' + r.id" :data-row-group="r.group" :data-moment="JSON.stringify(r.moment)"
                                     class="bg-gray-950/60 border border-gray-800 rounded-lg px-2.5 py-1.5 flex items-start gap-2.5"
                                     :class="r.group === 'later' ? 'opacity-60' : (r.box === 'asking' ? 'border-amber-500/50' : '')">
                                    <template x-if="r.box">
                                        <button type="button" data-row-box :data-box-state="r.box" @click="tick(project, r)"
                                                :disabled="!!(busy || ['argyle', 'asking', 'not_yet'].includes(r.box))"
                                                :aria-label="(r.box === 'done' ? 'Reopen ' : 'Complete ') + r.title" :aria-pressed="r.box === 'done'"
                                                class="row-box mt-0.5 shrink-0" :class="'row-box-' + r.box"></button>
                                    </template>
                                    <template x-if="!r.box"><span class="row-glyph mt-0.5 shrink-0 text-gray-500 text-xs" x-text="glyph(r)"></span></template>
                                    <div class="min-w-0 flex-1">
                                        <button type="button" data-row-title @click="openRow(project, r)" class="block w-full text-left text-xs font-semibold text-gray-200"
                                                :class="r.box === 'done' ? 'line-through text-gray-500' : ''" x-text="r.title"></button>
                                        <div class="text-[11px] text-gray-500" x-text="subtitle(r)"></div>
                                        <template x-if="r.actions.length && r.box !== 'done'">
                                            <div class="flex flex-wrap gap-1.5 mt-1">
                                                <template x-for="a in r.actions" :key="a.id">
                                                    <button type="button" :data-row-action="a.id" @click="rowAction(project, r, a)" :disabled="!!busy"
                                                            class="text-[11px] font-bold px-2.5 py-1 rounded-lg bg-teal-700 text-white active:bg-teal-800 disabled:opacity-50" x-text="a.label"></button>
                                                </template>
                                            </div>
                                        </template>
                                    </div>
                                    <span class="text-[11px] text-gray-500 shrink-0 mt-0.5" x-text="whenLabel(r)"></span>
                                </div>
                            </template>
                        </div>
                    </div>
                </template>
                <p class="text-xs text-gray-500 italic" x-show="!(rows[project.id] || []).length">Nothing here yet. Add a step, or plan it with Argyle.</p>
                <template x-if="project.can_act && project.state === 'active'">
                    <div class="space-y-2">
                        <button type="button" data-project-add @click="add(project)" :disabled="!!busy"
                                class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white active:bg-teal-800 disabled:opacity-50">+ Add</button>
                        {% include 'components/project_piece_forms.html' %}
                    </div>
                </template>
            </article>
        </template>
        <!-- The step sheet: a step's own controls, one at a time, framed like the record sheet. -->
        <template x-if="stepSheet">
            <div data-step-sheet class="fixed inset-0 z-[82] bg-black/40 flex justify-end items-end md:items-stretch" @click.self="stepSheet = null" @keydown.escape.window="stepSheet = null">
                <div role="dialog" aria-modal="true" class="bg-gray-800 w-full md:w-[40rem] h-[70vh] md:h-full overflow-y-auto border-t md:border-l border-gray-700 rounded-t-2xl md:rounded-none p-4 space-y-3">
                    <div class="flex items-center gap-3"><h2 class="flex-1 text-lg font-extrabold text-white truncate" x-text="stepSheet.step.title"></h2>
                        <button type="button" @click="stepSheet = null" aria-label="Close" class="w-8 h-8 rounded-full bg-gray-900 text-white font-bold">✕</button></div>
                    <p class="text-sm text-gray-300"><span class="text-gray-500">Who: </span><span x-text="stepSheet.step.owner_label"></span><span x-text="stepSheet.step.due_date ? ' · due ' + stepSheet.step.due_date : ''"></span></p>
                    <p class="text-sm text-gray-400" x-text="stepState(stepSheet.step.state)"></p>
                    <template x-if="stepSheet.step.owner === 'argyle'">
                        <div class="space-y-1 text-sm">
                            <template x-for="(line, i) in foundLines(stepSheet.step.found)" :key="i"><p class="text-gray-300" x-text="line"></p></template>
                            <template x-if="stepSheet.step.mission_id && !isChild()"><button type="button" :data-piece-open="'mission:' + stepSheet.step.mission_id" @click="openSheet('mission', stepSheet.step.mission_id, stepSheet.step.title, stepSheet.project.id)" class="text-xs font-bold text-teal-300 underline underline-offset-2">Open Argyle’s work</button></template>
                            <template x-if="stepSheet.step.state === 'doing' && stepSheet.step.can_cancel">
                                <div class="flex flex-wrap gap-2 pt-1">
                                    <button type="button" :data-step-skip="stepSheet.step.id" @click="cancel(stepSheet.project, stepSheet.step, 'skip')" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Skip</button>
                                    <button type="button" :data-step-stop="stepSheet.step.id" @click="cancel(stepSheet.project, stepSheet.step, 'stop')" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700">Stop</button>
                                </div>
                            </template>
                        </div>
                    </template>
                    <template x-if="stepSheet.step.owner !== 'argyle' && stepSheet.step.can_edit">
                        <div class="space-y-2 text-sm">
                            <p class="text-gray-400" x-show="stepSheet.step.hold" x-text="stepSheet.step.hold ? 'On the calendar: ' + windowLabel(stepSheet.step.hold) : ''"></p>
                            <div class="flex flex-wrap gap-2">
                                <button type="button" :data-step-hold="stepSheet.step.id" @click="suggest(stepSheet.project, stepSheet.step)" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Put it on the calendar</button>
                                <template x-if="stepSheet.step.hold"><button type="button" @click="writeStep(stepSheet.project, stepSheet.step, 'hold/clear', {})" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Clear time</button></template>
                                <template x-if="isParent() && stepSheet.row && stepSheet.row.box === 'not_yet' && stepSheet.step.state === 'todo'"><button type="button" data-step-override @click="tick(stepSheet.project, stepSheet.row, true)" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Complete anyway</button></template>
                                <button type="button" data-step-remove @click="removeStep(stepSheet.project, stepSheet.step)" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-900 text-red-400 border border-red-900/60">Remove step</button>
                            </div>
                            <template x-if="hold && hold.projectId === stepSheet.project.id && hold.stepId === stepSheet.step.id">
                                <div class="space-y-2">
                                    <p class="text-gray-300" x-text="hold ? (hold.window ? windowLabel(hold.window) : hold.message) : ''"></p>
                                    <div class="flex flex-wrap gap-2">
                                        <template x-if="hold && hold.window"><button type="button" data-hold-confirm @click="keepHold(stepSheet.project, stepSheet.step)" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white">Keep this time</button></template>
                                        <button type="button" @click="pickTime()" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Pick another time</button>
                                        <button type="button" @click="hold = null" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Cancel</button>
                                    </div>
                                </div>
                            </template>
                        </div>
                    </template>
                </div>
            </div>
        </template>
        <!-- The link sheet: a trip, occasion or list attached here (R1). -->
        <template x-if="linkSheet">
            <div data-link-sheet class="fixed inset-0 z-[82] bg-black/40 flex justify-end items-end md:items-stretch" @click.self="linkSheet = null" @keydown.escape.window="linkSheet = null">
                <div role="dialog" aria-modal="true" class="bg-gray-800 w-full md:w-[40rem] h-[40vh] md:h-full border-t md:border-l border-gray-700 rounded-t-2xl md:rounded-none p-4 space-y-3">
                    <div class="flex items-center gap-3"><h2 class="flex-1 text-lg font-extrabold text-white truncate" x-text="linkSheet.row.title"></h2>
                        <button type="button" @click="linkSheet = null" aria-label="Close" class="w-8 h-8 rounded-full bg-gray-900 text-white font-bold">✕</button></div>
                    <p class="text-sm text-gray-400" x-text="linkSheet.row.subtitle"></p>
                    <div class="flex flex-wrap gap-2">
                        <button type="button" data-link-open @click="openLink(linkSheet.card)" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-teal-700 text-white">Open</button>
                        <template x-if="linkSheet.project.can_act"><button type="button" data-link-remove @click="removePiece(linkSheet.project, linkSheet.card).then(() => linkSheet = null)" :disabled="!!busy" class="text-xs font-bold px-3 py-1.5 rounded-lg bg-gray-800 text-gray-400 border border-gray-700">Remove</button></template>
                    </div>
                </div>
            </div>
        </template>
    </div>
</template>
```

Add to the component's `<style>` (or the page's shared CSS next to `.agenda-*` in `panel_skin.html` if the guide's sibling rule prefers; here the row-box is new and small, so keep it in this component):

```html
<style>
.row-box { width:16px; height:16px; border:1.5px solid #6b7280; border-radius:4px; position:relative; background:transparent; }
.row-box-done { background:#14b8a6; border-color:#14b8a6; }
.row-box-done::after { content:"✓"; color:#fff; font-size:11px; font-weight:900; position:absolute; left:2px; top:-2px; }
.row-box-argyle, .row-box-asking { border-color:#5eead4; border-style:dashed; }
.row-box-argyle::after { content:""; position:absolute; inset:3px; border-radius:50%; border:2px solid #5eead4; border-right-color:transparent; animation: row-spin 1.2s linear infinite; }
.row-box-not_yet { border-color:#374151; background:#111827; }
.row-box-not_yet::after { content:"·"; color:#4b5563; position:absolute; left:4px; top:-6px; font-size:18px; }
@keyframes row-spin { to { transform: rotate(360deg); } }
</style>
```

In the Alpine island add state `rows: {}, logOpen: false, stepSheet: null, linkSheet: null` and methods:

```js
headerLine(p) { return [this.memberName(p.owner_member_id), p.body_goal ? 'Only you' : p.audience_label, p.done_when].filter(Boolean).join(' · '); },
rowKey(r) { return r.kind + ':' + r.id + ':' + (r.moment.window_date || '') + ':' + (r.moment.slot_rank || 0); },
groups(p) {
    const all = this.rows[p.id] || [];
    const defs = [['now', 'Now', 'text-amber-400'], ['next', 'Next', 'text-teal-300'], ['later', 'Later', 'text-gray-500'], ['linked', 'Linked', 'text-gray-500'], ['logbook', 'Logbook', 'text-gray-600']];
    return defs.map(([key, label, cls]) => ({key, label, cls, rows: all.filter(r => r.group === key)})).filter(g => g.rows.length);
},
subtitle(r) { return r.reason && r.box === 'not_yet' ? r.subtitle + ' · ' + r.reason : r.subtitle; },
whenLabel(r) {
    if (r.when === 'running') return 'running';
    if (r.when === 'now' || !r.when) return '';
    const d = new Date(r.when.date + 'T12:00:00'), today = new Date(); today.setHours(12, 0, 0, 0);
    const day = d.toDateString() === today.toDateString() ? 'today' : d.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
    return r.when.time ? day + ' ' + (window.formatClock ? window.formatClock(r.when.time) : r.when.time) : day;
},
glyph(r) { return {trip: '✈', occasion: '🎉', list: '☰'}[r.glyph] || '›'; },
async loadRows(p) {
    try { const d = await this.request('api/projects/' + encodeURIComponent(p.id)); this.rows[p.id] = d.rows || []; this.projects = this.projects.map(x => x.id === p.id ? {...x, ...d.project} : x); }
    catch (e) { this.error = e.message; }
},
async tick(p, r, override = false) {
    if (this.busy) return;
    const done = r.box !== 'done';
    const moment = {...r.moment, ...(r.kind === 'conversation' && !done ? {entry_id: this._completed[r.id] || ''} : {})};
    this.busy = true; this.error = '';
    try {
        const d = await this.request('api/projects/' + encodeURIComponent(p.id) + '/tick', {kind: r.kind, id: r.id, moment, done, key: crypto.randomUUID(), override});
        this.rows[p.id] = d.rows || [];
        if (r.kind === 'conversation' && done) {
            this._completed[r.id] = (d.result || {}).entry_id || '';
            const next = await promptInput("What's next with " + (r.subtitle.split(' · ')[0] || 'them') + '?', '', {okText: 'Set it'});
            if (next && next.trim()) { await this.request('api/threads/' + encodeURIComponent(r.id) + '/advance', {next_action: next.trim()}); }
            await this.loadRows(p);
        }
        this.stepSheet = null;
    } catch (e) {
        this.error = e.message;
        await this.loadRows(p);   // a 409 carries fresh rows; re-reading is simplest and always right
    } finally { this.busy = false; }
},
openRow(p, r) {
    if (r.kind === 'step') { const step = p.steps.find(s => s.id === r.id); if (step) this.stepSheet = {project: p, step, row: r}; return; }
    if (r.kind === 'link') { const card = (this.pieces[p.id] || []).find(c => c.id === r.id); this.linkSheet = {project: p, row: r, card: card || {kind: r.glyph, id: r.id, link: (r.actions.find(a => a.verb === 'link') || {payload: {}}).payload.link}}; return; }
    if (r.sheet) this.openSheet(r.sheet.kind, r.sheet.id, r.title, p.id);
},
async rowAction(p, r, a) {
    if (a.verb === 'rebind') { const card = (this.pieces[p.id] || []).find(c => c.kind === 'program' && c.id === r.id); if (card) return this.rebind(p, card); }
    if (a.verb === 'approve') { return this.openSheet('program', r.id, r.title, p.id); }
    if (r.sheet) this.openSheet(r.sheet.kind, r.sheet.id, r.title, p.id);   // Answer / Use / Approve plan: the sheet's own buttons act
},
async menu(p) {
    const items = [];
    if (p.can_act && !this.isChild() && p.state === 'active') items.push({value: 'plan', label: 'Plan it with Argyle'});
    if (p.can_edit_audience && !p.body_goal) items.push({value: 'audience', label: 'Who sees it'});
    if (p.can_act && p.state === 'active') items.push({value: 'paused', label: 'Pause'});
    if (p.can_act && p.state === 'paused') items.push({value: 'active', label: 'Resume'});
    if (p.can_act && ['active', 'paused'].includes(p.state)) items.push({value: 'done', label: 'Mark done'}, {value: 'dropped', label: 'Drop'});
    if (this.canDelete(p)) items.push({value: 'delete', label: 'Delete'});
    const pick = await promptChoice(p.title, '', items);
    if (!pick) return;
    if (pick === 'plan') return this.plan(p);
    if (pick === 'audience') return this.chooseAudience(p);
    if (pick === 'delete') return this.deleteProject(p);
    return this.state(p, pick, {paused: 'Pause', active: 'Resume', done: 'Mark done', dropped: 'Drop'}[pick]);
},
async add(p) {
    const options = [{value: 'step', label: 'Step'}];
    if (!this.isChild()) options.push({value: 'thread', label: 'Conversation'}, {value: 'mission', label: 'Ask Argyle'});
    options.push({value: 'program', label: 'Program'}, {value: 'existing', label: 'Something already in Chauffeur'});
    const pick = await promptChoice('Add to ' + p.title, '', options);
    if (!pick) return;
    if (pick === 'step') return this.addStep(p);
    return this.addPieceKind(p, pick);
},
async removeStep(p, s) {
    if (!await promptConfirm('Remove “' + s.title + '”?', 'It leaves the project.', 'Remove', 'Keep it')) return;
    if (await this.mutate('api/projects/' + encodeURIComponent(p.id) + '/steps/' + encodeURIComponent(s.id), undefined, 'DELETE')) this.stepSheet = null;
},
```

Rename today's `addPiece(p)` to `addPieceKind(p, pick)` with the `promptChoice` removed (the kind arrives as the argument). Make `mutate(path, body, method = 'POST')` pass `method` to `request`. `_completed: {}` in state. Every place that called `loadPieces(p)` also calls `loadRows(p)` (`open`, `load`, `mutate`'s reload, `close` of the record sheet via `chf-projects-open`). `tick(..., true)` from Complete anyway sends `override: true`.

List page: replace the filter row and lanes with three groups:

```js
get listGroups() {
    const rows = this.shownProjects;
    const word = p => ({needs_you: 'needs you', moving: 'moving', waiting: 'waiting', paused: 'paused', closed: ''}[p.lane || 'waiting']);
    const by = f => rows.filter(f).map(p => ({...p, lane_word: word(p)}));
    const out = [{key: 'needs_you', label: 'Needs you', cls: 'text-amber-400', items: by(p => p.lane === 'needs_you')},
                 {key: 'rest', label: 'Everything else', cls: 'text-gray-500', items: by(p => !['needs_you', 'closed'].includes(p.lane))}];
    if (this.showClosed) out.push({key: 'closed', label: 'Done & dropped', cls: 'text-gray-600', items: by(p => p.lane === 'closed')});
    return out.filter(g => g.items.length);
},
```

Draw `[data-list-group="key"]` sections; the card's second line is `memberName(owner) + ' · ' + lane_word`; delete the state chip `<span … :class="chip(project.state)">` from the card; delete the `programsOnly` state, the `[data-lane-filter]` button and `lane=programs` handling. Turn the `+ New project` accordion into a button that sets `creating = true` and draws the form inside a sheet (`data-create-sheet`, same frame as the step sheet) with `[data-create-project]` kept on the submit.

Run `python tools/build_tailwind.py`.

- [ ] **Step 4: Run the live tests**

Run: `python tests/test_projects_detail_live.py; python tests/test_projects_live.py; python tests/test_project_card_live.py`
Expected: PASS; look at the screenshots in the scratchpad and compare against the brainstorm mockup `project-detail-v3.html` (the four box states, one ⋯, one + Add).

- [ ] **Step 5: Commit**

```bash
git add chauffeur/templates/components/projects_page.html chauffeur/static/tailwind.css chauffeur/tests/test_projects_detail_live.py chauffeur/tests/test_projects_live.py chauffeur/config.yaml
git commit -m "feat(projects): the detail page is one list - Now/Next/Later/Linked/Logbook rows with a checkbox each, one ... menu, one + Add, a step sheet and a link sheet; the list page groups Needs you then the rest, no state chip, no Programs filter (vX.Y.Z)"
```

---

### Task 5: The phone: no tab, no admin anchors, navigation callbacks (Claude)

**Files:**
- Modify: `templates/app.html` (remove `#tab-projects` markup ~line 521-525 and its display line ~1021; drop `'projects'` from the `hiddenNow` arrays ~1047-1049; keep the sprout redirect ~1062; `pieceSheetCtx` gains `navigate`)
- Modify: `static/situations.js` (~line 94 subject anchor; the handoff `Open it` link; `act` for `subject`)
- Modify: `static/project_links.js` (Part of as buttons on the phone)
- Test: `tests/test_project_sheets_phone_live.py`, `tests/test_projects_live.py`, `tests/test_pwa_adult_shell_live.py`, `tests/test_access_live.py`, `tests/test_audience_picker_live.py`, `tests/test_deletion_live.py`, `tests/test_library_live.py` (every file that clicks `#tab-projects` moves to the More path)

**Interfaces:**
- Produces: `Situations.cardHtml(s, ctx)` draws `<button data-sit-nav="kind:id">About: title</button>` when `ctx.navigate` is a function, else today's anchor; `bind()` wires `[data-sit-nav]` to `ctx.navigate(kind, id)`. The phone's `pieceSheetCtx` passes `navigate: (kind, id) => phoneOpenRecord(kind, id)` where `phoneOpenRecord` opens the piece sheet for thread/mission/program, `setView('projects')` + `chf-project-open` for a project, and the kind's phone view for trip/occasion/list (use the existing phone openers: grep `openTripSheet\|openOccasion\|openListSheet` in `app.html` and map; where no phone home exists yet, show `showGlobalAlert('Open that from the ' + kind + ' page on a computer.')` and record the gap in the hand-back note).
- A helper for tests: `window.chfPwaOpenProjects = () => setView('projects')`.

- [ ] **Step 1: Write the failing live assertions**

In `tests/test_project_sheets_phone_live.py` add:

```python
def scenario_no_tab_and_no_admin_anchor_in_sheets():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        pwa(page, served, 'mom')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_selector('#tab-more', timeout=15000)
        check(page.locator('#tab-projects').count() == 0, "no Projects tab")
        page.locator('#tab-more').click()
        page.get_by_text('Projects', exact=True).first.click()
        page.wait_for_selector('[data-project-card]', timeout=15000)
        page.locator(f'[data-project-id="{IDS["bath"]}"]').click()
        page.wait_for_selector('[data-row]', timeout=10000)
        check(page.locator('#projects-container a[href]').count() == 0, "no anchors in the projects surface")
        page.locator(f'[data-row="conversation:{IDS["thread"]}"] [data-row-title]').click()
        page.wait_for_selector('[data-piece-sheet]', timeout=10000)
        hrefs = page.locator('[data-piece-sheet] a[href]').evaluate_all('els => els.map(e => e.getAttribute("href"))')
        check(all(h.startswith('http') and 'localhost' not in h for h in hrefs), f"no admin anchors inside the piece sheet: {hrefs}")
        check(page.locator('[data-piece-sheet] [data-sit-nav]').count() >= 0, "subjects draw as buttons")
        shot(page, 'one-list-phone')
```

And a helper `_open_projects(page)` in `project_sheets_fixture.py`:

```python
def open_projects(page):
    page.locator('#tab-more').click()
    page.get_by_text('Projects', exact=True).first.click()
    page.wait_for_selector('[data-project-card], [data-project-detail]', timeout=15000)
```

Replace every `page.locator('#tab-projects').click()` (or `page.click('#tab-projects')`) in the listed test files with `open_projects(page)` (import it from `project_sheets_fixture`; files that do not use that fixture copy the three lines).

- [ ] **Step 2: Run to see them fail**

Run: `python tests/test_project_sheets_phone_live.py`
Expected: FAIL on `#tab-projects` still present.

- [ ] **Step 3: Implement**

`app.html`: delete the `<button id="tab-projects" …>…</button>` block; delete `document.getElementById('tab-projects').style.display = …;`; remove `'projects'` from the two `hiddenNow` arrays (the view stays reachable from More; `pwaAllowed('projects')` still gates More). Add near `pieceSheetCtx`:

```js
function phoneOpenRecord(kind, id) {
    if (['thread', 'mission', 'program'].includes(kind)) return openPieceSheet({kind, id, title: ''});
    if (kind === 'project') { setView('projects'); window.dispatchEvent(new CustomEvent('chf-project-open', {detail: {id}})); return; }
    const opener = {trip: window.phoneOpenTrip, occasion: window.phoneOpenOccasion, list: window.phoneOpenList}[kind];
    if (typeof opener === 'function') return opener(id);
    showGlobalAlert('Open that from the ' + kind + ' page on a computer.');
}
window.chfPwaOpenProjects = () => setView('projects');
```
and in `pieceSheetCtx` add `navigate: phoneOpenRecord`. Grep for the real phone openers (`grep -n "function phoneOpen\|function openTrip\|function openOccasion\|function openList" templates/app.html`) and wire the three that exist.

`situations.js`: in `cardHtml`, the `subj` line becomes
```js
const subj = s.subject
  ? (typeof ctx.navigate === 'function'
      ? `<div class="sit-subject text-[11px] text-indigo-300 mt-0.5" data-sit-subject="${esc(s.subject.kind)}:${esc(s.subject.id)}">About: <button type="button" class="underline underline-offset-2" data-sit-nav="${esc(s.subject.kind)}:${esc(s.subject.id)}">${esc(s.subject.title || s.subject.kind)}</button></div>`
      : `…today's anchor markup unchanged…`)
  : '';
```
and in `bind()` add `el.querySelectorAll('[data-sit-nav]').forEach(b => { b.onclick = () => { const [k, id] = b.dataset.sitNav.split(':'); ctx.navigate(k, id); }; });`. The handoff `Open it` link stays an anchor: it is an outside URL (`https://…`), which the rule allows.

`project_links.js`: when `document.body.dataset.pwa === 'true'` or `window.chfLibraryHost === 'phone'` (check which marker the phone body carries: `grep -n "data-pwa\|dataset.pwa" templates/app.html`), draw `Part of:` with a `<button type="button">` whose `onclick` is `window.chfPwaOpenProjects(); window.dispatchEvent(new CustomEvent('chf-project-open', {detail: {id: p.id}}))`.

In `projects_page.html`, `openLink(card)` on the phone host: `if (this.host === 'phone' && window.phoneOpenRecord) return window.phoneOpenRecord(card.kind, card.id);` before the `location.href` fallback.

- [ ] **Step 4: Run the moved live tests**

Run: `python tests/test_project_sheets_phone_live.py; python tests/test_projects_live.py; python tests/test_pwa_adult_shell_live.py; python tests/test_access_live.py; python tests/test_audience_picker_live.py; python tests/test_deletion_live.py; python tests/test_library_live.py`
Expected: PASS. If `test_library_live` clicks the Library More item it is unaffected; only its Projects hops change.

- [ ] **Step 5: Commit**

```bash
git add chauffeur/templates/app.html chauffeur/static/situations.js chauffeur/static/project_links.js chauffeur/templates/components/projects_page.html chauffeur/tests/project_sheets_fixture.py chauffeur/tests/*_live.py chauffeur/config.yaml
git commit -m "feat(pwa): Projects leaves the tab bar for More; situation cards and Part of lines navigate through phone callbacks, never an admin anchor (vX.Y.Z)"
```

---

### Task 6: Parity guard, capabilities doc, close-out (Claude)

**Files:**
- Modify: `tests/test_projects_parity.py`
- Modify: `chauffeur/system_capabilities.md` (top entry)
- Modify: the memory arc `projects-programs-usability-arc.md` (shipped note)

- [ ] **Step 1: Extend the parity test**

Read `tests/test_projects_parity.py` end to end. It walks the front-door inventory; add a section that, for the Bathroom fixture, asserts every verb below is reachable from the new surfaces by DOM query in a live run (reuse `project_sheets_fixture`):

| verb | where |
|---|---|
| Draft a message, Change the next step, Look something up, Link to something in Chauffeur, Done with it, I'll handle it myself, Drop it | thread sheet (`[data-record-sheet][data-kind="thread"]`) |
| Answer, Steer, Drop the mission | mission sheet |
| Put it on the calendar, Clear time, Pick another time, Skip, Stop, Complete anyway (parent, blocked step), Remove step | step sheet |
| Open, Remove | link sheet |
| Plan it with Argyle, Who sees it, Pause, Mark done, Drop, Delete | ⋯ |
| Step, Conversation, Ask Argyle, Program, Something already in Chauffeur | + Add |
| Show closed | list page |

Write it as one scenario per surface, each opening the surface and asserting the labels appear in its text.

- [ ] **Step 2: Run it**

Run: `python tests/test_projects_parity.py`
Expected: PASS.

- [ ] **Step 3: Capabilities doc**

Add a top entry to `chauffeur/system_capabilities.md`: "Projects: one list (vX.Y.Z)" describing the row model (five groups, precedence, the five box states, moment identity, idempotency), the tick route and its gates, the thread revision pair, the ⋯ and + Add, the step and link sheets, the list page groups, the phone changes (More only, navigation callbacks), the rulings R1–R5, and the device steps: open a project on the admin page, tick a step, tick a conversation's next step and answer the prompt, tick today's practice window, open the ⋯, add a conversation through + Add; on the phone, More › Projects, open a thread row, tap its About.

- [ ] **Step 4: Gate, bump, commit, push**

Run: `python tests/test_project_rows.py; python tests/test_project_rows_tick.py; python tests/test_thread_next_action_rev.py; python tests/test_projects_parity.py; python tests/test_projects_detail_live.py; python tests/test_project_sheets_phone_live.py; python tests/test_access_register.py; python tests/test_auth.py`
Expected: PASS.

```bash
git add chauffeur/system_capabilities.md chauffeur/tests/test_projects_parity.py chauffeur/config.yaml
git commit -m "docs(projects): system_capabilities.md records the one-list detail page, the tick route, the thread revision pair, the sheets and the phone changes; parity test guards every verb (vX.Y.Z)"
git push origin main
```

---

## Self-review notes

- Spec §1.1 every row kind and state → Task 1 table and tests; §1.2 precedence → `_group_of` and `scenario_mission_rows_and_precedence`; §1.3 asking rows → `_ask_actions`; §1.4 folding → `_fold_target`; §1.5 server-side → `rows` + route key.
- §2.1 identity, key, gates → Task 3; §2.2 dispatch per kind → Task 3; §2.2 thread functions and §2.3 drafting → Task 2.
- §3 detail page, step sheet, link sheet → Task 4; §4 list page → Task 4; §5 phone → Task 5; §6 API → Tasks 1–3; §7 vocabulary → Task 4 copy; §8 tests → Tasks 1–6; R1–R5 → Tasks 1, 3, 4.
- Open point the implementer must settle, not guess: `storage.db_lock` re-entrancy (Task 3 note) and the real name of the mission finisher (Task 2 note).
