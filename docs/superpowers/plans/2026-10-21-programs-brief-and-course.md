# Programs: brief, course page, one-pass setup, monitoring sheet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A library program is made from a plain-language brief and steered in words; its page reads as a course; adding it to a project is one pass that lands active; the admin run sheet is monitoring; the run's days change in one write.

**Architecture:** Two halves, each shippable on its own. **Runs** (Tasks 1–4): a transactional `programs.replace_schedule`, an activation contract on `POST /api/programs`, `programs.monitor` + `remove_session`, then the setup sheet and the monitoring sheet on top. **Library** (Tasks 5–8): a `revision` on library rows and one commit path, a steer endpoint that builds one validated candidate curriculum, a brief parser feeding the curator, then the course page and the DM card. Task 9 closes out (parity guard, docs). Every write stays behind the existing hand endpoints' rules; the model only proposes.

**Tech Stack:** FastAPI + the project's storage layer (`services/storage.py`), the model pools (`model_pools.call_pool_json`, free chain only for unattended work), Jinja + vendored Alpine, precompiled Tailwind, plain-script tests from `chauffeur/`, Playwright live tests through `tests/live_app.py`.

**Spec:** `docs/superpowers/specs/2026-10-20-programs-brief-and-course-design.md` (rev 2). Rulings P1–P8 at its top are decided. Read it first; section numbers below refer to it.

## Global Constraints

- Tests run from `chauffeur/` as plain scripts with `HA_BASE_URL` unset (`cd chauffeur; unset HA_BASE_URL; python tests/test_x.py`). Never the whole suite; each task names its gate.
- Locked rules: a person judges a milestone, on ANY unjudged phase (`mark_milestone` already allows it); no completion fraction on a program (never "3 of 12"; "2 sessions this week" is a count); curate over generate with the tier on the face (`source.origin` cited | generated | none); the unattended writing job never reaches the paid key (`call_pool_json(..., paid_ok=False)`); a hand-edited script is never overwritten without its own warning; a child never creates a library row; stable lesson ids; v2.499.630: Done stays today-or-earlier, Start may run a future window with `slot_date`.
- Every new route gets a `services/auth.py` rule (the `/api/library/*` and `/api/programs/*` SIGNED_IN rules cover the paths below; confirm with `python tests/test_auth.py`) and a `services/access_readers.READERS` row (`python tests/test_access_register.py`). Every new reader helper is classified INTERNAL there.
- `storage.update_library_program` allow-lists fields (`title, made_for, source, phases, lessons, archived`); any new library field (`revision`) must be added to that set and to `models/schemas.LibraryProgram`. `storage._check_program_keys` bans streak/percent-style keys on every program and library write; never add such a key.
- No browser dialogs (`showGlobalAlert`, `promptConfirm`, `promptInput`, `promptChoice`). Vendored Alpine `:disabled="!!(...)"`. `python tools/build_tailwind.py` after template class changes; commit the sheet.
- Nothing a person can do today is removed: the inventory is today's run sheet (Log a session, Pause/Resume, Finished, Re-shape the week, Drop, Delete, Reached it per phase, Another session on this / Move on, Open the lesson, Edit (starting point, minutes, sessions, days, target), Look again, Plan without the book, Dismiss, Not these times?, Approve), the library page (New program, Edit/Open, Write lessons, Archive, Delete, per lesson ▲▼ Edit Remove, Add lesson, per script Play/Edit/Regenerate/Reset) and the phone Today card (unchanged). Each lands in a sheet, ⋯ or the course page.
- Codex-built tasks leave their changes uncommitted with a note; the controller reviews, bumps `chauffeur/config.yaml` and commits. Claude-built tasks bump and commit (`(vX.Y.Z)` in the subject, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`).
- Copy: the vocabulary table in spec §8 is binding (no "run", "claim", "footprint", "Re-shape", "ready to judge", "rotation/variant" on screens; "Done with it", "Change the days", "Start the program", "What it adds to the week", "Needs a program", "Practice time only · {reason}").

## Review Focus

1. **A run with a library program whose lessons are all judged but the run never finished** (every phase milestone hit by an older path): `monitor` must still render a ladder and `replace_schedule` must still work. Pinned in Task 3 (`scenario_monitor_all_judged`).
2. **Change the days while the week's commitments were already partly deleted by hand** (orphaned emissions): the snapshot restore must not re-create ghosts. Pinned in Task 1 (`scenario_replace_with_orphaned_emissions`).
3. **A brief in a language other than English or with no title words at all** ("something for Kate on Tuesdays"): the parser must return a refusal the form shows, never a program titled "something". Pinned in Task 7 (`scenario_brief_without_an_aim`).
4. **A steer whose plan removes every lesson of a phase and adds none**: the candidate must be refused as a whole, nothing written. Pinned in Task 6 (`scenario_steer_empties_a_phase`).
5. **Two people steer the same program at once**: the second must get 409 on `revision`, never a merged half-plan. Pinned in Task 6 (`scenario_concurrent_steers`).

---

## File structure

- `services/programs.py` — add `replace_schedule`, `monitor`, `remove_session`; `weekday_shortfall` / `maybe_rebaseline` read `baseline.schedule_changed_on`.
- `services/watchers.py` ~635-645 — the drift finding's action becomes `change_program_days`; `services/chat_actions.py` ~318 — both action types execute nothing (open-the-editor offers).
- `main.py` — `POST /api/programs` gains `activate`; new `POST /api/programs/preview-slots`, `PATCH /api/programs/{id}/schedule`, `GET /api/programs/{id}/monitor`, `DELETE /api/programs/{id}/sessions/{session_id}`, `POST /api/library/{id}/steer`; `/api/programs/{id}/reshape` route removed; the `/edit` route accepts `minutes`, `starting_point`, `target_date` on an active or paused run (Program settings, P4).
- `services/migrations.py` — `migrate_program_sessions_ids_v2499` (session `id`s), `migrate_library_revision_summary_v2499` (`revision`, `lessons[].summary`, `lessons[].origin`).
- `services/library.py` — `revision`; `_commit(library_id, candidate, actor)` as the one writer; `add_lesson(after=)`, `update_phase`; whitelists carry `summary`, `origin`; `_write` refuses archived rows; `runners` carries `run_id` for visible runs.
- `services/library_steer.py` (new) — plan → candidate → screens → provenance → commit → change list.
- `services/library_scripts.py` — claims carry `revision`; `_run` reloads each lesson; `stale` on hand-edited scripts a steer touched.
- `services/program_brief.py` (new) — `parse`; `services/programs_curate.py` — `public_context`, `based_on` in the research question, `brief` argument.
- `services/agent_tools_v2.py` `propose_program` — takes `brief`, persists it on the choice; the DM course card.
- `templates/components/program_setup_sheet.html` (new), `templates/components/programs_page.html` (sheet mode redrawn; dead form deleted), `templates/components/project_piece_forms.html` (program branch → the setup sheet), `templates/components/library_page.html` + `library_card.html` (course page, brief box, Steer), `templates/components/projects_page.html` (`addPieceKind('program')` opens the sheet).
- Tests (new): `tests/test_program_schedule.py`, `tests/test_program_setup.py`, `tests/test_program_monitor.py`, `tests/test_library_steer.py`, `tests/test_program_brief.py`; extended: `tests/test_library_model.py`, `tests/test_library_live.py`, `tests/test_programs_endpoints.py`, `tests/test_library_flows.py`, `tests/test_library_argyle.py`, `tests/test_programs_reachable.py`, `tests/test_projects_detail_live.py`.

---

## Half A — runs

### Task 1: `programs.replace_schedule` and the retired reshape (Codex)

**Files:**
- Modify: `services/programs.py` (after `reshape`, ~line 790; `weekday_shortfall` ~1495; `maybe_rebaseline` ~1627)
- Modify: `services/watchers.py:635-645`, `services/chat_actions.py:102,126,318`, `main.py:8949-8962` (reshape route) and a new `PATCH /api/programs/{program_id}/schedule`
- Modify: `services/access_readers.py` (READERS row for the PATCH, INTERNAL for the helper)
- Test: `tests/test_program_schedule.py` (new)

**Interfaces:**
- Consumes: `release_commitments(program_id, commitment_ids=None)` (raises RuntimeError on partial failure, keeps failed ids on the row), `_emit_commitments(program_id, row, slots, emissions, made)`, `sanitize_slots(slots, minutes)`, `propose_slots(member_id, shape)`, `emitted_slots(row)`, `storage.claim_program(id, from_state, to_state)`, `storage.add_protected_commitment`, `storage.get_protected_commitments(member_id=, include_inactive=)`, `_program_permission_or_refuse(request, body, row)`, `_approver_of_record`.
- Produces: `programs.replace_schedule(program_id, slots, actor) -> dict` with `{'status': 'success', 'schedule_dirty': bool, 'state': 'active'|'paused'|'proposed', 'slots': [...], 'message': str}` or `{'status': 'error', 'code'?: int, 'message': str}`; `baseline.schedule_changed_on` (ISO date) and `baseline.schedule_history: [{'until': ISO date, 'preferred_days': [...]}]` on the run; the chat action `change_program_days` whose execution returns `{'status': 'success', 'open': {'kind': 'program', 'id': program_id, 'menu': 'change_days'}}` and writes nothing; `PATCH /api/programs/{program_id}/schedule` body `{slots: [{day, time_start}], member_id?}` → `_program_refresh(result)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_program_schedule.py`:

```python
"""programs.replace_schedule: Change the days on an active or paused run in one write;
a child's change goes through proposed; drift reads the change date; the old
reshape offer executes nothing (spec 2026-10-20-programs-brief-and-course §5.3, P8).
Run from chauffeur/: python tests/test_program_schedule.py"""
import datetime
from unittest.mock import patch

from program_fixture import add_run, loaded  # harness first
from harness import check  # noqa: F401
from services import storage, programs

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}
SHAPE = {'sessions_per_week': 2, 'minutes': 20, 'preferred_days': [0, 2]}
BASE = {'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'm',
                    'units': [{'title': 'Scales', 'sessions': 2}]}],
        'source': {'origin': 'none', 'reason': 'test'},
        'baseline': {'start_date': '2026-10-01', 'target_date': None, 'target_event_id': None,
                     'rebaselined_at': None, 'rebaselines': 0}}


def _reset():
    for t in (storage.programs_table, storage.library_programs_table, storage.members_table, storage.protected_commitments_table):
        t.truncate()
    for m in (MOM, AUNT, KID):
        storage.add_member(dict(m))


def _active(member='kid'):
    rid = add_run({'id': 'r1', 'member_id': member, 'title': 'Piano', 'state': 'proposed', 'shape': dict(SHAPE), **BASE})
    res = programs.approve(rid, 'mom', slots=[{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}])
    check(res['status'] == 'success', f"fixture approves: {res}")
    return rid


def _commitments(rid):
    ids = set((storage.get_program(rid).get('emissions') or {}).get('commitment_ids') or [])
    return [pc for pc in storage.get_protected_commitments(member_id=storage.get_program(rid)['member_id']) if pc['id'] in ids]


def scenario_active_replace_claims_new_days():
    _reset(); rid = _active()
    before = {pc['id'] for pc in _commitments(rid)}
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:30'}, {'day': 3, 'time_start': '17:30'}, {'day': 5, 'time_start': '09:00'}], dict(MOM))
    row = storage.get_program(rid)
    now = _commitments(rid)
    check(res['status'] == 'success' and res['state'] == 'active' and res['schedule_dirty'], f"replaced: {res}")
    check({pc['days_of_week'][0] for pc in now} == {1, 3, 5} and not (before & {pc['id'] for pc in now}), "old windows gone, new ones claimed")
    check(row['shape']['slots'] and row['shape']['sessions_per_week'] == 3 and row['shape']['preferred_days'] == [1, 3, 5], f"shape follows the slots: {row['shape']}")
    check(row['baseline']['schedule_changed_on'] == datetime.date.today().isoformat()
          and row['baseline']['schedule_history'][-1]['preferred_days'] == [0, 2], f"the change is dated and the old days kept: {row['baseline']}")


def scenario_empty_slots_let_the_app_pick():
    _reset(); rid = _active()
    res = programs.replace_schedule(rid, [], dict(MOM))
    check(res['status'] == 'success' and len(_commitments(rid)) == 2, f"the app proposed and claimed: {res}")


def scenario_claim_failure_restores_the_old_week():
    _reset(); rid = _active()
    before = sorted(pc['days_of_week'][0] for pc in _commitments(rid))
    calls = {'n': 0}
    real = storage.add_protected_commitment
    def flaky(data):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('disk full')
        return real(data)
    with patch.object(storage, 'add_protected_commitment', flaky):
        res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:30'}, {'day': 3, 'time_start': '17:30'}], dict(MOM))
    after = sorted(pc['days_of_week'][0] for pc in _commitments(rid))
    row = storage.get_program(rid)
    check(res['status'] == 'error' and after == before and row['state'] == 'active' and row['shape']['preferred_days'] == [0, 2],
          f"nothing changed on failure: {res} {after}")


def scenario_replace_with_orphaned_emissions():
    _reset(); rid = _active()
    gone = _commitments(rid)[0]['id']
    storage.delete_protected_commitment(gone)   # someone removed one window by hand
    res = programs.replace_schedule(rid, [{'day': 4, 'time_start': '18:00'}], dict(MOM))
    ids = (storage.get_program(rid).get('emissions') or {}).get('commitment_ids') or []
    check(res['status'] == 'success' and len(ids) == 1 and storage.get_protected_commitment(gone) is None,
          f"an orphan is forgotten, never re-created: {res} {ids}")


def scenario_paused_run_remembers_only():
    _reset(); rid = _active()
    programs.pause(rid)
    res = programs.replace_schedule(rid, [{'day': 6, 'time_start': '10:00'}], dict(MOM))
    row = storage.get_program(rid)
    check(res['status'] == 'success' and res['state'] == 'paused' and not _commitments(rid)
          and row['paused_slots'][0]['day'] == 6 and row['shape']['preferred_days'] == [6], f"paused: remembered, not claimed: {row['paused_slots']}")
    res = programs.resume(rid)
    check(res['status'] == 'success' and {pc['days_of_week'][0] for pc in _commitments(rid)} == {6}, "resume claims the remembered days")


def scenario_child_change_goes_through_proposed():
    _reset(); rid = _active()
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '16:00'}], dict(KID))
    row = storage.get_program(rid)
    check(res['status'] == 'success' and res['state'] == 'proposed' and row['state'] == 'proposed'
          and not _commitments(rid) and row['shape']['slots'][0]['day'] == 1, f"a child's wish waits for approval: {res}")
    check('parent or adult' in res['message'], res['message'])
    res = programs.approve(rid, 'mom')
    check(res['status'] == 'success' and {pc['days_of_week'][0] for pc in _commitments(rid)} == {1}, "approval claims the child's days")


def scenario_adult_may_claim():
    _reset(); rid = _active()
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '16:00'}], dict(AUNT))
    check(res['status'] == 'success' and res['state'] == 'active', f"an adult claims directly (P5): {res}")


def scenario_refusals():
    _reset(); rid = _active()
    programs.finish(rid)
    res = programs.replace_schedule(rid, [{'day': 1, 'time_start': '16:00'}], dict(MOM))
    check(res['status'] == 'error', f"a finished run has no days to change: {res}")
    check(programs.replace_schedule('nope', [], dict(MOM))['status'] == 'error', "unknown run")


def scenario_drift_reads_the_change_date():
    _reset(); rid = _active()
    # Six weeks of Monday/Wednesday windows missed, then the days change to Tue/Thu today.
    row = storage.get_program(rid)
    storage.update_program(rid, {'baseline': {**row['baseline'], 'start_date': (datetime.date.today() - datetime.timedelta(days=42)).isoformat()}})
    programs.replace_schedule(rid, [{'day': 1, 'time_start': '17:00'}, {'day': 3, 'time_start': '17:00'}], dict(MOM))
    short = programs.weekday_shortfall(loaded(rid))
    check(short is None, f"no shortfall is blamed on days that only started today: {short}")


def scenario_watcher_offer_executes_nothing():
    _reset(); rid = _active()
    from services import chat_actions
    before = storage.get_program(rid)['state']
    res = chat_actions._execute('change_program_days', {'program_id': rid})
    check(res['status'] == 'success' and res['open'] == {'kind': 'program', 'id': rid, 'menu': 'change_days'}
          and storage.get_program(rid)['state'] == before and _commitments(rid), f"the offer only opens the editor: {res}")
    res = chat_actions._execute('reshape_program', {'program_id': rid})
    check(res['status'] == 'success' and storage.get_program(rid)['state'] == before and _commitments(rid),
          f"an old stored offer no longer releases time: {res}")
    check(chat_actions.ACTION_LABELS.get('change_program_days') == 'Change the days', "label")


