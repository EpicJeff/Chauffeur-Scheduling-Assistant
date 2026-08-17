"""The auth guard's classification table (services/auth.py, auth arc S1).

The load-bearing test is the first one: EVERY route the app registers must be
classified. That is the whole reason this file exists — the app reached 417
routes with five of them checked because nothing ever failed when a new route
arrived ungated. A table that has to be remembered is a table that drifts, so
the build breaks instead.

The rest pin the properties the guard's usefulness rests on: audit mode
refuses nothing, an unclassified route is never denied (our bug, not the
family's), tiers are sets rather than ranks, and the tunnel check fails toward
asking for credentials.

Run from chauffeur/:  python tests/test_auth.py
"""
import os

from harness import check  # noqa: F401  (isolates CHAUFFEUR_DATA_DIR)

from services import auth


def _app_routes():
    """Every (method, template) the app actually serves.

    Imports main, which is heavy — but asking the real router is the only way
    this test can be true. A hand-maintained list of routes to check against a
    hand-maintained table of routes would agree with itself forever."""
    import main
    out = []
    for route in main.app.routes:
        path = getattr(route, 'path', None)
        methods = getattr(route, 'methods', None)
        if not path or not methods:
            continue  # mounts (StaticFiles) and websockets carry no methods
        for m in methods:
            if m in ('HEAD', 'OPTIONS'):
                continue
            out.append((m, path))
    return out


def scenario_a_every_route_is_classified():
    """The guarantee: no route is public by accident, ever again."""
    unclassified = [(m, p) for m, p in _app_routes() if auth.resolve(m, p) is None]
    check(not unclassified,
          "routes with no tier in services/auth.RULES — classify them there, "
          "do not delete this test:\n  "
          + "\n  ".join(f"{m} {p}" for m, p in sorted(unclassified)))


def scenario_b_audit_mode_refuses_nothing():
    """S1 ships dark. Every route, no credentials, and not one refusal."""
    orig = auth.enforcing
    auth.enforcing = lambda: False
    try:
        for m, p in _app_routes():
            verdict = auth.check_request(m, p, {}, {})
            check(verdict is None,
                  f"audit mode refused {m} {p} — S1 must never deny")
    finally:
        auth.enforcing = orig


def scenario_c_enforcing_denies_the_unauthenticated():
    """And when it is flipped, it actually bites."""
    orig = auth.enforcing
    auth.enforcing = lambda: True
    try:
        # An anonymous caller off the tunnel gets 401 on an admin route...
        tunnel = {'cf-connecting-ip': '203.0.113.7'}
        verdict = auth.check_request('GET', '/api/download_db', tunnel, {})
        check(verdict and verdict['status'] == 401,
              f"the public internet could still download the database: {verdict}")
        # ...but the public allowlist stays open, or nobody can ever sign in.
        check(auth.check_request('POST', '/api/members/{member_id}/auth',
                                 tunnel, {}) is None,
              "sign-in was gated behind sign-in")
        check(auth.check_request('GET', '/health', tunnel, {}) is None,
              "health checks started needing credentials")
    finally:
        auth.enforcing = orig


def scenario_d_an_unclassified_route_is_recorded_not_denied():
    """A gap in OUR table must never cost the family a working app."""
    orig = auth.enforcing
    auth.enforcing = lambda: True
    auth.reset_audit()
    try:
        check(auth.check_request('GET', '/api/nothing/ever/registered/this',
                                 {'cf-connecting-ip': '203.0.113.7'}, {}) is None,
              "an unclassified route was denied — table gaps are our bug")
        rows = auth.audit_report()['would_deny']
        check(any(r['path'].endswith('registered/this') and not r['needs']
                  for r in rows),
              f"the unclassified route was not recorded for us to fix: {rows}")
    finally:
        auth.enforcing = orig
        auth.reset_audit()


def scenario_e_a_tier_is_a_set_not_a_rank():
    """The chores DATA is read by a parent AND by a panel; /api/v2/converse is
    the HA Assist webhook and no member's. Ranking these on one axis forces a
    lie. (S8 note: /api/chat itself moved OUT of this example — the Argyle bar
    on the PWA and the wall posts it as a member or a device, so robots-only
    there was the table being wrong, found by reading the callers.)

    Asserted against `/api/chores` rather than the `/chores` page, because the
    page is a public shell — see scenario_v for why that is deliberate."""
    chores = auth.resolve('GET', '/api/chores')
    check(auth.DEVICE in chores and auth.PARENT in chores,
          f"a wall panel lost the chores board: {chores}")
    chat = auth.resolve('POST', '/api/v2/converse')
    check(auth.SERVICE in chat and auth.MEMBER not in chat,
          f"/api/v2/converse is Assist's webhook, not a member's: {chat}")
    # Ordering is load-bearing: the specific rule must beat the prefix it
    # carves out of, or pin/clear silently inherits the members' tier.
    check(auth.resolve('POST', '/api/members/{member_id}/pin/clear') == auth.PARENTS,
          "pin/clear fell through to a weaker rule — check RULES order")


