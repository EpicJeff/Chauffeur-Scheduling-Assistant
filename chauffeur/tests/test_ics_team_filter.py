"""One league feed, several kids: a feed subscription can name the teams it is for.

User report (2026-10-26): "This calendar from Team Sideline has events for
multiple kids, but our importer doesn't differentiate and assigns all the
events to the person who has the calendar added." The feed
(tests/fixtures/teamsideline_sample.ics, fetched 2026-10-26) carries no
per-player data at all: no CATEGORIES, no ATTENDEE, DESCRIPTION is the
literal 'Staff Notes:' on every row. The only marker is the LAST
parenthesised group of the SUMMARY, the team and its division:

    Practice ( Lions-Purple (10USB-W))
     Vs  Lions-Navy (10USB-W) ( Lions-Purple (10USB-W))
    [Canceled] Vs  Lions-Red (10USB-C) ( Lions-Purple (10USB-W))
    Practice (Surge (G10w))

Opponents appear in parentheses too, so only the last group counts.

Rulings (user, 2026-10-26): titles are NEVER altered (the team token stays
in the stored summary); a feed takes a LIST of teams (several kids on one
team, or one kid on two); an empty list is the whole feed, as before. Mine:
an event with no team token at all (a league-wide picture day) is not
another team's and stays in; only a different team's token keeps an event
out.

Run from chauffeur/:  python tests/test_ics_team_filter.py
"""
import datetime
import os
import sys
import tempfile

os.environ.setdefault("CHAUFFEUR_DATA_DIR", tempfile.mkdtemp(prefix="chauffeur_ics_teams_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import check  # noqa: E402
from services import ics_sync, storage  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, 'fixtures', 'teamsideline_sample.ics')
NOW = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)

PURPLE = 'Lions-Purple (10USB-W)'
SURGE = 'Surge (G10w)'
WOMBATS = 'Wombats (CO6w)'
WARTHOGS = 'Warthogs (B8w)'


def _utc(dt):
    return dt.strftime('%Y%m%dT%H%M%SZ')


