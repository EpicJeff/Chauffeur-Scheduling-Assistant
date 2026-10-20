# Lesson Depth and Program-Owned Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A lesson script belongs to the library program (one template per lesson and variant, `{name}`/`{project}` filled at read time), fills the session it was asked for, teaches before it drills, is written by a per-program background job on a chosen model pool, and the synchronous sweep is gone.

**Architecture:** A new `library_scripts` table with five named write doors guarded by a per-row claim token under `db_lock` (claim, commit, replace, edit, delete); a `library_scripts` service that generates one lesson's script from the public profile with a time budget and a shortfall retry, runs the per-program job on a thread with ownership in `app_state`, and is the nightly retry; the run routes resolve a script through one function and fill variables; the library page owns editing, Play, Regenerate and Write lessons; a migration deletes every per-run script of a library run.

**Tech Stack:** Python 3.14, FastAPI (`chauffeur/main.py`), SQLite-backed storage (`services/storage.py`, `db_lock` is an RLock, `storage.db.transaction()`), plain-script tests from `chauffeur/` (`python tests/test_x.py`, `HA_BASE_URL` unset), Alpine.js templates, Node for extracted player JS, Playwright live tests.

**Spec:** `docs/superpowers/specs/2026-10-20-lesson-depth-design.md` rev 3, approved by the user 2026-10-20. Read it before any task: §1 doors and tokens, §2 variables, §3 budget, §4 teach, §5 arc and patterns, §6 generation, job and nightly retry, §7 migration and routes, §8 UI, §11 rulings (a)–(g), §13 the Codex findings each clause answers.

## Global Constraints

- **Running tests:** from `chauffeur/` with `HA_BASE_URL` unset: `python tests/test_library_scripts.py`. Run the task's own tests plus the named neighbours. Never the whole suite.
- **Fixture data only.** Tests isolate storage through `tests/harness.py` (`from harness import check` first) or `tests/program_fixture.py`. A live test that needs auth enforcement must not import `harness.py` (use `tests/live_app.py` and `library_run_fixture.py` as `test_library_live.py` does).
- **Exact strings:**
  - already writing: `"Already writing lessons for this program."`
  - library-run legacy write: 409 `"Scripts live in the library."`
  - shortfall note: `"runs about {n} minutes of {minutes}"`
  - edit refusal (existing): `"Only the person who made this program, or a parent, can change it."`
  - switches off (existing): `"Programs are switched off for this household."` / `"Lesson scripts are switched off for this household."`
  - Rhythms link: `"Scripts live in the library: {title}"`
  - card job line: `"Writing lessons · {done} of {total}"`
  - chips: `writing…`, `ready · about {n} min`, `failed · {note}`, `no script yet`
- **Numbers (spec §3, §4):** `scene_cap(minutes) = max(12, min(40, minutes))`; teach title 80, text 700, examples 5 × 160, speak 500 (`MAX_TEACH_SPEAK`); `MAX_SPEAK` 200 elsewhere; shortfall threshold 50 percent of `minutes × 60`; prompt range 80–120 percent; dead job after 30 minutes without progress; `UNIT_BODY_CHARS` 1500.
- **Variables:** `{name}`, `{project}` only; regex `\{[A-Za-z_]+\}`; unknown single-word tokens stripped with their braces; `{a b}` left alone; empty name fills `you`.
- **Locked rules:** no completion count or fraction; milestone is the person's call; rotation by date; Back stays; nothing records how a session went; an outage is never papered over (a cited lesson needs its page); a hand edit is never regenerated over; the public profile never carries a starting point; the voice ladder is not touched.
- **No browser dialogs.** `showGlobalAlert`, `promptConfirm`, `promptInput` only. Buttons, not anchors, on the phone. Vendored Alpine: coerce every `:disabled` with `!!`.
- **Tailwind is precompiled:** after a template class change run `python tools/build_tailwind.py` from `chauffeur/`.
- **Every HA touchpoint degrades gracefully.** This slice adds none.
- **Codex tasks** (2, 3, 4) run on gpt-6-astra, effort high (user, this run), leave changes in the working tree and never bump `chauffeur/config.yaml` or commit (AGENTS.md). Claude reviews, gates, bumps the patch version (v2.499.N), updates `system_capabilities.md` and commits with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Reviews cross models.** Codex-built tasks get a Claude reviewer subagent; Claude-built tasks (1, 5) get Codex (`codex-companion.mjs task --model gpt-6-astra --effort high`, read-only). Codex's sandbox cannot run Playwright; the controller runs the live tests and looks at the screenshots.
- **PowerShell:** no double quotes in commit messages. Use the Bash tool for git and for file edits.

## Review Focus

1. **A person edits a script in the library while the job is writing that same lesson.** Expected: the edit stands, the job's result is dropped, the chip reads ready and `edited by hand`. Pinned in Task 1 `scenario_an_edit_during_a_job_wins` (storage doors) and exercised through the job in `scenario_job_result_after_edit_is_dropped`.
2. **A library program is deleted a second after Write lessons was tapped** (it had no runs). Expected: no script row and no job entry reappear. Pinned in Task 1 `scenario_delete_mid_call_leaves_nothing`.
3. **The add-on restarts mid-job.** Expected: the card stops saying writing within a page poll, Write lessons works again at once, the lessons already written are kept. Pinned in Task 1 `scenario_startup_clears_the_job_map` and `scenario_a_restart_keeps_written_scripts`.
4. **A model answers a script of 40 scenes for a 20-minute session.** Expected: the cap holds at 20, the estimate is honest, nothing crashes. Pinned in Task 1 `scenario_scene_cap_scales_with_minutes`.
5. **A wall panel opens a lesson for a child whose name has an apostrophe or a non-ASCII letter** (`D'Arcy`, `Zoë`). Expected: `{name}` fills verbatim, the speak route accepts the filled line. Pinned in Task 1 `scenario_fill_keeps_names_verbatim`.

---

## File Structure

- Create `chauffeur/services/library_scripts.py`: `generate_script`, `write` (the job), `job_state`, `clear_jobs`, `needs_script`, `script_for_run`, `retry_due` (the nightly pass), `migrate_library_scripts_v2499` helper body (called from `migrations.py`). Owns everything that is "a library's script"; `program_lessons.py` keeps the shape (sanitizer, estimate, fill, prompts, legacy `generate_for`).
- Modify `chauffeur/services/program_lessons.py`: `MAX_TEACH_SPEAK`, `VARIABLE_RE`, `VARIABLES`, `scene_cap`, `estimate_seconds`, `fill`, teach branch in `sanitize_script`, `minutes` argument, `_SYSTEM` arc and patterns, `_GENERATED_PROMPT`/`_CITED_PROMPT` budget lines, `profile_context`, `shortfall_prompt`; `generate_due` becomes a thin call into `library_scripts.retry_due` plus the legacy branch; `sweep_report` deleted.
- Modify `chauffeur/services/storage.py`: `library_scripts_table`, `_library_script_query`, `claim_library_script`, `commit_library_script`, `replace_library_script`, `edit_library_script`, `get_library_script`, `get_library_scripts(library_id)`, `delete_library_script`, `delete_library_scripts`; `delete_library_program` also deletes scripts and clears the job entry.
- Modify `chauffeur/services/library.py`: `_view` adds `scripts` and `writing`; `create` starts the job.
- Modify `chauffeur/services/programs_curate.py`: GENERATE_SYSTEM body instruction, `UNIT_BODY_CHARS = 1500`.
- Modify `chauffeur/services/settings_registry.py`: `lesson_pool`.
- Modify `chauffeur/services/migrations.py`: `migrate_library_scripts_v2499`, appended to `run_all_migrations`.
- Modify `chauffeur/services/auth.py`: remove the sweep rule (new library routes fall under `/api/library/*`).
- Modify `chauffeur/main.py`: library script routes; run routes through `script_for_run` + `fill`; legacy PUT/DELETE answer 409 for library runs; sweep route removed; speak/voice caps; triggers in `create_program` (recurate branch) and the lifespan clear; `lesson-help` through `script_for_run`.
- Modify `chauffeur/services/agent_tools_v2.py` (the `propose_program` curate path) to start the job after a new library row.
- Modify `chauffeur/templates/components/library_page.html`, `library_card.html`, `programs_page.html`, `programs_settings.html`, `lesson_player.html`.
- Tests: `tests/test_library_scripts.py` (new), `tests/test_library_scripts_live.py` (new), `tests/test_program_lessons.py`, `tests/test_lesson_endpoints.py`, `tests/test_lesson_player_runtime.py`, `tests/test_programs_curate.py` (extended).

---

### Task 1: Tests first (Claude)

**Files:**
- Create: `tests/test_library_scripts.py`
- Create: `tests/test_library_scripts_live.py` (checklist docstring now; scenarios in Task 5)
- Modify: `tests/test_program_lessons.py` (append scenarios and register them in `__main__`)
- Modify: `tests/test_lesson_endpoints.py` (the route-shape scenario changes: PUT/DELETE stay routed but answer 409 for library runs; the sweep route is gone)
- Modify: `tests/test_lesson_player_runtime.py`, `tests/test_programs_curate.py` (append)

**Interfaces (what the tests pin; Tasks 2–4 implement exactly these names):**
- `program_lessons.MAX_TEACH_SPEAK == 500`, `program_lessons.VARIABLES == ('name', 'project')`, `program_lessons.scene_cap(minutes: int | None) -> int`, `program_lessons.estimate_seconds(scenes: list) -> int`, `program_lessons.fill(scenes: list, vars: dict) -> list`, `program_lessons.sanitize_script(scenes, origin, minutes=None, _depth=0)`, `program_lessons.system_prompt() -> str`, `program_lessons.profile_context(library_row) -> str`, `program_lessons.lesson_prompt(library_row, lesson, variant_label) -> str`, `program_lessons.shortfall_prompt(n_minutes, minutes) -> str`.
- Storage: `storage.library_scripts_table`; `storage.claim_library_script(library_id, slot) -> str | None`; `storage.commit_library_script(library_id, slot, token, data) -> str`; `storage.replace_library_script(library_id, slot, token, data) -> str`; `storage.edit_library_script(library_id, slot, data) -> str`; `storage.get_library_script(library_id, slot) -> dict | None`; `storage.get_library_scripts(library_id) -> list`; `storage.delete_library_script(library_id, slot) -> bool`; `storage.delete_library_scripts(library_id) -> int`. A `slot` is `{'lesson_id': str, 'variant_label': str}`. `data` carries `origin, source_url, scenes, model, attempts, note, minutes` (and `edited` only through `edit_`). Every door returns the row's new `claim` or `''` when refused.
- Service: `library_scripts.generate_script(library_row, lesson, variant_label, settings, *, allowance=None) -> dict | None` (the stored row or None); `library_scripts.write(library_id, actor, lesson_id=None, variant_label='') -> dict` (`{'status': 'ok', 'job': {...}}` or `{'status': 'error', 'message': ...}`); `library_scripts.job_state(library_id) -> dict | None` (None when absent or dead); `library_scripts.clear_jobs()`; `library_scripts.needs_script(library_id, slot) -> bool`; `library_scripts.script_for_run(run, lesson_id, variant_label) -> dict | None` (the library script for a library run, the legacy `program_lessons` row for an unconverted run); `library_scripts.retry_due(now, limit) -> int`; `library_scripts.JOBS_KEY == 'library_script_jobs'`; `library_scripts.DEAD_AFTER_S == 1800`; `library_scripts.pool_tier(settings) -> 'heavy' | 'background'`.
- Routes: `GET /api/library/{id}/lessons/{lesson_id}/script?variant_label=&fill=`, `PUT`, `DELETE` same path, `POST /api/library/{id}/scripts/write`.

- [ ] **Step 1: Write `tests/test_library_scripts.py`**

