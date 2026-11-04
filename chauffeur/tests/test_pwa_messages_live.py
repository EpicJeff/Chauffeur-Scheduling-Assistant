"""Messages, Signal's list and Messenger's thread, in the served PWA (slice 4, Task 3).

The adult Messages tab is Signal's list: a 34px "Messages" title with the
presence stack, a camera (Add a moment) and a compose button on its row; the
search field; a Moments row of rings with "Add" first; then Pinned (Family,
then Argyle) and Chats (the server's order), each conversation an avatar, a
name with its time, one preview line, and unread as a dot or a count. A tap
pushes the thread as a PwaNav screen that ADOPTS #thread-view (every id and
handler kept), skinned as Messenger's thread; hardware Back closes it. Kids
keep today's list and today's absolute thread overlay with no history entry.

Written before the views exist (Tasks 4-5 make it green), so its first failure
is the missing `.pwa-conv-label` on the parent's Messages tab.

Every read the views make is mocked with page.route (members and auth are
seeded and served for real); every write goes through a recorder and the
scenario asserts its path and body. The list is checked against
pwaConversationRows() evaluated IN THE PAGE over the payload the mock served,
and against the order that payload must produce.

Run (from chauffeur/, HA_BASE_URL unset): python tests/test_pwa_messages_live.py
PWA_REVIEW_PROFILE=<key> runs one profile. PWA_REVIEW_OUTPUT=1 writes the
screenshots to tests/probe_shots/pwa_slice4 (gitignored); any other value is
taken as the output directory.
"""
import atexit
import base64
import copy
import json
import os
import re
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'chauffeur'))
DATA = tempfile.mkdtemp(prefix='chauffeur_messages_')
os.environ['CHAUFFEUR_DATA_DIR'] = DATA
atexit.register(lambda: shutil.rmtree(DATA, ignore_errors=True))
from live_app import live_app
from services import storage, ha_api

NOW = datetime.now().replace(hour=15, minute=12, second=0, microsecond=0)
DAY = NOW.strftime('%Y-%m-%d')
EVENT_END = DAY + 'T17:00:00'

PROFILES = [('parent', 'parent', 'd1'), ('adult', 'adult', 'd2'), ('helper', 'helper', 'd3'),
            ('guest', 'guest', None), ('navigator', 'child', None)]
NAMES = {'parent': 'Alex Morgan', 'lorena': 'Lorena Diaz', 'adult': 'Robin Lee', 'navigator': 'Sam',
         'helper': 'Nana Bea', 'guest': 'Gail Ward'}
COLORS = {'parent': '#287a72', 'lorena': '#c2410c', 'adult': '#287a72', 'navigator': '#287a72',
          'helper': '#287a72', 'guest': '#287a72'}
BAD_RESPONSES = []
SHOTS = None

# A 1x1 PNG for every /api/media/* still (thread photos, album cells, the
# Moments rings' posters, the lightbox).
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=')
ORB_BACK = ("document.getElementById('tab-argyle').checkVisibility("
            "{visibilityProperty: true, opacityProperty: true})")


def seed():
    # Roster order = alphabetical order for the household (Alex, Lorena,
    # Robin, Sam), so the family member line reads the same either way.
    order = [('parent', 'parent', 'd1'), ('lorena', 'adult', None), ('adult', 'adult', 'd2'),
             ('navigator', 'child', None), ('helper', 'helper', 'd3'), ('guest', 'guest', None)]
    for key, role, driver in order:
        member = {'id': key, 'name': NAMES[key], 'role': role, 'driver_id': driver,
                  'color_code': COLORS[key]}
        if role == 'child':
            member['stage_override'] = 'navigator'
        if key == 'helper':
            # The helper preset reads event threads 'invited'; this helper
            # cannot read them at all, so an event thread she was not let
            # into is the share-only surface (openChannel: helperShareMode =
            # scopeOf('chat.event_threads') === 'none' && not in member_ids).
            member['scope'] = {'preset': 'helper', 'overrides': {'chat.event_threads': 'none'}}
        storage.add_member(member)
        if driver:
            storage.add_driver({'id': driver, 'name': NAMES[key], 'home_location': 'Home',
                                'color_code': COLORS[key]})


# --- fixtures ----------------------------------------------------------------

def at(days_ago, hour, minute):
    """A message timestamp (seconds) on a day relative to the fixed clock."""
    return int((NOW - timedelta(days=days_ago)).replace(hour=hour, minute=minute).timestamp())


def msg(mid, cid, sender, body, ts, **extra):
    """A GET /api/channels/{id}/messages row as renderThread reads it."""
    row = dict(id=mid, channel_id=cid, sender_member_id=sender, body=body, ts=ts, reactions={})
    row.update(extra)
    return row


def ask(ask_id, what):
    """services/asks.py _card(): the shape renderAskCard reads."""
    return {'kind': 'ask', 'ask_id': ask_id, 'what': what, 'state': 'open', 'outcome': None,
            'actions': [{'label': 'Yes', 'style': 'primary', 'ask_id': ask_id, 'act': 'yes'},
                        {'label': 'No', 'style': 'default', 'ask_id': ask_id, 'act': 'no'}]}


THEIRS = 'Did you move the dentist?'
MINE = 'I can grab Sam if it runs long'
FAMILY_LINE = 'Lorena, Robin, Sam'
ARGYLE_LINE = 'Ask anything · every exchange lands here'
SWAP_ASK = ask('a-swap', "Swap Sam's piano pickup to Alex at 5:30?")
RUTH_ASK = ask('a-ruth', 'Ask Grandma Ruth to take Kate Thursday at 5:10?')
PHOTO = {'url': '/api/media/fam-photo.jpg', 'kind': 'photo'}
ALBUM = {'items': [{'url': '/api/media/s1.jpg', 'kind': 'photo'},
                   {'url': '/api/media/s2.jpg', 'kind': 'photo'},
                   {'url': '/api/media/s3.jpg', 'kind': 'photo'}]}
CLIP = {'url': '/api/media/v1.mp4', 'kind': 'video'}


def family_thread():
    """Yesterday then today; theirs (Lorena), mine, Argyle with an ask card,
    a photo, reactions on the first. The last one is the list's preview."""
    return [msg('f1', 'family', 'lorena', 'Practice might go late, coach said', at(1, 18, 20),
                reactions={'❤️': ['adult']}),
            msg('f2', 'family', 'parent', MINE, at(1, 18, 24)),
            msg('f3', 'family', 'argyle', "If practice runs to 5:30, Sam's piano pickup lands on Lorena. "
                                          'Want me to swap it?', at(0, 8, 15), card=SWAP_ASK),
            msg('f4', 'family', 'lorena', '', at(0, 9, 2), attachment=PHOTO),
            msg('f5', 'family', 'lorena', THEIRS, at(0, 9, 40))]


FAMILY = {'id': 'family', 'kind': 'family', 'title': 'Family', 'member_ids': []}
DM_ROBIN = {'id': 'dm_robin', 'kind': 'dm', 'member_ids': ['parent', 'adult']}
DM_ARGYLE = {'id': 'dm_argyle', 'kind': 'dm', 'member_ids': ['parent', 'argyle']}
DM_ARGYLE_ADULT = {'id': 'dm_argyle_adult', 'kind': 'dm', 'member_ids': ['adult', 'argyle']}
DM_HELPER = {'id': 'dm_helper', 'kind': 'dm', 'member_ids': ['helper', 'parent']}
EV_SOCCER = {'id': 'ev_soccer', 'kind': 'event', 'title': 'Soccer practice', 'event_id': 'soccer',
             'event_end': EVENT_END, 'member_ids': []}
EV_PIANO = {'id': 'ev_piano', 'kind': 'event', 'title': 'Piano lesson', 'event_id': 'piano',
            'event_end': DAY + 'T18:00:00', 'member_ids': []}
SCHOOL = {'id': 'school', 'kind': 'group', 'title': 'School pickup', 'member_ids': ['parent', 'adult', 'lorena']}


