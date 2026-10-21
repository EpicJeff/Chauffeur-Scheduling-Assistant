"""Steer a library program in words (programs spec §2): one model call proposes an edit plan
over the hand operations; the server builds one candidate, screens every model-authored
word, stamps provenance, commits once with a revision check, and reports a change list it
computed itself. Hand-edited scripts are preserved unless their lesson or slot is removed."""
import copy
import json

from services import library, library_scripts, model_pools, programs_curate, storage

OPS = ('update_profile', 'update_phase', 'add_lesson', 'update_lesson', 'remove_lesson', 'order_lessons')
LESSON_FIELDS = ('title', 'sessions', 'steps', 'body', 'url', 'variants', 'summary')
PHASE_FIELDS = ('name', 'milestone', 'what', 'progression')
SYSTEM = ("You revise a practice program for a family. Answer ONLY with JSON: {\"edits\": [...], \"said\": \"one sentence\"}. "
          "Each edit is one of: update_profile{fields{title,age_band,minutes,sessions_per_week,assumes}}, "
          "update_phase{phase_id,fields{name,milestone,what,progression}}, "
          "add_lesson{phase_id,after,fields{title,sessions,steps,body,url,variants,summary}}, update_lesson{lesson_id,fields}, "
          "remove_lesson{lesson_id}, order_lessons{ids}. Use the ids given. Keep lessons that are not mentioned. "
          "Every lesson keeps or gets a one-sentence summary written for the parent, ending with its session count. "
          "Content may cite an existing source.fact by its 1-based cite index or exact url; never invent a citation. "
          "Never prescribe loads, doses or body-composition targets.")


def _course_text(row):
    return json.dumps({'title': row.get('title'), 'made_for': row.get('made_for'),
                       'facts': [{**fact, 'index': n} for n, fact in enumerate((row.get('source') or {}).get('facts') or [], 1)
                                 if isinstance(fact, dict)],
                       'phases': [{'id': p['id'], 'name': p.get('name'), 'milestone': p.get('milestone'), 'what': p.get('what'), 'progression': p.get('progression')} for p in row.get('phases') or []],
                       'lessons': [{k: l.get(k) for k in ('id', 'phase_id', 'title', 'sessions', 'steps', 'body', 'url', 'summary', 'variants')} for l in row.get('lessons') or []]})


def plan(row, text, settings):
    api_key = (settings or {}).get('llm_gemini_api_key', '')
    res = model_pools.call_pool_json('interactive', api_key, SYSTEM, f"Program:\n{_course_text(row)}\n\nThe person says: {text}",
                                     timeout_s=60, settings=settings, paid_ok=False)
    if not isinstance(res, dict) or res.get('error') or not isinstance(res.get('edits'), list):
        return {'error': (res.get('error') or 'no usable edit plan') if isinstance(res, dict) else 'no answer'}
    return {'edits': res['edits'], 'said': res.get('said') or ''}


def _line(raw, aim, cap=240):
    if not isinstance(raw, str):
        raise ValueError('Plan text must be text.')
    # Screen the entire value before capping it; unsafe tails must not disappear.
    cleaned = programs_curate._clean_line(raw, aim, max(len(raw), cap))
    screen = programs_curate.screen_starting_point(cleaned)
    if (raw.strip() and not cleaned) or not screen.get('ok'):
        raise ValueError('Text was refused (loads, doses, body targets or unreadable text).')
    return cleaned[:cap]


def _steps(raw, aim):
    if not isinstance(raw, list) or not all(isinstance(s, str) for s in raw):
        raise ValueError('Steps must be a list of text.')
    if len(raw) > programs_curate.MAX_STEPS:
        raise ValueError(f'A lesson or session may have at most {programs_curate.MAX_STEPS} steps.')
    for step in raw:
        _line(step, aim, programs_curate.STEP_CHARS)
    cleaned = programs_curate._clean_steps(raw, aim)
    if len(cleaned) != len([s for s in raw if s.strip()]):
        raise ValueError('A step was refused (loads, doses or unreadable text).')
    return cleaned