def scenario_e2_the_lanes_real_callers_actually_use():
    """S8's route-table fixes, each one found by reading the live callers
    rather than imagining them. A wall panel draws the music card (players,
    transport commands, artwork), holds the app's one WebSocket, paints trip
    backgrounds, and talks to Argyle — every one of those was classified for a
    caller that never makes the request, and would have died at the flip."""
    for m, p in (('GET', '/api/ha/media_players'),
                 ('POST', '/api/ha/media_players/{entity_id}/command'),
                 ('GET', '/api/ha/image64/{encoded}'),
                 ('WEBSOCKET', '/api/sendspin/ws'),
                 ('GET', '/api/unsplash/background'),
                 ('POST', '/api/chat'),
                 ('GET', '/api/v2/chat/stream')):
        tiers = auth.resolve(m, p) or frozenset()
        check(auth.DEVICE in tiers,
              f"{m} {p} refuses the wall panel that actually calls it: {tiers}")
    # The PWA's own Argyle bar posts as a member.
    check(auth.MEMBER in (auth.resolve('POST', '/api/chat') or frozenset()),
          "a signed-in member lost the Argyle bar")
    # ...and the carve-outs must not have opened the prefixes they sit above.
    check(auth.resolve('GET', '/api/ha/anything_else') == auth.PARENTS,
          "the music lanes opened the rest of /api/ha")
    check(auth.resolve('GET', '/api/unsplash/refresh') == auth.SIGNED_IN,
          "the background lane opened the rest of /api/unsplash")
    check(auth.resolve('POST', '/api/v2/converse') == auth.ROBOTS,
          "the chat stream lane opened the Assist webhook")


def scenario_e3_no_cors_wildcard_ever_again():
    """S8 took CORS off `*`. The old config allowed credentials, which
    Starlette honours by ECHOING any Origin — every website on earth could
    script this API with the visitor's tokens attached. Every real caller is
    same-origin or server-side, so there is no CORS middleware at all; a
    future native wrapper gets a deliberate allowlist, not a wildcard."""
    import main
    for m in main.app.user_middleware:
        check('CORSMiddleware' not in str(getattr(m, 'cls', '')),
              "CORS middleware is back — if a native app needs it, allowlist "
              "its origin explicitly, never '*' with credentials")


def scenario_f_the_tunnel_check_fails_toward_asking():
    """Absence of forwarding headers means the LAN; anything that looks
    forwarded is treated as the internet, never the other way round."""
    check(auth.arrived_via_tunnel({'cf-connecting-ip': '203.0.113.7'}),
          "a cloudflared request read as local")
    check(auth.arrived_via_tunnel({'x-forwarded-for': '203.0.113.7'}),
          "a forwarded request read as local")
    check(not auth.arrived_via_tunnel({}),
          "a direct LAN request read as external — this is Argyle's grace")
    # The grace is what keeps Argyle alive until S7; pin it so removing it is
    # a decision rather than an accident.
    who = auth.identify({}, {})
    check(who['tier'] == auth.SERVICE and who.get('via') == 'local-grace',
          f"the local-origin grace stopped applying: {who}")


# --- S2: identity comes from the token, not the body ------------------------

class _FakeStorage:
    """Two members and a token for one of them."""
    MEMBERS = {'kid': {'id': 'kid', 'name': 'Lily', 'role': 'child'},
               'mum': {'id': 'mum', 'name': 'Vovo', 'role': 'parent'}}
    TOKENS = {'tok-kid': 'kid', 'tok-mum': 'mum'}

    @classmethod
    def get_member(cls, mid):
        return cls.MEMBERS.get(mid)

    @classmethod
    def get_member_by_token(cls, token):
        return cls.MEMBERS.get(cls.TOKENS.get(token or ''))


def _with_fake_storage(fn):
    import sys
    real = sys.modules.get('services.storage')
    import services
    sys.modules['services.storage'] = _FakeStorage
    setattr(services, 'storage', _FakeStorage)
    try:
        return fn()
    finally:
        if real is not None:
            sys.modules['services.storage'] = real
            setattr(services, 'storage', real)