```python
"""Program-owned lesson scripts (spec 2026-10-20-lesson-depth-design.md rev 3, sections 1, 2, 6, 7).

Pinned here: the five storage doors and their claim tokens; the job and its ownership; the
nightly retry; the migration; the run routes reading through one resolver with variables
filled; the library script routes and who may use them.

Run from chauffeur/:  python tests/test_library_scripts.py   (HA_BASE_URL unset)
"""
import threading
import time
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)
from program_fixture import add_run
from services import storage, program_lessons as pl

PIANO = {'title': 'Learn piano', 'shape': {'minutes': 30, 'sessions_per_week': 3},
         'phases': [{'name': 'Foundations', 'what': 'Hands and keys', 'milestone': 'A scale',
                     'units': [{'n': 1, 'title': 'Middle C', 'sessions': 1, 'body': 'Find C. Play it with thumb 1.'},
                               {'n': 2, 'title': 'Five fingers', 'sessions': 1, 'body': 'C D E F G up and down.'}],
                     'rotation': [{'label': 'Session A', 'steps': ['Right hand']},
                                  {'label': 'Session B', 'steps': ['Left hand']}]}],
         'source': {'origin': 'generated', 'reason': 'test'}}
SAY = [{'type': 'say', 'text': 'Sit at the keys, {name}.'}]
TEACH = [{'type': 'teach', 'title': 'Middle C', 'text': 'C sits left of the two black keys. ' * 4,
          'examples': [{'text': 'Play C, rest, C'}, {'text': 'Dó', 'speak_lang': 'pt-BR'}],
          'speak': 'Find the two black keys and step left.'}]


def _reset():
    for t in ('programs', 'library_programs', 'program_lessons', 'library_scripts', 'members', 'projects'):
        getattr(storage, t + '_table').truncate()
    storage.set_app_state(pl_jobs_key(), {})
    storage.add_member({'id': 'mom', 'name': 'Mom', 'role': 'parent'})
    storage.add_member({'id': 'aunt', 'name': 'Aunt Jo', 'role': 'adult'})
    storage.add_member({'id': 'kate', 'name': "D'Arcy Zoë", 'role': 'child'})
    storage.add_member({'id': 'sam', 'name': 'Sam', 'role': 'child'})
    storage.add_project({'id': 'prj', 'title': 'Piano for Kate', 'goal': 'piano', 'done_when': 'habit',
                         'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household', 'pieces': [], 'steps': []})
    rid = add_run({'member_id': 'kate', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **PIANO})
    run = storage.get_program(rid)
    lid = run['library_id']
    lesson = storage.get_library_program(lid)['lessons'][0]
    return rid, lid, lesson


def pl_jobs_key():
    from services import library_scripts
    return library_scripts.JOBS_KEY


def _slot(lesson, label='Session A'):
    return {'lesson_id': lesson['id'], 'variant_label': label}


def _data(scenes=SAY, **kw):
    return {'origin': 'generated', 'source_url': '', 'scenes': scenes, 'model': 'test',
            'attempts': 0, 'note': '', 'minutes': 1, **kw}


# --- doors -------------------------------------------------------------------

def scenario_claim_then_commit_then_nobody_else():
    rid, lid, lesson = _reset()
    t1 = storage.claim_library_script(lid, _slot(lesson))
    check(t1, 'an empty slot can be claimed')
    t2 = storage.claim_library_script(lid, _slot(lesson))
    check(t2 and t2 != t1, 'a second claim on a still-empty slot refreshes the token')
    check(storage.commit_library_script(lid, _slot(lesson), t1, _data()) == '', 'the stale first token is refused')
    new = storage.commit_library_script(lid, _slot(lesson), t2, _data())
    check(new, 'the current token commits')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['scenes'] == SAY and row['claim'] == new, f'row stored with the new token, got {row}')
    check(storage.claim_library_script(lid, _slot(lesson)) is None, 'a slot with scenes cannot be claimed')
    check(storage.commit_library_script(lid, _slot(lesson), new, _data(scenes=[], attempts=1, note='x')) == '',
          'a failure record never lands on scenes')


def scenario_failure_record_lands_only_on_an_empty_slot():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    check(storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[], attempts=1, note='pool empty')),
          'a failure commits onto its own claim')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['attempts'] == 1 and row['note'] == 'pool empty' and not row['scenes'], f'failure row, got {row}')
    check(storage.claim_library_script(lid, _slot(lesson)), 'a failure row is still claimable')


def scenario_commit_after_library_delete_archive_or_lesson_removal_is_dropped():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.update_library_program(lid, {'archived': True})
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'archived: dropped')
    storage.update_library_program(lid, {'archived': False})
    t = storage.claim_library_script(lid, _slot(lesson))
    row = storage.get_library_program(lid)
    storage.update_library_program(lid, {'lessons': [l for l in row['lessons'] if l['id'] != lesson['id']]})
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'lesson gone: dropped')
    storage.update_library_program(lid, {'lessons': row['lessons']})
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.delete_library_program(lid)
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'library gone: dropped')
    check(storage.get_library_scripts(lid) == [], 'library delete removed its script rows')


def scenario_replace_is_in_place_and_conditional():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    t2 = storage.commit_library_script(lid, _slot(lesson), t, _data())
    longer = SAY + [{'type': 'do', 'text': 'Play C ten times', 'seconds': 60}]
    seen = []
    orig_remove = storage.library_scripts_table.remove

    def spy(*a, **kw):
        seen.append('remove')
        return orig_remove(*a, **kw)
    with patch.object(storage.library_scripts_table, 'remove', spy):
        t3 = storage.replace_library_script(lid, _slot(lesson), t2, _data(scenes=longer, minutes=2))
    check(t3 and storage.get_library_script(lid, _slot(lesson))['scenes'] == longer, 'replace landed')
    check(storage.replace_library_script(lid, _slot(lesson), t2, _data()) == '', 'the old token is refused')
    ids = [r['id'] for r in storage.get_library_scripts(lid)]
    check(len(ids) == 1, f'one row, never an empty window, got {ids}')


def scenario_an_edit_during_a_job_wins():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.edit_library_script(lid, _slot(lesson), _data(scenes=[{'type': 'say', 'text': 'Mine'}]))
    check(storage.commit_library_script(lid, _slot(lesson), t, _data()) == '', 'the in-flight generated result is dropped')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['edited'] and row['scenes'][0]['text'] == 'Mine', f'the edit stands, got {row}')
    check(storage.replace_library_script(lid, _slot(lesson), row['claim'], _data()) == '', 'replace never touches an edit')
    check(storage.edit_library_script(lid, _slot(lesson), _data(scenes=[{'type': 'say', 'text': 'Again'}])),
          'an edit replaces an edit')


def scenario_delete_invalidates_every_token():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    t2 = storage.commit_library_script(lid, _slot(lesson), t, _data())
    check(storage.delete_library_script(lid, _slot(lesson)), 'deleted')
    check(storage.replace_library_script(lid, _slot(lesson), t2, _data()) == '', 'old token dead after delete')
    t3 = storage.claim_library_script(lid, _slot(lesson))
    check(storage.commit_library_script(lid, _slot(lesson), t3, _data()), 'a fresh claim commits')


# --- generation ----------------------------------------------------------------

def _fake_pool(answers):
    """Each call pops the next answer; records the tier and prompts."""
    calls = []

    def call(tier, key, system, prompt, **kw):
        calls.append({'tier': tier, 'system': system, 'prompt': prompt})
        return answers.pop(0) if answers else {'error': 'empty'}
    return call, calls


def _short():
    return {'scenes': SAY}


def _long():
    return {'scenes': TEACH + [{'type': 'do', 'text': 'Play C and D', 'seconds': 600}] * 3}


def scenario_a_short_script_is_stored_then_retried_once_and_replaced():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    call, calls = _fake_pool([_short(), _long()])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 2, f'one retry, got {len(calls)}')
    check('runs about' in calls[1]['prompt'] and 'of the 30 asked' in calls[1]['prompt'], f'shortfall named: {calls[1]["prompt"][-200:]}')
    check(row and row['scenes'][0]['type'] == 'teach', 'the longer result replaced the first')
    check(row['minutes'] >= 15 and not row['note'], f'estimate honest, no note, got {row["minutes"]} {row["note"]!r}')


def scenario_retry_needs_allowance_and_a_worse_second_changes_nothing():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    call, calls = _fake_pool([_short(), _long()])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'}, allowance=1)
    check(len(calls) == 1 and row['scenes'] == pl.sanitize_script(SAY, 'generated', minutes=30), 'no allowance: first kept')
    check(row['note'] == 'runs about 0 minutes of 30' or row['note'].startswith('runs about'), f'note set, got {row["note"]!r}')
    storage.delete_library_script(lid, _slot(lesson))
    call, calls = _fake_pool([_short(), {'error': 'boom', 'transient': True}])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 2 and row['scenes'][0]['type'] == 'say' and row['attempts'] == 0,
          'a failed retry keeps the first script and records no attempt')


def scenario_a_full_length_script_costs_one_call_and_resets_attempts():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[], attempts=2, note='old'))
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call):
        row = library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A',
                                              {'llm_gemini_api_key': 'k'})
    check(len(calls) == 1 and row['attempts'] == 0 and not row['note'], f'one call, attempts reset, got {row}')


def scenario_the_pool_setting_picks_the_tier():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    for setting, tier in ((None, 'heavy'), ('background', 'background'), ('heavy', 'heavy'), ('bogus', 'heavy')):
        storage.delete_library_script(lid, _slot(lesson))
        settings = {'llm_gemini_api_key': 'k', **({'lesson_pool': setting} if setting else {})}
        call, calls = _fake_pool([_long()])
        with patch.object(model_pools, 'call_pool_json', call):
            library_scripts.generate_script(storage.get_library_program(lid), lesson, 'Session A', settings)
        check(calls[0]['tier'] == tier, f'{setting!r} -> {tier}, got {calls[0]["tier"]}')


def scenario_the_prompt_carries_the_spine():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    row = storage.get_library_program(lid)
    second = row['lessons'][1]
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call):
        library_scripts.generate_script(row, second, 'Session B', {'llm_gemini_api_key': 'k'})
    p = calls[0]['prompt']
    for needle in ('Hands and keys', 'Middle C', 'Find C. Play it with thumb 1.', '30 minutes', 'between 24 and 36',
                   'Up to 30 scenes', '{name}', 'complete beginner' if row['made_for'].get('assumes') else 'all ages'):
        check(needle in p, f'prompt lacks {needle!r}: {p[:600]}')
    check('Five fingers' in p, 'this lesson named')
    s = calls[0]['system']
    for needle in ('Open', 'Teach', 'Work', 'Wrap', '"type":"teach"', 'movement', 'cooking', 'phonics', 'problem-shaped',
                   'language', 'music', '{name}', '{project}', 'Nothing else goes in braces'):
        check(needle in s, f'system prompt lacks {needle!r}')
    check('At most 10 scenes' not in s, 'the old cap line is gone')


def scenario_a_cited_lesson_still_needs_its_page():
    from services import library_scripts, model_pools, web
    rid, lid, lesson = _reset()
    row = storage.get_library_program(lid)
    storage.update_library_program(lid, {'source': {**row['source'], 'origin': 'cited'},
                                         'lessons': [{**row['lessons'][0], 'url': 'https://example.test/c'}] + row['lessons'][1:]})
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call), patch.object(web, 'read_page', lambda u: ''):
        out = library_scripts.generate_script(storage.get_library_program(lid), storage.get_library_program(lid)['lessons'][0],
                                              'Session A', {'llm_gemini_api_key': 'k'})
    check(out is None and not calls, 'an unreadable page spends nothing and stores nothing')


# --- the job ---------------------------------------------------------------------

def _wait(pred, s=5.0):
    end = time.time() + s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def scenario_write_runs_every_lesson_in_order_and_clears():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    mom = storage.get_member('mom')
    call, calls = _fake_pool([_long()] * 4)
    with patch.object(model_pools, 'call_pool_json', call):
        res = library_scripts.write(lid, mom)
        check(res['status'] == 'ok' and res['job']['total'] == 4, f'four (lesson, variant) pairs, got {res}')
        check(library_scripts.write(lid, mom)['message'] == 'Already writing lessons for this program.', 'second refused')
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'entry cleared at the end')
    rows = storage.get_library_scripts(lid)
    check(len(rows) == 4 and all(r['scenes'] for r in rows), f'four scripts, got {len(rows)}')
    order = [p['prompt'] for p in calls]
    check('Middle C' in order[0] and 'Five fingers' in order[2], 'ladder order')


def scenario_regenerate_one_deletes_then_claims_and_writes_that_one():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data())
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call):
        res = library_scripts.write(lid, storage.get_member('mom'), lesson_id=lesson['id'], variant_label='Session A')
        check(res['status'] == 'ok' and res['job']['total'] == 1, f'one lesson, got {res}')
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'cleared')
    check(len(calls) == 1 and storage.get_library_script(lid, _slot(lesson))['scenes'][0]['type'] == 'teach', 'rewritten')
    check(len(storage.get_library_scripts(lid)) == 1, 'the other slots untouched')


def scenario_job_result_after_edit_is_dropped():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    gate = threading.Event()

    def call(tier, key, system, prompt, **kw):
        gate.wait(5)
        return _long()
    with patch.object(model_pools, 'call_pool_json', call):
        library_scripts.write(lid, storage.get_member('mom'), lesson_id=lesson['id'], variant_label='Session A')
        check(_wait(lambda: storage.get_library_script(lid, _slot(lesson)) is not None), 'claimed')
        storage.edit_library_script(lid, _slot(lesson), _data(scenes=[{'type': 'say', 'text': 'Mine'}]))
        gate.set()
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'job ended')
    row = storage.get_library_script(lid, _slot(lesson))
    check(row['edited'] and row['scenes'][0]['text'] == 'Mine', f'edit stands, got {row}')


def scenario_delete_mid_call_leaves_nothing():
    from services import library_scripts, model_pools, library
    rid, lid, lesson = _reset()
    storage.programs_table.truncate()          # no runs: the library may be deleted
    gate = threading.Event()

    def call(tier, key, system, prompt, **kw):
        gate.wait(5)
        return _long()
    with patch.object(model_pools, 'call_pool_json', call):
        library_scripts.write(lid, storage.get_member('mom'))
        check(_wait(lambda: library_scripts.job_state(lid) is not None), 'running')
        check(library.delete(lid, storage.get_member('mom'))['status'] == 'success', 'deleted while in flight')
        gate.set()
        time.sleep(0.3)
    check(storage.get_library_scripts(lid) == [], 'no script reappeared')
    check(library_scripts.job_state(lid) is None, 'no job entry reappeared')
    check(storage.get_library_program(lid) is None, 'still gone')


def scenario_a_dead_entry_is_reclaimed_and_the_stale_thread_is_ignored():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    dead = {'job_id': 'old', 'started_at': time.time() - 4000, 'last_progress_at': time.time() - 1860,
            'total': 4, 'done': 1, 'failed': 0, 'lesson_id': lesson['id'], 'variant_label': 'Session A'}
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: dead})
    check(library_scripts.job_state(lid) is None, 'a dead entry reads as absent')
    call, calls = _fake_pool([_long()] * 4)
    with patch.object(model_pools, 'call_pool_json', call):
        res = library_scripts.write(lid, storage.get_member('mom'))
        check(res['status'] == 'ok' and res['job']['job_id'] != 'old', 'reclaimed with a new job id')
        check(_wait(lambda: library_scripts.job_state(lid) is None), 'cleared')
    # a stale thread's map update: nothing to update when the entry is another job's
    library_scripts._progress(lid, 'old', done=99)
    check((storage.get_app_state(library_scripts.JOBS_KEY) or {}).get(lid) is None, 'stale update dropped')


def scenario_two_libraries_both_start():
    from services import library_scripts, model_pools
    rid, lid, lesson = _reset()
    rid2 = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **{**PIANO, 'title': 'Learn drums'}})
    lid2 = storage.get_program(rid2)['library_id']
    call, calls = _fake_pool([_long()] * 8)
    with patch.object(model_pools, 'call_pool_json', call):
        a = library_scripts.write(lid, storage.get_member('mom'))
        b = library_scripts.write(lid2, storage.get_member('mom'))
        check(a['status'] == 'ok' and b['status'] == 'ok', 'both started')
        check(_wait(lambda: library_scripts.job_state(lid) is None and library_scripts.job_state(lid2) is None), 'both ended')
    check(len(storage.get_library_scripts(lid)) == 4 and len(storage.get_library_scripts(lid2)) == 4, 'eight scripts')


def scenario_write_refuses_switches_and_children():
    from services import library_scripts
    rid, lid, lesson = _reset()
    with patch.object(storage, 'get_settings', lambda: {'program_lessons_enabled': False}):
        check(library_scripts.write(lid, storage.get_member('mom'))['message'] == 'Lesson scripts are switched off for this household.', 'switch')
    with patch.object(storage, 'get_settings', lambda: {'programs_enabled': False}):
        check(library_scripts.write(lid, storage.get_member('mom'))['message'] == 'Programs are switched off for this household.', 'switch')
    check(library_scripts.write(lid, storage.get_member('kate'))['code'] == 403, 'a child may not')
    check(library_scripts.write(lid, storage.get_member('aunt'))['code'] == 403, 'a non-creator adult may not')


def scenario_startup_clears_the_job_map():
    from services import library_scripts
    rid, lid, lesson = _reset()
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'x', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 2, 'done': 0, 'failed': 0}})
    library_scripts.clear_jobs()
    check(library_scripts.job_state(lid) is None, 'cleared')
    import inspect, main
    check('clear_jobs' in inspect.getsource(main.lifespan), 'the lifespan clears the map at startup')


def scenario_a_restart_keeps_written_scripts():
    from services import library_scripts
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data())
    library_scripts.clear_jobs()
    check(storage.get_library_script(lid, _slot(lesson))['scenes'] == SAY, 'written scripts survive a restart')
    check(library_scripts.needs_script(lid, _slot(lesson)) is False, 'and are not rewritten')


# --- nightly retry ---------------------------------------------------------------

def scenario_retry_due_claims_writes_and_skips_a_live_job():
    import datetime
    from services import library_scripts, model_pools, programs
    rid, lid, lesson = _reset()
    windows = [{'program_id': rid, 'date': (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                'lesson_id': lesson['id'], 'variant_label': 'Session A'}]
    call, calls = _fake_pool([_long()] * 3)
    with patch.object(model_pools, 'call_pool_json', call), patch.object(programs, '_practice_windows', lambda a, b: windows):
        wrote = library_scripts.retry_due(datetime.datetime.now(), limit=6)
    check(wrote == 1 and len(calls) == 1 and storage.get_library_script(lid, _slot(lesson))['scenes'], 'written once')
    storage.delete_library_script(lid, _slot(lesson))
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'j', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 4, 'done': 0, 'failed': 0}})
    call, calls = _fake_pool([_long()])
    with patch.object(model_pools, 'call_pool_json', call), patch.object(programs, '_practice_windows', lambda a, b: windows):
        wrote = library_scripts.retry_due(datetime.datetime.now(), limit=6)
    check(wrote == 0 and not calls, 'a live job means the nightly pass skips that library')


def scenario_retry_due_shortfall_counts_against_the_pass():
    import datetime
    from services import library_scripts, model_pools, programs
    rid, lid, lesson = _reset()
    windows = [{'program_id': rid, 'date': (datetime.date.today() + datetime.timedelta(days=1)).isoformat(),
                'lesson_id': lesson['id'], 'variant_label': 'Session A'},
               {'program_id': rid, 'date': (datetime.date.today() + datetime.timedelta(days=2)).isoformat(),
                'lesson_id': lesson['id'], 'variant_label': 'Session B'}]
    call, calls = _fake_pool([_short(), _long(), _long()])
    with patch.object(model_pools, 'call_pool_json', call), patch.object(programs, '_practice_windows', lambda a, b: windows):
        library_scripts.retry_due(datetime.datetime.now(), limit=2)
    check(len(calls) == 2, f'the retry spent the second unit, Session B waits: {len(calls)}')
    check(storage.get_library_script(lid, _slot(lesson))['scenes'][0]['type'] == 'teach', 'the longer replaced')
    check(storage.get_library_script(lid, _slot(lesson, 'Session B')) is None, 'B not reached this pass')
    check(storage.program_lessons_table.all() == [], 'nothing written to program_lessons')


def scenario_generate_due_still_routes_through_the_marker_and_switches():
    import datetime
    from services import library_scripts
    rid, lid, lesson = _reset()
    storage.set_app_state('program_lessons_swept', '')
    with patch.object(library_scripts, 'retry_due', lambda now, limit: 7):
        check(pl.generate_due(datetime.datetime.now()) == 7, 'generate_due calls retry_due')
        check(pl.generate_due(datetime.datetime.now()) == 0, 'the day marker throttles')
    check(not hasattr(pl, 'sweep_report'), 'sweep_report is gone')


# --- migration -------------------------------------------------------------------

def scenario_migration_deletes_every_per_run_script_of_a_library_run():
    from services import migrations, library_scripts
    rid, lid, lesson = _reset()
    rid2 = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **PIANO})
    storage.update_program(rid2, {'library_id': lid})
    storage.program_lessons_table.insert({'id': 'a', 'program_id': rid, 'lesson_id': lesson['id'], 'variant_label': 'Session A',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'SECRET shy about playing'}],
                                          'edited': False, 'created_at': 1.0})
    storage.program_lessons_table.insert({'id': 'b', 'program_id': rid2, 'lesson_id': lesson['id'], 'variant_label': 'Session A',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'Mine'}], 'edited': True, 'created_at': 2.0})
    legacy = storage.add_program({'member_id': 'sam', 'title': 'Old', 'phases': [{'name': 'P', 'steps': ['x']}], 'state': 'active',
                                  'shape': {'minutes': 20, 'sessions_per_week': 2}, 'created_by': 'mom'})
    storage.program_lessons_table.insert({'id': 'c', 'program_id': legacy, 'phase_name': 'P', 'unit_n': 0, 'session_label': '',
                                          'origin': 'generated', 'scenes': [{'type': 'say', 'text': 'legacy'}], 'edited': False})
    with patch.object(migrations.logger, 'info') as info:
        migrations.migrate_library_scripts_v2499()
        logged = ' '.join(str(c) for c in info.call_args_list)
    left = [r['id'] for r in storage.program_lessons_table.all()]
    check(left == ['c'], f'only the unconverted run keeps its row, got {left}')
    check('b' in logged and 'Mine' not in logged, 'the edited row is logged by id, never its text')
    check(storage.get_library_scripts(lid) == [], 'nothing was written to the library')
    migrations.migrate_library_scripts_v2499()
    check([r['id'] for r in storage.program_lessons_table.all()] == ['c'], 'a second run is a no-op')
    run = storage.get_program(rid)
    check(library_scripts.script_for_run(run, lesson['id'], 'Session A') is None, 'the run reads no old script')


# --- routes ----------------------------------------------------------------------

def _client():
    import main
    return TestClient(main.app), main


def _hdr(mid):
    return {'x-member-token': storage.create_member_token(mid)}


def scenario_run_routes_fill_and_share_one_script():
    rid, lid, lesson = _reset()
    rid2 = add_run({'member_id': 'sam', 'created_by': 'mom', 'project_id': 'prj', 'state': 'active', **PIANO})
    storage.update_program(rid2, {'library_id': lid})
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=[{'type': 'say', 'text': 'Sit down, {name}, for {project}.', 'speak': 'Go {name}'}]))
    c, main = _client()
    qs = f"lesson_id={lesson['id']}&variant_label=Session%20A"
    a = c.get(f'/api/programs/{rid}/lesson?{qs}', headers=_hdr('mom')).json()['lesson']
    b = c.get(f'/api/programs/{rid2}/lesson?{qs}', headers=_hdr('mom')).json()['lesson']
    check(a['scenes'][0]['text'] == "Sit down, D'Arcy, for Piano for Kate." and a['scenes'][0]['speak'] == "Go D'Arcy", f'filled: {a}')
    check(b['scenes'][0]['text'] == 'Sit down, Sam, for Piano for Kate.', 'the other run, the same template')
    check('model' not in a and a['minutes'] == 1, f'no model name, minutes present: {a.keys()}')
    wall = c.get(f'/api/programs/{rid}/lesson-scenes?{qs}').json()['lesson']
    check(wall['scenes'][0]['text'].startswith("Sit down, D'Arcy"), f'a panel gets filled scenes, got {wall}')
    v = c.post('/api/lessons/voice', json={'text': "Sit down, D'Arcy, for Piano for Kate.", 'lang': ''})
    check(v.status_code != 400, 'the filled line passes the voice route screens')


def scenario_fill_keeps_names_verbatim():
    rid, lid, lesson = _reset()
    out = pl.fill([{'type': 'say', 'text': 'Hi {name}', 'speak': '{name}!'}], {'name': "D'Arcy Zoë", 'project': 'P'})
    check(out[0]['text'] == "Hi D'Arcy Zoë" and out[0]['speak'] == "D'Arcy Zoë!", f'verbatim, got {out}')
    out = pl.fill([{'type': 'say', 'text': 'Hi {name}'}], {'name': '', 'project': 'P'})
    check(out[0]['text'] == 'Hi you', 'an empty name says you')


def scenario_legacy_run_writes_answer_409_for_a_library_run():
    rid, lid, lesson = _reset()
    c, main = _client()
    body = {'member_id': 'mom', 'lesson_id': lesson['id'], 'variant_label': 'Session A', 'scenes': SAY}
    r = c.put(f'/api/programs/{rid}/lesson', json=body, headers=_hdr('mom'))
    check(r.status_code == 409 and r.json()['detail'] == 'Scripts live in the library.', f'PUT 409, got {r.status_code} {r.text}')
    r = c.delete(f"/api/programs/{rid}/lesson?lesson_id={lesson['id']}&variant_label=Session%20A", headers=_hdr('mom'))
    check(r.status_code == 409, 'DELETE 409')
    r = c.post('/api/programs/lessons/sweep', json={'member_id': 'mom'}, headers=_hdr('mom'))
    check(r.status_code in (404, 405), f'the sweep route is gone, got {r.status_code}')
    from services import auth
    check(not any('/api/programs/lessons/sweep' in str(rule) for rule in auth.ROUTE_RULES), 'and gone from the auth table')


def scenario_library_script_routes_and_who_may():
    rid, lid, lesson = _reset()
    c, main = _client()
    path = f"/api/library/{lid}/lessons/{lesson['id']}/script?variant_label=Session%20A"
    check(c.get(path, headers=_hdr('kate')).json()['script'] is None, 'a member reads: nothing yet')
    r = c.put(path, json={'scenes': [{'type': 'say', 'text': 'Hi {name}'}] * 20}, headers=_hdr('mom'))
    check(r.status_code == 200 and r.json()['status'] == 'ok', f'a parent edits, got {r.text}')
    got = c.get(path, headers=_hdr('kate')).json()['script']
    check(len(got['scenes']) == 20 and got['edited'] and got['scenes'][0]['text'] == 'Hi {name}', f'template, cap by profile (30), got {len(got["scenes"])}')
    filled = c.get(path + '&fill=1', headers=_hdr('kate')).json()['script']
    check(filled['scenes'][0]['text'] == "Hi D'Arcy", 'preview fills with the viewer')
    for who in ('kate', 'aunt'):
        check(c.put(path, json={'scenes': SAY}, headers=_hdr(who)).status_code == 403, f'{who} may not edit')
        check(c.delete(path, headers=_hdr(who)).status_code == 403, f'{who} may not delete')
        check(c.post(f'/api/library/{lid}/scripts/write', json={}, headers=_hdr(who)).status_code == 403, f'{who} may not write')
    r = c.put(path, json={'scenes': [{'type': 'say', 'text': 'x'}] * 31}, headers=_hdr('mom'))
    check(len(c.get(path, headers=_hdr('mom')).json()['script']['scenes']) == 30, 'PUT honours scene_cap(30)')
    check(c.delete(path, headers=_hdr('mom')).json()['status'] == 'ok', 'a parent deletes')
    from services import library_scripts
    with patch.object(library_scripts, 'write', lambda lid_, actor, **kw: {'status': 'ok', 'job': {'job_id': 'j', 'total': 4, 'done': 0}}):
        r = c.post(f'/api/library/{lid}/scripts/write', json={}, headers=_hdr('mom'))
    check(r.status_code == 202 and r.json()['job']['total'] == 4, f'202 with the job, got {r.status_code} {r.text}')


def scenario_library_view_carries_script_state():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(minutes=12))
    t = storage.claim_library_script(lid, _slot(lesson, 'Session B'))
    storage.commit_library_script(lid, _slot(lesson, 'Session B'), t, _data(scenes=[], attempts=1, note='pool empty'))
    from services import library, library_scripts
    storage.set_app_state(library_scripts.JOBS_KEY, {lid: {'job_id': 'j', 'started_at': time.time(), 'last_progress_at': time.time(),
                                                           'total': 4, 'done': 2, 'failed': 1, 'lesson_id': lesson['id'], 'variant_label': ''}})
    view = library.get(lid, storage.get_member('kate'))
    s = view['scripts'][lesson['id']]
    check(s['Session A']['state'] == 'ready' and s['Session A']['minutes'] == 12, f'ready, got {s}')
    check(s['Session B']['state'] == 'failed' and s['Session B']['note'] == 'pool empty', 'failed with note')
    check(view['writing']['done'] == 2 and view['writing']['total'] == 4, 'job on the view')
    other = view['scripts'][storage.get_library_program(lid)['lessons'][1]['id']]
    check(other['Session A']['state'] == 'none', 'no script yet')


def scenario_lesson_help_reads_a_teach_beat_through_the_resolver():
    rid, lid, lesson = _reset()
    t = storage.claim_library_script(lid, _slot(lesson))
    storage.commit_library_script(lid, _slot(lesson), t, _data(scenes=pl.sanitize_script(TEACH, 'generated', minutes=30)))
    c, main = _client()
    from services import model_pools
    seen = {}

    def call(tier, key, system, prompt, **kw):
        seen['prompt'] = prompt
        return {'answer': 'Step left of the two black keys.'}
    with patch.object(model_pools, 'call_pool_json', call), patch.object(model_pools, 'credentials', lambda t, s: ('m', 'k')):
        r = c.post(f'/api/programs/{rid}/lesson-help', json={'lesson_id': lesson['id'], 'variant_label': 'Session A', 'scene_idx': 0},
                   headers=_hdr('mom'))
    check(r.status_code == 200 and 'two black keys' in seen['prompt'] and 'Play C, rest, C' in seen['prompt'], f'the teach beat, got {seen}')


if __name__ == '__main__':
    scenario_claim_then_commit_then_nobody_else()
    scenario_failure_record_lands_only_on_an_empty_slot()
    scenario_commit_after_library_delete_archive_or_lesson_removal_is_dropped()
    scenario_replace_is_in_place_and_conditional()
    scenario_an_edit_during_a_job_wins()
    scenario_delete_invalidates_every_token()
    scenario_a_short_script_is_stored_then_retried_once_and_replaced()
    scenario_retry_needs_allowance_and_a_worse_second_changes_nothing()
    scenario_a_full_length_script_costs_one_call_and_resets_attempts()
    scenario_the_pool_setting_picks_the_tier()
    scenario_the_prompt_carries_the_spine()
    scenario_a_cited_lesson_still_needs_its_page()
    scenario_write_runs_every_lesson_in_order_and_clears()
    scenario_regenerate_one_deletes_then_claims_and_writes_that_one()
    scenario_job_result_after_edit_is_dropped()
    scenario_delete_mid_call_leaves_nothing()
    scenario_a_dead_entry_is_reclaimed_and_the_stale_thread_is_ignored()
    scenario_two_libraries_both_start()
    scenario_write_refuses_switches_and_children()
    scenario_startup_clears_the_job_map()
    scenario_a_restart_keeps_written_scripts()
    scenario_retry_due_claims_writes_and_skips_a_live_job()
    scenario_retry_due_shortfall_counts_against_the_pass()
    scenario_generate_due_still_routes_through_the_marker_and_switches()
    scenario_migration_deletes_every_per_run_script_of_a_library_run()
    scenario_run_routes_fill_and_share_one_script()
    scenario_fill_keeps_names_verbatim()
    scenario_legacy_run_writes_answer_409_for_a_library_run()
    scenario_library_script_routes_and_who_may()
    scenario_library_view_carries_script_state()
    scenario_lesson_help_reads_a_teach_beat_through_the_resolver()
    print('test_library_scripts OK')
```

