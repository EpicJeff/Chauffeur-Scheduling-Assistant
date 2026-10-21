"""A library program's lesson scripts: written once per lesson and variant from the public profile.

The shape (sanitizer, estimate, fill, prompts) lives in program_lessons.py; this module owns the
claim-token flow around a model call, the per-program background job and its ownership, the
nightly retry, and the one resolver every run route reads through.
"""
import logging
import threading
import time
import uuid
from collections import deque

from services import deletion, storage, program_lessons as pl

logger = logging.getLogger(__name__)

JOBS_KEY = 'library_script_jobs'
DEAD_AFTER_S = 30 * 60
ALREADY = 'Already writing lessons for this program.'
# Only the nightly pass publishes this; background jobs use invocation-local lists.
_PASS_SPENT = 0


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
                                      timeout_s=60, gemma_timeout_s=180, settings=settings, paid_ok=False)


def generate_script(row: dict, lesson: dict, variant_label: str, settings: dict, *, allowance=None, spend=None):
    """One lesson's script, claimed, written and committed against its token. Returns the stored
    row or None. `allowance` is how many calls the caller still has; None means unbounded.
    When supplied, `spend` receives one entry for each model call attempted."""
    from services import web
    slot = {'lesson_id': lesson['id'], 'variant_label': variant_label or ''}
    minutes = int((row.get('made_for') or {}).get('minutes') or 25)
    origin = lesson.get('origin') or (row.get('source') or {}).get('origin') or 'generated'
    variant = next((v for v in lesson.get('variants') or [] if isinstance(v, dict) and (v.get('label') or '') == (variant_label or '')), {}) if variant_label else {}
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
    token = storage.claim_library_script(row['id'], slot, revision=int(row.get('revision') or 0))
    if not token:
        return None
    tier = pool_tier(settings)
    if spend is not None:
        spend.append(1)
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
        if spend is not None:
            spend.append(1)
        again = _call(tier, settings, pl.system_prompt(), prompt + '\n\n' + pl.shortfall_prompt(int(round(est / 60)), minutes))
        if isinstance(again, dict) and not again.get('error'):
            more = pl.sanitize_script(again.get('scenes') or [], origin, minutes=minutes)
            est2 = pl.estimate_seconds(more)
            if more and est2 > est:
                storage.replace_library_script(row['id'], slot, token, {
                    **data, 'scenes': more, 'model': again.get('_model') or data['model'], 'minutes': int(round(est2 / 60)),
                    'note': f"runs about {int(round(est2 / 60))} minutes of {minutes}" if est2 < target * pl.SHORTFALL else ''})
    return storage.get_library_script(row['id'], slot)


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
    if row.get('archived'):
        return {'status': 'error', 'message': 'This program is archived.'}
    if not library.can_edit(row, actor):
        return {'status': 'error', 'code': 403, 'message': library.EDIT_REFUSAL}
    if lesson_id:
        pairs = [(l, lab) for l, lab in slots_of(row) if l['id'] == lesson_id and lab == (variant_label or '')]
        if not pairs:
            return {'status': 'error', 'code': 404, 'message': 'No such lesson.'}
    else:
        pairs = [(l, lab) for l, lab in slots_of(row) if needs_script(library_id, {'lesson_id': l['id'], 'variant_label': lab})]
        if not pairs:
            return {'status': 'ok', 'job': None}
    with storage.db_lock:
        jobs = _jobs()
        if _alive(jobs.get(library_id)):
            return {'status': 'error', 'message': ALREADY}
        if lesson_id:
            storage.delete_library_script(library_id, {'lesson_id': lesson_id, 'variant_label': variant_label or ''})
        job_id = uuid.uuid4().hex
        entry = {'job_id': job_id, 'started_at': time.time(), 'last_progress_at': time.time(),
                 'total': len(pairs), 'done': 0, 'failed': 0, 'lesson_id': pairs[0][0]['id'] if pairs else '',
                 'variant_label': pairs[0][1] if pairs else ''}
        jobs[library_id] = entry
        storage.set_app_state(JOBS_KEY, jobs)
    revision = int(row.get('revision') or 0)
    pairs = [(lesson, label, revision) for lesson, label in pairs]
    threading.Thread(target=_run, args=(library_id, job_id, pairs, settings), daemon=True,
                     name=f'library-scripts-{library_id[:8]}').start()
    return {'status': 'ok', 'job': dict(entry)}