def moment_row(mid, cid, title, kind, media, poster, sender, ts, items):
    """GET /api/presence/moments row (services/presence.py _moment_row)."""
    return {'id': mid, 'channel_id': cid, 'ts': ts, 'body': '', 'kind': kind, 'media_url': media,
            'poster_url': poster, 'attachment': {}, 'reactions': {}, 'event_id': None,
            'event_title': title, 'sender_name': NAMES[sender], 'sender_color': COLORS[sender],
            'sender_avatar': None, 'sender_member_id': sender, 'items': items}


def schedule_for(driver):
    event = {'id': 'soccer', 'title': 'Soccer practice', 'start': DAY + 'T16:00:00', 'end': EVENT_END,
             'location': 'Riverside fields', 'calendar_ids': [], 'event_type': 'activity'}
    later = dict(event, id='piano', title='Piano lesson', start=DAY + 'T17:30:00',
                 end=DAY + 'T18:00:00', location='Music studio')
    return {'events': [event, later], 'assignments': {'soccer': driver, 'piano': driver},
            'home_location': 'Home', 'calendar_metadata': {},
            'initial_edges': {driver: {'soccer': {'travel_mins': 20, 'buffer_before_mins': 5}}} if driver else {},
            'route_edges': {}, 'final_edges': {}}


class Mocks:
    """One profile's server, as page.route answers it. State is mutable so a
    write changes what the next read returns; `calls` records every write."""

    def __init__(self, key, driver):
        self.key = key
        self.driver = driver
        self.calls = []
        self.meta = {}
        self.threads = {}
        self.unread = {}
        self.dm_for = {}
        self.moments = []
        self.message_gets = {}
        if key == 'parent':
            for meta in (FAMILY, DM_ROBIN, DM_ARGYLE, EV_SOCCER, EV_PIANO, SCHOOL):
                self.meta[meta['id']] = copy.deepcopy(meta)
            self.threads = {
                'family': family_thread(),
                'dm_robin': [msg('r0', 'dm_robin', 'parent', 'Can you take Sam Thursday?', at(0, 13, 0)),
                             msg('r1', 'dm_robin', 'adult', 'Running ten minutes late', at(0, 14, 5))],
                'dm_argyle': [msg('a1', 'dm_argyle', 'parent', 'Can Grandma take Kate Thursday?', at(1, 20, 9)),
                              msg('a2', 'dm_argyle', 'argyle', 'Grandma Ruth is free Thursday at 5:10.',
                                  at(1, 20, 10), card=RUTH_ASK)],
                'ev_soccer': [msg('s-album', 'ev_soccer', 'parent', '', at(0, 13, 30), attachment=ALBUM)],
                'ev_piano': [msg('p-clip', 'ev_piano', 'lorena', '', at(2, 18, 0), attachment=CLIP)],
                'school': [msg('k1', 'school', 'lorena', 'Who has Tuesday?', at(3, 7, 50)),
                           msg('k2', 'school', 'parent', 'I can take the Tuesday run', at(3, 8, 5))]}
            self.unread = {'family': 2, 'dm_robin': 1}
            self.dm_for = {'argyle': DM_ARGYLE, 'adult': DM_ROBIN}
            self.moments = [
                moment_row('s-album', 'ev_soccer', 'Soccer practice', 'photo', '/api/media/s1.jpg',
                           '/api/media/s1.jpg', 'parent', at(0, 13, 30),
                           [{'kind': 'photo', 'media_url': i['url'], 'poster_url': i['url']} for i in ALBUM['items']]),
                moment_row('p-clip', 'ev_piano', 'Piano lesson', 'video', '/api/media/v1.mp4',
                           '/api/media/v1.jpg', 'lorena', at(2, 18, 0),
                           [{'kind': 'video', 'media_url': '/api/media/v1.mp4', 'poster_url': '/api/media/v1.jpg'}])]
        elif key == 'adult':
            # No Argyle DM yet (the synthetic pinned row), no event thread
            # (the Add ring and the camera's "start from an event"), no moments
            # (the strip stays absent).
            for meta in (FAMILY, DM_ROBIN):
                self.meta[meta['id']] = copy.deepcopy(meta)
            self.threads = {
                'family': family_thread(),
                'dm_robin': [msg('r0', 'dm_robin', 'parent', 'Can you take Sam Thursday?', at(0, 13, 0)),
                             msg('r1', 'dm_robin', 'adult', 'Running ten minutes late', at(0, 14, 5))]}
            self.dm_for = {'argyle': DM_ARGYLE_ADULT, 'parent': DM_ROBIN}
        elif key == 'helper':
            # A helper lists her DMs only (chat.family/groups none); the event
            # thread reaches her through My Day's "Add a moment"
            # (openEventThread -> POST api/channels/event), not the list.
            self.meta['dm_helper'] = copy.deepcopy(DM_HELPER)
            self.threads = {'dm_helper': [msg('h1', 'dm_helper', 'parent', 'Pickup is at 3:15 today', at(0, 11, 0))],
                            'ev_soccer': [msg('s-album', 'ev_soccer', 'parent', '', at(0, 13, 30), attachment=ALBUM)]}
            self.dm_for = {'parent': DM_HELPER}
        elif key == 'guest':
            # A guest's list is the one event thread she was invited into.
            self.meta['ev_soccer'] = dict(copy.deepcopy(EV_SOCCER), member_ids=['guest'])
            self.threads = {'ev_soccer': [msg('s-album', 'ev_soccer', 'parent', '', at(0, 13, 30), attachment=ALBUM),
                                          msg('g1', 'ev_soccer', 'lorena', 'Thanks for coming, Gail!', at(0, 14, 30))]}
            self.unread = {'ev_soccer': 1}
        else:
            self.meta['family'] = copy.deepcopy(FAMILY)
            self.meta['cousins'] = {'id': 'cousins', 'kind': 'group', 'title': 'Cousins',
                                    'member_ids': ['navigator', 'lorena']}
            self.threads = {'family': [msg('k-f1', 'family', 'lorena', 'Dinner at six', at(0, 12, 0))],
                            'cousins': [msg('k-c1', 'cousins', 'lorena', 'Sleepover Friday?', at(1, 19, 0))]}

    # --- the payload the list reads (main.py list_channels) ---
    def payload(self):
        out = []
        for cid, meta in self.meta.items():
            thread = self.threads.get(cid) or []
            last = copy.deepcopy(thread[-1]) if thread else None
            if not last and meta['kind'] != 'family':
                continue   # the server lists an empty channel only for the family hub
            out.append(dict(copy.deepcopy(meta), last_message=last, unread=self.unread.get(cid, 0)))
        out.sort(key=lambda c: (0 if c['kind'] == 'family' else 1, -((c['last_message'] or {}).get('ts') or 0)))
        return out

    # --- the recorder ---
    def record(self, route):
        req = route.request
        try:
            body = req.post_data_json
        except Exception:
            body = req.post_data
        self.calls.append({'method': req.method, 'path': urlparse(req.url).path, 'body': body})
        return self.calls[-1]

    def last_call(self, method, path_pattern):
        hits = [c for c in self.calls if c['method'] == method and re.search(path_pattern, c['path'])]
        assert hits, (method, path_pattern, self.calls)
        return hits[-1]

    def posts_to(self, path_pattern):
        return [c for c in self.calls if c['method'] == 'POST' and re.search(path_pattern, c['path'])]

    # --- handlers ---
    def channels_list(self, route):
        if route.request.method != 'GET':
            return route.continue_()
        route.fulfill(json=self.payload())

    def open_dm(self, route):
        # POST {member_id, other_member_id} (messageMember, startNewChat,
        # pwaOpenArgyle, PwaArgyle.ensureDm); answers the channel object.
        if route.request.method != 'POST':
            return route.continue_()
        call = self.record(route)
        body = call['body'] if isinstance(call['body'], dict) else {}
        ch = self.dm_for.get(body.get('other_member_id'))
        if not ch:
            return route.fulfill(status=403, json={'detail': 'not in this fixture'})
        route.fulfill(json=copy.deepcopy(ch))

    def open_event(self, route):
        # openEventThread (app.html ~3495): POST {event_id, title, event_end}.
        if route.request.method != 'POST':
            return route.continue_()
        self.record(route)
        # The parent's thread: the helper is NOT in member_ids.
        route.fulfill(json=dict(copy.deepcopy(EV_SOCCER), member_ids=['parent']))

    def messages(self, route):
        req = route.request
        cid = urlparse(req.url).path.rstrip('/').split('/')[-2]
        if req.method == 'POST':
            call = self.record(route)
            body = call['body'] if isinstance(call['body'], dict) else {}
            row = msg('sent-%d' % len(self.calls), cid, body.get('sender_member_id'), body.get('body') or '',
                      int(NOW.timestamp()) + len(self.calls))
            self.threads.setdefault(cid, []).append(row)
            return route.fulfill(json=row)
        if req.method != 'GET':
            return route.continue_()
        self.message_gets[cid] = self.message_gets.get(cid, 0) + 1
        limit = int(parse_qs(urlparse(req.url).query).get('limit', ['50'])[0])
        route.fulfill(json=copy.deepcopy((self.threads.get(cid) or [])[-limit:]))

    def read(self, route):
        # markRead (app.html ~6481): POST {member_id, ts}.
        if route.request.method != 'POST':
            return route.continue_()
        call = self.record(route)
        self.unread[call['path'].rstrip('/').split('/')[-2]] = 0
        route.fulfill(json={'status': 'ok'})

    def react(self, route):
        # reactTo (app.html ~5263): POST {member_id, emoji}; toggles.
        if route.request.method != 'POST':
            return route.continue_()
        call = self.record(route)
        mid = call['path'].rstrip('/').split('/')[-2]
        body = call['body'] if isinstance(call['body'], dict) else {}
        for thread in self.threads.values():
            for m in thread:
                if m['id'] == mid:
                    who = m.setdefault('reactions', {}).setdefault(body.get('emoji'), [])
                    (who.remove if body.get('member_id') in who else who.append)(body.get('member_id'))
                    return route.fulfill(json=copy.deepcopy(m))
        route.fulfill(status=404, json={'detail': 'Message not found'})

    def answer(self, route):
        self.record(route)
        route.fulfill(json={'ok': True})

    def install(self, page):
        key = self.key
        schedule = schedule_for(self.driver)
        page.route('**/api/schedule?*', lambda r: r.fulfill(json=schedule))
        page.route('**/api/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/messages/stream*', lambda r: r.fulfill(status=204, body=''))
        page.route('**/api/music/favorites*', lambda r: r.fulfill(json={'items': []}))

        def member_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'member_id': key, 'name': NAMES[key], 'date': date, 'rides': [],
                                'due_soon': [], 'still_open': [], 'status_days': [], 'launch': None})
        page.route('**/api/members/*/day?*', member_day)

        def routine_day(route):
            date = parse_qs(urlparse(route.request.url).query).get('date', [DAY])[0]
            route.fulfill(json={'date': date, 'items': [], 'streak': {}})
        page.route('**/api/routines/day?*', routine_day)
        page.route('**/api/requests?*', lambda r: r.fulfill(json={'waiting_on_me': [], 'mine': []}))
        page.route('**/api/proposals?*', lambda r: r.fulfill(json=[]))
        page.route('**/api/weather/now*', lambda r: r.fulfill(status=200, content_type='application/json', body='null'))
        page.route('**/api/commitments?*', lambda r: r.fulfill(json=[]))
        page.route('**/api/chores', lambda r: r.fulfill(json=[]))
        page.route('**/api/points', lambda r: r.fulfill(json=[]))
        page.route('**/api/rewards', lambda r: r.fulfill(json=[]))
        page.route('**/api/redemptions?*', lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/household-tasks(\?[^/]*)?$'), lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/shopping/lists(\?.*)?$'), lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/shopping/items(\?.*)?$'), lambda r: r.fulfill(json=[]))
        page.route(re.compile(r'.*/api/shopping/runs(\?.*)?$'), lambda r: r.fulfill(json={
            'shop_date': None, 'groups': [], 'runs': {'guess': None, 'scheduled': None, 'next': None},
            'late': [], 'top_up': False, 'counts': {}}))
        page.route(re.compile(r'.*/api/projects(\?.*)?$'), lambda r: r.fulfill(json={'projects': []}))
        page.route('**/api/projects/elsewhere*', lambda r: r.fulfill(json={'situations': []}))
        page.route(re.compile(r'.*/api/programs(\?.*)?$'), lambda r: r.fulfill(json={'programs': []}))
        page.route('**/api/programs/*/lesson*', lambda r: r.fulfill(json={}))
        page.route('**/api/practice-windows*', lambda r: r.fulfill(json={'windows': []}))
        page.route('**/api/situations?*', lambda r: r.fulfill(json={'situations': []}))
        # Messages: the list, the doors that open a channel, a thread's
        # reads and writes, the Moments row and every still it draws.
        page.route('**/api/channels?*', self.channels_list)
        page.route('**/api/channels/dm', self.open_dm)
        page.route('**/api/channels/event', self.open_event)
        page.route('**/api/channels/*/messages*', self.messages)
        page.route('**/api/channels/*/read', self.read)
        page.route('**/api/messages/*/react', self.react)
        page.route('**/api/asks/*/answer', self.answer)
        page.route('**/api/presence/moments*', lambda r: r.fulfill(json=self.moments))
        page.route('**/api/media/**', lambda r: r.fulfill(status=200, content_type='image/png', body=PNG))


