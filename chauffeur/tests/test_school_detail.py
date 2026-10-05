"""Tests for K4d — a school feed's detail survives into the kid's list.

Load-bearing properties: a Canvas-shaped feed keeps each item's class (the
trailing [tag] Canvas appends, keyed by the course id in its URL), the
teacher's description and links, the link back to Canvas and the due TIME;
a UTC-stamped 11:59 PM due date lands on the LOCAL day (it used to land a day
late); a teacher's one-off '[IMPORTANT]' is not mistaken for a class; Canvas
calendar events are never 'homework'; classes register themselves with a
color and the family's name for one reaches every line; existing tasks pick
the detail up on the next sync.

Run from chauffeur/:  python tests/test_school_detail.py
"""
import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from harness import check  # noqa: F401  (harness isolates CHAUFFEUR_DATA_DIR)

from services import storage, ics_sync

NY = ZoneInfo('America/New_York')
TODAY = datetime.datetime.now(NY).date()
D3 = TODAY + datetime.timedelta(days=3)
D4 = TODAY + datetime.timedelta(days=4)
D5 = TODAY + datetime.timedelta(days=5)


def _utc_stamp(day, hh, mm):
    local = datetime.datetime.combine(day, datetime.time(hh, mm), NY)
    return local.astimezone(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _canvas_ics():
    url = "https://knox.instructure.com/calendar?include_contexts=course_88&month=10&year=2026"
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Instructure//Canvas",
        "X-WR-CALNAME:Addison Calendar (Canvas)",
        # timed, UTC-stamped 11:59 PM local
        "BEGIN:VEVENT", "UID:event-assignment-1001",
        f"DTSTAMP:{_utc_stamp(TODAY, 8, 0)}",
        f"DTSTART:{_utc_stamp(D3, 23, 59)}", f"DTEND:{_utc_stamp(D3, 23, 59)}",
        "SUMMARY:Cell Lab Report [502.Knox.30062Y0.6001.2027]",
        "DESCRIPTION:Write up the lab. Template: https://docs.google.com/document/d/abc\\n\\n\\n\\nDue at midnight.",
        "X-ALT-DESC;FMTTYPE=text/html:<p>Write up the lab. See <a href=\"https://knox.instructure.com/courses/88/files/5\">the rubric</a>.</p>",
        f"URL;VALUE=URI:{url}#assignment_1001",
        "END:VEVENT",
        # all-day, same class
        "BEGIN:VEVENT", "UID:event-assignment-1002",
        f"DTSTAMP:{_utc_stamp(TODAY, 8, 0)}",
        f"DTSTART;VALUE=DATE:{D4.strftime('%Y%m%d')}",
        "SUMMARY:Chapter 4 Quiz [502.Knox.30062Y0.6001.2027]",
        f"URL;VALUE=URI:{url}#assignment_1002",
        "END:VEVENT",
        # a named class, twice (once as a Canvas calendar event)
        "BEGIN:VEVENT", "UID:event-assignment-2001",
        f"DTSTAMP:{_utc_stamp(TODAY, 8, 0)}",
        f"DTSTART;VALUE=DATE:{D4.strftime('%Y%m%d')}",
        "SUMMARY:Problem set 7 [Algebra 1]",
        "END:VEVENT",
        "BEGIN:VEVENT", "UID:event-calendar-event-77",
        f"DTSTAMP:{_utc_stamp(TODAY, 8, 0)}",
        f"DTSTART;VALUE=DATE:{D5.strftime('%Y%m%d')}",
        "SUMMARY:Field trip to the museum [Algebra 1]",
        "END:VEVENT",
        # a teacher's one-off bracket is NOT a class
        "BEGIN:VEVENT", "UID:event-assignment-3001",
        f"DTSTAMP:{_utc_stamp(TODAY, 8, 0)}",
        f"DTSTART;VALUE=DATE:{D5.strftime('%Y%m%d')}",
        "SUMMARY:Read chapter 3 [IMPORTANT]",
        "END:VEVENT",
        "END:VCALENDAR", ""]).encode('utf-8')


