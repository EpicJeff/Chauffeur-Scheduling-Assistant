"""Planner photo intake (K4d): a page of a child's paper planner -> proposed
changes to their school list.

Layout-agnostic by design. Planners differ (week across two pages, a page
a day, a month grid, a sticky note, a whiteboard), so the instructions never
describe a layout. They ask the model to find each written entry and work
out its date from whatever the page offers (a date written on the line, a
day column, a page header), and to say how it knew.

The model is also shown the child's classes and current school items, and
may claim an entry IS one of them (`match_id`). That claim is checked here,
in code: the id must exist on this child's list and its due date must be
within two days of the entry's. A failed claim is dropped, never trusted.
Each entry then becomes one proposed action:

  note       the entry matches an item and adds something (chapters, what
             to bring) -> appended to that item's notes
  already    it matches and says nothing new -> shown, nothing to do
  new        no match -> a new item on the list (source 'planner')
  needs_date no date could be worked out -> the child picks one

Nothing is written here. The review screen decides, then `apply` writes.
"""
import datetime
import re

from services import storage

SYSTEM = (
    "You read a photo of a page from a school student's paper planner. "
    "Planners differ a great deal: a week across two pages, a page per day, "
    "a month grid, a plain list, a sticky note, a whiteboard. Do not assume "
    "any particular layout; work out the structure from what you see.\n\n"
    "Find every written entry about schoolwork or school life: assignments, "
    "tests and quizzes, projects, things to bring or wear, forms, reminders. "
    "Skip doodles, printed planner text (holidays, quotes, headings that are "
    "part of the planner itself) and anything you cannot read.\n\n"
    "For each entry decide its DATE from whatever the page gives: a date "
    "written on the entry ('due Fri', '10/9'), the day column or row it sits "
    "in, a page or week header. Dates without a year belong to the school "
    "year that contains TODAY (given below). Say how you knew in "
    "date_basis: 'written' (on the entry), 'layout' (its column/row/page "
    "header), 'guess', or 'none' (no way to tell; then date is null). In a "
    "planner, an entry written on a day usually means it is DUE that day, "
    "unless the text says otherwise ('due Fri', 'test next Tue').\n\n"
    "You are given the student's classes and the items already on their "
    "school list. If an entry is clearly the SAME assignment as one of those "
    "items (same class or subject, same thing, a date within a day or two), "
    "put that item's id in match_id. Students abbreviate ('sci quiz ch4' is "
    "'Chapter 4 Quiz' in Science). If unsure, leave match_id null — a "
    "wrong match is worse than none.\n\n"
    "Return JSON only:\n"
    '{"page_dates": "short description of the dates the page covers, or null",\n'
    ' "entries": [{"text": "the entry, as written but readable",\n'
    '   "subject": "class or subject as written, or null",\n'
    '   "date": "YYYY-MM-DD or null", "date_basis": "written|layout|guess|none",\n'
    '   "kind": "test|project|homework|bring|other",\n'
    '   "details": "extra specifics on the entry (chapters, pages, materials), or null",\n'
    '   "checked_off": true/false (crossed out or ticked on the page),\n'
    '   "match_id": "id of the matching list item, or null"}]}\n'
    "Never invent entries or details that are not on the page."
)

MAX_ENTRIES = 40
_KINDS = ('test', 'project', 'homework', 'bring', 'other')


def _context(member_id: str, today: datetime.date):
    """Classes + nearby items the model may match against (open and done:
    a ticked planner line can still match an item already checked off)."""
    classes = storage.get_school_classes(member_id)
    lo = (today - datetime.timedelta(days=21)).isoformat()
    hi = (today + datetime.timedelta(days=45)).isoformat()
    tasks = [t for t in storage.decorate_kid_tasks(storage.get_kid_tasks(member_id, include_done=True))
             if lo <= (t.get('due_date') or '') <= hi]
    tasks.sort(key=lambda t: t.get('due_date') or '')
    return classes, tasks[:120]


def _norm_date(s):
    try:
        return datetime.date.fromisoformat(str(s)[:10]).isoformat() if s else None
    except ValueError:
        return None


def _new_info(entry_text: str, details: str, task: dict) -> str:
    """What the planner line adds to the item, or '' when nothing: words in
    the entry that the item's title, notes and description do not already
    carry. A child's 'sci quiz ch 4' adds nothing to 'Chapter 4 Quiz'."""
    have = ' '.join([task.get('title') or '', task.get('notes') or '',
                     task.get('description') or '', task.get('course_name') or '']).lower()
    have_words = set(re.findall(r'[a-z0-9]+', have))
    extra = (details or '').strip()
    if extra:
        words = set(re.findall(r'[a-z0-9]+', extra.lower()))
        return extra if words - have_words else ''
    return ''


def _class_for(subject: str, classes: list):
    """The child's class a written subject means ('sci' -> Science), by the
    family's/Canvas's name or the feed label; None when it is not clear."""
    if not subject:
        return None
    sub = subject.lower().strip()
    hits = []
    for c in classes:
        names = [storage.school_class_display(c), c.get('name'), c.get('canvas_name'), c.get('label')]
        for n in [x.lower() for x in names if x]:
            if sub == n or n.startswith(sub) or sub in n.split() or (len(sub) >= 4 and sub in n):
                hits.append(c)
                break
    return hits[0] if len(hits) == 1 else None