# --- page helpers ------------------------------------------------------------

def norm(text):
    return ' '.join((text or '').split())


def settle(page, condition, timeout=6000, arg=None):
    """Give an async re-render the chance to land; the assertion that follows
    says what was wrong if it never did."""
    try:
        if arg is None:
            page.wait_for_function('() => ' + condition, timeout=timeout)
        else:
            page.wait_for_function(condition, arg=arg, timeout=timeout)
    except Exception:
        pass


def shot(page, name):
    if SHOTS:
        page.mouse.move(0, 0)
        Path(SHOTS, name).write_bytes(page.screenshot())


def no_overflow(page):
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), \
        page.evaluate('[document.documentElement.scrollWidth, innerWidth]')


def is_channels_get(request):
    return request.method == 'GET' and urlparse(request.url).path.endswith('/api/channels')


def is_messages_get(cid):
    return lambda r: r.method == 'GET' and urlparse(r.url).path.endswith(f'/api/channels/{cid}/messages')


def is_post(path_suffix):
    return lambda r: r.request.method == 'POST' and urlparse(r.url).path.endswith(path_suffix)


def is_post_request(path_suffix):
    return lambda r: r.method == 'POST' and urlparse(r.url).path.endswith(path_suffix)


# pwaConversationRows (static/pwa_messages.js) over the payload the mock
# served, with the page's own identity, roster, clock, Argyle gate, channel
# display and attachment wording.
ORACLE = r"""(channels) => {
    const r = pwaConversationRows(channels, {meId: selectedMemberId, members: membersData, now: Date.now(),
        argyleAllowed: pwaOrbAllowed(), display: channelDisplay, previewLabel: momentPreviewLabel});
    const n = s => String(s ?? '').replace(/\s+/g, ' ').trim();
    const f = x => ({id: x.id ?? null, kind: x.kind, name: n(x.name), time: n(x.time), preview: n(x.preview),
                     unread: x.unread || 0, unreadStyle: x.unreadStyle});
    return {pinned: (r.pinned || []).map(f), chats: (r.chats || []).map(f)};
}"""