Adjust `auth.ROUTE_RULES` to the actual name of the rule table in `services/auth.py` (read it first; the table the test must scan is the one `check_request` consults).

- [ ] **Step 2: Append sanitizer, estimate and prompt scenarios to `tests/test_program_lessons.py`** (before `if __name__`), and register each in the `__main__` block:

```python
def scenario_a_teach_scene_is_title_text_examples_and_speak():
    out = pl.sanitize_script([{'type': 'teach', 'title': 'T' * 100, 'text': 'x ' * 500,
                              'examples': ['plain', {'text': 'e' * 200, 'speak_lang': 'pt-BR'}, {'text': 'burns calories'},
                                           {'text': '4'}, {'text': '5'}, {'text': '6'}],
                              'speak': 's' * 600}], 'generated')
    check(len(out) == 1 and out[0]['type'] == 'teach', f'teach survives, got {out}')
    t = out[0]
    check(len(t['title']) == 80 and len(t['text']) == pl.MAX_TEACH_TEXT == 700, f'caps, got {len(t["title"])} {len(t["text"])}')
    check(len(t['speak']) == pl.MAX_TEACH_SPEAK == 500, 'speak cap')
    check(t['examples'][0] == {'text': 'plain'}, 'a bare string becomes {text}')
    check(len(t['examples'][1]['text']) == 160 and t['examples'][1]['speak_lang'] == 'pt-BR', 'example cap and lang')
    check(all(e['text'] != 'burns calories' for e in t['examples']), 'a screened example drops itself only')
    check(len(t['examples']) == 5, f'five examples at most, got {len(t["examples"])}')
    check(pl.sanitize_script([{'type': 'teach', 'text': 'rotate the wrist'}], 'generated') == [], 'screened text drops the scene')
    check(pl.sanitize_script([{'type': 'teach', 'text': 'fine', 'speak': 'rotate the wrist'}], 'generated')[0].get('speak') is None,
          'screened speak drops the speak, keeps the scene')


def scenario_variables_survive_and_strangers_are_stripped():
    out = pl.sanitize_script([{'type': 'say', 'text': "Hi {name}'s friend, o{nome} {a b} {project} {age}"}], 'generated')
    check(out[0]['text'] == "Hi {name}'s friend, o {a b} {project} ", f'got {out[0]["text"]!r}')
    check(pl.VARIABLES == ('name', 'project'), 'closed set')
    cards = pl.sanitize_script([{'type': 'show', 'primitive': {'kind': 'cards', 'pairs': [{'front': '{nome}', 'back': 'ok {name}'}]}, 'caption': 'c'}], 'generated')
    check(cards[0]['primitive']['pairs'][0]['front'] == '' or cards == [] or cards[0]['type'] == 'say',
          'a face that was only a stranger token empties (and the pair rule decides the rest)')


def scenario_scene_cap_scales_with_minutes():
    check(pl.scene_cap(30) == 30 and pl.scene_cap(5) == 12 and pl.scene_cap(90) == 40 and pl.scene_cap(None) == 12, 'cap')
    scenes = [{'type': 'say', 'text': f'b{i}'} for i in range(45)]
    check(len(pl.sanitize_script(scenes, 'generated')) == 12, 'default keeps 12')
    check(len(pl.sanitize_script(scenes, 'generated', minutes=20)) == 20, 'a 20-minute profile holds 20')
    check(len(pl.sanitize_script(scenes, 'generated', minutes=400)) == 40, 'never more than 40')


def scenario_estimate_seconds_table():
    w10 = ' '.join(['w'] * 10)
    check(pl.estimate_seconds([{'type': 'say', 'text': w10}]) == 8, 'say: 4 + 10/2.5')
    check(pl.estimate_seconds([{'type': 'say', 'text': w10, 'speak': w10}]) == 12, 'speak adds')
    check(pl.estimate_seconds([{'type': 'say', 'text': w10, 'fade': True, 'passes': 3}]) == 12, 'fade: passes x words/2.5')
    check(pl.estimate_seconds([{'type': 'teach', 'text': w10, 'examples': [{'text': 'a'}, {'text': 'b'}]}]) == 22, 'teach: 6 + 4 + 12')
    check(pl.estimate_seconds([{'type': 'do', 'text': 'x'}]) == 60 and pl.estimate_seconds([{'type': 'do', 'text': 'x', 'seconds': 90}]) == 90, 'do')
    check(pl.estimate_seconds([{'type': 'check', 'ask': 'x'}]) == 8, 'check')
    check(pl.estimate_seconds([{'type': 'wait', 'minutes': 2, 'text': 'x'}]) == 120, 'wait')
    for kind, params, secs in (('timer', {'seconds': 45}, 45), ('listen', {'mode': 'presence', 'seconds': 20}, 20), ('metronome', {'bpm': 80}, 45),
                               ('keyboard', {'keys': ['C4']}, 20), ('fretboard', {'dots': []}, 20), ('tuner', {}, 20),
                               ('cards', {'pairs': [{}, {}, {}]}, 24), ('lines', {'pairs': [{}, {}]}, 24),
                               ('counter', {'target': 10, 'seconds_per_rep': 3}, 30), ('hints', {'steps': ['a'], 'answer': 'b'}, 30)):
        got = pl.estimate_seconds([{'type': 'show', 'primitive': {'kind': kind, **params}}])
        check(got == secs, f'{kind}: {secs}, got {got}')


def scenario_fill_touches_every_field_and_never_the_stored_row():
    scenes = [{'type': 'teach', 'title': '{name}', 'text': '{name}', 'speak': '{name}', 'examples': [{'text': '{name}'}]},
              {'type': 'do', 'text': '{name}', 'cues': [{'at': 1, 'say': '{name}'}]},
              {'type': 'check', 'ask': '{name}', 'not_yet_offer': {'label': '{name}', 'scenes': [{'type': 'say', 'text': '{name}'}]}},
              {'type': 'wait', 'minutes': 1, 'text': '{name}', 'announce': '{name}'},
              {'type': 'show', 'caption': '{project}', 'primitive': {'kind': 'cards', 'pairs': [{'front': '{name}', 'back': '{name}', 'speak': '{name}'}]}},
              {'type': 'show', 'caption': '', 'primitive': {'kind': 'lines', 'pairs': [{'cue': '{name}', 'line': '{name}'}]}},
              {'type': 'show', 'caption': '', 'primitive': {'kind': 'hints', 'steps': ['{name}'], 'answer': '{name}'}}]
    import copy, json
    before = copy.deepcopy(scenes)
    out = pl.fill(scenes, {'name': 'Kate', 'project': 'Piano'})
    check(scenes == before, 'the input is never mutated')
    text = json.dumps(out)
    check('{name}' not in text and '{project}' not in text and text.count('Kate') == 16 and 'Piano' in text, f'every field filled: {text}')
    check(pl.fill([{'type': 'say', 'text': '{other}'}], {'name': 'K', 'project': 'P'})[0]['text'] == '{other}', 'unknown left alone by fill')


def scenario_the_system_prompt_has_the_arc_and_the_variables():
    s = pl.system_prompt()
    for needle in ('Open', 'Teach', 'Work', 'Wrap', 'teach', 'examples', '{name}', '{project}', 'Nothing else goes in braces',
                   'music', 'movement', 'cooking', 'phonics', 'problem-shaped', 'language', 'greeting'):
        check(needle in s, f'system prompt lacks {needle!r}')
    check('At most 10 scenes' not in s and 'a short why, then the drill' not in s, 'the drill template is gone')


def scenario_the_lesson_prompt_states_the_budget_and_the_neighbours():
    row = {'title': 'Learn piano', 'made_for': {'age_band': 'explorer', 'minutes': 30, 'sessions_per_week': 3, 'assumes': 'complete beginner'},
           'source': {'origin': 'generated'},
           'phases': [{'id': 'p', 'name': 'Foundations', 'what': 'Hands and keys', 'progression': 'faster'}],
           'lessons': [{'id': 'a', 'phase_id': 'p', 'title': 'Middle C', 'steps': ['Find C'], 'body': 'B' * 400, 'variants': []},
                       {'id': 'b', 'phase_id': 'p', 'title': 'Five fingers', 'steps': ['C to G'], 'body': 'go', 'variants': []},
                       {'id': 'c', 'phase_id': 'p', 'title': 'Both hands', 'steps': [], 'variants': []}]}
    p = pl.lesson_prompt(row, row['lessons'][1], '')
    for needle in ('30 minutes', 'between 24 and 36', 'Up to 30 scenes', 'Hands and keys', 'Five fingers', 'C to G',
                   'Middle C', 'B' * 300, 'Both hands', 'complete beginner', 'faster', '{name}'):
        check(needle in p, f'lesson prompt lacks {needle!r}')
    check('B' * 301 not in p, 'the previous body is cut at 300')
    check('Middle C' not in pl.lesson_prompt(row, row['lessons'][0], '').split('Previous lesson')[0] or 'Previous lesson' not in pl.lesson_prompt(row, row['lessons'][0], ''),
          'the first lesson names no previous lesson')
    check('runs about 4 minutes of the 30 asked' in pl.shortfall_prompt(4, 30), 'shortfall wording')
    ctx = pl.profile_context(row)
    check('ages' in ctx and 'complete beginner' in ctx and 'birth' not in ctx.lower(), f'profile context, got {ctx}')
```