def _reset():
    import main  # noqa: F401
    for t in (storage.members_table, storage.kid_tasks_table,
              storage.ics_feeds_table, storage.school_classes_table):
        t.truncate()
    storage.add_member({"id": "kid1", "name": "Addison", "role": "child", "is_child": True})
    storage.add_member({"id": "kid2", "name": "Ben", "role": "child", "is_child": True})
    storage.add_member({"id": "momm", "name": "Mom", "role": "parent"})


def _sync():
    fid = storage.add_ics_feed({"url": "https://x/feed.ics", "name": "Canvas",
                                "calendar_id": "", "target_kind": "tasks",
                                "member_id": "kid1"})
    with mock.patch.object(ics_sync, '_local_tz', return_value=NY), \
         mock.patch.object(ics_sync, 'fetch_ics', return_value=_canvas_ics()), \
         mock.patch.object(ics_sync.gcal, 'insert_event') as ins:
        res = ics_sync.sync_feed(storage.get_ics_feed(fid))
        check(ins.call_count == 0, "task mode never touches Google Calendar")
    return fid, res


def _by_title():
    return {t['title']: t for t in storage.get_kid_tasks("kid1")}


def scenario_canvas_detail_survives():
    _reset()
    _, res = _sync()
    check(res['added'] == 5, f"five items imported, got {res}")
    t = _by_title()
    check(set(t) == {"Cell Lab Report", "Chapter 4 Quiz", "Problem set 7",
                     "Field trip to the museum", "Read chapter 3 [IMPORTANT]"},
          f"class tags leave titles, a one-off bracket stays: {set(t)}")
    lab = t["Cell Lab Report"]
    check(lab['due_date'] == D3.isoformat() and lab['due_time'] == '23:59',
          f"UTC 11:59 PM lands on the LOCAL day with its time, got {lab['due_date']} {lab['due_time']}")
    check(lab['course_key'] == 'course_88'
          and lab['course_label'] == '502.Knox.30062Y0.6001.2027',
          f"class keyed by Canvas course id, label kept: {lab['course_key']} / {lab['course_label']}")
    check((lab['description'] or '').startswith("Write up the lab.")
          and "\n\n\n" not in lab['description'],
          f"description kept, blank runs collapsed: {lab['description']!r}")
    urls = [l['url'] for l in lab['links']]
    check(urls[0] == "https://knox.instructure.com/courses/88/files/5"
          and lab['links'][0]['text'] == "the rubric"
          and "https://docs.google.com/document/d/abc" in urls,
          f"anchors from the HTML description and bare URLs in the text: {lab['links']}")
    check((lab['url'] or '').endswith('#assignment_1001'), "link back to Canvas kept")
    quiz = t["Chapter 4 Quiz"]
    check(quiz['due_date'] == D4.isoformat() and quiz['due_time'] is None
          and quiz['kind'] == 'test', "all-day item: date, no time, quiz is a test")
    check(t["Problem set 7"]['course_key'] == 'Algebra 1',
          "a repeated tag is a class even without a Canvas URL")
    check(t["Field trip to the museum"]['kind'] == 'other',
          "a Canvas calendar event is never homework")
    check(t["Read chapter 3 [IMPORTANT]"]['course_key'] is None,
          "a teacher's one-off bracket is not a class")
    classes = {c['key']: c for c in storage.get_school_classes("kid1")}
    check(set(classes) == {'course_88', 'Algebra 1'}, f"classes registered: {set(classes)}")
    check(classes['course_88']['color'] != classes['Algebra 1']['color'],
          "each class gets its own color")