# The painted list, in document order: each label opens a group; rows are
# DIRECT children of #channel-list (the search and the kid check rely on it).
LIST_DOM = r"""() => {
    const n = s => String(s ?? '').replace(/\s+/g, ' ').trim();
    const groups = []; let g = null;
    document.querySelectorAll('#channel-list .pwa-conv-label, #channel-list > button.pwa-conv').forEach(e => {
        if (e.classList.contains('pwa-conv-label')) {
            g = {label: n(e.textContent), visible: e.checkVisibility(), rows: []}; groups.push(g); return;
        }
        if (!g) { g = {label: null, visible: false, rows: []}; groups.push(g); }
        const nameEl = e.querySelector('.pwa-conv-name');
        let name = null;
        if (nameEl) { const c = nameEl.cloneNode(true); c.querySelectorAll('.pwa-conv-time').forEach(t => t.remove()); name = n(c.textContent); }
        const pv = e.querySelector('.pwa-conv-preview');
        const count = e.querySelector('.pwa-conv-count');
        g.rows.push({id: e.getAttribute('data-channel'), name, time: n(e.querySelector('.pwa-conv-time')?.textContent),
            preview: pv ? n(pv.textContent) : null, u: !!pv && pv.classList.contains('u'),
            dot: !!e.querySelector('.pwa-conv-dot'), count: count ? n(count.textContent) : null,
            av: !!e.querySelector('.pwa-conv-av'), tx: !!e.querySelector('.pwa-conv-tx'), visible: e.checkVisibility()});
    });
    return groups;
}"""

# Every row's id, name, time, preview, unread weight and badge against the
# oracle, group by group; Pinned / Chats labels only for a non-empty group.
CHECK = r"""(channels) => {
    const o = (%s)(channels);
    const d = (%s)();
    const bad = [];
    const want = [];
    if (o.pinned.length) want.push(['Pinned', o.pinned]);
    if (o.chats.length) want.push(['Chats', o.chats]);
    const labels = d.map(g => g.label);
    if (JSON.stringify(labels) !== JSON.stringify(want.map(w => w[0]))) bad.push({labels, want: want.map(w => w[0])});
    want.forEach(([label, rows], i) => {
        const got = (d[i] || {rows: []}).rows;
        if (got.length !== rows.length) bad.push({label, rows: got.map(r => r.name), want: rows.map(r => r.name)});
        rows.forEach((w, j) => {
            const g = got[j]; if (!g) return;
            const count = w.unreadStyle === 'count' ? (w.unread > 99 ? '99+' : String(w.unread)) : null;
            const exp = {id: w.id === null ? g.id : w.id, name: w.name, time: w.time, preview: w.preview,
                         u: w.unread > 0, dot: w.unreadStyle === 'dot', count, av: true, tx: true};
            const have = {id: g.id, name: g.name, time: g.time, preview: g.preview, u: g.u, dot: g.dot,
                          count: g.count, av: g.av, tx: g.tx};
            if (JSON.stringify(exp) !== JSON.stringify(have)) bad.push({label, row: j, want: exp, got: have});
        });
    });
    return {bad, oracle: o};
}""" % (ORACLE, LIST_DOM)

CHECK_SETTLED = r"""(channels) => { try { return (%s)(channels).bad.length === 0; } catch (e) { return false; } }""" % CHECK

THREAD_HOME = r"""() => { const t = document.getElementById('thread-view');
    return {stack: !!t.closest('#pwa-stack .pwa-screen[data-screen="thread"]'),
            messages: !!t.parentElement && t.parentElement.id === 'messages-container',
            display: getComputedStyle(t).display}; }"""

VISIBLE_ROWS = r"""() => [...document.querySelectorAll('#channel-list > button')]
    .filter(b => b.checkVisibility()).map(b => b.getAttribute('data-channel'))"""

# A text bubble: the leaf div in #msg-<id> whose text is the body.
BUBBLE = r"""(a) => { const m = document.getElementById('msg-' + a.id); if (!m) return null;
    const b = [...m.querySelectorAll('div')].find(d => !d.children.length && d.textContent.trim() === a.body);
    if (!b) return null; const r = b.getBoundingClientRect();
    return {bg: getComputedStyle(b).backgroundColor, top: r.top}; }"""

ACCENT_PROBE = r"""() => { const p = document.createElement('div'); p.style.background = 'var(--pwa-accent)';
    document.getElementById('thread-messages').append(p); const c = getComputedStyle(p).backgroundColor;
    p.remove(); return c; }"""

# renderAskCard's box: the Yes button's row's parent (renderCard is kept;
# only CSS changes its look).
CARD = r"""(id) => { const m = document.getElementById('msg-' + id); if (!m) return null;
    const yes = [...m.querySelectorAll('button')].find(b => b.textContent.trim() === 'Yes');
    if (!yes) return null; const box = yes.parentElement.parentElement; const s = getComputedStyle(box);
    return {bg: s.backgroundColor, border: s.borderTopWidth, style: s.borderTopStyle,
            buttons: [...yes.parentElement.querySelectorAll('button')].map(b => {
                const r = b.getBoundingClientRect();
                return {text: b.textContent.trim(), visible: b.checkVisibility(), h: r.height,
                        radius: parseFloat(getComputedStyle(b).borderTopLeftRadius) || 0}; })}; }"""

HEAD_AVATAR = r"""() => { const h = document.querySelector('#pwa-stack .pwa-screen[data-screen="thread"] .pwa-thread-head');
    if (!h) return null;
    return [...h.querySelectorAll('*')].some(e => { const r = e.getBoundingClientRect();
        return Math.abs(r.width - 38) <= 1 && Math.abs(r.height - 38) <= 1; }); }"""


def conv(page, cid):
    return page.locator(f'#channel-list > button.pwa-conv[data-channel="{cid}"]')


def top_screen(page):
    return page.locator('#pwa-stack .pwa-screen').last


def open_messages(page):
    """Tap the Messages tab; the list must draw its Pinned / Chats labels
    (the first failure before Task 4: there are none)."""
    page.locator('#tab-messages').click()
    page.wait_for_function("currentView === 'messages'")
    settle(page, "document.querySelectorAll('#channel-list .pwa-conv-label').length > 0", timeout=8000)
    assert page.locator('#channel-list .pwa-conv-label').count() > 0, \
        '.pwa-conv-label missing: the adult Messages tab drew no Pinned / Chats labels in #channel-list'


def assert_list(page, mocks, profile):
    payload = mocks.payload()
    settle(page, CHECK_SETTLED, timeout=8000, arg=payload)
    r = page.evaluate(CHECK, payload)
    assert not r['bad'], (profile, 'the list differs from pwaConversationRows', r['bad'])
    return r['oracle']


def expect_thread(page, title, back='‹ Messages'):
    """The thread is ONE pushed screen over the list; it adopted #thread-view."""
    settle(page, "PwaNav.depth() === 1 && !!document.querySelector('#pwa-stack .pwa-screen[data-screen=\"thread\"] h1')"
                 " && document.querySelector('#pwa-stack .pwa-screen[data-screen=\"thread\"] h1').textContent.trim() === %s"
           % json.dumps(title), timeout=8000)
    assert page.evaluate('PwaNav.depth()') == 1, ('no pushed thread screen for', title, page.evaluate('PwaNav.depth()'))
    assert page.locator('#pwa-stack .pwa-screen').count() == 1, page.locator('#pwa-stack .pwa-screen').count()
    assert page.locator('#pwa-stack .pwa-screen[data-screen="thread"]').count() == 1, 'the screen is not data-screen="thread"'
    h1 = norm(page.locator('#pwa-stack .pwa-screen h1').last.text_content())
    assert h1 == title, (h1, title)
    if back:
        label = norm(page.locator('#pwa-stack .pwa-screen .pwa-back').last.text_content())
        assert label == back, (label, back)
    assert page.evaluate('currentView') == 'messages', page.evaluate('currentView')
    home = page.evaluate(THREAD_HOME)
    assert home == {'stack': True, 'messages': False, 'display': 'flex'}, ('#thread-view was not adopted', home)


