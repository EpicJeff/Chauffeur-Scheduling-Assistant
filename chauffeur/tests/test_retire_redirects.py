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
                     ('static/study.js', "'/programs'")):
        check(old not in open(os.path.join(ROOT, rel), encoding='utf-8').read(), f"{rel} no longer links to a retired page")
    import re
    house = open(os.path.join(ROOT, 'static/house.js'), encoding='utf-8').read()
    overlay = open(os.path.join(ROOT, 'static/kitchen_overlay.js'), encoding='utf-8').read()
    # The Programs lane filter is gone (one-list spec R5): the binders open the Library, which lists every program.
    check(re.search(r"study_binders:\s*\['Program binders',\s*'library'\]", house),
          "the House study binders open the Library")
    check(re.search(r"study_binders:\s*'library'", overlay),
          "the overlay study binders open the Library")
    study = open(os.path.join(ROOT, 'static/study.js'), encoding='utf-8').read()
    check('lane=programs' not in study and "'/library'" in study, "the Study binders open the Library")
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
