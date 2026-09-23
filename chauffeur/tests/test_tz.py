"""services/tz.py: the one answer to "which time zone", and the calendar
write choke point that stamps it.

User report (2026-09-22): events made from email intake opened later in
Google Calendar pinned to GMT. An offset-only dateTime with no `timeZone`
is what does that. Every Google write now goes through `tz.stamp`, and the
zone is the family's setting, else the calendar's own, else the box's TZ.
"""
import datetime
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_tz_'))

from harness import check
from services import tz, storage
import services.calendar as gcal


def _settings(**kw):
    return mock.patch.object(storage, 'get_settings', return_value=kw)


def scenario_the_setting_wins_then_the_calendar_then_the_box():
    with _settings(timezone='America/Chicago', default_calendar_id='cal1'), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value='America/New_York'):
        check(tz.zone_name('cal1') == 'America/Chicago', 'the family setting wins')
    with _settings(timezone='', default_calendar_id='cal1'), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value='America/New_York') as g:
        check(tz.zone_name() == 'America/New_York', 'blank setting follows the calendar')
        check(g.call_args[0][0] == 'cal1', 'the default calendar is the one asked, when none is named')
        check(tz.zone_name('cal9') == 'America/New_York' and g.call_args[0][0] == 'cal9',
              'a named calendar is the one asked')
    with _settings(timezone='Mars/Olympus', default_calendar_id='cal1'), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value='America/New_York'):
        check(tz.zone_name() == 'America/New_York', 'a typo in the setting falls through, never reaches Google')
    with _settings(timezone='', default_calendar_id='cal1'), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value=None), \
         mock.patch.dict(os.environ, {'TZ': 'Europe/London'}):
        check(tz.zone_name() == 'Europe/London', "an unreadable calendar falls through to the box's TZ")
    with _settings(timezone='', default_calendar_id=''), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value=None), \
         mock.patch.dict(os.environ, {'TZ': ''}):
        check(tz.zone_name() is None, 'nothing known = None, never a guess')


def scenario_stamp_names_the_zone_only_where_it_belongs():
    with _settings(timezone='America/Chicago'):
        body = {'summary': 'x', 'start': {'dateTime': '2026-09-23T15:00:00-05:00'},
                'end': {'dateTime': '2026-09-23T16:00:00-05:00'}}
        tz.stamp(body, 'cal1')
        check(body['start']['timeZone'] == 'America/Chicago' and body['end']['timeZone'] == 'America/Chicago',
              f'both ends stamped: {body}')
        allday = {'start': {'date': '2026-09-23'}, 'end': {'date': '2026-09-24'}}
        tz.stamp(allday, 'cal1')
        check('timeZone' not in allday['start'], 'an all-day date carries no zone')
        named = {'start': {'dateTime': '2026-09-23T15:00:00-05:00', 'timeZone': 'Europe/Paris'},
                 'end': {'dateTime': '2026-09-23T16:00:00-05:00', 'timeZone': 'Europe/Paris'}}
        tz.stamp(named, 'cal1')
        check(named['start']['timeZone'] == 'Europe/Paris', "a caller's own zone is kept")
        naive = {'start': {'dateTime': '2026-10-01T15:00:00'}, 'end': {'dateTime': '2026-10-01T16:00:00'}}
        tz.stamp(naive, 'cal1')
        check(naive['start']['timeZone'] == 'America/Chicago',
              'a naive stay time (trips) becomes that zone\'s wall time, not UTC')
    with _settings(timezone='', default_calendar_id=''), \
         mock.patch.object(gcal, 'get_calendar_timezone', return_value=None), \
         mock.patch.dict(os.environ, {'TZ': ''}):
        body = {'start': {'dateTime': '2026-09-23T15:00:00-05:00'}, 'end': {'dateTime': '2026-09-23T16:00:00-05:00'}}
        tz.stamp(body, 'cal1')
        check('timeZone' not in body['start'], 'no zone known = field omitted, the offset still names the instant')