def assert_thread_home(page):
    """The thread closed: no screen, #thread-view back under
    #messages-container and hidden, the open-thread state reset."""
    settle(page, "PwaNav.depth() === 0 && document.getElementById('thread-view').parentElement.id === 'messages-container'")
    assert page.evaluate('PwaNav.depth()') == 0, page.evaluate('PwaNav.depth()')
    assert page.locator('#pwa-stack .pwa-screen').count() == 0, 'a thread screen stayed in #pwa-stack'
    home = page.evaluate(THREAD_HOME)
    assert home == {'stack': False, 'messages': True, 'display': 'none'}, ('#thread-view did not go home', home)
    assert page.evaluate('activeChannelId') is None, page.evaluate('activeChannelId')
    assert page.evaluate('threadChannel') is None, 'threadChannel survived the close'


def back_by_button(page):
    with page.expect_request(is_channels_get):
        page.locator('#pwa-stack .pwa-screen .pwa-back').last.click()
    assert_thread_home(page)


def back_by_history(page):
    with page.expect_request(is_channels_get):
        page.go_back()
    assert_thread_home(page)


def same_row(a, b):
    return a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']


# --- scenarios: parent ----------------------------------------------------------

def list_is_signals(page, mocks):
    open_messages(page)
    labels = [norm(t) for t in page.locator('#channel-list .pwa-conv-label').all_text_contents()]
    assert labels == ['Pinned', 'Chats'], labels
    o = assert_list(page, mocks, 'parent')
    # From the payload: the family hub, then the Argyle DM; the rest in the
    # server's order (most recent first), Argyle taken out of it.
    assert [r['id'] for r in o['pinned']] == ['family', 'dm_argyle'], o['pinned']
    assert [r['id'] for r in o['chats']] == ['dm_robin', 'ev_soccer', 'ev_piano', 'school'], o['chats']
    rows = page.locator('#channel-list > button.pwa-conv')
    assert rows.count() == 6, rows.count()
    for i in range(rows.count()):
        for part in ('.pwa-conv-av', '.pwa-conv-name', '.pwa-conv-time', '.pwa-conv-preview'):
            assert rows.nth(i).locator(part).count() == 1, (i, part)
    fam = conv(page, 'family')
    assert norm(fam.locator('.pwa-conv-count').text_content()) == '2'
    assert 'u' in (fam.locator('.pwa-conv-preview').get_attribute('class') or '').split(), 'the unread preview is not weighted'
    assert norm(fam.locator('.pwa-conv-preview').text_content()) == 'Lorena: ' + THEIRS
    assert norm(fam.locator('.pwa-conv-time').text_content()) == '9:40'
    robin = conv(page, 'dm_robin')
    assert robin.locator('.pwa-conv-dot').count() == 1 and robin.locator('.pwa-conv-count').count() == 0
    assert norm(conv(page, 'ev_soccer').locator('.pwa-conv-preview').text_content()) == 'You: 📷 3 photos'
    assert conv(page, 'ev_soccer').locator('.pwa-conv-dot, .pwa-conv-count').count() == 0
    # Signal's list: no cards, no borders.
    assert page.locator('#channel-list .rounded-2xl').count() == 0, 'card borders still draw in the list'
    borders = rows.evaluate_all("els => els.map(e => { const s = getComputedStyle(e); return s.borderTopWidth + ' ' + s.borderBottomWidth; })")
    assert set(borders) == {'0px 0px'}, borders
    # The title row: 34px "Messages", the presence stack, the camera, compose.
    title = page.locator('#messages-container .pwa-msg-title')
    assert title.count() == 1 and title.is_visible(), '.pwa-msg-title missing'
    assert title.evaluate('e => e.tagName') == 'H1'
    assert norm(title.text_content()) == 'Messages'
    assert title.evaluate('e => getComputedStyle(e).fontSize') == '34px'
    assert title.evaluate('e => getComputedStyle(e).fontWeight') == '700'
    heading = page.locator('#pwa-page-heading')
    assert not (heading.is_visible() and 'Messages' in norm(heading.text_content())), \
        'the #pwa-page-heading entry for Messages still draws over the in-page title'
    assert page.locator('#presence-stack').count() == 1
    page.evaluate("onlineMemberIds = ['adult', 'lorena']; renderPresence()")
    tbox = title.bounding_box()
    assert page.locator('#presence-stack').is_visible()
    assert same_row(page.locator('#presence-stack').bounding_box(), tbox), 'the presence stack left the title row'
    for sel, name in (('#messages-add-moment', 'Add a moment'), ('#messages-new-chat', None)):
        btn = page.locator(sel)
        assert btn.count() == 1 and btn.is_visible(), sel + ' missing'
        box = btn.bounding_box()
        assert round(box['width']) == 36 and round(box['height']) == 36, (sel, box)
        assert btn.evaluate('e => parseFloat(getComputedStyle(e).borderTopLeftRadius)') >= 18, sel + ' is not a circle'
        assert same_row(box, tbox), sel + ' is not on the title row'
        if name:
            assert btn.get_attribute('aria-label') == name, (sel, btn.get_attribute('aria-label'))
    search = page.get_by_role('searchbox', name='Find a conversation')
    assert search.count() == 1 and search.is_visible()
    # The Moments row: Add first, then a ring per moment, the event under each.
    settle(page, "document.querySelectorAll('#moments-strip-row .pwa-mo').length === 3")
    assert page.locator('#moments-strip').is_visible(), 'the Moments row is hidden'
    rings = [norm(t) for t in page.locator('#moments-strip-row .pwa-mo').all_text_contents()]
    assert rings == ['Add', 'Soccer practice', 'Piano lesson'], rings
    assert 'add' in (page.locator('#moments-strip-row .pwa-mo').first.get_attribute('class') or '').split()
    assert page.locator('#moments-strip-row .pwa-mo.add').count() == 1
    shot(page, 'messages-list-light.png')


def search_filters(page, mocks):
    search = page.get_by_role('searchbox', name='Find a conversation')
    search.fill('Soccer')
    settle(page, "(%s)().length === 1" % VISIBLE_ROWS)
    assert page.evaluate(VISIBLE_ROWS) == ['ev_soccer'], page.evaluate(VISIBLE_ROWS)
    assert page.locator('#channel-list .pwa-conv-label:visible').count() == 0, 'the labels stay up while searching'
    search.fill('')
    settle(page, "(%s)().length === 6" % VISIBLE_ROWS)
    assert len(page.evaluate(VISIBLE_ROWS)) == 6, page.evaluate(VISIBLE_ROWS)
    assert page.locator('#channel-list .pwa-conv-label:visible').count() == 2, 'clearing did not bring the labels back'
    search.blur()


def add_moment_ring(page, mocks):
    """Add posts into an event thread: choose one (two exist), the thread is
    pushed with the photo picker pulsing."""
    page.locator('#moments-strip-row .pwa-mo.add').click()
    page.wait_for_selector('.pwa-prompt-overlay', state='visible')
    sheet = page.locator('.pwa-prompt-overlay').last
    assert 'Add a moment to' in norm(sheet.inner_text()), sheet.inner_text()
    picks = [norm(t) for t in sheet.locator('[data-pick]').all_text_contents()]
    assert picks == ['Soccer practice', 'Piano lesson'], picks
    with page.expect_request(is_messages_get('ev_soccer')):
        sheet.locator('[data-pick]').filter(has_text='Soccer practice').click()
    expect_thread(page, 'Soccer practice')
    settle(page, "document.getElementById('thread-attach-btn').classList.contains('animate-pulse')")
    attach = page.locator('#thread-attach-btn')
    assert attach.is_visible(), '#thread-attach-btn is hidden in the event thread'
    assert 'animate-pulse' in (attach.get_attribute('class') or '').split(), 'the photo picker is not armed'
    shot(page, 'messages-add-moment.png')
    back_by_button(page)
    assert 'animate-pulse' not in (attach.get_attribute('class') or '').split(), 'the pulse outlived the thread'
    # The header camera is the same door.
    page.locator('#messages-add-moment').click()
    page.wait_for_selector('.pwa-prompt-overlay', state='visible')
    sheet = page.locator('.pwa-prompt-overlay').last
    assert [norm(t) for t in sheet.locator('[data-pick]').all_text_contents()] == ['Soccer practice', 'Piano lesson']
    sheet.locator('[data-no]').click()
    page.wait_for_function("document.querySelectorAll('.pwa-prompt-overlay').length === 0")
    assert page.evaluate('PwaNav.depth()') == 0, 'cancelling the chooser opened a thread'