def scenario_g_the_token_beats_the_body():
    """The impersonation hole: a child could post as a parent by typing the
    parent's id into the request. The token settles it."""
    def body():
        acting = auth.acting_member({'x-member-token': 'tok-kid'}, {}, 'mum')
        check(acting['id'] == 'kid',
              f"the body's claim outranked the token: {acting}")
        check(acting['mismatch'],
              "acting as somebody else was not flagged as a mismatch")
        # Same person, no drama.
        agree = auth.acting_member({'x-member-token': 'tok-kid'}, {}, 'kid')
        check(agree['id'] == 'kid' and not agree['mismatch'],
              f"a member acting as themselves was flagged: {agree}")
    _with_fake_storage(body)


def scenario_h_no_token_still_works_but_is_counted():
    """The installed base on the day S2 ships sends no token anywhere. Refusing
    would log the family out of their own house to fix a bug they did not
    have; the fallback is honoured and COUNTED, and the count is what says
    when S8 may flip."""
    def body():
        auth.reset_audit()
        acting = auth.acting_member({}, {}, 'kid')
        check(acting['id'] == 'kid' and acting['source'] == 'claimed',
              f"the no-token fallback stopped working: {acting}")
        counts = auth.audit_report()['identity']
        check(counts['claimed'] == 1,
              f"the claim was not counted as migration debt: {counts}")
        auth.reset_audit()
    _with_fake_storage(body)


def scenario_i_impersonation_is_refused_only_when_enforcing():
    """Dark-ship discipline, same as the route guard: record now, refuse when
    the evidence says it is safe."""
    def body():
        acting = auth.acting_member({'x-member-token': 'tok-kid'}, {}, 'mum')
        orig = auth.enforcing
        auth.enforcing = lambda: False
        try:
            check(not auth.impersonation_refused(acting),
                  "S2 refused an act while shipping dark")
            auth.enforcing = lambda: True
            check(auth.impersonation_refused(acting),
                  "enforcement did not stop an impersonation")
        finally:
            auth.enforcing = orig
        auth.reset_audit()
    _with_fake_storage(body)


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]



def scenario_v_shells_are_public_and_the_data_is_not():
    """The rule that makes every way IN reachable.

    The sign-in overlay lives inside the admin pages and the pairing screen
    lives inside nav, so gating the PAGE means a refused browser gets a bare
    403 with no way to fix it: a wall panel could never show the code that
    would let it in, and a parent could never reach the box that would sign
    them in. Shells are public; the household's information is not."""
    for page in ('/app', '/home', '/chores', '/config', '/dashboard',
                 '/board/{slug}'):
        check(auth.resolve('GET', page) == auth.ANYONE,
              f"{page} is a shell and must stay reachable, or nobody can sign in")
    # ...and the data behind them is emphatically not public.
    for api, needs in (('/api/settings', auth.PARENT),
                       ('/api/messages/list', auth.MEMBER),
                       ('/api/download_db', auth.PARENT)):
        tiers = auth.resolve('GET', api) or frozenset()
        check(tiers and needs in tiers,
              f"{api} lost its gate when the shells opened: {tiers}")
        check(tiers != auth.ANYONE, f"{api} went public")