def _screen_lesson(fields, aim):
    out = dict(fields)
    if 'steps' in out:
        out['steps'] = _steps(out['steps'], aim)
    for key in ('title', 'summary', 'body', 'url'):
        if key in out:
            caps = {'title': programs_curate.UNIT_TITLE_CHARS, 'body': programs_curate.UNIT_BODY_CHARS,
                    'summary': 240, 'url': 2000}
            out[key] = _line(out[key], aim, caps[key])
    if 'variants' in out:
        if not isinstance(out['variants'], list):
            raise ValueError('Sessions must be a list.')
        vs = []
        for v in out['variants']:
            if not isinstance(v, dict):
                raise ValueError('Invalid session.')
            label = _line(v.get('label', ''), aim, programs_curate.LABEL_CHARS)
            if not label or label in [x['label'] for x in vs]:
                raise ValueError('Choose a distinct name for every session.')
            vs.append({'label': label, 'steps': _steps(v.get('steps', []), aim),
                       **{k: _line(v[k], aim, programs_curate.UNIT_BODY_CHARS if k == 'body' else 2000)
                          for k in ('body', 'url') if k in v}})
        out['variants'] = vs
    if 'sessions' in out:
        out['sessions'] = max(1, min(programs_curate.MAX_UNIT_SESSIONS, int(out['sessions'] or 1)))
    return out


CONTENT = ('steps', 'body', 'url', 'variants')


def _provenance(row, edit, fields):
    """Only citations resolving to existing, numbered facts may keep a source."""
    facts = (row.get('source') or {}).get('facts') or []
    by_ref = {n: fact for n, fact in enumerate(facts, 1) if isinstance(fact, dict) and fact.get('url')}
    urls = {fact['url'] for fact in by_ref.values()}
    citation = {**(edit.get('fields') or {}), **{k: v for k, v in edit.items() if k != 'fields'}}
    url = programs_curate._cited_url(citation, by_ref, urls)
    if not url:
        fields['origin'] = 'generated'
        fields['source_index'] = None
        return
    fields.update(origin='cited', url=url, source_index=next(n for n, fact in by_ref.items() if fact['url'] == url))
    for variant in fields.get('variants') or []:
        if variant.get('url'):
            known = programs_curate._cited_url({'url': variant['url']}, by_ref, urls)
            if not known:
                raise ValueError('A cited session URL must name a page already in the sources.')
            variant['url'] = known


def _apply(row, edits):
    """Screen the plan, then use the hand mutations on one unpublished copy."""
    cand = copy.deepcopy(row)
    aim = row.get('title') or ''
    if not isinstance(edits, list):
        raise ValueError('Edits must be a list.')
    for edit in edits:
        if not isinstance(edit, dict) or not isinstance(edit.get('fields', {}), dict):
            raise ValueError('Invalid edit.')
        op = edit.get('op')
        if op not in OPS:
            raise ValueError('Unknown edit operation.')
        raw = edit.get('fields') or {}
        if op == 'update_profile':
            fields = {}
            if 'title' in raw:
                fields['title'] = _line(raw['title'], aim, programs_curate.UNIT_TITLE_CHARS)
            profile = dict(cand.get('made_for') or {})
            for key in ('age_band', 'minutes', 'sessions_per_week', 'assumes'):
                if key in raw:
                    profile[key] = _line(raw[key], aim) if key == 'assumes' else raw[key]
            fields['made_for'] = profile
            library._change_profile(cand, fields)
        elif op == 'update_phase':
            fields = {k: _line(v, aim, programs_curate.PROGRESSION_CHARS if k == 'progression' else 240)
                      for k, v in raw.items() if k in PHASE_FIELDS}
            library._change_update_phase(cand, edit.get('phase_id'), fields)
        elif op in ('add_lesson', 'update_lesson'):
            fields = _screen_lesson({k: v for k, v in raw.items() if k in LESSON_FIELDS}, aim)
            if op == 'add_lesson':
                if not fields.get('title'):
                    raise ValueError('A new lesson needs a title.')
                _provenance(cand, edit, fields)
                library._change_add_lesson(cand, {**fields, 'phase_id': edit.get('phase_id')}, edit.get('after'))
            else:
                old = next((l for l in cand['lessons'] if l['id'] == edit.get('lesson_id')), None)
                if old and any(k in fields and fields[k] != old.get(k) for k in CONTENT):
                    _provenance(cand, edit, fields)
                library._change_update_lesson(cand, edit.get('lesson_id'), fields)
        elif op == 'remove_lesson':
            library._change_remove_lesson(cand, edit.get('lesson_id'))
        elif op == 'order_lessons':
            library._change_order(cand, edit.get('ids'))
    for phase in cand['phases']:
        if not any(l['phase_id'] == phase['id'] for l in cand['lessons']):
            raise ValueError(f"The phase {phase.get('name') or ''} would have no lesson left.")
    before = {l['id']: l for l in row['lessons']}
    touched = {l['id'] for l in cand['lessons'] if l['id'] not in before
               or any(l.get(k) != before[l['id']].get(k) for k in CONTENT)}
    for lesson in cand['lessons']:
        library._change_update_lesson(cand, lesson['id'], {
            'summary': lesson.get('summary') or (library.default_summary(lesson.get('steps'), lesson.get('sessions'))
                                                if lesson['id'] in touched else ''),
            'origin': lesson.get('origin') or (cand.get('source') or {}).get('origin') or 'none'})
    return cand, touched