def thread_is_messengers(page, mocks):
    with page.expect_request(is_post_request('/api/channels/family/read')):
        conv(page, 'family').click()
    expect_thread(page, 'Family')
    call = mocks.last_call('POST', r'/api/channels/family/read$')
    assert call['body'] == {'member_id': 'parent', 'ts': family_thread()[-1]['ts']}, call
    settle(page, "!!document.getElementById('msg-f5')")
    head = top_screen(page).locator('.pwa-thread-head')
    assert head.count() == 1 and head.is_visible(), '.pwa-thread-head missing from the thread screen'
    assert page.evaluate(HEAD_AVATAR), 'the thread head has no 38px avatar'
    assert norm(head.locator('.pwa-thread-sub').text_content()) == FAMILY_LINE, \
        norm(head.locator('.pwa-thread-sub').text_content())
    days = [norm(t) for t in page.locator('#thread-messages .pwa-day').all_text_contents()]
    assert days == ['Yesterday', 'Today'], days
    theirs = page.evaluate(BUBBLE, {'id': 'f5', 'body': THEIRS})
    assert theirs, 'the theirs bubble is missing'
    assert theirs['bg'] == 'rgba(31, 29, 43, 0.06)', theirs
    who = page.locator('#msg-f5 .pwa-who')
    assert who.count() == 1, '.pwa-who (the sender name) is missing on a theirs message'
    assert norm(who.text_content()).startswith('Lorena'), norm(who.text_content())
    wbox = who.bounding_box()
    assert wbox['y'] + wbox['height'] <= theirs['top'] + 1, ('the sender name is not above the bubble', wbox, theirs)
    mine = page.evaluate(BUBBLE, {'id': 'f2', 'body': MINE})
    assert mine and mine['bg'] == page.evaluate(ACCENT_PROBE), (mine, page.evaluate(ACCENT_PROBE))
    assert page.locator('#msg-f2 .pwa-who').count() == 0, 'mine carries a sender name'
    photo = page.locator('#msg-f4 img').first
    radii = photo.evaluate("e => [getComputedStyle(e).borderTopLeftRadius, getComputedStyle(e).borderTopRightRadius]")
    assert radii == ['16px', '16px'], radii
    card = page.evaluate(CARD, 'f3')
    assert card, "Argyle's ask card is missing from the family thread"
    assert card['bg'] == 'rgb(255, 255, 255)' and card['border'] == '1px' and card['style'] == 'solid', card
    assert [b['text'] for b in card['buttons']] == ['Yes', 'No'], card['buttons']
    for b in card['buttons']:
        assert b['visible'] and b['radius'] >= b['h'] / 2 - 1, ('the card buttons are not pills', b)
    assert '❤️' in norm(page.locator('#msg-f1').text_content()), 'the reaction on f1 is missing'
    # ☺+ still reacts.
    page.locator('#msg-f1 button').filter(has_text='☺+').first.click()
    quick = page.locator('#qr-f1')
    assert quick.is_visible(), '☺+ did not open the quick reactions'
    with page.expect_response(is_post('/api/messages/f1/react')):
        quick.get_by_role('button', name='👍', exact=True).click()
    call = mocks.last_call('POST', r'/api/messages/f1/react$')
    assert call['body'] == {'member_id': 'parent', 'emoji': '👍'}, call
    chip = "[...document.querySelectorAll('#msg-f1 button')].filter(b => !b.closest('#qr-f1') && b.textContent.includes('👍')).length === 1"
    settle(page, chip)
    assert page.evaluate(chip), 'the new reaction did not draw'
    # ⋯ still opens the message actions.
    page.locator('#msg-f2 button').filter(has_text='⋯').first.click()
    actions = page.locator('#ma-f2')
    assert actions.is_visible() and actions.get_by_role('button', name='Edit', exact=True).is_visible(), \
        '⋯ did not open the actions'
    page.locator('#msg-f2 button').filter(has_text='⋯').first.click()
    assert not actions.is_visible()
    # Compose: Send only with text; Enter still sends.
    send = page.locator('#thread-send')
    assert send.count() == 1, '#thread-send missing'
    assert send.get_attribute('aria-label') == 'Send' or norm(send.text_content()) == 'Send', send.evaluate('e => e.outerHTML')
    assert not send.is_visible(), 'Send shows with nothing typed'
    assert not page.evaluate("document.getElementById('thread-form').classList.contains('has-text')")
    assert not page.locator('#phone-voice-mic').is_visible(), 'the mic shows outside the Argyle thread'
    page.locator('#thread-input').fill('On my way')
    settle(page, "document.getElementById('thread-form').classList.contains('has-text')")
    assert page.evaluate("document.getElementById('thread-form').classList.contains('has-text')"), 'typing did not mark #thread-form.has-text'
    assert send.is_visible(), 'Send did not appear with text'
    shot(page, 'messages-thread-light.png')
    with page.expect_response(is_post('/api/channels/family/messages')):
        send.click()
    call = mocks.last_call('POST', r'/api/channels/family/messages$')
    assert call['body'] == {'sender_member_id': 'parent', 'body': 'On my way'}, call
    settle(page, "document.getElementById('thread-input').value === '' && !document.getElementById('thread-send').checkVisibility()")
    assert page.locator('#thread-input').input_value() == ''
    assert not send.is_visible(), 'Send stayed up after the message went'
    page.locator('#thread-input').fill('Leaving now')
    with page.expect_response(is_post('/api/channels/family/messages')):
        page.locator('#thread-input').press('Enter')
    assert mocks.last_call('POST', r'/api/channels/family/messages$')['body'] == \
        {'sender_member_id': 'parent', 'body': 'Leaving now'}
    settle(page, "document.getElementById('thread-messages').textContent.includes('Leaving now')")
    back_by_button(page)
    settle(page, "!document.querySelector('#channel-list > button.pwa-conv[data-channel=\"family\"] .pwa-conv-count')")
    assert conv(page, 'family').locator('.pwa-conv-count').count() == 0, 'the read family thread still counts unread'
    assert_list(page, mocks, 'parent')


def argyle_thread_has_mic(page, mocks):
    conv(page, 'dm_argyle').click()
    expect_thread(page, 'Argyle')
    settle(page, "document.getElementById('phone-voice-mic').checkVisibility()")
    assert page.locator('#phone-voice-mic').is_visible(), 'the mic is missing in the Argyle thread'
    try:
        page.locator('#tab-argyle').wait_for(state='hidden', timeout=2000)
    except Exception:
        pass
    assert not page.locator('#tab-argyle').is_visible(), 'the orb covers the Argyle composer'
    sub = top_screen(page).locator('.pwa-thread-head .pwa-thread-sub')
    assert norm(sub.text_content()) == ARGYLE_LINE, norm(sub.text_content())
    card = page.evaluate(CARD, 'a2')
    assert card and [b['text'] for b in card['buttons']] == ['Yes', 'No'], card
    back_by_button(page)
    settle(page, ORB_BACK, 3000)
    assert page.evaluate(ORB_BACK), 'the orb did not come back on the list'
    assert not page.locator('#phone-voice-mic').is_visible()