def scenario_only_a_refusal_pairing_could_fix_offers_pairing():
    """A bare 403 is not a reason to ask a screen to pair, and the panel proved
    it. nav's fetch wrapper offered the pairing overlay on ANY 401/403 — but
    most 403s in this app are domain rules, not authentication:

        "This chore isn't available to you"   "Not your routine"
        "Only children redeem rewards"        "Parent authorization required"

    All reachable from an interactive board. A child tapping a sibling's chore
    on the kitchen wall was answered with a full-screen six-digit pairing code,
    for a refusal pairing could not fix: a trusted device is the DEVICE tier,
    and no amount of it makes that chore theirs or the screen a parent.

    So the guard signs its own refusals with the tiers that WOULD have worked,
    and only `device` in that list is something a panel can act on.
    """
    import asyncio
    import main
    from starlette.requests import Request

    async def _guard(path, method='GET'):
        # Off the tunnel, so `identify` cannot hand out Argyle's local grace
        # and the caller is genuinely anonymous — same setup as scenario_c.
        req = Request({'type': 'http', 'method': method, 'path': path,
                       'headers': [(b'cf-connecting-ip', b'203.0.113.7')],
                       'query_string': b'', 'scheme': 'http',
                       'server': ('testserver', 80), 'root_path': ''})
        try:
            await main._auth_guard(req)
            return None
        except Exception as exc:                       # HTTPException
            return exc

    orig = auth.enforcing
    auth.enforcing = lambda: True
    try:
        # A board read: a panel IS allowed to draw this, so being trusted is
        # exactly what it lacks. Pairing is the right offer.
        exc = asyncio.run(_guard('/api/home_board/tiles'))
        check(exc is not None, "enforcing did not refuse an anonymous board read")
        header = (getattr(exc, 'headers', None) or {}).get('X-Auth-Refusal', '')
        check(auth.DEVICE in header.split(','),
              f"a refusal a panel could fix by pairing does not say so: {header}")
        # Administration: a paired screen is still not a parent, so offering
        # pairing here would send somebody through a setup that cannot help.
        exc = asyncio.run(_guard('/api/settings'))
        check(exc is not None, "enforcing did not refuse anonymous settings")
        header = (getattr(exc, 'headers', None) or {}).get('X-Auth-Refusal', '')
        check(auth.DEVICE not in header.split(','),
              f"a parent-only refusal invites a screen to pair: {header}")
    finally:
        auth.enforcing = orig
        auth.reset_audit()

    # The wrapper must key on the header, not on the status alone...
    nav = open(os.path.join(os.path.dirname(main.__file__),
                            'templates', 'nav.html'), encoding='utf-8').read()
    frag = nav[nav.index('attachDeviceToken'):]
    frag = frag[:frag.index('DOMContentLoaded')]
    check('X-Auth-Refusal' in frag,
          "the pairing prompt still fires on any 403, so a domain rule like "
          "\"not your routine\" shows a wall panel a setup screen")
    # ...and the tier name is a literal on the JS side, so it has to be pinned
    # to the constant, the same way the music card's sentinel is.
    check(f"includes('{auth.DEVICE}')" in frag,
          f"nav does not test for the {auth.DEVICE!r} tier by name — if the "
          f"constant moves, the panel silently stops asking to pair")


def scenario_the_guard_runs_on_a_websocket_too():
    """A global dependency runs on WEBSOCKET routes as well, and FastAPI only
    fills a `Request` parameter when the connection really is one:

        if dependant.request_param_name and isinstance(request, Request):
        elif dependant.websocket_param_name and isinstance(request, WebSocket):

    Neither branch matched a guard that asked for a `Request`, so it was called
    with no arguments — `TypeError: _auth_guard() missing 1 required positional
    argument` — and EVERY WebSocket handshake in the app 500'd from S1 onward.
    There is one WebSocket route here, so the entire visible symptom was that
    no screen and no phone could ever become a Music Assistant player, and a
    day went into blaming a tunnel that was carrying the upgrade perfectly.

    `HTTPConnection` is the common base of both and is filled unconditionally.
    Pinned two ways: the parameter FastAPI will fill, and the guard actually
    awaited on a websocket scope.
    """
    import asyncio
    import main
    from fastapi.dependencies.utils import get_dependant
    from starlette.requests import Request
    from starlette.websockets import WebSocket

    dep = get_dependant(path='/api/sendspin/ws', call=main._auth_guard)
    check(dep.http_connection_param_name,
          "the guard does not take an HTTPConnection, so FastAPI has nothing "
          "to fill on a websocket route and every handshake raises TypeError")
    check(not dep.request_param_name,
          "the guard asks for a Request — filled on http routes and silently "
          "absent on websocket ones, which is the bug itself")

    async def _recv():
        return {'type': 'websocket.connect'}

    async def _send(_message):
        return None

    base = {'headers': [], 'query_string': b'', 'scheme': 'ws',
            'server': ('testserver', 80), 'root_path': ''}
    ws = WebSocket({**base, 'type': 'websocket',
                    'path': '/api/sendspin/ws'}, _recv, _send)
    asyncio.run(main._auth_guard(ws))          # must not raise
    req = Request({**base, 'type': 'http', 'scheme': 'http',
                   'method': 'GET', 'path': '/api/home_board'})
    asyncio.run(main._auth_guard(req))         # and neither must the http one

    # Refusing a handshake needs a close code, not a status code. Dark today,
    # but S8 flips it and this arc's own rule is that the hole is closed
    # BEFORE the flip rather than at it.
    src = open(main.__file__, encoding='utf-8').read()
    guard = src[src.index('async def _auth_guard('):]
    guard = guard[:guard.index('\napp = FastAPI(')]
    check('WebSocketException' in guard,
          "a refused websocket would raise HTTPException, which is the same "
          "class of failure as the one this scenario exists for")


SCENARIOS = [v for k, v in sorted(globals().items()) if k.startswith("scenario_")]

if __name__ == "__main__":
    for fn in SCENARIOS:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(SCENARIOS)}/{len(SCENARIOS)} auth scenarios passed")
