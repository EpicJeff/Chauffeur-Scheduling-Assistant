"""Dated PWA sessions use real reads/writes against the isolated test store."""
import datetime
from pathlib import Path
from services import storage, programs


def check_program_dates(page, member, driver, output=None):
    today = datetime.date.today()
    yesterday, tomorrow = today - datetime.timedelta(days=1), today + datetime.timedelta(days=1)
    pid, cid = 'dated-'+member, 'dated-slot-'+member
    storage.add_protected_commitment(dict(id=cid, member_id=member, title='Dated guitar',
        days_of_week=list(range(7)), time_start='11:00', time_end='13:00', active=True))
    storage.add_program(dict(id=pid, member_id=member, title='Dated guitar', state='active',
        phases=[dict(name='Chords', steps=['Tune up', 'Practice chord changes'])],
        shape=dict(sessions_per_week=7, minutes=30),
        baseline=dict(start_date=(today-datetime.timedelta(days=14)).isoformat()),
        emissions=dict(commitment_ids=[cid])))
    for date, label in [(yesterday, 'Quiet recovery day'), (tomorrow, 'Family visiting')]:
        proto = 'status-'+member+'-'+date.isoformat()
        storage.add_status_protocol(dict(id=proto, name=label, adult_message=label, kid_message=label))
        storage.add_status_day(dict(protocol_id=proto, date=date.isoformat(), member_id=member))
    # Remove presentation fixtures for these endpoints: the POST and refreshed
    # Done badge must agree with the actual persisted session, not a mock.
    for pattern in ('**/api/programs', '**/api/practice-windows?*', '**/api/members/*/day?*'):
        page.unroute(pattern)
    page.evaluate("document.documentElement.style.fontSize=''; datedTimelineDays.clear(); practiceBuiltAt=0")
    page.set_viewport_size(dict(width=390, height=844))

    def select(offset):
        if driver:
            page.evaluate("""offset=>{
                setView('drives');
                window.globalStartDate=new Date(_mydayLocalDate(-1)+'T00:00:00');
                window.globalDaysToShow=3; timelineInitialized=true;
                activeDateIndex=offset+1; buildTimeline();
            }""", offset)
            page.wait_for_function('(date)=>currentDates[activeDateIndex]===date && datedTimelineDays.has(`${selectedMemberId}:${date}`)', arg=(today+datetime.timedelta(days=offset)).isoformat())
            return page.locator('#pane-'+str(offset+1))
        page.evaluate("offset=>{setView('myday'); void pwaChildChooseDate(offset)}", offset)
        page.wait_for_function('offset=>pwaChildDay?.offset===offset', arg=offset)
        return page.locator('#myday-content')

    future = select(1)
    row = future.locator('[data-myday-program="'+pid+'"]')
    row.wait_for()
    assert future.get_by_text('Family visiting', exact=True).count() > 0
    assert future.get_by_text('Quiet recovery day', exact=True).count() == 0
    if driver:
        future.locator('[onclick*="toggleStatusSetRow"]').click()
        future.locator('[id="status-set-row-'+tomorrow.isoformat()+'"] button').first.wait_for()
    assert 'Now' not in row.inner_text() and 'Did it happen?' not in row.inner_text()
    row.locator('[data-myday-toggle]').click()
    sheet = page.locator('.pwa-prompt-overlay')
    assert sheet.get_by_text('Tomorrow, 11:00 AM', exact=True).is_visible()
    assert sheet.get_by_text('Practice chord changes', exact=True).is_visible()
    assert sheet.locator('[data-done], [data-start]').count() == 0
    sheet.locator('[data-close]').click()
    past = select(-1)
    row = past.locator('[data-myday-program="'+pid+'"]')
    row.wait_for()
    assert past.get_by_text('Quiet recovery day', exact=True).count() > 0
    assert past.get_by_text('Family visiting', exact=True).count() == 0
    assert past.locator('[onclick*="armClearStatus"], [onclick*="toggleStatusSetRow"]').count() == 0
    assert past.locator('.child-rewards-link, .pwa-request-details').count() == 0
    row.locator('[data-myday-toggle]').click()
    assert sheet.get_by_text('Yesterday, 11:00 AM', exact=True).is_visible()
    assert sheet.locator('[data-start]').count() == 0
    if output: Path(output, member+'-past-program.png').write_bytes(page.screenshot())
    with page.expect_response('**/api/programs/'+pid+'/session') as response:
        sheet.locator('[data-done]').click()
    assert response.value.ok, response.value.text()
    assert response.value.request.post_data_json['slot_date'] == yesterday.isoformat()
    row.get_by_text('Done', exact=True).wait_for()
    logged = storage.get_program(pid)
    assert len(programs.sessions_between(logged, yesterday, yesterday)) == 1
    assert not programs.sessions_between(logged, today, today)
    row.locator('[data-myday-toggle]').click()
    assert sheet.locator('[data-done]').count() == 0
    sheet.locator('[data-close]').click()
    select(1)
    past = select(-1)
    past.locator('[data-myday-program="'+pid+'"]', has_text='Done').wait_for()
    assert len(programs.sessions_between(storage.get_program(pid), yesterday, yesterday)) == 1
    if output: Path(output, member+'-past-day.png').write_bytes(page.screenshot())
    if driver:
        page.evaluate("setView('family')")
        page.wait_for_function('(date)=>currentDates[activeDateIndex]===date', arg=yesterday.isoformat())
        assert page.locator('#pane-0').get_by_text('Quiet recovery day', exact=True).count() > 0