- [ ] **Step 3: Replace `scenario_endpoints_exist` in `tests/test_lesson_endpoints.py`** so it asserts GET, PUT and DELETE still exist on `/api/programs/{program_id}/lesson` (unchanged) and add `scenario_an_unconverted_run_still_edits_by_hand`: build a legacy run with `storage.add_program` (no `library_id`, with `phases`), PUT a script through the route as the parent, read it back, DELETE it. Keep every existing scenario.

- [ ] **Step 4: Append to `tests/test_lesson_player_runtime.py`:** `scenario_a_teach_scene_renders_its_own_block` (the component has an `x-if="scene().type === 'teach'"` block with `data-teach-title`, `data-teach-text`, `data-teach-example` markers, and the say block's condition excludes teach), `scenario_split_sentences_is_pure_and_keeps_numbers` (extract `splitSentences` with the file's existing JS-extraction helper and run under Node: `"Play it. Count 2.5 beats! Again?"` → three parts, `2.5` whole; an empty string → `[]`), `scenario_an_example_tap_speaks_in_its_language` (extracted `speakExample(i)` calls `this.say(text, lang, tone)` with the example's `speak_lang`), `scenario_a_scene_speak_is_queued_sentence_by_sentence` (the scene-enter path calls `say` once per sentence of `s.speak`, in order).

- [ ] **Step 5: Append to `tests/test_programs_curate.py`:** `scenario_generated_units_carry_the_material_itself` (`programs_curate.UNIT_BODY_CHARS == 1500`; `GENERATE_SYSTEM` contains `"the material itself"`, `"words, the rule and example sentences"`, `"notes, chords"`, `"sets and reps"`, `"recipe steps"`, `"the sound and the words"`; a unit with a 1400-character body survives `_clean_units(..., allow_body=True)` intact).

- [ ] **Step 6: Write `tests/test_library_scripts_live.py` docstring checklist** (items 1–8 below, scenarios land in Task 5), importing nothing from `harness.py`:
  1. Library page: each lesson row shows a chip (`no script yet` / `ready · about 12 min` / `failed · {note}` / `writing…`), Play for everyone, Edit and Regenerate for `can_edit`.
  2. Card header: Write lessons for `can_edit`; `Writing lessons · 2 of 4` when the job map holds an entry.
  3. Edit: add a teach row, fill title, text, two examples (`Dó | pt-BR`), speak; Save; reload; the fields come back; the thirteenth row on a 30-minute profile is accepted; the thirty-first refused.
  4. Play opens the player in preview with `{name}` filled with the viewer's name.
  5. Rhythms (`/rhythms`): a library run shows `Scripts live in the library: Learn piano` and no editor; an unconverted run still shows the editor.
  6. Settings drawer Lessons tab: `lesson_pool` select present; no Write lessons now; no report.
  7. Phone More → Library: chips and Play only; buttons, not anchors.
  8. Light and dark at phone width; screenshots inspected.

- [ ] **Step 7: Run every new test and confirm red for the right reason**

Run from `chauffeur/`: `python tests/test_library_scripts.py`, `python tests/test_program_lessons.py`, `python tests/test_lesson_player_runtime.py`, `python tests/test_programs_curate.py`, `python tests/test_lesson_endpoints.py`.
Expected: `AttributeError`/`ImportError` on `library_scripts`, `scene_cap`, `MAX_TEACH_SPEAK`, missing routes. The pre-existing scenarios in each file still pass up to the first new one.

- [ ] **Step 8: Codex review of the tests** (read-only, `codex-companion.mjs task --model gpt-6-astra --effort high`): "Review tests/test_library_scripts.py and the new scenarios against the spec sections 1, 3, 6, 7, 9. Report a test that pins behaviour the spec does not state, a spec clause with no test, and any test that would pass against a wrong implementation." Fold findings.

- [ ] **Step 9: Commit (Claude)**

```bash
git add tests/test_library_scripts.py tests/test_library_scripts_live.py tests/test_program_lessons.py tests/test_lesson_endpoints.py tests/test_lesson_player_runtime.py tests/test_programs_curate.py chauffeur/config.yaml
git commit -F - <<'EOF'
test(lessons): lesson depth contract - storage doors and claim tokens, generation budget and shortfall retry, the per-program job and its ownership, the nightly retry, the migration, run routes through one resolver with variables filled, library script routes, the teach scene, estimate table, fill, prompts, player render and curation body (red; Task 1) (v2.499.N)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 2: The shape — sanitizer, estimate, fill, teach, prompts, curation body, setting (Codex)

**Files:**
- Modify: `chauffeur/services/program_lessons.py` (constants near line 24–60; `sanitize_script`; `_SYSTEM`; prompts near line 1020–1060; `_context_block`)
- Modify: `chauffeur/services/programs_curate.py` (`UNIT_BODY_CHARS` line 173; `GENERATE_SYSTEM` units paragraph line ~500)
- Modify: `chauffeur/services/settings_registry.py` (after `lesson_max_attempts`, line ~756)
- Test: `tests/test_program_lessons.py` (Task 1 Step 2 scenarios), `tests/test_programs_curate.py`

**Interfaces:**
- Produces: `MAX_TEACH_TEXT = 700`, `MAX_TEACH_SPEAK = 500`, `MAX_TEACH_TITLE = 80`, `MAX_TEACH_EXAMPLES = 5`, `MAX_TEACH_EXAMPLE = 160`, `VARIABLES = ('name', 'project')`, `VARIABLE_RE = re.compile(r'\{[A-Za-z_]+\}')`, `scene_cap(minutes)`, `estimate_seconds(scenes)`, `fill(scenes, vars)`, `sanitize_script(scenes, origin, minutes=None, _depth=0)`, `profile_context(library_row)`, `lesson_prompt(library_row, lesson, variant_label)`, `shortfall_prompt(n_minutes, minutes)`, `BUDGET_LOW = 0.8`, `BUDGET_HIGH = 1.2`, `SHORTFALL = 0.5`. `_clean_text` strips stranger tokens: `VARIABLE_RE.sub(lambda m: m.group(0) if m.group(0)[1:-1] in VARIABLES else '', text)` applied before the whitespace collapse, so every field everywhere gets it.

- [ ] **Step 1: Constants and `scene_cap`**

```python
MAX_TEACH_TITLE = 80
MAX_TEACH_TEXT = 700
MAX_TEACH_SPEAK = 500
MAX_TEACH_EXAMPLES = 5
MAX_TEACH_EXAMPLE = 160
VARIABLES = ('name', 'project')
VARIABLE_RE = re.compile(r'\{[A-Za-z_]+\}')
BUDGET_LOW, BUDGET_HIGH, SHORTFALL = 0.8, 1.2, 0.5


def scene_cap(minutes) -> int:
    """How many scenes a session this long may hold: one a minute between 12 and 40."""
    m = _to_int(minutes)
    return 12 if m is None else max(12, min(40, m))
```

Keep `MAX_SCENES = 12` as the default `scene_cap(None)` returns; `sanitize_script` reads `cap = scene_cap(minutes)` and breaks at `cap`.

- [ ] **Step 2: `_clean_text` strips stranger tokens**

```python
def _clean_text(raw, cap: int = MAX_TEXT) -> str:
    text = VARIABLE_RE.sub(lambda m: m.group(0) if m.group(0)[1:-1] in VARIABLES else '', str(raw or ''))
    return re.sub(r'\s+', ' ', text).strip()[:cap]
```

- [ ] **Step 3: The teach branch in `sanitize_script`** (after the `say` branch):

```python
        elif kind == 'teach':
            text = _clean_text(raw.get('text'), MAX_TEACH_TEXT)
            title = _clean_text(raw.get('title'), MAX_TEACH_TITLE)
            if not text or _screened(text, origin) or (title and _screened(title, origin)):
                continue
            scene = {'type': 'teach', 'text': text}
            if title:
                scene['title'] = title
            examples = []
            for ex in (raw.get('examples') if isinstance(raw.get('examples'), list) else []):
                if isinstance(ex, str):
                    ex = {'text': ex}
                if not isinstance(ex, dict):
                    continue
                etext = _clean_text(ex.get('text'), MAX_TEACH_EXAMPLE)
                if not etext or _screened(etext, origin):
                    continue
                entry = {'text': etext}
                lang = ex.get('speak_lang')
                if isinstance(lang, str) and _LANG_RE.match(lang):
                    entry['speak_lang'] = lang
                examples.append(entry)
                if len(examples) >= MAX_TEACH_EXAMPLES:
                    break
            if examples:
                scene['examples'] = examples
            voice = dict(voice)
            speak = _clean_text(raw.get('speak'), MAX_TEACH_SPEAK)
            voice.pop('speak', None)
            if speak and not _screened(speak, origin):
                voice['speak'] = speak
            scene.update(voice)
            out.append(scene)
```

(`_voice_fields` already clipped `speak` at `MAX_SPEAK`; the teach branch recomputes it at the teach cap.)

- [ ] **Step 4: `estimate_seconds` and `fill`**

```python
def _words(text) -> float:
    return len(str(text or '').split())


def estimate_seconds(scenes) -> int:
    total = 0.0
    for s in (scenes if isinstance(scenes, list) else []):
        if not isinstance(s, dict):
            continue
        kind = s.get('type')
        if kind == 'say':
            if s.get('fade'):
                total += (_to_int(s.get('passes')) or MIN_FADE_PASSES) * _words(s.get('text')) / 2.5
            else:
                total += 4 + _words(s.get('text')) / 2.5
            total += _words(s.get('speak')) / 2.5
        elif kind == 'teach':
            total += 6 + _words(s.get('text')) / 2.5 + _words(s.get('speak')) / 2.5 + 6 * len(s.get('examples') or [])
        elif kind == 'do':
            total += _to_int(s.get('seconds')) or 60
        elif kind == 'check':
            total += 8
        elif kind == 'wait':
            total += (_to_int(s.get('minutes')) or 0) * 60
        elif kind == 'show':
            p = s.get('primitive') or {}
            k = p.get('kind')
            if k in ('timer', 'listen'):
                total += _to_int(p.get('seconds')) or 0
            elif k == 'metronome':
                total += 45
            elif k in ('keyboard', 'fretboard', 'tuner'):
                total += 20
            elif k == 'cards':
                total += 8 * len(p.get('pairs') or [])
            elif k == 'lines':
                total += 12 * len(p.get('pairs') or [])
            elif k == 'counter':
                total += (_to_int(p.get('target')) or 0) * (_to_int(p.get('seconds_per_rep')) or COUNTER_DEFAULT_SPR)
            elif k == 'hints':
                total += 30
    return int(round(total))


def fill(scenes, vars: dict) -> list:
    """Substitute the closed variable set in every free-text field. Pure."""
    import copy
    values = {'name': str((vars or {}).get('name') or '').strip() or 'you',
              'project': str((vars or {}).get('project') or '').strip()}

    def sub(text):
        if not isinstance(text, str):
            return text
        for k, v in values.items():
            text = text.replace('{' + k + '}', v)
        return text

    def walk(node):
        if isinstance(node, dict):
            return {k: (walk(v) if k in ('examples', 'cues', 'pairs', 'steps', 'scenes', 'primitive', 'not_yet_offer')
                        else sub(v) if k in ('text', 'speak', 'ask', 'caption', 'announce', 'title', 'say', 'front', 'back',
                                              'cue', 'line', 'answer', 'label') else v)
                    for k, v in node.items()}
        if isinstance(node, list):
            return [walk(x) if isinstance(x, (dict, list)) else sub(x) for x in node]
        return node
    return walk(copy.deepcopy(scenes if isinstance(scenes, list) else []))
```

(`steps` inside a `hints` primitive is a list of strings and goes through `sub` by the list branch; `scenes` inside an offer recurse.) `{project}` empty fills with the empty string; the caller passes the program title for a library preview.

- [ ] **Step 5: The system prompt** — replace the `"At most 10 scenes. Structure: a short why, then the drill as do-beats, one check near the end."` sentence with the arc, add the teach type to the scene list, and replace PATTERNS:

```python
    '{"type":"teach","title":"","text":"","examples":[{"text":"","speak_lang":"pt-BR"}],"speak":""} '
    "a teaching beat: what is new, why it matters, what good looks like, in up to 700 characters, with up to 5 short "
    "examples (each may carry speak_lang when it is in another language; a tap says it) and up to 500 spoken characters; "
    ...
    "STRUCTURE, four parts: OPEN connects to the previous lesson only when this one builds on it (cards or lines from its "
    "material, never more than two scenes; cooking and lawn mostly skip it). TEACH: at least one teach scene per new idea. "
    "WORK: the drill as do-beats and primitives, most of the time. WRAP: one check or one fade. "
    "VARIABLES: write {name} wherever a teacher would say the learner's name, and {project} for what they are working "
    "towards. Nothing else goes in braces. "
    "PATTERNS, by what the session is: music - teach names the notes or chords and is followed by a keyboard or fretboard "
    "show before metronome do-beats; strings tune up first. movement (anything moved or held) - teach says what the exercise "
    "is for and its pacing, never how to hold or move a joint; work is counters with spoken counts and switch-overs. cooking "
    "and crafts - teach the technique before the step it applies to; waits carry announce; grownup true on heat, blades, power "
    "tools. reading and phonics - teach the sound or rule with cards; work is cards and lines. problem-shaped (maths, puzzles) "
    "- teach the rule with one worked example; work is hint ladders, smallest nudge first. language - teach the rule with "
    "examples in both languages (speak_lang on the target-language ones); controlled practice through lines (lang set) and "
    "cards (speak + speak_lang); free production through a presence listen; at most one greeting beat in a session; OPEN "
    "reviews last lesson's words as cards. chemical (fertiliser, cleaner, weedkiller) - follow the label, never a rate or an amount."
```

Keep every other sentence of `_SYSTEM` (voice fields, no praise-fluff, body composition, grownup).

- [ ] **Step 6: `profile_context`, `lesson_prompt`, `shortfall_prompt`**

```python
def profile_context(row: dict) -> str:
    from services import library
    made = row.get('made_for') or {}
    return (f"Who this is for: {library.made_for_line(made)}"
            + (f"; assumes {made['assumes']}." if made.get('assumes') else '.')
            + " Write it so they can run the session on their own; put grownup true on any scene that needs an adult.")


def _budget_lines(minutes: int) -> str:
    return (f"This session is {minutes} minutes. Write a script that runs between {int(minutes * BUDGET_LOW)} and "
            f"{int(minutes * BUDGET_HIGH)} minutes by this reckoning: a say or teach beat takes about a second per two and a "
            f"half words read plus the same for its spoken line, a teach adds six seconds per example, a do-beat takes its "
            f"seconds (60 when it has none), a check 8 seconds, a wait its minutes, cards 8 seconds a pair, lines 12 seconds a "
            f"pair, a counter its target times its pace, a metronome 45 seconds, a keyboard, fretboard or tuner 20, a hint ladder "
            f"30, a timer or listen its seconds. Up to {scene_cap(minutes)} scenes.")


def lesson_prompt(row: dict, lesson: dict, variant_label: str) -> str:
    phases = {p['id']: p for p in row.get('phases') or []}
    phase = phases.get(lesson.get('phase_id')) or {}
    ladder = row.get('lessons') or []
    idx = next((i for i, l in enumerate(ladder) if l['id'] == lesson['id']), 0)
    prev = ladder[idx - 1] if idx > 0 else None
    nxt = ladder[idx + 1] if idx + 1 < len(ladder) else None
    variant = next((v for v in lesson.get('variants') or [] if (v.get('label') or '') == (variant_label or '')), {}) if variant_label else {}
    steps = variant.get('steps') or lesson.get('steps') or []
    body = variant.get('body') or lesson.get('body') or ''
    minutes = int((row.get('made_for') or {}).get('minutes') or 25)
    lines = [f'Write the session script for "{row.get("title") or ""}", phase {phase.get("name") or ""}'
             + (f' ({phase.get("what")})' if phase.get('what') else '') + f', lesson "{lesson.get("title") or ""}"'
             + (f', session {variant_label}' if variant_label else '') + '.',
             profile_context(row), _budget_lines(minutes),
             'Steps the lesson names: ' + ' | '.join(steps), 'Lesson material: ' + body,
             'Progression rule: ' + (phase.get('progression') or '')]
    if prev:
        lines.append(f'Previous lesson: "{prev.get("title") or ""}" - {str(prev.get("body") or "")[:300]}')
    if nxt:
        lines.append(f'Next lesson: "{nxt.get("title") or ""}"')
    lines.append('Build the session around the steps and the material; teach before you drill. Do NOT prescribe how to hold '
                 'or move any part of the body.')
    return '\n'.join(lines)


def shortfall_prompt(n_minutes: int, minutes: int) -> str:
    return (f"Your last script runs about {n_minutes} minutes of the {minutes} asked. Keep what works and add teaching, "
            f"practice and review until it fills the session.")
```

The cited prompt (`_CITED_PROMPT`) keeps its material rule and gains the same `_budget_lines(minutes)` and `profile_context` lines in place of `{context}`; `lesson_prompt` is the generated path. `_context_block` stays only for the legacy `generate_for` path.

- [ ] **Step 7: Curation and the setting**

In `programs_curate.py`: `UNIT_BODY_CHARS = 1500`; in `GENERATE_SYSTEM` replace the `units` paragraph with: "`units` is the LADDER: the lessons this phase works through IN ORDER, each with a title and a `body` carrying the material itself in the activity's own terms, enough to run the session without looking anything up: the words, the rule and example sentences for a language; the notes, chords or the section of the piece for music; the exercises with sets and reps for movement; the recipe steps for cooking; the sound and the words for phonics. `sessions` is how many sessions that unit takes, 1-4. NEVER give a unit a `url`: you have no source and a link you invented is worse than no link."

In `settings_registry.py` after `lesson_max_attempts`:

```python
    _e('lesson_pool', 'programs', 'Lesson writing model',
       'Which model pool writes lesson scripts: best available (Flash first, then Lite, then Gemma; default) or '
       'low cost (Gemma first). Used when a program is created, by Write lessons and Regenerate, and by the nightly retry.',
       page='work?tab=projects', anchor='lessons'),
```

- [ ] **Step 8: Run** `python tests/test_program_lessons.py` and `python tests/test_programs_curate.py`. Expected: the Task 1 Step 2 and Step 5 scenarios pass; every pre-existing scenario still passes (`scenario_scene_cap` reads `pl.MAX_SCENES`, unchanged at 12).

- [ ] **Step 9: Hand back** with a note of what changed and the test output. Claude reviews (a Claude subagent reads the diff against spec §2–§5), gates with `tests/test_lesson_endpoints.py` and `tests/test_lesson_player_runtime.py`, bumps, commits.

---

### Task 3: Storage doors, the service, the job, the nightly retry, the migration (Codex)

**Files:**
- Modify: `chauffeur/services/storage.py` (table at line ~575; doors after `delete_program_lessons` line ~4000; `delete_library_program` line ~3796)
- Create: `chauffeur/services/library_scripts.py`
- Modify: `chauffeur/services/program_lessons.py` (`generate_due` body; delete `sweep_report` and `_lesson_skip_reason`; keep `generate_for`, `_windows_to_scan`, `_lessons_switched_on`, `needs_lesson`, `_record_attempt` for the legacy branch)
- Modify: `chauffeur/services/library.py` (`_view`; `create` starts the job; `delete` already calls `storage.delete_library_program`)
- Modify: `chauffeur/services/migrations.py` (new function; append to `run_all_migrations` after `migrate_program_library_v2499`)
- Modify: `chauffeur/main.py` lifespan (one line: `library_scripts.clear_jobs()` before the tasks start)
- Test: `tests/test_library_scripts.py` doors, generation, job, nightly, migration scenarios; `tests/test_library_model.py`, `tests/test_library_migration.py`, `tests/test_program_lessons.py` as neighbours

**Interfaces:**
- Consumes from Task 2: `pl.sanitize_script(..., minutes=)`, `pl.estimate_seconds`, `pl.lesson_prompt`, `pl.shortfall_prompt`, `pl.system_prompt`, `pl._CITED_PROMPT`, `pl.SHORTFALL`, `pl.max_attempts`.
- Produces: the storage doors and the `library_scripts` API named in Task 1's Interfaces, exactly.

- [ ] **Step 1: Storage doors**

```python
    library_scripts_table = db.table('library_scripts')   # beside program_lessons_table
```

```python
def _library_script_query(library_id: str, slot: dict):
    slot = slot or {}
    q = Query()
    return ((q.library_id == library_id) & (q.lesson_id == str(slot.get('lesson_id') or ''))
            & (q.variant_label == str(slot.get('variant_label') or '')))


def _library_slot_alive(library_id: str, slot: dict) -> bool:
    row = get_library_program(library_id)
    return bool(row and not row.get('archived')
                and any(l.get('id') == (slot or {}).get('lesson_id') for l in row.get('lessons') or []))


def _script_row(library_id, slot, data, claim, edited, row_id=None):
    import uuid
    return {'id': row_id or uuid.uuid4().hex, 'library_id': library_id,
            'lesson_id': str(slot.get('lesson_id') or ''), 'variant_label': str(slot.get('variant_label') or ''),
            'origin': data.get('origin') or 'generated', 'source_url': data.get('source_url') or '',
            'scenes': list(data.get('scenes') or []), 'edited': edited, 'model': data.get('model') or '',
            'attempts': int(data.get('attempts') or 0), 'note': str(data.get('note') or ''),
            'minutes': int(data.get('minutes') or 0), 'claim': claim, 'created_at': time.time()}


def claim_library_script(library_id: str, slot: dict):
    import uuid
    with db_lock, db.transaction():
        if not _library_slot_alive(library_id, slot):
            return None
        cond = _library_script_query(library_id, slot)
        existing = library_scripts_table.search(cond)
        if existing and (existing[0].get('scenes') or existing[0].get('edited')):
            return None
        token = uuid.uuid4().hex
        if existing:
            library_scripts_table.update({'claim': token}, cond)
        else:
            library_scripts_table.insert(_script_row(library_id, slot, {}, token, False))
        return token


def _guarded_replace(library_id, slot, token, data, *, allow_edited):
    import uuid
    with db_lock, db.transaction():
        if not _library_slot_alive(library_id, slot):
            return ''
        cond = _library_script_query(library_id, slot)
        existing = library_scripts_table.search(cond)
        if not existing or existing[0].get('claim') != token:
            return ''
        if existing[0].get('edited') and not allow_edited:
            return ''
        new = uuid.uuid4().hex
        library_scripts_table.update(_script_row(library_id, slot, data, new, False, row_id=existing[0]['id']), cond)
        return new


def commit_library_script(library_id: str, slot: dict, token: str, data: dict) -> str:
    """A generated success or a failure record, against the token the claim handed out.
    A failure (no scenes) is refused when the row already holds scenes."""
    with db_lock, db.transaction():
        existing = library_scripts_table.search(_library_script_query(library_id, slot))
        if existing and existing[0].get('scenes') and not (data or {}).get('scenes'):
            return ''
        return _guarded_replace(library_id, slot, token, data or {}, allow_edited=False)


def replace_library_script(library_id: str, slot: dict, token: str, data: dict) -> str:
    return _guarded_replace(library_id, slot, token, data or {}, allow_edited=False)


def edit_library_script(library_id: str, slot: dict, data: dict) -> str:
    import uuid
    with db_lock, db.transaction():
        if not _library_slot_alive(library_id, slot):
            return ''
        cond = _library_script_query(library_id, slot)
        existing = library_scripts_table.search(cond)
        new = uuid.uuid4().hex
        row = _script_row(library_id, slot, data or {}, new, True, row_id=existing[0]['id'] if existing else None)
        if existing:
            library_scripts_table.update(row, cond)
        else:
            library_scripts_table.insert(row)
        return new


def get_library_script(library_id: str, slot: dict):
    with db_lock:
        res = library_scripts_table.search(_library_script_query(library_id, slot))
        return dict(res[0]) if res else None


def get_library_scripts(library_id: str) -> list:
    with db_lock:
        return [dict(r) for r in library_scripts_table.search(Query().library_id == library_id)]


def delete_library_script(library_id: str, slot: dict) -> bool:
    with db_lock:
        return bool(library_scripts_table.remove(_library_script_query(library_id, slot)))


def delete_library_scripts(library_id: str) -> int:
    with db_lock:
        gone = library_scripts_table.remove(Query().library_id == library_id)
        return len(gone) if isinstance(gone, list) else int(gone or 0)
```

`delete_library_program` adds, inside its lock: `library_scripts_table.remove(Query().library_id == library_id)` and clears `library_id` from `app_state['library_script_jobs']`. Check that `db.transaction()` nests under an outer `with db_lock` the way `library._write` already uses it (storage_sqlite line ~274); if the sqlite layer refuses a nested transaction, the doors take the lock and call the table methods without their own `transaction()`, relying on `RLock` + single-row writes, and say so in the hand-back.

- [ ] **Step 2: `services/library_scripts.py`**

```python
"""A library program's lesson scripts: written once per lesson and variant from the public profile.

The shape (sanitizer, estimate, fill, prompts) lives in program_lessons.py; this module owns the
claim-token flow around a model call, the per-program background job and its ownership, the
nightly retry, and the one resolver every run route reads through.
"""
import threading
import time
import uuid

from services import storage, program_lessons as pl

JOBS_KEY = 'library_script_jobs'
DEAD_AFTER_S = 30 * 60
ALREADY = 'Already writing lessons for this program.'


def pool_tier(settings: dict) -> str:
    return 'background' if (settings or {}).get('lesson_pool') == 'background' else 'heavy'


def needs_script(library_id: str, slot: dict) -> bool:
    row = storage.get_library_script(library_id, slot) or {}
    if row.get('edited') or row.get('scenes'):
        return False
    return int(row.get('attempts') or 0) < pl.max_attempts()


def slots_of(row: dict) -> list:
    """Every (lesson, variant_label) of a library row, in ladder order."""
    out = []
    for lesson in row.get('lessons') or []:
        labels = [v.get('label') or '' for v in lesson.get('variants') or [] if isinstance(v, dict) and v.get('steps')]
        for label in (labels or ['']):
            out.append((lesson, label))
    return out


def _call(tier, settings, system, prompt):
    from services import model_pools
    return model_pools.call_pool_json(tier, settings.get('llm_gemini_api_key', ''), system, prompt,
                                      timeout_s=60, gemma_timeout_s=180, settings=settings)


def generate_script(row: dict, lesson: dict, variant_label: str, settings: dict, *, allowance=None):
    """One lesson's script, claimed, written and committed against its token. Returns the stored
    row or None. `allowance` is how many calls the caller still has; None means unbounded."""
    from services import web
    slot = {'lesson_id': lesson['id'], 'variant_label': variant_label or ''}
    minutes = int((row.get('made_for') or {}).get('minutes') or 25)
    origin = (row.get('source') or {}).get('origin') or 'generated'
    variant = next((v for v in lesson.get('variants') or [] if (v.get('label') or '') == (variant_label or '')), {}) if variant_label else {}
    url = (variant.get('url') or lesson.get('url') or '') if origin == 'cited' else ''
    source_url = ''
    if origin == 'cited' and url:
        page = web.read_page(url)
        if not page:
            return None                    # an outage is never papered over
        source_url = url
        prompt = pl._CITED_PROMPT.format(url=url, page=page[:8000], minutes=minutes, label=variant_label or 'practice',
                                         phase=next((p.get('name') for p in row.get('phases') or [] if p.get('id') == lesson.get('phase_id')), ''),
                                         title=row.get('title') or '', context=pl.profile_context(row) + '\n' + pl._budget_lines(minutes),
                                         steps=' | '.join(variant.get('steps') or lesson.get('steps') or []))
    else:
        origin = 'generated'
        prompt = pl.lesson_prompt(row, lesson, variant_label or '')
    token = storage.claim_library_script(row['id'], slot)
    if not token:
        return None
    tier = pool_tier(settings)
    res = _call(tier, settings, pl.system_prompt(), prompt)
    if not isinstance(res, dict) or res.get('error'):
        counts = not (isinstance(res, dict) and (res.get('transient') or res.get('deferred')))
        existing = storage.get_library_script(row['id'], slot) or {}
        storage.commit_library_script(row['id'], slot, token, {
            'origin': origin, 'source_url': source_url, 'scenes': [],
            'attempts': int(existing.get('attempts') or 0) + (1 if counts else 0),
            'note': pl._clean_text(str(res.get('error') if isinstance(res, dict) else 'the model pool answered with nothing usable'), pl.MAX_SHORT_TEXT)})
        return None
    scenes = pl.sanitize_script(res.get('scenes') or [], origin, minutes=minutes)
    if not scenes:
        existing = storage.get_library_script(row['id'], slot) or {}
        storage.commit_library_script(row['id'], slot, token, {'origin': origin, 'source_url': source_url, 'scenes': [],
                                                               'attempts': int(existing.get('attempts') or 0) + 1,
                                                               'note': 'Nothing in the script the model wrote survived the screens.'})
        return None
    est = pl.estimate_seconds(scenes)
    target = minutes * 60
    data = {'origin': origin, 'source_url': source_url, 'scenes': scenes, 'model': res.get('_model') or '',
            'attempts': 0, 'note': '', 'minutes': int(round(est / 60))}
    if est < target * pl.SHORTFALL:
        data['note'] = f"runs about {int(round(est / 60))} minutes of {minutes}"
    token = storage.commit_library_script(row['id'], slot, token, data)
    if not token:
        return None
    if est < target * pl.SHORTFALL and (allowance is None or allowance >= 2):
        again = _call(tier, settings, pl.system_prompt(), prompt + '\n\n' + pl.shortfall_prompt(int(round(est / 60)), minutes))
        if isinstance(again, dict) and not again.get('error'):
            more = pl.sanitize_script(again.get('scenes') or [], origin, minutes=minutes)
            est2 = pl.estimate_seconds(more)
            if more and est2 > est:
                storage.replace_library_script(row['id'], slot, token, {
                    **data, 'scenes': more, 'model': again.get('_model') or data['model'], 'minutes': int(round(est2 / 60)),
                    'note': f"runs about {int(round(est2 / 60))} minutes of {minutes}" if est2 < target * pl.SHORTFALL else ''})
    return storage.get_library_script(row['id'], slot)
```

Note the failure record's `attempts` reads the existing row and adds one; the Task 1 scenario `scenario_a_full_length_script_costs_one_call_and_resets_attempts` pins that a success writes `attempts: 0`.

- [ ] **Step 3: The job**

```python
def _jobs() -> dict:
    jobs = storage.get_app_state(JOBS_KEY) or {}
    return jobs if isinstance(jobs, dict) else {}


def _alive(entry) -> bool:
    return bool(isinstance(entry, dict) and entry.get('job_id')
                and time.time() - float(entry.get('last_progress_at') or 0) < DEAD_AFTER_S)


def job_state(library_id: str):
    entry = _jobs().get(library_id)
    return entry if _alive(entry) else None


def clear_jobs():
    storage.set_app_state(JOBS_KEY, {})


def _progress(library_id, job_id, **fields):
    """Update this library's entry only while it is still this job's."""
    with storage.db_lock:
        jobs = _jobs()
        entry = jobs.get(library_id)
        if not isinstance(entry, dict) or entry.get('job_id') != job_id:
            return False
        entry.update(fields, last_progress_at=time.time())
        storage.set_app_state(JOBS_KEY, jobs)
        return True


def _finish(library_id, job_id):
    with storage.db_lock:
        jobs = _jobs()
        if isinstance(jobs.get(library_id), dict) and jobs[library_id].get('job_id') == job_id:
            del jobs[library_id]
            storage.set_app_state(JOBS_KEY, jobs)


def write(library_id: str, actor: dict, lesson_id: str = None, variant_label: str = '') -> dict:
    from services import library
    settings = storage.get_settings() or {}
    if not settings.get('programs_enabled', True):
        return {'status': 'error', 'message': 'Programs are switched off for this household.'}
    if not settings.get('program_lessons_enabled', True):
        return {'status': 'error', 'message': 'Lesson scripts are switched off for this household.'}
    row = storage.get_library_program(library_id)
    if not row:
        return {'status': 'error', 'code': 404, 'message': 'No such library program.'}
    if not library.can_edit(row, actor):
        return {'status': 'error', 'code': 403, 'message': library.EDIT_REFUSAL}
    if lesson_id:
        pairs = [(l, lab) for l, lab in slots_of(row) if l['id'] == lesson_id and lab == (variant_label or '')]
        if not pairs:
            return {'status': 'error', 'code': 404, 'message': 'No such lesson.'}
        storage.delete_library_script(library_id, {'lesson_id': lesson_id, 'variant_label': variant_label or ''})
    else:
        pairs = [(l, lab) for l, lab in slots_of(row) if needs_script(library_id, {'lesson_id': l['id'], 'variant_label': lab})]
    with storage.db_lock:
        jobs = _jobs()
        if _alive(jobs.get(library_id)):
            return {'status': 'error', 'message': ALREADY}
        job_id = uuid.uuid4().hex
        entry = {'job_id': job_id, 'started_at': time.time(), 'last_progress_at': time.time(),
                 'total': len(pairs), 'done': 0, 'failed': 0, 'lesson_id': pairs[0][0]['id'] if pairs else '',
                 'variant_label': pairs[0][1] if pairs else ''}
        jobs[library_id] = entry
        storage.set_app_state(JOBS_KEY, jobs)
    threading.Thread(target=_run, args=(library_id, job_id, pairs, settings), daemon=True,
                     name=f'library-scripts-{library_id[:8]}').start()
    return {'status': 'ok', 'job': dict(entry)}


def _run(library_id, job_id, pairs, settings):
    done = failed = 0
    try:
        for lesson, label in pairs:
            row = storage.get_library_program(library_id)
            if not row or row.get('archived') or not _progress(library_id, job_id, lesson_id=lesson['id'], variant_label=label):
                return
            try:
                written = generate_script(row, lesson, label, settings)
            except Exception as e:                 # never let one lesson kill the job
                print(f"[library_scripts] {library_id} {lesson.get('id')} failed: {e}")
                written = None
            done += 1
            if not (written and written.get('scenes')):
                failed += 1
            if not _progress(library_id, job_id, done=done, failed=failed):
                return
    finally:
        _finish(library_id, job_id)
```

- [ ] **Step 4: The resolver and the nightly retry**

```python
def script_for_run(run: dict, lesson_id: str, variant_label: str):
    """The one script a run may play: its library's, or a legacy row for an unconverted run."""
    if not run:
        return None
    if run.get('library_id'):
        if not lesson_id:
            return None
        return storage.get_library_script(run['library_id'], {'lesson_id': lesson_id, 'variant_label': variant_label or ''})
    return None   # legacy runs are read by the caller through storage.get_program_lesson with the tuple slot


def retry_due(now, limit: int) -> int:
    """Tonight's pass: every active run's windows in the next two days whose library lesson still
    needs a script. Skips a library with a live job. Counts calls, a shortfall retry included."""
    import datetime
    from services import programs
    settings = storage.get_settings() or {}
    start = now.date() + datetime.timedelta(days=1)
    runs = {r['id']: r for r in storage.get_programs(state='active')}
    wrote = spent = 0
    seen = set()
    for w in programs._practice_windows(start, start + datetime.timedelta(days=2)):
        run = runs.get(w.get('program_id'))
        if not run or not run.get('library_id') or not w.get('lesson_id'):
            continue
        key = (run['library_id'], w['lesson_id'], w.get('variant_label') or '')
        if key in seen:
            continue
        seen.add(key)
        if job_state(run['library_id']):
            continue
        slot = {'lesson_id': w['lesson_id'], 'variant_label': w.get('variant_label') or ''}
        if not needs_script(run['library_id'], slot):
            continue
        if spent >= max(0, int(limit or 0)):
            break
        row = storage.get_library_program(run['library_id'])
        lesson = next((l for l in (row or {}).get('lessons') or [] if l['id'] == w['lesson_id']), None)
        if not row or not lesson:
            continue
        allowance = max(0, int(limit) - spent)
        before = _calls_made()
        out = generate_script(row, lesson, slot['variant_label'], settings, allowance=allowance)
        spent += max(1, _calls_made() - before)
        if out and out.get('scenes'):
            wrote += 1
    return wrote
```

Replace `_calls_made()` with a plain counter: `generate_script` returns the row; have it also return how many calls it made through a module-level `_LAST_CALLS` set at the end of each call (`_LAST_CALLS = 1` or `2`), and `retry_due` adds `_LAST_CALLS`. Keep it that simple; the Task 1 scenario `scenario_retry_due_shortfall_counts_against_the_pass` pins the accounting (a short first plus a retry spends two of `limit=2`, so Session B is not reached).

`program_lessons.generate_due` keeps its marker, switches and `try/except`, and its body becomes:

```python
        from services import library_scripts
        wrote = library_scripts.retry_due(now, limit)
        # unconverted runs keep the legacy branch
        spent = 0
        for row, w, unit in _windows_to_scan(now, start_offset, 2):
            if row.get('library_id'):
                continue
            slot = slot_of(w, unit_n=int((unit or {}).get('n') or 0))
            if not needs_lesson(row['id'], slot):
                continue
            if spent >= max(0, int(limit or 0)):
                break
            spent += 1
            if generate_for(row, w, unit, settings):
                wrote += 1
        return wrote
```

Delete `sweep_report` and `_lesson_skip_reason`.

- [ ] **Step 5: `library._view`, `library.create`, the migration, the lifespan**

In `library.py`:

```python
def _script_view(row):
    from services import library_scripts
    scripts = {}
    by_slot = {(s['lesson_id'], s['variant_label']): s for s in storage.get_library_scripts(row['id'])}
    job = library_scripts.job_state(row['id'])
    for lesson, label in library_scripts.slots_of(row):
        s = by_slot.get((lesson['id'], label)) or {}
        if job and job.get('lesson_id') == lesson['id'] and (job.get('variant_label') or '') == label:
            state = 'writing'
        elif s.get('scenes'):
            state = 'ready'
        elif s.get('attempts') or s.get('note'):
            state = 'failed'
        else:
            state = 'none'
        scripts.setdefault(lesson['id'], {})[label] = {'state': state, 'minutes': int(s.get('minutes') or 0), 'note': s.get('note') or '',
                                                        'origin': s.get('origin') or '', 'edited': bool(s.get('edited'))}
    return scripts, job
```

`_view` adds `'scripts': scripts, 'writing': job`. `create` (after `storage.add_library_program`) calls `library_scripts.write(lid, actor)` and ignores its answer (a switch that is off simply writes nothing; the person sees `no script yet` and taps Write lessons later).

`migrations.py`:

```python
def migrate_library_scripts_v2499():
    """Every per-run script of a library run goes; the library job rewrites them from public inputs.
    Edited rows are logged by id, never their text. Idempotent."""
    from services import storage
    with storage.db_lock:
        library_runs = {r['id'] for r in storage.programs_table.all() if r.get('library_id')}
        gone = edited = 0
        for doc in storage.program_lessons_table.all():
            if doc.get('program_id') not in library_runs:
                continue
            if doc.get('edited'):
                edited += 1
                logger.info(f"[migrations] library script edit retired: run {doc.get('program_id')} lesson {doc.get('lesson_id')} "
                            f"variant {doc.get('variant_label')!r} scenes {len(doc.get('scenes') or [])} row {doc.get('id')}")
            storage.program_lessons_table.remove(doc_ids=[doc.doc_id])
            gone += 1
    if gone:
        logger.info(f"[migrations] library scripts: {gone} per-run rows retired ({edited} hand-edited)")
```

Appended to `run_all_migrations` after `migrate_program_library_v2499` inside its own `try/except`. In `main.py` `lifespan`, before `planned.reconcile()`: `from services import library_scripts; library_scripts.clear_jobs()`.

- [ ] **Step 6: Run** `python tests/test_library_scripts.py` (doors through migration scenarios pass; the route scenarios still fail until Task 4), `python tests/test_program_lessons.py`, `python tests/test_library_model.py`, `python tests/test_library_migration.py`.

- [ ] **Step 7: Hand back.** Claude reviews against spec §1, §6, §7; a Claude subagent reads the diff with the Codex findings in §13 as its checklist. Bump, commit.

---

### Task 4: Routes, triggers, caps (Codex)

**Files:**
- Modify: `chauffeur/main.py`: library script routes after `order_library_lessons_api` (line ~7841); `get_program_lesson_api`, `program_lesson_scenes`, `lesson_help_api` through `script_for_run` + `fill`; `put_program_lesson_api`/`delete_program_lesson_api` answer 409 for a library run; remove `sweep_program_lessons_now` and `_LESSON_SWEEP_PARAM_MAX`; `lesson_speak_api` and `lesson_voice_api` caps to `MAX_TEACH_SPEAK`; `create_program`'s `recurate` branch starts the job after the new library row.
- Modify: `chauffeur/services/auth.py`: remove the `/api/programs/lessons/sweep` rule.
- Modify: `chauffeur/services/agent_tools_v2.py`: after `propose_program` creates a new library row (the "I made a new library program" path), `library_scripts.write(lid, actor)`.
- Test: `tests/test_library_scripts.py` route scenarios, `tests/test_lesson_endpoints.py`, `tests/test_library_flows.py`, `tests/test_library_argyle.py`

**Interfaces:**
- Consumes from Task 3: `library_scripts.script_for_run`, `.write`, `.job_state`; from Task 2: `pl.fill`, `pl.sanitize_script(minutes=)`, `pl.MAX_TEACH_SPEAK`; storage doors `edit_library_script`, `delete_library_script`, `get_library_script`.

- [ ] **Step 1: A fill helper and the run reads**

```python
def _script_vars(run: dict) -> dict:
    member = storage.get_member(run.get('member_id') or '') or {}
    project = storage.get_project(run.get('project_id') or '') if run.get('project_id') else None
    name = str(member.get('name') or '').strip().split(' ')[0] if member.get('name') else ''
    return {'name': name, 'project': (project or {}).get('title') or ''}


def _run_script(row, slot):
    """The filled script for a run, or None. Legacy runs read their tuple row as before."""
    from services import library_scripts, program_lessons as _pl
    if row.get('library_id'):
        script = library_scripts.script_for_run(row, slot.get('lesson_id'), slot.get('variant_label') or '')
    else:
        script = _program_lesson_call(storage.get_program_lesson, row['id'], slot)
    if not script:
        return None
    return {**script, 'scenes': _pl.fill(script.get('scenes') or [], _script_vars(row))}
```

`get_program_lesson_api` returns `{"lesson": {k: s[k] for k in ('scenes', 'origin', 'source_url', 'edited', 'minutes', 'note', 'attempts') if k in s}}` (no `model`, no `claim`, no `id`). `program_lesson_scenes` returns scenes, origin, source_url from `_run_script`. `lesson_help_api` reads `scenes` from `_run_script` and, for a teach scene, builds `beat` from `title`, `text` and `' '.join(e['text'] for e in examples)`.

A first name: the first whitespace-separated word of `member['name']`; `D'Arcy Zoë` → `D'Arcy`. Keep apostrophes and non-ASCII letters verbatim.

- [ ] **Step 2: Legacy writes answer 409 for library runs**

At the top of `put_program_lesson_api` and `delete_program_lesson_api`, after the row lookup: `if row.get('library_id'): raise HTTPException(status_code=409, detail='Scripts live in the library.')`. Everything after stays for unconverted runs.

- [ ] **Step 3: Library script routes**

```python
def _library_script_slot(lesson_id, variant_label):
    return {'lesson_id': str(lesson_id or ''), 'variant_label': str(variant_label or '')}


@app.get('/api/library/{id}/lessons/{lesson_id}/script')
def get_library_script_api(id: str, lesson_id: str, request: Request, variant_label: str = '', fill: int = 0):
    from services import library, program_lessons as _pl
    actor = _library_actor(request)
    row = library.get(id, actor)
    if row is None:
        raise HTTPException(status_code=404, detail='No such library program.')
    script = storage.get_library_script(id, _library_script_slot(lesson_id, variant_label))
    if not script:
        return {'script': None}
    scenes = script.get('scenes') or []
    if fill:
        scenes = _pl.fill(scenes, {'name': str(actor.get('name') or '').split(' ')[0], 'project': row.get('title') or ''})
    return {'script': {'scenes': scenes, 'origin': script.get('origin') or '', 'source_url': script.get('source_url') or '',
                       'edited': bool(script.get('edited')), 'minutes': int(script.get('minutes') or 0), 'note': script.get('note') or ''}}


@app.put('/api/library/{id}/lessons/{lesson_id}/script')
def put_library_script_api(id: str, lesson_id: str, request: Request, body: dict = Body(default={}), variant_label: str = ''):
    from services import library, program_lessons as _pl
    actor = _library_actor(request)
    row = storage.get_library_program(id)
    if not row:
        raise HTTPException(status_code=404, detail='No such library program.')
    if not library.can_edit(row, actor):
        raise HTTPException(status_code=403, detail=library.EDIT_REFUSAL)
    slot = _library_script_slot(lesson_id, body.get('variant_label', variant_label))
    existing = storage.get_library_script(id, slot) or {}
    origin = existing.get('origin') or ((row.get('source') or {}).get('origin') if (row.get('source') or {}).get('origin') == 'cited' else 'generated')
    scenes = _pl.sanitize_script(body.get('scenes') or [], origin, minutes=(row.get('made_for') or {}).get('minutes'))
    if not scenes:
        return {'status': 'error', 'message': 'Nothing survivable in that script.'}
    saved = storage.edit_library_script(id, slot, {'origin': origin, 'source_url': existing.get('source_url') or '', 'scenes': scenes,
                                                   'model': existing.get('model') or '', 'minutes': int(round(_pl.estimate_seconds(scenes) / 60))})
    if not saved:
        raise HTTPException(status_code=409, detail='That lesson moved; open it again.')
    return {'status': 'ok'}


@app.delete('/api/library/{id}/lessons/{lesson_id}/script')
def delete_library_script_api(id: str, lesson_id: str, request: Request, variant_label: str = ''):
    from services import library
    actor = _library_actor(request)
    row = storage.get_library_program(id)
    if not row:
        raise HTTPException(status_code=404, detail='No such library program.')
    if not library.can_edit(row, actor):
        raise HTTPException(status_code=403, detail=library.EDIT_REFUSAL)
    storage.delete_library_script(id, _library_script_slot(lesson_id, variant_label))
    return {'status': 'ok'}


@app.post('/api/library/{id}/scripts/write', status_code=202)
def write_library_scripts_api(id: str, request: Request, body: dict = Body(default={})):
    from services import library_scripts
    res = library_scripts.write(id, _library_actor(request), lesson_id=body.get('lesson_id') or None,
                                variant_label=body.get('variant_label') or '')
    if res.get('code'):
        raise HTTPException(status_code=res['code'], detail=res['message'])
    if res.get('status') == 'error':
        return JSONResponse(status_code=200, content=res)
    return res
```

(`JSONResponse` from `fastapi.responses`; an error without a code returns 200 with `status: error` as every other programs write does.) The three new paths fall under the existing `/api/library/*` SIGNED_IN rule; confirm with `services/auth.py` and the test.

- [ ] **Step 4: Remove the sweep; raise the speak caps; triggers**

Delete `sweep_program_lessons_now`, `_LESSON_SWEEP_PARAM_MAX`, and the `/api/programs/lessons/sweep` line in `services/auth.py`. In `lesson_speak_api` and `lesson_voice_api` replace `_pl.MAX_SPEAK` with `_pl.MAX_TEACH_SPEAK` in the length check, the `_clean_text` cap and the detail string ("A spoken line is at most 500 characters."). In `create_program`'s `recurate` branch, after `library._invalidate()`: `from services import library_scripts; library_scripts.write(lid, actor)`. In `agent_tools_v2.py`, where `propose_program` has just created a library row through `library.create` (search for `I made a new library program`): nothing to add if it goes through `library.create` (which now starts the job); if it calls `storage.add_library_program` directly, add the `write` call there.

- [ ] **Step 5: Run** `python tests/test_library_scripts.py` (all green), `python tests/test_lesson_endpoints.py`, `python tests/test_library_flows.py`, `python tests/test_library_argyle.py`, `python tests/test_auth_tiers.py` (or whichever test audits the route table; find it with `grep -l ROUTE_RULES tests/*.py`).

- [ ] **Step 6: Hand back.** Claude reviews against spec §7; bump, commit.

---

### Task 5: UI — library page scripts, editor move, Rhythms link, settings drawer, player teach (Claude subagent)

**Files:**
- Modify: `chauffeur/templates/components/library_page.html` (lesson rows ~line 80–170; Alpine ~230–332)
- Modify: `chauffeur/templates/components/library_card.html` (card header: Write lessons / Writing lessons line)
- Modify: `chauffeur/templates/components/programs_page.html` (replace the editor block lines ~300–440 for library runs with the link; keep it for runs without `library_id`; JS `toggleLesson`…`regenerateLesson` stay for the legacy case)
- Modify: `chauffeur/templates/components/programs_settings.html` (lines ~55–100: `lesson_pool` select; remove the Write lessons now button and the report; remove `runLessonSweep`, `playSweepSlot`, `sweeping`, `sweepReport` from programs_page.html JS)
- Modify: `chauffeur/templates/components/lesson_player.html` (teach block after the say blocks ~line 186–215; `splitSentences`, `speakExample`; the scene-enter `say(line…)` at ~2191 becomes a loop over sentences)
- Modify: `tests/test_library_scripts_live.py` (the Playwright scenarios for the docstring's eight items)
- Run: `python tools/build_tailwind.py`
- Test: `tests/test_lesson_player_runtime.py`, `tests/test_library_scripts_live.py`, `tests/test_library_live.py`, `tests/test_settings_drawer.py`, `tests/test_programs_reachable.py`

**Interfaces:**
- Consumes: the library view's `scripts[lesson_id][variant_label] = {state, minutes, note, origin, edited}` and `writing = {job_id, done, total, ...} | null`; the Task 4 routes; `lesson-player:open` with `preview: true` and `lesson: {scenes, origin, source_url}`.

- [ ] **Step 1: Library page lesson row** — under each lesson's steps, one line per variant label (or one unlabelled line):

```html
<template x-for="lab in scriptLabels(l)" :key="lab">
  <div data-lesson-script :data-variant="lab" class="flex items-center gap-1.5 flex-wrap text-[11px]">
    <span class="text-gray-500" x-show="lab" x-text="lab"></span>
    <span data-script-chip class="font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300" x-text="scriptChip(lp, l, lab)"></span>
    <span x-show="scriptOf(lp, l, lab).edited" class="font-bold px-1.5 py-0.5 rounded bg-gray-700 text-gray-300">edited by hand</span>
    <button type="button" data-script-play @click="playScript(lp, l, lab)" :disabled="!!busy"
            class="font-bold px-2 py-1 rounded-lg bg-teal-700 text-white active:bg-teal-800 disabled:opacity-50">▶ Play</button>
    <template x-if="lp.can_edit">
      <span class="flex items-center gap-1.5">
        <button type="button" data-script-edit @click="editScript(lp, l, lab)" class="font-bold px-2 py-1 rounded-lg bg-gray-800 text-gray-300 border border-gray-700 active:bg-gray-700"
                x-text="scriptEdits[scriptKey(l, lab)] ? 'Close' : 'Edit'"></button>
        <button type="button" data-script-regenerate @click="regenerateScript(lp, l, lab)" :disabled="!!(busy || scriptOf(lp, l, lab).state === 'writing')"
                class="font-bold px-2 py-1 rounded-lg bg-gray-800 text-gray-400 border border-gray-700 active:bg-gray-700 disabled:opacity-50">Regenerate</button>
      </span>
    </template>
  </div>
</template>
```

Alpine helpers: `scriptLabels(l)` = variant labels with steps, else `['']`; `scriptOf(lp, l, lab)` = `((lp.scripts || {})[l.id] || {})[lab] || {state: 'none'}`; `scriptChip` maps state to `writing…` / `ready · about N min` / `failed · {note}` / `no script yet`; `scriptKey(l, lab) = l.id + '|' + lab`.

`playScript`: `GET lib(lp, '/lessons/' + id + '/script?variant_label=' + lab + '&fill=1')`, then dispatch `lesson-player:open` with `{preview: true, window: {title: lp.title, session_label: lab, lesson_id: l.id, variant_label: lab, phase_name, steps: l.steps, unit_title: l.title}, lesson: script || null}`. The library page must include `components/lesson_player.html` once (check `library.html`; add the include the way `programs_page.html`'s host does).

`regenerateScript`: if the script is `edited`, `promptConfirm('Rewrite this lesson by hand-edited script?', 'Your edit goes away and the app writes a fresh script.', 'Rewrite', 'Keep it')`; otherwise `promptConfirm('Rewrite this lesson?', 'The app writes a fresh script. Anyone practising keeps the plain steps until it lands.', 'Rewrite', 'Cancel')`; then `POST lib(lp, '/scripts/write')` with `{lesson_id, variant_label}`; on `status: error` show its message; then `load()` and start polling.

The editor (`editScript`) loads the template through `GET …/script` (no fill) into `scriptDrafts[key]`, rows per scene with type-specific fields:

```html
<template x-if="row.type === 'teach'">
  <div class="flex-1 min-w-0 space-y-1">
    <input x-model="row.title" placeholder="Title (optional)" class="w-full …">
    <textarea x-model="row.text" rows="3" placeholder="What is new, why, what good looks like" class="w-full …"></textarea>
    <textarea x-model="row._examples" rows="2" placeholder="One example per line; add | pt-BR for another language" class="w-full …"></textarea>
    <input x-model="row.speak" placeholder="What Argyle says (optional)" class="w-full …">
  </div>
</template>
```

`_examples` is a join of `examples.map(e => e.text + (e.speak_lang ? ' | ' + e.speak_lang : ''))` on load and is split back (`text | lang`) on save; the Add select offers Say, Do, Teach, Check, Wait, Show-caption; the row cap is `Math.max(12, Math.min(40, lp.made_for.minutes || 12))` with `showGlobalAlert(cap + ' beats is the most a ' + minutes + '-minute lesson holds.')`. Save: `PUT …/script` with `{variant_label, scenes}`, then `load()`. Reorder and remove as the old editor did.

Card header (`library_card.html`): for `can_edit`, a `Write lessons` button (`POST lib(lp, '/scripts/write')`, `{}`) that reads `Writing lessons · {done} of {total}` and is disabled while `lp.writing`; while any visible card has `writing`, poll `load()` every 10 s (`setInterval`, cleared when none is writing).

- [ ] **Step 2: Rhythms page** — wrap the existing editor block in `<template x-if="!p.library_id">` and add beside it:

```html
<template x-if="p.library_id">
  <button type="button" data-scripts-in-library @click="openLibrary(p)"
          class="mt-2 w-full text-left text-[11px] font-bold text-teal-300 border border-teal-700/60 rounded-lg px-2 py-1.5 hover:bg-teal-900/20"
          x-text="'Scripts live in the library: ' + (p.title || '')"></button>
</template>
```

`openLibrary(p)` navigates to `this.apiBase + 'library?id=' + encodeURIComponent(p.library_id)` (the library page already reads `?id=`). Remove `runLessonSweep`, `playSweepSlot`, `sweeping`, `sweepReport`, `fmtDate` if unused.

- [ ] **Step 3: Settings drawer** — replace the Write lessons block in `programs_settings.html` with:

```html
<label class="flex items-center justify-between gap-3">
  <span class="text-xs text-gray-300">Lesson writing model
    <span class="block text-[11px] text-gray-500 mt-0.5">Best available uses Flash first and spends the daily Flash quota; low cost starts on Gemma.</span>
  </span>
  <select x-model="s.lesson_pool" @change="saveProgramSettings()" class="bg-gray-900 border border-gray-700 rounded-lg px-2 py-1.5 text-white text-xs">
    <option value="heavy">Best available</option>
    <option value="background">Low cost</option>
  </select>
</label>
```

`s.lesson_pool` defaults to `'heavy'` when unset on load.

- [ ] **Step 4: Player** — teach block, example tap, sentence queue:

```html
<template x-if="scene().type === 'teach'">
  <div class="w-full max-w-md text-left space-y-3">
    <div data-teach-title x-show="scene().title" class="font-bold text-gray-100" :class="panel ? 'text-2xl' : 'text-lg'" x-text="scene().title"></div>
    <p data-teach-text class="text-gray-200 leading-relaxed" :class="panel ? 'text-xl' : 'text-base'" x-text="scene().text"></p>
    <ul class="space-y-1.5" x-show="(scene().examples || []).length">
      <template x-for="(ex, i) in (scene().examples || [])" :key="i">
        <li><button type="button" data-teach-example @click.stop="speakExample(i)"
                    class="w-full text-left rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-gray-100 active:bg-gray-700"
                    :class="panel ? 'text-xl' : 'text-sm'" x-text="ex.text"></button></li>
      </template>
    </ul>
  </div>
</template>
```

The say block's condition gains `&& scene().type !== 'teach'` where it degrades unknown shows (teach is known, so this is only belt and braces). JS:

```js
splitSentences(text) {
    const s = String(text || '').trim();
    if (!s) return [];
    return s.split(/(?<=[.!?])\s+(?=\S)/).map(x => x.trim()).filter(Boolean);
},
speakExample(i) {
    const ex = (this.scene().examples || [])[i] || {};
    if (ex.text) this.say(ex.text, ex.speak_lang || this.scene().speak_lang, this.scene().tone);
},
```

At the scene-enter `const line = [lead, s.speak]…; if (line) this.say(line, …)`: keep `lead` as its own first utterance, then `for (const part of this.splitSentences(s.speak)) this.say(part, s.speak_lang, s.tone);` — `say` already queues (`voiceQueue`) one utterance at a time, so the parts play in order and a tapped example joins the queue after the sentence in progress. Check `say()`'s own cancel behaviour: if it cancels the queue on call, change the scene-enter path to push parts onto `voiceQueue` directly through the existing enqueue helper so the first part is not cancelled by the second.

- [ ] **Step 5: `tests/test_library_scripts_live.py` scenarios** for the docstring's eight items, modelled on `test_library_live.py` (`live_app`, `seed`, tokens, `LIBRARY_SHOTS`), with a stubbed `library_scripts.write` that writes one fixed script synchronously and a faked job entry in `app_state` for the `Writing lessons · 2 of 4` check. Screenshots at phone width, light and dark.

- [ ] **Step 6: Build Tailwind, run** `python tools/build_tailwind.py`; `python tests/test_lesson_player_runtime.py`; `python tests/test_library_scripts_live.py`; `python tests/test_library_live.py`; `python tests/test_settings_drawer.py`; `python tests/test_programs_reachable.py`. Look at the screenshots.

- [ ] **Step 7: Codex review** of the UI diff (`codex-companion.mjs task --model gpt-6-astra --effort high`, read-only, with `docs/ui_design_guide.md` named as first reading). Fold. Bump, commit.

---

### Task 6: Close-out (Claude)

- [ ] **Step 1: Whole-branch review** by a Claude reviewer subagent of the full diff since v2.499.610 against the spec, with §13's twelve findings as the checklist; a Codex `adversarial-review --base <v2.499.610 sha>` as the cross-model pass. Fix wave if needed, with its own gate.
- [ ] **Step 2: Gate** (`HA_BASE_URL` unset): `test_library_scripts.py`, `test_program_lessons.py`, `test_lesson_endpoints.py`, `test_library_flows.py`, `test_library_model.py`, `test_library_migration.py`, `test_library_argyle.py`, `test_programs_curate.py`, `test_lesson_player_runtime.py`, `test_settings_drawer.py`, `test_library_live.py`, `test_library_scripts_live.py`, the auth route-table test.
- [ ] **Step 3: `system_capabilities.md`**: one BUILT, NOT device-verified entry at the top (shipped behaviour only, no NEXT), the lesson-player section's "four beat types" paragraph updated to five with teach, the library section's "Lesson identity" bullet rewritten to library ownership, the sweep paragraph removed.
- [ ] **Step 4: Memory**: update `lesson-scripts-belong-to-the-program.md` (SHIPPED, versions, device steps: rebuild, open More → Library, see chips, tap Write lessons on the Portuguese program, watch `Writing lessons · n of m`, play a lesson and hear a teach beat with Portuguese examples, check the session fills about 30 minutes), `instructor-arc.md` pointer, `MEMORY.md` line, `codex-coordination.md` note that this run used gpt-6-astra.
- [ ] **Step 5: Bump, commit, push.**

## Self-review notes

- Spec coverage: §1 doors (T3), §2 variables (T2 shape, T4 fill at read), §3 budget (T2 + T3 retry), §4 teach (T2 sanitizer, T4 caps, T5 render), §5 arc (T2), §6 inputs/pool/job/triggers/nightly (T2, T3, T4), §7 migration and routes (T3, T4), §8 UI (T5), §9 tests (T1 + T5), §10 split (header + tasks), §11 rulings (T4 409, T5 editor move, T3 migration), §12 out of scope untouched.
- Type consistency: `slot = {'lesson_id', 'variant_label'}` everywhere; doors return the new `claim` or `''`; `claim_library_script` alone returns `None` for "nothing to do"; `write` returns `{'status', 'job' | 'message', 'code'?}`; `job_state` returns the entry or `None`.
- Review Focus 1–5 are pinned in Task 1 (`scenario_an_edit_during_a_job_wins`, `scenario_job_result_after_edit_is_dropped`, `scenario_delete_mid_call_leaves_nothing`, `scenario_startup_clears_the_job_map`, `scenario_a_restart_keeps_written_scripts`, `scenario_scene_cap_scales_with_minutes`, `scenario_fill_keeps_names_verbatim`, `scenario_run_routes_fill_and_share_one_script`).
