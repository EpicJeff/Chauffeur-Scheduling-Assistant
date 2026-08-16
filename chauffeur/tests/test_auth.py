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
    """The chores DATA is read by a parent AND by a panel; /api/chat is
    Argyle's and not a member's. Ranking these on one axis forces a lie.

    Asserted against `/api/chores` rather than the `/chores` page, because the
    page is a public shell — see scenario_v for why that is deliberate."""
    chores = auth.resolve('GET', '/api/chores')
    check(auth.DEVICE in chores and auth.PARENT in chores,
          f"a wall panel lost the chores board: {chores}")
    chat = auth.resolve('POST', '/api/chat/message')
    check(auth.SERVICE in chat and auth.MEMBER not in chat,
          f"/api/chat is Argyle's lane, not a member's: {chat}")
    # Ordering is load-bearing: the specific rule must beat the prefix it
    # carves out of, or pin/clear silently inherits the members' tier.
    check(auth.resolve('POST', '/api/members/{member_id}/pin/clear') == auth.PARENTS,
          "pin/clear fell through to a weaker rule — check RULES order")


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