def scenario_naming_a_class_reaches_every_line():
    _reset()
    import main
    from fastapi import HTTPException
    _sync()
    listing = {c['key']: c for c in main.list_school_classes("kid1")}
    sci = listing['course_88']
    check(sci['open_count'] == 2 and sci['display'] == '502.Knox.30062Y0.6001.2027',
          f"class list counts open items, shows the code until named: {sci}")
    day = main.member_day("kid1", TODAY.isoformat())
    lab = next(r for r in day['due_soon'] if r['title'] == 'Cell Lab Report')
    check(lab['course_named'] is False and lab['description'] and lab['links']
          and lab['due_time'] == '23:59', f"My Day row carries the detail: {lab}")
    check(main._task_line(lab, TODAY) == f"📚 Cell Lab Report — {main._task_due_label(D3, TODAY)}",
          "a raw course code never rides a digest line")
    algebra = next(r for r in day['due_soon'] if r['title'] == 'Problem set 7')
    check(algebra['course_named'] and "(Algebra 1)" in main._task_line(algebra, TODAY),
          "a class whose label is already a name shows on the line")

    try:
        main.update_school_class_api(sci['id'], main.SchoolClassUpdate(name="Science", member_id="kid2"))
        check(False, "a sibling naming another kid's class must 403")
    except HTTPException as e:
        check(e.status_code == 403, "a child names only their own classes")
    try:
        main.update_school_class_api(sci['id'], main.SchoolClassUpdate(color="red"))
        check(False, "a bad color must 400")
    except HTTPException as e:
        check(e.status_code == 400, "colors are #rrggbb")
    main.update_school_class_api(sci['id'], main.SchoolClassUpdate(name="Science", color="#123456", member_id="kid1"))
    day = main.member_day("kid1", TODAY.isoformat())
    lab = next(r for r in day['due_soon'] if r['title'] == 'Cell Lab Report')
    check(lab['course_name'] == 'Science' and lab['course_color'] == '#123456' and lab['course_named'],
          f"the family's name and color reach the row: {lab['course_name']} {lab['course_color']}")
    check("(Science)" in main._task_line(lab, TODAY), "and the digest line")
    # A resync never overwrites the family's name.
    _sync_again()
    c = storage.get_school_class(sci['id'])
    check(c['name'] == 'Science' and c['color'] == '#123456', "resync keeps the family's name")


def _sync_again():
    fid = storage.get_ics_feeds()[0]['id']
    with mock.patch.object(ics_sync, '_local_tz', return_value=NY), \
         mock.patch.object(ics_sync, 'fetch_ics', return_value=_canvas_ics()):
        return ics_sync.sync_feed(storage.get_ics_feed(fid))


def scenario_existing_tasks_catch_up():
    """A task imported before K4d (title + date only) gains its detail on
    the next sync through the ordinary patch path; a DONE one stays final."""
    _reset()
    fid, _ = _sync()
    t = _by_title()
    storage.update_kid_task(t["Cell Lab Report"]['id'],
                            {'description': None, 'links': [], 'course_key': None, 'due_time': None})
    storage.complete_kid_task(t["Chapter 4 Quiz"]['id'])
    storage.update_kid_task(t["Chapter 4 Quiz"]['id'], {'course_key': None})
    res = _sync_again()
    check(res['updated'] == 1, f"only the open stale task is patched, got {res}")
    lab = storage.get_kid_task(t["Cell Lab Report"]['id'])
    check(lab['course_key'] == 'course_88' and lab['description'] and lab['due_time'] == '23:59',
          "the stale open task caught up")
    quiz = storage.get_kid_task(t["Chapter 4 Quiz"]['id'])
    check(quiz['status'] == 'done' and quiz['course_key'] is None, "a done task stays final")
    res = _sync_again()
    check(res['updated'] == 0, f"an unchanged feed patches nothing, got {res}")


class _Resp:
    def __init__(self, status, body, links=None):
        self.status_code, self._body, self.links = status, body, links or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


def _canvas_feed():
    fid, _ = _sync()
    storage.update_ics_feed(fid, {'url': 'webcal://knox.instructure.com/feeds/calendars/user_abc.ics'})
    return fid


