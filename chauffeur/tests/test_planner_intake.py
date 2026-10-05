"""Tests for K4d planner photo intake: a paper planner page -> proposals.

Load-bearing properties: the model's match claim is checked in code (it must
name an item on THIS child's list, within two days of the entry), a matched
line that adds something becomes a note and one that adds nothing is
"already"; an undated line needs a date; a written subject maps to the
child's class; the instructions assume no planner layout; nothing is written
until apply, which appends notes once, adds new items as 'planner' items
with a locked kind, and refuses a sibling or a helper.

Run from chauffeur/:  python tests/test_planner_intake.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, planner_intake, model_pools

TODAY = datetime.date.today()


def _d(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.kid_tasks_table, storage.school_classes_table):
        t.truncate()
    storage.get_settings = lambda: {"llm_gemini_api_key": "k"}
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child"})
    storage.add_member({"id": "kid2", "name": "Ben", "role": "child"})
    storage.add_member({"id": "help", "name": "Nanny", "role": "helper"})
    sci = storage.ensure_school_class("kid1", "course_88", "502.Knox.30062Y0.6001.2027")
    storage.update_school_class(sci['id'], {'canvas_name': 'Biology - Knox'})
    storage.ensure_school_class("kid1", "course_91", "611.Knox.40011Z0.6002.2027")
    storage.update_school_class(storage.get_school_classes("kid1")[1]['id'], {'name': 'English'})
    from models.schemas import KidTask
    ids = {}
    for member, title, due, kind, course in [
            ("kid1", "Chapter 4 Quiz", _d(2), "test", "course_88"),
            ("kid1", "Reading log", _d(1), "homework", "course_91"),
            ("kid2", "Spelling test", _d(2), "test", None)]:
        t = KidTask(member_id=member, title=title, due_date=due, kind=kind,
                    course_key=course, source='ics').model_dump()
        storage.add_kid_task(t)
        ids[title] = t['id']
    return ids


def _model(entries, page="Week of Oct 5"):
    captured = {}

    def fake(pool, key, system, prompt, **kw):
        captured.update(pool=pool, system=system, prompt=prompt, images=kw.get('images'))
        return {"page_dates": page, "entries": entries}
    return fake, captured


def scenario_matching_is_checked_in_code():
    ids = _reset()
    entries = [
        {"text": "sci quiz ch4", "subject": "sci", "date": _d(2), "date_basis": "layout",
         "kind": "test", "details": "chapters 4-5, bring calculator", "match_id": ids["Chapter 4 Quiz"]},
        {"text": "reading log", "subject": "English", "date": _d(1), "date_basis": "layout",
         "kind": "homework", "details": None, "match_id": ids["Reading log"]},
        {"text": "spelling test", "subject": None, "date": _d(2), "date_basis": "layout",
         "kind": "test", "match_id": ids["Spelling test"]},          # a SIBLING's item
        {"text": "quiz retake", "subject": "Bio", "date": _d(9), "date_basis": "written",
         "kind": "test", "match_id": ids["Chapter 4 Quiz"]},         # 7 days off
        {"text": "bring poster board", "subject": "English", "date": _d(3),
         "date_basis": "layout", "kind": "bring", "match_id": None},
        {"text": "field trip form", "subject": None, "date": None, "date_basis": "none",
         "kind": "other", "match_id": None},
    ]
    fake, cap = _model(entries)
    with mock.patch.object(model_pools, 'call_pool_json', side_effect=fake):
        out = planner_intake.extract("kid1", "b64", "image/jpeg")
    check(out['error'] is None and out['page_dates'] == "Week of Oct 5", f"read ok: {out['error']}")
    rows = out['rows']
    acts = [r['action'] for r in rows]
    check(acts == ['note', 'already', 'new', 'new', 'new', 'needs_date'],
          f"note / already / sibling claim dropped / far claim dropped / new / needs date: {acts}")
    check(rows[0]['note'] == "chapters 4-5, bring calculator" and rows[0]['match']['title'] == "Chapter 4 Quiz"
          and rows[0]['match']['course_name'] == "Biology - Knox", f"note row: {rows[0]}")
    check(rows[4].get('course_name') == 'English' and rows[4].get('course_key') == 'course_91',
          f"a written subject maps to the child's class: {rows[4]}")
    check(rows[3].get('course_name') == 'Biology - Knox', f"'Bio' finds Biology: {rows[3]}")
    check(cap['pool'] == 'vision' and cap['images'][0]['b64'] == 'b64', "one vision call with the photo")
    check("Chapter 4 Quiz" in cap['prompt'] and "Biology - Knox" in cap['prompt']
          and "Spelling test" not in cap['prompt'],
          "the model sees this child's classes and items, never a sibling's")
    check("Do not assume" in cap['system'] and "layout" in cap['system'],
          "the instructions describe no particular planner layout")
    check(storage.get_kid_task(ids["Chapter 4 Quiz"]).get('notes') in ('', None),
          "reading writes nothing")


def scenario_conflicting_dates_are_flagged():
    ids = _reset()
    fake, _ = _model([{"text": "ch 4 quiz", "subject": "Science", "date": _d(3),
                       "date_basis": "layout", "kind": "test", "details": None,
                       "match_id": ids["Chapter 4 Quiz"]}])
    with mock.patch.object(model_pools, 'call_pool_json', side_effect=fake):
        row = planner_intake.extract("kid1", "b64", "image/jpeg")['rows'][0]
    check(row['action'] == 'already' and row['conflict'], f"a day's difference is flagged, not changed: {row}")


def scenario_no_key_and_bad_answers():
    _reset()
    storage.get_settings = lambda: {}
    out = planner_intake.extract("kid1", "b64", "image/jpeg")
    check(out['error'] and 'Gemini' in out['error'], "no key says so")
    _reset()
    with mock.patch.object(model_pools, 'call_pool_json', side_effect=RuntimeError("boom")):
        out = planner_intake.extract("kid1", "b64", "image/jpeg")
    check(out['error'] and out['rows'] == [], "a failed read is an error, not a crash")


def scenario_apply_and_identity():
    ids = _reset()
    import main
    from fastapi import HTTPException
    rows = [{'action': 'note', 'task_id': ids["Chapter 4 Quiz"], 'note': 'chapters 4-5'},
            {'action': 'note', 'task_id': ids["Spelling test"], 'note': 'not yours'},
            {'action': 'new', 'title': 'English: bring poster board', 'due_date': _d(3),
             'kind': 'bring', 'course_key': 'course_91', 'note': 'white, not colored'},
            {'action': 'new', 'title': 'no date', 'due_date': None, 'kind': 'other'},
            {'action': 'new', 'title': 'bad class', 'due_date': _d(4), 'kind': 'test',
             'course_key': 'course_999'}]
    for actor in ('kid2', 'help'):
        try:
            main.planner_apply(main.PlannerApplyRequest(owner_id='kid1', member_id=actor, rows=rows))
            check(False, f"{actor} must be refused")
        except HTTPException as e:
            check(e.status_code == 403, f"{actor} refused")
    res = main.planner_apply(main.PlannerApplyRequest(owner_id='kid1', member_id='kid1', rows=rows))
    check(res == {'noted': 1, 'added': 2}, f"one note (not the sibling's), two new (not the undated): {res}")
    quiz = storage.get_kid_task(ids["Chapter 4 Quiz"])
    check(quiz['notes'] == '📒 chapters 4-5', f"note appended: {quiz['notes']!r}")
    check(storage.get_kid_task(ids["Spelling test"]).get('notes') in ('', None), "a sibling's item untouched")
    new = {t['title']: t for t in storage.get_kid_tasks('kid1') if t.get('source') == 'planner'}
    poster = new['English: bring poster board']
    check(poster['kind'] == 'bring' and poster['kind_locked'] and poster['course_key'] == 'course_91'
          and poster['notes'] == '📒 white, not colored', f"new planner item: {poster}")
    check(new['bad class']['course_key'] is None, "an unknown class key is dropped")
    res = main.planner_apply(main.PlannerApplyRequest(owner_id='kid1', member_id='mom', rows=rows[:1]))
    check(res['noted'] == 0 and storage.get_kid_task(ids["Chapter 4 Quiz"])['notes'] == '📒 chapters 4-5',
          "the same note twice is not added twice; a parent may apply")


SCENARIOS = [
    scenario_matching_is_checked_in_code,
    scenario_conflicting_dates_are_flagged,
    scenario_no_key_and_bad_answers,
    scenario_apply_and_identity,
]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