def _slot_content(lesson):
    """Script material by live label; names are keys, not authored material."""
    common = {k: lesson.get(k) or '' for k in ('steps', 'body', 'url')}
    variants = [v for v in lesson.get('variants') or [] if v.get('steps')]
    if not variants:
        return {'': common}
    return {v.get('label') or '': {**common, 'variant': {k: v.get(k) or '' for k in ('steps', 'body', 'url')}}
            for v in variants}


def _sync_scripts(library_id, before, after, touched):
    """Run under the commit lock. Return pending slots and deleted hand-script notices."""
    old = {l['id']: l for l in before['lessons']}
    new = {l['id']: l for l in after['lessons']}
    scripts = storage.get_library_scripts(library_id)
    queue, removed_hands = [], []
    for lid in old.keys() - new.keys():
        removed_hands.extend(s for s in scripts if s['lesson_id'] == lid and s.get('edited'))
        # The same post-commit deletion door as library.remove_lesson.
        storage.delete_library_lesson_scripts(library_id, lid)
    for lid in new:
        if lid not in touched:
            continue
        old_slots = _slot_content(old[lid]) if lid in old else {}
        new_slots = _slot_content(new[lid])
        old_count = len((old.get(lid) or {}).get('variants') or [])
        new_count = len(new[lid].get('variants') or [])
        if old_count == new_count and len(old_slots) == len(new_slots):
            labels = dict(zip(old_slots, new_slots))
        else:
            labels = {label: label for label in old_slots if label in new_slots}
        for script in scripts:
            if script['lesson_id'] == lid and script['variant_label'] not in labels:
                if script.get('edited'):
                    removed_hands.append(script)
                storage.delete_library_script(library_id, script)
        storage.rekey_library_scripts(library_id, lid, labels)
        previous = {dest: src for src, dest in labels.items()}
        for label, content in new_slots.items():
            if old_slots.get(previous.get(label)) == content:
                continue                     # a pure relabel retains every script byte
            slot = {'lesson_id': lid, 'variant_label': label}
            script = storage.get_library_script(library_id, slot)
            if script and script.get('edited'):
                storage.mark_library_script_stale(library_id, slot, True)
            else:
                storage.delete_library_script(library_id, slot)
                queue.append((lid, label))
    return queue, removed_hands