def scenario_watcher_finding_names_the_new_action():
    _reset(); rid = _active()
    from services import watchers
    for pc in _commitments(rid):
        storage.delete_protected_commitment(pc['id'])
    findings = watchers._program_findings(datetime.datetime.now())
    drift = next((f for f in findings if f.kind == 'program_drift'), None)
    check(drift is not None and drift.action['action_type'] == 'change_program_days' and drift.action['label'] == 'Change the days'
          and 'Re-shape' not in drift.line, f"drift offers Change the days: {drift}")


def scenario_http_patch_schedule_and_no_reshape_route():
    _reset(); rid = _active()
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    paths = {r.path for r in main.app.routes}
    check('/api/programs/{program_id}/reshape' not in paths and '/api/programs/{program_id}/schedule' in paths, f"routes: reshape gone, schedule present")
    tok = storage.create_member_token('mom')
    r = c.patch(f'/api/programs/{rid}/schedule', json={'slots': [{'day': 4, 'time_start': '18:00'}]}, headers={'X-Member-Token': tok})
    check(r.status_code == 200 and r.json()['status'] == 'success', f"PATCH schedule: {r.text}")
    tok = storage.create_member_token('kid')
    r = c.patch(f'/api/programs/{rid}/schedule', json={'slots': [{'day': 5, 'time_start': '18:00'}]}, headers={'X-Member-Token': tok})
    check(r.status_code == 200 and r.json()['state'] == 'proposed', f"a child's PATCH lands proposed: {r.text}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

Read `tests/test_programs_endpoints.py` `_reset()` and `Req` first and copy its token/header convention if `create_member_token` differs; read `watchers._program_findings`'s signature (`now`) and `Finding`'s attribute names (`kind`, `action`, `line`) and adjust.

- [ ] **Step 2: Run to see it fail**

Run: `cd chauffeur; unset HA_BASE_URL; python tests/test_program_schedule.py`
Expected: AttributeError `replace_schedule`, then route assertions failing.

- [ ] **Step 3: Implement `replace_schedule`**

In `services/programs.py` after `reshape`:

```python
def _claimer(actor) -> bool:
    return bool(actor) and actor.get('role') in ('parent', 'adult') and (actor.get('status') or 'active') == 'active'


@_program_work
def replace_schedule(program_id: str, slots: list, actor: dict) -> dict:
    """Change the days (spec §5.3): active = release + claim in one bracket with a
    snapshot restore; paused = remember only; a child keeper's wish goes to proposed."""
    row = load(storage.get_program(program_id))
    if not row:
        return {'status': 'error', 'code': 404, 'message': 'That program is no longer here.'}
    if row.get('unresolved'):
        return {'status': 'error', 'message': 'Its library program is missing'}
    state = row.get('state')
    if state not in ('active', 'paused'):
        return {'status': 'error', 'message': f"That program is {state}; there are no days to change."}
    shape = dict(row.get('shape') or {})
    minutes = int(shape.get('minutes') or 25)
    wanted = sanitize_slots(slots, minutes) or propose_slots(row.get('member_id'), {**shape, 'slots': []})
    if not wanted:
        return {'status': 'error', 'message': 'There is no time to claim.'}
    new_shape = clamp_shape({**shape, 'slots': wanted, 'preferred_days': [s['day'] for s in wanted]})
    today = datetime.date.today().isoformat()
    baseline = dict(row.get('baseline') or {})
    history = list(baseline.get('schedule_history') or [])
    history.append({'until': today, 'preferred_days': list(shape.get('preferred_days') or [])})
    new_baseline = {**baseline, 'schedule_changed_on': today, 'schedule_history': history[-12:]}

    if state == 'paused':
        storage.update_program(program_id, {'paused_slots': wanted, 'shape': new_shape, 'baseline': new_baseline})
        return {'status': 'success', 'schedule_dirty': False, 'state': 'paused', 'slots': wanted,
                'message': 'Saved. These days are claimed when you resume.'}

    if not _claimer(actor):
        # A child keeper (own run): the wish is kept, the week is handed back for approval.
        try:
            released = release_commitments(program_id)
        except RuntimeError:
            return {'status': 'error', 'message': RELEASE_ERROR}
        storage.update_program(program_id, {'state': 'proposed', 'paused_at': None, 'paused_slots': [],
                                            'shape': new_shape, 'baseline': new_baseline})
        return {'status': 'success', 'schedule_dirty': bool(released), 'state': 'proposed', 'slots': wanted,
                'message': 'Saved your times; a parent or adult puts them on the calendar.'}

    # Active, claimer: one bracket. Snapshot what the week holds now.
    with storage.db_lock:
        live = {pc['id']: pc for pc in storage.get_protected_commitments(member_id=row.get('member_id'), include_inactive=True)}
        emissions = dict(storage.get_program(program_id).get('emissions') or {})
        old_ids = [cid for cid in (emissions.get('commitment_ids') or []) if cid in live]
        snapshot = [dict(live[cid]) for cid in old_ids]
        # Orphans (deleted by hand) are forgotten, never re-created.
        emissions['commitment_ids'] = old_ids
        storage.update_program(program_id, {'emissions': emissions})
        made = []
        try:
            release_commitments(program_id)
            fresh = {'commitment_ids': [], 'thread_ids': list(emissions.get('thread_ids') or []),
                     'event_ids': list(emissions.get('event_ids') or [])}
            _emit_commitments(program_id, row, wanted, fresh, made)
            storage.update_program(program_id, {'shape': new_shape, 'baseline': new_baseline, 'emissions': fresh})
        except deletion.Cancelled:
            raise
        except Exception as e:
            # Put the old week back exactly: delete what this attempt made, re-insert the snapshot.
            for cid in made:
                _quietly('undo new commitment', storage.delete_protected_commitment, cid)
            restored = []
            for pc in snapshot:
                if storage.get_protected_commitment(pc['id']) is None:
                    _quietly('restore commitment', storage.add_protected_commitment, pc)
                restored.append(pc['id'])
            storage.update_program(program_id, {'emissions': {**emissions, 'commitment_ids': restored}})
            return {'status': 'error', 'message': f"Couldn't change the days, so the old ones were kept: {e}"}
    return {'status': 'success', 'schedule_dirty': True, 'state': 'active', 'slots': wanted,
            'message': f"Changed. {len(wanted)} practice window(s) on the calendar."}
```

Check `storage.add_protected_commitment` accepts a full row with its `id` (re-insert); if it mints a new id, add an `id`-preserving path or use the table directly under the lock, and say so in the report. Check `deletion` and `_quietly` are importable names in this module (they are used by `approve`).

Drift: in `weekday_shortfall`, after reading `start`, read `changed = (program.get('baseline') or {}).get('schedule_changed_on')`; when set, `began = max(began, date(changed))` so the window starts at the change. `maybe_rebaseline` calls `weekday_shortfall`, so it follows.

Watcher: `services/watchers.py:643-645` → `action={'label': 'Change the days', 'action_type': 'change_program_days', 'payload': {'program_id': row['id']}}` and the line text "… Change the days and I'll put the new windows on the calendar." `services/chat_actions.py`: `ADMIN_ACTIONS` gains `"change_program_days"`; `ACTION_LABELS["change_program_days"] = "Change the days"`; in `_execute`, both `change_program_days` and `reshape_program` return `{'status': 'success', 'open': {'kind': 'program', 'id': payload.get('program_id'), 'menu': 'change_days'}, 'message': 'Open the program and choose Change the days.'}` with no service call. Keep `programs.reshape` (unreferenced now; the child path above does its own release).

Routes: delete `reshape_program` at `main.py:8949`; add

```python
@app.patch("/api/programs/{program_id}/schedule")
def program_schedule(program_id: str, background_tasks: BackgroundTasks = None,
                     body: dict = Body(default={}), request: Request = None):
    """Change the days (programs spec §5.3): the run's keeper or a parent/adult stand-in."""
    _piece_or_404('program', program_id, request, 'edit')
    from services import programs as _prog
    row = storage.get_program(program_id)
    if not row:
        raise HTTPException(status_code=404, detail='No such program')
    _program_permission_or_refuse(request, body, row)
    actor = storage.get_member(_acting_id(request, body.get('member_id'))) or {}
    return _program_refresh(_prog.replace_schedule(program_id, body.get('slots') or [], actor), background_tasks)
```

Add the READERS row next to the other `/api/programs/{program_id}/...` rows with kinds `('program',)` and gate text `_piece_or_404 edit; _program_permission_or_refuse`; classify `programs.replace_schedule` and `programs._claimer` INTERNAL if the register test lists them.

- [ ] **Step 4: Run to green, then the neighbours**

Run: `python tests/test_program_schedule.py; python tests/test_programs_endpoints.py; python tests/test_programs_runtime.py; python tests/test_programs_vitals.py; python tests/test_chat_actions.py; python tests/test_access_register.py; python tests/test_auth.py; python tests/test_retire_redirects.py`
`test_programs_endpoints` asserts the reshape route exists in its first scenario: update that assertion to `schedule`. Expected: PASS.

- [ ] **Step 5: Hand back** (working tree + note: the `add_protected_commitment` id finding, what you ran).

---

### Task 2: One-pass setup server side: preview slots and the activation contract (Codex)

**Files:**
- Modify: `main.py` `create_program` (~8087-8144), new `POST /api/programs/preview-slots`; `templates/components/programs_page.html:602` copy and `canApprove()` (~856) are Task 4's
- Modify: `services/access_readers.py`
- Test: `tests/test_program_setup.py` (new)

**Interfaces:**
- Consumes: `programs.approve(program_id, approver_id, slots=)` (returns `{'status': 'error', 'message': 'There is no time to claim.'}` on no time; other errors revert its own emissions), `programs.create_row`, `library.prepare`, `storage.add_library_program`, `library_scripts.write`, `propose_slots(member_id, shape)`, `clamp_shape`, `_project_to_join`, `_library_actor`.
- Produces: `POST /api/programs` body gains `activate: bool` and `minutes`; with `activate` true and a parent/adult actor the run lands `active` with commitments claimed, or the whole creation is rolled back on an approval error (no run, no new library row), or stays `proposed` with `status: 'success', 'state': 'proposed', 'message': "Made it, but found no free time this week; pick times to start it."` when approve says no time. `POST /api/programs/preview-slots` body `{member_id, library_id?, minutes?, sessions_per_week?, preferred_days?}` → `{'slots': [...], 'minutes': int}`; a child may preview only themselves; an adult/parent anyone.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_program_setup.py`:

```python
"""One-pass setup (spec §4): activate lands active for a parent/adult, proposed for a child,
proposed with a message when there is no time, and nothing is kept when activation fails.
Run from chauffeur/: python tests/test_program_setup.py"""
from unittest.mock import patch

from program_fixture import add_run  # harness first
from harness import check  # noqa: F401
from fastapi.testclient import TestClient
from services import storage, programs, library

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
AUNT = {'id': 'aunt', 'name': 'Aunt', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}


def _reset():
    for t in (storage.programs_table, storage.library_programs_table, storage.members_table, storage.protected_commitments_table, storage.projects_table):
        t.truncate()
    for m in (MOM, AUNT, KID):
        storage.add_member(dict(m))
    from services import projects
    p = projects.create({'title': 'Piano for Kate', 'goal': 'x', 'done_when': 'x', 'owner_member_id': 'kid', 'audience': 'household'}, dict(MOM))['project']
    lib = storage.add_library_program(library.from_curated('Learn piano', {'age_band': 'any', 'minutes': 20, 'sessions_per_week': 2, 'assumes': ''},
        {'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'm', 'units': [{'title': 'Scales', 'sessions': 2}]}],
         'source': {'origin': 'cited', 'plan_name': 'Piano Adventures', 'url': 'https://x', 'facts': []}}, 'mom'))
    return p['id'], lib


def _c():
    import main
    return TestClient(main.app)


def _h(who):
    return {'X-Member-Token': storage.create_member_token(who)}


def _runs():
    return storage.get_programs(include_finished=True)


def scenario_parent_activate_lands_active():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True,
                                                           'slots': [{'day': 0, 'time_start': '18:00'}, {'day': 2, 'time_start': '18:00'}], 'minutes': 20})
    check(r.status_code == 200 and r.json()['status'] == 'success' and r.json()['program']['state'] == 'active', f"active at once: {r.text}")
    run = _runs()[0]
    ids = run['emissions']['commitment_ids']
    check(len(ids) == 2 and run['approved_by'] == 'mom' and run['baseline']['start_date'], f"claimed exactly as approve claims: {run['emissions']} {run['baseline']}")
    check(run['shape']['minutes'] == 20 and run['shape']['sessions_per_week'] == 2, f"one duration per run: {run['shape']}")


def scenario_adult_activates_too():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('aunt'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True})
    check(r.status_code == 200 and r.json()['program']['state'] == 'active', f"an adult may start it (P5): {r.text}")


def scenario_child_lands_proposed():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('kid'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True})
    check(r.status_code == 200 and r.json()['program']['state'] == 'proposed' and not _runs()[0]['emissions'].get('commitment_ids'),
          f"a child never claims time: {r.text}")


def scenario_no_time_keeps_a_proposal_and_says_so():
    pid, lib = _reset()
    with patch.object(programs, 'propose_slots', lambda *a, **k: []):
        r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid, 'activate': True, 'slots': []})
    body = r.json()
    check(r.status_code == 200 and body['status'] == 'success' and body['program']['state'] == 'proposed'
          and 'no free time' in body['message'], f"proposed with the message: {r.text}")


def scenario_activation_failure_keeps_nothing():
    pid, lib = _reset()
    before_libs = len(storage.get_library_programs())
    def boom(data):
        raise RuntimeError('calendar down')
    with patch.object(storage, 'add_protected_commitment', boom):
        r = _c().post('/api/programs', headers=_h('mom'), json={'title': 'Learn drums', 'for_member_id': 'kid', 'project_id': pid, 'activate': True,
                                                               'slots': [{'day': 0, 'time_start': '18:00'}]})
    check(r.status_code == 200 and r.json()['status'] == 'error', f"the error is reported: {r.text}")
    check(not _runs() and len(storage.get_library_programs()) == before_libs, "no run and no new library row survive a failed activation")


def scenario_without_activate_today_behaviour_stands():
    pid, lib = _reset()
    r = _c().post('/api/programs', headers=_h('mom'), json={'library_id': lib, 'for_member_id': 'kid', 'project_id': pid})
    check(r.status_code == 200 and r.json()['program']['state'] == 'proposed', f"no activate = proposed, as today: {r.text}")