def thread_from_every_door(page, mocks):
    """Every way into a thread pushes the same screen; hardware Back closes it."""
    # 1. messageMember (a person chip), from My Day.
    page.locator('#tab-myday').click()
    page.wait_for_function("currentView === 'myday'")
    with page.expect_request(is_post_request('/api/channels/dm')):
        page.evaluate("messageMember('adult')")
    expect_thread(page, 'Robin Lee')
    assert mocks.last_call('POST', r'/api/channels/dm$')['body'] == {'member_id': 'parent', 'other_member_id': 'adult'}
    back_by_history(page)
    assert page.evaluate('currentView') == 'messages'
    # 2. A Moments ring (openMomentFromStrip): the thread, the moment on top.
    settle(page, "document.querySelectorAll('#moments-strip-row .pwa-mo:not(.add)').length === 2")
    with page.expect_request(is_messages_get('ev_soccer')):
        page.locator('#moments-strip-row .pwa-mo:not(.add)').first.click()
    expect_thread(page, 'Soccer practice')
    settle(page, "!!document.querySelector('.moment-overlay')")
    assert page.locator('.moment-overlay').count() >= 1, 'the ring did not open the moment over its thread'
    page.evaluate("document.querySelectorAll('.moment-overlay').forEach(o => o.remove())")
    back_by_history(page)
    # 3. New chat with one pill.
    page.locator('#messages-new-chat').click()
    page.wait_for_selector('#new-chat-modal', state='visible')
    page.locator('#new-chat-suggestions > button').filter(has_text='Robin Lee').first.click()
    with page.expect_request(is_post_request('/api/channels/dm')):
        page.locator('#new-chat-start').click()
    expect_thread(page, 'Robin Lee')
    assert not page.locator('#new-chat-modal').is_visible()
    assert mocks.last_call('POST', r'/api/channels/dm$')['body'] == {'member_id': 'parent', 'other_member_id': 'adult'}
    back_by_history(page)
    # 4. The overlay's "full conversation in Messages".
    page.locator('#tab-argyle').click()
    page.locator('#pwa-argyle-overlay').wait_for(state='visible', timeout=4000)
    page.locator('#pwa-argyle-overlay .pwa-argyle-to-messages').click()
    expect_thread(page, 'Argyle')
    assert not page.locator('#pwa-argyle-overlay').is_visible(), 'the overlay stayed over the thread'
    back_by_history(page)
    # 5. app_voice.js: setView('messages') then openChannel(id, channel).
    page.locator('#tab-myday').click()
    page.wait_for_function("currentView === 'myday'")
    voice_door = """async () => { setView('messages');
        await openChannel('dm_argyle', {id: 'dm_argyle', kind: 'dm', member_ids: ['parent', 'argyle']}); }"""
    page.evaluate(voice_door)
    expect_thread(page, 'Argyle')
    # The same door from INSIDE the Argyle thread: the mic's own voice turn
    # (ChauffeurPhoneVoice.start -> setView('messages') -> openChannel). The
    # turn must survive it: no stop() (generation bump), one screen.
    generation = page.evaluate('ChauffeurPhoneVoice.generation')
    page.evaluate(voice_door)
    expect_thread(page, 'Argyle')
    assert page.evaluate('ChauffeurPhoneVoice.generation') == generation, \
        "re-entering the open Argyle thread stopped the voice turn (the mic's own setView + openChannel)"
    back_by_history(page)


def leave_with_thread_open(page, mocks):
    conv(page, 'family').click()
    expect_thread(page, 'Family')
    page.locator('#tab-myday').click()
    page.wait_for_function("currentView === 'myday'")
    assert_thread_home(page)
    page.locator('#tab-messages').click()
    page.wait_for_function("currentView === 'messages'")
    assert_list(page, mocks, 'parent')
    assert page.evaluate('PwaNav.depth()') == 0, 'Messages came back on the thread, not the list'
    assert page.locator('#channel-list').is_visible()
    assert not page.locator('#thread-view').is_visible()


def widths_and_dark(page, mocks):
    assert_list(page, mocks, 'parent')
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        no_overflow(page)
        assert page.locator('#messages-container').evaluate('e => e.scrollWidth <= e.clientWidth')
    av = page.locator('#channel-list .pwa-conv-av').first.bounding_box()
    assert round(av['width']) == 52 and round(av['height']) == 52, av
    title = page.locator('#messages-container .pwa-msg-title')
    assert title.evaluate('e => getComputedStyle(e).fontSize') == '34px'
    light_ink = title.evaluate('e => getComputedStyle(e).color')
    page.evaluate("applyTheme('dark')")
    assert title.evaluate('e => getComputedStyle(e).color') != light_ink, 'the title ink did not change for dark'
    no_overflow(page)
    shot(page, 'messages-list-dark.png')
    conv(page, 'family').click()
    expect_thread(page, 'Family')
    settle(page, "!!document.getElementById('msg-f5')")
    for width in (360, 390):
        page.set_viewport_size({'width': width, 'height': 844})
        no_overflow(page)
        assert page.locator('#thread-messages').evaluate('e => e.scrollWidth <= e.clientWidth')
    shot(page, 'messages-thread-dark.png')
    back_by_button(page)
    page.evaluate("applyTheme('light')")
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    running = page.evaluate("""() => ['messages-container', 'pwa-stack'].map(id => document.getElementById(id))
        .filter(Boolean).flatMap(e => e.getAnimations({subtree: true})).filter(a => a.playState === 'running').length""")
    assert running == 0, running


# --- scenarios: the other profiles -------------------------------------------

def adult_list_and_argyle(page, mocks):
    """No Argyle DM yet: Argyle is still pinned (a synthetic row whose tap
    ensures the DM); no event thread, so no Add ring and the camera says to
    start from an event; no moments, so no Moments row."""
    open_messages(page)
    o = assert_list(page, mocks, 'adult')
    assert [r['id'] for r in o['pinned']] == ['family', None], o['pinned']
    synthetic = o['pinned'][1]
    assert (synthetic['kind'], synthetic['name'], synthetic['preview']) == ('argyle', 'Argyle', 'Ask me anything.'), synthetic
    assert [r['id'] for r in o['chats']] == ['dm_robin'], o['chats']
    assert not page.locator('#moments-strip').is_visible(), 'the Moments row shows with no moments'
    assert page.locator('#moments-strip-row .pwa-mo.add').count() == 0, 'an Add ring with no event thread'
    page.locator('#messages-add-moment').click()
    settle(page, "(document.getElementById('global-alert') || {}).textContent === "
                 "'Start from an event: open it from your day and tap Add a moment.'")
    assert norm(page.locator('#global-alert').text_content()) == \
        'Start from an event: open it from your day and tap Add a moment.', page.locator('#global-alert').text_content()
    assert page.locator('.pwa-prompt-overlay').count() == 0 and page.evaluate('PwaNav.depth()') == 0
    argyle = page.locator('#channel-list > button.pwa-conv').filter(has_text='Argyle').first
    with page.expect_request(is_post_request('/api/channels/dm')):
        argyle.click()
    expect_thread(page, 'Argyle')
    assert mocks.last_call('POST', r'/api/channels/dm$')['body'] == {'member_id': 'adult', 'other_member_id': 'argyle'}
    settle(page, "document.getElementById('phone-voice-mic').checkVisibility()")
    assert page.locator('#phone-voice-mic').is_visible(), 'the mic is missing in the new Argyle thread'
    back_by_button(page)
    conv(page, 'dm_robin').click()
    expect_thread(page, 'Alex Morgan')
    back_by_button(page)