def extract(member_id: str, image_b64: str, mime: str, today: datetime.date = None) -> dict:
    """Photo -> {'page_dates', 'rows': [...], 'error'}. Writes nothing."""
    from services import model_pools
    today = today or datetime.date.today()
    out = {'page_dates': None, 'rows': [], 'error': None}
    settings = storage.get_settings() or {}
    api_key = settings.get('llm_gemini_api_key', '')
    if not api_key:
        out['error'] = 'Reading photos needs the Gemini API key (Config).'
        return out
    classes, tasks = _context(member_id, today)
    by_id = {t['id']: t for t in tasks}
    class_lines = [f"- {storage.school_class_display(c)}"
                   + (f" (also written as {c['label']})" if c.get('label') and c.get('label') != storage.school_class_display(c) else '')
                   for c in classes]
    task_lines = [f"- id={t['id']} | {t.get('title')} | class: {t.get('course_name') or '-'}"
                  f" | due {t.get('due_date')} | {t.get('kind')}" + (" | done" if t.get('status') == 'done' else '')
                  for t in tasks]
    prompt = (f"TODAY is {today.isoformat()} ({today.strftime('%A')}).\n\n"
              "The student's classes:\n" + ('\n'.join(class_lines) or '- (none known)') + "\n\n"
              "Items already on their school list:\n" + ('\n'.join(task_lines) or '- (none)') + "\n\n"
              "Read the attached planner page.")
    try:
        res = model_pools.call_pool_json(
            'vision', api_key, SYSTEM, prompt, temperature=0.1, timeout_s=90,
            settings=settings, images=[{'mime': mime or 'image/jpeg', 'b64': image_b64}])
        if not isinstance(res, dict) or res.get('error'):
            raise RuntimeError(str((res or {}).get('error') or 'bad response'))
    except Exception as e:
        out['error'] = f'Could not read the photo ({e})'
        return out

    out['page_dates'] = (str(res.get('page_dates')).strip()[:80] or None) if res.get('page_dates') else None
    entries = res.get('entries') if isinstance(res.get('entries'), list) else []
    rows = []
    for e in entries[:MAX_ENTRIES]:
        if not isinstance(e, dict):
            continue
        text = str(e.get('text') or '').strip()[:140]
        if not text:
            continue
        date = _norm_date(e.get('date'))
        kind = str(e.get('kind') or 'homework').strip().lower()
        kind = kind if kind in _KINDS else 'homework'
        details = (str(e.get('details') or '').strip()[:200] or None)
        row = {'text': text, 'subject': (str(e.get('subject') or '').strip()[:60] or None),
               'date': date, 'date_basis': str(e.get('date_basis') or 'none')[:10],
               'kind': kind, 'details': details,
               'checked_off': bool(e.get('checked_off')), 'match': None,
               'action': None, 'note': None, 'conflict': None}
        # The model's match claim is only a claim: it must name an item on
        # THIS child's list, within two days of the entry's date.
        t = by_id.get(str(e.get('match_id') or ''))
        if t and date and abs((datetime.date.fromisoformat(t['due_date'])
                               - datetime.date.fromisoformat(date)).days) <= 2:
            row['match'] = {'id': t['id'], 'title': t.get('title'),
                            'course_name': t.get('course_name') if t.get('course_named') else None,
                            'due_date': t.get('due_date'), 'status': t.get('status')}
            if t.get('due_date') != date:
                row['conflict'] = f"The list says {t.get('due_date')}"
            note = _new_info(text, details, t)
            row['action'], row['note'] = ('note', note) if note else ('already', None)
        else:
            row['action'] = 'needs_date' if not date else 'new'
            c = _class_for(row['subject'], classes)
            if c:
                row['course_key'] = c['key']
                row['course_name'] = storage.school_class_display(c)
        rows.append(row)
    out['rows'] = rows
    return out


def apply(member_id: str, rows: list, actor_id: str = None) -> dict:
    """Write what the review screen kept. Notes are appended (never replacing
    the child's or the teacher's text); new items are source 'planner' so the
    feed sync never deletes them. Returns {'noted', 'added'}."""
    from models.schemas import KidTask
    noted = added = 0
    for r in rows or []:
        action = r.get('action')
        if action == 'note' and r.get('task_id') and (r.get('note') or '').strip():
            t = storage.get_kid_task(r['task_id'])
            if not t or t.get('member_id') != member_id:
                continue
            note = r['note'].strip()[:200]
            existing = (t.get('notes') or '').strip()
            if note.lower() in existing.lower():
                continue
            storage.update_kid_task(t['id'], {'notes': (existing + '\n' if existing else '') + '📒 ' + note})
            noted += 1
        elif action == 'new':
            title = (r.get('title') or '').strip()[:140]
            date = _norm_date(r.get('due_date'))
            if not title or not date:
                continue
            kind = r.get('kind') if r.get('kind') in _KINDS else 'homework'
            notes = (r.get('note') or '').strip()[:200]
            course_key = r.get('course_key') if r.get('course_key') in {
                c['key'] for c in storage.get_school_classes(member_id)} else None
            storage.add_kid_task(KidTask(
                member_id=member_id, title=title, due_date=date, kind=kind,
                kind_locked=True, notes=('📒 ' + notes) if notes else '',
                course_key=course_key,
                source='planner', created_by_member_id=actor_id).model_dump())
            added += 1
    return {'noted': noted, 'added': added}
