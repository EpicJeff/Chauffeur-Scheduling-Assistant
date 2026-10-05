"""School view (K4d) in the served PWA: the Due Soon card carries each
task's class and opens its detail; See all opens the agenda/month sheet;
the past-due bucket stays collapsed; a class gets named from the sheet and
the name reaches the card; a parent reaches a child's list from More.

Run: venv/Scripts/python.exe -X utf8 chauffeur/tests/test_school_view_live.py
Optional SCHOOL_REVIEW_OUTPUT=<dir> writes screenshots.
"""
import atexit
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
DATA = tempfile.mkdtemp(prefix='chauffeur_school_view_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

TODAY = date.today()


def _d(n):
    return (TODAY + timedelta(days=n)).isoformat()


def seed():
    storage.add_member({'id': 'mom', 'name': 'Alex Morgan', 'role': 'parent', 'color_code': '#287a72'})
    storage.add_member({'id': 'kid', 'name': 'Jamie', 'role': 'child', 'is_child': True,
                        'stage_override': 'navigator', 'color_code': '#6366f1'})
    sci = storage.ensure_school_class('kid', 'course_88', '502.Knox.30062Y0.6001.2027')
    storage.ensure_school_class('kid', 'Algebra 1', 'Algebra 1')
    storage.ensure_school_class('kid', 'course_77', '611.Knox.40011Z0.6002.2027')
    from models.schemas import KidTask
    rows = [
        dict(title='Cell Lab Report', due_date=_d(1), due_time='23:59', kind='homework',
             course_key='course_88', course_label=sci['label'],
             description='Write up the lab using the template.\n\nTemplate: https://docs.google.com/document/d/abc',
             links=[{'url': 'https://knox.instructure.com/courses/88/files/5', 'text': 'the rubric'}],
             url='https://knox.instructure.com/courses/88/assignments/1001'),
        dict(title='Chapter 4 Quiz', due_date=_d(2), kind='test', course_key='course_88',
             course_label=sci['label']),
        dict(title='Problem set 7', due_date=_d(2), kind='homework', course_key='Algebra 1',
             course_label='Algebra 1'),
        dict(title='Science fair board', due_date=_d(12), kind='project', course_key='course_88',
             course_label=sci['label']),
        dict(title='Reading log', due_date=_d(-3), kind='homework', course_key='Algebra 1',
             course_label='Algebra 1'),
        dict(title='Old worksheet', due_date=_d(-9), kind='homework'),
        dict(title='Essay draft', due_date=_d(3), kind='homework', course_key='course_77',
             course_label='611.Knox.40011Z0.6002.2027'),
    ]
    for r in rows:
        storage.add_kid_task(KidTask(member_id='kid', source='ics', **r).model_dump())
    storage.set_cached_schedule({'events': [], 'assignments': {}, 'matched_rules': {},
                                 'scheduled_errands': []})


def _login(page, key):
    token = storage.create_member_token(key)
    values = {'chauffeur_member_id': key, 'chauffeur_member_token': token,
              'chauffeur_member_token_for': key, 'chauffeur_view': 'myday',
              'chauffeur_theme': 'dark'}
    page.add_init_script('Object.entries(' + json.dumps(values) +
                         ').forEach(([k,v])=>localStorage.setItem(k,v));')


def _stub(page):
    def static_asset(route):
        if route.request.resource_type in ('script', 'stylesheet'):
            route.fulfill(response=route.fetch(max_retries=2))
        else:
            route.continue_()
    page.route('**/static/**', static_asset)
    page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
    page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))
    page.route('**/api/schedule?*', lambda r: r.fulfill(json={'events': [], 'assignments': {}}))


def _open(served, page, key):
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.set_viewport_size({'width': 390, 'height': 844})
    _stub(page)
    _login(page, key)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    page.wait_for_timeout(500)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function('membersData.length > 0')
    return errors