def scenario_preview_slots():
    pid, lib = _reset()
    r = _c().post('/api/programs/preview-slots', headers=_h('mom'), json={'member_id': 'kid', 'library_id': lib})
    check(r.status_code == 200 and len(r.json()['slots']) == 2 and r.json()['minutes'] == 20, f"a preview from the library profile: {r.text}")
    r = _c().post('/api/programs/preview-slots', headers=_h('kid'), json={'member_id': 'mom'})
    check(r.status_code == 403, f"a child previews only their own week: {r.status_code}")
    r = _c().post('/api/programs/preview-slots', headers=_h('kid'), json={'member_id': 'kid', 'sessions_per_week': 3, 'minutes': 15, 'preferred_days': [1, 3, 5]})
    check(r.status_code == 200 and [s['day'] for s in r.json()['slots']] == [1, 3, 5], f"preferred days respected: {r.text}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

The make-new path in `scenario_activation_failure_keeps_nothing` calls the curator: stub it as `tests/test_library_flows.py` `_fresh()` does (`programs_curate.curate` → a cited two-phase result) by importing and reusing that stub, or patch `programs_curate.curate` to return the same `{'phases': [...], 'source': {...}}` shape used in `_reset()` above. `library_scripts.write` must not start a thread in tests: patch it to `lambda *a, **k: {'status': 'ok', 'job': None}` in `_reset()` or per scenario.

- [ ] **Step 2: Run to see it fail**

Run: `python tests/test_program_setup.py`
Expected: `activate` ignored (state proposed in the first scenario), preview route 404.

- [ ] **Step 3: Implement**

In `create_program` (main.py ~8087): read `activate = bool(body.get('activate'))`. Keep the existing transaction that writes the library row (make-new) and the run. After `pid` is known and still inside the `try` that owns `RunRefused`, if `activate`:

```python
            if activate:
                actor_row = storage.get_member(actor.get('id')) or {}
                if actor_row.get('role') in ('parent', 'adult'):
                    approved = _prog.approve(pid, actor.get('id'), slots=body.get('slots'))
                    if approved.get('status') != 'success':
                        if approved.get('message') == 'There is no time to claim.':
                            no_time = True
                        else:
                            raise ActivationFailed(approved.get('message') or 'Could not start the program.')
```

Define `class ActivationFailed(Exception)` beside `RunRefused`; catching it outside the `with storage.db_lock, storage.db.transaction():` block returns `{'status': 'error', 'message': str(e)}` — the transaction's rollback discards the run and the library row (confirm `storage.db.transaction()` rolls back on exception by reading `services/storage_sqlite.py:330`; if the library row was inserted through a path that commits separately, delete it explicitly in the except). `approve` runs inside the same transaction; its own `_revert_attempt` runs before the exception reaches here, which is fine. The script job (`library_scripts.write`) starts after the `with` block, only on success. When `no_time`: return `{'status': 'success', 'id': pid, 'program': load(...), 'state': 'proposed', 'message': "Made it, but found no free time this week; pick times to start it."}`. Also accept `minutes` in the body (it is already in the `shape` merge list).

Preview route, next to `program_footprint`:

```python
@app.post("/api/programs/preview-slots")
def program_preview_slots(body: dict = Body(default={}), request: Request = None):
    """The week the app would propose, before a run exists (programs spec §4)."""
    from services import programs as _prog, library as _lib
    actor = _library_actor(request)
    member_id = body.get('member_id') or actor.get('id')
    me = storage.get_member(actor.get('id')) or {}
    if member_id != actor.get('id') and me.get('role') not in ('parent', 'adult'):
        raise HTTPException(status_code=403, detail='You can only look at your own week.')
    if not storage.get_member(member_id):
        raise HTTPException(status_code=404, detail='No such member')
    profile = {}
    if body.get('library_id'):
        row = storage.get_library_program(body['library_id']) or {}
        profile = dict(row.get('made_for') or {})
    shape = _prog.clamp_shape({**{k: profile[k] for k in ('minutes', 'sessions_per_week') if k in profile},
                               **{k: body[k] for k in ('minutes', 'sessions_per_week', 'preferred_days') if k in body}})
    return {'slots': _prog.propose_slots(member_id, {**shape, 'slots': []}), 'minutes': shape['minutes']}
```

READERS row: `((R, 'POST', '/api/programs/preview-slots'), '4.1-signed-in', (), '_library_actor; self or parent/adult')`.

- [ ] **Step 4: Run to green, then the neighbours**

Run: `python tests/test_program_setup.py; python tests/test_programs_endpoints.py; python tests/test_library_flows.py; python tests/test_project_pieces.py; python tests/test_access_register.py; python tests/test_auth.py`
Expected: PASS.

- [ ] **Step 5: Hand back.**

---

### Task 3: `programs.monitor`, session ids and `remove_session` (Codex)

**Files:**
- Modify: `services/programs.py` (after `progress`), `services/migrations.py` (new `migrate_program_session_ids_v2499`, chained at the end of the startup list ~line 742), `main.py` (new `GET /api/programs/{program_id}/monitor`, `DELETE /api/programs/{program_id}/sessions/{session_id}`), `services/storage.py` `append_program_session` (mint `id`), `services/access_readers.py`
- Test: `tests/test_program_monitor.py` (new)

**Interfaces:**
- Consumes: `load`, `progress`, `practice_windows(start, end, member_id, viewer=)`, `lesson_for(run, date, slot_rank=)`, `ready_to_judge`, `reconcile_progress`.
- Produces: `programs.monitor(run, viewer=None) -> dict`:
  `{'last_practised': 'YYYY-MM-DD'|None, 'sessions_this_week': int, 'next_window': {'date','time_start','lesson_title','variant_label'}|None, 'sessions_total': int, 'minutes_total': int, 'phases': [{'id','name','milestone','milestone_hit_at','progression','current': bool, 'lessons': [{'id','title','sessions','done_sessions','completed': bool,'current': bool,'next_variant': str|None,'logged_variants': [str]}]}], 'log': [{'id','when','logged_on','minutes','lesson_title','variant_label','source','note'}], 'ready_to_judge': str}`; every session row has an `id` (uuid hex) after migration; `programs.remove_session(program_id, session_id) -> {'status','message'}` recomputes `progress` from the remaining sessions; `GET /api/programs/{id}/monitor` → the dict; `DELETE /api/programs/{id}/sessions/{sid}` → `{'status': 'success'}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_program_monitor.py`:

```python
"""programs.monitor and remove_session (spec §5.1). Run from chauffeur/: python tests/test_program_monitor.py"""
import datetime, time
from unittest.mock import patch

from program_fixture import add_run, loaded, phase_id  # harness first
from harness import check  # noqa: F401
from services import storage, programs

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}
BASE = {'shape': {'sessions_per_week': 3, 'minutes': 20, 'preferred_days': [0, 2, 4]},
        'phases': [{'name': 'Foundations', 'weeks': 2, 'steps': ['a'], 'milestone': 'plays a C scale', 'progression': 'one less reminder',
                    'units': [{'title': 'Hands and keys', 'sessions': 1}, {'title': 'Scales', 'sessions': 2}], 'rotation': [{'label': 'A', 'steps': ['r']}, {'label': 'B', 'steps': ['l']}]},
                   {'name': 'Songs', 'weeks': 3, 'steps': ['b'], 'milestone': 'plays Twinkle', 'units': [{'title': 'Twinkle', 'sessions': 2}]}],
        'source': {'origin': 'none', 'reason': 'test'},
        'baseline': {'start_date': '2026-10-01', 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}


def _reset():
    for t in (storage.programs_table, storage.library_programs_table, storage.members_table, storage.protected_commitments_table):
        t.truncate()
    storage.add_member(dict(MOM)); storage.add_member(dict(KID))
    return add_run({'id': 'r1', 'member_id': 'kid', 'title': 'Piano', 'state': 'active', **BASE})


def _lesson_ids(rid):
    return [l['id'] for l in loaded(rid)['lessons']]


def scenario_sessions_carry_ids():
    rid = _reset()
    programs.log_session(rid, minutes=20)
    s = storage.get_program(rid)['sessions'][0]
    check(isinstance(s.get('id'), str) and len(s['id']) == 32, f"a new session has an id: {s}")


def scenario_migration_mints_ids_once():
    rid = _reset()
    storage.update_program(rid, {'sessions': [{'ts': time.time() - 86400, 'minutes': 10, 'source': 'added', 'note': ''}]})
    from services import migrations
    migrations.migrate_program_session_ids_v2499()
    first = storage.get_program(rid)['sessions'][0]['id']
    migrations.migrate_program_session_ids_v2499()
    check(first and storage.get_program(rid)['sessions'][0]['id'] == first, "ids are minted once and kept")


def scenario_monitor_stats_ladder_and_log():
    rid = _reset()
    ids = _lesson_ids(rid)
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    programs.log_session(rid, minutes=20, slot_date=monday.isoformat(), lesson_id=ids[0], variant_label='A')          # completes lesson 1
    programs.log_session(rid, minutes=25, slot_date=(monday + datetime.timedelta(days=2)).isoformat(), lesson_id=ids[1], variant_label='B')
    win = [{'program_id': rid, 'date': (today + datetime.timedelta(days=1)).isoformat(), 'time_start': '18:00', 'lesson_id': ids[1], 'variant_label': 'A', 'unit_title': 'Scales', 'logged': False}]
    with patch.object(programs, 'practice_windows', lambda *a, **k: win):
        m = programs.monitor(loaded(rid), viewer=dict(MOM))
    check(m['sessions_this_week'] == 2 and m['sessions_total'] == 2 and m['minutes_total'] == 45, f"counts, never a fraction: {m}")
    check(m['last_practised'] == (monday + datetime.timedelta(days=2)).isoformat(), f"last practised by slot date: {m['last_practised']}")
    check(m['next_window'] and m['next_window']['lesson_title'] == 'Scales' and m['next_window']['variant_label'] == 'A', f"next window: {m['next_window']}")
    ph = m['phases'][0]
    check(ph['current'] and ph['progression'] == 'one less reminder' and ph['milestone'] == 'plays a C scale', f"phase: {ph}")
    l1, l2 = ph['lessons']
    check(l1['completed'] and l1['done_sessions'] == 1 and not l1['current'], f"lesson 1 done: {l1}")
    check(l2['current'] and l2['done_sessions'] == 1 and l2['logged_variants'] == ['B'] and l2['next_variant'] == 'A', f"the lit rung knows its variants from the log and the next window: {l2}")
    check(not m['phases'][1]['current'] and m['phases'][1]['lessons'][0]['done_sessions'] == 0, "the second phase waits")
    row = m['log'][0]
    check(set(row) >= {'id', 'when', 'logged_on', 'minutes', 'lesson_title', 'variant_label', 'source'} and row['lesson_title'] == 'Scales', f"log rows: {row}")
    check(all(k not in str(m) for k in ('percent', 'of 12', '1 of 3')), "no completion fraction anywhere")


def scenario_monitor_all_judged():
    rid = _reset()
    for i in range(2):
        programs.mark_milestone(rid, phase_id=phase_id(rid, i))
    m = programs.monitor(loaded(rid), viewer=dict(MOM))
    check(len(m['phases']) == 2 and all(p['milestone_hit_at'] for p in m['phases']) and m['next_window'] is None, f"a judged-out run still renders: {m}")


def scenario_remove_session_recomputes_progress():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, minutes=20, lesson_id=ids[0])
    row = storage.get_program(rid)
    check(row['progress']['current'] == ids[1], "the bookmark moved on")
    sid = row['sessions'][0]['id']
    res = programs.remove_session(rid, sid)
    row = storage.get_program(rid)
    check(res['status'] == 'success' and not row['sessions'] and row['progress']['current'] == ids[0]
          and not row['progress']['lessons'].get(ids[0], {}).get('completed_at'), f"progress recomputed from the log: {row['progress']}")
    check(programs.remove_session(rid, 'nope')['status'] == 'error', "unknown session")


def scenario_remove_keeps_a_judged_phase():
    rid = _reset()
    ids = _lesson_ids(rid)
    programs.log_session(rid, minutes=20, lesson_id=ids[0])
    programs.mark_milestone(rid, phase_id=phase_id(rid, 0))
    sid = storage.get_program(rid)['sessions'][0]['id']
    programs.remove_session(rid, sid)
    p = storage.get_program(rid)['progress']
    check(p['phases'][phase_id(rid, 0)]['milestone_hit_at'] and p['current'] == ids[2], f"a person's judgement outlives a removed session: {p}")


def scenario_http():
    rid = _reset()
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    tok = {'X-Member-Token': storage.create_member_token('mom')}
    programs.log_session(rid, minutes=20)
    r = c.get(f'/api/programs/{rid}/monitor', headers=tok)
    check(r.status_code == 200 and r.json()['sessions_total'] == 1, f"monitor route: {r.text}")
    sid = storage.get_program(rid)['sessions'][0]['id']
    r = c.delete(f'/api/programs/{rid}/sessions/{sid}', headers=tok)
    check(r.status_code == 200 and not storage.get_program(rid)['sessions'], f"delete route: {r.text}")
    kid = {'X-Member-Token': storage.create_member_token('kid')}
    programs.log_session(rid, minutes=20)
    sid = storage.get_program(rid)['sessions'][0]['id']
    r = c.delete(f'/api/programs/{rid}/sessions/{sid}', headers=kid)
    check(r.status_code == 200 and not storage.get_program(rid)['sessions'], "the run's own keeper may remove their session")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

- [ ] **Step 2: Run to see it fail.** Expected: no `id` on sessions, `monitor` missing.

- [ ] **Step 3: Implement**

`storage.append_program_session`: `entry.setdefault('id', uuid.uuid4().hex)` before appending.

Migration in `services/migrations.py`:

```python
def migrate_program_session_ids_v2499():
    """Every logged session gets a stable id so one can be removed by name (programs spec §5.1)."""
    import uuid
    if storage.get_app_state('program_session_ids_v2499'):
        return
    for run in storage.get_programs(include_finished=True):
        sessions = run.get('sessions') or []
        if all(s.get('id') for s in sessions):
            continue
        storage.update_program(run['id'], {'sessions': [{**s, 'id': s.get('id') or uuid.uuid4().hex} for s in sessions]})
    storage.set_app_state('program_session_ids_v2499', time.time())
```
Chain it after `migrate_library_scripts_v2499()` in the startup list (same try/except shape) and classify it INTERNAL in `access_readers`. The test calls it twice; make the second call a no-op by the app_state gate, and make the first call idempotent per row.

`programs.monitor`:

```python
def monitor(run: dict, viewer=None) -> dict:
    """The admin sheet's monitoring view (spec §5.1): counts, the ladder, the log. Never a fraction."""
    row = load(run)
    sessions = list(row.get('sessions') or [])
    def day_of(s):
        if s.get('slot_date'):
            return str(s['slot_date'])
        try:
            return datetime.datetime.fromtimestamp(float(s['ts'])).date().isoformat()
        except (KeyError, TypeError, ValueError):
            return ''
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday())
    days = [day_of(s) for s in sessions]
    this_week = sum(1 for d in days if d and monday.isoformat() <= d <= (monday + datetime.timedelta(days=6)).isoformat())
    windows = [w for w in practice_windows(today, today + datetime.timedelta(days=13), row.get('member_id'), viewer=viewer)
               if w.get('program_id') == row.get('id') and not w.get('logged')] if row.get('state') == 'active' else []
    nxt = windows[0] if windows else None
    lessons_by_id = {l['id']: l for l in row.get('lessons') or []}
    titles = {lid: l.get('title') or '' for lid, l in lessons_by_id.items()}
    counts = (row.get('progress') or {}).get('lessons') or {}
    current = (row.get('progress') or {}).get('current')
    logged_variants = {}
    for s in sessions:
        if s.get('lesson_id'):
            logged_variants.setdefault(s['lesson_id'], []).append(s.get('variant_label') or '')
    phases = []
    first_unjudged = next((p['id'] for p in row.get('phases') or [] if not p.get('milestone_hit_at')), None)
    for ph in row.get('phases') or []:
        ls = []
        for l in (row.get('lessons') or []):
            if l['phase_id'] != ph['id']:
                continue
            c = counts.get(l['id']) or {}
            ls.append({'id': l['id'], 'title': l.get('title') or '', 'sessions': int(l.get('sessions') or 1),
                       'done_sessions': int(c.get('done_sessions') or 0), 'completed': bool(c.get('completed_at')),
                       'current': l['id'] == current,
                       'next_variant': (nxt.get('variant_label') or None) if nxt and nxt.get('lesson_id') == l['id'] else None,
                       'logged_variants': [v for v in logged_variants.get(l['id'], []) if v]})
        phases.append({'id': ph['id'], 'name': ph.get('name') or '', 'milestone': ph.get('milestone') or '',
                       'milestone_hit_at': ph.get('milestone_hit_at'), 'progression': ph.get('progression') or '',
                       'current': ph['id'] == first_unjudged, 'lessons': ls})
    log = []
    for s in sorted(sessions, key=lambda s: float(s.get('ts') or 0), reverse=True):
        logged_on = ''
        try:
            logged_on = datetime.datetime.fromtimestamp(float(s['ts'])).date().isoformat()
        except (KeyError, TypeError, ValueError):
            pass
        log.append({'id': s.get('id'), 'when': day_of(s), 'logged_on': logged_on, 'minutes': int(s.get('minutes') or 0),
                    'lesson_title': titles.get(s.get('lesson_id'), ''), 'variant_label': s.get('variant_label') or '',
                    'source': s.get('source') or '', 'note': s.get('note') or ''})
    return {'last_practised': max((d for d in days if d), default=None), 'sessions_this_week': this_week,
            'next_window': ({'date': nxt['date'], 'time_start': nxt.get('time_start') or '', 'lesson_title': nxt.get('unit_title') or '',
                             'variant_label': nxt.get('variant_label') or ''} if nxt else None),
            'sessions_total': len(sessions), 'minutes_total': sum(int(s.get('minutes') or 0) for s in sessions),
            'phases': phases, 'log': log, 'ready_to_judge': ready_to_judge(row)}


def remove_session(program_id: str, session_id: str) -> dict:
    """Undo one logged session; progress is recomputed from what remains (spec §5.1)."""
    with storage.db_lock, storage.db.transaction():
        raw = storage.get_program(program_id)
        if not raw:
            return {'status': 'error', 'code': 404, 'message': 'That program is no longer here.'}
        kept = [s for s in raw.get('sessions') or [] if s.get('id') != session_id]
        if len(kept) == len(raw.get('sessions') or []):
            return {'status': 'error', 'code': 404, 'message': 'No such session.'}
        row = load({**raw, 'sessions': kept})
        progress_ = {'lessons': {}, 'current': None, 'phases': dict((row.get('progress') or {}).get('phases') or {})}
        for s in kept:
            lid = s.get('lesson_id')
            if lid and lid in {l['id'] for l in row.get('lessons') or []}:
                c = progress_['lessons'].setdefault(lid, {'done_sessions': 0, 'completed_at': None})
                c['done_sessions'] += 1
                need = int(next(l for l in row['lessons'] if l['id'] == lid).get('sessions') or 1)
                if c['done_sessions'] >= need and not c['completed_at']:
                    c['completed_at'] = s.get('ts') or time.time()
        progress_ = reconcile_progress({**raw, 'sessions': kept, 'progress': progress_}, storage.get_library_program(raw.get('library_id')) or {})
        storage.update_program(program_id, {'sessions': kept, 'progress': progress_})
    return {'status': 'success', 'message': 'Removed. Progress follows the sessions that are left.'}