def _run(library_id, job_id, pairs, settings):
    done = failed = 0
    pending = deque((lesson, label, revision, False) for lesson, label, revision in pairs)
    try:
        while pending:
            queued, label, revision, retried = pending.popleft()
            row = storage.get_library_program(library_id)
            if not row or row.get('archived') or not _progress(library_id, job_id, lesson_id=queued['id'], variant_label=label):
                return
            lesson = next((l for l in row.get('lessons') or [] if l['id'] == queued['id']), None)
            current_revision = int(row.get('revision') or 0)
            moved = current_revision != revision
            if lesson is not None and moved and not retried:
                pending.append((lesson, label, current_revision, True))
                continue
            slot = {'lesson_id': queued['id'], 'variant_label': label}
            valid_slot = lesson is not None and any(l['id'] == queued['id'] and lab == label for l, lab in slots_of(row))
            written = None
            try:
                if valid_slot and not moved and needs_script(library_id, slot):
                    written = generate_script(row, lesson, label, settings)
                elif valid_slot and not moved:
                    written = storage.get_library_script(library_id, slot)
            except Exception:                     # never let one lesson kill the job
                logger.exception("Library %s lesson %s failed", library_id, queued['id'])
            fresh = storage.get_library_program(library_id)
            if (valid_slot and not retried and fresh and not fresh.get('archived')
                    and int(fresh.get('revision') or 0) != current_revision):
                pending.append((lesson, label, int(fresh.get('revision') or 0), True))
                continue
            done += 1
            if not (written and written.get('scenes')):
                failed += 1
            if not _progress(library_id, job_id, done=done, failed=failed):
                return
    finally:
        _finish(library_id, job_id)

def script_for_run(run: dict, lesson_id: str, variant_label: str):
    """Return the library script, or None for an unconverted run.

    The legacy script read lives in main._run_script.
    """
    if not run:
        return None
    if run.get('library_id'):
        if not lesson_id:
            return None
        return storage.get_library_script(run['library_id'], {'lesson_id': lesson_id, 'variant_label': variant_label or ''})
    return None   # legacy runs are read by the caller through storage.get_program_lesson with the tuple slot


def retry_due(now, limit: int, *, start_offset: int = 1) -> int:
    """Tonight's pass: every active run's windows in the next two days whose library lesson still
    needs a script. Skips a library with a live job. Counts calls, a shortfall retry included."""
    global _PASS_SPENT
    spent = 0
    try:
        import datetime
        from services import programs
        settings = storage.get_settings() or {}
        start = now.date() + datetime.timedelta(days=start_offset)
        runs = {r['id']: r for r in storage.get_programs(state='active')}
        wrote = 0
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
            spend = []
            try:
                # Acting for the RUN this window serves: cleanup waits while
                # the call runs, and a result arriving after the run's
                # deletion is refused at the write (the doors check the carried source under the lock).
                with deletion.acting_for('program', run['id']):
                    out = generate_script(row, lesson, slot['variant_label'], settings, allowance=allowance, spend=spend)
            except deletion.Cancelled:
                raise
            except Exception as e:
                logger.exception("Library %s lesson %s retry failed: %s", row['id'], lesson['id'], e)
                continue
            finally:
                spent += max(1, len(spend))
            if out and out.get('scenes'):
                wrote += 1
        return wrote
    finally:
        _PASS_SPENT = spent