def scenario_canvas_token_names_classes():
    """A token fetches Canvas's own course names: matched by the course id
    the feed's URLs carry, or by course_code when an item had no URL. The
    family's name still wins, the token is never returned, and it is only
    ever sent to the feed's own host."""
    _reset()
    import main
    from services import canvas_courses
    fid = _canvas_feed()
    calls = []
    page1 = [{'id': 88, 'name': 'Biology - Knox', 'course_code': '502.Knox.30062Y0.6001.2027'}]
    page2 = [{'id': 91, 'name': 'Algebra I Honors', 'course_code': 'Algebra 1'}]

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, headers))
        if 'page=2' in url:
            return _Resp(200, page2, {'next': {'url': 'https://evil.example.com/api/v1/courses?page=3'}})
        return _Resp(200, page1, {'next': {'url': 'https://knox.instructure.com/api/v1/courses?page=2'}})

    with mock.patch.object(canvas_courses.requests, 'get', side_effect=fake_get):
        res = main.set_canvas_token(fid, main.CanvasTokenRequest(token='  tok123 '))
    check(res['named'] == 2 and res['status'].startswith('ok'), f"both classes named: {res}")
    check(all(u.startswith('https://knox.instructure.com/') for u, _ in calls) and len(calls) == 2,
          f"only the feed's own host, pagination stops at a foreign host: {[u for u, _ in calls]}")
    check(calls[0][1]['Authorization'] == 'Bearer tok123', "token sent trimmed, as a bearer")
    listed = main.list_ics_feeds()[0]
    check('canvas_token' not in listed and listed['canvas_token_set'] is True,
          f"the token is write-only: {sorted(listed)}")
    classes = {c['key']: c for c in main.list_school_classes("kid1")}
    check(classes['course_88']['display'] == 'Biology - Knox'
          and classes['Algebra 1']['display'] == 'Algebra I Honors',
          f"Canvas names show: {[c['display'] for c in classes.values()]}")
    day = main.member_day("kid1", TODAY.isoformat())
    lab = next(r for r in day['due_soon'] if r['title'] == 'Cell Lab Report')
    check(lab['course_named'] and lab['course_name'] == 'Biology - Knox' and lab['course_id'],
          f"a Canvas name counts as named and the row knows its class id: {lab}")
    main.update_school_class_api(classes['course_88']['id'], main.SchoolClassUpdate(name="Science"))
    check(main.list_school_classes("kid1")[0]['display'] == 'Science', "the family's name wins")

    # The hourly sync does not hammer Canvas: at most daily.
    with mock.patch.object(canvas_courses.requests, 'get', side_effect=fake_get) as g:
        _sync_again()
        check(g.call_count == 0, "a fresh name list is not refetched on every sync")

    # A refused token says so and keeps the names it had.
    with mock.patch.object(canvas_courses.requests, 'get', return_value=_Resp(401, {})):
        res = main.set_canvas_token(fid, main.CanvasTokenRequest(token='expired'))
    check('refused' in res['status'], f"a 401 is reported plainly: {res}")
    check(main.list_ics_feeds()[0]['canvas_status'].startswith('error'), "status shown on the feed")

    # Clearing removes the token and the Canvas names.
    res = main.set_canvas_token(fid, main.CanvasTokenRequest(token=''))
    check(res['status'] == 'cleared' and main.list_ics_feeds()[0]['canvas_token_set'] is False,
          "an empty token clears it")
    check(not any(c.get('canvas_name') for c in storage.get_school_classes("kid1")),
          "and the names it brought")


def scenario_canvas_token_refuses_bad_feeds():
    _reset()
    import main
    from fastapi import HTTPException
    fid, _ = _sync()   # https://x/feed.ics is https -> allowed host 'x'
    storage.update_ics_feed(fid, {'url': 'http://plain.example.com/feed.ics'})
    try:
        main.set_canvas_token(fid, main.CanvasTokenRequest(token='t'))
        check(False, "an http feed must not receive a token")
    except HTTPException as e:
        check(e.status_code == 400, "plain http refused")
    cal = storage.add_ics_feed({"url": "https://x/team.ics", "name": "Team",
                                "calendar_id": "primary", "target_kind": "calendar"})
    try:
        main.set_canvas_token(cal, main.CanvasTokenRequest(token='t'))
        check(False, "a calendar feed takes no token")
    except HTTPException as e:
        check(e.status_code == 400, "calendar feeds refused")


SCENARIOS = [
    scenario_canvas_detail_survives,
    scenario_naming_a_class_reaches_every_line,
    scenario_existing_tasks_catch_up,
    scenario_canvas_token_names_classes,
    scenario_canvas_token_refuses_bad_feeds,
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