```

Read `reconcile_progress(run, curriculum, previous=None)` before relying on it: it must keep `progress.phases[*].milestone_hit_at` (a person's judgement) and place `current` at the first uncompleted lesson of the first unjudged phase. If it does not accept a run whose `progress.lessons` is already rebuilt, compute `current` directly here with the same rule and keep `phases` as they were. Legacy runs (no `library_id`): `remove_session` only drops the entry.

Routes (beside `/footprint`): `GET /api/programs/{program_id}/monitor` → `_piece_or_404('program', id, request)` then `programs.monitor(row, viewer=_piece_viewer(request))`; `DELETE /api/programs/{program_id}/sessions/{session_id}` → `_piece_or_404(..., 'edit')`, `_program_permission_or_refuse`, `programs.remove_session`, `_library_result`. READERS rows for both with kinds `('program',)`; INTERNAL for `monitor`, `remove_session`, the migration.

- [ ] **Step 4: Run to green, then the neighbours**

Run: `python tests/test_program_monitor.py; python tests/test_programs_endpoints.py; python tests/test_programs_storage.py; python tests/test_library_model.py; python tests/test_programs_vitals.py; python tests/test_access_register.py; python tests/test_auth.py`
Expected: PASS.

- [ ] **Step 5: Hand back.**

---

### Task 4: The setup sheet and the monitoring sheet (Claude)

**Files:**
- Create: `templates/components/program_setup_sheet.html`
- Modify: `templates/components/programs_page.html` (delete lines 19–78 dead form; redraw sheet-mode body; ⋯; copy; `canApprove`), `templates/components/project_piece_forms.html` (program branch → the sheet), `templates/components/projects_page.html` (`addPieceKind('program')` opens the sheet; `pickLibrary`, `loadLibrary` move into the sheet's island), `templates/components/library_card.html` (`Start it for…` in the card's ⋯ comes in Task 8; here only `chfLibrary.openSetup(libraryId)` helper), `templates/app.html` (the phone's Add a piece › Program path uses the same sheet component included once)
- Test: `tests/test_library_live.py` (new scenarios), `tests/test_programs_endpoints.py` (copy), `tests/test_programs_reachable.py`
- Run: `python tools/build_tailwind.py`

**Interfaces:**
- Consumes: `POST /api/programs/preview-slots`, `POST /api/programs` with `activate`, `GET /api/programs/{id}/monitor`, `PATCH /api/programs/{id}/schedule`, `DELETE /api/programs/{id}/sessions/{sid}`, `POST /api/programs/{id}/edit` (minutes / starting_point / target_date on active runs — see Step 3), existing `/session`, `/milestone`, `/unit`, `/pause`, `/resume`, `/finish`, `/drop`, `/approve`, `/lesson`, `chfDeleteRecord`, `promptChoice`, `lesson-player:open`.
- Produces: a window-scoped opener `window.chfProgramSetup.open({projectId, forMemberId?, libraryId?, runId?})` (the DM card and the library's Start it for… call it; with `runId` it configures that run's slots and approves, never creating a second run, Task 7); DOM contract for tests: `[data-setup-sheet]`, `[data-setup-who]`, `[data-setup-pick="library_id"]`, `[data-setup-make-new]`, `[data-setup-slot]` rows with `[data-slot-day]` select and `[data-slot-time]`, `[data-setup-add-time]`, `[data-setup-minutes]`, `[data-setup-start]`, `[data-setup-retry]`; monitoring sheet: `[data-monitor-stats]`, `[data-rung="lesson_id"]` with `[data-rung-current]`, `[data-reached-it="phase_id"]` on every unjudged phase, `[data-monitor-log]` folded, `[data-run-menu]` (⋯) whose promptChoice offers exactly: Change the days, Program settings, Log a session, Start a session, Look again, Plan without the book, Pause|Resume, Done with it, Drop, Delete.

- [ ] **Step 1: Write the failing live scenarios**

Append to `tests/test_library_live.py` (reuse its `serve`, `admin`, `pwa`, `_open_projects`, `shot`, seed rows PIANO/`run-kate`/`prj-piano`):

```python
def scenario_setup_sheet_lands_active():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.wait_for_selector('[data-project-add]', timeout=15000)
        page.locator('[data-project-add]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        page.locator('#cc-choice-modal button', has_text='Program').click()
        page.wait_for_selector('[data-setup-sheet]', timeout=10000)
        page.locator('[data-setup-who]').select_option('sam')
        page.locator(f'[data-setup-pick="{DRUMS}"]').click()
        page.wait_for_selector('[data-setup-slot]', timeout=10000)
        n = page.locator('[data-setup-slot]').count()
        check(n >= 1, "the app proposed days once who and which are chosen")
        page.locator('[data-setup-slot]').first.locator('[data-slot-day]').select_option('4')
        page.locator('[data-setup-start]').click()
        page.wait_for_selector('[data-setup-sheet]', state='detached', timeout=15000)
        from services import storage
        run = next(r for r in storage.get_programs(include_finished=True) if r['member_id'] == 'sam' and r['library_id'] == DRUMS and r['project_id'] == 'prj-piano')
        check(run['state'] == 'active' and run['emissions']['commitment_ids'], f"one pass, active: {run['state']}")
        shot(page, 'setup-sheet-active')


def scenario_setup_preview_failure_shows_retry():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.route('**/api/programs/preview-slots', lambda route: route.fulfill(status=500, body='{}'))
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        page.locator('[data-project-add]').click()
        page.locator('#cc-choice-modal button', has_text='Program').click()
        page.locator(f'[data-setup-pick="{DRUMS}"]').click()
        page.wait_for_selector('[data-setup-retry]', timeout=10000)
        check("Couldn't look at the week" in page.locator('[data-setup-sheet]').inner_text(), "the failure is said, with Retry")


def scenario_monitoring_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'projects?id=prj-piano&piece=program:run-kate'), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"] [data-monitor-stats]', timeout=15000)
        sheet = page.locator('[data-record-sheet]')
        text = sheet.inner_text()
        for word in ('Re-shape', 'claim', 'footprint', 'ready to judge', 'rotation'):
            check(word not in text, f"no '{word}' on the sheet")
        check(page.locator('[data-reached-it]').count() == 2, "Reached it on every unjudged phase (P2)")
        check(page.locator('[data-rung-current]').count() == 1, "one lit rung")
        check(sheet.locator('button:visible').count() <= 8, f"a monitoring sheet, not a button wall: {sheet.locator('button:visible').count()}")
        page.locator('[data-run-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Change the days', 'Program settings', 'Log a session', 'Start a session', 'Look again', 'Plan without the book', 'Pause', 'Done with it', 'Drop', 'Delete'):
            check(any(want in l for l in labels), f"⋯ holds {want}: {labels}")
        page.keyboard.press('Escape')
        shot(page, 'monitor-sheet')


def scenario_change_the_days_from_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'projects?id=prj-piano&piece=program:run-kate'), wait_until='load')
        page.wait_for_selector('[data-run-menu]', timeout=15000)
        page.locator('[data-run-menu]').click()
        page.locator('#cc-choice-modal button', has_text='Change the days').click()
        page.wait_for_selector('[data-days-editor] [data-setup-slot]', timeout=10000)
        page.locator('[data-days-editor] [data-setup-slot]').first.locator('[data-slot-day]').select_option('6')
        page.locator('[data-days-save]').click()
        page.wait_for_selector('[data-days-editor]', state='detached', timeout=10000)
        from services import storage
        check(6 in storage.get_program('run-kate')['shape']['preferred_days'], "the days changed in one write")
```

Seed note: `run-kate` in `seed()` must carry `emissions.commitment_ids` claimed on real commitments for the Change-the-days scenario (approve it in `seed()` through `programs.approve('run-kate', 'mom', slots=[...])` after `storage.update_settings`, or create the commitments by hand as `_emit_commitments` does). Add one dad/aunt-free `prj-piano` row if missing.

- [ ] **Step 2: Run to see them fail.** Run: `python tests/test_library_live.py` — the new scenarios fail on `[data-setup-sheet]` / `[data-monitor-stats]` absent; the older scenarios must stay green at the end.

- [ ] **Step 3: Build the setup sheet**

`templates/components/program_setup_sheet.html`, one Alpine island `programSetup()` mounted once per host (include it in `projects.html`, `work.html`, `library.html` and `app.html` next to the record sheet / piece sheets; it listens on `window` for `chf-program-setup-open`). Markup (same frame as the record sheet: `fixed inset-0 z-[82] bg-black/40`, panel `bg-gray-800 md:w-[40rem]`):

```html
<div x-data="programSetup()" x-show="open" x-cloak data-setup-sheet @chf-program-setup-open.window="start($event.detail)" @keydown.escape.window="close()" @click.self="close()"
     class="fixed inset-0 z-[83] bg-black/40 flex justify-end items-end md:items-stretch">
  <div role="dialog" aria-modal="true" class="bg-gray-800 w-full md:w-[40rem] h-[88vh] md:h-full overflow-y-auto border-t md:border-l border-gray-700 rounded-t-2xl md:rounded-none flex flex-col">
    <div class="sticky top-0 z-10 bg-gray-800 border-b border-gray-700 px-4 py-3 flex items-center gap-3">
      <h2 class="flex-1 text-lg font-extrabold text-white">New program</h2>
      <button type="button" @click="close()" aria-label="Close" class="w-8 h-8 rounded-full bg-gray-900 text-white font-bold">✕</button>
    </div>
    <div class="px-4 py-3 space-y-4">
      <p class="text-xs text-red-300" x-show="error" x-text="error" role="status"></p>
      <!-- 1 Who -->
      <section class="space-y-1.5">
        <div class="text-xs font-bold text-gray-300">1 · Who is doing it</div>
        <select data-setup-who x-model="forMemberId" @change="onWho()" :disabled="!!(isChild() || runId)" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-2 py-2 text-gray-100 text-sm">
          <template x-for="m in members" :key="m.id"><option :value="m.id" x-text="m.name + (bands[m.id] ? ' · ' + bandLabel(bands[m.id]) : '')"></option></template>
        </select>
      </section>
      <!-- 2 Which program -->
      <section class="space-y-1.5" x-show="!runId">
        <div class="text-xs font-bold text-gray-300">2 · Which program</div>
        <p class="text-xs text-gray-500 italic" x-show="!libraryLoaded">Loading the library…</p>
        <template x-for="lp in library" :key="lp.id">
          <button type="button" :data-setup-pick="lp.id" @click="pick(lp)" :aria-pressed="libraryId === lp.id"
                  class="w-full text-left bg-gray-900 border rounded-lg px-2.5 py-1.5" :class="libraryId === lp.id ? 'border-teal-500' : 'border-gray-800'">
            <span class="block text-xs font-semibold text-gray-200" x-text="lp.title"></span>
            <span class="block text-[11px] text-gray-500" x-text="chfLibrary.madeFor(lp) + (chfLibrary.runnersLine(lp) ? ' · ' + chfLibrary.runnersLine(lp) : '')"></span>
          </button>
        </template>
        <template x-if="!isChild() && !making"><button type="button" data-setup-make-new @click="making = true" class="w-full text-left text-xs font-bold px-2.5 py-2 rounded-lg bg-gray-900 text-teal-300 border border-dashed border-gray-700">+ Make a new one</button></template>
        <template x-if="making">
          <div data-setup-new class="space-y-2 border-t border-gray-800 pt-2">
            {{ library_profile_fields('draft', 'ageBands') }}
          </div>
        </template>
        <label class="block text-xs text-gray-400">Where they're starting from (optional)
          <input x-model="startingPoint" placeholder="What they can already do" class="w-full bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-gray-100 text-sm">
          <span class="block text-[11px] text-gray-500 mt-0.5" x-text="'stays private to ' + forName() + '\'s program'"></span>
        </label>
      </section>
      <!-- 3 Days and times -->
      <section class="space-y-1.5" x-show="libraryId || making || runId">
        <div class="text-xs font-bold text-gray-300">3 · Days and times</div>
        <p class="text-xs text-gray-500" x-show="!previewFailed">The app looked at the week. Change any of these; empty the list and it picks again.</p>
        <div x-show="previewFailed" class="flex items-center gap-2 text-xs text-amber-300"><span>Couldn't look at the week.</span><button type="button" data-setup-retry @click="preview()" class="text-xs font-bold px-2.5 py-1 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">Retry</button></div>
        <label class="text-xs text-gray-400">Minutes each <input data-setup-minutes type="number" min="5" max="240" x-model.number="minutes" class="w-20 bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-gray-100 text-sm"></label>
        <template x-for="(s, i) in slots" :key="i">
          <div data-setup-slot class="flex items-center gap-2">
            <select data-slot-day x-model.number="s.day" class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-gray-100 text-sm"><template x-for="d in 7" :key="d"><option :value="d - 1" x-text="['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][d - 1]"></option></template></select>
            <input data-slot-time type="time" x-model="s.time_start" class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-gray-100 text-sm">
            <button type="button" @click="slots.splice(i, 1)" aria-label="Remove this time" class="text-xs text-gray-500">✕</button>
          </div>
        </template>
        <div class="flex flex-wrap gap-2 items-center">
          <button type="button" data-setup-add-time @click="slots.push({day: 0, time_start: '19:00'})" :disabled="!!(slots.length >= 7)" class="text-xs font-bold px-2.5 py-1 rounded-lg bg-gray-800 text-gray-300 border border-gray-700">+ Add a time</button>
          <label class="text-xs text-gray-400">Aim for a date (optional) <input type="date" x-model="targetDate" class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1 text-gray-100 text-sm"></label>
        </div>
      </section>
      <button type="button" data-setup-start @click="start_()" :disabled="!!(busy || !(libraryId || making || runId))"
              class="w-full text-sm font-bold px-3 py-3 rounded-lg bg-teal-700 text-white active:bg-teal-800 disabled:opacity-50"
              x-text="busy ? (making ? 'Looking for a real plan…' : 'Starting…') : (isChild() ? 'Ask to start the program' : 'Start the program')"></button>
      <p class="text-[11px] text-gray-500" x-text="'Puts these times on ' + forName() + '\'s calendar as practice. You can change them any time from the program\'s ⋯.'"></p>
    </div>
  </div>
</div>
```

Island (same file): `open, busy, error, projectId, forMemberId, libraryId, runId, making, draft{title, age_band, minutes, sessions_per_week, assumes}, startingPoint, slots, minutes, targetDate, members, bands, ageBands, library, libraryLoaded, previewFailed`; `start(detail)` loads `api/members` and `api/library?include_archived=false` (as `projectsPage.loadLibrary` does), sets fields from `detail` (`projectId, forMemberId, libraryId, runId`), and when `runId` is given loads the run's shape/slots as the editor's starting rows; `pick(lp)` sets `libraryId`, `minutes = lp.made_for.minutes` and calls `preview()`; `preview()` POSTs `api/programs/preview-slots {member_id: forMemberId, library_id, minutes, sessions_per_week: making ? draft.sessions_per_week : undefined, preferred_days}` and sets `slots`, or `previewFailed = true`; `start_()`: with `runId` → `PATCH api/programs/{runId}/schedule {slots}` then `POST …/approve {slots}` if the run is proposed (Task 7's DM-card path); else `POST api/programs` with `{library_id | title+age_band+minutes+sessions_per_week+assumes (making), for_member_id, member_id: myId, starting_point, slots: slots.map(s => ({day: s.day, time_start: s.time_start})), minutes, target_date, project_id, activate: true}`; on success `window.dispatchEvent(new CustomEvent('chf-projects-open'))`, `showGlobalAlert(message)` when the server says it stayed proposed, close. `window.chfProgramSetup = {open: detail => window.dispatchEvent(new CustomEvent('chf-program-setup-open', {detail}))}`.

`projects_page.html`: `addPieceKind(p, 'program')` → `window.chfProgramSetup.open({projectId: p.id, forMemberId: this.myId})`; delete `loadLibrary`, `libraryBand`, `pickLibrary`, `togglePieceDay` and the `program` branch of `createPiece` and the `emptyPieceForm` program fields; delete the program `<form>` in `project_piece_forms.html` (lines 55–107) and its macro import if unused. The phone's `app.html` Add a piece › Program (grep `addPieceKind\|pieceForm.*program`) opens the same event.

- [ ] **Step 4: Redraw the monitoring sheet**

In `programs_page.html` sheet mode (the `{% if _sheet %}` body): replace the under-way block (~677–728) and the per-phase blocks (~480–520) with:

1. Header: title; line `memberName · daysLine(p) · minutes + ' min' · ` + a `data-library-link` button "in the library ›"; one muted line when `tier(p) === 'generated'` ("Made by the app") or `'none'` ("Practice time only · " + reason); ⋯ button `data-run-menu` → `menu(p)`.
2. `[data-monitor-stats]` from `GET api/programs/{id}/monitor` (loaded in `onSheet` beside `load()`; store `monitor[p.id]`): "last practised {weekday or date}" · "{n} sessions this week" (P1, never "of") · "next {Weekday HH:MM}" · "{total} sessions, {h} h {m} min".
3. For each `monitor.phases[]`: heading "{name} · done when {milestone}", a progression line when set, `[data-reached-it="id"]` Reached it button on every phase without `milestone_hit_at` (P2) calling today's `markMilestone(p, ph)`; a ladder: `<ol>` of `[data-rung="lesson id"]` rows, done ones struck, the current one with `[data-rung-current]` and the text "Session A ✓ · B next" built from `logged_variants` and `next_variant`; the current rung carries "Another session on this" / "Move on" (today's `moveUnit(p, 'back'|'next')`); tapping a rung opens `lessonSheet(p, lesson)` (a small inline panel: steps, Preview via `playLesson` with the lesson id and variant, the url) — no bookmark control there. When `monitor.ready_to_judge`, the lit rung's line reads "every lesson done — reached it?".
4. "Session log · N · Show" folded: rows `when (logged on {logged_on} when different) · minutes · lesson_title variant · source`, each with `[data-session-remove]` → `promptConfirm('Remove this session?', …)` → `DELETE api/programs/{id}/sessions/{sid}` → reload.
5. The legacy branch (`!p.library_id`, ~326) stays as is.
6. `menu(p)` → `promptChoice(p.title, '', items)` with, in order and gated: `Change the days` (active/paused) → `changeDays(p)`; `Program settings` → `settings(p)`; `Log a session` → today's `sessionOpen` toggle; `Start a session` → `startSession(p)`; `Look again` → `lookAgain(p)`; `Plan without the book` (when `p.source.book_spine`) → `replanWithoutBooks(p)`; `Pause`/`Resume`; `Done with it` → `finishProgram(p)`; `Drop` → `dropProgram(p)`; `Delete` (when `canDeleteRun(p)`) → `deleteRun(p)`.
   - `changeDays(p)`: opens `[data-days-editor]` inline (same rows as the setup sheet's part 3: `[data-setup-slot]`, `[data-slot-day]`, `[data-slot-time]`, add/remove, `[data-days-save]`) seeded from `p.shape.slots` (else `paused_slots`, else the preview route); Save → `PATCH api/programs/{id}/schedule {slots}`; the response's `message` is shown; reload.
   - `settings(p)`: `promptInput` chain or a small inline form for `starting_point`, `minutes`, `target_date` → `POST api/programs/{id}/edit` — **that route refuses non-proposed runs today** (`main.py` ~8147: 'Only a proposal can be edited…'); change it to accept exactly `starting_point`, `minutes`, `target_date` on an active or paused run (write `shape.minutes` via `clamp_shape`, `starting_point`, `baseline.target_date`; `recurate`, `library_id`, `slots`, `preferred_days`, `sessions_per_week` keep the proposed-only rule), with a scenario in `tests/test_programs_endpoints.py`.
   - `startSession(p)`: `promptChoice('Which session?', '', windows)` over the next 14 days' windows of this run (`GET api/practice-windows`), then today's `playLesson` path for that window (lesson id + variant + `slot_date`), exactly what the phone's Start does (v2.499.630).
   - `lookAgain` / `replanWithoutBooks` keep their confirms, which must say: a new library program, progress starts over, scripts regenerate (P4).
7. The proposed block keeps its footprint panel, "Not these times?" editor and Approve; copy per spec §8: heading "What it adds to the week", button **Approve** with the footnote "Puts these times on {name}'s calendar"; line ~602 and `canApprove()` become adult-or-parent (P5): `canApprove() { return !this.myId || this.iAmParent() || this.iAmAdult(); }` with `iAmAdult()` reading `members`.
8. Delete lines 19–78 (the unreachable propose form) and the now-unused `proposeProgram`, `draft`, `toggleDay`, `creating` state; keep `Re-shape the week`'s handler out (route gone): remove `reshapeProgram` and its button.

Run `python tools/build_tailwind.py`.

- [ ] **Step 5: Run the gate**

Run: `python tests/test_library_live.py; python tests/test_programs_endpoints.py; python tests/test_programs_reachable.py; python tests/test_projects_detail_live.py; python tests/test_project_sheets_phone_live.py; python tests/test_library_scripts_live.py; python tests/test_program_setup.py`
`test_programs_reachable` parses inline scripts with node: keep every `<script>` parseable. Expected: PASS; look at `setup-sheet-active.png` and `monitor-sheet.png` against the brainstorm mockup `.superpowers/brainstorm/56101-1792548799/content/program-setup.html`.

- [ ] **Step 6: Commit**

```bash
git add chauffeur/templates chauffeur/static/tailwind.css chauffeur/main.py chauffeur/tests chauffeur/config.yaml
git commit -m "feat(programs): one-pass setup sheet (who, which, days and times, Start the program) replaces Add a piece's program form on both hosts; the admin run sheet is monitoring - stats, the ladder with the lit rung and Reached it on every unjudged phase, the session log folded with Remove, and one ... menu (Change the days, Program settings, Log a session, Start a session, Look again, Plan without the book, Pause/Resume, Done with it, Drop, Delete); adults approve; the dead propose form and Re-shape are gone (vX.Y.Z)"
```

---

## Half B — library

### Task 5: Library revision, summary, origin, one commit path (Codex)

**Files:**
- Modify: `services/library.py` (`_write` → `_commit`; `add_lesson(after=)`; `update_phase`; whitelists; archived refusal; `runners` gains `run_id`), `services/storage.py:3786` (allow `revision`), `models/schemas.py:765` (`revision: int = 0`), `services/migrations.py` (`migrate_library_revision_summary_v2499`), `services/library_scripts.py` (claims carry `revision`; `_run` reloads the lesson), `services/access_readers.py`
- Test: `tests/test_library_model.py` (extend), `tests/test_library_scripts.py` (extend)

**Interfaces:**
- Produces: library rows carry `revision: int` (migration 0; every successful write bumps by 1 and `updated_at`), `lessons[].summary: str`, `lessons[].origin: 'cited'|'generated'|'none'`; `library._commit(library_id, candidate_row, actor, *, expect_revision=None) -> {'status': 'success', 'program': row} | {'status': 'error', 'code': 403|404|409, 'message'} | {'status': 'error', 'message'}` (validates with `valid_curriculum`, refuses archived rows except for `archive`/un-archive writes, reconciles every run once, bumps `revision`); the hand functions (`update`, `add_lesson(library_id, fields, actor, after=None)`, `update_lesson`, `remove_lesson`, `order_lessons`, new `update_phase(library_id, phase_id, fields, actor)` with fields `name|milestone|what|progression`) build a candidate and call `_commit`; `add_lesson`/`update_lesson` keep `summary` and `origin`; `library.runners(library_id, viewer)['named'][i]['run_id']`; `library_scripts.write(...)` queues pairs with `(lesson_id, label, revision)` and `_run` reloads the lesson from the current row before `generate_script`, dropping a pair whose lesson vanished and re-queuing a pair whose row revision moved (one extra pass, then stop); `storage.claim_library_script(library_id, slot, revision=None)` records `revision` on the row and `commit_library_script` refuses when the row's library `revision` moved since the claim (returns `''`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_library_model.py`; read its helpers first: `_fresh()`, `_library(title=, created_by='aunt', ...)` whose creator is Aunt, `_project(owner=, title=, audience=)`, `MOM`; define `def _phase(lid): return storage.get_library_program(lid)['phases'][0]['id']` if absent; `library` here is the service module):

