"""Tests for K4d's parent safety net: what is coming, never what is overdue.

Load-bearing properties: `upcoming_school_items` is forward-only (a start
before today is clamped) and keeps tests/projects/bring-items unless asked
for everything; the wall calendar endpoint and the calendar card (grid
payload + list view rows) carry the school layer only for the children the
card names; the household briefing gains a School section with the big
items due tomorrow through two days on, and never homework or overdue.

Run from chauffeur/:  python tests/test_school_parent.py
"""
import datetime
from unittest import mock

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage

TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)


def _d(n):
    return (TODAY + datetime.timedelta(days=n)).isoformat()


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.kid_tasks_table, storage.school_classes_table,
              storage.cache_table):
        t.truncate()
    storage.add_member({"id": "mom", "name": "Mom", "role": "parent"})
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child", "is_child": True,
                        "color_code": "#ec4899"})
    storage.add_member({"id": "kid2", "name": "Ben", "role": "child", "is_child": True})
    c = storage.ensure_school_class("kid1", "course_88", "502.Knox.30062Y0.6001.2027")
    storage.update_school_class(c['id'], {'name': 'Science'})
    from models.schemas import KidTask
    for member, title, due, kind, course in [
            ("kid1", "Chapter 4 Quiz", _d(1), "test", "course_88"),
            ("kid1", "Worksheet", _d(1), "homework", None),
            ("kid1", "Poster board", _d(2), "bring", None),
            ("kid1", "Old test", _d(-2), "test", None),
            ("kid1", "Far project", _d(20), "project", None),
            ("kid2", "Spelling test", _d(3), "test", None)]:
        storage.add_kid_task(KidTask(member_id=member, title=title, due_date=due, kind=kind,
                                     course_key=course).model_dump())
    storage.set_cached_schedule({"events": [], "assignments": {}, "matched_rules": {},
                                 "scheduled_errands": []})


def scenario_upcoming_is_forward_only():
    _reset()
    rows = storage.upcoming_school_items(_d(-7), _d(7))
    titles = {t['title'] for t in rows}
    check(titles == {"Chapter 4 Quiz", "Poster board", "Spelling test"},
          f"big items only, overdue clamped away, far ones out of range: {titles}")
    rows = storage.upcoming_school_items(_d(0), _d(7), member_ids=["kid1"], big_only=False)
    titles = {t['title'] for t in rows}
    check(titles == {"Chapter 4 Quiz", "Worksheet", "Poster board"},
          f"everything for one child when asked: {titles}")
    quiz = next(t for t in rows if t['title'] == "Chapter 4 Quiz")
    check(quiz['member_name'] == "Addison" and quiz['member_color'] == "#ec4899"
          and quiz['course_name'] == "Science", f"rows carry child and class: {quiz}")


def scenario_calendar_endpoint():
    _reset()
    import main
    check(main.school_calendar_items(_d(-30), _d(30)) == [], "no children named, no layer")
    rows = main.school_calendar_items(_d(-30) + "T00:00:00", _d(30) + "T00:00:00", members="kid1")
    check({r['title'] for r in rows} == {"Chapter 4 Quiz", "Poster board", "Far project"},
          f"one child's big upcoming items, range strings accepted: {[r['title'] for r in rows]}")
    quiz = next(r for r in rows if r['title'] == "Chapter 4 Quiz")
    check(quiz['emoji'] == '📝' and quiz['course_name'] == 'Science', f"display fields: {quiz}")
    rows = main.school_calendar_items(_d(0), _d(5), members="kid1,kid2", all=True)
    check("Worksheet" in {r['title'] for r in rows}, "all=true adds homework")


def scenario_calendar_card():
    _reset()
    from services import home_board
    now = datetime.datetime.combine(TODAY, datetime.time(12))
    keys = {o['key'] for o in next(c for c in home_board.WIDGETS
                                   if c['key'] == 'calendar')['options']}
    check({'school', 'school_all'} <= keys, f"calendar card offers the school layer: {keys}")
    grid = home_board._tile_calendar(now, config={'view': 'agenda', 'school': ['kid1']})
    check(grid['grid']['school'] == ['kid1'] and grid['grid']['school_all'] is False,
          f"grid views carry the layer to the component: {grid['grid']}")
    plain = home_board._tile_calendar(now, config={'view': 'list'})
    check('empty' in plain, "no school layer unless a child is picked")
    lst = home_board._tile_calendar(now, config={'view': 'list', 'school': ['kid1']})
    titles = [r['title'] for r in lst['rows']]
    check(titles and all(r['kind'] == 'school' for r in lst['rows'])
          and any("Addison: Chapter 4 Quiz" in t for t in titles)
          and not any("Worksheet" in t or "Old test" in t for t in titles),
          f"list view rows: big, upcoming, this child only: {titles}")


def scenario_household_briefing():
    _reset()
    from services import family_digest
    b = family_digest.build_household_briefing(TOMORROW)
    lines = b['lines']
    check("School:" in lines, f"a School section: {lines}")
    school = lines[lines.index("School:") + 1:]
    check(any(l == "📝 Addison: Chapter 4 Quiz (Science) — tomorrow" for l in school),
          f"a test due tomorrow, with its named class: {school}")
    check(any(l.startswith("🎒 Addison: Poster board") for l in school)
          and any(l.startswith("📝 Ben: Spelling test") for l in school)
          and not any("Far project" in l for l in school),
          f"bring-items in, every child, nothing past two days on: {school}")
    check(not any("Worksheet" in l or "Old test" in l for l in lines),
          "never homework, never overdue")
    check(b['open_count'] == 0, "school lines are not openings")


SCENARIOS = [
    scenario_upcoming_is_forward_only,
    scenario_calendar_endpoint,
    scenario_calendar_card,
    scenario_household_briefing,
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