def scenario_localize_reads_the_clock_in_the_family_zone():
    with _settings(timezone='America/Chicago'):
        dt = tz.localize(datetime.datetime(2026, 7, 4, 15, 0))
        check(dt.utcoffset() == datetime.timedelta(hours=-5), f'July 3pm Chicago is CDT: {dt.isoformat()}')
        dt = tz.localize(datetime.datetime(2026, 1, 4, 15, 0))
        check(dt.utcoffset() == datetime.timedelta(hours=-6), f'January 3pm Chicago is CST: {dt.isoformat()}')
        aware = datetime.datetime(2026, 7, 4, 15, 0, tzinfo=datetime.timezone.utc)
        check(tz.localize(aware) is aware, 'an aware time is returned untouched')


def scenario_every_google_write_passes_the_choke_point():
    class FakeEvents:
        def __init__(self, seen): self.seen = seen
        def insert(self, calendarId, body):
            self.seen.append(('insert', calendarId, body)); return self
        def patch(self, calendarId, eventId, body):
            self.seen.append(('patch', calendarId, body)); return self
        def execute(self): return {'id': 'gid1'}
    class FakeService:
        def __init__(self, seen): self._e = FakeEvents(seen)
        def events(self): return self._e
    seen = []
    with _settings(timezone='America/Denver'), \
         mock.patch.object(gcal, 'get_calendar_service', return_value=FakeService(seen)):
        gcal.create_event('cal1', 'Stay: Cabin', '2026-10-01T15:00:00', '2026-10-03T11:00:00')
        gcal.insert_event('cal1', {'summary': 'ICS', 'start': {'dateTime': '2026-10-01T09:00:00-06:00'},
                                   'end': {'dateTime': '2026-10-01T10:00:00-06:00'}})
        gcal.patch_event('cal1', 'gid1', {'start': {'dateTime': '2026-10-01T09:30:00-06:00'},
                                          'end': {'dateTime': '2026-10-01T10:30:00-06:00'}})
    check(len(seen) == 3, f'three writes seen: {len(seen)}')
    for kind, _cid, body in seen:
        check(body['start'].get('timeZone') == 'America/Denver' and body['end'].get('timeZone') == 'America/Denver',
              f'{kind} stamped both ends: {body}')


def scenario_intake_reads_the_email_clock_in_the_family_zone():
    from services import email_ingest
    day = (datetime.date.today() + datetime.timedelta(days=5)).isoformat()
    with _settings(timezone='America/Chicago'):
        prop = email_ingest.normalize_item({'kind': 'event', 'title': 'Soccer', 'date': day,
                                            'start_time': '15:00', 'end_time': '16:30', 'confidence': 0.9})
    check(prop and prop['start'][11:16] == '15:00', f'3:00 PM stays 3:00 PM on the clock: {prop}')
    off = datetime.datetime.fromisoformat(prop['start']).utcoffset()
    check(off in (datetime.timedelta(hours=-5), datetime.timedelta(hours=-6)),
          f"and the offset is Chicago's, not the box's: {prop['start']}")


def scenario_the_setting_is_registered_and_validated():
    from services import settings_registry as reg
    from models.schemas import Settings
    check('timezone' in Settings.model_fields, 'Settings carries timezone')
    check('timezone' in reg.BY_KEY and reg.BY_KEY['timezone']['group'] == 'daily',
          'the registry lists it beside the calendar settings')
    import main
    from fastapi import HTTPException
    try:
        main.update_settings(Settings(timezone='Nowhere/Land'), mock.MagicMock())
        check(False, 'a bad zone name must be refused')
    except HTTPException as e:
        check(e.status_code == 400 and 'America/Chicago' in str(e.detail), f'refused with a hint: {e.detail}')


if __name__ == '__main__':
    scenario_the_setting_wins_then_the_calendar_then_the_box()
    scenario_stamp_names_the_zone_only_where_it_belongs()
    scenario_localize_reads_the_clock_in_the_family_zone()
    scenario_every_google_write_passes_the_choke_point()
    scenario_intake_reads_the_email_clock_in_the_family_zone()
    scenario_the_setting_is_registered_and_validated()
    print('test_tz OK')