```python
def scenario_revision_bumps_on_every_write():
    _fresh(); lid = _library('Piano')
    r0 = storage.get_library_program(lid).get('revision', 0)
    library.update(lid, {'title': 'Piano basics'}, MOM)
    r1 = storage.get_library_program(lid)['revision']
    library.add_lesson(lid, {'phase_id': _phase(lid), 'title': 'New'}, MOM)
    r2 = storage.get_library_program(lid)['revision']
    check(r1 == r0 + 1 and r2 == r1 + 1, f"revision counts writes: {r0} {r1} {r2}")
    res = library._commit(lid, storage.get_library_program(lid), MOM, expect_revision=r0)
    check(res['status'] == 'error' and res['code'] == 409, f"a stale expectation is refused: {res}")


def scenario_add_lesson_after_and_update_phase():
    _fresh(); lid = _library('Piano')
    ph = _phase(lid)
    ids = [l['id'] for l in storage.get_library_program(lid)['lessons'] if l['phase_id'] == ph]
    res = library.add_lesson(lid, {'phase_id': ph, 'title': 'Duet', 'summary': 'She plays the tune, you play chords.'}, MOM, after=ids[0])
    lessons = [l for l in storage.get_library_program(lid)['lessons'] if l['phase_id'] == ph]
    check(res['status'] == 'success' and lessons[1]['title'] == 'Duet' and lessons[1]['summary'].startswith('She plays'), f"placed after: {[l['title'] for l in lessons]}")
    res = library.update_phase(lid, ph, {'milestone': 'plays Twinkle both hands', 'progression': 'one less reminder'}, MOM)
    phase = next(p for p in storage.get_library_program(lid)['phases'] if p['id'] == ph)
    check(res['status'] == 'success' and phase['milestone'] == 'plays Twinkle both hands' and phase['progression'] == 'one less reminder', f"phase updated: {phase}")
    check(library.update_phase(lid, 'nope', {'milestone': 'x'}, MOM)['status'] == 'error', "unknown phase")


def scenario_archived_refuses_every_edit():
    _fresh(); lid = _library('Piano')
    library.archive(lid, MOM)
    for res in (library.update(lid, {'title': 'x'}, MOM), library.add_lesson(lid, {'phase_id': _phase(lid), 'title': 'x'}, MOM),
                library.order_lessons(lid, [l['id'] for l in storage.get_library_program(lid)['lessons']], MOM)):
        check(res['status'] == 'error' and 'archived' in res['message'].lower(), f"archived: {res}")


def scenario_migration_fills_summary_and_origin():
    _fresh(); lid = _library('Piano')
    row = storage.get_library_program(lid)
    storage.library_programs_table.update({'lessons': [{k: v for k, v in l.items() if k not in ('summary', 'origin')} for l in row['lessons']],
                                           'revision': None}, storage.Query().id == lid)
    from services import migrations
    migrations.migrate_library_revision_summary_v2499()
    row = storage.get_library_program(lid)
    check(row['revision'] == 0 and all(l.get('summary') and l.get('origin') == row['source']['origin'] for l in row['lessons']), f"filled: {row['lessons'][0]}")
    check('session' in row['lessons'][0]['summary'], f"the summary names the session count: {row['lessons'][0]['summary']}")


def scenario_runners_carry_run_id():
    _fresh(); lid = _library('Piano'); pid = _project(owner='kid', title='Piano for Kate', audience='household')
    rid = programs.create_row({'member_id': 'kid', 'library_id': lid, 'shape': {}, 'created_by': 'mom', 'starting_point': '',
                               'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}, project_id=pid)
    named = library.runners(lid, MOM)['named']
    check(named and named[0]['run_id'] == rid, f"a visible runner names its run: {named}")
```
And in `tests/test_library_scripts.py`: `scenario_claim_bound_to_revision` — claim a slot, bump the row (`library.update(lid, {'title': 'x'}, MOM)`), `commit_library_script` with the old token returns `''`; `scenario_run_reloads_lessons` — queue `write` with a stub `generate_script` that records the lesson title it received, update the lesson title between queue and run (patch `threading.Thread` to run synchronously after the update), assert the new title was used.

- [ ] **Step 2: Run to see them fail.** `python tests/test_library_model.py; python tests/test_library_scripts.py`.

- [ ] **Step 3: Implement**

`models/schemas.py` `LibraryProgram`: `revision: int = 0`. `storage.update_library_program`: add `'revision'` to `allowed`. Migration:

```python
def migrate_library_revision_summary_v2499():
    """Library rows gain a revision counter and every lesson a parent-facing summary and its origin (programs spec §6)."""
    if storage.get_app_state('library_revision_summary_v2499'):
        return
    for row in storage.get_library_programs():
        origin = (row.get('source') or {}).get('origin') or 'none'
        lessons = []
        for l in row.get('lessons') or []:
            n = int(l.get('sessions') or 1)
            first = (l.get('steps') or [''])[0]
            summary = l.get('summary') or ((first + '. ' if first else '') + f"{n} session{'s' if n != 1 else ''}.")
            lessons.append({**l, 'summary': summary, 'origin': l.get('origin') or origin})
        storage.update_library_program(row['id'], {'lessons': lessons, 'revision': int(row.get('revision') or 0)})
    storage.set_app_state('library_revision_summary_v2499', time.time())
```
Chain after the session-id migration; INTERNAL row.

`library.py`: rename `_write` to `_commit(library_id, candidate, actor, *, expect_revision=None)` taking a full candidate row instead of a change callable; inside the lock: 404/403 as before; `if expect_revision is not None and int(before.get('revision') or 0) != int(expect_revision): return {'status': 'error', 'code': 409, 'message': 'The program changed; read it again.'}`; `if before.get('archived') and candidate.get('archived') is not False: return {'status': 'error', 'message': 'This program is archived.'}` (un-archive is the one write an archived row accepts); `valid_curriculum`; write with `revision = before.revision + 1`; reconcile runs once; invalidate. Keep a thin `_write(library_id, actor, change)` wrapper that deep-copies, applies `change`, and calls `_commit`, so the existing hand functions change minimally. `add_lesson(library_id, fields, actor, after=None)`: insert after the lesson id when given (same phase), else append; whitelists gain `summary`, `origin`. `update_phase` as specified. `runners`: include `'run_id': run['id']` on named entries.