def check_kid(served, output):
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        errors = _open(served, page, 'kid')
        page.evaluate("setView('myday')")
        page.evaluate('void renderMyDay()')
        page.wait_for_selector('text=Cell Lab Report')
        card = page.locator('text=📚 Due Soon').locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]')
        text = card.inner_text()
        assert 'Cell Lab Report' in text and 'by 11:59' in text, text
        assert 'Reading log' not in card.locator(':scope > div.divide-y').first.inner_text(), \
            'past-due must not mix into the upcoming list'
        bucket = page.locator('#still-open-bucket')
        assert bucket.count() == 1 and bucket.get_attribute('open') is None, 'bucket starts collapsed'
        assert 'Algebra 1' in text, 'a named class shows its chip'
        if output:
            card.screenshot(path=str(Path(output, 'school-due-soon-card.png')))

        # Detail sheet from the row
        page.locator('button:has-text("Cell Lab Report")').first.click()
        sheet = page.locator('.pwa-prompt-overlay').last
        sheet.wait_for()
        st = sheet.inner_text()
        assert 'Write up the lab' in st and 'the rubric' in st and 'Open in school site' in st, st
        assert sheet.locator('a[href="https://docs.google.com/document/d/abc"]').count() == 1, \
            'bare URLs in the description are links'
        if output:
            page.screenshot(path=str(Path(output, 'school-task-detail.png')))
        sheet.locator('[data-close]').click()

        # See all -> agenda
        page.locator('button:has-text("See all")').click()
        page.wait_for_selector('#pwa-school-body >> text=Science fair board')
        body = page.locator('#pwa-school-body')
        bt = body.inner_text()
        assert 'Tomorrow' in bt and 'Science fair board' in bt, bt
        assert 'Give your classes names' in bt, 'an unnamed course code prompts naming'
        if output:
            page.screenshot(path=str(Path(output, 'school-agenda.png')))

        # Name the class from the sheet
        body.locator('[onclick^="pwaSchoolRenameClass"]:has-text("502.Knox")').click()
        prompt = page.locator('.pwa-prompt-overlay textarea')
        prompt.fill('Science')
        page.locator('.pwa-prompt-overlay [data-yes]').click()
        page.wait_for_function("pwaSchool && pwaSchool.classes.some(c => c.name === 'Science')")
        page.wait_for_selector('#pwa-school-body >> text=Science')
        # one class is still a bare code (named from its detail sheet below)
        assert 'Give your classes names' in body.inner_text()

        # Month view
        page.locator('#pwa-school-body [role="button"]:text-is("Month")').click()
        page.wait_for_selector('#pwa-school-body .grid-cols-7')
        page.locator(f'#pwa-school-body [data-day="{_d(2)}"]').click()
        mt = body.inner_text()
        assert 'Chapter 4 Quiz' in mt and 'Problem set 7' in mt, mt
        if output:
            page.screenshot(path=str(Path(output, 'school-month.png')))
        page.evaluate('pwaSchoolClose()')
        assert storage.get_school_classes('kid')[0]['name'] == 'Science'

        # The class line on a task's detail sheet names the class in place.
        page.evaluate("openKidTaskDetail(Object.values(pwaSchoolTasks).find(t => t.title === 'Essay draft').id)")
        link = page.locator('.pwa-prompt-overlay [data-rename]')
        link.wait_for()
        assert 'Name this class' in link.inner_text(), link.inner_text()
        if output:
            page.screenshot(path=str(Path(output, 'school-detail-name-class.png')))
        link.click()
        page.locator('.pwa-prompt-overlay textarea').fill('English')
        page.locator('.pwa-prompt-overlay [data-yes]').click()
        page.wait_for_function("!document.querySelector('.pwa-prompt-overlay')")
        page.wait_for_timeout(300)
        named = {c['key']: c.get('name') for c in storage.get_school_classes('kid')}
        assert named['course_77'] == 'English', named
        assert not errors, errors


def check_class_pills(served, output):
    """Class pills filter the School sheet like the calendar's people pills,
    and the choice survives closing the sheet (per child, this device)."""
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        errors = _open(served, page, 'kid')
        page.evaluate("pwaSchoolOpen('kid')")
        body = page.locator('#pwa-school-body')
        page.wait_for_selector('#pwa-school-body >> text=Cell Lab Report')
        pills = page.locator('#pwa-school-body [data-pill]')
        labels = [p.strip() for p in pills.all_inner_texts()]
        assert 'Science' in labels and 'Algebra 1' in labels and 'No class' in labels, labels
        pills.filter(has_text='Science').click()
        page.wait_for_function("!document.getElementById('pwa-school-body').innerText.includes('Cell Lab Report')")
        text = body.inner_text()
        assert 'Problem set 7' in text and 'Chapter 4 Quiz' not in text, text
        assert pills.filter(has_text='Science').get_attribute('aria-pressed') == 'false'
        if output:
            page.screenshot(path=str(Path(output, 'school-class-pills.png')))
        # Month view honours the same filter.
        page.locator('#pwa-school-body [role="button"]:text-is("Month")').click()
        page.locator(f'#pwa-school-body [data-day="{_d(2)}"]').click()
        mt = body.inner_text()
        assert 'Problem set 7' in mt and 'Chapter 4 Quiz' not in mt, mt
        # Persistent: close and reopen.
        page.evaluate('pwaSchoolClose()')
        page.evaluate("pwaSchoolOpen('kid')")
        page.wait_for_selector('#pwa-school-body >> text=Problem set 7')
        assert 'Cell Lab Report' not in body.inner_text(), 'the filter survives reopening'
        page.locator('#pwa-school-body [role="button"]:text-is("Show all")').click()
        page.wait_for_selector('#pwa-school-body >> text=Cell Lab Report')
        page.evaluate('pwaSchoolClose()')
        assert not errors, errors