def _changes(before, after, library_id, viewer, runners=None, removed_scripts=None):
    out = []
    if before.get('title') != after.get('title'):
        out.append(f"Renamed to {after.get('title')}")
    if before.get('made_for') != after.get('made_for'):
        profile = after.get('made_for') or {}
        out.append('Made for ' + library.made_for_line(profile) + f", {profile.get('sessions_per_week')} a week")
        if (before.get('made_for') or {}).get('assumes') != profile.get('assumes'):
            out.append('Assumes: ' + (profile.get('assumes') or 'no prior experience'))
    bp = {p['id']: p for p in before.get('phases') or []}
    for p in after.get('phases') or []:
        old = bp.get(p['id']) or {}
        for k in PHASE_FIELDS:
            if (old.get(k) or '') != (p.get(k) or ''):
                out.append(f"{p.get('name') or 'A phase'} {k} now: {p.get(k)}")
    bl = {l['id']: l for l in before.get('lessons') or []}
    al = {l['id']: l for l in after.get('lessons') or []}
    runners = runners if runners is not None else library.runners(library_id, viewer)
    names_on = {}
    for r in runners.get('named') or []:
        names_on.setdefault(r.get('current'), []).append(r)
    current = {r['run_id']: r.get('current') for r in library.runners(library_id, viewer).get('named') or []}
    hidden_on = runners.get('hidden_on') or {}

    def impact(lid, old, removed=False):
        lines = []
        for r in names_on.get(lid) or []:
            nxt = al.get(current.get(r['run_id'])) or {}
            line = f"{r['name']} is on {old.get('title')}"
            if removed:
                line += '; moves on' + (f" to {nxt['title']}" if nxt.get('title') else '')
            lines.append(line)
        if hidden_on.get(lid):
            lines.append(f"and {hidden_on[lid]} more affected")
        return '; ' + '; '.join(lines) if lines else ''
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
            out.append(f"{l['title']}: {old.get('sessions') or 1} sessions → {l.get('sessions') or 1}" + impact(lid, old))
        if any((old.get(k) or '') != (l.get(k) or '') for k in ('steps', 'body', 'url', 'variants', 'summary')):
            out.append(f"{l['title']} reworded")
    for lid, old in bl.items():
        if lid not in al:
            notice = ' (its hand-written script went with it)' if any(sc['lesson_id'] == lid for sc in removed_scripts or []) else ''
            out.append(f"− {old.get('title')}" + notice + impact(lid, old, removed=True))
    for script in removed_scripts or []:
        lid = script['lesson_id']
        if lid in al:
            out.append(f"− {bl[lid]['title']} · {script['variant_label'] or 'Practice'} (its hand-written script went with it)")
    if [l['id'] for l in before.get('lessons') or [] if l['id'] in al] != [l['id'] for l in after.get('lessons') or [] if l['id'] in bl]:
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
    if type(expect_revision) is not int or expect_revision < 0:
        return {'status': 'error', 'code': 400, 'message': 'Send the revision you read.'}
    if int(row.get('revision') or 0) != expect_revision:
        return {'status': 'error', 'code': 409, 'message': 'The program changed; read it again.'}
    settings = storage.get_settings() or {}
    if not isinstance(text, str) or not text.strip():
        return {'status': 'error', 'message': 'Describe the change you want.'}
    try:
        planned = plan(row, text.strip(), settings)
        if not isinstance(planned, dict) or planned.get('error'):
            return {'status': 'error', 'message': "Couldn't work out that change. Try again."}
        said = _line(planned.get('said') or '', row.get('title') or '')
        cand, touched = _apply(row, planned['edits'])
    except (ValueError, TypeError, KeyError, OverflowError) as e:
        return {'status': 'error', 'message': f"That change was refused: {e}"}
    queue = []
    # Publish and invalidate under one lock: no hand edit or writer can slip
    # between inspecting a script and deleting/marking it.
    with storage.db_lock, storage.db.transaction():
        runners = library.runners(library_id, actor)
        res = library._commit(library_id, cand, actor, expect_revision=expect_revision)
        if res.get('status') != 'success':
            return res
        after = res['program']
        queue, removed_hands = _sync_scripts(library_id, row, after, touched)
        changes = _changes(row, after, library_id, actor, runners, removed_hands)
    # Jobs begin only after the enclosing transaction has committed.
    for lid, label in queue:
        library_scripts.write(library_id, actor, lesson_id=lid, variant_label=label, enqueue=True)
    return {'status': 'success', 'program': library.get(library_id, actor), 'changes': changes, 'said': said}