`library_scripts.py`: `write` captures `rev = int(row.get('revision') or 0)` and queues `(lesson, label, rev)`; `_run` for each pair: `row = storage.get_library_program(library_id)`; `lesson = next((l for l in row['lessons'] if l['id'] == queued['id']), None)`; skip if None; if `row.revision != rev` and this pair has not been retried: requeue once with the fresh revision; call `generate_script(row, lesson, label, settings)` with the fresh lesson. `storage.claim_library_script(library_id, slot, revision=None)` stores `revision` on the script row; `commit_library_script` reads the library row's current `revision` and returns `''` when it differs from the claim's. (`generate_script` passes the row's `revision` to the claim.)

- [ ] **Step 4: Run to green, then neighbours**

Run: `python tests/test_library_model.py; python tests/test_library_scripts.py; python tests/test_library_flows.py; python tests/test_library_cutover.py; python tests/test_library_migration.py; python tests/test_library_migration_edges.py; python tests/test_programs_endpoints.py; python tests/test_access_register.py`
Expected: PASS.

- [ ] **Step 5: Hand back.**

---

### Task 6: Steer (Codex)

**Files:**
- Create: `services/library_steer.py`
- Modify: `main.py` (new `POST /api/library/{id}/steer`), `services/access_readers.py`, `services/library_scripts.py` (`stale`), `services/library.py` (`_script_view` exposes `stale`)
- Test: `tests/test_library_steer.py` (new)

**Interfaces:**
- Consumes: `library._commit(library_id, candidate, actor, expect_revision=)`, `library.can_edit`, `valid_curriculum`, `programs_curate._clean_steps(raw, aim)`, `_clean_line(raw, aim, cap)`, `screen_starting_point`, `library.runners(library_id, viewer)`, `model_pools.call_pool_json(tier, api_key, system, prompt, timeout_s=, settings=, paid_ok=False)`, `library_scripts.write(library_id, actor, lesson_id=, variant_label=)`, `storage.get_library_script`, `storage.edit_library_script`.
- Produces: `library_steer.plan(row, text, settings) -> {'edits': [...], 'said': str} | {'error': str}` (one model call, free chain); `library_steer.apply(library_id, text, actor, expect_revision) -> {'status': 'success', 'program': row, 'changes': [str], 'said': str} | {'status': 'error', 'code'?, 'message'}` (candidate → screens → provenance → `_commit` → scripts); `POST /api/library/{id}/steer` body `{text, revision}` → that dict (`_library_result`); script rows gain `stale: bool`; `library._script_view` reports `stale` and the chip text `'edited by hand · may be out of date'` is the template's concern.

Supported ops (exact): `update_profile {fields: {title?, age_band?, minutes?, sessions_per_week?, assumes?}}`, `update_phase {phase_id, fields: {name?, milestone?, what?, progression?}}`, `add_lesson {phase_id, after: lesson_id|null, fields: {title, sessions?, steps?, body?, url?, variants?, summary?}}`, `update_lesson {lesson_id, fields: {title?, sessions?, steps?, body?, url?, variants?, summary?}}`, `remove_lesson {lesson_id}`, `order_lessons {ids}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Steer: one validated candidate committed once with a server-computed change list (spec §2).
Run from chauffeur/: python tests/test_library_steer.py"""
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, library, library_steer, programs, library_scripts
from test_library_model import _fresh, _library, _project, MOM   # read that file: _library(title, created_by, minutes, sessions_per_week, b_sessions), _project(owner, title, audience)
AUNT = {'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True}


def _phase(lid):
    return storage.get_library_program(lid)['phases'][0]['id']


def _plan(edits, said='Changed.'):
    return lambda *a, **k: {'edits': edits, 'said': said}


def _row(lid):
    return storage.get_library_program(lid)


def scenario_steer_applies_one_candidate_with_a_change_list():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    edits = [{'op': 'update_lesson', 'lesson_id': ids[0], 'fields': {'sessions': 2}},
             {'op': 'add_lesson', 'phase_id': ph, 'after': ids[0], 'fields': {'title': 'Duet with a parent', 'sessions': 1, 'steps': ['play the tune'], 'summary': 'She plays the tune, you play the chords. 1 session.'}},
             {'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'plays Twinkle both hands'}}]
    with patch.object(library_steer, 'plan', _plan(edits)):
        res = library_steer.apply(lid, 'shorter scales, add a duet', MOM, _row(lid)['revision'])
    row = _row(lid)
    check(res['status'] == 'success' and row['revision'] == 1, f"committed once: {res.get('message')} rev={row['revision']}")
    titles = [l['title'] for l in row['lessons'] if l['phase_id'] == ph]
    check(titles[1] == 'Duet with a parent', f"placed after: {titles}")
    check(any('sessions' in c and '2' in c for c in res['changes']) and any('Duet with a parent' in c for c in res['changes'])
          and any('plays Twinkle both hands' in c for c in res['changes']), f"the change list names each move: {res['changes']}")
    duet = next(l for l in row['lessons'] if l['title'] == 'Duet with a parent')
    check(duet['origin'] == 'generated' and duet['summary'].startswith('She plays'), f"provenance and summary: {duet}")


def scenario_refusal_writes_nothing():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    before = _row(lid)
    edits = [{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'x'}}, {'op': 'remove_lesson', 'lesson_id': 'nope'}]
    with patch.object(library_steer, 'plan', _plan(edits)):
        res = library_steer.apply(lid, 'x', MOM, before['revision'])
    check(res['status'] == 'error' and _row(lid) == before, f"a bad edit aborts the whole steer: {res}")


def scenario_steer_empties_a_phase():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    with patch.object(library_steer, 'plan', _plan([{'op': 'remove_lesson', 'lesson_id': i} for i in ids])):
        res = library_steer.apply(lid, 'remove them all', MOM, _row(lid)['revision'])
    check(res['status'] == 'error' and len(_row(lid)['lessons']) == len(ids) + len([l for l in _row(lid)['lessons'] if l['phase_id'] != ph]) - 0 and 'phase' in res['message'].lower(),
          f"a phase cannot be emptied: {res}")


def scenario_remove_then_add_in_one_steer_is_fine():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    edits = [{'op': 'remove_lesson', 'lesson_id': i} for i in ids] + [{'op': 'add_lesson', 'phase_id': ph, 'after': None, 'fields': {'title': 'Fresh start', 'steps': ['a']}}]
    with patch.object(library_steer, 'plan', _plan(edits)):
        res = library_steer.apply(lid, 'start over', MOM, _row(lid)['revision'])
    check(res['status'] == 'success' and [l['title'] for l in _row(lid)['lessons'] if l['phase_id'] == ph] == ['Fresh start'], f"validated once at the end: {res}")


def scenario_content_screens_refuse_loads():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    with patch.object(library_steer, 'plan', _plan([{'op': 'add_lesson', 'phase_id': ph, 'after': None, 'fields': {'title': 'Heavy', 'steps': ['bench 100 kg for 5']}}])):
        res = library_steer.apply(lid, 'add lifting', MOM, _row(lid)['revision'])
    check(res['status'] == 'error' and not any(l['title'] == 'Heavy' for l in _row(lid)['lessons']), f"a load prescription never lands: {res}")


def scenario_concurrent_steers():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    rev = _row(lid)['revision']
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'a'}}])):
        a = library_steer.apply(lid, 'a', MOM, rev)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'b'}}])):
        b = library_steer.apply(lid, 'b', MOM, rev)
    check(a['status'] == 'success' and b['status'] == 'error' and b['code'] == 409 and next(p for p in _row(lid)['phases'] if p['id'] == ph)['milestone'] == 'a',
          f"the second steer on a stale revision is refused: {b}")


def scenario_change_list_names_visible_runners_only():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    seen = _project(owner='kid', title='Piano for Kate', audience='household'); hidden = _project(owner='dad', title='Secret', audience='private')
    base = {'library_id': lid, 'shape': {}, 'created_by': 'mom', 'starting_point': '', 'baseline': {'start_date': None, 'target_date': None, 'target_event_id': None, 'rebaselined_at': None, 'rebaselines': 0}}
    programs.create_row({**base, 'member_id': 'kid'}, project_id=seen)
    programs.create_row({**base, 'member_id': 'dad', 'created_by': 'dad'}, project_id=hidden)
    first = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph][0]
    with patch.object(library_steer, 'plan', _plan([{'op': 'remove_lesson', 'lesson_id': first}])):
        res = library_steer.apply(lid, 'drop the first', AUNT, _row(lid)['revision'])
    text = ' '.join(res['changes'])
    check('Kate' in text and 'Dad' not in text and '1 more' in text, f"runners through the visible projection: {res['changes']}")


def scenario_scripts_regenerated_hand_edits_kept_stale():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    ids = [l['id'] for l in _row(lid)['lessons'] if l['phase_id'] == ph]
    storage.edit_library_script(lid, {'lesson_id': ids[0], 'variant_label': ''}, {'scenes': [{'type': 'say', 'text': 'hi'}]})
    storage.claim_library_script(lid, {'lesson_id': ids[1], 'variant_label': ''})
    storage.commit_library_script(lid, {'lesson_id': ids[1], 'variant_label': ''}, storage.get_library_script(lid, {'lesson_id': ids[1], 'variant_label': ''})['claim'],
                                  {'scenes': [{'type': 'say', 'text': 'gen'}], 'origin': 'generated', 'minutes': 10})
    queued = []
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_lesson', 'lesson_id': ids[0], 'fields': {'steps': ['new a']}},
                                                     {'op': 'update_lesson', 'lesson_id': ids[1], 'fields': {'steps': ['new b']}}])), \
         patch.object(library_scripts, 'write', lambda lid_, actor, lesson_id=None, variant_label='': queued.append(lesson_id) or {'status': 'ok', 'job': None}):
        res = library_steer.apply(lid, 'rewrite steps', MOM, _row(lid)['revision'])
    hand = storage.get_library_script(lid, {'lesson_id': ids[0], 'variant_label': ''})
    gen = storage.get_library_script(lid, {'lesson_id': ids[1], 'variant_label': ''})
    check(res['status'] == 'success' and hand['edited'] and hand['scenes'] and hand.get('stale'), f"a hand edit stays, marked stale: {hand}")
    check(gen is None or not gen.get('scenes'), "a generated script is dropped for rewriting")
    check(ids[1] in queued and ids[0] not in queued, f"only the generated one is re-queued: {queued}")


def scenario_child_and_archived_refused():
    _fresh(); lid = _library('Piano')
    with patch.object(library_steer, 'plan', _plan([])):
        check(library_steer.apply(lid, 'x', KID, 0)['status'] == 'error', "a child cannot steer")
        library.archive(lid, MOM)
        check(library_steer.apply(lid, 'x', MOM, _row(lid)['revision'])['status'] == 'error', "archived refused")


def scenario_http_route():
    _fresh(); lid = _library('Piano'); ph = _phase(lid)
    import main
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    with patch.object(library_steer, 'plan', _plan([{'op': 'update_phase', 'phase_id': ph, 'fields': {'milestone': 'z'}}])):
        r = c.post(f'/api/library/{lid}/steer', json={'text': 'z', 'revision': _row(lid)['revision']}, headers={'X-Member-Token': storage.create_member_token('mom')})
    check(r.status_code == 200 and r.json()['status'] == 'success' and r.json()['changes'], f"route: {r.text}")
    r = c.post(f'/api/library/{lid}/steer', json={'text': 'z', 'revision': 0}, headers={'X-Member-Token': storage.create_member_token('mom')})
    check(r.status_code == 409, f"stale revision: {r.status_code}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

Read `tests/test_library_model.py` for the real helper names (`_fresh`, `_library`, `_phase`, `_project`, the member dicts); if they differ, import the ones that exist and define the rest locally.

- [ ] **Step 2: Run to see it fail.** `python tests/test_library_steer.py`.

- [ ] **Step 3: Implement `services/library_steer.py`**

```python
"""Steer a library program in words (programs spec §2): one model call proposes an edit plan
over the hand operations; the server builds one candidate, screens every model-authored
word, stamps provenance, commits once with a revision check, and reports a change list it
computed itself. Hand-edited scripts are never rewritten here."""
import copy
import json
import uuid

from services import library, library_scripts, model_pools, programs_curate, storage

OPS = ('update_profile', 'update_phase', 'add_lesson', 'update_lesson', 'remove_lesson', 'order_lessons')
LESSON_FIELDS = ('title', 'sessions', 'steps', 'body', 'url', 'variants', 'summary')
PHASE_FIELDS = ('name', 'milestone', 'what', 'progression')
SYSTEM = ("You revise a practice program for a family. Answer ONLY with JSON: {\"edits\": [...], \"said\": \"one sentence\"}. "
          "Each edit is one of: update_profile{fields}, update_phase{phase_id,fields{name,milestone,what,progression}}, "
          "add_lesson{phase_id,after,fields{title,sessions,steps,body,url,variants,summary}}, update_lesson{lesson_id,fields}, "
          "remove_lesson{lesson_id}, order_lessons{ids}. Use the ids given. Keep lessons that are not mentioned. "
          "Every lesson keeps or gets a one-sentence summary written for the parent, ending with its session count. "
          "Never prescribe loads, doses or body-composition targets.")


def _course_text(row):
    return json.dumps({'title': row.get('title'), 'made_for': row.get('made_for'),
                       'phases': [{'id': p['id'], 'name': p.get('name'), 'milestone': p.get('milestone'), 'what': p.get('what'), 'progression': p.get('progression')} for p in row.get('phases') or []],
                       'lessons': [{k: l.get(k) for k in ('id', 'phase_id', 'title', 'sessions', 'steps', 'summary', 'variants')} for l in row.get('lessons') or []]})


def plan(row, text, settings):
    api_key = (settings or {}).get('llm_gemini_api_key', '')
    res = model_pools.call_pool_json('interactive', api_key, SYSTEM, f"Program:\n{_course_text(row)}\n\nThe person says: {text}",
                                     timeout_s=60, settings=settings, paid_ok=False)
    if not isinstance(res, dict) or res.get('error') or not isinstance(res.get('edits'), list):
        return {'error': (res or {}).get('error') if isinstance(res, dict) else 'no answer'}
    return {'edits': res['edits'], 'said': str(res.get('said') or '').strip()}


def _screen_lesson(fields, aim):
    out = dict(fields)
    if 'steps' in out:
        cleaned = programs_curate._clean_steps(out['steps'], aim)
        if len(cleaned) != len([s for s in out['steps'] if str(s).strip()]):
            raise ValueError('A step was refused (loads, doses or unreadable text).')
        out['steps'] = cleaned
    for key in ('title', 'summary', 'body'):
        if key in out:
            cleaned = programs_curate._clean_line(out[key], aim, 240 if key != 'body' else 2000)
            if not cleaned and str(out[key]).strip():
                raise ValueError(f'The {key} was refused.')
            out[key] = cleaned
    if 'variants' in out:
        vs = []
        for v in out['variants'] or []:
            if not isinstance(v, dict):
                continue
            steps = programs_curate._clean_steps(v.get('steps') or [], aim)
            if len(steps) != len([s for s in v.get('steps') or [] if str(s).strip()]):
                raise ValueError('A session step was refused.')
            vs.append({'label': str(v.get('label') or '').strip(), 'steps': steps, **{k: v[k] for k in ('body', 'url') if v.get(k)}})
        out['variants'] = vs
    if 'sessions' in out:
        out['sessions'] = max(1, min(50, int(out['sessions'] or 1)))
    return out


CONTENT = ('steps', 'body', 'url', 'variants')


def _apply(row, edits):
    """Apply the plan to a copy; raise ValueError on any refusal. Returns (candidate, touched_lesson_ids)."""
    cand = copy.deepcopy(row)
    aim = cand.get('title') or ''
    touched = set()
    by_id = lambda lid: next((l for l in cand['lessons'] if l['id'] == lid), None)
    for e in edits:
        op = e.get('op')
        if op not in OPS:
            raise ValueError(f'Unknown edit {op!r}.')
        if op == 'update_profile':
            f = e.get('fields') or {}
            if 'title' in f:
                s = programs_curate.screen_aim(str(f['title']).strip())
                if not s.get('ok'):
                    raise ValueError(s['message'])
                cand['title'] = str(f['title']).strip()
            made = dict(cand.get('made_for') or {})
            for k in ('age_band', 'minutes', 'sessions_per_week', 'assumes'):
                if k in f:
                    made[k] = f[k]
            cand['made_for'] = library.public_profile(made)
            s = programs_curate.screen_starting_point(cand['made_for']['assumes'])
            if not s.get('ok'):
                raise ValueError(s['message'])
        elif op == 'update_phase':
            ph = next((p for p in cand['phases'] if p['id'] == e.get('phase_id')), None)
            if ph is None:
                raise ValueError('No such phase.')
            for k, v in (e.get('fields') or {}).items():
                if k in PHASE_FIELDS:
                    cleaned = programs_curate._clean_line(v, aim, 240)
                    if not cleaned and str(v).strip():
                        raise ValueError(f'The phase {k} was refused.')
                    ph[k] = cleaned
        elif op == 'add_lesson':
            if not any(p['id'] == e.get('phase_id') for p in cand['phases']):
                raise ValueError('No such phase.')
            f = _screen_lesson({k: v for k, v in (e.get('fields') or {}).items() if k in LESSON_FIELDS}, aim)
            if not f.get('title'):
                raise ValueError('A new lesson needs a title.')
            lesson = {'id': uuid.uuid4().hex, 'phase_id': e['phase_id'], 'steps': [], 'variants': [], 'sessions': 1, 'summary': '', 'origin': 'generated', **f}
            after = e.get('after')
            idx = next((i for i, l in enumerate(cand['lessons']) if l['id'] == after), None) if after else None
            if idx is None:
                last = max((i for i, l in enumerate(cand['lessons']) if l['phase_id'] == e['phase_id']), default=None)
                cand['lessons'].insert(last + 1 if last is not None else len(cand['lessons']), lesson)
            else:
                cand['lessons'].insert(idx + 1, lesson)
            touched.add(lesson['id'])
        elif op == 'update_lesson':
            l = by_id(e.get('lesson_id'))
            if l is None:
                raise ValueError('No such lesson.')
            f = _screen_lesson({k: v for k, v in (e.get('fields') or {}).items() if k in LESSON_FIELDS}, aim)
            if any(k in f for k in CONTENT):
                l['origin'] = 'generated'   # model-authored material never wears a citation (§2 step 4)
                touched.add(l['id'])
            l.update(f)
        elif op == 'remove_lesson':
            if by_id(e.get('lesson_id')) is None:
                raise ValueError('No such lesson.')
            cand['lessons'] = [l for l in cand['lessons'] if l['id'] != e['lesson_id']]
        elif op == 'order_lessons':
            ids = list(e.get('ids') or [])
            by = {l['id']: l for l in cand['lessons']}
            if len(ids) != len(by) or set(ids) != set(by):
                raise ValueError('Choose every lesson once.')
            cand['lessons'] = [by[i] for i in ids]
    for p in cand['phases']:
        if not any(l['phase_id'] == p['id'] for l in cand['lessons']):
            raise ValueError(f"The phase {p.get('name') or ''} would have no lesson left.")
    for l in cand['lessons']:
        l.setdefault('summary', ''); l.setdefault('origin', (cand.get('source') or {}).get('origin') or 'none')
    return cand, touched


def _changes(before, after, library_id, viewer):
    out = []
    if before.get('title') != after.get('title'):
        out.append(f"Renamed to {after.get('title')}")
    if before.get('made_for') != after.get('made_for'):
        out.append('Who it is made for changed: ' + library.made_for_line(after.get('made_for') or {}))
    bp = {p['id']: p for p in before.get('phases') or []}
    for p in after.get('phases') or []:
        old = bp.get(p['id']) or {}
        for k in PHASE_FIELDS:
            if (old.get(k) or '') != (p.get(k) or ''):
                out.append(f"{p.get('name') or 'A phase'} {k} now: {p.get(k)}")
    bl = {l['id']: l for l in before.get('lessons') or []}
    al = {l['id']: l for l in after.get('lessons') or []}
    runners = library.runners(library_id, viewer)
    names_on = {}
    for r in runners.get('named') or []:
        names_on.setdefault(r.get('current'), []).append(r['name'])
    hidden_on = runners.get('hidden_on') or {}
    for lid, l in al.items():
        if lid not in bl:
            prev = None
            ids = [x['id'] for x in after['lessons']]
            i = ids.index(lid)
            if i > 0 and after['lessons'][i - 1]['phase_id'] == l['phase_id']:
                prev = after['lessons'][i - 1]['title']
            out.append(f"+ {l['title']}" + (f" after {prev}" if prev else ''))
            continue
        old = bl[lid]
        if old.get('title') != l.get('title'):
            out.append(f"{old.get('title')} is now {l.get('title')}")
        if int(old.get('sessions') or 1) != int(l.get('sessions') or 1):
            out.append(f"{l['title']}: {old.get('sessions') or 1} sessions → {l.get('sessions') or 1}")
        if any((old.get(k) or '') != (l.get(k) or '') for k in ('steps', 'body', 'url', 'variants', 'summary')):
            out.append(f"{l['title']} reworded")
    for lid, old in bl.items():
        if lid not in al:
            line = f"− {old.get('title')}"
            who = names_on.get(lid) or []
            if who:
                nxt = next((x['title'] for x in after['lessons'] if x['phase_id'] == old['phase_id']), None)
                line += '; ' + ', '.join(who) + (' moves on to ' + nxt if nxt else ' moves on')
            if hidden_on.get(lid):
                line += f" (and {hidden_on[lid]} more affected)"
            out.append(line)
    if [l['id'] for l in before.get('lessons') or []] != [l['id'] for l in after.get('lessons') or [] if l['id'] in bl] and set(bl) == set(al):
        out.append('Lessons reordered')
    return out


def apply(library_id, text, actor, expect_revision):
    row = storage.get_library_program(library_id)
    if not row:
        return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
    if not library.can_edit(row, actor):
        return {'status': 'error', 'code': 403, 'message': library.EDIT_REFUSAL}
    if row.get('archived'):
        return {'status': 'error', 'message': 'This program is archived.'}
    if int(row.get('revision') or 0) != int(expect_revision):
        return {'status': 'error', 'code': 409, 'message': 'The program changed; read it again.'}
    settings = storage.get_settings() or {}
    planned = plan(row, str(text or '').strip(), settings)
    if planned.get('error'):
        return {'status': 'error', 'message': f"Couldn't work out that change ({planned['error']})."}
    try:
        cand, touched = _apply(row, planned['edits'])
    except (ValueError, TypeError, KeyError) as e:
        return {'status': 'error', 'message': f"That change was refused: {e}"}
    res = library._commit(library_id, cand, actor, expect_revision=expect_revision)
    if res.get('status') != 'success':
        return res
    after = res['program']
    # Scripts: generated ones for touched lessons are dropped and re-queued; hand-edited ones are kept and marked stale.
    for lid in touched:
        lesson = next((l for l in after['lessons'] if l['id'] == lid), None)
        if not lesson:
            continue
        for lesson_, label in library_scripts.slots_of({'lessons': [lesson]}):
            slot = {'lesson_id': lid, 'variant_label': label}
            sc = storage.get_library_script(library_id, slot)
            if sc and sc.get('edited'):
                storage.mark_library_script_stale(library_id, slot, True)
            elif sc:
                storage.delete_library_script(library_id, slot)
                library_scripts.write(library_id, actor, lesson_id=lid, variant_label=label)
    return {'status': 'success', 'program': library.get(library_id, actor), 'changes': _changes(row, after, library_id, actor), 'said': planned.get('said') or ''}
```

Add `storage.mark_library_script_stale(library_id, slot, stale: bool)` (sets `stale` on the row under the lock) and clear `stale` in `storage.edit_library_script` (a fresh hand edit is current). `library._script_view` carries `stale`. Route in main.py beside the library lesson routes:

```python
@app.post("/api/library/{id}/steer")
def steer_library_api(id: str, request: Request, body: dict = Body(default={})):
    from services import library_steer
    actor = _library_actor(request)
    if 'revision' not in body:
        raise HTTPException(status_code=400, detail='Send the revision you read.')
    return _library_result(library_steer.apply(id, body.get('text') or '', actor, body['revision']))
```
READERS row with kinds `('program',)` (runners through the visible projection); INTERNAL for `library_steer.plan/_apply/_changes/apply`.

- [ ] **Step 4: Run to green, then neighbours**

Run: `python tests/test_library_steer.py; python tests/test_library_model.py; python tests/test_library_scripts.py; python tests/test_library_flows.py; python tests/test_access_register.py; python tests/test_auth.py`
Expected: PASS.

- [ ] **Step 5: Hand back.**

---

### Task 7: The brief, the public context and the DM course card (Claude)

**Files:**
- Create: `services/program_brief.py`
- Modify: `services/programs_curate.py` (`public_context`; `curate(..., brief=None, based_on='')`; the research question), `services/library.py` `prepare` (accepts `brief`/`based_on`), `services/agent_tools_v2.py` `propose_program` (`brief=`, persisted on the choice), `services/planned.py` `answer_program_choice` (make_new uses the choice's brief), `main.py` `POST /api/library` (accepts `{brief}`), `static/situations.js` / the DM card renderer (course card), `services/access_readers.py`
- Test: `tests/test_program_brief.py` (new), `tests/test_library_argyle.py` (extend)

**Interfaces:**
- Produces: `program_brief.parse(text, actor, members, *, surface) -> {'status': 'success', 'brief': {...}} | {'status': 'error', 'message', 'alternatives'?}` where brief = `{title, for_member_id|None, profile{age_band, minutes, sessions_per_week, assumes}, starting_point, preferred_days, target_date, based_on, exclude_books, notes}`; `programs_curate.public_context(profile, notes='', based_on='') -> str`; `curate(title, shape, ..., brief=None)` where `brief` carries `notes`/`based_on`; `POST /api/library` with `{brief: text}` → `library.create` from the parsed brief (P6: library only; the response carries `for_member_id` so the page can offer Start it for…); `propose_program(..., brief=None)`; the DM course card: a mission `ask`-style card posted by `_dm_person` with `refs` `[{'kind': 'library', 'id'}, {'kind': 'program', 'id': run_id}]` and two buttons rendered by `static/situations.js` (`Preview` → `chfLibrary.open(id)`, `Set it up for {name}` → `window.chfProgramSetup.open({runId, projectId})`).

- [ ] **Step 1: Write the failing tests**

```python
"""program_brief.parse and the public context (spec §1). Run from chauffeur/: python tests/test_program_brief.py"""
from unittest.mock import patch

from harness import check  # noqa: F401
from services import storage, program_brief, programs_curate, model_pools

MOM = {'id': 'mom', 'name': 'Mom', 'role': 'parent'}
KID = {'id': 'kid', 'name': 'Kate', 'role': 'child', 'is_child': True, 'birthdate': '2018-03-01'}
MEMBERS = [MOM, KID]


def _model(answer):
    return patch.object(model_pools, 'call_pool_json', lambda *a, **k: answer)


def scenario_brief_naming_a_child():
    with _model({'title': 'Learn piano', 'for': 'Kate', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'plays a tune one-handed',
                 'starting_point': 'plays Twinkle with her right hand', 'based_on': 'Piano Adventures', 'notes': 'evenings'}):
        res = program_brief.parse('Piano for Kate. She plays Twinkle with her right hand. 20 minutes, three evenings. Base it on Piano Adventures.', MOM, MEMBERS, surface='library')
    b = res['brief']
    check(res['status'] == 'success' and b['title'] == 'Learn piano' and b['for_member_id'] == 'kid' and b['profile']['minutes'] == 20
          and b['profile']['sessions_per_week'] == 3 and b['profile']['age_band'] != 'any' and b['based_on'] == 'Piano Adventures', f"parsed: {b}")


def scenario_brief_naming_nobody():
    with _model({'title': 'Learn guitar', 'minutes': None, 'sessions_per_week': None}):
        lib = program_brief.parse('a beginner guitar program', MOM, MEMBERS, surface='library')
        chat = program_brief.parse('I want to learn guitar', MOM, MEMBERS, surface='chat')
    check(lib['brief']['for_member_id'] is None and lib['brief']['profile']['minutes'] == 20 and lib['brief']['profile']['sessions_per_week'] == 3, f"library: nobody, defaults: {lib}")
    check(chat['brief']['for_member_id'] == 'mom', f"chat: the speaker (P6): {chat}")


def scenario_brief_without_an_aim():
    with _model({'title': '', 'for': 'Kate'}):
        res = program_brief.parse('something for Kate on Tuesdays', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error' and 'aim' in res['message'].lower(), f"no aim, no program: {res}")


def scenario_every_free_text_is_screened():
    with _model({'title': 'Get fit', 'notes': 'lose 10 kg by June'}):
        res = program_brief.parse('x', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error', f"a body target in notes is refused: {res}")
    with _model({'title': 'Learn piano', 'starting_point': 'plays Twinkle', 'assumes': 'plays Twinkle'}):
        res = program_brief.parse('x', MOM, MEMBERS, surface='library')
    check(res['status'] == 'error' and 'private' in res['message'].lower(), f"the starting point copied into the public assumes is refused: {res}")


def scenario_public_context_and_research_question():
    ctx = programs_curate.public_context({'age_band': 'any', 'minutes': 20, 'sessions_per_week': 3, 'assumes': 'beginner'}, notes='prefers songs over drills', based_on='Piano Adventures')
    check('prefers songs' in ctx and 'Piano Adventures' in ctx and 'Twinkle' not in ctx, f"public context carries notes and based_on, never a starting point: {ctx}")
    seen = {}
    def fake_research(question, read_pages=0):
        seen['q'] = question
        return {'status': 'ok', 'facts': [], 'sources': []}
    from services import web
    with patch.object(web, 'research', fake_research), patch.object(programs_curate, '_fallback', lambda *a, **k: {'phases': [], 'source': programs_curate._source_none('test')}):
        programs_curate.curate('learn piano', {'age_band': 'any', 'minutes': 20, 'sessions_per_week': 3, 'assumes': ''}, brief={'based_on': 'Piano Adventures', 'notes': 'songs'})
    check('Piano Adventures' in seen['q'], f"a named method is searched for: {seen['q']}")


def scenario_create_from_brief_route():
    for t in (storage.library_programs_table, storage.members_table):
        t.truncate()
    storage.add_member(dict(MOM)); storage.add_member(dict(KID))
    import main
    from fastapi.testclient import TestClient
    with _model({'title': 'Learn piano', 'for': 'Kate'}), \
         patch.object(programs_curate, 'curate', lambda *a, **k: {'phases': [{'name': 'F', 'weeks': 1, 'steps': ['a'], 'milestone': 'm', 'units': [{'title': 'U', 'sessions': 1}]}], 'source': {'origin': 'generated', 'reason': 'no_plan'}}), \
         patch('services.library_scripts.write', lambda *a, **k: {'status': 'ok', 'job': None}):
        r = TestClient(main.app).post('/api/library', json={'brief': 'Piano for Kate'}, headers={'X-Member-Token': storage.create_member_token('mom')})
    body = r.json()
    check(r.status_code == 200 and body['status'] == 'success' and body['program']['title'] == 'Learn piano' and body['for_member_id'] == 'kid', f"a brief makes a library row and names the person: {r.text}")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]

if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL {fn.__name__}"); traceback.print_exc()
    raise SystemExit(1 if failed else 0)
```

And in `tests/test_library_argyle.py`: `scenario_make_new_curates_from_the_brief` — a chat `propose_program(title, brief={'notes': 'songs over drills', 'based_on': 'Piano Adventures'})` reaching the waiting choice; answering Make new calls `curate` with that brief (patch `curate` to record kwargs); and `scenario_dm_course_card_binds_the_run` — after Use, the DM holds a card with refs to the library row and the run, and the card's `setup` ref carries `run_id`.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Implement**

`services/program_brief.py`:

```python
"""A plain-language brief becomes the curator's inputs (programs spec §1).
One model call on the free chain; every free-text field screened; the starting
point stays private to the run and never enters the public profile."""
from services import model_pools, programs_curate, stages, storage

SYSTEM = ("Read a family's description of a practice program and answer ONLY with JSON: "
          "{\"title\": short aim like 'Learn piano' or '', \"for\": a person's first name or '', \"minutes\": int or null, "
          "\"sessions_per_week\": int or null, \"assumes\": generic starting level like 'complete beginner' or '', "
          "\"starting_point\": what THIS person can already do, in their words, or '', \"preferred_days\": [0-6 weekday ints] or [], "
          "\"target_date\": 'YYYY-MM-DD' or '', \"based_on\": a named book, site or method or '', "
          "\"exclude_books\": true only if they said no books, \"notes\": anything else that should shape the plan or ''}. "
          "Leave title empty if no aim is stated.")


def parse(text, actor, members, *, surface='library'):
    text = str(text or '').strip()
    if not text:
        return {'status': 'error', 'message': 'Say what the program is for.'}
    settings = storage.get_settings() or {}
    raw = model_pools.call_pool_json('interactive', settings.get('llm_gemini_api_key', ''), SYSTEM, text,
                                     timeout_s=45, settings=settings, paid_ok=False)
    if not isinstance(raw, dict) or raw.get('error'):
        return {'status': 'error', 'message': "Couldn't read that just now. Try again, or fill it in by hand."}
    title = str(raw.get('title') or '').strip()
    if not title:
        return {'status': 'error', 'message': "Say what the aim is (for example 'learn piano' or 'train for a 5K')."}
    for field in ('title', 'assumes', 'starting_point', 'based_on', 'notes'):
        value = str(raw.get(field) or '').strip()
        if not value:
            continue
        screen = programs_curate.screen_aim(value) if field == 'title' else programs_curate.screen_starting_point(value)
        if not screen.get('ok'):
            return {'status': 'error', 'message': screen['message'], **({'alternatives': screen['alternatives']} if screen.get('alternatives') else {})}
    starting = str(raw.get('starting_point') or '').strip()
    assumes = str(raw.get('assumes') or '').strip()
    if starting and assumes and (assumes.lower() in starting.lower() or starting.lower() in assumes.lower()):
        return {'status': 'error', 'message': "What they can already do stays private; say a generic level for everyone (for example 'complete beginner')."}
    name = str(raw.get('for') or '').strip().lower()
    member = next((m for m in members if name and str(m.get('name') or '').strip().lower().startswith(name)), None)
    if member is None and surface == 'chat':
        member = actor
    band = stages.stage_for_age(stages.age_of(member)) if member and stages.age_of(member) is not None else 'any'
    profile = {'age_band': band, 'minutes': int(raw.get('minutes') or 20), 'sessions_per_week': int(raw.get('sessions_per_week') or 3), 'assumes': assumes}
    try:
        from services import library
        profile = library.public_profile(profile)
    except ValueError as e:
        return {'status': 'error', 'message': str(e)}
    days = [int(d) for d in (raw.get('preferred_days') or []) if str(d).lstrip('-').isdigit() and 0 <= int(d) <= 6]
    return {'status': 'success', 'brief': {
        'title': title, 'for_member_id': member.get('id') if member else None, 'profile': profile,
        'starting_point': starting, 'preferred_days': days, 'target_date': str(raw.get('target_date') or '').strip() or None,
        'based_on': str(raw.get('based_on') or '').strip(), 'exclude_books': bool(raw.get('exclude_books')),
        'notes': str(raw.get('notes') or '').strip()}}
```

`programs_curate.public_context(profile, notes='', based_on='')`: the inline library-path context block at ~687-701 extracted into this function, plus `f"Based on: {based_on}"` and `f"Also: {notes[:240]}"` lines when given; `curate(title, shape, member_name='', member=None, starting_point='', exclude_books=False, brief=None)`: when `'age_band' in shape` use `public_context(shape, (brief or {}).get('notes',''), (brief or {}).get('based_on',''))`; the research question gains `f" If it exists, follow {based_on}."` when `based_on`. `library.prepare(fields, actor)`: passes `brief={'notes': fields.get('notes',''), 'based_on': fields.get('based_on','')}` and `exclude_books`. `POST /api/library`: when `body.brief` is given, `program_brief.parse(body['brief'], actor, active members, surface='library')` → on error `_library_result`; on success `library.create({**brief['profile'], 'title', 'notes', 'based_on', 'exclude_books'}, actor)` and add `for_member_id` to the response. `propose_program(..., brief=None)`: `choice['brief'] = brief` so `_start_program_choice`'s make-new `library.prepare` sees it; `planned.answer_program_choice` already passes the stored choice.

DM course card: after a run is created from chat (`_start_program_choice` success), `_dm_person(mission, text)` is already called with the notice; extend the message record with `refs: [{'kind': 'library', 'id': library_id}, {'kind': 'program', 'id': run_id}]` and `card: {'type': 'program_setup', 'library_id', 'run_id', 'project_id', 'for_name'}` (read how `missions._dm_person` builds refs and how `static/situations.js` / the DM renderer draws `card` payloads for `ask` cards; follow that mechanism). The renderer draws title, source line, phases with lesson counts, **Preview** (`chfLibrary.open(library_id)`) and **Set it up for {name}** (`window.chfProgramSetup.open({runId, projectId})`); `chfProgramSetup` with `runId` never posts `POST /api/programs` (Task 4's island already branches on `runId`).

- [ ] **Step 4: Run to green, then neighbours**

Run: `python tests/test_program_brief.py; python tests/test_library_argyle.py; python tests/test_library_flows.py; python tests/test_programs_curate.py; python tests/test_programs_agent_tools.py; python tests/test_access_register.py`
Expected: PASS.

- [ ] **Step 5: Commit** (`feat(programs): a plain-language brief makes a library program - program_brief.parse screens every field and keeps the starting point private, one public context feeds the curator and the research question follows a named method, chat and the Library page share it, and the DM posts a course card whose Set it up configures the run the choice already made (vX.Y.Z)`).

---

### Task 8: The course page, the brief box and Steer (Claude)

**Files:**
- Modify: `templates/components/library_page.html` (the program view and the New program box), `templates/components/library_card.html` (`chfLibrary.openSetup`, source line words), `static/situations.js` (only if the DM card renderer lives there and Task 7 left markup to style)
- Test: `tests/test_library_live.py`, `tests/test_library_scripts_live.py` (migrate editor selectors behind Edit by hand)
- Run: `python tools/build_tailwind.py`

**Interfaces:**
- Consumes: `GET /api/library/{id}` (`scripts[lesson][label].{state, minutes, note, edited, stale}`, `writing`, `runners.named[].run_id`, `revision`, `lessons[].summary/origin`, `source.{plan_name,url,why_this_one,runners_up,origin,reason}`, `phases[].progression`), `POST /api/library/{id}/steer {text, revision}`, `POST /api/library {brief}`, `GET /api/library/{id}/lessons/{lid}/script?variant_label=&fill=1`, `GET /api/programs/{run_id}/lesson?lesson_id=&variant_label=` (runner-context preview), `lesson-player:open`, `window.chfProgramSetup.open`.
- Produces DOM: `[data-course-header]`, `[data-course-source]`, `[data-course-why]` (fold), `[data-course-phase="id"]` with `[data-phase-progression]`, `[data-course-lesson="id"]` with `[data-lesson-summary]` and `[data-lesson-preview]` (one button; `[data-preview-choice]` chooser when variants > 1 or runners visible), `[data-script-chip]` only when writing/failed, `[data-script-short]` when `minutes` is below the profile's minutes by the shortfall rule, `[data-steer-box]` + `[data-steer-send]` + `[data-steer-changes]`, `[data-course-menu]` (⋯: Steer in words, Edit by hand, Write lessons (admin), Make a variant, Archive, Delete, Start it for…), `[data-edit-by-hand]` mode toggling today's editor (`[data-lesson-edit]` etc. appear only in that mode), `[data-brief-box]` + `[data-brief-find]` on the list page with `[data-brief-by-hand]` revealing today's profile form.

- [ ] **Step 1: Write the failing live scenarios** (append to `tests/test_library_live.py`):

```python
def scenario_course_page_at_rest():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url(f'library?id={PIANO}'), wait_until='load')
        page.wait_for_selector('[data-course-header]', timeout=15000)
        check(page.locator('[data-lesson-edit]').count() == 0 and page.locator('[data-lesson-up]').count() == 0, "no editor controls at rest")
        n = page.locator('[data-course-lesson]').count()
        check(n == 3 and page.locator('[data-lesson-preview]').count() == n, "one Preview per lesson")
        check(page.locator('[data-lesson-summary]').first.inner_text().strip() != '', "a sentence per lesson")
        check(page.locator('[data-script-chip]').count() <= 1, "chips only while writing or failed")
        text = page.locator('[data-course-source]').inner_text()
        check('lessons' in text and ('Based on' in text or 'Made by the app' in text or 'Practice time only' in text), f"source line: {text}")
        page.locator('[data-course-why]').click()
        check('Why' in page.locator('[data-course-header]').inner_text(), "Why this one unfolds")
        page.locator('[data-course-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Steer in words', 'Edit by hand', 'Write lessons', 'Make a variant', 'Archive', 'Delete', 'Start it for'):
            check(any(want in l for l in labels), f"⋯ holds {want}: {labels}")
        page.locator('#cc-choice-modal button', has_text='Edit by hand').click()
        page.wait_for_selector('[data-lesson-edit]', timeout=5000)
        check(page.locator('[data-lesson-up]').count() >= 1 and page.locator('[data-library-add-lesson]').count() >= 1, "Edit by hand reveals today's editor")
        shot(page, 'course-page')


def scenario_steer_posts_and_shows_changes():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.route('**/api/library/*/steer', lambda route: route.fulfill(status=200, content_type='application/json',
            body='{"status":"success","changes":["Scales: 3 sessions → 2","+ Duet with a parent after Chords"],"said":"Done.","program":{}}'))
        page.goto(served.url(f'library?id={PIANO}'), wait_until='load')
        page.wait_for_selector('[data-steer-box]', timeout=15000)
        page.locator('[data-steer-box]').fill('shorter scales and a duet')
        page.locator('[data-steer-send]').click()
        page.wait_for_selector('[data-steer-changes]', timeout=10000)
        check('Duet with a parent' in page.locator('[data-steer-changes]').inner_text(), "the change list is shown")


def scenario_brief_box_on_the_list_page():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('library'), wait_until='load')
        page.wait_for_selector('[data-library-new]', timeout=15000)
        page.locator('[data-library-new]').click()
        page.wait_for_selector('[data-brief-box]', timeout=5000)
        check(page.locator('[data-brief-find]').count() == 1 and page.locator('[data-library-create-form] input[name="title"]').count() == 0, "the brief box leads; the form is folded")
        page.locator('[data-brief-by-hand]').click()
        page.wait_for_selector('[data-library-create-form] input[name="title"]', timeout=5000)
        shot(page, 'library-brief')