def check_big_items(served, output):
    """Tests and projects stand out: the Heads-up strip on Due Soon, a tag
    on every row, a Tests & projects filter, and a Type line that retypes
    a task by hand."""
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        errors = _open(served, page, 'kid')
        page.evaluate("setView('myday')")
        page.evaluate('void renderMyDay()')
        strip = page.locator('[data-heads-up]')
        strip.wait_for()
        st = strip.inner_text()
        assert 'Chapter 4 Quiz' in st and 'Cell Lab Report' not in st, st
        assert 'TEST' in st.upper() and '2 DAYS' in st.upper(), st
        if output:
            page.locator('text=📚 Due Soon').locator('xpath=ancestor::div[contains(@class,"rounded-xl")][1]') \
                .screenshot(path=str(Path(output, 'school-heads-up.png')))
        # Retype the lab report as a test from its detail sheet.
        page.locator('button:has-text("Cell Lab Report")').first.click()
        page.locator('.pwa-prompt-overlay [data-kind]').click()
        page.locator('.pwa-prompt-overlay [data-pick]').filter(has_text='Test or quiz').click()
        page.wait_for_function("document.querySelector('[data-heads-up]') && document.querySelector('[data-heads-up]').innerText.includes('Cell Lab Report')")
        lab = next(t for t in storage.get_kid_tasks('kid') if t['title'] == 'Cell Lab Report')
        assert lab['kind'] == 'test' and lab['kind_locked'], lab
        # Tests & projects only, in the School sheet.
        page.evaluate("pwaSchoolOpen('kid')")
        page.wait_for_selector('#pwa-school-body >> text=Problem set 7')
        page.locator('#pwa-school-body [data-big-pill]').click()
        page.wait_for_function("!document.getElementById('pwa-school-body').innerText.includes('Problem set 7')")
        bt = page.locator('#pwa-school-body').inner_text()
        assert 'Chapter 4 Quiz' in bt and 'Science fair board' in bt, bt
        if output:
            page.screenshot(path=str(Path(output, 'school-big-only.png')))
        page.locator('#pwa-school-body [data-big-pill]').click()
        page.wait_for_selector('#pwa-school-body >> text=Problem set 7')
        page.evaluate('pwaSchoolClose()')
        assert not errors, errors


def check_parent(served, output):
    with served.browser(reduced_motion='reduce', has_touch=True) as page:
        errors = _open(served, page, 'mom')
        page.evaluate("setView('more')")
        page.locator('[data-feature="school"]').click()
        page.wait_for_selector('#pwa-school-body >> text=Cell Lab Report')
        pt = page.locator('#pwa-school-body').inner_text()
        assert 'Jamie' in pt, pt
        assert 'Still open from earlier' not in pt and 'Reading log' not in pt,             'a parent sees what is coming, never what is overdue'
        if output:
            page.screenshot(path=str(Path(output, 'school-parent.png')))
        assert not errors, errors


def check_calendar_layer(served, output):
    """The shared calendar component draws a child's upcoming school items
    as all-day entries when mounted with `school` (the wall card's option),
    and a tap says what it is instead of 'Not assigned'."""
    with served.browser(reduced_motion='reduce') as page:
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_viewport_size({'width': 1100, 'height': 800})
        _stub(page)
        page.goto(served.url('calendar'), wait_until='domcontentloaded')
        page.wait_for_function('window.FamilyCalendar && FamilyCalendar.mount')
        page.evaluate('''async () => {
            const host = document.createElement('div');
            host.id = 'school-layer-cal';
            host.style.cssText = 'position:fixed;inset:64px 0 0 0;z-index:1;display:flex;background:#0f172a;padding:16px';
            document.body.appendChild(host);
            await FamilyCalendar.mount({targetContainerId: 'school-layer-cal', view: 'agenda',
                toolbar: false, details: true, legend: true, agendaDays: 7,
                base: window.chfBase || '', school: ['kid']});
        }''')
        page.wait_for_selector('#school-layer-cal >> text=Jamie: Chapter 4 Quiz')
        text = page.locator('#school-layer-cal').inner_text()
        assert 'Problem set 7' not in text, 'plain homework stays off unless asked'
        assert 'Reading log' not in text, 'never overdue'
        if output:
            page.screenshot(path=str(Path(output, 'school-calendar-layer.png')))
        page.locator('#school-layer-cal >> text=Chapter 4 Quiz').click()
        page.wait_for_selector('#modal-driver >> text=Schoolwork')
        assert page.locator('#modal-passengers').inner_text().strip() == 'Jamie'
        assert page.locator('#modal-driver-label').inner_text().strip().lower() == 'what'
        assert page.locator('#modal-location-label').inner_text().strip().lower() == 'class'
        if output:
            page.screenshot(path=str(Path(output, 'school-calendar-detail.png')))
        assert not errors, errors


def run():
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    import main

    @asynccontextmanager
    async def isolated_lifespan(app):
        yield
    main.app.router.lifespan_context = isolated_lifespan
    served = live_app(seed)
    if served is None:
        return
    output = os.environ.get('SCHOOL_REVIEW_OUTPUT')
    if output:
        Path(output).mkdir(parents=True, exist_ok=True)
    check_kid(served, output)
    print('PASS  kid: card, detail, agenda, naming, month')
    check_class_pills(served, output)
    print('PASS  kid: class pills filter and persist')
    check_big_items(served, output)
    print('PASS  kid: heads-up strip, kind switch, tests & projects filter')
    check_parent(served, output)
    print('PASS  parent: More -> School')
    check_calendar_layer(served, output)
    print('PASS  calendar component: school layer + details')


if __name__ == '__main__':
    run()