def build_ics(summaries, name='TeamSideline Calendar'):
    """One timed event per summary, a week out and an hour apart, titles
    exactly as given (leading spaces and all, the way the real feed has them)."""
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//Teamsideline.com//EN',
             f'X-WR-CALNAME:{name}']
    for i, summary in enumerate(summaries):
        start = NOW + datetime.timedelta(days=7, hours=i)
        lines += ['BEGIN:VEVENT', f'UID:-{1000 + i}.teamsideline.com',
                  f'SUMMARY:{summary}', 'LOCATION:Bond Park #4\\, Cary\\, NC',
                  'DESCRIPTION: Staff Notes: ',
                  f'DTSTART:{_utc(start)}', f'DTEND:{_utc(start + datetime.timedelta(hours=1))}',
                  'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines).encode('utf-8')


class FakeGcal:
    def __init__(self):
        self.events = {}
        self.inserted, self.patched, self.removed = [], [], []
        self._n = 0

    def insert_event(self, cal_id, body):
        self._n += 1
        gid = f'g{self._n}'
        self.events[gid] = body
        self.inserted.append((cal_id, gid, body))
        return gid

    def patch_event(self, cal_id, gid, body):
        self.events[gid] = body
        self.patched.append((cal_id, gid, body))
        return True

    def remove_event(self, cal_id, gid):
        self.events.pop(gid, None)
        self.removed.append((cal_id, gid))
        return True

    def list_tagged_events(self, cal_id, prop_key, prop_value):
        return [dict(b, id=gid, created='2026-01-01T00:00:00Z') for gid, b in self.events.items()
                if b['extendedProperties']['private'].get(prop_key) == prop_value]


FEED_TITLES = [
    'Practice ( Lions-Purple (10USB-W))',
    ' Vs  Lions-Navy (10USB-W) ( Lions-Purple (10USB-W))',
    '[Canceled] Vs  Lions-Red (10USB-C) ( Lions-Purple (10USB-W))',
    'Practice (Surge (G10w))',
    ' Vs  Storm (G10w) (Surge (G10w))',
    'Practice (Wombats (CO6w))',
    'League picture day',
]


def _feed(teams=None, cal='kid@cal'):
    storage.ics_feeds_table.truncate() if hasattr(storage, 'ics_feeds_table') else None
    row = {'url': 'https://x/team.ics', 'name': 'T', 'calendar_id': cal}
    if teams is not None:
        row['teams'] = teams
    return storage.add_ics_feed(row)


def _sync(feed_id, summaries, fake):
    real_gcal, real_fetch = ics_sync.gcal, ics_sync.fetch_ics
    ics_sync.gcal = fake
    ics_sync.fetch_ics = lambda url: build_ics(summaries)
    try:
        return ics_sync.sync_feed(storage.get_ics_feed(feed_id))
    finally:
        ics_sync.gcal, ics_sync.fetch_ics = real_gcal, real_fetch


def scenario_the_team_is_the_last_parenthesised_group():
    tok = ics_sync.team_token
    check(tok('Practice ( Lions-Purple (10USB-W))') == PURPLE, tok('Practice ( Lions-Purple (10USB-W))'))
    check(tok(' Vs  Lions-Navy (10USB-W) ( Lions-Purple (10USB-W))') == PURPLE,
          "the opponent's group is not the team: %r" % tok(' Vs  Lions-Navy (10USB-W) ( Lions-Purple (10USB-W))'))
    check(tok('[Canceled] Vs  Lions-Red (10USB-C) ( Lions-Purple (10USB-W))') == PURPLE,
          'a canceled row still names its team')
    check(tok('Practice (Surge (G10w))') == SURGE, tok('Practice (Surge (G10w))'))
    check(tok('Practice') is None, 'no group, no team')
    check(tok('League picture day') is None, 'no group, no team')
    check(tok('Game (home) tonight') is None, 'a group that is not at the end is not the team')
    check(tok('Open gym (')  is None and tok(')(') is None, 'unbalanced parens do not crash')


def scenario_the_sample_feed_detects_four_teams():
    with open(SAMPLE, 'rb') as fh:
        parsed = ics_sync.parse_ics(fh.read(), window_start=datetime.date(2026, 8, 1),
                                    window_end=datetime.date(2027, 1, 1))
    teams = ics_sync.detect_teams(parsed['items'])
    got = [(t['team'], t['count']) for t in teams]
    check(got == [(PURPLE, 21), (SURGE, 6), (WARTHOGS, 6), (WOMBATS, 6)],
          'four teams, most events first, ties by name: %s' % got)
    check(all(t['team'] == t['team'].strip() for t in teams), 'tokens are trimmed')


def scenario_only_the_named_teams_are_created_and_titles_are_verbatim():
    fake = FakeGcal()
    feed_id = _feed(teams=[SURGE])
    res = _sync(feed_id, FEED_TITLES, fake)
    titles = sorted(b['summary'] for _, _, b in fake.inserted)
    check(res['error'] is None and res['added'] == 3,
          'two Surge rows and the league-wide picture day: %s / %s' % (res, titles))
    check(titles == sorted(['Practice (Surge (G10w))', 'Vs  Storm (G10w) (Surge (G10w))',
                            'League picture day']),
          'titles are the feed\'s own, token and double space included: %s' % titles)
    check(res['total'] == 3, 'the status counts what this feed keeps: %s' % res)


def scenario_several_teams_on_one_feed():
    fake = FakeGcal()
    feed_id = _feed(teams=[SURGE, WOMBATS])
    res = _sync(feed_id, FEED_TITLES, fake)
    check(res['added'] == 4, 'Surge (2) + Wombats (1) + picture day: %s' % res)
    check(not any('Lions-Purple' in b['summary'] for _, _, b in fake.inserted),
          "a Purple row got onto the Surge kids' calendar")


def scenario_no_teams_means_the_whole_feed():
    fake = FakeGcal()
    feed_id = _feed(teams=[])
    res = _sync(feed_id, FEED_TITLES, fake)
    check(res['added'] == len(FEED_TITLES), 'empty list is the whole feed: %s' % res)
    fake2 = FakeGcal()
    feed_id = _feed()
    res = _sync(feed_id, FEED_TITLES, fake2)
    check(res['added'] == len(FEED_TITLES), 'a feed from before this field is the whole feed: %s' % res)


def scenario_changing_the_teams_moves_events_on_the_next_sync():
    """Narrowing drops the now-excluded future events (the feed's own
    missing-means-cancelled rule); widening brings them back."""
    fake = FakeGcal()
    feed_id = _feed(teams=[SURGE, PURPLE])
    res = _sync(feed_id, FEED_TITLES, fake)
    check(res['added'] == 6, 'Surge (2) + Purple (3) + picture day: %s' % res)
    storage.update_ics_feed(feed_id, {'teams': [SURGE]})
    res = _sync(feed_id, FEED_TITLES, fake)
    check(res['removed'] == 3 and res['added'] == 0,
          'narrowing to Surge removes the three Purple rows: %s' % res)
    check(sorted(b['summary'] for b in fake.events.values()) == sorted(
        ['Practice (Surge (G10w))', 'Vs  Storm (G10w) (Surge (G10w))', 'League picture day']),
        'what is left on the calendar: %s' % sorted(b['summary'] for b in fake.events.values()))
    storage.update_ics_feed(feed_id, {'teams': [SURGE, WOMBATS]})
    res = _sync(feed_id, FEED_TITLES, fake)
    check(res['added'] == 1 and res['removed'] == 0, 'widening adds the Wombats row: %s' % res)


def _client():
    from fastapi.testclient import TestClient
    import main
    main.trigger_background_refresh = lambda *a, **k: None
    return TestClient(main.app), main


def _parent_headers(mid='p1'):
    storage.members_table.truncate()
    storage.add_member({'id': mid, 'name': 'Pat', 'role': 'parent'})
    return {'X-Member-Token': storage.create_member_token(mid)}


def scenario_the_routes_preview_create_list_and_edit_teams():
    client, main = _client()
    headers = _parent_headers()
    # The preview reads the sync window (past events are history), so the
    # feed it sees is built a week out, not the dated sample.
    real_fetch, real_gcal = ics_sync.fetch_ics, ics_sync.gcal
    synced = []
    real_sync = ics_sync.sync_feed
    ics_sync.fetch_ics = lambda url: build_ics(FEED_TITLES)
    ics_sync.gcal = FakeGcal()
    ics_sync.sync_feed = lambda feed: synced.append(feed['id']) or {'added': 0, 'updated': 0, 'removed': 0}
    try:
        r = client.post('/api/ics_feeds/preview', json={'url': 'webcal://x/team.ics'}, headers=headers)
        check(r.status_code == 200, '%s %s' % (r.status_code, r.text))
        body = r.json()
        teams = [(t['team'], t['count']) for t in body.get('teams') or []]
        check(teams == [(PURPLE, 3), (SURGE, 2), (WOMBATS, 1)],
              'the preview names the teams, most events first, untokened rows skipped: %s' % body)
        check(body.get('event_count') == len(FEED_TITLES), body)
        check(body.get('name') == 'TeamSideline Calendar', body)

        r = client.post('/api/ics_feeds', json={'url': 'webcal://x/team.ics', 'calendar_id': 'kid@cal',
                                                 'teams': [SURGE, ' Wombats (CO6w) ']}, headers=headers)
        check(r.status_code == 200, '%s %s' % (r.status_code, r.text))
        feed_id = r.json()['id']
        feed = storage.get_ics_feed(feed_id)
        check(feed.get('teams') == [SURGE, WOMBATS], 'teams stored, trimmed: %s' % feed.get('teams'))

        r = client.get('/api/ics_feeds', headers=headers)
        row = next(f for f in r.json() if f['id'] == feed_id)
        check(row.get('teams') == [SURGE, WOMBATS], 'the listing carries the teams: %s' % row)

        synced.clear()
        r = client.put(f'/api/ics_feeds/{feed_id}', json={'teams': [PURPLE]}, headers=headers)
        check(r.status_code == 200, '%s %s' % (r.status_code, r.text))
        check(storage.get_ics_feed(feed_id).get('teams') == [PURPLE], 'teams updated')
        check(synced == [feed_id], 'a teams change re-syncs the feed at once: %s' % synced)

        synced.clear()
        r = client.put(f'/api/ics_feeds/{feed_id}', json={'teams': []}, headers=headers)
        check(r.status_code == 200 and storage.get_ics_feed(feed_id).get('teams') == [],
              'clearing the list is allowed and means the whole feed')
        check(synced == [feed_id], 'clearing re-syncs too')

        r = client.post('/api/ics_feeds/preview', json={'url': ''}, headers=headers)
        check(r.status_code == 400, 'an empty url is refused: %s' % r.status_code)
    finally:
        ics_sync.fetch_ics, ics_sync.gcal, ics_sync.sync_feed = real_fetch, real_gcal, real_sync


def scenario_the_hand_path_exists():
    """Config › People: the subscribe form offers the detected teams as
    checkboxes and an existing feed shows and edits its teams."""
    with open(os.path.join(HERE, '..', 'templates', 'config.html'), encoding='utf-8') as fh:
        src = fh.read()
    check('api/ics_feeds/preview' in src, 'the form previews the feed before subscribing')
    check('feed.teams' in src, 'a subscribed feed shows its teams')
    check("type=\"checkbox\"" in src and 'newIcsFeed.teams' in src, 'teams are checkboxes on the form')


if __name__ == '__main__':
    scenarios = [v for k, v in sorted(globals().items()) if k.startswith('scenario_')]
    failed = 0
    for fn in scenarios:
        try:
            fn()
            print('PASS', fn.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', fn.__name__, '-', e)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print('ERROR', fn.__name__, '-', type(e).__name__, e)
    print('%d/%d passed' % (len(scenarios) - failed, len(scenarios)))
    raise SystemExit(1 if failed else 0)