def scenario_phone_keeps_edit_by_hand_without_scripts():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        pwa(page, served, 'mom')
        page.goto(served.url('app?view=library'), wait_until='load')
        page.wait_for_selector('[data-library-page]', timeout=15000)
        page.locator(f'[data-library-open][data-library-id="{PIANO}"]').first.click()
        page.wait_for_selector('[data-course-menu]', timeout=10000)
        page.locator('[data-course-menu]').click()
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        check(any('Edit by hand' in l for l in labels) and not any('Write lessons' in l for l in labels), f"phone: Edit by hand yes, Write lessons no (P3): {labels}")
        page.locator('#cc-choice-modal button', has_text='Edit by hand').click()
        page.wait_for_selector('[data-lesson-edit]', timeout=5000)
        check(page.locator('[data-script-edit]').count() == 0, "no script editor on the phone")
```

Existing scenarios in `test_library_live.py` and `test_library_scripts_live.py` that click `[data-lesson-edit]`, `[data-script-edit]`, `[data-library-write]` or `[data-script-play]` at rest must first enter Edit by hand (`page.locator('[data-course-menu]').click(); page.locator('#cc-choice-modal button', has_text='Edit by hand').click()`) or use `[data-lesson-preview]`; migrate them, keeping their assertions.

- [ ] **Step 2: Run to see them fail.**

- [ ] **Step 3: Build the course page**

`library_page.html` program view (`opened && detail`), top to bottom:

1. `[data-course-header]`: title; made-for line; `[data-course-source]`: `sourceLine(lp)` = `"Based on " + plan_name + " · cited"` (link on the name when `url`) | `"Made by the app"` | `"Practice time only · " + reason`, then `" · N lessons · about W weeks"` (W = sum of phase weeks); when `chfLibrary.mixedCount(lp)` (lessons with `origin === 'generated'` inside a cited program) add `" · {n} lessons changed by the app"`; `[data-course-why]` button "Why this one" toggling a fold with `source.why_this_one` and `runners_up` (today's `whyText` in programs_page.html is the sibling: copy it); runners as today; `[data-course-menu]` ⋯ → `menu(lp)` (promptChoice: `Steer in words` (focus the box) · `Edit by hand`/`Done editing` · `Write lessons` (admin, can_edit, not archived) · `Make a variant` · `Archive` · `Delete` · `Start it for…` → `chfProgramSetup.open({libraryId: lp.id})`).
2. Phases: `[data-course-phase]` "N · name · done when milestone", `[data-phase-progression]` "Next time: …" when set; lessons `[data-course-lesson]`: title, `[data-lesson-summary]` (`l.summary`, falling back to the first step + session count), `[data-lesson-preview]` → `preview(lp, l)`: one script → `playScript(lp, l, label)`; several variants or visible runners → `promptChoice('Preview as', '', options)` where options are each variant label and, for each visible runner with `run_id`, `"as " + name` which plays through `GET api/programs/{run_id}/lesson?lesson_id=&variant_label=` (same `lesson-player:open` payload shape); `[data-script-chip]` only when `scriptOf(...).state` is `writing` or `failed` (failed chip click → today's `regenerateScript` confirm); `[data-script-short]` note "about {minutes} min, shorter than asked" when the script row's `note` says it runs short (`library_scripts.py:114` writes `runs about N minutes of M` when `est < target * program_lessons.SHORTFALL`; expose `short: bool` from `library._script_view` by that note rather than recomputing); `edited by hand · may be out of date` chip when `stale`.
3. Edit mode (`editing === lp.id`): today's editor markup exactly (▲▼ Edit Remove, Add lesson, script rows with Play/Edit/Regenerate/Reset on admin); the phone host (`host === 'phone'`) shows the lesson editor but no script editor, as today.
4. `[data-steer-box]` textarea + `[data-steer-send]` (can_edit, not archived): POST `api/library/{id}/steer {text, revision: lp.revision}`; on success render `[data-steer-changes]` (`changes` list + `said`) above the box and `load(true)`; on 409 `showGlobalAlert('The program changed; read it again.')` and reload.
5. List page: `[data-library-new]` opens `[data-brief-box]` (textarea with the placeholder from spec §1) + `[data-brief-find]` ("Find a plan") → POST `api/library {brief}`; on success open the program and, when `for_member_id` is set, `promptConfirm('Start it for ' + name + '?', …)` → `chfProgramSetup.open({libraryId, forMemberId})`; `[data-brief-by-hand]` ("Fill it in by hand") reveals today's `[data-library-create-form]`.
6. `chfLibrary.source(lp)` labels become `Based on {name} · cited` / `Made by the app` / `Practice time only`; the card's `Edit`/`Open` button text becomes `Open`.

Tailwind rebuild.

- [ ] **Step 4: Run the gate**

Run: `python tests/test_library_live.py; python tests/test_library_scripts_live.py; python tests/test_library_flows.py; python tests/test_library_access.py; python tests/test_project_sheets_phone_live.py`
Expected: PASS; screenshots `course-page.png`, `library-brief.png` compared with the mockup `.superpowers/brainstorm/56101-1792548799/content/course-page.html`.

- [ ] **Step 5: Commit** (`feat(library): the program page is a course - source line with Why this one, phases with their progression, one parent-facing sentence and Preview per lesson (per variant, or as a runner), chips only while writing or failed, Steer in words with a change list, hand editing and scripts behind Edit by hand, a brief box on the list page with Fill it in by hand (vX.Y.Z)`).

---

### Task 9: Parity guard, capabilities doc, close-out (Claude)

**Files:**
- Modify: `tests/test_programs_reachable.py` (DOM reachability scenarios via `tests/test_library_live.py` helpers, one per surface), `chauffeur/system_capabilities.md` (top entry), `docs/superpowers/specs/2026-10-20-programs-brief-and-course-design.md` status line

- [ ] **Step 1: Extend the parity test**

One live scenario per surface asserting every verb of the Global Constraints inventory is reachable: run sheet ⋯ (Change the days, Program settings, Log a session, Start a session, Look again, Plan without the book, Pause/Resume, Done with it, Drop, Delete), run sheet body (Reached it on every unjudged phase, Another session on this / Move on on the lit rung, Preview on a rung, Remove this session in the log), proposed block (What it adds to the week, Not these times?, Approve, Dismiss), course page ⋯ (Steer in words, Edit by hand, Write lessons, Make a variant, Archive, Delete, Start it for…), Edit by hand (▲▼ Edit Remove, Add lesson, script Edit/Regenerate/Reset), list page (brief box, Fill it in by hand), setup sheet (who, which, make new, days/times, minutes, target, Start). Keep the existing source-parsing scenarios.

- [ ] **Step 2: Capabilities entry**

Top of `system_capabilities.md`: "Programs: brief, course page, one-pass setup, monitoring sheet (vX.Y.Z)" — shipped-only; what and why; the activation contract; `replace_schedule`'s bracket and the child path; `monitor`'s fields and the no-fraction rule; the brief parser's screens and the private starting point; steer's one-candidate rule, provenance and the change list; stale hand-edited scripts; revision-bound script claims; P1–P8; device steps: (1) Library › New program, type a brief naming a child, Find a plan, read the course, steer once, Start it for her; (2) in a project, + Add › Program, pick, change a day, Start the program, see it active; (3) open the run sheet, read the stats and ladder, ⋯ › Change the days; (4) ⋯ › Start a session, pick tomorrow's window; (5) in the Argyle DM, "piano for Kate, 20 minutes, three evenings", Use the library match, tap Set it up for Kate.

- [ ] **Step 3: Gate, bump, commit, push**

Run: `python tests/test_program_schedule.py; python tests/test_program_setup.py; python tests/test_program_monitor.py; python tests/test_library_model.py; python tests/test_library_steer.py; python tests/test_program_brief.py; python tests/test_programs_reachable.py; python tests/test_library_live.py; python tests/test_programs_endpoints.py; python tests/test_access_register.py; python tests/test_auth.py`

```bash
git commit -m "docs(programs): system_capabilities.md records the brief, the course page, one-pass setup, the monitoring sheet and Change the days; the reachability guard covers every verb (vX.Y.Z)"
git push origin main
```

---

## Self-review notes

- Spec §1 brief → Task 7; §2 steer (steps 1–7) → Tasks 5 (revision, commit, claims) and 6; §3 course page → Task 8; §4 setup + activation → Tasks 2, 4; §5.1 monitoring → Tasks 3, 4; §5.3 Change the days → Task 1; §6 data/API → Tasks 1, 2, 3, 5, 6; §7 DM card → Task 7 (+ Task 4's `runId` branch); §8 vocabulary → Tasks 4, 8; §9 defects → Task 4 (copy/canApprove, preview Retry) and Task 8 (Regenerate confirm via the course page); §10 tests → each task; P1–P8 → Tasks 3/4 (P1, P2, P4, P5, P7, P8), 8 (P3), 7 (P6).
- Review Focus 1 → Task 3 `scenario_monitor_all_judged`; 2 → Task 1 `scenario_replace_with_orphaned_emissions`; 3 → Task 7 `scenario_brief_without_an_aim`; 4 → Task 6 `scenario_steer_empties_a_phase`; 5 → Task 6 `scenario_concurrent_steers`.
- Things the implementer must settle from the code, flagged in the task text: `add_protected_commitment` id preservation (T1), transaction rollback on exception (T2), `reconcile_progress` keeping judgements (T3), the real helper names in `test_library_model.py` (T5, T6), the DM card mechanism (`_dm_person` refs/card) (T7), the shortfall constant (T8).