def helper_share_mode(page, mocks):
    """A helper who cannot read event threads, handed one she is not in:
    the share-only surface, still a pushed screen."""
    open_messages(page)
    assert_list(page, mocks, 'helper')
    with page.expect_request(is_post_request('/api/channels/event')):
        page.evaluate("openEventThread('soccer', 'Soccer practice', %s)" % json.dumps(EVENT_END))
    expect_thread(page, 'Share a moment')
    call = mocks.last_call('POST', r'/api/channels/event$')
    assert call['body'] == {'event_id': 'soccer', 'title': 'Soccer practice', 'event_end': EVENT_END}, call
    assert page.evaluate('helperShareMode') is True
    text = norm(page.locator('#thread-messages').text_content())
    assert 'Share a photo or video from the event' in text, text
    assert page.locator('#thread-messages [id^="msg-"]').count() == 0, 'the share surface shows the thread'
    assert mocks.message_gets.get('ev_soccer', 0) == 0, 'the share surface read the thread'
    assert page.locator('#thread-attach-btn').is_visible(), 'no way to add a photo'
    page.locator('#thread-input').fill('Here they are')
    settle(page, "document.getElementById('thread-send').checkVisibility()")
    page.locator('#thread-send').click()
    want = 'Add a photo or video — text goes in your chat with the parents'
    settle(page, "(document.getElementById('global-alert') || {}).textContent === %s" % json.dumps(want))
    assert norm(page.locator('#global-alert').text_content()) == want, page.locator('#global-alert').text_content()
    assert not mocks.posts_to(r'/messages$'), mocks.calls
    assert page.locator('#thread-input').input_value() == 'Here they are'
    back_by_button(page)
    assert page.evaluate('helperShareMode') is False


def guest_lands_on_messages(page, mocks):
    settle(page, "currentView === 'messages'")
    assert page.evaluate('currentView') == 'messages', page.evaluate('currentView')
    settle(page, "document.querySelectorAll('#channel-list .pwa-conv-label').length > 0", timeout=8000)
    o = assert_list(page, mocks, 'guest')
    assert o['pinned'] == [], o['pinned']
    assert [r['id'] for r in o['chats']] == ['ev_soccer'], o['chats']
    names = [norm(t) for t in page.locator('#channel-list > button.pwa-conv .pwa-conv-name').all_text_contents()]
    assert not any(n.startswith('Argyle') for n in names), names
    assert not page.locator('#messages-add-moment').is_visible(), 'a guest has the Add a moment camera'
    conv(page, 'ev_soccer').click()
    expect_thread(page, 'Soccer practice')
    settle(page, "!!document.getElementById('msg-g1')")
    assert page.locator('#msg-g1').count() == 1, "the invited thread's history is missing"
    back_by_button(page)


def kid_unchanged(page, mocks):
    page.locator('#tab-messages').click()
    page.wait_for_function("currentView === 'messages'")
    settle(page, "document.querySelectorAll('#channel-list > button').length === 2")
    buttons = page.locator('#channel-list > button')
    assert buttons.count() == 2, buttons.count()
    assert page.locator('#channel-list > button.pwa-conv').count() == 0, 'a kid got the adult rows'
    assert page.locator('#channel-list > button.rounded-2xl').count() == 2, "the kid's rows are not today's cards"
    assert page.locator('#channel-list .pwa-conv-label').count() == 0, 'a kid got the Pinned / Chats labels'
    assert not page.locator('#messages-container .pwa-msg-title').is_visible()
    assert not page.locator('#messages-add-moment').is_visible()
    buttons.first.click()
    settle(page, "getComputedStyle(document.getElementById('thread-view')).display === 'flex'")
    assert page.evaluate('PwaNav.depth()') == 0, "a kid's thread went through PwaNav"
    assert page.locator('#pwa-stack .pwa-screen').count() == 0
    home = page.evaluate(THREAD_HOME)
    assert home == {'stack': False, 'messages': True, 'display': 'flex'}, home
    page.evaluate('closeThread()')
    settle(page, "getComputedStyle(document.getElementById('thread-view')).display === 'none'")
    assert page.evaluate(THREAD_HOME) == {'stack': False, 'messages': True, 'display': 'none'}
    assert page.evaluate('activeChannelId') is None


# --- the run -----------------------------------------------------------------

def wait_app(page):
    page.wait_for_function("""() => !!document.querySelector('#screen-schedule:not(.hidden)')
        || !!document.getElementById('pin-modal-skip')?.checkVisibility()""", timeout=20000)
    if page.locator('#pin-modal-skip').is_visible():
        page.locator('#pin-modal-skip').click()
    page.wait_for_selector('#screen-schedule:not(.hidden)')
    page.wait_for_function("typeof membersData !== 'undefined' && membersData.length > 0")


def boot(served, page, key, role, driver):
    failed_assets = []
    page.on('requestfailed', lambda request: failed_assets.append(
        (request.url, request.failure)) if request.resource_type in ('script', 'stylesheet') else None)
    page.on('response', lambda response: failed_assets.append(
        (response.url, response.status)) if response.request.resource_type in ('script', 'stylesheet')
        and response.status >= 400 else None)
    # Every 4xx/5xx with its URL, so an unmocked route names itself.
    page.on('response', lambda response: BAD_RESPONSES.append(
        (key, response.status, response.url.split('?')[0])) if response.status >= 400 else None)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.clock.set_fixed_time(NOW)

    def static_asset(route):
        if route.request.resource_type in ('script', 'stylesheet'):
            route.fulfill(response=route.fetch(max_retries=2))
        else:
            route.continue_()
    page.route('**/static/**', static_asset)
    token = storage.create_member_token(key)
    values = {'chauffeur_member_id': key, 'chauffeur_member_token': token,
              'chauffeur_member_token_for': key, 'chauffeur_view': 'myday', 'chauffeur_theme': 'light'}
    if driver:
        values['chauffeur_driver_id'] = driver
    page.add_init_script("if (!sessionStorage.getItem('chf_test_seeded')) { Object.entries(" + json.dumps(values)
                         + ").forEach(([k, v]) => localStorage.setItem(k, v)); sessionStorage.setItem('chf_test_seeded', '1'); }")
    mocks = Mocks(key, driver)
    mocks.install(page)
    if role == 'child':
        # Registered last, so the child's own day and routines win.
        from pwa_child_checks import install_child_data
        install_child_data(page, key, DAY)
    page.goto(served.url('app'), wait_until='domcontentloaded')
    wait_app(page)
    assert page.evaluate('selectedMemberId') == key
    assert page.evaluate('currentMemberRole()') == role
    if role in ('parent', 'adult'):
        settle(page, "!!document.querySelector('#myday-content .pwa-brief-greet')", timeout=8000)
    return mocks, failed_assets


def page_errors(served, key):
    errors = list(served.errors())
    if errors:
        errors = errors + [f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key]
    return errors


SCENARIOS = {
    'parent': [list_is_signals, search_filters, add_moment_ring, thread_is_messengers, argyle_thread_has_mic,
               thread_from_every_door, leave_with_thread_open, widths_and_dark],
    'adult': [adult_list_and_argyle],
    'helper': [helper_share_mode],
    'guest': [guest_lands_on_messages],
    'navigator': [kid_unchanged],
}


def run():
    global SHOTS
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
    output = os.environ.get('PWA_REVIEW_OUTPUT')
    if output:
        SHOTS = (Path(__file__).resolve().parent / 'probe_shots' / 'pwa_slice4'
                 if output.lower() in ('1', 'true', 'yes', 'on') else Path(output))
        SHOTS.mkdir(parents=True, exist_ok=True)
    try:
        for key, role, driver in PROFILES:
            if os.environ.get('PWA_REVIEW_PROFILE') and key != os.environ['PWA_REVIEW_PROFILE']:
                continue
            with served.browser(reduced_motion='reduce', has_touch=True) as page:
                mocks, failed_assets = boot(served, page, key, role, driver)
                for scenario in SCENARIOS[key]:
                    try:
                        scenario(page, mocks)
                    except Exception:
                        bad = sorted({f'{st} {url}' for k, st, url in BAD_RESPONSES if k == key})
                        print('FAIL', key, scenario.__name__, '| page errors:', list(served.errors())[:5],
                              '| 4xx/5xx:', bad[:8], flush=True)
                        raise
                    print('  ok', key, scenario.__name__, flush=True)
                errors = page_errors(served, key)
                assert not errors and not failed_assets, (key, errors, failed_assets)
                print('ok', key, flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    run()
